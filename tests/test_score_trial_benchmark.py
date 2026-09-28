from __future__ import annotations

import hashlib
import json
import runpy
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_scorer = runpy.run_path(str(SCRIPTS / "score_trial_benchmark.py"))
_result_dimensions = _scorer["_result_dimensions"]
_result_mismatches = _scorer["_result_mismatches"]
_mismatch_facets = _scorer["_mismatch_facets"]
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
        "result_scope_denominators": {
            "mechanical_match": 0,
            "mechanical_mismatch": 0,
            "adjudicated_equivalent": 0,
            "accepted_with_scope_difference": 0,
            "unavailable": 0,
            "mismatch": 0,
            "unresolved": 0,
        },
        "review_required_cases": 0,
        "combined_primary_score": {"cases": 0, "domain_cells": 0},
        "proposal_relation_denominators": {
            "exact": 0,
            "broader": 0,
            "narrower": 0,
            "component": 0,
            "related": 0,
            "unknown": 2,
        },
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

    assert (
        _result_mismatches(expected, _result_dimensions(result, "GETUG-AFU-15"), "GETUG-AFU-15")
        == []
    )


def test_score_requires_exact_result_scope_before_reading_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def labels_must_not_be_read(_root: Path) -> dict[tuple[str, str], object]:
        raise AssertionError("labels were read before Result scope was validated")

    monkeypatch.setitem(score.__globals__, "_load_reference", labels_must_not_be_read)

    result = score(manifest, reference)

    assert result["scope"]["finalized_scored_cases"] == 0
    assert result["scope"]["excluded_cases"] == 1
    assert "population" in result["excluded"][0]["reason"]
    assert result["excluded"][0]["result_scope"] == "mismatched"
    assert result["excluded"][0]["correspondence"] == "unresolved"
    assert "population" in result["excluded"][0]["result_scope_details"]["differing_facets"]


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
    markdown = render_markdown(result)
    details = excluded["result_scope_details"]
    assert details["code"] == "result_scope_mismatch"
    definition = next(item for item in details["fields"] if item["field"] == "endpoint_definition")
    assert set(definition["expected"]) == {"present", "kind", "length", "sha256"}
    assert set(definition["observed"]) == {"present", "kind", "length", "sha256"}
    assert "PRIVATE_SOURCE_TEXT" not in json.dumps(excluded)
    assert excluded["artifact"] == {
        "path": "result.rob2.zip",
        "sha256": hashlib.sha256((run_dir / "result.rob2.zip").read_bytes()).hexdigest(),
        "identity": artifact_identity,
        "verified": True,
    }
    assert result["scope"]["result_scope_denominators"]["mismatch"] == 1
    assert result["hard_failures"][0]["result_scope_details"]["code"] == ("result_scope_mismatch")
    assert excluded["correspondence"] == "unresolved"
    assert "endpoint_definition" in details["differing_facets"]
    assert "PRIVATE_SOURCE_TEXT" not in markdown
    assert "endpoint_definition" in markdown


