"""Model-agnostic retrieval coverage records.

This module describes what was searched, inspected, and delivered.  It does
not interpret a search miss as a scientific absence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import ClassVar, Literal

CoverageStatus = Literal[
    "unsearched",
    "candidate_only",
    "searched_no_match",
    "partially_read",
    "read_complete",
    "render_delivered",
    "unavailable",
    "retrieval_incomplete",
]
SearchState = Literal[
    "unsearched",
    "candidate_only",
    "searched_no_match",
    "searched_match",
    "retrieval_incomplete",
]
ReadState = Literal["unread", "partially_read", "read_complete"]
RenderState = Literal["not_delivered", "render_delivered"]
RecoveryOperation = Literal["search", "read", "render"]

VALID_STATUSES = frozenset(
    {
        "unsearched",
        "candidate_only",
        "searched_no_match",
        "partially_read",
        "read_complete",
        "render_delivered",
        "unavailable",
        "retrieval_incomplete",
    }
)


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _unique_strings(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"{name} must be a tuple of non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


def _identity(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    """Coverage for one source or source projection."""

    source_id: str
    status: CoverageStatus
    source_available: bool = True
    search: SearchState = "unsearched"
    read: ReadState = "unread"
    render: RenderState = "not_delivered"
    refs: tuple[str, ...] = ()

    _allowed: ClassVar[frozenset[str]] = VALID_STATUSES

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        if self.status not in self._allowed:
            raise ValueError(f"invalid coverage status: {self.status!r}")
        if type(self.source_available) is not bool:
            raise ValueError("source_available must be a bool")
        if self.search not in {
            "unsearched",
            "candidate_only",
            "searched_no_match",
            "searched_match",
            "retrieval_incomplete",
        }:
            raise ValueError(f"invalid search state: {self.search!r}")
        if self.read not in {"unread", "partially_read", "read_complete"}:
            raise ValueError(f"invalid read state: {self.read!r}")
        if self.render not in {"not_delivered", "render_delivered"}:
            raise ValueError(f"invalid render state: {self.render!r}")
        _unique_strings(self.refs, "refs")
        if self.status == "unavailable" and self.source_available:
            raise ValueError("unavailable coverage requires source_available=False")
        if self.status == "candidate_only" and self.search not in {
            "candidate_only",
            "searched_match",
        }:
            raise ValueError("candidate_only requires a search match or candidate state")
        if self.status == "searched_no_match" and self.search != "searched_no_match":
            raise ValueError("searched_no_match requires searched_no_match search state")
        if self.status == "retrieval_incomplete" and self.search != "retrieval_incomplete":
            raise ValueError("retrieval_incomplete requires retrieval_incomplete search state")
        if self.status == "partially_read" and self.read != "partially_read":
            raise ValueError("partially_read requires partially_read read state")
        if self.status == "read_complete" and self.read != "read_complete":
            raise ValueError("read_complete requires read_complete read state")
        if self.status == "render_delivered" and self.render != "render_delivered":
            raise ValueError("render_delivered requires render_delivered render state")
        if self.status == "searched_no_match" and self.read != "unread":
            raise ValueError("a no-hit record cannot claim inspected content")

    @property
    def identity(self) -> str:
        return _identity(
            {
                "source_id": self.source_id,
                "status": self.status,
                "source_available": self.source_available,
                "search": self.search,
                "read": self.read,
                "render": self.render,
                "refs": self.refs,
            }
        )

    @property
    def absence_claim(self) -> bool:
        """Always false for retrieval misses: no-hit is not scientific absence."""

        return False


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    """A bounded, executable description of one retrieval operation."""

    operation: RecoveryOperation
    source_id: str
    start: int
    end: int
    max_items: int = 1

    def __post_init__(self) -> None:
        if self.operation not in {"search", "read", "render"}:
            raise ValueError(f"invalid recovery operation: {self.operation!r}")
        _text(self.source_id, "source_id")
        if (
            type(self.start) is not int
            or type(self.end) is not int
            or self.start < 0
            or self.end <= self.start
        ):
            raise ValueError("recovery bounds must be integers with 0 <= start < end")
        if type(self.max_items) is not int or self.max_items < 1:
            raise ValueError("max_items must be a positive integer")

    @property
    def identity(self) -> str:
        return _identity(
            {
                "operation": self.operation,
                "source_id": self.source_id,
                "start": self.start,
                "end": self.end,
                "max_items": self.max_items,
            }
        )


@dataclass(frozen=True, slots=True)
class RecoveryWindow:
    source_id: str
    start: int
    end: int
    actions: tuple[RecoveryAction, ...] = ()
    max_actions: int = 8

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        if (
            type(self.start) is not int
            or type(self.end) is not int
            or self.start < 0
            or self.end <= self.start
        ):
            raise ValueError("recovery bounds must be integers with 0 <= start < end")
        if type(self.max_actions) is not int or self.max_actions < 1:
            raise ValueError("max_actions must be a positive integer")
        if not isinstance(self.actions, tuple) or len(self.actions) > self.max_actions:
            raise ValueError("actions must be a tuple within max_actions")
        for action in self.actions:
            if not isinstance(action, RecoveryAction) or action.source_id != self.source_id:
                raise ValueError("every action must target the window source")
            if action.start < self.start or action.end > self.end:
                raise ValueError("action must fit inside recovery window")

    def bounded(self, limit: int | None = None) -> RecoveryWindow:
        bound = self.max_actions if limit is None else limit
        if type(bound) is not int or bound < 1:
            raise ValueError("limit must be a positive integer")
        return RecoveryWindow(
            self.source_id,
            self.start,
            self.end,
            self.actions[:bound],
            min(self.max_actions, bound),
        )

    @property
    def identity(self) -> str:
        return _identity(
            {
                "source_id": self.source_id,
                "start": self.start,
                "end": self.end,
                "actions": tuple(action.identity for action in self.actions),
                "max_actions": self.max_actions,
            }
        )


@dataclass(frozen=True, slots=True)
class PremiseCoverage:
    premise_id: str
    required: bool
    covered: bool
    missing: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.premise_id, "premise_id")
        if type(self.required) is not bool or type(self.covered) is not bool:
            raise ValueError("required and covered must be bools")
        _unique_strings(self.missing, "missing")
        _unique_strings(self.refs, "refs")
        if self.covered and self.missing:
            raise ValueError("covered premise cannot have missing requirements")
        if self.required and not self.covered and not self.missing:
            raise ValueError("an uncovered required premise must name what is missing")

    @property
    def identity(self) -> str:
        return _identity(
            {
                "premise_id": self.premise_id,
                "required": self.required,
                "covered": self.covered,
                "missing": self.missing,
                "refs": self.refs,
            }
        )


def bounded_recovery(actions: tuple[RecoveryAction, ...], limit: int) -> tuple[RecoveryAction, ...]:
    """Return at most ``limit`` actions, preserving their deterministic order."""

    if not isinstance(actions, tuple) or type(limit) is not int or limit < 1:
        raise ValueError("actions must be a tuple and limit must be a positive integer")
    return actions[:limit]
