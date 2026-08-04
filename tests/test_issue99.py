"""Project-local release runtime and ownership contracts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
from rob2_kit.interfaces.cli.app import app
from rob2_kit.interfaces import harness

ROOT = Path(__file__).resolve().parents[1]


def _bundled_release(tmp_path: Path) -> Path:
    bundled = tmp_path / "site-packages" / "rob2_kit"
    bundled.mkdir(parents=True)
    (bundled / "__init__.py").write_text("", encoding="utf-8")
    for name in ("adapters", "skills", "docs", "packs", "schemas"):
        shutil.copytree(ROOT / name, bundled / name)
    shutil.copyfile(ROOT / "rob2.lock", bundled / "rob2.lock")
    shutil.copyfile(ROOT / "uv.lock", bundled / "uv.lock")
    shutil.copytree(ROOT / "release", bundled / "release")
    return bundled


def test_bootstrap_materializes_runtime_and_portable_ownership_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda name: name)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        return object()

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    project = tmp_path / "project"

    result = CliRunner().invoke(app, ["bootstrap", str(project)])

    assert result.exit_code == 0, result.output
    assert calls and calls[0][1:4] == ["sync", "--locked", "--no-sources"]
    assert (project / ".rob2" / "runtime" / "pyproject.toml").is_file()
    codex = (project / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'command = "uv"' in codex
    assert '".rob2/runtime"' in codex
    claude = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"]["rob2-kit"]["args"][4] == "${CLAUDE_PROJECT_DIR}/.rob2/runtime"

    ownership = json.loads((project / "rob2.lock").read_text(encoding="utf-8"))
    assert ownership["kind"] == "rob2-kit-project"
    assert ownership["runtime"]["path"] == ".rob2/runtime"
    assert {"engine", "schema", "packs", "skills", "adapters", "parser", "policies"} <= set(
        ownership["identities"]
    )
    assert ownership["config_ownership"]["codex"]["key"] == "mcp_servers.rob2-kit"


def test_doctor_reports_runtime_and_ownership_without_mutating(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda name: name)
    monkeypatch.setattr(harness.subprocess, "run", lambda *_args, **_kwargs: object())
    project = tmp_path / "project"
    assert CliRunner().invoke(app, ["bootstrap", str(project)]).exit_code == 0
    monkeypatch.setattr(harness, "verify_mcp_launchability", lambda *_args: RUN_OPERATION_NAMES)

    before = (project / "rob2.lock").read_bytes()
    result = CliRunner().invoke(app, ["doctor", str(project)])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["ok"] is True
    assert receipt["checks"]["locked_runtime"]["state"] == "locked"
    assert receipt["checks"]["ownership"]["schema_version"] == 1
    assert (project / "rob2.lock").read_bytes() == before


def test_failed_bootstrap_restores_prior_project_bytes(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda name: name)
    monkeypatch.setattr(harness.subprocess, "run", lambda *_args, **_kwargs: object())
    project = tmp_path / "project"
    config = project / ".mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"mcpServers": {"unrelated": {"command": "keep"}}}\n', encoding="utf-8")
    original = config.read_bytes()
    monkeypatch.setattr(
        harness,
        "_install_claude_server",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("simulated write failure")),
    )

    result = CliRunner().invoke(app, ["bootstrap", str(project)])

    assert result.exit_code != 0
    assert "prior project state was restored" in result.output
    assert config.read_bytes() == original
    assert not (project / "rob2.lock").exists()
    assert not (project / ".rob2" / "runtime").exists()
