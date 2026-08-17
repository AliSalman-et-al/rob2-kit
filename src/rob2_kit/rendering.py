"""Selective rendering over an explicit immutable Source record."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.sources import Source, verified_source_bytes


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RenderedPage(_Result):
    source_id: str
    source_hash: str
    page_number: int = Field(ge=1)
    region: tuple[float, float, float, float] | None = None
    image_bytes: bytes
    media_type: str = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str


class RenderCondition(_Result):
    source_id: str
    source_hash: str
    page_number: int = Field(ge=1)
    code: str


def render_page(
    workspace: str | Path,
    source: Source,
    page_number: int,
    region: tuple[float, float, float, float] | None = None,
) -> RenderedPage | RenderCondition:
    if page_number < 1:
        raise ValueError("page number must be one-based")
    if region is not None and (
        len(region) != 4
        or any(not 0 <= value <= 1 for value in region)
        or region[0] >= region[2]
        or region[1] >= region[3]
    ):
        raise ValueError("region must be a nonempty normalized rectangle")
    data = verified_source_bytes(Path(workspace).resolve(strict=True), source)
    if source.media_type != "application/pdf":
        return RenderCondition(
            source_id=source.id,
            source_hash=source.sha256,
            page_number=page_number,
            code="visual_rendering_unsupported",
        )
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if page_number > doc.page_count:
            raise ValueError("page number outside source")
        page = doc[page_number - 1]
        r = page.rect
        clip = (
            None
            if region is None
            else pymupdf.Rect(
                r.x0 + r.width * region[0],
                r.y0 + r.height * region[1],
                r.x0 + r.width * region[2],
                r.y0 + r.height * region[3],
            )
        )
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False)
        image = pix.tobytes("png")
    finally:
        doc.close()
    return RenderedPage(
        source_id=source.id,
        source_hash=source.sha256,
        page_number=page_number,
        region=region,
        image_bytes=image,
        width=pix.width,
        height=pix.height,
        sha256="sha256:" + hashlib.sha256(image).hexdigest(),
    )
