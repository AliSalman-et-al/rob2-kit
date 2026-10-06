"""Read-only partial-assessment inventory and safe session/usage metadata."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
OLD = ROOT / "docs/evaluation/2026-10-03-gupta-full-validation"
RUN = ROOT.parent / "diagnostics/gupta-validation-fcd83d7"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


protected = [*OLD.glob("*.json"), *OLD.glob("*.jsonl"), *OLD.glob("*.sqlite3")]
protected += list((RUN / "workspace/.rob2-kit").glob("*.sqlite3"))
sessions = list((RUN / "home/sessions").rglob("*.jsonl"))
assert len(sessions) == 1
protected += sessions
before = {str(p): digest(p) for p in protected}
with sqlite3.connect(
    f"file:{(RUN / 'workspace/.rob2-kit/canonical.sqlite3').resolve()}?mode=ro", uri=True
) as c:
    revision, payload = c.execute("SELECT revision,payload FROM workflow_head").fetchone()
    state = json.loads(payload)
assert revision == 8 and state["phase"] == "assessment"
assert len(state["domain_records"]) == 4 and not state.get("trial_closures")
sources = []
for source in state["batch"]["trials"][0]["sources"]:
    path = RUN / "workspace/.rob2-kit/sources/gupta-2024" / (source["id"] + ".bin")
    assert digest(path) == source["sha256"].removeprefix("sha256:")
    sources.append(
        {
            "source_id": source["id"],
            "logical_path": source["logical_path"],
            "sha256_verified": source["sha256"],
            "projection_hash": source["projection_hash"],
        }
    )
turns = []
contexts = []
d5_start = None
for line in sessions[0].read_text().splitlines():
    row = json.loads(line)
    payload = row.get("payload") or {}
    if row.get("type") == "event_msg" and payload.get("type") in (
        "task_started",
        "task_complete",
        "turn_aborted",
    ):
        turns.append(
            {
                "timestamp": row.get("timestamp"),
                "type": payload["type"],
                "turn_id": payload.get("turn_id"),
            }
        )
    if row.get("type") == "turn_context":
        contexts.append({key: payload.get(key) for key in ("turn_id", "model", "effort", "cwd")})
    if (
        row.get("type") == "response_item"
        and payload.get("type") == "function_call"
        and payload.get("name") == "get_domain_context"
    ):
        args = json.loads(payload.get("arguments", "{}"))
        if args.get("domain_id") == "domain:selection" and d5_start is None:
            d5_start = row["timestamp"]
usage = json.loads((OLD / "durable-token-usage-records.json").read_text())
stage = [r for r in usage if r.get("timestamp", "") >= d5_start]
stage_usage = {
    key: sum(r["usage"].get(key, 0) for r in stage)
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
}
status = json.loads((OLD / "final-status.json").read_text())
assert before == {str(p): digest(p) for p in protected}
result = {
    "model_calls": 0,
    "original_run_hashes_unchanged": before,
    "revision": revision,
    "phase": state["phase"],
    "approved_result": state["proposal"]["payload"]["results"][0],
    "proposal_acknowledgment": state["proposal_acknowledgment"],
    "saved_domain_identities": {k: v["identity"] for k, v in state["domain_records"].items()},
    "continuation": status["continuation"],
    "conditions": status["conditions"],
    "main_report_reading": status["main_report_reading"],
    "working_checkpoint_status": {
        k: status["working_checkpoint"].get(k) for k in ("status", "reason", "checkpoint_identity")
    },
    "sources_verified": sources,
    "session_path": str(sessions[0]),
    "session_turn_status": turns,
    "model_context": contexts,
    "session_recovery_runtime_verified": False,
    "D5_timestamp_boundary": d5_start,
    "D5_tail_per_response_count": len(stage),
    "D5_tail_usage_request_telemetry_only": stage_usage,
    "D5_tail_max_single_request_input": max(r["usage"]["input_tokens"] for r in stage),
    "old_run_usage_unchanged": json.loads((OLD / "usage.json").read_text()),
}
(OUT / "readiness.json").write_text(json.dumps(result, indent=2) + "\n")
print(
    json.dumps(
        {
            "actual_head": revision,
            "remaining_domain": "selection",
            "sources_verified": len(sources),
            "originals_unchanged": True,
            "D5_tail_usage": stage_usage,
        }
    )
)
