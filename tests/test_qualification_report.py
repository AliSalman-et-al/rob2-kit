from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from rob2_kit.evaluation import run_comparison
from rob2_kit.evaluation.harness import QUALIFICATION_COMPARISON_SCHEMA
from rob2_kit.evaluation.qualification_report import (
    HISTORICAL_QUALIFICATION_SCHEMA,
    QUALIFICATION_SCHEMA,
    SCHEMA,
    bind_comparison,
    identity,
    promotion_decision,
    validate,
)


def _report() -> dict:
    frozen = {
        name: identity({"name": name, "revision": 1})
        for name in ("build", "pack", "skill", "source", "config")
    }
    return {
        "schema": SCHEMA,
        "identity": frozen,
        "mechanical": [
            {
                "check_id": "integrity-1",
                "kind": "integrity",
                "status": "completion",
                "observed": True,
            }
        ],
        "observations": [
            _observation("text", "text-1"),
            _observation("image", "image-1"),
            _observation("guidance", "guidance-1"),
            _observation("schema", "schema-1"),
            _observation("continuation", "continuation-1"),
        ],
        "attempts": [{"attempt_id": "attempt-1", "host": "codex", "status": "completion"}],
        "promotion": "promote",
    }


def _observation(
    kind: str, observation_id: str, *, attempt_id: str = "attempt-1", host: str = "codex"
) -> dict:
    return {
        "observation_id": observation_id,
        "attempt_id": attempt_id,
        "host": host,
        "kind": kind,
        "status": "completion",
        "observable": True,
    }


def test_complete_observable_report_promotes_deterministically() -> None:
    report = _report()
    assert validate(report) == []
    assert promotion_decision(report) == "promote"
    assert report == deepcopy(report)


def test_unobservable_host_check_is_retained_and_forces_hold() -> None:
    report = _report()
    report["observations"][1]["observable"] = None
    report["observations"][1]["status"] = "unsupported_reassurance"
    report["promotion"] = "hold"
    assert validate(report) == []
    assert promotion_decision(report) == "hold"


def test_failures_are_retained_and_private_fields_are_rejected() -> None:
    report = _report()
    report["attempts"].append(
        {"attempt_id": "failed-1", "host": "claude-code", "status": "failure"}
    )
    report["promotion"] = "hold"
    assert validate(report) == []
    private = deepcopy(report)
    private["observations"][0]["prompt"] = "must not be retained"
    assert any("private field" in error for error in validate(private))
    assert all("must not be retained" not in error for error in validate(private))


def test_closed_enums_and_false_promotion_are_rejected() -> None:
    report = _report()
    report["observations"][0]["status"] = "pass"
    assert validate(report)
    report = _report()
    report["promotion"] = "promote"
    report["observations"][0]["observable"] = False
    assert "promotion does not match recorded evidence" in "; ".join(validate(report))


def test_required_host_observation_matrix_is_closed() -> None:
    report = _report()
    report["observations"] = report["observations"][:1]
    report["promotion"] = "hold"
    assert any("required host observations are missing" in error for error in validate(report))
    assert promotion_decision(report) == "hold"


def test_required_observation_matrix_is_complete_for_each_attempt_host() -> None:
    report = _report()
    report["attempts"].append(
        {"attempt_id": "attempt-2", "host": "claude-code", "status": "completion"}
    )
    report["observations"][1]["attempt_id"] = "attempt-2"
    report["observations"][1]["host"] = "claude-code"
    report["promotion"] = "hold"

    errors = validate(report)

    assert any("for codex" in error for error in errors)
    assert any("for claude-code" in error for error in errors)
    assert promotion_decision(report) == "hold"


def test_observation_host_must_match_its_attempt() -> None:
    report = _report()
    report["observations"][0]["host"] = "claude-code"
    report["promotion"] = "hold"

    errors = validate(report)

    assert "observations[0] host does not match its attempt" in errors
    assert promotion_decision(report) == "hold"


