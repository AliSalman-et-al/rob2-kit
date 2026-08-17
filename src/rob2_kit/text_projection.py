"""Verified, rebuildable text projections for captured Sources.

Projection pages are derivative data.  Their identity is canonical, but the
page text and FTS index live in a separate SQLite file that can be removed and
recreated without changing workflow records.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from rob2_kit.models import StrictModel, canonical_json_bytes, sha256
from rob2_kit.sources import Source, _extract_pages, sha256_bytes
from rob2_kit.storage import ensure_contract_version, workspace_mutation_lock
from rob2_kit.telemetry import (
    NO_OP_EVENT_SINK,
    EventSinkLike,
    ProjectionEvent,
    ProjectionOperation,
    ProjectionOutcome,
    emit_event,
)

FTS_TOKENIZER_ID = "unicode61_casefold_no_diacritics_v1"
FTS_SQL_TOKENIZER = "unicode61 remove_diacritics 0"


def unicode61_tokens(text: str) -> tuple[tuple[int, int, str], ...]:
    """Return original spans paired with terms normalized by SQLite unicode61."""

    tokens: list[tuple[int, int, str]] = []
    start: int | None = None
    for index, character in enumerate(text):
        category = unicodedata.category(character)
        token_character = category[0] in {"L", "N"} or category in {"Co", "Mn", "Mc", "Me"}
        if token_character and start is None:
            start = index
        elif not token_character and start is not None:
            tokens.append((start, index, text[start:index]))
            start = None
    if start is not None:
        tokens.append((start, len(text), text[start:]))
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            f"CREATE VIRTUAL TABLE tokenize_input USING fts5(text, tokenize='{FTS_SQL_TOKENIZER}')"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE tokenize_vocab USING fts5vocab(tokenize_input, instance)"
        )
        connection.execute("INSERT INTO tokenize_input(text) VALUES(?)", (text,))
        normalized = tuple(
            str(row[0])
            for row in connection.execute("SELECT term FROM tokenize_vocab ORDER BY offset")
        )
    finally:
        connection.close()
    if len(normalized) != len(tokens):
        raise ValueError("SQLite unicode61 token boundaries are unsupported")
    return tuple(
        (start, end, term) for (start, end, _original), term in zip(tokens, normalized, strict=True)
    )


PROJECTION_DB_NAME = "text-projections.sqlite3"
PROJECTION_SCHEMA = "rob2-kit.text-projections.v1"
PROJECTION_RECIPE = "rob2-kit.extract-pages.v1"


class TextProjectionIdentity(StrictModel):
    """The frozen recipe and hashes needed to verify a derivative projection."""

    schema_version: Literal["rob2-kit.text-projection.v1"] = "rob2-kit.text-projection.v1"
    recipe: Literal["rob2-kit.extract-pages.v1"] = PROJECTION_RECIPE
    source_sha256: str
    media_type: str
    page_hashes: tuple[str, ...] = Field(min_length=1)
    projection_hash: str
    page_count: int = Field(ge=1)


def projection_database_path(workspace: str | Path) -> Path:
    root = Path(workspace).resolve(strict=True)
    internal = root / ".rob2-kit"
    if internal.exists() and (internal.is_symlink() or _reparse(internal)):
        raise ValueError("internal workspace directory is redirected")
    internal.mkdir(exist_ok=True)
    path = internal / PROJECTION_DB_NAME
    if path.exists() and (path.is_symlink() or _reparse(path)):
        raise ValueError("text projection database is redirected")
    return path


def projection_identity(source: Source, pages: tuple[str, ...]) -> TextProjectionIdentity:
    """Derive a deterministic identity without normalizing page text."""

    if not pages:
        raise ValueError("a Source projection must contain at least one page")
    if len(pages) != source.page_count:
        raise ValueError("projection page count differs from Source metadata")
    page_hashes = tuple(sha256_bytes(page.encode("utf-8")) for page in pages)
    projection_hash = sha256(
        {
            "recipe": PROJECTION_RECIPE,
            "source_sha256": source.sha256,
            "media_type": source.media_type,
            "page_hashes": page_hashes,
        }
    )
    return TextProjectionIdentity(
        source_sha256=source.sha256,
        media_type=source.media_type,
        page_hashes=page_hashes,
        projection_hash=projection_hash,
        page_count=len(pages),
    )


def extract_projection(
    source: Source, data: bytes
) -> tuple[TextProjectionIdentity, tuple[str, ...]]:
    """Extract and identify one Source, checking its captured byte identity."""

    if sha256_bytes(data) != source.sha256:
        raise ValueError("captured Source bytes have changed")
    pages = _extract_pages(data, source.media_type)
    return projection_identity(source, pages), pages


def materialize_projection(
    workspace: str | Path,
    source: Source,
    pages: tuple[str, ...] | None = None,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> TextProjectionIdentity:
    """Publish one complete Source projection to the derivative store.

    ``pages`` may be supplied by ingestion when extraction has already happened;
    otherwise the captured bytes are verified and extracted once here.
    """

    ensure_contract_version(workspace)
    root = Path(workspace).resolve(strict=True)
    if pages is None:
        captured = (root / source.captured_path).resolve(strict=True)
        if not captured.is_relative_to(root) or not captured.is_file():
            raise ValueError("captured Source path is unavailable")
        identity, pages = extract_projection(source, captured.read_bytes())
    else:
        identity = projection_identity(source, pages)
    path = projection_database_path(root)
    with workspace_mutation_lock(root):
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        try:
            _create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            _store_projection(connection, source, identity, pages)
            connection.execute("COMMIT")
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
    emit_event(
        event_sink,
        ProjectionEvent(
            operation=ProjectionOperation.MATERIALIZE,
            outcome=ProjectionOutcome.CREATED,
            page_count=identity.page_count,
        ),
    )
    return identity


def materialize_projections(
    workspace: str | Path,
    projections: Iterable[tuple[Source, tuple[str, ...]]],
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> tuple[TextProjectionIdentity, ...]:
    """Materialize a deterministic batch of already extracted projections."""

    entries = tuple(projections)
    if not entries:
        return ()
    ensure_contract_version(workspace)
    root = Path(workspace).resolve(strict=True)
    identities = tuple(projection_identity(source, pages) for source, pages in entries)
    path = projection_database_path(root)
    with workspace_mutation_lock(root):
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        try:
            _create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            for (source, pages), identity in zip(entries, identities, strict=True):
                _store_projection(connection, source, identity, pages)
            connection.execute("COMMIT")
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
    for identity in identities:
        emit_event(
            event_sink,
            ProjectionEvent(
                operation=ProjectionOperation.MATERIALIZE,
                outcome=ProjectionOutcome.CREATED,
                page_count=identity.page_count,
            ),
        )
    return identities


def verified_pages(
    workspace: str | Path,
    source: Source,
    expected: TextProjectionIdentity,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
    allow_rebuild: bool = True,
    rebuild_gate: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Read one verified projection, rebuilding the derivative at most once."""

    root = Path(workspace).resolve(strict=True)
    relative = Path(source.captured_path)
    expected_parent = Path(".rob2-kit") / "sources" / source.trial_id
    if relative.parent != expected_parent or relative.name.split(".")[0] != source.id:
        raise ValueError("Source captured path is not its Trial capture path")
    try:
        captured = (root / relative).resolve(strict=True)
    except OSError as error:
        raise ValueError("captured Source path is unavailable") from error
    if not captured.is_relative_to(root) or not captured.is_file():
        raise ValueError("captured Source path is unavailable")
    data = captured.read_bytes()
    if sha256_bytes(data) != source.sha256:
        raise ValueError("captured Source bytes have changed")
    try:
        pages = _read_projection(root, source, expected)
    except (OSError, sqlite3.Error, ValueError):
        if rebuild_gate is not None:
            rebuild_gate()
        if not allow_rebuild:
            raise
        # This is the one bounded automatic repair attempt for this top-level
        # projection read.  If repair cannot reproduce the frozen identity, the
        # original operation fails closed.
        identity, pages = extract_projection(source, data)
        if identity != expected:
            raise ValueError("rebuilt text projection differs from frozen identity")
        materialize_projection(root, source, pages, event_sink=event_sink)
        emit_event(
            event_sink,
            ProjectionEvent(
                operation=ProjectionOperation.REBUILD,
                outcome=ProjectionOutcome.REBUILT,
                page_count=expected.page_count,
            ),
        )
        return pages
    emit_event(
        event_sink,
        ProjectionEvent(
            operation=ProjectionOperation.VERIFY,
            outcome=ProjectionOutcome.REUSED,
            page_count=expected.page_count,
        ),
    )
    return pages


