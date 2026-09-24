"""Run one fresh benchmark phase for every case in bounded parallel waves."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from benchmark_contract import (
    TOOL_INVENTORY_VERSION,
    execution_index_binding,
    finalization_no_progress_continuation_audit,
    host_delivery_diagnosis,
    host_tools_infrastructure_recovery_diagnosis,
    _parse_aware_datetime,
    _no_progress_trace_audit,
    public_tool_inventory,
    _rollout_no_progress_candidates,
    _rollout_status_only_candidates,
    _status_only_no_progress_trace_audit,
    tool_inventory_provenance,
    trace_session_ids,
)

EXPECTED_TOOL_INVENTORY = public_tool_inventory()


def _case_key(outcome: object, trial: object) -> tuple[str, str]:
    """Normalize the human-readable exclusion key used at the launcher boundary."""

    return (
        outcome.casefold().strip() if isinstance(outcome, str) else "",
        trial.casefold().strip() if isinstance(trial, str) else "",
    )


def _parse_case_filter(
    values: list[str], cases: object, *, option: str
) -> tuple[set[tuple[str, str]], list[dict[str, str]]]:
    """Validate OUTCOME:TRIAL selection keys against the frozen index cases."""

    available: dict[tuple[str, str], dict[str, str]] = {}
    if not isinstance(cases, list):
        raise SystemExit("benchmark index cases must be a list")
    for item in cases:
        if not isinstance(item, dict):
            raise SystemExit("benchmark index contains a malformed case")
        outcome = item.get("outcome")
        trial = item.get("trial")
        key = _case_key(outcome, trial)
        if not all(key):
            raise SystemExit("benchmark index cases must declare nonempty outcome and trial")
        if key in available:
            raise SystemExit(
                "benchmark index contains duplicate outcome/trial case key: "
                + f"{outcome}:{trial}"
            )
        available[key] = {
            "outcome": str(outcome).strip(),
            "trial": str(trial).strip(),
        }

    selected: set[tuple[str, str]] = set()
    excluded: list[dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, str) or raw.count(":") != 1:
            raise SystemExit(
                f"invalid {option} {raw!r}; expected OUTCOME:TRIAL"
            )
        outcome, trial = (part.strip() for part in raw.split(":", 1))
        key = _case_key(outcome, trial)
        if not all(key):
            raise SystemExit(
                f"invalid {option} {raw!r}; outcome and trial must be nonempty"
            )
        if key in selected:
            raise SystemExit(f"duplicate {option} {raw!r}")
        selected.add(key)
        if key not in available:
            raise SystemExit(f"{option} {raw!r} is not present in the benchmark index")
        excluded.append(available[key])
    return selected, excluded


def _parse_excluded_cases(
    values: list[str], cases: object
) -> tuple[set[tuple[str, str]], list[dict[str, str]]]:
    return _parse_case_filter(values, cases, option="--exclude-case")


def _parse_included_cases(
    values: list[str], cases: object
) -> tuple[set[tuple[str, str]], list[dict[str, str]]]:
    if not values:
        raise SystemExit("--include-case requires at least one OUTCOME:TRIAL key")
    selected, included = _parse_case_filter(values, cases, option="--include-case")
    if not selected:
        raise SystemExit("--include-case selection is empty")
    return selected, included


def _trace_sessions(path: Path) -> tuple[str, ...]:
    return trace_session_ids(path)


def _session_id(run_dir: Path, phase: int) -> str:
    execution_path = run_dir / "execution.json"
    record = json.loads(execution_path.read_text(encoding="utf-8"))
    value = record.get("codex_session_id")
    if isinstance(value, str) and value:
        return value
    for prior_phase in range(phase - 1, 0, -1):
        trace = run_dir / f"phase-{prior_phase}.jsonl"
        sessions = _trace_sessions(trace)
        if len(sessions) > 1:
            raise RuntimeError(f"ambiguous Codex session identifiers in {trace}")
        if sessions:
            return sessions[0]
    raise RuntimeError(f"no Codex session found in {execution_path}")


def _launcher_summary_path(index_path: Path, phase: int) -> Path:
    base = index_path.resolve().parent / f"phase-{phase}-launcher-summary.json"
    if not base.exists():
        return base
    if phase == 1:
        raise SystemExit(
            "phase 1 already has a launcher summary; use a predeclared replacement index "
            "to retain the prior draw"
        )
    suffix = 2
    while True:
        candidate = base.with_name(f"phase-{phase}-rerun-{suffix}-launcher-summary.json")
        if not candidate.exists():
            return candidate
        suffix += 1


def _write_no_progress_audit_note(run_dir: Path, phase: int) -> dict[str, str] | None:
    """Retain the classification separately from the failed phase record."""

    if phase == 4:
        return _write_finalization_no_progress_audit_note(run_dir)
    if phase != 3:
        return None
    note_path = run_dir / "phase-3.no-progress-audit.json"
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
        row = next(
            item
            for item in execution.get("phases", [])
            if isinstance(item, dict) and item.get("phase") == phase
        )
        trace = (run_dir / f"phase-{phase}.jsonl").read_bytes()
        session = row.get("codex_session_id")
        trial = run_inputs.get("trial")
        audit = (
            _no_progress_trace_audit(trace, session, trial)
            if isinstance(session, str) and isinstance(trial, str)
            else None
        ) or (
            _status_only_no_progress_trace_audit(trace, session, trial)
            if isinstance(session, str) and isinstance(trial, str)
            else None
        )
        if audit is None:
            raise ValueError("the no-progress trace no longer matches its audited classification")
        runtime = execution.get("runtime_inputs")
        codex_home = Path(str(runtime["codex_home_path"])).resolve(strict=True)
        phase_start = _parse_aware_datetime(row.get("started_at"))
        phase_finish = _parse_aware_datetime(row.get("finished_at"))
        rollout_candidates = (
            _rollout_status_only_candidates(
                codex_home,
                session,
                phase_start,
                phase_finish,
                phase=3,
                trial=trial,
                trace_status_result=audit["status_result"],
                expected_status_projection=audit["status_projection"],
            )
            if audit.get("workflow_methods_called")
            else _rollout_no_progress_candidates(
                codex_home,
                session,
                phase_start,
                phase_finish,
                audit["mcp_calls"],
                audit["status_projection"],
                trial,
            )
        )
        if len(rollout_candidates) != 1:
            raise ValueError("the no-progress turn does not bind to exactly one audited rollout")
        rollout = rollout_candidates[0]
        note = {
            "schema": "rob2-kit.audited-no-progress-continuation.v1",
            "phase": phase,
            "classification": (
                "completed_no_workflow_progress"
                if not audit.get("workflow_methods_called")
                else "completed_status_only_no_progress"
            ),
            "original_failure_preserved": True,
            "trace_sha256": hashlib.sha256(trace).hexdigest(),
            "codex_session_id": session,
            "workflow_methods_called": audit.get("workflow_methods_called", []),
            "read_only_methods_called": audit.get("read_only_methods_called", []),
            "read_only_diagnostics": audit.get("read_only_diagnostics", []),
            "resource_probes": audit.get("resource_probes", []),
            "status_projection": audit.get("status_projection"),
            "rollout": {
                "path": str(rollout["path"]),
                "sha256": rollout["sha256"],
                "byte_count": rollout["byte_count"],
                "turn_id": rollout["turn_id"],
                "exec_source_sha256s": rollout.get("exec_source_sha256s", []),
                "exec_call_ids": rollout.get("exec_call_ids", []),
                "exec_output_sha256s": rollout.get("exec_output_sha256s", []),
            },
            "detail": (
                "Phase 3 completed with one successful read-only get_status call and paired "
                "read-only tool-description output; the rollout contains no other action."
                if audit.get("workflow_methods_called")
                else "Phase 3 completed with the same Codex session and no public Rob2 workflow call. "
                "Its resource reads were read-only diagnostics; the tool-list output enumerated "
                "the advertised public inventory and was not a workflow call."
            ),
            "next_phase": phase + 1,
        }
        if not audit.get("workflow_methods_called"):
            note["tool_inventory_count"] = len(EXPECTED_TOOL_INVENTORY)
        encoded = json.dumps(note, indent=2, sort_keys=True) + "\n"
        if note_path.exists():
            existing = json.loads(note_path.read_text(encoding="utf-8"))
            existing_rollout = existing.get("rollout") if isinstance(existing, dict) else None
            if (
                not isinstance(existing, dict)
                or not isinstance(existing_rollout, dict)
                or existing.get("phase") != phase
                or existing.get("trace_sha256") != note["trace_sha256"]
                or existing.get("codex_session_id") != session
                or existing.get("status_projection") != note["status_projection"]
                or existing_rollout.get("path") != note["rollout"]["path"]
                or existing_rollout.get("sha256") != note["rollout"]["sha256"]
                or existing_rollout.get("byte_count") != note["rollout"]["byte_count"]
                or existing_rollout.get("turn_id") != note["rollout"]["turn_id"]
            ):
                return {
                    "code": "no_progress_audit_note_mismatch",
                    "detail": "The retained no-progress audit note does not match its verified trace and rollout.",
                    "recovery": "Retain Phase 3 and inspect its separate audit note before continuing.",
                }
        else:
            with note_path.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
    except (AttributeError, OSError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "code": "no_progress_audit_note_unavailable",
            "detail": str(error),
            "recovery": "Retain Phase 3 and preserve its original failure record.",
        }
    return None


def _write_finalization_no_progress_audit_note(
    run_dir: Path,
) -> dict[str, str] | None:
    """Retain the narrowly audited Phase 4 read-only turn separately."""

    note_path = run_dir / "phase-4.no-progress-audit.json"
    try:
        evidence = finalization_no_progress_continuation_audit(run_dir)
        if not isinstance(evidence, dict):
            raise ValueError("Phase 4 no-progress evidence is unavailable")
        rollout = evidence.get("rollout")
        trace_audit = evidence.get("trace_audit")
        if not isinstance(rollout, dict) or not isinstance(trace_audit, dict):
            raise ValueError("Phase 4 audit is missing its bound trace or rollout evidence")
        status_only = trace_audit.get("workflow_methods_called") == ["get_status"]
        if status_only:
            rollout_record = {
                "path": str(rollout["path"]),
                "sha256": rollout["sha256"],
                "byte_count": rollout["byte_count"],
                "turn_id": rollout["turn_id"],
                "exec_source_sha256s": rollout["exec_source_sha256s"],
                "exec_call_ids": rollout["exec_call_ids"],
                "exec_output_sha256s": rollout["exec_output_sha256s"],
            }
            classification = "completed_status_only_no_progress"
            read_only_methods = ["get_status"]
            read_only_diagnostics = ["functions.exec:get_status_and_filtered_tool_name_lookup"]
            detail = (
                "Phase 4 completed with one successful get_status call and one paired, read-only "
                "tool-name lookup. The trace and rollout bind both to the unchanged "
                "ready-to-finalize workspace."
            )
        else:
            rollout_record = {
                "path": str(rollout["path"]),
                "sha256": rollout["sha256"],
                "byte_count": rollout["byte_count"],
                "turn_id": rollout["turn_id"],
                "exec_source_sha256": rollout["exec_source_sha256"],
                "exec_call_id": rollout["exec_call_id"],
                "exec_output_sha256": rollout.get("exec_output_sha256"),
            }
            classification = "completed_read_only_tool_description_lookup"
            read_only_methods = ["tool_description_lookup:mcp__rob2__review_trial"]
            read_only_diagnostics = [
                "functions.exec:ALL_TOOLS.find(mcp__rob2__review_trial).description"
            ]
            detail = (
                "Phase 4 completed with one paired, read-only lookup of the public "
                "review_trial tool description and no Rob2 workflow call. The trace and "
                "rollout bind this turn to the unchanged ready-to-finalize workspace."
            )
        note = {
            "schema": "rob2-kit.audited-no-progress-continuation.v1",
            "phase": 4,
            "classification": classification,
            "original_failure_preserved": True,
            "scoring_status": "infrastructure_no_progress_unscored",
            "trace_sha256": evidence.get("trace_sha256"),
            "codex_session_id": evidence.get("codex_session_id"),
            "workflow_methods_called": trace_audit.get("workflow_methods_called", []),
            "read_only_methods_called": read_only_methods,
            "read_only_diagnostics": read_only_diagnostics,
            "resource_probes": [],
            "status_projection": evidence.get("status_projection"),
            "runtime_inputs_sha256": evidence.get("runtime_inputs_sha256"),
            "runtime_transition": evidence.get("runtime_transition"),
            "phase_started_at": evidence.get("phase_started_at"),
            "phase_finished_at": evidence.get("phase_finished_at"),
            "rollout": rollout_record,
            "detail": detail,
            "next_phase": 5,
        }
        if not status_only:
            note["tool_inventory_count"] = len(EXPECTED_TOOL_INVENTORY)
        encoded = json.dumps(note, indent=2, sort_keys=True) + "\n"
        if note_path.exists():
            if note_path.read_text(encoding="utf-8") != encoded:
                return {
                    "code": "no_progress_audit_note_mismatch",
                    "detail": "The retained Phase 4 audit note differs from its verified classification.",
                    "recovery": "Retain Phase 4 and repair its separate audit note before continuing.",
                }
        else:
            with note_path.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "code": "no_progress_audit_note_unavailable",
            "detail": str(error),
            "recovery": "Retain Phase 4 and preserve its original failure record.",
        }
    return None


def _continuation_diagnosis(run_dir: Path, phase: int) -> str | dict[str, str] | None:
    prior_phase = phase - 1
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            "frozen launch tool inventory is unavailable; recovery: start a fresh "
            "benchmark attempt and retain this run as resumable"
        )
    runtime = execution.get("runtime_inputs") if isinstance(execution, dict) else None
    runtime_digest = (
        hashlib.sha256(
            json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(runtime, dict)
        else None
    )
    if runtime_digest is None or execution.get("runtime_inputs_sha256") != runtime_digest:
        return (
            "frozen launch runtime inputs failed their integrity check; "
            "recovery: start a fresh benchmark attempt"
        )
    frozen = runtime.get("expected_tool_inventory") if isinstance(runtime, dict) else None
    version = runtime.get("tool_inventory_version") if isinstance(runtime, dict) else None
    provenance = runtime.get("tool_inventory") if isinstance(runtime, dict) else None
    if isinstance(provenance, dict):
        frozen = provenance.get("names") or frozen
        version = provenance.get("version") or version
    if not isinstance(frozen, list) or not frozen or not isinstance(version, str):
        return (
            "frozen launch tool inventory or provenance is unavailable; recovery: start a "
            "fresh benchmark attempt and retain this run as resumable"
        )
    if version != TOOL_INVENTORY_VERSION:
        return (
            "frozen launch tool inventory version is incompatible; recovery: start a fresh "
            "benchmark attempt"
        )
    if isinstance(provenance, dict):
        current_provenance = tool_inventory_provenance()
        for field in ("source", "contract_version", "contract_sha256"):
            if provenance.get(field) is not None and provenance.get(
                field
            ) != current_provenance.get(field):
                return (
                    "current tool inventory provenance is incompatible with the frozen "
                    "launch record; recovery: start a fresh benchmark attempt"
                )
    advertised = runtime.get("server_advertised_inventory") if isinstance(runtime, dict) else None
    server_binding = advertised.get("server_binding") if isinstance(advertised, dict) else None
    codex_binding = runtime.get("codex_registered_mcp") if isinstance(runtime, dict) else None
    if not isinstance(server_binding, dict) or codex_binding != server_binding:
        return {
            "code": "codex_mcp_binding_mismatch",
            "detail": (
                "The frozen Codex rob2 command/args binding does not match the probed MCP server."
            ),
            "recovery": (
                "Start a fresh benchmark attempt with the configured rob2 command and args."
            ),
        }
    if (
        not isinstance(advertised, dict)
        or advertised.get("status") != "verified"
        or advertised.get("source") != "stdio tools/list"
        or advertised.get("server") != "rob2"
        or advertised.get("names")
        != sorted(name for name in EXPECTED_TOOL_INVENTORY if isinstance(name, str))
        or not isinstance(advertised.get("inventory_sha256"), str)
    ):
        return (
            "server-advertised MCP tools/list inventory is missing or incompatible; "
            "recovery: start a fresh benchmark attempt and retain this run"
        )
    current_provenance = tool_inventory_provenance()
    if (
        advertised.get("contract_version") != current_provenance.get("contract_version")
        or advertised.get("contract_sha256") != current_provenance.get("contract_sha256")
    ):
        return (
            "server-advertised MCP inventory does not match the current public contract; "
            "recovery: start a fresh benchmark attempt"
        )
    try:
        phase_meta = json.loads(
            (run_dir / f"phase-{prior_phase}.meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        phase_meta = None
    if (
        not isinstance(phase_meta, dict)
        or phase_meta.get("server_advertised_inventory") != advertised
    ):
        return (
            "prior phase metadata does not bind the verified server-advertised inventory; "
            "recovery: start a fresh benchmark attempt and retain this run"
        )
    phases = execution.get("phases") if isinstance(execution, dict) else None
    prior = next(
        (
            row
            for row in reversed(phases)
            if isinstance(row, dict) and row.get("phase") == prior_phase
        ),
        None,
    ) if isinstance(phases, list) else None
    delivery = host_delivery_diagnosis(
        run_dir / f"phase-{prior_phase}.jsonl",
        expected_sha256=(prior.get("trace_sha256") if isinstance(prior, dict) else None),
        expected_session=(prior.get("codex_session_id") if isinstance(prior, dict) else None),
    )
    if isinstance(delivery, dict) and delivery.get("code") == "host_delivery_call_missing":
        recovery = (
            host_tools_infrastructure_recovery_diagnosis(run_dir, prior_phase)
        )
        if recovery is None:
            if prior_phase in {3, 4}:
                recovery = _write_no_progress_audit_note(run_dir, prior_phase)
        if recovery is None:
            delivery = None
        else:
            return recovery
    if delivery is not None:
        return delivery
    if not isinstance(prior, dict):
        return {
            "code": "host_delivery_phase_binding_missing",
            "detail": "The prior benchmark phase has no execution record to bind its trace.",
            "recovery": "Retain this phase as resumable and inspect its execution record.",
        }
    recorded_sessions = [
        phase_meta[field]
        for field in ("codex_session_id", "session")
        if field in phase_meta
    ]
    if (
        phase_meta.get("trace_sha256") != prior.get("trace_sha256")
        or not recorded_sessions
        or any(
            not isinstance(value, str)
            or not value.strip()
            or value != prior.get("codex_session_id")
            for value in recorded_sessions
        )
    ):
        return {
            "code": "host_delivery_phase_binding_mismatch",
            "detail": (
                "Prior phase metadata does not bind the verified trace hash and Codex session."
            ),
            "recovery": (
                "Retain this phase as resumable and repair its phase metadata before continuing."
            ),
        }
    frozen_set = {name for name in frozen if isinstance(name, str) and name.strip()}
    current_set = set(EXPECTED_TOOL_INVENTORY)
    if frozen_set != current_set:
        missing = sorted(frozen_set - current_set)
        unexpected = sorted(current_set - frozen_set)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        return (
            "current tool inventory is incompatible with the frozen launch inventory ("
            + "; ".join(detail)
            + "); recovery: start a fresh benchmark attempt"
        )
    return None


def _run_one(
    repo: Path,
    item: dict[str, Any],
    phase: int,
    prompt: Path,
    *,
    model: str,
    effort: str,
    manifest_model: str,
    manifest_effort: str,
    timeout_seconds: float | None = None,
    require_isolated_host: bool,
    index_path: Path | None = None,
    index_sha256: str | None = None,
    allow_build_only_transition: bool = False,
    build_transition_reason: str | None = None,
    launcher_invocation_id: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(item["run_dir"])
    prompt_path = Path(item["prompt"]) if phase == 1 else prompt
    launcher_invocation_id = launcher_invocation_id or uuid.uuid4().hex
    attempt_number = item.get("attempt", 1)
    if isinstance(attempt_number, str) and attempt_number.isdecimal():
        attempt_number = int(attempt_number)
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        return {
            "outcome": item.get("outcome"),
            "trial": item.get("trial"),
            "phase": phase,
            "exit_code": 2,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "invalid_attempt_number",
                "detail": "benchmark case attempt must be a positive integer",
            },
        }
    if phase == 1:
        try:
            case = json.loads(Path(item["case"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return {
                "outcome": item.get("outcome"),
                "trial": item.get("trial"),
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": {"code": "case_unreadable", "detail": str(error)},
            }
        if isinstance(case, dict) and isinstance(case.get("scope_unresolved"), str):
            return {
                "outcome": item.get("outcome"),
                "trial": item.get("trial"),
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": {
                    "code": "scope_unresolved",
                    "detail": case["scope_unresolved"],
                    "recovery": "Freeze a complete expected_result before launching Codex.",
                },
            }
        campaign_id = item.get("campaign_id")
        if isinstance(campaign_id, str) and case.get("campaign_id") != campaign_id:
            return {
                "outcome": item.get("outcome"),
                "trial": item.get("trial"),
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": {
                    "code": "campaign_binding_mismatch",
                    "detail": "case campaign_id differs from the frozen benchmark index",
                },
            }
    if phase == 1 and (
        allow_build_only_transition or build_transition_reason is not None
    ):
        return {
            "outcome": item.get("outcome"),
            "trial": item.get("trial"),
            "phase": phase,
            "exit_code": 2,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "invalid_build_transition_options",
                "detail": "build-only runtime transitions are valid only for continuation phases",
            },
        }
    if allow_build_only_transition != bool(
        isinstance(build_transition_reason, str) and build_transition_reason.strip()
    ):
        return {
            "outcome": item.get("outcome"),
            "trial": item.get("trial"),
            "phase": phase,
            "exit_code": 2,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "invalid_build_transition_options",
                "detail": "--allow-build-only-transition and --build-transition-reason must be supplied together with a nonempty reason",
            },
        }
    if phase > 1:
        campaign_id = item.get("campaign_id")
        if isinstance(campaign_id, str):
            try:
                execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
                execution_campaign_id = execution.get("identity", {}).get("campaign_id")
            except (OSError, json.JSONDecodeError, AttributeError):
                execution_campaign_id = None
            if execution_campaign_id != campaign_id:
                return {
                    "outcome": item.get("outcome"),
                    "trial": item.get("trial"),
                    "phase": phase,
                    "exit_code": 2,
                    "run_dir": str(run_dir),
                    "diagnosis": {
                        "code": "campaign_binding_mismatch",
                        "detail": "execution campaign_id differs from the frozen benchmark index",
                },
            }
        try:
            execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
            runtime_inputs = execution.get("runtime_inputs")
            frozen_isolation = (
                runtime_inputs.get("host_isolation_required")
                if isinstance(runtime_inputs, dict)
                else None
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            frozen_isolation = None
        if frozen_isolation is not require_isolated_host:
            return {
                "outcome": item.get("outcome"),
                "trial": item.get("trial"),
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": {
                    "code": "isolation_binding_mismatch",
                    "detail": "continuation isolation mode differs from the frozen first phase",
                },
            }
        diagnosis = _continuation_diagnosis(run_dir, phase)
        if diagnosis is not None:
            return {
                "outcome": item["outcome"],
                "trial": item["trial"],
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": diagnosis,
            }
    runtime_index_path = index_path
    runtime_index_sha256 = index_sha256
    if phase > 1 and ((index_path is None) != (index_sha256 is None)):
        return {
            "outcome": item.get("outcome"),
            "trial": item.get("trial"),
            "phase": phase,
            "exit_code": 2,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "continuation_benchmark_index_invalid",
                "detail": "The continuation selection index and its digest must be supplied together.",
            },
        }
    if phase > 1 and index_path is not None and index_sha256 is not None:
        try:
            execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
            execution_index_binding(index_path, index_sha256, item, run_dir, attempt_number)
            runtime_inputs = execution.get("runtime_inputs")
            frozen_binding = (
                runtime_inputs.get("benchmark_index")
                if isinstance(runtime_inputs, dict)
                else None
            )
            if not isinstance(frozen_binding, dict):
                raise ValueError("the execution has no frozen benchmark index binding")
            frozen_path = frozen_binding.get("path")
            frozen_sha256 = frozen_binding.get("sha256")
            if not isinstance(frozen_path, str) or not isinstance(frozen_sha256, str):
                raise ValueError("the frozen benchmark index path or digest is missing")
            verified_frozen_binding = execution_index_binding(
                Path(frozen_path), frozen_sha256, item, run_dir, attempt_number
            )
            if verified_frozen_binding != frozen_binding:
                raise ValueError("the frozen execution index binding does not match its retained index")
            # The batch index selects the run; runtime provenance remains bound to Phase 1.
            runtime_index_path = Path(frozen_binding["path"])
            runtime_index_sha256 = frozen_binding["sha256"]
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return {
                "outcome": item.get("outcome"),
                "trial": item.get("trial"),
                "phase": phase,
                "exit_code": 2,
                "run_dir": str(run_dir),
                "diagnosis": {
                    "code": "continuation_benchmark_index_invalid",
                    "detail": str(error),
                },
            }
    command = [
        "uv",
        "run",
        "--no-project",
        "python",
        "scripts/run_rsi_case.py",
        "--prompt",
        str(prompt_path),
        "--run-dir",
        str(run_dir),
        "--phase",
        str(phase),
        "--model",
        model,
        "--effort",
        effort,
        "--manifest-model",
        str(item.get("manifest_model") or manifest_model),
        "--manifest-effort",
        str(item.get("manifest_effort") or manifest_effort),
    ]
    if require_isolated_host:
        command.append("--require-isolated-host")
    if runtime_index_path is not None and runtime_index_sha256 is not None:
        command.extend(
            [
                "--benchmark-index",
                str(runtime_index_path),
                "--benchmark-index-sha256",
                runtime_index_sha256,
            ]
        )
    if phase == 1:
        command[5:5] = ["--case", str(item["case"])]
    else:
        command.extend(["--session", _session_id(run_dir, phase)])
    if timeout_seconds is not None:
        command.extend(["--timeout-seconds", str(timeout_seconds)])
    if allow_build_only_transition:
        command.append("--allow-build-only-transition")
        command.extend(["--build-transition-reason", build_transition_reason.strip()])
    command.extend(["--attempt-number", str(attempt_number)])
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return {
            "outcome": item["outcome"],
            "trial": item["trial"],
            "phase": phase,
            "exit_code": 127,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "launcher_process_start_failed",
                "failure_kind": "process_start",
                "exception_type": type(error).__name__,
                "detail": str(error),
            },
        }
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / f"launcher-phase-{phase}-{launcher_invocation_id}.stdout.txt"
    stderr_path = run_dir / f"launcher-phase-{phase}-{launcher_invocation_id}.stderr.txt"
    try:
        with stdout_path.open("xb") as output_file:
            output_file.write(completed.stdout)
        with stderr_path.open("xb") as error_file:
            error_file.write(completed.stderr)
    except OSError as error:
        return {
            "outcome": item["outcome"],
            "trial": item["trial"],
            "phase": phase,
            "exit_code": 127,
            "run_dir": str(run_dir),
            "diagnosis": {
                "code": "launcher_log_write_failed",
                "detail": str(error),
            },
        }
    return {
        "outcome": item["outcome"],
        "trial": item["trial"],
        "phase": phase,
        "exit_code": completed.returncode,
        "run_dir": str(run_dir),
        "launcher_stdout_path": str(stdout_path.resolve()),
        "launcher_stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "launcher_stderr_path": str(stderr_path.resolve()),
        "launcher_stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "launcher_invocation_id": launcher_invocation_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument(
        "--exclude-case",
        action="append",
        default=[],
        metavar="OUTCOME:TRIAL",
        help="Omit a documented case from this batch while retaining the frozen index binding",
    )
    parser.add_argument(
        "--include-case",
        action="append",
        default=[],
        metavar="OUTCOME:TRIAL",
        help="Run only these reviewed cases while retaining the frozen index binding",
    )
    parser.add_argument(
        "--allow-build-only-transition",
        action="store_true",
        help="Permit a continuation whose only runtime change is build_sha256",
    )
    parser.add_argument(
        "--build-transition-reason",
        help="Required nonempty reason when allowing a build-only continuation transition",
    )
    isolation = parser.add_mutually_exclusive_group(required=True)
    isolation.add_argument(
        "--require-isolated-host", dest="require_isolated_host", action="store_const", const=True
    )
    isolation.add_argument(
        "--non-strict-exploratory",
        dest="require_isolated_host",
        action="store_const",
        const=False,
        help="Run explicitly as an exploratory campaign that cannot qualify as isolated",
    )
    args = parser.parse_args()
    if args.phase < 1 or args.workers < 1:
        raise SystemExit("--phase must be positive and --workers must be at least one")
    if args.phase == 1 and (
        args.allow_build_only_transition or args.build_transition_reason is not None
    ):
        raise SystemExit(
            "build-only runtime transitions are valid only for continuation phases"
        )
    if args.allow_build_only_transition != bool(
        isinstance(args.build_transition_reason, str) and args.build_transition_reason.strip()
    ):
        raise SystemExit(
            "--allow-build-only-transition and --build-transition-reason must be supplied together with a nonempty reason"
        )
    if args.include_case and args.exclude_case:
        raise SystemExit("--include-case and --exclude-case cannot be combined")
    repo = Path(__file__).resolve().parents[1]
    index_path = args.index.resolve(strict=True)
    index_bytes = index_path.read_bytes()
    index_sha256 = hashlib.sha256(index_bytes).hexdigest()
    index = json.loads(index_bytes)
    if not isinstance(index, dict):
        raise SystemExit("benchmark index must be an object")
    case_keys = index.get("cases")
    if args.include_case:
        included_keys, _included = _parse_included_cases(
            args.include_case, case_keys
        )
        submitted_cases = [
            item
            for item in index["cases"]
            if _case_key(item.get("outcome"), item.get("trial")) in included_keys
        ]
        excluded_cases = [
            {"outcome": item["outcome"], "trial": item["trial"]}
            for item in index["cases"]
            if _case_key(item.get("outcome"), item.get("trial")) not in included_keys
        ]
        included_cases = [
            {"outcome": item["outcome"], "trial": item["trial"]}
            for item in submitted_cases
        ]
        selection_mode = "include"
    else:
        excluded_keys, excluded_cases = _parse_excluded_cases(
            args.exclude_case, case_keys
        )
        submitted_cases = [
            item
            for item in index["cases"]
            if _case_key(item.get("outcome"), item.get("trial")) not in excluded_keys
        ]
        included_cases = [
            {"outcome": item["outcome"], "trial": item["trial"]}
            for item in submitted_cases
        ]
        selection_mode = "exclude" if args.exclude_case else "all"
    prompt = (args.prompt or index_path.parent / "continuation.txt").resolve(strict=True)
    manifest_model = index.get("model")
    manifest_effort = index.get("reasoning_effort", index.get("effort"))
    if not isinstance(manifest_model, str) or not manifest_model.strip():
        raise SystemExit("benchmark index must declare model")
    if not isinstance(manifest_effort, str) or not manifest_effort.strip():
        raise SystemExit("benchmark index must declare reasoning effort")
    model = args.model or manifest_model
    effort = args.effort or manifest_effort
    manifest_timeout = index.get("timeout_seconds")
    timeout_seconds = (
        args.timeout_seconds if args.timeout_seconds is not None else manifest_timeout
    )
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise SystemExit("timeout_seconds must be a positive finite number")
    summary_path = _launcher_summary_path(index_path, args.phase)
    launcher_invocation_id = uuid.uuid4().hex
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                repo,
                item,
                args.phase,
                prompt,
                model=model,
                effort=effort,
                manifest_model=manifest_model,
                manifest_effort=manifest_effort,
                timeout_seconds=timeout_seconds,
                require_isolated_host=args.require_isolated_host,
                index_path=index_path,
                index_sha256=index_sha256,
                allow_build_only_transition=args.allow_build_only_transition,
                build_transition_reason=args.build_transition_reason,
                launcher_invocation_id=launcher_invocation_id,
            ): item
            for item in submitted_cases
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {
                    "outcome": item.get("outcome"),
                    "trial": item.get("trial"),
                    "phase": args.phase,
                    "exit_code": 2,
                    "run_dir": str(item.get("run_dir", "")),
                    "diagnosis": {
                        "code": "launcher_future_failed",
                        "detail": f"{type(error).__name__}: {error}",
                    },
                }
            result["benchmark_index_sha256"] = index_sha256
            result["launcher_invocation_id"] = launcher_invocation_id
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: (row["outcome"], row["trial"]))
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    scope_report = {
        "schema": "rob2-kit.benchmark-phase-scope.v1",
        "phase": args.phase,
        "benchmark_index": str(index_path),
        "benchmark_index_sha256": index_sha256,
        "selection_mode": selection_mode,
        "included_count": len(included_cases),
        "included_cases": included_cases,
        "submitted_count": len(submitted_cases),
        "excluded_count": len(excluded_cases),
        "submitted_cases": [
            {"outcome": item["outcome"], "trial": item["trial"]}
            for item in submitted_cases
        ],
        "excluded_cases": excluded_cases,
    }
    scope_path = summary_path.with_name(
        summary_path.name.replace("-launcher-summary.json", "-launcher-scope.json")
    )
    scope_path.write_text(json.dumps(scope_report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scope": scope_report}, ensure_ascii=False), flush=True)
    failures = [row for row in results if row["exit_code"] != 0]
    if failures:
        raise SystemExit(f"{len(failures)} benchmark phases failed; see launcher logs")


if __name__ == "__main__":
    main()
