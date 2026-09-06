"""Deterministic scoring for retrieval, premise quality, and workflow friction.

The harness consumes hashed/abstracted records rather than source text. It is
intended to make an evaluation rerunnable without paid model calls or leaking
private trial material into a qualification receipt.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def evaluate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Score a synthetic held-out fixture deterministically.

    Records use ``needed_passages``, ``retrieved_passages``, ``premises``, and
    ``attempts``. A premise has ``required`` and ``supported`` booleans; an
    attempt has trial, outcome, draw, model, label, and prediction fields, with
    optional friction, selection, and disposition metadata. Trial rows may
    declare draws and model families to define expected scoring cells.
    """
    if not isinstance(fixture, dict):
        raise ValueError("fixture must be an object")
    raw_trials = fixture.get("trials", [])
    if not isinstance(raw_trials, list):
        raise ValueError("trials must be a list")
    trial_rows: list[dict[str, Any]] = []
    for row in raw_trials:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("trial_id"), str)
            or not row["trial_id"].strip()
        ):
            raise ValueError("each trial needs a non-blank trial_id")
        outcomes = row.get("outcomes")
        if (
            not isinstance(outcomes, list)
            or not outcomes
            or any(not isinstance(outcome, str) or not outcome.strip() for outcome in outcomes)
            or len(set(outcomes)) != len(outcomes)
        ):
            raise ValueError(f"trial {row['trial_id']!r} has malformed or duplicate outcomes")
        for key in ("selected_disposition", "final_disposition"):
            if key in row and row[key] not in {"assessed", "needs_input", "failed", "pending"}:
                raise ValueError(f"trial {row['trial_id']!r} has an invalid {key}")
        trial_rows.append(row)
    trials = {row["trial_id"] for row in trial_rows}
    if len(trials) != len(trial_rows):
        raise ValueError("trials contain duplicate trial_id values")

    # A scoring cell is one trial/outcome/draw/model attempt.  Keep every raw
    # attempt for audit, but score duplicate cells once so retries cannot
    # change a scientific numerator or the always-Low denominator.
    def cell_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row.get("trial_id")),
            str(row.get("outcome_id", row.get("outcome", "default"))),
            str(row.get("draw", "1")),
            str(row.get("model_family", row.get("model", "default"))),
        )

    needed = fixture.get("needed_passages", [])
    retrieved = fixture.get("retrieved_passages", [])
    if not isinstance(needed, list) or not isinstance(retrieved, list):
        raise ValueError("passage lists must be arrays")
    needed_by_trial: dict[str, list[str]] = defaultdict(list)
    for row in needed:
        if not isinstance(row, dict) or "trial_id" not in row or "passage_id" not in row:
            raise ValueError("needed passages are malformed")
        if str(row["trial_id"]) not in trials or not str(row["passage_id"]).strip():
            raise ValueError("needed passage references an unknown trial or blank passage")
        needed_by_trial[str(row["trial_id"])].append(str(row["passage_id"]))
    retrieved_by_trial: dict[str, list[str]] = defaultdict(list)
    for row in retrieved:
        if not isinstance(row, dict) or "trial_id" not in row or "passage_id" not in row:
            raise ValueError("retrieved passages are malformed")
        if str(row["trial_id"]) not in trials or not str(row["passage_id"]).strip():
            raise ValueError("retrieved passage references an unknown trial or blank passage")
        retrieved_by_trial[str(row["trial_id"])].append(str(row["passage_id"]))
    recalls: list[float] = []
    ranks: list[int] = []
    for trial_id, passages in needed_by_trial.items():
        returned = retrieved_by_trial.get(trial_id, [])
        ranks.extend(index + 1 for index, value in enumerate(returned) if value in passages)
        recalls.append(len(set(returned) & set(passages)) / len(set(passages)) if passages else 1.0)
    raw_premises = fixture.get("premises", [])
    if not isinstance(raw_premises, list) or any(not isinstance(row, dict) for row in raw_premises):
        raise ValueError("premises must be a list of objects")
    premises = raw_premises
    required_premises = [row for row in premises if row.get("required") is True]
    supported = [row for row in required_premises if row.get("supported") is True]
    premise_support = len(supported) / len(required_premises) if required_premises else 0.0
    contradictions = sum(1 for row in premises if row.get("contradiction_handled") is True)
    raw_attempts = fixture.get("attempts", [])
    if not isinstance(raw_attempts, list):
        raise ValueError("attempts must be a list")
    attempts: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    trial_by_id = {row["trial_id"]: row for row in trial_rows}
    for row in raw_attempts:
        required = ("trial_id", "outcome_id", "draw", "model_family", "label", "prediction")
        if not isinstance(row, dict) or any(key not in row for key in required):
            raise ValueError(
                "attempts must contain trial, outcome, draw, model, label, and prediction"
            )
        trial_id = row["trial_id"]
        if not isinstance(trial_id, str) or not isinstance(row["outcome_id"], str):
            raise ValueError("attempt trial_id and outcome_id must be strings")
        if (
            trial_id not in trial_by_id
            or row["outcome_id"] not in trial_by_id[trial_id]["outcomes"]
        ):
            raise ValueError("attempt references an unknown trial or outcome")
        if (
            not isinstance(row["label"], str)
            or not row["label"].strip()
            or not isinstance(row["prediction"], str)
            or not row["prediction"].strip()
        ):
            raise ValueError("attempt label and prediction must be non-blank strings")
        if (
            type(row["draw"]) is not int
            or row["draw"] < 1
            or not isinstance(row["model_family"], str)
            or not row["model_family"].strip()
        ):
            raise ValueError("attempt draw/model_family is malformed")
        for key in ("selected", "final"):
            if key in row and type(row[key]) is not bool:
                raise ValueError(f"attempt {key} must be boolean")
        for key in ("selected_disposition", "final_disposition"):
            if key in row and row[key] not in {"assessed", "needs_input", "failed", "pending"}:
                raise ValueError(f"attempt {key} is invalid")
        attempts.append(row)
        if (
            row.get("selected", True)
            and row.get("final", True)
            and row.get("final_disposition", row.get("selected_disposition", "assessed"))
            == "assessed"
        ):
            eligible.append(row)
    cells: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_attempts = 0
    for row in eligible:
        key = cell_key(row)
        if key in cells:
            duplicate_attempts += 1
            continue
        cells[key] = row
    scored = list(cells.values())
    observed_draws = sorted({row["draw"] for row in attempts}) or [1]
    observed_models = sorted({row["model_family"] for row in attempts}) or ["default"]
    expected_cells: set[tuple[str, str, str, str]] = set()
    for trial in trial_rows:
        draws = trial.get("draws", observed_draws)
        models = trial.get("model_families", observed_models)
        if not isinstance(draws, list) or not all(
            type(draw) is int and draw >= 1 for draw in draws
        ):
            raise ValueError(f"trial {trial['trial_id']!r} has malformed draws")
        if not isinstance(models, list) or not all(
            isinstance(model, str) and model.strip() for model in models
        ):
            raise ValueError(f"trial {trial['trial_id']!r} has malformed model_families")
        if len(set(draws)) != len(draws) or len(set(models)) != len(models):
            raise ValueError(f"trial {trial['trial_id']!r} has duplicate scoring dimensions")
        expected_cells.update(
            (trial["trial_id"], outcome, str(draw), model)
            for outcome in trial["outcomes"]
            for draw in draws
            for model in models
        )
    unexpected_cells = {cell_key(row) for row in attempts} - expected_cells
    if unexpected_cells:
        raise ValueError("attempt references an undeclared draw or model family")
    correct = [row for row in scored if row.get("label") == row.get("prediction")]
    by_class: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    for row in scored:
        label = str(row.get("label", "unknown"))
        by_class[label]["total"] += 1
        by_class[label]["correct"] += int(row.get("label") == row.get("prediction"))
    class_rates = [
        value["correct"] / value["total"] for value in by_class.values() if value["total"]
    ]
    totals = {
        key: sum(float(row.get(key, 0) or 0) for row in attempts)
        for key in ("tool_calls", "repair_loops", "tokens", "elapsed_ms", "cost")
    }
    missing_artifacts = fixture.get("missing_artifacts", [])
    if not isinstance(missing_artifacts, list) or any(
        not isinstance(item, str) or not item.strip() for item in missing_artifacts
    ):
        raise ValueError("missing_artifacts must be a list of non-blank strings")
    missing_references = sum(
        bool(row.get("missing_reference") or row.get("reference_available") is False)
        for row in premises + attempts
    )
    incomplete_replay = bool(missing_artifacts) or bool(fixture.get("incomplete_replay"))
    coverage = len(set(cells) & expected_cells) / len(expected_cells) if expected_cells else 0.0
    return {
        "schema": "rob2-kit.held-out-evaluation.v0.4",
        "fixture_sha256": _hash(fixture),
        "evaluation_status": (
            "complete"
            if not incomplete_replay and not missing_references and coverage == 1.0
            else "incomplete"
        ),
        "trial_count": len(trials),
        "retrieval": {
            "needed_passage_recall": sum(recalls) / len(recalls) if recalls else 0.0,
            "needed_passage_count": len(needed),
            "retrieved_count": len(retrieved),
            "mean_rank": sum(ranks) / len(ranks) if ranks else None,
        },
        "premises": {
            "supported_fraction": premise_support,
            "required_count": len(required_premises),
            "contradictions_handled": contradictions,
        },
        "scientific": {
            "coverage": coverage,
            "expected_cell_count": len(expected_cells),
            "missing_cells": sorted(expected_cells - set(cells)),
            "accuracy": len(correct) / len(scored) if scored else 0.0,
            "balanced_class_accuracy": sum(class_rates) / len(class_rates) if class_rates else 0.0,
            "by_class": dict(by_class),
            "abstentions": sum(
                row.get("prediction") in {"no_information", "abstain"} for row in scored
            ),
            "scored_cell_count": len(scored),
            "always_low": {
                "accuracy": (
                    sum(row.get("label") == "low" for row in scored) / len(scored)
                    if scored
                    else 0.0
                ),
                "denominator": len(scored),
            },
        },
        "friction": totals,
        "attempt_count": len(attempts),
        "audit": {
            "duplicate_attempts": duplicate_attempts,
            "trial_outcome_count": sum(
                len(row.get("outcomes", []))
                for row in trial_rows
                if isinstance(row.get("outcomes", []), list)
            ),
            "missing_references": missing_references,
            "false_repairs": sum(bool(row.get("false_repair")) for row in attempts),
            "incomplete_replay": incomplete_replay,
            "missing_artifacts": missing_artifacts,
        },
    }