@dataclass
class VerifiedProjection:
    """Per-operation cache for verified pages from distinct Sources."""

    workspace: str | Path
    event_sink: EventSinkLike = NO_OP_EVENT_SINK
    _pages: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _rebuild_attempted: bool = False

    def pages(self, source: Source, expected: TextProjectionIdentity) -> tuple[str, ...]:
        if source.id not in self._pages:
            self._pages[source.id] = verified_pages(
                self.workspace,
                source,
                expected,
                event_sink=self.event_sink,
                rebuild_gate=self._claim_rebuild,
            )
        return self._pages[source.id]

    def _claim_rebuild(self) -> None:
        if self._rebuild_attempted:
            raise ValueError("top-level operation already attempted a projection rebuild")
        self._rebuild_attempted = True


def stored_projection_identity(
    workspace: str | Path, source: Source
) -> TextProjectionIdentity | None:
    """Return a stored identity when the derivative has one, without extraction."""

    path = projection_database_path(workspace)
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key=?", (f"projection:{source.id}",)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        identity = TextProjectionIdentity.model_validate_json(bytes(row[0]))
        if (
            identity.source_sha256 != source.sha256
            or identity.media_type != source.media_type
            or identity.page_count != source.page_count
        ):
            return None
        return identity
    except (OSError, sqlite3.Error, ValueError):
        return None


