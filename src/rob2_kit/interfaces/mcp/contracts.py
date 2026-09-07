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
    TypeAdapter,
    model_validator,
)
from pydantic.types import PositiveInt

from rob2_kit.application.contracts import TOOL_NAMES
from rob2_kit.models import Answer, Judgment, QuerySuggestion, ResponseFramework
from rob2_kit.workflow_models import (
    AssessableTargetRelation,
    ComparativeEffectResult,
    DomainId,
    EvidenceHandle,
    GroupBoundValuesResult,
    Identity,
    NormalizedCoordinate,
    OmissionDecision,
    QuestionId,
    RegistryOutcome,
    ReportedEndpoint,
    ResultClarity,
    ResultTarget,
    ReviewPurpose,
    SearchReceiptHandle,
    Source,
    SourceId,
    SourceRole,
    TrialId,
    UnavailableResult,
)


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PageNumber = Annotated[StrictInt, Field(ge=1)]


class SaveProposalAction(PublicModel):
    operation: Literal["save_proposal"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt
    caller_inputs: tuple[Literal["results"], ...]


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
    caller_inputs: tuple[Literal["answers", "multiple_concerns", "revision_basis"], ...]
    # Present only when the current Domain has a committed checkpoint that a
    # model-owned correction must replace.  The continuation names that exact
    # content identity; callers must not infer it from the unbounded history.
    supersedes: Identity | None = Field(
        default=None,
        description="Checkpoint replaced by this correction; omit otherwise.",
    )

    @model_validator(mode="after")
    def caller_inputs_match_phase(self) -> SaveDomainJudgmentAction:
        expected = (
            ("answers", "multiple_concerns", "revision_basis")
            if self.supersedes is not None
            else ("answers", "multiple_concerns")
        )
        if self.caller_inputs != expected:
            raise ValueError("caller_inputs must name exactly the fields required by this save")
        return self


class FinalizeBatchAction(PublicModel):
    operation: Literal["finalize_batch"]
    authority: Literal["host"]
    expected_revision: NonNegativeInt


class ResearcherReviewAction(PublicModel):
    operation: Literal["researcher_review"]
    authority: Literal["researcher"]
    reference: Identity
    purpose: ReviewPurpose


NextAction = Annotated[
    PrepareBatchAction
    | SaveProposalAction
    | GetDomainContextAction
    | SaveDomainJudgmentAction
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


class ConditionData(PublicModel):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


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
    "list_sources": {},
    "search_sources": {},
    "read_pages": {},
    "select_text_evidence": {},
    "render_page": {},
    "select_visual_evidence": {},
    "save_proposal": {"review": True, "repair": True, "conflict": True},
    "request_proposal_approval": {},
    "get_domain_context": {},
    "save_domain_judgment": {"repair": True, "conflict": True},
    "request_trial_terminal": {"conflict": True},
    "finalize_batch": {"conflict": True},
}


class UnreadableSourceCondition(PublicModel):
    code: Literal["unreadable_source"]
    trial_id: TrialId
    path: str = Field(min_length=1)


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
    UnreadableSourceCondition
    | InvalidRegistryCondition
    | RegistryReviewCondition
    | OmissionReviewCondition
    | NoSupportedSourcesCondition,
    Field(discriminator="code"),
]


class PublicCapturedTrial(PublicModel):
    id: TrialId
    label: str = Field(min_length=1)
    requested_outcome: str = Field(min_length=1)
    sources: tuple[Source, ...]
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
    failed: NonNegativeInt
    pending: NonNegativeInt


