from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from scripts.workflow_completion import tool_feedback

ROOT = Path(__file__).parents[1]
PAID = ROOT / "docs/archive/evaluation/2026-10-03-gupta-full-validation"
PATCH = ROOT / "docs/archive/evaluation/2026-10-03-gupta-guard-image-audit/bounded_launcher.py"
spec = importlib.util.spec_from_file_location("offline_gupta_budget", PATCH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def native_error():
    for line in (PAID / "turn-2.jsonl").read_text().splitlines():
        row = json.loads(line)
        item = row.get("item", {})
        if (
            row.get("type") == "item.completed"
            and item.get("tool") == "read_pages"
            and (item.get("result") or {}).get("structured_content") is None
        ):
            return row
    raise AssertionError("retained error absent")


def test_exact_error_replay_across_resume_preserves_all_counters_and_details():
    now = [0.0]
    b = module.Budget(clock=lambda: now[0])
    b.begin_turn()
    b.state["records"]["original"] = {"usage": {"output_tokens": 9000, "input_tokens": 8000000}}
    b.state["calls"] = ["existing-call"]
    error = native_error()
    b.consume(error)
    assert b.state["identical"] == 1
    state = json.loads(json.dumps(b.state))
    now[0] = 100.0
    b = module.Budget(state, clock=lambda: now[0])
    b.begin_turn()
    b.consume(
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "get_status",
                "result": {"structured_content": {"outcome": "success"}},
            },
        }
    )
    b.consume(error)
    assert b.check() == "repeated identical error"
    assert b.state["turns"] == 2 and b.usage()["output_tokens"] == 9000
    assert b.state["calls"] == ["existing-call"] and b.remaining() == 1100
    assert b.state["events"][-1]["original"] == error["item"]
    assert b.state["previous_error"] == tool_feedback(error["item"]).fingerprint


def test_successful_read_or_image_clears_failure_but_does_not_reset_limits():
    b = module.Budget(clock=lambda: 0)
    b.consume(native_error())
    b.state["records"]["r"] = {"usage": {"output_tokens": 15000}}
    b.consume(
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "render_page",
                "result": {"content": [{"type": "image", "data": "pixels"}]},
            },
        }
    )
    assert b.state["identical"] == 0 and b.check() == "cumulative output limit"


def test_wrappers_hidden_from_stdout_count_once_across_resume():
    b = module.Budget(clock=lambda: 0)
    b.state["calls"] = [f"mcp:{n}" for n in range(79)]
    row = {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "same"}}
    b.observe_session_record(row)
    resumed = module.Budget(json.loads(json.dumps(b.state)), clock=lambda: 0)
    resumed.observe_session_record(row)
    assert len(resumed.state["calls"]) == 80
    assert resumed.check() == "cumulative tool limit"
