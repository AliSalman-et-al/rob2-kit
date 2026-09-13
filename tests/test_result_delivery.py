"""Wire-level delivery of complete structured tool results."""

from __future__ import annotations

import asyncio
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
    _read_required_main_reports,
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


def _assert_structured_result(result: mcp_types.CallToolResult) -> dict[str, Any]:
    assert result.content == []
    assert isinstance(result.structured_content, dict)
    return dict(result.structured_content)


def test_structured_consumer_receives_the_complete_workflow_result(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    assert (
        _assert_structured_result(_wire_call(workspace, "get_status", {}))["head"]["next_action"][
            "operation"
        ]
        == "prepare_batch"
    )

    evidence = _prepared_evidence(workspace)
    search = _assert_structured_result(
        _wire_call(
            workspace,
            "search_sources",
            {"trial_id": "trial", "query": "requested outcome", "mode": "any"},
        )
    )
    assert search["data"]["hits"][0]["passage_ref"].startswith("eh_")

    conflict = _assert_structured_result(
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
    _read_required_main_reports(workspace)
    context = _assert_structured_result(_wire_call(workspace, "get_domain_context", {}))
    while (
        isinstance(context.get("data"), dict)
        and isinstance(context["data"].get("context_page"), dict)
        and context["data"]["context_page"].get("next_cursor") is not None
    ):
        cursor = context["data"]["context_page"]["next_cursor"]
        context = _assert_structured_result(
            _wire_call(workspace, "get_domain_context", {"cursor": cursor})
        )
    assert context["data"]["trial_id"] == "trial"
    revision = int(context["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:randomization", revision, evidence=evidence)
    duplicated = dict(draft["answers"][0]["bases"][0])
    draft["answers"][0]["bases"].append(duplicated)
    repair = _assert_structured_result(_wire_call(workspace, "save_domain_judgment", draft))
    assert repair["outcome"] == "repair"
    assert repair["repairs"][0]["code"] == "duplicate_answer_basis"
