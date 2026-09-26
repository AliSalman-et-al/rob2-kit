from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rob2_kit.application.contracts import TOOL_NAMES
from rob2_kit.evaluation.observations import (
    DOCUMENTED_TOOLS,
    MANIFEST_SCHEMA,
    SEARCH_MODES,
    ObservationImportError,
    dump_observations,
    import_observations,
)

FIXTURE = Path(__file__).parent / "fixtures" / "observation_import" / "synthetic.jsonl"
MALICIOUS_FIXTURE = Path(__file__).parent / "fixtures" / "observation_import" / "malicious.jsonl"
REVIEW_FIXTURE = Path(__file__).parent / "fixtures" / "observation_import" / "review_required.jsonl"
CANONICAL_SAVE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "observation_import" / "canonical_save.jsonl"
)
SHA = "sha256:" + "a" * 64


def _manifest() -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "attempts": [
            {
                "attempt_id": "attempt-a",
                "trial_id": "trial-a",
                "result_id": SHA,
                "intervention_id": "intervention-a",
                "model": {"family": "model", "version": "v1"},
                "kit_revision": "revision-a",
                "transcripts": ["session-a"],
            }
        ],
        "transcripts": [
            {
                "transcript_id": "session-a",
                "session_id": "session-a",
                "attempt_id": "attempt-a",
                "phase": "assessment",
            }
        ],
    }


def test_import_is_deterministic_and_keeps_observations_structural() -> None:
    raw = FIXTURE.read_bytes()
    first = import_observations(_manifest(), {"session-a": raw})
    second = import_observations(_manifest(), {"session-a": raw})
    assert first == second
    assert first["reconciliation"] == {
        "workflow_attempts": 1,
        "records": 11,
        "imported_mcp_records": 9,
        "ignored_host_records": 2,
        "mcp_calls": 8,
        "searches": 2,
        "assessment_searches": 2,
    }
    attempt = first["attempts"][0]
    assert attempt["capture_status"] == "complete"
    assert attempt["terminal_disposition"] == "assessed"
    calls = {call["call_id"]: call for call in attempt["operations"]}
    assert calls["call_reject"]["status"] == "rejected"
    assert calls["call_reject"]["response"]["outcome"] == "error"
    assert calls["call_save"]["status"] == "accepted"
    assert calls["call_save"]["mutation"]["committed_evidence_ids"] is None
    assert calls["call_save"]["mutation"]["submitted_evidence_ids"] == ["eh_1111111111111111"]
    assert calls["call_save"]["mutation"]["supersedes"].startswith("sha256:")
    assert calls["call_select"]["selection"] == ["eh_1111111111111111"]
    assert calls["call_unmatched"]["status"] == "unmatched"
    assert calls["call_zero"]["response"]["zero_hits"] is True
    encoded = json.dumps(first, sort_keys=True)
    for forbidden in ("private query", "private rationale", "source_text", "reviewer"):
        assert forbidden not in encoded
    destination = FIXTURE.parent / "_artifact-test.json"
    second_destination = FIXTURE.parent / "_artifact-test-2.json"
    try:
        dump_observations(first, destination)
        dump_observations(second, second_destination)
        assert destination.read_bytes() == second_destination.read_bytes()
    finally:
        destination.unlink(missing_ok=True)
        second_destination.unlink(missing_ok=True)


def test_import_projects_validation_repairs_as_mechanical_events() -> None:
    raw = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "repair-call",
                    "type": "mcp_tool_call",
                    "server": "rob2",
                    "tool": "validate_domain_assessment",
                    "arguments": {"trial_id": "trial-a", "domain_id": "domain:missing"},
                    "result": {
                        "structured_content": {
                            "outcome": "repair",
                            "repairs": [
                                {
                                    "path": "/answers/0/answer",
                                    "code": "invalid_answer",
                                    "detail": "private detail omitted",
                                },
                                {
                                    "path": "/answers",
                                    "code": "missing_active_question",
                                    "detail": "private detail omitted",
                                },
                            ],
                        }
                    },
                },
            }
        )
        + "\n"
    ).encode()

    artifact = import_observations(_manifest(), {"session-a": raw})
    operation = artifact["attempts"][0]["operations"][0]

    assert operation["repair"] == {
        "kind": "mechanical_validation",
        "count": 2,
        "codes": ["invalid_answer", "missing_active_question"],
        "paths": ["/answers", "/answers/0/answer"],
        "rows": [
            {"code": "invalid_answer", "path": "/answers/0/answer"},
            {"code": "missing_active_question", "path": "/answers"},
        ],
    }
    assert "private detail omitted" not in json.dumps(artifact)


