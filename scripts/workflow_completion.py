"""Opt-in host ownership of one workflow across bounded same-session turns."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Boundary = Literal["complete", "waiting_for_user", "blocked", "unfinished", "aborted"]


@dataclass(frozen=True)
class AssessmentScope:
    """Prospectively bound operational scope, never preferred answers or labels."""

    trial_id: str
    result_identity: str
    domain_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        valid_domains = {
            "domain:randomization",
            "domain:deviations",
            "domain:missing",
            "domain:measurement",
            "domain:selection",
        }
        if (
            not isinstance(self.trial_id, str)
            or not self.trial_id.strip()
            or not isinstance(self.result_identity, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.result_identity)
            or not self.domain_ids
            or not all(isinstance(d, str) for d in self.domain_ids)
            or len(set(self.domain_ids)) != len(self.domain_ids)
            or not set(self.domain_ids) <= valid_domains
        ):
            raise ValueError("invalid bound assessment completion scope")

    @classmethod
    def load(cls, path: Path) -> AssessmentScope:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or set(value) != {
            "trial_id",
            "result_identity",
            "domain_ids",
        }:
            raise ValueError("completion scope requires only Trial, Result identity and Domain IDs")
        if not isinstance(value["domain_ids"], list):
            raise ValueError("completion Domain IDs must be an array")
        return cls(value["trial_id"], value["result_identity"], tuple(value["domain_ids"]))


def scoped_status(
    status: Mapping[str, Any],
    scope: AssessmentScope,
    *,
    result_identity: str | None,
    domain_records: Mapping[str, Any],
    traces: Sequence[Path] = (),
    outside_scope_baseline: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Adapt authoritative current state to a requested partial assessment goal.

    Canonical records/Result are supplied by the existing host state reader. No
    judgments, source prose or inferred reading claims enter host continuations.
    """
    current = dict(status)
    head = dict(current.get("head") or current)
    action = head.get("next_action") or current.get("continuation") or {}
    if action.get("authority") == "researcher" or current.get("outcome") in {"error", "condition"}:
        return current
    if result_identity != scope.result_identity:
        return {
            **current,
            "outcome": "condition",
            "condition": {
                "code": "completion_scope_changed",
                "detail": "The bound selected Result is unavailable or changed.",
            },
        }
    if outside_scope_baseline is not None:
        outside = {
            key: record.get("identity")
            for key, record in domain_records.items()
            if key.startswith(scope.trial_id + ":")
            and isinstance(record, Mapping)
            and record.get("domain_id") not in scope.domain_ids
        }
        if outside != outside_scope_baseline:
            return {
                **current,
                "outcome": "condition",
                "condition": {
                    "code": "completion_scope_violated",
                    "detail": "Canonical checkpoints outside the requested scope changed.",
                },
            }
    accepted = {}
    for domain in scope.domain_ids:
        record = domain_records.get(f"{scope.trial_id}:{domain}")
        if (
            isinstance(record, Mapping)
            and record.get("result_identity") == scope.result_identity
            and record.get("trial_id") == scope.trial_id
            and record.get("domain_id") == domain
            and isinstance(record.get("identity"), str)
        ):
            accepted[domain] = record["identity"]
    missing = [domain for domain in scope.domain_ids if domain not in accepted]
    reading = (current.get("main_report_reading") or {}).get(scope.trial_id, {})
    reading_complete = (
        reading.get("status") in {"complete", "budget_limited"}
        and reading.get("required_range_count") == 0
    )
    current["host_scope"] = {
        "trial_id": scope.trial_id,
        "result_identity": scope.result_identity,
        "domain_ids": list(scope.domain_ids),
        "accepted": accepted,
        "missing": missing,
        "reading_complete": reading_complete,
        "complete": not missing and reading_complete,
    }
    action = {
        "operation": "get_domain_context",
        "authority": "host",
        "trial_id": scope.trial_id,
        "domain_id": (missing or list(scope.domain_ids))[0],
    }
    # Reuse the current native receipt's actionable cursor without consuming it.
    delivered = set()
    for path in traces:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            item = row.get("item", {})
            if (
                row.get("type") != "item.completed"
                or item.get("type") != "mcp_tool_call"
                or item.get("server") != "rob2"
            ):
                continue
            payload = (item.get("result") or {}).get("structured_content") or {}
            receipt_head = payload.get("head") or {}
            candidate = receipt_head.get("next_action") or {}
            data = payload.get("data") or {}
            page = data.get("context_page") or {}
            if (
                payload.get("outcome") == "success"
                and candidate.get("authority") == "host"
                and candidate.get("trial_id") == scope.trial_id
                and candidate.get("domain_id") in missing
                and receipt_head.get("state_revision") == head.get("state_revision")
            ):
                action = candidate
            if page.get("domain_id") in scope.domain_ids and page.get("trial_id") == scope.trial_id:
                if isinstance(page.get("snapshot_digest"), str) and isinstance(
                    page.get("index"), int
                ):
                    delivered.add((page["domain_id"], page["snapshot_digest"], page["index"]))
    current["continuation"] = action
    if "head" in current:
        current["head"] = {**head, "next_action": action}
    current["host_progress"] = {"accepted": accepted, "context_pages": sorted(delivered)}
    return current


def scope_verified(status: Mapping[str, Any], scope: AssessmentScope) -> bool:
    value = status.get("host_scope") or {}
    return (
        value.get("trial_id") == scope.trial_id
        and value.get("result_identity") == scope.result_identity
        and value.get("domain_ids") == list(scope.domain_ids)
        and value.get("complete") is True
    )


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


