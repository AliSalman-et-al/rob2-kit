"""Empty extracted text retains genuine source pixels without invented coverage."""

import hashlib
from pathlib import Path

import pymupdf
import pytest

from rob2_kit.application._state import _state
from rob2_kit.application.intake import prepare_batch_for_outcome
from scripts.freeze_native_evidence import freeze_native_evidence


def test_empty_and_graphic_pdf_pages_preserve_pixels_without_read_receipts(tmp_path: Path) -> None:
    folder = tmp_path / "input" / "trial"
    folder.mkdir(parents=True)
    with pymupdf.open() as pdf:
        pdf.new_page()
        page = pdf.new_page()
        page.draw_rect(pymupdf.Rect(40, 40, 140, 140), fill=(1, 0, 0))
        pdf.save(folder / "main.pdf")
    prepare_batch_for_outcome(tmp_path, "requested outcome", 0)
    before = _state(tmp_path)
    frozen = freeze_native_evidence(tmp_path, "trial")
    assert _state(tmp_path) == before
    assert not frozen.windows
    assert [frame.page for frame in frozen.images] == [1, 2]
    assert [record.visual_interpretation for record in frozen.empty_text_pages] == [
        "not_asserted",
        "not_asserted",
    ]
    for frame in frozen.images:
        pixels = frozen.bundle[frame.input_start_byte : frame.input_end_byte]
        assert pixels.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(pixels).hexdigest() == frame.png_sha256
    assert frozen.images[0].png_sha256 != frozen.images[1].png_sha256
    source = before["batch"]["trials"][0]["sources"][0]
    captured = tmp_path / ".rob2-kit" / "sources" / "trial" / (source["id"] + ".bin")
    captured.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        freeze_native_evidence(tmp_path, "trial")
