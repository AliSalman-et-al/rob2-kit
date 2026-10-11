from __future__ import annotations

import copy
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
