from __future__ import annotations

import hashlib
import json
import runpy
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_scorer = runpy.run_path(str(SCRIPTS / "score_trial_benchmark.py"))
_result_dimensions = _scorer["_result_dimensions"]
_result_mismatches = _scorer["_result_mismatches"]
score = _scorer["score"]
render_markdown = _scorer["render_markdown"]

def _write_reference(root: Path) -> None:
    catalog = root / "catalog"
    labels = catalog / "provisional-labels"
    labels.mkdir(parents=True)
    (catalog / "trials.csv").write_text(
        "trial_label,trial_slug,source_directory,nct_number,outcomes\n"
        "GETUG-AFU 15,GETUG-AFU-15,sources/GETUG-AFU-15,NCT00104715,Overall Survival\n",
        encoding="utf-8",
    )
    row = (
        "Trial,D1,D2,D3,D4,D5,Overall Risk\n"
        "GETUG-AFU 15,L,S,L,L,S,Some Concerns\n"
        "unfinished,L,S,L,L,S,Some Concerns\n"
    )
    for filename in (
        "overall-survival.csv",
        "progression-free-survival.csv",
        "adverse-events.csv",
    ):
        (labels / filename).write_text(row, encoding="utf-8")


def _write_case(root: Path, state: str = "succeeded") -> Path:
    run_dir = root / "runs" / "overall-survival" / "GETUG-AFU-15"
    run_dir.mkdir(parents=True)
    (run_dir / "execution.json").write_text(
        json.dumps({"state": state, "phases": [{"state": state}]}), encoding="utf-8"
    )
    if state == "succeeded":
        bundle = run_dir / "workspace" / ".rob2-kit" / "finalized" / "case.rob2.zip"
        bundle.parent.mkdir(parents=True)
        canonical = {
            "snapshots": {
                "getug": {
                    "domain_judgments": {
                        "domain:randomization": "low",
                        "domain:deviations": "some_concerns",
                        "domain:missing": "low",
                        "domain:measurement": "low",
                        "domain:selection": "some_concerns",
                    },
                    "overall": "some_concerns",
                }
            },
            "proposal": {
                "payload": {
                    "results": [
                        {
                            "trial_id": "GETUG-AFU-15",
                            "target": {
                                "comparison_groups": [
                                    {"id": "A", "assignment": "A"},
                                    {"id": "B", "assignment": "B"},
                                ],
                                "outcome_definition": "death from any cause",
                                "intended_analysis_population": "all randomized participants",
                                "time_point_or_window": {
                                    "kind": "fixed",
                                    "description": "36 months",
                                },
                            },
                            "reported": {
                                "endpoint": {"definition": "death from any cause"},
                                "estimate": "HR 1.01",
                                "precision": "95% CI 0.75 to 1.36",
                            },
                        }
                    ]
                }
            },
        }
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("canonical.json", json.dumps(canonical))
            archive.writestr("verification.json", json.dumps({"result": "verified"}))
    return run_dir


def _expected_result() -> dict[str, object]:
    return {
        "trial": "GETUG-AFU-15",
        "comparison": [
            {"id": "A", "assignment": "A"},
            {"id": "B", "assignment": "B"},
        ],
        "endpoint_definition": "death from any cause",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "36 months"},
        "estimate": "HR 1.01",
        "precision": "95% CI 0.75 to 1.36",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 1.01",
            "precision": "95% CI 0.75 to 1.36",
            "group_values": [],
        },
    }


