"""Measure retained public event projections; never infer provider context length."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).parent
CODE = Path("/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases")
DIAGNOSTICS = Path(__file__).resolve().parents[4] / "diagnostics"


def size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


sessions = {
    "exscel": [
        DIAGNOSTICS / "frozen-exscel-full-bd92ec8/events.jsonl",
        DIAGNOSTICS / "exscel-host-recovery/turn-0.events.jsonl",
    ],
    "monarch-2": [CODE / "monarch-2/turn-1.jsonl", CODE / "monarch-2/turn-2.jsonl"],
}
results = {}
for slug, paths in sessions.items():
    visible = []
    saved = []
    selected = []
    pages = []
    boundaries = []
    usage = []
    tools = []
    checkpoint_status = []
    current_domain = None
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            row = json.loads(line)
            item = row.get("item") or {}
            if row["type"] == "turn.completed":
                usage.append({"file": path.name, "usage": row["usage"]})
            if row["type"] != "item.completed":
                continue
            locator = {"file": str(path), "line": line_number, "item_id": item.get("id")}
            if item.get("type") != "mcp_tool_call":
                if item.get("type") == "agent_message":
                    visible.append({"text": item.get("text", "")})
                continue
            arguments = item.get("arguments") or {}
            result = (item.get("result") or {}).get("structured_content") or {}
            data = result.get("data") or {}
            tool = item["tool"]
            tools.append(tool)
            if tool == "get_status" and "working_checkpoint" in data:
                checkpoint_status.append({**locator, "checkpoint": data["working_checkpoint"]})
            domain = arguments.get("domain_id")
            if tool == "get_domain_context" and domain and domain != current_domain:
                current_domain = domain
                referenced_handles = {
                    basis.get("evidence")
                    for record in saved
                    for answer in record.get("answers", [])
                    for basis in answer.get("bases", [])
                    if basis.get("evidence")
                }
                cited = [
                    e
                    for e in selected
                    if e.get("handle") in referenced_handles
                    or e.get("identity") in referenced_handles
                ]
                uncovered = []
                for page in pages:
                    if not any(
                        e.get("source_id") == page["source_id"]
                        and e.get("page") == page["page"]
                        and e.get("start_line", 0) <= page["start_line"]
                        and e.get("end_line", 0) >= page["end_line"]
                        for e in cited
                    ):
                        uncovered.append(page)
                boundaries.append(
                    {
                        **locator,
                        "domain": domain,
                        "observed_prior_history_projection_bytes": sum(size(v) for v in visible),
                        "observed_prior_tool_calls": len(tools) - 1,
                        "fresh_first_context_response_bytes": size(result),
                        "saved_submission_bytes": size(saved),
                        "saved_domain_count": len(saved),
                        "saved_unknown_count": sum(
                            len(a.get("unknowns", [])) for d in saved for a in d.get("answers", [])
                        ),
                        "saved_counterevidence_count": sum(
                            len(a.get("counterevidence", []))
                            for d in saved
                            for a in d.get("answers", [])
                        ),
                        "uncited_or_partly_cited_prior_read_windows": uncovered,
                        "saved_submissions": list(saved),
                        "fresh_context_keys": list(data),
                        "boundary_working_checkpoint": data.get("working_checkpoint"),
                        "prior_domain_context_calls": tools[:-1].count("get_domain_context"),
                        "prior_read_windows": len(pages),
                        "unique_prior_read_windows": len(
                            {
                                (p["source_id"], p["page"], p["start_line"], p["end_line"])
                                for p in pages
                            }
                        ),
                    }
                )
            if tool == "save_domain_judgment" and result.get("outcome") == "success":
                saved.append(arguments)
            if tool == "select_text_evidence" and data.get("evidence"):
                selected.append(data["evidence"])
            for page in data.get("pages", []):
                if "numbered_text" in page:
                    pages.append(
                        {
                            **locator,
                            "source_id": page["source_id"],
                            "page": page["page"],
                            "start_line": page["returned_start_line"],
                            "end_line": page["returned_end_line"],
                        }
                    )
            visible.append({"tool": tool, "arguments": arguments, "result": result})
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    results[slug] = {
        "trace_hashes": hashes,
        "boundaries": boundaries,
        "turn_usage_not_context_length": usage,
        "explicit_checkpoint_calls": tools.count("save_working_checkpoint"),
        "status_checkpoint_receipts": checkpoint_status,
        "completed_tool_calls": len(tools),
        "history_scope": (
            "Only retained public completed event projections; "
            "no hidden host history, prompts, reasoning or schemas"
        ),
        "original_files_unchanged": True,
    }
write("measurements.json", results)
print(
    json.dumps(
        {
            s: [
                {
                    k: b[k]
                    for k in (
                        "domain",
                        "observed_prior_history_projection_bytes",
                        "fresh_first_context_response_bytes",
                        "saved_submission_bytes",
                        "saved_domain_count",
                    )
                }
                for b in r["boundaries"]
            ]
            for s, r in results.items()
        },
        indent=2,
    )
)
