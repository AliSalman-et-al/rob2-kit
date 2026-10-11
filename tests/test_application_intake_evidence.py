from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from rob2_kit.application._state import _db, _reserved_role
from rob2_kit.application.evidence import (
    _evidence_for_handles,
    read_pages,
    search_sources,
    select_text_evidence,
)
from rob2_kit.application.intake import prepare_batch
from rob2_kit.application.status import get_status
from rob2_kit.workflow_models import TrialDeclaration


def _source_for_text(tmp_path: Path, text: str) -> tuple[Path, dict[str, object]]:
    (tmp_path / "input" / "trial").mkdir(parents=True)
    (tmp_path / "input" / "trial" / "main.txt").write_bytes(text.encode("utf-8"))
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]
    return tmp_path, source


def test_prepare_exposes_supported_and_unsupported_file_dispositions(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured main report", encoding="utf-8")
    (trial / "declared-protocol.docx").write_bytes(b"not a supported projection")
    (trial / "undeclared.bin").write_bytes(b"not a supported projection")
    (trial / "omitted.docx").write_bytes(b"must not be read")
    (trial / "sources.toml.bak").write_bytes(b"backup config")
    (trial / "sources.toml.backup").write_bytes(b"backup config")
    (trial / "sources.toml.orig").write_bytes(b"backup config")
    (trial / "sources.toml~").write_bytes(b"backup config")
    (trial / ".hidden.bin").write_bytes(b"hidden")
    (trial / "sources.toml").write_text(
        'omissions = ["omitted.docx", "missing.docx"]\n'
        "[roles]\n"
        '"main.txt" = "main_article"\n'
        '"declared-protocol.docx" = "protocol"\n'
        '"omitted.docx" = "supplement"\n'
        '"missing.docx" = "protocol"\n',
        encoding="utf-8",
    )

    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )
    captured = prepared["trials"][0]
    [source] = captured["sources"]
    assert source["logical_path"] == "main.txt"
    assert source["role"] == "main_article"
    assert source["declared_role"] == "main_article"
    assert source["sha256"].startswith("sha256:")

    [omitted, missing] = captured["omissions"]
    assert omitted == {
        "path": "omitted.docx",
        "reason": "other",
        "rationale": "omitted by sources.toml",
        "role": "supplement",
        "declared_role": "supplement",
        "sha256": None,
    }
    assert missing["path"] == "missing.docx"
    assert missing["role"] == "protocol"
    assert missing["declared_role"] == "protocol"

    conditions = prepared["conditions"]
    by_path = {item["path"]: item for item in conditions if "path" in item}
    assert by_path["declared-protocol.docx"]["code"] == "unreadable_source"
    assert by_path["declared-protocol.docx"]["role"] == "protocol"
    assert by_path["declared-protocol.docx"]["declared_role"] == "protocol"
    assert by_path["undeclared.bin"]["code"] == "unsupported_source"
    assert by_path["undeclared.bin"]["role"] == "other"
    assert by_path["undeclared.bin"]["declared_role"] is None
    assert by_path["missing.docx"]["code"] == "declared_source_missing"
    assert by_path["missing.docx"]["sha256"] is None
    assert not any(path.startswith("sources.toml.") or path == "sources.toml~" for path in by_path)
    assert "omitted.docx" not in by_path

    status = get_status(tmp_path)
    assert status["phase"] == "proposal"
    assert status["conditions"] == conditions
    assert (
        "Inspect intake conditions before concluding that evidence is unavailable. Search covers "
        "captured text projections only. Supplied files listed as unsupported, unreadable, or "
        "missing were not searched. A declared role does not establish document contents."
        in status["authoritative_wording"]
    )


