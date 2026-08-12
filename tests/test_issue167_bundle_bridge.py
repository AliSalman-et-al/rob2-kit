"""v3 bridge coverage from materialized question evidence to a durable step."""

from rob2_kit.application.active_question_frontier import (
    QuestionAnswerCommitStep,
    evidence_closure_from_workflow,
)
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.question_evidence_bundle import materialize_question_evidence_bundle
from rob2_kit.application.question_evidence_session import QuestionEvidenceSessionStore
from tests.test_issue167_question_bundle import _input
from tests.test_question_evidence_session import _closed_workflow, _service_for, _two_peer_state


def test_materialized_bundle_binds_only_its_active_question_step(tmp_path) -> None:
    state = _two_peer_state()
    navigation = V3EvidenceNavigationStore(tmp_path)
    service = _service_for(state, QuestionEvidenceSessionStore(tmp_path), navigation)
    projection = service.initialize()
    question_id = projection.frontier.question_ids[0]
    workflow = _closed_workflow(service, navigation, question_id)

    # Materialize through the same exact session and runtime identities used
    # by the eventual question transition, rather than accepting caller-set
    # supporting polarity or no-information flags.
    bundle_input = _input(tmp_path / "bundle")
    bundle_input = bundle_input.model_copy(
        update={
            "session": service.load(),
            "workflow": workflow,
            "evidence_closure": evidence_closure_from_workflow(workflow),
        }
    )
    materialized = materialize_question_evidence_bundle(bundle_input)
    entry = next(item for item in projection.frontier.entries if item.question_id == question_id)
    step = QuestionAnswerCommitStep(
        step_id="step:bundle-bridge",
        question_id=question_id,
        answer="no_information",
        rationale="The closed v3 search produced a verified no-information basis.",
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=materialized.binding,
    )

    committed = service.commit_answer(
        expected_content_hash=projection.session_content_hash, step=step, workflow=workflow
    )

    assert committed.receipt.kind == "answer"
    assert committed.receipt.predecessor_session_hash == projection.session_content_hash
    assert service.load().ledger.steps == (step,)
    assert committed.projection.frontier.question_ids == ("sq:session:second",)
