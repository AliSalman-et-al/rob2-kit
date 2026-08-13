from __future__ import annotations

import os
from pathlib import Path

import pymupdf
import pytest

from rob2_kit.ingestion import ingest_batch
from rob2_kit.sources import SourceInput, TrialInput


def _pdf(path: Path, text: str = "page") -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_main_article_expected_conditions(tmp_path: Path):
    (tmp_path / "note.txt").write_text("note", encoding="utf-8")
    _pdf(tmp_path / "a.pdf")
    _pdf(tmp_path / "b.pdf")
    missing = ingest_batch(
        tmp_path, (TrialInput(id="missing", label="Missing", sources=()),)
    ).trials[0]
    assert missing.condition and missing.condition.code == "main_article_required"
    multiple = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="multiple",
                label="Multiple",
                sources=(
                    SourceInput(role="main_article", path="a.pdf", label="A"),
                    SourceInput(role="main_article", path="b.pdf", label="B"),
                ),
            ),
        ),
    ).trials[0]
    assert multiple.condition and multiple.condition.code == "main_article_ambiguous"
    non_pdf = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="text",
                label="Text",
                sources=(SourceInput(role="main_article", path="note.txt", label="Note"),),
            ),
        ),
    ).trials[0]
    assert non_pdf.condition and non_pdf.condition.code == "main_article_must_be_pdf"


def test_supplement_formats_trial_isolation_and_source_identity(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    (tmp_path / "note.txt").write_text("plain", encoding="utf-8")
    (tmp_path / "metadata.json").write_text('{"z": 1, "a": 2}', encoding="utf-8")
    trial_sources = (
        SourceInput(role="main_article", path="main.pdf", label="Main"),
        SourceInput(role="supplement", path="note.txt", label="Note"),
        SourceInput(role="supplement", path="metadata.json", label="Metadata"),
    )
    result = ingest_batch(
        tmp_path,
        (
            TrialInput(id="one", label="One", sources=trial_sources),
            TrialInput(id="two", label="Two", sources=trial_sources),
        ),
    )
    one, two = result.trials
    assert {source.media_type for source in one.sources} == {
        "application/pdf",
        "text/plain",
        "application/json",
    }
    assert {source.id for source in one.sources}.isdisjoint({source.id for source in two.sources})
    assert all(source.captured_path.startswith(".rob2-kit/sources/one/") for source in one.sources)
    assert all(source.captured_path.startswith(".rob2-kit/sources/two/") for source in two.sources)


def test_same_bytes_in_one_trial_are_distinct_sources(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    (tmp_path / "copy-a.txt").write_text("same bytes", encoding="utf-8")
    sources = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="duplicate",
                    label="Duplicate",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="copy-a.txt", label="Exact copy"),
                        SourceInput(role="supplement", path="copy-a.txt", label="Exact copy"),
                    ),
                ),
            ),
        )
        .trials[0]
        .sources
    )
    copies = [source for source in sources if source.media_type == "text/plain"]
    assert len({source.id for source in copies}) == 2
    assert len({source.captured_path for source in copies}) == 2


def test_reordering_distinct_inputs_keeps_source_ids_and_paths(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    main = SourceInput(role="main_article", path="main.pdf", label="Main")
    a = SourceInput(role="supplement", path="a.txt", label="A")
    b = SourceInput(role="supplement", path="b.txt", label="B")
    first = ingest_batch(
        tmp_path, (TrialInput(id="stable", label="Stable", sources=(main, a, b)),)
    ).trials[0]
    second = ingest_batch(
        tmp_path, (TrialInput(id="stable", label="Stable", sources=(b, main, a)),)
    ).trials[0]
    assert {(source.id, source.captured_path) for source in first.sources} == {
        (source.id, source.captured_path) for source in second.sources
    }


def test_write_failure_cleans_staging_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import rob2_kit.ingestion.service as service

    _pdf(tmp_path / "main.pdf")
    (tmp_path / "supplement.txt").write_text("supplement", encoding="utf-8")
    original = service._write_capture
    calls = 0

    def fail_second(target: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original(target, data)

    monkeypatch.setattr(service, "_write_capture", fail_second)
    with pytest.raises(OSError, match="injected"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="failed",
                    label="Failed",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="supplement.txt", label="Supplement"),
                    ),
                ),
            ),
        )
    assert not (tmp_path / ".rob2-kit" / "sources" / "failed").exists()
    assert not list((tmp_path / ".rob2-kit" / "capture-staging").iterdir())


def test_rejects_traversal_and_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.pdf"
    _pdf(outside)
    with pytest.raises(ValueError, match="escapes"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="bad",
                    label="Bad",
                    sources=(SourceInput(role="main_article", path="../outside.pdf", label="Bad"),),
                ),
            ),
        )
    link = tmp_path / "escape.pdf"
    try:
        os.symlink(outside, link)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    with pytest.raises(ValueError, match="escapes"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="link",
                    label="Link",
                    sources=(SourceInput(role="main_article", path="escape.pdf", label="Link"),),
                ),
            ),
        )


def test_rejects_hostile_capture_tree_and_leaves_no_partial_capture(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    outside = tmp_path.parent / "capture-outside"
    outside.mkdir(exist_ok=True)
    capture_root = tmp_path / ".rob2-kit"
    capture_root.mkdir()
    redirected_sources = capture_root / "sources"
    try:
        os.symlink(outside, redirected_sources, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    with pytest.raises(ValueError, match="redirected"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="hostile",
                    label="Hostile",
                    sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
                ),
            ),
        )
    assert not (outside / "hostile").exists()


def test_later_invalid_input_creates_no_trial_capture(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    (tmp_path / "unsupported.bin").write_bytes(b"not supported")
    with pytest.raises(ValueError, match="unsupported"):
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="atomic",
                    label="Atomic",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="unsupported.bin", label="Bad"),
                    ),
                ),
            ),
        )
    assert not (tmp_path / ".rob2-kit" / "sources" / "atomic").exists()


def test_pdf_content_not_extension_and_blank_page_warning(tmp_path: Path):
    (tmp_path / "renamed.pdf").write_text("not a PDF", encoding="utf-8")
    rejected = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="bad-pdf",
                label="Bad",
                sources=(SourceInput(role="main_article", path="renamed.pdf", label="Bad"),),
            ),
        ),
    ).trials[0]
    assert rejected.condition and rejected.condition.code == "main_article_must_be_pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(tmp_path / "article.data")
    document.close()
    source = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="blank",
                    label="Blank",
                    sources=(SourceInput(role="main_article", path="article.data", label="Main"),),
                ),
            ),
        )
        .trials[0]
        .sources[0]
    )
    assert source.media_type == "application/pdf"
    assert source.extraction_warnings == ("page_1_has_no_extractable_text",)
