"""Project-local Codex and Claude Harness installation and diagnostics."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from rob2_kit.release import (
    CANONICAL_SKILL_NAMES,
    SUPPORTED_HOSTS,
    ReleaseLock,
    load_release_lock,
    verify_host_adapters,
    verify_mcp_launchability,
)
from rob2_kit.storage import ArtifactStore, WorkflowLedger
from rob2_kit.storage.ledger import LedgerError

_MCP_SERVER_NAME = "rob2-kit"
_BOOTSTRAP_LOCK = "rob2.lock"
_REFERENCE_FILENAMES = (
    "HARNESS-WORKFLOW.md",
    "EVIDENCE-SEARCH.md",
    "SIGNALING-QUESTIONS.md",
)
_HOST_SKILL_ROOTS = (("codex", ".codex/skills"), ("claude", ".claude/skills"))


class HarnessBootstrapError(ValueError):
    """A project-local Harness file would need unsafe replacement."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"{detail} Recovery: preserve the existing configuration, remove or "
            f"reconcile its {_MCP_SERVER_NAME!r} entry, then rerun rob2 bootstrap."
        )


def bootstrap_project(project_root: Path) -> dict[str, Any]:
    """Install the locked adapters without changing unrelated host settings."""

    root = project_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    release_root = _release_root()
    lock = load_release_lock(release_root)
    verify_host_adapters(release_root)

    codex_path = root / ".codex" / "config.toml"
    claude_path = root / ".mcp.json"
    codex_config = _read_toml(codex_path)
    claude_config = _read_json_object(claude_path)
    expected_server = _server_config(lock)
    codex_servers = codex_config.get("mcp_servers", {})
    if not isinstance(codex_servers, dict):
        raise HarnessBootstrapError(f"{codex_path} has a non-table mcp_servers value.")
    _validate_server_entry(codex_servers.get(_MCP_SERVER_NAME), expected_server, codex_path)
    claude_servers = claude_config.get("mcpServers", {})
    if not isinstance(claude_servers, dict):
        raise HarnessBootstrapError(f"{claude_path} has a non-object mcpServers value.")
    _validate_server_entry(claude_servers.get(_MCP_SERVER_NAME), expected_server, claude_path)
    _validate_adapter_targets(root, release_root)

    changed = False
    changed |= _install_adapter_trees(root, release_root)
    changed |= _install_skills(root, release_root)
    changed |= _install_references(root, release_root)
    changed |= _install_bootstrap_lock(root, release_root)
    changed |= _install_codex_server(codex_path, codex_config, expected_server)
    changed |= _install_claude_server(claude_path, claude_config, expected_server)

    return {
        "status": "installed" if changed else "already_installed",
        "hosts": list(sorted(SUPPORTED_HOSTS)),
        "project_root": str(root),
        "launcher": lock.launcher,
        "recovery": "Run rob2 doctor to verify this locked project-local Harness install.",
    }


def doctor_project(project_root: Path) -> dict[str, Any]:
    """Return actionable, deterministic checks for the lean-v1 Harness journey."""

    root = project_root.resolve()
    release_root = _release_root()
    checks = {
        "execution_contract": _check_execution_contract(root, release_root),
        "canonical_skills": _check_canonical_skills(root, release_root),
        "host_adapters": _check_host_adapters(root, release_root),
        "mcp_launchability": _check_mcp_launchability(root),
        "project_state_schema": _check_project_state(root),
    }
    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def _release_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / _BOOTSTRAP_LOCK).is_file():
        return package_root
    return package_root.parents[1]


def _server_config(lock: ReleaseLock) -> dict[str, Any]:
    parts = lock.launcher.split()
    if not parts or parts[0] != "uvx":
        raise HarnessBootstrapError("The locked MCP launcher is not an isolated uvx command.")
    return {"command": parts[0], "args": parts[1:]}


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HarnessBootstrapError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise HarnessBootstrapError(f"{path} must contain a TOML object.")
    return value


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise HarnessBootstrapError(f"{path} must contain a JSON object.")
    return value


def _validate_server_entry(entry: object, expected: dict[str, Any], path: Path) -> None:
    if entry is None:
        return
    if entry != expected:
        raise HarnessBootstrapError(
            f"{path} already defines a different {_MCP_SERVER_NAME!r} MCP server."
        )


