import base64
import binascii
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from bisect import bisect_right
from collections import Counter, OrderedDict
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, cast

import pymupdf
from rapidfuzz.distance import OSA

from ..models import canonical_json_bytes
from ..workflow_models import SearchReceiptHandle
from ._state import (
    _SEARCH_PROFILE,
    _canonical_query_text,
    _canonical_search_text,
    _create_search_fts,
    _db,
    _ensure,
    _identity,
    _normalized_text_with_spans,
    _ordered_sources,
    _projection_hash,
    _read,
    _root,
    _state,
    internal_path,
)
from .contracts import COUNTERS

MAIN_REPORT_TEXT_BUDGET = 65_536
_SEARCH_PREVIEW_MAX_BYTES = 512
_SEARCH_CANDIDATE_MAX_BYTES = 2_048
_TERM_FEEDBACK_MAX_TERMS = 16
_TERM_FEEDBACK_MAX_SOURCES = 64
_SOURCE_NAVIGATION_VERSION = "rob2-kit.source-navigation.v0.1"
_SOURCE_NAVIGATION_MAX_ENTRIES = 12
_SOURCE_NAVIGATION_MAX_TEXT = 512

_SEARCH_SESSION_VERSION = "rob2-kit.search-session.v0.9"
_SEARCH_CANDIDATE_VERSION = "rob2-kit.search-candidates.v0.9"
_SEARCH_NORMALIZATION_VERSION = "rob2-kit.search-normalization.v1"
_SEARCH_RANKING_VERSION = "fts5-bm25-scoped-page-source-tiebreak.v1"
_LEGACY_SEARCH_PROFILE = "legacy-default-v1"
_SEARCH_CORPUS_CACHE_MAX = 8
_SEARCH_RANKING_CACHE_MAX = 64
_SEARCH_PHASE_ORDER = {"proposal": 0, "assessment": 1, "ready_to_finalize": 2}

# These counters expose whether a request rebuilt and persisted a full scoped
# ranking. They are deliberately local to Evidence's disposable search cache.
COUNTERS.setdefault("search_ranking_builds", 0)
COUNTERS.setdefault("search_ranking_cache_writes", 0)
COUNTERS.setdefault("search_ranking_validations", 0)
COUNTERS.setdefault("search_cache_writes", 0)
COUNTERS.setdefault("search_ranking_cache_hits", 0)
COUNTERS.setdefault("search_ranking_recomputations", 0)
COUNTERS.setdefault("search_fts_corpus_builds", 0)
COUNTERS.setdefault("search_fts_corpus_cache_hits", 0)
COUNTERS.setdefault("search_spelling_catalogue_builds", 0)
COUNTERS.setdefault("search_spelling_catalogue_cache_hits", 0)

# The SQLite rows are the durable derivative, but rebuilding the scoped FTS
# ranking and every candidate on each warm request is needless work.  This
# process-local cache is deliberately keyed by the workspace and immutable
# session identity: a restart still validates and rebuilds from the durable
# rows, while repeated calls in one host process reuse the verified result.
_SEARCH_RANKING_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_SEARCH_CORPUS_CACHE: OrderedDict[
    tuple[str, str, tuple[tuple[str, str], ...]], sqlite3.Connection
] = OrderedDict()
_SEARCH_SPELLING_CATALOGUE_CACHE: OrderedDict[
    tuple[str, str, tuple[tuple[str, str], ...]],
    tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]]],
] = OrderedDict()
_SEARCH_CORPUS_LOCK = RLock()
_SEARCH_CORPUS_LEASES: dict[int, int] = {}
_SEARCH_CORPUS_KEYS: dict[int, tuple[str, str, tuple[tuple[str, str], ...]]] = {}
_SEARCH_CORPUS_RETIRED: dict[int, sqlite3.Connection] = {}


def reset_search_caches() -> None:
    """Drop disposable process-local search caches without touching durable data."""

    with _SEARCH_CORPUS_LOCK:
        connections = {
            id(connection): connection
            for connection in (*_SEARCH_CORPUS_CACHE.values(), *_SEARCH_CORPUS_RETIRED.values())
        }
        _SEARCH_RANKING_CACHE.clear()
        _SEARCH_SPELLING_CATALOGUE_CACHE.clear()
        _SEARCH_CORPUS_CACHE.clear()
        _SEARCH_CORPUS_RETIRED.clear()
        _SEARCH_CORPUS_LEASES.clear()
        _SEARCH_CORPUS_KEYS.clear()
        for connection in connections.values():
            connection.close()
    _cached_normalized_search_text.cache_clear()


def list_sources(
    workspace: str | Path,
    trial_id: str | None = None,
    source_id: str | None = None,
    cursor: str | None = None,
    limit: int = _SOURCE_NAVIGATION_MAX_ENTRIES,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    batch = _read(root, "batch") or {}
    trials = batch.get("trials", [])
    if trial_id is None:
        if len(trials) != 1:
            raise ValueError("trial_id is required unless the Batch has exactly one captured Trial")
        trial = trials[0]
    else:
        trial = next((item for item in trials if item["id"] == trial_id), None)
        if trial is None:
            raise ValueError("unknown captured Trial ID")
    sources = _ordered_sources(trial["sources"])
    if source_id is None and cursor is not None:
        raise ValueError("source_navigation_cursor_invalid: source_id is required")
    navigation = None
    if source_id is not None:
        source = next((item for item in sources if item["id"] == source_id), None)
        if source is None:
            raise ValueError("source is outside the active Trial")
        verified = _verified_source_projections(root, {(trial["id"], source_id)})
        _, pages = verified[(trial["id"], source_id)]
        navigation = _source_navigation(
            source,
            pages,
            cursor=cursor,
            limit=limit,
        )
    conditions = [
        condition
        for condition in batch.get("conditions", [])
        if condition.get("trial_id") == trial["id"]
    ]
    result: dict[str, Any] = {
        "outcome": "success",
        "sources": sources,
        "conditions": conditions,
        "omissions": trial.get("omissions", []),
    }
    if navigation is not None:
        result["navigation"] = navigation
    return result


def _source_navigation(
    source: dict[str, Any],
    pages: tuple[str, ...],
    *,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """Return bounded literal navigation over one verified persisted projection."""

    entries = _source_navigation_entries(pages)
    offset = 0
    if cursor is not None:
        payload = _decode_source_navigation_cursor(cursor)
        if (
            payload.get("source_id") != source.get("id")
            or payload.get("projection_hash") != source.get("projection_hash")
            or payload.get("version") != _SOURCE_NAVIGATION_VERSION
        ):
            raise ValueError("source_navigation_cursor_stale: source or projection changed")
        offset = payload["offset"]
        if offset < 0 or offset > len(entries):
            raise ValueError("source_navigation_cursor_expired: request the first page")
    bounded_limit = max(1, min(limit, _SOURCE_NAVIGATION_MAX_ENTRIES))
    selected = entries[offset : offset + bounded_limit]
    next_offset = offset + len(selected)
    has_more = next_offset < len(entries)
    unreadable_pages = [page for page, text in enumerate(pages, 1) if not text.strip()]
    return {
        "source_id": source["id"],
        "projection_hash": source["projection_hash"],
        "navigation_version": _SOURCE_NAVIGATION_VERSION,
        "entries": selected,
        "total_entries": len(entries),
        "returned_entries": len(selected),
        "remaining_entries": len(entries) - next_offset,
        "terminal": not has_more,
        "page_count": len(pages),
        "pages_examined": len(pages),
        "pages_without_text_projection": unreadable_pages,
        "unreadable_pages": unreadable_pages,
        "truncated": has_more,
        "next_cursor": (_source_navigation_cursor(source, next_offset) if has_more else None),
        "condition": "no_text_projection" if not entries else None,
    }


def _source_navigation_cursor(source: dict[str, Any], offset: int) -> str:
    payload = {
        "offset": offset,
        "projection_hash": source["projection_hash"],
        "source_id": source["id"],
        "version": _SOURCE_NAVIGATION_VERSION,
    }
    encoded = base64.urlsafe_b64encode(canonical_json_bytes(payload)).decode("ascii")
    return "sn1." + encoded.rstrip("=")


def _decode_source_navigation_cursor(cursor: str) -> dict[str, Any]:
    if not cursor.startswith("sn1."):
        raise ValueError("source_navigation_cursor_invalid: unsupported cursor")
    encoded = cursor[4:]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("source_navigation_cursor_invalid: malformed cursor") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"offset", "projection_hash", "source_id", "version"}
        or not isinstance(payload["offset"], int)
        or isinstance(payload["offset"], bool)
        or not isinstance(payload["projection_hash"], str)
        or not isinstance(payload["source_id"], str)
        or payload["version"] != _SOURCE_NAVIGATION_VERSION
    ):
        raise ValueError("source_navigation_cursor_invalid: incomplete cursor")
    return payload


def _source_navigation_entries(pages: tuple[str, ...]) -> list[dict[str, Any]]:
    """Index literal headings, leads, and cross-references without inferring meaning."""

    page_lines = [page.splitlines() for page in pages]
    first_lines = [
        next((line.strip() for line in lines if line.strip()), "") for lines in page_lines
    ]
    repeated = Counter(line for line in first_lines if line)
    repeated_furniture = {line for line, count in repeated.items() if count >= 2}
    page_marker = re.compile(r"^(?:page\s+\d+(?:\s+of\s+\d+)?|version\s+\S+)$", re.I)
    numbered_heading = re.compile(r"^(?:\d+[.)]\s*|\d+(?:\.\d+)+\s+)[A-Z][^.!?:;]{0,119}$")
    contents_row = re.compile(r"^.{2,180}?\.{2,}\s*\d{1,4}\s*$")
    date_pattern = re.compile(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
        r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4}|(?:January|February|March|April|May|June|"
        r"July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})\b",
        re.I,
    )
    cross_reference = re.compile(
        r"\b(?:see|refer\s+to|described\s+in|reported\s+in|according\s+to)\s+"
        r"(?:section|subsection|appendix|table|figure|page|pages|the\s+protocol|the\s+sap)\b",
        re.I,
    )
    version_lead = re.compile(
        r"\b(?:version|revision|edition|amendment|protocol\s+version|sap\s+version)\b|"
        r"\bv\d+(?:\.\d+)*\b",
        re.I,
    )
    entries: list[dict[str, Any]] = []
    for page_number, lines in enumerate(page_lines, 1):
        useful: list[tuple[int, str]] = []
        for line_number, raw in enumerate(lines, 1):
            text = raw.strip()
            if (
                not text
                or (page_marker.fullmatch(text) and version_lead.search(text) is None)
                or text in repeated_furniture
            ):
                continue
            useful.append((line_number, text))
        if useful:
            start_line, excerpt = useful[0]
            excerpt_lines = [(start_line, excerpt)]
            for candidate_line, candidate_text in useful[1:]:
                if candidate_line > start_line + 4:
                    break
                joined = " ".join(
                    text for _, text in (*excerpt_lines, (candidate_line, candidate_text))
                )
                if len(joined) > _SOURCE_NAVIGATION_MAX_TEXT:
                    break
                excerpt_lines.append((candidate_line, candidate_text))
            entries.append(
                {
                    "text": " ".join(text for _, text in excerpt_lines),
                    "page": page_number,
                    "start_line": start_line,
                    "end_line": excerpt_lines[-1][0],
                    "kind": "page_excerpt",
                }
            )
        for line_number, text in useful:
            lowered = text.casefold()
            is_contents = (
                lowered in {"contents", "table of contents"}
                or contents_row.fullmatch(text) is not None
            )
            is_version = version_lead.search(text) is not None
            is_cross_reference = cross_reference.search(text) is not None
            date_match = date_pattern.search(text)
            if is_contents:
                entries.append(
                    {
                        "text": text,
                        "page": page_number,
                        "start_line": line_number,
                        "end_line": line_number,
                        "kind": "contents_lead",
                    }
                )
            if is_version:
                entries.append(
                    {
                        "text": text,
                        "page": page_number,
                        "start_line": line_number,
                        "end_line": line_number,
                        "kind": "version_lead",
                    }
                )
            if date_match is not None:
                date_kind = next(
                    (
                        kind
                        for words, kind in (
                            (("capture", "captured"), "capture"),
                            (("version", "revision", "edition"), "version"),
                            (("amend", "amended"), "amendment"),
                            (("cutoff", "cut-off", "last data"), "cutoff"),
                            (("template", "form"), "template"),
                        )
                        if any(word in lowered for word in words)
                    ),
                    None,
                )
                item = {
                    "text": text,
                    "page": page_number,
                    "start_line": line_number,
                    "end_line": line_number,
                    "kind": "date_lead",
                }
                if date_kind is not None:
                    item["date_kind"] = date_kind
                entries.append(item)
            if is_cross_reference:
                entries.append(
                    {
                        "text": text,
                        "page": page_number,
                        "start_line": line_number,
                        "end_line": line_number,
                        "kind": "cross_reference_lead",
                    }
                )
        for line_number, text in useful:
            if len(text) > 120 or text.endswith((".", ":", ";", "?", "!")):
                continue
            if "@" in text or ";" in text:
                continue
            blank_before = line_number == 1 or not lines[line_number - 2].strip()
            blank_after = line_number == len(lines) or not lines[line_number].strip()
            if numbered_heading.fullmatch(text):
                if not (blank_before or blank_after):
                    continue
            elif not (blank_before and blank_after and len(text.split()) <= 10):
                continue
            entries.append(
                {
                    "text": text,
                    "page": page_number,
                    "start_line": line_number,
                    "end_line": line_number,
                    "kind": "heading_candidate",
                }
            )
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    metadata_kinds = {
        "contents_lead",
        "version_lead",
        "date_lead",
        "cross_reference_lead",
    }
    for item in entries:
        key = (
            item["page"],
            item["start_line"],
            item["end_line"],
            item["kind"],
            item["text"],
        )
        unique.setdefault(key, item)
    ordered = sorted(
        unique.values(), key=lambda item: (item["page"], item["start_line"], item["kind"])
    )
    metadata_locations = {
        (item["page"], item["start_line"], item["end_line"], item["text"])
        for item in ordered
        if item["kind"] in metadata_kinds
    }
    ordered = [
        item
        for item in ordered
        if item["kind"] != "page_excerpt"
        or (
            item["page"],
            item["start_line"],
            item["end_line"],
            item["text"],
        )
        not in metadata_locations
    ]
    # Keep the complete deterministic index here.  ``_source_navigation`` is
    # the transport boundary and is the only place that should apply the
    # response limit; truncating this list would make late sections
    # unreachable while reporting a false terminal page.
    return sorted(ordered, key=lambda item: (item["page"], item["start_line"], item["kind"]))


def _verified_source_projections(
    root: Path, requested: set[tuple[str, str]]
) -> dict[tuple[str, str], tuple[dict[str, Any], tuple[str, ...]]]:
    """Resolve and verify a small Source set in one derivative read pass."""
    if not requested:
        return {}
    batch = _read(root, "batch") or {}
    # The Batch is the authority for Source metadata.  ``source_index`` is a
    # disposable lookup cache, not a second authority: accepting its payload
    # here would let a tampered derivative redefine the bytes and projection
    # that later Evidence operations trust.
    authoritative: dict[tuple[str, str], dict[str, Any]] = {}
    for trial in batch.get("trials", []):
        for source in trial.get("sources", []):
            key = (trial.get("id"), source.get("id"))
            if key in requested:
                authoritative[key] = source
    missing = requested - set(authoritative)
    if missing:
        raise ValueError("source is outside the active Trial")

    with _db(root, "derivative.sqlite3") as connection:
        placeholders = ",".join("?" for _ in requested)
        indexed_rows = connection.execute(
            "SELECT source_id,batch_id,trial_id,payload FROM source_index "
            f"WHERE source_id IN ({placeholders})",
            tuple(source_id for _, source_id in sorted(requested)),
        ).fetchall()
        page_rows = connection.execute(
            "SELECT source_id,page,text FROM pages "
            f"WHERE source_id IN ({placeholders}) ORDER BY source_id,page",
            tuple(source_id for _, source_id in sorted(requested)),
        ).fetchall()

    indexed = {str(row[0]): row for row in indexed_rows}
    pages_by_source: dict[str, list[Any]] = {}
    for row in page_rows:
        pages_by_source.setdefault(str(row[0]), []).append(row)

    verified: dict[tuple[str, str], tuple[dict[str, Any], tuple[str, ...]]] = {}
    for key, source in authoritative.items():
        trial_id, source_id = key
        cached = indexed.get(source_id)
        if cached is not None:
            try:
                indexed_source = json.loads(bytes(cached[3]))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("source index payload is corrupt") from error
            if (
                cached[1] != batch.get("identity")
                or cached[2] != trial_id
                or not isinstance(indexed_source, dict)
                or indexed_source.get("id") != source_id
                or canonical_json_bytes(indexed_source) != canonical_json_bytes(source)
            ):
                raise ValueError("source index payload is stale or corrupt")
        path = internal_path(root, "sources", trial_id, f"{source_id}.bin")
        if not path.is_file():
            raise ValueError("captured Source bytes are unavailable")
        data = path.read_bytes()
        COUNTERS["source_bytes_hashed"] += len(data)
        if "sha256:" + hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("captured Source bytes do not match Canonical identity")
        # Intake (or an explicit derivative rebuild) owns extraction.  Normal
        # Evidence operations verify the persisted projection instead of
        # reopening and parsing the captured PDF on every call.
        source_pages = pages_by_source.get(source_id, [])
        COUNTERS["projection_rows_read"] += len(source_pages)
        page_numbers = tuple(row[1] for row in source_pages)
        if any(not isinstance(row[2], str) for row in source_pages):
            raise ValueError("captured Source page text is corrupt")
        pages = tuple(row[2] for row in source_pages)
        media_type = source.get("media_type", "text/plain")
        if _projection_hash(source["sha256"], media_type, pages) != source.get("projection_hash"):
            raise ValueError("captured Source projection identity is corrupt")
        page_count = source.get("page_count")
        if (
            not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or len(pages) != page_count
            or not pages
            or page_numbers != tuple(range(1, page_count + 1))
        ):
            raise ValueError("captured Source page count is corrupt")
        verified[key] = (source, pages)
    COUNTERS["source_projection_verifications"] += len(verified)
    return verified


