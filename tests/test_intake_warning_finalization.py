from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
import support.rob2 as support
from support.rob2 import _standalone_verify
from test_assessment_review_gate import _complete_assessment
from test_finalization_bundle_integrity import _close_trials

from rob2_kit.application._state import _state
from rob2_kit.application.finalization import finalize_batch, verify_bundle


@pytest.mark.parametrize(
    "condition", ["declared_source_missing", "unsupported_source", "unreadable_source"]
)
def test_intake_warning_is_reconstructed_and_cannot_be_removed(
    tmp_path: Path, monkeypatch, condition: str
):
    original_workspace = support._workspace

    def workspace_with_condition(path, requested_outcome="requested outcome"):
        workspace = original_workspace(path, requested_outcome)
        trial = workspace / "input/trial"
        if condition == "declared_source_missing":
            (trial / "sources.toml").write_text(
                'roles = { "main.txt" = "main_article", "missing.txt" = "other" }\n'
            )
        elif condition == "unsupported_source":
            (trial / "supplement.doc").write_bytes(b"Unsupported source format")
        else:
            (trial / "empty.txt").write_bytes(b"")
        return workspace

    monkeypatch.setattr(support, "_workspace", workspace_with_condition)
    workspace, _evidence, revision = _complete_assessment(tmp_path)
    assert condition in {c["code"] for c in _state(workspace)["batch"]["conditions"]}
    revision = _close_trials(workspace, revision)
    receipt = finalize_batch(workspace, revision)
    artifact = workspace / receipt["artifact"]["path"]
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0
    with zipfile.ZipFile(artifact) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    claims = json.loads(files["claims.json"])
    assert "Inspect intake conditions" in claims["authoritative_wording"]
    claims["authoritative_wording"] = claims["authoritative_wording"].split(
        " Inspect intake conditions"
    )[0]
    files["claims.json"] = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    files["report.html"] = (
        "<html><body><h1>Batch finalized</h1><pre>"
        + json.dumps(claims, sort_keys=True)
        + "</pre></body></html>"
    ).encode()
    manifest = json.loads(files["manifest.json"])
    for entry in manifest["files"]:
        entry["sha256"] = "sha256:" + hashlib.sha256(files[entry["path"]]).hexdigest()
    files["manifest.json"] = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    tampered = tmp_path / "warning-removed.rob2.zip"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    assert not verify_bundle(tampered)
    assert _standalone_verify(tampered).returncode == 1
