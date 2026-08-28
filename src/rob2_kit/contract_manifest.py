"""Generate the checked public contract from the typed runtime adapter."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

from fastmcp import Client
from pydantic import BaseModel, ConfigDict


class ContractExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    resource: str


EXAMPLES = (ContractExample(name="current_status", resource="rob2://current-batch"),)


def _schema_hash(schema: dict[str, object]) -> str:
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def _manifest() -> dict[str, object]:
    from .interfaces.mcp.server import mcp

    async with Client(mcp) as client:
        tools = await client.list_tools()
        if any(tool.outputSchema is None for tool in tools):
            raise ValueError("public MCP tool is missing outputSchema")
        resource_items = await client.list_resources()
        if any(not (item.description or "").strip() for item in resource_items):
            raise ValueError("public MCP resource is missing description")
        resources = [str(item.uri) for item in resource_items]
        templates = [str(item.uriTemplate) for item in await client.list_resource_templates()]
    hosts = Path(__file__).parent / "hosts"
    host = json.loads((hosts / "codex.json").read_text(encoding="utf-8"))
    return {
        "contract_version": "0.3.0",
        "tools": [
            {
                "name": tool.name,
                "title": (tool.title or "").strip(),
                "description": (tool.description or "").strip(),
                "read_only": bool(tool.annotations and tool.annotations.readOnlyHint),
                "destructive": bool(tool.annotations and tool.annotations.destructiveHint),
                "idempotent": bool(tool.annotations and tool.annotations.idempotentHint),
                "open_world": tool.annotations.openWorldHint if tool.annotations else None,
                "schema_sha256": _schema_hash(tool.inputSchema),
                "output_schema_sha256": _schema_hash(cast(dict[str, object], tool.outputSchema)),
            }
            for tool in tools
        ],
        "resources": resources,
        "resource_descriptions": {
            str(item.uri): (item.description or "").strip() for item in resource_items
        },
        "resource_templates": templates,
        "skill_pointers": host["skills"],
        "examples": [example.model_dump(mode="json") for example in EXAMPLES],
    }


def generate(output: str | Path) -> dict[str, object]:
    manifest = asyncio.run(_manifest())
    path = Path(output)
    path.write_text(
        json.dumps(manifest, sort_keys=False, separators=(",\n", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)
