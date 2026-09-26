from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from support.rob2 import _call

import rob2_kit.application._state as source_state
from rob2_kit.application._state import (
    _db,
    _normalize_projected_text,
    _pages,
    _projection_hash,
    _semantic_table_page,
    _table_gfm,
)
from rob2_kit.application.evidence import (
    list_sources,
    read_pages,
    render_page,
    search_sources,
    select_text_evidence,
)
from rob2_kit.application.intake import prepare_batch
from rob2_kit.application.source_handles import resolve_source_handle
from rob2_kit.projection_verify import reproduce_projection_identity
from rob2_kit.workflow_models import TrialDeclaration


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    narrative = document.new_page()
    narrative.insert_text((50, 50), "Narrative page with no table.")
    table = document.new_page()
    for x in (50, 150, 225, 300):
        table.draw_line((x, 80), (x, 200))
    for y in range(80, 201, 20):
        table.draw_line((50, y), (300, y))
    rows = [
        ("Arm", "Events", "Rate"),
        ("ADT", "12", "3%"),
        ("Docetaxel", "22", "5%"),
        ("ADT+other", "31", "7%"),
        ("Control", "15", "4%"),
        ("Total", "80", "4%"),
    ]
    for row_number, row in enumerate(rows):
        for column, value in enumerate(row):
            table.insert_text((55 + (0, 110, 190)[column], 95 + row_number * 20), value)
    try:
        return document.tobytes()
    finally:
        document.close()


def _prepare_pdf(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(_pdf_bytes())
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="result")],
        expected_revision=0,
    )
    return tmp_path, prepared["trials"][0]["sources"][0]


def test_pdf_projection_keeps_narrative_and_projects_table_axes() -> None:
    pages = _pages(Path("article.pdf"), _pdf_bytes())

    assert len(pages) == 2
    assert pages[0] == "Narrative page with no table.\n"
    assert pages[1].startswith("Arm\nEvents\nRate\nADT\n12\n3%\n")
    assert "[Extracted table 1]" in pages[1]
    assert "|Docetaxel|22|5%|" in pages[1]


def test_optional_table_extraction_failure_keeps_searchable_source_and_render_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(_pdf_bytes())

    table_extraction_attempts = 0

    def fail_table(_table: object, _index: int) -> str:
        nonlocal table_extraction_attempts
        table_extraction_attempts += 1
        raise ValueError("optional table extraction failed")

    monkeypatch.setattr(source_state, "_table_gfm", fail_table)
    prepared = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "result", "expected_revision": 0},
    )
    source = prepared["data"]["trials"][0]["sources"][0]
    [failure] = [
        item
        for item in prepared["data"]["conditions"]
        if item["code"] == "optional_table_extraction_failed"
    ]
    source_id = resolve_source_handle(tmp_path, "trial", source["id"])

    assert prepared["outcome"] == "success"
    assert failure["source_id"] == source["id"]
    assert failure["page"] == 2
    assert "narrative text remains searchable" in failure["reason"]
    page = read_pages(tmp_path, "trial", source_id, [2])["pages"][0]
    assert "Docetaxel" in page["text"]
    assert "[Extracted table 1]" not in page["text"]
    assert search_sources(tmp_path, "trial", "Docetaxel")["hits"][0]["page"] == 2

    navigation = list_sources(tmp_path, "trial", source_id)["navigation"]
    recovery = next(item for item in navigation["render_recovery"] if item["page"] == 2)
    assert recovery == {
        "operation": "render_page",
        "trial_id": "trial",
        "source_id": source_id,
        "page": 2,
        "inline": True,
    }
    assert render_page(tmp_path, "trial", source_id, 2)["_png_bytes"].startswith(b"\x89PNG")

    attempts_at_capture = table_extraction_attempts
    with _db(tmp_path, "derivative.sqlite3") as derivative:
        derivative.execute("DELETE FROM pages WHERE source_id=?", (source_id,))
    rebuilt_search = search_sources(tmp_path, "trial", "Docetaxel")
    assert rebuilt_search["hits"][0]["page"] == 2
    assert table_extraction_attempts == attempts_at_capture
    assert "Docetaxel" in read_pages(tmp_path, "trial", source_id, [2])["pages"][0]["text"]

    captured = tmp_path / ".rob2-kit" / "sources" / "trial" / f"{source_id}.bin"
    captured.write_bytes(b"tampered source bytes")
    with pytest.raises(ValueError, match="captured Source bytes do not match Canonical identity"):
        search_sources(tmp_path, "trial", "Docetaxel")


class _TableShape:
    def __init__(self, rows: int, columns: int, cells: list[list[str | None]]) -> None:
        self.row_count = rows
        self.col_count = columns
        self._cells = cells

    def extract(self) -> list[list[str | None]]:
        return self._cells


def test_semantic_table_filter_uses_shape_and_text_not_source_names() -> None:
    meaningful = _TableShape(
        5, 3, [["Header", "Count", "Rate"], ["A", "1", "2%"], ["B", "2", "3%"]]
    )
    tiny = _TableShape(2, 3, [["label", None, None], ["value", None, None]])

    assert _semantic_table_page((tiny, meaningful)) is True


def test_semantic_table_filter_rejects_form_pages_with_many_small_regions() -> None:
    form_regions = tuple(
        _TableShape(3 if index % 2 else 2, 3, [["x", None, None]] * (3 if index % 2 else 2))
        for index in range(199)
    )

    assert _semantic_table_page(form_regions) is False


