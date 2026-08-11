"""Complete-search receipts, exact claims, derived facts, and frozen bundles."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
)
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.evidence.obligations import (
    ChronologyConstraint,
    EvidenceCoverageStageOutcomeKind,
    EvidenceNavigationIntentKind,
    EvidencePassActivation,
    EvidenceSearchObligation,
    EvidenceStageActivation,
    SourceSetRule,
)
from rob2_kit.evidence.search import (
    EvidenceSearchPage,
    EvidenceSearchTriageFlags,
    SearchQuery,
)


class SearchPassKind(StrEnum):
    GUIDANCE_SEED = "guidance_seed"
    TRIAL_FOLLOW_UP = "trial_follow_up"
    CONTRADICTION = "contradiction"


class V2QueryAttemptKind(StrEnum):
    SELECTED = "selected"
    EXPLORATORY = "exploratory"
    SUPERSEDED = "superseded"


class V2TriageKind(StrEnum):
    RETAINED = "retained"
    IRRELEVANT = "irrelevant"
    DUPLICATE = "duplicate"
    UNRESOLVED = "unresolved"


class TriageBasis(StrEnum):
    """The objectively auditable material supporting a terminal triage decision."""

    PREVIEW = "preview"
    READ_VIEW_RECEIPT = "read_view_receipt"


class IrrelevantReason(StrEnum):
    WRONG_TRIAL = "wrong_trial"
    WRONG_RESULT = "wrong_result"
    WRONG_QUESTION = "wrong_question"
    OUTSIDE_CONFIRMED_SCOPE = "outside_confirmed_scope"
    NON_SUBSTANTIVE_REFERENCE = "non_substantive_reference"
    LEXICAL_FALSE_POSITIVE = "lexical_false_positive"
    OTHER = "other"


class V2SearchAttempt(FrozenModel):
    """One attributable query attempt, never overwritten by a replacement."""

    attempt_id: Identifier
    sq_id: Identifier
    pass_kind: SearchPassKind
    query: SearchQuery
    query_hash: ContentHash
    kind: V2QueryAttemptKind
    supersedes_attempt_id: Identifier | None = None
    superseded_by_attempt_id: Identifier | None = None
    supersession_rationale: str | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> V2SearchAttempt:
        if self.query_hash != canonical_hash(self.query):
            raise ValueError("attempt query hash must bind the exact structured query")
        superseded = self.kind is V2QueryAttemptKind.SUPERSEDED
        if superseded != (self.superseded_by_attempt_id is not None):
            raise ValueError("only superseded attempts name their replacement")
        if superseded and self.supersedes_attempt_id is not None:
            raise ValueError("a superseded attempt cannot supersede another attempt")
        if superseded != (self.supersession_rationale is not None):
            raise ValueError("supersession requires an explicit rationale")
        if self.supersession_rationale is not None and not self.supersession_rationale.strip():
            raise ValueError("supersession rationale cannot be blank")
        return self


class V2PageExposure(FrozenModel):
    """Durable edge from an attempt/page to one candidate identity."""

    attempt_id: Identifier
    page_handle: str = Field(min_length=1)
    candidate_id: Identifier
    canonical_unit_id: Identifier
    location_handle: str = Field(min_length=1)
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    left_omitted_character_count: int = Field(ge=0)
    right_omitted_character_count: int = Field(ge=0)
    undisplayed_match_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()
    triage_flags: EvidenceSearchTriageFlags
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    duplicate_group_id: Identifier | None = None
    retained_duplicate_target_id: Identifier | None = None
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    traversal_complete: bool


class V2ExposedPage(FrozenModel):
    """Page-level audit record, retained even when the page has zero candidates."""

    attempt_id: Identifier
    page_handle: str = Field(min_length=1)
    candidate_ids: tuple[Identifier, ...] = ()
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    traversal_complete: bool


class V2CandidateTriageRevision(FrozenModel):
    """Append-only classification of one candidate occurrence on one SQ page.

    Candidate IDs identify canonical source material and can therefore recur
    across selected queries.  A classification is deliberately not global:
    its attempt, signaling question, and page handle bind the decision to the
    exact surfaced occurrence that supplied its review context.
    """

    revision_id: Identifier
    candidate_id: Identifier
    attempt_id: Identifier
    sq_id: Identifier
    page_handle: str = Field(min_length=1)
    kind: V2TriageKind
    irrelevant_reason: IrrelevantReason | None = None
    retained_target_id: Identifier | None = None
    rationale: str | None = None
    basis: TriageBasis | None = None
    read_view_receipt: str | None = None
    retained_target_read_view_receipt: str | None = None

    @model_validator(mode="after")
    def validate_triage(self) -> V2CandidateTriageRevision:
        if self.kind is V2TriageKind.IRRELEVANT:
            if self.irrelevant_reason is None:
                raise ValueError("irrelevant triage requires a closed reason")
            if self.irrelevant_reason is IrrelevantReason.OTHER and not (
                self.rationale and self.rationale.strip()
            ):
                raise ValueError("the other irrelevant reason requires a rationale")
            if self.basis is None:
                raise ValueError(
                    "irrelevant triage requires an explicit preview or read receipt basis"
                )
            if self.basis is TriageBasis.PREVIEW and self.read_view_receipt is not None:
                raise ValueError("preview triage cannot attach a read-view receipt")
            if self.basis is TriageBasis.READ_VIEW_RECEIPT and not self.read_view_receipt:
                raise ValueError("read-based triage requires a read-view receipt")
        elif self.irrelevant_reason is not None:
            raise ValueError("irrelevant reasons apply only to irrelevant triage")
        if self.kind is V2TriageKind.DUPLICATE:
            if self.retained_target_id is None or self.retained_target_id == self.candidate_id:
                raise ValueError("duplicate triage requires a distinct retained target")
        elif (
            self.retained_target_id is not None
            or self.retained_target_read_view_receipt is not None
        ):
            raise ValueError("retained target and its receipt apply only to duplicate triage")
        if self.kind is V2TriageKind.UNRESOLVED and not (self.rationale and self.rationale.strip()):
            raise ValueError("unresolved triage requires a rationale")
        return self

    @property
    def disposition_fingerprint(self) -> ContentHash:
        """Identify the terminal classification, not the supporting read instance.

        A canonical candidate can be exposed for several signaling questions.
        Each page still needs its own receipt-bound triage revision, but the
        receipts are necessarily question-specific.  Treating those supporting
        receipts as conflicting dispositions made an otherwise identical,
        conservative dismissal impossible to record across those pages.
        """
        return canonical_hash(
            {
                "candidate_id": self.candidate_id,
                "kind": self.kind,
                "irrelevant_reason": self.irrelevant_reason,
                "retained_target_id": self.retained_target_id,
                "rationale": self.rationale,
            }
        )


class V2PageTriageSubmission(FrozenModel):
    """One exact, all-or-nothing partition over complete exposed pages."""

    submission_id: Identifier
    page_handles: tuple[str, ...]
    triage_revision_ids: tuple[Identifier, ...]
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_submission(self) -> V2PageTriageSubmission:
        if not self.page_handles or len(self.page_handles) != len(set(self.page_handles)):
            raise ValueError("a triage submission needs unique complete page handles")
        if len(self.triage_revision_ids) != len(set(self.triage_revision_ids)):
            raise ValueError("a triage submission cannot repeat revision IDs")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("triage submission hash must bind its exact partition")
        return self


class V2EvidenceWorkflowState(FrozenModel):
    """Serializable immutable reducer state for the unexposed v2 workflow."""

    result_id: Identifier
    domain_id: Identifier
    snapshot_hash: ContentHash
    search_policy_id: Identifier
    search_policy_hash: ContentHash
    attempts: tuple[V2SearchAttempt, ...] = ()
    pages: tuple[V2ExposedPage, ...] = ()
    exposures: tuple[V2PageExposure, ...] = ()
    triage_revisions: tuple[V2CandidateTriageRevision, ...] = ()
    triage_submissions: tuple[V2PageTriageSubmission, ...] = ()

    @model_validator(mode="after")
    def validate_audit_state(self) -> V2EvidenceWorkflowState:
        attempt_by_id = {attempt.attempt_id: attempt for attempt in self.attempts}
        if len(attempt_by_id) != len(self.attempts):
            raise ValueError("search attempt IDs must be unique")
        if any(page.attempt_id not in attempt_by_id for page in self.pages):
            raise ValueError("exposed pages must name an issued search attempt")
        if any(exposure.attempt_id not in attempt_by_id for exposure in self.exposures):
            raise ValueError("page exposures must name an issued search attempt")
        if len({page.page_handle for page in self.pages}) != len(self.pages):
            raise ValueError("exposed page handles must be unique")
        exposure_keys = {
            (edge.attempt_id, edge.page_handle, edge.candidate_id) for edge in self.exposures
        }
        if len(exposure_keys) != len(self.exposures):
            raise ValueError("page exposure edges must be unique")
        pages: dict[tuple[Identifier, str], list[V2PageExposure]] = {}
        for edge in self.exposures:
            pages.setdefault((edge.attempt_id, edge.page_handle), []).append(edge)
        for page_edges in pages.values():
            identity = (page_edges[0].page_number, page_edges[0].total_page_count)
            if any((edge.page_number, edge.total_page_count) != identity for edge in page_edges):
                raise ValueError("one page handle must bind one deterministic page position")
            if len({edge.candidate_id for edge in page_edges}) != len(page_edges):
                raise ValueError("one page cannot expose a candidate twice")
        page_by_handle = {page.page_handle: page for page in self.pages}
        for handle, page_edges in pages.items():
            page = page_by_handle.get(handle[1])
            if (
                page is None
                or page.attempt_id != handle[0]
                or page.candidate_ids != tuple(edge.candidate_id for edge in page_edges)
            ):
                raise ValueError("candidate exposure edges must exactly match their exposed page")
        revisions = {revision.revision_id: revision for revision in self.triage_revisions}
        if len(revisions) != len(self.triage_revisions):
            raise ValueError("triage revision IDs must be unique")
        by_occurrence: dict[tuple[Identifier, Identifier, str, Identifier], ContentHash] = {}
        exposure_by_occurrence = {
            (
                edge.attempt_id,
                attempt_by_id[edge.attempt_id].sq_id,
                edge.page_handle,
                edge.candidate_id,
            ): edge
            for edge in self.exposures
        }
        for revision in self.triage_revisions:
            occurrence = (
                revision.attempt_id,
                revision.sq_id,
                revision.page_handle,
                revision.candidate_id,
            )
            if occurrence not in exposure_by_occurrence:
                raise ValueError("triage revision must bind an exposed SQ page occurrence")
            prior = by_occurrence.setdefault(occurrence, revision.disposition_fingerprint)
            if prior != revision.disposition_fingerprint:
                raise ValueError(
                    "conflicting triage revisions are not permitted for one occurrence"
                )
        submissions = {
            submission.submission_id: submission for submission in self.triage_submissions
        }
        if len(submissions) != len(self.triage_submissions):
            raise ValueError("triage submission IDs must be unique")
        used_pages: set[str] = set()
        for submission in self.triage_submissions:
            if used_pages.intersection(submission.page_handles):
                raise ValueError("a page partition may be submitted only once")
            used_pages.update(submission.page_handles)
            selected_pages = [page_by_handle.get(handle) for handle in submission.page_handles]
            if any(page is None for page in selected_pages):
                raise ValueError("triage submission names an unexposed page")
            selected = [
                edge for edge in self.exposures if edge.page_handle in submission.page_handles
            ]
            selected_occurrences = {
                (
                    edge.attempt_id,
                    attempt_by_id[edge.attempt_id].sq_id,
                    edge.page_handle,
                    edge.candidate_id,
                )
                for edge in selected
            }
            submitted_occurrences = {
                (
                    revisions[item].attempt_id,
                    revisions[item].sq_id,
                    revisions[item].page_handle,
                    revisions[item].candidate_id,
                )
                for item in submission.triage_revision_ids
                if item in revisions
            }
            if len(submission.triage_revision_ids) != len(submitted_occurrences):
                raise ValueError(
                    "triage submission must reference issued unique occurrence revisions"
                )
            if submitted_occurrences != selected_occurrences:
                raise ValueError(
                    "triage submissions must classify every candidate occurrence in complete pages"
                )
        selected = [
            attempt for attempt in self.attempts if attempt.kind is V2QueryAttemptKind.SELECTED
        ]
        current_keys = {(attempt.sq_id, attempt.pass_kind) for attempt in selected}
        if len(current_keys) != len(selected):
            raise ValueError("each signaling-question pass has one current selected attempt")
        for sq_id in {attempt.sq_id for attempt in selected}:
            hashes = [attempt.query_hash for attempt in selected if attempt.sq_id == sq_id]
            if len(hashes) != len(set(hashes)):
                raise ValueError("selected mandatory queries must be pairwise distinct")
        return self

    @property
    def content_hash(self) -> ContentHash:
        return canonical_hash(self.model_dump(mode="json"))

    def outstanding_triage_candidate_ids(self) -> tuple[Identifier, ...]:
        classified = {
            (revision.attempt_id, revision.page_handle, revision.candidate_id)
            for revision in self.triage_revisions
        }
        return tuple(
            sorted(
                {
                    edge.candidate_id
                    for edge in self.exposures
                    if (edge.attempt_id, edge.page_handle, edge.candidate_id) not in classified
                }
            )
        )

    def coverage_complete(self) -> bool:
        selected_attempts = [
            attempt for attempt in self.attempts if attempt.kind is V2QueryAttemptKind.SELECTED
        ]
        if not selected_attempts:
            return False
        for sq_id in {attempt.sq_id for attempt in selected_attempts}:
            if {
                attempt.pass_kind for attempt in selected_attempts if attempt.sq_id == sq_id
            } != set(SearchPassKind):
                return False
        for attempt in self.attempts:
            if attempt.kind is not V2QueryAttemptKind.SELECTED:
                continue
            pages = [page for page in self.pages if page.attempt_id == attempt.attempt_id]
            if not pages:
                return False
            totals = {page.total_page_count for page in pages}
            if len(totals) != 1:
                return False
            expected = set(range(1, next(iter(totals)) + 1))
            if {page.page_number for page in pages} != expected:
                return False
            if not any(page.traversal_complete for page in pages):
                return False
        return True

    def freeze_valid(self) -> bool:
        if not self.coverage_complete() or self.outstanding_triage_candidate_ids():
            return False
        return not any(
            revision.kind is V2TriageKind.UNRESOLVED for revision in self.triage_revisions
        )


class V3AttemptKind(StrEnum):
    SELECTED = "selected"
    EXPLORATORY = "exploratory"
    SUPERSEDED = "superseded"


class V3TriageKind(StrEnum):
    RETAINED = "retained"
    IRRELEVANT = "irrelevant"
    DUPLICATE = "duplicate"
    UNRESOLVED = "unresolved"


class V3TriggerDispositionKind(StrEnum):
    FALSE = "false"
    TRUE = "true"
    MATERIALLY_UNRESOLVED = "materially_unresolved"


class V3ScopeLimitationKind(StrEnum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    MATERIAL_UNRESOLVED = "material_unresolved"
    CHRONOLOGY_UNRESOLVED = "chronology_unresolved"
    CROSS_SOURCE_INSUFFICIENT = "cross_source_insufficient"


class V3ChronologyStatus(StrEnum):
    """Closed attributable chronology status for one Source/Parse revision."""

    SATISFIES = "satisfies"
    DOES_NOT_SATISFY = "does_not_satisfy"
    UNRESOLVED = "unresolved"


class V3SourceChronologyFact(FrozenModel):
    constraint: ChronologyConstraint
    status: V3ChronologyStatus
    rationale: str = Field(min_length=1)


class V3AuthorizedSource(FrozenModel):
    """One accepted Source descriptor, optionally before a searchable Parse exists."""

    source_id: Identifier
    roles: tuple[SourceRole, ...]
    source_artifact_hash: ContentHash | None = None
    parse_id: Identifier | None = None
    parse_output_hash: ContentHash | None = None
    chronology_facts: tuple[V3SourceChronologyFact, ...] = ()
    availability: SourceAvailability = SourceAvailability.ACQUIRED
    processing: SourceProcessing = SourceProcessing.USABLE
    criticality: SourceCriticality = SourceCriticality.EXPECTED
    page_count: int = Field(default=0, ge=0)
    indexed_unit_count: int = Field(default=0, ge=0)
    unit_orientation: str = Field(default="indexed_units", pattern=r"^(indexed_units|pages)$")
    unresolved_potential_roles: tuple[SourceRole, ...] = ()
    lineage_source_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_roles(self) -> V3AuthorizedSource:
        if not self.roles or len(self.roles) != len(set(self.roles)):
            raise ValueError("authorized Source roles must be non-empty and unique")
        if len(self.unresolved_potential_roles) != len(set(self.unresolved_potential_roles)):
            raise ValueError("authorized Source unresolved potential roles must be unique")
        if set(self.roles).intersection(self.unresolved_potential_roles):
            raise ValueError("authorized Source roles cannot also be unresolved")
        chronology_constraints = [item.constraint for item in self.chronology_facts]
        if len(chronology_constraints) != len(set(chronology_constraints)):
            raise ValueError("authorized Source chronology facts must be unique per constraint")
        identity_values = (
            self.source_artifact_hash,
            self.parse_id,
            self.parse_output_hash,
        )
        if any(item is None for item in identity_values) and any(
            item is not None for item in identity_values
        ):
            raise ValueError(
                "authorized Source artifact and Parse identity must be complete together"
            )
        if self.is_searchable and not self.has_exact_source_parse:
            raise ValueError("acquired usable Source requires exact artifact and Parse identity")
        return self

    @property
    def has_exact_source_parse(self) -> bool:
        return (
            self.source_artifact_hash is not None
            and self.parse_id is not None
            and self.parse_output_hash is not None
        )

    @property
    def is_searchable(self) -> bool:
        return self.availability is SourceAvailability.ACQUIRED and self.processing in {
            SourceProcessing.USABLE,
            SourceProcessing.COVERAGE_LIMITED,
        }


class V3StageScopeLimitation(FrozenModel):
    """An engine-materialized role, chronology, or source-set limitation."""

    role: SourceRole | None = None
    chronology_constraint: ChronologyConstraint | None = None
    source_set_rule: SourceSetRule | None = None
    kind: V3ScopeLimitationKind
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> V3StageScopeLimitation:
        if (
            sum(
                item is not None
                for item in (self.role, self.chronology_constraint, self.source_set_rule)
            )
            != 1
        ):
            raise ValueError(
                "v3 scope limitation must name exactly one role, chronology constraint, "
                "or source-set rule"
            )
        return self


class V3MaterializedStageScope(FrozenModel):
    """The engine's exact source scope for one static stage, never caller-built."""

    scope_id: Identifier
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    authorized_source_ids: tuple[Identifier, ...]
    authorized_source_scope_hash: ContentHash
    chronology_constraints: tuple[ChronologyConstraint, ...] = ()
    applicable_source_roles: tuple[SourceRole, ...] = ()
    source_set_rule: SourceSetRule | None = None
    role_limitations: tuple[V3StageScopeLimitation, ...] = ()

    @model_validator(mode="after")
    def validate_scope_hash(self) -> V3MaterializedStageScope:
        if self.authorized_source_ids != tuple(sorted(self.authorized_source_ids)):
            raise ValueError("materialized stage Source IDs must use canonical order")
        if self.authorized_source_scope_hash != canonical_hash(self.authorized_source_ids):
            raise ValueError("stage scope hash must bind its exact authorized Source IDs")
        targets = tuple(
            (item.role, item.chronology_constraint, item.source_set_rule)
            for item in self.role_limitations
        )
        if len(set(targets)) != len(targets):
            raise ValueError("materialized stage scope cannot repeat limitations")
        return self


