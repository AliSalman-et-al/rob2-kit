#!/usr/bin/env python3
"""Validate an integrated, privacy-safe qualification report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rob2_kit.evaluation.qualification_report import validate


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
    print(f"qualification report validated; {report['promotion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
