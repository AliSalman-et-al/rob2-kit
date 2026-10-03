"""Run one already-prepared isolated Luna Medium Domain probe; never retry it."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

from domain_probe_controls import ProbeLimits, guard_stop, load_controls, rejection_fingerprint

_REPO = Path(__file__).resolve().parents[1]


def preflight(root: Path) -> tuple[dict[str, Any], ProbeLimits, str]:
    manifest, limits, prompt = load_controls(root)
    config = tomllib.loads((root / "home/config.toml").read_text())
    if (manifest.get("model"), manifest.get("reasoning_effort")) != ("gpt-6-luna", "medium"):
        raise ValueError("probe manifest must use exact gpt-6-luna / medium")
    if (config.get("model"), config.get("model_reasoning_effort")) != ("gpt-6-luna", "medium"):
        raise ValueError("CLI model configuration differs from the manifest")
    if manifest.get("no_invocation_retry") is not True or (root / "run.json").exists():
        raise ValueError("probe requires a fresh one-invocation run directory")
    if list((root / "home/sessions").rglob("*.jsonl")):
        raise ValueError("probe home already contains a rollout; do not resume or retry it")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_REPO, text=True).strip()
    if sha != manifest.get("code_sha") or subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=_REPO
    ):
        raise ValueError("probe runtime must match the frozen clean checkout")
    return manifest, limits, prompt


def probe_command(root: Path) -> list[str]:
    """Keep rob2 tools direct: no generated ALL_TOOLS catalog or exec output clipping."""
    return [
        "codex",
        "exec",
        "--strict-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-m",
        "gpt-6-luna",
        "-c",
        'model_reasoning_effort="medium"',
        "-c",
        'features.code_mode={enabled=true,direct_only_tool_namespaces=["mcp__rob2"]}',
        "--json",
        "-o",
        str(root / "response.txt"),
        "-",
    ]


def run(root: Path) -> None:
    manifest, limits, prompt = preflight(root)
    env = {**os.environ, "CODEX_HOME": str(root / "home")}
    command = probe_command(root)
    records: dict[str, dict[str, Any]] = {}
    code_calls = code_completed = mcp_calls = mcp_completed = rejections = saves = 0
    accepted = None
    saves_completed = identical_rejections = 0
    previous_rejection = None
    rejection_records: list[dict[str, Any]] = []
    start = last = time.monotonic()
    reason = None
    usage: dict[str, int] = {}

    def read_usage() -> None:
        nonlocal usage, code_calls, code_completed
        paths = list((root / "home/sessions").rglob("*.jsonl"))
        if len(paths) > 1:
            raise ValueError("isolated probe home contains multiple rollouts")
        if not paths:
            return
        code_calls = code_completed = 0
        for line in paths[0].read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # The writer may still be completing the final line.
            payload = row.get("payload", {})
            if row.get("type") == "token_usage_record":
                records[payload["response_id"]] = {"timestamp": row.get("timestamp"), **payload}
            if row.get("type") == "response_item" and payload.get("type") == "custom_tool_call":
                code_calls += 1
            if (
                row.get("type") == "response_item"
                and payload.get("type") == "custom_tool_call_output"
            ):
                code_completed += 1
        usage = {
            key: sum(record["usage"].get(key, 0) for record in records.values())
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        }
        (root / "durable-token-usage-records.json").write_text(
            json.dumps(list(records.values()), indent=2) + "\n"
        )

    def consume(raw: bytes) -> None:
        nonlocal last, mcp_calls, mcp_completed, saves, rejections, reason, accepted
        nonlocal saves_completed, identical_rejections, previous_rejection
        log.write(raw)
        log.flush()
        event = json.loads(raw)
        last = time.monotonic()
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call":
            if event.get("type") == "item.started":
                mcp_calls += 1
                saves += item.get("tool") == "save_domain_judgment"
            if event.get("type") == "item.completed":
                mcp_completed += 1
                if item.get("tool") == "save_domain_judgment":
                    saves_completed += 1
                    result = (item.get("result") or {}).get("structured_content") or {}
                    if result.get("outcome") == "success":
                        accepted = result
                        reason = reason or "accepted Domain checkpoint"
                    else:
                        rejections += 1
                        fingerprint = rejection_fingerprint(item.get("result") or {})
                        identical_rejections = (
                            identical_rejections + 1 if fingerprint == previous_rejection else 1
                        )
                        previous_rejection = fingerprint
                        rejection_records.append(
                            {
                                "save_attempt": saves_completed,
                                "fingerprint": fingerprint,
                                "consecutive_identical": identical_rejections,
                                "result": item.get("result"),
                            }
                        )
        if item.get("type") == "command_execution":
            reason = reason or "unapproved shell access"

    with (root / "stderr.log").open("wb") as err, (root / "events.jsonl").open("wb") as log:
        proc = subprocess.Popen(
            command,
            cwd=root / "workspace",
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            start_new_session=True,
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(prompt.encode())
        proc.stdin.close()
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            while proc.poll() is None:
                for key, _ in sel.select(1):
                    raw = proc.stdout.readline()
                    if not raw:
                        continue
                    consume(raw)
                read_usage()
                if max(code_calls, mcp_calls) > limits.tool_calls:
                    reason = reason or "tool-start limit exceeded"
                if saves > limits.save_attempts:
                    reason = reason or "save-start limit exceeded"
                reason = reason or guard_stop(
                    limits,
                    usage,
                    tools=max(code_completed, mcp_completed),
                    saves=saves_completed,
                    identical_rejections=identical_rejections,
                    wall_seconds=time.monotonic() - start,
                    idle_seconds=time.monotonic() - last,
                )
                if reason:
                    break
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            for raw in proc.stdout:
                consume(raw)
            read_usage()
            sel.close()
    (root / "run.json").write_text(
        json.dumps(
            {
                "code_sha": manifest["code_sha"],
                "guard_identity": limits.identity(),
                "guards": limits.model_dump(),
                "command": command,
                "stop_reason": reason,
                "exit_code": proc.returncode,
                "elapsed_seconds": time.monotonic() - start,
                "model_code_calls": code_calls,
                "mcp_calls": mcp_calls,
                "save_calls": saves,
                "model_code_calls_completed": code_completed,
                "mcp_calls_completed": mcp_completed,
                "accepted_checkpoint": accepted,
                "rejections": rejections,
                "save_calls_completed": saves_completed,
                "rejection_records": rejection_records,
                "consecutive_identical_rejections": identical_rejections,
                "usage": usage,
                "uncached_input_tokens": usage.get("input_tokens", 0)
                - usage.get("cached_input_tokens", 0),
                "input_overshoot": max(0, usage.get("input_tokens", 0) - limits.input_tokens),
                "uncached_input_overshoot": max(
                    0,
                    usage.get("input_tokens", 0)
                    - usage.get("cached_input_tokens", 0)
                    - limits.uncached_input_tokens,
                ),
                "output_overshoot": max(0, usage.get("output_tokens", 0) - limits.output_tokens),
                "tool_start_overshoot": max(0, max(code_calls, mcp_calls) - limits.tool_calls),
                "save_start_overshoot": max(0, saves - limits.save_attempts),
                "no_invocation_retry": True,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        preflight(args.root.resolve())
    else:
        run(args.root.resolve())
