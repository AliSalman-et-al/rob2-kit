"""Complete-search receipts, exact claims, derived facts, and frozen bundles."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
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


class V2TriageBasis(StrEnum):
    """The objectively auditable material supporting a terminal triage decision."""

    PREVIEW = "preview"
    READ_VIEW_RECEIPT = "read_view_receipt"


class V2IrrelevantReason(StrEnum):
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
    irrelevant_reason: V2IrrelevantReason | None = None
    retained_target_id: Identifier | None = None
    rationale: str | None = None
    basis: V2TriageBasis | None = None
    read_view_receipt: str | None = None
    retained_target_read_view_receipt: str | None = None

    @model_validator(mode="after")
    def validate_triage(self) -> V2CandidateTriageRevision:
        if self.kind is V2TriageKind.IRRELEVANT:
            if self.irrelevant_reason is None:
                raise ValueError("irrelevant triage requires a closed reason")
            if self.irrelevant_reason is V2IrrelevantReason.OTHER and not (
                self.rationale and self.rationale.strip()
            ):
                raise ValueError("the other irrelevant reason requires a rationale")
            if self.basis is None:
                raise ValueError(
                    "irrelevant triage requires an explicit preview or read receipt basis"
                )
            if self.basis is V2TriageBasis.PREVIEW and self.read_view_receipt is not None:
                raise ValueError("preview triage cannot attach a read-view receipt")
            if self.basis is V2TriageBasis.READ_VIEW_RECEIPT and not self.read_view_receipt:
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
            revision.kind is V2TriageKind.UNRESOLVED
            for revision in self.triage_revisions
        )


def _submission_hash(
    submission_id: Identifier,
    page_handles: tuple[str, ...],
    revisions: tuple[V2CandidateTriageRevision, ...],
) -> ContentHash:
    payload = {
        "submission_id": submission_id,
        "page_handles": page_handles,
        "triage_revision_ids": tuple(revision.revision_id for revision in revisions),
        "content_hash": None,
    }
    return canonical_hash(payload)


def start_v2_search_attempt(
    state: V2EvidenceWorkflowState,
    attempt: V2SearchAttempt,
) -> V2EvidenceWorkflowState:
    """Append an explicit selected or exploratory attempt without implicit replacement."""

    if attempt.attempt_id in {item.attempt_id for item in state.attempts}:
        raise ValueError("search attempt ID has already been issued")
    same_pass = [
        item
        for item in state.attempts
        if (item.sq_id, item.pass_kind) == (attempt.sq_id, attempt.pass_kind)
    ]
    if attempt.kind is V2QueryAttemptKind.SELECTED and any(
        item.kind is V2QueryAttemptKind.SELECTED for item in same_pass
    ):
        raise ValueError("replace a selected query only through explicit supersession")
    if attempt.kind is V2QueryAttemptKind.SUPERSEDED:
        raise ValueError("use supersede_v2_search_attempt to preserve both audit records")
    return state.model_copy(update={"attempts": (*state.attempts, attempt)})


def supersede_v2_search_attempt(
    state: V2EvidenceWorkflowState,
    *,
    old_attempt_id: Identifier,
    replacement: V2SearchAttempt,
    rationale: str,
) -> V2EvidenceWorkflowState:
    """Replace one selected attempt while retaining its non-crediting history."""

    old = next((item for item in state.attempts if item.attempt_id == old_attempt_id), None)
    if old is None or old.kind is not V2QueryAttemptKind.SELECTED:
        raise ValueError("only a current selected attempt may be superseded")
    if replacement.kind is not V2QueryAttemptKind.SELECTED:
        raise ValueError("a superseding replacement must be selected")
    if (replacement.sq_id, replacement.pass_kind) != (old.sq_id, old.pass_kind):
        raise ValueError("a replacement must retain its signaling-question pass")
    if not rationale.strip():
        raise ValueError("query supersession requires a rationale")
    retired = old.model_copy(
        update={
            "kind": V2QueryAttemptKind.SUPERSEDED,
            "superseded_by_attempt_id": replacement.attempt_id,
            "supersession_rationale": rationale,
        }
    )
    attempts = tuple(
        retired if item.attempt_id == old_attempt_id else item for item in state.attempts
    )
    return start_v2_search_attempt(
        state.model_copy(update={"attempts": attempts}),
        replacement.model_copy(update={"supersedes_attempt_id": old_attempt_id}),
    )


def record_v2_page_exposure(
    state: V2EvidenceWorkflowState,
    *,
    attempt_id: Identifier,
    page: EvidenceSearchPage,
) -> V2EvidenceWorkflowState:
    """Append every page/candidate edge exactly as the search page exposed it."""

    if page.snapshot_hash != state.snapshot_hash:
        raise ValueError("search page snapshot does not match workflow state")
    if page.policy_id != state.search_policy_id or page.policy_hash != state.search_policy_hash:
        raise ValueError("search page policy does not match workflow state")
    if attempt_id not in {attempt.attempt_id for attempt in state.attempts}:
        raise ValueError("page exposure requires an issued search attempt")
    existing_page = next(
        (item for item in state.pages if item.page_handle == page.page_handle), None
    )
    proposed = tuple(
        V2PageExposure(
            attempt_id=attempt_id,
            page_handle=page.page_handle,
            candidate_id=candidate.candidate_id,
            canonical_unit_id=candidate.canonical_unit_id,
            location_handle=candidate.location_handle,
            source_id=candidate.source_id,
            source_artifact_hash=candidate.source_artifact_hash,
            parse_id=candidate.parse_id,
            canonical_start=candidate.canonical_start,
            canonical_end=candidate.canonical_end,
            left_omitted_character_count=candidate.left_omitted_character_count,
            right_omitted_character_count=candidate.right_omitted_character_count,
            undisplayed_match_count=candidate.undisplayed_match_count,
            warnings=candidate.warnings,
            triage_flags=candidate.triage_flags,
            table_headers=candidate.table_headers,
            caption=candidate.caption,
            duplicate_group_id=candidate.duplicate_group_id,
            retained_duplicate_target_id=candidate.retained_duplicate_target_id,
            page_number=page.page_number,
            total_page_count=page.total_page_count,
            traversal_complete=page.traversal_complete,
        )
        for candidate in page.candidates
    )
    page_record = V2ExposedPage(
        attempt_id=attempt_id,
        page_handle=page.page_handle,
        candidate_ids=page.candidate_ids,
        page_number=page.page_number,
        total_page_count=page.total_page_count,
        traversal_complete=page.traversal_complete,
    )
    if existing_page is not None:
        existing = [edge for edge in state.exposures if edge.page_handle == page.page_handle]
        if existing_page != page_record or tuple(existing) != proposed:
            raise ValueError("page handle has already been exposed with different content")
        return state
    return state.model_copy(
        update={"pages": (*state.pages, page_record), "exposures": (*state.exposures, *proposed)}
    )


def submit_v2_page_triage(
    state: V2EvidenceWorkflowState,
    *,
    submission_id: Identifier,
    page_handles: tuple[str, ...],
    revisions: tuple[V2CandidateTriageRevision, ...],
) -> V2EvidenceWorkflowState:
    """Append an idempotent exhaustive triage partition over complete pages."""

    content_hash = _submission_hash(submission_id, page_handles, revisions)
    proposed = V2PageTriageSubmission(
        submission_id=submission_id,
        page_handles=page_handles,
        triage_revision_ids=tuple(revision.revision_id for revision in revisions),
        content_hash=content_hash,
    )
    existing = next(
        (item for item in state.triage_submissions if item.submission_id == submission_id), None
    )
    if existing is not None:
        if existing != proposed:
            raise ValueError("triage submission ID was replayed with different content")
        return state
    return state.model_copy(
        update={
            "triage_revisions": (*state.triage_revisions, *revisions),
            "triage_submissions": (*state.triage_submissions, proposed),
        }
    )
