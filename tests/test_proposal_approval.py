"""MCP Proposal approval elicitation behavior."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastmcp import Context
from fastmcp.client import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.tools import InputRequiredToolResult, ToolResult
from mcp import types as mcp_types
from support.rob2 import (
    _call,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _workspace,
)

from rob2_kit.interfaces.mcp import server
from rob2_kit.interfaces.mcp.server import mcp


def _pending_workspace(tmp_path: Path) -> Path:
    workspace = _workspace(tmp_path)
    prepared = _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
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
    elicitation_params: list[Any] | None = None,
) -> dict[str, Any]:
    async def elicit(
        message: str, _response_type: type[Any] | None, _params: Any, _context: Any
    ) -> Any:
        assert _response_type is not None
        if messages is not None:
            messages.append(message)
        if elicitation_params is not None:
            elicitation_params.append(_params)
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


class _ModernContext:
    def __init__(
        self,
        *,
        input_responses: mcp_types.InputResponses | None = None,
        request_state: str | None = None,
    ) -> None:
        self.session = SimpleNamespace(client_capabilities=SimpleNamespace(elicitation=object()))
        self.input_responses = input_responses
        self.request_state = request_state

    @staticmethod
    def _is_modern_protocol() -> bool:
        return True


def _modern_approval_call(
    workspace: Path,
    *,
    input_responses: mcp_types.InputResponses | None = None,
    request_state: str | None = None,
) -> ToolResult:
    previous_workspace = os.environ.get("ROB2_WORKSPACE")
    try:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        context = _ModernContext(
            input_responses=input_responses,
            request_state=request_state,
        )
        return asyncio.run(server.request_proposal_approval(cast(Context, context)))
    finally:
        if previous_workspace is None:
            os.environ.pop("ROB2_WORKSPACE", None)
        else:
            os.environ["ROB2_WORKSPACE"] = previous_workspace


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


def test_modern_proposal_approval_binds_input_request_to_exact_review(
    tmp_path: Path,
) -> None:
    workspace = _pending_workspace(tmp_path)
    review_reference = _call(workspace, "get_status", {})["head"]["next_action"]["reference"]

    result = _modern_approval_call(workspace)

    assert isinstance(result, InputRequiredToolResult)
    assert result.input_required.request_state == review_reference
    assert result.input_required.input_requests is not None
    request = result.input_required.input_requests["proposal_review"]
    assert isinstance(request, mcp_types.ElicitRequest)
    assert review_reference in request.params.message


def test_modern_proposal_approval_emits_codex_compatible_schema(tmp_path: Path) -> None:
    workspace = _pending_workspace(tmp_path)

    result = _modern_approval_call(workspace)

    assert isinstance(result, InputRequiredToolResult)
    assert result.input_required.input_requests is not None
    request = result.input_required.input_requests["proposal_review"]
    assert isinstance(request, mcp_types.ElicitRequest)
    assert isinstance(request.params, mcp_types.ElicitRequestFormParams)
    schema = request.params.requested_schema
    assert set(schema) == {"type", "properties", "required"}
    assert schema["type"] == "object"
    assert schema["properties"]["approved"]["type"] == "boolean"
    assert schema["properties"]["approved"]["title"] == "Approve Proposal Review"
    assert schema["properties"]["approved"]["description"]
    assert schema["required"] == ["approved"]


def test_legacy_proposal_approval_emits_codex_compatible_schema(tmp_path: Path) -> None:
    workspace = _pending_workspace(tmp_path)
    params: list[Any] = []

    _approval_call(
        workspace,
        ElicitResult(action="decline"),
        elicitation_params=params,
    )

    assert len(params) == 1
    schema = params[0].requested_schema
    assert set(schema) == {"type", "properties", "required"}
    assert schema["type"] == "object"
    assert schema["properties"]["approved"]["type"] == "boolean"
    assert schema["properties"]["approved"]["title"] == "Approve Proposal Review"
    assert schema["properties"]["approved"]["description"]
    assert schema["required"] == ["approved"]


def test_modern_proposal_approval_accepts_only_bound_researcher_response(
    tmp_path: Path,
) -> None:
    workspace = _pending_workspace(tmp_path)
    review_reference = _call(workspace, "get_status", {})["head"]["next_action"]["reference"]
    response = mcp_types.ElicitResult(action="accept", content={"approved": True})

    result = _modern_approval_call(
        workspace,
        input_responses={"proposal_review": response},
        request_state=review_reference,
    )

    assert result.structured_content is not None
    assert result.structured_content["outcome"] == "success"
    acknowledgment = result.structured_content["data"]["acknowledgment_record"]
    assert acknowledgment["review_identity"] == review_reference
    assert acknowledgment["method"] == "mcp_elicitation"


@pytest.mark.parametrize(
    ("request_state", "response", "code"),
    (
        (
            "sha256:" + "0" * 64,
            mcp_types.ElicitResult(action="accept", content={"approved": True}),
            "proposal_approval_stale",
        ),
        (
            None,
            mcp_types.ElicitResult(action="decline"),
            "proposal_approval_declined",
        ),
        (
            None,
            mcp_types.ElicitResult(action="cancel"),
            "proposal_approval_cancelled",
        ),
    ),
)
def test_modern_proposal_approval_preserves_stale_declined_and_cancelled_reviews(
    tmp_path: Path,
    request_state: str | None,
    response: mcp_types.ElicitResult,
    code: str,
) -> None:
    workspace = _pending_workspace(tmp_path)
    review_reference = _call(workspace, "get_status", {})["head"]["next_action"]["reference"]

    result = _modern_approval_call(
        workspace,
        input_responses={"proposal_review": response},
        request_state=request_state or review_reference,
    )

    assert result.structured_content is not None
    assert result.structured_content["outcome"] == "condition"
    assert result.structured_content["condition"]["code"] == code
    current_reference = _call(workspace, "get_status", {})["head"]["next_action"]["reference"]
    assert current_reference == review_reference


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
            return dict(tool.input_schema)

    schema = asyncio.run(inspect())

    assert schema["properties"] == {}
    assert schema.get("required", []) == []
