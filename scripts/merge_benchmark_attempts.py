"""Build one selected-attempt index from a main campaign and replacements."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--replacement", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index_path = args.index.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite selected index directory: {output}")
    merged = json.loads(index_path.read_text(encoding="utf-8"))
    replacements: dict[tuple[str, str], dict[str, object]] = {}
    for path in args.replacement:
        replacement = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
        for row in replacement["cases"]:
            replacements[(row["outcome"], row["trial"])] = row
    cases = []
    for row in merged["cases"]:
        cases.append(replacements.get((row["outcome"], row["trial"]), row))
    if len(cases) != len(merged["cases"]):
        raise SystemExit("selected index cardinality changed")
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    result = dict(merged)
    result["cases"] = cases
    result["selected_attempts"] = [
        str(index_path),
        *(str(path.resolve()) for path in args.replacement),
    ]
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(cases)}))


if __name__ == "__main__":
    main()