class V3SearchAttempt(FrozenModel):
    """An immutable lexical attempt for one issued navigation intent."""

    attempt_id: Identifier
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    intent_id: Identifier
    query: SearchQuery
    query_hash: ContentHash
    source_scope_hash: ContentHash
    kind: V3AttemptKind = V3AttemptKind.SELECTED
    supersedes_attempt_id: Identifier | None = None
    superseded_by_attempt_id: Identifier | None = None
    supersession_rationale: str | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> V3SearchAttempt:
        if self.query_hash != canonical_hash(self.query):
            raise ValueError("v3 attempt query hash must bind the exact structured query")
        retired = self.kind is V3AttemptKind.SUPERSEDED
        if retired != (self.superseded_by_attempt_id is not None):
            raise ValueError("only superseded v3 attempts name their replacement")
        if retired and self.supersedes_attempt_id is not None:
            raise ValueError("a superseded v3 attempt cannot supersede another attempt")
        if retired != (self.supersession_rationale is not None):
            raise ValueError("v3 supersession requires an attributable rationale")
        if self.supersession_rationale is not None and not self.supersession_rationale.strip():
            raise ValueError("v3 supersession rationale cannot be blank")
        return self


class V3ExposedPage(FrozenModel):
    attempt_id: Identifier
    page_handle: str = Field(min_length=1)
    candidate_ids: tuple[Identifier, ...] = ()
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    traversal_complete: bool


