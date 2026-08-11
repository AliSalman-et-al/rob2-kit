"""Project-local release runtime and ownership contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
from rob2_kit.interfaces import harness
from rob2_kit.interfaces.cli.app import app

ROOT = Path(__file__).resolve().parents[1]


def _bundled_release(tmp_path: Path) -> Path:
    bundled = tmp_path / "site-packages" / "rob2_kit"
    bundled.mkdir(parents=True)
    (bundled / "__init__.py").write_text("", encoding="utf-8")
    for name in ("adapters", "skills", "docs", "packs", "schemas"):
        shutil.copytree(ROOT / name, bundled / name)
    shutil.copyfile(ROOT / "rob2.lock", bundled / "rob2.lock")
    shutil.copyfile(ROOT / "uv.lock", bundled / "uv.lock")
    shutil.copytree(
        ROOT / "release",
        bundled / "release",
        ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
    )
    output = tmp_path / "wheel"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    built = next(output.glob("rob2_kit-*.whl"))
    wheel = bundled / built.name
    shutil.copyfile(built, wheel)
    runtime_wheel = bundled / "release" / "runtime" / built.name
    for stale in (bundled / "release" / "runtime").glob("*.whl"):
        stale.unlink()
    shutil.copyfile(built, runtime_wheel)
    (bundled / "release" / "wheel-pin.json").write_text(
        json.dumps(
            {
                "filename": wheel.name,
                "version": "0.1.0",
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (bundled / "release" / "runtime-wheel-pin.json").write_text(
        json.dumps(
            {
                "filename": runtime_wheel.name,
                "version": "0.1.0",
                "sha256": hashlib.sha256(runtime_wheel.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
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
    assert any(command[1:4] == ["sync", "--locked", "--project"] for command in calls)
    assert not any("lock" in command[1:] for command in calls)
    assert (project / ".rob2" / "runtime" / "pyproject.toml").is_file()
    codex = (project / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert 'command = "uv"' in codex
    assert '".rob2/runtime"' in codex
    claude = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"]["rob2-kit"]["args"][3] == "${CLAUDE_PROJECT_DIR}/.rob2/runtime"

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
    (project / ".rob2" / "runtime" / ".venv").mkdir(exist_ok=True)
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
    journal = json.loads((project / ".rob2" / "install-journal.json").read_text())
    assert journal["status"] == "rollback_succeeded"
    assert journal["restored_paths"]


def test_missing_uv_fails_transactionally(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda _name: None)
    result = CliRunner().invoke(app, ["bootstrap", str(tmp_path / "project")])
    assert result.exit_code != 0
    assert "prior project state was restored" in result.output.lower()


def test_runtime_sync_failure_fails_transactionally(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "uv")),
    )
    result = CliRunner().invoke(app, ["bootstrap", str(tmp_path / "project")])
    assert result.exit_code != 0
    assert "prior project state was restored" in result.output.lower()


def test_rebootstrap_refuses_a_tampered_existing_runtime(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundled_release(tmp_path)
    monkeypatch.setattr(harness, "_release_root", lambda: bundled)
    monkeypatch.setattr(harness.shutil, "which", lambda name: name)
    monkeypatch.setattr(harness.subprocess, "run", lambda *_args, **_kwargs: object())
    project = tmp_path / "project"
    assert CliRunner().invoke(app, ["bootstrap", str(project)]).exit_code == 0

    ownership = project / "rob2.lock"
    before = ownership.read_bytes()
    runtime = project / ".rob2" / "runtime" / "pyproject.toml"
    runtime.write_text(runtime.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["bootstrap", str(project)])

    assert result.exit_code != 0
    assert "owned generated file differs" in result.output
    assert ownership.read_bytes() == before


def test_built_main_wheel_bootstraps_a_real_project_runtime(tmp_path: Path) -> None:
    """Exercise the published-wheel path with uv rather than source fixtures."""

    source_root = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            ".hypothesis",
            "__pycache__",
            "dist",
        ),
    )
    subprocess.run([sys.executable, "scripts/build_release.py"], cwd=source_root, check=True)
    runtime_wheels = tuple((source_root / "release" / "runtime").glob("rob2_kit*.whl"))
    assert [wheel.name for wheel in runtime_wheels] == ["rob2_kit-0.1.0-py3-none-any.whl"]
    wheel = next((source_root / "dist").glob("rob2_kit-*.whl"))
    environment = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(environment), "--python", sys.executable], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True)
    project = tmp_path / "project"
    rob2 = environment / ("Scripts/rob2.exe" if os.name == "nt" else "bin/rob2")
    result = subprocess.run(
        [str(rob2), "bootstrap", str(project)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (project / ".rob2" / "runtime" / ".venv").is_dir()
    assert (project / ".rob2" / "install-journal.json").is_file()
    diagnosed = subprocess.run(
        [str(rob2), "doctor", str(project)],
        capture_output=True,
        text=True,
    )
    assert diagnosed.returncode == 0, diagnosed.stderr or diagnosed.stdout
    assert json.loads(diagnosed.stdout)["ok"] is True