def test_score_keeps_legacy_case_unscored_and_excludes_unfinished_cases(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = _write_case(tmp_path, state="succeeded")
    unfinished_dir = tmp_path / "runs" / "overall-survival" / "unfinished"
    unfinished_dir.mkdir(parents=True)
    (unfinished_dir / "execution.json").write_text(
        json.dumps({"state": "resumable", "phases": [{"state": "resumable"}]}),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-manifest.v2",
                "model": "test-model",
                "effort": "medium",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(run_dir),
                    },
                    {
                        "outcome": "Overall Survival",
                        "trial": "unfinished",
                        "run_dir": str(unfinished_dir),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    assert result["scope"] == {
        "manifest_rows": 2,
        "finalized_scored_cases": 0,
        "finalized_domain_cells": 0,
        "sensitivity_scored_cases": 0,
        "sensitivity_domain_cells": 0,
        "scope_difference_cases": 0,
        "excluded_cases": 2,
    }


def test_reported_scope_alone_supplies_comparative_estimate_and_precision() -> None:
    result = {
        "trial_id": "GETUG-AFU-15",
        "target": {
            "comparison_groups": [
                {"id": "A", "assignment": "A"},
                {"id": "B", "assignment": "B"},
            ],
            "outcome_definition": "death from any cause",
            "intended_analysis_population": "all randomized participants",
            "time_point_or_window": {"kind": "fixed", "description": "36 months"},
        },
        "reported": {
            "analysis_population": "all randomized participants",
            "effect_measure": "hazard_ratio",
            "endpoint": {"definition": "death from any cause"},
            "estimate": "HR 1.01",
            "precision": "95% CI 0.75 to 1.36",
        },
    }
    expected = {
        "trial": "GETUG-AFU-15",
        "comparison": result["target"]["comparison_groups"],
        "endpoint_definition": "death from any cause",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "36 months"},
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 1.01",
            "precision": "95% CI 0.75 to 1.36",
            "group_values": [],
        },
    }

    assert _result_mismatches(
        expected, _result_dimensions(result, "GETUG-AFU-15"), "GETUG-AFU-15"
    ) == []


def test_score_requires_exact_result_scope_before_reading_labels(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = tmp_path / "runs" / "overall-survival" / "GETUG-AFU-15"
    run_dir.mkdir(parents=True)
    (run_dir / "execution.json").write_text(
        json.dumps({"state": "succeeded", "phases": [{"state": "succeeded"}]}),
        encoding="utf-8",
    )
    canonical = {
        "snapshots": {
            "GETUG-AFU-15": {
                "domain_judgments": {
                    "domain:randomization": "low",
                    "domain:deviations": "some_concerns",
                    "domain:missing": "low",
                    "domain:measurement": "low",
                    "domain:selection": "some_concerns",
                },
                "overall": "some_concerns",
            }
        },
        "proposal": {
            "payload": {
                "results": [
                    {
                        "trial_id": "GETUG-AFU-15",
                        "target": {
                            "comparison_groups": [
                                {"id": "A", "assignment": "A"},
                                {"id": "B", "assignment": "B"},
                            ],
                            "outcome_definition": "death from any cause",
                            "intended_analysis_population": "all randomized participants",
                            "time_point_or_window": {"kind": "fixed", "description": "36 months"},
                        },
                        "reported": {
                            "effect_measure": "hazard_ratio",
                            "endpoint": {"definition": "death from any cause"},
                            "estimate": "HR 1.01",
                            "precision": "95% CI 0.75 to 1.36",
                        },
                    }
                ]
            }
        },
    }
    bundle = run_dir / "result.rob2.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", json.dumps({"result": "verified"}))
    expected = {
        "trial": "GETUG-AFU-15",
        "comparison": canonical["proposal"]["payload"]["results"][0]["target"]["comparison_groups"],
        "endpoint_definition": "death from any cause",
        "population": "wrong population",
        "window": {"kind": "fixed", "description": "36 months"},
        "effect_measure": "hazard_ratio",
        "estimate": "HR 1.01",
        "precision": "95% CI 0.75 to 1.36",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 1.01",
            "precision": "95% CI 0.75 to 1.36",
            "group_values": [],
        },
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.trial-benchmark-manifest.v3",
                "result_matching": "required",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(run_dir),
                        "expected_result": expected,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    assert result["scope"]["finalized_scored_cases"] == 0
    assert result["scope"]["excluded_cases"] == 1
    assert "population" in result["excluded"][0]["reason"]


