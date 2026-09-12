"""Closed, immutable v0.5 workflow models.

The application stores JSON, but it must not pass JSON-shaped dictionaries between
workflow boundaries.  This module is the small vocabulary shared by the adapters,
the ledger, and the independent bundle verifier.  Every persisted model has a
content identity derived from its other fields; callers cannot choose an identity.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.functional_validators import AfterValidator

from .models import canonical_json_bytes


class StrictModel(BaseModel):
    """The wire/storage base: closed and immutable with strict semantic scalars."""

    # ``strict`` is intentionally left at Pydantic's boundary default: JSON
    # arrays become immutable tuples, while the closed field set remains
    # enforced.  Scalar semantic types below carry their own constraints.
    model_config = ConfigDict(extra="forbid", frozen=True)


Identity = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


NonBlankText = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_nonblank),
]
VisualTranscription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
TrialId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
SourceId = Annotated[str, StringConstraints(pattern=r"^source_[0-9a-f]{64}$")]
SourceHandle = Annotated[str, StringConstraints(pattern=r"^sh_[0-9a-f]{16}$")]
DomainId = Literal[
    "domain:randomization",
    "domain:deviations",
    "domain:missing",
    "domain:measurement",
    "domain:selection",
]
QuestionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
# Handles are disposable derivative pointers (the content identity remains in
# the referenced Canonical Evidence record).  The application deliberately
# uses a short, opaque ``eh_`` token for them.
EvidenceHandle = Annotated[str, StringConstraints(pattern=r"^eh_[0-9a-f]{16}$")]
# Search receipts are disposable server-issued navigation tokens.  Their
# content identity stays internal to the canonical ledger; callers submit the
# short handle returned by ``search_sources`` and the application resolves it
# before persisting any checkpoint.
SearchReceiptHandle = Annotated[str, StringConstraints(pattern=r"^sr_[0-9a-f]{16}$")]


def _strict_json_int(value: Any) -> Any:
    if type(value) is not int:
        raise ValueError("JSON integer must be encoded as an integer")
    return value


PageNumber = Annotated[StrictInt, BeforeValidator(_strict_json_int), Field(ge=1)]
NormalizedCoordinate = Annotated[StrictFloat, Field(ge=0, le=1)]
ExpectedRevision = Annotated[StrictInt, BeforeValidator(_strict_json_int), Field(ge=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class MissingDataRow(StrictModel):
    """One scope-matched participant-flow count supplied for Domain 3."""

    arm: NonBlankText = Field(description="Trial arm for this participant-flow row.")
    population: NonBlankText = Field(
        description="Population represented by this participant-flow row."
    )
    unit: NonBlankText = Field(description="Unit counted, such as participants.")
    time_point: NonBlankText = Field(description="Outcome time point represented by this row.")
    randomized: NonNegativeInt | None = Field(
        default=None, description="Number randomized when reported."
    )
    observed: NonNegativeInt | None = Field(
        default=None, description="Number with observed outcome data when reported."
    )
    analyzed: NonNegativeInt | None = Field(
        default=None, description="Number included in the analysis when reported."
    )
    imputed: NonNegativeInt | None = Field(
        default=None, description="Number whose outcome data were imputed when reported."
    )
    exclusions: tuple[NonBlankText, ...] = Field(
        default=(), description="Reported reasons for exclusion or missingness."
    )
    basis: tuple[EvidenceHandle, ...] = Field(
        default=(),
        description=(
            "Evidence handles supporting this row. When saving an answer, omit to reuse "
            "all Evidence handles attached to that answer. A get_domain_context preview "
            "requires explicit current-Trial Evidence handles for every row."
        ),
    )


RelativePath = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4096),
    AfterValidator(
        lambda value: (
            value.replace("\\", "/")
            if not PurePosixPath(value.replace("\\", "/")).is_absolute()
            and ".." not in PurePosixPath(value.replace("\\", "/")).parts
            and not value.replace("\\", "/").startswith("/")
            else (_ for _ in ()).throw(ValueError("path must be a safe relative path"))
        )
    ),
]


def _utc(value: object) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("timestamp must be ISO-8601") from error
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


UTCTimestamp = Annotated[datetime, BeforeValidator(_utc)]


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


_ModelT = TypeVar("_ModelT", bound=StrictModel)


def _identity(model: _ModelT, supplied: str | None) -> _ModelT:
    expected = _digest(model.model_dump(mode="python", exclude={"identity"}, exclude_none=True))
    if supplied is not None and supplied != expected:
        raise ValueError("identity does not match canonical content")
    return model.model_copy(update={"identity": expected})


def exact_relation_rationale(target_name: str, reported_name: str) -> str:
    return (
        f"Exact relation: target outcome '{target_name}' and reported endpoint "
        f"'{reported_name}' match after Unicode, whitespace, case, and hyphen normalization."
    )


def _unique(values: tuple[Any, ...], label: str = "items") -> tuple[Any, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")
    return values


def _unique_field(values: tuple[Any, ...], field: str, label: str) -> tuple[Any, ...]:
    keys = tuple(getattr(item, field) for item in values)
    _unique(keys, label)
    return values


class SourceOrigin(StrEnum):
    LOCAL_DOSSIER = "local_dossier"
    REGISTRY = "registry"
    RESEARCHER_PROVIDED = "researcher_provided"


class SourceRole(StrEnum):
    MAIN_ARTICLE = "main_article"
    REGISTRY = "registry"
    SUPPLEMENT = "supplement"
    SAP = "sap"
    PROTOCOL = "protocol"
    OTHER = "other"


class Source(StrictModel):
    id: SourceId
    trial_id: TrialId
    role: SourceRole
    label: str = Field(min_length=1)
    logical_path: RelativePath
    sha256: Identity
    media_type: str = Field(min_length=1)
    page_count: PageNumber
    projection_hash: Identity
    origin: SourceOrigin = SourceOrigin.LOCAL_DOSSIER

    @model_validator(mode="after")
    def identity_matches(self) -> Source:
        # SourceId is scoped by Trial, path, and bytes; projection_hash covers pages.
        expected = (
            "source_"
            + hashlib.sha256(
                f"{self.trial_id}\0{self.logical_path}\0{self.sha256}".encode()
            ).hexdigest()
        )
        if self.id != expected:
            raise ValueError("Source id does not match trial, path, and bytes")
        return self


class TrialDeclaration(StrictModel):
    id: TrialId
    label: str = Field(min_length=1)
    requested_outcome: str = Field(min_length=1)

    @field_validator("label", "requested_outcome")
    @classmethod
    def text_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain non-whitespace content")
        return value


class OmissionReason(StrEnum):
    DUPLICATE = "duplicate"
    IRRELEVANT = "irrelevant"
    UNREADABLE = "unreadable"
    RESTRICTED = "restricted"
    OTHER = "other"


class OmissionDecision(StrictModel):
    path: RelativePath
    reason: OmissionReason
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def rationale_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must contain non-whitespace text")
        return value


class RegistryMatched(StrictModel):
    kind: Literal["matched"]
    registry_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    retrieved_at: UTCTimestamp


class RegistryNotFound(StrictModel):
    kind: Literal["not_found"]
    query: str = Field(min_length=1)
    retrieved_at: UTCTimestamp


class RegistryAmbiguous(StrictModel):
    kind: Literal["ambiguous"]
    query: str = Field(min_length=1)
    candidates: tuple[str, ...] = Field(min_length=2)
    retrieved_at: UTCTimestamp

    @field_validator("candidates")
    @classmethod
    def candidate_ids_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "registry candidates")


class RegistryUnavailable(StrictModel):
    kind: Literal["unavailable"]
    query: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    retrieved_at: UTCTimestamp


class RegistryContradiction(StrictModel):
    kind: Literal["contradiction"]
    registry_id: str = Field(min_length=1)
    facts: tuple[str, ...] = Field(min_length=1)
    retrieved_at: UTCTimestamp


RegistryOutcome = Annotated[
    RegistryMatched
    | RegistryNotFound
    | RegistryAmbiguous
    | RegistryUnavailable
    | RegistryContradiction,
    Field(discriminator="kind"),
]


class IntakeBlocker(StrictModel):
    kind: Literal["blocker"]
    code: str = Field(min_length=1)
    trial_id: TrialId | None = None
    detail: str = Field(min_length=1)


class IntakeReviewCondition(StrictModel):
    kind: Literal["review_condition"]
    code: str = Field(min_length=1)
    trial_id: TrialId | None = None
    detail: str = Field(min_length=1)


IntakeCondition = Annotated[IntakeBlocker | IntakeReviewCondition, Field(discriminator="kind")]


class CapturedTrial(StrictModel):
    id: TrialId
    label: str = Field(min_length=1)
    requested_outcome: str = Field(min_length=1)
    sources: tuple[Source, ...]
    registry: RegistryOutcome
    omissions: tuple[OmissionDecision, ...] = ()
    identity: Identity | None = None

    @field_validator("sources")
    @classmethod
    def sources_unique(cls, value: tuple[Source, ...]) -> tuple[Source, ...]:
        return _unique_field(value, "id", "Sources")

    @field_validator("omissions")
    @classmethod
    def omissions_unique(cls, value: tuple[OmissionDecision, ...]) -> tuple[OmissionDecision, ...]:
        return _unique_field(value, "path", "omissions")

    @model_validator(mode="after")
    def identity_matches(self) -> CapturedTrial:
        return _identity(self, self.identity)


class CapturedBatch(StrictModel):
    trials: tuple[CapturedTrial, ...] = Field(min_length=1)
    conditions: tuple[IntakeCondition, ...] = ()
    identity: Identity | None = None

    @field_validator("trials")
    @classmethod
    def trials_unique(cls, value: tuple[CapturedTrial, ...]) -> tuple[CapturedTrial, ...]:
        return _unique_field(value, "id", "Trials")

    @model_validator(mode="after")
    def identity_matches(self) -> CapturedBatch:
        return _identity(self, self.identity)


class ReviewPurpose(StrEnum):
    PROPOSAL = "proposal"


class ReviewAcknowledgment(StrictModel):
    review_identity: Identity
    purpose: ReviewPurpose
    caller: str = Field(min_length=1)
    method: str = Field(min_length=1)
    observed_at: UTCTimestamp
    workflow_basis: NonNegativeInt
    identity: Identity | None = None

    @field_validator("caller", "method")
    @classmethod
    def text_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain non-whitespace content")
        return value

    @model_validator(mode="after")
    def identity_matches(self) -> ReviewAcknowledgment:
        return _identity(self, self.identity)


class OutcomeMeasurement(StrictModel):
    metric: NonBlankText
    method: NonBlankText


class OutcomeMeasurementDraft(StrictModel):
    """Caller-owned measurement method; the target metric comes from Intake."""

    method: NonBlankText = Field(
        description="Source-supported method used to measure the requested outcome.",
    )


class DescribedTiming(StrictModel):
    kind: Literal["described"] = Field(description="Timing expressed as a descriptive window.")
    description: NonBlankText = Field(
        description="Source-supported description of the target time point or window.",
    )


class QuantifiedTiming(StrictModel):
    kind: Literal["quantified"] = Field(description="Use when timing has a numeric value and unit.")
    description: NonBlankText = Field(
        description=(
            "Required source-supported timing description, including the time origin or window; "
            "for example, '15 days after randomization'. Supply alongside value and unit."
        ),
    )
    value: NonBlankText = Field(description="Source-reported timing value.")
    unit: NonBlankText = Field(description="Source-reported timing unit.")


ResultTiming = Annotated[
    DescribedTiming | QuantifiedTiming,
    Field(discriminator="kind"),
]


class ComparisonGroup(StrictModel):
    id: NonBlankText = Field(
        description="Caller-owned structural identifier used to reference this comparison group.",
    )
    assignment: NonBlankText = Field(
        description="Source-supported description of the intervention assigned to this group.",
    )


class ResultTarget(StrictModel):
    outcome_definition: NonBlankText
    measurement: OutcomeMeasurement
    time_point_or_window: ResultTiming
    effect_of_interest: Literal["assignment"]
    comparison_groups: tuple[ComparisonGroup, ...] = Field(min_length=2)
    intended_analysis_population: NonBlankText
    intended_effect_measure: NonBlankText


class ResultTargetDraft(StrictModel):
    """Proposal target fields that require researcher interpretation."""

    measurement: OutcomeMeasurementDraft = Field(
        description="How the requested outcome is measured for this Trial.",
    )
    time_point_or_window: ResultTiming = Field(
        description="Source-supported timing or analysis window for the target Result.",
    )
    comparison_groups: tuple[ComparisonGroup, ...] = Field(
        min_length=2,
        description="Every randomized group compared by the target Result.",
    )
    baseline_subgroup: NonBlankText | None = Field(
        description=(
            "Baseline-defined restriction identifying the target subgroup, or null for the "
            "full randomized comparison population. Analysis exclusions are recorded under "
            "reported.analysis_population."
        ),
    )
    intended_effect_measure: NonBlankText = Field(
        description="Effect measure intended for the target comparison.",
    )


def _same_relation_name(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value)
        for character in "‐‑‒–—":
            value = value.replace(character, "-")
        return " ".join(value.casefold().replace("-", " ").split())

    return normalize(left) == normalize(right)


class ResultApplicability(StrictModel):
    """Host's source-grounded applicability assessment for the installed pack."""

    design: Literal[
        "individual_parallel",
        "cluster_randomized",
        "crossover",
        "unclear",
    ] = Field(description="Source-grounded randomization and trial design.")
    rationale: NonBlankText = Field(
        description="Source facts supporting the design, or the unresolved design information."
    )
    evidence: tuple[EvidenceHandle, ...] = Field(
        default=(),
        description="Inspected same-Trial Evidence handles; required when the design is known.",
    )

    @model_validator(mode="after")
    def known_design_needs_basis(self) -> ResultApplicability:
        if self.design != "unclear" and not self.evidence:
            raise ValueError("known trial design requires source Evidence")
        return self