def test_identity_mismatched_scope_adjudication_remains_unresolved(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = _write_case(tmp_path, state="succeeded")
    bundle = run_dir / "workspace" / ".rob2-kit" / "finalized" / "case.rob2.zip"
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        verification = archive.read("verification.json")
    canonical["snapshots"]["GETUG-AFU-15"] = canonical["snapshots"].pop("getug")
    result_record = canonical["proposal"]["payload"]["results"][0]
    result_record["relation"] = "narrower"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", verification)

    expected = _expected_result()
    expected["population"] = "a different frozen population"
    expected_hash = score.__globals__["expected_result_sha256"](expected)
    adjudications = tmp_path / "scope-adjudications.json"
    adjudications.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-scope-adjudications.v2",
                "adjudications": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "expected_result_sha256": expected_hash,
                        "review_identity": "sha256:stale-review",
                        "result_identity": "sha256:stale-result",
                        "observed_relation": "narrower",
                        "decision": "equivalent",
                        "rationale": "A stale decision must not settle this correspondence.",
                        "source_citation": "Main article, p. 1.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
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
                        "expected_result": expected,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference, adjudications)
    excluded = result["excluded"][0]

    assert excluded["result_scope"] == "unresolved"
    assert excluded["correspondence"] == "unresolved"
    assert excluded["result_scope_details"]["code"] == "scope_adjudication_identity_mismatch"
    assert excluded["proposal_relation"] == "narrower"
    assert "population" in excluded["result_scope_details"]["differing_facets"]
    assert result["scope"]["finalized_scored_cases"] == 0
    assert result["scope"]["result_scope_denominators"]["unresolved"] == 1
    assert result["scope"]["result_scope_denominators"]["adjudicated_equivalent"] == 0


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
    assert result["scope"]["result_scope_denominators"] == {
        "mechanical_match": 1,
        "mechanical_mismatch": 1,
        "adjudicated_equivalent": 0,
        "accepted_with_scope_difference": 1,
        "unavailable": 0,
        "mismatch": 0,
        "unresolved": 0,
    }
    assert result["pooled"]["case_count"] == 1
    assert result["sensitivity"]["pooled"]["case_count"] == 2
    assert result["sensitivity"]["pooled"]["domain_cells"] == 10
    assert result["sensitivity"]["by_outcome"]["Overall Survival"]["case_count"] == 2
    assert result["sensitivity"]["by_domain"]["D1"]["exact"]["total"] == 2
    assert (
        result["sensitivity"]["by_outcome_domain"]["Overall Survival"]["D1"]["exact"]["total"] == 2
    )
    assert result["sensitivity"]["by_primary_status"]["primary"]["case_count"] == 2
    assert (
        result["scope_difference_cases"][0]["scope_adjudication"]["decision"]
        == "accepted_with_scope_difference"
    )
    assert result["scope_difference_cases"][0]["result_scope"] == ("accepted_with_scope_difference")
    markdown = render_markdown(result)
    assert "Scope-difference sensitivity" in markdown
    assert "accepted_with_scope_difference" in markdown
    assert "mechanical matches 1; mechanical mismatches 1;" in markdown
    assert "accepted scope differences 1" in markdown


def test_score_report_separates_format_and_wording_equivalents_from_proposal_relation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    records = [
        {
            "observed": labels,
            "bundle": "format.rob2.zip",
            "proposal_relation": "exact",
            "scope_adjudication": {
                "expected_result_sha256": "a" * 64,
                "review_identity": "sha256:review-format",
                "result_identity": "sha256:result-format",
                "decision": "equivalent",
                "rationale": "The estimate uses a different number format for the same result.",
                "source_citation": "Main article, p. 1.",
            },
            "result_scope_details": {
                "mechanical_match": False,
                "differing_facets": ["reported_scope.estimate"],
                "proposal_relation": "exact",
            },
        },
        {
            "observed": labels,
            "bundle": "wording.rob2.zip",
            "proposal_relation": "narrower",
            "scope_adjudication": {
                "expected_result_sha256": "b" * 64,
                "review_identity": "sha256:review-wording",
                "result_identity": "sha256:result-wording",
                "decision": "equivalent",
                "rationale": (
                    "The endpoint wording differs, but the cited passage "
                    "identifies the same endpoint."
                ),
                "source_citation": "Supplement, p. 4.",
            },
            "result_scope_details": {
                "mechanical_match": False,
                "differing_facets": ["endpoint_definition", "reported_scope.endpoint.definition"],
                "proposal_relation": "narrower",
            },
        },
    ]
    monkeypatch.setitem(
        score.__globals__,
        "_bundle_snapshot",
        lambda *_args, **_kwargs: (records.pop(0), None),
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-manifest.v2",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(tmp_path / name),
                        "expected_result": _expected_result(),
                    }
                    for name in ("format", "wording")
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, tmp_path / "reference")
    markdown = render_markdown(result, publish_adjudication_details=True)

    assert result["scope"]["combined_primary_score"] == {"cases": 2, "domain_cells": 10}
    assert result["scope"]["result_scope_denominators"]["mechanical_match"] == 0
    assert result["scope"]["result_scope_denominators"]["mechanical_mismatch"] == 2
    assert result["scope"]["result_scope_denominators"]["adjudicated_equivalent"] == 2
    assert result["scope"]["proposal_relation_denominators"] == {
        "exact": 1,
        "broader": 0,
        "narrower": 1,
        "component": 0,
        "related": 0,
        "unknown": 0,
    }
    assert result["cases"][0]["result_scope"] == "adjudicated_equivalent"
    assert "reported_scope.estimate" in markdown
    assert "reported_scope.endpoint.definition" in markdown
    assert "sha256:result-format" in markdown
    assert "The estimate uses a different number format" in markdown
    assert "Supplement, p. 4." in markdown
    public_default = render_markdown(result)
    assert "The estimate uses a different number format" not in public_default
    assert "Supplement, p. 4." not in public_default


