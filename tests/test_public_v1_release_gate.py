import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from rob2_kit.ingestion.project import BoundedZipError, read_bounded_zip
from rob2_kit.release_gate import ReleaseGateError, load_release_gate

ROOT = Path(__file__).resolve().parents[1]


def test_every_public_v1_blocker_has_owned_evidence() -> None:
    gate = load_release_gate(ROOT)

    assert set(gate.blockers) == {
        "logic",
        "result-identity",
        "evidence",
        "adversarial-rendering",
        "resume-invalidation",
        "failure-isolation",
        "cross-host-equivalence",
        "human-sign-off",
        "gui-accessibility",
        "security-boundaries",
        "package-archives",
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
        "scanned",
        "sparse",
        "blank",
        "garbled",
        "table",
        "flowchart",
        "parse-render-discrepant",
        "compound-protocol-sap",
        "missing-required",
        "corrupt-required",
        "failed-optional",
        "source-conflict",
        "ambiguous-denominator",
        "visible-prompt-injection",
        "hidden-prompt-injection",
        "hostile-markup",
        "hostile-unicode-metadata",
        "malformed-pdf",
        "path-attack",
        "container-attack",
        "multiple-results",
        "reuse-cases",
        "workflow-edge-cases",
        "normalized-host-submissions",
    } <= fixture_kinds
    assert all(fixture.path.is_file() for fixture in gate.fixtures.values())
    assert all(
        "eval/reference" not in fixture.path.as_posix()
        for fixture in gate.fixtures.values()
    )


def test_distributable_fixture_contracts_are_executable() -> None:
    gate = load_release_gate(ROOT)
    loaded = {
        fixture.kind: fixture.path.read_bytes()
        for fixture in gate.fixtures.values()
    }

    assert all(content for content in loaded.values())
    assert loaded["compound-protocol-sap"].startswith(b"%PDF-")
    assert loaded["compound-protocol-sap"].count(b"/Type /Page") >= 2
    assert b"PROTOCOL" in loaded["compound-protocol-sap"]
    assert b"STATISTICAL ANALYSIS PLAN" in loaded["compound-protocol-sap"]
    assert loaded["malformed-pdf"].startswith(b"%PDF-")
    assert b"%%EOF" not in loaded["malformed-pdf"]
    assert not loaded["corrupt-required"].startswith(b"%PDF-")

    path_attack = json.loads(loaded["path-attack"])
    for member in path_attack["members"]:
        container = BytesIO()
        with ZipFile(container, "w") as archive:
            archive.writestr(member, b"unsafe")
        with pytest.raises(BoundedZipError, match="unsafe"):
            read_bounded_zip(container.getvalue())

    container_attack = json.loads(loaded["container-attack"])
    container = BytesIO()
    with ZipFile(container, "w", ZIP_DEFLATED) as archive:
        archive.writestr("one.pdf", b"expanded")
    with pytest.raises(BoundedZipError, match="member-count"):
        read_bounded_zip(
            container.getvalue(),
            max_members=min(0, container_attack["member_count"] - 1),
        )
    with pytest.raises(BoundedZipError, match="expanded-size"):
        read_bounded_zip(
            container.getvalue(),
            max_expanded_bytes=min(1, container_attack["expanded_bytes"] - 1),
        )

    edge_cases = json.loads(loaded["workflow-edge-cases"])["cases"]
    assert {
        "interruption-before-commit",
        "interruption-after-commit",
        "host-disconnection",
        "stale-gui-action",
        "duplicate-submission",
        "targeted-invalidation",
        "archive-verification",
    } == set(edge_cases)
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
    assert "python -m rob2_kit.release_gate" in workflow
    assert "uv run --frozen pytest" in workflow
    assert "uv build --wheel" in workflow
