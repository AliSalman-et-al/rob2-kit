from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "analyze_claude_dogfood",
    Path(__file__).parents[1] / "scripts" / "analyze_claude_dogfood.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
analyze_run = _MODULE.analyze_run


def _record(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_analyze_run_aggregates_calls_results_repairs_and_fallbacks(tmp_path: Path) -> None:
    stream = tmp_path / "first-stream.jsonl"
    _record(
        stream,
        [
            {"type": "system", "subtype": "init", "session_id": "session-1"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "mcp__server__operation",
                            "input": {},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": json.dumps(
                                {
                                    "outcome": "repair",
                                    "repairs": [{"code": "invalid_request"}],
                                }
                            ),
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Given the token budget, I will summarize the remaining work.",
                        }
                    ]
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "terminal_reason": "completed",
                "num_turns": 2,
                "total_cost_usd": 0.25,
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 4,
                    "output_tokens_details": {"thinking_tokens": 1},
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 6,
                },
                "modelUsage": {"model": {"contextWindow": 200000}},
            },
        ],
    )

    summary = analyze_run(tmp_path)
    session = summary["session_files"][0]
    assert session["tool_calls"] == {"mcp__server__operation": 1}
    assert session["repair_codes"] == {"invalid_request": 1}
    assert session["prose_fallbacks"][0]["final_assistant_text"] is True
    assert summary["aggregate"]["cost_usd"] == 0.25
    assert summary["aggregate"]["turns"] == 2
    assert summary["aggregate"]["usage_coverage"] == {
        "source": "stream_json",
        "scope": "stream_files",
        "complete": True,
        "note": "Cost, token, and turn metrics cover all stream result records.",
    }
    assert (
        summary["aggregate"]["tool_result_bytes"]["mcp__server__operation"]["repair"]["count"] == 1
    )


def test_analyze_run_keeps_truncated_final_line_as_malformed(tmp_path: Path) -> None:
    stream = tmp_path / "live-stream.jsonl"
    stream.write_text(
        json.dumps({"type": "system", "subtype": "init"}) + "\n" + '{"type":"assistant"',
        encoding="utf-8",
    )

    summary = analyze_run(tmp_path)

    assert summary["session_files"][0]["valid_records"] == 1
    assert summary["session_files"][0]["malformed_records"][0]["line"] == 2
    assert summary["aggregate"]["malformed_records"] == 1


def test_analyze_run_ignores_nonterminal_planning_text_before_tool_call(tmp_path: Path) -> None:
    _record(
        tmp_path / "initial-stream.jsonl",
        [{"type": "system", "subtype": "init", "session_id": "session-1"}],
    )
    stream = tmp_path / "interactive-session.jsonl"
    _record(
        stream,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Due to the active context question, I will search next.",
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "mcp__server__search",
                            "input": {},
                        }
                    ]
                },
            },
        ],
    )

    summary = analyze_run(tmp_path)

    assert summary["aggregate"]["prose_fallbacks"] == []


def test_analyze_run_uses_complete_interactive_transcript_for_behavior(tmp_path: Path) -> None:
    _record(
        tmp_path / "initial-stream.jsonl",
        [
            {"type": "system", "subtype": "init", "session_id": "session-1"},
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 1,
                "total_cost_usd": 0.5,
                "usage": {},
            },
        ],
    )
    _record(
        tmp_path / "interactive-session.jsonl",
        [
            {"type": "system", "subtype": "init", "session_id": "session-1"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "mcp__server__operation",
                            "input": {},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": "Input validation error: bad argument",
                        }
                    ]
                },
            },
            {"type": "system", "subtype": "compact_boundary"},
        ],
    )

    summary = analyze_run(tmp_path)

    assert len(summary["session_files"]) == 1
    assert len(summary["transcript_files"]) == 1
    assert summary["aggregate"]["cost_usd"] == 0.5
    assert summary["aggregate"]["tool_calls"] == {"mcp__server__operation": 1}
    assert summary["aggregate"]["error_codes"] == {"input_validation_error": 1}
    assert len(summary["aggregate"]["compactions"]) == 1
    assert summary["aggregate"]["behavior_source"] == "interactive_transcript"
    assert summary["aggregate"]["usage_coverage"] == {
        "source": "stream_json",
        "scope": "stream_files_only",
        "complete": False,
        "note": (
            "Behavior metrics use the interactive transcript, but cost, token, and turn "
            "metrics use stream result records only and may omit transcript continuations."
        ),
    }
