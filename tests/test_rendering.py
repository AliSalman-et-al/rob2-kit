from pathlib import Path
from typing import Any, cast

import pymupdf
import pytest

from rob2_kit.ingestion import ingest_batch
from rob2_kit.rendering import RenderCondition, RenderedPage, render_page
from rob2_kit.sources import SourceInput, TrialInput


def _pdf(path: Path):
    doc = pymupdf.open()
    page = doc.new_page()
    shape = page.new_shape()
    for x in (60, 180, 300):
        shape.draw_line((x, 70), (x, 170))
    for y in (70, 120, 170):
        shape.draw_line((60, y), (300, y))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    page.insert_text((75, 100), "Table cell A")
    page.insert_text((195, 150), "Table cell B")
    for rect, label in (((80, 230, 260, 270), "Randomized"), ((80, 330, 260, 370), "Analysed")):
        page.draw_rect(rect, color=(0, 0, 0))
        page.insert_text((100, rect[1] + 25), label)
    page.draw_line((170, 270), (170, 330), color=(0, 0, 0), width=2)
    page.insert_text((70, 800), "Footnote: spatial evidence")
    doc.save(path)
    doc.close()


def test_render_page_and_crop_metadata(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    (tmp_path / "note.txt").write_text("text", encoding="utf-8")
    sources = (
        ingest_batch(
            tmp_path,
            (
                TrialInput(
                    id="t",
                    label="T",
                    sources=(
                        SourceInput(role="main_article", path="main.pdf", label="Main"),
                        SourceInput(role="supplement", path="note.txt", label="Text"),
                    ),
                ),
            ),
        )
        .trials[0]
        .sources
    )
    pdf = next(s for s in sources if s.media_type == "application/pdf")
    full = render_page(tmp_path, pdf, 1)
    crop = render_page(tmp_path, pdf, 1, (0, 0, 0.5, 0.5))
    assert isinstance(full, RenderedPage) and isinstance(crop, RenderedPage)
    assert full.image_bytes and full.sha256
    assert crop.width is not None and full.width is not None and crop.width < full.width
    assert crop.height is not None and full.height is not None and crop.height < full.height
    text = next(s for s in sources if s.media_type == "text/plain")
    unsupported = render_page(tmp_path, text, 1)
    assert isinstance(unsupported, RenderCondition)
    assert unsupported.code == "visual_rendering_unsupported"
    with pytest.raises(ValueError):
        render_page(tmp_path, pdf, 0)
    with pytest.raises(ValueError):
        render_page(tmp_path, pdf, -1)
    with pytest.raises(ValueError):
        render_page(tmp_path, pdf, 1, cast(Any, (0, 0, 1)))


def test_vector_layout_crops_and_extraction_discrepancy(tmp_path: Path):
    _pdf(tmp_path / "main.pdf")
    vector = pymupdf.open()
    vector.new_page().draw_circle((200, 200), 80, color=(1, 0, 0), fill=(1, 1, 0))
    vector.save(tmp_path / "vector.pdf")
    vector.close()
    result = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="v",
                label="V",
                sources=(
                    SourceInput(role="main_article", path="main.pdf", label="Main"),
                    SourceInput(role="supplement", path="vector.pdf", label="Diagram"),
                ),
            ),
        ),
    ).trials[0]
    main, diagram = result.sources
    full = render_page(tmp_path, main, 1)
    central = render_page(tmp_path, main, 1, (0.1, 0.1, 0.8, 0.65))
    bottom = render_page(tmp_path, main, 1, (0, 0.85, 1, 1))
    assert (
        isinstance(full, RenderedPage)
        and isinstance(central, RenderedPage)
        and isinstance(bottom, RenderedPage)
    )
    repeat = render_page(tmp_path, main, 1)
    assert isinstance(repeat, RenderedPage) and full.sha256 == repeat.sha256
    assert (
        central.sha256 != bottom.sha256
        and central.width < full.width
        and bottom.height < full.height
    )
    assert sum(full.image_bytes) > 0 and sum(bottom.image_bytes) > 0

    def ink_count(image: bytes) -> int:
        raster = pymupdf.open(stream=image, filetype="png")
        try:
            return sum(value < 245 for value in raster[0].get_pixmap().samples)
        finally:
            raster.close()

    assert ink_count(central.image_bytes) > 100
    assert ink_count(bottom.image_bytes) > 20
    assert ink_count(central.image_bytes) != ink_count(bottom.image_bytes)
    assert diagram.extraction_warnings == ("page_1_has_no_extractable_text",)
    visual = render_page(tmp_path, diagram, 1)
    assert isinstance(visual, RenderedPage) and ink_count(visual.image_bytes) > 1_000
