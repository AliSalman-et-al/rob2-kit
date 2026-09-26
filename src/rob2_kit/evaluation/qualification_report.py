"""Validate a privacy-safe integrated qualification report.

The report is deliberately a receipt, not a scorer.  It records what was
checked and what the host exposed; an inaccessible host observation can never
be converted into a passing observation by this module.

Version 1 remains readable for historical reports.  Version 2 is intentionally
not a drop-in extension: it must carry a complete qualification comparison
receipt and joins its campaign, attempts, and deterministic metrics to that
receipt before a promotion decision can be accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any

SCHEMA = "rob2-kit.integrated-qualification.v1"
HISTORICAL_QUALIFICATION_SCHEMA = "rob2-kit.integrated-qualification.v2"
QUALIFICATION_SCHEMA = "rob2-kit.integrated-qualification.v3"
QUALIFICATION_COMPARISON_RUN_SCHEMA = "rob2-kit.evaluation-comparison-run.v0.2"
PROMOTIONS = frozenset({"promote", "hold"})
STATUSES = frozenset(
    {
        "gain",
        "regression",
        "unsupported_reassurance",
        "concern",
        "scope_correction",
        "completion",
        "failure",
        "context",
        "latency",
        "cost",
    }
)
MECHANICAL_KINDS = frozenset(
    {
        "build",
        "pack",
        "skill",
        "source",
        "config",
        "integrity",
        "formatting",
        "types",
        "full_test_suite",
        "public_contract",
        "bundle_verification",
    }
)
OBSERVATION_KINDS = frozenset({"text", "image", "guidance", "schema", "continuation"})
HOST_CHECK_KINDS = frozenset(
    {"tool", "structured", "text", "image", "continuation", "compaction", "restart", "review"}
)
_REQUIRED_MECHANICAL_KINDS = frozenset(
    {"formatting", "types", "full_test_suite", "public_contract", "bundle_verification"}
)
_LABELS = ("low", "some_concerns", "high")
_AGGREGATION_POLICY = "ADR-0035-current-deterministic-cochrane-v1"
ATTEMPT_STATUSES = STATUSES
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PRIVATE = frozenset(
    {
        "path",
        "paths",
        "source",
        "sources",
        "content",
        "prompt",
        "prompts",
        "trace",
        "traces",
        "credential",
        "credentials",
        "rationale",
        "transcript",
        "transcripts",
    }
)
_DELIVERIES = frozenset({"success", "repairable_error", "unobservable"})
_QUALIFICATION_METRICS = (
    "result_scope",
    "decisive_claim_validity",
    "premise_support",
    "counterevidence",
    "unsupported_concern",
    "unsupported_reassurance",
    "provisional_agreement",
    "completion",
)
_HISTORICAL_QUALIFICATION_METRICS = tuple(
    metric for metric in _QUALIFICATION_METRICS if metric != "decisive_claim_validity"
)
_QUALIFICATION_TOTALS = ("context_bytes", "calls", "latency", "cost")
_QUALIFICATION_REPORT_FIELDS = {
    "schema",
    "identity",
    "campaign",
    "metrics",
    "mechanical",
    "observations",
    "attempts",
    "host_checks",
    "diagnostics",
    "promotion",
    "claim",
    "comparison",
}
_HISTORICAL_QUALIFICATION_REPORT_FIELDS = _QUALIFICATION_REPORT_FIELDS - {
    "host_checks",
    "diagnostics",
}
_QUALIFICATION_CAMPAIGN_FIELDS = {
    "campaign_id",
    "split",
    "conditions",
    "attempt_policy",
    "platforms",
    "controls",
}
_QUALIFICATION_SPLIT_FIELDS = {"kind", "development_trials", "holdout_trials"}
_QUALIFICATION_CONDITION_FIELDS = {"baseline", "successor"}
_QUALIFICATION_ATTEMPT_FIELDS = {"draws_per_cell", "selection"}
_QUALIFICATION_PLATFORM_FIELDS = {
    "id",
    "host",
    "model_family",
    "model_version",
    "effort",
}
_QUALIFICATION_COMPARISON_FIELDS = {
    "receipt",
    "receipt_identity",
    "campaign_identity",
    "attempt_identity",
    "metric_identity",
    "report_metrics_identity",
}
_QUALIFICATION_RECEIPT_FIELDS = {
    "schema",
    "config_identity",
    "plan_identity",
    "campaign_identity",
    "configuration",
    "campaign",
    "plan",
    "interventions",
    "outcomes",
    "metrics",
    "retained_outcome_count",
    "outcome_identity",
    "metric_identity",
    "receipt_identity",
}
_QUALIFICATION_REPORT_ATTEMPT_FIELDS = {
    "attempt_id",
    "host",
    "status",
    "platform_id",
    "arm_id",
    "cell_id",
    "draw",
}
_QUALIFICATION_MECHANICAL_FIELDS = {
    "check_id",
    "kind",
    "result",
    "artifact_identity",
}
_QUALIFICATION_HOST_CHECK_FIELDS = {
    "platform_id",
    "host",
    "model_family",
    "kind",
    "result",
    "artifact_identity",
}
_QUALIFICATION_RESULTS = frozenset({"passed", "failed", "missing"})
_DIAGNOSTIC_RATE_FIELDS = {
    "provisional_agreement",
    "result_scope",
    "decisive_claim_validity",
    "non_low",
}
_DIAGNOSTIC_ARM_FIELDS = _DIAGNOSTIC_RATE_FIELDS | {
    "confusion",
    "class_support",
    "predicted_support",
    "high_support",
    "uncertainty",
    "completion",
    "cost",
}
_DIAGNOSTICS_FIELDS = {
    "schema",
    "source_artifact_identity",
    "scorer",
    "arms",
    "aggregation",
}
_AGGREGATION_FIELDS = {
    "policy_id",
    "policy_version",
    "reference_basis",
    "source_artifact_identity",
    "agreement",
    "confusion",
    "uncertainty",
}
_LABEL_METRIC_FIELDS = frozenset(
    {
        "provisional_agreement",
        "scientific_accuracy",
        "class_recall",
        "left_provisional_agreement",
        "right_provisional_agreement",
        "left_accuracy",
        "right_accuracy",
    }
)
_QUALIFICATION_ATTEMPT_STATUSES = frozenset(
    {"assessed", "needs_input", "failed", "draw", "scope_correction"}
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def identity(value: Any) -> str:
    """Return the canonical identity for a JSON-serializable frozen value."""
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _private(value: Any, location: str = "$") -> list[str]:
    if isinstance(value, dict):
        errors = [
            f"{location}: private field {key!r}"
            for key in value
            if isinstance(key, str)
            and key.casefold() in _PRIVATE
            and not (location in {"$.identity", "$.qualification"} and key == "source")
        ]
        return errors + [
            error for key, child in value.items() for error in _private(child, f"{location}.{key}")
        ]
    if isinstance(value, list):
        return [
            error
            for index, child in enumerate(value)
            for error in _private(child, f"{location}[{index}]")
        ]
    if isinstance(value, str) and ("/" in value or "\\" in value):
        return [f"{location}: paths are forbidden"]
    return []


def _closed(row: object, fields: set[str], location: str, errors: list[str]) -> bool:
    if not isinstance(row, dict) or set(row) != fields:
        errors.append(f"{location} has an unclosed field set")
        return False
    return True


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _valid_status(value: object) -> bool:
    return isinstance(value, str) and value in STATUSES


def _metric_rate(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator", "rate"}:
        errors.append(f"{location} has an invalid rate metric")
        return
    numerator = value["numerator"]
    denominator = value["denominator"]
    rate = value["rate"]
    if (
        type(numerator) is not int
        or numerator < 0
        or type(denominator) is not int
        or denominator < 0
        or numerator > denominator
        or type(rate) not in (int, float)
        or isinstance(rate, bool)
        or not 0 <= rate <= 1
        or rate != (numerator / denominator if denominator else 0.0)
    ):
        errors.append(f"{location} is not a deterministic rate")


def _metric_total(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"total"}:
        errors.append(f"{location} has an invalid total metric")
        return
    total = value["total"]
    if (
        type(total) not in (int, float)
        or isinstance(total, bool)
        or not math.isfinite(total)
        or total < 0
    ):
        errors.append(f"{location} is not a non-negative total")


def _metric_count(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"count"}:
        errors.append(f"{location} has an invalid count metric")
        return
    count = value["count"]
    if type(count) is not int or count < 0:
        errors.append(f"{location} is not a non-negative count")


def _digest(value: Any) -> str:
    """Use the comparison harness' canonical JSON digest format."""

    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _without_label_metrics(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_label_metrics(item)
            for key, item in value.items()
            if key not in _LABEL_METRIC_FIELDS
        }
    if isinstance(value, list):
        return [_without_label_metrics(item) for item in value]
    return value


