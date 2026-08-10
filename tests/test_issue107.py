"""Release contracts for the canonical cross-Harness agent skills (#107)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
from rob2_kit.release import (
    CANONICAL_SKILL_NAMES,
    SKILL_ALLOWED_TOOL_NAMES,
    SKILL_REFERENCE_FILENAMES,
    load_release_lock,
    validate_skill_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_two_canonical_skills_are_linted_with_four_direct_references() -> None:
    """The skills orchestrate; their four topical references hold operating detail."""

    validate_skill_contract(ROOT)

    assert CANONICAL_SKILL_NAMES == ("rob2-init", "rob2-assess")
    assert SKILL_REFERENCE_FILENAMES == (
        "HARNESS-WORKFLOW.md",
        "RUN-DEFINITION.md",
        "EVIDENCE-SEARCH.md",
        "SIGNALING-QUESTIONS.md",
    )
    assert all((ROOT / "docs" / name).is_file() for name in SKILL_REFERENCE_FILENAMES)

    init = (ROOT / "skills" / "rob2-init" / "SKILL.md").read_text(encoding="utf-8")
    assess = (ROOT / "skills" / "rob2-assess" / "SKILL.md").read_text(encoding="utf-8")
    assert "rob2-assess" in init
    assert "rob2-init" in assess
    assert "unconfirmed Run definition" in assess
    assert "RUN-DEFINITION.md" in init
    assert "RUN-DEFINITION.md" in assess


def test_generated_host_adapters_pin_exactly_the_skill_allowlist_and_hashes() -> None:
    """Host copies are generated from canonical sources and expose no extra skill tools."""

    assert len(SKILL_ALLOWED_TOOL_NAMES) == 13
    assert set(SKILL_ALLOWED_TOOL_NAMES) <= set(RUN_OPERATION_NAMES)
    lock = load_release_lock(ROOT)
    for host in ("codex", "claude"):
        adapter_root = ROOT / "adapters" / host
        descriptor = json.loads((adapter_root / "adapter.json").read_text(encoding="utf-8"))
        assert descriptor["allowed_tools"] == list(SKILL_ALLOWED_TOOL_NAMES)
        assert descriptor["skill_hashes"] == {
            name: lock.skills[name].content_hash for name in CANONICAL_SKILL_NAMES
        }
        assert descriptor["forward_fixtures_hashes"] == {
            name: lock.skills[name].forward_fixtures_hash for name in CANONICAL_SKILL_NAMES
        }
        for name in CANONICAL_SKILL_NAMES:
            assert (adapter_root / "skills" / name / "SKILL.md").read_bytes() == (
                ROOT / "skills" / name / "SKILL.md"
            ).read_bytes()


def test_skill_lint_rejects_a_fifth_direct_reference(tmp_path: Path) -> None:
    """Progressive disclosure stays bounded even when a filename is lowercase."""

    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    skill = tmp_path / "skills" / "rob2-assess" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + "\nSee `../references/extra.md`.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly the four"):
        validate_skill_contract(tmp_path)


def test_skill_lint_rejects_unclosed_front_matter(tmp_path: Path) -> None:
    """Generated host skills must remain parseable skills, not merely plain text."""

    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    skill = tmp_path / "skills" / "rob2-init" / "SKILL.md"
    skill.write_text(
        "---\nname: rob2-init\ndescription: broken front matter\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid front matter"):
        validate_skill_contract(tmp_path)


def test_skill_lint_rejects_a_malformed_opening_delimiter(tmp_path: Path) -> None:
    """Skill front matter uses a standalone opening delimiter line."""

    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    skill = tmp_path / "skills" / "rob2-init" / "SKILL.md"
    skill.write_text(
        "---name: rob2-init\ndescription: malformed opening\n---\ntext\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid front matter"):
        validate_skill_contract(tmp_path)


def test_fresh_agent_forward_fixtures_cover_safe_routing_without_expected_answers() -> None:
    """Fixture prompts exercise entry, resume, correction, explanation, and rejection routing."""

    fixtures = json.loads(
        (ROOT / "skills" / "rob2-assess" / "forward-fixtures.json").read_text(encoding="utf-8")
    )
    scenarios = {fixture["scenario"] for fixture in fixtures}
    assert {"normal", "resume", "negative", "correction", "report_explanation"} <= scenarios
    assert all("expected_answer" not in fixture for fixture in fixtures)
    assert all("judgment" not in fixture for fixture in fixtures)
    selected_skills = {fixture["scenario"]: fixture["activated_skill"] for fixture in fixtures}
    assert selected_skills["normal"] == "rob2-assess"
    assert selected_skills["resume"] == "rob2-assess"
    assert selected_skills["negative"] == "rob2-assess"
    assert selected_skills["correction"] == "rob2-init"
    assert selected_skills["report_explanation"] == "rob2-assess"
    assert all(
        set(fixture["allowed_tools"]) <= set(SKILL_ALLOWED_TOOL_NAMES) for fixture in fixtures
    )
