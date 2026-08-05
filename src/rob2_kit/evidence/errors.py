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


class RetrievalErrorCode(StrEnum):
    """Stable machine-readable recovery classes for bounded retrieval."""

    STALE_CURSOR = "stale_cursor"
    CURSOR_SCOPE_MISMATCH = "cursor_scope_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    STALE_WORK_TOKEN = "stale_work_token"
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
    RetrievalErrorCode.SCOPE_MISMATCH: (
        "use only IDs issued by the active WorkToken",
        "retry with the issued unit or scope",
    ),
    RetrievalErrorCode.STALE_WORK_TOKEN: (
        "call continue_run",
        "copy the current submit_domain_evidence WorkToken",
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

    def __init__(
        self,
        *,
        code: RetrievalErrorCode,
        message: str,
        field: str | None = None,
        recovery: Iterable[str] | None = None,
        next_actions: Iterable[str] | None = None,
    ) -> None:
        self.code = RetrievalErrorCode(code)
        self.field = field
        self.message = message
        self.recovery = tuple(recovery or _DEFAULT_RECOVERY[self.code])
        self.next_actions = tuple(next_actions or self.recovery)
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
    ) -> None:
        super().__init__(
            code=RetrievalErrorCode.INVALID_REQUEST,
            field=field,
            message=message,
            recovery=recovery,
        )


class StaleCursor(RetrievalFailure):
    def __init__(self, message: str, *, field: str | None = "cursor") -> None:
        super().__init__(
            code=RetrievalErrorCode.STALE_CURSOR,
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
CursorScopeMismatchFailure = CursorScopeMismatch
ScopeMismatchFailure = ScopeMismatch
StaleWorkTokenFailure = StaleWorkToken
RetrievalOperationalFailure = OperationalRetrievalFailure


def invalid_request_from_validation(error: Exception) -> InvalidRetrievalRequest:
    """Convert a Pydantic validation error into stable field-level metadata."""

    field: str | None = None
    errors = getattr(error, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            location = first.get("loc", ())
            if location:
                field = ".".join(str(part) for part in location)
            message = str(first.get("msg") or error)
        except (IndexError, TypeError, AttributeError):
            message = str(error)
    else:
        message = str(error)
    return InvalidRetrievalRequest(message, field=field)
