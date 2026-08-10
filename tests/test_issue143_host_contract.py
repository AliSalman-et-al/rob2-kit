"""MCP exposes only the v2 Evidence-navigation transport shapes."""

from __future__ import annotations

import anyio

from rob2_kit.interfaces.mcp.server import create_server


def test_mcp_evidence_navigation_is_v2_only() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search = tools["search_evidence"].input_schema["properties"]
    read = tools["read_evidence"].input_schema["properties"]
    review = tools["submit_evidence_review"].input_schema["properties"]
    freeze = tools["submit_domain_evidence"].input_schema["properties"]

    assert {"attempt_id", "attempt_kind", "continuation", "continue_reason"} <= set(search)
    assert "cursor" not in search
    assert "batch" in read
    assert not {"location_handle", "mode", "cursor", "sq_id"}.intersection(read)
    assert {"submission_id", "page_handles", "triage_revisions", "contract_version"} <= set(review)
    assert freeze["contract_version"]["const"] == "2.0.0"
