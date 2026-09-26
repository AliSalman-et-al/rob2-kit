#!/usr/bin/env python3
"""Normalize retained development-comparison runner records without labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

NORMALIZATION_SCHEMA = "rob2-kit.development-comparison-normalization.v1"
_LABELS = {"low", "some_concerns", "high"}


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_sha256(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _canonical_identity(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return _sha256(payload)


def _same_identity(left: Any, right: Any) -> bool:
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and left.removeprefix("sha256:") == right.removeprefix("sha256:")
    )


def _expected_field(expected: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in expected:
            return expected[name]
    return None


def _contains_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def _same_scope_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return " ".join(actual.casefold().split()) == " ".join(expected.casefold().split())
    if isinstance(expected, str) and isinstance(actual, dict):
        description = actual.get("description")
        return isinstance(description, str) and _same_scope_value(description, expected)
    return actual == expected


def _comparison_group_mapping(actual: Any, expected: Any) -> dict[str, str] | None:
    if (
        not isinstance(actual, list)
        or not isinstance(expected, list)
        or len(actual) != len(expected)
    ):
        return None
    mapping: dict[str, str] = {}
    actual_ids: set[str] = set()
    for actual_group, expected_group in zip(actual, expected, strict=True):
        if not isinstance(actual_group, dict) or not isinstance(expected_group, dict):
            return None
        actual_id, expected_id = actual_group.get("id"), expected_group.get("id")
        if (
            not isinstance(actual_id, str)
            or not isinstance(expected_id, str)
            or actual_id in actual_ids
            or not _same_scope_value(
                actual_group.get("assignment"), expected_group.get("assignment")
            )
        ):
            return None
        actual_ids.add(actual_id)
        mapping[expected_id] = actual_id
    return mapping


def _matches_expected_result(result: dict[str, Any], expected: Any, outcome_id: str) -> bool:
    if not isinstance(expected, dict):
        return False
    target = result.get("target")
    reported = result.get("reported")
    if not isinstance(target, dict) or not isinstance(reported, dict):
        return False
    endpoint = expected.get("endpoint")
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    expected_comparison = _expected_field(expected, "comparison", "comparison_groups")
    group_mapping = _comparison_group_mapping(target.get("comparison_groups"), expected_comparison)
    expected_dimensions = (
        (
            reported.get("endpoint", {}).get("definition")
            if isinstance(reported.get("endpoint"), dict)
            else None,
            _expected_field(expected, "endpoint_definition", "definition")
            or endpoint.get("definition"),
        ),
        (
            target.get("intended_analysis_population"),
            _expected_field(expected, "population", "intended_analysis_population"),
        ),
    )
    expected_reported = expected.get("reported_scope")
    expected_trial = _expected_field(expected, "trial", "trial_id")
    expected_reported = (
        json.loads(json.dumps(expected_reported)) if isinstance(expected_reported, dict) else None
    )
    if isinstance(expected_reported, dict) and isinstance(
        expected_reported.get("group_values"), list
    ):
        if group_mapping is not None:
            for row in expected_reported["group_values"]:
                if isinstance(row, dict) and row.get("group_id") in group_mapping:
                    row["group_id"] = group_mapping[row["group_id"]]
    window_dimensions = expected.get(
        "window", expected.get("window_or_cutoff", expected.get("cutoff"))
    )
    if window_dimensions is None:
        window_dimensions = expected.get("time_point_or_window")
    return (
        expected_trial == result.get("trial_id")
        and result.get("requested_outcome") == outcome_id
        and group_mapping is not None
        and all(
            value is not None and _same_scope_value(actual, value)
            for actual, value in expected_dimensions
        )
        and window_dimensions is not None
        and _same_scope_value(target.get("time_point_or_window"), window_dimensions)
        and isinstance(expected_reported, dict)
        and _contains_expected(reported, expected_reported)
    )


def _phase_trace_provenance(
    run_dir: Path, phases: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    records: list[dict[str, Any]] = []
    for phase in phases:
        number = phase.get("phase")
        declared = phase.get("trace_sha256")
        record: dict[str, Any] = {"phase": number, "status": "unknown"}
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            path = (run_dir / f"phase-{number}.jsonl").resolve()
            if path.is_relative_to(run_dir.resolve()) and path.is_file():
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                record["sha256"] = actual
                record["status"] = "verified" if declared == actual else "unverified"
                if declared != actual:
                    record["reason"] = "retained phase JSONL digest differs from execution.json"
            else:
                record["status"] = "unverified"
                record["reason"] = "retained phase JSONL is missing"
        else:
            record["status"] = "unverified"
            record["reason"] = "execution phase number is missing"
        records.append(record)
    last_verified = next(
        (row["sha256"] for row in reversed(records) if row.get("status") == "verified"), None
    )
    return records, last_verified


def _source_materialization(run_dir: Path, planned: dict[str, Any]) -> dict[str, Any]:
    expectations = planned.get("source_expectations")
    trial_id = planned.get("trial_id")
    if not isinstance(expectations, list) or not expectations or not isinstance(trial_id, str):
        return {"status": "unknown", "reason": "planned Source byte expectations are missing"}
    try:
        manifest = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
        recorded_sources = manifest.get("sources")
        if not isinstance(recorded_sources, list):
            raise ValueError("run-inputs.json has no Source list")
        case_metadata = planned.get("frozen_case_metadata")
        if not isinstance(case_metadata, dict):
            raise ValueError("planned frozen Trial/Result metadata is missing")
        for field in (
            "trial",
            "requested_outcome",
            "expected_result",
            "approved_scope",
            "campaign_id",
        ):
            if manifest.get(field) != case_metadata.get(field):
                raise ValueError(f"run-inputs.json {field} differs from the frozen case")
        registry_expected = case_metadata.get("registry_capture")
        registry_actual = manifest.get("registry_capture")
        if registry_expected is None:
            if registry_actual is not None:
                raise ValueError("run-inputs.json contains an unexpected registry capture")
        elif (
            not isinstance(registry_actual, dict)
            or registry_actual.get("captured_at") != registry_expected.get("captured_at")
            or registry_actual.get("sha256") != registry_expected.get("sha256", "").lower()
            or registry_actual.get("capture_provenance") != registry_expected.get("provenance")
            or registry_actual.get("registry_id") != registry_expected.get("registry_id")
        ):
            raise ValueError("run-inputs.json registry capture differs from the frozen case")
        if (
            case_metadata.get("trial") != trial_id
            or case_metadata.get("requested_outcome") != planned.get("outcome_id")
            or _json_sha256(case_metadata.get("expected_result")) != planned.get("result_identity")
        ):
            raise ValueError("planned case metadata does not match its Result identity")
        copied = run_dir / "workspace" / "input" / trial_id
        expected_records: set[tuple[str, str, str]] = set()
        hashes: list[dict[str, str]] = []
        for source in expectations:
            if (
                not isinstance(source, dict)
                or not isinstance(source.get("name"), str)
                or not isinstance(source.get("role"), str)
                or not isinstance(source.get("sha256"), str)
            ):
                raise ValueError("planned Source expectation is malformed")
            source_path = (copied / source["name"]).resolve()
            if not source_path.is_relative_to(copied.resolve()) or not source_path.is_file():
                raise ValueError(f"materialized Source is missing: {source['name']}")
            actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual != source["sha256"] or not any(
                isinstance(row, dict)
                and row.get("name") == source["name"]
                and row.get("role") == source["role"]
                and row.get("sha256") == actual
                for row in recorded_sources
            ):
                raise ValueError(f"materialized Source digest is not verified: {source['name']}")
            expected_records.add((source["name"], source["role"], actual))
            hashes.append({"name": source["name"], "role": source["role"], "sha256": actual})
        recorded_records = {
            (row.get("name"), row.get("role"), row.get("sha256"))
            for row in recorded_sources
            if isinstance(row, dict)
        }
        if recorded_records != expected_records or len(recorded_records) != len(recorded_sources):
            raise ValueError("run input Source manifest differs from the planned allowlist")
    except (OSError, ValueError, AttributeError, json.JSONDecodeError) as error:
        return {"status": "unverified", "reason": str(error)}
    return {"status": "verified", "sources": hashes}


def _continuation_trace_provenance(
    campaign_root: Path, planned: dict[str, Any]
) -> list[dict[str, Any]]:
    continuations = planned.get("continuations")
    if not isinstance(continuations, list):
        return []
    records: list[dict[str, Any]] = []
    for continuation in continuations:
        if not isinstance(continuation, dict):
            records.append({"status": "unverified", "reason": "continuation record is invalid"})
            continue
        trace = continuation.get("trace")
        expected = continuation.get("trace_identity")
        record = {"phase": continuation.get("phase"), "status": "unknown"}
        if not isinstance(trace, str) or not trace or Path(trace).is_absolute():
            record.update(status="unverified", reason="continuation trace path is invalid")
        else:
            path = (campaign_root / trace).resolve()
            if not path.is_relative_to(campaign_root) or not path.is_file():
                record.update(status="unverified", reason="continuation trace is missing")
            else:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                record["sha256"] = actual
                record["status"] = "verified" if _same_identity(expected, actual) else "unverified"
                if record["status"] == "unverified":
                    record["reason"] = "continuation trace digest differs from launch manifest"
        if isinstance(continuation.get("session_id"), str):
            record["session_id"] = continuation["session_id"]
        records.append(record)
    return records


def _identity_bindings(declared: Any, execution: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(declared, dict):
        return {"status": "unknown", "reason": "launch has no declared environment"}
    runtime = execution.get("runtime_inputs")
    runtime = runtime if isinstance(runtime, dict) else {}
    provenance = execution.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    build = provenance.get("build")
    build = build if isinstance(build, dict) else {}
    skill = provenance.get("skill")
    skill = skill if isinstance(skill, dict) else {}
    tool_inventory = runtime.get("tool_inventory")
    tool_inventory = tool_inventory if isinstance(tool_inventory, dict) else {}
    phases = execution.get("phases")
    phases = phases if isinstance(phases, list) else []
    artifacts = declared.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    observed: dict[str, Any] = {
        "host": runtime.get("host"),
        "model": {
            "family": execution.get("model"),
            "version": None,
            "effort": execution.get("reasoning_effort"),
        },
        "artifacts": {
            "kit_identity": runtime.get("build_sha256") or build.get("sha256"),
            "pack_identity": runtime.get("pack_identity"),
            "skill_identity": runtime.get("skill_sha256") or skill.get("sha256"),
            "tool_schema_identity": tool_inventory.get("contract_sha256"),
        },
    }
    prompt_hashes = [phase.get("prompt_sha256") for phase in phases if isinstance(phase, dict)]
    host = declared.get("host")
    host = host if isinstance(host, dict) else {}
    observed_prompt = next(
        (
            prompt_hash
            for prompt_hash in prompt_hashes
            if _same_identity(prompt_hash, host.get("prompt_identity"))
        ),
        None,
    )
    if observed_prompt is not None:
        observed["host_prompt_identity"] = observed_prompt
    result: dict[str, Any] = {}
    for section in ("host", "model", "artifacts"):
        expected = declared.get(section)
        seen = observed.get(section)
        if not isinstance(expected, dict):
            continue
        section_result = {}
        for key, value in expected.items():
            actual = seen.get(key) if isinstance(seen, dict) else None
            if section == "host" and key == "prompt_identity":
                actual = observed.get("host_prompt_identity")
            section_result[key] = {
                "declared": value,
                "observed": actual,
                "status": "verified" if _same_identity(actual, value) else "declared_only",
            }
        result[section] = section_result
    return result


def _elapsed_ms(phases: list[dict[str, Any]]) -> int | None:
    milliseconds = 0
    observed = False
    for phase in phases:
        try:
            started = datetime.fromisoformat(phase["started_at"].replace("Z", "+00:00"))
            finished = datetime.fromisoformat(phase["finished_at"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, TypeError, ValueError):
            continue
        duration = (finished - started).total_seconds() * 1000
        if duration < 0:
            continue
        milliseconds += round(duration)
        observed = True
    return milliseconds if observed else None


def _metric(raw_attempt: dict[str, Any], phases: list[dict[str, Any]], key: str) -> Any:
    if raw_attempt.get(key) is not None:
        return raw_attempt[key]
    observed = [phase[key] for phase in phases if phase.get(key) is not None]
    if observed and all(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in observed
    ):
        return sum(observed)
    return None


def _verified_prediction(
    run_dir: Path,
    execution: dict[str, Any],
    attempt_id: str,
    trial_id: str,
    outcome_id: str,
    expected_result: Any,
    result_identity: Any,
) -> tuple[str | None, dict[str, Any]]:
    artifact = execution.get("artifact")
    if (
        not isinstance(artifact, dict)
        or artifact.get("attempt_id") != attempt_id
        or artifact.get("verified") is not True
        or not isinstance(artifact.get("path"), str)
        or not isinstance(artifact.get("sha256"), str)
        or not isinstance(artifact.get("identity"), str)
    ):
        return None, {"status": "unavailable", "reason": "no verified artifact for attempt"}
    run_root = run_dir.resolve()
    path = (run_root / artifact["path"]).resolve()
    if not path.is_relative_to(run_root) or not path.is_file():
        return None, {
            "status": "invalid",
            "reason": "artifact path is missing or escapes run directory",
        }
    if _sha256(path.read_bytes()).removeprefix("sha256:") != artifact["sha256"].removeprefix(
        "sha256:"
    ):
        return None, {"status": "invalid", "reason": "artifact digest differs from execution.json"}

    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))
    verifier = runpy.run_path(str(Path(__file__).with_name("verify_bundle.py")))
    verified, reason = verifier["verify"](path)
    if verified is not True:
        return None, {"status": "invalid", "reason": str(reason)}
    try:
        with zipfile.ZipFile(path) as archive:
            canonical = json.loads(archive.read("canonical.json"))
            bundle_manifest = json.loads(archive.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        return None, {
            "status": "invalid",
            "reason": f"cannot read verified canonical data: {error}",
        }
    if not _same_identity(artifact.get("identity"), bundle_manifest.get("identity")):
        return None, {"status": "invalid", "reason": "bundle identity differs from execution.json"}
    dispositions = canonical.get("dispositions")
    snapshots = canonical.get("snapshots")
    if not isinstance(dispositions, dict) or not isinstance(snapshots, dict):
        return None, {"status": "invalid", "reason": "canonical Trial snapshot is missing"}
    matches = [
        key
        for key in dispositions
        if isinstance(key, str) and key.casefold() == trial_id.casefold()
    ]
    if len(matches) != 1:
        return None, {
            "status": "invalid",
            "reason": "canonical bundle Trial identity does not match plan",
        }
    canonical_trial = matches[0]
    if dispositions[canonical_trial] != "assessed":
        return None, {
            "status": "verified",
            "disposition": dispositions[canonical_trial],
            "bundle_identity": artifact.get("identity"),
            "bundle_sha256": artifact["sha256"],
        }
    snapshot = snapshots.get(canonical_trial)
    label = snapshot.get("overall") if isinstance(snapshot, dict) else None
    if label not in _LABELS:
        return None, {
            "status": "invalid",
            "reason": "assessed snapshot has no valid overall judgment",
        }
    proposal = canonical.get("proposal")
    payload = proposal.get("payload") if isinstance(proposal, dict) else None
    results = payload.get("results") if isinstance(payload, dict) else None
    candidate_results = [
        result
        for result in results or []
        if isinstance(result, dict) and result.get("trial_id") == canonical_trial
    ]
    expected_hash = _json_sha256(expected_result)
    if (
        not isinstance(expected_result, dict)
        or result_identity != expected_hash
        or len(candidate_results) != 1
        or not _same_identity(
            _canonical_identity(candidate_results[0]), snapshot.get("result_identity")
        )
    ):
        return None, {
            "status": "invalid",
            "reason": "verified bundle does not contain the planned approved Result identity",
        }
    runner_attempts = execution.get("attempts")
    runner_attempt = next(
        (
            row
            for row in runner_attempts or []
            if isinstance(row, dict) and row.get("attempt_id") == attempt_id
        ),
        None,
    )
    runner_hash = (
        runner_attempt.get("expected_result_sha256") if isinstance(runner_attempt, dict) else None
    )
    if runner_hash is None:
        runner_hash = execution.get("expected_result_sha256")
    if runner_hash != expected_hash.removeprefix("sha256:"):
        return None, {
            "status": "invalid",
            "reason": "runner did not bind the execution to the planned Result identity",
        }
    if not _matches_expected_result(candidate_results[0], expected_result, outcome_id):
        return label, {
            "status": "verified",
            "disposition": "scope_unverified",
            "reason": (
                "verified bundle Result dimensions differ from the frozen target; "
                "source-adjudicated scope equivalence is unresolved"
            ),
            "bundle_identity": artifact.get("identity"),
            "bundle_sha256": artifact["sha256"],
            "canonical_trial": canonical_trial,
            "planned_result_identity": expected_hash,
            "approved_result_identity": snapshot.get("result_identity"),
        }
    return label, {
        "status": "verified",
        "disposition": "assessed",
        "bundle_identity": artifact.get("identity"),
        "bundle_sha256": artifact["sha256"],
        "canonical_trial": canonical_trial,
        "planned_result_identity": expected_hash,
        "approved_result_identity": snapshot.get("result_identity"),
    }


def _state_status(state: object) -> str:
    if state == "failed_infrastructure":
        return "failed_infrastructure"
    if state == "waiting_for_user":
        return "needs_input"
    if state == "succeeded":
        return "assessed"
    return "failed"


def normalize_launch(
    launch: Any, campaign_dir: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return privacy-safe scorer input plus trace and bundle provenance."""
    if (
        not isinstance(launch, dict)
        or launch.get("schema") != "rob2-kit.development-comparison-launch.v1"
        or not isinstance(launch.get("attempts"), list)
    ):
        raise ValueError("input is not a development-comparison launch manifest")
    outcomes: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    campaign_root = campaign_dir.resolve(strict=True)
    raw_sessions_by_draw: dict[str, tuple[str, str, str]] = {}
    declared_environment = launch.get("declared_environment")
    for planned in launch["attempts"]:
        if not isinstance(planned, dict):
            raise ValueError("launch attempt row is invalid")
        relative = Path(planned["run_dir"])
        if relative.is_absolute():
            raise ValueError("launch run directories must be relative")
        run_dir = (campaign_root / relative).resolve()
        if not run_dir.is_relative_to(campaign_root):
            raise ValueError("launch run directory escapes the campaign")
        execution_path = run_dir / "execution.json"
        execution: dict[str, Any] = {}
        if execution_path.is_file():
            raw = json.loads(execution_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"runner execution record is invalid: {execution_path}")
            execution = raw
        raw_attempts = execution.get("attempts")
        if not isinstance(raw_attempts, list) or not raw_attempts:
            raw_attempts = [
                {
                    "attempt_id": planned["attempt_id"],
                    "kind": "initial",
                    "state": "failed_infrastructure",
                }
            ]

        # A continuation can append a repeated attempt id for a later phase;
        # retain one outcome row for that attempt with all of its phase records.
        attempts_by_id: dict[str, dict[str, Any]] = {}
        for raw_attempt in raw_attempts:
            if not isinstance(raw_attempt, dict) or not isinstance(
                raw_attempt.get("attempt_id"), str
            ):
                continue
            attempts_by_id[raw_attempt["attempt_id"]] = raw_attempt
        phases = execution.get("phases")
        phases = phases if isinstance(phases, list) else []
        source_materialization = _source_materialization(run_dir, planned)
        continuation_traces = _continuation_trace_provenance(campaign_root, planned)
        previous_id: str | None = None
        for index, (runner_id, raw_attempt) in enumerate(attempts_by_id.items()):
            attempt_id = f"{planned['attempt_id']}:{runner_id}"
            attempt_phases = [
                phase
                for phase in phases
                if isinstance(phase, dict) and phase.get("attempt_id") == runner_id
            ]
            session_observations = [
                {"phase": phase.get("phase"), "session_id": phase["codex_session_id"]}
                for phase in attempt_phases
                if isinstance(phase.get("codex_session_id"), str) and phase["codex_session_id"]
            ]
            if execution.get("attempt_id") == runner_id:
                session = execution.get("codex_session_id")
                if isinstance(session, str) and session:
                    session_observations.append({"phase": None, "session_id": session})
            continuation = execution.get("continuation")
            lineage = continuation.get("lineage") if isinstance(continuation, dict) else None
            for item in lineage if isinstance(lineage, list) else []:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("session"), str)
                    and item["session"]
                ):
                    session_observations.append(
                        {"phase": item.get("phase"), "session_id": item["session"]}
                    )
            for item in continuation_traces:
                continuation_rows = planned.get("continuations")
                continuation = next(
                    (
                        row
                        for row in continuation_rows or []
                        if isinstance(row, dict) and row.get("phase") == item.get("phase")
                    ),
                    None,
                )
                if isinstance(continuation, dict) and isinstance(
                    continuation.get("session_id"), str
                ):
                    session_observations.append(
                        {
                            "phase": item.get("phase"),
                            "session_id": continuation["session_id"],
                        }
                    )
            session_ids = sorted({row["session_id"] for row in session_observations})
            session_id = _sha256("\n".join(session_ids).encode()) if session_ids else None
            draw_key = (planned["arm_id"], planned["cell_id"], planned["draw_id"])
            for raw_session_id in session_ids:
                prior_draw = raw_sessions_by_draw.setdefault(raw_session_id, draw_key)
                if prior_draw != draw_key:
                    raise ValueError("a host session was reused across development arms or draws")
            state = raw_attempt.get("state")
            status = _state_status(state)
            prediction: str | None = None
            artifact_provenance: dict[str, Any] = {
                "status": "unavailable",
                "reason": "runner attempt has no terminal assessment artifact",
            }
            if status == "assessed":
                prediction, artifact_provenance = _verified_prediction(
                    run_dir,
                    execution,
                    runner_id,
                    planned["trial_id"],
                    planned["outcome_id"],
                    planned.get("expected_result"),
                    planned.get("result_identity"),
                )
                if prediction is None:
                    disposition = artifact_provenance.get("disposition")
                    if disposition == "needs_input":
                        status = "needs_input"
                    else:
                        status = "failed"
                elif artifact_provenance.get("disposition") == "scope_unverified":
                    status = "scope_unverified"
            if prediction is None:
                prediction = "unknown"
            if status in {"assessed", "scope_unverified"} and session_id is None:
                status = "failed"
                prediction = "unknown"
            outcome = {
                "attempt_id": attempt_id,
                "arm_id": planned["arm_id"],
                "cell_id": planned["cell_id"],
                "draw_id": planned["draw_id"],
                "session_id": session_id,
                "status": status,
                "prediction": prediction,
                "support": "unavailable",
                "completion": status in {"assessed", "scope_unverified"},
                "latency_ms": _elapsed_ms(attempt_phases),
                "cost": _metric(raw_attempt, attempt_phases, "cost"),
                "context_bytes": _metric(raw_attempt, attempt_phases, "context_bytes"),
                "tool_calls": _metric(raw_attempt, attempt_phases, "tool_calls"),
            }
            if raw_attempt.get("kind") == "infrastructure_retry" and previous_id is not None:
                outcome["retry_of"] = previous_id
            trace_records, trace_hash = _phase_trace_provenance(run_dir, attempt_phases)
            outcomes.append(outcome)
            provenance.append(
                {
                    "launch_attempt_id": planned["attempt_id"],
                    "attempt_id": attempt_id,
                    "runner_attempt_id": runner_id,
                    "runner_state": state,
                    "phase_count": len(attempt_phases),
                    "trace_sha256": trace_hash,
                    "phase_traces": trace_records,
                    "continuation_traces": continuation_traces,
                    "host_session_observations": session_observations,
                    "source_materialization": source_materialization,
                    "environment_identity_bindings": _identity_bindings(
                        declared_environment, execution
                    ),
                    "artifact": artifact_provenance,
                    "planned_source_identity": {
                        "identity": planned.get("source_identity"),
                        "status": "declared_only",
                    },
                    "fact_source_availability": (
                        "available"
                        if any(
                            source.get("name") == "scope-matched-facts.json"
                            for source in planned.get("source_expectations", [])
                        )
                        and source_materialization.get("status") == "verified"
                        else "not_applicable"
                        if launch.get("selected_factor") != "fact_binding"
                        else "unverified"
                    ),
                    "fact_uptake_or_correct_binding": "unknown",
                }
            )
            previous_id = attempt_id
        if not attempts_by_id:
            raise ValueError(
                f"no normalizable attempts for planned draw {planned.get('attempt_id')}"
            )

    audit = {
        "schema": NORMALIZATION_SCHEMA,
        "launch_identity": launch.get("comparison_identity"),
        "launcher_identity": launch.get("inputs_identity"),
        "selected_factor": launch.get("selected_factor"),
        "attempts": provenance,
        "declared_environment": {
            "host": "declared_only unless execution telemetry matches the declared value",
            "model": "declared_only unless execution telemetry matches the declared value",
            "artifacts": "declared_only unless execution telemetry matches the declared value",
        },
        "measurements": {
            "latency_ms": "elapsed runner phase timestamps when both endpoints are present",
            "cost": None,
            "context_bytes": None,
            "tool_calls": None,
            "fact_binding": (
                "Source availability can be observed; model uptake and correct binding are unknown"
            ),
        },
    }
    return outcomes, audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args(argv)
    launch_path = args.launch.resolve(strict=True)
    campaign_dir = (
        args.campaign_dir.resolve(strict=True) if args.campaign_dir else launch_path.parent
    )
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    outcomes, provenance = normalize_launch(launch, campaign_dir)
    args.outcomes.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.outcomes.write_text(
        json.dumps(outcomes, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    args.provenance.write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"normalized {len(outcomes)} attempts; provenance retained separately")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
