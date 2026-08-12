"""Transactional release cutover contracts for issue #108."""

from __future__ import annotations

import json
import sqlite3
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest

from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    materialize_evidence_context,
)
from rob2_kit.application.evidence_navigation import (
    V3EvidenceNavigationStore,
    new_v3_navigation_state,
)
from rob2_kit.domain.canonical import canonical_hash
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
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import EvidenceReadPolicy, EvidenceSearchPolicy
from rob2_kit.evidence.workflow import V3EvidenceWorkflowState
from rob2_kit.release import ReleaseLock, SKILL_ALLOWED_TOOL_NAMES
from rob2_kit.storage import ArtifactStore, Transition, WorkflowLedger, dependency_fingerprint


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


def _declare_installed_catalog(project: Path, tools: tuple[str, ...]) -> None:
    """Model a prior locked release whose adapter declared a smaller tool catalog."""

    adapter = project / ".rob2" / "adapters" / "codex" / "adapter.json"
    descriptor = json.loads(adapter.read_text(encoding="utf-8"))
    descriptor["allowed_tools"] = list(tools)
    adapter.write_text(json.dumps(descriptor, sort_keys=True) + "\n", encoding="utf-8")

    manifest_path = project / "rob2.lock"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["owned_paths"][".rob2/adapters/codex/adapter.json"] = harness._content_hash(adapter)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")


def _commit_artifact_referencing_state(project: Path) -> None:
    """Create a ledger event whose preflight must read its stored artifact."""

    observed_at = datetime(2026, 8, 12, tzinfo=UTC)
    ledger = WorkflowLedger(
        project / ".rob2" / "ledger.sqlite3",
        ArtifactStore(project / ".rob2" / "artifacts"),
    )
    dependencies = ()
    ledger.commit(
        Transition(
            scope="scope:test",
            operation="operation:test",
            operation_key="operation-key:artifact-stage",
            actor=Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test system"),
            observed_at=observed_at,
            entity_id="entity:test",
            revision_id="revision:test",
            artifact=b'{"artifact":"required"}',
            artifact_media_type="application/json",
            dependencies=dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(dependencies),
            outcome="completed",
        ),
        ledger.acquire_lease("process:artifact-stage", observed_at, timedelta(minutes=5)),
        now=observed_at,
    )