class V3PageExposure(FrozenModel):
    attempt_id: Identifier
    page_handle: str = Field(min_length=1)
    candidate_id: Identifier
    canonical_unit_id: Identifier
    location_handle: str = Field(min_length=1)
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    left_omitted_character_count: int = Field(ge=0)
    right_omitted_character_count: int = Field(ge=0)
    undisplayed_match_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    traversal_complete: bool
    triage_flags: EvidenceSearchTriageFlags
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    duplicate_group_id: Identifier | None = None
    retained_duplicate_target_id: Identifier | None = None


class V3CandidateTriageRevision(FrozenModel):
    revision_id: Identifier
    attempt_id: Identifier
    sq_id: Identifier
    page_handle: str = Field(min_length=1)
    candidate_id: Identifier
    kind: V3TriageKind
    irrelevant_reason: IrrelevantReason | None = None
    retained_target_id: Identifier | None = None
    rationale: str | None = None
    basis: TriageBasis | None = None
    read_view_receipt: str | None = None
    retained_target_read_view_receipt: str | None = None

    @model_validator(mode="after")
    def validate_triage(self) -> V3CandidateTriageRevision:
        if self.kind is V3TriageKind.IRRELEVANT:
            if self.irrelevant_reason is None or self.basis is None:
                raise ValueError("irrelevant v3 triage requires a closed reason and explicit basis")
            if self.irrelevant_reason is IrrelevantReason.OTHER and not (
                self.rationale and self.rationale.strip()
            ):
                raise ValueError("the other irrelevant reason requires a rationale")
            if self.basis is TriageBasis.PREVIEW and self.read_view_receipt is not None:
                raise ValueError("preview triage cannot attach a read-view receipt")
            if self.basis is TriageBasis.READ_VIEW_RECEIPT and not self.read_view_receipt:
                raise ValueError("read-based triage requires a read-view receipt")
        elif self.kind is V3TriageKind.RETAINED:
            if not self.read_view_receipt:
                raise ValueError("retained v3 triage requires a read-view receipt")
            if self.irrelevant_reason is not None or self.basis is not None:
                raise ValueError("irrelevant details apply only to irrelevant v3 triage")
        elif self.kind is V3TriageKind.DUPLICATE:
            if (
                self.irrelevant_reason is not None
                or self.basis is not None
                or self.read_view_receipt
            ):
                raise ValueError("irrelevant details apply only to irrelevant v3 triage")
            if self.retained_target_id is None or self.retained_target_id == self.candidate_id:
                raise ValueError("duplicate v3 triage requires a distinct retained target")
        else:
            if self.irrelevant_reason is not None or self.basis is not None:
                raise ValueError("irrelevant details apply only to irrelevant v3 triage")
        if self.kind is not V3TriageKind.DUPLICATE and (
            self.retained_target_id is not None
            or self.retained_target_read_view_receipt is not None
        ):
            raise ValueError("duplicate target details apply only to duplicate v3 triage")
        if self.kind is V3TriageKind.UNRESOLVED and not (self.rationale and self.rationale.strip()):
            raise ValueError("unresolved v3 triage requires a rationale")
        return self

    @property
    def disposition_fingerprint(self) -> ContentHash:
        return canonical_hash(
            {
                "candidate_id": self.candidate_id,
                "kind": self.kind,
                "irrelevant_reason": self.irrelevant_reason,
                "retained_target_id": self.retained_target_id,
                "rationale": self.rationale,
            }
        )


class V3PageTriageSubmission(FrozenModel):
    submission_id: Identifier
    attempt_id: Identifier
    page_handles: tuple[str, ...]
    triage_revision_ids: tuple[Identifier, ...]
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_submission(self) -> V3PageTriageSubmission:
        if not self.page_handles or len(self.page_handles) != len(set(self.page_handles)):
            raise ValueError("v3 triage submission needs unique page handles")
        if len(self.triage_revision_ids) != len(set(self.triage_revision_ids)):
            raise ValueError("v3 triage submission cannot repeat revisions")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("v3 triage submission hash must bind its partition")
        return self


class V3NavigationCompletionReceipt(FrozenModel):
    """A policy-bound receipt resolved from an engine-issued receipt registry."""

    receipt_id: Identifier
    issuance_id: Identifier
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    intent_id: Identifier
    kind: EvidenceNavigationIntentKind
    source_scope_hash: ContentHash
    snapshot_hash: ContentHash
    read_policy_id: Identifier | None = None
    read_policy_hash: ContentHash | None = None
    visual_policy_id: Identifier | None = None
    visual_policy_hash: ContentHash | None = None
    receipt_hash: ContentHash

    @model_validator(mode="after")
    def validate_receipt(self) -> V3NavigationCompletionReceipt:
        if self.kind is EvidenceNavigationIntentKind.SEARCH:
            raise ValueError("Search intents complete through traversal, not a navigation receipt")
        if self.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW:
            if not self.visual_policy_id or not self.visual_policy_hash:
                raise ValueError("visual completion receipt must bind the visual policy")
        elif not self.read_policy_id or not self.read_policy_hash:
            raise ValueError("read completion receipt must bind the read policy")
        payload = self.model_dump(mode="json")
        payload["receipt_hash"] = None
        if self.receipt_hash != canonical_hash(payload):
            raise ValueError("navigation receipt hash must bind the engine-issued receipt")
        return self


class V3AcquisitionAttemptReceipt(FrozenModel):
    """Engine-issued evidence that acquisition was attempted for unavailable Sources."""

    receipt_id: Identifier
    issuance_id: Identifier
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    materialized_scope_id: Identifier
    inventory_snapshot_hash: ContentHash
    unavailable_source_ids: tuple[Identifier, ...] = Field(min_length=1)
    limitation_hash: ContentHash
    receipt_hash: ContentHash

    @model_validator(mode="after")
    def validate_receipt(self) -> V3AcquisitionAttemptReceipt:
        if self.unavailable_source_ids != tuple(sorted(self.unavailable_source_ids)) or len(
            self.unavailable_source_ids
        ) != len(set(self.unavailable_source_ids)):
            raise ValueError("acquisition receipt Source IDs must be sorted and unique")
        payload = self.model_dump(mode="json")
        payload["receipt_hash"] = None
        if self.receipt_hash != canonical_hash(payload):
            raise ValueError("acquisition receipt hash must bind the engine-issued receipt")
        return self


class V3TriggerDisposition(FrozenModel):
    trigger_id: Identifier
    kind: V3TriggerDispositionKind
    rationale: str = Field(min_length=1)