class SelectedNarrativeEvidence(PublicModel):
    kind: Literal["narrative"]
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    identity: Identity
    trial_id: TrialId
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    page: PageNumber
    # Exact line bounds are emitted for new search- and read-derived passages.
    # They remain optional for canonical evidence created by an older contract.
    start_line: PageNumber | None = None
    end_line: PageNumber | None = None
    start: NonNegativeInt | None = None
    end: NonNegativeInt | None = None
    quote: str = Field(min_length=1)
    inclusion_reason: (
        Literal[
            "result",
            "checkpoint",
            "active_domain_candidate",
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


class RenderProjection(PublicModel):
    identity: Identity
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    page: PageNumber
    png_sha256: Identity
    recipe: str = Field(min_length=1)


class SelectedFigureEvidence(PublicModel):
    kind: Literal["figure"]
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    identity: Identity
    trial_id: TrialId
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    render: RenderProjection
    transcription: str = Field(min_length=1)
    provenance: Literal["text_corroborated", "host_visual"]
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
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    page: PageNumber
    start_line: PageNumber
    end_line: PageNumber


class EvidenceRecovery(PublicModel):
    """Exact recovery metadata for text omitted from a context projection."""

    operation: Literal["read_pages"]
    trial_id: TrialId
    windows: tuple[EvidenceReadWindow, ...] = Field(min_length=1, max_length=20)


SelectedEvidence = Annotated[
    SelectedNarrativeEvidence | SelectedFigureEvidence,
    Field(discriminator="kind"),
]


class StatusData(PublicModel):
    trial_dispositions: dict[TrialId, Literal["pending", "assessed", "needs_input", "failed"]]
    terminal_counts: TerminalCounts
    selected_evidence: tuple[SelectedEvidence, ...]


class SourcesData(PublicModel):
    sources: tuple[Source, ...]


class SearchRange(PublicModel):
    start: PositiveInt
    end: PositiveInt


class SearchHit(PublicModel):
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    source_role: SourceRole
    source_label: str = Field(min_length=1)
    page: PageNumber
    start_line: PageNumber = Field(description="First matching read_pages line.")
    end_line: PageNumber = Field(description="Last matching read_pages line.")
    preview: str = Field(min_length=1)
    passage_ref: str = Field(
        pattern=r"^eh_[0-9a-f]{16}$",
        description="Passage reference.",
    )
    rank: PositiveInt = Field(description="Stable underlying candidate rank.")
    within_source_rank: PositiveInt = Field(description="Rank within the Source.")
    range: SearchRange


class SearchReceipt(PublicModel):
    """Full receipt retained only inside durable checkpoints."""

    identity: Identity
    handle: str = Field(pattern=r"^sr_[0-9a-f]{16}$")
    trial_id: TrialId
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix"]
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


class SearchNextAction(PublicModel):
    """One executable recovery refinement or continuation for a search response."""

    kind: Literal["refine", "continue"]
    operation: Literal["search_sources"]
    trial_id: TrialId
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix"]
    source_id: SourceId | None = None
    limit: PositiveInt
    cursor: str | None = None

    @model_validator(mode="after")
    def continuation_cursor_matches_kind(self) -> SearchNextAction:
        if self.kind == "continue" and self.cursor is None:
            raise ValueError("continuation action requires a cursor")
        if self.kind == "refine" and self.cursor is not None:
            raise ValueError("refinement action cannot carry a cursor")
        return self


class SearchDiagnostic(PublicModel):
    """Observable retrieval advice; it is never a scientific conclusion."""

    code: Literal["broad_any_truncated", "narrow_no_hits"]
    normalized_term_count: PositiveInt
    total_matches: NonNegativeInt
    candidate_count: NonNegativeInt
    returned_count: NonNegativeInt
    detail: str = Field(min_length=1)
    next_action: SearchNextAction


class SearchData(PublicModel):
    hits: tuple[SearchHit, ...]
    query: str = Field(min_length=1)
    mode: Literal["all", "phrase", "any", "prefix"]
    total_matches: NonNegativeInt
    truncated: StrictBool
    condition: Literal["no_hits"] | None
    search_receipt: SearchReceiptHandle
    session_id: Identity
    session_handle: str = Field(pattern=r"^ss_[0-9a-f]{16}$")
    matching_page_count: NonNegativeInt
    candidate_count: NonNegativeInt
    ranking_complete: StrictBool
    returned_rank_start: PositiveInt | None
    returned_rank_end: PositiveInt | None
    next_cursor: str | None
    exhausted: StrictBool
    diagnostic: SearchDiagnostic | None = None


class PageData(PublicModel):
    source_id: str = Field(
        pattern=r"^source_[0-9a-f]{64}$",
        description="Source.",
    )
    page: PageNumber
    numbered_text: str
    line_count: NonNegativeInt
    returned_start_line: PageNumber
    returned_end_line: NonNegativeInt
    truncated: StrictBool
    next_start_line: PageNumber | None = None
    passage_ref: str | None = Field(
        default=None,
        pattern=r"^eh_[0-9a-f]{16}$",
        description="Evidence ref, when non-empty.",
    )


class PagesData(PublicModel):
    pages: tuple[PageData, ...] = Field(min_length=1)


class TextEvidenceData(PublicModel):
    evidence: SelectedNarrativeEvidence


class VisualEvidenceData(PublicModel):
    evidence: SelectedFigureEvidence


class RenderData(PublicModel):
    render: RenderProjection


class ProposalData(PublicModel):
    proposal_identity: Identity
    retry: StrictBool = False


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


class CompactAnswerOption(PublicModel):
    """Lossless option semantics without repeated generated prose."""

    id: str = Field(pattern=r"^opt_[0-9a-f]{24}$")
    official_answer: Answer
    proposition: Literal["true", "false", "unknown"]
    certainty: Literal["certain", "probable", "unknown"]
    decision_table_value: Literal["yes", "no", "no_information"]
    anchor: str = Field(min_length=1)
    activates: tuple[str, ...] = ()
    meaning: str | None = None
    consequence: str | None = None


class DomainQuestionCard(PublicModel):
    """Compact model-facing card for one scientific-pack question."""

    id: QuestionId
    wording: str = Field(min_length=1)
    options: tuple[CompactAnswerOption, ...] = Field(min_length=1)
    active: StrictBool
    activation: QuestionActivation
    official_guidance: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    decision_rule: str = Field(min_length=1)
    evidence_needed: tuple[str, ...] = Field(min_length=1)
    no_information_rule: str = Field(min_length=1)
    considerations: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "Optional operational considerations and retrieval examples. Adapt, combine, "
            "or ignore them; they are examples, not a required query list."
        ),
    )
    invalid_shortcuts: tuple[str, ...] = Field(min_length=1)
    query_suggestions: tuple[QuerySuggestion, ...] = Field(min_length=1, max_length=8)