class TargetRelation(StrEnum):
    EXACT = "exact"
    BROADER = "broader"
    NARROWER = "narrower"
    COMPONENT = "component"
    RELATED = "related"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class AssessableTargetRelation(StrEnum):
    """Relations that describe a result eligible for downstream assessment."""

    EXACT = TargetRelation.EXACT
    BROADER = TargetRelation.BROADER
    NARROWER = TargetRelation.NARROWER
    COMPONENT = TargetRelation.COMPONENT
    RELATED = TargetRelation.RELATED


class ResultClarity(StrictModel):
    outcome_definition: Literal["specified", "unclear", "unavailable"]
    measurement: Literal["specified", "unclear", "unavailable"]
    time_point: Literal["specified", "unclear", "unavailable"]
    analysis_population: Literal["specified", "unclear", "unavailable"]
    comparison_groups: Literal["specified", "unclear", "unavailable"]
    effect_measure: Literal["specified", "unclear", "unavailable"]
    source_table_meaning: Literal["specified", "unclear", "unavailable"]
    eligible_result_choice: Literal["specified", "unclear", "unavailable"]


class GroupResultValue(StrictModel):
    group_id: NonBlankText = Field(
        description=(
            "Structural reference to a target comparison-group id; it must match a target "
            "id but does not require a separate Source Evidence mapping."
        ),
    )
    statistic: NonBlankText = Field(description="Source-reported statistic label for this group.")
    value: NonBlankText = Field(description="Source-reported value for this group.")
    unit: NonBlankText = Field(description="Source-reported unit for this group value.")


