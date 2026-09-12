"""Summarize one isolated RSI trace against five reference Domain labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

DOMAINS = ("randomization", "deviations", "missing", "measurement", "selection")
LABELS = {"low": "Low", "some_concerns": "Some", "high": "High"}


def _structured_response(item: dict[str, Any]) -> dict[str, Any] | None:
    """Read one complete MCP receipt without projecting away workflow state."""

    result = item.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("structured_content", "structuredContent"):
        structured = result.get(key)
        if isinstance(structured, dict):
            return structured
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _text_bytes(result: dict[str, Any]) -> int:
    content = result.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        len(part["text"].encode("utf-8"))
        for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--rank", type=int, required=True)
    args = parser.parse_args()

    with args.gold.open(encoding="utf-8-sig", newline="") as stream:
        gold = next(row for row in csv.DictReader(stream) if int(row["rank"]) == args.rank)
    calls: Counter[str] = Counter()
    searches = Counter()
    reads = Counter()
    mcp_payload = {
        "domain_context_calls": 0,
        "domain_context_parsed": 0,
        "domain_context_unparsed": 0,
        "domain_context_result_truncation_markers": 0,
        "domain_context_max_structured_bytes": 0,
        "domain_context_max_text_bytes": 0,
    }
    source_by_id: dict[str, dict[str, Any]] = {}
    final: dict[str, Any] | None = None
    for trace in sorted(args.run_dir.glob("phase-*.jsonl")):
        with trace.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                item = record.get("item") or {}
                if record.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
                    continue
                tool = item.get("tool")
                if not isinstance(tool, str):
                    continue
                calls[tool] += 1
                request = item.get("arguments") or {}
                raw_result = item.get("result") or {}
                response = _structured_response(item) or {}
                data = response.get("data") or {}
                if tool == "get_domain_context":
                    mcp_payload["domain_context_calls"] += 1
                    if response:
                        mcp_payload["domain_context_parsed"] += 1
                        mcp_payload["domain_context_max_structured_bytes"] = max(
                            mcp_payload["domain_context_max_structured_bytes"],
                            len(
                                json.dumps(
                                    response,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ).encode("utf-8")
                            ),
                        )
                    else:
                        mcp_payload["domain_context_unparsed"] += 1
                    mcp_payload["domain_context_max_text_bytes"] = max(
                        mcp_payload["domain_context_max_text_bytes"],
                        _text_bytes(raw_result) if isinstance(raw_result, dict) else 0,
                    )
                    if "Warning: truncated output" in json.dumps(
                        raw_result, ensure_ascii=False
                    ):
                        mcp_payload["domain_context_result_truncation_markers"] += 1
                if tool == "prepare_batch" and response.get("outcome") == "success":
                    for trial in data.get("trials", []):
                        for source in trial.get("sources", []):
                            source_by_id[source["id"]] = source
                if tool == "search_sources":
                    searches["calls"] += 1
                    if data.get("total_matches") == 0:
                        searches["zero_hits"] += 1
                    if request.get("cursor"):
                        searches["cursor_calls"] += 1
                    if request.get("source_id"):
                        role = source_by_id.get(request["source_id"], {}).get("role", "unknown")
                        searches[f"scoped_{role}"] += 1
                if tool == "read_pages" and response.get("outcome") == "success":
                    source_ids = {request.get("source_id")}
                    source_ids.update(
                        window.get("source_id") for window in request.get("windows", [])
                    )
                    for source_id in source_ids - {None}:
                        role = source_by_id.get(source_id, {}).get("role", "unknown")
                        reads[role] += 1
                if tool == "finalize_batch" and response.get("outcome") == "success":
                    final = data

    domains: dict[str, dict[str, Any]] = {}
    if final:
        summary = next(iter(final["assessment_summary"].values()))
        for index, name in enumerate(DOMAINS, 1):
            observed = summary["domains"][f"domain:{name}"]
            reference = gold[f"D{index}"]
            domains[f"D{index}"] = {
                "observed": LABELS[observed],
                "reference": reference,
                "agree": LABELS[observed] == reference,
            }
    result = {
        "rank": args.rank,
        "trial": gold["trial"],
        "finalized": final is not None,
        "domains": domains,
        "domain_agreement": sum(item["agree"] for item in domains.values()),
        "mcp_calls": dict(sorted(calls.items())),
        "searches": dict(sorted(searches.items())),
        "successful_reads_by_role": dict(sorted(reads.items())),
        "mcp_payload": mcp_payload,
        "source_hashes": {
            source["label"]: source["sha256"] for source in source_by_id.values()
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
