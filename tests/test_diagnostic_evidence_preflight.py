from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from diagnostic_evidence_preflight import check_manifest, launch_checked


def fixture(tmp_path: Path, supplied_page: int = 188):
    prompt = b"Source passage only; no desired answer."
    input_path = tmp_path / "input.txt"
    input_path.write_bytes(prompt)
    window = {"source_identity": "source_identity", "page": 188, "start_line": 20, "end_line": 40}
    manifest = {
        "research_question": "Does the reviewer distinguish planned analysis from results?",
        "input_sha256": hashlib.sha256(prompt).hexdigest(),
        "required_windows": [window],
        "supplied_windows": [
            {
                **window,
                "page": supplied_page,
                "input_start_byte": 0,
                "input_end_byte": len(prompt),
                "text_sha256": hashlib.sha256(prompt).hexdigest(),
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, input_path, manifest


def test_required_uncited_source_omission_prevents_any_launch(tmp_path):
    manifest, prompt, _ = fixture(tmp_path, supplied_page=192)
    with patch("diagnostic_evidence_preflight.subprocess.Popen") as child:
        with pytest.raises(ValueError, match="evidence omitted"):
            launch_checked(
                ["paid-launch"],
                manifest_path=manifest,
                input_path=prompt,
                receipt_path=tmp_path / "receipt.json",
                expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )
        child.assert_not_called()
    assert not (tmp_path / "receipt.json").exists()


def test_frozen_manifest_passes_without_entering_model_input(tmp_path):
    manifest, prompt, _ = fixture(tmp_path)
    before = prompt.read_bytes()
    with patch("diagnostic_evidence_preflight.subprocess.Popen") as child:
        launch_checked(
            ["paid-launch"],
            manifest_path=manifest,
            input_path=prompt,
            receipt_path=tmp_path / "receipt.json",
            expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        )
        child.assert_called_once_with(["paid-launch"])
    assert prompt.read_bytes() == before
    assert json.loads((tmp_path / "receipt.json").read_text())["passed"]


@pytest.mark.parametrize("change", ["input", "passage", "source", "range"])
def test_changed_input_wrong_identity_hash_or_partial_coverage_rejected(tmp_path, change):
    path, prompt, manifest = fixture(tmp_path)
    if change == "input":
        prompt.write_bytes(b"changed")
    elif change == "passage":
        manifest["supplied_windows"][0]["text_sha256"] = "0" * 64
    elif change == "source":
        manifest["supplied_windows"][0]["source_identity"] = "unrelated"
    else:
        manifest["supplied_windows"][0]["end_line"] = 39
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        check_manifest(path, prompt)


def test_contiguous_windows_cover_requirement_but_gap_does_not(tmp_path):
    path, prompt, manifest = fixture(tmp_path)
    first = manifest["supplied_windows"][0]
    first["end_line"] = 29
    manifest["supplied_windows"].append({**first, "start_line": 30, "end_line": 40})
    path.write_text(json.dumps(manifest))
    assert check_manifest(path, prompt)["passed"]
    manifest["supplied_windows"][1]["start_line"] = 31
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="evidence omitted"):
        check_manifest(path, prompt)


def test_actual_confounded_exscel_input_is_rejected_without_launch():
    root = Path(__file__).parents[1] / "docs/evaluation/2026-10-03-exscel-review-response-d789ea8"
    with pytest.raises(ValueError, match="page 188 lines 20-40"):
        check_manifest(root / "retrospective-required-evidence-manifest.json", root / "input.txt")


def test_changed_preregistered_manifest_prevents_launch(tmp_path):
    manifest, prompt, data = fixture(tmp_path)
    frozen_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    data["research_question"] = "Changed research question"
    manifest.write_text(json.dumps(data))
    with patch("diagnostic_evidence_preflight.subprocess.Popen") as child:
        with pytest.raises(ValueError, match="manifest hash mismatch"):
            launch_checked(
                ["paid-launch"],
                manifest_path=manifest,
                input_path=prompt,
                receipt_path=tmp_path / "receipt.json",
                expected_manifest_sha256=frozen_hash,
            )
        child.assert_not_called()
