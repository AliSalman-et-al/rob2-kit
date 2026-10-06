"""Host completion depends on canonical state, never a model's final prose."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.workflow_completion import Turn, boundary, drive, trace_facts


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
                "server": "rob2",
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
        Path(__file__).parents[1]
        / "docs/archive/evaluation/2026-10-03-exscel-full-bd92ec8/events.jsonl"
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
    from scripts.workflow_completion import finalized_artifact

    trace_path = (
        Path(__file__).parents[1]
        / "docs/archive/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl"
    )
    status = {"phase": "finalized", "state_revision": 12}
    artifact = finalized_artifact(status, [trace_path])
    assert artifact and artifact["path"].endswith(".rob2.zip")
    assert finalized_artifact({**status, "state_revision": 13}, [trace_path]) is None
    assert finalized_artifact({**status, "phase": "assessment"}, [trace_path]) is None


def scoped_fixture(reading="complete", domains=None):
    from scripts.workflow_completion import AssessmentScope, scoped_status

    scope = AssessmentScope(
        "neutral", "sha256:" + "a" * 64, ("domain:deviations", "domain:missing", "domain:selection")
    )
    records = {
        f"neutral:{d}": {
            "trial_id": "neutral",
            "domain_id": d,
            "result_identity": scope.result_identity,
            "identity": "sha256:" + "b" * 64,
        }
        for d in (scope.domain_ids if domains is None else domains)
    }
    status = {
        **pending(),
        "main_report_reading": {
            "neutral": {
                "status": reading,
                "required_range_count": 2 if reading == "required" else 0,
                "required_ranges": [
                    {"source_id": "sh_0123456789abcdef", "page": 2, "start_line": 1, "end_line": 4}
                ]
                if reading == "required"
                else [],
            }
        },
    }
    return scope, scoped_status(
        status, scope, result_identity=scope.result_identity, domain_records=records
    )


def test_scoped_premature_final_with_unread_pages_uses_generic_same_session_continuation(tmp_path):
    from scripts.workflow_completion import scope_verified

    scope, unread = scoped_fixture("required")
    _, done = scoped_fixture()
    statuses = iter([unread, unread, done])
    prompts = []

    def invoke(session, prompt, remaining, index):
        prompts.append((session, prompt))
        return Turn(0, trace(tmp_path / f"scope-{index}.jsonl", tool="read_pages"))

    result = drive(
        invoke,
        lambda: next(statuses),
        lambda s: scope_verified(s, scope),
        prompt="Assess the bound scope",
        session=None,
        max_resumes=1,
        no_progress_limit=2,
        wall_seconds=60,
        scope=scope,
    )
    assert result["boundary"] == "complete"
    assert len(result["turns"]) == 2 and prompts[1][0] == "same"
    assert "no other Domains, review, closure or finalization" in prompts[1][1]
    assert "follow its authoritative pending action through review" not in prompts[1][1]
    assert "Some concerns" not in prompts[1][1] and "blinded" not in prompts[1][1]
    assert result["usage"]["input_tokens"] == 200


def test_scoped_unsubmitted_domains_remain_actionable_and_zero_resumes_are_not_success(tmp_path):
    from scripts.workflow_completion import scope_verified

    scope, status = scoped_fixture(domains=("domain:missing",))
    assert status["continuation"]["domain_id"] == "domain:deviations"
    result = drive(
        lambda *args: Turn(0, trace(tmp_path / "one.jsonl")),
        lambda: status,
        lambda s: scope_verified(s, scope),
        prompt="Assess",
        session=None,
        max_resumes=0,
        no_progress_limit=2,
        wall_seconds=60,
        scope=scope,
    )
    assert result["boundary"] == "unfinished" and len(result["turns"]) == 1


def test_scoped_completed_goal_stops_without_finalizing_or_model_call():
    from scripts.workflow_completion import scope_verified

    scope, done = scoped_fixture()
    result = drive(
        lambda *args: pytest.fail("already complete"),
        lambda: done,
        lambda s: scope_verified(s, scope),
        prompt="Assess",
        session=None,
        max_resumes=2,
        no_progress_limit=2,
        wall_seconds=60,
        scope=scope,
    )
    assert result["boundary"] == "complete" and result["turns"] == []
    assert done["phase"] == "assessment"


def test_scoped_genuine_blocker_human_gate_and_changed_result_never_invoke():
    from scripts.workflow_completion import scope_verified, scoped_status

    scope, status = scoped_fixture(domains=())
    for pending_status in (
        {**status, "outcome": "condition"},
        {**status, "continuation": {"authority": "researcher"}},
    ):
        current = scoped_status(
            pending_status, scope, result_identity=scope.result_identity, domain_records={}
        )
        result = drive(
            lambda *args: pytest.fail("blocked/gated"),
            lambda: current,
            lambda s: scope_verified(s, scope),
            prompt="Assess",
            session="same",
            max_resumes=2,
            no_progress_limit=2,
            wall_seconds=60,
            scope=scope,
        )
        assert result["boundary"] in {"blocked", "waiting_for_user"}
    changed = scoped_status(status, scope, result_identity="sha256:" + "f" * 64, domain_records={})
    assert boundary(changed, verified=False, scope=scope) == "blocked"


def test_scoped_failed_handoff_and_no_progress_protection(tmp_path):
    from scripts.workflow_completion import scope_verified

    scope, status = scoped_fixture(domains=())
    for replacement, failed in ((True, False), (False, True)):
        result = drive(
            lambda *args: Turn(
                0,
                trace(
                    tmp_path / f"handoff-{replacement}.jsonl",
                    session="other" if replacement else "same",
                    failed=failed,
                ),
            ),
            lambda: status,
            lambda s: scope_verified(s, scope),
            prompt="Assess",
            session="same",
            max_resumes=5,
            no_progress_limit=2,
            wall_seconds=60,
            scope=scope,
        )
        assert result["boundary"] == ("aborted" if replacement else "unfinished")
        assert len(result["turns"]) == (1 if replacement else 2)


def test_scope_loader_rejects_labels_and_wrong_domain_fields(tmp_path):
    from scripts.workflow_completion import AssessmentScope

    path = tmp_path / "scope.json"
    path.write_text(
        json.dumps(
            {
                "trial_id": "neutral",
                "result_identity": "sha256:" + "a" * 64,
                "domain_ids": ["domain:missing"],
                "preferred_label": "low",
            }
        )
    )
    with pytest.raises(ValueError, match="requires only"):
        AssessmentScope.load(path)
    with pytest.raises(ValueError, match="invalid bound"):
        AssessmentScope("neutral", "sha256:" + "a" * 64, ("domain:invented",))


def test_receipt_reading_report_does_not_accept_narrative_or_partial_line(tmp_path):
    from scripts.workflow_completion import receipt_reading_report

    rows = [
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "rob2",
                "tool": "get_domain_context",
                "arguments": {"trial_id": "neutral"},
                "result": {
                    "structured_content": {
                        "outcome": "success",
                        "data": {
                            "reading_recovery": {
                                "trial_id": "neutral",
                                "windows": [
                                    {
                                        "source_id": "sh_0123456789abcdef",
                                        "page": 1,
                                        "start_line": 1,
                                        "end_line": 2,
                                    }
                                ],
                            }
                        },
                    }
                },
            },
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "All main pages read; complete."},
        },
    ]
    path = tmp_path / "reading.jsonl"
    path.write_text("\n".join(map(json.dumps, rows)))
    assert receipt_reading_report([path])["complete"] is False
    read = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "rob2",
            "tool": "read_pages",
            "arguments": {"trial_id": "neutral"},
            "result": {
                "structured_content": {
                    "outcome": "success",
                    "data": {
                        "pages": [
                            {
                                "source_id": "sh_0123456789abcdef",
                                "page": 1,
                                "returned_start_line": 1,
                                "returned_end_line": 2,
                                "passage_ref": None,
                                "numbered_text": "1|partial",
                            }
                        ]
                    },
                }
            },
        },
    }
    rows.append(read)
    path.write_text("\n".join(map(json.dumps, rows)))
    assert receipt_reading_report([path])["complete"] is False
    read["item"]["result"]["structured_content"]["data"]["pages"][0]["passage_ref"] = (
        "eh_0123456789abcdef"
    )
    path.write_text("\n".join(map(json.dumps, rows)))
    assert receipt_reading_report([path])["complete"] is True


def test_scoped_cursor_recovery_uses_only_current_authoritative_rob2_receipts(tmp_path):
    from scripts.workflow_completion import scoped_status

    scope, status = scoped_fixture(domains=())
    action = {
        "operation": "get_domain_context",
        "authority": "host",
        "trial_id": "neutral",
        "domain_id": "domain:selection",
        "cursor": "current-next",
    }
    item = {
        "type": "mcp_tool_call",
        "server": "rob2",
        "tool": "get_domain_context",
        "result": {
            "structured_content": {
                "outcome": "success",
                "head": {"state_revision": 4, "next_action": action},
                "data": {
                    "context_page": {
                        "trial_id": "neutral",
                        "domain_id": "domain:selection",
                        "snapshot_digest": "stable",
                        "index": 1,
                    }
                },
            }
        },
    }
    path = tmp_path / "cursor.jsonl"
    path.write_text(json.dumps({"type": "item.completed", "item": item}) + "\n")
    current = scoped_status(
        status, scope, result_identity=scope.result_identity, domain_records={}, traces=[path]
    )
    assert current["continuation"] == action
    item["result"]["structured_content"]["head"]["state_revision"] = 3
    path.write_text(json.dumps({"type": "item.completed", "item": item}) + "\n")
    stale = scoped_status(
        status, scope, result_identity=scope.result_identity, domain_records={}, traces=[path]
    )
    assert "cursor" not in stale["continuation"]
    item["server"] = "untrusted"
    path.write_text(json.dumps({"type": "item.completed", "item": item}) + "\n")
    assert not scoped_status(
        status, scope, result_identity=scope.result_identity, domain_records={}, traces=[path]
    )["host_progress"]["context_pages"]


def test_existing_bounded_reading_policy_and_out_of_scope_history_are_preserved():
    from scripts.workflow_completion import scope_verified, scoped_status

    scope, status = scoped_fixture("budget_limited")
    assert scope_verified(status, scope)
    prior = {
        "neutral:domain:randomization": {
            "domain_id": "domain:randomization",
            "identity": "sha256:" + "c" * 64,
        }
    }
    same = scoped_status(
        status,
        scope,
        result_identity=scope.result_identity,
        domain_records=prior,
        outside_scope_baseline={"neutral:domain:randomization": "sha256:" + "c" * 64},
    )
    assert same.get("outcome") != "condition"
    changed = scoped_status(
        status,
        scope,
        result_identity=scope.result_identity,
        domain_records=prior,
        outside_scope_baseline={},
    )
    assert changed["condition"]["code"] == "completion_scope_violated"


def test_missing_turn_usage_is_unknown_not_zero_cost(tmp_path):
    path = trace(tmp_path / "partial.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("\n".join(json.dumps(row) for row in rows if row["type"] != "turn.completed"))
    facts = trace_facts(path)
    assert facts["usage"] == {} and facts["usage_receipt_available"] is False
    assert facts["completed_turns"] == 0
