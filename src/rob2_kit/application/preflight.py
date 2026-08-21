"""Bounded, deterministic source discovery before a Batch is captured."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import httpx
import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.registry import TrialFacts, http_request, match_registry
from rob2_kit.sources import SourceRole
from rob2_kit.storage import workspace_mutation_lock

from ._state import identity, read_json, record_uri, write_jsons
from .contracts import RecordKind, RecordReference


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorizedSourceRoot(_Closed):
    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    path: str = Field(min_length=1)
    trial_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PreflightLimits(_Closed):
    max_depth: int = Field(default=32, ge=1, le=256)
    max_visited_entries: int = Field(default=10000, ge=1, le=1_000_000)
    max_candidates: int = Field(default=1000, ge=1, le=100_000)
    max_file_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    max_total_bytes: int = Field(default=500 * 1024 * 1024, ge=1)
    max_extracted_pages: int = Field(default=5000, ge=1)
    max_registry_attempts: int = Field(default=1, ge=0, le=1)


PREFLIGHT_LIMITS = PreflightLimits()
RegistryRequest = Callable[[str], Mapping[str, object]]


class PreflightRequest(_Closed):
    roots: tuple[AuthorizedSourceRoot, ...] = Field(min_length=1)
    expected_head: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class RoleSuggestion(_Closed):
    role: SourceRole
    rule_id: str
    observed_facts: tuple[str, ...] = ()


class CandidateSource(_Closed):
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_id: str
    root_alias: str
    relative_path: str
    media_type: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    page_count: int = Field(default=0, ge=0)
    pages: tuple[str, ...] = ()
    duplicate_group: str | None = None
    suggestions: tuple[RoleSuggestion, ...] = ()
    condition: str | None = None


class CandidateInspection(_Closed):
    candidate: CandidateSource
    page: int | None = Field(default=None, ge=1)
    text: str | None = None
    hits: tuple[tuple[int, int], ...] = ()


class SourcePreflight(_Closed):
    kind: Literal["source_preflight"] = "source_preflight"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    roots: tuple[str, ...]
    candidates: tuple[CandidateSource, ...]
    conditions: tuple[str, ...] = ()
    registry_attempts: int = Field(ge=0)
    registry_outcomes: tuple[tuple[str, str], ...] = ()

    @property
    def reference(self) -> RecordReference:
        return RecordReference(
            kind=RecordKind.SOURCE_PREFLIGHT,
            identity=self.identity,
            uri=record_uri("source_preflight", self.identity),
        )


def verify_source_preflight(raw: object) -> SourcePreflight:
    """Validate the full closed catalog and its canonical identity."""
    if not isinstance(raw, dict) or set(raw) != {
        "kind", "identity", "roots", "candidates", "conditions", "registry_attempts", "registry_outcomes"
    }:
        raise ValueError("stored source preflight has an invalid shape")
    preflight = SourcePreflight.model_validate(raw)
    payload = {
        "roots": list(preflight.roots),
        "candidates": [item.model_dump(mode="json") for item in preflight.candidates],
        "conditions": list(preflight.conditions),
        "registry_attempts": preflight.registry_attempts,
        "registry_outcomes": [list(item) for item in preflight.registry_outcomes],
    }
    if identity(payload) != preflight.identity:
        raise ValueError("stored source preflight identity mismatch")
    return preflight


class PreflightLimitError(ValueError):
    """The catalog exceeded a fixed server-owned bound; no partial result exists."""


def _media(path: Path, data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        return "text/plain"
    if path.suffix.lower() == ".json":
        return "application/json"
    return "application/octet-stream"


def _extract(data: bytes, media: str) -> tuple[tuple[str, ...], str | None]:
    try:
        if media == "application/pdf":
            document = pymupdf.open(stream=data, filetype="pdf")
            try:
                pages = tuple(page.get_text() for page in document)
            finally:
                document.close()
            return pages, None if pages else "empty_pdf"
        if media in {"text/plain", "application/json"}:
            text = data.decode("utf-8")
            if media == "application/json":
                json.loads(text)
            return (text,), None
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError, pymupdf.FileDataError):
        return (), "unreadable"
    return (), "unsupported"


def _suggest(alias: str, relative: str, media: str) -> tuple[RoleSuggestion, ...]:
    name = Path(relative).name.casefold()
    facts: list[str] = [f"media_type={media}"]
    # Only the file's own name is considered.  Parent directory names are never
    # propagated as scientific role hints.
    if "protocol" in name:
        return (
            RoleSuggestion(
                role="protocol", rule_id="filename_protocol", observed_facts=tuple(facts)
            ),
        )
    if "sap" in name or "analysis" in name:
        return (
            RoleSuggestion(
                role="sap", rule_id="filename_analysis_plan", observed_facts=tuple(facts)
            ),
        )
    if "supp" in name or "appendix" in name:
        return (
            RoleSuggestion(
                role="supplement", rule_id="filename_supplement", observed_facts=tuple(facts)
            ),
        )
    if media == "application/pdf":
        return (
            RoleSuggestion(role="main_article", rule_id="pdf_default", observed_facts=tuple(facts)),
        )
    return (RoleSuggestion(role="other", rule_id="fallback_other", observed_facts=tuple(facts)),)


def _redirected(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return stat.S_ISLNK(mode) or bool(
            attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    except OSError:
        return False


def _root_path(workspace: Path, requested: str) -> Path:
    requested_path = Path(requested)
    if requested_path.is_absolute() or ".." in requested_path.parts:
        raise ValueError("authorized root escapes workspace")
    path = workspace / requested_path
    probe = workspace
    for part in requested_path.parts:
        probe = probe / part
        if _redirected(probe):
            raise ValueError("authorized root is redirected")
    if not path.is_dir():
        raise ValueError("authorized root is not a directory")
    return path


def preflight_sources(
    workspace: str | Path,
    request: PreflightRequest,
    *,
    persist: bool = True,
    registry_request: RegistryRequest | None = None,
) -> SourcePreflight:
    workspace_path = Path(workspace).resolve(strict=True)
    previous = read_json(workspace_path, "state.json")
    current_head = None if previous is None else previous.get("preflight_identity")
    if request.expected_head is not None and request.expected_head != current_head:
        raise ValueError("stale preflight head")
    limits = PREFLIGHT_LIMITS
    candidates: list[CandidateSource] = []
    conditions: list[str] = []
    visited = 0
    total_bytes = 0
    pages_seen = 0
    seen_digests: Counter[str] = Counter()
    for root in sorted(request.roots, key=lambda item: item.alias):
        base = _root_path(workspace_path, root.path)
        stack: list[tuple[Path, int]] = [(base, 0)]
        while stack:
            directory, depth = stack.pop()
            if depth > limits.max_depth:
                raise PreflightLimitError("preflight maximum nesting exceeded")
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
            except OSError:
                conditions.append(f"unreadable_directory:{root.alias}:{directory.name}")
                continue
            for entry in entries:
                visited += 1
                if visited > limits.max_visited_entries:
                    raise PreflightLimitError("preflight visited-entry limit exceeded")
                relative = (Path(entry.path).relative_to(base)).as_posix()
                if relative == ".rob2-kit" or relative.startswith(".rob2-kit/"):
                    continue
                path = Path(entry.path)
                if _redirected(path):
                    conditions.append(f"unsafe_redirect:{root.alias}:{relative}")
                    continue
                try:
                    mode = os.lstat(path).st_mode
                    if stat.S_ISDIR(mode):
                        stack.append((path, depth + 1))
                        continue
                    if not stat.S_ISREG(mode):
                        conditions.append(f"special_entry:{root.alias}:{relative}")
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    conditions.append(f"unreadable_entry:{root.alias}:{relative}")
                    continue
                if size > limits.max_file_bytes:
                    conditions.append(f"file_too_large:{root.alias}:{relative}")
                    continue
                total_bytes += size
                if total_bytes > limits.max_total_bytes:
                    raise PreflightLimitError("preflight total-byte limit exceeded")
                try:
                    data = path.read_bytes()
                except OSError:
                    conditions.append(f"unreadable_file:{root.alias}:{relative}")
                    continue
                digest = "sha256:" + hashlib.sha256(data).hexdigest()
                media = _media(path, data)
                pages, condition = _extract(data, media)
                pages_seen += len(pages)
                if pages_seen > limits.max_extracted_pages:
                    raise PreflightLimitError("preflight extraction limit exceeded")
                candidate_identity = identity(
                    {
                        "alias": root.alias,
                        "path": relative,
                        "media": media,
                        "size": size,
                        "sha256": digest,
                    }
                )
                candidate = CandidateSource(
                    identity=candidate_identity,
                    trial_id=root.trial_id,
                    root_alias=root.alias,
                    relative_path=relative,
                    media_type=media,
                    size=size,
                    sha256=digest,
                    page_count=len(pages),
                    pages=pages,
                    suggestions=_suggest(root.alias, relative, media),
                    condition=condition,
                )
                candidates.append(candidate)
                if len(candidates) > limits.max_candidates:
                    raise PreflightLimitError("preflight candidate limit exceeded")
                seen_digests[digest] += 1
    duplicate_numbers = {
        digest: number
        for number, (digest, count) in enumerate(sorted(seen_digests.items()))
        if count > 1
    }
    if duplicate_numbers:
        candidates = [
            item.model_copy(
                update={"duplicate_group": f"duplicate-{duplicate_numbers[item.sha256]}"}
            )
            if item.sha256 in duplicate_numbers
            else item
            for item in candidates
        ]
    candidates.sort(
        key=lambda item: (item.root_alias, item.relative_path.casefold(), item.identity)
    )
    registry_outcomes: list[tuple[str, str]] = []
    if persist and limits.max_registry_attempts:
        trial_candidates: dict[str, list[CandidateSource]] = {}
        for item in candidates:
            trial_candidates.setdefault(item.trial_id, []).append(item)
        for trial_id in sorted({root.trial_id for root in request.roots}):
            trial_items = trial_candidates.get(trial_id)
            if not trial_items:
                conditions.append(f"registry_no_candidate:{trial_id}")
                continue
            article = next(
                (item for item in trial_items if item.media_type == "application/pdf"),
                trial_items[0],
            )
            text = "\n".join(article.pages)
            try:
                if registry_request is None:
                    with httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                        match = match_registry(
                            TrialFacts(), http_request(client), main_article_text=text
                        )
                else:
                    match = match_registry(TrialFacts(), registry_request, main_article_text=text)
                registry_outcomes.append((trial_id, match.status.value))
            except (httpx.HTTPError, ValueError):
                registry_outcomes.append((trial_id, "unavailable"))
                conditions.append(f"registry_unavailable:{trial_id}")
    elif not persist:
        prior_preflight = read_json(workspace_path, "preflight.json") or {}
        registry_outcomes = [
            (str(trial_id), str(status))
            for trial_id, status in prior_preflight.get("registry_outcomes", ())
        ]
    payload = {
        "roots": [item.alias for item in sorted(request.roots, key=lambda item: item.alias)],
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "conditions": sorted(set(conditions)),
        "registry_attempts": len(registry_outcomes),
        "registry_outcomes": registry_outcomes,
    }
    result = SourcePreflight(
        identity=identity(payload),
        roots=tuple(payload["roots"]),
        candidates=tuple(candidates),
        conditions=tuple(payload["conditions"]),
        registry_attempts=payload["registry_attempts"],
        registry_outcomes=tuple(registry_outcomes),
    )
    if persist:
        with workspace_mutation_lock(workspace_path):
            latest = read_json(workspace_path, "state.json")
            latest_head = None if latest is None else latest.get("preflight_identity")
            if request.expected_head is not None and request.expected_head != latest_head:
                raise ValueError("stale preflight head")
            state = latest or {}
            state.update({"phase": "intake", "preflight_identity": result.identity})
            write_jsons(
                workspace_path,
                {
                    "preflight.json": result.model_dump(mode="json"),
                    "roots.json": {
                        "roots": [
                            item.model_dump(mode="json")
                            for item in sorted(request.roots, key=lambda item: item.alias)
                        ]
                    },
                    "state.json": state,
                },
            )
    return result


def inspect_candidate_sources(
    workspace: str | Path,
    candidate: CandidateSource,
    *,
    query: str | None = None,
    page: int | None = None,
) -> CandidateInspection:
    """Return bounded frozen candidate content; this function cannot mint evidence."""
    preflight = read_json(workspace, "preflight.json")
    try:
        verified = None if preflight is None else verify_source_preflight(preflight)
    except (TypeError, ValueError):
        verified = None
    if verified is None:
        raise ValueError("active preflight is unavailable or corrupt")
    stored = (
        None
        if preflight is None
        else next(
            (
                CandidateSource.model_validate(item)
                for item in preflight.get("candidates", ())
                if item.get("identity") == candidate.identity
            ),
            None,
        )
    )
    if stored is None:
        raise ValueError("candidate is not in the active preflight")
    candidate = stored
    text = None
    if page is not None:
        if page > candidate.page_count:
            raise ValueError("page is outside candidate")
        text = candidate.pages[page - 1]
    hits: tuple[tuple[int, int], ...] = ()
    if query:
        haystack = candidate.pages[page - 1] if page is not None else "\n".join(candidate.pages)
        starts = []
        offset = 0
        while True:
            found = haystack.casefold().find(query.casefold(), offset)
            if found < 0:
                break
            starts.append((found, found + len(query)))
            offset = found + max(len(query), 1)
            if len(starts) >= 100:
                break
        hits = tuple(starts)
    return CandidateInspection(candidate=candidate, page=page, text=text, hits=hits)
