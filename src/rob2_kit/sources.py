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
    condition: ExpectedCondition | None = None


class IngestBatchResult(_StrictModel):
    trials: tuple[IngestedTrial, ...]


class PageText(_StrictModel):
    page_number: Annotated[int, Field(ge=1)]
    text: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]


class ReadPagesResult(_StrictModel):
    source_id: str
    pages: tuple[PageText, ...]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def source_sort_key(source: Source) -> tuple[int, str, str]:
    return (SOURCE_PRIORITY.index(source.role), source.label.casefold(), source.id)


def list_sources(sources: tuple[Source, ...] | list[Source]) -> tuple[Source, ...]:
    """Return Sources in the documented role priority and a stable tie order."""
    return tuple(sorted(sources, key=source_sort_key))


def read_pages(
    workspace: str | Path, source: Source, page_numbers: tuple[int, ...]
) -> ReadPagesResult:
    """Read exact page-local text from an immutable captured Source."""
    root = Path(workspace).resolve(strict=True)
    captured = _under(root, source.captured_path)
    data = captured.read_bytes()
    if sha256_bytes(data) != source.sha256:
        raise ValueError("captured source bytes have changed")
    if not page_numbers:
        raise ValueError("at least one one-based page number is required")
    if len(set(page_numbers)) != len(page_numbers):
        raise ValueError("page numbers must be unique")
    texts = _extract_pages(data, source.media_type)
    pages: list[PageText] = []
    for page_number in page_numbers:
        if page_number < 1 or page_number > len(texts):
            raise ValueError(f"page number outside source: {page_number}")
        text = texts[page_number - 1]
        pages.append(PageText(page_number=page_number, text=text, start=0, end=len(text)))
    return ReadPagesResult(source_id=source.id, pages=tuple(pages))


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
