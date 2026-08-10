import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    PrepareRunRequest,
    ReadEvidenceRequest,
    RunDirective,
    RunOperation,
    RunProposalSelection,
    RunStatusRequest,
    SearchEvidenceRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    WorkflowCondition,
    WorkToken,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.results import Comparison, Estimate, Result
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.storage import ArtifactStore, Transition, WorkflowLedger, dependency_fingerprint

OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:operator",
    display_name="Run operator",
)


def result(result_id: str = "result:trial-a-mortality") -> Result:
    return Result(
        result_id=result_id,
        trial_id="trial:a",
        randomization_id="randomization:a",
        comparison=Comparison(
            experimental_arm_id="arm:experimental",
            comparator_arm_id="arm:control",
        ),
        effect_of_interest="assignment",
        outcome_construct="mortality",
        measurement_instrument="all-cause",
        time_point="30 days",
        analysis_population="intention-to-treat",
        analysis_model="risk ratio",
        effect_measure="risk_ratio",
        source_locator="report:primary/table:2/row:mortality",
    )


def test_run_engine_resumes_current_run_from_concrete_durable_state(tmp_path) -> None:
    first_engine = RunEngine()

    prepared = first_engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    status = first_engine.run_status(RunStatusRequest(run_id=prepared.run_id))
    resumed = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert prepared.run_state is RunState.AWAITING_CONFIRMATION
    assert prepared.condition is WorkflowCondition.CONFIRMATION_REQUIRED
    assert prepared.committed is True
    assert prepared.proposal is not None
    assert status.run_state is RunState.AWAITING_CONFIRMATION
    assert status.committed is False
    assert status.progress is not None
    assert status.progress.committed_checkpoint == "checkpoint:run-prepared"
    assert status.progress.current_scope == ()
    assert status.progress.terminal_result_counts == {
        "diagnostic_ready": 0,
        "report_ready": 0,
    }
    assert resumed.run_id == prepared.run_id
    assert resumed.proposal == prepared.proposal
    assert resumed.committed is False


def test_run_engine_threads_one_persistent_verified_hash_cache_across_calls(tmp_path) -> None:
    """RunEngine rebuilds WorkflowLedger/ArtifactStore fresh on every call
    (#130), so preflight()'s artifact-verification cache can only survive
    across calls if RunEngine owns it and passes the same set through each
    time. test_storage.py separately proves that a shared set actually makes
    preflight() skip re-reading bytes; this proves RunEngine wires that
    sharing correctly rather than handing each call its own fresh set.
    """

    engine = RunEngine()
    assert engine._verified_artifact_hashes == set()

    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    engine.run_status(RunStatusRequest(run_id=prepared.run_id))
    verified_after_first_call = set(engine._verified_artifact_hashes)
    assert verified_after_first_call

    engine.run_status(RunStatusRequest(run_id=prepared.run_id))

    # The same RunEngine-owned set keeps growing (or staying put), never
    # getting replaced by a fresh, empty one on a later call.
    assert engine._verified_artifact_hashes >= verified_after_first_call


def test_starting_new_run_retires_prior_unfinished_run_durably(tmp_path) -> None:
    engine = RunEngine()
    first = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    second = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    retired = engine.run_status(RunStatusRequest(run_id=first.run_id))
    resumed = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert second.run_id != first.run_id
    assert retired.run_state is RunState.RETIRED
    assert resumed.run_id == second.run_id
    assert resumed.run_state is RunState.AWAITING_CONFIRMATION


def test_run_proposal_confirmation_and_blocker_are_ledger_derived(tmp_path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None

    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:submit-proposal",
        )
    )
    confirmed = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:confirm-proposal",
            confirmed_by=OPERATOR,
        )
    )
    assessing = engine.run_status(RunStatusRequest(run_id=prepared.run_id))
    continued = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    blocked = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert submitted.condition is WorkflowCondition.CONFIRMATION_REQUIRED
    assert confirmed.run_state is RunState.ASSESSING
    assert assessing.run_state is RunState.ASSESSING
    assert continued.directive is RunDirective.RUN_BLOCKED
    assert continued.run_state is RunState.BLOCKED
    assert blocked.run_state is RunState.BLOCKED


def test_prepare_run_refuses_incompatible_pre_release_schema_actionably(tmp_path) -> None:
    state = tmp_path / ".rob2"
    state.mkdir()
    ledger_path = state / "ledger.sqlite3"
    with sqlite3.connect(ledger_path) as connection:
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '0')")

    response = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    assert response.run_state is RunState.INTEGRITY_FAILED
    assert response.condition is WorkflowCondition.RUN_INTEGRITY_FAILURE
    assert response.committed is False
    assert response.integrity is not None
    assert response.integrity.code == "incompatible_ledger_schema"
    assert response.integrity.expected_schema_version == "1"
    assert response.integrity.found_schema_version == "0"
    assert any("doctor" in action for action in response.integrity.recovery)
    assert any("preserve" in action.casefold() for action in response.integrity.recovery)
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone() == ("0",)

    status_engine = RunEngine()
    rebound = status_engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    status_response = status_engine.run_status(RunStatusRequest(run_id=rebound.run_id))
    continue_response = status_engine.continue_run(ContinueRunRequest(run_id=rebound.run_id))

    assert status_response.condition is WorkflowCondition.RUN_INTEGRITY_FAILURE
    assert status_response.integrity is not None
    assert status_response.integrity.code == "incompatible_ledger_schema"
    assert continue_response.directive is RunDirective.RUN_INTEGRITY_FAILURE
    assert continue_response.integrity is not None
    assert continue_response.integrity.code == "incompatible_ledger_schema"


