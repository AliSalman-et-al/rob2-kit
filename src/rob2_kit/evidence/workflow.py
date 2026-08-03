"""Complete-search receipts, exact claims, derived facts, and frozen bundles."""

from __future__ import annotations

import base64
import binascii
import json
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.domain.evidence import VerificationStatus
from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    EvidenceSearchIndex,
    SearchPage,
    SearchPolicy,
    SearchQuery,
)


def _dependency_changed(
    current: RecordReference | ContentHash,
    bound: RecordReference,
) -> bool:
    if isinstance(current, RecordReference):
        return current != bound
    return current != bound.content_hash


def _looks_like_search_cursor(cursor: str) -> bool:
    """Check the structural envelope before an index verifies its MAC."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        envelope = json.loads(raw)
        encoded_payload = envelope["payload"]
        mac = envelope["mac"]
        if (
            not isinstance(encoded_payload, str)
            or not isinstance(mac, str)
            or len(mac) != 64
            or any(character not in "0123456789abcdef" for character in mac)
        ):
            return False
        payload = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        values = json.loads(payload)
        return {"snapshot", "query", "policy", "offset"} <= set(values)
    except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError):
        return False


class SearchPassKind(StrEnum):
    GUIDANCE_SEED = "guidance_seed"
    TRIAL_FOLLOW_UP = "trial_follow_up"
    CONTRADICTION = "contradiction"


class SearchResultDispositionKind(StrEnum):
    IRRELEVANT = "irrelevant"
    RETAINED_CANDIDATE = "retained_candidate"
    DUPLICATE = "duplicate"


class SearchResultDisposition(FrozenModel):
    unit_id: Identifier
    kind: SearchResultDispositionKind
    candidate_id: Identifier | None = None
    duplicate_of: Identifier | None = None

    @model_validator(mode="after")
    def validate_duplicate(self) -> SearchResultDisposition:
        if self.kind is SearchResultDispositionKind.DUPLICATE and self.duplicate_of is None:
            raise ValueError("duplicate search results require the covered unit ID")
        if self.kind is SearchResultDispositionKind.DUPLICATE and self.duplicate_of == self.unit_id:
            raise ValueError("duplicate search results cannot cover themselves")
        if self.kind is not SearchResultDispositionKind.DUPLICATE and self.duplicate_of is not None:
            raise ValueError("duplicate_of is only valid for duplicate search results")
        retained = self.kind is SearchResultDispositionKind.RETAINED_CANDIDATE
        if retained != (self.candidate_id is not None):
            raise ValueError("retained search results require exactly one candidate ID")
        return self


class SourceSearchState(StrEnum):
    SEARCHED = "searched"
    UNOBTAINED = "unobtained"
    UNREADABLE = "unreadable"
    UNSEARCHED = "unsearched"
    SEARCH_LIMITED = "search_limited"


class SourceSearchCoverage(FrozenModel):
    source_id: Identifier
    state: SourceSearchState
    sufficiently_readable: bool
    artifact_hash: ContentHash | None = None
    parse_record_hashes: tuple[ContentHash, ...] = ()
    limitations: tuple[str, ...] = ()


class VisualCandidateCoverage(FrozenModel):
    candidate_id: Identifier
    dispositioned: bool
    required: bool


class ExecutedSearchQuery(FrozenModel):
    sq_id: Identifier | None = None
    query: SearchQuery
    query_hash: ContentHash
    pass_kind: SearchPassKind
    seed_family: Identifier | None = None
    returned_unit_ids: tuple[Identifier, ...]
    traversal_complete: bool
    broad_query: bool = False
    broad_query_justification: str | None = None
    first_cursor: str | None = None
    last_cursor: str | None = None
    pages_traversed: int = Field(default=1, ge=1)
    snapshot_hash: ContentHash | None = None
    policy_id: Identifier | None = None
    policy_hash: ContentHash | None = None

    @model_validator(mode="after")
    def validate_query(self) -> ExecutedSearchQuery:
        if self.query_hash != canonical_hash(self.query):
            raise ValueError("query hash must bind the exact structured query and filters")
        if self.pass_kind is SearchPassKind.GUIDANCE_SEED and self.seed_family is None:
            raise ValueError("Guidance-seed queries require their seed family")
        if self.pass_kind is not SearchPassKind.GUIDANCE_SEED and self.seed_family is not None:
            raise ValueError("seed families apply only to Guidance-seed queries")
        if self.broad_query and not self.broad_query_justification:
            raise ValueError("broad queries require a complete-traversal justification")
        if (
            self.broad_query_justification is not None
            and not self.broad_query_justification.strip()
        ):
            raise ValueError("broad query justification cannot be blank")
        return self


class SearchCoverageReceipt(FrozenModel):
    """Immutable search-accounting data, not an authority by itself.

    ``recorder_proof`` is a deterministic content binding emitted after the
    runtime recorder verifies every page; hosts must retain that trust boundary
    when deciding whether a No-information basis is usable.
    """

    receipt_id: Identifier
    sq_id: Identifier
    snapshot_hash: ContentHash
    policy_id: Identifier
    policy_hash: ContentHash
    result_spec: RecordReference
    source_inventory: RecordReference
    parse_record_hashes: tuple[ContentHash, ...]
    guidance_release_id: Identifier
    project_rule_ids: tuple[Identifier, ...] = ()
    coverage_limits: tuple[str, ...] = ()
    required_seed_families: tuple[Identifier, ...]
    completed_seed_families: tuple[Identifier, ...]
    completed_passes: tuple[SearchPassKind, ...]
    executed_queries: tuple[ExecutedSearchQuery, ...]
    returned_unit_ids: tuple[Identifier, ...]
    result_dispositions: tuple[SearchResultDisposition, ...]
    sources: tuple[SourceSearchCoverage, ...]
    inventory_source_ids: tuple[Identifier, ...]
    visual_candidates: tuple[VisualCandidateCoverage, ...] = ()
    latest_complete_round_new_material_candidates: int = Field(default=0, ge=0)
    traversal_complete: bool
    interrupted: bool
    broad_query_justifications: tuple[str, ...] = ()
    resume_cursor: str | None = Field(default=None, min_length=1)
    resume_query_hash: ContentHash | None = None
    resume_snapshot_hash: ContentHash | None = None
    resume_policy_id: Identifier | None = None
    stopping_reason: str = (
        "mandatory protocol complete; latest complete round found no new material"
    )
    recorder_proof: ContentHash | None = None

    @model_validator(mode="before")
    @classmethod
    def bind_query_dependencies(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        raw_queries = values.get("executed_queries", ())
        bound_queries = []
        for raw_query in raw_queries:
            payload = (
                raw_query.model_dump(mode="python")
                if isinstance(raw_query, ExecutedSearchQuery)
                else dict(raw_query)
            )
            for field in ("sq_id", "snapshot_hash", "policy_id", "policy_hash"):
                bound_value = values.get(field)
                supplied_value = payload.get(field)
                if supplied_value is not None and supplied_value != bound_value:
                    raise ValueError(f"executed query {field} does not match the receipt")
                payload[field] = bound_value
            bound_queries.append(payload)
        values = dict(values)
        values["executed_queries"] = bound_queries
        return values

    @model_validator(mode="after")
    def validate_protocol_accounting(self) -> SearchCoverageReceipt:
        passes = set(self.completed_passes)
        missing_passes = set(SearchPassKind) - passes
        if missing_passes and not self.interrupted:
            names = ", ".join(sorted(item.value for item in missing_passes))
            raise ValueError(f"mandatory search pass missing: {names}")
        missing_seeds = set(self.required_seed_families) - set(self.completed_seed_families)
        if missing_seeds and not self.interrupted:
            raise ValueError(f"mandatory Guidance seed families missing: {sorted(missing_seeds)}")
        executed_passes = {item.pass_kind for item in self.executed_queries}
        if executed_passes != passes:
            raise ValueError("completed passes must match the attributable executed queries")
        if any(
            query.snapshot_hash is not None and query.snapshot_hash != self.snapshot_hash
            for query in self.executed_queries
        ):
            raise ValueError("executed queries must bind the receipt index snapshot")
        if any(
            query.sq_id is not None and query.sq_id != self.sq_id
            for query in self.executed_queries
        ):
            raise ValueError("executed queries must bind the receipt signaling question")
        if any(
            query.policy_id is not None and query.policy_id != self.policy_id
            for query in self.executed_queries
        ):
            raise ValueError("executed queries must bind the receipt search policy")
        if any(
            query.policy_hash is not None and query.policy_hash != self.policy_hash
            for query in self.executed_queries
        ):
            raise ValueError("executed queries must bind the exact search policy")
        contradiction_hashes = {
            item.query_hash
            for item in self.executed_queries
            if item.pass_kind is SearchPassKind.CONTRADICTION
        }
        ordinary_hashes = {
            item.query_hash
            for item in self.executed_queries
            if item.pass_kind is not SearchPassKind.CONTRADICTION
        }
        if not self.interrupted and contradiction_hashes & ordinary_hashes:
            raise ValueError("contradiction search must use a distinct query")
        executed_seeds = {
            item.seed_family for item in self.executed_queries if item.seed_family is not None
        }
        if executed_seeds != set(self.completed_seed_families):
            raise ValueError("completed seed families must match the attributable queries")
        if self.traversal_complete and any(
            not item.traversal_complete for item in self.executed_queries
        ):
            raise ValueError("coverage cannot be complete while a query traversal is incomplete")
        if self.resume_cursor is not None and self.resume_query_hash is None:
            raise ValueError("a resume cursor must bind the interrupted query hash")
        resume_record = next(
            (
                item
                for item in self.executed_queries
                if item.query_hash == self.resume_query_hash
            ),
            None,
        )
        if self.resume_cursor is not None and (
            resume_record is None or resume_record.last_cursor != self.resume_cursor
        ):
            raise ValueError("resume cursor must be the recorded query continuation")
        if self.resume_cursor is not None and not _looks_like_search_cursor(self.resume_cursor):
            raise ValueError("resume cursor is not an engine-issued opaque cursor")
        if self.resume_cursor is not None and self.resume_snapshot_hash != self.snapshot_hash:
            raise ValueError("resume cursor must bind the receipt snapshot")
        if self.resume_cursor is not None and self.resume_policy_id != self.policy_id:
            raise ValueError("resume cursor must bind the receipt search policy")
        if self.resume_cursor is None and (
            self.resume_snapshot_hash is not None or self.resume_policy_id is not None
        ):
            raise ValueError("resume dependency bindings require a resume cursor")
        if self.resume_query_hash is not None and self.resume_query_hash not in {
            query.query_hash for query in self.executed_queries
        }:
            raise ValueError("resume cursor must bind an executed search query")
        if self.resume_cursor is not None and not self.interrupted:
            raise ValueError("resume cursors are valid only for interrupted coverage")
        if self.interrupted and not self.traversal_complete and self.resume_cursor is None:
            raise ValueError("interrupted pagination must preserve an opaque resume cursor")
        returned = set(self.returned_unit_ids)
        if len(self.returned_unit_ids) != len(returned):
            raise ValueError("returned evidence unit IDs must be unique")
        query_returns = {
            unit_id for query in self.executed_queries for unit_id in query.returned_unit_ids
        }
        if any(
            len(query.returned_unit_ids) != len(set(query.returned_unit_ids))
            for query in self.executed_queries
        ):
            raise ValueError("each executed query must return each unit at most once")
        if returned != query_returns:
            raise ValueError("receipt results must match the union of executed-query results")
        disposition_ids = [item.unit_id for item in self.result_dispositions]
        if len(disposition_ids) != len(set(disposition_ids)):
            raise ValueError("each unique returned unit must have one disposition")
        if returned != set(disposition_ids):
            raise ValueError("every unique returned unit must have one disposition")
        for disposition in self.result_dispositions:
            if (
                disposition.kind is SearchResultDispositionKind.DUPLICATE
                and disposition.duplicate_of not in returned
            ):
                raise ValueError("duplicate dispositions must point to a returned unit")
        candidate_ids = [
            disposition.candidate_id
            for disposition in self.result_dispositions
            if disposition.candidate_id is not None
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("each retained search result must have a unique candidate ID")
        if self.latest_complete_round_new_material_candidates != 0 and self.traversal_complete:
            raise ValueError(
                "search cannot stop while the latest complete round found new material"
            )
        if len(self.inventory_source_ids) != len(set(self.inventory_source_ids)):
            raise ValueError("inventory source IDs must be unique")
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("source coverage IDs must be unique")
        if set(self.inventory_source_ids) != {source.source_id for source in self.sources}:
            raise ValueError("source coverage must account for the bound source inventory")
        if self.broad_query_justifications and any(
            not item.strip() for item in self.broad_query_justifications
        ):
            raise ValueError("broad query justifications cannot be blank")
        if not self.stopping_reason.strip():
            raise ValueError("stopping reason cannot be blank")
        if any(not item.strip() for item in self.coverage_limits):
            raise ValueError("coverage limitations cannot be blank")
        if self.recorder_proof is not None and not self._proof_is_valid():
            raise ValueError("receipt recorder proof does not bind its immutable payload")
        return self

    def _proof_is_valid(self) -> bool:
        if self.recorder_proof is None:
            return False
        unsigned = self.model_dump(mode="json")
        unsigned["recorder_proof"] = None
        return self.recorder_proof == canonical_hash(unsigned)

    def is_complete(self) -> bool:
        return (
            self._proof_is_valid()
            and self.traversal_complete
            and not self.interrupted
            and self.latest_complete_round_new_material_candidates == 0
        )

    @property
    def resumable(self) -> bool:
        return self.interrupted and (
            self.resume_cursor is not None or not self.traversal_complete
        )

    @property
    def has_contradiction_pass(self) -> bool:
        return any(
            query.pass_kind is SearchPassKind.CONTRADICTION for query in self.executed_queries
        )

    def establishes_no_information_basis(self) -> bool:
        return (
            self.is_complete()
            and not self.coverage_limits
            and bool(self.sources)
            and all(
                source.state is SourceSearchState.SEARCHED
                and source.sufficiently_readable
                and not source.limitations
                for source in self.sources
            )
            and all(
                not candidate.required or candidate.dispositioned
                for candidate in self.visual_candidates
            )
        )

    def retained_candidate_ids(self) -> set[Identifier]:
        return {
            item.candidate_id
            for item in self.result_dispositions
            if item.candidate_id is not None
        }

    @property
    def dependency_fingerprint(self) -> ContentHash:
        """Hash the exact dependencies that determine receipt usability."""
        payload = {
            "snapshot_hash": self.snapshot_hash,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "result_spec": self.result_spec.model_dump(mode="json"),
            "source_inventory": self.source_inventory.model_dump(mode="json"),
            "parse_record_hashes": self.parse_record_hashes,
            "guidance_release_id": self.guidance_release_id,
            "project_rule_ids": self.project_rule_ids,
        }
        return canonical_hash(payload)

    @property
    def content_hash(self) -> ContentHash:
        """Stable receipt hash, derived from the complete immutable payload."""
        return canonical_hash(self.model_dump(mode="json"))

    def stale_reasons(
        self,
        *,
        snapshot_hash: ContentHash | None = None,
        policy_id: Identifier | None = None,
        policy_hash: ContentHash | None = None,
        result_spec: RecordReference | ContentHash | None = None,
        source_inventory: RecordReference | ContentHash | None = None,
        parse_record_hashes: tuple[ContentHash, ...] | None = None,
        guidance_release_id: Identifier | None = None,
        project_rule_ids: tuple[Identifier, ...] | None = None,
        current_snapshot_hash: ContentHash | None = None,
        current_policy_id: Identifier | None = None,
        current_policy_hash: ContentHash | None = None,
        current_result_spec: RecordReference | ContentHash | None = None,
        current_source_inventory: RecordReference | ContentHash | None = None,
        current_parse_record_hashes: tuple[ContentHash, ...] | None = None,
        current_guidance_release_id: Identifier | None = None,
        current_project_rule_ids: tuple[Identifier, ...] | None = None,
    ) -> tuple[str, ...]:
        """Return exact dependency differences; omitted values mean unchanged."""
        if current_snapshot_hash is not None:
            snapshot_hash = current_snapshot_hash
        if current_policy_id is not None:
            policy_id = current_policy_id
        if current_policy_hash is not None:
            policy_hash = current_policy_hash
        if current_result_spec is not None:
            result_spec = current_result_spec
        if current_source_inventory is not None:
            source_inventory = current_source_inventory
        if current_parse_record_hashes is not None:
            parse_record_hashes = current_parse_record_hashes
        if current_guidance_release_id is not None:
            guidance_release_id = current_guidance_release_id
        if current_project_rule_ids is not None:
            project_rule_ids = current_project_rule_ids
        reasons: list[str] = []
        if snapshot_hash is not None and snapshot_hash != self.snapshot_hash:
            reasons.append("snapshot_hash")
        if policy_id is not None and policy_id != self.policy_id:
            reasons.append("policy_id")
        if policy_hash is not None and policy_hash != self.policy_hash:
            reasons.append("policy_hash")
        if result_spec is not None and _dependency_changed(result_spec, self.result_spec):
            reasons.append("result_spec")
        if source_inventory is not None and _dependency_changed(
            source_inventory, self.source_inventory
        ):
            reasons.append("source_inventory")
        if (
            parse_record_hashes is not None
            and tuple(parse_record_hashes) != self.parse_record_hashes
        ):
            reasons.append("parse_record_hashes")
        if guidance_release_id is not None and guidance_release_id != self.guidance_release_id:
            reasons.append("guidance_release_id")
        if project_rule_ids is not None and tuple(project_rule_ids) != self.project_rule_ids:
            reasons.append("project_rule_ids")
        return tuple(reasons)

    def is_stale(self, **dependencies: Any) -> bool:
        return bool(self.stale_reasons(**dependencies))

    def validate_resume_cursor(
        self,
        index: EvidenceSearchIndex,
        query: SearchQuery,
        *,
        policy: SearchPolicy | None = None,
    ) -> bool:
        """Verify the opaque cursor MAC and its exact snapshot/query/policy binding."""
        if self.resume_cursor is None or self.resume_query_hash != canonical_hash(query):
            return False
        active_policy = policy or SearchPolicy(policy_id=self.policy_id)
        if active_policy.policy_id != self.policy_id:
            return False
        resume_record = next(
            (item for item in self.executed_queries if item.query_hash == self.resume_query_hash),
            None,
        )
        if resume_record is None or resume_record.last_cursor != self.resume_cursor:
            return False
        try:
            page = index.search(
                query,
                policy=active_policy,
                cursor=self.resume_cursor,
                broad_query_justification=(
                    resume_record.broad_query_justification if resume_record else None
                ),
            )
        except ValueError:
            return False
        return (
            page.snapshot_hash == self.snapshot_hash
            and page.policy_id == self.policy_id
            and page.policy_hash == self.policy_hash
        )


class SearchCoverageRecorder:
    """Accumulate bounded search rounds into one validated coverage receipt."""

    def __init__(
        self,
        *,
        receipt_id: Identifier,
        sq_id: Identifier,
        snapshot_hash: ContentHash,
        policy_id: Identifier,
        policy_hash: ContentHash | None = None,
        result_spec: RecordReference,
        source_inventory: RecordReference,
        parse_record_hashes: tuple[ContentHash, ...],
        guidance_release_id: Identifier,
        required_seed_families: tuple[Identifier, ...],
        sources: tuple[SourceSearchCoverage, ...],
        inventory_source_ids: tuple[Identifier, ...],
        project_rule_ids: tuple[Identifier, ...] = (),
        coverage_limits: tuple[str, ...] = (),
        visual_candidates: tuple[VisualCandidateCoverage, ...] = (),
    ) -> None:
        self._metadata: dict[str, Any] = {
            "receipt_id": receipt_id,
            "sq_id": sq_id,
            "snapshot_hash": snapshot_hash,
            "policy_id": policy_id,
            "policy_hash": policy_hash or canonical_hash(SearchPolicy(policy_id=policy_id)),
            "result_spec": result_spec,
            "source_inventory": source_inventory,
            "parse_record_hashes": parse_record_hashes,
            "guidance_release_id": guidance_release_id,
            "required_seed_families": required_seed_families,
            "sources": sources,
            "inventory_source_ids": inventory_source_ids,
            "project_rule_ids": project_rule_ids,
            "coverage_limits": coverage_limits,
            "visual_candidates": visual_candidates,
        }
        self._queries: list[ExecutedSearchQuery] = []
        self._dispositions: dict[Identifier, SearchResultDisposition] = {}
        self._next_cursors: dict[tuple[SearchPassKind, ContentHash], str | None] = {}
        self._partial_traversal = False

    def record_query(self, query: ExecutedSearchQuery) -> None:
        """Reject unverified query metadata; use :meth:`record_page` instead."""
        raise ValueError("record_query requires an index-verified page; use record_page")

    def _record_query(self, query: ExecutedSearchQuery) -> None:
        """Record metadata after :meth:`record_page` has verified the page."""
        if (
            query.snapshot_hash is not None
            and query.snapshot_hash != self._metadata["snapshot_hash"]
        ):
            raise ValueError("search query snapshot does not match the recorder")
        if query.policy_id is not None and query.policy_id != self._metadata["policy_id"]:
            raise ValueError("search query policy does not match the recorder")
        if query.policy_hash is not None and query.policy_hash != self._metadata["policy_hash"]:
            raise ValueError("search query policy content does not match the recorder")
        if query.sq_id is not None and query.sq_id != self._metadata["sq_id"]:
            raise ValueError("search query signaling question does not match the recorder")
        if query.snapshot_hash is None or query.policy_id is None or query.policy_hash is None:
            query = query.model_copy(
                update={
                    "sq_id": self._metadata["sq_id"],
                    "snapshot_hash": self._metadata["snapshot_hash"],
                    "policy_id": self._metadata["policy_id"],
                    "policy_hash": self._metadata["policy_hash"],
                }
            )
        if query.sq_id is None:
            query = query.model_copy(update={"sq_id": self._metadata["sq_id"]})
        if query.pass_kind is SearchPassKind.CONTRADICTION and any(
            item.pass_kind is not SearchPassKind.CONTRADICTION
            and item.query_hash == query.query_hash
            for item in self._queries
        ):
            raise ValueError("contradiction search must use a distinct query")
        if query.pass_kind is not SearchPassKind.CONTRADICTION and any(
            item.pass_kind is SearchPassKind.CONTRADICTION
            and item.query_hash == query.query_hash
            for item in self._queries
        ):
            raise ValueError("contradiction search must use a distinct query")
        self._queries.append(query)

    def record_page(
        self,
        page: SearchPage,
        *,
        index: EvidenceSearchIndex,
        policy: SearchPolicy | None = None,
        query: SearchQuery,
        pass_kind: SearchPassKind,
        seed_family: Identifier | None = None,
        cursor: str | None = None,
        broad_query_justification: str | None = None,
    ) -> ExecutedSearchQuery:
        """Record one server-bounded page and its attributable traversal metadata."""
        active_policy = policy or SearchPolicy(policy_id=self._metadata["policy_id"])
        if active_policy.policy_id != self._metadata["policy_id"]:
            raise ValueError("search policy does not match the recorder")
        try:
            verified_page = index.search(
                query,
                policy=active_policy,
                cursor=cursor,
                broad_query_justification=broad_query_justification,
            )
        except ValueError as error:
            raise ValueError("recorded page failed index verification") from error
        if verified_page != page:
            raise ValueError("recorded page does not match the index result")
        if page.snapshot_hash != self._metadata["snapshot_hash"]:
            raise ValueError("search page snapshot does not match the recorder")
        if page.policy_id != self._metadata["policy_id"]:
            raise ValueError("search page policy does not match the recorder")
        if page.policy_hash != self._metadata["policy_hash"]:
            raise ValueError("search page policy content does not match the recorder")
        cursor_key = (pass_kind, page.query_hash)
        if cursor_key in self._next_cursors:
            expected_cursor = self._next_cursors[cursor_key]
            if expected_cursor is None or cursor != expected_cursor:
                raise ValueError("search pages must follow the issued continuation cursor")
        elif cursor is not None:
            self._partial_traversal = True
        page_record = ExecutedSearchQuery(
            query=query,
            query_hash=page.query_hash,
            sq_id=self._metadata["sq_id"],
            pass_kind=pass_kind,
            seed_family=seed_family,
            returned_unit_ids=tuple(hit.unit.unit_id for hit in page.hits),
            traversal_complete=page.next_cursor is None,
            broad_query=page.preview.requires_broad_query_justification,
            broad_query_justification=broad_query_justification,
            first_cursor=cursor,
            last_cursor=page.next_cursor,
            snapshot_hash=page.snapshot_hash,
            policy_id=page.policy_id,
            policy_hash=page.policy_hash,
        )
        if cursor_key in self._next_cursors:
            existing_index = next(
                index
                for index, item in enumerate(self._queries)
                if item.pass_kind is pass_kind and item.query_hash == page.query_hash
            )
            existing = self._queries[existing_index]
            aggregate = existing.model_copy(
                update={
                    "returned_unit_ids": tuple(
                        dict.fromkeys((*existing.returned_unit_ids, *page_record.returned_unit_ids))
                    ),
                    "traversal_complete": page_record.traversal_complete,
                    "last_cursor": page_record.last_cursor,
                    "pages_traversed": existing.pages_traversed + 1,
                }
            )
            self._queries[existing_index] = aggregate
        else:
            self._record_query(page_record)
        self._next_cursors[cursor_key] = page.next_cursor
        return page_record

    def record_disposition(self, disposition: SearchResultDisposition) -> None:
        """Record exactly one disposition for each unique returned unit."""
        if disposition.unit_id in self._dispositions:
            raise ValueError("search result unit already has a disposition")
        returned = {
            unit_id for query in self._queries for unit_id in query.returned_unit_ids
        }
        if disposition.unit_id not in returned:
            raise ValueError("disposition must cover a unit returned by a recorded query")
        self._dispositions[disposition.unit_id] = disposition

    def freeze(
        self,
        *,
        completed_seed_families: tuple[Identifier, ...],
        interrupted: bool = False,
        traversal_complete: bool = True,
        resume_cursor: str | None = None,
        resume_query_hash: ContentHash | None = None,
        resume_snapshot_hash: ContentHash | None = None,
        resume_policy_id: Identifier | None = None,
        resume_index: EvidenceSearchIndex | None = None,
        resume_query: SearchQuery | None = None,
        resume_policy: SearchPolicy | None = None,
        latest_complete_round_new_material_candidates: int = 0,
        stopping_reason: str = (
            "mandatory protocol complete; latest complete round found no new material"
        ),
        broad_query_justifications: tuple[str, ...] = (),
    ) -> SearchCoverageReceipt:
        passes = tuple(dict.fromkeys(query.pass_kind for query in self._queries))
        returned_unit_ids = tuple(
            dict.fromkeys(
                unit_id for query in self._queries for unit_id in query.returned_unit_ids
            )
        )
        if self._partial_traversal and traversal_complete and not interrupted:
            raise ValueError(
                "a traversal resumed from a continuation cursor cannot establish complete coverage"
            )
        if resume_cursor is not None:
            if resume_index is None or resume_query is None:
                raise ValueError(
                    "freeze requires an evidence index and query to verify a resume cursor"
                )
            active_policy = resume_policy or SearchPolicy(policy_id=self._metadata["policy_id"])
            if active_policy.policy_id != self._metadata["policy_id"]:
                raise ValueError("resume policy does not match the recorder")
            if resume_query_hash != canonical_hash(resume_query):
                raise ValueError("resume query hash does not match the supplied query")
            resume_record = next(
                (item for item in self._queries if item.query_hash == resume_query_hash),
                None,
            )
            if resume_record is None or resume_record.last_cursor != resume_cursor:
                raise ValueError("resume cursor must be the recorded query continuation")
            try:
                page = resume_index.search(
                    resume_query,
                    policy=active_policy,
                    cursor=resume_cursor,
                    broad_query_justification=next(
                        (
                            item.broad_query_justification
                            for item in self._queries
                            if item.query_hash == resume_query_hash
                        ),
                        None,
                    ),
                )
            except ValueError as error:
                raise ValueError("resume cursor failed cryptographic verification") from error
            if (
                page.snapshot_hash != self._metadata["snapshot_hash"]
                or page.policy_id != self._metadata["policy_id"]
                or page.policy_hash != self._metadata["policy_hash"]
            ):
                raise ValueError("resume cursor dependencies do not match the recorder")
        receipt = SearchCoverageReceipt(
            **self._metadata,
            completed_seed_families=completed_seed_families,
            completed_passes=passes,
            executed_queries=tuple(self._queries),
            returned_unit_ids=returned_unit_ids,
            result_dispositions=tuple(self._dispositions.values()),
            latest_complete_round_new_material_candidates=(
                latest_complete_round_new_material_candidates
            ),
            traversal_complete=traversal_complete,
            interrupted=interrupted,
            resume_cursor=resume_cursor,
            resume_query_hash=resume_query_hash,
            resume_snapshot_hash=(
                (resume_snapshot_hash or self._metadata["snapshot_hash"])
                if resume_cursor is not None
                else None
            ),
            resume_policy_id=(
                (resume_policy_id or self._metadata["policy_id"])
                if resume_cursor is not None
                else None
            ),
            broad_query_justifications=broad_query_justifications,
            stopping_reason=stopping_reason,
        )
        proof_payload = receipt.model_dump(mode="json")
        proof_payload["recorder_proof"] = None
        return SearchCoverageReceipt.model_validate(
            receipt.model_dump(mode="json")
            | {"recorder_proof": canonical_hash(proof_payload)}
        )


class CandidateDispositionKind(StrEnum):
    ACCEPTED_SUPPORTING = "accepted_supporting"
    ACCEPTED_CONTRADICTING = "accepted_contradicting"
    ACCEPTED_CONTEXTUAL = "accepted_contextual"
    DUPLICATE = "duplicate"
    WRONG_SCOPE = "wrong_scope"
    IMMATERIAL = "immaterial"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


_ACCEPTED = {
    CandidateDispositionKind.ACCEPTED_SUPPORTING,
    CandidateDispositionKind.ACCEPTED_CONTRADICTING,
    CandidateDispositionKind.ACCEPTED_CONTEXTUAL,
}


class CandidateDisposition(FrozenModel):
    candidate_id: Identifier
    kind: CandidateDispositionKind
    claim_ids: tuple[Identifier, ...] = ()
    basis: str | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> CandidateDisposition:
        if self.kind in _ACCEPTED and not self.claim_ids:
            raise ValueError("accepted candidates require at least one materialized claim")
        if self.kind not in _ACCEPTED and self.claim_ids:
            raise ValueError("only accepted candidates may identify claims")
        if self.kind is CandidateDispositionKind.SUPERSEDED and not self.basis:
            raise ValueError("superseded candidates require a chronology or amendment basis")
        return self


class MaterializedEvidenceClaim(FrozenModel):
    claim_id: Identifier
    canonical_unit: CanonicalEvidenceUnit | None = None
    canonical_unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    page: int = Field(ge=1)
    spatial: tuple[float, float, float, float] | None
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    quoted_text: str = Field(min_length=1)
    quoted_text_hash: ContentHash
    claim_type: Identifier
    verification_status: VerificationStatus

    @model_validator(mode="after")
    def validate_quote_hash(self) -> MaterializedEvidenceClaim:
        if self.canonical_unit is None:
            raise ValueError("canonical unit is required for exact span verification")
        if self.canonical_unit.unit_id != self.canonical_unit_id:
            raise ValueError("claim canonical unit ID does not match its bound unit")
        if self.canonical_unit.source_id != self.source_id:
            raise ValueError("claim source does not match its bound canonical unit")
        if self.canonical_unit.source_artifact_hash != self.source_artifact_hash:
            raise ValueError("claim source artifact does not match its bound unit")
        if self.canonical_unit.parse_id != self.parse_id:
            raise ValueError("claim Parse record does not match its bound unit")
        if self.canonical_unit.page != self.page:
            raise ValueError("claim page does not match its bound canonical unit")
        if self.canonical_unit.spatial != self.spatial:
            raise ValueError("claim spatial provenance does not match its bound unit")
        if self.span_end > len(self.canonical_unit.text):
            raise ValueError("claim span exceeds canonical unit text")
        if self.quoted_text != self.canonical_unit.text[self.span_start : self.span_end]:
            raise ValueError("quoted text must equal the selected canonical span")
        if self.quoted_text_hash != sha256_digest(self.quoted_text.encode()):
            raise ValueError("quoted text hash must bind the deterministic materialized quote")
        if self.span_end <= self.span_start:
            raise ValueError("claim span must have positive extent")
        return self


def materialize_evidence_claim(
    *,
    claim_id: Identifier,
    unit: CanonicalEvidenceUnit,
    span_start: int,
    span_end: int,
    claim_type: Identifier,
    verification_status: VerificationStatus = VerificationStatus.MACHINE_VERIFIED,
) -> MaterializedEvidenceClaim:
    """Materialize an exact quote from canonical text; callers never provide quote text."""
    if span_start < 0 or span_end <= span_start or span_end > len(unit.text):
        raise ValueError("claim span must select a non-empty range within the canonical unit")
    quote = unit.text[span_start:span_end]
    return MaterializedEvidenceClaim(
        claim_id=claim_id,
        canonical_unit=unit,
        canonical_unit_id=unit.unit_id,
        source_id=unit.source_id,
        source_artifact_hash=unit.source_artifact_hash,
        parse_id=unit.parse_id,
        page=unit.page,
        spatial=unit.spatial,
        span_start=span_start,
        span_end=span_end,
        quoted_text=quote,
        quoted_text_hash=sha256_digest(quote.encode()),
        claim_type=claim_type,
        verification_status=verification_status,
    )


class DerivedFactInput(FrozenModel):
    claim_id: Identifier
    role: RiskRatioInputRole
    value: str = Field(min_length=1)


class RiskRatioInputRole(StrEnum):
    EXPERIMENTAL_EVENTS = "experimental_events"
    EXPERIMENTAL_TOTAL = "experimental_total"
    COMPARATOR_EVENTS = "comparator_events"
    COMPARATOR_TOTAL = "comparator_total"


class MaterializedDerivedFact(FrozenModel):
    fact_id: Identifier
    derivation_id: Identifier
    inputs: tuple[DerivedFactInput, ...]
    population: str = Field(min_length=1)
    arms: tuple[str, str]
    analysis_set: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    units: str | None
    numerator: str
    denominator: str
    rounding_places: int = Field(ge=0, le=12)
    value: str
    content_hash: ContentHash


class DerivationDefinition(FrozenModel):
    derivation_id: Identifier
    required_roles: frozenset[RiskRatioInputRole]
    formula: str


_RISK_RATIO = DerivationDefinition(
    derivation_id="derivation:risk-ratio",
    required_roles=frozenset(RiskRatioInputRole),
    formula="(experimental_events / experimental_total) / "
    "(comparator_events / comparator_total)",
)
_DERIVATIONS = {_RISK_RATIO.derivation_id: _RISK_RATIO}


def derive_fact(
    *,
    fact_id: Identifier,
    derivation_id: Identifier,
    inputs: tuple[DerivedFactInput, ...],
    population: str,
    arms: tuple[str, str],
    analysis_set: str,
    outcome: str,
    time_point: str,
    units: str | None,
    rounding_places: int,
) -> MaterializedDerivedFact:
    """Execute one named deterministic derivation from the closed registry."""
    definition = _DERIVATIONS.get(derivation_id)
    if definition is None:
        raise ValueError(f"{derivation_id} is not in the closed registry")
    values: dict[RiskRatioInputRole, Decimal] = {}
    for item in inputs:
        if item.role in values:
            raise ValueError(f"derived-fact input role is duplicated: {item.role}")
        try:
            values[item.role] = Decimal(item.value)
        except InvalidOperation as error:
            raise ValueError(f"derived-fact input is not numeric: {item.role}") from error
    if set(values) != definition.required_roles:
        raise ValueError(
            "risk-ratio inputs must be exactly "
            f"{sorted(role.value for role in definition.required_roles)}"
        )
    if (
        values[RiskRatioInputRole.EXPERIMENTAL_TOTAL] <= 0
        or values[RiskRatioInputRole.COMPARATOR_TOTAL] <= 0
    ):
        raise ValueError("risk-ratio denominators must be positive")
    if not (
        0
        <= values[RiskRatioInputRole.EXPERIMENTAL_EVENTS]
        <= values[RiskRatioInputRole.EXPERIMENTAL_TOTAL]
        and 0
        <= values[RiskRatioInputRole.COMPARATOR_EVENTS]
        <= values[RiskRatioInputRole.COMPARATOR_TOTAL]
    ):
        raise ValueError("event counts must be between zero and their arm totals")
    comparator_risk = (
        values[RiskRatioInputRole.COMPARATOR_EVENTS]
        / values[RiskRatioInputRole.COMPARATOR_TOTAL]
    )
    if comparator_risk == 0:
        raise ValueError("risk ratio is undefined when comparator risk is zero")
    raw = (
        values[RiskRatioInputRole.EXPERIMENTAL_EVENTS]
        / values[RiskRatioInputRole.EXPERIMENTAL_TOTAL]
    ) / comparator_risk
    quantum = Decimal(1).scaleb(-rounding_places)
    value = format(raw.quantize(quantum, rounding=ROUND_HALF_EVEN), f".{rounding_places}f")
    payload = {
        "fact_id": fact_id,
        "derivation_id": derivation_id,
        "inputs": [item.model_dump(mode="json") for item in inputs],
        "population": population,
        "arms": arms,
        "analysis_set": analysis_set,
        "outcome": outcome,
        "time_point": time_point,
        "formula": definition.formula,
        "units": units,
        "numerator": "experimental_events / experimental_total",
        "denominator": "comparator_events / comparator_total",
        "rounding_places": rounding_places,
        "value": value,
    }
    return MaterializedDerivedFact(**payload, content_hash=canonical_hash(payload))


class VisualGate(FrozenModel):
    gate_id: Identifier
    required: bool
    complete: bool


class FrozenEvidenceBundle(FrozenModel):
    result_spec_id: Identifier
    receipt_ids: tuple[Identifier, ...]
    candidate_dispositions: tuple[CandidateDisposition, ...]
    claims: tuple[MaterializedEvidenceClaim, ...]
    derived_facts: tuple[MaterializedDerivedFact, ...]
    visual_item_ids: tuple[Identifier, ...]
    conflicts: tuple[tuple[Identifier, ...], ...]
    policy_ids: tuple[Identifier, ...]
    content_hash: ContentHash


class ConsiderationDisposition(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXTUAL = "contextual"
    DUPLICATE = "duplicate"
    UNRESOLVED = "unresolved"


class ConsideredEvidenceItem(FrozenModel):
    item_id: Identifier
    disposition: ConsiderationDisposition


class EvidenceConsiderationManifest(FrozenModel):
    manifest_id: Identifier
    sq_id: Identifier
    bundle_hash: ContentHash
    items: tuple[ConsideredEvidenceItem, ...]
    content_hash: ContentHash


def freeze_evidence_bundle(
    *,
    result_spec_id: Identifier,
    receipts: tuple[SearchCoverageReceipt, ...],
    candidate_dispositions: tuple[CandidateDisposition, ...],
    claims: tuple[MaterializedEvidenceClaim, ...] = (),
    derived_facts: tuple[MaterializedDerivedFact, ...] = (),
    visual_gates: tuple[VisualGate, ...] = (),
    visual_item_ids: tuple[Identifier, ...] = (),
    conflicts: tuple[tuple[Identifier, ...], ...] = (),
) -> FrozenEvidenceBundle:
    """Freeze only complete, fully dispositioned search and visual work."""
    if not receipts or any(not receipt.is_complete() for receipt in receipts):
        raise ValueError("all mandatory search coverage receipts must be complete")
    if {receipt.result_spec.entity_id for receipt in receipts} != {result_spec_id}:
        raise ValueError("coverage receipts must bind the bundle ResultSpec")
    if len({receipt.source_inventory for receipt in receipts}) != 1:
        raise ValueError("coverage receipts must bind one source-inventory revision")
    if len({receipt.snapshot_hash for receipt in receipts}) != 1:
        raise ValueError("coverage receipts must bind one index snapshot")
    if any(item.kind is CandidateDispositionKind.UNRESOLVED for item in candidate_dispositions):
        raise ValueError("potentially material candidates cannot remain unresolved")
    gate_by_id = {gate.gate_id: gate for gate in visual_gates}
    if len(gate_by_id) != len(visual_gates):
        raise ValueError("visual gate IDs must be unique")
    required_visuals = {
        candidate.candidate_id
        for receipt in receipts
        for candidate in receipt.visual_candidates
        if candidate.required
    }
    if any(
        visual_id not in gate_by_id or not gate_by_id[visual_id].complete
        for visual_id in required_visuals
    ):
        raise ValueError("every required visual candidate needs its completed visual gate")
    if any(gate.required and not gate.complete for gate in visual_gates):
        raise ValueError("every required visual gate must be complete")
    retained_candidates = set().union(
        *(receipt.retained_candidate_ids() for receipt in receipts)
    )
    disposition_ids = {item.candidate_id for item in candidate_dispositions}
    if len(disposition_ids) != len(candidate_dispositions):
        raise ValueError("each Evidence candidate must have exactly one disposition")
    if retained_candidates != disposition_ids:
        raise ValueError("every retained Evidence candidate requires exactly one disposition")
    claim_ids = {claim.claim_id for claim in claims}
    if len(claim_ids) != len(claims):
        raise ValueError("claim IDs must be unique")
    referenced_claims = {
        claim_id for item in candidate_dispositions for claim_id in item.claim_ids
    }
    if referenced_claims != claim_ids:
        raise ValueError("accepted candidate claims and frozen claims must match exactly")
    for conflict in conflicts:
        if len(conflict) < 2 or not set(conflict).issubset(claim_ids):
            raise ValueError("conflicts must preserve at least two frozen claims")
    ordered_receipts = tuple(sorted(receipts, key=lambda item: item.receipt_id))
    ordered_dispositions = tuple(
        sorted(candidate_dispositions, key=lambda item: item.candidate_id)
    )
    ordered_claims = tuple(sorted(claims, key=lambda item: item.claim_id))
    ordered_facts = tuple(sorted(derived_facts, key=lambda item: item.fact_id))
    ordered_visuals = tuple(sorted(visual_item_ids))
    ordered_conflicts = tuple(sorted(tuple(sorted(item)) for item in conflicts))
    policy_ids = tuple(sorted({receipt.policy_id for receipt in ordered_receipts}))
    payload = {
        "result_spec_id": result_spec_id,
        "receipt_ids": [item.receipt_id for item in ordered_receipts],
        "receipt_hashes": [
            canonical_hash(item) for item in ordered_receipts
        ],
        "candidate_dispositions": [
            item.model_dump(mode="json") for item in ordered_dispositions
        ],
        "claims": [item.model_dump(mode="json") for item in ordered_claims],
        "derived_facts": [item.model_dump(mode="json") for item in ordered_facts],
        "visual_item_ids": ordered_visuals,
        "conflicts": ordered_conflicts,
        "policy_ids": policy_ids,
    }
    return FrozenEvidenceBundle(
        result_spec_id=result_spec_id,
        receipt_ids=tuple(item.receipt_id for item in ordered_receipts),
        candidate_dispositions=ordered_dispositions,
        claims=ordered_claims,
        derived_facts=ordered_facts,
        visual_item_ids=ordered_visuals,
        conflicts=ordered_conflicts,
        policy_ids=policy_ids,
        content_hash=canonical_hash(payload),
    )


def build_consideration_manifest(
    *,
    manifest_id: Identifier,
    sq_id: Identifier,
    bundle: FrozenEvidenceBundle,
    items: tuple[ConsideredEvidenceItem, ...],
) -> EvidenceConsiderationManifest:
    """Account for how every frozen item was considered for one SQ answer."""
    required = {
        *(claim.claim_id for claim in bundle.claims),
        *(fact.fact_id for fact in bundle.derived_facts),
        *bundle.visual_item_ids,
    }
    item_ids = [item.item_id for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("consideration-manifest item IDs must be unique")
    if set(item_ids) != required:
        raise ValueError("every frozen evidence item requires one consideration disposition")
    ordered = tuple(sorted(items, key=lambda item: item.item_id))
    payload = {
        "manifest_id": manifest_id,
        "sq_id": sq_id,
        "bundle_hash": bundle.content_hash,
        "items": [item.model_dump(mode="json") for item in ordered],
    }
    return EvidenceConsiderationManifest(
        **payload,
        content_hash=canonical_hash(payload),
    )
