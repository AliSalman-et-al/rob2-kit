"""Official Python MCP SDK adapter over the application gateway."""

from __future__ import annotations

from typing import Any

from rob2_kit.application.gateway import (
    MUTATION_TOOLS,
    STATIC_TOOL_NAMES,
    ApplicationGateway,
)


def registered_tool_names() -> tuple[str, ...]:
    return STATIC_TOOL_NAMES


def create_server() -> Any:
    from mcp.server import MCPServer

    server = MCPServer("rob2-kit")
    gateway = ApplicationGateway()

    def dispatch(
        tool_name: str,
        project_id: str,
        arguments: dict[str, Any] | None = None,
        mutation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return gateway.call(
            tool_name,
            project_id,
            arguments=arguments,
            mutation_context=mutation_context,
        ).model_dump(mode="json")

    for tool_name in STATIC_TOOL_NAMES:
        if tool_name == "initialize_project":
            initialize_project = _initialization_tool(gateway)
            initialize_project.__name__ = tool_name
            server.tool(name=tool_name)(initialize_project)
        elif tool_name in MUTATION_TOOLS:
            tool = _mutation_tool(dispatch, tool_name)
            tool.__name__ = tool_name
            server.tool(name=tool_name)(tool)
        else:
            tool = _query_tool(dispatch, tool_name)
            tool.__name__ = tool_name
            server.tool(name=tool_name)(tool)
    return server


def _initialization_tool(gateway: ApplicationGateway) -> Any:
    def initialize_project(
        project_root: str, authorized: bool = False
    ) -> dict[str, Any]:
        """Authorize and initialize one confined project root."""
        return gateway.initialize_project(
            __import__("pathlib").Path(project_root), authorized=authorized
        ).model_dump(mode="json")

    return initialize_project


def _query_tool(dispatch: Any, tool_name: str) -> Any:
    def tool(
        project_id: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one bounded host-neutral operation."""
        return dispatch(tool_name, project_id, arguments, None)

    return tool


def _mutation_tool(dispatch: Any, tool_name: str) -> Any:
    def tool(
        project_id: str,
        arguments: dict[str, Any],
        mutation_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Commit one typed, engine-authorized preparation submission."""
        return dispatch(tool_name, project_id, arguments, mutation_context)

    return tool


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
