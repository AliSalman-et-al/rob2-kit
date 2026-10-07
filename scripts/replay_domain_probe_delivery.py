"""Replay recorded Domain context through existing pagination without model inference."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from rob2_kit.interfaces.mcp.server import (
    _domain_context_transport_bytes,
    _paginate_domain_context_transport,
)
from scripts.profile_domain_context_delivery import _reconstruct


def replay(events: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    item = next(
        row["item"]
        for row in rows
        if row.get("type") == "item.completed"
        and row.get("item", {}).get("tool") == "get_domain_context"
    )
    original = copy.deepcopy(item["result"]["structured_content"])
    original["data"].pop("context_page")
    cursor = None
    pages = []
    responses = {}
    while True:
        page = _paginate_domain_context_transport(
            original, cursor, None, "offline-replay", original["head"]["state_revision"]
        )
        data = page["data"]
        responses[data["context_page"]["index"]] = page
        pages.append(
            {"index": data["context_page"]["index"], "bytes": _domain_context_transport_bytes(page)}
        )
        assert pages[-1]["bytes"] <= 32768
        assert data["context_page"]["stable_recovery"]["operation"] == "get_domain_context"
        cursor = data["context_page"]["next_cursor"]
        if cursor is None:
            break
    recovered = _reconstruct(responses)
    assert recovered is not None
    # Current transport supplies empty arrays absent from a historical envelope.
    # Remove only those defaults; retain every original field and its exact value.
    for name in set(recovered) - set(original["data"]):
        assert name in (
            "primary_report",
            "questions",
            "evidence",
            "comparison_cards",
            "delivery_history",
        )
        assert recovered[name] == []
        del recovered[name]
    assert recovered == original["data"], "scientific data changed during pagination"
    return {
        "recorded_requested_bytes": item["arguments"]["max_response_bytes"],
        "recorded_native_bytes": _domain_context_transport_bytes(
            item["result"]["structured_content"]
        ),
        "default_pages": pages,
        "scientific_data_recovered_exactly": True,
        "all_recovery_cursors_preserved": True,
        "delivery_history_ranges_recovered": len(recovered.get("delivery_history", [])),
        "limitations": (
            "Server replay only; native client/model delivery has not been run with inference."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.events), indent=2))
