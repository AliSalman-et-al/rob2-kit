"""Persisted public integration coverage for v3 question-answer correction."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rob2_kit.application.active_question_frontier import effective_question_steps
from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    CorrectQuestionStepRequest,
    MaterializeQuestionEvidenceBundleRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    SubmitQuestionStepRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
)
from rob2_kit.application.evidence_navigation import new_v3_navigation_state
from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.application.run_engine import (
    InvalidRetrievalRequest,
    RunEngine,
    StaleWorkTokenError,
    _DomainAnswersRecord,
    _DomainEvidenceRecord,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.obligations import (
    EvidenceNavigationIntentKind,
    EvidencePassActivation,
    EvidenceStageActivation,
)
from rob2_kit.evidence.search import SearchQuery
from rob2_kit.evidence.workflow import (
    V3EvidenceStageOutcomeSubmission,
    V3ExposedPage,
    V3NavigationCompletionReceipt,
    V3SearchAttempt,
    V3TriggerDisposition,
    V3TriggerDispositionKind,
)
from rob2_kit.storage.ledger import WorkflowEventOutcome
from tests.test_input_reconciliation import OPERATOR, _config, _result
from tests.test_run_proposal import StubParser, _first_proposal

INITIAL_ANSWERS = {
    "sq:randomization:sequence": "no",
    "sq:randomization:concealment": "no",
    "sq:randomization:baseline-imbalance": "no",
    "sq:deviations:participants-aware": "no",
    "sq:deviations:personnel-aware": "no",
    "sq:deviations:appropriate-analysis": "yes",
    # This closes Domain 3 with Q3.2 inactive. Correcting it to ``no`` later
    # is the smallest real Logic-pack transition that activates a dependent.
    "sq:missing:data-available": "yes",
    "sq:measurement:method-inappropriate": "yes",
    "sq:measurement:differential": "no",
    "sq:selection:prespecified-analysis": "no",
    "sq:selection:multiple-measurements": "no",
    "sq:selection:multiple-analyses": "no",
}


def _prepare_confirm_with_complete_source_roles(root: Path) -> tuple[RunEngine, str]:
    """Confirm one real Result while making the fixture Source applicable everywhere."""

    config = _config(_result("result:a", "trial:trial-a"))
    (root / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
    assert prepared.initialization is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:correction-fixture-source-roles",
            selections=tuple(
                RunProposalSelection(
                    trial_id=item.trial_id,
                    source_id=item.source_id,
                    roles=tuple(SourceRole),
                )
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    selections = tuple(
        RunProposalSelection(
            trial_id=candidate.trial_id,
            outcome_target_id=candidate.outcome_target_id,
            result_id=candidate.result_id,
            result_candidate_id=candidate.candidate_id,
        )
        for candidate in prepared.proposal.result_candidates
        if candidate.result_id is not None
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:correction-fixture-proposal",
            selections=selections,
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:correction-fixture-confirm",
            confirmed_by=OPERATOR,
        )
    )
    return engine, prepared.run_id


def _seed_unrelated_domain_checkpoints(engine: RunEngine, run_id: str) -> None:
    """Seed only unrelated Domain products; the correction Domain stays fully public."""

    ledger = engine._bound_ledger(run_id)
    now = engine._now()
    answers_by_domain = {
        "domain:measurement": {
            "sq:measurement:method-inappropriate": "yes",
            "sq:measurement:differential": "no",
        },
        "domain:selection": {
            "sq:selection:prespecified-analysis": "no",
            "sq:selection:multiple-measurements": "no",
            "sq:selection:multiple-analyses": "no",
        },
    }
    transitions = []
    for domain_id, answers in answers_by_domain.items():
        slug = domain_id.removeprefix("domain:")
        transitions.extend(
            (
                engine._transition(
                    scope="result:a",
                    operation="operation:submit-domain-evidence",
                    operation_key=f"idempotency:fixture:{slug}:evidence",
                    entity_id=f"domain-evidence:fixture-{slug}",
                    revision_id=f"revision:domain-evidence-fixture-{slug}",
                    artifact=_DomainEvidenceRecord(
                        run_id=run_id,
                        result_id="result:a",
                        domain_id=domain_id,
                        coverage_state="complete",
                    ),
                    checkpoint=f"checkpoint:evidence-{slug}",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                ),
                engine._transition(
                    scope="result:a",
                    operation="operation:submit-domain-answers",
                    operation_key=f"idempotency:fixture:{slug}:answers",
                    entity_id=f"domain-answers:fixture-{slug}",
                    revision_id=f"revision:domain-answers-fixture-{slug}",
                    artifact=_DomainAnswersRecord(
                        run_id=run_id,
                        result_id="result:a",
                        domain_id=domain_id,
                        answers=answers,
                        rationales={key: "Unrelated fixture answer." for key in answers},
                    ),
                    checkpoint=f"checkpoint:answers-{slug}",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                ),
            )
        )
    ledger.commit_batch(tuple(transitions), engine._acquire_lease(ledger, now), now=now)


def _close_workflow(service, question_id: str):
    """Persist a clean exhaustive fixture traversal for the real obligation."""

    opened = service.runtime_for_question(question_id)
    workflow = opened.state.workflow
    scopes = tuple(
        scope.model_copy(update={"role_limitations": ()}) for scope in workflow.stage_scopes
    )
    scope_by_stage = {scope.stage_id: scope for scope in scopes}
    attempts = []
    pages = []
    receipts = []
    outcomes = []
    counter = 0
    for proposition in workflow.obligation.propositions:
        for evidence_pass in proposition.evidence_passes:
            if evidence_pass.activation is not EvidencePassActivation.MANDATORY:
                continue
            for stage in evidence_pass.coverage_stages:
                if stage.activation is not EvidenceStageActivation.MANDATORY:
                    continue
                scope = scope_by_stage[stage.id]
                for intent in stage.navigation_intents:
                    counter += 1
                    if intent.kind is EvidenceNavigationIntentKind.SEARCH:
                        query = SearchQuery(
                            terms=("fixture",),
                            source_ids=scope.authorized_source_ids,
                        )
                        attempt = V3SearchAttempt(
                            attempt_id=f"attempt:correction-fixture:{counter}",
                            proposition_id=proposition.id,
                            pass_id=evidence_pass.id,
                            stage_id=stage.id,
                            intent_id=intent.id,
                            query=query,
                            query_hash=canonical_hash(query),
                            source_scope_hash=scope.authorized_source_scope_hash,
                        )
                        attempts.append(attempt)
                        pages.append(
                            V3ExposedPage(
                                attempt_id=attempt.attempt_id,
                                page_handle=f"page:correction-fixture:{counter}",
                                candidate_ids=(),
                                page_number=1,
                                total_page_count=1,
                                traversal_complete=True,
                            )
                        )
                        continue
                    payload = {
                        "receipt_id": f"receipt:correction-fixture:{counter}",
                        "issuance_id": f"issuance:correction-fixture:{counter}",
                        "proposition_id": proposition.id,
                        "pass_id": evidence_pass.id,
                        "stage_id": stage.id,
                        "intent_id": intent.id,
                        "kind": intent.kind,
                        "source_scope_hash": scope.authorized_source_scope_hash,
                        "snapshot_hash": workflow.snapshot_hash,
                        "read_policy_id": (
                            None
                            if intent.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW
                            else workflow.read_policy_id
                        ),
                        "read_policy_hash": (
                            None
                            if intent.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW
                            else workflow.read_policy_hash
                        ),
                        "visual_policy_id": (
                            workflow.visual_policy_id
                            if intent.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW
                            else None
                        ),
                        "visual_policy_hash": (
                            workflow.visual_policy_hash
                            if intent.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW
                            else None
                        ),
                        "receipt_hash": None,
                    }
                    receipts.append(
                        V3NavigationCompletionReceipt.model_validate(
                            payload | {"receipt_hash": canonical_hash(payload)}
                        )
                    )
                trigger_ids = tuple(
                    trigger.id
                    for trigger in workflow.obligation.escalation_triggers
                    if trigger.source_stage_id == stage.id
                )
                outcome_payload = {
                    "submission_id": f"outcome:correction-fixture:{counter}",
                    "run_id": workflow.run_id,
                    "result_id": workflow.result_id,
                    "domain_id": workflow.domain_id,
                    "question_id": question_id,
                    "obligation_revision_id": workflow.obligation_revision_id,
                    "obligation_hash": workflow.obligation_hash,
                    "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
                    "proposition_id": proposition.id,
                    "pass_id": evidence_pass.id,
                    "stage_id": stage.id,
                    "materialized_scope_id": scope.scope_id,
                    "outcome_kind": "obligation_satisfied",
                    "rationale": "The fixture exhausted every issued navigation intent.",
                    "trigger_dispositions": tuple(
                        V3TriggerDisposition(
                            trigger_id=trigger_id,
                            kind=V3TriggerDispositionKind.FALSE,
                            rationale="No escalation condition was found.",
                        ).model_dump(mode="json")
                        for trigger_id in trigger_ids
                    ),
                    "acquisition_receipt_id": None,
                    "content_hash": None,
                }
                outcomes.append(
                    V3EvidenceStageOutcomeSubmission.model_validate(
                        outcome_payload | {"content_hash": canonical_hash(outcome_payload)}
                    )
                )
    closed = workflow.model_copy(
        update={
            "stage_scopes": scopes,
            "attempts": tuple(attempts),
            "pages": tuple(pages),
            "issued_receipt_hashes": tuple(
                (receipt.issuance_id, receipt.receipt_hash) for receipt in receipts
            ),
            "completion_receipts": tuple(receipts),
            "stage_outcomes": tuple(outcomes),
        }
    )
    navigation = new_v3_navigation_state(workflow=closed)
    service._navigation_store.save(
        navigation,
        expected_content_hash=opened.state.content_hash,
    )
    return navigation


def _answer_current_question(
    engine: RunEngine,
    run_id: str,
    *,
    answer: str,
    key: str,
):
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    work = continued.work_item
    assert work is not None
    assert work.operation is RunOperation.SUBMIT_QUESTION_STEP
    assert work.result_id is not None
    assert work.domain_id is not None
    assert work.question_id is not None
    assert work.session_content_hash is not None
    assert work.frontier_entry_hash is not None

    ledger = engine._bound_ledger(run_id)
    service = engine._question_session_service(ledger, run_id, work.result_id, work.domain_id)
    service.initialize()
    navigation = _close_workflow(service, work.question_id)
    bundle = engine.materialize_question_evidence_bundle(
        MaterializeQuestionEvidenceBundleRequest(
            contract_version="3.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key=f"idempotency:{key}:bundle",
            result_id=work.result_id,
            domain_id=work.domain_id,
            question_id=work.question_id,
            session_content_hash=work.session_content_hash,
            frontier_entry_hash=work.frontier_entry_hash,
            expected_navigation_state_hash=navigation.content_hash,
        )
    )
    response = engine.submit_question_step(
        SubmitQuestionStepRequest(
            contract_version="3.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key=f"idempotency:{key}:answer",
            result_id=work.result_id,
            domain_id=work.domain_id,
            question_id=work.question_id,
            session_content_hash=work.session_content_hash,
            frontier_entry_hash=work.frontier_entry_hash,
            answer=answer,
            rationale=f"Fixture answer for {work.question_id}.",
            evidence_bundle=bundle.evidence_bundle,
        )
    )
    return work, bundle.evidence_bundle, response


def test_public_correction_reopens_dependencies_and_rematerializes_terminal_result(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm_with_complete_source_roles(tmp_path)

    prerequisite = None
    for index in range(7):
        next_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert next_work is not None and next_work.question_id is not None
        question_id = next_work.question_id
        work, bundle, response = _answer_current_question(
            engine,
            run_id,
            answer=INITIAL_ANSWERS[question_id],
            key=f"seed-{index}",
        )
        if question_id == "sq:missing:data-available":
            prerequisite = (work, bundle, response)

    assert prerequisite is not None
    _, prerequisite_bundle, prerequisite_response = prerequisite
    assert prerequisite_response.correction_token is not None

    # Terminal materialization is deliberately invoked only for the fixture's
    # pre-correction state. The acceptance assertion below requires the public
    # corrected workflow to rematerialize its own successor.
    ledger = engine._bound_ledger(run_id)
    _seed_unrelated_domain_checkpoints(engine, run_id)
    engine._materialize_terminal(ledger, run_id, "result:a")
    engine._commit_run_completed_if_ready(ledger, run_id)
    assert engine._projection(ledger, run_id).run_state is RunState.COMPLETE
    assert (
        engine._result_state(engine._projection(ledger, run_id), "result:a")
        is ResultState.REPORT_READY
    )
    old_evidence = engine._current_checkpoint_event(
        ledger, "result:a", "checkpoint:evidence-missing"
    )
    old_answers = engine._current_checkpoint_event(ledger, "result:a", "checkpoint:answers-missing")
    assert old_evidence is not None and old_answers is not None

    original_step = next(
        item
        for item in engine._question_session_service(ledger, run_id, "result:a", "domain:missing")
        .load()
        .ledger.steps
        if item.question_id == "sq:missing:data-available"
    )
    correction = CorrectQuestionStepRequest(
        contract_version="3.0.0",
        run_id=run_id,
        work_token=prerequisite_response.correction_token,
        idempotency_key="idempotency:correct-missing-prerequisite",
        result_id="result:a",
        domain_id="domain:missing",
        question_id="sq:missing:data-available",
        session_content_hash=prerequisite_response.session_content_hash,
        prior_step_hash=original_step.content_hash,
        answer="no",
        rationale="The final attributable review shows data were not available.",
        evidence_bundle=prerequisite_bundle,
    )
    assert prerequisite_response.correction_token.model_copy(
        update={"trial_id": None}
    ) == engine._question_correction_work_item(
        run_id,
        "result:a",
        "domain:missing",
        "sq:missing:data-available",
        prerequisite_response.session_content_hash,
    ).work_token.model_copy(update={"trial_id": None})
    corrected = engine.correct_question_step(correction)
    assert corrected.committed is True
    assert corrected.run_state is RunState.ASSESSING
    assert corrected.result_state is ResultState.ASSESSING
    assert corrected.correction_token is not None
    assert old_answers.revision_id in {
        revision.revision_id for revision in ledger.current_revisions()
    }

    replay = engine.correct_question_step(correction)
    assert replay.committed is False
    with pytest.raises(InvalidRetrievalRequest, match="replayed differently"):
        engine.correct_question_step(
            correction.model_copy(update={"rationale": "Conflicting replay."})
        )
    with pytest.raises(StaleWorkTokenError):
        engine.correct_question_step(
            correction.model_copy(update={"idempotency_key": "idempotency:stale-correction"})
        )
    with pytest.raises(InvalidRetrievalRequest, match="predecessor is stale or conflicting"):
        engine.correct_question_step(
            correction.model_copy(
                update={
                    "work_token": corrected.correction_token,
                    "idempotency_key": "idempotency:conflicting-predecessor",
                    "session_content_hash": corrected.session_content_hash,
                }
            )
        )

    correction_sequence = max(
        event.sequence
        for event in ledger.events()
        if event.operation == "operation:correct-question-step"
    )
    assert not any(
        event.operation == "operation:result-report-ready"
        and event.scope == "result:a"
        and event.sequence > correction_sequence
        for event in ledger.events()
    )

    dependent = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert dependent.run_state is RunState.ASSESSING
    assert dependent.work_item is not None
    assert dependent.work_item.question_id == "sq:missing:evidence-unbiased"

    _answer_current_question(
        engine,
        run_id,
        answer="yes",
        key="newly-active-dependent",
    )

    projection = engine._projection(ledger, run_id)
    assert projection.run_state is RunState.COMPLETE
    assert engine._result_state(projection, "result:a") is ResultState.REPORT_READY
    current_evidence = engine._current_checkpoint_event(
        ledger, "result:a", "checkpoint:evidence-missing"
    )
    current_answers = engine._current_checkpoint_event(
        ledger, "result:a", "checkpoint:answers-missing"
    )
    assert current_evidence is not None and current_answers is not None
    assert current_evidence.supersedes_revision_id == old_evidence.revision_id
    assert current_answers.revision_id != old_answers.revision_id
    assert current_answers.entity_id == old_answers.entity_id
    current_revision_ids = {revision.revision_id for revision in ledger.current_revisions()}
    assert old_answers.revision_id not in current_revision_ids
    assert current_answers.revision_id in current_revision_ids

    effective = effective_question_steps(
        engine._question_session_service(ledger, run_id, "result:a", "domain:missing").load().ledger
    )
    assert {item.question_id: item.answer.value for item in effective} == {
        "sq:missing:data-available": "no",
        "sq:missing:evidence-unbiased": "yes",
    }
