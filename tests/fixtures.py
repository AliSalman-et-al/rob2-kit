"""Reusable canonical-record builders."""

from datetime import UTC, datetime
from typing import TypedDict

from rob2_kit.domain.revisions import Actor, ActorKind, Dependency, RecordReference

HASH = "sha256:" + ("a" * 64)


class RevisionFields(TypedDict):
    entity_id: str
    revision_id: str
    actor: Actor
    observed_at: datetime


def actor() -> Actor:
    return Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test system")


def revision_fields(name: str = "record") -> RevisionFields:
    return {
        "entity_id": f"entity:{name}",
        "revision_id": f"revision:{name}-1",
        "actor": actor(),
        "observed_at": datetime(2026, 7, 29, 12, tzinfo=UTC),
    }


def reference(name: str = "record") -> RecordReference:
    return RecordReference(
        entity_id=f"entity:{name}",
        revision_id=f"revision:{name}-1",
        content_hash=HASH,
    )


def dependency(name: str = "record", role: str = "dependency:input") -> Dependency:
    record = reference(name)
    return Dependency(**record.model_dump(), role=role)
