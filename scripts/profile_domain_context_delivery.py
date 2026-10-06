"""Profile retained Codex JSONL captures of get_domain_context delivery.

Only aggregate measurements and snapshot digests are emitted. Context bodies,
prompts, Source text, and host identifiers are never written to the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

_SECTIONS = ("primary_report", "questions", "evidence", "comparison_cards")


def _structured_response(item: dict[str, Any]) -> dict[str, Any] | None:
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("structured_content", "structuredContent"):
        response = result.get(key)
        if isinstance(response, dict):
            return response
    content = result.get("content")
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        try:
            response = json.loads(part.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(response, dict):
            return response
    return None


def _content_metrics(result: dict[str, Any], response: dict[str, Any]) -> dict[str, int]:
    content = result.get("content")
    parts = content if isinstance(content, list) else []
    text_parts = [
        part for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    exact_text_copies = 0
    for part in text_parts:
        try:
            exact_text_copies += json.loads(part["text"]) == response
        except (json.JSONDecodeError, TypeError):
            continue
    return {
        "content_parts": len(parts),
        "text_parts": len(text_parts),
        "text_bytes": sum(len(part["text"].encode("utf-8")) for part in text_parts),
        "exact_text_copies": exact_text_copies,
        "nontext_parts": len(parts) - len(text_parts),
    }


def _wire_bytes(response: dict[str, Any]) -> int:
    envelope = {"content": [], "structured_content": response}
    return len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _candidate_bytes(response: dict[str, Any]) -> tuple[int, int]:
    """Measure the candidate that omits empty section arrays on delta pages."""
    candidate, omitted = _omit_empty_section_arrays(response)
    return _wire_bytes(candidate), omitted


def _omit_empty_section_arrays(response: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return a bounded candidate payload and the number of omitted arrays."""
    page_data = response.get("data")
    page = page_data.get("context_page") if isinstance(page_data, dict) else None
    if not isinstance(page, dict) or page.get("index", 0) == 0:
        return response, 0
    candidate = json.loads(json.dumps(response, ensure_ascii=False))
    candidate_data = candidate["data"]
    omitted = 0
    for name in _SECTIONS:
        if candidate_data.get(name) == []:
            del candidate_data[name]
            omitted += 1
    return candidate, omitted


