from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from rob2_kit.sources import SourceInput, SourceRole, TrialInput, list_sources, read_pages


def _pdf(path: Path, *pages: str) -> None:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_list_sources_priority_and_direct_pdf_page_coordinates(tmp_path: Path):
    from rob2_kit.ingestion import ingest_batch

    _pdf(tmp_path / "main.pdf", "first page", "second page")
    (tmp_path / "z.txt").write_text("supplement", encoding="utf-8")
    result = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="trial-a",
                label="Trial A",
                sources=(
                    SourceInput(role=SourceRole.SUPPLEMENT, path="z.txt", label="Z supplement"),
                    SourceInput(
                        role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main article"
                    ),
                ),
            ),
        ),
    )
    sources = result.trials[0].sources
    assert [source.role for source in sources] == [SourceRole.MAIN_ARTICLE, SourceRole.SUPPLEMENT]
    assert sources[0].id != sources[0].label != sources[0].captured_path
    assert sources[0].page_count == 2
    pages = read_pages(tmp_path, sources[0], (2, 1)).pages
    assert [(page.page_number, page.start, page.end) for page in pages] == [(2, 0, 12), (1, 0, 11)]
    assert [page.text.strip() for page in pages] == ["second page", "first page"]
    assert list_sources(tuple(reversed(sources))) == sources


def test_read_pages_rejects_invalid_coordinates_and_changed_capture(tmp_path: Path):
    from rob2_kit.ingestion import ingest_batch

    _pdf(tmp_path / "main.pdf", "one")
    source = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="trial",
                    label="Trial",
                    sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
                ),
            ),
        )
        .trials[0]
        .sources[0]
    )
    with pytest.raises(ValueError, match="outside"):
        read_pages(tmp_path, source, (2,))
    captured = tmp_path / source.captured_path
    captured.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        read_pages(tmp_path, source, (1,))


def test_json_page_text_preserves_source_authored_whitespace_and_order(tmp_path: Path):
    from rob2_kit.ingestion import ingest_batch

    _pdf(tmp_path / "main.pdf", "article")
    authored = '{\n  "z": [3, 2],\n  "a": 1\n}\n'
    (tmp_path / "source.json").write_bytes(authored.encode("utf-8"))
    sources = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="json",
                    label="JSON",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="source.json", label="JSON"),
                    ),
                ),
            ),
        )
        .trials[0]
        .sources
    )
    json_source = next(source for source in sources if source.media_type == "application/json")
    page = read_pages(tmp_path, json_source, (1,)).pages[0]
    assert page.text == authored
    assert (page.start, page.end) == (0, len(authored))
