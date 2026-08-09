from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.domain.results import Comparison, Estimate, Result, ResultSpecRevision
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.storage import (
    ArtifactCorruptionError,
    ArtifactStore,
    DependencyInput,
    IntegrityError,
    LeaseConflictError,
    LeaseToken,
    RunIntegrityFailure,
    StaleWriterError,
    Transition,
    WorkflowLedger,
    dependency_fingerprint,
)
from rob2_kit.storage.ledger import ArtifactVerificationCache

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
ACTOR = Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test system")


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def ledger(tmp_path: Path) -> WorkflowLedger:
    return WorkflowLedger(tmp_path / "ledger.sqlite3", ArtifactStore(tmp_path / "artifacts"))


def transition(
    revision: str,
    *,
    entity: str = "entity:result",
    operation_key: str | None = None,
    dependencies: tuple[DependencyInput, ...] = (),
    checkpoint: str | None = None,
    artifact: bytes = b'{"answer":"yes"}',
) -> Transition:
    return Transition(
        scope="scope:trial-1",
        operation="operation:submit",
        operation_key=operation_key or f"operation-key:{revision}",
        actor=ACTOR,
        observed_at=NOW,
        entity_id=entity,
        revision_id=f"revision:{revision}",
        artifact=artifact,
        artifact_media_type="application/json",
        dependencies=dependencies,
        expected_dependency_fingerprint=dependency_fingerprint(dependencies),
        checkpoint=checkpoint,
        outcome="completed",
    )


def acquire(ledger: WorkflowLedger, owner: str = "process:writer") -> LeaseToken:
    return ledger.acquire_lease(owner, NOW, timedelta(minutes=5))


def embedded_result_spec(observed_at: datetime) -> ResultSpecRevision:
    return ResultSpecRevision(
        entity_id="result-spec:trial-a-mortality",
        revision_id="revision:result-spec-shared",
        actor=ACTOR,
        observed_at=observed_at,
        result=Result(
            result_id="result:trial-a-mortality",
            trial_id="trial:a",
            randomization_id="randomization:a",
            comparison=Comparison(
                experimental_arm_id="arm:experimental", comparator_arm_id="arm:control"
            ),
            effect_of_interest="assignment",
            outcome_construct="mortality",
            measurement_instrument="all-cause",
            time_point="30 days",
            analysis_population="intention-to-treat",
            analysis_model="risk ratio",
            effect_measure="risk_ratio",
            source_locator="report:primary/table:2",
        ),
        estimate=Estimate(value=Decimal("0.82")),
        provenance_note="primary report",
    )


def test_artifacts_are_addressed_by_exact_bytes_and_deduplicated(store: ArtifactStore) -> None:
    first = store.put(b"same bytes", "text/plain")
    second = store.put(b"same bytes", "application/octet-stream")
    different = store.put(b"same bytes\n", "text/plain")

    assert first.content_hash == second.content_hash
    assert first.path == second.path
    assert different.content_hash != first.content_hash
    assert store.read(first.content_hash) == b"same bytes"


def test_artifact_corruption_is_detected(store: ArtifactStore) -> None:
    artifact = store.put(b"trusted", "text/plain")
    artifact.path.write_bytes(b"changed")

    with pytest.raises(ArtifactCorruptionError, match=artifact.content_hash):
        store.read(artifact.content_hash)


def test_json_artifacts_are_canonicalized_before_hashing(store: ArtifactStore) -> None:
    spaced = store.put('{"z": 1, "a": "é"}'.encode(), "application/json")
    reordered = store.put('{"a":"é","z":1}'.encode(), "application/json")

    assert spaced.content_hash == reordered.content_hash
    assert store.read(spaced.content_hash) == '{"a":"é","z":1}'.encode()


