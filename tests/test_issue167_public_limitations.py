"""Public v3 terminalization for evidence-limited questions."""

import pytest

import rob2_kit.application.run_engine as run_engine_module
from rob2_kit.application.contracts import (
    ContinueRunRequest,
    SubmitEvidenceStageOutcomeRequest,
    SubmitQuestionStepRequest,
    SubmitSourceChronologyReviewRequest,
)
from rob2_kit.application.evidence_context import materialize_evidence_context
from rob2_kit.application.lifecycle import ResultState
from rob2_kit.application.question_evidence_session import QuestionEvidenceSessionService
from rob2_kit.application.run_engine import InvalidRetrievalRequest
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.evidence.workflow import (
    V3ChronologyStatus,
    V3EvidenceStageOutcomeSubmission,
    V3ScopeLimitationKind,
    V3StageScopeLimitation,
    V3TriggerDisposition,
    V3TriggerDispositionKind,
    v3_stage_is_active,
)
from tests.test_issue167_correction_integration import _prepare_confirm_with_complete_source_roles
from tests.test_issue167_workflow import _outcome, _state


def _limited_context(context, *, include_chronology: bool = False):
    if include_chronology and any(
        fact.constraint.value == "before_randomization"
        and fact.status is V3ChronologyStatus.SATISFIES
        for source in context.authorized_inventory
        for fact in source.chronology_facts
    ):
        return context
    propositions = []
    for proposition in context.propositions:
        passes = []
        for evidence_pass in proposition.passes:
            stages = []
            for stage in evidence_pass.stages:
                limitation_kind = (
                    V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED
                    if include_chronology
                    else V3ScopeLimitationKind.MATERIAL_UNRESOLVED
                )
                limitations = tuple(
                    V3StageScopeLimitation(
                        role=role,
                        kind=limitation_kind,
                        rationale=(
                            "The accepted source chronology is unresolved."
                            if include_chronology
                            else "The accepted source revision is not readable."
                        ),
                    )
                    for role in stage.scope.applicable_source_roles
                )
                scope = stage.scope.model_copy(
                    update={
                        "authorized_source_ids": (),
                        "authorized_source_scope_hash": canonical_hash(()),
                        "role_limitations": limitations,
                    }
                )
                stages.append(
                    stage.model_copy(
                        update={
                            "scope": scope,
                            "recommended_source_ids": (),
                            "priority_hash": canonical_hash(
                                {"scope_id": scope.scope_id, "recommended_source_ids": ()}
                            ),
                            "immediate_static_blockers": limitations,
                        }
                    )
                )
            passes.append(evidence_pass.model_copy(update={"stages": tuple(stages)}))
        propositions.append(proposition.model_copy(update={"passes": tuple(passes)}))
    unsigned = context.model_copy(
        update={"propositions": tuple(propositions), "materialization_hash": ""}
    )
    payload = unsigned.model_dump(mode="json")
    payload["materialization_hash"] = None
    return unsigned.model_copy(update={"materialization_hash": canonical_hash(payload)})


def test_only_exact_chronology_limitations_mint_direct_recovery_authority() -> None:
    state = _state()
    first = state.stage_scopes[0]
    chronology_limited = first.model_copy(
        update={
            "authorized_source_ids": (),
            "authorized_source_scope_hash": canonical_hash(()),
            "applicable_source_roles": ("primary_report",),
            "role_limitations": (
                V3StageScopeLimitation(
                    chronology_constraint="before_randomization",
                    kind=V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED,
                    rationale="The source chronology is unresolved.",
                ),
            ),
        }
    )
    state = state.model_copy(
        update={
            "stage_scopes": tuple(
                chronology_limited if item.stage_id == first.stage_id else item
                for item in state.stage_scopes
            )
        }
    )
    state = state.model_copy(
        update={
            "stage_outcomes": (_outcome(state, first.stage_id, kind="scope_limitation_unresolved"),)
        }
    )

    assert run_engine_module.RunEngine._chronology_diagnostic_is_recoverable(state) is True
    assert run_engine_module.RunEngine._evidence_diagnostic_recovery_actions(state) == (
        "Submit a changed attributable chronology fact with the evidence recovery token.",
    )


