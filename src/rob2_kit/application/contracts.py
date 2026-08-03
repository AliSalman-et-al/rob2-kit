"""Typed public contracts for the lean RunEngine boundary.

The legacy gateway keeps its original envelopes for the expand step.  These
contracts are the new, one-operation-per-method seam and intentionally carry
no MCP, CLI, or host-framework types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.domain.assessment import SQAnswerCategory
from rob2_kit.domain.evidence import EvidenceCoverageState
from rob2_kit.domain.results import Estimate, Result, ResultSpecRevision
from rob2_kit.domain.revisions import (
    Actor,
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.domain.sources import (
    SourceDescriptor,
    SourceRole,
)
from rob2_kit.evidence.search import (
    CONTEXT_CHARACTER_TARGET,
    CanonicalEvidenceUnit,
    EvidenceContext,
    SearchPage,
    SearchPolicy,
    SearchQuery,
)
from rob2_kit.evidence.visual import (
    VisualCandidate,
    VisualRenderRequest,
)
from rob2_kit.evidence.workflow import ExecutedSearchQuery, SearchPassKind
from rob2_kit.ingestion.project import ProjectInitialization, ResultCandidate, TrialInitialization
from rob2_kit.registry import RegistryCandidate


class RunOperation(StrEnum):
    PREPARE_RUN = "prepare_run"
    RUN_STATUS = "run_status"
    CONTINUE_RUN = "continue_run"
    GET_WORK_CONTEXT = "get_work_context"
    SUBMIT_RUN_PROPOSAL = "submit_run_proposal"
    CONFIRM_RUN_DEFINITION = "confirm_run_definition"
    SEARCH_EVIDENCE = "search_evidence"
    READ_EVIDENCE = "read_evidence"
    INSPECT_VISUAL_CANDIDATE = "inspect_visual_candidate"
    SUBMIT_SOURCE_CLASSIFICATION = "submit_source_classification"
    SUBMIT_RESULT_RESOLUTION = "submit_result_resolution"
    SUBMIT_DOMAIN_EVIDENCE = "submit_domain_evidence"
    SUBMIT_DOMAIN_ANSWERS = "submit_domain_answers"


RUN_OPERATION_NAMES: tuple[str, ...] = tuple(operation.value for operation in RunOperation)


class WorkflowCondition(StrEnum):
    CONFIRMATION_REQUIRED = "confirmation_required"
    AGENT_WORK_REQUIRED = "agent_work_required"
    RUN_BLOCKED = "run_blocked"
    RUN_COMPLETE = "run_complete"
    RUN_INTEGRITY_FAILURE = "run_integrity_failure"
    COMPLETED = "completed"
    ACCEPTED = "accepted"
    STALE = "stale"
    INVALIDATED = "invalidated"
    RETRY = "retry"


class RunDirective(StrEnum):
    CONFIRMATION_REQUIRED = "confirmation_required"
    AGENT_WORK_REQUIRED = "agent_work_required"
    RUN_BLOCKED = "run_blocked"
    RUN_COMPLETE = "run_complete"
    RUN_INTEGRITY_FAILURE = "run_integrity_failure"


@dataclass(frozen=True)
class OperationContract:
    """Inspection metadata for one fixed public operation."""

    operation: RunOperation
    request_type: type[FrozenModel]
    response_type: type[OperationResponse]
    expected_conditions: tuple[WorkflowCondition, ...]


class ResultStatus(FrozenModel):
    result_id: Identifier
    state: ResultState


class IntegrityFailure(FrozenModel):
    code: Literal["incompatible_ledger_schema", "ledger_integrity_failure"]
    detail: str = Field(min_length=1)
    expected_schema_version: str | None = None
    found_schema_version: str | None = None
    recovery: tuple[str, ...] = Field(min_length=1)


class OperationError(FrozenModel):
    """Expected validation failure returned as a normal operation result."""

    code: Literal[
        "unsupported_method",
        "invalid_configuration",
        "second_project_root",
        "stale_proposal",
        "stale_work",
        "authorization_required",
        "material_ambiguity",
    ]
    detail: str = Field(min_length=1)
    recovery: tuple[str, ...] = Field(min_length=1)


class WorkToken(FrozenModel):
    """Opaque authorization for exactly one typed submission kind."""

    token: Identifier
    run_id: Identifier
    work_item_id: Identifier
    operation: RunOperation
    dependency_fingerprint: ContentHash
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None


class WorkItem(FrozenModel):
    work_item_id: Identifier
    work_token: WorkToken
    operation: RunOperation
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    dependency_fingerprint: ContentHash


class WorkContext(FrozenModel):
    work_item: WorkItem
    trial: TrialInitialization | None = None
    result_spec: ResultSpecRevision | None = None
    sources: tuple[SourceDescriptor, ...] = ()
    domain_id: Identifier | None = None
    registry_candidates: tuple[RegistryCandidate, ...] = ()
    result_candidates: tuple[ResultCandidate, ...] = ()


class RunProposalSelection(FrozenModel):
    trial_id: Identifier
    result_id: Identifier | None = None
    result_candidate_id: Identifier | None = None
    registry_candidate_id: Identifier | None = None
    outcome_target_id: Identifier | None = None
    accepted: bool = True


class RunProposalAmbiguity(FrozenModel):
    """A material initialization ambiguity retained in the proposal."""

    ambiguity_id: Identifier
    scope: Identifier
    detail: str = Field(min_length=1)
    material: bool = True
    resolved: bool = False
    resolution: str | None = None


class RunProposal(FrozenModel):
    proposal_id: Identifier
    proposal_token: Identifier
    run_id: Identifier
    supported_scope: Identifier
    trial_ids: tuple[Identifier, ...]
    result_ids: tuple[Identifier, ...]
    input_snapshot_hash: ContentHash
    initialization: ProjectInitialization
    selections: tuple[RunProposalSelection, ...] = ()
    registry_candidates: tuple[RegistryCandidate, ...] = ()
    result_candidates: tuple[ResultCandidate, ...] = ()
    ambiguities: tuple[RunProposalAmbiguity, ...] = ()

    @property
    def unresolved_ambiguities(self) -> tuple[RunProposalAmbiguity, ...]:
        return tuple(item for item in self.ambiguities if item.material and not item.resolved)


class ConfirmedRunDefinition(FrozenModel):
    run_id: Identifier
    proposal_id: Identifier
    proposal_token: Identifier
    supported_scope: Identifier
    trial_ids: tuple[Identifier, ...]
    result_ids: tuple[Identifier, ...]
    confirmed_by: Actor
    confirmed_at: datetime
    registry_candidate_ids: tuple[Identifier, ...] = ()
    outcome_target_ids: tuple[Identifier, ...] = ()


class PrepareRunRequest(FrozenModel):
    project_root: Path
    authorized: bool = False
    start_new: bool = False
    method: str | None = None
    supported_scope: str | None = None


class RunStatusRequest(FrozenModel):
    run_id: Identifier


class ContinueRunRequest(FrozenModel):
    run_id: Identifier


class GetWorkContextRequest(FrozenModel):
    run_id: Identifier
    work_token: WorkToken


class SubmitRunProposalRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    selections: tuple[RunProposalSelection, ...] = ()
    ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    unresolved_ambiguities: tuple[RunProposalAmbiguity, ...] = ()


class ConfirmRunDefinitionRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    confirmed_by: Actor


class SearchEvidenceRequest(FrozenModel):
    run_id: Identifier
    query: SearchQuery
    result_id: Identifier | None = None
    cursor: str | None = None
    broad_query_justification: str | None = None
    policy: SearchPolicy | None = None
    sq_id: Identifier | None = None
    pass_kind: SearchPassKind | None = None
    seed_family: Identifier | None = None


class ReadEvidenceRequest(FrozenModel):
    run_id: Identifier
    unit_id: Identifier
    result_id: Identifier | None = None
    neighbor_limit: int = Field(default=6, ge=0, le=50)
    context_character_target: int = Field(
        default=CONTEXT_CHARACTER_TARGET,
        ge=1,
        le=CONTEXT_CHARACTER_TARGET,
    )


class InspectVisualCandidateRequest(FrozenModel):
    run_id: Identifier
    candidate_id: Identifier
    result_id: Identifier | None = None
    current_render: VisualRenderRequest | None = None
    still_ambiguous: bool = True


class SourceClassificationInput(FrozenModel):
    source_id: Identifier
    roles: tuple[SourceRole, ...] = Field(min_length=1)


class SubmitSourceClassificationRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    classifications: tuple[SourceClassificationInput, ...] = Field(min_length=1)


class SubmitResultResolutionRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result: Result
    estimate: Estimate
    provenance_note: str = Field(min_length=1)


class SubmitDomainEvidenceRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    items: tuple[RecordReference, ...] = ()
    coverage_state: EvidenceCoverageState = EvidenceCoverageState.COMPLETE
    coverage_limitations: tuple[str, ...] = ()
    no_information_basis: bool = False
    conflicts: tuple[tuple[Identifier, ...], ...] = ()


class SQAnswerInput(FrozenModel):
    question_id: Identifier
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)


class SubmitDomainAnswersRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    answers: tuple[SQAnswerInput, ...] = Field(min_length=1)
    assessor_inputs: dict[Identifier, bool] = Field(default_factory=dict)


class OperationResponse(FrozenModel):
    operation_id: Identifier
    ledger_cursor: str = Field(min_length=1)
    affected_scope: tuple[Identifier, ...]
    condition: WorkflowCondition
    committed: bool
    next_permitted_action: RunOperation | None = None
    error: OperationError | None = None


class PrepareRunResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    proposal: RunProposal | None = None
    integrity: IntegrityFailure | None = None


class RunStatusResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    result_states: tuple[ResultStatus, ...] = ()
    integrity: IntegrityFailure | None = None


class ContinueRunResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    directive: RunDirective
    work_item: WorkItem | None = None
    integrity: IntegrityFailure | None = None


class GetWorkContextResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    work_item: WorkItem | None = None
    context: WorkContext | None = None


class SubmitRunProposalResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    proposal: RunProposal | None = None


class ConfirmRunDefinitionResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    run_definition: ConfirmedRunDefinition | None = None


class SearchEvidenceResponse(OperationResponse):
    run_id: Identifier
    page: SearchPage
    executed_query: ExecutedSearchQuery | None = None


class ReadEvidenceResponse(OperationResponse):
    run_id: Identifier
    unit: CanonicalEvidenceUnit
    context: EvidenceContext | None = None


class InspectVisualCandidateResponse(OperationResponse):
    run_id: Identifier
    candidate: VisualCandidate
    render: VisualRenderRequest


class SubmissionResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    result_id: Identifier | None = None
    result_state: ResultState | None = None
    work_item: WorkItem | None = None


class SubmitSourceClassificationResponse(SubmissionResponse):
    pass


class SubmitResultResolutionResponse(SubmissionResponse):
    result_spec: ResultSpecRevision | None = None


class SubmitDomainEvidenceResponse(SubmissionResponse):
    domain_id: Identifier


class SubmitDomainAnswersResponse(SubmissionResponse):
    domain_id: Identifier


RUN_OPERATION_CONTRACTS: tuple[OperationContract, ...] = (
    OperationContract(
        operation=RunOperation.PREPARE_RUN,
        request_type=PrepareRunRequest,
        response_type=PrepareRunResponse,
        expected_conditions=(
            WorkflowCondition.CONFIRMATION_REQUIRED,
            WorkflowCondition.RUN_BLOCKED,
            WorkflowCondition.RUN_INTEGRITY_FAILURE,
        ),
    ),
    OperationContract(
        operation=RunOperation.RUN_STATUS,
        request_type=RunStatusRequest,
        response_type=RunStatusResponse,
        expected_conditions=(
            WorkflowCondition.COMPLETED,
            WorkflowCondition.RUN_INTEGRITY_FAILURE,
        ),
    ),
    OperationContract(
        operation=RunOperation.CONTINUE_RUN,
        request_type=ContinueRunRequest,
        response_type=ContinueRunResponse,
        expected_conditions=(
            WorkflowCondition.CONFIRMATION_REQUIRED,
            WorkflowCondition.AGENT_WORK_REQUIRED,
            WorkflowCondition.RUN_BLOCKED,
            WorkflowCondition.RUN_COMPLETE,
            WorkflowCondition.RUN_INTEGRITY_FAILURE,
        ),
    ),
    OperationContract(
        operation=RunOperation.GET_WORK_CONTEXT,
        request_type=GetWorkContextRequest,
        response_type=GetWorkContextResponse,
        expected_conditions=(
            WorkflowCondition.AGENT_WORK_REQUIRED,
            WorkflowCondition.CONFIRMATION_REQUIRED,
            WorkflowCondition.STALE,
        ),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_RUN_PROPOSAL,
        request_type=SubmitRunProposalRequest,
        response_type=SubmitRunProposalResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.CONFIRMATION_REQUIRED,
            WorkflowCondition.STALE,
        ),
    ),
    OperationContract(
        operation=RunOperation.CONFIRM_RUN_DEFINITION,
        request_type=ConfirmRunDefinitionRequest,
        response_type=ConfirmRunDefinitionResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.AGENT_WORK_REQUIRED,
            WorkflowCondition.STALE,
            WorkflowCondition.RUN_BLOCKED,
        ),
    ),
    OperationContract(
        operation=RunOperation.SEARCH_EVIDENCE,
        request_type=SearchEvidenceRequest,
        response_type=SearchEvidenceResponse,
        expected_conditions=(WorkflowCondition.COMPLETED,),
    ),
    OperationContract(
        operation=RunOperation.READ_EVIDENCE,
        request_type=ReadEvidenceRequest,
        response_type=ReadEvidenceResponse,
        expected_conditions=(WorkflowCondition.COMPLETED,),
    ),
    OperationContract(
        operation=RunOperation.INSPECT_VISUAL_CANDIDATE,
        request_type=InspectVisualCandidateRequest,
        response_type=InspectVisualCandidateResponse,
        expected_conditions=(WorkflowCondition.COMPLETED,),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_SOURCE_CLASSIFICATION,
        request_type=SubmitSourceClassificationRequest,
        response_type=SubmitSourceClassificationResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.STALE,
            WorkflowCondition.RETRY,
        ),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_RESULT_RESOLUTION,
        request_type=SubmitResultResolutionRequest,
        response_type=SubmitResultResolutionResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.STALE,
            WorkflowCondition.RETRY,
        ),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_DOMAIN_EVIDENCE,
        request_type=SubmitDomainEvidenceRequest,
        response_type=SubmitDomainEvidenceResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.RUN_BLOCKED,
            WorkflowCondition.STALE,
        ),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_DOMAIN_ANSWERS,
        request_type=SubmitDomainAnswersRequest,
        response_type=SubmitDomainAnswersResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.RUN_COMPLETE,
            WorkflowCondition.STALE,
        ),
    ),
)