def _find_source(root: Path, trial_id: str, source_id: str) -> dict[str, Any]:
    return _verified_source_projections(root, {(trial_id, source_id)})[(trial_id, source_id)][0]


def _broad_search_diagnostic(
    *,
    trial_id: str,
    normalized_query: str,
    mode: str,
    source_id: str | None,
    limit: int,
    total_matches: int,
    candidate_count: int,
    returned_count: int,
    truncated: bool,
    next_cursor: str | None,
    purpose_domain_id: str | None = None,
    purpose_question_id: str | None = None,
) -> dict[str, Any] | None:
    """Describe only observable breadth/truncation facts and one next call."""

    terms = tuple(term for term in normalized_query.split() if term)
    if mode != "any" or not truncated or not total_matches:
        return None
    action = {
        "kind": "continue",
        "operation": "search_sources",
        "trial_id": trial_id,
        "query": normalized_query,
        "mode": "any",
        "source_id": source_id,
        "limit": limit,
        "cursor": next_cursor,
    }
    if purpose_domain_id is not None:
        action["purpose_domain_id"] = purpose_domain_id
        action["purpose_question_id"] = purpose_question_id
    return {
        "code": "broad_any_truncated",
        "mode": mode,
        "profile": _SEARCH_PROFILE,
        "normalized_term_count": len(terms),
        "total_matches": total_matches,
        "candidate_count": candidate_count,
        "returned_count": returned_count,
        "detail": (
            "This any search matched the reported pages and its ranking is truncated. "
            "Continue this same query and mode if more ranked passages could resolve the "
            "current question, then inspect the passages."
        ),
        "next_action": action,
    }


def _no_hits_diagnostic(
    *,
    normalized_query: str,
    mode: str,
    total_matches: int,
    returned_count: int,
) -> dict[str, Any] | None:
    """Report the exact lexical condition that produced an initial zero-hit result."""

    if total_matches != 0 or returned_count != 0:
        return None
    descriptions = {
        "all": "every normalized query term on the same page",
        "phrase": "the normalized query terms as one contiguous phrase",
        "any": "at least one normalized query term on a page",
        "prefix": "a page containing a token that starts with a normalized query term",
        "literal": "the exact contiguous presentation-normalized wording",
    }
    return {
        "code": "no_hits",
        "mode": mode,
        "profile": _SEARCH_PROFILE,
        "normalized_term_count": len(normalized_query.split()),
        "total_matches": total_matches,
        "candidate_count": 0,
        "returned_count": returned_count,
        "detail": (
            f"This {mode} query matched no captured text: no page satisfied "
            f"{descriptions[mode]}. Zero hits establish only that this issued lexical "
            "query matched nothing; they do not establish that the underlying method or fact "
            "is absent. Compare per-term counts with the complete-query count, inspect the "
            "relevant Source section, or reformulate using wording found in the Source."
        ),
        "next_action": None,
    }


def _source_navigation_diagnostic(
    diagnostic: dict[str, Any] | None,
    *,
    source: dict[str, Any] | None,
    pages: tuple[str, ...] | None,
    trial_id: str,
) -> dict[str, Any] | None:
    """Attach literal source navigation to a scoped lexical miss."""

    if diagnostic is None or diagnostic.get("code") != "no_hits" or source is None or pages is None:
        return diagnostic
    navigation = _source_navigation(
        source,
        pages,
        cursor=None,
        limit=_SOURCE_NAVIGATION_MAX_ENTRIES,
    )
    diagnostic["navigation"] = navigation
    diagnostic["next_action"] = (
        {
            "kind": "navigate",
            "operation": "list_sources",
            "trial_id": trial_id,
            "source_id": source["id"],
            "limit": _SOURCE_NAVIGATION_MAX_ENTRIES,
            "cursor": navigation["next_cursor"],
        }
        if navigation["next_cursor"] is not None
        else None
    )
    diagnostic["detail"] = (
        f"This scoped {diagnostic['mode']} query matched no captured text. Inspect the "
        "literal heading and leading-page navigation entries below, then read the cited "
        "Source pages or reformulate with wording found there. Zero hits establish only "
        "that the issued lexical query matched no captured text."
    )
    return diagnostic


def search_sources(
    workspace: str | Path,
    trial_id: str,
    query: str,
    mode: str = "any",
    limit: int = 10,
    source_id: str | None = None,
    cursor: str | None = None,
    purpose_domain_id: str | None = None,
    purpose_question_id: str | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    requested_source_id = source_id
    valid_modes = {"all", "phrase", "any", "prefix", "literal"}
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(mode, str) or mode not in valid_modes:
        raise ValueError("unknown lexical mode")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("search limit must be between 1 and 100")
    if purpose_domain_id is not None and (
        not isinstance(purpose_domain_id, str)
        or purpose_domain_id
        not in {
            "domain:randomization",
            "domain:deviations",
            "domain:missing",
            "domain:measurement",
            "domain:selection",
        }
    ):
        raise ValueError("unknown search purpose Domain")
    if purpose_question_id is not None and (
        not isinstance(purpose_question_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", purpose_question_id) is None
    ):
        raise ValueError("invalid search purpose question")
    if purpose_question_id is not None and purpose_domain_id is None:
        raise ValueError("question search purpose requires a Domain")
    if purpose_question_id is not None:
        from ..packs.scientific import SCIENTIFIC_PACK

        question = next(
            (item for item in SCIENTIFIC_PACK.questions if item.id == purpose_question_id), None
        )
        if question is None or question.domain_id != purpose_domain_id:
            raise ValueError("search purpose question is outside the selected Domain")
    normalized_query = (
        _canonical_search_text(query).casefold()
        if mode == "literal"
        else _canonical_query_text(query)
    )
    terms = [term for term in normalized_query.split() if term]
    if not terms:
        raise ValueError("query must not be empty")
    sources = list_sources(workspace, trial_id)["sources"]
    if source_id is not None:
        sources = [source for source in sources if source["id"] == source_id]
        if not sources:
            raise ValueError("source is outside the active Trial")
    # FTS is a derivative projection, not evidence in its own right.  Verify
    # every projection this query is about to trust once before reading it.
    # This also makes a damaged FTS cache fail closed instead of returning
    # plausible-looking stale text.
    verified = _verified_source_projections(root, {(trial_id, source["id"]) for source in sources})
    allowed = {source["id"] for source in sources}
    bounded_limit = max(1, min(limit, 100))
    # Scope ranking to the verified Trial pages.  The persistent FTS cache is
    # checked below for integrity, but its corpus also contains other Trials;
    # using it for BM25 would make a receipt depend on unrelated documents.
    if not allowed:
        session_spec = {
            "version": _SEARCH_SESSION_VERSION,
            "candidate_version": _SEARCH_CANDIDATE_VERSION,
            "normalization": _SEARCH_NORMALIZATION_VERSION,
            "ranking_version": _SEARCH_RANKING_VERSION,
            "trial_id": trial_id,
            "sources": [],
            "query": " ".join(terms),
            "normalized_query": " ".join(terms),
            "mode": mode,
            "profile": _SEARCH_PROFILE,
            "ranking": _SEARCH_RANKING_VERSION,
        }
        session_identity = _identity(session_spec)
        session_handle = _session_handle(session_identity)
        session_payload = {
            "identity": session_identity,
            "handle": session_handle,
            "spec": session_spec,
            "matching_page_count": 0,
            "candidate_count": 0,
            "complete": True,
            "ranked_pages": [],
            "term_feedback": [],
        }
        with _db(root, "derivative.sqlite3") as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO search_sessions VALUES (?,?)",
                (session_identity, canonical_json_bytes(session_payload)),
            ).rowcount
        COUNTERS["search_cache_writes"] += inserted
        receipt = {
            "trial_id": trial_id,
            "sources": [],
            "query": query,
            "normalized_query": " ".join(terms),
            "mode": mode,
            "profile": _SEARCH_PROFILE,
            "purpose_domain_id": purpose_domain_id,
            "purpose_question_id": purpose_question_id,
            "hits": [],
            "limit": bounded_limit,
            "total_matches": 0,
            "truncated": False,
            "condition": "no_hits",
            "batch_identity": (_read(root, "batch") or {}).get("identity"),
            "session_id": session_identity,
            "session_handle": session_handle,
            "candidate_count": 0,
            "matching_page_count": 0,
            "ranking_complete": True,
            "returned_rank_start": None,
            "returned_rank_end": None,
            "next_cursor": None,
            "exhausted": True,
            "returned_material": 0,
            "returned_candidates": [],
        }
        receipt["identity"] = _identity(receipt)
        receipt["handle"] = "sr_" + receipt["identity"].removeprefix("sha256:")[:16]
        with _db(root, "derivative.sqlite3") as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO search_receipts VALUES (?,?)",
                (receipt["identity"], canonical_json_bytes(receipt)),
            ).rowcount
        COUNTERS["search_cache_writes"] += inserted
        diagnostic = _no_hits_diagnostic(
            normalized_query=" ".join(terms),
            mode=mode,
            total_matches=0,
            returned_count=0,
        )
        return {
            "outcome": "success",
            "hits": [],
            "query": query,
            "mode": mode,
            "profile": _SEARCH_PROFILE,
            "total_matches": 0,
            "truncated": False,
            "condition": "no_hits",
            "search_receipt": receipt,
            "session_id": session_identity,
            "session_handle": session_handle,
            "matching_page_count": 0,
            "candidate_count": 0,
            "distinct_passage_count": 0,
            "distinct_page_count": 0,
            "distinct_source_count": 0,
            "ranking_complete": True,
            "returned_rank_start": None,
            "returned_rank_end": None,
            "next_cursor": None,
            "exhausted": True,
            "term_feedback": [],
            "term_feedback_truncated": False,
            "term_feedback_sources_truncated": False,
            "diagnostic": diagnostic,
            "purpose_domain_id": purpose_domain_id,
            "purpose_question_id": purpose_question_id,
            "spelling_suggestions": [],
            "spelling_suggestions_incomplete": False,
        }
    ordered_sources = _ordered_sources(sources)
    ordered_source_ids = [str(source["id"]) for source in ordered_sources]
    feedback_source_ids = ordered_source_ids[:_TERM_FEEDBACK_MAX_SOURCES]
    term_feedback_sources_truncated = len(ordered_source_ids) > _TERM_FEEDBACK_MAX_SOURCES
    placeholders = ",".join("?" for _ in allowed)
    with _db(root, "derivative.sqlite3") as connection:
        cached_rows = connection.execute(
            "SELECT source_id,page,raw_text,normalized_text FROM pages_fts "
            f"WHERE source_id IN ({placeholders}) ORDER BY source_id,page",
            tuple(sorted(allowed)),
        ).fetchall()
        COUNTERS["fts_rows_read"] += len(cached_rows)
        expected_rows = [
            (source_id, page, *_discovery_search_derivative(text))
            for source_id in sorted(allowed)
            for page, text in enumerate(verified[(trial_id, source_id)][1], 1)
        ]
        if [tuple(row) for row in cached_rows] != expected_rows:
            raise ValueError("text search projection is corrupt")
    page_map = {source_id: verified[(trial_id, source_id)][1] for source_id in ordered_source_ids}
    scope_key, search_corpus = _search_corpus(root, ordered_sources, page_map)
    feedback_terms = list(dict.fromkeys(terms))
    session_spec = {
        "version": _SEARCH_SESSION_VERSION,
        "candidate_version": _SEARCH_CANDIDATE_VERSION,
        "normalization": _SEARCH_NORMALIZATION_VERSION,
        "ranking_version": _SEARCH_RANKING_VERSION,
        "trial_id": trial_id,
        "sources": [
            {"id": source["id"], "projection_hash": source["projection_hash"]}
            for source in ordered_sources
        ],
        "query": " ".join(terms),
        "normalized_query": " ".join(terms),
        "mode": mode,
        "profile": _SEARCH_PROFILE,
        "ranking": _SEARCH_RANKING_VERSION,
    }
    session_identity = _identity(session_spec)
    session_handle = _session_handle(session_identity)
    cache_key = (str(root), session_identity)
    with _db(root, "derivative.sqlite3") as connection:
        existing_session = connection.execute(
            "SELECT payload FROM search_sessions WHERE identity=?", (session_identity,)
        ).fetchone()
    candidates: list[dict[str, Any]] = []
    all_pairs: list[tuple[str, int]] = []
    term_feedback: list[dict[str, Any]] = []
    term_feedback_truncated = len(feedback_terms) > _TERM_FEEDBACK_MAX_TERMS
    term_feedback_sources_truncated = len(ordered_source_ids) > _TERM_FEEDBACK_MAX_SOURCES
    if existing_session is not None:
        try:
            stored = json.loads(bytes(existing_session[0]))
            if (
                not isinstance(stored, dict)
                or set(stored)
                != {
                    "identity",
                    "handle",
                    "spec",
                    "matching_page_count",
                    "candidate_count",
                    "complete",
                    "ranked_pages",
                    "term_feedback",
                }
                or stored.get("spec") != session_spec
                or stored.get("identity") != session_identity
                or stored.get("handle") != session_handle
                or stored.get("complete") is not True
                or not isinstance(stored.get("matching_page_count"), int)
                or isinstance(stored.get("matching_page_count"), bool)
                or not isinstance(stored.get("candidate_count"), int)
                or isinstance(stored.get("candidate_count"), bool)
                or not isinstance(stored.get("term_feedback"), list)
            ):
                raise ValueError("search session configuration is stale")
            with _db(root, "derivative.sqlite3") as connection:
                candidate_rows = connection.execute(
                    "SELECT payload FROM search_candidates WHERE session_identity=? ORDER BY rank",
                    (session_identity,),
                ).fetchall()
            candidates = [json.loads(bytes(row[0])) for row in candidate_rows]
            term_feedback = stored["term_feedback"]
            if len(candidates) != stored["candidate_count"]:
                raise ValueError("search session candidate count is stale")
            ranked_pages = stored["ranked_pages"]
            if (
                not isinstance(ranked_pages, list)
                or len(ranked_pages) != stored["matching_page_count"]
            ):
                raise ValueError("search session ranking is incomplete")
            all_pairs = []
            for page_entry in ranked_pages:
                if (
                    not isinstance(page_entry, dict)
                    or set(page_entry) != {"source_id", "page"}
                    or not isinstance(page_entry.get("source_id"), str)
                    or page_entry["source_id"] not in page_map
                    or not isinstance(page_entry.get("page"), int)
                    or isinstance(page_entry.get("page"), bool)
                    or not 1 <= page_entry["page"] <= len(page_map[page_entry["source_id"]])
                ):
                    raise ValueError("search session ranking is corrupt")
                all_pairs.append((page_entry["source_id"], page_entry["page"]))
            if len(all_pairs) != len(set(all_pairs)):
                raise ValueError("search session ranking contains duplicate pages")
            with _SEARCH_CORPUS_LOCK:
                cached_projection = _SEARCH_RANKING_CACHE.pop(cache_key, None)
                if cached_projection is not None:
                    _SEARCH_RANKING_CACHE[cache_key] = cached_projection
            COUNTERS["search_ranking_validations"] += 1
            if cached_projection is not None:
                try:
                    cached_pairs = cached_projection["all_pairs"]
                    cached_feedback = cached_projection["term_feedback"]
                    cached_candidates = cached_projection["candidates"]
                    if all_pairs != cached_pairs:
                        raise ValueError("search session ranking is stale or corrupt")
                    if term_feedback != cached_feedback:
                        raise ValueError("search session term feedback is stale or corrupt")
                    if candidates != cached_candidates:
                        raise ValueError("search session candidates are stale or corrupt")
                    COUNTERS["search_ranking_cache_hits"] += 1
                finally:
                    # A warm ranking hit does not enter the recomputation
                    # helper, so release the corpus lease here.
                    _release_search_corpus(search_corpus)
            else:
                # A process restart drops only this disposable cache.  Rebuild
                # from the verified durable session and source projections,
                # then repopulate it without changing the session identity.
                COUNTERS["search_ranking_recomputations"] += 1
                expected_all_pairs, expected_term_pages = _recomputed_search_projection(
                    page_map,
                    normalized_query,
                    mode,
                    ordered_source_ids,
                    tuple(feedback_terms[:_TERM_FEEDBACK_MAX_TERMS]),
                    connection=search_corpus,
                )
                if all_pairs != expected_all_pairs:
                    raise ValueError("search session ranking is stale or corrupt")
                expected_term_feedback = _term_page_feedback(
                    page_map,
                    feedback_terms[:_TERM_FEEDBACK_MAX_TERMS],
                    feedback_source_ids,
                    expected_all_pairs,
                    expected_term_pages,
                )
                if term_feedback != expected_term_feedback:
                    raise ValueError("search session term feedback is stale or corrupt")
                expected_candidates = _session_candidates(
                    page_map, normalized_query, mode, ordered_source_ids, expected_all_pairs
                )
                if candidates != expected_candidates:
                    raise ValueError("search session candidates are stale or corrupt")
                with _SEARCH_CORPUS_LOCK:
                    _SEARCH_RANKING_CACHE[cache_key] = {
                        "all_pairs": list(all_pairs),
                        "term_feedback": json.loads(json.dumps(term_feedback)),
                        "candidates": json.loads(json.dumps(candidates)),
                    }
                    while len(_SEARCH_RANKING_CACHE) > _SEARCH_RANKING_CACHE_MAX:
                        _SEARCH_RANKING_CACHE.popitem(last=False)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
            raise ValueError("search session derivative is corrupt; restart the search") from error
        except (TypeError, AttributeError) as error:
            raise ValueError("search session derivative is corrupt; restart the search") from error
    else:
        COUNTERS["search_ranking_builds"] += 1
        all_pairs, term_pages = _recomputed_search_projection(
            page_map,
            normalized_query,
            mode,
            ordered_source_ids,
            tuple(feedback_terms[:_TERM_FEEDBACK_MAX_TERMS]),
            connection=search_corpus,
        )
        term_feedback = _term_page_feedback(
            page_map,
            feedback_terms[:_TERM_FEEDBACK_MAX_TERMS],
            feedback_source_ids,
            all_pairs,
            term_pages,
        )
        candidates = _session_candidates(
            page_map, normalized_query, mode, ordered_source_ids, all_pairs
        )
        session_payload = {
            "identity": session_identity,
            "handle": session_handle,
            "spec": session_spec,
            "matching_page_count": len(all_pairs),
            "candidate_count": len(candidates),
            "complete": True,
            "ranked_pages": [
                {"source_id": source_id, "page": page} for source_id, page in all_pairs
            ],
            "term_feedback": term_feedback,
        }
        with _db(root, "derivative.sqlite3") as connection:
            connection.execute(
                "INSERT OR REPLACE INTO search_sessions VALUES (?,?)",
                (session_identity, canonical_json_bytes(session_payload)),
            )
            connection.execute(
                "DELETE FROM search_candidates WHERE session_identity=?", (session_identity,)
            )
            connection.executemany(
                "INSERT INTO search_candidates VALUES (?,?,?)",
                [
                    (session_identity, item["rank"], canonical_json_bytes(item))
                    for item in candidates
                ],
            )
        with _SEARCH_CORPUS_LOCK:
            _SEARCH_RANKING_CACHE[cache_key] = {
                "all_pairs": list(all_pairs),
                "term_feedback": json.loads(json.dumps(term_feedback)),
                "candidates": json.loads(json.dumps(candidates)),
            }
            while len(_SEARCH_RANKING_CACHE) > _SEARCH_RANKING_CACHE_MAX:
                _SEARCH_RANKING_CACHE.popitem(last=False)
        COUNTERS["search_ranking_cache_writes"] += 1
        COUNTERS["search_cache_writes"] += 1
    spelling_suggestions, spelling_suggestions_incomplete = _spelling_suggestions(
        page_map,
        terms,
        mode,
        ordered_source_ids,
        term_feedback,
        trial_id,
        requested_source_id,
        bounded_limit,
        purpose_domain_id,
        purpose_question_id,
        query,
        term_feedback_truncated,
        term_feedback_sources_truncated,
        lambda: _spelling_catalogue(scope_key, page_map, ordered_source_ids),
    )
    total_matches = len(all_pairs)
    # Candidate rank is the one public ordering. It is persisted so receipts,
    # cursors, cached rows, and displayed hits cannot disagree about ranks 1..N.
    presentation = candidates
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r"sc_([0-9a-f]{16})_(\d+)", cursor)
        if match is None or match.group(1) != session_identity.removeprefix("sha256:")[:16]:
            raise ValueError(
                "search_cursor_stale: restart search with the same query, mode, and Source scope"
            )
        offset = int(match.group(2))
        if offset < 0 or offset > len(presentation):
            raise ValueError("search_cursor_expired: request a fresh search session")
    selected_candidates = presentation[offset : offset + bounded_limit]
    candidate_truncated = offset + len(selected_candidates) < len(presentation)
    source_by_id = {str(source["id"]): source for source in ordered_sources}
    # An omitted purpose is an unassigned Trial discovery.  Never infer an
    # association from whichever Domain happens to be active in the workflow.
    if purpose_domain_id is not None:
        # Associate the complete immutable ranking with the Domain that issued
        # the search. Lower-ranked candidates may not be materialized yet, but
        # context continuation must still reach them without rerunning retrieval.
        for candidate in candidates:
            _associate_search_candidate(
                root,
                session_identity,
                candidate["rank"],
                purpose_domain_id,
                trial_id,
            )
    hits = []
    for candidate in selected_candidates:
        source_id, page = candidate["source_id"], candidate["page"]
        page_text = verified[(trial_id, source_id)][1][page - 1]
        spans = [
            (start, end)
            for start, end in _all_search_match_spans(page_text, normalized_query, mode)
            if start < candidate["end"] and end > candidate["start"]
        ]
        if not spans:
            spans = [(candidate["start"], candidate["end"])]
        # Keep the issued candidate's query span as the anchor. The displayed
        # source window and its reusable Evidence must cover the same bounds.
        quote_start, quote_end, hit_candidate_truncated = _search_candidate_window(
            page_text,
            spans,
        )
        if quote_end <= quote_start:
            quote_end = len(page_text)
        while quote_end > quote_start and page_text[quote_end - 1] in "\r\n":
            quote_end -= 1
        passage_start_line, passage_end_line, _raw_start, _raw_end = _line_bounds(
            page_text, quote_start, quote_end
        )
        passage = _evidence(
            root,
            trial_id,
            source_id,
            "narrative",
            {
                "page": page,
                "start": quote_start,
                "end": quote_end,
                "quote": page_text[quote_start:quote_end],
                "source_version": verified[(trial_id, source_id)][0]["projection_hash"],
                "start_line": passage_start_line,
                "end_line": passage_end_line,
            },
        )
        _associate_search_evidence(root, session_identity, candidate["rank"], passage["identity"])
        _record_search_evidence(
            root,
            session_identity,
            candidate["rank"],
            trial_id,
            passage["identity"],
            purpose_domain_id,
            purpose_question_id,
        )
        hits.append(
            {
                "source_id": source_id,
                "source_role": source_by_id[source_id]["role"],
                "source_label": source_by_id[source_id]["label"],
                "page": page,
                "start_line": passage_start_line,
                "end_line": passage_end_line,
                "preview": passage["quote"],
                "passage_ref": passage["handle"],
                "candidate_truncated": hit_candidate_truncated,
                "candidate_recovery": (
                    {
                        "operation": "read_pages",
                        "trial_id": trial_id,
                        "windows": [
                            {
                                "source_id": source_id,
                                "page": page,
                                "start_line": candidate["start_line"],
                                "end_line": candidate["end_line"],
                            }
                        ],
                    }
                    if hit_candidate_truncated
                    else None
                ),
                "query": query,
                "rank": candidate["rank"],
                "within_source_rank": candidate["within_source_rank"],
                "range": {"start": offset + 1, "end": offset + len(selected_candidates)},
            }
        )
    condition = None if hits else "no_hits"
    receipt = {
        "trial_id": trial_id,
        "sources": [
            {"id": source["id"], "projection_hash": source["projection_hash"]}
            for source in ordered_sources
        ],
        "query": query,
        "normalized_query": " ".join(terms),
        "mode": mode,
        "profile": _SEARCH_PROFILE,
        "purpose_domain_id": purpose_domain_id,
        "purpose_question_id": purpose_question_id,
        "hits": [{"source_id": item["source_id"], "page": item["page"]} for item in hits],
        "limit": bounded_limit,
        "total_matches": total_matches,
        "truncated": candidate_truncated,
        "condition": condition,
        "batch_identity": (_read(root, "batch") or {}).get("identity"),
        "session_id": session_identity,
        "session_handle": session_handle,
        "candidate_count": len(candidates),
        "matching_page_count": total_matches,
        "ranking_complete": True,
        "returned_rank_start": offset + 1 if selected_candidates else None,
        "returned_rank_end": offset + len(selected_candidates) if selected_candidates else None,
        "next_cursor": (
            _cursor_handle(session_identity, offset + len(selected_candidates))
            if offset + len(selected_candidates) < len(presentation)
            else None
        ),
        "exhausted": not candidate_truncated,
        "returned_material": len(selected_candidates),
        "returned_candidates": [
            {
                "rank": item["rank"],
                "source_id": item["source_id"],
                "page": item["page"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in selected_candidates
        ],
    }
    receipt["identity"] = _identity(receipt)
    receipt["handle"] = "sr_" + receipt["identity"].removeprefix("sha256:")[:16]
    with _db(root, "derivative.sqlite3") as connection:
        inserted = connection.execute(
            "INSERT OR IGNORE INTO search_receipts VALUES (?,?)",
            (receipt["identity"], canonical_json_bytes(receipt)),
        ).rowcount
    COUNTERS["search_cache_writes"] += inserted
    diagnostic = _broad_search_diagnostic(
        trial_id=trial_id,
        normalized_query=" ".join(terms),
        mode=mode,
        source_id=requested_source_id,
        limit=bounded_limit,
        total_matches=total_matches,
        candidate_count=len(candidates),
        returned_count=len(selected_candidates),
        truncated=candidate_truncated,
        next_cursor=receipt["next_cursor"],
        purpose_domain_id=purpose_domain_id,
        purpose_question_id=purpose_question_id,
    )
    if diagnostic is None:
        diagnostic = _no_hits_diagnostic(
            normalized_query=" ".join(terms),
            mode=mode,
            total_matches=total_matches,
            returned_count=len(selected_candidates),
        )
    if requested_source_id is not None and diagnostic is not None:
        source = next(
            (item for item in ordered_sources if item["id"] == requested_source_id),
            None,
        )
        diagnostic = _source_navigation_diagnostic(
            diagnostic,
            source=source,
            pages=verified[(trial_id, requested_source_id)][1] if source is not None else None,
            trial_id=trial_id,
        )
    return {
        "outcome": "success",
        "hits": hits,
        "query": query,
        "mode": mode,
        "profile": _SEARCH_PROFILE,
        "total_matches": total_matches,
        "truncated": candidate_truncated,
        "condition": condition,
        "search_receipt": receipt,
        "session_id": session_identity,
        "session_handle": session_handle,
        "matching_page_count": total_matches,
        "candidate_count": len(candidates),
        "distinct_passage_count": len(candidates),
        "distinct_page_count": total_matches,
        "distinct_source_count": len({source_id for source_id, _page in all_pairs}),
        "ranking_complete": True,
        "returned_rank_start": receipt["returned_rank_start"],
        "returned_rank_end": receipt["returned_rank_end"],
        "next_cursor": receipt["next_cursor"],
        "exhausted": receipt["exhausted"],
        "term_feedback": term_feedback,
        "term_feedback_truncated": term_feedback_truncated,
        "term_feedback_sources_truncated": term_feedback_sources_truncated,
        "diagnostic": diagnostic,
        "purpose_domain_id": purpose_domain_id,
        "purpose_question_id": purpose_question_id,
        "spelling_suggestions": spelling_suggestions,
        "spelling_suggestions_incomplete": spelling_suggestions_incomplete,
    }


def _search_expression(query: str, mode: str) -> str:
    terms = [term for term in _canonical_search_text(query).split() if term]
    if not terms:
        raise ValueError("query must not be empty")
    if mode not in {"all", "phrase", "any", "prefix"}:
        raise ValueError("unknown lexical mode")

    def quoted(term: str) -> str:
        return '"' + term.replace('"', '""') + '"'

    if mode == "phrase":
        return quoted(" ".join(terms))
    if mode == "any":
        return " OR ".join(quoted(term) for term in terms)
    if mode == "prefix":
        return " OR ".join(f"{quoted(term)}*" for term in terms)
    return " AND ".join(quoted(term) for term in terms)


def _create_search_fts_for_profile(
    connection: sqlite3.Connection, profile: str, table_name: str = "pages_fts"
) -> None:
    """Create the tokenizer used by a current or historical search receipt."""
    if profile == _SEARCH_PROFILE:
        _create_search_fts(connection, table_name)
        return
    if profile == _LEGACY_SEARCH_PROFILE:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
            raise ValueError("invalid search FTS table name")
        connection.execute(
            f"CREATE VIRTUAL TABLE {table_name} USING fts5("
            "source_id, page UNINDEXED, raw_text, normalized_text)"
        )
        return
    raise ValueError("unknown search tokenizer profile")


def _search_scope_key(
    root: Path,
    sources: list[dict[str, Any]],
    profile: str = _SEARCH_PROFILE,
) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    return (
        str(root),
        profile,
        tuple((str(source["id"]), str(source["projection_hash"])) for source in sources),
    )


def _search_corpus(
    root: Path,
    sources: list[dict[str, Any]],
    pages: dict[str, tuple[str, ...]],
    profile: str = _SEARCH_PROFILE,
) -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], sqlite3.Connection]:
    """Reuse one verified, scope-bound FTS corpus across warm query ranks."""
    key = _search_scope_key(root, sources, profile)
    with _SEARCH_CORPUS_LOCK:
        cached = _SEARCH_CORPUS_CACHE.pop(key, None)
        if cached is not None:
            _SEARCH_CORPUS_CACHE[key] = cached
            _SEARCH_CORPUS_LEASES[id(cached)] = _SEARCH_CORPUS_LEASES.get(id(cached), 0) + 1
            _SEARCH_CORPUS_KEYS[id(cached)] = key
            COUNTERS["search_fts_corpus_cache_hits"] += 1
            return key, cached
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        _create_search_fts_for_profile(connection, profile)
        source_order = [str(source["id"]) for source in sources]
        rows = [
            (source_id, page, *_discovery_search_derivative(text))
            for source_id in source_order
            for page, text in enumerate(pages[source_id], 1)
        ]
        connection.executemany("INSERT INTO pages_fts VALUES (?,?,?,?)", rows)
        _SEARCH_CORPUS_CACHE[key] = connection
        _SEARCH_CORPUS_LEASES[id(connection)] = 1
        _SEARCH_CORPUS_KEYS[id(connection)] = key
        COUNTERS["search_fts_corpus_builds"] += 1
        while len(_SEARCH_CORPUS_CACHE) > _SEARCH_CORPUS_CACHE_MAX:
            _old_key, old_connection = _SEARCH_CORPUS_CACHE.popitem(last=False)
            old_id = id(old_connection)
            if _SEARCH_CORPUS_LEASES.get(old_id, 0):
                # A caller may have received this connection just before this
                # eviction. Retire it, then close it after the caller releases
                # its lease instead of invalidating an active query.
                _SEARCH_CORPUS_RETIRED[old_id] = old_connection
            else:
                old_connection.close()
                _SEARCH_CORPUS_KEYS.pop(old_id, None)
            _SEARCH_SPELLING_CATALOGUE_CACHE.pop(_old_key, None)
        return key, connection


