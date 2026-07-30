import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.review.service import (
    ActionDecision,
    ActionKind,
    AttentionTier,
    BoundEvidence,
    DomainQuestionSummary,
    DomainReviewSummary,
    FindingRequirement,
    PreparedAnswer,
    ReviewAction,
    ReviewCase,
    ReviewCommand,
    ReviewError,
    ReviewPolicy,
    ReviewService,
    SignOffBlockedError,
    StaleReviewError,
)
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from tests.fixtures import HASH, reference

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def reviewer() -> Actor:
    return Actor(
        kind=ActorKind.HUMAN,
        actor_id="actor:reviewer",
        display_name="Dr. Reviewer",
    )


def service(tmp_path: Path, review_case: ReviewCase) -> ReviewService:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ledger = WorkflowLedger(tmp_path / "workflow.sqlite3", artifacts)
    lease = ledger.acquire_lease("owner:review-gui", NOW, timedelta(days=7))
    ledger.commit(
        Transition(
            scope="preparation:trial-1",
            operation="preparation:complete",
            operation_key="idempotency:preparation-complete",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="preparation-attempt:trial-1",
            revision_id="revision:preparation-trial-1",
            artifact=b'{"outcome":"draft_ready"}',
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint="checkpoint:preparation-outcome",
            outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
        ),
        lease,
        now=NOW,
    )
    return ReviewService(ledger, lease, review_case)


def case() -> ReviewCase:
    evidence_text = "<script>alert('source')</script> ‏trial text"
    evidence_hash = f"sha256:{hashlib.sha256(evidence_text.encode()).hexdigest()}"
    return ReviewCase(
        review_id="review:trial-1",
        review_revision=reference("review"),
        assessment=reference("assessment"),
        policy=ReviewPolicy(
            reference=reference("review-policy"),
            domain_ids=("domain:1", "domain:2", "domain:3", "domain:4", "domain:5"),
        ),
        assessment_revision_id="revision:assessment-1",
        assessment_content_hash=HASH,
        result_label="Mortality at 30 days",
        domain_ids=("domain:1", "domain:2", "domain:3", "domain:4", "domain:5"),
        actions=(
            ReviewAction(
                action_id="review-action:domain-1",
                kind=ActionKind.DOMAIN_REVIEW,
                domain_id="domain:1",
                title="Review domain 1",
            ),
            ReviewAction(
                action_id="review-action:finding-1",
                kind=ActionKind.VERIFY_EVIDENCE,
                domain_id="domain:1",
                title="Verify allocation evidence",
                source_locator="Protocol p. 4",
                bound_evidence=BoundEvidence(
                    canonical_unit=reference("canonical-unit").model_copy(
                        update={"content_hash": evidence_hash}
                    ),
                    canonical_text=evidence_text,
                    span_start=0,
                    span_end=len(evidence_text),
                ),
                prepared_answer=PreparedAnswer(
                    revision=reference("sq-answer"),
                    answer="Probably yes",
                    rationale="Allocation concealment was described.",
                ),
                finding_requirement=FindingRequirement.RESOLVE,
                finding_id="finding:allocation",
                evidence_claim=reference("evidence-claim"),
                evidence_bundle=reference("evidence-bundle"),
                answer_revision=reference("sq-answer"),
                consequence="The prepared answer cannot be reviewed until evidence is verified.",
                correction_checkpoint="checkpoint:evidence",
            ),
            ReviewAction(
                action_id="review-action:repair-1",
                kind=ActionKind.BLOCKING_REPAIR,
                title="Resolve the Result identity",
                finding_requirement=FindingRequirement.RESOLVE,
            ),
        ),
        preparation_scopes=("preparation:trial-1",),
    )


def command(
    action_id: str,
    kind: ActionKind,
    *,
    key: str,
    expected: str = "revision:assessment-1",
    value: ActionDecision = ActionDecision.ACCEPTED,
    domain_opened: bool | None = None,
) -> ReviewCommand:
    return ReviewCommand(
        idempotency_key=key,
        action_id=action_id,
        kind=kind,
        expected_assessment_revision_id=expected,
        actor=reviewer(),
        value=value,
        rationale="Reviewed against the source.",
        observed_at=NOW,
        reviewer_profile=reference("reviewer-profile"),
        review_session_id="review-session:test",
        domain_opened=(
            domain_opened
            if domain_opened is not None
            else kind is ActionKind.DOMAIN_REVIEW
        ),
    )


