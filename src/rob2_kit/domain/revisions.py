"""Identifiers, provenance, dependencies, and immutable revision metadata."""

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0.0"
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]*:[A-Za-z0-9._~:-]+$"),
]
ContentHash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
SchemaVersion = Annotated[str, StringConstraints(pattern=r"^[1-9]\d*\.\d+\.\d+$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class Actor(FrozenModel):
    kind: ActorKind
    actor_id: Identifier
    display_name: str = Field(min_length=1)
    software_name: str | None = None
    software_version: str | None = None
    model_id: str | None = None


class Dependency(FrozenModel):
    entity_id: Identifier
    revision_id: Identifier
    role: Identifier
    content_hash: ContentHash


class Supersession(FrozenModel):
    entity_id: Identifier
    revision_id: Identifier
    content_hash: ContentHash
    reason: str = Field(min_length=1)


class Revision(FrozenModel):
    dependency_roles: ClassVar[dict[str, Identifier]] = {}
    schema_version: SchemaVersion = SCHEMA_VERSION
    entity_id: Identifier
    revision_id: Identifier
    dependencies: tuple[Dependency, ...] = ()
    actor: Actor
    observed_at: datetime
    supersedes: Supersession | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> "Revision":
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        if self.entity_id == self.revision_id:
            raise ValueError("entity_id and revision_id must be distinct")
        dependency_keys = {(d.entity_id, d.revision_id, d.role) for d in self.dependencies}
        if len(dependency_keys) != len(self.dependencies):
            raise ValueError("dependencies must be unique")
        if any(d.revision_id == self.revision_id for d in self.dependencies):
            raise ValueError("a revision cannot depend on itself")
        if self.supersedes:
            if self.supersedes.revision_id == self.revision_id:
                raise ValueError("a revision cannot supersede itself")
            if self.supersedes.entity_id != self.entity_id:
                raise ValueError("a revision can supersede only the same stable entity")
        for name in type(self).model_fields:
            if name in Revision.model_fields:
                continue
            expected_role = self.dependency_roles.get(name)
            references = tuple(_record_references(getattr(self, name)))
            if references and expected_role is None:
                raise ValueError(f"referenced field {name} must declare its dependency role")
            for reference in references:
                if not any(
                    dependency.entity_id == reference.entity_id
                    and dependency.revision_id == reference.revision_id
                    and dependency.content_hash == reference.content_hash
                    and dependency.role == expected_role
                    for dependency in self.dependencies
                ):
                    raise ValueError(
                        f"{name} must have a matching direct dependency with role {expected_role}"
                    )
        return self


class SchemaEnvelope(FrozenModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    record_type: Identifier
    payload: dict[str, Any]


class RecordReference(FrozenModel):
    entity_id: Identifier
    revision_id: Identifier
    content_hash: ContentHash


class ContractStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ValidationReceipt(FrozenModel):
    status: ContractStatus
    schema_version: SchemaVersion = SCHEMA_VERSION
    errors: tuple[str, ...] = ()
    kind: Literal["schema_validation"] = "schema_validation"


def _record_references(value: object) -> Iterable[RecordReference]:
    if isinstance(value, RecordReference):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _record_references(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _record_references(item)