class ReportedEndpoint(StrictModel):
    name: NonBlankText = Field(
        description=(
            "Source-reported endpoint label supported by selected Evidence. Keep the reported "
            "label distinct from the requested outcome. Explain correspondence in "
            "relation_rationale."
        ),
    )
    definition: NonBlankText | None = Field(
        default=None,
        description=(
            "Complete Source definition, including event set, time origin or window, population, "
            "and measurement or state criteria; omit when no selected passage explicitly ties "
            "a coherent definition to this endpoint label. Never borrow a component or related "
            "endpoint definition."
        ),
    )


class ComparativeEffectResult(StrictModel):
    form: Literal["comparative_effect"] = Field(
        description="A source-reported between-group effect estimate.",
    )
    effect_measure: NonBlankText = Field(description="Source-reported effect-measure label.")
    estimate: NonBlankText = Field(
        description="Source-reported comparative estimate; put its interval in precision."
    )
    precision: NonBlankText | None = Field(
        default=None,
        description="Source-reported precision interval or uncertainty; omit when absent.",
    )
    analysis_population: NonBlankText = Field(
        description=(
            "Summarize who was included in this estimate and any reported exclusions, using the "
            "selected passages. You may combine and paraphrase information across passages. "
            "Include participant inclusion or exclusion details when available; an analysis "
            "label alone is insufficient."
        ),
    )
    endpoint: ReportedEndpoint = Field(
        description="Endpoint identified by the same Evidence as the quantitative tuple.",
    )
    group_values: tuple[GroupResultValue, ...] = Field(
        default=(),
        description=(
            "Optional source-reported values for each randomized group. Omit these when the "
            "comparative estimate is complete and the source does not state an unambiguous "
            "statistic and unit for every group."
        ),
    )

    @model_validator(mode="after")
    def complete_optional_group_values(self) -> ComparativeEffectResult:
        if len(self.group_values) == 1:
            raise ValueError("group_values must be omitted or contain at least two groups")
        return self


