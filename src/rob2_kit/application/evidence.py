import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from bisect import bisect_right
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import pymupdf

from ..models import canonical_json_bytes
from ..workflow_models import SearchReceiptHandle
from ._state import (
    _canonical_query_text,
    _canonical_search_text,
    _db,
    _ensure,
    _identity,
    _normalized_text_with_spans,
    _ordered_sources,
    _projection_hash,
    _read,
    _root,
    internal_path,
)
from .contracts import COUNTERS

_SEARCH_SESSION_VERSION = "rob2-kit.search-session.v0.5"
_SEARCH_CANDIDATE_VERSION = "rob2-kit.search-candidates.v0.5"


def list_sources(workspace: str | Path, trial_id: str | None = None) -> dict[str, Any]:
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
    return {"outcome": "success", "sources": _ordered_sources(trial["sources"])}


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
        if "sha256:" + hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("captured Source bytes do not match Canonical identity")
        # Intake (or an explicit derivative rebuild) owns extraction.  Normal
        # Evidence operations verify the persisted projection instead of
        # reopening and parsing the captured PDF on every call.
        source_pages = pages_by_source.get(source_id, [])
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
) -> dict[str, Any] | None:
    """Describe only observable breadth/truncation facts and one next call."""

    terms = tuple(term for term in normalized_query.split() if term)
    if mode != "any" or not truncated or not total_matches:
        return None
    if len(terms) > 1:
        action = {
            "kind": "refine",
            "operation": "search_sources",
            "trial_id": trial_id,
            "query": normalized_query,
            "mode": "all",
            "source_id": source_id,
            "limit": limit,
            "cursor": None,
        }
        detail = (
            "This multi-term any search is broad and truncated; refine with all to require "
            "every normalized term on a page, then inspect the returned hits."
        )
    else:
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
        detail = (
            "This any search is truncated; continue the issued cursor before drawing a "
            "conclusion from the displayed ranking."
        )
    return {
        "code": "broad_any_truncated",
        "normalized_term_count": len(terms),
        "total_matches": total_matches,
        "candidate_count": candidate_count,
        "returned_count": returned_count,
        "detail": detail,
        "next_action": action,
    }


def _narrow_no_hits_diagnostic(
    *,
    trial_id: str,
    query: str,
    normalized_query: str,
    mode: str,
    source_id: str | None,
    limit: int,
    total_matches: int,
    returned_count: int,
    cursor: str | None,
) -> dict[str, Any] | None:
    """Offer one observable, caller-executed widening for an initial narrow miss."""

    if (
        mode not in {"all", "phrase"}
        or len(normalized_query.split()) < 2
        or cursor is not None
        or total_matches != 0
        or returned_count != 0
    ):
        return None
    return {
        "code": "narrow_no_hits",
        "normalized_term_count": len(normalized_query.split()),
        "total_matches": total_matches,
        "candidate_count": 0,
        "returned_count": returned_count,
        "detail": (
            "This initial multi-token narrow search matched nothing. Zero hits establish only "
            "that the issued lexical query matched nothing; broaden once with any and inspect "
            "the returned passages. The broader search is not evidence of relevance, scientific "
            "completeness, or a preferred answer."
        ),
        "next_action": {
            "kind": "refine",
            "operation": "search_sources",
            "trial_id": trial_id,
            "query": query,
            "mode": "any",
            "source_id": source_id,
            "limit": limit,
            "cursor": None,
        },
    }


