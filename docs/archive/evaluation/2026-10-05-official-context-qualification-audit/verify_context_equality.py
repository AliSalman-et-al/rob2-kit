"""Reproduce unchanged-context hashes from retained private native MCP captures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def receipt(before: Path, after: Path) -> dict[str, object]:
    captures = [json.loads(path.read_bytes()) for path in (before, after)]
    assert captures[0].keys() == captures[1].keys()
    fields = ("result", "evidence", "response_framework", "guidance", "traps", "comparison_cards")
    domains = {}
    for domain in captures[0]:
        hashes = {}
        for field in fields:
            values = [capture[domain][field] for capture in captures]
            assert values[0] == values[1], (domain, field)
            hashes[field] = hashlib.sha256(
                json.dumps(
                    values[0], sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        domains[domain] = hashes
    return {
        "method": "Parsed JSON exact equality; field hashes use sorted compact UTF-8 JSON.",
        "raw_captures": [
            {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (before, after)
        ],
        "equal_fields_by_domain": domains,
        "limitation": (
            "Public field hashes bind private captures; reproduction requires those captures. "
            "Published scientific snapshots omit Result/Evidence."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    print(json.dumps(receipt(args.before, args.after), indent=2))
