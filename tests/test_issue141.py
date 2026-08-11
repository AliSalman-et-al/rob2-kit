"""Exact v3 question-step retry identity regressions (#141)."""

import pytest

from rob2_kit.application.active_question_frontier import (
    QuestionAnswerCommitStep,
    evidence_closure_from_workflow,
)
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.question_evidence_session import (
    QuestionEvidenceSessionStore,
    StaleQuestionEvidenceSession,
)
from tests.test_question_evidence_session import (
    _bundle_binding,
    _closed_workflow,
    _service_for,
    _two_peer_state,
)


def test_question_step_replay_requires_the_exact_predecessor_and_semantics(tmp_path) -> None:
    state = _two_peer_state()
    service = _service_for(
        state, QuestionEvidenceSessionStore(tmp_path), V3EvidenceNavigationStore(tmp_path)
    )
    before = service.initialize()
    question_id = before.frontier.question_ids[0]
    workflow = _closed_workflow(service, V3EvidenceNavigationStore(tmp_path), question_id)
    entry = next(item for item in before.frontier.entries if item.question_id == question_id)
    step = QuestionAnswerCommitStep(
        step_id="step:issue141",
        question_id=question_id,
        answer="yes",
        rationale="The closed question has an attributable basis.",
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, question_id),
    )
    committed = service.commit_answer(
        expected_content_hash=before.session_content_hash, step=step, workflow=workflow
    )
    replay = service.commit_answer(
        expected_content_hash=before.session_content_hash, step=step, workflow=workflow
    )

    assert replay.replayed is True
    assert replay.receipt == committed.receipt
    changed = QuestionAnswerCommitStep(
        step_id="step:issue141:different",
        question_id=question_id,
        answer="no",
        rationale="Different semantics.",
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, question_id),
    )
    with pytest.raises(StaleQuestionEvidenceSession):
        service.commit_answer(
            expected_content_hash=before.session_content_hash, step=changed, workflow=workflow
        )
