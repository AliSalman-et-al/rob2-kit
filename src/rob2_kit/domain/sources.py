"""Immutable source custody, parsing, and inventory contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
    Revision,
)


class SourceRole(StrEnum):
    PRIMARY_REPORT = "primary_report"
    SECONDARY_REPORT = "secondary_report"
    SUPPLEMENT = "supplement"
    PROTOCOL = "protocol"
    STATISTICAL_ANALYSIS_PLAN = "statistical_analysis_plan"
    REGISTRY_CURRENT = "registry_current"
    REGISTRY_HISTORY = "registry_history"
    CLINICAL_STUDY_REPORT = "clinical_study_report"
    REGULATORY_DOCUMENT = "regulatory_document"
    AUTHOR_CORRESPONDENCE = "author_correspondence"
    OTHER = "other"
    UNCLASSIFIED_SUPPORTING = "unclassified_supporting"


class SourceAvailability(StrEnum):
    DECLARED_OR_DISCOVERED = "declared_or_discovered"
    ACQUIRED = "acquired"
    UNAVAILABLE = "unavailable"
    ACCESS_RESTRICTED = "access_restricted"
    ACQUISITION_FAILED = "acquisition_failed"


class SourceProcessing(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    USABLE = "usable"
    COVERAGE_LIMITED = "coverage_limited"
    FAILED = "failed"


class SourceUse(StrEnum):
    NOT_SEARCHED = "not_searched"
    SEARCHED = "searched"
    SEARCH_LIMITED = "search_limited"
    EVIDENCE_USED = "evidence_used"
    REVIEWED_NOT_USED = "reviewed_not_used"


class SourceCriticality(StrEnum):
    REQUIRED = "required"
    EXPECTED = "expected"
    OPTIONAL = "optional"


class AcquisitionMethod(StrEnum):
    LOCAL_IMPORT = "local_import"
    REGISTRY_FETCH = "registry_fetch"
    DOWNLOAD = "download"


class AcquisitionOutcome(StrEnum):
    ACQUIRED = "acquired"
    FAILED = "failed"


class SourceFailureCategory(StrEnum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    ENCRYPTED = "encrypted"
    MALFORMED = "malformed"
    CORRUPT_OR_UNREADABLE = "corrupt_or_unreadable"


class CoverageState(StrEnum):
    TEXT_USABLE = "text_usable"
    VISUAL_REQUIRED = "visual_required"
    RECOVERY_REQUIRED = "recovery_required"
    COVERAGE_LIMITED = "coverage_limited"
    INTENTIONALLY_BLANK = "intentionally_blank"


class ParserQualityPolicy(FrozenModel):
    """Pinned interpretation of LiteParse complexity observations.

    LiteParse reason strings are observations, not confidence scores.  The
    policy owns the small set of reason codes that may influence routing;
    codes outside that set remain diagnostics and never acquire an implicit
    meaning from a later parser release.
    """

    policy_release: Identifier = "policy:parser-quality-1.0.0"
    recovery_reasons: tuple[str, ...] = ("no-text", "scanned")
    limited_reasons: tuple[str, ...] = ("garbled",)
    blank_reasons: tuple[str, ...] = (
        "blank",
        "intentionally-blank",
        "intentionally_blank",
    )
    visual_reasons: tuple[str, ...] = ("parse-render-discrepancy",)

    @property
    def known_reasons(self) -> frozenset[str]:
        return frozenset(
            (
                *self.recovery_reasons,
                *self.limited_reasons,
                *self.blank_reasons,
                *self.visual_reasons,
            )
        )


class ClassificationProvenance(FrozenModel):
    authority: str = Field(min_length=1)
    cues: tuple[str, ...] = ()
    classifier_version: str = Field(min_length=1)


class AcquisitionReceipt(FrozenModel):
    receipt_id: Identifier
    source_id: Identifier
    method: AcquisitionMethod
    origin: str = Field(min_length=1)
    attempted_at: datetime
    actor: Identifier
    declared_metadata: tuple[tuple[str, str], ...] = ()
    artifact_hash: ContentHash | None = None
    outcome: AcquisitionOutcome
    failure_category: SourceFailureCategory | None = None


class PageCoverage(FrozenModel):
    page_index: int = Field(ge=0)
    state: CoverageState
    diagnostics: tuple[str, ...] = ()
    recovery_attempted: bool = False
    # Coverage is derived from the OCR-off parse and, when present, one
    # bounded recovery parse.  These bindings make the before/after decision
    # auditable without treating the map as an opaque source-level score.
    parse_id: Identifier | None = None
    recovery_parse_id: Identifier | None = None
    artifact_hash: ContentHash | None = None
    configuration_hash: ContentHash | None = None
    before_state: CoverageState | None = None

    @property
    def page_number(self) -> int:
        """Return the stable one-based page identity used by LiteParse."""

        return self.page_index + 1


class ParseRecord(FrozenModel):
    parse_id: Identifier
    source_id: Identifier
    artifact_hash: ContentHash
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    configuration_hash: ContentHash
    canonicalization_version: str = Field(min_length=1)
    output_hash: ContentHash
    output_artifact_hash: ContentHash | None = None
    page_artifact_hash: ContentHash | None = None
    ocr_enabled: bool
    target_pages: tuple[int, ...] | None = None
    quality_observations: tuple[str, ...] = ()
    # A compact, deterministic projection of every parser option requested for
    # this record.  ``configuration_hash`` remains the canonical binding;
    # carrying the projection makes diagnostics useful without re-running the
    # parser or guessing defaults from its version.
    configuration: tuple[tuple[str, str], ...] = ()
    page_count: int = Field(default=0, ge=0)
    page_numbers: tuple[int, ...] = ()


class SourceComponentAnnotation(FrozenModel):
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    roles: tuple[SourceRole, ...]
    classification: ClassificationProvenance

    @model_validator(mode="after")
    def validate_range(self) -> "SourceComponentAnnotation":
        if self.page_end < self.page_start:
            raise ValueError("component page_end must not precede page_start")
        return self


class SourceDescriptor(FrozenModel):
    source_id: Identifier
    title: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    roles: tuple[SourceRole, ...]
    criticality: SourceCriticality
    classification: ClassificationProvenance
    availability: SourceAvailability
    processing: SourceProcessing
    use: SourceUse = SourceUse.NOT_SEARCHED
    artifact_hash: ContentHash | None = None
    external_identifiers: tuple[str, ...] = ()
    acquisition_receipt_ids: tuple[Identifier, ...] = ()
    parse_records: tuple[ParseRecord, ...] = ()
    coverage: tuple[PageCoverage, ...] = ()
    components: tuple[SourceComponentAnnotation, ...] = ()
    failure_category: SourceFailureCategory | None = None


class TrialSourceInventory(FrozenModel):
    """An immutable discovery snapshot produced before a ResultSpec exists."""

    inventory_id: Identifier
    trial_id: Identifier
    sources: tuple[SourceDescriptor, ...]
    coverage_limitations: tuple[str, ...] = ()


class SourceComponent(Revision):
    dependency_roles = {"source": "dependency:source"}
    source: RecordReference
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    roles: tuple[SourceRole, ...]
    classification: ClassificationProvenance

    @model_validator(mode="after")
    def validate_range(self) -> "SourceComponent":
        if self.page_end < self.page_start:
            raise ValueError("component page_end must not precede page_start")
        return self


class SourceInventoryRevision(Revision):
    dependency_roles = {"result_spec": "dependency:result-spec"}
    result_spec: RecordReference
    sources: tuple[SourceDescriptor, ...]
    coverage_limitations: tuple[str, ...] = ()
