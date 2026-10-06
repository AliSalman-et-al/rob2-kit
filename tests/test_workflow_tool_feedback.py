from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.workflow_completion import Turn, drive, tool_feedback, trace_facts

CASE = (
    Path(__file__).parents[1]
    / "tests/fixtures/historical-evaluation/2026-10-03-gupta-full-validation"
)


def retained_validation_error() -> dict:
    for line in (CASE / "turn-2.jsonl").read_text().splitlines():
        row = json.loads(line)
        item = row.get("item", {})
        if row.get("type") == "item.completed" and item.get("tool") == "read_pages":
            result = item.get("result") or {}
            if result.get("structured_content") is None:
                return item
    raise AssertionError("retained native validation event absent")


def test_native_completed_error_and_equivalent_failed_envelope_preserve_details() -> None:
    original = retained_validation_error()
    untouched = copy.deepcopy(original)
    feedback = tool_feedback(original)
    changed = copy.deepcopy(original)
    changed["status"] = "failed"
    changed["id"] = "different-turn-id"
    changed["result"]["content"][0]["text"] = (
        changed["result"]["content"][0]["text"]
        .replace("109, 110, 111", "200, 201, 202")
        .replace("\n", "\r\n")
    )
    equivalent = tool_feedback(changed)
    assert feedback.kind == equivalent.kind == "input_rejection"
    assert feedback.fingerprint == equivalent.fingerprint
    assert feedback.original == untouched and original == untouched
    assert (
        equivalent.original["result"]["content"][0]["text"]
        != untouched["result"]["content"][0]["text"]
    )
    assert not feedback.retryable


def test_actual_trace_now_counts_both_previously_missed_schema_errors() -> None:
    first = trace_facts(CASE / "turn-1.jsonl")
    second = trace_facts(CASE / "turn-2.jsonl")
    assert len([x for x in first["feedback"] if x["kind"] == "input_rejection"]) == 1
    assert len([x for x in second["feedback"] if x["kind"] == "input_rejection"]) == 1
    assert first["calls"] == 14 and second["calls"] == 42


@pytest.mark.parametrize(
    "result",
    [
        {"content": [{"type": "image", "data": "pixels", "mimeType": "image/png"}]},
        {"content": [{"type": "text", "text": "Validation errors in the source were discussed."}]},
        {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "1 validation error for call[read_pages]\n"
                        "A clinical description, not a typed validator"
                    ),
                }
            ]
        },
        {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "1 validation error for call[other_tool]\npages\n  invalid [type=too_long]"
                    ),
                }
            ]
        },
        {
            "structured_content": {
                "outcome": "success",
                "data": {
                    "text": (
                        "1 validation error for call[read_pages]\npages\n  invalid [type=too_long]"
                    )
                },
            }
        },
        {
            "structured_content": {"outcome": "success"},
            "content": [{"type": "image", "data": "pixels"}],
        },
    ],
)
def test_successful_text_images_and_source_mentions_are_not_errors(result: dict) -> None:
    feedback = tool_feedback({"tool": "read_pages", "status": "completed", "result": result})
    assert feedback.kind == "success" and feedback.fingerprint is None


def test_assessment_rejection_transport_retry_and_researcher_gate_are_distinct() -> None:
    scientific = tool_feedback(
        {
            "tool": "save_domain_judgment",
            "result": {
                "structured_content": {
                    "outcome": "repair",
                    "head": {"state_revision": 4},
                    "repairs": [
                        {
                            "code": "unresolved_premise",
                            "path": "/answers/0",
                            "detail": "cause unknown",
                        }
                    ],
                }
            },
        }
    )
    changed = copy.deepcopy(scientific.original)
    changed["result"]["structured_content"]["head"]["state_revision"] = 5
    assert tool_feedback(changed).fingerprint == scientific.fingerprint
    transport = tool_feedback(
        {"tool": "read_pages", "error": {"message": "transport timed out", "retryable": True}}
    )
    gate = tool_feedback(
        {
            "tool": "save_proposal",
            "result": {
                "structured_content": {
                    "outcome": "review_required",
                    "head": {"next_action": {"authority": "researcher"}},
                }
            },
        }
    )
    assert scientific.kind == "assessment_rejection" and not scientific.retryable
    assert transport.kind == "transport_error" and transport.retryable
    assert gate.kind == "researcher_gate" and gate.fingerprint is None
    assert scientific.fingerprint != transport.fingerprint


def test_repeated_native_error_across_turns_survives_status_only_recovery(tmp_path: Path) -> None:
    event = retained_validation_error()
    calls = []

    def invoke(session, prompt, remaining, index):
        calls.append((session, remaining))
        rows = [
            {"type": "thread.started", "thread_id": "same"},
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "tool": "get_status",
                    "result": {"structured_content": {"outcome": "success"}},
                },
            },
            {"type": "item.completed", "item": event},
            {"type": "turn.completed", "usage": {"output_tokens": 10}},
        ]
        path = tmp_path / f"{index}.jsonl"
        path.write_text("\n".join(json.dumps(x) for x in rows))
        return Turn(0, path)

    revision = 0

    def status():
        nonlocal revision
        revision += 1  # Exclude a no-progress stop, exercise equivalent errors.
        return {
            "phase": "assessment",
            "state_revision": revision,
            "continuation": {"authority": "host"},
        }

    result = drive(
        invoke,
        status,
        lambda _: False,
        prompt="Complete",
        session="same",
        max_resumes=5,
        no_progress_limit=5,
        wall_seconds=1200,
    )
    assert len(calls) == 2 and result["reason"] == "bounded no-progress or repeated-error stop"
    assert result["usage"]["output_tokens"] == 20
    assert calls[1][1] <= calls[0][1]