def guided_case() -> ReviewCase:
    base = case()
    actions = (
        *base.actions,
        ReviewAction(
            action_id="review-action:limitation-1",
            kind=ActionKind.ACKNOWLEDGE_LIMITATION,
            domain_id="domain:2",
            sq_id="sq:2.3",
            title="Acknowledge incomplete outcome data coverage",
            finding_requirement=FindingRequirement.ACKNOWLEDGE,
            finding_id="finding:coverage",
            consequence="Domain 2 and Result sign-off remain blocked.",
            next_action="Review and acknowledge the coverage limitation.",
            accepted_contradiction=True,
            source_conflict=True,
            elevated_visual_transcription=True,
            no_information=True,
            influential_project_rule=True,
            judgment_override=True,
        ),
    )
    summaries = tuple(
        DomainReviewSummary(
            domain_id=f"domain:{index}",
            full_name=f"Domain {index} full name",
            judgment="Low risk" if index != 2 else "Some concerns",
            active_sq_count=index,
            evidence_count=index + 1,
            coverage="Complete" if index != 2 else "Limited",
            deterministic_basis=f"Answers for Domain {index} map to this judgment.",
            coverage_acknowledged=index == 2,
            active_questions=(
                DomainQuestionSummary(
                    sq_id=f"sq:{index}.1",
                    guidance=f"Question {index}.1",
                    answer="Yes",
                    rationale=f"Rationale for question {index}.1.",
                    evidence_count=index + 1,
                ),
            ),
        )
        for index in range(1, 6)
    )
    return base.model_copy(update={"actions": actions, "domain_summaries": summaries})


def test_guided_queue_derives_attention_reasons_and_prioritizes_available_work(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, guided_case())
    correction = command(
        "review-action:finding-1",
        ActionKind.VERIFY_EVIDENCE,
        key="idempotency:awaiting-rework",
        value=ActionDecision.CORRECTION_REQUESTED,
    )
    review.commit(correction)

    queue = review.queue()

    assert queue[0].action_id == "review-action:repair-1"
    waiting = next(item for item in queue if item.action_id == correction.action_id)
    assert waiting.attention_tier is AttentionTier.ACTION_REQUIRED
    assert waiting.actionable is False
    assert waiting.reasons == ("A requested correction is waiting for targeted agent rework.",)
    limitation = next(item for item in queue if item.action_id == "review-action:limitation-1")
    assert limitation.attention_tier is AttentionTier.ACTION_REQUIRED
    assert limitation.reasons == (
        "A required coverage limitation must be acknowledged.",
        "Accepted contradicting evidence requires careful inspection.",
        "An accepted Source conflict requires careful inspection.",
        "An elevated Visual transcription requires careful inspection.",
        "A No information answer requires its search basis to be inspected.",
        "A materially influential Project rule requires careful inspection.",
        "A Judgment override requires careful inspection.",
        "The Domain judgment is Some concerns.",
        "An acknowledged coverage limitation remains material to sign-off.",
    )
    assert limitation.affected_context == "Mortality at 30 days · Domain 2 · SQ 2.3"
    assert limitation.consequence == "Domain 2 and Result sign-off remain blocked."
    routine = next(item for item in queue if item.action_id == "review-action:domain-3")
    assert routine.attention_tier is AttentionTier.ROUTINE_REVIEW
    assert routine.domain_summary == guided_case().domain_summaries[2]

    review.ledger.commit(
        Transition(
            scope="review:trial-1",
            operation="assessment:replace",
            operation_key="idempotency:stale-guided-review",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="entity:assessment",
            revision_id="revision:assessment-newer",
            artifact=b'{"revision":2}',
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )
    stale = review.queue()[0]
    assert stale.attention_tier is AttentionTier.ACTION_REQUIRED
    assert "A newer Assessment revision makes this review read-only." in stale.reasons


def test_domain_confirmation_requires_the_individual_domain_to_be_opened(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, guided_case())

    with pytest.raises(ReviewError, match="opened"):
        review.commit(
            command(
                "review-action:domain-3",
                ActionKind.DOMAIN_REVIEW,
                key="idempotency:unopened-domain",
                domain_opened=False,
            )
        )

    assert len(review.ledger.events()) == 1


def test_queue_is_policy_ordered_and_answer_is_staged(tmp_path: Path) -> None:
    review = service(tmp_path, case())

    queue = review.queue()

    assert [item.kind for item in queue[:2]] == [
        ActionKind.BLOCKING_REPAIR,
        ActionKind.VERIFY_EVIDENCE,
    ]
    assert [item.domain_id for item in queue[2:]] == [
        "domain:1",
        "domain:2",
        "domain:3",
        "domain:4",
        "domain:5",
    ]
    assert queue[1].evidence_text is not None
    assert queue[1].evidence_text.startswith("<script>")
    assert queue[1].answer_visible is False
    assert queue[1].staged_answer is None


def test_human_action_commits_once_and_reveals_answer(tmp_path: Path) -> None:
    review = service(tmp_path, case())
    request = command(
        "review-action:finding-1",
        ActionKind.VERIFY_EVIDENCE,
        key="idempotency:evidence-1",
    )

    first = review.commit(request)
    duplicate = review.commit(request)

    assert first.receipt.outcome == "action_completed"
    assert duplicate.receipt.revision_id == first.receipt.revision_id
    assert duplicate.duplicate is True
    assert len(review.ledger.events()) == 2
    verified = next(item for item in review.queue() if item.action_id == request.action_id)
    assert verified.answer_visible is True
    assert verified.staged_answer == "Probably yes"


def test_refreshed_submission_with_a_new_key_cannot_duplicate_an_action(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, case())
    first = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:first-page",
        )
    )
    refreshed = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:refreshed-page",
        )
    )

    assert refreshed.duplicate is True
    assert refreshed.receipt.revision_id == first.receipt.revision_id
    assert len(review.ledger.events()) == 2


