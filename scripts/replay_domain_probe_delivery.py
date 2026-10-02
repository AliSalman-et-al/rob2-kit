"""Replay recorded Domain context through existing pagination without model inference."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from rob2_kit.interfaces.mcp.server import (
    _DOMAIN_CONTEXT_PAGE_SECTIONS,
    _domain_context_transport_bytes,
    _paginate_domain_context_transport,
)


def replay(events: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    item = next(
        row["item"]
        for row in rows
        if row.get("type") == "item.completed"
        and row.get("item", {}).get("tool") == "get_domain_context"
    )
    original = copy.deepcopy(item["result"]["structured_content"])
    original["data"].pop("context_page")
    sections = {name: [] for name in _DOMAIN_CONTEXT_PAGE_SECTIONS}
    cursor = None
    pages = []
    header = None
    while True:
        page = _paginate_domain_context_transport(
            original, cursor, None, "offline-replay", original["head"]["state_revision"]
        )
        data = page["data"]
        if header is None:
            header = {k: v for k, v in data.items() if k not in sections and k != "context_page"}
        for name in sections:
            sections[name].extend(data.get(name, []))
        pages.append(
            {"index": data["context_page"]["index"], "bytes": _domain_context_transport_bytes(page)}
        )
        assert pages[-1]["bytes"] <= 32768
        assert data["context_page"]["stable_recovery"]["operation"] == "get_domain_context"
        cursor = data["context_page"]["next_cursor"]
        if cursor is None:
            break
    assert {**header, **sections} == original["data"], "scientific data changed during pagination"
    return {
        "recorded_requested_bytes": item["arguments"]["max_response_bytes"],
        "recorded_native_bytes": _domain_context_transport_bytes(
            item["result"]["structured_content"]
        ),
        "default_pages": pages,
        "scientific_data_recovered_exactly": True,
        "all_recovery_cursors_preserved": True,
        "limitations": (
            "Server replay only; native client/model delivery has not been run with inference."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.events), indent=2))
