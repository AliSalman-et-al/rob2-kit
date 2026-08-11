"""Typed public contracts for the lean RunEngine boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from rob2_kit.application.active_question_frontier import QuestionEvidenceBundleBinding
from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.domain.assessment import SQAnswerCategory
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.domain.evidence import (
    ConsiderationDisposition,
    EvidenceReviewDisposition,
    TrialAttribution,
)
from rob2_kit.domain.results import (
    DiscoveryCandidateDisposition,
    Estimate,
    ProposalDiscoveryCoverageReceipt,
    ProposalLimitation,
    ProposalMappingStatus,
    ReportedArmCandidate,
    ReportedCandidateProvenance,
    ReportedEndpointCandidate,
    ReportedRandomizationCandidate,
    Result,
    ResultIdentityCompleteness,
    ResultSpecRevision,
)
from rob2_kit.domain.revisions import (
    Actor,
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
    Supersession,
)
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceDescriptor,
    SourceFailureCategory,
    SourceProcessing,
    SourceRole,
    SourceUse,
)
from rob2_kit.evidence.errors import OperationalRetrievalFailure, RetrievalErrorCode
from rob2_kit.evidence.obligations import ChronologyConstraint
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    EvidenceReadBatchPage,
    EvidenceReadBatchRequest,
    EvidenceSearchPage,
    SearchContinuationReason,
    SearchQuery,
    SearchQueryFields,
    compact_coverage_progress,
)
from rob2_kit.evidence.visual import (
    VisualCandidate,
    VisualRenderRequest,
)
from rob2_kit.evidence.workflow import (
    V3CandidateTriageRevision,
    V3ChronologyStatus,
    V3EvidenceStageOutcomeSubmission,
)
from rob2_kit.ingestion.project import (
    OutcomeTarget,
    ProjectInitialization,
    ResultCandidate,
    SourceRoleCandidate,
)
from rob2_kit.logic.packs import GuidanceItem
from rob2_kit.registry import RegistryCandidate

CONTRACT_VERSION = "1.1.0"
EVIDENCE_NAVIGATION_CONTRACT_VERSION = "3.0.0"
DOMAIN_EVIDENCE_CONTRACT_VERSION = "3.0.0"


class RunOperation(StrEnum):
    PREPARE_RUN = "prepare_run"
    RUN_STATUS = "run_status"
    CONTINUE_RUN = "continue_run"
    REPRIORITIZE_RESULTS = "reprioritize_results"
    WITHDRAW_RESULT = "withdraw_result"
    REOPEN_RESULT = "reopen_result"
    GET_WORK_CONTEXT = "get_work_context"
    SUBMIT_RUN_PROPOSAL = "submit_run_proposal"
    SUBMIT_PROPOSAL_DISCOVERY_REVIEW = "submit_proposal_discovery_review"
    SUBMIT_RESULT_MAPPING_REVIEW = "submit_result_mapping_review"
    CONFIRM_RUN_DEFINITION = "confirm_run_definition"
    SEARCH_EVIDENCE = "search_evidence"
    READ_EVIDENCE = "read_evidence"
    INSPECT_VISUAL_CANDIDATE = "inspect_visual_candidate"
    SUBMIT_SOURCE_ROLE_REVIEW = "submit_source_role_review"
    SUBMIT_RESULT_RESOLUTION = "submit_result_resolution"
    SUBMIT_EVIDENCE_REVIEW = "submit_evidence_review"
    SUBMIT_EVIDENCE_STAGE_OUTCOME = "submit_evidence_stage_outcome"
    MATERIALIZE_QUESTION_EVIDENCE_BUNDLE = "materialize_question_evidence_bundle"
    SUBMIT_QUESTION_STEP = "submit_question_step"
    CORRECT_QUESTION_STEP = "correct_question_step"
    SUBMIT_SOURCE_CHRONOLOGY_REVIEW = "submit_source_chronology_review"


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


class ErrorClass(StrEnum):
    """Stable MCP outcome classes for model-visible failures."""

    CORRECTABLE = "correctable"
    AUTHORITY = "authority"
    OPERATIONAL = "operational"


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


class RunProgress(FrozenModel):
    """Ledger-derived details a Harness needs to resume without inference."""

    committed_checkpoint: Identifier | None = None
    current_scope: tuple[Identifier, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    result_state_counts: dict[str, int] = Field(default_factory=dict)
    terminal_result_counts: dict[str, int] = Field(default_factory=dict)
    report_locations: tuple[str, ...] = ()
    result_order: tuple[Identifier, ...] = ()
    next_action: RunOperation | None = None


class IntegrityFailure(FrozenModel):
    code: Literal["incompatible_ledger_schema", "ledger_integrity_failure"]
    detail: str = Field(min_length=1)
    expected_schema_version: str | None = None
    found_schema_version: str | None = None
    recovery: tuple[str, ...] = Field(min_length=1)


class OperationError(FrozenModel):
    """Expected validation failure returned as a normal operation result."""

    error_class: ErrorClass = ErrorClass.CORRECTABLE

    code: Literal[
        "unsupported_method",
        "invalid_configuration",
        "second_project_root",
        "stale_proposal",
        "stale_work",
        "invalid_result_control",
        "human_actor_required",
        "authorization_required",
        "material_ambiguity",
        "evidence_insufficient",
    ]
    detail: str = Field(min_length=1)
    recovery: tuple[str, ...] = Field(min_length=1)
    correlation_id: Identifier | None = None
    violations: tuple[OperationError, ...] = Field(default_factory=tuple)


class RetrievalFieldViolation(FrozenModel):
    """One field-level validation failure within a possibly-batched request."""

    field: str | None = None
    message: str = Field(min_length=1)


class RetrievalError(FrozenModel):
    code: RetrievalErrorCode
    field: str | None = None
    message: str = Field(min_length=1)
    recovery: tuple[str, ...] = Field(min_length=1)
    violations: tuple[RetrievalFieldViolation, ...] = Field(default_factory=tuple)

    @property
    def detail(self) -> str:
        """Backward-compatible name for hosts that used the old envelope."""

        return self.message


class RetrievalErrorResponse(FrozenModel):
    condition: Literal["retrieval_error"] = "retrieval_error"
    error: RetrievalError
    omitted: Literal[True] = True
    next_actions: tuple[str, ...] = Field(min_length=1)


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
    source_id: Identifier | None = None
    parse_id: Identifier | None = None
    # v3 evidence work is authorized against one immutable question-session
    # projection, rather than the former domain-wide navigation state.
    question_id: Identifier | None = None
    session_content_hash: ContentHash | None = None
    frontier_entry_hash: ContentHash | None = None
    context_id: Identifier | None = None
    context_hash: ContentHash | None = None
    diagnostic_stop_hash: ContentHash | None = None


class WorkItem(FrozenModel):
    work_item_id: Identifier
    work_token: WorkToken
    operation: RunOperation
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    dependency_fingerprint: ContentHash
    source_id: Identifier | None = None
    parse_id: Identifier | None = None
    question_id: Identifier | None = None
    session_content_hash: ContentHash | None = None
    frontier_entry_hash: ContentHash | None = None
    context_id: Identifier | None = None
    context_hash: ContentHash | None = None


class NextActionArguments(FrozenModel):
    """Engine-known arguments for one follow-up action.

    The Harness must copy these values verbatim instead of reconstructing
    scope from conversation history.  Optional fields keep the envelope
    compact while the closed model prevents arbitrary host-controlled
    dispatch arguments from entering the public contract.
    """

    run_id: Identifier | None = None
    work_token: WorkToken | None = None
    proposal_token: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    cursor: str | None = None


class NextAction(FrozenModel):
    """One legal, engine-authored continuation instruction."""

    operation: RunOperation
    reason: str = Field(min_length=1)
    arguments: NextActionArguments = Field(default_factory=NextActionArguments)


class EvidenceConsiderationInput(FrozenModel):
    """Agent disposition for one candidate before an Evidence Bundle freezes."""

    item_id: Identifier = Field(
        description="Evidence candidate/item ID issued by the current evidence work item."
    )
    disposition: ConsiderationDisposition = Field(
        description=(
            "One valid exact enum value: supporting, contradicting, contextual, duplicate, "
            "out_of_scope, immaterial, superseded, or unresolved. Do not use aliases "
            "such as irrelevant."
        )
    )
    basis: str | None = Field(
        default=None,
        description=(
            "Concise attributable basis; required for superseded chronology and unresolved "
            "limitations."
        ),
    )
    superseded_by: Identifier | None = Field(
        default=None,
        description=(
            "Evidence item that supersedes this one. Required only for superseded; it must be "
            "recorded in the same conflict group."
        ),
    )

    @model_validator(mode="after")
    def validate_supersession(self) -> EvidenceConsiderationInput:
        superseded = self.disposition is ConsiderationDisposition.SUPERSEDED
        if superseded and (self.superseded_by is None or not self.basis):
            raise ValueError("superseded evidence requires replacing item and chronology basis")
        if not superseded and self.superseded_by is not None:
            raise ValueError("superseded_by is valid only for superseded evidence")
        if superseded and self.superseded_by == self.item_id:
            raise ValueError("evidence cannot supersede itself")
        return self


class EvidencePassageInput(FrozenModel):
    """Exact canonical passage selected for a Domain Evidence Bundle."""

    unit_id: Identifier = Field(
        description="Canonical unit_id returned by search_evidence or read_evidence."
    )
    span_start: int = Field(
        ge=0, description="Zero-based inclusive character offset in the canonical unit text."
    )
    span_end: int | None = Field(
        default=None,
        description=(
            "Optional zero-based exclusive offset; omit to select through the end of the unit."
        ),
    )
    claim_type: Identifier = Field(
        description="Attributable claim category, for example claim-type:randomization-method."
    )
    candidate_id: Identifier | None = Field(
        default=None,
        description=(
            "Retained Evidence-candidate ID for this exact span. Required when the "
            "submission includes Search coverage receipts."
        ),
    )
    question_ids: tuple[Identifier, ...] = Field(
        min_length=1,
        description="Active signaling-question IDs supported by this exact passage.",
    )
    disposition: ConsiderationDisposition = Field(
        default=ConsiderationDisposition.SUPPORTING,
        description="How the selected passage bears on the mapped questions.",
    )
    basis: str | None = Field(
        default=None,
        description=(
            "Optional concise basis for the disposition; required for superseded chronology."
        ),
    )
    superseded_by: Identifier | None = Field(
        default=None,
        description=(
            "Evidence item that supersedes this passage's claim. Required only for "
            "superseded; it must be recorded in the same conflicts group."
        ),
    )

    @model_validator(mode="after")
    def validate_passage(self) -> EvidencePassageInput:
        if self.span_end is not None and self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("question_ids must be unique")
        if self.disposition not in {
            ConsiderationDisposition.SUPPORTING,
            ConsiderationDisposition.CONTRADICTING,
            ConsiderationDisposition.CONTEXTUAL,
            ConsiderationDisposition.SUPERSEDED,
        }:
            raise ValueError("passage disposition must accept the selected passage")
        superseded = self.disposition is ConsiderationDisposition.SUPERSEDED
        if superseded and (self.superseded_by is None or not self.basis):
            raise ValueError("superseded passage requires replacing item and chronology basis")
        if not superseded and self.superseded_by is not None:
            raise ValueError("superseded_by is valid only for superseded passages")
        return self


class EvidenceReviewSpanInput(FrozenModel):
    """Agent's review of an exact span in one engine-issued read view."""

    read_view_receipt: str = Field(min_length=1, max_length=8192)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    trial_attribution: TrialAttribution
    disposition: EvidenceReviewDisposition
    rationale: str = Field(min_length=1)
    attribution_rationale: str | None = None
    visual_review_condition: Identifier | None = None
    duplicate_of: Identifier | None = None

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceReviewSpanInput:
        if self.span_end <= self.span_start:
            raise ValueError("review span must have positive extent")
        if self.trial_attribution is TrialAttribution.ACTIVE and not self.attribution_rationale:
            raise ValueError("active attribution requires bounded-context rationale")
        return self


