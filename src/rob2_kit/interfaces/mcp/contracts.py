"""Typed public FastMCP receipts.

The application keeps its durable projection as JSON. This module is the
transport boundary: Pydantic models validate the projection and generate the
same schemas advertised to MCP clients.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Generic, Literal, TypeVar, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    model_validator,
)
from pydantic.types import PositiveInt

from rob2_kit.application.contracts import TOOL_NAMES
from rob2_kit.application.source_handles import public_source_references
from rob2_kit.models import Answer, Judgment, QuerySuggestion, ResponseFramework
from rob2_kit.workflow_models import (
    AssessableTargetRelation,
    ComparativeEffectResult,
    DomainCounterevidence,
    DomainId,
    EvidenceHandle,
    GroupBoundValuesResult,
    Identity,
    MissingDataSemantics,
    NormalizedCoordinate,
    OmissionDecision,
    QuestionId,
    RegistryOutcome,
    RelativePath,
    ReportedEndpoint,
    ResultClarity,
    ResultTarget,
    ReviewPurpose,
    SearchReceiptHandle,
    SourceHandle,
    SourceOrigin,
    SourceRole,
    TrialId,
    UnavailableResult,
    WorkingPremiseStatus,
)


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PageNumber = Annotated[StrictInt, Field(ge=1)]


class SaveProposalAction(PublicModel):
    operation: Literal["save_proposal"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt


class ValidateProposalAction(PublicModel):
    operation: Literal["validate_proposal"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["results", "assessments"], ...]


class PrepareBatchAction(PublicModel):
    operation: Literal["prepare_batch"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["requested_outcome", "trial_labels"], ...]


class GetDomainContextAction(PublicModel):
    operation: Literal["get_domain_context"]
    authority: Literal["host"]
    trial_id: TrialId
    domain_id: DomainId


class SaveDomainJudgmentAction(PublicModel):
    operation: Literal["save_domain_judgment"]
    authority: Literal["host"]
    trial_id: TrialId
    domain_id: DomainId
    expected_revision: NonNegativeInt


class ValidateDomainAssessmentAction(PublicModel):
    operation: Literal["validate_domain_assessment"]
    authority: Literal["host"]
    trial_id: TrialId
    domain_id: DomainId
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["answers", "revision_basis"], ...]
    supersedes: Identity | None = None


class FinalizeBatchAction(PublicModel):
    operation: Literal["finalize_batch"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt


class ReviewTrialAction(PublicModel):
    model_config = ConfigDict(title="Trial review")

    operation: Literal["review_trial"]
    authority: Literal["host"]
    trial_id: TrialId
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["request"], ...] | None = None

    @model_validator(mode="after")
    def caller_inputs_are_complete(self) -> ReviewTrialAction:
        if self.caller_inputs not in (None, ("request",)):
            raise ValueError("review_trial caller_inputs must be omitted or [request]")
        return self


class CloseTrialAction(PublicModel):
    model_config = ConfigDict(title="Closure")

    operation: Literal["close_trial"]
    authority: Literal["host"]
    trial_id: TrialId
    expected_revision: NonNegativeInt
    review_reference: Identity


class TrialReviewAction(PublicModel):
    """Compatibility validator for the former combined review/close action."""

    operation: Literal["review_trial", "close_trial"]
    authority: Literal["host"]
    trial_id: TrialId
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["request"], ...] | None = Field(
        default=None,
        description=(
            "Omit for a normal review or an automatically terminal unavailable or unsupported "
            'Result. Use ["request"] only for a genuine needs_input or failed blocker.'
        ),
        examples=[None, ["request"]],
    )
    review_reference: Identity | None = None

    @model_validator(mode="after")
    def match_action_inputs(self) -> TrialReviewAction:
        if self.operation == "review_trial":
            if self.review_reference is not None or self.caller_inputs not in (None, ("request",)):
                raise ValueError("review_trial accepts no fields or caller_inputs=request only")
        elif self.caller_inputs is not None or self.review_reference is None:
            raise ValueError("close_trial requires its review_reference only")
        return self


class ResearcherReviewAction(PublicModel):
    operation: Literal["researcher_review"]
    authority: Literal["researcher"]
    reference: Identity
    purpose: ReviewPurpose


NextAction = Annotated[
    PrepareBatchAction
    | SaveProposalAction
    | ValidateProposalAction
    | GetDomainContextAction
    | ValidateDomainAssessmentAction
    | SaveDomainJudgmentAction
    | ReviewTrialAction
    | CloseTrialAction
    | FinalizeBatchAction
    | ResearcherReviewAction,
    Field(discriminator="operation"),
]


class PublicHead(PublicModel):
    phase: Literal["empty", "proposal", "assessment", "ready_to_finalize", "finalized"]
    state_revision: NonNegativeInt
    next_action: NextAction | None
    authoritative_wording: str = Field(min_length=1)


class RepairDefect(PublicModel):
    path: str = Field(min_length=1)
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ConflictData(PublicModel):
    expected_revision: NonNegativeInt
    current_revision: NonNegativeInt


class DomainContextRecoveryArguments(PublicModel):
    trial_id: TrialId
    domain_id: DomainId
    cursor: StrictStr = Field(min_length=1)
    max_response_bytes: StrictInt = Field(
        ge=4096,
        le=131_072,
        description="Byte budget for the continued page; valid range 4096–131072.",
        json_schema_extra={"examples": [65_536]},
    )


class DomainContextRecovery(PublicModel):
    operation: Literal["get_domain_context"]
    arguments: DomainContextRecoveryArguments


class ConditionData(PublicModel):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    action: str | None = Field(default=None, min_length=1)


class DomainContextDeliveryCondition(ConditionData):
    recovery: DomainContextRecovery | None = None


class SearchCursorStaleCondition(PublicModel):
    code: Literal["search_cursor_stale"]
    detail: str = Field(min_length=1)


class SearchCursorExpiredCondition(PublicModel):
    code: Literal["search_cursor_expired"]
    detail: str = Field(min_length=1)


class SearchInvalidRequestCondition(PublicModel):
    code: Literal["invalid_request"]
    detail: str = Field(min_length=1)


SearchCursorCondition = Annotated[
    SearchCursorStaleCondition | SearchCursorExpiredCondition | SearchInvalidRequestCondition,
    Field(discriminator="code"),
]

DataT = TypeVar("DataT", bound=PublicModel)


class SuccessReceipt(PublicModel, Generic[DataT]):
    outcome: Literal["success"]
    head: PublicHead
    data: DataT


class ReviewReceipt(PublicModel, Generic[DataT]):
    outcome: Literal["review_required"]
    head: PublicHead
    data: DataT


class RepairReceipt(PublicModel):
    outcome: Literal["repair"]
    head: PublicHead
    repairs: tuple[RepairDefect, ...] = Field(min_length=1)


class ConflictReceipt(PublicModel):
    outcome: Literal["conflict"]
    head: PublicHead
    conflict: ConflictData


class ConditionReceipt(PublicModel, Generic[DataT]):
    outcome: Literal["condition"]
    head: PublicHead
    condition: DataT


def _receipt(
    data: Any,
    condition: Any = ConditionData,
    *,
    success: bool = True,
    review: bool = False,
    repair: bool = False,
    conflict: bool = False,
) -> Any:
    variants: list[Any] = [ConditionReceipt[condition]]
    if success:
        variants.insert(0, SuccessReceipt[data])
    if review:
        variants.append(ReviewReceipt[data])
    if repair:
        variants.append(RepairReceipt)
    if conflict:
        variants.append(ConflictReceipt)
    union = variants[0]
    for variant in variants[1:]:
        union = union | variant
    return Annotated[union, Field(discriminator="outcome")]


_RECEIPT_OPTIONS: Final = {
    "prepare_batch": {"conflict": True},
    "get_status": {},
    "save_working_checkpoint": {},
    "list_sources": {},
    "search_sources": {},
    "search_sources_batch": {},
    "read_pages": {},
    "select_text_evidence": {},
    "render_page": {},
    "select_visual_evidence": {},
    "validate_proposal": {"repair": True, "conflict": True},
    "save_proposal": {"review": True, "repair": True, "conflict": True},
    "request_proposal_approval": {},
    "get_domain_context": {},
    "validate_domain_assessment": {"repair": True, "conflict": True},
    "save_domain_judgment": {"repair": True, "conflict": True},
    "review_trial": {"conflict": True},
    "close_trial": {"conflict": True},
    "finalize_batch": {"conflict": True},
}


class FileVisibilityCondition(PublicModel):
    trial_id: TrialId
    path: RelativePath
    role: SourceRole
    declared_role: SourceRole | None = None
    reason: str = Field(min_length=1)
    sha256: Identity | None = None


class UnreadableSourceCondition(FileVisibilityCondition):
    code: Literal["unreadable_source"]


class UnsupportedSourceCondition(FileVisibilityCondition):
    code: Literal["unsupported_source"]


class DeclaredSourceMissingCondition(FileVisibilityCondition):
    code: Literal["declared_source_missing"]


class InvalidRegistryCondition(PublicModel):
    code: Literal["invalid_registry_identifier"]
    trial_id: TrialId
    value: str = Field(min_length=1)


class RegistryReviewCondition(PublicModel):
    code: Literal["registry_review"]
    trial_id: TrialId
    outcome: RegistryOutcome


class OmissionReviewCondition(PublicModel):
    code: Literal["omission_review"]
    trial_id: TrialId
    paths: tuple[str, ...]
    records: tuple[OmissionDecision, ...]


class NoSupportedSourcesCondition(PublicModel):
    code: Literal["no_supported_sources"]
    trial_id: TrialId


IntakeCondition = Annotated[
    UnsupportedSourceCondition
    | UnreadableSourceCondition
    | DeclaredSourceMissingCondition
    | InvalidRegistryCondition
    | RegistryReviewCondition
    | OmissionReviewCondition
    | NoSupportedSourcesCondition,
    Field(discriminator="code"),
]


class PublicSource(PublicModel):
    id: SourceHandle
    trial_id: TrialId
    role: SourceRole
    label: str = Field(min_length=1)
    logical_path: RelativePath
    sha256: Identity
    media_type: str = Field(min_length=1)
    page_count: PageNumber
    projection_hash: Identity
    origin: SourceOrigin = SourceOrigin.LOCAL_DOSSIER
    declared_role: SourceRole | None = None


class PublicCapturedTrial(PublicModel):
    id: TrialId
    label: str = Field(min_length=1)
    requested_outcome: str = Field(min_length=1)
    sources: tuple[PublicSource, ...]
    registry: RegistryOutcome
    omissions: tuple[OmissionDecision, ...] = ()
    identity: Identity


class PrepareData(PublicModel):
    batch_identity: Identity
    conditions: tuple[IntakeCondition, ...]
    trials: tuple[PublicCapturedTrial, ...]
    retry: StrictBool = False


class TerminalCounts(PublicModel):
    assessed: NonNegativeInt
    needs_input: NonNegativeInt
    unsupported_design: NonNegativeInt
    failed: NonNegativeInt
    pending: NonNegativeInt
    reviewable: NonNegativeInt


class SelectedNarrativeEvidence(PublicModel):
    kind: Literal["narrative"]
    handle: EvidenceHandle = Field(description="Exact selected passage handle from this Trial.")
    identity: Identity
    trial_id: TrialId
    source_id: SourceHandle
    source_version: Identity | None = Field(
        default=None,
        description="Captured Source projection version used to derive this exact text span.",
    )
    page: PageNumber
    # Exact line bounds are emitted for new search- and read-derived passages.
    # They remain optional for canonical evidence created by an older contract.
    start_line: PageNumber | None = None
    end_line: PageNumber | None = None
    start: NonNegativeInt | None = None
    end: NonNegativeInt | None = None
    quote: str | None = Field(default=None, min_length=1)
    inclusion_reason: (
        Literal[
            "result",
            "checkpoint",
            "active_domain_candidate",
            "trial_discovery",
            "question_candidate",
            "contradiction",
            "explicit_carry_forward",
        ]
        | None
    ) = None
    domain_id: DomainId | None = None
    question_id: QuestionId | None = None
    search_session: Identity | None = None
    candidate_rank: PositiveInt | None = None
    returned_previously: StrictBool | None = None
    text_status: Literal["complete", "omitted"] = "complete"
    recovery: EvidenceRecovery | None = None

    @model_validator(mode="after")
    def text_projection_shape(self) -> SelectedNarrativeEvidence:
        if self.text_status == "omitted":
            if self.quote is not None or self.recovery is None:
                raise ValueError("omitted narrative text requires recovery and no quote")
            if self.start_line is None or self.end_line is None:
                raise ValueError("omitted narrative text requires exact line coordinates")
            if len(self.recovery.windows) != 1:
                raise ValueError("omitted narrative text requires one exact recovery window")
            window = self.recovery.windows[0]
            if (
                self.recovery.trial_id != self.trial_id
                or window.source_id != self.source_id
                or window.page != self.page
                or window.start_line != self.start_line
                or window.end_line != self.end_line
            ):
                raise ValueError("recovery window does not match narrative coordinates")
        elif self.quote is None or self.recovery is not None:
            raise ValueError("complete narrative text requires a quote and no recovery")
        return self


class RenderProjection(PublicModel):
    identity: Identity
    source_id: SourceHandle
    page: PageNumber
    png_sha256: Identity
    recipe: str = Field(min_length=1)


class SelectedFigureEvidence(PublicModel):
    kind: Literal["figure"]
    handle: EvidenceHandle = Field(description="Exact selected figure handle from this Trial.")
    identity: Identity
    trial_id: TrialId
    source_id: SourceHandle
    render: RenderProjection
    delivery_receipt: Identity
    transcription: str = Field(min_length=1)
    provenance: Literal["text_corroborated", "host_visual"]
    uncertainty: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        description=(
            "Optional host-observed uncertainty retained with the transcription. This is "
            "provenance, not a server-verified comprehension or scientific claim."
        ),
    )
    region: tuple[
        NormalizedCoordinate,
        NormalizedCoordinate,
        NormalizedCoordinate,
        NormalizedCoordinate,
    ]
    inclusion_reason: str | None = None
    domain_id: DomainId | None = None
    question_id: QuestionId | None = None
    search_session: Identity | None = None
    returned_previously: StrictBool | None = None


class EvidenceReadWindow(PublicModel):
    source_id: SourceHandle
    page: PageNumber
    start_line: PageNumber
    end_line: PageNumber
    start_char: NonNegativeInt = Field(
        default=0,
        description="Start character offset for a continued physical line.",
    )
    end_char: NonNegativeInt | None = Field(
        default=None,
        description="Optional exclusive end offset within the final line.",
    )

    @model_validator(mode="after")
    def character_bounds_are_valid(self) -> EvidenceReadWindow:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        if (
            self.end_line == self.start_line
            and self.end_char is not None
            and self.end_char < self.start_char
        ):
            raise ValueError("end_char must not precede start_char")
        return self


class EvidenceRecovery(PublicModel):
    """Exact recovery metadata for text omitted from a context projection."""

    operation: Literal["read_pages"]
    trial_id: TrialId
    windows: tuple[EvidenceReadWindow, ...] = Field(min_length=1, max_length=20)


class RenderRecovery(PublicModel):
    """Exact recovery route for layout-dependent or image-only Source material."""

    operation: Literal["render_page"]
    trial_id: TrialId
    source_id: SourceHandle
    page: PageNumber
    inline: StrictBool = True


SourceRecovery = EvidenceRecovery | RenderRecovery


class MainReportRecovery(EvidenceRecovery):
    """Bounded recovery metadata for the mandatory report text pass."""

    window_count: NonNegativeInt = 0
    status: Literal["required", "budget_limited"] = "required"
    unread_ranges: tuple[EvidenceReadWindow, ...] = ()
    unread_range_count: NonNegativeInt = 0


SelectedEvidence = Annotated[
    SelectedNarrativeEvidence | SelectedFigureEvidence,
    Field(discriminator="kind"),
]


class MainReportReadingStatus(PublicModel):
    status: Literal["required", "complete", "budget_limited"]
    budget_bytes: NonNegativeInt
    covered_prefix_bytes: NonNegativeInt
    required_ranges: tuple[EvidenceReadWindow, ...] = Field(
        default=(),
        description="Next bounded text windows required to complete the fixed report prefix.",
    )
    required_range_count: NonNegativeInt = 0
    unread_ranges: tuple[EvidenceReadWindow, ...] = ()
    unread_range_count: NonNegativeInt = 0


class WorkingSourceRangeData(PublicModel):
    source_id: SourceHandle
    page: PageNumber
    start_line: NonNegativeInt
    end_line: NonNegativeInt


class WorkingSourceBindingData(PublicModel):
    source_id: SourceHandle
    projection_hash: Identity


class WorkingDomainBindingData(PublicModel):
    domain_id: DomainId
    checkpoint_identity: Identity


class WorkingNoteData(PublicModel):
    text: str = Field(min_length=1, max_length=4_000)
    sources: tuple[WorkingSourceRangeData, ...] = Field(min_length=1, max_length=8)
    domain_id: DomainId | None = None
    question_id: QuestionId | None = None


class WorkingTermData(PublicModel):
    term: str = Field(min_length=1, max_length=256)
    meaning: str = Field(min_length=1, max_length=2_000)
    sources: tuple[WorkingSourceRangeData, ...] = Field(min_length=1, max_length=8)


class WorkingDraftData(PublicModel):
    domain_id: DomainId
    question_id: QuestionId
    answer: Answer | None = None
    text: str = Field(min_length=1, max_length=4_000)
    sources: tuple[WorkingSourceRangeData, ...] = Field(min_length=1, max_length=8)


class WorkingPremiseRecordData(PublicModel):
    proposition: str = Field(min_length=1, max_length=4_000)
    status: WorkingPremiseStatus
    observations: tuple[WorkingNoteData, ...] = ()
    inference: str | None = Field(default=None, min_length=1, max_length=4_000)
    counterevidence: tuple[WorkingNoteData, ...] = ()
    unresolved_component: str | None = Field(default=None, min_length=1, max_length=4_000)
    next_action: str | None = Field(default=None, min_length=1, max_length=2_000)
    stopping_rationale: str | None = Field(default=None, min_length=1, max_length=4_000)
    domain_id: DomainId | None = None
    question_id: QuestionId | None = None

    @model_validator(mode="after")
    def unresolved_status_has_component(self) -> WorkingPremiseRecordData:
        if self.status in {"unresolved", "bounded"} and self.unresolved_component is None:
            raise ValueError(f"{self.status} premise status requires unresolved_component")
        if self.status == "bounded" and self.stopping_rationale is None:
            raise ValueError("bounded premise status requires stopping_rationale")
        return self


class WorkingCheckpointData(PublicModel):
    identity: Identity
    batch_id: Identity
    trial_id: TrialId
    result_identity: Identity | None = None
    domain_checkpoint_identities: tuple[Identity, ...] | None = None
    domain_checkpoint_bindings: tuple[WorkingDomainBindingData, ...] | None = None
    source_scope: tuple[WorkingSourceBindingData, ...]
    observations: tuple[WorkingNoteData, ...]
    interpretations: tuple[WorkingNoteData, ...]
    terminology: tuple[WorkingTermData, ...]
    unread_ranges: tuple[WorkingSourceRangeData, ...]
    open_questions: tuple[WorkingNoteData, ...]
    drafts: tuple[WorkingDraftData, ...]
    premise_records: tuple[WorkingPremiseRecordData, ...] = ()
    next_action: str | None = None


class WorkingCheckpointStatus(PublicModel):
    status: Literal["absent", "current", "stale"]
    reason: (
        Literal[
            "no_active_trial",
            "no_active_batch",
            "not_saved",
            "result_changed",
            "source_changed",
            "canonical_newer",
        ]
        | None
    )
    trial_id: TrialId | None = None
    checkpoint_identity: Identity | None = None
    checkpoint: WorkingCheckpointData | None = None
    stale_domains: tuple[DomainId, ...] = ()
    recovery: Literal[
        "reorient_from_sources",
        "resume_from_checkpoint",
        "resume_from_canonical_checkpoint",
    ]


class InvestigationCoverage(PublicModel):
    """Source coverage observed by a host-owned premise investigation."""

    source_scope: tuple[SourceHandle, ...] = ()
    observed_sources: tuple[SourceHandle, ...] = ()
    unread_sources: tuple[SourceHandle, ...] = ()
    observed_note_count: NonNegativeInt = 0
    state: Literal["unobserved", "partial", "complete", "invalidated", "legacy"]


class InvestigationRecoveryChoice(PublicModel):
    """One host-visible way to continue or deliberately bound investigation."""

    operation: Literal[
        "save_working_checkpoint",
        "search_sources",
        "read_pages",
        "render_page",
        "validate_domain_assessment",
        "save_domain_judgment",
        "accept_limitation",
    ]
    available: StrictBool = True
    rationale: str = Field(min_length=1)


class InvestigationWorkflowPermission(PublicModel):
    """Workflow legality, intentionally separate from scientific sufficiency."""

    permitted: StrictBool
    operation: str = Field(min_length=1)
    authority: Literal["host", "researcher", "none"]
    detail: str = Field(min_length=1)


class InvestigationSufficiency(PublicModel):
    """A host assertion; this is not server-verified entailment."""

    status: Literal["supported", "contradicted", "unresolved", "bounded", "not_established"]
    attribution: Literal["host_asserted", "not_established"]


class InvestigationStaleMaterial(PublicModel):
    material: Literal[
        "observations",
        "interpretations",
        "counterevidence",
        "premise_inference",
        "drafts",
        "stopping_rationale",
    ]
    reason: Literal["domain_revision", "source_changed", "result_changed", "legacy_checkpoint"]


class InvestigationView(PublicModel):
    """Compact derived projection of the existing working premise checkpoint."""

    proposition: str = Field(min_length=1, max_length=4_000)
    status: Literal["supported", "contradicted", "unresolved", "bounded", "not_established"]
    sufficiency: InvestigationSufficiency
    workflow_permission: InvestigationWorkflowPermission
    coverage: InvestigationCoverage
    observations: tuple[WorkingNoteData, ...] = ()
    support: tuple[WorkingNoteData, ...] = ()
    counterevidence: tuple[WorkingNoteData, ...] = ()
    premises: tuple[WorkingPremiseRecordData, ...] = ()
    unresolved: str | None = Field(default=None, min_length=1, max_length=4_000)
    recovery_choices: tuple[InvestigationRecoveryChoice, ...] = ()
    stopping_rationale: str | None = Field(default=None, min_length=1, max_length=4_000)
    stale: tuple[InvestigationStaleMaterial, ...] = ()
    checkpoint_identity: Identity | None = None
    legacy: Literal["supported", "reorientation_required"] = "supported"


class DomainPremiseCheckpoint(PublicModel):
    """Small Domain-context projection of the reusable premise checkpoint."""

    identity: Identity
    result_identity: Identity | None = None
    source_scope: tuple[WorkingSourceBindingData, ...]
    premise_records: tuple[WorkingPremiseRecordData, ...] = ()


class DomainPremiseCheckpointStatus(PublicModel):
    """Compatibility-safe status and recovery metadata for premise reuse."""

    status: Literal["absent", "current", "stale"]
    reason: (
        Literal[
            "no_active_trial",
            "no_active_batch",
            "not_saved",
            "result_changed",
            "source_changed",
            "canonical_newer",
        ]
        | None
    )
    trial_id: TrialId | None = None
    checkpoint_identity: Identity | None = None
    checkpoint: DomainPremiseCheckpoint | None = None
    recovery: Literal[
        "reorient_from_sources",
        "resume_from_checkpoint",
        "resume_from_canonical_checkpoint",
    ]


class TrialDomainAttribution(PublicModel):
    domain_id: DomainId = Field(description="Canonical Domain represented by this review row.")
    attribution: Literal["new_evidence", "self_correction", "mechanical_repair", "unchanged"] = (
        Field(
            description=(
                "Observable basis of the current Domain checkpoint: a cited new Evidence item, "
                "the model's correction of its earlier interpretation, a mechanical repair, or no "
                "revision."
            )
        )
    )
    checkpoint_identity: Identity = Field(
        description="Identity of the current Domain checkpoint used by this Trial review."
    )


class TrialReviewSummary(PublicModel):
    identity: Identity
    trial_id: TrialId
    result_identity: Identity
    checkpoint_ids: tuple[Identity, ...]
    disposition: Literal["assessed", "needs_input", "unsupported_design", "failed"]
    reason: str | None = None
    facts: tuple[str, ...] = ()
    domain_attribution: tuple[TrialDomainAttribution, ...] = Field(
        default=(),
        description=(
            "Per-Domain attribution of the current checkpoints used by this review. "
            "This records workflow provenance, not a scientific judgment."
        ),
    )


class StatusData(PublicModel):
    trial_dispositions: dict[
        TrialId,
        Literal["pending", "reviewable", "assessed", "needs_input", "unsupported_design", "failed"],
    ]
    terminal_counts: TerminalCounts
    selected_evidence: tuple[SelectedEvidence, ...]
    working_checkpoint: WorkingCheckpointStatus
    investigation: InvestigationView | None = Field(
        default=None,
        description=(
            "Derived premise investigation view. Workflow permission and host-asserted "
            "sufficiency are separate and this view is not Evidence or a save gate."
        ),
    )
    trial_review: TrialReviewSummary | None = None
    main_report_reading: dict[TrialId, MainReportReadingStatus] = {}
    conditions: tuple[IntakeCondition, ...] = ()


class SaveWorkingCheckpointData(PublicModel):
    checkpoint_identity: Identity
    trial_id: TrialId
    result_identity: Identity | None = None
    source_count: NonNegativeInt
    authoritative: StrictBool
    next_action: str = Field(min_length=1)


class SourceNavigationEntry(PublicModel):
    text: str = Field(
        min_length=1,
        max_length=512,
        description=(
            "Source-derived navigation text. Whitespace may be joined and page furniture "
            "omitted. Inspect the cited line range before using it as Evidence."
        ),
    )
    page: PageNumber
    start_line: PageNumber
    end_line: PageNumber
    kind: Literal[
        "heading_candidate",
        "page_excerpt",
        "contents_lead",
        "version_lead",
        "date_lead",
        "cross_reference_lead",
    ]
    date_kind: Literal[
        "capture",
        "version",
        "amendment",
        "cutoff",
        "template",
        "submission",
        "posting",
        "approval",
        "finalization",
        "retrieval",
        "unblinded_access",
    ] | None = Field(
        default=None,
        description=(
            "Explicit lexical date context copied from the Source. Posting, approval, "
            "finalization, retrieval, and actual unblinded access are distinct events; null "
            "means no date classification was made."
        ),
    )
    logical_section: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description=(
            "Nearest literal section heading in the captured projection. This is a routing "
            "label only and does not establish document precedence or applicability."
        ),
    )
    embedded_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description=(
            "Literal version or amendment text copied from this Source line, when present; "
            "it is not a precedence judgment."
        ),
    )

    @model_validator(mode="after")
    def line_order(self) -> SourceNavigationEntry:
        if self.end_line < self.start_line:
            raise ValueError("navigation entry end_line must not precede start_line")
        return self


class SourceNavigationData(PublicModel):
    source_id: SourceHandle
    source_label: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    projection_hash: Identity
    navigation_version: Literal["rob2-kit.source-navigation.v0.1"]
    entries: tuple[SourceNavigationEntry, ...] = Field(max_length=12)
    total_entries: NonNegativeInt = Field(
        description="Total entries in the complete deterministic Source navigation index."
    )
    returned_entries: NonNegativeInt = Field(description="Entries returned in this transport page.")
    remaining_entries: NonNegativeInt = Field(
        description="Entries still available after this transport page."
    )
    terminal: StrictBool = Field(
        description="True only when the complete navigation index has been traversed."
    )
    page_count: PageNumber
    pages_examined: NonNegativeInt = Field(
        description=(
            "Number of Source pages scanned to generate navigation. This does not record "
            "agent reading or comprehension."
        )
    )
    pages_without_text_projection: tuple[PageNumber, ...] = Field(
        description=(
            "Source pages with no extracted text in the captured text projection. Such a page "
            "may contain visual or otherwise unextracted material and requires direct inspection."
        )
    )
    unreadable_pages: tuple[PageNumber, ...] = Field(
        description=(
            "Source pages without readable extracted text. Their presence does not imply that "
            "other pages were exhausted or that the underlying content is absent."
        )
    )
    truncated: StrictBool
    next_cursor: str | None = None
    condition: Literal["no_text_projection", "layout_inspection_available"] | None = Field(
        default=None,
        description=(
            "no_text_projection marks pages without extracted text; layout_inspection_available "
            "marks a PDF page excerpt with an exact render route for optional direct inspection."
        ),
    )
    render_recovery: tuple[RenderRecovery, ...] = Field(
        default=(),
        description=(
            "Exact render_page operations for pages without extracted text and for page excerpts "
            "where direct layout inspection may help. Rendering proves pixel delivery only; the "
            "host must inspect or transcribe the result."
        ),
    )
    version_spans: tuple[SourceNavigationEntry, ...] = Field(
        default=(),
        description="Literal embedded version or amendment lines for navigation only.",
    )
    date_spans: tuple[SourceNavigationEntry, ...] = Field(
        default=(),
        description="Literal date lines with their lexical date meaning, when one is stated.",
    )


class SourcesData(PublicModel):
    sources: tuple[PublicSource, ...]
    conditions: tuple[IntakeCondition, ...] = ()
    omissions: tuple[OmissionDecision, ...] = ()
    navigation: SourceNavigationData | None = None


class SearchRange(PublicModel):
    start: PositiveInt
    end: PositiveInt


class SearchHit(PublicModel):
    source_id: SourceHandle
    source_role: SourceRole
    source_label: str = Field(min_length=1)
    page: PageNumber
    start_line: PageNumber = Field(
        description="First line of the displayed and citable source window."
    )
    end_line: PageNumber = Field(
        description="Last line of the displayed and citable source window."
    )
    preview: str = Field(min_length=1, description="Exact source text identified by passage_ref.")
    passage_ref: EvidenceHandle = Field(
        description="Exact returned passage handle for this displayed search window."
    )
    candidate_truncated: StrictBool = Field(
        description=(
            "True when the displayed and citable window omits part of the matched candidate "
            "because of the response size limit. Use the supplied read_pages locator to "
            "inspect the omitted text before relying on the complete match. False means the "
            "candidate fits; it does not establish that the passage contains a complete "
            "scientific premise."
        )
    )
    candidate_recovery: EvidenceRecovery | None = Field(
        description=(
            "Read_pages locator covering the full matched candidate when candidate_truncated "
            "is true; null otherwise."
        )
    )
    rank: PositiveInt = Field(description="Stable underlying candidate rank.")
    within_source_rank: PositiveInt = Field(description="Rank within the Source.")
    range: SearchRange


class SearchReceipt(PublicModel):
    """Full receipt retained only inside durable checkpoints."""

    identity: Identity
    handle: SearchReceiptHandle = Field(description="Exact search receipt handle.")
    trial_id: TrialId
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    profile: str = Field(
        default="historical",
        min_length=1,
        description="Tokenizer and normalization profile bound to this search receipt.",
    )
    purpose_domain_id: DomainId | None = Field(
        default=None,
        description=(
            "Optional Domain whose workflow issued this search; omitted means unassigned discovery."
        ),
    )
    purpose_question_id: QuestionId | None = Field(
        default=None,
        description="Optional scientific question whose wording motivated this search.",
    )
    total_matches: NonNegativeInt
    truncated: StrictBool
    condition: str | None
    session_id: Identity
    session_handle: str = Field(pattern=r"^ss_[0-9a-f]{16}$")
    candidate_count: NonNegativeInt
    matching_page_count: NonNegativeInt
    ranking_complete: StrictBool
    returned_rank_start: PositiveInt | None
    returned_rank_end: PositiveInt | None
    next_cursor: str | None
    exhausted: StrictBool
    returned_material: NonNegativeInt

    @model_validator(mode="after")
    def purpose_requires_domain(self) -> SearchReceipt:
        if self.purpose_question_id is not None and self.purpose_domain_id is None:
            raise ValueError("question purpose requires a Domain")
        return self


class SearchNextAction(PublicModel):
    """One executable recovery refinement or continuation for a search response."""

    kind: Literal["refine", "continue"]
    operation: Literal["search_sources"]
    trial_id: TrialId
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    source_id: SourceHandle | None = None
    purpose_domain_id: DomainId | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Optional Domain purpose to preserve when refining or continuing a search.",
    )
    purpose_question_id: QuestionId | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Optional question purpose paired with purpose_domain_id.",
    )
    limit: PositiveInt
    cursor: str | None = None

    @model_validator(mode="after")
    def continuation_cursor_matches_kind(self) -> SearchNextAction:
        if self.kind == "continue" and self.cursor is None:
            raise ValueError("continuation action requires a cursor")
        if self.kind == "refine" and self.cursor is not None:
            raise ValueError("refinement action cannot carry a cursor")
        if self.purpose_question_id is not None and self.purpose_domain_id is None:
            raise ValueError("question purpose requires a Domain")
        return self


class SourceNavigationAction(PublicModel):
    """Executable literal navigation after a scoped lexical miss."""

    kind: Literal["navigate"]
    operation: Literal["list_sources"]
    trial_id: TrialId
    source_id: SourceHandle
    limit: PositiveInt
    cursor: str | None = None


SearchRecoveryAction = Annotated[
    SearchNextAction | SourceNavigationAction,
    Field(discriminator="operation"),
]


class SearchDiagnostic(PublicModel):
    """Observable retrieval advice; it is never a scientific conclusion."""

    code: Literal["broad_any_truncated", "no_hits"]
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    profile: str = Field(
        min_length=1,
        description="Tokenizer and normalization profile used for the diagnostic counts.",
    )
    normalized_term_count: PositiveInt
    total_matches: NonNegativeInt
    candidate_count: NonNegativeInt
    returned_count: NonNegativeInt
    detail: str = Field(min_length=1)
    next_action: SearchRecoveryAction | None = None
    navigation: SourceNavigationData | None = None


class SearchSpellingExample(PublicModel):
    """One exact Source span showing a suggested captured spelling."""

    source_id: SourceHandle
    page: PageNumber
    start: NonNegativeInt
    end: NonNegativeInt
    start_line: PageNumber
    end_line: PageNumber

    @model_validator(mode="after")
    def span_is_ordered(self) -> SearchSpellingExample:
        if self.end <= self.start:
            raise ValueError("spelling example end must follow start")
        if self.end_line < self.start_line:
            raise ValueError("spelling example end_line must not precede start_line")
        return self


class SearchSpellingSuggestion(PublicModel):
    query_unit: str = Field(
        min_length=1,
        description="Normalized query unit with zero matching pages under the issued search.",
    )
    query_unit_index: NonNegativeInt = Field(
        description="Zero-based query-unit position replaced by this executable alternative."
    )
    suggested_term: str = Field(
        min_length=1,
        description="Captured-source term within the bounded edit-distance suggestion policy.",
    )
    surface_page_count: NonNegativeInt = Field(
        description="Distinct captured pages containing the suggested surface term."
    )
    example: SearchSpellingExample = Field(
        description="Exact captured Source span showing the suggested surface term."
    )
    next_action: SearchNextAction = Field(
        description="Executable refinement that replaces only this query unit."
    )


class SearchTermPageCount(PublicModel):
    term: str = Field(
        min_length=1,
        description=(
            "One distinct whitespace-delimited normalized query unit; tokenizer matching may "
            "map it to more than one FTS token."
        ),
    )
    matching_page_count: NonNegativeInt = Field(
        description=(
            "Number of distinct captured pages where this query unit matches under the search "
            "tokenizer; this is not an occurrence count."
        )
    )


class SearchSourceTermFeedback(PublicModel):
    source_id: SourceHandle
    page_count: PageNumber = Field(
        description="Total captured pages in this Source, used to interpret term counts."
    )
    query_matching_page_count: NonNegativeInt = Field(
        description=(
            "Distinct pages in this Source matching the complete issued query under its "
            "mode; compare with term counts to distinguish term presence from full-query "
            "matches. Individual term counts do not establish co-occurrence or phrase "
            "adjacency. The complete-query count follows the issued mode. Prefix counts "
            "reflect prefix matching."
        )
    )
    term_page_counts: tuple[SearchTermPageCount, ...] = Field(min_length=1)


class SearchData(PublicModel):
    hits: tuple[SearchHit, ...]
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    profile: str = Field(
        min_length=1,
        description="Tokenizer and normalization profile used for this search ranking.",
    )
    total_matches: NonNegativeInt
    truncated: StrictBool
    condition: Literal["no_hits"] | None
    search_receipt: SearchReceiptHandle
    session_id: Identity
    session_handle: str = Field(pattern=r"^ss_[0-9a-f]{16}$")
    matching_page_count: NonNegativeInt
    candidate_count: NonNegativeInt
    distinct_passage_count: NonNegativeInt = Field(
        description="Distinct canonical Source/projection/range passages in the complete session."
    )
    distinct_page_count: NonNegativeInt = Field(
        description="Distinct matching Source pages in the complete session."
    )
    distinct_source_count: NonNegativeInt = Field(
        description="Distinct Sources contributing matching pages in the complete session."
    )
    ranking_complete: StrictBool
    returned_rank_start: PositiveInt | None
    returned_rank_end: PositiveInt | None
    next_cursor: str | None
    exhausted: StrictBool
    term_feedback: tuple[SearchSourceTermFeedback, ...]
    term_feedback_truncated: StrictBool = Field(
        description=(
            "True when the query contained more normalized units than the bounded feedback "
            "list; counts are provided only for the returned units."
        )
    )
    term_feedback_sources_truncated: StrictBool = Field(
        description=(
            "True when the Trial had more Sources than the bounded feedback rows; counts are "
            "provided only for the returned Source rows."
        )
    )
    diagnostic: SearchDiagnostic | None = None
    spelling_suggestions: tuple[SearchSpellingSuggestion, ...] = ()
    spelling_suggestions_incomplete: StrictBool = False
    purpose_domain_id: DomainId | None = Field(
        default=None,
        description="Optional Domain purpose; omitted searches remain unassigned discovery.",
    )
    purpose_question_id: QuestionId | None = Field(
        default=None,
        description="Optional question purpose paired with purpose_domain_id.",
    )

    @model_validator(mode="after")
    def purpose_requires_domain(self) -> SearchData:
        if self.purpose_question_id is not None and self.purpose_domain_id is None:
            raise ValueError("question purpose requires a Domain")
        return self


class SearchBatchRequest(PublicModel):
    trial_id: TrialId = Field(description="Captured Trial to search.")
    query: StrictStr = Field(min_length=1, description="One independent lexical query.")
    mode: Literal["all", "phrase", "any", "prefix", "literal"] = Field(
        description="The explicit lexical intent for this query."
    )
    source_id: SourceHandle | None = Field(
        default=None,
        description="Optional source_id from the same Trial.",
    )
    purpose_domain_id: DomainId | None = Field(
        default=None,
        description="Optional Domain purpose; it controls attribution only, not ranking identity.",
    )
    purpose_question_id: QuestionId | None = Field(
        default=None,
        description="Optional question purpose within the selected Domain.",
    )
    limit: Annotated[
        StrictInt,
        Field(ge=1, le=100, description="Maximum passages returned for this query (1-100)."),
    ] = 10
    cursor: StrictStr | None = Field(
        default=None,
        description="Continuation cursor for this query only.",
    )

    @model_validator(mode="after")
    def purpose_requires_domain(self) -> SearchBatchRequest:
        if self.purpose_question_id is not None and self.purpose_domain_id is None:
            raise ValueError("question purpose requires a Domain")
        return self


class SearchBatchSuccess(PublicModel):
    outcome: Literal["success"]
    data: SearchData


class SearchBatchCondition(PublicModel):
    outcome: Literal["condition"]
    condition: ConditionData


SearchBatchResult = Annotated[
    SearchBatchSuccess | SearchBatchCondition,
    Field(discriminator="outcome"),
]


class SearchBatchItem(PublicModel):
    index: NonNegativeInt
    query: StrictStr
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    result: SearchBatchResult


class SearchBatchData(PublicModel):
    results: tuple[SearchBatchItem, ...] = Field(min_length=1, max_length=8)


class PageData(PublicModel):
    source_id: SourceHandle = Field(description="Exact Source handle for this returned page.")
    page: PageNumber
    numbered_text: str = Field(
        description="Returned Source text with each line prefixed by its 1-based line number."
    )
    line_count: NonNegativeInt
    returned_start_line: PageNumber
    returned_end_line: NonNegativeInt
    page_remainder: EvidenceReadWindow | None = Field(
        default=None,
        description="Unread physical lines after the returned page range, when any.",
    )
    truncated: StrictBool
    next_start_line: PageNumber | None = None
    returned_start_char: NonNegativeInt | None = Field(
        default=None,
        description="Start offset of the returned line fragment.",
    )
    next_start_char: NonNegativeInt | None = Field(
        default=None,
        description="Next offset for continuing the same physical line.",
    )
    line_fragment: StrictBool = Field(
        default=False,
        description="Whether this page contains a physical-line fragment.",
    )
    passage_ref: EvidenceHandle | None = Field(
        default=None,
        description=(
            "Exact returned passage handle for complete nonblank text. Physical-line fragments "
            "have no passage_ref."
        ),
    )

    @model_validator(mode="after")
    def fragment_provenance_is_truthful(self) -> PageData:
        if not self.line_fragment and (
            self.returned_start_char is not None or self.next_start_char is not None
        ):
            raise ValueError("character extents require line_fragment=true")
        if self.line_fragment and self.passage_ref is not None:
            raise ValueError("a partial physical line cannot receive a passage_ref")
        if self.next_start_char is not None and not self.truncated:
            raise ValueError("a fragment continuation requires truncated=true")
        return self


class PagesData(PublicModel):
    pages: tuple[PageData, ...] = Field(min_length=1)
    remaining_windows: tuple[EvidenceReadWindow, ...] = Field(
        default=(),
        description="Exact requested line windows not returned in this response, in request order.",
    )


class TextEvidenceData(PublicModel):
    evidence: SelectedNarrativeEvidence


class VisualEvidenceData(PublicModel):
    evidence: SelectedFigureEvidence


class RenderData(PublicModel):
    render: RenderProjection
    delivery_receipt: Identity | None = None


class ProposalData(PublicModel):
    proposal_identity: Identity
    retry: StrictBool = False


class ReasoningProposalSaveAction(PublicModel):
    expected_revision: NonNegativeInt


class ValidateProposalData(PublicModel):
    validation_scope: Literal["structure_and_references_only"]
    repairs: tuple[RepairDefect, ...] = ()
    next_action: ReasoningProposalSaveAction


class ProposalApprovalAcknowledgment(PublicModel):
    review_identity: Identity
    purpose: Literal["proposal"]
    caller: str = Field(min_length=1)
    method: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    workflow_basis: NonNegativeInt
    identity: Identity


class ProposalApprovalData(PublicModel):
    approved: Literal[True]
    acknowledgment: Identity
    acknowledgment_record: ProposalApprovalAcknowledgment
    retry: StrictBool = False


class ProposalApprovalDeclined(PublicModel):
    code: Literal["proposal_approval_declined"]
    detail: str = Field(min_length=1)


class ProposalApprovalCancelled(PublicModel):
    code: Literal["proposal_approval_cancelled"]
    detail: str = Field(min_length=1)


class ProposalApprovalUnsupported(PublicModel):
    code: Literal["proposal_approval_unsupported"]
    detail: str = Field(min_length=1)


class ProposalApprovalStale(PublicModel):
    code: Literal["proposal_approval_stale"]
    detail: str = Field(min_length=1)


class ProposalApprovalUnavailable(PublicModel):
    code: Literal["proposal_review_not_pending"]
    detail: str = Field(min_length=1)


ProposalApprovalCondition = Annotated[
    ProposalApprovalDeclined
    | ProposalApprovalCancelled
    | ProposalApprovalUnsupported
    | ProposalApprovalStale
    | ProposalApprovalUnavailable,
    Field(discriminator="code"),
]


class AlwaysQuestionActivation(PublicModel):
    kind: Literal["always"]


class QuestionActivationPredicate(PublicModel):
    question_id: QuestionId
    accepted_answers: tuple[Answer, ...] = Field(min_length=1)


class ConditionalQuestionActivation(PublicModel):
    kind: Literal["rule"]
    mode: Literal["any", "all"]
    predicates: tuple[QuestionActivationPredicate, ...] = Field(min_length=1)


QuestionActivation = Annotated[
    AlwaysQuestionActivation | ConditionalQuestionActivation,
    Field(discriminator="kind"),
]


class AnswerAnchor(PublicModel):
    answer: Answer
    text: str = Field(min_length=1)


class DomainQuestionCard(PublicModel):
    """Compact model-facing card for one scientific-pack question."""

    id: QuestionId
    wording: str = Field(min_length=1)
    options: tuple[Answer, ...] = Field(
        min_length=1,
        description="Official answer values permitted for this question.",
    )
    activation_status: Literal[
        "always_active",
        "dependent_on_draft_answers",
        "active_in_saved_checkpoint",
        "inactive_in_saved_checkpoint",
    ] = Field(
        description=(
            "Scoped activation status: always_active is unconditional; dependent_on_draft_answers "
            "awaits the submitted draft path; active_in_saved_checkpoint and "
            "inactive_in_saved_checkpoint describe only the current saved checkpoint."
        ),
    )
    activation: QuestionActivation = Field(
        description="Evaluate against earlier draft answers to derive the complete active path.",
    )
    official_guidance: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    bias_construct: str = Field(
        min_length=1,
        description="The causal bias construct assessed by this signalling question.",
    )
    decision_rule: str = Field(min_length=1)
    evidence_needed: tuple[str, ...] = Field(min_length=1)
    no_information_rule: str = Field(min_length=1)
    answer_anchors: tuple[AnswerAnchor, ...] = Field(
        min_length=1,
        description=(
            "Operational examples for interpreting each answer. Anchors clarify semantics; "
            "they are not a whitelist of acceptable evidence."
        ),
    )
    considerations: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Operational guidance for this question. Retrieval examples are optional alternatives, "
            "not a required query list."
        ),
    )
    invalid_shortcuts: tuple[str, ...] = Field(min_length=1)
    query_suggestions: tuple[QuerySuggestion, ...] = Field(min_length=1, max_length=8)


class DomainTableEvidence(PublicModel):
    kind: Literal["table"]
    handle: EvidenceHandle = Field(description="Exact selected table passage handle.")
    basis: Literal["text", "visual"]
    title: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    row: str = Field(min_length=1)
    columns: tuple[str, ...] = Field(min_length=1)
    group_or_category_axes: tuple[str, ...] = Field(min_length=1)
    cells: tuple[str, ...] = Field(min_length=1)
    units: tuple[str, ...] = Field(min_length=1)
    denominators: tuple[str, ...] = Field(min_length=1)
    footnotes: tuple[str, ...] = ()


class DomainTableEvidenceSpan(PublicModel):
    """A separately selected table fragment retained without joining its text."""

    role: Literal["title_or_definition", "header", "quantitative_row", "unit", "footnote"]
    handle: EvidenceHandle = Field(description="Exact selected table-fragment handle.")
    identity: Identity
    source_id: SourceHandle
    page: PageNumber
    start: NonNegativeInt
    end: NonNegativeInt
    start_line: PageNumber | None = None
    end_line: PageNumber | None = None


class DomainMultiSpanTableEvidenceReference(PublicModel):
    """Proof locations for a table Result; the spans do not imply continuity."""

    kind: Literal["table_multispan"]
    basis: Literal["text"]
    spans: tuple[DomainTableEvidenceSpan, ...] = Field(min_length=2)


class DomainDerivedInput(PublicModel):
    handle: EvidenceHandle = Field(description="Exact selected Evidence handle for this value.")
    value: str = Field(min_length=1)


class DomainDerivedEvidence(PublicModel):
    kind: Literal["derived"]
    operation: Literal["difference", "ratio", "sum"]
    inputs: tuple[DomainDerivedInput, ...] = Field(min_length=1)
    value: str = Field(min_length=1)


class DomainNarrativeEvidence(PublicModel):
    """Domain-only narrative projection; canonical selected Evidence stays strict."""

    kind: Literal["narrative"]
    handle: EvidenceHandle = Field(description="Exact selected narrative handle.")
    identity: Identity
    trial_id: TrialId
    source_id: SourceHandle
    source_version: Identity | None = None
    page: PageNumber
    # Canonical Evidence from older checkpoints may have a complete quote but
    # no line coordinates.  Coordinates are required only when text is omitted
    # and the model needs to execute read_pages recovery.
    start_line: PageNumber | None = None
    end_line: PageNumber | None = None
    start: NonNegativeInt | None = None
    end: NonNegativeInt | None = None
    quote: str | None = Field(default=None, min_length=1)
    inclusion_reason: (
        Literal[
            "result",
            "checkpoint",
            "active_domain_candidate",
            "trial_discovery",
            "question_candidate",
            "contradiction",
            "explicit_carry_forward",
        ]
        | None
    ) = None
    domain_id: DomainId | None = None
    question_id: QuestionId | None = None
    search_session: Identity | None = None
    candidate_rank: PositiveInt | None = None
    returned_previously: StrictBool | None = None
    text_status: Literal["complete", "omitted"] = "complete"
    recovery: EvidenceRecovery | None = None

    @model_validator(mode="after")
    def text_projection_shape(self) -> DomainNarrativeEvidence:
        if self.text_status == "omitted":
            if self.quote is not None or self.recovery is None:
                raise ValueError("omitted narrative text requires recovery and no quote")
            if self.recovery.operation != "read_pages":
                raise ValueError("omitted narrative text requires read_pages recovery")
            if self.start_line is None or self.end_line is None:
                raise ValueError("omitted narrative text requires exact line coordinates")
            if len(self.recovery.windows) != 1:
                raise ValueError("omitted narrative text requires one exact recovery window")
            window = self.recovery.windows[0]
            if (
                self.recovery.trial_id != self.trial_id
                or window.source_id != self.source_id
                or window.page != self.page
                or window.start_line != self.start_line
                or window.end_line != self.end_line
            ):
                raise ValueError("recovery window does not match narrative coordinates")
        elif self.quote is None or self.recovery is not None:
            raise ValueError("complete narrative text requires a quote and no recovery")
        return self


DomainEvidence = Annotated[
    DomainNarrativeEvidence | DomainTableEvidence | SelectedFigureEvidence | DomainDerivedEvidence,
    Field(discriminator="kind"),
]


class DomainResultEvidenceReference(PublicModel):
    """The compact Evidence identity needed while answering a Domain."""

    kind: Literal["narrative", "table", "figure"]
    handle: EvidenceHandle = Field(description="Exact selected Evidence handle.")
    identity: Identity


DomainResultEvidence = Annotated[
    DomainResultEvidenceReference | DomainMultiSpanTableEvidenceReference | DomainDerivedEvidence,
    Field(discriminator="kind"),
]


class DomainCategoryValue(PublicModel):
    category_axes: tuple[str, ...] = Field(min_length=1)
    value: str = Field(min_length=1)


class DomainCategoryProfileResult(PublicModel):
    """Complete approved category profile without proof-oriented bindings."""

    form: Literal["single_group_category_profile"]
    analysis_population: str = Field(min_length=1)
    endpoint: ReportedEndpoint
    group_id: str = Field(min_length=1)
    denominator_basis: str = Field(min_length=1)
    category_axis_names: tuple[str, ...] = Field(min_length=1)
    categories: tuple[DomainCategoryValue, ...] = Field(min_length=1)


class DomainAssessableResult(PublicModel):
    """Approved Result data without canonical, proof-oriented bindings."""

    kind: Literal["assessable"]
    trial_id: TrialId
    requested_outcome: str = Field(min_length=1)
    relation: AssessableTargetRelation
    relation_rationale: str = Field(min_length=1)
    target: ResultTarget
    reported: Annotated[
        ComparativeEffectResult | GroupBoundValuesResult | DomainCategoryProfileResult,
        Field(discriminator="form"),
    ]
    clarity: ResultClarity
    evidence: tuple[DomainResultEvidence, ...] = Field(min_length=1)


DomainResultChoice = Annotated[
    DomainAssessableResult | UnavailableResult,
    Field(discriminator="kind"),
]


class SearchEvidenceContinuation(PublicModel):
    operation: Literal["search_sources"]
    trial_id: TrialId
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix", "literal"]
    source_id: SourceHandle | None = None
    purpose_domain_id: DomainId | None = Field(
        default=None,
        description="Optional Domain purpose to preserve while continuing a search.",
    )
    purpose_question_id: QuestionId | None = Field(
        default=None,
        description="Optional question purpose paired with purpose_domain_id.",
    )
    limit: PositiveInt
    cursor: str = Field(pattern=r"^sc_[0-9a-f]{16}_[0-9]+$")

    @model_validator(mode="after")
    def purpose_requires_domain(self) -> SearchEvidenceContinuation:
        if self.purpose_question_id is not None and self.purpose_domain_id is None:
            raise ValueError("question purpose requires a Domain")
        return self


class ReadEvidenceContinuation(PublicModel):
    operation: Literal["read_pages"]
    trial_id: TrialId
    windows: tuple[EvidenceReadWindow, ...] = Field(min_length=1, max_length=20)


class UnavailableEvidenceContinuation(PublicModel):
    operation: Literal["unavailable"]
    trial_id: TrialId
    search_session: Identity
    reason: Literal["derivative_search_session_unavailable"]


ExecutableEvidenceContinuation = Annotated[
    SearchEvidenceContinuation | ReadEvidenceContinuation,
    Field(discriminator="operation"),
]


EvidenceContinuation = Annotated[
    SearchEvidenceContinuation | ReadEvidenceContinuation | UnavailableEvidenceContinuation,
    Field(discriminator="operation"),
]


class OmittedEvidenceCounts(PublicModel):
    result: NonNegativeInt = 0
    checkpoint: NonNegativeInt = 0
    contradiction: NonNegativeInt = 0
    active_domain_candidate: NonNegativeInt = 0
    explicit_carry_forward: NonNegativeInt = 0
    trial_discovery: NonNegativeInt = 0
    deduplicated: NonNegativeInt = 0


class EvidenceWorkspaceGroup(PublicModel):
    inclusion_reason: Literal[
        "result",
        "checkpoint",
        "contradiction",
        "active_domain_candidate",
        "trial_discovery",
        "explicit_carry_forward",
    ]
    question_ids: tuple[QuestionId, ...] = ()
    evidence_handles: tuple[EvidenceHandle, ...] = ()


class EvidenceWorkspace(PublicModel):
    selection_policy_version: Literal["rob2-kit.domain-projection.v0.7"]
    groups: tuple[EvidenceWorkspaceGroup, ...]
    omitted_count: NonNegativeInt = 0
    omitted_by_category: OmittedEvidenceCounts = OmittedEvidenceCounts()
    continuation: ExecutableEvidenceContinuation | None = Field(
        default=None,
        description="Backward-compatible alias for the first executable recovery action.",
    )
    continuations: tuple[EvidenceContinuation, ...] = Field(
        default=(),
        description=(
            "All executable recovery actions and explicit unavailable session states, in "
            "deterministic order. This collection is authoritative when more than one search "
            "session or read-pages chunk is omitted."
        ),
    )
    recoverable_narrative_text_budget: NonNegativeInt = Field(
        default=12_288,
        description=(
            "UTF-8 byte limit for recoverable narrative quote text. Table, figure, and derived "
            "text is additional."
        ),
    )
    recoverable_narrative_text_bytes: NonNegativeInt = Field(
        default=0,
        description="UTF-8 bytes of included narrative quote text within the recoverable budget.",
    )
    omitted_narrative_text_bytes: NonNegativeInt = Field(
        default=0,
        description=(
            "UTF-8 bytes omitted from narrative quotes, including duplicate checkpoint basis "
            "source text removed from the context."
        ),
    )
    omitted_narrative_text_count: NonNegativeInt = Field(
        default=0,
        description="Number of narrative Evidence items whose quote text was omitted.",
    )
    unrecoverable_inline_text_bytes: NonNegativeInt = Field(
        default=0,
        description=(
            "UTF-8 bytes of inline Evidence text outside the recoverable narrative budget "
            "because no exact recovery operation exists. This includes coordinate-less legacy "
            "narrative text and table, figure, or derived text."
        ),
    )


class DomainPack(PublicModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_hash: Identity


class OfficialGuidanceSection(PublicModel):
    """One exact, pack-bound official excerpt available for recovery."""

    question_ids: tuple[QuestionId, ...] = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[A-F0-9]{64}$")
    source_locator: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class OfficialGuidanceRecovery(PublicModel):
    """Complete bounded official guidance for the selected Domain."""

    pack: DomainPack
    sections: tuple[OfficialGuidanceSection, ...] = Field(min_length=1)
    complete: StrictBool
    next_cursor: str | None = None


class DomainContextData(PublicModel):
    trial_id: TrialId | None = None
    domain_id: DomainId | None = None
    pack: DomainPack | None = Field(
        default=None,
        description="Exact scientific pack identity and version used for this Domain context.",
    )
    official_guidance: OfficialGuidanceRecovery | None = Field(
        default=None,
        description=(
            "Exact, pack-bound official excerpts for the selected Domain. Complete is false "
            "only when a bounded continuation is supplied."
        ),
    )
    result: DomainResultChoice | None = None
    evidence: tuple[DomainEvidence, ...] = ()
    answers: tuple[CheckpointAnswer, ...] = ()
    investigation: InvestigationView | None = Field(
        default=None,
        description=(
            "Current host-owned investigation projection for the selected Domain. It remains "
            "advisory and does not establish Evidence entailment."
        ),
    )
    working_checkpoint: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Current source-grounded premise checkpoint, when one exists. It is reusable only "
            "while its exact approved Result identity and captured Source projections match; "
            "stale checkpoints are returned with an explicit recovery reason."
        ),
    )
    evidence_sufficiency: EvidenceSufficiencySummary | None = None
    # Only the active checkpoint is needed to form a model-owned revision.
    # Complete revision history remains in the canonical bundle, not in the
    # model-facing continuation context.
    current_checkpoint: Identity | None = Field(
        default=None,
        description="Exact active checkpoint identity, when this Domain has been saved before.",
    )
    guidance: tuple[str, ...] = ()
    response_framework: ResponseFramework | None = None
    traps: tuple[str, ...] = ()
    questions: tuple[DomainQuestionCard, ...] = ()
    completion_rule: str | None = Field(default=None, min_length=1)
    evidence_workspace: EvidenceWorkspace | None = None
    comparison_cards: tuple[ComparisonCard, ...] = ()
    coverage: tuple[SourceCoverage, ...] = ()
    reading_recovery: MainReportRecovery | None = Field(
        default=None,
        description="Required read windows, or optional unread ranges when budget_limited.",
    )
    context_page: DomainContextPage | None = Field(
        default=None,
        description=(
            "Optional bounded transport page. When present, fetch every page in order before "
            "interpreting the Domain; page identity is bound to the Trial, Domain, and revision."
        ),
    )

    @model_validator(mode="after")
    def stable_header_is_delivered_once(self) -> DomainContextData:
        continuation = self.context_page is not None and self.context_page.index > 0
        stable = (
            self.trial_id,
            self.domain_id,
            self.pack,
            self.result,
            self.response_framework,
            self.completion_rule,
            self.evidence_workspace,
        )
        if continuation and any(value is not None for value in stable):
            raise ValueError("continuation pages must contain only context deltas")
        if not continuation and any(value is None for value in stable):
            raise ValueError("the first context page requires the complete stable header")
        return self


class DomainContextStableRecovery(PublicModel):
    operation: Literal["get_domain_context"]
    cursor: str = Field(
        min_length=1,
        description="Opaque page-zero cursor for the exact frozen scientific view.",
    )


class DomainContextPage(PublicModel):
    view_version: Literal["rob2-kit.domain-context.v1"] = "rob2-kit.domain-context.v1"
    snapshot_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the canonical unpaginated scientific view reconstructed by pages.",
    )
    trial_id: TrialId
    domain_id: DomainId
    state_revision: NonNegativeInt = Field(
        description=(
            "Frozen workflow revision used to bind every page in this context-page sequence; "
            "it may differ from the current head revision after unrelated changes."
        )
    )
    index: NonNegativeInt
    count: PositiveInt
    section: Literal["complete", "questions", "comparison_cards", "evidence"]
    item_start: NonNegativeInt = 0
    item_count: NonNegativeInt = 0
    max_response_bytes: StrictInt = Field(
        ge=4096,
        le=131_072,
        description="Byte budget used to produce this page; valid range 4096–131072.",
    )
    cursor: str | None = Field(default=None, min_length=1)
    next_cursor: str | None = Field(default=None, min_length=1)
    stable_recovery: DomainContextStableRecovery = Field(
        description="Exact operation for recovering the stable page-zero scientific header."
    )


class ComparisonPassageRef(PublicModel):
    handle: EvidenceHandle = Field(description="Exact selected passage handle.")
    source_id: SourceHandle
    page: PageNumber
    start_line: PageNumber
    end_line: PageNumber


class ComparisonPassageGroup(PublicModel):
    source_id: SourceHandle
    source_role: SourceRole
    source_label: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    page_count: PageNumber
    sha256: Identity
    source_origin: SourceOrigin
    registry_url: str | None = None
    registry_retrieved_at: str | None = None
    registry_field_paths: tuple[str, ...] = ()
    registry_recovery: EvidenceRecovery | None = None
    registry_window_count: NonNegativeInt = 0
    passages: tuple[ComparisonPassageRef, ...] = ()


class SourceCoverage(PublicModel):
    """Bounded retrieval state for one captured Source.

    This records delivery and navigation state only.  In particular,
    ``searched_no_match`` is a lexical retrieval fact and never means that a
    scientific premise was not reported.
    """

    source_id: SourceHandle
    source_role: SourceRole
    page_count: PageNumber
    status: Literal[
        "unsearched",
        "candidate_only",
        "searched_no_match",
        "partially_read",
        "read_complete",
        "render_delivered",
        "unavailable",
        "retrieval_incomplete",
    ]
    search: Literal[
        "unsearched",
        "candidate_only",
        "searched_no_match",
        "searched_match",
        "retrieval_incomplete",
    ]
    read: Literal["unread", "partially_read", "read_complete"]
    render: Literal["not_delivered", "render_delivered"]
    recovery: tuple[SourceRecovery, ...] = ()


class ComparisonSlot(PublicModel):
    name: str = Field(min_length=1)
    status: Literal["supported", "unknown", "conflicted"]
    value: str | None = None
    passages: tuple[ComparisonPassageRef, ...] = ()


class ComparisonProposition(PublicModel):
    """One host-owned scientific seam exposed by a comparison card."""

    question_id: QuestionId
    name: str = Field(min_length=1)
    proposition: str = Field(min_length=1)
    status: Literal["supported", "unknown", "conflicted"] = "unknown"
    depends_on: tuple[QuestionId, ...] = ()
    passages: tuple[ComparisonPassageRef, ...] = ()


class ComparisonExample(PublicModel):
    """A neutral paired contrast; it deliberately carries no expected answer."""

    pair_id: str = Field(min_length=1)
    changed_premise: str = Field(min_length=1)
    left_facts: tuple[str, ...] = Field(min_length=1)
    right_facts: tuple[str, ...] = Field(min_length=1)
    reasoning_focus: str = Field(min_length=1)


class ComparisonResultScope(PublicModel):
    """Exact Result scope used to interpret a comparison card."""

    result_identity: Identity
    endpoint: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    time_window: str = Field(min_length=1)
    population: str = Field(min_length=1)
    comparison_groups: tuple[str, ...] = Field(min_length=2)
    effect_measure: str = Field(min_length=1)


class ComparisonCard(PublicModel):
    card_id: str = Field(min_length=1)
    question_id: QuestionId
    result_identity: Identity
    result_scope: ComparisonResultScope | None = None
    passage_groups: tuple[ComparisonPassageGroup, ...] = ()
    slots: tuple[ComparisonSlot, ...] = Field(min_length=1)
    propositions: tuple[ComparisonProposition, ...] = ()
    paired_examples: tuple[ComparisonExample, ...] = ()
    participant_flow: tuple[ParticipantFlowProjection, ...] = ()
    missing_data: MissingDataReconciliation | None = None
    prompt: str = Field(min_length=1)


class DirectCheckpointEvidenceUse(PublicModel):
    kind: Literal["direct_support", "indirect_support", "contradiction", "context", "inference"]
    evidence: Identity
    # The Domain projection can omit this duplicate of Evidence text; the
    # handle/identity remains authoritative and exactly recoverable.
    source: str | None = Field(default=None, min_length=1)


class AbsenceCheckpointEvidenceUse(PublicModel):
    kind: Literal["absence"]
    search_receipt: Identity


class LimitationCheckpointBasis(PublicModel):
    kind: Literal["limitation"]
    unresolved_premise: str = Field(
        min_length=1,
        description="Specific premise that the captured Sources did not establish.",
    )
    stopping_rationale: str = Field(
        min_length=1,
        description="Why the bounded search/read effort stopped without establishing that premise.",
    )
    search_receipt: Identity | None = Field(
        default=None,
        description=(
            "Optional identity of the bounded search receipt supporting this limitation; a "
            "directly read passage does not require a search receipt."
        ),
    )


CheckpointEvidenceUse = Annotated[
    DirectCheckpointEvidenceUse | AbsenceCheckpointEvidenceUse | LimitationCheckpointBasis,
    Field(discriminator="kind"),
]


class MissingDataScope(PublicModel):
    arm: str = Field(min_length=1)
    population: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    result_identity: Identity | None = Field(default=None, exclude_if=lambda value: value is None)
    endpoint: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    severity: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    window: str | None = Field(default=None, min_length=1, exclude_if=lambda value: value is None)
    event_definition: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )


class ParticipantFlowProjection(PublicModel):
    """A source-bound participant transition or event numerator."""

    kind: Literal[
        "randomized",
        "eligible",
        "treated",
        "observed",
        "analyzed",
        "imputed",
        "excluded",
        "event",
    ]
    value: StrictInt | None = Field(default=None, ge=0)
    status: Literal["supported", "unknown", "conflicted"] = "unknown"
    result_identity: Identity | None = Field(default=None, exclude_if=lambda value: value is None)
    endpoint: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    severity: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    window: str | None = Field(default=None, min_length=1, exclude_if=lambda value: value is None)
    event_definition: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    scope: MissingDataScope
    passages: tuple[ComparisonPassageRef, ...] = ()


class MissingDataBounds(PublicModel):
    lower: StrictInt = Field(ge=0)
    upper: StrictInt = Field(ge=0)
    kind: Literal["exact", "bound"]

    @model_validator(mode="after")
    def ordered(self) -> MissingDataBounds:
        if self.upper < self.lower:
            raise ValueError("missing-data upper bound must not precede lower bound")
        return self


class MissingDataReconciledRow(PublicModel):
    scope: MissingDataScope
    result_identity: Identity | None = Field(default=None, exclude_if=lambda value: value is None)
    endpoint: str | None = Field(default=None, min_length=1, exclude_if=lambda value: value is None)
    severity: str | None = Field(default=None, min_length=1, exclude_if=lambda value: value is None)
    window: str | None = Field(default=None, min_length=1, exclude_if=lambda value: value is None)
    randomized: StrictInt | None = Field(default=None, ge=0)
    eligible: StrictInt | None = Field(default=None, ge=0)
    treated: StrictInt | None = Field(default=None, ge=0)
    observed: StrictInt | None = Field(default=None, ge=0)
    analyzed: StrictInt | None = Field(default=None, ge=0)
    imputed: StrictInt | None = Field(default=None, ge=0)
    excluded: StrictInt | None = Field(default=None, ge=0)
    event_count: StrictInt | None = Field(default=None, ge=0)
    event_definition: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    exclusions: tuple[str, ...] = ()
    basis: tuple[Identity, ...] = Field(min_length=1)
    missing: StrictInt | None = Field(default=None, ge=0)
    missing_fraction: float | None = Field(default=None, ge=0)
    missing_bounds: MissingDataBounds | None = None
    semantics: MissingDataSemantics | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class MissingDataConflict(PublicModel):
    scope: MissingDataScope
    reports: tuple[MissingDataReconciledRow, ...] = Field(min_length=2)


class MissingDataReconciliation(PublicModel):
    rows: tuple[MissingDataReconciledRow, ...] = Field(min_length=1)
    conflicts: tuple[MissingDataConflict, ...] = ()


class CheckpointAnswer(PublicModel):
    question_id: QuestionId
    answer: Answer
    bases: tuple[CheckpointEvidenceUse, ...] = Field(min_length=1)
    missing_data: MissingDataReconciliation | None = None
    justification: str | None = Field(
        default=None,
        description="Concise explanation of cited premises and uncertainty.",
    )
    unknowns: tuple[str, ...] | None = None
    counterevidence: tuple[DomainCounterevidence, ...] | None = None


class ClaimTrace(PublicModel):
    question_id: QuestionId
    status: Literal[
        "supported",
        "contradicted",
        "indirect",
        "unresolved",
        "not_reported",
        "retrieval_incomplete",
    ]
    evidence: tuple[Identity, ...] = ()
    search_receipts: tuple[Identity, ...] = ()
    unresolved_premises: tuple[str, ...] = ()
    support_attribution: Literal["host_asserted", "not_established"] = Field(
        default="not_established",
        description=(
            "Whether the recorded status reflects the host's asserted Evidence relationship. "
            "This is not a server semantic judgment."
        ),
    )


class EvidenceSufficiencySummary(PublicModel):
    claims: tuple[ClaimTrace, ...] = Field(min_length=1)
    identity: Identity


class DriverAnswer(PublicModel):
    question_id: QuestionId
    answer: Answer


class OverallDriver(PublicModel):
    domain_id: DomainId
    checkpoint: Identity
    judgment: Judgment
    trace: tuple[str, ...] = Field(min_length=1)
    driver_questions: tuple[QuestionId, ...] = ()
    driver_answers: tuple[DriverAnswer, ...] = ()
    evidence_sufficiency: EvidenceSufficiencySummary | None = None


class OverallAlternative(PublicModel):
    domain_id: DomainId
    question_id: QuestionId
    from_answer: Answer
    to_answer: Answer
    diagnostic_only: StrictBool = True
    status: Literal["evaluated", "requires_reassessment"]
    hypothetical_domain_judgment: Judgment | None = None
    hypothetical_overall: Judgment | None = None
    reason: str | None = None


class OverallAggregationReceipt(PublicModel):
    rule: str = Field(min_length=1)
    driver_domains: tuple[DomainId, ...] = ()
    drivers: tuple[OverallDriver, ...] = ()
    alternatives: tuple[OverallAlternative, ...] = ()
    stability: Literal["stable", "sensitive", "not_assessed", "requires_reassessment"]
    diagnostic_only: StrictBool = True


ParticipantFlowProjection.model_rebuild()
MissingDataReconciledRow.model_rebuild()
ComparisonCard.model_rebuild()
DomainContextData.model_rebuild()


class NewEvidenceRevision(PublicModel):
    kind: Literal["new_evidence"]
    evidence: Identity
    rationale: str = Field(min_length=1)


class SelfCorrectionRevision(PublicModel):
    kind: Literal["self_correction"]
    rationale: str = Field(min_length=1)


class MechanicalRepairRevision(PublicModel):
    kind: Literal["mechanical_repair"]
    repair_id: str | None = Field(
        default=None,
        min_length=1,
        description="Stable repair identifier when the correction came from a recorded repair.",
    )
    codes: tuple[str, ...] = Field(
        default=(),
        description=(
            "Mechanical repair codes that explain this rewrite without changing the scientific "
            "claim."
        ),
    )

    @model_validator(mode="after")
    def has_repair_reference(self) -> MechanicalRepairRevision:
        if self.repair_id is None and not self.codes:
            raise ValueError("mechanical_repair requires repair_id or codes")
        if len(self.codes) != len(set(self.codes)):
            raise ValueError("mechanical_repair codes must be unique")
        return self


CheckpointRevisionBasis = Annotated[
    NewEvidenceRevision | SelfCorrectionRevision | MechanicalRepairRevision,
    Field(discriminator="kind"),
]


class CheckpointSearchAccount(SearchReceipt):
    pass


class Checkpoint(PublicModel):
    identity: Identity
    trial_id: TrialId
    domain_id: DomainId
    result_identity: Identity | None = None
    answers: tuple[CheckpointAnswer, ...]
    judgment: Judgment
    active_questions: tuple[str, ...]
    inactive_questions: tuple[str, ...]
    search_accounts: tuple[CheckpointSearchAccount, ...]
    trace: tuple[str, ...]
    driver_questions: tuple[QuestionId, ...] = ()
    evidence_sufficiency: EvidenceSufficiencySummary | None = None
    observed_at: str = Field(min_length=1)
    supersedes: Identity | None = None
    revision_basis: CheckpointRevisionBasis | None = None


class DomainCheckpointSummary(PublicModel):
    identity: Identity
    trial_id: TrialId
    domain_id: DomainId
    judgment: Judgment
    driver_questions: tuple[QuestionId, ...] = ()
    evidence_sufficiency: EvidenceSufficiencySummary | None = None


class DomainJudgmentData(PublicModel):
    checkpoint: DomainCheckpointSummary
    trial_ready_for_review: StrictBool = Field(
        default=False,
        description=(
            "True after the save qualifies the Trial for review; the Trial remains correctable "
            "until it is explicitly closed."
        ),
    )
    retry: StrictBool = False


class ReasoningSaveAction(PublicModel):
    trial_id: TrialId
    domain_id: DomainId
    expected_revision: NonNegativeInt


class ValidateDomainAssessmentData(PublicModel):
    active_question_ids: tuple[QuestionId, ...]
    validation_scope: Literal["structure_and_references_only"]
    repairs: tuple[RepairDefect, ...] = ()
    investigation: InvestigationView | None = None
    next_action: ReasoningSaveAction


class ReviewEvidenceReference(PublicModel):
    """One exact Evidence identity retained by a reviewed answer."""

    handle: EvidenceHandle
    identity: Identity


class ReviewFact(PublicModel):
    """One source-bound fact shown before the host's answer warrant."""

    text: str = Field(
        min_length=1,
        max_length=4_000,
        description=(
            "Bounded source excerpt, at most 4,000 characters. Use evidence_expansions for exact "
            "recovery when more context is needed."
        ),
    )
    evidence: ReviewEvidenceReference | None = None
    role: Literal["support", "counterevidence", "context"] = "support"


