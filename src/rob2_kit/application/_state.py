"""SQLite canonical state and deterministic derivative utilities."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import stat
import time
import tomllib
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymupdf

from ..models import canonical_json_bytes, sha256
from ..workflow_models import SourceRole
from .contracts import COUNTERS, WorkflowConflict

_SEARCH_DERIVATIVE_VERSION = "rob2-kit.search-projection.v4"

_SEARCH_PUNCTUATION_EQUIVALENTS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)


def _canonical_search_text(value: str) -> str:
    """Normalize only presentation differences that discovery may ignore."""
    normalized, _spans = _normalized_text_with_spans(value)
    return " ".join(normalized.split())


def _search_derivative(text: str) -> tuple[str, str]:
    """Return separate raw and normalized discovery-only search variants."""
    normalized = _canonical_search_text(text)
    if normalized == text:
        normalized = ""
    return text, normalized


def _normalized_text_with_spans(
    value: str, *, dehyphenate_line_ends: bool = True
) -> tuple[str, list[tuple[int, int]]]:
    """Build the one presentation-normalized stream used by discovery and Evidence."""
    filtered: list[tuple[str, int, int]] = []
    for index, character in enumerate(value):
        if character == "\u00ad":
            # PDF text commonly uses a discretionary soft hyphen immediately
            # before a physical line break. Preserve it as a line-end hyphen so
            # the normal dehyphenation pass can join the split word; otherwise
            # it remains an invisible formatting character and is discarded.
            if re.match(r"[^\S\r\n]*\r?\n", value[index + 1 :]):
                filtered.append(("-", index, index + 1))
            continue
        if unicodedata.category(character) != "Cf":
            filtered.append((character, index, index + 1))
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(filtered):
        cluster = [filtered[index]]
        index += 1
        while index < len(filtered) and unicodedata.combining(filtered[index][0]):
            cluster.append(filtered[index])
            index += 1
        raw_start = cluster[0][1]
        raw_end = cluster[-1][2]
        chunk = unicodedata.normalize("NFKC", "".join(item[0] for item in cluster)).translate(
            _SEARCH_PUNCTUATION_EQUIVALENTS
        )
        chunk = "".join(
            character for character in chunk if unicodedata.category(character) != "Cf"
        ).casefold()
        for character in chunk:
            if character.isspace():
                if characters and characters[-1] == " ":
                    spans[-1] = (spans[-1][0], raw_end)
                else:
                    characters.append(" ")
                    spans.append((raw_start, raw_end))
            else:
                characters.append(character)
                spans.append((raw_start, raw_end))

    output: list[str] = []
    output_spans: list[tuple[int, int]] = []
    index = 0
    while index < len(characters):
        if characters[index] == "-" and output and (output[-1].isalnum() or output[-1] == "_"):
            next_index = index + 1
            while next_index < len(characters) and characters[next_index] == " ":
                next_index += 1
            whitespace = (
                value[spans[index][1] : spans[next_index][0]] if next_index < len(spans) else ""
            )
            if (
                next_index > index + 1
                and any(character in "\r\n" for character in whitespace)
                and next_index < len(characters)
                and (characters[next_index].isalnum() or characters[next_index] == "_")
            ):
                if dehyphenate_line_ends:
                    output_spans[-1] = (output_spans[-1][0], spans[next_index][0])
                else:
                    output.append(" ")
                    output_spans.append((spans[index][0], spans[next_index][0]))
                index = next_index
                continue
        output.append(characters[index])
        output_spans.append(spans[index])
        index += 1
    return "".join(output), output_spans


def _link_like(path: Path) -> bool:
    """Reject symlinks and Windows reparse-point indirection on all supported Python versions."""
    is_junction = getattr(path, "is_junction", None)
    if path.is_symlink() or bool(is_junction and is_junction()):
        return True
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def internal_path(root: Path, *parts: str) -> Path:
    """Resolve a fixed server-owned path without following filesystem indirection."""

    internal = root / ".rob2-kit"
    for path in (
        internal,
        *(internal.joinpath(*parts[:index]) for index in range(1, len(parts) + 1)),
    ):
        if _link_like(path):
            raise ValueError(f"{path.relative_to(root)} must not be a symlink or junction")
        if path.exists() and not path.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"{path.relative_to(root)} must remain inside the workspace")
    return internal.joinpath(*parts)


def _root(workspace: str | Path) -> Path:
    root = Path(workspace).resolve(strict=True)
    internal = internal_path(root)
    internal.mkdir(exist_ok=True)
    return root


@contextmanager
def _db(root: Path, name: str):
    started = time.perf_counter()
    COUNTERS["database_queries"] += 1
    connection = sqlite3.connect(internal_path(root, name))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()
        COUNTERS["elapsed_ms"] += (time.perf_counter() - started) * 1000


def _ensure(root: Path) -> None:
    internal = internal_path(root)
    legacy = internal / "active-batch.sqlite3"
    if legacy.exists():
        raise ValueError("contract_version_unsupported")
    with _db(root, "canonical.sqlite3") as connection:
        # ``records`` is the integrity-checked head projection used for cheap
        # lookups; ``canonical_records`` is the immutable content ledger.
        # Workspaces from earlier contracts are rejected above.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, payload BLOB NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS canonical_records ("
            "identity TEXT PRIMARY KEY, kind TEXT NOT NULL, batch_id TEXT, trial_id TEXT, "
            "payload BLOB NOT NULL, payload_hash TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS workflow_head ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        current = connection.execute("SELECT value FROM meta WHERE name='contract'").fetchone()
        if current is None:
            connection.execute("INSERT INTO meta VALUES ('contract','0.3.0')")
        elif current[0] != "0.3.0":
            raise ValueError("contract_version_unsupported")
    with _db(root, "derivative.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_index ("
            "source_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, trial_id TEXT NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS pages (source_id TEXT, page INTEGER, text TEXT, "
            "PRIMARY KEY(source_id,page))"
        )
        fts_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(pages_fts)").fetchall()
        }
        if fts_columns and fts_columns != {"source_id", "page", "raw_text", "normalized_text"}:
            connection.execute("DROP TABLE pages_fts")
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5("
            "source_id, page UNINDEXED, raw_text, normalized_text)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS search_projection_meta ("
            "name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS renders (identity TEXT PRIMARY KEY, "
            "payload BLOB NOT NULL, png BLOB NOT NULL)"
        )
        # Handles are disposable navigation projections.  They deliberately do
        # not enter the canonical ledger until a proposal or Domain checkpoint
        # binds them as scientific evidence.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS evidence_handles (identity TEXT PRIMARY KEY, "
            "payload BLOB NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS search_receipts (identity TEXT PRIMARY KEY, "
            "payload BLOB NOT NULL)"
        )
    _rebuild_derivative_if_needed(root)


def _rebuild_derivative_if_needed(root: Path) -> None:
    """Recreate derivative pages after cache loss from captured Source bytes."""
    batch = _read(root, "batch")
    if not batch:
        return
    with _db(root, "derivative.sqlite3") as connection:
        existing = connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        indexed = connection.execute("SELECT COUNT(*) FROM source_index").fetchone()[0]
        version_row = connection.execute(
            "SELECT value FROM search_projection_meta WHERE name='version'"
        ).fetchone()
    rebuild_pages = not existing
    rebuild_search = version_row is None or version_row[0] != _SEARCH_DERIVATIVE_VERSION
    if existing and indexed and not rebuild_search:
        return
    COUNTERS["derivative_rebuilds"] += 1
    rows: list[tuple[str, int, str]] = []
    search_rows: list[tuple[str, int, str, str]] = []
    sources: list[tuple[str, str, str, bytes]] = []
    batch_identity = str(batch.get("identity", ""))
    for trial in batch.get("trials", []):
        for source in trial.get("sources", []):
            path = internal_path(root, "sources", trial["id"], f"{source['id']}.bin")
            if not path.is_file():
                raise ValueError("captured Source bytes are unavailable")
            data = path.read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != source.get("sha256"):
                raise ValueError("captured Source bytes do not match Canonical identity")
            if source["id"] != _source_id(trial["id"], source["logical_path"], source["sha256"]):
                raise ValueError("captured Source projection identity is corrupt")
            pages = _pages(Path(source["logical_path"]), data)
            media_type = str(source["media_type"])
            if _projection_hash(source["sha256"], media_type, pages) != source.get(
                "projection_hash"
            ):
                raise ValueError("captured Source projection identity is corrupt")
            if rebuild_pages:
                rows.extend((source["id"], page, text) for page, text in enumerate(pages, 1))
            if rebuild_search:
                search_rows.extend(
                    (source["id"], page, *_search_derivative(text))
                    for page, text in enumerate(pages, 1)
                )
            sources.append(
                (source["id"], batch_identity, trial["id"], canonical_json_bytes(source))
            )
    with _db(root, "derivative.sqlite3") as connection:
        if rebuild_pages:
            connection.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?)", rows)
        if rebuild_search:
            connection.execute("DELETE FROM pages_fts")
            connection.executemany("INSERT INTO pages_fts VALUES (?,?,?,?)", search_rows)
            connection.execute(
                "INSERT OR REPLACE INTO search_projection_meta(name,value) VALUES ('version',?)",
                (_SEARCH_DERIVATIVE_VERSION,),
            )
        connection.executemany(
            "INSERT OR REPLACE INTO source_index(source_id,batch_id,trial_id,payload) "
            "VALUES (?,?,?,?)",
            sources,
        )


def _read(root: Path, name: str) -> dict[str, Any] | None:
    """Read an active record only after checking its canonical ledger entry.

    ``records`` is deliberately just a mutable projection for cheap lookups.
    It is not an authority source: a restart must use the workflow head for
    State and verify every other projection against the immutable ledger.
    """

    with _db(root, "canonical.sqlite3") as connection:
        if name == "state":
            head = connection.execute(
                "SELECT revision, payload FROM workflow_head WHERE singleton=1"
            ).fetchone()
            if head is None:
                projection = connection.execute(
                    "SELECT payload FROM records WHERE name='state'"
                ).fetchone()
                canonical_state = connection.execute(
                    "SELECT 1 FROM canonical_records WHERE kind='state' LIMIT 1"
                ).fetchone()
                if projection is not None or canonical_state is not None:
                    raise ValueError("workflow head is missing")
                return None
            payload = bytes(head["payload"])
            value = _decode_object(payload, "workflow head")
            revision = value.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise ValueError("workflow head revision is invalid")
            if revision != int(head["revision"]):
                raise ValueError("workflow head revision does not match payload")
            _verify_canonical_payload(connection, value, payload, expected_kind="state")
            projection = connection.execute(
                "SELECT payload FROM records WHERE name='state'"
            ).fetchone()
            if projection is None or bytes(projection["payload"]) != payload:
                raise ValueError("workflow state projection is corrupt")
            return value

        row = connection.execute("SELECT payload FROM records WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        payload = bytes(row["payload"])
        value = _decode_object(payload, f"record {name}")
        _verify_canonical_payload(connection, value, payload)
        return value


def _decode_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is corrupt") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def _verify_canonical_payload(
    connection: sqlite3.Connection,
    value: dict[str, Any],
    payload: bytes,
    *,
    expected_kind: str | None = None,
) -> None:
    """Verify payload bytes, their recorded digest, and their content identity."""

    identity = str(value.get("identity") or _identity(value))
    row = connection.execute(
        "SELECT identity, kind, payload, payload_hash FROM canonical_records WHERE identity=?",
        (identity,),
    ).fetchone()
    payload_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    if (
        row is None
        or bytes(row["payload"]) != payload
        or row["payload_hash"] != payload_hash
        or hashlib.sha256(bytes(row["payload"])).hexdigest()
        != str(row["payload_hash"]).removeprefix("sha256:")
        or (expected_kind is not None and row["kind"] != expected_kind)
    ):
        raise ValueError("canonical record integrity check failed")


def _write(root: Path, values: dict[str, dict[str, Any]]) -> None:
    with _db(root, "canonical.sqlite3") as connection:
        for name, value in values.items():
            connection.execute(
                "INSERT OR REPLACE INTO records VALUES (?,?)", (name, canonical_json_bytes(value))
            )
            COUNTERS["serialized_bytes"] += len(canonical_json_bytes(value))


def _state(root: Path) -> dict[str, Any]:
    return _read(root, "state") or {"phase": "empty", "revision": 0, "trial_dispositions": {}}


def _commit(root: Path, state: dict[str, Any], expected: int | None) -> dict[str, Any]:
    current = _state(root)
    if expected is not None and expected != current.get("revision", 0):
        raise WorkflowConflict(expected, int(current.get("revision", 0)))
    return _commit_records(root, state, expected, {})


def _commit_records(
    root: Path, state: dict[str, Any], expected: int | None, records: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Commit the revision check and every Canonical write on one connection."""
    with _db(root, "canonical.sqlite3") as connection:
        connection.execute("BEGIN IMMEDIATE")
        head = connection.execute(
            "SELECT revision, payload FROM workflow_head WHERE singleton=1"
        ).fetchone()
        if head is None:
            projection = connection.execute(
                "SELECT payload FROM records WHERE name='state'"
            ).fetchone()
            canonical_state = connection.execute(
                "SELECT 1 FROM canonical_records WHERE kind='state' LIMIT 1"
            ).fetchone()
            if projection is not None or canonical_state is not None:
                raise ValueError("workflow head is missing")
            current: dict[str, Any] = {}
        else:
            current = _decode_object(bytes(head["payload"]), "workflow head")
            revision_value = current.get("revision")
            if isinstance(revision_value, bool) or not isinstance(revision_value, int):
                raise ValueError("workflow head revision is invalid")
            if revision_value != int(head["revision"]):
                raise ValueError("workflow head revision does not match payload")
            _verify_canonical_payload(
                connection, current, bytes(head["payload"]), expected_kind="state"
            )
            projection = connection.execute(
                "SELECT payload FROM records WHERE name='state'"
            ).fetchone()
            if projection is None or bytes(projection["payload"]) != bytes(head["payload"]):
                raise ValueError("workflow state projection is corrupt")
        revision = int(current.get("revision", 0))
        # The state projection used to build ``records`` is itself a compare-
        # and-swap basis.  This protects callers which omit an explicit
        # revision as well as callers which supply one: validation, state
        # check, and every Canonical write are one SQLite transaction.
        basis = int(state.get("revision", 0))
        required_revision = basis if expected is None else expected
        if required_revision != revision:
            raise WorkflowConflict(required_revision, revision)
        committed = {**state, "revision": revision + 1}
        for name, value in {"state": committed, **records}.items():
            payload = canonical_json_bytes(value)
            connection.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (name, payload))
            identity = str(value.get("identity") or _identity(value))
            kind = (
                "evidence"
                if name.startswith("evidence:")
                else str(value.get("kind") or name.split(":", 1)[0])
            )
            batch_id = value.get("batch_id") or value.get("batch_identity")
            trial_id = value.get("trial_id")
            existing = connection.execute(
                "SELECT payload_hash FROM canonical_records WHERE identity=?", (identity,)
            ).fetchone()
            payload_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
            if existing is not None and existing[0] != payload_hash:
                raise ValueError("canonical identity collision")
            connection.execute(
                "INSERT OR IGNORE INTO canonical_records "
                "(identity,kind,batch_id,trial_id,payload,payload_hash) VALUES (?,?,?,?,?,?)",
                (identity, kind, batch_id, trial_id, payload, payload_hash),
            )
            if name == "state":
                connection.execute(
                    "INSERT OR REPLACE INTO workflow_head"
                    "(singleton,revision,payload) VALUES (1,?,?)",
                    (committed["revision"], payload),
                )
            COUNTERS["serialized_bytes"] += len(payload)
    return committed


