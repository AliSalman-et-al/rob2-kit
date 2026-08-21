"""Isolated, noninteractive host launcher for ``rob2 assess``."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .application._state import read_json
from .application.contracts import VerifiedCurrentStatus
from .application.finalization import FinalizationResult, verify_finalization_result
from .application.status import current_status

EXIT_FINALIZED = 0
EXIT_PAUSED = 10
EXIT_HOST_FAILURE = 20
EXIT_POSTFLIGHT_FAILURE = 30

Host = Literal["codex", "claude-code"]


class UnsupportedHostIsolation(RuntimeError):
    """The installed host cannot express the MCP-only capability boundary."""


@dataclass(frozen=True)
class LaunchResult:
    exit_code: int
    output: str
    error: str
    status_path: Path


def _host_command(host: Host, model: str | None, config: Path, project: Path) -> list[str]:
    if host == "codex":
        raise UnsupportedHostIsolation(
            "unsupported-host-isolation: installed Codex CLI cannot disable built-in shell/filesystem tools"
        )
    else:
        from .interfaces.mcp.server import PUBLIC_TOOL_NAMES

        allowed_tools = ",".join(f"mcp__rob2-kit__{name}" for name in PUBLIC_TOOL_NAMES)
        command = [
            "claude", "--print", "--mcp-config", str(config), "--strict-mcp-config",
            "--tools", allowed_tools, "--allowedTools", allowed_tools,
            "--permission-mode", "dontAsk", "--no-session-persistence",
            "--setting-sources", "project",
        ]
    if model:
        command.extend(["--model", model])
    return command


def _config(workspace: Path, path: Path) -> None:
    payload = {
        "mcpServers": {
            "rob2-kit": {
                "command": "rob2",
                "args": ["mcp"],
                "env": {"ROB2_WORKSPACE": str(workspace)},
            }
        }
    }
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _install_skills(project: Path) -> None:
    source = Path(__file__).parent / "skills"
    destination = project / ".claude" / "skills"
    if not source.is_dir():
        raise UnsupportedHostIsolation("unsupported-host-isolation: packaged rob2 skills are unavailable")
    destination.mkdir(parents=True, exist_ok=True)
    for skill in ("rob2-workflow", "rob2-signalling"):
        source_skill = source / skill
        if not source_skill.is_dir():
            raise UnsupportedHostIsolation(f"unsupported-host-isolation: packaged skill {skill} is unavailable")
        shutil.copytree(source_skill, destination / skill)


def _postflight(workspace: Path, status: VerifiedCurrentStatus | None, error: str | None) -> tuple[Path, str]:
    state_dir = workspace / ".rob2-kit"
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": None if status is None else status.model_dump(mode="json"),
        "error": error,
    }
    path = state_dir / "postflight-status.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    if status is None:
        block = "Verified rob2-kit status\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    else:
        block = "Verified rob2-kit status\n" + status.model_dump_json(exclude_none=True, exclude_defaults=True)
    return path, block


def launch_assessment(
    workspace: str | Path,
    host: Host,
    model: str | None,
    prompt: str,
    *,
    executable_env: dict[str, str] | None = None,
) -> LaunchResult:
    """Run one isolated host process and always perform durable postflight."""

    root = Path(workspace).resolve(strict=True)
    if host not in ("codex", "claude-code"):
        raise ValueError("unsupported host")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("assessment prompt must not be blank")
    launch_root = root / ".rob2-kit" / "launches"
    launch_root.mkdir(parents=True, exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix="assessment-", dir=launch_root))
    config = project / "mcp-config.json"
    try:
        _config(root, config)
        _install_skills(project)
    except UnsupportedHostIsolation as error:
        shutil.rmtree(project, ignore_errors=True)
        return LaunchResult(EXIT_POSTFLIGHT_FAILURE, "", str(error), root / ".rob2-kit" / "postflight-status.json")
    environment = os.environ.copy()
    if executable_env:
        environment.update(executable_env)
    environment["ROB2_LAUNCH_PROJECT"] = str(project)
    process_return = EXIT_HOST_FAILURE
    stdout = ""
    stderr = ""
    status: VerifiedCurrentStatus | None = None
    postflight_error: str | None = None
    try:
        command = _host_command(host, model, config, project)
        completed = subprocess.run(
            command,
            cwd=project,
            env=environment,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
        process_return = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except UnsupportedHostIsolation as error:
        stderr = str(error)
        process_return = EXIT_POSTFLIGHT_FAILURE
    except (OSError, ValueError) as error:
        stderr = str(error)
    finally:
        try:
            status = current_status(root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            postflight_error = str(error)
        status_path, block = _postflight(root, status, postflight_error)
        try:
            shutil.rmtree(project)
        except OSError:
            if postflight_error is None:
                postflight_error = "isolated project cleanup failed"
        if postflight_error is not None:
            process_return = EXIT_POSTFLIGHT_FAILURE
        elif process_return == 0:
            if getattr(status, "phase", None) == "finalized":
                finalization_identity = (read_json(root, "state.json") or {}).get("finalization_identity")
                finalization = (
                    read_json(root, f"finalization-{str(finalization_identity).removeprefix('sha256:')}.json")
                    if isinstance(finalization_identity, str)
                    else None
                )
                try:
                    verified = (
                        finalization is not None
                        and verify_finalization_result(
                            root, FinalizationResult.model_validate(finalization)
                        )
                        is not None
                    )
                except (OSError, ValueError, TypeError):
                    verified = False
                process_return = EXIT_FINALIZED if verified else EXIT_POSTFLIGHT_FAILURE
            else:
                process_return = EXIT_PAUSED
        elif process_return != EXIT_POSTFLIGHT_FAILURE:
            process_return = EXIT_HOST_FAILURE
    return LaunchResult(process_return, stdout + ("\n" if stdout and not stdout.endswith("\n") else "") + block + "\n", stderr, status_path)
