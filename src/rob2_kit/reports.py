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

from rob2_kit.batch_summary import BatchSummary, verified_summary
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


def _batch_bundle_complete(root: Path, path: Path, data: bytes, summary: BatchSummary) -> bool:
    """Accept only the exact self-contained tree derivable from committed records."""
    try:
        if (
            path.is_symlink()
            or not path.is_dir()
            or (path / "batch-summary.json").read_bytes() != data
        ):
            return False
        expected = {Path("batch-summary.json"), Path("index.html")}
        assessed = [entry for entry in summary.entries if entry.status == "assessed"]
        if assessed:
            expected.add(Path("trials"))
        index = (path / "index.html").read_text(encoding="utf-8")
        for entry in assessed:
            trial_dir = Path("trials") / entry.trial.id
            snapshot_data = _snapshot_bytes(root, entry.trial.id, entry.result_spec.id)
            snapshot = _verified(AssessmentSnapshot.model_validate_json(snapshot_data))
            if snapshot.snapshot_hash != entry.snapshot_hash:
                return False
            expected.update(
                {
                    trial_dir,
                    trial_dir / "assessment.json",
                    trial_dir / "report.html",
                    trial_dir / "sources",
                    trial_dir / "assets",
                }
            )
            if (path / trial_dir / "assessment.json").read_bytes() != snapshot_data:
                return False
            if f'href="trials/{entry.trial.id}/report.html"' not in index:
                return False
            for source in snapshot.sources:
                relative = trial_dir / "sources" / f"{source.id}{Path(source.captured_path).suffix}"
                if sha256_bytes((path / relative).read_bytes()) != source.sha256:
                    return False
                expected.add(relative)
            for judgment in snapshot.domain_judgments:
                for answer in judgment.active_answers:
                    for use in answer.evidence_uses:
                        for ref in use.refs:
                            if ref.kind == "visual":
                                relative = (
                                    trial_dir
                                    / "assets"
                                    / f"{ref.image_sha256.removeprefix('sha256:')}.png"
                                )
                                if sha256_bytes((path / relative).read_bytes()) != ref.image_sha256:
                                    return False
                                expected.add(relative)
        actual = {item.relative_to(path) for item in path.rglob("*")}
        return actual == expected and not any(item.is_symlink() for item in path.rglob("*"))
    except (OSError, ValueError):
        return False


def export_batch(workspace: str | Path, approved_batch_hash: str) -> Path:
    """Materialize the committed BatchSummary and its assessed Trial bundles."""
    root = Path(workspace).resolve(strict=True)
    with transaction(root) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (f"batch_summary:{approved_batch_hash}",)
        ).fetchone()
    if row is None:
        raise ValueError("batch summary is not committed")
    data = row[0] if isinstance(row[0], bytes) else str(row[0]).encode()
    summary = verified_summary(BatchSummary.model_validate_json(data))
    parent = root / ".rob2-kit" / "batches"
    parent.mkdir(parents=True, exist_ok=True)
    name = approved_batch_hash.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", name):
        raise ValueError("invalid approved batch hash")
    target = _safe_child(parent, name)
    backup = _safe_child(parent, f".{name}-backup")
    # A prior interrupted publish is recoverable only when its committed summary is exact.
    for residue in parent.glob(f".{name}-stage-*"):
        if (
            re.fullmatch(rf"\.{re.escape(name)}-stage-[a-z0-9_]+", residue.name) is None
            or residue.is_symlink()
            or not residue.is_dir()
        ):
            raise ValueError("ambiguous batch staging residue")
        shutil.rmtree(residue)

    def complete(path: Path) -> bool:
        return _batch_bundle_complete(root, path, data, summary)

    if target.exists() and backup.exists():
        if complete(target):
            shutil.rmtree(backup)
        else:
            # Never destroy a named publication to prefer a backup: an operator
            # must inspect a corrupt target before it can be replaced.
            raise ValueError("batch publication residue cannot be verified")
    elif backup.exists() and not target.exists():
        if not complete(backup):
            raise ValueError("batch backup cannot be verified")
        backup.replace(target)
    elif target.exists() and not complete(target):
        raise ValueError("batch target cannot be verified")
    stage = Path(tempfile.mkdtemp(prefix=f".{name}-stage-", dir=parent))
    try:
        (stage / "batch-summary.json").write_bytes(data)
        links = []
        for entry in summary.entries:
            if entry.status == "assessed":
                trial_id = entry.trial.id
                snapshot_data = _snapshot_bytes(root, trial_id, entry.result_spec.id)
                snapshot = _verified(AssessmentSnapshot.model_validate_json(snapshot_data))
                if snapshot.snapshot_hash != entry.snapshot_hash:
                    raise ValueError("summary assessment entry does not match committed snapshot")
                destination = (
                    _safe_child(stage / "trials", trial_id)
                    if (stage / "trials").exists()
                    else stage / "trials" / trial_id
                )
                destination.parent.mkdir(exist_ok=True)
                destination.mkdir()
                (destination / "assessment.json").write_bytes(snapshot_data)
                sources = destination / "sources"
                sources.mkdir()
                for source in snapshot.sources:
                    source_data = _source_bytes(root, source)
                    if sha256_bytes(source_data) != source.sha256:
                        raise ValueError("source copy does not match committed source hash")
                    (sources / f"{source.id}{Path(source.captured_path).suffix}").write_bytes(
                        source_data
                    )
                (destination / "report.html").write_bytes(_report(root, snapshot, destination))
                links.append(
                    f'<li>{html.escape(trial_id)}: <a href="trials/{html.escape(trial_id)}/report.html">'
                    f"assessed</a>; result {html.escape(entry.result_spec.id)}; "
                    f"judgments {html.escape(', '.join(entry.judgments))}; "
                    f"limitations {html.escape(', '.join(entry.limitations))}; "
                    f"snapshot {html.escape(entry.snapshot_hash)}</li>"
                )
            else:
                links.append(
                    f"<li>{html.escape(entry.trial.id)}: {html.escape(entry.status)} — "
                    f"{html.escape(str([problem.model_dump(mode='json') for problem in entry.problems]))}</li>"
                )
        page = (
            "<!doctype html><meta charset=utf-8><title>RoB 2 batch</title>"
            + f"<h1>{html.escape(summary.outcome_target.label)}</h1>"
            + f"<p>{html.escape(summary.outcome_target.description)}</p>"
            + f"<p>{html.escape(str(summary.counts.model_dump()))}</p><ul>{''.join(links)}</ul>"
            + "<h2>Canonical provenance</h2><pre>"
            + html.escape(
                str(
                    {
                        "approved_batch_hash": summary.approved_batch_hash,
                        "summary_hash": summary.summary_hash,
                        "pack_identities": [
                            item.model_dump(mode="json") for item in summary.pack_identities
                        ],
                    }
                )
            )
            + "</pre>"
        )
        (stage / "index.html").write_text(page, encoding="utf-8")
        if target.exists():
            if backup.exists():
                raise ValueError("batch backup already exists")
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
