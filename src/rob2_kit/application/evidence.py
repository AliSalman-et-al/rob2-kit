"""Restart-safe navigation and Evidence records for the application boundary."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from rob2_kit.retrieval import (
    RetrievalSnapshot,
    authoritative_sources,
    build_retrieval_snapshot,
)
from rob2_kit.sources import Source, SourceRole, _extract_pages, sha256_bytes
from rob2_kit.storage import read_only_transaction
from rob2_kit.text_projection import (
    TextProjectionIdentity,
    canonical_projection_identity,
    projection_identity,
    unicode61_tokens,
)

from ._state import identity, read_json, write_json
from .contracts import EvidenceReference, RenderReference


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("transcription must contain non-whitespace text")
    return value


NonBlankTranscription = Annotated[str, Field(min_length=1), AfterValidator(_require_nonblank)]


class LexicalMode(StrEnum):
    ALL_TERMS = "all_terms"
    EXACT_PHRASE = "exact_phrase"
    ANY_TERMS = "any_terms"
    PREFIX_TERMS = "prefix_terms"


class SourceAlias(_Closed):
    alias: str
    source_id: str
    role: SourceRole
    origin: Literal["local", "registry"]
    media_type: str
    page_count: int = Field(ge=1)
    sha256: str
    projection_hash: str
    limitations: tuple[str, ...] = ()


class SearchRequest(_Closed):
    kind: Literal["search"]
    query: str = Field(min_length=1)
    mode: LexicalMode
    source_aliases: tuple[str, ...] = ()
    limit: int = Field(default=5, ge=1, le=20)
    cursor: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def source_aliases_are_unique(self) -> SearchRequest:
        if len(self.source_aliases) != len(set(self.source_aliases)):
            raise ValueError("source aliases must be unique")
        return self


class SearchContinuation(_Closed):
    kind: Literal["continuation"]
    cursor: str = Field(min_length=1)


class PageReadRequest(_Closed):
    kind: Literal["page_read"]
    source_alias: str
    page: int = Field(ge=1)


class NormalSelectionRequest(_Closed):
    kind: Literal["normal_selection"]
    hit: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    extent: Literal["match", "sentence", "paragraph", "table_row"]


class ManualSelectionRequest(_Closed):
    kind: Literal["manual_selection"]
    source_alias: str
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def span_is_ordered(self) -> ManualSelectionRequest:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("manual extent must bind the exact Unicode quote")
        return self


class VisualSelectionRequest(_Closed):
    kind: Literal["visual_selection"]
    render: RenderReference
    transcription: NonBlankTranscription


class EvidenceCatalogRequest(_Closed):
    kind: Literal["catalog"]
    basis: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    after: EvidenceReference | None = None

    @model_validator(mode="after")
    def pagination_is_paired(self) -> EvidenceCatalogRequest:
        if (self.basis is None) != (self.after is None):
            raise ValueError("catalog basis and after must be supplied together")
        return self


class EvidenceRetrievalRequest(_Closed):
    trial_id: str
    searches: tuple[SearchRequest, ...] = ()
    continuations: tuple[SearchContinuation, ...] = ()
    page_reads: tuple[PageReadRequest, ...] = ()
    normal_selections: tuple[NormalSelectionRequest, ...] = ()
    manual_selections: tuple[ManualSelectionRequest, ...] = ()
    visual_selections: tuple[VisualSelectionRequest, ...] = ()
    catalog: EvidenceCatalogRequest | None = None

    @model_validator(mode="after")
    def has_work(self) -> EvidenceRetrievalRequest:
        if not any(
            (
                self.searches,
                self.continuations,
                self.page_reads,
                self.normal_selections,
                self.manual_selections,
                self.visual_selections,
                self.catalog,
            )
        ):
            raise ValueError("retrieval request must contain an operation")
        if (
            len(self.searches)
            + len(self.continuations)
            + len(self.page_reads)
            + len(self.normal_selections)
            + len(self.manual_selections)
            + len(self.visual_selections)
            + int(self.catalog is not None)
            > 8
        ):
            raise ValueError("retrieval request may contain at most 8 operations")
        if self.catalog is not None and any(
            (
                self.searches,
                self.continuations,
                self.page_reads,
                self.normal_selections,
                self.manual_selections,
                self.visual_selections,
            )
        ):
            raise ValueError("catalog retrieval is exclusive of other operations")
        return self


class HitSpan(_Closed):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class Hit(_Closed):
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot: str
    source_alias: str
    source_id: str
    page: int = Field(ge=1)
    projection_hash: str
    preview: str
    spans: tuple[HitSpan, ...]
    omitted_match_count: int = Field(default=0, ge=0)
    available_extents: tuple[str, ...] = ("match", "sentence", "paragraph", "table_row")
    next_cursor: str | None = None


class Cursor(_Closed):
    kind: Literal["cursor"] = "cursor"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot: str
    query: str
    mode: LexicalMode
    source_aliases: tuple[str, ...]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=20)
    projection_hashes: tuple[str, ...]


class PageRead(_Closed):
    source_alias: str
    page: int
    text: str


_HASH = r"^sha256:[0-9a-f]{64}$"


class TextEvidenceRecord(_Closed):
    kind: Literal["text"]
    identity: str = Field(pattern=_HASH, strict=True)
    trial_id: str = Field(min_length=1, strict=True)
    snapshot: str = Field(pattern=_HASH, strict=True)
    source_id: str = Field(min_length=1, strict=True)
    source_sha256: str = Field(pattern=_HASH, strict=True)
    projection_hash: str = Field(pattern=_HASH, strict=True)
    page: int = Field(ge=1, strict=True)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    quote: str = Field(min_length=1, strict=True)
    quote_sha256: str = Field(pattern=_HASH, strict=True)

    @model_validator(mode="after")
    def quote_extent_is_exact(self) -> TextEvidenceRecord:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("Evidence extent must bind the exact Unicode quote")
        return self


class VisualEvidenceRecord(_Closed):
    kind: Literal["visual"]
    identity: str = Field(pattern=_HASH, strict=True)
    trial_id: str = Field(min_length=1, strict=True)
    snapshot: str = Field(pattern=_HASH, strict=True)
    source_id: str = Field(min_length=1, strict=True)
    source_sha256: str = Field(pattern=_HASH, strict=True)
    projection_hash: str = Field(pattern=_HASH, strict=True)
    page: int = Field(ge=1, strict=True)
    region: tuple[float, float, float, float] | None = None
    render: RenderReference
    transcription: NonBlankTranscription

    @field_validator("region", mode="before")
    @classmethod
    def normalized_region(cls, value: object):
        if value is None:
            return value
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 4
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
        ):
            raise ValueError("region must contain four finite numbers")
        x0, y0, x1, y1 = (float(item) for item in value)
        import math

        if not all(math.isfinite(item) for item in (x0, y0, x1, y1)) or not (
            0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
        ):
            raise ValueError("region must be normalized and ordered")
        return (x0, y0, x1, y1)


EvidenceRecord: TypeAlias = TextEvidenceRecord | VisualEvidenceRecord
_EVIDENCE_RECORD = TypeAdapter(Annotated[EvidenceRecord, Field(discriminator="kind")])


def parse_evidence_record(value: object) -> EvidenceRecord:
    """Parse the one canonical, closed Evidence union at every trust boundary."""
    return _EVIDENCE_RECORD.validate_python(value)


class TextEvidenceCatalogEntry(_Closed):
    kind: Literal["text"] = "text"
    evidence: EvidenceReference
    source_id: str = Field(min_length=1, strict=True)
    source_alias: str = Field(min_length=1, max_length=16, strict=True)
    page: int = Field(ge=1, strict=True)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    preview: str = Field(min_length=1, max_length=160, strict=True)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def coordinates_are_ordered(self) -> TextEvidenceCatalogEntry:
        if self.end <= self.start:
            raise ValueError("catalog text coordinates must be ordered")
        return self


class VisualEvidenceCatalogEntry(_Closed):
    kind: Literal["visual"] = "visual"
    evidence: EvidenceReference
    source_id: str = Field(min_length=1, strict=True)
    source_alias: str = Field(min_length=1, max_length=16, strict=True)
    page: int = Field(ge=1, strict=True)
    region: tuple[float, float, float, float] | None
    preview: str = Field(min_length=1, max_length=160, strict=True)
    truncated: bool = Field(strict=True)

    @field_validator("region", mode="before")
    @classmethod
    def normalized_region(cls, value: object):
        return VisualEvidenceRecord.normalized_region(value)


EvidenceCatalogEntry = Annotated[
    TextEvidenceCatalogEntry | VisualEvidenceCatalogEntry, Field(discriminator="kind")
]


class EvidenceCatalogSlice(_Closed):
    basis: str = Field(pattern=_HASH, strict=True)
    entries: tuple[EvidenceCatalogEntry, ...] = Field(max_length=32)
    has_more: bool = Field(strict=True)
    next_after: EvidenceReference | None = None

    @model_validator(mode="after")
    def page_is_keyset_ordered(self) -> EvidenceCatalogSlice:
        identities = [entry.evidence.identity for entry in self.entries]
        if identities != sorted(identities) or len(identities) != len(set(identities)):
            raise ValueError("catalog entries must be sorted and unique")
        if self.has_more != (self.next_after is not None):
            raise ValueError("catalog continuation does not match has_more")
        if self.next_after is not None and (
            not identities or self.next_after.identity != identities[-1]
        ):
            raise ValueError("catalog continuation must be the final entry")
        return self


class EvidenceCondition(_Closed):
    code: Literal[
        "no_hits",
        "ambiguous",
        "invalid_cursor",
        "source_out_of_scope",
        "page_out_of_range",
        "visual_render_required",
        "render_unavailable",
        "stale_catalog",
    ]
    detail: str
    next_action: str


class EvidenceRetrievalResponse(_Closed):
    snapshot: str
    hits: tuple[Hit, ...] = ()
    continuations: tuple[Cursor, ...] = ()
    page_reads: tuple[PageRead, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    catalog: EvidenceCatalogSlice | None = None
    conditions: tuple[EvidenceCondition, ...] = ()


def list_sources(workspace: str | Path, trial_id: str) -> tuple[SourceAlias, ...]:
    sources, projections = _source_basis(workspace, trial_id)
    aliases: list[SourceAlias] = []
    for number, (source, projection) in enumerate(zip(sources, projections, strict=True), 1):
        aliases.append(
            SourceAlias(
                alias=f"s{number}",
                source_id=source.id,
                role=source.role.value,
                origin="registry" if source.role.value == "registry" else "local",
                media_type=source.media_type,
                page_count=source.page_count,
                sha256=source.sha256,
                projection_hash=projection.projection_hash,
                limitations=source.extraction_warnings,
            )
        )
    return tuple(aliases)


def source_records(workspace: str | Path, trial_id: str) -> tuple[Source, ...]:
    return _source_basis(workspace, trial_id)[0]


def _source_basis(
    workspace: str | Path, trial_id: str
) -> tuple[tuple[Source, ...], tuple[TextProjectionIdentity, ...]]:
    """Read either the new application capture or the legacy verified basis."""
    captured = read_json(workspace, "captured_batch.json")
    preflight = read_json(workspace, "preflight.json")
    if captured is None or preflight is None:
        sources = authoritative_sources(workspace, trial_id)
        return sources, tuple(
            canonical_projection_identity(workspace, source) for source in sources
        )
    candidate_rows = {
        str(item["identity"]): item
        for item in preflight.get("candidates", ())
        if isinstance(item, dict)
    }
    source_rows = [
        item
        for item in captured.get("sources", ())
        if isinstance(item, dict) and item.get("trial_id") == trial_id
    ]
    built: list[Source] = []
    projections: list[TextProjectionIdentity] = []
    root = Path(workspace).resolve(strict=True)
    captured_identity = str(captured.get("identity", "")).removeprefix("sha256:")
    for row in source_rows:
        candidate = candidate_rows.get(str(row.get("candidate_identity")))
        if candidate is None:
            raise ValueError("application capture references an unknown candidate")
        path = (
            Path(".rob2-kit")
            / "sources-v3"
            / captured_identity
            / trial_id
            / str(row["candidate_identity"])
        )
        data_path = root / path
        if not data_path.is_file() or data_path.is_symlink():
            raise ValueError("application capture bytes are unavailable")
        data = data_path.read_bytes()
        if sha256_bytes(data) != row.get("sha256"):
            raise ValueError("application capture bytes are stale")
        media = str(candidate["media_type"])
        pages = _extract_pages(data, media)
        source = Source(
            id=str(candidate["identity"]),
            trial_id=trial_id,
            role=SourceRole(str(row["role"])),
            label=Path(str(candidate["relative_path"])).name,
            sha256=str(row["sha256"]),
            media_type=media,
            page_count=len(pages),
            extraction_warnings=(),
            captured_path=path.as_posix(),
        )
        built.append(source)
        projections.append(projection_identity(source, pages))
    ordered = tuple(
        sorted(
            zip(built, projections, strict=True),
            key=lambda pair: (
                int(pair[0].role is not SourceRole.MAIN_ARTICLE),
                pair[0].label.casefold(),
                pair[0].id,
            ),
        )
    )
    return tuple(item[0] for item in ordered), tuple(item[1] for item in ordered)


def _context(workspace: str | Path, trial_id: str):
    captured = read_json(workspace, "captured_batch.json")
    if captured is None:
        context = build_retrieval_snapshot(workspace, trial_id)
    else:
        sources, projections = _source_basis(workspace, trial_id)
        pages = {
            source.id: _extract_pages(
                (Path(workspace).resolve(strict=True) / source.captured_path).read_bytes(),
                source.media_type,
            )
            for source in sources
        }
        scope_hash = str(captured.get("identity"))
        snapshot_content = {
            "trial_id": trial_id,
            "scope_kind": "captured_batch",
            "scope_hash": scope_hash,
            "source_ids": tuple(source.id for source in sources),
            "source_hashes": tuple(source.sha256 for source in sources),
            "projection_hashes": tuple(item.projection_hash for item in projections),
            "tokenizer": "unicode61_casefold_no_diacritics_v1",
            "ordering": "authoritative_source_role_label_id_page_v1",
        }
        snapshot = RetrievalSnapshot(
            trial_id=trial_id,
            scope_kind="captured_batch",
            scope_hash=scope_hash,
            source_ids=tuple(source.id for source in sources),
            source_hashes=tuple(source.sha256 for source in sources),
            projection_hashes=tuple(item.projection_hash for item in projections),
            snapshot_hash=identity(snapshot_content),
        )

        class ApplicationContext:
            def __init__(self) -> None:
                self.snapshot = snapshot
                self.sources = sources
                self.pages = pages

        context = ApplicationContext()
    aliases = list_sources(workspace, trial_id)
    by_alias = {alias.alias: source for alias, source in zip(aliases, context.sources, strict=True)}
    return context, aliases, by_alias


def _terms(query: str) -> tuple[str, ...]:
    terms = tuple(item.casefold() for item in re.findall(r"\w+", query, flags=re.UNICODE))
    if not terms:
        raise ValueError("query has no lexical terms")
    return terms


def source_layout_projection(
    text: str, *, casefold: bool = False
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """Collapse PDF layout while retaining coordinates in the original text.

    A hyphen followed by a line break is PDF line-end layout, not source wording.
    Other punctuation and hyphens remain exact.  ``casefold`` is solely for search.
    """
    characters: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(text):
        if text[index] == "-" and index + 1 < len(text) and text[index + 1].isspace():
            whitespace_end = index + 1
            while whitespace_end < len(text) and text[whitespace_end].isspace():
                whitespace_end += 1
            if "\r" in text[index + 1 : whitespace_end] or "\n" in text[index + 1 : whitespace_end]:
                index = whitespace_end
                continue
        if text[index].isspace():
            start = index
            while index < len(text) and text[index].isspace():
                index += 1
            characters.append(" ")
            starts.append(start)
            ends.append(index)
            continue
        value = text[index].casefold() if casefold else text[index]
        characters.extend(value)
        starts.extend([index] * len(value))
        ends.extend([index + 1] * len(value))
        index += 1
    return "".join(characters), tuple(starts), tuple(ends)


def _spans(text: str, query: str, mode: LexicalMode) -> tuple[HitSpan, ...]:
    terms = _terms(query)
    spans: list[HitSpan] = []
    if mode is LexicalMode.EXACT_PHRASE:
        folded, starts, ends = source_layout_projection(text, casefold=True)
        start = 0
        last_original_end = 0
        phrase = " ".join(terms)
        while (found := folded.find(phrase, start)) >= 0:
            end = found + len(phrase)
            original_start = starts[found]
            original_end = ends[end - 1]
            if original_start >= last_original_end:
                spans.append(
                    HitSpan(
                        start=original_start,
                        end=original_end,
                        text=text[original_start:original_end],
                    )
                )
                last_original_end = original_end
            start = end
    else:
        token_matches = unicode61_tokens(text)
        values = {token for _start, _end, token in token_matches}
        for start, end, value in token_matches:
            matched = (
                all(term in values for term in terms) and value in terms
                if mode is LexicalMode.ALL_TERMS
                else any(value.startswith(term) for term in terms)
                if mode is LexicalMode.PREFIX_TERMS
                else any(term == value for term in terms)
            )
            if matched:
                spans.append(HitSpan(start=start, end=end, text=text[start:end]))
    return tuple(spans)


def _search_rows(
    workspace: str | Path,
    context,
    aliases: tuple[SourceAlias, ...],
    by_alias: dict[str, Source],
    search: SearchRequest,
    *,
    offset: int = 0,
) -> tuple[tuple[Hit, ...], Cursor | None]:
    selected = (
        set(search.source_aliases) if search.source_aliases else {alias.alias for alias in aliases}
    )
    invalid = selected - set(by_alias)
    if invalid:
        raise KeyError(",".join(sorted(invalid)))
    rows: list[Hit] = []
    for alias in aliases:
        if alias.alias not in selected:
            continue
        source = by_alias[alias.alias]
        projection_hash = alias.projection_hash
        for page, text in enumerate(context.pages[source.id], 1):
            spans = _spans(text, search.query, search.mode)
            if not spans:
                continue
            hit_identity = identity(
                {
                    "snapshot": context.snapshot.snapshot_hash,
                    "source": source.id,
                    "page": page,
                    "query": search.query,
                    "mode": search.mode.value,
                    "projection": projection_hash,
                }
            )
            hit = Hit(
                identity=hit_identity,
                snapshot=context.snapshot.snapshot_hash,
                source_alias=alias.alias,
                source_id=source.id,
                page=page,
                projection_hash=projection_hash,
                preview=text[:240],
                spans=spans[:8],
                omitted_match_count=max(0, len(spans) - 8),
            )
            write_json(
                workspace,
                f"hit-{hit_identity.removeprefix('sha256:')}.json",
                hit.model_dump(mode="json"),
            )
            rows.append(hit)
    page = tuple(rows[offset : offset + search.limit])
    next_cursor = None
    cursor = None
    if offset + search.limit < len(rows):
        payload = {
            "snapshot": context.snapshot.snapshot_hash,
            "query": search.query,
            "mode": search.mode.value,
            "source_aliases": tuple(alias.alias for alias in aliases if alias.alias in selected),
            "offset": offset + search.limit,
            "limit": search.limit,
            "projection_hashes": context.snapshot.projection_hashes,
        }
        next_cursor = identity(payload)
        cursor = Cursor(
            identity=next_cursor,
            snapshot=context.snapshot.snapshot_hash,
            query=search.query,
            mode=search.mode,
            source_aliases=tuple(alias.alias for alias in aliases if alias.alias in selected),
            offset=offset + search.limit,
            limit=search.limit,
            projection_hashes=context.snapshot.projection_hashes,
        )
        write_json(
            workspace,
            f"cursor-{next_cursor.removeprefix('sha256:')}.json",
            cursor.model_dump(mode="json"),
        )
    if page and next_cursor:
        page = tuple(hit.model_copy(update={"next_cursor": next_cursor}) for hit in page)
    return page, cursor


def retrieve_evidence(
    workspace: str | Path, request: EvidenceRetrievalRequest
) -> EvidenceRetrievalResponse:
    context, aliases, by_alias = _context(workspace, request.trial_id)
    hits: list[Hit] = []
    continuations: list[Cursor] = []
    page_results: list[PageRead] = []
    conditions: list[EvidenceCondition] = []
    if request.catalog is not None:
        try:
            catalog = reusable_evidence_catalog(
                workspace,
                request.trial_id,
                aliases,
                basis=request.catalog.basis,
                after=request.catalog.after,
            )
        except ValueError as error:
            if str(error) != "stale_catalog":
                raise
            return EvidenceRetrievalResponse(
                snapshot=context.snapshot.snapshot_hash,
                conditions=(
                    EvidenceCondition(
                        code="stale_catalog",
                        detail="catalog changed; restart from the first page",
                        next_action="restart_catalog",
                    ),
                ),
            )
        return EvidenceRetrievalResponse(snapshot=context.snapshot.snapshot_hash, catalog=catalog)
    for search in request.searches:
        offset = 0
        if search.cursor is not None:
            raw = read_json(workspace, f"cursor-{search.cursor.removeprefix('sha256:')}.json")
            try:
                cursor = Cursor.model_validate(raw) if raw is not None else None
            except ValueError:
                cursor = None
            if (
                cursor is None
                or cursor.identity != search.cursor
                or cursor.snapshot != context.snapshot.snapshot_hash
                or cursor.projection_hashes != context.snapshot.projection_hashes
                or cursor.query != search.query
                or cursor.mode != search.mode
                or cursor.source_aliases
                != (search.source_aliases or tuple(alias.alias for alias in aliases))
                or cursor.limit != search.limit
            ):
                conditions.append(
                    EvidenceCondition(
                        code="invalid_cursor",
                        detail="search cursor is stale or does not bind this query",
                        next_action="search_again",
                    )
                )
                continue
            offset = cursor.offset
        try:
            rows, cursor = _search_rows(
                workspace, context, aliases, by_alias, search, offset=offset
            )
        except KeyError as error:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope",
                    detail=str(error),
                    next_action="use_list_sources",
                )
            )
            continue
        if not rows:
            conditions.append(
                EvidenceCondition(
                    code="no_hits",
                    detail="the exact lexical query produced no hits",
                    next_action="change_query",
                )
            )
        hits.extend(rows)
        if cursor is not None:
            continuations.append(cursor)
    for continuation in request.continuations:
        raw = read_json(workspace, f"cursor-{continuation.cursor.removeprefix('sha256:')}.json")
        if raw is None:
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="continuation is unavailable",
                    next_action="search_again",
                )
            )
            continue
        try:
            cursor = Cursor.model_validate(raw)
        except ValueError:
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="continuation is corrupt",
                    next_action="search_again",
                )
            )
            continue
        if (
            cursor.identity != continuation.cursor
            or cursor.snapshot != context.snapshot.snapshot_hash
            or cursor.projection_hashes != context.snapshot.projection_hashes
        ):
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="continuation is stale for this verified snapshot",
                    next_action="search_again",
                )
            )
            continue
        try:
            rows, next_cursor = _search_rows(
                workspace,
                context,
                aliases,
                by_alias,
                SearchRequest(
                    kind="search",
                    query=cursor.query,
                    mode=cursor.mode,
                    source_aliases=cursor.source_aliases,
                    limit=cursor.limit,
                ),
                offset=cursor.offset,
            )
        except KeyError as error:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope", detail=str(error), next_action="use_list_sources"
                )
            )
            continue
        hits.extend(rows)
        if next_cursor is not None:
            continuations.append(next_cursor)
    for read in request.page_reads:
        source = by_alias.get(read.source_alias)
        if source is None:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope",
                    detail=read.source_alias,
                    next_action="use_list_sources",
                )
            )
            continue
        pages = context.pages[source.id]
        if read.page > len(pages):
            conditions.append(
                EvidenceCondition(
                    code="page_out_of_range", detail=str(read.page), next_action="read_exact_page"
                )
            )
            continue
        page_results.append(
            PageRead(source_alias=read.source_alias, page=read.page, text=pages[read.page - 1])
        )
    evidence: list[EvidenceReference] = []
    for selection in request.normal_selections:
        raw = read_json(workspace, f"hit-{selection.hit.removeprefix('sha256:')}.json")
        if raw is None:
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="Hit reference is unavailable",
                    next_action="search_again",
                )
            )
            continue
        hit = Hit.model_validate(raw)
        if hit.snapshot != context.snapshot.snapshot_hash:
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="Hit reference is stale",
                    next_action="search_again",
                )
            )
            continue
        source = by_alias.get(hit.source_alias)
        if source is None:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope",
                    detail=hit.source_alias,
                    next_action="use_list_sources",
                )
            )
            continue
        expected_projection = aliases[int(hit.source_alias[1:]) - 1].projection_hash
        if hit.projection_hash != expected_projection or hit.source_id != source.id:
            conditions.append(
                EvidenceCondition(
                    code="invalid_cursor",
                    detail="Hit projection or Source identity is stale",
                    next_action="search_again",
                )
            )
            continue
        if hit.page > len(context.pages[source.id]) or not hit.spans:
            conditions.append(
                EvidenceCondition(
                    code="page_out_of_range"
                    if hit.page > len(context.pages[source.id])
                    else "invalid_cursor",
                    detail="Hit extent is unavailable",
                    next_action="read_exact_page"
                    if hit.page > len(context.pages[source.id])
                    else "search_again",
                )
            )
            continue
        if selection.extent == "match" and len(hit.spans) > 1:
            conditions.append(
                EvidenceCondition(
                    code="ambiguous",
                    detail="Hit contains multiple exact matches",
                    next_action="choose_an_exact_match_or_a_larger_extent",
                )
            )
            continue
        text = context.pages[source.id][hit.page - 1]
        start, end = _extent(text, hit.spans[0], selection.extent)
        evidence.append(
            _mint_text(
                workspace, request.trial_id, source, context, hit.page, start, end, text[start:end]
            )
        )
    for selection in request.manual_selections:
        source = by_alias.get(selection.source_alias)
        if source is None:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope",
                    detail=selection.source_alias,
                    next_action="use_list_sources",
                )
            )
            continue
        pages = context.pages[source.id]
        if selection.page > len(pages):
            conditions.append(
                EvidenceCondition(
                    code="page_out_of_range",
                    detail=str(selection.page),
                    next_action="read_exact_page",
                )
            )
            continue
        text = pages[selection.page - 1]
        if text[selection.start : selection.end] != selection.quote:
            conditions.append(
                EvidenceCondition(
                    code="ambiguous",
                    detail="manual quote does not match frozen text",
                    next_action="choose_exact_span",
                )
            )
            continue
        evidence.append(
            _mint_text(
                workspace,
                request.trial_id,
                source,
                context,
                selection.page,
                selection.start,
                selection.end,
                selection.quote,
            )
        )
    for selection in request.visual_selections:
        try:
            from rob2_kit.rendering import read_render

            rendered, _image = read_render(workspace, selection.render.identity)
        except (OSError, ValueError):
            conditions.append(
                EvidenceCondition(
                    code="render_unavailable",
                    detail="the referenced persistent render is unavailable or corrupt",
                    next_action="render_the_full_page_again",
                )
            )
            continue
        source = next((item for item in context.sources if item.id == rendered.source_id), None)
        if source is None or source.sha256 != rendered.source_hash:
            conditions.append(
                EvidenceCondition(
                    code="source_out_of_scope",
                    detail="render Source is outside the verified Trial inventory",
                    next_action="render_a_scoped_source",
                )
            )
            continue
        projection_hash = context.snapshot.projection_hashes[
            context.snapshot.source_ids.index(source.id)
        ]
        payload = {
            "kind": "visual",
            "trial_id": request.trial_id,
            "snapshot": context.snapshot.snapshot_hash,
            "source_id": source.id,
            "source_sha256": source.sha256,
            "projection_hash": projection_hash,
            "page": rendered.page_number,
            "region": rendered.region,
            "render": selection.render.model_dump(mode="json"),
            "transcription": selection.transcription,
        }
        evidence_identity = identity(payload)
        record = VisualEvidenceRecord(identity=evidence_identity, **payload)
        write_json(
            workspace,
            f"evidence-{evidence_identity.removeprefix('sha256:')}.json",
            record.model_dump(mode="json"),
        )
        evidence.append(EvidenceReference(kind="evidence", identity=evidence_identity))
    return EvidenceRetrievalResponse(
        snapshot=context.snapshot.snapshot_hash,
        hits=tuple(hits),
        continuations=tuple(continuations),
        page_reads=tuple(page_results),
        evidence=tuple(evidence),
        conditions=tuple(conditions),
    )


def _extent(text: str, span: HitSpan, extent: str) -> tuple[int, int]:
    if extent == "match":
        return span.start, span.end
    if extent == "table_row":
        start = text.rfind("\n", 0, span.start) + 1
        end = text.find("\n", span.end)
        return start, len(text) if end < 0 else end
    if extent == "paragraph":
        start = text.rfind("\n\n", 0, span.start) + 2
        end = text.find("\n\n", span.end)
        return start, len(text) if end < 0 else end
    boundaries = ".!?\n"
    start = max((text.rfind(char, 0, span.start) for char in boundaries), default=-1) + 1
    end_candidates = [
        text.find(char, span.end) for char in boundaries if text.find(char, span.end) >= 0
    ]
    return start, (min(end_candidates) + 1 if end_candidates else len(text))


def _mint_text(
    workspace: str | Path,
    trial_id: str,
    source: Source,
    context,
    page: int,
    start: int,
    end: int,
    quote: str,
) -> EvidenceReference:
    record_payload = {
        "kind": "text",
        "trial_id": trial_id,
        "snapshot": context.snapshot.snapshot_hash,
        "source_id": source.id,
        "source_sha256": source.sha256,
        "projection_hash": context.snapshot.projection_hashes[
            context.snapshot.source_ids.index(source.id)
        ],
        "page": page,
        "start": start,
        "end": end,
        "quote": quote,
        "quote_sha256": "sha256:" + hashlib.sha256(quote.encode()).hexdigest(),
    }
    record_identity = identity(record_payload)
    record = TextEvidenceRecord(identity=record_identity, **record_payload)
    write_json(
        workspace,
        f"evidence-{record_identity.removeprefix('sha256:')}.json",
        record.model_dump(mode="json"),
    )
    return EvidenceReference(kind="evidence", identity=record_identity)


def resolve_evidence(workspace: str | Path, reference: EvidenceReference) -> EvidenceRecord:
    raw = read_json(workspace, f"evidence-{reference.identity.removeprefix('sha256:')}.json")
    if raw is None:
        raise ValueError("Evidence is unavailable")
    try:
        record = parse_evidence_record(raw)
    except ValueError as error:
        raise ValueError("Evidence identity is corrupt") from error
    if (
        record.identity != reference.identity
        or identity(record.model_dump(mode="json", exclude={"identity"})) != reference.identity
    ):
        raise ValueError("Evidence identity is corrupt")
    if record.kind == "text":
        sources, projections = _source_basis(workspace, record.trial_id)
        source = next((item for item in sources if item.id == record.source_id), None)
        if source is None or source.sha256 != record.source_sha256:
            raise ValueError("Evidence Source is outside its scope")
        projection = projections[
            next(index for index, item in enumerate(sources) if item.id == source.id)
        ]
        if projection.projection_hash != record.projection_hash:
            raise ValueError("Evidence projection is stale")
        context, _aliases, _by_alias = _context(workspace, record.trial_id)
        if record.snapshot != context.snapshot.snapshot_hash:
            raise ValueError("Evidence scope is stale")
        if (
            record.page is None
            or record.start is None
            or record.end is None
            or record.quote is None
        ):
            raise ValueError("Evidence text coordinates are incomplete")
        if record.page < 1 or record.page > len(context.pages[source.id]):
            raise ValueError("Evidence page coordinate is outside its Source")
        text = context.pages[source.id][record.page - 1]
        if (
            record.start < 0
            or record.end > len(text)
            or record.end <= record.start
            or text[record.start : record.end] != record.quote
            or record.quote_sha256 != "sha256:" + hashlib.sha256(record.quote.encode()).hexdigest()
        ):
            raise ValueError("Evidence quote is corrupt")
    else:
        if record.render is None or not record.transcription:
            raise ValueError("visual Evidence is incomplete")
        from rob2_kit.rendering import read_render

        rendered, _image = read_render(workspace, record.render.identity)
        if (
            rendered.source_id != record.source_id
            or rendered.page_number != record.page
            or rendered.region != record.region
        ):
            raise ValueError("visual Evidence render scope is invalid")
        if rendered.source_hash != record.source_sha256:
            raise ValueError("visual Evidence render source hash is outside its scope")
        sources, projections = _source_basis(workspace, record.trial_id)
        source_index = next(
            (index for index, item in enumerate(sources) if item.id == record.source_id),
            None,
        )
        source = None if source_index is None else sources[source_index]
        if source is None or source.sha256 != record.source_sha256:
            raise ValueError("visual Evidence Source is outside its scope")
        context, _aliases, _by_alias = _context(workspace, record.trial_id)
        if record.snapshot != context.snapshot.snapshot_hash:
            raise ValueError("visual Evidence scope is stale")
        if source_index is None:
            raise ValueError("visual Evidence Source is outside its scope")
        projection = projections[source_index]
        if projection.projection_hash != record.projection_hash:
            raise ValueError("visual Evidence projection is stale")
    return record


def reusable_evidence_catalog(
    workspace: str | Path,
    trial_id: str,
    aliases: tuple[SourceAlias, ...],
    *,
    basis: str | None = None,
    after: EvidenceReference | None = None,
) -> EvidenceCatalogSlice:
    """Return one fixed, content-addressed keyset page of reusable Evidence."""
    with read_only_transaction(workspace) as connection:
        rows = (
            ()
            if connection is None
            else connection.execute(
                "SELECT name FROM records WHERE name LIKE 'application:evidence-%.json'"
            ).fetchall()
        )
    by_source = {alias.source_id: alias.alias for alias in aliases}
    records: list[tuple[EvidenceReference, EvidenceRecord, str]] = []
    for (name,) in rows:
        record_name = str(name).removeprefix("application:")
        token = record_name.removeprefix("evidence-").removesuffix(".json")
        reference = EvidenceReference(kind="evidence", identity=f"sha256:{token}")
        record = resolve_evidence(workspace, reference)
        if record.trial_id != trial_id:
            continue
        source_alias = by_source.get(record.source_id or "")
        if source_alias is None or record.page is None:
            raise ValueError("retained Evidence Source is outside the Trial scope")
        records.append((reference, record, source_alias))
    records.sort(key=lambda row: row[0].identity)
    computed_basis = identity(
        {
            "trial_id": trial_id,
            "snapshot": _context(workspace, trial_id)[0].snapshot.snapshot_hash,
            "sources": [
                (alias.source_id, alias.sha256, alias.projection_hash) for alias in aliases
            ],
            "evidence": [reference.identity for reference, _record, _alias in records],
        }
    )
    if basis is not None and basis != computed_basis:
        raise ValueError("stale_catalog")
    start_index = 0
    if after is not None:
        identities = [reference.identity for reference, _record, _alias in records]
        if after.identity not in identities:
            raise ValueError("stale_catalog")
        start_index = identities.index(after.identity) + 1
    page = records[start_index : start_index + 32]
    entries: list[EvidenceCatalogEntry] = []
    for reference, record, source_alias in page:
        if isinstance(record, TextEvidenceRecord):
            content = record.quote
            entries.append(
                TextEvidenceCatalogEntry(
                    evidence=reference,
                    source_id=record.source_id,
                    source_alias=source_alias,
                    page=record.page,
                    start=record.start,
                    end=record.end,
                    preview=content[:160],
                    truncated=len(content) > 160,
                )
            )
        else:
            content = record.transcription
            entries.append(
                VisualEvidenceCatalogEntry(
                    evidence=reference,
                    source_id=record.source_id,
                    source_alias=source_alias,
                    page=record.page,
                    region=record.region,
                    preview=content[:160],
                    truncated=len(content) > 160,
                )
            )
    has_more = start_index + len(page) < len(records)
    return EvidenceCatalogSlice(
        basis=computed_basis,
        entries=tuple(entries),
        has_more=has_more,
        next_after=entries[-1].evidence if has_more else None,
    )