def test_current_receipts_keep_scope_handles_answers_batch_children_and_repair_rows() -> None:
    transcript = [
        {
            "type": "item.completed",
            "item": {
                "id": "batch-1",
                "type": "mcp_tool_call",
                "server": "rob2",
                "tool": "search_sources_batch",
                "arguments": {
                    "requests": [
                        {
                            "trial_id": "trial-a",
                            "source_id": "sh_0123456789abcdef",
                            "purpose_domain_id": "domain:missing",
                            "purpose_question_id": "sq:missing:data-available",
                            "query": "private query one",
                            "mode": "all",
                        },
                        {
                            "trial_id": "trial-a",
                            "query": "private query two",
                            "mode": "phrase",
                            "cursor": "sc_0123456789abcdef_2",
                        },
                    ]
                },
                "result": {
                    "structured_content": {
                        "outcome": "success",
                        "data": {
                            "results": [
                                {
                                    "index": 0,
                                    "result": {
                                        "outcome": "success",
                                        "data": {
                                            "hits": [{"source_id": "sh_0123456789abcdef"}],
                                            "next_cursor": "sc_0123456789abcdef_3",
                                        },
                                    },
                                },
                                {
                                    "index": 1,
                                    "result": {
                                        "outcome": "condition",
                                        "condition": {"code": "search_cursor_stale"},
                                    },
                                },
                            ]
                        },
                    }
                },
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "save-1",
                "type": "mcp_tool_call",
                "server": "rob2",
                "tool": "save_domain_judgment",
                "arguments": {"trial_id": "trial-a"},
                "result": {
                    "structured_content": {
                        "outcome": "success",
                        "data": {
                            "checkpoint": {
                                "identity": "sha256:" + "b" * 64,
                                "answers": [
                                    {
                                        "question_id": "sq:missing:data-available",
                                        "answer": "probably_no",
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
            "item": {
                "id": "repair-1",
                "type": "mcp_tool_call",
                "server": "rob2",
                "tool": "validate_domain_assessment",
                "arguments": {"trial_id": "trial-a"},
                "result": {
                    "structured_content": {
                        "outcome": "repair",
                        "data": {
                            "repairs": [{"path": "/answers/0/answer", "code": "invalid_answer"}]
                        },
                    }
                },
            },
        },
    ]
    raw = ("\n".join(json.dumps(row) for row in transcript) + "\n").encode()

    artifact = import_observations(_manifest(), {"session-a": raw})
    operations = {row["call_id"]: row for row in artifact["attempts"][0]["operations"]}

    batch = operations["batch-1"]["response"]
    assert artifact["reconciliation"]["searches"] == 2
    assert len(batch["logical_searches"]) == 2
    assert batch["logical_searches"][0]["scope"]["source_id"] == "sh_0123456789abcdef"
    assert batch["logical_searches"][0]["purpose"] == {
        "domain_id": "domain:missing",
        "question_id": "sq:missing:data-available",
    }
    assert batch["logical_searches"][0]["has_next_cursor"] is True
    assert batch["logical_searches"][1]["outcome"] == "condition"
    assert batch["logical_searches"][1]["has_cursor"] is True
    assert "sh_0123456789abcdef" in operations["batch-1"]["request_identities"]
    assert operations["save-1"]["mutation"]["committed_answers"] == [
        {"question_id": "sq:missing:data-available", "answer": "probably_no"}
    ]
    assert operations["repair-1"]["repair"]["codes"] == ["invalid_answer"]
    assert operations["repair-1"]["repair"]["rows"] == [
        {"path": "/answers/0/answer", "code": "invalid_answer"}
    ]


def test_event_positions_retain_overlap_restart_fallback_replay_and_missing_edges() -> None:
    def mcp(call_id: str, event_type: str, *, result: dict[str, Any] | None = None) -> dict:
        item: dict[str, Any] = {
            "id": call_id,
            "type": "mcp_tool_call",
            "server": "rob2",
            "tool": "read_pages",
            "arguments": {"trial_id": "trial-a"},
        }
        if result is not None:
            item["result"] = result
        return {"type": event_type, "item": item}

    text_result = {
        "content": [{"type": "text", "text": '{"outcome":"success","data":{"windows":[]}}'}]
    }
    structured_result = {"structured_content": {"outcome": "success", "data": {}}}
    rows = [
        {"type": "thread.started", "thread_id": "private-thread-one"},
        mcp("call-a", "item.started"),
        mcp("call-b", "item.started"),
        mcp("call-b", "item.completed", result=text_result),
        mcp("call-b", "item.completed", result=text_result),
        {"type": "thread.started", "thread_id": "private-thread-two"},
        mcp("call-a", "item.completed", result=structured_result),
        mcp("call-c", "item.completed", result=structured_result),
        mcp("call-d", "item.started"),
    ]
    raw = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    manifest = _manifest()
    manifest["transcripts"][0]["path"] = "eval/runs/frozen/phase.jsonl"

    artifact = import_observations(manifest, {"session-a": raw})
    attempt = artifact["attempts"][0]
    operations = {row["call_id"]: row for row in attempt["operations"]}

    assert [row["call_id"] for row in attempt["operations"]] == [
        "call-a",
        "call-b",
        "call-c",
        "call-d",
    ]
    assert [event["line"] for event in attempt["event_stream"]] == list(range(1, 10))
    assert attempt["transcripts"][0]["path"] == "eval/runs/frozen/phase.jsonl"
    assert attempt["transcripts"][0]["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert len(attempt["transcripts"][0]["thread_identities"]) == 2
    assert "private-thread-one" not in json.dumps(artifact)
    assert operations["call-a"]["event_order"]["started"]["line"] == 2
    assert operations["call-a"]["event_order"]["completed"]["line"] == 7
    assert operations["call-b"]["event_order"]["completion_events"] == [
        {"type": "item.completed", "event_ordinal": 4, "line": 4},
        {"type": "item.completed", "event_ordinal": 5, "line": 5},
    ]
    assert operations["call-b"]["response"]["encoding"] == "text_fallback"
    assert operations["call-c"]["event_order"]["started"] is None
    assert operations["call-c"]["event_order"]["completed"]["line"] == 8
    assert operations["call-d"]["event_order"]["started"]["line"] == 9
    assert operations["call-d"]["event_order"]["completed"] is None


def test_frozen_live_transcript_preserves_original_event_positions() -> None:
    path = (
        Path(__file__).parents[1]
        / "eval"
        / "runs"
        / "22-Sep-26"
        / "os-random-luna-medium-20260922-current"
        / "runs"
        / "overall-survival"
        / "CHAARTED"
        / "phase-2.jsonl"
    )
    raw = path.read_bytes()
    manifest = _manifest()
    manifest["transcripts"][0]["path"] = path.relative_to(Path(__file__).parents[1]).as_posix()

    artifact = import_observations(manifest, {"session-a": raw})
    operations = {row["call_id"]: row for row in artifact["attempts"][0]["operations"]}

    assert [row["call_id"] for row in artifact["attempts"][0]["operations"][:6]] == [
        f"item_{index}" for index in range(1, 7)
    ]
    assert operations["item_1"]["event_order"]["started"]["line"] == 4
    assert operations["item_1"]["event_order"]["completed"]["line"] == 5
    assert operations["item_6"]["event_order"]["started"]["line"] == 14
    assert operations["item_6"]["event_order"]["completed"]["line"] == 15
    assert len(operations["item_6"]["response"]["logical_searches"]) == 4
    assert all(
        search["outcome"] is not None
        for search in operations["item_6"]["response"]["logical_searches"]
    )


def test_unavailable_phase_delivery_and_cost_remain_unknown() -> None:
    manifest = _manifest()
    manifest["transcripts"][0].pop("phase")
    raw = (
        json.dumps(
            {
                "type": "item.started",
                "item": {
                    "id": "search-started",
                    "type": "mcp_tool_call",
                    "server": "rob2",
                    "tool": "search_sources",
                    "arguments": {"trial_id": "trial-a", "query": "private query", "mode": "all"},
                },
            }
        )
        + "\n"
    ).encode()

    artifact = import_observations(manifest, {"session-a": raw})
    attempt = artifact["attempts"][0]
    operation = attempt["operations"][0]

    assert attempt["transcripts"][0]["phase"] is None
    assert attempt["reconciliation"]["assessment_searches"] is None
    assert artifact["reconciliation"]["assessment_searches"] is None
    assert operation["status"] == "unmatched"
    assert operation["response"]["encoding"] == "unavailable"
    assert operation["metrics"]["cost"] is None


def test_documented_tools_match_the_public_contract() -> None:
    public_tools = frozenset(TOOL_NAMES)
    assert public_tools <= DOCUMENTED_TOOLS
    assert DOCUMENTED_TOOLS - public_tools == {
        "reason_domain_assessment",
        "reason_proposal",
        "request_trial_terminal",
    }


def test_duplicate_operation_identity_is_rejected_without_payload_echo() -> None:
    raw = FIXTURE.read_bytes().replace(
        b'"trial_id":"trial-a","query":"private query"',
        b'"trial_id":"trial-a","query":"different private query"',
        1,
    )
    with pytest.raises(
        ObservationImportError, match="ambiguous duplicate MCP operation identity"
    ) as error:
        import_observations(_manifest(), {"session-a": raw})
    assert "different private query" not in str(error.value)


def test_malformed_record_reports_location_without_echoing_payload() -> None:
    malformed = b'{"type":"item.completed","item":{"type":"mcp_tool_call","id":1}}\n'
    with pytest.raises(ObservationImportError, match="session-a:1") as error:
        import_observations(_manifest(), {"session-a": malformed})
    assert "mcp_tool_call" not in str(error.value)


def test_split_transcripts_keep_same_local_call_ids_distinct() -> None:
    manifest = _manifest()
    manifest["attempts"][0]["transcripts"] = ["part-a", "part-b"]
    manifest["transcripts"] = [
        {
            "transcript_id": "part-a",
            "session_id": "session-a",
            "attempt_id": "attempt-a",
            "phase": "assessment",
        },
        {
            "transcript_id": "part-b",
            "session_id": "session-a",
            "attempt_id": "attempt-a",
            "phase": "assessment",
        },
    ]
    first = {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "mcp_tool_call",
            "server": "rob2",
            "tool": "search_sources",
            "arguments": {"trial_id": "trial-a", "query": "one", "mode": "all"},
            "result": {"structured_content": {"outcome": "success", "data": {}}},
        },
    }
    second = {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "mcp_tool_call",
            "server": "rob2",
            "tool": "read_pages",
            "arguments": {"trial_id": "trial-a", "source_id": "source_aaaaaaaaaaaaaaaa"},
            "result": {"structured_content": {"outcome": "success", "data": {}}},
        },
    }
    artifact = import_observations(
        manifest,
        {
            "part-a": (json.dumps(first) + "\n").encode(),
            "part-b": (json.dumps(second) + "\n").encode(),
        },
    )
    operations = artifact["attempts"][0]["operations"]
    assert artifact["reconciliation"]["mcp_calls"] == 2
    assert {operation["tool"] for operation in operations} == {"search_sources", "read_pages"}
    assert len({operation["operation_id"] for operation in operations}) == 2


def test_operation_ids_encode_transcript_and_local_call_unambiguously() -> None:
    manifest = _manifest()
    manifest["attempts"][0]["transcripts"] = ["a:b", "a"]
    manifest["transcripts"] = [
        {
            "transcript_id": "a:b",
            "session_id": "same",
            "attempt_id": "attempt-a",
            "phase": "assessment",
        },
        {
            "transcript_id": "a",
            "session_id": "same",
            "attempt_id": "attempt-a",
            "phase": "assessment",
        },
    ]

    def record(call_id: str) -> bytes:
        return (
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": call_id,
                        "type": "mcp_tool_call",
                        "server": "rob2",
                        "tool": "read_pages",
                        "arguments": {"trial_id": "trial-a"},
                        "result": {"structured_content": {"outcome": "success", "data": {}}},
                    },
                }
            )
            + "\n"
        ).encode()

    artifact = import_observations(manifest, {"a:b": record("c"), "a": record("b:c")})
    operation_ids = [
        operation["operation_id"] for operation in artifact["attempts"][0]["operations"]
    ]
    assert len(operation_ids) == 2
    assert len(set(operation_ids)) == 2


@pytest.mark.parametrize(
    ("record_type", "result", "expected_status", "expected_disposition"),
    (
        (
            "item.completed",
            {
                "structured_content": {
                    "outcome": "success",
                    "data": {
                        "terminal": {
                            "identity": "sha256:" + "4" * 64,
                            "disposition": "needs_input",
                        }
                    },
                }
            },
            "accepted",
            "needs_input",
        ),
        (
            "item.completed",
            {"structured_content": {"outcome": "error", "data": {}}},
            "rejected",
            "unknown",
        ),
        ("item.started", None, "unmatched", "unknown"),
    ),
)
def test_terminal_disposition_requires_an_accepted_response(
    record_type: str,
    result: dict[str, Any] | None,
    expected_status: str,
    expected_disposition: str,
) -> None:
    manifest = _manifest()
    item: dict[str, Any] = {
        "id": "terminal_1",
        "type": "mcp_tool_call",
        "server": "rob2",
        "tool": "request_trial_terminal",
        "arguments": {
            "request": {
                "trial_id": "trial-a",
                "disposition": "needs_input",
                "reason": "Need clarification.",
                "missing_facts": ["fact"],
            },
            "expected_revision": 1,
        },
    }
    if result is not None:
        item["result"] = result
    else:
        item["status"] = "in_progress"
    raw = (json.dumps({"type": record_type, "item": item}) + "\n").encode()

    artifact = import_observations(manifest, {"session-a": raw})
    operation = artifact["attempts"][0]["operations"][0]
    assert operation["status"] == expected_status
    assert artifact["attempts"][0]["terminal_disposition"] == expected_disposition
    assert operation["mutation"]["accepted"] is (expected_status == "accepted")
    assert len(artifact["attempts"][0]["attempted_mutations"]) == 1


def test_malicious_nested_fields_are_not_emitted_and_enums_are_closed() -> None:
    artifact = import_observations(_manifest(), {"session-a": MALICIOUS_FIXTURE.read_bytes()})
    assert artifact["attempts"][0]["terminal_disposition"] == "unknown"
    allowed_keys = {
        "schema",
        "manifest_identity",
        "attempts",
        "reconciliation",
        "workflow_attempts",
        "attempt_id",
        "trial_id",
        "result_id",
        "intervention_id",
        "model",
        "family",
        "version",
        "kit_revision",
        "capture_status",
        "terminal_disposition",
        "operations",
        "operation_id",
        "session_id",
        "call_id",
        "transcript_id",
        "tool",
        "status",
        "scope",
        "domain_id",
        "question_id",
        "request_shape",
        "has_search_term",
        "mode",
        "limit",
        "has_cursor",
        "argument_count",
        "response",
        "present",
        "outcome",
        "response_bytes",
        "identities",
        "hit_count",
        "truncated",
        "zero_hits",
        "terminal_dispositions",
        "metrics",
        "cost",
        "tokens",
        "context_bytes",
        "latency_ms",
        "reconciliation",
        "records",
        "imported_mcp_records",
        "ignored_host_records",
        "mcp_calls",
        "searches",
        "assessment_searches",
        "attempted_mutations",
        "accepted_commits",
        "accepted",
        "checkpoint_identity",
        "supersedes",
        "selection",
        "submitted_evidence_ids",
        "committed_evidence_ids",
        "submitted_option_ids",
        "committed_option_ids",
        "repair",
        "rows",
        "kind",
        "count",
        "codes",
        "paths",
    }
    allowed_keys.update(
        {
            "transcripts",
            "digest",
            "path",
            "phase",
            "event_count",
            "thread_identities",
            "event_stream",
            "type",
            "event_ordinal",
            "line",
            "thread_identity",
            "thread_instance",
            "transcript_digest",
            "purpose",
            "request_identities",
            "source_id",
            "event_order",
            "started",
            "completed",
            "start_events",
            "completion_events",
            "encoding",
            "logical_searches",
            "continuation",
            "requested",
            "returned",
            "index",
            "has_next_cursor",
            "committed_answers",
            "answer",
        }
    )

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(child) for child in value))
        return set()

    assert keys(artifact) <= allowed_keys
    encoded = json.dumps(artifact, sort_keys=True)
    for forbidden in (
        "DO NOT EMIT THIS QUERY",
        "DO NOT EMIT THIS PROMPT",
        "DO NOT EMIT THIS RATIONALE",
        "DO NOT EMIT THIS SOURCE",
        "DO NOT EMIT THIS REVIEWER",
        "C:\\private\\file",
    ):
        assert forbidden not in encoded
    for attempt in artifact["attempts"]:
        assert attempt["terminal_disposition"] in {"assessed", "needs_input", "failed", "unknown"}
        for operation in attempt["operations"]:
            assert operation["tool"] in DOCUMENTED_TOOLS
            assert operation["request_shape"]["mode"] in SEARCH_MODES | {None}
            assert operation["status"] in {"accepted", "rejected", "unmatched"}
            assert operation["response"]["outcome"] in {
                "success",
                "review_required",
                "repair",
                "error",
                "condition",
                "conflict",
                None,
            }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("server", "evil", "unsupported MCP server"),
        ("tool", "evil_tool", "unsupported MCP tool"),
        ("mode", "wild", "unsupported search mode"),
    ),
)
def test_unsafe_capture_dimensions_are_rejected_without_echo(
    field: str, value: str, message: str
) -> None:
    raw = MALICIOUS_FIXTURE.read_bytes()
    if field == "server":
        raw = raw.replace(b'"server":"rob2"', b'"server":"evil"')
    elif field == "tool":
        raw = raw.replace(b'"tool":"search_sources"', b'"tool":"evil_tool"')
    else:
        raw = raw.replace(b'"mode":"all"', b'"mode":"wild"')
    with pytest.raises(ObservationImportError, match=message) as error:
        import_observations(_manifest(), {"session-a": raw})
    assert value not in str(error.value)
    assert "DO NOT EMIT" not in str(error.value)


