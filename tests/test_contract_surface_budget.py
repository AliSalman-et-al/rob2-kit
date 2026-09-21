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
        "save_working_checkpoint",
        "list_sources",
        "search_sources",
        "search_sources_batch",
        "read_pages",
        "select_text_evidence",
        "render_page",
        "select_visual_evidence",
        "validate_proposal",
        "save_proposal",
        "request_proposal_approval",
        "get_domain_context",
        "validate_domain_assessment",
        "save_domain_judgment",
        "review_trial",
        "close_trial",
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
    # Search recovery, Porter/literal profiles, explicit search purpose,
    # spelling feedback, bounded source navigation, independent batched search,
    # review attribution, closure operations, evidence-sufficiency receipts,
    # and overall aggregation receipts add schema surface. Keep a small explicit
    # ceiling above the measured contract rather than silently dropping typed
    # provenance from the public output. D3 semantics, Source coverage,
    # premise records, and stable-context recovery are deliberate additions to
    # that surface; continuation payloads themselves no longer repeat it.
    assert total_bytes < 635_000

    by_name = {tool.name: tool for tool in tools}
    search_annotations = by_name["search_sources"].annotations
    text_annotations = by_name["select_text_evidence"].annotations
    visual_annotations = by_name["select_visual_evidence"].annotations
    assert search_annotations is not None and search_annotations.read_only_hint is True
    assert text_annotations is not None and text_annotations.read_only_hint is False
    assert visual_annotations is not None and visual_annotations.read_only_hint is False

    search_description = by_name["search_sources"].description or ""
    batch_search_description = by_name["search_sources_batch"].description or ""
    search_parameters = by_name["search_sources"].parameters
    search_mode_description = search_parameters["properties"]["mode"]["description"]
    read_description = by_name["read_pages"].description or ""
    read_parameters = by_name["read_pages"].parameters
    source_parameters = by_name["list_sources"].parameters
    select_description = by_name["select_text_evidence"].description or ""
    assert "captured Trial sources" in search_description
    assert all(name in search_parameters["required"] for name in ("trial_id", "query", "mode"))
    assert "mode" in search_parameters["required"]
    assert "broad discovery" in search_mode_description
    assert "Required lexical intent" in search_mode_description
    assert "all=every token on one page" in search_mode_description
    assert "phrase=known contiguous wording" in search_mode_description
    assert "zero-hit receipt describes only the issued lexical query" in search_description
    assert "Validate every request" in batch_search_description
    assert "byte budget includes metadata" in batch_search_description
    batch_requests = by_name["search_sources_batch"].parameters["properties"]["requests"]
    assert batch_requests["maxItems"] == 8
    assert batch_requests["minItems"] == 1
    assert search_parameters["properties"]["query"]["examples"] == ["central randomization"]
    source_scope = search_parameters["properties"]["source_id"]
    assert source_scope["default"] is None
    assert source_scope["anyOf"][0]["pattern"] == r"^sh_[0-9a-f]{16}$"
    source_limit = source_parameters["properties"]["limit"]
    assert source_limit["le"] == 12
    assert "default is 12" in source_limit["description"]
    assert "not printed labels" in read_description
    assert "numbered lines" in read_description
    assert "data.remaining_windows" in read_description
    assert (
        "oversized physical line is returned across lossless character fragments"
        in read_description
    )
    assert "there is no top-level end_line" in read_description
    assert "data.pages[].numbered_text" in read_description
    assert "data.remaining_windows" in read_description
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
    assert (
        "Copy the returned source_id exactly"
        in read_window["properties"]["source_id"]["description"]
    )
    assert "One-based Source-page index" in read_window["properties"]["page"]["description"]
    domain_tool = by_name["validate_domain_assessment"]
    save_tool = by_name["save_domain_judgment"]
    context_tool = by_name["get_domain_context"]
    assert "current Domain checkpoint" in (context_tool.description or "")
    assert "restart without a cursor" in (context_tool.description or "")
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
        "outside the recoverable narrative budget"
        in workspace_properties["unrecoverable_inline_text_bytes"]["description"]
    )
    assert "Before saving a Domain" in (domain_tool.description or "")
    assert "counterevidence and unresolved facts" in (domain_tool.description or "")
    answer_schema = domain_tool.parameters["properties"]["answers"]["items"]
    assert set(answer_schema["required"]) >= {"question_id", "answer", "bases"}
    assert "active answer" in answer_schema["properties"]["justification"]["description"]
    assert "inactive branch answers" in answer_schema["properties"]["unknowns"]["description"]
    assert "exact Domain draft stored" in (save_tool.description or "")
    assert "multiple_concerns" not in domain_tool.parameters["properties"]
    proposal_tool = by_name["validate_proposal"]
    assert proposal_tool.title == "Validate Proposal draft"
    assert "complete typed request" in (proposal_tool.description or "")
    assert "partial nested objects" in (proposal_tool.description or "")
    visual_tool = by_name["select_visual_evidence"]
    assert "accepts only" in (visual_tool.description or "")
    assert "attach the returned Evidence later" in (visual_tool.description or "")
    approval_description = by_name["request_proposal_approval"].description or ""
    assert "has no approval arguments" in approval_description
    assert "with {}" in approval_description
    assert "Call get_status" in approval_description
    review_tool = by_name["review_trial"]
    assert "With no request" in (review_tool.description or "")
    assert "deterministic Cochrane" in (review_tool.description or "")
    review_request = review_tool.parameters["properties"]["request"]
    assert "examples" not in review_request
    assert "permitted uncertainty answer" in review_request["description"]


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
    assert mcp.version == "0.9.0"
    assert mcp.website_url == "https://github.com/AliSalman-et-al/rob2-kit"
    assert len(resources) == 1
    resource = resources[0]
    assert str(resource.uri) == "rob2://current-batch"
    assert resource.title == "Current batch status"
    assert resource.mime_type == "application/json"
    assert (resource.description or "").strip()


def test_required_skill_references_match_receipt_only_proposal_contract() -> None:
    skill_root = Path("src/rob2_kit/skills/rob2-assess")
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    evidence = (skill_root / "references/evidence.md").read_text(encoding="utf-8")
    result = (skill_root / "references/result.md").read_text(encoding="utf-8")
    required_instructions = "\n".join((skill, evidence, result))
    normalized_instructions = " ".join(required_instructions.split())

    assert "Do not place Evidence objects in `reported`" in evidence
    assert "live `validate_proposal` schema" in normalized_instructions
    assert "`save_proposal` consumes the receipt returned by that call" in normalized_instructions
    assert "not printed page labels" in required_instructions
    assert "never reconstruct PDF text" in required_instructions
    assert "one selection on each page" in normalized_instructions
    assert "timing, and arm assignments" in normalized_instructions
    assert "do not need duplicate source quotations" in normalized_instructions
    for deleted_instruction in (
        "Use Table Evidence",
        "Use Derived Evidence",
        '{"kind":"narrative","handle":"eh_..."}',
        "mark its clarity",
        "add a complete alternative",
    ):
        assert deleted_instruction not in normalized_instructions