def boundary(
    status: Mapping[str, Any], *, verified: bool, scope: AssessmentScope | None = None
) -> Boundary:
    """Only authoritative state and verification determine a completion boundary."""
    head = status.get("head") or status
    phase = head.get("phase")
    action = head.get("next_action") or status.get("continuation")
    if isinstance(action, Mapping) and action.get("authority") == "researcher":
        return "waiting_for_user"
    if status.get("outcome") in {"error", "condition"}:
        return "blocked"
    if scope is not None and verified:
        return "complete"
    if phase == "finalized":
        return "complete" if verified else "blocked"
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
    completed_turns = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("type") == "thread.started":
            sessions.add(row["thread_id"])
        if row.get("type") == "turn.completed":
            completed_turns += 1
            for key, value in row.get("usage", {}).items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
        item = row.get("item", {})
        if (
            row.get("type") != "item.completed"
            or item.get("type") != "mcp_tool_call"
            or item.get("server") != "rob2"
        ):
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
        "completed_turns": completed_turns,
        "usage_receipt_available": completed_turns > 0 and bool(usage),
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
                or item.get("server") != "rob2"
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
    scope: AssessmentScope | None = None,
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
        state = boundary(status, verified=verify(status), scope=scope)
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
                "completed_turns": facts["completed_turns"],
                "usage_receipt_available": facts["usage_receipt_available"],
            }
        )
        if not session_valid:
            return {
                "boundary": "aborted",
                "reason": "session binding changed or missing",
                "turns": turns,
                "usage": usage,
            }
        state = boundary(status, verified=verify(status), scope=scope)
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
        if scope is not None:
            prompt = (
                "The requested assessment scope is unfinished. Resume this SAME session. "
                "Recover current selected-Result, required-reading and Domain context through "
                "native tools; consume actionable reading/context continuations. Continue only "
                "the bound Trial/Result and requested Domains; no other Domains, review, closure "
                "or finalization. Stop for "
                "an actual researcher action or unrecoverable blocker. Bound scope: "
                + json.dumps(
                    {
                        "trial_id": scope.trial_id,
                        "result_identity": scope.result_identity,
                        "domain_ids": scope.domain_ids,
                    },
                    sort_keys=True,
                )
                + "; pending authorized action: "
                + json.dumps(action, sort_keys=True)
            )
        else:
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


def receipt_reading_report(traces: Sequence[Path]) -> dict[str, Any]:
    """Verify required-window delivery from successful native receipts, never prose.

    Full-page/all-source claims need explicitly listed required ranges. Uncertified
    partial physical-line fragments do not establish complete line delivery.
    """
    required: set[tuple[str, str, int, int, int]] = set()
    covered: dict[tuple[str, str, int], list[tuple[int, int]]] = {}
    uncertain_fragments = 0
    truncated_requirements = False
    for path in traces:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            item = row.get("item", {})
            if (
                row.get("type") != "item.completed"
                or item.get("type") != "mcp_tool_call"
                or item.get("server") != "rob2"
            ):
                continue
            payload = (item.get("result") or {}).get("structured_content") or {}
            if payload.get("outcome") != "success":
                continue
            data = payload.get("data") or {}
            recovery = data.get("reading_recovery") or {}
            trial = recovery.get("trial_id") or item.get("arguments", {}).get("trial_id")
            if not isinstance(trial, str):
                continue
            windows = recovery.get("windows", ())
            count = recovery.get("window_count", len(windows))
            if isinstance(count, int) and count > len(windows):
                truncated_requirements = True
            for window in windows:
                values = (
                    window.get("source_id"),
                    window.get("page"),
                    window.get("start_line"),
                    window.get("end_line"),
                )
                if isinstance(values[0], str) and all(isinstance(v, int) for v in values[1:]):
                    required.add((trial, *values))
            if item.get("tool") != "read_pages":
                continue
            for page in data.get("pages", ()):
                if not page.get("passage_ref"):
                    uncertain_fragments += 1
                    continue
                source, number = page.get("source_id"), page.get("page")
                start, end = page.get("returned_start_line"), page.get("returned_end_line")
                if isinstance(source, str) and all(
                    isinstance(v, int) for v in (number, start, end)
                ):
                    covered.setdefault((trial, source, number), []).append((start, end))
    missing = []
    for trial, source, page, start, end in sorted(required):
        cursor = start
        for first, last in sorted(covered.get((trial, source, page), ())):
            if first > cursor:
                missing.append(
                    {
                        "trial_id": trial,
                        "source_id": source,
                        "page": page,
                        "start_line": cursor,
                        "end_line": min(first - 1, end),
                    }
                )
            cursor = max(cursor, last + 1)
            if cursor > end:
                break
        if cursor <= end:
            missing.append(
                {
                    "trial_id": trial,
                    "source_id": source,
                    "page": page,
                    "start_line": cursor,
                    "end_line": end,
                }
            )
    return {
        "basis": "successful native required-window and numbered-text receipts",
        "model_narrative_consulted": False,
        "required_window_count": len(required),
        "complete": bool(required) and not missing and not truncated_requirements,
        "missing_windows": missing,
        "uncertified_partial_fragments": uncertain_fragments,
        "truncated_requirement_envelope_seen": truncated_requirements,
        "limitation": "Delivery is not comprehension; unlisted sources/windows are not certified.",
    }