class EvidenceReviewRevisionInput(FrozenModel):
    """Candidate review submitted for exactly one signaling question.

    The engine resolves receipts and derives stable span identities before it
    writes the immutable EvidenceReviewRevision.
    """

    entity_id: Identifier
    revision_id: Identifier
    actor: Actor
    observed_at: datetime
    supersedes: Supersession | None = None
    candidate_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    sq_id: Identifier
    spans: tuple[EvidenceReviewSpanInput, ...] = Field(min_length=1)


class SourceContextSummary(FrozenModel):
    """Bounded source projection for routine agent work context."""

    source_id: Identifier
    title: str
    relative_path: str
    roles: tuple[SourceRole, ...]
    criticality: SourceCriticality
    availability: SourceAvailability
    processing: SourceProcessing
    use: SourceUse
    artifact_hash: ContentHash | None = None
    external_identifiers: tuple[str, ...] = ()
    failure_category: SourceFailureCategory | None = None
    page_count: int = Field(ge=0)
    coverage_states: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_descriptor(cls, source: SourceDescriptor) -> SourceContextSummary:
        states: dict[str, int] = {}
        for page in source.coverage:
            states[page.state.value] = states.get(page.state.value, 0) + 1
        return cls(
            source_id=source.source_id,
            title=source.title,
            relative_path=source.relative_path,
            roles=source.roles,
            criticality=source.criticality,
            availability=source.availability,
            processing=source.processing,
            use=source.use,
            artifact_hash=source.artifact_hash,
            external_identifiers=source.external_identifiers,
            failure_category=source.failure_category,
            page_count=len(source.coverage),
            coverage_states=states,
        )


