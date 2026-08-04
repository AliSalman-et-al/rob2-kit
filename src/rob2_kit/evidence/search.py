"""Canonical evidence units and deterministic, snapshot-bound FTS5 search."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier

PROJECTION_TARGET = 2_400
CONTEXT_CHARACTER_TARGET = 16_000
CONTEXT_NEIGHBOR_LIMIT = 6
CONTEXT_UNIT_LIMIT = 6
PAGE_HIT_TARGET_MAX = 20
PAGE_CHARACTER_TARGET_MAX = 8_000
BROAD_UNIQUE_HIT_THRESHOLD_MAX = 100
BROAD_INDEX_FRACTION_MAX = 0.05
_TOKEN = re.compile(r"^[^\s\"'()*:^{}[\]\\]+$")


class CanonicalUnitKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    TABLE_ROW = "table_row"


class DocumentZone(StrEnum):
    """Coarse source zones used for safe evidence retrieval defaults."""

    MAIN = "main"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    BIBLIOGRAPHY = "bibliography"
    CONTENTS = "contents"
    PAGE_FURNITURE = "page_furniture"
    EXTRACTION_ARTIFACT = "extraction_artifact"
    OTHER = "other"


class TrialDiscourseScope(StrEnum):
    """Classification of the Trial discourse in a source-authored unit."""

    ACTIVE = "active"
    OTHER = "other"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"
    NONE = "none"


class ReadContextMode(StrEnum):
    UNIT = "unit"
    NEIGHBORS = "neighbors"
    SECTION = "section"


class CanonicalWordBox(FrozenModel):
    """A parser-retained word and its exact character span in a canonical unit.

    Word boxes are optional because some parsers expose only block geometry.  A
    visual citation may claim phrase-level geometry only when every selected
    character range is covered by these retained spans.
    """

    text: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    spatial: tuple[float, float, float, float]

    @model_validator(mode="after")
    def validate_span(self) -> CanonicalWordBox:
        if self.span_end <= self.span_start:
            raise ValueError("word box span_end must be greater than span_start")
        if len(self.spatial) != 4:
            raise ValueError("word box spatial bounds must contain four coordinates")
        left, top, right, bottom = self.spatial
        if right <= left or bottom <= top:
            raise ValueError("word box spatial bounds must have positive extent")
        return self


class CanonicalEvidenceUnit(FrozenModel):
    unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    page: int = Field(ge=1)
    kind: CanonicalUnitKind
    text: str = Field(min_length=1)
    spatial: tuple[float, float, float, float] | None = None
    word_boxes: tuple[CanonicalWordBox, ...] = ()
    # Optional structure metadata is populated by parsers that can preserve
    # hierarchy and Trial discourse.  Keeping it optional retains compatibility
    # with older parse records while allowing retrieval to fail closed when a
    # Work-token scope requires an explicit identity.
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_ids: tuple[Identifier, ...] = ()
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: str | None = None
    document_zone: DocumentZone | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    discourse_scope: TrialDiscourseScope = TrialDiscourseScope.NONE
    duplicate_group_id: Identifier | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_word_boxes(self) -> CanonicalEvidenceUnit:
        previous_end = -1
        for box in self.word_boxes:
            if box.span_end > len(self.text):
                raise ValueError("word box span exceeds canonical unit text")
            if box.span_start < previous_end:
                raise ValueError("word boxes must be ordered and non-overlapping")
            if box.text != self.text[box.span_start : box.span_end]:
                raise ValueError("word box text must equal its canonical unit span")
            previous_end = box.span_end
        return self


class CanonicalBlock(FrozenModel):
    kind: CanonicalUnitKind
    text: str = Field(min_length=1)
    spatial: tuple[float, float, float, float]
    word_boxes: tuple[CanonicalWordBox, ...] = ()
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: str | None = None
    document_zone: DocumentZone | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    discourse_scope: TrialDiscourseScope = TrialDiscourseScope.NONE
    duplicate_group_id: Identifier | None = None
    warnings: tuple[str, ...] = ()


class CanonicalPage(FrozenModel):
    page: int = Field(ge=1)
    blocks: tuple[CanonicalBlock, ...]


def canonicalize_evidence_units(
    *,
    source_id: Identifier,
    source_artifact_hash: ContentHash,
    parse_id: Identifier,
    pages: tuple[CanonicalPage, ...],
    trial_id: Identifier | None = None,
    result_id: Identifier | None = None,
    domain_id: Identifier | None = None,
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
                    word_boxes=block.word_boxes,
                    trial_id=trial_id,
                    result_id=result_id,
                    domain_id=domain_id,
                    section_path=block.section_path,
                    hierarchy_path=block.hierarchy_path,
                    reading_order=block.reading_order or len(units),
                    source_role=block.source_role,
                    document_zone=block.document_zone,
                    discourse_scope=block.discourse_scope,
                    duplicate_group_id=block.duplicate_group_id,
                    warnings=block.warnings,
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
    projection_version: str = Field(default="1.0.0", min_length=1)

    @model_validator(mode="after")
    def validate_non_citable(self) -> SearchProjection:
        if self.citable:
            raise ValueError("search projections are non-citable")
        if self.end <= self.start:
            raise ValueError("search projection span must have positive extent")
        if len(self.text) != self.end - self.start:
            raise ValueError("search projection text must bind its exact canonical span")
        return self


class SearchQuery(FrozenModel):
    terms: tuple[str, ...] = Field(
        default=(), description="Individual lexical tokens, for example ['allocation']."
    )
    phrases: tuple[str, ...] = Field(
        default=(), description="Exact multi-word phrases, for example ['allocation concealment']."
    )
    prefixes: tuple[str, ...] = Field(
        default=(), description="Token prefixes without wildcard syntax, for example ['random']."
    )
    any_of: tuple[tuple[str, ...], ...] = Field(
        default=(),
        description=(
            "Boolean alternatives as groups of tokens, for example [['sealed'], ['central']]."
        ),
    )
    source_ids: tuple[Identifier, ...] = Field(
        default=(), description="Optional source IDs issued for the current Result."
    )
    kinds: tuple[CanonicalUnitKind, ...] = Field(
        default=(), description="Optional canonical-unit kind filters."
    )
    pages: tuple[int, ...] = Field(
        default=(), description="Optional one-based source page numbers."
    )
    # Safe metadata refinements.  These are values, never executable FTS
    # syntax; active Work-token scope is applied in addition to these filters.
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_id: Identifier | None = None
    trial_ids: tuple[Identifier, ...] = ()
    result_ids: tuple[Identifier, ...] = ()
    domain_ids: tuple[Identifier, ...] = ()
    question_ids: tuple[Identifier, ...] = ()
    source_roles: tuple[str, ...] = ()
    document_zones: tuple[DocumentZone, ...] = ()
    include_uncertain: bool = True
    include_other_trial: bool = False

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
        if any(not role.strip() for role in self.source_roles):
            raise ValueError("source roles cannot be blank")
        return self


class EvidenceScope(FrozenModel):
    """Engine-issued scope applied before lexical ranking."""

    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_id: Identifier | None = None
    source_ids: tuple[Identifier, ...] = ()
    source_roles: tuple[str, ...] = ()
    document_zones: tuple[DocumentZone, ...] = ()
    include_uncertain: bool = False
    include_other_trial: bool = False
    # Structure-aware parsers may not map every authored unit to a signaling
    # Domain.  The engine can explicitly permit those same-Result units while
    # retaining Trial/Result scope; ad-hoc callers remain fail-closed.
    allow_unclassified: bool = False


class SearchPolicy(FrozenModel):
    policy_id: Identifier = "policy:evidence-search-1.0.0"
    page_hit_target: int = Field(default=20, ge=1, le=PAGE_HIT_TARGET_MAX)
    page_character_target: int = Field(
        default=8_000,
        ge=1,
        le=PAGE_CHARACTER_TARGET_MAX,
    )
    broad_unique_hit_threshold: int = Field(
        default=100,
        ge=1,
        le=BROAD_UNIQUE_HIT_THRESHOLD_MAX,
    )
    broad_index_fraction: float = Field(
        default=0.05,
        gt=0,
        le=BROAD_INDEX_FRACTION_MAX,
    )


class SearchHit(FrozenModel):
    unit: CanonicalEvidenceUnit
    projection: SearchProjection
    rank: float
    oversized: bool = False
    preview: str = ""
    match_explanation: str = "lexical match"
    warnings: tuple[str, ...] = ()
    duplicate_group_id: Identifier | None = None


class QueryPreview(FrozenModel):
    unique_hit_count: int
    scoped_unit_count: int
    source_distribution: tuple[tuple[Identifier, int], ...]
    requires_broad_query_justification: bool


class SearchPage(FrozenModel):
    snapshot_hash: ContentHash
    query_hash: ContentHash
    policy_id: Identifier
    policy_hash: ContentHash
    hits: tuple[SearchHit, ...]
    next_cursor: str | None = Field(default=None, min_length=1)
    preview: QueryPreview
    character_count: int = Field(default=0, ge=0)
    oversized_unit_ids: tuple[Identifier, ...] = ()
    condition: Literal["results", "zero_hits", "excluded_only", "truncated"] = "results"
    excluded_count: int = Field(default=0, ge=0)
    estimated_omitted_characters: int = Field(default=0, ge=0)
    next_actions: tuple[str, ...] = ()

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


class EvidenceContext(FrozenModel):
    """A bounded, snapshot-bound view around one intact canonical unit."""

    snapshot_hash: ContentHash
    unit: CanonicalEvidenceUnit
    neighbors: tuple[CanonicalEvidenceUnit, ...] = ()
    character_count: int = Field(ge=0)
    character_target: int = Field(ge=1)
    neighbor_limit: int = Field(ge=0)
    oversized: bool = False
    omitted_neighbor_count: int = Field(ge=0)
    mode: ReadContextMode = ReadContextMode.NEIGHBORS
    section_path: tuple[str, ...] = ()
    continuation_cursor: str | None = None
    warnings: tuple[str, ...] = ()
    visual_inspection_available: bool = False

    @model_validator(mode="after")
    def validate_bounds_and_provenance(self) -> EvidenceContext:
        if self.character_target > CONTEXT_CHARACTER_TARGET:
            raise ValueError(
                f"character_target cannot exceed {CONTEXT_CHARACTER_TARGET} characters"
            )
        if self.neighbor_limit > CONTEXT_UNIT_LIMIT - 1:
            raise ValueError(f"neighbor_limit cannot exceed {CONTEXT_UNIT_LIMIT - 1}")
        if len(self.neighbors) > self.neighbor_limit:
            raise ValueError("context returned more neighbors than its bound")
        if len({item.unit_id for item in self.neighbors}) != len(self.neighbors):
            raise ValueError("context neighbors must be unique")
        if self.unit.unit_id in {item.unit_id for item in self.neighbors}:
            raise ValueError("context neighbors cannot include the target unit")
        provenance = (
            self.unit.source_id,
            self.unit.source_artifact_hash,
            self.unit.parse_id,
        )
        if any(
            (item.source_id, item.source_artifact_hash, item.parse_id) != provenance
            for item in self.neighbors
        ):
            raise ValueError("context neighbors must preserve source and Parse provenance")
        expected_count = sum(len(item.text) for item in self.all_units)
        if self.character_count != expected_count:
            raise ValueError("context character_count must bind the returned canonical units")
        expected_oversized = len(self.unit.text) > self.character_target
        if self.oversized != expected_oversized:
            raise ValueError("context oversized metadata must bind the target character bound")
        if self.oversized and self.neighbors:
            raise ValueError("oversized context views cannot include neighboring units")
        if not self.oversized and self.character_count > self.character_target:
            raise ValueError("bounded context exceeds its character target")
        if self.mode is ReadContextMode.SECTION and self.section_path:
            if any(item.section_path != self.section_path for item in self.neighbors):
                raise ValueError("section context cannot cross hierarchy boundaries")
        return self

    @property
    def all_units(self) -> tuple[CanonicalEvidenceUnit, ...]:
        """Return the target followed by context in deterministic source order."""
        return (self.unit, *self.neighbors)


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
                    spatial TEXT,
                    word_boxes TEXT,
                    trial_id TEXT,
                    result_id TEXT,
                    domain_id TEXT,
                    question_ids TEXT,
                    section_path TEXT,
                    hierarchy_path TEXT,
                    reading_order INTEGER NOT NULL DEFAULT 0,
                    source_role TEXT,
                    document_zone TEXT,
                    discourse_scope TEXT NOT NULL DEFAULT 'none',
                    duplicate_group_id TEXT,
                    warnings TEXT
                );
                CREATE TABLE IF NOT EXISTS evidence_snapshot (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_cursor_secret (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    secret BLOB NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                    projection_id UNINDEXED,
                    unit_id UNINDEXED,
                    text,
                    tokenize='porter unicode61'
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(evidence_units)").fetchall()
            }
            if "word_boxes" not in columns:
                connection.execute("ALTER TABLE evidence_units ADD COLUMN word_boxes TEXT")
            migrations = {
                "trial_id": "TEXT",
                "result_id": "TEXT",
                "domain_id": "TEXT",
                "question_ids": "TEXT",
                "section_path": "TEXT",
                "hierarchy_path": "TEXT",
                "reading_order": "INTEGER NOT NULL DEFAULT 0",
                "source_role": "TEXT",
                "document_zone": "TEXT",
                "discourse_scope": "TEXT NOT NULL DEFAULT 'none'",
                "duplicate_group_id": "TEXT",
                "warnings": "TEXT",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE evidence_units ADD COLUMN {name} {declaration}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO evidence_cursor_secret(singleton, secret) VALUES (1, ?)",
                (secrets.token_bytes(32),),
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
                    "INSERT INTO evidence_units "
                    "(unit_id, source_id, source_artifact_hash, parse_id, page, kind, text, "
                    "spatial, word_boxes, trial_id, result_id, domain_id, question_ids, "
                    "section_path, hierarchy_path, reading_order, source_role, document_zone, "
                    "discourse_scope, duplicate_group_id, warnings) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.unit_id,
                        item.source_id,
                        item.source_artifact_hash,
                        item.parse_id,
                        item.page,
                        item.kind.value,
                        item.text,
                        json.dumps(item.spatial),
                        json.dumps([box.model_dump(mode="json") for box in item.word_boxes]),
                        item.trial_id,
                        item.result_id,
                        item.domain_id,
                        json.dumps(item.question_ids),
                        json.dumps(item.section_path),
                        json.dumps(item.hierarchy_path),
                        item.reading_order,
                        item.source_role,
                        item.document_zone.value if item.document_zone else None,
                        item.discourse_scope.value,
                        item.duplicate_group_id,
                        json.dumps(item.warnings),
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
        rows, scoped_count, _ = self._matches(query)
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

    def read_unit(
        self,
        unit_id: Identifier,
        *,
        scope: EvidenceScope | None = None,
    ) -> CanonicalEvidenceUnit:
        """Read one engine-issued canonical unit without accepting raw source locators."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_units WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
        if row is None:
            raise ValueError("canonical evidence unit identifier was not issued by this index")
        unit = CanonicalEvidenceUnit(
            unit_id=row["unit_id"],
            source_id=row["source_id"],
            source_artifact_hash=row["source_artifact_hash"],
            parse_id=row["parse_id"],
            page=row["page"],
            kind=row["kind"],
            text=row["text"],
            spatial=None if row["spatial"] == "null" else tuple(json.loads(row["spatial"])),
            word_boxes=tuple(
                CanonicalWordBox.model_validate(item)
                for item in json.loads(row["word_boxes"] or "[]")
            ),
            trial_id=row["trial_id"],
            result_id=row["result_id"],
            domain_id=row["domain_id"],
            question_ids=tuple(json.loads(row["question_ids"] or "[]")),
            section_path=tuple(json.loads(row["section_path"] or "[]")),
            hierarchy_path=tuple(json.loads(row["hierarchy_path"] or "[]")),
            reading_order=row["reading_order"] or 0,
            source_role=row["source_role"],
            document_zone=row["document_zone"],
            discourse_scope=row["discourse_scope"] or TrialDiscourseScope.NONE,
            duplicate_group_id=row["duplicate_group_id"],
            warnings=tuple(json.loads(row["warnings"] or "[]")),
        )
        if scope is not None and not _unit_in_scope(unit, scope):
            raise ValueError("canonical evidence unit is outside the active retrieval scope")
        return unit

    def read_context(
        self,
        unit_id: Identifier,
        *,
        neighbor_limit: int = CONTEXT_NEIGHBOR_LIMIT,
        character_target: int = CONTEXT_CHARACTER_TARGET,
        mode: ReadContextMode = ReadContextMode.NEIGHBORS,
        scope: EvidenceScope | None = None,
        cursor: str | None = None,
    ) -> EvidenceContext:
        """Read an intact unit with deterministic, bounded same-source neighbors.

        The target is never split or replaced by a projection.  If it is larger
        than the context target, it is returned as a dedicated oversized view
        with explicit metadata and no neighbors.  Every returned unit retains
        its source artifact hash and Parse record ID.
        """
        if neighbor_limit < 0:
            raise ValueError("neighbor_limit must be non-negative")
        if character_target < 1:
            raise ValueError("character_target must be positive")
        if character_target > CONTEXT_CHARACTER_TARGET:
            raise ValueError(
                f"character_target cannot exceed {CONTEXT_CHARACTER_TARGET} characters"
            )
        snapshot = self._snapshot()
        target = self.read_unit(unit_id, scope=scope)
        if mode is ReadContextMode.UNIT:
            neighbor_limit = 0
        effective_neighbor_limit = min(neighbor_limit, max(0, CONTEXT_UNIT_LIMIT - 1))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unit_id, page FROM evidence_units "
                "WHERE source_id = ? AND source_artifact_hash = ? AND parse_id = ? "
                "ORDER BY page ASC, unit_id ASC",
                (target.source_id, target.source_artifact_hash, target.parse_id),
            ).fetchall()
        source_ids = sorted(
            (row["unit_id"] for row in rows),
            key=_canonical_unit_order,
        )
        if mode is ReadContextMode.SECTION and target.section_path:
            section_rows = []
            for candidate_id in source_ids:
                try:
                    candidate = self.read_unit(candidate_id, scope=scope)
                except ValueError:
                    continue
                if candidate.section_path == target.section_path:
                    section_rows.append(candidate_id)
            source_ids = section_rows
        try:
            position = source_ids.index(unit_id)
        except ValueError as error:  # pragma: no cover - read_unit already guards this
            raise ValueError("canonical evidence unit is not in the current snapshot") from error
        if mode is ReadContextMode.SECTION:
            candidate_ids = [candidate_id for candidate_id in source_ids if candidate_id != unit_id]
            offset = (
                _decode_read_cursor(cursor, snapshot, unit_id, self._cursor_secret())
                if cursor
                else 0
            )
            if offset > len(candidate_ids):
                raise ValueError("read continuation cursor is outside the current section")
            candidate_ids = candidate_ids[offset:]
        else:
            candidate_ids = [
                source_ids[index]
                for distance in range(1, len(source_ids) + 1)
                for index in (position - distance, position + distance)
                if 0 <= index < len(source_ids)
            ]
            offset = 0
        oversized = len(target.text) > character_target
        if oversized:
            if self._snapshot() != snapshot:
                raise ValueError("evidence snapshot changed while reading context")
            return EvidenceContext(
                snapshot_hash=snapshot,
                unit=target,
                character_count=len(target.text),
                character_target=character_target,
                neighbor_limit=effective_neighbor_limit,
                oversized=True,
                omitted_neighbor_count=max(0, len(source_ids) - 1),
                mode=mode,
                section_path=target.section_path,
                warnings=target.warnings,
                visual_inspection_available=(target.spatial is not None),
            )

        selected: list[CanonicalEvidenceUnit] = []
        characters = len(target.text)
        for candidate_id in candidate_ids:
            if len(selected) >= effective_neighbor_limit:
                break
            try:
                candidate = self.read_unit(candidate_id, scope=scope)
            except ValueError:
                # Same-source units outside the active Work-token scope are
                # boundaries, not implicit expansion candidates.
                continue
            if characters + len(candidate.text) > character_target:
                continue
            selected.append(candidate)
            characters += len(candidate.text)
        # Context is presented in source order, not alternating distance order.
        selected.sort(key=_canonical_unit_order)
        if self._snapshot() != snapshot:
            raise ValueError("evidence snapshot changed while reading context")
        return EvidenceContext(
            snapshot_hash=snapshot,
            unit=target,
            neighbors=tuple(selected),
            character_count=characters,
            character_target=character_target,
            neighbor_limit=effective_neighbor_limit,
            oversized=False,
            omitted_neighbor_count=max(0, len(source_ids) - 1 - len(selected)),
            mode=mode,
            section_path=target.section_path,
            continuation_cursor=(
                _encode_read_cursor(
                    snapshot,
                    target.unit_id,
                    offset + len(selected),
                    self._cursor_secret(),
                )
                if mode is ReadContextMode.SECTION
                and offset + len(selected) < len(candidate_ids) + offset
                else None
            ),
            warnings=target.warnings,
            visual_inspection_available=(target.spatial is not None),
        )

    def unit_ids(self) -> frozenset[Identifier]:
        """Return the stable engine-issued unit identities in the current snapshot."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unit_id FROM evidence_units ORDER BY unit_id"
            ).fetchall()
        return frozenset(row["unit_id"] for row in rows)

    def search(
        self,
        query: SearchQuery,
        *,
        policy: SearchPolicy | None = None,
        cursor: str | None = None,
        broad_query_justification: str | None = None,
        scope: EvidenceScope | None = None,
    ) -> SearchPage:
        policy = policy or SearchPolicy()
        snapshot = self._snapshot()
        query_hash = canonical_hash(query)
        offset = (
            _decode_cursor(cursor, snapshot, query_hash, policy, self._cursor_secret())
            if cursor
            else 0
        )
        rows, scoped_count, excluded_count = self._matches(query, scope=scope)
        if self._snapshot() != snapshot:
            raise ValueError("evidence snapshot changed while searching")
        rows = _best_projection_per_unit(rows)
        rows = _collapse_duplicate_groups(rows)
        rows = _diversify_rows(rows)
        if offset > len(rows):
            raise ValueError("search cursor offset is outside the current result set")
        is_broad = (
            len(rows) > policy.broad_unique_hit_threshold
            and scoped_count > 0
            and len(rows) / scoped_count > policy.broad_index_fraction
        )
        if is_broad and (
            broad_query_justification is None or not broad_query_justification.strip()
        ):
            raise ValueError("broad query requires refinement or complete-traversal justification")
        selected: list[sqlite3.Row] = []
        characters = 0
        for row in rows[offset:]:
            length = len(row["text"])
            if selected and (
                len(selected) >= policy.page_hit_target
                or characters + length > policy.page_character_target
            ):
                break
            selected.append(row)
            characters += length
            # An indivisible canonical unit gets a dedicated page, even when
            # it exceeds the ordinary character target.
            if length > policy.page_character_target:
                break
            if len(selected) >= policy.page_hit_target:
                break
        consumed = offset + len(selected)
        next_cursor = (
            _encode_cursor(snapshot, query_hash, policy, consumed, self._cursor_secret())
            if consumed < len(rows)
            else None
        )
        hits = tuple(
            self._hit(row, oversized=len(row["text"]) > policy.page_character_target)
            for row in selected
        )
        if self._snapshot() != snapshot:
            raise ValueError("evidence snapshot changed while searching")
        oversized_unit_ids = tuple(
            hit.unit.unit_id for hit in hits if len(hit.unit.text) > policy.page_character_target
        )
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
            policy_hash=canonical_hash(policy),
            hits=hits,
            next_cursor=next_cursor,
            preview=preview,
            character_count=characters,
            oversized_unit_ids=oversized_unit_ids,
            condition=(
                "zero_hits" if not hits and excluded_count == 0
                else "excluded_only" if not hits and excluded_count > 0
                else "truncated" if next_cursor is not None
                else "results"
            ),
            excluded_count=excluded_count,
            estimated_omitted_characters=sum(
                len(row["text"]) for row in rows[consumed:]
            ),
            next_actions=(
                ("refine the plain-language need or continue with the returned cursor",)
                if next_cursor is not None
                else (
                    ("read an issued canonical unit",)
                    if hits
                    else ("refine the plain-language need",)
                )
            ),
        )

    def _matches(
        self,
        query: SearchQuery,
        *,
        scope: EvidenceScope | None = None,
    ) -> tuple[list[sqlite3.Row], int, int]:
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
        metadata_filters = _query_metadata_filters(query, scope)
        filters.extend(metadata_filters[0])
        parameters.extend(metadata_filters[1])
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
            all_count = connection.execute(
                "SELECT COUNT(*) FROM evidence_units AS u"
            ).fetchone()[0]
        return rows, scoped_count, max(0, all_count - scoped_count)

    def _snapshot(self) -> ContentHash:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM evidence_snapshot WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ValueError("evidence index has no snapshot")
        return row[0]

    @staticmethod
    def _hit(row: sqlite3.Row, *, oversized: bool = False) -> SearchHit:
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
            word_boxes=tuple(
                CanonicalWordBox.model_validate(item)
                for item in json.loads(row["word_boxes"] or "[]")
            ),
            trial_id=row["trial_id"],
            result_id=row["result_id"],
            domain_id=row["domain_id"],
            question_ids=tuple(json.loads(row["question_ids"] or "[]")),
            section_path=tuple(json.loads(row["section_path"] or "[]")),
            hierarchy_path=tuple(json.loads(row["hierarchy_path"] or "[]")),
            reading_order=row["reading_order"] or 0,
            source_role=row["source_role"],
            document_zone=row["document_zone"],
            discourse_scope=row["discourse_scope"] or TrialDiscourseScope.NONE,
            duplicate_group_id=row["duplicate_group_id"],
            warnings=tuple(json.loads(row["warnings"] or "[]")),
        )
        projection_number = int(row["projection_id"].rsplit("-", 1)[1])
        projections = _project(unit)
        projection = projections[projection_number]
        return SearchHit(
            unit=unit,
            projection=projection,
            rank=row["score"],
            oversized=oversized,
            preview=_coherent_preview(unit.text),
            match_explanation="lexical match in canonical source text",
            warnings=unit.warnings
            + ((f"Trial discourse classified as {unit.discourse_scope.value}",)
               if unit.discourse_scope in {TrialDiscourseScope.MIXED, TrialDiscourseScope.UNCERTAIN}
               else ()),
            duplicate_group_id=unit.duplicate_group_id,
        )

    def _cursor_secret(self) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT secret FROM evidence_cursor_secret WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ValueError("evidence index has no cursor secret")
        return bytes(row["secret"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _compile_match(query: SearchQuery) -> str:
    clauses = [f'"{term}"' for term in query.terms]
    clauses.extend(f'"{phrase.strip()}"' for phrase in query.phrases)
    clauses.extend(f'"{prefix}"*' for prefix in query.prefixes)
    clauses.extend("(" + " OR ".join(f'"{term}"' for term in group) + ")" for group in query.any_of)
    return " AND ".join(clauses)


def _canonical_unit_order(unit: CanonicalEvidenceUnit | str) -> tuple[object, ...]:
    unit_id = unit.unit_id if isinstance(unit, CanonicalEvidenceUnit) else unit
    match = re.search(r"-p(\d+)-b(\d+)$", unit_id)
    if match:
        return (0, int(match.group(1)), int(match.group(2)), unit_id)
    return (1, unit_id)


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
            projection_version="1.0.0",
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


def _collapse_duplicate_groups(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Collapse exact duplicate source copies to one inspection candidate."""

    unique: dict[str, sqlite3.Row] = {}
    for row in rows:
        key = row["duplicate_group_id"] or row["unit_id"]
        current = unique.get(key)
        if current is None or (row["score"], row["unit_id"]) < (
            current["score"], current["unit_id"]
        ):
            unique[key] = row
    return sorted(unique.values(), key=lambda row: (row["score"], row["unit_id"]))


