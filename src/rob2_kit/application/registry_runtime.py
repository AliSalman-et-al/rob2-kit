"""Materialize matched ClinicalTrials.gov records as immutable Evidence Sources."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from rob2_kit.sources import Source, SourceRole, _extract_pages, sha256_bytes

from ._state import identity, read_json, write_json

_NCT = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_strings(child)


def _root_paths(workspace: Path, preflight: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in preflight.get("roots", ()):
        if not isinstance(root, dict):
            continue
        alias, path = root.get("alias"), root.get("path")
        if isinstance(alias, str) and isinstance(path, str):
            candidate = (workspace / path).resolve()
            if candidate.is_relative_to(workspace):
                result[alias] = candidate
    return result


def _candidate_text(workspace: Path, preflight: dict[str, Any]) -> str:
    roots = _root_paths(workspace, preflight)
    chunks: list[str] = []
    for candidate in preflight.get("candidates", ()):
        if not isinstance(candidate, dict):
            continue
        alias, relative, media = (
            candidate.get("root_alias"),
            candidate.get("relative_path"),
            candidate.get("media_type"),
        )
        if not all(isinstance(item, str) for item in (alias, relative, media)):
            continue
        root = roots.get(alias)
        if root is None:
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(workspace) or not path.is_file():
            continue
        try:
            chunks.extend(_extract_pages(path.read_bytes(), media))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return "\n".join(chunks)


def _nct_ids(workspace: Path, preflight: dict[str, Any]) -> tuple[str, ...]:
    values = "\n".join(_walk_strings(preflight)) + "\n" + _candidate_text(workspace, preflight)
    return tuple(sorted({match.group().upper() for match in _NCT.finditer(values)}))


def _fetch(nct_id: str) -> bytes:
    request = urllib.request.Request(
        f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
        headers={"Accept": "application/json", "User-Agent": "rob2-kit/registry-source"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
    parsed = json.loads(data)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ensure_registry_snapshot(
    workspace: str | Path, preflight_value: object | None = None
) -> dict[str, object]:
    root = Path(workspace).resolve(strict=True)
    preflight = (
        preflight_value.model_dump(mode="json")
        if hasattr(preflight_value, "model_dump")
        else preflight_value
        if isinstance(preflight_value, dict)
        else read_json(workspace, "preflight.json")
    )
    if not isinstance(preflight, dict):
        return {"outcome": "condition", "code": "preflight_unavailable"}
    outcomes = dict(preflight.get("registry_outcomes", ()))
    trials = sorted(
        {
            str(item.get("trial_id"))
            for item in preflight.get("candidates", ())
            if isinstance(item, dict) and item.get("trial_id")
        }
        | set(str(item) for item in outcomes)
    )
    nct_ids = _nct_ids(root, preflight)
    materialized: list[dict[str, object]] = []
    conditions: list[dict[str, object]] = []
    for trial_id in trials:
        if outcomes.get(trial_id) != "matched":
            continue
        current = read_json(workspace, f"registry-source-{trial_id}.json")
        if isinstance(current, dict):
            materialized.append(current)
            continue
        if not nct_ids:
            conditions.append(
                {
                    "trial_id": trial_id,
                    "code": "registry_identifier_unavailable",
                    "detail": "registry matched but no NCT identifier was found in the dossier",
                }
            )
            continue
        nct_id = nct_ids[0]
        try:
            data = _fetch(nct_id)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            conditions.append(
                {
                    "trial_id": trial_id,
                    "code": "registry_fetch_failed",
                    "detail": str(error),
                }
            )
            continue
        directory = root / ".rob2-kit" / "registry" / trial_id
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("registry source directory is redirected")
        data_hash = sha256_bytes(data)
        source_id = "registry_" + hashlib.sha256(
            f"{trial_id}\0{nct_id}\0{data_hash}".encode()
        ).hexdigest()
        path = directory / f"{nct_id}.json"
        if path.exists() and path.read_bytes() != data:
            raise ValueError("registry path is bound to different bytes")
        path.write_bytes(data)
        payload = {
            "kind": "registry_source",
            "trial_id": trial_id,
            "nct_id": nct_id,
            "matched_nct_ids": list(nct_ids),
            "source_id": source_id,
            "sha256": data_hash,
            "media_type": "application/json",
            "page_count": 1,
            "captured_path": path.relative_to(root).as_posix(),
        }
        payload["identity"] = identity(payload)
        write_json(workspace, f"registry-source-{trial_id}.json", payload)
        materialized.append(payload)
    return {
        "outcome": "success" if not conditions else "condition",
        "sources": materialized,
        "conditions": conditions,
    }


def registry_source(workspace: str | Path, trial_id: str) -> Source | None:
    raw = read_json(workspace, f"registry-source-{trial_id}.json")
    if not isinstance(raw, dict):
        return None
    root = Path(workspace).resolve(strict=True)
    path = (root / str(raw.get("captured_path", ""))).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError("registry source bytes are unavailable")
    data = path.read_bytes()
    if sha256_bytes(data) != raw.get("sha256"):
        raise ValueError("registry source bytes are stale")
    payload = {key: raw[key] for key in raw if key != "identity"}
    if identity(payload) != raw.get("identity"):
        raise ValueError("registry source metadata is corrupt")
    return Source(
        id=str(raw["source_id"]),
        trial_id=trial_id,
        role=SourceRole.REGISTRY,
        label=f"ClinicalTrials.gov {raw['nct_id']}",
        sha256=str(raw["sha256"]),
        media_type="application/json",
        page_count=1,
        extraction_warnings=(),
        captured_path=str(raw["captured_path"]),
    )


def registry_record(workspace: str | Path, trial_id: str) -> dict[str, object]:
    source = registry_source(workspace, trial_id)
    if source is None:
        raise ValueError("registry record is unavailable")
    root = Path(workspace).resolve(strict=True)
    data = (root / source.captured_path).read_bytes()
    return {
        "source": source.model_dump(mode="json"),
        "record": json.loads(data),
    }