class GroupBoundValuesResult(StrictModel):
    form: Literal["group_bound_values"] = Field(
        description="Source-reported values bound to each randomized group.",
    )
    analysis_population: NonBlankText = Field(
        description=(
            "Summarize who was included in this estimate and any reported exclusions, using the "
            "selected passages. You may combine and paraphrase information across passages. "
            "Include participant inclusion or exclusion details when available; an analysis "
            "label alone is insufficient."
        ),
    )
    endpoint: ReportedEndpoint = Field(
        description="Endpoint identified by the same Evidence as the group values.",
    )
    values: tuple[GroupResultValue, ...] = Field(
        min_length=2,
        description="One complete source-reported value for every randomized group.",
    )


class CategoryValue(StrictModel):
    """One complete source-located cell in a categorical result profile.

    A one-arm profile records only the supported randomized arm. Comparator
    categories must never be invented to satisfy a comparative shape.

    The source cell is copied as one opaque value. Do not invent a statistic
    or unit label that the selected material does not contain.
    """

    # Every non-treatment axis needed to locate the cell, such as event row
    # plus grade column. Treatment groups remain represented by group_id.
    category_axes: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Ordered complete non-treatment row, column, or series labels locating one table cell."
        ),
    )
    value: NonBlankText = Field(description="Value in this category cell.")

    @field_validator("category_axes")
    @classmethod
    def category_axes_are_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("category_axes must contain non-empty labels")
        return value


