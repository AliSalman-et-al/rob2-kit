"""Evidence boundary schemas; search and bundle workflows belong to issue #19."""

from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.domain.revisions import ContentHash, Identifier, RecordReference, Revision


class VerificationStatus(StrEnum):
    MACHINE_VERIFIED = "machine_verified"
    REVIEW_REQUIRED = "review_required"
    VISUAL_ONLY = "visual_only"


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
    transcription: str = Field(min_length=1)
    verification_status: VerificationStatus = VerificationStatus.REVIEW_REQUIRED


class EvidenceBundle(Revision):
    dependency_roles = {
        "result_spec": "dependency:result-spec",
        "items": "dependency:evidence-item",
    }
    result_spec: RecordReference
    items: tuple[RecordReference, ...]
    frozen_content_hash: ContentHash


class EvidenceConsiderationManifest(Revision):
    dependency_roles = {
        "bundle": "dependency:evidence-bundle",
        "considered_items": "dependency:considered-item",
    }
    sq_id: Identifier
    bundle: RecordReference
    considered_items: tuple[RecordReference, ...]


class ContextViewManifest(Revision):
    dependency_roles = {"ordered_items": "dependency:context-item"}
    context_kind: Identifier
    ordered_items: tuple[RecordReference, ...]
    transformation_ids: tuple[Identifier, ...] = ()
