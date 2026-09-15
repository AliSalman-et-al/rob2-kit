"""Active workspace version cutover behavior."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rob2_kit.application._state import _ensure


def test_new_workspace_uses_v0_6_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".rob2-kit").mkdir(parents=True)

    _ensure(workspace)

    with sqlite3.connect(workspace / ".rob2-kit" / "canonical.sqlite3") as connection:
        contract = connection.execute("SELECT value FROM meta WHERE name='contract'").fetchone()
    assert contract == ("0.6.0",)


def test_workspace_probe_releases_read_only_database_handle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".rob2-kit").mkdir(parents=True)
    _ensure(workspace)

    _ensure(workspace)
    shutil.rmtree(workspace)

    assert not workspace.exists()


def test_v0_8_workspace_is_rejected_without_modification(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    internal = workspace / ".rob2-kit"
    internal.mkdir(parents=True)
    canonical = internal / "canonical.sqlite3"
    with sqlite3.connect(canonical) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('contract','0.5.0')")
    original = canonical.read_bytes()

    with pytest.raises(
        ValueError,
        match=r"workspace_contract_unsupported:.*0\.5\.0.*new empty workspace",
    ):
        _ensure(workspace)

    assert canonical.read_bytes() == original
    assert not (internal / "derivative.sqlite3").exists()


def test_legacy_active_batch_workspace_is_rejected_without_modification(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    internal = workspace / ".rob2-kit"
    internal.mkdir(parents=True)
    legacy = internal / "active-batch.sqlite3"
    legacy.write_bytes(b"legacy active workspace")
    original = legacy.read_bytes()

    with pytest.raises(
        ValueError,
        match=r"workspace_contract_unsupported:.*new empty workspace",
    ):
        _ensure(workspace)

    assert legacy.read_bytes() == original
    assert not (internal / "canonical.sqlite3").exists()