class DomainTableEvidence(PublicModel):
    kind: Literal["table"]
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
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


class DomainDerivedInput(PublicModel):
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    value: str = Field(min_length=1)


class DomainDerivedEvidence(PublicModel):
    kind: Literal["derived"]
    operation: Literal["difference", "ratio", "sum"]
    inputs: tuple[DomainDerivedInput, ...] = Field(min_length=1)
    value: str = Field(min_length=1)


class DomainNarrativeEvidence(PublicModel):
    """Domain-only narrative projection; canonical selected Evidence stays strict."""

    kind: Literal["narrative"]
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    identity: Identity
    trial_id: TrialId
    source_id: SourceId
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
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    identity: Identity


DomainResultEvidence = Annotated[
    DomainResultEvidenceReference | DomainDerivedEvidence,
    Field(discriminator="kind"),
]


class DomainCategoryValue(PublicModel):
    category_axes: tuple[str, ...] = Field(min_length=1)
    value: str = Field(min_length=1)


class DomainCategoryProfileResult(PublicModel):
    """Complete approved category profile without proof-oriented bindings."""

    form: Literal["single_group_category_profile"]
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
    mode: Literal["all", "phrase", "any", "prefix"]
    source_id: str | None = None
    limit: PositiveInt
    cursor: str = Field(pattern=r"^sc_[0-9a-f]{16}_[0-9]+$")


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
    deduplicated: NonNegativeInt = 0


class EvidenceWorkspaceGroup(PublicModel):
    inclusion_reason: Literal[
        "result",
        "checkpoint",
        "contradiction",
        "active_domain_candidate",
        "explicit_carry_forward",
    ]
    question_ids: tuple[QuestionId, ...] = ()
    evidence_handles: tuple[EvidenceHandle, ...] = ()


class EvidenceWorkspace(PublicModel):
    selection_policy_version: Literal["rob2-kit.domain-projection.v0.6"]
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


