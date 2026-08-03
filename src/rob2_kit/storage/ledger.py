"""SQLite source of truth for append-only workflow history and projections."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.revisions import (
    SCHEMA_VERSION as RECORD_SCHEMA_VERSION,
)
from rob2_kit.domain.revisions import (
    Actor,
    ContentHash,
    Identifier,
    SchemaVersion,
)
from rob2_kit.storage.artifacts import (
    ArtifactCorruptionError,
    ArtifactNotFoundError,
    ArtifactStore,
)

GENESIS_HASH = "sha256:" + ("0" * 64)
SCHEMA_VERSION = 1
IDENTIFIER_CHECK = "instr({column}, ':') > 1 AND instr({column}, ' ') = 0"


class LedgerError(RuntimeError):
    """Base class for ledger failures."""


class LeaseConflictError(LedgerError):
    """Raised when another live writer owns the project lease."""


class StaleWriterError(LedgerError):
    """Raised when a writer's lease or observed dependencies are stale."""


class RunIntegrityFailure(LedgerError):
    """Failure that makes shared workflow state untrustworthy."""


class IntegrityError(RunIntegrityFailure):
    """Raised when deterministic preflight cannot trust the ledger."""


class LedgerSchemaRefusal(IntegrityError):
    """Raised when a ledger belongs to an incompatible pre-release schema.

    The state is deliberately not migrated, rewritten, or dual-written.  The
    recovery text is part of the exception so an application boundary can
    return it as a normal, actionable integrity condition.
    """

    def __init__(
        self,
        *,
        expected_version: int,
        found_version: str,
        ledger_path: Path,
    ) -> None:
        self.expected_version = expected_version
        self.found_version = found_version
        self.ledger_path = Path(ledger_path)
        super().__init__(
            f"unsupported ledger schema version {found_version!r}; "
            f"this release requires schema version {expected_version}. "
            "Preserve the existing .rob2 state, run doctor for diagnostics, "
            "and start a new Run after archiving or removing the incompatible state."
        )


class LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DependencyInput(LedgerModel):
    entity_id: Identifier
    revision_id: Identifier
    role: Identifier
    content_hash: ContentHash


class WorkflowEventOutcome(StrEnum):
    COMPLETED = "completed"
    WORK_REQUIRED = "work_required"
    PREPARATION_OUTCOME_REACHED = "preparation_outcome_reached"
    RETRYABLE_INTERRUPTION = "retryable_interruption"
    TRIAL_PROBLEM = "trial_problem"
    RUN_INTEGRITY_FAILURE = "run_integrity_failure"


class Transition(LedgerModel):
    record_schema_version: SchemaVersion = RECORD_SCHEMA_VERSION
    scope: Identifier
    operation: Identifier
    operation_key: Identifier
    actor: Actor
    observed_at: datetime
    entity_id: Identifier
    revision_id: Identifier
    artifact: bytes
    artifact_media_type: str = Field(min_length=1)
    dependencies: tuple[DependencyInput, ...] = ()
    expected_dependency_fingerprint: ContentHash
    checkpoint: Identifier | None = None
    outcome: WorkflowEventOutcome
    causation_id: Identifier | None = None
    correlation_id: Identifier | None = None
    supersedes_revision_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_observed_at(self) -> Transition:
        if self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must use UTC")
        return self


class LeaseToken(LedgerModel):
    owner_id: Identifier
    fencing_token: int
    expires_at: datetime


class CommitResult(LedgerModel):
    operation_id: Identifier
    sequence: int
    event_id: Identifier
    artifact_hash: ContentHash
    dependency_fingerprint: ContentHash
    committed: bool = True
    duplicate: bool = False
    earliest_stale_checkpoint: Identifier | None = None


class WorkflowEvent(LedgerModel):
    sequence: int
    event_id: Identifier
    scope: Identifier
    actor: Actor
    observed_at: datetime
    operation: Identifier
    operation_key: Identifier
    operation_id: Identifier
    causation_id: Identifier | None
    correlation_id: Identifier | None
    entity_id: Identifier
    revision_id: Identifier
    record_schema_version: SchemaVersion
    dependencies: tuple[DependencyInput, ...]
    checkpoint: Identifier | None
    supersedes_revision_id: Identifier | None
    input_revision_hashes: tuple[ContentHash, ...]
    output_revision_hashes: tuple[ContentHash, ...]
    outcome: WorkflowEventOutcome
    previous_event_hash: ContentHash
    event_hash: ContentHash


