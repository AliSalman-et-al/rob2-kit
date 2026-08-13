"""The model-free FastMCP boundary."""

import os
import re
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict

from rob2_kit.registry import RegistryNotCaptured, read_captured_registry


class CurrentBatch(BaseModel):
    """The initial state before batch ingestion exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_batch: Literal[None] = None


mcp = FastMCP("rob2-kit")


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    """Return the active batch, if one exists."""
    return CurrentBatch().model_dump_json()


@mcp.resource("rob2://registry/{trial_id}")
def registry_record(trial_id: str) -> str:
    """Read a validated captured ClinicalTrials.gov record for one Trial."""
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", trial_id) is None:
        raise ValueError("invalid trial identifier")
    workspace = os.environ.get("ROB2_WORKSPACE")
    if not workspace:
        return RegistryNotCaptured(trial_id=trial_id, status="not_captured").model_dump_json()
    return read_captured_registry(workspace, trial_id).model_dump_json()


def main() -> None:
    """Run the stdio MCP server."""
    mcp.run()
