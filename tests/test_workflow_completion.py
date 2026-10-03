"""Host completion depends on canonical state, never a model's final prose."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from workflow_completion import Turn, boundary, drive, trace_facts


def pending(operation: str = "get_domain_context", cursor: str = "next") -> dict:
    return {
        "phase": "assessment",
        "state_revision": 4,
        "continuation": {"operation": operation, "authority": "host", "cursor": cursor},
    }


def trace(
    path: Path, *, failed: bool = False, session: str = "same", tool: str = "get_status"
) -> Path:
    payload = (
        {"content": [{"text": "schema failure"}], "structured_content": None}
        if failed
        else {"structured_content": {"outcome": "success"}}
    )
    rows = [
        {"type": "thread.started", "thread_id": session},
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": tool,
                "arguments": {},
                "result": payload,
                "error": None,
                "status": "failed" if failed else "completed",
            },
        },
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10},
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    return path


def test_completion_requires_finalized_verified_state_and_respects_human_gate() -> None:
    assert boundary({"phase": "finalized"}, verified=True) == "complete"
    assert boundary({"phase": "finalized"}, verified=False) == "blocked"
    assert boundary(pending("finalize_batch"), verified=True) == "unfinished"
    assert (
        boundary({"phase": "proposal", "continuation": {"authority": "researcher"}}, verified=False)
        == "waiting_for_user"
    )
    assert (
        boundary(
            {"outcome": "condition", "code": "internal_evidence_integrity_error"}, verified=False
        )
        == "blocked"
    )


def test_same_session_resume_follows_pending_action_and_sums_every_turn(tmp_path: Path) -> None:
    statuses = iter([pending(), pending(cursor="last"), {"phase": "finalized"}])
    seen = []

    def invoke(session, prompt, remaining, index):
        seen.append((session, prompt, remaining))
        return Turn(0, trace(tmp_path / f"{index}.jsonl", tool="get_domain_context"))

    result = drive(
        invoke,
        lambda: next(statuses),
        lambda s: s.get("phase") == "finalized",
        prompt="Complete all Domains/review/closure/finalize",
        session=None,
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
    )
    assert result["boundary"] == "complete"
    assert seen[0][0] is None and seen[1][0] == "same"
    assert '"cursor": "last"' in seen[1][1]
    assert result["usage"] == {"input_tokens": 200, "cached_input_tokens": 160, "output_tokens": 20}
    assert len(result["turns"]) == 2


def test_no_progress_and_identical_native_failures_stop_without_replacement(tmp_path: Path) -> None:
    for failed in (False, True):
        calls = []

        def invoke(session, prompt, remaining, index):
            calls.append(session)
            return Turn(0, trace(tmp_path / f"{failed}-{index}.jsonl", failed=failed))

        result = drive(
            invoke,
            pending,
            lambda s: False,
            prompt="Assess",
            session="same",
            max_resumes=8,
            no_progress_limit=2,
            wall_seconds=60,
        )
        assert result["boundary"] == "unfinished"
        assert len(calls) == 2 and set(calls) == {"same"}
        assert result["usage"]["input_tokens"] == 200


def test_pending_researcher_action_never_invokes_or_acknowledges() -> None:
    def forbidden(*args):
        raise AssertionError("must not cross human gate")

    result = drive(
        forbidden,
        lambda: {"phase": "proposal", "continuation": {"authority": "researcher"}},
        lambda s: False,
        prompt="Assess",
        session="same",
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
    )
    assert result["boundary"] == "waiting_for_user" and result["turns"] == []


def test_session_mismatch_is_retained_and_never_resumed(tmp_path: Path) -> None:
    result = drive(
        lambda *args: Turn(0, trace(tmp_path / "bad.jsonl", session="replacement")),
        pending,
        lambda s: False,
        prompt="Assess",
        session="same",
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
    )
    assert result["boundary"] == "aborted"
    assert len(result["turns"]) == 1 and result["usage"]["input_tokens"] == 100


def test_shared_wall_budget_and_host_abort_are_real_boundaries(tmp_path: Path) -> None:
    times = iter([0, 61])
    result = drive(
        lambda *args: pytest.fail("wall budget"),
        pending,
        lambda s: False,
        prompt="Assess",
        session="same",
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
        clock=lambda: next(times),
    )
    assert result["boundary"] == "aborted" and result["turns"] == []
    result = drive(
        lambda *args: Turn(124, trace(tmp_path / "expired.jsonl")),
        pending,
        lambda s: False,
        prompt="Assess",
        session="same",
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
    )
    assert result["boundary"] == "aborted" and len(result["turns"]) == 1


def test_actual_exscel_failed_item_status_is_counted_without_error_field() -> None:
    artifact = (
        Path(__file__).parents[1] / "docs/evaluation/2026-10-03-exscel-full-bd92ec8/events.jsonl"
    )
    facts = trace_facts(artifact)
    assert facts["calls"] == 6
    assert len([x for x in facts["failures"] if x]) == 1
    assert facts["usage"]["input_tokens"] == 334932


def test_novel_queries_and_timestamps_are_not_durable_progress(tmp_path: Path) -> None:
    count = 0

    def status():
        nonlocal count
        count += 1
        return {**pending(), "observed_at": count}

    result = drive(
        lambda *args: Turn(0, trace(tmp_path / f"query-{count}.jsonl", tool="search_sources")),
        status,
        lambda s: False,
        prompt="Assess",
        session="same",
        max_resumes=3,
        no_progress_limit=2,
        wall_seconds=60,
    )
    assert result["boundary"] == "unfinished"
    assert len(result["turns"]) == 2 and not any(t["progress"] for t in result["turns"])


def test_finalization_receipt_lookup_matches_authoritative_revision() -> None:
    from workflow_completion import finalized_artifact

    trace_path = (
        Path(__file__).parents[1]
        / "docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl"
    )
    status = {"phase": "finalized", "state_revision": 12}
    artifact = finalized_artifact(status, [trace_path])
    assert artifact and artifact["path"].endswith(".rob2.zip")
    assert finalized_artifact({**status, "state_revision": 13}, [trace_path]) is None
    assert finalized_artifact({**status, "phase": "assessment"}, [trace_path]) is None
