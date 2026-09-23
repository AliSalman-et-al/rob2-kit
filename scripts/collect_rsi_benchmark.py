#!/usr/bin/env python3
"""Collect finalized RSI bundles into the restricted benchmark scoring schema."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import runpy
import zipfile
from pathlib import Path
from typing import Any

from benchmark_contract import artifact_manifest_identity

from rob2_kit.evaluation.adjudication import read_sidecar, validate_sidecars

DOMAINS = (
    ("D1", "randomization"),
    ("D2", "deviations"),
    ("D3", "missing"),
    ("D4", "measurement"),
    ("D5", "selection"),
)
SCHEMA = "rob2-kit.rsi-run-analysis.v1"
EXECUTION_SCHEMA = "rob2-kit.rsi-execution.v1"
HISTORICAL_EXECUTION_COMPATIBILITY = "historical-unqualified"


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


def _labels_match(left: str, right: object) -> bool:
    """Compare canonical labels while allowing human-facing case/spacing."""

    return isinstance(right, str) and _normalise(left) == _normalise(right)


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


def _benchmark_rows(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"benchmark manifest is unreadable: {path}") from error
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("benchmark manifest rows are missing")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("trial"), str)
            or not isinstance(row.get("outcome"), str)
        ):
            raise ValueError("benchmark manifest row is malformed")
        key = (_normalise(row["outcome"]), _normalise(row["trial"]))
        if key in indexed:
            raise ValueError(f"duplicate benchmark manifest row: {key}")
        indexed[key] = row
    return indexed


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


def _bundle(
    trial_dir: Path,
    execution: dict[str, Any] | None = None,
    *,
    legacy_read_only: bool = False,
) -> Path | None:
    """Return only the recorded artifact; legacy mode is deliberately explicit."""
    bundles = list(trial_dir.rglob("*.rob2.zip"))
    if execution is None:
        if not legacy_read_only:
            raise ValueError(f"execution.json is required for {trial_dir}")
        if len(bundles) > 1:
            raise ValueError(f"duplicate legacy bundles found in {trial_dir}")
        return bundles[0] if bundles else None
    artifact = execution.get("artifact")
    if execution.get("state") != "succeeded":
        if bundles:
            raise ValueError(f"unclaimed bundle exists for non-successful execution in {trial_dir}")
        return None
    if not isinstance(artifact, dict):
        raise ValueError(f"successful execution has no artifact record: {trial_dir}")
    if artifact.get("verified") is not True:
        raise ValueError(f"successful execution has an unverified artifact: {trial_dir}")
    recorded = artifact.get("path")
    if not isinstance(recorded, str):
        raise ValueError(f"successful execution has no recorded artifact path: {trial_dir}")
    path = (trial_dir / recorded).resolve()
    if not path.is_file() or not path.is_relative_to(trial_dir.resolve()):
        raise ValueError(f"recorded artifact is stale or moved: {recorded}")
    if len(bundles) != 1 or bundles[0].resolve() != path:
        raise ValueError(f"stale or duplicate bundle artifacts found in {trial_dir}")
    expected_hash = artifact.get("sha256")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_hash != actual_hash:
        raise ValueError(f"bundle hash mismatch for {path}")
    recorded_identity = artifact.get("identity")
    if not isinstance(recorded_identity, str) or not recorded_identity:
        raise ValueError(f"successful execution has no artifact identity: {trial_dir}")
    internal_identity = artifact_manifest_identity(path)
    if recorded_identity != internal_identity:
        raise ValueError(f"artifact identity mismatch for {path}")
    return path


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


def _read_bundle(
    path: Path, *, expected_trial: str | None = None, expected_outcome: str | None = None
) -> tuple[dict[str, str], str | None, dict[str, Any], str]:
    with zipfile.ZipFile(path) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    snapshots = canonical.get("snapshots", {})
    if not isinstance(snapshots, dict) or len(snapshots) != 1:
        raise ValueError(f"bundle must contain one trial snapshot: {path}")
    trial_id, snapshot = next(iter(snapshots.items()))
    if expected_trial is not None and _normalise(str(trial_id)) != _normalise(expected_trial):
        raise ValueError(
            f"bundle trial identity mismatch: expected {expected_trial}, observed {trial_id}"
        )
    if not isinstance(snapshot, dict):
        raise ValueError(f"bundle snapshot is invalid: {path}")
    batch = canonical.get("batch")
    batch_trials = batch.get("trials") if isinstance(batch, dict) else None
    batch_trial = (
        next(
            (
                item
                for item in batch_trials
                if isinstance(item, dict)
                and _normalise(str(item.get("id", ""))) == _normalise(str(trial_id))
            ),
            None,
        )
        if isinstance(batch_trials, list)
        else None
    )
    if expected_outcome is not None and (
        not isinstance(batch_trial, dict)
        or not isinstance(batch_trial.get("requested_outcome"), str)
        or not batch_trial["requested_outcome"].strip()
    ):
        raise ValueError(
            f"bundle trial-specific requested outcome is missing for {trial_id}; "
            f"benchmark concept was {expected_outcome}"
        )
    judgments = snapshot.get("domain_judgments", {})
    observed = {
        domain_key: judgments[f"domain:{domain}"]
        for domain_key, domain in DOMAINS
        if isinstance(judgments.get(f"domain:{domain}"), str)
    }
    if set(observed) != {domain_key for domain_key, _ in DOMAINS}:
        raise ValueError(f"bundle snapshot is missing domain judgments: {path}")
    results = canonical.get("proposal", {}).get("payload", {}).get("results", [])
    trial_results = (
        [item for item in results if isinstance(item, dict) and item.get("trial_id") == trial_id]
        if isinstance(results, list)
        else []
    )
    if len(trial_results) != 1:
        raise ValueError(f"bundle Result coverage is not unique for {trial_id}: {path}")
    proposal = trial_results[0]
    reported = proposal.get("reported", {}) if isinstance(proposal, dict) else {}
    endpoint = reported.get("endpoint", {}) if isinstance(reported, dict) else {}
    target = proposal.get("target", {}) if isinstance(proposal, dict) else {}
    proposal_details = {
        "trial": trial_id,
        "relation": proposal.get("relation") if isinstance(proposal, dict) else None,
        "comparison": target.get("comparison_groups") if isinstance(target, dict) else None,
        "endpoint": endpoint.get("name") if isinstance(endpoint, dict) else None,
        "endpoint_definition": (
            target.get("outcome_definition")
            if isinstance(target, dict) and target.get("outcome_definition") is not None
            else endpoint.get("definition")
            if isinstance(endpoint, dict)
            else None
        ),
        "population": (
            target.get("intended_analysis_population") if isinstance(target, dict) else None
        ),
        "window_or_cutoff": (
            target.get("time_point_or_window") if isinstance(target, dict) else None
        ),
        "estimate": reported.get("estimate") if isinstance(reported, dict) else None,
        "precision": reported.get("precision") if isinstance(reported, dict) else None,
    }
    proposal_details["definition"] = proposal_details["endpoint_definition"]
    result_identity = snapshot.get("result_identity")
    overall = snapshot.get("overall")
    return (
        observed,
        overall if isinstance(overall, str) else None,
        proposal_details,
        str(result_identity),
    )


def _execution(
    trial_dir: Path, identity: dict[str, str], *, legacy_read_only: bool
) -> dict[str, Any] | None:
    path = trial_dir / "execution.json"
    if not path.is_file():
        if legacy_read_only:
            return None
        raise ValueError(f"missing authoritative execution.json: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid execution.json: {path}") from error
    if (
        not isinstance(record, dict)
        or record.get("schema") != EXECUTION_SCHEMA
        or record.get("identity") != identity
    ):
        raise ValueError(f"execution identity mismatch: {path}")
    attempts = record.get("attempts")
    if (
        not isinstance(attempts, list)
        or not attempts
        or any(
            not isinstance(attempt, dict) or not isinstance(attempt.get("attempt_id"), str)
            for attempt in attempts
        )
    ):
        historical = dict(record)
        historical["compatibility"] = {
            "mode": HISTORICAL_EXECUTION_COMPATIBILITY,
            "schema": EXECUTION_SCHEMA,
            "reason": "immutable attempt identity was not recorded",
        }
        return historical
    attempt_ids: set[str] = set()
    selected_ids: set[str] = set()
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or not isinstance(attempt.get("attempt_id"), str):
            raise ValueError(f"execution attempt {index} is missing an immutable identity: {path}")
        attempt_id = attempt["attempt_id"]
        attempt_ids.add(attempt_id)
        if attempt.get("selected") is True:
            selected_ids.add(attempt_id)
    if len(selected_ids) > 1:
        raise ValueError(f"execution selects more than one attempt: {path}")
    policy = record.get("selected_attempt_rule")
    if not isinstance(policy, str) or not policy.strip():
        raise ValueError(f"execution selection policy is missing: {path}")
    selection = record.get("selection_policy")
    if isinstance(selection, dict) and selection.get("selected_attempt_id") not in {
        None,
        *attempt_ids,
    }:
        raise ValueError(f"execution selected attempt is unknown: {path}")
    return record


def _is_historical_execution(record: dict[str, Any] | None) -> bool:
    compatibility = record.get("compatibility") if isinstance(record, dict) else None
    return (
        isinstance(compatibility, dict)
        and compatibility.get("mode") == HISTORICAL_EXECUTION_COMPATIBILITY
    )


def _validate_execution_inputs(
    trial_dir: Path,
    execution: dict[str, Any],
    *,
    trial: str,
    outcome: str,
    manifest_row: dict[str, Any] | None,
    bundle: Path | None,
) -> None:
    """Bind a successful artifact to the frozen case, prompt, and inputs."""

    run_inputs_path = trial_dir / "run-inputs.json"
    if not run_inputs_path.is_file():
        raise ValueError(f"authoritative run inputs are missing: {run_inputs_path}")
    try:
        run_inputs = json.loads(run_inputs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"authoritative run inputs are invalid: {run_inputs_path}") from error
    if (
        not isinstance(run_inputs, dict)
        or run_inputs.get("trial") != trial
        or run_inputs.get("requested_outcome") != outcome
    ):
        raise ValueError(f"execution input identity mismatch for {trial}")
    expected_input_hash = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if execution.get("run_input_sha256") != expected_input_hash:
        raise ValueError(f"run-input hash mismatch for {trial}")
    if bundle is not None:
        try:
            with zipfile.ZipFile(bundle) as archive:
                canonical = json.loads(archive.read("canonical.json"))
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                f"authoritative bundle canonical data is unreadable: {bundle}"
            ) from error
        batch = canonical.get("batch") if isinstance(canonical, dict) else None
        batch_trials = batch.get("trials") if isinstance(batch, dict) else None
        bundle_trial = (
            next(
                (
                    item
                    for item in batch_trials
                    if isinstance(item, dict)
                    and _normalise(str(item.get("id", ""))) == _normalise(trial)
                ),
                None,
            )
            if isinstance(batch_trials, list)
            else None
        )
        if not isinstance(bundle_trial, dict):
            raise ValueError(f"bundle batch does not contain the requested trial: {trial}")
        if (
            not isinstance(bundle_trial.get("requested_outcome"), str)
            or not bundle_trial["requested_outcome"].strip()
        ):
            raise ValueError(f"bundle trial-specific requested outcome is missing for {trial}")

        def source_inventory(rows: object) -> list[tuple[str, str]]:
            if not isinstance(rows, list):
                raise ValueError(f"source inventory is missing for {trial}")
            inventory: list[tuple[str, str]] = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"source inventory is malformed for {trial}")
                role = row.get("role")
                digest = row.get("sha256")
                if not isinstance(role, str) or not isinstance(digest, str):
                    raise ValueError(f"source inventory entry is incomplete for {trial}")
                normalized_digest = digest.casefold().removeprefix("sha256:")
                if len(normalized_digest) != 64 or any(
                    character not in "0123456789abcdef" for character in normalized_digest
                ):
                    raise ValueError(f"source inventory hash is malformed for {trial}")
                inventory.append((role, normalized_digest))
            return inventory

        expected_sources = source_inventory(run_inputs.get("sources"))
        observed_sources = source_inventory(bundle_trial.get("sources"))
        if sorted(expected_sources) != sorted(observed_sources):
            raise ValueError(f"bundle source inventory/content hashes are not bound to {trial}")
    if manifest_row is not None:
        case_path = manifest_row.get("case_path")
        prompt_path = manifest_row.get("prompt_path")
        expected_run_dir = manifest_row.get("run_dir")
        if not all(isinstance(value, str) and value for value in (case_path, prompt_path)):
            raise ValueError(f"benchmark manifest inputs are incomplete for {trial}")
        if expected_run_dir and Path(expected_run_dir).resolve() != trial_dir.resolve():
            raise ValueError(f"run directory is not the manifest case directory for {trial}")
        case_file = Path(case_path if isinstance(case_path, str) else "")
        prompt_file = Path(prompt_path if isinstance(prompt_path, str) else "")
        if not case_file.is_file() or not prompt_file.is_file():
            raise ValueError(f"benchmark manifest input is missing for {trial}")
        if execution.get("manifest_sha256") != hashlib.sha256(case_file.read_bytes()).hexdigest():
            raise ValueError(f"case manifest hash mismatch for {trial}")
        if execution.get("prompt_sha256") != hashlib.sha256(prompt_file.read_bytes()).hexdigest():
            raise ValueError(f"prompt hash mismatch for {trial}")


def _verify_bundle(path: Path) -> tuple[bool, str]:
    verifier = runpy.run_path(str(Path(__file__).with_name("verify_bundle.py")))
    return verifier["verify"](path)


def _adjudication_paths(trial_dir: Path) -> list[Path]:
    """Find the explicit per-case adjudication sidecar convention."""

    candidates = []
    root_record = trial_dir / "adjudication.json"
    if root_record.is_file():
        candidates.append(root_record)
    candidates.extend(
        sorted(path for path in (trial_dir / "adjudications").glob("*.json") if path.is_file())
    )
    return candidates


def _case_adjudications(
    trial_dir: Path,
    *,
    case_id: str,
    trial_id: str,
    campaign_id: str,
    bundle: Path | None,
    result_identity: str | None,
) -> list[dict[str, Any]]:
    """Load optional adjudications and bind them to the verified case artifact."""

    paths = _adjudication_paths(trial_dir)
    if not paths:
        return []
    if bundle is None or result_identity is None:
        raise ValueError(f"adjudication sidecars require a finalized bundle for {case_id}")
    try:
        records = validate_sidecars(read_sidecar(path) for path in paths)
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"invalid adjudication sidecar for {case_id}: {error}") from error
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    snapshots = canonical.get("snapshots", {}) if isinstance(canonical, dict) else {}
    snapshot = snapshots.get(trial_id) if isinstance(snapshots, dict) else None
    if not isinstance(snapshot, dict):
        raise ValueError(f"canonical bundle is missing snapshot for {trial_id}")
    checkpoint_ids = {
        item
        for item in (snapshot.get("checkpoints", []) if isinstance(snapshot, dict) else [])
        if isinstance(item, str)
    }
    if not checkpoint_ids:
        raise ValueError(f"canonical snapshot has no Domain checkpoints for {case_id}")
    domain_records = canonical.get("domain_records", {}) if isinstance(canonical, dict) else {}
    source_identities: set[str] = set()
    batch = canonical.get("batch", {}) if isinstance(canonical, dict) else {}
    trial_record = (
        next(
            (
                item
                for item in batch.get("trials", [])
                if isinstance(item, dict) and item.get("id") == trial_id
            ),
            None,
        )
        if isinstance(batch, dict)
        else None
    )
    for source in trial_record.get("sources", []) if isinstance(trial_record, dict) else []:
        if not isinstance(source, dict):
            continue
        for key in ("id", "sha256", "projection_hash"):
            if isinstance(source.get(key), str):
                source_identities.add(source[key])
    validated: list[dict[str, Any]] = []
    for record in records:
        if record.case_identity != case_id:
            raise ValueError(f"adjudication case identity mismatch for {case_id}")
        if record.run_identity != campaign_id:
            raise ValueError(f"adjudication run identity mismatch for {case_id}")
        if record.result_identity != result_identity:
            raise ValueError(f"adjudication Result identity mismatch for {case_id}")
        if record.checkpoint_identity not in checkpoint_ids:
            raise ValueError(f"adjudication checkpoint identity mismatch for {case_id}")
        checkpoint = (
            next(
                (
                    item
                    for item in domain_records.values()
                    if isinstance(item, dict) and item.get("identity") == record.checkpoint_identity
                ),
                None,
            )
            if isinstance(domain_records, dict)
            else None
        )
        if not isinstance(checkpoint, dict) or checkpoint.get("trial_id") != trial_id:
            raise ValueError(f"adjudication checkpoint record is unavailable for {case_id}")
        if checkpoint.get("domain_id") != record.domain_identity:
            raise ValueError(f"adjudication domain identity mismatch for {case_id}")
        question_ids = {
            answer.get("question_id")
            for answer in checkpoint.get("answers", [])
            if isinstance(answer, dict) and isinstance(answer.get("question_id"), str)
        }
        if record.question_identity not in question_ids:
            raise ValueError(f"adjudication question identity mismatch for {case_id}")
        if not _labels_match(record.model_label, checkpoint.get("judgment")):
            raise ValueError(f"adjudication model label mismatch for {case_id}")
        if not set(record.source_identities) <= source_identities:
            raise ValueError(f"adjudication source identity is outside the case for {case_id}")
        validated.append(record.model_dump(mode="json", by_alias=True))
    return validated


def collect(
    reference: Path,
    run_root: Path,
    outcome: str,
    *,
    legacy_read_only: bool = False,
    manifest: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    trials = _catalog_trials(reference, outcome)
    gold = _gold(reference, outcome)
    manifest_rows = _benchmark_rows(manifest)
    cases: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    for trial in trials:
        trial_dir = run_root / trial
        campaign_id = run_root.parent.name
        identity = {
            "campaign_id": campaign_id,
            "case_id": f"{campaign_id}-{_normalise(outcome)}-{_normalise(trial)}",
            "trial_id": trial,
            "outcome": outcome,
        }
        execution = (
            _execution(trial_dir, identity, legacy_read_only=legacy_read_only)
            if trial_dir.is_dir()
            else None
        )
        manifest_row = manifest_rows.get((_normalise(outcome), _normalise(trial)))
        if manifest is not None and manifest_row is None:
            raise ValueError(f"benchmark manifest is missing eligible case: {outcome}/{trial}")
        if execution is not None:
            historical_execution = _is_historical_execution(execution)
            bundle = (
                _bundle(
                    trial_dir,
                    None if historical_execution else execution,
                    legacy_read_only=legacy_read_only or historical_execution,
                )
                if trial_dir.is_dir()
                else None
            )
            if not historical_execution:
                _validate_execution_inputs(
                    trial_dir,
                    execution,
                    trial=trial,
                    outcome=outcome,
                    manifest_row=manifest_row,
                    bundle=bundle,
                )
        else:
            historical_execution = False
            bundle = (
                _bundle(trial_dir, execution, legacy_read_only=legacy_read_only)
                if trial_dir.is_dir()
                else None
            )
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
        elif execution is None or historical_execution:
            verified, verification_message = _verify_bundle(bundle)
            if not verified:
                raise ValueError(f"bundle verification failed: {verification_message}")
            observed, observed_overall, proposal, result_identity = _read_bundle(
                bundle, expected_trial=trial, expected_outcome=outcome
            )
            completion = "historical_unqualified" if historical_execution else "legacy_finalized"
        elif execution.get("state") != "succeeded":
            observed = {}
            observed_overall = None
            proposal = {}
            result_identity = None
            completion = "interrupted" if execution else "finalized"
        else:
            verified, verification_message = _verify_bundle(bundle)
            if not verified:
                raise ValueError(f"bundle verification failed: {verification_message}")
            observed, observed_overall, proposal, result_identity = _read_bundle(
                bundle, expected_trial=trial, expected_outcome=outcome
            )
            completion = "finalized"
        case_id = identity["case_id"]
        case_adjudications = (
            _case_adjudications(
                trial_dir,
                case_id=case_id,
                trial_id=trial,
                campaign_id=campaign_id,
                bundle=bundle,
                result_identity=result_identity,
            )
            if trial_dir.is_dir()
            else []
        )
        adjudications.extend(case_adjudications)
        cases.append(
            {
                "case_id": case_id,
                "trial_id": trial,
                "outcome": outcome,
                "scope": "eligible",
                "completion": completion,
                "expected": {key: expected[key] for key, _ in DOMAINS},
                "observed": observed,
                "failure_causes": (
                    {}
                    if execution is None or execution.get("state") == "succeeded"
                    else {
                        "operational_state": execution.get("state"),
                        "child_exit_code": execution.get("child_exit_code"),
                        "recovery_required": True,
                    }
                ),
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
                "execution": execution,
                "operational_state": execution.get("state") if execution else "legacy",
                "operational_failure": (
                    {
                        "child_exit_code": execution.get("child_exit_code"),
                        "state": execution.get("state"),
                    }
                    if execution and execution.get("state") != "succeeded"
                    else None
                ),
                "verification": (
                    {
                        "verified": True,
                        "mode": (
                            "historical-unqualified" if historical_execution else "authoritative"
                        ),
                    }
                    if bundle and execution
                    else ({"verified": True, "mode": "legacy-read-only"} if bundle else None)
                ),
                "proposal_correction_count": sum(
                    phase.get("phase_kind") == "proposal_correction" for phase in phases
                ),
                "adjudication_count": len(case_adjudications),
            }
        )
    sidecar = {
        "schema": SCHEMA,
        "cases": cases,
        "adjudications": sorted(
            adjudications,
            key=lambda item: str(item.get("identity", "")),
        ),
    }
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
    parser.add_argument(
        "--manifest",
        type=Path,
        help="frozen benchmark manifest used to bind case and prompt inputs",
    )
    parser.add_argument(
        "--legacy-read-only",
        action="store_true",
        help="read historical runs without execution.json; never infer authority from them",
    )
    args = parser.parse_args()
    sidecar, details = collect(
        args.reference,
        args.run_root,
        args.outcome,
        legacy_read_only=args.legacy_read_only,
        manifest=args.manifest,
    )
    for path, value in ((args.output, sidecar), (args.details_output, details)):
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    print(f"Collected {len(sidecar['cases'])} eligible {args.outcome} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
