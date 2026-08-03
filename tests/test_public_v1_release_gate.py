import json
from pathlib import Path

import pytest

from rob2_kit.release_gate import ReleaseGateError, load_release_gate

ROOT = Path(__file__).resolve().parents[1]


def test_every_public_v1_blocker_has_owned_evidence() -> None:
    gate = load_release_gate(ROOT)

    assert set(gate.blockers) == {
        "logic",
        "result-identity",
        "evidence",
        "static-reports",
        "resume-invalidation",
        "failure-isolation",
        "typed-mcp",
        "package-archives",
        "frozen-wheel-qualification",
        "security",
    }
    assert all(blocker.evidence for blocker in gate.blockers.values())
    assert all(
        manual_check.owner and manual_check.evidence_slot
        for blocker in gate.blockers.values()
        for manual_check in blocker.manual_checks
    )


def test_release_gate_uses_only_distributable_fixtures() -> None:
    gate = load_release_gate(ROOT)

    fixture_kinds = {fixture.kind for fixture in gate.fixtures.values()}
    assert {
        "born-digital",
        "compound-protocol-sap",
        "multiple-results",
        "normalized-host-submissions",
    } <= fixture_kinds
    assert all(fixture.path.is_file() for fixture in gate.fixtures.values())
    assert all(
        "eval/reference" not in fixture.path.as_posix() for fixture in gate.fixtures.values()
    )


def test_distributable_fixture_contracts_are_executable() -> None:
    gate = load_release_gate(ROOT)
    loaded = {fixture.kind: fixture.path.read_bytes() for fixture in gate.fixtures.values()}

    assert all(content for content in loaded.values())
    assert loaded["compound-protocol-sap"].startswith(b"%PDF-")
    assert loaded["compound-protocol-sap"].count(b"/Type /Page") >= 2
    assert b"PROTOCOL" in loaded["compound-protocol-sap"]
    assert b"STATISTICAL ANALYSIS PLAN" in loaded["compound-protocol-sap"]
    host_submissions = json.loads(loaded["normalized-host-submissions"])
    assert host_submissions["codex"] == host_submissions["claude"]


def test_release_gate_rejects_private_or_provisional_artifacts(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_gate.py").write_text(
        "def test_logic() -> None:\n    pass\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "release-gate.toml"
    manifest.write_text(
        """
version = 1

[[fixtures]]
id = "private"
kind = "born-digital"
path = "eval/reference/sources/private.pdf"
description = "Provisional reference label used as a correctness oracle"
evidence = "tests/test_gate.py::test_logic"

[[blockers]]
id = "logic"
description = "Logic"
evidence = ["tests/test_gate.py::test_logic"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ReleaseGateError, match="private|Provisional"):
        load_release_gate(tmp_path)


def test_ci_runs_the_same_release_gate_on_all_supported_platforms() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert 'python-version: ["3.13"]' in workflow
    assert "matrix.os" in workflow
    assert "uv sync --frozen --all-groups" in workflow
    assert "python -m rob2_kit.release_gate" in workflow
    assert "uv run --frozen pytest" in workflow
    assert "uv build --wheel" in workflow
    assert "scripts/release_qualification.py" in workflow
    assert "upload-artifact" in workflow
    assert "compare-qualification-receipts" in workflow