def test_semantic_table_filter_accepts_compact_three_by_three_result_table() -> None:
    result = _TableShape(
        3,
        3,
        [
            ["Group", "Events", "Denominator"],
            ["Treatment", "12", "100"],
            ["Control", "20", "100"],
        ],
    )

    assert _semantic_table_page((result,)) is True


def test_semantic_table_filter_rejects_sparse_three_by_three_form() -> None:
    form = _TableShape(
        3,
        3,
        [["Name", None, None], ["Signature", None, None], ["Date", "", None]],
    )

    assert _semantic_table_page((form,)) is False


def test_table_gfm_preserves_category_axes_and_values() -> None:
    table = _TableShape(
        3,
        4,
        [
            ["Event", "Grade 3", "Grade 4", "Grade 5"],
            ["Any event", "65 (16.7)", "49 (12.6)", "1 (0.3)"],
            ["Fatigue", "16 (4.1)", "0", "0"],
        ],
    )

    rendered = _table_gfm(table, 1)

    assert "|Event|Grade 3|Grade 4|Grade 5|" in rendered
    assert "|Any event|65 (16.7)|49 (12.6)|1 (0.3)|" in rendered


def test_projection_identity_is_recipe_versioned() -> None:
    pages = ("narrative", "|Arm|Events|\n|---|---|\n|ADT|12|")
    source = {"sha256": "sha256:" + "a" * 64, "media_type": "application/pdf"}
    identity = reproduce_projection_identity(source, pages)

    assert identity["schema_version"] == "rob2-kit.text-projection.v3"
    assert identity["recipe"] == "rob2-kit.extract-pages.v4"
    assert (
        _projection_hash(source["sha256"], source["media_type"], pages)
        == identity["projection_hash"]
    )


def test_projection_normalization_removes_nonprinting_artifacts_once() -> None:
    raw = "The \ufb01nal\u200b\u202e analysis\x00 was complete.\u00ad\r\n"

    assert _normalize_projected_text(raw) == "The final analysis was complete.\n"


def test_text_source_projection_uses_the_same_normalized_text_as_public_reads() -> None:
    raw = "A\u00a0ligature: \ufb01. A bidi marker:\u202e done.\x07\n"

    assert _pages(Path("source.txt"), raw.encode("utf-8")) == (
        "A ligature: fi. A bidi marker: done.\n",
    )


def test_fts_and_exact_evidence_use_projected_table_cells(tmp_path: Path) -> None:
    workspace, source = _prepare_pdf(tmp_path)

    hits = search_sources(workspace, "trial", "Docetaxel")
    # Search sessions retain separate local match windows, even when table
    # extraction and page text produce two navigable passages on one page.
    assert len(hits["hits"]) == 2
    assert hits["hits"][0]["page"] == 2
    assert "Docetaxel" in hits["hits"][0]["preview"]
    assert "[Extracted table 1]" in hits["hits"][0]["preview"]
    evidence = select_text_evidence(workspace, "trial", str(source["id"]), 2, "|Docetaxel|22|5%|")
    assert evidence["evidence"]["quote"] == "|Docetaxel|22|5%|"


def test_text_selection_canonicalizes_a_unique_match_on_another_page(tmp_path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((50, 50), "A unique source phrase.")
    second = document.new_page()
    second.insert_text((50, 50), "A different page.")
    try:
        pdf = document.tobytes()
    finally:
        document.close()

    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(pdf)
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="result")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]

    evidence = select_text_evidence(
        tmp_path, "trial", str(source["id"]), 2, "A unique source phrase."
    )["evidence"]

    assert evidence["page"] == 1
    assert evidence["quote"] == "A unique source phrase."


def test_text_selection_rejects_cross_page_ambiguity(tmp_path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((50, 50), "A different page.")
    second = document.new_page()
    second.insert_text((50, 50), "A repeated source phrase.")
    third = document.new_page()
    third.insert_text((50, 50), "A repeated source phrase.\nA repeated source phrase.")
    try:
        pdf = document.tobytes()
    finally:
        document.close()

    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(pdf)
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="result")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]

    with pytest.raises(ValueError, match="not an exact page selection"):
        select_text_evidence(tmp_path, "trial", str(source["id"]), 1, "A repeated source phrase.")


def test_text_selection_canonicalizes_a_unique_out_of_range_page_hint(tmp_path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((50, 50), "A unique source phrase.")
    try:
        pdf = document.tobytes()
    finally:
        document.close()

    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(pdf)
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="result")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]

    evidence = select_text_evidence(
        tmp_path, "trial", str(source["id"]), 7, "A unique source phrase."
    )["evidence"]

    assert evidence["page"] == 1


def test_text_selection_rejects_ambiguous_out_of_range_page_hint(tmp_path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((50, 50), "A repeated source phrase.")
    second = document.new_page()
    second.insert_text((50, 50), "A repeated source phrase.")
    try:
        pdf = document.tobytes()
    finally:
        document.close()

    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "article.pdf").write_bytes(pdf)
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="result")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]

    with pytest.raises(ValueError, match="not an exact page selection"):
        select_text_evidence(tmp_path, "trial", str(source["id"]), 7, "A repeated source phrase.")


def test_stale_projected_pages_fail_closed(tmp_path: Path) -> None:
    workspace, source = _prepare_pdf(tmp_path)
    with _db(workspace, "derivative.sqlite3") as connection:
        connection.execute(
            "UPDATE pages SET text='stale' WHERE source_id=? AND page=2", (source["id"],)
        )

    with pytest.raises(ValueError, match="projection identity is corrupt"):
        read_pages(workspace, "trial", str(source["id"]), [2])