def search_sources(
    workspace: str | Path,
    trial_id: str,
    query: str,
    mode: str = "any",
    limit: int = 10,
    source_id: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    requested_source_id = source_id
    normalized_query = _canonical_query_text(query)
    terms = [term for term in normalized_query.split() if term]
    if not terms:
        raise ValueError("query must not be empty")
    if mode not in {"all", "phrase", "any", "prefix"}:
        raise ValueError("unknown lexical mode")
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
            "trial_id": trial_id,
            "sources": [],
            "query": " ".join(terms),
            "normalized_query": " ".join(terms),
            "mode": mode,
            "ranking": "fts5-bm25-source-order-page-cluster",
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
        }
        with _db(root, "derivative.sqlite3") as connection:
            connection.execute(
                "INSERT OR REPLACE INTO search_sessions VALUES (?,?)",
                (session_identity, canonical_json_bytes(session_payload)),
            )
        receipt = {
            "trial_id": trial_id,
            "sources": [],
            "query": query,
            "normalized_query": " ".join(terms),
            "mode": mode,
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
            connection.execute(
                "INSERT OR REPLACE INTO search_receipts VALUES (?,?)",
                (receipt["identity"], canonical_json_bytes(receipt)),
            )
        diagnostic = _narrow_no_hits_diagnostic(
            trial_id=trial_id,
            query=query,
            normalized_query=" ".join(terms),
            mode=mode,
            source_id=requested_source_id,
            limit=bounded_limit,
            total_matches=0,
            returned_count=0,
            cursor=cursor,
        )
        return {
            "outcome": "success",
            "hits": [],
            "query": query,
            "mode": mode,
            "total_matches": 0,
            "truncated": False,
            "condition": "no_hits",
            "search_receipt": receipt,
            "session_id": session_identity,
            "session_handle": session_handle,
            "matching_page_count": 0,
            "candidate_count": 0,
            "ranking_complete": True,
            "returned_rank_start": None,
            "returned_rank_end": None,
            "next_cursor": None,
            "exhausted": True,
            "diagnostic": diagnostic,
        }
    ordered_sources = _ordered_sources(sources)
    ordered_source_ids = [str(source["id"]) for source in ordered_sources]
    placeholders = ",".join("?" for _ in allowed)
    with _db(root, "derivative.sqlite3") as connection:
        cached_rows = connection.execute(
            "SELECT source_id,page,raw_text,normalized_text FROM pages_fts "
            f"WHERE source_id IN ({placeholders}) ORDER BY source_id,page",
            tuple(sorted(allowed)),
        ).fetchall()
        expected_rows = [
            (source_id, page, *_discovery_search_derivative(text))
            for source_id in sorted(allowed)
            for page, text in enumerate(verified[(trial_id, source_id)][1], 1)
        ]
        if [tuple(row) for row in cached_rows] != expected_rows:
            raise ValueError("text search projection is corrupt")
    page_map = {source_id: verified[(trial_id, source_id)][1] for source_id in ordered_source_ids}
    all_pairs = _recomputed_all_pairs(page_map, normalized_query, mode, ordered_source_ids)
    total_matches = len(all_pairs)
    session_spec = {
        "version": _SEARCH_SESSION_VERSION,
        "candidate_version": _SEARCH_CANDIDATE_VERSION,
        "trial_id": trial_id,
        "sources": [
            {"id": source["id"], "projection_hash": source["projection_hash"]}
            for source in ordered_sources
        ],
        "query": " ".join(terms),
        "normalized_query": " ".join(terms),
        "mode": mode,
        "ranking": "fts5-bm25-source-order-page-cluster",
    }
    session_identity = _identity(session_spec)
    session_handle = _session_handle(session_identity)
    with _db(root, "derivative.sqlite3") as connection:
        existing_session = connection.execute(
            "SELECT payload FROM search_sessions WHERE identity=?", (session_identity,)
        ).fetchone()
    candidates: list[dict[str, Any]] = []
    if existing_session is not None:
        try:
            stored = json.loads(bytes(existing_session[0]))
            if stored.get("spec") != session_spec:
                raise ValueError("search session configuration is stale")
            with _db(root, "derivative.sqlite3") as connection:
                candidate_rows = connection.execute(
                    "SELECT payload FROM search_candidates WHERE session_identity=? ORDER BY rank",
                    (session_identity,),
                ).fetchall()
            candidates = [json.loads(bytes(row[0])) for row in candidate_rows]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
            raise ValueError("search session derivative is corrupt; restart the search") from error
    if not candidates:
        candidates = _session_candidates(
            page_map, normalized_query, mode, ordered_source_ids, all_pairs
        )
        session_payload = {
            "identity": session_identity,
            "handle": session_handle,
            "spec": session_spec,
            "matching_page_count": total_matches,
            "candidate_count": len(candidates),
            "complete": True,
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
    # Candidate rank is the one public ordering.  It already includes the
    # Source-diversity pass, so receipts, cursors, cached rows, and displayed
    # hits cannot disagree about what ranks 1..N mean.
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
    # Import lazily: status projects search data, while search needs only its
    # authoritative workflow selector here.
    from .status import _active_trial_and_domain

    state = _read(root, "state") or {}
    active_trial_id, active_domain_id = _active_trial_and_domain(state)
    if (
        state.get("phase") == "assessment"
        and active_trial_id == trial_id
        and active_domain_id is not None
    ):
        # Associate the complete immutable ranking with the Domain that issued
        # the search. Lower-ranked candidates may not be materialized yet, but
        # context continuation must still reach them without rerunning retrieval.
        for candidate in candidates:
            _associate_search_candidate(
                root,
                session_identity,
                candidate["rank"],
                active_domain_id,
            )
    hits = []
    for candidate in selected_candidates:
        source_id, page = candidate["source_id"], candidate["page"]
        page_text = verified[(trial_id, source_id)][1][page - 1]
        spans = _search_match_spans(page_text, normalized_query, mode)
        if not spans or not any(
            start < candidate["end"] and end > candidate["start"] for start, end in spans
        ):
            spans = [(candidate["start"], candidate["end"])]
        # Use the same local co-occurrence cluster for navigation, preview,
        # and the reusable passage. Otherwise a preview can mention a nearby
        # term while passage_ref points at a different line.
        preview_spans = spans
        start_line, end_line = candidate["start_line"], candidate["end_line"]
        # Search hits are navigation results, but giving the host a reusable
        # exact window removes the error-prone copy/paste/select round trip.
        # The handle is derivative state; submission still revalidates its
        # coordinates against the immutable captured projection.
        line_starts = [0]
        line_offset = 0
        for line in page_text.splitlines(keepends=True):
            line_offset += len(line)
            line_starts.append(line_offset)
        quote_start = candidate["start"]
        quote_end = candidate["end"]
        if quote_end <= quote_start:
            quote_end = len(page_text)
        while quote_end > quote_start and page_text[quote_end - 1] in "\r\n":
            quote_end -= 1
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
                "search_session": session_identity,
                "candidate_rank": candidate["rank"],
                "start_line": start_line,
                "end_line": end_line,
            },
        )
        hits.append(
            {
                "source_id": source_id,
                "source_role": source_by_id[source_id]["role"],
                "source_label": source_by_id[source_id]["label"],
                "page": page,
                "start_line": start_line,
                "end_line": end_line,
                "preview": _match_centered_preview(
                    page_text, normalized_query, mode, spans=preview_spans
                ),
                "passage_ref": passage["handle"],
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
        connection.execute(
            "INSERT OR REPLACE INTO search_receipts VALUES (?,?)",
            (receipt["identity"], canonical_json_bytes(receipt)),
        )
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
    )
    if diagnostic is None:
        diagnostic = _narrow_no_hits_diagnostic(
            trial_id=trial_id,
            query=query,
            normalized_query=" ".join(terms),
            mode=mode,
            source_id=requested_source_id,
            limit=bounded_limit,
            total_matches=total_matches,
            returned_count=len(selected_candidates),
            cursor=cursor,
        )
    return {
        "outcome": "success",
        "hits": hits,
        "query": query,
        "mode": mode,
        "total_matches": total_matches,
        "truncated": candidate_truncated,
        "condition": condition,
        "search_receipt": receipt,
        "session_id": session_identity,
        "session_handle": session_handle,
        "matching_page_count": total_matches,
        "candidate_count": len(candidates),
        "ranking_complete": True,
        "returned_rank_start": receipt["returned_rank_start"],
        "returned_rank_end": receipt["returned_rank_end"],
        "next_cursor": receipt["next_cursor"],
        "exhausted": receipt["exhausted"],
        "diagnostic": diagnostic,
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
) -> tuple[int, float, int]:
    """Prefer the established Source order, then FTS relevance and page order."""
    return source_order[source_id], rank, page


def _search_match_spans(text: str, query: str, mode: str) -> list[tuple[int, int]]:
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
        return _fts_token_match_spans(text, query, mode)
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


def _match_centered_preview(
    text: str,
    query: str,
    mode: str,
    radius: int = 120,
    spans: list[tuple[int, int]] | None = None,
) -> str:
    """Return a compact discovery preview centered on an actual query match."""
    # A search hit's coordinate remains anchored to its first match, while
    # the preview should show nearby distinct query terms when they co-occur.
    # This is presentation-only and never changes Evidence boundaries.
    if spans is None:
        spans = _search_match_spans(text, query, mode)
    preview_spans = _preview_match_spans(text, query, mode, radius, spans)
    if not preview_spans:
        return text[: 2 * radius]
    raw_start = min(start for start, _end in preview_spans)
    raw_end = max(end for _start, end in preview_spans)
    left = max(0, raw_start - radius)
    right = min(len(text), raw_end + radius)
    prefix = "…" if left else ""
    suffix = "…" if right < len(text) else ""
    return prefix + text[left:right] + suffix


def _preview_match_spans(
    text: str,
    query: str,
    mode: str,
    radius: int,
    fallback: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Choose a bounded local cluster of distinct query-term matches."""
    terms = [term for term in _canonical_search_text(query).split() if term]
    if not terms or not fallback:
        return fallback
    # Search the same normalized stream as FTS and map every occurrence back
    # to raw coordinates. This lets previews score co-occurring terms even
    # when punctuation, accents, or a line-end hyphen differs from the query.
    searchable, character_spans = _normalized_text_with_spans(text)
    occurrences: list[tuple[int, int, str]] = []
    for term in terms:
        variants = tuple(dict.fromkeys((term, term.replace("-", ""), term.replace("-", " "))))
        for variant in variants:
            if not variant:
                continue
            suffix = "" if mode == "prefix" else r"(?!\w)"
            pattern = rf"(?<!\w){re.escape(variant)}{suffix}"
            for match in re.finditer(pattern, searchable, re.IGNORECASE):
                if not character_spans:
                    continue
                start = character_spans[match.start()][0]
                end = character_spans[min(match.end() - 1, len(character_spans) - 1)][1]
                occurrences.append((start, end, term.casefold()))
    if not occurrences:
        return fallback
    occurrences = sorted(set(occurrences))
    anchor = fallback[0][0]
    candidates = [item for item in occurrences if abs(item[0] - anchor) <= 2 * radius]
    if not candidates:
        return fallback

    # Score candidate windows globally: maximize distinct query-term coverage,
    # then minimize the span and distance from the primary FTS match.
    def window(item: tuple[int, int, str]) -> list[tuple[int, int, str]]:
        nearby = [candidate for candidate in candidates if abs(candidate[0] - item[0]) <= radius]
        closest_by_term: dict[str, tuple[int, int, str]] = {}
        for candidate in nearby:
            current = closest_by_term.get(candidate[2])
            if current is None or (abs(candidate[0] - item[0]), candidate[0]) < (
                abs(current[0] - item[0]),
                current[0],
            ):
                closest_by_term[candidate[2]] = candidate
        return list(closest_by_term.values())

    best = min(
        candidates,
        key=lambda item: (
            -len({candidate[2] for candidate in window(item)}),
            max(candidate[1] for candidate in window(item))
            - min(candidate[0] for candidate in window(item)),
            abs(item[0] - anchor),
            item[0],
        ),
    )
    selected = window(best)
    distinct = {item[2] for item in selected}
    if mode in {"all", "phrase"} or len(distinct) > 1:
        return [(item[0], item[1]) for item in selected]
    return fallback


def _recomputed_search_hits(
    pages: dict[str, tuple[str, ...]], query: str, mode: str, limit: int
) -> list[tuple[str, int]]:
    """Recompute lexical hits from verified pages, bypassing the persistent FTS cache."""
    return _recomputed_search_summary(pages, query, mode, limit)[0]


def _source_diverse_search_hits(
    pairs: list[tuple[str, int]], limit: int, source_order: list[str]
) -> list[tuple[str, int]]:
    """Bound hits while retaining one best hit from every matching Source.

    ``pairs`` is already ordered by Source priority and BM25 rank.  When the
    bound can cover all matching Sources, return one hit per Source before a
    second hit from any Source. If there are more matching Sources than slots,
    the highest-priority Sources receive the slots.
    """
    by_source: dict[str, list[tuple[str, int]]] = {}
    for pair in pairs:
        by_source.setdefault(pair[0], []).append(pair)
    matching_sources = [source_id for source_id in source_order if source_id in by_source]

    selected: list[tuple[str, int]] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for source_id in matching_sources:
            source_pairs = by_source[source_id]
            if depth < len(source_pairs):
                selected.append(source_pairs[depth])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        depth += 1

    return selected


def _recomputed_search_summary(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    limit: int,
    source_order: list[str] | None = None,
    span_cache: dict[tuple[str, int], list[tuple[int, int]]] | None = None,
) -> tuple[list[tuple[str, int]], int]:
    """Recompute bounded hits and the complete scoped match count."""
    expression = _search_expression(query, mode)
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE VIRTUAL TABLE pages_fts USING fts5("
            "source_id, page UNINDEXED, raw_text, normalized_text)"
        )
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
    order = {source_id: index for index, source_id in enumerate(source_order or sorted(pages))}
    hits.sort(key=lambda row: _search_result_order(str(row[0]), int(row[1]), float(row[2]), order))
    all_pairs = [(str(row[0]), int(row[1])) for row in hits]
    bounded_limit = max(1, min(limit, 100))
    ordered_source_ids = source_order or sorted(pages)
    selected = _source_diverse_search_hits(all_pairs, bounded_limit, ordered_source_ids)
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
    # Keep the diversity interleaving chosen above. Re-sorting by Source here
    # silently undoes the one-hit-per-Source guarantee whenever the result is
    # mapped back to raw coordinates.
    return mapped, len(all_pairs)


def _recomputed_all_pairs(
    pages: dict[str, tuple[str, ...]], query: str, mode: str, source_order: list[str]
) -> list[tuple[str, int]]:
    expression = _search_expression(query, mode)
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE VIRTUAL TABLE pages_fts USING fts5("
            "source_id,page UNINDEXED,raw_text,normalized_text)"
        )
        rows = [
            (source_id, page, *_discovery_search_derivative(text))
            for source_id in source_order
            for page, text in enumerate(pages[source_id], 1)
        ]
        connection.executemany("INSERT INTO pages_fts VALUES (?,?,?,?)", rows)
        hits = connection.execute(
            "SELECT source_id,page,bm25(pages_fts) FROM pages_fts WHERE pages_fts MATCH ?",
            (expression,),
        ).fetchall()
    order = {source_id: index for index, source_id in enumerate(source_order)}
    hits.sort(key=lambda row: _search_result_order(str(row[0]), int(row[1]), float(row[2]), order))
    return [(str(row[0]), int(row[1])) for row in hits]


def _all_search_match_spans(text: str, query: str, mode: str) -> list[tuple[int, int]]:
    """Map every lexical occurrence to raw projection coordinates.

    The older helper intentionally returned one anchor for a page. Sessions
    retain all local anchors so a page with separated match clusters can be
    traversed without changing the authoritative quote coordinates.
    """
    terms = [term for term in _canonical_search_text(query).split() if term]
    searchable, character_spans = _normalized_text_with_spans(text)
    if not terms or not character_spans:
        return []
    occurrences: list[tuple[int, int, str]] = []
    if mode == "phrase":
        phrases = tuple(dict.fromkeys((" ".join(terms), " ".join(terms).replace("-", ""))))
        for phrase in phrases:
            for match in re.finditer(
                rf"(?<!\w){re.escape(phrase)}(?!\w)", searchable, re.IGNORECASE
            ):
                occurrences.append(
                    (
                        character_spans[match.start()][0],
                        character_spans[min(match.end() - 1, len(character_spans) - 1)][1],
                        " ".join(terms),
                    )
                )
    else:
        for term in terms:
            suffix = "" if mode == "prefix" else r"(?!\w)"
            for variant in tuple(
                dict.fromkeys((term, term.replace("-", ""), term.replace("-", " ")))
            ):
                for match in re.finditer(
                    rf"(?<!\w){re.escape(variant)}{suffix}", searchable, re.IGNORECASE
                ):
                    occurrences.append(
                        (
                            character_spans[match.start()][0],
                            character_spans[min(match.end() - 1, len(character_spans) - 1)][1],
                            term.casefold(),
                        )
                    )
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
        return sorted(selected)
    return [(start, end) for start, end, _term in sorted(set(occurrences))]


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int, int, int]:
    starts = [0]
    offset = 0
    for line in text.splitlines(keepends=True):
        offset += len(line)
        starts.append(offset)
    first = bisect_right(starts, start)
    last = bisect_right(starts, max(start, end - 1))
    return first, last, starts[first - 1], starts[last] if last < len(starts) else len(text)


def _session_candidates(
    pages: dict[str, tuple[str, ...]],
    query: str,
    mode: str,
    ordered_source_ids: list[str],
    all_pairs: list[tuple[str, int]],
) -> list[dict[str, Any]]:
    by_page_rank = {pair: index + 1 for index, pair in enumerate(all_pairs)}
    candidates: list[dict[str, Any]] = []
    for source_id, page in all_pairs:
        text = pages[source_id][page - 1]
        spans = _all_search_match_spans(text, query, mode)
        if not spans:
            spans = _search_match_spans(text, query, mode)
        if not spans:
            continue
        # One local line window per cluster; adjacent windows merge, but the
        # raw coordinates remain the exact boundaries of the merged quote.
        windows: list[tuple[int, int]] = []
        for start, end in spans:
            first, last, _raw_start, _raw_end = _line_bounds(text, start, end)
            windows.append((first, last))
        windows.sort()
        merged: list[tuple[int, int]] = []
        for first, last in windows:
            if merged and first <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            else:
                merged.append((first, last))
        for cluster, (first, last) in enumerate(merged):
            starts = [0]
            offset = 0
            for line in text.splitlines(keepends=True):
                offset += len(line)
                starts.append(offset)
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
    source_order = {value: index for index, value in enumerate(ordered_source_ids)}
    candidates.sort(
        key=lambda item: (
            item["score"],
            source_order[item["source_id"]],
            item["page"],
            item["cluster"],
        )
    )
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_source.setdefault(item["source_id"], []).append(item)
    presentation: list[dict[str, Any]] = []
    depth = 0
    while len(presentation) < len(candidates):
        added = False
        for source_id in ordered_source_ids:
            rows = by_source.get(source_id, [])
            if depth < len(rows):
                presentation.append(rows[depth])
                added = True
        if not added:
            break
        depth += 1
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
    base_keys = {
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
    if (
        not isinstance(receipt, dict)
        or set(receipt) != base_keys
        or not base_keys.issubset(receipt)
        or handle != receipt.get("handle")
        or receipt.get("identity")
        != _identity(
            {key: value for key, value in receipt.items() if key not in {"identity", "handle"}}
        )
        or receipt.get("handle")
        != "sr_" + str(receipt.get("identity")).removeprefix("sha256:")[:16]
    ):
        raise ValueError("search receipt identity is corrupt")
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
        or receipt.get("normalized_query") != _canonical_query_text(query)
        or mode not in {"all", "phrase", "any", "prefix"}
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
        "ranking": "fts5-bm25-source-order-page-cluster",
    }
    if (
        not isinstance(session, dict)
        or set(session)
        != {"identity", "handle", "spec", "matching_page_count", "candidate_count", "complete"}
        or spec != expected_spec
        or session.get("identity") != session_identity
        or session.get("identity") != _identity(spec)
        or session.get("handle") != _session_handle(session_identity)
        or session.get("complete") is not True
    ):
        raise ValueError("search session configuration is stale or corrupt")
    pages = {source_id: verified[(trial_id, source_id)][1] for source_id in source_ids}
    all_pairs = _recomputed_all_pairs(pages, receipt["normalized_query"], mode, source_ids)
    expected_candidates = _session_candidates(
        pages, receipt["normalized_query"], mode, source_ids, all_pairs
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
    wanted = set(requested_pages)
    selected = [{"page": row[0], "text": row[1]} for row in rows if row[0] in wanted]
    if not selected:
        raise ValueError("requested pages are outside Source")
    return {
        "outcome": "success",
        "pages": selected,
    }


def _evidence(
    root: Path, trial_id: str, source_id: str, kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    item = {"kind": kind, "trial_id": trial_id, "source_id": source_id, **payload}
    item["identity"] = _identity(item)
    item["handle"] = "eh_" + item["identity"].removeprefix("sha256:")[:16]
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR REPLACE INTO evidence_handles VALUES (?,?)",
            (item["identity"], canonical_json_bytes(item)),
        )
    return item


def _associate_search_candidate(
    root: Path, session_identity: str, rank: int, domain_id: str
) -> None:
    """Associate disposable navigation with a Domain without changing its identity."""
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO search_domain_associations VALUES (?,?,?)",
            (session_identity, rank, domain_id),
        )


def _associated_search_ranks(root: Path, trial_id: str, domain_id: str) -> set[tuple[str, int]]:
    """Return associations owned by exactly one Trial.

    The derivative association table has no Trial column.  A search session's
    immutable spec is the owner, so filter through it rather than joining the
    shared RoB Domain ids across Trials.
    """
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT session_identity,rank FROM search_domain_associations WHERE domain_id=?",
            (domain_id,),
        ).fetchall()
    result: set[tuple[str, int]] = set()
    with _db(root, "derivative.sqlite3") as connection:
        for session_identity, rank in rows:
            payload = connection.execute(
                "SELECT payload FROM search_sessions WHERE identity=?", (session_identity,)
            ).fetchone()
            if payload is None:
                continue
            try:
                spec = json.loads(bytes(payload[0]))["spec"]
            except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("search session derivative is corrupt") from error
            if spec.get("trial_id") == trial_id:
                result.add((str(session_identity), int(rank)))
    return result


def _search_continuation(
    root: Path,
    trial_id: str,
    domain_id: str,
    included: set[tuple[str, int]],
    limit: int,
) -> dict[str, Any] | None:
    """Return one fully bound action that starts at an omitted candidate."""
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT session_identity,rank FROM search_domain_associations "
            "WHERE domain_id=? ORDER BY session_identity,rank",
            (domain_id,),
        ).fetchall()
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
        by_source: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            by_source.setdefault(candidate["source_id"], []).append(candidate)
        source_order = [
            item["id"]
            for item in sources
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        presentation: list[dict[str, Any]] = []
        depth = 0
        while len(presentation) < len(candidates):
            added = False
            for source in source_order:
                values = by_source.get(source, [])
                if depth < len(values):
                    presentation.append(values[depth])
                    added = True
            if not added:
                break
            depth += 1
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
        return {
            "operation": "search_sources",
            "trial_id": spec["trial_id"],
            "query": spec["query"],
            "mode": spec["mode"],
            "source_id": source_id,
            "limit": limit,
            "cursor": _cursor_handle(session_identity, offset),
        }
    return None


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
            "transcription",
            "region",
            "provenance",
            "identity",
            "handle",
        }
        if kind == "figure"
        else set()
    )
    if kind == "narrative" and "search_session" in item:
        expected = expected | {"search_session", "candidate_rank"}
    if kind == "narrative" and {"start_line", "end_line"}.issubset(item):
        expected = expected | {"start_line", "end_line"}
    if not expected or set(item) != expected:
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
        page = item.get("page")
        start = item.get("start")
        end = item.get("end")
        quote = item.get("quote")
        if "search_session" in item and (
            not isinstance(item.get("candidate_rank"), int)
            or isinstance(item.get("candidate_rank"), bool)
            or item["candidate_rank"] < 1
        ):
            raise ValueError("search candidate rank is corrupt")
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
                "start_line": selected_start_line,
                "end_line": selected_end_line,
            },
        ),
    }


def _render_page_png(root: Path, trial_id: str, source_id: str, page: int) -> bytes:
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
    COUNTERS["render_bytes"] += len(png)
    return png


def render_page(
    workspace: str | Path, trial_id: str, source_id: str, page: int, inline: bool = True
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    source = _find_source(root, trial_id, source_id)
    if page > int(source["page_count"]):
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
        payload = json.loads(bytes(cached[0]))
        return {
            "outcome": "success",
            "render": payload,
            "_png_bytes": bytes(cached[1]) if inline else None,
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


def select_visual_evidence(
    workspace: str | Path,
    trial_id: str,
    source_id: str,
    render_identity: str,
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
        row = connection.execute(
            "SELECT payload,png FROM renders WHERE identity=?", (render_identity,)
        ).fetchone()
    if row is None:
        raise ValueError("verified render is unavailable")
    render = json.loads(bytes(row[0]))
    png = bytes(row[1])
    if (
        not isinstance(render, dict)
        or render.get("identity") != render_identity
        or render.get("source_id") != source_id
        or render.get("page", 0) < 1
        or render.get("png_sha256") != "sha256:" + hashlib.sha256(png).hexdigest()
        or render_identity
        != _identity(
            {
                "source_id": source_id,
                "source_sha256": source["sha256"],
                "page": render.get("page"),
                "recipe": render.get("recipe"),
            }
        )
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
                "transcription": transcription,
                "region": region,
                "provenance": provenance,
            },
        ),
    }
