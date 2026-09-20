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

from rob2_kit.evaluation.adjudication import validate_sidecars

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
            "reference_available",
            "reference_availability",
            "scope_comparable",
            "scope_comparability",
            "latency_ms",
            "attempts",
            "selected_attempt_id",
            "diagnostic",
            "trace",
            "artifacts",
            "result_identity",
            "source_versions",
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
        latency = row.get("latency_ms")
        if latency is not None and (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ValueError(f"{location}.latency_ms must be non-negative or null")
        causes = row.get("failure_causes", {})
        if not isinstance(causes, dict) or set(causes) - set(DOMAINS):
            raise ValueError(f"{location}.failure_causes must map Domain IDs to causes")
        for domain, cause in causes.items():
            if not isinstance(cause, str) or cause not in FAILURE_CAUSES:
                raise ValueError(f"{location}.failure_causes.{domain} is invalid")
        for field_name in (
            "reference_available",
            "reference_availability",
            "scope_comparable",
            "scope_comparability",
        ):
            mapping = row.get(field_name)
            if mapping is None:
                continue
            if not isinstance(mapping, dict) or set(mapping) - set(DOMAINS):
                raise ValueError(f"{location}.{field_name} must map Domain IDs")
            for domain, flag in mapping.items():
                if type(flag) is not bool:
                    raise ValueError(f"{location}.{field_name}.{domain} must be boolean")
        attempts = row.get("attempts")
        if attempts is not None:
            if not isinstance(attempts, list) or not attempts:
                raise ValueError(f"{location}.attempts must be a non-empty list")
            attempt_ids: set[str] = set()
            selected_count = 0
            selected_ids: set[str] = set()
            for attempt_index, attempt in enumerate(attempts):
                attempt_location = f"{location}.attempts[{attempt_index}]"
                if not isinstance(attempt, dict):
                    raise ValueError(f"{attempt_location} must be an object")
                allowed_attempt_fields = {
                    "attempt_id",
                    "observed",
                    "cost_usd",
                    "latency_ms",
                    "completion",
                    "status",
                    "selected",
                    "failure_causes",
                    "exit_code",
                }
                if set(attempt) - allowed_attempt_fields:
                    raise ValueError(f"{attempt_location} contains unsupported fields")
                attempt_id = attempt.get("attempt_id")
                if not isinstance(attempt_id, str) or not attempt_id.strip():
                    raise ValueError(f"{attempt_location}.attempt_id must be non-empty text")
                if attempt_id in attempt_ids:
                    raise ValueError(f"{attempt_location}.attempt_id is duplicated")
                attempt_ids.add(attempt_id)
                attempt_observed = attempt.get("observed", {})
                if not isinstance(attempt_observed, dict) or set(attempt_observed) - set(DOMAINS):
                    raise ValueError(f"{attempt_location}.observed must map known Domains")
                for domain, label in attempt_observed.items():
                    if not isinstance(label, str) or label not in LABELS:
                        raise ValueError(f"{attempt_location}.observed.{domain} is invalid")
                for numeric_name in ("cost_usd", "latency_ms"):
                    numeric = attempt.get(numeric_name)
                    if numeric is not None and (
                        isinstance(numeric, bool)
                        or not isinstance(numeric, (int, float))
                        or not math.isfinite(numeric)
                        or numeric < 0
                    ):
                        raise ValueError(
                            f"{attempt_location}.{numeric_name} must be non-negative or null"
                        )
                if "completion" in attempt and (
                    not isinstance(attempt["completion"], str)
                    or attempt["completion"] not in COMPLETION
                ):
                    raise ValueError(f"{attempt_location}.completion is invalid")
                if "selected" in attempt:
                    if type(attempt["selected"]) is not bool:
                        raise ValueError(f"{attempt_location}.selected must be boolean")
                    if attempt["selected"]:
                        selected_count += 1
                        selected_ids.add(attempt_id)
            if selected_count > 1:
                raise ValueError(f"{location}.attempts must select at most one attempt")
            selected_id = row.get("selected_attempt_id")
            if selected_id is not None and (
                not isinstance(selected_id, str) or selected_id not in attempt_ids
            ):
                raise ValueError(f"{location}.selected_attempt_id is not present in attempts")
            if selected_id is not None and selected_ids and selected_id not in selected_ids:
                raise ValueError(f"{location}.selected_attempt_id disagrees with attempts.selected")
        elif row.get("selected_attempt_id") is not None:
            raise ValueError(f"{location}.selected_attempt_id requires attempts")
        validated.append(row)
    return validated


def _validated_adjudications(
    value: object, case_ids: set[str]
) -> list[dict[str, Any]]:
    """Validate optional evidence-grounded labels without joining them to scores."""

    raw = value.get("adjudications", []) if isinstance(value, dict) else []
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("adjudications must be a list")
    try:
        records = validate_sidecars(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"adjudications are invalid: {error}") from error
    if any(record.case_identity not in case_ids for record in records):
        raise ValueError("adjudication references an unknown benchmark case")
    return [record.model_dump(mode="json", by_alias=True) for record in records]


def _adjudication_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize reviewer classifications; never turn them into corrected labels."""

    classifications = Counter(
        record["classification"] for record in records if isinstance(record, dict)
    )
    return {
        "schema": "rob2-kit.adjudication-sidecar.v1",
        "record_count": len(records),
        "case_count": len(
            {record["case_identity"] for record in records if isinstance(record, dict)}
        ),
        "by_classification": dict(sorted(classifications.items())),
        "qualification": (
            "reviewer classifications are reported separately from provisional-label agreement; "
            "they do not correct observed labels or estimate scientific accuracy"
        ),
    }


def _domain_flags(row: dict[str, Any], field: str, domains: tuple[str, ...]) -> dict[str, bool]:
    aliases = {
        "reference_available": ("reference_available", "reference_availability"),
        "scope_comparable": ("scope_comparable", "scope_comparability"),
    }
    mapping = next(
        (row.get(name) for name in aliases[field] if isinstance(row.get(name), dict)),
        None,
    )
    expected = row.get("expected", {})
    if not isinstance(expected, dict):
        expected = {}
    default = field == "reference_available"
    result = {
        domain: bool(mapping[domain])
        if isinstance(mapping, dict) and domain in mapping
        else (domain in expected if default else True)
        for domain in domains
    }
    return result


def _selected_attempt(row: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    attempts = row.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        observed = row.get("observed", {})
        return (dict(observed) if isinstance(observed, dict) else {}, None)
    selected_id = row.get("selected_attempt_id")
    selected = next(
        (
            attempt
            for attempt in attempts
            if isinstance(attempt, dict)
            and (
                attempt.get("attempt_id") == selected_id
                or (selected_id is None and attempt.get("selected") is True)
            )
        ),
        None,
    )
    if selected is None:
        selected = attempts[0]
    attempt_observed = selected.get("observed", {}) if isinstance(selected, dict) else {}
    if not attempt_observed and isinstance(row.get("observed"), dict):
        attempt_observed = row["observed"]
    return (
        dict(attempt_observed),
        str(selected.get("attempt_id")) if isinstance(selected, dict) else None,
    )


def _attempt_accounting(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for row in rows:
        row_attempts = row.get("attempts")
        if isinstance(row_attempts, list):
            for attempt in row_attempts:
                if isinstance(attempt, dict):
                    attempts.append(attempt)
        else:
            attempts.append(
                {
                    "attempt_id": row.get("case_id"),
                    "cost_usd": row.get("cost_usd"),
                    "latency_ms": row.get("latency_ms"),
                }
            )
    known_costs = [
        float(attempt["cost_usd"])
        for attempt in attempts
        if isinstance(attempt.get("cost_usd"), (int, float))
        and not isinstance(attempt.get("cost_usd"), bool)
    ]
    latencies = [
        float(attempt["latency_ms"])
        for attempt in attempts
        if isinstance(attempt.get("latency_ms"), (int, float))
        and not isinstance(attempt.get("latency_ms"), bool)
    ]
    return {
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - len(rows)),
        "known_attempt_cost_count": len(known_costs),
        "unknown_attempt_cost_count": len(attempts) - len(known_costs),
        "known_attempt_cost_total": sum(known_costs) if known_costs else None,
        "known_attempt_latency_count": len(latencies),
        "unknown_attempt_latency_count": len(attempts) - len(latencies),
        "known_attempt_latency_total_ms": sum(latencies) if latencies else None,
    }


_DIAGNOSTIC_STAGES = (
    "approved_result",
    "source_version",
    "delivered_passage",
    "selected_evidence",
    "justification",
    "answer",
    "revisions",
    "rule",
)
_FAILURE_STAGE = {
    "passage_not_found": "delivered_passage",
    "passage_not_delivered": "delivered_passage",
    "citation_incomplete": "selected_evidence",
    "interpretation_error": "justification",
    "scope_error": "approved_result",
    "workflow_incomplete": "answer",
    "infrastructure": "answer",
}


def _diagnostic_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Project retained joins without copying source-bearing private traces."""

    cases: list[dict[str, Any]] = []
    for row in rows:
        trace = row.get("diagnostic")
        if not isinstance(trace, dict):
            trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
        artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}
        selected_id = _selected_attempt(row)[1]
        domains: dict[str, Any] = {}
        for domain in DOMAINS:
            domain_trace = trace.get(domain) if isinstance(trace.get(domain), dict) else trace
            cause = row.get("failure_causes", {}).get(domain)
            stages: dict[str, dict[str, Any]] = {}
            missing_stage: str | None = None
            for stage in _DIAGNOSTIC_STAGES:
                raw = domain_trace.get(stage) if isinstance(domain_trace, dict) else None
                if isinstance(raw, dict):
                    available = bool(
                        raw.get("available", raw.get("status") in {"present", "complete"})
                    )
                    stage_identity = raw.get("identity")
                else:
                    available = bool(raw) if isinstance(raw, bool) else raw is not None
                    stage_identity = (
                        raw if isinstance(raw, str) and raw.startswith("sha256:") else None
                    )
                if stage == "approved_result" and row.get("result_identity") is not None:
                    available = True
                    stage_identity = row.get("result_identity")
                if stage == "source_version" and isinstance(row.get("source_versions"), dict):
                    available = domain in row["source_versions"]
                    stage_identity = row["source_versions"].get(domain)
                stages[stage] = {
                    "status": "present" if available else "missing",
                    "identity": stage_identity if isinstance(stage_identity, str) else None,
                }
                if missing_stage is None and not available:
                    missing_stage = stage
            if cause in _FAILURE_STAGE:
                earliest = _FAILURE_STAGE[cause]
                classification = cause
            elif cause == "other":
                earliest = missing_stage
                classification = "unresolved"
            elif missing_stage is not None:
                earliest = missing_stage
                classification = "unresolved"
            else:
                earliest = None
                classification = "defensible_or_agreement"
            domains[domain] = {
                "stages": stages,
                "earliest_failure_stage": earliest,
                "classification": classification,
                "reference_available": _domain_flags(row, "reference_available", (domain,))[domain],
                "scope_comparable": _domain_flags(row, "scope_comparable", (domain,))[domain],
            }
        cases.append(
            {
                "case_id": row["case_id"],
                "trial_id": row["trial_id"],
                "outcome": row["outcome"],
                "result_identity": row.get("result_identity"),
                "selected_attempt_id": selected_id,
                "attempt_ids": [
                    attempt.get("attempt_id")
                    for attempt in row.get("attempts", [])
                    if isinstance(attempt, dict)
                ]
                or [row["case_id"]],
                "domains": domains,
                "artifact_identities": {
                    key: value
                    for key, value in artifacts.items()
                    if key.endswith("_identity") and isinstance(value, str)
                },
            }
        )
    return {
        "version": "rob2-kit.rsi-diagnostic-ledger.v1",
        "stage_order": list(_DIAGNOSTIC_STAGES),
        "cases": cases,
    }


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
    expected_count = labelled_count = observed_count = scored_count = 0
    exact_matches = binary_matches = 0
    exact_matrix: Counter[tuple[str, str]] = Counter()
    binary_matrix: Counter[tuple[str, str]] = Counter()
    exact_scored_by_trial: Counter[str] = Counter()
    exact_expected_by_trial: Counter[str] = Counter()
    exact_trial_expected: Counter[str] = Counter()
    comparable_trial_expected: Counter[str] = Counter()
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
        observed, _selected_attempt_id = _selected_attempt(row)
        if row["scope"] != "eligible":
            continue
        reference_flags = _domain_flags(row, "reference_available", domains)
        comparable_flags = _domain_flags(row, "scope_comparable", domains)
        for domain in domains:
            actual = expected.get(domain)
            prediction = observed.get(domain)
            expected_count += 1
            exact_trial_expected[trial_id] += 1
            binary_trial_expected[trial_id] += 1
            has_reference = reference_flags[domain] and actual in LABELS
            if has_reference:
                labelled_count += 1
            if has_reference and actual == "high":
                high_actual += 1
            if prediction is None:
                causes[row.get("failure_causes", {}).get(domain, "delivery_unknown")] += 1
                continue
            observed_count += 1
            if prediction == "high":
                high_predicted += 1
            if not has_reference or not comparable_flags[domain]:
                continue
            comparable_trial_expected[trial_id] += 1
            exact_expected_by_trial[trial_id] += int(actual == prediction)
            binary_expected_by_trial[trial_id] += int((actual == "low") == (prediction == "low"))
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
            comparable_trial_expected[trial],
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
        "operational_expected_outputs": expected_count,
        "labelled_opportunities": labelled_count,
        "observed_outputs": observed_count,
        "comparable_pairs": scored_count,
        "scored_outputs": scored_count,
        "exact_agreement": {
            "matches": exact_matches,
            "scored_rate": _rate(exact_matches, scored_count),
            "all_expected_rate": _rate(exact_matches, expected_count),
            "labelled_rate": _rate(exact_matches, labelled_count),
            "trial_clustered_95ci_scored": _cluster_interval(exact_scored_trials, rng, replicates),
            "trial_clustered_95ci_all_expected": _cluster_interval(
                exact_all_trials, rng, replicates
            ),
        },
        "binary_low_vs_non_low": {
            "matches": binary_matches,
            "scored_rate": _rate(binary_matches, scored_count),
            "all_expected_rate": _rate(binary_matches, expected_count),
            "labelled_rate": _rate(binary_matches, labelled_count),
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
    adjudications = _validated_adjudications(value, {row["case_id"] for row in rows})
    eligible = [row for row in rows if row["scope"] == "eligible"]
    uncertain = [row for row in rows if row["scope"] == "scope_uncertain"]
    ineligible = [row for row in rows if row["scope"] == "ineligible"]
    rng = random.Random(seed)
    per_domain = {
        domain: _score_group(eligible, (domain,), rng, bootstrap_replicates) for domain in DOMAINS
    }
    pooled = _score_group(eligible, DOMAINS, rng, bootstrap_replicates)
    per_outcome = {
        outcome: _score_group(
            [row for row in eligible if row["outcome"] == outcome],
            DOMAINS,
            rng,
            bootstrap_replicates,
        )
        for outcome in sorted({row["outcome"] for row in eligible})
    }
    attempt_metrics = _attempt_accounting(rows)
    has_extended_metadata = any(
        any(
            key in row
            for key in (
                "reference_available",
                "reference_availability",
                "scope_comparable",
                "scope_comparability",
                "attempts",
                "selected_attempt_id",
                "diagnostic",
                "trace",
                "artifacts",
                "result_identity",
                "source_versions",
                "latency_ms",
            )
        )
        for row in rows
    )
    if has_extended_metadata:
        provisional_rows = [
            {
                **row,
                "reference_available": {domain: True for domain in DOMAINS},
                "scope_comparable": {domain: True for domain in DOMAINS},
            }
            for row in eligible
        ]
        provisional_per_domain = {
            domain: _score_group(provisional_rows, (domain,), rng, bootstrap_replicates)
            for domain in DOMAINS
        }
        provisional_pooled = _score_group(provisional_rows, DOMAINS, rng, bootstrap_replicates)
    else:
        provisional_per_domain = None
        provisional_pooled = None
    if any(isinstance(row.get("attempts"), list) for row in rows):
        known_run_count = attempt_metrics["known_attempt_cost_count"]
        unknown_run_count = attempt_metrics["unknown_attempt_cost_count"]
        known_total = attempt_metrics["known_attempt_cost_total"]
        mean_known = known_total / known_run_count if known_run_count else None
    else:
        known_costs = [row["cost_usd"] for row in rows if row.get("cost_usd") is not None]
        known_run_count = len(known_costs)
        unknown_run_count = len(rows) - len(known_costs)
        known_total = sum(known_costs) if known_costs else None
        mean_known = known_total / len(known_costs) if known_costs else None
    finalized = sum(row["completion"] == "finalized" for row in eligible)
    completion_counts = dict(sorted(Counter(row["completion"] for row in rows).items()))
    result = {
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
            "known_run_count": known_run_count,
            "unknown_run_count": unknown_run_count,
            "known_total": known_total,
            "mean_known_per_run": mean_known,
        },
        "attempts": {
            **attempt_metrics,
            "selection": (
                "explicit selected_attempt_id, selected=true, otherwise first in input order"
            ),
            "selected_attempts": {row["case_id"]: _selected_attempt(row)[1] for row in rows},
        },
        "per_outcome": per_outcome,
        "diagnostics": _diagnostic_ledger(rows),
        "adjudication": _adjudication_summary(adjudications),
        "bootstrap": {
            "method": "percentile bootstrap resampling whole Trials with replacement",
            "replicates": bootstrap_replicates,
            "seed": seed,
        },
        "qualification": (
            "provisional label agreement only; not an estimate of scientific accuracy; "
            "no automatic pass/fail threshold; exposed-cohort evidence is not a holdout "
            "and does not establish generalization or repeatability"
        ),
    }
    latency_summary = {
        "known_run_count": attempt_metrics["known_attempt_latency_count"],
        "unknown_run_count": attempt_metrics["unknown_attempt_latency_count"],
        "known_total_ms": attempt_metrics["known_attempt_latency_total_ms"],
        "mean_known_per_run_ms": (
            attempt_metrics["known_attempt_latency_total_ms"]
            / attempt_metrics["known_attempt_latency_count"]
            if attempt_metrics["known_attempt_latency_count"]
            else None
        ),
    }
    result["latency_ms"] = latency_summary
    if any(isinstance(row.get("attempts"), list) for row in rows):
        result["cost_usd"]["attempts"] = attempt_metrics
    if has_extended_metadata:
        result["provisional_per_domain"] = provisional_per_domain
        result["provisional_pooled_domains"] = provisional_pooled
    return result


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