class RevisionProjection(LedgerModel):
    entity_id: Identifier
    revision_id: Identifier
    artifact_hash: ContentHash
    sequence: int
    checkpoint: Identifier | None


class Checkpoint(LedgerModel):
    scope: Identifier
    checkpoint: Identifier
    revision_id: Identifier
    sequence: int


class IntegrityReceipt(LedgerModel):
    ok: bool
    event_count: int
    artifact_count: int
    schema_version: int


class ReplayProjection(LedgerModel):
    current_revisions: tuple[RevisionProjection, ...]
    checkpoints: tuple[Checkpoint, ...]


def dependency_fingerprint(dependencies: tuple[DependencyInput, ...]) -> str:
    canonical = [
        dependency.model_dump(mode="json")
        for dependency in sorted(
            dependencies,
            key=lambda item: (
                item.entity_id,
                item.revision_id,
                item.role,
                item.content_hash,
            ),
        )
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class WorkflowLedger:
    """Command/query boundary over one SQLite workflow ledger."""

    def __init__(
        self,
        path: Path,
        artifacts: ArtifactStore,
        *,
        now: Callable[[], datetime] | None = None,
        event_identifiers: Callable[[str, str, int], tuple[str, str]] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = artifacts
        self._now = now or (lambda: datetime.now(UTC))
        self._event_identifiers = event_identifiers
        self._initialize()

    def acquire_lease(
        self,
        owner_id: Identifier,
        now: datetime,
        duration: timedelta,
        *,
        owner_is_dead: Callable[[str], bool] | None = None,
    ) -> LeaseToken:
        if now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("lease time must use UTC")
        if duration <= timedelta(0):
            raise ValueError("lease duration must be positive")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT owner_id, fencing_token, expires_at FROM writer_lease WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                expires_at = datetime.fromisoformat(row["expires_at"])
                same_owner = row["owner_id"] == owner_id
                expired = expires_at <= now
                dead = owner_is_dead is not None and owner_is_dead(row["owner_id"])
                if not same_owner and expires_at > now and not dead:
                    raise LeaseConflictError(f"writer lease is held by {row['owner_id']}")
                if expired or (not same_owner and dead):
                    self._preflight_connection(connection)
                fencing_token = (
                    row["fencing_token"] if same_owner and not expired else row["fencing_token"] + 1
                )
            else:
                fencing_token = 1
            expires_at = now + duration
            connection.execute(
                """
                INSERT INTO writer_lease(singleton, owner_id, fencing_token, expires_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    fencing_token = excluded.fencing_token,
                    expires_at = excluded.expires_at
                """,
                (owner_id, fencing_token, expires_at.isoformat()),
            )
        return LeaseToken(owner_id=owner_id, fencing_token=fencing_token, expires_at=expires_at)

    def renew_lease(self, lease: LeaseToken, now: datetime, duration: timedelta) -> LeaseToken:
        with self._transaction() as connection:
            self._validate_lease(connection, lease, now)
            expires_at = now + duration
            connection.execute(
                "UPDATE writer_lease SET expires_at = ? WHERE singleton = 1",
                (expires_at.isoformat(),),
            )
        return lease.model_copy(update={"expires_at": expires_at})

    def commit(
        self,
        transition: Transition,
        lease: LeaseToken,
        *,
        now: datetime | None = None,
    ) -> CommitResult:
        return self.commit_batch((transition,), lease, now=now)[0]

    def commit_batch(
        self,
        transitions: tuple[Transition, ...],
        lease: LeaseToken,
        *,
        now: datetime | None = None,
    ) -> tuple[CommitResult, ...]:
        """Commit related revisions in one SQLite transaction."""
        if not transitions:
            raise ValueError("a commit batch must contain at least one transition")
        operation_keys = [transition.operation_key for transition in transitions]
        if len(operation_keys) != len(set(operation_keys)):
            raise ValueError("operation keys must be unique within a commit batch")
        commit_time = now or self._now()
        artifacts = tuple(
            self.artifacts.put(transition.artifact, transition.artifact_media_type)
            for transition in transitions
        )
        with self._transaction() as connection:
            self._validate_lease(connection, lease, commit_time)
            duplicates = tuple(
                connection.execute(
                    "SELECT result_json FROM operations WHERE operation_key = ?",
                    (transition.operation_key,),
                ).fetchone()
                for transition in transitions
            )
            if any(duplicate is not None for duplicate in duplicates):
                if not all(duplicate is not None for duplicate in duplicates):
                    raise StaleWriterError("commit batch is only partially present")
                return tuple(
                    CommitResult.model_validate_json(duplicate["result_json"]).model_copy(
                        update={"duplicate": True}
                    )
                    for duplicate in duplicates
                    if duplicate is not None
                )
            results = []
            for transition, artifact in zip(transitions, artifacts, strict=True):
                fingerprint = dependency_fingerprint(transition.dependencies)
                if transition.expected_dependency_fingerprint != fingerprint:
                    raise StaleWriterError("dependency fingerprint does not match submission")
                self._validate_dependencies(connection, transition.dependencies)
                self._validate_supersession(
                    connection, transition.entity_id, transition.supersedes_revision_id
                )
                previous = connection.execute(
                    "SELECT sequence, event_hash FROM workflow_events "
                    "ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                sequence = 1 if previous is None else previous["sequence"] + 1
                previous_hash = GENESIS_HASH if previous is None else previous["event_hash"]
                if self._event_identifiers is None:
                    operation_id, event_id = _event_identifiers(transition, sequence)
                else:
                    operation_id, event_id = self._event_identifiers(
                        transition.operation_key, transition.revision_id, sequence
                    )
                event_data = self._event_data(
                    transition,
                    sequence=sequence,
                    event_id=event_id,
                    operation_id=operation_id,
                    artifact_hash=artifact.content_hash,
                    previous_hash=previous_hash,
                )
                event_hash = _hash_json(event_data)
                connection.execute(
                    """
                    INSERT INTO workflow_events(
                        sequence, event_id, scope, actor_json, observed_at, operation,
                        operation_key, operation_id, causation_id, correlation_id, entity_id,
                        revision_id, transition_json, input_hashes_json, output_hashes_json,
                        outcome, previous_event_hash, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        event_id,
                        transition.scope,
                        transition.actor.model_dump_json(),
                        transition.observed_at.isoformat(),
                        transition.operation,
                        transition.operation_key,
                        operation_id,
                        transition.causation_id,
                        transition.correlation_id,
                        transition.entity_id,
                        transition.revision_id,
                        json.dumps(
                            self._transition_projection(transition),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(event_data["input_revision_hashes"], separators=(",", ":")),
                        json.dumps(event_data["output_revision_hashes"], separators=(",", ":")),
                        transition.outcome,
                        previous_hash,
                        event_hash,
                    ),
                )
                earliest = self._apply_supersession(connection, transition.supersedes_revision_id)
                connection.execute(
                    """
                    INSERT INTO revisions(
                        entity_id, revision_id, artifact_hash, media_type, sequence, scope,
                        checkpoint, supersedes_revision_id, dependency_fingerprint,
                        record_schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transition.entity_id,
                        transition.revision_id,
                        artifact.content_hash,
                        transition.artifact_media_type,
                        sequence,
                        transition.scope,
                        transition.checkpoint,
                        transition.supersedes_revision_id,
                        fingerprint,
                        transition.record_schema_version,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO current_revisions(entity_id, revision_id) VALUES (?, ?)
                    ON CONFLICT(entity_id) DO UPDATE SET revision_id = excluded.revision_id
                    """,
                    (transition.entity_id, transition.revision_id),
                )
                if transition.checkpoint is not None:
                    connection.execute(
                        """
                        INSERT INTO current_checkpoints(scope, checkpoint, revision_id, sequence)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(scope, checkpoint) DO UPDATE SET
                            revision_id = excluded.revision_id,
                            sequence = excluded.sequence
                        """,
                        (
                            transition.scope,
                            transition.checkpoint,
                            transition.revision_id,
                            sequence,
                        ),
                    )
                for dependency in transition.dependencies:
                    connection.execute(
                        """
                        INSERT INTO revision_dependencies(
                            revision_id, dependency_entity_id, dependency_revision_id,
                            dependency_role, dependency_hash
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            transition.revision_id,
                            dependency.entity_id,
                            dependency.revision_id,
                            dependency.role,
                            dependency.content_hash,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO reachable_artifacts(
                        content_hash, media_type, size, first_sequence
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(content_hash) DO NOTHING
                    """,
                    (artifact.content_hash, artifact.media_type, artifact.size, sequence),
                )
                result = CommitResult(
                    operation_id=operation_id,
                    sequence=sequence,
                    event_id=event_id,
                    artifact_hash=artifact.content_hash,
                    dependency_fingerprint=fingerprint,
                    earliest_stale_checkpoint=earliest,
                )
                connection.execute(
                    "INSERT INTO operations(operation_key, result_json) VALUES (?, ?)",
                    (transition.operation_key, result.model_dump_json()),
                )
                results.append(result)
        return tuple(results)

    def events(self) -> tuple[WorkflowEvent, ...]:
        with self._connection() as connection:
            return tuple(
                self._row_to_event(row)
                for row in connection.execute("SELECT * FROM workflow_events ORDER BY sequence")
            )

    def current_revisions(self) -> tuple[RevisionProjection, ...]:
        return self._revision_query(active=True)

    def inactive_revisions(self) -> tuple[RevisionProjection, ...]:
        return self._revision_query(active=False)

    def checkpoints(self) -> tuple[Checkpoint, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT scope, checkpoint, revision_id, sequence
                FROM current_checkpoints
                ORDER BY sequence
                """
            )
            return tuple(Checkpoint.model_validate(dict(row)) for row in rows)

    def reachable_artifact_hashes(self) -> tuple[str, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT content_hash FROM reachable_artifacts ORDER BY first_sequence"
            )
            return tuple(row["content_hash"] for row in rows)

    def preflight(self) -> IntegrityReceipt:
        with self._connection() as connection:
            return self._preflight_connection(connection)

    def replay(self) -> ReplayProjection:
        self.preflight()
        return self._replay_events(self.events())

    def _replay_events(self, events: tuple[WorkflowEvent, ...]) -> ReplayProjection:
        active: dict[str, RevisionProjection] = {}
        checkpoint_rows: dict[tuple[str, str], Checkpoint] = {}
        dependencies: dict[str, tuple[str, ...]] = {}
        for event in events:
            if event.supersedes_revision_id is not None:
                stale = _transitive_descendants(event.supersedes_revision_id, dependencies)
                for entity_id, revision in tuple(active.items()):
                    if revision.revision_id in stale:
                        del active[entity_id]
                for key, checkpoint in tuple(checkpoint_rows.items()):
                    if checkpoint.revision_id in stale:
                        del checkpoint_rows[key]
            revision = RevisionProjection(
                entity_id=event.entity_id,
                revision_id=event.revision_id,
                artifact_hash=event.output_revision_hashes[0],
                sequence=event.sequence,
                checkpoint=event.checkpoint,
            )
            active[event.entity_id] = revision
            dependencies[event.revision_id] = tuple(
                dependency.revision_id for dependency in event.dependencies
            )
            if event.checkpoint is not None:
                checkpoint_rows[(event.scope, event.checkpoint)] = Checkpoint(
                    scope=event.scope,
                    checkpoint=event.checkpoint,
                    revision_id=event.revision_id,
                    sequence=event.sequence,
                )
        return ReplayProjection(
            current_revisions=tuple(sorted(active.values(), key=_revision_sequence)),
            checkpoints=tuple(sorted(checkpoint_rows.values(), key=_checkpoint_sequence)),
        )

    def export_jsonl(self, path: Path) -> None:
        lines = (
            json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            for event in self.events()
        )
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    def _initialize(self) -> None:
        self._refuse_incompatible_existing_schema()
        with self._connection() as connection:
            connection.executescript(
                f"""
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS metadata(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value)
                VALUES ('schema_version', '{SCHEMA_VERSION}');
                CREATE TABLE IF NOT EXISTS writer_lease(
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_events(
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    scope TEXT NOT NULL,
                    actor_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    operation_key TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL UNIQUE,
                    causation_id TEXT,
                    correlation_id TEXT,
                    entity_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL UNIQUE,
                    transition_json TEXT NOT NULL,
                    input_hashes_json TEXT NOT NULL,
                    output_hashes_json TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    previous_event_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS revisions(
                    entity_id TEXT NOT NULL CHECK({IDENTIFIER_CHECK.format(column="entity_id")}),
                    revision_id TEXT PRIMARY KEY CHECK(
                        {IDENTIFIER_CHECK.format(column="revision_id")}
                    ),
                    artifact_hash TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    sequence INTEGER NOT NULL UNIQUE REFERENCES workflow_events(sequence),
                    scope TEXT NOT NULL,
                    checkpoint TEXT,
                    supersedes_revision_id TEXT REFERENCES revisions(revision_id),
                    dependency_fingerprint TEXT NOT NULL,
                    record_schema_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS current_revisions(
                    entity_id TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL UNIQUE REFERENCES revisions(revision_id)
                );
                CREATE TABLE IF NOT EXISTS current_checkpoints(
                    scope TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    revision_id TEXT NOT NULL UNIQUE REFERENCES revisions(revision_id),
                    sequence INTEGER NOT NULL,
                    PRIMARY KEY(scope, checkpoint)
                );
                CREATE TABLE IF NOT EXISTS revision_dependencies(
                    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    dependency_entity_id TEXT NOT NULL,
                    dependency_revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    dependency_role TEXT NOT NULL,
                    dependency_hash TEXT NOT NULL,
                    PRIMARY KEY(
                        revision_id, dependency_entity_id, dependency_revision_id,
                        dependency_role
                    )
                );
                CREATE TABLE IF NOT EXISTS reachable_artifacts(
                    content_hash TEXT PRIMARY KEY,
                    media_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    first_sequence INTEGER NOT NULL REFERENCES workflow_events(sequence)
                );
                CREATE TABLE IF NOT EXISTS operations(
                    operation_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL
                );
                """
            )

    def _refuse_incompatible_existing_schema(self) -> None:
        """Refuse known old state before ``CREATE TABLE IF NOT EXISTS`` runs."""

        if not self.path.is_file() or self.path.stat().st_size == 0:
            return
        try:
            with sqlite3.connect(self.path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not tables:
                    return
                if "metadata" not in tables:
                    raise LedgerSchemaRefusal(
                        expected_version=SCHEMA_VERSION,
                        found_version="missing",
                        ledger_path=self.path,
                    )
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    raise LedgerSchemaRefusal(
                        expected_version=SCHEMA_VERSION,
                        found_version="missing",
                        ledger_path=self.path,
                    )
                found = str(row[0])
                if found != str(SCHEMA_VERSION):
                    raise LedgerSchemaRefusal(
                        expected_version=SCHEMA_VERSION,
                        found_version=found,
                        ledger_path=self.path,
                    )
        except LedgerSchemaRefusal:
            raise
        except sqlite3.DatabaseError as error:
            raise LedgerSchemaRefusal(
                expected_version=SCHEMA_VERSION,
                found_version="unreadable",
                ledger_path=self.path,
            ) from error

    def _apply_supersession(
        self, connection: sqlite3.Connection, superseded: str | None
    ) -> str | None:
        if superseded is None:
            return None
        exists = connection.execute(
            "SELECT revision_id FROM current_revisions WHERE revision_id = ?",
            (superseded,),
        ).fetchone()
        if exists is None:
            raise StaleWriterError("superseded revision is not current")
        descendants = connection.execute(
            """
            WITH RECURSIVE descendants(revision_id) AS (
                SELECT revision_id FROM revisions WHERE revision_id = ?
                UNION
                SELECT dependency.revision_id
                FROM revision_dependencies AS dependency
                JOIN descendants
                  ON dependency.dependency_revision_id = descendants.revision_id
            )
            SELECT revision_id FROM descendants
            """,
            (superseded,),
        ).fetchall()
        revision_ids = tuple(row["revision_id"] for row in descendants)
        placeholders = ",".join("?" for _ in revision_ids)
        checkpoint = connection.execute(
            f"""
            SELECT revisions.checkpoint FROM revisions
            JOIN current_revisions USING(revision_id)
            WHERE revisions.revision_id IN ({placeholders})
              AND revisions.revision_id != ?
              AND revisions.checkpoint IS NOT NULL
            ORDER BY sequence LIMIT 1
            """,
            (*revision_ids, superseded),
        ).fetchone()
        connection.execute(
            f"DELETE FROM current_checkpoints WHERE revision_id IN ({placeholders})",
            revision_ids,
        )
        connection.execute(
            f"DELETE FROM current_revisions WHERE revision_id IN ({placeholders})",
            revision_ids,
        )
        return None if checkpoint is None else checkpoint["checkpoint"]

    def _validate_dependencies(
        self, connection: sqlite3.Connection, dependencies: tuple[DependencyInput, ...]
    ) -> None:
        for dependency in dependencies:
            current = connection.execute(
                """
                SELECT revisions.revision_id, revisions.artifact_hash FROM revisions
                JOIN current_revisions USING(revision_id)
                WHERE current_revisions.entity_id = ?
                """,
                (dependency.entity_id,),
            ).fetchone()
            if (
                current is None
                or current["revision_id"] != dependency.revision_id
                or current["artifact_hash"] != dependency.content_hash
            ):
                raise StaleWriterError(f"dependency {dependency.entity_id} is no longer current")

    def _validate_supersession(
        self,
        connection: sqlite3.Connection,
        entity_id: str,
        supersedes_revision_id: str | None,
    ) -> None:
        current = connection.execute(
            "SELECT revision_id FROM current_revisions WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if current is None and supersedes_revision_id is not None:
            raise StaleWriterError("cannot supersede an entity with no current revision")
        if current is not None and supersedes_revision_id != current["revision_id"]:
            raise StaleWriterError("a new revision must explicitly supersede the current revision")

    def _validate_lease(
        self, connection: sqlite3.Connection, lease: LeaseToken, now: datetime
    ) -> None:
        row = connection.execute(
            "SELECT owner_id, fencing_token, expires_at FROM writer_lease WHERE singleton = 1"
        ).fetchone()
        if (
            row is None
            or row["owner_id"] != lease.owner_id
            or row["fencing_token"] != lease.fencing_token
            or datetime.fromisoformat(row["expires_at"]) <= now
        ):
            raise StaleWriterError("writer lease is stale")

    def _preflight_connection(self, connection: sqlite3.Connection) -> IntegrityReceipt:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise IntegrityError(f"SQLite integrity check failed: {quick_check}")
        schema_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if schema_row is None:
            raise LedgerSchemaRefusal(
                expected_version=SCHEMA_VERSION,
                found_version="missing",
                ledger_path=self.path,
            )
        found_version = str(schema_row[0])
        try:
            version = int(found_version)
        except ValueError as error:
            raise LedgerSchemaRefusal(
                expected_version=SCHEMA_VERSION,
                found_version=found_version,
                ledger_path=self.path,
            ) from error
        if version != SCHEMA_VERSION:
            raise LedgerSchemaRefusal(
                expected_version=SCHEMA_VERSION,
                found_version=found_version,
                ledger_path=self.path,
            )
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        event_count = 0
        for row in connection.execute("SELECT * FROM workflow_events ORDER BY sequence"):
            if row["sequence"] != expected_sequence:
                raise IntegrityError("event order is not contiguous")
            if row["previous_event_hash"] != previous_hash:
                raise IntegrityError("event hash link is corrupted")
            expected_hash = _hash_json(
                {
                    "sequence": row["sequence"],
                    "event_id": row["event_id"],
                    "scope": row["scope"],
                    "actor": json.loads(row["actor_json"]),
                    "observed_at": row["observed_at"],
                    "operation": row["operation"],
                    "operation_key": row["operation_key"],
                    "operation_id": row["operation_id"],
                    "causation_id": row["causation_id"],
                    "correlation_id": row["correlation_id"],
                    "entity_id": row["entity_id"],
                    "revision_id": row["revision_id"],
                    **json.loads(row["transition_json"]),
                    "input_revision_hashes": json.loads(row["input_hashes_json"]),
                    "output_revision_hashes": json.loads(row["output_hashes_json"]),
                    "outcome": row["outcome"],
                    "previous_event_hash": row["previous_event_hash"],
                }
            )
            if row["event_hash"] != expected_hash:
                raise IntegrityError(f"event hash is corrupted at sequence {expected_sequence}")
            event = self._row_to_event(row)
            if event.record_schema_version != RECORD_SCHEMA_VERSION:
                raise IntegrityError(
                    f"unsupported record schema version {event.record_schema_version}"
                )
            revision = connection.execute(
                """
                SELECT artifact_hash, sequence, checkpoint, supersedes_revision_id,
                       record_schema_version, dependency_fingerprint
                FROM revisions WHERE revision_id = ? AND entity_id = ?
                """,
                (event.revision_id, event.entity_id),
            ).fetchone()
            if (
                revision is None
                or revision["artifact_hash"] != event.output_revision_hashes[0]
                or revision["sequence"] != event.sequence
                or revision["checkpoint"] != event.checkpoint
                or revision["supersedes_revision_id"] != event.supersedes_revision_id
                or revision["record_schema_version"] != event.record_schema_version
                or revision["dependency_fingerprint"] != dependency_fingerprint(event.dependencies)
            ):
                raise IntegrityError(
                    f"revision projection is corrupted at sequence {expected_sequence}"
                )
            stored_dependencies = {
                (
                    item["dependency_entity_id"],
                    item["dependency_revision_id"],
                    item["dependency_role"],
                    item["dependency_hash"],
                )
                for item in connection.execute(
                    """
                    SELECT dependency_entity_id, dependency_revision_id,
                           dependency_role, dependency_hash
                    FROM revision_dependencies WHERE revision_id = ?
                    """,
                    (event.revision_id,),
                )
            }
            event_dependencies = {
                (
                    item.entity_id,
                    item.revision_id,
                    item.role,
                    item.content_hash,
                )
                for item in event.dependencies
            }
            if stored_dependencies != event_dependencies:
                raise IntegrityError(
                    f"revision dependencies are corrupted at sequence {expected_sequence}"
                )
            previous_hash = row["event_hash"]
            expected_sequence += 1
            event_count += 1
        artifact_count = 0
        referenced_hashes = {
            row["artifact_hash"]
            for row in connection.execute("SELECT artifact_hash FROM revisions")
        }
        reachable_hashes = {
            row["content_hash"]
            for row in connection.execute("SELECT content_hash FROM reachable_artifacts")
        }
        if referenced_hashes != reachable_hashes:
            raise IntegrityError("reachable artifact projection does not match revision references")
        for content_hash in sorted(referenced_hashes):
            try:
                self.artifacts.read(content_hash)
            except (ArtifactCorruptionError, ArtifactNotFoundError) as error:
                raise IntegrityError(str(error)) from error
            artifact_count += 1
        active_dependencies = connection.execute(
            """
            SELECT dependency.revision_id
            FROM revision_dependencies AS dependency
            JOIN current_revisions AS child ON child.revision_id = dependency.revision_id
            LEFT JOIN revisions AS parent
              ON parent.revision_id = dependency.dependency_revision_id
             AND parent.artifact_hash = dependency.dependency_hash
            LEFT JOIN current_revisions AS current_parent
              ON current_parent.revision_id = parent.revision_id
            WHERE current_parent.revision_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if active_dependencies is not None:
            raise IntegrityError(
                f"active revision {active_dependencies['revision_id']} has a stale dependency"
            )
        lease = connection.execute(
            "SELECT owner_id, fencing_token, expires_at FROM writer_lease WHERE singleton = 1"
        ).fetchone()
        if lease is not None:
            try:
                expires_at = datetime.fromisoformat(lease["expires_at"])
            except ValueError as error:
                raise IntegrityError("writer lease expiry is invalid") from error
            if expires_at.utcoffset() != UTC.utcoffset(expires_at):
                raise IntegrityError("writer lease expiry must use UTC")
            if lease["fencing_token"] < 1:
                raise IntegrityError("writer lease fencing token is invalid")
        events = tuple(
            self._row_to_event(row)
            for row in connection.execute("SELECT * FROM workflow_events ORDER BY sequence")
        )
        replayed = self._replay_events(events)
        persisted_revisions = tuple(
            RevisionProjection.model_validate(dict(row))
            for row in connection.execute(
                """
                SELECT revisions.entity_id, revisions.revision_id, artifact_hash,
                       sequence, checkpoint
                FROM revisions
                JOIN current_revisions USING(revision_id)
                ORDER BY sequence
                """
            )
        )
        persisted_checkpoints = tuple(
            Checkpoint.model_validate(dict(row))
            for row in connection.execute(
                """
                SELECT scope, checkpoint, revision_id, sequence
                FROM current_checkpoints ORDER BY sequence
                """
            )
        )
        if replayed.current_revisions != persisted_revisions:
            raise IntegrityError("current revision projection does not match event replay")
        if replayed.checkpoints != persisted_checkpoints:
            raise IntegrityError("checkpoint projection does not match event replay")
        return IntegrityReceipt(
            ok=True,
            event_count=event_count,
            artifact_count=artifact_count,
            schema_version=version,
        )

    def _event_data(
        self,
        transition: Transition,
        *,
        sequence: int,
        event_id: str,
        operation_id: str,
        artifact_hash: str,
        previous_hash: str,
    ) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "event_id": event_id,
            "scope": transition.scope,
            "actor": transition.actor.model_dump(mode="json"),
            "observed_at": transition.observed_at.isoformat(),
            "operation": transition.operation,
            "operation_key": transition.operation_key,
            "operation_id": operation_id,
            "causation_id": transition.causation_id,
            "correlation_id": transition.correlation_id,
            "entity_id": transition.entity_id,
            "revision_id": transition.revision_id,
            **self._transition_projection(transition),
            "input_revision_hashes": [
                dependency.content_hash for dependency in transition.dependencies
            ],
            "output_revision_hashes": [artifact_hash],
            "outcome": transition.outcome,
            "previous_event_hash": previous_hash,
        }

    def _row_to_event(self, row: sqlite3.Row) -> WorkflowEvent:
        transition = json.loads(row["transition_json"])
        return WorkflowEvent(
            sequence=row["sequence"],
            event_id=row["event_id"],
            scope=row["scope"],
            actor=Actor.model_validate_json(row["actor_json"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            operation=row["operation"],
            operation_key=row["operation_key"],
            operation_id=row["operation_id"],
            causation_id=row["causation_id"],
            correlation_id=row["correlation_id"],
            entity_id=row["entity_id"],
            revision_id=row["revision_id"],
            record_schema_version=transition["record_schema_version"],
            dependencies=tuple(
                DependencyInput.model_validate(item) for item in transition["dependencies"]
            ),
            checkpoint=transition["checkpoint"],
            supersedes_revision_id=transition["supersedes_revision_id"],
            input_revision_hashes=tuple(json.loads(row["input_hashes_json"])),
            output_revision_hashes=tuple(json.loads(row["output_hashes_json"])),
            outcome=row["outcome"],
            previous_event_hash=row["previous_event_hash"],
            event_hash=row["event_hash"],
        )

    def _transition_projection(self, transition: Transition) -> dict[str, Any]:
        return {
            "record_schema_version": transition.record_schema_version,
            "dependencies": [
                dependency.model_dump(mode="json") for dependency in transition.dependencies
            ],
            "checkpoint": transition.checkpoint,
            "supersedes_revision_id": transition.supersedes_revision_id,
        }

    def _revision_query(self, *, active: bool) -> tuple[RevisionProjection, ...]:
        with self._connection() as connection:
            join = "JOIN" if active else "LEFT JOIN"
            condition = "" if active else "WHERE current.revision_id IS NULL"
            rows = connection.execute(
                f"""
                SELECT revisions.entity_id, revisions.revision_id, artifact_hash,
                       sequence, checkpoint
                FROM revisions
                {join} current_revisions AS current
                  ON current.revision_id = revisions.revision_id
                {condition}
                ORDER BY sequence
                """
            )
            return tuple(RevisionProjection.model_validate(dict(row)) for row in rows)

    def _row_to_revision(self, row: sqlite3.Row) -> RevisionProjection:
        return RevisionProjection(
            entity_id=row["entity_id"],
            revision_id=row["revision_id"],
            artifact_hash=row["artifact_hash"],
            sequence=row["sequence"],
            checkpoint=row["checkpoint"],
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def _event_identifiers(_transition: Transition, _sequence: int) -> tuple[str, str]:
    return f"operation:{uuid.uuid4()}", f"event:{uuid.uuid4()}"


def _hash_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def workflow_event_hash_payload(event: WorkflowEvent) -> dict[str, Any]:
    """Return the exact public payload covered by a Workflow event hash."""
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "scope": event.scope,
        "actor": event.actor.model_dump(mode="json"),
        "observed_at": event.observed_at.isoformat(),
        "operation": event.operation,
        "operation_key": event.operation_key,
        "operation_id": event.operation_id,
        "causation_id": event.causation_id,
        "correlation_id": event.correlation_id,
        "entity_id": event.entity_id,
        "revision_id": event.revision_id,
        "record_schema_version": event.record_schema_version,
        "dependencies": [dependency.model_dump(mode="json") for dependency in event.dependencies],
        "checkpoint": event.checkpoint,
        "supersedes_revision_id": event.supersedes_revision_id,
        "input_revision_hashes": list(event.input_revision_hashes),
        "output_revision_hashes": list(event.output_revision_hashes),
        "outcome": event.outcome,
        "previous_event_hash": event.previous_event_hash,
    }


def _revision_sequence(revision: RevisionProjection) -> int:
    return revision.sequence


def _checkpoint_sequence(checkpoint: Checkpoint) -> int:
    return checkpoint.sequence


def _transitive_descendants(
    root_revision_id: str, dependencies: dict[str, tuple[str, ...]]
) -> set[str]:
    stale = {root_revision_id}
    changed = True
    while changed:
        changed = False
        for revision_id, direct_dependencies in dependencies.items():
            if revision_id not in stale and any(
                dependency in stale for dependency in direct_dependencies
            ):
                stale.add(revision_id)
                changed = True
    return stale
