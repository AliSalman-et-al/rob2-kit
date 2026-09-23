"""Run one fresh benchmark phase for every case in bounded parallel waves."""

from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from benchmark_contract import (
    TOOL_INVENTORY_VERSION,
    public_tool_inventory,
    tool_inventory_provenance,
    trace_has_rob2_runtime_evidence,
)

EXPECTED_TOOL_INVENTORY = public_tool_inventory()


def _trace_sessions(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    sessions: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in {
            "thread.started",
            "session.started",
            "session.created",
            "session_id",
        }:
            for key in ("thread_id", "session_id"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    sessions.add(value.strip())
            thread = event.get("thread")
            if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                sessions.add(thread["id"].strip())
    return tuple(sorted(session for session in sessions if session))


def _trace_tool_inventory(path: Path) -> tuple[str, ...] | None:
    if not path.is_file():
        return None
    inventories: set[tuple[str, ...]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        payload = None
        if event.get("type") in {
            "mcp_list_tools",
            "mcp.tools.list",
            "session.ready",
            "thread.ready",
        }:
            payload = (
                event.get("tools") or event.get("tool_inventory") or event.get("available_tools")
            )
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") in {"mcp_list_tools", "mcp.tools.list"}
        ):
            payload = item.get("tools") or item.get("tool_inventory") or item.get("available_tools")
        if not isinstance(payload, list):
            continue
        names = sorted(
            {
                (entry if isinstance(entry, str) else entry.get("name") or entry.get("tool"))
                for entry in payload
                if isinstance(entry, str) or isinstance(entry, dict)
            }
        )
        names = [name for name in names if isinstance(name, str) and name.strip()]
        if names:
            inventories.add(tuple(names))
    if len(inventories) > 1:
        raise RuntimeError(f"ambiguous tool inventory in {path}")
    return next(iter(inventories), None)


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


def _continuation_diagnosis(run_dir: Path, phase: int) -> str | None:
    prior_phase = phase - 1
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            "frozen launch tool inventory is unavailable; recovery: start a fresh "
            "benchmark attempt and retain this run as resumable"
        )
    runtime = execution.get("runtime_inputs") if isinstance(execution, dict) else None
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
    trace = run_dir / f"phase-{prior_phase}.jsonl"
    inventory = _trace_tool_inventory(trace)
    if inventory is None and not trace_has_rob2_runtime_evidence(trace):
        return (
            "continuation runtime availability is unverified; no rob2 MCP call was observed; "
            "recovery: start a fresh benchmark attempt and retain this run"
        )
    if inventory is not None and set(inventory) != frozen_set:
        missing = sorted(frozen_set - set(inventory))
        unexpected = sorted(set(inventory) - frozen_set)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        return (
            "continuation tool inventory is incompatible ("
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
) -> dict[str, Any]:
    run_dir = Path(item["run_dir"])
    prompt_path = Path(item["prompt"]) if phase == 1 else prompt
    if phase > 1:
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
    if phase == 1:
        command[5:5] = ["--case", str(item["case"])]
    else:
        command.extend(["--session", _session_id(run_dir, phase)])
    completed = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        check=False,
    )
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
    args = parser.parse_args()
    if args.phase < 1 or args.workers < 1:
        raise SystemExit("--phase must be positive and --workers must be at least one")
    repo = Path(__file__).resolve().parents[1]
    index = json.loads(args.index.resolve(strict=True).read_text(encoding="utf-8"))
    prompt = (args.prompt or args.index.resolve().parent / "continuation.txt").resolve(strict=True)
    manifest_model = index.get("model")
    manifest_effort = index.get("reasoning_effort", index.get("effort"))
    if not isinstance(manifest_model, str) or not manifest_model.strip():
        raise SystemExit("benchmark index must declare model")
    if not isinstance(manifest_effort, str) or not manifest_effort.strip():
        raise SystemExit("benchmark index must declare reasoning effort")
    model = args.model or manifest_model
    effort = args.effort or manifest_effort
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
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
            )
            for item in index["cases"]
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: (row["outcome"], row["trial"]))
    summary_path = args.index.resolve().parent / f"phase-{args.phase}-launcher-summary.json"
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    failures = [row for row in results if row["exit_code"] != 0]
    if failures:
        raise SystemExit(f"{len(failures)} benchmark phases failed; see launcher logs")


if __name__ == "__main__":
    main()
