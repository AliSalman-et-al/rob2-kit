#!/usr/bin/env python3
"""Capture a reproducible cold/warm/restart search-work artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rob2_kit.application._state import _SEARCH_DERIVATIVE_VERSION, _SEARCH_PROFILE, _db
from rob2_kit.application.contracts import COUNTERS, counter_snapshot, reset_counters
from rob2_kit.application.evidence import render_page, reset_search_caches, search_sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--source-id")
    parser.add_argument("--render-page", type=int)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.render_page is not None and args.source_id is None:
        parser.error("--render-page requires --source-id")

    reset_search_caches()
    reset_counters()
    phases: list[dict[str, object]] = []
    observed_profile: str | None = None

    def candidate_rows() -> int:
        with _db(args.workspace, "derivative.sqlite3") as connection:
            return int(connection.execute("SELECT COUNT(*) FROM search_candidates").fetchone()[0])

    def measure(name: str, query: str, mode: str = "any") -> None:
        nonlocal observed_profile
        candidates_before = candidate_rows()
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
        candidates_after = candidate_rows()
        phases.append(
            {
                "phase": name,
                "query": query,
                "mode": mode,
                "receipt_identity": result["search_receipt"]["identity"],
                "returned_candidates": result["search_receipt"]["returned_candidates"],
                "passage_refs": [hit["passage_ref"] for hit in result["hits"]],
                "candidate_rows_before": candidates_before,
                "candidate_rows_after": candidates_after,
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
    render_phases: list[dict[str, object]] = []
    if args.render_page is not None and args.source_id is not None:
        for name in ("first_render", "repeat_render"):
            before = counter_snapshot()
            result = render_page(args.workspace, args.trial, args.source_id, args.render_page)
            after = counter_snapshot()
            render_phases.append(
                {
                    "phase": name,
                    "page": args.render_page,
                    "render_identity": result["render"]["identity"],
                    "png_byte_length": len(result["_png_bytes"]),
                    "before": before,
                    "after": after,
                    "delta": {
                        key: after[key] - before[key]
                        for key in after
                        if isinstance(after[key], (int, float))
                        and isinstance(before[key], (int, float))
                    },
                }
            )
    cold, warm, restart = phases[:2] + [phases[-1]]
    artifact = {
        "schema": "rob2-kit.search-cache-benchmark.v2",
        "workspace_scope": "caller_supplied",
        "trial_id": args.trial,
        "source_id": args.source_id,
        "profile": observed_profile or _SEARCH_PROFILE,
        "derivative_version": _SEARCH_DERIVATIVE_VERSION,
        "queries": len(args.query),
        "candidate_locators_stable": (
            cold["returned_candidates"] == warm["returned_candidates"]
            and cold["returned_candidates"] == restart["returned_candidates"]
            and cold["passage_refs"] == warm["passage_refs"] == restart["passage_refs"]
        ),
        "phases": phases,
        "render_phases": render_phases,
    }
    args.output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(phases)} search-cache measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
