"""Reject platform-qualified candidates whose canonical release outputs differ."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_PLATFORMS = {"linux", "darwin", "win32"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipts", type=Path)
    arguments = parser.parse_args()
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in arguments.receipts.glob("**/release-qualification.json")
    ]
    platforms = {receipt["platform"] for receipt in receipts}
    if platforms != EXPECTED_PLATFORMS:
        raise SystemExit(
            f"expected one receipt for {sorted(EXPECTED_PLATFORMS)}, got {sorted(platforms)}"
        )
    if len(receipts) != len(platforms):
        raise SystemExit("expected exactly one qualification receipt per platform")
    expected = receipts[0]["journey"]
    for receipt in receipts:
        if receipt["python"] != "3.13":
            raise SystemExit(f"{receipt['platform']} did not use Python 3.13")
        if receipt["journey"] != expected:
            raise SystemExit(
                "canonical report, manifest, or normalized ledger receipt differs on "
                f"{receipt['platform']}"
            )
        if not all(receipt["doctor"].values()):
            raise SystemExit(f"doctor qualification was incomplete on {receipt['platform']}")
        telemetry = receipt["telemetry"]
        if telemetry["non_loopback_outbound_attempts"] != []:
            raise SystemExit(f"telemetry guard observed outbound traffic on {receipt['platform']}")
        if not telemetry["normalized_attempts_hash"].startswith("sha256:"):
            raise SystemExit(f"telemetry guard hash was missing on {receipt['platform']}")
        if receipt["owner_evaluation"]["status"] != "external_required":
            raise SystemExit("owner-evaluation receipt must not be fabricated by CI")
    print("frozen-wheel qualification receipts match across all supported platforms")


if __name__ == "__main__":
    main()
