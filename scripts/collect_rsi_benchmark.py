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

from benchmark_contract import (
    artifact_manifest_identity,
    validate_execution_index_binding,
    validate_replacement_case,
)
from score_trial_benchmark import _result_dimensions, _result_mismatches, _safe_mismatch_details

from rob2_kit.application._state import _identity as _canonical_identity
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


def _benchmark_rows(
    path: Path | None,
) -> tuple[str | None, str | None, dict[tuple[str, str], dict[str, Any]]]:
    if path is None:
        return None, None, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"benchmark manifest is unreadable: {path}") from error
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict):
        rows = payload.get("cases")
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
    schema = payload.get("schema") if isinstance(payload, dict) else None
    campaign_id = payload.get("campaign_id") if isinstance(payload, dict) else None
    if campaign_id is not None and (
        not isinstance(campaign_id, str) or not campaign_id.strip()
    ):
        raise ValueError("benchmark manifest campaign_id is malformed")
    if isinstance(campaign_id, str) and any(
        row.get("campaign_id", campaign_id) != campaign_id for row in indexed.values()
    ):
        raise ValueError("benchmark manifest case campaign_id differs from its frozen campaign")
    return schema if isinstance(schema, str) else None, campaign_id, indexed


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
    if isinstance(execution.get("attempts"), list):
        selection = execution.get("selection_policy")
        selected_id = selection.get("selected_attempt_id") if isinstance(selection, dict) else None
        if not isinstance(selected_id, str) or artifact.get("attempt_id") != selected_id:
            raise ValueError(f"bundle is not bound to the selected attempt: {trial_dir}")
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


def _completion_for_state(state: object) -> str:
    if state == "succeeded":
        return "finalized"
    if state in {"failed_infrastructure", "scientific_failed", "expired"}:
        return "failed"
    if state == "cancelled":
        return "interrupted"
    if state in {"queued", "running", "resumable", "waiting_for_user"}:
        return "incomplete"
    return "unknown"


