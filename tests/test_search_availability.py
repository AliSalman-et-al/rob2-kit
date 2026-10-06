import sqlite3
from pathlib import Path

import pymupdf
import pytest
from fastmcp.exceptions import ToolError
from support.rob2 import _call


def _prepare(workspace: Path, *, article: str | None = None, image_only: bool = False):
    trial = workspace / "input" / "trial"
    trial.mkdir(parents=True)
    if article is not None:
        (trial / "main.txt").write_text(article, encoding="utf-8")
    if image_only:
        document = pymupdf.open()
        document.new_page()
        (trial / "scan.pdf").write_bytes(document.tobytes())
        document.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "symptoms", "expected_revision": 0},
    )


def _search(workspace: Path, **scope):
    return _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "allocation", "mode": "all", **scope},
    )


def test_no_captured_sources_does_not_issue_an_absence_receipt(tmp_path: Path):
    _prepare(tmp_path)
    result = _search(tmp_path)
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "no_sources"
    assert "no text was searched" in result["condition"]["detail"]
    assert "data" not in result
    with sqlite3.connect(tmp_path / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM search_receipts").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM search_sessions").fetchone()[0] == 0


def test_pdf_without_text_routes_to_image_recovery_not_query_refinement(tmp_path: Path):
    _prepare(tmp_path, image_only=True)
    result = _search(tmp_path)
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "no_searchable_sources"
    assert "render_page" in result["condition"]["detail"]
    assert "data" not in result


def test_source_scope_with_no_text_is_distinct_from_trial_lexical_miss(tmp_path: Path):
    _prepare(tmp_path, article="Outcome symptoms were collected monthly.", image_only=True)
    sources = _call(tmp_path, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    scan = next(source for source in sources if source["logical_path"] == "scan.pdf")
    scoped = _search(tmp_path, source_id=scan["id"])
    assert scoped["condition"]["code"] == "no_searchable_sources"
    searched = _search(tmp_path)
    assert searched["outcome"] == "success"
    assert searched["data"]["condition"] == "no_hits"
    assert searched["data"]["search_receipt"]


def test_search_batch_preserves_unsearchable_item_and_successful_independent_query(tmp_path: Path):
    _prepare(tmp_path, article="Allocation was concealed.", image_only=True)
    sources = _call(tmp_path, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    scan = next(source for source in sources if source["logical_path"] == "scan.pdf")
    result = _call(
        tmp_path,
        "search_sources_batch",
        {
            "requests": [
                {
                    "trial_id": "trial",
                    "query": "allocation",
                    "mode": "all",
                    "source_id": scan["id"],
                },
                {"trial_id": "trial", "query": "allocation", "mode": "all"},
            ]
        },
    )
    items = result["data"]["results"]
    assert items[0]["result"]["outcome"] == "condition"
    assert items[0]["result"]["condition"]["code"] == "no_searchable_sources"
    assert items[1]["result"]["outcome"] == "success"
    assert items[1]["result"]["data"]["total_matches"] == 1


def test_unavailable_source_preserves_verified_search_of_other_sources(tmp_path: Path):
    _prepare(tmp_path, article="Allocation was concealed.", image_only=True)
    sources = _call(tmp_path, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    article = next(source for source in sources if source["logical_path"] == "main.txt")
    scan = next(source for source in sources if source["logical_path"] == "scan.pdf")
    capture = tmp_path / ".rob2-kit" / "sources" / "trial"
    next(path for path in capture.iterdir() if path.read_bytes().startswith(b"%PDF")).unlink()

    result = _search(tmp_path)
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "captured_source_unavailable"
    assert result["condition"]["unavailable_source_ids"] == [scan["id"]]
    assert result["condition"]["available_source_ids"] == [article["id"]]
    assert "no text was searched" in result["condition"]["detail"]
    assert "data" not in result
    with sqlite3.connect(tmp_path / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM search_receipts").fetchone()[0] == 0
    batch = _call(
        tmp_path,
        "search_sources_batch",
        {
            "requests": [
                {"trial_id": "trial", "query": "allocation", "mode": "all"},
                {
                    "trial_id": "trial",
                    "query": "allocation",
                    "mode": "all",
                    "source_id": article["id"],
                },
            ]
        },
    )["data"]["results"]
    assert batch[0]["result"]["condition"] == result["condition"]
    assert batch[1]["result"]["data"]["total_matches"] == 1
    assert batch[1]["result"]["data"]["search_receipt"]

    next(capture.iterdir()).write_bytes(b"Different captured content")
    with pytest.raises(ToolError, match="internal_evidence_integrity_error"):
        _search(tmp_path, source_id=article["id"])


def test_search_scoped_to_unavailable_source_does_not_offer_other_scope(tmp_path: Path):
    _prepare(tmp_path, article="Allocation was concealed.")
    source = _call(tmp_path, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    next((tmp_path / ".rob2-kit" / "sources" / "trial").iterdir()).unlink()
    result = _search(tmp_path, source_id=source["id"])
    assert result["condition"]["unavailable_source_ids"] == [source["id"]]
    assert result["condition"]["available_source_ids"] == []
    assert "data" not in result
