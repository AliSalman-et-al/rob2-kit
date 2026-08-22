"""Materialize matched ClinicalTrials.gov records as immutable Evidence Sources."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from rob2_kit.sources import Source, SourceRole, _extract_pages, sha256_bytes
from rob2_kit.text_projection import TextProjectionIdentity, projection_identity

from ._state import identity, read_json, write_json

_NCT = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
_HOOK_INSTALLED = False


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return value
    return ()


def _root_paths(workspace: Path, preflight: Mapping[str, object]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw_root in _sequence(preflight.get("roots")):
        if not isinstance(raw_root, Mapping):
            continue
        alias, path = raw_root.get("alias"), raw_root.get("path")
        if isinstance(alias, str) and isinstance(path, str):
            candidate = (workspace / path).resolve()
            if candidate.is_relative_to(workspace):
                result[alias] = candidate
    return result


def _trial_text(
    workspace: Path, preflight: Mapping[str, object], trial_id: str
) -> str:
    roots = _root_paths(workspace, preflight)
    chunks: list[str] = [trial_id]
    for raw_candidate in _sequence(preflight.get("candidates")):
        if (
            not isinstance(raw_candidate, Mapping)
            or raw_candidate.get("trial_id") != trial_id
        ):
            continue
        candidate = dict(raw_candidate)
        chunks.append(json.dumps(candidate, sort_keys=True, default=str))
        alias, relative, media = (
            candidate.get("root_alias"),
            candidate.get("relative_path"),
            candidate.get("media_type"),
        )
        if not all(isinstance(item, str) for item in (alias, relative, media)):
            continue
        root = roots.get(cast(str, alias))
        if root is None:
            continue
        path = (root / cast(str, relative)).resolve()
        if not path.is_relative_to(workspace) or not path.is_file() or path.is_symlink():
            continue
        try:
            chunks.extend(_extract_pages(path.read_bytes(), cast(str, media)))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return "\n".join(chunks)


def _nct_ids(
    workspace: Path, preflight: Mapping[str, object], trial_id: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                match.group().upper()
                for match in _NCT.finditer(_trial_text(workspace, preflight, trial_id))
            }
        )
    )


def _fetch(nct_id: str) -> bytes:
    request = urllib.request.Request(
        f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
        headers={"Accept": "application/json", "User-Agent": "rob2-kit/registry-source"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
    parsed = json.loads(data)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _preflight_value(
    workspace: str | Path, value: object | None
) -> dict[str, object] | None:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raw = read_json(workspace, "preflight.json")
    return raw if isinstance(raw, dict) else None


def _outcomes(preflight: Mapping[str, object]) -> dict[str, object]:
    raw = preflight.get("registry_outcomes", ())
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes | bytearray):
        result: dict[str, object] = {}
        for item in raw:
            if (
                isinstance(item, Sequence)
                and not isinstance(item, str | bytes | bytearray)
                and len(item) == 2
            ):
                result[str(item[0])] = item[1]
        return result
    return {}


def ensure_registry_snapshot(
    workspace: str | Path, preflight_value: object | None = None
) -> dict[str, object]:
    root = Path(workspace).resolve(strict=True)
    preflight = _preflight_value(workspace, preflight_value)
    if preflight is None:
        return {
            "outcome": "condition",
            "sources": [],
            "conditions": [
                {
                    "code": "preflight_unavailable",
                    "detail": "registry materialization requires source preflight",
                }
            ],
        }
    outcomes = _outcomes(preflight)
    trial_ids = {
        str(item.get("trial_id"))
        for item in _sequence(preflight.get("candidates"))
        if isinstance(item, Mapping) and item.get("trial_id")
    }
    trials = sorted(trial_ids | set(outcomes))
    materialized: list[dict[str, object]] = []
    conditions: list[dict[str, object]] = []
    for trial_id in trials:
        if outcomes.get(trial_id) != "matched":
            continue
        nct_ids = _nct_ids(root, preflight, trial_id)
        current = read_json(workspace, f"registry-source-{trial_id}.json")
        if isinstance(current, dict) and (not nct_ids or current.get("nct_id") in nct_ids):
            try:
                registry_source(workspace, trial_id)
            except (OSError, TypeError, ValueError):
                current = None
            else:
                materialized.append(current)
                continue
        if len(nct_ids) != 1:
            conditions.append(
                {
                    "trial_id": trial_id,
                    "code": (
                        "registry_identifier_unavailable"
                        if not nct_ids
                        else "registry_identifier_ambiguous"
                    ),
                    "detail": (
                        "registry matched but the Trial dossier did not identify "
                        "exactly one NCT record"
                    ),
                    "matched_nct_ids": list(nct_ids),
                }
            )
            continue
        nct_id = nct_ids[0]
        try:
            data = _fetch(nct_id)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            conditions.append(
                {"trial_id": trial_id, "code": "registry_fetch_failed", "detail": str(error)}
            )
            continue
        directory = root / ".rob2-kit" / "registry" / trial_id
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("registry source directory is redirected")
        data_hash = sha256_bytes(data)
        source_id = (
            "registry_"
            + hashlib.sha256(f"{trial_id}\0{nct_id}\0{data_hash}".encode()).hexdigest()
        )
        path = directory / f"{nct_id}.json"
        if path.exists() and path.read_bytes() != data:
            raise ValueError("registry path is bound to different bytes")
        path.write_bytes(data)
        payload: dict[str, object] = {
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
    install_registry_source_hook()
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
    return {
        "source": source.model_dump(mode="json"),
        "record": json.loads((root / source.captured_path).read_bytes()),
    }


def install_registry_source_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    from . import evidence

    original = evidence._source_basis

    def source_basis(
        workspace: str | Path, trial_id: str
    ) -> tuple[tuple[Source, ...], tuple[TextProjectionIdentity, ...]]:
        sources, projections = original(workspace, trial_id)
        registry = registry_source(workspace, trial_id)
        if registry is None or any(item.id == registry.id for item in sources):
            return sources, projections
        root = Path(workspace).resolve(strict=True)
        path = root / registry.captured_path
        if not path.is_file() or path.is_symlink():
            raise ValueError("registry source bytes are unavailable")
        pages = _extract_pages(path.read_bytes(), registry.media_type)
        combined = [
            *zip(sources, projections, strict=True),
            (registry, projection_identity(registry, pages)),
        ]
        combined.sort(
            key=lambda pair: (
                0
                if pair[0].role is SourceRole.MAIN_ARTICLE
                else 1
                if pair[0].role is SourceRole.REGISTRY
                else 2,
                pair[0].label.casefold(),
                pair[0].id,
            )
        )
        return tuple(item[0] for item in combined), tuple(item[1] for item in combined)

    cast(Any, evidence)._source_basis = source_basis
    _HOOK_INSTALLED = True


__all__ = [
    "ensure_registry_snapshot",
    "install_registry_source_hook",
    "registry_record",
    "registry_source",
]