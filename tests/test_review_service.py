import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rob2_kit.domain.assessment import (
    AssessmentRevision,
    AssessmentSignOff,
    DomainReviewDisposition,
    ReviewerProfileRevision,
)
from rob2_kit.domain.revisions import Actor, ActorKind, Dependency, Supersession
from rob2_kit.review.service import (
    ActionDecision,
    ActionKind,
    AttentionTier,
    BoundEvidence,
    CorrectionReworkCommand,
    CorrectionReworkStatus,
    CorrectionScope,
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
    SignOffWithdrawalCommand,
    StaleReviewError,
)
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
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


def committed_reference(
    review: ReviewService,
    name: str,
    payload: dict | None = None,
):
    result = review.ledger.commit(
        Transition(
            scope="review:trial-1",
            operation=f"test:materialize-{name}",
            operation_key=f"idempotency:materialize-{name}",
            actor=reviewer(),
            observed_at=NOW,
            entity_id=f"{name}:trial-1",
            revision_id=f"revision:{name}-1",
            artifact=json.dumps(payload or {"record": name}).encode(),
            artifact_media_type="application/json",
            dependencies=(),
            expected_dependency_fingerprint=dependency_fingerprint(()),
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )
    return reference(name).model_copy(
        update={
            "entity_id": f"{name}:trial-1",
            "revision_id": f"revision:{name}-1",
            "content_hash": result.artifact_hash,
        }
    )


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
                sq_id="sq:1:concealment",
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
    review = service(tmp_path, guided_case())
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

    canonical = {
        event.operation: json.loads(
            review.ledger.artifacts.read(event.output_revision_hashes[0])
        )
        for event in review.ledger.events()
        if event.operation.startswith("review:canonical-")
    }
    profile = ReviewerProfileRevision.model_validate(
        canonical["review:canonical-reviewer-profile"]
    )
    dispositions = [
        DomainReviewDisposition.model_validate(
            json.loads(review.ledger.artifacts.read(event.output_revision_hashes[0]))
        )
        for event in review.ledger.events()
        if event.operation == "review:canonical-domain-disposition"
    ]
    signed = AssessmentSignOff.model_validate(
        canonical["review:canonical-assessment-sign-off"]
    )
    assert profile.display_name == "Dr. Reviewer"
    assert {item.domain_id for item in dispositions} == {
        "domain:1",
        "domain:2",
        "domain:3",
        "domain:4",
        "domain:5",
    }
    assert signed.assessment == reference("assessment")
    assert signed.reviewer_profile.revision_id == profile.revision_id
    assert {item.revision_id for item in signed.domain_dispositions} == {
        disposition.revision_id for disposition in dispositions
    }
    materialization = review.record_output_materialization(
        sign_off=reference("sign-off").model_copy(
            update={
                "entity_id": signed.entity_id,
                "revision_id": signed.revision_id,
                "content_hash": next(
                    event.output_revision_hashes[0]
                    for event in review.ledger.events()
                    if event.revision_id == signed.revision_id
                ),
            }
        ),
        operation_key="output-attempt:failed",
        actor=reviewer().model_copy(update={"kind": ActorKind.SYSTEM}),
        observed_at=NOW,
        failure_reason="disk unavailable",
    )
    assert materialization.status == "incomplete"
    assert materialization.retry_action == "Retry deterministic output generation"
    assert review.current_sign_off() is not None
    assert review.output_materialization() == materialization

    withdrawal_ref = review.withdraw_sign_off(
        SignOffWithdrawalCommand(
            idempotency_key="idempotency:reopen-review",
            expected_assessment_revision_id="revision:assessment-1",
            expected_sign_off_revision_id=signed.revision_id,
            actor=reviewer(),
            reviewer_profile=reference("reviewer-profile"),
            reason="Reopen to inspect a newly reported concern.",
            observed_at=NOW,
        )
    )
    withdrawal_event = next(
        event
        for event in review.ledger.events()
        if event.revision_id == withdrawal_ref.revision_id
    )
    withdrawal = json.loads(
        review.ledger.artifacts.read(withdrawal_event.output_revision_hashes[0])
    )
    assert withdrawal["sign_off"]["revision_id"] == signed.revision_id
    assert withdrawal["reason"] == "Reopen to inspect a newly reported concern."
    assert any(event.revision_id == signed.revision_id for event in review.ledger.events())
    assert review.connection_state().value == "connected—waiting"


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
    queue = {item.action_id: item for item in review.queue()}
    assert queue["review-action:domain-1"].actionable is False
    assert queue["review-action:domain-2"].actionable is True


def test_correction_receipt_pins_context_and_derives_non_shrinkable_scope(
    tmp_path: Path,
) -> None:
    review = service(tmp_path, case())

    correction = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:targeted-correction",
            value=ActionDecision.CORRECTION_REQUESTED,
        ).model_copy(
            update={
                "rationale": "The quotation omits the sentence describing open allocation.",
                "correction_scope": CorrectionScope.DOMAIN,
            }
        )
    )

    request = correction.receipt.correction_request
    assert request is not None
    assert request.challenged_assessment == reference("assessment")
    assert request.result_label == "Mortality at 30 days"
    assert request.domain_id == "domain:1"
    assert request.evidence_claim == reference("evidence-claim")
    assert request.exact_text == "<script>alert('source')</script> ‏trial text"
    assert request.highlighted_region == (0, 44)
    assert request.prepared_answer == "Probably yes"
    assert request.prepared_rationale == "Allocation concealment was described."
    assert request.minimum_scope is CorrectionScope.EVIDENCE
    assert request.requested_scope is CorrectionScope.DOMAIN
    assert request.affected_scope == ("domain:1",)
    assert correction.receipt.revision_id in request.agent_prompt
    assert "The quotation omits" in request.agent_prompt

    separate_review = service(tmp_path / "narrow", case())
    with pytest.raises(ValueError, match="cannot narrow"):
        separate_review.commit(
            command(
                "review-action:domain-1",
                ActionKind.DOMAIN_REVIEW,
                key="idempotency:narrow-correction",
                value=ActionDecision.CORRECTION_REQUESTED,
            ).model_copy(update={"correction_scope": CorrectionScope.SIGNALING_QUESTION})
        )