class CategoryProfileResult(StrictModel):
    """A complete categorical profile reported for one supported randomized arm.

    Use this form when a source fully reports category cells for one arm even
    if comparator values are absent. Keep every randomized arm in the target,
    set ``group_id`` to the supported arm, and do not invent comparator cells.
    A complete assessable profile is preferred to an unavailable result.
    """

    form: Literal["single_group_category_profile"] = Field(
        description="A complete source-reported category profile for one randomized group.",
    )
    analysis_population: NonBlankText = Field(
        description=(
            "Summarize who was included in this estimate and any reported exclusions, using the "
            "selected passages. You may combine and paraphrase information across passages. "
            "Include participant inclusion or exclusion details when available; an analysis "
            "label alone is insufficient."
        ),
    )
    endpoint: ReportedEndpoint = Field(
        description="Endpoint identified by the same Evidence as the category profile.",
    )
    group_id: NonBlankText = Field(
        description=(
            "Structural reference to the target comparison-group id; it must match a target "
            "id but does not require a separate Source Evidence mapping."
        ),
    )
    denominator_basis: NonBlankText = Field(
        description="Population or denominator shared by every category cell.",
    )
    category_axis_names: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Structural ordered names of the non-treatment dimensions shared by every category "
            "cell; one name is valid for a one-dimensional profile and these names do not "
            "require separate Source Evidence mappings. Source labels remain in category_axes."
        ),
    )
    categories: tuple[CategoryValue, ...] = Field(
        min_length=1,
        description="Every source-reported category cell in the selected profile.",
    )

    @model_validator(mode="before")
    @classmethod
    def category_cells_use_one_closed_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not isinstance(value.get("categories"), (list, tuple)):
            return value
        allowed = {"category_axes", "value"}
        unexpected = {
            key
            for item in value["categories"]
            if isinstance(item, dict)
            for key in item
            if key not in allowed
        }
        if unexpected:
            raise ValueError(
                "each category contains only category_axes and value; select Evidence before "
                "save_proposal and do not repeat Evidence handles inside category cells"
            )
        return value

    @model_validator(mode="after")
    def category_cells_are_unique(self) -> CategoryProfileResult:
        if any(not name.strip() for name in self.category_axis_names):
            raise ValueError("category_axis_names must contain non-empty labels")
        if len(self.category_axis_names) != len(set(self.category_axis_names)):
            raise ValueError("category_axis_names must not repeat an axis name")
        if any(
            len(item.category_axes) != len(self.category_axis_names) for item in self.categories
        ):
            raise ValueError("every category_axes tuple must match category_axis_names arity")
        keys = [item.category_axes for item in self.categories]
        if len(keys) != len(set(keys)):
            raise ValueError("categories must not repeat the same category axes")
        return self


class UnavailableReportedResult(StrictModel):
    form: Literal["unavailable"]
    reason: NonBlankText
    explanation: NonBlankText


ReportedResult = Annotated[
    ComparativeEffectResult
    | GroupBoundValuesResult
    | CategoryProfileResult
    | UnavailableReportedResult,
    Field(discriminator="form"),
]


class NarrativeEvidence(StrictModel):
    """A server-selected narrative passage.

    The handle already resolves to an immutable, page-preserving quote.  Do not
    make the model copy that quote into a second set of clauses or author
    source-to-result mappings: those duplicates created a second, weaker proof
    surface at Proposal time.  Structured Result values must occur in the
    selected passage (or use typed Derived Evidence).
    """

    kind: Literal["narrative"]
    handle: EvidenceHandle


class TableEvidence(StrictModel):
    kind: Literal["table"]
    handle: EvidenceHandle
    basis: Literal["text", "visual"]
    title: NonBlankText = Field(
        description="Exact or normalization-equivalent title copied from selected table material.",
    )
    scope: NonBlankText = Field(
        description="Exact or normalization-equivalent scope copied from selected table material.",
    )
    cohort: NonBlankText = Field(
        description=(
            "Exact or normalization-equivalent cohort label copied from selected table material."
        ),
    )
    row: NonBlankText = Field(
        description=(
            "Exact or normalization-equivalent row label copied from selected table material."
        ),
    )
    columns: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Complete ordered column labels copied exactly or normalization-equivalently "
            "from selected table material."
        ),
    )
    group_or_category_axes: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Complete ordered category or series labels copied exactly or "
            "normalization-equivalently from selected table material; preserve every "
            "applicable dimension."
        ),
    )
    cells: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Reported cell labels or values copied exactly or normalization-equivalently "
            "from selected table material."
        ),
    )
    units: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description="Exact or normalization-equivalent units copied from selected table material.",
    )
    denominators: tuple[NonBlankText, ...] = Field(
        min_length=1,
        description=(
            "Exact or normalization-equivalent denominators copied from selected table material."
        ),
    )
    footnotes: tuple[NonBlankText, ...] = Field(
        default=(),
        description=(
            "Applicable footnotes copied exactly or normalization-equivalently from "
            "selected table material."
        ),
    )


class FigureEvidence(StrictModel):
    kind: Literal["figure"]
    handle: EvidenceHandle
    render_identity: Identity
    region: tuple[
        NormalizedCoordinate,
        NormalizedCoordinate,
        NormalizedCoordinate,
        NormalizedCoordinate,
    ]
    transcription: VisualTranscription
    provenance: Literal["text_corroborated", "host_visual"]


class FigureEvidenceDraft(StrictModel):
    """A server-owned figure projection selected by handle."""

    kind: Literal["figure"]
    handle: EvidenceHandle


class DerivedEvidence(StrictModel):
    kind: Literal["derived"]
    operation: Literal["difference", "ratio", "sum"]
    inputs: tuple[DerivedInput, ...] = Field(min_length=1)
    value: NonBlankText


class DerivedInput(StrictModel):
    handle: EvidenceHandle
    value: NonBlankText


ResultEvidence = Annotated[
    NarrativeEvidence | TableEvidence | FigureEvidence | DerivedEvidence,
    Field(discriminator="kind"),
]

ResultEvidenceDraft = Annotated[
    NarrativeEvidence | TableEvidence | FigureEvidenceDraft | DerivedEvidence,
    Field(discriminator="kind"),
]


