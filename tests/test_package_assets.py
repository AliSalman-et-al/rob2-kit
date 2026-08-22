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
    assert "denominator bases" in workflow
    assert "reported_text" in workflow
    assert "defined as" in workflow
    assert (
        "Search-hit identities and render identities are navigation handles, not Evidence"
        in workflow
    )
    assert (
        "only the Evidence identity returned by `retrieve_evidence` after an exact normal, "
        "manual, or visual selection may be used in `save_proposal`"
        in workflow
    )
    assert "use that exact full text in `ProposalInput.outcome_statement`" in workflow
    assert "use the exact suffix as `target.outcome_definition`" in workflow
    assert (
        "Before considering `outcome_not_measured` for a researcher-supplied "
        "`<label>, defined as <definition>`, search the primary report abstract and "
        "results for the complete definition and its distinctive component phrases"
        in workflow
    )
    assert (
        "A broader, narrower, component, protocol-planned, or merely related endpoint "
        "is not evidence that the exact requested outcome is absent and must not replace it"
        in workflow
    )
    assert (
        "Do not select `outcome_not_measured` while an exact requested-outcome result is "
        "reported in any included source"
        in workflow
    )
    assert (
        "Before using `outcome_not_measured`, inspect every included main report/result "
        "source likely to report the requested outcome and cite complete passages that "
        "establish the unresolved absence or definition problem"
        in workflow
    )
    assert (
        "search hits and clipped line fragments are not sufficient Evidence for a "
        "terminal scientific disposition"
        in workflow
    )
    assert (
        "When the exact requested-outcome result is found, build the Result card from "
        "that result even if another related endpoint is more prominent or appears elsewhere"
        in workflow
    )
    assert (
        "Choose stable comparison group IDs once and reuse them exactly in "
        "`target.comparison_groups`, `reported.comparison_groups` or group bindings, "
        "and `population.outcome_measurement_coverage`"
        in workflow
    )
    assert (
        "when the source reports the requested outcome for both target comparison groups, "
        "include a `measured` entry for both target comparison groups only when Evidence "
        "supports outcome measurement; otherwise use the appropriate `needs_input` disposition"
        in workflow
    )
    assert "Repair every returned defect" in signalling
    assert "assessment_in_progress" in workflow
    assert "immediate instruction to continue in this same run" in workflow
    assert (
        "After each `commit_domain_judgment`, consume its returned `next work_packet` immediately"
        in workflow
    )
    assert "Reuse persisted Evidence whenever it supports a later Domain" in workflow
    assert (
        "specific missing signalling fact, never by rescanning the full corpus per Domain"
        in workflow
    )
    assert "Repeat immediately for each active Domain" in signalling
    assert "packet returned by `commit_domain_judgment` must be consumed at once" in signalling
    assert "Reuse persisted Evidence from the packet and prior records" in signalling
    retired = ("ingest_batch", "discard_active_batch", "expected_predecessor", "actor", "UTC time")
    for name in retired:
        assert name not in workflow
        assert name not in signalling
