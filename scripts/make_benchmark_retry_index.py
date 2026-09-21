"""Create a retained infrastructure-retry index for failed phase-1 launches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=int, default=2)
    args = parser.parse_args()

    index_path = args.index.resolve(strict=True)
    summary_path = args.summary.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite retry index directory: {output}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    failed = {(row["outcome"], row["trial"]) for row in summary if row["exit_code"] != 0}
    rows = [row for row in index["cases"] if (row["outcome"], row["trial"]) in failed]
    if not rows:
        raise SystemExit("no failed cases found in launcher summary")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    retry_root = output / "runs"
    rewritten = []
    for row in rows:
        row = dict(row)
        row["run_dir"] = str(retry_root / row["outcome"].lower().replace(" ", "-") / row["trial"])
        row["attempt"] = str(args.attempt)
        rewritten.append(row)
    result = dict(index)
    result["cases"] = rewritten
    result["retry_of"] = str(index_path)
    result["attempt"] = args.attempt
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(rewritten), "attempt": args.attempt}))


if __name__ == "__main__":
    main()
