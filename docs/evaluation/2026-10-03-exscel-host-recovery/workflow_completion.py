"""Opt-in host ownership of one workflow across bounded same-session turns."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Boundary = Literal["complete", "waiting_for_user", "blocked", "unfinished", "aborted"]


@dataclass(frozen=True)
class Turn:
    exit_code: int
    trace: Path


def boundary(status: Mapping[str, Any], *, verified: bool) -> Boundary:
    """Only authoritative state and verification determine a completion boundary."""
    head = status.get("head") or status
    phase = head.get("phase")
    action = head.get("next_action") or status.get("continuation")
    if phase == "finalized":
        return "complete" if verified else "blocked"
    if isinstance(action, Mapping) and action.get("authority") == "researcher":
        return "waiting_for_user"
    if status.get("outcome") in {"error", "condition"}:
        return "blocked"
    if not isinstance(action, Mapping) or action.get("authority") != "host":
        return "blocked"
    return "unfinished"


def trace_facts(path: Path) -> dict[str, Any]:
    """Count every turn; distinguish successful work from repeated failed receipts."""
    sessions: set[str] = set()
    work: set[str] = set()
    failures: list[str] = []
    calls = 0
    usage: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("type") == "thread.started":
            sessions.add(row["thread_id"])
        if row.get("type") == "turn.completed":
            for key, value in row.get("usage", {}).items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
        item = row.get("item", {})
        if row.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
            continue
        calls += 1
        result = item.get("result") or {}
        payload = result.get("structured_content") or {}
        failed = (
            item.get("status") == "failed"
            or bool(item.get("error"))
            or payload.get("outcome") in {"repair", "error", "condition"}
        )
        if failed:
            failures.append(
                json.dumps([item.get("tool"), result, item.get("error")], sort_keys=True)
            )
        else:
            failures.append("")  # A successful intervening call breaks consecutive failure.
            if item.get("tool") != "get_status":
                work.add(json.dumps([item.get("tool"), item.get("arguments")], sort_keys=True))
    return {
        "sessions": sorted(sessions),
        "work": work,
        "failures": failures,
        "calls": calls,
        "usage": usage,
    }


def drive(
    invoke: Callable[[str | None, str, float, int], Turn],
    read_status: Callable[[], dict[str, Any]],
    verify: Callable[[dict[str, Any]], bool],
    *,
    prompt: str,
    session: str | None,
    max_resumes: int,
    no_progress_limit: int,
    wall_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Never approve, repair, choose answers or create a replacement session."""
    if max_resumes < 0 or no_progress_limit < 1 or wall_seconds <= 0:
        raise ValueError("invalid completion budget")
    started = clock()
    status = read_status()
    no_progress = 0
    last_failure = ""
    identical_failures = 0
    turns: list[dict[str, Any]] = []
    usage: dict[str, int] = {}
    for index in range(max_resumes + 1):
        state = boundary(status, verified=verify(status))
        if state != "unfinished":
            return {
                "boundary": state,
                "reason": "authoritative workflow boundary",
                "turns": turns,
                "usage": usage,
            }
        remaining = wall_seconds - (clock() - started)
        if remaining <= 0:
            return {
                "boundary": "aborted",
                "reason": "shared wall budget",
                "turns": turns,
                "usage": usage,
            }
        before = json.dumps(status, sort_keys=True)
        turn = invoke(session, prompt, remaining, index)
        facts = trace_facts(turn.trace)
        sessions = facts["sessions"]
        session_valid = len(sessions) == 1 and (session is None or sessions[0] == session)
        if session_valid:
            session = sessions[0]
        status = read_status()
        # Exclude volatile timestamps/notes: workflow identity and returned action,
        # delivered reading ranges and adapter-supplied durable delivery progress.
        progress_keys = (
            "phase",
            "state_revision",
            "continuation",
            "main_report_reading",
            "host_progress",
        )
        prior = json.loads(before)
        progress = any(prior.get(k) != status.get(k) for k in progress_keys)
        no_progress = 0 if progress else no_progress + 1
        for failure in facts["failures"]:
            identical_failures = (
                identical_failures + 1
                if failure and failure == last_failure
                else int(bool(failure))
            )
            last_failure = failure
        for key, value in facts["usage"].items():
            usage[key] = usage.get(key, 0) + value
        turns.append(
            {
                "index": index,
                "session": session,
                "trace": str(turn.trace),
                "exit_code": turn.exit_code,
                "status": status,
                "progress": progress,
                "calls": facts["calls"],
                "usage": facts["usage"],
            }
        )
        if not session_valid:
            return {
                "boundary": "aborted",
                "reason": "session binding changed or missing",
                "turns": turns,
                "usage": usage,
            }
        state = boundary(status, verified=verify(status))
        if turn.exit_code != 0:
            return {
                "boundary": "aborted",
                "reason": f"host exit {turn.exit_code}",
                "turns": turns,
                "usage": usage,
            }
        if state != "unfinished":
            return {
                "boundary": state,
                "reason": "authoritative workflow boundary",
                "turns": turns,
                "usage": usage,
            }
        if no_progress >= no_progress_limit or identical_failures >= 2:
            return {
                "boundary": "unfinished",
                "reason": "bounded no-progress or repeated-error stop",
                "turns": turns,
                "usage": usage,
            }
        head = status.get("head") or status
        action = head.get("next_action") or status.get("continuation")
        prompt = (
            "The requested workflow is unfinished. Resume this SAME assessment/session. "
            "Call get_status, recover current working context and follow its authoritative "
            "pending action through review, closure and finalize_batch. Do not stop at a "
            "successful Domain save or incomplete pagination. Preserve unresolved scientific "
            "facts; do not infer answers from this host continuation. Stop for an actual "
            "researcher action, unrecoverable blocker or budget. Pending action snapshot: "
            + json.dumps(action, sort_keys=True)
        )
    return {
        "boundary": "unfinished",
        "reason": "same-session resume allowance exhausted",
        "turns": turns,
        "usage": usage,
    }
