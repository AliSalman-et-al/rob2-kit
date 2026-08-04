"""Explicit local acceptance helper for public normalized-trace goldens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rob2_kit.evaluation import accept_golden, normalize_trace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="rewrite the golden after displaying the semantic diff",
    )
    args = parser.parse_args()
    trace = normalize_trace(json.loads(args.trace.read_text(encoding="utf-8")))
    try:
        differences = accept_golden(args.golden, trace, accept=args.accept)
    except RuntimeError as error:
        print(error)
        raise SystemExit(2) from error
    if differences:
        print("\n".join(differences))
    else:
        print("golden is semantically unchanged")


if __name__ == "__main__":
    main()
