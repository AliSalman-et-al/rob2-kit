"""Contained SQLite BLOB storage for the one active batch."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock

_MUTATION_LOCKS: dict[str, RLock] = {}
_MUTATION_LOCKS_GUARD = Lock()


class WorkspaceLockedError(RuntimeError):
    """Another server process owns this workspace."""


class WorkspaceLock:
    """An advisory OS lock held for one server process; never a lease."""

    def __init__(self, workspace: str | Path) -> None:
        root = Path(workspace).resolve(strict=True)
        internal = root / ".rob2-kit"
        if internal.exists() and (internal.is_symlink() or _reparse(internal)):
            raise ValueError("internal workspace directory is redirected")
        internal.mkdir(exist_ok=True)
        if internal.is_symlink() or _reparse(internal):
            raise ValueError("internal workspace directory is redirected")
        self.path = internal / "server.lock"
        if self.path.exists() and (self.path.is_symlink() or _reparse(self.path)):
            raise ValueError("workspace lock path is redirected")
        self._handle = None

    def __enter__(self) -> WorkspaceLock:
        # Check immediately before opening too: a pre-existing redirected lock file
        # must never be followed merely to attempt advisory locking.
        if self.path.exists() and (self.path.is_symlink() or _reparse(self.path)):
            raise ValueError("workspace lock path is redirected")
        handle = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise WorkspaceLockedError("workspace is already owned by a server") from error
        self._handle = handle
        return self

    def __exit__(self, *_: object) -> None:
        if self._handle is None:
            return
        if sys.platform == "win32":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


@contextmanager
def workspace_mutation_lock(workspace: str | Path) -> Iterator[None]:
    """Serialize mutations in this process for one resolved workspace.

    ``WorkspaceLock`` remains the cross-process server boundary. This reentrant
    lock closes gaps between separate SQLite transactions and filesystem moves.
    The process-lifetime map is bounded by the workspaces a server process uses.
    """

    key = str(Path(workspace).resolve(strict=True))
    with _MUTATION_LOCKS_GUARD:
        lock = _MUTATION_LOCKS.setdefault(key, RLock())
    with lock:
        yield


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
    with workspace_mutation_lock(workspace):
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
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
    finally:
        connection.close()
    return None if row is None else bytes(row[0])


def save_state(workspace: str | Path, payload: bytes) -> None:
    with transaction(workspace) as connection:
        connection.execute(
            "INSERT INTO records(name,payload) VALUES('active_batch',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (payload,),
        )
