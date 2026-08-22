"""Reject release-gate trace signatures, independently of host prose."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TraceEvent:
    kind: str
    operation: str = ""
    status: str = ""
    detail: str = ""
    durable_status: str = ""


def parse_trace(value: object) -> tuple[TraceEvent, ...]:
    """Parse the retained, privacy-safe trace wire shape."""

    if isinstance(value, dict):
        if set(value) != {"events"}:
            raise ValueError("trace input must be an event list")
        value = value["events"]
    if not isinstance(value, list):
        raise ValueError("trace input must be an event list")
    fields = {"kind", "operation", "status", "detail", "durable_status"}
    events: list[TraceEvent] = []
    for row in value:
        if not isinstance(row, dict) or not set(row) <= fields:
            raise ValueError("trace event has an invalid shape")
        if not isinstance(row.get("kind"), str) or not row["kind"]:
            raise ValueError("trace event kind is missing")
        if any(not isinstance(row.get(field, ""), str) for field in fields - {"kind"}):
            raise ValueError("trace event fields must be strings")
        events.append(TraceEvent(**row))
    return tuple(events)


def read_trace(path: str | Path) -> tuple[TraceEvent, ...]:
    try:
        return parse_trace(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("trace input is unavailable or invalid") from error


_BAD = (
    "not json serializable",
    "serialization",
    "schema validation",
    "validationerror",
    "identity guessed",
    "guessed identity",
    "invalid transition",
    "transition_consumed_mismatch",
)
_CLAIM_WORDS = (
    "assessment complete",
    "assessment completed",
    "review completed",
    "approved result",
)


def check_trace(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> tuple[str, ...]:
    failures: list[str] = []
    seen_defects: set[tuple[str, str]] = set()
    for event in events:
        detail = event.detail.casefold()
        if any(signature in detail for signature in _BAD):
            failures.append(f"prohibited trace signature: {event.detail}")
        if event.kind == "defect":
            key = (event.operation, detail)
            if key in seen_defects:
                failures.append(f"repeated defect: {event.operation}")
            seen_defects.add(key)
        if (
            event.kind == "claim"
            and any(word in detail for word in _CLAIM_WORDS)
            and event.durable_status not in {"assessed", "finalized"}
        ):
            failures.append("unsupported completed-assessment claim")
        if event.kind == "prose" and event.durable_status and event.durable_status not in detail:
            failures.append("model prose contradicts authoritative status")
        if event.kind == "transition" and event.status in {"invalid", "rejected"}:
            failures.append("invalid transition attempted")
    return tuple(failures)


def check_required_operations(
    events: tuple[TraceEvent, ...] | list[TraceEvent],
    required: tuple[tuple[str, str], ...],
    terminal: tuple[str, str] = ("preapproval_terminal", "acknowledged"),
) -> tuple[str, ...]:
    """Require named operations before an acknowledged preapproval terminal."""

    terminal_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.kind == "operation" and (event.operation, event.status) == terminal
        ),
        None,
    )
    if terminal_index is None:
        return ("required preapproval terminal is absent",)
    prior = {
        (event.operation, event.status)
        for event in events[:terminal_index]
        if event.kind == "operation"
    }
    return tuple(
        f"required operation is absent before preapproval terminal: {operation}/{status}"
        for operation, status in required
        if (operation, status) not in prior
    )
