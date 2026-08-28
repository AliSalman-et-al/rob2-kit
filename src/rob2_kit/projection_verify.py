"""Standalone Text projection identity reproduction for installed artifact verification."""

import hashlib
import json
from collections.abc import Mapping, Sequence


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def reproduce_projection_identity(
    source: Mapping[str, object], pages: Sequence[str]
) -> dict[str, object]:
    """Reproduce identity without importing the runtime projection implementation."""

    if not pages:
        raise ValueError("a Text projection must contain at least one page")
    page_hashes = ["sha256:" + hashlib.sha256(page.encode("utf-8")).hexdigest() for page in pages]
    content = {
        "recipe": "rob2-kit.extract-pages.v4",
        "source_sha256": source["sha256"],
        "media_type": source["media_type"],
        "page_hashes": page_hashes,
    }
    return {
        "schema_version": "rob2-kit.text-projection.v3",
        **content,
        "projection_hash": _hash(content),
        "page_count": len(pages),
    }


__all__ = ["reproduce_projection_identity"]
