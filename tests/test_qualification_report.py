from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from rob2_kit.evaluation import run_comparison
from rob2_kit.evaluation.harness import QUALIFICATION_COMPARISON_SCHEMA
from rob2_kit.evaluation.qualification_report import (
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
                        "prediction": "low",
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
    receipt = run_comparison(config, interventions, outcomes)
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
    report = _report()
    report.update(
        {
            "schema": QUALIFICATION_SCHEMA,
            "campaign": config["campaign"],
            "metrics": metrics,
            "attempts": attempts,
            "observations": observations,
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