def test_prepare_separates_read_and_projection_failures_without_global_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured main report", encoding="utf-8")
    (trial / "corrupt.txt").write_bytes(b"\xff")
    (trial / "blocked.txt").write_text("unreadable", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path.name == "blocked.txt":
            raise PermissionError("test read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )

    assert prepared["trials"][0]["sources"][0]["logical_path"] == "main.txt"
    conditions = {item["path"]: item for item in prepared["conditions"] if "path" in item}
    assert conditions["blocked.txt"]["code"] == "unreadable_source"
    assert conditions["blocked.txt"]["reason"] == "file read failed: PermissionError"
    assert conditions["blocked.txt"]["sha256"] is None
    assert conditions["corrupt.txt"]["code"] == "unreadable_source"
    assert conditions["corrupt.txt"]["reason"].startswith("projection extraction failed:")
    assert conditions["corrupt.txt"]["sha256"].startswith("sha256:")
    assert prepared["phase"] == "proposal"


def test_search_preview_coordinates_and_passage_reference_share_one_window(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(
        tmp_path,
        "analysis appears alone\nfiller\nprospective analysis plan finalized\ntrailer\n",
    )

    result = search_sources(
        workspace,
        "trial",
        "prospective analysis plan",
        mode="all",
    )

    hit = result["hits"][0]
    [passage] = _evidence_for_handles(workspace, {hit["passage_ref"]}, "trial").values()
    assert (hit["start_line"], hit["end_line"]) == (1, 4)
    assert "prospective analysis plan" in hit["preview"]
    assert passage["source_id"] == source["id"]
    assert passage["page"] == hit["page"]
    assert passage["quote"] == hit["preview"]


def test_prepare_batch_does_not_follow_symlinked_source_files(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("not authorized", encoding="utf-8")
    link = trial / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    assert prepared["trials"][0]["sources"] == []


def test_prepare_batch_rejects_symlinked_source_manifest(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text('roles = { "main.txt" = "protocol" }\n', encoding="utf-8")
    manifest = trial / "sources.toml"
    try:
        manifest.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    (trial / "main.txt").write_text("captured source", encoding="utf-8")

    with pytest.raises(ValueError, match="sources.toml is outside the Trial directory"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
            expected_revision=0,
        )


def test_prepare_batch_rejects_symlinked_internal_trial_directory(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    internal_sources = tmp_path / ".rob2-kit" / "sources"
    internal_sources.mkdir(parents=True)
    link = internal_sources / "trial"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="must not be a symlink or junction"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
            expected_revision=0,
        )


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows boundary")
def test_prepare_batch_rejects_junctioned_input_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "Trial").mkdir(parents=True)
    (outside / "Trial" / "main.txt").write_text("not authorized", encoding="utf-8")
    input_root = tmp_path / "input"
    result = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(input_root), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("directory junctions are unavailable on this platform")

    with pytest.raises(ValueError, match="input directory is not available"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="Trial", requested_outcome="outcome")],
            expected_revision=0,
        )


def test_prepare_batch_rejects_two_declarations_for_one_trial_directory(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "Trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate trial directory"):
        prepare_batch(
            tmp_path,
            [
                TrialDeclaration(id="first", label="Trial", requested_outcome="outcome"),
                TrialDeclaration(id="second", label="Trial", requested_outcome="outcome"),
            ],
            expected_revision=0,
        )


def test_disclosure_filename_defaults_to_other_role(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "disclosure.txt").write_text("captured source", encoding="utf-8")
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    assert prepared["trials"][0]["sources"][0]["role"] == "other"
    assert _reserved_role("registry.pdf") == "registry"
    assert _reserved_role("disclosure.pdf") == "other"


def test_preview_uses_token_boundary_not_substring_match(tmp_path: Path) -> None:
    raw = "antitarget " * 80 + "target result" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "target")
    preview = result["hits"][0]["preview"]

    assert "target result" in preview
    assert not preview.startswith("antitarget antitarget")


def test_prefix_preview_scans_past_substring_false_positive(tmp_path: Path) -> None:
    raw = "antitarget " * 80 + "target result" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "target", mode="prefix")
    preview = result["hits"][0]["preview"]

    assert "target result" in preview
    assert not preview.startswith("antitarget antitarget")


def test_read_pages_rejects_mixed_valid_and_invalid_requests_atomically(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(tmp_path, "page one")

    with pytest.raises(ValueError, match="outside Source"):
        read_pages(workspace, "trial", str(source["id"]), [1, 2])


def test_old_page_projection_recipe_is_rejected_without_rewriting_identity(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(tmp_path, "captured text")
    with _db(workspace, "canonical.sqlite3") as connection:
        connection.execute(
            "UPDATE meta SET value='rob2-kit.page-projection.legacy' WHERE name='page_projection'"
        )

    with pytest.raises(ValueError, match="page_projection_recipe_unsupported"):
        read_pages(workspace, "trial", str(source["id"]), [1])

    # The canonical Source identity and bytes remain untouched by the refusal.
    with _db(workspace, "canonical.sqlite3") as connection:
        stored = connection.execute(
            "SELECT value FROM meta WHERE name='page_projection'"
        ).fetchone()
    assert stored[0] == "rob2-kit.page-projection.legacy"


def test_select_text_evidence_rejects_ambiguous_normalized_matches(tmp_path: Path) -> None:
    _, source = _source_for_text(tmp_path, "target value\nother target value")

    with pytest.raises(ValueError, match="ambiguous"):
        select_text_evidence(tmp_path, "trial", str(source["id"]), 1, "target value")


def test_select_text_evidence_rejects_wrong_numeric_or_text_content(tmp_path: Path) -> None:
    _, source = _source_for_text(tmp_path, "Hazard ratio 0.61 was reported.")

    with pytest.raises(ValueError, match="not an exact page selection"):
        select_text_evidence(
            tmp_path,
            "trial",
            str(source["id"]),
            1,
            "Hazard ratio 0.62 was reported.",
        )
