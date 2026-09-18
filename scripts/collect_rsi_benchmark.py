#!/usr/bin/env python3
"""Collect finalized RSI bundles into the restricted benchmark scoring schema."""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path
from typing import Any

DOMAINS = (
    ("D1", "randomization"),
    ("D2", "deviations"),
    ("D3", "missing"),
    ("D4", "measurement"),
    ("D5", "selection"),
)
SCHEMA = "rob2-kit.rsi-run-analysis.v1"


def _normalise(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _reference_label(value: str) -> str:
    labels = {
        "L": "low",
        "S": "some_concerns",
        "H": "high",
        "Low": "low",
        "Some Concerns": "some_concerns",
        "High": "high",
    }
    try:
        return labels[value]
    except KeyError as error:
        raise ValueError(f"unsupported reference label: {value}") from error


def _label_path(reference: Path, outcome: str) -> Path:
    names = {
        "progressionfreesurvival": "progression-free-survival.csv",
        "overallsurvival": "overall-survival.csv",
        "adverseevents": "adverse-events.csv",
    }
    try:
        return reference / "catalog" / "provisional-labels" / names[_normalise(outcome)]
    except KeyError as error:
        raise ValueError(f"unsupported outcome: {outcome}") from error


def _catalog_trials(reference: Path, outcome: str) -> list[str]:
    requested = _normalise(outcome)
    catalog = reference / "catalog" / "trials.csv"
    with catalog.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    trials: list[str] = []
    for row in rows:
        available = {
            _normalise(item) for item in (row.get("outcomes") or "").split(";") if item.strip()
        }
        if requested in available:
            trials.append(row["trial_slug"])
    return trials


def _gold(reference: Path, outcome: str) -> dict[str, dict[str, str]]:
    path = _label_path(reference, outcome)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {
            _normalise(row["Trial"]): {
                **{f"D{index}": _reference_label(row[f"D{index}"]) for index in range(1, 6)},
                "overall": _reference_label(row["Overall Risk"]),
            }
            for row in csv.DictReader(stream)
        }


def _bundle(trial_dir: Path) -> Path | None:
    bundles = sorted(trial_dir.rglob("*.rob2.zip"))
    return bundles[-1] if bundles else None


def _phase_details(trial_dir: Path) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for path in sorted(trial_dir.glob("phase-*.meta.json")):
        with path.open(encoding="utf-8") as stream:
            meta = json.load(stream)
        details.append(
            {
                "phase": meta.get("phase"),
                "phase_kind": meta.get("phase_kind"),
                "build_sha256": meta.get("build_sha256"),
                "skill_sha256": meta.get("skill_sha256"),
                "prompt_file": meta.get("prompt_file"),
                "prompt_sha256": meta.get("prompt_sha256"),
                "session": meta.get("session"),
            }
        )
    return details


def _read_bundle(path: Path) -> tuple[dict[str, str], str | None, dict[str, Any], str]:
    with zipfile.ZipFile(path) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    snapshots = canonical.get("snapshots", {})
    if not isinstance(snapshots, dict) or len(snapshots) != 1:
        raise ValueError(f"bundle must contain one trial snapshot: {path}")
    trial_id, snapshot = next(iter(snapshots.items()))
    if not isinstance(snapshot, dict):
        raise ValueError(f"bundle snapshot is invalid: {path}")
    judgments = snapshot.get("domain_judgments", {})
    observed = {
        domain_key: judgments[f"domain:{domain}"]
        for domain_key, domain in DOMAINS
        if isinstance(judgments.get(f"domain:{domain}"), str)
    }
    results = canonical.get("proposal", {}).get("payload", {}).get("results", [])
    proposal = results[0] if isinstance(results, list) and results else {}
    reported = proposal.get("reported", {}) if isinstance(proposal, dict) else {}
    endpoint = reported.get("endpoint", {}) if isinstance(reported, dict) else {}
    proposal_details = {
        "relation": proposal.get("relation") if isinstance(proposal, dict) else None,
        "endpoint": endpoint.get("name") if isinstance(endpoint, dict) else None,
        "definition": endpoint.get("definition") if isinstance(endpoint, dict) else None,
        "estimate": reported.get("estimate") if isinstance(reported, dict) else None,
        "precision": reported.get("precision") if isinstance(reported, dict) else None,
    }
    result_identity = snapshot.get("result_identity")
    overall = snapshot.get("overall")
    return (
        observed,
        overall if isinstance(overall, str) else None,
        proposal_details,
        str(result_identity),
    )


def collect(reference: Path, run_root: Path, outcome: str) -> tuple[dict[str, Any], dict[str, Any]]:
    trials = _catalog_trials(reference, outcome)
    gold = _gold(reference, outcome)
    cases: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for trial in trials:
        trial_dir = run_root / trial
        bundle = _bundle(trial_dir) if trial_dir.is_dir() else None
        phases = _phase_details(trial_dir) if trial_dir.is_dir() else []
        expected = gold.get(_normalise(trial))
        if expected is None:
            raise ValueError(f"reference labels are missing for eligible trial: {trial}")
        if bundle is None:
            observed: dict[str, str] = {}
            observed_overall = None
            proposal: dict[str, Any] = {}
            result_identity = None
            completion = "incomplete" if phases else "unknown"
        else:
            observed, observed_overall, proposal, result_identity = _read_bundle(bundle)
            completion = "finalized"
        case_id = f"{run_root.name}-{_normalise(outcome)}-{_normalise(trial)}"
        cases.append(
            {
                "case_id": case_id,
                "trial_id": trial,
                "outcome": outcome,
                "scope": "eligible",
                "completion": completion,
                "expected": {key: expected[key] for key, _ in DOMAINS},
                "observed": observed,
                "failure_causes": {},
                "result_identity": result_identity,
            }
        )
        details.append(
            {
                "case_id": case_id,
                "trial_id": trial,
                "outcome": outcome,
                "expected_overall": expected["overall"],
                "observed_overall": observed_overall,
                "bundle": str(bundle) if bundle else None,
                "proposal": proposal,
                "phases": phases,
                "proposal_correction_count": sum(
                    phase.get("phase_kind") == "proposal_correction" for phase in phases
                ),
            }
        )
    sidecar = {"schema": SCHEMA, "cases": cases}
    detail_doc = {
        "schema": "rob2-kit.rsi-benchmark-details.v1",
        "reference": str(reference),
        "run_root": str(run_root),
        "outcome": outcome,
        "cases": details,
    }
    return sidecar, detail_doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--details-output", type=Path, required=True)
    args = parser.parse_args()
    sidecar, details = collect(args.reference, args.run_root, args.outcome)
    args.output.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.details_output.write_text(
        json.dumps(details, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Collected {len(sidecar['cases'])} eligible {args.outcome} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