def _release_search_corpus(connection: sqlite3.Connection) -> None:
    """Release a corpus lease and close an evicted connection when safe."""

    connection_id = id(connection)
    with _SEARCH_CORPUS_LOCK:
        lease_count = _SEARCH_CORPUS_LEASES.get(connection_id)
        if lease_count is None:
            return
        if lease_count > 1:
            _SEARCH_CORPUS_LEASES[connection_id] = lease_count - 1
            return
        _SEARCH_CORPUS_LEASES.pop(connection_id, None)
        retired = _SEARCH_CORPUS_RETIRED.pop(connection_id, None)
        if retired is not None:
            retired.close()
            _SEARCH_CORPUS_KEYS.pop(connection_id, None)


def _spelling_catalogue(
    key: tuple[str, str, tuple[tuple[str, str], ...]],
    pages: dict[str, tuple[str, ...]],
    source_order: list[str],
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]]]:
    """Cache bounded counts and one exact captured-source example per word."""
    with _SEARCH_CORPUS_LOCK:
        cached = _SEARCH_SPELLING_CATALOGUE_CACHE.pop(key, None)
        if cached is not None:
            _SEARCH_SPELLING_CATALOGUE_CACHE[key] = cached
            COUNTERS["search_spelling_catalogue_cache_hits"] += 1
            return cached
        words: Counter[str] = Counter()
        page_counts: Counter[str] = Counter()
        examples: dict[str, dict[str, Any]] = {}
        word_pattern = re.compile(r"(?<![\w])[A-Za-z]{5,40}(?![\w])")
        for source_id in source_order:
            for page_number, page in enumerate(pages[source_id], 1):
                canonical_page, canonical_spans = _canonical_search_text_with_spans(page)
                locatable_words: dict[str, tuple[int, int]] = {}
                for match in word_pattern.finditer(canonical_page):
                    start, end = match.span()
                    locatable_words.setdefault(
                        match.group(),
                        (canonical_spans[start][0], canonical_spans[end - 1][1]),
                    )
                found = set(word_pattern.findall(page.casefold()))
                line_starts = _line_starts(page)
                for word in found:
                    span = locatable_words.get(word)
                    if span is None:
                        # Preserve the old rule: raw word fragments that are
                        # not exact words in the canonical projection are not
                        # valid spelling examples.
                        continue
                    words[word] += 1
                    page_counts[word] += 1
                    if word not in examples:
                        start, end = span
                        start_line = bisect_right(line_starts, start)
                        end_line = bisect_right(line_starts, max(start, end - 1))
                        examples[word] = {
                            "source_id": source_id,
                            "page": page_number,
                            "start": start,
                            "end": end,
                            "start_line": start_line,
                            "end_line": end_line,
                        }
        result = (dict(words), dict(page_counts), examples)
        _SEARCH_SPELLING_CATALOGUE_CACHE[key] = result
        COUNTERS["search_spelling_catalogue_builds"] += 1
        return result


@lru_cache(maxsize=2048)
def _cached_normalized_search_text(text: str) -> str:
    """Cache only the bounded, discovery-only normalized page text.

    The captured page text remains the authority for evidence and coordinate
    validation.  This cache only avoids rebuilding the same FTS input during
    search projection checks and in-memory ranking; its key is the immutable
    page text, and it has a bounded size so a large corpus cannot grow the
    process without limit.  Raw page text and coordinate spans are never
    cached here.
    """
    return _canonical_search_text(text)


def _discovery_search_derivative(text: str) -> tuple[str, str]:
    """Return the raw and cached normalized variants used to build FTS rows."""
    normalized = _cached_normalized_search_text(text)
    return text, normalized if normalized != text else ""


def _search_result_order(
    source_id: str,
    page: int,
    rank: float,
    source_order: dict[str, int],
) -> tuple[float, int, int]:
    """Prefer global FTS relevance, then deterministic Source and page order."""
    return rank, source_order[source_id], page


