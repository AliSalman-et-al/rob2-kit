#!/usr/bin/env python3
"""Rebuild the 26–27 September cohorts, score reconciliation, and trace inventory."""

# Embedded source-audit narratives are kept intact as data fields.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal, TypedDict

from rob2_kit.evaluation.adjudication import (
    AdjudicationClassification,
    AdjudicationSidecar,
    EvidenceLocator,
)
from rob2_kit.evaluation.cohort import (
    DOMAINS,
    AgreementSampleEntry,
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

_CODE_LABELS = {"L": CohortLabel.LOW, "S": CohortLabel.SOME_CONCERNS, "H": CohortLabel.HIGH}
_NAME_LABELS = {
    "low": CohortLabel.LOW,
    "some concerns": CohortLabel.SOME_CONCERNS,
    "some_concerns": CohortLabel.SOME_CONCERNS,
    "high": CohortLabel.HIGH,
}
_OUTCOMES = {
    "overall survival": "overall-survival",
    "progression-free survival": "progression-free-survival",
    "adverse events": "adverse-events",
}
_OUTCOME_FILES = {
    "overall-survival": "overall-survival.csv",
    "progression-free-survival": "progression-free-survival.csv",
    "adverse-events": "adverse-events.csv",
}
_DOMAIN_KEYS = dict(zip((f"D{i}" for i in range(1, 6)), DOMAINS, strict=True))
_REVIEWED_AT = "2026-09-27T14:04:24+05:00"
_REVIEWER = "codex-agent-issue-475-2026-09-27"
_REVIEWER_ROLE = "AI source-grounded reviewer; not an independent human expert"
_AGREEMENT_REVIEWED_AT = "2026-09-27T14:28:06+05:00"
_AGREEMENT_REVIEWER = "codex-agent-issue-475-agreement-sample-followup-2026-09-27"


class SourceAuditFinding(TypedDict):
    campaign: str
    outcome: str
    trial: str
    domain: str
    question_ids: tuple[str, ...]
    classification: AdjudicationClassification
    confidence: float
    source_files: tuple[str, ...]
    evidence: tuple[tuple[str, str, str], ...]
    rationale: str
    unresolved_facts: tuple[str, ...]
    follow_up: tuple[str, ...]
    attribution: str


class AgreementSampleReview(TypedDict):
    case_identity: str
    outcome: str
    domain: str
    classification: AdjudicationClassification
    confidence: float
    sample_note: str
    rationale: str
    unresolved_facts: tuple[str, ...]
    follow_up: tuple[str, ...]


_AGREEMENT_SAMPLE_REVIEWS: tuple[AgreementSampleReview, ...] = (
    {
        "case_identity": "2026-09-26:adverse-events:latitude",
        "outcome": "adverse-events",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.72,
        "sample_note": (
            "AI review checked the selected grade 3 or higher AE Result and each saved Domain 4 answer against captured source windows. "
            "The differential-ascertainment answer contains unsupported reassurance about unequal exposure; the final Low label remains unresolved."
        ),
        "rationale": (
            "The CTCAE method and double-blind assessment statements support the saved method and assessor answers. "
            "For differential measurement, the answer notes but dismisses median exposure of 24 versus 14 months without assessing the unequal time at risk for a cumulative grade 3 or higher AE result. "
            "A common visit schedule does not establish equal cumulative ascertainment opportunity. This is a likely model error in that question's reassurance, while its effect on the final Domain label is unresolved."
        ),
        "unresolved_facts": (
            "The source report does not quantify how unequal treatment exposure affected cumulative grade 3 or higher AE ascertainment.",
            "Actual attendance at scheduled safety assessments by randomized group is not reported.",
        ),
        "follow_up": (
            "Compare cumulative AE ascertainment and time at risk by randomized group under the approved safety estimand.",
        ),
    },
    {
        "case_identity": "2026-09-26:overall-survival:chaarted",
        "outcome": "overall-survival",
        "domain": "domain:missing",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.7,
        "sample_note": "AI source review found the saved near-complete vital-status reasoning supported, with exact cutoff availability left unresolved.",
        "rationale": (
            "The approved Result is the earlier overall-survival cutoff. The article's randomized analysis denominator and follow-up statement support near-complete survival information at that cutoff. "
            "Later losses and withdrawals do not establish that status was missing by the earlier cutoff. The answer properly keeps exact cutoff availability uncertain."
        ),
        "unresolved_facts": (
            "The number with unknown vital status at the approved December 23, 2013 cutoff is not reported.",
            "The later withdrawal and loss records do not establish outcome availability at the earlier cutoff.",
        ),
        "follow_up": ("Review cutoff-specific vital-status accounting if it becomes available.",),
    },
    {
        "case_identity": "2026-09-26:overall-survival:enzamet",
        "outcome": "overall-survival",
        "domain": "domain:randomization",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.67,
        "sample_note": "AI source review found the low-risk Domain 1 reasoning consistent with the random component, central allocation, and balanced baseline evidence.",
        "rationale": (
            "The report identifies minimization with a random component, supporting random sequence generation. "
            "The protocol describes a central randomization system but not the operator or explicit access controls, so the answer's probable concealment judgment is appropriately qualified. "
            "The reported group sizes and prognostic factors are balanced."
        ),
        "unresolved_facts": (
            "The source packet does not identify the central system operator or explicitly state whether enrolling clinicians could access upcoming assignments.",
        ),
        "follow_up": ("Review the allocation-system operating record if concealment certainty is needed.",),
    },
    {
        "case_identity": "2026-09-26:overall-survival:titan",
        "outcome": "overall-survival",
        "domain": "domain:deviations",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.73,
        "sample_note": "AI source review found the participant and personnel masking and intention-to-treat reasoning supported by the captured report and protocol.",
        "rationale": (
            "The report states that participants and trial personnel were masked, and the protocol defines the efficacy population as all randomized participants. "
            "The saved answers support the information about awareness and assignment-based analysis; they do not infer context-driven deviations from awareness alone."
        ),
        "unresolved_facts": ("The source packet does not enumerate every treatment deviation and its cause.",),
        "follow_up": ("Review participant-level deviations only if evidence of context-driven departures emerges.",),
    },
    {
        "case_identity": "2026-09-26:overall-survival:arasens",
        "outcome": "overall-survival",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.76,
        "sample_note": "AI source review found the all-cause death method, common follow-up approach, and qualified masking inference supported.",
        "rationale": (
            "All-cause mortality is a direct, objective endpoint. The protocol describes the same long-term contacts and survival sweeps across groups, which supports but does not prove equal follow-up completion. "
            "The double-blind description supports the saved probable assessor-masking judgment; the answer notes that specific death-recording roles are not detailed."
        ),
        "unresolved_facts": (
            "Group-specific completion of survival follow-up and reasons for censoring are not reported.",
            "The source packet does not separately identify who confirmed each death or their masking status.",
        ),
        "follow_up": ("Review group-specific survival contact completion and death-verification procedures if available.",),
    },
    {
        "case_identity": "2026-09-26:progression-free-survival:enzamet",
        "outcome": "progression-free-survival",
        "domain": "domain:deviations",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.71,
        "sample_note": "AI source review found that open-label awareness was not treated as proof of context-driven deviation and the ITT analysis was supported.",
        "rationale": (
            "The report establishes participant and clinician awareness, while the protocol and article descriptions identify discontinuation and subsequent treatment compatible with the planned course or ordinary post-progression care. "
            "The ITT statement supports the assignment-effect analysis. The answer does not claim that no deviations occurred; it identifies that trial-context causation is not established."
        ),
        "unresolved_facts": ("The article does not provide a complete group-specific account of all treatment deviations and their causes.",),
        "follow_up": ("Review detailed treatment-deviation records if context-driven departures are suspected.",),
    },
    {
        "case_identity": "2026-09-26:overall-survival:arches",
        "outcome": "overall-survival",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.71,
        "sample_note": "AI source review found the objective all-cause mortality method and qualified differential-measurement and assessor judgments supportable.",
        "rationale": (
            "The report defines overall survival as death from any cause and uses one common randomized comparison. "
            "The captured evidence does not describe a detailed vital-status system or group-specific ascertainment schedule, and the answers state those limits. "
            "The double-blind design makes probable masking plausible but does not prove that the death assessor was blinded."
        ),
        "unresolved_facts": (
            "Group-specific vital-status ascertainment procedures are not described.",
            "The report does not identify the person or system confirming vital status or explicitly state assessor masking.",
        ),
        "follow_up": ("Review vital-status ascertainment and assessor procedures if available.",),
    },
    {
        "case_identity": "2026-09-26:adverse-events:peace-1",
        "outcome": "adverse-events",
        "domain": "domain:missing",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.63,
        "sample_note": "AI source review found near-complete safety denominators support the low-risk reasoning; outcomes for the small absent group remain unknown.",
        "rationale": (
            "The reported safety denominators include 347/355 and 350/355 randomized participants in the docetaxel population, approximately 98% in each arm. "
            "This supports the saved near-complete-data reasoning. The status of the 13 randomized participants outside those safety denominators is unknown, and the low label is not independently certified."
        ),
        "unresolved_facts": (
            "Severe-AE outcomes for the eight and five participants missing from the respective safety denominators are not reported.",
            "The source packet does not establish reasons for absence or whether those participants had any safety contact.",
        ),
        "follow_up": ("Review safety follow-up for the 13 randomized participants outside the reported safety denominators.",),
    },
    {
        "case_identity": "2026-09-26:overall-survival:arasens",
        "outcome": "overall-survival",
        "domain": "domain:selection",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.7,
        "sample_note": "AI source review found the cited primary analysis and multiplicity reasoning supported, while unblinded-access timing remains unresolved.",
        "rationale": (
            "The approved primary HR and test align with SAP v4.0 and the main report. The later v4.1 changes are described as fraud-related exclusion and sensitivity analysis; the answer does not treat these as outcome-driven selection. "
            "Fixed-time survival estimates and sensitivity analyses are not themselves proof that the primary HR was selected from favorable alternatives. The exact unblinded-access chronology remains unknown."
        ),
        "unresolved_facts": (
            "The timing of first unblinded OS access by investigators or sponsor statisticians is not reported.",
            "The source packet does not provide estimates for all planned sensitivity analyses.",
        ),
        "follow_up": ("Review dated SAP versions and outcome-access chronology if available.",),
    },
    {
        "case_identity": "2026-09-27:overall-survival:getug-afu-15",
        "outcome": "overall-survival",
        "domain": "domain:selection",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.74,
        "sample_note": "AI source review found the saved Some Concerns assessment appropriately reflects the missing historical plan and data-access chronology.",
        "rationale": (
            "The report describes an initial 36-month plan and a later common cutoff, plus several possible analyses, but the captured sources do not establish the applicable historical plan or when unblinded data became available. "
            "The answer correctly treats multiplicity as an audit signal rather than evidence that results drove selection. Some Concerns is supportable; the underlying chronology remains unresolved."
        ),
        "unresolved_facts": (
            "The applicable historical protocol or SAP, plan-finalization date, data-access chronology, and timing of the follow-up extension are not established.",
            "The complete eligible time-point and analysis sets are not available.",
        ),
        "follow_up": ("Review dated SAPs and the timing of unblinded outcome access and follow-up extension.",),
    },
    {
        "case_identity": "2026-09-27:progression-free-survival:latitude",
        "outcome": "progression-free-survival",
        "domain": "domain:deviations",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.72,
        "sample_note": "AI source review found the double-blind design, randomized-group ITT analysis, and qualified awareness reasoning supported by saved sources.",
        "rationale": (
            "The report and protocol describe double-blind treatment and restrictions on code access. The answer acknowledges possible participant guesses from adverse effects without claiming that masking was shown to fail. "
            "The protocol-defined randomized efficacy population and report denominators support the assignment-effect analysis."
        ),
        "unresolved_facts": (
            "Whether any participant or intervention-delivery personnel correctly inferred assignment is not reported.",
            "The cited passages do not list endpoint-specific participants included in the PFS model.",
        ),
        "follow_up": ("Review masking success data and the final PFS analysis population if available.",),
    },
    {
        "case_identity": "2026-09-27:overall-survival:enzamet",
        "outcome": "overall-survival",
        "domain": "domain:deviations",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.71,
        "sample_note": "AI source review found the open-label facts, ordinary post-progression care, and ITT analysis reasoning supported, with full deviation detail unavailable.",
        "rationale": (
            "The trial is open-label, but awareness alone does not establish trial-context-driven deviations. The protocol and report describe treatment discontinuation and subsequent care compatible with progression, toxicity, participant choice, or ordinary post-progression treatment. "
            "The ITT analysis supports the assignment effect. The answer keeps the incomplete deviation accounting visible."
        ),
        "unresolved_facts": ("The report does not enumerate all deviations from assigned treatment or explain every discontinuation.",),
        "follow_up": ("Review detailed treatment-deviation records if context-driven departures are suspected.",),
    },
    {
        "case_identity": "2026-09-27:overall-survival:arches",
        "outcome": "overall-survival",
        "domain": "domain:randomization",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.68,
        "sample_note": "AI source review found no disclosed random sequence method, probable central concealment, and baseline balance consistent with the saved low-risk judgment.",
        "rationale": (
            "Central 1:1 randomization establishes an assignment process but does not disclose sequence generation, which the answer correctly records as unavailable. "
            "It supports probable concealment, though the source does not name the operator or access restrictions. The baseline table is broadly balanced; the noted disease-volume correction is explained as a reporting correction rather than a sequence problem."
        ),
        "unresolved_facts": (
            "The allocation sequence-generation method is not reported.",
            "The central allocation operator and independence from enrollment personnel are not identified.",
        ),
        "follow_up": ("Review the randomization system record if sequence or concealment certainty is required.",),
    },
    {
        "case_identity": "2026-09-27:progression-free-survival:arches",
        "outcome": "progression-free-survival",
        "domain": "domain:randomization",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.68,
        "sample_note": "AI source review found sequence generation unavailable, probable central concealment, and baseline balance consistent with the saved low-risk judgment.",
        "rationale": (
            "The cited report states central 1:1 randomization but gives no sequence-generation method. That supports the answer's no-information response for sequence generation and qualified probable concealment. "
            "Baseline group sizes and prognostic characteristics are similar. No cited imbalance suggests a problem with randomization."
        ),
        "unresolved_facts": (
            "The allocation sequence-generation method is not reported.",
            "The source packet does not identify the allocation operator or enrollment access controls.",
        ),
        "follow_up": ("Review the randomization system record if sequence or concealment certainty is required.",),
    },
    {
        "case_identity": "2026-09-27:overall-survival:titan",
        "outcome": "overall-survival",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.74,
        "sample_note": "AI source review found the objective death definition, common survival follow-up, and assessor-masking reasoning supported.",
        "rationale": (
            "The Result is all-cause death, and the report/protocol describe repeated survival follow-up using common contact approaches across groups, including after study-drug discontinuation. "
            "The trial masking statement supports assessor awareness reasoning. The report cannot rule out unreported emergency unblinding, so the saved exception is retained."
        ),
        "unresolved_facts": (
            "Group-specific survival follow-up completion and any individual emergency unblinding are not reported.",
        ),
        "follow_up": ("Review group-specific vital-status follow-up and any unblinding before the interim cutoff if available.",),
    },
    {
        "case_identity": "2026-09-27:progression-free-survival:chaarted",
        "outcome": "progression-free-survival",
        "domain": "domain:missing",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.68,
        "sample_note": "AI source review found near-complete PFS follow-up evidence supports Low while exact censoring and withdrawal status remain unavailable.",
        "rationale": (
            "The flow diagram documents follow-up for nearly all randomized participants and only one without follow-up. The supplement explains censoring at the last clinical disease evaluation. "
            "The answer appropriately notes that these counts do not resolve timing and reasons for each withdrawal or establish endpoint-specific outcome availability."
        ),
        "unresolved_facts": (
            "Endpoint-specific event and censor totals and the timing and reason for each withdrawal or loss are not reported.",
        ),
        "follow_up": ("Review participant-level progression assessment and vital-status follow-up at the approved cutoff if available.",),
    },
    {
        "case_identity": "2026-09-27:progression-free-survival:titan",
        "outcome": "progression-free-survival",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.73,
        "sample_note": "AI source review found the standard progression method, common imaging schedule, and qualified assessor masking reasoning supported.",
        "rationale": (
            "The report uses modified RECIST/PCWG2 imaging and a common scheduled imaging calendar; the protocol specifies use of the same modality per participant and allows symptom-prompted unscheduled imaging. "
            "No group-specific method or schedule is reported. The answer explicitly leaves actual group-specific scan frequency and emergency unblinding unresolved."
        ),
        "unresolved_facts": (
            "Actual imaging frequency, unscheduled scans, and group-specific delivery of imaging are not reported.",
            "Whether any PFS assessment followed emergency unblinding is unknown.",
        ),
        "follow_up": ("Compare actual imaging frequency and unblinding records by randomized group if available.",),
    },
    {
        "case_identity": "2026-09-27:progression-free-survival:arches",
        "outcome": "progression-free-survival",
        "domain": "domain:deviations",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.71,
        "sample_note": "AI source review found the matching-placebo masking and intent-to-treat analysis evidence supportable, with masking-role detail limited.",
        "rationale": (
            "The double-blind placebo-controlled design supports probable participant and intervention-personnel masking, while the answer records that the report does not identify all masking roles or treatment-code access. "
            "The supplement defines the efficacy population as all randomized participants, and the randomized group counts support the PFS assignment-effect analysis."
        ),
        "unresolved_facts": (
            "Which study personnel were masked and who could access treatment assignments is not described.",
        ),
        "follow_up": ("Review the trial masking plan and final rPFS analysis population if available.",),
    },
    {
        "case_identity": "2026-09-27:overall-survival:getug-afu-15",
        "outcome": "overall-survival",
        "domain": "domain:measurement",
        "classification": AdjudicationClassification.AGREEMENT,
        "confidence": 0.73,
        "sample_note": "AI source review found objective all-cause death and common cutoff reasoning support Low, while assessor awareness remains separate from outcome influence.",
        "rationale": (
            "All-cause death is an objective event. The report notes more frequent clinical checks during docetaxel but gives a common survival endpoint and last-visit/common-cutoff rule with no loss to follow-up. "
            "Investigators were unmasked, but the answer reasonably distinguishes awareness from plausible influence over whether or when a participant died and notes no independent vital-status verification details."
        ),
        "unresolved_facts": (
            "The source packet does not identify who independently verified each death date or whether an external vital-status source was used.",
        ),
        "follow_up": ("Review death-date verification and vital-status ascertainment procedures if available.",),
    },
)

_QUESTION_CLASSIFICATION_OVERRIDES: dict[tuple[str, str], AdjudicationClassification] = {
    (
        "2026-09-26:adverse-events:latitude",
        "sq:measurement:differential",
    ): AdjudicationClassification.LIKELY_MODEL_ERROR,
}


def _normalise(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _label(value: str) -> CohortLabel:
    cleaned = value.strip()
    if cleaned in _CODE_LABELS:
        return _CODE_LABELS[cleaned]
    try:
        return _NAME_LABELS[cleaned.casefold()]
    except KeyError as error:
        raise ValueError(f"unsupported risk label: {value}") from error


def _reference_catalog(reference: Path, outcome: str) -> dict[str, tuple[CohortLabel, ...]]:
    path = reference / "catalog" / "provisional-labels" / _OUTCOME_FILES[outcome]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {
            _normalise(row["Trial"]): tuple(_label(row[f"D{i}"]) for i in range(1, 6))
            for row in csv.DictReader(stream)
        }


def _case_key(case: dict[str, Any]) -> tuple[str, str]:
    return (_OUTCOMES[case["outcome"].casefold()], _normalise(case["trial"]))


def _all_cases(score: dict[str, Any]) -> list[dict[str, Any]]:
    cases = list(score.get("cases", ())) + list(score.get("scope_difference_cases", ()))
    identities = [_case_key(case) for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("score file contains duplicate outcome/Trial cases")
    return cases


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "eval" and (parent.parent / "pyproject.toml").is_file():
            return resolved.relative_to(parent.parent).as_posix()
    raise ValueError(f"source path is not inside a rob2-kit checkout: {path}")


def _calls(paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
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
                receipt = result.get("structured_content", result.get("structuredContent"))
                if isinstance(receipt, dict):
                    calls.append({"tool": item.get("tool"), "receipt": receipt})
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


def _selected_trace(bundle: Path) -> tuple[Path, ...]:
    attempt_directory = bundle.parents[3]

    def phase_number(path: Path) -> int:
        match = re.search(r"phase-(\d+)", path.name)
        if match is None:
            raise ValueError(f"trace segment has no phase number: {path}")
        return int(match.group(1))

    segments = tuple(
        sorted(
            attempt_directory.glob("phase-*.jsonl"),
            key=phase_number,
        )
    )
    if not segments:
        raise ValueError(f"no JSONL trace segments beside selected bundle: {bundle}")
    return segments


def _review_from_trace(
    paths: tuple[Path, ...],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]:
    calls = _calls(paths)
    assessed: list[tuple[dict[str, Any], list[Any]]] = []
    for call in calls:
        if call["tool"] != "review_trial":
            continue
        data = call["receipt"].get("data", {})
        review = data.get("review")
        findings = data.get("domain_findings")
        if (
            data.get("review_page", {}).get("mode", "complete") == "complete"
            and isinstance(review, dict)
            and review.get("disposition") == "assessed"
            and isinstance(findings, list)
            and len(findings) == len(DOMAINS)
        ):
            assessed.append((review, findings))
    if not assessed:
        raise ValueError(f"no complete assessed review receipt in {paths}")
    review, findings = assessed[-1]
    by_domain = {item.get("domain_id"): item for item in findings if isinstance(item, dict)}
    if set(by_domain) != set(DOMAINS):
        raise ValueError(f"assessed review has incomplete Domain findings in {paths}")

    projections: dict[str, set[str]] = defaultdict(set)
    for obj in _walk(calls):
        source_id = obj.get("source_id")
        if (
            not isinstance(source_id, str)
            and isinstance(obj.get("id"), str)
            and isinstance(obj.get("projection_hash"), str)
        ):
            source_id = obj["id"]
        projection = obj.get("projection_hash")
        if isinstance(source_id, str) and isinstance(projection, str):
            projections[source_id].add(projection)
    if not projections or any(len(values) != 1 for values in projections.values()):
        raise ValueError(f"missing or inconsistent source projections in {paths}")
    return review, by_domain, {key: next(iter(values)) for key, values in projections.items()}


def _scope_cases(
    scope_score: dict[str, Any], campaign: str
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], dict[tuple[str, str], str]]:
    included_cases = list(scope_score.get("cases", ()))
    scope_difference_cases = list(scope_score.get("scope_difference_cases", ()))
    excluded_cases = list(scope_score.get("excluded_cases", ()))
    included = {_case_key(case) for case in included_cases}
    scope_differences = {_case_key(case) for case in scope_difference_cases}
    reasons = {
        _case_key(case): str(case.get("scope_note", case.get("rationale", "")))
        for case in [*scope_difference_cases, *excluded_cases]
    }
    if campaign == "2026-09-26":
        return included | scope_differences, scope_differences, reasons
    return included, scope_differences, reasons


def _published_totals(
    cells: list[CohortCell], unit: Literal["outcome", "domain"]
) -> dict[str, PublishedTotals]:
    key_for = (lambda cell: cell.outcome_id) if unit == "outcome" else (lambda cell: cell.domain_id)
    grouped: dict[str, list[CohortCell]] = defaultdict(list)
    for cell in cells:
        grouped[key_for(cell)].append(cell)
    return {
        key: PublishedTotals(
            unit=unit,
            assessments=len({cell.case_identity for cell in rows}),
            domain_cells=len(rows),
            exact_matches=sum(cell.comparison == "agreement" for cell in rows),
            disagreements=sum(cell.comparison == "disagreement" for cell in rows),
        )
        for key, rows in grouped.items()
    }


def _build_campaign(
    campaign: str,
    run_root: Path,
    score: dict[str, Any],
    scope_score: dict[str, Any],
    reference: Path,
) -> tuple[CohortManifest, dict[tuple[str, str], dict[str, Any]], set[Path]]:
    cases = _all_cases(score)
    if len(cases) != 26:
        raise ValueError(f"{campaign} score must contain 26 cases, found {len(cases)}")
    scope_eligible, scope_differences, scope_reasons = _scope_cases(scope_score, campaign)
    scope_excluded = {_case_key(case) for case in scope_score.get("excluded_cases", ())}
    cells: list[CohortCell] = []
    case_rows: dict[tuple[str, str], dict[str, Any]] = {}
    case_ids: list[str] = []
    selected_logs: set[Path] = set()
    catalog_cache: dict[str, dict[str, tuple[CohortLabel, ...]]] = {}
    for case in cases:
        outcome = _OUTCOMES[case["outcome"].casefold()]
        trial = case["trial"]
        key = _case_key(case)
        if outcome not in catalog_cache:
            catalog_cache[outcome] = _reference_catalog(reference, outcome)
        catalog_labels = catalog_cache[outcome].get(_normalise(trial))
        if catalog_labels is None:
            raise ValueError(f"reference catalog has no {outcome}/{trial}")
        expected = tuple(_label(case["expected"][f"D{i}"]) for i in range(1, 6))
        observed = tuple(_label(case["observed"][f"D{i}"]) for i in range(1, 6))
        if expected != catalog_labels:
            raise ValueError(f"score reference labels differ from catalog for {outcome}/{trial}")

        bundle = Path(case["bundle"])
        if not bundle.is_file():
            raise ValueError(f"selected result bundle is missing: {bundle}")
        bundle_sha256 = case.get("bundle_sha256", _sha256(bundle))
        bundle_identity = case.get("bundle_identity", f"sha256:{bundle.stem}")
        if _sha256(bundle) != bundle_sha256:
            raise ValueError(f"selected result bundle hash differs from score file: {bundle}")
        segments = _selected_trace(bundle)
        selected_logs.update(segments)
        review, findings, projection_map = _review_from_trace(segments)
        trial_id = review.get("trial_id")
        if not isinstance(trial_id, str) or _normalise(trial_id) != _normalise(trial):
            raise ValueError(f"trace Trial differs from score row: {outcome}/{trial}")
        result_identity = review.get("result_identity")
        review_identity = review.get("identity")
        if not isinstance(result_identity, str) or not isinstance(review_identity, str):
            raise ValueError(f"trace review lacks immutable identities: {outcome}/{trial}")
        if (
            review_identity.startswith("sha256:") is False
            or result_identity.startswith("sha256:") is False
        ):
            raise ValueError(f"trace review identities are not content hashes: {outcome}/{trial}")
        case_identity = f"{campaign}:{outcome}:{trial_id}"
        case_ids.append(case_identity)
        segment_refs = [f"{_repo_relative(path)}#sha256:{_sha256(path)}" for path in segments]
        for index, domain_id in enumerate(DOMAINS):
            finding = findings[domain_id]
            model_label = _label(str(finding.get("judgment", "")))
            if model_label != observed[index]:
                raise ValueError(f"trace and score labels differ for {outcome}/{trial}/{domain_id}")
            answers = finding.get("answers")
            if not isinstance(answers, list) or not answers:
                raise ValueError(f"no question bindings in {outcome}/{trial}/{domain_id}")
            source_ids = {
                window.get("source_id")
                for answer in answers
                if isinstance(answer, dict)
                for expansion in answer.get("evidence_expansions", ())
                if isinstance(expansion, dict)
                for window in expansion.get("windows", ())
                if isinstance(window, dict) and isinstance(window.get("source_id"), str)
            }
            scope = "answer_expansions"
            if not source_ids:
                source_ids = set(projection_map)
                scope = "case_source_inventory"
            elif not source_ids <= set(projection_map):
                raise ValueError(
                    f"Domain sources have no projection: {outcome}/{trial}/{domain_id}"
                )
            question_ids = tuple(
                answer["question_id"]
                for answer in answers
                if isinstance(answer, dict) and isinstance(answer.get("question_id"), str)
            )
            if not question_ids:
                raise ValueError(
                    f"Domain has no question identities: {outcome}/{trial}/{domain_id}"
                )
            cells.append(
                CohortCell(
                    campaign_id=campaign,
                    case_identity=case_identity,
                    trial_id=trial_id,
                    outcome_id=outcome,
                    result_identity=result_identity,
                    review_identity=review_identity,
                    domain_id=domain_id,
                    question_ids=question_ids,
                    checkpoint_identity=str(finding.get("checkpoint_identity", "")),
                    source_identities=tuple(sorted(source_ids)),
                    source_projection_ids=tuple(
                        sorted({projection_map[source] for source in source_ids})
                    ),
                    source_projection_scope=scope,
                    reference_label=expected[index],
                    model_label=model_label,
                    reviewer_provenance=ReviewerProvenance(
                        note="Scientific classification is pending except for separate source-audit sidecars."
                    ),
                    trace_reference=";".join(segment_refs),
                )
            )
        case_rows[key] = {
            "case_identity": case_identity,
            "outcome": outcome,
            "trial": trial,
            "scope_status": (
                "excluded_mismatch"
                if key in scope_excluded
                else "accepted_scope_difference"
                if key in scope_differences and campaign == "2026-09-27"
                else "accepted_proxy"
                if key in scope_differences
                else "exact"
                if key in scope_eligible
                else "not_in_scope_sensitivity"
            ),
            "primary_scope_eligible": key in scope_eligible and key not in scope_differences,
            "accepted_scope_sensitivity_eligible": key in scope_eligible
            or key in scope_differences,
            "scope_note": scope_reasons.get(key, case.get("scope_note", "")),
            "result_identity": result_identity,
            "review_identity": review_identity,
            "bundle_reference": _repo_relative(bundle),
            "bundle_sha256": bundle_sha256,
            "bundle_identity": bundle_identity,
            "_bundle_path": bundle,
            "trace_segments": [
                {
                    "path": _repo_relative(path),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in segments
            ],
            "reference_labels": [label.value for label in expected],
            "model_labels": [label.value for label in observed],
            "cohort_cell_identities": [],
        }
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"{campaign} has duplicate case identities")
    if len(cells) != 130:
        raise ValueError(f"{campaign} must contain 130 Domain cells, found {len(cells)}")

    by_case_domain = {(cell.case_identity, cell.domain_id): cell for cell in cells}
    for row in case_rows.values():
        row["cohort_cell_identities"] = [
            by_case_domain[(row["case_identity"], domain)].identity for domain in DOMAINS
        ]

    seed = f"rob2-kit-{campaign}-agreement-sample-v1"
    required: tuple[str, ...] = ()
    if campaign == "2026-09-26":
        pinned = by_case_domain[("2026-09-26:overall-survival:arasens", "domain:missing")]
        if pinned.comparison != "agreement":
            raise ValueError("ARASENS OS D3 must remain an exact-label agreement in September 26")
        required = (str(pinned.identity),)
    sample = list(
        select_agreement_sample(
            cells,
            seed=seed,
            size=10,
            required_cell_identities=required,
        )
    )
    if required:
        sample[0] = AgreementSampleEntry(
            cell_identity=sample[0].cell_identity,
            selection_seed=sample[0].selection_seed,
            selection_rank=sample[0].selection_rank,
            dimensions=sample[0].dimensions,
            review_status="complete",
            reviewer_provenance=ReviewerProvenance(
                status="complete",
                reviewer_identity=_REVIEWER,
                reviewer_role=_REVIEWER_ROLE,
                reviewed_at=_REVIEWED_AT,
                note=(
                    "AI source-grounded review found an unsupported reassurance warrant. "
                    "This does not certify a human-expert label or prove the final Low label false."
                ),
            ),
        )
    review_by_cell = {
        (finding["case_identity"], finding["domain"]): finding
        for finding in _AGREEMENT_SAMPLE_REVIEWS
    }
    cell_by_identity = {str(cell.identity): cell for cell in cells}
    for index, entry in enumerate(sample):
        cell = cell_by_identity[entry.cell_identity]
        finding = review_by_cell.get((cell.case_identity, cell.domain_id))
        if finding is None:
            continue
        sample[index] = AgreementSampleEntry(
            cell_identity=entry.cell_identity,
            selection_seed=entry.selection_seed,
            selection_rank=entry.selection_rank,
            dimensions=entry.dimensions,
            review_status="complete",
            reviewer_provenance=ReviewerProvenance(
                status="complete",
                reviewer_identity=_AGREEMENT_REVIEWER,
                reviewer_role=_REVIEWER_ROLE,
                reviewed_at=_AGREEMENT_REVIEWED_AT,
                note=finding["sample_note"],
            ),
        )
    manifest = CohortManifest(
        campaign_id=campaign,
        pinned_run=_repo_relative(run_root),
        reference_catalog=_repo_relative(reference / "catalog" / "provisional-labels"),
        cells=tuple(cells),
        partitions=CohortPartitions(development_case_ids=tuple(sorted(set(case_ids)))),
        published_outcome_totals=_published_totals(cells, "outcome"),
        published_domain_totals=_published_totals(cells, "domain"),
        agreement_sample=tuple(sample),
        model_access=ModelAccess(
            note=(
                "These post-run labels and source audits are development evidence. "
                "The assessments did not receive this cohort or its adjudications. "
                "Exact model prompt bytes are not captured for every attempt."
            )
        ),
        note=(
            "All cases are development material. Original labels and trace judgments are retained. "
            "The cohort contains no corrected accuracy; source-audit sidecars are separately attributed."
        ),
    )
    return manifest, case_rows, selected_logs


def _canonical_sources(bundle: Path) -> dict[str, str]:
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    sources: dict[str, str] = {}
    for trial in canonical.get("batch", {}).get("trials", ()):
        for source in trial.get("sources", ()):
            source_id = source.get("id")
            label = source.get("label")
            if isinstance(source_id, str) and isinstance(label, str):
                sources[label] = source_id
    return sources


_SOURCE_AUDITS: tuple[SourceAuditFinding, ...] = (
    {
        "campaign": "2026-09-26",
        "outcome": "overall-survival",
        "trial": "ARASENS",
        "domain": "domain:missing",
        "question_ids": ("sq:missing:data-available",),
        "classification": AdjudicationClassification.LIKELY_MODEL_ERROR,
        "confidence": 0.8,
        "source_files": ("main_article.pdf", "ClinicalTrials.gov NCT02799602"),
        "evidence": (
            (
                "main_article.pdf",
                "CONSORT flow diagram, PDF p. 4",
                "Deaths and censorings sum to the analyzed denominators, but the flow diagram does not establish complete outcome availability.",
            ),
            (
                "ClinicalTrials.gov NCT02799602",
                "Enrollment and analysis record",
                "Registry counts describe analysis accounting, not the reasons for censoring.",
            ),
        ),
        "rationale": "The saved answer infers nearly complete availability because deaths plus censorings equal the analyzed denominators. The answer acknowledges that censoring reasons are unknown. These counts do not establish that participants with censored outcomes remained observed. The Low label matches the catalog, but the warrant is unsupported and the final label is not thereby proven false.",
        "unresolved_facts": (
            "The reasons and timing for censoring are not established by the cited totals.",
        ),
        "follow_up": ("Review the full follow-up record before changing the final Domain label.",),
        "attribution": "Relevant counts were retrieved and the unsupported step is interpretation. Full model context is not captured.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "overall-survival",
        "trial": "CHAARTED",
        "domain": "domain:deviations",
        "question_ids": (
            "sq:deviations:context-deviations",
            "sq:deviations:affected-outcome",
            "sq:deviations:balanced",
        ),
        "classification": AdjudicationClassification.INDETERMINATE,
        "confidence": 0.4,
        "source_files": ("main_article.pdf", "supplement.pdf"),
        "evidence": (
            (
                "main_article.pdf",
                "Treatment and CONSORT flow, PDF pp. 2–3",
                "The trial was unmasked and the flow diagram reports participants who did not start assigned docetaxel.",
            ),
            (
                "supplement.pdf",
                "Supplemental participant flow",
                "The report gives withdrawal or refusal reasons for the non-starters, including one medical decision.",
            ),
        ),
        "rationale": "The saved High judgment treats documented non-initiation in an unmasked trial as a trial-context departure affecting survival. The trace cites participant withdrawals or refusals and one medical decision. Their reasons do not establish that the departures arose from trial context rather than ordinary treatment decisions. The evidence supports review of the inference but does not establish that the model's label is wrong.",
        "unresolved_facts": (
            "The circumstances behind the refusals and medical decision are not reported.",
            "Deaths among the non-starters are not reported.",
        ),
        "follow_up": (
            "Have an independent RoB 2 reviewer assess whether the non-initiation was caused by trial context.",
        ),
        "attribution": "The facts are present in the saved evidence. The causal interpretation is uncertain. Policy and capacity attribution are not established.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "adverse-events",
        "trial": "TITAN",
        "domain": "domain:missing",
        "question_ids": ("sq:missing:likely-dependent",),
        "classification": AdjudicationClassification.INDETERMINATE,
        "confidence": 0.5,
        "source_files": ("main_article.pdf", "protocol.pdf"),
        "evidence": (
            (
                "main_article.pdf",
                "Participant flow and safety population, PDF p. 4",
                "The article reports 39 participants lost or withdrawn from all further data collection and separately reports participants who continued secondary endpoint follow-up.",
            ),
            (
                "protocol.pdf",
                "End-of-treatment and post-dose safety follow-up",
                "The protocol defines planned safety contacts but does not establish observed completion for the 39 losses.",
            ),
        ),
        "rationale": "The High judgment follows the saved No-information branch for likely outcome-dependent missingness. The sources do not map the 39 losses to the adverse-event observation window or randomized arm. The safety denominator alone does not establish outcome availability, and planned follow-up does not establish completion.",
        "unresolved_facts": (
            "The adverse-event window completion and arm allocation of the 39 losses are unknown.",
        ),
        "follow_up": ("Inspect participant-level follow-up and safety-window completion records.",),
        "attribution": "The trace captures source availability and answer evidence. The branch follows the official uncertainty rule; a model or policy defect is not established.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "adverse-events",
        "trial": "TITAN",
        "domain": "domain:measurement",
        "question_ids": ("sq:measurement:differential",),
        "classification": AdjudicationClassification.INDETERMINATE,
        "confidence": 0.45,
        "source_files": ("main_article.pdf", "protocol.pdf"),
        "evidence": (
            (
                "main_article.pdf",
                "Blinding, monthly AE assessment, and exposure, PDF pp. 1–4",
                "The article reports double blinding, shared monthly CTCAE assessment, and median exposure of 20.5 versus 18.3 months.",
            ),
            (
                "protocol.pdf",
                "Safety assessment schedule",
                "The protocol specifies a common end-of-treatment visit and 30-day post-dose AE window.",
            ),
        ),
        "rationale": "Longer exposure creates more time at risk and could increase cumulative AE ascertainment. The saved answer identifies shared monthly assessment and grading, then infers differential measurement from the exposure difference. This is a plausible concern, but the evidence does not show a different measurement method or assessor. The Low versus High severity remains unresolved.",
        "unresolved_facts": (
            "The effect of exposure duration on ascertainment within the stated safety estimand is not quantified.",
        ),
        "follow_up": (
            "Review the target safety estimand and ascertainment opportunity by randomized arm.",
        ),
        "attribution": "The exposure and shared schedule were retrieved. The disputed step is interpretation; full model context is not captured.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "adverse-events",
        "trial": "STAMPEDE",
        "domain": "domain:measurement",
        "question_ids": ("sq:measurement:differential",),
        "classification": AdjudicationClassification.DEFENSIBLE_DEVIATION,
        "confidence": 0.7,
        "source_files": ("main_article.pdf", "supplement.pdf"),
        "evidence": (
            (
                "main_article.pdf",
                "Follow-up schedule, PDF p. 3",
                "The report describes scheduled assessments that differ for combination-therapy participants.",
            ),
            (
                "supplement.pdf",
                "SAP version 2, safety follow-up section",
                "The SAP links routine adverse-event reporting to follow-up visits and specifies standardized CTCAE grading.",
            ),
        ),
        "rationale": "The sources describe additional scheduled assessments for combination-therapy participants and link routine AE reporting to follow-up visits. That difference supports the model's concern about unequal opportunity to identify or report events. The size of the difference is not reported, so High versus Some Concerns remains a severity judgment.",
        "unresolved_facts": (
            "The actual size of the visit-schedule difference and its impact on the assessed estimand are not reported.",
        ),
        "follow_up": (
            "Assess whether the extra visits changed AE ascertainment for the approved safety Result.",
        ),
        "attribution": "The schedule was retrieved and supports the model premise. Severity and policy attribution remain unresolved.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "adverse-events",
        "trial": "STAMPEDE",
        "domain": "domain:selection",
        "question_ids": ("sq:selection:prespecified-analysis",),
        "classification": AdjudicationClassification.INDETERMINATE,
        "confidence": 0.5,
        "source_files": ("main_article.pdf", "supplement.pdf"),
        "evidence": (
            (
                "supplement.pdf",
                "SAP version 2, p. 42",
                "The SAP describes a safety window through 30 days after treatment.",
            ),
            (
                "main_article.pdf",
                "AE results and Table 2, PDF pp. 6 and 10",
                "The report presents worst grade 3–5 events over the entire time in the trial and says analyses followed prespecified criteria.",
            ),
        ),
        "rationale": "The SAP safety window differs from the report's entire-trial summary. The mismatch is a valid audit lead, but it does not show that investigators selected the reported result based on its findings. The captured materials do not establish the applicable analysis plan or result-selection chronology.",
        "unresolved_facts": (
            "The full result-selection chronology and applicable SAP version are not established.",
        ),
        "follow_up": (
            "Review dated SAP versions and when unblinded outcome data became available.",
        ),
        "attribution": "The plan and report passages were retrieved. Their applicability and interpretation remain unresolved.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "adverse-events",
        "trial": "PEACE-1",
        "domain": "domain:measurement",
        "question_ids": ("sq:measurement:differential",),
        "classification": AdjudicationClassification.DEFENSIBLE_DEVIATION,
        "confidence": 0.75,
        "source_files": ("main_article.pdf", "supplement.pdf"),
        "evidence": (
            (
                "supplement.pdf",
                "Additional laboratory monitoring schedule",
                "The supplement specifies extra liver-function monitoring in abiraterone arms during treatment.",
            ),
            (
                "main_article.pdf",
                "Open-label design and safety endpoint, PDF pp. 1 and 4",
                "The report identifies the open-label design, CTCAE grading, and safety observation window.",
            ),
        ),
        "rationale": "Additional AST, ALT, and bilirubin monitoring in abiraterone arms could detect more severe laboratory adverse events. The source packet supports a differential ascertainment mechanism for this safety endpoint. The magnitude remains unknown, but the model's High concern is scientifically defensible relative to the provisional Some Concerns label.",
        "unresolved_facts": (
            "The magnitude of the additional monitoring's effect on the endpoint is unknown.",
        ),
        "follow_up": (
            "Estimate the impact of the differential laboratory schedule on the approved safety Result.",
        ),
        "attribution": "The extra monitoring schedule is in the saved source record and supports the model concern. Magnitude and policy attribution are not established.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "progression-free-survival",
        "trial": "STAMPEDE",
        "domain": "domain:selection",
        "question_ids": ("sq:selection:prespecified-analysis",),
        "classification": AdjudicationClassification.DEFENSIBLE_DEVIATION,
        "confidence": 0.65,
        "source_files": ("main_article.pdf", "supplement.pdf"),
        "evidence": (
            (
                "supplement.pdf",
                "SAP version 2 cover and PFS definition",
                "The SAP predates the report and specifies the PFS endpoint.",
            ),
            (
                "main_article.pdf",
                "Methods and analysis statement, PDF p. 3",
                "The report says analyses followed prespecified criteria and names CTU authors who accessed raw data.",
            ),
        ),
        "rationale": "The SAP predates the report and defines PFS, but the captured sources do not show when investigators first accessed unblinded outcomes. The model's Some Concerns call is a conservative reading of that missing chronology. The catalog Low label is also plausible, so this difference is not a decisive model error.",
        "unresolved_facts": ("The timing of first unblinded outcome access is not stated.",),
        "follow_up": ("Review dated data-access and SAP approval records.",),
        "attribution": "The SAP and analysis statement were retrieved. The remaining uncertainty is in the evidence interpretation, not a proven policy defect.",
    },
    {
        "campaign": "2026-09-27",
        "outcome": "progression-free-survival",
        "trial": "PEACE-1",
        "domain": "domain:selection",
        "question_ids": ("sq:selection:prespecified-analysis",),
        "classification": AdjudicationClassification.INDETERMINATE,
        "confidence": 0.5,
        "source_files": ("supplement.pdf",),
        "evidence": (
            (
                "supplement.pdf",
                "PDF p. 9, amendment 32",
                "The supplement records endpoint and testing-strategy changes and says the amendments were made without reference to outcomes.",
            ),
        ),
        "rationale": "The supplement documents a real endpoint and testing-strategy change and says the amendments were made without reference to outcomes. Exact final SAP approval and first unblinded access remain unknown. The evidence supports both the concern and counterevidence against results-driven selection, so the final difference remains unresolved.",
        "unresolved_facts": (
            "The final SAP approval and first unblinded outcome access dates are unknown.",
        ),
        "follow_up": ("Review the dated amendments, SAP versions, and outcome-access chronology.",),
        "attribution": "The amendment source was retrieved. The chronology is incomplete, and policy or model attribution is not established.",
    },
)


def _source_audits(
    cohorts: dict[str, CohortManifest],
    cases_by_campaign: dict[str, dict[tuple[str, str], dict[str, Any]]],
) -> tuple[AdjudicationSidecar, ...]:
    records: list[AdjudicationSidecar] = []
    for finding in _SOURCE_AUDITS:
        campaign = finding["campaign"]
        outcome = finding["outcome"]
        trial = finding["trial"]
        case = cases_by_campaign[campaign][(outcome, _normalise(trial))]
        by_domain = {(cell.case_identity, cell.domain_id): cell for cell in cohorts[campaign].cells}
        cell = by_domain[(case["case_identity"], finding["domain"])]
        if not set(finding["question_ids"]) <= set(cell.question_ids):
            raise ValueError(
                f"source-audit question is absent from selected review: {outcome}/{trial}/{finding['domain']}"
            )
        case_score = next(
            row
            for row in cases_by_campaign[campaign].values()
            if row["case_identity"] == case["case_identity"]
        )
        bundle = case_score["_bundle_path"]
        sources = _canonical_sources(bundle)
        missing_sources = set(finding["source_files"]) - set(sources)
        if missing_sources:
            raise ValueError(
                f"source-audit files are absent from selected bundle: {sorted(missing_sources)}"
            )
        source_ids = tuple(sources[name] for name in finding["source_files"])
        evidence = tuple(
            EvidenceLocator(
                source_identity=sources[file_name],
                locator=locator,
                note=note,
            )
            for file_name, locator, note in finding["evidence"]
        )
        for question_id in finding["question_ids"]:
            records.append(
                AdjudicationSidecar(
                    run_identity=campaign,
                    case_identity=cell.case_identity,
                    result_identity=cell.result_identity,
                    domain_identity=cell.domain_id,
                    question_identity=question_id,
                    checkpoint_identity=cell.checkpoint_identity,
                    source_identities=source_ids,
                    reference_label=cell.reference_label.value,
                    model_label=cell.model_label.value,
                    provisional_label=cell.reference_label.value,
                    classification=finding["classification"],
                    evidence=evidence,
                    rationale=finding["rationale"],
                    unresolved_facts=finding["unresolved_facts"],
                    follow_up=finding["follow_up"],
                    reviewer_identity=_REVIEWER,
                    reviewer_role=_REVIEWER_ROLE,
                    adjudication_version="2026-09-27-source-audit-v1",
                    reviewed_at=_REVIEWED_AT,
                    confidence=finding["confidence"],
                )
            )
    identities = [record.identity for record in records]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate source-audit sidecar record")
    return tuple(records)


def _canonical_source_handles(bundle: Path) -> dict[str, tuple[str, str, str]]:
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    handles: dict[str, tuple[str, str, str]] = {}
    for trial in canonical.get("batch", {}).get("trials", ()):
        for source in trial.get("sources", ()):
            source_id = source.get("id")
            label = source.get("label")
            projection = source.get("projection_hash")
            if (
                isinstance(source_id, str)
                and source_id.startswith("source_")
                and isinstance(label, str)
                and isinstance(projection, str)
            ):
                handles[f"sh_{source_id.removeprefix('source_')[:16]}"] = (
                    source_id,
                    label,
                    projection,
                )
    return handles


def _agreement_sample_audits(
    cohorts: dict[str, CohortManifest],
    cases_by_campaign: dict[str, dict[tuple[str, str], dict[str, Any]]],
) -> tuple[AdjudicationSidecar, ...]:
    records: list[AdjudicationSidecar] = []
    cells_by_campaign = {
        campaign: {
            (cell.case_identity, cell.domain_id): cell
            for cell in cohort.cells
        }
        for campaign, cohort in cohorts.items()
    }
    for finding in _AGREEMENT_SAMPLE_REVIEWS:
        case_identity = finding["case_identity"]
        campaign = case_identity[:10]
        cell = cells_by_campaign[campaign][(case_identity, finding["domain"])]
        if cell.outcome_id != finding["outcome"]:
            raise ValueError(f"sample review outcome differs from selected cell: {case_identity}")
        if cell.comparison != "agreement":
            raise ValueError(f"agreement sample review is not a matching-label cell: {case_identity}")
        case_score = next(
            row
            for row in cases_by_campaign[campaign].values()
            if row["case_identity"] == case_identity
        )
        bundle = case_score["_bundle_path"]
        paths = _selected_trace(bundle)
        review, findings, _ = _review_from_trace(paths)
        if review.get("result_identity") != cell.result_identity:
            raise ValueError(f"selected Result differs from sampled cell: {case_identity}")
        if review.get("identity") != cell.review_identity:
            raise ValueError(f"selected review differs from sampled cell: {case_identity}")
        domain_finding = findings[finding["domain"]]
        answers = {
            answer.get("question_id"): answer
            for answer in domain_finding.get("answers", ())
            if isinstance(answer, dict) and isinstance(answer.get("question_id"), str)
        }
        if set(answers) != set(cell.question_ids):
            raise ValueError(f"sampled question identities differ from saved review: {case_identity}")
        source_handles = _canonical_source_handles(bundle)
        calls = _calls(paths)
        captured_evidence = {
            item["handle"]: item
            for item in _walk(calls)
            if isinstance(item.get("handle"), str)
            and isinstance(item.get("source_id"), str)
            and isinstance(item.get("page"), int)
        }
        trace_reference = ";".join(
            f"{_repo_relative(path)}#sha256:{_sha256(path)}" for path in paths
        )
        for question_id in cell.question_ids:
            answer = answers[question_id]
            locators: list[EvidenceLocator] = []
            source_ids: set[str] = set()
            locator_keys: set[tuple[str, str]] = set()
            for expansion in answer.get("evidence_expansions", ()):
                if not isinstance(expansion, dict):
                    continue
                evidence_handle = expansion.get("evidence")
                for window in expansion.get("windows", ()):
                    if not isinstance(window, dict):
                        continue
                    source_handle = window.get("source_id")
                    if source_handle not in source_handles:
                        raise ValueError(
                            f"captured question window has no canonical Source: {case_identity}/{question_id}"
                        )
                    source_id, source_label, projection = source_handles[source_handle]
                    page = window.get("page")
                    start_line = window.get("start_line")
                    end_line = window.get("end_line")
                    if not isinstance(page, int):
                        raise ValueError(f"captured question window has no page: {case_identity}/{question_id}")
                    if isinstance(start_line, int) and isinstance(end_line, int):
                        locator = f"{source_label}, PDF p. {page}, lines {start_line}–{end_line}"
                    else:
                        locator = f"{source_label}, PDF p. {page}"
                    locator = (
                        f"{locator}; captured evidence {evidence_handle}; source version {projection}; "
                        f"selected trace {trace_reference}"
                    )
                    if (source_id, locator) not in locator_keys:
                        locators.append(
                            EvidenceLocator(
                                source_identity=source_id,
                                locator=locator,
                                note=(
                                    f"Original captured {expansion.get('operation', 'source')} window cited by "
                                    f"the saved {question_id} answer."
                                ),
                            )
                        )
                        locator_keys.add((source_id, locator))
                    source_ids.add(source_id)

            if (
                case_identity == "2026-09-26:adverse-events:latitude"
                and question_id == "sq:measurement:differential"
            ):
                handle = "eh_e8d8c5be69654304"
                extra = captured_evidence.get(handle)
                if (
                    extra is None
                    or extra.get("source_id") != "sh_c697b666a3a887b5"
                    or extra.get("page") != 4
                    or extra.get("start_line") != 68
                    or extra.get("end_line") != 76
                ):
                    raise ValueError("saved LATITUDE exposure-duration capture is missing or changed")
                source_id, source_label, projection = source_handles[extra["source_id"]]
                locators.append(
                    EvidenceLocator(
                        source_identity=source_id,
                        locator=(
                            f"{source_label}, PDF p. 4, lines 68–76; captured evidence {handle}; "
                            f"source version {projection}; selected trace {trace_reference}"
                        ),
                        note=(
                            "Original selected trace retrieved this exposure-duration passage, but the saved answer's cited windows omitted it. "
                            "The article reports median intervention exposure of 24 months versus 14 months; this was checked against the saved reassurance about equal ascertainment opportunity."
                        ),
                    )
                )
                source_ids.add(source_id)

            if not source_ids or not locators:
                raise ValueError(f"sampled answer has no original source locator: {case_identity}/{question_id}")
            saved_justification = answer.get("justification")
            if not isinstance(saved_justification, str) or not saved_justification:
                raise ValueError(f"sampled answer has no saved justification: {case_identity}/{question_id}")
            classification = _QUESTION_CLASSIFICATION_OVERRIDES.get(
                (case_identity, question_id), finding["classification"]
            )
            records.append(
                AdjudicationSidecar(
                    run_identity=campaign,
                    case_identity=cell.case_identity,
                    result_identity=cell.result_identity,
                    domain_identity=cell.domain_id,
                    question_identity=question_id,
                    checkpoint_identity=cell.checkpoint_identity,
                    source_identities=tuple(sorted(source_ids)),
                    reference_label=cell.reference_label.value,
                    model_label=cell.model_label.value,
                    provisional_label=cell.reference_label.value,
                    classification=classification,
                    evidence=tuple(locators),
                    rationale=(
                        f"Saved answer justification: {saved_justification} "
                        f"Source-grounded review: {finding['rationale']}"
                    ),
                    unresolved_facts=tuple(
                        dict.fromkeys(
                            (*finding["unresolved_facts"], *answer.get("unknowns", ()))
                        )
                    ),
                    follow_up=finding["follow_up"],
                    reviewer_identity=_AGREEMENT_REVIEWER,
                    reviewer_role=_REVIEWER_ROLE,
                    adjudication_version="2026-09-27-agreement-sample-source-review-v1",
                    reviewed_at=_AGREEMENT_REVIEWED_AT,
                    confidence=finding["confidence"],
                )
            )
    return tuple(records)


def _trace_inventory(date_roots: dict[str, Path], selected_logs: set[Path]) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    hashes: dict[str, list[str]] = defaultdict(list)
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for campaign, date_root in date_roots.items():
        for path in sorted(date_root.rglob("*.jsonl")):
            digest = _sha256(path)
            relative = _repo_relative(path)
            hashes[digest].append(relative)
            counts: Counter[str] = Counter()
            item_types: Counter[str] = Counter()
            errors: list[str] = []
            malformed: list[int] = []
            with path.open(encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        malformed.append(line_number)
                        continue
                    event_type = event.get("type", "?")
                    counts[event_type] += 1
                    if event_type.startswith("item."):
                        item_types[event.get("item", {}).get("type", "?")] += 1
                    if event_type == "error":
                        errors.append(str(event.get("message", "")))
            run_tree = "issue-465-e2e" if "issue-465-e2e" in path.parts else "benchmark"
            selection = (
                "selected"
                if path.resolve() in selected_logs
                else "non_selected_attempt_or_continuation"
            )
            inventory.append(
                {
                    "date": campaign,
                    "run_tree": run_tree,
                    "selection": selection,
                    "path": relative,
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                    "events": dict(counts),
                    "item_types": dict(item_types),
                    "errors": errors,
                    "malformed_lines": malformed,
                }
            )
            totals[campaign]["files"] += 1
            totals[campaign]["bytes"] += path.stat().st_size
            totals[campaign]["completed_items"] += counts["item.completed"]
            totals[campaign]["started_items"] += counts["item.started"]
            totals[campaign]["errors"] += len(errors)
            totals[campaign]["malformed_lines"] += len(malformed)
            totals[campaign]["selected_segments"] += selection == "selected"
            totals[campaign]["issue_465_e2e_segments"] += run_tree == "issue-465-e2e"
    duplicates = [paths for paths in hashes.values() if len(paths) > 1]
    if duplicates:
        raise ValueError(f"duplicate JSONL content found: {duplicates}")
    return {
        "schema": "rob2-kit.september-trace-inventory.v1",
        "scope": "Every JSONL under both date roots. The September 27 issue-465 E2E tree is separately identified.",
        "totals": {key: dict(value) for key, value in totals.items()},
        "duplicate_content_groups": duplicates,
        "files": inventory,
    }


def _reconciliation(
    cohorts: dict[str, CohortManifest],
    cases: dict[str, dict[tuple[str, str], dict[str, Any]]],
    source_audits: tuple[AdjudicationSidecar, ...],
    score_hashes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    audit_cells = {
        (record.run_identity, record.case_identity, record.domain_identity)
        for record in source_audits
    }
    campaigns = []
    for campaign in ("2026-09-26", "2026-09-27"):
        cohort = cohorts[campaign]
        rows = list(cases[campaign].values())
        all_cells = [cell for cell in cohort.cells if cell.revision == 0]
        agreements = [cell for cell in all_cells if cell.comparison == "agreement"]
        disagreements = [cell for cell in all_cells if cell.comparison == "disagreement"]
        scope_cases = [row for row in rows if row["accepted_scope_sensitivity_eligible"]]
        scope_case_ids = {row["case_identity"] for row in scope_cases}
        scope_cells = [cell for cell in all_cells if cell.case_identity in scope_case_ids]
        primary_case_ids = {
            row["case_identity"] for row in scope_cases if row["primary_scope_eligible"]
        }
        primary_cells = [cell for cell in all_cells if cell.case_identity in primary_case_ids]
        sidecar_cells = {
            (record.case_identity, record.domain_identity)
            for record in source_audits
            if record.run_identity == campaign
        }
        cells_by_identity = {cell.identity: cell for cell in all_cells}
        classes_by_cell: dict[tuple[str, str], set[str]] = defaultdict(set)
        for case_identity, domain_id in sorted(sidecar_cells):
            classes_by_cell[(case_identity, domain_id)] = {
                record.classification.value
                for record in source_audits
                if record.run_identity == campaign
                and record.case_identity == case_identity
                and record.domain_identity == domain_id
            }
        classification_precedence = (
            AdjudicationClassification.LIKELY_MODEL_ERROR.value,
            AdjudicationClassification.REFERENCE_ISSUE.value,
            AdjudicationClassification.INDETERMINATE.value,
            AdjudicationClassification.DEFENSIBLE_DEVIATION.value,
            AdjudicationClassification.AGREEMENT.value,
        )
        class_support: Counter[str] = Counter()
        for classes in classes_by_cell.values():
            class_support[next(item for item in classification_precedence if item in classes)] += 1
        cells_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cell in all_cells:
            cells_by_case[cell.case_identity].append(
                {
                    "domain_id": cell.domain_id,
                    "identity": cell.identity,
                    "comparison": cell.comparison,
                    "reference_label": cell.reference_label.value,
                    "model_label": cell.model_label.value,
                    "question_ids": list(cell.question_ids),
                    "source_identities": list(cell.source_identities),
                    "source_projection_scope": cell.source_projection_scope,
                    "source_availability": "projection_observed_in_trace",
                    "retrieval": (
                        "saved_answer_has_source_window"
                        if cell.source_projection_scope == "answer_expansions"
                        else "case_inventory_only"
                    ),
                    "context_delivery": "not_observable_in_jsonl",
                    "interpretation": (
                        "source_audit_sidecar"
                        if (campaign, cell.case_identity, cell.domain_id) in audit_cells
                        else "pending"
                    ),
                    "response_mapping": "trace_judgment_matches_score_label",
                    "policy_attribution": "not_assessed",
                }
            )
        campaigns.append(
            {
                "campaign_id": campaign,
                "cohort_identity": cohort.identity,
                "cohort_path": f"eval/cohorts/{campaign}.json",
                "score_files": score_hashes[campaign],
                "all_case_score": {
                    "assessments": len(rows),
                    "domain_cells": len(all_cells),
                    "exact_matches": len(agreements),
                    "disagreements": len(disagreements),
                },
                "primary_scope": {
                    "eligible_assessments": len(primary_case_ids),
                    "domain_cells": len(primary_cells),
                    "exact_matches": sum(cell.comparison == "agreement" for cell in primary_cells),
                    "disagreements": sum(
                        cell.comparison == "disagreement" for cell in primary_cells
                    ),
                    "policy": "Exact or source-adjudicated equivalent scopes only.",
                },
                "accepted_scope_sensitivity": {
                    "eligible_assessments": len(scope_cases),
                    "domain_cells": len(scope_cells),
                    "exact_matches": sum(cell.comparison == "agreement" for cell in scope_cells),
                    "disagreements": sum(cell.comparison == "disagreement" for cell in scope_cells),
                    "excluded_assessments": 26 - len(scope_cases),
                    "policy": (
                        "14 exact or equivalent result scopes plus 3 accepted proxies"
                        if campaign == "2026-09-26"
                        else "24 exact or equivalent result scopes plus 2 accepted scope differences; this equals the published all-26 sensitivity"
                    ),
                },
                "source_audit_coverage": {
                    "disagreement_cells": len(disagreements),
                    "source_reviewed_cells": len(sidecar_cells),
                    "source_reviewed_disagreement_cells": sum(
                        cell.comparison == "disagreement"
                        for cell in all_cells
                        if (cell.case_identity, cell.domain_id) in sidecar_cells
                    ),
                    "unreviewed_disagreement_cells": len(disagreements)
                    - sum(
                        cell.comparison == "disagreement"
                        for cell in all_cells
                        if (cell.case_identity, cell.domain_id) in sidecar_cells
                    ),
                    "source_reviewed_agreement_cells": sum(
                        cell.comparison == "agreement"
                        for cell in all_cells
                        if (cell.case_identity, cell.domain_id) in sidecar_cells
                    ),
                    "class_support": dict(class_support),
                    "independent_human_certification": False,
                    "corrected_accuracy_calculated": False,
                },
                "agreement_sample": {
                    "declared_size": len(cohort.agreement_sample),
                    "reviewed": sum(
                        entry.review_status == "complete" for entry in cohort.agreement_sample
                    ),
                    "pending": sum(
                        entry.review_status == "pending_external_adjudication"
                        for entry in cohort.agreement_sample
                    ),
                    "selection_seed": cohort.agreement_sample[0].selection_seed,
                    "entries": [
                        {
                            "cell_identity": entry.cell_identity,
                            "case_identity": cells_by_identity[entry.cell_identity].case_identity,
                            "trial_id": cells_by_identity[entry.cell_identity].trial_id,
                            "outcome_id": cells_by_identity[entry.cell_identity].outcome_id,
                            "domain_id": cells_by_identity[entry.cell_identity].domain_id,
                            "comparison": cells_by_identity[entry.cell_identity].comparison,
                            "reference_label": cells_by_identity[
                                entry.cell_identity
                            ].reference_label.value,
                            "model_label": cells_by_identity[entry.cell_identity].model_label.value,
                            "selection_rank": entry.selection_rank,
                            "review_status": entry.review_status,
                            "reviewer_provenance": entry.reviewer_provenance.model_dump(
                                mode="json", by_alias=True
                            ),
                        }
                        for entry in cohort.agreement_sample
                    ],
                },
                "cases": [
                    {
                        **{key: value for key, value in row.items() if not key.startswith("_")},
                        "cells": cells_by_case[row["case_identity"]],
                    }
                    for row in rows
                ],
            }
        )
    return {
        "schema": "rob2-kit.september-adjudication-reconciliation.v1",
        "score_comparison": "Descriptive across two campaigns. The campaigns did not control code, selected Result, scope policy, or retry path as a paired intervention.",
        "campaigns": campaigns,
        "source_audit_records": [
            {
                "identity": record.identity,
                "run_identity": record.run_identity,
                "case_identity": record.case_identity,
                "result_identity": record.result_identity,
                "domain_identity": record.domain_identity,
                "question_identity": record.question_identity,
                "classification": record.classification.value,
                "reviewer_identity": record.reviewer_identity,
                "reviewer_role": record.reviewer_role,
            }
            for record in source_audits
        ],
    }


def build(args: argparse.Namespace) -> None:
    reference = args.reference.resolve()
    roots = {
        "2026-09-26": args.run_26_root.resolve(),
        "2026-09-27": args.run_27_root.resolve(),
    }
    score_paths = {
        "2026-09-26": (
            roots["2026-09-26"] / "all-case-accuracy.json",
            roots["2026-09-26"] / "scope-matched-score.json",
        ),
        "2026-09-27": (
            roots["2026-09-27"] / "accuracy.json",
            roots["2026-09-27"] / "accuracy.json",
        ),
    }
    scores: dict[str, dict[str, Any]] = {}
    scopes: dict[str, dict[str, Any]] = {}
    hashes: dict[str, dict[str, str]] = {}
    for campaign, (score_path, scope_path) in score_paths.items():
        scores[campaign] = json.loads(score_path.read_text(encoding="utf-8"))
        scopes[campaign] = json.loads(scope_path.read_text(encoding="utf-8"))
        hashes[campaign] = {
            "all_case_score_sha256": _sha256(score_path),
            "scope_score_sha256": _sha256(scope_path),
        }

    cohorts: dict[str, CohortManifest] = {}
    case_rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    selected_logs: set[Path] = set()
    for campaign in ("2026-09-26", "2026-09-27"):
        cohort, rows, logs = _build_campaign(
            campaign, roots[campaign], scores[campaign], scopes[campaign], reference
        )
        cohorts[campaign] = cohort
        case_rows[campaign] = rows
        selected_logs.update(path.resolve() for path in logs)
        write_cohort(args.output_dir / f"{campaign}.json", cohort)

    source_audits = (
        *_source_audits(cohorts, case_rows),
        *_agreement_sample_audits(cohorts, case_rows),
    )
    source_audit_path = args.output_dir / "2026-09-27-source-audits.json"
    source_audit_path.parent.mkdir(parents=True, exist_ok=True)
    source_audit_path.write_text(
        json.dumps(
            [record.model_dump(mode="json", by_alias=True) for record in source_audits],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    date_roots = {campaign: run_root.parent for campaign, run_root in roots.items()}
    trace_inventory = _trace_inventory(date_roots, selected_logs)
    inventory_path = args.inventory_output
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        json.dumps(trace_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    reconciliation = _reconciliation(cohorts, case_rows, source_audits, hashes)
    reconciliation_path = args.reconciliation_output
    reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
    reconciliation_path.write_text(
        json.dumps(reconciliation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                campaign: {
                    "cohort_identity": cohort.identity,
                    "assessments": len({cell.case_identity for cell in cohort.cells}),
                    "domain_cells": len(cohort.cells),
                    "exact_matches": sum(cell.comparison == "agreement" for cell in cohort.cells),
                    "disagreements": sum(
                        cell.comparison == "disagreement" for cell in cohort.cells
                    ),
                    "development_cases": len(cohort.partitions.development_case_ids),
                    "agreement_sample": len(cohort.agreement_sample),
                }
                for campaign, cohort in cohorts.items()
            }
            | {
                "trace_files": len(trace_inventory["files"]),
                "source_audit_records": len(source_audits),
                "source_audit_cells": len(
                    {
                        (record.run_identity, record.case_identity, record.domain_identity)
                        for record in source_audits
                    }
                ),
                "inventory_output": str(inventory_path),
                "reconciliation_output": str(reconciliation_path),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path("eval/reference"))
    parser.add_argument(
        "--run-26-root",
        type=Path,
        default=Path("eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium"),
    )
    parser.add_argument("--run-27-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/cohorts"))
    parser.add_argument(
        "--inventory-output",
        type=Path,
        default=Path("docs/evaluation/2026-09-27-trace-inventory.json"),
    )
    parser.add_argument(
        "--reconciliation-output",
        type=Path,
        default=Path("docs/evaluation/2026-09-27-cohort-reconciliation.json"),
    )
    args = parser.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
