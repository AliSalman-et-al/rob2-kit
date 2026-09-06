#!/usr/bin/env python3
"""Run the privacy-safe deterministic held-out evaluation scorer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rob2_kit.evaluation import evaluate_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = evaluate_fixture(fixture)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
