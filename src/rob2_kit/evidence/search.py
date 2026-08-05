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

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.errors import (
    CursorScopeMismatch,
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    RetrievalFailure,
    ScopeMismatch,
    StaleCursor,
)

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
    UNCLASSIFIED = "unclassified"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    TABLE_ROW = "table_row"


class EvidenceApplicability(StrEnum):
    """Typed Result applicability for a canonical evidence unit."""

    RESULT = "result"
    TRIAL_WIDE = "trial_wide"
    UNRESOLVED = "unresolved"


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
    UNKNOWN = "unknown"
    OTHER = "other"


FORBIDDEN_RETRIEVAL_ZONES = frozenset(
    {
        DocumentZone.BIBLIOGRAPHY,
        DocumentZone.CONTENTS,
        DocumentZone.PAGE_FURNITURE,
        DocumentZone.EXTRACTION_ARTIFACT,
    }
)


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


def _same_context_structure(
    candidate: CanonicalEvidenceUnit, target: CanonicalEvidenceUnit
) -> bool:
    """Require identical explicit structure, discourse, zone, and table identity."""
    return (
        candidate.section_path == target.section_path
        and candidate.hierarchy_path == target.hierarchy_path
        and candidate.document_zone == target.document_zone
        and candidate.discourse_scope == target.discourse_scope
        and (
            candidate.kind is not CanonicalUnitKind.TABLE_ROW
            and target.kind is not CanonicalUnitKind.TABLE_ROW
            or (
                candidate.kind is CanonicalUnitKind.TABLE_ROW
                and target.kind is CanonicalUnitKind.TABLE_ROW
                and bool(candidate.table_headers or candidate.caption)
                and bool(target.table_headers or target.caption)
                and candidate.table_headers == target.table_headers
                and candidate.caption == target.caption
            )
        )
    )


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
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    applicability: EvidenceApplicability = EvidenceApplicability.UNRESOLVED
    applicable_result_ids: tuple[Identifier, ...] = ()
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: SourceRole | None = None
    document_zone: DocumentZone | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    discourse_scope: TrialDiscourseScope = TrialDiscourseScope.NONE
    duplicate_group_id: Identifier | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_word_boxes(self) -> CanonicalEvidenceUnit:
        if self.applicability is EvidenceApplicability.RESULT and self.result_id is None:
            raise ValueError("result applicability requires result_id")
        if self.applicability is EvidenceApplicability.TRIAL_WIDE and self.result_id is not None:
            raise ValueError("trial-wide applicability cannot carry result_id")
        if (
            self.applicability is EvidenceApplicability.TRIAL_WIDE
            and not self.applicable_result_ids
        ):
            raise ValueError("trial-wide applicability requires applicable_result_ids")
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
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_ids: tuple[Identifier, ...] = ()
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    applicability: EvidenceApplicability | None = None
    applicable_result_ids: tuple[Identifier, ...] = ()
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: SourceRole | None = None
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
    applicability: EvidenceApplicability = EvidenceApplicability.UNRESOLVED,
    applicable_result_ids: tuple[Identifier, ...] = (),
) -> tuple[CanonicalEvidenceUnit, ...]:
    """Turn parser-preserved structural blocks into immutable citable units."""
    source_slug = source_id.removeprefix("source:")
    if len({page.page for page in pages}) != len(pages):
        raise ValueError("canonicalization pages must be unique")
    units: list[CanonicalEvidenceUnit] = []
    for page in sorted(pages, key=lambda item: item.page):
        for number, block in enumerate(page.blocks, start=1):
            block_applicability = block.applicability or (
                EvidenceApplicability.RESULT if block.result_id is not None else applicability
            )
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
                    trial_id=block.trial_id or trial_id,
                    result_id=(
                        block.result_id
                        if block_applicability is EvidenceApplicability.RESULT
                        else None
                    )
                    or (result_id if block_applicability is EvidenceApplicability.RESULT else None),
                    domain_id=block.domain_id or domain_id,
                    question_ids=block.question_ids,
                    table_headers=block.table_headers,
                    caption=block.caption,
                    applicability=block_applicability,
                    applicable_result_ids=(block.applicable_result_ids or applicable_result_ids),
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
    projection_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def validate_non_citable(self) -> SearchProjection:
        if self.citable:
            raise ValueError("search projections are non-citable")
        if self.end <= self.start:
            raise ValueError("search projection span must have positive extent")
        if len(self.text) != self.end - self.start:
            raise ValueError("search projection text must bind its exact canonical span")
        return self


