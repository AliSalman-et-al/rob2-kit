from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

FIXTURE = Path("eval/scientific-premise-contrasts-2026-09-27.json")
TRIAL_NAMES = re.compile(
    r"CHAARTED|TITAN|STAMPEDE|PEACE-1|ARASENS|SWOG-1216|GETUG-AFU-15|ENZAMET|ARCHES|LATITUDE",
    re.IGNORECASE,
)
OUTCOME_LABELS = re.compile(r"\b(low|some_concerns|high|no_information)\b")
EXPECTED_THEMES = {
    "analyzed_event_censor_totals_vs_outcome_completeness",
    "ordinary_care_vs_trial_context_departure",
    "unequal_exposure_vs_actual_ascertainment_opportunity",
    "plan_applicability",
    "plan_chronology",
}


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sentences(prompt: str) -> Counter[str]:
    return Counter(
        sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", prompt) if sentence.strip()
    )


def test_scientific_contrast_fixture_is_blinded_and_trial_independent() -> None:
    fixture = _fixture()
    model_inputs = fixture["model_inputs"]

    assert fixture["schema"] == "rob2-kit.scientific-premise-contrasts.v1"
    assert fixture["purpose"] == "development_only"
    assert fixture["reference_status"] == "provisional_until_issue_475_adjudication"
    assert len(model_inputs) == 10
    assert all(set(item) == {"case_id", "model_input"} for item in model_inputs)
    assert len({item["case_id"] for item in model_inputs}) == len(model_inputs)

    for item in model_inputs:
        prompt = item["model_input"]
        assert prompt.startswith("/rob2-assess Assess risk of bias for the reported ")
        assert item["case_id"] not in prompt
        assert not TRIAL_NAMES.search(prompt)
        assert not OUTCOME_LABELS.search(prompt.casefold())
        assert "evaluator_key" not in prompt
        assert re.search(r"\b(Article|Report|Analysis plan|Protocol):", prompt)


def test_each_contrast_changes_one_premise_and_keeps_its_controls_fixed() -> None:
    fixture = _fixture()
    model_inputs = {item["case_id"]: item["model_input"] for item in fixture["model_inputs"]}
    evaluator = fixture["evaluator_key"]
    contrasts = evaluator["contrasts"]
    expectations = evaluator["case_expectations"]

    assert {contrast["theme"] for contrast in contrasts} == EXPECTED_THEMES
    assert len(contrasts) == 5
    paired_cases: list[str] = []
    for contrast in contrasts:
        cases = contrast["cases"]
        assert len(cases) == 2
        paired_cases.extend(cases)
        assert contrast["controlled_facts"]
        left, right = (model_inputs[case_id] for case_id in cases)
        left_sentences, right_sentences = _sentences(left), _sentences(right)
        assert sum((left_sentences - right_sentences).values()) == 1
        assert sum((right_sentences - left_sentences).values()) == 1
        changed_values = {expectations[case_id]["changed_premise_value"] for case_id in cases}
        assert len(changed_values) == 2
        assert all(contrast["pair_id"] not in model_inputs[case_id] for case_id in cases)
        assert all(case_id in expectations for case_id in cases)

    assert len(paired_cases) == len(set(paired_cases))
    assert set(paired_cases) == set(model_inputs)
    assert set(expectations) == set(model_inputs)
    assert {item["expected_domain_judgment"] for item in expectations.values()} >= {
        "low",
        "some_concerns",
        "high",
    }
    assert any(
        answer == "no_information"
        for item in expectations.values()
        for answer in item["expected_answers"].values()
    )


def test_contrast_keys_match_focal_questions_and_domain_judgments() -> None:
    fixture = _fixture()
    expectations = fixture["evaluator_key"]["case_expectations"]
    valid_judgments = {"low", "some_concerns", "high"}

    for contrast in fixture["evaluator_key"]["contrasts"]:
        for case_id in contrast["cases"]:
            expectation = expectations[case_id]
            assert expectation["expected_domain_judgment"] in valid_judgments
            assert set(expectation["expected_answers"]) == {contrast["question_id"]}
            assert set(expectation) == {
                "changed_premise_value",
                "expected_answers",
                "expected_domain_judgment",
                "rationale",
            }
