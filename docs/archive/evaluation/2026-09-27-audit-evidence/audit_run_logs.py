#!/usr/bin/env python3
"""Reproduce compact run inventory, trace metrics, and paired label comparison."""
import csv
import hashlib
import json
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / "eval" / "runs"
DAY_ROOTS = [RUNS / d for d in ("2026-09-26", "2026-09-27")]
BASE_SCORE = DAY_ROOTS[0] / "rob2-trial-benchmark-luna-medium" / "all-case-accuracy.json"
LATEST_SCORE = DAY_ROOTS[1] / "rob2-trial-benchmark-latest-8ae8016" / "accuracy.json"
DOMAINS = ["D1", "D2", "D3", "D4", "D5", "overall"]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


inventory, all_hashes = {}, defaultdict(list)
for day in DAY_ROOTS:
    files = sorted(day.rglob("*.jsonl"))
    counts, tools, item_types, phase_counts = Counter(), Counter(), Counter(), Counter()
    result_bytes, errors, malformed = 0, [], []
    per_root = Counter()
    for path in files:
        digest = sha256(path)
        all_hashes[digest].append(str(path.relative_to(ROOT)))
        rel = path.relative_to(day)
        per_root[rel.parts[0]] += 1
        phase_counts[path.name] += 1
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                try:
                    event = json.loads(line)
                except Exception as exc:
                    malformed.append({"path": str(path.relative_to(ROOT)), "line": line_no, "error": str(exc)})
                    continue
                counts[event.get("type", "?")] += 1
                item = event.get("item", {})
                if event.get("type", "").startswith("item."):
                    item_types[item.get("type", "?")] += 1
                if event.get("type") == "error":
                    errors.append({"path": str(path.relative_to(ROOT)), "message": event.get("message", "")})
                if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                    tools[item.get("tool", "?")] += 1
                    result_bytes += len(json.dumps(item.get("result"), ensure_ascii=False).encode("utf-8"))
    inventory[str(day.name)] = {
        "jsonl_files": len(files),
        "file_bytes": sum(p.stat().st_size for p in files),
        "files_by_run_root": dict(per_root),
        "phase_files": dict(phase_counts),
        "events": dict(counts),
        "item_types": dict(item_types),
        "completed_mcp_calls_by_tool": dict(tools),
        "completed_mcp_call_count": sum(tools.values()),
        "serialized_mcp_result_bytes": result_bytes,
        "errors": errors,
        "malformed_lines": malformed,
    }
inventory["duplicate_jsonl_content_groups"] = [paths for paths in all_hashes.values() if len(paths) > 1]


def trace_metrics(run_root):
    files = sorted(run_root.rglob("*.jsonl"))
    tools, item_types, event_types = Counter(), Counter(), Counter()
    result_bytes, result_sizes, search_ones = 0, [], []
    no_hits, errors = [], []
    broad_searches, truncated_searches, query_modes = [], 0, Counter()
    response_outcomes, repair_codes = Counter(), Counter()
    context_continuations, search_counts_unknown = 0, 0
    for path in files:
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                event_types[event.get("type", "?")] += 1
                item = event.get("item", {})
                if event.get("type", "").startswith("item."):
                    item_types[item.get("type", "?")] += 1
                if event.get("type") == "error":
                    errors.append({"path": str(path.relative_to(ROOT)), "line": line_no, "message": event.get("message", "")})
                if event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
                    continue
                tool = item.get("tool", "?")
                tools[tool] += 1
                result = item.get("result") or {}
                sc = result.get("structured_content") or result.get("structuredContent") or {}
                response_outcomes[sc.get("outcome", "unstructured_or_unknown")] += 1
                if tool == "get_domain_context" and item.get("arguments", {}).get("cursor"):
                    context_continuations += 1
                for repair in sc.get("repairs", []):
                    if isinstance(repair, dict):
                        repair_codes[repair.get("code", "unknown")] += 1
                size = len(json.dumps(item.get("result"), ensure_ascii=False).encode("utf-8"))
                result_sizes.append(size)
                result_bytes += size
                if tool == "search_sources":
                    data = sc.get("data") or {}
                    hits = data.get("total_matches")
                    if not isinstance(hits, int):
                        search_counts_unknown += 1
                        continue
                    search_ones.append(hits)
                    query_modes[item.get("arguments", {}).get("mode", "unspecified")] += 1
                    if hits == 0:
                        no_hits.append({"trial": item.get("arguments", {}).get("trial_id"), "query": item.get("arguments", {}).get("query", "")})
                    if hits > 100:
                        broad_searches.append({"trial": item.get("arguments", {}).get("trial_id"), "query": item.get("arguments", {}).get("query", ""), "hits": hits})
                    truncated_searches += bool(data.get("truncated"))
    return {
        "jsonl_segments": len(files), "event_types": dict(event_types), "item_types": dict(item_types),
        "completed_mcp_calls_by_tool": dict(tools), "completed_mcp_call_count": sum(tools.values()),
        "response_outcomes": dict(response_outcomes), "repair_codes": dict(repair_codes),
        "domain_context_continuation_calls": context_continuations,
        "serialized_mcp_result_bytes": result_bytes,
        "serialized_mcp_result_bytes_per_call": {
            "mean": round(statistics.mean(result_sizes), 1), "median": statistics.median(result_sizes),
            "p95": sorted(result_sizes)[int(.95 * len(result_sizes)) - 1], "max": max(result_sizes),
        },
        "single_search_calls": len(search_ones), "single_search_zero_hit_calls": len(no_hits),
        "single_search_unknown_count_calls": search_counts_unknown,
        "single_search_total_matches_median": statistics.median(search_ones),
        "single_search_total_matches_max": max(search_ones), "single_search_query_modes": dict(query_modes),
        "single_search_truncated_calls": truncated_searches,
        "single_search_over_100_matches": broad_searches,
        "single_search_no_hit_examples": no_hits[:12],
        "errors": errors,
    }


