"""Human-facing journey documentation contracts for issue #109."""

from __future__ import annotations

import shutil
from pathlib import Path

import anyio
import pytest

from rob2_kit.interfaces.mcp.server import create_server
from rob2_kit.release import validate_documentation_contract

ROOT = Path(__file__).resolve().parents[1]


def test_journey_docs_cover_installation_workflow_recovery_and_evaluation() -> None:
    """The shipped guide is a practical journey, not a tool-schema reference."""

    validate_documentation_contract(ROOT)

    journey = (ROOT / "docs" / "USER-JOURNEY.md").read_text(encoding="utf-8")
    for topic in (
        "Codex",
        "Claude Code",
        "one Trial",
        "many Trials",
        "synonym",
        "time point",
        "optional",
        "resume",
        "start a new",
        "immutable",
        "audit",
        "troubleshoot",
    ):
        assert topic.casefold() in journey.casefold()

    runbook = (ROOT / "docs" / "LOCAL-RUNBOOK.md").read_text(encoding="utf-8")
    assert "not CI" in runbook
    assert "not a coded sign-off gate" in runbook


def test_every_public_tool_description_front_loads_safe_use_guidance() -> None:
    """Tool discovery must orient a Harness before it sees schema detail."""

    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    assert len(tools) == 12
    for name, tool in tools.items():
        description = tool.description or ""
        assert description.startswith("When to use:"), name
        assert "Prerequisite:" in description, name
        assert "Safe default:" in description, name
        assert "Not for:" in description, name


def test_documentation_validation_rejects_obsolete_workflow_terms(tmp_path: Path) -> None:
    """A release cannot silently ship docs for removed aliases or field names."""

    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    (tmp_path / "docs" / "USER-JOURNEY.md").write_text(
        (tmp_path / "docs" / "USER-JOURNEY.md").read_text(encoding="utf-8")
        + "\nCall run_status with the limitation field.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="obsolete workflow term"):
        validate_documentation_contract(tmp_path)


def test_documentation_validation_rejects_contract_version_drift(tmp_path: Path) -> None:
    """The journey's declared workflow contract must track the generated release."""

    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    journey = tmp_path / "docs" / "USER-JOURNEY.md"
    journey.write_text(
        journey.read_text(encoding="utf-8").replace(
            "rob2-kit-contract-version: 1.1.0", "rob2-kit-contract-version: 9.9.9"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contract version diverges"):
        validate_documentation_contract(tmp_path)