def _search_match_spans(
    text: str,
    query: str,
    mode: str,
    profile: str = _SEARCH_PROFILE,
) -> list[tuple[int, int]]:
    """Return raw spans for the normalized match selected by one search mode."""
    terms = [item.casefold() for item in query.split() if item]
    if not terms:
        return []

    def variants(term: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    term,
                    re.sub(r"-", "", term),
                    re.sub(r"-", " ", term),
                )
            )
        )

    def find(searchable: str, term: str, prefix: bool = False) -> tuple[int, int]:
        folded = searchable.casefold()
        positions: list[tuple[int, int]] = []
        for candidate in variants(term):
            if not candidate:
                continue
            pattern = rf"(?<!\w){re.escape(candidate)}"
            if not prefix:
                pattern += r"(?!\w)"
            match = re.search(pattern, folded)
            if match is not None:
                positions.append((match.start(), len(candidate)))
        return min(positions, default=(-1, 0))

    def phrase_variants() -> tuple[str, ...]:
        phrase = " ".join(terms)
        return tuple(
            dict.fromkeys(
                (
                    phrase,
                    phrase.replace("-", ""),
                    phrase.replace("-", " "),
                )
            )
        )

    candidates: list[tuple[int, list[tuple[int, int]], list[tuple[int, int]]]] = []
    for dehyphenate in (False, True):
        searchable, spans = _normalized_text_with_spans(text, dehyphenate_line_ends=dehyphenate)
        if mode == "phrase":
            folded = searchable.casefold()
            for phrase in phrase_variants():
                match = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", folded)
                if match is not None:
                    candidates.append((match.start(), [(match.start(), len(phrase))], spans))
        else:
            matches = [find(searchable, term, mode == "prefix") for term in terms]
            if mode == "all" and not all(start >= 0 for start, _ in matches):
                continue
            found = [(start, length) for start, length in matches if start >= 0]
            if found:
                candidates.append((found[0][0], found, spans))
    if not candidates:
        return (
            _fts_token_match_spans(text, query, mode)
            if profile == _LEGACY_SEARCH_PROFILE
            else _native_fts_match_spans(text, query, mode)
        )
    _start, matches, spans = min(candidates, key=lambda item: item[0])
    raw_spans = [
        (spans[start][0], spans[min(start + length - 1, len(spans) - 1)][1])
        for start, length in matches
        if spans and 0 <= start < len(spans) and length > 0
    ]
    raw_spans.sort()
    # ``all`` only determines whether the page is a hit.  Navigation should
    # stay compact and point at the same first term that the preview uses,
    # rather than spanning unrelated terms across a long page.
    return raw_spans[:1]


def _fts_token_match_spans(text: str, query: str, mode: str) -> list[tuple[int, int]]:
    """Map an FTS token match when punctuation differs from the source text."""

    def fold(token: str) -> str:
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", token)
            if unicodedata.category(character) != "Mn"
        )

    query_tokens = [fold(token) for token in re.findall(r"\w+", _canonical_search_text(query))]
    if not query_tokens:
        return []

    candidates: list[tuple[int, int]] = []
    for dehyphenate in (False, True):
        searchable, character_spans = _normalized_text_with_spans(
            text, dehyphenate_line_ends=dehyphenate
        )
        tokens = [
            (
                fold(match.group()),
                character_spans[match.start()][0],
                character_spans[match.end() - 1][1],
            )
            for match in re.finditer(r"\w+", searchable)
            if character_spans
        ]
        if mode == "phrase":
            width = len(query_tokens)
            for index in range(len(tokens) - width + 1):
                if [token[0] for token in tokens[index : index + width]] == query_tokens:
                    candidates.append((tokens[index][1], tokens[index + width - 1][2]))
        else:
            matches: list[tuple[int, int]] = []
            for query_token in query_tokens:
                match = next(
                    (
                        (start, end)
                        for token, start, end in tokens
                        if (
                            token.startswith(query_token)
                            if mode == "prefix"
                            else token == query_token
                        )
                    ),
                    None,
                )
                if match is not None:
                    matches.append(match)
            if mode == "all" and len(matches) != len(query_tokens):
                continue
            candidates.extend(matches)
    return [min(candidates)] if candidates else []