def _submit_material_limited_outcomes(engine, run_id, work, service):
    workflow = service.runtime_for_question(work.question_id).state.workflow
    navigation_hash = service.runtime_for_question(work.question_id).state.content_hash
    for proposition in workflow.obligation.propositions:
        for evidence_pass in proposition.evidence_passes:
            for stage in evidence_pass.coverage_stages:
                if not v3_stage_is_active(workflow, proposition.id, evidence_pass.id, stage.id):
                    continue
                scope = next(item for item in workflow.stage_scopes if item.stage_id == stage.id)
                trigger_dispositions = tuple(
                    V3TriggerDisposition(
                        trigger_id=trigger.id,
                        kind=V3TriggerDispositionKind.FALSE,
                        rationale="The static limitation does not activate semantic widening.",
                    )
                    for trigger in workflow.obligation.escalation_triggers
                    if trigger.source_stage_id == stage.id
                )
                payload = {
                    "submission_id": f"outcome:public-limitation:{stage.id}",
                    "run_id": workflow.run_id,
                    "result_id": workflow.result_id,
                    "domain_id": workflow.domain_id,
                    "question_id": workflow.question_id,
                    "obligation_revision_id": workflow.obligation_revision_id,
                    "obligation_hash": workflow.obligation_hash,
                    "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
                    "proposition_id": proposition.id,
                    "pass_id": evidence_pass.id,
                    "stage_id": stage.id,
                    "materialized_scope_id": scope.scope_id,
                    "outcome_kind": "scope_limitation_unresolved",
                    "rationale": "The exact materialized scope is terminally limited.",
                    "trigger_dispositions": tuple(
                        item.model_dump(mode="json") for item in trigger_dispositions
                    ),
                    "acquisition_receipt_id": None,
                    "content_hash": None,
                }
                response = engine.submit_evidence_stage_outcome(
                    SubmitEvidenceStageOutcomeRequest(
                        contract_version="3.0.0",
                        run_id=run_id,
                        work_token=work.work_token,
                        idempotency_key=f"idempotency:public-limitation:{stage.id}",
                        result_id=work.result_id,
                        domain_id=work.domain_id,
                        question_id=work.question_id,
                        session_content_hash=work.session_content_hash,
                        expected_navigation_state_hash=navigation_hash,
                        submission=V3EvidenceStageOutcomeSubmission.model_validate(
                            payload | {"content_hash": canonical_hash(payload)}
                        ),
                    )
                )
                navigation_hash = response.navigation_state_hash
                workflow = service.runtime_for_question(work.question_id).state.workflow