def _diversify_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Round-robin Sources while preserving lexical order inside each Source."""

    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(row["source_id"], []).append(row)
    for values in groups.values():
        values.sort(key=lambda row: (row["score"], row["unit_id"]))
    ordered: list[sqlite3.Row] = []
    for index in range(max((len(values) for values in groups.values()), default=0)):
        for source_id in sorted(groups):
            values = groups[source_id]
            if index < len(values):
                ordered.append(values[index])
    return ordered


def _coherent_preview(text: str, limit: int = 480) -> str:
    """Return a bounded source-authored preview without clipping mid-word."""

    if len(text) <= limit:
        return text
    candidate = text[:limit].rsplit(" ", 1)[0]
    return (candidate or text[:limit]).rstrip() + "…"


def _query_metadata_filters(
    query: SearchQuery,
    scope: EvidenceScope | None,
) -> tuple[list[str], list[object]]:
    filters: list[str] = []
    params: list[object] = []

    def add_in(column: str, values: tuple[str, ...]) -> None:
        if values:
            filters.append(f"u.{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)

    trial_ids = query.trial_ids or ((query.trial_id,) if query.trial_id else ())
    result_ids = query.result_ids or ((query.result_id,) if query.result_id else ())
    domain_ids = query.domain_ids or ((query.domain_id,) if query.domain_id else ())
    question_ids = query.question_ids or ((query.question_id,) if query.question_id else ())
    if scope is not None:
        if scope.trial_id is not None:
            trial_ids = (scope.trial_id,)
        if scope.result_id is not None:
            result_ids = (scope.result_id,)
        if scope.domain_id is not None:
            domain_ids = (scope.domain_id,)
        if scope.question_id is not None:
            question_ids = (scope.question_id,)
        if scope.source_ids:
            add_in("source_id", scope.source_ids)
    add_in("trial_id", trial_ids)
    add_in("result_id", result_ids)
    if domain_ids and scope is not None and scope.allow_unclassified:
        filters.append(
            "(u.domain_id IN ("
            + ",".join("?" for _ in domain_ids)
            + ") OR u.domain_id IS NULL)"
        )
        params.extend(domain_ids)
    else:
        add_in("domain_id", domain_ids)
    if question_ids:
        filters.append(
            "EXISTS (SELECT 1 FROM json_each(COALESCE(u.question_ids, '[]')) "
            "WHERE json_each.value IN ("
            + ",".join("?" for _ in question_ids)
            + "))"
        )
        params.extend(question_ids)
    source_roles = scope.source_roles if scope and scope.source_roles else query.source_roles
    add_in("source_role", source_roles)
    zones = scope.document_zones if scope and scope.document_zones else query.document_zones
    add_in("document_zone", tuple(zone.value for zone in zones))

    include_other = scope.include_other_trial if scope else query.include_other_trial
    if not include_other:
        filters.append(
            "COALESCE(u.discourse_scope, 'none') NOT IN ('other')"
        )
    include_uncertain = scope.include_uncertain if scope else query.include_uncertain
    if not include_uncertain:
        filters.append(
            "COALESCE(u.discourse_scope, 'none') NOT IN ('uncertain', 'mixed')"
        )
    # Ordinary retrieval excludes known non-evidence zones.  Callers can opt
    # into those zones explicitly through an EvidenceScope refinement.
    if not zones:
        filters.append(
            "COALESCE(u.document_zone, 'main') NOT IN "
            "('bibliography', 'contents', 'page_furniture', 'extraction_artifact')"
        )
    return filters, params


def _unit_in_scope(unit: CanonicalEvidenceUnit, scope: EvidenceScope) -> bool:
    if scope.trial_id is not None and unit.trial_id != scope.trial_id:
        return False
    if scope.result_id is not None and unit.result_id != scope.result_id:
        return False
    if (
        scope.domain_id is not None
        and unit.domain_id != scope.domain_id
        and not (scope.allow_unclassified and unit.domain_id is None)
    ):
        return False
    if scope.question_id is not None and scope.question_id not in unit.question_ids:
        return False
    if scope.source_ids and unit.source_id not in scope.source_ids:
        return False
    if scope.source_roles and unit.source_role not in scope.source_roles:
        return False
    if scope.document_zones and unit.document_zone not in scope.document_zones:
        return False
    if not scope.document_zones and unit.document_zone in {
        DocumentZone.BIBLIOGRAPHY,
        DocumentZone.CONTENTS,
        DocumentZone.PAGE_FURNITURE,
        DocumentZone.EXTRACTION_ARTIFACT,
    }:
        return False
    if not scope.include_other_trial and unit.discourse_scope is TrialDiscourseScope.OTHER:
        return False
    if not scope.include_uncertain and unit.discourse_scope in {
        TrialDiscourseScope.MIXED,
        TrialDiscourseScope.UNCERTAIN,
    }:
        return False
    return True


def _encode_cursor(
    snapshot: str,
    query_hash: str,
    policy: SearchPolicy,
    offset: int,
    secret: bytes,
) -> str:
    payload = json.dumps(
        {
            "snapshot": snapshot,
            "query": query_hash,
            "policy": canonical_hash(policy),
            "offset": offset,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    envelope = {
        "payload": base64.urlsafe_b64encode(payload).decode().rstrip("="),
        "mac": hmac.new(secret, payload, hashlib.sha256).hexdigest(),
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _encode_read_cursor(snapshot: str, unit_id: str, offset: int, secret: bytes) -> str:
    payload = json.dumps(
        {"snapshot": snapshot, "unit": unit_id, "offset": offset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    envelope = {
        "payload": base64.urlsafe_b64encode(payload).decode().rstrip("="),
        "mac": hmac.new(secret, payload, hashlib.sha256).hexdigest(),
    }
    return base64.urlsafe_b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def _decode_read_cursor(cursor: str, snapshot: str, unit_id: str, secret: bytes) -> int:
    try:
        envelope = json.loads(
            base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        )
        encoded_payload = envelope["payload"]
        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        expected = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
        if not isinstance(envelope.get("mac"), str) or not hmac.compare_digest(
            envelope["mac"], expected
        ):
            raise ValueError("invalid read continuation cursor integrity tag")
        payload = json.loads(payload_bytes)
        if payload.get("snapshot") != snapshot:
            raise ValueError("read continuation cursor belongs to a different snapshot")
        if payload.get("unit") != unit_id:
            raise ValueError("read continuation cursor belongs to a different unit")
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("read continuation cursor offset is invalid")
        return offset
    except ValueError:
        raise
    except (KeyError, TypeError, OverflowError, binascii.Error, json.JSONDecodeError) as error:
        raise ValueError("invalid read continuation cursor") from error


def _decode_cursor(
    cursor: str,
    snapshot: str,
    query_hash: str,
    policy: SearchPolicy,
    secret: bytes,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        envelope = json.loads(base64.urlsafe_b64decode(cursor + padding))
        encoded_payload = envelope["payload"]
        mac = envelope["mac"]
        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        expected_mac = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
        if not isinstance(mac, str) or not hmac.compare_digest(mac, expected_mac):
            raise ValueError("invalid search cursor integrity tag")
        payload = json.loads(payload_bytes)
        if payload["snapshot"] != snapshot:
            raise ValueError("cursor belongs to a different index snapshot")
        if payload["query"] != query_hash:
            raise ValueError("cursor belongs to a different structured query")
        if payload["policy"] != canonical_hash(policy):
            raise ValueError("cursor belongs to a different search policy")
        raw_offset = payload["offset"]
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, int):
            raise ValueError("search cursor offset is not an integer")
        offset = raw_offset
        if offset < 0:
            raise ValueError
        return offset
    except ValueError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        raise ValueError("invalid search cursor") from error
