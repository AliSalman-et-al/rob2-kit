from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.workflow_completion import Turn, drive, tool_feedback


def retained_validation_error() -> dict:
    """A native Codex event for a schema-rejected read_pages call."""
    return {
        "id": "item_39",
        "type": "mcp_tool_call",
        "server": "rob2",
        "tool": "read_pages",
        "arguments": {"trial_id": "trial", "source_id": "sh_0", "pages": list(range(109, 120))},
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "1 validation error for call[read_pages]\npages\n  List should have at "
                    "most 10 items after validation, not 11 [type=too_long, input_value=[109, 110, "
                    "111, 112, 113,...115, 116, 117, 118, 119], input_type=list]\n    For further "
                    "information visit https://errors.pydantic.dev/2.13/v/too_long",
                }
            ],
            "structured_content": None,
        },
        "error": None,
        "status": "failed",
    }


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
