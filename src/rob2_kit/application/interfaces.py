"""Host-neutral interface envelopes; transports belong to issue #23."""

from enum import StrEnum
from typing import Any

from pydantic import Field, TypeAdapter

from rob2_kit.domain.revisions import FrozenModel, Identifier, SchemaVersion


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


class SourceClassificationSubmission(FrozenModel):
    source_id: Identifier
    roles: tuple[Identifier, ...] = Field(min_length=1)


class ResultResolutionSubmission(FrozenModel):
    result_spec: dict[str, Any]


class EvidenceDispositionsSubmission(FrozenModel):
    dispositions: tuple[dict[str, Any], ...] = Field(min_length=1)


class VisualTranscriptionSubmission(FrozenModel):
    transcription: dict[str, Any]


class EvidenceBundleSubmission(FrozenModel):
    bundle: dict[str, Any]


class SQAnswersSubmission(FrozenModel):
    answers: tuple[dict[str, Any], ...] = Field(min_length=1)


SUBMISSION_ARGUMENTS = {
    "submit_source_classification": TypeAdapter(SourceClassificationSubmission),
    "submit_result_resolution": TypeAdapter(ResultResolutionSubmission),
    "submit_evidence_dispositions": TypeAdapter(EvidenceDispositionsSubmission),
    "submit_visual_transcription": TypeAdapter(VisualTranscriptionSubmission),
    "freeze_evidence_bundle": TypeAdapter(EvidenceBundleSubmission),
    "submit_sq_answers": TypeAdapter(SQAnswersSubmission),
}