class ReviewLimitation(PublicModel):
    """A host-recorded information limit, without implying scientific absence."""

    unresolved_premise: str = Field(min_length=1, max_length=4_000)
    stopping_rationale: str | None = Field(default=None, min_length=1, max_length=4_000)
    search_receipt: Identity | None = None


class ReviewConflict(PublicModel):
    """A deterministic or host-reported tension surfaced for correction."""

    kind: Literal[
        "population_mismatch",
        "endpoint_mismatch",
        "window_mismatch",
        "chronology_conflict",
        "contradiction",
        "unsupported_link",
        "accessible_uninvestigated_route",
        "potential_scope_mismatch",
    ]
    detail: str = Field(min_length=1, max_length=4_000)
    assertion: Literal["host_asserted", "server_derived"] = Field(
        default="host_asserted",
        description=(
            "Whether a conflict was reported by the host or derived by comparing typed, "
            "source-bound records. A server-derived scope difference is a review signal, "
            "not an assessor judgment."
        ),
    )
    evidence: tuple[ReviewEvidenceReference, ...] = ()


class ReviewInvestigationRoute(PublicModel):
    """A still-accessible route that may resolve an answer limitation."""

    operation: Literal["search_sources", "read_pages", "render_page", "list_sources"]
    detail: str = Field(min_length=1, max_length=2_000)
    search_receipt: Identity | None = None


