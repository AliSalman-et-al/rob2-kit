from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from rob2_kit.interfaces.mcp.server import mcp


def test_public_catalog_is_exact_and_annotated() -> None:
    async def discover():
        async with Client(mcp) as client:
            return (
                await client.list_tools(),
                await client.list_resources(),
                await client.list_resource_templates(),
            )

    tools, resources, templates = asyncio.run(discover())
    assert [tool.name for tool in tools] == [
        "preflight_sources",
        "inspect_candidate_sources",
        "save_intake_plan",
        "capture_batch",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "save_proposal",
        "approve_batch",
        "validate_domain_judgment",
        "commit_domain_judgment",
        "prepare_trial_finish",
        "finish_trial",
        "finalize_batch",
        "read_record",
    ]
    assert [str(item.uri) for item in resources] == ["rob2://current-batch"]
    assert [str(item.uriTemplate) for item in templates] == [
        "rob2://detail/{kind}/{identity}",
        "rob2://registry/{trial_id}",
        "rob2://render/{identity}",
    ]
    read_only = {
        "inspect_candidate_sources",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "read_record",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is (tool.name in read_only)
        assert not tool.annotations.destructiveHint
        assert bool(tool.annotations.openWorldHint) is (tool.name == "preflight_sources")


def test_current_batch_is_a_typed_json_resource(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def read() -> str:
        async with Client(mcp) as client:
            return (await client.read_resource("rob2://current-batch"))[0].text

    assert json.loads(asyncio.run(read()))["phase"] == "empty"