class TrialContextSummary(FrozenModel):
    """Trial identity and inventory limitations without repeated source detail."""

    trial_id: Identifier
    status: Literal["inventory_ready", "trial_failed"]
    inventory_id: Identifier
    coverage_limitations: tuple[str, ...] = ()


class DomainContextPack(FrozenModel):
    """Bounded, reproducible context for one Result × RoB 2 domain."""

    result_id: Identifier
    domain_id: Identifier
    # Pack release identifiers are the pack's canonical version (for example
    # ``2019.1``), not an entity identifier with a ``name:`` prefix.
    logic_pack_release_id: str = Field(min_length=1)
    logic_pack_hash: ContentHash
    guidance_pack_release_id: str = Field(min_length=1)
    guidance_pack_hash: ContentHash
    active_question_ids: tuple[Identifier, ...]
    inactive_question_ids: tuple[Identifier, ...] = ()
    guidance_items: tuple[GuidanceItem, ...] = ()
    project_rules: tuple[RecordReference, ...] = ()
    sources: tuple[SourceContextSummary, ...] = ()
    source_limitations: tuple[str, ...] = ()
    reusable_evidence: tuple[RecordReference, ...] = ()
    required_protocol: tuple[str, ...] = (
        "mandatory_search_coverage",
        "candidate_disposition",
        "contradiction_pass",
        "visual_gate",
    )
    content_hash: ContentHash
    # These fields make the active v3 session projection explicit to callers
    # without exposing the private durable session ledger.
    session_content_hash: ContentHash | None = None
    frontier_entry_hash: ContentHash | None = None
    context_id: Identifier | None = None
    context_hash: ContentHash | None = None
    context_page_ids: tuple[Identifier, ...] = ()

    @property
    def active_questions(self) -> tuple[Identifier, ...]:
        return self.active_question_ids

    @property
    def guidance(self) -> tuple[GuidanceItem, ...]:
        return self.guidance_items

    @property
    def limitations(self) -> tuple[str, ...]:
        return self.source_limitations

    @model_validator(mode="after")
    def validate_content_hash(self) -> DomainContextPack:
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("Domain context pack content hash does not match its contents")
        return self


class WorkContext(FrozenModel):
    work_item: WorkItem
    trial: TrialContextSummary | None = None
    result_spec: ResultSpecRevision | None = None
    sources: tuple[SourceContextSummary, ...] = ()
    detailed_sources: tuple[SourceDescriptor, ...] = ()
    domain_id: Identifier | None = None
    registry_candidates: tuple[RegistryCandidate, ...] = ()
    result_candidates: tuple[ResultCandidate, ...] = ()
    reported_endpoint_candidates: tuple[ReportedEndpointCandidate, ...] = ()
    reported_randomization_candidates: tuple[ReportedRandomizationCandidate, ...] = ()
    reported_arm_candidates: tuple[ReportedArmCandidate, ...] = ()
    proposal_discovery_receipts: tuple[ProposalDiscoveryCoverageReceipt, ...] = ()
    proposal_discovery_page: EvidenceSearchPage | None = None
    proposal_discovery_units: tuple[CanonicalEvidenceUnit, ...] = ()
    proposal_discovery_read_continuation: str | None = None
    proposal_discovery_policy: ProposalDiscoveryPolicy | None = None
    domain_context: DomainContextPack | None = None

    @property
    def context_pack(self) -> DomainContextPack | None:
        return self.domain_context


class RunProposalSelection(FrozenModel):
    trial_id: Identifier
    result_id: Identifier | None = None
    result_candidate_id: Identifier | None = None
    registry_candidate_id: Identifier | None = None
    outcome_target_id: Identifier | None = None
    # Source-role disposition uses this same shape rather than a second
    # record type (#119): source_id selects the Source-role candidate's
    # slot, mutually exclusive with the Trial × Outcome fields above. roles
    # is the accepted role set — omit it to accept the candidate's proposed
    # roles as-is, or supply a corrected set explicitly.
    source_id: Identifier | None = None
    roles: tuple[SourceRole, ...] | None = None
    accepted: bool = True
    removed: bool = False
    exclusion_reason: str | None = Field(
        default=None,
        validation_alias=AliasChoices("exclusion_reason", "reason"),
        description=(
            "Human-readable reason for explicitly excluding this Trial × Outcome target "
            "or Source-role candidate. Required when accepted is false."
        ),
    )

    @model_validator(mode="after")
    def validate_disposition(self) -> RunProposalSelection:
        if self.source_id is not None:
            if (
                self.outcome_target_id is not None
                or self.result_id is not None
                or self.result_candidate_id is not None
                or self.registry_candidate_id is not None
            ):
                raise ValueError(
                    "a Source-role selection cannot also select an Outcome target, "
                    "Result, or Registry candidate"
                )
            if self.removed:
                raise ValueError("a Source-role selection cannot be removed")
            if self.accepted:
                if self.exclusion_reason is not None and not self.exclusion_reason.strip():
                    raise ValueError("exclusion_reason cannot be blank")
            else:
                if self.roles is not None:
                    raise ValueError("a rejected Source-role selection cannot set roles")
                if not self.exclusion_reason or not self.exclusion_reason.strip():
                    raise ValueError("a rejected Source-role selection requires exclusion_reason")
            return self
        if self.roles is not None:
            raise ValueError("roles is only meaningful for a Source-role selection")
        if self.removed:
            if self.accepted:
                raise ValueError("a removed Run proposal pairing must set accepted=false")
            if self.result_id is not None or self.result_candidate_id is not None:
                raise ValueError("a removed Run proposal pairing cannot select a Result")
            if self.exclusion_reason is not None and not self.exclusion_reason.strip():
                raise ValueError("exclusion_reason cannot be blank")
            return self
        if not self.accepted:
            if self.result_id is not None or self.result_candidate_id is not None:
                raise ValueError("an excluded Run proposal pairing cannot select a Result")
            if not self.exclusion_reason or not self.exclusion_reason.strip():
                raise ValueError("an excluded Run proposal pairing requires exclusion_reason")
        elif self.exclusion_reason is not None and not self.exclusion_reason.strip():
            raise ValueError("exclusion_reason cannot be blank")
        return self


