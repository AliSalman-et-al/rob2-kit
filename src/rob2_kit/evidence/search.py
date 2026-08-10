"""Canonical evidence units and deterministic, snapshot-bound FTS5 search."""

from __future__ import annotations

import itertools
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes, sha256_digest
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
    SearchPolicyMismatch,
    StaleCursor,
    StaleSearchContinuation,
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
EVIDENCE_SEARCH_POLICY_ID = "policy:evidence-search-2.0.0"
EVIDENCE_READ_POLICY_ID = "policy:evidence-read-2.0.0"
EVIDENCE_SEARCH_ESTIMATOR_ID = "estimator:serialized-utf8-ceil-bytes-div-4:1.0.0"
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


class EvidenceSearchPolicy(FrozenModel):
    """Engine-owned bounds for the v2 lightweight candidate page.

    ``serialized_response_bytes`` is measured from ``canonical_json_bytes`` of
    the model-facing compact page projection.  ``estimated_response_tokens`` is consequently
    always ``ceil(bytes / 4)``: a stable provider-neutral proxy, not a claim
    about any provider tokenizer.
    """

    policy_id: Identifier = EVIDENCE_SEARCH_POLICY_ID
    estimator_id: Identifier = EVIDENCE_SEARCH_ESTIMATOR_ID
    estimated_token_target: int = Field(default=1_800, ge=1)
    serialized_byte_ceiling: int = Field(default=10_000, ge=1)
    candidate_ceiling: int = Field(default=12, ge=1)
    oversized_candidate_byte_ceiling: int = Field(default=16_000, ge=1)
    snippet_character_target: int = Field(default=480, ge=1, le=2_400)
    high_cost_page_threshold: int = Field(default=4, ge=1)
    high_cost_estimated_token_threshold: int = Field(default=6_500, ge=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> EvidenceSearchPolicy:
        if self.oversized_candidate_byte_ceiling < self.serialized_byte_ceiling:
            raise ValueError("oversized candidate ceiling cannot be below page byte ceiling")
        return self


class EvidenceReadPolicy(FrozenModel):
    """Engine-owned limits for one v2 ordered read response."""

    policy_id: Identifier = EVIDENCE_READ_POLICY_ID
    estimator_id: Identifier = EVIDENCE_SEARCH_ESTIMATOR_ID
    estimated_token_target: int = Field(default=2_400, ge=1)
    serialized_byte_ceiling: int = Field(default=12_000, ge=1)
    item_ceiling: int = Field(default=8, ge=1)
    per_view_character_target: int = Field(default=2_000, ge=1, le=CONTEXT_CHARACTER_TARGET)
    absolute_oversized_byte_ceiling: int = Field(default=16_000, ge=1)

    @model_validator(mode="after")
    def validate_read_bounds(self) -> EvidenceReadPolicy:
        if self.absolute_oversized_byte_ceiling < self.serialized_byte_ceiling:
            raise ValueError("absolute read ceiling cannot be below the response ceiling")
        return self


class EvidenceReadBatchScope(FrozenModel):
    result_id: Identifier
    domain_id: Identifier
    snapshot_hash: ContentHash


class EvidenceReadBatchItem(FrozenModel):
    location_handle: str = Field(min_length=1)
    continuation: str | None = None
    mode: ReadContextMode = ReadContextMode.UNIT
    # A read is only reviewable when it is attributable to at least one
    # signaling question.  In particular, an unbound receipt must never be
    # usable to dismiss a candidate under a later, unrelated selected query.
    question_ids: tuple[Identifier, ...] = Field(min_length=1)
    source_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_questions(self) -> EvidenceReadBatchItem:
        if len(self.question_ids) != len(set(self.question_ids)):
            raise ValueError("question bindings must be unique")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("item source bindings must be unique")
        return self


class EvidenceReadBatchRequest(FrozenModel):
    scope: EvidenceReadBatchScope
    items: tuple[EvidenceReadBatchItem, ...] = Field(min_length=1)
    continuation: str | None = None

    @model_validator(mode="after")
    def validate_request(self) -> EvidenceReadBatchRequest:
        handles = [item.location_handle for item in self.items]
        if len(handles) != len(set(handles)):
            raise ValueError("duplicate location handles reject the whole batch")
        return self


class EvidenceReadItemCondition(StrEnum):
    SUCCESS = "success"
    STALE = "stale"
    UNREADABLE = "unreadable"
    WRONG_SCOPE = "wrong_scope"


class EvidenceReadBatchFragment(FrozenModel):
    """One exact, non-concatenated canonical-unit portion in a batch view."""

    canonical_unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    canonicalization_version: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    text_hash: ContentHash
    warnings: tuple[str, ...] = ()
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_text(self) -> EvidenceReadBatchFragment:
        if self.end < self.start:
            raise ValueError("fragment end cannot precede fragment start")
        if self.text_hash != sha256_digest(self.text.encode()):
            raise ValueError("fragment text hash must bind its exact source-authored text")
        return self


class EvidenceReadBatchView(FrozenModel):
    location_handle: str
    read_view_receipt: str = Field(min_length=1)
    fragments: tuple[EvidenceReadBatchFragment, ...] = Field(min_length=1)
    # Convenience identity is present only for a one-unit view.  Text remains
    # exclusively on fragments so multi-unit context cannot be mistaken for a
    # synthesized source passage.
    canonical_unit_id: Identifier | None = None
    source_id: Identifier | None = None
    source_artifact_hash: ContentHash | None = None
    parse_id: Identifier | None = None
    mode: ReadContextMode
    warnings: tuple[str, ...] = ()
    policy_id: Identifier
    policy_hash: ContentHash
    continuation: str | None = None
    oversized: bool = False
    limiting_bounds: tuple[str, ...] = ()
    omitted_fragment_count: int = Field(default=0, ge=0)
    omitted_character_count: int = Field(default=0, ge=0)
    citable: Literal[False] = False

    @model_validator(mode="after")
    def validate_primary_identity(self) -> EvidenceReadBatchView:
        identities = (
            self.canonical_unit_id,
            self.source_id,
            self.source_artifact_hash,
            self.parse_id,
        )
        if len(self.fragments) == 1:
            fragment = self.fragments[0]
            expected = (
                fragment.canonical_unit_id,
                fragment.source_id,
                fragment.source_artifact_hash,
                fragment.parse_id,
            )
            if identities != expected:
                raise ValueError("single-fragment view must expose its primary identity")
        elif any(identity is not None for identity in identities):
            raise ValueError("multi-fragment view cannot expose a misleading primary identity")
        return self


class EvidenceReadBatchOutcome(FrozenModel):
    input_index: int = Field(ge=0)
    location_handle: str
    question_ids: tuple[Identifier, ...] = ()
    condition: EvidenceReadItemCondition
    detail: str = Field(min_length=1)
    next_actions: tuple[str, ...] = ()
    view: EvidenceReadBatchView | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> EvidenceReadBatchOutcome:
        if (self.condition is EvidenceReadItemCondition.SUCCESS) != (self.view is not None):
            raise ValueError("successful read outcomes require exactly one view")
        return self


class EvidenceReadBatchPage(FrozenModel):
    snapshot_hash: ContentHash
    policy_id: Identifier
    policy_hash: ContentHash
    scope: EvidenceReadBatchScope
    outcomes: tuple[EvidenceReadBatchOutcome, ...]
    next_index: int = Field(ge=0)
    continuation: str | None = None
    serialized_response_bytes: int = Field(ge=0)
    estimated_response_tokens: int = Field(ge=0)
    limiting_bounds: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_measurement(self) -> EvidenceReadBatchPage:
        if self.estimated_response_tokens != _estimate_response_tokens(
            self.serialized_response_bytes
        ):
            raise ValueError("read batch token estimate must use ceil(bytes / 4)")
        return self


class SearchContinuationReason(StrEnum):
    COVERAGE_REQUIRES_BREADTH = "coverage_requires_breadth"
    SOURCE_SCOPE_ALREADY_MINIMAL = "source_scope_already_minimal"
    NARROWING_WOULD_OMIT_VARIANTS = "narrowing_would_omit_variants"
    TERM_IS_INHERENTLY_REPETITIVE = "term_is_inherently_repetitive"
    OTHER = "other"


class EvidenceSearchReadAction(FrozenModel):
    """The only action a candidate offers for authoritative source text."""

    action: Literal["read_evidence"] = "read_evidence"
    location_handle: str = Field(min_length=1)


class EvidenceSearchTriageFlags(FrozenModel):
    """Mechanical inspection facts; deliberately no relevance verdict."""

    has_reading_order_uncertainty: bool = False
    has_visual_uncertainty: bool = False
    has_duplicate_lineage: bool = False
    is_table_content: bool = False
    is_oversized_unit: bool = False
    has_context_dependency: bool = False
    has_possible_contradiction: bool = False


class EvidenceSearchCandidate(FrozenModel):
    """A non-citable, source-preserving navigation candidate.

    The candidate intentionally does not contain a ``CanonicalEvidenceUnit``
    or a full-text field.  Its location handle must be resolved through the
    Evidence read boundary before any text can become reviewed Evidence.
    """

    candidate_id: Identifier
    exposure_id: Identifier
    canonical_unit_id: Identifier
    location_handle: str = Field(min_length=1)
    source_id: Identifier
    source_label: str = Field(min_length=1)
    source_artifact_hash: ContentHash
    parse_id: Identifier
    canonicalization_version: str = Field(min_length=1)
    fragment_ids: tuple[Identifier, ...] = ()
    page: int = Field(ge=1)
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    kind: CanonicalUnitKind
    source_role: SourceRole | None = None
    document_zone: DocumentZone | None = None
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    source_snippet: str = Field(min_length=1)
    displayed_match_spans: tuple[tuple[int, int], ...] = ()
    displayed_match_count: int = Field(ge=0)
    undisplayed_match_count: int = Field(ge=0)
    canonical_start: int = Field(ge=0)
    canonical_end: int = Field(gt=0)
    left_omitted_character_count: int = Field(ge=0)
    right_omitted_character_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()
    triage_flags: EvidenceSearchTriageFlags
    duplicate_group_id: Identifier | None = None
    retained_duplicate_target_id: Identifier | None = None
    estimated_full_unit_bytes: int = Field(ge=1)
    estimated_full_unit_tokens: int = Field(ge=1)
    oversized_unit: bool = False
    read_evidence: EvidenceSearchReadAction
    citable: Literal[False] = False

    @model_validator(mode="after")
    def validate_snippet(self) -> EvidenceSearchCandidate:
        if self.canonical_end - self.canonical_start != len(self.source_snippet):
            raise ValueError("candidate snippet must bind its canonical character range")
        if self.displayed_match_count != len(self.displayed_match_spans):
            raise ValueError("displayed match count must bind displayed match spans")
        if any(
            start < 0 or end <= start or end > len(self.source_snippet)
            for start, end in self.displayed_match_spans
        ):
            raise ValueError("displayed match spans must stay inside the source snippet")
        if self.read_evidence.location_handle != self.location_handle:
            raise ValueError("read action must use the candidate location handle")
        return self


class EvidenceSearchSourceDiagnostic(FrozenModel):
    source_id: Identifier
    source_label: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    scoped_unit_count: int = Field(ge=0)
    scoped_candidate_fraction: float = Field(ge=0, le=1)
    page_candidate_count: int = Field(ge=0)


class EvidenceSearchTraversalCost(FrozenModel):
    classification: Literal["ordinary", "high"]
    projected_page_count: int = Field(ge=1)
    projected_cumulative_response_bytes: int = Field(ge=0)
    projected_cumulative_estimated_tokens: int = Field(ge=0)
    decision_required: bool = False


class EvidenceSearchPage(FrozenModel):
    """A deterministic v2 page measured as one complete JSON response."""

    snapshot_hash: ContentHash
    query_hash: ContentHash
    policy_id: Identifier
    policy_hash: ContentHash
    page_handle: str = Field(min_length=1)
    continuation: str | None = None
    candidate_ids: tuple[Identifier, ...]
    candidates: tuple[EvidenceSearchCandidate, ...]
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    remaining_page_count: int = Field(ge=0)
    returned_candidate_count: int = Field(ge=0)
    prior_candidate_count: int = Field(ge=0)
    total_candidate_count: int = Field(ge=0)
    remaining_candidate_count: int = Field(ge=0)
    estimated_response_tokens: int = Field(ge=0)
    serialized_response_bytes: int = Field(ge=0)
    current_cumulative_response_bytes: int = Field(ge=0)
    current_cumulative_estimated_tokens: int = Field(ge=0)
    projected_cumulative_response_bytes: int = Field(ge=0)
    projected_cumulative_estimated_tokens: int = Field(ge=0)
    limiting_bounds: tuple[str, ...] = ()
    omitted_candidate_count: int = Field(ge=0)
    omitted_estimated_response_bytes: int = Field(ge=0)
    traversal_complete: bool
    source_diagnostics: tuple[EvidenceSearchSourceDiagnostic, ...] = ()
    traversal_cost: EvidenceSearchTraversalCost
    next_actions: tuple[str, ...] = ()
    condition: Literal["results", "zero_hits", "excluded_only", "truncated"] = "results"
    excluded_count: int = Field(default=0, ge=0)

    def model_facing_payload(self) -> dict[str, object]:
        """Return the authoritative compact, non-citable search wire shape.

        The typed page deliberately remains complete: workflow persistence and
        audit need every field.  A model, however, needs a page catalogue, not
        the same policy defaults and source accounting repeated for every page.
        This projection is consequently the sole model-facing representation
        and retains every fact that can change a conservative triage decision.
        """

        source_keys = tuple(
            sorted(
                {
                    (
                        candidate.source_id,
                        candidate.source_label,
                        candidate.source_artifact_hash,
                        candidate.parse_id,
                        candidate.canonicalization_version,
                    )
                    for candidate in self.candidates
                }
            )
        )
        source_refs = {key: number for number, key in enumerate(source_keys)}

        def _candidate(candidate: EvidenceSearchCandidate) -> dict[str, object]:
            source_key = (
                candidate.source_id,
                candidate.source_label,
                candidate.source_artifact_hash,
                candidate.parse_id,
                candidate.canonicalization_version,
            )
            payload: dict[str, object] = {
                "candidate_id": candidate.candidate_id,
                "canonical_unit_id": candidate.canonical_unit_id,
                "location_handle": candidate.location_handle,
                "source_ref": source_refs[source_key],
                "page": candidate.page,
                "kind": candidate.kind.value,
                "snippet": candidate.source_snippet,
                "span": (candidate.canonical_start, candidate.canonical_end),
                "estimated_full_unit": (
                    candidate.estimated_full_unit_bytes,
                    candidate.estimated_full_unit_tokens,
                ),
            }
            optional = {
                "fragment_ids": candidate.fragment_ids,
                "section_path": candidate.section_path,
                "hierarchy_path": candidate.hierarchy_path,
                "source_role": candidate.source_role.value if candidate.source_role else None,
                "document_zone": candidate.document_zone.value if candidate.document_zone else None,
                "table_headers": candidate.table_headers,
                "caption": candidate.caption,
                "displayed_match_spans": candidate.displayed_match_spans,
                "displayed_match_count": (
                    candidate.displayed_match_count if candidate.displayed_match_count else None
                ),
                "undisplayed_match_count": (
                    candidate.undisplayed_match_count if candidate.undisplayed_match_count else None
                ),
                "omitted_characters": (
                    (
                        candidate.left_omitted_character_count,
                        candidate.right_omitted_character_count,
                    )
                    if (
                        candidate.left_omitted_character_count
                        or candidate.right_omitted_character_count
                    )
                    else None
                ),
                "warnings": candidate.warnings,
                "duplicate_group_id": candidate.duplicate_group_id,
                "retained_duplicate_target_id": candidate.retained_duplicate_target_id,
            }
            payload.update(
                {
                    key: value
                    for key, value in optional.items()
                    if value not in (None, (), 0, (0, 0))
                }
            )
            flags = candidate.triage_flags.model_dump(mode="json", exclude_defaults=True)
            if flags:
                payload["triage_flags"] = flags
            if candidate.oversized_unit:
                payload["oversized_unit"] = True
            return payload

        def _source_diagnostic(diagnostic: EvidenceSearchSourceDiagnostic) -> dict[str, object]:
            source_key = next(
                (
                    key
                    for key in source_keys
                    if key[0] == diagnostic.source_id and key[1] == diagnostic.source_label
                ),
                None,
            )
            return {
                **(
                    {"source_ref": source_refs[source_key]}
                    if source_key is not None
                    else {"source_id": diagnostic.source_id}
                ),
                "candidate_count": diagnostic.candidate_count,
                "page_candidate_count": diagnostic.page_candidate_count,
            }

        return {
            "snapshot_hash": self.snapshot_hash,
            "query_hash": self.query_hash,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "page_handle": self.page_handle,
            "continuation": self.continuation,
            "page_number": self.page_number,
            "total_page_count": self.total_page_count,
            "remaining_page_count": self.remaining_page_count,
            "returned_candidate_count": self.returned_candidate_count,
            "prior_candidate_count": self.prior_candidate_count,
            "total_candidate_count": self.total_candidate_count,
            "remaining_candidate_count": self.remaining_candidate_count,
            "serialized_response_bytes": self.serialized_response_bytes,
            "estimated_response_tokens": self.estimated_response_tokens,
            "current_cumulative_response_bytes": self.current_cumulative_response_bytes,
            "current_cumulative_estimated_tokens": self.current_cumulative_estimated_tokens,
            "projected_cumulative_response_bytes": self.projected_cumulative_response_bytes,
            "projected_cumulative_estimated_tokens": self.projected_cumulative_estimated_tokens,
            "limiting_bounds": self.limiting_bounds,
            "traversal_complete": self.traversal_complete,
            "traversal_cost": self.traversal_cost.model_dump(mode="json"),
            # Source-level breadth is a decision fact, not durable-only
            # bookkeeping.  Use the catalogue's compact source reference so
            # it costs one small integer per diagnostic, rather than repeat
            # source provenance already emitted above.
            "source_diagnostics": tuple(
                _source_diagnostic(diagnostic) for diagnostic in self.source_diagnostics
            ),
            "next_actions": self.next_actions,
            "condition": self.condition,
            "catalog": {
                "candidate_read_action": "read_evidence",
                "candidates_citable": False,
                "sources": tuple(
                    {
                        "source_id": source_id,
                        "source_label": source_label,
                        "source_artifact_hash": artifact_hash,
                        "parse_id": parse_id,
                        "canonicalization_version": canonicalization_version,
                    }
                    for (
                        source_id,
                        source_label,
                        artifact_hash,
                        parse_id,
                        canonicalization_version,
                    ) in source_keys
                ),
            },
            "candidates": [_candidate(candidate) for candidate in self.candidates],
        }

    @model_validator(mode="after")
    def validate_page(self) -> EvidenceSearchPage:
        if self.candidate_ids != tuple(candidate.candidate_id for candidate in self.candidates):
            raise ValueError("candidate IDs must preserve candidate order")
        if self.returned_candidate_count != len(self.candidates):
            raise ValueError("returned candidate count must bind page candidates")
        if (
            self.remaining_candidate_count
            != self.total_candidate_count
            - self.prior_candidate_count
            - self.returned_candidate_count
        ):
            raise ValueError("remaining candidate count must bind the current page")
        if self.remaining_page_count != self.total_page_count - self.page_number:
            raise ValueError("remaining page count must bind the current page")
        if self.traversal_complete != (self.continuation is None):
            raise ValueError("traversal completion must bind continuation presence")
        if self.estimated_response_tokens != _estimate_response_tokens(
            self.serialized_response_bytes
        ):
            raise ValueError("estimated tokens must use the declared byte-derived estimator")
        return self


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
        if cursor is not None and mode is ReadContextMode.SECTION:
            try:
                deferred = self._resolve_token("sectionoversize", cursor)
            except UnknownCursor:
                deferred = None
            if deferred is not None:
                if (
                    deferred.get("snapshot") != snapshot
                    or deferred.get("target") != target.unit_id
                    or deferred.get("source_artifact_hash") != target.source_artifact_hash
                    or deferred.get("parse_id") != target.parse_id
                ):
                    raise StaleCursor("section continuation is stale", field="cursor")
                deferred_id = deferred.get("deferred_unit_id")
                resume_offset = deferred.get("resume_offset")
                if (
                    not isinstance(deferred_id, str)
                    or isinstance(resume_offset, bool)
                    or not isinstance(resume_offset, int)
                    or resume_offset < 0
                ):
                    raise StaleCursor("section continuation is malformed", field="cursor")
                deferred_unit = self.read_unit(deferred_id, scope=scope)
                return EvidenceContext(
                    snapshot_hash=snapshot,
                    unit=deferred_unit,
                    character_count=len(deferred_unit.text),
                    character_target=character_target,
                    neighbor_limit=(
                        min(neighbor_limit, max(0, CONTEXT_UNIT_LIMIT - 1))
                        if mode is not ReadContextMode.UNIT
                        else 0
                    ),
                    oversized=True,
                    omitted_neighbor_count=0,
                    mode=mode,
                    section_path=deferred_unit.section_path,
                    continuation_cursor=self._encode_read_cursor(
                        snapshot, target.unit_id, resume_offset, scope=scope
                    ),
                    warnings=deferred_unit.warnings + ("oversized_section_fragment",),
                    visual_inspection_available=(deferred_unit.spatial is not None),
                )
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
        deferred_cursor: str | None = None
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
                if mode is ReadContextMode.SECTION:
                    deferred_cursor = self._issue_token(
                        "sectionoversize",
                        {
                            "snapshot": snapshot,
                            "target": target.unit_id,
                            "source_artifact_hash": target.source_artifact_hash,
                            "parse_id": target.parse_id,
                            "deferred_unit_id": candidate.unit_id,
                            "resume_offset": offset + scanned,
                        },
                    )
                    break
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
                deferred_cursor
                or self._encode_read_cursor(
                    snapshot,
                    target.unit_id,
                    next_offset,
                    scope=scope,
                )
                if deferred_cursor is not None
                or (
                    mode is ReadContextMode.SECTION
                    and next_offset < len(candidate_ids) + offset
                )
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

    def read_batch_v2(
        self,
        request: EvidenceReadBatchRequest,
        *,
        policy: EvidenceReadPolicy | None = None,
    ) -> EvidenceReadBatchPage:
        """Return one deterministic, bounded prefix of independent read views."""
        policy = policy or EvidenceReadPolicy()
        snapshot = self._snapshot()
        if request.scope.snapshot_hash != snapshot:
            raise StaleSearchContinuation("read batch scope belongs to a stale snapshot")
        request_hash = canonical_hash(
            {
                "scope": request.scope.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in request.items],
            }
        )
        start = 0
        if request.continuation:
            try:
                payload = self._resolve_token("v2readcur", request.continuation)
            except UnknownCursor:
                raise UnknownCursor(
                    "invalid v2 read batch continuation", field="continuation"
                ) from None
            if payload.get("snapshot") != snapshot:
                raise StaleSearchContinuation("read batch continuation belongs to a stale snapshot")
            if payload.get("policy") != canonical_hash(policy):
                raise SearchPolicyMismatch(
                    "read batch continuation belongs to a different read policy"
                )
            if payload.get("scope") != canonical_hash(request.scope):
                raise CursorScopeMismatch("read batch continuation belongs to a different scope")
            if payload.get("request") != request_hash:
                raise StaleSearchContinuation(
                    "read batch continuation belongs to a different request"
                )
            start = payload.get("next_index", -1)
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or not 0 <= start < len(request.items)
            ):
                raise StaleSearchContinuation("read batch continuation index is invalid")
        outcomes = tuple(
            self._read_batch_outcome(index, item, scope=request.scope, policy=policy)
            for index, item in enumerate(request.items[start:], start=start)
        )
        selected: list[EvidenceReadBatchOutcome] = []
        for outcome in outcomes:
            if len(selected) >= policy.item_ceiling:
                break
            candidate = tuple((*selected, outcome))
            payload = self._read_batch_payload(
                request.scope, policy, candidate, start + len(candidate), len(request.items)
            )
            # Probe the largest final envelope: continuation and a limiting
            # explanation are both present whenever another item remains.
            # Their fixed-width placeholders make the later issued token an
            # exact measurement replacement.
            if start + len(candidate) < len(request.items):
                payload["limiting_bounds"] = ("response_budget",)
            size, tokens = _read_batch_measure(payload)
            if size <= policy.serialized_byte_ceiling and tokens <= policy.estimated_token_target:
                selected.append(outcome)
                continue
            if not selected and size <= policy.absolute_oversized_byte_ceiling:
                selected.append(outcome)
            break
        if not selected and outcomes:
            raise OperationalRetrievalFailure(
                "one v2 read outcome exceeds the absolute response ceiling"
            )
        next_index = start + len(selected)
        payload = self._read_batch_payload(
            request.scope, policy, tuple(selected), next_index, len(request.items)
        )
        size, tokens = _read_batch_measure(payload)
        limiting: tuple[str, ...] = ()
        if next_index < len(request.items):
            limiting = (
                ("item_ceiling",)
                if len(selected) >= policy.item_ceiling
                else (
                    ("oversized_item",)
                    if size > policy.serialized_byte_ceiling
                    else ("response_budget",)
                )
            )
        payload["limiting_bounds"] = limiting
        size, tokens = _read_batch_measure(payload)
        payload["serialized_response_bytes"] = size
        payload["estimated_response_tokens"] = tokens
        continuation = (
            self._issue_token(
                "v2readcur",
                {
                    "snapshot": snapshot,
                    "policy": canonical_hash(policy),
                    "scope": canonical_hash(request.scope),
                    "request": request_hash,
                    "next_index": next_index,
                },
            )
            if next_index < len(request.items)
            else None
        )
        payload["continuation"] = continuation
        size, tokens = _read_batch_measure(payload)
        payload["serialized_response_bytes"] = size
        payload["estimated_response_tokens"] = tokens
        return EvidenceReadBatchPage.model_validate(payload)

    def _read_batch_outcome(
        self,
        index: int,
        item: EvidenceReadBatchItem,
        *,
        scope: EvidenceReadBatchScope,
        policy: EvidenceReadPolicy,
    ) -> EvidenceReadBatchOutcome:
        try:
            read = self.read_location(
                item.location_handle,
                character_target=policy.per_view_character_target,
                scope=EvidenceScope(source_ids=item.source_ids),
            )
            unit = read.unit
            if item.mode not in {
                ReadContextMode.UNIT,
                ReadContextMode.NEIGHBORS,
                ReadContextMode.SECTION,
            }:
                raise InvalidRetrievalRequest("unsupported v2 read mode", field="mode")
            if item.mode is not ReadContextMode.UNIT:
                context_cursor: str | None = None
                if item.continuation is not None:
                    payload = self._resolve_token("v2itemread", item.continuation)
                    if (
                        payload.get("snapshot") != read.snapshot_hash
                        or payload.get("policy") != canonical_hash(policy)
                        or payload.get("scope") != canonical_hash(scope)
                        or payload.get("location_handle") != item.location_handle
                        or payload.get("mode") != item.mode.value
                        or payload.get("unit") != unit.unit_id
                        or payload.get("source_artifact_hash") != unit.source_artifact_hash
                        or payload.get("parse_id") != unit.parse_id
                        or payload.get("questions") != list(item.question_ids)
                    ):
                        raise StaleCursor(
                            "v2 item continuation belongs to a different read request"
                        )
                    raw_context_cursor = payload.get("context")
                    if not isinstance(raw_context_cursor, str):
                        raise StaleCursor("v2 context continuation position is invalid")
                    context_cursor = raw_context_cursor
                    oversized_unit_id = payload.get("oversized_unit_id")
                    if oversized_unit_id is not None:
                        offset = payload.get("oversized_offset")
                        resume_context = payload.get("resume_context")
                        if (
                            not isinstance(oversized_unit_id, str)
                            or isinstance(offset, bool)
                            or not isinstance(offset, int)
                            or not isinstance(resume_context, str)
                        ):
                            raise StaleCursor("oversized section continuation is invalid")
                        oversized_unit = self.read_unit(
                            oversized_unit_id,
                            scope=EvidenceScope(source_ids=item.source_ids),
                        )
                        return self._v2_oversized_section_outcome(
                            index=index,
                            item=item,
                            unit=oversized_unit,
                            continuation_target_unit_id=unit.unit_id,
                            start=offset,
                            resume_context=resume_context,
                            scope=scope,
                            policy=policy,
                            continuation_input=item.continuation,
                        )
                context = self.read_context(
                    unit.unit_id,
                    character_target=policy.per_view_character_target,
                    mode=item.mode,
                    scope=EvidenceScope(source_ids=item.source_ids),
                    cursor=context_cursor,
                )
                if context.oversized:
                    return self._v2_oversized_section_outcome(
                        index=index,
                        item=item,
                        unit=context.unit,
                        continuation_target_unit_id=unit.unit_id,
                        start=0,
                        resume_context=context.continuation_cursor,
                        scope=scope,
                        policy=policy,
                        continuation_input=item.continuation,
                    )
                fragments = tuple(
                    EvidenceReadBatchFragment(
                        canonical_unit_id=displayed.unit_id,
                        source_id=displayed.source_id,
                        source_artifact_hash=displayed.source_artifact_hash,
                        parse_id=displayed.parse_id,
                        canonicalization_version=displayed.canonicalization_version,
                        start=0,
                        end=len(displayed.text),
                        text=displayed.text,
                        text_hash=sha256_digest(displayed.text.encode()),
                        warnings=displayed.warnings,
                        table_headers=displayed.table_headers,
                        caption=displayed.caption,
                        section_path=displayed.section_path,
                        hierarchy_path=displayed.hierarchy_path,
                    )
                    for displayed in context.all_units
                )
                receipt_fragments = tuple(
                    ReviewedEvidenceFragment(
                        unit_id=fragment.canonical_unit_id,
                        source_id=fragment.source_id,
                        source_artifact_hash=fragment.source_artifact_hash,
                        parse_id=fragment.parse_id,
                        canonicalization_version=fragment.canonicalization_version,
                        unit_content_hash=sha256_digest(displayed.text.encode()),
                        span_start=fragment.start,
                        span_end=fragment.end,
                        content_hash=fragment.text_hash,
                    )
                    for fragment, displayed in zip(fragments, context.all_units, strict=True)
                )
                receipt = self.issue_read_view_receipt(
                    snapshot_hash=context.snapshot_hash,
                    requested_mode=item.mode,
                    applied_mode=item.mode,
                    continuation_input=item.continuation,
                    continuation=context.continuation_cursor,
                    fragments=receipt_fragments,
                    displayed_units=context.all_units,
                    read_policy_id=policy.policy_id,
                    read_policy_hash=canonical_hash(policy),
                    question_ids=item.question_ids,
                )
                continuation = (
                    self._issue_token(
                        "v2itemread",
                        {
                            "snapshot": context.snapshot_hash,
                            "policy": canonical_hash(policy),
                            "scope": canonical_hash(scope),
                            "location_handle": item.location_handle,
                            "mode": item.mode.value,
                            "unit": unit.unit_id,
                            "source_artifact_hash": unit.source_artifact_hash,
                            "parse_id": unit.parse_id,
                            "questions": list(item.question_ids),
                            "context": context.continuation_cursor,
                        },
                    )
                    if context.continuation_cursor
                    else None
                )
                primary = fragments[0] if len(fragments) == 1 else None
                view = EvidenceReadBatchView(
                    location_handle=item.location_handle,
                    read_view_receipt=receipt,
                    fragments=fragments,
                    canonical_unit_id=primary.canonical_unit_id if primary else None,
                    source_id=primary.source_id if primary else None,
                    source_artifact_hash=primary.source_artifact_hash if primary else None,
                    parse_id=primary.parse_id if primary else None,
                    mode=item.mode,
                    warnings=context.warnings,
                    policy_id=policy.policy_id,
                    policy_hash=canonical_hash(policy),
                    continuation=continuation,
                    oversized=context.oversized,
                    limiting_bounds=(("per_view_character_target",) if context.oversized else ()),
                    omitted_fragment_count=context.omitted_neighbor_count,
                    # The context reducer intentionally does not synthesize
                    # omitted text.  It does retain an exact omitted-unit
                    # count; character count is zero only when no omitted
                    # source fragments are present in this context window.
                    omitted_character_count=0,
                )
                return EvidenceReadBatchOutcome(
                    input_index=index,
                    location_handle=item.location_handle,
                    question_ids=item.question_ids,
                    condition=EvidenceReadItemCondition.SUCCESS,
                    detail="bounded source-authored Evidence fragments",
                    next_actions=("continue_read",) if continuation else (),
                    view=view,
                )
            if item.continuation is not None:
                payload = self._resolve_token("v2itemread", item.continuation)
                if (
                    payload.get("snapshot") != read.snapshot_hash
                    or payload.get("policy") != canonical_hash(policy)
                    or payload.get("scope") != canonical_hash(scope)
                    or payload.get("location_handle") != item.location_handle
                    or payload.get("mode") != item.mode.value
                    or payload.get("unit") != unit.unit_id
                    or payload.get("source_artifact_hash") != unit.source_artifact_hash
                    or payload.get("parse_id") != unit.parse_id
                    or payload.get("questions") != list(item.question_ids)
                ):
                    raise StaleCursor("v2 item continuation belongs to a different read request")
                next_start = payload.get("next")
                if isinstance(next_start, bool) or not isinstance(next_start, int):
                    raise StaleCursor("v2 item continuation position is invalid")
                if not 0 <= next_start < len(unit.text):
                    raise StaleCursor("v2 item continuation is outside the canonical unit")
                end = min(next_start + policy.per_view_character_target, len(unit.text))
                read = EvidenceRead(
                    snapshot_hash=read.snapshot_hash,
                    unit=unit,
                    text=unit.text[next_start:end],
                    start=next_start,
                    end=end,
                    character_target=policy.per_view_character_target,
                    continuation_cursor="more" if end < len(unit.text) else None,
                    warnings=unit.warnings,
                )
            fragment = ReviewedEvidenceFragment(
                unit_id=unit.unit_id,
                source_id=unit.source_id,
                source_artifact_hash=unit.source_artifact_hash,
                parse_id=unit.parse_id,
                canonicalization_version=unit.canonicalization_version,
                unit_content_hash=sha256_digest(unit.text.encode()),
                span_start=read.start,
                span_end=read.end,
                content_hash=sha256_digest(read.text.encode()),
            )
            receipt = self.issue_read_view_receipt(
                snapshot_hash=read.snapshot_hash,
                requested_mode=item.mode,
                applied_mode=item.mode,
                continuation_input=None,
                continuation=read.continuation_cursor,
                fragments=(fragment,),
                displayed_units=(unit,),
                read_policy_id=policy.policy_id,
                read_policy_hash=canonical_hash(policy),
                question_ids=item.question_ids,
            )
            continuation = (
                self._issue_token(
                    "v2itemread",
                    {
                        "snapshot": read.snapshot_hash,
                        "policy": canonical_hash(policy),
                        "scope": canonical_hash(scope),
                        "location_handle": item.location_handle,
                        "mode": item.mode.value,
                        "unit": unit.unit_id,
                        "source_artifact_hash": unit.source_artifact_hash,
                        "parse_id": unit.parse_id,
                        "questions": list(item.question_ids),
                        "next": read.end,
                    },
                )
                if read.continuation_cursor
                else None
            )
            view = EvidenceReadBatchView(
                location_handle=item.location_handle,
                read_view_receipt=receipt,
                fragments=(
                    EvidenceReadBatchFragment(
                        canonical_unit_id=unit.unit_id,
                        source_id=unit.source_id,
                        source_artifact_hash=unit.source_artifact_hash,
                        parse_id=unit.parse_id,
                        canonicalization_version=unit.canonicalization_version,
                        start=read.start,
                        end=read.end,
                        text=read.text,
                        text_hash=sha256_digest(read.text.encode()),
                        warnings=read.warnings,
                        table_headers=unit.table_headers,
                        caption=unit.caption,
                        section_path=unit.section_path,
                        hierarchy_path=unit.hierarchy_path,
                    ),
                ),
                canonical_unit_id=unit.unit_id,
                source_id=unit.source_id,
                source_artifact_hash=unit.source_artifact_hash,
                parse_id=unit.parse_id,
                mode=item.mode,
                warnings=read.warnings,
                policy_id=policy.policy_id,
                policy_hash=canonical_hash(policy),
                continuation=continuation,
                oversized=len(unit.text.encode("utf-8")) > policy.per_view_character_target,
                limiting_bounds=("per_view_character_target",) if read.end < len(unit.text) else (),
                omitted_fragment_count=0,
                omitted_character_count=len(unit.text) - read.end,
            )
            return EvidenceReadBatchOutcome(
                input_index=index,
                location_handle=item.location_handle,
                question_ids=item.question_ids,
                condition=EvidenceReadItemCondition.SUCCESS,
                detail="bounded source-authored Evidence view",
                next_actions=("continue_read",) if continuation else (),
                view=view,
            )
        except ScopeMismatch:
            condition = EvidenceReadItemCondition.WRONG_SCOPE
            detail = "location is outside the item's authorized Source scope"
        except (StaleCursor, UnknownCursor):
            condition = EvidenceReadItemCondition.STALE
            detail = "location handle is stale or no longer resolvable"
        except RetrievalFailure:
            condition = EvidenceReadItemCondition.UNREADABLE
            detail = "Evidence source could not be read safely"
        return EvidenceReadBatchOutcome(
            input_index=index,
            location_handle=item.location_handle,
            question_ids=item.question_ids,
            condition=condition,
            detail=detail,
            next_actions=("request a fresh evidence search",),
        )

    def _v2_oversized_section_outcome(
        self,
        *,
        index: int,
        item: EvidenceReadBatchItem,
        unit: CanonicalEvidenceUnit,
        continuation_target_unit_id: Identifier,
        start: int,
        resume_context: str | None,
        scope: EvidenceReadBatchScope,
        policy: EvidenceReadPolicy,
        continuation_input: str | None,
    ) -> EvidenceReadBatchOutcome:
        """Return one bounded window of a deferred oversized section unit."""

        if start < 0 or start >= len(unit.text):
            raise StaleCursor("oversized section continuation is outside its unit")
        # The first window of an oversized target has no deferred SECTION
        # cursor.  Store that terminal state as None, never as an empty string:
        # an empty cursor means "start SECTION" to read_context.
        resume_context = resume_context or None
        end = min(start + policy.per_view_character_target, len(unit.text))
        text = unit.text[start:end]
        fragment = EvidenceReadBatchFragment(
            canonical_unit_id=unit.unit_id,
            source_id=unit.source_id,
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            canonicalization_version=unit.canonicalization_version,
            start=start,
            end=end,
            text=text,
            text_hash=sha256_digest(text.encode()),
            warnings=unit.warnings,
            table_headers=unit.table_headers,
            caption=unit.caption,
            section_path=unit.section_path,
            hierarchy_path=unit.hierarchy_path,
        )
        receipt_fragment = ReviewedEvidenceFragment(
            unit_id=unit.unit_id,
            source_id=unit.source_id,
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            canonicalization_version=unit.canonicalization_version,
            unit_content_hash=sha256_digest(unit.text.encode()),
            span_start=start,
            span_end=end,
            content_hash=fragment.text_hash,
        )
        next_context = resume_context if end >= len(unit.text) else None
        receipt = self.issue_read_view_receipt(
            snapshot_hash=scope.snapshot_hash,
            requested_mode=item.mode,
            applied_mode=item.mode,
            continuation_input=continuation_input,
            continuation=next_context,
            fragments=(receipt_fragment,),
            displayed_units=(unit,),
            read_policy_id=policy.policy_id,
            read_policy_hash=canonical_hash(policy),
            question_ids=item.question_ids,
        )
        token_payload: dict[str, object] = {
            "snapshot": scope.snapshot_hash,
            "policy": canonical_hash(policy),
            "scope": canonical_hash(scope),
            "location_handle": item.location_handle,
            "mode": item.mode.value,
            "unit": continuation_target_unit_id,
            "source_artifact_hash": unit.source_artifact_hash,
            "parse_id": unit.parse_id,
            "questions": list(item.question_ids),
            "context": next_context or resume_context or "",
        }
        if end < len(unit.text):
            token_payload["oversized_unit_id"] = unit.unit_id
            token_payload["oversized_offset"] = end
            token_payload["resume_context"] = resume_context or ""
        # A terminal window has no next section cursor.  Issuing a token with
        # an empty context would be interpreted as a fresh SECTION read and
        # silently restart traversal from the first neighbor.
        continuation = (
            self._issue_token("v2itemread", token_payload)
            if end < len(unit.text) or next_context is not None
            else None
        )
        view = EvidenceReadBatchView(
            location_handle=item.location_handle,
            read_view_receipt=receipt,
            fragments=(fragment,),
            canonical_unit_id=unit.unit_id,
            source_id=unit.source_id,
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            mode=item.mode,
            warnings=unit.warnings + ("oversized_section_fragment",),
            policy_id=policy.policy_id,
            policy_hash=canonical_hash(policy),
            continuation=continuation,
            oversized=True,
            limiting_bounds=("per_view_character_target",),
            omitted_fragment_count=1 if end < len(unit.text) else 0,
            omitted_character_count=len(unit.text) - end,
        )
        return EvidenceReadBatchOutcome(
            input_index=index,
            location_handle=item.location_handle,
            question_ids=item.question_ids,
            condition=EvidenceReadItemCondition.SUCCESS,
            detail="bounded oversized section Evidence fragment",
            next_actions=("continue_read",),
            view=view,
        )

    @staticmethod
    def _read_batch_payload(
        scope: EvidenceReadBatchScope,
        policy: EvidenceReadPolicy,
        outcomes: tuple[EvidenceReadBatchOutcome, ...],
        next_index: int,
        total_items: int,
    ) -> dict[str, object]:
        del total_items
        return {
            "snapshot_hash": scope.snapshot_hash,
            "policy_id": policy.policy_id,
            "policy_hash": canonical_hash(policy),
            "scope": scope,
            "outcomes": outcomes,
            "next_index": next_index,
            "continuation": _v2_placeholder("v2readcur") if next_index else None,
            "serialized_response_bytes": 0,
            "estimated_response_tokens": 0,
            "limiting_bounds": (),
        }

    def search_v2(
        self,
        query: SearchQuery,
        *,
        issuance_context: str | None = None,
        continuation: str | None = None,
        scope: EvidenceScope | None = None,
        continue_reason: SearchContinuationReason | None = None,
        continue_rationale: str | None = None,
        policy: EvidenceSearchPolicy | None = None,
        envelope_measure: Callable[[EvidenceSearchPage], tuple[int, int]] | None = None,
    ) -> EvidenceSearchPage:
        """Return one engine-bounded v2 navigation page.

        The public caller controls only query semantics, authorized scope, and
        an opaque continuation.  ``policy`` exists for engine calibration and
        replay tests; application/MCP surfaces must select it server-side.
        """
        policy = policy or EvidenceSearchPolicy()
        snapshot = self._snapshot()
        query_hash = canonical_hash(query)
        offset, reason_required = (
            self._decode_v2_continuation(
                continuation,
                snapshot=snapshot,
                query_hash=query_hash,
                policy=policy,
                scope=scope,
                issuance_context=issuance_context,
            )
            if continuation
            else (0, False)
        )
        if continuation is None and (continue_reason is not None or continue_rationale is not None):
            raise InvalidRetrievalRequest(
                "a continuation reason is valid only with a search continuation",
                field="continue_reason",
            )
        if reason_required and continue_reason is None:
            raise InvalidRetrievalRequest(
                "continuing this high-cost search requires a reason code",
                field="continue_reason",
            )
        if continue_reason is SearchContinuationReason.OTHER and not (
            continue_rationale and continue_rationale.strip()
        ):
            raise InvalidRetrievalRequest(
                "the other continuation reason requires a rationale",
                field="continue_rationale",
            )
        if continue_reason is not SearchContinuationReason.OTHER and continue_rationale is not None:
            raise InvalidRetrievalRequest(
                "a continuation rationale is only valid for the other reason code",
                field="continue_rationale",
            )

        rows, scoped_count, excluded_count = self._matches(query, scope=scope)
        scoped_source_ids = self._v2_scoped_source_ids(query, scope=scope)
        if self._snapshot() != snapshot:
            raise StaleSearchContinuation(
                "evidence snapshot changed while preparing the search page",
                field="continuation",
            )
        rows = _diversify_rows(_collapse_duplicate_groups(_best_projection_per_unit(rows)))
        if offset > len(rows):
            raise StaleSearchContinuation("search continuation position is outside the result set")
        candidates = tuple(
            self._v2_candidate(
                row,
                query=query,
                snapshot=snapshot,
                query_hash=query_hash,
                policy=policy,
                issuance_context=issuance_context,
            )
            for row in rows
        )
        layouts = _pack_v2_candidate_pages(
            candidates,
            snapshot=snapshot,
            query_hash=query_hash,
            policy=policy,
            scoped_count=scoped_count,
            excluded_count=excluded_count,
            scoped_source_ids=scoped_source_ids,
            envelope_measure=envelope_measure,
        )
        if not layouts:
            layouts = ((),)
        # Self-reporting measurements and limiting-bound labels can grow after
        # a provisional layout is chosen.  Re-materialize and split any normal
        # bound violation until the actual wire envelopes are stable.
        for _ in range(max(1, len(candidates) + 1)):
            pages = _materialize_v2_pages(
                layouts,
                snapshot=snapshot,
                query_hash=query_hash,
                policy=policy,
                scoped_count=scoped_count,
                excluded_count=excluded_count,
                scoped_source_ids=scoped_source_ids,
                envelope_measure=envelope_measure,
            )
            offending = tuple(
                number
                for number, page in enumerate(pages)
                if (
                    page.serialized_response_bytes > policy.serialized_byte_ceiling
                    or page.estimated_response_tokens > policy.estimated_token_target
                )
                and len(layouts[number]) > 1
            )
            if not offending:
                break
            layouts = _split_v2_candidate_layouts(layouts, offending)
        else:  # pragma: no cover - each split strictly reduces a page width
            raise OperationalRetrievalFailure("v2 evidence search layout did not stabilize")
        starts = [sum(len(page) for page in layouts[:number]) for number in range(len(layouts))]
        try:
            page_index = starts.index(offset)
        except ValueError as error:
            raise StaleSearchContinuation(
                "search continuation position is not a page boundary"
            ) from error
        _validate_materialized_v2_pages(
            pages, policy=policy, envelope_measure=envelope_measure
        )
        page = pages[page_index]
        page_handle = self._issue_stable_token(
            "v2page",
            {
                "snapshot": snapshot,
                "query": query_hash,
                "policy": canonical_hash(policy),
                "scope": canonical_hash(scope) if scope is not None else None,
                "issuance_context": issuance_context,
                "offset": offset,
            },
        )
        next_offset = offset + len(page.candidates)
        continuation_value = (
            self._issue_stable_token(
                "v2cur",
                {
                    "snapshot": snapshot,
                    "query": query_hash,
                    "policy": canonical_hash(policy),
                    "scope": canonical_hash(scope) if scope is not None else None,
                    "issuance_context": issuance_context,
                    "offset": next_offset,
                    "reason_required": page.traversal_cost.decision_required,
                },
            )
            if next_offset < len(candidates)
            else None
        )
        if self._snapshot() != snapshot:
            raise StaleSearchContinuation(
                "evidence snapshot changed while issuing the search page",
                field="continuation",
            )
        # Lookup-token prefixes and random bodies have the fixed lengths used
        # in packing placeholders, so replacement preserves the measured bytes.
        return page.model_copy(
            update={"page_handle": page_handle, "continuation": continuation_value}
        )

    def _v2_scoped_source_ids(
        self, query: SearchQuery, *, scope: EvidenceScope | None
    ) -> tuple[Identifier, ...]:
        """Return every source in the query's authorized universe, including zero hits."""

        filters: list[str] = []
        parameters: list[object] = []
        if query.source_ids:
            filters.append(f"u.source_id IN ({','.join('?' for _ in query.source_ids)})")
            parameters.extend(query.source_ids)
        if query.pages:
            filters.append(f"u.page IN ({','.join('?' for _ in query.pages)})")
            parameters.extend(query.pages)
        metadata_filters, metadata_parameters = _query_metadata_filters(query, scope)
        filters.extend(metadata_filters)
        parameters.extend(metadata_parameters)
        where = " AND " + " AND ".join(filters) if filters else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT u.source_id FROM evidence_units AS u WHERE 1=1{where} "
                "ORDER BY u.source_id",
                parameters,
            ).fetchall()
        return tuple(row["source_id"] for row in rows)

    def _decode_v2_continuation(
        self,
        continuation: str,
        *,
        snapshot: ContentHash,
        query_hash: ContentHash,
        policy: EvidenceSearchPolicy,
        scope: EvidenceScope | None,
        issuance_context: str | None,
    ) -> tuple[int, bool]:
        try:
            payload = self._resolve_token("v2cur", continuation)
        except UnknownCursor:
            raise UnknownCursor("invalid v2 search continuation", field="continuation") from None
        if payload.get("snapshot") != snapshot:
            raise StaleSearchContinuation("continuation belongs to a different index snapshot")
        if payload.get("query") != query_hash:
            raise StaleSearchContinuation("continuation belongs to a different structured query")
        if payload.get("issuance_context") != issuance_context:
            raise StaleSearchContinuation("continuation belongs to a different search attempt")
        if payload.get("policy") != canonical_hash(policy):
            raise SearchPolicyMismatch()
        if payload.get("scope") != (canonical_hash(scope) if scope is not None else None):
            raise CursorScopeMismatch(
                "continuation belongs to a different Evidence scope", field="continuation"
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise StaleSearchContinuation("search continuation position is invalid")
        reason_required = payload.get("reason_required")
        if not isinstance(reason_required, bool):
            raise StaleSearchContinuation("search continuation decision state is invalid")
        return offset, reason_required

    def _v2_candidate(
        self,
        row: sqlite3.Row,
        *,
        query: SearchQuery,
        snapshot: ContentHash,
        query_hash: ContentHash,
        policy: EvidenceSearchPolicy,
        issuance_context: str | None,
    ) -> EvidenceSearchCandidate:
        unit = _unit_from_row(row)
        snippet, start, end, spans, undisplayed = _match_centered_snippet(
            unit.text, _query_lexical_patterns(query), policy.snippet_character_target
        )
        candidate_id = _v2_candidate_id(unit)
        exposure_id = "exposure:" + canonical_hash(
            {
                "snapshot": snapshot,
                "query": query_hash,
                "policy": canonical_hash(policy),
                "candidate_id": candidate_id,
                "issuance_context": issuance_context,
            }
        ).removeprefix("sha256:")
        full_unit_bytes = len(unit.text.encode("utf-8"))
        flags = EvidenceSearchTriageFlags(
            has_reading_order_uncertainty="reading_order_uncertain" in unit.warnings,
            has_visual_uncertainty=(
                unit.spatial is None or "parse_render_discrepancy" in unit.warnings
            ),
            has_duplicate_lineage=unit.duplicate_group_id is not None,
            is_table_content=unit.kind is CanonicalUnitKind.TABLE_ROW,
            is_oversized_unit=full_unit_bytes > policy.serialized_byte_ceiling,
            # These are parser/reconciliation facts, never semantic verdicts.
            has_context_dependency=any(
                warning
                in {
                    "context_dependency",
                    "negation_context_required",
                    "pronoun_context_required",
                }
                for warning in unit.warnings
            ),
            has_possible_contradiction="possible_contradiction" in unit.warnings,
        )
        location_handle = self._encode_location_handle(
            unit, snapshot, issuance_context=issuance_context
        )
        return EvidenceSearchCandidate(
            candidate_id=candidate_id,
            exposure_id=exposure_id,
            canonical_unit_id=unit.unit_id,
            location_handle=location_handle,
            source_id=unit.source_id,
            source_label=_source_label(unit.source_id),
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            canonicalization_version=unit.canonicalization_version,
            fragment_ids=unit.fragment_ids,
            page=unit.page,
            section_path=unit.section_path,
            hierarchy_path=unit.hierarchy_path,
            kind=unit.kind,
            source_role=unit.source_role,
            document_zone=unit.document_zone,
            table_headers=unit.table_headers,
            caption=unit.caption,
            source_snippet=snippet,
            displayed_match_spans=spans,
            displayed_match_count=len(spans),
            undisplayed_match_count=undisplayed,
            canonical_start=start,
            canonical_end=end,
            left_omitted_character_count=start,
            right_omitted_character_count=len(unit.text) - end,
            warnings=unit.warnings,
            triage_flags=flags,
            duplicate_group_id=unit.duplicate_group_id,
            # Duplicate targets are navigation identities, never canonical
            # unit IDs.  The representative of an engine-known duplicate
            # group is the retained candidate for that lineage.
            retained_duplicate_target_id=(candidate_id if unit.duplicate_group_id else None),
            estimated_full_unit_bytes=full_unit_bytes,
            estimated_full_unit_tokens=_estimate_response_tokens(full_unit_bytes),
            oversized_unit=flags.is_oversized_unit,
            read_evidence=EvidenceSearchReadAction(location_handle=location_handle),
        )

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
        # Keep stable tokens at the same fixed width as ordinary lookup
        # tokens, so page packing remains exact.  The collision check below
        # rejects the astronomically unlikely truncated-digest collision.
        token = f"{kind}:{canonical_hash(payload).removeprefix('sha256:')[:22]}"
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO evidence_cursor_token(token, kind, payload) "
                "VALUES (?, ?, ?)",
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
        read_policy_id: Identifier | None = None,
        read_policy_hash: ContentHash | None = None,
        question_ids: tuple[Identifier, ...] = (),
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
            "read_policy_id": read_policy_id,
            "read_policy_hash": read_policy_hash,
            "question_ids": question_ids,
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
            read_policy_id = payload.get("read_policy_id")
            read_policy_hash = payload.get("read_policy_hash")
            question_ids = payload.get("question_ids", [])
            if (
                not isinstance(snapshot_hash, str)
                or not isinstance(requested_mode, str)
                or not isinstance(applied_mode, str)
                or not isinstance(raw_fragments, list)
                or not isinstance(raw_lineage, list)
                or not isinstance(continuation_input, (str, type(None)))
                or not isinstance(continuation, (str, type(None)))
                or not isinstance(read_policy_id, (str, type(None)))
                or not isinstance(read_policy_hash, (str, type(None)))
                or not isinstance(question_ids, (list, tuple))
                or not all(isinstance(question_id, str) for question_id in question_ids)
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
                or any(
                    value != getattr(unit, attribute)
                    for value, attribute in (
                        (fragment.source_id, "source_id"),
                        (fragment.source_artifact_hash, "source_artifact_hash"),
                        (fragment.parse_id, "parse_id"),
                        (fragment.canonicalization_version, "canonicalization_version"),
                    )
                )
                or fragment.unit_content_hash != sha256_digest(unit.text.encode())
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
            read_policy_id=read_policy_id,
            read_policy_hash=read_policy_hash,
            question_ids=tuple(question_ids),
            fragments=frozen_fragments,
        )

    def _encode_location_handle(
        self,
        unit: CanonicalEvidenceUnit,
        snapshot: ContentHash,
        *,
        issuance_context: str | None = None,
    ) -> str:
        """Issue an opaque handle bound to the exact source/Parse lineage."""
        return self._issue_stable_token(
            "loc",
            {
                "snapshot": snapshot,
                "unit": unit.unit_id,
                "source_artifact_hash": unit.source_artifact_hash,
                "parse_id": unit.parse_id,
                "fragment_ids": list(unit.fragment_ids),
                "canonicalization_version": unit.canonicalization_version,
                "issuance_context": issuance_context,
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


def _estimate_response_tokens(serialized_response_bytes: int) -> int:
    """Return the versioned provider-neutral ``ceil(bytes / 4)`` estimate."""

    return (serialized_response_bytes + 3) // 4


def _read_batch_measure(payload: dict[str, object]) -> tuple[int, int]:
    size = 0
    tokens = 0
    for _ in range(8):
        measured = len(
            canonical_json_bytes(
                EvidenceReadBatchPage.model_construct(
                    **(
                        payload
                        | {
                            "serialized_response_bytes": size,
                            "estimated_response_tokens": tokens,
                        }
                    )
                ).model_dump(mode="json")
            )
        )
        estimated = _estimate_response_tokens(measured)
        if (measured, estimated) == (size, tokens):
            return measured, estimated
        size, tokens = measured, estimated
    return size, tokens


def _source_label(source_id: Identifier) -> str:
    """Use the issued Source ID as the safe fallback display label."""

    return source_id


def _query_lexical_patterns(query: SearchQuery) -> tuple[re.Pattern[str], ...]:
    """Literal source-text patterns used only to choose a visible snippet.

    FTS remains the retrieval authority.  These patterns never generate prose;
    they merely find a source-authored lexical occurrence to center the view.
    """

    patterns = [re.compile(re.escape(phrase), re.IGNORECASE) for phrase in query.phrases]
    patterns.extend(
        re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        for term in (*query.terms, *(term for group in query.any_of for term in group))
    )
    patterns.extend(
        re.compile(rf"\b{re.escape(prefix)}\w*", re.IGNORECASE) for prefix in query.prefixes
    )
    return tuple(patterns)


def _match_centered_snippet(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    target: int,
) -> tuple[str, int, int, tuple[tuple[int, int], ...], int]:
    matches = sorted(
        (match.start(), match.end())
        for pattern in patterns
        for match in pattern.finditer(text)
        if match.end() > match.start()
    )
    # A porter-tokenized FTS match can have no literal substring (for example
    # a stem variant).  Still return source-authored text, without pretending a
    # marker is a match.
    focus = matches[0][0] if matches else 0
    start = max(0, min(focus - target // 2, len(text) - target))
    end = min(len(text), start + target)
    snippet = text[start:end]
    displayed = tuple(
        (match_start - start, match_end - start)
        for match_start, match_end in matches
        if start <= match_start and match_end <= end
    )
    undisplayed = len(matches) - len(displayed)
    return snippet, start, end, displayed, undisplayed


def _v2_placeholder(kind: str) -> str:
    """Match the exact length of a token issued by ``_LookupTokenCodec``."""

    return f"{kind}:" + "x" * 22


def _v2_candidate_id(unit: CanonicalEvidenceUnit) -> Identifier:
    """Return the stable candidate identity for one canonical unit."""

    return "candidate:" + canonical_hash(
        {
            "unit_id": unit.unit_id,
            "source_artifact_hash": unit.source_artifact_hash,
            "parse_id": unit.parse_id,
            "canonicalization_version": unit.canonicalization_version,
        }
    ).removeprefix("sha256:")


def _v2_source_diagnostics(
    candidates: tuple[EvidenceSearchCandidate, ...],
    page_candidates: tuple[EvidenceSearchCandidate, ...],
    scoped_count: int,
    scoped_source_ids: tuple[Identifier, ...],
) -> tuple[EvidenceSearchSourceDiagnostic, ...]:
    totals: dict[str, int] = {}
    page_totals: dict[str, int] = {}
    for candidate in candidates:
        totals[candidate.source_id] = totals.get(candidate.source_id, 0) + 1
    for candidate in page_candidates:
        page_totals[candidate.source_id] = page_totals.get(candidate.source_id, 0) + 1
    return tuple(
        EvidenceSearchSourceDiagnostic(
            source_id=source_id,
            source_label=_source_label(source_id),
            candidate_count=count,
            scoped_unit_count=scoped_count,
            scoped_candidate_fraction=(count / scoped_count if scoped_count else 0),
            page_candidate_count=page_totals.get(source_id, 0),
        )
        for source_id in scoped_source_ids
        for count in (totals.get(source_id, 0),)
    )


def _v2_page_payload(
    *,
    all_candidates: tuple[EvidenceSearchCandidate, ...],
    page_candidates: tuple[EvidenceSearchCandidate, ...],
    page_number: int,
    total_page_count: int,
    snapshot: ContentHash,
    query_hash: ContentHash,
    policy: EvidenceSearchPolicy,
    scoped_count: int,
    excluded_count: int,
    scoped_source_ids: tuple[Identifier, ...],
    serialized_response_bytes: int = 0,
    estimated_response_tokens: int = 0,
    current_cumulative_response_bytes: int = 0,
    current_cumulative_estimated_tokens: int = 0,
    projected_cumulative_response_bytes: int = 0,
    projected_cumulative_estimated_tokens: int = 0,
    limiting_bounds: tuple[str, ...] = (),
) -> dict[str, object]:
    end = sum(len(page) for page in ())  # Keeps the response representation intentionally explicit.
    del end
    candidate_count = len(all_candidates)
    prior = 0  # The caller supplies remaining counts; this function is reused for packing probes.
    del prior
    # Position is encoded in candidate membership rather than caller offset.
    page_start = 0
    # The first candidate ID is unique, so membership lookup remains deterministic
    # after duplicate collapse.
    if page_candidates:
        page_start = all_candidates.index(page_candidates[0])
    page_end = page_start + len(page_candidates)
    remaining = candidate_count - page_end
    traversal_complete = remaining == 0
    projected_pages = total_page_count
    high = (
        projected_pages >= policy.high_cost_page_threshold
        or projected_cumulative_estimated_tokens >= policy.high_cost_estimated_token_threshold
    )
    decision_required = high and page_number == 1 and not traversal_complete
    condition: Literal["results", "zero_hits", "excluded_only", "truncated"]
    if not page_candidates:
        condition = "excluded_only" if excluded_count else "zero_hits"
    elif traversal_complete:
        condition = "results"
    else:
        condition = "truncated"
    return {
        "snapshot_hash": snapshot,
        "query_hash": query_hash,
        "policy_id": policy.policy_id,
        "policy_hash": canonical_hash(policy),
        "page_handle": _v2_placeholder("v2page"),
        "continuation": None if traversal_complete else _v2_placeholder("v2cur"),
        "candidate_ids": tuple(candidate.candidate_id for candidate in page_candidates),
        "candidates": page_candidates,
        "page_number": page_number,
        "total_page_count": total_page_count,
        "remaining_page_count": total_page_count - page_number,
        "returned_candidate_count": len(page_candidates),
        "prior_candidate_count": page_start,
        "total_candidate_count": candidate_count,
        "remaining_candidate_count": remaining,
        "estimated_response_tokens": estimated_response_tokens,
        "serialized_response_bytes": serialized_response_bytes,
        "current_cumulative_response_bytes": current_cumulative_response_bytes,
        "current_cumulative_estimated_tokens": current_cumulative_estimated_tokens,
        "projected_cumulative_response_bytes": projected_cumulative_response_bytes,
        "projected_cumulative_estimated_tokens": projected_cumulative_estimated_tokens,
        "limiting_bounds": limiting_bounds,
        "omitted_candidate_count": remaining,
        "omitted_estimated_response_bytes": sum(
            candidate.estimated_full_unit_bytes for candidate in all_candidates[page_end:]
        ),
        "traversal_complete": traversal_complete,
        "source_diagnostics": _v2_source_diagnostics(
            all_candidates, page_candidates, scoped_count, scoped_source_ids
        ),
        "traversal_cost": EvidenceSearchTraversalCost(
            classification="high" if high else "ordinary",
            projected_page_count=projected_pages,
            projected_cumulative_response_bytes=projected_cumulative_response_bytes,
            projected_cumulative_estimated_tokens=projected_cumulative_estimated_tokens,
            decision_required=decision_required,
        ),
        "next_actions": (
            ("refine_or_supersede_query", "continue_search")
            if decision_required
            else (
                ("continue_search",)
                if not traversal_complete
                else (("read_evidence",) if page_candidates else ())
            )
        ),
        "condition": condition,
        "excluded_count": excluded_count,
    }


def _v2_payload_size(
    payload: dict[str, object],
    *,
    envelope_measure: Callable[[EvidenceSearchPage], tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Solve the two self-reporting measurement fields to a stable value."""

    size = 0
    tokens = 0
    for _ in range(8):
        page = EvidenceSearchPage.model_construct(
            **(
                payload
                | {
                    "serialized_response_bytes": size,
                    "estimated_response_tokens": tokens,
                }
            )
        )
        if envelope_measure is None:
            measured = len(canonical_json_bytes(page.model_facing_payload()))
            estimated = _estimate_response_tokens(measured)
        else:
            measured, estimated = envelope_measure(page)
        if measured == size and estimated == tokens:
            return measured, estimated
        size, tokens = measured, estimated
    return size, tokens


def _pack_v2_candidate_pages(
    candidates: tuple[EvidenceSearchCandidate, ...],
    *,
    snapshot: ContentHash,
    query_hash: ContentHash,
    policy: EvidenceSearchPolicy,
    scoped_count: int,
    excluded_count: int,
    scoped_source_ids: tuple[Identifier, ...],
    envelope_measure: Callable[[EvidenceSearchPage], tuple[int, int]] | None = None,
) -> tuple[tuple[EvidenceSearchCandidate, ...], ...]:
    if not candidates:
        return ()
    total_guess = len(candidates)
    pages: tuple[tuple[EvidenceSearchCandidate, ...], ...] = ()
    for _ in range(8):
        built: list[tuple[EvidenceSearchCandidate, ...]] = []
        offset = 0
        while offset < len(candidates):
            chosen: list[EvidenceSearchCandidate] = []
            while offset + len(chosen) < len(candidates) and len(chosen) < policy.candidate_ceiling:
                proposed = tuple((*chosen, candidates[offset + len(chosen)]))
                payload = _v2_page_payload(
                    all_candidates=candidates,
                    page_candidates=proposed,
                    page_number=len(built) + 1,
                    total_page_count=total_guess,
                    snapshot=snapshot,
                    query_hash=query_hash,
                    policy=policy,
                    scoped_count=scoped_count,
                    excluded_count=excluded_count,
                    scoped_source_ids=scoped_source_ids,
                )
                size, tokens = _v2_payload_size(payload, envelope_measure=envelope_measure)
                if (
                    size <= policy.serialized_byte_ceiling
                    and tokens <= policy.estimated_token_target
                ):
                    chosen.append(candidates[offset + len(chosen)])
                    continue
                break
            if not chosen:
                # An indivisible candidate is permitted only through the
                # separately-enforced absolute ceiling, so a tail never stalls.
                proposed = (candidates[offset],)
                payload = _v2_page_payload(
                    all_candidates=candidates,
                    page_candidates=proposed,
                    page_number=len(built) + 1,
                    total_page_count=total_guess,
                    snapshot=snapshot,
                    query_hash=query_hash,
                    policy=policy,
                    scoped_count=scoped_count,
                    excluded_count=excluded_count,
                    scoped_source_ids=scoped_source_ids,
                    limiting_bounds=("oversized_candidate",),
                )
                size, _ = _v2_payload_size(payload, envelope_measure=envelope_measure)
                if (
                    size > policy.oversized_candidate_byte_ceiling
                ):
                    raise OperationalRetrievalFailure(
                        "one evidence candidate exceeds the absolute response ceiling"
                    )
                chosen.append(candidates[offset])
            built.append(tuple(chosen))
            offset += len(chosen)
        candidate_pages = tuple(built)
        if candidate_pages == pages and len(candidate_pages) == total_guess:
            return candidate_pages
        pages = candidate_pages
        total_guess = len(candidate_pages)
    return pages


def _materialize_v2_pages(
    layouts: tuple[tuple[EvidenceSearchCandidate, ...], ...],
    *,
    snapshot: ContentHash,
    query_hash: ContentHash,
    policy: EvidenceSearchPolicy,
    scoped_count: int,
    excluded_count: int,
    scoped_source_ids: tuple[Identifier, ...],
    envelope_measure: Callable[[EvidenceSearchPage], tuple[int, int]] | None = None,
) -> tuple[EvidenceSearchPage, ...]:
    candidates = tuple(candidate for page in layouts for candidate in page)
    total_pages = len(layouts)
    sizes = [0] * total_pages
    tokens = [0] * total_pages
    limiting_bounds: list[tuple[str, ...]] = [()] * total_pages
    # Cumulative fields and limiting text are part of the envelope; converge
    # their final, self-reported values together rather than measuring a
    # smaller provisional response and relabelling it afterward.
    for _ in range(32):
        projected_bytes = sum(sizes)
        projected_tokens = sum(tokens)
        cumulative_bytes = 0
        cumulative_tokens = 0
        new_sizes: list[int] = []
        new_tokens: list[int] = []
        new_limits: list[tuple[str, ...]] = []
        offset = 0
        for number, page_candidates in enumerate(layouts, start=1):
            payload = _v2_page_payload(
                all_candidates=candidates,
                page_candidates=page_candidates,
                page_number=number,
                total_page_count=total_pages,
                snapshot=snapshot,
                query_hash=query_hash,
                policy=policy,
                scoped_count=scoped_count,
                excluded_count=excluded_count,
                scoped_source_ids=scoped_source_ids,
                current_cumulative_response_bytes=cumulative_bytes + sizes[number - 1],
                current_cumulative_estimated_tokens=cumulative_tokens + tokens[number - 1],
                projected_cumulative_response_bytes=projected_bytes,
                projected_cumulative_estimated_tokens=projected_tokens,
                limiting_bounds=limiting_bounds[number - 1],
            )
            size, estimated = _v2_payload_size(payload, envelope_measure=envelope_measure)
            new_sizes.append(size)
            new_tokens.append(estimated)
            offset += len(page_candidates)
            if (
                size > policy.serialized_byte_ceiling
                or estimated > policy.estimated_token_target
            ):
                limit = ("oversized_candidate",)
            elif offset < len(candidates):
                if len(page_candidates) >= policy.candidate_ceiling:
                    limit = ("candidate_ceiling",)
                elif estimated >= policy.estimated_token_target:
                    limit = ("estimated_token_target",)
                else:
                    limit = ("serialized_byte_ceiling",)
            else:
                limit = ()
            new_limits.append(limit)
            cumulative_bytes += size
            cumulative_tokens += estimated
        if new_sizes == sizes and new_tokens == tokens and new_limits == limiting_bounds:
            break
        sizes, tokens, limiting_bounds = new_sizes, new_tokens, new_limits
    else:  # pragma: no cover - fixed-size integer measurements converge rapidly
        raise OperationalRetrievalFailure("v2 evidence search measurements did not stabilize")
    projected_bytes = sum(sizes)
    projected_tokens = sum(tokens)
    result: list[EvidenceSearchPage] = []
    cumulative_bytes = 0
    cumulative_tokens = 0
    offset = 0
    for number, page_candidates in enumerate(layouts, start=1):
        offset += len(page_candidates)
        cumulative_bytes += sizes[number - 1]
        cumulative_tokens += tokens[number - 1]
        payload = _v2_page_payload(
            all_candidates=candidates,
            page_candidates=page_candidates,
            page_number=number,
            total_page_count=total_pages,
            snapshot=snapshot,
            query_hash=query_hash,
            policy=policy,
            scoped_count=scoped_count,
            excluded_count=excluded_count,
            scoped_source_ids=scoped_source_ids,
            serialized_response_bytes=sizes[number - 1],
            estimated_response_tokens=tokens[number - 1],
            current_cumulative_response_bytes=cumulative_bytes,
            current_cumulative_estimated_tokens=cumulative_tokens,
            projected_cumulative_response_bytes=projected_bytes,
            projected_cumulative_estimated_tokens=projected_tokens,
            limiting_bounds=limiting_bounds[number - 1],
        )
        result.append(EvidenceSearchPage.model_validate(payload))
    return tuple(result)


def _split_v2_candidate_layouts(
    layouts: tuple[tuple[EvidenceSearchCandidate, ...], ...], offending: tuple[int, ...]
) -> tuple[tuple[EvidenceSearchCandidate, ...], ...]:
    """Split each overgrown non-singleton page without changing candidate order."""

    offending_set = set(offending)
    split: list[tuple[EvidenceSearchCandidate, ...]] = []
    for number, page in enumerate(layouts):
        if number not in offending_set:
            split.append(page)
            continue
        midpoint = len(page) // 2
        split.extend((page[:midpoint], page[midpoint:]))
    return tuple(split)


def _validate_materialized_v2_pages(
    pages: tuple[EvidenceSearchPage, ...],
    *,
    policy: EvidenceSearchPolicy,
    envelope_measure: Callable[[EvidenceSearchPage], tuple[int, int]] | None = None,
) -> None:
    """Reject a page set whose published navigation equations are not exact."""

    if not pages:
        raise OperationalRetrievalFailure("v2 evidence search materialized no pages")
    projected_bytes = sum(page.serialized_response_bytes for page in pages)
    projected_tokens = sum(page.estimated_response_tokens for page in pages)
    cumulative_bytes = 0
    cumulative_tokens = 0
    expected_prior = 0
    total = pages[0].total_candidate_count
    for number, page in enumerate(pages, start=1):
        if envelope_measure is None:
            actual_bytes = len(canonical_json_bytes(page.model_facing_payload()))
            actual_tokens = _estimate_response_tokens(actual_bytes)
        else:
            actual_bytes, actual_tokens = envelope_measure(page)
        if page.serialized_response_bytes != actual_bytes:
            raise OperationalRetrievalFailure("v2 page serialized-byte measurement is not exact")
        if page.estimated_response_tokens != actual_tokens:
            raise OperationalRetrievalFailure("v2 page token measurement is not exact")
        cumulative_bytes += actual_bytes
        cumulative_tokens += page.estimated_response_tokens
        if (
            page.page_number != number
            or page.total_page_count != len(pages)
            or page.prior_candidate_count != expected_prior
            or page.returned_candidate_count != len(page.candidates)
            or page.remaining_candidate_count != total - expected_prior - len(page.candidates)
            or page.remaining_page_count != len(pages) - number
            or page.current_cumulative_response_bytes != cumulative_bytes
            or page.current_cumulative_estimated_tokens != cumulative_tokens
            or page.projected_cumulative_response_bytes != projected_bytes
            or page.projected_cumulative_estimated_tokens != projected_tokens
        ):
            raise OperationalRetrievalFailure("v2 page navigation equations are inconsistent")
        normal_bound_violated = (
            actual_bytes > policy.serialized_byte_ceiling
            or page.estimated_response_tokens > policy.estimated_token_target
        )
        if normal_bound_violated:
            if (
                page.limiting_bounds != ("oversized_candidate",)
                or actual_bytes > policy.oversized_candidate_byte_ceiling
            ):
                raise OperationalRetrievalFailure("v2 page violates a hard response bound")
        elif actual_bytes > policy.serialized_byte_ceiling:
            raise OperationalRetrievalFailure("v2 page exceeds its normal response ceiling")
        expected_prior += len(page.candidates)


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