def test_invalid_persisted_lifecycle_is_a_typed_run_integrity_condition(tmp_path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    ledger_path = tmp_path / ".rob2" / "ledger.sqlite3"
    with sqlite3.connect(ledger_path) as connection:
        connection.execute(
            "UPDATE writer_lease SET expires_at = ? WHERE singleton = 1",
            (datetime(2000, 1, 1, tzinfo=UTC).isoformat(),),
        )
    ledger = WorkflowLedger(
        ledger_path,
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )
    now = datetime.now(UTC)
    lease = ledger.acquire_lease("owner:test-corruption", now, timedelta(minutes=5))
    for index in range(2):
        ledger.commit(
            Transition(
                scope=prepared.run_id,
                operation="operation:run-confirmed",
                operation_key=f"idempotency:invalid-confirmation-{index}",
                actor=OPERATOR,
                observed_at=now,
                entity_id=f"run-confirmation:invalid-{index}",
                revision_id=f"revision:run-confirmation-invalid-{index}",
                artifact=b"{}",
                artifact_media_type="application/json",
                expected_dependency_fingerprint=dependency_fingerprint(()),
                checkpoint=f"checkpoint:invalid-confirmation-{index}",
                outcome="completed",
            ),
            lease,
            now=now,
        )

    status = engine.run_status(RunStatusRequest(run_id=prepared.run_id))
    continued = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))

    assert status.condition is WorkflowCondition.RUN_INTEGRITY_FAILURE
    assert status.integrity is not None
    assert "not allowed" in status.integrity.detail
    assert continued.directive is RunDirective.RUN_INTEGRITY_FAILURE


def test_run_proposal_rejects_identifiers_not_issued_by_the_engine(tmp_path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None

    with pytest.raises(ValueError, match="not issued"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                proposal_token=prepared.proposal.proposal_token,
                idempotency_key="idempotency:forged-proposal",
                selections=(RunProposalSelection(trial_id="trial:forged"),),
            )
        )


def test_result_resolution_rejects_unissued_preconfirmation_token(tmp_path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    token = WorkToken(
        token="work-token:result-resolution",
        run_id=prepared.run_id,
        work_item_id="work-item:result-resolution",
        operation=RunOperation.SUBMIT_RESULT_RESOLUTION,
        dependency_fingerprint="sha256:" + ("a" * 64),
    )
    request = SubmitResultResolutionRequest(
        contract_version="1.0.0",
        run_id=prepared.run_id,
        work_token=token,
        idempotency_key="idempotency:result-resolution",
        result=result(),
        estimate=Estimate(value=Decimal("0.82")),
        provenance_note="Primary report table 2",
    )

    first = engine.submit_result_resolution(request)
    repeated = engine.submit_result_resolution(request)
    status = engine.run_status(RunStatusRequest(run_id=prepared.run_id))

    assert first.condition is WorkflowCondition.STALE
    assert first.committed is False
    assert first.error is not None
    assert first.error.code == "stale_work"
    assert repeated.committed is False
    assert repeated.condition is WorkflowCondition.STALE
    assert status.result_states == ()


def test_one_run_engine_process_rejects_a_second_project_root(tmp_path) -> None:
    engine = RunEngine()
    engine.prepare_run(PrepareRunRequest(project_root=tmp_path / "one", authorized=True))

    try:
        engine.prepare_run(PrepareRunRequest(project_root=tmp_path / "two", authorized=True))
    except ValueError as error:
        assert "already bound" in str(error)
    else:
        raise AssertionError("a process must not bind a second project root")


def test_prepare_run_without_ledger_returns_structured_authorization_required(tmp_path) -> None:
    """Issue #123: this gate used to raise a bare PermissionError instead of
    returning through the normal tool result contract."""

    response = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert response.committed is False
    assert response.run_state is RunState.BLOCKED
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.proposal is None
    assert response.error is not None
    assert response.error.code == "authorization_required"
    assert not (tmp_path / ".rob2" / "ledger.sqlite3").is_file()


def test_prepare_run_with_existing_ledger_and_no_current_run_returns_structured_condition(
    tmp_path,
) -> None:
    """Issue #123: this gate used to raise a bare PermissionError instead of
    returning through the normal tool result contract. It is only reachable
    once a ledger already exists on disk (e.g. from an earlier authorized
    call) but no run was ever prepared into it."""

    WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )

    response = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert response.committed is False
    assert response.run_state is RunState.BLOCKED
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.proposal is None
    assert response.error is not None
    assert response.error.code == "authorization_required"


def test_run_engine_retrieval_contract_rejects_missing_work_token(tmp_path) -> None:
    with pytest.raises(Exception, match="work_token"):
        SearchEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "query": {"terms": ["allocation"]},
            }
        )
    with pytest.raises(Exception, match="work_token"):
        ReadEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "unit_id": "unit:test",
            }
        )
