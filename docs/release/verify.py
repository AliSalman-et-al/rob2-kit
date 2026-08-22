"""Fail-closed verification of the public wheel contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "release" / "public-contract.json"


def _load_contract() -> dict[str, Any]:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if set(value) != {"tools", "resources", "resource_templates", "skill_pointers", "examples"}:
        raise ValueError("public contract shape differs")
    expected_order = [
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
    if [item["name"] for item in value["tools"]] != expected_order:
        raise ValueError("public tool order differs")
    if value["resources"] != ["rob2://current-batch"] or value["resource_templates"] != [
        "rob2://detail/{kind}/{identity}",
        "rob2://registry/{trial_id}",
        "rob2://render/{identity}",
    ]:
        raise ValueError("public resource catalog differs")
    return value


def _assert_generated(contract: dict[str, Any]) -> None:
    from rob2_kit.contract_manifest import _manifest

    generated = asyncio.run(_manifest())
    if generated != contract:
        raise ValueError("checked public contract differs from generated runtime contract")


def _schema_hash(schema: dict[str, Any]) -> str:
    text = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


async def _verify_client(client: Client, contract: dict[str, Any]) -> None:
    tools = await client.list_tools()
    if [tool.name for tool in tools] != [item["name"] for item in contract["tools"]]:
        raise ValueError("MCP tool catalog differs")
    for tool, expected in zip(tools, contract["tools"], strict=True):
        annotations = tool.annotations
        if annotations is None or annotations.readOnlyHint != expected["read_only"]:
            raise ValueError(f"MCP annotations differ: {tool.name}")
        if bool(annotations.openWorldHint) != expected["open_world"]:
            raise ValueError(f"MCP open-world annotation differs: {tool.name}")
        if annotations.destructiveHint:
            raise ValueError(f"MCP tool is destructively advertised: {tool.name}")
        if _schema_hash(tool.inputSchema) != expected["schema_sha256"]:
            raise ValueError(f"MCP schema hash differs: {tool.name}")
    resources = [str(item.uri) for item in await client.list_resources()]
    templates = [str(item.uriTemplate) for item in await client.list_resource_templates()]
    if resources != contract["resources"] or templates != contract["resource_templates"]:
        raise ValueError("MCP resource catalog differs")
    current = await client.read_resource("rob2://current-batch")
    if len(current) != 1 or not getattr(current[0], "text", None):
        raise ValueError("current-batch resource is unreadable")


def _verify_wheel_archive(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            "\\" in name or ".." in name.split("/") for name in names
        ):
            raise ValueError("wheel archive has ambiguous members")
        entries = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entries) != 1:
            raise ValueError("wheel entry point is unavailable")
        entry_points = archive.read(entries[0]).decode("utf-8").replace("\r\n", "\n")
        if entry_points != "[console_scripts]\nrob2 = rob2_kit.interfaces.cli.app:main\n":
            raise ValueError("wheel entry point differs")
        for host in ("codex.json", "claude-code.json"):
            member = f"rob2_kit/hosts/{host}"
            payload = json.loads(archive.read(member))
            if payload.get("mcp_command") != "rob2 mcp":
                raise ValueError(f"wheel host command differs: {host}")


def _installed_python(wheel: Path, directory: Path) -> Path:
    venv = directory / "venv"
    subprocess.run(["uv", "venv", str(venv)], cwd=ROOT, check=True, capture_output=True)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return python


def verify(wheel: Path | None = None) -> None:
    contract = _load_contract()
    _assert_generated(contract)
    if wheel is None:
        from rob2_kit.interfaces.mcp.server import mcp

        async def local() -> None:
            async with Client(mcp) as client:
                await _verify_client(client, contract)

        asyncio.run(local())
        return
    _verify_wheel_archive(wheel)
    with tempfile.TemporaryDirectory(prefix="rob2-release-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        python = _installed_python(wheel, Path(temporary))
        environment = os.environ | {"ROB2_WORKSPACE": str(workspace)}

        async def stdio() -> None:
            transport = StdioTransport(
                command=str(python),
                args=["-m", "rob2_kit.interfaces.cli.app", "mcp"],
                env=environment,
            )
            async with Client(transport) as client:
                await _verify_client(client, contract)

        asyncio.run(stdio())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    verify(parser.parse_args().wheel)
