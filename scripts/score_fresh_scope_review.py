#!/usr/bin/env python3
"""Re-score the retained 27 September campaign with its pending safety-scope review."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from score_trial_benchmark import render_markdown, score

REVIEWED_ADJUDICATION_SHA256 = "cb88cb6599ff3e205e6bf8823a43f60b9647d89085786223d3d98f5a9e321f50"
FROZEN_MANIFEST_SHA256 = "716601e15b8bfa4f220aa90d922ba3c1456d189a4e862d0a66ecd3d6be7f5acc"


def public_case(case: dict) -> dict:
    adjudication = case.get("scope_adjudication")
    return {
        key: case.get(key)
        for key in (
            "outcome",
            "trial",
            "primary_status",
            "proposal_relation",
            "result_scope",
            "correspondence",
            "expected",
            "observed",
        )
    } | {
        "differing_facets": (case.get("result_scope_details") or {}).get("differing_facets", []),
        "review_required": bool(case.get("scope_review_required")),
        "review_reason": case.get("scope_review_required"),
        "adjudication": (
            {
                key: adjudication.get(key)
                for key in (
                    "decision",
                    "expected_result_sha256",
                    "review_identity",
                    "result_identity",
                    "rationale",
                    "source_citation",
                )
            }
            if isinstance(adjudication, dict)
            else None
        ),
    }


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    campaign = repo / "eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798"
    source_path = campaign / "scoring-manifest.json"
    if sha256(source_path.read_bytes()).hexdigest() != FROZEN_MANIFEST_SHA256:
        raise ValueError("frozen scoring manifest changed; review before rebuilding")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    rows = []
    for original in source["rows"]:
        suffix = original["run_dir"].replace("\\", "/").split(f"{campaign.name}/", 1)[1]
        row = {
            key: original[key]
            for key in ("outcome", "trial", "primary_status", "role", "expected_result")
        }
        row["run_dir"] = (campaign / suffix).relative_to(repo).as_posix()
        if (row["outcome"], row["trial"]) == ("Adverse Events", "ARASENS"):
            row["scope_review_required"] = (
                "The approved safety Result uses treatment-received group membership, "
                "including a participant assigned to placebo who received darolutamide. "
                "The existing generic equivalence rationale does not address this grouping "
                "facet; obtain a separate source-grounded decision before including this case "
                "in the primary score."
            )
        rows.append(row)
    if len(rows) != 26 or sum("scope_review_required" in row for row in rows) != 1:
        raise ValueError("the frozen campaign or pending review set changed")

    manifest = {
        "schema": source["schema"],
        "model": source["model"],
        "reasoning_effort": source["reasoning_effort"],
        "rows": rows,
    }
    manifest_path = campaign / "supplemental-scope-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    adjudication_path = campaign / "selected-attempts-scope-adjudications.json"
    if sha256(adjudication_path.read_bytes()).hexdigest() != REVIEWED_ADJUDICATION_SHA256:
        raise ValueError("scope adjudications changed; review before publishing rationale")
    result = score(
        manifest_path,
        repo / "eval/reference",
        adjudication_path,
    )
    if result["hard_failures"] or result["scope"]["finalized_scored_cases"] != 25:
        raise ValueError("supplemental score did not reconcile 25 primary cases")
    (campaign / "supplemental-scope-score.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = repo / "docs/evaluation/2026-09-27-result-scope-report.md"
    report.write_text(
        render_markdown(result, publish_adjudication_details=True)
        + "\nA sanitized [case-level machine summary](2026-09-27-result-scope-score.json) "
        "is published beside this report. Rebuild both with "
        "`python scripts/score_fresh_scope_review.py`.\n",
        encoding="utf-8",
    )
    public_result = {
        "schema": "rob2-kit.trial-benchmark-public-scope-score.v1",
        "source_schema": result["schema"],
        "source_manifest_sha256": FROZEN_MANIFEST_SHA256,
        "adjudication_sha256": REVIEWED_ADJUDICATION_SHA256,
        "scope": result["scope"],
        "pooled": result["pooled"],
        "cases": [public_case(case) for case in result["cases"]],
        "scope_difference_cases": [public_case(case) for case in result["scope_difference_cases"]],
        "review_required_cases": [public_case(case) for case in result["review_required_cases"]],
    }
    report.with_name("2026-09-27-result-scope-score.json").write_text(
        json.dumps(public_result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["scope"], sort_keys=True))


if __name__ == "__main__":
    main()
