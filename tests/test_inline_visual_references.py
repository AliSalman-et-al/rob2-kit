"""Delivered image references retain provenance without certifying interpretation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastmcp.exceptions import ToolError
from support import rob2 as support

from rob2_kit.application._state import _canonical_evidence_records, _identity, _state
from rob2_kit.application.domains import _approved_result

TRANSCRIPTIONS = (
    "Allocation table. Alpha 20, Beta 30, Gamma 40 participants. Total 90. "
    "Footnote: allocated participants, not observed outcomes.",
    "Allocation flow: randomized 90 branches to Alpha 20, Beta 30 and Gamma 40. "
    "Arrows indicate allocation, not outcome ascertainment.",
    "Mean score plot: horizontal axis day 0 to day 30; vertical axis score 0 to 6. "
    "Alpha rises, Beta falls, Gamma rises. Exact final marker values are not labeled.",
)


def _neutral_graphics(path: Path) -> None:
    """Raster cells/branches/markers intentionally have only caption text extraction."""
    visible = pymupdf.open()
    table = visible.new_page()
    table.insert_text((48, 70), "Allocation table")
    for i, (arm, count) in enumerate([("Alpha", 20), ("Beta", 30), ("Gamma", 40)]):
        x = 48 + i * 145
        table.draw_rect(pymupdf.Rect(x, 100, x + 125, 160))
        table.insert_text((x + 10, 120), arm)
        table.insert_text((x + 10, 145), str(count))
    table.insert_text((48, 190), "Total 90; allocated participants, not observed outcomes.")
    flow = visible.new_page()
    flow.insert_text((220, 80), "Randomized 90")
    for i, (arm, count) in enumerate([("Alpha", 20), ("Beta", 30), ("Gamma", 40)]):
        x = 48 + i * 145
        flow.draw_line((260, 90), (x + 60, 170))
        flow.draw_rect(pymupdf.Rect(x, 170, x + 125, 220))
        flow.insert_text((x + 10, 195), f"{arm} {count}")
    flow.insert_text((48, 250), "Arrows indicate allocation, not outcome ascertainment.")
    plot = visible.new_page()
    plot.insert_text((48, 70), "Mean score plot")
    plot.draw_line((100, 300), (420, 300))
    plot.draw_line((100, 300), (100, 100))
    plot.insert_text((100, 320), "day 0")
    plot.insert_text((390, 320), "day 30")
    for score in [0, 2, 4, 6]:
        plot.insert_text((72, 300 - score * 30), str(score))
    for i, (arm, start, end) in enumerate([("Alpha", 2, 4), ("Beta", 3, 2), ("Gamma", 4, 5)]):
        color = [(1, 0, 0), (0, 0.5, 0), (0, 0, 1)][i]
        plot.draw_line((100, 300 - start * 30), (400, 300 - end * 30), color=color)
        plot.draw_circle((400, 300 - end * 30), 4, color=color)
        plot.insert_text((440, 130 + i * 25), arm, color=color)
    plot.insert_text((48, 350), "Score 0 to 6; exact final marker values are not labeled.")
    document = pymupdf.open()
    for i in range(len(visible)):
        page = visible[i]
        target = document.new_page()
        target.insert_image(target.rect, stream=page.get_pixmap().tobytes("png"))
        target.insert_text((48, 30), f"Figure {i + 1}: neutral appendix graphic; caption only.")
    document.save(path)
    document.close()
    visible.close()


def _prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any], int, dict[str, Any]]:
    original = support._workspace

    def create(path: Path, requested_outcome: str = "requested outcome") -> Path:
        workspace = original(path, requested_outcome)
        _neutral_graphics(workspace / "input/trial/figures.pdf")
        return workspace

    monkeypatch.setattr(support, "_workspace", create)
    workspace, evidence, revision = support._assessment_workspace(tmp_path)
    source = next(
        item
        for item in support._call(workspace, "list_sources", {"trial_id": "trial"})["data"][
            "sources"
        ]
        if item["label"] == "figures.pdf"
    )
    return workspace, evidence, revision, source


def _reference(workspace: Path, source: dict[str, Any], page: int) -> dict[str, Any]:
    rendered = support._call(
        workspace, "render_page", {"trial_id": "trial", "source_id": source["id"], "page": page}
    )
    assert len(rendered["_image_content"]) == 1
    return {
        "delivery_receipt": rendered["data"]["delivery_receipt"],
        "region": [0.0, 0.0, 1.0, 1.0],
        "transcription": TRANSCRIPTIONS[page - 1],
        "uncertainty": (
            "Exact final marker values are unknown from the graphic."
            if page == 3
            else "The graphic does not establish observed-outcome counts or analysis timing."
        ),
    }


@pytest.mark.parametrize("page", [1, 2, 3], ids=["multiarm-table", "allocation-flow", "score-plot"])
def test_inline_visual_preserves_same_evidence_result_unknowns_and_counterclaim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: int
) -> None:
    workspace, text, revision, source = _prepared(tmp_path, monkeypatch)
    ref = _reference(workspace, source, page)
    support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:selection"}
    )
    draft = support._domain_draft("trial", "domain:selection", revision, text)
    answer = draft["answers"][0]
    answer["bases"].append(ref if page == 1 else {"evidence": ref, "role": "context"})
    answer["unknowns"] = ["The graphic does not establish analysis timing."]
    answer["counterevidence"] = [
        {"evidence": [ref], "implication": "These graphical values do not date an analysis plan."}
    ]
    before = _state(workspace)
    saved = support._call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    record = _state(workspace)["domain_records"]["trial:domain:selection"]
    assert record["result_identity"] == _identity(_approved_result(before, "trial"))
    assert [item["answer"] for item in record["answers"]] == [
        item["answer"] for item in draft["answers"]
    ]
    ids = {basis["evidence"] for item in record["answers"] for basis in item["bases"]}
    catalog = _canonical_evidence_records(workspace, ids)
    visual = next(item for item in catalog.values() if item["kind"] == "figure")
    assert visual["transcription"] == ref["transcription"]
    assert visual["uncertainty"] == ref["uncertainty"]
    assert visual["region"] == ref["region"]
    assert visual["delivery_receipt"] == ref["delivery_receipt"]
    assert visual["render"]["page"] == page
    assert visual["provenance"] == "host_visual"
    first = record["answers"][0]
    assert first["unknowns"] == answer["unknowns"]
    point = first["counterevidence"][0]
    assert point["implication"] == answer["counterevidence"][0]["implication"]
    assert first["bases"][point["basis_index"]]["evidence"] == visual["identity"]
    legacy = support._call(
        workspace, "select_visual_evidence", {"trial_id": "trial", "source_id": source["id"], **ref}
    )
    assert legacy["data"]["evidence"]["identity"] == visual["identity"]


def test_text_caption_remains_narrative_without_graphical_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, evidence, revision, source = _prepared(tmp_path, monkeypatch)
    support._call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:selection"}
    )
    draft = support._domain_draft("trial", "domain:selection", revision, evidence)
    draft["answers"][0]["bases"].append(
        {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1}
    )
    saved = support._call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    record = _state(workspace)["domain_records"]["trial:domain:selection"]
    ids = {basis["evidence"] for item in record["answers"] for basis in item["bases"]}
    catalog = _canonical_evidence_records(workspace, ids)
    assert all(item["kind"] == "narrative" for item in catalog.values())
    caption = next(item for item in catalog.values() if "caption only" in item["quote"])
    assert caption["quote"] == "Figure 1: neutral appendix graphic; caption only."
    assert "transcription" not in caption and "render" not in caption


@pytest.mark.parametrize(
    "defect",
    [
        "text-receipt",
        "stale-receipt",
        "wrong-trial",
        "wrong-source",
        "hash",
        "region",
        "metadata-only",
    ],
)
def test_inline_visual_rejects_invalid_provenance_without_canonical_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    workspace, text, revision, source = _prepared(tmp_path, monkeypatch)
    ref = _reference(workspace, source, 1)
    if defect == "text-receipt":
        ref["delivery_receipt"] = text["handle"]
    elif defect == "stale-receipt":
        ref["delivery_receipt"] = "sha256:" + "0" * 64
    elif defect == "region":
        ref["region"] = [0.9, 0.0, 0.1, 1.0]
    elif defect == "metadata-only":
        metadata = support._call(
            workspace,
            "render_page",
            {"trial_id": "trial", "source_id": source["id"], "page": 2, "inline": False},
        )
        assert not metadata["_image_content"] and metadata["data"]["delivery_receipt"] is None
        ref["delivery_receipt"] = metadata["data"]["render"]["identity"]
    else:
        column, value = {
            "wrong-trial": ("trial_id", "another-trial"),
            "wrong-source": ("source_id", "source_" + "0" * 64),
            "hash": ("png_sha256", "sha256:" + "0" * 64),
        }[defect]
        with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as connection:
            connection.execute(
                f"UPDATE visual_deliveries SET {column}=? WHERE identity=?",
                (value, ref["delivery_receipt"]),
            )
    draft = support._domain_draft("trial", "domain:selection", revision, text)
    draft["answers"][0]["bases"] = [ref]
    try:
        result = support._call(workspace, "save_domain_judgment", draft)
        assert result["outcome"] in {"condition", "repair"}, result
    except ToolError:
        pass
    assert not _state(workspace).get("domain_records")
    assert _state(workspace)["revision"] == revision
