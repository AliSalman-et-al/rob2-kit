from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.score_trial_benchmark import score


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
            }
        }
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("canonical.json", json.dumps(canonical))
            archive.writestr("verification.json", json.dumps({"result": "verified"}))
    return run_dir


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
    assert result["excluded"][0]["reason"] == "execution state=resumable, last phase=resumable"