def test_manifest_phase_is_closed() -> None:
    manifest = _manifest()
    manifest["transcripts"][0]["phase"] = "other"
    with pytest.raises(ObservationImportError, match="invalid transcript phase"):
        import_observations(manifest, {"session-a": FIXTURE.read_bytes()})


def test_finalize_without_observed_disposition_is_complete_but_unknown() -> None:
    raw = FIXTURE.read_bytes().replace(
        b'"trial_dispositions":{"trial-a":"assessed"}',
        b'"trial_dispositions":{}',
    )
    attempt = import_observations(_manifest(), {"session-a": raw})["attempts"][0]
    assert attempt["capture_status"] == "complete"
    assert attempt["terminal_disposition"] == "unknown"


def test_operation_ids_are_unique_across_attempt_transcripts() -> None:
    first = _manifest()
    second = copy.deepcopy(first["attempts"][0])
    second["attempt_id"] = "attempt-b"
    second["transcripts"] = ["session-b"]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "attempts": [first["attempts"][0], second],
        "transcripts": [
            {
                "transcript_id": "session-a",
                "session_id": "same",
                "attempt_id": "attempt-a",
                "phase": "assessment",
            },
            {
                "transcript_id": "session-b",
                "session_id": "same",
                "attempt_id": "attempt-b",
                "phase": "assessment",
            },
        ],
    }
    artifact = import_observations(
        manifest,
        {"session-a": FIXTURE.read_bytes(), "session-b": FIXTURE.read_bytes()},
    )
    first_id = artifact["attempts"][0]["operations"][0]["operation_id"]
    second_id = artifact["attempts"][1]["operations"][0]["operation_id"]
    assert first_id != second_id


