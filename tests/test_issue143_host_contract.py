"""MCP exposes only question-scoped v3 Evidence-navigation transport shapes."""

from __future__ import annotations

import anyio

from rob2_kit.interfaces.mcp.server import create_server


def test_mcp_evidence_navigation_is_question_scoped_and_v3_only() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search = tools["search_evidence"].input_schema["properties"]
    read = tools["read_evidence"].input_schema["properties"]
    review = tools["submit_evidence_review"].input_schema["properties"]
    outcome = tools["submit_evidence_stage_outcome"].input_schema["properties"]
    freeze = tools["materialize_question_evidence_bundle"].input_schema["properties"]

    assert {
        "question_id",
        "session_content_hash",
        "proposition_id",
        "pass_id",
        "stage_id",
        "intent_id",
    } <= set(search)
    assert "batch" in read
    assert {"question_id", "session_content_hash", "triage_revisions"} <= set(review)
    assert outcome["contract_version"]["const"] == "3.0.0"
    assert freeze["contract_version"]["const"] == "3.0.0"
    assert {
        "question_id",
        "session_content_hash",
        "frontier_entry_hash",
        "expected_navigation_state_hash",
    } <= set(freeze)
    assert "submit_domain_evidence" not in tools
    assert "submit_domain_answers" not in tools
