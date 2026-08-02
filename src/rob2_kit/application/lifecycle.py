"""Deterministic Run and Result lifecycle transitions.

The lifecycle is a projection of the Workflow ledger.  It deliberately does
not keep a second mutable state store: callers replay the typed lifecycle
events in ledger order and either get the next state or a structured refusal.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel, Identifier
from rob2_kit.storage.ledger import WorkflowEvent


class RunState(StrEnum):
    """The durable coarse state presented to a Harness."""

    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ASSESSING = "assessing"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    INTEGRITY_FAILED = "integrity_failed"
    RETIRED = "retired"


class ResultState(StrEnum):
    """The independently derived preparation state of one Result."""

    PENDING = "pending"
    ASSESSING = "assessing"
    REPORT_READY = "report_ready"
    DIAGNOSTIC_READY = "diagnostic_ready"


class RunLifecycleEvent(StrEnum):
    PREPARED = "run_prepared"
    PROPOSAL_SUBMITTED = "run_proposal_submitted"
    CONFIRMED = "run_confirmed"
    WORK_STARTED = "run_work_started"
    BLOCKED = "run_blocked"
    UNBLOCKED = "run_unblocked"
    COMPLETED = "run_completed"
    INTEGRITY_FAILED = "run_integrity_failed"
    RETIRED = "run_retired"


class ResultLifecycleEvent(StrEnum):
    DISCOVERED = "result_discovered"
    STARTED = "result_started"
    REPORT_READY = "result_report_ready"
    DIAGNOSTIC_READY = "result_diagnostic_ready"
    INVALIDATED = "result_invalidated"


class LifecycleEvent(FrozenModel):
    """One typed event consumed by a run or result transition table."""

    event: RunLifecycleEvent | ResultLifecycleEvent
    result_id: Identifier | None = None
    sequence: int | None = Field(default=None, ge=1)


class TransitionRejection(FrozenModel):
    """Actionable details for an event that cannot follow the current state."""

    state: str
    event: str
    allowed_events: tuple[str, ...]
    reason: str = Field(min_length=1)
    sequence: int | None = Field(default=None, ge=1)


class TransitionRejected(ValueError):
    """Raised when a ledger event would make lifecycle replay ambiguous."""

    def __init__(self, rejection: TransitionRejection) -> None:
        self.rejection = rejection
        super().__init__(rejection.reason)


class LifecycleIntegrityError(RuntimeError):
    """Raised when persisted lifecycle events cannot be replayed safely."""

    def __init__(self, rejection: TransitionRejection) -> None:
        self.rejection = rejection
        super().__init__(rejection.reason)


class ResultLifecycle(FrozenModel):
    result_id: Identifier
    state: ResultState
    last_sequence: int | None = Field(default=None, ge=1)


class LifecycleProjection(FrozenModel):
    run_state: RunState
    results: tuple[ResultLifecycle, ...] = ()
    last_sequence: int | None = Field(default=None, ge=1)


# The tables are intentionally explicit and public.  A test can enumerate
# every source state and event without reaching into a workflow framework.
RUN_TRANSITIONS: Final[dict[RunState | None, dict[RunLifecycleEvent, RunState]]] = {
    None: {RunLifecycleEvent.PREPARED: RunState.AWAITING_CONFIRMATION},
    RunState.AWAITING_CONFIRMATION: {
        RunLifecycleEvent.PROPOSAL_SUBMITTED: RunState.AWAITING_CONFIRMATION,
        RunLifecycleEvent.CONFIRMED: RunState.ASSESSING,
        RunLifecycleEvent.BLOCKED: RunState.BLOCKED,
        RunLifecycleEvent.INTEGRITY_FAILED: RunState.INTEGRITY_FAILED,
        RunLifecycleEvent.RETIRED: RunState.RETIRED,
    },
    RunState.ASSESSING: {
        RunLifecycleEvent.WORK_STARTED: RunState.ASSESSING,
        RunLifecycleEvent.BLOCKED: RunState.BLOCKED,
        RunLifecycleEvent.COMPLETED: RunState.COMPLETE,
        RunLifecycleEvent.INTEGRITY_FAILED: RunState.INTEGRITY_FAILED,
        RunLifecycleEvent.RETIRED: RunState.RETIRED,
    },
    RunState.BLOCKED: {
        RunLifecycleEvent.UNBLOCKED: RunState.ASSESSING,
        RunLifecycleEvent.INTEGRITY_FAILED: RunState.INTEGRITY_FAILED,
        RunLifecycleEvent.RETIRED: RunState.RETIRED,
    },
    RunState.COMPLETE: {
        RunLifecycleEvent.INTEGRITY_FAILED: RunState.INTEGRITY_FAILED,
    },
    RunState.INTEGRITY_FAILED: {
        RunLifecycleEvent.RETIRED: RunState.RETIRED,
    },
    RunState.RETIRED: {},
}

RESULT_TRANSITIONS: Final[dict[ResultState | None, dict[ResultLifecycleEvent, ResultState]]] = {
    None: {
        ResultLifecycleEvent.DISCOVERED: ResultState.PENDING,
    },
    ResultState.PENDING: {
        ResultLifecycleEvent.STARTED: ResultState.ASSESSING,
        ResultLifecycleEvent.DIAGNOSTIC_READY: ResultState.DIAGNOSTIC_READY,
    },
    ResultState.ASSESSING: {
        ResultLifecycleEvent.REPORT_READY: ResultState.REPORT_READY,
        ResultLifecycleEvent.DIAGNOSTIC_READY: ResultState.DIAGNOSTIC_READY,
        ResultLifecycleEvent.INVALIDATED: ResultState.PENDING,
    },
    ResultState.REPORT_READY: {
        ResultLifecycleEvent.INVALIDATED: ResultState.PENDING,
    },
    ResultState.DIAGNOSTIC_READY: {
        ResultLifecycleEvent.INVALIDATED: ResultState.PENDING,
    },
}


def transition_run(
    state: RunState | None,
    event: RunLifecycleEvent,
    *,
    sequence: int | None = None,
) -> RunState:
    """Apply one Run event or raise a structured transition refusal."""

    allowed = RUN_TRANSITIONS[state]
    next_state = allowed.get(event)
    if next_state is None:
        current = "uninitialized" if state is None else state.value
        rejection = TransitionRejection(
            state=current,
            event=event.value,
            allowed_events=tuple(item.value for item in allowed),
            reason=(
                f"lifecycle event {event.value!r} is not allowed from {current!r}; "
                "repair the ledger or start a new Run"
            ),
            sequence=sequence,
        )
        raise TransitionRejected(rejection)
    return next_state


def transition_result(
    state: ResultState | None,
    event: ResultLifecycleEvent,
    *,
    sequence: int | None = None,
) -> ResultState:
    """Apply one Result event or raise a structured transition refusal."""

    allowed = RESULT_TRANSITIONS[state]
    next_state = allowed.get(event)
    if next_state is None:
        current = "uninitialized" if state is None else state.value
        rejection = TransitionRejection(
            state=current,
            event=event.value,
            allowed_events=tuple(item.value for item in allowed),
            reason=(
                f"result lifecycle event {event.value!r} is not allowed from {current!r}; "
                "invalidate the Result or start a new Run"
            ),
            sequence=sequence,
        )
        raise TransitionRejected(rejection)
    return next_state


def derive_lifecycle(events: tuple[WorkflowEvent, ...]) -> LifecycleProjection:
    """Replay target lifecycle events from one concrete Workflow ledger."""

    run_state: RunState | None = None
    result_states: dict[str, ResultState | None] = {}
    result_sequences: dict[str, int] = {}
    last_sequence: int | None = None
    for workflow_event in events:
        lifecycle_event = lifecycle_event_for(workflow_event)
        if lifecycle_event is None:
            continue
        last_sequence = workflow_event.sequence
        if isinstance(lifecycle_event, RunLifecycleEvent):
            try:
                run_state = transition_run(
                    run_state, lifecycle_event, sequence=workflow_event.sequence
                )
            except TransitionRejected as error:
                raise LifecycleIntegrityError(error.rejection) from error
            continue

        result_id = lifecycle_result_id(workflow_event)
        if result_id is None:
            rejection = TransitionRejection(
                state="unknown",
                event=lifecycle_event.value,
                allowed_events=(),
                reason="a Result lifecycle event is missing its engine-issued result ID",
                sequence=workflow_event.sequence,
            )
            raise LifecycleIntegrityError(rejection)
        current = result_states.get(result_id)
        try:
            result_states[result_id] = transition_result(
                current, lifecycle_event, sequence=workflow_event.sequence
            )
        except TransitionRejected as error:
            raise LifecycleIntegrityError(error.rejection) from error
        result_sequences[result_id] = workflow_event.sequence

    return LifecycleProjection(
        run_state=run_state or RunState.AWAITING_CONFIRMATION,
        results=tuple(
            ResultLifecycle(
                result_id=result_id,
                state=state or ResultState.PENDING,
                last_sequence=result_sequences.get(result_id),
            )
            for result_id, state in sorted(result_states.items())
        ),
        last_sequence=last_sequence,
    )


def lifecycle_event_for(event: WorkflowEvent) -> RunLifecycleEvent | ResultLifecycleEvent | None:
    """Map only target operation names to lifecycle events.

    Legacy gateway operations intentionally return ``None`` and therefore do
    not contaminate the target projection while both boundaries coexist.
    """

    operation = event.operation
    aliases: dict[str, RunLifecycleEvent | ResultLifecycleEvent] = {
        "operation:run-prepared": RunLifecycleEvent.PREPARED,
        "operation:prepare-run": RunLifecycleEvent.PREPARED,
        "operation:run-proposal-submitted": RunLifecycleEvent.PROPOSAL_SUBMITTED,
        "operation:submit-run-proposal": RunLifecycleEvent.PROPOSAL_SUBMITTED,
        "operation:run-confirmed": RunLifecycleEvent.CONFIRMED,
        "operation:confirm-run-definition": RunLifecycleEvent.CONFIRMED,
        "operation:run-work-started": RunLifecycleEvent.WORK_STARTED,
        "operation:run-blocked": RunLifecycleEvent.BLOCKED,
        "operation:run-unblocked": RunLifecycleEvent.UNBLOCKED,
        "operation:run-completed": RunLifecycleEvent.COMPLETED,
        "operation:run-integrity-failed": RunLifecycleEvent.INTEGRITY_FAILED,
        "operation:run-retired": RunLifecycleEvent.RETIRED,
        "operation:run-register-result": ResultLifecycleEvent.DISCOVERED,
        "operation:run-register-diagnostic-result": ResultLifecycleEvent.DISCOVERED,
        "operation:result-discovered": ResultLifecycleEvent.DISCOVERED,
        "operation:result-started": ResultLifecycleEvent.STARTED,
        "operation:result-report-ready": ResultLifecycleEvent.REPORT_READY,
        "operation:result-diagnostic-ready": ResultLifecycleEvent.DIAGNOSTIC_READY,
        "operation:result-invalidated": ResultLifecycleEvent.INVALIDATED,
    }
    return aliases.get(operation)


def lifecycle_result_id(event: WorkflowEvent) -> Identifier | None:
    """Get a Result ID from the scope fields available during event replay."""

    if event.scope.startswith("result:"):
        return event.scope
    if event.entity_id.startswith("result:"):
        return event.entity_id
    return None


def lifecycle_event_table() -> tuple[tuple[str, str, str], ...]:
    """Return the explicit transition table in a stable inspection format."""

    rows: list[tuple[str, str, str]] = []
    for state, transitions in RUN_TRANSITIONS.items():
        state_name = "uninitialized" if state is None else state.value
        rows.extend(
            (state_name, event.value, next_state.value) for event, next_state in transitions.items()
        )
    return tuple(rows)


def result_lifecycle_event_table() -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for state, transitions in RESULT_TRANSITIONS.items():
        state_name = "uninitialized" if state is None else state.value
        rows.extend(
            (state_name, event.value, next_state.value) for event, next_state in transitions.items()
        )
    return tuple(rows)
