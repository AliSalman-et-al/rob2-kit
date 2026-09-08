from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

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


def test_split_transcripts_deduplicate_calls_within_one_session() -> None:
    lines = FIXTURE.read_bytes().splitlines(keepends=True)
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
    artifact = import_observations(
        manifest,
        {"part-a": b"".join(lines[:2]), "part-b": b"".join(lines[2:])},
    )
    assert artifact["reconciliation"]["mcp_calls"] == 8
    assert len(artifact["attempts"][0]["operations"]) == 8


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
    }

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


def test_operation_ids_include_attempt_identity() -> None:
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
