"""Receipt-bound review and passage materialization regressions (#135, v3)."""

import pytest

from rob2_kit.application.active_question_frontier import evidence_closure_from_workflow
from rob2_kit.application.question_evidence_bundle import (
    QuestionEvidenceBundleMaterializationError,
    materialize_question_evidence_bundle,
)
from rob2_kit.evidence.workflow import V3CandidateTriageRevision, V3TriageKind
from tests.test_issue167_question_bundle import _input


def test_retained_candidate_requires_a_current_resolved_review_before_freezing(tmp_path) -> None:
    input = _input(tmp_path)
    workflow = input.workflow.model_copy(
        update={
            "triage_revisions": (
                V3CandidateTriageRevision(
                    revision_id="triage:issue135",
                    attempt_id="attempt:issue135",
                    sq_id=input.workflow.question_id,
                    page_handle="page:issue135",
                    candidate_id="candidate:issue135",
                    kind=V3TriageKind.RETAINED,
                    read_view_receipt="read-view:issue135",
                ),
            )
        }
    )

    with pytest.raises(QuestionEvidenceBundleMaterializationError, match="retained candidate"):
        materialize_question_evidence_bundle(
            input.model_copy(
                update={
                    "workflow": workflow,
                    "evidence_closure": evidence_closure_from_workflow(workflow),
                }
            )
        )


def test_zero_hit_materialization_has_no_claim_or_conflict_input_to_freeze(tmp_path) -> None:
    materialized = materialize_question_evidence_bundle(_input(tmp_path))

    assert materialized.pending_artifacts.bundle.items == ()
    assert materialized.pending_artifacts.bundle.conflicts == ()
    assert materialized.binding.engine_verified_no_information_basis is not None