def _search_match_line_range(
    text: str,
    query: str,
    mode: str,
    spans: list[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Map the normalized search span to inclusive lines of the page projection."""
    if spans is None:
        spans = _search_match_spans(text, query, mode)
    if not spans:
        raise ValueError("search result match is absent from the captured page projection")
    raw_start = min(start for start, _end in spans)
    raw_end = max(end for _start, end in spans)
    line_starts = [0]
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        line_starts.append(offset)
    start_line = bisect_right(line_starts, raw_start)
    end_line = bisect_right(line_starts, max(raw_start, raw_end - 1))
    return start_line, end_line


def _preview_window_bounds(
    text: str, spans: list[tuple[int, int]], radius: int = 120
) -> tuple[int, int]:
    """Return bounded whole-line coordinates around an explicit source anchor."""
    if not spans:
        return 0, min(len(text), 2 * radius)
    ordered_spans = sorted(spans)
    raw_start, raw_end = ordered_spans[0]
    for start, end in ordered_spans[1:]:
        if start - raw_start > 2 * radius:
            break
        raw_end = max(raw_end, end)
    line_starts = [0]
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        line_starts.append(offset)
    first, last, _line_start, _line_end = _line_bounds(text, raw_start, raw_end)
    start_line, end_line = first, last
    start = line_starts[start_line - 1]
    end = line_starts[end_line] if end_line < len(line_starts) else len(text)

    def fits(left: int, right: int) -> bool:
        return len(text[left:right].encode("utf-8")) <= _SEARCH_PREVIEW_MAX_BYTES

    if not fits(start, end):
        left = max(0, raw_start - radius)
        right = min(len(text), raw_end + radius)
        while not fits(left, right) and (left < raw_start or right > raw_end):
            if left < raw_start:
                left += 1
            elif right > raw_end:
                right -= 1
        while not fits(left, right) and right > left:
            right -= 1
        return left, right

    while True:
        expanded = False
        if start_line > 1 and fits(line_starts[start_line - 2], end):
            start_line -= 1
            start = line_starts[start_line - 1]
            expanded = True
        if end_line < len(line_starts) - 1 and fits(start, line_starts[end_line + 1]):
            end_line += 1
            end = line_starts[end_line]
            expanded = True
        if not expanded:
            return start, end


def _utf8_prefix_end(text: str, start: int, end: int, byte_limit: int) -> int:
    consumed = 0
    cursor = start
    for character in text[start:end]:
        size = len(character.encode("utf-8"))
        if consumed + size > byte_limit:
            break
        consumed += size
        cursor += 1
    return cursor


def _search_candidate_window(
    text: str,
    spans: list[tuple[int, int]],
) -> tuple[int, int, bool]:
    """Keep a complete candidate, or expose its bounded read_pages recovery."""
    if not spans:
        start, end = _preview_window_bounds(text, spans)
        return start, end, False
    candidate_start = min(start for start, _end in spans)
    candidate_end = max(end for _start, end in spans)
    candidate_bytes = len(text[candidate_start:candidate_end].encode("utf-8"))
    if candidate_bytes > _SEARCH_CANDIDATE_MAX_BYTES:
        end = _utf8_prefix_end(
            text,
            candidate_start,
            candidate_end,
            _SEARCH_CANDIDATE_MAX_BYTES,
        )
        return candidate_start, end, True

    start, end = _preview_window_bounds(text, spans)
    if all(start <= span_start and span_end <= end for span_start, span_end in spans):
        return start, end, False
    _first, _last, line_start, line_end = _line_bounds(text, candidate_start, candidate_end)
    if len(text[line_start:line_end].encode("utf-8")) <= _SEARCH_CANDIDATE_MAX_BYTES:
        return line_start, line_end, False
    return candidate_start, candidate_end, False


def _recomputed_search_hits(
    pages: dict[str, tuple[str, ...]], query: str, mode: str, limit: int
) -> list[tuple[str, int]]:
    """Recompute lexical hits from verified pages, bypassing the persistent FTS cache."""
    return _recomputed_search_summary(pages, query, mode, limit)[0]


def _recomputed_search_summary(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    limit: int,
    source_order: list[str] | None = None,
    span_cache: dict[tuple[str, int], list[tuple[int, int]]] | None = None,
) -> tuple[list[tuple[str, int]], int]:
    """Recompute bounded hits and the complete scoped match count."""
    if mode == "literal":
        ordered_sources = source_order or sorted(pages)
        all_pairs = [
            (source_id, page)
            for source_id in ordered_sources
            for page, text in enumerate(pages[source_id], 1)
            if _literal_match_spans(text, query)
        ]
        bounded_limit = max(1, min(limit, 100))
        selected = all_pairs[:bounded_limit]
        if span_cache is not None:
            for pair in selected:
                span_cache[pair] = _literal_match_spans(pages[pair[0]][pair[1] - 1], query)
        return selected, len(all_pairs)
    expression = _search_expression(query, mode)
    with sqlite3.connect(":memory:") as connection:
        _create_search_fts(connection)
        rows = [
            (source_id, page, *_discovery_search_derivative(text))
            for source_id in (source_order or sorted(pages))
            for page, text in enumerate(pages[source_id], 1)
        ]
        connection.executemany("INSERT INTO pages_fts VALUES (?,?,?,?)", rows)
        hits = connection.execute(
            "SELECT source_id,page,bm25(pages_fts) FROM pages_fts WHERE pages_fts MATCH ?",
            (expression,),
        ).fetchall()
        COUNTERS["fts_rows_read"] += len(hits)
    order = {source_id: index for index, source_id in enumerate(source_order or sorted(pages))}
    hits.sort(key=lambda row: _search_result_order(str(row[0]), int(row[1]), float(row[2]), order))
    all_pairs = [(str(row[0]), int(row[1])) for row in hits]
    bounded_limit = max(1, min(limit, 100))
    selected = all_pairs[:bounded_limit]
    if span_cache is None:
        return selected, len(all_pairs)

    # Coordinate mapping is a presentation concern, so do it only for the
    # bounded result set.  FTS and the canonical projection normally use the
    # same normalized text; if a future tokenizer edge case produces a hit
    # that cannot map, walk the remaining deterministic FTS order for a
    # replacement rather than returning an invalid coordinate.
    mapped: list[tuple[str, int]] = []
    for pair in selected:
        spans = _search_match_spans(pages[pair[0]][pair[1] - 1], query, mode)
        span_cache[pair] = spans
        if spans:
            mapped.append(pair)
    if len(mapped) < len(selected):
        selected_set = set(selected)
        for pair in all_pairs:
            if pair in selected_set:
                continue
            spans = _search_match_spans(pages[pair[0]][pair[1] - 1], query, mode)
            span_cache[pair] = spans
            if spans:
                mapped.append(pair)
                if len(mapped) == len(selected):
                    break
    # Keep the global BM25 ordering chosen above when candidates are mapped back
    # to raw coordinates.
    return mapped, len(all_pairs)


def _recomputed_all_pairs(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    source_order: list[str],
    profile: str = _SEARCH_PROFILE,
    connection: sqlite3.Connection | None = None,
) -> list[tuple[str, int]]:
    all_pairs, _feedback = _recomputed_search_projection(
        pages, query, mode, source_order, (), profile=profile, connection=connection
    )
    return all_pairs


def _recomputed_search_projection(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    source_order: list[str],
    feedback_terms: tuple[str, ...],
    profile: str = _SEARCH_PROFILE,
    connection: sqlite3.Connection | None = None,
) -> tuple[list[tuple[str, int]], dict[str, dict[str, set[int]]]]:
    if mode == "literal":
        pairs = [
            (source_id, page)
            for source_id in source_order
            for page, text in enumerate(pages[source_id], 1)
            if _literal_match_spans(text, query)
        ]
        return pairs, {
            term: {source_id: set() for source_id in source_order} for term in feedback_terms
        }
    expression = _search_expression(query, mode)
    owns_connection = connection is None
    current = connection or sqlite3.connect(":memory:")
    if not owns_connection:
        _SEARCH_CORPUS_LOCK.acquire()
    try:
        if owns_connection:
            _create_search_fts_for_profile(current, profile)
            rows = [
                (source_id, page, *_discovery_search_derivative(text))
                for source_id in source_order
                for page, text in enumerate(pages[source_id], 1)
            ]
            current.executemany("INSERT INTO pages_fts VALUES (?,?,?,?)", rows)
        hits = current.execute(
            "SELECT source_id,page,bm25(pages_fts) FROM pages_fts WHERE pages_fts MATCH ?",
            (expression,),
        ).fetchall()
        term_pages: dict[str, dict[str, set[int]]] = {
            term: {source_id: set() for source_id in source_order} for term in feedback_terms
        }
        term_mode = "prefix" if mode == "prefix" else "any"
        for term in feedback_terms:
            term_expression = _search_expression(term, term_mode)
            term_rows = current.execute(
                "SELECT DISTINCT source_id,page FROM pages_fts WHERE pages_fts MATCH ?",
                (term_expression,),
            ).fetchall()
            COUNTERS["fts_rows_read"] += len(term_rows)
            for source_id, page in term_rows:
                term_pages[term][str(source_id)].add(int(page))
    finally:
        if not owns_connection:
            _release_search_corpus(current)
            _SEARCH_CORPUS_LOCK.release()
        else:
            current.close()
    order = {source_id: index for index, source_id in enumerate(source_order)}
    hits.sort(key=lambda row: _search_result_order(str(row[0]), int(row[1]), float(row[2]), order))
    return [(str(row[0]), int(row[1])) for row in hits], term_pages


def _term_page_feedback(
    pages: dict[str, tuple[str, ...]],
    terms: list[str],
    source_order: list[str],
    query_pairs: list[tuple[str, int]],
    term_pages: dict[str, dict[str, set[int]]],
) -> list[dict[str, Any]]:
    """Format distinct page counts from one verified FTS build."""
    if not pages or not terms:
        return []
    query_pages: dict[str, set[int]] = {source_id: set() for source_id in source_order}
    for source_id, page in query_pairs:
        query_pages[source_id].add(page)
    return [
        {
            "source_id": source_id,
            "page_count": len(pages[source_id]),
            "query_matching_page_count": len(query_pages[source_id]),
            "term_page_counts": [
                {"term": term, "matching_page_count": len(term_pages[term][source_id])}
                for term in terms
            ],
        }
        for source_id in source_order
    ]


def _literal_match_spans(text: str, query: str) -> list[tuple[int, int]]:
    """Find contiguous presentation-normalized wording without stemming."""
    # Keep literal matching independent of the caller's query preparation. In
    # particular, casefold can expand a source character (``ß`` -> ``ss``),
    # while ``character_spans`` still maps every folded character back to the
    # authoritative source extent.
    needle = _canonical_search_text(query).casefold()
    if not needle:
        return []
    searchable, character_spans = _canonical_search_text_with_spans(text)

    def is_endpoint(value: str, index: int) -> bool:
        return index == 0 or not value[index - 1].isalnum()

    def is_end_endpoint(value: str, index: int) -> bool:
        return index == len(value) or not value[index].isalnum()

    result: list[tuple[int, int]] = []
    start = searchable.find(needle)
    while start >= 0:
        end = start + len(needle)
        if (
            is_endpoint(searchable, start)
            and is_end_endpoint(searchable, end)
            and character_spans
            and end <= len(character_spans)
        ):
            result.append((character_spans[start][0], character_spans[end - 1][1]))
        start = searchable.find(needle, start + 1)
    return result


def _canonical_search_text_with_spans(value: str) -> tuple[str, list[tuple[int, int]]]:
    """Canonicalize whitespace while retaining one raw span per output character."""

    normalized, spans = _normalized_text_with_spans(value)
    output: list[str] = []
    output_spans: list[tuple[int, int]] = []
    for character, span in zip(normalized, spans, strict=True):
        if character.isspace():
            if not output:
                continue
            if output[-1] == " ":
                output_spans[-1] = (output_spans[-1][0], span[1])
            else:
                output.append(" ")
                output_spans.append(span)
            continue
        output.append(character)
        output_spans.append(span)
    if output and output[-1] == " ":
        output.pop()
        output_spans.pop()
    return "".join(output), output_spans


def _osa_distance(left: str, right: str, cutoff: int) -> int:
    """Bounded optimal-string-alignment distance for spelling feedback."""
    if abs(len(left) - len(right)) > cutoff:
        return cutoff + 1
    previous = list(range(len(right) + 1))
    before = [0] * (len(right) + 1)
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            value = min(
                current[-1] + 1, previous[j] + 1, previous[j - 1] + (left_char != right_char)
            )
            if i > 1 and j > 1 and left_char == right[j - 2] and left[i - 2] == right_char:
                value = min(value, before[j - 2] + 1)
            current.append(value)
        before, previous = previous, current
    return previous[-1]


def _spelling_suggestions(
    pages: dict[str, tuple[str, ...]],
    terms: list[str],
    mode: str,
    source_order: list[str],
    term_feedback: list[dict[str, Any]],
    trial_id: str,
    source_id: str | None,
    limit: int,
    purpose_domain_id: str | None,
    purpose_question_id: str | None,
    original_query: str,
    term_feedback_truncated: bool,
    term_feedback_sources_truncated: bool,
    catalogue: (
        tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]]]
        | Callable[[], tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]]]]
        | None
    ) = None,
) -> tuple[list[dict[str, Any]], bool]:
    if mode in {"literal", "prefix", "phrase"} or not pages:
        return [], False
    incomplete = term_feedback_truncated or term_feedback_sources_truncated
    if incomplete:
        zero: set[str] = set()
    else:
        counts_by_term: dict[str, list[int]] = {term: [] for term in terms}
        for row in term_feedback:
            for item in row["term_page_counts"]:
                if item["term"] in counts_by_term:
                    counts_by_term[item["term"]].append(item["matching_page_count"])
        zero = {
            term
            for term, counts in counts_by_term.items()
            if counts and all(count == 0 for count in counts)
        }
    uppercase_terms = {
        re.sub(r"^\W+|\W+$", "", raw).casefold()
        for raw in original_query.split()
        if any(character.isalpha() for character in raw) and raw.isupper()
    }
    eligible_terms = {
        term
        for term in terms
        if term in zero and term not in uppercase_terms and re.fullmatch(r"[a-z]{5,40}", term)
    }
    if not eligible_terms:
        return [], incomplete
    if catalogue is None:
        return [], incomplete
    if callable(catalogue):
        catalogue_value = cast(
            Callable[[], tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]]]],
            catalogue,
        )()
    else:
        catalogue_value = catalogue
    words = Counter(catalogue_value[0])
    page_counts = Counter(catalogue_value[1])
    examples = catalogue_value[2]
    suggestions: list[dict[str, Any]] = []
    for term_index, term in enumerate(terms):
        if term not in eligible_terms:
            continue
        cutoff = 1 if len(term) <= 9 else 2
        candidates = []
        for word in words:
            distance = OSA.distance(term, word, score_cutoff=cutoff)
            if distance <= cutoff and word != term:
                candidates.append((distance, distance / len(term), -page_counts[word], word))
        for _distance, _normalized, _frequency, word in sorted(candidates)[:3]:
            replacement = [
                word if index == term_index else item for index, item in enumerate(terms)
            ]
            next_action = {
                "kind": "refine",
                "operation": "search_sources",
                "trial_id": trial_id,
                "query": " ".join(replacement),
                "mode": mode,
                "source_id": source_id,
                "limit": limit,
                "cursor": None,
            }
            if purpose_domain_id is not None:
                next_action["purpose_domain_id"] = purpose_domain_id
                next_action["purpose_question_id"] = purpose_question_id
            suggestions.append(
                {
                    "query_unit": term,
                    "query_unit_index": term_index,
                    "suggested_term": word,
                    "surface_page_count": page_counts[word],
                    "example": examples.get(word),
                    "next_action": next_action,
                }
            )
            if len(suggestions) >= 8:
                return suggestions, True
    return suggestions, incomplete


def _native_fts_match_spans(
    text: str,
    query: str,
    mode: str,
    connection: sqlite3.Connection | None = None,
) -> list[tuple[int, int]]:
    """Use SQLite highlight as the authority for Porter token boundaries."""
    expression = _search_expression(query, mode)
    normalized_text = _canonical_search_text(text)
    marker_pairs = (("\x01", "\x02"), ("\ue000", "\ue001"), ("\u241e", "\u241f"))
    markers = next(
        (
            pair
            for pair in marker_pairs
            if all(marker not in text and marker not in normalized_text for marker in pair)
        ),
        None,
    )
    if markers is None:
        raise ValueError("search match localization failed: no safe highlight markers")

    def highlighted_row(current: sqlite3.Connection) -> sqlite3.Row | tuple[object, ...] | None:
        return current.execute(
            "SELECT highlight(pages_fts,2,?,?), highlight(pages_fts,3,?,?) "
            "FROM pages_fts WHERE pages_fts MATCH ?",
            (*markers, *markers, expression),
        ).fetchone()

    try:
        if connection is None:
            with sqlite3.connect(":memory:") as current:
                _create_search_fts(current)
                current.execute(
                    "INSERT INTO pages_fts VALUES (?,?,?,?)",
                    ("source", 1, text, normalized_text),
                )
                row = highlighted_row(current)
        else:
            row = highlighted_row(connection)
    except sqlite3.Error as error:
        raise ValueError("search match localization failed: FTS highlight unavailable") from error
    if row is None:
        return []

    def ranges(value: str, expected: str) -> list[tuple[int, int]]:
        output: list[tuple[int, int]] = []
        plain = 0
        opened: int | None = None
        plain_characters: list[str] = []
        for character in value:
            if character == markers[0]:
                if opened is not None:
                    raise ValueError("search match localization failed: nested highlight markers")
                opened = plain
            elif character == markers[1]:
                if opened is None:
                    raise ValueError("search match localization failed: unmatched highlight marker")
                output.append((opened, plain))
                opened = None
            else:
                plain += 1
                plain_characters.append(character)
        if opened is not None or "".join(plain_characters) != expected:
            raise ValueError("search match localization failed: highlighted text mapping mismatch")
        return output

    raw = ranges(str(row[0]), text)
    normalized = ranges(str(row[1]), normalized_text)
    _normalized, character_spans = _canonical_search_text_with_spans(text)
    if any(not 0 <= start < end <= len(character_spans) for start, end in normalized):
        raise ValueError("search match localization failed: normalized span is unmappable")
    mapped_normalized = [
        (character_spans[start][0], character_spans[end - 1][1]) for start, end in normalized
    ]
    # FTS indexes both the captured wording and its presentation-normalized
    # derivative. A query can match one occurrence in each representation, so
    # returning the first non-empty column would silently lose recoverable
    # Source spans.
    return sorted(set(raw) | set(mapped_normalized))


def _all_search_match_spans(
    text: str,
    query: str,
    mode: str,
    profile: str = _SEARCH_PROFILE,
) -> list[tuple[int, int]]:
    """Map every lexical occurrence to raw projection coordinates.

    The older helper intentionally returned one anchor for a page. Sessions
    retain all local anchors so a page with separated match clusters can be
    traversed without changing the authoritative quote coordinates.
    """
    if mode == "literal":
        return _literal_match_spans(text, query)
    if profile == _LEGACY_SEARCH_PROFILE:
        return _search_match_spans(text, query, mode, profile=profile)
    terms = [term for term in _canonical_search_text(query).split() if term]
    if not terms:
        return []
    if mode in {"phrase", "any", "prefix"}:
        # Native highlight is authoritative for Porter token boundaries. A
        # regex occurrence is only a presentation coincidence for a stemmed
        # or prefix query and can point at characters SQLite did not match.
        return _native_fts_match_spans(text, query, mode)

    occurrences: list[tuple[int, int, str]] = []
    with sqlite3.connect(":memory:") as connection:
        _create_search_fts(connection)
        connection.execute(
            "INSERT INTO pages_fts VALUES (?,?,?,?)",
            ("source", 1, text, _canonical_search_text(text)),
        )
        for term in dict.fromkeys(terms):
            occurrences.extend(
                (start, end, term.casefold())
                for start, end in _native_fts_match_spans(text, term, "any", connection=connection)
            )
    if not occurrences:
        return _native_fts_match_spans(text, query, mode)
    if mode == "all":
        # Enumerate minimal co-occurrence windows, then keep the narrowest
        # non-overlapping windows. This retains repeated local clusters on one
        # page without manufacturing a giant bridge between two clusters.
        ordered = sorted(set(occurrences))
        needed = {term.casefold() for term in terms}
        counts: Counter[str] = Counter()
        left = 0
        windows: list[tuple[int, int]] = []
        for right, occurrence in enumerate(ordered):
            counts[occurrence[2]] += 1
            if not all(counts[term] for term in needed):
                continue
            while left <= right and counts[ordered[left][2]] > 1:
                counts[ordered[left][2]] -= 1
                left += 1
            window = ordered[left : right + 1]
            windows.append((min(item[0] for item in window), max(item[1] for item in window)))
            counts[ordered[left][2]] -= 1
            left += 1
        selected: list[tuple[int, int]] = []
        for candidate in sorted(set(windows), key=lambda value: (value[1] - value[0], *value)):
            if any(candidate[0] < end and candidate[1] > start for start, end in selected):
                continue
            selected.append(candidate)
        return sorted(selected) if selected else _native_fts_match_spans(text, query, mode)
    if occurrences:
        return [(start, end) for start, end, _term in sorted(set(occurrences))]
    return _native_fts_match_spans(text, query, mode)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        starts.append(offset)
    return starts


def _line_bounds_from_starts(starts: list[int], start: int, end: int) -> tuple[int, int, int, int]:
    first = bisect_right(starts, start)
    last = bisect_right(starts, max(start, end - 1))
    return first, last, starts[first - 1], starts[last] if last < len(starts) else starts[-1]


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int, int, int]:
    return _line_bounds_from_starts(_line_starts(text), start, end)


def _session_candidates(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    ordered_source_ids: list[str],
    all_pairs: list[tuple[str, int]],
    profile: str = _SEARCH_PROFILE,
) -> list[dict[str, Any]]:
    COUNTERS["candidate_reconstructions"] += 1
    # FTS normally returns each page once, but the canonical session must not
    # depend on that implementation detail.  Preserve the first page rank
    # when a derivative or legacy projection repeats a page.
    unique_pairs = list(dict.fromkeys(all_pairs))
    by_page_rank = {pair: index + 1 for index, pair in enumerate(unique_pairs)}
    candidates: list[dict[str, Any]] = []
    for source_id, page in unique_pairs:
        text = pages[source_id][page - 1]
        starts = _line_starts(text)
        spans = _all_search_match_spans(text, query, mode, profile=profile)
        if not spans:
            spans = _search_match_spans(text, query, mode, profile=profile)
        if not spans:
            raise ValueError(
                "search match localization failed: FTS hit has no recoverable Source span"
            )
        # One local line window per cluster; adjacent windows merge, but the
        # raw coordinates remain the exact boundaries of the merged quote.
        windows: list[tuple[int, int]] = []
        for start, end in spans:
            first, last, _raw_start, _raw_end = _line_bounds_from_starts(starts, start, end)
            windows.append((first, last))
        windows.sort()
        merged: list[tuple[int, int]] = []
        for first, last in windows:
            if merged and first <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            else:
                merged.append((first, last))
        for cluster, (first, last) in enumerate(merged):
            raw_start = starts[max(0, first - 1)]
            raw_end = starts[min(last, len(starts) - 1)]
            while raw_end > raw_start and text[raw_end - 1] in "\r\n":
                raw_end -= 1
            candidates.append(
                {
                    "source_id": source_id,
                    "page": page,
                    "start_line": first,
                    "end_line": min(last, len(starts) - 1),
                    "start": raw_start,
                    "end": raw_end,
                    "score": float(by_page_rank[(source_id, page)]),
                    "page_rank": by_page_rank[(source_id, page)],
                    "cluster": cluster,
                }
            )
    # Coalesce only canonical ranges from one continuous Source page.  Source
    # identity, projection/version, and page remain part of the identity, so
    # similar text in another Source or version is never merged.  The union
    # keeps qualifiers, headers, and footnotes from either overlapping window.
    candidates.sort(key=lambda item: (item["source_id"], item["page"], item["start"], item["end"]))
    coalesced: list[dict[str, Any]] = []
    for candidate in candidates:
        if coalesced:
            prior = coalesced[-1]
            same_page = (
                prior["source_id"] == candidate["source_id"] and prior["page"] == candidate["page"]
            )
            overlap = max(
                0,
                min(prior["end"], candidate["end"]) - max(prior["start"], candidate["start"]),
            )
            smaller = min(prior["end"] - prior["start"], candidate["end"] - candidate["start"])
            strongly_overlaps = smaller > 0 and overlap * 5 >= smaller * 4
            if same_page and strongly_overlaps:
                prior["start"] = min(prior["start"], candidate["start"])
                prior["end"] = max(prior["end"], candidate["end"])
                prior["start_line"] = min(prior["start_line"], candidate["start_line"])
                prior["end_line"] = max(prior["end_line"], candidate["end_line"])
                continue
        coalesced.append(candidate)

    source_order = {value: index for index, value in enumerate(ordered_source_ids)}
    coalesced.sort(
        key=lambda item: (
            item["score"],
            source_order[item["source_id"]],
            item["page"],
            item["cluster"],
        )
    )
    presentation = coalesced
    for rank, item in enumerate(presentation, 1):
        item["rank"] = rank
        item["within_source_rank"] = sum(
            1 for prior in presentation[:rank] if prior["source_id"] == item["source_id"]
        )
    return presentation


def _session_handle(identity: str) -> str:
    return "ss_" + identity.removeprefix("sha256:")[:16]


def _cursor_handle(session_identity: str, offset: int) -> str:
    return "sc_" + session_identity.removeprefix("sha256:")[:16] + "_" + str(offset)


def _search_receipt(root: Path, handle: SearchReceiptHandle) -> dict[str, Any]:
    """Resolve a disposable receipt only when its verified basis is still current."""
    with _db(root, "derivative.sqlite3") as connection:
        # The handle is the first 16 digest characters.  The candidate prefix
        # narrows the lookup, while the full receipt integrity checks below
        # remain authoritative (including collision safety).
        rows = connection.execute(
            "SELECT payload FROM search_receipts WHERE identity LIKE ? ORDER BY identity",
            (f"sha256:{handle[3:]}%",),
        ).fetchall()
    if not rows:
        raise ValueError("search receipt is unavailable")
    matches: list[dict[str, Any]] = []
    for row in rows:
        candidate = json.loads(bytes(row[0]))
        if isinstance(candidate, dict) and candidate.get("handle") == handle:
            matches.append(candidate)
    if len(matches) > 1:
        raise ValueError("search receipt handle is ambiguous")
    if not matches:
        raise ValueError("search receipt is unavailable")
    receipt = matches[0]
    legacy_keys = {
        "trial_id",
        "sources",
        "query",
        "normalized_query",
        "mode",
        "hits",
        "condition",
        "batch_identity",
        "limit",
        "total_matches",
        "truncated",
        "session_id",
        "session_handle",
        "candidate_count",
        "matching_page_count",
        "ranking_complete",
        "returned_rank_start",
        "returned_rank_end",
        "next_cursor",
        "exhausted",
        "returned_material",
        "returned_candidates",
        "identity",
        "handle",
    }
    modern_keys = legacy_keys | {"profile"}
    purpose_keys = {"purpose_domain_id", "purpose_question_id"}
    has_purpose = isinstance(receipt, dict) and set(receipt) == modern_keys | purpose_keys
    purpose_valid = True
    if has_purpose:
        purpose_domain_id = receipt.get("purpose_domain_id")
        purpose_question_id = receipt.get("purpose_question_id")
        valid_domains = {
            "domain:randomization",
            "domain:deviations",
            "domain:missing",
            "domain:measurement",
            "domain:selection",
        }
        purpose_valid = purpose_domain_id is None or purpose_domain_id in valid_domains
        if purpose_question_id is not None:
            from ..packs.scientific import SCIENTIFIC_PACK

            purpose_valid = purpose_valid and any(
                question.id == purpose_question_id and question.domain_id == purpose_domain_id
                for question in SCIENTIFIC_PACK.questions
            )
    if (
        not isinstance(receipt, dict)
        or set(receipt) not in (legacy_keys, modern_keys, modern_keys | purpose_keys)
        or handle != receipt.get("handle")
        or receipt.get("identity")
        != _identity(
            {key: value for key, value in receipt.items() if key not in {"identity", "handle"}}
        )
        or receipt.get("handle")
        != "sr_" + str(receipt.get("identity")).removeprefix("sha256:")[:16]
    ):
        raise ValueError("search receipt identity is corrupt")
    modern = "profile" in receipt
    batch = _read(root, "batch") or {}
    trial_id = receipt.get("trial_id")
    query = receipt.get("query")
    mode = receipt.get("mode")
    sources = receipt.get("sources")
    hits = receipt.get("hits")
    limit = receipt.get("limit")
    total_matches = receipt.get("total_matches")
    truncated = receipt.get("truncated")
    if (
        not isinstance(trial_id, str)
        or not isinstance(query, str)
        or not query.strip()
        or receipt.get("normalized_query")
        != (
            _canonical_search_text(query).casefold()
            if mode == "literal"
            else _canonical_query_text(query)
        )
        or mode
        not in (
            {"all", "phrase", "any", "prefix", "literal"}
            if modern
            else {"all", "phrase", "any", "prefix"}
        )
        or (modern and receipt.get("profile") != _SEARCH_PROFILE)
        or (has_purpose and not purpose_valid)
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
        or not isinstance(total_matches, int)
        or isinstance(total_matches, bool)
        or total_matches < 0
        or not isinstance(truncated, bool)
        or not isinstance(receipt.get("session_id"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["session_id"])
        or receipt.get("session_handle")
        != "ss_" + receipt["session_id"].removeprefix("sha256:")[:16]
        or not isinstance(receipt.get("candidate_count"), int)
        or isinstance(receipt.get("candidate_count"), bool)
        or receipt["candidate_count"] < 0
        or not isinstance(receipt.get("matching_page_count"), int)
        or isinstance(receipt.get("matching_page_count"), bool)
        or receipt["matching_page_count"] < 0
        or receipt.get("ranking_complete") is not True
        or not isinstance(receipt.get("returned_material"), int)
        or isinstance(receipt.get("returned_material"), bool)
        or receipt["returned_material"] < 0
        or not isinstance(receipt.get("returned_candidates"), list)
        or receipt.get("batch_identity") != batch.get("identity")
        or not isinstance(sources, list)
        or not isinstance(hits, list)
    ):
        raise ValueError("search receipt shape is corrupt")
    authoritative = {
        source["id"]: source
        for trial in batch.get("trials", [])
        if trial.get("id") == trial_id
        for source in trial.get("sources", [])
    }
    source_ids = [item.get("id") for item in sources if isinstance(item, dict)]
    if (
        not any(
            isinstance(trial, dict) and trial.get("id") == trial_id
            for trial in batch.get("trials", [])
        )
        or len(source_ids) != len(set(source_ids))
        or any(
            not isinstance(item, dict)
            or set(item) != {"id", "projection_hash"}
            or item.get("id") not in authoritative
            or item.get("projection_hash") != authoritative[item["id"]].get("projection_hash")
            for item in sources
        )
    ):
        raise ValueError("search receipt Source coverage is stale or corrupt")
    if source_ids != [
        source["id"]
        for source in _ordered_sources(
            authoritative[source_id] for source_id in source_ids if source_id in authoritative
        )
    ]:
        raise ValueError("search receipt Source coverage is stale or corrupt")
    hit_pairs = []
    for hit in hits:
        if (
            not isinstance(hit, dict)
            or set(hit) != {"source_id", "page"}
            or not isinstance(hit.get("source_id"), str)
            or not isinstance(hit.get("page"), int)
            or isinstance(hit.get("page"), bool)
            or hit["source_id"] not in authoritative
            or not 1 <= hit["page"] <= authoritative[hit["source_id"]]["page_count"]
        ):
            raise ValueError("search receipt hit is corrupt")
        hit_pairs.append((hit["source_id"], hit["page"]))
        if truncated != (receipt["returned_rank_end"] is not None and not receipt["exhausted"]):
            raise ValueError("search receipt match summary is corrupt")
    if (bool(hits) and receipt.get("condition") is not None) or (
        not hits and receipt.get("condition") != "no_hits"
    ):
        raise ValueError("search receipt condition is corrupt")
    verified = _verified_source_projections(
        root, set((trial_id, source_id) for source_id in source_ids)
    )
    session_identity = receipt["session_id"]
    with _db(root, "derivative.sqlite3") as connection:
        session_row = connection.execute(
            "SELECT payload FROM search_sessions WHERE identity=?", (session_identity,)
        ).fetchone()
        candidate_rows = connection.execute(
            "SELECT payload FROM search_candidates WHERE session_identity=? ORDER BY rank",
            (session_identity,),
        ).fetchall()
    if session_row is None:
        raise ValueError(
            "search_cursor_expired: the search receipt's session is unavailable; rerun the search"
        )
    try:
        session = json.loads(bytes(session_row[0]))
        candidates = [json.loads(bytes(row[0])) for row in candidate_rows]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("search session derivative is corrupt") from error
    spec = session.get("spec") if isinstance(session, dict) else None
    expected_spec = {
        "version": _SEARCH_SESSION_VERSION,
        "candidate_version": _SEARCH_CANDIDATE_VERSION,
        "trial_id": trial_id,
        "sources": sources,
        "query": receipt["normalized_query"],
        "normalized_query": receipt["normalized_query"],
        "mode": mode,
        "normalization": _SEARCH_NORMALIZATION_VERSION,
        "ranking_version": _SEARCH_RANKING_VERSION,
        "ranking": _SEARCH_RANKING_VERSION,
    }
    if modern:
        expected_spec["profile"] = _SEARCH_PROFILE
    if (
        not isinstance(session, dict)
        or set(session)
        != {
            "identity",
            "handle",
            "spec",
            "matching_page_count",
            "candidate_count",
            "complete",
            "ranked_pages",
            "term_feedback",
        }
        or spec != expected_spec
        or session.get("identity") != session_identity
        or session.get("identity") != _identity(spec)
        or session.get("handle") != _session_handle(session_identity)
        or session.get("complete") is not True
    ):
        raise ValueError("search session configuration is stale or corrupt")
    pages = {source_id: verified[(trial_id, source_id)][1] for source_id in source_ids}
    corpus_sources = [
        {"id": source_id, "projection_hash": authoritative[source_id]["projection_hash"]}
        for source_id in source_ids
    ]
    profile = _SEARCH_PROFILE if modern else _LEGACY_SEARCH_PROFILE
    _scope_key, search_corpus = _search_corpus(root, corpus_sources, pages, profile)
    all_pairs = _recomputed_all_pairs(
        pages,
        receipt["normalized_query"],
        mode,
        source_ids,
        profile=profile,
        connection=search_corpus,
    )
    expected_candidates = _session_candidates(
        pages,
        receipt["normalized_query"],
        mode,
        source_ids,
        all_pairs,
        profile=profile,
    )
    if candidates != expected_candidates:
        raise ValueError("search session candidates are stale or corrupt")
    if session.get("candidate_count") != len(candidates) or session.get(
        "matching_page_count"
    ) != len(all_pairs):
        raise ValueError("search session counts are stale")
    if (
        receipt.get("candidate_count") != len(candidates)
        or receipt.get("matching_page_count") != len(all_pairs)
        or total_matches != len(all_pairs)
    ):
        raise ValueError("search receipt results do not match the captured page projections")
    returned = receipt.get("returned_candidates", [])
    if not isinstance(returned, list):
        raise ValueError("search receipt candidate range is corrupt")
    expected_ranks = [item.get("rank") for item in returned if isinstance(item, dict)]
    if any(
        rank not in {candidate.get("rank") for candidate in candidates} for rank in expected_ranks
    ):
        raise ValueError("search receipt candidate range is corrupt")
    by_rank = {candidate.get("rank"): candidate for candidate in candidates}
    selected = [by_rank.get(rank) for rank in expected_ranks]
    if (
        len(expected_ranks) != len(returned)
        or len(expected_ranks) != len(set(expected_ranks))
        or any(not isinstance(candidate, dict) for candidate in selected)
        or any(
            not isinstance(item, dict)
            or set(item) != {"rank", "source_id", "page", "start_line", "end_line"}
            or not isinstance(candidate, dict)
            or any(item[key] != candidate.get(key) for key in item)
            for item, candidate in zip(returned, selected, strict=True)
        )
        or hit_pairs
        != [
            (candidate["source_id"], candidate["page"])
            for candidate in selected
            if isinstance(candidate, dict)
        ]
    ):
        raise ValueError("search receipt results do not match the captured page projections")
    if receipt.get("returned_material") != len(selected):
        raise ValueError("search receipt candidate range is corrupt")
    start = receipt.get("returned_rank_start")
    end = receipt.get("returned_rank_end")
    if selected:
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("search receipt candidate range is corrupt")
        if end - start + 1 != len(selected) or expected_ranks != list(range(start, end + 1)):
            raise ValueError("search receipt candidate range is corrupt")
        expected_exhausted = end >= len(candidates)
    else:
        if start is not None or end is not None:
            raise ValueError("search receipt candidate range is corrupt")
        expected_exhausted = True
    if receipt.get("exhausted") is not expected_exhausted:
        raise ValueError("search receipt candidate range is corrupt")
    if truncated is not (not expected_exhausted):
        raise ValueError("search receipt match summary is corrupt")
    expected_cursor = None
    if selected and not expected_exhausted:
        expected_cursor = _cursor_handle(session_identity, cast(int, end))
    if receipt.get("next_cursor") != expected_cursor:
        raise ValueError("search receipt candidate range is corrupt")
    return receipt


def read_pages(
    workspace: str | Path, trial_id: str, source_id: str, pages: list[int] | None = None
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    source = _find_source(root, trial_id, source_id)
    page_count = int(source["page_count"])
    requested_pages = pages or list(range(1, page_count + 1))
    if any(page < 1 or page > page_count for page in requested_pages):
        raise ValueError("requested page is outside Source")
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT page,text FROM pages WHERE source_id=? ORDER BY page", (source_id,)
        ).fetchall()
    by_page = {int(row[0]): {"page": row[0], "text": row[1]} for row in rows}
    selected = [by_page[page] for page in requested_pages if page in by_page]
    if not selected:
        raise ValueError("requested pages are outside Source")
    return {
        "outcome": "success",
        "pages": selected,
    }


def record_read_coverage(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    page: int,
    start_line: int,
    end_line: int,
) -> None:
    """Persist only the numbered range actually delivered by ``read_pages``."""

    record_read_coverage_batch(
        workspace,
        [(trial_id, source_id, page, start_line, end_line)],
    )


def record_read_coverage_batch(
    workspace: str | Path,
    ranges: list[tuple[str, str, int, int, int]],
) -> None:
    """Persist delivered read ranges atomically after a successful response."""

    root = _root(workspace)
    _ensure(root)
    validated: list[tuple[str, str, int, int, int]] = []
    for trial_id, source_id, page, start_line, end_line in ranges:
        source = _find_source(root, trial_id, source_id)
        if not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (page, start_line, end_line)
        ):
            raise ValueError("read coverage coordinates are invalid")
        if page < 1 or page > int(source["page_count"]):
            raise ValueError("read coverage coordinates are outside Source")
        if (start_line, end_line) != (0, 0) and (start_line < 1 or end_line < start_line):
            raise ValueError("read coverage coordinates are outside Source")
        validated.append((trial_id, source_id, page, start_line, end_line))
    if not validated:
        return
    phase = _state(root).get("phase")
    if phase not in {"proposal", "assessment"}:
        return
    batch = _read(root, "batch") or {}
    batch_id = batch.get("identity")
    if not isinstance(batch_id, str):
        raise ValueError("active Batch identity is unavailable")
    with _db(root, "derivative.sqlite3") as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO page_reads "
            "(batch_id,phase,trial_id,source_id,page,start_line,end_line) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (batch_id, phase, trial_id, source_id, page, start_line, end_line)
                for trial_id, source_id, page, start_line, end_line in validated
            ],
        )


def _main_report_sources(trial: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [item for item in trial.get("sources", []) if isinstance(item, dict)]
    main = [item for item in sources if item.get("role") == "main_article"]
    if main:
        return sorted(
            main, key=lambda item: (str(item.get("logical_path", "")), str(item.get("id", "")))
        )
    priority = {"protocol": 0, "sap": 1, "supplement": 2, "other": 3, "registry": 4}
    return sorted(
        sources, key=lambda item: (priority.get(str(item.get("role")), 5), str(item.get("id", "")))
    )[:1]


def _main_report_layout(
    connection: Any, trial: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute one deterministic, whole-line UTF-8 prefix for a Trial report."""

    layout: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    for source in _main_report_sources(trial):
        budget = MAIN_REPORT_TEXT_BUDGET
        prefix_open = True
        source_id = source.get("id")
        end_page = int(source.get("page_count", 0))
        rows = connection.execute(
            "SELECT page,text FROM pages WHERE source_id=? AND page<=? ORDER BY page",
            (source_id, end_page),
        ).fetchall()
        for row in rows:
            page = int(row["page"])
            lines = str(row["text"]).splitlines(keepends=True)
            required_count = 0
            if prefix_open and not lines:
                layout.append(
                    {
                        "source_id": source_id,
                        "page": page,
                        "lines": lines,
                        "required_count": 0,
                        "no_readable_text": True,
                    }
                )
            elif prefix_open:
                for index, line in enumerate(lines, 1):
                    size = len(line.encode("utf-8"))
                    if size > budget:
                        prefix_open = False
                        unread.append(
                            {
                                "source_id": source_id,
                                "page": page,
                                "start_line": index,
                                "end_line": len(lines),
                            }
                        )
                        break
                    budget -= size
                    required_count = index
                layout.append(
                    {
                        "source_id": source_id,
                        "page": page,
                        "lines": lines,
                        "required_count": required_count,
                        "no_readable_text": False,
                    }
                )
            else:
                if lines:
                    unread.append(
                        {
                            "source_id": source_id,
                            "page": page,
                            "start_line": 1,
                            "end_line": len(lines),
                        }
                    )
                layout.append(
                    {
                        "source_id": source_id,
                        "page": page,
                        "lines": lines,
                        "required_count": 0,
                        "no_readable_text": False,
                    }
                )
    return layout, unread


def main_report_read_gaps(
    workspace: str | Path,
    trials: list[dict[str, Any]],
    *,
    phase: str | None = None,
) -> list[dict[str, Any]]:
    """Return bounded read_pages windows for uncovered report-prefix lines."""

    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    phase = phase or state.get("phase")
    if phase not in {"proposal", "assessment"}:
        return []
    batch = _read(root, "batch") or {}
    batch_id = batch.get("identity")
    if not isinstance(batch_id, str):
        return []
    gaps: list[dict[str, Any]] = []
    with _db(root, "derivative.sqlite3") as connection:
        for trial in trials:
            if not isinstance(trial, dict) or not isinstance(trial.get("id"), str):
                continue
            for item in _main_report_layout(connection, trial)[0]:
                page = item["page"]
                required_count = item["required_count"]
                covered = connection.execute(
                    "SELECT start_line,end_line FROM page_reads "
                    "WHERE batch_id=? AND phase=? AND trial_id=? "
                    "AND source_id=? AND page=? ORDER BY start_line,end_line",
                    (batch_id, phase, trial["id"], item["source_id"], page),
                ).fetchall()
                if item["no_readable_text"]:
                    if not any(int(row[0]) == 0 and int(row[1]) == 0 for row in covered):
                        gaps.append(
                            {
                                "trial_id": trial["id"],
                                "source_id": item["source_id"],
                                "page": page,
                                "start_line": 1,
                                "end_line": 1,
                                "no_readable_text": True,
                            }
                        )
                    continue
                cursor = 1
                for row in covered:
                    start = max(1, int(row[0]))
                    end = min(required_count, int(row[1]))
                    if end < cursor:
                        continue
                    if start > cursor:
                        gaps.append(
                            {
                                "trial_id": trial["id"],
                                "source_id": item["source_id"],
                                "page": page,
                                "start_line": cursor,
                                "end_line": start - 1,
                            }
                        )
                    cursor = max(cursor, end + 1)
                if cursor <= required_count:
                    gaps.append(
                        {
                            "trial_id": trial["id"],
                            "source_id": item["source_id"],
                            "page": page,
                            "start_line": cursor,
                            "end_line": required_count,
                        }
                    )
    return gaps


def main_report_reading_status(
    workspace: str | Path,
    trials: list[dict[str, Any]],
    *,
    phase: str,
) -> dict[str, dict[str, Any]]:
    """Report complete, required, or budget-limited text coverage per Trial."""

    root = _root(workspace)
    _ensure(root)
    gaps = main_report_read_gaps(root, trials, phase=phase)
    batch = _read(root, "batch") or {}
    batch_id = batch.get("identity")
    result: dict[str, dict[str, Any]] = {}
    with _db(root, "derivative.sqlite3") as connection:
        for trial in trials:
            if not isinstance(trial, dict) or not isinstance(trial.get("id"), str):
                continue
            layout, unread = _main_report_layout(connection, trial)
            covered_prefix = 0
            covered_unread: list[dict[str, Any]] = []
            unread_by_page: dict[tuple[str, int], list[dict[str, Any]]] = {}
            for pending in unread:
                unread_by_page.setdefault((pending["source_id"], pending["page"]), []).append(
                    pending
                )
            if isinstance(batch_id, str):
                prefix_open = True
                current_source: str | None = None
                for item in layout:
                    if item["source_id"] != current_source:
                        current_source = item["source_id"]
                        prefix_open = True
                    rows = connection.execute(
                        "SELECT start_line,end_line FROM page_reads "
                        "WHERE batch_id=? AND phase=? AND trial_id=? "
                        "AND source_id=? AND page=? ORDER BY start_line,end_line",
                        (batch_id, phase, trial["id"], item["source_id"], item["page"]),
                    ).fetchall()
                    for pending in unread_by_page.get((item["source_id"], item["page"]), ()):
                        cursor = pending["start_line"]
                        for row in rows:
                            start = max(cursor, int(row[0]), pending["start_line"])
                            end = min(pending["end_line"], int(row[1]))
                            if end < start:
                                continue
                            if cursor < start:
                                covered_unread.append(
                                    {
                                        **pending,
                                        "start_line": cursor,
                                        "end_line": start - 1,
                                    }
                                )
                            cursor = max(cursor, end + 1)
                        if cursor <= pending["end_line"]:
                            covered_unread.append(
                                {**pending, "start_line": cursor, "end_line": pending["end_line"]}
                            )
                    if not prefix_open:
                        continue
                    if item["no_readable_text"]:
                        if not any(int(row[0]) == 0 and int(row[1]) == 0 for row in rows):
                            prefix_open = False
                        continue
                    line = 1
                    while line <= item["required_count"]:
                        covering = next(
                            (row for row in rows if int(row[0]) <= line <= int(row[1])),
                            None,
                        )
                        if covering is None:
                            prefix_open = False
                            break
                        covered_prefix += len(item["lines"][line - 1].encode("utf-8"))
                        line += 1
            else:
                covered_unread = list(unread)
            trial_gaps = [item for item in gaps if item.get("trial_id") == trial["id"]]
            result[trial["id"]] = {
                "status": (
                    "required" if trial_gaps else "budget_limited" if covered_unread else "complete"
                ),
                "budget_bytes": MAIN_REPORT_TEXT_BUDGET,
                "covered_prefix_bytes": covered_prefix,
                "unread_ranges": covered_unread,
                "required_ranges": trial_gaps,
            }
    return result


def _evidence(
    root: Path, trial_id: str, source_id: str, kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    # Discovery is recorded in search_domain_associations.  It must never be
    # folded into an Evidence record: the immutable claim is only this exact
    # captured Source version and its exact selected span.
    if {"search_session", "candidate_rank"} & set(payload):
        raise ValueError("discovery metadata cannot be part of Evidence identity")
    item = {"kind": kind, "trial_id": trial_id, "source_id": source_id, **payload}
    item["identity"] = _identity(item)
    item["handle"] = "eh_" + item["identity"].removeprefix("sha256:")[:16]
    with _db(root, "derivative.sqlite3") as connection:
        inserted = connection.execute(
            "INSERT OR IGNORE INTO evidence_handles VALUES (?,?)",
            (item["identity"], canonical_json_bytes(item)),
        ).rowcount
    COUNTERS["search_cache_writes"] += inserted
    return item


def _associate_search_candidate(
    root: Path,
    session_identity: str,
    rank: int,
    domain_id: str,
    trial_id: str,
) -> None:
    """Associate disposable navigation with a Domain without changing its identity."""
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO search_domain_associations "
            "(session_identity,rank,domain_id,trial_id) VALUES (?,?,?,?)",
            (session_identity, rank, domain_id, trial_id),
        )


def _associate_search_evidence(
    root: Path, session_identity: str, rank: int, evidence_identity: str
) -> None:
    """Keep discovery rank linked to canonical Evidence outside its identity."""
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "UPDATE search_domain_associations SET evidence_identity=? "
            "WHERE session_identity=? AND rank=?",
            (evidence_identity, session_identity, rank),
        )


def _record_search_evidence(
    root: Path,
    session_identity: str,
    rank: int,
    trial_id: str,
    evidence_identity: str,
    purpose_domain_id: str | None = None,
    purpose_question_id: str | None = None,
) -> None:
    """Record search provenance without overwriting investigative history."""

    phase = str(_state(root).get("phase", "proposal"))
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO search_evidence_provenance_history "
            "(session_identity,rank,trial_id,evidence_identity,phase,"
            "purpose_domain_id,purpose_question_id) VALUES (?,?,?,?,?,?,?)",
            (
                session_identity,
                rank,
                trial_id,
                evidence_identity,
                phase,
                purpose_domain_id or "",
                purpose_question_id or "",
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO search_evidence_provenance "
            "(session_identity,rank,trial_id,evidence_identity,phase) VALUES (?,?,?,?,?)",
            (session_identity, rank, trial_id, evidence_identity, phase),
        )
        current = connection.execute(
            "SELECT phase FROM search_evidence_provenance WHERE session_identity=? AND rank=?",
            (session_identity, rank),
        ).fetchone()
        if current is not None and _SEARCH_PHASE_ORDER.get(phase, -1) > _SEARCH_PHASE_ORDER.get(
            str(current[0]), -1
        ):
            # A purpose-neutral ranking can be reused after approval. Keep
            # the durable discovery eligible for the later assessment phase
            # instead of freezing the first proposal replay forever.
            connection.execute(
                "UPDATE search_evidence_provenance SET phase=? WHERE session_identity=? AND rank=?",
                (phase, session_identity, rank),
            )


def _associated_search_ranks(root: Path, trial_id: str, domain_id: str) -> set[tuple[str, int]]:
    """Return associations owned by exactly one Trial, including lost sessions."""
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT session_identity,rank FROM search_domain_associations "
            "WHERE domain_id=? AND trial_id=?",
            (domain_id, trial_id),
        ).fetchall()
    return {(str(session_identity), int(rank)) for session_identity, rank in rows}


