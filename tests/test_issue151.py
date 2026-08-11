"""Current-review provenance and question isolation regressions (#151, v3)."""

import pytest
from pydantic import ValidationError

from rob2_kit.application.active_question_frontier import evidence_closure_from_workflow
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.question_evidence_bundle import (
    ResolvedQuestionEvidenceReview,
    ResolvedQuestionVisualTranscription,
    materialize_question_evidence_bundle,
)
from rob2_kit.application.question_evidence_session import QuestionEvidenceSessionStore
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import (
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    ReviewedEvidenceContext,
    ReviewedEvidenceFragment,
    TrialAttribution,
    VisualTranscription,
)
from rob2_kit.domain.revisions import Dependency
from tests.test_issue167_question_bundle import _input, _reference
from tests.test_question_evidence_session import _closed_workflow, _service_for, _two_peer_state


def test_tampered_current_review_reference_is_rejected_before_bundle_materialization(
    tmp_path,
) -> None:
    input = _input(tmp_path)
    review = EvidenceReviewRevision(
        entity_id="evidence-review:issue151",
        revision_id="revision:evidence-review-issue151",
        actor=input.actor,
        observed_at=input.observed_at,
        candidate_id="candidate:issue151",
        result_id=input.workflow.result_id,
        domain_id=input.workflow.domain_id,
        sq_id=input.workflow.question_id,
        spans=(
            EvidenceReviewSpan(
                span_id="span:issue151",
                span_start=0,
                span_end=1,
                trial_attribution=TrialAttribution.ACTIVE,
                disposition=EvidenceReviewDisposition.SUPPORTING,
                rationale="The reviewed span supports this question.",
                attribution_rationale="The active trial is explicitly identified.",
                reviewed_context=ReviewedEvidenceContext(
                    receipt_hash=canonical_hash({"receipt": "issue151"}),
                    snapshot_hash=canonical_hash({"snapshot": "issue151"}),
                    requested_mode="detail",
                    applied_mode="detail",
                    fragments=(
                        ReviewedEvidenceFragment(
                            unit_id="unit:issue151",
                            source_id="source:issue151",
                            source_artifact_hash=canonical_hash({"source": "issue151"}),
                            parse_id="parse:issue151",
                            canonicalization_version="1",
                            unit_content_hash=canonical_hash({"unit": "issue151"}),
                            span_start=0,
                            span_end=1,
                            content_hash=canonical_hash({"fragment": "issue151"}),
                        ),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ValidationError, match="stale or tampered"):
        ResolvedQuestionEvidenceReview(
            review=review,
            reference=_reference("evidence-review:issue151", "revision:evidence-review-issue151"),
        )


def test_tampered_visual_transcription_reference_is_rejected_before_freezing(tmp_path) -> None:
    input = _input(tmp_path)
    source = _reference("source:issue151", "revision:source-issue151")
    transcription = VisualTranscription(
        entity_id="visual-transcription:issue151",
        revision_id="revision:visual-transcription-issue151",
        dependencies=(Dependency(**source.model_dump(), role="dependency:source"),),
        actor=input.actor,
        observed_at=input.observed_at,
        source=source,
        page=1,
        region=(0.0, 0.0, 1.0, 1.0),
        render_mode="crop",
        dpi=144,
        transcription="Allocation was concealed.",
    )

    with pytest.raises(ValidationError, match="stale or tampered"):
        ResolvedQuestionVisualTranscription(
            transcription=transcription,
            reference=_reference(
                "visual-transcription:issue151", "revision:visual-transcription-issue151"
            ),
            candidate_id="candidate:issue151",
            authorizing_review=_reference(
                "evidence-review:issue151", "revision:evidence-review-issue151"
            ),
            review_span_id="span:issue151",
        )


def test_question_bundles_remain_isolated_when_peer_questions_share_a_session(tmp_path) -> None:
    state = _two_peer_state()
    navigation = V3EvidenceNavigationStore(tmp_path)
    service = _service_for(state, QuestionEvidenceSessionStore(tmp_path), navigation)
    projection = service.initialize()
    first, second = projection.frontier.question_ids
    first_workflow = _closed_workflow(service, navigation, first)
    second_workflow = _closed_workflow(service, navigation, second)
    base = _input(tmp_path / "bundle-input")

    first_bundle = materialize_question_evidence_bundle(
        base.model_copy(
            update={
                "session": service.load(),
                "workflow": first_workflow,
                "evidence_closure": evidence_closure_from_workflow(first_workflow),
            }
        )
    )
    second_bundle = materialize_question_evidence_bundle(
        base.model_copy(
            update={
                "session": service.load(),
                "workflow": second_workflow,
                "evidence_closure": evidence_closure_from_workflow(second_workflow),
            }
        )
    )

    assert first_bundle.binding.question_id == first
    assert second_bundle.binding.question_id == second
    assert first_bundle.binding.bundle_content_hash != second_bundle.binding.bundle_content_hash
