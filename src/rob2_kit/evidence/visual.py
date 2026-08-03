"""Relevance-gated, bounded visual inspection workflow."""

from __future__ import annotations

import base64
import binascii
import json
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier


class VisualCandidateKind(StrEnum):
    TABLE = "table"
    FIGURE = "figure"
    FLOWCHART = "flowchart"
    FOOTNOTE_OR_LEGEND = "footnote_or_legend"
    SUSPECT_EXTRACTION = "suspect_extraction"


class VisualNominationBasis(StrEnum):
    RESULT_SPEC_LOCATOR = "result_spec_locator"
    GUIDANCE_MAPPING = "guidance_mapping"
    RETRIEVED_REFERENCE = "retrieved_reference"
    NUMERICAL_CONFLICT = "numerical_conflict"
    PARSE_RENDER_DISCREPANCY = "parse_render_discrepancy"
    AGENT_REASON = "agent_reason"


class DecisionCriticalContent(StrEnum):
    DENOMINATOR = "denominator"
    EXCLUSION = "exclusion"
    MISSING_DATA_COUNT = "missing_data_count"
    ANALYSIS_POPULATION = "analysis_population"


class CropBox(FrozenModel):
    left: float = Field(ge=0)
    top: float = Field(ge=0)
    right: float = Field(gt=0)
    bottom: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_extent(self) -> CropBox:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("crop must have positive width and height")
        return self


class VisualCandidate(FrozenModel):
    candidate_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    sq_id: Identifier
    page: int = Field(ge=1)
    kind: VisualCandidateKind
    nomination_basis: VisualNominationBasis
    relevance_reason: str = Field(min_length=1)
    initial_crop: CropBox
    context_inside_crop: bool
    small_type: bool = False
    parse_render_discrepancy: bool = False
    decision_critical: tuple[DecisionCriticalContent, ...] = ()

    @model_validator(mode="after")
    def validate_relevance(self) -> VisualCandidate:
        if (
            self.nomination_basis is VisualNominationBasis.AGENT_REASON
            and not _states_decision_impact(self.relevance_reason)
        ):
            raise ValueError(
                "complexity alone cannot nominate a visual; the attributable agent reason "
                "must connect it to an active SQ and likely decision impact"
            )
        if (
            self.nomination_basis is VisualNominationBasis.PARSE_RENDER_DISCREPANCY
            and not self.parse_render_discrepancy
        ):
            raise ValueError("parse/render discrepancy nominations must identify the discrepancy")
        return self


def _states_decision_impact(reason: str) -> bool:
    normalized = reason.casefold()
    impacts = (
        "answer",
        "bias",
        "decision",
        "denominator",
        "exclusion",
        "missing",
        "population",
        "randomization",
        "allocation",
    )
    return ("active sq" in normalized or "signaling question" in normalized) and any(
        term in normalized for term in impacts
    )


class VisualRenderMode(StrEnum):
    CROP = "crop"
    FULL_PAGE = "full_page"


class VisualRenderRequest(FrozenModel):
    candidate_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    page: int = Field(ge=1)
    mode: VisualRenderMode
    dpi: Literal[144, 180, 216]
    crop: CropBox | None

    @model_validator(mode="after")
    def validate_crop_mode(self) -> VisualRenderRequest:
        if (self.mode is VisualRenderMode.CROP) != (self.crop is not None):
            raise ValueError("crop provenance is required exactly for crop renders")
        return self


