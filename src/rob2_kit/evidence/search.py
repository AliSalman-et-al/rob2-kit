"""Canonical evidence units and deterministic, snapshot-bound FTS5 search."""

from __future__ import annotations

import itertools
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.domain.evidence import ReviewedEvidenceContext, ReviewedEvidenceFragment
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.errors import (
    CursorScopeMismatch,
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    ReprocessingRequired,
    RetrievalFailure,
    ScopeMismatch,
    StaleCursor,
    UnknownCursor,
)

PROJECTION_TARGET = 2_400
CONTEXT_CHARACTER_TARGET = 16_000
CONTEXT_NEIGHBOR_LIMIT = 6
CONTEXT_UNIT_LIMIT = 6
# Bumped from 1.1.0: fragment-merge now rejoins PDF line-wrap hyphens
# (see ADR-0013/ADR-0014), changing merged CanonicalEvidenceUnit text and
# fragment_spans for affected units.
CANONICALIZATION_VERSION = "canonicalization:1.3.0"
RETRIEVAL_SCHEMA_VERSION = "retrieval-schema:1.0.0"
EVIDENCE_INDEX_SCHEMA_VERSION = "evidence-index-schema:1.0.0"
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


class ReadContextMode(StrEnum):
    UNIT = "unit"
    NEIGHBORS = "neighbors"
    SECTION = "section"


