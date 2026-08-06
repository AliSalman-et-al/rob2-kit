from datetime import UTC, datetime

import pytest

from rob2_kit.domain.evidence import (
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    TrialAttribution,
)
from rob2_kit.domain.revisions import Actor, ActorKind


def _review(*, disposition: EvidenceReviewDisposition) -> EvidenceReviewRevision:
    return EvidenceReviewRevision(
        entity_id="evidence-review:candidate-1",
        revision_id="revision:evidence-review-candidate-1-v1",
        actor=Actor(
            kind=ActorKind.AGENT,
            actor_id="agent:assessor",
            display_name="Assessor",
        ),
        observed_at=datetime(2026, 8, 6, tzinfo=UTC),
        candidate_id="candidate:one",
        result_id="result:one",
        domain_id="domain:one",
        question_ids=("sq:one",),
        trial_attribution=TrialAttribution.ACTIVE,
        reviewed_context_handles=("handle:context-1",),
        spans=(
            EvidenceReviewSpan(
                location_handle="handle:context-1",
                span_start=2,
                span_end=9,
                disposition=disposition,
                rationale="The passage identifies the active trial allocation method.",
                context_handles=("handle:context-1",),
            ),
        ),
    )


def test_substantive_review_is_bound_to_context_and_exact_span() -> None:
    review = _review(disposition=EvidenceReviewDisposition.SUPPORTING)

    assert review.is_complete

    with pytest.raises(ValueError, match="reviewed context"):
        EvidenceReviewRevision.model_validate(
            _review(disposition=EvidenceReviewDisposition.SUPPORTING).model_dump()
            | {"reviewed_context_handles": ("handle:other",)}
        )


def test_visual_review_condition_keeps_semantic_review_incomplete() -> None:
    review = EvidenceReviewRevision.model_validate(
        _review(disposition=EvidenceReviewDisposition.SUPPORTING).model_dump()
        | {
            "spans": (
                EvidenceReviewSpan(
                    location_handle="handle:context-1",
                    span_start=2,
                    span_end=9,
                    disposition=EvidenceReviewDisposition.NEEDS_VISUAL_REVIEW,
                    rationale="The table layout is required to establish the denominator.",
                    context_handles=("handle:context-1",),
                    visual_review_condition="visual:table-layout",
                ),
            )
        }
    )

    assert not review.is_complete
