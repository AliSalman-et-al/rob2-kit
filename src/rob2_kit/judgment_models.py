"""Strict immutable payloads for one scientific Domain checkpoint."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from rob2_kit.batch import PackIdentity
from rob2_kit.models import Answer, Judgment, StrictModel

NonBlankStr = Annotated[str, Field(min_length=1)]


class _NonBlank(StrictModel):
    @field_validator("*", mode="before")
    @classmethod
    def nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
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


class ActiveAnswer(_NonBlank):
    question_id: NonBlankStr
    answer: Answer
    rationale: NonBlankStr
    evidence_uses: tuple[EvidenceUse, ...] = Field(min_length=1)


class InactiveQuestion(_NonBlank):
    question_id: NonBlankStr
    status: Literal["inactive"] = "inactive"


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
