#!/usr/bin/env python3
"""Capture a reproducible cold/warm/restart search-work artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rob2_kit.application._state import _SEARCH_DERIVATIVE_VERSION, _SEARCH_PROFILE
from rob2_kit.application.contracts import COUNTERS, counter_snapshot, reset_counters
from rob2_kit.application.evidence import reset_search_caches, search_sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--source-id")
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reset_search_caches()
    reset_counters()
    phases: list[dict[str, object]] = []
    observed_profile: str | None = None

    def measure(name: str, query: str, mode: str = "any") -> None:
        nonlocal observed_profile
        before = counter_snapshot()
        result = search_sources(
            args.workspace,
            args.trial,
            query,
            mode=mode,
            source_id=args.source_id,
        )
        if isinstance(result.get("profile"), str):
            observed_profile = result["profile"]
        COUNTERS["response_bytes"] += len(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        )
        after = counter_snapshot()
        phases.append(
            {
                "phase": name,
                "query": query,
                "mode": mode,
                "receipt_identity": result["search_receipt"]["identity"],
                "before": before,
                "after": after,
                "counters": after,
                "delta": {
                    key: after[key] - before[key]
                    for key in after
                    if isinstance(after[key], (int, float))
                    and isinstance(before[key], (int, float))
                },
            }
        )

    measure("cold", args.query[0])
    measure("warm_exact_repeat", args.query[0])
    for index, query in enumerate(args.query[1:], 1):
        measure(f"warm_new_query_{index}", query)
    reset_search_caches()
    measure("restart_durable_reuse", args.query[0])
    artifact = {
        "schema": "rob2-kit.search-cache-benchmark.v1",
        "workspace_scope": "caller_supplied",
        "trial_id": args.trial,
        "source_id": args.source_id,
        "profile": observed_profile or _SEARCH_PROFILE,
        "derivative_version": _SEARCH_DERIVATIVE_VERSION,
        "queries": len(args.query),
        "phases": phases,
    }
    args.output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(phases)} search-cache measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
