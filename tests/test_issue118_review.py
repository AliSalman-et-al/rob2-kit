from datetime import UTC, datetime

import pytest

from rob2_kit.domain.evidence import (
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    ReviewedEvidenceContext,
    ReviewedEvidenceFragment,
    TrialAttribution,
)
from rob2_kit.domain.revisions import Actor, ActorKind


def _context() -> ReviewedEvidenceContext:
    return ReviewedEvidenceContext(
        receipt_hash="sha256:" + "1" * 64,
        snapshot_hash="sha256:" + "2" * 64,
        requested_mode="unit",
        applied_mode="unit",
        fragments=(
            ReviewedEvidenceFragment(
                unit_id="unit:one",
                source_id="source:one",
                source_artifact_hash="sha256:" + "3" * 64,
                parse_id="parse:one",
                canonicalization_version="1.0.0",
                unit_content_hash="sha256:" + "4" * 64,
                span_start=0,
                span_end=9,
                content_hash="sha256:" + "5" * 64,
            ),
        ),
    )


def _review(*, disposition: EvidenceReviewDisposition) -> EvidenceReviewRevision:
    return EvidenceReviewRevision(
        entity_id="evidence-review:candidate-1",
        revision_id="revision:evidence-review-candidate-1-v1",
        actor=Actor(kind=ActorKind.AGENT, actor_id="agent:assessor", display_name="Assessor"),
        observed_at=datetime(2026, 8, 6, tzinfo=UTC),
        candidate_id="candidate:one",
        result_id="result:one",
        domain_id="domain:one",
        sq_id="sq:one",
        spans=(
            EvidenceReviewSpan(
                span_id="review-span:one",
                span_start=2,
                span_end=9,
                trial_attribution=TrialAttribution.ACTIVE,
                disposition=disposition,
                rationale="The passage identifies the allocation method.",
                attribution_rationale="The issued bounded context identifies this Result.",
                reviewed_context=_context(),
            ),
        ),
    )


def test_substantive_review_is_question_specific_and_context_bound() -> None:
    review = _review(disposition=EvidenceReviewDisposition.SUPPORTING)
    assert review.sq_id == "sq:one"
    assert review.spans[0].reviewed_context.fragments[0].unit_id == "unit:one"


def test_non_active_span_cannot_authorize_substantive_evidence() -> None:
    with pytest.raises(ValueError, match="non-active"):
        EvidenceReviewSpan(
            span_id="review-span:two",
            span_start=0,
            span_end=2,
            trial_attribution=TrialAttribution.OTHER,
            disposition=EvidenceReviewDisposition.SUPPORTING,
            rationale="Different study.",
            reviewed_context=_context(),
        )
