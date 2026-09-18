#!/usr/bin/env python3
"""Retain and score a predeclared privacy-safe comparison run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rob2_kit.evaluation import run_comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--interventions", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    interventions = json.loads(args.interventions.read_text(encoding="utf-8"))
    outcomes = json.loads(args.outcomes.read_text(encoding="utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels else None
    result = run_comparison(config, interventions, outcomes, labels)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"retained {result['retained_outcome_count']} comparison outcomes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
