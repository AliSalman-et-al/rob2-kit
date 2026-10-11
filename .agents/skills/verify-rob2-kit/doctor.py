"""Read-only check that this checkout's rob2 server is worth driving.

usage: uv run python .agents/skills/verify-rob2-kit/doctor.py
Exit 0 means every check passed; each failing check prints FAIL with its reason.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def main() -> int:
    failures = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")

    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    installed = importlib.metadata.version("rob2-kit")
    check(
        "installed package", installed == version, f"{installed} (pyproject {version}; run uv sync)"
    )

    cli = subprocess.run(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    check("rob2 CLI", cli.returncode == 0, "starts" if cli.returncode == 0 else cli.stderr[-300:])

    expected = {
        tool["name"]
        for tool in json.loads(
            (REPO / "docs/release/public-contract.json").read_text(encoding="utf-8")
        )["tools"]
    }
    for entrypoint in ("mcp", "mcp-codex"):
        tools = asyncio.run(_list_tools(entrypoint))
        check(
            f"rob2 {entrypoint} over stdio",
            tools == expected,
            f"{len(tools)} tools" + ("" if tools == expected else f"; differs: {tools ^ expected}"),
        )

    plugin = {
        path: json.loads((REPO / path).read_text(encoding="utf-8"))["version"]
        for path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
    }
    check("plugin versions", set(plugin.values()) == {version}, json.dumps(plugin))
    return 1 if failures else 0


async def _list_tools(entrypoint: str) -> set[str]:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    with tempfile.TemporaryDirectory(prefix="rob2-doctor-") as workspace:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "rob2_kit.interfaces.cli.app", "--workspace", workspace, entrypoint],
            env={**os.environ, "FASTMCP_LOG_LEVEL": "WARNING"},
        )
        async with Client(transport) as client:
            return {tool.name for tool in await client.list_tools()}


if __name__ == "__main__":
    raise SystemExit(main())