class ReviewBasisFinding(PublicModel):
    """One host assertion retained in the final review projection."""

    kind: Literal[
        "direct_support",
        "indirect_support",
        "contradiction",
        "context",
        "inference",
        "absence",
        "limitation",
    ]
    assertion: Literal["host_asserted"] = Field(
        default="host_asserted",
        description=(
            "The relationship or limitation was asserted by the host. The server preserves and "
            "checks its references but does not independently judge scientific entailment."
        ),
    )
    evidence: ReviewEvidenceReference | None = None
    search_receipt: Identity | None = None
    unresolved_premise: str | None = None
    stopping_rationale: str | None = None


class ReviewReadEvidenceAction(PublicModel):
    """A review expansion containing read operation and evidence metadata."""

    operation: Literal["read_pages"]
    evidence: EvidenceHandle
    trial_id: TrialId
    windows: tuple[EvidenceReadWindow, ...] = Field(min_length=1, max_length=1)


class ReviewRenderEvidenceAction(PublicModel):
    """A review expansion containing render operation and evidence metadata."""

    operation: Literal["render_page"]
    evidence: EvidenceHandle
    trial_id: TrialId
    source_id: SourceHandle
    page: PageNumber


ReviewEvidenceExpansion = Annotated[
    ReviewReadEvidenceAction | ReviewRenderEvidenceAction,
    Field(discriminator="operation"),
]


