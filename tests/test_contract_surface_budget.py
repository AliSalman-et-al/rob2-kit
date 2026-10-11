"""Behavioral guardrails for the public FastMCP contract size and closure."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rob2_kit.interfaces.mcp.server import mcp


def _walk(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value, *[item for child in value.values() for item in _walk(child)]]
    if isinstance(value, list):
        return [item for child in value for item in _walk(child)]
    return []


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local JSON Schema reference without requiring dereferencing."""

    reference = node.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return node
    resolved: Any = schema
    for part in reference.removeprefix("#/").split("/"):
        resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(resolved, dict)
    return resolved


def test_public_output_surface_is_closed_and_within_budget() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert tuple(tool.name for tool in tools) == (
        "read_guidance",
        "calculate_arithmetic",
        "prepare_batch",
        "get_status",
        "save_working_checkpoint",
        "request_companion_source",
        "acquire_companion_source",
        "admit_companion_source",
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
        and tool.annotations.idempotent_hint
        is (tool.name not in {"acquire_companion_source", "admit_companion_source"})
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
    # Two companion operations and durable typed status recovery add 18 KB.
    # Authored bookmark provenance and bound outline/read actions add 14 KB; measured 667054.
    # Conditional event-definition disclosure and field descriptions measure 680803 bytes.
    # v0.12 adds source-bound ancillary statistics and numerical-role scope review.
    # After removing redundant descriptions: 688577 aggregate bytes (+7774 from
    # 680803, 1.14%). This sums 23 closed input/output schemas, not observed host
    # prompt tokens. Keep the new observations typed rather than hiding them.
    # The Domain reference, reading leads and registry registration dates add
    # typed navigation (690795 measured). A read_pages next action for the
    # post-approval reading gate repeats in every head (716851 measured).
    assert total_bytes < 720_000

    by_name = {tool.name: tool for tool in tools}
    search_annotations = by_name["search_sources"].annotations
    text_annotations = by_name["select_text_evidence"].annotations
    visual_annotations = by_name["select_visual_evidence"].annotations
    assert search_annotations is not None and search_annotations.read_only_hint is True
    assert text_annotations is not None and text_annotations.read_only_hint is False
    assert visual_annotations is not None and visual_annotations.read_only_hint is False

    search_parameters = by_name["search_sources"].parameters
    read_parameters = by_name["read_pages"].parameters
    source_parameters = by_name["list_sources"].parameters
    assert all(name in search_parameters["required"] for name in ("trial_id", "query", "mode"))
    batch_requests = by_name["search_sources_batch"].parameters["properties"]["requests"]
    assert batch_requests["maxItems"] == 8
    assert batch_requests["minItems"] == 1
    source_scope = search_parameters["properties"]["source_id"]
    assert source_scope["default"] is None
    assert source_scope["anyOf"][0]["pattern"] == r"^sh_[0-9a-f]{16}$"
    assert source_parameters["properties"]["limit"]["le"] == 12
    assert read_parameters["properties"]["pages"]["examples"] == [[1, 3]]
    domain_tool = by_name["save_domain_judgment"]
    answer_schema = _resolve(
        domain_tool.parameters,
        domain_tool.parameters["properties"]["answers"]["items"],
    )
    assert set(answer_schema["required"]) == {
        "question_id",
        "answer",
        "justification",
        "unknowns",
        "counterevidence",
    }
    assert "multiple_concerns" not in domain_tool.parameters["properties"]
    assert "examples" not in by_name["review_trial"].parameters["properties"]["request"]


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
    assert mcp.version == "0.12.0"
    assert mcp.website_url == "https://github.com/AliSalman-et-al/rob2-kit"
    assert len(resources) == 1
    resource = resources[0]
    assert str(resource.uri) == "rob2://current-batch"
    assert resource.title == "Current batch status"
    assert resource.mime_type == "application/json"
    assert (resource.description or "").strip()
