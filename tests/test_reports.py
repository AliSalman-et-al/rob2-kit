from pathlib import Path

import pytest
from test_finish import _completed_workspace, _finish

from rob2_kit.reports import export_trial
from rob2_kit.sources import sha256_bytes


def _tree(path: Path) -> dict[Path, bytes]:
    return {item.relative_to(path): item.read_bytes() for item in path.rglob("*") if item.is_file()}


def test_export_is_standalone_deterministic_and_uses_committed_bytes(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    finished = _finish(workspace)
    assert finished.status == "saved"
    first = export_trial(workspace, "t", "r")
    initial = {
        path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()
    }
    second = export_trial(workspace, "t", "r")
    assert initial == {
        path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()
    }
    assert initial[Path("assessment.json")]
    assert b"<mark>random</mark>" in initial[Path("report.html")]
    copied = next((second / "sources").iterdir())
    assert sha256_bytes(copied.read_bytes()) == finished.snapshot.sources[0].sha256


def test_export_promotion_failure_restores_existing_bundle(tmp_path: Path, monkeypatch) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    _finish(workspace)
    target = export_trial(workspace, "t", "r")
    original = _tree(target)
    real_replace = Path.replace

    def fail_stage_promotion(self: Path, other: Path) -> Path:
        if "-stage-" in self.name and other.name == "t":
            raise OSError("injected promotion failure")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", fail_stage_promotion)
    with pytest.raises(OSError, match="promotion"):
        export_trial(workspace, "t", "r")
    assert original == _tree(target)
    parent = target.parent
    assert not list(parent.glob(".t-stage-*")) and not (parent / ".t-backup").exists()
    monkeypatch.setattr(Path, "replace", real_replace)
    assert export_trial(workspace, "t", "r") == target


def test_export_backup_failure_leaves_existing_bundle_intact(tmp_path: Path, monkeypatch) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    _finish(workspace)
    target = export_trial(workspace, "t", "r")
    original = _tree(target)
    real_replace = Path.replace

    def fail_backup(self: Path, other: Path) -> Path:
        if self == target and other.name == ".t-backup":
            raise OSError("injected backup failure")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", fail_backup)
    with pytest.raises(OSError, match="backup"):
        export_trial(workspace, "t", "r")
    assert original == _tree(target)


def test_export_recovers_post_promotion_and_missing_target_backup_residue(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    _finish(workspace)
    target = export_trial(workspace, "t", "r")
    original = _tree(target)
    backup = target.parent / ".t-backup"
    target.replace(backup)
    backup.replace(target)
    backup.mkdir()
    (backup / "junk").write_text("old")
    assert _tree(export_trial(workspace, "t", "r")) == original
    target.replace(backup)
    assert _tree(export_trial(workspace, "t", "r")) == original


def test_export_invalid_residue_fails_closed_and_preserves_it(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    _finish(workspace)
    target = export_trial(workspace, "t", "r")
    backup = target.parent / ".t-backup"
    backup.mkdir()
    (backup / "bad").write_text("bad")
    (target / "assessment.json").write_text("bad")
    with pytest.raises(ValueError, match="residue"):
        export_trial(workspace, "t", "r")
    assert backup.exists() and target.exists()


def test_export_recovers_tempfile_style_underscore_stage_suffix(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    _finish(workspace)
    target = export_trial(workspace, "t", "r")
    residue = target.parent / ".t-stage-ab_cd"
    residue.mkdir()
    (residue / "partial").write_text("discardable")
    assert export_trial(workspace, "t", "r") == target
    assert not residue.exists()