class ReviewAnswerFinding(PublicModel):
    question_id: QuestionId
    answer: Answer
    facts: tuple[ReviewFact, ...] = ()
    warrant: str | None = Field(
        default=None,
        min_length=1,
        max_length=4_000,
        description=(
            "Host-authored warrant connecting the displayed facts to the answer. The server "
            "does not independently judge this inference."
        ),
    )
    justification: str | None = None
    unknowns: tuple[str, ...] = ()
    counterevidence: tuple[DomainCounterevidence, ...] = ()
    limitations: tuple[ReviewLimitation, ...] = ()
    conflicts: tuple[ReviewConflict, ...] = ()
    uninvestigated_routes: tuple[ReviewInvestigationRoute, ...] = ()
    evidence: tuple[ReviewEvidenceReference, ...] = ()
    bases: tuple[dict[str, Any], ...] = Field(
        default=(),
        description=(
            "Exact premise-basis assertions retained for review; support remains host-asserted "
            "and is not a server semantic finding."
        ),
    )
    evidence_expansions: tuple[ReviewEvidenceExpansion, ...] = ()


class ReviewDomainFinding(PublicModel):
    domain_id: DomainId
    checkpoint_identity: Identity
    judgment: Judgment
    answers: tuple[ReviewAnswerFinding, ...] = Field(min_length=1)
    premise_checkpoint_identity: Identity | None = Field(
        default=None,
        description=(
            "Current source-grounded premise checkpoint used for this projection, when it is "
            "still bound to the approved Result and Source projections."
        ),
    )
    premise_records: tuple[WorkingPremiseRecordData, ...] = Field(
        default=(),
        description=(
            "Source-grounded host notes for material premises. They are not Domain judgments or "
            "Evidence authority."
        ),
    )
    investigation: InvestigationView | None = Field(
        default=None,
        description=(
            "Dependency-aware investigation state for this Domain. Stale inference and "
            "stopping decisions are identified separately from reusable source observations."
        ),
    )


