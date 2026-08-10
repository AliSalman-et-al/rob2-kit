"""Transactional release cutover contracts for issue #108."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path

import anyio
import pytest

from rob2_kit.interfaces import harness
from rob2_kit.interfaces.harness import (
    HarnessBootstrapError,
    _check_project_state,
    bootstrap_project,
    preview_uninstall_project,
    rollback_project,
    uninstall_project,
    upgrade_project,
)
from rob2_kit.interfaces.mcp.server import CANONICAL_TOOL_NAMES, create_server
from rob2_kit.release import ReleaseLock


def _install_switchable_candidate_launcher(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Install a candidate-only launcher change for lifecycle cutover tests."""

    original_server_config = harness._server_config
    candidate = {"enabled": False}

    def server_config(
        lock: ReleaseLock, release_root: Path, host: str = "codex", *, mode: str = "locked"
    ) -> dict[str, object]:
        if not candidate["enabled"]:
            return original_server_config(lock, release_root, host, mode=mode)
        return {"command": "candidate-launcher", "args": ["--host", host, "rob2-mcp"]}

    monkeypatch.setattr(harness, "_server_config", server_config)
    return candidate


def test_cutover_exposes_exactly_the_twelve_canonical_tools() -> None:
    names = tuple(tool.name for tool in anyio.run(create_server().list_tools))

    assert names == CANONICAL_TOOL_NAMES
    assert len(names) == 12
    assert not {"run_status", "classify_sources", "resolve_result", "correct_domain_answers"} & set(
        names
    )


