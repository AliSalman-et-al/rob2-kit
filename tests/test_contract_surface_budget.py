"""Behavioral guardrails for the public FastMCP contract size and closure."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rob2_kit.interfaces.mcp.server import mcp


def _walk(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value, *[item for child in value.values() for item in _walk(child)]]
    if isinstance(value, list):
        return [item for child in value for item in _walk(child)]
    return []


def test_public_output_surface_is_closed_and_within_budget() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert tuple(tool.name for tool in tools) == (
        "prepare_batch",
        "get_status",
        "list_sources",
        "search_sources",
        "read_pages",
        "select_text_evidence",
        "render_page",
        "select_visual_evidence",
        "save_proposal",
        "request_proposal_approval",
        "get_domain_context",
        "save_domain_judgment",
        "request_trial_terminal",
        "finalize_batch",
    )
    schemas = [tool.output_schema for tool in tools]
    assert all((tool.title or "").strip() for tool in tools)
    assert all((tool.description or "").strip() for tool in tools)
    assert all(tool.annotations is not None for tool in tools)
    assert all(
        tool.annotations is not None
        and tool.annotations.destructive_hint is False
        and tool.annotations.idempotent_hint is True
        for tool in tools
    )
    assert all(
        property_schema.get("description")
        for tool in tools
        for node in _walk(tool.parameters)
        for property_schema in node.get("properties", {}).values()
    )
    assert all(isinstance(schema, dict) for schema in schemas)
    closed_schemas = [schema for schema in schemas if isinstance(schema, dict)]
    assert all(schema.get("type") == "object" for schema in closed_schemas)
    assert all(
        node.get("additionalProperties") is False
        for schema in closed_schemas
        for node in _walk(schema)
        if node.get("type") == "object" and "properties" in node
    )
    total_bytes = sum(
        len(json.dumps(schema, separators=(",", ":")))
        + len(json.dumps(tool.parameters, separators=(",", ":")))
        for tool, schema in zip(tools, closed_schemas, strict=True)
    )
    # This is a ceiling, not a target. Smaller closed schemas are better.
    # v0.5 adds stable search-session metadata, option cards, and bounded
    # domain comparison projections to the closed output contract.
    assert total_bytes < 260_000

    by_name = {tool.name: tool for tool in tools}
    search_annotations = by_name["search_sources"].annotations
    text_annotations = by_name["select_text_evidence"].annotations
    visual_annotations = by_name["select_visual_evidence"].annotations
    assert search_annotations is not None and search_annotations.read_only_hint is True
    assert text_annotations is not None and text_annotations.read_only_hint is False
    assert visual_annotations is not None and visual_annotations.read_only_hint is False

    search_description = by_name["search_sources"].description or ""
    search_parameters = by_name["search_sources"].parameters
    search_mode_description = search_parameters["properties"]["mode"]["description"]
    read_description = by_name["read_pages"].description or ""
    read_parameters = by_name["read_pages"].parameters
    select_description = by_name["select_text_evidence"].description or ""
    assert "1-based source indexes" in search_description
    assert "Required: trial_id, query, mode" in search_description
    assert "mode" in search_parameters["required"]
    assert "broad discovery" in search_mode_description
    assert "Required lexical intent" in search_mode_description
    assert "all=every token on one page" in search_mode_description
    assert "phrase=known contiguous wording" in search_mode_description
    assert "one executable any broadening" in search_description
    assert search_parameters["properties"]["query"]["examples"] == ["central randomization"]
    source_scope = search_parameters["properties"]["source_id"]
    assert source_scope["default"] is None
    assert source_scope["anyOf"][0]["pattern"] == r"^source_[0-9a-f]{64}$"
    assert "not printed labels" in read_description
    assert "numbered lines" in read_description
    assert "required for every read" in read_parameters["properties"]["trial_id"]["description"]
    assert "integer source-page indexes" in read_parameters["properties"]["pages"]["description"]
    assert read_parameters["properties"]["pages"]["examples"] == [[1, 3]]
    assert "one contiguous range" in select_description
    assert "one selection per page" in select_description
    assert "start_text" not in select_description
    assert "end_text" not in select_description
    windows_description = read_parameters["properties"]["windows"]["description"]
    assert "Supply trial_id and windows" in windows_description
    assert "top-level start_line" in windows_description
    read_window = read_parameters["properties"]["windows"]["anyOf"][0]["items"]
    assert "Captured Source ID" in read_window["properties"]["source_id"]["description"]
    assert "One-based Source-page index" in read_window["properties"]["page"]["description"]
    domain_tool = by_name["save_domain_judgment"]
    context_tool = by_name["get_domain_context"]
    assert "current checkpoint" in (context_tool.description or "")
    assert "recovery.trial_id and recovery.windows" in (context_tool.description or "")
    workspace_schema = next(
        node
        for node in _walk(context_tool.output_schema)
        if "recoverable_narrative_text_budget" in node.get("properties", {})
    )
    workspace_properties = workspace_schema["properties"]
    assert (
        "duplicate checkpoint basis"
        in workspace_properties["omitted_narrative_text_bytes"]["description"]
    )
    assert (
        "narrative Evidence items"
        in workspace_properties["omitted_narrative_text_count"]["description"]
    )
    assert (
        "outside the narrative budget"
        in workspace_properties["unavoidable_non_narrative_text_bytes"]["description"]
    )
    assert "activated by the selected options" in (domain_tool.description or "")
    assert "check each basis against the approved Result" in (domain_tool.description or "")
    assert "grouped repairs without committing" in (domain_tool.description or "")
    answer_example = domain_tool.parameters["properties"]["answers"]["examples"][0][0]
    assert set(answer_example) == {"question_id", "option_id", "bases"}
    assert set(answer_example["bases"][0]) == {"kind", "evidence"}
    multiple_concerns = domain_tool.parameters["properties"]["multiple_concerns"]
    assert set(multiple_concerns["examples"][0]) == {
        "raises_overall_to_high",
        "rationale",
    }
    assert "Omit unless a repair requests" in multiple_concerns["description"]
    assert "never boolean/string" in multiple_concerns["description"]


def test_server_and_resource_metadata_are_explicit() -> None:
    async def metadata() -> tuple[Any, list[Any]]:
        from fastmcp import Client

        async with Client(mcp) as client:
            return client.initialize_result, list(await client.list_resources())

    initialization, resources = asyncio.run(metadata())
    # FastMCP 4 stores handshake metadata on the server object rather than
    # exposing the initialize result through its in-process client.
    assert initialization is None
    assert mcp.name == "rob2-kit"
    assert mcp.version == "0.5.0"
    assert mcp.website_url == "https://github.com/AliSalman-et-al/rob2-kit"
    assert len(resources) == 1
    resource = resources[0]
    assert str(resource.uri) == "rob2://current-batch"
    assert resource.title == "Current batch status"
    assert resource.mime_type == "application/json"
    assert (resource.description or "").strip()


def test_required_skill_references_match_handle_only_proposal_contract() -> None:
    skill_root = Path("src/rob2_kit/skills/rob2-assess")
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    evidence = (skill_root / "references/evidence.md").read_text(encoding="utf-8")
    result = (skill_root / "references/result.md").read_text(encoding="utf-8")
    required_instructions = "\n".join((skill, evidence, result))
    normalized_instructions = " ".join(required_instructions.split())

    assert "Do not send an `evidence` field" in evidence
    assert "not printed page labels" in required_instructions
    assert "never reconstruct PDF text" in required_instructions
    assert "one selection on each page" in normalized_instructions
    assert "timing and arm assignments" in normalized_instructions
    assert "do not need duplicate source quotations" in normalized_instructions
    for deleted_instruction in (
        "Use Table Evidence",
        "Use Derived Evidence",
        '{"kind":"narrative","handle":"eh_..."}',
        "mark its clarity",
        "add a complete alternative",
    ):
        assert deleted_instruction not in normalized_instructions
