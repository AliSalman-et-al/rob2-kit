"""Canonical evidence units and deterministic, snapshot-bound FTS5 search."""

from __future__ import annotations

import base64
import json
import re
import sqlite3
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier

PROJECTION_TARGET = 2_400
_TOKEN = re.compile(r"^[^\s\"'()*:^{}[\]\\]+$")


class CanonicalUnitKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    TABLE_ROW = "table_row"


class CanonicalEvidenceUnit(FrozenModel):
    unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    page: int = Field(ge=1)
    kind: CanonicalUnitKind
    text: str = Field(min_length=1)
    spatial: tuple[float, float, float, float] | None = None


class CanonicalBlock(FrozenModel):
    kind: CanonicalUnitKind
    text: str = Field(min_length=1)
    spatial: tuple[float, float, float, float]


class CanonicalPage(FrozenModel):
    page: int = Field(ge=1)
    blocks: tuple[CanonicalBlock, ...]


def canonicalize_evidence_units(
    *,
    source_id: Identifier,
    source_artifact_hash: ContentHash,
    parse_id: Identifier,
    pages: tuple[CanonicalPage, ...],
) -> tuple[CanonicalEvidenceUnit, ...]:
    """Turn parser-preserved structural blocks into immutable citable units."""
    source_slug = source_id.removeprefix("source:")
    if len({page.page for page in pages}) != len(pages):
        raise ValueError("canonicalization pages must be unique")
    units: list[CanonicalEvidenceUnit] = []
    for page in sorted(pages, key=lambda item: item.page):
        for number, block in enumerate(page.blocks, start=1):
            units.append(
                CanonicalEvidenceUnit(
                    unit_id=f"unit:{source_slug}-p{page.page}-b{number}",
                    source_id=source_id,
                    source_artifact_hash=source_artifact_hash,
                    parse_id=parse_id,
                    page=page.page,
                    kind=block.kind,
                    text=block.text,
                    spatial=block.spatial,
                )
            )
    return tuple(units)


class SearchProjection(FrozenModel):
    projection_id: Identifier
    canonical_unit_id: Identifier
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    citable: bool = False


class SearchQuery(FrozenModel):
    terms: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    any_of: tuple[tuple[str, ...], ...] = ()
    source_ids: tuple[Identifier, ...] = ()
    kinds: tuple[CanonicalUnitKind, ...] = ()
    pages: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_structure(self) -> SearchQuery:
        lexical = (*self.terms, *self.phrases, *self.prefixes)
        lexical += tuple(term for group in self.any_of for term in group)
        if not lexical:
            raise ValueError("structured query requires at least one lexical clause")
        if any(not group for group in self.any_of):
            raise ValueError("structured Boolean groups cannot be empty")
        tokens = (*self.terms, *self.prefixes)
        tokens += tuple(term for group in self.any_of for term in group)
        if any(not _TOKEN.fullmatch(token) for token in tokens):
            raise ValueError("raw FTS syntax is not accepted")
        if any(not phrase.strip() or '"' in phrase for phrase in self.phrases):
            raise ValueError("raw FTS syntax is not accepted")
        if any(page < 1 for page in self.pages):
            raise ValueError("page filters use one-based positive page numbers")
        return self


class SearchPolicy(FrozenModel):
    policy_id: Identifier = "policy:evidence-search-1.0.0"
    page_hit_target: int = Field(default=20, ge=1)
    page_character_target: int = Field(default=8_000, ge=1)
    broad_unique_hit_threshold: int = Field(default=100, ge=1)
    broad_index_fraction: float = Field(default=0.05, gt=0, le=1)


class SearchHit(FrozenModel):
    unit: CanonicalEvidenceUnit
    projection: SearchProjection
    rank: float


class QueryPreview(FrozenModel):
    unique_hit_count: int
    scoped_unit_count: int
    source_distribution: tuple[tuple[Identifier, int], ...]
    requires_broad_query_justification: bool


class SearchPage(FrozenModel):
    snapshot_hash: ContentHash
    query_hash: ContentHash
    policy_id: Identifier
    hits: tuple[SearchHit, ...]
    next_cursor: str | None
    preview: QueryPreview


