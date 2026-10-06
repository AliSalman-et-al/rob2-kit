"""Supported Codex entrypoint and frozen runner binding controls; no model calls."""

from __future__ import annotations

import json
import os
import runpy
import sys
import tomllib
from pathlib import Path

import pytest

from rob2_kit.interfaces.cli.app import main


@pytest.mark.parametrize("command", ["mcp", "mcp-codex"])
def test_cli_selects_explicit_host_entrypoint(command, monkeypatch):
    from rob2_kit.interfaces.mcp import codex, server

    called = []
    monkeypatch.setattr(server, "main", lambda: called.append("mcp"))
    monkeypatch.setattr(codex, "main", lambda: called.append("mcp-codex"))
    assert main([command]) == 0
    assert called == [command]


def test_packaged_hosts_select_codex_compatibility_only():
    root = Path(__file__).parents[1] / "src/rob2_kit/hosts"
    assert json.loads((root / "codex.json").read_text())["mcp_command"] == "rob2 mcp-codex"
    assert json.loads((root / "claude-code.json").read_text())["mcp_command"] == "rob2 mcp"


@pytest.mark.parametrize("command", ["mcp", "mcp-codex"])
def test_runner_config_keeps_selected_binding(command, tmp_path):
    runner = runpy.run_path("scripts/run_rsi_case.py")
    config = tomllib.loads("\n".join(runner["_codex_mcp_config"]("rob2", tmp_path, command)))
    assert config["mcp_servers"]["rob2"]["args"] == [command]


@pytest.mark.parametrize("command", ["mcp", "mcp-codex"])
def test_actual_stdio_entrypoint_preflight_binds_original_schemas(command, tmp_path, monkeypatch):
    from scripts.benchmark_contract import probe_server_advertised_inventory

    # uv installs the platform-native console launcher, including rob2.exe on Windows.
    executable = Path(sys.executable).parent / ("rob2.exe" if os.name == "nt" else "rob2")
    assert executable.is_file()
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = probe_server_advertised_inventory(executable, workspace, mcp_command=command)
    assert result["status"] == "verified"
    binding = result["server_binding"]
    assert isinstance(binding, dict)
    assert binding["args"] == [command]


@pytest.mark.parametrize("command", ["mcp", "mcp-codex"])
def test_native_cli_prevents_pdf_recommendation_from_contaminating_stdout(
    command, monkeypatch, capsys
):
    import pymupdf

    from rob2_kit.interfaces.mcp import codex, server

    monkeypatch.setattr(pymupdf, "_recommend_layout", True)
    monkeypatch.setenv("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "1")
    monkeypatch.setattr(pymupdf.importlib.util, "find_spec", lambda name: None)
    entrypoint = server if command == "mcp" else codex
    monkeypatch.setattr(entrypoint, "main", pymupdf._warn_layout_once)
    assert main([command]) == 0
    assert capsys.readouterr().out == ""