def _canonical_evidence_records(root: Path, identities: set[str]) -> dict[str, dict[str, Any]]:
    """Load only the promoted Evidence records named by a Domain history."""
    if not identities:
        return {}
    placeholders = ",".join("?" for _ in identities)
    with _db(root, "canonical.sqlite3") as connection:
        rows = connection.execute(
            "SELECT identity,payload,kind FROM canonical_records "
            f"WHERE kind='evidence' AND identity IN ({placeholders})",
            tuple(sorted(identities)),
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = _decode_object(bytes(row[1]), "canonical Evidence")
        if row[0] != item.get("identity") or item.get("kind") not in {"narrative", "figure"}:
            raise ValueError("canonical Evidence record is corrupt")
        result[str(row[0])] = item
    return result


def _identity(value: Any) -> str:
    return sha256(value)


def _result(outcome: str, state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "state_revision": state.get("revision", 0),
        "phase": state.get("phase", "empty"),
        **extra,
    }


def _supported(path: Path, data: bytes) -> bool:
    return data.startswith(b"%PDF-") or path.suffix.lower() in {".txt", ".md", ".csv", ".json"}


def _pages(path: Path, data: bytes) -> tuple[str, ...]:
    COUNTERS["extraction_calls"] += 1
    if data.startswith(b"%PDF-"):
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            pages = [document[number].get_text() for number in range(len(document))]
            table_pages: dict[int, tuple[Any, ...]] = {}
            for number in range(len(document)):
                tables = getattr(document[number].find_tables(), "tables", ())
                if _semantic_table_page(tables):
                    table_pages[number] = tuple(tables)
            if not table_pages:
                return tuple(pages)
            for number, tables in table_pages.items():
                rendered = [
                    _table_gfm(table, index)
                    for index, table in enumerate(tables, start=1)
                    if _textual_table_shape(table)
                ]
                if rendered:
                    pages[number] = pages[number].rstrip() + "\n\n" + "\n\n".join(rendered) + "\n"
            return tuple(pages)
        finally:
            document.close()
    return (data.decode("utf-8"),)


def _semantic_table_page(tables: Any) -> bool:
    """Return whether table geometry describes a textual table worth relaying.

    ``find_tables`` also reports the small boxed regions used by disclosure
    forms and other administrative pages.  Shape and cell text are available
    from that one scan, so reject those pages before paying for the layout
    projection.  The check deliberately stays structural: it does not infer
    anything from a filename or trial-specific vocabulary.
    """
    candidates = tuple(tables or ())
    if not candidates:
        return False
    small_regions = sum(
        1
        for table in candidates
        if int(getattr(table, "row_count", 0) or 0) <= 3
        or int(getattr(table, "col_count", 0) or 0) <= 2
    )
    if len(candidates) >= 4 and small_regions >= len(candidates) - 1:
        return False
    return any(_textual_table_shape(table) for table in candidates)


def _textual_table_shape(table: Any) -> bool:
    """Accept a multi-row/column table only when it contains real cell text."""
    rows = int(getattr(table, "row_count", 0) or 0)
    columns = int(getattr(table, "col_count", 0) or 0)
    compact_result = rows == 3 and columns == 3
    if not ((rows >= 4 and columns >= 2) or (rows >= 3 and columns >= 4) or compact_result):
        return False
    try:
        extracted = table.extract()
    except Exception as exc:
        raise ValueError("selected PDF table extraction failed") from exc
    if not isinstance(extracted, list) or any(not isinstance(row, list) for row in extracted):
        raise ValueError("selected PDF table extraction returned malformed rows")
    cells = []
    for row in extracted:
        for cell in row:
            if cell is not None and not isinstance(cell, str):
                raise ValueError("selected PDF table extraction returned a non-text cell")
            if isinstance(cell, str) and cell.strip():
                cells.append(cell.strip())
    if compact_result:
        # A three-by-three result table is the smallest useful table shape:
        # one header row and two comparison rows.  Require at least two text
        # cells in every row so sparse ruled forms do not become evidence.
        nonempty_by_row = [sum(bool(cell and cell.strip()) for cell in row) for row in extracted]
        if min(nonempty_by_row, default=0) < 2 or len(cells) < 7:
            return False
    return len(cells) >= 4 and sum(len(cell) for cell in cells) >= 12


def _table_gfm(table: Any, index: int) -> str:
    """Render one selected ``find_tables`` result without parser metadata."""
    try:
        rows = table.extract()
    except Exception as exc:
        raise ValueError("selected PDF table extraction failed") from exc
    if not isinstance(rows, list) or not rows or any(not isinstance(row, list) for row in rows):
        raise ValueError("selected PDF table extraction returned malformed rows")
    width = int(getattr(table, "col_count", 0) or 0)
    if width < 2:
        raise ValueError("selected PDF table extraction returned an invalid width")
    normalized: list[list[str]] = []
    for row in rows:
        if len(row) > width:
            raise ValueError("selected PDF table extraction exceeded its declared width")
        normalized.append([_table_cell(value) for value in row] + [""] * (width - len(row)))
    if not normalized:
        raise ValueError("selected PDF table extraction returned no rows")
    use_first_row_header = sum(bool(value) for value in normalized[0]) >= 2
    header = (
        normalized[0]
        if use_first_row_header
        else [f"Column {column}" for column in range(1, width + 1)]
    )
    separator = ["---"] * width
    body = normalized[1:] if use_first_row_header else normalized
    lines = [f"[Extracted table {index}]", _table_row(header), _table_row(separator)]
    lines.extend(_table_row(row) for row in body)
    return "\n".join(lines)


def _table_cell(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("selected PDF table extraction returned a non-text cell")
    lines = [" ".join(line.split()) for line in value.replace("\r", "\n").split("\n")]
    return "<br>".join(line for line in lines if line).replace("|", "\\|")


def _table_row(row: list[str]) -> str:
    return "|" + "|".join(row) + "|"


def _reserved_role(name: str) -> str:
    stem = Path(name).stem.casefold()
    if "disclosure" in stem:
        return "other"
    if "protocol" in stem:
        return "protocol"
    if "sap" in stem or "analysis" in stem:
        return "sap"
    if "supp" in stem or "appendix" in stem:
        return "supplement"
    if "registry" in stem or "nct" in stem:
        return "registry"
    if Path(name).suffix.casefold() == ".pdf":
        return "main_article"
    return "other"


_SOURCE_ROLE_ORDER = {
    "main_article": 0,
    "registry": 1,
    "supplement": 2,
    "sap": 3,
    "protocol": 4,
}


def _source_order_key(source: dict[str, Any]) -> tuple[int, str, str]:
    """Return the deterministic discovery order for one captured Source."""
    return (
        _SOURCE_ROLE_ORDER.get(str(source.get("role")), 5),
        str(source.get("logical_path", "")).casefold(),
        str(source.get("id", "")),
    )


def _ordered_sources(sources: Any) -> list[dict[str, Any]]:
    return sorted(
        (source for source in sources if isinstance(source, dict)),
        key=_source_order_key,
    )


def _manifest(path: Path) -> dict[str, Any]:
    manifest = path / "sources.toml"
    if not manifest.exists():
        return {}
    with manifest.open("rb") as stream:
        value = tomllib.load(stream)
    if not isinstance(value, dict):
        raise ValueError("invalid sources.toml")
    allowed = {"omissions", "roles", "sources", "registry", "nct", "nct_id"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"sources.toml has unknown fields: {', '.join(unknown)}")
    for key in ("nct", "nct_id"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"sources.toml {key} must be a string")
    if "omissions" in value:
        omissions = value["omissions"]
        if not isinstance(omissions, list) or not all(
            (
                isinstance(item, str)
                and bool(item)
                and not Path(item).is_absolute()
                and ".." not in Path(item).parts
            )
            or (
                isinstance(item, dict)
                and set(item) == {"path", "reason", "rationale"}
                and isinstance(item.get("path"), str)
                and bool(item["path"])
                and not Path(item["path"]).is_absolute()
                and ".." not in Path(item["path"]).parts
                and isinstance(item.get("reason"), str)
                and bool(item["reason"])
                and item["reason"]
                in {"duplicate", "irrelevant", "unreadable", "restricted", "other"}
                and isinstance(item.get("rationale"), str)
                and bool(item["rationale"])
            )
            for item in omissions
        ):
            raise ValueError(
                "sources.toml omissions must contain safe paths or path/reason/rationale records"
            )
    if "roles" in value:
        roles = value["roles"]
        if not isinstance(roles, dict) or not all(
            isinstance(key, str) and isinstance(role, str) and role in SourceRole._value2member_map_
            for key, role in roles.items()
        ):
            raise ValueError(
                "sources.toml roles must map paths to main_article, registry, "
                "supplement, sap, protocol, or other"
            )
    if "sources" in value:
        sources = value["sources"]
        if not isinstance(sources, list) or not all(
            isinstance(item, dict)
            and set(item) <= {"path", "file", "role"}
            and "role" in item
            and ("path" in item or "file" in item)
            and isinstance(item.get("path", item.get("file")), str)
            and bool(item.get("path", item.get("file")))
            and isinstance(item.get("role"), str)
            and item["role"] in SourceRole._value2member_map_
            for item in sources
        ):
            raise ValueError("sources.toml sources must contain a path or file and a valid role")
    return value


def _source_id(trial_id: str, relative: str, digest: str) -> str:
    return "source_" + hashlib.sha256(f"{trial_id}\0{relative}\0{digest}".encode()).hexdigest()


def _projection_hash(source_sha256: str, media_type: str, pages: tuple[str, ...]) -> str:
    """Freeze the exact extraction recipe and every page's UTF-8 bytes."""
    return _identity(
        {
            "recipe": "rob2-kit.extract-pages.v2",
            "source_sha256": source_sha256,
            "media_type": media_type,
            "page_hashes": [
                "sha256:" + hashlib.sha256(page.encode("utf-8")).hexdigest() for page in pages
            ],
        }
    )
