"""Relevance-gated, bounded visual inspection workflow."""

from __future__ import annotations

import base64
import json
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
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
    page: int
    mode: VisualRenderMode
    dpi: Literal[144, 180, 216]
    crop: CropBox | None

    @model_validator(mode="after")
    def validate_crop_mode(self) -> VisualRenderRequest:
        if (self.mode is VisualRenderMode.CROP) != (self.crop is not None):
            raise ValueError("crop provenance is required exactly for crop renders")
        return self


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
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid visual candidate cursor") from error


class VisualCandidateDispositionKind(StrEnum):
    INSPECTED_IRRELEVANT = "inspected_irrelevant"
    TRANSCRIBED = "transcribed"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"


class VisualCandidateDisposition(FrozenModel):
    candidate_id: Identifier
    kind: VisualCandidateDispositionKind
    limitation: str | None = None
    duplicate_of: Identifier | None = None

    @model_validator(mode="after")
    def validate_kind_details(self) -> VisualCandidateDisposition:
        if (self.kind is VisualCandidateDispositionKind.AMBIGUOUS) != (
            self.limitation is not None
        ):
            raise ValueError("ambiguous visual candidates require exactly one coverage limitation")
        if (self.kind is VisualCandidateDispositionKind.DUPLICATE) != (
            self.duplicate_of is not None
        ):
            raise ValueError("duplicate visual candidates require exactly one covered candidate")
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
