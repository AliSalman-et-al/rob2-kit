"""Evidence boundary schemas; search and bundle workflows belong to issue #19."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
    Revision,
)


class VerificationStatus(StrEnum):
    MACHINE_VERIFIED = "machine_verified"
    REVIEW_REQUIRED = "review_required"
    VISUAL_ONLY = "visual_only"


class EvidenceCoverageState(StrEnum):
    COMPLETE = "complete"
    COMPLETE_WITH_LIMITATIONS = "complete_with_limitations"
    INCOMPLETE = "incomplete"


class ConsiderationDisposition(StrEnum):
    """The attributable pre-answer disposition of one frozen evidence item."""

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXTUAL = "contextual"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"
    IMMATERIAL = "immaterial"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


class EvidenceConsideration(FrozenModel):
    """One complete, question-specific consideration-manifest entry."""

    item_id: Identifier
    disposition: ConsiderationDisposition
    basis: str | None = None
    superseded_by: Identifier | None = None

    @model_validator(mode="after")
    def validate_basis(self) -> "EvidenceConsideration":
        if self.disposition is ConsiderationDisposition.SUPERSEDED and (
            not self.basis or self.superseded_by is None
        ):
            raise ValueError("superseded evidence requires replacement and chronology basis")
        if (
            self.disposition is not ConsiderationDisposition.SUPERSEDED
            and self.superseded_by is not None
        ):
            raise ValueError("superseded_by is valid only for superseded evidence")
        if self.superseded_by == self.item_id:
            raise ValueError("evidence cannot supersede itself")
        if self.disposition is ConsiderationDisposition.UNRESOLVED and not self.basis:
            raise ValueError("unresolved evidence requires an explicit limitation")
        return self


class EvidenceCandidateDispositionRecord(Revision):
    """Frozen pre-answer disposition record retained in Verification archives."""

    dependency_roles = {"items": "dependency:evidence-item"}
    result_id: Identifier
    domain_id: Identifier
    items: tuple[RecordReference, ...] = ()
    dispositions: tuple[EvidenceConsideration, ...] = ()


class EvidenceCoverageReceiptRecord(Revision):
    """Frozen search-receipt payloads retained without a host-side query."""

    result_id: Identifier
    domain_id: Identifier
    receipts: tuple[dict[str, Any], ...] = ()


class EvidenceCandidate(Revision):
    dependency_roles = {
        "canonical_unit": "dependency:canonical-unit",
        "source": "dependency:source",
    }
    canonical_unit: RecordReference
    source: RecordReference
    relevance_reason: str = Field(min_length=1)


class EvidenceClaim(Revision):
    dependency_roles = {
        "canonical_unit": "dependency:canonical-unit",
        "source": "dependency:source",
    }
    canonical_unit: RecordReference
    source: RecordReference
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    quoted_text_hash: ContentHash
    claim_type: Identifier
    verification_status: VerificationStatus

    @model_validator(mode="after")
    def validate_span(self) -> "EvidenceClaim":
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        return self


class DerivedFact(Revision):
    dependency_roles = {"inputs": "dependency:derived-fact-input"}
    derivation_id: Identifier
    inputs: tuple[RecordReference, ...]
    value: str
    units: str | None = None


class VisualTranscription(Revision):
    dependency_roles = {"source": "dependency:source"}
    source: RecordReference
    page: int = Field(ge=1)
    region: tuple[float, float, float, float]
    render_mode: Literal["crop", "full_page"]
    dpi: Literal[144, 180, 216]
    transcription: str = Field(min_length=1)
    verification_status: Literal[VerificationStatus.VISUAL_ONLY] = VerificationStatus.VISUAL_ONLY
    review_required: Literal[True] = True
    decision_critical: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_region(self) -> "VisualTranscription":
        left, top, right, bottom = self.region
        if min(self.region) < 0 or right <= left or bottom <= top:
            raise ValueError("visual transcription region must have positive extent")
        return self


class EvidenceBundle(Revision):
    dependency_roles = {
        "result_spec": "dependency:result-spec",
        "disposition": "dependency:evidence-disposition",
        "items": "dependency:evidence-item",
        "coverage_receipts": "dependency:search-coverage",
        "consideration_manifest": "dependency:evidence-consideration",
    }
    result_spec: RecordReference
    disposition: RecordReference
    items: tuple[RecordReference, ...]
    frozen_content_hash: ContentHash
    # A bundle is question-specific in lean-v1.  The optional default keeps
    # pre-issue domain records readable while all new engine records pin it.
    sq_id: Identifier | None = None
    domain_id: Identifier | None = None
    coverage_receipts: tuple[RecordReference, ...] = ()
    consideration_manifest: RecordReference | None = None
    coverage_state: EvidenceCoverageState = EvidenceCoverageState.COMPLETE
    coverage_limitations: tuple[str, ...] = ()
    no_information_basis: bool = False
    conflicts: tuple[tuple[Identifier, ...], ...] = ()

    @model_validator(mode="after")
    def validate_audit_metadata(self) -> "EvidenceBundle":
        item_ids = {item.entity_id for item in self.items}
        if any(len(conflict) < 2 or not set(conflict) <= item_ids for conflict in self.conflicts):
            raise ValueError("source conflicts must bind at least two frozen Evidence items")
        if self.no_information_basis and (
            self.coverage_state is not EvidenceCoverageState.COMPLETE or self.coverage_limitations
        ):
            raise ValueError("no-information basis requires complete, unlimited coverage")
        if self.no_information_basis and not self.coverage_receipts:
            raise ValueError("no-information basis requires Search coverage receipts")
        if self.sq_id is not None and self.consideration_manifest is None:
            raise ValueError("question-specific Evidence Bundles require a consideration manifest")
        return self


class EvidenceConsiderationManifest(Revision):
    dependency_roles = {
        "bundle": "dependency:evidence-bundle",
        "considered_items": "dependency:considered-item",
    }
    sq_id: Identifier
    # The pre-freeze manifest is durable before its bundle exists.  The
    # optional binding is then filled by the final manifest revision that
    # supersedes that pre-freeze accounting record.
    bundle: RecordReference | None = None
    considered_items: tuple[RecordReference, ...]
    dispositions: tuple[EvidenceConsideration, ...] = ()

    @model_validator(mode="after")
    def validate_complete_manifest(self) -> "EvidenceConsiderationManifest":
        item_ids = tuple(item.entity_id for item in self.considered_items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("consideration manifest item IDs must be unique")
        disposition_ids = tuple(item.item_id for item in self.dispositions)
        if item_ids and set(disposition_ids) != set(item_ids):
            raise ValueError("consideration manifest dispositions must cover every item")
        if len(disposition_ids) != len(set(disposition_ids)):
            raise ValueError("consideration manifest dispositions must be unique")
        if any(
            item.disposition is ConsiderationDisposition.UNRESOLVED for item in self.dispositions
        ):
            raise ValueError("an Evidence Bundle cannot freeze with unresolved material items")
        return self


class ContextViewManifest(Revision):
    dependency_roles = {"ordered_items": "dependency:context-item"}
    context_kind: Identifier
    ordered_items: tuple[RecordReference, ...]
    transformation_ids: tuple[Identifier, ...] = ()