class ReviewTrialData(PublicModel):
    review: TrialReviewSummary
    result: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Exact approved Result scope retained with final review: endpoint, measurement, "
            "population, comparison, timing, analysis, effect measure, and eligible alternatives."
        ),
    )
    domain_findings: tuple[ReviewDomainFinding, ...] = Field(
        default=(),
        description="Current checkpoint support and exact Evidence expansion actions for review.",
    )
    retry: StrictBool = False


class TrialClosureSummary(PublicModel):
    identity: Identity
    trial_id: TrialId
    review_identity: Identity
    disposition: Literal["assessed", "needs_input", "unsupported_design", "failed"]


class CloseTrialData(PublicModel):
    closure: TrialClosureSummary
    retry: StrictBool = False


class Artifact(PublicModel):
    path: str = Field(min_length=1)
    identity: Identity
    sha256: Identity
    files: tuple[str, ...]


class AssessmentSummary(PublicModel):
    overall: Judgment
    domains: dict[DomainId, Judgment] = Field(min_length=5, max_length=5)
    overall_trace: tuple[str, ...] = ()
    overall_driver_domains: tuple[DomainId, ...] = ()
    overall_receipt: OverallAggregationReceipt | None = None

    @model_validator(mode="after")
    def includes_every_domain(self) -> AssessmentSummary:
        if set(self.domains) != set(get_args(DomainId)):
            raise ValueError("assessment summary must include exactly the five Domains")
        return self


