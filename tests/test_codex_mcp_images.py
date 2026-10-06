from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, TextContent

from rob2_kit.interfaces.mcp.contracts import output_schema, validate_output
from scripts.codex_mcp import CodexImageContent

CASE = Path(__file__).parents[1] / "docs/archive/evaluation/2026-10-03-gupta-full-validation"


def retained_render() -> dict:
    for line in (CASE / "turn-2.jsonl").read_text().splitlines():
        row = json.loads(line)
        item = row.get("item", {})
        if row.get("type") == "item.completed" and item.get("tool") == "render_page":
            return item["result"]
    raise AssertionError("retained render absent")


def cli_0159_model_body(result: dict):
    """Replay the documented rust-v0.159.0 CallToolResult conversion branch."""
    if result.get("structuredContent") is not None:
        return json.dumps(result["structuredContent"])
    return result["content"]


@pytest.mark.parametrize("compat", [False, True])
def test_actual_render_receipt_image_replay_and_normal_client_compatibility(compat) -> None:
    asyncio.run(_replay(compat))


async def _replay(compat) -> None:
    raw = retained_render()
    receipt = raw["structured_content"]
    validate_output("render_page", receipt)
    image = next(c for c in raw["content"] if c["type"] == "image")
    pixels = base64.b64decode(image["data"], validate=True)
    mcp = FastMCP("offline-image-replay")
    original_schema = output_schema("render_page")

    @mcp.tool(output_schema=original_schema)
    def render_page(inline: bool = True) -> ToolResult:
        content = [TextContent(type="text", text=json.dumps(receipt))]
        if inline:
            content.append(
                ImageContent.model_validate(
                    {"type": "image", "data": image["data"], "mimeType": "image/png"}
                )
            )
        return ToolResult(content=content, structured_content=receipt)

    @mcp.tool()
    def get_status() -> dict:
        return {"outcome": "success", "phase": "assessment"}

    if compat:
        mcp.add_middleware(CodexImageContent())
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert (tools["render_page"].output_schema is None) == compat
        rendered = await client.call_tool("render_page")
        wire = {
            "content": [
                block.model_dump(by_alias=True, exclude_none=True) for block in rendered.content
            ],
            "structuredContent": rendered.structured_content,
        }
        blocks = wire["content"]
        delivered = next(c for c in blocks if c["type"] == "image")
        assert base64.b64decode(delivered["data"]) == pixels
        assert json.loads(blocks[0]["text"]) == receipt
        if compat:
            assert rendered.structured_content is None
            schema_text = json.loads(blocks[-1]["text"])
            assert schema_text == {"tool": "render_page", "receipt_schema": original_schema}
            assert tools["render_page"].meta["rob2_receipt_schema"] == original_schema
            assert any(c["type"] == "image" for c in cli_0159_model_body(wire))
        else:
            assert rendered.structured_content == receipt
            assert isinstance(cli_0159_model_body(wire), str)
        status = await client.call_tool("get_status")
        assert status.structured_content == {"outcome": "success", "phase": "assessment"}
        metadata = await client.call_tool("render_page", {"inline": False})
        assert metadata.structured_content == receipt
        assert not any(c.type == "image" for c in metadata.content)
    # Middleware changes advertised copies, not the normal tool or its schema.
    original = await mcp.get_tool("render_page")
    assert original is not None
    assert original.output_schema == original_schema


def test_codex_compat_preserves_error_flags_even_with_image_content() -> None:
    from fastmcp.server.middleware import MiddlewareContext
    from mcp.types import CallToolRequestParams

    async def replay():
        result = ToolResult(
            content=[
                ImageContent.model_validate(
                    {"type": "image", "data": "pixels", "mimeType": "image/png"}
                )
            ],
            structured_content={"outcome": "error"},
            is_error=True,
        )

        async def next_call(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            return result

        context = MiddlewareContext(message=CallToolRequestParams(name="render_page"))
        assert await CodexImageContent().on_call_tool(context, next_call) is result

    asyncio.run(replay())