def _execution_draws(
    execution: dict[str, Any], *, observed: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    attempts = execution.get("attempts")
    selection = execution.get("selection_policy")
    selected_id = selection.get("selected_attempt_id") if isinstance(selection, dict) else None
    if not isinstance(attempts, list):
        return [], None
    phases = execution.get("phases")
    phase_rows = phases if isinstance(phases, list) else []
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            continue
        if attempt_id not in grouped:
            order.append(attempt_id)
        phase = attempt.get("phase")
        phase_record = next(
            (
                item
                for item in phase_rows
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("phase") == phase
            ),
            {},
        )
        is_selected = attempt_id == selected_id
        draw: dict[str, Any] = {
            "attempt_id": attempt_id,
            "observed": dict(observed or {}) if is_selected else {},
            "completion": _completion_for_state(attempt.get("state")),
            "status": attempt.get("state", "unknown"),
            "selected": is_selected,
        }
        if isinstance(phase_record, dict) and isinstance(phase_record.get("exit_code"), int):
            draw["exit_code"] = phase_record["exit_code"]
        grouped[attempt_id] = draw
    for attempt_id, draw in grouped.items():
        failures = []
        for phase_record in phase_rows:
            if not isinstance(phase_record, dict) or phase_record.get("attempt_id") != attempt_id:
                continue
            exit_code = phase_record.get("exit_code")
            state = phase_record.get("state")
            if not (
                (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0)
                or state in {"failed_infrastructure", "expired", "cancelled"}
            ):
                continue
            event = {
                "phase": phase_record.get("phase"),
                "state": state,
            }
            if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                event["exit_code"] = exit_code
            failures.append(event)
        if failures:
            draw["phase_failures"] = failures
    draws = [grouped[attempt_id] for attempt_id in order]
    return draws, selected_id if isinstance(selected_id, str) else None


def _launcher_draws(
    index_path: Path, row: dict[str, Any], *, attempt_number: int
) -> list[dict[str, Any]]:
    key = (_normalise(str(row.get("outcome", ""))), _normalise(str(row.get("trial", ""))))
    run_dir = row.get("run_dir")
    expected_index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    try:
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"benchmark index is invalid: {index_path}") from error
    is_fresh_index = (
        isinstance(index_payload, dict)
        and index_payload.get("schema") == "rob2-kit.fresh-benchmark-index.v1"
    )
    matched: list[dict[str, Any]] = []
    for summary_path in sorted(index_path.parent.glob("phase-*-launcher-summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"launcher summary is invalid: {summary_path}") from error
        if not isinstance(summary, list):
            raise ValueError(f"launcher summary must be a list: {summary_path}")
        for result in summary:
            if not isinstance(result, dict):
                raise ValueError(f"launcher result is malformed: {summary_path}")
            result_key = (
                _normalise(str(result.get("outcome", ""))),
                _normalise(str(result.get("trial", ""))),
            )
            if result_key != key:
                continue
            if is_fresh_index and result.get("benchmark_index_sha256") != expected_index_sha256:
                raise ValueError(f"launcher summary index hash mismatch: {summary_path}")
            if isinstance(run_dir, str) and result.get("run_dir"):
                if Path(str(result["run_dir"])).resolve() != Path(run_dir).resolve():
                    continue
            phase = result.get("phase")
            exit_code = result.get("exit_code")
            if isinstance(phase, bool) or not isinstance(phase, int) or phase < 1:
                raise ValueError(f"launcher result phase is malformed: {summary_path}")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise ValueError(f"launcher result exit code is malformed: {summary_path}")
            diagnosis = result.get("diagnosis")
            if exit_code == 0 or not isinstance(diagnosis, dict):
                continue
            code = (
                diagnosis.get("code")
                if isinstance(diagnosis, dict) and isinstance(diagnosis.get("code"), str)
                else "launcher_exit"
            )
            invocation = result.get("launcher_invocation_id")
            if not isinstance(invocation, str) or not invocation:
                invocation = hashlib.sha256(
                    (str(summary_path) + json.dumps(result, sort_keys=True)).encode()
                ).hexdigest()[:16]
            matched.append(
                {
                    "attempt_id": f"launcher-{invocation}-attempt-{attempt_number}-phase-{phase}",
                    "observed": {},
                    "completion": "failed",
                    "status": code,
                    "selected": False,
                    "phase": phase,
                    "exit_code": exit_code,
                }
            )
    if matched:
        matched[-1]["selected"] = True
    return matched


def _lineage_draws(
    *,
    manifest_path: Path,
    manifest_row: dict[str, Any],
    identity: dict[str, str],
    selected_observed: dict[str, str],
    selected_result: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    lineage = manifest_row.get("attempt_history")
    if not isinstance(lineage, list) or not lineage:
        return [], None
    if any(not isinstance(item, dict) for item in lineage):
        raise ValueError("attempt lineage entry is malformed")
    if sum(item.get("selected") is True for item in lineage) != 1:
        raise ValueError("attempt lineage must select exactly one retained run")
    if len(lineage) != 2 or lineage[-1]["selected"] is not True:
        raise ValueError(
            "replacement attempt lineage must retain original then selected replacement"
        )
    original_entry, replacement_entry = lineage
    if not isinstance(original_entry, dict) or not isinstance(replacement_entry, dict):
        raise ValueError("attempt lineage entry is malformed")
    original_index_path = Path(str(original_entry.get("index"))).resolve(strict=True)
    replacement_index_path = Path(str(replacement_entry.get("index"))).resolve(strict=True)
    original_index = json.loads(original_index_path.read_text(encoding="utf-8"))
    replacement_index = json.loads(replacement_index_path.read_text(encoding="utf-8"))
    if not isinstance(original_index, dict) or not isinstance(replacement_index, dict):
        raise ValueError("attempt lineage source index is malformed")
    case_key = (_normalise(identity["outcome"]), _normalise(identity["trial_id"]))
    original_row, replacement_row = validate_replacement_case(
        original_index_path,
        original_index,
        replacement_index_path,
        replacement_index,
        case_key,
        require_success=False,
    )
    if (
        original_entry.get("run_dir") != original_row.get("run_dir")
        or replacement_entry.get("run_dir") != replacement_row.get("run_dir")
    ):
        raise ValueError("attempt lineage run directories differ from their frozen indexes")
    draws: list[dict[str, Any]] = []
    selected_id: str | None = None
    for entry in lineage:
        if not isinstance(entry, dict):
            raise ValueError("attempt lineage entry is malformed")
        source_index_value = entry.get("index")
        source_run_value = entry.get("run_dir")
        expected_hash = entry.get("index_sha256")
        if not isinstance(source_index_value, str) or not isinstance(source_run_value, str):
            raise ValueError("attempt lineage source is incomplete")
        source_index = Path(source_index_value).resolve(strict=True)
        if (
            not isinstance(expected_hash, str)
            or hashlib.sha256(source_index.read_bytes()).hexdigest() != expected_hash
        ):
            raise ValueError("attempt lineage source index hash mismatch")
        source_payload = json.loads(source_index.read_text(encoding="utf-8"))
        if not isinstance(source_payload, dict):
            raise ValueError("attempt lineage source index is malformed")
        source_rows = source_payload.get("cases")
        case_key = (_normalise(identity["outcome"]), _normalise(identity["trial_id"]))
        source_matches = [
            item
            for item in source_rows
            if isinstance(item, dict)
            and _normalise(str(item.get("outcome", ""))) == case_key[0]
            and _normalise(str(item.get("trial", ""))) == case_key[1]
        ] if isinstance(source_rows, list) else []
        if len(source_matches) != 1 or source_matches[0].get("run_dir") != source_run_value:
            raise ValueError("attempt lineage case/run binding mismatch")
        source_row = source_matches[0]
        attempt_number = source_row.get("attempt", source_payload.get("attempt", 1))
        if isinstance(attempt_number, str) and attempt_number.isdecimal():
            attempt_number = int(attempt_number)
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
            raise ValueError("attempt lineage attempt number is malformed")
        source_run = Path(source_run_value)
        source_execution_path = source_run / "execution.json"
        if source_execution_path.is_file():
            source_execution = _execution(source_run, identity, legacy_read_only=False)
            if source_execution is None:
                raise ValueError("attempt lineage execution record is unavailable")
            source_bundle = _bundle(source_run, source_execution, legacy_read_only=False)
            if source_execution.get("state") == "succeeded":
                _validate_execution_inputs(
                    source_run,
                    source_execution,
                    trial=identity["trial_id"],
                    outcome=identity["outcome"],
                    manifest_row=source_row,
                    bundle=source_bundle,
                )
            source_draws, local_selected_id = _execution_draws(
                source_execution,
                observed=(
                    selected_observed
                    if entry.get("selected") is True and selected_result
                    else None
                ),
            )
            for draw in source_draws:
                draw["selected"] = entry.get("selected") is True and draw.get("selected") is True
            draws.extend(source_draws)
            if entry.get("selected") is True:
                selected_id = local_selected_id
            # Launcher failures before a later resumable phase are separate
            # operational draws and must remain in the denominator.
            launcher_failures = _launcher_draws(
                source_index, source_row, attempt_number=attempt_number
            )
            for draw in launcher_failures:
                draw["selected"] = False
            draws.extend(launcher_failures)
        else:
            source_draws = _launcher_draws(source_index, source_row, attempt_number=attempt_number)
            for draw in source_draws:
                draw["selected"] = entry.get("selected") is True and draw.get("selected") is True
            draws.extend(source_draws)
            if entry.get("selected") is True:
                selected_draw = next(
                    (draw for draw in source_draws if draw.get("selected") is True), None
                )
                if isinstance(selected_draw, dict):
                    selected_id = selected_draw.get("attempt_id")
    return draws, selected_id


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
    if expected_outcome is not None:
        requested_outcome = (
            batch_trial.get("requested_outcome") if isinstance(batch_trial, dict) else None
        )
        if not isinstance(requested_outcome, str) or not requested_outcome.strip():
            raise ValueError(
                f"bundle trial-specific requested outcome is missing for {trial_id}; "
                f"benchmark concept was {expected_outcome}"
            )
        if _normalise(requested_outcome) != _normalise(expected_outcome):
            raise ValueError(
                f"bundle requested outcome mismatch for {trial_id}: expected {expected_outcome!r}, "
                f"observed {requested_outcome!r}"
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
        [
            item
            for item in results
            if isinstance(item, dict)
            and _normalise(str(item.get("trial_id", ""))) == _normalise(str(trial_id))
        ]
        if isinstance(results, list)
        else []
    )
    result_identity = snapshot.get("result_identity")
    if isinstance(result_identity, str):
        trial_results = [
            item for item in trial_results if _canonical_identity(item) == result_identity
        ]
    if len(trial_results) != 1:
        raise ValueError(
            "bundle approved Result identity is missing or ambiguous for "
            f"{trial_id}: {path}"
        )
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
    trial_dir: Path,
    identity: dict[str, str],
    *,
    legacy_read_only: bool,
    allow_historical_missing_attempts: bool = False,
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
    if "attempts" not in record:
        if not allow_historical_missing_attempts:
            raise ValueError(f"execution attempt history is missing: {path}")
        historical = dict(record)
        historical["compatibility"] = {
            "mode": HISTORICAL_EXECUTION_COMPATIBILITY,
            "schema": EXECUTION_SCHEMA,
            "reason": "immutable attempt identity was not recorded",
        }
        return historical
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"execution attempt history is malformed: {path}")
    attempt_ids: set[str] = set()
    attempt_phases: set[tuple[str, int]] = set()
    for index, attempt in enumerate(attempts):
        if (
            not isinstance(attempt, dict)
            or not isinstance(attempt.get("attempt_id"), str)
            or not attempt["attempt_id"].strip()
            or not isinstance(attempt.get("phase"), int)
        ):
            raise ValueError(f"execution attempt {index} is missing an immutable identity: {path}")
        attempt_id = attempt["attempt_id"]
        phase_key = (attempt_id, attempt["phase"])
        if phase_key in attempt_phases:
            raise ValueError(f"execution repeats an attempt phase: {path}")
        attempt_phases.add(phase_key)
        attempt_ids.add(attempt_id)
    policy = record.get("selected_attempt_rule")
    if not isinstance(policy, str) or not policy.strip():
        raise ValueError(f"execution selection policy is missing: {path}")
    selection = record.get("selection_policy")
    selected_attempt_id = (
        selection.get("selected_attempt_id") if isinstance(selection, dict) else None
    )
    if selected_attempt_id not in attempt_ids:
        raise ValueError(f"execution selected attempt is missing or inconsistent: {path}")
    if selection.get("rule") != policy:
        raise ValueError(f"execution selection rule differs from its predeclared policy: {path}")
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
        or _normalise(str(run_inputs.get("requested_outcome", ""))) != _normalise(outcome)
    ):
        raise ValueError(f"execution input identity mismatch for {trial}")
    expected_input_hash = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if execution.get("run_input_sha256") != expected_input_hash:
        raise ValueError(f"run-input hash mismatch for {trial}")
    if execution.get("schema") == EXECUTION_SCHEMA:
        phases = execution.get("phases")
        phase_hashes = execution.get("prompt_sha256_by_phase")
        if not isinstance(phases, list) or not phases or not isinstance(phase_hashes, dict):
            raise ValueError(f"phase prompt provenance is missing for {trial}")
        seen_phases: set[int] = set()
        for phase in phases:
            phase_number = phase.get("phase") if isinstance(phase, dict) else None
            if not isinstance(phase_number, int) or phase_number in seen_phases:
                raise ValueError(f"phase prompt provenance is malformed for {trial}")
            seen_phases.add(phase_number)
            phase_hash = phase.get("prompt_sha256")
            if (
                not isinstance(phase_hash, str)
                or not phase_hash
                or phase_hashes.get(str(phase_number)) != phase_hash
            ):
                raise ValueError(f"phase {phase_number} prompt hash is inconsistent for {trial}")
            metadata_path = trial_dir / f"phase-{phase_number}.meta.json"
            try:
                phase_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"phase {phase_number} metadata is missing for {trial}") from error
            prompt_path = (
                phase_metadata.get("prompt_file") if isinstance(phase_metadata, dict) else None
            )
            if (
                not isinstance(phase_metadata, dict)
                or phase_metadata.get("prompt_sha256") != phase_hash
                or not isinstance(prompt_path, str)
                or not Path(prompt_path).is_file()
                or hashlib.sha256(Path(prompt_path).read_bytes()).hexdigest() != phase_hash
            ):
                raise ValueError(f"phase {phase_number} prompt binding mismatch for {trial}")
    manifest_case: dict[str, Any] = {}
    if manifest_row is not None:
        case_path = manifest_row.get("case_path", manifest_row.get("case"))
        prompt_path = manifest_row.get("prompt_path", manifest_row.get("prompt"))
        expected_run_dir = manifest_row.get("run_dir")
        if not isinstance(case_path, str) or not case_path:
            raise ValueError(f"benchmark manifest inputs are incomplete for {trial}")
        if not isinstance(prompt_path, str) or not prompt_path:
            raise ValueError(f"benchmark manifest inputs are incomplete for {trial}")
        if expected_run_dir and Path(expected_run_dir).resolve() != trial_dir.resolve():
            raise ValueError(f"run directory is not the manifest case directory for {trial}")
        case_file = Path(case_path)
        prompt_file = Path(prompt_path)
        if not case_file.is_file() or not prompt_file.is_file():
            raise ValueError(f"benchmark manifest input is missing for {trial}")
        if execution.get("manifest_sha256") != hashlib.sha256(case_file.read_bytes()).hexdigest():
            raise ValueError(f"case manifest hash mismatch for {trial}")
        if execution.get("prompt_sha256") != hashlib.sha256(prompt_file.read_bytes()).hexdigest():
            raise ValueError(f"prompt hash mismatch for {trial}")
        try:
            manifest_case = json.loads(case_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"benchmark case manifest is invalid for {trial}") from error
        if not isinstance(manifest_case, dict):
            raise ValueError(f"benchmark case manifest is malformed for {trial}")

    expected_result = (
        manifest_row.get("expected_result")
        if isinstance(manifest_row, dict) and isinstance(manifest_row.get("expected_result"), dict)
        else manifest_case.get("expected_result")
    )
    unresolved_scope = (
        manifest_row.get("scope_unresolved")
        if isinstance(manifest_row, dict)
        and isinstance(manifest_row.get("scope_unresolved"), str)
        else manifest_case.get("scope_unresolved", run_inputs.get("scope_unresolved"))
    )
    if isinstance(unresolved_scope, str):
        unresolved_scope = unresolved_scope.strip() or None
    if expected_result is not None and unresolved_scope is not None:
        raise ValueError(f"case has both frozen and unresolved Result scope for {trial}")
    if expected_result is not None and run_inputs.get("expected_result") != expected_result:
        raise ValueError(f"frozen expected Result differs from launch inputs for {trial}")
    if unresolved_scope is not None and run_inputs.get("scope_unresolved") != unresolved_scope:
        raise ValueError(f"frozen scope_unresolved reason differs from launch inputs for {trial}")
    scope_status = execution.get("scope_status")
    if scope_status is not None:
        expected_status = "frozen" if expected_result is not None else "scope_unresolved"
        if scope_status != expected_status:
            raise ValueError(f"execution Result scope status mismatch for {trial}")
        if scope_status == "frozen" and execution.get("expected_result_sha256") != hashlib.sha256(
            json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest():
            raise ValueError(f"execution expected Result hash mismatch for {trial}")
        if (
            scope_status == "scope_unresolved"
            and execution.get("scope_unresolved") != unresolved_scope
        ):
            raise ValueError(f"execution scope_unresolved reason mismatch for {trial}")
    if expected_result is not None and bundle is None:
        raise ValueError(f"cannot qualify a run without its expected Result artifact: {trial}")

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
        if _normalise(bundle_trial["requested_outcome"]) != _normalise(outcome):
            raise ValueError(
                f"bundle requested outcome mismatch for {trial}: expected {outcome!r}, "
                f"observed {bundle_trial['requested_outcome']!r}"
            )

        if expected_result is not None:
            snapshots = canonical.get("snapshots") if isinstance(canonical, dict) else None
            snapshot = (
                next(
                    (
                        item
                        for snapshot_trial, item in snapshots.items()
                        if _normalise(str(snapshot_trial)) == _normalise(trial)
                    ),
                    None,
                )
                if isinstance(snapshots, dict)
                else None
            )
            snapshot_identity = (
                snapshot.get("result_identity") if isinstance(snapshot, dict) else None
            )
            proposal = canonical.get("proposal") if isinstance(canonical, dict) else None
            results = (
                proposal.get("payload", {}).get("results") if isinstance(proposal, dict) else None
            )
            matching = (
                [
                    item
                    for item in results
                    if isinstance(item, dict)
                    and _normalise(str(item.get("trial_id", ""))) == _normalise(trial)
                    and _canonical_identity(item) == snapshot_identity
                ]
                if isinstance(results, list) and isinstance(snapshot_identity, str)
                else []
            )
            if len(matching) != 1:
                raise ValueError(f"approved Result identity is missing or ambiguous for {trial}")
            mismatches = _result_mismatches(
                expected_result, _result_dimensions(matching[0], trial), trial
            )
            if mismatches:
                raise ValueError(
                    "expected Result scope mismatch: "
                    + json.dumps(_safe_mismatch_details(mismatches), sort_keys=True)
                )
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
    manifest_schema, frozen_campaign_id, manifest_rows = _benchmark_rows(manifest)
    cases: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    for trial in trials:
        manifest_row = manifest_rows.get((_normalise(outcome), _normalise(trial)))
        if manifest is not None and manifest_row is None:
            raise ValueError(f"benchmark manifest is missing eligible case: {outcome}/{trial}")
        run_dir_value = manifest_row.get("run_dir") if manifest_row is not None else None
        if isinstance(run_dir_value, str) and run_dir_value.strip():
            selected_run_dir = Path(run_dir_value)
            trial_dir = (
                selected_run_dir.resolve()
                if selected_run_dir.is_absolute()
                else (manifest.resolve().parent / selected_run_dir).resolve()
            )
        else:
            trial_dir = run_root / trial
        inferred_campaign_id = (
            run_root.resolve().parents[1].name
            if len(run_root.resolve().parents) > 1
            else run_root.resolve().parent.name
        )
        campaign_id = frozen_campaign_id or inferred_campaign_id
        if manifest_row is not None:
            row_campaign_id = manifest_row.get("campaign_id")
            if row_campaign_id is not None and row_campaign_id != campaign_id:
                raise ValueError(f"benchmark case campaign_id differs from campaign for {trial}")
            run_inputs_path = trial_dir / "run-inputs.json"
            if run_inputs_path.is_file():
                try:
                    run_inputs_campaign = json.loads(
                        run_inputs_path.read_text(encoding="utf-8")
                    ).get("campaign_id")
                except (OSError, json.JSONDecodeError, AttributeError):
                    run_inputs_campaign = None
                if run_inputs_campaign is not None and run_inputs_campaign != campaign_id:
                    raise ValueError(f"run inputs campaign_id differs from manifest for {trial}")
        identity = {
            "campaign_id": campaign_id,
            "case_id": f"{campaign_id}-{_normalise(outcome)}-{_normalise(trial)}",
            "trial_id": trial,
            "outcome": outcome,
        }
        execution = (
            _execution(
                trial_dir,
                identity,
                legacy_read_only=legacy_read_only,
                allow_historical_missing_attempts=(
                    manifest_schema == "rob2-kit.benchmark-manifest.v2"
                ),
            )
            if trial_dir.is_dir()
            and ((trial_dir / "execution.json").is_file() or manifest_row is None)
            else None
        )
        if execution is not None:
            if (
                manifest is not None
                and manifest_row is not None
                and manifest_schema == "rob2-kit.fresh-benchmark-index.v1"
                and not isinstance(manifest_row.get("attempt_history"), list)
            ):
                validate_execution_index_binding(manifest.resolve(strict=True), manifest_row, execution)
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
            if not historical_execution and execution.get("state") == "succeeded":
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
                if trial_dir.is_dir() and manifest_row is None
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
            completion = _completion_for_state(execution.get("state")) if execution else (
                "incomplete" if phases else "unknown"
            )
        elif execution is None or historical_execution:
            verified, verification_message = _verify_bundle(bundle)
            if not verified:
                raise ValueError(f"bundle verification failed: {verification_message}")
            observed, observed_overall, proposal, result_identity = _read_bundle(
                bundle, expected_trial=trial, expected_outcome=outcome
            )
            completion = "finalized"
        elif execution.get("state") != "succeeded":
            observed = {}
            observed_overall = None
            proposal = {}
            result_identity = None
            completion = _completion_for_state(execution.get("state"))
        else:
            verified, verification_message = _verify_bundle(bundle)
            if not verified:
                raise ValueError(f"bundle verification failed: {verification_message}")
            observed, observed_overall, proposal, result_identity = _read_bundle(
                bundle, expected_trial=trial, expected_outcome=outcome
            )
            completion = "finalized"
        selected_observed = observed if completion == "finalized" else {}
        if manifest is not None and manifest_row is not None:
            attempt_draws, selected_attempt_id = _lineage_draws(
                manifest_path=manifest,
                manifest_row=manifest_row,
                identity=identity,
                selected_observed=selected_observed,
                selected_result=bool(selected_observed),
            )
            if not attempt_draws and execution is not None:
                attempt_draws, selected_attempt_id = _execution_draws(
                    execution, observed=selected_observed
                )
            if not attempt_draws and execution is None:
                attempt_number = manifest_row.get("attempt", 1)
                if isinstance(attempt_number, str) and attempt_number.isdecimal():
                    attempt_number = int(attempt_number)
                if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
                    raise ValueError(f"benchmark attempt number is malformed for {trial}")
                attempt_draws = _launcher_draws(
                    manifest, manifest_row, attempt_number=attempt_number
                )
                selected = next((item for item in attempt_draws if item.get("selected")), None)
                selected_attempt_id = (
                    selected.get("attempt_id") if isinstance(selected, dict) else None
                )
            elif execution is not None:
                attempt_number = manifest_row.get("attempt", 1)
                if isinstance(attempt_number, str) and attempt_number.isdecimal():
                    attempt_number = int(attempt_number)
                if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
                    raise ValueError(f"benchmark attempt number is malformed for {trial}")
                launcher_failures = _launcher_draws(
                    manifest, manifest_row, attempt_number=attempt_number
                )
                for draw in launcher_failures:
                    draw["selected"] = False
                attempt_draws.extend(launcher_failures)
        elif execution is not None:
            attempt_draws, selected_attempt_id = _execution_draws(
                execution, observed=selected_observed
            )
            if manifest is not None and manifest_row is not None:
                attempt_number = manifest_row.get("attempt", 1)
                if isinstance(attempt_number, str) and attempt_number.isdecimal():
                    attempt_number = int(attempt_number)
                if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
                    raise ValueError(f"benchmark attempt number is malformed for {trial}")
                launcher_failures = _launcher_draws(
                    manifest, manifest_row, attempt_number=attempt_number
                )
                for draw in launcher_failures:
                    draw["selected"] = False
                attempt_draws.extend(launcher_failures)
        else:
            attempt_draws, selected_attempt_id = [], None
        if execution is None and attempt_draws:
            selected_draw = next(
                (item for item in attempt_draws if item.get("selected") is True), None
            )
            if isinstance(selected_draw, dict) and selected_draw.get("completion") in {
                "failed",
                "incomplete",
                "interrupted",
            }:
                completion = str(selected_draw["completion"])
        scope_status = (
            "scope_uncertain"
            if manifest_row is not None
            and (
                isinstance(manifest_row.get("scope_unresolved"), str)
                or not isinstance(manifest_row.get("expected_result"), dict)
            )
            else "eligible"
        )
        selected_draw = next(
            (item for item in attempt_draws if item.get("selected") is True), None
        )
        operational_state = (
            execution.get("state")
            if execution is not None
            else selected_draw.get("status", "legacy")
            if isinstance(selected_draw, dict)
            else "unlaunched"
            if manifest_row is not None
            else "legacy"
        )
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
                "scope": scope_status,
                "completion": completion,
                "expected": {key: expected[key] for key, _ in DOMAINS},
                "observed": observed,
                "attempts": attempt_draws if attempt_draws else None,
                "selected_attempt_id": selected_attempt_id,
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
                "execution": execution,
                "attempts": attempt_draws,
                "selected_attempt_id": selected_attempt_id,
                "launcher_draws": (
                    attempt_draws
                    if execution is None and attempt_draws
                    else []
                ),
                "operational_state": operational_state,
                "scope_status": execution.get("scope_status") if execution else None,
                "scope_unresolved": execution.get("scope_unresolved") if execution else None,
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
