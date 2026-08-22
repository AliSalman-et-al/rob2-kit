"""Closed transport contracts shared by the CLI and MCP adapters.

These models deliberately contain no FastMCP types. References are locators,
not capabilities: resolving one always performs an independent integrity and
authority check.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperationOutcome(StrEnum):
    SUCCESS = "success"
    REPAIR = "repair"
    CONDITION = "condition"
    CONFLICT = "conflict"


class WorkflowPhase(StrEnum):
    EMPTY = "empty"
    INTAKE = "intake"
    PROPOSAL = "proposal"
    ASSESSMENT = "assessment"
    READY_TO_FINALIZE = "ready_to_finalize"
    FINALIZED = "finalized"


class TrialDisposition(StrEnum):
    PENDING = "pending"
    ASSESSED = "assessed"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


class ReviewAuthority(StrEnum):
    NONE = "none"
    HOST = "host"
    RESEARCHER = "researcher"


class RecordKind(StrEnum):
    SOURCE_PREFLIGHT = "source_preflight"
    INTAKE_PLAN = "intake_plan"
    CAPTURED_BATCH = "captured_batch"
    PROPOSAL_REVIEW = "proposal_review"
    APPROVED_BATCH = "approved_batch"
    APPROVED_WORK_PACKET = "work_packet"
    DOMAIN_CANDIDATE = "domain_candidate"
    DOMAIN_OBSERVATION = "domain_checkpoint"
    SYNTHESIS = "trial_synthesis"
    ASSESSMENT_SNAPSHOT = "assessment_snapshot"
    TRIAL_OUTCOME = "trial_terminal"
    FINALIZATION = "batch_summary"
    ARTIFACT_MANIFEST = "artifact_manifest"
    REVIEW_ACK = "review_ack"
    DIAGNOSTIC = "diagnostic"


class RecordReference(_Closed):
    kind: RecordKind
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    uri: str = Field(pattern=r"^rob2://detail/[a-z_]+/sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def uri_matches_identity(self) -> RecordReference:
        if self.uri != f"rob2://detail/{self.kind.value}/{self.identity}":
            raise ValueError("record reference URI does not match kind and identity")
        return self


class ReviewAcknowledgmentReference(_Closed):
    kind: Literal["review_ack"]
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    uri: str = Field(pattern=r"^rob2://detail/review_ack/sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def uri_matches_identity(self) -> ReviewAcknowledgmentReference:
        if self.uri != f"rob2://detail/review_ack/{self.identity}":
            raise ValueError("review acknowledgment URI does not match identity")
        return self


class TransitionReference(_Closed):
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RenderReference(_Closed):
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    uri: str = Field(pattern=r"^rob2://render/sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def uri_matches_identity(self) -> RenderReference:
        if self.uri != f"rob2://render/{self.identity}":
            raise ValueError("render reference URI does not match identity")
        return self


class EvidenceReference(_Closed):
    kind: Literal["evidence"]
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReviewAuthorityRequirement(_Closed):
    required: ReviewAuthority
    satisfied: bool = False
    acknowledgment: ReviewAcknowledgmentReference | None = None


class PreflightSourcesContinuation(_Closed):
    operation: Literal["preflight_sources"] = "preflight_sources"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    expected_head: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class SaveIntakePlanContinuation(_Closed):
    operation: Literal["save_intake_plan"] = "save_intake_plan"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    preflight: RecordReference
    entries: None = None


class CaptureBatchContinuation(_Closed):
    operation: Literal["capture_batch"] = "capture_batch"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    plan: RecordReference
    acknowledgment: ReviewAcknowledgmentReference


class SaveProposalContinuation(_Closed):
    operation: Literal["save_proposal"] = "save_proposal"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    captured_batch: RecordReference


class ResearcherReviewContinuation(_Closed):
    operation: Literal["researcher_review"] = "researcher_review"
    authority: Literal[ReviewAuthority.RESEARCHER] = ReviewAuthority.RESEARCHER
    record: RecordReference
    purpose: Literal["intake", "proposal", "trial_finish"]
    unlocks: Literal["capture_batch", "approve_batch", "finish_trial"]


class ApproveBatchContinuation(_Closed):
    operation: Literal["approve_batch"] = "approve_batch"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    review: RecordReference
    transition: TransitionReference
    acknowledgment: ReviewAcknowledgmentReference


class ValidateDomainJudgmentContinuation(_Closed):
    operation: Literal["validate_domain_judgment"] = "validate_domain_judgment"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    packet: RecordReference
    draft: None = None


class PrepareTrialFinishContinuation(_Closed):
    operation: Literal["prepare_trial_finish"] = "prepare_trial_finish"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    packet: RecordReference
    disposition: None = None
    rationale: None = None


class FinishTrialContinuation(_Closed):
    operation: Literal["finish_trial"] = "finish_trial"
    authority: Literal[ReviewAuthority.RESEARCHER] = ReviewAuthority.RESEARCHER
    transition: TransitionReference
    acknowledgment: ReviewAcknowledgmentReference


class FinalizeBatchContinuation(_Closed):
    operation: Literal["finalize_batch"] = "finalize_batch"
    authority: Literal[ReviewAuthority.HOST] = ReviewAuthority.HOST
    approved_batch: RecordReference


Continuation = Annotated[
    PreflightSourcesContinuation
    | SaveIntakePlanContinuation
    | CaptureBatchContinuation
    | SaveProposalContinuation
    | ResearcherReviewContinuation
    | ApproveBatchContinuation
    | ValidateDomainJudgmentContinuation
    | PrepareTrialFinishContinuation
    | FinishTrialContinuation
    | FinalizeBatchContinuation,
    Field(discriminator="operation"),
]


class AuthoritativePresentation(_Closed):
    code: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class VerifiedCondition(_Closed):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class VerifiedCurrentStatus(_Closed):
    phase: WorkflowPhase
    trial_dispositions: tuple[tuple[str, TrialDisposition], ...] = ()
    committed_domains: tuple[tuple[str, tuple[str, ...]], ...] = ()
    conditions: tuple[VerifiedCondition, ...] = ()
    review: ReviewAuthorityRequirement
    continuation: Continuation | None = None
    presentation: AuthoritativePresentation

    @model_serializer(mode="wrap")
    def actionable_wire_format(self, serializer):
        """Never let compact serialization erase an executable union discriminator.

        Callers commonly request ``exclude_defaults=True`` to keep launcher payloads small.
        Pydantic would otherwise remove the default-valued ``operation`` and ``authority``
        fields that distinguish continuation variants, leaving agents to guess the next tool.
        Reinsert those two protocol fields after normal serialization. Once a review has been
        consumed and the Batch is terminal or ready to finalize, expose no actionable review;
        the immutable acknowledgment remains available in its provenance record.
        """

        value = serializer(self)
        if self.continuation is not None:
            continuation = dict(value.get("continuation", {}))
            continuation["operation"] = self.continuation.operation
            continuation["authority"] = self.continuation.authority.value
            value["continuation"] = continuation
        if (
            self.phase in {WorkflowPhase.READY_TO_FINALIZE, WorkflowPhase.FINALIZED}
            and self.review.satisfied
        ):
            value["review"] = {
                "required": ReviewAuthority.NONE.value,
                "satisfied": True,
            }
        return value
