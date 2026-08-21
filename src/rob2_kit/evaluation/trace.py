"""Reject release-gate trace signatures, independently of host prose."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TraceEvent:
    kind: str
    operation: str = ""
    status: str = ""
    detail: str = ""
    durable_status: str = ""


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