class SearchQueryFields(BaseModel):
    """Shared lexical and metadata fields for engine and transport queries.

    This model intentionally contains only the wire-safe field contract.  The
    engine-facing :class:`SearchQuery` adds semantic FTS validation, while the
    MCP :class:`SearchQueryEnvelope` uses this same schema before handing the
    values to the engine for that validation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    terms: tuple[str, ...] = Field(
        default=(),
        max_length=32,
        description="Lexical tokens; e.g. ['allocation'].",
        examples=[["allocation"]],
    )
    phrases: tuple[str, ...] = Field(
        default=(),
        max_length=16,
        description="Exact multi-word phrases; raw FTS syntax is not accepted.",
        examples=[["allocation concealment"]],
    )
    prefixes: tuple[str, ...] = Field(
        default=(),
        max_length=16,
        description="Token prefixes without wildcard syntax.",
        examples=[["random"]],
    )
    any_of: tuple[tuple[str, ...], ...] = Field(
        default=(),
        max_length=8,
        description="Boolean alternative groups of lexical tokens; each group is non-empty.",
        examples=[[["sealed"], ["central"]]],
    )
    source_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Source IDs issued by get_work_context.",
    )
    kinds: tuple[CanonicalUnitKind, ...] = Field(
        default=(),
        max_length=8,
        description="Finite canonical-unit kind filters.",
        examples=[[CanonicalUnitKind.PARAGRAPH.value]],
    )
    pages: tuple[int, ...] = Field(
        default=(),
        max_length=128,
        description="One-based source page numbers.",
        examples=[[1, 2]],
    )
    # Safe metadata refinements.  These are values, never executable FTS
    # syntax; active Work-token scope is applied in addition to these filters.
    trial_id: Identifier | None = Field(
        default=None,
        description="One Trial identifier refinement; do not combine with trial_ids.",
    )
    result_id: Identifier | None = Field(
        default=None,
        description="One Result identifier refinement; do not combine with result_ids.",
    )
    domain_id: Identifier | None = Field(
        default=None,
        description="One Domain identifier refinement; do not combine with domain_ids.",
    )
    question_id: Identifier | None = Field(
        default=None,
        description="One signaling-question identifier; do not combine with question_ids.",
    )
    trial_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Explicit Trial ID set; mutually exclusive with trial_id.",
    )
    result_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Explicit Result ID set; mutually exclusive with result_id.",
    )
    domain_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Explicit Domain ID set; mutually exclusive with domain_id.",
    )
    question_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Explicit question ID set; mutually exclusive with question_id.",
    )
    source_roles: tuple[SourceRole, ...] = Field(
        default=(),
        max_length=8,
        description="Finite source-role values from Source classification.",
        examples=[[SourceRole.PRIMARY_REPORT.value]],
    )
    document_zones: tuple[DocumentZone, ...] = Field(
        default=(),
        max_length=8,
        description=(
            "Finite semantic document zones; forbidden bibliography/contents zones are rejected."
        ),
        examples=[[DocumentZone.RESULTS.value]],
    )
    include_uncertain: bool = Field(
        default=False,
        description="Include parser-uncertain Trial discourse only when explicitly requested.",
    )
    include_other_trial: bool = Field(
        default=False, description="Include other-Trial discourse only when explicitly justified."
    )


class SearchQuery(SearchQueryFields):
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
        if any(
            not _TOKEN.fullmatch(token) or any(ord(character) < 0x20 for character in token)
            for token in tokens
        ):
            raise ValueError("raw FTS syntax is not accepted")
        if any(
            not phrase.strip()
            or '"' in phrase
            or any(ord(character) < 0x20 for character in phrase)
            for phrase in self.phrases
        ):
            raise ValueError("raw FTS syntax is not accepted")
        if any(page < 1 for page in self.pages):
            raise ValueError("page filters use one-based positive page numbers")
        if any(not role.strip() for role in self.source_roles):
            raise ValueError("source roles cannot be blank")
        for singular, plural, label in (
            (self.trial_id, self.trial_ids, "trial"),
            (self.result_id, self.result_ids, "result"),
            (self.domain_id, self.domain_ids, "domain"),
            (self.question_id, self.question_ids, "question"),
        ):
            if singular is not None and plural:
                raise ValueError(f"{label}_id and {label}_ids are mutually exclusive")
        if FORBIDDEN_RETRIEVAL_ZONES.intersection(self.document_zones):
            raise ValueError(
                "bibliography, contents, page_furniture, and extraction_artifact "
                "zones are excluded from evidence retrieval; review Source classification"
            )
        return self


class EvidenceScope(FrozenModel):
    """Engine-issued scope applied before lexical ranking."""

    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_id: Identifier | None = None
    source_ids: tuple[Identifier, ...] = ()
    source_roles: tuple[SourceRole, ...] = ()
    document_zones: tuple[DocumentZone, ...] = ()
    include_uncertain: bool = False
    include_other_trial: bool = False
    work_token_id: Identifier | None = None
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
    scope_warnings: tuple[str, ...] = ()

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
    mode: ReadContextMode = ReadContextMode.UNIT
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
            if any(
                item.section_path != self.section_path
                or item.hierarchy_path != self.unit.hierarchy_path
                or item.discourse_scope != self.unit.discourse_scope
                for item in self.neighbors
            ):
                raise ValueError("section context cannot cross hierarchy boundaries")
        if self.mode in {ReadContextMode.NEIGHBORS, ReadContextMode.SECTION}:
            if any(item.document_zone != self.unit.document_zone for item in self.neighbors):
                raise ValueError("context cannot cross document-zone boundaries")
            if self.unit.kind is CanonicalUnitKind.TABLE_ROW:
                if not (self.unit.table_headers or self.unit.caption):
                    raise ValueError("table context requires a stable header or caption identity")
                if any(
                    item.kind is not CanonicalUnitKind.TABLE_ROW
                    or not (item.table_headers or item.caption)
                    or item.table_headers != self.unit.table_headers
                    or item.caption != self.unit.caption
                    for item in self.neighbors
                ):
                    raise ValueError("table context cannot cross table identity boundaries")
        return self

    @property
    def all_units(self) -> tuple[CanonicalEvidenceUnit, ...]:
        """Return the target followed by context in deterministic source order."""
        return (self.unit, *self.neighbors)


class EvidenceSearchIndex:
    """Persistent FTS5 index whose cursors are invalid across snapshot changes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise OperationalRetrievalFailure(
                "unable to prepare the evidence retrieval index directory"
            ) from error
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
                    applicability TEXT NOT NULL DEFAULT 'result',
                    applicable_result_ids TEXT,
                    table_headers TEXT,
                    caption TEXT,
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
                "applicability": "TEXT NOT NULL DEFAULT 'result'",
                "applicable_result_ids": "TEXT",
                "table_headers": "TEXT",
                "caption": "TEXT",
                "duplicate_group_id": "TEXT",
                "warnings": "TEXT",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE evidence_units ADD COLUMN {name} {declaration}"
                    )
            # Historical rows (including databases that already carried an
            # applicability column from an interrupted migration) must never
            # inherit RESULT when they have no Result identity. Preserve
            # explicit TRIAL_WIDE/UNRESOLVED values.
            connection.execute(
                "UPDATE evidence_units SET applicability = 'unresolved' "
                "WHERE result_id IS NULL "
                "AND (applicability IS NULL OR applicability = 'result')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO evidence_cursor_secret(singleton, secret) VALUES (1, ?)",
                (secrets.token_bytes(32),),
            )

    def replace_units(self, units: tuple[CanonicalEvidenceUnit, ...]) -> ContentHash:
        ordered = tuple(sorted(units, key=lambda item: item.unit_id))
        if len({item.unit_id for item in ordered}) != len(ordered):
            raise InvalidRetrievalRequest("canonical unit IDs must be unique", field="units")
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
                    "discourse_scope, applicability, applicable_result_ids, table_headers, "
                    "caption, "
                    "duplicate_group_id, warnings) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?)",
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
                        item.applicability.value,
                        json.dumps(item.applicable_result_ids),
                        json.dumps(item.table_headers),
                        item.caption,
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

    def preview(
        self,
        query: SearchQuery,
        *,
        policy: SearchPolicy | None = None,
        scope: EvidenceScope | None = None,
    ) -> QueryPreview:
        policy = policy or SearchPolicy()
        rows, scoped_count, _ = self._matches(query, scope=scope)
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
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM evidence_units WHERE unit_id = ?",
                    (unit_id,),
                ).fetchone()
            if row is None:
                raise InvalidRetrievalRequest(
                    "canonical evidence unit identifier was not issued by this index",
                    field="unit_id",
                )
            unit = _unit_from_row(row)
            if scope is not None and not _unit_in_scope(unit, scope):
                raise ScopeMismatch(
                    "canonical evidence unit is outside the active retrieval scope",
                    field="unit_id",
                )
            return unit
        except RetrievalFailure:
            raise
        except (sqlite3.Error, OSError) as error:
            raise OperationalRetrievalFailure(
                "unable to read canonical evidence from the retrieval index",
                field="unit_id",
            ) from error

    def read_context(
        self,
        unit_id: Identifier,
        *,
        neighbor_limit: int = CONTEXT_NEIGHBOR_LIMIT,
        character_target: int = CONTEXT_CHARACTER_TARGET,
        mode: ReadContextMode = ReadContextMode.UNIT,
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
            raise InvalidRetrievalRequest(
                "neighbor_limit must be non-negative", field="neighbor_limit"
            )
        if character_target < 1:
            raise InvalidRetrievalRequest(
                "character_target must be positive", field="character_target"
            )
        if character_target > CONTEXT_CHARACTER_TARGET:
            raise InvalidRetrievalRequest(
                f"character_target cannot exceed {CONTEXT_CHARACTER_TARGET} characters",
                field="character_target",
            )
        if cursor is not None and mode is not ReadContextMode.SECTION:
            raise InvalidRetrievalRequest(
                "read continuation cursor is only valid for section mode", field="cursor"
            )
        snapshot = self._snapshot()
        target = self.read_unit(unit_id, scope=scope)
        if mode is ReadContextMode.UNIT:
            neighbor_limit = 0
        effective_neighbor_limit = min(neighbor_limit, max(0, CONTEXT_UNIT_LIMIT - 1))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT unit_id, page, reading_order FROM evidence_units "
                "WHERE source_id = ? AND source_artifact_hash = ? AND parse_id = ? "
                "ORDER BY page ASC, unit_id ASC",
                (target.source_id, target.source_artifact_hash, target.parse_id),
            ).fetchall()
        source_ids = [
            row["unit_id"]
            for row in sorted(
                rows,
                key=lambda row: (row["reading_order"] or 0, row["page"], row["unit_id"]),
            )
        ]
        section_boundary_reached = False
        if mode is ReadContextMode.SECTION:
            if not target.section_path:
                # Without parser-provided section structure, do not flatten
                # the entire source into a fabricated section continuation.
                section_boundary_reached = len(source_ids) > 1
                source_ids = [unit_id]
            else:
                section_rows = [unit_id]
                original_position = source_ids.index(unit_id)
                for direction in (-1, 1):
                    index = original_position + direction
                    while 0 <= index < len(source_ids):
                        candidate_id = source_ids[index]
                        try:
                            candidate = self.read_unit(candidate_id, scope=scope)
                        except ValueError:
                            section_boundary_reached = True
                            break
                        if not _same_context_structure(candidate, target):
                            section_boundary_reached = True
                            break
                        section_rows.append(candidate_id)
                        index += direction
                section_rows.sort(key=source_ids.index)
                section_boundary_reached = len(section_rows) < len(source_ids)
                source_ids = section_rows
        try:
            position = source_ids.index(unit_id)
        except ValueError as error:  # pragma: no cover - read_unit already guards this
            raise StaleCursor(
                "canonical evidence unit is not in the current snapshot", field="unit_id"
            ) from error
        if mode is ReadContextMode.SECTION:
            candidate_ids = [candidate_id for candidate_id in source_ids if candidate_id != unit_id]
            offset = (
                _decode_read_cursor(
                    cursor,
                    snapshot,
                    unit_id,
                    self._cursor_secret(),
                    scope=scope,
                )
                if cursor
                else 0
            )
            if offset > len(candidate_ids):
                raise StaleCursor("read continuation cursor is outside the current section")
            candidate_ids = candidate_ids[offset:]
        else:
            offset = 0
            directional_candidates: dict[int, list[str]] = {-1: [], 1: []}
            if not target.section_path or not target.hierarchy_path:
                # Neighbors require an explicit structural anchor.  Shared
                # zone/discourse alone is not enough to infer scientific
                # adjacency; return the target with a limitation warning.
                section_boundary_reached = len(source_ids) > 1
            else:
                for direction in (-1, 1):
                    index = position + direction
                    while 0 <= index < len(source_ids):
                        candidate_id = source_ids[index]
                        try:
                            candidate = self.read_unit(candidate_id, scope=scope)
                        except ValueError:
                            section_boundary_reached = True
                            break
                        same_structure = _same_context_structure(candidate, target)
                        if not same_structure:
                            section_boundary_reached = True
                            break
                        directional_candidates[direction].append(candidate_id)
                        index += direction
            candidate_ids = [
                candidate_id
                for distance in range(
                    max(
                        len(directional_candidates[-1]),
                        len(directional_candidates[1]),
                    )
                )
                for direction in (-1, 1)
                if distance < len(directional_candidates[direction])
                for candidate_id in (directional_candidates[direction][distance],)
            ]
        boundary_warnings = (
            ("structural_boundary_reached",)
            if (
                section_boundary_reached
                or (mode is ReadContextMode.NEIGHBORS and len(candidate_ids) < len(source_ids) - 1)
            )
            else ()
        )

        def discourse_warnings(units: tuple[CanonicalEvidenceUnit, ...]) -> tuple[str, ...]:
            if any(
                item.discourse_scope in {TrialDiscourseScope.MIXED, TrialDiscourseScope.UNCERTAIN}
                for item in units
            ):
                return ("trial_discourse_uncertain",)
            return ()

        target_discourse_warnings = discourse_warnings((target,))
        oversized = len(target.text) > character_target
        if oversized:
            if self._snapshot() != snapshot:
                raise StaleCursor("evidence snapshot changed while reading context", field="cursor")
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
                warnings=target.warnings + target_discourse_warnings + boundary_warnings,
                visual_inspection_available=(target.spatial is not None),
            )

        selected: list[CanonicalEvidenceUnit] = []
        characters = len(target.text)
        scanned = 0
        oversized_neighbor_skipped = False
        for candidate_id in candidate_ids:
            if len(selected) >= effective_neighbor_limit:
                break
            scanned += 1
            try:
                candidate = self.read_unit(candidate_id, scope=scope)
            except ValueError:
                # Same-source units outside the active Work-token scope are
                # boundaries, not implicit expansion candidates.
                continue
            if characters + len(candidate.text) > character_target:
                oversized_neighbor_skipped = True
                continue
            selected.append(candidate)
            characters += len(candidate.text)
        # Context is presented in source order, not alternating distance order.
        selected.sort(key=_canonical_unit_order)
        if self._snapshot() != snapshot:
            raise StaleCursor("evidence snapshot changed while reading context", field="cursor")
        next_offset = offset + scanned
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
                    next_offset,
                    self._cursor_secret(),
                    scope=scope,
                )
                if mode is ReadContextMode.SECTION and next_offset < len(candidate_ids) + offset
                else None
            ),
            warnings=target.warnings
            + discourse_warnings((target, *selected))
            + boundary_warnings
            + (("oversized_neighbor_skipped",) if oversized_neighbor_skipped else ()),
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
            _decode_cursor(
                cursor,
                snapshot,
                query_hash,
                policy,
                self._cursor_secret(),
                scope=scope,
            )
            if cursor
            else 0
        )
        rows, scoped_count, excluded_count = self._matches(query, scope=scope)
        if self._snapshot() != snapshot:
            raise StaleCursor("evidence snapshot changed while searching", field="cursor")
        rows = _best_projection_per_unit(rows)
        rows = _collapse_duplicate_groups(rows)
        rows = _diversify_rows(rows)
        if offset > len(rows):
            raise StaleCursor("search cursor offset is outside the current result set")
        is_broad = (
            len(rows) > policy.broad_unique_hit_threshold
            and scoped_count > 0
            and len(rows) / scoped_count > policy.broad_index_fraction
        )
        if is_broad and (
            broad_query_justification is None or not broad_query_justification.strip()
        ):
            raise InvalidRetrievalRequest(
                "broad query requires refinement or complete-traversal justification",
                field="broad_query_justification",
            )
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
            _encode_cursor(
                snapshot,
                query_hash,
                policy,
                consumed,
                self._cursor_secret(),
                scope=scope,
            )
            if consumed < len(rows)
            else None
        )
        hits = tuple(
            self._hit(row, oversized=len(row["text"]) > policy.page_character_target)
            for row in selected
        )
        warning_values: list[str] = []
        if (
            scope is not None
            and scope.allow_unclassified
            and any(row["domain_id"] is None for row in rows)
        ):
            warning_values.append("domain_scope_unclassified_units")
        if (
            scope is not None
            and scope.result_id is not None
            and any(
                (row["applicability"] or EvidenceApplicability.UNRESOLVED.value)
                != EvidenceApplicability.RESULT.value
                for row in rows
            )
        ):
            warning_values.append("result_scope_unresolved_units")
        if excluded_count:
            warning_values.append("retrieval_scope_excluded_matches")
            if scope is not None and (scope.domain_id is not None or scope.question_id is not None):
                warning_values.append("scope_provenance_unclassified_units_excluded")
        scope_warnings = tuple(warning_values)
        if scope_warnings:
            hits = tuple(
                hit.model_copy(update={"warnings": hit.warnings + scope_warnings}) for hit in hits
            )
        if self._snapshot() != snapshot:
            raise StaleCursor("evidence snapshot changed while searching", field="cursor")
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
                "zero_hits"
                if not hits and excluded_count == 0
                else "excluded_only"
                if not hits and excluded_count > 0
                else "truncated"
                if next_cursor is not None
                else "results"
            ),
            excluded_count=excluded_count,
            estimated_omitted_characters=sum(len(row["text"]) for row in rows[consumed:]),
            next_actions=(
                ("refine the plain-language need or continue with the returned cursor",)
                if next_cursor is not None
                else (
                    ("read an issued canonical unit",)
                    if hits
                    else (
                        (
                            "review Source/zone classification, then retry with the active "
                            "Work token",
                        )
                        if excluded_count
                        else ("refine the plain-language need",)
                    )
                )
            ),
            scope_warnings=scope_warnings,
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
        base_filters = list(filters)
        base_parameters = list(parameters[1:])
        metadata_filters = _query_metadata_filters(query, scope)
        filters.extend(metadata_filters[0])
        parameters.extend(metadata_filters[1])
        where = " AND " + " AND ".join(filters) if filters else ""
        # Count lexical candidates before *any* Work-token metadata policy so
        # excluded-only pages can explain why authored text was withheld,
        # including units whose Domain/question provenance is missing.
        lexical_where = " AND " + " AND ".join(base_filters) if base_filters else ""
        lexical_query_parameters = [match, *base_parameters]
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
            lexical_rows = connection.execute(
                f"""
                SELECT DISTINCT u.unit_id
                FROM evidence_fts AS f
                JOIN evidence_units AS u ON u.unit_id = f.unit_id
                WHERE evidence_fts MATCH ?{lexical_where}
                """,
                lexical_query_parameters,
            ).fetchall()
        lexical_ids = {row[0] for row in lexical_rows}
        scoped_ids = {row["unit_id"] for row in rows}
        return rows, scoped_count, max(0, len(lexical_ids - scoped_ids))

    def _snapshot(self) -> ContentHash:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM evidence_snapshot WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise OperationalRetrievalFailure("evidence index has no snapshot")
        return row[0]

    @staticmethod
    def _hit(row: sqlite3.Row, *, oversized: bool = False) -> SearchHit:
        unit = _unit_from_row(row)
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
            + (
                (f"Trial discourse classified as {unit.discourse_scope.value}",)
                if unit.discourse_scope
                in {TrialDiscourseScope.MIXED, TrialDiscourseScope.UNCERTAIN}
                else ()
            ),
            duplicate_group_id=unit.duplicate_group_id,
        )

    def _cursor_secret(self) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT secret FROM evidence_cursor_secret WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise OperationalRetrievalFailure("evidence index has no cursor secret")
        return bytes(row["secret"])

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path)
        except (sqlite3.Error, OSError) as error:
            raise OperationalRetrievalFailure(
                "unable to open the evidence retrieval index"
            ) from error
        connection.row_factory = sqlite3.Row
        return connection


