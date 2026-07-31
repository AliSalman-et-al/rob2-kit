"""Ledger-backed human review queue and command boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.application.preparation import ReviewReceiptOutcome
from rob2_kit.domain.assessment import (
    AssessmentRevision,
    AssessmentSignOff,
    DomainReviewDisposition,
    DomainReviewDispositionKind,
    ReviewerProfileRevision,
    SignOffWithdrawal,
)
from rob2_kit.domain.revisions import (
    Actor,
    ActorKind,
    ContentHash,
    Dependency,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.storage.artifacts import ArtifactNotFoundError
from rob2_kit.storage.ledger import (
    DependencyInput,
    LeaseToken,
    Transition,
    WorkflowEvent,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)


class ReviewError(RuntimeError):
    """Base class for review command failures."""


class StaleReviewError(ReviewError):
    """The browser is bound to an assessment revision that is no longer current."""


class SignOffBlockedError(ReviewError):
    """The review policy does not yet permit Assessment sign-off."""


class ActionKind(StrEnum):
    BLOCKING_REPAIR = "blocking_repair"
    VERIFY_EVIDENCE = "verify_evidence"
    ACKNOWLEDGE_LIMITATION = "acknowledge_limitation"
    INSPECT_FINDING = "inspect_finding"
    DOMAIN_REVIEW = "domain_review"
    SIGN_OFF = "sign_off"


class FindingRequirement(StrEnum):
    RESOLVE = "resolve"
    ACKNOWLEDGE = "acknowledge"


class ActionDecision(StrEnum):
    ACCEPTED = "accepted"
    ACKNOWLEDGED = "acknowledged"
    CORRECTION_REQUESTED = "correction_requested"
    DEFERRED = "deferred"
    OVERRIDDEN = "overridden"
    SIGNED = "signed"


class AttentionTier(StrEnum):
    ACTION_REQUIRED = "Action required"
    INSPECT_CAREFULLY = "Inspect carefully"
    ROUTINE_REVIEW = "Routine review"


class BoundEvidence(FrozenModel):
    canonical_unit: RecordReference
    canonical_text: str
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_materialization(self) -> BoundEvidence:
        if self.span_end > len(self.canonical_text) or self.span_start >= self.span_end:
            raise ValueError("evidence span must select exact canonical-unit text")
        expected_hash = f"sha256:{hashlib.sha256(self.canonical_text.encode()).hexdigest()}"
        if self.canonical_unit.content_hash != expected_hash:
            raise ValueError("canonical evidence text does not match its content hash")
        return self

    def quote(self) -> str:
        return self.canonical_text[self.span_start : self.span_end]


class PreparedAnswer(FrozenModel):
    revision: RecordReference
    answer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ConnectionState(StrEnum):
    CONNECTED_WAITING = "connected—waiting"
    WORKING = "working—updating"
    NOT_CONNECTED = "not connected—review saved"
    RECONNECT_NEEDED = "reconnect needed"
    COMPLETE = "review complete"


class CorrectionScope(StrEnum):
    EVIDENCE = "evidence"
    SIGNALING_QUESTION = "signaling_question"
    DOMAIN = "domain"
    RESULT = "result"


class ReviewAction(FrozenModel):
    action_id: Identifier
    kind: ActionKind
    title: str = Field(min_length=1)
    domain_id: Identifier | None = None
    sq_id: Identifier | None = None
    source_locator: str | None = None
    bound_evidence: BoundEvidence | None = None
    prepared_answer: PreparedAnswer | None = None
    finding_requirement: FindingRequirement | None = None
    finding_id: Identifier | None = None
    evidence_claim: RecordReference | None = None
    evidence_bundle: RecordReference | None = None
    answer_revision: RecordReference | None = None
    consequence: str | None = None
    correction_checkpoint: Identifier | None = None
    source_role: str | None = None
    source_criticality: str | None = None
    relevant_dates: tuple[str, ...] = ()
    acquisition_attempts: tuple[str, ...] = ()
    final_coverage: str | None = None
    affected_scope: tuple[Identifier, ...] = ()
    crop_reference: RecordReference | None = None
    next_action: str | None = None
    accepted_contradiction: bool = False
    source_conflict: bool = False
    elevated_visual_transcription: bool = False
    no_information: bool = False
    influential_project_rule: bool = False
    judgment_override: bool = False

    @model_validator(mode="after")
    def validate_evidence_binding(self) -> ReviewAction:
        if self.kind is ActionKind.VERIFY_EVIDENCE and not all(
            (
                self.sq_id,
                self.evidence_claim,
                self.evidence_bundle,
                self.answer_revision,
                self.bound_evidence,
                self.prepared_answer,
            )
        ):
            raise ValueError(
                "evidence verification must bind its SQ, canonical evidence, and answer revisions"
            )
        return self


class ReviewPolicy(FrozenModel):
    reference: RecordReference
    domain_ids: tuple[Identifier, ...] = Field(min_length=1)
    action_order: tuple[ActionKind, ...] = tuple(ActionKind)
    required_finding_requirements: tuple[FindingRequirement, ...] = tuple(FindingRequirement)


class DomainQuestionSummary(FrozenModel):
    sq_id: Identifier
    guidance: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_count: int = Field(ge=0)


class DomainReviewSummary(FrozenModel):
    domain_id: Identifier
    full_name: str = Field(min_length=1)
    judgment: str = Field(min_length=1)
    active_sq_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    coverage: str = Field(min_length=1)
    deterministic_basis: str = Field(min_length=1)
    coverage_acknowledged: bool = False
    active_questions: tuple[DomainQuestionSummary, ...] = ()


class ReviewCase(FrozenModel):
    review_id: Identifier
    review_revision: RecordReference
    assessment: RecordReference
    policy: ReviewPolicy
    assessment_revision_id: Identifier
    assessment_content_hash: ContentHash
    result_label: str = Field(min_length=1)
    domain_ids: tuple[Identifier, ...] = Field(min_length=1)
    actions: tuple[ReviewAction, ...] = ()
    domain_summaries: tuple[DomainReviewSummary, ...] = ()
    preparation_scopes: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action_ids(self) -> ReviewCase:
        if self.assessment.revision_id != self.assessment_revision_id:
            raise ValueError("assessment binding must match assessment_revision_id")
        if self.assessment.content_hash != self.assessment_content_hash:
            raise ValueError("assessment binding must match assessment_content_hash")
        if self.policy.domain_ids != self.domain_ids:
            raise ValueError("Review policy must define the reviewed domains")
        if len({action.action_id for action in self.actions}) != len(self.actions):
            raise ValueError("review action IDs must be unique")
        finding_ids = [
            action.finding_id for action in self.actions if action.finding_id is not None
        ]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("one underlying finding must produce one Review action")
        summary_ids = {summary.domain_id for summary in self.domain_summaries}
        if summary_ids and summary_ids != set(self.domain_ids):
            raise ValueError("Domain summaries must cover every reviewed Domain exactly once")
        return self


class QueueItem(FrozenModel):
    action_id: Identifier
    kind: ActionKind
    title: str
    domain_id: Identifier | None = None
    sq_id: Identifier | None = None
    evidence_text: str | None = None
    highlighted_region: tuple[int, int] | None = None
    source_locator: str | None = None
    answer_visible: bool = False
    staged_answer: str | None = None
    staged_rationale: str | None = None
    correction_prepared_answer: str | None = None
    correction_prepared_rationale: str | None = None
    completed: bool = False
    finding_id: Identifier | None = None
    evidence_claim: RecordReference | None = None
    evidence_bundle: RecordReference | None = None
    answer_revision: RecordReference | None = None
    consequence: str | None = None
    correction_checkpoint: Identifier | None = None
    source_role: str | None = None
    source_criticality: str | None = None
    relevant_dates: tuple[str, ...] = ()
    acquisition_attempts: tuple[str, ...] = ()
    final_coverage: str | None = None
    affected_scope: tuple[Identifier, ...] = ()
    crop_reference: RecordReference | None = None
    next_action: str | None = None
    attention_tier: AttentionTier
    reasons: tuple[str, ...] = ()
    affected_context: str
    actionable: bool = True
    domain_summary: DomainReviewSummary | None = None


class ReviewCommand(FrozenModel):
    idempotency_key: Identifier
    action_id: Identifier
    kind: ActionKind
    expected_assessment_revision_id: Identifier
    actor: Actor
    value: ActionDecision
    rationale: str | None = None
    confirmed_display_name: str | None = None
    reviewer_profile: RecordReference
    review_session_id: Identifier
    observed_at: datetime
    domain_opened: bool = False
    correction_scope: CorrectionScope | None = None

    @model_validator(mode="after")
    def validate_time(self) -> ReviewCommand:
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        if (
            self.value is ActionDecision.CORRECTION_REQUESTED
            and not (self.rationale and self.rationale.strip())
        ):
            raise ValueError("correction requests require a request")
        return self


class CorrectionRequest(FrozenModel):
    challenged_assessment: RecordReference
    result_label: str
    domain_id: Identifier | None = None
    sq_id: Identifier | None = None
    evidence_claim: RecordReference | None = None
    exact_text: str | None = None
    highlighted_region: tuple[int, int] | None = None
    prepared_answer: str | None = None
    prepared_rationale: str | None = None
    request: str = Field(min_length=1)
    minimum_scope: CorrectionScope
    requested_scope: CorrectionScope
    affected_scope: tuple[Identifier, ...]
    agent_prompt: str = Field(min_length=1)
    disposition: str = "pending_targeted_rework"
    last_checkpoint: Identifier | None = None
    failure_reason: str | None = None
    resume_action: str = Field(min_length=1)
    predecessor_receipt_revision_id: Identifier | None = None


class CorrectionReworkStatus(StrEnum):
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


class CorrectionComparison(FrozenModel):
    evidence_consideration: tuple[str, ...] = Field(min_length=1)
    answer_and_rationale: tuple[str, ...] = Field(min_length=1)
    judgments: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    reopened_decisions: tuple[Identifier, ...] = Field(min_length=1)
    reused_unaffected_work: tuple[str, ...] = Field(min_length=1)


class CorrectionReworkCommand(FrozenModel):
    operation_key: Identifier
    correction_receipt_revision_id: Identifier
    actor: Actor
    observed_at: datetime
    status: CorrectionReworkStatus
    last_checkpoint: Identifier
    failure_reason: str | None = None
    resume_action: str | None = None
    superseding_assessment_revision_id: Identifier | None = None
    assessment_artifact: bytes | None = None
    corrected_sq_id: Identifier | None = None
    corrected_evidence_id: Identifier | None = None
    superseding_review_case: ReviewCase | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> CorrectionReworkCommand:
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        if self.status is CorrectionReworkStatus.SUCCEEDED and not all(
            (
                self.superseding_assessment_revision_id,
                self.assessment_artifact,
                self.corrected_sq_id,
                self.superseding_review_case,
            )
        ):
            raise ValueError(
                "successful rework requires an Assessment and corrected SQ"
            )
        if self.status is CorrectionReworkStatus.SUCCEEDED and (
            self.failure_reason is not None or self.resume_action is not None
        ):
            raise ValueError(
                "successful rework cannot include failure or resume details"
            )
        if self.status is not CorrectionReworkStatus.SUCCEEDED and not (
            self.failure_reason and self.resume_action
        ):
            raise ValueError("interrupted or failed rework requires failure and resume details")
        if self.status is not CorrectionReworkStatus.SUCCEEDED and any(
            value is not None
            for value in (
                self.superseding_assessment_revision_id,
                self.assessment_artifact,
                self.corrected_sq_id,
                self.corrected_evidence_id,
                self.superseding_review_case,
            )
        ):
            raise ValueError(
                "interrupted or failed rework cannot include successful outputs"
            )
        return self


class CorrectionReworkState(FrozenModel):
    revision_id: Identifier
    correction_receipt_revision_id: Identifier
    status: CorrectionReworkStatus
    actor: Actor
    last_checkpoint: Identifier
    failure_reason: str | None = None
    resume_action: str | None = None
    challenged_assessment: RecordReference
    current_proposed_assessment: RecordReference | None = None
    corrected_sq_id: Identifier | None = None
    corrected_evidence_id: Identifier | None = None
    comparison: CorrectionComparison | None = None
    current_review_case: ReviewCase | None = None


class DurableReviewReceipt(FrozenModel):
    revision_id: Identifier
    outcome: ReviewReceiptOutcome
    review_action_id: Identifier
    assessment_revision_id: Identifier
    assessment: RecordReference
    review_revision: RecordReference
    review_policy: RecordReference
    reviewer_profile: RecordReference
    review_session_id: Identifier
    actor: Actor
    ledger_event_id: Identifier
    value: ActionDecision
    rationale: str | None = None
    correction_checkpoint: Identifier | None = None
    correction_request: CorrectionRequest | None = None
    assurance: str | None = None


class ReviewCommit(FrozenModel):
    receipt: DurableReviewReceipt
    duplicate: bool


class SignOffWithdrawalCommand(FrozenModel):
    idempotency_key: Identifier
    expected_assessment_revision_id: Identifier
    expected_sign_off_revision_id: Identifier
    actor: Actor
    reviewer_profile: RecordReference
    reason: str = Field(min_length=1)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> SignOffWithdrawalCommand:
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        return self


class ReviewService:
    """Commit human-only review decisions and derive all current review state."""

    def __init__(
        self,
        ledger: WorkflowLedger,
        lease: LeaseToken,
        review_case: ReviewCase,
    ) -> None:
        self.ledger = ledger
        self.lease = lease
        self.review_case = review_case
        self._connection_state = ConnectionState.CONNECTED_WAITING
        self._last_contact = datetime.now(UTC)
        self.ledger.preflight()
        self._validate_preparation_outcomes()
        self._restore_current_proposed_assessment()

    def queue(self) -> tuple[QueueItem, ...]:
        completed = self._receipts_by_action()
        stale = self.is_stale()
        pending_corrections = tuple(
            receipt.correction_request
            for receipt in completed.values()
            if receipt.correction_request is not None
        )

        def blocked_by_correction(action: ReviewAction) -> bool:
            for correction in pending_corrections:
                if correction.requested_scope is CorrectionScope.RESULT:
                    return True
                if (
                    action.domain_id is not None
                    and action.domain_id in correction.affected_scope
                ):
                    return True
            return False

        limitation_acknowledged = any(
            action.kind is ActionKind.ACKNOWLEDGE_LIMITATION
            and completed.get(action.action_id) is not None
            and completed[action.action_id].outcome
            is ReviewReceiptOutcome.ACTION_COMPLETED
            for action in self.review_case.actions
        )
        summaries = {
            summary.domain_id: (
                summary.model_copy(update={"coverage_acknowledged": True})
                if limitation_acknowledged
                and summary.coverage.casefold() not in {"complete", "adequate"}
                else summary
            )
            for summary in self.review_case.domain_summaries
        }
        actions = {action.action_id: action for action in self.review_case.actions}
        for domain_id in self.review_case.policy.domain_ids:
            action_id = _domain_action_id(domain_id)
            actions.setdefault(
                action_id,
                ReviewAction(
                    action_id=action_id,
                    kind=ActionKind.DOMAIN_REVIEW,
                    domain_id=domain_id,
                    title=f"Review {domain_id.replace(':', ' ')}",
                ),
            )
        if self._sign_off_eligible(completed):
            actions["review-action:sign-off"] = ReviewAction(
                action_id="review-action:sign-off",
                kind=ActionKind.SIGN_OFF,
                title="Sign off this exact Assessment revision",
            )
        items = []
        order = {
            kind: position for position, kind in enumerate(self.review_case.policy.action_order)
        }

        def queue_key(action: ReviewAction) -> tuple[int, int, int, int, str]:
            receipt = completed.get(action.action_id)
            actionable = receipt is None and not stale and not blocked_by_correction(action)
            if receipt is not None and receipt.outcome is ReviewReceiptOutcome.CORRECTION_REQUESTED:
                actionable = False
            tier, _ = self._attention(
                action,
                receipt,
                summaries.get(action.domain_id),
                stale=stale,
                blocked_by_correction=blocked_by_correction(action),
            )
            return (
                0 if actionable else 1,
                tuple(AttentionTier).index(tier),
                order[action.kind],
                _domain_order(action.domain_id),
                action.action_id,
            )

        ordered_actions = sorted(actions.values(), key=queue_key)
        for action in ordered_actions:
            receipt = completed.get(action.action_id)
            summary = summaries.get(action.domain_id)
            attention_tier, reasons = self._attention(
                action,
                receipt,
                summary,
                stale=stale,
                blocked_by_correction=blocked_by_correction(action),
            )
            answer_visible = (
                action.kind is ActionKind.VERIFY_EVIDENCE
                and receipt is not None
                and receipt.outcome is ReviewReceiptOutcome.ACTION_COMPLETED
            )
            items.append(
                QueueItem(
                    **action.model_dump(
                        exclude={
                            "bound_evidence",
                            "prepared_answer",
                            "finding_requirement",
                            "consequence",
                            "next_action",
                            "accepted_contradiction",
                            "source_conflict",
                            "elevated_visual_transcription",
                            "no_information",
                            "influential_project_rule",
                            "judgment_override",
                        }
                    ),
                    evidence_text=(
                        action.bound_evidence.quote() if action.bound_evidence is not None else None
                    ),
                    highlighted_region=(
                        (action.bound_evidence.span_start, action.bound_evidence.span_end)
                        if action.bound_evidence is not None
                        else None
                    ),
                    answer_visible=answer_visible,
                    staged_answer=(
                        action.prepared_answer.answer
                        if answer_visible and action.prepared_answer is not None
                        else None
                    ),
                    staged_rationale=(
                        action.prepared_answer.rationale
                        if answer_visible and action.prepared_answer is not None
                        else None
                    ),
                    correction_prepared_answer=(
                        action.prepared_answer.answer
                        if action.prepared_answer is not None
                        else None
                    ),
                    correction_prepared_rationale=(
                        action.prepared_answer.rationale
                        if action.prepared_answer is not None
                        else None
                    ),
                    completed=receipt is not None,
                    attention_tier=attention_tier,
                    reasons=reasons,
                    affected_context=self._affected_context(action),
                    actionable=(
                        receipt is None and not stale and not blocked_by_correction(action)
                    ),
                    domain_summary=summary,
                    consequence=action.consequence or self._default_consequence(action),
                    next_action=action.next_action or self._default_next_action(action),
                )
            )
        return tuple(items)

    def commit(self, command: ReviewCommand) -> ReviewCommit:
        if command.actor.kind is not ActorKind.HUMAN:
            raise ValueError("review actions require a human actor")
        if (
            command.value is ActionDecision.CORRECTION_REQUESTED
            and self._receipt_for_operation(command.idempotency_key) is None
        ):
            pending = next(
                (
                    receipt
                    for receipt in reversed(self.correction_receipts())
                    if (
                        state := self.correction_state(receipt.revision_id)
                    ) is None
                    or state.status is not CorrectionReworkStatus.SUCCEEDED
                ),
                None,
            )
            if pending is not None:
                raise ReviewError(
                    "a correction is already pending; the revision chain cannot branch"
                )
        prior = self._receipt_for_operation(command.idempotency_key)
        if prior is not None:
            if (
                prior.review_action_id != command.action_id
                or prior.assessment_revision_id != command.expected_assessment_revision_id
            ):
                raise ReviewError("idempotency key was already used for different review work")
            return ReviewCommit(receipt=prior, duplicate=True)
        if (
            command.expected_assessment_revision_id != self.review_case.assessment_revision_id
            or self.is_stale()
        ):
            raise StaleReviewError("this review page is stale and is now read-only")
        completed_action = self._receipts_by_action().get(command.action_id)
        if completed_action is not None:
            return ReviewCommit(receipt=completed_action, duplicate=True)
        actions = {item.action_id: item for item in self.queue()}
        if command.kind is ActionKind.SIGN_OFF:
            if not self._sign_off_eligible(self._receipts_by_action()):
                raise SignOffBlockedError("all findings and five domains must be reviewed")
            if command.confirmed_display_name != command.actor.display_name:
                raise SignOffBlockedError("sign-off must reconfirm the visible reviewer identity")
        elif (
            command.action_id not in actions
            or actions[command.action_id].kind is not command.kind
        ):
            raise ReviewError("review action is not currently permitted")
        elif not actions[command.action_id].actionable:
            raise ReviewError("review action is read-only while targeted rework is pending")
        elif command.kind is ActionKind.DOMAIN_REVIEW and not command.domain_opened:
            raise ReviewError("the individual Domain must be opened before confirmation")

        self._connection_state = ConnectionState.WORKING
        receipt_id = self._receipt_revision_id(command)
        selected_action = actions.get(command.action_id)
        receipt_entity_id = f"review-receipt:{command.action_id.split(':', 1)[1]}"
        current_receipt = next(
            (
                revision
                for revision in self.ledger.current_revisions()
                if revision.entity_id == receipt_entity_id
            ),
            None,
        )
        correction_request = (
            self._correction_request(command, selected_action, receipt_id)
            if command.value is ActionDecision.CORRECTION_REQUESTED
            and selected_action is not None
            else None
        )
        payload = {
            "revision_id": receipt_id,
            "outcome": self._receipt_outcome(command),
            "review_action_id": command.action_id,
            "assessment_revision_id": self.review_case.assessment_revision_id,
            "assessment": self.review_case.assessment.model_dump(mode="json"),
            "review_revision": self.review_case.review_revision.model_dump(mode="json"),
            "review_policy": self.review_case.policy.reference.model_dump(mode="json"),
            "reviewer_profile": command.reviewer_profile.model_dump(mode="json"),
            "review_session_id": command.review_session_id,
            "actor": command.actor.model_dump(mode="json"),
            "ledger_event_id": "event:pending",
            "value": command.value,
            "rationale": command.rationale,
            "correction_checkpoint": (
                selected_action.correction_checkpoint
                if command.value is ActionDecision.CORRECTION_REQUESTED
                and selected_action is not None
                else None
            ),
            "correction_request": (
                correction_request.model_dump(mode="json")
                if correction_request is not None
                else None
            ),
            "assurance": (
                "local_human_attribution" if command.kind is ActionKind.SIGN_OFF else None
            ),
        }
        result = self.ledger.commit(
            Transition(
                scope=self.review_case.review_id,
                operation=f"review:{command.kind.value}",
                operation_key=command.idempotency_key,
                actor=command.actor,
                observed_at=command.observed_at,
                entity_id=receipt_entity_id,
                revision_id=receipt_id,
                artifact=json.dumps(payload, ensure_ascii=False).encode(),
                artifact_media_type="application/json",
                dependencies=(),
                expected_dependency_fingerprint=dependency_fingerprint(()),
                checkpoint=f"review-checkpoint:{command.action_id.split(':', 1)[1]}",
                outcome=self._workflow_outcome(command),
                supersedes_revision_id=(
                    current_receipt.revision_id if current_receipt is not None else None
                ),
            ),
            self.lease,
            now=command.observed_at,
        )
        receipt = DurableReviewReceipt.model_validate(
            {**payload, "ledger_event_id": result.event_id}
        )
        self._commit_canonical_review_revision(command, receipt)
        self._connection_state = (
            ConnectionState.COMPLETE
            if command.kind is ActionKind.SIGN_OFF
            else ConnectionState.CONNECTED_WAITING
        )
        self._last_contact = command.observed_at
        return ReviewCommit(receipt=receipt, duplicate=False)

    def _commit_canonical_review_revision(
        self, command: ReviewCommand, receipt: DurableReviewReceipt
    ) -> None:
        if command.kind not in {ActionKind.DOMAIN_REVIEW, ActionKind.SIGN_OFF}:
            return
        profile = self._canonical_reviewer_profile(command)
        if command.kind is ActionKind.DOMAIN_REVIEW:
            domain_id = _domain_id_from_action(command.action_id)
            review_key = self.review_case.review_id.split(":", 1)[1]
            domain_key = domain_id.split(":", 1)[1]
            disposition = DomainReviewDisposition(
                entity_id=f"domain-review-disposition:{review_key}-{domain_key}",
                revision_id=f"revision:domain-disposition-{receipt.revision_id.split(':', 1)[1]}",
                dependencies=self._revision_dependencies(
                    (self.review_case.assessment, profile),
                    ("dependency:assessment", "dependency:reviewer-profile"),
                ),
                actor=command.actor,
                observed_at=command.observed_at,
                domain_id=domain_id,
                disposition={
                    ActionDecision.ACCEPTED: DomainReviewDispositionKind.ACCEPT,
                    ActionDecision.CORRECTION_REQUESTED: DomainReviewDispositionKind.CORRECT,
                    ActionDecision.OVERRIDDEN: DomainReviewDispositionKind.OVERRIDE,
                    ActionDecision.DEFERRED: DomainReviewDispositionKind.DEFER,
                }.get(command.value, DomainReviewDispositionKind.ACCEPT),
                assessment=self.review_case.assessment,
                reviewer_profile=profile,
                rationale=command.rationale,
            )
            self._commit_canonical(
                disposition,
                operation="review:canonical-domain-disposition",
                operation_key=f"{command.idempotency_key}:canonical",
            )
            return
        current_revision_ids = {
            revision.revision_id for revision in self.ledger.current_revisions()
        }
        dispositions = tuple(
            self._canonical_reference(event)
            for event in self.ledger.events()
            if event.scope == self.review_case.review_id
            and event.operation == "review:canonical-domain-disposition"
            and event.revision_id in current_revision_ids
        )
        disposition_domains = {
            DomainReviewDisposition.model_validate_json(
                self.ledger.artifacts.read(reference.content_hash)
            ).domain_id
            for reference in dispositions
        }
        if (
            len(dispositions) != len(self.review_case.policy.domain_ids)
            or disposition_domains != set(self.review_case.policy.domain_ids)
        ):
            raise SignOffBlockedError(
                "sign-off requires exactly one current disposition for every Domain"
            )
        assessment_key = self.review_case.assessment.entity_id.split(":", 1)[1]
        sign_off = AssessmentSignOff(
            entity_id=f"assessment-sign-off:{assessment_key}",
            revision_id=f"revision:assessment-sign-off-{receipt.revision_id.split(':', 1)[1]}",
            dependencies=self._revision_dependencies(
                (
                    self.review_case.assessment,
                    profile,
                    *dispositions,
                    self.review_case.policy.reference,
                ),
                (
                    "dependency:assessment",
                    "dependency:reviewer-profile",
                    *(["dependency:domain-review-disposition"] * len(dispositions)),
                    "dependency:review-policy",
                ),
            ),
            actor=command.actor,
            observed_at=command.observed_at,
            assessment=self.review_case.assessment,
            reviewer_profile=profile,
            domain_dispositions=dispositions,
            review_policy=self.review_case.policy.reference,
        )
        self._commit_canonical(
            sign_off,
            operation="review:canonical-assessment-sign-off",
            operation_key=f"{command.idempotency_key}:canonical",
        )

    def _canonical_reviewer_profile(self, command: ReviewCommand) -> RecordReference:
        existing = next(
            (
                self._canonical_reference(event)
                for event in reversed(self.ledger.events())
                if event.scope == self.review_case.review_id
                and event.operation == "review:canonical-reviewer-profile"
            ),
            None,
        )
        if existing is not None:
            return existing
        profile = ReviewerProfileRevision(
            entity_id=f"reviewer-profile:{command.actor.actor_id.split(':', 1)[1]}",
            revision_id=f"revision:reviewer-profile-{command.review_session_id.split(':', 1)[1]}",
            dependencies=(),
            actor=command.actor,
            observed_at=command.observed_at,
            display_name=command.actor.display_name,
        )
        return self._commit_canonical(
            profile,
            operation="review:canonical-reviewer-profile",
            operation_key=f"canonical-profile:{command.review_session_id}",
        )

    def _commit_canonical(
        self, revision, *, operation: str, operation_key: str
    ) -> RecordReference:
        ledger_dependencies = tuple(
            DependencyInput(
                entity_id=item.entity_id,
                revision_id=item.revision_id,
                role=item.role,
                content_hash=item.content_hash,
            )
            for item in revision.dependencies
            if any(
                current.entity_id == item.entity_id
                and current.revision_id == item.revision_id
                and current.artifact_hash == item.content_hash
                for current in self.ledger.current_revisions()
            )
        )
        result = self.ledger.commit(
            Transition(
                scope=self.review_case.review_id,
                operation=operation,
                operation_key=operation_key,
                actor=revision.actor,
                observed_at=revision.observed_at,
                entity_id=revision.entity_id,
                revision_id=revision.revision_id,
                artifact=revision.model_dump_json().encode(),
                artifact_media_type="application/json",
                dependencies=ledger_dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(ledger_dependencies),
                outcome=WorkflowEventOutcome.COMPLETED,
            ),
            self.lease,
            now=revision.observed_at,
        )
        return RecordReference(
            entity_id=revision.entity_id,
            revision_id=revision.revision_id,
            content_hash=result.artifact_hash,
        )

    def _canonical_reference(self, event: WorkflowEvent) -> RecordReference:
        return RecordReference(
            entity_id=event.entity_id,
            revision_id=event.revision_id,
            content_hash=event.output_revision_hashes[0],
        )

    def _revision_dependencies(
        self, references: tuple[RecordReference, ...], roles: tuple[str, ...]
    ) -> tuple[Dependency, ...]:
        return tuple(
            Dependency(
                entity_id=reference.entity_id,
                revision_id=reference.revision_id,
                role=role,
                content_hash=reference.content_hash,
            )
            for reference, role in zip(references, roles, strict=True)
        )

    def connection_state(self) -> ConnectionState:
        return self._connection_state

    def withdraw_sign_off(
        self, command: SignOffWithdrawalCommand
    ) -> RecordReference:
        """Reopen one exact signed Result without deleting its signed history."""
        if command.actor.kind is not ActorKind.HUMAN:
            raise ValueError("sign-off withdrawal requires a human actor")
        if (
            command.expected_assessment_revision_id
            != self.review_case.assessment_revision_id
            or self.is_stale()
        ):
            raise StaleReviewError("this review page is stale and is now read-only")
        sign_off_event = next(
            (
                event
                for event in reversed(self.ledger.events())
                if event.scope == self.review_case.review_id
                and event.operation == "review:canonical-assessment-sign-off"
                and event.revision_id == command.expected_sign_off_revision_id
            ),
            None,
        )
        if sign_off_event is None:
            raise ReviewError("the requested sign-off is not current for this Result")
        existing = next(
            (
                event
                for event in self.ledger.events()
                if event.operation_key == command.idempotency_key
            ),
            None,
        )
        if existing is not None:
            if existing.operation != "review:canonical-sign-off-withdrawal":
                raise ReviewError("idempotency key was already used for different review work")
            return self._canonical_reference(existing)
        profile = self._canonical_reviewer_profile(
            ReviewCommand(
                idempotency_key=f"{command.idempotency_key}:profile",
                action_id="review-action:sign-off",
                kind=ActionKind.SIGN_OFF,
                expected_assessment_revision_id=command.expected_assessment_revision_id,
                actor=command.actor,
                value=ActionDecision.SIGNED,
                reviewer_profile=command.reviewer_profile,
                review_session_id=(
                    "review-session:withdraw-"
                    f"{command.actor.actor_id.split(':', 1)[1]}"
                ),
                observed_at=command.observed_at,
                confirmed_display_name=command.actor.display_name,
            )
        )
        sign_off = self._canonical_reference(sign_off_event)
        withdrawal = SignOffWithdrawal(
            entity_id=f"sign-off-withdrawal:{sign_off.revision_id.split(':', 1)[1]}",
            revision_id=f"revision:sign-off-withdrawal-{command.idempotency_key.split(':', 1)[1]}",
            dependencies=self._revision_dependencies(
                (sign_off, profile),
                ("dependency:assessment-sign-off", "dependency:reviewer-profile"),
            ),
            actor=command.actor,
            observed_at=command.observed_at,
            sign_off=sign_off,
            reviewer_profile=profile,
            reason=command.reason,
        )
        reference = self._commit_canonical(
            withdrawal,
            operation="review:canonical-sign-off-withdrawal",
            operation_key=command.idempotency_key,
        )
        self._connection_state = ConnectionState.CONNECTED_WAITING
        self._last_contact = command.observed_at
        return reference

    def last_contact(self) -> datetime:
        return self._last_contact

    def heartbeat(self) -> None:
        """Record local browser activity without changing authoritative review state."""
        if self._connection_state is not ConnectionState.COMPLETE:
            self._connection_state = ConnectionState.CONNECTED_WAITING
        self._last_contact = datetime.now(UTC)

    def is_stale(self) -> bool:
        current = next(
            (
                revision
                for revision in self.ledger.current_revisions()
                if revision.entity_id == self.review_case.assessment.entity_id
            ),
            None,
        )
        return (
            current is not None
            and current.revision_id != self.review_case.assessment.revision_id
        )

    def latest_receipt(self, *, after_sequence: int = 0) -> DurableReviewReceipt | None:
        for event in reversed(self.ledger.events()):
            if (
                event.sequence > after_sequence
                and event.scope == self.review_case.review_id
                and event.operation.startswith("review:")
                and not event.operation.startswith("review:canonical-")
            ):
                return self._receipt_from_event(event)
        return None

    def correction_receipts(self) -> tuple[DurableReviewReceipt, ...]:
        """Return the durable linear correction chain for this review."""
        receipts = (
            self._receipt_from_event(event)
            for event in self.ledger.events()
            if event.scope == self.review_case.review_id
            and event.operation.startswith("review:")
            and not event.operation.startswith("review:canonical-")
        )
        return tuple(receipt for receipt in receipts if receipt.correction_request is not None)

    def correction_state(
        self, correction_receipt_revision_id: Identifier
    ) -> CorrectionReworkState | None:
        states = (
            event
            for event in reversed(self.ledger.events())
            if event.operation.startswith("correction:targeted-rework")
        )
        for event in states:
            payload = json.loads(self.ledger.artifacts.read(event.output_revision_hashes[0]))
            if payload["correction_receipt_revision_id"] == correction_receipt_revision_id:
                state = CorrectionReworkState.model_validate(payload)
                proposed = state.current_proposed_assessment
                if state.status is CorrectionReworkStatus.SUCCEEDED and proposed is not None:
                    current = next(
                        (
                            revision
                            for revision in self.ledger.current_revisions()
                            if revision.entity_id == proposed.entity_id
                        ),
                        None,
                    )
                    if current is None or current.revision_id != proposed.revision_id:
                        return state.model_copy(
                            update={
                                "status": CorrectionReworkStatus.INTERRUPTED,
                                "failure_reason": (
                                    "Assessment supersession was interrupted after rework."
                                ),
                                "resume_action": (
                                    "Retry submit_targeted_rework with the same idempotency key."
                                ),
                            }
                        )
                return state
        return None

    def submit_targeted_rework(
        self, command: CorrectionReworkCommand
    ) -> CorrectionReworkState:
        receipt = next(
            (
                candidate
                for candidate in self.correction_receipts()
                if candidate.revision_id == command.correction_receipt_revision_id
            ),
            None,
        )
        if receipt is None or receipt.correction_request is None:
            raise ReviewError("targeted rework must bind an existing correction receipt")
        duplicate = next(
            (
                event
                for event in self.ledger.events()
                if event.operation_key == command.operation_key
                and event.operation == "correction:targeted-rework"
            ),
            None,
        )
        if duplicate is not None:
            state = CorrectionReworkState.model_validate_json(
                self.ledger.artifacts.read(duplicate.output_revision_hashes[0])
            )
            if (
                state.correction_receipt_revision_id
                != command.correction_receipt_revision_id
                or state.status is not command.status
                or state.actor != command.actor
                or state.last_checkpoint != command.last_checkpoint
                or state.failure_reason != command.failure_reason
                or state.resume_action != command.resume_action
                or state.corrected_sq_id != command.corrected_sq_id
                or state.corrected_evidence_id != command.corrected_evidence_id
                or state.current_review_case != command.superseding_review_case
            ):
                raise ReviewError("idempotency key was reused for different rework")
            if state.status is CorrectionReworkStatus.SUCCEEDED:
                submitted_hash = self.ledger.artifacts.put(
                    command.assessment_artifact or b"", "application/json"
                ).content_hash
                if (
                    state.current_proposed_assessment is None
                    or state.current_proposed_assessment.revision_id
                    != command.superseding_assessment_revision_id
                    or state.current_proposed_assessment.content_hash != submitted_hash
                ):
                    raise ReviewError(
                        "idempotency key was reused with different rework content"
                    )
            return self._apply_successful_rework(command, receipt, state)
        prior = self.correction_state(command.correction_receipt_revision_id)
        proposed: RecordReference | None = None
        comparison: CorrectionComparison | None = None
        if command.status is CorrectionReworkStatus.SUCCEEDED:
            correction = receipt.correction_request
            if (
                correction.sq_id is not None
                and command.corrected_sq_id != correction.sq_id
            ):
                raise ValueError("successful rework must resume at the challenged SQ")
            if correction.sq_id is None:
                allowed_questions = {
                    question.sq_id
                    for summary in self.review_case.domain_summaries
                    if (
                        correction.domain_id is None
                        or summary.domain_id == correction.domain_id
                    )
                    for question in summary.active_questions
                }
                if (
                    allowed_questions
                    and command.corrected_sq_id not in allowed_questions
                ):
                    raise ValueError(
                        "successful rework must resume within the challenged scope"
                    )
            if (
                correction.evidence_claim is not None
                and command.corrected_evidence_id
                != correction.evidence_claim.entity_id
            ):
                raise ValueError(
                    "evidence correction must resume with the triggering evidence context"
                )
            challenged = AssessmentRevision.model_validate_json(
                self.ledger.artifacts.read(receipt.assessment.content_hash)
            )
            superseding = AssessmentRevision.model_validate_json(
                command.assessment_artifact or b""
            )
            if (
                superseding.entity_id != challenged.entity_id
                or superseding.revision_id
                != command.superseding_assessment_revision_id
                or superseding.supersedes is None
                or superseding.supersedes.entity_id != challenged.entity_id
                or superseding.supersedes.revision_id != challenged.revision_id
                or superseding.supersedes.content_hash != receipt.assessment.content_hash
            ):
                raise ValueError(
                    "superseding Assessment must link the exact challenged revision"
                )
            comparison = _derive_correction_comparison(
                challenged,
                superseding,
                correction.affected_scope,
                correction.requested_scope,
                self.review_case.domain_ids,
                self.ledger,
            )
            artifact = self.ledger.artifacts.put(
                command.assessment_artifact or b"", "application/json"
            )
            if artifact.content_hash == receipt.assessment.content_hash:
                raise ValueError(
                    "successful rework must produce a changed Assessment revision"
                )
            proposed = RecordReference(
                entity_id=receipt.assessment.entity_id,
                revision_id=command.superseding_assessment_revision_id or "",
                content_hash=artifact.content_hash,
            )
            self._validate_superseding_review_case(
                command.superseding_review_case,
                proposed,
                superseding,
                correction,
                command.corrected_sq_id,
            )
        state_id = self._rework_revision_id(command)
        state = CorrectionReworkState(
            revision_id=state_id,
            correction_receipt_revision_id=command.correction_receipt_revision_id,
            status=command.status,
            actor=command.actor,
            last_checkpoint=command.last_checkpoint,
            failure_reason=command.failure_reason,
            resume_action=command.resume_action,
            challenged_assessment=receipt.assessment,
            current_proposed_assessment=proposed,
            corrected_sq_id=command.corrected_sq_id,
            corrected_evidence_id=command.corrected_evidence_id,
            comparison=comparison,
            current_review_case=command.superseding_review_case,
        )
        entity_id = f"correction-rework:{command.correction_receipt_revision_id.split(':')[-1]}"
        state_dependencies = self._rework_dependencies(receipt)
        self.ledger.commit(
            Transition(
                scope=self.review_case.review_id,
                operation="correction:targeted-rework",
                operation_key=command.operation_key,
                actor=command.actor,
                observed_at=command.observed_at,
                entity_id=entity_id,
                revision_id=state_id,
                artifact=state.model_dump_json().encode(),
                artifact_media_type="application/json",
                dependencies=state_dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(
                    state_dependencies
                ),
                checkpoint=command.last_checkpoint,
                outcome=(
                    WorkflowEventOutcome.COMPLETED
                    if command.status is CorrectionReworkStatus.SUCCEEDED
                    else WorkflowEventOutcome.RETRYABLE_INTERRUPTION
                ),
                causation_id=receipt.ledger_event_id,
                correlation_id=receipt.revision_id,
                supersedes_revision_id=prior.revision_id if prior is not None else None,
            ),
            self.lease,
            now=command.observed_at,
        )
        return self._apply_successful_rework(command, receipt, state)

    def _apply_successful_rework(
        self,
        command: CorrectionReworkCommand,
        receipt: DurableReviewReceipt,
        state: CorrectionReworkState,
    ) -> CorrectionReworkState:
        proposed = state.current_proposed_assessment
        if state.status is not CorrectionReworkStatus.SUCCEEDED or proposed is None:
            return state
        current = next(
            (
                revision
                for revision in self.ledger.current_revisions()
                if revision.entity_id == receipt.assessment.entity_id
            ),
            None,
        )
        if current is not None and current.revision_id == proposed.revision_id:
            self._adopt_proposed_assessment(proposed, state.current_review_case)
            return self._commit_applied_rework_state(command, receipt, state)
        if current is None or current.revision_id != receipt.assessment.revision_id:
            raise StaleReviewError(
                "the challenged Assessment is no longer the single current revision"
            )
        assessment = AssessmentRevision.model_validate_json(
            command.assessment_artifact or b""
        )
        dependencies = tuple(
            DependencyInput(
                entity_id=dependency.entity_id,
                revision_id=dependency.revision_id,
                role=dependency.role,
                content_hash=dependency.content_hash,
            )
            for dependency in assessment.dependencies
        )
        committed = self.ledger.commit(
            Transition(
                scope=self.review_case.review_id,
                operation="correction:supersede-assessment",
                operation_key=f"{command.operation_key}:assessment",
                actor=command.actor,
                observed_at=command.observed_at,
                entity_id=receipt.assessment.entity_id,
                revision_id=proposed.revision_id,
                artifact=command.assessment_artifact or b"",
                artifact_media_type="application/json",
                dependencies=dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(dependencies),
                checkpoint=command.last_checkpoint,
                outcome=WorkflowEventOutcome.COMPLETED,
                causation_id=receipt.ledger_event_id,
                correlation_id=receipt.revision_id,
                supersedes_revision_id=receipt.assessment.revision_id,
            ),
            self.lease,
            now=command.observed_at,
        )
        if committed.artifact_hash != proposed.content_hash:
            raise ValueError("retried Assessment bytes differ from the recorded proposed revision")
        self._adopt_proposed_assessment(proposed, state.current_review_case)
        return self._commit_applied_rework_state(command, receipt, state)

    def _rework_dependencies(
        self,
        receipt: DurableReviewReceipt,
        proposed: RecordReference | None = None,
    ) -> tuple[DependencyInput, ...]:
        receipt_event = next(
            event
            for event in self.ledger.events()
            if event.revision_id == receipt.revision_id
        )
        references = [
            (
                RecordReference(
                    entity_id=receipt_event.entity_id,
                    revision_id=receipt_event.revision_id,
                    content_hash=receipt_event.output_revision_hashes[0],
                ),
                "dependency:correction-receipt",
            ),
            (receipt.assessment, "dependency:challenged-assessment"),
        ]
        if proposed is not None:
            references.append((proposed, "dependency:proposed-assessment"))
        return tuple(
            DependencyInput(**reference.model_dump(), role=role)
            for reference, role in references
        )

    def _commit_applied_rework_state(
        self,
        command: CorrectionReworkCommand,
        receipt: DurableReviewReceipt,
        state: CorrectionReworkState,
    ) -> CorrectionReworkState:
        proposed = state.current_proposed_assessment
        assert proposed is not None
        applied_id = f"{state.revision_id}-applied"
        entity_id = (
            f"correction-rework:{state.correction_receipt_revision_id.split(':')[-1]}"
        )
        current = next(
            (
                revision
                for revision in self.ledger.current_revisions()
                if revision.entity_id == entity_id
            ),
            None,
        )
        if current is not None and current.revision_id == applied_id:
            return state.model_copy(update={"revision_id": applied_id})
        applied = state.model_copy(update={"revision_id": applied_id})
        dependencies = (
            DependencyInput(
                **proposed.model_dump(),
                role="dependency:proposed-assessment",
            ),
        )
        self.ledger.commit(
            Transition(
                scope=self.review_case.review_id,
                operation="correction:targeted-rework-applied",
                operation_key=f"{command.operation_key}:applied",
                actor=command.actor,
                observed_at=command.observed_at,
                entity_id=entity_id,
                revision_id=applied_id,
                artifact=applied.model_dump_json().encode(),
                artifact_media_type="application/json",
                dependencies=dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(dependencies),
                checkpoint=command.last_checkpoint,
                outcome=WorkflowEventOutcome.COMPLETED,
                causation_id=receipt.ledger_event_id,
                correlation_id=receipt.revision_id,
                supersedes_revision_id=(
                    current.revision_id if current is not None else None
                ),
            ),
            self.lease,
            now=command.observed_at,
        )
        return applied

    def _adopt_proposed_assessment(
        self,
        proposed: RecordReference,
        projected_case: ReviewCase | None,
    ) -> None:
        if projected_case is None:
            raise ValueError("successful rework requires its refreshed Review projection")
        self.review_case = projected_case

    def _validate_superseding_review_case(
        self,
        projected: ReviewCase | None,
        proposed: RecordReference,
        superseding: AssessmentRevision,
        correction: CorrectionRequest,
        corrected_sq_id: Identifier | None,
    ) -> None:
        if projected is None or projected.assessment != proposed:
            raise ValueError("refreshed Review projection must bind the proposed Assessment")
        for field in (
            "review_id",
            "review_revision",
            "policy",
            "result_label",
            "domain_ids",
            "preparation_scopes",
        ):
            if getattr(projected, field) != getattr(self.review_case, field):
                raise ValueError(f"refreshed Review projection changes immutable {field}")
        affected = set(correction.affected_scope)
        old_summaries = {
            summary.domain_id: summary for summary in self.review_case.domain_summaries
        }
        new_summaries = {
            summary.domain_id: summary for summary in projected.domain_summaries
        }
        for domain_id in set(self.review_case.domain_ids) - affected:
            if old_summaries.get(domain_id) != new_summaries.get(domain_id):
                raise ValueError("refreshed Review projection changes an unaffected Domain")
        old_actions = {
            action.action_id: action for action in self.review_case.actions
        }
        new_actions = {action.action_id: action for action in projected.actions}
        for action_id, old_action in old_actions.items():
            if old_action.domain_id not in affected:
                if new_actions.get(action_id) != old_action:
                    raise ValueError(
                        "refreshed Review projection changes an unaffected action"
                    )
        if any(
            action_id not in old_actions and action.domain_id not in affected
            for action_id, action in new_actions.items()
        ):
            raise ValueError("refreshed Review projection adds an unaffected action")
        answer_references = set(superseding.answers)
        evidence_changed = (
            set(
                (reference.entity_id, reference.revision_id)
                for reference in AssessmentRevision.model_validate_json(
                    self.ledger.artifacts.read(
                        correction.challenged_assessment.content_hash
                    )
                ).evidence_bundles
            )
            != set(
                (reference.entity_id, reference.revision_id)
                for reference in superseding.evidence_bundles
            )
        )
        current_claims = {
            item["entity_id"]: RecordReference.model_validate(item)
            for bundle in superseding.evidence_bundles
            for item in json.loads(
                self.ledger.artifacts.read(bundle.content_hash)
            ).get("items", ())
            if isinstance(item, dict)
            and isinstance(item.get("entity_id"), str)
            and {"revision_id", "content_hash"} <= item.keys()
        }
        answer_payloads: dict[str, dict] = {}
        for reference in superseding.answers:
            payload = json.loads(self.ledger.artifacts.read(reference.content_hash))
            if isinstance(payload, dict) and isinstance(payload.get("sq_id"), str):
                answer_payloads[payload["sq_id"]] = payload
            if isinstance(payload, dict):
                answer_payloads.update(
                    {
                        item["question_id"]: item
                        for item in payload.get("answers", ())
                        if isinstance(item, dict)
                        and isinstance(item.get("question_id"), str)
                    }
                )
        judgment_payloads = {
            payload["domain_id"]: payload
            for reference in superseding.judgments
            if isinstance(
                payload := json.loads(
                    self.ledger.artifacts.read(reference.content_hash)
                ),
                dict,
            )
            and isinstance(payload.get("domain_id"), str)
        }
        for action in projected.actions:
            if (
                action.domain_id in affected
                and action.prepared_answer is not None
                and action.prepared_answer.revision not in answer_references
            ):
                raise ValueError(
                    "refreshed Review projection retains a stale prepared answer"
                )
            if (
                action.domain_id in affected
                and action.answer_revision is not None
                and action.answer_revision not in answer_references
            ):
                raise ValueError(
                    "refreshed Review projection retains a stale answer binding"
                )
            if (
                evidence_changed
                and action.domain_id in affected
                and action.evidence_claim is not None
            ):
                current_claim = current_claims.get(action.evidence_claim.entity_id)
                if current_claim != action.evidence_claim:
                    raise ValueError(
                        "refreshed Review projection retains stale Evidence"
                    )
                claim_payload = json.loads(
                    self.ledger.artifacts.read(current_claim.content_hash)
                )
                quoted = claim_payload.get("quoted_text")
                if (
                    quoted is not None
                    and action.bound_evidence is not None
                    and action.bound_evidence.quote() != quoted
                ):
                    raise ValueError(
                        "refreshed Review projection retains stale exact Evidence text"
                    )
        for summary in projected.domain_summaries:
            if summary.domain_id not in affected:
                continue
            current_judgment = judgment_payloads.get(summary.domain_id)
            if current_judgment is not None:
                expected_judgment = str(
                    current_judgment.get("judgment", "")
                ).replace("_", " ").casefold()
                if summary.judgment.casefold() != expected_judgment:
                    raise ValueError(
                        "refreshed Review projection retains a stale Domain judgment"
                    )
                previous_summary = old_summaries.get(summary.domain_id)
                if (
                    previous_summary is not None
                    and previous_summary.judgment != summary.judgment
                    and previous_summary.deterministic_basis
                    == summary.deterministic_basis
                ):
                    raise ValueError(
                        "refreshed Review projection retains a stale judgment basis"
                    )
            for question in summary.active_questions:
                current_answer = answer_payloads.get(question.sq_id)
                if current_answer is None:
                    raise ValueError(
                        "refreshed Review projection lacks current SQ decision content"
                    )
                expected = str(current_answer.get("answer", "")).replace("_", " ").casefold()
                if (
                    question.answer.casefold() != expected
                    or question.rationale != current_answer.get("rationale")
                ):
                    raise ValueError(
                        "refreshed Review projection retains stale SQ decision content"
                    )
        available_questions = {
            question.sq_id
            for summary in projected.domain_summaries
            if summary.domain_id in affected
            for question in summary.active_questions
        }
        if available_questions and corrected_sq_id not in available_questions:
            raise ValueError("corrected SQ is absent from the refreshed Review projection")

    def mark_disconnected(self) -> None:
        if self._connection_state is not ConnectionState.COMPLETE:
            self._connection_state = ConnectionState.NOT_CONNECTED
            self._last_contact = datetime.now(UTC)

    def mark_reconnect_needed(self) -> None:
        if self._connection_state is not ConnectionState.COMPLETE:
            self._connection_state = ConnectionState.RECONNECT_NEEDED
            self._last_contact = datetime.now(UTC)

    def _receipts_by_action(self) -> dict[str, DurableReviewReceipt]:
        receipts = {}
        for event in self.ledger.events():
            if (
                event.scope != self.review_case.review_id
                or not event.operation.startswith("review:")
                or event.operation.startswith("review:canonical-")
            ):
                continue
            receipt = self._receipt_from_event(event)
            if receipt.assessment_revision_id != self.review_case.assessment_revision_id:
                state = (
                    self.correction_state(receipt.revision_id)
                    if receipt.correction_request is not None
                    else None
                )
                if state is not None and state.status is CorrectionReworkStatus.SUCCEEDED:
                    continue
                action = next(
                    (
                        candidate
                        for candidate in self.review_case.actions
                        if candidate.action_id == receipt.review_action_id
                    ),
                    None,
                )
                reopened = {
                    decision
                    for correction in self.correction_receipts()
                    if (
                        rework := self.correction_state(correction.revision_id)
                    ) is not None
                    and rework.status is CorrectionReworkStatus.SUCCEEDED
                    and rework.comparison is not None
                    for decision in rework.comparison.reopened_decisions
                }
                if action is None or action.domain_id in reopened:
                    continue
            receipts[receipt.review_action_id] = receipt
        return receipts

    def _receipt_for_operation(self, operation_key: str) -> DurableReviewReceipt | None:
        for event in self.ledger.events():
            if event.operation_key == operation_key:
                return self._receipt_from_event(event)
        return None

    def _sign_off_eligible(self, receipts: dict[str, DurableReviewReceipt]) -> bool:
        satisfactory = {
            action_id
            for action_id, receipt in receipts.items()
            if receipt.outcome is ReviewReceiptOutcome.ACTION_COMPLETED
        }
        required_findings = {
            action.action_id
            for action in self.review_case.actions
            if action.finding_requirement in self.review_case.policy.required_finding_requirements
        }
        reviewed_domains = {
            action.domain_id
            for action in self.review_case.actions
            if action.kind is ActionKind.DOMAIN_REVIEW and action.action_id in satisfactory
        }
        reviewed_domains.update(
            _domain_id_from_action(action_id)
            for action_id in satisfactory
            if action_id.startswith("review-action:domain-")
        )
        return (
            required_findings <= satisfactory
            and set(self.review_case.policy.domain_ids) <= reviewed_domains
        )

    def _receipt_outcome(self, command: ReviewCommand) -> ReviewReceiptOutcome:
        if command.kind is ActionKind.SIGN_OFF:
            return ReviewReceiptOutcome.ASSESSMENT_SIGNED_OFF
        if command.value is ActionDecision.CORRECTION_REQUESTED:
            return ReviewReceiptOutcome.CORRECTION_REQUESTED
        if command.value is ActionDecision.DEFERRED:
            return ReviewReceiptOutcome.DEFERRED
        return ReviewReceiptOutcome.ACTION_COMPLETED

    def _attention(
        self,
        action: ReviewAction,
        receipt: DurableReviewReceipt | None,
        summary: DomainReviewSummary | None,
        *,
        stale: bool,
        blocked_by_correction: bool = False,
    ) -> tuple[AttentionTier, tuple[str, ...]]:
        action_required: list[str] = []
        inspect_carefully: list[str] = []
        if stale:
            action_required.append(
                "A newer Assessment revision makes this review read-only."
            )
        if receipt is not None and receipt.outcome is ReviewReceiptOutcome.CORRECTION_REQUESTED:
            action_required.append(
                "A requested correction is waiting for targeted agent rework."
            )
        elif blocked_by_correction:
            action_required.append(
                "This affected Domain is read-only pending targeted agent rework."
            )
        if action.kind is ActionKind.BLOCKING_REPAIR and receipt is None:
            action_required.append(
                "Result or source identity must be resolved before sign-off."
            )
        if action.kind is ActionKind.VERIFY_EVIDENCE and receipt is None:
            action_required.append(
                "Required evidence or visual material must be verified."
            )
        if (
            action.kind is ActionKind.ACKNOWLEDGE_LIMITATION
            and action.finding_requirement is FindingRequirement.ACKNOWLEDGE
            and receipt is None
        ):
            action_required.append(
                "A required coverage limitation must be acknowledged."
            )

        if action.accepted_contradiction:
            inspect_carefully.append(
                "Accepted contradicting evidence requires careful inspection."
            )
        if action.source_conflict:
            inspect_carefully.append(
                "An accepted Source conflict requires careful inspection."
            )
        if action.elevated_visual_transcription:
            inspect_carefully.append(
                "An elevated Visual transcription requires careful inspection."
            )
        if action.no_information:
            inspect_carefully.append(
                "A No information answer requires its search basis to be inspected."
            )
        if action.influential_project_rule:
            inspect_carefully.append(
                "A materially influential Project rule requires careful inspection."
            )
        if action.judgment_override:
            inspect_carefully.append(
                "A Judgment override requires careful inspection."
            )
        if summary is not None:
            if summary.judgment.casefold() in {"some concerns", "high", "high risk"}:
                inspect_carefully.append(f"The Domain judgment is {summary.judgment}.")
            if (
                summary.coverage.casefold() not in {"complete", "adequate"}
                and summary.coverage_acknowledged
            ):
                inspect_carefully.append(
                    "An acknowledged coverage limitation remains material to sign-off."
                )
        reasons = (*action_required, *inspect_carefully)
        if action_required:
            return AttentionTier.ACTION_REQUIRED, reasons
        if inspect_carefully:
            return AttentionTier.INSPECT_CAREFULLY, reasons
        return AttentionTier.ROUTINE_REVIEW, ("No higher-tier Review policy condition applies.",)

    def _affected_context(self, action: ReviewAction) -> str:
        parts = [self.review_case.result_label]
        if action.domain_id is not None:
            parts.append(action.domain_id.replace("domain:", "Domain "))
        if action.sq_id is not None:
            parts.append(action.sq_id.replace("sq:", "SQ "))
        return " · ".join(parts)

    def _default_consequence(self, action: ReviewAction) -> str:
        if action.kind is ActionKind.SIGN_OFF:
            return "This commits sign-off for only this exact Result Assessment revision."
        if action.kind is ActionKind.DOMAIN_REVIEW:
            return "This Domain must be confirmed before Result sign-off is available."
        return "This item must be completed before Result sign-off is available."

    def _default_next_action(self, action: ReviewAction) -> str:
        return {
            ActionKind.BLOCKING_REPAIR: "Resolve the Result or source identity.",
            ActionKind.VERIFY_EVIDENCE: "Open the bound evidence and record a decision.",
            ActionKind.ACKNOWLEDGE_LIMITATION: "Review and acknowledge the limitation.",
            ActionKind.INSPECT_FINDING: "Inspect the preserved finding in Full evidence audit.",
            ActionKind.DOMAIN_REVIEW: "Open this Domain and confirm it individually.",
            ActionKind.SIGN_OFF: "Review the Result summary and sign this revision.",
        }[action.kind]

    def _workflow_outcome(self, command: ReviewCommand) -> WorkflowEventOutcome:
        if command.value is ActionDecision.CORRECTION_REQUESTED:
            return WorkflowEventOutcome.WORK_REQUIRED
        if command.value is ActionDecision.DEFERRED:
            return WorkflowEventOutcome.REVIEW_PENDING
        return WorkflowEventOutcome.COMPLETED

    def _correction_request(
        self,
        command: ReviewCommand,
        action: QueueItem,
        receipt_id: Identifier,
    ) -> CorrectionRequest:
        source_action = next(
            (
                candidate
                for candidate in self.review_case.actions
                if candidate.action_id == action.action_id
            ),
            None,
        )
        domain_summary = next(
            (
                summary
                for summary in self.review_case.domain_summaries
                if summary.domain_id == action.domain_id
            ),
            None,
        )
        prior_correction = next(reversed(self.correction_receipts()), None)
        minimum_scope = _minimum_correction_scope(action)
        requested_scope = command.correction_scope or minimum_scope
        if _scope_rank(requested_scope) < _scope_rank(minimum_scope):
            raise ValueError(
                f"correction scope cannot narrow the invocation context below {minimum_scope.value}"
            )
        affected = self._dependency_affected_scope(action, requested_scope)
        request_text = (command.rationale or "").strip()
        prompt = (
            "Targeted rob2-kit correction request\n"
            f"Receipt: {receipt_id}\n"
            f"Challenged Assessment: {self.review_case.assessment.revision_id}\n"
            f"Result: {self.review_case.result_label}\n"
            f"Starting scope: {requested_scope.value}\n"
            f"Required affected path: {', '.join(affected) or self.review_case.result_label}\n"
            f"Request: {request_text}\n"
            "Preserve the challenged Assessment unchanged. Regenerate only the recorded "
            "dependency path and create one superseding Assessment revision. Report progress "
            "and completion with submit_targeted_rework using this receipt revision."
        )
        return CorrectionRequest(
            challenged_assessment=self.review_case.assessment,
            result_label=self.review_case.result_label,
            domain_id=action.domain_id,
            sq_id=action.sq_id,
            evidence_claim=action.evidence_claim,
            exact_text=action.evidence_text,
            highlighted_region=(
                (
                    source_action.bound_evidence.span_start,
                    source_action.bound_evidence.span_end,
                )
                if source_action is not None and source_action.bound_evidence is not None
                else None
            ),
            prepared_answer=(
                source_action.prepared_answer.answer
                if source_action is not None and source_action.prepared_answer is not None
                else (domain_summary.judgment if domain_summary is not None else None)
            ),
            prepared_rationale=(
                source_action.prepared_answer.rationale
                if source_action is not None and source_action.prepared_answer is not None
                else (
                    domain_summary.deterministic_basis
                    if domain_summary is not None
                    else None
                )
            ),
            request=request_text,
            minimum_scope=minimum_scope,
            requested_scope=requested_scope,
            affected_scope=affected,
            agent_prompt=prompt,
            last_checkpoint=action.correction_checkpoint,
            resume_action=prompt,
            predecessor_receipt_revision_id=(
                prior_correction.revision_id if prior_correction is not None else None
            ),
        )

    def _dependency_affected_scope(
        self,
        action: QueueItem,
        requested_scope: CorrectionScope,
    ) -> tuple[Identifier, ...]:
        if requested_scope is CorrectionScope.RESULT:
            return self.review_case.domain_ids
        if requested_scope is CorrectionScope.DOMAIN:
            return tuple(
                dict.fromkeys(
                    (
                        *((action.domain_id,) if action.domain_id is not None else ()),
                        *action.affected_scope,
                    )
                )
            )
        seed_revisions = {
            reference.revision_id
            for reference in (
                action.evidence_claim,
                action.evidence_bundle,
                action.answer_revision,
            )
            if reference is not None
        }
        affected_revisions = set(seed_revisions)
        changed = True
        events = self.ledger.events()
        while changed:
            changed = False
            for event in events:
                if event.revision_id in affected_revisions:
                    continue
                if any(
                    dependency.revision_id in affected_revisions
                    for dependency in event.dependencies
                ):
                    affected_revisions.add(event.revision_id)
                    changed = True
        domains = []
        for candidate in self.review_case.actions:
            if candidate.domain_id is None:
                continue
            candidate_revisions = {
                reference.revision_id
                for reference in (
                    candidate.evidence_claim,
                    candidate.evidence_bundle,
                    candidate.answer_revision,
                    (
                        candidate.prepared_answer.revision
                        if candidate.prepared_answer is not None
                        else None
                    ),
                )
                if reference is not None
            }
            if (
                candidate.action_id == action.action_id
                or candidate.sq_id == action.sq_id
                or candidate_revisions & affected_revisions
            ):
                domains.append(candidate.domain_id)
        return tuple(
            dict.fromkeys(
                (
                    *((action.domain_id,) if action.domain_id is not None else ()),
                    *domains,
                    *action.affected_scope,
                )
            )
        )

    def _receipt_from_event(self, event: WorkflowEvent) -> DurableReviewReceipt:
        payload = json.loads(self.ledger.artifacts.read(event.output_revision_hashes[0]))
        payload["ledger_event_id"] = event.event_id
        return DurableReviewReceipt.model_validate(payload)

    def _receipt_revision_id(self, command: ReviewCommand) -> str:
        digest = hashlib.sha256(
            (
                f"{self.review_case.review_id}|{self.review_case.assessment_revision_id}|"
                f"{command.action_id}|{command.idempotency_key}"
            ).encode()
        ).hexdigest()[:24]
        return f"revision:review-receipt-{digest}"

    def _rework_revision_id(self, command: CorrectionReworkCommand) -> str:
        digest = hashlib.sha256(
            (
                f"{command.correction_receipt_revision_id}|{command.operation_key}|"
                f"{command.status}"
            ).encode()
        ).hexdigest()[:24]
        return f"revision:correction-rework-{digest}"

    def _validate_preparation_outcomes(self) -> None:
        completed_scopes = {
            event.scope
            for event in self.ledger.events()
            if event.outcome is WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED
        }
        missing = set(self.review_case.preparation_scopes) - completed_scopes
        if missing:
            raise ValueError("review cannot open until every Trial has a Preparation outcome")

    def _restore_current_proposed_assessment(self) -> None:
        for event in reversed(self.ledger.events()):
            if (
                event.operation != "correction:targeted-rework"
                or event.scope != self.review_case.review_id
            ):
                continue
            state = CorrectionReworkState.model_validate_json(
                self.ledger.artifacts.read(event.output_revision_hashes[0])
            )
            if (
                state.status is CorrectionReworkStatus.SUCCEEDED
                and state.current_proposed_assessment is not None
                and state.challenged_assessment.entity_id
                == self.review_case.assessment.entity_id
            ):
                proposed = state.current_proposed_assessment
                current = next(
                    (
                        revision
                        for revision in self.ledger.current_revisions()
                        if revision.entity_id == proposed.entity_id
                    ),
                    None,
                )
                if current is None or current.revision_id != proposed.revision_id:
                    continue
                self._adopt_proposed_assessment(
                    proposed,
                    state.current_review_case,
                )
                return


def _domain_action_id(domain_id: str) -> str:
    return f"review-action:domain-{domain_id.removeprefix('domain:')}"


def _domain_id_from_action(action_id: str) -> str:
    return f"domain:{action_id.removeprefix('review-action:domain-')}"


def _domain_order(domain_id: str | None) -> int:
    if domain_id is None:
        return 0
    suffix = domain_id.rsplit(":", 1)[-1].removeprefix("D")
    return int(suffix) if suffix.isdigit() else 99


def _minimum_correction_scope(action: QueueItem) -> CorrectionScope:
    if action.evidence_claim is not None:
        return CorrectionScope.EVIDENCE
    if action.sq_id is not None:
        return CorrectionScope.SIGNALING_QUESTION
    if action.domain_id is not None:
        return CorrectionScope.DOMAIN
    return CorrectionScope.RESULT


def _scope_rank(scope: CorrectionScope) -> int:
    return tuple(CorrectionScope).index(scope)


def _derive_correction_comparison(
    challenged: AssessmentRevision,
    superseding: AssessmentRevision,
    affected_scope: tuple[Identifier, ...],
    requested_scope: CorrectionScope,
    all_domains: tuple[Identifier, ...],
    ledger: WorkflowLedger,
) -> CorrectionComparison:
    def payload(reference: RecordReference) -> dict:
        loaded = json.loads(ledger.artifacts.read(reference.content_hash))
        return loaded if isinstance(loaded, dict) else {"value": loaded}

    def pairs(
        before: tuple[RecordReference, ...],
        after: tuple[RecordReference, ...],
    ) -> tuple[tuple[dict, dict], ...]:
        old = {reference.entity_id: payload(reference) for reference in before}
        new = {reference.entity_id: payload(reference) for reference in after}
        return tuple(
            (old.get(entity_id, {}), new.get(entity_id, {}))
            for entity_id in sorted(old.keys() | new.keys())
            if old.get(entity_id) != new.get(entity_id)
        )

    evidence_pairs = pairs(
        challenged.evidence_bundles,
        superseding.evidence_bundles,
    )
    answer_pairs = pairs(challenged.answers, superseding.answers)
    judgment_pairs = pairs(challenged.judgments, superseding.judgments)
    finding_pairs = pairs(
        challenged.review_findings,
        superseding.review_findings,
    )
    override_pairs = pairs(
        challenged.judgment_overrides,
        superseding.judgment_overrides,
    )
    identity_changed = (
        challenged.result_spec != superseding.result_spec
        or challenged.source_inventory != superseding.source_inventory
    )
    if identity_changed and requested_scope is not CorrectionScope.RESULT:
        raise ValueError("targeted correction changes Result identity outside its scope")
    if not any((evidence_pairs, answer_pairs, judgment_pairs, finding_pairs)):
        if not override_pairs and not identity_changed:
            raise ValueError(
                "successful correction must change an Assessment decision dependency"
            )
    evidence = tuple(
        _payload_difference(
            "Evidence consideration",
            before,
            after,
            ("items", "coverage_state", "coverage_limitations", "conflicts"),
        )
        for before, after in evidence_pairs
    ) or ("Evidence consideration: no substantive change.",)
    answers = tuple(
        _answer_difference(before, after) for before, after in answer_pairs
    ) or ("Answer and rationale: no substantive change.",)
    judgments = tuple(
        _payload_difference("Judgment", before, after, ("domain_id", "judgment"))
        for before, after in judgment_pairs
    ) or ("Judgments: no substantive change.",)
    limitations = tuple(
        _payload_difference(
            "Limitation",
            before,
            after,
            ("summary", "severity", "finding_type", "affected_records"),
        )
        for before, after in finding_pairs
    )
    if not limitations:
        limitations = tuple(
            _payload_difference(
                "Limitations",
                before,
                after,
                ("coverage_state", "coverage_limitations"),
            )
            for before, after in evidence_pairs
        ) or ("Limitations: no substantive change.",)
    changed_domains = {
        domain_id
        for before, after in (
            *evidence_pairs,
            *answer_pairs,
            *judgment_pairs,
            *finding_pairs,
            *override_pairs,
        )
        for domain_id in (
            _payload_domains(before, ledger) | _payload_domains(after, ledger)
        )
    }
    if evidence_pairs:
        evidence_domains = _evidence_change_domains(
            evidence_pairs,
            (*pairs(challenged.answers, ()), *pairs((), superseding.answers)),
            ledger,
        )
        changed_domains.update(evidence_domains or set(all_domains))
    if changed_domains and not changed_domains <= set(affected_scope):
        raise ValueError("superseding Assessment changes an unaffected Domain")
    reopened = tuple(
        domain_id
        for domain_id in affected_scope
        if not changed_domains or domain_id in changed_domains
    )
    reusable = []
    def revisions(references: tuple[RecordReference, ...]) -> tuple[Identifier, ...]:
        return tuple(reference.revision_id for reference in references)

    for label, before, after in (
        ("ResultSpec", (challenged.result_spec,), (superseding.result_spec,)),
        ("Source inventory", (challenged.source_inventory,), (superseding.source_inventory,)),
        ("Evidence Bundles", challenged.evidence_bundles, superseding.evidence_bundles),
        ("SQ Answers", challenged.answers, superseding.answers),
        ("Judgments", challenged.judgments, superseding.judgments),
        (
            "Judgment overrides",
            challenged.judgment_overrides,
            superseding.judgment_overrides,
        ),
        ("Review findings", challenged.review_findings, superseding.review_findings),
    ):
        if revisions(before) == revisions(after):
            reusable.append(label)
    return CorrectionComparison(
        evidence_consideration=evidence,
        answer_and_rationale=answers,
        judgments=judgments,
        limitations=limitations,
        reopened_decisions=reopened,
        reused_unaffected_work=tuple(reusable) or ("No unaffected Assessment work.",),
    )


def _payload_difference(
    label: str,
    before: dict,
    after: dict,
    keys: tuple[str, ...],
) -> str:
    changes = [
        f"{key}: {before.get(key)!r} → {after.get(key)!r}"
        for key in keys
        if before.get(key) != after.get(key)
    ]
    if not changes:
        changes = [f"record: {before!r} → {after!r}"]
    return f"{label}: {'; '.join(changes)}."


def _answer_difference(before: dict, after: dict) -> str:
    old_answers = {
        item.get("question_id"): item
        for item in before.get("answers", ())
        if isinstance(item, dict)
    }
    new_answers = {
        item.get("question_id"): item
        for item in after.get("answers", ())
        if isinstance(item, dict)
    }
    changes = []
    for sq_id in sorted(old_answers.keys() | new_answers.keys(), key=str):
        old = old_answers.get(sq_id, {})
        new = new_answers.get(sq_id, {})
        if old != new:
            changes.append(
                f"{sq_id}: answer {old.get('answer')!r} → {new.get('answer')!r}; "
                f"rationale {old.get('rationale')!r} → {new.get('rationale')!r}"
            )
    return (
        f"Answer and rationale: {'; '.join(changes)}."
        if changes
        else _payload_difference("Answer and rationale", before, after, ("answers",))
    )


def _payload_domains(
    payload: dict,
    ledger: WorkflowLedger,
    visited_hashes: set[str] | None = None,
) -> set[Identifier]:
    visited = visited_hashes or set()
    domains: set[Identifier] = set()
    for key, value in payload.items():
        if key == "domain_id" and isinstance(value, str) and value.startswith("domain:"):
            domains.add(value)
        if key in {"sq_id", "question_id"} and isinstance(value, str) and value.startswith(
            "sq:"
        ):
            domains.add(f"domain:{value.split(':', 2)[1]}")
        if isinstance(value, dict):
            domains.update(_payload_domains(value, ledger, visited))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    domains.update(_payload_domains(item, ledger, visited))
        if (
            isinstance(value, dict)
            and isinstance(value.get("content_hash"), str)
            and value["content_hash"] not in visited
        ):
            visited.add(value["content_hash"])
            try:
                referenced = json.loads(ledger.artifacts.read(value["content_hash"]))
            except (ArtifactNotFoundError, ValueError):
                continue
            if isinstance(referenced, dict):
                domains.update(_payload_domains(referenced, ledger, visited))
    return domains


def _evidence_change_domains(
    evidence_pairs: tuple[tuple[dict, dict], ...],
    answer_pairs: tuple[tuple[dict, dict], ...],
    ledger: WorkflowLedger,
) -> set[Identifier]:
    changed_claims: set[str] = set()
    for before, after in evidence_pairs:
        old_items = {
            json.dumps(item, sort_keys=True)
            for item in before.get("items", ())
            if isinstance(item, dict)
        }
        new_items = {
            json.dumps(item, sort_keys=True)
            for item in after.get("items", ())
            if isinstance(item, dict)
        }
        for serialized in old_items ^ new_items:
            item = json.loads(serialized)
            entity_id = item.get("entity_id")
            if isinstance(entity_id, str):
                changed_claims.add(entity_id)
    domains: set[Identifier] = set()
    for before, after in answer_pairs:
        for payload in (before, after):
            answers = (
                payload.get("answers", ())
                if "answers" in payload
                else (payload,)
            )
            for answer in answers:
                if not isinstance(answer, dict):
                    continue
                sq_id = answer.get("question_id") or answer.get("sq_id")
                claims = set(answer.get("evidence_claim_ids", ()))
                evidence_bundle = answer.get("evidence_bundle")
                if isinstance(evidence_bundle, dict):
                    claims.update(
                        _bundle_claim_ids(evidence_bundle, ledger)
                    )
                if (
                    isinstance(sq_id, str)
                    and sq_id.startswith("sq:")
                    and changed_claims & claims
                ):
                    domains.add(f"domain:{sq_id.split(':', 2)[1]}")
    return domains


def _bundle_claim_ids(reference: dict, ledger: WorkflowLedger) -> set[str]:
    content_hash = reference.get("content_hash")
    if not isinstance(content_hash, str):
        return set()
    try:
        payload = json.loads(ledger.artifacts.read(content_hash))
    except (ArtifactNotFoundError, ValueError):
        return set()
    return {
        item["entity_id"]
        for item in payload.get("items", ())
        if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
    }
