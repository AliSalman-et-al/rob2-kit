import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from test_judgments import _save, approved_workspace

from rob2_kit.batch import ApprovedBatch, Problem, StaleBatch, current_batch
from rob2_kit.finish import finish_trial
from rob2_kit.judgment_models import DomainJudgment
from rob2_kit.judgments import checkpoint_content
from rob2_kit.models import Judgment, canonical_json_bytes, sha256
from rob2_kit.recovery import DiscardActiveBatchRequest, discard_active_batch, recovery_progress
from rob2_kit.reports import export_trial
from rob2_kit.storage import WorkspaceLock, WorkspaceLockedError, save_state


def _discard(workspace: Path, *, expected_frozen_hash: str | None = None):
    state = current_batch(workspace)
    frozen = state.approved if isinstance(state, StaleBatch) else state
    assert isinstance(frozen, ApprovedBatch)
    return discard_active_batch(
        workspace,
        DiscardActiveBatchRequest(
            expected_frozen_hash=expected_frozen_hash or frozen.frozen_hash,
            confirmation="I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH",
            actor="researcher",
            observed_at=datetime(2026, 8, 14, tzinfo=UTC),
            reason="The researcher explicitly requested this discard.",
        ),
    )


def test_progress_is_derived_from_approved_durable_records(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    initial = recovery_progress(workspace)
    assert initial.status == "approved"
    assert initial.trials[0].status == "pending"
    assert len(initial.trials[0].pending_domains) == 5


def test_discard_removes_only_unfinished_runtime_database(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    (workspace / "outputs").mkdir()
    (workspace / "outputs" / "done.txt").write_text("done")
    result = _discard(workspace)
    assert result.status == "discarded"
    assert (workspace / "outputs" / "done.txt").read_text() == "done"
    assert recovery_progress(workspace).status == "no_active"


def test_discard_holds_workspace_mutation_lock_until_runtime_files_are_removed(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, _ = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    replacement_proposal = approved.proposal.model_copy(
        update={
            "request": approved.proposal.request.model_copy(
                update={
                    "outcome_target": approved.proposal.request.outcome_target.model_copy(
                        update={"label": "Replacement"}
                    )
                }
            )
        }
    )
    replacement = approved.model_copy(
        update={
            "proposal": replacement_proposal,
            "frozen_hash": sha256(
                {"proposal": replacement_proposal, "packs": approved.pack_identities}
            ),
        }
    )
    attempted = threading.Event()
    release_competitor = threading.Event()
    replaced = threading.Event()

    def replace_with_b() -> None:
        release_competitor.wait(timeout=5)
        attempted.set()
        save_state(workspace, canonical_json_bytes(replacement))
        replaced.set()

    thread = threading.Thread(target=replace_with_b)
    thread.start()
    import rob2_kit.recovery as recovery

    def old_race_hook(root: Path, state: ApprovedBatch) -> None:
        release_competitor.set()
        assert attempted.wait(timeout=5)
        assert not replaced.wait(timeout=0.2)

    monkeypatch.setattr(recovery, "_preserve_frozen_assessments", old_race_hook)
    try:
        assert _discard(workspace).status == "discarded"
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        release_competitor.set()
        thread.join(timeout=5)
    assert replaced.is_set()
    assert current_batch(workspace) == replacement


def test_recovery_rejects_self_hashed_checkpoint_with_changed_logic(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    assert _save(workspace, source).status == "saved"
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    key = f"domain_judgment:{approved.frozen_hash}:t:r:domain:randomization"
    with sqlite3.connect(workspace / ".rob2-kit" / "active-batch.sqlite3") as connection:
        raw = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()[0]
        judgment = DomainJudgment.model_validate_json(bytes(raw)).model_copy(
            update={"proposed_judgment": Judgment.HIGH}
        )
        judgment = judgment.model_copy(
            update={"checkpoint_hash": sha256(checkpoint_content(judgment))}
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?", (judgment.model_dump_json(), key)
        )
    progress = recovery_progress(workspace)
    assert progress.status == "stale"
    assert progress.problems[0].code == "corrupt_active_batch"


def test_discard_preserves_exporter_residues(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    residue = workspace / ".rob2-kit" / "assessments" / ".trial-backup"
    residue.mkdir(parents=True)
    (residue / "keep.txt").write_text("published")
    assert _discard(workspace).status == "discarded"
    assert (residue / "keep.txt").read_text() == "published"


def test_discard_recovers_completed_assessment_backup_before_removing_database(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    for domain in (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    ):
        assert _save(workspace, source, domain).status == "saved"
    assert (
        finish_trial(
            workspace, "t", None, None, None, (), "actor", datetime(2026, 8, 14, tzinfo=UTC)
        ).status
        == "saved"
    )
    target = export_trial(workspace, "t", "r")
    backup = target.parent / ".t-backup"
    target.replace(backup)
    assert not target.exists() and backup.exists()
    assert _discard(workspace).status == "discarded"
    assert target.is_dir() and not backup.exists()


def test_tampered_terminal_makes_recovery_corrupt(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    key = f"terminal_trial:{approved.frozen_hash}:t"
    with sqlite3.connect(workspace / ".rob2-kit" / "active-batch.sqlite3") as connection:
        connection.execute("INSERT INTO records(name,payload) VALUES(?,?)", (key, b'{"bad":true}'))
    assert recovery_progress(workspace).problems[0].code == "corrupt_active_batch"


def test_discard_move_failure_restores_every_runtime_file(tmp_path: Path, monkeypatch) -> None:
    workspace, _ = approved_workspace(tmp_path)
    internal = workspace / ".rob2-kit"
    files = (
        internal / "active-batch.sqlite3",
        internal / "active-batch.sqlite3-wal",
        internal / "active-batch.sqlite3-shm",
    )
    connection = sqlite3.connect(files[0])
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("INSERT INTO records(name,payload) VALUES('discard-test',x'00')")
    connection.commit()
    assert all(item.exists() for item in files)
    before = {item.name: item.read_bytes() for item in files}
    replace = Path.replace
    calls = 0

    def fail_second(path: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected move failure")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_second)
    try:
        result = _discard(workspace)
        assert result.status == "condition" and result.code == "discard_move_failed"
        assert before[files[0].name] == files[0].read_bytes()
        assert before[files[1].name] == files[1].read_bytes()
        # SQLite may update shared-memory reader marks while inspecting the DB;
        # it must remain present, but those volatile bytes are not user data.
        assert files[2].exists()
        assert not list(internal.glob(".discard-trash-*"))
    finally:
        connection.close()


def test_expected_source_or_pack_staleness_remains_discardable(tmp_path: Path, monkeypatch) -> None:
    workspace, source = approved_workspace(tmp_path)
    (workspace / "outputs").mkdir()
    (workspace / "outputs" / "done").write_text("keep")
    (workspace / source.captured_path).write_bytes(b"changed")
    stale = recovery_progress(workspace)
    assert stale.status == "stale" and stale.problems[0].code != "corrupt_active_batch"
    assert _discard(workspace).status == "discarded"
    assert recovery_progress(workspace).status == "no_active"
    assert (workspace / "outputs" / "done").read_text() == "keep"

    other_root = tmp_path / "pack"
    other_root.mkdir()
    other, _ = approved_workspace(other_root)
    import rob2_kit.recovery as recovery

    original = recovery.current_batch_in_transaction

    def pack_stale(root, connection):
        state = original(root, connection)
        assert isinstance(state, ApprovedBatch)
        return StaleBatch(
            approved=state,
            problems=(Problem(code="pack_identity_changed", detail="test"),),
        )

    monkeypatch.setattr(recovery, "current_batch_in_transaction", pack_stale)
    assert recovery_progress(other).problems[0].code == "pack_identity_changed"
    assert _discard(other).status == "discarded"


def test_stale_frozen_assessment_is_materialized_before_discard(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, source = approved_workspace(tmp_path)
    for domain in (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    ):
        assert _save(workspace, source, domain).status == "saved"
    assert (
        finish_trial(
            workspace, "t", None, None, None, (), "actor", datetime(2026, 8, 14, tzinfo=UTC)
        ).status
        == "saved"
    )
    import rob2_kit.recovery as recovery

    original = recovery.current_batch_in_transaction

    def pack_stale(root, connection):
        value = original(root, connection)
        assert isinstance(value, ApprovedBatch)
        return StaleBatch(
            approved=value, problems=(Problem(code="pack_identity_changed", detail="test"),)
        )

    monkeypatch.setattr(recovery, "current_batch_in_transaction", pack_stale)
    assert _discard(workspace).status == "discarded"
    target = workspace / ".rob2-kit" / "assessments" / "t"
    assert (target / "assessment.json").is_file() and (target / "report.html").is_file()
    monkeypatch.undo()
    assert recovery_progress(workspace).status == "no_active"


def test_workspace_lock_is_exclusive_across_processes_and_releases(tmp_path: Path) -> None:
    script = "\n".join(
        (
            "from rob2_kit.storage import WorkspaceLock",
            "import sys, time",
            "with WorkspaceLock(sys.argv[1]):",
            "    print('ready', flush=True)",
            "    time.sleep(1.5)",
        )
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    assert holder.stdout is not None and holder.stdout.readline().strip() == "ready"
    try:
        try:
            with WorkspaceLock(tmp_path):
                raise AssertionError("contender acquired holder lock")
        except WorkspaceLockedError:
            pass
    finally:
        holder.wait(timeout=5)
    with WorkspaceLock(tmp_path):
        pass


def test_workspace_lock_rejects_redirected_lock_path(tmp_path: Path) -> None:
    internal = tmp_path / ".rob2-kit"
    internal.mkdir()
    target = tmp_path / "outside.lock"
    target.write_text("x")
    try:
        (internal / "server.lock").symlink_to(target)
    except OSError:
        return
    import pytest

    with pytest.raises(ValueError, match="redirected"):
        WorkspaceLock(tmp_path)
