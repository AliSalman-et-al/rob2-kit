"""Offline cumulative Budget replay. No launcher; the paid case remains closed."""

from __future__ import annotations

import time
from typing import Any

from scripts.workflow_completion import tool_feedback


class Budget:
    def __init__(self, state: dict[str, Any] | None = None, *, clock=time.time):
        self.clock = clock
        self.state = state or {
            "start": clock(),
            "last": clock(),
            "turns": 0,
            "calls": [],
            "records": {},
            "previous_error": None,
            "identical": 0,
            "no_progress": 0,
            "stop": None,
            "session": None,
            "events": [],
        }

    def usage(self):
        return {
            k: sum(r["usage"].get(k, 0) for r in self.state["records"].values())
            for k in [
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            ]
        }

    def consume(self, row):
        s = self.state
        s["last"] = self.clock()
        item = row.get("item", {})
        if row.get("type") == "thread.started":
            sid = row["thread_id"]
            if s["session"] is not None and sid != s["session"]:
                s["stop"] = "session changed"
            s["session"] = sid
        if row.get("type") == "item.started" and item.get("type") == "mcp_tool_call":
            identity = f"{s['turns']}:{item['id']}"
            if identity not in s["calls"]:
                s["calls"].append(identity)
        if item.get("type") == "command_execution":
            s["stop"] = "unexpected model shell access"
        if row.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
            feedback = tool_feedback(item)
            self.state["events"].append(
                {
                    "event": "tool_feedback",
                    "kind": feedback.kind,
                    "retryable": feedback.retryable,
                    "original": dict(feedback.original),
                }
            )
            if feedback.fingerprint:
                s["identical"] = (
                    s["identical"] + 1 if feedback.fingerprint == s["previous_error"] else 1
                )
                s["previous_error"] = feedback.fingerprint
            elif item.get("tool") != "get_status":
                s["identical"] = 0
                s["previous_error"] = None

    def observe_session_record(self, row: dict[str, Any]) -> None:
        # CLI stdout omits code-mode wrappers. Count their durable call IDs once.
        payload = row.get("payload", {})
        if row.get("type") == "token_usage_record":
            self.state["records"][payload["response_id"]] = payload
        elif row.get("type") == "response_item" and payload.get("type") == "custom_tool_call":
            identity = "wrapper:" + payload["call_id"]
            if identity not in self.state["calls"]:
                self.state["calls"].append(identity)

    def boundary(self, before, after):
        keys = ["phase", "state_revision", "continuation", "main_report_reading", "host_progress"]
        progress = any(before.get(k) != after.get(k) for k in keys)
        self.state["no_progress"] = 0 if progress else self.state["no_progress"] + 1
        return progress

    def check(self):
        s = self.state
        u = self.usage()
        elapsed = self.clock() - s["start"]
        idle = self.clock() - s["last"]
        checks = [
            (elapsed >= 1200, "cumulative wall limit"),
            (idle >= 180, "idle limit"),
            (len(s["calls"]) >= 80, "cumulative tool limit"),
            (u["output_tokens"] >= 15000, "cumulative output limit"),
            (s["identical"] >= 2, "repeated identical error"),
            (s["no_progress"] >= 2, "two consecutive no-progress boundaries"),
        ]
        s["stop"] = s["stop"] or next((why for hit, why in checks if hit), None)
        return s["stop"]

    def begin_turn(self):
        if self.check():
            raise RuntimeError(self.state["stop"])
        if self.state["turns"] >= 3:
            raise RuntimeError("total three-turn allowance exhausted")
        self.state["turns"] += 1

    def remaining(self):
        return max(0, 1200 - (self.clock() - self.state["start"]))