class EvidenceSearchIndex:
    """Persistent FTS5 index whose cursors are invalid across snapshot changes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_units (
                    unit_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_artifact_hash TEXT NOT NULL,
                    parse_id TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    spatial TEXT
                );
                CREATE TABLE IF NOT EXISTS evidence_snapshot (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    content_hash TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                    projection_id UNINDEXED,
                    unit_id UNINDEXED,
                    text,
                    tokenize='porter unicode61'
                );
                """
            )

    def replace_units(self, units: tuple[CanonicalEvidenceUnit, ...]) -> ContentHash:
        ordered = tuple(sorted(units, key=lambda item: item.unit_id))
        if len({item.unit_id for item in ordered}) != len(ordered):
            raise ValueError("canonical unit IDs must be unique")
        snapshot = canonical_hash([item.model_dump(mode="json") for item in ordered])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM evidence_fts")
            connection.execute("DELETE FROM evidence_units")
            for item in ordered:
                connection.execute(
                    "INSERT INTO evidence_units VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.unit_id,
                        item.source_id,
                        item.source_artifact_hash,
                        item.parse_id,
                        item.page,
                        item.kind.value,
                        item.text,
                        json.dumps(item.spatial),
                    ),
                )
                for projection in _project(item):
                    connection.execute(
                        "INSERT INTO evidence_fts(projection_id, unit_id, text) VALUES (?, ?, ?)",
                        (projection.projection_id, item.unit_id, projection.text),
                    )
            connection.execute(
                """
                INSERT INTO evidence_snapshot(singleton, content_hash) VALUES (1, ?)
                ON CONFLICT(singleton) DO UPDATE SET content_hash = excluded.content_hash
                """,
                (snapshot,),
            )
        return snapshot

    def preview(self, query: SearchQuery, *, policy: SearchPolicy | None = None) -> QueryPreview:
        policy = policy or SearchPolicy()
        rows, scoped_count = self._matches(query)
        sources: dict[str, set[str]] = {}
        for row in rows:
            sources.setdefault(row["source_id"], set()).add(row["unit_id"])
        unique_count = len({row["unit_id"] for row in rows})
        return QueryPreview(
            unique_hit_count=unique_count,
            scoped_unit_count=scoped_count,
            source_distribution=tuple(
                (source, len(unit_ids)) for source, unit_ids in sorted(sources.items())
            ),
            requires_broad_query_justification=(
                unique_count > policy.broad_unique_hit_threshold
                and scoped_count > 0
                and unique_count / scoped_count > policy.broad_index_fraction
            ),
        )

    def read_unit(self, unit_id: Identifier) -> CanonicalEvidenceUnit:
        """Read one engine-issued canonical unit without accepting raw source locators."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_units WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
        if row is None:
            raise ValueError("canonical evidence unit identifier was not issued by this index")
        return CanonicalEvidenceUnit(
            unit_id=row["unit_id"],
            source_id=row["source_id"],
            source_artifact_hash=row["source_artifact_hash"],
            parse_id=row["parse_id"],
            page=row["page"],
            kind=row["kind"],
            text=row["text"],
            spatial=None if row["spatial"] == "null" else tuple(json.loads(row["spatial"])),
        )

    def search(
        self,
        query: SearchQuery,
        *,
        policy: SearchPolicy | None = None,
        cursor: str | None = None,
        broad_query_justification: str | None = None,
    ) -> SearchPage:
        policy = policy or SearchPolicy()
        snapshot = self._snapshot()
        query_hash = canonical_hash(query)
        offset = _decode_cursor(cursor, snapshot, query_hash) if cursor else 0
        rows, scoped_count = self._matches(query)
        rows = _best_projection_per_unit(rows)
        is_broad = (
            len(rows) > policy.broad_unique_hit_threshold
            and scoped_count > 0
            and len(rows) / scoped_count > policy.broad_index_fraction
        )
        if is_broad and not broad_query_justification:
            raise ValueError("broad query requires refinement or complete-traversal justification")
        selected: list[sqlite3.Row] = []
        characters = 0
        for row in rows[offset:]:
            length = len(row["projection_text"])
            if selected and (
                len(selected) >= policy.page_hit_target
                or characters + length > policy.page_character_target
            ):
                break
            selected.append(row)
            characters += length
            if len(selected) >= policy.page_hit_target:
                break
        consumed = offset + len(selected)
        next_cursor = (
            _encode_cursor(snapshot, query_hash, consumed) if consumed < len(rows) else None
        )
        hits = tuple(self._hit(row) for row in selected)
        source_counts: dict[str, int] = {}
        for row in rows:
            source_counts[row["source_id"]] = source_counts.get(row["source_id"], 0) + 1
        preview = QueryPreview(
            unique_hit_count=len(rows),
            scoped_unit_count=scoped_count,
            source_distribution=tuple(sorted(source_counts.items())),
            requires_broad_query_justification=is_broad,
        )
        return SearchPage(
            snapshot_hash=snapshot,
            query_hash=query_hash,
            policy_id=policy.policy_id,
            hits=hits,
            next_cursor=next_cursor,
            preview=preview,
        )

    def _matches(self, query: SearchQuery) -> tuple[list[sqlite3.Row], int]:
        match = _compile_match(query)
        filters: list[str] = []
        parameters: list[object] = [match]
        if query.source_ids:
            filters.append(f"u.source_id IN ({','.join('?' for _ in query.source_ids)})")
            parameters.extend(query.source_ids)
        if query.kinds:
            filters.append(f"u.kind IN ({','.join('?' for _ in query.kinds)})")
            parameters.extend(kind.value for kind in query.kinds)
        if query.pages:
            filters.append(f"u.page IN ({','.join('?' for _ in query.pages)})")
            parameters.extend(query.pages)
        where = " AND " + " AND ".join(filters) if filters else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT f.projection_id, f.unit_id, f.text AS projection_text,
                       bm25(evidence_fts) AS score, u.*
                FROM evidence_fts AS f
                JOIN evidence_units AS u ON u.unit_id = f.unit_id
                WHERE evidence_fts MATCH ?{where}
                ORDER BY score ASC, f.unit_id ASC, f.projection_id ASC
                """,
                parameters,
            ).fetchall()
            scoped_count = connection.execute(
                f"SELECT COUNT(*) FROM evidence_units AS u WHERE 1=1{where}",
                parameters[1:],
            ).fetchone()[0]
        return rows, scoped_count

    def _snapshot(self) -> ContentHash:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM evidence_snapshot WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ValueError("evidence index has no snapshot")
        return row[0]

    @staticmethod
    def _hit(row: sqlite3.Row) -> SearchHit:
        spatial = json.loads(row["spatial"]) if row["spatial"] else None
        unit = CanonicalEvidenceUnit(
            unit_id=row["unit_id"],
            source_id=row["source_id"],
            source_artifact_hash=row["source_artifact_hash"],
            parse_id=row["parse_id"],
            page=row["page"],
            kind=row["kind"],
            text=row["text"],
            spatial=tuple(spatial) if spatial else None,
        )
        projection_number = int(row["projection_id"].rsplit("-", 1)[1])
        projections = _project(unit)
        projection = projections[projection_number]
        return SearchHit(unit=unit, projection=projection, rank=row["score"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _compile_match(query: SearchQuery) -> str:
    clauses = [f'"{term}"' for term in query.terms]
    clauses.extend(f'"{phrase.strip()}"' for phrase in query.phrases)
    clauses.extend(f'"{prefix}"*' for prefix in query.prefixes)
    clauses.extend(
        "(" + " OR ".join(f'"{term}"' for term in group) + ")" for group in query.any_of
    )
    return " AND ".join(clauses)


def _project(unit: CanonicalEvidenceUnit) -> tuple[SearchProjection, ...]:
    if len(unit.text) <= PROJECTION_TARGET:
        spans = ((0, len(unit.text)),)
    else:
        spans = _projection_spans(unit.text)
    return tuple(
        SearchProjection(
            projection_id=f"projection:{unit.unit_id.removeprefix('unit:')}-{number}",
            canonical_unit_id=unit.unit_id,
            text=unit.text[start:end],
            start=start,
            end=end,
        )
        for number, (start, end) in enumerate(spans)
    )


def _projection_spans(text: str) -> tuple[tuple[int, int], ...]:
    boundaries = [match.end() for match in re.finditer(r"(?:[.!?](?:\s+|$)|\n+)", text)]
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        target = min(start + PROJECTION_TARGET, len(text))
        candidates = [value for value in boundaries if start < value <= target]
        end = candidates[-1] if candidates else target
        spans.append((start, end))
        if end == len(text):
            break
        sentence_starts = [0, *boundaries]
        candidates = [value for value in sentence_starts if start < value < end]
        start = candidates[-1] if candidates else end
    return tuple(spans)


def _best_projection_per_unit(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    unique: dict[str, sqlite3.Row] = {}
    for row in rows:
        unique.setdefault(row["unit_id"], row)
    return sorted(unique.values(), key=lambda row: (row["score"], row["unit_id"]))


def _encode_cursor(snapshot: str, query_hash: str, offset: int) -> str:
    payload = json.dumps(
        {"snapshot": snapshot, "query": query_hash, "offset": offset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str, snapshot: str, query_hash: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if payload["snapshot"] != snapshot:
            raise ValueError("cursor belongs to a different index snapshot")
        if payload["query"] != query_hash:
            raise ValueError("cursor belongs to a different structured query")
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError
        return offset
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid search cursor") from error
