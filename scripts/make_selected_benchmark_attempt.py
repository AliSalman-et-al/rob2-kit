"""Create a new retained index for selected, proven infrastructure failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark_contract import ATTEMPT_POLICY, infrastructure_failure_proven


def _key(value: str) -> tuple[str, str]:
    outcome, separator, trial = value.partition("=")
    if not separator or not outcome.strip() or not trial.strip():
        raise ValueError("each --case must be OUTCOME=TRIAL")
    def normalize(item: str) -> str:
        return "".join(c for c in item.casefold() if c.isalnum())

    return normalize(outcome), normalize(trial)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True, help="OUTCOME=TRIAL")
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    index_path = args.index.resolve(strict=True)
    summary_path = args.summary.resolve(strict=True) if args.summary else None
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite attempt index directory: {output}")
    selected = {_key(value) for value in args.case}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or index.get("attempt_policy") != ATTEMPT_POLICY:
        raise SystemExit("benchmark index lacks the predeclared infrastructure-only attempt policy")
    original_attempt = index.get("attempt", 1)
    if isinstance(original_attempt, bool) or not isinstance(original_attempt, int):
        raise SystemExit("benchmark index attempt number is malformed")
    if args.attempt != original_attempt + 1 or args.attempt > ATTEMPT_POLICY["max_attempts"]:
        raise SystemExit("replacement attempt is outside the predeclared attempt policy")
    rows = index.get("cases")
    if not isinstance(rows, list):
        raise SystemExit("benchmark index cases are malformed")
    matching = [row for row in rows if _row_key(row) in selected]
    if len(matching) != len(selected):
        raise SystemExit("one or more selected cases were not found in the index")
    if any(
        not isinstance(row, dict)
        or not infrastructure_failure_proven(index_path, row, summary_path)
        for row in matching
    ):
        raise SystemExit("selected case is not a proven infrastructure failure")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    run_root = output / "runs"
    rewritten: list[dict[str, Any]] = []
    for row in matching:
        rewritten_row = dict(row)
        rewritten_row["run_dir"] = str(
            run_root / row["outcome"].lower().replace(" ", "-") / row["trial"]
        )
        rewritten_row["attempt"] = args.attempt
        rewritten.append(rewritten_row)
    result = dict(index)
    result["cases"] = rewritten
    result["attempt"] = args.attempt
    result["retry_of"] = str(index_path)
    result["retry_of_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    if summary_path is not None:
        result["predecessor_failure_summary"] = str(summary_path)
        result["predecessor_failure_summary_sha256"] = hashlib.sha256(
            summary_path.read_bytes()
        ).hexdigest()
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(rewritten), "attempt": args.attempt}))


def _row_key(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None
    outcome, trial = row.get("outcome"), row.get("trial")
    if not isinstance(outcome, str) or not isinstance(trial, str):
        return None
    def normalize(value: str) -> str:
        return "".join(c for c in value.casefold() if c.isalnum())

    return normalize(outcome), normalize(trial)


if __name__ == "__main__":
    main()
