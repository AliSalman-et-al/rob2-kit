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
        "get_domain_context",
        "save_domain_judgment",
        "request_trial_terminal",
        "finalize_batch",
    )
    schemas = [tool.output_schema for tool in tools]
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
    assert total_bytes < 230_000

    by_name = {tool.name: tool for tool in tools}
    search_annotations = by_name["search_sources"].annotations
    text_annotations = by_name["select_text_evidence"].annotations
    visual_annotations = by_name["select_visual_evidence"].annotations
    assert search_annotations is not None and search_annotations.readOnlyHint is True
    assert text_annotations is not None and text_annotations.readOnlyHint is False
    assert visual_annotations is not None and visual_annotations.readOnlyHint is False

    search_description = by_name["search_sources"].description or ""
    search_parameters = by_name["search_sources"].parameters
    read_description = by_name["read_pages"].description or ""
    select_description = by_name["select_text_evidence"].description or ""
    assert "1-based source indexes" in search_description
    assert "phrase only for known contiguous wording" in search_description
    source_scope = search_parameters["properties"]["source_id"]
    assert source_scope["default"] is None
    assert source_scope["anyOf"][0]["pattern"] == r"^source_[0-9a-f]{64}$"
    assert "not printed labels" in read_description
    assert "numbered lines" in read_description
    assert "one contiguous range" in select_description
    assert "one selection per page" in select_description


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
    assert "Target timing and arm assignments require selected source support" in (
        normalized_instructions
    )
    for deleted_instruction in (
        "Use Table Evidence",
        "Use Derived Evidence",
        '{"kind":"narrative","handle":"eh_..."}',
        "mark its clarity",
        "add a complete alternative",
        "Target method, timing, intended population",
    ):
        assert deleted_instruction not in normalized_instructions
