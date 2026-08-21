"""Immutable local source records and direct page-coordinate reads."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import pymupdf
from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRole(StrEnum):
    MAIN_ARTICLE = "main_article"
    REGISTRY = "registry"
    PROTOCOL = "protocol"
    SAP = "sap"
    SUPPLEMENT = "supplement"
    SECONDARY_REPORT = "secondary_report"
    OTHER = "other"


SOURCE_PRIORITY = tuple(SourceRole)


class SourceInput(_StrictModel):
    role: SourceRole
    path: str
    label: Annotated[str, Field(min_length=1)]


class TrialInput(_StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    label: Annotated[str, Field(min_length=1)]
    sources: tuple[SourceInput, ...]


class Source(_StrictModel):
    id: str
    trial_id: str
    role: SourceRole
    label: str
    sha256: str
    media_type: str
    page_count: Annotated[int, Field(ge=1)]
    extraction_warnings: tuple[str, ...]
    captured_path: str


class ExpectedCondition(_StrictModel):
    code: str
    trial_id: str
    detail: str


class IngestedTrial(_StrictModel):
    trial_id: str
    sources: tuple[Source, ...] = ()
    projection_pages: tuple[tuple[str, ...], ...] = Field(default=(), exclude=True)
    condition: ExpectedCondition | None = None


class IngestBatchResult(_StrictModel):
    trials: tuple[IngestedTrial, ...]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def local_source_id(
    trial_id: str, role: SourceRole, input_path: str, label: str, bytes_hash: str, occurrence: int
) -> str:
    """Stable captured-Source identity; occurrence distinguishes exact declarations."""
    normalized = Path(input_path).as_posix()
    material = "\0".join((trial_id, str(role), normalized, label, bytes_hash, str(occurrence)))
    return "source_" + hashlib.sha256(material.encode()).hexdigest()


def source_sort_key(source: Source) -> tuple[int, str, str]:
    return (SOURCE_PRIORITY.index(source.role), source.label.casefold(), source.id)


def list_sources(sources: tuple[Source, ...] | list[Source]) -> tuple[Source, ...]:
    """Return Sources in the documented role priority and a stable tie order."""
    return tuple(sorted(sources, key=source_sort_key))


def verified_source_bytes(root: Path, source: Source) -> bytes:
    """Read one captured Source after verifying its path, hash, and media type."""
    relative = Path(source.captured_path)
    expected = Path(".rob2-kit") / "sources" / source.trial_id
    v3_prefix = Path(".rob2-kit") / "sources-v3"
    if relative.parts[:2] == v3_prefix.parts:
        if (
            len(relative.parts) != 5
            or relative.parts[2].startswith("sha256:")
            or relative.parts[3] != source.trial_id
            or relative.parts[4] != source.id
        ):
            raise ValueError("Source captured path is not its application capture path")
    elif relative.parent != expected or relative.name.split(".")[0] != source.id:
        raise ValueError("Source captured path is not its Trial capture path")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Source captured path escapes workspace")
    data = path.read_bytes()
    if sha256_bytes(data) != source.sha256 or _media_type(path, data) != source.media_type:
        raise ValueError("Source metadata is stale")
    return data


def _under(workspace: Path, requested: str) -> Path:
    candidate = (workspace / requested).resolve(strict=True)
    if not candidate.is_relative_to(workspace):
        raise ValueError("path escapes workspace")
    return candidate


def _media_type(path: Path, data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return {".txt": "text/plain", ".json": "application/json"}.get(
        path.suffix.lower(), "application/octet-stream"
    )


def _extract_pages(data: bytes, media_type: str) -> tuple[str, ...]:
    if media_type == "application/pdf":
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            pages = tuple(page.get_text() for page in document)
        finally:
            document.close()
        if not pages:
            raise ValueError("PDF has no pages")
        return pages
    if media_type == "application/json":
        text = data.decode("utf-8")
        json.loads(text)
        return (text,)
    if media_type == "text/plain":
        return (data.decode("utf-8"),)
    raise ValueError("unsupported source media type")


def extraction_warnings(media_type: str, pages: tuple[str, ...]) -> tuple[str, ...]:
    if media_type != "application/pdf":
        return ()
    return tuple(
        f"page_{number}_has_no_extractable_text"
        for number, text in enumerate(pages, start=1)
        if not text.strip()
    )
