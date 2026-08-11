"""Focused pure-materializer tests for the v3 question Evidence Bundle seam."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.application.active_question_frontier import evidence_closure_from_workflow
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.question_evidence_bundle import (
    QuestionEvidenceBundleMaterializationError,
    QuestionEvidenceBundleMaterializationInput,
    ResolvedQuestionEvidenceClaim,
    ResolvedQuestionEvidenceReview,
    materialize_question_evidence_bundle,
)
from rob2_kit.application.question_evidence_session import QuestionEvidenceSessionStore
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import (
    EvidenceClaim,
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    ReviewedEvidenceContext,
    ReviewedEvidenceFragment,
    TrialAttribution,
)
from rob2_kit.domain.revisions import Actor, Dependency, RecordReference
from rob2_kit.evidence.workflow import (
    V3CandidateTriageRevision,
    V3PageExposure,
    V3TriageKind,
)

sys.path.insert(0, str(Path(__file__).parent))

# The session tests own the compact, valid two-question v3 fixture. This module
# deliberately only tests materialization, not session construction.
from test_question_evidence_session import _closed_workflow, _service_for, _two_peer_state


def _reference(entity_id: str, revision_id: str) -> RecordReference:
    return RecordReference(
        entity_id=entity_id,
        revision_id=revision_id,
        content_hash=canonical_hash({"entity_id": entity_id, "revision_id": revision_id}),
    )


def _input(tmp_path, *, workflow=None) -> QuestionEvidenceBundleMaterializationInput:
    session = _two_peer_state()
    navigation = V3EvidenceNavigationStore(tmp_path)
    service = _service_for(session, QuestionEvidenceSessionStore(tmp_path), navigation)
    service.initialize()
    workflow = workflow or _closed_workflow(service, navigation, "sq:session:first")
    return QuestionEvidenceBundleMaterializationInput(
        materialization_id="materialization:bundle-test",
        session=session,
        workflow=workflow,
        evidence_closure=evidence_closure_from_workflow(workflow),
        result_spec=_reference("result-spec:bundle-test", "revision:result-spec-bundle-test"),
        actor=Actor(kind="system", actor_id="actor:bundle-test", display_name="Bundle test"),
        observed_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def test_clean_zero_hit_workflow_derives_typed_no_information_and_is_deterministic(
    tmp_path,
) -> None:
    input = _input(tmp_path)

    first = materialize_question_evidence_bundle(input)
    second = materialize_question_evidence_bundle(input)

    assert first == second
    assert first.binding.engine_verified_no_information_basis is not None
    assert first.pending_artifacts.bundle.no_information_basis is True
    assert first.pending_artifacts.bundle.v3_coverage_receipt is not None
    assert first.pending_artifacts.coverage_receipt.stages
    assert len(first.pending_references) == 4


def test_retained_candidate_without_resolved_review_cannot_become_no_information(tmp_path) -> None:
    input = _input(tmp_path)
    workflow = input.workflow.model_copy(
        update={
            "triage_revisions": (
                V3CandidateTriageRevision(
                    revision_id="triage:bundle-test",
                    attempt_id="attempt:bundle-test",
                    sq_id=input.workflow.question_id,
                    page_handle="page:bundle-test",
                    candidate_id="candidate:bundle-test",
                    kind=V3TriageKind.RETAINED,
                    read_view_receipt="read-view:bundle-test",
                ),
            ),
        }
    )
    # The forged state has a retained candidate, so materialization must not
    # silently convert zero claims into an answer basis.
    forged = input.model_copy(
        update={"workflow": workflow, "evidence_closure": evidence_closure_from_workflow(workflow)}
    )
    with pytest.raises(QuestionEvidenceBundleMaterializationError, match="retained candidate"):
        materialize_question_evidence_bundle(forged)


def test_supporting_and_contradicting_claims_are_derived_from_review_spans(tmp_path) -> None:
    input = _input(tmp_path)
    source = input.workflow.authorized_inventory[0]
    unit = _reference("unit:bundle-test", "revision:unit-bundle-test")
    source_ref = _reference(source.source_id, "revision:source-bundle-test")
    candidates = ("candidate:bundle-supporting", "candidate:bundle-contradicting")
    workflow = input.workflow.model_copy(
        update={
            "exposures": tuple(
                V3PageExposure(
                    attempt_id=f"attempt:bundle-{index}",
                    page_handle=f"page:bundle-{index}",
                    candidate_id=candidate_id,
                    canonical_unit_id=unit.entity_id,
                    location_handle=f"location:bundle-{index}",
                    source_id=source.source_id,
                    source_artifact_hash=source.source_artifact_hash,
                    parse_id=source.parse_id,
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
                for index, candidate_id in enumerate(candidates, start=1)
            ),
            "triage_revisions": tuple(
                V3CandidateTriageRevision(
                    revision_id=f"triage:bundle-{index}",
                    attempt_id=f"attempt:bundle-{index}",
                    sq_id=input.workflow.question_id,
                    page_handle=f"page:bundle-{index}",
                    candidate_id=candidate_id,
                    kind=V3TriageKind.RETAINED,
                    read_view_receipt=f"read-view:bundle-{index}",
                )
                for index, candidate_id in enumerate(candidates, start=1)
            ),
        }
    )
    reviews, claims = [], []
    for index, (candidate_id, disposition) in enumerate(
        zip(
            candidates,
            (EvidenceReviewDisposition.SUPPORTING, EvidenceReviewDisposition.CONTRADICTING),
            strict=True,
        ),
        start=1,
    ):
        review = EvidenceReviewRevision(
            entity_id=f"evidence-review:bundle-{index}",
            revision_id=f"revision:evidence-review-bundle-{index}",
            actor=input.actor,
            observed_at=input.observed_at,
            candidate_id=candidate_id,
            result_id=workflow.result_id,
            domain_id=workflow.domain_id,
            sq_id=workflow.question_id,
            spans=(
                EvidenceReviewSpan(
                    span_id=f"span:bundle-{index}",
                    span_start=0,
                    span_end=1,
                    trial_attribution=TrialAttribution.ACTIVE,
                    disposition=disposition,
                    rationale="Attributable reviewed evidence.",
                    attribution_rationale="Explicitly names the active trial.",
                    reviewed_context=ReviewedEvidenceContext(
                        receipt_hash=canonical_hash({"receipt": index}),
                        snapshot_hash=canonical_hash({"snapshot": index}),
                        requested_mode="detail",
                        applied_mode="detail",
                        fragments=(
                            ReviewedEvidenceFragment(
                                unit_id=unit.entity_id,
                                source_id=source_ref.entity_id,
                                source_artifact_hash=source.source_artifact_hash,
                                parse_id=source.parse_id,
                                canonicalization_version="1",
                                unit_content_hash=canonical_hash({"unit": index}),
                                span_start=0,
                                span_end=1,
                                content_hash=canonical_hash({"fragment": index}),
                            ),
                        ),
                    ),
                ),
            ),
        )
        review_ref = RecordReference(
            entity_id=review.entity_id,
            revision_id=review.revision_id,
            content_hash=canonical_hash(review),
        )
        claim = EvidenceClaim(
            entity_id=f"claim:bundle-{index}",
            revision_id=f"revision:claim-bundle-{index}",
            dependencies=(
                Dependency(**unit.model_dump(), role="dependency:canonical-unit"),
                Dependency(**source_ref.model_dump(), role="dependency:source"),
                Dependency(**review_ref.model_dump(), role="dependency:evidence-review"),
            ),
            actor=input.actor,
            observed_at=input.observed_at,
            canonical_unit=unit,
            source=source_ref,
            authorizing_review=review_ref,
            review_span_id=f"span:bundle-{index}",
            candidate_id=candidate_id,
            span_start=0,
            span_end=1,
            quoted_text_hash=canonical_hash({"quote": index}),
            claim_type="claim-type:bundle-test",
            verification_status="machine_verified",
        )
        reviews.append(ResolvedQuestionEvidenceReview(review=review, reference=review_ref))
        claims.append(
            ResolvedQuestionEvidenceClaim(
                claim=claim,
                reference=RecordReference(
                    entity_id=claim.entity_id,
                    revision_id=claim.revision_id,
                    content_hash=canonical_hash(claim),
                ),
            )
        )
    result = materialize_question_evidence_bundle(
        input.model_copy(
            update={
                "workflow": workflow,
                "evidence_closure": evidence_closure_from_workflow(workflow),
                "reviews": tuple(reviews),
                "claims": tuple(claims),
            }
        )
    )
    assert result.binding.supporting_evidence_ids == ("claim:bundle-1",)
    assert result.binding.contradicting_evidence_ids == ("claim:bundle-2",)
    assert result.pending_artifacts.bundle.no_information_basis is False


def test_unresolved_triage_blocks_an_answer_ready_bundle(tmp_path) -> None:
    input = _input(tmp_path)
    workflow = input.workflow.model_copy(
        update={
            "exposures": (
                V3PageExposure(
                    attempt_id="attempt:bundle-unresolved",
                    page_handle="page:bundle-unresolved",
                    candidate_id="candidate:bundle-unresolved",
                    canonical_unit_id="unit:bundle-unresolved",
                    location_handle="location:bundle-unresolved",
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
                    revision_id="triage:bundle-unresolved",
                    attempt_id="attempt:bundle-unresolved",
                    sq_id=input.workflow.question_id,
                    page_handle="page:bundle-unresolved",
                    candidate_id="candidate:bundle-unresolved",
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="Material ambiguity remains.",
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


def test_stale_resolved_review_hash_is_rejected_at_the_pure_boundary(tmp_path) -> None:
    input = _input(tmp_path)
    review = EvidenceReviewRevision(
        entity_id="evidence-review:bundle-test",
        revision_id="revision:evidence-review-bundle-test",
        actor=input.actor,
        observed_at=input.observed_at,
        candidate_id="candidate:bundle-test",
        result_id=input.workflow.result_id,
        domain_id=input.workflow.domain_id,
        sq_id=input.workflow.question_id,
        spans=(
            EvidenceReviewSpan(
                span_id="span:bundle-test",
                span_start=0,
                span_end=1,
                trial_attribution=TrialAttribution.ACTIVE,
                disposition=EvidenceReviewDisposition.SUPPORTING,
                rationale="Attributable.",
                attribution_rationale="Explicitly names the active trial.",
                reviewed_context=ReviewedEvidenceContext(
                    receipt_hash=canonical_hash({"receipt": "bundle-test"}),
                    snapshot_hash=canonical_hash({"snapshot": "bundle-test"}),
                    requested_mode="detail",
                    applied_mode="detail",
                    fragments=(
                        ReviewedEvidenceFragment(
                            unit_id="unit:bundle-test",
                            source_id="source:bundle-test",
                            source_artifact_hash=canonical_hash({"source": "bundle-test"}),
                            parse_id="parse:bundle-test",
                            canonicalization_version="1",
                            unit_content_hash=canonical_hash({"unit": "bundle-test"}),
                            span_start=0,
                            span_end=1,
                            content_hash=canonical_hash({"fragment": "bundle-test"}),
                        ),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="stale or tampered"):
        ResolvedQuestionEvidenceReview(
            review=review,
            reference=_reference(
                "evidence-review:bundle-test", "revision:evidence-review-bundle-test"
            ),
        )