def _same_context_structure(
    candidate: CanonicalEvidenceUnit, target: CanonicalEvidenceUnit
) -> bool:
    """Require identical parser structure and table identity.

    Zone and Trial-discourse classifications are semantic diagnostics, not
    parser-authored mechanical section boundaries.  Context may cross them,
    with the crossing reported to the caller.
    """
    return (
        candidate.section_path == target.section_path
        and candidate.hierarchy_path == target.hierarchy_path
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


class CanonicalFragmentSpan(FrozenModel):
    """An exact parser-fragment range retained in canonical-unit coordinates.

    Normally a span's canonical extent equals its source-fragment extent
    (pure preservation).  A zero-width canonical extent instead records that
    the source range produced no canonical text at all -- for example a
    PDF line-wrap hyphen character deleted while dehyphenating a merged
    fragment.  Every source character stays attributable to a canonical
    position, even a "produced nothing" one, rather than silently dropped
    from the mapping.
    """

    fragment_id: Identifier
    fragment_start: int = Field(ge=0)
    fragment_end: int = Field(gt=0)
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_mapping(self) -> CanonicalFragmentSpan:
        if self.fragment_end <= self.fragment_start:
            raise ValueError("fragment span must have positive extent")
        if self.canonical_end < self.canonical_start:
            raise ValueError("canonical fragment span cannot end before it starts")
        fragment_extent = self.fragment_end - self.fragment_start
        canonical_extent = self.canonical_end - self.canonical_start
        if canonical_extent not in (0, fragment_extent):
            raise ValueError("canonical extent must equal the fragment extent or be zero (deleted)")
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
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: SourceRole | None = None
    document_zone: DocumentZone | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    duplicate_group_id: Identifier | None = None
    # Parser fragment identity is retained even when a later conservative
    # canonicalization combines source-authored fragments.  It is lineage, not
    # a semantic assertion, and therefore remains available for uncertain
    # material as well as citable units.
    fragment_ids: tuple[Identifier, ...] = ()
    fragment_spans: tuple[CanonicalFragmentSpan, ...] = ()
    canonicalization_version: str = CANONICALIZATION_VERSION
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
        if self.fragment_spans:
            # A fragment may be split into consecutive spans (e.g. its
            # preserved text plus a zero-width deletion span for a stripped
            # hyphen), so dedupe consecutive repeats before comparing identity
            # order against fragment_ids.
            deduped_span_ids = tuple(
                fragment_id
                for fragment_id, _ in itertools.groupby(
                    span.fragment_id for span in self.fragment_spans
                )
            )
            if deduped_span_ids != self.fragment_ids:
                raise ValueError("fragment spans must match canonical fragment identity order")
            for span in self.fragment_spans:
                if span.canonical_end > len(self.text):
                    raise ValueError("fragment span exceeds canonical unit text")
        return self


class CanonicalBlock(FrozenModel):
    kind: CanonicalUnitKind
    text: str = Field(min_length=1)
    spatial: tuple[float, float, float, float]
    word_boxes: tuple[CanonicalWordBox, ...] = ()
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    source_role: SourceRole | None = None
    document_zone: DocumentZone | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    duplicate_group_id: Identifier | None = None
    fragment_ids: tuple[Identifier, ...] = ()
    fragment_spans: tuple[CanonicalFragmentSpan, ...] = ()
    warnings: tuple[str, ...] = ()


class CanonicalPage(FrozenModel):
    page: int = Field(ge=1)
    blocks: tuple[CanonicalBlock, ...]


def _block_order(block: CanonicalBlock) -> tuple[object, ...]:
    """Use parser reading order when present, with geometry as a stable fallback."""

    left, top, _, _ = block.spatial
    return (
        0 if block.reading_order else 1,
        block.reading_order,
        top,
        left,
        block.fragment_ids,
        block.text,
    )


def _hyphen_rejoin_boundary(previous: CanonicalBlock, candidate: CanonicalBlock) -> bool:
    """Recognize a PDF line-wrap hyphen split ("balanced be-" + "tween").

    Deliberately no dictionary or heuristic check for genuine hyphenated
    compounds ("well-being") landing on a line break -- see ADR-0013.  Any
    trailing ASCII hyphen after a letter, immediately followed by another
    letter on the next line-wrap-consecutive fragment, is treated as a split
    word rather than punctuation, a numeric range, or an em/en dash.
    """

    previous_text = previous.text
    candidate_text = candidate.text
    return (
        len(previous_text) >= 2
        and previous_text[-1] == "-"
        and previous_text[-2].isalpha()
        and bool(candidate_text)
        and candidate_text[0].isalpha()
    )


def _mergeable_fragments(previous: CanonicalBlock, candidate: CanonicalBlock) -> bool:
    """Recognize only consecutive, single-column parser fragments.

    This intentionally modest rule avoids turning ordinary nearby paragraphs or
    ambiguous multi-column extraction into invented prose.  A trailing
    line-wrap hyphen is the one exception to the whitespace-boundary
    requirement, since a hyphenated split word never has whitespace on
    either side of the break.
    """

    whitespace_boundary = previous.text[-1].isspace() or candidate.text[0].isspace()
    if (
        previous.kind is CanonicalUnitKind.UNCLASSIFIED
        or candidate.kind is not previous.kind
        or not previous.reading_order
        or candidate.reading_order != previous.reading_order + 1
        or "reading_order_uncertain" in previous.warnings
        or "reading_order_uncertain" in candidate.warnings
        or not (whitespace_boundary or _hyphen_rejoin_boundary(previous, candidate))
    ):
        return False
    if any(
        getattr(previous, field) != getattr(candidate, field)
        for field in (
            "table_headers",
            "caption",
            "section_path",
            "hierarchy_path",
            "source_role",
            "document_zone",
            "duplicate_group_id",
        )
    ):
        return False
    left, _, right, bottom = previous.spatial
    candidate_left, candidate_top, candidate_right, _ = candidate.spatial
    line_height = bottom - previous.spatial[1]
    return (
        abs(left - candidate_left) <= 5
        and abs(right - candidate_right) <= 5
        and 0 <= candidate_top - bottom <= max(24, line_height * 2)
    )


def _drop_trailing_hyphen_word_box(
    word_boxes: tuple[CanonicalWordBox, ...], original_text_length: int
) -> tuple[CanonicalWordBox, ...]:
    """Trim or drop the word box covering a stripped trailing hyphen."""

    if not word_boxes:
        return word_boxes
    last = word_boxes[-1]
    if last.span_end != original_text_length:
        return word_boxes
    if last.text == "-":
        return word_boxes[:-1]
    if last.text.endswith("-"):
        return word_boxes[:-1] + (
            last.model_copy(update={"text": last.text[:-1], "span_end": last.span_end - 1}),
        )
    return word_boxes


def _drop_trailing_hyphen_fragment_span(
    spans: tuple[CanonicalFragmentSpan, ...], original_text_length: int
) -> tuple[CanonicalFragmentSpan, ...]:
    """Shrink the trailing fragment span by one character (the deleted hyphen).

    The hyphen's own source position keeps a zero-width canonical mapping
    (ADR-0014) rather than being silently dropped from the fragment lineage.
    """

    if not spans:
        return spans
    last = spans[-1]
    if last.canonical_end != original_text_length:
        return spans
    if last.canonical_end - last.canonical_start == 1:
        return spans[:-1] + (last.model_copy(update={"canonical_end": last.canonical_start}),)
    shrunk_canonical_end = last.canonical_end - 1
    shrunk_fragment_end = last.fragment_end - 1
    return spans[:-1] + (
        last.model_copy(
            update={"fragment_end": shrunk_fragment_end, "canonical_end": shrunk_canonical_end}
        ),
        CanonicalFragmentSpan(
            fragment_id=last.fragment_id,
            fragment_start=shrunk_fragment_end,
            fragment_end=last.fragment_end,
            canonical_start=shrunk_canonical_end,
            canonical_end=shrunk_canonical_end,
        ),
    )


def _merged_block(previous: CanonicalBlock, candidate: CanonicalBlock) -> CanonicalBlock:
    """Combine two already-proven adjacent fragments.

    A trailing PDF line-wrap hyphen is stripped when rejoining ("balanced
    be-" + "tween" -> "balanced between"); see ADR-0013.  The deleted hyphen
    character's fragment lineage is preserved as a zero-width canonical span
    rather than dropped, per ADR-0014.
    """

    strip_hyphen = _hyphen_rejoin_boundary(previous, candidate)
    original_length = len(previous.text)
    previous_text = previous.text[:-1] if strip_hyphen else previous.text
    offset = len(previous_text)

    previous_word_boxes = previous.word_boxes
    previous_spans = _block_fragment_spans(previous)
    if strip_hyphen:
        previous_word_boxes = _drop_trailing_hyphen_word_box(previous_word_boxes, original_length)
        previous_spans = _drop_trailing_hyphen_fragment_span(previous_spans, original_length)

    return previous.model_copy(
        update={
            "text": previous_text + candidate.text,
            "spatial": (
                min(previous.spatial[0], candidate.spatial[0]),
                min(previous.spatial[1], candidate.spatial[1]),
                max(previous.spatial[2], candidate.spatial[2]),
                max(previous.spatial[3], candidate.spatial[3]),
            ),
            "word_boxes": previous_word_boxes
            + tuple(
                box.model_copy(
                    update={
                        "span_start": box.span_start + offset,
                        "span_end": box.span_end + offset,
                    }
                )
                for box in candidate.word_boxes
            ),
            "fragment_ids": previous.fragment_ids + candidate.fragment_ids,
            "fragment_spans": previous_spans
            + tuple(
                span.model_copy(
                    update={
                        "canonical_start": span.canonical_start + offset,
                        "canonical_end": span.canonical_end + offset,
                    }
                )
                for span in _block_fragment_spans(candidate)
            ),
            "warnings": tuple(dict.fromkeys(previous.warnings + candidate.warnings)),
        }
    )


def _canonical_page_blocks(page: CanonicalPage) -> tuple[CanonicalBlock, ...]:
    """Merge only unambiguous parser fragments in deterministic page order."""

    blocks: list[CanonicalBlock] = []
    for block in sorted(page.blocks, key=_block_order):
        if blocks and _mergeable_fragments(blocks[-1], block):
            blocks[-1] = _merged_block(blocks[-1], block)
        else:
            blocks.append(block)
    return tuple(blocks)


def _block_fragment_spans(block: CanonicalBlock) -> tuple[CanonicalFragmentSpan, ...]:
    if block.fragment_spans:
        return block.fragment_spans
    return tuple(
        CanonicalFragmentSpan(
            fragment_id=fragment_id,
            fragment_start=0,
            fragment_end=len(block.text),
            canonical_start=0,
            canonical_end=len(block.text),
        )
        for fragment_id in block.fragment_ids
    )


def _with_fragment_identity(
    block: CanonicalBlock,
    *,
    source_artifact_hash: ContentHash,
    parse_id: Identifier,
    page: int,
) -> CanonicalBlock:
    """Give parser-id-less blocks deterministic lineage before any merge."""

    if block.fragment_ids:
        return block
    fragment_id = "fragment:" + canonical_hash(
        {
            "source_artifact_hash": source_artifact_hash,
            "parse_id": parse_id,
            "page": page,
            "text": block.text,
            "spatial": block.spatial,
        }
    ).removeprefix("sha256:")
    return block.model_copy(update={"fragment_ids": (fragment_id,)})


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
        identified_page = CanonicalPage(
            page=page.page,
            blocks=tuple(
                _with_fragment_identity(
                    block,
                    source_artifact_hash=source_artifact_hash,
                    parse_id=parse_id,
                    page=page.page,
                )
                for block in page.blocks
            ),
        )
        for block in _canonical_page_blocks(identified_page):
            fragment_ids = block.fragment_ids
            unit_identity = canonical_hash(
                {
                    "source_artifact_hash": source_artifact_hash,
                    "parse_id": parse_id,
                    "page": page.page,
                    "fragment_ids": fragment_ids,
                    "text": block.text,
                    "spatial": block.spatial,
                    "canonicalization_version": CANONICALIZATION_VERSION,
                }
            ).removeprefix("sha256:")
            units.append(
                CanonicalEvidenceUnit(
                    unit_id=f"unit:{source_slug}-{unit_identity}",
                    source_id=source_id,
                    source_artifact_hash=source_artifact_hash,
                    parse_id=parse_id,
                    page=page.page,
                    kind=block.kind,
                    text=block.text,
                    spatial=block.spatial,
                    word_boxes=block.word_boxes,
                    table_headers=block.table_headers,
                    caption=block.caption,
                    section_path=block.section_path,
                    hierarchy_path=block.hierarchy_path,
                    reading_order=block.reading_order or len(units),
                    source_role=block.source_role,
                    document_zone=block.document_zone,
                    duplicate_group_id=block.duplicate_group_id,
                    fragment_ids=fragment_ids,
                    fragment_spans=_block_fragment_spans(
                        block.model_copy(update={"fragment_ids": fragment_ids})
                    ),
                    canonicalization_version=CANONICALIZATION_VERSION,
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
        description=(
            "Lexical tokens; every term must match (AND). For alternatives, use a single "
            "any_of group instead."
        ),
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
        description=(
            "AND-of-ORs Boolean groups: every group must match (AND across groups); within a "
            "group, any one listed token satisfies it (OR within group). For 'any of these "
            "words' semantics, put every alternative in one group."
        ),
        examples=[[["sealed", "central", "opaque"]]],
    )
    source_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=64,
        description="Source IDs issued by get_work_context.",
    )
    pages: tuple[int, ...] = Field(
        default=(),
        max_length=128,
        description="One-based source page numbers.",
        examples=[[1, 2]],
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
        return self


class EvidenceScope(FrozenModel):
    """Engine-issued scope applied before lexical ranking."""

    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_id: Identifier | None = None
    source_ids: tuple[Identifier, ...] = ()
    work_token_id: Identifier | None = None


class SearchPolicy(FrozenModel):
    policy_id: Identifier = "policy:evidence-search-1.1.0"
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
    location_handle: str = Field(min_length=1)


class QueryPreview(FrozenModel):
    unique_hit_count: int
    scoped_unit_count: int
    source_distribution: tuple[tuple[Identifier, int], ...]
    requires_broad_query_justification: bool
    malformed_query_hints: tuple[str, ...] = ()


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
    malformed_query_hints: tuple[str, ...] = ()

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
            self.unit.page,
        )
        if any(
            (item.source_id, item.source_artifact_hash, item.parse_id, item.page) != provenance
            for item in self.neighbors
        ):
            raise ValueError("context neighbors must preserve source, Parse, and page provenance")
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
                for item in self.neighbors
            ):
                raise ValueError("section context cannot cross hierarchy boundaries")
        if self.mode in {ReadContextMode.NEIGHBORS, ReadContextMode.SECTION}:
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


