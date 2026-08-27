"""Deterministic researcher-requested archive of captured Source bytes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from ..models import canonical_json_bytes
from ._state import _identity, _root, _state, internal_path

_SCHEMA = "rob2-kit.source-archive.v0.1"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_SOURCE_FIELDS = {
    "trial_id",
    "id",
    "role",
    "label",
    "logical_path",
    "sha256",
    "media_type",
    "page_count",
    "origin",
    "projection_hash",
}


def _manifest_for_state(
    root: Path, state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bytes]]:
    batch = state.get("batch")
    if not isinstance(batch, dict) or not isinstance(batch.get("trials"), list):
        raise ValueError("source archive requires a captured Batch")
    sources: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    for trial in batch["trials"]:
        if not isinstance(trial, dict) or not isinstance(trial.get("id"), str):
            raise ValueError("captured Trial metadata is corrupt")
        trial_id = trial["id"]
        for source in trial.get("sources", []):
            if not isinstance(source, dict) or set(source) != {
                "id",
                "trial_id",
                "role",
                "label",
                "logical_path",
                "sha256",
                "media_type",
                "page_count",
                "origin",
                "projection_hash",
            }:
                raise ValueError("captured Source metadata is corrupt")
            if source["trial_id"] != trial_id:
                raise ValueError("captured Source Trial identity is corrupt")
            source_id = str(source["id"])
            archive_path = f"sources/{trial_id}/{source_id}.bin"
            payload_path = internal_path(root, "sources", trial_id, f"{source_id}.bin")
            if not payload_path.is_file():
                raise ValueError("captured Source bytes are unavailable")
            payload = payload_path.read_bytes()
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            if digest != source["sha256"]:
                raise ValueError("captured Source bytes do not match Canonical identity")
            files[archive_path] = payload
            sources.append(
                {
                    "trial_id": trial_id,
                    **{key: source[key] for key in sorted(_SOURCE_FIELDS - {"trial_id"})},
                    "archive_path": archive_path,
                    "size": len(payload),
                }
            )
    sources.sort(key=lambda item: (item["trial_id"], item["logical_path"].casefold(), item["id"]))
    content = {"schema": _SCHEMA, "sources": sources}
    manifest = {**content, "identity": _identity(content)}
    files["manifest.json"] = canonical_json_bytes(manifest)
    return manifest, files


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return output.getvalue()


def archive_sources(workspace: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    root = _root(workspace)
    state = _state(root)
    manifest, files = _manifest_for_state(root, state)
    archive_bytes = _zip_bytes(files)
    if output is None:
        target = internal_path(
            root,
            "source-archives",
            manifest["identity"].removeprefix("sha256:") + ".sources.zip",
        )
    else:
        target = Path(output)
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    retry = target.is_file() and target.read_bytes() == archive_bytes
    if target.exists() and not retry:
        raise ValueError(f"source archive path already contains different bytes: {target}")
    if not retry:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(archive_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "outcome": "success",
        "path": target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target),
        "identity": manifest["identity"],
        "sha256": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
        "retry": retry,
        "sources": len(manifest["sources"]),
    }


def verify_source_archive(path: str | Path) -> bool:
    try:
        raw = Path(path).read_bytes()
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            if (
                names != sorted(names)
                or len(names) != len(set(names))
                or "manifest.json" not in names
            ):
                return False
            if any(
                PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                for name in names
            ):
                return False
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or set(manifest) != {"schema", "sources", "identity"}:
                return False
            content = {key: manifest[key] for key in ("schema", "sources")}
            if manifest["schema"] != _SCHEMA or manifest["identity"] != _identity(content):
                return False
            if not isinstance(manifest["sources"], list):
                return False
            source_keys: list[tuple[str, str]] = []
            expected_sources: list[dict[str, Any]] = []
            expected_names = {"manifest.json"}
            for source in manifest["sources"]:
                if not isinstance(source, dict) or set(source) != {
                    "trial_id",
                    "id",
                    "role",
                    "label",
                    "logical_path",
                    "sha256",
                    "media_type",
                    "page_count",
                    "origin",
                    "projection_hash",
                    "archive_path",
                    "size",
                }:
                    return False
                trial_id = source["trial_id"]
                source_id = source["id"]
                if (
                    not isinstance(trial_id, str)
                    or not trial_id
                    or not isinstance(source_id, str)
                    or not source_id
                    or source.get("role")
                    not in {
                        "main_article",
                        "registry",
                        "supplement",
                        "sap",
                        "protocol",
                        "other",
                    }
                    or source.get("origin")
                    not in {"local_dossier", "registry", "researcher_provided"}
                    or "/" in trial_id
                    or "\\" in trial_id
                    or "/" in source_id
                    or "\\" in source_id
                ):
                    return False
                expected_path = f"sources/{trial_id}/{source_id}.bin"
                archive_path = source["archive_path"]
                if archive_path != expected_path or archive_path in expected_names:
                    return False
                source_keys.append((trial_id, source_id))
                expected_sources.append(source)
                expected_names.add(archive_path)
                payload = archive.read(archive_path)
                if len(payload) != source["size"] or (
                    "sha256:" + hashlib.sha256(payload).hexdigest() != source["sha256"]
                ):
                    return False
            if len(source_keys) != len(set(source_keys)):
                return False
            if expected_sources != sorted(
                expected_sources,
                key=lambda item: (
                    item["trial_id"],
                    item["logical_path"].casefold(),
                    item["id"],
                ),
            ):
                return False
            if names != sorted(expected_names):
                return False
            for info in archive.infolist():
                if (
                    info.date_time != _ZIP_TIMESTAMP
                    or info.create_system != 3
                    or info.external_attr != 0o100644 << 16
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or info.extra
                ):
                    return False
            files = {
                "manifest.json": canonical_json_bytes(manifest),
                **{
                    source["archive_path"]: archive.read(source["archive_path"])
                    for source in expected_sources
                },
            }
            return raw == _zip_bytes(files)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
