"""Neutral methodological controls preserve activation, not model reasoning claims."""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from rob2_kit.logic import active_questions, evaluate_domain

_ROOT = Path(__file__).parents[1] / "docs/evaluation/2026-10-03-d27-mechanism-impact"


class _Control(TypedDict):
    id: str
    lines: list[str]
    review: str
    analysis: str
    impact: str | None


_CONTROLS = cast(
    list[_Control], json.loads((_ROOT / "private-neutral-controls.json").read_text())["cases"]
)


@pytest.mark.parametrize("case", _CONTROLS, ids=[case["id"] for case in _CONTROLS])
def test_methodological_controls_preserve_probable_and_uncertain_paths(case: _Control) -> None:
    # Answers are independently authored methodological expectations, not computed
    # from the facts. This verifies that guidance edits add no mechanical gate.
    answers = {
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:appropriate-analysis": case["analysis"],
    }
    impact = "sq:deviations:substantial-impact"
    assert (impact in active_questions(answers)) == (case["impact"] is not None)
    if case["impact"] is not None:
        answers[impact] = case["impact"]
    result = evaluate_domain("domain:deviations", answers)
    expected = {
        "important-restriction": "high",
        "negligible-restriction": "some_concerns",
        "unknown-impact": "high",
        "stopping-with-retained-outcomes": "low",
    }
    assert result.judgment.value == expected[case["id"]]


def test_targeted_experiment_changes_only_impact_considerations() -> None:
    before_after = json.loads((_ROOT / "guidance-before-after.json").read_text())
    before, after = before_after["baseline"], before_after["current"]
    assert before[0] == after[0]
    before_considerations = before[1]["operational_guidance"].pop("considerations")
    after_considerations = after[1]["operational_guidance"].pop("considerations")
    assert before[1] == after[1]
    assert before_considerations != after_considerations
    for arm in ("baseline", "current"):
        text = (_ROOT / f"{arm}-input.txt").read_text()
        for case in _CONTROLS:
            assert all(line in text for line in case["lines"])
            assert case["review"] not in text
        assert "expected_answer" not in text
