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


FeedbackKind = Literal[
    "success",
    "researcher_gate",
    "input_rejection",
    "assessment_rejection",
    "transport_error",
    "tool_error",
    "condition",
]


@dataclass(frozen=True)
class ToolFeedback:
    kind: FeedbackKind
    fingerprint: str | None
    retryable: bool
    original: Mapping[str, Any]


def _validation_defects(tool: str, text: str) -> list[tuple[str, str]] | None:
    """Recognize the native call-validation envelope, never words in source prose."""
    lines = text.splitlines()
    if not lines:
        return None
    count, separator, suffix = lines[0].partition(" validation error")
    if (
        not separator
        or not count.isdecimal()
        or int(count) < 1
        or suffix != ("" if int(count) == 1 else "s") + f" for call[{tool}]"
    ):
        return None
    defects: list[tuple[str, str]] = []
    path = ""
    for line in lines[1:]:
        if line and not line[0].isspace():
            path = line
        elif path and " [type=" in line:
            code = line.partition(" [type=")[2].partition(",")[0].partition("]")[0]
            if code and all(char.isalnum() or char == "_" for char in code):
                defects.append((path, code))
    return sorted(defects) if len(defects) == int(count) else None


def tool_feedback(item: Mapping[str, Any]) -> ToolFeedback:
    """Classify host envelopes; retain originals separately from equivalence keys."""
    result = item.get("result") or {}
    payload = result.get("structured_content")
    payload = payload if isinstance(payload, Mapping) else {}
    tool = str(item.get("tool", ""))
    text = "\n".join(
        block.get("text", "") for block in result.get("content", []) if block.get("type") == "text"
    )
    defects = _validation_defects(tool, text) if not payload else None
    error = item.get("error")
    retryable = isinstance(error, Mapping) and error.get("retryable") is True
    kind: FeedbackKind = "success"
    normalized: Any = None
    if defects is not None:
        kind, normalized = "input_rejection", defects
    elif error:
        kind, normalized = "transport_error", error
    elif item.get("status") == "failed" or result.get("isError") or result.get("is_error"):
        kind, normalized = "tool_error", {"payload": payload, "text": text}
    else:
        head = payload.get("head") or {}
        action = head.get("next_action") or payload.get("continuation") or {}
        outcome = payload.get("outcome")
        if outcome == "review_required" or action.get("authority") == "researcher":
            kind = "researcher_gate"
        elif outcome in {"repair", "error", "condition"}:
            condition = payload.get("condition") or {}
            code = condition.get("code") if isinstance(condition, Mapping) else None
            kind = (
                "input_rejection"
                if code == "invalid_request"
                else "assessment_rejection"
                if outcome == "repair"
                else "condition"
                if outcome == "condition"
                else "tool_error"
            )
            normalized = {
                key: value for key, value in payload.items() if key not in {"head", "counters"}
            }
    fingerprint = (
        json.dumps([tool, kind, normalized], sort_keys=True) if normalized is not None else None
    )
    return ToolFeedback(kind, fingerprint, retryable, item)


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
    feedback: list[dict[str, Any]] = []
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
        classified = tool_feedback(item)
        feedback.append(
            {
                "kind": classified.kind,
                "retryable": classified.retryable,
                "fingerprint": classified.fingerprint,
                "original": item,
            }
        )
        if classified.fingerprint:
            failures.append(classified.fingerprint)
        else:
            # A status-only boundary read must not erase an error from the prior turn.
            if item.get("tool") != "get_status":
                failures.append("")
            if item.get("tool") != "get_status":
                work.add(json.dumps([item.get("tool"), item.get("arguments")], sort_keys=True))
    return {
        "sessions": sorted(sessions),
        "work": work,
        "failures": failures,
        "feedback": feedback,
        "calls": calls,
        "usage": usage,
    }


def finalized_artifact(status: Mapping[str, Any], traces: list[Path]) -> dict[str, Any] | None:
    """Recover only a successful finalization receipt matching authoritative revision."""
    head = status.get("head") or status
    if head.get("phase") != "finalized":
        return None
    for trace in reversed(traces):
        for line in reversed(trace.read_text(encoding="utf-8").splitlines()):
            row = json.loads(line)
            item = row.get("item", {})
            if (
                row.get("type") != "item.completed"
                or item.get("type") != "mcp_tool_call"
                or item.get("tool") != "finalize_batch"
                or item.get("status") == "failed"
                or item.get("error")
            ):
                continue
            payload = (item.get("result") or {}).get("structured_content") or {}
            receipt_head = payload.get("head") or {}
            if (
                payload.get("outcome") == "success"
                and receipt_head.get("phase") == "finalized"
                and receipt_head.get("state_revision") == head.get("state_revision")
                and isinstance(head.get("state_revision"), int)
            ):
                artifact = (payload.get("data") or {}).get("artifact")
                if isinstance(artifact, dict):
                    return artifact
    return None


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
