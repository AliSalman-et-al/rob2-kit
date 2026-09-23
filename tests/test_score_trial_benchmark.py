from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.score_trial_benchmark import _result_dimensions, _result_mismatches, score


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
    }


def test_score_uses_trial_aliases_and_excludes_unfinished_cases(tmp_path: Path) -> None:
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
                        "expected_result": _expected_result(),
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
        "finalized_scored_cases": 1,
        "finalized_domain_cells": 5,
        "excluded_cases": 1,
    }
    assert result["pooled"]["pooled_domains"]["exact"] == {
        "correct": 5,
        "total": 5,
        "rate": 1.0,
    }
    assert result["excluded"][0]["reason"] == (
        "expected_result is missing; historical run is unscored"
    )


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
        "estimate": "HR 1.01",
        "precision": "95% CI 0.75 to 1.36",
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
                            "comparison_groups": [{"id": "A"}, {"id": "B"}],
                            "outcome_definition": "PRIVATE_SOURCE_TEXT_OBSERVED",
                            "intended_analysis_population": "all randomized participants",
                            "time_point_or_window": {"kind": "fixed", "description": "36 months"},
                        },
                        "reported": {
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
        "comparison": [{"id": "A"}, {"id": "B"}],
        "endpoint_definition": "PRIVATE_SOURCE_TEXT_EXPECTED",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "36 months"},
        "estimate": "HR 1.01",
        "precision": "95% CI 0.75 to 1.36",
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
