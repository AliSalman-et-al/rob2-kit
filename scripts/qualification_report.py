#!/usr/bin/env python3
"""Validate an integrated, privacy-safe qualification report.

The report is a deterministic receipt for an externally executed campaign;
this command does not launch a model or provide a second scientific authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rob2_kit.evaluation.qualification_report import (
    HISTORICAL_QUALIFICATION_SCHEMA,
    QUALIFICATION_SCHEMA,
    promotion_decision,
    validate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2
    errors = validate(report)
    if errors:
        print("qualification report rejected: " + "; ".join(errors), file=sys.stderr)
        return 1
    decision = promotion_decision(report)
    if report["schema"] == QUALIFICATION_SCHEMA:
        print(
            "qualification report validated; "
            f"{decision} (bounded engineering claim; "
            "not adjudicated scientific accuracy)"
        )
    elif report["schema"] == HISTORICAL_QUALIFICATION_SCHEMA:
        print("historical qualification report validated; hold for the integrated v3 gate")
    else:
        print(f"qualification report validated; {decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
