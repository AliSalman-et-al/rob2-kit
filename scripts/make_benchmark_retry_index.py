"""Create a retained replacement index for predeclared infrastructure failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark_contract import ATTEMPT_POLICY, infrastructure_failure_proven


def _key(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None
    outcome, trial = row.get("outcome"), row.get("trial")
    if not isinstance(outcome, str) or not isinstance(trial, str):
        return None
    def normalize(value: str) -> str:
        return "".join(c for c in value.casefold() if c.isalnum())

    return normalize(outcome), normalize(trial)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=int)
    args = parser.parse_args()

    index_path = args.index.resolve(strict=True)
    summary_path = args.summary.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite retry index directory: {output}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or index.get("attempt_policy") != ATTEMPT_POLICY:
        raise SystemExit("benchmark index lacks the predeclared infrastructure-only attempt policy")
    if not isinstance(summary, list):
        raise SystemExit("launcher summary must be a list")
    original_attempt = index.get("attempt", 1)
    if isinstance(original_attempt, bool) or not isinstance(original_attempt, int):
        raise SystemExit("benchmark index attempt number is malformed")
    attempt = args.attempt if args.attempt is not None else original_attempt + 1
    if attempt != original_attempt + 1 or attempt > ATTEMPT_POLICY["max_attempts"]:
        raise SystemExit("replacement attempt is outside the predeclared attempt policy")
    failed = {
        _key(row)
        for row in summary
        if isinstance(row, dict) and row.get("phase") == 1 and row.get("exit_code") != 0
    }
    rows = [
        row
        for row in index.get("cases", [])
        if _key(row) in failed
        and isinstance(row, dict)
        and infrastructure_failure_proven(index_path, row, summary_path)
    ]
    if not rows:
        raise SystemExit("no proven infrastructure-failed cases found in launcher summary")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    retry_root = output / "runs"
    rewritten: list[dict[str, Any]] = []
    for row in rows:
        rewritten_row = dict(row)
        rewritten_row["run_dir"] = str(
            retry_root / row["outcome"].lower().replace(" ", "-") / row["trial"]
        )
        rewritten_row["attempt"] = attempt
        rewritten.append(rewritten_row)
    result = dict(index)
    result["cases"] = rewritten
    result["attempt"] = attempt
    result["retry_of"] = str(index_path)
    result["retry_of_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    result["predecessor_failure_summary"] = str(summary_path)
    result["predecessor_failure_summary_sha256"] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(rewritten), "attempt": attempt}))


if __name__ == "__main__":
    main()
