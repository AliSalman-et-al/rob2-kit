from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

_script = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "analyze_rsi_runs.py"))
analyze = _script["analyze"]
SCHEMA = _script["SCHEMA"]
SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_rsi_runs.py"


def _case(
    case_id: str,
    trial_id: str,
    *,
    expected: dict[str, str] | None = None,
    observed: dict[str, str] | None = None,
    scope: str = "eligible",
    completion: str = "finalized",
    cost_usd: float | None = 0.5,
    failure_causes: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "trial_id": trial_id,
        "outcome": "outcome-a",
        "scope": scope,
        "completion": completion,
        "expected": expected
        if expected is not None
        else {
            "D1": "low",
            "D2": "some_concerns",
            "D3": "high",
            "D4": "low",
            "D5": "some_concerns",
        },
        "observed": observed
        if observed is not None
        else {
            "D1": "low",
            "D2": "some_concerns",
            "D3": "high",
            "D4": "low",
            "D5": "some_concerns",
        },
        "cost_usd": cost_usd,
        "failure_causes": failure_causes or {},
    }


def _input(*cases: dict[str, object]) -> dict[str, object]:
    return {"schema": SCHEMA, "cases": list(cases)}


def test_reports_exact_binary_direction_completion_and_high_sensitivity_limit() -> None:
    first = _case(
        "case-a",
        "trial-a",
        observed={
            "D1": "high",
            "D2": "high",
            "D4": "some_concerns",
            "D5": "some_concerns",
        },
        completion="incomplete",
        failure_causes={"D3": "workflow_incomplete"},
    )
    second = _case("case-b", "trial-b")

    result = analyze(_input(first, second), bootstrap_replicates=200)
    d1 = result["per_domain"]["D1"]
    assert d1["expected_outputs"] == 2
    assert d1["observed_outputs"] == 2
    assert d1["exact_agreement"]["matches"] == 1
    assert d1["exact_agreement"]["scored_rate"] == 0.5
    assert d1["exact_agreement"]["all_expected_rate"] == 0.5
    assert d1["high_class"]["predicted_high"] == 1
    assert d1["high_class"]["sensitivity"] is None
    assert d1["high_class"]["sensitivity_status"] == "unestimable_no_reference_high_cases"
    assert d1["confusion_matrix"]["actual_rows_predicted_columns"] == [
        [1, 0, 1],
        [0, 0, 0],
        [0, 0, 0],
    ]
    assert d1["direction_errors"] == {
        "overcalls": 1,
        "overcall_steps": 2,
        "undercalls": 0,
        "undercall_steps": 0,
    }
    d3 = result["per_domain"]["D3"]
    assert d3["expected_outputs"] == 2
    assert d3["observed_outputs"] == 1
    assert d3["exact_agreement"]["matches"] == 1
    assert d3["exact_agreement"]["all_expected_rate"] == 0.5
    assert result["completion"]["finalized_eligible_cases"] == 1
    assert result["completion"]["expected_eligible_cases"] == 2
    assert result["completion"]["eligible_case_rate"] == 0.5
    assert result["pooled_domains"]["expected_outputs"] == 10
    assert result["pooled_domains"]["scored_outputs"] == 9
    assert result["pooled_domains"]["binary_low_vs_non_low"]["confusion_matrix"][
        "actual_rows_predicted_columns"
    ] == [[2, 2], [0, 5]]
    assert result["pooled_domains"]["binary_low_vs_non_low"]["false_positives"] == 2
    assert result["pooled_domains"]["binary_low_vs_non_low"]["false_negatives"] == 0
    assert "not an estimate of scientific accuracy" in result["qualification"]
    assert (
        result["per_domain"]["D1"]["exact_agreement"]["trial_clustered_95ci_scored"]
        == analyze(_input(first, second), bootstrap_replicates=200)["per_domain"]["D1"][
            "exact_agreement"
        ]["trial_clustered_95ci_scored"]
    )


def test_scope_uncertain_cases_are_reported_separately_and_cost_unknown_stays_unknown() -> None:
    result = analyze(
        _input(
            _case("eligible", "trial-a", cost_usd=None),
            _case(
                "uncertain",
                "trial-b",
                scope="scope_uncertain",
                completion="interrupted",
                cost_usd=2.0,
            ),
            _case("ineligible", "trial-c", scope="ineligible", cost_usd=None),
        )
    )

    assert result["scope"] == {
        "all_runs": 3,
        "eligible_cases": 1,
        "scope_uncertain_cases": 1,
        "ineligible_cases": 1,
        "scope_uncertain_by_completion": {"interrupted": 1},
    }
    assert result["per_domain"]["D1"]["expected_outputs"] == 1
    assert result["cost_usd"] == {
        "known_run_count": 1,
        "unknown_run_count": 2,
        "known_total": 2.0,
        "mean_known_per_run": 2.0,
    }


def test_failure_attribution_keeps_delivery_citation_and_interpretation_distinct() -> None:
    expected = {"D1": "low", "D2": "low", "D3": "low", "D4": "low", "D5": "low"}
    observed = {domain: "high" for domain in expected}
    causes = {
        "D1": "passage_not_delivered",
        "D2": "citation_incomplete",
        "D3": "interpretation_error",
        "D4": "delivery_unknown",
    }
    result = analyze(
        _input(
            _case("case-a", "trial-a", expected=expected, observed=observed, failure_causes=causes)
        )
    )

    assert result["per_domain"]["D1"]["failure_causes"] == {"passage_not_delivered": 1}
    assert result["per_domain"]["D2"]["failure_causes"] == {"citation_incomplete": 1}
    assert result["per_domain"]["D3"]["failure_causes"] == {"interpretation_error": 1}
    assert result["per_domain"]["D4"]["failure_causes"] == {"delivery_unknown": 1}
    assert result["per_domain"]["D5"]["failure_causes"] == {"delivery_unknown": 1}
    assert result["pooled_domains"]["failure_causes"] == {
        "citation_incomplete": 1,
        "delivery_unknown": 2,
        "interpretation_error": 1,
        "passage_not_delivered": 1,
    }


def test_cli_reads_posthoc_input_and_writes_aggregate_receipt(tmp_path: Path) -> None:
    input_path = tmp_path / "rsi-wave.json"
    output_path = tmp_path / "analysis.json"
    input_path.write_text(
        json.dumps(_input(_case("case-a", "trial-a"))),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(input_path),
            "--output",
            str(output_path),
            "--bootstrap-replicates",
            "0",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["schema"] == "rob2-kit.rsi-run-analysis-result.v1"
    assert result["pooled_domains"]["exact_agreement"]["all_expected_rate"] == 1.0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update(expected={"D1": "high"}),
        lambda row: row.update(observed={"D1": "maybe"}),
        lambda row: row.update(cost_usd=float("nan")),
        lambda row: row.update(failure_causes={"D1": "delivered_and_understood"}),
        lambda row: row.update(completion="best_retry_only"),
    ],
)
def test_rejects_malformed_posthoc_records(mutate) -> None:
    case = _case("case-a", "trial-a")
    mutate(case)
    with pytest.raises(ValueError):
        analyze(_input(case), bootstrap_replicates=0)
