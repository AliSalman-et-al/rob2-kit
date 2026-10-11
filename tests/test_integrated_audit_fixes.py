from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
)

from rob2_kit.application.evidence import (
    record_visual_delivery,
    render_page,
    select_visual_evidence,
)
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
    rendered = render_page(tmp_path, "trial", source["id"], 1)
    receipt = record_visual_delivery(
        tmp_path,
        "trial",
        source["id"],
        rendered["render"]["identity"],
        rendered["_png_bytes"],
    )

    with pytest.raises(ValidationError):
        FigureEvidence.model_validate(
            {
                "kind": "figure",
                "handle": "eh_" + "a" * 16,
                "render_identity": rendered["render"]["identity"],
                "delivery_receipt": receipt,
                "region": (0.0, 0.0, 1.0, 1.0),
                "transcription": "   ",
            }
        )
    with pytest.raises(ValueError, match="visual transcription"):
        select_visual_evidence(
            tmp_path,
            "trial",
            source["id"],
            receipt,
            "   ",
            [0.0, 0.0, 1.0, 1.0],
        )


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
