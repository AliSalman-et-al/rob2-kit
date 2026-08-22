"""Small command surface for the external #247 qualification runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manifest import CHAARTED_MANIFEST
from .trace import read_trace
from .verifier import verify_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a retained CHAARTED run artifact")
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--outcome", choices=("pfs", "overall_survival", "adverse_events"), required=True
    )
    parser.add_argument(
        "--trace",
        type=Path,
        required=True,
        help="external retained privacy-safe trace JSON",
    )
    args = parser.parse_args()
    try:
        trace = read_trace(args.trace)
    except ValueError as error:
        print(json.dumps({"ok": False, "failures": (str(error),), "facts_checked": ()}))
        raise SystemExit(1) from error
    result = verify_artifact(args.artifact, CHAARTED_MANIFEST, args.outcome, trace=trace)
    print(
        json.dumps(
            {"ok": result.ok, "failures": result.failures, "facts_checked": result.facts_checked}
        )
    )
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