def test_result_scope_mismatch_preserves_bounded_field_details(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = tmp_path / "runs" / "overall-survival" / "GETUG-AFU-15"
    run_dir.mkdir(parents=True)
    canonical = {
        "snapshots": {
            "GETUG-AFU-15": {
                "domain_judgments": {
                    "domain:randomization": "low",
                    "domain:deviations": "some_concerns",
                    "domain:missing": "low",
                    "domain:measurement": "low",
                    "domain:selection": "some_concerns",
                },
                "overall": "some_concerns",
            }
        },
        "proposal": {
            "payload": {
                "results": [
                    {
                        "trial_id": "GETUG-AFU-15",
                        "target": {
                            "comparison_groups": [
                                {"id": "A", "assignment": "A"},
                                {"id": "B", "assignment": "B"},
                            ],
                            "outcome_definition": "PRIVATE_SOURCE_TEXT_OBSERVED",
                            "intended_analysis_population": "all randomized participants",
                            "time_point_or_window": {"kind": "fixed", "description": "36 months"},
                        },
                        "reported": {
                            "analysis_population": "all randomized participants",
                            "effect_measure": "hazard_ratio",
                            "endpoint": {"definition": "PRIVATE_SOURCE_TEXT_OBSERVED"},
                            "estimate": "HR 1.01",
                            "precision": "95% CI 0.75 to 1.36",
                        },
                    }
                ]
            }
        },
    }
    bundle = run_dir / "result.rob2.zip"
    artifact_identity = "sha256:" + "a" * 64
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"identity": artifact_identity}))
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", json.dumps({"result": "verified"}))
    (run_dir / "execution.json").write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-execution.v1",
                "state": "succeeded",
                "artifact": {
                    "path": "result.rob2.zip",
                    "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    "identity": artifact_identity,
                    "verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    expected = {
        "trial": "GETUG-AFU-15",
        "comparison": [
            {"id": "A", "assignment": "A"},
            {"id": "B", "assignment": "B"},
        ],
        "endpoint_definition": "PRIVATE_SOURCE_TEXT_EXPECTED",
        "population": "all randomized participants",
        "reported_analysis_population": "all randomized participants",
        "window": {"kind": "fixed", "description": "36 months"},
        "effect_measure": "hazard_ratio",
        "estimate": "HR 1.01",
        "precision": "95% CI 0.75 to 1.36",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "PRIVATE_SOURCE_TEXT_EXPECTED"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 1.01",
            "precision": "95% CI 0.75 to 1.36",
            "group_values": [],
        },
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.trial-benchmark-manifest.v3",
                "result_matching": "required",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(run_dir),
                        "expected_result": expected,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    excluded = result["excluded"][0]
    details = excluded["result_scope_details"]
    assert details["code"] == "result_scope_mismatch"
    definition = next(item for item in details["fields"] if item["field"] == "endpoint_definition")
    assert set(definition["expected"]) == {"present", "kind", "length", "sha256"}
    assert set(definition["observed"]) == {"present", "kind", "length", "sha256"}
    assert "PRIVATE_SOURCE_TEXT" not in json.dumps(excluded)


def test_result_scope_rejects_changed_group_bound_values() -> None:
    result = {
        "trial_id": "trial-a",
        "target": {
            "comparison_groups": [{"id": "A"}, {"id": "B"}],
            "outcome_definition": "mortality",
            "intended_analysis_population": "all randomized participants",
            "time_point_or_window": {"kind": "fixed", "description": "12 months"},
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "all randomized participants",
            "endpoint": {"name": "Mortality", "definition": "death from any cause"},
            "group_values": [
                {"group_id": "A", "statistic": "risk", "value": "10", "unit": "%"},
                {"group_id": "B", "statistic": "risk", "value": "20", "unit": "%"},
            ],
        },
    }
    expected = {
        "trial": "trial-a",
        "comparison": result["target"]["comparison_groups"],
        "endpoint_definition": "mortality",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "12 months"},
        "estimate": None,
        "precision": None,
        "reported_scope": {
            **result["reported"],
            "group_values": [
                {"group_id": "A", "statistic": "risk", "value": "10", "unit": "%"},
                {"group_id": "B", "statistic": "risk", "value": "99", "unit": "%"},
            ],
        },
    }

    mismatches = _result_mismatches(expected, _result_dimensions(result, "trial-a"), "trial-a")

    assert [item["field"] for item in mismatches] == ["reported_scope"]


def test_result_scope_accepts_trial_name_case_difference_only() -> None:
    result = {
        "trial_id": "peace-1",
        "target": {
            "comparison_groups": [{"id": "A"}, {"id": "B"}],
            "outcome_definition": "death from any cause",
            "intended_analysis_population": "all randomized participants",
            "time_point_or_window": "follow-up",
        },
        "reported": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"name": "overall survival"},
            "effect_measure": "HR",
            "estimate": "0.82",
            "precision": "95% CI 0.69 to 0.98",
            "group_values": [],
        },
    }
    observed = _result_dimensions(result, "PEACE-1")
    expected = {**observed, "trial": "PEACE-1"}

    assert _result_mismatches(expected, observed, "PEACE-1") == []