class VisualCitation(FrozenModel):
    """Deterministic visual binding for a canonical text span.

    A citation is generated from canonical text and spatial provenance.  It
    does not claim that an agent inspected the image; only a
    :class:`VisualTranscriptionSubmission` carries that stronger, explicitly
    visual-only status.
    """

    citation_id: Identifier
    canonical_unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    page: int = Field(ge=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    quoted_text_hash: ContentHash
    boxes: tuple[CropBox, ...] = Field(min_length=1)
    geometry_scope: Literal["phrase_exact", "block"]
    geometry_hash: ContentHash
    render: VisualRenderRequest
    render_hash: ContentHash
    base_render_hash: ContentHash | None = None
    derived_render_hash: ContentHash | None = None
    overlay_hash: ContentHash | None = None
    crop_hash: ContentHash | None = None
    context_hash: ContentHash | None = None
    agent_inspected: Literal[False] = False
    citation_hash: ContentHash

    @model_validator(mode="after")
    def validate_span(self) -> VisualCitation:
        if self.span_end <= self.span_start:
            raise ValueError("visual citation span_end must be greater than span_start")
        if self.render.source_id != self.source_id:
            raise ValueError("visual citation render source does not match canonical source")
        if self.render.source_artifact_hash != self.source_artifact_hash:
            raise ValueError("visual citation render artifact does not match canonical source")
        if self.render.page != self.page:
            raise ValueError("visual citation render page does not match canonical span")
        return self


def materialize_visual_citation(
    canonical_unit: object,
    *,
    span_start: int,
    span_end: int,
    render: VisualRenderRequest | None = None,
    base_render_hash: ContentHash | None = None,
    derived_render_hash: ContentHash | None = None,
) -> VisualCitation:
    """Create a hash-stable citation from a canonical unit's exact span.

    The function intentionally accepts the canonical unit structurally to
    avoid coupling the visual module to the search index implementation.  A
    unit must provide ``unit_id``, ``source_id``, ``source_artifact_hash``,
    ``parse_id``, ``page``, ``text``, and optional ``spatial`` attributes.
    """

    text_value = getattr(canonical_unit, "text", None)
    claim_quote = False
    if text_value is None:
        text_value = getattr(canonical_unit, "quoted_text", "")
        claim_quote = True
        claim_start = getattr(canonical_unit, "span_start", None)
        claim_end = getattr(canonical_unit, "span_end", None)
        if (claim_start, claim_end) != (span_start, span_end):
            raise ValueError("visual citation span must match the accepted canonical quote")
    text = str(text_value)
    if (
        not claim_quote
        and (span_start < 0 or span_end <= span_start or span_end > len(text))
    ):
        raise ValueError("visual citation span must be an exact canonical text range")
    if claim_quote and not text:
        raise ValueError("accepted canonical quotes must contain text")
    spatial = getattr(canonical_unit, "spatial", None)
    if spatial is None:
        raise ValueError("spatially anchored canonical units are required for visual citations")
    if len(spatial) != 4:
        raise ValueError("canonical spatial bounds must contain four coordinates")
    source_id = str(getattr(canonical_unit, "source_id"))
    source_artifact_hash = str(getattr(canonical_unit, "source_artifact_hash"))
    parse_id = str(getattr(canonical_unit, "parse_id"))
    page = int(getattr(canonical_unit, "page"))
    unit_id = str(
        getattr(
            canonical_unit,
            "unit_id",
            getattr(canonical_unit, "canonical_unit_id", ""),
        )
    )
    if not unit_id:
        raise ValueError("canonical visual citations require a canonical unit identity")
    block_crop = CropBox(
        left=float(spatial[0]),
        top=float(spatial[1]),
        right=float(spatial[2]),
        bottom=float(spatial[3]),
    )
    word_boxes = tuple(getattr(canonical_unit, "word_boxes", ()) or ())
    # Exact phrase geometry is safe only when the selected range starts and
    # ends on retained word boundaries and every intervening word is retained.
    covered = tuple(
        item
        for item in word_boxes
        if item.span_end > span_start and item.span_start < span_end
    )
    phrase_exact = bool(covered) and (
        covered[0].span_start == span_start and covered[-1].span_end == span_end
    )
    if phrase_exact:
        cursor = span_start
        for item in covered:
            if text[cursor : item.span_start].strip():
                phrase_exact = False
                break
            cursor = item.span_end
        if text[cursor:span_end].strip():
            phrase_exact = False
    if phrase_exact:
        boxes = tuple(
            CropBox(
                left=float(item.spatial[0]),
                top=float(item.spatial[1]),
                right=float(item.spatial[2]),
                bottom=float(item.spatial[3]),
            )
            for item in covered
        )
    else:
        boxes = (block_crop,)
    geometry_scope: Literal["phrase_exact", "block"] = (
        "phrase_exact" if phrase_exact else "block"
    )
    # The render crop is the bounding rectangle of all retained word boxes;
    # block-level fallback remains explicit rather than implying exactness.
    crop = CropBox(
        left=min(item.left for item in boxes),
        top=min(item.top for item in boxes),
        right=max(item.right for item in boxes),
        bottom=max(item.bottom for item in boxes),
    )
    if render is None:
        render = VisualRenderRequest(
            candidate_id=unit_id,
            source_id=source_id,
            source_artifact_hash=source_artifact_hash,
            page=page,
            mode=VisualRenderMode.CROP,
            dpi=144,
            crop=crop,
        )
    if render.source_id != source_id or render.source_artifact_hash != source_artifact_hash:
        raise ValueError("visual citation render provenance does not match canonical unit")
    if render.page != page:
        raise ValueError("visual citation render page does not match canonical unit")
    quoted_text = text if claim_quote else text[span_start:span_end]
    quoted_text_hash = sha256_digest(quoted_text.encode("utf-8"))
    payload = {
        "unit_id": unit_id,
        "source_id": source_id,
        "source_artifact_hash": source_artifact_hash,
        "parse_id": parse_id,
        "page": page,
        "span_start": span_start,
        "span_end": span_end,
        "quoted_text_hash": quoted_text_hash,
        "boxes": [item.model_dump(mode="json") for item in boxes],
        "geometry_scope": geometry_scope,
        "geometry_hash": canonical_hash(
            {
                "unit_id": unit_id,
                "span_start": span_start,
                "span_end": span_end,
                "boxes": [item.model_dump(mode="json") for item in boxes],
                "scope": geometry_scope,
            }
        ),
        "render": render.model_dump(mode="json"),
        "render_hash": canonical_hash(render),
        "base_render_hash": base_render_hash,
        "derived_render_hash": derived_render_hash,
        "agent_inspected": False,
    }
    citation_hash = canonical_hash(payload)
    citation_id = f"visual-citation:{citation_hash.removeprefix('sha256:')[:24]}"
    return VisualCitation(
        citation_id=citation_id,
        canonical_unit_id=unit_id,
        source_id=source_id,
        source_artifact_hash=source_artifact_hash,
        parse_id=parse_id,
        page=page,
        span_start=span_start,
        span_end=span_end,
        quoted_text_hash=quoted_text_hash,
        boxes=boxes,
        geometry_scope=geometry_scope,
        geometry_hash=canonical_hash(
            {
                "unit_id": unit_id,
                "span_start": span_start,
                "span_end": span_end,
                "boxes": [item.model_dump(mode="json") for item in boxes],
                "scope": geometry_scope,
            }
        ),
        render=render,
        render_hash=canonical_hash(render),
        base_render_hash=base_render_hash,
        derived_render_hash=derived_render_hash,
        citation_hash=citation_hash,
    )


# ``build_visual_citation`` is a concise alias for host adapters and callers
# that use the terminology from the v1 specification.
build_visual_citation = materialize_visual_citation


class VisualInspectionPolicy(FrozenModel):
    initial_dpi: Literal[144] = 144
    escalation_dpi: tuple[Literal[180, 216], Literal[216]] = (180, 216)

    def initial_request(self, candidate: VisualCandidate) -> VisualRenderRequest:
        return VisualRenderRequest(
            candidate_id=candidate.candidate_id,
            source_id=candidate.source_id,
            source_artifact_hash=candidate.source_artifact_hash,
            page=candidate.page,
            mode=VisualRenderMode.CROP,
            dpi=self.initial_dpi,
            crop=candidate.initial_crop,
        )

    def escalate(
        self,
        candidate: VisualCandidate,
        current: VisualRenderRequest,
        *,
        still_ambiguous: bool,
    ) -> VisualRenderRequest | None:
        if current.candidate_id != candidate.candidate_id:
            raise ValueError("render request must belong to the candidate")
        if (
            current.source_id != candidate.source_id
            or current.source_artifact_hash != candidate.source_artifact_hash
            or current.page != candidate.page
        ):
            raise ValueError("render request provenance must match the candidate")
        if not still_ambiguous:
            return current
        if current.mode is VisualRenderMode.CROP and not candidate.context_inside_crop:
            return current.model_copy(
                update={"mode": VisualRenderMode.FULL_PAGE, "crop": None}
            )
        if not candidate.small_type:
            return None
        dpi_sequence = (self.initial_dpi, *self.escalation_dpi)
        current_index = dpi_sequence.index(current.dpi)
        next_dpi = (
            dpi_sequence[current_index + 1]
            if current_index + 1 < len(dpi_sequence)
            else None
        )
        if next_dpi is None:
            return None
        return current.model_copy(update={"dpi": next_dpi})


class VisualCandidatePage(FrozenModel):
    snapshot_hash: ContentHash
    candidates: tuple[VisualCandidate, ...]
    next_cursor: str | None


class VisualInspectionQueue:
    """Stable, unbounded candidate accounting with snapshot-bound pagination."""

    def __init__(self, candidates: tuple[VisualCandidate, ...]) -> None:
        ids = [item.candidate_id for item in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("visual candidate IDs must be unique")
        self._candidates = tuple(sorted(candidates, key=lambda item: item.candidate_id))
        self._snapshot_hash = canonical_hash(
            [item.model_dump(mode="json") for item in self._candidates]
        )

    @property
    def snapshot_hash(self) -> ContentHash:
        return self._snapshot_hash

    def candidate_ids(self) -> frozenset[Identifier]:
        return frozenset(item.candidate_id for item in self._candidates)

    def page(self, *, limit: int = 1, cursor: str | None = None) -> VisualCandidatePage:
        if limit < 1:
            raise ValueError("limit must be positive")
        offset = 0
        if cursor is not None:
            payload = _decode_cursor(cursor)
            if payload.get("snapshot_hash") != self._snapshot_hash:
                raise ValueError("visual candidate cursor belongs to a different snapshot")
            raw_offset = payload.get("offset")
            if not isinstance(raw_offset, int) or raw_offset < 0:
                raise ValueError("invalid visual candidate cursor")
            offset = raw_offset
        selected = self._candidates[offset : offset + limit]
        next_offset = offset + len(selected)
        next_cursor = (
            _encode_cursor(self._snapshot_hash, next_offset)
            if next_offset < len(self._candidates)
            else None
        )
        return VisualCandidatePage(
            snapshot_hash=self._snapshot_hash,
            candidates=selected,
            next_cursor=next_cursor,
        )


def _encode_cursor(snapshot_hash: str, offset: int) -> str:
    raw = json.dumps(
        {"offset": offset, "snapshot_hash": snapshot_hash},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> dict[str, object]:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (
        binascii.Error,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError("invalid visual candidate cursor") from error


class VisualCandidateDispositionKind(StrEnum):
    INSPECTED_IRRELEVANT = "inspected_irrelevant"
    TRANSCRIBED = "transcribed"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"


class VisualCandidateDisposition(FrozenModel):
    candidate_id: Identifier
    kind: VisualCandidateDispositionKind
    limitation: str | None = Field(default=None, min_length=1)
    duplicate_of: Identifier | None = None

    @model_validator(mode="after")
    def validate_kind_details(self) -> VisualCandidateDisposition:
        if (
            self.kind is not VisualCandidateDispositionKind.AMBIGUOUS
            and self.limitation is not None
        ):
            raise ValueError("only ambiguous visual candidates may carry a limitation")
        if (self.kind is VisualCandidateDispositionKind.AMBIGUOUS) != (
            self.limitation is not None
        ):
            raise ValueError("ambiguous visual candidates require exactly one coverage limitation")
        if (self.kind is VisualCandidateDispositionKind.DUPLICATE) != (
            self.duplicate_of is not None
        ):
            raise ValueError("duplicate visual candidates require exactly one covered candidate")
        if (
            self.kind is not VisualCandidateDispositionKind.DUPLICATE
            and self.duplicate_of is not None
        ):
            raise ValueError("only duplicate visual candidates may reference another candidate")
        if self.duplicate_of == self.candidate_id:
            raise ValueError("a visual candidate cannot be a duplicate of itself")
        return self


class VisualTranscriptionSubmission(FrozenModel):
    transcription_id: Identifier
    candidate_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    sq_id: Identifier
    transcription: str = Field(min_length=1)
    render: VisualRenderRequest
    verification_status: Literal["visual_only"] = "visual_only"
    review_required: Literal[True] = True
    decision_critical: tuple[DecisionCriticalContent, ...] = ()
    content_hash: ContentHash


class VisualInspectionResult(FrozenModel):
    disposition: VisualCandidateDisposition
    transcription: VisualTranscriptionSubmission | None = None
    coverage_limited: bool = False

    @model_validator(mode="after")
    def validate_ambiguity(self) -> VisualInspectionResult:
        ambiguous = self.disposition.kind is VisualCandidateDispositionKind.AMBIGUOUS
        if self.coverage_limited != ambiguous:
            raise ValueError("ambiguous visual candidates must remain coverage_limited")
        transcribed = self.disposition.kind is VisualCandidateDispositionKind.TRANSCRIBED
        if transcribed != (self.transcription is not None):
            raise ValueError("transcribed dispositions require exactly one transcription")
        return self

    def establishes_no_information_basis(self) -> bool:
        return not self.coverage_limited


class VisualInspectionManifest(FrozenModel):
    snapshot_hash: ContentHash
    results: tuple[VisualInspectionResult, ...]

    @classmethod
    def complete(
        cls,
        *,
        queue: VisualInspectionQueue,
        results: tuple[VisualInspectionResult, ...],
    ) -> VisualInspectionManifest:
        candidate_ids = queue.candidate_ids()
        result_ids = [result.disposition.candidate_id for result in results]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("every nominated visual candidate requires one disposition")
        if set(result_ids) != candidate_ids:
            raise ValueError("every nominated visual candidate requires one disposition")
        for result in results:
            duplicate_of = result.disposition.duplicate_of
            if duplicate_of is not None and duplicate_of not in candidate_ids:
                raise ValueError("duplicate visual candidates must reference a nominated candidate")
        dispositions = {
            result.disposition.candidate_id: result.disposition for result in results
        }
        for result in results:
            current = result.disposition.candidate_id
            seen: set[str] = set()
            while True:
                duplicate = dispositions[current].duplicate_of
                if duplicate is None:
                    break
                if current in seen:
                    raise ValueError("duplicate visual candidate references must be acyclic")
                seen.add(current)
                current = duplicate
        ordered_results: tuple[VisualInspectionResult, ...] = tuple(
            sorted(results, key=_result_candidate_id)
        )
        return cls(
            snapshot_hash=queue.snapshot_hash,
            results=ordered_results,
        )

    def establishes_no_information_basis(self) -> bool:
        return all(result.establishes_no_information_basis() for result in self.results)


def _result_candidate_id(result: VisualInspectionResult) -> str:
    return result.disposition.candidate_id


def submit_visual_inspection(
    *,
    candidate: VisualCandidate,
    render: VisualRenderRequest,
    disposition: VisualCandidateDispositionKind,
    transcription: str | None = None,
    limitation: str | None = None,
    duplicate_of: Identifier | None = None,
) -> VisualInspectionResult:
    """Submit the sole terminal outcome for one candidate work unit."""
    if render.candidate_id != candidate.candidate_id:
        raise ValueError("render request must belong to the submitted candidate")
    if (
        render.source_id != candidate.source_id
        or render.source_artifact_hash != candidate.source_artifact_hash
        or render.page != candidate.page
    ):
        raise ValueError("render provenance must bind the candidate source artifact and page")
    if disposition is VisualCandidateDispositionKind.TRANSCRIBED:
        if not transcription:
            raise ValueError("transcribed candidates require a legible transcription")
        payload = {
            "transcription_id": f"transcription:{candidate.candidate_id.split(':', 1)[1]}",
            "candidate_id": candidate.candidate_id,
            "source_id": candidate.source_id,
            "source_artifact_hash": candidate.source_artifact_hash,
            "sq_id": candidate.sq_id,
            "transcription": transcription,
            "render": render.model_dump(mode="json"),
            "verification_status": "visual_only",
            "review_required": True,
            "decision_critical": candidate.decision_critical,
        }
        visual_transcription = VisualTranscriptionSubmission(
            **payload,
            content_hash=canonical_hash(payload),
        )
    else:
        if transcription is not None:
            raise ValueError("only transcribed candidates may contain transcription text")
        visual_transcription = None
    candidate_disposition = VisualCandidateDisposition(
        candidate_id=candidate.candidate_id,
        kind=disposition,
        limitation=limitation,
        duplicate_of=duplicate_of,
    )
    return VisualInspectionResult(
        disposition=candidate_disposition,
        transcription=visual_transcription,
        coverage_limited=disposition is VisualCandidateDispositionKind.AMBIGUOUS,
    )
