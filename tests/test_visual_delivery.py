from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from support.rob2 import (
    _call,
    _domain_draft,
    _finalize_assessment,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
    _workspace,
)

from rob2_kit.application.finalization import verify_bundle
from rob2_kit.interfaces.mcp import server
from rob2_kit.packs import SCIENTIFIC_PACK


def _draw_flow_diagram(path: Path, *, prose: str | None = None) -> None:
    document = pymupdf.open()
    page = document.new_page()
    if prose:
        page.insert_text((48, 48), prose)
    page.draw_rect(pymupdf.Rect(70, 130, 190, 180), color=(0, 0, 0), width=1)
    page.draw_line((190, 155), (270, 155), color=(0, 0, 0), width=1)
    page.draw_line((260, 145), (270, 155), color=(0, 0, 0), width=1)
    page.draw_line((260, 165), (270, 155), color=(0, 0, 0), width=1)
    page.draw_rect(pymupdf.Rect(270, 115, 390, 155), color=(0, 0, 0), width=1)
    page.draw_rect(pymupdf.Rect(270, 165, 390, 205), color=(0, 0, 0), width=1)
    document.save(path)
    document.close()


def _prepare(workspace: Path) -> dict[str, dict[str, object]]:
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    return {
        source["label"]: source
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    }


def test_image_only_vector_page_needs_a_returned_image_before_selection(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _draw_flow_diagram(workspace / "input" / "trial" / "methods.pdf")
    source = _prepare(workspace)["methods.pdf"]

    pages = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )["data"]["pages"]
    assert pages[0]["numbered_text"] == ""

    rendered = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    assert len(rendered["_image_content"]) == 1
    receipt = rendered["data"]["delivery_receipt"]
    selected = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "delivery_receipt": receipt,
            "transcription": "A flow diagram has one starting box and two allocation branches.",
            "region": [0.0, 0.0, 1.0, 1.0],
        },
    )["data"]["evidence"]
    assert selected["provenance"] == "host_visual"
    assert selected["delivery_receipt"] == receipt


def test_narrative_and_vector_figure_remain_separate_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _draw_flow_diagram(
        workspace / "input" / "trial" / "main.pdf",
        prose="The report says participants were individually randomized.",
    )
    sources = _prepare(workspace)
    source = sources["main.pdf"]
    page = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )["data"]["pages"][0]
    assert "individually randomized" in page["numbered_text"]

    passage = _call(
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
    rendered = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    visual = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "delivery_receipt": rendered["data"]["delivery_receipt"],
            "transcription": "A vector diagram branches one cohort into two allocation boxes.",
            "region": [0.0, 0.2, 1.0, 1.0],
        },
    )["data"]["evidence"]

    status = _call(workspace, "get_status", {})["data"]["selected_evidence"]
    by_handle = {item["handle"]: item for item in status}
    assert by_handle[passage["handle"]]["quote"] == passage["quote"]
    assert by_handle[visual["handle"]]["transcription"] == visual["transcription"]
    assert by_handle[visual["handle"]]["provenance"] == "host_visual"
    assert by_handle[visual["handle"]]["delivery_receipt"] == rendered["data"]["delivery_receipt"]
    assert passage["identity"] != visual["identity"]


def test_delivery_failure_returns_no_image_block_or_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _draw_flow_diagram(workspace / "input" / "trial" / "methods.pdf")
    source = _prepare(workspace)["methods.pdf"]

    def fail_delivery(*_args: object, **_kwargs: object) -> str:
        raise ValueError("ImageContent delivery failed")

    monkeypatch.setattr(server, "_record_visual_delivery", fail_delivery)
    failed = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    assert failed["outcome"] == "condition"
    assert "ImageContent delivery failed" in failed["condition"]["detail"]
    assert failed["_image_content"] == []
    assert failed.get("data", {}).get("delivery_receipt") is None


def test_visual_delivery_receipt_survives_approved_result_and_bundle_verification(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    visual_definition = (
        "The diagram defines the requested outcome as all-cause mortality by day 30."
    )
    _draw_flow_diagram(
        workspace / "input" / "trial" / "figure.pdf",
        prose=(
            "The requested outcome was measured in the analyzed population. "
            f"{visual_definition} death ascertainment; end of follow-up; "
            "assigned to intervention; assigned to control; randomized population; risk ratio; "
            "risk; 1; events; 2."
        ),
    )
    sources = _prepare(workspace)
    text_source = sources["main.txt"]
    figure_source = sources["figure.pdf"]
    passage = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": text_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    rendered = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": figure_source["id"], "page": 1},
    )
    assert len(rendered["_image_content"]) == 1
    selected = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": figure_source["id"],
            "delivery_receipt": rendered["data"]["delivery_receipt"],
            "transcription": (
                "The requested outcome was measured in the analyzed population. death "
                f"{visual_definition} death ascertainment; end of follow-up; "
                "assigned to intervention; assigned to control; randomized population; "
                "risk ratio; risk; 1; events; 2."
            ),
            "region": [0.0, 0.2, 1.0, 1.0],
        },
    )["data"]["evidence"]
    assert selected["provenance"] == "host_visual"

    result = _result(passage)
    result["reported"]["endpoint"]["definition"] = visual_definition
    result["evidence"] = [
        {"kind": "narrative", "handle": passage["handle"]},
        {"kind": "figure", "handle": selected["handle"]},
    ]
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        receipt = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, passage),
        )
        assert receipt["outcome"] == "success", receipt
        revision = int(receipt["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    standalone = _standalone_verify(artifact)
    assert standalone.returncode == 0, standalone.stderr

    with zipfile.ZipFile(artifact) as opened:
        canonical = json.loads(opened.read("canonical.json"))
    selected_record = next(
        item
        for item in canonical["proposal"]["evidence"].values()
        if item["handle"] == selected["handle"]
    )
    result_records = canonical["proposal"]["payload"]["results"][0]["evidence"]
    result_record = next(item for item in result_records if item["kind"] == "figure")
    assert selected_record["delivery_receipt"] == rendered["data"]["delivery_receipt"]
    assert result_record["delivery_receipt"] == selected_record["delivery_receipt"]