def test_extended_host_delivery_matrix_requires_success_and_repairable_error() -> None:
    report = _report()
    report["identity"] = {
        **report["identity"],
        **{
            name: identity({"name": name, "revision": 2})
            for name in ("executable", "tools", "schemas", "protocol", "runtime")
        },
    }
    report["qualification"] = dict(report["identity"])
    observations = []
    for kind in ("text", "image", "guidance", "schema", "continuation"):
        base = _observation(kind, f"{kind}-success")
        base.update(
            {
                "delivery": "success",
                "payload_digest": identity({"kind": kind, "delivery": "success"}),
                "error_code": None,
            }
        )
        observations.append(base)
        error = _observation(kind, f"{kind}-error")
        error.update(
            {
                "status": "context",
                "delivery": "repairable_error",
                "payload_digest": identity({"kind": kind, "delivery": "error"}),
                "error_code": "retryable_host_error",
            }
        )
        observations.append(error)
    report["observations"] = observations

    assert validate(report) == []

    missing = deepcopy(report)
    missing["observations"] = [
        row
        for row in missing["observations"]
        if not (row["kind"] == "image" and row["delivery"] == "repairable_error")
    ]
    errors = validate(missing)
    assert any("repairable-error host observation is missing" in error for error in errors)
    assert promotion_decision(missing) == "hold"


def test_qualification_identities_must_match_the_frozen_report_identity() -> None:
    report = _report()
    report["identity"] = {
        **report["identity"],
        **{
            name: identity({"name": name, "revision": 2})
            for name in ("executable", "tools", "schemas", "protocol", "runtime")
        },
    }
    report["qualification"] = dict(report["identity"])
    assert validate(report) == []

    report["qualification"]["pack"] = identity({"pack": "different"})
    errors = validate(report)

    assert "qualification identities do not match frozen identities" in errors
    assert promotion_decision(report) == "hold"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda report: report["mechanical"][0].update({"check_id": []}),
        lambda report: report["mechanical"][0].update({"kind": []}),
        lambda report: report["observations"][0].update({"observation_id": []}),
        lambda report: report["observations"][0].update({"observable": []}),
        lambda report: report["attempts"][0].update({"attempt_id": []}),
        lambda report: report["attempts"][0].update({"status": []}),
    ),
)
def test_malformed_json_is_held_without_raising_type_errors(mutate) -> None:
    report = _report()
    mutate(report)
    assert validate(report)
    assert promotion_decision(report) == "hold"


def test_malformed_promotion_is_held_without_raising_type_errors() -> None:
    report = _report()
    report["promotion"] = []
    assert validate(report)
    assert promotion_decision(report) == "hold"


def test_malformed_schema_is_held_without_raising_type_errors() -> None:
    report = _report()
    report["schema"] = []
    assert validate(report)
    assert promotion_decision(report) == "hold"