class FinalizeData(PublicModel):
    artifact: Artifact
    trial_dispositions: dict[
        TrialId,
        Literal["pending", "reviewable", "assessed", "needs_input", "unsupported_design", "failed"],
    ] = {}
    assessment_summary: dict[TrialId, AssessmentSummary]
    retry: StrictBool = False


DataByTool: Final = {
    "prepare_batch": PrepareData,
    "get_status": StatusData,
    "save_working_checkpoint": SaveWorkingCheckpointData,
    "list_sources": SourcesData,
    "search_sources": SearchData,
    "search_sources_batch": SearchBatchData,
    "read_pages": PagesData,
    "select_text_evidence": TextEvidenceData,
    "render_page": RenderData,
    "select_visual_evidence": VisualEvidenceData,
    "save_proposal": ProposalData,
    "validate_proposal": ValidateProposalData,
    "request_proposal_approval": ProposalApprovalData,
    "get_domain_context": DomainContextData,
    "validate_domain_assessment": ValidateDomainAssessmentData,
    "save_domain_judgment": DomainJudgmentData,
    "review_trial": ReviewTrialData,
    "close_trial": CloseTrialData,
    "finalize_batch": FinalizeData,
}
ConditionByTool: Final = {
    "search_sources": SearchCursorCondition,
    "search_sources_batch": ConditionData,
    "finalize_batch": ConditionData,
    "request_proposal_approval": ProposalApprovalCondition,
    "validate_domain_assessment": DomainContextDeliveryCondition,
    "save_domain_judgment": DomainContextDeliveryCondition,
}