def test_upgrade_requires_a_preview_then_records_a_rollback_transaction(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    before = (tmp_path / "rob2.lock").read_bytes()

    preview = upgrade_project(tmp_path)
    assert preview["preview"] is True
    assert preview["user_action"].endswith("--apply PROJECT_ROOT.")
    assert not set(preview["owned_removals"]) & {
        "rob2.lock",
        ".rob2/rob2.lock",
        ".rob2/install-journal.json",
        ".rob2/runtime",
    }
    assert (tmp_path / "rob2.lock").read_bytes() == before

    upgraded = upgrade_project(tmp_path, apply=True)
    assert upgraded["status"] == "upgraded"
    assert (tmp_path / "rob2.lock").is_file()
    assert (tmp_path / ".rob2" / "rollback.json").is_file()

    rollback_preview = rollback_project(tmp_path)
    assert rollback_preview["preview"] is True
    rollback_record = json.loads((tmp_path / ".rob2" / "rollback.json").read_text())
    rollback_backup = tmp_path / rollback_record["backup"]
    assert rollback_project(tmp_path, apply=True)["status"] == "rolled_back"
    assert (tmp_path / "rob2.lock").read_bytes() == before
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not rollback_backup.exists()
    with pytest.raises(HarnessBootstrapError, match="no complete release rollback transaction"):
        rollback_project(tmp_path)


def test_uninstall_is_previewed_and_refuses_ambiguous_owned_content(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    preview = preview_uninstall_project(tmp_path)
    assert preview["preview"] is True
    assert preview["owned_removals"]
    assert {"rob2.lock", ".rob2/rob2.lock", ".rob2/rollback.json"} <= set(preview["owned_removals"])
    assert {
        ".codex/config.toml:mcp_servers.rob2-kit",
        ".mcp.json:mcpServers.rob2-kit",
    } <= set(preview["owned_removals"])
    assert preview["state_compatibility"]["ok"] is True

    owned_skill = tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md"
    owned_skill.write_text("user edit\n", encoding="utf-8")
    with pytest.raises(HarnessBootstrapError, match="owned generated file differs"):
        uninstall_project(tmp_path, apply=True)
    assert owned_skill.read_text(encoding="utf-8") == "user edit\n"


def test_uninstall_removes_only_its_host_entries(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers":{"unrelated":{"command":"keep"}}}\n', encoding="utf-8"
    )
    bootstrap_project(tmp_path)

    result = uninstall_project(tmp_path, apply=True)

    assert result["status"] == "uninstalled"
    assert "rob2-kit" not in (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert '"unrelated"' in (tmp_path / ".mcp.json").read_text(encoding="utf-8")


def test_uninstall_preserves_unrelated_claude_entry_bytes(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers":{"unrelated":{"command":"keep","args":["--exact"]}}}\n',
        encoding="utf-8",
    )
    bootstrap_project(tmp_path)
    claude_path = tmp_path / ".mcp.json"
    before = claude_path.read_bytes()
    unrelated_tail = before[before.index(b'    "unrelated"') :]

    uninstall_project(tmp_path, apply=True)

    assert claude_path.read_bytes().endswith(unrelated_tail)


def test_uninstall_preserves_unmanaged_codex_bytes_and_refuses_managed_comments(
    tmp_path: Path,
) -> None:
    codex_path = tmp_path / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_path.write_bytes(b"# keep these bytes exactly\n\n")
    bootstrap_project(tmp_path)

    uninstall_project(tmp_path, apply=True)

    assert codex_path.read_bytes() == b"# keep these bytes exactly\n\n"

    bootstrap_project(tmp_path)
    codex_path.write_text(
        codex_path.read_text(encoding="utf-8") + "# user comment\n", encoding="utf-8"
    )
    with pytest.raises(HarnessBootstrapError, match="Codex MCP section differs"):
        uninstall_project(tmp_path, apply=True)


def test_failed_upgrade_leaves_no_rollback_record(tmp_path: Path, monkeypatch) -> None:
    bootstrap_project(tmp_path)
    monkeypatch.setattr(
        harness,
        "_verify_candidate_install",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("candidate failed")),
    )

    with pytest.raises(HarnessBootstrapError, match="Prior project state was restored"):
        upgrade_project(tmp_path, apply=True)

    assert not (tmp_path / ".rob2" / "rollback.json").exists()


def test_upgrade_does_not_touch_live_assets_until_the_staged_candidate_passes(
    tmp_path: Path, monkeypatch
) -> None:
    bootstrap_project(tmp_path)
    skill = tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md"
    original = skill.read_bytes()
    monkeypatch.setattr(
        harness,
        "_verify_staged_candidate",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("candidate doctor failed")),
    )

    with pytest.raises(HarnessBootstrapError, match="Prior project state was restored"):
        upgrade_project(tmp_path, apply=True)

    assert skill.read_bytes() == original
    assert not (tmp_path / ".rob2" / "rollback.json").exists()


def test_rollback_refuses_incompatible_durable_state(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    upgrade_project(tmp_path, apply=True)
    ledger = tmp_path / ".rob2" / "ledger.sqlite3"
    with sqlite3.connect(ledger) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '99')")

    with pytest.raises(HarnessBootstrapError, match="incompatible with the rollback release"):
        rollback_project(tmp_path, apply=True)


def test_rollback_refuses_ambiguous_owned_content(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    upgrade_project(tmp_path, apply=True)
    skill = tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md"
    skill.write_text("USER EDIT\n", encoding="utf-8")

    with pytest.raises(HarnessBootstrapError, match="owned generated file differs"):
        rollback_project(tmp_path, apply=True)

    assert skill.read_text(encoding="utf-8") == "USER EDIT\n"


def test_lifecycle_refuses_edited_release_lock_metadata(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    upgrade_project(tmp_path, apply=True)
    lock = tmp_path / ".rob2" / "rob2.lock"
    lock.write_text("USER EDIT\n", encoding="utf-8")

    with pytest.raises(HarnessBootstrapError, match="owned release lock differs"):
        rollback_project(tmp_path, apply=True)
    with pytest.raises(HarnessBootstrapError, match="owned release lock differs"):
        uninstall_project(tmp_path, apply=True)

    assert lock.read_text(encoding="utf-8") == "USER EDIT\n"


def test_uninstall_refuses_edited_journal_and_manifest_path_injection(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    journal = tmp_path / ".rob2" / "install-journal.json"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    payload["status"] = "user-edit"
    journal.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HarnessBootstrapError, match="owned install journal differs"):
        uninstall_project(tmp_path, apply=True)

    bootstrap_project(tmp_path)
    note = tmp_path / "notes.txt"
    note.write_text("user note\n", encoding="utf-8")
    manifest_path = tmp_path / "rob2.lock"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["owned_paths"]["notes.txt"] = harness._content_hash(note)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(HarnessBootstrapError, match="unexpected owned path"):
        uninstall_project(tmp_path, apply=True)
    assert note.read_text(encoding="utf-8") == "user note\n"


def test_pending_upgrade_recovers_before_the_next_lifecycle_action(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    backup = harness._write_rollback_backup(tmp_path, manifest)
    candidate_paths = tuple(harness._candidate_owned_source_paths(Path.cwd()))
    harness._write_pending_upgrade(tmp_path, manifest, backup, candidate_paths)
    skill = tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md"
    original = skill.read_bytes()
    skill.unlink()

    preview = upgrade_project(tmp_path)

    assert preview["preview"] is True
    assert skill.read_bytes() == original
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()


def test_pending_recovery_restores_host_files_and_cleans_staged_runtime(tmp_path: Path) -> None:
    codex_path = tmp_path / ".codex" / "config.toml"
    codex_path.parent.mkdir()
    codex_path.write_text("# Codex user setting\n", encoding="utf-8")
    claude_path = tmp_path / ".mcp.json"
    claude_path.write_text('{"mcpServers":{"other":{"command":"keep"}}}\n', encoding="utf-8")
    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    backup = harness._write_rollback_backup(tmp_path, manifest)
    harness._write_pending_upgrade(
        tmp_path, manifest, backup, tuple(harness._candidate_owned_source_paths(Path.cwd()))
    )
    codex_before = codex_path.read_bytes()
    claude_before = claude_path.read_bytes()
    stage = tmp_path / ".rob2" / "runtime-stage-interrupted"
    stage.mkdir()
    (stage / "partial").write_text("stale\n", encoding="utf-8")

    upgrade_project(tmp_path)

    assert codex_path.read_bytes() == codex_before
    assert claude_path.read_bytes() == claude_before
    assert not stage.exists()


def test_pending_recovery_refuses_edited_candidate_content(tmp_path: Path) -> None:
    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    backup = harness._write_rollback_backup(tmp_path, manifest)
    candidate_paths = harness._candidate_owned_source_paths(Path.cwd())
    harness._write_pending_upgrade(
        tmp_path,
        manifest,
        backup,
        tuple(candidate_paths),
        {relative: harness._content_hash(source) for relative, source in candidate_paths.items()},
    )
    skill = tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md"
    skill.write_text("USER EDIT\n", encoding="utf-8")

    with pytest.raises(HarnessBootstrapError, match="interrupted release candidate differs"):
        upgrade_project(tmp_path)

    assert skill.read_text(encoding="utf-8") == "USER EDIT\n"


def test_pending_recovery_refuses_unrelated_host_configuration_edits(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers":{"unrelated":{"command":"keep"}}}\n', encoding="utf-8"
    )
    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    backup = harness._write_rollback_backup(tmp_path, manifest)
    harness._write_pending_upgrade(
        tmp_path, manifest, backup, tuple(harness._candidate_owned_source_paths(Path.cwd()))
    )
    claude = tmp_path / ".mcp.json"
    claude.write_text('{"mcpServers":{"unrelated":{"command":"user-edit"}}}\n', encoding="utf-8")

    with pytest.raises(HarnessBootstrapError, match="interrupted release candidate differs"):
        upgrade_project(tmp_path)

    assert "user-edit" in claude.read_text(encoding="utf-8")


def test_upgrade_and_rollback_replace_both_owned_launcher_entries(
    tmp_path: Path, monkeypatch
) -> None:
    """A changed release launcher is staged, cut over, and restored as one transaction."""

    candidate = _install_switchable_candidate_launcher(monkeypatch)
    bootstrap_project(tmp_path)
    old_codex = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8"))
    old_claude = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    candidate["enabled"] = True

    upgrade_preview = upgrade_project(tmp_path)
    assert {
        ".codex/config.toml:mcp_servers.rob2-kit",
        ".mcp.json:mcpServers.rob2-kit",
    } <= set(upgrade_preview["owned_replacements"])
    assert upgrade_project(tmp_path, apply=True)["status"] == "upgraded"
    record = json.loads((tmp_path / ".rob2" / "rollback.json").read_text(encoding="utf-8"))
    assert not {".codex/config.toml", ".mcp.json"} & set(record["paths"])
    upgraded_codex = tomllib.loads(
        (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    )
    assert upgraded_codex["mcp_servers"]["rob2-kit"]["command"] == "candidate-launcher"
    assert (
        json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["rob2-kit"][
            "command"
        ]
        == "candidate-launcher"
    )

    with (tmp_path / ".codex" / "config.toml").open("a", encoding="utf-8") as handle:
        handle.write('[mcp_servers.unrelated]\ncommand = "keep"\n')
    claude_path = tmp_path / ".mcp.json"
    claude = json.loads(claude_path.read_text(encoding="utf-8"))
    claude["mcpServers"]["unrelated"] = {"command": "keep"}
    claude_path.write_text(json.dumps(claude, indent=2) + "\n", encoding="utf-8")

    rollback_preview = rollback_project(tmp_path)
    assert {
        ".codex/config.toml:mcp_servers.rob2-kit",
        ".mcp.json:mcpServers.rob2-kit",
    } <= set(rollback_preview["owned_replacements"])
    candidate["enabled"] = False
    assert rollback_project(tmp_path, apply=True)["status"] == "rolled_back"
    restored_codex = tomllib.loads(
        (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    )
    assert restored_codex["mcp_servers"]["rob2-kit"] == old_codex["mcp_servers"]["rob2-kit"]
    restored_claude = json.loads(claude_path.read_text(encoding="utf-8"))
    assert restored_claude["mcpServers"]["rob2-kit"] == old_claude["mcpServers"]["rob2-kit"]
    assert restored_codex["mcp_servers"]["unrelated"] == {"command": "keep"}
    assert restored_claude["mcpServers"]["unrelated"] == {"command": "keep"}


def test_interrupted_changed_launcher_cutover_restores_both_host_configs(
    tmp_path: Path, monkeypatch
) -> None:
    """Recovery restores the old host bytes after a launcher-only candidate interruption."""

    candidate = _install_switchable_candidate_launcher(monkeypatch)
    bootstrap_project(tmp_path)
    old_codex = (tmp_path / ".codex" / "config.toml").read_bytes()
    old_claude = (tmp_path / ".mcp.json").read_bytes()
    manifest = harness._load_ownership_manifest(tmp_path)
    backup = harness._write_rollback_backup(tmp_path, manifest)
    paths = harness._candidate_owned_source_paths(Path.cwd())
    harness._write_pending_upgrade(
        tmp_path,
        manifest,
        backup,
        tuple(paths),
        {relative: harness._content_hash(source) for relative, source in paths.items()},
    )
    candidate["enabled"] = True
    harness._apply_candidate_host_configuration(
        tmp_path, manifest, harness.load_release_lock(Path.cwd()), Path.cwd()
    )
    harness._update_pending_candidate_hashes(tmp_path)
    assert b"candidate-launcher" in (tmp_path / ".codex" / "config.toml").read_bytes()

    candidate["enabled"] = False
    assert upgrade_project(tmp_path)["preview"] is True
    assert (tmp_path / ".codex" / "config.toml").read_bytes() == old_codex
    assert (tmp_path / ".mcp.json").read_bytes() == old_claude


def test_failed_rollback_recovers_the_current_release_after_restore(
    tmp_path: Path, monkeypatch
) -> None:
    bootstrap_project(tmp_path)
    upgrade_project(tmp_path, apply=True)
    current_skill = (tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md").read_bytes()

    monkeypatch.setattr(
        harness,
        "_require_current_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HarnessBootstrapError("doctor failed")),
    )

    with pytest.raises(HarnessBootstrapError, match="doctor failed"):
        rollback_project(tmp_path, apply=True)

    assert (tmp_path / ".codex" / "skills" / "rob2-init" / "SKILL.md").read_bytes() == current_skill
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()


def test_incompatible_durable_state_has_exact_schema_diagnosis(tmp_path: Path) -> None:
    ledger = tmp_path / ".rob2" / "ledger.sqlite3"
    ledger.parent.mkdir()
    with sqlite3.connect(ledger) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '99')")

    diagnosis = _check_project_state(tmp_path)

    assert diagnosis == {
        "ok": False,
        "state": "incompatible",
        "expected_schema_version": 1,
        "found_schema_version": "99",
        "recovery": (
            "Preserve .rob2 before changing it.",
            "Use a release that explicitly migrates this schema or archive the state "
            "and start a new Run.",
        ),
    }
