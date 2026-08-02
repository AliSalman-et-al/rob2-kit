from datetime import UTC, datetime, timedelta

import pytest

from rob2_kit.application.lifecycle import (
    RESULT_TRANSITIONS,
    RUN_TRANSITIONS,
    ResultLifecycleEvent,
    ResultState,
    RunLifecycleEvent,
    RunState,
    TransitionRejected,
    derive_lifecycle,
    transition_result,
    transition_run,
)
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.storage import ArtifactStore, Transition, WorkflowLedger, dependency_fingerprint

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
ACTOR = Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test engine")

EXPECTED_RUN_TRANSITIONS = {
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

EXPECTED_RESULT_TRANSITIONS = {
    None: {ResultLifecycleEvent.DISCOVERED: ResultState.PENDING},
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


@pytest.mark.parametrize(
    ("state", "event", "expected"),
    [
        (state, event, expected)
        for state, transitions in EXPECTED_RUN_TRANSITIONS.items()
        for event, expected in transitions.items()
    ],
)
def test_every_allowed_run_transition_is_explicit(
    state: RunState | None,
    event: RunLifecycleEvent,
    expected: RunState,
) -> None:
    assert transition_run(state, event) is expected


@pytest.mark.parametrize(
    ("state", "event"),
    [
        (state, event)
        for state, transitions in EXPECTED_RUN_TRANSITIONS.items()
        for event in RunLifecycleEvent
        if event not in transitions
    ],
)
def test_every_rejected_run_transition_is_structured(
    state: RunState | None,
    event: RunLifecycleEvent,
) -> None:
    with pytest.raises(TransitionRejected) as raised:
        transition_run(state, event, sequence=7)

    assert raised.value.rejection.event == event.value
    assert raised.value.rejection.sequence == 7


@pytest.mark.parametrize(
    ("state", "event", "expected"),
    [
        (state, event, expected)
        for state, transitions in EXPECTED_RESULT_TRANSITIONS.items()
        for event, expected in transitions.items()
    ],
)
def test_every_allowed_result_transition_is_explicit(
    state: ResultState | None,
    event: ResultLifecycleEvent,
    expected: ResultState,
) -> None:
    assert transition_result(state, event) is expected


@pytest.mark.parametrize(
    ("state", "event"),
    [
        (state, event)
        for state, transitions in EXPECTED_RESULT_TRANSITIONS.items()
        for event in ResultLifecycleEvent
        if event not in transitions
    ],
)
def test_every_rejected_result_transition_is_structured(
    state: ResultState | None,
    event: ResultLifecycleEvent,
) -> None:
    with pytest.raises(TransitionRejected) as raised:
        transition_result(state, event, sequence=11)

    assert raised.value.rejection.event == event.value
    assert raised.value.rejection.sequence == 11


def test_public_transition_tables_match_the_finite_model() -> None:
    assert RUN_TRANSITIONS == EXPECTED_RUN_TRANSITIONS
    assert RESULT_TRANSITIONS == EXPECTED_RESULT_TRANSITIONS


def test_run_and_result_state_are_replayed_from_workflow_events(tmp_path) -> None:
    ledger = WorkflowLedger(
        tmp_path / "ledger.sqlite3",
        ArtifactStore(tmp_path / "artifacts"),
    )
    lease = ledger.acquire_lease("owner:test", NOW, timedelta(minutes=5))
    events = (
        ("run:one", "operation:run-prepared", "run-record:one", "revision:run-one"),
        (
            "result:one",
            "operation:run-register-result",
            "run-result:one",
            "revision:result-one",
        ),
        ("run:one", "operation:run-confirmed", "run-confirmation:one", "revision:confirm-one"),
        (
            "result:one",
            "operation:result-started",
            "result-state:one-started",
            "revision:result-one-started",
        ),
        (
            "result:one",
            "operation:result-report-ready",
            "result-state:one-ready",
            "revision:result-one-ready",
        ),
        ("run:one", "operation:run-completed", "run-state:one-ready", "revision:run-one-ready"),
    )
    for index, (scope, operation, entity_id, revision_id) in enumerate(events):
        ledger.commit(
            Transition(
                scope=scope,
                operation=operation,
                operation_key=f"idempotency:lifecycle-{index}",
                actor=ACTOR,
                observed_at=NOW,
                entity_id=entity_id,
                revision_id=revision_id,
                artifact=b"{}",
                artifact_media_type="application/json",
                expected_dependency_fingerprint=dependency_fingerprint(()),
                checkpoint=f"checkpoint:lifecycle-{index}",
                outcome="completed",
            ),
            lease,
            now=NOW,
        )

    projection = derive_lifecycle(ledger.events())

    assert projection.run_state is RunState.COMPLETE
    assert [(item.result_id, item.state) for item in projection.results] == [
        ("result:one", ResultState.REPORT_READY)
    ]
