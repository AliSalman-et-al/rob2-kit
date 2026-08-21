import json
from importlib.resources import files
from pathlib import Path


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

    contract_path = Path(__file__).parents[1] / "docs/release/public-contract.json"
    contract = json.loads(contract_path.read_text())
    tools = {item["name"] for item in contract["tools"]}
    for name in tools:
        assert f"`{name}`" in workflow or f"`{name}`" in signalling
    assert "work_packet" in workflow and "work_packet" in signalling
    assert "typed continuation" in workflow
    assert "proposal_approval_ready" in workflow
    assert "do not reinterpret or reopen it" in workflow
    assert "Repair every returned defect" in signalling
    retired = ("ingest_batch", "discard_active_batch", "expected_predecessor", "actor", "UTC time")
    for name in retired:
        assert name not in workflow
        assert name not in signalling
