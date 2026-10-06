"""A stale wheel must never satisfy the release artifact check."""

from pathlib import Path

import pytest

from scripts.build_release_wheel import build_release_wheel


def test_stale_wheel_is_ignored_and_only_fresh_current_artifact_is_verified(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="rob2-kit"\nversion="0.11.0"\n')
    (tmp_path / "dist").mkdir()
    stale = tmp_path / "dist/rob2_kit-0.10.0-py3-none-any.whl"
    stale.write_bytes(b"old artifact")
    commands = []

    def run(command, *, cwd, check):
        assert cwd == tmp_path and check
        commands.append(command)
        if command[1] == "build":
            output = Path(command[-1])
            (output / "rob2_kit-0.11.0-py3-none-any.whl").write_bytes(b"new artifact")

    monkeypatch.setattr("scripts.build_release_wheel.subprocess.run", run)
    wheel = build_release_wheel(tmp_path)
    assert wheel.read_bytes() == b"new artifact" and stale.read_bytes() == b"old artifact"
    assert commands[-1][-1] == str(wheel)
    assert wheel.parent != stale.parent


def test_wrong_version_from_fresh_build_is_rejected_before_verification(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="rob2-kit"\nversion="0.11.0"\n')
    commands = []

    def run(command, *, cwd, check):
        commands.append(command)
        (Path(command[-1]) / "rob2_kit-0.10.0-py3-none-any.whl").write_bytes(b"wrong")

    monkeypatch.setattr("scripts.build_release_wheel.subprocess.run", run)
    with pytest.raises(ValueError, match="current project wheel"):
        build_release_wheel(tmp_path)
    assert len(commands) == 1
