from __future__ import annotations

import json
from pathlib import Path

import pytest

from rob2_kit.evaluation import evaluate_fixture


def test_synthetic_heldout_scorer_is_deterministic_and_tracks_friction() -> None:
    fixture = json.loads(Path("eval/synthetic-heldout.json").read_text(encoding="utf-8"))
    first = evaluate_fixture(fixture)
    second = evaluate_fixture(fixture)
    assert first == second
    assert first["retrieval"]["needed_passage_recall"] == 1.0
    assert first["scientific"]["coverage"] == 1.0
    assert first["friction"]["repair_loops"] == 1.0
    assert first["evaluation_status"] == "incomplete"


def test_scorer_groups_duplicate_draw_cells_and_reports_incomplete_replay() -> None:
    result = evaluate_fixture(
        {
            "trials": [{"trial_id": "t", "outcomes": ["o1", "o2"]}],
            "missing_artifacts": ["reference_labels"],
            "attempts": [
                {
                    "trial_id": "t",
                    "outcome_id": "o1",
                    "draw": 1,
                    "model_family": "a",
                    "label": "low",
                    "prediction": "low",
                    "false_repair": True,
                },
                {
                    "trial_id": "t",
                    "outcome_id": "o1",
                    "draw": 1,
                    "model_family": "a",
                    "label": "low",
                    "prediction": "some_concerns",
                },
                {
                    "trial_id": "t",
                    "outcome_id": "o2",
                    "draw": 1,
                    "model_family": "a",
                    "label": "some_concerns",
                    "prediction": "some_concerns",
                },
            ],
        }
    )
    assert result["scientific"]["scored_cell_count"] == 2
    assert result["scientific"]["always_low"]["denominator"] == 2
    assert result["audit"] == {
        "duplicate_attempts": 1,
        "trial_outcome_count": 2,
        "missing_references": 0,
        "false_repairs": 1,
        "incomplete_replay": True,
        "missing_artifacts": ["reference_labels"],
    }


def test_scorer_coverage_uses_expected_outcome_draw_model_cells() -> None:
    result = evaluate_fixture(
        {
            "trials": [
                {
                    "trial_id": "t",
                    "outcomes": ["o1", "o2"],
                    "draws": [1, 2],
                    "model_families": ["a", "b"],
                }
            ],
            "attempts": [
                {
                    "trial_id": "t",
                    "outcome_id": "o1",
                    "draw": 1,
                    "model_family": "a",
                    "label": "low",
                    "prediction": "low",
                }
            ],
        }
    )
    assert result["scientific"]["expected_cell_count"] == 8
    assert result["scientific"]["scored_cell_count"] == 1
    assert result["scientific"]["coverage"] == 0.125
    assert len(result["scientific"]["missing_cells"]) == 7


def test_scorer_rejects_malformed_attempts() -> None:
    with pytest.raises(ValueError, match="attempts must contain"):
        evaluate_fixture({"trials": [{"trial_id": "t", "outcomes": ["o1"]}], "attempts": [{}]})


def test_scorer_keeps_nonassessed_attempts_in_the_intended_coverage_denominator() -> None:
    result = evaluate_fixture(
        {
            "trials": [
                {
                    "trial_id": "t",
                    "outcomes": ["o1"],
                    "draws": [1],
                    "model_families": ["a"],
                    "final_disposition": "needs_input",
                }
            ],
            "attempts": [
                {
                    "trial_id": "t",
                    "outcome_id": "o1",
                    "draw": 1,
                    "model_family": "a",
                    "label": "low",
                    "prediction": "abstain",
                    "final_disposition": "needs_input",
                }
            ],
        }
    )

    assert result["scientific"]["expected_cell_count"] == 1
    assert result["scientific"]["scored_cell_count"] == 0
    assert result["scientific"]["coverage"] == 0.0
    assert result["evaluation_status"] == "incomplete"


def test_scorer_rejects_attempts_outside_declared_dimensions() -> None:
    with pytest.raises(ValueError, match="undeclared draw or model family"):
        evaluate_fixture(
            {
                "trials": [
                    {
                        "trial_id": "t",
                        "outcomes": ["o1"],
                        "draws": [1],
                        "model_families": ["a"],
                    }
                ],
                "attempts": [
                    {
                        "trial_id": "t",
                        "outcome_id": "o1",
                        "draw": 2,
                        "model_family": "a",
                        "label": "low",
                        "prediction": "low",
                    }
                ],
            }
        )


def test_scorer_requires_well_formed_missing_artifact_names() -> None:
    with pytest.raises(ValueError, match="missing_artifacts"):
        evaluate_fixture(
            {
                "trials": [{"trial_id": "t", "outcomes": ["o1"]}],
                "missing_artifacts": "labels",
            }
        )