class V3EvidenceStageOutcomeSubmission(FrozenModel):
    """Append-only outcome for exactly one materialized stage."""

    submission_id: Identifier
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    obligation_revision_id: Identifier
    obligation_hash: ContentHash
    inventory_snapshot_hash: ContentHash
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    materialized_scope_id: Identifier
    outcome_kind: EvidenceCoverageStageOutcomeKind
    rationale: str = Field(min_length=1)
    trigger_dispositions: tuple[V3TriggerDisposition, ...] = ()
    acquisition_receipt_id: Identifier | None = None
    content_hash: ContentHash

    @model_validator(mode="after")
    def validate_outcome(self) -> V3EvidenceStageOutcomeSubmission:
        if len({item.trigger_id for item in self.trigger_dispositions}) != len(
            self.trigger_dispositions
        ):
            raise ValueError("stage outcome cannot repeat trigger dispositions")
        if (
            self.outcome_kind
            not in {
                EvidenceCoverageStageOutcomeKind.SOURCE_UNAVAILABLE_AFTER_ATTEMPT,
                EvidenceCoverageStageOutcomeKind.SCOPE_LIMITATION_UNRESOLVED,
            }
            and self.acquisition_receipt_id is not None
        ):
            raise ValueError(
                "only source or scope-limitation outcomes may bind an acquisition receipt"
            )
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        if self.content_hash != canonical_hash(payload):
            raise ValueError("stage outcome hash must bind the complete submission")
        return self


