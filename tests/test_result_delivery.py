"""Wire-level parity for model-visible text and structured tool results."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from mcp import types as mcp_types
from support.rob2 import (
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.interfaces.mcp.server import mcp


def _wire_call(
    workspace: Path, tool: str, arguments: dict[str, object]
) -> mcp_types.CallToolResult:
    async def invoke() -> mcp_types.CallToolResult:
        previous_workspace = os.environ.get("ROB2_WORKSPACE")
        try:
            os.environ["ROB2_WORKSPACE"] = str(workspace)
            async with Client(mcp) as client:
                return await client.call_tool(tool, arguments)
        finally:
            if previous_workspace is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous_workspace

    return asyncio.run(invoke())


def _assert_text_structured_parity(result: mcp_types.CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    text_blocks = [item for item in result.content if isinstance(item, mcp_types.TextContent)]
    assert len(text_blocks) == 1
    parsed = json.loads(text_blocks[0].text)
    assert parsed == result.structured_content
    return parsed


def test_text_only_and_structured_consumers_receive_the_same_workflow_results(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    assert (
        _assert_text_structured_parity(_wire_call(workspace, "get_status", {}))["head"][
            "next_action"
        ]["operation"]
        == "prepare_batch"
    )

    evidence = _prepared_evidence(workspace)
    search = _assert_text_structured_parity(
        _wire_call(
            workspace,
            "search_sources",
            {"trial_id": "trial", "query": "requested outcome"},
        )
    )
    assert search["data"]["hits"][0]["passage_ref"].startswith("eh_")

    conflict = _assert_text_structured_parity(
        _wire_call(
            workspace,
            "prepare_batch",
            {"requested_outcome": "different outcome", "expected_revision": 0},
        )
    )
    assert conflict["outcome"] == "conflict"

    _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(evidence)]),
    )
    _review(workspace)
    context = _assert_text_structured_parity(_wire_call(workspace, "get_domain_context", {}))
    assert context["data"]["trial_id"] == "trial"
    revision = int(context["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:randomization", revision, evidence=evidence)
    duplicated = dict(draft["answers"][0]["bases"][0])
    draft["answers"][0]["bases"].append(duplicated)
    repair = _assert_text_structured_parity(_wire_call(workspace, "save_domain_judgment", draft))
    assert repair["outcome"] == "repair"
    assert repair["repairs"][0]["code"] == "duplicate_answer_basis"