class DomainContextData(PublicModel):
    trial_id: TrialId
    domain_id: DomainId
    result: DomainResultChoice
    evidence: tuple[DomainEvidence, ...]
    answers: tuple[CheckpointAnswer, ...]
    # Only the active checkpoint is needed to form a model-owned revision.
    # Complete revision history remains in the canonical bundle, not in the
    # model-facing continuation context.
    current_checkpoint: Identity | None = Field(
        default=None,
        description="Exact active checkpoint identity, when this Domain has been saved before.",
    )
    guidance: tuple[str, ...]
    response_framework: ResponseFramework
    traps: tuple[str, ...]
    questions: tuple[DomainQuestionCard, ...]
    completion_rule: str = Field(min_length=1)
    evidence_workspace: EvidenceWorkspace
    comparison_cards: tuple[ComparisonCard, ...] = ()


class ComparisonPassageRef(PublicModel):
    handle: str = Field(pattern=r"^eh_[0-9a-f]{16}$")
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    page: PageNumber
    start_line: PageNumber
    end_line: PageNumber


class ComparisonPassageGroup(PublicModel):
    source_id: str = Field(pattern=r"^source_[0-9a-f]{64}$")
    source_role: SourceRole
    source_label: str = Field(min_length=1)
    passages: tuple[ComparisonPassageRef, ...] = ()


class ComparisonSlot(PublicModel):
    name: str = Field(min_length=1)
    status: Literal["supported", "unknown", "conflicted"]
    value: str | None = None
    passages: tuple[ComparisonPassageRef, ...] = ()


class ComparisonCard(PublicModel):
    card_id: str = Field(min_length=1)
    question_id: QuestionId
    result_identity: Identity
    passage_groups: tuple[ComparisonPassageGroup, ...] = ()
    slots: tuple[ComparisonSlot, ...] = Field(min_length=1)
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
    text: str = Field(min_length=1)
    search_receipt: Identity


CheckpointEvidenceUse = Annotated[
    DirectCheckpointEvidenceUse | AbsenceCheckpointEvidenceUse | LimitationCheckpointBasis,
    Field(discriminator="kind"),
]


class MissingDataScope(PublicModel):
    arm: str = Field(min_length=1)
    population: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    time_point: str = Field(min_length=1)


class MissingDataReconciledRow(PublicModel):
    scope: MissingDataScope
    randomized: StrictInt | None = Field(default=None, ge=0)
    observed: StrictInt | None = Field(default=None, ge=0)
    analyzed: StrictInt | None = Field(default=None, ge=0)
    imputed: StrictInt | None = Field(default=None, ge=0)
    exclusions: tuple[str, ...] = ()
    basis: tuple[Identity, ...] = Field(min_length=1)
    missing: StrictInt | None = Field(default=None, ge=0)
    missing_fraction: float | None = Field(default=None, ge=0)


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


DomainContextData.model_rebuild()


class NewEvidenceRevision(PublicModel):
    kind: Literal["new_evidence"]
    evidence: Identity
    rationale: str = Field(min_length=1)


class SelfCorrectionRevision(PublicModel):
    kind: Literal["self_correction"]
    rationale: str = Field(min_length=1)


CheckpointRevisionBasis = Annotated[
    NewEvidenceRevision | SelfCorrectionRevision,
    Field(discriminator="kind"),
]


class CheckpointSearchAccount(SearchReceipt):
    pass


class Checkpoint(PublicModel):
    identity: Identity
    trial_id: TrialId
    domain_id: DomainId
    answers: tuple[CheckpointAnswer, ...]
    judgment: Judgment
    active_questions: tuple[str, ...]
    inactive_questions: tuple[str, ...]
    search_accounts: tuple[CheckpointSearchAccount, ...]
    trace: tuple[str, ...]
    observed_at: str = Field(min_length=1)
    supersedes: Identity | None = None
    revision_basis: CheckpointRevisionBasis | None = None


class DomainCheckpointSummary(PublicModel):
    identity: Identity
    trial_id: TrialId
    domain_id: DomainId
    judgment: Judgment


class DomainJudgmentData(PublicModel):
    checkpoint: DomainCheckpointSummary
    trial_completed: StrictBool = Field(
        default=False,
        description=(
            "True only when this save completed the fifth Domain and froze the Trial's final "
            "AssessmentSnapshot."
        ),
    )
    retry: StrictBool = False


class NeedsInputTerminalData(PublicModel):
    identity: Identity
    trial_id: TrialId
    disposition: Literal["needs_input"]
    reason: str = Field(min_length=1)
    missing_facts: tuple[str, ...] = Field(min_length=1)


