"""Opt-in stdio entrypoint for Codex CLI 0.159 structured-content image precedence.

The ordinary server stays unchanged. Only render_page advertises an unstructured
MCP result here: its already-validated JSON receipt remains the text block beside
unchanged PNG pixels. Codex's structured-content shortcut otherwise drops pixels.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp.types import CallToolRequestParams, ListToolsRequest


class CodexImageContent(Middleware):
    async def on_list_tools(
        self,
        context: MiddlewareContext[ListToolsRequest],
        call_next: CallNext[ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [
            tool.model_copy(update={"output_schema": None}) if tool.name == "render_page" else tool
            for tool in tools
        ]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        if context.message.name != "render_page" or result.is_error:
            return result
        if not any(block.type == "image" for block in result.content):
            return result
        return ToolResult(content=result.content, meta=result.meta, is_error=result.is_error)


def main() -> None:
    from rob2_kit.interfaces.mcp.server import mcp

    mcp.add_middleware(CodexImageContent())
    mcp.run()


if __name__ == "__main__":
    main()