def test_failed_transaction_exposes_no_event_revision_or_reachable_artifact(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            CREATE TRIGGER interrupt_revision_insert
            BEFORE INSERT ON revisions
            BEGIN
                SELECT RAISE(ABORT, 'simulated interruption');
            END
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        ledger.commit(transition("bad"), lease, now=NOW)

    assert ledger.events() == ()
    assert ledger.current_revisions() == ()
    assert ledger.reachable_artifact_hashes() == ()


def test_failed_batch_exposes_none_of_the_related_revisions(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            CREATE TRIGGER interrupt_second_revision
            BEFORE INSERT ON revisions
            WHEN NEW.revision_id = 'revision:sign-off'
            BEGIN
                SELECT RAISE(ABORT, 'simulated sign-off interruption');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        ledger.commit_batch(
            (
                transition("receipt", entity="review-receipt:sign-off"),
                transition("sign-off", entity="assessment-sign-off:result"),
            ),
            lease,
            now=NOW,
        )

    assert ledger.events() == ()
    assert ledger.current_revisions() == ()
    assert ledger.reachable_artifact_hashes() == ()


def test_committed_transition_atomically_updates_event_current_and_checkpoint(
    ledger: WorkflowLedger,
) -> None:
    result = ledger.commit(
        transition("one", checkpoint="checkpoint:parsed"), acquire(ledger), now=NOW
    )

    assert result.committed is True
    assert result.duplicate is False
    assert ledger.current_revisions()[0].revision_id == "revision:one"
    assert ledger.checkpoints()[0].checkpoint == "checkpoint:parsed"
    assert ledger.reachable_artifact_hashes() == (result.artifact_hash,)
    assert ledger.artifacts.read(result.artifact_hash) == b'{"answer":"yes"}'


def test_interruption_after_commit_resumes_from_durable_checkpoint(
    ledger: WorkflowLedger,
) -> None:
    result = ledger.commit(
        transition("one", checkpoint="checkpoint:parsed"), acquire(ledger), now=NOW
    )

    reopened = WorkflowLedger(ledger.path, ledger.artifacts)

    assert reopened.preflight().ok is True
    assert reopened.checkpoints()[0].revision_id == "revision:one"
    assert reopened.events()[0].event_id == result.event_id


def test_identical_duplicate_operation_returns_original_commit_without_new_event(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    original = ledger.commit(transition("one", operation_key="operation-key:same"), lease, now=NOW)
    duplicate = ledger.commit(transition("one", operation_key="operation-key:same"), lease, now=NOW)

    assert duplicate == original.model_copy(update={"duplicate": True})
    assert len(ledger.events()) == 1
    assert ledger.current_revisions()[0].revision_id == "revision:one"


def test_duplicate_operation_key_with_different_transition_is_an_integrity_failure(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    ledger.commit(transition("one", operation_key="operation-key:same"), lease, now=NOW)

    with pytest.raises(RunIntegrityFailure, match="operation key"):
        ledger.commit(transition("other", operation_key="operation-key:same"), lease, now=NOW)

    assert len(ledger.events()) == 1


def test_preflight_rejects_nested_result_spec_revision_identity_collision(
    ledger: WorkflowLedger,
) -> None:
    first = embedded_result_spec(NOW)
    second = embedded_result_spec(NOW + timedelta(seconds=1))
    lease = acquire(ledger)
    ledger.commit(
        transition(
            "first-envelope",
            entity="proposal:first",
            artifact=json.dumps({"result_spec": first.model_dump(mode="json")}).encode(),
        ),
        lease,
        now=NOW,
    )
    ledger.commit(
        transition(
            "second-envelope",
            entity="proposal:second",
            artifact=json.dumps({"result_spec": second.model_dump(mode="json")}).encode(),
        ),
        lease,
        now=NOW,
    )

    with pytest.raises(IntegrityError, match="ResultSpec revision identity"):
        ledger.preflight()


def test_preflight_compares_new_result_spec_artifacts_against_cached_identities(
    tmp_path: Path,
) -> None:
    verification_cache = ArtifactVerificationCache()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    first = WorkflowLedger(
        tmp_path / "ledger.sqlite3",
        artifacts,
        verification_cache=verification_cache,
    )
    first.commit(
        transition(
            "cached-envelope",
            entity="proposal:cached",
            artifact=json.dumps(
                {"result_spec": embedded_result_spec(NOW).model_dump(mode="json")}
            ).encode(),
        ),
        acquire(first),
        now=NOW,
    )
    assert first.preflight().ok is True
    assert verification_cache.result_spec_identities

    second = WorkflowLedger(
        first.path,
        artifacts,
        verification_cache=verification_cache,
    )
    second.commit(
        transition(
            "new-envelope",
            entity="proposal:new",
            artifact=json.dumps(
                {
                    "result_spec": embedded_result_spec(
                        NOW + timedelta(seconds=1)
                    ).model_dump(mode="json")
                }
            ).encode(),
        ),
        acquire(second),
        now=NOW,
    )

    with pytest.raises(IntegrityError, match="ResultSpec revision identity"):
        second.preflight()


def test_revising_a_current_entity_requires_explicit_supersession(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    ledger.commit(transition("one"), lease, now=NOW)

    with pytest.raises(StaleWriterError, match="explicitly supersede"):
        ledger.commit(transition("two"), lease, now=NOW)


def test_workflow_event_outcomes_are_typed() -> None:
    with pytest.raises(ValidationError):
        Transition.model_validate({**transition("one").model_dump(), "outcome": "invented"})


def test_lease_excludes_live_owner_and_allows_expired_or_dead_owner_takeover(
    ledger: WorkflowLedger,
) -> None:
    first = acquire(ledger, "process:first")
    with pytest.raises(LeaseConflictError):
        ledger.acquire_lease("process:second", NOW + timedelta(minutes=1), timedelta(minutes=5))

    expired = ledger.acquire_lease(
        "process:second", NOW + timedelta(minutes=6), timedelta(minutes=5)
    )
    assert expired.fencing_token > first.fencing_token

    dead_owner = ledger.acquire_lease(
        "process:third",
        NOW + timedelta(minutes=7),
        timedelta(minutes=5),
        owner_is_dead=lambda owner: owner == "process:second",
    )
    assert dead_owner.fencing_token > expired.fencing_token


def test_expired_same_owner_reacquisition_fences_the_old_token(
    ledger: WorkflowLedger,
) -> None:
    stale = acquire(ledger)
    replacement = ledger.acquire_lease(
        stale.owner_id, NOW + timedelta(minutes=6), timedelta(minutes=5)
    )

    assert replacement.fencing_token > stale.fencing_token
    with pytest.raises(StaleWriterError, match="lease"):
        ledger.commit(transition("one"), stale, now=NOW + timedelta(minutes=6))


def test_dependency_fingerprint_is_independent_of_role_order() -> None:
    first = DependencyInput(
        entity_id="entity:input",
        revision_id="revision:input",
        role="dependency:first",
        content_hash="sha256:" + "a" * 64,
    )
    second = first.model_copy(update={"role": "dependency:second"})

    assert dependency_fingerprint((first, second)) == dependency_fingerprint((second, first))


def test_stale_lease_and_dependency_fingerprint_are_rejected(ledger: WorkflowLedger) -> None:
    stale_lease = acquire(ledger, "process:first")
    current_lease = ledger.acquire_lease(
        "process:second", NOW + timedelta(minutes=6), timedelta(minutes=5)
    )
    with pytest.raises(StaleWriterError, match="lease"):
        ledger.commit(transition("one"), stale_lease, now=NOW + timedelta(minutes=6))

    base = ledger.commit(transition("base"), current_lease, now=NOW + timedelta(minutes=6))
    dependent = transition(
        "dependent",
        entity="entity:answer",
        dependencies=(
            DependencyInput(
                entity_id="entity:result",
                revision_id="revision:base",
                role="dependency:result",
                content_hash=base.artifact_hash,
            ),
        ),
    )
    wrong = dependent.model_copy(update={"expected_dependency_fingerprint": "sha256:" + "0" * 64})
    with pytest.raises(StaleWriterError, match="dependency"):
        ledger.commit(wrong, current_lease, now=NOW + timedelta(minutes=6))


def test_supersession_invalidates_only_transitive_descendants_from_earliest_checkpoint(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    base = ledger.commit(transition("base", checkpoint="checkpoint:source"), lease, now=NOW)
    ledger.commit(
        transition("unrelated", entity="entity:other", checkpoint="checkpoint:other"),
        lease,
        now=NOW,
    )
    answer = ledger.commit(
        transition(
            "answer",
            entity="entity:answer",
            checkpoint="checkpoint:answer",
            dependencies=(
                DependencyInput(
                    entity_id="entity:result",
                    revision_id="revision:base",
                    role="dependency:result",
                    content_hash=base.artifact_hash,
                ),
            ),
        ),
        lease,
        now=NOW,
    )
    ledger.commit(
        transition(
            "judgment",
            entity="entity:judgment",
            checkpoint="checkpoint:judgment",
            dependencies=(
                DependencyInput(
                    entity_id="entity:answer",
                    revision_id="revision:answer",
                    role="dependency:answer",
                    content_hash=answer.artifact_hash,
                ),
            ),
        ),
        lease,
        now=NOW,
    )

    replacement = transition("replacement", checkpoint="checkpoint:source").model_copy(
        update={"supersedes_revision_id": "revision:base"}
    )
    result = ledger.commit(replacement, lease, now=NOW)

    assert result.earliest_stale_checkpoint == "checkpoint:answer"
    assert {item.revision_id for item in ledger.current_revisions()} == {
        "revision:replacement",
        "revision:unrelated",
    }
    assert {item.revision_id for item in ledger.inactive_revisions()} >= {
        "revision:base",
        "revision:answer",
        "revision:judgment",
    }


def test_integrity_preflight_detects_corrupted_event_hash_and_order(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    ledger.commit(transition("one"), lease, now=NOW)
    ledger.commit(transition("two", entity="entity:other"), lease, now=NOW)
    assert ledger.preflight().ok is True

    with sqlite3.connect(ledger.path) as connection:
        connection.execute("UPDATE workflow_events SET event_hash = ? WHERE sequence = 1", ("bad",))

    with pytest.raises(IntegrityError, match="event hash"):
        ledger.preflight()


def test_integrity_preflight_detects_noncontiguous_event_order(
    ledger: WorkflowLedger,
) -> None:
    lease = acquire(ledger)
    ledger.commit(transition("one"), lease, now=NOW)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("UPDATE workflow_events SET sequence = 2 WHERE sequence = 1")

    with pytest.raises(RunIntegrityFailure, match="event order"):
        ledger.preflight()


def test_integrity_preflight_detects_missing_referenced_artifact(
    ledger: WorkflowLedger,
) -> None:
    result = ledger.commit(transition("one"), acquire(ledger), now=NOW)
    ledger.artifacts.path_for(result.artifact_hash).unlink()

    with pytest.raises(RunIntegrityFailure, match="was not found"):
        ledger.preflight()


def test_integrity_preflight_detects_missing_artifact_reachability_row(
    ledger: WorkflowLedger,
) -> None:
    ledger.commit(transition("one"), acquire(ledger), now=NOW)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("DELETE FROM reachable_artifacts")

    with pytest.raises(RunIntegrityFailure, match="artifact projection"):
        ledger.preflight()


def test_integrity_preflight_detects_corrupted_current_projection(
    ledger: WorkflowLedger,
) -> None:
    ledger.commit(transition("one"), acquire(ledger), now=NOW)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("DELETE FROM current_revisions")

    with pytest.raises(RunIntegrityFailure, match="projection"):
        ledger.preflight()


def test_preflight_skips_reading_artifacts_already_verified_via_shared_cache(
    tmp_path: Path,
) -> None:
    verification_cache = ArtifactVerificationCache()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    read_calls: list[str] = []
    original_read = artifacts.read

    def counting_read(content_hash: str) -> bytes:
        read_calls.append(content_hash)
        return original_read(content_hash)

    artifacts.read = counting_read  # type: ignore[method-assign]

    first = WorkflowLedger(
        tmp_path / "ledger.sqlite3",
        artifacts,
        verification_cache=verification_cache,
    )
    first.commit(transition("one"), acquire(first), now=NOW)
    assert first.preflight().ok is True
    assert len(read_calls) == 1

    # A fresh WorkflowLedger instance over the same path, sharing the same
    # caches (as RunEngine does across calls), must not re-read bytes it has
    # already verified and typed-walked.
    second = WorkflowLedger(
        tmp_path / "ledger.sqlite3",
        artifacts,
        verification_cache=verification_cache,
    )
    assert second.preflight().ok is True
    assert len(read_calls) == 1


def test_preflight_does_not_redetect_tampering_of_already_verified_artifact(
    tmp_path: Path,
) -> None:
    """#130 accepts cached artifact bytes for the process lifetime."""

    verified: set[str] = set()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ledger = WorkflowLedger(
        tmp_path / "ledger.sqlite3", artifacts, verified_artifact_hashes=verified
    )
    result = ledger.commit(transition("one"), acquire(ledger), now=NOW)
    assert ledger.preflight().ok is True

    ledger.artifacts.path_for(result.artifact_hash).write_bytes(b"tampered")

    assert ledger.preflight().ok is True


def test_replay_and_jsonl_export_are_deterministic_projections(
    ledger: WorkflowLedger, tmp_path: Path
) -> None:
    lease = acquire(ledger)
    ledger.commit(transition("one"), lease, now=NOW)
    ledger.commit(transition("two", entity="entity:other"), lease, now=NOW)

    replayed = ledger.replay()
    export_path = tmp_path / "events.jsonl"
    ledger.export_jsonl(export_path)

    assert replayed.current_revisions == ledger.current_revisions()
    lines = export_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]
    assert [event.sequence for event in ledger.events()] == [1, 2]