def test_domain_correction_pins_prepared_judgment_and_basis(tmp_path: Path) -> None:
    review = service(tmp_path, guided_case())

    correction = review.commit(
        command(
            "review-action:domain-2",
            ActionKind.DOMAIN_REVIEW,
            key="idempotency:domain-correction",
            value=ActionDecision.CORRECTION_REQUESTED,
        )
    ).receipt.correction_request

    assert correction is not None
    assert correction.prepared_answer == "Some concerns"
    assert correction.prepared_rationale == "Answers for Domain 2 map to this judgment."


def test_interrupted_rework_rejects_success_only_outputs() -> None:
    with pytest.raises(ValueError, match="cannot include successful outputs"):
        CorrectionReworkCommand(
            operation_key="idempotency:invalid-interruption",
            correction_receipt_revision_id="revision:correction-1",
            actor=reviewer().model_copy(update={"kind": ActorKind.AGENT}),
            observed_at=NOW,
            status=CorrectionReworkStatus.INTERRUPTED,
            last_checkpoint="checkpoint:evidence",
            failure_reason="Connection closed.",
            resume_action="Retry.",
            superseding_assessment_revision_id="revision:assessment-2",
        )

    with pytest.raises(ValueError, match="cannot include failure"):
        CorrectionReworkCommand(
            operation_key="idempotency:invalid-success",
            correction_receipt_revision_id="revision:correction-1",
            actor=reviewer().model_copy(update={"kind": ActorKind.AGENT}),
            observed_at=NOW,
            status=CorrectionReworkStatus.SUCCEEDED,
            last_checkpoint="checkpoint:assessment",
            failure_reason="Old failure.",
            superseding_assessment_revision_id="revision:assessment-2",
            assessment_artifact=b"{}",
            corrected_sq_id="sq:1:concealment",
            superseding_review_case=guided_case(),
        )


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


