from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

import pytest

from scripts.render_d3_card_prompt_contrast import (
    TESTED_D3_PROMPT_CANDIDATE,
    _arm_context,
    _build_plan,
    _check_evaluator_key_separation,
    _extract_arm_prompts,
    _fixed_context,
    _render_prompt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_paired_context_changes_only_the_comparison_card_prompt() -> None:
    captured = {
        "result": {"trial_id": "arasens", "estimate": "0.68"},
        "questions": [{"id": "sq:missing:data-available"}],
        "source_excerpts": [{"source_id": "registry", "text": "229 deaths, 422 censored"}],
        "comparison_card": {
            "paired_examples": [{"pair_id": "d3-complete-versus-unresolved-availability"}],
            "propositions": [{"status": "unknown"}],
            "prompt": "generic prompt",
        },
    }

    baseline = _arm_context(captured, "generic prompt")
    current = _arm_context(captured, "D3-specific prompt")

    assert _fixed_context(baseline) == _fixed_context(current) == _fixed_context(captured)
    assert baseline["comparison_card"]["prompt"] != current["comparison_card"]["prompt"]


def test_run_plan_pairs_two_models_at_three_repeats() -> None:
    plan = _build_plan()
    assert len(plan) == 12
    assert Counter(item["arm"] for item in plan) == {"baseline": 6, "current": 6}
    assert Counter((item["model"], item["reasoning_effort"]) for item in plan) == {
        ("gpt-6-luna", "medium"): 6,
        ("gpt-6-sol", "high"): 6,
    }

    pairs: dict[str, list[dict[str, str]]] = {}
    for item in plan:
        pairs.setdefault(item["pair_id"], []).append(item)
    assert len(pairs) == 6
    assert all({item["arm"] for item in pair} == {"baseline", "current"} for pair in pairs.values())
    assert [item["arm"] for item in plan[:6]] == [
        "baseline",
        "current",
        "current",
        "baseline",
        "baseline",
        "current",
    ]


def test_arms_use_the_pinned_generic_and_frozen_candidate_prompts() -> None:
    available = subprocess.run(
        ["git", "cat-file", "-e", "8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8^{commit}"],
        cwd=ROOT,
        capture_output=True,
    )
    if available.returncode:
        pytest.skip(
            "Historical contrast requires the preserved 8fa90ed commit, absent from this checkout."
        )
    baseline_source = subprocess.run(
        [
            "git",
            "show",
            "8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8:src/rob2_kit/application/domains.py",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

    prompts = _extract_arm_prompts(baseline_source)

    assert prompts["baseline"].startswith(
        "Use the exact Result scope, passages, and quantities above."
    )
    assert prompts["current"] == TESTED_D3_PROMPT_CANDIDATE
    assert prompts["current"].startswith(
        "For 3.1, match observed outcomes and follow-up to the approved Result."
    )


def test_plan_keeps_blind_run_ids_and_never_embeds_arm_labels() -> None:
    plan = _build_plan()
    run_ids = [item["run_id"] for item in plan]
    assert len(set(run_ids)) == len(run_ids)
    assert all(item["input_file"].endswith(f"{item['run_id']}.txt") for item in plan)
    assert all(item["expected_jsonl_log"].endswith(f"{item['run_id']}.jsonl") for item in plan)


def test_evaluator_answer_and_source_review_stay_out_of_model_input() -> None:
    context = {
        "result": {"trial_id": "arasens"},
        "questions": [],
        "source_excerpts": [],
        "comparison_card": {"prompt": "same input prompt"},
    }
    key = {
        "recorded_trace_answer": {"justification": "PRIVATE ANSWER RATIONALE"},
        "source_review": {
            "classification": "PRIVATE REVIEW CLASSIFICATION",
            "rationale": "PRIVATE REVIEW RATIONALE",
        },
    }
    model_input = _render_prompt(context, "fixed D3 guidance")

    _check_evaluator_key_separation(model_input, key)
    assert "PRIVATE ANSWER RATIONALE" not in model_input
    assert "PRIVATE REVIEW CLASSIFICATION" not in model_input
    assert "PRIVATE REVIEW RATIONALE" not in model_input
