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

    assert "current-batch" in workflow
    assert "After approval" in workflow
    assert "finalize_batch" in workflow
    assert "artifact" in workflow
    assert "researcher-only" in workflow
    assert workflow.index("`retrieve_evidence`") < workflow.index("`save_proposal`")
    assert workflow.index("`save_proposal`") < workflow.index("`read_record`")
    assert workflow.index("`read_record`") < workflow.index("`approve_batch`")
    assert "Packet-guided" in signalling
    assert "deliberate text selections" in signalling
    assert "strict Domain draft" in signalling
    assert "every independent repair" in signalling
    assert "synthesis" in signalling
    assert signalling.index("`retrieve_evidence`") < signalling.index("save the\nProposal")
    assert signalling.index("save the\nProposal") < signalling.index("`approve_batch`")
