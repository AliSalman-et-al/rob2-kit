import sqlite3
from pathlib import Path

import pymupdf
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
