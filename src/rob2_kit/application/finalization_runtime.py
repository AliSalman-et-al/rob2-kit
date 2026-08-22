"""Finalization wrapper that adds a compact transitive-closure archive."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ._state import read_json, write_json
from .archive import record_closure, verify_archive, write_archive
from .finalization import FinalizationCondition, finalize_batch

_RENDER = re.compile(r"rob2://render/(sha256:[0-9a-f]{64})")


def _json_files(root: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    if not root.is_dir():
        return records
    for path in root.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records[path.relative_to(root).as_posix()] = value
    return records


def _runtime_records(workspace: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for pattern in (
        "proposal-provenance-*.json",
        "domain-scientific-*.json",
        "registry-source-*.json",
        "table-evidence-*.json",
    ):
        for path in workspace.glob(pattern):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records[f"runtime/{path.name}"] = value
    return records


def _root_ids(summary: dict[str, object], records: dict[str, dict[str, object]]) -> list[str]:
    roots: list[str] = []
    approved = summary.get("approved_batch")
    if isinstance(approved, dict) and isinstance(approved.get("identity"), str):
        roots.append(str(approved["identity"]))
    trials = summary.get("trials", ())
    if isinstance(trials, (list, tuple)):
        for trial in trials:
            if not isinstance(trial, dict):
                continue
            for key in ("outcome", "snapshot"):
                value = trial.get(key)
                if isinstance(value, dict) and isinstance(value.get("identity"), str):
                    roots.append(str(value["identity"]))
    for record in records.values():
        if record.get("kind") in {
            "proposal_provenance",
            "domain_scientific_draft",
            "registry_source",
            "table_cell_evidence",
        } and isinstance(record.get("identity"), str):
            roots.append(str(record["identity"]))
    return roots


def _registry_sources(workspace: Path) -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    for metadata in workspace.glob("registry-source-*.json"):
        raw = read_json(workspace, metadata.name)
        if not isinstance(raw, dict) or not isinstance(raw.get("captured_path"), str):
            continue
        path = (workspace / str(raw["captured_path"])).resolve(strict=True)
        if path.is_relative_to(workspace) and path.is_file() and not path.is_symlink():
            sources[f"registry/{path.name}"] = path.read_bytes()
    return sources


def finalize_with_archive(workspace: str | Path) -> object:
    result = finalize_batch(workspace)
    if isinstance(result, FinalizationCondition):
        return result
    root = Path(workspace).resolve(strict=True)
    bundle = (root / result.artifact.bundle_path).resolve(strict=True)
    if not bundle.is_relative_to(root) or not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("verified loose finalization bundle is unavailable")
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    records = {**_json_files(bundle / "records"), **_runtime_records(root)}
    roots = _root_ids(summary, records)
    selected = record_closure(records, roots)
    closure_text = "\n".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) for value in selected.values()
    )
    render_ids = set(_RENDER.findall(closure_text))
    renders: dict[str, bytes] = {}
    render_root = bundle / "renders"
    if render_root.is_dir():
        for path in render_root.iterdir():
            if (
                path.is_file()
                and not path.is_symlink()
                and any(
                    identifier.removeprefix("sha256:") in path.name for identifier in render_ids
                )
            ):
                renders[path.name] = path.read_bytes()
    sources: dict[str, bytes] = _registry_sources(root)
    seen_hashes = {hashlib.sha256(value).hexdigest() for value in sources.values()}
    source_root = bundle / "sources"
    if source_root.is_dir():
        for path in source_root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            sources[path.relative_to(source_root).as_posix()] = data
    report_html = (bundle / "report.html").read_text(encoding="utf-8")
    approved = summary.get("approved_batch")
    if not isinstance(approved, dict) or not isinstance(approved.get("identity"), str):
        raise ValueError("finalization summary lacks approved Batch identity")
    artifact = write_archive(
        workspace,
        approved_identity=str(approved["identity"]),
        summary=summary,
        records=records,
        root_record_ids=roots,
        sources=sources,
        renders=renders,
        report_html=report_html,
    )
    if not verify_archive(workspace, artifact):
        raise ValueError("compact finalization archive failed verification")
    write_json(
        workspace,
        f"compact-archive-{result.summary.identity.removeprefix('sha256:')}.json",
        {
            "kind": "compact_archive",
            "summary": result.summary.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
        },
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["compact_archive"] = artifact.model_dump(mode="json")
    payload["artifact_preference"] = "compact_archive"
    return payload
