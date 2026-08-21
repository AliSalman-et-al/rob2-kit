"""Small command surface for the external #247 qualification runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manifest import CHAARTED_MANIFEST
from .verifier import verify_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a retained CHAARTED run artifact")
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--outcome", choices=("pfs", "overall_survival", "adverse_events"), required=True
    )
    args = parser.parse_args()
    result = verify_artifact(args.artifact, CHAARTED_MANIFEST, args.outcome)
    print(
        json.dumps(
            {"ok": result.ok, "failures": result.failures, "facts_checked": result.facts_checked}
        )
    )
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