def _seed_active_v3_navigation_state(project: Path) -> Path:
    """Persist one valid active navigation record for lifecycle staging tests."""

    obligation = EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": "sq:lifecycle:v3",
            "propositions": [
                {
                    "id": "proposition:lifecycle:v3",
                    "statement": "Lifecycle V3 state.",
                    "accepted_source_roles": ["primary_report"],
                    "evidence_passes": [
                        {
                            "id": "pass:lifecycle:v3",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": "stage:lifecycle:v3",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:lifecycle:v3",
                                            "kind": "search",
                                            "terms": ["allocation"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "pass:lifecycle:v3:contradiction",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": "stage:lifecycle:v3:contradiction",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:lifecycle:v3:contradiction",
                                            "kind": "search",
                                            "terms": ["allocation"],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )
    context = materialize_evidence_context(
        obligation,
        EvidenceContextInventory(inventory_id="inventory:lifecycle:v3", sources=()),
    )
    search_policy, read_policy = EvidenceSearchPolicy(), EvidenceReadPolicy()
    workflow = V3EvidenceWorkflowState(
        run_id="run:lifecycle:v3",
        result_id="result:lifecycle:v3",
        domain_id="domain:lifecycle:v3",
        question_id=context.question_id,
        snapshot_hash=canonical_hash({"snapshot": "lifecycle:v3"}),
        obligation_revision_id="revision:lifecycle:v3",
        obligation=context.obligation,
        obligation_hash=context.obligation_hash,
        inventory_snapshot_hash=context.inventory_snapshot_hash,
        authorized_inventory=context.authorized_inventory,
        search_policy_id=search_policy.policy_id,
        search_policy_hash=canonical_hash(search_policy),
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
        visual_policy_id="policy:visual:lifecycle:v3",
        visual_policy_hash=canonical_hash({"visual": "lifecycle:v3"}),
        stage_scopes=context.stage_scopes,
    )
    store = V3EvidenceNavigationStore(project)
    store.save(new_v3_navigation_state(workflow=workflow))
    return next(store.root.glob("*.json"))


def test_cutover_exposes_exactly_the_eighteen_canonical_tools() -> None:
    names = tuple(tool.name for tool in anyio.run(create_server().list_tools))

    assert names == CANONICAL_TOOL_NAMES
    assert len(names) == 18
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

    with pytest.raises(HarnessBootstrapError, match="Prior managed state remained unchanged"):
        upgrade_project(tmp_path, apply=True)

    assert skill.read_bytes() == original
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not tuple((tmp_path / ".rob2").glob("release-candidate-*"))


def test_upgrade_stages_artifacts_referenced_by_the_durable_ledger(tmp_path: Path) -> None:
    """Candidate durable-state doctor runs against an isolated complete artifact closure."""

    bootstrap_project(tmp_path)
    _commit_artifact_referencing_state(tmp_path)

    assert upgrade_project(tmp_path, apply=True)["status"] == "upgraded"
    assert not tuple((tmp_path / ".rob2").glob("release-candidate-*"))


def test_upgrade_candidate_preflight_validates_active_v3_navigation_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Candidate doctor rejects malformed copied active V3 navigation, not retired storage."""

    bootstrap_project(tmp_path)
    _seed_active_v3_navigation_state(tmp_path)
    original_stage = harness._stage_candidate_generation

    def stage_with_corrupted_v3_state(*args: object) -> Path:
        stage = original_stage(*args)
        next((stage / ".rob2" / "evidence-navigation-v3").glob("*.json")).write_text(
            "{", encoding="utf-8"
        )
        return stage

    monkeypatch.setattr(harness, "_stage_candidate_generation", stage_with_corrupted_v3_state)

    with pytest.raises(HarnessBootstrapError, match="candidate durable-state check failed") as error:
        upgrade_project(tmp_path, apply=True)

    assert "active v3 evidence-navigation state" in str(error.value).lower()
    assert not tuple((tmp_path / ".rob2").glob("release-candidate-*"))


def test_candidate_sqlite_snapshot_includes_committed_wal_content(tmp_path: Path) -> None:
    """Candidate durable state uses SQLite backup, not an inconsistent main-file copy."""

    source = tmp_path / ".rob2" / "evidence.sqlite3"
    source.parent.mkdir()
    with sqlite3.connect(source) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE staged_snapshot (value TEXT NOT NULL)")
        connection.execute("INSERT INTO staged_snapshot VALUES ('committed in wal')")
        connection.commit()
        assert source.with_name(f"{source.name}-wal").is_file()

        stage = tmp_path / ".rob2" / "release-candidate-snapshot"
        stage.mkdir()
        harness._stage_candidate_durable_state(tmp_path, stage)

        staged = stage / ".rob2" / "evidence.sqlite3"
        assert not staged.with_name(f"{staged.name}-wal").exists()
        assert not staged.with_name(f"{staged.name}-shm").exists()
        with sqlite3.connect(staged) as snapshot:
            assert snapshot.execute("SELECT value FROM staged_snapshot").fetchone() == (
                "committed in wal",
            )


def test_upgrade_reports_a_locked_pre_mutation_candidate_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed candidate doctor must not hide a stage it could not remove."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-locked"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(
        harness,
        "_verify_staged_candidate",
        lambda *_args: (_ for _ in ()).throw(HarnessBootstrapError("candidate doctor failed")),
    )
    monkeypatch.setattr(
        harness,
        "_cleanup_candidate_stage",
        lambda *_args: (_ for _ in ()).throw(PermissionError("candidate stage is locked")),
    )

    with pytest.raises(HarnessBootstrapError, match="candidate doctor failed") as error:
        upgrade_project(tmp_path, apply=True)

    message = str(error.value).lower()
    assert "candidate-stage cleanup remains" in message
    assert "candidate stage is locked" in message
    assert stage.is_dir()
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not (tmp_path / ".rob2" / "install.lock").exists()


def test_upgrade_accepts_a_prior_runtime_catalog_declared_by_its_installed_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate must not judge an installed release by its newer tool contract."""

    bootstrap_project(tmp_path)
    prior_tools = SKILL_ALLOWED_TOOL_NAMES[:-1]
    _declare_installed_catalog(tmp_path, prior_tools)
    (tmp_path / ".rob2" / "runtime" / ".venv").mkdir(parents=True)
    assert upgrade_project(tmp_path)["state_compatibility"]["ok"] is True
    monkeypatch.setattr(harness, "inspect_mcp_tool_inventory", lambda *_args, **_kwargs: prior_tools)
    staged: list[Path] = []

    def reached_candidate_stage(*args: object, **_kwargs: object) -> Path:
        staged.append(args[0])
        raise RuntimeError("candidate stage reached")

    monkeypatch.setattr(harness, "_stage_candidate_generation", reached_candidate_stage)

    with pytest.raises(HarnessBootstrapError, match="candidate stage reached"):
        upgrade_project(tmp_path, apply=True)

    assert staged == [tmp_path]


def test_upgrade_pre_mutation_failure_does_not_rewrite_a_locked_runtime_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-cutover error must leave the immutable snapshot untouched."""

    bootstrap_project(tmp_path)
    locked_binary = tmp_path / ".rob2" / "runtime" / ".venv" / "locked.pyd"
    locked_binary.parent.mkdir(parents=True, exist_ok=True)
    locked_binary.write_bytes(b"locked runtime binary")
    monkeypatch.setattr(
        harness,
        "_require_current_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HarnessBootstrapError("pre-mutation fault")),
    )
    original_write_bytes = Path.write_bytes
    attempts: list[Path] = []

    def reject_locked_write(path: Path, data: bytes) -> int:
        if path == locked_binary:
            attempts.append(path)
            raise PermissionError("simulated locked runtime binary")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", reject_locked_write)

    with pytest.raises(HarnessBootstrapError, match="pre-mutation fault") as error:
        upgrade_project(tmp_path, apply=True)

    assert "prior managed state remained unchanged" in str(error.value).lower()
    assert attempts == []


def test_upgrade_incomplete_pending_receipt_preserves_its_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first managed receipt is removed directly when its write never completed."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    restores: list[object] = []
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(harness, "_restore_managed_state", lambda *_args: restores.append(object()))

    def fail_pending(root: Path, *_args: object, **_kwargs: object) -> None:
        harness._pending_transaction_path(root).write_text("{", encoding="utf-8")
        raise OSError("pending receipt failure")

    monkeypatch.setattr(harness, "_write_pending_upgrade", fail_pending)

    with pytest.raises(HarnessBootstrapError, match="pending receipt failure"):
        upgrade_project(tmp_path, apply=True)

    assert restores == []
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not stage.exists()
    assert not tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))


def test_upgrade_incomplete_pending_unlink_failure_retains_its_private_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retained incomplete receipt must retain the backup it still references."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)

    def fail_pending(root: Path, *_args: object, **_kwargs: object) -> None:
        harness._pending_transaction_path(root).write_text("{", encoding="utf-8")
        raise OSError("pending receipt failure")

    monkeypatch.setattr(harness, "_write_pending_upgrade", fail_pending)
    pending = tmp_path / ".rob2" / "pending-release-transaction.json"
    original_unlink = Path.unlink

    def retain_pending(path: Path, *args: object, **kwargs: object) -> None:
        if path == pending:
            raise OSError("pending receipt is locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", retain_pending)

    with pytest.raises(HarnessBootstrapError, match="Incomplete transaction receipt remains") as error:
        upgrade_project(tmp_path, apply=True)

    assert "pending receipt is locked" in str(error.value)
    assert pending.is_file()
    assert tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))
    assert not stage.exists()


def test_upgrade_pending_write_failure_before_receipt_cleans_private_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt that was never created must not retain its private backup."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "_write_pending_upgrade",
        lambda *_args: (_ for _ in ()).throw(OSError("pending write failed before receipt")),
    )

    with pytest.raises(HarnessBootstrapError, match="pending write failed before receipt") as error:
        upgrade_project(tmp_path, apply=True)

    assert "incomplete transaction receipt remains" not in str(error.value).lower()
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))
    assert not stage.exists()


def test_interrupted_recovery_retries_after_pending_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt remains retryable when recovery cannot consume it yet."""

    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    harness._begin_recoverable_lifecycle(tmp_path, manifest)
    pending = tmp_path / ".rob2" / "pending-release-transaction.json"
    journal = tmp_path / ".rob2" / "install-journal.json"
    original_journal = journal.read_bytes()
    original_unlink = Path.unlink
    failed = False

    def fail_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if path == pending and not failed:
            failed = True
            raise OSError("pending unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    with pytest.raises(OSError, match="pending unlink failure"):
        harness._recover_interrupted_upgrade(tmp_path)

    assert pending.is_file()
    assert journal.read_bytes() == original_journal
    monkeypatch.setattr(Path, "unlink", original_unlink)
    harness._recover_interrupted_upgrade(tmp_path)
    assert not pending.exists()
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "upgrade_rollback_succeeded"


def test_interrupted_recovery_restores_pending_after_atomic_journal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed rollback-success receipt publication leaves recovery retryable."""

    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    harness._begin_recoverable_lifecycle(tmp_path, manifest)
    pending = tmp_path / ".rob2" / "pending-release-transaction.json"
    journal = tmp_path / ".rob2" / "install-journal.json"
    original_journal = journal.read_bytes()
    original_replace = harness.os.replace

    def fail_journal_replace(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == journal:
            raise OSError("rollback journal replacement failed")
        original_replace(source, destination)

    monkeypatch.setattr(harness.os, "replace", fail_journal_replace)

    with pytest.raises(OSError, match="rollback journal replacement failed"):
        harness._recover_interrupted_upgrade(tmp_path)

    assert pending.is_file()
    assert journal.read_bytes() == original_journal
    assert tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))
    monkeypatch.setattr(harness.os, "replace", original_replace)
    harness._recover_interrupted_upgrade(tmp_path)
    assert not pending.exists()
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "upgrade_rollback_succeeded"


def test_upgrade_surfaces_successful_mutex_release_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful cutover is not reported as success while its mutex remains."""

    bootstrap_project(tmp_path)
    monkeypatch.setattr(
        harness,
        "_release_install_mutex",
        lambda *_args: (_ for _ in ()).throw(OSError("mutex release failure")),
    )

    with pytest.raises(HarnessBootstrapError, match="installation mutex could not be released"):
        upgrade_project(tmp_path, apply=True)

    assert (tmp_path / ".rob2" / "install.lock").is_file()


def test_upgrade_preserves_original_failure_when_mutex_release_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release error cannot replace the transaction error already in flight."""

    bootstrap_project(tmp_path)
    monkeypatch.setattr(
        harness,
        "_require_current_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HarnessBootstrapError("transaction fault")),
    )
    monkeypatch.setattr(
        harness,
        "_release_install_mutex",
        lambda *_args: (_ for _ in ()).throw(OSError("mutex release failure")),
    )

    with pytest.raises(HarnessBootstrapError, match="transaction fault") as error:
        upgrade_project(tmp_path, apply=True)

    assert "mutex could not be released" not in str(error.value)


def test_upgrade_journal_receipt_failure_keeps_recovery_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable pending receipt drives cleanup even when the next journal write fails."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "_write_journal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("journal receipt failure")),
    )

    with pytest.raises(HarnessBootstrapError, match="journal receipt failure") as error:
        upgrade_project(tmp_path, apply=True)

    assert "recovery remains pending" in str(error.value).lower()
    assert (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not stage.exists()
    assert tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))


def test_upgrade_rollback_receipt_failure_recovers_without_masking_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed rollback receipt leaves no dangling durable transaction."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "_write_rollback_record",
        lambda *_args: (_ for _ in ()).throw(OSError("rollback receipt failure")),
    )

    with pytest.raises(HarnessBootstrapError, match="rollback receipt failure") as error:
        upgrade_project(tmp_path, apply=True)

    assert "prior project state was restored" in str(error.value).lower()
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not stage.exists()
    assert not tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))


def test_rollback_backup_failure_discards_its_private_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed private backup cannot leave an attempt directory for later recovery."""

    bootstrap_project(tmp_path)
    manifest = harness._load_ownership_manifest(tmp_path)
    monkeypatch.setattr(
        harness.shutil,
        "copyfile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("backup copy failure")),
    )

    with pytest.raises(OSError, match="backup copy failure"):
        harness._write_rollback_backup(tmp_path, manifest)

    rollback_root = tmp_path / ".rob2" / "release-rollbacks"
    assert not tuple(rollback_root.glob("*"))


def test_upgrade_keeps_pending_receipt_until_candidate_stage_cleanup_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final-stage cleanup failure must still enter recovery with its receipt."""

    candidate = _install_switchable_candidate_launcher(monkeypatch)
    bootstrap_project(tmp_path)
    old_codex = (tmp_path / ".codex" / "config.toml").read_bytes()
    old_claude = (tmp_path / ".mcp.json").read_bytes()
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    candidate["enabled"] = True
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(harness, "_verify_candidate_install", lambda *_args: None)
    monkeypatch.setattr(harness, "_refresh_candidate_assets", lambda *_args: None)

    original_recover = harness._recover_interrupted_upgrade
    pending_at_recovery: list[bool] = []

    def observe_recovery(root: Path, **kwargs: object) -> None:
        pending_at_recovery.append(
            (root / ".rob2" / "pending-release-transaction.json").exists()
        )
        original_recover(root, **kwargs)

    monkeypatch.setattr(harness, "_recover_interrupted_upgrade", observe_recovery)
    original_cleanup = harness._cleanup_candidate_stage
    cleanup_calls = 0

    def fail_first_cleanup(candidate_stage: Path | None) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError("candidate stage cleanup failure")
        original_cleanup(candidate_stage)

    monkeypatch.setattr(harness, "_cleanup_candidate_stage", fail_first_cleanup)

    with pytest.raises(HarnessBootstrapError, match="candidate stage cleanup failure"):
        upgrade_project(tmp_path, apply=True)

    assert pending_at_recovery == [False, True]
    assert (tmp_path / ".codex" / "config.toml").read_bytes() == old_codex
    assert (tmp_path / ".mcp.json").read_bytes() == old_claude
    assert not (tmp_path / ".rob2" / "pending-release-transaction.json").exists()
    assert not (tmp_path / ".rob2" / "rollback.json").exists()
    assert not stage.exists()


def test_upgrade_reports_pending_recovery_when_durable_recovery_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed recovery must retain its durable receipt and report uncertainty."""

    bootstrap_project(tmp_path)
    stage = tmp_path / ".rob2" / "release-candidate-test"
    stage.mkdir()
    monkeypatch.setattr(harness, "_stage_candidate_generation", lambda *_args: stage)
    monkeypatch.setattr(harness, "_verify_staged_candidate", lambda *_args: None)
    monkeypatch.setattr(harness, "_require_complete_doctor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "_write_rollback_record",
        lambda *_args: (_ for _ in ()).throw(OSError("transaction fault")),
    )
    original_recover = harness._recover_interrupted_upgrade

    def fail_durable_recovery(root: Path, **kwargs: object) -> None:
        if (root / ".rob2" / "pending-release-transaction.json").exists():
            raise OSError("recovery fault")
        original_recover(root, **kwargs)

    monkeypatch.setattr(
        harness,
        "_recover_interrupted_upgrade",
        fail_durable_recovery,
    )

    with pytest.raises(HarnessBootstrapError, match="transaction fault") as error:
        upgrade_project(tmp_path, apply=True)

    message = str(error.value).lower()
    assert "recovery remains pending" in message
    assert "recovery fault" in message
    assert "prior project state was restored" not in message
    assert "before cutover" not in message
    assert (tmp_path / ".rob2" / "pending-release-transaction.json").is_file()
    assert tuple((tmp_path / ".rob2" / "release-rollbacks").glob("*"))


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
