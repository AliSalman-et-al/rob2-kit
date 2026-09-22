"""Run one fresh benchmark phase for every case in bounded parallel waves."""

from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _session_id(run_dir: Path, phase: int) -> str:
    execution_path = run_dir / "execution.json"
    record = json.loads(execution_path.read_text(encoding="utf-8"))
    value = record.get("codex_session_id")
    if isinstance(value, str) and value:
        return value
    for prior_phase in range(phase - 1, 0, -1):
        trace = run_dir / f"phase-{prior_phase}.jsonl"
        if not trace.is_file():
            continue
        for line in reversed(trace.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("thread.started", "session_id", "thread_id"):
                if event.get("type") == key and isinstance(event.get("session_id"), str):
                    return event["session_id"]
            item = event.get("item")
            if isinstance(item, dict) and isinstance(item.get("session_id"), str):
                return item["session_id"]
        
    raise RuntimeError(f"no Codex session found in {execution_path}")


def _run_one(repo: Path, item: dict[str, Any], phase: int, prompt: Path) -> dict[str, Any]:
    run_dir = Path(item["run_dir"])
    prompt_path = Path(item["prompt"]) if phase == 1 else prompt
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
        "gpt-5.6-luna",
        "--effort",
        "medium",
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
    args = parser.parse_args()
    if args.phase < 1 or args.workers < 1:
        raise SystemExit("--phase must be positive and --workers must be at least one")
    repo = Path(__file__).resolve().parents[1]
    index = json.loads(args.index.resolve(strict=True).read_text(encoding="utf-8"))
    prompt = (args.prompt or args.index.resolve().parent / "continuation.txt").resolve(strict=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run_one, repo, item, args.phase, prompt) for item in index["cases"]]
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
