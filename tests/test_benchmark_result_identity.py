from __future__ import annotations

import csv
import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from support.rob2 import _assessed_artifact, _workspace

from rob2_kit.application._state import _identity

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

artifact_manifest_identity = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))[
    "artifact_manifest_identity"
]
_result_dimensions = runpy.run_path(str(SCRIPTS / "score_trial_benchmark.py"))["_result_dimensions"]


def _write_reference(reference: Path, trial: str = "trial") -> None:
    catalog = reference / "catalog"
    labels = catalog / "provisional-labels"
    labels.mkdir(parents=True)
    (catalog / "trials.csv").write_text(
        "trial_label,trial_slug,source_directory,nct_number,outcomes\n"
        f"{trial},{trial},sources/{trial},NCT00000001,Overall Survival\n",
        encoding="utf-8",
    )
    row = [trial, "L", "S", "L", "S", "L", "Some Concerns"]
    for filename in (
        "overall-survival.csv",
        "progression-free-survival.csv",
        "adverse-events.csv",
    ):
        with (labels / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Trial", "D1", "D2", "D3", "D4", "D5", "Overall Risk"])
            writer.writerow(row)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_real_verified_bundle_collects_and_scores_without_result_identity_field(
    tmp_path: Path,
) -> None:
    campaign = "campaign"
    outcome = "Overall Survival"
    trial = "trial"
    run_root = tmp_path / campaign / "overall-survival"
    trial_dir = run_root / trial
    workspace = _workspace(trial_dir / "workspace", outcome)
    bundle = _assessed_artifact(workspace, outcome)
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    result = canonical["proposal"]["payload"]["results"][0]
    snapshot = canonical["snapshots"][trial]
    assert "identity" not in result
    expected_result_identity = snapshot["result_identity"]
    assert expected_result_identity == _identity(result)

    expected = _result_dimensions(result, trial)
    batch_trial = next(item for item in canonical["batch"]["trials"] if item["id"] == trial)
    run_inputs = {
        "trial": trial,
        "requested_outcome": outcome,
        "expected_result": expected,
        "sources": batch_trial["sources"],
    }
    run_inputs_path = trial_dir / "run-inputs.json"
    run_inputs_path.write_text(json.dumps(run_inputs), encoding="utf-8")
    case_path = trial_dir / "case.json"
    case_path.write_text(json.dumps({"expected_result": expected}), encoding="utf-8")
    prompt_path = trial_dir / "prompt.txt"
    prompt_path.write_text("Assess the supplied Trial.", encoding="utf-8")
    attempt_id = "attempt-real-bundle"
    identity = {
        "campaign_id": campaign,
        "case_id": "campaign-overallsurvival-trial",
        "trial_id": trial,
        "outcome": outcome,
    }
    artifact_identity = artifact_manifest_identity(bundle)
    execution = {
        "schema": "rob2-kit.rsi-execution.v1",
        "identity": identity,
        "state": "succeeded",
        "selected_attempt_rule": "declared",
        "selection_policy": {"selected_attempt_id": attempt_id, "rule": "declared"},
        "attempts": [
            {
                "attempt_id": attempt_id,
                "phase": 1,
                "selected": True,
                "expected_result_sha256": _sha256_json(expected),
            }
        ],
        "phases": [
            {
                "phase": 1,
                "attempt_id": attempt_id,
                "state": "succeeded",
                "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
            }
        ],
        "prompt_sha256_by_phase": {"1": hashlib.sha256(prompt_path.read_bytes()).hexdigest()},
        "run_input_sha256": _sha256_json(run_inputs),
        "expected_result_sha256": _sha256_json(expected),
        "manifest_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "artifact": {
            "path": bundle.relative_to(trial_dir).as_posix(),
            "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "identity": artifact_identity,
            "verified": True,
            "attempt_id": attempt_id,
        },
    }
    (trial_dir / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
    (trial_dir / "phase-1.meta.json").write_text(
        json.dumps(
            {
                "prompt_file": str(prompt_path),
                "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference"
    _write_reference(reference, trial)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "outcome": outcome,
                        "trial": trial,
                        "run_dir": str(trial_dir),
                        "case_path": str(case_path),
                        "prompt_path": str(prompt_path),
                        "expected_result": expected,
                        "primary_status": "primary",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    collected = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "collect_rsi_benchmark.py"),
            "--reference",
            str(reference),
            "--run-root",
            str(run_root),
            "--outcome",
            outcome,
            "--output",
            str(tmp_path / "collected.json"),
            "--details-output",
            str(tmp_path / "details.json"),
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert collected.returncode == 0, collected.stderr
    sidecar = json.loads((tmp_path / "collected.json").read_text(encoding="utf-8"))
    assert sidecar["cases"][0]["result_identity"] == expected_result_identity
    scored_path = tmp_path / "score.json"
    scored = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "score_trial_benchmark.py"),
            "--manifest",
            str(manifest),
            "--reference",
            str(reference),
            "--output",
            str(scored_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert scored.returncode == 0, scored.stderr
    assert (
        json.loads(scored_path.read_text(encoding="utf-8"))["scope"]["finalized_scored_cases"] == 1
    )


def _write_v1_scoring_case(
    run_dir: Path,
    *,
    wrong_trial: bool = False,
    ambiguous_result: bool = False,
    missing_attempts: bool = False,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True)
    result = {
        "trial_id": "GETUG-AFU-15",
        "target": {
            "comparison_groups": [{"id": "A", "assignment": "A"}, {"id": "B", "assignment": "B"}],
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
    result_identity = _identity(result)
    snapshot_trial = "another-trial" if wrong_trial else "GETUG-AFU-15"
    results = [result, dict(result)] if ambiguous_result else [result]
    canonical = {
        "snapshots": {
            snapshot_trial: {
                "result_identity": result_identity,
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
        "proposal": {"payload": {"results": results}},
    }
    bundle = run_dir / "case.rob2.zip"
    artifact_identity = "sha256:" + "a" * 64
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"identity": artifact_identity}))
        archive.writestr("canonical.json", json.dumps(canonical))
        archive.writestr("verification.json", json.dumps({"result": "verified"}))
    expected = _result_dimensions(result, "GETUG-AFU-15")
    attempt_id = "attempt-selected"
    execution = {
        "schema": "rob2-kit.rsi-execution.v1",
        "state": "succeeded",
        "expected_result_sha256": _sha256_json(expected),
        "selection_policy": {"selected_attempt_id": attempt_id},
        "artifact": {
            "path": "case.rob2.zip",
            "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "identity": artifact_identity,
            "verified": True,
            "attempt_id": attempt_id,
        },
    }
    if not missing_attempts:
        execution["attempts"] = [
            {
                "attempt_id": attempt_id,
                "phase": 1,
                "selected": True,
                "expected_result_sha256": _sha256_json(expected),
            }
        ]
    (run_dir / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
    return expected


def test_scoring_command_hard_fails_wrong_trial_and_ambiguous_result_before_labels(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference, "GETUG-AFU-15")
    cases = (
        ("wrong-trial", {"wrong_trial": True}, "trial scope mismatch"),
        ("ambiguous-result", {"ambiguous_result": True}, "unavailable or ambiguous"),
    )
    for case_name, options, reason in cases:
        run_dir = tmp_path / case_name
        expected = _write_v1_scoring_case(run_dir, **options)
        manifest = tmp_path / f"{case_name}.json"
        output = tmp_path / f"{case_name}-score.json"
        manifest.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "outcome": "Overall Survival",
                            "trial": "GETUG-AFU-15",
                            "run_dir": str(run_dir),
                            "expected_result": expected,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "score_trial_benchmark.py"),
                "--manifest",
                str(manifest),
                "--reference",
                str(reference),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 2, completed.stderr
        assert output.exists(), completed.stderr
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["scope"]["finalized_scored_cases"] == 0
        assert len(report["hard_failures"]) == 1
        assert reason in report["hard_failures"][0]["reason"]


def test_scoring_command_hard_fails_fresh_succeeded_execution_without_attempt_history(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference, "GETUG-AFU-15")
    run_dir = tmp_path / "missing-attempts"
    expected = _write_v1_scoring_case(run_dir, missing_attempts=True)
    manifest = tmp_path / "fresh.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.trial-benchmark-manifest.v3",
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
    output = tmp_path / "fresh-score.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "score_trial_benchmark.py"),
            "--manifest",
            str(manifest),
            "--reference",
            str(reference),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["scope"]["finalized_scored_cases"] == 0
    assert result["hard_failures"] == [
        {
            "outcome": "Overall Survival",
            "trial": "GETUG-AFU-15",
            "reason": "execution attempt history is missing for a fresh benchmark",
        }
    ]


def test_fresh_scorer_reverifies_bundle_instead_of_trusting_forged_verification_json(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference"
    _write_reference(reference, "GETUG-AFU-15")
    run_dir = tmp_path / "forged"
    expected = _write_v1_scoring_case(run_dir)
    manifest = tmp_path / "fresh.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.trial-benchmark-manifest.v3",
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
    output = tmp_path / "score.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "score_trial_benchmark.py"),
            "--manifest",
            str(manifest),
            "--reference",
            str(reference),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["scope"]["finalized_scored_cases"] == 0
    assert "independent bundle verification failed" in report["hard_failures"][0]["reason"]