def test_orphan_and_mixed_phase_transcripts_are_rejected() -> None:
    orphan = _manifest()
    orphan["transcripts"].append(
        {"transcript_id": "orphan", "attempt_id": "missing", "phase": "assessment"}
    )
    with pytest.raises(ObservationImportError, match="no declared attempt"):
        import_observations(orphan, {"session-a": FIXTURE.read_bytes(), "orphan": b""})

    mixed = _manifest()
    mixed["attempts"][0]["transcripts"].append("session-b")
    mixed["transcripts"].append({"transcript_id": "session-b", "attempt_id": "attempt-a"})
    with pytest.raises(ObservationImportError, match="phase must be declared"):
        import_observations(
            mixed,
            {"session-a": FIXTURE.read_bytes(), "session-b": FIXTURE.read_bytes()},
        )


def test_review_required_proposal_save_is_an_accepted_mutation() -> None:
    artifact = import_observations(_manifest(), {"session-a": REVIEW_FIXTURE.read_bytes()})
    attempt = artifact["attempts"][0]
    operation = attempt["operations"][0]
    assert operation["response"]["outcome"] == "review_required"
    assert operation["status"] == "accepted"
    assert attempt["accepted_commits"][0]["accepted"] is True


def test_committed_save_uses_canonical_option_and_evidence_only() -> None:
    artifact = import_observations(_manifest(), {"session-a": CANONICAL_SAVE_FIXTURE.read_bytes()})
    operation = next(
        operation
        for operation in artifact["attempts"][0]["operations"]
        if operation["call_id"] == "save"
    )
    mutation = operation["mutation"]
    assert mutation["submitted_option_ids"] == ["opt_active123456789", "opt_inactive1234567"]
    assert mutation["committed_option_ids"] == ["opt_active123456789"]
    assert mutation["submitted_evidence_ids"] is None
    assert mutation["committed_evidence_ids"] == ["eh_2222222222222222"]
    commit = artifact["attempts"][0]["accepted_commits"][0]
    assert commit["committed_option_ids"] == ["opt_active123456789"]