def test_stale_action_is_read_only(tmp_path: Path) -> None:
    review = service(tmp_path, case())

    with pytest.raises(StaleReviewError):
        review.commit(
            command(
                "review-action:finding-1",
                ActionKind.VERIFY_EVIDENCE,
                key="idempotency:stale",
                expected="revision:assessment-old",
            )
        )

    assert len(review.ledger.events()) == 1


def test_sign_off_requires_findings_and_every_domain_then_reconfirms_identity(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, case())

    with pytest.raises(SignOffBlockedError):
        review.commit(
            command(
                "review-action:sign-off",
                ActionKind.SIGN_OFF,
                key="idempotency:early-signoff",
            )
        )

    review.commit(
        command(
            "review-action:repair-1",
            ActionKind.BLOCKING_REPAIR,
            key="idempotency:repair",
        )
    )
    review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:evidence",
        )
    )
    for domain in range(1, 6):
        review.commit(
            command(
                f"review-action:domain-{domain}",
                ActionKind.DOMAIN_REVIEW,
                key=f"idempotency:domain-{domain}",
            )
        )

    sign_off = review.commit(
        ReviewCommand(
            **command(
                "review-action:sign-off",
                ActionKind.SIGN_OFF,
                key="idempotency:sign-off",
            ).model_dump(exclude={"confirmed_display_name"}),
            confirmed_display_name="Dr. Reviewer",
        )
    )

    assert sign_off.receipt.outcome == "assessment_signed_off"
    assert sign_off.receipt.assurance == "local_human_attribution"
    assert sign_off.receipt.review_policy == reference("review-policy")
    assert sign_off.receipt.reviewer_profile == reference("reviewer-profile")
    assert review.connection_state().value == "review complete"


def test_nonhuman_actor_cannot_commit_review_action(tmp_path: Path) -> None:
    review = service(tmp_path, case())
    agent = reviewer().model_copy(update={"kind": ActorKind.AGENT})

    with pytest.raises(ValueError, match="human"):
        review.commit(
            command(
                "review-action:finding-1",
                ActionKind.VERIFY_EVIDENCE,
                key="idempotency:agent",
            ).model_copy(update={"actor": agent})
        )


def test_correction_request_is_attributable_and_does_not_satisfy_review_policy(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, case())

    correction = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:correction",
            value=ActionDecision.CORRECTION_REQUESTED,
        )
    )

    assert correction.receipt.outcome == "correction_requested"
    assert correction.receipt.actor == reviewer()
    assert correction.receipt.correction_checkpoint == "checkpoint:evidence"
    assert review.ledger.events()[-1].outcome == "work_required"
    assert all(item.kind is not ActionKind.SIGN_OFF for item in review.queue())


def test_authoritative_newer_assessment_makes_session_stale(tmp_path: Path) -> None:
    review = service(tmp_path, case())
    review.ledger.commit(
        Transition(
            scope="review:trial-1",
            operation="assessment:replace",
            operation_key="idempotency:new-assessment",
            actor=reviewer(),
            observed_at=NOW,
            entity_id="entity:assessment",
            revision_id="revision:assessment-2",
            artifact=b'{"revision":2}',
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint="checkpoint:assessment",
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )

    assert review.is_stale() is True
    with pytest.raises(StaleReviewError):
        review.commit(
            command(
                "review-action:finding-1",
                ActionKind.VERIFY_EVIDENCE,
                key="idempotency:after-new-assessment",
            )
        )
