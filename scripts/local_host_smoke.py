"""Execute the local-only real Codex/Claude smoke workflow for release owners."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from rob2_kit.evaluation.installed_replay import normalize_semantic_value
from rob2_kit.evaluation.local_host_smoke import (
    HostSmokeOptions,
    build_smoke_plan,
    cleanup_smoke_workspace,
    compare_semantic_outcomes,
    inspect_durable_outcome,
    redact_diagnostic,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--codex-model")
    parser.add_argument("--claude-model")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--cleanup-successful-projects", action="store_true")
    args = parser.parse_args()
    options = HostSmokeOptions(
        wheel=args.wheel,
        workspace=args.workspace,
        execute=args.execute,
        codex_model=args.codex_model,
        claude_model=args.claude_model,
    )
    plan = build_smoke_plan(options, environ=os.environ)
    plan.workspace.mkdir(parents=True, exist_ok=False)
    smoke_env = os.environ | {
        "UV_CACHE_DIR": str(plan.workspace / ".uv-cache"),
        "UV_FIND_LINKS": str(args.wheel.resolve().parent),
    }
    diagnostics: list[str] = []
    receipt: dict[str, object] = {
        "schema_version": 1,
        "release": {"wheel": args.wheel.name, "sha256": plan.release_sha256},
        "outcome": "running",
        "hosts": [],
        "diagnostics": diagnostics,
    }
    preparation_checkpoints: list[dict[str, object]] = []
    receipt["preparation_checkpoints"] = preparation_checkpoints
    receipt_path = plan.workspace / "smoke-receipt.json"
    try:
        for scenario in plan.scenarios:
            scenario.project.mkdir()
            (scenario.project / ".rob2-local-host-smoke").write_text(
                str(scenario.project.resolve()), encoding="utf-8"
            )
            _run_checked(
                ["uv", "venv", str(scenario.project / ".venv"), "--python", "3.13"],
                env=smoke_env,
                timeout_seconds=args.timeout_seconds,
                diagnostics=diagnostics,
            )
            trial = scenario.project / "input" / "smoke-trial"
            trial.mkdir(parents=True)
            (trial / "full-text.txt").write_text(
                """SMOKE randomized trial methods and results
Participants were randomly assigned 1:1 using a computer-generated sequence.
Allocation was concealed centrally. Baseline groups were balanced.
The prespecified outcome was all-cause mortality at 30 days. Follow-up was complete.
There were 10 deaths among 100 assigned intervention participants and 12 among 100 controls.
Analysis followed intention to treat and the prespecified analysis plan.
""",
                encoding="utf-8",
            )
        setup = zip(plan.install_commands, plan.adapter_commands, plan.doctor_commands, strict=True)
        verification = []
        for commands in setup:
            for command in commands:
                completed = _run_checked(
                    command,
                    env=smoke_env,
                    timeout_seconds=args.timeout_seconds,
                    diagnostics=diagnostics,
                )
                if command[1] in {"bootstrap", "doctor"}:
                    verification.append(json.loads(completed.stdout))
        doctor_receipts = [item for item in verification if "checks" in item]
        if len(doctor_receipts) != 2 or not all(item["ok"] for item in doctor_receipts):
            raise ValueError(
                "installed adapter, skill discovery, or MCP launch verification failed"
            )
        receipt["installed_verification"] = doctor_receipts
        receipt["adapter"] = doctor_receipts[0]["checks"]["host_adapters"]
        receipt["skills"] = doctor_receipts[0]["checks"]["canonical_skills"]
        receipt["mcp"] = doctor_receipts[0]["checks"]["mcp_launchability"]
        for index, command in enumerate(plan.host_commands):
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    cwd=plan.scenarios[index // 2].project,
                    text=True,
                    capture_output=True,
                    timeout=args.timeout_seconds,
                    check=False,
                    env=smoke_env,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                diagnostics.append(redact_diagnostic(str(error)))
                raise RuntimeError(diagnostics[-1]) from error
            host = command[0]
            stream_metadata = _metadata_from_stream(completed.stdout)
            entry = {
                "host": host,
                "model": stream_metadata.get("model")
                or (args.codex_model if host == "codex" else args.claude_model),
                "capabilities": ["skills", "mcp", "durable-resume"],
                "latency_seconds": round(time.monotonic() - started, 3),
                "outcome": "passed" if completed.returncode == 0 else "failed",
                "usage": stream_metadata.get("usage"),
                "diagnostic": redact_diagnostic(completed.stderr),
                "trace_excerpt": redact_diagnostic(completed.stdout),
            }
            receipt["hosts"].append(entry)  # type: ignore[union-attr]
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            if completed.returncode:
                raise SystemExit(f"{host} failed; inspect {receipt_path}")
            if index % 2 == 0:
                checkpoint = inspect_durable_outcome(plan.scenarios[index // 2].project)
                if checkpoint["run_state"] == "complete" or not checkpoint["next_actions"]:
                    raise ValueError(
                        "first host did not leave an incomplete resumable Preparation checkpoint"
                    )
                preparation_checkpoints.append(checkpoint)
        outcomes = [
            normalize_semantic_value(inspect_durable_outcome(scenario.project))
            for scenario in plan.scenarios
        ]
        if any(
            outcome["run_state"] != "complete" or outcome["next_actions"] or not outcome["reports"]
            for outcome in outcomes
        ):
            raise ValueError("resume host did not reach the complete report-ready checkpoint")
        receipt["semantic_outcomes"] = outcomes
        receipt["semantic_difference"] = compare_semantic_outcomes(*outcomes)
        if receipt["semantic_difference"]:
            raise ValueError("cross-host directions did not converge semantically")
        receipt["outcome"] = "passed"
        if args.cleanup_successful_projects:
            for scenario in plan.scenarios:
                cleanup_smoke_workspace(scenario.project, workspace=plan.workspace)
    except Exception as error:
        diagnostics.append(redact_diagnostic(str(error)))
        raise
    finally:
        if receipt["outcome"] == "running":
            receipt["outcome"] = "failed"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def _metadata_from_stream(stream: str) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("usage") is not None:
            metadata["usage"] = event["usage"]
        if isinstance(event, dict) and event.get("model") is not None:
            metadata["model"] = event["model"]
        if isinstance(event, dict) and event.get("total_cost_usd") is not None:
            metadata["usage"] = {
                "usage": metadata.get("usage"),
                "total_cost_usd": event["total_cost_usd"],
            }
    return metadata


def _run_checked(
    command: list[str] | tuple[str, ...],
    *,
    env: dict[str, str],
    timeout_seconds: int,
    diagnostics: list[str],
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        diagnostic = redact_diagnostic(str(error))
        diagnostics.append(diagnostic)
        raise RuntimeError(diagnostic) from error
    if completed.returncode:
        diagnostic = redact_diagnostic(completed.stderr)
        diagnostics.append(diagnostic)
        raise RuntimeError(diagnostic)
    return completed


if __name__ == "__main__":
    main()