def _associated_search_evidence(
    root: Path, trial_id: str, domain_id: str
) -> list[tuple[str, str, int]]:
    """Return canonical Evidence identities with their separate discovery rank."""
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT evidence_identity,session_identity,rank FROM search_domain_associations "
            "WHERE domain_id=? AND trial_id=? AND evidence_identity IS NOT NULL "
            "ORDER BY rank,session_identity,evidence_identity",
            (domain_id, trial_id),
        ).fetchall()
    return [
        (str(identity), str(session_identity), int(rank))
        for identity, session_identity, rank in rows
    ]


def _unassigned_search_evidence(root: Path, trial_id: str) -> list[tuple[str, str, int]]:
    """Return Trial discoveries that have not been assigned to a Domain."""

    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT provenance.evidence_identity,provenance.session_identity,provenance.rank "
            "FROM search_evidence_provenance_history AS provenance "
            "WHERE provenance.trial_id=? AND provenance.phase IN "
            "('assessment','ready_to_finalize') "
            "AND NOT EXISTS ("
            "SELECT 1 FROM search_domain_associations AS association "
            "WHERE association.session_identity=provenance.session_identity "
            "AND association.rank=provenance.rank) "
            "ORDER BY provenance.session_identity,provenance.rank,provenance.evidence_identity",
            (trial_id,),
        ).fetchall()
    return list(
        dict.fromkeys(
            (str(identity), str(session_identity), int(rank))
            for identity, session_identity, rank in rows
        )
    )


