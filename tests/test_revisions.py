from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from rob2_kit.domain.revisions import (
    Dependency,
    RecordReference,
    Revision,
    SchemaEnvelope,
    Supersession,
)
from tests.fixtures import HASH, revision_fields


def test_revision_round_trips_through_public_schema() -> None:
    revision = Revision(
        **revision_fields(),
        dependencies=(
            Dependency(
                entity_id="entity:input",
                revision_id="revision:input-1",
                role="dependency:result-spec",
                content_hash=HASH,
            ),
        ),
        supersedes=Supersession(
            entity_id="entity:record",
            revision_id="revision:record-0",
            content_hash=HASH,
            reason="Correction",
        ),
    )
    assert Revision.model_validate_json(revision.model_dump_json()) == revision


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "v1"),
        ("entity_id", "not opaque"),
        ("revision_id", "not opaque"),
    ],
)
def test_invalid_revision_fields_are_rejected(field: str, value: str) -> None:
    fields: dict[str, object] = dict(revision_fields())
    fields[field] = value
    with pytest.raises(ValidationError):
        Revision.model_validate(fields)


def test_duplicate_and_self_dependencies_are_rejected() -> None:
    dependency = Dependency(
        entity_id="entity:input",
        revision_id="revision:record-1",
        role="dependency:input",
        content_hash=HASH,
    )
    with pytest.raises(ValidationError):
        Revision(**revision_fields(), dependencies=(dependency,))


def test_non_utc_observed_time_is_rejected() -> None:
    fields: dict[str, object] = dict(revision_fields())
    fields["observed_at"] = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))
    with pytest.raises(ValidationError):
        Revision.model_validate(fields)


def test_schema_envelope_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SchemaEnvelope.model_validate(
            {"record_type": "record:test", "payload": {}, "unexpected": True}
        )


def test_revision_subclass_rejects_unlisted_record_reference() -> None:
    class ReferencingRevision(Revision):
        dependency_roles = {"source": "dependency:source"}
        source: RecordReference

    with pytest.raises(ValidationError):
        ReferencingRevision(
            **revision_fields("referencing"),
            source=RecordReference(
                entity_id="entity:source",
                revision_id="revision:source-1",
                content_hash=HASH,
            ),
        )


def test_revision_rejects_cross_entity_supersession() -> None:
    with pytest.raises(ValidationError):
        Revision(
            **revision_fields(),
            supersedes=Supersession(
                entity_id="entity:other",
                revision_id="revision:other-1",
                content_hash=HASH,
                reason="Not the same stable entity",
            ),
        )