def test_targeted_rework_resumes_then_supersedes_exact_current_assessment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = service(tmp_path, guided_case())
    result_spec = committed_reference(review, "result-spec")
    inventory = committed_reference(review, "source-inventory")
    bundle = committed_reference(review, "evidence-bundle")
    answer_before = committed_reference(
        review,
        "sq-answer-before",
        {
            "sq_id": "sq:1:concealment",
            "answer": "probably_yes",
            "rationale": "Allocation appeared concealed.",
        },
    )
    answer_after = committed_reference(
        review,
        "sq-answer-after",
        {
            "sq_id": "sq:1:concealment",
            "answer": "no",
            "rationale": "Open allocation was reported.",
        },
    )
    judgment = committed_reference(
        review,
        "judgment",
        {"domain_id": "domain:1", "judgment": "low_risk"},
    )
    judgment_after = committed_reference(
        review,
        "judgment-after",
        {"domain_id": "domain:1", "judgment": "some_concerns"},
    )
    unrelated_judgment = committed_reference(
        review,
        "judgment-unrelated",
        {"domain_id": "domain:2", "judgment": "high"},
    )

    def assessment(
        revision_id: str,
        answer,
        *,
        judgment_reference=None,
        supersedes: Supersession | None = None,
    ) -> AssessmentRevision:
        selected_judgment = judgment_reference or judgment
        references = (
            (result_spec, "dependency:result-spec"),
            (inventory, "dependency:source-inventory"),
            (bundle, "dependency:evidence-bundle"),
            (answer, "dependency:sq-answer"),
            (selected_judgment, "dependency:algorithmic-judgment"),
        )
        return AssessmentRevision(
            entity_id=review.review_case.assessment.entity_id,
            revision_id=revision_id,
            actor=reviewer(),
            observed_at=NOW,
            supersedes=supersedes,
            dependencies=tuple(
                Dependency(**item.model_dump(), role=role)
                for item, role in references
            ),
            result_spec=result_spec,
            source_inventory=inventory,
            evidence_bundles=(bundle,),
            answers=(answer,),
            judgments=(selected_judgment,),
        )

    challenged = assessment(review.review_case.assessment.revision_id, answer_before)
    challenged_dependencies = tuple(
        DependencyInput(**dependency.model_dump())
        for dependency in challenged.dependencies
    )
    original = review.ledger.commit(
        Transition(
            scope="review:trial-1",
            operation="assessment:materialize",
            operation_key="idempotency:materialize-assessment",
            actor=reviewer(),
            observed_at=NOW,
            entity_id=review.review_case.assessment.entity_id,
            revision_id=review.review_case.assessment.revision_id,
            artifact=challenged.model_dump_json().encode(),
            artifact_media_type="application/json",
            dependencies=challenged_dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(
                challenged_dependencies
            ),
            checkpoint="checkpoint:assessment",
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        review.lease,
        now=NOW,
    )
    review.review_case = review.review_case.model_copy(
        update={
            "assessment": review.review_case.assessment.model_copy(
                update={"content_hash": original.artifact_hash}
            ),
            "assessment_content_hash": original.artifact_hash,
        }
    )
    challenged_case = review.review_case
    correction = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:rework-correction",
            value=ActionDecision.CORRECTION_REQUESTED,
        )
    )
    interrupted = review.submit_targeted_rework(
        CorrectionReworkCommand(
            operation_key="idempotency:rework-interrupted",
            correction_receipt_revision_id=correction.receipt.revision_id,
            actor=reviewer().model_copy(update={"kind": ActorKind.AGENT}),
            observed_at=NOW,
            status=CorrectionReworkStatus.INTERRUPTED,
            last_checkpoint="checkpoint:evidence",
            failure_reason="Agent connection closed.",
            resume_action="Resume from checkpoint:evidence.",
        )
    )
    assert interrupted.status is CorrectionReworkStatus.INTERRUPTED
    assert review.correction_state(correction.receipt.revision_id) == interrupted

    corrected_assessment = assessment(
        "revision:assessment-2",
        answer_after,
        judgment_reference=judgment_after,
        supersedes=Supersession(
            **review.review_case.assessment.model_dump(),
            reason="Targeted correction",
        ),
    )
    corrected_artifact = corrected_assessment.model_dump_json().encode()
    proposed_reference = review.review_case.assessment.model_copy(
        update={
            "revision_id": "revision:assessment-2",
            "content_hash": review.ledger.artifacts.put(
                corrected_artifact, "application/json"
            ).content_hash,
        }
    )
    corrected_actions = tuple(
        action.model_copy(
            update={
                "prepared_answer": PreparedAnswer(
                    revision=answer_after,
                    answer="No",
                    rationale="Open allocation was reported.",
                ),
                "answer_revision": answer_after,
            }
        )
        if action.action_id == "review-action:finding-1"
        else action
        for action in review.review_case.actions
    )
    corrected_summaries = tuple(
        summary.model_copy(
            update={
                "judgment": "Some concerns",
                "deterministic_basis": "Corrected answers map to Some concerns.",
                "active_questions": (
                    DomainQuestionSummary(
                        sq_id="sq:1:concealment",
                        guidance="Was allocation concealed?",
                        answer="No",
                        rationale="Open allocation was reported.",
                        evidence_count=1,
                    ),
                ),
            }
        )
        if summary.domain_id == "domain:1"
        else summary
        for summary in review.review_case.domain_summaries
    )
    corrected_case = review.review_case.model_copy(
        update={
            "assessment": proposed_reference,
            "assessment_revision_id": proposed_reference.revision_id,
            "assessment_content_hash": proposed_reference.content_hash,
            "actions": corrected_actions,
            "domain_summaries": corrected_summaries,
        }
    )
    completion_command = CorrectionReworkCommand(
            operation_key="idempotency:rework-complete",
            correction_receipt_revision_id=correction.receipt.revision_id,
            actor=reviewer().model_copy(update={"kind": ActorKind.AGENT}),
            observed_at=NOW,
            status=CorrectionReworkStatus.SUCCEEDED,
            last_checkpoint="checkpoint:assessment",
            superseding_assessment_revision_id="revision:assessment-2",
            assessment_artifact=corrected_artifact,
            corrected_sq_id="sq:1:concealment",
            corrected_evidence_id="entity:evidence-claim",
            superseding_review_case=corrected_case,
        )
    with pytest.raises(ValueError, match="stale Domain judgment"):
        stale_summaries = tuple(
            summary.model_copy(
                update={
                    "judgment": "Low risk",
                    "deterministic_basis": "Answers map to Low risk.",
                }
            )
            if summary.domain_id == "domain:1"
            else summary
            for summary in corrected_summaries
        )
        review.submit_targeted_rework(
            completion_command.model_copy(
                update={
                    "operation_key": "idempotency:stale-judgment-projection",
                    "superseding_review_case": corrected_case.model_copy(
                        update={"domain_summaries": stale_summaries}
                    ),
                }
            )
        )
    original_commit = review.ledger.commit
    failed_once = False

    def interrupt_between_success_and_supersession(*args, **kwargs):
        nonlocal failed_once
        transition = args[0]
        if (
            transition.operation == "correction:supersede-assessment"
            and not failed_once
        ):
            failed_once = True
            raise RuntimeError("simulated interruption")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(review.ledger, "commit", interrupt_between_success_and_supersession)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        review.submit_targeted_rework(completion_command)
    interrupted_apply = review.correction_state(correction.receipt.revision_id)
    assert interrupted_apply.status is CorrectionReworkStatus.INTERRUPTED
    assert "supersession was interrupted" in interrupted_apply.failure_reason
    assert "same idempotency key" in interrupted_apply.resume_action
    monkeypatch.setattr(review.ledger, "commit", original_commit)
    completed = review.submit_targeted_rework(completion_command)

    assert completed.current_proposed_assessment is not None
    assert completed.current_proposed_assessment.revision_id == "revision:assessment-2"
    current = {
        revision.entity_id: revision.revision_id
        for revision in review.ledger.current_revisions()
    }
    assert current[review.review_case.assessment.entity_id] == "revision:assessment-2"
    assert completed.comparison is not None
    assert "Answer and rationale" in completed.comparison.answer_and_rationale[0]
    assert "Evidence Bundles" in completed.comparison.reused_unaffected_work
    refreshed = next(
        action
        for action in review.review_case.actions
        if action.action_id == "review-action:finding-1"
    )
    assert refreshed.prepared_answer.answer == "No"
    assert review.submit_targeted_rework(completion_command) == completed
    assert len(
        [
            event
            for event in review.ledger.events()
            if event.operation == "correction:supersede-assessment"
        ]
    ) == 1
    rework_events = [
        event
        for event in review.ledger.events()
        if event.operation.startswith("correction:targeted-rework")
    ]
    assert {dependency.role for dependency in rework_events[-2].dependencies} == {
        "dependency:correction-receipt",
        "dependency:challenged-assessment",
    }
    assert {dependency.role for dependency in rework_events[-1].dependencies} == {
        "dependency:proposed-assessment"
    }
    with pytest.raises(ReviewError, match="different rework content"):
        review.submit_targeted_rework(
            completion_command.model_copy(update={"assessment_artifact": b"{}"})
        )
    resumed = ReviewService(review.ledger, review.lease, challenged_case)
    assert resumed.review_case.assessment_revision_id == "revision:assessment-2"
    assert resumed.correction_state(correction.receipt.revision_id) == completed

    next_correction = review.commit(
        command(
            "review-action:finding-1",
            ActionKind.VERIFY_EVIDENCE,
            key="idempotency:second-correction",
            expected="revision:assessment-2",
            value=ActionDecision.CORRECTION_REQUESTED,
        )
    )
    chain = review.correction_receipts()
    assert [item.revision_id for item in chain] == [
        correction.receipt.revision_id,
        next_correction.receipt.revision_id,
    ]
    assert next_correction.receipt.correction_request is not None
    assert (
        next_correction.receipt.correction_request.challenged_assessment.revision_id
        == "revision:assessment-2"
    )
    assert (
        next_correction.receipt.correction_request.predecessor_receipt_revision_id
        == correction.receipt.revision_id
    )
    unrelated_assessment = assessment(
        "revision:assessment-3",
        answer_after,
        judgment_reference=unrelated_judgment,
        supersedes=Supersession(
            **review.review_case.assessment.model_dump(),
            reason="Targeted correction",
        ),
    )
    unrelated_artifact = unrelated_assessment.model_dump_json().encode()
    unrelated_reference = review.review_case.assessment.model_copy(
        update={
            "revision_id": "revision:assessment-3",
            "content_hash": review.ledger.artifacts.put(
                unrelated_artifact, "application/json"
            ).content_hash,
        }
    )
    unrelated_case = review.review_case.model_copy(
        update={
            "assessment": unrelated_reference,
            "assessment_revision_id": unrelated_reference.revision_id,
            "assessment_content_hash": unrelated_reference.content_hash,
        }
    )
    with pytest.raises(ValueError, match="unaffected Domain"):
        review.submit_targeted_rework(
            CorrectionReworkCommand(
                operation_key="idempotency:unrelated-domain-rework",
                correction_receipt_revision_id=next_correction.receipt.revision_id,
                actor=reviewer().model_copy(update={"kind": ActorKind.AGENT}),
                observed_at=NOW,
                status=CorrectionReworkStatus.SUCCEEDED,
                last_checkpoint="checkpoint:assessment",
                superseding_assessment_revision_id="revision:assessment-3",
                assessment_artifact=unrelated_artifact,
                corrected_sq_id="sq:1:concealment",
                corrected_evidence_id="entity:evidence-claim",
                superseding_review_case=unrelated_case,
            )
        )
    with pytest.raises(StaleReviewError):
        review.commit(
            command(
                "review-action:finding-1",
                ActionKind.VERIFY_EVIDENCE,
                key="idempotency:after-new-assessment",
            )
        )
