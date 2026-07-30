import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.review.service import (
    ActionDecision,
    ActionKind,
    BoundEvidence,
    FindingRequirement,
    PreparedAnswer,
    ReviewAction,
    ReviewCase,
    ReviewCommand,
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
    )


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
