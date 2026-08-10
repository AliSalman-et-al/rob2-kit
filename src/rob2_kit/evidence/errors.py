"""Typed failures raised by the bounded evidence retrieval boundary.

The search index and the application engine deliberately expose failures as
small, stable values rather than relying on exception-message inspection at a
transport boundary.  The exception text remains useful for logs and Python
callers, while ``code``, ``field``, ``message``, and recovery metadata are the
contract consumed by MCP hosts.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pydantic import BaseModel


class FieldViolation(NamedTuple):
    """One field-level validation failure within a possibly-batched request."""

    field: str | None
    message: str


class RetrievalErrorCode(StrEnum):
    """Stable machine-readable recovery classes for bounded retrieval."""

    STALE_CURSOR = "stale_cursor"
    CURSOR_SCOPE_MISMATCH = "cursor_scope_mismatch"
    UNKNOWN_CURSOR = "unknown_cursor"
    SCOPE_MISMATCH = "scope_mismatch"
    STALE_WORK_TOKEN = "stale_work_token"
    REPROCESSING_REQUIRED = "reprocessing_required"
    INVALID_REQUEST = "invalid_request"
    OPERATIONAL = "retrieval_operational"


_DEFAULT_RECOVERY: dict[RetrievalErrorCode, tuple[str, ...]] = {
    RetrievalErrorCode.STALE_CURSOR: (
        "discard the cursor",
        "retry the first bounded page with the active WorkToken",
    ),
    RetrievalErrorCode.CURSOR_SCOPE_MISMATCH: (
        "discard the cursor",
        "restart the bounded page with the current WorkToken and scope",
    ),
    RetrievalErrorCode.UNKNOWN_CURSOR: (
        "re-copy the exact value from the response that returned it",
        "if it was never returned by this server, request a fresh one",
    ),
    RetrievalErrorCode.SCOPE_MISMATCH: (
        "use only IDs issued by the active WorkToken",
        "retry with the issued unit or scope",
    ),
    RetrievalErrorCode.STALE_WORK_TOKEN: (
        "call continue_run",
        "copy the current submit_domain_evidence WorkToken",
    ),
    RetrievalErrorCode.REPROCESSING_REQUIRED: (
        "reprocess the current Trial Sources and Parses",
        "resume only after the current-schema evidence index is materialized",
    ),
    RetrievalErrorCode.INVALID_REQUEST: (
        "inspect the field-level validation detail",
        "retry only the corrected request",
    ),
    RetrievalErrorCode.OPERATIONAL: (
        "retry the bounded retrieval once",
        "if repeated, report the retrieval limitation",
    ),
}


class RetrievalFailure(ValueError):
    """Base typed failure for expected retrieval boundary conditions."""

    code: RetrievalErrorCode
    field: str | None
    message: str
    recovery: tuple[str, ...]
    next_actions: tuple[str, ...]
    violations: tuple[FieldViolation, ...]

    def __init__(
        self,
        *,
        code: RetrievalErrorCode,
        message: str,
        field: str | None = None,
        recovery: Iterable[str] | None = None,
        next_actions: Iterable[str] | None = None,
        violations: Iterable[FieldViolation] | None = None,
    ) -> None:
        self.code = RetrievalErrorCode(code)
        self.field = field
        self.message = message
        self.recovery = tuple(recovery or _DEFAULT_RECOVERY[self.code])
        self.next_actions = tuple(next_actions or self.recovery)
        self.violations = (
            tuple(violations) if violations is not None else (FieldViolation(field, message),)
        )
        super().__init__(message)

    @property
    def next_action(self) -> str:
        """The first safe action, for hosts that expose a singular action."""

        return self.next_actions[0]


class InvalidRetrievalRequest(RetrievalFailure):
    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        recovery: Iterable[str] | None = None,
        violations: Iterable[FieldViolation] | None = None,
    ) -> None:
        super().__init__(
            code=RetrievalErrorCode.INVALID_REQUEST,
            field=field,
            message=message,
            recovery=recovery,
            violations=violations,
        )


class StaleCursor(RetrievalFailure):
    def __init__(
        self,
        message: str,
        *,
        field: str | None = "cursor",
        recovery: Iterable[str] | None = None,
    ) -> None:
        super().__init__(
            code=RetrievalErrorCode.STALE_CURSOR,
            field=field,
            message=message,
            recovery=recovery,
        )


class StaleSearchContinuation(StaleCursor):
    """A v2 Search continuation or page handle no longer names this view.

    This remains a stale-cursor condition at the transport boundary, while
    giving in-process callers a precise type for the v2 navigation seam.
    """

    def __init__(self, message: str, *, field: str | None = "continuation") -> None:
        super().__init__(message, field=field)


class SearchPolicyMismatch(StaleSearchContinuation):
    """A v2 continuation was issued under a different engine-owned policy."""

    def __init__(self, message: str = "continuation belongs to a different search policy") -> None:
        super().__init__(message, field="continuation")


class UnknownCursor(RetrievalFailure):
    """A cursor/handle token that was never issued by this server, or is malformed.

    Distinct from :class:`StaleCursor`: a stale cursor was issued but its
    bound identity no longer matches; an unknown cursor has no matching row
    at all -- most often a transcription error (ADR-0011).
    """

    def __init__(self, message: str, *, field: str | None = "cursor") -> None:
        super().__init__(
            code=RetrievalErrorCode.UNKNOWN_CURSOR,
            field=field,
            message=message,
        )


class CursorScopeMismatch(RetrievalFailure):
    def __init__(self, message: str, *, field: str | None = "cursor") -> None:
        super().__init__(
            code=RetrievalErrorCode.CURSOR_SCOPE_MISMATCH,
            field=field,
            message=message,
        )


class ScopeMismatch(RetrievalFailure):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(
            code=RetrievalErrorCode.SCOPE_MISMATCH,
            field=field,
            message=message,
        )


class StaleWorkToken(RetrievalFailure):
    def __init__(self, message: str, *, field: str | None = "work_token") -> None:
        super().__init__(
            code=RetrievalErrorCode.STALE_WORK_TOKEN,
            field=field,
            message=message,
        )


class ReprocessingRequired(RetrievalFailure):
    """The derived index belongs to a retired retrieval or index schema."""

    def __init__(self, message: str, *, field: str | None = "evidence_index") -> None:
        super().__init__(
            code=RetrievalErrorCode.REPROCESSING_REQUIRED,
            field=field,
            message=message,
        )


class OperationalRetrievalFailure(RetrievalFailure):
    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        recovery: Iterable[str] | None = None,
    ) -> None:
        super().__init__(
            code=RetrievalErrorCode.OPERATIONAL,
            field=field,
            message=message,
            recovery=recovery,
        )


# Descriptive aliases make the boundary easy to discover without requiring
# callers to know the shorter concrete class names.
InvalidRetrievalRequestFailure = InvalidRetrievalRequest
StaleCursorFailure = StaleCursor
StaleSearchContinuationFailure = StaleSearchContinuation
SearchPolicyMismatchFailure = SearchPolicyMismatch
CursorScopeMismatchFailure = CursorScopeMismatch
ScopeMismatchFailure = ScopeMismatch
StaleWorkTokenFailure = StaleWorkToken


def _extra_field_hint(entry: dict[str, object], sibling_model: type[BaseModel] | None) -> str:
    """Suggest the correct top-level field when an extra-forbidden field matches one."""

    if sibling_model is None or entry.get("type") != "extra_forbidden":
        return ""
    location = entry.get("loc", ())
    if not location:
        return ""
    extra_name = str(location[-1])
    if extra_name in sibling_model.model_fields:
        return f" (did you mean the top-level `{extra_name}` field instead of nesting it?)"
    return ""


def invalid_request_from_validation(
    error: Exception,
    *,
    sibling_model: type[BaseModel] | None = None,
) -> InvalidRetrievalRequest:
    """Convert a Pydantic validation error into stable field-level metadata.

    Every error reported by Pydantic is preserved as its own
    :class:`FieldViolation` rather than only the first one, so a caller sees
    every problem with a request in one round trip. When ``sibling_model`` is
    given, an ``extra_forbidden`` error whose field name matches a top-level
    field on that model gets a hint pointing at the correct location -- the
    class of mistake behind the ``query.seed_family`` papercut (GitHub #125).
    """

    field: str | None = None
    message: str
    violations: list[FieldViolation] = []
    errors = getattr(error, "errors", None)
    if callable(errors):
        try:
            entries = errors()
        except (TypeError, AttributeError):
            entries = []
        if entries:
            for entry in entries:
                location = entry.get("loc", ())
                entry_field = ".".join(str(part) for part in location) if location else None
                entry_message = str(entry.get("msg") or error) + _extra_field_hint(
                    entry, sibling_model
                )
                violations.append(FieldViolation(entry_field, entry_message))
            field = violations[0].field
            message = violations[0].message
        else:
            message = str(error)
    else:
        message = str(error)
    return InvalidRetrievalRequest(
        message,
        field=field,
        violations=violations or None,
    )
