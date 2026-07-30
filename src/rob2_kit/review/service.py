"""Ledger-backed human review queue and command boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.application.preparation import ReviewReceiptOutcome
from rob2_kit.domain.revisions import (
    Actor,
    ActorKind,
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.storage.ledger import (
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
                self.evidence_claim,
                self.evidence_bundle,
                self.answer_revision,
                self.bound_evidence,
                self.prepared_answer,
            )
        ):
            raise ValueError(
                "evidence verification must bind canonical evidence and answer revisions"
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
    source_locator: str | None = None
    answer_visible: bool = False
    staged_answer: str | None = None
    staged_rationale: str | None = None
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

    @model_validator(mode="after")
    def validate_time(self) -> ReviewCommand:
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        return self


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
    assurance: str | None = None


class ReviewCommit(FrozenModel):
    receipt: DurableReviewReceipt
    duplicate: bool


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

    def queue(self) -> tuple[QueueItem, ...]:
        completed = self._receipts_by_action()
        stale = self.is_stale()
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
            actionable = receipt is None and not stale
            if receipt is not None and receipt.outcome is ReviewReceiptOutcome.CORRECTION_REQUESTED:
                actionable = False
            tier, _ = self._attention(
                action, receipt, summaries.get(action.domain_id), stale=stale
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
                action, receipt, summary, stale=stale
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
                    completed=receipt is not None,
                    attention_tier=attention_tier,
                    reasons=reasons,
                    affected_context=self._affected_context(action),
                    actionable=receipt is None and not stale,
                    domain_summary=summary,
                    consequence=action.consequence or self._default_consequence(action),
                    next_action=action.next_action or self._default_next_action(action),
                )
            )
        return tuple(items)

    def commit(self, command: ReviewCommand) -> ReviewCommit:
        if command.actor.kind is not ActorKind.HUMAN:
            raise ValueError("review actions require a human actor")
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
        elif command.kind is ActionKind.DOMAIN_REVIEW and not command.domain_opened:
            raise ReviewError("the individual Domain must be opened before confirmation")

        self._connection_state = ConnectionState.WORKING
        receipt_id = self._receipt_revision_id(command)
        selected_action = actions.get(command.action_id)
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
                entity_id=f"review-receipt:{command.action_id.split(':', 1)[1]}",
                revision_id=receipt_id,
                artifact=json.dumps(payload, ensure_ascii=False).encode(),
                artifact_media_type="application/json",
                dependencies=(),
                expected_dependency_fingerprint=dependency_fingerprint(()),
                checkpoint=f"review-checkpoint:{command.action_id.split(':', 1)[1]}",
                outcome=self._workflow_outcome(command),
            ),
            self.lease,
            now=command.observed_at,
        )
        receipt = DurableReviewReceipt.model_validate(
            {**payload, "ledger_event_id": result.event_id}
        )
        self._connection_state = (
            ConnectionState.COMPLETE
            if command.kind is ActionKind.SIGN_OFF
            else ConnectionState.CONNECTED_WAITING
        )
        self._last_contact = command.observed_at
        return ReviewCommit(receipt=receipt, duplicate=False)

    def connection_state(self) -> ConnectionState:
        return self._connection_state

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
            ):
                return self._receipt_from_event(event)
        return None

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
            ):
                continue
            receipt = self._receipt_from_event(event)
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

    def _validate_preparation_outcomes(self) -> None:
        completed_scopes = {
            event.scope
            for event in self.ledger.events()
            if event.outcome is WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED
        }
        missing = set(self.review_case.preparation_scopes) - completed_scopes
        if missing:
            raise ValueError("review cannot open until every Trial has a Preparation outcome")


def _domain_action_id(domain_id: str) -> str:
    return f"review-action:domain-{domain_id.removeprefix('domain:')}"


def _domain_id_from_action(action_id: str) -> str:
    return f"domain:{action_id.removeprefix('review-action:domain-')}"


def _domain_order(domain_id: str | None) -> int:
    if domain_id is None:
        return 0
    suffix = domain_id.rsplit(":", 1)[-1].removeprefix("D")
    return int(suffix) if suffix.isdigit() else 99
