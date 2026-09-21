"""Select fresh cases whose first Codex turn ended before a Proposal Review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", type=int, default=2)
    args = parser.parse_args()
    index_path = args.index.resolve(strict=True)
    review_root = args.reviews.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite continuation index directory: {output}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    pending = []
    for item in index["cases"]:
        path = review_root / item["outcome"].lower().replace(" ", "-") / f"{item['trial']}.json"
        review = json.loads(path.read_text(encoding="utf-8"))
        candidate = review.get("candidate")
        proposal = candidate.get("proposal") if isinstance(candidate, dict) else None
        if not proposal:
            pending.append(dict(item))
    if not pending:
        raise SystemExit("all cases already have a Proposal Review")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    result = dict(index)
    result["cases"] = pending
    result["continuation_of"] = str(index_path)
    result["phase"] = args.phase
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(pending), "phase": args.phase}))


if __name__ == "__main__":
    main()