def canonical_projection_identity(workspace: str | Path, source: Source) -> TextProjectionIdentity:
    """Read the frozen identity from the canonical Captured Batch, never derivatives."""

    from rob2_kit.ingestion.service import read_captured_batch

    captured = read_captured_batch(workspace)
    if captured is None:
        raise ValueError("canonical Captured Batch is unavailable")
    for trial in captured.trials:
        for captured_source, identity in zip(trial.sources, trial.projections, strict=True):
            if captured_source.id == source.id:
                if captured_source != source:
                    raise ValueError("Source does not match canonical Captured Batch")
                return identity
    raise ValueError("Source projection is not in canonical Captured Batch")


def build_fts_index(
    workspace: str | Path,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> None:
    """Build the assessment-wide derivative FTS index lazily and atomically."""

    ensure_contract_version(workspace)
    path = projection_database_path(workspace)
    with workspace_mutation_lock(workspace):
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        try:
            _create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            basis = _fts_basis(connection)
            connection.execute("DROP TABLE IF EXISTS pages_fts")
            connection.execute(
                "CREATE VIRTUAL TABLE pages_fts USING fts5(source_id UNINDEXED, "
                f"page_number UNINDEXED, text, tokenize='{FTS_SQL_TOKENIZER}')"
            )
            connection.execute(
                "INSERT INTO pages_fts(source_id,page_number,text) "
                "SELECT source_id,page_number,text FROM pages"
            )
            connection.execute(
                "INSERT INTO metadata(key,value) VALUES('fts_schema',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (PROJECTION_SCHEMA.encode(),),
            )
            connection.execute(
                "INSERT INTO metadata(key,value) VALUES('fts_basis',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (basis.encode(),),
            )
            connection.execute("COMMIT")
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
    emit_event(
        event_sink,
        ProjectionEvent(
            operation=ProjectionOperation.INDEX,
            outcome=ProjectionOutcome.CREATED,
            page_count=0,
        ),
    )


def search_fts_pages(
    workspace: str | Path, query: str, source_ids: tuple[str, ...]
) -> tuple[tuple[str, int, str], ...]:
    """Search the verified assessment-scoped FTS derivative, rebuilding once if stale."""

    if not source_ids:
        return ()
    path = projection_database_path(workspace)
    rebuilt = False
    while True:
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                schema = connection.execute(
                    "SELECT value FROM metadata WHERE key='fts_schema'"
                ).fetchone()
                basis = connection.execute(
                    "SELECT value FROM metadata WHERE key='fts_basis'"
                ).fetchone()
                if (
                    schema is None
                    or bytes(schema[0]) != PROJECTION_SCHEMA.encode()
                    or basis is None
                    or bytes(basis[0]).decode() != _fts_basis(connection)
                ):
                    raise ValueError("FTS derivative is stale")
                authoritative_rows = connection.execute(
                    "SELECT source_id,page_number,text FROM pages ORDER BY source_id,page_number"
                ).fetchall()
                indexed_rows = connection.execute(
                    "SELECT source_id,page_number,text FROM pages_fts "
                    "ORDER BY source_id,page_number"
                ).fetchall()
                if indexed_rows != authoritative_rows:
                    raise ValueError("FTS derivative content differs from verified pages")
                placeholders = ",".join("?" for _ in source_ids)
                rows = connection.execute(
                    "SELECT source_id,page_number,text FROM pages_fts "
                    f"WHERE pages_fts MATCH ? AND source_id IN ({placeholders}) "
                    "ORDER BY source_id,page_number",
                    (query, *source_ids),
                ).fetchall()
                rank = {source_id: index for index, source_id in enumerate(source_ids)}
                result = tuple((str(row[0]), int(row[1]), str(row[2])) for row in rows)
                return tuple(sorted(result, key=lambda row: (rank[row[0]], row[1])))
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError):
            if rebuilt:
                raise
            build_fts_index(workspace)
            rebuilt = True


