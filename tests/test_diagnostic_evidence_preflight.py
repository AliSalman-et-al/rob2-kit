from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.diagnostic_evidence_preflight import check_manifest, launch_checked


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
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
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
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
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
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
        with pytest.raises(ValueError, match="manifest hash mismatch"):
            launch_checked(
                ["paid-launch"],
                manifest_path=manifest,
                input_path=prompt,
                receipt_path=tmp_path / "receipt.json",
                expected_manifest_sha256=frozen_hash,
            )
        child.assert_not_called()


def image_fixture(tmp_path):
    import pymupdf

    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 3), False).tobytes("png")
    input_path = tmp_path / "frame.png"
    input_path.write_bytes(png)
    frame = {
        "source_identity": "captured_source",
        "page": 1,
        "png_sha256": hashlib.sha256(png).hexdigest(),
        "width": 4,
        "height": 3,
    }
    manifest = {
        "research_question": "Can the image frame be inspected?",
        "input_sha256": hashlib.sha256(png).hexdigest(),
        "required_images": [frame],
        "supplied_images": [{**frame, "input_start_byte": 0, "input_end_byte": len(png)}],
    }
    path = tmp_path / "image-manifest.json"
    path.write_text(json.dumps(manifest))
    return path, input_path, manifest


def test_image_only_manifest_uses_actual_frame_without_inventing_text_lines(tmp_path):
    path, input_path, _ = image_fixture(tmp_path)
    receipt = check_manifest(path, input_path)
    assert receipt["passed"] and receipt["required_image_count"] == 1
    assert receipt["required_window_count"] == 0


@pytest.mark.parametrize("change", ["identity", "page", "pixels", "dimensions", "omitted"])
def test_image_identity_pixel_and_geometry_drift_prevents_launch(tmp_path, change):
    path, input_path, data = image_fixture(tmp_path)
    supplied = data["supplied_images"][0]
    if change == "identity":
        supplied["source_identity"] = "different_source"
    elif change == "page":
        supplied["page"] = 2
    elif change == "pixels":
        supplied["png_sha256"] = "0" * 64
    elif change == "dimensions":
        supplied["width"] = 5
    else:
        data["supplied_images"] = []
    path.write_text(json.dumps(data))
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
        with pytest.raises(ValueError):
            launch_checked(
                ["paid-launch"],
                manifest_path=path,
                input_path=input_path,
                receipt_path=tmp_path / "receipt.json",
                expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        child.assert_not_called()


def test_local_reference_is_not_delivered_until_included_in_instructions(tmp_path: Path) -> None:
    from scripts.diagnostic_evidence_preflight import check_instruction_delivery

    skill = tmp_path / "SKILL.md"
    reference = tmp_path / "procedure.md"
    instructions = tmp_path / "instructions.md"
    skill.write_text("Read procedure.md before drafting.\n")
    reference.write_text("Source facts precede independent propositions.\n")
    instructions.write_bytes(skill.read_bytes())
    with pytest.raises(ValueError, match="not delivered: procedure.md"):
        check_instruction_delivery(instructions, (skill, reference))
    instructions.write_bytes(skill.read_bytes() + b"\n" + reference.read_bytes())
    receipt = check_instruction_delivery(instructions, (skill, reference))
    assert receipt["passed"] and len(receipt["required_documents"]) == 2
    reference.write_text("Changed operational instructions.\n")
    with pytest.raises(ValueError, match="not delivered"):
        check_instruction_delivery(instructions, (skill, reference))


def test_separate_native_bundle_keeps_generic_prompt_and_blocks_changed_sources(tmp_path):
    path, prompt, manifest = fixture(tmp_path)
    bundle = tmp_path / "evidence.txt"
    bundle.write_bytes(prompt.read_bytes())
    prompt.write_bytes(b"Assess the result through the normal MCP workflow.")
    manifest["input_sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
    manifest["evidence_bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
        launch_checked(
            ["native-launch"],
            manifest_path=path,
            input_path=prompt,
            evidence_bundle_path=bundle,
            receipt_path=tmp_path / "receipt.json",
            expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        child.assert_called_once_with(["native-launch"])
    assert prompt.read_bytes() == b"Assess the result through the normal MCP workflow."
    with pytest.raises(ValueError, match="requires both"):
        check_manifest(path, prompt)
    bundle.write_bytes(b"Changed source")
    with patch("scripts.diagnostic_evidence_preflight.subprocess.Popen") as child:
        with pytest.raises(ValueError, match="evidence bundle hash mismatch"):
            launch_checked(
                ["native-launch"],
                manifest_path=path,
                input_path=prompt,
                evidence_bundle_path=bundle,
                receipt_path=tmp_path / "changed-receipt.json",
                expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        child.assert_not_called()
    assert not (tmp_path / "changed-receipt.json").exists()
