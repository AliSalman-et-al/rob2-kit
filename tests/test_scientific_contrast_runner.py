from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.run_scientific_contrast_baseline import (
    FIXTURE,
    _add_production_guidance,
    _cli_args,
    _load_fixture,
    _plan,
    run_baseline,
)


def test_luna_plan_has_five_blinded_pairs_and_counterbalances_order() -> None:
    fixture = _load_fixture(FIXTURE)
    plan = _plan(fixture, 3, "gpt-6-luna", "medium")

    assert len(plan) == 30
    assert Counter(item["pair_id"] for item in plan) == {f"P-{number}": 6 for number in range(1, 6)}
    for pair_id in (f"P-{number}" for number in range(1, 6)):
        pair = [item for item in plan if item["pair_id"] == pair_id]
        assert [item["case_id"] for item in pair[:2]] == [
            fixture["evaluator_key"]["contrasts"][int(pair_id[2:]) - 1]["cases"][0],
            fixture["evaluator_key"]["contrasts"][int(pair_id[2:]) - 1]["cases"][1],
        ]
        assert [item["case_id"] for item in pair[2:4]] == [
            item["case_id"] for item in reversed(pair[:2])
        ]


def test_cli_disables_shell_and_web_and_uses_read_only_empty_workspace(tmp_path: Path) -> None:
    args = _cli_args("gpt-6-luna", "medium", tmp_path / "blank")

    assert "--strict-config" in args
    assert args[args.index("--disable") + 1] == "shell_tool"
    assert "standalone_web_search" in args
    assert 'web_search="disabled"' in args
    assert "read-only" in args
    assert str((tmp_path / "blank").resolve()) in args
    assert args[-1] == "-"


def test_prepare_stores_only_blinded_prompts_separate_from_key(tmp_path: Path) -> None:
    output = tmp_path / "prepared"
    manifest = run_baseline(FIXTURE, output, repeats=1)
    fixture = _load_fixture(FIXTURE)
    expected = {
        item["case_id"]: item["model_input"].removeprefix("/rob2-assess ")
        for item in fixture["model_inputs"]
    }

    assert manifest["run_count"] == 10
    assert (
        json.loads((output / "evaluator-key.json").read_text(encoding="utf-8"))
        == (fixture["evaluator_key"])
    )
    for run in manifest["runs"]:
        prompt = (output / run["input_file"]).read_text(encoding="utf-8")
        assert prompt == expected[run["case_id"]]
        assert run["pair_id"] not in prompt
        assert "expected_answers" not in prompt
    assert all((output / run["workspace"]).is_dir() for run in manifest["runs"])


def test_fixed_pack_inputs_add_current_reference_and_question_context() -> None:
    fixture = _load_fixture(FIXTURE)
    guided, hashes = _add_production_guidance(fixture, {"P-2", "P-3"})
    prompts = {item["case_id"]: item["model_input"] for item in guided["model_inputs"]}

    assert set(prompts) == {"C-31", "C-42", "C-53", "C-68"}
    assert "The trial context caused the protocol-inconsistent change." in prompts["C-31"]
    assert "Outcome measurement or detection could differ between groups." in prompts["C-53"]
    assert "Current Domain reference guidance" in prompts["C-31"]
    assert "Current Domain reference guidance" in prompts["C-53"]
    assert "complete official Box 10 elaborations" in prompts["C-53"]
    reference = Path("src/rob2_kit/skills/rob2-assess/references/measurement.md").read_text()
    assert reference.rstrip() in prompts["C-53"]
    assert "Preserve which actor, arm, period and endpoint" in prompts["C-53"]
    assert any(Path(path).name == "measurement.md" for path in hashes)
    assert fixture["model_inputs"][0]["model_input"].count("Current Domain reference") == 0
    assert {item["pair_id"] for item in guided["evaluator_key"]["contrasts"]} == {
        "P-2",
        "P-3",
    }
