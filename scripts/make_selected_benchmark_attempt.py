"""Create a new retained attempt index for selected infrastructure failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True, help="OUTCOME=TRIAL")
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    index_path = args.index.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite attempt index directory: {output}")
    selected = {tuple(value.split("=", 1)) for value in args.case}
    if any(len(value) != 2 for value in selected):
        raise SystemExit("each --case must be OUTCOME=TRIAL")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows = [row for row in index["cases"] if (row["outcome"], row["trial"]) in selected]
    if len(rows) != len(selected):
        raise SystemExit("one or more selected cases were not found in the index")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    run_root = output / "runs"
    rewritten = []
    for row in rows:
        row = dict(row)
        row["run_dir"] = str(run_root / row["outcome"].lower().replace(" ", "-") / row["trial"])
        row["attempt"] = str(args.attempt)
        rewritten.append(row)
    result = dict(index)
    result["cases"] = rewritten
    result["attempt"] = args.attempt
    result["retry_of"] = str(index_path)
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(rewritten), "attempt": args.attempt}))


if __name__ == "__main__":
    main()
