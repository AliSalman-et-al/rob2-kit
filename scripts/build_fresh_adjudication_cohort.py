#!/usr/bin/env python3
"""Register the selected 27-Sep campaign and reconcile its trace segments."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rob2_kit.evaluation.cohort import (
    DOMAINS,
    CohortCell,
    CohortManifest,
    CohortPartitions,
    ModelAccess,
    ReviewerProvenance,
    select_agreement_sample,
    write_cohort,
)

if __package__:
    from .build_adjudication_cohort import (
        _OUTCOME_FILES,
        _label,
        _normalise,
        _published,
        _reference_catalog,
    )
else:
    from build_adjudication_cohort import (
        _OUTCOME_FILES,
        _label,
        _normalise,
        _published,
        _reference_catalog,
    )

_OUTCOMES = {
    "Overall Survival": "overall-survival",
    "Progression-Free Survival": "progression-free-survival",
    "Adverse Events": "adverse-events",
}
_DOMAINS = {f"D{index}": domain for index, domain in enumerate(DOMAINS, 1)}
_RETRY = re.compile(r"^retry-attempt-(\d+)-")
_PHASE = re.compile(r"^phase-(\d+)\.jsonl$")
_DATE_MARKER = "/eval/runs/2026-09-27/"
_SAMPLE_SEED = "rob2-kit-2026-09-27-fresh-agreement-sample-v1"


def _phase_number(name: str) -> int:
    match = _PHASE.fullmatch(name)
    if match is None:
        raise ValueError(f"invalid phase trace name: {name}")
    return int(match.group(1))


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _captured_path(value: str, date_root: Path) -> Path:
    normalized = value.replace("\\", "/")
    index = normalized.casefold().find(_DATE_MARKER)
    if index < 0:
        raise ValueError(f"captured path is outside the September 27 run tree: {value}")
    path = date_root / normalized[index + len(_DATE_MARKER) :]
    if not path.exists():
        raise ValueError(f"captured path does not exist in this checkout: {path}")
    return path


def _relative(path: Path, repo: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _trace(
    run_dir: Path,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, str],
    Path,
    int,
    dict[str, tuple[Path, int]],
]:
    calls = []
    phase_paths = sorted(run_dir.glob("phase-*.jsonl"), key=lambda path: _phase_number(path.name))
    for path in phase_paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from error
            item = event.get("item", {})
            if event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
                continue
            result = item.get("result", {})
            receipt = result.get("structured_content", result.get("structuredContent"))
            if isinstance(receipt, dict):
                calls.append(
                    (
                        item.get("tool"),
                        receipt,
                        path,
                        line_number,
                        item.get("arguments", {}),
                    )
                )

    reviews = []
    projections: dict[str, set[str]] = defaultdict(set)
    for tool, receipt, path, line, _ in calls:
        data = receipt.get("data", {})
        review, findings = data.get("review"), data.get("domain_findings")
        if (
            tool == "review_trial"
            and data.get("review_page", {}).get("mode", "complete") == "complete"
            and isinstance(review, dict)
            and review.get("disposition") == "assessed"
            and isinstance(findings, list)
            and len(findings) == len(DOMAINS)
        ):
            reviews.append((review, findings, path, line))
        for item in _walk(receipt):
            source = item.get("source_id") or item.get("id")
            projection = item.get("projection_hash")
            if isinstance(source, str) and isinstance(projection, str):
                projections[source].add(projection)

    if not reviews:
        raise ValueError(f"no complete assessed review receipt found in {run_dir}")
    review, raw_findings, review_path, review_line = reviews[-1]
    findings = {item.get("domain_id"): item for item in raw_findings if isinstance(item, dict)}
    if set(findings) != set(DOMAINS):
        raise ValueError(f"assessed review has incomplete Domain coverage in {run_dir}")
    projection_map = {}
    for source, values in projections.items():
        if len(values) != 1:
            raise ValueError(f"source {source} changes projection within {run_dir}")
        projection_map[source] = next(iter(values))
    if not projection_map:
        raise ValueError(f"no source projection bindings found in {run_dir}")
    domain_saves: dict[str, tuple[Path, int]] = {}
    for tool, receipt, path, line, arguments in calls:
        trial_id = arguments.get("trial_id") if isinstance(arguments, dict) else None
        domain_id = arguments.get("domain_id") if isinstance(arguments, dict) else None
        if (
            tool == "save_domain_judgment"
            and receipt.get("outcome") == "success"
            and isinstance(trial_id, str)
            and _normalise(trial_id) == _normalise(str(review.get("trial_id", "")))
            and isinstance(domain_id, str)
            and domain_id in DOMAINS
        ):
            domain_saves[domain_id] = (path, line)
    if set(domain_saves) != set(DOMAINS):
        raise ValueError(f"no successful saved judgment locator for every Domain in {run_dir}")
    return review, findings, projection_map, review_path, review_line, domain_saves


def _history(row: dict[str, Any], date_root: Path, repo: Path):
    run_value = row.get("run_dir")
    if not isinstance(run_value, str):
        raise ValueError("selected attempt run_dir must be a string")
    run_dir = _captured_path(run_value, date_root)
    history = row.get("attempt_history")
    if not isinstance(history, list):
        index_path = next(
            (
                parent / "index.json"
                for parent in (run_dir, *run_dir.parents)
                if (parent / "index.json").is_file()
            ),
            None,
        )
        if index_path is None:
            raise ValueError(f"no attempt index found for {run_dir}")
        history = [
            {
                "attempt": row.get("attempt", 1),
                "index": str(index_path),
                "run_dir": str(run_dir),
                "selected": True,
            }
        ]
    attempts: list[dict[str, str | int | bool]] = []
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("attempt history entry must be an object")
        index_value = item.get("index")
        run_value = item.get("run_dir")
        if not isinstance(index_value, str) or not isinstance(run_value, str):
            raise ValueError("attempt history paths must be strings")
        index_path = _captured_path(index_value, date_root)
        attempt_dir = _captured_path(run_value, date_root)
        number = item.get("attempt")
        selected = item.get("selected")
        if type(number) is not int or not isinstance(selected, bool):
            raise ValueError(
                "attempt history entries require an integer number and boolean selection"
            )
        attempts.append(
            {
                "number": number,
                "index": _relative(index_path, repo),
                "identity": _hash(index_path),
                "run_dir": _relative(attempt_dir, repo),
                "selected": selected,
            }
        )
    if sum(1 for attempt in attempts if attempt["selected"]) != 1:
        raise ValueError("attempt history must identify exactly one selected attempt")
    return run_dir, attempts


def _case_key(outcome: str, trial: str) -> tuple[str, str]:
    return outcome, _normalise(trial)


def _segments(
    date_root: Path,
    repo: Path,
    selected_dirs: dict[tuple[str, str], Path],
    scored_campaign: str,
):
    records = []
    for path in sorted(date_root.rglob("*.jsonl")):
        parts = path.relative_to(date_root).parts
        campaign = parts[0]
        if campaign not in {"issue-465-e2e", "latest-rob2-kit-luna-medium", scored_campaign}:
            continue
        case = None
        outcome = trial = None
        for index, part in enumerate(parts[:-1]):
            if part == "runs" and index + 2 < len(parts):
                outcome, trial = parts[index + 1 : index + 3]
                case = f"{outcome}/{trial}"
                break
        attempt = next((int(match.group(1)) for part in parts if (match := _RETRY.match(part))), 1)
        phase_match = _PHASE.fullmatch(path.name)
        phase = int(phase_match.group(1)) if phase_match else None
        run_dir = path.parent
        index_path = next(
            (
                parent / "index.json"
                for parent in (run_dir, *run_dir.parents)
                if (parent / "index.json").is_file()
            ),
            None,
        )
        campaign_id = _read(index_path).get("campaign_id") if index_path else None
        if campaign == "issue-465-e2e":
            selection = "e2e_workflow_check"
        elif campaign == "latest-rob2-kit-luna-medium":
            selection = "unfinished_unscored"
        elif outcome and trial and selected_dirs.get(_case_key(outcome, trial)) == run_dir:
            selection = "selected_scored_attempt"
        elif (
            campaign == "rob2-trial-benchmark-fresh-4e03e798"
            and outcome == "progression-free-survival"
            and trial == "PEACE-1"
            and attempt == 1
        ):
            selection = "superseded_original_attempt"
        else:
            selection = "unselected_trace"

        malformed, events, calls = [], 0, 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(line_number)
                continue
            events += 1
            item = event.get("item", {})
            calls += event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call"
        records.append(
            {
                "path": _relative(path, repo),
                "campaign_directory": campaign,
                "campaign_id": campaign_id,
                "case": case,
                "attempt": attempt,
                "attempt_identity": _hash(index_path) if index_path else None,
                "phase": phase,
                "selection": selection,
                "sha256": _hash(path),
                "event_count": events,
                "completed_mcp_call_count": calls,
                "malformed_lines": malformed,
            }
        )
    return records


def _answer_trace(answer: dict[str, Any]):
    cited = set()
    for fact in answer.get("facts", []):
        evidence = fact.get("evidence") if isinstance(fact, dict) else None
        handle = evidence.get("handle") if isinstance(evidence, dict) else evidence
        if isinstance(handle, str) and handle.startswith("eh_"):
            cited.add(handle)
    expanded, locators = set(), []
    for expansion in answer.get("evidence_expansions", []):
        if not isinstance(expansion, dict):
            continue
        evidence = expansion.get("evidence")
        if isinstance(evidence, str) and evidence.startswith("eh_"):
            expanded.add(evidence)
        for window in expansion.get("windows", []):
            if isinstance(window, dict):
                locators.append(
                    {
                        "evidence_handle": evidence,
                        "operation": expansion.get("operation"),
                        "source_id": window.get("source_id"),
                        "page": window.get("page"),
                        "start_line": window.get("start_line"),
                        "end_line": window.get("end_line"),
                    }
                )
        if not expansion.get("windows") and expansion.get("source_id"):
            locators.append(
                {
                    "evidence_handle": evidence,
                    "operation": expansion.get("operation"),
                    "source_id": expansion.get("source_id"),
                    "page": expansion.get("page"),
                    "start_line": None,
                    "end_line": None,
                }
            )
    return sorted(cited), sorted(expanded), locators


def _premise_contrasts(cells, details):
    by_key = {(cell.outcome_id, _normalise(cell.trial_id), cell.domain_id): cell for cell in cells}

    def bind(outcome, trial, domain, role):
        cell = by_key[(outcome, _normalise(trial), domain)]
        answers = details[str(cell.identity)][1]
        return {
            "cohort_cell_identity": cell.identity,
            "trial": cell.trial_id,
            "outcome": cell.outcome_id,
            "domain": cell.domain_id,
            "role": role,
            "question_ids": list(cell.question_ids),
            "driver_question_ids": [
                answer["question_id"]
                for answer in answers
                if answer.get("driver") and answer.get("question_id")
            ],
            "trace_reference": cell.trace_reference,
            "trace_event_line": details[str(cell.identity)][7],
        }

    return [
        {
            "id": "trial-context-caused-deviations",
            "tracks": ["#476", "#463"],
            "status": "source_triage_lead_pending_review",
            "premise": (
                "Open-label awareness, ordinary discontinuation, or post-progression crossover "
                "alone does not establish trial-context-caused deviations affecting the "
                "assigned-effect result."
            ),
            "cells": [
                bind("overall-survival", "PEACE-1", "domain:deviations", "open-label care control"),
                bind(
                    "progression-free-survival",
                    "GETUG-AFU-15",
                    "domain:deviations",
                    "post-progression crossover; violations unresolved",
                ),
                bind(
                    "adverse-events",
                    "TITAN",
                    "domain:deviations",
                    "blinded conduct and expected AE discontinuations",
                ),
                bind(
                    "overall-survival",
                    "CHAARTED",
                    "domain:deviations",
                    "matching-label open-label reassurance candidate",
                ),
                bind(
                    "overall-survival",
                    "ENZAMET",
                    "domain:deviations",
                    "matching-label awareness control",
                ),
                bind(
                    "progression-free-survival",
                    "STAMPEDE",
                    "domain:deviations",
                    "matching-label open-label control",
                ),
            ],
        },
        {
            "id": "outcome-availability-vs-analysis-membership",
            "tracks": ["#476", "#463"],
            "status": "source_triage_lead_pending_review",
            "premise": (
                "Analysis membership, censoring rules, or event totals do not alone establish "
                "outcome availability for all or nearly all randomized participants."
            ),
            "cells": [
                bind(
                    "overall-survival",
                    "TITAN",
                    "domain:missing",
                    "losses with follow-up reported; arm impact unresolved",
                ),
                bind(
                    "overall-survival",
                    "ARASENS",
                    "domain:missing",
                    "analysis count does not establish follow-up completeness",
                ),
            ],
        },
        {
            "id": "measurement-opportunity-vs-observed-events",
            "tracks": ["#476", "#463"],
            "status": "source_triage_lead_pending_review",
            "premise": (
                "Unequal visits or laboratory monitoring can create differential opportunity "
                "to detect safety events even when aggregate rates are similar."
            ),
            "cells": [
                bind(
                    "adverse-events",
                    "PEACE-1",
                    "domain:measurement",
                    "defensible concern control: extra arm-specific laboratory monitoring",
                )
            ],
        },
        {
            "id": "analysis-plan-vs-unblinded-access-chronology",
            "tracks": ["#476", "#463"],
            "status": "source_triage_lead_pending_review",
            "premise": (
                "A dated plan before the analysis cutoff does not prove it predated access to "
                "unblinded outcome data or that the result was selected because of its result."
            ),
            "cells": [
                bind(
                    "progression-free-survival",
                    "TITAN",
                    "domain:selection",
                    "protocol timing; access chronology unresolved",
                ),
                bind(
                    "progression-free-survival",
                    "STAMPEDE",
                    "domain:selection",
                    "SAP timing; result-driven selection not shown",
                ),
            ],
        },
        {
            "id": "approved-safety-result-scope",
            "tracks": ["#479", "#476", "#463"],
            "status": "independent_result_scope_review_pending",
            "premise": (
                "Check the approved safety Result's actual analysis population and "
                "treatment-received membership against the frozen expected Result scope."
            ),
            "cells": [
                bind(
                    "adverse-events",
                    "ARASENS",
                    "domain:measurement",
                    "safety Result includes one crossover in actual-exposure grouping",
                )
            ],
        },
    ]


def _source_triage_addendum(matrix):
    by_key = {(row["outcome"], row["trial"], row["domain"]): row for row in matrix}

    candidate_notes = {
        ("overall-survival", "peace-1", "domain:deviations"): (
            "Open-label awareness and post-progression care alone do not establish "
            "trial-context-caused deviations; the model Low remains plausible."
        ),
        ("progression-free-survival", "chaarted", "domain:measurement"): (
            "Different follow-up intervals over a composite endpoint are a plausible "
            "differential-monitoring mechanism; impact and rating remain unresolved."
        ),
        ("progression-free-survival", "peace-1", "domain:measurement"): (
            "Unmasked conduct and suspicion-triggered imaging are a candidate "
            "differential-opportunity mechanism; impact and rating remain unresolved."
        ),
        ("adverse-events", "peace-1", "domain:measurement"): (
            "Additional arm-specific laboratory checks support differential "
            "ascertainment; this does not establish a corrected label."
        ),
    }

    def record(row, status, note):
        return {
            "cohort_cell_identity": row["cohort_cell_identity"],
            "status": status,
            "note": note,
            "trace_locator": {
                "path": row["trace_reference"],
                "phase": row["trace_phase"],
                "event_line": row["trace_event_line"],
            },
            "domain_judgment_locator": {
                "path": row["domain_judgment_trace_reference"],
                "phase": row["domain_judgment_trace_phase"],
                "event_line": row["domain_judgment_event_line"],
            },
            "source_locator_refs": [
                {key: locator.get(key) for key in ("source_id", "page", "start_line", "end_line")}
                for locator in row["source_locators"]
            ],
            "source_projection_bindings": row["source_projection_bindings"],
        }

    candidates = []
    candidate_ids = set()
    for key, note in candidate_notes.items():
        row = by_key[key]
        if row["review_kind"] != "disagreement":
            raise ValueError(f"triage candidate is not a disagreement: {key}")
        candidates.append(record(row, "defensible_alternative_mechanism_candidate", note))
        candidate_ids.add(row["cohort_cell_identity"])

    disagreements = [row for row in matrix if row["review_kind"] == "disagreement"]
    indeterminate = sorted(
        row["cohort_cell_identity"]
        for row in disagreements
        if row["cohort_cell_identity"] not in candidate_ids
    )
    caveat_ids = [
        by_key[("adverse-events", "arasens", domain)]["cohort_cell_identity"]
        for domain in ("domain:deviations", "domain:selection")
    ]
    controls = [
        record(
            row, "matching_label_plausible_with_caveats", "Source-checked control; no label edit."
        )
        for row in sorted(
            (row for row in matrix if row["review_kind"] == "matching_label_sample"),
            key=lambda row: row["selection_sample"]["rank"],
        )
    ]
    arches_d1 = by_key[("adverse-events", "arches", "domain:randomization")]
    return {
        "status": "provisional_ai_source_triage_recorded",
        "source_report": "docs/archive/evaluation/2026-09-27-fresh-audit-evidence/science.md",
        "independent_adjudication_status": "pending_external_adjudication",
        "labels_corrected": False,
        "uniquely_wrong_model_label_established": False,
        "confirmed_model_error_count": 0,
        "confirmed_reference_or_result_scope_error_count": 0,
        "disagreements": {
            "count": len(disagreements),
            "defensible_alternative_candidates": candidates,
            "indeterminate_count": len(indeterminate),
            "indeterminate_cell_identities": indeterminate,
            "result_scope_caveats": [
                {
                    "cohort_cell_identity": identity,
                    "issue": "#480",
                    "status": "unresolved_caveat_not_confirmed_scope_mismatch",
                    "note": (
                        "ARASENS adverse-events uses treatment-received grouping, including "
                        "one crossover, while the frozen expected scope differs. The recorded "
                        "equivalent decision is not independent Result-scope certification."
                    ),
                }
                for identity in caveat_ids
            ],
        },
        "matching_label_controls": {
            "count": len(controls),
            "status": "source_checked_plausible_with_caveats",
            "rows": controls,
            "caveats": [
                {
                    "cohort_cell_identity": arches_d1["cohort_cell_identity"],
                    "note": (
                        "ARCHES adverse-events D1 sequence-generation warrant remains caveated."
                    ),
                }
            ],
        },
        "locator_note": (
            "The candidate and control records carry phase/event-line and source page/line "
            "locators from review_matrix. These locate captured evidence; they do not "
            "establish entailment."
        ),
    }


def build(reference: Path, run_root: Path, audit_root: Path):
    repo = Path(__file__).resolve().parents[1]
    reference, run_root, audit_root = reference.resolve(), run_root.resolve(), audit_root.resolve()
    index_path = run_root / "index.json"
    selected_path = run_root / "selected-attempts" / "index.json"
    score_path = run_root / "scores.json"
    campaign_id = _read(index_path)["campaign_id"]
    selected_rows = {
        (row["outcome"], _normalise(row["trial"])): row for row in _read(selected_path)["cases"]
    }
    score_rows = _read(score_path).get("cases", [])
    if len(score_rows) != 26:
        raise ValueError(f"expected 26 selected cases, found {len(score_rows)}")

    cells, cases, detail = [], [], {}
    selected_dirs, catalog_cache = {}, {}
    for row in score_rows:
        outcome, trial = _OUTCOMES[row["outcome"]], row["trial"]
        selected = selected_rows[(row["outcome"], _normalise(trial))]
        run_dir, attempts = _history(selected, audit_root, repo)
        selected_dirs[_case_key(outcome, trial)] = run_dir
        review, findings, projections, review_path, review_line, domain_saves = _trace(run_dir)
        scope = row.get("scope_adjudication")
        if not isinstance(scope, dict) or scope.get("result_identity") != review.get(
            "result_identity"
        ):
            raise ValueError(
                f"selected Result scope does not bind to the review for {trial}/{outcome}"
            )
        if outcome not in catalog_cache:
            catalog_cache[outcome] = (
                _reference_catalog(reference, outcome),
                reference / "catalog" / "provisional-labels" / _OUTCOME_FILES[outcome],
            )
        catalog, catalog_path = catalog_cache[outcome]
        expected = tuple(_label(row["expected"][f"D{i}"]) for i in range(1, 6))
        observed = tuple(_label(row["observed"][f"D{i}"]) for i in range(1, 6))
        if catalog.get(_normalise(trial)) != expected:
            raise ValueError(f"score reference differs from catalog for {trial}/{outcome}")

        trial_id = review.get("trial_id")
        if not isinstance(trial_id, str) or _normalise(trial_id) != _normalise(trial):
            raise ValueError(f"review Trial differs from score row for {trial}/{outcome}")
        case_id = f"{campaign_id}:{outcome}:{trial_id}"
        case_cells = []
        for i, domain in enumerate(DOMAINS):
            finding = findings[domain]
            domain_save_path, domain_save_line = domain_saves[domain]
            if _label(str(finding.get("judgment", ""))) != observed[i]:
                raise ValueError(f"trace label differs from scores for {trial}/{domain}")
            answers = finding.get("answers", [])
            if not answers:
                raise ValueError(f"missing active questions for {trial}/{domain}")
            source_ids = {
                window["source_id"]
                for answer in answers
                for expansion in answer.get("evidence_expansions", [])
                if isinstance(expansion, dict)
                for window in expansion.get("windows", [])
                if isinstance(window, dict) and isinstance(window.get("source_id"), str)
            }
            source_ids.update(
                expansion["source_id"]
                for answer in answers
                for expansion in answer.get("evidence_expansions", [])
                if isinstance(expansion, dict) and isinstance(expansion.get("source_id"), str)
            )
            projection_scope = "answer_expansions"
            if not source_ids:
                source_ids, projection_scope = set(projections), "case_source_inventory"
            if not source_ids <= set(projections):
                raise ValueError(f"missing source projection for {trial}/{domain}")
            checkpoint = finding.get("checkpoint_identity")
            questions = tuple(
                answer["question_id"] for answer in answers if answer.get("question_id")
            )
            if not checkpoint or not questions:
                raise ValueError(f"missing checkpoint or question identity for {trial}/{domain}")
            cell = CohortCell(
                campaign_id=campaign_id,
                case_identity=case_id,
                trial_id=trial_id,
                outcome_id=outcome,
                result_identity=review["result_identity"],
                review_identity=review["identity"],
                domain_id=domain,
                question_ids=questions,
                checkpoint_identity=checkpoint,
                source_identities=tuple(sorted(source_ids)),
                source_projection_ids=tuple(sorted({projections[source] for source in source_ids})),
                source_projection_scope=projection_scope,
                reference_label=expected[i],
                model_label=observed[i],
                reviewer_provenance=ReviewerProvenance(
                    note="Independent scientific adjudication and reviewer provenance are pending."
                ),
                trace_reference=_relative(review_path, repo),
            )
            cells.append(cell)
            case_cells.append(cell)
            detail[str(cell.identity)] = (
                finding,
                answers,
                catalog_path,
                row["trial"],
                scope,
                selected,
                attempts,
                review_line,
                projections,
                _relative(domain_save_path, repo),
                domain_save_line,
            )

        cases.append(
            {
                "trial": trial,
                "outcome": outcome,
                "selected_attempt": int(selected.get("attempt", 1)),
                "attempts": attempts,
                "result_identity": review["result_identity"],
                "assessment_review_identity": review["identity"],
                "scope_review_identity": scope["review_identity"],
                "recorded_relation": scope["observed_relation"],
                "recorded_decision": scope["decision"],
                "scope_status": "recorded_not_independently_certified",
                "scope_review_note": (
                    "Treatment-received safety Result includes one crossover in "
                    "actual-exposure grouping; frozen expected scope differs."
                    if trial == "ARASENS" and outcome == "adverse-events"
                    else None
                ),
            }
        )

    if sum(cell.comparison == "agreement" for cell in cells) != 83:
        raise ValueError("expected 83 exact Domain agreements")
    if sum((cell.reference_label == "low") == (cell.model_label == "low") for cell in cells) != 96:
        raise ValueError("expected 96 Low-vs-non-Low agreements")
    if sum(cell.reference_label == "low" for cell in cells) != 104:
        raise ValueError("expected 104/130 all-Low reference agreement")
    if sum(row["expected"]["overall"] == row["observed"]["overall"] for row in score_rows) != 2:
        raise ValueError("expected 2/26 exact overall agreement")

    sample = select_agreement_sample(cells, seed=_SAMPLE_SEED, size=10)
    manifest = CohortManifest(
        campaign_id=campaign_id,
        pinned_run=_relative(run_root, repo),
        reference_catalog=_relative(reference / "catalog", repo),
        cells=tuple(cells),
        partitions=CohortPartitions(
            development_case_ids=tuple(sorted({cell.case_identity for cell in cells}))
        ),
        published_outcome_totals=_published(cells, unit="outcome"),
        published_domain_totals=_published(cells, unit="domain"),
        agreement_sample=sample,
        model_access=ModelAccess(
            note=(
                "Prompt files exist, but this cohort does not verify bytes delivered to the model. "
                "Later adjudication was not provided to the campaign."
            )
        ),
        note=(
            "All scientific classifications, reviewer identities, and uncertainty assessments "
            "remain pending."
        ),
    )

    sample_ids = {entry.cell_identity: entry for entry in sample}
    matrix = []
    for cell in cells:
        sample_entry = sample_ids.get(str(cell.identity))
        if cell.comparison != "disagreement" and sample_entry is None:
            continue
        (
            finding,
            answers,
            catalog_path,
            catalog_trial,
            scope,
            selected,
            attempts,
            review_line,
            projections,
            domain_save_reference,
            domain_save_line,
        ) = detail[str(cell.identity)]
        locators, cited, expanded = [], set(), set()
        for answer in answers:
            answer_cited, answer_expanded, answer_locators = _answer_trace(answer)
            cited.update(answer_cited)
            expanded.update(answer_expanded)
            locators.extend(answer_locators)
        phase = _PHASE.fullmatch(Path(cell.trace_reference).name)
        catalog_hash = _hash(catalog_path)
        matrix.append(
            {
                "review_kind": "disagreement"
                if cell.comparison == "disagreement"
                else "matching_label_sample",
                "review_status": "pending_ai_triage_and_evidence_status_audit",
                "independent_adjudication_status": cell.adjudication_status,
                "cohort_cell_identity": cell.identity,
                "case_identity": cell.case_identity,
                "trial": cell.trial_id,
                "outcome": cell.outcome_id,
                "domain": cell.domain_id,
                "reference_label": cell.reference_label.value,
                "model_label": cell.model_label.value,
                "classification": None,
                "uncertainty": "pending",
                "reviewer_provenance": cell.reviewer_provenance.model_dump(mode="json"),
                "reference_provenance": {
                    "catalog_path": _relative(catalog_path, repo),
                    "catalog_version": catalog_hash,
                    "trial_row": catalog_trial,
                    "domain": cell.domain_id,
                    "label": cell.reference_label.value,
                },
                "result_identity": cell.result_identity,
                "review_identity": cell.review_identity,
                "selected_attempt": int(selected.get("attempt", 1)),
                "attempt_identity": next(item["identity"] for item in attempts if item["selected"]),
                "trace_reference": cell.trace_reference,
                "trace_phase": int(phase.group(1)) if phase else None,
                "trace_event_line": review_line,
                "domain_judgment_trace_reference": domain_save_reference,
                "domain_judgment_trace_phase": _phase_number(Path(domain_save_reference).name),
                "domain_judgment_event_line": domain_save_line,
                "question_ids": list(cell.question_ids),
                "driver_question_ids": [
                    answer["question_id"]
                    for answer in answers
                    if answer.get("driver") and answer.get("question_id")
                ],
                "checkpoint_identity": cell.checkpoint_identity,
                "source_identities": list(cell.source_identities),
                "source_projection_ids": list(cell.source_projection_ids),
                "source_projection_bindings": [
                    {"source_id": source, "projection_id": projections[source]}
                    for source in cell.source_identities
                ],
                "source_projection_scope": cell.source_projection_scope,
                "recorded_result_scope_status": "recorded_not_independently_certified",
                "evidence_availability_status": (
                    "source_projection_bound; decisive_evidence_pending"
                ),
                "evidence_delivery_status": "accepted_answer_expansion_recorded"
                if expanded
                else "none_recorded",
                "evidence_citation_status": "accepted_answer_fact_handle_recorded"
                if cited
                else "none_recorded",
                "evidence_interpretation_status": "pending_source_review",
                "cited_evidence_handle_count": len(cited),
                "expanded_evidence_handle_count": len(expanded),
                "source_locators": sorted(
                    {json.dumps(locator, sort_keys=True): locator for locator in locators}.values(),
                    key=lambda item: (
                        item.get("source_id") or "",
                        item.get("page") or 0,
                        item.get("start_line") or 0,
                    ),
                ),
                "selection_sample": (
                    {"seed": sample_entry.selection_seed, "rank": sample_entry.selection_rank}
                    if sample_entry
                    else None
                ),
            }
        )
    if sum(row["review_kind"] == "disagreement" for row in matrix) != 47 or len(sample_ids) != 10:
        raise ValueError("review matrix coverage does not reconcile")
    triage_addendum = _source_triage_addendum(matrix)
    if (
        triage_addendum["disagreements"]["indeterminate_count"] != 43
        or triage_addendum["matching_label_controls"]["count"] != 10
    ):
        raise ValueError("source-triage addendum coverage does not reconcile")

    segments = _segments(audit_root, repo, selected_dirs, run_root.name)
    if len(segments) != 102:
        raise ValueError(f"expected 102 JSONL segments, found {len(segments)}")
    segment_counts = Counter(item["selection"] for item in segments)
    expected_segments = Counter(
        {
            "e2e_workflow_check": 7,
            "unfinished_unscored": 33,
            "selected_scored_attempt": 59,
            "superseded_original_attempt": 3,
        }
    )
    if segment_counts != expected_segments:
        raise ValueError(f"segment reconciliation differs: {dict(segment_counts)}")

    reconciliation = {
        "schema": "rob2-kit.fresh-campaign-reconciliation.v1",
        "campaign_id": campaign_id,
        "cohort_identity": manifest.identity,
        "source_inputs": {
            "campaign_index": {"path": _relative(index_path, repo), "identity": _hash(index_path)},
            "selected_attempt_index": {
                "path": _relative(selected_path, repo),
                "identity": _hash(selected_path),
            },
            "scores": {"path": _relative(score_path, repo), "identity": _hash(score_path)},
            "scope_adjudications": {
                "path": _relative(run_root / "selected-attempts-scope-adjudications.json", repo),
                "identity": _hash(run_root / "selected-attempts-scope-adjudications.json"),
            },
        },
        "reference_catalog": {
            "catalog_path": _relative(reference / "catalog", repo),
            "label_files": [
                {"path": _relative(path, repo), "catalog_version": _hash(path)}
                for _, path in sorted(catalog_cache.values(), key=lambda item: item[1].name)
            ],
        },
        "coverage": {
            "assessment_cases": 26,
            "domain_cells": 130,
            "exact_domain_agreements": 83,
            "low_vs_non_low_agreements": 96,
            "exact_overall_agreements": 2,
            "all_low_baseline_agreements": 104,
            "disagreement_cells": 47,
            "matching_label_sample_cells": 10,
            "pending_ai_triage_rows": 57,
            "independent_reviews_complete": 0,
            "scope_decisions_recorded": len(cases),
            "scope_decisions_independently_certified": 0,
        },
        "segments": {
            "count": len(segments),
            "classifications": dict(segment_counts),
            "items": segments,
        },
        "selected_cases": cases,
        "review_matrix": matrix,
        "source_triage_addendum": triage_addendum,
        "premise_contrasts": _premise_contrasts(cells, detail),
        "scope_limit": (
            "Recorded equivalent decisions are not independently certified. ARASENS "
            "adverse-events requires Result-population review."
        ),
        "interpretation_limit": (
            "Trace provenance does not validate source entailment. No label is corrected and "
            "no adjusted accuracy is computed."
        ),
    }
    return manifest, reconciliation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path("eval/reference"))
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798"),
    )
    parser.add_argument("--audit-root", type=Path, default=Path("eval/runs/2026-09-27"))
    parser.add_argument("--output", type=Path, default=Path("eval/cohorts/2026-09-27-fresh.json"))
    parser.add_argument(
        "--reconciliation-output",
        type=Path,
        default=Path("eval/cohorts/2026-09-27-fresh-reconciliation.json"),
    )
    args = parser.parse_args()
    manifest, reconciliation = build(args.reference, args.run_root, args.audit_root)
    write_cohort(args.output, manifest)
    args.reconciliation_output.parent.mkdir(parents=True, exist_ok=True)
    args.reconciliation_output.write_text(
        json.dumps(reconciliation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "cohort_output": str(args.output),
                "cohort_identity": manifest.identity,
                "reconciliation_output": str(args.reconciliation_output),
                "cases": len({cell.case_identity for cell in manifest.cells}),
                "domain_cells": len(manifest.cells),
                "exact_agreements": sum(cell.comparison == "agreement" for cell in manifest.cells),
                "disagreements": sum(cell.comparison == "disagreement" for cell in manifest.cells),
                "agreement_sample": len(manifest.agreement_sample),
                "segments": reconciliation["segments"]["count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