def test_score_keeps_scope_difference_out_of_primary_and_adds_it_to_sensitivity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected_result()
    _write_reference(tmp_path / "reference")
    labels = {
        "D1": "low",
        "D2": "some_concerns",
        "D3": "low",
        "D4": "low",
        "D5": "some_concerns",
        "overall": "some_concerns",
    }
    monkeypatch.setitem(
        score.__globals__,
        "_load_reference",
        lambda _root: {("Overall Survival", "GETUG-AFU-15"): labels},
    )
    adjudication = {
        "outcome": "Overall Survival",
        "trial": "GETUG-AFU-15",
        "expected_result_sha256": "0" * 64,
        "review_identity": "review-1",
        "result_identity": "result-1",
        "observed_relation": "broader",
        "decision": "accepted_with_scope_difference",
        "rationale": "The broader endpoint is retained for sensitivity analysis.",
        "source_citation": "Main article, p. 1.",
    }
    bundles = [
        {"observed": labels, "bundle": "exact.rob2.zip", "scope_adjudication": None},
        {
            "observed": labels,
            "bundle": "broader.rob2.zip",
            "scope_adjudication": adjudication,
        },
    ]

    def fake_bundle(*_args, **_kwargs):
        return bundles.pop(0), None

    monkeypatch.setitem(score.__globals__, "_bundle_snapshot", fake_bundle)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-manifest.v2",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(tmp_path / "exact"),
                        "primary_status": "primary",
                        "expected_result": expected,
                    },
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(tmp_path / "broader"),
                        "primary_status": "primary",
                        "expected_result": expected,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, tmp_path / "reference")

    assert result["scope"]["finalized_scored_cases"] == 1
    assert result["scope"]["sensitivity_scored_cases"] == 2
    assert result["scope"]["scope_difference_cases"] == 1
    assert result["pooled"]["case_count"] == 1
    assert result["sensitivity"]["pooled"]["case_count"] == 2
    assert result["sensitivity"]["pooled"]["domain_cells"] == 10
    assert result["sensitivity"]["by_outcome"]["Overall Survival"]["case_count"] == 2
    assert result["sensitivity"]["by_domain"]["D1"]["exact"]["total"] == 2
    assert (
        result["sensitivity"]["by_outcome_domain"]["Overall Survival"]["D1"]["exact"]["total"]
        == 2
    )
    assert result["sensitivity"]["by_primary_status"]["primary"]["case_count"] == 2
    assert (
        result["scope_difference_cases"][0]["scope_adjudication"]["decision"]
        == "accepted_with_scope_difference"
    )
    markdown = render_markdown(result)
    assert "Scope-difference sensitivity" in markdown
    assert "accepted_with_scope_difference" in markdown


def test_legacy_manifest_row_without_expected_result_is_visible_and_unscored(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = _write_case(tmp_path, state="succeeded")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-manifest.v2",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(run_dir),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    assert result["scope"]["finalized_scored_cases"] == 0
    assert result["scope"]["excluded_cases"] == 1
    assert result["excluded"] == [
        {
            "outcome": "Overall Survival",
            "trial": "GETUG-AFU-15",
            "primary_status": None,
            "result_scope": "historical_unscored",
            "reason": "expected_result is missing; historical run is unscored",
        }
    ]


def test_new_manifest_requires_frozen_scope_or_explicit_scope_unresolved(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.fresh-benchmark-index.v1",
                "rows": [
                    {"outcome": "Overall Survival", "trial": "GETUG-AFU-15"},
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "scope_unresolved": "The source metadata omitted the endpoint window.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    assert result["hard_failures"] == [
        {
            "outcome": "Overall Survival",
            "trial": "GETUG-AFU-15",
            "reason": "new benchmark row has no frozen Result scope or scope_unresolved marker",
        }
    ]
    assert result["excluded"][1]["result_scope"] == "scope_unresolved"
    assert result["excluded"][1]["reason"] == "The source metadata omitted the endpoint window."
