"""Host-neutral interface envelopes; transports belong to issue #23."""

from enum import StrEnum
from typing import Any

from pydantic import Field, TypeAdapter

from rob2_kit.domain.assessment import SQAnswerCategory
from rob2_kit.domain.results import Estimate, Result
from rob2_kit.domain.revisions import (
    FrozenModel,
    Identifier,
    RecordReference,
    SchemaVersion,
)
from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.workflow import CandidateDisposition


class WorkflowStatus(StrEnum):
    COMPLETED = "completed"
    WORK_REQUIRED = "work_required"
    REVIEW_PENDING = "review_pending"
    PREPARATION_OUTCOME_REACHED = "preparation_outcome_reached"
    RETRYABLE_INTERRUPTION = "retryable_interruption"
    TRIAL_PROBLEM = "trial_problem"
    RUN_INTEGRITY_FAILURE = "run_integrity_failure"


class MutationContext(FrozenModel):
    idempotency_key: str = Field(min_length=1)
    work_item_id: Identifier
    contract_version: SchemaVersion
    expected_dependency_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class OperationEnvelope(FrozenModel):
    operation_id: Identifier
    ledger_cursor: str = Field(min_length=1)
    affected_scope: tuple[Identifier, ...]
    status: WorkflowStatus
    findings: tuple[Identifier, ...] = ()
    committed: bool
    next_permitted_action: Identifier | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SourceClassification(FrozenModel):
    source_id: Identifier
    roles: tuple[SourceRole, ...] = Field(min_length=1)


class SourceClassificationSubmission(FrozenModel):
    classifications: tuple[SourceClassification, ...] = Field(min_length=1)


class ResultResolutionSubmission(FrozenModel):
    result: Result
    estimate: Estimate
    provenance_note: str = Field(min_length=1)


class EvidenceDispositionsSubmission(FrozenModel):
    dispositions: tuple[CandidateDisposition, ...] = Field(min_length=1)
    visual_candidates: tuple[dict[str, Any], ...] = ()


class VisualTranscriptionSubmission(FrozenModel):
    transcription: dict[str, Any]


class EvidenceBundleSubmission(FrozenModel):
    items: tuple[RecordReference, ...] = ()
    frozen_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SQAnswerDraft(FrozenModel):
    question_id: Identifier
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)


class SQAnswersSubmission(FrozenModel):
    answers: tuple[SQAnswerDraft, ...] = Field(min_length=1)
    assessor_inputs: dict[Identifier, bool] = Field(default_factory=dict)


SUBMISSION_ARGUMENTS = {
    "submit_source_classification": TypeAdapter(SourceClassificationSubmission),
    "submit_result_resolution": TypeAdapter(ResultResolutionSubmission),
    "submit_evidence_dispositions": TypeAdapter(EvidenceDispositionsSubmission),
    "submit_visual_transcription": TypeAdapter(VisualTranscriptionSubmission),
    "freeze_evidence_bundle": TypeAdapter(EvidenceBundleSubmission),
    "submit_sq_answers": TypeAdapter(SQAnswersSubmission),
}
