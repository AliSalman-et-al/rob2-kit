from pathlib import Path

import pymupdf
import pytest

from rob2_kit.ingestion import ingest_batch
from rob2_kit.search import search_sources
from rob2_kit.sources import SourceInput, TrialInput


def _pdf(path: Path, *texts: str):
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_search_is_explicit_deterministic_and_coordinate_bound(tmp_path: Path):
    _pdf(tmp_path / "main.pdf", "CONSORT table random allocation", "footnote allocation details")
    (tmp_path / "other.txt").write_text(
        "allocation concatenate cat café café supplement", encoding="utf-8"
    )
    sources = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="t",
                    label="T",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="other.txt", label="Other"),
                    ),
                ),
            ),
        )
        .trials[0]
        .sources
    )
    hits = search_sources(tmp_path, "t", sources, "allocation", 0, 10)
    assert [(h.source_id, h.page_number) for h in hits] == [
        (h.source_id, h.page_number)
        for h in search_sources(tmp_path, "t", sources, "allocation", 0, 10)
    ]
    assert all(
        h.text[span.start - h.start : span.end - h.start].lower() == "allocation"
        for h in hits
        for span in h.match_spans
    )
    assert search_sources(tmp_path, "t", (sources[0],), "allocation", 0, 10)
    assert search_sources(tmp_path, "t", (sources[0],), "allocation; DROP TABLE pages", 0, 10) == ()
    assert search_sources(tmp_path, "t", sources, "allocation", 1, 1) == hits[1:2]
    repeated = search_sources(tmp_path, "t", sources, "allocation footnote", 0, 10)
    assert repeated and all(span.end > span.start for hit in repeated for span in hit.match_spans)
    cat = search_sources(tmp_path, "t", (sources[1],), "cat", 0, 10)[0]
    assert [span.text for span in cat.match_spans] == ["cat"]
    cafe = search_sources(tmp_path, "t", (sources[1],), "cafe", 0, 10)[0]
    assert [span.text for span in cafe.match_spans] == ["café", "café"]
    assert not (tmp_path / ".rob2-kit" / "search-index").exists()
    with pytest.raises(ValueError):
        search_sources(tmp_path, "other", sources, "allocation", 0, 10)
    forged = sources[0].model_copy(update={"captured_path": "outside.pdf"})
    with pytest.raises(ValueError):
        search_sources(tmp_path, "t", (forged,), "allocation", 0, 10)
    (tmp_path / sources[0].captured_path).write_bytes(b"stale")
    with pytest.raises(ValueError):
        search_sources(tmp_path, "t", (sources[0],), "allocation", 0, 10)


def test_equal_rank_ties_are_source_then_page_with_stable_slices(tmp_path: Path):
    _pdf(tmp_path / "main.pdf", "tie token", "tie token")
    source = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="ties",
                    label="Ties",
                    sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
                ),
            ),
        )
        .trials[0]
        .sources[0]
    )
    hits = search_sources(tmp_path, "ties", (source,), "tie token", 0, 10)
    assert [(hit.source_id, hit.page_number) for hit in hits] == [(source.id, 1), (source.id, 2)]
    assert search_sources(tmp_path, "ties", (source,), "tie token", 1, 1) == hits[1:2]
