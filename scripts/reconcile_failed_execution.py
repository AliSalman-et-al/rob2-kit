#!/usr/bin/env python3
"""Write one validated completion reconciliation sidecar for a failed execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from benchmark_contract import (  # noqa: E402
    COMPLETION_RECONCILIATION_FILENAME,
    build_completion_reconciliation_sidecar,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve(strict=True)
    payload = build_completion_reconciliation_sidecar(run_dir, args.phase)
    sidecar_path = run_dir / COMPLETION_RECONCILIATION_FILENAME
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        with sidecar_path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(encoded)
    except FileExistsError as error:
        raise SystemExit(f"refusing to replace existing sidecar: {sidecar_path}") from error
    print(sidecar_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