class RunProposalPair(FrozenModel):
    """Compact human-facing disposition for one requested Trial × Outcome target."""

    trial_id: Identifier
    outcome_target_id: Identifier
    candidate_ids: tuple[Identifier, ...] = ()
    result_id: Identifier | None = None
    preferred_result_id: Identifier | None = None
    selection_policy: str | None = None
    disposition: Literal["selected", "excluded", "removed", "unresolved"] = "unresolved"
    exclusion_reason: str | None = None
    differences: tuple[str, ...] = ()


class RunProposalAmbiguity(FrozenModel):
    """A material initialization ambiguity retained in the proposal."""

    ambiguity_id: Identifier
    scope: Identifier
    detail: str = Field(min_length=1)
    material: bool = True
    resolved: bool = False
    resolution: str | None = None
    trial_id: Identifier | None = None
    outcome_target_id: Identifier | None = None


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
    source_role_candidates: tuple[SourceRoleCandidate, ...] = ()
    reported_endpoint_candidates: tuple[ReportedEndpointCandidate, ...] = ()
    reported_randomization_candidates: tuple[ReportedRandomizationCandidate, ...] = ()
    reported_arm_candidates: tuple[ReportedArmCandidate, ...] = ()
    proposal_discovery_receipts: tuple[ProposalDiscoveryCoverageReceipt, ...] = ()
    limitations: tuple[ProposalLimitation, ...] = ()
    randomization_bindings: tuple[tuple[Identifier, Identifier], ...] = ()
    arm_bindings: tuple[tuple[Identifier, Identifier], ...] = ()
    promotion_batches: tuple[ProposalPromotionBatchInput, ...] = ()
    submission_request_hash: ContentHash | None = None
    ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    supersedes_proposal_id: Identifier | None = None
    semantic_diff: tuple[str, ...] = ()

    @property
    def unresolved_ambiguities(self) -> tuple[RunProposalAmbiguity, ...]:
        return tuple(item for item in self.ambiguities if item.material and not item.resolved)

    @property
    def outcome_targets(self) -> tuple[OutcomeTarget, ...]:
        return self.initialization.manifest.outcome_target_specs

    @property
    def source_limitations(self) -> tuple[str, ...]:
        limitations: list[str] = []
        for trial in self.initialization.trials:
            limitations.extend(
                f"{trial.trial_id}: {item}" for item in trial.inventory.coverage_limitations
            )
        limitations.extend(
            finding.detail
            for finding in self.initialization.diagnostics
            if finding.kind.value
            in {
                "optional_source_acquisition_failed",
                "optional_source_processing_failed",
                "registry_unavailable",
                "registry_acquisition_failed",
            }
        )
        return tuple(dict.fromkeys(limitations))

    def pairings(self) -> tuple[RunProposalPair, ...]:
        """Return the compact, progressive-disclosure mapping view."""

        from rob2_kit.application.proposals import proposal_pairings

        return proposal_pairings(self)

    def compact_payload(self) -> dict[str, object]:
        """Serialize only the human proposal projection, never parser output."""

        from rob2_kit.application.proposals import compact_proposal_payload

        return compact_proposal_payload(self)


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


# Canonical expand-phase spelling.  The aliases intentionally share the same
# closed schema and durable operation as the legacy ``run_status`` contract.
GetRunStatusRequest = RunStatusRequest


class ContinueRunRequest(FrozenModel):
    run_id: Identifier


class ReprioritizeResultsRequest(FrozenModel):
    """Durably reorder only Results that have not started preparation."""

    contract_version: Literal["1.0.0"]
    run_id: Identifier
    result_ids: tuple[Identifier, ...] = Field(min_length=1)
    idempotency_key: Identifier
    requested_by: Actor


class WithdrawResultRequest(FrozenModel):
    """Stop one Result at a checkpoint while retaining its diagnostic record."""

    contract_version: Literal["1.0.0"]
    run_id: Identifier
    result_id: Identifier
    reason: str = Field(min_length=1)
    idempotency_key: Identifier
    requested_by: Actor


class ReopenResultRequest(FrozenModel):
    """Return an explicitly withdrawn Result to the pending work order."""

    contract_version: Literal["1.0.0"]
    run_id: Identifier
    result_id: Identifier
    idempotency_key: Identifier
    requested_by: Actor


class GetWorkContextRequest(FrozenModel):
    run_id: Identifier
    work_token: WorkToken
    include_source_details: bool = False
    proposal_discovery_query: SearchQuery | None = None
    proposal_discovery_unit_ids: tuple[Identifier, ...] = Field(default=(), max_length=4)
    proposal_discovery_continuation: str | None = None
    proposal_discovery_read_continuation: str | None = None
    proposal_discovery_pass: str | None = None

    @model_validator(mode="after")
    def validate_discovery_navigation(self) -> GetWorkContextRequest:
        if self.proposal_discovery_query is not None and self.proposal_discovery_unit_ids:
            raise ValueError(
                "proposal discovery context accepts either a query or unit IDs, not both"
            )
        if (
            self.proposal_discovery_continuation is not None
            and self.proposal_discovery_query is None
        ):
            raise ValueError("proposal discovery continuation requires a query")
        if self.proposal_discovery_read_continuation is not None and (
            self.proposal_discovery_query is not None
            or self.proposal_discovery_unit_ids
            or self.proposal_discovery_continuation is not None
        ):
            raise ValueError(
                "proposal discovery read continuation is a standalone navigation request"
            )
        if (self.proposal_discovery_query is None) != (self.proposal_discovery_pass is None):
            raise ValueError("proposal discovery search requires an engine-issued pass")
        return self


