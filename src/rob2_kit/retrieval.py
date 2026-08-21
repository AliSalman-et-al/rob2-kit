"""Snapshot-bound, read-only Evidence retrieval.

This module is deliberately an in-process seam.  A retrieval batch verifies one
Source/projection basis, evaluates independent operations against that basis,
and never writes search history or scientific state.  Evidence handles are
content-addressed locators; resolving one rechecks the current verified basis.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import Field, model_validator

from rob2_kit.ingestion.service import local_sources, registry_source
from rob2_kit.judgment_models import TextEvidenceRef, VisualEvidenceRef, VisualOrigin
from rob2_kit.models import StrictModel, canonical_json_bytes, sha256
from rob2_kit.rendering import RenderCondition, RenderedPage, render_page
from rob2_kit.sources import Source, list_sources
from rob2_kit.telemetry import (
    NO_OP_EVENT_SINK,
    DurationOperation,
    EventSinkLike,
    RetrievalEvent,
    RetrievalOperation,
    RetrievalOutcome,
    emit_event,
    measured_duration,
)
from rob2_kit.text_projection import (
    FTS_TOKENIZER_ID,
    TextProjectionIdentity,
    VerifiedProjection,
    canonical_projection_identity,
    search_fts_pages,
    unicode61_tokens,
)


class LexicalMode(StrEnum):
    ALL_TERMS = "all_terms"
    EXACT_PHRASE = "exact_phrase"
    ANY_TERMS = "any_terms"
    PREFIX_TERMS = "prefix_terms"


class RetrievalKind(StrEnum):
    SEARCH = "search"
    PAGE = "page"
    WINDOW = "window"
    TEXT_SPAN = "text_span"
    TEXT_QUOTE = "text_quote"
    VISUAL_REGION = "visual_region"


class RetrievalConditionCode(StrEnum):
    INVALID_QUERY = "invalid_query"
    NO_HITS = "no_hits"
    PAGE_OUT_OF_RANGE = "page_out_of_range"
    WINDOW_OUT_OF_RANGE = "window_out_of_range"
    TEXT_MISMATCH = "text_mismatch"
    AMBIGUOUS_QUOTE = "ambiguous_quote"
    VISUAL_UNSUPPORTED = "visual_unsupported"
    REGION_INVALID = "region_invalid"
    VISUAL_MISMATCH = "visual_mismatch"
    CURSOR_INVALID = "cursor_invalid"
    SOURCE_OUT_OF_SCOPE = "source_out_of_scope"


class RetrievalAction(StrEnum):
    CHANGE_QUERY = "change_query"
    READ_EXACT_PAGE = "read_exact_page"
    CHOOSE_EXACT_SPAN = "choose_exact_span"
    CHOOSE_EXACT_REGION = "choose_exact_region"
    USE_SUPPORTED_SOURCE = "use_supported_source"
    RETRY = "retry"


class RetrievalModel(StrictModel):
    """Strict base for transport-only retrieval payloads."""


class SearchOperation(RetrievalModel):
    kind: Literal["search"] = "search"
    caller_id: Annotated[str, Field(min_length=1)]
    query: Annotated[str, Field(min_length=1)]
    mode: LexicalMode
    source_ids: tuple[str, ...] = ()
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None

    @model_validator(mode="after")
    def unique_sources(self) -> SearchOperation:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("search Source IDs must be unique")
        return self


class PageOperation(RetrievalModel):
    kind: Literal["page"] = "page"
    caller_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    page_number: int = Field(ge=1)


class WindowOperation(RetrievalModel):
    kind: Literal["window"] = "window"
    caller_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    page_number: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> WindowOperation:
        if self.end < self.start:
            raise ValueError("window end must not precede start")
        return self


class TextSpanSelection(RetrievalModel):
    kind: Literal["text_span"] = "text_span"
    caller_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    page_number: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def ordered(self) -> TextSpanSelection:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("text span coordinates must bind the quote")
        return self


class TextQuoteSelection(RetrievalModel):
    kind: Literal["text_quote"] = "text_quote"
    caller_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    page_number: int | None = Field(default=None, ge=1)
    quote: Annotated[str, Field(min_length=1)]


class VisualRegionSelection(RetrievalModel):
    kind: Literal["visual_region"] = "visual_region"
    caller_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    page_number: int = Field(ge=1)
    region: tuple[float, float, float, float]
    transcription: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def valid_region(self) -> VisualRegionSelection:
        if (
            any(not 0 <= value <= 1 for value in self.region)
            or self.region[0] >= self.region[2]
            or self.region[1] >= self.region[3]
        ):
            raise ValueError("region must be a nonempty normalized rectangle")
        return self


RetrievalOperationInput: TypeAlias = Annotated[
    SearchOperation
    | PageOperation
    | WindowOperation
    | TextSpanSelection
    | TextQuoteSelection
    | VisualRegionSelection,
    Field(discriminator="kind"),
]


class EvidenceRetrievalBatch(RetrievalModel):
    trial_id: Annotated[str, Field(min_length=1)]
    operations: tuple[RetrievalOperationInput, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_callers(self) -> EvidenceRetrievalBatch:
        callers = tuple(operation.caller_id for operation in self.operations)
        if len(callers) != len(set(callers)):
            raise ValueError("retrieval caller IDs must be unique")
        return self


class RetrievalSnapshot(RetrievalModel):
    schema_id: Literal["rob2.retrieval_snapshot"] = "rob2.retrieval_snapshot"
    schema_version: Literal[1] = 1
    trial_id: str
    scope_kind: Literal["captured_batch", "approved_batch"]
    scope_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    source_ids: tuple[str, ...] = Field(min_length=1)
    source_hashes: tuple[str, ...] = Field(min_length=1)
    projection_hashes: tuple[str, ...] = Field(min_length=1)
    tokenizer: Literal["unicode61_casefold_no_diacritics_v1"] = (
        "unicode61_casefold_no_diacritics_v1"
    )
    ordering: Literal["authoritative_source_role_label_id_page_v1"] = (
        "authoritative_source_role_label_id_page_v1"
    )
    snapshot_hash: str


class SearchSpan(RetrievalModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class SearchHit(RetrievalModel):
    source_id: str
    source_hash: str
    page_number: int = Field(ge=1)
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    match_spans: tuple[SearchSpan, ...]
    omitted_match_count: int = Field(default=0, ge=0)
    source_match_count: int = Field(ge=1)


class SearchResult(RetrievalModel):
    kind: Literal["search"] = "search"
    hits: tuple[SearchHit, ...]
    next_cursor: str | None = None
    normalized_terms: tuple[str, ...]
    total_match_pages: int = Field(ge=0)


class PageResult(RetrievalModel):
    kind: Literal["page"] = "page"
    source_id: str
    source_hash: str
    page_number: int = Field(ge=1)
    text: str
    start: Literal[0] = 0
    end: int = Field(ge=0)


class WindowResult(RetrievalModel):
    kind: Literal["window"] = "window"
    source_id: str
    source_hash: str
    page_number: int = Field(ge=1)
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class EvidenceHandle(RetrievalModel):
    """Opaque, immutable locator minted only after deliberate selection."""

    token: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    scope_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    source_id: str
    source_sha256: str
    kind: Literal["text", "visual"]
    page_number: int = Field(ge=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    quote_sha256: str | None = None
    region: tuple[float, float, float, float] | None = None
    image_sha256: str | None = None
    transcription: str | None = None

    @property
    def handle_id(self) -> str:
        return self.token


class TextSelectionResult(RetrievalModel):
    kind: Literal["text_selection"] = "text_selection"
    handle: EvidenceHandle


class VisualSelectionResult(RetrievalModel):
    kind: Literal["visual_selection"] = "visual_selection"
    handle: EvidenceHandle
    image_sha256: str


class SelectionCandidate(RetrievalModel):
    source_id: str
    page_number: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class RetrievalCondition(RetrievalModel):
    code: RetrievalConditionCode
    action: RetrievalAction
    normalized_terms: tuple[str, ...] = ()
    candidate_count: int = Field(default=0, ge=0)
    candidates: tuple[SelectionCandidate, ...] = ()


RetrievalPayload: TypeAlias = Annotated[
    SearchResult | PageResult | WindowResult | TextSelectionResult | VisualSelectionResult,
    Field(discriminator="kind"),
]


class RetrievalOperationResult(RetrievalModel):
    caller_id: str
    status: Literal["succeeded", "condition"]
    result: RetrievalPayload | None = None
    condition: RetrievalCondition | None = None

    @model_validator(mode="after")
    def one_outcome(self) -> RetrievalOperationResult:
        if (self.result is None) == (self.condition is None):
            raise ValueError("retrieval operation must have exactly one outcome")
        if self.status == "succeeded" and self.result is None:
            raise ValueError("successful retrieval requires a result")
        if self.status == "condition" and self.condition is None:
            raise ValueError("conditional retrieval requires a condition")
        return self


class RetrievalBatchResult(RetrievalModel):
    status: Literal["succeeded"] = "succeeded"
    snapshot: RetrievalSnapshot
    operations: tuple[RetrievalOperationResult, ...]


class RetrievalBatchCondition(RetrievalModel):
    status: Literal["condition"] = "condition"
    code: Literal["basis_unavailable"] = "basis_unavailable"
    detail: str


class RetrievalBasisError(ValueError):
    """The shared immutable retrieval basis could not be verified."""


@dataclass(frozen=True)
class VerifiedRetrievalContext:
    workspace: Path
    snapshot: RetrievalSnapshot
    sources: tuple[Source, ...]
    pages: dict[str, tuple[str, ...]]
    projection: VerifiedProjection


_PREVIEW_LIMIT = 240
_HANDLE_CACHE: dict[str, EvidenceHandle] = {}


def handle_from_id(handle_id: str) -> EvidenceHandle:
    """Legacy v0.2 handle lookup retained for superseded packet paths."""

    try:
        return _HANDLE_CACHE[handle_id]
    except KeyError as error:
        raise ValueError("Evidence handle is unavailable or expired") from error
def authoritative_sources(workspace: str | Path, trial_id: str) -> tuple[Source, ...]:
    local = local_sources(workspace, trial_id)
    registry = registry_source(workspace, trial_id)
    return list_sources(local + (() if registry is None else (registry,)))


def _retrieval_scope(workspace: str | Path) -> tuple[str, str]:
    from rob2_kit.batch import (
        ApprovedBatch,
        frozen_batch_hash,
        read_proposal_version,
    )
    from rob2_kit.ingestion.service import read_captured_batch
    from rob2_kit.storage import read_only_transaction

    approved: ApprovedBatch | None = None
    with read_only_transaction(workspace) as connection:
        if connection is not None:
            row = connection.execute(
                "SELECT payload FROM records WHERE name='active_batch'"
            ).fetchone()
            if row is not None:
                try:
                    approved = ApprovedBatch.model_validate_json(bytes(row[0]))
                except ValueError as error:
                    raise RetrievalBasisError(
                        "active Batch scope is unsupported or corrupt"
                    ) from error
                if approved.frozen_hash != frozen_batch_hash(
                    approved.proposal, approved.pack_identities
                ):
                    raise RetrievalBasisError("Approved Batch scope identity is corrupt")
                detail = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"detail:batch:{approved.frozen_hash}",),
                ).fetchone()
                if detail is None or bytes(detail[0]) != bytes(row[0]):
                    raise RetrievalBasisError(
                        "active Approved Batch differs from its immutable Detail"
                    )
    if approved is not None:
        try:
            version = read_proposal_version(workspace)
            captured = read_captured_batch(workspace)
        except (OSError, ValueError) as error:
            raise RetrievalBasisError("Approved Batch parent basis is corrupt") from error
        if (
            version is None
            or captured is None
            or version.proposal != approved.proposal
            or version.proposal_hash != sha256(approved.proposal)
            or version.captured_batch_hash != captured.content_hash
        ):
            raise RetrievalBasisError("Approved Batch parent basis is corrupt")
        return "approved_batch", approved.frozen_hash
    captured = read_captured_batch(workspace)
    if captured is None:
        raise RetrievalBasisError("Captured Batch scope is unavailable")
    return "captured_batch", captured.content_hash


def build_retrieval_snapshot(
    workspace: str | Path,
    trial_id: str,
    sources: tuple[Source, ...] | None = None,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
    projection: VerifiedProjection | None = None,
) -> VerifiedRetrievalContext:
    """Verify one authoritative Source/projection basis for a retrieval batch."""

    try:
        authoritative = authoritative_sources(workspace, trial_id)
    except (OSError, ValueError) as error:
        raise RetrievalBasisError("authoritative Source basis is unavailable") from error
    scope_kind, scope_hash = _retrieval_scope(workspace)
    source_inventory = authoritative if sources is None else list_sources(sources)
    if source_inventory != authoritative:
        raise RetrievalBasisError("Source inventory does not match authoritative state")
    if not source_inventory or any(source.trial_id != trial_id for source in source_inventory):
        raise RetrievalBasisError("authoritative Source inventory is unavailable")
    if len({source.id for source in source_inventory}) != len(source_inventory):
        raise RetrievalBasisError("authoritative Source inventory is not unique")
    projection = projection or VerifiedProjection(workspace, event_sink=event_sink)
    identities: list[TextProjectionIdentity] = []
    pages: dict[str, tuple[str, ...]] = {}
    try:
        for source in source_inventory:
            identity = canonical_projection_identity(workspace, source)
            pages[source.id] = projection.pages(source, identity)
            identities.append(identity)
    except RetrievalBasisError:
        raise
    except (OSError, ValueError) as error:
        raise RetrievalBasisError("retrieval Source basis is stale or corrupt") from error
    snapshot_content = {
        "trial_id": trial_id,
        "scope_kind": scope_kind,
        "scope_hash": scope_hash,
        "source_ids": tuple(source.id for source in source_inventory),
        "source_hashes": tuple(source.sha256 for source in source_inventory),
        "projection_hashes": tuple(identity.projection_hash for identity in identities),
        "tokenizer": FTS_TOKENIZER_ID,
        "ordering": "authoritative_source_role_label_id_page_v1",
    }
    snapshot = RetrievalSnapshot(
        trial_id=trial_id,
        scope_kind=cast(Any, scope_kind),
        scope_hash=scope_hash,
        source_ids=tuple(source.id for source in source_inventory),
        source_hashes=tuple(source.sha256 for source in source_inventory),
        projection_hashes=tuple(identity.projection_hash for identity in identities),
        snapshot_hash=sha256(snapshot_content),
    )
    return VerifiedRetrievalContext(Path(workspace), snapshot, source_inventory, pages, projection)


def retrieval_snapshot(
    workspace: str | Path,
    trial_id: str,
    sources: tuple[Source, ...] | None = None,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> RetrievalSnapshot:
    """Return only the immutable snapshot identity for a verified basis."""

    return build_retrieval_snapshot(workspace, trial_id, sources, event_sink=event_sink).snapshot


def retrieve_batch(
    workspace: str | Path,
    batch: EvidenceRetrievalBatch,
    sources: tuple[Source, ...] | None = None,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> RetrievalBatchResult:
    """Evaluate independent operations against one verified retrieval snapshot."""

    with measured_duration(event_sink, DurationOperation.RETRIEVAL):
        staged_events: list[object] = []
        staged_sink = staged_events.append
        handles_before = set(_HANDLE_CACHE)
        try:
            context = build_retrieval_snapshot(
                workspace, batch.trial_id, sources, event_sink=event_sink
            )
            snapshot = context.snapshot
            by_id = {source.id: source for source in context.sources}
            results = tuple(
                _operation(
                    workspace,
                    batch.trial_id,
                    operation,
                    snapshot,
                    context.projection,
                    by_id,
                    context.pages,
                    staged_sink,
                )
                for operation in batch.operations
            )
        except RetrievalBasisError as error:
            for handle_id in set(_HANDLE_CACHE) - handles_before:
                del _HANDLE_CACHE[handle_id]
            return cast(RetrievalBatchResult, RetrievalBatchCondition(detail=str(error)))
        for event in staged_events:
            emit_event(event_sink, cast(Any, event))
        return RetrievalBatchResult(snapshot=snapshot, operations=results)


def resolve_evidence_handle(
    context: VerifiedRetrievalContext,
    handle: EvidenceHandle,
) -> TextEvidenceRef | VisualEvidenceRef:
    """Resolve and revalidate a handle against the exact snapshot scope."""

    snapshot = context.snapshot
    if handle.scope_hash != snapshot.snapshot_hash:
        raise ValueError("Evidence handle scope is stale or mismatched")
    source = next((item for item in context.sources if item.id == handle.source_id), None)
    if source is None or source.sha256 != handle.source_sha256:
        raise ValueError("Evidence handle Source is outside its scope")
    if handle.kind == "text":
        if handle.start is None or handle.end is None or handle.quote_sha256 is None:
            raise ValueError("text Evidence handle is incomplete")
        page = context.pages[source.id][handle.page_number - 1]
        quote = page[handle.start : handle.end]
        if sha256(quote) != handle.quote_sha256 or not quote:
            raise ValueError("Evidence handle text no longer matches its Source")
        expected_token = sha256(
            {
                "scope_hash": snapshot.snapshot_hash,
                "source_id": source.id,
                "source_sha256": source.sha256,
                "kind": "text",
                "page_number": handle.page_number,
                "start": handle.start,
                "end": handle.end,
                "quote_sha256": handle.quote_sha256,
            }
        )
        if handle.token != expected_token:
            raise ValueError("Evidence handle integrity check failed")
        return TextEvidenceRef(
            source_id=source.id,
            source_sha256=source.sha256,
            page_number=handle.page_number,
            start=handle.start,
            end=handle.end,
            quote=quote,
        )
    if handle.region is None or handle.image_sha256 is None:
        raise ValueError("visual Evidence handle is incomplete")
    if not handle.transcription:
        raise ValueError("visual Evidence handle transcription is incomplete")
    rendered = render_page(context.workspace, source, handle.page_number, handle.region)
    if not isinstance(rendered, RenderedPage) or rendered.sha256 != handle.image_sha256:
        raise ValueError("Evidence handle render no longer matches its Source")
    expected_token = sha256(
        {
            "scope_hash": snapshot.snapshot_hash,
            "source_id": source.id,
            "source_sha256": source.sha256,
            "kind": "visual",
            "page_number": handle.page_number,
            "region": handle.region,
            "image_sha256": handle.image_sha256,
            "transcription": handle.transcription,
        }
    )
    if handle.token != expected_token:
        raise ValueError("Evidence handle integrity check failed")
    return VisualEvidenceRef(
        source_id=source.id,
        source_sha256=source.sha256,
        page_number=handle.page_number,
        origin=VisualOrigin.RENDERED_REGION,
        region=handle.region,
        image_sha256=rendered.sha256,
        transcription=handle.transcription,
    )


def _operation(
    workspace: str | Path,
    trial_id: str,
    operation: RetrievalOperationInput,
    snapshot: RetrievalSnapshot,
    projection: VerifiedProjection,
    sources: dict[str, Source],
    pages: dict[str, tuple[str, ...]],
    event_sink: EventSinkLike,
) -> RetrievalOperationResult:
    try:
        if isinstance(operation, SearchOperation):
            result = _search(workspace, operation, snapshot, sources)
            outcome = RetrievalOutcome.SUCCEEDED if result.hits else RetrievalOutcome.CONDITION
            emit_event(
                event_sink,
                RetrievalEvent(
                    operation=RetrievalOperation.SEARCH,
                    outcome=outcome,
                    operation_count=1,
                    result_count=len(result.hits),
                ),
            )
            if not result.hits:
                return RetrievalOperationResult(
                    caller_id=operation.caller_id,
                    status="condition",
                    condition=RetrievalCondition(
                        code=RetrievalConditionCode.NO_HITS,
                        action=RetrievalAction.CHANGE_QUERY,
                        normalized_terms=result.normalized_terms,
                        candidate_count=0,
                    ),
                )
            return RetrievalOperationResult(
                caller_id=operation.caller_id, status="succeeded", result=result
            )
        if isinstance(operation, PageOperation):
            source = _scoped_source(operation.source_id, sources)
            page = _page(pages[source.id], operation.page_number)
            result = PageResult(
                source_id=source.id,
                source_hash=source.sha256,
                page_number=operation.page_number,
                text=page,
                end=len(page),
            )
            return _success(operation.caller_id, result, RetrievalOperation.PAGE_READ, event_sink)
        if isinstance(operation, WindowOperation):
            source = _scoped_source(operation.source_id, sources)
            page = _page(pages[source.id], operation.page_number)
            if operation.start > len(page) or operation.end > len(page):
                return _condition(
                    operation.caller_id,
                    RetrievalConditionCode.WINDOW_OUT_OF_RANGE,
                    RetrievalAction.READ_EXACT_PAGE,
                    event_sink,
                    RetrievalOperation.WINDOW_READ,
                )
            result = WindowResult(
                source_id=source.id,
                source_hash=source.sha256,
                page_number=operation.page_number,
                text=page[operation.start : operation.end],
                start=operation.start,
                end=operation.end,
            )
            return _success(operation.caller_id, result, RetrievalOperation.WINDOW_READ, event_sink)
        if isinstance(operation, (TextSpanSelection, TextQuoteSelection)):
            return _text_selection(operation, snapshot, sources, pages, event_sink)
        return _visual_selection(workspace, operation, snapshot, sources, pages, event_sink)
    except _InvalidQuery:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.INVALID_QUERY,
            RetrievalAction.CHANGE_QUERY,
            event_sink,
            _telemetry_operation(operation),
        )
    except _InvalidCursor:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.CURSOR_INVALID,
            RetrievalAction.RETRY,
            event_sink,
            RetrievalOperation.SEARCH,
        )
    except RetrievalBasisError:
        raise
    except _OutOfScope:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.SOURCE_OUT_OF_SCOPE,
            RetrievalAction.USE_SUPPORTED_SOURCE,
            event_sink,
            _telemetry_operation(operation),
        )
    except IndexError:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.PAGE_OUT_OF_RANGE,
            RetrievalAction.READ_EXACT_PAGE,
            event_sink,
            _telemetry_operation(operation),
        )
    except ValueError:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.TEXT_MISMATCH,
            RetrievalAction.RETRY,
            event_sink,
            _telemetry_operation(operation),
        )
    except Exception as error:
        raise RetrievalBasisError("retrieval operation basis is unavailable") from error


def _search(
    workspace: str | Path,
    operation: SearchOperation,
    snapshot: RetrievalSnapshot,
    sources: dict[str, Source],
) -> SearchResult:
    terms = tuple(token for _, _, token in unicode61_tokens(operation.query))
    if not terms:
        raise _InvalidQuery
    if any(item not in sources for item in operation.source_ids):
        raise _OutOfScope
    selected = (
        tuple(sources[item] for item in operation.source_ids)
        if operation.source_ids
        else tuple(sources.values())
    )
    if any(item.id not in sources for item in selected):
        raise _OutOfScope
    query = _fts_query(operation.mode, terms)
    try:
        rows = tuple(
            (sources[source_id], page_number, text)
            for source_id, page_number, text in search_fts_pages(
                workspace, query, tuple(source.id for source in selected)
            )
        )
    except (OSError, ValueError, KeyError) as error:
        raise RetrievalBasisError("retrieval index basis is unavailable") from error
    source_counts: dict[str, int] = {}
    for source, _, _ in rows:
        source_counts[source.id] = source_counts.get(source.id, 0) + 1
    hits = tuple(
        _search_hit(source, page, text, operation.mode, terms, source_counts[source.id])
        for source, page, text in rows
    )
    total = len(hits)
    offset = operation.offset
    if operation.cursor is not None:
        cursor = _decode_cursor(operation.cursor)
        if cursor.get("snapshot_hash") != snapshot.snapshot_hash or cursor.get(
            "search_hash"
        ) != _search_hash(operation, snapshot):
            raise _InvalidCursor
        raw_offset = cursor.get("offset")
        if not isinstance(raw_offset, int) or raw_offset < 0:
            raise _InvalidCursor
        offset = raw_offset
    visible = hits[offset : offset + operation.limit]
    next_cursor = None
    if offset + len(visible) < total:
        next_cursor = _encode_cursor(
            {
                "snapshot_hash": snapshot.snapshot_hash,
                "search_hash": _search_hash(operation, snapshot),
                "offset": offset + len(visible),
            }
        )
    return SearchResult(
        hits=visible,
        next_cursor=next_cursor,
        normalized_terms=terms,
        total_match_pages=total,
    )


def _search_hit(
    source: Source,
    page_number: int,
    text: str,
    mode: LexicalMode,
    terms: tuple[str, ...],
    source_match_count: int,
) -> SearchHit:
    tokens = unicode61_tokens(text)
    spans: list[tuple[int, int]] = []
    if mode is LexicalMode.EXACT_PHRASE:
        width = len(terms)
        for index in range(len(tokens) - width + 1):
            window = tokens[index : index + width]
            if tuple(token for _, _, token in window) == terms:
                spans.append((window[0][0], window[-1][1]))
    else:
        for start, end, token in tokens:
            if any(
                token.startswith(term) if mode is LexicalMode.PREFIX_TERMS else token == term
                for term in terms
            ):
                spans.append((start, end))
    merged_spans = _merge_spans(spans)
    first = merged_spans[0][0] if merged_spans else 0
    preview_start = max(0, first - 80)
    preview_end = min(len(text), preview_start + _PREVIEW_LIMIT)
    visible = tuple(
        SearchSpan(start=start, end=end, text=text[start:end])
        for start, end in merged_spans
        if start >= preview_start and end <= preview_end
    )
    return SearchHit(
        source_id=source.id,
        source_hash=source.sha256,
        page_number=page_number,
        text=text[preview_start:preview_end],
        start=preview_start,
        end=preview_end,
        match_spans=visible,
        omitted_match_count=len(merged_spans) - len(visible),
        source_match_count=source_match_count,
    )


def _text_selection(
    operation: TextSpanSelection | TextQuoteSelection,
    snapshot: RetrievalSnapshot,
    sources: dict[str, Source],
    pages: dict[str, tuple[str, ...]],
    event_sink: EventSinkLike,
) -> RetrievalOperationResult:
    source = _scoped_source(operation.source_id, sources)
    if operation.page_number is not None:
        if not 1 <= operation.page_number <= len(pages[source.id]):
            return _condition(
                operation.caller_id,
                RetrievalConditionCode.PAGE_OUT_OF_RANGE,
                RetrievalAction.READ_EXACT_PAGE,
                event_sink,
                RetrievalOperation.TEXT_SELECTION,
            )
        candidates = [(operation.page_number, pages[source.id][operation.page_number - 1])]
    else:
        candidates = list(enumerate(pages[source.id], 1))
    if isinstance(operation, TextSpanSelection):
        page = pages[source.id][operation.page_number - 1]
        if page[operation.start : operation.end] != operation.quote:
            return _condition(
                operation.caller_id,
                RetrievalConditionCode.TEXT_MISMATCH,
                RetrievalAction.RETRY,
                event_sink,
                RetrievalOperation.TEXT_SELECTION,
            )
        return _success(
            operation.caller_id,
            TextSelectionResult(
                handle=_make_text_handle(
                    snapshot,
                    source,
                    operation.page_number,
                    operation.start,
                    operation.end,
                    operation.quote,
                )
            ),
            RetrievalOperation.TEXT_SELECTION,
            event_sink,
        )
    found: list[tuple[int, int]] = []
    for number, page in candidates:
        start = page.find(operation.quote)
        while start >= 0:
            found.append((number, start))
            start = page.find(operation.quote, start + 1)
    if not found:
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.TEXT_MISMATCH,
            RetrievalAction.RETRY,
            event_sink,
            RetrievalOperation.TEXT_SELECTION,
        )
    if len(found) != 1:
        candidates = tuple(
            SelectionCandidate(
                source_id=source.id,
                page_number=number,
                start=start,
                end=start + len(operation.quote),
            )
            for number, start in found
        )
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.AMBIGUOUS_QUOTE,
            RetrievalAction.CHOOSE_EXACT_SPAN,
            event_sink,
            RetrievalOperation.TEXT_SELECTION,
            len(found),
            candidates,
        )
    page_number, start = found[0]
    return _success(
        operation.caller_id,
        TextSelectionResult(
            handle=_make_text_handle(
                snapshot, source, page_number, start, start + len(operation.quote), operation.quote
            )
        ),
        RetrievalOperation.TEXT_SELECTION,
        event_sink,
    )


def _visual_selection(
    workspace: str | Path,
    operation: VisualRegionSelection,
    snapshot: RetrievalSnapshot,
    sources: dict[str, Source],
    pages: dict[str, tuple[str, ...]],
    event_sink: EventSinkLike,
) -> RetrievalOperationResult:
    source = _scoped_source(operation.source_id, sources)
    if not 1 <= operation.page_number <= len(pages[source.id]):
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.PAGE_OUT_OF_RANGE,
            RetrievalAction.READ_EXACT_PAGE,
            event_sink,
            RetrievalOperation.VISUAL_SELECTION,
        )
    if (
        any(not 0 <= value <= 1 for value in operation.region)
        or operation.region[0] >= operation.region[2]
        or operation.region[1] >= operation.region[3]
    ):
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.REGION_INVALID,
            RetrievalAction.CHOOSE_EXACT_REGION,
            event_sink,
            RetrievalOperation.VISUAL_SELECTION,
        )
    rendered = render_page(workspace, source, operation.page_number, operation.region)
    if isinstance(rendered, RenderCondition):
        return _condition(
            operation.caller_id,
            RetrievalConditionCode.VISUAL_UNSUPPORTED,
            RetrievalAction.USE_SUPPORTED_SOURCE,
            event_sink,
            RetrievalOperation.VISUAL_SELECTION,
        )
    handle = _make_visual_handle(snapshot, source, operation, rendered.sha256)
    return _success(
        operation.caller_id,
        VisualSelectionResult(handle=handle, image_sha256=rendered.sha256),
        RetrievalOperation.VISUAL_SELECTION,
        event_sink,
    )


def _make_text_handle(
    snapshot: RetrievalSnapshot, source: Source, page: int, start: int, end: int, quote: str
) -> EvidenceHandle:
    content = {
        "scope_hash": snapshot.snapshot_hash,
        "source_id": source.id,
        "source_sha256": source.sha256,
        "kind": "text",
        "page_number": page,
        "start": start,
        "end": end,
        "quote_sha256": sha256(quote),
    }
    handle = EvidenceHandle(
        token=sha256(content),
        scope_hash=snapshot.snapshot_hash,
        source_id=source.id,
        source_sha256=source.sha256,
        kind="text",
        page_number=page,
        start=start,
        end=end,
        quote_sha256=sha256(quote),
    )
    _HANDLE_CACHE[handle.token] = handle
    return handle


def _make_visual_handle(
    snapshot: RetrievalSnapshot, source: Source, operation: VisualRegionSelection, image_hash: str
) -> EvidenceHandle:
    content = {
        "scope_hash": snapshot.snapshot_hash,
        "source_id": source.id,
        "source_sha256": source.sha256,
        "kind": "visual",
        "page_number": operation.page_number,
        "region": operation.region,
        "image_sha256": image_hash,
        "transcription": operation.transcription,
    }
    handle = EvidenceHandle(
        token=sha256(content),
        scope_hash=snapshot.snapshot_hash,
        source_id=source.id,
        source_sha256=source.sha256,
        kind="visual",
        page_number=operation.page_number,
        region=operation.region,
        image_sha256=image_hash,
        transcription=operation.transcription,
    )
    _HANDLE_CACHE[handle.token] = handle
    return handle


def _scoped_source(source_id: str, sources: dict[str, Source]) -> Source:
    try:
        return sources[source_id]
    except KeyError as error:
        raise _OutOfScope from error


def _page(pages: tuple[str, ...], number: int) -> str:
    try:
        return pages[number - 1]
    except IndexError as error:
        raise IndexError from error


def _success(
    caller_id: str, result: RetrievalPayload, operation: RetrievalOperation, sink: EventSinkLike
) -> RetrievalOperationResult:
    emit_event(
        sink,
        RetrievalEvent(
            operation=operation,
            outcome=RetrievalOutcome.SUCCEEDED,
            operation_count=1,
            result_count=1,
        ),
    )
    return RetrievalOperationResult(caller_id=caller_id, status="succeeded", result=result)


def _condition(
    caller_id: str,
    code: RetrievalConditionCode,
    action: RetrievalAction,
    sink: EventSinkLike,
    operation: RetrievalOperation,
    candidate_count: int = 0,
    candidates: tuple[SelectionCandidate, ...] = (),
) -> RetrievalOperationResult:
    emit_event(
        sink,
        RetrievalEvent(
            operation=operation,
            outcome=RetrievalOutcome.CONDITION,
            operation_count=1,
            result_count=0,
        ),
    )
    return RetrievalOperationResult(
        caller_id=caller_id,
        status="condition",
        condition=RetrievalCondition(
            code=code,
            action=action,
            candidate_count=candidate_count,
            candidates=candidates,
        ),
    )


def _telemetry_operation(operation: RetrievalOperationInput) -> RetrievalOperation:
    return {
        "search": RetrievalOperation.SEARCH,
        "page": RetrievalOperation.PAGE_READ,
        "window": RetrievalOperation.WINDOW_READ,
        "text_span": RetrievalOperation.TEXT_SELECTION,
        "text_quote": RetrievalOperation.TEXT_SELECTION,
        "visual_region": RetrievalOperation.VISUAL_SELECTION,
    }[operation.kind]


def _fts_query(mode: LexicalMode, terms: tuple[str, ...]) -> str:
    quoted = tuple('"' + term.replace('"', '""') + '"' for term in terms)
    if mode is LexicalMode.ALL_TERMS:
        return " AND ".join(quoted)
    if mode is LexicalMode.EXACT_PHRASE:
        return '"' + " ".join(terms).replace('"', '""') + '"'
    if mode is LexicalMode.ANY_TERMS:
        return " OR ".join(quoted)
    return " OR ".join(term.replace('"', '""') + "*" for term in terms)


def _merge_spans(spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _search_hash(operation: SearchOperation, snapshot: RetrievalSnapshot) -> str:
    return sha256(
        {
            "snapshot_hash": snapshot.snapshot_hash,
            "query": operation.query,
            "mode": operation.mode,
            "source_ids": operation.source_ids,
            "limit": operation.limit,
        }
    )


def _encode_cursor(value: dict[str, object]) -> str:
    signed = {"payload": value, "digest": sha256(value)}
    return base64.urlsafe_b64encode(canonical_json_bytes(signed)).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, object]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("payload"), dict):
            raise ValueError
        payload = parsed["payload"]
        if parsed.get("digest") != sha256(payload):
            raise ValueError
        return payload
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _InvalidCursor("cursor is invalid") from error


class _OutOfScope(ValueError):
    pass


class _InvalidQuery(ValueError):
    pass


class _InvalidCursor(ValueError):
    pass


__all__ = [
    "EvidenceHandle",
    "EvidenceRetrievalBatch",
    "LexicalMode",
    "PageOperation",
    "PageResult",
    "RetrievalBatchResult",
    "RetrievalBatchCondition",
    "RetrievalCondition",
    "RetrievalConditionCode",
    "RetrievalOperationInput",
    "RetrievalOperationResult",
    "RetrievalSnapshot",
    "SearchHit",
    "SearchOperation",
    "SearchResult",
    "SearchSpan",
    "SelectionCandidate",
    "TextQuoteSelection",
    "TextSelectionResult",
    "TextSpanSelection",
    "VisualRegionSelection",
    "VisualSelectionResult",
    "VerifiedRetrievalContext",
    "WindowOperation",
    "WindowResult",
    "authoritative_sources",
    "build_retrieval_snapshot",
    "resolve_evidence_handle",
    "retrieval_snapshot",
    "retrieve_batch",
]
