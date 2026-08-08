"""Public project-local Harness installation and diagnostic contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
from rob2_kit.interfaces.cli.app import app
from rob2_kit.interfaces.harness import _release_root
from rob2_kit.release import load_release_lock
from rob2_kit.storage import ArtifactStore, WorkflowLedger

ROOT = Path(__file__).resolve().parents[1]


def _expected_server() -> dict[str, object]:
    """Return the launcher for the current source checkout or wheel install."""

    release_root = _release_root()
    if (release_root / "__init__.py").is_file():
        return {
            "command": sys.executable,
            "args": ["-m", "rob2_kit.interfaces.mcp.server"],
        }
    return {
        "command": "uvx",
        "args": [
            "--python",
            "3.13",
            "--from",
            "rob2-kit==0.1.0",
            "rob2-mcp",
        ],
    }


def test_bootstrap_from_an_installed_wheel_uses_that_exact_install(
    tmp_path: Path, monkeypatch
) -> None:
    """A locally installed wheel must not be replaced by a registry lookup."""

    bundled_root = tmp_path / "site-packages" / "rob2_kit"
    bundled_root.mkdir(parents=True)
    (bundled_root / "__init__.py").write_text("", encoding="utf-8")
    for name in ("adapters", "skills", "docs", "packs", "schemas"):
        shutil.copytree(ROOT / name, bundled_root / name)
    shutil.copyfile(ROOT / "rob2.lock", bundled_root / "rob2.lock")
    shutil.copyfile(ROOT / "uv.lock", bundled_root / "uv.lock")
    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: bundled_root)

    project_root = tmp_path / "consumer"
    result = CliRunner().invoke(app, ["bootstrap", str(project_root)])

    assert result.exit_code == 0, result.output
    codex = tomllib.loads((project_root / ".codex" / "config.toml").read_text(encoding="utf-8"))
    server = codex["mcp_servers"]["rob2-kit"]
    assert server == {
        "command": sys.executable,
        "args": ["-m", "rob2_kit.interfaces.mcp.server"],
    }


def _build_bundled_release_with_runtime(root: Path) -> Path:
    """Build an installed-wheel-shaped release root with an embedded runtime wheel."""

    bundled_root = root / "site-packages" / "rob2_kit"
    bundled_root.mkdir(parents=True)
    (bundled_root / "__init__.py").write_text("", encoding="utf-8")
    for name in ("adapters", "skills", "docs", "packs", "schemas"):
        shutil.copytree(ROOT / name, bundled_root / name)
    shutil.copyfile(ROOT / "rob2.lock", bundled_root / "rob2.lock")
    shutil.copyfile(ROOT / "uv.lock", bundled_root / "uv.lock")

    runtime = bundled_root / "release" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "pyproject.toml").write_text('[project]\nname = "stub"\n', encoding="utf-8")
    (runtime / "uv.lock").write_text("", encoding="utf-8")

    wheel = runtime / "rob2_kit-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "rob2_kit-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: rob2-kit\nVersion: 0.1.0\n",
        )
    (bundled_root / "release" / "runtime-wheel-pin.json").write_text(
        json.dumps(
            {
                "filename": wheel.name,
                "version": "0.1.0",
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return bundled_root


def test_bootstrap_unlocked_wires_directly_to_the_shared_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    """--unlocked skips the project-local runtime copy and declares the mode."""

    bundled_root = _build_bundled_release_with_runtime(tmp_path)
    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: bundled_root)

    project_root = tmp_path / "consumer"
    result = CliRunner().invoke(app, ["bootstrap", str(project_root), "--unlocked"])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["runtime_mode"] == "unlocked"
    assert receipt["runtime"] is None
    assert not (project_root / ".rob2" / "runtime").exists()

    codex = tomllib.loads((project_root / ".codex" / "config.toml").read_text(encoding="utf-8"))
    server = codex["mcp_servers"]["rob2-kit"]
    assert server["command"] == "uv"
    assert str(bundled_root / "runtime") in server["args"]
    assert ".rob2/runtime" not in " ".join(server["args"])

    manifest = json.loads((project_root / "rob2.lock").read_text(encoding="utf-8"))
    assert manifest["runtime_mode"] == "unlocked"

    from rob2_kit.interfaces.harness import doctor_project

    doctor = doctor_project(project_root)
    assert doctor["ok"], doctor
    assert "locked_runtime" not in doctor["checks"]
    assert doctor["checks"]["ownership"]["ok"]
    assert doctor["checks"]["ownership"]["runtime_mode"] == "unlocked"


def test_upgrade_refuses_an_unlocked_mode_project_instead_of_recreating_a_local_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    """Unlocked mode has no in-place upgrade path yet; it must refuse, not mishandle."""

    from rob2_kit.interfaces.harness import HarnessBootstrapError, upgrade_project

    bundled_root = _build_bundled_release_with_runtime(tmp_path)
    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: bundled_root)
    project_root = tmp_path / "consumer"
    CliRunner().invoke(app, ["bootstrap", str(project_root), "--unlocked"])

    with pytest.raises(HarnessBootstrapError, match="does not yet support in-place upgrade"):
        upgrade_project(project_root, apply=True)

    assert not (project_root / ".rob2" / "runtime").exists()


def test_rollback_refuses_an_unlocked_mode_project(tmp_path: Path) -> None:
    """A rollback record recorded against a declared-unlocked project is refused."""

    from rob2_kit.interfaces.harness import HarnessBootstrapError, rollback_project

    root = tmp_path
    (root / "rob2.lock").write_text(
        json.dumps(
            {
                "kind": "rob2-kit-project",
                "schema_version": 1,
                "owned_paths": {},
                "owned_metadata_paths": [],
                "release": {},
                "runtime_mode": "unlocked",
            }
        ),
        encoding="utf-8",
    )
    backup = root / ".rob2" / "release-rollbacks" / "backup-1"
    backup.mkdir(parents=True)
    (root / ".rob2" / "rollback.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup": str(backup.relative_to(root)),
                "paths": [],
                "release": {"version": "0.1.0"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HarnessBootstrapError, match="does not yet support rollback"):
        rollback_project(root, apply=True)


def test_bootstrap_unlocked_wires_a_source_checkout_directly(tmp_path: Path, monkeypatch) -> None:
    """Unlocked mode in a source checkout wires straight to it, not the registry."""

    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: ROOT)

    consumer = tmp_path / "consumer"
    result = CliRunner().invoke(app, ["bootstrap", str(consumer), "--unlocked"])

    assert result.exit_code == 0, result.output
    claude_config = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    server = claude_config["mcpServers"]["rob2-kit"]
    assert server == {
        "command": "uv",
        "args": ["run", "--project", str(ROOT), "rob2-mcp"],
    }


def test_verify_runtime_self_consistency_passes_for_a_source_checkout(monkeypatch) -> None:
    """A source checkout has no embedded runtime, so there is nothing to check."""

    from rob2_kit.interfaces.harness import verify_runtime_self_consistency

    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: ROOT)

    verify_runtime_self_consistency()


def test_verify_runtime_self_consistency_fails_when_the_runtime_wheel_drifts_from_its_pin(
    tmp_path: Path, monkeypatch
) -> None:
    """A rebuilt-in-place runtime wheel that no longer matches its own pin is refused."""

    from rob2_kit.interfaces.harness import HarnessBootstrapError, verify_runtime_self_consistency

    bundled_root = _build_bundled_release_with_runtime(tmp_path)
    monkeypatch.setattr("rob2_kit.interfaces.harness._release_root", lambda: bundled_root)

    wheel = next((bundled_root / "release" / "runtime").glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"drift")

    with pytest.raises(HarnessBootstrapError, match="release pin"):
        verify_runtime_self_consistency()


def test_bootstrap_installs_both_hosts_idempotently_without_overwriting_user_config(
    tmp_path: Path,
) -> None:
    """Both Harnesses receive the locked adapter while unrelated settings survive."""

    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text('model = "user-selected-model"\n', encoding="utf-8")
    claude_config = tmp_path / ".mcp.json"
    unrelated_claude_server = {
        "command": "unrelated-server",
        "args": ["--preserve-me"],
    }
    claude_config.write_text(
        json.dumps({"mcpServers": {"unrelated": unrelated_claude_server}}),
        encoding="utf-8",
    )

    runner = CliRunner()
    installed = runner.invoke(app, ["bootstrap", str(tmp_path)])

    assert installed.exit_code == 0, installed.output
    receipt = json.loads(installed.stdout)
    assert receipt["status"] == "installed"
    assert receipt["hosts"] == ["claude", "codex"]

    codex = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert codex["model"] == "user-selected-model"
    expected_server = _expected_server()
    assert codex["mcp_servers"]["rob2-kit"] == expected_server
    claude = json.loads(claude_config.read_text(encoding="utf-8"))
    assert claude["mcpServers"]["unrelated"] == unrelated_claude_server
    assert claude["mcpServers"]["rob2-kit"] == expected_server

    for host, skill_root in (("codex", ".codex/skills"), ("claude", ".claude/skills")):
        for skill_name in ("rob2-init", "rob2-assess"):
            installed_skill = tmp_path / skill_root / skill_name / "SKILL.md"
            assert (
                installed_skill.read_bytes()
                == (ROOT / "skills" / skill_name / "SKILL.md").read_bytes()
            ), host
        assert {path.name for path in (tmp_path / skill_root / "references").iterdir()} == {
            "HARNESS-WORKFLOW.md",
            "RUN-DEFINITION.md",
            "EVIDENCE-SEARCH.md",
            "SIGNALING-QUESTIONS.md",
        }
    assert {path.name for path in (tmp_path / ".rob2" / "references").iterdir()} == {
        "HARNESS-WORKFLOW.md",
        "RUN-DEFINITION.md",
        "EVIDENCE-SEARCH.md",
        "SIGNALING-QUESTIONS.md",
    }

    installed_files = {
        path: path.read_bytes()
        for path in (
            codex_config,
            claude_config,
            tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md",
            tmp_path / ".claude" / "skills" / "rob2-assess" / "SKILL.md",
        )
    }
    repeated = runner.invoke(app, ["bootstrap", str(tmp_path)])
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.stdout)["status"] == "already_installed"
    assert {path: path.read_bytes() for path in installed_files} == installed_files


def test_bootstrap_refuses_a_conflicting_managed_host_entry_without_overwriting_it(
    tmp_path: Path,
) -> None:
    """A user-controlled adapter conflict remains intact and has recovery guidance."""

    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "rob2-kit": {"command": "different-launcher", "args": []},
                    "unrelated": {"command": "keep-this", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )
    original = config.read_bytes()

    result = CliRunner().invoke(app, ["bootstrap", str(tmp_path)])

    assert result.exit_code != 0
    assert "rob2-kit" in result.output
    assert "recovery" in result.output.lower()
    assert config.read_bytes() == original


def test_bootstrap_refuses_an_unextendable_codex_mcp_shape_without_overwriting_it(
    tmp_path: Path,
) -> None:
    """An inline TOML map cannot safely receive a new project server table."""

    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('mcp_servers = { unrelated = { command = "keep-this" } }\n')
    original = config.read_bytes()

    result = CliRunner().invoke(app, ["bootstrap", str(tmp_path)])

    assert result.exit_code != 0
    assert "inline" in result.output
    assert "recovery" in result.output.lower()
    assert config.read_bytes() == original


def test_doctor_verifies_the_execution_contract_and_reports_uninitialized_state(
    tmp_path: Path, monkeypatch
) -> None:
    """Doctor checks the locked install before a project Run has been authorized."""

    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap", str(tmp_path)]).exit_code == 0
    launched: dict[str, object] = {}

    def probe(project_root: Path, command: str, args: tuple[str, ...]) -> tuple[str, ...]:
        launched.update(project_root=project_root, command=command, args=args)
        return RUN_OPERATION_NAMES

    monkeypatch.setattr("rob2_kit.interfaces.harness.verify_mcp_launchability", probe)

    diagnosed = runner.invoke(app, ["doctor", str(tmp_path)])

    assert diagnosed.exit_code == 0, diagnosed.output
    receipt = json.loads(diagnosed.stdout)
    assert receipt["ok"] is True
    assert set(receipt["checks"]) == {
        "execution_contract",
        "canonical_skills",
        "host_adapters",
        "mcp_launchability",
        "project_state_schema",
    }
    assert all(check["ok"] for check in receipt["checks"].values())
    assert receipt["checks"]["project_state_schema"]["state"] == "not_initialized"
    assert receipt["checks"]["project_state_schema"]["recovery"]
    assert receipt["checks"]["execution_contract"]["lock"] == (
        load_release_lock(ROOT).model_dump(mode="json")
    )
    expected_server = _expected_server()
    expected_args = cast(list[str], expected_server["args"])
    assert receipt["checks"]["execution_contract"]["effective_launcher"] == expected_server
    assert launched == {
        "project_root": tmp_path.resolve(),
        "command": expected_server["command"],
        "args": tuple(expected_args),
    }


def test_doctor_preflights_an_existing_project_state_schema(tmp_path: Path, monkeypatch) -> None:
    """Doctor reports the exact compatible ledger schema when durable state exists."""

    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(
        "rob2_kit.interfaces.harness.verify_mcp_launchability",
        lambda _project_root, _command, _args: RUN_OPERATION_NAMES,
    )
    WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )

    receipt = json.loads(runner.invoke(app, ["doctor", str(tmp_path)]).stdout)

    assert receipt["checks"]["project_state_schema"] == {
        "ok": True,
        "state": "compatible",
        "schema_version": 1,
        "recovery": [],
    }


def test_doctor_rejects_a_missing_host_mcp_configuration(tmp_path: Path, monkeypatch) -> None:
    """Adapter hashes alone cannot prove that a Harness can launch the MCP server."""

    runner = CliRunner()
    assert runner.invoke(app, ["bootstrap", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(
        "rob2_kit.interfaces.harness.verify_mcp_launchability",
        lambda _project_root, _command, _args: RUN_OPERATION_NAMES,
    )
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")

    receipt = json.loads(runner.invoke(app, ["doctor", str(tmp_path)]).stdout)

    assert receipt["ok"] is False
    assert receipt["checks"]["host_adapters"]["ok"] is False
    assert "rob2-kit" in receipt["checks"]["host_adapters"]["detail"]
    assert receipt["checks"]["host_adapters"]["recovery"]


def test_bootstrap_reports_a_scalar_codex_mcp_setting_as_recoverable(tmp_path: Path) -> None:
    """Malformed but unrelated project configuration is never replaced implicitly."""

    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('mcp_servers = "not-a-table"\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["bootstrap", str(tmp_path)])

    assert result.exit_code != 0
    assert "mcp_servers" in result.output
    assert "recovery" in result.output.lower()


def test_canonical_skills_share_progressively_disclosed_harness_references() -> None:
    """Harness prose narrates the journey but leaves methods to the pinned tools."""

    references = {
        "HARNESS-WORKFLOW.md",
        "RUN-DEFINITION.md",
        "EVIDENCE-SEARCH.md",
        "SIGNALING-QUESTIONS.md",
    }
    assert references <= {path.name for path in (ROOT / "docs").iterdir()}
    init = (ROOT / "skills" / "rob2-init" / "SKILL.md").read_text(encoding="utf-8")
    assess = (ROOT / "skills" / "rob2-assess" / "SKILL.md").read_text(encoding="utf-8")
    for name in references:
        assert name in init or name in assess
    assert "start-new" in init
    assert "proposal" in init
    assert "confirmation" in init
    assert "Trial, Result, and Domain" in assess
    assert "interruption" in assess
    assert "terminal report" in assess
    assert "raw protocol identifier" in assess
    assert "assess or judge RoB 2" in assess

    workflow = " ".join((ROOT / "docs" / "HARNESS-WORKFLOW.md").read_text(encoding="utf-8").split())
    evidence = " ".join((ROOT / "docs" / "EVIDENCE-SEARCH.md").read_text(encoding="utf-8").split())
    questions = " ".join(
        (ROOT / "docs" / "SIGNALING-QUESTIONS.md").read_text(encoding="utf-8").split()
    )
    assert "exactly the sources returned by `get_work_context`" in workflow
    assert "copy the issued Result identity" in workflow
    assert "reuse it exactly in coverage" in evidence
    assert "no relevant evidence may support `no_information`" in evidence
    assert "complete_with_limitations` retains a material source or search uncertainty" in evidence
    assert "omit `seed_family`" in evidence
    assert "every active question returned by `get_work_context`" in questions
    assert "do not attach `evidence_refs`" in questions
    assert "no_information" in questions
    assert "cited or related trial is out of scope" in questions
    assert "one active question solely from evidence addressing another" in questions