def _head(value: dict[str, Any]) -> dict[str, Any]:
    continuation = value.get("continuation")
    if isinstance(continuation, dict):
        authority = str(continuation.get("authority", "host"))
        return {
            "phase": value.get("phase", "empty"),
            "state_revision": value.get("state_revision", 0),
            "next_action": (
                {
                    "operation": str(continuation.get("operation", "get_status")),
                    "authority": "researcher",
                    "reference": continuation.get("review_reference"),
                    "purpose": continuation.get("purpose") or "researcher review",
                }
                if authority == "researcher"
                else {
                    key: continuation[key]
                    for key in (
                        "operation",
                        "authority",
                        "expected_revision",
                        "trial_id",
                        "domain_id",
                        "review_reference",
                        "caller_inputs",
                        "supersedes",
                    )
                    if key in continuation
                }
            ),
            "authoritative_wording": str(
                value.get("authoritative_wording", "Inspect the current workflow status.")
            ),
        }
    phase = value.get("phase", "empty")
    if phase == "empty":
        next_action: dict[str, Any] | None = {
            "operation": "prepare_batch",
            "authority": "host",
            "expected_revision": value.get("state_revision", 0),
            "caller_inputs": ["requested_outcome", "trial_labels"],
        }
    else:
        next_action = None
    return {
        "phase": phase,
        "state_revision": value.get("state_revision", 0),
        "next_action": next_action,
        "authoritative_wording": str(
            value.get("authoritative_wording", "Inspect the current workflow status.")
        ),
    }


