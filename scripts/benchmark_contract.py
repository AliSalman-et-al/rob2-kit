"""Shared benchmark metadata derived from the maintained public contract."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

PUBLIC_CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "release" / "public-contract.json"
TOOL_INVENTORY_VERSION = "rob2-kit.mcp-tools.v1"
PUBLIC_CONTRACT_SOURCE = "docs/release/public-contract.json"


def _load_public_contract() -> dict[str, object]:
    try:
        contract = json.loads(PUBLIC_CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"public MCP contract is unreadable: {PUBLIC_CONTRACT}") from error
    if not isinstance(contract, dict):
        raise RuntimeError(f"public MCP contract is not an object: {PUBLIC_CONTRACT}")
    return contract


def public_contract_version() -> str:
    """Return the advertised release contract version."""

    contract = _load_public_contract()
    version = contract.get("contract_version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"public MCP contract has no version: {PUBLIC_CONTRACT}")
    return version.strip()


def public_tool_inventory() -> tuple[str, ...]:
    """Return the exact public MCP tool names advertised by the release contract."""

    tools = _load_public_contract().get("tools")
    if not isinstance(tools, list) or not tools:
        raise RuntimeError(f"public MCP contract has no tool inventory: {PUBLIC_CONTRACT}")
    names: list[str] = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(f"public MCP contract contains an invalid tool: {PUBLIC_CONTRACT}")
        names.append(name.strip())
    if len(set(names)) != len(names):
        raise RuntimeError(f"public MCP contract contains duplicate tools: {PUBLIC_CONTRACT}")
    return tuple(names)


def public_contract_sha256() -> str:
    """Return the frozen contract bytes used to derive the public inventory."""

    try:
        payload = PUBLIC_CONTRACT.read_bytes()
    except OSError as error:
        raise RuntimeError(f"public MCP contract is unreadable: {PUBLIC_CONTRACT}") from error
    return hashlib.sha256(payload).hexdigest()


def tool_inventory_provenance() -> dict[str, object]:
    """Return the inventory plus enough provenance to replay its launch binding."""

    return {
        "names": list(public_tool_inventory()),
        "version": TOOL_INVENTORY_VERSION,
        "source": PUBLIC_CONTRACT_SOURCE,
        "contract_version": public_contract_version(),
        "contract_sha256": public_contract_sha256(),
    }


def trace_has_rob2_runtime_evidence(path: Path) -> bool:
    """Return whether a trace proves that the rob2 MCP surface was callable."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "rob2"
            and item.get("status") == "completed"
            and item.get("error") is None
            and item.get("result") is not None
        ):
            return True
    return False


def artifact_manifest_identity(path: Path) -> str:
    """Read the content-addressed identity recorded inside a verified bundle."""

    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ValueError(f"artifact manifest is unreadable: {path}") from error
    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    if not isinstance(identity, str) or not identity:
        raise ValueError(f"artifact manifest has no identity: {path}")
    return identity
