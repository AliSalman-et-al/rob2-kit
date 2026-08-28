"""MCP Proposal approval elicitation behavior."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp.client import Client
from fastmcp.client.elicitation import ElicitResult
from support.rob2 import _call, _proposal_args, _result, _workspace

from rob2_kit.interfaces.mcp import server
from rob2_kit.interfaces.mcp.server import mcp


def _pending_workspace(tmp_path: Path) -> Path:
    workspace = _workspace(tmp_path)
    prepared = _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(evidence)]),
    )
    assert prepared["outcome"] == "success"
    assert saved["outcome"] == "review_required"
    return workspace


def _approval_call(
    workspace: Path,
    response: Any | None = None,
    *,
    with_handler: bool = True,
    messages: list[str] | None = None,
) -> dict[str, Any]:
    async def elicit(
        message: str, _response_type: type[Any] | None, _params: Any, _context: Any
    ) -> Any:
        assert _response_type is not None
        if messages is not None:
            messages.append(message)
        return response

    async def run() -> dict[str, Any]:
        previous_workspace = os.environ.get("ROB2_WORKSPACE")
        try:
            os.environ["ROB2_WORKSPACE"] = str(workspace)
            kwargs = {"elicitation_handler": elicit} if with_handler else {}
            async with Client(mcp, **kwargs) as client:
                result = await client.call_tool("request_proposal_approval", {})
                return dict(result.structured_content or {})
        finally:
            if previous_workspace is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous_workspace

    return asyncio.run(run())


def test_request_proposal_approval_accepts_exact_review(tmp_path: Path) -> None:
    workspace = _pending_workspace(tmp_path)
    review_reference = _call(workspace, "get_status", {})["head"]["next_action"]["reference"]
    messages: list[str] = []

    result = _approval_call(workspace, {"approved": True}, messages=messages)

    assert result["outcome"] == "success"
    assert result["data"]["approved"] is True
    assert review_reference in messages[0]
    assert result["data"]["acknowledgment_record"]["review_identity"] == review_reference
    assert result["data"]["acknowledgment_record"]["caller"] == "researcher"
    assert result["data"]["acknowledgment_record"]["method"] == "mcp_elicitation"


@pytest.mark.parametrize(
    ("response", "code"),
    (
        ({"approved": False}, "proposal_approval_declined"),
        (ElicitResult(action="decline"), "proposal_approval_declined"),
        (ElicitResult(action="cancel"), "proposal_approval_cancelled"),
    ),
)
def test_request_proposal_approval_preserves_unaccepted_review(
    tmp_path: Path, response: Any, code: str
) -> None:
    workspace = _pending_workspace(tmp_path)

    result = _approval_call(workspace, response)

    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == code
    assert result["head"]["next_action"]["operation"] == "researcher_review"


def test_request_proposal_approval_reports_unsupported_client(tmp_path: Path) -> None:
    workspace = _pending_workspace(tmp_path)

    result = _approval_call(workspace, with_handler=False)

    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "proposal_approval_unsupported"
    assert result["head"]["next_action"]["operation"] == "researcher_review"


def test_request_proposal_approval_requires_pending_review(tmp_path: Path) -> None:
    result = _approval_call(_workspace(tmp_path), with_handler=False)

    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "proposal_review_not_pending"


def test_request_proposal_approval_replays_existing_acknowledgment(tmp_path: Path) -> None:
    workspace = _pending_workspace(tmp_path)
    first = _approval_call(workspace, {"approved": True})
    second = _approval_call(workspace, with_handler=False)

    assert first["outcome"] == "success"
    assert second["outcome"] == "success"
    assert second["data"]["retry"] is True
    assert second["data"]["acknowledgment"] == first["data"]["acknowledgment"]


def test_request_proposal_approval_reports_stale_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _pending_workspace(tmp_path)

    def stale(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("the exact displayed Review record must be acknowledged")

    monkeypatch.setattr(server, "_approve_review", stale)
    result = _approval_call(workspace, {"approved": True})

    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "proposal_approval_stale"


def test_request_proposal_approval_has_no_caller_arguments() -> None:
    async def inspect() -> dict[str, Any]:
        async with Client(mcp) as client:
            tool = next(
                item
                for item in await client.list_tools()
                if item.name == "request_proposal_approval"
            )
            return dict(tool.inputSchema)

    schema = asyncio.run(inspect())

    assert schema["properties"] == {}
    assert schema.get("required", []) == []