def _qualification_report() -> dict:
    config = _qualification_config()
    interventions = {
        "baseline": identity({"arm": "baseline"}),
        "successor": identity({"arm": "successor"}),
    }
    labels = {
        "case-1": "low",
        "case-2": "some_concerns",
        "case-3": "high",
        "case-4": "low",
    }
    outcomes = []
    attempt = 0
    for platform_id in ("platform-a", "platform-b"):
        for case_id in ("case-1", "case-2", "case-3", "case-4"):
            for arm_id in ("baseline", "successor"):
                attempt += 1
                outcomes.append(
                    {
                        "attempt_id": f"attempt-{attempt}",
                        "arm_id": arm_id,
                        "cell_id": case_id,
                        "session_id": f"session-{attempt}",
                        "status": "assessed",
                        "prediction": labels[case_id],
                        "support": "full",
                        "completion": True,
                        "latency_ms": 10,
                        "cost": 0.1,
                        "context_bytes": 100,
                        "tool_calls": 2,
                        "platform_id": platform_id,
                        "draw": 1,
                    }
                )
    receipt = run_comparison(config, interventions, outcomes, labels=labels)
    attempts = [
        {
            "attempt_id": row["attempt_id"],
            "host": next(
                platform["host"]
                for platform in config["campaign"]["platforms"]
                if platform["id"] == row["platform_id"]
            ),
            "status": row["status"],
            "platform_id": row["platform_id"],
            "arm_id": row["arm_id"],
            "cell_id": row["cell_id"],
            "draw": row["draw"],
        }
        for row in outcomes
    ]
    observations = [
        _observation(
            kind,
            f"{kind}-{attempt['attempt_id']}",
            attempt_id=cast(str, attempt["attempt_id"]),
            host=cast(str, attempt["host"]),
        )
        for attempt in attempts
        for kind in ("text", "image", "guidance", "schema", "continuation")
    ]
    metrics = {
        metric: {"numerator": len(outcomes), "denominator": len(outcomes), "rate": 1.0}
        for metric in (
            "result_scope",
            "decisive_claim_validity",
            "premise_support",
            "counterevidence",
            "unsupported_concern",
            "unsupported_reassurance",
            "provisional_agreement",
        )
    }
    metrics.update(
        {
            "completion": {"numerator": len(outcomes), "denominator": len(outcomes), "rate": 1.0},
            "errors": {"count": 0},
            "context_bytes": {"total": 1600},
            "calls": {"total": 32},
            "latency": {"total": 160},
            "cost": {"total": 1.6},
        }
    )
    matrix = {
        "low": {"low": 4, "some_concerns": 0, "high": 0},
        "some_concerns": {"low": 0, "some_concerns": 2, "high": 0},
        "high": {"low": 0, "some_concerns": 0, "high": 2},
    }
    class_support = {"low": 4, "some_concerns": 2, "high": 2}
    interval = {
        "method": "trial_cluster_percentile_bootstrap",
        "clusters": 4,
        "lower": 0.6,
        "upper": 1.0,
    }
    diagnostics_arms = {
        arm_id: {
            "provisional_agreement": {"numerator": 8, "denominator": 8, "rate": 1.0},
            "result_scope": {"numerator": 8, "denominator": 8, "rate": 1.0},
            "decisive_claim_validity": {"numerator": 8, "denominator": 8, "rate": 1.0},
            "non_low": {"numerator": 4, "denominator": 4, "rate": 1.0},
            "confusion": deepcopy(matrix),
            "class_support": deepcopy(class_support),
            "predicted_support": deepcopy(class_support),
            "high_support": {
                "reference": 2,
                "predicted": 2,
                "true_positive": 2,
                "sensitivity": {"numerator": 2, "denominator": 2, "rate": 1.0},
            },
            "uncertainty": deepcopy(interval),
            "completion": {"numerator": 8, "denominator": 8, "rate": 1.0},
            "cost": 0.8,
        }
        for arm_id in ("baseline", "successor")
    }
    diagnostic_confusion = {
        "low": {"low": 2, "some_concerns": 0, "high": 0},
        "some_concerns": {"low": 0, "some_concerns": 1, "high": 0},
        "high": {"low": 0, "some_concerns": 0, "high": 1},
    }
    diagnostic_identity = identity({"comparison": receipt["receipt_identity"], "labels": labels})
    host_checks = [
        {
            "platform_id": platform["id"],
            "host": platform["host"],
            "model_family": platform["model_family"],
            "kind": kind,
            "result": "passed",
            "artifact_identity": identity({"platform": platform["id"], "kind": kind}),
        }
        for platform in config["campaign"]["platforms"]
        for kind in (
            "tool",
            "structured",
            "text",
            "image",
            "continuation",
            "compaction",
            "restart",
            "review",
        )
    ]
    report = _report()
    report["mechanical"] = [
        {
            "check_id": kind,
            "kind": kind,
            "result": "passed",
            "artifact_identity": identity({"check": kind}),
        }
        for kind in (
            "formatting",
            "types",
            "full_test_suite",
            "public_contract",
            "bundle_verification",
        )
    ]
    report.update(
        {
            "schema": QUALIFICATION_SCHEMA,
            "campaign": config["campaign"],
            "metrics": metrics,
            "attempts": attempts,
            "observations": observations,
            "host_checks": host_checks,
            "diagnostics": {
                "schema": "rob2-kit.qualification-diagnostics.v1",
                "source_artifact_identity": diagnostic_identity,
                "scorer": "heldout-diagnostics-v1",
                "arms": diagnostics_arms,
                "aggregation": {
                    "policy_id": "ADR-0035",
                    "policy_version": "ADR-0035-current-deterministic-cochrane-v1",
                    "reference_basis": "provisional_overall_labels",
                    "source_artifact_identity": diagnostic_identity,
                    "agreement": {"numerator": 4, "denominator": 4, "rate": 1.0},
                    "confusion": diagnostic_confusion,
                    "uncertainty": deepcopy(interval),
                },
            },
            "claim": {
                "decision": "promote",
                "scope": "bounded_engineering",
                "adjudicated_scientific_accuracy": False,
            },
        }
    )
    return bind_comparison(report, receipt)


