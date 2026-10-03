"""Replay frozen navigation receipts without source or model calls."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).parent
PATHS = {
    "exscel": ROOT / "docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl",
    "emperor": ROOT / "docs/evaluation/2026-10-03-emperor-final-8198144/events.jsonl",
}


def calls(path):
    return {
        event["item"]["id"]: event["item"]
        for line in path.read_text().splitlines()
        if (event := json.loads(line)).get("type") == "item.completed"
        and event.get("item", {}).get("type") == "mcp_tool_call"
    }


def data(call):
    return call["result"]["structured_content"]["data"]


exscel = calls(PATHS["exscel"])
emperor = calls(PATHS["emperor"])
pending = data(exscel["item_32"])["remaining_windows"]
assert [window["page"] for window in pending] == [191, 192, 193]
assert exscel["item_33"]["arguments"]["windows"] == pending
assert data(exscel["item_33"])["remaining_windows"] == []
assert emperor["item_8"]["arguments"]["pages"] == [21]
assert data(emperor["item_8"])["remaining_windows"] == []
assert data(emperor["item_8"])["pages"][0]["numbered_text"].rstrip().endswith("OR")
for trace in (exscel, emperor):
    assert not any(call["tool"] == "save_working_checkpoint" for call in trace.values())
assert any(call["tool"] == "close_trial" for call in exscel.values())
assert not any(call["tool"] in {"review_trial", "close_trial"} for call in emperor.values())
packet = {
    "decision": "reject runtime patch: no lost registered reading obligation demonstrated",
    "trace_sha256": {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in PATHS.items()
    },
    "exscel": {
        "pending_item_32": pending,
        "consumed_item_33": exscel["item_33"]["arguments"],
        "appendix_navigation_item_6": exscel["item_6"]["result"]["structured_content"],
        "review_item_35": exscel["item_35"]["result"]["structured_content"],
    },
    "emperor": {
        "search_item_7": emperor["item_7"]["result"]["structured_content"],
        "read_item_8": emperor["item_8"],
    },
}
(OUTPUT / "navigation-replay.json").write_text(json.dumps(packet, indent=2) + "\n")
print("Frozen navigation assertions passed; packet regenerated.")