def test_revision_projection_retains_before_after_state_without_scientific_prose() -> None:
    first_identity = "sha256:" + "6" * 64
    second_identity = "sha256:" + "7" * 64
    transcript = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "first",
                    "type": "mcp_tool_call",
                    "server": "rob2",
                    "tool": "save_domain_judgment",
                    "arguments": {"trial_id": "trial-a", "domain_id": "domain:randomization"},
                    "result": {
                        "structured_content": {
                            "outcome": "success",
                            "data": {
                                "checkpoint": {
                                    "identity": first_identity,
                                    "answers": [
                                        {
                                            "question_id": "sq:randomization:sequence",
                                            "answer": "no_information",
                                            "justification": "Initial private justification.",
                                            "unknowns": ["Initial private unknown."],
                                            "counterevidence": [],
                                            "bases": [
                                                {
                                                    "kind": "direct_support",
                                                    "evidence": "eh_3333333333333333",
                                                    "source_id": "source_aaaaaaaaaaaaaaaa",
                                                    "page": 2,
                                                    "start_line": 4,
                                                    "end_line": 6,
                                                }
                                            ],
                                        }
                                    ],
                                }
                            },
                        }
                    },
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "second",
                    "type": "mcp_tool_call",
                    "server": "rob2",
                    "tool": "save_domain_judgment",
                    "arguments": {"trial_id": "trial-a", "domain_id": "domain:randomization"},
                    "result": {
                        "structured_content": {
                            "outcome": "success",
                            "data": {
                                "checkpoint": {
                                    "identity": second_identity,
                                    "supersedes": first_identity,
                                    "revision_basis": {
                                        "kind": "self_correction",
                                        "rationale": "Private revision rationale.",
                                    },
                                    "answers": [
                                        {
                                            "question_id": "sq:randomization:sequence",
                                            "answer": "probably_no",
                                            "justification": "Updated private justification.",
                                            "unknowns": [],
                                            "counterevidence": ["Updated private counterpoint."],
                                            "bases": [
                                                {
                                                    "kind": "direct_support",
                                                    "evidence": "eh_3333333333333333",
                                                    "source_id": "source_aaaaaaaaaaaaaaaa",
                                                    "page": 2,
                                                    "start_line": 4,
                                                    "end_line": 6,
                                                }
                                            ],
                                        }
                                    ],
                                }
                            },
                        }
                    },
                },
            }
        )
    ).encode()

    artifact = import_observations(_manifest(), {"session-a": transcript})
    operations = artifact["attempts"][0]["operations"]
    revision = next(
        operation["mutation"]["revision"]
        for operation in operations
        if operation["call_id"] == "second"
    )

    assert revision["before_identity"] == first_identity
    assert revision["after_identity"] == second_identity
    assert revision["before"][0]["answer"] == "no_information"
    assert revision["after"][0]["answer"] == "probably_no"
    assert revision["before"][0]["evidence_locators"][0]["page"] == 2
    assert revision["revision_reason"]["kind"] == "self_correction"
    assert revision["revision_reason"]["rationale_bytes"] > 0
    encoded = json.dumps(artifact, sort_keys=True)
    for forbidden in (
        "Initial private justification",
        "Initial private unknown",
        "Updated private justification",
        "Updated private counterpoint",
        "Private revision rationale",
    ):
        assert forbidden not in encoded