def _validate_adapter_targets(root: Path, release_root: Path) -> None:
    for host in SUPPORTED_HOSTS:
        source = release_root / "adapters" / host
        destination = root / ".rob2" / "adapters" / host
        if destination.exists() and not _same_tree(source, destination):
            raise HarnessBootstrapError(
                f"{destination} differs from the locked {host} adapter."
            )
    for host, skill_root in _HOST_SKILL_ROOTS:
        for skill_name in CANONICAL_SKILL_NAMES:
            source = release_root / "skills" / skill_name
            destination = root / skill_root / skill_name
            if destination.exists() and not _same_tree(source, destination):
                raise HarnessBootstrapError(
                    f"{destination} differs from the canonical {host} skill adapter."
                )
    project_lock = root / ".rob2" / _BOOTSTRAP_LOCK
    release_lock = release_root / _BOOTSTRAP_LOCK
    if project_lock.exists() and project_lock.read_bytes() != release_lock.read_bytes():
        raise HarnessBootstrapError(
            f"{project_lock} differs from the installed execution contract."
        )
    for name in _REFERENCE_FILENAMES:
        source = release_root / "docs" / name
        destination = root / ".rob2" / "references" / name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise HarnessBootstrapError(
                f"{destination} differs from the bundled shared Harness reference."
            )
    for _host, skill_root in _HOST_SKILL_ROOTS:
        for name in _REFERENCE_FILENAMES:
            source = release_root / "docs" / name
            destination = root / skill_root / "references" / name
            if destination.exists() and destination.read_bytes() != source.read_bytes():
                raise HarnessBootstrapError(
                    f"{destination} differs from the bundled shared Harness reference."
                )


def _install_adapter_trees(root: Path, release_root: Path) -> bool:
    changed = False
    for host in SUPPORTED_HOSTS:
        source = release_root / "adapters" / host
        destination = root / ".rob2" / "adapters" / host
        if not destination.exists():
            shutil.copytree(source, destination)
            changed = True
    return changed


def _install_skills(root: Path, release_root: Path) -> bool:
    changed = False
    for _host, skill_root in _HOST_SKILL_ROOTS:
        for skill_name in CANONICAL_SKILL_NAMES:
            source = release_root / "skills" / skill_name
            destination = root / skill_root / skill_name
            if not destination.exists():
                shutil.copytree(source, destination)
                changed = True
    return changed


def _install_bootstrap_lock(root: Path, release_root: Path) -> bool:
    destination = root / ".rob2" / _BOOTSTRAP_LOCK
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release_root / _BOOTSTRAP_LOCK, destination)
    return True


def _install_references(root: Path, release_root: Path) -> bool:
    changed = False
    reference_root = root / ".rob2" / "references"
    reference_root.mkdir(parents=True, exist_ok=True)
    for name in _REFERENCE_FILENAMES:
        destination = reference_root / name
        if not destination.exists():
            shutil.copyfile(release_root / "docs" / name, destination)
            changed = True
    for _host, skill_root in _HOST_SKILL_ROOTS:
        host_references = root / skill_root / "references"
        host_references.mkdir(parents=True, exist_ok=True)
        for name in _REFERENCE_FILENAMES:
            destination = host_references / name
            if not destination.exists():
                shutil.copyfile(release_root / "docs" / name, destination)
                changed = True
    return changed


def _install_codex_server(path: Path, config: dict[str, Any], expected: dict[str, Any]) -> bool:
    servers = config.get("mcp_servers")
    if servers is not None and not isinstance(servers, dict):
        raise HarnessBootstrapError(f"{path} has a non-table mcp_servers value.")
    if isinstance(servers, dict) and _MCP_SERVER_NAME in servers:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = path.read_text(encoding="utf-8") if path.exists() else ""
    if re.search(r"(?m)^\s*mcp_servers\s*=", prefix):
        raise HarnessBootstrapError(
            f"{path} defines mcp_servers as an inline value that cannot be extended safely."
        )
    separator = "" if not prefix or prefix.endswith("\n") else "\n"
    args = ", ".join(json.dumps(value) for value in expected["args"])
    path.write_text(
        f"{prefix}{separator}\n[mcp_servers.{_MCP_SERVER_NAME}]\n"
        f"command = {json.dumps(expected['command'])}\nargs = [{args}]\n",
        encoding="utf-8",
    )
    return True


