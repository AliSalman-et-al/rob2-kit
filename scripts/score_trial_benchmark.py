#!/usr/bin/env python3
"""Score finalized trial-specific benchmark bundles against frozen catalog labels."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

DOMAINS = ("D1", "D2", "D3", "D4", "D5")
DOMAIN_KEYS = {
    "D1": "domain:randomization",
    "D2": "domain:deviations",
    "D3": "domain:missing",
    "D4": "domain:measurement",
    "D5": "domain:selection",
}
OUTCOME_FILES = {
    "Overall Survival": "overall-survival.csv",
    "Progression-Free Survival": "progression-free-survival.csv",
    "Adverse Events": "adverse-events.csv",
}
LABELS = {"L": "low", "S": "some_concerns", "H": "high"}
LABEL_NAMES = {
    "low": "Low",
    "some_concerns": "Some Concerns",
    "high": "High",
}


def _load_reference(reference_root: Path) -> dict[tuple[str, str], dict[str, str]]:
    labels: dict[tuple[str, str], dict[str, str]] = {}
    trial_aliases: dict[str, set[str]] = defaultdict(set)
    trials_path = reference_root / "catalog" / "trials.csv"
    if trials_path.exists():
        with trials_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                display = (row.get("trial_label") or row.get("trial") or "").strip()
                slug = (row.get("trial_slug") or row.get("slug") or "").strip()
                if display and slug:
                    trial_aliases[display].add(slug)
                    trial_aliases[slug].add(display)
    for outcome, filename in OUTCOME_FILES.items():
        with (reference_root / "catalog" / "provisional-labels" / filename).open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                trial = (row.get("Trial") or "").strip()
                if not trial:
                    continue
                values = {domain: LABELS[row[domain].strip()] for domain in DOMAINS}
                overall = (row.get("Overall Risk") or "").strip()
                values["overall"] = {
                    "Low": "low",
                    "Some Concerns": "some_concerns",
                    "High": "high",
                }.get(overall, "")
                if not values["overall"]:
                    raise ValueError(f"unsupported overall label {overall!r} for {outcome}/{trial}")
                labels[(outcome, trial)] = values
                for alias in trial_aliases.get(trial, ()):
                    labels[(outcome, alias)] = values
    return labels


def _bundle_snapshot(run_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    execution_path = run_dir / "execution.json"
    if not execution_path.exists():
        return None, "missing execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if execution.get("state") != "succeeded":
        phases = execution.get("phases") or []
        last_phase = phases[-1] if phases else {}
        state = execution.get("state", "unknown")
        detail = last_phase.get("state") if isinstance(last_phase, dict) else None
        return None, f"execution state={state}" + (f", last phase={detail}" if detail else "")
    bundles = sorted(run_dir.rglob("*.rob2.zip"))
    if len(bundles) != 1:
        return None, f"expected one verified bundle, found {len(bundles)}"
    with zipfile.ZipFile(bundles[0]) as archive:
        verification = json.loads(archive.read("verification.json"))
        if verification.get("result") != "verified":
            return None, "bundle verification did not report verified"
        canonical = json.loads(archive.read("canonical.json"))
    snapshots = canonical.get("snapshots")
    if not isinstance(snapshots, dict) or len(snapshots) != 1:
        return None, "canonical snapshot is missing or not singular"
    snapshot = next(iter(snapshots.values()))
    if not isinstance(snapshot, dict):
        return None, "canonical snapshot is not an object"
    judgments = snapshot.get("domain_judgments")
    if not isinstance(judgments, dict):
        return None, "canonical domain_judgments is missing"
    observed = {}
    for domain, key in DOMAIN_KEYS.items():
        label = judgments.get(key)
        if label not in {"low", "some_concerns", "high"}:
            return None, f"canonical label for {domain} is invalid: {label!r}"
        observed[domain] = label
    overall = snapshot.get("overall")
    if overall not in {"low", "some_concerns", "high"}:
        return None, f"canonical overall label is invalid: {overall!r}"
    observed["overall"] = overall
    return {"observed": observed, "bundle": str(bundles[0])}, None


def _rate(correct: int, total: int) -> dict[str, Any]:
    return {"correct": correct, "total": total, "rate": correct / total if total else None}


def _score(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    exact = sum(row["expected"][key] == row["observed"][key] for row in rows)
    binary = sum(
        (row["expected"][key] == "low") == (row["observed"][key] == "low") for row in rows
    )
    return {"exact": _rate(exact, len(rows)), "low_vs_non_low": _rate(binary, len(rows))}


def _group(rows: list[dict[str, Any]], *, include_overall: bool = False) -> dict[str, Any]:
    return {
        "case_count": len(rows),
        "domain_cells": len(rows) * len(DOMAINS),
        "domains": {key: _score(rows, key) for key in DOMAINS},
        "pooled_domains": {
            metric: _rate(
                sum(
                    (row["expected"][domain] == row["observed"][domain])
                    if metric == "exact"
                    else ((row["expected"][domain] == "low") == (row["observed"][domain] == "low"))
                    for row in rows
                    for domain in DOMAINS
                ),
                len(rows) * len(DOMAINS),
            )
            for metric in ("exact", "low_vs_non_low")
        },
        **({"overall": _score(rows, "overall")} if include_overall else {}),
    }


def score(manifest_path: Path, reference_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise ValueError("manifest rows must be a list")
    references = _load_reference(reference_root)
    scored: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in rows:
        outcome = item.get("outcome")
        trial = item.get("trial")
        if (outcome, trial) not in references:
            excluded.append(
                {"outcome": outcome, "trial": trial, "reason": "reference label unavailable"}
            )
            continue
        run_dir = Path(item["run_dir"])
        bundle, reason = _bundle_snapshot(run_dir)
        if bundle is None:
            excluded.append(
                {
                    "outcome": outcome,
                    "trial": trial,
                    "primary_status": item.get("primary_status"),
                    "reason": reason,
                }
            )
            continue
        expected = references[(outcome, trial)]
        scored.append(
            {
                "outcome": outcome,
                "trial": trial,
                "primary_status": item.get("primary_status"),
                "role": item.get("role"),
                "expected": expected,
                "observed": bundle["observed"],
                "bundle": bundle["bundle"],
            }
        )

    by_outcome = {
        outcome: _group([row for row in scored if row["outcome"] == outcome], include_overall=True)
        for outcome in sorted({row["outcome"] for row in scored})
    }
    by_domain = {domain: _score(scored, domain) for domain in DOMAINS}
    by_role = {
        role: _group([row for row in scored if row["primary_status"] == role], include_overall=True)
        for role in ("primary", "secondary")
    }
    by_outcome_domain = {
        outcome: {
            domain: _score(
                [row for row in scored if row["outcome"] == outcome], domain
            )
            for domain in DOMAINS
        }
        for outcome in sorted({row["outcome"] for row in scored})
    }
    return {
        "schema": "rob2-kit.trial-benchmark-score.v1",
        "manifest": str(manifest_path),
        "model": manifest.get("model"),
        "reasoning_effort": manifest.get("reasoning_effort", manifest.get("effort")),
        "prompt_policy": manifest.get("prompt_policy"),
        "label_interpretation": (
            "agreement with frozen provisional catalog labels; "
            "not adjudicated scientific accuracy"
        ),
        "scope": {
            "manifest_rows": len(rows),
            "finalized_scored_cases": len(scored),
            "finalized_domain_cells": len(scored) * len(DOMAINS),
            "excluded_cases": len(excluded),
        },
        "pooled": _group(scored, include_overall=True),
        "by_outcome": by_outcome,
        "by_domain": by_domain,
        "by_outcome_domain": by_outcome_domain,
        "by_primary_status": by_role,
        "excluded": excluded,
        "cases": scored,
    }


def _metric_text(metric: dict[str, Any]) -> str:
    rate = metric["rate"]
    percentage = "n/a" if rate is None else f"{rate:.1%}"
    return f"{metric['correct']}/{metric['total']} ({percentage})"


def render_markdown(result: dict[str, Any]) -> str:
    """Render a short reference report from the machine-readable score."""
    pooled = result["pooled"]
    lines = [
        "# Trial-specific rob2-kit benchmark",
        "",
        (
            "This report measures agreement with the frozen provisional catalog labels. "
            "It is not an adjudicated estimate of scientific accuracy."
        ),
        "",
        f"- Model: `{result.get('model')}` with `{result.get('reasoning_effort')}` reasoning.",
        (
            f"- Manifest rows: {result['scope']['manifest_rows']} abstract-eligible "
            "outcome/trial cases."
        ),
        (
            f"- Finalized scored cases: {result['scope']['finalized_scored_cases']} "
            f"({result['scope']['finalized_domain_cells']} domain cells)."
        ),
        f"- Excluded after execution: {result['scope']['excluded_cases']}.",
        (
            "- Exact scoring compares Low, Some Concerns, and High. Binary scoring maps "
            "Some Concerns and High to Non-Low."
        ),
        (
            "- The frozen catalog contains no reference High labels, so High sensitivity "
            "is not estimable from this cohort."
        ),
        "",
        "## Pooled result",
        "",
        "| Measure | Exact | Low vs Non-Low |",
        "|---|---:|---:|",
        (
            f"| Five domains ({pooled['domain_cells']} cells) | "
            f"{_metric_text(pooled['pooled_domains']['exact'])} | "
            f"{_metric_text(pooled['pooled_domains']['low_vs_non_low'])} |"
        ),
        (
            f"| Overall final label ({pooled['case_count']} cases) | "
            f"{_metric_text(pooled['overall']['exact'])} | "
            f"{_metric_text(pooled['overall']['low_vs_non_low'])} |"
        ),
        "",
        "## Accuracy by outcome",
        "",
            "| Outcome | Cases | Domains exact | Domains Low vs Non-Low | "
            "Overall exact | Overall Low vs Non-Low |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for outcome in ("Overall Survival", "Progression-Free Survival", "Adverse Events"):
        group = result["by_outcome"].get(outcome)
        if group:
            lines.append(
                f"| {outcome} | {group['case_count']} | "
                f"{_metric_text(group['pooled_domains']['exact'])} | "
                f"{_metric_text(group['pooled_domains']['low_vs_non_low'])} | "
                f"{_metric_text(group['overall']['exact'])} | "
                f"{_metric_text(group['overall']['low_vs_non_low'])} |"
            )
    lines.extend(
        [
            "",
            "## Accuracy by domain",
            "",
            "| Domain | Exact | Low vs Non-Low |",
            "|---|---:|---:|",
        ]
    )
    for domain in DOMAINS:
        group = result["by_domain"][domain]
        lines.append(
            f"| {domain} | {_metric_text(group['exact'])} | "
            f"{_metric_text(group['low_vs_non_low'])} |"
        )
    lines.extend(
        [
            "",
            "## Accuracy by outcome and domain",
            "",
            "Exact agreement:",
            "",
            "| Outcome | D1 | D2 | D3 | D4 | D5 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for outcome in ("Overall Survival", "Progression-Free Survival", "Adverse Events"):
        groups = result["by_outcome_domain"].get(outcome)
        if groups:
            lines.append(
                f"| {outcome} | "
                + " | ".join(_metric_text(groups[d]["exact"]) for d in DOMAINS)
                + " |"
            )
    lines.extend(
        [
            "",
            "Low vs Non-Low agreement:",
            "",
            "| Outcome | D1 | D2 | D3 | D4 | D5 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for outcome in ("Overall Survival", "Progression-Free Survival", "Adverse Events"):
        groups = result["by_outcome_domain"].get(outcome)
        if groups:
            lines.append(
                f"| {outcome} | "
                + " | ".join(_metric_text(groups[d]["low_vs_non_low"]) for d in DOMAINS)
                + " |"
            )
    lines.extend(
        [
            "",
            "## Accuracy by primary or secondary outcome",
            "",
            "Co-primary and other explicitly primary endpoints are in the Primary row.",
            "",
            "| Outcome role | Cases | Domains exact | Domains Low vs Non-Low | "
            "Overall exact | Overall Low vs Non-Low |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for role in ("primary", "secondary"):
        group = result["by_primary_status"][role]
        lines.append(
            f"| {role.title()} | {group['case_count']} | "
            f"{_metric_text(group['pooled_domains']['exact'])} | "
            f"{_metric_text(group['pooled_domains']['low_vs_non_low'])} | "
            f"{_metric_text(group['overall']['exact'])} | "
            f"{_metric_text(group['overall']['low_vs_non_low'])} |"
        )
    lines.extend(["", "## Excluded cases", "", "| Outcome | Trial | Reason |", "|---|---|---|"])
    for row in result["excluded"]:
        lines.append(f"| {row['outcome']} | {row['trial']} | {row['reason']} |")
    lines.extend(
        [
            "",
            (
                "The complete case-level expected and observed labels are in the adjacent "
                "`score.json` file. The benchmark manifest records each trial-specific "
                "definition, abstract effect estimate, role, prompt, and run directory."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    try:
        result = score(args.manifest, args.reference)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.markdown_output:
            args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as error:
        print(f"benchmark scoring failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result["scope"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