def test_changed_safety_grouping_facets_are_reported_without_claiming_equivalence() -> None:
    observed = {
        "trial_id": "GETUG-AFU-15",
        "target": {
            "comparison_groups": [
                {"id": "darolutamide", "assignment": "actual treatment"},
                {"id": "placebo", "assignment": "assigned control"},
            ],
            "outcome_definition": "grade 3 or higher adverse events",
            "intended_analysis_population": "all randomized participants",
            "time_point_or_window": "during treatment",
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "safety set",
            "endpoint": {"name": "grade 3 or 4 adverse events"},
            "group_values": [
                {"group_id": "darolutamide", "value": "66.1"},
                {"group_id": "placebo", "value": "63.5"},
            ],
        },
    }
    expected = {
        "trial": "GETUG-AFU-15",
        "comparison": [
            {"id": "treatment", "assignment": "assigned treatment"},
            {"id": "control", "assignment": "assigned control"},
        ],
        "endpoint_definition": "grade 3 or higher adverse events",
        "population": "all randomized participants",
        "window": "during treatment",
        "reported_scope": {
            "form": "group_bound_values",
            "analysis_population": "safety set",
            "endpoint": {"name": "grade 3 or 4 adverse events"},
            "group_values": [
                {"group_id": "treatment", "value": "66.1"},
                {"group_id": "control", "value": "63.5"},
            ],
        },
    }

    mismatches = _result_mismatches(
        expected, _result_dimensions(observed, "GETUG-AFU-15"), "GETUG-AFU-15"
    )
    facets = _mismatch_facets(mismatches)

    assert "comparison[0].id" in facets
    assert "reported_scope.group_values[0].group_id" in facets
    assert "reported_scope.group_values[1].group_id" in facets


