"""Summarize Claude stream-json traces without changing the run directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CONSTRAINT_WORDS = re.compile(
    r"\b(?:token|tokens|context|budget|length|window|constraint|constraints?|limit|"
    r"remaining|critical|exhaust(?:ed|ion)?|short)\b",
    re.IGNORECASE,
)
_FALLBACK_WORDS = re.compile(
    r"\b(?:due to|because of|given|must note|cannot|can't|unable|not able|"
    r"will summarize|summarize|complete efficiently|proceed efficiently)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Line:
    number: int
    value: dict[str, Any] | None
    byte_count: int
    error: str | None = None


@dataclass(frozen=True)
class ToolCall:
    line: int
    name: str
    tool_id: str | None


@dataclass(frozen=True)
class ToolResult:
    line: int
    tool_id: str | None
    payload: Any
    byte_count: int
    outcome: str


def _read_jsonl(path: Path) -> tuple[list[Line], int]:
    lines: list[Line] = []
    total_bytes = 0
    for number, raw in enumerate(path.read_bytes().splitlines(keepends=True), start=1):
        total_bytes += len(raw)
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            lines.append(Line(number, None, len(raw), str(error)))
            continue
        if not isinstance(value, dict):
            lines.append(Line(number, None, len(raw), "JSONL record is not an object"))
            continue
        lines.append(Line(number, value, len(raw)))
    return lines, total_bytes


def _blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            return [item for item in content if isinstance(item, dict)]
    return []


def _tool_calls(lines: list[Line]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for line in lines:
        if line.value is None or line.value.get("type") != "assistant":
            continue
        for block in _blocks(line.value.get("message")):
            if block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                calls.append(ToolCall(line.number, block["name"], block.get("id")))
    return calls


def _payload_from_block(block: dict[str, Any]) -> Any:
    payload = block.get("content")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


def _payload_bytes(payload: Any) -> int:
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _outcome(payload: Any) -> str:
    if isinstance(payload, dict):
        outcome = payload.get("outcome")
        if isinstance(outcome, str) and outcome:
            return outcome
    if isinstance(payload, str):
        return "error"
    return "unknown"


def _tool_results(lines: list[Line]) -> list[ToolResult]:
    results: list[ToolResult] = []
    for line in lines:
        if line.value is None or line.value.get("type") != "user":
            continue
        blocks = _blocks(line.value.get("message"))
        if not blocks:
            tool_result = line.value.get("tool_use_result")
            if tool_result is not None:
                blocks = [{"type": "tool_result", "content": tool_result}]
        for block in blocks:
            if block.get("type") != "tool_result":
                continue
            payload = _payload_from_block(block)
            results.append(
                ToolResult(
                    line.number,
                    block.get("tool_use_id"),
                    payload,
                    _payload_bytes(block.get("content")),
                    _outcome(payload),
                )
            )
    return results


def _repair_codes(payload: Any) -> Counter[str]:
    if not isinstance(payload, dict):
        return Counter()
    return Counter(
        item.get("code")
        for item in payload.get("repairs", [])
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    )


def _error_code(payload: Any) -> str | None:
    if not isinstance(payload, str):
        return None
    if payload.startswith("Input validation error:"):
        return "input_validation_error"
    return "tool_error"


def _text_blocks(lines: list[Line]) -> list[tuple[int, str, str | None]]:
    texts: list[tuple[int, str, str | None]] = []
    for line in lines:
        if line.value is None or line.value.get("type") != "assistant":
            continue
        message = line.value.get("message")
        stop_reason = message.get("stop_reason") if isinstance(message, dict) else None
        for block in _blocks(message):
            text = block.get("text")
            if block.get("type") == "text" and isinstance(text, str) and text.strip():
                texts.append((line.number, text, stop_reason))
    return texts


def _prose_fallbacks(lines: list[Line]) -> list[dict[str, Any]]:
    texts = _text_blocks(lines)
    tool_lines = {call.line for call in _tool_calls(lines)}
    fallbacks: list[dict[str, Any]] = []
    for index, (line, text, stop_reason) in enumerate(texts):
        constraint_matches = sorted({match.casefold() for match in _CONSTRAINT_WORDS.findall(text)})
        fallback_matches = sorted({match.casefold() for match in _FALLBACK_WORDS.findall(text)})
        if not constraint_matches or not fallback_matches:
            continue
        final_assistant_text = index == len(texts) - 1
        if stop_reason != "end_turn" and any(tool_line > line for tool_line in tool_lines):
            continue
        fallbacks.append(
            {
                "line": line,
                "final_assistant_text": final_assistant_text,
                "constraint_markers": constraint_matches,
                "fallback_markers": fallback_matches,
                "text": text,
            }
        )
    return fallbacks


def _result_summary(lines: list[Line]) -> dict[str, Any] | None:
    records = [line.value for line in lines if line.value and line.value.get("type") == "result"]
    if not records:
        return None
    result = records[-1]
    raw_usage = result.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    raw_model_usage = result.get("modelUsage")
    model_usage: dict[str, Any] = raw_model_usage if isinstance(raw_model_usage, dict) else {}
    return {
        "subtype": result.get("subtype"),
        "is_error": result.get("is_error"),
        "stop_reason": result.get("stop_reason"),
        "terminal_reason": result.get("terminal_reason"),
        "turns": result.get("num_turns"),
        "cost_usd": result.get("total_cost_usd"),
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "thinking_tokens": (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
        "model_usage": model_usage,
    }


def _session_ids(lines: list[Line]) -> list[str]:
    return sorted(
        {
            line.value["session_id"]
            for line in lines
            if line.value and isinstance(line.value.get("session_id"), str)
        }
    )


def _compactions(lines: list[Line], calls: list[ToolCall]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in lines:
        if line.value is None or line.value.get("type") != "system":
            continue
        if line.value.get("subtype") != "compact_boundary":
            continue
        metadata = line.value.get("compact_metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        output.append(
            {
                "line": line.number,
                "trigger": metadata.get("trigger"),
                "pre_tokens": metadata.get("pre_tokens"),
                "post_tokens": metadata.get("post_tokens"),
                "dropped_tokens": metadata.get("cumulative_dropped_tokens"),
                "tool_calls_after": sum(call.line > line.number for call in calls),
            }
        )
    return output


def _summarize_file(path: Path, root: Path) -> dict[str, Any]:
    lines, byte_count = _read_jsonl(path)
    valid_lines = [line for line in lines if line.value is not None]
    calls = _tool_calls(lines)
    results = _tool_results(lines)
    call_by_id = {call.tool_id: call.name for call in calls if call.tool_id}
    tool_call_counts = Counter(call.name for call in calls)
    result_bytes: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "bytes": 0})
    )
    repair_codes: Counter[str] = Counter()
    error_codes: Counter[str] = Counter()
    for result in results:
        tool = call_by_id.get(result.tool_id, "<unmatched>")
        bucket = result_bytes[tool][result.outcome]
        bucket["count"] += 1
        bucket["bytes"] += result.byte_count
        repair_codes.update(_repair_codes(result.payload))
        error_code = _error_code(result.payload)
        if error_code is not None:
            error_codes[error_code] += 1
    return {
        "path": str(path.relative_to(root)),
        "bytes": byte_count,
        "lines": len(lines),
        "valid_records": len(valid_lines),
        "malformed_records": [
            {"line": line.number, "bytes": line.byte_count, "error": line.error}
            for line in lines
            if line.error is not None
        ],
        "session_ids": _session_ids(lines),
        "result_session": _result_summary(lines),
        "tool_calls": dict(sorted(tool_call_counts.items())),
        "tool_result_bytes": {
            tool: dict(sorted(outcomes.items())) for tool, outcomes in sorted(result_bytes.items())
        },
        "repair_codes": dict(sorted(repair_codes.items())),
        "error_codes": dict(sorted(error_codes.items())),
        "prose_fallbacks": _prose_fallbacks(lines),
        "compactions": _compactions(lines, calls),
    }


def analyze_run(run_directory: Path) -> dict[str, Any]:
    if not run_directory.is_dir():
        raise ValueError(f"run directory is not a directory: {run_directory}")
    paths = sorted(run_directory.glob("*-stream.jsonl"))
    if not paths:
        raise ValueError(f"run directory contains no stream JSONL files: {run_directory}")
    sessions = [_summarize_file(path, run_directory) for path in paths]
    transcript_paths = sorted(run_directory.glob("interactive-*.jsonl"))
    transcripts = [_summarize_file(path, run_directory) for path in transcript_paths]
    behavior_sessions = transcripts or sessions
    totals = {
        "cost_usd": 0.0,
        "turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    tool_calls: Counter[str] = Counter()
    result_bytes: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0, "bytes": 0})
    )
    repair_codes: Counter[str] = Counter()
    error_codes: Counter[str] = Counter()
    session_ids: set[str] = set()
    malformed = 0
    fallbacks: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    for session in behavior_sessions:
        malformed += len(session["malformed_records"])
        session_ids.update(session["session_ids"])
        fallbacks.extend({"file": session["path"], **item} for item in session["prose_fallbacks"])
        compactions.extend({"file": session["path"], **item} for item in session["compactions"])
        tool_calls.update(session["tool_calls"])
        repair_codes.update(session["repair_codes"])
        error_codes.update(session["error_codes"])
        for tool, outcomes in session["tool_result_bytes"].items():
            for outcome, values in outcomes.items():
                bucket = result_bytes[tool][outcome]
                bucket["count"] += values["count"]
                bucket["bytes"] += values["bytes"]
    for session in sessions:
        result = session["result_session"]
        if result is None:
            continue
        totals["cost_usd"] += result["cost_usd"] or 0.0
        totals["turns"] += result["turns"] or 0
        for key, value in result["usage"].items():
            totals[key] += value or 0
    has_complete_stream_results = bool(sessions) and all(
        session["result_session"] is not None for session in sessions
    )
    if transcripts:
        usage_coverage = {
            "source": "stream_json",
            "scope": "stream_files_only",
            "complete": False,
            "note": (
                "Behavior metrics use the interactive transcript, but cost, token, and turn "
                "metrics use stream result records only and may omit transcript continuations."
            ),
        }
    else:
        usage_coverage = {
            "source": "stream_json",
            "scope": "stream_files",
            "complete": has_complete_stream_results,
            "note": (
                "Cost, token, and turn metrics cover all stream result records."
                if has_complete_stream_results
                else (
                    "One or more stream files has no terminal result record; usage metrics are "
                    "partial."
                )
            ),
        }
    return {
        "run_directory": str(run_directory),
        "session_files": sessions,
        "transcript_files": transcripts,
        "aggregate": {
            **totals,
            "session_count": len(sessions),
            "session_ids": sorted(session_ids),
            "same_session_across_files": len(session_ids) == 1,
            "tool_calls": dict(sorted(tool_calls.items())),
            "tool_result_bytes": {
                tool: dict(sorted(outcomes.items()))
                for tool, outcomes in sorted(result_bytes.items())
            },
            "repair_codes": dict(sorted(repair_codes.items())),
            "error_codes": dict(sorted(error_codes.items())),
            "malformed_records": malformed,
            "prose_fallbacks": fallbacks,
            "compactions": compactions,
            "behavior_source": "interactive_transcript" if transcripts else "stream_json",
            "usage_coverage": usage_coverage,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    try:
        summary = analyze_run(args.run_directory)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
