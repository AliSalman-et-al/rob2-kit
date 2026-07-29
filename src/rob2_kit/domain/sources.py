"""Source inventory boundary contracts."""

from enum import StrEnum

from pydantic import Field

from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
    Revision,
)


class SourceAvailability(StrEnum):
    OBTAINED = "obtained"
    MISSING = "missing"
    DISCOVERED = "discovered"


class SourceCriticality(StrEnum):
    REQUIRED = "required"
    EXPECTED = "expected"
    OPTIONAL = "optional"


class SourceDescriptor(FrozenModel):
    source_id: Identifier
    title: str = Field(min_length=1)
    roles: tuple[Identifier, ...]
    criticality: SourceCriticality
    availability: SourceAvailability
    artifact_hash: ContentHash | None = None
    external_identifiers: tuple[str, ...] = ()


class SourceComponent(Revision):
    dependency_roles = {"source": "dependency:source"}
    source: RecordReference
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    roles: tuple[Identifier, ...]


class SourceInventoryRevision(Revision):
    dependency_roles = {"result_spec": "dependency:result-spec"}
    result_spec: RecordReference
    sources: tuple[SourceDescriptor, ...]
    coverage_limitations: tuple[str, ...] = ()
