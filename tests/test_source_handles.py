from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from support.rob2 import _call, _standalone_verify, _workspace

from rob2_kit.application import source_handles
from rob2_kit.application.finalization import verify_bundle


def test_source_handles_round_trip_across_source_tools_and_recovery(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").unlink()
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "alpha beta\nsecond line")
    (workspace / "input" / "trial" / "main.pdf").write_bytes(document.tobytes())
    document.close()
    prepared = _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "outcome", "expected_revision": 0},
    )
    source_handle = prepared["data"]["trials"][0]["sources"][0]["id"]
    assert source_handle.startswith("sh_") and len(source_handle) == 19
    listed = _call(workspace, "list_sources", {"trial_id": "trial"})
    assert listed["data"]["sources"][0]["id"] == source_handle
    status = _call(workspace, "get_status", {})
    required = [
        window
        for item in status["data"]["main_report_reading"].values()
        for window in item["required_ranges"]
    ]
    assert required and all(window["source_id"] == source_handle for window in required)

    search = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "alpha",
            "mode": "any",
            "source_id": source_handle,
        },
    )
    assert search["data"]["hits"][0]["source_id"] == source_handle
    pages = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source_handle, "pages": [1]},
    )
    assert pages["data"]["pages"][0]["source_id"] == source_handle
    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source_handle,
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )
    assert selected["data"]["evidence"]["source_id"] == source_handle
    rendered = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source_handle, "page": 1, "inline": False},
    )
    assert rendered["data"]["render"]["source_id"] == source_handle
    visual = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": source_handle,
            "render_identity": rendered["data"]["render"]["identity"],
            "transcription": "alpha beta",
            "region": [0.0, 0.0, 1.0, 1.0],
        },
    )
    assert visual["data"]["evidence"]["source_id"] == source_handle


def test_source_handles_reject_unknown_and_wrong_trial(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "first").mkdir()
    (workspace / "input" / "second").mkdir()
    (workspace / "input" / "first" / "main.txt").write_text("text\n", encoding="utf-8")
    (workspace / "input" / "second" / "main.txt").write_text("text\n", encoding="utf-8")
    prepared = _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "outcome", "expected_revision": 0},
    )
    source_handle = prepared["data"]["trials"][0]["sources"][0]["id"]
    unknown = _call(
        workspace,
        "read_pages",
        {"trial_id": "first", "source_id": "sh_" + "f" * 16, "pages": [1]},
    )
    assert unknown["condition"]["code"] == "invalid_request"
    assert "unknown" in unknown["condition"]["detail"]
    wrong_trial = _call(
        workspace,
        "read_pages",
        {"trial_id": "second", "source_id": source_handle, "pages": [1]},
    )
    assert wrong_trial["condition"]["code"] == "invalid_request"
    assert "outside" in wrong_trial["condition"]["detail"]


def test_source_handle_collision_is_scoped_to_trial(monkeypatch, tmp_path: Path) -> None:
    first = "source_" + "a" * 16 + "0" * 48
    second = "source_" + "a" * 16 + "1" * 48
    shared = "source_" + "b" * 64
    batch = {
        "trials": [
            {"id": "first", "sources": [{"id": first}, {"id": second}]},
            {"id": "second", "sources": [{"id": shared}]},
            {"id": "third", "sources": [{"id": shared}]},
        ]
    }
    monkeypatch.setattr(source_handles, "_state", lambda _root: {"batch": batch})
    with pytest.raises(ValueError, match="ambiguous"):
        source_handles.resolve_source_handle(tmp_path, "first", "sh_" + "a" * 16)
    assert source_handles.resolve_source_handle(tmp_path, "second", "sh_" + "b" * 16) == shared
    assert source_handles.resolve_source_handle(tmp_path, "third", "sh_" + "b" * 16) == shared
    with pytest.raises(ValueError, match="outside"):
        source_handles.resolve_source_handle(tmp_path, "first", "sh_" + "b" * 16)
    with pytest.raises(ValueError, match="ambiguous"):
        source_handles.public_source_references(
            {
                "sources": [
                    {"trial_id": "first", "id": first},
                    {"trial_id": "first", "id": second},
                ]
            }
        )
    assert source_handles.public_source_references(
        {
            "sources": [
                {"trial_id": "second", "id": shared},
                {"trial_id": "third", "id": shared},
            ]
        }
    ) == {
        "sources": [
            {"trial_id": "second", "id": "sh_" + "b" * 16},
            {"trial_id": "third", "id": "sh_" + "b" * 16},
        ]
    }


def test_source_handles_do_not_change_canonical_bundle_identity(tmp_path: Path) -> None:
    from test_finalization_bundle_integrity import _artifact

    artifact = _artifact(_workspace(tmp_path))
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    source_ids = [
        source["id"] for trial in canonical["batch"]["trials"] for source in trial["sources"]
    ]
    assert source_ids and all(source_id.startswith("source_") for source_id in source_ids)
