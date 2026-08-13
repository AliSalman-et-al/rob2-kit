# ruff: noqa: E501
"""Deterministic standalone per-Trial assessment bundles."""

from __future__ import annotations

import html
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.judgment_models import TextEvidenceRef, VisualEvidenceRef
from rob2_kit.rendering import RenderedPage, render_page
from rob2_kit.search import _source_bytes
from rob2_kit.sources import Source, _extract_pages, sha256_bytes
from rob2_kit.storage import transaction


def _safe_child(parent: Path, name: str) -> Path:
    path = parent / name
    if (
        path.parent != parent
        or path.is_symlink()
        or (
            path.exists()
            and bool(
                getattr(os.lstat(path), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        )
    ):
        raise ValueError("assessment output path is redirected")
    return path


def _complete_bundle(path: Path, data: bytes, snapshot: AssessmentSnapshot) -> bool:
    try:
        if (
            path.is_symlink()
            or not path.is_dir()
            or (path / "assessment.json").read_bytes() != data
        ):
            return False
        if not (path / "report.html").is_file() or not (path / "sources").is_dir():
            return False
        for source in snapshot.sources:
            copied = path / "sources" / f"{source.id}{Path(source.captured_path).suffix}"
            if not copied.is_file() or sha256_bytes(copied.read_bytes()) != source.sha256:
                return False
        return (path / "assets").is_dir()
    except OSError:
        return False


def _recover(
    parent: Path, target: Path, backup: Path, data: bytes, snapshot: AssessmentSnapshot
) -> None:
    pattern = re.compile(rf"\.{re.escape(target.name)}-stage-[a-z0-9_]+")
    for item in parent.iterdir():
        if item.name.startswith(f".{target.name}-stage-"):
            if not pattern.fullmatch(item.name) or item.is_symlink() or not item.is_dir():
                raise ValueError("ambiguous assessment staging residue")
            shutil.rmtree(item)
    target_valid = target.exists() and _complete_bundle(target, data, snapshot)
    backup_valid = backup.exists() and _complete_bundle(backup, data, snapshot)
    if target.exists() and backup.exists():
        if target_valid:
            shutil.rmtree(backup)
        elif backup_valid:
            shutil.rmtree(target)
            backup.replace(target)
        else:
            raise ValueError("assessment residue cannot be verified")
    elif not target.exists() and backup.exists():
        if not backup_valid:
            raise ValueError("assessment backup cannot be verified")
        backup.replace(target)
    elif target.exists() and not target_valid:
        raise ValueError("assessment target cannot be verified")


def _snapshot_bytes(workspace: Path, trial_id: str, result_id: str) -> bytes:
    with transaction(workspace) as connection:
        rows = connection.execute(
            "SELECT payload FROM records WHERE name LIKE ?", (f"assessment_snapshot:%:{trial_id}",)
        ).fetchall()
    matches = [
        bytes(row[0])
        for row in rows
        if AssessmentSnapshot.model_validate_json(bytes(row[0])).result_spec.id == result_id
    ]
    if len(matches) != 1:
        raise ValueError("exact committed Trial ResultSpec snapshot is required")
    _verified(AssessmentSnapshot.model_validate_json(matches[0]))
    return matches[0]


def _text_ref(root: Path, sources: dict[str, Source], ref: TextEvidenceRef) -> str:
    source = sources[ref.source_id]
    page = _extract_pages(_source_bytes(root, source), source.media_type)[ref.page_number - 1]
    if source.sha256 != ref.source_sha256 or page[ref.start : ref.end] != ref.quote:
        raise ValueError("text citation no longer matches committed captured source")
    before, after = page[max(0, ref.start - 120) : ref.start], page[ref.end : ref.end + 120]
    return (
        f"<code>{html.escape(ref.source_id)} p.{ref.page_number} [{ref.start}:{ref.end}]</code> "
        f"<span>{html.escape(before)}<mark>{html.escape(ref.quote)}</mark>{html.escape(after)}</span>"
    )


def _visual_ref(
    root: Path, assets: Path, sources: dict[str, Source], ref: VisualEvidenceRef
) -> str:
    source = sources[ref.source_id]
    rendered = render_page(
        root, source, ref.page_number, None if ref.origin.value == "rendered_page" else ref.region
    )
    if not isinstance(rendered, RenderedPage) or rendered.sha256 != ref.image_sha256:
        raise ValueError("visual citation no longer matches committed render")
    name = f"{ref.image_sha256.removeprefix('sha256:')}.png"
    (assets / name).write_bytes(rendered.image_bytes)
    return (
        f'<figure><img src="assets/{name}" alt="{html.escape(ref.transcription)}">'
        f"<figcaption>{html.escape(ref.origin)} p.{ref.page_number}: {html.escape(ref.transcription)}</figcaption></figure>"
    )


def _report(root: Path, snapshot: AssessmentSnapshot, stage: Path) -> bytes:
    sources = {source.id: source for source in snapshot.sources}
    assets = stage / "assets"
    assets.mkdir()
    domains = []
    for judgment in snapshot.domain_judgments:
        answers = []
        for answer in judgment.active_answers:
            uses = []
            for use in answer.evidence_uses:
                refs = []
                for ref in use.refs:
                    refs.append(
                        _text_ref(root, sources, ref)
                        if ref.kind == "text"
                        else _visual_ref(root, assets, sources, ref)
                    )
                uses.append(
                    f"<li><b>{html.escape(use.relationship)}</b>: {html.escape(use.claim)} — {html.escape(use.rationale)}<br>{''.join(refs)}</li>"
                )
            answers.append(
                f"<li>{html.escape(answer.question_id)} = {html.escape(answer.answer)} — {html.escape(answer.rationale)}<ul>{''.join(uses)}</ul></li>"
            )
        domains.append(
            f"<details open><summary>{html.escape(judgment.domain_id)}: {html.escape(judgment.final_judgment)}</summary>"
            f"<p>Proposed: {html.escape(judgment.proposed_judgment)}; trace: {html.escape(', '.join(judgment.trace))}</p>"
            f"<ul>{''.join(answers)}</ul><p>Inactive: {html.escape(', '.join(q.question_id for q in judgment.inactive_questions))}</p>"
            f"<p>Limitations: {html.escape(', '.join(judgment.limitations))}; actor: {html.escape(judgment.actor)}; time: {judgment.observed_at.isoformat()}</p></details>"
        )
    audit = {
        "batch": snapshot.approved_batch_hash,
        "snapshot": snapshot.snapshot_hash,
        "packs": [pack.model_dump(mode="json") for pack in snapshot.pack_identities],
        "sources": [source.model_dump(mode="json") for source in snapshot.sources],
        "result_spec": snapshot.result_spec.model_dump(mode="json"),
    }
    body = (
        "<!doctype html><meta charset=utf-8><title>RoB 2 assessment</title>"
        "<style>@media print{details{display:block}}body{font:16px sans-serif;max-width:960px;margin:auto}img{max-width:100%}details{margin:1em 0}</style>"
        f"<h1>{html.escape(snapshot.trial.label)}</h1><p>Overall proposed: {html.escape(snapshot.proposed_overall.judgment)}; final: {html.escape(snapshot.final_judgment)}</p>"
        f"<p>Override: {html.escape(snapshot.override.justification if snapshot.override else '')}; limitations: {html.escape(', '.join(snapshot.limitations))}; actor: {html.escape(snapshot.actor)}; time: {snapshot.observed_at.isoformat()}</p>"
        + "".join(domains)
        + f"<h2>Canonical audit</h2><pre>{html.escape(str(audit))}</pre>"
    )
    return body.encode()


def export_trial(workspace: str | Path, trial_id: str, result_id: str) -> Path:
    """Materialize a standalone bundle from the committed canonical snapshot bytes only."""
    root = Path(workspace).resolve(strict=True)
    data = _snapshot_bytes(root, trial_id, result_id)
    snapshot = _verified(AssessmentSnapshot.model_validate_json(data))
    parent = root / ".rob2-kit" / "assessments"
    parent.mkdir(parents=True, exist_ok=True)
    backup = _safe_child(parent, f".{trial_id}-backup")
    target = _safe_child(parent, trial_id)
    _recover(parent, target, backup, data, snapshot)
    stage = Path(tempfile.mkdtemp(prefix=f".{trial_id}-stage-", dir=parent))
    try:
        (stage / "assessment.json").write_bytes(data)
        source_dir = stage / "sources"
        source_dir.mkdir()
        for source in snapshot.sources:
            source_data = _source_bytes(root, source)
            if sha256_bytes(source_data) != source.sha256:
                raise ValueError("source copy does not match committed source hash")
            (source_dir / f"{source.id}{Path(source.captured_path).suffix}").write_bytes(
                source_data
            )
        (stage / "report.html").write_bytes(_report(root, snapshot, stage))
        if target.exists():
            if backup.exists():
                raise ValueError("assessment backup already exists")
            target.replace(backup)
        try:
            stage.replace(target)
        except BaseException:
            if backup.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return target
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
