"""Public host boundaries for the single typed RunEngine workflow."""

from __future__ import annotations

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
from rob2_kit.interfaces.mcp.server import registered_tool_names


def blank_pdf() -> bytes:
    """Return the small valid PDF fixture shared by stdio workflow tests."""

    stream = b"BT /F1 12 Tf 10 36 Td (Trial report) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def test_stdio_mcp_surface_is_the_fixed_run_engine_inventory() -> None:
    assert registered_tool_names() == RUN_OPERATION_NAMES
    assert "open_review" not in registered_tool_names()
