"""Cached deterministic page rendering and transport policy."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rob2_kit.rendering import RenderCondition, RenderedPage, read_render, render_page
from rob2_kit.sources import Source


class RenderDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rendered: RenderedPage | None = None
    condition: RenderCondition | None = None
    cached: bool = False
    include_inline_image: bool = True


def _metadata_files(workspace: str | Path):
    root = Path(workspace).resolve(strict=True)
    yield from root.glob("render-*.json")


def _cached(
    workspace: str | Path,
    source: Source,
    page: int,
    region: tuple[float, float, float, float] | None,
) -> RenderedPage | None:
    normalized = None if region is None else tuple(float(value) for value in region)
    for path in _metadata_files(workspace):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        stored_region = (
            tuple(raw["region"]) if isinstance(raw.get("region"), list) else raw.get("region")
        )
        if (
            raw.get("source_id") != source.id
            or raw.get("source_hash") != source.sha256
            or raw.get("page_number") != page
            or stored_region != normalized
        ):
            continue
        identity = raw.get("render_identity")
        if not isinstance(identity, str):
            continue
        try:
            return read_render(workspace, identity)[0]
        except (OSError, ValueError):
            continue
    return None


def render_cached(
    workspace: str | Path,
    source: Source,
    page: int,
    region: tuple[float, float, float, float] | None = None,
    *,
    force_inline: bool = False,
) -> RenderDelivery:
    existing = _cached(workspace, source, page, region)
    if existing is not None:
        return RenderDelivery(
            rendered=existing,
            cached=True,
            include_inline_image=force_inline,
        )
    result = render_page(workspace, source, page, region)
    if isinstance(result, RenderCondition):
        return RenderDelivery(condition=result, include_inline_image=False)
    return RenderDelivery(rendered=result, cached=False, include_inline_image=True)