def test_public_material_limitation_yields_judgment_free_reconciliation_diagnostic(
    tmp_path, monkeypatch
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    original_service = QuestionEvidenceSessionService

    def limited_service(**kwargs):
        def context_factory(obligation, inventory):
            return _limited_context(materialize_evidence_context(obligation, inventory))

        return original_service(**kwargs, context_factory=context_factory)

    monkeypatch.setattr(
        run_engine_module,
        "QuestionEvidenceSessionService",
        limited_service,
    )
    engine, run_id = _prepare_confirm_with_complete_source_roles(tmp_path)
    response = None
    for index in range(6):
        continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
        work = continued.work_item
        assert work is not None
        assert work.result_id == "result:a"
        assert work.domain_id is not None and work.question_id is not None
        service = engine._question_session_service(
            engine._bound_ledger(run_id), run_id, work.result_id, work.domain_id
        )
        _submit_material_limited_outcomes(engine, run_id, work, service)

        response = engine.submit_question_step(
            SubmitQuestionStepRequest(
                contract_version="3.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:public-material-diagnostic:{index}",
                result_id=work.result_id,
                domain_id=work.domain_id,
                question_id=work.question_id,
                session_content_hash=work.session_content_hash,
                frontier_entry_hash=work.frontier_entry_hash,
                diagnostic_stop=True,
            )
        )
        if response.diagnostic_terminal:
            break

    assert response is not None
    assert response.diagnostic_terminal is True
    assert response.result_state is ResultState.DIAGNOSTIC_READY
    assert response.evidence_recovery_token is None
    events = engine._events_for_run(engine._bound_ledger(run_id), run_id)
    diagnostic_event = next(
        event
        for event in reversed(events)
        if event.operation == "operation:result-diagnostic-ready"
    )
    diagnostic = engine._event_payload(engine._bound_ledger(run_id), diagnostic_event)
    assert diagnostic["recovery"] == [
        "Reprocess or replace the unreadable accepted Source, then reconcile the changed inventory."
    ]
    assert "reopen" not in " ".join(diagnostic["recovery"]).lower()
    assert not any(
        event.operation in {"operation:submit-domain-evidence", "operation:submit-domain-answers"}
        for event in events
    )


def test_public_chronology_diagnostic_recovers_only_into_a_new_context_revision(
    tmp_path, monkeypatch
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    original_service = QuestionEvidenceSessionService

    def limited_service(**kwargs):
        def context_factory(obligation, inventory):
            return _limited_context(
                materialize_evidence_context(obligation, inventory), include_chronology=True
            )

        return original_service(**kwargs, context_factory=context_factory)

    monkeypatch.setattr(run_engine_module, "QuestionEvidenceSessionService", limited_service)
    monkeypatch.setattr(
        run_engine_module.EvidenceSearchIndex,
        "resolve_read_view_receipt",
        lambda *_args, **_kwargs: None,
    )
    engine, run_id = _prepare_confirm_with_complete_source_roles(tmp_path)
    initial_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert initial_work is not None
    initial_service = engine._question_session_service(
        engine._bound_ledger(run_id),
        run_id,
        initial_work.result_id,
        initial_work.domain_id,
    )
    initial_runtime = initial_service.runtime_for_question(initial_work.question_id)
    initial_source = initial_runtime.context.authorized_inventory[0]
    unresolved_rationale = "The available text does not establish the relevant date."
    engine.submit_source_chronology_review(
        SubmitSourceChronologyReviewRequest(
            contract_version="3.0.0",
            run_id=run_id,
            work_token=initial_work.work_token,
            idempotency_key="idempotency:public-chronology-unresolved",
            result_id=initial_work.result_id,
            domain_id=initial_work.domain_id,
            question_id=initial_work.question_id,
            source_id=initial_source.source_id,
            source_artifact_hash=initial_source.source_artifact_hash,
            parse_id=initial_source.parse_id,
            parse_output_hash=initial_source.parse_output_hash,
            constraint="before_randomization",
            status=V3ChronologyStatus.UNRESOLVED,
            rationale=unresolved_rationale,
            evidence_read_receipt="read-view:chronology-unresolved",
        )
    )
    response = None
    work = None
    for index in range(6):
        work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert work is not None and work.domain_id is not None and work.question_id is not None
        service = engine._question_session_service(
            engine._bound_ledger(run_id), run_id, work.result_id, work.domain_id
        )
        _submit_material_limited_outcomes(engine, run_id, work, service)
        response = engine.submit_question_step(
            SubmitQuestionStepRequest(
                contract_version="3.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:public-chronology-diagnostic:{index}",
                result_id=work.result_id,
                domain_id=work.domain_id,
                question_id=work.question_id,
                session_content_hash=work.session_content_hash,
                frontier_entry_hash=work.frontier_entry_hash,
                diagnostic_stop=True,
            )
        )
        if response.diagnostic_terminal:
            break

    assert response is not None and response.evidence_recovery_token is not None
    assert work is not None and work.domain_id is not None and work.question_id is not None
    token = response.evidence_recovery_token
    prior_context_hash = token.context_hash
    service = engine._question_session_service(
        engine._bound_ledger(run_id), run_id, work.result_id, work.domain_id
    )
    stopped = service.runtime_for_diagnostic_question(work.question_id)
    source = stopped.context.authorized_inventory[0]
    with pytest.raises(InvalidRetrievalRequest, match="changed materialized chronology fact"):
        engine.submit_source_chronology_review(
            SubmitSourceChronologyReviewRequest(
                contract_version="3.0.0",
                run_id=run_id,
                work_token=token,
                idempotency_key="idempotency:unchanged-chronology-recovery",
                result_id=work.result_id,
                domain_id=work.domain_id,
                question_id=work.question_id,
                source_id=source.source_id,
                source_artifact_hash=source.source_artifact_hash,
                parse_id=source.parse_id,
                parse_output_hash=source.parse_output_hash,
                constraint="before_randomization",
                status=V3ChronologyStatus.UNRESOLVED,
                rationale=unresolved_rationale,
                evidence_read_receipt="read-view:chronology-unchanged",
            )
        )
    recovered = engine.submit_source_chronology_review(
        SubmitSourceChronologyReviewRequest(
            contract_version="3.0.0",
            run_id=run_id,
            work_token=token,
            idempotency_key="idempotency:public-chronology-recovery",
            result_id=work.result_id,
            domain_id=work.domain_id,
            question_id=work.question_id,
            source_id=source.source_id,
            source_artifact_hash=source.source_artifact_hash,
            parse_id=source.parse_id,
            parse_output_hash=source.parse_output_hash,
            constraint="before_randomization",
            status=V3ChronologyStatus.SATISFIES,
            rationale="The dated protocol predates randomization.",
            evidence_read_receipt="read-view:chronology-recovery",
        )
    )

    assert recovered.result_state is ResultState.PENDING
    refreshed_service = engine._question_session_service(
        engine._bound_ledger(run_id), run_id, work.result_id, work.domain_id
    )
    assert refreshed_service.project().frontier.status == "active"
    refreshed = refreshed_service.runtime_for_question(work.question_id)
    assert refreshed.context.materialization_hash != prior_context_hash
    assert all(
        limitation.kind is not V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED
        for scope in refreshed.context.stage_scopes
        for limitation in scope.role_limitations
    )
