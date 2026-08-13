"""Stateless FTS5 search over an explicit immutable Source inventory."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from rob2_kit.sources import PageText, Source, _extract_pages, _media_type, sha256_bytes


class MatchSpan(PageText):
    end: int


class SearchHit(PageText):
    source_id: str
    source_hash: str
    match_spans: tuple[MatchSpan, ...]
    omitted_match_count: int = 0


def search_sources(
    workspace: str | Path,
    trial_id: str,
    sources: tuple[Source, ...],
    query: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[SearchHit, ...]:
    if not sources or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("nonempty explicit Sources, offset >= 0, and limit 1..100 are required")
    if len({s.id for s in sources}) != len(sources) or any(s.trial_id != trial_id for s in sources):
        raise ValueError("Sources must be unique and belong to the requested Trial")
    tokens = tuple(re.findall(r"[\w]+", query, re.UNICODE))
    if not tokens:
        raise ValueError("query must contain lexical tokens; semantics are token AND")
    rows = []
    for source in sources:
        data = _source_bytes(Path(workspace).resolve(strict=True), source)
        for page, text in enumerate(_extract_pages(data, source.media_type), 1):
            rows.append((source.id, source.sha256, page, text))
    db = sqlite3.connect(":memory:")
    try:
        db.execute(
            "CREATE VIRTUAL TABLE pages USING fts5("
            "source_id UNINDEXED, source_hash UNINDEXED, page UNINDEXED, text)"
        )
        db.executemany("INSERT INTO pages VALUES(?,?,?,?)", rows)
        if any("\ue000" in row[3] or "\ue001" in row[3] for row in rows):
            raise ValueError("source text contains reserved FTS highlight markers")
        match = " AND ".join(f'"{token}"' for token in tokens)
        found = db.execute(
            "SELECT source_id,source_hash,page,text,highlight(pages,3,?,?),bm25(pages) rank "
            "FROM pages WHERE pages MATCH ? ORDER BY rank,source_id,page LIMIT ? OFFSET ?",
            ("\ue000", "\ue001", match, limit, offset),
        ).fetchall()
    finally:
        db.close()
    return tuple(_hit(row[0], row[1], row[2], row[3], row[4]) for row in found)


def _source_bytes(root: Path, source: Source) -> bytes:
    relative = Path(source.captured_path)
    expected = Path(".rob2-kit") / "sources" / source.trial_id
    if relative.parent != expected or relative.name.split(".")[0] != source.id:
        raise ValueError("Source captured path is not its Trial capture path")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Source captured path escapes workspace")
    data = path.read_bytes()
    if (
        sha256_bytes(data) != source.sha256
        or _media_type(path, data) != source.media_type
        or len(_extract_pages(data, source.media_type)) != source.page_count
    ):
        raise ValueError("Source metadata is stale")
    return data


def _hit(source_id: str, source_hash: str, page: int, text: str, highlighted: str) -> SearchHit:
    rebuilt = []
    unique = []
    position = 0
    start_span = None
    for char in highlighted:
        if char == "\ue000":
            start_span = position
        elif char == "\ue001":
            if start_span is None:
                raise ValueError("invalid FTS highlight")
            unique.append((start_span, position))
            start_span = None
        else:
            rebuilt.append(char)
            position += 1
    if start_span is not None or "".join(rebuilt) != text:
        raise ValueError("FTS highlight does not reconstruct source text")
    unique = tuple(unique)
    if not unique:
        return SearchHit(
            source_id=source_id,
            source_hash=source_hash,
            page_number=page,
            text="",
            start=0,
            end=0,
            match_spans=(),
        )
    start = max(0, unique[0][0] - 80)
    end = min(len(text), start + 240)
    visible = tuple(
        MatchSpan(page_number=page, text=text[a:b], start=a, end=b)
        for a, b in unique
        if a >= start and b <= end
    )
    return SearchHit(
        source_id=source_id,
        source_hash=source_hash,
        page_number=page,
        text=text[start:end],
        start=start,
        end=end,
        match_spans=visible,
        omitted_match_count=len(unique) - len(visible),
    )
