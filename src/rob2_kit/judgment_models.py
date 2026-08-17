"""Strict immutable payloads for one scientific Domain checkpoint."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from rob2_kit.batch import PackIdentity
from rob2_kit.detail import DetailReference
from rob2_kit.models import Answer, Judgment, StrictModel

NonBlankStr = Annotated[str, Field(min_length=1)]


class _NonBlank(StrictModel):
    @field_validator("*", mode="before")
    @classmethod
    def nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("text must not be blank")
        return value


class EvidenceRelationship(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXTUAL = "contextual"


class VisualOrigin(StrEnum):
    RENDERED_PAGE = "rendered_page"
    RENDERED_REGION = "rendered_region"


class TextEvidenceRef(_NonBlank):
    kind: Literal["text"] = "text"
    source_id: NonBlankStr
    source_sha256: NonBlankStr
    page_number: Annotated[int, Field(ge=1)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: NonBlankStr


class VisualEvidenceRef(_NonBlank):
    kind: Literal["visual"] = "visual"
    source_id: NonBlankStr
    source_sha256: NonBlankStr
    page_number: Annotated[int, Field(ge=1)]
    origin: VisualOrigin
    region: tuple[float, float, float, float]
    image_sha256: NonBlankStr
    transcription: NonBlankStr

    @model_validator(mode="after")
    def valid_region(self) -> VisualEvidenceRef:
        if (
            any(not 0 <= item <= 1 for item in self.region)
            or self.region[0] >= self.region[2]
            or self.region[1] >= self.region[3]
        ):
            raise ValueError("region must be a nonempty normalized rectangle")
        if self.origin is VisualOrigin.RENDERED_PAGE and self.region != (0.0, 0.0, 1.0, 1.0):
            raise ValueError("rendered_page must use the full normalized region")
        return self


class EvidenceUse(_NonBlank):
    relationship: EvidenceRelationship
    claim: NonBlankStr
    rationale: NonBlankStr
    refs: tuple[TextEvidenceRef | VisualEvidenceRef, ...] = Field(min_length=1)
    handle_ids: tuple[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")], ...] = ()


class ActiveAnswer(_NonBlank):
    question_id: NonBlankStr
    answer: Answer
    rationale: NonBlankStr
    evidence_uses: tuple[EvidenceUse, ...] = Field(min_length=1)


class InactiveQuestion(_NonBlank):
    question_id: NonBlankStr
    status: Literal["inactive"] = "inactive"


class DomainEvidenceUseDraft(_NonBlank):
    """Evidence use before opaque retrieval handles are resolved."""

    relationship: EvidenceRelationship
    claim: NonBlankStr
    rationale: NonBlankStr
    handle_ids: tuple[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")], ...] = Field(
        min_length=1
    )


class DomainAnswerDraft(_NonBlank):
    question_id: NonBlankStr
    answer: Answer
    rationale: NonBlankStr
    evidence_uses: tuple[DomainEvidenceUseDraft, ...] = Field(min_length=1)


class DomainOverrideDraft(_NonBlank):
    final_judgment: Judgment
    justification: NonBlankStr


class DomainDraft(_NonBlank):
    """Minimal v2 Domain input; identity and inactive questions are derived."""

    active_answers: tuple[DomainAnswerDraft, ...]
    limitations: tuple[NonBlankStr, ...] = ()
    override: DomainOverrideDraft | None = None


class DomainDraftOperation(_NonBlank):
    """Strict operation envelope kept separate from the researcher draft."""

    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    actor: NonBlankStr
    expected_predecessor_hash: NonBlankStr | None = None
    draft: DomainDraft


class DomainDraftRepair(_NonBlank):
    pointer: Annotated[str, Field(pattern=r"^(?:/|/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*)$")]
    subject: NonBlankStr | None = None
    invariant: Literal[
        "question_scope",
        "question_duplicate",
        "question_activation",
        "evidence_required",
        "evidence_handle",
        "evidence_scope",
        "evidence_stale",
        "evidence_integrity",
        "override",
        "draft_shape",
        "draft_schema",
    ]
    actual: Literal[
        "missing",
        "duplicate",
        "unknown",
        "out_of_scope",
        "stale",
        "invalid",
        "mismatch",
        "wrong_type",
        "extra",
    ]
    action: Literal[
        "add_answer",
        "remove_answer",
        "replace_handle",
        "correct_activation",
        "correct_override",
        "retry",
        "correct_field",
        "remove_field",
    ]
    count: Annotated[int, Field(ge=0)] | None = None


class DomainValidationReceipt(_NonBlank):
    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    draft_hash: NonBlankStr
    actor: NonBlankStr
    expected_predecessor_hash: NonBlankStr | None = None
    observed_active_revision: Annotated[int, Field(ge=1)] | None = None
    observed_active_hash: NonBlankStr | None = None
    pack_identities_hash: NonBlankStr
    candidate_hash: NonBlankStr
    observed_at: datetime
    remaining_domains: tuple[NonBlankStr, ...]
    receipt_hash: NonBlankStr

    @field_validator("observed_at")
    @classmethod
    def receipt_time_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value


class DomainDraftRepairOutcome(StrictModel):
    status: Literal["repair"] = "repair"
    draft_hash: NonBlankStr
    repairs: tuple[DomainDraftRepair, ...]


class DomainWorkflowCondition(StrictModel):
    status: Literal["condition"] = "condition"
    draft_hash: NonBlankStr
    code: NonBlankStr
    detail: NonBlankStr


DomainDraftRepairResult: TypeAlias = Annotated[
    DomainDraftRepairOutcome | DomainWorkflowCondition, Field(discriminator="status")
]


class DomainDraftValidated(_NonBlank):
    status: Literal["validated"] = "validated"
    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    draft_hash: NonBlankStr
    candidate_ref: DetailReference
    candidate_hash: NonBlankStr
    proposed_judgment: Judgment
    predecessor_observation: NonBlankStr | None = None
    remaining_domains: tuple[NonBlankStr, ...]
    receipt: DomainValidationReceipt
    next_action: Literal["review_then_commit"] = "review_then_commit"


class DomainDraftCommitOperation(_NonBlank):
    """Exact reviewed-candidate commit envelope; no repair-only fields."""

    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    actor: NonBlankStr
    expected_predecessor_hash: NonBlankStr | None = None
    draft: DomainDraft
    validation_receipt: DomainValidationReceipt
    reviewed_candidate_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class DomainCommitCondition(_NonBlank):
    status: Literal["condition"] = "condition"
    code: NonBlankStr
    detail: NonBlankStr


class DomainCommitConflict(_NonBlank):
    status: Literal["conflict"] = "conflict"
    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    expected_predecessor_hash: NonBlankStr | None
    current_ref: DetailReference | None
    current_active_revision: Annotated[int, Field(ge=1)] | None
    current_active_hash: NonBlankStr | None
    changed_paths: tuple[NonBlankStr, ...]
    next_action: Literal["review_and_revalidate"] = "review_and_revalidate"


class DomainCommitSuccess(_NonBlank):
    status: Literal["committed"] = "committed"
    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    candidate_ref: DetailReference
    active_revision: Annotated[int, Field(ge=1)]
    active_hash: NonBlankStr
    remaining_domains: tuple[NonBlankStr, ...]
    next_packet_ref: DetailReference
    next_action: Literal["answer_active_questions", "review_correction", "finish_trial"]


class Override(_NonBlank):
    justification: NonBlankStr
    actor: NonBlankStr
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value


class DomainJudgment(_NonBlank):
    approved_batch_hash: NonBlankStr
    trial_id: NonBlankStr
    result_id: NonBlankStr
    domain_id: NonBlankStr
    scientific_pack: PackIdentity
    policy_pack: PackIdentity
    active_answers: tuple[ActiveAnswer, ...]
    inactive_questions: tuple[InactiveQuestion, ...]
    proposed_judgment: Judgment
    trace: tuple[NonBlankStr, ...] = Field(min_length=1)
    final_judgment: Judgment
    override: Override | None = None
    limitations: tuple[NonBlankStr, ...] = ()
    actor: NonBlankStr
    observed_at: datetime
    checkpoint_hash: NonBlankStr

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value

    @model_validator(mode="after")
    def coherent(self) -> DomainJudgment:
        active = tuple(item.question_id for item in self.active_answers)
        inactive = tuple(item.question_id for item in self.inactive_questions)
        if len(set(active + inactive)) != len(active) + len(inactive):
            raise ValueError("questions must form a disjoint partition")
        if (self.final_judgment != self.proposed_judgment) != (self.override is not None):
            raise ValueError("override is required exactly when final judgment differs")
        return self
