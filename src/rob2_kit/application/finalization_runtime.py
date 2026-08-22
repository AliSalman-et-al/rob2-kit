"""Finalization wrapper that adds a compact transitive-closure archive."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._state import write_json
from .archive import verify_archive, write_archive
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


def _root_ids(summary: dict[str, object], records: dict[str, dict[str, object]]) -> list[str]:
    roots: list[str] = []
    approved = summary.get("approved_batch")
    if isinstance(approved, dict) and isinstance(approved.get("identity"), str):
        roots.append(str(approved["identity"]))
    for trial in summary.get("trials", ()):
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
        } and isinstance(record.get("identity"), str):
            roots.append(str(record["identity"]))
    return roots


def finalize_with_archive(workspace: str | Path) -> object:
    result = finalize_batch(workspace)
    if isinstance(result, FinalizationCondition):
        return result
    root = Path(workspace).resolve(strict=True)
    bundle = (root / result.artifact.bundle_path).resolve(strict=True)
    if not bundle.is_relative_to(root) or not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("verified loose finalization bundle is unavailable")
    summary = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    records = _json_files(bundle / "records")
    roots = _root_ids(summary, records)
    closure_text = "\n".join(
        json.dumps(value, sort_keys=True, separators=(",", ":"))
        for value in records.values()
        if isinstance(value.get("identity"), str) and value["identity"] in roots
    )
    render_ids = set(_RENDER.findall(closure_text))
    renders: dict[str, bytes] = {}
    render_root = bundle / "renders"
    if render_root.is_dir():
        for path in render_root.iterdir():
            if path.is_file() and not path.is_symlink():
                if not render_ids or any(identifier.removeprefix("sha256:") in path.name for identifier in render_ids):
                    renders[path.name] = path.read_bytes()
    sources: dict[str, bytes] = {}
    source_root = bundle / "sources"
    if source_root.is_dir():
        for path in source_root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                sources[path.relative_to(source_root).as_posix()] = path.read_bytes()
    report_html = (bundle / "report.html").read_text(encoding="utf-8")
    artifact = write_archive(
        workspace,
        approved_identity=result.artifact.bundle_path.rsplit("/", 1)[-1],
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
    return payload