class EvidenceRead(FrozenModel):
    """One bounded, source-authored character window resolved from a handle."""

    snapshot_hash: ContentHash
    unit: CanonicalEvidenceUnit
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    character_target: int = Field(ge=1, le=CONTEXT_CHARACTER_TARGET)
    continuation_cursor: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_window(self) -> EvidenceRead:
        if self.end < self.start or self.text != self.unit.text[self.start : self.end]:
            raise ValueError("read text must be the exact source-authored unit window")
        return self


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

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        """Create the current physical schema in a newly materialized database.

        Schema changes intentionally never mutate an existing derived index:
        callers must fully re-canonicalize first, then swap this ready database
        into place atomically.
        """
        connection.executescript(
            """
            CREATE TABLE evidence_units (
                unit_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_artifact_hash TEXT NOT NULL,
                parse_id TEXT NOT NULL,
                page INTEGER NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                spatial TEXT,
                word_boxes TEXT,
                section_path TEXT,
                hierarchy_path TEXT,
                reading_order INTEGER NOT NULL DEFAULT 0,
                source_role TEXT,
                document_zone TEXT,
                table_headers TEXT,
                caption TEXT,
                duplicate_group_id TEXT,
                fragment_ids TEXT,
                fragment_spans TEXT,
                canonicalization_version TEXT NOT NULL,
                warnings TEXT
            );
            CREATE TABLE evidence_snapshot (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                content_hash TEXT NOT NULL,
                retrieval_schema_version TEXT NOT NULL,
                index_schema_version TEXT NOT NULL
            );
            CREATE TABLE evidence_cursor_token (
                token TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE evidence_fts USING fts5(
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
            raise InvalidRetrievalRequest("canonical unit IDs must be unique", field="units")
        snapshot = canonical_hash(
            {
                "units": [item.model_dump(mode="json") for item in ordered],
                "retrieval_schema_version": RETRIEVAL_SCHEMA_VERSION,
                "index_schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
            }
        )
        replacement = self.path.with_name(f"{self.path.name}.{secrets.token_hex(12)}.next")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(replacement)
            connection.row_factory = sqlite3.Row
            self._create_schema(connection)
            for item in ordered:
                connection.execute(
                    "INSERT INTO evidence_units "
                    "(unit_id, source_id, source_artifact_hash, parse_id, page, kind, text, "
                    "spatial, word_boxes, section_path, hierarchy_path, reading_order, "
                    "source_role, document_zone, table_headers, "
                    "caption, duplicate_group_id, fragment_ids, canonicalization_version, "
                    "fragment_spans, warnings) "
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
                        json.dumps(item.section_path),
                        json.dumps(item.hierarchy_path),
                        item.reading_order,
                        item.source_role,
                        item.document_zone.value if item.document_zone else None,
                        json.dumps(item.table_headers),
                        item.caption,
                        item.duplicate_group_id,
                        json.dumps(item.fragment_ids),
                        item.canonicalization_version,
                        json.dumps([span.model_dump(mode="json") for span in item.fragment_spans]),
                        json.dumps(item.warnings),
                    ),
                )
                for projection in _project(item):
                    connection.execute(
                        "INSERT INTO evidence_fts(projection_id, unit_id, text) VALUES (?, ?, ?)",
                        (projection.projection_id, item.unit_id, projection.text),
                    )
            # Retain issued lookup tokens solely so a caller receives the
            # precise stale-snapshot failure after a replacement. They carry
            # no indexed content and cannot resolve against the new snapshot.
            if self.path.exists():
                try:
                    previous = sqlite3.connect(self.path)
                    try:
                        rows = previous.execute(
                            "SELECT token, kind, payload FROM evidence_cursor_token"
                        ).fetchall()
                    finally:
                        previous.close()
                    connection.executemany(
                        "INSERT OR IGNORE INTO evidence_cursor_token(token, kind, payload) "
                        "VALUES (?, ?, ?)",
                        rows,
                    )
                except sqlite3.Error:
                    # A legacy/partial index has no transferable token state;
                    # its opaque values remain fail-closed as unknown.
                    pass
            connection.execute(
                """
                INSERT INTO evidence_snapshot(
                    singleton, content_hash, retrieval_schema_version, index_schema_version
                ) VALUES (1, ?, ?, ?)
                """,
                (snapshot, RETRIEVAL_SCHEMA_VERSION, EVIDENCE_INDEX_SCHEMA_VERSION),
            )
            connection.commit()
            connection.close()
            connection = None
            # A complete committed replacement is the only point at which the
            # prior index is replaced.  If construction fails it remains intact.
            os.replace(replacement, self.path)
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            replacement.unlink(missing_ok=True)
            raise
        return snapshot

    def preview(
        self,
        query: SearchQuery,
        *,
        policy: SearchPolicy | None = None,
        scope: EvidenceScope | None = None,
    ) -> QueryPreview:
        policy = policy or SearchPolicy()
        self._snapshot()
        rows, scoped_count, excluded_count = self._matches(query, scope=scope)
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
            malformed_query_hints=(
                _malformed_query_hints(query) if unique_count == 0 and excluded_count == 0 else ()
            ),
        )

    def read_unit(
        self,
        unit_id: Identifier,
        *,
        scope: EvidenceScope | None = None,
    ) -> CanonicalEvidenceUnit:
        """Read one engine-issued canonical unit without accepting raw source locators."""
        self._snapshot()
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

    def read_location(
        self,
        location_handle: str,
        *,
        character_target: int = CONTEXT_CHARACTER_TARGET,
        cursor: str | None = None,
        scope: EvidenceScope | None = None,
    ) -> EvidenceRead:
        """Dereference an opaque, snapshot-bound location in a bounded window.

        Handles deliberately contain no caller-controlled path or ordinal.  A
        changed artifact, Parse, canonicalization, or index snapshot makes the
        handle stale; index ranking alone does not alter the bound unit.
        """
        if not 1 <= character_target <= CONTEXT_CHARACTER_TARGET:
            raise InvalidRetrievalRequest(
                f"character_target must be between 1 and {CONTEXT_CHARACTER_TARGET}",
                field="character_target",
            )
        snapshot = self._snapshot()
        try:
            payload = self._resolve_token("loc", location_handle)
        except UnknownCursor:
            raise UnknownCursor(
                "invalid evidence location handle", field="location_handle"
            ) from None
        if payload.get("snapshot") != snapshot:
            raise StaleCursor("evidence location handle is stale", field="location_handle")
        unit_id = payload.get("unit")
        if not isinstance(unit_id, str):
            raise StaleCursor("invalid evidence location handle", field="location_handle")
        unit = self.read_unit(unit_id, scope=scope)
        if any(
            payload.get(key) != value
            for key, value in (
                ("source_artifact_hash", unit.source_artifact_hash),
                ("parse_id", unit.parse_id),
                ("canonicalization_version", unit.canonicalization_version),
                ("fragment_ids", list(unit.fragment_ids)),
            )
        ):
            raise StaleCursor("evidence location handle is stale", field="location_handle")
        start = (
            self._decode_read_cursor(cursor, snapshot, unit.unit_id, scope=scope) if cursor else 0
        )
        if start >= len(unit.text):
            raise StaleCursor("read continuation cursor is outside the unit", field="cursor")
        end = min(start + character_target, len(unit.text))
        return EvidenceRead(
            snapshot_hash=snapshot,
            unit=unit,
            text=unit.text[start:end],
            start=start,
            end=end,
            character_target=character_target,
            continuation_cursor=(
                self._encode_read_cursor(snapshot, unit.unit_id, end, scope=scope)
                if end < len(unit.text)
                else None
            ),
            warnings=unit.warnings,
        )

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
                "WHERE source_id = ? AND source_artifact_hash = ? AND parse_id = ? AND page = ? "
                "ORDER BY page ASC, unit_id ASC",
                (target.source_id, target.source_artifact_hash, target.parse_id, target.page),
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
                self._decode_read_cursor(
                    cursor,
                    snapshot,
                    unit_id,
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
                # No candidate was ever considered here, so the omitted
                # count must not claim same-page siblings were filtered.
                section_boundary_reached = len(source_ids) > 1
                source_ids = [unit_id]
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
                warnings=target.warnings + boundary_warnings,
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
        semantic_crossing_warnings = tuple(
            warning
            for warning, crossed in (
                (
                    "document_zone_boundary_crossed",
                    any(item.document_zone != target.document_zone for item in selected),
                ),
            )
            if crossed
        )
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
                self._encode_read_cursor(
                    snapshot,
                    target.unit_id,
                    next_offset,
                    scope=scope,
                )
                if mode is ReadContextMode.SECTION and next_offset < len(candidate_ids) + offset
                else None
            ),
            warnings=target.warnings
            + boundary_warnings
            + semantic_crossing_warnings
            + (("oversized_neighbor_skipped",) if oversized_neighbor_skipped else ()),
            visual_inspection_available=(target.spatial is not None),
        )

    def unit_ids(self) -> frozenset[Identifier]:
        """Return the stable engine-issued unit identities in the current snapshot."""
        self._snapshot()
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
            self._decode_cursor(
                cursor,
                snapshot,
                query_hash,
                policy,
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
            self._encode_cursor(
                snapshot,
                query_hash,
                policy,
                consumed,
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
        if excluded_count:
            warning_values.append("retrieval_scope_excluded_matches")
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
        malformed_hints = _malformed_query_hints(query) if not rows and excluded_count == 0 else ()
        preview = QueryPreview(
            unique_hit_count=len(rows),
            scoped_unit_count=scoped_count,
            source_distribution=tuple(sorted(source_counts.items())),
            requires_broad_query_justification=is_broad,
            malformed_query_hints=malformed_hints,
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
                        else ("refine the plain-language need", *malformed_hints)
                    )
                )
            ),
            scope_warnings=scope_warnings,
            malformed_query_hints=malformed_hints,
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
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT content_hash, retrieval_schema_version, index_schema_version "
                    "FROM evidence_snapshot WHERE singleton = 1"
                ).fetchone()
        except sqlite3.Error as error:
            raise ReprocessingRequired(
                "evidence index cannot prove its current retrieval schema identity"
            ) from error
        if row is None:
            raise ReprocessingRequired("evidence index has no current-schema snapshot")
        if (
            row["retrieval_schema_version"] != RETRIEVAL_SCHEMA_VERSION
            or row["index_schema_version"] != EVIDENCE_INDEX_SCHEMA_VERSION
        ):
            raise ReprocessingRequired(
                "evidence index schema is retired; current Source/Parse reprocessing is required"
            )
        return row[0]

    def _hit(self, row: sqlite3.Row, *, oversized: bool = False) -> SearchHit:
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
                (f"document_zone:{unit.document_zone.value}",)
                if unit.document_zone is not None
                else ("document_zone:unclassified",)
            ),
            duplicate_group_id=unit.duplicate_group_id,
            location_handle=self._encode_location_handle(unit, self._snapshot()),
        )

    def _issue_token(self, kind: str, payload: dict[str, object]) -> str:
        with self._connect() as connection:
            return _LookupTokenCodec.encode(connection, kind, payload)

    def _issue_stable_token(self, kind: str, payload: dict[str, object]) -> str:
        """Persist one collision-checked opaque lookup token per exact payload.

        Read-view receipts become durable review-submission inputs.  Their
        identity must therefore converge when an interrupted qualification
        journey reissues the exact same displayed view; a random lookup token
        would otherwise leak process history into immutable Evidence records.
        """

        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        token = f"{kind}:{canonical_hash(payload).removeprefix('sha256:')}"
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO evidence_cursor_token(token, kind, payload) VALUES (?, ?, ?)",
                (token, kind, encoded),
            )
            existing = connection.execute(
                "SELECT kind, payload FROM evidence_cursor_token WHERE token = ?", (token,)
            ).fetchone()
            if existing is None or existing["kind"] != kind or existing["payload"] != encoded:
                raise OperationalRetrievalFailure(
                    "read-view receipt identity collision in the evidence index"
                )
        return token

    def _resolve_token(self, kind: str, token: str) -> dict[str, object]:
        with self._connect() as connection:
            return _LookupTokenCodec.decode(connection, kind, token)

    def issue_read_view_receipt(
        self,
        *,
        snapshot_hash: ContentHash,
        requested_mode: ReadContextMode,
        applied_mode: ReadContextMode,
        continuation_input: str | None,
        continuation: str | None,
        fragments: tuple[ReviewedEvidenceFragment, ...],
        displayed_units: tuple[CanonicalEvidenceUnit, ...],
    ) -> str:
        """Persist an opaque, exact read-view receipt for later review binding.

        The receipt is deliberately a lookup token rather than a caller-owned
        descriptor.  Its payload retains all units actually displayed and the
        source/Parse/canonical lineage needed to reject a changed snapshot.
        """
        current_snapshot = self._snapshot()
        if snapshot_hash != current_snapshot:
            raise StaleCursor("read-view receipt snapshot is stale", field="snapshot_hash")
        by_id = {unit.unit_id: unit for unit in displayed_units}
        if len(by_id) != len(displayed_units) or set(by_id) != {
            fragment.unit_id for fragment in fragments
        }:
            raise InvalidRetrievalRequest(
                "read-view fragments must exactly describe displayed canonical units",
                field="read_view_receipt",
            )
        payload = {
            "snapshot_hash": snapshot_hash,
            "requested_mode": requested_mode.value,
            "applied_mode": applied_mode.value,
            "continuation_input": continuation_input,
            "continuation": continuation,
            "fragments": [fragment.model_dump(mode="json") for fragment in fragments],
            "lineage": [
                {
                    "unit_id": unit.unit_id,
                    "source_id": unit.source_id,
                    "source_artifact_hash": unit.source_artifact_hash,
                    "parse_id": unit.parse_id,
                    "canonicalization_version": unit.canonicalization_version,
                    "unit_content_hash": sha256_digest(unit.text.encode()),
                }
                for unit in displayed_units
            ],
        }
        return self._issue_stable_token("read-view", payload)

    def resolve_read_view_receipt(
        self,
        receipt: str,
        *,
        scope: EvidenceScope | None = None,
    ) -> ReviewedEvidenceContext:
        """Resolve and revalidate an opaque receipt against this exact index.

        An issued receipt whose snapshot or lineage changed is stale and must
        be recreated by a fresh search/read.  An unknown or corrupt token is
        intentionally distinguishable from that recoverable stale condition.
        """
        try:
            payload = self._resolve_token("read-view", receipt)
        except UnknownCursor:
            raise UnknownCursor(
                "invalid evidence read-view receipt", field="read_view_receipt"
            ) from None
        try:
            snapshot_hash = payload["snapshot_hash"]
            requested_mode = payload["requested_mode"]
            applied_mode = payload["applied_mode"]
            raw_fragments = payload["fragments"]
            raw_lineage = payload["lineage"]
            continuation_input = payload.get("continuation_input")
            continuation = payload.get("continuation")
            if (
                not isinstance(snapshot_hash, str)
                or not isinstance(requested_mode, str)
                or not isinstance(applied_mode, str)
                or not isinstance(raw_fragments, list)
                or not isinstance(raw_lineage, list)
                or not isinstance(continuation_input, (str, type(None)))
                or not isinstance(continuation, (str, type(None)))
            ):
                raise ValueError("receipt payload has invalid field types")
            ReadContextMode(requested_mode)
            ReadContextMode(applied_mode)
            fragments = tuple(
                ReviewedEvidenceFragment.model_validate(item) for item in raw_fragments
            )
            if not fragments or len({fragment.unit_id for fragment in fragments}) != len(fragments):
                raise ValueError("receipt fragments are empty or duplicate")
            lineage_by_unit = {
                str(item["unit_id"]): item
                for item in raw_lineage
                if isinstance(item, dict) and isinstance(item.get("unit_id"), str)
            }
            if len(lineage_by_unit) != len(raw_lineage) or set(lineage_by_unit) != {
                fragment.unit_id for fragment in fragments
            }:
                raise ValueError("receipt lineage does not exactly match fragments")
        except (KeyError, TypeError, ValueError):
            raise UnknownCursor(
                "malformed evidence read-view receipt", field="read_view_receipt"
            ) from None
        if snapshot_hash != self._snapshot():
            raise StaleCursor(
                "evidence read-view receipt is stale; rerun search and read",
                field="read_view_receipt",
                recovery=("rerun search_evidence", "rerun read_evidence"),
            )
        for fragment in fragments:
            try:
                unit = self.read_unit(fragment.unit_id, scope=scope)
            except (InvalidRetrievalRequest, ScopeMismatch) as error:
                raise StaleCursor(
                    "evidence read-view receipt no longer resolves; rerun search and read",
                    field="read_view_receipt",
                    recovery=("rerun search_evidence", "rerun read_evidence"),
                ) from error
            lineage = lineage_by_unit[fragment.unit_id]
            if (
                any(
                    lineage.get(key) != value
                    for key, value in (
                        ("source_id", unit.source_id),
                        ("source_artifact_hash", unit.source_artifact_hash),
                        ("parse_id", unit.parse_id),
                        ("canonicalization_version", unit.canonicalization_version),
                        ("unit_content_hash", sha256_digest(unit.text.encode())),
                    )
                )
                or fragment.span_end > len(unit.text)
                or fragment.content_hash
                != sha256_digest(unit.text[fragment.span_start : fragment.span_end].encode())
            ):
                raise StaleCursor(
                    "evidence read-view receipt lineage changed; rerun search and read",
                    field="read_view_receipt",
                    recovery=("rerun search_evidence", "rerun read_evidence"),
                )
        frozen_fragments = tuple(
            ReviewedEvidenceFragment(
                unit_id=fragment.unit_id,
                source_id=str(lineage_by_unit[fragment.unit_id]["source_id"]),
                source_artifact_hash=str(lineage_by_unit[fragment.unit_id]["source_artifact_hash"]),
                parse_id=str(lineage_by_unit[fragment.unit_id]["parse_id"]),
                canonicalization_version=str(
                    lineage_by_unit[fragment.unit_id]["canonicalization_version"]
                ),
                unit_content_hash=str(lineage_by_unit[fragment.unit_id]["unit_content_hash"]),
                span_start=fragment.span_start,
                span_end=fragment.span_end,
                content_hash=fragment.content_hash,
            )
            for fragment in fragments
        )
        return ReviewedEvidenceContext(
            receipt_hash=canonical_hash(payload),
            snapshot_hash=snapshot_hash,
            requested_mode=requested_mode,
            applied_mode=applied_mode,
            continuation_input=continuation_input,
            continuation=continuation,
            fragments=frozen_fragments,
        )

    def _encode_location_handle(self, unit: CanonicalEvidenceUnit, snapshot: ContentHash) -> str:
        """Issue an opaque handle bound to the exact source/Parse lineage."""
        return self._issue_token(
            "loc",
            {
                "snapshot": snapshot,
                "unit": unit.unit_id,
                "source_artifact_hash": unit.source_artifact_hash,
                "parse_id": unit.parse_id,
                "fragment_ids": list(unit.fragment_ids),
                "canonicalization_version": unit.canonicalization_version,
            },
        )

    def _encode_cursor(
        self,
        snapshot: str,
        query_hash: str,
        policy: SearchPolicy,
        offset: int,
        *,
        scope: EvidenceScope | None = None,
    ) -> str:
        return self._issue_token(
            "cur",
            {
                "snapshot": snapshot,
                "query": query_hash,
                "policy": canonical_hash(policy),
                "offset": offset,
                "scope": canonical_hash(scope) if scope is not None else None,
            },
        )

    def _decode_cursor(
        self,
        cursor: str,
        snapshot: str,
        query_hash: str,
        policy: SearchPolicy,
        *,
        scope: EvidenceScope | None = None,
    ) -> int:
        payload = self._resolve_token("cur", cursor)
        if payload.get("snapshot") != snapshot:
            raise StaleCursor("cursor belongs to a different index snapshot")
        if payload.get("query") != query_hash:
            raise StaleCursor("cursor belongs to a different structured query")
        if payload.get("policy") != canonical_hash(policy):
            raise StaleCursor("cursor belongs to a different search policy")
        if payload.get("scope") != (canonical_hash(scope) if scope is not None else None):
            raise CursorScopeMismatch("cursor belongs to a different Evidence scope")
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise StaleCursor("search cursor offset is invalid")
        return offset

    def _encode_read_cursor(
        self,
        snapshot: str,
        unit_id: str,
        offset: int,
        *,
        scope: EvidenceScope | None = None,
    ) -> str:
        return self._issue_token(
            "read",
            {
                "snapshot": snapshot,
                "unit": unit_id,
                "offset": offset,
                "scope": canonical_hash(scope) if scope is not None else None,
            },
        )

    def _decode_read_cursor(
        self,
        cursor: str,
        snapshot: str,
        unit_id: str,
        *,
        scope: EvidenceScope | None = None,
    ) -> int:
        payload = self._resolve_token("read", cursor)
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

    @contextmanager
    def _connect(self):
        try:
            connection = sqlite3.connect(self.path)
        except (sqlite3.Error, OSError) as error:
            raise OperationalRetrievalFailure(
                "unable to open the evidence retrieval index"
            ) from error
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()


def _compile_match(query: SearchQuery) -> str:
    clauses = [f'"{term}"' for term in query.terms]
    clauses.extend(f'"{phrase.strip()}"' for phrase in query.phrases)
    clauses.extend(f'"{prefix}"*' for prefix in query.prefixes)
    clauses.extend("(" + " OR ".join(f'"{term}"' for term in group) + ")" for group in query.any_of)
    return " AND ".join(clauses)


def _malformed_query_hints(query: SearchQuery) -> tuple[str, ...]:
    """Flag query shapes that almost certainly meant OR but got AND-of-ORs semantics."""
    hints: list[str] = []
    if len(query.any_of) >= 2 and all(len(group) == 1 for group in query.any_of):
        hints.append(
            "every any_of group has exactly one term, so they were AND'd together, not "
            "treated as alternatives — put every alternative in a single any_of group for "
            "OR semantics"
        )
    if len(query.terms) > 1:
        hints.append(
            "multiple terms are AND'd together, not OR'd — move alternative words into a "
            "single any_of group instead of terms"
        )
    return tuple(hints)


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
        table_headers=tuple(json.loads(row["table_headers"] or "[]")),
        caption=row["caption"],
        section_path=tuple(json.loads(row["section_path"] or "[]")),
        hierarchy_path=tuple(json.loads(row["hierarchy_path"] or "[]")),
        reading_order=row["reading_order"] or 0,
        source_role=(SourceRole(row["source_role"]) if row["source_role"] else None),
        document_zone=row["document_zone"],
        duplicate_group_id=row["duplicate_group_id"],
        fragment_ids=tuple(json.loads(row["fragment_ids"] or "[]")),
        fragment_spans=tuple(
            CanonicalFragmentSpan.model_validate(item)
            for item in json.loads(row["fragment_spans"] or "[]")
        ),
        canonicalization_version=row["canonicalization_version"],
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
        if current is None or (
            row["score"],
            row["reading_order"] or 0,
            row["page"],
            row["unit_id"],
        ) < (
            current["score"],
            current["reading_order"] or 0,
            current["page"],
            current["unit_id"],
        ):
            unique[key] = row
    return sorted(
        unique.values(),
        key=lambda row: (row["score"], row["reading_order"] or 0, row["page"], row["unit_id"]),
    )


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
        if scope.source_ids:
            source_ids = intersect(query.source_ids, scope.source_ids)
            add_in("source_id", source_ids)
        elif query.source_ids:
            add_in("source_id", query.source_ids)
    elif query.source_ids:
        add_in("source_id", query.source_ids)
    # Parser output contributes only structural and provenance fields. Trial,
    # Result, Domain, and signaling-question scope is authorized by WorkTokens
    # and attributable review, never candidate ranking metadata.
    return filters, params


def _unit_in_scope(unit: CanonicalEvidenceUnit, scope: EvidenceScope) -> bool:
    if scope.source_ids and unit.source_id not in scope.source_ids:
        return False
    return True


class _LookupTokenCodec:
    """Shared server-side lookup-table codec for search and read cursors.

    Retired the HMAC-signed self-verifying envelope in favor of a short
    ``kind:``-prefixed token looked up against a local table (ADR-0011).
    This server is the sole issuer and sole verifier of every cursor and
    handle for a run's lifetime, so the cross-process portability an
    authenticated envelope buys is never exercised here -- a lookup gives
    the same tamper-resistance and staleness detection with far less
    machinery and none of the transcription risk of a multi-kilobyte blob.
    """

    @staticmethod
    def encode(connection: sqlite3.Connection, kind: str, payload: dict[str, object]) -> str:
        token = f"{kind}:{secrets.token_urlsafe(16)}"
        connection.execute(
            "INSERT INTO evidence_cursor_token(token, kind, payload) VALUES (?, ?, ?)",
            (token, kind, json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        )
        return token

    @staticmethod
    def decode(connection: sqlite3.Connection, kind: str, token: str) -> dict[str, object]:
        # A lookup miss is distinguished from a stale-but-known row: an
        # unrecognized or wrong-kind token was most likely mistranscribed
        # (or never issued) rather than genuinely superseded (#125/#126).
        if not token.startswith(f"{kind}:"):
            raise UnknownCursor(f"not a recognized {kind} token")
        row = connection.execute(
            "SELECT payload FROM evidence_cursor_token WHERE token = ? AND kind = ?",
            (token, kind),
        ).fetchone()
        if row is None:
            raise UnknownCursor(f"no {kind} token matches this value")
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError as error:
            raise UnknownCursor(f"corrupt {kind} token payload") from error
        if not isinstance(payload, dict):
            raise UnknownCursor(f"corrupt {kind} token payload")
        return payload