def _compile_match(query: SearchQuery) -> str:
    clauses = [f'"{term}"' for term in query.terms]
    clauses.extend(f'"{phrase.strip()}"' for phrase in query.phrases)
    clauses.extend(f'"{prefix}"*' for prefix in query.prefixes)
    clauses.extend("(" + " OR ".join(f'"{term}"' for term in group) + ")" for group in query.any_of)
    return " AND ".join(clauses)


def _unit_from_row(row: sqlite3.Row) -> CanonicalEvidenceUnit:
    """Convert one stored row to the canonical unit used by every read path."""

    spatial = json.loads(row["spatial"]) if row["spatial"] else None
    return CanonicalEvidenceUnit(
        unit_id=row["unit_id"],
        source_id=row["source_id"],
        source_artifact_hash=row["source_artifact_hash"],
        parse_id=row["parse_id"],
        page=row["page"],
        kind=row["kind"],
        text=row["text"],
        spatial=tuple(spatial) if spatial else None,
        word_boxes=tuple(
            CanonicalWordBox.model_validate(item) for item in json.loads(row["word_boxes"] or "[]")
        ),
        trial_id=row["trial_id"],
        result_id=row["result_id"],
        domain_id=row["domain_id"],
        question_ids=tuple(json.loads(row["question_ids"] or "[]")),
        applicability=row["applicability"] or EvidenceApplicability.UNRESOLVED,
        applicable_result_ids=tuple(json.loads(row["applicable_result_ids"] or "[]")),
        table_headers=tuple(json.loads(row["table_headers"] or "[]")),
        caption=row["caption"],
        section_path=tuple(json.loads(row["section_path"] or "[]")),
        hierarchy_path=tuple(json.loads(row["hierarchy_path"] or "[]")),
        reading_order=row["reading_order"] or 0,
        source_role=(SourceRole(row["source_role"]) if row["source_role"] else None),
        document_zone=row["document_zone"],
        discourse_scope=row["discourse_scope"] or TrialDiscourseScope.NONE,
        duplicate_group_id=row["duplicate_group_id"],
        warnings=tuple(json.loads(row["warnings"] or "[]")),
    )


