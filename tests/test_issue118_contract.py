"""Public #118 contract guardrails, separate from retrieval and review mechanics."""

from __future__ import annotations

import anyio

from rob2_kit.interfaces.mcp.server import create_server


def _tools() -> dict[str, object]:
    return {tool.name: tool for tool in anyio.run(create_server().list_tools)}


def test_public_evidence_guidance_distinguishes_visibility_review_and_freeze() -> None:
    reference = open("docs/EVIDENCE-SEARCH.md", encoding="utf-8").read()
    skill = open("skills/rob2-assess/SKILL.md", encoding="utf-8").read()

    for text in (reference, skill):
        assert "location_handle" in text
        assert "include_other_trial" in text
        assert "include_uncertain" in text
        assert "projection" in text
        assert "visual" in text

    assert "search -> read/expand -> semantic review -> exact-span freeze" in reference
    assert "not hide a candidate or make it citable" in reference
    assert "append-only" in reference
    assert "stale-handle" in reference


def test_mcp_search_advertises_visible_candidates_and_retired_override_upgrade() -> None:
    search_tool = _tools()["search_evidence"]
    schema = search_tool.input_schema
    properties = schema["properties"]
    description = search_tool.description or ""

    assert "location handles" in description
    assert "other-Trial" in description
    for name in ("include_other_trial", "include_uncertain"):
        override = properties[name]
        assert override["deprecated"] is True
        assert "upgrade_required" in override["description"]


def test_mcp_freeze_schema_exposes_append_only_review_provenance() -> None:
    freeze_tool = _tools()["submit_domain_evidence"]
    review = freeze_tool.input_schema["properties"]["review_revisions"]
    description = freeze_tool.description or ""

    assert "append-only" in review["description"].lower()
    assert "context handles" in review["description"]
    assert "needs_visual_review" in description
    assert "search projection" in description


def test_mcp_read_uses_opaque_location_handle_instead_of_unit_id() -> None:
    read_tool = _tools()["read_evidence"]
    properties = read_tool.input_schema["properties"]

    assert "location_handle" in properties
    assert "unit_id" not in properties
    assert "location handle" in (read_tool.description or "").lower()


def test_legacy_visibility_override_returns_typed_upgrade_recovery() -> None:
    server = create_server()
    token = {
        "token": "token:issue118",
        "run_id": "run:issue118",
        "work_item_id": "work-item:issue118",
        "operation": "submit_domain_evidence",
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke() -> object:
        return await server.call_tool(
            "search_evidence",
            {
                "run_id": "run:issue118",
                "query": {"terms": ["allocation"]},
                "work_token": token,
                "sq_id": "sq:randomization",
                "include_other_trial": False,
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == "invalid_request"
    assert error["field"] == "include_other_trial"
    assert error["message"].startswith("upgrade_required:")
    assert error["recovery"][0] == "remove the retired override"
