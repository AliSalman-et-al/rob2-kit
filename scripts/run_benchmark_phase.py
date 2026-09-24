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
    host_delivery_diagnosis,
    public_tool_inventory,
    tool_inventory_provenance,
    trace_session_ids,
)

EXPECTED_TOOL_INVENTORY = public_tool_inventory()


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
    if delivery is not None:
        return delivery
    if not isinstance(prior, dict):
        return {
            "code": "host_delivery_phase_binding_missing",
            "detail": "The prior benchmark phase has no execution record to bind its trace.",
            "recovery": "Retain this phase as resumable and inspect its execution record.",
        }
    if (
        phase_meta.get("trace_sha256") != prior.get("trace_sha256")
        or phase_meta.get("codex_session_id") != prior.get("codex_session_id")
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
) -> dict[str, Any]:
    run_dir = Path(item["run_dir"])
    prompt_path = Path(item["prompt"]) if phase == 1 else prompt
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
    if index_path is not None and index_sha256 is not None:
        command.extend(
            ["--benchmark-index", str(index_path), "--benchmark-index-sha256", index_sha256]
        )
    if phase == 1:
        command[5:5] = ["--case", str(item["case"])]
    else:
        command.extend(["--session", _session_id(run_dir, phase)])
    if timeout_seconds is not None:
        command.extend(["--timeout-seconds", str(timeout_seconds)])
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
    (run_dir / f"launcher-phase-{phase}.stdout.txt").write_bytes(completed.stdout)
    (run_dir / f"launcher-phase-{phase}.stderr.txt").write_bytes(completed.stderr)
    return {
        "outcome": item["outcome"],
        "trial": item["trial"],
        "phase": phase,
        "exit_code": completed.returncode,
        "run_dir": str(run_dir),
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
    repo = Path(__file__).resolve().parents[1]
    index_path = args.index.resolve(strict=True)
    index_bytes = index_path.read_bytes()
    index_sha256 = hashlib.sha256(index_bytes).hexdigest()
    index = json.loads(index_bytes)
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
            ): item
            for item in index["cases"]
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
    failures = [row for row in results if row["exit_code"] != 0]
    if failures:
        raise SystemExit(f"{len(failures)} benchmark phases failed; see launcher logs")


if __name__ == "__main__":
    main()
