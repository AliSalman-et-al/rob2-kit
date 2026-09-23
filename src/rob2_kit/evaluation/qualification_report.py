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
import re
from copy import deepcopy
from typing import Any

SCHEMA = "rob2-kit.integrated-qualification.v1"
QUALIFICATION_SCHEMA = "rob2-kit.integrated-qualification.v2"
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
MECHANICAL_KINDS = frozenset({"build", "pack", "skill", "source", "config", "integrity"})
OBSERVATION_KINDS = frozenset({"text", "image", "guidance", "schema", "continuation"})
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
    "premise_support",
    "counterevidence",
    "unsupported_concern",
    "unsupported_reassurance",
    "provisional_agreement",
    "completion",
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
    "promotion",
    "claim",
    "comparison",
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
    if type(total) not in (int, float) or isinstance(total, bool) or total < 0:
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
    """Bind a v2 report to one complete qualification comparison receipt.

    The returned copy keeps the full privacy-safe receipt so an independent
    validator can replay configuration, outcome, and metric joins without
    trusting a detached campaign summary.
    """

    if report.get("schema") != QUALIFICATION_SCHEMA:
        raise ValueError("comparison binding requires the qualification report v2 schema")
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
            receipt.get("receipt_identity"), bound.get("metrics")
        ),
    }
    return bound


def _validate_qualification_extension(
    campaign: object, metrics: object, claim: object, errors: list[str]
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
            or set(controls) != {"D2", "D3", "D4", "D5"}
        ):
            errors.append("campaign controls must cover D2, D3, D4, and D5")

    if not isinstance(metrics, dict) or set(metrics) != set(_QUALIFICATION_METRICS) | set(
        _QUALIFICATION_TOTALS
    ) | {"errors"}:
        errors.append("qualification metrics are incomplete or unclosed")
    else:
        for metric in _QUALIFICATION_METRICS:
            _metric_rate(metrics[metric], f"metrics.{metric}", errors)
        _metric_count(metrics["errors"], "metrics.errors", errors)
        for metric in _QUALIFICATION_TOTALS:
            _metric_total(metrics[metric], f"metrics.{metric}", errors)

    if not isinstance(claim, dict) or set(claim) != {
        "decision",
        "scope",
        "adjudicated_scientific_accuracy",
    }:
        errors.append("qualification claim has an unclosed field set")
    else:
        if claim["decision"] not in PROMOTIONS:
            errors.append("qualification claim decision is invalid")
        if claim["scope"] != "bounded_engineering":
            errors.append("qualification claim scope is invalid")
        if claim["adjudicated_scientific_accuracy"] is not False:
            errors.append("qualification claim must disclaim adjudicated scientific accuracy")


def _validate_comparison_binding(report: dict[str, Any], errors: list[str]) -> None:
    """Validate the exact comparison receipt joined into a v2 report."""

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
    if (
        _bound_identity(receipt["receipt_identity"], metrics)
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
    else:
        if any(key in report for key in ("campaign", "metrics", "claim")):
            errors.append(f"qualification fields require schema {QUALIFICATION_SCHEMA}")
        allowed_fields = (fields, fields | {"qualification"})
    if set(report) not in allowed_fields:
        errors.append("report has an unclosed field set")
        return errors
    if not isinstance(schema, str) or schema not in {SCHEMA, QUALIFICATION_SCHEMA}:
        errors.append("report schema is invalid")
    if schema == QUALIFICATION_SCHEMA:
        _validate_qualification_extension(
            report.get("campaign"), report.get("metrics"), report.get("claim"), errors
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
            if not _closed(check, {"check_id", "kind", "status", "observed"}, location, errors):
                continue
            check_id = check["check_id"]
            if not _valid_id(check_id) or (
                isinstance(check_id, str) and check_id in mechanical_ids
            ):
                errors.append(f"{location}.check_id is invalid or duplicated")
            if isinstance(check_id, str) and _valid_id(check_id):
                mechanical_ids.add(check_id)
            if (
                not isinstance(check["kind"], str)
                or check["kind"] not in MECHANICAL_KINDS
                or not _valid_status(check["status"])
            ):
                errors.append(f"{location} kind or status is invalid")
            if not isinstance(check["observed"], bool):
                errors.append(f"{location}.observed is invalid")

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
            if schema == QUALIFICATION_SCHEMA:
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
                schema == QUALIFICATION_SCHEMA
                and isinstance(attempt["status"], str)
                and attempt["status"] in _QUALIFICATION_ATTEMPT_STATUSES
            )
            if not _valid_id(attempt["host"]) or not valid_attempt_status:
                errors.append(f"{location} host or status is invalid")
            if schema == QUALIFICATION_SCHEMA and (
                not _valid_id(attempt["platform_id"])
                or not _valid_id(attempt["arm_id"])
                or not _valid_id(attempt["cell_id"])
                or type(attempt["draw"]) is not int
                or attempt["draw"] < 1
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
    if schema == QUALIFICATION_SCHEMA:
        _validate_comparison_binding(report, errors)
    expected_promotion = "promote"
    if errors:
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
        schema == QUALIFICATION_SCHEMA
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
    if schema == QUALIFICATION_SCHEMA and isinstance(report.get("claim"), dict):
        claim = report["claim"]
        if claim.get("decision") != expected_promotion:
            errors.append("qualification claim decision does not match recorded evidence")
    return errors


def promotion_decision(report: object) -> str:
    """Return the conservative decision; malformed reports are held."""
    return report["promotion"] if isinstance(report, dict) and not validate(report) else "hold"