def _search_evidence_identities(root: Path, trial_id: str) -> set[str]:
    """Return every Evidence identity materialized by search in this Trial."""

    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT DISTINCT evidence_identity FROM search_domain_associations "
            "WHERE trial_id=? AND evidence_identity IS NOT NULL "
            "UNION SELECT DISTINCT evidence_identity FROM search_evidence_provenance_history "
            "WHERE trial_id=?",
            (trial_id, trial_id),
        ).fetchall()
    return {str(row[0]) for row in rows if isinstance(row[0], str)}


def _search_session_question_purpose(
    root: Path, session_identity: str, domain_id: str
) -> str | None:
    """Recover one unambiguous question purpose for a Domain continuation."""

    question_ids: set[str] = set()
    has_unqualified_receipt = False
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute("SELECT payload FROM search_receipts").fetchall()
    for row in rows:
        try:
            receipt = json.loads(bytes(row[0]))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            continue
        if (
            not isinstance(receipt, dict)
            or receipt.get("session_id") != session_identity
            or receipt.get("purpose_domain_id") != domain_id
        ):
            continue
        question_id = receipt.get("purpose_question_id")
        if isinstance(question_id, str):
            question_ids.add(question_id)
        else:
            has_unqualified_receipt = True
    if has_unqualified_receipt or len(question_ids) != 1:
        return None
    return next(iter(question_ids))


def _search_continuation_for_rows(
    root: Path,
    trial_id: str,
    rows: list[tuple[str, int]],
    included: set[tuple[str, int]],
    limit: int,
    domain_id: str | None,
) -> list[dict[str, Any]]:
    """Return one fully bound action for each session with omitted candidates."""
    continuations: list[dict[str, Any]] = []
    by_session: dict[str, list[int]] = {}
    for session_identity, rank in rows:
        by_session.setdefault(str(session_identity), []).append(int(rank))
    for session_identity, ranks in by_session.items():
        included_ranks = {rank for session, rank in included if session == session_identity}
        omitted_ranks = sorted(set(ranks) - included_ranks)
        if not omitted_ranks:
            continue
        with _db(root, "derivative.sqlite3") as connection:
            row = connection.execute(
                "SELECT payload FROM search_sessions WHERE identity=?", (session_identity,)
            ).fetchone()
        if row is None:
            continuations.append(
                {
                    "operation": "unavailable",
                    "trial_id": trial_id,
                    "search_session": session_identity,
                    "reason": "derivative_search_session_unavailable",
                }
            )
            continue
        try:
            payload = json.loads(bytes(row[0]))
            spec = payload["spec"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("search session derivative is corrupt") from error
        if spec.get("trial_id") != trial_id:
            continue
        sources = spec.get("sources")
        if not isinstance(sources, list):
            raise ValueError("search session derivative is corrupt")
        source_id = (
            sources[0].get("id") if len(sources) == 1 and isinstance(sources[0], dict) else None
        )
        first_omitted_rank = omitted_ranks[0]
        with _db(root, "derivative.sqlite3") as connection:
            candidate_rows = connection.execute(
                "SELECT payload FROM search_candidates WHERE session_identity=? ORDER BY rank",
                (session_identity,),
            ).fetchall()
        candidates = [json.loads(bytes(candidate[0])) for candidate in candidate_rows]
        # ``rank`` is the frozen global BM25 order persisted by search_sources.
        # Reconstructing a round-robin order by Source silently changed cursors
        # for multi-Source sessions and could skip or repeat lower-ranked hits.
        presentation = sorted(candidates, key=lambda candidate: candidate["rank"])
        offset = next(
            (
                index
                for index, candidate in enumerate(presentation)
                if candidate.get("rank") == first_omitted_rank
            ),
            None,
        )
        if offset is None:
            raise ValueError("search session candidate is corrupt")
        question_id = (
            _search_session_question_purpose(root, session_identity, domain_id)
            if domain_id is not None
            else None
        )
        continuations.append(
            {
                "operation": "search_sources",
                "trial_id": spec["trial_id"],
                "query": spec["query"],
                "mode": spec["mode"],
                "source_id": source_id,
                "limit": limit,
                "cursor": _cursor_handle(session_identity, offset),
                **({"purpose_domain_id": domain_id} if domain_id is not None else {}),
                **({"purpose_question_id": question_id} if question_id is not None else {}),
            }
        )
    return continuations


def _search_continuation(
    root: Path,
    trial_id: str,
    domain_id: str,
    included: set[tuple[str, int]],
    limit: int,
) -> list[dict[str, Any]]:
    """Return one fully bound action for each Domain search with omitted candidates."""

    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT session_identity,rank FROM search_domain_associations "
            "WHERE domain_id=? AND trial_id=? ORDER BY session_identity,rank",
            (domain_id, trial_id),
        ).fetchall()
    return _search_continuation_for_rows(
        root,
        trial_id,
        [(str(session_identity), int(rank)) for session_identity, rank in rows],
        included,
        limit,
        domain_id,
    )


def _unassigned_search_continuation(
    root: Path,
    trial_id: str,
    included: set[tuple[str, int]],
    limit: int,
) -> list[dict[str, Any]]:
    """Return one unassigned search continuation for each omitted Trial discovery."""

    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT provenance.session_identity,provenance.rank "
            "FROM search_evidence_provenance_history AS provenance "
            "WHERE provenance.trial_id=? AND provenance.phase IN "
            "('assessment','ready_to_finalize') "
            "AND NOT EXISTS ("
            "SELECT 1 FROM search_domain_associations AS association "
            "WHERE association.session_identity=provenance.session_identity "
            "AND association.rank=provenance.rank) "
            "ORDER BY provenance.session_identity,provenance.rank",
            (trial_id,),
        ).fetchall()
    return _search_continuation_for_rows(
        root,
        trial_id,
        [(str(session_identity), int(rank)) for session_identity, rank in rows],
        included,
        limit,
        None,
    )


def _validate_selected_evidence(
    root: Path,
    row_identity: str,
    payload: bytes,
    verified: dict[tuple[str, str], tuple[dict[str, Any], tuple[str, ...]]] | None = None,
) -> dict[str, Any]:
    """Validate one disposable handle against the captured projections.

    Evidence handles are convenient derivative references, not an authority.
    Recomputing a handle digest only proves that a row is self-consistent.  The
    promotion boundary must also prove that the narrative span or cached
    render still belongs to the canonical Source projection.
    """
    try:
        item = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("evidence handle payload is corrupt") from error
    if not isinstance(item, dict):
        raise ValueError("evidence handle payload is not an object")
    if row_identity != item.get("identity"):
        raise ValueError("evidence handle row identity is corrupt")
    kind = item.get("kind")
    expected = (
        {"kind", "trial_id", "source_id", "page", "start", "end", "quote", "identity", "handle"}
        if kind == "narrative"
        else {
            "kind",
            "trial_id",
            "source_id",
            "render",
            "delivery_receipt",
            "transcription",
            "region",
            "provenance",
            "identity",
            "handle",
        }
        if kind == "figure"
        else set()
    )
    allowed_shapes = {frozenset(expected)}
    if kind == "narrative":
        for source_version in (False, True):
            for line_bounds in (False, True):
                shape = set(expected)
                if source_version:
                    shape.add("source_version")
                if line_bounds:
                    shape.update({"start_line", "end_line"})
                allowed_shapes.add(frozenset(shape))
    if not expected or frozenset(item) not in allowed_shapes:
        raise ValueError("evidence handle shape is corrupt")
    if (
        not isinstance(item.get("trial_id"), str)
        or not isinstance(item.get("source_id"), str)
        or item["identity"]
        != _identity(
            {key: value for key, value in item.items() if key not in {"identity", "handle"}}
        )
        or item["handle"] != "eh_" + row_identity.removeprefix("sha256:")[:16]
    ):
        raise ValueError("evidence handle identity is corrupt")

    source_data = (
        verified.get((item["trial_id"], item["source_id"])) if verified is not None else None
    )
    if source_data is None:
        if verified is not None:
            raise ValueError("evidence handle source is outside the active Trial")
        source_data = _verified_source_projections(
            root, {(item["trial_id"], item["source_id"])}
        ).get((item["trial_id"], item["source_id"]))
        if source_data is None:
            raise ValueError("evidence handle source is outside the active Trial")
    source, pages = source_data
    if kind == "narrative":
        if "source_version" in item and item["source_version"] != source.get("projection_hash"):
            raise ValueError("narrative Evidence Source version is stale")
        page = item.get("page")
        start = item.get("start")
        end = item.get("end")
        quote = item.get("quote")
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(quote, str)
            or not quote
            or not 1 <= page <= source["page_count"]
        ):
            raise ValueError("narrative Evidence coordinates are corrupt")
        page_text = pages[page - 1] if page <= len(pages) else None
        if (
            not isinstance(page_text, str)
            or not 0 <= start < end <= len(page_text)
            or page_text[start:end] != quote
        ):
            raise ValueError("narrative Evidence is outside the captured page projection")
        if "start_line" in item and (
            (item["start_line"], item["end_line"]) != _line_bounds(page_text, start, end)[:2]
        ):
            raise ValueError("narrative Evidence line coordinates are corrupt")
        return item

    render = item["render"]
    region = item["region"]
    if (
        not isinstance(render, dict)
        or set(render) != {"identity", "source_id", "page", "png_sha256", "recipe"}
        or render.get("source_id") != item["source_id"]
        or not isinstance(render.get("page"), int)
        or isinstance(render["page"], bool)
        or not 1 <= render["page"] <= source["page_count"]
        or render.get("recipe") != "pymupdf-1.5"
        or not isinstance(render.get("png_sha256"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", render["png_sha256"])
        or render.get("identity")
        != _identity(
            {
                "source_id": item["source_id"],
                "source_sha256": source["sha256"],
                "page": render["page"],
                "recipe": render["recipe"],
            }
        )
        or not isinstance(item.get("transcription"), str)
        or not item["transcription"].strip()
        or item["transcription"] != item["transcription"].strip()
        or not isinstance(item.get("delivery_receipt"), str)
        or item["delivery_receipt"]
        != _identity(
            {
                "trial_id": item["trial_id"],
                "source_id": item["source_id"],
                "render_identity": render.get("identity"),
                "png_sha256": render.get("png_sha256"),
                "channel": "mcp_image_content",
                "mime_type": "image/png",
            }
        )
        or item.get("provenance") not in {"text_corroborated", "host_visual"}
        or not isinstance(region, list)
        or len(region) != 4
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in region
        )
        or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1)
    ):
        raise ValueError("figure Evidence projection is corrupt")
    with _db(root, "derivative.sqlite3") as connection:
        render_row = connection.execute(
            "SELECT payload,png FROM renders WHERE identity=?", (render["identity"],)
        ).fetchone()
    if render_row is None:
        raise ValueError("figure Evidence render is unavailable")
    try:
        stored_render = json.loads(bytes(render_row[0]))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("cached render payload is corrupt") from error
    png = bytes(render_row[1])
    if (
        not isinstance(stored_render, dict)
        or canonical_json_bytes(stored_render) != canonical_json_bytes(render)
        or stored_render.get("identity") != render["identity"]
        or stored_render.get("png_sha256") != "sha256:" + hashlib.sha256(png).hexdigest()
    ):
        raise ValueError("figure Evidence does not match the cached render projection")
    with _db(root, "derivative.sqlite3") as connection:
        delivery = connection.execute(
            "SELECT trial_id,source_id,render_identity,png_sha256 "
            "FROM visual_deliveries WHERE identity=?",
            (item["delivery_receipt"],),
        ).fetchone()
    if delivery is None or tuple(delivery) != (
        item["trial_id"],
        item["source_id"],
        render["identity"],
        render["png_sha256"],
    ):
        raise ValueError("figure Evidence has no matching ImageContent delivery")
    canonical_png = _render_page_png(root, item["trial_id"], item["source_id"], render["page"])
    canonical_png_sha256 = "sha256:" + hashlib.sha256(canonical_png).hexdigest()
    if render["png_sha256"] != canonical_png_sha256:
        raise ValueError("figure Evidence does not match the captured PDF render")
    return item


def _evidence_catalog(
    root: Path, trial_id: str | None = None, limit: int | None = None
) -> dict[str, dict[str, Any]]:
    """Read disposable handles.  Cache loss is recoverable, not workflow loss."""
    if limit is not None and limit < 1:
        return {}
    with _db(root, "derivative.sqlite3") as connection:
        if trial_id is None:
            if limit is None:
                rows = connection.execute(
                    "SELECT identity,payload FROM evidence_handles ORDER BY identity"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT identity,payload FROM evidence_handles ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        else:
            # Evidence handles are disposable and may belong to another Trial.
            # Filter in SQLite before validating source projections so a Domain
            # context cannot accidentally recover cross-Trial material.
            escaped_trial_id = (
                trial_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            query = (
                "SELECT identity,payload FROM evidence_handles "
                "WHERE CAST(payload AS TEXT) LIKE ? ESCAPE '\\' "
                f"ORDER BY {'rowid DESC' if limit is not None else 'identity'}"
            )
            parameters: tuple[Any, ...] = (f'%"trial_id":"{escaped_trial_id}"%',)
            if limit is not None:
                query += " LIMIT ?"
                parameters += (limit,)
            rows = connection.execute(query, parameters).fetchall()
    requested: set[tuple[str, str]] = set()
    for row in rows:
        try:
            item = json.loads(bytes(row[1]))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(item, dict)
            and isinstance(item.get("trial_id"), str)
            and isinstance(item.get("source_id"), str)
            and (trial_id is None or item["trial_id"] == trial_id)
        ):
            requested.add((item["trial_id"], item["source_id"]))
    verified = _verified_source_projections(root, requested)
    catalog: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row[0])
        payload = bytes(row[1])
        item = _validate_selected_evidence(root, identity, payload, verified)
        if payload != canonical_json_bytes(item):
            raise ValueError("evidence handle payload is not canonical")
        catalog[identity] = item
    return catalog


def _evidence_for_handles(
    root: Path, handles: set[str], trial_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """Resolve and validate only the bounded Evidence handles in one operation."""
    if not handles:
        return {}
    prefixes = sorted({handle.removeprefix("eh_") for handle in handles})
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT identity,payload FROM evidence_handles WHERE "
            + " OR ".join("identity LIKE ?" for _ in prefixes),
            tuple(f"sha256:{prefix}%" for prefix in prefixes),
        ).fetchall()
    candidates: dict[str, tuple[str, bytes]] = {}
    for row in rows:
        identity = str(row[0])
        try:
            item = json.loads(bytes(row[1]))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("evidence handle payload is corrupt") from error
        handle = item.get("handle") if isinstance(item, dict) else None
        if handle in handles:
            if handle in candidates:
                raise ValueError("evidence handle is ambiguous")
            candidates[handle] = (identity, bytes(row[1]))
    missing = handles - set(candidates)
    if missing:
        raise ValueError("evidence handle is unavailable")
    parsed: dict[str, dict[str, Any]] = {}
    requested_sources: set[tuple[str, str]] = set()
    for handle, (identity, payload) in candidates.items():
        try:
            item = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("evidence handle payload is corrupt") from error
        if not isinstance(item, dict) or trial_id is not None and item.get("trial_id") != trial_id:
            raise ValueError("evidence handle is outside the active Trial")
        requested_sources.add((str(item.get("trial_id")), str(item.get("source_id"))))
        parsed[handle] = {"identity": identity, "payload": payload}
    verified = _verified_source_projections(root, requested_sources)
    result: dict[str, dict[str, Any]] = {}
    for handle, value in parsed.items():
        item = _validate_selected_evidence(
            root,
            value["identity"],
            value["payload"],
            verified,
        )
        result[item["identity"]] = item
    return result


