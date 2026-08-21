from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rob2_kit.application._state import write_jsons
from rob2_kit.launcher import (
    EXIT_FINALIZED,
    EXIT_HOST_FAILURE,
    EXIT_PAUSED,
    EXIT_POSTFLIGHT_FAILURE,
    launch_assessment,
)

# ruff: noqa: E501


def test_launcher_isolates_config_and_appends_verified_pause(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        config = Path(command[command.index("--mcp-config") + 1])
        observed["config"] = json.loads(config.read_text(encoding="utf-8"))
        observed["cwd"] = kwargs["cwd"]
        project = Path(kwargs["cwd"])
        observed["skills"] = sorted(
            path.relative_to(project).as_posix()
            for path in (project / ".claude" / "skills").rglob("SKILL.md")
        )
        observed["command"] = command
        assert "private-prompt" in kwargs["input"]
        return subprocess.CompletedProcess(command, 0, "model prose", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = launch_assessment(tmp_path, "claude-code", "model", "private-prompt")
    assert result.exit_code == EXIT_PAUSED
    assert "Verified rob2-kit status" in result.output
    assert "No active Batch" in result.output
    assert observed["config"]["mcpServers"]["rob2-kit"]["env"]["ROB2_WORKSPACE"] == str(tmp_path.resolve())
    assert observed["skills"] == [
        ".claude/skills/rob2-signalling/SKILL.md",
        ".claude/skills/rob2-workflow/SKILL.md",
    ]
    assert "--strict-mcp-config" in observed["command"]
    assert "--tools" in observed["command"]
    allowed = observed["command"][observed["command"].index("--tools") + 1]
    assert allowed.startswith("mcp__rob2-kit__preflight_sources,")
    assert allowed.endswith("mcp__rob2-kit__read_record")
    assert observed["command"][observed["command"].index("--allowedTools") + 1] == allowed
    assert observed["command"][observed["command"].index("--permission-mode") + 1] == "dontAsk"
    assert "--safe-mode" not in observed["command"]
    assert not Path(observed["cwd"]).exists()
    assert "private-prompt" not in result.output


def test_launcher_finally_postflight_and_exit_classes(monkeypatch, tmp_path: Path) -> None:
    write_jsons(tmp_path, {"state.json": {"phase": "finalized", "trial_dispositions": {}}})
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""))
    result = launch_assessment(tmp_path, "claude-code", None, "finish")
    assert result.exit_code == EXIT_POSTFLIGHT_FAILURE
    postflight = json.loads(result.status_path.read_text(encoding="utf-8"))
    assert postflight["status"]["phase"] == "finalized"

    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 7, "", "host failed"))
    failed = launch_assessment(tmp_path, "claude-code", None, "finish")
    assert failed.exit_code == EXIT_HOST_FAILURE
    assert "Verified rob2-kit status" in failed.output


def test_codex_fails_closed_when_mcp_only_is_unsupported(tmp_path: Path) -> None:
    result = launch_assessment(tmp_path, "codex", None, "private")
    assert result.exit_code == 30
    assert "unsupported-host-isolation" in result.error


@pytest.mark.skipif(
    os.environ.get("ROB2_RUN_LIVE_CLAUDE") != "1",
    reason="opt-in live Claude Code smoke test",
)
def test_live_claude_isolated_smoke(tmp_path: Path) -> None:
    """Exercise the packaged Claude boundary with the installed CLI."""

    workspace_marker = str(tmp_path.resolve())
    result = launch_assessment(
        tmp_path,
        "claude-code",
        None,
        "Call preflight_sources once with root alias dossier, relative path '.', and trial ID "
        "handshake. Then reply exactly ROB2_LIVE_OK without revealing workspace paths.",
    )
    assert "ROB2_LIVE_OK" in result.output
    assert '"phase":"intake"' in result.output
    assert workspace_marker not in result.output
    assert workspace_marker not in result.error
    assert "Verified rob2-kit status" in result.output
    assert result.exit_code in (EXIT_PAUSED, EXIT_FINALIZED)