def _bound_identity(receipt_identity: object, value: object) -> str:
    return identity({"receipt_identity": receipt_identity, "value": value})


def bind_comparison(report: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Bind a v3 report to one complete qualification comparison receipt.

    The returned copy keeps the full privacy-safe receipt so an independent
    validator can replay configuration, outcome, and metric joins without
    trusting a detached campaign summary.
    """

    if report.get("schema") != QUALIFICATION_SCHEMA:
        raise ValueError(
            "comparison binding requires the integrated qualification report v3 schema"
        )
    if receipt.get("schema") != QUALIFICATION_COMPARISON_RUN_SCHEMA:
        raise ValueError("comparison binding requires a qualification comparison receipt")
    if not isinstance(receipt.get("receipt_identity"), str):
        raise ValueError("comparison receipt is missing its deterministic identity")
    bound = deepcopy(report)
    bound["comparison"] = {
        "receipt": deepcopy(receipt),
        "receipt_identity": receipt["receipt_identity"],
        "campaign_identity": receipt.get("campaign_identity"),
        "attempt_identity": _bound_identity(receipt.get("outcome_identity"), bound.get("attempts")),
        "metric_identity": receipt.get("metric_identity"),
        "report_metrics_identity": _bound_identity(
            receipt.get("receipt_identity"),
            {"metrics": bound.get("metrics"), "diagnostics": bound.get("diagnostics")},
        ),
    }
    return bound


def _validate_source_identity(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        errors.append(f"{location} must identify its source artifact")


def _validate_confusion(
    value: object, location: str, errors: list[str]
) -> tuple[dict[str, int], dict[str, int], int, int] | None:
    if not isinstance(value, dict) or set(value) != set(_LABELS):
        errors.append(f"{location} has an invalid three-class confusion matrix")
        return None
    rows: dict[str, int] = {}
    columns = dict.fromkeys(_LABELS, 0)
    for actual in _LABELS:
        row = value[actual]
        if not isinstance(row, dict) or set(row) != set(_LABELS):
            errors.append(f"{location}.{actual} has an invalid confusion row")
            return None
        if any(type(row[predicted]) is not int or row[predicted] < 0 for predicted in _LABELS):
            errors.append(f"{location}.{actual} has invalid confusion counts")
            return None
        rows[actual] = sum(row.values())
        for predicted in _LABELS:
            columns[predicted] += row[predicted]
    return rows, columns, sum(rows.values()), sum(value[label][label] for label in _LABELS)


def _validate_trial_interval(value: object, location: str, errors: list[str]) -> bool:
    fields = {"method", "clusters", "lower", "upper"}
    if not isinstance(value, dict) or set(value) != fields:
        errors.append(f"{location} has an invalid uncertainty interval")
        return False
    clusters = value["clusters"]
    if (
        value["method"] != "trial_cluster_percentile_bootstrap"
        or type(clusters) is not int
        or clusters < 0
    ):
        errors.append(f"{location} has invalid Trial-cluster uncertainty metadata")
        return False
    lower, upper = value["lower"], value["upper"]
    if clusters < 2:
        if lower is not None or upper is not None:
            errors.append(f"{location} must omit bounds with fewer than two Trial clusters")
            return False
        return False
    if (
        type(lower) not in (int, float)
        or type(upper) not in (int, float)
        or isinstance(lower, bool)
        or isinstance(upper, bool)
        or not 0 <= lower <= upper <= 1
    ):
        errors.append(f"{location} has invalid uncertainty bounds")
        return False
    return True


def _validate_diagnostics(value: object, campaign: object, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != _DIAGNOSTICS_FIELDS:
        errors.append("qualification diagnostics have an unclosed field set")
        return
    if value["schema"] != "rob2-kit.qualification-diagnostics.v1":
        errors.append("qualification diagnostics schema is invalid")
    _validate_source_identity(value["source_artifact_identity"], "diagnostics", errors)
    if not _valid_id(value["scorer"]):
        errors.append("diagnostics scorer identity is invalid")
    conditions = campaign.get("conditions") if isinstance(campaign, dict) else None
    arm_ids = (
        set(conditions.values())
        if isinstance(conditions, dict) and all(_valid_id(item) for item in conditions.values())
        else set()
    )
    arms = value["arms"]
    if not isinstance(arms, dict) or set(arms) != arm_ids or len(arm_ids) != 2:
        errors.append("diagnostics must report both declared comparison arms")
        return
    for arm_id, arm in arms.items():
        location = f"diagnostics.arms.{arm_id}"
        if not isinstance(arm, dict) or set(arm) != _DIAGNOSTIC_ARM_FIELDS:
            errors.append(f"{location} has an unclosed metric set")
            continue
        for metric in _DIAGNOSTIC_RATE_FIELDS:
            _metric_rate(arm[metric], f"{location}.{metric}", errors)
        matrix = _validate_confusion(arm["confusion"], f"{location}.confusion", errors)
        if matrix is None:
            continue
        row_support, predicted_support, total, correct = matrix
        for name, expected in (
            ("class_support", row_support),
            ("predicted_support", predicted_support),
        ):
            observed = arm[name]
            if (
                not isinstance(observed, dict)
                or set(observed) != set(_LABELS)
                or any(type(observed[label]) is not int or observed[label] < 0 for label in _LABELS)
            ):
                errors.append(f"{location}.{name} is invalid")
            elif observed != expected:
                errors.append(f"{location}.{name} does not match its confusion matrix")
        agreement = arm["provisional_agreement"]
        if isinstance(agreement, dict) and agreement.get("denominator") == total:
            if agreement.get("numerator") != correct:
                errors.append(f"{location} agreement does not match its confusion matrix")
        else:
            errors.append(f"{location} agreement denominator does not match its confusion matrix")
        non_low = arm["non_low"]
        non_low_correct = sum(
            arm["confusion"][actual][predicted]
            for actual in _LABELS[1:]
            for predicted in _LABELS[1:]
        )
        if isinstance(non_low, dict) and (
            non_low.get("numerator") != non_low_correct
            or non_low.get("denominator") != row_support["some_concerns"] + row_support["high"]
        ):
            errors.append(f"{location} non-Low support does not match its confusion matrix")
        high = arm["high_support"]
        if not isinstance(high, dict) or set(high) != {
            "reference",
            "predicted",
            "true_positive",
            "sensitivity",
        }:
            errors.append(f"{location}.high_support is invalid")
        elif (
            any(
                type(high[field]) is not int or high[field] < 0
                for field in ("reference", "predicted", "true_positive")
            )
            or high["reference"] != row_support["high"]
            or high["predicted"] != predicted_support["high"]
            or high["true_positive"] != arm["confusion"]["high"]["high"]
        ):
            errors.append(f"{location}.high_support does not match its confusion matrix")
        elif row_support["high"]:
            _metric_rate(high["sensitivity"], f"{location}.high_support.sensitivity", errors)
            expected_high_rate = {
                "numerator": arm["confusion"]["high"]["high"],
                "denominator": row_support["high"],
                "rate": arm["confusion"]["high"]["high"] / row_support["high"],
            }
            if high["sensitivity"] != expected_high_rate:
                errors.append(f"{location} High sensitivity does not match its confusion matrix")
        elif high["sensitivity"] is not None:
            errors.append(f"{location} High sensitivity must be unavailable without High support")
        _validate_trial_interval(arm["uncertainty"], f"{location}.uncertainty", errors)
        _metric_rate(arm["completion"], f"{location}.completion", errors)
        if (
            type(arm["cost"]) not in (int, float)
            or isinstance(arm["cost"], bool)
            or not math.isfinite(arm["cost"])
            or arm["cost"] < 0
        ):
            errors.append(f"{location}.cost is invalid")

    aggregation = value["aggregation"]
    if not isinstance(aggregation, dict) or set(aggregation) != _AGGREGATION_FIELDS:
        errors.append("diagnostics aggregation evaluation has an unclosed field set")
        return
    if (
        aggregation["policy_id"] != "ADR-0035"
        or aggregation["policy_version"] != _AGGREGATION_POLICY
        or aggregation["reference_basis"] != "provisional_overall_labels"
    ):
        errors.append("diagnostics must name the current ADR-0035 policy and its reference basis")
    _validate_source_identity(aggregation["source_artifact_identity"], "aggregation", errors)
    _metric_rate(aggregation["agreement"], "diagnostics.aggregation.agreement", errors)
    aggregate_matrix = _validate_confusion(
        aggregation["confusion"], "diagnostics.aggregation.confusion", errors
    )
    if aggregate_matrix is not None:
        _, _, total, correct = aggregate_matrix
        agreement = aggregation["agreement"]
        if not isinstance(agreement, dict) or (
            agreement.get("numerator") != correct or agreement.get("denominator") != total
        ):
            errors.append("diagnostics aggregation agreement does not match its confusion matrix")
    _validate_trial_interval(
        aggregation["uncertainty"], "diagnostics.aggregation.uncertainty", errors
    )


def _validate_qualification_extension(
    campaign: object,
    metrics: object,
    claim: object,
    diagnostics: object,
    errors: list[str],
    *,
    integrated: bool,
) -> None:
    if not isinstance(campaign, dict) or set(campaign) != _QUALIFICATION_CAMPAIGN_FIELDS:
        errors.append("campaign has an unclosed field set")
    else:
        if not _valid_id(campaign["campaign_id"]):
            errors.append("campaign id is invalid")
        split = campaign["split"]
        if not isinstance(split, dict) or set(split) != _QUALIFICATION_SPLIT_FIELDS:
            errors.append("campaign split has an unclosed field set")
        else:
            if split["kind"] != "trial_heldout":
                errors.append("campaign split is not Trial-held-out")
            trial_sets: list[set[str]] = []
            for name in ("development_trials", "holdout_trials"):
                values = split[name]
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not _valid_id(value) for value in values)
                    or len(set(values)) != len(values)
                ):
                    errors.append(f"campaign split {name} are invalid")
                else:
                    trial_sets.append(set(values))
            if len(trial_sets) == 2 and trial_sets[0] & trial_sets[1]:
                errors.append("campaign Trial-held-out split overlaps")
        conditions = campaign["conditions"]
        if (
            not isinstance(conditions, dict)
            or set(conditions) != _QUALIFICATION_CONDITION_FIELDS
            or not all(_valid_id(conditions.get(key)) for key in _QUALIFICATION_CONDITION_FIELDS)
            or conditions.get("baseline") == conditions.get("successor")
        ):
            errors.append("campaign conditions are invalid")
        attempt_policy = campaign["attempt_policy"]
        if (
            not isinstance(attempt_policy, dict)
            or set(attempt_policy) != _QUALIFICATION_ATTEMPT_FIELDS
            or type(attempt_policy.get("draws_per_cell")) is not int
            or not 1 <= attempt_policy.get("draws_per_cell", 0) <= 8
            or attempt_policy.get("selection") != "retain_all"
        ):
            errors.append("campaign attempt policy is invalid")
        platforms = campaign["platforms"]
        platform_ids: set[str] = set()
        hosts: set[str] = set()
        families: set[str] = set()
        if not isinstance(platforms, list) or not platforms:
            errors.append("campaign platforms must be a non-empty list")
        else:
            for index, platform in enumerate(platforms):
                location = f"campaign.platforms[{index}]"
                if (
                    not isinstance(platform, dict)
                    or set(platform) != _QUALIFICATION_PLATFORM_FIELDS
                ):
                    errors.append(f"{location} has an unclosed field set")
                    continue
                if (
                    any(not _valid_id(platform[key]) for key in _QUALIFICATION_PLATFORM_FIELDS)
                    or platform["id"] in platform_ids
                ):
                    errors.append(f"{location} identity is invalid")
                    continue
                platform_ids.add(platform["id"])
                hosts.add(platform["host"])
                families.add(platform["model_family"])
            if len(hosts) < 2 and len(families) < 2:
                errors.append("campaign requires two model families or materially different hosts")
        controls = campaign["controls"]
        if (
            not isinstance(controls, list)
            or len(controls) != 4
            or any(not isinstance(control, str) for control in controls)
            or set(controls) != {"D2", "D3", "D4", "D5"}
        ):
            errors.append("campaign controls must cover D2, D3, D4, and D5")

    metric_names = _QUALIFICATION_METRICS if integrated else _HISTORICAL_QUALIFICATION_METRICS
    if not isinstance(metrics, dict) or set(metrics) != set(metric_names) | set(
        _QUALIFICATION_TOTALS
    ) | {"errors"}:
        errors.append("qualification metrics are incomplete or unclosed")
    else:
        for metric in metric_names:
            _metric_rate(metrics[metric], f"metrics.{metric}", errors)
        _metric_count(metrics["errors"], "metrics.errors", errors)
        for metric in _QUALIFICATION_TOTALS:
            _metric_total(metrics[metric], f"metrics.{metric}", errors)

    if integrated:
        _validate_diagnostics(diagnostics, campaign, errors)

    if not isinstance(claim, dict) or set(claim) != {
        "decision",
        "scope",
        "adjudicated_scientific_accuracy",
    }:
        errors.append("qualification claim has an unclosed field set")
    else:
        if not isinstance(claim["decision"], str) or claim["decision"] not in PROMOTIONS:
            errors.append("qualification claim decision is invalid")
        if claim["scope"] != "bounded_engineering":
            errors.append("qualification claim scope is invalid")
        if claim["adjudicated_scientific_accuracy"] is not False:
            errors.append("qualification claim must disclaim adjudicated scientific accuracy")


def _validate_qualification_host_checks(
    checks: object, campaign: object, errors: list[str]
) -> None:
    if not isinstance(checks, list):
        errors.append("installed-host checks are required")
        return
    platforms = campaign.get("platforms") if isinstance(campaign, dict) else None
    if not isinstance(platforms, list):
        errors.append("installed-host checks cannot be joined to campaign platforms")
        return
    platform_by_id = {
        platform["id"]: platform
        for platform in platforms
        if isinstance(platform, dict) and isinstance(platform.get("id"), str)
    }
    expected = {(platform_id, kind) for platform_id in platform_by_id for kind in HOST_CHECK_KINDS}
    observed: set[tuple[str, str]] = set()
    for index, check in enumerate(checks):
        location = f"host_checks[{index}]"
        if not _closed(check, _QUALIFICATION_HOST_CHECK_FIELDS, location, errors):
            continue
        if any(
            not _valid_id(check[key]) for key in ("platform_id", "host", "model_family", "kind")
        ):
            errors.append(f"{location} identity or kind is invalid")
            continue
        if not isinstance(check["result"], str):
            errors.append(f"{location}.result is invalid")
            continue
        key = (check["platform_id"], check["kind"])
        if key in observed:
            errors.append(f"{location} is duplicated")
        observed.add(key)
        platform = platform_by_id.get(check["platform_id"])
        if (
            platform is None
            or check["host"] != platform.get("host")
            or check["model_family"] != platform.get("model_family")
        ):
            errors.append(f"{location} does not match its frozen campaign platform")
        if check["kind"] not in HOST_CHECK_KINDS:
            errors.append(f"{location}.kind is invalid")
        if check["result"] not in _QUALIFICATION_RESULTS:
            errors.append(f"{location}.result is invalid")
        artifact_identity = check["artifact_identity"]
        if check["result"] == "missing":
            if artifact_identity is not None:
                errors.append(f"{location} missing result cannot claim an artifact identity")
        elif not isinstance(artifact_identity, str) or not _HASH.fullmatch(artifact_identity):
            errors.append(f"{location} must identify its observed artifact")
    if observed != expected:
        errors.append("installed-host matrix must cover each required behavior on every platform")


def _rate_not_worse(successor: object, baseline: object) -> bool:
    if not isinstance(successor, dict) or not isinstance(baseline, dict):
        return False
    successor_numerator = successor.get("numerator")
    successor_denominator = successor.get("denominator")
    baseline_numerator = baseline.get("numerator")
    baseline_denominator = baseline.get("denominator")
    if (
        type(successor_numerator) is not int
        or type(successor_denominator) is not int
        or successor_denominator <= 0
        or type(baseline_numerator) is not int
        or type(baseline_denominator) is not int
        or baseline_denominator <= 0
    ):
        return False
    return successor_numerator * baseline_denominator >= baseline_numerator * successor_denominator


def _diagnostics_support_promotion(value: object, metrics: object, campaign: object) -> bool:
    if (
        not isinstance(value, dict)
        or not isinstance(metrics, dict)
        or not isinstance(campaign, dict)
    ):
        return False
    if any(
        not isinstance(metrics.get(name), dict)
        or type(metrics[name].get("denominator")) is not int
        or metrics[name]["denominator"] == 0
        for name in _QUALIFICATION_METRICS
    ):
        return False
    arms = value.get("arms")
    conditions = campaign.get("conditions")
    if not isinstance(arms, dict) or len(arms) != 2 or not isinstance(conditions, dict):
        return False
    for arm in arms.values():
        if not isinstance(arm, dict):
            return False
        support = arm.get("class_support")
        high = arm.get("high_support")
        interval = arm.get("uncertainty")
        if (
            not isinstance(support, dict)
            or set(support) != set(_LABELS)
            or any(type(support[label]) is not int or support[label] == 0 for label in _LABELS)
            or not isinstance(high, dict)
            or not isinstance(high.get("sensitivity"), dict)
            or not isinstance(arm.get("non_low"), dict)
            or not arm["non_low"].get("denominator")
            or not isinstance(interval, dict)
            or type(interval.get("clusters")) is not int
            or interval["clusters"] < 2
            or interval.get("lower") is None
            or interval.get("upper") is None
            or any(
                not isinstance(arm.get(metric), dict)
                or type(arm[metric].get("denominator")) is not int
                or arm[metric]["denominator"] == 0
                for metric in _DIAGNOSTIC_RATE_FIELDS
            )
        ):
            return False
    baseline = arms.get(conditions.get("baseline"))
    successor = arms.get(conditions.get("successor"))
    if not isinstance(baseline, dict) or not isinstance(successor, dict):
        return False
    # A passing successor must not regress on any required per-arm quality
    # rate, including High-class sensitivity. Use integer cross-products so
    # the decision does not depend on rounded display rates.
    if any(
        not _rate_not_worse(successor.get(metric), baseline.get(metric))
        for metric in (*_DIAGNOSTIC_RATE_FIELDS, "completion")
    ) or not _rate_not_worse(
        successor["high_support"].get("sensitivity"),
        baseline["high_support"].get("sensitivity"),
    ):
        return False
    aggregation = value.get("aggregation")
    if (
        not isinstance(aggregation, dict)
        or not isinstance(aggregation.get("agreement"), dict)
        or not isinstance(aggregation.get("confusion"), dict)
        or not isinstance(aggregation.get("uncertainty"), dict)
        or type(aggregation["uncertainty"].get("clusters")) is not int
        or aggregation["uncertainty"]["clusters"] < 2
        or aggregation["uncertainty"].get("lower") is None
        or aggregation["uncertainty"].get("upper") is None
    ):
        return False
    return all(sum(aggregation["confusion"][label].values()) > 0 for label in _LABELS)


def _validate_comparison_binding(report: dict[str, Any], errors: list[str]) -> None:
    """Validate the exact comparison receipt joined into a qualification report."""

    comparison = report.get("comparison")
    if not isinstance(comparison, dict) or set(comparison) != _QUALIFICATION_COMPARISON_FIELDS:
        errors.append("comparison has an unclosed field set")
        return
    identities = {
        key: comparison[key]
        for key in (
            "receipt_identity",
            "campaign_identity",
            "attempt_identity",
            "metric_identity",
            "report_metrics_identity",
        )
    }
    if any(
        not isinstance(value, str) or not _HASH.fullmatch(value) for value in identities.values()
    ):
        errors.append("comparison identities are invalid")

    receipt = comparison["receipt"]
    if not isinstance(receipt, dict) or set(receipt) != _QUALIFICATION_RECEIPT_FIELDS:
        errors.append("comparison.receipt has an unclosed field set")
        return
    if receipt["schema"] != QUALIFICATION_COMPARISON_RUN_SCHEMA:
        errors.append("comparison receipt schema is invalid")
        return
    receipt_hashes = {
        key: receipt[key]
        for key in (
            "config_identity",
            "plan_identity",
            "campaign_identity",
            "outcome_identity",
            "metric_identity",
            "receipt_identity",
        )
    }
    if any(
        not isinstance(value, str) or not _HASH.fullmatch(value)
        for value in receipt_hashes.values()
    ):
        errors.append("comparison receipt identities are invalid")
    else:
        receipt_without_identity = {
            key: value for key, value in receipt.items() if key != "receipt_identity"
        }
        if _digest(receipt_without_identity) != receipt["receipt_identity"]:
            errors.append("comparison receipt identity does not match its contents")
        if _digest(receipt["outcomes"]) != receipt["outcome_identity"]:
            errors.append("comparison receipt outcome identity does not match its outcomes")
        if _digest(receipt["metrics"]) != receipt["metric_identity"]:
            errors.append("comparison receipt metric identity does not match its metrics")
        if receipt["config_identity"] != _digest(receipt["configuration"]):
            errors.append("comparison receipt configuration identity does not match")
        if receipt["plan_identity"] != _digest(receipt["plan"]):
            errors.append("comparison receipt plan identity does not match")
        if receipt["campaign_identity"] != _digest(receipt["campaign"]):
            errors.append("comparison receipt campaign identity does not match")
    for field in ("receipt_identity", "campaign_identity", "metric_identity"):
        if comparison[field] != receipt[field]:
            errors.append(f"comparison {field} does not match the receipt")
    if report.get("campaign") != receipt.get("campaign"):
        errors.append("qualification campaign is detached from the comparison receipt")

    try:
        from .harness import run_comparison, validate_comparison_config

        configuration = receipt["configuration"]
        interventions = receipt["interventions"]
        validate_comparison_config(configuration, interventions)
        if receipt["campaign"] != configuration["campaign"]:
            errors.append("comparison receipt campaign is detached from configuration")
        if receipt["plan"] != configuration["plan"]:
            errors.append("comparison receipt plan is detached from configuration")
        expected = run_comparison(configuration, interventions, receipt["outcomes"])
        if _without_label_metrics(expected["metrics"]) != _without_label_metrics(
            receipt["metrics"]
        ):
            errors.append("comparison receipt metrics do not match its retained outcomes")
    except (KeyError, TypeError, ValueError):
        errors.append("comparison receipt configuration or outcomes are invalid")
        return

    campaign = receipt["campaign"]
    platforms = campaign.get("platforms") if isinstance(campaign, dict) else None
    platform_hosts = (
        {
            platform["id"]: platform["host"]
            for platform in platforms
            if isinstance(platform, dict)
            and isinstance(platform.get("id"), str)
            and isinstance(platform.get("host"), str)
        }
        if isinstance(platforms, list)
        else {}
    )
    outcomes = receipt["outcomes"]
    if not isinstance(outcomes, list) or receipt["retained_outcome_count"] != len(outcomes):
        errors.append("comparison attempt identity or retained count is invalid")
        return
    if not isinstance(report["attempts"], list):
        errors.append("comparison attempt identity or retained count is invalid")
        return
    if (
        _bound_identity(receipt["outcome_identity"], report["attempts"])
        != comparison["attempt_identity"]
    ):
        errors.append("comparison attempt identity does not match report attempts")
    expected_attempts: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            errors.append("comparison receipt outcome is invalid")
            return
        platform_id = outcome.get("platform_id")
        expected_attempts.append(
            {
                "attempt_id": outcome.get("attempt_id"),
                "host": platform_hosts.get(platform_id),
                "status": outcome.get("status"),
                "platform_id": platform_id,
                "arm_id": outcome.get("arm_id"),
                "cell_id": outcome.get("cell_id"),
                "draw": outcome.get("draw"),
            }
        )
    if report["attempts"] != expected_attempts:
        errors.append("qualification attempts are detached from comparison outcomes")

    diagnostics = report.get("diagnostics")
    if report.get("schema") == QUALIFICATION_SCHEMA:
        receipt_arms = (
            receipt["metrics"].get("arms") if isinstance(receipt["metrics"], dict) else None
        )
        conditions = campaign.get("conditions") if isinstance(campaign, dict) else None
        if not isinstance(receipt_arms, dict) or not isinstance(conditions, dict):
            errors.append("comparison receipt has no arm metrics for diagnostic joins")
        elif isinstance(diagnostics, dict) and isinstance(diagnostics.get("arms"), dict):
            arms_for_pooling: list[dict[str, Any]] = []
            for arm_id in (conditions.get("baseline"), conditions.get("successor")):
                arm_metrics = receipt_arms.get(arm_id)
                diagnostic_arm = diagnostics["arms"].get(arm_id)
                if not isinstance(arm_metrics, dict) or not isinstance(diagnostic_arm, dict):
                    errors.append(
                        f"diagnostics for arm {arm_id} are detached from comparison metrics"
                    )
                    continue
                arms_for_pooling.append(diagnostic_arm)
                for field in ("provisional_agreement", "completion", "cost"):
                    if diagnostic_arm.get(field) != arm_metrics.get(field):
                        errors.append(
                            f"diagnostics arm {arm_id} {field} is detached from comparison metrics"
                        )
                recall = arm_metrics.get("class_recall")
                if not isinstance(recall, dict):
                    errors.append(f"comparison arm {arm_id} has no class-recall metrics")
                else:
                    matrix = diagnostic_arm.get("confusion")
                    if isinstance(matrix, dict) and all(
                        isinstance(matrix.get(label), dict)
                        and set(matrix[label]) == set(_LABELS)
                        and all(type(matrix[label][predicted]) is int for predicted in _LABELS)
                        for label in _LABELS
                    ):
                        for label in _LABELS:
                            support = sum(matrix[label].values())
                            if support:
                                expected_recall = {
                                    "numerator": matrix[label][label],
                                    "denominator": support,
                                    "rate": matrix[label][label] / support,
                                }
                                if recall.get(label) != expected_recall:
                                    errors.append(
                                        "diagnostics arm "
                                        f"{arm_id} {label} recall is detached "
                                        "from comparison metrics"
                                    )
                            elif label in recall:
                                errors.append(
                                    f"diagnostics arm {arm_id} includes unsupported class {label}"
                                )
            report_metrics = report.get("metrics")
            if len(arms_for_pooling) == 2 and isinstance(report_metrics, dict):
                for metric in (
                    "provisional_agreement",
                    "result_scope",
                    "decisive_claim_validity",
                ):
                    values = [arm.get(metric) for arm in arms_for_pooling]
                    rates = [value for value in values if isinstance(value, dict)]
                    if len(rates) != 2 or any(
                        type(value.get("numerator")) is not int
                        or type(value.get("denominator")) is not int
                        or value["numerator"] < 0
                        or value["denominator"] < 0
                        for value in rates
                    ):
                        continue
                    numerator = sum(value["numerator"] for value in rates)
                    denominator = sum(value["denominator"] for value in rates)
                    expected = {
                        "numerator": numerator,
                        "denominator": denominator,
                        "rate": numerator / denominator if denominator else 0.0,
                    }
                    if report_metrics.get(metric) != expected:
                        errors.append(
                            f"qualification metric {metric} does not match the pooled arm metrics"
                        )

    expected_metrics: dict[str, Any] = {
        "completion": {
            "numerator": sum(
                isinstance(row, dict) and row.get("completion") is True for row in outcomes
            ),
            "denominator": len(outcomes),
        },
        "errors": {
            "count": sum(
                isinstance(row, dict) and row.get("status") == "failed" for row in outcomes
            )
        },
        "context_bytes": {"total": sum(row["context_bytes"] for row in outcomes)},
        "calls": {"total": sum(row["tool_calls"] for row in outcomes)},
        "latency": {"total": sum(row["latency_ms"] for row in outcomes)},
        "cost": {"total": sum(row["cost"] for row in outcomes)},
    }
    completed: dict[str, Any] = expected_metrics["completion"]
    completed["rate"] = (
        completed["numerator"] / completed["denominator"] if completed["denominator"] else 0.0
    )
    metrics = report["metrics"]
    if not isinstance(metrics, dict):
        errors.append("qualification metrics are invalid")
    else:
        for name, expected_metric in expected_metrics.items():
            if metrics.get(name) != expected_metric:
                errors.append(f"qualification metric {name} is detached from comparison outcomes")
    bound_metrics = (
        {"metrics": metrics, "diagnostics": diagnostics}
        if report.get("schema") == QUALIFICATION_SCHEMA
        else metrics
    )
    if (
        _bound_identity(receipt["receipt_identity"], bound_metrics)
        != comparison["report_metrics_identity"]
    ):
        errors.append("comparison report metric identity does not match report metrics")


def validate(report: object) -> list[str]:
    """Return structural/privacy errors, without echoing private payloads."""
    if not isinstance(report, dict):
        return ["report must be an object"]
    errors = _private(report)
    schema = report.get("schema")
    fields = {"schema", "identity", "mechanical", "observations", "attempts", "promotion"}
    if schema == QUALIFICATION_SCHEMA:
        allowed_fields = (
            _QUALIFICATION_REPORT_FIELDS,
            _QUALIFICATION_REPORT_FIELDS | {"qualification"},
        )
    elif schema == HISTORICAL_QUALIFICATION_SCHEMA:
        allowed_fields = (
            _HISTORICAL_QUALIFICATION_REPORT_FIELDS,
            _HISTORICAL_QUALIFICATION_REPORT_FIELDS | {"qualification"},
        )
    else:
        if any(key in report for key in ("campaign", "metrics", "claim")):
            errors.append(f"qualification fields require schema {QUALIFICATION_SCHEMA}")
        allowed_fields = (fields, fields | {"qualification"})
    if set(report) not in allowed_fields:
        errors.append("report has an unclosed field set")
        return errors
    if not isinstance(schema, str) or schema not in {
        SCHEMA,
        HISTORICAL_QUALIFICATION_SCHEMA,
        QUALIFICATION_SCHEMA,
    }:
        errors.append("report schema is invalid")
    if isinstance(schema, str) and schema in {
        HISTORICAL_QUALIFICATION_SCHEMA,
        QUALIFICATION_SCHEMA,
    }:
        _validate_qualification_extension(
            report.get("campaign"),
            report.get("metrics"),
            report.get("claim"),
            report.get("diagnostics"),
            errors,
            integrated=schema == QUALIFICATION_SCHEMA,
        )
    if schema == QUALIFICATION_SCHEMA:
        _validate_qualification_host_checks(
            report.get("host_checks"), report.get("campaign"), errors
        )
    frozen = report["identity"]
    identity_fields = {"build", "pack", "skill", "source", "config"}
    extended_identity_fields = identity_fields | {
        "executable",
        "tools",
        "schemas",
        "protocol",
        "runtime",
    }
    if not isinstance(frozen, dict) or set(frozen) not in (
        identity_fields,
        extended_identity_fields,
    ):
        errors.append("identity has an unclosed field set")
    elif isinstance(frozen, dict):
        if any(
            not isinstance(frozen[key], str) or not _HASH.fullmatch(frozen[key]) for key in frozen
        ):
            errors.append("frozen identities are invalid")
    qualification = report.get("qualification")
    if qualification is not None:
        qualification_fields = extended_identity_fields
        if not isinstance(frozen, dict) or set(frozen) != extended_identity_fields:
            errors.append("qualification requires the extended frozen identity set")
        if _closed(qualification, qualification_fields, "qualification", errors):
            if any(
                not isinstance(qualification[key], str) or not _HASH.fullmatch(qualification[key])
                for key in qualification
            ):
                errors.append("qualification identities are invalid")
            elif isinstance(frozen, dict) and set(frozen) == extended_identity_fields:
                if any(qualification[key] != frozen[key] for key in qualification_fields):
                    errors.append("qualification identities do not match frozen identities")

    mechanical = report["mechanical"]
    mechanical_ids: set[str] = set()
    if not isinstance(mechanical, list) or not mechanical:
        errors.append("mechanical checks must be a non-empty list")
    else:
        for index, check in enumerate(mechanical):
            location = f"mechanical[{index}]"
            fields_for_check = (
                _QUALIFICATION_MECHANICAL_FIELDS
                if schema == QUALIFICATION_SCHEMA
                else {"check_id", "kind", "status", "observed"}
            )
            if not _closed(check, fields_for_check, location, errors):
                continue
            check_id = check["check_id"]
            if not _valid_id(check_id) or (
                isinstance(check_id, str) and check_id in mechanical_ids
            ):
                errors.append(f"{location}.check_id is invalid or duplicated")
            if isinstance(check_id, str) and _valid_id(check_id):
                mechanical_ids.add(check_id)
            if schema == QUALIFICATION_SCHEMA:
                if (
                    not isinstance(check["kind"], str)
                    or check["kind"] not in _REQUIRED_MECHANICAL_KINDS
                    or check_id != check["kind"]
                ):
                    errors.append(f"{location} kind or check id is invalid")
                if (
                    not isinstance(check["result"], str)
                    or check["result"] not in _QUALIFICATION_RESULTS
                ):
                    errors.append(f"{location}.result is invalid")
                artifact_identity = check["artifact_identity"]
                if check["result"] == "missing":
                    if artifact_identity is not None:
                        errors.append(
                            f"{location} missing result cannot claim an artifact identity"
                        )
                elif not isinstance(artifact_identity, str) or not _HASH.fullmatch(
                    artifact_identity
                ):
                    errors.append(f"{location} must identify its observed artifact")
            else:
                if (
                    not isinstance(check["kind"], str)
                    or check["kind"] not in MECHANICAL_KINDS
                    or not _valid_status(check["status"])
                ):
                    errors.append(f"{location} kind or status is invalid")
                if not isinstance(check["observed"], bool):
                    errors.append(f"{location}.observed is invalid")

        if schema == QUALIFICATION_SCHEMA:
            observed_kinds = {
                check.get("kind")
                for check in mechanical
                if isinstance(check, dict) and isinstance(check.get("kind"), str)
            }
            if observed_kinds != _REQUIRED_MECHANICAL_KINDS or len(mechanical) != len(
                _REQUIRED_MECHANICAL_KINDS
            ):
                errors.append(
                    "qualification must record every required mechanical gate exactly once"
                )

    observations = report["observations"]
    observation_ids: set[str] = set()
    observation_rows: list[dict[str, Any]] = []
    if not isinstance(observations, list) or not observations:
        errors.append("host observations must be a non-empty list")
    else:
        for index, observation in enumerate(observations):
            location = f"observations[{index}]"
            observation_fields = {
                "observation_id",
                "attempt_id",
                "host",
                "kind",
                "status",
                "observable",
            }
            extended_observation_fields = observation_fields | {
                "delivery",
                "payload_digest",
                "error_code",
            }
            if not isinstance(observation, dict) or set(observation) not in (
                observation_fields,
                extended_observation_fields,
            ):
                errors.append(f"{location} has an unclosed field set")
                continue
            observation_rows.append(observation)
            observation_id = observation["observation_id"]
            if not _valid_id(observation_id) or (
                isinstance(observation_id, str) and observation_id in observation_ids
            ):
                errors.append(f"{location}.observation_id is invalid or duplicated")
            if isinstance(observation_id, str) and _valid_id(observation_id):
                observation_ids.add(observation_id)
            if not _valid_id(observation["attempt_id"]) or not _valid_id(observation["host"]):
                errors.append(f"{location} identity is invalid")
            if (
                not isinstance(observation["kind"], str)
                or observation["kind"] not in OBSERVATION_KINDS
                or not _valid_status(observation["status"])
            ):
                errors.append(f"{location} kind or status is invalid")
            if (
                observation["observable"] is not True
                and observation["observable"] is not False
                and observation["observable"] is not None
            ):
                errors.append(f"{location}.observable is invalid")
            if "delivery" in observation and observation["delivery"] not in _DELIVERIES:
                errors.append(f"{location}.delivery is invalid")
            if "payload_digest" in observation and (
                observation["payload_digest"] is not None
                and (
                    not isinstance(observation["payload_digest"], str)
                    or not _HASH.fullmatch(observation["payload_digest"])
                )
            ):
                errors.append(f"{location}.payload_digest is invalid")
            if "error_code" in observation and (
                observation["error_code"] is not None
                and (
                    not isinstance(observation["error_code"], str)
                    or not _valid_id(observation["error_code"])
                )
            ):
                errors.append(f"{location}.error_code is invalid")
            delivery = observation.get("delivery")
            if delivery == "success" and (
                observation.get("observable") is not True
                or not isinstance(observation.get("payload_digest"), str)
                or observation.get("error_code") is not None
            ):
                errors.append(f"{location}.successful delivery is incomplete")
            if delivery == "repairable_error" and (
                observation.get("observable") is not True
                or not isinstance(observation.get("payload_digest"), str)
                or not isinstance(observation.get("error_code"), str)
            ):
                errors.append(f"{location}.repairable delivery is incomplete")
            if delivery == "unobservable" and observation.get("observable") is True:
                errors.append(f"{location}.unobservable delivery is contradictory")

    attempts = report["attempts"]
    attempt_ids: set[str] = set()
    attempt_hosts: dict[str, str] = {}
    attempt_statuses: dict[str, str] = {}
    if not isinstance(attempts, list) or not attempts:
        errors.append("attempts must be a non-empty list")
    else:
        for index, attempt in enumerate(attempts):
            location = f"attempts[{index}]"
            attempt_fields = {"attempt_id", "host", "status"}
            if isinstance(schema, str) and schema in {
                HISTORICAL_QUALIFICATION_SCHEMA,
                QUALIFICATION_SCHEMA,
            }:
                attempt_fields = _QUALIFICATION_REPORT_ATTEMPT_FIELDS
            if not _closed(attempt, attempt_fields, location, errors):
                continue
            attempt_id = attempt["attempt_id"]
            if not _valid_id(attempt_id) or (
                isinstance(attempt_id, str) and attempt_id in attempt_ids
            ):
                errors.append(f"{location}.attempt_id is invalid or duplicated")
            if isinstance(attempt_id, str) and _valid_id(attempt_id):
                attempt_ids.add(attempt_id)
                if _valid_id(attempt["host"]):
                    attempt_hosts[attempt_id] = attempt["host"]
                if isinstance(attempt.get("status"), str):
                    attempt_statuses[attempt_id] = attempt["status"]
            valid_attempt_status = _valid_status(attempt["status"]) or (
                isinstance(schema, str)
                and schema in {HISTORICAL_QUALIFICATION_SCHEMA, QUALIFICATION_SCHEMA}
                and isinstance(attempt["status"], str)
                and attempt["status"] in _QUALIFICATION_ATTEMPT_STATUSES
            )
            if not _valid_id(attempt["host"]) or not valid_attempt_status:
                errors.append(f"{location} host or status is invalid")
            if (
                isinstance(schema, str)
                and schema in {HISTORICAL_QUALIFICATION_SCHEMA, QUALIFICATION_SCHEMA}
                and (
                    not _valid_id(attempt["platform_id"])
                    or not _valid_id(attempt["arm_id"])
                    or not _valid_id(attempt["cell_id"])
                    or type(attempt["draw"]) is not int
                    or attempt["draw"] < 1
                )
            ):
                errors.append(f"{location} comparison linkage is invalid")

    if observation_rows and attempt_ids:
        observation_attempt_ids = {
            row["attempt_id"]
            for row in observation_rows
            if isinstance(row["attempt_id"], str) and _valid_id(row["attempt_id"])
        }
        if observation_attempt_ids - attempt_ids:
            errors.append("host observation references an undeclared attempt")
        for index, observation in enumerate(observation_rows):
            attempt_host = attempt_hosts.get(str(observation["attempt_id"]))
            if attempt_host is not None and observation["host"] != attempt_host:
                errors.append(f"observations[{index}] host does not match its attempt")

    if attempt_hosts:
        rows_by_attempt = {
            (attempt_id, host): [
                row
                for row in observation_rows
                if row.get("attempt_id") == attempt_id and row.get("host") == host
            ]
            for attempt_id, host in attempt_hosts.items()
        }
        extended_delivery = any("delivery" in row for row in observation_rows)
        for (attempt_id, host), attempt_rows in sorted(rows_by_attempt.items()):
            if attempt_statuses.get(attempt_id) == "failure":
                continue
            observed_kinds = {
                row["kind"]
                for row in attempt_rows
                if isinstance(row.get("kind"), str) and row["kind"] in OBSERVATION_KINDS
            }
            missing = OBSERVATION_KINDS - observed_kinds
            if missing:
                errors.append(
                    f"required host observations are missing for {host} ({attempt_id}): "
                    + ", ".join(sorted(missing))
                )
            if extended_delivery:
                for kind in sorted(OBSERVATION_KINDS):
                    deliveries = {
                        row.get("delivery") for row in attempt_rows if row.get("kind") == kind
                    }
                    if "success" not in deliveries:
                        errors.append(
                            "successful host observation is missing for "
                            f"{host} ({attempt_id}): {kind}"
                        )
                    if "repairable_error" not in deliveries:
                        errors.append(
                            "repairable-error host observation is missing for "
                            f"{host} ({attempt_id}): {kind}"
                        )
    if isinstance(schema, str) and schema in {
        HISTORICAL_QUALIFICATION_SCHEMA,
        QUALIFICATION_SCHEMA,
    }:
        _validate_comparison_binding(report, errors)
    expected_promotion = "promote"
    if errors:
        expected_promotion = "hold"
    elif schema == QUALIFICATION_SCHEMA:
        if (
            any(check["result"] != "passed" for check in mechanical)
            or any(row["result"] != "passed" for row in report["host_checks"])
            or any(
                row["observable"] is not True
                or row["status"] in {"failure", "regression", "concern", "scope_correction"}
                for row in observation_rows
            )
            or any(
                attempt["status"] in {"failure", "regression", "concern"} for attempt in attempts
            )
            or not _diagnostics_support_promotion(
                report.get("diagnostics"), report.get("metrics"), report.get("campaign")
            )
        ):
            expected_promotion = "hold"
    elif (
        any(
            not check["observed"] or check["status"] in {"failure", "regression", "concern"}
            for check in mechanical
        )
        or any(
            row["observable"] is not True
            or row["status"] in {"failure", "regression", "concern", "scope_correction"}
            for row in observation_rows
        )
        or any(attempt["status"] in {"failure", "regression", "concern"} for attempt in attempts)
    ):
        expected_promotion = "hold"
    if (
        isinstance(schema, str)
        and schema in {HISTORICAL_QUALIFICATION_SCHEMA, QUALIFICATION_SCHEMA}
        and isinstance(report.get("metrics"), dict)
        and isinstance(report["metrics"].get("errors"), dict)
        and isinstance(report["metrics"]["errors"].get("count"), int)
        and report["metrics"]["errors"]["count"] > 0
    ):
        expected_promotion = "hold"
    promotion = report["promotion"]
    if not isinstance(promotion, str) or promotion not in PROMOTIONS:
        errors.append("promotion is invalid")
    elif promotion != expected_promotion:
        errors.append("promotion does not match recorded evidence")
    if (
        isinstance(schema, str)
        and schema in {HISTORICAL_QUALIFICATION_SCHEMA, QUALIFICATION_SCHEMA}
        and isinstance(report.get("claim"), dict)
    ):
        claim = report["claim"]
        if claim.get("decision") != expected_promotion:
            errors.append("qualification claim decision does not match recorded evidence")
    return errors


def promotion_decision(report: object) -> str:
    """Return the conservative decision; malformed reports are held."""
    if not isinstance(report, dict) or validate(report):
        return "hold"
    if report.get("schema") == HISTORICAL_QUALIFICATION_SCHEMA:
        return "hold"
    return report["promotion"]