def _reconstruct(pages: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    first = pages.get(0)
    first_data = first.get("data") if isinstance(first, dict) else None
    if not isinstance(first_data, dict):
        return None
    reconstructed = json.loads(json.dumps(first_data, ensure_ascii=False))
    for index in sorted(pages):
        if index == 0:
            continue
        data = pages[index].get("data")
        if not isinstance(data, dict):
            return None
        page = data.get("context_page")
        section = page.get("section") if isinstance(page, dict) else None
        if section not in _SECTIONS:
            continue
        reconstructed[section] = [
            *reconstructed.get(section, []),
            *data.get(section, []),
        ]
    cores = [
        pages[index]["data"]["official_guidance"]
        for index in sorted(pages)
        if pages[index]["data"].get("official_guidance")
    ]
    if cores:
        reconstructed["official_guidance"] = {
            "pack": cores[0]["pack"],
            "sections": [section for core in cores for section in core["sections"]],
            "complete": True,
            "next_cursor": None,
        }
    reconstructed.pop("context_page", None)
    return reconstructed


def profile_run(run_dir: Path) -> dict[str, Any]:
    context_calls: list[dict[str, Any]] = []
    pages_by_snapshot: dict[tuple[str, int, int], dict[int, dict[str, Any]]] = defaultdict(dict)
    repairs = 0
    failures = 0
    usage_records = 0
    latency_measurements_ms: list[float] = []
    traces = sorted(run_dir.glob("phase-*.jsonl"))
    trace_files = []
    for trace in traces:
        trace_bytes = trace.read_bytes()
        trace_files.append(
            {
                "name": trace.name,
                "bytes": len(trace_bytes),
                "sha256": hashlib.sha256(trace_bytes).hexdigest(),
            }
        )
        with trace.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("type") == "token_usage_record":
                    usage_records += 1
                item = event.get("item") or {}
                if event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
                    continue
                result = item.get("result") or {}
                response = _structured_response(item)
                if response and response.get("outcome") == "repair":
                    repairs += 1
                if item.get("error") or (isinstance(result, dict) and result.get("isError")):
                    failures += 1
                if item.get("tool") != "get_domain_context" or response is None:
                    continue
                content = _content_metrics(result if isinstance(result, dict) else {}, response)
                page_data = response.get("data")
                page = page_data.get("context_page") if isinstance(page_data, dict) else None
                page_index = page.get("index") if isinstance(page, dict) else None
                digest = page.get("snapshot_digest") if isinstance(page, dict) else None
                if (
                    isinstance(page, dict)
                    and isinstance(page_index, int)
                    and isinstance(digest, str)
                ):
                    count = page.get("count")
                    budget = page.get("max_response_bytes")
                    if isinstance(count, int) and isinstance(budget, int):
                        pages_by_snapshot[(digest, count, budget)][page_index] = response
                candidate_size, omitted = _candidate_bytes(response)
                context_calls.append(
                    {
                        "index": page_index,
                        "bytes": _wire_bytes(response),
                        "structured_bytes": len(
                            json.dumps(
                                response,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ),
                        "candidate_bytes": candidate_size,
                        "omitted_empty_arrays": omitted,
                        **content,
                    }
                )
                started = item.get("started_at")
                completed = item.get("completed_at")
                if isinstance(started, (int, float)) and isinstance(completed, (int, float)):
                    latency_measurements_ms.append((completed - started) * 1000)

    first_page_calls = sum(call["index"] == 0 for call in context_calls)
    continuation_calls = sum(
        isinstance(call["index"], int) and call["index"] > 0 for call in context_calls
    )
    unpaged_calls = sum(call["index"] is None for call in context_calls)
    baseline_bytes = sum(call["bytes"] for call in context_calls)
    candidate_bytes = sum(call["candidate_bytes"] for call in context_calls)
    first_page_bytes = sum(call["bytes"] for call in context_calls if call["index"] == 0)
    continuation_bytes = sum(
        call["bytes"]
        for call in context_calls
        if isinstance(call["index"], int) and call["index"] > 0
    )
    unpaged_bytes = sum(call["bytes"] for call in context_calls if call["index"] is None)
    snapshots = []
    for (digest, count, _page_size), pages in sorted(pages_by_snapshot.items()):
        complete = set(pages) == set(range(count))
        reconstructed = _reconstruct(pages) if complete else None
        canonical = (
            json.dumps(reconstructed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if reconstructed is not None
            else None
        )
        reconstructed_digest = (
            hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical is not None else None
        )
        questions = reconstructed.get("questions", []) if reconstructed else []
        evidence = reconstructed.get("evidence", []) if reconstructed else []
        comparison_cards = reconstructed.get("comparison_cards", []) if reconstructed else []
        result_bytes = (
            len(
                json.dumps(
                    reconstructed["result"], ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            )
            if reconstructed and "result" in reconstructed
            else 0
        )
        snapshots.append(
            {
                "snapshot_sha256": digest,
                "page_count": count,
                "captured_page_indexes": sorted(pages),
                "complete": complete,
                "reconstruction_digest_matches": reconstructed_digest == digest,
                "question_count": len(questions),
                "conditional_question_count": sum(
                    question.get("activation_status") == "dependent_on_draft_answers"
                    for question in questions
                    if isinstance(question, dict)
                ),
                "evidence_count": len(evidence),
                "comparison_card_count": len(comparison_cards),
                "result_serialized_bytes": result_bytes,
            }
        )
    return {
        "capture": "/".join(run_dir.parts[-2:]),
        "phases": len(traces),
        "trace_files": trace_files,
        "domain_context_calls": len(context_calls),
        "first_page_calls": first_page_calls,
        "continuation_page_calls": continuation_calls,
        "unpaged_calls": unpaged_calls,
        "serialized_response_bytes": baseline_bytes,
        "first_page_response_bytes": first_page_bytes,
        "continuation_response_bytes": continuation_bytes,
        "unpaged_response_bytes": unpaged_bytes,
        "structured_payload_bytes": sum(call["structured_bytes"] for call in context_calls),
        "text_content_parts": sum(call["text_parts"] for call in context_calls),
        "text_content_bytes": sum(call["text_bytes"] for call in context_calls),
        "exact_structured_text_copy_calls": sum(
            call["exact_text_copies"] > 0 for call in context_calls
        ),
        "nontext_content_parts": sum(call["nontext_parts"] for call in context_calls),
        "candidate_serialized_response_bytes": candidate_bytes,
        "candidate_bytes_saved": baseline_bytes - candidate_bytes,
        "candidate_reduction_percent": (
            round((baseline_bytes - candidate_bytes) * 100 / baseline_bytes, 3)
            if baseline_bytes
            else 0.0
        ),
        "omitted_empty_array_occurrences": sum(
            call["omitted_empty_arrays"] for call in context_calls
        ),
        "complete_context_snapshots": sum(1 for snapshot in snapshots if snapshot["complete"]),
        "context_snapshots": snapshots,
        "repair_receipts_all_tools": repairs,
        "tool_call_errors_all_tools": failures,
        "latency_measurements_ms": latency_measurements_ms,
        "latency_available": bool(latency_measurements_ms),
        "token_usage_records": usage_records,
        "token_usage_available": usage_records > 0,
    }


def profile_tree(root: Path) -> dict[str, Any]:
    run_dirs = sorted({trace.parent for trace in root.rglob("phase-*.jsonl")})
    return {"runs": [profile_run(run_dir) for run_dir in run_dirs]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path, help="Directory containing phase-*.jsonl captures")
    args = parser.parse_args()
    print(json.dumps(profile_tree(args.run_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
