import json
from importlib.resources import files


def test_installed_skill_and_host_metadata_are_shared() -> None:
    package = files("rob2_kit")
    skills = package.joinpath("skills")
    assert sorted(item.name for item in skills.iterdir()) == ["rob2-signalling", "rob2-workflow"]

    expected = ["rob2-workflow", "rob2-signalling"]
    for filename in ("codex.json", "claude-code.json"):
        metadata = json.loads(package.joinpath("hosts", filename).read_text())
        assert metadata["skills"] == expected
        assert metadata["skill_directory"] == "rob2_kit/skills"


def test_packaged_skills_guard_the_human_acceptance_boundaries() -> None:
    package = files("rob2_kit")
    workflow = package.joinpath("skills", "rob2-workflow", "SKILL.md").read_text()
    signalling = package.joinpath("skills", "rob2-signalling", "SKILL.md").read_text()

    assert "Inspect `inputs/<trial>`" in workflow
    assert "wait for explicit approval" in workflow
    assert "After every Trial has a terminal outcome, call `finalize_batch`" in workflow
    assert "`FinalizedBatch.receipt`" in workflow
    assert "standalone host-authored HTML" in workflow
    assert "available only for an explicit researcher instruction" in workflow
    assert "all five guidance resources" in signalling
    assert "versioned working save, verify this checklist" in signalling
    assert "debug or test payload" in signalling
    assert "inspect the tool schema rather than probing with a save" in signalling
    assert "`expected_previous_hash`" in workflow
    assert "Preflight the entire payload" in signalling