def _qualification_config() -> dict:
    neutral = {
        "mode": "none",
        "passages": "not_supplied",
        "labels": "forbidden",
        "answers": "forbidden",
    }
    arms = [
        {
            "id": arm,
            "intervention_id": arm,
            "retrieval": "free_search",
            "spelling": "porter_only",
            "context": "baseline",
            "guidance": "baseline",
            "evidence": neutral,
        }
        for arm in ("baseline", "successor")
    ]
    return {
        "schema": QUALIFICATION_COMPARISON_SCHEMA,
        "arms": arms,
        "pairs": [
            {
                "id": f"control-{control.lower()}",
                "left": "baseline",
                "right": "successor",
                "diagnostic": True,
                "control": control,
                "case_ids": [f"case-{index}"],
            }
            for index, control in enumerate(("D2", "D3", "D4", "D5"), 1)
        ],
        "campaign": {
            "campaign_id": "qualification-1",
            "split": {
                "kind": "trial_heldout",
                "development_trials": ["trial-dev"],
                "holdout_trials": ["trial-1", "trial-2", "trial-3", "trial-4"],
            },
            "conditions": {"baseline": "baseline", "successor": "successor"},
            "attempt_policy": {"draws_per_cell": 1, "selection": "retain_all"},
            "platforms": [
                {
                    "id": "platform-a",
                    "host": "codex",
                    "model_family": "luna",
                    "model_version": "5.6",
                    "effort": "medium",
                },
                {
                    "id": "platform-b",
                    "host": "claude",
                    "model_family": "claude",
                    "model_version": "4",
                    "effort": "medium",
                },
            ],
            "controls": ["D2", "D3", "D4", "D5"],
        },
        "plan": {
            "cases": [
                {
                    "case_id": f"case-{index}",
                    "trial_id": f"trial-{index}",
                    "outcome_id": f"outcome-{index}",
                    "domain_ids": [domain],
                }
                for index, domain in enumerate(
                    (
                        "domain:deviations",
                        "domain:missing",
                        "domain:measurement",
                        "domain:selection",
                    ),
                    1,
                )
            ],
            "host": {
                "provider": "codex-cli",
                "interface": "jsonl",
                "version": "1",
                "prompt_identity": identity({"prompt": "qualification"}),
            },
            "model": {"family": "luna", "version": "medium", "effort": "medium"},
            "retry_policy": {"max_attempts": 1, "rule": "infrastructure_only"},
            "scoring": {
                "primary_metric": "provisional_agreement",
                "metrics": ["support", "completion", "latency", "cost"],
                "class_recall": True,
            },
            "budget": {
                "max_attempts": 16,
                "max_cost": 2.0,
                "max_context_bytes": 2000,
                "max_tool_calls": 40,
            },
        },
    }


def test_qualification_report_exposes_separate_metrics_and_bounded_claim() -> None:
    report = _qualification_report()

    assert validate(report) == []
    assert promotion_decision(report) == "promote"
    assert report["claim"]["adjudicated_scientific_accuracy"] is False
    assert set(report["metrics"]) == {
        "result_scope",
        "decisive_claim_validity",
        "premise_support",
        "counterevidence",
        "unsupported_concern",
        "unsupported_reassurance",
        "provisional_agreement",
        "completion",
        "errors",
        "context_bytes",
        "calls",
        "latency",
        "cost",
    }
    assert report["comparison"]["receipt_identity"].startswith("sha256:")
    assert (
        report["comparison"]["receipt_identity"]
        == report["comparison"]["receipt"]["receipt_identity"]
    )
    assert set(report["diagnostics"]["arms"]["successor"]["confusion"]) == {
        "low",
        "some_concerns",
        "high",
    }


def test_successor_quality_regression_holds_a_complete_report() -> None:
    report = _qualification_report()
    report["diagnostics"]["arms"]["successor"]["decisive_claim_validity"] = {
        "numerator": 6,
        "denominator": 8,
        "rate": 0.75,
    }
    report["metrics"]["decisive_claim_validity"] = {
        "numerator": 14,
        "denominator": 16,
        "rate": 0.875,
    }
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"
    report = bind_comparison(report, report["comparison"]["receipt"])

    assert validate(report) == []
    assert promotion_decision(report) == "hold"