class FailedTerminalData(PublicModel):
    identity: Identity
    trial_id: TrialId
    disposition: Literal["failed"]
    reason: str = Field(min_length=1)
    facts: tuple[str, ...] = Field(min_length=1)


TerminalData = Annotated[
    NeedsInputTerminalData | FailedTerminalData,
    Field(discriminator="disposition"),
]


class TerminalReceiptData(PublicModel):
    terminal: TerminalData
    retry: StrictBool = False


class Artifact(PublicModel):
    path: str = Field(min_length=1)
    identity: Identity
    sha256: Identity
    files: tuple[str, ...]


class AssessmentSummary(PublicModel):
    overall: Judgment
    domains: dict[DomainId, Judgment] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def includes_every_domain(self) -> AssessmentSummary:
        if set(self.domains) != set(get_args(DomainId)):
            raise ValueError("assessment summary must include exactly the five Domains")
        return self


class FinalizeData(PublicModel):
    artifact: Artifact
    trial_dispositions: dict[TrialId, Literal["pending", "assessed", "needs_input", "failed"]] = {}
    assessment_summary: dict[TrialId, AssessmentSummary]
    retry: StrictBool = False


DataByTool: Final = {
    "prepare_batch": PrepareData,
    "get_status": StatusData,
    "list_sources": SourcesData,
    "search_sources": SearchData,
    "read_pages": PagesData,
    "select_text_evidence": TextEvidenceData,
    "render_page": RenderData,
    "select_visual_evidence": VisualEvidenceData,
    "save_proposal": ProposalData,
    "request_proposal_approval": ProposalApprovalData,
    "get_domain_context": DomainContextData,
    "save_domain_judgment": DomainJudgmentData,
    "request_trial_terminal": TerminalReceiptData,
    "finalize_batch": FinalizeData,
}
ConditionByTool: Final = {
    "search_sources": SearchCursorCondition,
    "finalize_batch": ConditionData,
    "request_proposal_approval": ProposalApprovalCondition,
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

    head = value.get("head")
    if isinstance(head, dict):
        action = head.get("next_action")
        if isinstance(action, dict) and action.get("supersedes") is None:
            action.pop("supersedes", None)
    data = value.get("data")
    if isinstance(data, dict) and data.get("current_checkpoint") is None:
        data.pop("current_checkpoint", None)
    return value


_META_KEYS = {
    "outcome",
    "phase",
    "state_revision",
    "review",
    "repairs",
    "code",
    "condition",
    "expected_revision",
    "current_revision",
    "authoritative_wording",
    "continuation",
    "trial_dispositions",
    "terminal_counts",
    "review_required",
    "selected_evidence",
    "authority_required",
    "counters",
}


def _payload(tool: str, value: dict[str, Any]) -> dict[str, Any]:
    if tool == "get_status":
        return {
            key: value[key]
            for key in (
                "trial_dispositions",
                "terminal_counts",
                "selected_evidence",
            )
            if key in value
        }
    if tool == "finalize_batch":
        return {
            key: value[key]
            for key in ("artifact", "trial_dispositions", "assessment_summary", "retry")
            if key in value
        }
    data = {key: item for key, item in value.items() if key not in _META_KEYS}
    if tool == "search_sources" and isinstance(data.get("hits"), list):
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
                    "rank",
                    "within_source_rank",
                    "range",
                )
            }
            for item in data["hits"]
        ]
    if isinstance(data.get("search_receipt"), dict):
        receipt = data["search_receipt"]
        data["search_receipt"] = receipt["handle"]
    checkpoint = data.get("checkpoint")
    if tool == "save_domain_judgment" and isinstance(checkpoint, dict):
        data["checkpoint"] = {
            key: checkpoint[key] for key in ("identity", "trial_id", "domain_id", "judgment")
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
    outcome = str(value.get("outcome", "success"))
    head = PublicHead.model_validate(_head(value)).model_dump(mode="json")
    if outcome in {"success", "review_required"}:
        payload = _payload(tool, value)
        if tool == "request_trial_terminal" and isinstance(payload.get("terminal"), dict):
            terminal = dict(payload["terminal"])
            if terminal.get("disposition") == "failed":
                terminal["facts"] = terminal.pop("missing_facts", [])
            payload["terminal"] = terminal
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
