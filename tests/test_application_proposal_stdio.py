from __future__ import annotations

import asyncio
from typing import Any, cast

from fastmcp import Client

from rob2_kit.interfaces.mcp.server import mcp


def test_proposal_tools_expose_only_root_model_inputs() -> None:
    async def inspect() -> dict[str, object]:
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        assert {"save_proposal", "approve_batch"} <= set(tools)
        return {
            "save": tools["save_proposal"].inputSchema,
            "approve": tools["approve_batch"].inputSchema,
            "finish": tools["finish_trial"].inputSchema,
        }

    schemas = asyncio.run(inspect())
    typed_schemas = cast(dict[str, dict[str, Any]], schemas)
    rendered = str(schemas)
    assert "actor" not in rendered
    assert "observed_at" not in rendered
    assert "researcher" not in rendered
    assert "transition" in rendered
    for name in ("approve", "finish"):
        schema = typed_schemas[name]
        assert isinstance(schema, dict)
        assert schema["required"] == ["transition", "acknowledgment"]
        assert "request" not in schema["properties"]
    proposal = typed_schemas["save"]
    assert isinstance(proposal, dict)
    proposal = proposal["properties"]["proposal"]
    results = proposal["properties"]["results"]["items"]
    assert "compatibility" not in results["properties"]
    reported_forms = results["properties"]["reported"]["oneOf"]
    assert all("form" in item["required"] for item in reported_forms)
