"""Selective rendering over an explicit immutable Source record."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.application._state import identity as content_identity
from rob2_kit.application._state import read_json, write_json
from rob2_kit.sources import Source, verified_source_bytes

if TYPE_CHECKING:
    from rob2_kit.application.contracts import RenderReference


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
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    sha256: str
    render_identity: str = ""
    recipe: str = "png-rgb-72dpi-full-144dpi-region-v1"


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
    normalized_region = None if region is None else tuple(float(value) for value in region)
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
        if normalized_region is None:
            clip = None
        else:
            clip = pymupdf.Rect(
                r.x0 + r.width * normalized_region[0],
                r.y0 + r.height * normalized_region[1],
                r.x0 + r.width * normalized_region[2],
                r.y0 + r.height * normalized_region[3],
            )
        scale = 2 if region is not None else 1
        bounds = clip or r
        factor = min(1.0, 2048 / max(bounds.width * scale, bounds.height * scale))
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(scale * factor, scale * factor), clip=clip, alpha=False
        )
        image = pix.tobytes("png")
    finally:
        doc.close()
    # Keep the public geometry in the source's 72-DPI coordinate space.  The
    # encoded PNG dimensions remain explicit below because regions are always
    # rendered at 144 DPI and therefore may have more pixels than the full
    # page.  This makes region extents comparable without weakening the fixed
    # raster recipes.
    width = max(1, round(bounds.width))
    height = max(1, round(bounds.height))
    pixel_width, pixel_height = pix.width, pix.height
    image_hash = "sha256:" + hashlib.sha256(image).hexdigest()
    render_id = content_identity(
        {
            "source_id": source.id,
            "source_sha256": source.sha256,
            "page": page_number,
            "region": normalized_region,
            "recipe": "png-rgb-72dpi-full-144dpi-region-v1",
            "width": width,
            "height": height,
            "pixel_width": pixel_width,
            "pixel_height": pixel_height,
            "media_type": "image/png",
            "png_sha256": image_hash,
        }
    )
    result = RenderedPage(
        source_id=source.id,
        source_hash=source.sha256,
        page_number=page_number,
        region=normalized_region,
        image_bytes=image,
        width=width,
        height=height,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
        sha256=image_hash,
        render_identity=render_id,
    )
    persist_render(workspace, result)
    return result


def _render_root(workspace: str | Path, *, create: bool = True) -> Path:
    root = Path(workspace).resolve(strict=True) / ".rob2-kit" / "renders"
    if root.exists() and root.is_symlink():
        raise ValueError("render store is redirected")
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def persist_render(workspace: str | Path, rendered: RenderedPage) -> RenderReference:
    from rob2_kit.application.contracts import RenderReference

    root = _render_root(workspace)
    path = root / f"{rendered.render_identity.removeprefix('sha256:')}.png"
    if path.is_symlink():
        raise ValueError("render bytes are redirected")
    # The exact bytes are content-addressed and never silently overwritten.
    if path.exists() and path.read_bytes() != rendered.image_bytes:
        raise ValueError("render identity is bound to different PNG bytes")
    if not path.exists():
        path.write_bytes(rendered.image_bytes)
    metadata = {
        "source_id": rendered.source_id,
        "source_hash": rendered.source_hash,
        "page_number": rendered.page_number,
        "region": rendered.region,
        "width": rendered.width,
        "height": rendered.height,
        "pixel_width": rendered.pixel_width,
        "pixel_height": rendered.pixel_height,
        "media_type": rendered.media_type,
        "sha256": rendered.sha256,
        "render_identity": rendered.render_identity,
        "recipe": rendered.recipe,
    }
    write_json(
        workspace,
        f"render-{rendered.render_identity.removeprefix('sha256:')}.json",
        metadata,
    )
    return RenderReference(
        identity=rendered.render_identity,
        uri=f"rob2://render/{rendered.render_identity}",
    )


def read_render(workspace: str | Path, identity: str) -> tuple[RenderedPage, bytes]:
    if not identity.startswith("sha256:") or len(identity) != 71:
        raise ValueError("invalid render identity")
    metadata = read_json(workspace, f"render-{identity.removeprefix('sha256:')}.json")
    if metadata is None:
        raise ValueError("render is unavailable")
    path = _render_root(workspace, create=False) / f"{identity.removeprefix('sha256:')}.png"
    if not path.is_file() or path.is_symlink():
        raise ValueError("render bytes are unavailable")
    image = path.read_bytes()
    if "sha256:" + hashlib.sha256(image).hexdigest() != metadata.get("sha256"):
        raise ValueError("render PNG bytes are corrupt")
    payload = dict(metadata)
    payload["image_bytes"] = image
    rendered = RenderedPage.model_validate(payload)
    if (
        len(image) < 26
        or image[:8] != b"\x89PNG\r\n\x1a\n"
        or image[12:16] != b"IHDR"
        or struct.unpack(">II", image[16:24]) != (rendered.pixel_width, rendered.pixel_height)
        or image[24] != 8
        or image[25] != 2
    ):
        raise ValueError("render PNG dimensions or color model are corrupt")
    expected = content_identity(
        {
            "source_id": rendered.source_id,
            "source_sha256": rendered.source_hash,
            "page": rendered.page_number,
            "region": rendered.region,
            "recipe": rendered.recipe,
            "width": rendered.width,
            "height": rendered.height,
            "pixel_width": rendered.pixel_width,
            "pixel_height": rendered.pixel_height,
            "media_type": rendered.media_type,
            "png_sha256": rendered.sha256,
        }
    )
    if expected != identity or rendered.render_identity != identity:
        raise ValueError("render identity is corrupt")
    return rendered, image
