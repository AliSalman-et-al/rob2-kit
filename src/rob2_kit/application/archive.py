"""Compact deterministic finalization archives."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ._state import identity


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArchiveArtifact(_Closed):
    archive_path: str
    archive_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    file_count: int = Field(ge=1)
    byte_count: int = Field(ge=1)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _references(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        identity_value = value.get("identity")
        kind = value.get("kind")
        if (
            isinstance(identity_value, str)
            and identity_value.startswith("sha256:")
            and isinstance(kind, str)
        ):
            found.add(identity_value)
        for child in value.values():
            found.update(_references(child))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for child in value:
            found.update(_references(child))
    return found


def record_closure(
    records: Mapping[str, dict[str, object]], roots: Sequence[str]
) -> dict[str, dict[str, object]]:
    """Return the transitive identity closure rooted in terminal records."""

    by_identity = {
        str(record.get("identity")): record
        for record in records.values()
        if isinstance(record.get("identity"), str)
    }
    selected: dict[str, dict[str, object]] = {}
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in selected:
            continue
        record = by_identity.get(current)
        if record is None:
            continue
        selected[current] = record
        queue.extend(_references(record) - set(selected))
    return selected


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def write_archive(
    workspace: str | Path,
    *,
    approved_identity: str,
    summary: dict[str, object],
    records: Mapping[str, dict[str, object]],
    root_record_ids: Sequence[str],
    sources: Mapping[str, bytes],
    renders: Mapping[str, bytes],
    report_html: str,
) -> ArchiveArtifact:
    root = Path(workspace).resolve(strict=True)
    output = root / ".rob2-kit" / "archives"
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("archive output directory is redirected")
    name = approved_identity.removeprefix("sha256:") + ".rob2.zip"
    path = output / name
    closure = record_closure(records, root_record_ids)
    entries: dict[str, bytes] = {
        "summary.json": _json(summary),
        "report.html": report_html.encode("utf-8"),
    }
    for record_identity, record in sorted(closure.items()):
        entries[f"records/{record_identity.removeprefix('sha256:')}.json"] = _json(record)
    for source_name, data in sorted(sources.items()):
        entries[f"sources/{source_name}"] = data
    for render_name, data in sorted(renders.items()):
        entries[f"renders/{render_name}"] = data
    file_rows = [
        {"path": entry, "sha256": _sha(data), "bytes": len(data)}
        for entry, data in sorted(entries.items())
    ]
    manifest_base = {
        "format": "rob2-archive/v1",
        "summary_identity": summary.get("identity"),
        "approved_batch": approved_identity,
        "files": file_rows,
    }
    manifest_hash = identity(manifest_base)
    entries["manifest.json"] = _json({**manifest_base, "manifest_hash": manifest_hash})
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for entry, data in sorted(entries.items()):
            archive.writestr(_zip_info(entry), data)
    data = temporary.read_bytes()
    if path.exists() and path.read_bytes() != data:
        raise ValueError("archive path is bound to different bytes")
    temporary.replace(path)
    return ArchiveArtifact(
        archive_path=path.relative_to(root).as_posix(),
        archive_hash=_sha(data),
        manifest_hash=manifest_hash,
        file_count=len(entries),
        byte_count=len(data),
    )


def verify_archive(workspace: str | Path, artifact: ArchiveArtifact) -> bool:
    root = Path(workspace).resolve(strict=True)
    path = (root / artifact.archive_path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        return False
    data = path.read_bytes()
    if _sha(data) != artifact.archive_hash or len(data) != artifact.byte_count:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != artifact.file_count or len(names) != len(set(names)):
                return False
            manifest = json.loads(archive.read("manifest.json"))
            base = {
                "format": manifest["format"],
                "summary_identity": manifest["summary_identity"],
                "approved_batch": manifest["approved_batch"],
                "files": manifest["files"],
            }
            if (
                manifest.get("manifest_hash") != artifact.manifest_hash
                or identity(base) != artifact.manifest_hash
            ):
                return False
            expected = {str(row["path"]): row for row in manifest["files"]}
            if set(names) != set(expected) | {"manifest.json"}:
                return False
            for name, row in expected.items():
                content = archive.read(name)
                if _sha(content) != row["sha256"] or len(content) != row["bytes"]:
                    return False
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
    return True
