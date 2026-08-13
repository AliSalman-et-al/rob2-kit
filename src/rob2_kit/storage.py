"""Contained SQLite BLOB storage for the one active batch."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _reparse(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def database_path(workspace: str | Path) -> Path:
    root = Path(workspace).resolve(strict=True)
    internal = root / ".rob2-kit"
    internal.mkdir(exist_ok=True)
    if internal.is_symlink() or _reparse(internal):
        raise ValueError("internal workspace directory is redirected")
    path = internal / "active-batch.sqlite3"
    if path.exists() and (path.is_symlink() or _reparse(path)):
        raise ValueError("active batch database is redirected")
    return path


@contextmanager
def transaction(workspace: str | Path) -> Iterator[sqlite3.Connection]:
    path = database_path(workspace)
    connection = sqlite3.connect(path, isolation_level=None, timeout=10)
    begun = False
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, payload BLOB NOT NULL)"
        )
        connection.execute("BEGIN IMMEDIATE")
        begun = True
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        if begun:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def load_state(workspace: str | Path) -> bytes | None:
    path = database_path(workspace)
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
    return None if row is None else bytes(row[0])


def save_state(workspace: str | Path, payload: bytes) -> None:
    with transaction(workspace) as connection:
        connection.execute(
            "INSERT INTO records(name,payload) VALUES('active_batch',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (payload,),
        )