class V3EvidenceWorkflowState(FrozenModel):
    """Durable v3 reducer state bound to an exact Guidance obligation revision."""

    state_version: Literal["evidence-workflow:3.0.0"] = "evidence-workflow:3.0.0"
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    snapshot_hash: ContentHash
    obligation_revision_id: Identifier
    obligation: EvidenceSearchObligation
    obligation_hash: ContentHash
    inventory_snapshot_hash: ContentHash
    authorized_inventory: tuple[V3AuthorizedSource, ...]
    search_policy_id: Identifier
    search_policy_hash: ContentHash
    read_policy_id: Identifier
    read_policy_hash: ContentHash
    visual_policy_id: Identifier
    visual_policy_hash: ContentHash
    stage_scopes: tuple[V3MaterializedStageScope, ...]
    issued_receipt_hashes: tuple[tuple[Identifier, ContentHash], ...] = ()
    issued_acquisition_receipt_hashes: tuple[tuple[Identifier, ContentHash], ...] = ()
    attempts: tuple[V3SearchAttempt, ...] = ()
    pages: tuple[V3ExposedPage, ...] = ()
    exposures: tuple[V3PageExposure, ...] = ()
    triage_revisions: tuple[V3CandidateTriageRevision, ...] = ()
    triage_submissions: tuple[V3PageTriageSubmission, ...] = ()
    completion_receipts: tuple[V3NavigationCompletionReceipt, ...] = ()
    acquisition_receipts: tuple[V3AcquisitionAttemptReceipt, ...] = ()
    stage_outcomes: tuple[V3EvidenceStageOutcomeSubmission, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> V3EvidenceWorkflowState:
        if self.question_id != self.obligation.question_id:
            raise ValueError("v3 workflow question must bind its exact obligation")
        if self.obligation_hash != canonical_hash(self.obligation):
            raise ValueError("v3 workflow obligation hash must bind the exact obligation")
        inventory_ids = [item.source_id for item in self.authorized_inventory]
        if len(inventory_ids) != len(set(inventory_ids)):
            raise ValueError("authorized inventory cannot repeat Source IDs")
        if self.inventory_snapshot_hash != _v3_inventory_hash(self.authorized_inventory):
            raise ValueError("inventory snapshot hash must bind the exact authorized inventory")
        stage_map = _v3_stage_map(self.obligation)
        if set((x.proposition_id, x.pass_id, x.stage_id) for x in self.stage_scopes) != set(
            stage_map
        ):
            raise ValueError("v3 state must materialize every static obligation stage exactly once")
        if len({item.scope_id for item in self.stage_scopes}) != len(self.stage_scopes):
            raise ValueError("materialized stage scope IDs must be unique")
        inventory = {item.source_id: item for item in self.authorized_inventory}
        for scope in self.stage_scopes:
            static_stage = stage_map[(scope.proposition_id, scope.pass_id, scope.stage_id)]
            if scope.chronology_constraints != static_stage.chronology_constraints:
                raise ValueError("materialized scope must bind the static stage chronology")
            if (
                scope.applicable_source_roles
                and scope.applicable_source_roles != static_stage.applicable_source_roles
            ):
                raise ValueError("materialized scope must bind the static stage roles")
            proposition = next(
                item for item in self.obligation.propositions if item.id == scope.proposition_id
            )
            if (
                scope.source_set_rule is not None
                and scope.source_set_rule is not proposition.source_set_rule
            ):
                raise ValueError("materialized scope must bind the proposition source-set rule")
            covered_roles: set[SourceRole] = set()
            for source_id in scope.authorized_source_ids:
                source = inventory.get(source_id)
                if (
                    source is None
                    or not source.is_searchable
                    or not source.has_exact_source_parse
                    or not set(source.roles).intersection(static_stage.applicable_source_roles)
                ):
                    raise ValueError(
                        "materialized scope contains a Source outside the static stage"
                    )
                covered_roles.update(
                    set(source.roles).intersection(static_stage.applicable_source_roles)
                )
            limited_roles = {item.role for item in scope.role_limitations if item.role is not None}
            missing_roles = set(static_stage.applicable_source_roles) - covered_roles
            if missing_roles != limited_roles:
                raise ValueError(
                    "materialized scope must explicitly limit every required role not covered"
                )
        if len({item.attempt_id for item in self.attempts}) != len(self.attempts):
            raise ValueError("v3 attempt IDs must be unique")
        scopes = {
            (item.proposition_id, item.pass_id, item.stage_id): item for item in self.stage_scopes
        }
        for attempt in self.attempts:
            intent = _v3_intent(self, attempt)
            if intent is None or intent.kind is not EvidenceNavigationIntentKind.SEARCH:
                raise ValueError("v3 attempt must bind an issued Search navigation intent")
            if (
                attempt.source_scope_hash
                != scopes[
                    (attempt.proposition_id, attempt.pass_id, attempt.stage_id)
                ].authorized_source_scope_hash
            ):
                raise ValueError("v3 attempt must bind the issued stage Source scope")
            if (
                attempt.query.source_ids
                != scopes[
                    (attempt.proposition_id, attempt.pass_id, attempt.stage_id)
                ].authorized_source_ids
            ):
                raise ValueError("v3 query Source IDs must bind the issued stage Source scope")
        selected_intents = [
            item.intent_id for item in self.attempts if item.kind is V3AttemptKind.SELECTED
        ]
        if len(selected_intents) != len(set(selected_intents)):
            raise ValueError("each v3 navigation intent has at most one selected attempt")
        pages = {item.page_handle: item for item in self.pages}
        if len(pages) != len(self.pages):
            raise ValueError("v3 exposed page handles must be unique")
        attempts = {item.attempt_id: item for item in self.attempts}
        exposure_keys = {
            (item.attempt_id, item.page_handle, item.candidate_id) for item in self.exposures
        }
        if len(exposure_keys) != len(self.exposures):
            raise ValueError("v3 page exposures must be unique")
        inventory_by_id = {item.source_id: item for item in self.authorized_inventory}
        for page in self.pages:
            if page.attempt_id not in attempts:
                raise ValueError("v3 page must name an issued attempt")
            exposed = tuple(
                item.candidate_id for item in self.exposures if item.page_handle == page.page_handle
            )
            if exposed != page.candidate_ids:
                raise ValueError("v3 page exposures must exactly match the exposed page")
        for exposure in self.exposures:
            attempt = attempts.get(exposure.attempt_id)
            page = pages.get(exposure.page_handle)
            if attempt is None or page is None or page.attempt_id != exposure.attempt_id:
                raise ValueError("v3 exposure must bind an issued attempt and page")
            source = inventory_by_id.get(exposure.source_id)
            scope = scopes[(attempt.proposition_id, attempt.pass_id, attempt.stage_id)]
            if (
                source is None
                or not source.is_searchable
                or not source.has_exact_source_parse
                or exposure.source_id not in scope.authorized_source_ids
                or (source.source_artifact_hash, source.parse_id)
                != (exposure.source_artifact_hash, exposure.parse_id)
            ):
                raise ValueError("v3 exposure must remain inside its authorized Source/Parse scope")
        revisions = {item.revision_id: item for item in self.triage_revisions}
        if len(revisions) != len(self.triage_revisions):
            raise ValueError("v3 triage revision IDs must be unique")
        by_occurrence: dict[tuple[Identifier, Identifier, str, Identifier], ContentHash] = {}
        for revision in self.triage_revisions:
            if revision.sq_id != self.question_id:
                raise ValueError("v3 triage revision must bind the workflow signaling question")
            occurrence = (
                revision.attempt_id,
                revision.sq_id,
                revision.page_handle,
                revision.candidate_id,
            )
            prior = by_occurrence.setdefault(occurrence, revision.disposition_fingerprint)
            if prior != revision.disposition_fingerprint:
                raise ValueError("conflicting v3 triage dispositions are not permitted")
        if any(
            (item.attempt_id, item.page_handle, item.candidate_id) not in exposure_keys
            for item in self.triage_revisions
        ):
            raise ValueError("v3 triage revision must bind an exposed candidate")
        retained_by_candidate = {
            item.candidate_id: item
            for item in self.triage_revisions
            if item.kind is V3TriageKind.RETAINED
        }
        for revision in self.triage_revisions:
            if revision.kind is not V3TriageKind.DUPLICATE:
                continue
            target = retained_by_candidate.get(revision.retained_target_id)
            if target is None or not target.read_view_receipt:
                raise ValueError("duplicate v3 triage requires a read-backed retained target")
            if (
                revision.retained_target_read_view_receipt is not None
                and revision.retained_target_read_view_receipt != target.read_view_receipt
            ):
                raise ValueError("duplicate target receipt must match the retained target receipt")
        used_pages: set[str] = set()
        for submission in self.triage_submissions:
            if used_pages.intersection(submission.page_handles):
                raise ValueError("v3 page triage is append-only")
            used_pages.update(submission.page_handles)
            expected = {
                (item.attempt_id, item.page_handle, item.candidate_id)
                for item in self.exposures
                if item.page_handle in submission.page_handles
            }
            actual = {
                (
                    revisions[item].attempt_id,
                    revisions[item].page_handle,
                    revisions[item].candidate_id,
                )
                for item in submission.triage_revision_ids
                if item in revisions
            }
            if len(actual) != len(submission.triage_revision_ids) or actual != expected:
                raise ValueError("v3 triage submission must exhaustively partition its pages")
        if len({item.receipt_id for item in self.completion_receipts}) != len(
            self.completion_receipts
        ):
            raise ValueError("v3 completion receipt IDs must be unique")
        issued_receipts = dict(self.issued_receipt_hashes)
        if len(issued_receipts) != len(self.issued_receipt_hashes):
            raise ValueError("engine-issued receipt IDs must be unique")
        for receipt in self.completion_receipts:
            stage = stage_map.get((receipt.proposition_id, receipt.pass_id, receipt.stage_id))
            scope = scopes.get((receipt.proposition_id, receipt.pass_id, receipt.stage_id))
            if (
                stage is None
                or scope is None
                or receipt.snapshot_hash != self.snapshot_hash
                or receipt.source_scope_hash != scope.authorized_source_scope_hash
            ):
                raise ValueError("v3 receipt has stale scope or snapshot identity")
            intent = next(
                (item for item in stage.navigation_intents if item.id == receipt.intent_id), None
            )
            if intent is None or intent.kind != receipt.kind:
                raise ValueError("v3 receipt must bind an issued non-Search intent")
            if issued_receipts.get(receipt.issuance_id) != receipt.receipt_hash:
                raise ValueError("v3 receipt was not resolved from engine-owned issuance")
        issued_acquisition_receipts = dict(self.issued_acquisition_receipt_hashes)
        if len(issued_acquisition_receipts) != len(self.issued_acquisition_receipt_hashes):
            raise ValueError("engine-issued acquisition receipt IDs must be unique")
        if len({item.receipt_id for item in self.acquisition_receipts}) != len(
            self.acquisition_receipts
        ):
            raise ValueError("v3 acquisition receipt IDs must be unique")
        for receipt in self.acquisition_receipts:
            _validate_v3_acquisition_receipt(self, receipt)
            if issued_acquisition_receipts.get(receipt.issuance_id) != receipt.receipt_hash:
                raise ValueError("v3 acquisition receipt was not issued by the engine")
        if len({item.submission_id for item in self.stage_outcomes}) != len(self.stage_outcomes):
            raise ValueError("v3 stage outcome submission IDs must be unique")
        if len({(x.proposition_id, x.pass_id, x.stage_id) for x in self.stage_outcomes}) != len(
            self.stage_outcomes
        ):
            raise ValueError("a v3 stage may close only once")
        for outcome in self.stage_outcomes:
            if (
                outcome.run_id,
                outcome.result_id,
                outcome.domain_id,
                outcome.question_id,
                outcome.obligation_revision_id,
                outcome.obligation_hash,
                outcome.inventory_snapshot_hash,
            ) != (
                self.run_id,
                self.result_id,
                self.domain_id,
                self.question_id,
                self.obligation_revision_id,
                self.obligation_hash,
                self.inventory_snapshot_hash,
            ):
                raise ValueError("v3 stage outcome has stale workflow identity")
            scope = scopes.get((outcome.proposition_id, outcome.pass_id, outcome.stage_id))
            if scope is None or outcome.materialized_scope_id != scope.scope_id:
                raise ValueError("v3 stage outcome must bind its materialized scope")
            if outcome.acquisition_receipt_id is not None and not any(
                item.receipt_id == outcome.acquisition_receipt_id
                for item in self.acquisition_receipts
            ):
                raise ValueError(
                    "v3 unavailable-source outcome must bind a recorded acquisition receipt"
                )
        return self

    @property
    def content_hash(self) -> ContentHash:
        return canonical_hash(self.model_dump(mode="json"))


def _v3_stage_map(
    obligation: EvidenceSearchObligation,
) -> dict[tuple[Identifier, Identifier, Identifier], object]:
    return {
        (proposition.id, evidence_pass.id, stage.id): stage
        for proposition in obligation.propositions
        for evidence_pass in proposition.evidence_passes
        for stage in evidence_pass.coverage_stages
    }


def _v3_inventory_hash(inventory: tuple[V3AuthorizedSource, ...]) -> ContentHash:
    return canonical_hash(tuple(item.model_dump(mode="json") for item in inventory))


def _v3_preview_is_self_contained(exposure: V3PageExposure) -> bool:
    flags = exposure.triage_flags
    return not (
        exposure.left_omitted_character_count
        or exposure.right_omitted_character_count
        or exposure.undisplayed_match_count
        or exposure.warnings
        or exposure.table_headers
        or exposure.caption
        or flags.has_reading_order_uncertainty
        or flags.has_visual_uncertainty
        or flags.has_duplicate_lineage
        or flags.is_table_content
        or flags.has_context_dependency
        or flags.has_possible_contradiction
    )


def _v3_intent(state: V3EvidenceWorkflowState, attempt: V3SearchAttempt):
    for proposition in state.obligation.propositions:
        if proposition.id != attempt.proposition_id:
            continue
        for evidence_pass in proposition.evidence_passes:
            if evidence_pass.id != attempt.pass_id:
                continue
            for stage in evidence_pass.coverage_stages:
                if stage.id == attempt.stage_id:
                    return next(
                        (x for x in stage.navigation_intents if x.id == attempt.intent_id), None
                    )
    return None


def _v3_scope(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> V3MaterializedStageScope:
    return next(
        x
        for x in state.stage_scopes
        if (x.proposition_id, x.pass_id, x.stage_id) == (proposition_id, pass_id, stage_id)
    )


def start_v3_search_attempt(
    state: V3EvidenceWorkflowState, attempt: V3SearchAttempt
) -> V3EvidenceWorkflowState:
    """Append a query only for the exact engine-issued Search intent and scope."""

    if attempt.attempt_id in {x.attempt_id for x in state.attempts}:
        raise ValueError("v3 search attempt ID has already been issued")
    intent = _v3_intent(state, attempt)
    if intent is None or intent.kind is not EvidenceNavigationIntentKind.SEARCH:
        raise ValueError("v3 attempt must bind an issued Search navigation intent")
    scope = _v3_scope(state, attempt.proposition_id, attempt.pass_id, attempt.stage_id)
    if attempt.source_scope_hash != scope.authorized_source_scope_hash:
        raise ValueError("v3 attempt source scope must bind the materialized stage scope")
    if attempt.query.source_ids != scope.authorized_source_ids:
        raise ValueError("v3 query Source IDs must exactly equal the materialized stage scope")
    current = [
        x
        for x in state.attempts
        if x.intent_id == attempt.intent_id and x.kind is V3AttemptKind.SELECTED
    ]
    if attempt.kind is V3AttemptKind.SUPERSEDED:
        raise ValueError("use supersede_v3_search_attempt to preserve audit history")
    if attempt.kind is V3AttemptKind.SELECTED and current:
        raise ValueError("replace a v3 selected query only through explicit supersession")
    return state.model_copy(update={"attempts": (*state.attempts, attempt)})


def supersede_v3_search_attempt(
    state: V3EvidenceWorkflowState,
    *,
    old_attempt_id: Identifier,
    replacement: V3SearchAttempt,
    rationale: str,
) -> V3EvidenceWorkflowState:
    old = next((x for x in state.attempts if x.attempt_id == old_attempt_id), None)
    if old is None or old.kind is not V3AttemptKind.SELECTED:
        raise ValueError("only a current selected v3 attempt may be superseded")
    if replacement.kind is not V3AttemptKind.SELECTED or replacement.intent_id != old.intent_id:
        raise ValueError("v3 query supersession may replace only the same navigation intent")
    if not rationale.strip():
        raise ValueError("v3 query supersession requires a rationale")
    retired = old.model_copy(
        update={
            "kind": V3AttemptKind.SUPERSEDED,
            "superseded_by_attempt_id": replacement.attempt_id,
            "supersession_rationale": rationale,
        }
    )
    base = state.model_copy(
        update={
            "attempts": tuple(
                retired if x.attempt_id == old_attempt_id else x for x in state.attempts
            )
        }
    )
    return start_v3_search_attempt(
        base, replacement.model_copy(update={"supersedes_attempt_id": old_attempt_id})
    )


def record_v3_page_exposure(
    state: V3EvidenceWorkflowState, *, attempt_id: Identifier, page: EvidenceSearchPage
) -> V3EvidenceWorkflowState:
    """Record every exposed Search candidate; selected attempts cannot hide pages."""

    attempt = next((x for x in state.attempts if x.attempt_id == attempt_id), None)
    if attempt is None:
        raise ValueError("v3 page exposure requires an issued attempt")
    if page.snapshot_hash != state.snapshot_hash:
        raise ValueError("v3 search page snapshot does not match workflow state")
    if page.query_hash != attempt.query_hash:
        raise ValueError("v3 search page query does not match its issued attempt")
    if (page.policy_id, page.policy_hash) != (state.search_policy_id, state.search_policy_hash):
        raise ValueError("v3 search page policy does not match workflow state")
    scope = _v3_scope(state, attempt.proposition_id, attempt.pass_id, attempt.stage_id)
    authorized = {
        x.source_id: x
        for x in state.authorized_inventory
        if x.source_id in scope.authorized_source_ids
    }
    for candidate in page.candidates:
        source = authorized.get(candidate.source_id)
        if (
            source is None
            or not source.is_searchable
            or not source.has_exact_source_parse
            or (source.source_artifact_hash, source.parse_id)
            != (candidate.source_artifact_hash, candidate.parse_id)
        ):
            raise ValueError(
                "v3 search page candidate is outside the materialized Source/Parse scope"
            )
    proposed_page = V3ExposedPage(
        attempt_id=attempt_id,
        page_handle=page.page_handle,
        candidate_ids=page.candidate_ids,
        page_number=page.page_number,
        total_page_count=page.total_page_count,
        traversal_complete=page.traversal_complete,
    )
    proposed = tuple(
        V3PageExposure(
            attempt_id=attempt_id,
            page_handle=page.page_handle,
            candidate_id=x.candidate_id,
            canonical_unit_id=x.canonical_unit_id,
            location_handle=x.location_handle,
            source_id=x.source_id,
            source_artifact_hash=x.source_artifact_hash,
            parse_id=x.parse_id,
            canonical_start=x.canonical_start,
            canonical_end=x.canonical_end,
            left_omitted_character_count=x.left_omitted_character_count,
            right_omitted_character_count=x.right_omitted_character_count,
            undisplayed_match_count=x.undisplayed_match_count,
            warnings=x.warnings,
            page_number=page.page_number,
            total_page_count=page.total_page_count,
            traversal_complete=page.traversal_complete,
            triage_flags=x.triage_flags,
            table_headers=x.table_headers,
            caption=x.caption,
            duplicate_group_id=x.duplicate_group_id,
            retained_duplicate_target_id=x.retained_duplicate_target_id,
        )
        for x in page.candidates
    )
    old = next((x for x in state.pages if x.page_handle == page.page_handle), None)
    if old is not None:
        if (
            old != proposed_page
            or tuple(x for x in state.exposures if x.page_handle == page.page_handle) != proposed
        ):
            raise ValueError("v3 page handle has already been exposed with different content")
        return state
    return state.model_copy(
        update={"pages": (*state.pages, proposed_page), "exposures": (*state.exposures, *proposed)}
    )


def submit_v3_page_triage(
    state: V3EvidenceWorkflowState,
    *,
    submission_id: Identifier,
    attempt_id: Identifier,
    page_handles: tuple[str, ...],
    revisions: tuple[V3CandidateTriageRevision, ...],
) -> V3EvidenceWorkflowState:
    payload = {
        "submission_id": submission_id,
        "attempt_id": attempt_id,
        "page_handles": page_handles,
        "triage_revision_ids": tuple(x.revision_id for x in revisions),
        "content_hash": None,
    }
    proposed = V3PageTriageSubmission(**(payload | {"content_hash": canonical_hash(payload)}))
    existing = next((x for x in state.triage_submissions if x.submission_id == submission_id), None)
    if existing is not None:
        if existing != proposed:
            raise ValueError("v3 triage submission ID was replayed with different content")
        return state
    pages = [x for x in state.pages if x.page_handle in page_handles]
    if len(pages) != len(page_handles) or any(x.attempt_id != attempt_id for x in pages):
        raise ValueError("v3 triage must name complete pages of one issued attempt")
    expected = {
        (x.attempt_id, x.page_handle, x.candidate_id)
        for x in state.exposures
        if x.page_handle in page_handles
    }
    actual = {(x.attempt_id, x.page_handle, x.candidate_id) for x in revisions}
    if actual != expected or len(actual) != len(revisions):
        raise ValueError("v3 triage must disposition every exposed candidate exactly once")
    if any(x.sq_id != state.question_id for x in revisions):
        raise ValueError("v3 triage must bind the workflow signaling question")
    exposure_by_occurrence = {
        (x.attempt_id, x.page_handle, x.candidate_id): x for x in state.exposures
    }
    for revision in revisions:
        exposure = exposure_by_occurrence[
            (revision.attempt_id, revision.page_handle, revision.candidate_id)
        ]
        if (
            revision.kind is V3TriageKind.IRRELEVANT
            and revision.basis is TriageBasis.PREVIEW
            and not _v3_preview_is_self_contained(exposure)
        ):
            raise ValueError("preview-only v3 triage requires a complete unambiguous preview")
        if (
            revision.kind is V3TriageKind.UNRESOLVED
            and not _v3_preview_is_self_contained(exposure)
            and not revision.read_view_receipt
        ):
            raise ValueError("materially unresolved v3 triage requires a read-view receipt")
    all_revisions = (*state.triage_revisions, *revisions)
    retained_by_candidate = {
        item.candidate_id: item for item in all_revisions if item.kind is V3TriageKind.RETAINED
    }
    for revision in revisions:
        if revision.kind is not V3TriageKind.DUPLICATE:
            continue
        target = retained_by_candidate.get(revision.retained_target_id)
        if target is None or not target.read_view_receipt:
            raise ValueError("duplicate v3 triage requires a read-backed retained target")
        if (
            revision.retained_target_read_view_receipt is not None
            and revision.retained_target_read_view_receipt != target.read_view_receipt
        ):
            raise ValueError("duplicate target receipt must match the retained target receipt")
    if any(x.revision_id in {y.revision_id for y in state.triage_revisions} for x in revisions):
        raise ValueError("v3 triage revision ID has already been issued")
    if any(set(page_handles).intersection(x.page_handles) for x in state.triage_submissions):
        raise ValueError("an exposed v3 page may be triaged only once")
    return state.model_copy(
        update={
            "triage_revisions": (*state.triage_revisions, *revisions),
            "triage_submissions": (*state.triage_submissions, proposed),
        }
    )


def record_v3_navigation_completion(
    state: V3EvidenceWorkflowState, receipt: V3NavigationCompletionReceipt
) -> V3EvidenceWorkflowState:
    """Accept only a receipt whose exact intent, scope, snapshot, and policy match."""

    stage = _v3_stage_map(state.obligation).get(
        (receipt.proposition_id, receipt.pass_id, receipt.stage_id)
    )
    if stage is None:
        raise ValueError("v3 receipt names an unknown materialized stage")
    intent = next((x for x in stage.navigation_intents if x.id == receipt.intent_id), None)
    scope = _v3_scope(state, receipt.proposition_id, receipt.pass_id, receipt.stage_id)
    if (
        intent is None
        or intent.kind != receipt.kind
        or receipt.source_scope_hash != scope.authorized_source_scope_hash
    ):
        raise ValueError("v3 receipt does not bind its issued navigation intent and scope")
    if receipt.snapshot_hash != state.snapshot_hash:
        raise ValueError("v3 receipt snapshot is stale")
    if receipt.kind is EvidenceNavigationIntentKind.VISUAL_REVIEW:
        expected = (state.visual_policy_id, state.visual_policy_hash)
        actual = (receipt.visual_policy_id, receipt.visual_policy_hash)
    else:
        expected = (state.read_policy_id, state.read_policy_hash)
        actual = (receipt.read_policy_id, receipt.read_policy_hash)
    if actual != expected:
        raise ValueError("v3 receipt policy identity is stale")
    if dict(state.issued_receipt_hashes).get(receipt.issuance_id) != receipt.receipt_hash:
        raise ValueError("v3 receipt was not resolved from engine-owned issuance")
    old = next((x for x in state.completion_receipts if x.receipt_id == receipt.receipt_id), None)
    if old is not None:
        if old != receipt:
            raise ValueError("v3 navigation receipt ID was replayed with different content")
        return state
    return state.model_copy(update={"completion_receipts": (*state.completion_receipts, receipt)})


def _v3_search_attempt_terminal(state: V3EvidenceWorkflowState, attempt: V3SearchAttempt) -> bool:
    pages = [x for x in state.pages if x.attempt_id == attempt.attempt_id]
    if not pages:
        return False
    totals = {x.total_page_count for x in pages}
    if len(totals) != 1 or {x.page_number for x in pages} != set(range(1, next(iter(totals)) + 1)):
        return False
    if not any(x.traversal_complete for x in pages):
        return False
    exposed = {
        (x.attempt_id, x.page_handle, x.candidate_id)
        for x in state.exposures
        if x.attempt_id == attempt.attempt_id
    }
    triaged = {(x.attempt_id, x.page_handle, x.candidate_id) for x in state.triage_revisions}
    return exposed.issubset(triaged)


def _v3_intent_progress(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
    intent_id: Identifier,
) -> tuple[bool, bool, tuple[str, ...]]:
    """Return terminal, clean, blockers for one intent, never its siblings."""

    stage = _v3_stage_map(state.obligation)[(proposition_id, pass_id, stage_id)]
    intent = next(item for item in stage.navigation_intents if item.id == intent_id)
    if intent.kind is not EvidenceNavigationIntentKind.SEARCH:
        done = any(item.intent_id == intent_id for item in state.completion_receipts)
        return done, done, () if done else ("missing_navigation_receipt",)
    attempts = [item for item in state.attempts if item.intent_id == intent_id]
    selected = [item for item in attempts if item.kind is V3AttemptKind.SELECTED]
    if len(selected) != 1:
        return False, False, ("missing_selected_search_attempt",)
    selected_terminal = _v3_search_attempt_terminal(state, selected[0])
    exposed = [
        item for item in state.exposures if item.attempt_id in {x.attempt_id for x in attempts}
    ]
    triaged = {
        (item.attempt_id, item.page_handle, item.candidate_id) for item in state.triage_revisions
    }
    historic_complete = all(
        (item.attempt_id, item.page_handle, item.candidate_id) in triaged for item in exposed
    )
    unresolved = any(
        item.attempt_id in {x.attempt_id for x in attempts} and item.kind is V3TriageKind.UNRESOLVED
        for item in state.triage_revisions
    )
    terminal = selected_terminal and historic_complete
    blockers: list[str] = []
    if not selected_terminal:
        blockers.append("selected_search_traversal_incomplete")
    if not historic_complete:
        blockers.append("superseded_search_candidate_undispositioned")
    if unresolved:
        blockers.append("unresolved_semantic_review")
    return terminal, terminal and not unresolved, tuple(blockers)


def _v3_stage_intents_complete(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> bool:
    stage = _v3_stage_map(state.obligation)[(proposition_id, pass_id, stage_id)]
    return all(
        _v3_intent_progress(state, proposition_id, pass_id, stage_id, intent.id)[0]
        for intent in stage.navigation_intents
    )


def _v3_stage_has_unresolved_review(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> bool:
    stage = _v3_stage_map(state.obligation)[(proposition_id, pass_id, stage_id)]
    return any(
        "unresolved_semantic_review"
        in _v3_intent_progress(state, proposition_id, pass_id, stage_id, intent.id)[2]
        for intent in stage.navigation_intents
    )


def _v3_scope_limited(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> bool:
    return bool(_v3_scope(state, proposition_id, pass_id, stage_id).role_limitations)


def _v3_trigger_dispositions(
    state: V3EvidenceWorkflowState, stage_id: Identifier
) -> tuple[V3TriggerDisposition, ...]:
    outcome = next((x for x in state.stage_outcomes if x.stage_id == stage_id), None)
    return () if outcome is None else outcome.trigger_dispositions


def _v3_stage_active(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> bool:
    proposition = next(x for x in state.obligation.propositions if x.id == proposition_id)
    evidence_pass = next(x for x in proposition.evidence_passes if x.id == pass_id)
    stage = next(x for x in evidence_pass.coverage_stages if x.id == stage_id)
    if evidence_pass.activation is EvidencePassActivation.TRIGGERED:
        pass_trigger_ids = set(evidence_pass.activation_trigger_ids)
        if not any(
            d.trigger_id in pass_trigger_ids and d.kind is not V3TriggerDispositionKind.FALSE
            for outcome in state.stage_outcomes
            for d in outcome.trigger_dispositions
        ):
            return False
    if stage.activation is EvidenceStageActivation.MANDATORY:
        return True
    return any(
        d.trigger_id in set(stage.activation_trigger_ids)
        and d.kind is not V3TriggerDispositionKind.FALSE
        for outcome in state.stage_outcomes
        for d in outcome.trigger_dispositions
    )


def _v3_unavailable_receipt_sources(
    state: V3EvidenceWorkflowState, scope: V3MaterializedStageScope
) -> tuple[Identifier, ...]:
    unavailable_roles = {
        limitation.role
        for limitation in scope.role_limitations
        if limitation.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE
        and limitation.role is not None
    }
    return tuple(
        source.source_id
        for source in state.authorized_inventory
        if source.availability is not SourceAvailability.ACQUIRED
        and set(source.roles).intersection(unavailable_roles)
    )


def _v3_unavailable_limitation_hash(scope: V3MaterializedStageScope) -> ContentHash:
    return canonical_hash(
        tuple(
            limitation.model_dump(mode="json")
            for limitation in scope.role_limitations
            if limitation.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE
        )
    )


def _validate_v3_acquisition_receipt(
    state: V3EvidenceWorkflowState, receipt: V3AcquisitionAttemptReceipt
) -> None:
    receipt_payload = receipt.model_dump(mode="json")
    receipt_payload["receipt_hash"] = None
    if receipt.receipt_hash != canonical_hash(receipt_payload):
        raise ValueError("v3 acquisition receipt hash is forged or stale")
    scope = _v3_scope(state, receipt.proposition_id, receipt.pass_id, receipt.stage_id)
    if (
        receipt.run_id,
        receipt.result_id,
        receipt.domain_id,
        receipt.question_id,
        receipt.materialized_scope_id,
        receipt.inventory_snapshot_hash,
    ) != (
        state.run_id,
        state.result_id,
        state.domain_id,
        state.question_id,
        scope.scope_id,
        state.inventory_snapshot_hash,
    ):
        raise ValueError("v3 acquisition receipt has stale work, scope, or inventory identity")
    if not any(
        item.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE for item in scope.role_limitations
    ):
        raise ValueError("v3 acquisition receipt requires a source-unavailable scope limitation")
    if receipt.unavailable_source_ids != _v3_unavailable_receipt_sources(state, scope):
        raise ValueError("v3 acquisition receipt must bind every exact unavailable Source")
    if receipt.limitation_hash != _v3_unavailable_limitation_hash(scope):
        raise ValueError("v3 acquisition receipt must bind the exact source limitation")


def record_v3_acquisition_attempt(
    state: V3EvidenceWorkflowState, receipt: V3AcquisitionAttemptReceipt
) -> V3EvidenceWorkflowState:
    """Record one pre-issued acquisition receipt; acquisition itself lives outside navigation."""

    _validate_v3_acquisition_receipt(state, receipt)
    if (
        dict(state.issued_acquisition_receipt_hashes).get(receipt.issuance_id)
        != receipt.receipt_hash
    ):
        raise ValueError("v3 acquisition receipt was not issued by the engine")
    existing = next(
        (item for item in state.acquisition_receipts if item.receipt_id == receipt.receipt_id), None
    )
    if existing is not None:
        if existing != receipt:
            raise ValueError("v3 acquisition receipt ID was replayed with different content")
        return state
    return state.model_copy(update={"acquisition_receipts": (*state.acquisition_receipts, receipt)})


def _validate_v3_outcome_acquisition_receipt(
    state: V3EvidenceWorkflowState,
    submission: V3EvidenceStageOutcomeSubmission,
) -> None:
    """Require the exact engine-issued receipt whenever unavailability contributes."""

    receipt = next(
        (
            item
            for item in state.acquisition_receipts
            if item.receipt_id == submission.acquisition_receipt_id
        ),
        None,
    )
    if receipt is None:
        raise ValueError("source unavailability requires a recorded acquisition receipt")
    _validate_v3_acquisition_receipt(state, receipt)
    if (
        receipt.proposition_id,
        receipt.pass_id,
        receipt.stage_id,
        receipt.materialized_scope_id,
    ) != (
        submission.proposition_id,
        submission.pass_id,
        submission.stage_id,
        submission.materialized_scope_id,
    ):
        raise ValueError("acquisition receipt must bind the unavailable outcome stage")


def provision_v3_scope_acquisition_receipts(
    state: V3EvidenceWorkflowState,
) -> V3EvidenceWorkflowState:
    """Issue receipts for unavailable Sources already established by inventorying."""

    current = state
    for scope in state.stage_scopes:
        unavailable_source_ids = _v3_unavailable_receipt_sources(state, scope)
        if not unavailable_source_ids or not any(
            item.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE for item in scope.role_limitations
        ):
            continue
        identity = canonical_hash(
            {
                "run_id": state.run_id,
                "result_id": state.result_id,
                "domain_id": state.domain_id,
                "question_id": state.question_id,
                "scope_id": scope.scope_id,
                "inventory_snapshot_hash": state.inventory_snapshot_hash,
                "unavailable_source_ids": unavailable_source_ids,
            }
        )[7:]
        unsigned = V3AcquisitionAttemptReceipt.model_construct(
            receipt_id=f"acquisition-receipt:{identity}",
            issuance_id=f"acquisition-issuance:{identity}",
            run_id=state.run_id,
            result_id=state.result_id,
            domain_id=state.domain_id,
            question_id=state.question_id,
            proposition_id=scope.proposition_id,
            pass_id=scope.pass_id,
            stage_id=scope.stage_id,
            materialized_scope_id=scope.scope_id,
            inventory_snapshot_hash=state.inventory_snapshot_hash,
            unavailable_source_ids=unavailable_source_ids,
            limitation_hash=_v3_unavailable_limitation_hash(scope),
            receipt_hash="",
        )
        payload = unsigned.model_dump(mode="json")
        payload["receipt_hash"] = None
        receipt = unsigned.model_copy(update={"receipt_hash": canonical_hash(payload)})
        issued = dict(current.issued_acquisition_receipt_hashes)
        prior = issued.get(receipt.issuance_id)
        if prior is not None and prior != receipt.receipt_hash:
            raise ValueError("v3 acquisition issuance identity was reused with different content")
        if prior is None:
            issued[receipt.issuance_id] = receipt.receipt_hash
            current = current.model_copy(
                update={"issued_acquisition_receipt_hashes": tuple(sorted(issued.items()))}
            )
        current = record_v3_acquisition_attempt(current, receipt)
    return current


def v3_stage_is_active(
    state: V3EvidenceWorkflowState,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage_id: Identifier,
) -> bool:
    """Return whether an engine-materialized stage is currently authorized."""

    return _v3_stage_active(state, proposition_id, pass_id, stage_id)


def submit_evidence_stage_outcome(
    state: V3EvidenceWorkflowState, submission: V3EvidenceStageOutcomeSubmission
) -> V3EvidenceWorkflowState:
    """Close one active stage only after its issued navigation evidence is auditable."""

    existing = next(
        (x for x in state.stage_outcomes if x.submission_id == submission.submission_id), None
    )
    if existing is not None:
        if existing != submission:
            raise ValueError("v3 stage outcome submission ID was replayed with different content")
        return state
    expected_identity = (
        state.run_id,
        state.result_id,
        state.domain_id,
        state.question_id,
        state.obligation_revision_id,
        state.obligation_hash,
        state.inventory_snapshot_hash,
    )
    actual_identity = (
        submission.run_id,
        submission.result_id,
        submission.domain_id,
        submission.question_id,
        submission.obligation_revision_id,
        submission.obligation_hash,
        submission.inventory_snapshot_hash,
    )
    if actual_identity != expected_identity:
        raise ValueError("v3 stage outcome has stale obligation, inventory, or work identities")
    stage = _v3_stage_map(state.obligation).get(
        (submission.proposition_id, submission.pass_id, submission.stage_id)
    )
    if (
        stage is None
        or submission.materialized_scope_id
        != _v3_scope(
            state, submission.proposition_id, submission.pass_id, submission.stage_id
        ).scope_id
    ):
        raise ValueError("v3 stage outcome must bind its exact materialized stage scope")
    if not _v3_stage_active(
        state, submission.proposition_id, submission.pass_id, submission.stage_id
    ):
        raise ValueError("cannot close an inactive triggered v3 stage")
    pass_stages = next(
        x.coverage_stages
        for p in state.obligation.propositions
        if p.id == submission.proposition_id
        for x in p.evidence_passes
        if x.id == submission.pass_id
    )
    index = next(i for i, x in enumerate(pass_stages) if x.id == submission.stage_id)
    prior = pass_stages[:index]
    if any(
        _v3_stage_active(state, submission.proposition_id, submission.pass_id, x.id)
        and not any(y.stage_id == x.id for y in state.stage_outcomes)
        for x in prior
    ):
        raise ValueError("mandatory and activated v3 stages must close in order")
    trigger_ids = {
        x.id
        for x in state.obligation.escalation_triggers
        if x.source_stage_id == submission.stage_id
    }
    if {x.trigger_id for x in submission.trigger_dispositions} != trigger_ids:
        raise ValueError("v3 stage outcome must include complete trigger dispositions")
    escalated = any(
        x.kind is not V3TriggerDispositionKind.FALSE for x in submission.trigger_dispositions
    )
    navigation_complete = _v3_stage_intents_complete(
        state, submission.proposition_id, submission.pass_id, submission.stage_id
    )
    unresolved_review = _v3_stage_has_unresolved_review(
        state, submission.proposition_id, submission.pass_id, submission.stage_id
    )
    limited_scope = _v3_scope_limited(
        state, submission.proposition_id, submission.pass_id, submission.stage_id
    )
    scope = _v3_scope(state, submission.proposition_id, submission.pass_id, submission.stage_id)
    if submission.outcome_kind is EvidenceCoverageStageOutcomeKind.OBLIGATION_SATISFIED:
        if not navigation_complete or unresolved_review or limited_scope or escalated:
            raise ValueError(
                "obligation_satisfied requires clean traversal, false triggers, and complete scope"
            )
    elif submission.outcome_kind is EvidenceCoverageStageOutcomeKind.ESCALATION_REQUIRED:
        if not navigation_complete or not escalated:
            raise ValueError(
                "escalation_required requires completed navigation and a true or unresolved trigger"
            )
    elif (
        submission.outcome_kind is EvidenceCoverageStageOutcomeKind.SOURCE_UNAVAILABLE_AFTER_ATTEMPT
    ):
        if not limited_scope:
            raise ValueError(
                "source_unavailable_after_attempt requires a materialized scope limitation"
            )
        if scope.authorized_source_ids and not navigation_complete:
            raise ValueError(
                "a partially available scope requires exhaustive traversal before terminalization"
            )
        _validate_v3_outcome_acquisition_receipt(state, submission)
    elif submission.outcome_kind is EvidenceCoverageStageOutcomeKind.SCOPE_LIMITATION_UNRESOLVED:
        terminal_kinds = {
            V3ScopeLimitationKind.MATERIAL_UNRESOLVED,
            V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED,
            V3ScopeLimitationKind.CROSS_SOURCE_INSUFFICIENT,
        }
        if not any(item.kind in terminal_kinds for item in scope.role_limitations):
            raise ValueError(
                "scope_limitation_unresolved requires an exact terminal scope limitation"
            )
        if scope.authorized_source_ids and not navigation_complete:
            raise ValueError(
                "a nonempty limited scope requires exhaustive traversal before terminalization"
            )
        if any(
            item.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE for item in scope.role_limitations
        ):
            _validate_v3_outcome_acquisition_receipt(state, submission)
    elif (
        submission.outcome_kind is EvidenceCoverageStageOutcomeKind.SEMANTIC_UNCERTAINTY_UNRESOLVED
    ):
        if not navigation_complete or not unresolved_review:
            raise ValueError(
                "semantic_uncertainty_unresolved requires exhaustive traversal "
                "and unresolved review"
            )
    return state.model_copy(update={"stage_outcomes": (*state.stage_outcomes, submission)})


def v3_coverage_progress(state: V3EvidenceWorkflowState) -> dict[str, object]:
    """Deterministic proposition → pass → stage → intent progress with blockers."""

    def satisfactorily_closed(
        proposition_id: Identifier,
        pass_id: Identifier,
        stage_id: Identifier,
        seen: frozenset[str] = frozenset(),
    ) -> bool:
        if stage_id in seen:
            return False
        outcome = next((item for item in state.stage_outcomes if item.stage_id == stage_id), None)
        if outcome is None:
            return False
        if outcome.outcome_kind is EvidenceCoverageStageOutcomeKind.OBLIGATION_SATISFIED:
            return True
        if outcome.outcome_kind is not EvidenceCoverageStageOutcomeKind.ESCALATION_REQUIRED:
            return False
        targets = [
            item.target_stage_id
            for item in state.obligation.escalation_triggers
            if item.source_stage_id == stage_id
        ]
        return bool(targets) and all(
            satisfactorily_closed(proposition_id, pass_id, target, seen | {stage_id})
            for target in targets
        )

    propositions = []
    ready = True
    for proposition in state.obligation.propositions:
        passes = []
        for evidence_pass in proposition.evidence_passes:
            stages = []
            pass_is_active = (
                evidence_pass.activation is not EvidencePassActivation.TRIGGERED
                or any(
                    d.trigger_id in set(evidence_pass.activation_trigger_ids)
                    and d.kind is not V3TriggerDispositionKind.FALSE
                    for o in state.stage_outcomes
                    for d in o.trigger_dispositions
                )
            )
            for stage in evidence_pass.coverage_stages:
                active = pass_is_active and _v3_stage_active(
                    state, proposition.id, evidence_pass.id, stage.id
                )
                outcome = next((x for x in state.stage_outcomes if x.stage_id == stage.id), None)
                intents = []
                for intent in stage.navigation_intents:
                    terminal, clean, intent_blockers = _v3_intent_progress(
                        state, proposition.id, evidence_pass.id, stage.id, intent.id
                    )
                    intents.append(
                        {
                            "intent_id": intent.id,
                            "kind": intent.kind,
                            "complete": terminal,
                            "clean": clean,
                            "blockers": intent_blockers,
                        }
                    )
                blockers: tuple[str, ...] = ()
                if active:
                    if outcome is None:
                        blockers = ("stage_outcome_missing",)
                    elif not satisfactorily_closed(proposition.id, evidence_pass.id, stage.id):
                        if (
                            outcome.outcome_kind
                            is EvidenceCoverageStageOutcomeKind.ESCALATION_REQUIRED
                        ):
                            blockers = ("active_escalation_target_stage",)
                        else:
                            blockers = (outcome.outcome_kind.value,)
                    elif _v3_scope_limited(state, proposition.id, evidence_pass.id, stage.id):
                        blockers = ("unavailable_or_unresolved_required_scope",)
                if active and blockers:
                    ready = False
                stages.append(
                    {
                        "stage_id": stage.id,
                        "active": active,
                        "outcome": None if outcome is None else outcome.outcome_kind,
                        "intents": tuple(intents),
                        "blockers": blockers,
                    }
                )
            passes.append(
                {"pass_id": evidence_pass.id, "active": pass_is_active, "stages": tuple(stages)}
            )
        propositions.append({"proposition_id": proposition.id, "passes": tuple(passes)})
    return {
        "question_id": state.question_id,
        "question_ready": ready,
        "propositions": tuple(propositions),
    }
