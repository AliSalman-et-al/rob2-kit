from __future__ import annotations

from collections import Counter

from scripts.run_chaarted_d3_temporal_contrast import (
    CANDIDATE_PROMPT,
    _arm_context,
    _build_plan,
    _check_key_separation,
    _fixed_context,
    _render_prompt,
)


def test_paired_inputs_change_only_the_d3_comparison_card_prompt() -> None:
    captured = {
        "result": {"trial_id": "chaarted", "time_point": "2013-12-23"},
        "questions": [{"id": "sq:missing:data-available"}],
        "official_guidance": [{"excerpt": "fixed official guidance"}],
        "source_excerpts": [
            {"source": "main_article.pdf", "text": "all randomized patients followed"},
            {"source": "supplement.pdf", "text": "follow-up as of 12/23/14"},
        ],
        "comparison_card": {
            "passage_groups": [{"source_label": "supplement.pdf"}],
            "prompt": "captured baseline prompt",
        },
    }

    baseline = _arm_context(captured, "captured baseline prompt")
    candidate = _arm_context(captured, CANDIDATE_PROMPT)

    assert _fixed_context(baseline) == _fixed_context(candidate) == _fixed_context(captured)
    assert baseline["comparison_card"]["prompt"] != candidate["comparison_card"]["prompt"]


def test_plan_has_three_paired_luna_medium_repeats_with_alternating_order() -> None:
    plan = _build_plan()

    assert len(plan) == 6
    assert Counter(item["arm"] for item in plan) == {"baseline": 3, "candidate": 3}
    assert {(item["model"], item["reasoning_effort"]) for item in plan} == {
        ("gpt-6-luna", "medium")
    }
    pairs: dict[str, list[dict[str, str]]] = {}
    for item in plan:
        pairs.setdefault(item["pair_id"], []).append(item)
    assert len(pairs) == 3
    assert all(
        {item["arm"] for item in pair} == {"baseline", "candidate"} for pair in pairs.values()
    )
    assert [item["arm"] for item in plan] == [
        "baseline",
        "candidate",
        "candidate",
        "baseline",
        "baseline",
        "candidate",
    ]
    assert all("arm" not in item["run_id"] for item in plan)


def test_evaluator_rubric_and_saved_answer_stay_out_of_model_inputs() -> None:
    context = {
        "result": {"trial_id": "chaarted"},
        "questions": [],
        "official_guidance": [],
        "source_excerpts": [],
        "comparison_card": {"prompt": "same card field"},
    }
    key = {
        "recorded_trace_answer": {"justification": "PRIVATE SAVED ANSWER"},
        "source_review": {
            "classification": "PRIVATE SOURCE CLASSIFICATION",
            "rationale": "PRIVATE SOURCE RATIONALE",
        },
        "rubric": {"dated_basis": "PRIVATE RUBRIC TEXT"},
    }
    model_input = _render_prompt(context, "fixed guidance")

    _check_key_separation(model_input, key)
    assert "PRIVATE SAVED ANSWER" not in model_input
    assert "PRIVATE SOURCE CLASSIFICATION" not in model_input
    assert "PRIVATE SOURCE RATIONALE" not in model_input
    assert "PRIVATE RUBRIC TEXT" not in model_input