def _fts_basis(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT source_id,source_hash,page_number,page_hash FROM pages "
        "ORDER BY source_id,page_number"
    ).fetchall()
    return sha256(tuple(tuple(row) for row in rows))


def _read_projection(
    workspace: str | Path, source: Source, expected: TextProjectionIdentity
) -> tuple[str, ...]:
    path = projection_database_path(workspace)
    if not path.exists():
        raise ValueError("text projection store is unavailable")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        schema = connection.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        if schema is None or bytes(schema[0]) != PROJECTION_SCHEMA.encode():
            raise ValueError("text projection schema is unsupported")
        identity_row = connection.execute(
            "SELECT value FROM metadata WHERE key=?", (f"projection:{source.id}",)
        ).fetchone()
        if identity_row is None:
            raise ValueError("text projection identity is unavailable")
        stored_identity = TextProjectionIdentity.model_validate_json(bytes(identity_row[0]))
        rows = connection.execute(
            "SELECT page_number,source_hash,page_hash,text FROM pages WHERE source_id=? "
            "ORDER BY page_number",
            (source.id,),
        ).fetchall()
    finally:
        connection.close()
    pages = tuple(str(row[3]) for row in rows)
    actual = projection_identity(source, pages)
    if (
        actual != expected
        or stored_identity != expected
        or tuple(row[0] for row in rows) != tuple(range(1, expected.page_count + 1))
        or tuple(row[2] for row in rows) != expected.page_hashes
        or any(row[1] != expected.source_sha256 for row in rows)
    ):
        raise ValueError("stored text projection differs from frozen identity")
    return pages


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value BLOB NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pages("
        "source_id TEXT NOT NULL, source_hash TEXT NOT NULL, page_number INTEGER NOT NULL, "
        "page_hash TEXT NOT NULL, text TEXT NOT NULL, "
        "PRIMARY KEY(source_id,page_number))"
    )
    connection.execute(
        "INSERT INTO metadata(key,value) VALUES('schema',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (PROJECTION_SCHEMA.encode(),),
    )


def _store_projection(
    connection: sqlite3.Connection,
    source: Source,
    identity: TextProjectionIdentity,
    pages: tuple[str, ...],
) -> None:
    connection.execute("DELETE FROM pages WHERE source_id=?", (source.id,))
    connection.executemany(
        "INSERT INTO pages(source_id,source_hash,page_number,page_hash,text) VALUES(?,?,?,?,?)",
        [
            (source.id, source.sha256, number, identity.page_hashes[number - 1], text)
            for number, text in enumerate(pages, 1)
        ],
    )
    connection.execute(
        "INSERT INTO metadata(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"projection:{source.id}", canonical_json_bytes(identity)),
    )


def _reparse(path: Path) -> bool:
    import stat

    metadata = os.lstat(path)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


__all__ = [
    "PROJECTION_DB_NAME",
    "PROJECTION_RECIPE",
    "PROJECTION_SCHEMA",
    "TextProjectionIdentity",
    "VerifiedProjection",
    "build_fts_index",
    "extract_projection",
    "materialize_projection",
    "materialize_projections",
    "projection_database_path",
    "projection_identity",
    "search_fts_pages",
    "stored_projection_identity",
    "verified_pages",
]