class ResultFieldRef(StrictModel):
    """A JSON-pointer path to one exact leaf in target or reported Result data."""

    path: str = Field(pattern=r"^/(target|reported)(/[A-Za-z0-9_-]+)*$")


class FieldEvidenceBinding(StrictModel):
    field: ResultFieldRef
    evidence_index: NonNegativeInt
    value_digest: Identity


class AssessableResult(StrictModel):
    kind: Literal["assessable"]
    trial_id: TrialId
    requested_outcome: NonBlankText
    relation: AssessableTargetRelation = Field(
        description=(
            "Relation to the complete requested target: exact means equivalent scientific scope; "
            "broader is a superset, narrower is a subset or has additional restrictions, "
            "component is one constituent, and related is other overlap. Added criteria make "
            "a candidate narrower. Explain material differences; matching numbers do not prove "
            "equivalence."
        ),
    )
    relation_rationale: NonBlankText
    applicability: ResultApplicability | None = None
    target: ResultTarget
    reported: Annotated[
        ComparativeEffectResult | GroupBoundValuesResult | CategoryProfileResult,
        Field(discriminator="form"),
    ]
    clarity: ResultClarity
    evidence: tuple[ResultEvidence, ...] = Field(min_length=1)
    bindings: tuple[FieldEvidenceBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_bindings(self) -> AssessableResult:
        keys = tuple(item.field.path for item in self.bindings)
        _unique(keys, "result field bindings")
        if self.relation == AssessableTargetRelation.EXACT and _same_relation_name(
            self.target.outcome_definition, self.reported.endpoint.name
        ):
            expected = exact_relation_rationale(
                self.target.outcome_definition, self.reported.endpoint.name
            )
            if self.relation_rationale != expected:
                raise ValueError(
                    "exact relation_rationale must use the server-provable "
                    "normalized-match sentence"
                )
        return self


class AssessableResultDraft(StrictModel):
    """The MCP proposal form before the server adds canonical leaf digests."""

    kind: Literal["assessable"] = Field(
        description="Use when a complete source-reported Result candidate exists.",
    )
    trial_id: TrialId = Field(description="Server-issued Trial ID for this Result card.")
    relation: AssessableTargetRelation = Field(
        description=(
            "Use exact for equivalent complete Result scope. Broader when scope is a "
            "superset; narrower "
            "is a subset or has additional restrictions; component is one constituent; related "
            "is other overlap. Added criteria make a candidate narrower. Compare event set, time, "
            "population, measurement, state criteria, comparison, analysis, and effect scope; "
            "matching numbers do not prove "
            "equivalence. Resubmit if another candidate is better."
        ),
    )
    relation_rationale: NonBlankText | None = Field(
        default=None,
        description=(
            "Source-grounded correspondence when exact names differ, or material scope "
            "differences for a non-exact relation."
        ),
    )
    applicability: ResultApplicability = Field(
        description=(
            "Required pack applicability. Unsupported or unresolved designs remain unassessed "
            "after Proposal Review."
        ),
    )
    target: ResultTargetDraft = Field(description="Requested target Result for this Trial.")
    reported: Annotated[
        ComparativeEffectResult | GroupBoundValuesResult | CategoryProfileResult,
        Field(
            discriminator="form",
            description=(
                "One reported-result object with required form, alongside target in the "
                "Result card. For example, a minimal "
                "comparative object has form, effect_measure, estimate, and endpoint.name. "
                "Never place selected Evidence, an Evidence handle, a render, table metadata, "
                "or a figure object here."
            ),
        ),
    ]
    passage_refs: tuple[EvidenceHandle, ...] = Field(
        default=(),
        description="Inspected passage_ref handles from search_sources or read_pages, when needed.",
    )

    @model_validator(mode="after")
    def rationale_for_non_exact_relation(self) -> AssessableResultDraft:
        if (
            self.relation != AssessableTargetRelation.EXACT
            and not (self.relation_rationale or "").strip()
        ):
            raise ValueError("non-exact relation requires relation_rationale")
        return self


class UnavailableEvidenceBasis(StrictModel):
    """One selected source premise that explicitly reports a missing input."""

    kind: Literal["missing_reporting"]
    evidence: EvidenceHandle
    source: NonBlankText


class UnavailableIntakeConditionBasis(StrictModel):
    """The captured intake fact that a Trial has no supported Sources."""

    kind: Literal["intake_condition"]
    code: Literal["no_supported_sources"]


UnavailableEvidenceBasisChoice = Annotated[
    UnavailableEvidenceBasis | UnavailableIntakeConditionBasis,
    Field(discriminator="kind"),
]


class UnavailableMissingFact(StrictModel):
    """A missing input and the single typed basis that establishes it."""

    fact: NonBlankText
    basis: UnavailableEvidenceBasisChoice


class UnavailableEvidenceBasisDraft(StrictModel):
    """Caller-owned Evidence premise before the server copies its exact source."""

    kind: Literal["missing_reporting"] = Field(
        description="Use when selected Evidence explicitly establishes missing reporting.",
    )
    evidence: EvidenceHandle = Field(
        description="Selected Evidence handle that establishes the missing fact.",
    )


class UnavailableIntakeConditionBasisDraft(StrictModel):
    """Caller reference to the captured no-supported-Sources intake condition."""

    kind: Literal["intake_condition"] = Field(
        description="Use only for a captured intake condition.",
    )
    code: Literal["no_supported_sources"] = Field(
        description="Captured condition showing that the Trial has no supported Sources.",
    )


UnavailableEvidenceBasisDraftChoice = Annotated[
    UnavailableEvidenceBasisDraft | UnavailableIntakeConditionBasisDraft,
    Field(discriminator="kind"),
]


class UnavailableMissingFactDraft(StrictModel):
    """Caller-owned missing input and its typed basis."""

    fact: NonBlankText = Field(description="Specific missing fact required to define a Result.")
    basis: UnavailableEvidenceBasisDraftChoice = Field(
        description="Typed source or intake basis that establishes this missing fact.",
    )


class UnavailableResult(StrictModel):
    kind: Literal["unavailable"]
    trial_id: TrialId
    requested_outcome: NonBlankText
    relation: Literal[TargetRelation.AMBIGUOUS, TargetRelation.UNAVAILABLE]
    missing_facts: tuple[UnavailableMissingFact, ...] = Field(min_length=1)


class UnavailableResultDraft(StrictModel):
    """Unavailable proposal fields; use only when no complete assessable candidate exists.

    Missing comparator values alone do not make a complete one-arm category profile
    unavailable. Choose by event, time, population, measurement, and state criteria.
    """

    kind: Literal["unavailable"] = Field(
        description="Use only when no complete assessable Result candidate exists.",
    )
    trial_id: TrialId = Field(description="Server-issued Trial ID for this Result card.")
    relation: Literal[TargetRelation.AMBIGUOUS, TargetRelation.UNAVAILABLE] = Field(
        description="Whether the closest Result is ambiguous or unavailable.",
    )
    missing_facts: tuple[UnavailableMissingFactDraft, ...] = Field(
        min_length=1,
        description="Every fact whose absence prevents a complete assessable Result.",
    )


AssessableResultChoice = Annotated[AssessableResult, Field(discriminator="kind")]
UnavailableResultChoice = Annotated[UnavailableResult, Field(discriminator="kind")]
ResultChoice = Annotated[AssessableResult | UnavailableResult, Field(discriminator="kind")]
ResultChoiceDraft = Annotated[
    AssessableResultDraft | UnavailableResultDraft,
    Field(
        discriminator="kind",
        description=(
            "Choose exact assessable first, then the closest complete non-exact "
            "candidate or profile; use unavailable only when none exists. Do not rank by clinical "
            "salience. Missing comparator "
            "values do not invalidate a complete one-arm category profile. Compare event, time, "
            "population, measurement, and state criteria. Relations are relative to the target: "
            "broader is a superset; narrower is a subset or has additional restrictions; "
            "component is one constituent; related is other overlap."
        ),
    ),
]


class RenderIdentity(StrictModel):
    source_id: SourceId
    trial_id: TrialId
    page: PageNumber
    recipe: str = Field(min_length=1)
    png_sha256: Identity
    identity: Identity | None = None

    @model_validator(mode="after")
    def identity_matches(self) -> RenderIdentity:
        return _identity(self, self.identity)


class DomainLimitationBasis(StrictModel):
    kind: Literal["limitation"] = Field(
        description="Use for a specific information limit remaining after scoped discovery.",
    )
    text: str = Field(
        min_length=1, description="What remains unresolved for this question after discovery."
    )
    search_receipt: SearchReceiptHandle = Field(
        description="Current-Trial untruncated search receipt supporting this information limit.",
    )

    @field_validator("text")
    @classmethod
    def text_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("limitation text must contain non-whitespace text")
        return value


class MultipleConcernsDecision(StrictModel):
    raises_overall_to_high: StrictBool = Field(
        description="Whether Some concerns across Domains together raise overall risk to high.",
    )
    rationale: str = Field(
        min_length=1,
        description="Concise reason for the combined-concerns decision.",
    )

    @field_validator("rationale")
    @classmethod
    def rationale_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must contain non-whitespace text")
        return value


class DirectEvidenceUse(StrictModel):
    kind: Literal["direct_support", "indirect_support", "contradiction", "context", "inference"] = (
        Field(description="How the selected Evidence bears on this question answer.")
    )
    evidence: EvidenceHandle = Field(description="Selected Evidence handle for this premise.")


class AbsenceEvidenceUse(StrictModel):
    kind: Literal["absence"] = Field(
        description="Use for an untruncated scoped search with zero hits, not irrelevant hits.",
    )
    search_receipt: SearchReceiptHandle = Field(
        description="No-hit search receipt scoped to this question and Trial.",
    )


DomainBasis = Annotated[
    DirectEvidenceUse | AbsenceEvidenceUse | DomainLimitationBasis,
    Field(discriminator="kind"),
]


class DomainAnswer(StrictModel):
    question_id: QuestionId = Field(description="Question ID from the current Domain card.")
    option_id: str = Field(
        min_length=1,
        description=(
            "Copy one options[].id from the current question card character for character. "
            "This is an opaque identity, not an answer code."
        ),
    )
    bases: tuple[DomainBasis, ...] = Field(
        min_length=1,
        description=(
            "Evidence premises for this answer. Definitive yes or no needs direct_support, "
            "indirect_support, or contradiction; probable answers may also use a limitation, "
            "valid absence receipt, context, or inference."
        ),
    )
    missing_data: tuple[MissingDataRow, ...] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional scope-matched randomized/observed counts for the Domain 3.1 "
            "outcome-availability question."
        ),
    )
    justification: str | None = Field(
        default=None,
        description=(
            "Explain how cited facts support this answer when inference, conflict, or "
            "uncertainty matters."
        ),
    )

    @field_validator("justification")
    @classmethod
    def justification_is_meaningful(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("justification must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def missing_data_is_domain_3_only(self) -> DomainAnswer:
        if self.missing_data is not None and self.question_id != "sq:missing:data-available":
            raise ValueError("missing_data is only valid for question 'sq:missing:data-available'")
        return self


class NewEvidenceRevision(StrictModel):
    kind: Literal["new_evidence"] = Field(
        description="Use when newly selected Evidence changes a saved Domain.",
    )
    evidence: EvidenceHandle = Field(description="New Evidence supporting this revision.")
    rationale: str = Field(min_length=1, description="Why the new Evidence changes the Domain.")

    @field_validator("rationale")
    @classmethod
    def rationale_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must contain non-whitespace text")
        return value


class SelfCorrectionRevision(StrictModel):
    kind: Literal["self_correction"] = Field(
        description="Use when correcting the interpretation of already available Evidence.",
    )
    rationale: str = Field(min_length=1, description="Why the prior checkpoint was incorrect.")

    @field_validator("rationale")
    @classmethod
    def rationale_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must contain non-whitespace text")
        return value


DomainRevisionBasis = Annotated[
    NewEvidenceRevision | SelfCorrectionRevision,
    Field(discriminator="kind"),
]


class DomainDraft(StrictModel):
    trial_id: TrialId
    domain_id: DomainId
    expected_revision: ExpectedRevision
    answers: tuple[DomainAnswer, ...]
    multiple_concerns: MultipleConcernsDecision | None = None
    supersedes: Identity | None = None
    revision_basis: DomainRevisionBasis | None = None


class DomainContext(StrictModel):
    trial_id: TrialId
    domain_id: DomainId
    result: ResultChoice
    evidence: tuple[ResultEvidence, ...] = ()
    prior_digests: tuple[Identity, ...] = ()
    active_questions: tuple[QuestionId, ...]
    guidance: tuple[str, ...] = ()
    traps: tuple[str, ...] = ()
    completion_rule: str = Field(min_length=1)
    state_revision: NonNegativeInt


class NeedsInputTerminalRequest(StrictModel):
    disposition: Literal["needs_input"] = Field(
        description="Use only when specific researcher-supplied facts are required to continue.",
    )
    trial_id: TrialId = Field(description="Server-issued Trial ID that cannot continue.")
    reason: str = Field(min_length=1, description="Why ordinary conservative work cannot continue.")
    missing_facts: tuple[str, ...] = Field(
        min_length=1,
        description="Specific nonblank facts the researcher must supply.",
    )

    @field_validator("reason")
    @classmethod
    def reason_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must contain non-whitespace text")
        return value

    @field_validator("missing_facts")
    @classmethod
    def missing_facts_are_meaningful(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("missing_facts must contain non-whitespace text")
        return value


class AbandonmentTerminalRequest(StrictModel):
    disposition: Literal["failed"] = Field(
        description="Use only for an unrecoverable Trial failure.",
    )
    trial_id: TrialId = Field(description="Server-issued Trial ID that failed.")
    reason: str = Field(min_length=1, description="Why this Trial cannot be completed.")
    facts: tuple[str, ...] = Field(
        min_length=1,
        description="Specific nonblank facts establishing the unrecoverable failure.",
    )

    @field_validator("reason")
    @classmethod
    def reason_is_meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must contain non-whitespace text")
        return value

    @field_validator("facts")
    @classmethod
    def facts_are_meaningful(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("facts must contain non-whitespace text")
        return value


TerminalRequest = Annotated[
    NeedsInputTerminalRequest | AbandonmentTerminalRequest, Field(discriminator="disposition")
]


class ProposalDraft(StrictModel):
    results: tuple[ResultChoiceDraft, ...] = Field(
        min_length=1,
        description=(
            "Result cards only: each item is either kind=assessable or kind=unavailable. "
            "Selected Evidence is durable server state and is never an item in this array."
        ),
    )
    expected_revision: ExpectedRevision


class TerminalRequestEnvelope(StrictModel):
    request: TerminalRequest
    expected_revision: ExpectedRevision


__all__ = [name for name in globals() if not name.startswith("_")]
