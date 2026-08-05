"""Typed public contracts for the lean RunEngine boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import ConsiderationDisposition, EvidenceCoverageState
from rob2_kit.domain.results import Estimate, Result, ResultSpecRevision
from rob2_kit.domain.revisions import (
    Actor,
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
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
from rob2_kit.evidence.errors import RetrievalErrorCode
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    EvidenceContext,
    ReadContextMode,
    SearchPage,
    SearchQuery,
    SearchQueryFields,
)
from rob2_kit.evidence.visual import (
    VisualCandidate,
    VisualRenderRequest,
)
from rob2_kit.evidence.workflow import ExecutedSearchQuery, SearchCoverageReceipt, SearchPassKind
from rob2_kit.ingestion.project import OutcomeTarget, ProjectInitialization, ResultCandidate
from rob2_kit.logic.packs import GuidanceItem
from rob2_kit.registry import RegistryCandidate

CONTRACT_VERSION = "1.0.0"


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
    CORRECT_DOMAIN_ANSWERS = "correct_domain_answers"


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
    terminal_result_counts: dict[str, int] = Field(default_factory=dict)
    report_locations: tuple[str, ...] = ()


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
        "authorization_required",
        "material_ambiguity",
    ]
    detail: str = Field(min_length=1)
    recovery: tuple[str, ...] = Field(min_length=1)
    correlation_id: Identifier | None = None


class RetrievalError(FrozenModel):
    code: RetrievalErrorCode
    field: str | None = None
    message: str = Field(min_length=1)
    recovery: tuple[str, ...] = Field(min_length=1)

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


class WorkItem(FrozenModel):
    work_item_id: Identifier
    work_token: WorkToken
    operation: RunOperation
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    dependency_fingerprint: ContentHash


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
        default=None, description="Optional concise basis for the disposition."
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
        }:
            raise ValueError("passage disposition must accept the selected passage")
        return self


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
    accepted: bool = True
    removed: bool = False
    exclusion_reason: str | None = Field(
        default=None,
        validation_alias=AliasChoices("exclusion_reason", "reason"),
        description=(
            "Human-readable reason for explicitly excluding this Trial × Outcome target. "
            "Required when accepted is false."
        ),
    )

    @model_validator(mode="after")
    def validate_disposition(self) -> RunProposalSelection:
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


class GetWorkContextRequest(FrozenModel):
    run_id: Identifier
    work_token: WorkToken
    include_source_details: bool = False


class SubmitRunProposalRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    selections: tuple[RunProposalSelection, ...] = ()
    ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    unresolved_ambiguities: tuple[RunProposalAmbiguity, ...] = ()
    correction: str | None = Field(
        default=None,
        description=(
            "Optional bounded natural-language correction. It must name issued Trial, "
            "Outcome-target, and Result identifiers; unsupported prose is refused."
        ),
    )

    @model_validator(mode="after")
    def validate_correction(self) -> SubmitRunProposalRequest:
        if self.correction is not None and not self.correction.strip():
            raise ValueError("correction cannot be blank")
        return self


class ConfirmRunDefinitionRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    proposal_token: Identifier
    idempotency_key: Identifier
    confirmed_by: Actor


class SearchQueryEnvelope(SearchQueryFields):
    """Transport-safe query shape; semantic FTS validation runs inside the handler."""


class SearchEvidenceRequest(FrozenModel):
    run_id: Identifier = Field(description="Run identifier returned by prepare_run.")
    query: SearchQuery = Field(
        description=(
            "Structured lexical terms and safe metadata refinements; raw FTS syntax is rejected."
        )
    )
    work_token: WorkToken = Field(
        description=(
            "Copy the opaque token from the current submit_domain_evidence WorkItem; "
            "example token:domain-evidence."
        )
    )
    result_id: Identifier | None = Field(
        default=None,
        description="Optional Result identifier; it must match the active WorkToken scope.",
        examples=["result:primary"],
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description="Opaque cursor returned by the preceding page; omit on the first bounded page.",
        examples=["eyJwYXlsb2FkIjoi..."],
    )
    sq_id: Identifier = Field(
        description="Signaling-question identifier for the current evidence pass.",
        examples=["sq:randomization"],
    )
    pass_kind: SearchPassKind | None = Field(
        default=None,
        description="Search pass classification; guidance_seed requires seed_family.",
    )
    seed_family: Identifier | None = Field(
        default=None,
        description="Stable family identifier required only for guidance_seed passes.",
    )

    @model_validator(mode="after")
    def validate_seed_relation(self) -> SearchEvidenceRequest:
        guidance = self.pass_kind is SearchPassKind.GUIDANCE_SEED
        if guidance and self.seed_family is None:
            raise ValueError("guidance_seed pass_kind requires seed_family")
        if not guidance and self.seed_family is not None:
            raise ValueError("seed_family is only valid with guidance_seed pass_kind")
        return self


class ReadEvidenceRequest(FrozenModel):
    run_id: Identifier = Field(description="Run identifier returned by prepare_run.")
    unit_id: Identifier = Field(
        description="Canonical unit identifier issued by search_evidence.",
        examples=["unit:report-p1-b2"],
    )
    work_token: WorkToken = Field(
        description=(
            "Copy the opaque token from the current submit_domain_evidence WorkItem; "
            "the token binds Trial/Result/Domain scope."
        )
    )
    result_id: Identifier | None = Field(
        default=None,
        description="Optional Result identifier; it must match the active WorkToken scope.",
        examples=["result:primary"],
    )
    sq_id: Identifier = Field(
        description="Signaling-question scope; it must match any active question filter.",
        examples=["sq:randomization"],
    )
    mode: ReadContextMode = Field(
        default=ReadContextMode.UNIT,
        description="Read mode: unit, same-zone neighbors, or same-zone section continuation.",
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description=(
            "Opaque section cursor returned by a prior bounded section read; omit initially."
        ),
        examples=["eyJwYXlsb2FkIjoi..."],
    )


class InspectVisualCandidateRequest(FrozenModel):
    run_id: Identifier
    candidate_id: Identifier
    result_id: Identifier | None = None
    current_render: VisualRenderRequest | None = None
    still_ambiguous: bool = True


class SourceClassificationInput(FrozenModel):
    source_id: Identifier = Field(description="Source ID issued in get_work_context.sources.")
    roles: tuple[SourceRole, ...] = Field(
        min_length=1, description="One or more schema-enumerated roles; the key is plural roles."
    )


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
    items: tuple[RecordReference, ...] = Field(
        default=(),
        description=(
            "Legacy evidence references. Use this branch only when passages is empty; "
            "do not combine with evidence_by_question, candidate_dispositions, or conflicts."
        ),
    )
    passages: tuple[EvidencePassageInput, ...] = Field(
        default=(),
        description=(
            "Preferred exact canonical passages. Mutually exclusive with legacy items, "
            "evidence_by_question, candidate_dispositions, and conflicts."
        ),
    )
    coverage_state: EvidenceCoverageState = Field(
        default=EvidenceCoverageState.COMPLETE,
        description=("Coverage enum: complete, complete_with_limitations, or incomplete."),
    )
    coverage_limitations: tuple[str, ...] = Field(
        default=(),
        description=(
            "Material source/search limitations. The field is named coverage_limitations "
            "(not limitation); required for incomplete and allowed for complete_with_limitations."
        ),
    )
    no_information_basis: bool = Field(
        default=False,
        description=(
            "Set true only when complete search receipts and readable coverage justify "
            "no information."
        ),
    )
    conflicts: tuple[tuple[Identifier, ...], ...] = Field(
        default=(),
        description=(
            "Material candidate-ID conflicts for the legacy evidence branch; mutually exclusive "
            "with passages."
        ),
    )
    # New evidence-first fields.  They are optional for compatibility with
    # synthetic tracer submissions that intentionally carry an empty bundle.
    evidence_by_question: dict[Identifier, tuple[RecordReference, ...]] = Field(
        default_factory=dict,
        description=("Legacy question-to-reference mapping; mutually exclusive with passages."),
    )
    candidate_dispositions: tuple[EvidenceConsiderationInput, ...] = Field(
        default=(),
        description=("Legacy candidate disposition records; mutually exclusive with passages."),
    )
    coverage_receipts: tuple[SearchCoverageReceipt, ...] = Field(
        default=(),
        description=(
            "Complete typed search receipts supplied by search_evidence; omit partial receipts."
        ),
    )
    project_rules: tuple[RecordReference, ...] = Field(
        default=(), description="Issued project-rule references that materially guide this bundle."
    )
    actor: Actor | None = None

    @model_validator(mode="after")
    def validate_evidence_inputs(self) -> SubmitDomainEvidenceRequest:
        if self.passages and (
            self.items or self.evidence_by_question or self.candidate_dispositions or self.conflicts
        ):
            raise ValueError(
                "passages are mutually exclusive with legacy evidence inputs: clear items, "
                "evidence_by_question, candidate_dispositions, and conflicts, or submit the "
                "legacy branch without passages"
            )
        return self


class SQAnswerInput(FrozenModel):
    question_id: Identifier = Field(
        description="Active question ID from domain_context.active_question_ids."
    )
    answer: SQAnswerCategory = Field(description="One canonical lowercase answer category.")
    rationale: str = Field(min_length=1)


class FinalJudgmentInput(FrozenModel):
    """A justified departure from an engine-derived Domain judgment."""

    domain_id: Identifier
    judgment: JudgmentLevel
    alternative: JudgmentLevel
    material_bias_rationale: str = Field(min_length=1)
    cited_evidence: tuple[RecordReference, ...] = Field(min_length=1)


class SubmitDomainAnswersRequest(FrozenModel):
    contract_version: Literal["1.0.0"]
    run_id: Identifier
    work_token: WorkToken
    idempotency_key: Identifier
    result_id: Identifier
    domain_id: Identifier
    answers: tuple[SQAnswerInput, ...] = Field(min_length=1)
    assessor_inputs: dict[Identifier, bool] = Field(
        default_factory=dict,
        description=(
            "Structured Logic-pack inputs required for the Overall judgment. "
            "For example, submit input:combined-concerns only when the "
            "completed Domain judgments make it applicable."
        ),
    )
    final_judgment_departures: tuple[FinalJudgmentInput, ...] = ()
    project_rules: tuple[RecordReference, ...] = ()
    actor: Actor | None = None


class CorrectDomainAnswersRequest(SubmitDomainAnswersRequest):
    """A successor answer submission bound to an engine-issued correction token."""


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
    visual_inspection: VisualInspectionPath | None = None


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


class SubmitSourceClassificationResponse(SubmissionResponse):
    pass


class SubmitResultResolutionResponse(SubmissionResponse):
    result_spec: ResultSpecRevision | None = None


class SubmitDomainEvidenceResponse(SubmissionResponse):
    domain_id: Identifier
    evidence_bundles: tuple[RecordReference, ...] = ()
    consideration_manifests: tuple[RecordReference, ...] = ()
    coverage_receipts: tuple[RecordReference, ...] = ()


class SubmitDomainAnswersResponse(SubmissionResponse):
    domain_id: Identifier
    answer_revisions: tuple[RecordReference, ...] = ()
    judgments: tuple[RecordReference, ...] = ()
    correction_token: WorkToken | None = None


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
    OperationContract(
        operation=RunOperation.CORRECT_DOMAIN_ANSWERS,
        request_type=CorrectDomainAnswersRequest,
        response_type=SubmitDomainAnswersResponse,
        expected_conditions=(WorkflowCondition.ACCEPTED, WorkflowCondition.STALE),
    ),
)
