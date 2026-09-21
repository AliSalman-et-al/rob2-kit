#!/usr/bin/env python3
"""Build a pending post-audit cohort from frozen labels and run traces.

This importer joins labels to the final review receipt in each pinned trace.
It never derives a scientific adjudication from agreement, and it refuses to
write a completed reviewer record without explicit external input.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Literal

from rob2_kit.evaluation.cohort import (
    DOMAINS,
    OUTCOMES,
    CohortCell,
    CohortLabel,
    CohortManifest,
    CohortPartitions,
    ModelAccess,
    PublishedTotals,
    ReviewerProvenance,
    select_agreement_sample,
    write_cohort,
)

_OUTCOME_FILES = {
    "overall-survival": "overall-survival.csv",
    "progression-free-survival": "progression-free-survival.csv",
    "adverse-events": "adverse-events.csv",
}
_CODE_LABELS = {"L": CohortLabel.LOW, "S": CohortLabel.SOME_CONCERNS, "H": CohortLabel.HIGH}
_FULL_LABELS = {
    "low": CohortLabel.LOW,
    "some concerns": CohortLabel.SOME_CONCERNS,
    "some_concerns": CohortLabel.SOME_CONCERNS,
    "high": CohortLabel.HIGH,
}


def _normalise(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _label(value: str) -> CohortLabel:
    key = value.strip()
    if key in _CODE_LABELS:
        return _CODE_LABELS[key]
    try:
        return _FULL_LABELS[key.casefold()]
    except KeyError as error:
        raise ValueError(f"unsupported risk label: {value}") from error


def _reference_catalog(reference: Path, outcome: str) -> dict[str, tuple[CohortLabel, ...]]:
    path = reference / "catalog" / "provisional-labels" / _OUTCOME_FILES[outcome]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {
            _normalise(row["Trial"]): tuple(_label(row[f"D{index}"]) for index in range(1, 6))
            for row in csv.DictReader(stream)
        }


def _read_labels(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"outcome", "trial", "reference", "model", "trace"}
    if any(not required <= set(row) for row in rows):
        raise ValueError("model label rows require outcome, trial, reference, model, and trace")
    if len(rows) != 28:
        raise ValueError(f"pinned audit must provide 28 assessments, found {len(rows)}")
    return rows


def _completed_calls(path: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from error
            item = event.get("item")
            if (
                event.get("type") != "item.completed"
                or not isinstance(item, dict)
                or item.get("type") != "mcp_tool_call"
            ):
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            structured = result.get("structured_content", result.get("structuredContent"))
            if isinstance(structured, dict):
                calls.append(
                    {
                        "tool": item.get("tool"),
                        "arguments": item.get("arguments", {}),
                        "receipt": structured,
                    }
                )
    return calls


def _walk(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def _trace_receipt(
    path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]:
    calls = _completed_calls(path)
    reviews = [
        call["receipt"].get("data", {}).get("review")
        for call in calls
        if call["tool"] == "review_trial"
        and isinstance(call["receipt"].get("data", {}).get("review"), dict)
    ]
    review = next(
        (item for item in reversed(reviews) if item.get("disposition") == "assessed"), None
    )
    if review is None:
        raise ValueError(f"no assessed review receipt found in {path}")
    findings = [
        call["receipt"].get("data", {}).get("domain_findings")
        for call in calls
        if call["tool"] == "review_trial"
        and isinstance(call["receipt"].get("data", {}).get("domain_findings"), list)
    ]
    finding_list = next((item for item in reversed(findings) if len(item) == len(DOMAINS)), None)
    if finding_list is None:
        raise ValueError(f"assessed review has no complete Domain findings in {path}")
    findings_by_domain = {
        item.get("domain_id"): item for item in finding_list if isinstance(item, dict)
    }
    if set(findings_by_domain) != set(DOMAINS):
        raise ValueError(f"assessed review has incomplete Domain coverage in {path}")
    projections: dict[str, set[str]] = {}
    for obj in _walk(calls):
        source_id = obj.get("source_id")
        projection = obj.get("projection_hash")
        if isinstance(source_id, str) and isinstance(projection, str):
            projections.setdefault(source_id, set()).add(projection)
    projection_map: dict[str, str] = {}
    for source_id, values in projections.items():
        if len(values) != 1:
            raise ValueError(f"source {source_id} changes projection within {path}")
        projection_map[source_id] = next(iter(values))
    if not projection_map:
        raise ValueError(f"no source projection bindings found in {path}")
    return review, findings_by_domain, projection_map


def _published(
    rows: list[CohortCell], *, unit: Literal["outcome", "domain"]
) -> dict[str, PublishedTotals]:
    keys = {row.outcome_id if unit == "outcome" else row.domain_id for row in rows}
    return {
        key: PublishedTotals(
            unit=unit,
            assessments=len(
                {
                    row.case_identity
                    for row in rows
                    if (row.outcome_id if unit == "outcome" else row.domain_id) == key
                }
            ),
            domain_cells=sum(
                (row.outcome_id if unit == "outcome" else row.domain_id) == key for row in rows
            ),
            exact_matches=sum(
                (row.outcome_id if unit == "outcome" else row.domain_id) == key
                and row.comparison == "agreement"
                for row in rows
            ),
            disagreements=sum(
                (row.outcome_id if unit == "outcome" else row.domain_id) == key
                and row.comparison == "disagreement"
                for row in rows
            ),
        )
        for key in sorted(keys)
    }


def build(reference: Path, run_root: Path, labels_path: Path) -> CohortManifest:
    rows = _read_labels(labels_path)
    campaign_id = run_root.name
    cells: list[CohortCell] = []
    case_ids: list[str] = []
    for row in rows:
        outcome = row["outcome"].strip()
        if outcome not in OUTCOMES:
            raise ValueError(f"unsupported outcome in model labels: {outcome}")
        trial_label = row["trial"].strip()
        catalog_labels = _reference_catalog(reference, outcome)
        expected_reference = catalog_labels.get(_normalise(trial_label))
        if expected_reference is None:
            raise ValueError(f"reference catalog has no {outcome}/{trial_label}")
        reference_codes = tuple(_label(value) for value in row["reference"])
        model_codes = tuple(_label(value) for value in row["model"])
        if reference_codes != expected_reference:
            raise ValueError(
                f"model label file reference differs from catalog for {outcome}/{trial_label}"
            )
        trace = Path(row["trace"])
        if not trace.is_absolute():
            trace = Path.cwd() / trace
        if not trace.is_file():
            raise ValueError(f"trace does not exist: {trace}")
        review, findings, projection_map = _trace_receipt(trace)
        trial_id = review.get("trial_id")
        if not isinstance(trial_id, str) or _normalise(trial_id) != _normalise(trial_label):
            raise ValueError(f"review Trial does not match label row: {trial_label}")
        result_identity = review.get("result_identity")
        if not isinstance(result_identity, str):
            raise ValueError(f"review has no approved Result identity: {trace}")
        review_identity = review.get("identity")
        if not isinstance(review_identity, str):
            raise ValueError(f"review has no immutable review identity: {trace}")
        case_identity = f"{campaign_id}:{outcome}:{trial_id}"
        case_ids.append(case_identity)
        pending_reviewer = ReviewerProvenance(
            note=(
                "The pinned audit supplies provisional labels only; independent adjudication "
                "and reviewer provenance are pending."
            )
        )
        for index, domain_id in enumerate(DOMAINS):
            finding = findings[domain_id]
            observed = _label(str(finding.get("judgment", "")))
            if observed != model_codes[index]:
                raise ValueError(
                    "trace model label differs from audit row for "
                    f"{outcome}/{trial_label}/{domain_id}"
                )
            answers = finding.get("answers")
            if not isinstance(answers, list) or not answers:
                raise ValueError(
                    f"Domain has no question bindings for {outcome}/{trial_label}/{domain_id}"
                )
            source_ids = {
                window.get("source_id")
                for answer in answers
                if isinstance(answer, dict)
                for expansion in answer.get("evidence_expansions", [])
                if isinstance(expansion, dict)
                for window in expansion.get("windows", [])
                if isinstance(window, dict) and isinstance(window.get("source_id"), str)
            }
            scope = "answer_expansions"
            if not source_ids:
                source_ids = set(projection_map)
                scope = "case_source_inventory"
            elif not source_ids <= set(projection_map):
                missing_sources = sorted(source_ids - set(projection_map))
                raise ValueError(
                    f"Domain cites source identities without projections: {missing_sources}"
                )
            cells.append(
                CohortCell(
                    campaign_id=campaign_id,
                    case_identity=case_identity,
                    trial_id=trial_id,
                    outcome_id=outcome,
                    result_identity=result_identity,
                    review_identity=review_identity,
                    domain_id=domain_id,
                    question_ids=tuple(
                        answer["question_id"]
                        for answer in answers
                        if isinstance(answer, dict) and isinstance(answer.get("question_id"), str)
                    ),
                    checkpoint_identity=str(finding.get("checkpoint_identity", "")),
                    source_identities=tuple(sorted(source_ids)),
                    source_projection_ids=tuple(
                        sorted(projection_map[source_id] for source_id in source_ids)
                    ),
                    source_projection_scope=scope,
                    reference_label=reference_codes[index],
                    model_label=observed,
                    reviewer_provenance=pending_reviewer,
                    trace_reference=row["trace"].replace("\\", "/"),
                )
            )
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate outcome/Trial in model label rows")
    if len(cells) != 140:
        raise ValueError(f"pinned audit must provide 140 Domain cells, found {len(cells)}")
    if sum(cell.comparison == "agreement" for cell in cells) != 93:
        raise ValueError("pinned audit must reproduce 93 exact agreements")
    if sum(cell.comparison == "disagreement" for cell in cells) != 47:
        raise ValueError("pinned audit must reproduce 47 disagreements")
    sample = select_agreement_sample(cells)
    return CohortManifest(
        campaign_id=campaign_id,
        pinned_run=run_root.as_posix(),
        reference_catalog=(reference / "catalog").as_posix(),
        cells=tuple(cells),
        partitions=CohortPartitions(held_out_case_ids=tuple(sorted(set(case_ids)))),
        published_outcome_totals=_published(cells, unit="outcome"),
        published_domain_totals=_published(cells, unit="domain"),
        agreement_sample=sample,
        model_access=ModelAccess(
            note=(
                "Post-hoc cohort only: model prompts did not receive adjudication labels "
                "or rationales; prompt bytes were not retained in this artifact."
            )
        ),
        note=(
            "Baseline reconstruction from the pinned 21-Sep-26 run. Independent adjudications, "
            "reviewer identities, and agreement-sample reviews remain pending."
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--model-labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cohort = build(args.reference, args.run_root, args.model_labels)
    write_cohort(args.output, cohort)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "identity": cohort.identity,
                "assessments": len(set(cell.case_identity for cell in cohort.cells)),
                "domain_cells": len(cohort.cells),
                "exact_matches": sum(cell.comparison == "agreement" for cell in cohort.cells),
                "disagreements": sum(cell.comparison == "disagreement" for cell in cohort.cells),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
