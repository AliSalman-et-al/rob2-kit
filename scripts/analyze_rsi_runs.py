#!/usr/bin/env python3
"""Analyze frozen RSI run outputs and separately held posthoc annotations."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "rob2-kit.rsi-run-analysis.v1"
DOMAINS = ("D1", "D2", "D3", "D4", "D5")
LABELS = ("low", "some_concerns", "high")
COMPLETION = {"finalized", "incomplete", "failed", "interrupted", "unknown"}
SCOPE = {"eligible", "scope_uncertain", "ineligible"}
FAILURE_CAUSES = {
    "passage_not_found",
    "passage_not_delivered",
    "citation_incomplete",
    "interpretation_error",
    "delivery_unknown",
    "workflow_incomplete",
    "scope_error",
    "infrastructure",
    "other",
}
LABEL_NAMES = {
    "low": "Low",
    "some_concerns": "Some Concerns",
    "high": "High",
    "non_low": "Non-Low",
}


def _validate_input(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError(f"input must use schema {SCHEMA!r}")
    rows = value.get("cases")
    if not isinstance(rows, list):
        raise ValueError("cases must be a list")
    case_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        location = f"cases[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{location} must be an object")
        allowed = {
            "case_id",
            "trial_id",
            "outcome",
            "scope",
            "completion",
            "expected",
            "observed",
            "cost_usd",
            "failure_causes",
        }
        if set(row) - allowed:
            raise ValueError(f"{location} contains unsupported fields")
        for key in ("case_id", "trial_id", "outcome"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"{location}.{key} must be non-empty text")
        if row["case_id"] in case_ids:
            raise ValueError(f"{location}.case_id is duplicated")
        case_ids.add(row["case_id"])
        if not isinstance(row.get("scope"), str) or row["scope"] not in SCOPE:
            raise ValueError(f"{location}.scope is invalid")
        if not isinstance(row.get("completion"), str) or row["completion"] not in COMPLETION:
            raise ValueError(f"{location}.completion is invalid")
        expected = row.get("expected", {})
        observed = row.get("observed", {})
        if not isinstance(expected, dict) or not isinstance(observed, dict):
            raise ValueError(f"{location}.expected and observed must be objects")
        if set(expected) - set(DOMAINS) or set(observed) - set(DOMAINS):
            raise ValueError(f"{location} contains an unknown Domain")
        if row["scope"] == "eligible" and set(expected) != set(DOMAINS):
            raise ValueError(f"{location}.expected must contain D1 through D5 for eligible cases")
        for field_name, answers in (("expected", expected), ("observed", observed)):
            for domain, label in answers.items():
                if not isinstance(label, str) or label not in LABELS:
                    raise ValueError(f"{location}.{field_name}.{domain} is not a valid label")
        cost = row.get("cost_usd")
        if cost is not None and (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError(f"{location}.cost_usd must be non-negative or null")
        causes = row.get("failure_causes", {})
        if not isinstance(causes, dict) or set(causes) - set(DOMAINS):
            raise ValueError(f"{location}.failure_causes must map Domain IDs to causes")
        for domain, cause in causes.items():
            if not isinstance(cause, str) or cause not in FAILURE_CAUSES:
                raise ValueError(f"{location}.failure_causes.{domain} is invalid")
        validated.append(row)
    return validated


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _cluster_interval(
    per_trial: dict[str, tuple[int, int]], rng: random.Random, replicates: int
) -> dict[str, float] | None:
    clusters = list(per_trial.values())
    if len(clusters) < 2 or replicates <= 0 or not any(denominator for _, denominator in clusters):
        return None
    samples: list[float] = []
    for _ in range(replicates):
        numerator = denominator = 0
        for _cluster in clusters:
            successes, expected = rng.choice(clusters)
            numerator += successes
            denominator += expected
        if denominator:
            samples.append(numerator / denominator)
    if not samples:
        return None
    return {"low": _percentile(samples, 0.025), "high": _percentile(samples, 0.975)}


def _matrix(counts: Counter[tuple[str, str]], labels: tuple[str, ...]) -> dict[str, Any]:
    return {
        "labels": [LABEL_NAMES[label] for label in labels],
        "actual_rows_predicted_columns": [
            [counts[(actual, predicted)] for predicted in labels] for actual in labels
        ],
    }


def _score_group(
    rows: list[dict[str, Any]],
    domains: tuple[str, ...],
    rng: random.Random,
    replicates: int,
) -> dict[str, Any]:
    expected_count = observed_count = scored_count = exact_matches = binary_matches = 0
    exact_matrix: Counter[tuple[str, str]] = Counter()
    binary_matrix: Counter[tuple[str, str]] = Counter()
    exact_scored_by_trial: Counter[str] = Counter()
    exact_expected_by_trial: Counter[str] = Counter()
    exact_trial_expected: Counter[str] = Counter()
    binary_scored_by_trial: Counter[str] = Counter()
    binary_expected_by_trial: Counter[str] = Counter()
    binary_trial_expected: Counter[str] = Counter()
    overcalls = undercalls = overcall_steps = undercall_steps = 0
    false_positives = false_negatives = 0
    high_actual = high_predicted = high_true_positive = 0
    causes: Counter[str] = Counter()
    ordinal = {label: index for index, label in enumerate(LABELS)}

    for row in rows:
        trial_id = row["trial_id"]
        expected = row.get("expected", {})
        observed = row.get("observed", {})
        if row["scope"] != "eligible":
            continue
        for domain in domains:
            actual = expected[domain]
            prediction = observed.get(domain)
            expected_count += 1
            exact_trial_expected[trial_id] += 1
            binary_trial_expected[trial_id] += 1
            if actual == "high":
                high_actual += 1
            if prediction is None:
                causes[row.get("failure_causes", {}).get(domain, "delivery_unknown")] += 1
                continue
            observed_count += 1
            exact_expected_by_trial[trial_id] += int(actual == prediction)
            binary_expected_by_trial[trial_id] += int((actual == "low") == (prediction == "low"))
            if prediction == "high":
                high_predicted += 1
            scored_count += 1
            is_exact = actual == prediction
            is_binary = (actual == "low") == (prediction == "low")
            exact_matches += int(is_exact)
            binary_matches += int(is_binary)
            exact_scored_by_trial[trial_id] += int(is_exact)
            binary_scored_by_trial[trial_id] += int(is_binary)
            exact_matrix[(actual, prediction)] += 1
            binary_actual = "low" if actual == "low" else "non_low"
            binary_prediction = "low" if prediction == "low" else "non_low"
            binary_matrix[(binary_actual, binary_prediction)] += 1
            if actual == "high":
                high_true_positive += int(prediction == "high")
            if actual == "low" and prediction != "low":
                false_positives += 1
            if actual != "low" and prediction == "low":
                false_negatives += 1
            delta = ordinal[prediction] - ordinal[actual]
            if delta > 0:
                overcalls += 1
                overcall_steps += delta
            elif delta < 0:
                undercalls += 1
                undercall_steps += -delta
            if not is_exact:
                causes[row.get("failure_causes", {}).get(domain, "delivery_unknown")] += 1

    exact_scored_trials = {
        trial: (
            exact_scored_by_trial[trial],
            sum(
                1
                for row in rows
                if row["scope"] == "eligible" and row["trial_id"] == trial
                for domain in domains
                if domain in row.get("observed", {})
            ),
        )
        for trial in exact_trial_expected
    }
    binary_scored_trials = {
        trial: (binary_scored_by_trial[trial], exact_scored_trials[trial][1])
        for trial in exact_trial_expected
    }
    exact_all_trials = {
        trial: (exact_expected_by_trial[trial], exact_trial_expected[trial])
        for trial in exact_trial_expected
    }
    binary_all_trials = {
        trial: (binary_expected_by_trial[trial], binary_trial_expected[trial])
        for trial in binary_trial_expected
    }
    return {
        "expected_outputs": expected_count,
        "observed_outputs": observed_count,
        "scored_outputs": scored_count,
        "exact_agreement": {
            "matches": exact_matches,
            "scored_rate": _rate(exact_matches, scored_count),
            "all_expected_rate": _rate(exact_matches, expected_count),
            "trial_clustered_95ci_scored": _cluster_interval(exact_scored_trials, rng, replicates),
            "trial_clustered_95ci_all_expected": _cluster_interval(
                exact_all_trials, rng, replicates
            ),
        },
        "binary_low_vs_non_low": {
            "matches": binary_matches,
            "scored_rate": _rate(binary_matches, scored_count),
            "all_expected_rate": _rate(binary_matches, expected_count),
            "trial_clustered_95ci_scored": _cluster_interval(binary_scored_trials, rng, replicates),
            "trial_clustered_95ci_all_expected": _cluster_interval(
                binary_all_trials, rng, replicates
            ),
            "confusion_matrix": _matrix(binary_matrix, ("low", "non_low")),
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        },
        "confusion_matrix": _matrix(exact_matrix, LABELS),
        "direction_errors": {
            "overcalls": overcalls,
            "overcall_steps": overcall_steps,
            "undercalls": undercalls,
            "undercall_steps": undercall_steps,
        },
        "high_class": {
            "reference_high": high_actual,
            "predicted_high": high_predicted,
            "true_positive_high": high_true_positive,
            "sensitivity": _rate(high_true_positive, high_actual),
            "sensitivity_status": (
                "estimable" if high_actual else "unestimable_no_reference_high_cases"
            ),
        },
        "failure_causes": dict(sorted(causes.items())),
    }


def analyze(value: object, *, bootstrap_replicates: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Score all declared cases without selecting a best attempt or hiding omissions."""
    if isinstance(bootstrap_replicates, bool) or not isinstance(bootstrap_replicates, int):
        raise ValueError("bootstrap_replicates must be an integer")
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be non-negative")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rows = _validate_input(value)
    eligible = [row for row in rows if row["scope"] == "eligible"]
    uncertain = [row for row in rows if row["scope"] == "scope_uncertain"]
    ineligible = [row for row in rows if row["scope"] == "ineligible"]
    rng = random.Random(seed)
    per_domain = {
        domain: _score_group(eligible, (domain,), rng, bootstrap_replicates) for domain in DOMAINS
    }
    pooled = _score_group(eligible, DOMAINS, rng, bootstrap_replicates)
    known_costs = [row["cost_usd"] for row in rows if row.get("cost_usd") is not None]
    finalized = sum(row["completion"] == "finalized" for row in eligible)
    completion_counts = dict(sorted(Counter(row["completion"] for row in rows).items()))
    return {
        "schema": "rob2-kit.rsi-run-analysis-result.v1",
        "scope": {
            "all_runs": len(rows),
            "eligible_cases": len(eligible),
            "scope_uncertain_cases": len(uncertain),
            "ineligible_cases": len(ineligible),
            "scope_uncertain_by_completion": dict(
                sorted(Counter(row["completion"] for row in uncertain).items())
            ),
        },
        "completion": {
            "counts_all_runs": completion_counts,
            "finalized_eligible_cases": finalized,
            "expected_eligible_cases": len(eligible),
            "eligible_case_rate": _rate(finalized, len(eligible)),
            "expected_domain_outputs": len(eligible) * len(DOMAINS),
        },
        "per_domain": per_domain,
        "pooled_domains": pooled,
        "cost_usd": {
            "known_run_count": len(known_costs),
            "unknown_run_count": len(rows) - len(known_costs),
            "known_total": sum(known_costs) if known_costs else None,
            "mean_known_per_run": sum(known_costs) / len(known_costs) if known_costs else None,
        },
        "bootstrap": {
            "method": "percentile bootstrap resampling whole Trials with replacement",
            "replicates": bootstrap_replicates,
            "seed": seed,
        },
        "qualification": (
            "provisional label agreement only; not an estimate of scientific accuracy; "
            "no automatic pass/fail threshold"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Restricted, posthoc JSON labels and run outcomes")
    parser.add_argument("--output", type=Path, help="Write result JSON here instead of stdout")
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8") as stream:
            result = analyze(
                json.load(stream),
                bootstrap_replicates=args.bootstrap_replicates,
                seed=args.seed,
            )
        serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"RSI analysis rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
