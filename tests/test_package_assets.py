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
