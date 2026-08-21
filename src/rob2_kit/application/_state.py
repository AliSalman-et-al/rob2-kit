"""Canonical application records stored in the verified SQLite ledger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rob2_kit.storage import read_only_transaction, transaction


def _key(name: str) -> str:
    if not name.endswith(".json") or "/" in name or "\\" in name:
        raise ValueError("invalid application record name")
    return f"application:{name}"


def read_json(workspace: str | Path, name: str) -> dict[str, Any] | None:
    with read_only_transaction(workspace) as connection:
        if connection is None:
            return None
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (_key(name),)
        ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(bytes(row[0]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("application record is corrupt") from error
    if not isinstance(value, dict):
        raise ValueError("application record is not an object")
    return value


def write_json(workspace: str | Path, name: str, value: dict[str, Any]) -> None:
    write_jsons(workspace, {name: value})


def delete_json(workspace: str | Path, name: str) -> None:
    with transaction(workspace) as connection:
        connection.execute("DELETE FROM records WHERE name=?", (_key(name),))


def write_jsons(workspace: str | Path, values: dict[str, dict[str, Any]]) -> None:
    """Commit related application records in one SQLite transaction."""
    with transaction(workspace) as connection:
        for name, value in values.items():
            payload = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                (_key(name), payload),
            )


def identity(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def record_uri(kind: str, record_identity: str) -> str:
    return f"rob2://detail/{kind}/{record_identity}"