def _canonical_unit_order(unit: CanonicalEvidenceUnit | str) -> tuple[object, ...]:
    """Order by parser-provided reading order, then deterministic tie-breakers."""

    if isinstance(unit, CanonicalEvidenceUnit):
        return (unit.reading_order, unit.page, unit.unit_id)
    return (0, 0, unit)


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
            current["score"],
            current["unit_id"],
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
    *,
    apply_policy_exclusions: bool = True,
) -> tuple[list[str], list[object]]:
    filters: list[str] = []
    params: list[object] = []

    def add_in(column: str, values: tuple[str, ...]) -> None:
        if values:
            filters.append(f"u.{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)

    trial_ids = query.trial_ids or ((query.trial_id,) if query.trial_id else ())
    result_ids = query.result_ids or ((query.result_id,) if query.result_id else ())
    scoped_result_id: Identifier | None = None
    domain_ids = query.domain_ids or ((query.domain_id,) if query.domain_id else ())
    question_ids = query.question_ids or ((query.question_id,) if query.question_id else ())

    def intersect(
        requested: tuple[Identifier, ...], allowed: tuple[Identifier, ...]
    ) -> tuple[Identifier, ...]:
        if requested and allowed:
            narrowed = tuple(value for value in requested if value in allowed)
            if not narrowed:
                filters.append("1 = 0")
            return narrowed
        return requested or allowed

    if scope is not None:
        if scope.trial_id is not None:
            trial_ids = intersect(trial_ids, (scope.trial_id,))
        if scope.result_id is not None:
            scoped_result_id = scope.result_id
            if result_ids and scope.result_id not in result_ids:
                filters.append("1 = 0")
            result_ids = ()
        if scope.domain_id is not None:
            domain_ids = intersect(domain_ids, (scope.domain_id,))
        if scope.question_id is not None:
            question_ids = intersect(question_ids, (scope.question_id,))
        if scope.source_ids:
            source_ids = intersect(query.source_ids, scope.source_ids)
            add_in("source_id", source_ids)
        elif query.source_ids:
            add_in("source_id", query.source_ids)
    elif query.source_ids:
        add_in("source_id", query.source_ids)
    add_in("trial_id", trial_ids)
    if scoped_result_id is not None:
        filters.append(
            "(u.result_id = ? OR (u.result_id IS NULL "
            "AND u.applicability IN ('trial_wide', 'unresolved') "
            "AND EXISTS (SELECT 1 FROM json_each(COALESCE(u.applicable_result_ids, '[]')) "
            "WHERE json_each.value = ?)))"
        )
        params.extend((scoped_result_id, scoped_result_id))
    else:
        add_in("result_id", result_ids)
    if domain_ids and scope is not None and scope.allow_unclassified:
        filters.append(
            "(u.domain_id IN (" + ",".join("?" for _ in domain_ids) + ") OR u.domain_id IS NULL)"
        )
        params.extend(domain_ids)
    else:
        add_in("domain_id", domain_ids)
    if question_ids:
        filters.append(
            "EXISTS (SELECT 1 FROM json_each(COALESCE(u.question_ids, '[]')) "
            "WHERE json_each.value IN (" + ",".join("?" for _ in question_ids) + "))"
        )
        params.extend(question_ids)
    source_roles = query.source_roles
    if scope and scope.source_roles:
        if source_roles:
            source_roles = tuple(role for role in source_roles if role in scope.source_roles)
            if not source_roles:
                filters.append("1 = 0")
        else:
            source_roles = scope.source_roles
    add_in("source_role", source_roles)
    zones = query.document_zones
    if scope and scope.document_zones:
        if zones:
            zones = tuple(zone for zone in zones if zone in scope.document_zones)
            if not zones:
                filters.append("1 = 0")
        else:
            zones = scope.document_zones
    add_in("document_zone", tuple(zone.value for zone in zones))

    include_other = scope.include_other_trial if scope else query.include_other_trial
    if apply_policy_exclusions and not include_other:
        filters.append("COALESCE(u.discourse_scope, 'none') NOT IN ('other')")
    include_uncertain = scope.include_uncertain if scope else query.include_uncertain
    if apply_policy_exclusions and not include_uncertain:
        filters.append("COALESCE(u.discourse_scope, 'none') NOT IN ('uncertain', 'mixed')")
    # Ordinary retrieval excludes known non-evidence zones.  The blacklist is
    # immutable at this boundary, so semantic refinements cannot opt them back in.
    if apply_policy_exclusions:
        # Missing or unknown parser zones are never silently promoted to main
        # text, including for lower-level callers without a workflow scope.
        filters.append("u.document_zone IS NOT NULL")
        filters.append("u.document_zone != 'unknown'")
        filters.append(
            "u.document_zone NOT IN "
            "('bibliography', 'contents', 'page_furniture', 'extraction_artifact')"
        )
    return filters, params


def _unit_in_scope(unit: CanonicalEvidenceUnit, scope: EvidenceScope) -> bool:
    if unit.document_zone is None or unit.document_zone is DocumentZone.UNKNOWN:
        return False
    if scope.trial_id is not None and unit.trial_id != scope.trial_id:
        return False
    if scope.result_id is not None:
        if unit.result_id != scope.result_id and not (
            unit.result_id is None
            and unit.applicability
            in {
                EvidenceApplicability.TRIAL_WIDE,
                EvidenceApplicability.UNRESOLVED,
            }
            and scope.result_id in unit.applicable_result_ids
        ):
            return False
    if (
        scope.domain_id is not None
        and unit.domain_id != scope.domain_id
        and not (scope.allow_unclassified and scope.question_id is None and unit.domain_id is None)
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
    if (
        unit.document_zone in FORBIDDEN_RETRIEVAL_ZONES
        or unit.document_zone is DocumentZone.UNKNOWN
    ):
        return False
    if not scope.include_other_trial and unit.discourse_scope is TrialDiscourseScope.OTHER:
        return False
    if not scope.include_uncertain and unit.discourse_scope in {
        TrialDiscourseScope.MIXED,
        TrialDiscourseScope.UNCERTAIN,
    }:
        return False
    return True


class _SignedCursorCodec:
    """Shared authenticated envelope codec for search and read cursors."""

    @staticmethod
    def encode(payload: dict[str, object], secret: bytes) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        envelope = {
            "payload": base64.urlsafe_b64encode(raw).decode().rstrip("="),
            "mac": hmac.new(secret, raw, hashlib.sha256).hexdigest(),
        }
        return (
            base64.urlsafe_b64encode(
                json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )

    @staticmethod
    def decode(cursor: str, secret: bytes) -> dict[str, object]:
        try:
            envelope = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            encoded = envelope["payload"]
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
            if not isinstance(envelope.get("mac"), str) or not hmac.compare_digest(
                envelope["mac"], expected
            ):
                raise ValueError("invalid cursor integrity tag")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("invalid cursor payload")
            return payload
        except UnicodeDecodeError as error:
            raise ValueError("invalid cursor") from error
        except ValueError:
            raise
        except (KeyError, TypeError, OverflowError, binascii.Error, json.JSONDecodeError) as error:
            raise ValueError("invalid cursor") from error


def _encode_cursor(
    snapshot: str,
    query_hash: str,
    policy: SearchPolicy,
    offset: int,
    secret: bytes,
    *,
    scope: EvidenceScope | None = None,
) -> str:
    return _SignedCursorCodec.encode(
        {
            "snapshot": snapshot,
            "query": query_hash,
            "policy": canonical_hash(policy),
            "offset": offset,
            "scope": canonical_hash(scope) if scope is not None else None,
        },
        secret,
    )


def _encode_read_cursor(
    snapshot: str,
    unit_id: str,
    offset: int,
    secret: bytes,
    *,
    scope: EvidenceScope | None = None,
) -> str:
    return _SignedCursorCodec.encode(
        {
            "snapshot": snapshot,
            "unit": unit_id,
            "offset": offset,
            "scope": canonical_hash(scope) if scope is not None else None,
        },
        secret,
    )


def _decode_read_cursor(
    cursor: str,
    snapshot: str,
    unit_id: str,
    secret: bytes,
    *,
    scope: EvidenceScope | None = None,
) -> int:
    try:
        payload = _SignedCursorCodec.decode(cursor, secret)
        if payload.get("snapshot") != snapshot:
            raise StaleCursor("read continuation cursor belongs to a different snapshot")
        if payload.get("unit") != unit_id:
            raise CursorScopeMismatch("read continuation cursor belongs to a different unit")
        if payload.get("scope") != (canonical_hash(scope) if scope is not None else None):
            raise CursorScopeMismatch(
                "read continuation cursor belongs to a different Evidence scope"
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise StaleCursor("read continuation cursor offset is invalid")
        return offset
    except RetrievalFailure:
        raise
    except ValueError as error:
        raise StaleCursor("invalid read continuation cursor") from error


def _decode_cursor(
    cursor: str,
    snapshot: str,
    query_hash: str,
    policy: SearchPolicy,
    secret: bytes,
    *,
    scope: EvidenceScope | None = None,
) -> int:
    try:
        payload = _SignedCursorCodec.decode(cursor, secret)
        if payload["snapshot"] != snapshot:
            raise StaleCursor("cursor belongs to a different index snapshot")
        if payload["query"] != query_hash:
            raise StaleCursor("cursor belongs to a different structured query")
        if payload["policy"] != canonical_hash(policy):
            raise StaleCursor("cursor belongs to a different search policy")
        if payload.get("scope") != (canonical_hash(scope) if scope is not None else None):
            raise CursorScopeMismatch("cursor belongs to a different Evidence scope")
        raw_offset = payload["offset"]
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, int):
            raise StaleCursor("search cursor offset is not an integer")
        offset = raw_offset
        if offset < 0:
            raise StaleCursor("search cursor offset cannot be negative")
        return offset
    except RetrievalFailure:
        raise
    except ValueError as error:
        # Preserve authenticated-envelope diagnostics (notably integrity-tag
        # failures) while still presenting them through the typed stale-cursor
        # condition expected by retrieval callers.
        raise StaleCursor(str(error)) from error
    except (KeyError, TypeError) as error:
        raise StaleCursor("invalid search cursor") from error
