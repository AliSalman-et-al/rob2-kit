"""Focused private ledger tests for incremental signaling-question work."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.application.active_question_frontier import (
    ActiveQuestionLedger,
    AssessorInputActivationFact,
    DomainJudgmentActivationFact,
    QuestionAnswerCommitStep,
    QuestionAnswerCorrection,
    QuestionDiagnosticStop,
    QuestionEvidenceBundleBinding,
    active_question_frontier,
    append_question_answer,
    append_question_correction,
    append_question_diagnostic_stop,
    effective_question_steps,
    evidence_closure_from_workflow,
    evidence_diagnostic_from_workflow,
    new_active_question_ledger,
)
from rob2_kit.domain.assessment import JudgmentLevel
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import SearchQuery
from rob2_kit.evidence.workflow import (
    V3AcquisitionAttemptReceipt,
    V3AuthorizedSource,
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
    V3EvidenceWorkflowState,
    V3ExposedPage,
    V3MaterializedStageScope,
    V3NavigationCompletionReceipt,
    V3PageExposure,
    V3SearchAttempt,
    V3TriageKind,
)
from rob2_kit.logic.packs import LogicPack, load_logic_pack

PACK_ROOT = Path(__file__).parents[1] / "packs"


@pytest.fixture(scope="module")
def logic() -> LogicPack:
    return load_logic_pack(PACK_ROOT / "logic" / "rob2-parallel-assignment-2019.1.yaml")


def _closed_workflow(
    question_id: str, *, snapshot: int = 1, domain_id: str = "domain:deviations"
) -> V3EvidenceWorkflowState:
    """Build a valid two-pass closed workflow, one receipt per static stage."""

    obligation = EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": question_id,
            "propositions": [
                {
                    "id": "proposition:frontier:test",
                    "statement": "Attributable evidence closure.",
                    "accepted_source_roles": ["primary_report"],
                    "evidence_passes": [
                        {
                            "id": "pass:frontier:seed",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": "stage:frontier:seed",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:frontier:seed",
                                            "kind": "structural_read",
                                            "structural_targets": ["methods"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "pass:frontier:contradiction",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": "stage:frontier:contradiction",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:frontier:contradiction",
                                            "kind": "structural_read",
                                            "structural_targets": ["discussion"],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )
    source = V3AuthorizedSource(
        source_id="source:frontier",
        roles=("primary_report",),
        source_artifact_hash=canonical_hash({"source": snapshot}),
        parse_id="parse:frontier",
        parse_output_hash=canonical_hash({"parse": snapshot}),
    )
    scopes = tuple(
        V3MaterializedStageScope(
            scope_id=f"scope:{stage.id[6:]}",
            proposition_id=proposition.id,
            pass_id=evidence_pass.id,
            stage_id=stage.id,
            authorized_source_ids=(source.source_id,),
            authorized_source_scope_hash=canonical_hash((source.source_id,)),
        )
        for proposition in obligation.propositions
        for evidence_pass in proposition.evidence_passes
        for stage in evidence_pass.coverage_stages
    )
    state = V3EvidenceWorkflowState(
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id=domain_id,
        question_id=question_id,
        snapshot_hash=canonical_hash({"snapshot": snapshot}),
        obligation_revision_id="revision:frontier",
        obligation=obligation,
        obligation_hash=canonical_hash(obligation),
        inventory_snapshot_hash=canonical_hash((source.model_dump(mode="json"),)),
        authorized_inventory=(source,),
        search_policy_id="policy:frontier:search",
        search_policy_hash=canonical_hash({"search": snapshot}),
        read_policy_id="policy:frontier:read",
        read_policy_hash=canonical_hash({"read": snapshot}),
        visual_policy_id="policy:frontier:visual",
        visual_policy_hash=canonical_hash({"visual": snapshot}),
        stage_scopes=scopes,
    )
    receipts = []
    outcomes = []
    for scope in scopes:
        intent_id = next(
            stage.navigation_intents[0].id
            for proposition in obligation.propositions
            if proposition.id == scope.proposition_id
            for evidence_pass in proposition.evidence_passes
            if evidence_pass.id == scope.pass_id
            for stage in evidence_pass.coverage_stages
            if stage.id == scope.stage_id
        )
        receipt_payload = {
            "receipt_id": f"receipt:{scope.stage_id[6:]}",
            "issuance_id": f"issuance:{scope.stage_id[6:]}",
            "proposition_id": scope.proposition_id,
            "pass_id": scope.pass_id,
            "stage_id": scope.stage_id,
            "intent_id": intent_id,
            "kind": "structural_read",
            "source_scope_hash": scope.authorized_source_scope_hash,
            "snapshot_hash": state.snapshot_hash,
            "read_policy_id": state.read_policy_id,
            "read_policy_hash": state.read_policy_hash,
            "visual_policy_id": None,
            "visual_policy_hash": None,
            "receipt_hash": None,
        }
        receipt = V3NavigationCompletionReceipt.model_validate(
            receipt_payload | {"receipt_hash": canonical_hash(receipt_payload)}
        )
        receipts.append(receipt)
        outcome_payload = {
            "submission_id": f"submission:{scope.stage_id[6:]}",
            "run_id": state.run_id,
            "result_id": state.result_id,
            "domain_id": state.domain_id,
            "question_id": question_id,
            "obligation_revision_id": state.obligation_revision_id,
            "obligation_hash": state.obligation_hash,
            "inventory_snapshot_hash": state.inventory_snapshot_hash,
            "proposition_id": scope.proposition_id,
            "pass_id": scope.pass_id,
            "stage_id": scope.stage_id,
            "materialized_scope_id": scope.scope_id,
            "outcome_kind": "obligation_satisfied",
            "rationale": "Each required stage is closed.",
            "trigger_dispositions": (),
            "acquisition_receipt_id": None,
            "content_hash": None,
        }
        outcomes.append(
            V3EvidenceStageOutcomeSubmission.model_validate(
                outcome_payload | {"content_hash": canonical_hash(outcome_payload)}
            )
        )
    return state.model_copy(
        update={
            "issued_receipt_hashes": tuple(
                (item.issuance_id, item.receipt_hash) for item in receipts
            ),
            "completion_receipts": tuple(receipts),
            "stage_outcomes": tuple(outcomes),
        }
    )


def _step(
    ledger: ActiveQuestionLedger, question_id: str, answer: str, workflow
) -> QuestionAnswerCommitStep:
    frontier = active_question_frontier(ledger)
    entry = next(item for item in frontier.entries if item.question_id == question_id)
    return QuestionAnswerCommitStep(
        step_id=f"step:{question_id[3:]}",
        question_id=question_id,
        answer=answer,
        rationale="Attributable answer rationale.",
        logic_pack_family_id=ledger.logic_pack.family_id,
        logic_pack_release_id=ledger.logic_pack.release_id,
        logic_pack_hash=ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, question_id),
    )


def _bundle_binding(
    workflow: V3EvidenceWorkflowState, question_id: str
) -> QuestionEvidenceBundleBinding:
    return QuestionEvidenceBundleBinding(
        question_id=question_id,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        bundle_revision_id=f"revision:bundle:{question_id[3:]}",
        bundle_content_hash=canonical_hash({"bundle": question_id}),
        supporting_evidence_ids=(f"claim:supporting:{question_id[3:]}",),
    )


def _ledger(logic: LogicPack) -> ActiveQuestionLedger:
    return new_active_question_ledger(
        logic,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:deviations",
    )


def _semantic_terminal_workflow(question_id: str) -> V3EvidenceWorkflowState:
    """A reducer-shaped exhausted unresolved-search workflow for stop testing."""

    closed = _closed_workflow(question_id)
    obligation_payload = closed.obligation.model_dump(mode="json")
    for evidence_pass in obligation_payload["propositions"][0]["evidence_passes"]:
        intent = evidence_pass["coverage_stages"][0]["navigation_intents"][0]
        intent_id = intent["id"]
        intent.clear()
        intent.update({"id": intent_id, "kind": "search", "terms": ["term"]})
    obligation = EvidenceSearchObligation.model_validate(obligation_payload)
    attempts = []
    pages = []
    exposures = []
    triage = []
    outcomes = []
    for index, scope in enumerate(closed.stage_scopes, start=1):
        attempt = V3SearchAttempt(
            attempt_id=f"attempt:semantic:{index}",
            proposition_id=scope.proposition_id,
            pass_id=scope.pass_id,
            stage_id=scope.stage_id,
            intent_id=next(
                stage.navigation_intents[0].id
                for proposition in obligation.propositions
                for evidence_pass in proposition.evidence_passes
                if evidence_pass.id == scope.pass_id
                for stage in evidence_pass.coverage_stages
                if stage.id == scope.stage_id
            ),
            query=SearchQuery(terms=("term",), source_ids=("source:frontier",)),
            query_hash=canonical_hash(
                SearchQuery(terms=("term",), source_ids=("source:frontier",))
            ),
            source_scope_hash=scope.authorized_source_scope_hash,
        )
        candidate_id = f"candidate:semantic:{index}"
        page_handle = f"page:semantic:{index}"
        attempts.append(attempt)
        if index == 1:
            pages.append(
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_ids=(),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                )
            )
            outcome_kind = "obligation_satisfied"
        else:
            outcome_kind = "semantic_uncertainty_unresolved"
            pages.append(
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_ids=(candidate_id,),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                )
            )
            exposures.append(
                V3PageExposure(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_id=candidate_id,
                    canonical_unit_id=f"unit:semantic:{index}",
                    location_handle=f"location:semantic:{index}",
                    source_id="source:frontier",
                    source_artifact_hash=closed.authorized_inventory[0].source_artifact_hash,
                    parse_id="parse:frontier",
                    canonical_start=0,
                    canonical_end=1,
                    left_omitted_character_count=0,
                    right_omitted_character_count=0,
                    undisplayed_match_count=0,
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                    triage_flags={},
                )
            )
            triage.append(
                V3CandidateTriageRevision(
                    revision_id=f"triage:semantic:{index}",
                    attempt_id=attempt.attempt_id,
                    sq_id=question_id,
                    page_handle=page_handle,
                    candidate_id=candidate_id,
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="Material ambiguity remains.",
                )
            )
        outcome_payload = {
            **closed.stage_outcomes[index - 1].model_dump(mode="json"),
            "obligation_hash": canonical_hash(obligation),
            "outcome_kind": outcome_kind,
            "content_hash": None,
        }
        outcomes.append(
            V3EvidenceStageOutcomeSubmission.model_validate(
                outcome_payload | {"content_hash": canonical_hash(outcome_payload)}
            )
        )
    return closed.model_copy(
        update={
            "obligation": obligation,
            "obligation_hash": canonical_hash(obligation),
            "attempts": tuple(attempts),
            "pages": tuple(pages),
            "exposures": tuple(exposures),
            "triage_revisions": tuple(triage),
            "stage_outcomes": tuple(outcomes),
        }
    )


def _escalated_unavailable_workflow(question_id: str) -> V3EvidenceWorkflowState:
    workflow = _semantic_terminal_workflow(question_id)
    obligation_payload = workflow.obligation.model_dump(mode="json")
    first, second = [
        item["coverage_stages"][0]["id"]
        for item in obligation_payload["propositions"][0]["evidence_passes"]
    ]
    obligation_payload["escalation_triggers"] = [
        {
            "id": "trigger:frontier:escalate",
            "condition": "no_direct_evidence",
            "source_stage_id": first,
            "target_stage_id": second,
        }
    ]
    obligation = EvidenceSearchObligation.model_validate(obligation_payload)
    target_scope = next(item for item in workflow.stage_scopes if item.stage_id == second)
    receipt_payload = {
        "receipt_id": "receipt:frontier:acquisition",
        "issuance_id": "issuance:frontier:acquisition",
        "run_id": workflow.run_id,
        "result_id": workflow.result_id,
        "domain_id": workflow.domain_id,
        "question_id": workflow.question_id,
        "proposition_id": target_scope.proposition_id,
        "pass_id": target_scope.pass_id,
        "stage_id": target_scope.stage_id,
        "materialized_scope_id": target_scope.scope_id,
        "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
        "unavailable_source_ids": ["source:frontier"],
        "limitation_hash": canonical_hash({"limited": True}),
        "receipt_hash": None,
    }
    receipt = V3AcquisitionAttemptReceipt.model_validate(
        receipt_payload | {"receipt_hash": canonical_hash(receipt_payload)}
    )
    outcomes = []
    for outcome in workflow.stage_outcomes:
        payload = outcome.model_dump(mode="json")
        payload["obligation_hash"] = canonical_hash(obligation)
        if payload["stage_id"] == first:
            payload.update(
                {
                    "outcome_kind": "escalation_required",
                    "trigger_dispositions": [
                        {
                            "trigger_id": "trigger:frontier:escalate",
                            "kind": "true",
                            "rationale": "Direct evidence escalated.",
                        }
                    ],
                }
            )
        elif payload["stage_id"] == second:
            payload.update(
                {
                    "outcome_kind": "source_unavailable_after_attempt",
                    "trigger_dispositions": [],
                    "acquisition_receipt_id": receipt.receipt_id,
                }
            )
        payload["content_hash"] = None
        outcomes.append(
            V3EvidenceStageOutcomeSubmission.model_validate(
                payload | {"content_hash": canonical_hash(payload)}
            )
        )
    return workflow.model_copy(
        update={
            "obligation": obligation,
            "obligation_hash": canonical_hash(obligation),
            "issued_acquisition_receipt_hashes": ((receipt.issuance_id, receipt.receipt_hash),),
            "acquisition_receipts": (receipt,),
            "stage_outcomes": tuple(outcomes),
        }
    )


def test_conditional_question_waits_for_answer_and_false_condition_stays_inactive(
    logic: LogicPack,
) -> None:
    ledger = _ledger(logic)
    assert "sq:deviations:context-deviations" not in active_question_frontier(ledger).question_ids

    question_id = "sq:deviations:participants-aware"
    workflow = _closed_workflow(question_id)
    ledger = append_question_answer(ledger, _step(ledger, question_id, "yes", workflow), workflow)
    assert "sq:deviations:context-deviations" in active_question_frontier(ledger).question_ids

    false_ledger = _ledger(logic)
    false_workflow = _closed_workflow(question_id, snapshot=2)
    false_ledger = append_question_answer(
        false_ledger, _step(false_ledger, question_id, "no", false_workflow), false_workflow
    )
    assert (
        "sq:deviations:context-deviations"
        not in active_question_frontier(false_ledger).question_ids
    )


def test_correction_replays_effective_history_and_reopens_invalidated_dependency(
    logic: LogicPack,
) -> None:
    ledger = _ledger(logic)
    prerequisite = "sq:deviations:participants-aware"
    workflow = _closed_workflow(prerequisite)
    original = _step(ledger, prerequisite, "yes", workflow)
    ledger = append_question_answer(ledger, original, workflow)
    dependent = "sq:deviations:context-deviations"
    dependent_workflow = _closed_workflow(dependent, snapshot=2)
    ledger = append_question_answer(
        ledger, _step(ledger, dependent, "no", dependent_workflow), dependent_workflow
    )

    correction = QuestionAnswerCorrection(
        correction_id="correction:participants-aware",
        question_id=prerequisite,
        prior_step_hash=original.content_hash,
        answer="no",
        rationale="The final review found participants were not aware.",
        logic_pack_family_id=logic.family_id,
        logic_pack_release_id=logic.release_id,
        logic_pack_hash=logic.content_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=original.evidence_bundle,
    )
    corrected = append_question_correction(ledger, correction)

    assert {item.question_id for item in effective_question_steps(corrected)} == {prerequisite}
    assert dependent not in active_question_frontier(corrected).question_ids
    with pytest.raises(ValueError, match="stale or conflicting"):
        append_question_correction(
            corrected, correction.model_copy(update={"correction_id": "correction:stale"})
        )


def test_peer_order_is_declared_and_peer_commits_do_not_lock_each_other(logic: LogicPack) -> None:
    ledger = _ledger(logic)
    initial = active_question_frontier(ledger)
    assert (initial.run_id, initial.result_id, initial.domain_id) == (
        "run:frontier",
        "result:frontier",
        "domain:deviations",
    )
    other_scope = new_active_question_ledger(
        logic,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:randomization",
    )
    assert active_question_frontier(other_scope).frontier_hash != initial.frontier_hash
    peers = (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
        "sq:deviations:appropriate-analysis",
    )
    assert (
        tuple(question_id for question_id in initial.question_ids if question_id in peers) == peers
    )

    peer_workflow = _closed_workflow(peers[1])
    peer_step = _step(ledger, peers[1], "no", peer_workflow)
    first_workflow = _closed_workflow(peers[0], snapshot=2)
    ledger = append_question_answer(
        ledger, _step(ledger, peers[0], "no", first_workflow), first_workflow
    )
    assert append_question_answer(ledger, peer_step, peer_workflow).steps[-1] == peer_step


def test_commit_rejects_stale_conflicting_cross_domain_and_evidence_mismatch(
    logic: LogicPack,
) -> None:
    ledger = _ledger(logic)
    question_id = "sq:deviations:participants-aware"
    workflow = _closed_workflow(question_id)
    step = _step(ledger, question_id, "yes", workflow)
    committed = append_question_answer(ledger, step, workflow)
    assert append_question_answer(committed, step, workflow) is committed

    with pytest.raises(ValueError, match="replayed with different content"):
        append_question_answer(committed, step.model_copy(update={"answer": "no"}), workflow)
    with pytest.raises(ValueError, match="replayed with different content"):
        append_question_answer(
            committed,
            step.model_copy(update={"rationale": "Different attributable rationale."}),
            workflow,
        )
    with pytest.raises(ValidationError, match="rationale cannot be blank"):
        QuestionAnswerCommitStep.model_validate(step.model_dump(mode="json") | {"rationale": " "})
    invalid_bundle = step.evidence_bundle.model_dump(mode="json") | {
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "engine_verified_no_information_basis": None,
    }
    with pytest.raises(ValidationError, match="requires qualifying claims"):
        QuestionEvidenceBundleBinding.model_validate(invalid_bundle)
    with pytest.raises(ValidationError, match="must bind the same question"):
        QuestionAnswerCommitStep.model_validate(
            step.model_dump(mode="json")
            | {
                "evidence_bundle": step.evidence_bundle.model_dump(mode="json")
                | {"question_id": "sq:deviations:personnel-aware"}
            }
        )
    with pytest.raises(ValidationError, match="must match the closure scope"):
        QuestionAnswerCommitStep.model_validate(
            step.model_dump(mode="json")
            | {
                "evidence_bundle": step.evidence_bundle.model_dump(mode="json")
                | {"domain_id": "domain:randomization"}
            }
        )
    with pytest.raises(ValueError, match="stale dependency/frontier"):
        append_question_answer(
            _ledger(logic),
            step.model_copy(update={"expected_frontier_entry_hash": canonical_hash({})}),
            workflow,
        )
    cross_domain = step.model_copy(
        update={"question_id": "sq:randomization:sequence", "step_id": "step:cross-domain"}
    )
    with pytest.raises(ValueError, match="outside the ledger Domain"):
        append_question_answer(_ledger(logic), cross_domain, workflow)
    with pytest.raises(ValueError, match="does not match"):
        append_question_answer(_ledger(logic), step, _closed_workflow(question_id, snapshot=3))


def test_ledger_history_is_content_bound_and_incomplete_evidence_cannot_commit(
    logic: LogicPack,
) -> None:
    ledger = _ledger(logic)
    workflow = _closed_workflow("sq:deviations:participants-aware")
    step = _step(ledger, "sq:deviations:participants-aware", "yes", workflow)
    committed = append_question_answer(ledger, step, workflow)
    payload = committed.model_dump(mode="json")
    payload["steps"][0]["answer"] = "no"
    with pytest.raises(ValidationError, match="commit hash|history hash"):
        ActiveQuestionLedger.model_validate(payload)
    with pytest.raises(ValueError, match="not procedurally closed"):
        evidence_closure_from_workflow(workflow.model_copy(update={"completion_receipts": ()}))


def test_complete_frontier_is_detected_without_publishing_a_domain(logic: LogicPack) -> None:
    payload = logic.model_dump(exclude={"content_hash"})
    payload.update(
        {
            "questions": [{"id": "sq:test:only"}],
            "domains": [
                {
                    "id": "domain:test",
                    "question_ids": ["sq:test:only"],
                    "judgment_rules": [
                        {
                            "id": "rule:test:domain",
                            "when": {
                                "op": "answer_in",
                                "question_id": "sq:test:only",
                                "answers": ["yes"],
                            },
                            "judgment": "low",
                        },
                        {
                            "id": "rule:test:domain-fallback",
                            "when": {
                                "op": "answer_in",
                                "question_id": "sq:test:only",
                                "answers": ["probably_yes", "probably_no", "no", "no_information"],
                            },
                            "judgment": "some_concerns",
                        },
                    ],
                }
            ],
            "assessor_inputs": [],
            "overall_rules": [
                {
                    "id": "rule:test:overall",
                    "when": {"op": "domain_all", "judgments": ["low"]},
                    "judgment": "low",
                },
                {
                    "id": "rule:test:overall-fallback",
                    "when": {"op": "domain_any", "judgments": ["some_concerns"]},
                    "judgment": "some_concerns",
                },
            ],
            "inventory": [
                "sq:test:only",
                "domain:test",
                "rule:test:domain",
                "rule:test:domain-fallback",
                "rule:test:overall",
                "rule:test:overall-fallback",
            ],
        }
    )
    isolated = LogicPack.model_validate(payload)
    ledger = new_active_question_ledger(
        isolated,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:test",
    )
    workflow = _closed_workflow("sq:test:only", domain_id="domain:test")
    ledger = append_question_answer(
        ledger, _step(ledger, "sq:test:only", "yes", workflow), workflow
    )
    assert active_question_frontier(ledger).complete is True


def test_frontier_binds_input_and_prior_domain_activation_context(logic: LogicPack) -> None:
    payload = logic.model_dump(exclude={"content_hash"})
    questions = {item["id"]: item for item in payload["questions"]}
    questions["sq:deviations:context-deviations"]["active_if"] = {
        "op": "input_equals",
        "input_id": "input:combined-concerns",
        "value": True,
    }
    questions["sq:deviations:affected-outcome"]["active_if"] = {
        "op": "domain_all",
        "judgments": ["low"],
    }
    custom = LogicPack.model_validate(payload)
    baseline = new_active_question_ledger(
        custom,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:deviations",
    )
    with_input = new_active_question_ledger(
        custom,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:deviations",
        assessor_inputs=(
            AssessorInputActivationFact(input_id="input:combined-concerns", value=True),
        ),
    )
    with_judgment = new_active_question_ledger(
        custom,
        run_id="run:frontier",
        result_id="result:frontier",
        domain_id="domain:deviations",
        prior_domain_judgments=(
            DomainJudgmentActivationFact(
                domain_id="domain:randomization", judgment=JudgmentLevel.LOW
            ),
        ),
    )
    assert "sq:deviations:context-deviations" not in active_question_frontier(baseline).question_ids
    assert "sq:deviations:context-deviations" in active_question_frontier(with_input).question_ids
    assert "sq:deviations:affected-outcome" in active_question_frontier(with_judgment).question_ids
    assert (
        active_question_frontier(with_input).frontier_hash
        != active_question_frontier(baseline).frontier_hash
    )
    assert (
        active_question_frontier(with_judgment).frontier_hash
        != active_question_frontier(baseline).frontier_hash
    )


def test_diagnostic_stop_is_non_answer_terminal_and_preserves_peer_work(logic: LogicPack) -> None:
    ledger = _ledger(logic)
    question_id = "sq:deviations:participants-aware"
    workflow = _semantic_terminal_workflow(question_id)
    entry = next(
        item for item in active_question_frontier(ledger).entries if item.question_id == question_id
    )
    stop = QuestionDiagnosticStop(
        stop_id="stop:deviations:participants-aware",
        question_id=question_id,
        logic_pack_family_id=logic.family_id,
        logic_pack_release_id=logic.release_id,
        logic_pack_hash=logic.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_diagnostic=evidence_diagnostic_from_workflow(workflow),
    )
    stopped = append_question_diagnostic_stop(ledger, stop, workflow)
    frontier = active_question_frontier(stopped)
    assert question_id not in frontier.question_ids
    assert "sq:deviations:context-deviations" not in frontier.question_ids
    peer = "sq:deviations:personnel-aware"
    peer_workflow = _closed_workflow(peer, snapshot=7)
    assert append_question_answer(stopped, _step(stopped, peer, "no", peer_workflow), peer_workflow)
    with pytest.raises(ValueError, match="terminal diagnostic"):
        evidence_diagnostic_from_workflow(workflow.model_copy(update={"pages": ()}))


def test_diagnostic_terminal_accepts_mixed_and_escalated_limitation_paths() -> None:
    mixed = _semantic_terminal_workflow("sq:deviations:participants-aware")
    assert evidence_diagnostic_from_workflow(mixed).question_id == mixed.question_id

    escalated = _escalated_unavailable_workflow("sq:deviations:participants-aware")
    assert (
        evidence_diagnostic_from_workflow(escalated).workflow_state_hash == escalated.content_hash
    )
    missing_target = escalated.model_copy(update={"stage_outcomes": escalated.stage_outcomes[:1]})
    with pytest.raises(ValueError, match="terminal diagnostic"):
        evidence_diagnostic_from_workflow(missing_target)