def _install_claude_server(path: Path, config: dict[str, Any], expected: dict[str, Any]) -> bool:
    servers = config.get("mcpServers")
    if servers is None:
        servers = {}
        config["mcpServers"] = servers
    if not isinstance(servers, dict):
        raise HarnessBootstrapError(f"{path} has a non-object mcpServers value.")
    if _MCP_SERVER_NAME in servers:
        return False
    servers[_MCP_SERVER_NAME] = expected
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _check_execution_contract(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        verify_host_adapters(release_root)
        lock = load_release_lock(release_root)
        project_lock = root / ".rob2" / _BOOTSTRAP_LOCK
        if project_lock.read_bytes() != (release_root / _BOOTSTRAP_LOCK).read_bytes():
            raise ValueError(
                "project-local execution contract differs from the installed rob2.lock"
            )
    except (OSError, ValueError) as error:
        return _failed(
            str(error),
            "Run rob2 bootstrap to install the exact locked execution contract.",
        )
    return {"ok": True, "lock": lock.model_dump(mode="json"), "recovery": ()}


def _check_canonical_skills(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        for host, skill_root in _HOST_SKILL_ROOTS:
            for skill_name in CANONICAL_SKILL_NAMES:
                if not _same_tree(
                    release_root / "skills" / skill_name,
                    root / skill_root / skill_name,
                ):
                    raise ValueError(f"{host} {skill_name} differs from the canonical skill")
    except (LedgerError, ValueError) as error:
        return _failed(
            str(error),
            "Run rob2 bootstrap after preserving any intentional local edits.",
        )
    return {"ok": True, "skills": list(CANONICAL_SKILL_NAMES), "recovery": ()}


def _check_host_adapters(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        for host in SUPPORTED_HOSTS:
            if not _same_tree(
                release_root / "adapters" / host,
                root / ".rob2" / "adapters" / host,
            ):
                raise ValueError(f"project-local {host} adapter differs from the locked adapter")
        expected_server = _server_config(load_release_lock(release_root))
        codex_config = _read_toml(root / ".codex" / "config.toml")
        codex_servers = codex_config.get("mcp_servers")
        if not isinstance(codex_servers, dict):
            raise ValueError("Codex config does not define an MCP server table")
        _require_server_entry(
            codex_servers.get(_MCP_SERVER_NAME), expected_server, "Codex config"
        )
        claude_config = _read_json_object(root / ".mcp.json")
        claude_servers = claude_config.get("mcpServers")
        if not isinstance(claude_servers, dict):
            raise ValueError("Claude config does not define an MCP server object")
        _require_server_entry(
            claude_servers.get(_MCP_SERVER_NAME), expected_server, "Claude config"
        )
    except ValueError as error:
        return _failed(str(error), "Run rob2 bootstrap to restore the generated adapter tree.")
    return {"ok": True, "hosts": list(sorted(SUPPORTED_HOSTS)), "recovery": ()}


def _require_server_entry(entry: object, expected: dict[str, Any], description: str) -> None:
    if entry != expected:
        raise ValueError(f"{description} does not match the locked {_MCP_SERVER_NAME} launcher")


def _check_mcp_launchability(project_root: Path) -> dict[str, Any]:
    try:
        if shutil.which("uvx") is None and shutil.which("uv") is None:
            raise ValueError("neither uvx nor uv is available on PATH")
        lock = load_release_lock(_release_root())
        launcher = _server_config(lock)
        tools = verify_mcp_launchability(
            project_root,
            launcher["command"],
            tuple(launcher["args"]),
        )
    except (ImportError, OSError, TimeoutError, ValueError) as error:
        return _failed(
            str(error),
            "Install the exact locked release with uvx, then rerun rob2 doctor.",
        )
    return {"ok": True, "tools": list(tools), "recovery": ()}


def _check_project_state(root: Path) -> dict[str, Any]:
    ledger_path = root / ".rob2" / "ledger.sqlite3"
    if not ledger_path.exists():
        return {
            "ok": True,
            "state": "not_initialized",
            "recovery": ("Use rob2-init to prepare and confirm a Run when ready.",),
        }
    try:
        receipt = WorkflowLedger(
            ledger_path,
            ArtifactStore(root / ".rob2" / "artifacts"),
        ).preflight()
    except ValueError as error:
        return _failed(str(error), "Preserve .rob2, archive it, and start a new compatible Run.")
    return {
        "ok": receipt.ok,
        "state": "compatible",
        "schema_version": receipt.schema_version,
        "recovery": (),
    }


def _same_tree(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    left_files = {path.relative_to(left): path for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right): path for path in right.rglob("*") if path.is_file()}
    return left_files.keys() == right_files.keys() and all(
        path.read_bytes() == right_files[relative].read_bytes()
        for relative, path in left_files.items()
    )


def _failed(detail: str, recovery: str) -> dict[str, Any]:
    return {"ok": False, "detail": detail, "recovery": (recovery,)}
