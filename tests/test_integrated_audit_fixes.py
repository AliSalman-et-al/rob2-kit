from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
)

from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import render_page, select_visual_evidence
from rob2_kit.application.source_archive import archive_sources, verify_source_archive
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import FigureEvidence


def test_initial_domain_checkpoint_rejects_revision_metadata(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    draft["supersedes"] = "sha256:" + "a" * 64
    draft["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "This is not an initial checkpoint.",
    }

    rejected = _call(workspace, "save_domain_judgment", draft)

    assert rejected["outcome"] == "condition"
    assert rejected["condition"]["code"] == "domain_initial_checkpoint_cannot_have_revision"


def test_domain_evidence_survives_derivative_rebuild_for_finalization(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    derivative = workspace / ".rob2-kit" / "derivative.sqlite3"
    derivative.unlink()
    finalized = _finalize_assessment(workspace, revision)

    assert finalized["outcome"] == "success"
    assert finalized["data"]["artifact"]["identity"]


def test_domain_save_validates_only_submitted_evidence_handles(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "domain.txt").write_text("The requested outcome was not reported", encoding="utf-8")
    workspace, proposal_evidence, revision = _assessment_workspace(tmp_path)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "domain.txt"
    )
    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    before = COUNTERS["source_projection_verifications"]
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, proposal_evidence)
    draft["answers"][0]["bases"] = [
        {
            "kind": "direct_support",
            "evidence": selected["handle"],
        }
    ]
    saved = _call(workspace, "save_domain_judgment", draft)

    assert saved["outcome"] == "success", saved
    assert COUNTERS["source_projection_verifications"] - before == 1


def test_visual_transcription_rejects_blank_at_model_and_application_boundaries(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    import pymupdf

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "overall survival")
    document.save(trial / "main.pdf")
    document.close()
    from rob2_kit.application.evidence import list_sources
    from rob2_kit.application.intake import prepare_batch
    from rob2_kit.workflow_models import TrialDeclaration

    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )
    source = list_sources(tmp_path, "trial")["sources"][0]
    rendered = render_page(tmp_path, "trial", source["id"], 1)["render"]

    with pytest.raises(ValidationError):
        FigureEvidence.model_validate(
            {
                "kind": "figure",
                "handle": "eh_" + "a" * 16,
                "render_identity": rendered["identity"],
                "region": (0.0, 0.0, 1.0, 1.0),
                "transcription": "   ",
            }
        )
    with pytest.raises(ValueError, match="visual transcription"):
        select_visual_evidence(
            tmp_path,
            "trial",
            source["id"],
            rendered["identity"],
            "   ",
            [0.0, 0.0, 1.0, 1.0],
        )


def test_source_archive_is_deterministic_restart_safe_and_portable(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)

    first = archive_sources(workspace)
    second = archive_sources(workspace)
    archive = workspace / first["path"]

    assert first["retry"] is False
    assert second["retry"] is True
    assert verify_source_archive(archive)
    with zipfile.ZipFile(archive) as opened:
        manifest = json.loads(opened.read("manifest.json"))
        assert all("requested_outcome" not in item for item in manifest["sources"])
        assert all("trace" not in item for item in manifest["sources"])
        assert all("\\" not in name for name in opened.namelist())
        assert all(not Path(name).is_absolute() for name in opened.namelist())

    cli_archive = tmp_path / "portable.sources.zip"
    command = [
        sys.executable,
        "-m",
        "rob2_kit.interfaces.cli.app",
        "archive-sources",
        "--workspace",
        str(workspace),
        "--output",
        str(cli_archive),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "rob2_kit.interfaces.cli.app",
            "verify-sources",
            str(cli_archive),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "verified:" in verified.stdout


def test_source_archive_rejects_linked_default_archive_directory(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    outside = tmp_path / "outside-archives"
    outside.mkdir()
    archive_directory = workspace / ".rob2-kit" / "source-archives"
    try:
        archive_directory.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="must not be a symlink or junction"):
        archive_sources(workspace)


def test_source_archive_rejects_noncanonical_metadata_and_paths(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    archive = workspace / archive_sources(workspace)["path"]
    original = archive.read_bytes()

    with zipfile.ZipFile(BytesIO(original)) as opened:
        files = {info.filename: opened.read(info) for info in opened.infolist()}

    metadata_rewritten = tmp_path / "metadata-rewritten.sources.zip"
    with zipfile.ZipFile(metadata_rewritten, "w", compression=zipfile.ZIP_DEFLATED) as opened:
        for name in sorted(files):
            opened.writestr(name, files[name])
    assert not verify_source_archive(metadata_rewritten)

    manifest = json.loads(files["manifest.json"])
    source = manifest["sources"][0]
    old_path = source["archive_path"]
    source["archive_path"] = "sources/arbitrary/renamed.bin"
    manifest["identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {"schema": manifest["schema"], "sources": manifest["sources"]},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    files["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    renamed = tmp_path / "renamed.sources.zip"
    with zipfile.ZipFile(renamed, "w", compression=zipfile.ZIP_DEFLATED) as opened:
        for name in sorted(files):
            opened.writestr(
                source["archive_path"] if name == old_path else name,
                files[name],
            )
    assert not verify_source_archive(renamed)