def cases_from(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["cases"] + data.get("scope_difference_cases", [])
    return {(x["outcome"].lower(), x["trial"].lower()): x for x in rows}


baseline, latest = cases_from(BASE_SCORE), cases_from(LATEST_SCORE)
paired = sorted(baseline.keys() & latest.keys())
cells = []
for outcome, trial in paired:
    old, new = baseline[(outcome, trial)], latest[(outcome, trial)]
    for domain in DOMAINS:
        expected = old["expected"][domain]
        cells.append({
            "outcome": old["outcome"], "trial": old["trial"], "domain": domain,
            "expected": expected,
            "baseline_observed": old["observed"][domain],
            "latest_observed": new["observed"][domain],
            "baseline_correct": old["observed"][domain] == expected,
            "latest_correct": new["observed"][domain] == expected,
            "baseline_scope_note": old.get("scope_note", ""),
            "latest_scope_adjudication": (new.get("scope_adjudication") or {}).get("decision", "exact"),
        })

with (OUT / "case-cell-comparison.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(cells[0]))
    writer.writeheader()
    writer.writerows(cells)
for name, selected in (
    ("case-cell-mismatches.csv", [r for r in cells if not r["latest_correct"]]),
    ("case-cell-agreements.csv", [r for r in cells if r["latest_correct"]]),
):
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(cells[0]))
        writer.writeheader()
        writer.writerows(selected)

paired_scores = {}
for domain in DOMAINS:
    rows = [r for r in cells if r["domain"] == domain]
    paired_scores[domain] = {
        "total": len(rows),
        "baseline_correct": sum(r["baseline_correct"] for r in rows),
        "latest_correct": sum(r["latest_correct"] for r in rows),
    }
summary = {
    "scope": "All JSONL files under both requested dates; paired label outcomes by same trial/outcome and unchanged expected labels.",
    "log_inventory": inventory,
    "official_latest_trace_metrics": trace_metrics(DAY_ROOTS[1] / "rob2-trial-benchmark-latest-8ae8016" / "runs"),
    "score_paths": [str(BASE_SCORE.relative_to(ROOT)), str(LATEST_SCORE.relative_to(ROOT))],
    "baseline_cases": len(baseline), "latest_cases_including_scope_differences": len(latest),
    "paired_cases": len(paired),
    "paired_cases_with_same_expected_labels": sum(baseline[k]["expected"] == latest[k]["expected"] for k in paired),
    "paired_scores": paired_scores,
    "all_26_label_changes": [r for r in cells if r["baseline_observed"] != r["latest_observed"]],
    "cell_csv": "case-cell-comparison.csv",
    "mismatch_csv": "case-cell-mismatches.csv",
    "agreement_csv": "case-cell-agreements.csv",
}
# Final artifacts show accepted checkpoint history; raw save calls also include
# retries and unselected attempts, so they are not an amendment count.
history_counts, repeated_histories = Counter(), []
for case in latest.values():
    with zipfile.ZipFile(case["bundle"]) as bundle:
        canonical = json.loads(bundle.read("canonical.json"))
    for key, records in canonical.get("domain_history_records", {}).items():
        domain = key.rsplit(":", 1)[-1]
        history_counts[domain] += len(records)
        if len(records) > 1:
            repeated_histories.append({"outcome": case["outcome"], "trial": case["trial"], "domain": domain,
                                      "judgments": [r.get("judgment") for r in records]})
summary["final_bundle_domain_history_records"] = dict(history_counts)
summary["final_bundle_domain_history_record_total"] = sum(history_counts.values())
summary["final_bundle_repeated_domain_histories"] = repeated_histories
(OUT / "log-and-paired-scores.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({"log_counts": {k: v["jsonl_files"] for k, v in inventory.items() if isinstance(v, dict)}, "paired": summary["paired_scores"], "comparison_rows": len(cells), "output": str(OUT)}, indent=2))