def _clean_public(value: dict[str, Any]) -> dict[str, Any]:
    """Drop only context fields that are inapplicable in this projection."""

    def clean_conditions(node: object) -> None:
        if isinstance(node, dict):
            if "code" in node and "detail" in node and node.get("action") is None:
                node.pop("action", None)
            for child in node.values():
                clean_conditions(child)
        elif isinstance(node, list):
            for child in node:
                clean_conditions(child)

    def clean_search_actions(node: object) -> None:
        if isinstance(node, dict):
            if node.get("operation") == "search_sources" and node.get("purpose_domain_id") is None:
                node.pop("purpose_domain_id", None)
                node.pop("purpose_question_id", None)
            for child in node.values():
                clean_search_actions(child)
        elif isinstance(node, list):
            for child in node:
                clean_search_actions(child)

    head = value.get("head")
    if isinstance(head, dict):
        action = head.get("next_action")
        if isinstance(action, dict):
            if action.get("supersedes") is None:
                action.pop("supersedes", None)
            if action.get("purpose_domain_id") is None:
                action.pop("purpose_domain_id", None)
                action.pop("purpose_question_id", None)
            if action.get("operation") in {"review_trial", "close_trial"}:
                for key in ("caller_inputs", "review_reference"):
                    if action.get(key) is None:
                        action.pop(key, None)
    data = value.get("data")
    if isinstance(data, dict) and data.get("current_checkpoint") is None:
        data.pop("current_checkpoint", None)
    if isinstance(data, dict) and data.get("evidence_sufficiency") is None:
        data.pop("evidence_sufficiency", None)
    clean_search_actions(data)
    clean_conditions(value.get("condition"))
    clean_conditions(data)
    return value


_META_KEYS = {
    "outcome",
    "phase",
    "state_revision",
    "review",
    "code",
    "condition",
    "expected_revision",
    "current_revision",
    "authoritative_wording",
    "continuation",
    "trial_dispositions",
    "terminal_counts",
    "trial_review",
    "closure",
    "review_required",
    "selected_evidence",
    "authority_required",
    "counters",
}


def _search_data_payload(value: dict[str, Any]) -> dict[str, Any]:
    data = {key: item for key, item in value.items() if key not in _META_KEYS}
    if isinstance(data.get("hits"), list):
        data["condition"] = value.get("condition")
        data["hits"] = [
            {
                key: item[key]
                for key in (
                    "source_id",
                    "source_role",
                    "source_label",
                    "page",
                    "start_line",
                    "end_line",
                    "preview",
                    "passage_ref",
                    "candidate_truncated",
                    "candidate_recovery",
                    "rank",
                    "within_source_rank",
                    "range",
                )
            }
            for item in data["hits"]
        ]
    receipt = data.get("search_receipt")
    if isinstance(receipt, dict):
        data["search_receipt"] = receipt["handle"]
    return data


def _public_review(value: object) -> object:
    if not isinstance(value, dict):
        return value
    review = dict(value)
    attribution = review.get("domain_attribution")
    if isinstance(attribution, list):
        review["domain_attribution"] = [
            {
                key: item[key]
                for key in ("domain_id", "attribution", "checkpoint_identity")
                if isinstance(item, dict) and key in item
            }
            for item in attribution
        ]
    return review


def _payload(tool: str, value: dict[str, Any]) -> dict[str, Any]:
    if tool == "get_status":
        return {
            key: _public_review(value[key]) if key == "trial_review" else value[key]
            for key in (
                "trial_dispositions",
                "terminal_counts",
                "selected_evidence",
                "working_checkpoint",
                "investigation",
                "main_report_reading",
                "conditions",
                "trial_review",
            )
            if key in value
        }
    if tool == "finalize_batch":
        return {
            key: value[key]
            for key in ("artifact", "trial_dispositions", "assessment_summary", "retry")
            if key in value
        }
    if tool == "review_trial":
        return {
            key: _public_review(value[key]) if key == "review" else value[key]
            for key in ("review", "result", "domain_findings", "retry")
            if key in value
        }
    if tool == "close_trial":
        return {key: value[key] for key in ("closure", "retry") if key in value}
    if tool == "search_sources":
        return _search_data_payload(value)
    data = {key: item for key, item in value.items() if key not in _META_KEYS}
    if tool == "search_sources_batch" and isinstance(data.get("results"), list):
        for item in data["results"]:
            result = item.get("result") if isinstance(item, dict) else None
            if isinstance(result, dict) and result.get("outcome") == "success":
                result["data"] = _search_data_payload(result["data"])
    if isinstance(data.get("search_receipt"), dict):
        receipt = data["search_receipt"]
        data["search_receipt"] = receipt["handle"]
    checkpoint = data.get("checkpoint")
    if tool == "save_domain_judgment" and isinstance(checkpoint, dict):
        data["checkpoint"] = {
            key: checkpoint[key]
            for key in (
                "identity",
                "trial_id",
                "domain_id",
                "judgment",
                "driver_questions",
                "evidence_sufficiency",
            )
        }
    if tool == "prepare_batch" and "batch" in data:
        batch = data.pop("batch")
        data.update(
            batch_identity=batch.get("identity"),
            conditions=batch.get("conditions", []),
            trials=batch.get("trials", []),
        )
    return data


def _condition(tool: str, value: dict[str, Any]) -> dict[str, Any]:
    condition = value.get("condition")
    if isinstance(condition, dict):
        return condition
    detail = condition or value.get("code") or "workflow condition"
    return {"code": str(value.get("code", "workflow_condition")), "detail": str(detail)}


def normalize(tool: str, value: dict[str, Any]) -> dict[str, Any]:
    value = public_source_references(value)
    outcome = str(value.get("outcome", "success"))
    head = PublicHead.model_validate(_head(value)).model_dump(mode="json")
    if outcome in {"success", "review_required"}:
        payload = _payload(tool, value)
        data = TypeAdapter(DataByTool[tool]).validate_python(payload).model_dump(mode="json")
        if outcome == "review_required":
            return _clean_public(
                {
                    "outcome": outcome,
                    "head": head,
                    "data": data,
                }
            )
        return _clean_public({"outcome": outcome, "head": head, "data": data})
    if outcome == "repair":
        return _clean_public(
            RepairReceipt.model_validate(
                {"outcome": outcome, "head": head, "repairs": value["repairs"]}
            ).model_dump(mode="json")
        )
    if outcome == "conflict":
        conflict = {
            "expected_revision": value["expected_revision"],
            "current_revision": value["current_revision"],
        }
        return _clean_public(
            ConflictReceipt.model_validate(
                {"outcome": outcome, "head": head, "conflict": conflict}
            ).model_dump(mode="json")
        )
    condition_type = ConditionByTool.get(tool, ConditionData)
    return _clean_public(
        TypeAdapter(_receipt(DataByTool[tool], condition_type, **_RECEIPT_OPTIONS[tool]))
        .validate_python(
            {"outcome": "condition", "head": head, "condition": _condition(tool, value)}
        )
        .model_dump(mode="json")
    )


def output_schema(name: str) -> dict[str, Any]:
    schema = TypeAdapter(
        _receipt(
            DataByTool[name],
            ConditionByTool.get(name, ConditionData),
            **_RECEIPT_OPTIONS[name],
        )
    ).json_schema()
    # MCP requires a root object even when JSON Schema's discriminated union
    # naturally emits a root ``oneOf``.
    return {"type": "object", **schema}


def validate_output(name: str, value: dict[str, Any]) -> dict[str, Any]:
    return _clean_public(
        TypeAdapter(
            _receipt(
                DataByTool[name],
                ConditionByTool.get(name, ConditionData),
                **_RECEIPT_OPTIONS[name],
            )
        )
        .validate_python(value)
        .model_dump(mode="json")
    )


__all__ = ["DataByTool", "TOOL_NAMES", "normalize", "output_schema", "validate_output"]