def test_scope_review_required_grouping_case_stays_unresolved_and_unscored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = {
        "expected_result_sha256": "a" * 64,
        "review_identity": "sha256:review-arasens",
        "result_identity": "sha256:result-arasens",
        "decision": "equivalent",
        "rationale": (
            "The generic rationale does not address the treatment-received group membership."
        ),
        "source_citation": "ARASENS main article, p. 4; Table 3, p. 8.",
    }
    bundle = {
        "observed": {},
        "bundle": "arasens-ae.rob2.zip",
        "proposal_relation": "narrower",
        "scope_adjudication": review,
        "result_scope_details": {
            "mechanical_match": False,
            "differing_facets": [
                "comparison[0].id",
                "reported_scope.group_values[0].group_id",
            ],
            "proposal_relation": "narrower",
        },
    }
    monkeypatch.setitem(
        score.__globals__,
        "_bundle_snapshot",
        lambda *_args, **_kwargs: (bundle, None),
    )
    monkeypatch.setitem(
        score.__globals__,
        "_load_reference",
        lambda _root: (_ for _ in ()).throw(AssertionError("labels must not be loaded")),
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.fresh-benchmark-index.v1",
                "rows": [
                    {
                        "outcome": "Adverse Events",
                        "trial": "ARASENS",
                        "run_dir": str(tmp_path / "arasens"),
                        "expected_result": _expected_result(),
                        "scope_review_required": (
                            "A separate source-grounded decision is required for group membership."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, tmp_path / "reference")
    pending = result["review_required_cases"][0]

    assert result["scope"]["combined_primary_score"] == {"cases": 0, "domain_cells": 0}
    assert result["scope"]["result_scope_denominators"] == {
        "mechanical_match": 0,
        "mechanical_mismatch": 1,
        "adjudicated_equivalent": 0,
        "accepted_with_scope_difference": 0,
        "unavailable": 0,
        "mismatch": 0,
        "unresolved": 1,
    }
    assert result["scope"]["proposal_relation_denominators"]["narrower"] == 1
    assert pending["result_scope"] == "unresolved"
    assert pending["scope_adjudication"]["decision"] == "equivalent"
    assert pending["scope_review_required"].startswith("A separate")
    markdown = render_markdown(result, publish_adjudication_details=True)
    assert "reported_scope.group_values[0].group_id" in markdown
    assert "sha256:result-arasens" in markdown
    assert "A separate source-grounded decision is required" in markdown
    assert "A separate source-grounded decision is required" in render_markdown(result)


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


def test_historical_score_schema_remains_renderable_with_its_original_scope_labels(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema": "rob2-kit.benchmark-manifest.v2", "rows": []}),
        encoding="utf-8",
    )
    result = score(manifest, reference)
    result["schema"] = "rob2-kit.trial-benchmark-score.v1"
    result["scope"]["result_scope_denominators"] = {
        "exact": 26,
        "approved_proxy": 0,
        "unavailable": 0,
        "mismatch": 0,
    }

    markdown = render_markdown(result)

    assert "Result-scope cases: exact 26; approved proxy 0; unavailable 0; mismatch 0." in markdown
    assert "## Pooled result" in markdown
    assert "## Excluded cases" in markdown
    assert "## Result-scope correspondence" not in markdown


def test_missing_approved_result_has_its_own_unavailable_denominator(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = _write_case(tmp_path, state="succeeded")
    bundle = run_dir / "workspace" / ".rob2-kit" / "finalized" / "case.rob2.zip"
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        verification = archive.read("verification.json")
    canonical["snapshots"]["GETUG-AFU-15"] = canonical["snapshots"].pop("getug")
    canonical["proposal"]["payload"]["results"] = []
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", verification)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.trial-benchmark-manifest.v3",
                "rows": [
                    {
                        "outcome": "Overall Survival",
                        "trial": "GETUG-AFU-15",
                        "run_dir": str(run_dir),
                        "expected_result": _expected_result(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    assert result["scope"]["result_scope_denominators"] == {
        "mechanical_match": 0,
        "mechanical_mismatch": 0,
        "adjudicated_equivalent": 0,
        "accepted_with_scope_difference": 0,
        "unavailable": 1,
        "mismatch": 0,
        "unresolved": 0,
    }
    assert result["excluded"][0]["result_scope_details"] == {"code": "approved_result_unavailable"}


def test_historical_result_mismatch_keeps_artifact_and_explicit_unscored_reason(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference)
    run_dir = _write_case(tmp_path, state="succeeded")
    bundle = run_dir / "workspace" / ".rob2-kit" / "finalized" / "case.rob2.zip"
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        verification = archive.read("verification.json")
    canonical["snapshots"]["GETUG-AFU-15"] = canonical["snapshots"].pop("getug")
    result_record = canonical["proposal"]["payload"]["results"][0]
    result_record["target"]["outcome_definition"] = "a different endpoint"
    result_record["reported"]["endpoint"]["definition"] = "a different endpoint"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", verification)
    expected = cast(dict[str, Any], _expected_result())
    expected["endpoint_definition"] = "expected endpoint"
    expected["reported_scope"]["endpoint"]["definition"] = "expected endpoint"
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
                        "expected_result": expected,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = score(manifest, reference)

    excluded = result["excluded"][0]
    assert excluded["result_scope_details"]["code"] == "result_scope_mismatch"
    assert excluded["artifact"] == {
        "path": bundle.relative_to(run_dir).as_posix(),
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "identity": None,
    }
    assert result["hard_failures"] == []
    assert result["scope"]["result_scope_denominators"]["mismatch"] == 1


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
