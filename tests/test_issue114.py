"""Question-scoped terminal evidence sufficiency regressions (#114, migrated to v3)."""

import pytest

from rob2_kit.application.active_question_frontier import evidence_closure_from_workflow
from rob2_kit.application.question_evidence_bundle import (
    QuestionEvidenceBundleMaterializationError,
    materialize_question_evidence_bundle,
)
from rob2_kit.evidence.workflow import V3CandidateTriageRevision, V3PageExposure, V3TriageKind
from tests.test_issue167_question_bundle import _input


def test_closed_zero_hit_question_derives_an_engine_verified_no_information_basis(tmp_path) -> None:
    materialized = materialize_question_evidence_bundle(_input(tmp_path))

    assert materialized.binding.engine_verified_no_information_basis is not None
    assert materialized.pending_artifacts.bundle.no_information_basis is True
    assert materialized.pending_artifacts.coverage_receipt.stages


def test_unresolved_evidence_cannot_be_frozen_as_an_answer_basis(tmp_path) -> None:
    input = _input(tmp_path)
    workflow = input.workflow.model_copy(
        update={
            "exposures": (
                V3PageExposure(
                    attempt_id="attempt:issue114",
                    page_handle="page:issue114",
                    candidate_id="candidate:issue114",
                    canonical_unit_id="unit:issue114",
                    location_handle="location:issue114",
                    source_id=input.workflow.authorized_inventory[0].source_id,
                    source_artifact_hash=input.workflow.authorized_inventory[
                        0
                    ].source_artifact_hash,
                    parse_id=input.workflow.authorized_inventory[0].parse_id,
                    canonical_start=0,
                    canonical_end=1,
                    left_omitted_character_count=0,
                    right_omitted_character_count=0,
                    undisplayed_match_count=0,
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                    triage_flags={},
                ),
            ),
            "triage_revisions": (
                V3CandidateTriageRevision(
                    revision_id="triage:issue114",
                    attempt_id="attempt:issue114",
                    sq_id=input.workflow.question_id,
                    page_handle="page:issue114",
                    candidate_id="candidate:issue114",
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="The candidate remains materially ambiguous.",
                ),
            ),
        }
    )

    with pytest.raises(QuestionEvidenceBundleMaterializationError, match="material coverage"):
        materialize_question_evidence_bundle(
            input.model_copy(
                update={
                    "workflow": workflow,
                    "evidence_closure": evidence_closure_from_workflow(workflow),
                }
            )
        )