def _normalized_with_spans(value: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize caller/page text while retaining exact raw character spans."""
    return _normalized_text_with_spans(value)


def _normalized_equal(left: str, right: str) -> bool:
    """Compare text after the Evidence boundary's canonical normalization."""
    return _normalized_with_spans(left)[0] == _normalized_with_spans(right)[0]


def _normalized_contains(material: str, phrase: str) -> bool:
    """Test normalized containment without requiring a unique occurrence.

    Evidence handles identify one immutable selected item. Binding several
    Result leaves to that item must not fail merely because common labels,
    units, or zero values occur more than once inside its transcription.
    Uniqueness remains a requirement when selecting a passage, where it
    disambiguates the caller's selection; it is not a requirement for this
    later leaf-to-item binding.
    """
    normalized_material, _ = _normalized_with_spans(material)
    normalized_phrase, _ = _normalized_with_spans(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_material:
        return True

    wrapped_material, _ = _normalized_text_with_spans(material, dehyphenate_line_ends=False)
    wrapped_phrase, _ = _normalized_text_with_spans(phrase, dehyphenate_line_ends=False)
    line_wrap_phrase = re.sub(r"(?<=\w)-(?=\w)", " ", wrapped_phrase)
    return bool(line_wrap_phrase) and line_wrap_phrase in wrapped_material


def _numeric_boundary_before(value: str, index: int) -> bool:
    if index == 0:
        return True
    immediate = value[index - 1]
    if immediate.isspace():
        cursor = index - 2
        while cursor >= 0 and value[cursor].isspace():
            cursor -= 1
        if cursor < 0 or value[cursor] not in "+-<>≤≥":
            return True
        if value[cursor] == "+":
            return False
        before_operator = cursor - 1
        while before_operator >= 0 and value[before_operator].isspace():
            before_operator -= 1
        return value[cursor] == "-" and before_operator >= 0 and value[before_operator].isdigit()
    cursor = index - 1
    character = value[cursor]
    if character.isdigit() or character in "+<>≤≥" or character.isalpha() or character == "_":
        return False
    if character == "-":
        return cursor > 0 and value[cursor - 1].isdigit()
    if character in ".,":
        return cursor == 0 or not value[cursor - 1].isdigit()
    if character in "eE":
        return cursor == 0 or not value[cursor - 1].isdigit()
    return True


def _numeric_boundary_after(value: str, index: int, *, allow_percent_suffix: bool = False) -> bool:
    if index == len(value):
        return True
    immediate = value[index]
    if immediate.isspace():
        cursor = index + 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor == len(value) or value[cursor] not in "+-":
            return True
        if value[cursor] == "+":
            return False
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return (
            next_cursor == len(value)
            or value[next_cursor].isdigit()
            or value[next_cursor].isalpha()
        )
    cursor = index
    character = value[cursor]
    if character.isdigit() or character.isalpha() or character == "_":
        return False
    if character == "%":
        return allow_percent_suffix
    if character in ".,":
        return cursor + 1 == len(value) or not value[cursor + 1].isdigit()
    if character in "/:":
        return cursor + 1 == len(value) or not value[cursor + 1].isdigit()
    if character == "+":
        return False
    if character == "-":
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return next_cursor < len(value) and value[next_cursor].isdigit()
    if character in "eE":
        return False
    if character in "<>≤≥":
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return next_cursor == len(value) or not value[next_cursor].isdigit()
    return True


_NUMERIC_ATOM_PATTERN = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\d+,\d+)(?:[eE][+-]?\d+)?"
_NUMERIC_COMPOUND_PATTERN = re.compile(
    rf"{_NUMERIC_ATOM_PATTERN}\s*(?:\(\s*{_NUMERIC_ATOM_PATTERN}\s*\)|±\s*{_NUMERIC_ATOM_PATTERN})"
)


def _numeric_compound_marker_end(value: str, index: int) -> bool:
    if index == len(value):
        return True
    if not value[index].islower():
        return False
    cursor = index + 1
    while cursor < len(value) and value[cursor] == ",":
        cursor += 1
        if cursor == len(value) or not value[cursor].islower():
            return False
        cursor += 1
    return cursor == len(value) or not value[cursor].isalnum() and value[cursor] != "_"


def _numeric_contains(material: str, phrase: str, *, allow_percent_suffix: bool = False) -> bool:
    """Require a complete literal numeric expression after normalization.

    This is deliberately lexical.  It preserves source spelling and does not
    decide which arm, endpoint, or timepoint a number describes.
    """
    normalized_material, _ = _normalized_with_spans(material)
    normalized_phrase, _ = _normalized_with_spans(phrase)
    if not normalized_phrase or not any(character.isdigit() for character in normalized_phrase):
        return _normalized_contains(material, phrase)
    compound_phrase = _NUMERIC_COMPOUND_PATTERN.fullmatch(normalized_phrase) is not None
    compound_spans = tuple(
        match.span()
        for match in _NUMERIC_COMPOUND_PATTERN.finditer(normalized_material)
        if match.end() < len(normalized_material)
        and normalized_material[match.end()].islower()
        and _numeric_compound_marker_end(normalized_material, match.end())
    )
    start = normalized_material.find(normalized_phrase)
    while start >= 0:
        end = start + len(normalized_phrase)
        in_compound = any(
            start >= compound_start
            and end <= compound_end
            and (start, end) != (compound_start, compound_end)
            for compound_start, compound_end in compound_spans
        )
        after_is_valid = _numeric_boundary_after(
            normalized_material, end, allow_percent_suffix=allow_percent_suffix
        ) or (compound_phrase and _numeric_compound_marker_end(normalized_material, end))
        if (
            not in_compound
            and _numeric_boundary_before(normalized_material, start)
            and after_is_valid
        ):
            return True
        start = normalized_material.find(normalized_phrase, start + 1)
    return False


def _result_value_contains(material: str, phrase: str, field_path: str | None = None) -> bool:
    """Check one Result value with strict lexical boundaries for numeric fields."""
    numeric_field = field_path is None or field_path in {
        "/reported/estimate",
        "/reported/precision",
        "/reported/denominator_basis",
    }
    numeric_field = numeric_field or (
        field_path is not None
        and field_path.startswith("/reported/")
        and field_path.endswith("/value")
    )
    allow_percent_suffix = field_path is None or field_path.endswith("/value")
    return (
        _numeric_contains(
            material,
            phrase,
            allow_percent_suffix=allow_percent_suffix,
        )
        if numeric_field
        else _normalized_contains(material, phrase)
    )


def _normalized_match(material: str, phrase: str) -> tuple[str | None, str | None]:
    """Resolve one normalization-equivalent phrase to its raw material span."""
    normalized_material, spans = _normalized_with_spans(material)
    normalized_phrase, _ = _normalized_with_spans(phrase)
    if not normalized_phrase:
        return None, "empty"
    starts: list[int] = []
    start = normalized_material.find(normalized_phrase)
    while start >= 0:
        starts.append(start)
        start = normalized_material.find(normalized_phrase, start + 1)
    if not starts:
        return None, "absent"
    if len(starts) != 1:
        return None, "ambiguous"
    first = starts[0]
    last = first + len(normalized_phrase) - 1
    return material[spans[first][0] : spans[last][1]], None


def select_text_evidence(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    page: int,
    selected_text: str,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    source_data = _verified_source_projections(root, {(trial_id, source_id)}).get(
        (trial_id, source_id)
    )
    if source_data is None:
        raise ValueError("page is outside Source")
    source, pages = source_data
    if page < 1:
        raise ValueError("page is outside Source")
    invalid_selection = (
        "selected text is not an exact page selection: copy one contiguous passage from one "
        "read_pages page; "
        "use the 1-based source page index, not a printed page label; never paraphrase, "
        "reorder, omit intervening text, or reconstruct a table; select page-boundary "
        "fragments separately, and copy an extracted table's exact Markdown or use "
        "visual Evidence"
    )
    normalized_selection, _ = _normalized_with_spans(selected_text)
    if not normalized_selection:
        raise ValueError(invalid_selection)

    def matches(page_text: str) -> tuple[str, list[tuple[int, int]], list[int]]:
        normalized_text, spans = _normalized_with_spans(page_text)
        starts: list[int] = []
        offset = 0
        while True:
            start = normalized_text.find(normalized_selection, offset)
            if start < 0:
                break
            starts.append(start)
            offset = start + 1
        if starts:
            return page_text, spans, starts

        # Search and Evidence share line-wrap dehyphenation, but a model may
        # copy a semantic spelling such as ``multi-stage`` where the raw page
        # has ``multi-\nstage``. Retry only against the non-dehyphenated page
        # stream, where a hyphen-plus-line-break becomes a space. This does not
        # make ordinary punctuation optional. Unwrapped words and paraphrases
        # still fail.
        wrapped_text, wrapped_spans = _normalized_text_with_spans(
            page_text, dehyphenate_line_ends=False
        )
        wrapped_selection, _ = _normalized_text_with_spans(
            selected_text, dehyphenate_line_ends=False
        )
        line_wrap_selection = re.sub(r"(?<=\w)-(?=\w)", " ", wrapped_selection)
        if line_wrap_selection == wrapped_selection:
            return page_text, spans, starts
        offset = 0
        while True:
            start = wrapped_text.find(line_wrap_selection, offset)
            if start < 0:
                break
            starts.append(start)
            offset = start + 1
        if starts:
            return page_text, wrapped_spans, starts
        return page_text, spans, starts

    if page <= source["page_count"]:
        text, spans, starts = matches(pages[page - 1])
    else:
        text, spans, starts = "", [], []
    # Models occasionally carry the printed page label forward instead of the
    # 1-based source page index.  A unique exact match elsewhere in this same
    # verified projection is still unambiguous evidence: canonicalize to the
    # actual page rather than making the caller rediscover the page number.
    if not starts:
        candidates: list[tuple[int, list[tuple[int, int]], list[int]]] = []
        occurrence_count = 0
        for candidate_page, candidate_text in enumerate(pages, 1):
            if candidate_page == page and page <= source["page_count"]:
                continue
            _, candidate_spans, candidate_starts = matches(candidate_text)
            occurrence_count += len(candidate_starts)
            if candidate_starts:
                candidates.append((candidate_page, candidate_spans, candidate_starts))
        if occurrence_count == 1:
            page, spans, starts = candidates[0]
            text = pages[page - 1]
    # Caller supplied offsets are a second, unstable interpretation of page
    # text.  The server finds the one normalized occurrence and rejects ambiguity.
    if not starts:
        raise ValueError(invalid_selection)
    if len(starts) != 1:
        raise ValueError("selected text is ambiguous; select a unique passage")
    start = spans[starts[0]][0]
    end = spans[starts[0] + len(normalized_selection) - 1][1]
    start_line, end_line, _raw_start, _raw_end = _line_bounds(text, start, end)
    return {
        "outcome": "success",
        "evidence": _evidence(
            root,
            trial_id,
            source_id,
            "narrative",
            {
                "page": page,
                "start": start,
                "end": end,
                "quote": text[start:end],
                "source_version": source["projection_hash"],
                "start_line": start_line,
                "end_line": end_line,
            },
        ),
    }


def select_text_evidence_by_lines(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    page: int,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """Select exact source text using coordinates issued by ``read_pages``."""
    root = _root(workspace)
    _ensure(root)
    source_data = _verified_source_projections(root, {(trial_id, source_id)}).get(
        (trial_id, source_id)
    )
    if source_data is None:
        raise ValueError("page is outside Source")
    source, pages = source_data
    if page < 1 or page > int(source["page_count"]):
        raise ValueError("page is outside Source")

    text = pages[page - 1]
    lines = text.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError(
            f"line range is outside page {page}; choose 1 <= start_line <= end_line <= "
            f"{len(lines)} from read_pages"
        )
    start = sum(len(line) for line in lines[: start_line - 1])
    end = sum(len(line) for line in lines[:end_line])
    while end > start and text[end - 1] in "\r\n":
        end -= 1

    if end <= start:
        raise ValueError("line range must define a positive contiguous range")
    quote = text[start:end]
    if not quote.strip():
        raise ValueError("line range must contain non-whitespace source text")
    selected_start_line, selected_end_line, _, _ = _line_bounds(text, start, end)
    return {
        "outcome": "success",
        "evidence": _evidence(
            root,
            trial_id,
            source_id,
            "narrative",
            {
                "page": page,
                "start": start,
                "end": end,
                "quote": quote,
                "source_version": source["projection_hash"],
                "start_line": selected_start_line,
                "end_line": selected_end_line,
            },
        ),
    }


def _render_page_png(
    root: Path, trial_id: str, source_id: str, page: int, *, count: bool = True
) -> bytes:
    """Render one canonical captured PDF page using the fixed recipe."""
    path = internal_path(root, "sources", trial_id, f"{source_id}.bin")
    data = path.read_bytes()
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        png = (
            document[page - 1]
            .get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            .tobytes("png")
        )
    finally:
        document.close()
    if count:
        COUNTERS["render_bytes"] += len(png)
    return png


def _validated_cached_render(
    root: Path,
    trial_id: str,
    source_id: str,
    source: dict[str, Any],
    render_identity: str,
    payload_bytes: bytes,
    png_bytes: bytes,
) -> tuple[dict[str, Any], bytes]:
    """Validate a derivative render against both its Source and fixed recipe."""

    try:
        payload = json.loads(payload_bytes)
        cached_png = bytes(png_bytes)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("cached render payload is corrupt") from error
    expected_keys = {"identity", "source_id", "page", "png_sha256", "recipe"}
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_keys
        or payload.get("identity") != render_identity
        or payload.get("source_id") != source_id
        or not isinstance(payload.get("page"), int)
        or isinstance(payload.get("page"), bool)
        or not 1 <= payload["page"] <= int(source["page_count"])
        or payload.get("recipe") != "pymupdf-1.5"
        or payload.get("png_sha256") != "sha256:" + hashlib.sha256(cached_png).hexdigest()
        or render_identity
        != _identity(
            {
                "source_id": source_id,
                "source_sha256": source["sha256"],
                "page": payload["page"],
                "recipe": payload["recipe"],
            }
        )
    ):
        raise ValueError("cached render is corrupt or outside the requested Source")
    canonical_png = _render_page_png(root, trial_id, source_id, payload["page"], count=False)
    if canonical_png != cached_png:
        raise ValueError("cached render pixels do not match the captured Source")
    return payload, cached_png


def render_page(
    workspace: str | Path, trial_id: str, source_id: str, page: int, inline: bool = True
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    source = _find_source(root, trial_id, source_id)
    if (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page < 1
        or page > int(source["page_count"])
    ):
        raise ValueError("page is outside Source")
    identity = _identity(
        {
            "source_id": source_id,
            "source_sha256": source["sha256"],
            "page": page,
            "recipe": "pymupdf-1.5",
        }
    )
    with _db(root, "derivative.sqlite3") as connection:
        cached = connection.execute(
            "SELECT payload,png FROM renders WHERE identity=?", (identity,)
        ).fetchone()
    if cached is not None:
        payload, cached_png = _validated_cached_render(
            root, trial_id, source_id, source, identity, cached[0], cached[1]
        )
        if payload["page"] != page:
            raise ValueError("cached render is corrupt or outside the requested Source")
        return {
            "outcome": "success",
            "render": payload,
            "_png_bytes": cached_png if inline else None,
        }
    png = _render_page_png(root, trial_id, source_id, page)
    payload = {
        "identity": identity,
        "source_id": source_id,
        "page": page,
        "png_sha256": "sha256:" + hashlib.sha256(png).hexdigest(),
        "recipe": "pymupdf-1.5",
    }
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR REPLACE INTO renders VALUES (?,?,?)",
            (identity, canonical_json_bytes(payload), png),
        )
    return {
        "outcome": "success",
        "render": payload,
        # Pixels are transport data, but inspection is the normal render call;
        # inline=False remains available for metadata/cache-only callers.
        "_png_bytes": png if inline else None,
    }


def record_visual_delivery(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    render_identity: str,
    png_bytes: bytes,
) -> str:
    """Record the exact PNG returned as an MCP ImageContent block."""
    root = _root(workspace)
    _ensure(root)
    source = _find_source(root, trial_id, source_id)
    with _db(root, "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT payload,png FROM renders WHERE identity=?", (render_identity,)
        ).fetchone()
    if row is None:
        raise ValueError("visual Evidence requires an emitted render")
    render, cached_png = _validated_cached_render(
        root, trial_id, source_id, source, render_identity, row[0], row[1]
    )
    if png_bytes != cached_png:
        raise ValueError("render delivery does not match the captured Source")
    receipt = _identity(
        {
            "trial_id": trial_id,
            "source_id": source_id,
            "render_identity": render_identity,
            "png_sha256": render["png_sha256"],
            "channel": "mcp_image_content",
            "mime_type": "image/png",
        }
    )
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO visual_deliveries VALUES (?,?,?,?,?)",
            (receipt, trial_id, source_id, render_identity, render["png_sha256"]),
        )
        stored = connection.execute(
            "SELECT trial_id,source_id,render_identity,png_sha256 "
            "FROM visual_deliveries WHERE identity=?",
            (receipt,),
        ).fetchone()
    if stored is None or tuple(stored) != (
        trial_id,
        source_id,
        render_identity,
        render["png_sha256"],
    ):
        raise ValueError("visual delivery receipt is corrupt")
    return receipt


def select_visual_evidence(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    delivery_receipt: str,
    transcription: str,
    region: list[float],
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    transcription = transcription.strip()
    if not transcription:
        raise ValueError("visual transcription must contain non-whitespace text")
    source = _find_source(root, trial_id, source_id)
    with _db(root, "derivative.sqlite3") as connection:
        delivery = connection.execute(
            "SELECT trial_id,source_id,render_identity,png_sha256 "
            "FROM visual_deliveries WHERE identity=?",
            (delivery_receipt,),
        ).fetchone()
    if delivery is None:
        raise ValueError("visual Evidence requires a delivered ImageContent receipt")
    if tuple(delivery[:2]) != (trial_id, source_id):
        raise ValueError("visual Evidence delivery receipt belongs to another Source")
    render_identity = str(delivery[2])
    with _db(root, "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT payload,png FROM renders WHERE identity=?", (render_identity,)
        ).fetchone()
    if row is None:
        raise ValueError("verified render is unavailable")
    render, png = _validated_cached_render(
        root, trial_id, source_id, source, render_identity, row[0], row[1]
    )
    if render.get("png_sha256") != delivery[3] or delivery_receipt != _identity(
        {
            "trial_id": trial_id,
            "source_id": source_id,
            "render_identity": render_identity,
            "png_sha256": render.get("png_sha256"),
            "channel": "mcp_image_content",
            "mime_type": "image/png",
        }
    ):
        raise ValueError("cached render is corrupt or outside the requested Source")
    if len(region) != 4 or not all(math.isfinite(value) for value in region):
        raise ValueError("region must contain four finite normalized bounds")
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("region must be ordered and inside the render page")
    provenance = "host_visual"
    if region == [0.0, 0.0, 1.0, 1.0]:
        page_text = read_pages(workspace, trial_id, source_id, [int(render["page"])])["pages"][0][
            "text"
        ]
        if _normalized_contains(page_text, transcription):
            provenance = "text_corroborated"
    return {
        "outcome": "success",
        "evidence": _evidence(
            root,
            trial_id,
            source_id,
            "figure",
            {
                "render": render,
                "delivery_receipt": delivery_receipt,
                "transcription": transcription,
                "region": region,
                "provenance": provenance,
            },
        ),
    }
