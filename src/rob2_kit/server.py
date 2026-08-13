"""The initial model-free FastMCP boundary."""

from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict


class CurrentBatch(BaseModel):
    """The initial state before batch ingestion exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_batch: Literal[None] = None


mcp = FastMCP("rob2-kit")


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    """Return the active batch, if one exists."""
    return CurrentBatch().model_dump_json()


def main() -> None:
    """Run the stdio MCP server."""
    mcp.run()
