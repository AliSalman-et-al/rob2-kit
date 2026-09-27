from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.run_latitude_d4_card_prompt_contrast import (
    LATITUDE_CASE,
    PRESERVATION_CASE,
    TESTED_D4_PROMPT_CANDIDATE,
    run_contrast,
)


def _latitude_context_from_input(text: str) -> dict[str, Any]:
    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    return json.loads(text[start:end])


def _preservation_context_from_input(text: str) -> dict[str, Any]:
    marker = "## Active question and comparison card\n"
    case_input, card = text.split(marker, 1)
    return {"case_input": case_input.rstrip(), "card": json.loads(card)}


def test_rendered_arms_change_only_card_prompt_and_keep_c68_detection_contrast(
    tmp_path: Path,
) -> None:
    output = tmp_path / "harness"
    manifest = run_contrast(output)
    assert manifest["status"] == "prepared"
    assert manifest["run_count"] == 12
    assert manifest["source_excerpt_count"] == 9

    with (output / "run-plan.jsonl").open(encoding="utf-8") as stream:
        plan = [json.loads(line) for line in stream]
    assert Counter(row["arm"] for row in plan) == {"baseline": 6, "candidate": 6}
    assert Counter(row["scenario"] for row in plan) == {
        LATITUDE_CASE: 6,
        PRESERVATION_CASE: 6,
    }

    paired: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in plan:
        text = (output / row["input_file"]).read_text(encoding="utf-8")
        paired[(row["scenario"], row["repeat"])][row["arm"]] = (
            _latitude_context_from_input(text)
            if row["scenario"] == LATITUDE_CASE
            else _preservation_context_from_input(text)
        )
        assert "evaluator-key.json" not in text
        assert "expected_answers" not in text
        assert "likely_model_error" not in text

    for (scenario, _repeat), arms in paired.items():
        baseline = arms["baseline"]
        candidate = arms["candidate"]
        if scenario == LATITUDE_CASE:
            baseline_context = baseline
            candidate_context = candidate
            baseline_card = baseline["comparison_card"]
            candidate_card = candidate["comparison_card"]
        else:
            assert baseline["case_input"] == candidate["case_input"]
            baseline_context = baseline["card"]
            candidate_context = candidate["card"]
            baseline_card = baseline_context
            candidate_card = candidate_context
        baseline_prompt = baseline_card["prompt"]
        candidate_prompt = candidate_card["prompt"]
        assert baseline_prompt != candidate_prompt
        if scenario == LATITUDE_CASE:
            baseline_fixed = json.loads(json.dumps(baseline_context))
            candidate_fixed = json.loads(json.dumps(candidate_context))
            baseline_fixed["comparison_card"].pop("prompt")
            candidate_fixed["comparison_card"].pop("prompt")
        else:
            baseline_fixed = dict(baseline_context)
            candidate_fixed = dict(candidate_context)
            baseline_fixed.pop("prompt")
            candidate_fixed.pop("prompt")
        assert baseline_fixed == candidate_fixed
        assert candidate_prompt == TESTED_D4_PROMPT_CANDIDATE

    latitude_pair = paired[(LATITUDE_CASE, 1)]
    excerpts = latitude_pair["baseline"]["source_excerpts"]
    combined_source_text = "\n".join(
        item.get("numbered_text", item.get("quote", "")) for item in excerpts
    )
    assert "24 months" in combined_source_text and "14 months" in combined_source_text
    assert "30 days after the last dose" in combined_source_text

    c68_pair = paired[(PRESERVATION_CASE, 1)]
    assert "every two weeks" in c68_pair["baseline"]["case_input"].lower()
    key = json.loads((output / "evaluator-key.json").read_text(encoding="utf-8"))
    assert key["cases"][LATITUDE_CASE]["recorded_trace_answer"]["answer"] == "probably_no"
    assert key["cases"][PRESERVATION_CASE]["expectation"]["expected_answers"] == {
        "sq:measurement:differential": "yes"
    }


def test_run_plan_counterbalances_prompt_order_within_each_scenario(tmp_path: Path) -> None:
    output = tmp_path / "harness"
    manifest = run_contrast(output)
    with (output / "run-plan.jsonl").open(encoding="utf-8") as stream:
        plan = [json.loads(line) for line in stream]

    for scenario in (LATITUDE_CASE, PRESERVATION_CASE):
        scenario_rows = [row for row in plan if row["scenario"] == scenario]
        assert [row["arm"] for row in scenario_rows] == [
            "baseline",
            "candidate",
            "candidate",
            "baseline",
            "baseline",
            "candidate",
        ]
    assert manifest["model"] == "gpt-6-luna"
    assert manifest["reasoning_effort"] == "medium"
    assert manifest["model_inputs_exclude"]
