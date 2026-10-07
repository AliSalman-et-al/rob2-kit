from __future__ import annotations

import copy
import sqlite3
from pathlib import Path

from support.rob2 import _assessment_workspace, _call

from rob2_kit.application._state import _db, _root, _state, internal_path
from rob2_kit.application.domains import get_domain_context
from rob2_kit.application.working import _delivery_projection, _source_scope
from scripts.profile_domain_context_delivery import _reconstruct


def test_compact_history_preserves_scientific_fields_and_recovers_after_restart(
    tmp_path: Path,
) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    root = _root(workspace)
    before = {
        name: internal_path(root, name).read_bytes()
        for name in ("canonical.sqlite3", "working.sqlite3")
    }
    compact = get_domain_context(workspace, "trial", "domain:randomization")
    full = get_domain_context(
        workspace, "trial", "domain:randomization", include_delivery_history=True
    )
    state = _state(root)
    original = _delivery_projection(
        root, state, "trial", _source_scope(state, "trial"), range_limit=None
    )
    assert full["delivery_history"] == list(original["ranges"])
    assert compact["delivery_history"] == []
    assert compact["investigation"]["coverage"]["range_count"] == original["range_count"]
    assert compact["delivery_history_recovery"]["arguments"] == {
        "trial_id": "trial",
        "domain_id": "domain:randomization",
        "include_delivery_history": True,
    }
    scientific = copy.deepcopy(full)
    scientific["delivery_history"] = []
    assert scientific == compact
    pages = {}
    response = _call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:randomization",
            "include_delivery_history": True,
            "max_response_bytes": 16_384,
        },
    )
    while True:
        page = response["data"]["context_page"]
        pages[page["index"]] = response
        cursor = page["next_cursor"]
        if not cursor:
            break
        response = _call(workspace, "get_domain_context", {"cursor": cursor})
    reconstructed = _reconstruct(pages)
    assert reconstructed is not None
    assert reconstructed["delivery_history"] == full["delivery_history"]
    # Loss of disposable frozen-view cache cannot erase delivery intervals.
    with _db(root, "derivative.sqlite3") as connection:
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            if "context" in table and "view" in table:
                connection.execute(f'DELETE FROM "{table}"')
    rebuilt = get_domain_context(
        workspace, "trial", "domain:randomization", include_delivery_history=True
    )
    assert rebuilt == full
    assert {name: internal_path(root, name).read_bytes() for name in before} == before


def test_full_delivery_history_exceeds_legacy_preview_without_erasing_gaps(tmp_path: Path) -> None:
    from rob2_kit.application._state import _ensure
    from rob2_kit.workflow_models import WorkingSourceBinding

    _ensure(_root(tmp_path))
    source = "source_" + "a" * 64
    bindings = (WorkingSourceBinding(source_id=source, projection_hash="sha256:" + "b" * 64),)
    state = {"batch": {"identity": "batch"}}
    with _db(tmp_path, "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT INTO pages VALUES (?,?,?)", (source, 1, "\n".join(["line"] * 300))
        )
        connection.executemany(
            "INSERT INTO page_reads VALUES (?,?,?,?,?,?,?)",
            [("batch", "assessment", "trial", source, 1, n, n) for n in range(1, 280, 2)],
        )
    preview = _delivery_projection(tmp_path, state, "trial", bindings)
    full = _delivery_projection(tmp_path, state, "trial", bindings, range_limit=None)
    assert preview["range_count"] == full["range_count"] == 140
    assert len(preview["ranges"]) == 128 and preview["ranges_truncated"]
    assert len(full["ranges"]) == 140 and not full["ranges_truncated"]
    assert full["ranges"][:128] == preview["ranges"]
    assert all(r["start_line"] == r["end_line"] for r in full["ranges"])
    with sqlite3.connect(internal_path(tmp_path, "derivative.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM page_reads").fetchone()[0] == 140