def test_malformed_controls_are_held_without_raising_type_errors() -> None:
    report = _qualification_report()
    report["campaign"]["controls"] = ["D2", {}, "D4", "D5"]
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"

    errors = validate(report)

    assert any("campaign controls must cover" in error for error in errors)
    assert promotion_decision(report) == "hold"


def test_historical_v2_report_replays_but_cannot_qualify_the_integrated_gate() -> None:
    report = _qualification_report()
    report["schema"] = HISTORICAL_QUALIFICATION_SCHEMA
    report.pop("host_checks")
    report.pop("diagnostics")
    report["metrics"].pop("decisive_claim_validity")
    report["mechanical"] = [
        {
            "check_id": check["check_id"],
            "kind": "integrity",
            "status": "completion",
            "observed": True,
        }
        for check in report["mechanical"]
    ]
    report["comparison"]["report_metrics_identity"] = identity(
        {
            "receipt_identity": report["comparison"]["receipt_identity"],
            "value": report["metrics"],
        }
    )

    assert validate(report) == []
    assert promotion_decision(report) == "hold"


def test_qualification_report_holds_without_complete_gates_and_class_metrics() -> None:
    report = _qualification_report()
    report["host_checks"] = [row for row in report["host_checks"] if row["kind"] != "compaction"]
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"
    assert any("installed-host matrix" in error for error in validate(report))
    assert promotion_decision(report) == "hold"

    report = _qualification_report()
    del report["diagnostics"]["arms"]["successor"]["confusion"]
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"
    assert any("unclosed metric set" in error for error in validate(report))
    assert promotion_decision(report) == "hold"


def test_explicitly_missing_gate_evidence_is_a_valid_hold() -> None:
    report = _qualification_report()
    test_gate = next(row for row in report["mechanical"] if row["kind"] == "full_test_suite")
    test_gate.update({"result": "missing", "artifact_identity": None})
    host_gate = next(row for row in report["host_checks"] if row["kind"] == "restart")
    host_gate.update({"result": "missing", "artifact_identity": None})
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"

    assert validate(report) == []
    assert promotion_decision(report) == "hold"


def test_qualification_report_cross_checks_confusion_against_receipt_metrics() -> None:
    report = _qualification_report()
    report["diagnostics"]["arms"]["successor"]["confusion"]["low"]["low"] = 1
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"

    errors = validate(report)

    assert any("does not match its confusion matrix" in error for error in errors)
    assert any("detached from comparison metrics" in error for error in errors)
    assert promotion_decision(report) == "hold"


@pytest.mark.parametrize(
    "mutate, expected",
    (
        (
            lambda report: report["comparison"]["receipt"]["campaign"]["platforms"][0].update(
                {"host": "detached-host"}
            ),
            "comparison receipt identity does not match its contents",
        ),
        (
            lambda report: report["attempts"][0].update({"platform_id": "platform-b"}),
            "qualification attempts are detached from comparison outcomes",
        ),
        (
            lambda report: report["metrics"]["result_scope"].update({"numerator": 0, "rate": 0.0}),
            "comparison report metric identity does not match report metrics",
        ),
    ),
)
def test_qualification_report_rejects_detached_receipt_claims(mutate, expected) -> None:
    report = _qualification_report()
    mutate(report)

    assert expected in validate(report)
    assert promotion_decision(report) == "hold"


def test_qualification_report_holds_on_operational_error_or_accuracy_claim() -> None:
    report = _qualification_report()
    report["metrics"]["errors"] = {"count": 1}
    report["promotion"] = "hold"
    report["claim"]["decision"] = "hold"
    assert any("detached from comparison outcomes" in error for error in validate(report))
    assert promotion_decision(report) == "hold"

    report = _qualification_report()
    report["claim"]["adjudicated_scientific_accuracy"] = True
    assert any("disclaim adjudicated scientific accuracy" in error for error in validate(report))
    assert promotion_decision(report) == "hold"


def test_legacy_report_rejects_v2_fields_with_version_hint() -> None:
    report = _report()
    report["metrics"] = {}
    errors = validate(report)
    assert any(QUALIFICATION_SCHEMA in error for error in errors)
    assert promotion_decision(report) == "hold"