class ProposalDiscoveryPassQuery(FrozenModel):
    """Engine-issued semantic minimum for one discovery search pass."""

    pass_id: str = Field(min_length=1)
    required_any_terms: tuple[str, ...] = Field(min_length=1)
    canonical_query: SearchQuery


class ProposalDiscoveryPolicy(FrozenModel):
    """Engine-issued bounds for one token-scoped pre-confirmation review."""

    policy_revision: str = "discovery-policy:1"
    required_passes: tuple[str, ...] = Field(min_length=1)
    pass_queries: tuple[ProposalDiscoveryPassQuery, ...] = ()
    read_unit_ceiling: int = Field(default=4, ge=1)
    read_character_ceiling: int = Field(default=8_000, ge=1)

    @model_validator(mode="after")
    def validate_pass_queries(self) -> ProposalDiscoveryPolicy:
        if tuple(item.pass_id for item in self.pass_queries) != self.required_passes:
            raise ValueError("discovery policy must define query semantics for every required pass")
        return self


class SubmitRunProposalRequest(FrozenModel):
    contract_version: Literal["2.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    authorized: bool = False
    selections: tuple[RunProposalSelection, ...] = ()
    ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    unresolved_ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    promotions: ProposalPromotionBatchInput | None = None


class OutcomeTargetPromotionInput(FrozenModel):
    target: OutcomeTarget
    endpoint_candidate_ids: tuple[Identifier, ...] = Field(min_length=1)
    admissibility_rule: Literal["promoted_design_required", "design_undiscovered"] = (
        "promoted_design_required"
    )


class RandomizationPromotionInput(FrozenModel):
    randomization_candidate_id: Identifier
    arm_candidate_ids: tuple[Identifier, ...] = Field(min_length=1)


class ProposalPromotionBatchInput(FrozenModel):
    """Human-only identity binding; all durable IDs are engine issued."""

    promoted_by: Actor
    outcome_targets: tuple[OutcomeTargetPromotionInput, ...] = ()
    randomizations: tuple[RandomizationPromotionInput, ...] = ()

    @model_validator(mode="after")
    def validate_human_and_unique(self) -> ProposalPromotionBatchInput:
        if self.promoted_by.kind.value != "human":
            raise ValueError("proposal promotion requires an attributable human actor")
        if len({item.target.target_id for item in self.outcome_targets}) != len(
            self.outcome_targets
        ):
            raise ValueError("promoted outcome targets must be unique")
        if len({item.randomization_candidate_id for item in self.randomizations}) != len(
            self.randomizations
        ):
            raise ValueError("promoted randomizations must be unique")
        return self


class ProposalDiscoveryDispositionInput(FrozenModel):
    candidate_id: Identifier
    disposition: Literal["accepted", "rejected", "unresolved"]
    detail: str = Field(min_length=1)
    superseded_by_candidate_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_supersession(self) -> ProposalDiscoveryDispositionInput:
        DiscoveryCandidateDisposition(
            candidate_id=self.candidate_id,
            disposition=self.disposition,
            detail=self.detail,
            superseded_by_candidate_id=self.superseded_by_candidate_id,
        )
        return self


class SubmitProposalDiscoveryReviewRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    endpoints: tuple[ReportedEndpointCandidate, ...] = ()
    randomizations: tuple[ReportedRandomizationCandidate, ...] = ()
    arms: tuple[ReportedArmCandidate, ...] = ()
    dispositions: tuple[ProposalDiscoveryDispositionInput, ...] = ()
    coverage_receipt: ProposalDiscoveryCoverageReceipt


class ResultMappingReviewInput(FrozenModel):
    candidate_id: Identifier
    trial_id: Identifier
    endpoint_candidate_id: Identifier
    randomization_candidate_id: Identifier
    experimental_arm_candidate_id: Identifier
    comparator_arm_candidate_id: Identifier
    outcome_target_id: Identifier | None = None
    label: str = Field(min_length=1)
    mapping_status: ProposalMappingStatus
    identity_completeness: ResultIdentityCompleteness
    result: Result | None = None
    estimate: Estimate | None = None
    provenance_note: str | None = None
    source_provenance: ReportedCandidateProvenance | None = None
    construct_admissibility: Literal["exact", "accepted_synonym"] = "exact"
    construct_synonym_rationale: str | None = None
    reviewed_by: Actor

    @model_validator(mode="after")
    def validate_complete_mapping(self) -> ResultMappingReviewInput:
        complete = self.mapping_status is ProposalMappingStatus.ACCEPTED and (
            self.identity_completeness is ResultIdentityCompleteness.RESULT_COMPLETE
        )
        if complete and (self.result is None or self.estimate is None or not self.provenance_note):
            raise ValueError(
                "complete Result mapping requires Result, Estimate, and provenance_note"
            )
        if not complete and (self.result is not None or self.estimate is not None):
            raise ValueError("non-complete Result mapping cannot claim an exact Result")
        if complete and self.source_provenance is None:
            raise ValueError("complete Result mapping requires exact source provenance")
        if not complete and self.source_provenance is not None:
            raise ValueError("non-complete Result mapping cannot claim exact source provenance")
        if (
            self.construct_admissibility == "accepted_synonym"
            and not self.construct_synonym_rationale
        ):
            raise ValueError("accepted construct synonym requires a rationale")
        if (
            self.construct_admissibility == "accepted_synonym"
            and self.reviewed_by.kind.value != "human"
        ):
            raise ValueError("accepted construct synonym requires human review")
        return self


class SubmitResultMappingReviewRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    proposal_token: Identifier
    idempotency_key: Identifier
    mappings: tuple[ResultMappingReviewInput, ...] = Field(min_length=1)


class ConfirmRunDefinitionRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    confirmed_by: Actor


class SearchQueryEnvelope(SearchQueryFields):
    """Transport-safe query shape; semantic FTS validation runs inside the handler."""


class SearchEvidenceRequest(FrozenModel):
    """Question-scoped v3 semantic Evidence search under an issued session token."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier = Field(description="Run identifier returned by prepare_run.")
    query: SearchQuery = Field(
        description=(
            "Structured lexical terms and safe metadata refinements; raw FTS syntax is rejected."
        )
    )
    work_token: WorkToken = Field(
        description=("Copy the opaque token from the current submit_question_step WorkItem.")
    )
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    expected_navigation_state_hash: ContentHash
    continuation: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description="Opaque cursor returned by the preceding page; omit on the first bounded page.",
        examples=["eyJwYXlsb2FkIjoi..."],
    )
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    intent_id: Identifier
    attempt_id: Identifier
    supersede_attempt_id: Identifier | None = None
    supersession_rationale: str | None = None
    continue_reason: SearchContinuationReason | None = None
    continue_rationale: str | None = None

    @model_validator(mode="after")
    def validate_navigation(self) -> SearchEvidenceRequest:
        if (self.supersede_attempt_id is None) != (self.supersession_rationale is None):
            raise ValueError("explicit query supersession requires ID and rationale together")
        if self.supersession_rationale is not None and not self.supersession_rationale.strip():
            raise ValueError("supersession rationale cannot be blank")
        return self


class ReadEvidenceRequest(FrozenModel):
    """Question-scoped bounded read under the exact v3 session projection."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier = Field(description="Run identifier returned by prepare_run.")
    work_token: WorkToken = Field(
        description=(
            "Copy the opaque token from the current submit_question_step WorkItem; "
            "it binds the exact session, frontier, Result, Domain, and question scope."
        )
    )
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    expected_navigation_state_hash: ContentHash
    batch: EvidenceReadBatchRequest


class SubmitEvidenceReviewRequest(FrozenModel):
    """Append one exhaustive v3 triage partition for an issued question page."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    expected_navigation_state_hash: ContentHash
    submission_id: Identifier
    page_handles: tuple[str, ...] = Field(min_length=1)
    triage_revisions: tuple[V3CandidateTriageRevision, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> SubmitEvidenceReviewRequest:
        if len(self.page_handles) != len(set(self.page_handles)):
            raise ValueError("page review partition cannot repeat a page handle")
        if self.idempotency_key != self.submission_id:
            raise ValueError("v3 review idempotency_key must equal submission_id")
        return self


class SubmitQuestionStepRequest(FrozenModel):
    """Commit exactly one active v3 question answer or diagnostic stop."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    frontier_entry_hash: ContentHash
    answer: SQAnswerCategory | None = None
    rationale: str | None = None
    diagnostic_stop: bool = False
    evidence_bundle: QuestionEvidenceBundleBinding | None = None

    @model_validator(mode="after")
    def validate_exclusive_outcome(self) -> SubmitQuestionStepRequest:
        if (self.answer is None) == (self.diagnostic_stop is False):
            raise ValueError("submit_question_step requires exactly one answer or diagnostic_stop")
        if self.answer is not None and not (self.rationale and self.rationale.strip()):
            raise ValueError("a question answer requires a rationale")
        if self.diagnostic_stop and self.rationale:
            raise ValueError("diagnostic_stop cannot carry an answer rationale")
        if self.answer is not None and self.evidence_bundle is None:
            raise ValueError(
                "a question answer requires an engine-verified Evidence Bundle binding"
            )
        if self.diagnostic_stop and self.evidence_bundle is not None:
            raise ValueError("diagnostic_stop cannot carry an Evidence Bundle")
        return self


class CorrectQuestionStepRequest(FrozenModel):
    """Replace one effective v3 question answer using its issued correction token."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    prior_step_hash: ContentHash
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)
    evidence_bundle: QuestionEvidenceBundleBinding


class QuestionVisualProvenanceInput(FrozenModel):
    """Exact current review linkage required to retain a visual-only item."""

    transcription: RecordReference
    candidate_id: Identifier
    authorizing_review: RecordReference
    review_span_id: Identifier


class MaterializeQuestionEvidenceBundleRequest(FrozenModel):
    """Ask the engine to freeze the active question's v3 evidence bundle.

    This accepts only engine-issued scope and revision identities. In
    particular, callers cannot select supporting/contradicting polarity or a
    no-information basis; those are replayed from current durable evidence.
    """

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    frontier_entry_hash: ContentHash
    expected_navigation_state_hash: ContentHash
    review_revisions: tuple[EvidenceReviewRevisionInput, ...] = ()
    passages: tuple[EvidencePassageInput, ...] = ()
    visual_transcriptions: tuple[QuestionVisualProvenanceInput, ...] = ()

    @model_validator(mode="after")
    def validate_question_evidence_inputs(self) -> MaterializeQuestionEvidenceBundleRequest:
        if any(
            review.result_id != self.result_id
            or review.domain_id != self.domain_id
            or review.sq_id != self.question_id
            for review in self.review_revisions
        ):
            raise ValueError(
                "question bundle reviews must bind the active Result, Domain, and question"
            )
        if any(passage.question_ids != (self.question_id,) for passage in self.passages):
            raise ValueError("question bundle passages must bind exactly the active question")
        if len({(review.candidate_id, review.sq_id) for review in self.review_revisions}) != len(
            self.review_revisions
        ):
            raise ValueError("question bundle has multiple current reviews for one candidate")
        return self


class SubmitSourceChronologyReviewRequest(FrozenModel):
    """Attributable chronology fact for one immutable Source/Parse revision."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    parse_output_hash: ContentHash
    constraint: ChronologyConstraint
    status: V3ChronologyStatus
    rationale: str = Field(min_length=1)
    evidence_read_receipt: str = Field(min_length=1, max_length=8192)


class SubmitEvidenceStageOutcomeRequest(FrozenModel):
    """Reducer-validated outcome for one exact active v3 evidence stage."""

    contract_version: Literal["3.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    expected_navigation_state_hash: ContentHash
    submission: V3EvidenceStageOutcomeSubmission

    @model_validator(mode="after")
    def validate_scope(self) -> SubmitEvidenceStageOutcomeRequest:
        if self.submission.question_id != self.question_id:
            raise ValueError("stage outcome must bind the active question")
        return self


class InspectVisualCandidateRequest(FrozenModel):
    run_id: Identifier
    candidate_id: Identifier
    result_id: Identifier | None = None
    current_render: VisualRenderRequest | None = None
    still_ambiguous: bool = True


class SubmitSourceRoleReviewRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    # Source-id-scoped RunProposalSelection entries — one shared disposition
    # shape across Result, Registry, and Source-role candidates (#119).
    selections: tuple[RunProposalSelection, ...] = Field(min_length=1)


class SubmitResultResolutionRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result: Result
    estimate: Estimate
    provenance_note: str = Field(min_length=1)


class OperationResponse(FrozenModel):
    # ``next_permitted_action`` was the pre-expand field name.  Accept it on
    # input for old Harnesses, while emitting the canonical ``next_action``
    # envelope field for every new response.
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    operation_id: Identifier
    ledger_cursor: str = Field(min_length=1)
    affected_scope: tuple[Identifier, ...]
    condition: WorkflowCondition
    committed: bool
    summary: str = Field(default="", min_length=0)
    warnings: tuple[str, ...] = ()
    next_action: NextAction | RunOperation | None = Field(
        default=None,
        validation_alias=AliasChoices("next_action", "next_permitted_action"),
    )
    error: OperationError | None = None

    @model_validator(mode="after")
    def normalize_next_action(self) -> OperationResponse:
        if not self.summary:
            object.__setattr__(
                self,
                "summary",
                {
                    WorkflowCondition.CONFIRMATION_REQUIRED: (
                        "Run definition confirmation is required."
                    ),
                    WorkflowCondition.AGENT_WORK_REQUIRED: (
                        "The next bounded Run work item is ready."
                    ),
                    WorkflowCondition.RUN_BLOCKED: (
                        "The Run is blocked pending a correctable action."
                    ),
                    WorkflowCondition.RUN_COMPLETE: "The Run is complete.",
                    WorkflowCondition.RUN_INTEGRITY_FAILURE: "Run integrity could not be verified.",
                }.get(self.condition, "Run operation completed."),
            )
        action = self.next_action
        if isinstance(action, RunOperation):
            run_id = getattr(self, "run_id", None)
            work_item = getattr(self, "work_item", None)
            proposal = getattr(self, "proposal", None)
            arguments = NextActionArguments(
                run_id=run_id,
                work_token=(work_item.work_token if work_item is not None else None),
                proposal_token=(proposal.proposal_token if proposal is not None else None),
                result_id=(work_item.result_id if work_item is not None else None),
                domain_id=(work_item.domain_id if work_item is not None else None),
            )
            action = NextAction(
                operation=action,
                reason="Continue with the operation selected by the Run ledger.",
                arguments=arguments,
            )
            object.__setattr__(self, "next_action", action)
        elif action is not None and action.arguments.run_id is None:
            run_id = getattr(self, "run_id", None)
            if run_id is not None:
                object.__setattr__(
                    self,
                    "next_action",
                    action.model_copy(
                        update={"arguments": action.arguments.model_copy(update={"run_id": run_id})}
                    ),
                )
        terminal_run_state = getattr(self, "run_state", None) in {
            RunState.COMPLETE,
            RunState.INTEGRITY_FAILED,
            RunState.RETIRED,
        }
        terminal = (
            self.condition
            in {
                WorkflowCondition.RUN_COMPLETE,
                WorkflowCondition.RUN_INTEGRITY_FAILURE,
            }
            or terminal_run_state
        )
        if terminal and self.next_action is not None:
            # A submission may commit the final checkpoint while retaining
            # the historical ``accepted`` condition.  The Run state is the
            # terminal authority, so suppress the stale successor rather
            # than rejecting an otherwise valid committed response.
            object.__setattr__(self, "next_action", None)
        if not terminal:
            if self.next_action is None:
                # Read-only operations have no explicit successor in their
                # legacy constructors.  A status-preserving continuation is
                # the only safe default and remains engine-authored.
                run_id = getattr(self, "run_id", None)
                operation = (
                    RunOperation.SUBMIT_RUN_PROPOSAL
                    if self.condition is WorkflowCondition.CONFIRMATION_REQUIRED
                    else getattr(getattr(self, "work_item", None), "operation", None)
                    or RunOperation.CONTINUE_RUN
                )
                work_item = getattr(self, "work_item", None)
                proposal = getattr(self, "proposal", None)
                object.__setattr__(
                    self,
                    "next_action",
                    NextAction(
                        operation=operation,
                        reason=(
                            "Submit the Run proposal for confirmation."
                            if operation is RunOperation.SUBMIT_RUN_PROPOSAL
                            else "Continue the current Run from its durable checkpoint."
                        ),
                        arguments=NextActionArguments(
                            run_id=run_id,
                            work_token=(work_item.work_token if work_item is not None else None),
                            proposal_token=(
                                proposal.proposal_token if proposal is not None else None
                            ),
                            result_id=(work_item.result_id if work_item is not None else None),
                            domain_id=(work_item.domain_id if work_item is not None else None),
                        ),
                    ),
                )
        return self

    @property
    def next_permitted_action(self) -> RunOperation | None:
        """Compatibility view for pre-expand callers."""

        return (
            self.next_action.operation
            if isinstance(self.next_action, NextAction)
            else self.next_action
        )


class PrepareRunResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    initialization: ProjectInitialization | None = None
    proposal: RunProposal | None = None
    integrity: IntegrityFailure | None = None


class RunStatusResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    result_states: tuple[ResultStatus, ...] = ()
    progress: RunProgress | None = None
    integrity: IntegrityFailure | None = None


GetRunStatusResponse = RunStatusResponse


class ContinueRunResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    directive: RunDirective
    work_item: WorkItem | None = None
    progress: RunProgress | None = None
    integrity: IntegrityFailure | None = None


class ResultControlResponse(OperationResponse):
    run_id: Identifier
    run_state: RunState
    result_id: Identifier | None = None
    result_state: ResultState | None = None
    result_order: tuple[Identifier, ...] = ()


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
    evidence_navigation_contract_version: Literal["3.0.0"] = DOMAIN_EVIDENCE_CONTRACT_VERSION
    page: EvidenceSearchPage
    coverage_progress: dict[str, object]


def _compact_operation_payload(response: Any) -> dict[str, Any]:
    payload = response.model_dump(mode="json", exclude_none=True)
    page = getattr(response, "page", None)
    if page is not None and hasattr(page, "model_facing_payload") and "page" in payload:
        payload["page"] = page.model_facing_payload()
    payload.pop("next_action", None)
    if "coverage_progress" in payload:
        payload["coverage_progress"] = compact_coverage_progress(payload["coverage_progress"])
    if not payload.get("summary"):
        payload.pop("summary", None)
    if not payload.get("warnings"):
        payload.pop("warnings", None)
    return payload


def finalize_search_evidence_response(response: SearchEvidenceResponse) -> SearchEvidenceResponse:
    """Jointly settle the one returned Search page and its MCP envelope.

    This is deliberately downstream of stable packing: a reservation overrun
    is an operational invariant, never an instruction to move a boundary.
    """
    current = response
    bytes_ = tokens = 0
    for _ in range(16):
        page = current.page.model_copy(
            update={
                "serialized_response_bytes": bytes_,
                "estimated_response_tokens": tokens,
            }
        )
        current = current.model_copy(update={"page": page})
        payload = _compact_operation_payload(current)
        payload["response_accounting"] = {
            "estimator_id": "utf8-byte-div4-ceil:v1",
            "scope": "complete_mcp_operation_envelope",
            "serialized_response_bytes": bytes_,
            "estimated_response_tokens": tokens,
        }
        measured = len(canonical_json_bytes(payload))
        estimated = (measured + 3) // 4
        if (measured, estimated) == (bytes_, tokens):
            reservation = current.page.traversal_cost
            if (
                measured > reservation.response_bytes_upper_bound
                or estimated > reservation.estimated_tokens_upper_bound
            ):
                raise OperationalRetrievalFailure(
                    "Search returned envelope exceeds its stable packing reservation"
                )
            return current
        bytes_, tokens = measured, estimated
    raise RuntimeError("Search returned-envelope accounting did not stabilize")


def model_facing_operation_payload(response: Any) -> dict[str, Any]:
    """Build the exact compact v2 operation envelope used on the MCP wire.

    Search packing calls this same composition function before a response is
    returned.  Keeping it here prevents a page-local estimate from drifting
    away from the operation envelope once coverage progress and accounting are
    attached by the MCP adapter.
    """

    payload = _compact_operation_payload(response)
    bytes_ = tokens = 0
    for _ in range(16):
        payload["response_accounting"] = {
            "estimator_id": "utf8-byte-div4-ceil:v1",
            "scope": "complete_mcp_operation_envelope",
            "serialized_response_bytes": bytes_,
            "estimated_response_tokens": tokens,
        }
        measured = len(canonical_json_bytes(payload))
        estimated = (measured + 3) // 4
        if (measured, estimated) == (bytes_, tokens):
            return payload
        bytes_, tokens = measured, estimated
    raise RuntimeError("v2 MCP operation-envelope accounting did not stabilize")


class ReadEvidenceResponse(OperationResponse):
    run_id: Identifier
    evidence_navigation_contract_version: Literal["3.0.0"] = DOMAIN_EVIDENCE_CONTRACT_VERSION
    page: EvidenceReadBatchPage


class VisualInspectionArguments(FrozenModel):
    run_id: Identifier
    candidate_id: Identifier
    result_id: Identifier | None = None


class VisualInspectionPath(FrozenModel):
    """Bounded, provenance-tied handoff to the visual inspection tool."""

    unit_id: Identifier
    source_id: Identifier
    page: int = Field(ge=1)
    candidate_id: Identifier
    next_tool: Literal["inspect_visual_candidate"] = "inspect_visual_candidate"
    next_arguments: VisualInspectionArguments


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


class SubmitProposalDiscoveryReviewResponse(SubmissionResponse):
    proposal: RunProposal | None = None


class SubmitResultMappingReviewResponse(SubmissionResponse):
    proposal: RunProposal | None = None


class SubmitSourceRoleReviewResponse(SubmissionResponse):
    pass


class SubmitResultResolutionResponse(SubmissionResponse):
    result_spec: ResultSpecRevision | None = None


class SubmitEvidenceReviewResponse(SubmissionResponse):
    domain_id: Identifier
    workflow_state_hash: ContentHash
    outstanding_triage_candidate_ids: tuple[Identifier, ...] = ()


class SubmitQuestionStepResponse(SubmissionResponse):
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    frontier_entry_hash: ContentHash | None = None
    diagnostic_terminal: bool = False
    correction_token: WorkToken | None = None
    evidence_recovery_token: WorkToken | None = None


class CorrectQuestionStepResponse(SubmissionResponse):
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    frontier_entry_hash: ContentHash | None = None
    invalidated_question_ids: tuple[Identifier, ...] = ()
    correction_token: WorkToken | None = None


class MaterializeQuestionEvidenceBundleResponse(SubmissionResponse):
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    navigation_state_hash: ContentHash
    evidence_bundle: QuestionEvidenceBundleBinding


class SubmitSourceChronologyReviewResponse(SubmissionResponse):
    domain_id: Identifier
    question_id: Identifier
    source_id: Identifier
    inventory_revision_id: Identifier
    inventory_revision_hash: ContentHash


class SubmitEvidenceStageOutcomeResponse(SubmissionResponse):
    domain_id: Identifier
    question_id: Identifier
    navigation_state_hash: ContentHash
    progress: dict[str, object]


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
        operation=RunOperation.REPRIORITIZE_RESULTS,
        request_type=ReprioritizeResultsRequest,
        response_type=ResultControlResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.WITHDRAW_RESULT,
        request_type=WithdrawResultRequest,
        response_type=ResultControlResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.REOPEN_RESULT,
        request_type=ReopenResultRequest,
        response_type=ResultControlResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
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
        operation=RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
        request_type=SubmitProposalDiscoveryReviewRequest,
        response_type=SubmitProposalDiscoveryReviewResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.STALE,
            WorkflowCondition.RETRY,
        ),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
        request_type=SubmitResultMappingReviewRequest,
        response_type=SubmitResultMappingReviewResponse,
        expected_conditions=(
            WorkflowCondition.ACCEPTED,
            WorkflowCondition.STALE,
            WorkflowCondition.RETRY,
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
        operation=RunOperation.SUBMIT_SOURCE_ROLE_REVIEW,
        request_type=SubmitSourceRoleReviewRequest,
        response_type=SubmitSourceRoleReviewResponse,
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
        operation=RunOperation.SUBMIT_EVIDENCE_REVIEW,
        request_type=SubmitEvidenceReviewRequest,
        response_type=SubmitEvidenceReviewResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_EVIDENCE_STAGE_OUTCOME,
        request_type=SubmitEvidenceStageOutcomeRequest,
        response_type=SubmitEvidenceStageOutcomeResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.MATERIALIZE_QUESTION_EVIDENCE_BUNDLE,
        request_type=MaterializeQuestionEvidenceBundleRequest,
        response_type=MaterializeQuestionEvidenceBundleResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_QUESTION_STEP,
        request_type=SubmitQuestionStepRequest,
        response_type=SubmitQuestionStepResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.CORRECT_QUESTION_STEP,
        request_type=CorrectQuestionStepRequest,
        response_type=CorrectQuestionStepResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
    OperationContract(
        operation=RunOperation.SUBMIT_SOURCE_CHRONOLOGY_REVIEW,
        request_type=SubmitSourceChronologyReviewRequest,
        response_type=SubmitSourceChronologyReviewResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
)
