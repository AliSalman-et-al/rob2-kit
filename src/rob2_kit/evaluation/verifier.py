"""Fail-closed independent verifier for serialized finalization bundles."""
# ruff: noqa: E501, E701, E741

from __future__ import annotations

import html
import json
import math
import re
import struct
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import pymupdf

from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK

from .manifest import ObjectiveFactManifest, OutcomeFacts, check_reported_facts
from .trace import TraceEvent, check_required_operations, check_trace


def _presentation(counts: dict[str, Any]) -> dict[str, str] | None:
    """Derive the public wording here, rather than trusting the producer."""
    try:
        total = int(counts["total"])
        assessed = int(counts["assessed"])
        needs_input = int(counts["needs_input"])
        failed = int(counts["failed"])
        pending = int(counts["pending"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(total, assessed, needs_input, failed, pending) < 0 or pending:
        return None
    assessment = "assessment" if assessed == 1 else "assessments"
    trial = "Trial" if assessed == 1 else "Trials"
    if assessed == total and assessed > 0:
        return {
            "code": "finalized_all_assessed",
            "headline": f"{assessed} RoB 2 {assessment} completed",
            "summary": f"Batch finalized. RoB 2 {assessment} completed for {assessed} {trial}.",
        }
    if assessed == 0:
        details: list[str] = []
        if needs_input:
            details.append(
                f"{needs_input} {'Trial needs' if needs_input == 1 else 'Trials need'} researcher input."
            )
        if failed:
            details.append(f"{failed} {'Trial failed' if failed == 1 else 'Trials failed'}.")
        return {
            "code": "finalized_zero_assessed",
            "headline": "Batch finalized",
            "summary": "Batch finalized. No RoB 2 assessments were completed."
            + (" " + " ".join(details) if details else ""),
        }
    return {
        "code": "finalized_mixed",
        "headline": f"{assessed} RoB 2 {assessment} completed",
        "summary": (
            f"Batch finalized. RoB 2 {assessment} completed for {assessed} {trial}; "
            f"{needs_input} {'Trial needs' if needs_input == 1 else 'Trials need'} researcher input "
            f"and {failed} {'Trial failed' if failed == 1 else 'Trials failed'}."
        ),
    }


def _canonical(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + sha256(encoded.encode()).hexdigest()


def _has_exact_record_keys(record: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return set(record) == {"identity", *fields}


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _ref(value: object, kind: str) -> str | None:
    if not isinstance(value, dict) or set(value) != {"kind", "identity", "uri"}:
        return None
    serialized_kind = value.get("kind")
    if not isinstance(serialized_kind, str) or serialized_kind != kind:
        return None
    identity, uri = value["identity"], value["uri"]
    if not isinstance(identity, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None:
        return None
    if uri != f"rob2://detail/{serialized_kind}/{identity}":
        return None
    return identity


def _ref_record(kind: str, identity: object) -> dict[str, str] | None:
    if not isinstance(identity, str):
        return None
    return {"kind": kind, "identity": identity, "uri": f"rob2://detail/{kind}/{identity}"}


def _evidence_ref(value: object) -> str | None:
    if not isinstance(value, dict) or set(value) != {"kind", "identity"}:
        return None
    identity = value.get("identity")
    return (
        identity
        if value.get("kind") == "evidence"
        and isinstance(identity, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is not None
        else None
    )


def _render_ref(value: object) -> str | None:
    if not isinstance(value, dict) or set(value) != {"identity", "uri"}:
        return None
    identity, uri = value.get("identity"), value.get("uri")
    if not isinstance(identity, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None:
        return None
    return identity if uri == f"rob2://render/{identity}" else None


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    failures: tuple[str, ...]
    facts_checked: tuple[str, ...]


class _Bundle:
    def __init__(self, root: Path, failures: list[str]):
        self.root, self.failures = root, failures
        self.records: dict[str, dict[str, Any]] = {}
        self.names: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        try:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
            rows = manifest["files"]
            base = {"summary_hash": manifest["summary_hash"], "files": rows}
            if not isinstance(rows, list) or _canonical(base) != manifest.get("manifest_hash"):
                raise ValueError
            listed: set[str] = set()
            for row in rows:
                relative = row.get("path") if isinstance(row, dict) else None
                if not isinstance(relative, str) or not isinstance(row.get("sha256"), str):
                    raise ValueError
                path = self.root / relative
                if ".." in Path(relative).parts or path.is_symlink() or not path.is_file():
                    raise ValueError
                if _bytes_hash(path.read_bytes()) != row["sha256"] or relative in listed:
                    raise ValueError
                listed.add(relative)
            actual = {
                p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()
            }
            if actual != listed | {"manifest.json"}:
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.failures.append("artifact manifest, inventory, or file hash is invalid")
            return
        records = self.root / "records"
        for path in records.rglob("*.json") if records.is_dir() else ():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.failures.append("record JSON is corrupt")
                continue
            if not isinstance(record, dict):
                self.failures.append("record is not an object")
                continue
            self.names[path.name] = record
            identity = record.get("identity")
            if isinstance(identity, str):
                if identity in self.records:
                    self.failures.append("duplicate canonical record identity")
                self.records[identity] = record


_ANSWER_CODES = {
    "Y": "yes",
    "PY": "probably_yes",
    "PN": "probably_no",
    "N": "no",
    "NI": "no_information",
}


def _active_questions_from_pack(answers: dict[str, Any]) -> tuple[str, ...] | None:
    """Interpret the serialized SCIENTIFIC_PACK activation expressions.

    The release verifier deliberately has its own small interpreter.  The
    expressions use the numbered questions from the RoB 2 guidance (for
    example, ``2.1 or 2.2 is Y/PY/NI``); question order and activation text
    come from the pack rather than from the production evaluator.
    """
    questions = SCIENTIFIC_PACK.questions
    question_ids = {question.id for question in questions}
    if len(question_ids) != len(questions):
        return None
    if set(answers) - question_ids:
        return None
    if any(
        not isinstance(value, str)
        or value not in {answer.value for answer in question.allowed_answers}
        for question in questions
        for value in ([answers[question.id]] if question.id in answers else [])
    ):
        return None

    question_numbers: dict[str, dict[str, str]] = {}
    for domain in SCIENTIFIC_PACK.domains:
        if len(set(domain.question_ids)) != len(domain.question_ids):
            return None
        if any(question_id not in question_ids for question_id in domain.question_ids):
            return None
        sections = {
            match.group(1)
            for question in questions
            if question.domain_id == domain.id and question.active_when is not None
            for match in [re.match(r"^(\d+)\.\d+", question.active_when)]
            if match is not None
        }
        if len(sections) > 1:
            return None
        section = next(iter(sections), None)
        question_numbers[domain.id] = {
            f"{section}.{index}": question_id
            for index, question_id in enumerate(domain.question_ids, start=1)
            if section is not None
        }

    active: list[str] = []
    condition_pattern = re.compile(
        r"^(?P<references>\d+\.\d+(?:\s+(?:or|and)\s+\d+\.\d+)*)\s+"
        r"(?P<quantifier>is|are)\s+(?P<values>[A-Z]+(?:/[A-Z]+)*)$"
    )
    for question in questions:
        expression = question.active_when
        if expression is None:
            active.append(question.id)
            continue
        if not isinstance(expression, str):
            return None
        match = condition_pattern.fullmatch(expression.strip())
        if match is None:
            return None
        references = re.findall(r"\d+\.\d+", match.group("references"))
        operators = re.findall(r"\b(or|and)\b", match.group("references"))
        quantifier = match.group("quantifier")
        if (
            not references
            or (quantifier == "is" and any(operator != "or" for operator in operators))
            or (quantifier == "are" and any(operator != "and" for operator in operators))
            or (quantifier == "is" and len(references) > 1 and not operators)
            or (quantifier == "are" and len(references) < 2)
        ):
            return None
        number_map = question_numbers.get(question.domain_id)
        if number_map is None or any(reference not in number_map for reference in references):
            return None
        values = match.group("values").split("/")
        if not values or any(value not in _ANSWER_CODES for value in values):
            return None
        allowed = {_ANSWER_CODES[value] for value in values}
        observed = [answers.get(number_map[reference]) for reference in references]
        if quantifier == "is":
            condition = any(value in allowed for value in observed)
        else:
            condition = all(value in allowed for value in observed)
        if condition:
            active.append(question.id)
    return tuple(active)


def _domain_oracle(candidate: dict[str, Any]) -> str | None:
    """Independent RoB 2 rules for the canonical answer vocabulary."""
    draft = candidate.get("draft")
    rows = draft.get("active_answers") if isinstance(draft, dict) else None
    if not isinstance(rows, list):
        return None
    if not all(isinstance(row, dict) for row in rows):
        return None
    question_ids = [row.get("question_id") for row in rows]
    if not all(isinstance(question_id, str) for question_id in question_ids) or len(
        set(question_ids)
    ) != len(question_ids):
        return None
    domain = candidate.get("domain_id")
    domain_questions = next(
        (
            domain_record.question_ids
            for domain_record in SCIENTIFIC_PACK.domains
            if domain_record.id == domain
        ),
        None,
    )
    if domain_questions is None:
        return None
    answers = {str(row["question_id"]): row.get("answer") for row in rows}
    expected_all = _active_questions_from_pack(answers)
    if expected_all is None:
        return None
    expected = tuple(question_id for question_id in expected_all if question_id in domain_questions)
    if tuple(question_ids) != expected:
        return None
    yes, no = {"yes", "probably_yes"}, {"no", "probably_no"}
    no_u = no | {"no_information"}
    if domain == "domain:randomization":
        c, b = (
            answers.get("sq:randomization:concealment"),
            answers.get("sq:randomization:baseline-imbalance"),
        )
        if c in no or (c == "no_information" and b in yes):
            return "high"
        return (
            "some_concerns"
            if answers.get("sq:randomization:sequence") in no or c == "no_information" or b in yes
            else "low"
        )
    if domain == "domain:missing":
        a, u, d, l = (
            answers.get(f"sq:missing:{key}")
            for key in (
                "data-available",
                "evidence-unbiased",
                "true-value-dependent",
                "likely-dependent",
            )
        )
        if a in yes or u in yes or d in no:
            return "low"
        return "high" if l in yes | {"no_information"} else "some_concerns"
    if domain == "domain:measurement":
        i, d, l = (
            answers.get(f"sq:measurement:{key}")
            for key in ("method-inappropriate", "differential", "influence-likely")
        )
        if i in yes or d in yes or l in yes | {"no_information"}:
            return "high"
        return "some_concerns" if d == "no_information" or l in no else "low"
    if domain == "domain:selection":
        m, a = (
            answers.get("sq:selection:multiple-measurements"),
            answers.get("sq:selection:multiple-analyses"),
        )
        if m in yes or a in yes:
            return "high"
        return (
            "some_concerns"
            if answers.get("sq:selection:prespecified-analysis") in no_u
            or m == "no_information"
            or a == "no_information"
            else "low"
        )
    if domain == "domain:deviations":
        c, a, b = (
            answers.get(f"sq:deviations:{key}")
            for key in ("context-deviations", "affected-outcome", "balanced")
        )
        p, i = (
            answers.get("sq:deviations:appropriate-analysis"),
            answers.get("sq:deviations:substantial-impact"),
        )
        if c in yes and a in yes | {"no_information"} and b in no_u:
            return "high"
        if p in no_u and i in yes | {"no_information"}:
            return "high"
        return "some_concerns" if c == "no_information" or a in no or b in yes or i in no else "low"
    return None


def _overall_judgment(judgments: list[str]) -> str:
    if "high" in judgments:
        return "high"
    if "some_concerns" in judgments:
        return "some_concerns"
    return "low"


def _summary(bundle: _Bundle) -> dict[str, Any] | None:
    try:
        value = json.loads((bundle.root / "summary.json").read_text(encoding="utf-8"))
        payload = {
            key: value[key] for key in ("approved_batch", "counts", "trials", "presentation")
        }
        if value.get("kind") != "finalization" or _canonical(payload) != value.get("identity"):
            raise ValueError
        if _ref(value["approved_batch"], "approved_batch") is None:
            raise ValueError
        counts, trials = value["counts"], value["trials"]
        actual = {
            key: sum(row.get("disposition") == key for row in trials)
            for key in ("assessed", "needs_input", "failed")
        }
        if counts != {"total": len(trials), "pending": 0, **actual}:
            raise ValueError
        if value.get("presentation") != _presentation(counts):
            raise ValueError
        return value
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        bundle.failures.append("finalization summary identity, counts, or references are invalid")
        return None


def _proposal(bundle: _Bundle, key: str, objective: ObjectiveFactManifest) -> dict[str, Any] | None:
    value = bundle.names.get("proposal_review.json")
    if value is None:
        bundle.failures.append("durable Proposal review is unavailable")
        return None
    base = {
        field: value.get(field)
        for field in ("captured_batch", "outcome_statement", "results", "needs_input")
    }
    if value.get("kind") != "proposal_review" or _canonical(base) != value.get("identity"):
        bundle.failures.append("Proposal identity is invalid")
        return None
    if not _closed_proposal(value):
        bundle.failures.append("Proposal schema contains extra or invalid fields")
    if _ref(value.get("captured_batch"), "captured_batch") is None:
        bundle.failures.append("Proposal does not bind a captured Batch")
    facts = objective.outcome(key)
    selected = value.get("results")
    if not isinstance(selected, list) or len(selected) != 1:
        bundle.failures.append("Proposal has no exact Result card for the release outcome")
    else:
        bundle.failures.extend(check_reported_facts(facts, selected[0]))
    if facts.expected_terminal == "needs_input":
        needs = value.get("needs_input")
        if not isinstance(needs, list) or len(needs) != 1:
            bundle.failures.append("adverse events requires a separate needs-input disposition")
        elif not isinstance(needs[0], dict) or needs[0].get("reason") != "comparator_unavailable":
            bundle.failures.append("adverse-events needs-input reason must be missing comparator")
    return value


def _closed_proposal(value: dict[str, Any]) -> bool:
    fields = {
        "kind",
        "identity",
        "captured_batch",
        "outcome_statement",
        "results",
        "needs_input",
        "review",
        "transition",
    }
    if (
        set(value) != fields
        or not isinstance(value.get("results"), list)
        or not isinstance(value.get("needs_input"), list)
    ):
        return False
    if not _ref(value.get("captured_batch"), "captured_batch"):
        return False
    return (
        all(_closed_result(item) for item in value["results"])
        and all(_closed_needs_input(item) for item in value["needs_input"])
        and _closed_review(value.get("review"))
        and _closed_transition(value.get("transition"))
    )


def _closed_needs_input(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"trial_id", "reason", "missing_facts", "evidence"}
        and isinstance(value.get("trial_id"), str)
        and isinstance(value.get("reason"), str)
        and value["reason"] in {
            "outcome_not_reported",
            "outcome_not_measured",
            "comparator_unavailable",
            "population_unclear",
            "result_not_estimable",
        }
        and isinstance(value.get("missing_facts"), list)
        and bool(value["missing_facts"])
        and all(isinstance(item, str) for item in value["missing_facts"])
        and isinstance(value.get("evidence"), list)
        and all(_evidence_ref(item) for item in value["evidence"])
    )


def _closed_review(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"required", "satisfied", "acknowledgment"}:
        return False
    acknowledgment = value.get("acknowledgment")
    return (
        isinstance(value.get("required"), str)
        and value["required"] in {"none", "host", "researcher"}
        and isinstance(value.get("satisfied"), bool)
        and (
            acknowledgment is None
            or _ref(acknowledgment, "review_ack") is not None
        )
    )


def _closed_transition(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"operation", "identity"}
        and isinstance(value.get("operation"), str)
        and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value["operation"]) is not None
        and _is_hash(value.get("identity"))
    )


def _closed_result(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    reported = value.get("reported")
    if not isinstance(reported, dict):
        return False
    reported_fields = _reported_fields(reported.get("form"))
    common = {
        "trial_id",
        "target",
        "reported",
        "derived",
        "population",
        "source_table_meaning",
        "evidence",
        "clarity",
        "compatibility",
    }
    if reported_fields is None or set(value) != common | reported_fields:
        return False
    target = value.get("target")
    population = value.get("population")
    evidence = value.get("evidence")
    if not isinstance(target, dict) or set(target) != {
        "outcome_definition",
        "measurement",
        "time_point_or_window",
        "effect_of_interest",
        "comparison_groups",
        "intended_analysis_population",
        "intended_effect_measure",
    } or not _closed_target(target):
        return False
    if not isinstance(population, dict) or set(population) != {
        "randomized_enrollment",
        "outcome_measurement_coverage",
        "analyzed_population",
    } or not _closed_population(population):
        return False
    if not isinstance(evidence, dict) or set(evidence) != {
        "target_basis",
        "reported_values",
        "reported_context",
        "population_basis",
    } or not _closed_evidence(evidence):
        return False
    return (
        _closed_reported(reported)
        and _closed_derived(value.get("derived"))
        and _closed_clarity(value.get("clarity"))
        and _closed_compatibility(value.get("compatibility"))
        and all(
        isinstance(references, list)
        and references
        and all(_evidence_ref(item) for item in references)
        for references in evidence.values()
        )
    )


def _reported_fields(form: object) -> set[str] | None:
    return {
        "comparative_effect": {
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
            "precision",
        },
        "group_bound_values": {"form", "quantities", "comparison_groups"},
        "single_group_category_profile": {"form", "group_id", "categories"},
        "unavailable": {"form", "reason", "explanation"},
    }.get(form) if isinstance(form, str) else None


def _closed_quantity(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {
        "statistic",
        "unit",
        "group_or_category",
        "value",
        "denominator_basis",
    }


def _closed_target(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "outcome_definition",
        "measurement",
        "time_point_or_window",
        "effect_of_interest",
        "comparison_groups",
        "intended_analysis_population",
        "intended_effect_measure",
    }:
        return False
    groups = value.get("comparison_groups")
    return (
        isinstance(groups, list)
        and len(groups) == 2
        and all(
            isinstance(group, dict)
            and set(group) == {"id", "label"}
            and isinstance(group.get("id"), str)
            and isinstance(group.get("label"), str)
            for group in groups
        )
    )


def _closed_population(value: dict[str, Any]) -> bool:
    enrollment = value.get("randomized_enrollment")
    coverage = value.get("outcome_measurement_coverage")
    return (
        isinstance(enrollment, list)
        and all(_closed_quantity(item) for item in enrollment)
        and isinstance(coverage, list)
        and all(
            isinstance(item, dict)
            and set(item) == {"group_id", "status", "explanation"}
            and isinstance(item.get("group_id"), str)
            and item.get("status") in {"measured", "not_measured", "unclear"}
            and (item.get("explanation") is None or isinstance(item.get("explanation"), str))
            for item in coverage
        )
    )


def _closed_evidence(value: dict[str, Any]) -> bool:
    return all(
        isinstance(references, list)
        and references
        and all(_evidence_ref(item) for item in references)
        for references in value.values()
    )


def _closed_precision(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"confidence_interval", "p_value"}:
        return False
    interval, p_value = value["confidence_interval"], value["p_value"]
    return (
        isinstance(interval, dict)
        and set(interval) == {"level", "lower", "upper"}
        and isinstance(p_value, dict)
        and set(p_value) == {"operator", "value"}
        and p_value.get("operator") in {"=", "<", "<=", ">", ">="}
    )


def _closed_reported(value: dict[str, Any]) -> bool:
    form = value.get("form")
    if _reported_fields(form) != set(value):
        return False
    if form == "comparative_effect":
        return (
            isinstance(value.get("effect_measure"), str)
            and isinstance(value.get("reported_text"), str)
            and _closed_quantity(value.get("effect"))
            and isinstance(value.get("quantities"), list)
            and len(value["quantities"]) >= 2
            and all(_closed_quantity(item) for item in value["quantities"])
            and isinstance(value.get("comparison_groups"), list)
            and len(value["comparison_groups"]) == 2
            and all(isinstance(item, str) for item in value["comparison_groups"])
            and _closed_precision(value.get("precision"))
        )
    if form == "group_bound_values":
        return (
            isinstance(value.get("quantities"), list)
            and len(value["quantities"]) >= 2
            and all(_closed_quantity(item) for item in value["quantities"])
            and isinstance(value.get("comparison_groups"), list)
            and len(value["comparison_groups"]) == 2
            and all(isinstance(item, str) for item in value["comparison_groups"])
        )
    if form == "single_group_category_profile":
        return (
            isinstance(value.get("group_id"), str)
            and isinstance(value.get("categories"), list)
            and bool(value["categories"])
            and all(_closed_quantity(item) for item in value["categories"])
        )
    return (
        form == "unavailable"
        and value.get("reason") in {"not_reported", "not_measured", "not_estimable"}
        and isinstance(value.get("explanation"), str)
    )


def _closed_derived(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {
        "operation",
        "numerator_inputs",
        "denominator_inputs",
    }:
        return False
    return (
        value.get("operation") in {"risk_ratio", "risk_difference"}
        and isinstance(value.get("numerator_inputs"), list)
        and len(value["numerator_inputs"]) == 2
        and all(_closed_quantity(item) for item in value["numerator_inputs"])
        and isinstance(value.get("denominator_inputs"), list)
        and len(value["denominator_inputs"]) == 2
        and all(_closed_quantity(item) for item in value["denominator_inputs"])
    )


def _closed_clarity(value: object) -> bool:
    fields = {
        "outcome_definition",
        "measurement",
        "time_point",
        "analysis_population",
        "comparison_groups",
        "effect_measure",
        "source_table_meaning",
        "choice_among_eligible_results",
    }
    return isinstance(value, dict) and set(value) == fields and all(
        isinstance(item, dict)
        and set(item) == {"state", "explanation"}
        and item.get("state") in {"specified", "unclear", "unavailable"}
        and (item.get("explanation") is None or isinstance(item.get("explanation"), str))
        for item in value.values()
    )


def _closed_compatibility(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"status", "reasons"}
        and value.get("status") in {"compatible", "review_required", "incompatible"}
        and isinstance(value.get("reasons"), list)
        and all(isinstance(reason, str) for reason in value["reasons"])
    )


def _sources_and_evidence(
    bundle: _Bundle, proposal: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, bytes, tuple[str, ...], str]]]:
    """Bind captured source bytes and every retained Evidence record independently."""
    captured = bundle.names.get("captured_batch.json")
    if captured is None:
        bundle.failures.append("captured Batch is unavailable")
        return {}, {}
    payload = {key: captured.get(key) for key in ("plan", "acknowledgment", "sources")}
    if captured.get("kind") != "captured_batch" or _canonical(payload) != captured.get("identity"):
        bundle.failures.append("captured Batch identity is invalid")
        return {}, {}
    plan_value = captured.get("plan")
    plan_id = (
        plan_value
        if isinstance(plan_value, str) and plan_value.startswith("sha256:")
        else _ref(plan_value, "intake_plan")
    )
    plan = bundle.names.get("intake_plan.json")
    ack_value = captured.get("acknowledgment")
    intake_ack_id = (
        ack_value
        if isinstance(ack_value, str) and ack_value.startswith("sha256:")
        else _ref(ack_value, "review_ack")
    )
    intake_ack = bundle.names.get("review_ack.json")
    plan_payload = (
        {key: plan.get(key) for key in ("preflight", "entries", "blockers", "conditions")}
        if plan is not None
        else None
    )
    ack_payload = (
        {
            key: intake_ack.get(key)
            for key in ("record", "authority", "purpose", "caller", "observed_at")
        }
        if intake_ack is not None
        else None
    )
    conditional_intake = bool((plan or {}).get("conditions"))
    expected_intake_authority = "researcher" if conditional_intake else "host"
    valid_intake_caller = (
        str((intake_ack or {}).get("caller", "")).startswith(("cli:", "server:"))
        if conditional_intake
        else str((intake_ack or {}).get("caller", "")).startswith("host:")
    )
    if (
        plan is None
        or plan.get("kind") != "intake_plan"
        or plan.get("identity") != plan_id
        or _canonical(plan_payload) != plan_id
        or intake_ack is None
        or intake_ack.get("kind") != "review_ack"
        or intake_ack.get("identity") != intake_ack_id
        or _canonical(ack_payload) != intake_ack_id
        or intake_ack.get("record") != _ref_record("intake_plan", plan_id)
        or intake_ack.get("purpose") != "intake"
        or intake_ack.get("authority") != expected_intake_authority
        or not valid_intake_caller
    ):
        bundle.failures.append("captured Intake plan and acknowledgment chain is invalid")
    if _ref(proposal.get("captured_batch"), "captured_batch") != captured.get("identity"):
        bundle.failures.append("Proposal does not bind the exact captured Batch")
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]] = {}
    for source in captured.get("sources", []):
        if not isinstance(source, dict):
            bundle.failures.append("captured Source record is invalid")
            continue
        source_id, trial, source_hash, recorded_media_type = (
            source.get("candidate_identity"),
            source.get("trial_id"),
            source.get("sha256"),
            source.get("media_type"),
        )
        path = bundle.root / "sources" / str(trial) / str(source_id)
        if (
            not isinstance(source_id, str)
            or not isinstance(trial, str)
            or not isinstance(source_hash, str)
        ):
            bundle.failures.append("captured Source identity is invalid")
        elif not path.is_file() or _bytes_hash(path.read_bytes()) != source_hash:
            bundle.failures.append("captured Source bytes are unavailable or corrupt")
        else:
            data = path.read_bytes()
            media_type = recorded_media_type or (
                "application/pdf" if data.startswith(b"%PDF-") else "text/plain"
            )
            try:
                if media_type == "application/pdf" or data.startswith(b"%PDF-"):
                    document = pymupdf.open(stream=data, filetype="pdf")
                    try:
                        pages = tuple(page.get_text() for page in document)
                    finally:
                        document.close()
                else:
                    pages = (data.decode("utf-8"),)
            except (UnicodeDecodeError, ValueError, pymupdf.FileDataError):
                pages = ()
            page_hashes = tuple(_bytes_hash(page.encode()) for page in pages)
            projection_hash = _canonical(
                {
                    "recipe": "rob2-kit.extract-pages.v1",
                    "source_sha256": source_hash,
                    "media_type": media_type,
                    "page_hashes": page_hashes,
                }
            )
            sources[source_id] = (trial, data, pages, projection_hash)
    evidence: dict[str, dict[str, Any]] = {}
    for row in bundle.records.values():
        if row.get("kind") == "visual":
            _validate_visual_evidence(bundle, sources, row, evidence)
            continue
        if row.get("kind") != "text":
            continue
        fields = (
            "kind",
            "trial_id",
            "snapshot",
            "source_id",
            "source_sha256",
            "projection_hash",
            "page",
            "start",
            "end",
            "quote",
            "quote_sha256",
        )
        if not _has_exact_record_keys(row, fields) or _canonical(
            {key: row.get(key) for key in fields}
        ) != row.get("identity"):
            bundle.failures.append("Evidence identity is invalid")
            continue
        if row.get("snapshot") != _captured_snapshot(bundle, sources, row.get("trial_id")):
            bundle.failures.append("Evidence snapshot binding is invalid")
            continue
        source = sources.get(row.get("source_id"))
        page = row.get("page")
        if (
            source is None
            or row.get("trial_id") != source[0]
            or row.get("source_sha256") != _bytes_hash(source[1])
            or row.get("projection_hash") != source[3]
            or not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= len(source[2])
        ):
            bundle.failures.append("Evidence provenance or exact quote binding is invalid")
            continue
        source_page = source[2][page - 1]
        quote = row.get("quote")
        start, end = row.get("start"), row.get("end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(quote, str)
            or not quote
            or not 0 <= start < end <= len(source_page)
        ):
            bundle.failures.append("Evidence provenance or exact quote binding is invalid")
        elif source_page[start:end] != quote or row.get("quote_sha256") != _bytes_hash(
            quote.encode()
        ):
            bundle.failures.append("Evidence provenance or exact quote binding is invalid")
        else:
            evidence[str(row.get("identity"))] = row
    return evidence, sources


def _verify_proposal_evidence(
    bundle: _Bundle,
    proposal: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    required_roles: tuple[str, ...],
) -> None:
    """Require every Proposal Evidence reference to resolve to verified Evidence."""
    for result in proposal.get("results", []):
        if not isinstance(result, dict):
            continue
        trial_id = result.get("trial_id")
        roles = result.get("evidence")
        if not isinstance(roles, dict):
            bundle.failures.append("Proposal Result Evidence bindings are invalid")
            continue
        if set(roles) != set(required_roles):
            bundle.failures.append("Proposal Result Evidence roles are incomplete")
        for references in roles.values():
            if not isinstance(references, list) or not references:
                bundle.failures.append("Proposal Result Evidence bindings are invalid")
                continue
            for reference in references:
                evidence_id = _evidence_ref(reference)
                record = evidence.get(evidence_id or "")
                if record is None or record.get("trial_id") != trial_id:
                    bundle.failures.append(
                        "Proposal Evidence reference is unavailable or unrelated"
                    )
    for disposition in proposal.get("needs_input", []):
        if not isinstance(disposition, dict):
            continue
        trial_id = disposition.get("trial_id")
        references = disposition.get("evidence")
        if not isinstance(references, list):
            bundle.failures.append("Proposal needs-input Evidence bindings are invalid")
            continue
        for reference in references:
            evidence_id = _evidence_ref(reference)
            record = evidence.get(evidence_id or "")
            if record is None or record.get("trial_id") != trial_id:
                bundle.failures.append("Proposal Evidence reference is unavailable or unrelated")


def _evidence_text(record: dict[str, Any]) -> str:
    value = record.get("quote", record.get("transcription", ""))
    return " ".join(str(value).casefold().split())


def _verify_result_evidence_facts(
    bundle: _Bundle,
    result: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    outcome: OutcomeFacts,
) -> None:
    roles = result.get("evidence")
    if not isinstance(roles, dict):
        return

    def role_text(role: str) -> str:
        references = roles.get(role, [])
        return " ".join(
            _evidence_text(evidence[_evidence_ref(reference) or ""])
            for reference in references
            if _evidence_ref(reference) in evidence
        )

    target_raw = result.get("target")
    population_raw = result.get("population")
    reported_raw = result.get("reported")
    target: dict[str, Any] = target_raw if isinstance(target_raw, dict) else {}
    population: dict[str, Any] = population_raw if isinstance(population_raw, dict) else {}
    reported: dict[str, Any] = reported_raw if isinstance(reported_raw, dict) else {}
    checks: list[tuple[str, object]] = [
        ("target_basis", target.get("outcome_definition")),
        ("target_basis", target.get("measurement")),
        ("target_basis", target.get("time_point_or_window")),
        ("target_basis", target.get("intended_effect_measure")),
        ("reported_context", result.get("source_table_meaning")),
        ("population_basis", target.get("intended_analysis_population")),
        ("population_basis", population.get("analyzed_population")),
    ]
    groups = target.get("comparison_groups")
    if isinstance(groups, list):
        checks.extend(
            ("target_basis", item.get("label")) for item in groups if isinstance(item, dict)
        )
    for quantity in reported.get("quantities", reported.get("categories", [])):
        if isinstance(quantity, dict):
            checks.extend(
                ("reported_values", quantity.get(field))
                for field in ("statistic", "unit", "group_or_category", "value")
            )
            checks.append(("population_basis", quantity.get("denominator_basis")))
    effect = reported.get("effect")
    if isinstance(effect, dict):
        checks.extend(
            ("reported_values", effect.get(field)) for field in ("statistic", "unit", "value")
        )
        checks.append(("population_basis", effect.get("denominator_basis")))
    for role, required in checks:
        if (
            isinstance(required, str)
            and required.strip()
            and _evidence_value(required) not in role_text(role)
        ):
            bundle.failures.append(f"Proposal Evidence does not contain required {role} fact")
    values = roles.get("reported_values")
    if not isinstance(values, list) or len(values) != 1:
        bundle.failures.append("reported-values Evidence must be one complete record")
    elif (record := evidence.get(_evidence_ref(values[0]) or "")) is None or record.get(
        "kind"
    ) != "text":
        bundle.failures.append("reported-values Evidence must be one text record")
    elif isinstance(reported.get("reported_text"), str) and not _contains_normalized(
        record.get("quote"), reported.get("reported_text")
    ):
        bundle.failures.append(
            "reported-values Evidence does not contain the complete reported text"
        )


def _evidence_value(value: str) -> str:
    return " ".join(value.casefold().replace("+", " plus ").replace("–", "-").split())


def _contains_normalized(container: object, value: object) -> bool:
    return (
        isinstance(container, str)
        and isinstance(value, str)
        and _evidence_value(value) in _evidence_value(container)
    )


def _verify_domain_binding_provenance(
    bundle: _Bundle, binding: dict[str, Any], record: dict[str, Any] | None
) -> None:
    if record is None or not isinstance(binding, dict):
        return
    fields = (
        ("kind", "trial_id", "snapshot", "source_id", "source_sha256", "projection_hash", "page"),
        ("start", "end", "quote", "quote_sha256")
        if record.get("kind") == "text"
        else ("region", "render", "transcription"),
    )
    for field in fields[0] + fields[1]:
        if binding.get(field) != record.get(field):
            bundle.failures.append("Domain evidence binding provenance does not match Evidence")
            return


def _validate_visual_evidence(
    bundle: _Bundle,
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
    row: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> None:
    fields = (
        "kind",
        "trial_id",
        "snapshot",
        "source_id",
        "source_sha256",
        "projection_hash",
        "page",
        "region",
        "render",
        "transcription",
    )
    if not _has_exact_record_keys(row, fields) or _canonical(
        {key: row.get(key) for key in fields}
    ) != row.get("identity"):
        bundle.failures.append("visual Evidence identity is invalid")
        return
    source = sources.get(row.get("source_id"))
    page = row.get("page")
    region = row.get("region")
    render = row.get("render")
    render_id = _render_ref(render)
    if (
        source is None
        or row.get("trial_id") != source[0]
        or row.get("source_sha256") != _bytes_hash(source[1])
        or row.get("projection_hash") != source[3]
        or not isinstance(page, int)
        or isinstance(page, bool)
        or not 1 <= page <= len(source[2])
        or not isinstance(row.get("snapshot"), str)
        or not isinstance(row.get("transcription"), str)
        or not row["transcription"].strip()
        or not isinstance(render_id, str)
        or not _valid_region(region)
        or row.get("snapshot") != _captured_snapshot(bundle, sources, row.get("trial_id"))
    ):
        bundle.failures.append("visual Evidence provenance is invalid")
        return
    token = render_id.removeprefix("sha256:")
    image_path = bundle.root / "renders" / f"{token}.png"
    try:
        metadata = bundle.names[f"render-{token}.json"]
        image = image_path.read_bytes()
    except (KeyError, OSError):
        bundle.failures.append("visual Evidence render record or PNG is unavailable")
        return
    render_payload = {
        "source_id": metadata.get("source_id"),
        "source_sha256": metadata.get("source_hash"),
        "page": metadata.get("page_number"),
        "region": metadata.get("region"),
        "recipe": metadata.get("recipe"),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "pixel_width": metadata.get("pixel_width"),
        "pixel_height": metadata.get("pixel_height"),
        "media_type": metadata.get("media_type"),
        "png_sha256": metadata.get("sha256"),
    }
    if (
        _canonical(render_payload) != render_id
        or metadata.get("render_identity") != render_id
        or metadata.get("source_id") != row.get("source_id")
        or metadata.get("source_hash") != row.get("source_sha256")
        or metadata.get("page_number") != page
        or metadata.get("region") != region
        or metadata.get("sha256") != _bytes_hash(image)
        or metadata.get("recipe") != "png-rgb-72dpi-full-144dpi-region-v1"
        or metadata.get("media_type") != "image/png"
        or len(image) < 26
        or image[:8] != b"\x89PNG\r\n\x1a\n"
        or image[12:16] != b"IHDR"
        or struct.unpack(">II", image[16:24])
        != (metadata.get("pixel_width"), metadata.get("pixel_height"))
    ):
        bundle.failures.append("visual Evidence render binding is invalid")
        return
    evidence[str(row.get("identity"))] = row


def _captured_snapshot(
    bundle: _Bundle,
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
    trial_id: object,
) -> str | None:
    captured = bundle.names.get("captured_batch.json")
    if captured is None or not isinstance(trial_id, str):
        return None
    preflight = bundle.names.get("preflight.json")
    candidates = {
        row.get("identity"): row
        for row in (preflight or {}).get("candidates", [])
        if isinstance(row, dict) and isinstance(row.get("identity"), str)
    }
    source_rows = [
        row
        for row in captured.get("sources", [])
        if (
            isinstance(row, dict)
            and row.get("trial_id") == trial_id
            and isinstance(row.get("candidate_identity"), str)
            and isinstance(row.get("role"), str)
            and isinstance(candidates.get(row["candidate_identity"]), dict)
        )
    ]
    if not source_rows:
        return None
    ordered = sorted(
        source_rows,
        key=lambda row: (
            int(row["role"] != "main_article"),
            Path(
                str(candidates[row["candidate_identity"]].get("relative_path", ""))
            ).name.casefold(),
            row["candidate_identity"],
        ),
    )
    ids = tuple(row["candidate_identity"] for row in ordered)
    if any(source_id not in sources for source_id in ids):
        return None
    return _canonical(
        {
            "trial_id": trial_id,
            "scope_kind": "captured_batch",
            "scope_hash": captured.get("identity"),
            "source_ids": ids,
            "source_hashes": tuple(_bytes_hash(sources[source_id][1]) for source_id in ids),
            "projection_hashes": tuple(sources[source_id][3] for source_id in ids),
            "tokenizer": "unicode61_casefold_no_diacritics_v1",
            "ordering": "authoritative_source_role_label_id_page_v1",
        }
    )


def _valid_region(value: object) -> bool:
    return value is None or (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
            for item in value
        )
        and 0 <= value[0] < value[2] <= 1
        and 0 <= value[1] < value[3] <= 1
    )


def _verify_packet_catalog(
    bundle: _Bundle,
    packet: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
    trial_id: object,
) -> None:
    catalog = packet.get("reusable_evidence")
    if (
        not isinstance(catalog, dict)
        or set(catalog) != {"basis", "entries", "has_more", "next_after"}
        or not isinstance(trial_id, str)
    ):
        bundle.failures.append("Domain work packet reusable Evidence catalog is invalid")
        return
    entries = catalog.get("entries")
    if (
        not isinstance(catalog.get("basis"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", catalog["basis"])
        or not isinstance(entries, list)
        or len(entries) > 32
        or not isinstance(catalog.get("has_more"), bool)
        or (catalog["has_more"] != (catalog.get("next_after") is not None))
    ):
        bundle.failures.append("Domain work packet reusable Evidence catalog is invalid")
        return
    captured = bundle.names.get("captured_batch.json")
    candidates = {
        row.get("identity"): row
        for row in (bundle.names.get("preflight.json") or {}).get("candidates", [])
        if isinstance(row, dict)
    }
    ordered_sources = sorted(
        (
            row
            for row in (captured or {}).get("sources", [])
            if isinstance(row, dict) and row.get("trial_id") == trial_id
        ),
        key=lambda row: (
            int(row.get("role") != "main_article"),
            Path(
                str(candidates.get(row.get("candidate_identity"), {}).get("relative_path", ""))
            ).name.casefold(),
            str(row.get("candidate_identity")),
        ),
    )
    source_aliases = {
        row.get("candidate_identity"): f"s{index}" for index, row in enumerate(ordered_sources, 1)
    }
    expected_aliases = [f"s{index}" for index in range(1, len(ordered_sources) + 1)]
    if packet.get("stable_aliases") != expected_aliases:
        bundle.failures.append("Domain work packet stable aliases are invalid")
    actual: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            bundle.failures.append("Domain work packet reusable Evidence catalog is invalid")
            continue
        reference = entry.get("evidence")
        evidence_id = _evidence_ref(reference)
        if (
            not isinstance(reference, dict)
            or set(reference) != {"kind", "identity"}
            or reference.get("kind") != "evidence"
            or not isinstance(evidence_id, str)
            or len(evidence_id) != 71
            or any(character not in "0123456789abcdef" for character in evidence_id[7:])
        ):
            bundle.failures.append("Domain work packet reusable Evidence reference is invalid")
            continue
        record = evidence.get(evidence_id or "")
        if (
            record is None
            or record.get("trial_id") != trial_id
            or entry.get("kind") != record.get("kind")
            or not isinstance(entry.get("source_id"), str)
            or not entry.get("source_id")
            or entry.get("source_id") != record.get("source_id")
            or not isinstance(entry.get("source_alias"), str)
            or not 1 <= len(entry.get("source_alias")) <= 16
            or entry.get("source_alias") != source_aliases.get(record.get("source_id"))
            or not isinstance(entry.get("page"), int)
            or isinstance(entry.get("page"), bool)
            or entry.get("page") < 1
            or entry.get("page") != record.get("page")
        ):
            bundle.failures.append("Domain work packet reusable Evidence catalog is unbound")
            continue
        if entry.get("kind") == "text":
            valid = {
                "kind",
                "evidence",
                "source_id",
                "source_alias",
                "page",
                "start",
                "end",
                "preview",
                "truncated",
            }
            matches = (
                isinstance(entry.get("start"), int)
                and not isinstance(entry.get("start"), bool)
                and entry.get("start") >= 0
                and isinstance(entry.get("end"), int)
                and not isinstance(entry.get("end"), bool)
                and entry.get("end") > entry.get("start")
                and isinstance(entry.get("preview"), str)
                and bool(entry.get("preview"))
                and len(entry.get("preview")) <= 160
                and isinstance(entry.get("truncated"), bool)
                and entry.get("start") == record.get("start")
                and entry.get("end") == record.get("end")
                and entry.get("preview") == record.get("quote", "")[:160]
                and entry.get("truncated") is (len(record.get("quote", "")) > 160)
            )
        elif entry.get("kind") == "visual":
            valid = {
                "kind",
                "evidence",
                "source_id",
                "source_alias",
                "page",
                "region",
                "preview",
                "truncated",
            }
            matches = (
                _valid_region(entry.get("region"))
                and isinstance(entry.get("preview"), str)
                and bool(entry.get("preview"))
                and len(entry.get("preview")) <= 160
                and isinstance(entry.get("truncated"), bool)
                and entry.get("region") == record.get("region")
                and entry.get("preview") == record.get("transcription", "")[:160]
                and entry.get("truncated") is (len(record.get("transcription", "")) > 160)
            )
        else:
            valid, matches = set(), False
        if set(entry) != valid or not matches:
            bundle.failures.append("Domain work packet reusable Evidence catalog is tampered")
            continue
        actual.append(evidence_id or "")
    if actual != sorted(actual) or len(actual) != len(set(actual)):
        bundle.failures.append(
            "Domain work packet reusable Evidence catalog is unsorted or duplicate"
        )
    next_after = catalog.get("next_after")
    if next_after is not None and (not actual or _evidence_ref(next_after) != actual[-1]):
        bundle.failures.append(
            "Domain work packet reusable Evidence catalog continuation is invalid"
        )


def _verify_approved_dispositions(
    bundle: _Bundle, approved: dict[str, Any] | None, proposal: dict[str, Any]
) -> None:
    if approved is None:
        bundle.failures.append("Approved Batch is unavailable")
        return
    needs_input = {
        str(item.get("trial_id"))
        for item in proposal.get("needs_input", [])
        if isinstance(item, dict)
    }
    expected = sorted(
        [[trial_id, "needs_input"] for trial_id in needs_input]
        + [
            [str(item.get("trial_id")), "pending"]
            for item in proposal.get("results", [])
            if isinstance(item, dict) and str(item.get("trial_id")) not in needs_input
        ]
    )
    if approved.get("dispositions") != expected:
        bundle.failures.append("Approved Batch dispositions do not match Proposal dispositions")


def _verify_report_semantics(bundle: _Bundle, summary: dict[str, Any], report: str) -> None:
    def trial_section(trial_id: object) -> str:
        if not isinstance(trial_id, str) or not trial_id:
            return ""
        marker = f"<section><h2>{html.escape(trial_id)}</h2>"
        start = report.find(marker)
        if start < 0:
            return ""
        end = report.find("</section>", start + len(marker))
        return report[start : end + len("</section>")] if end >= 0 else ""

    def require(section: str, value: object, detail: str) -> None:
        if isinstance(value, str) and value and html.escape(value) not in section:
            bundle.failures.append(f"report omits {detail}")

    def require_global(value: object, detail: str) -> None:
        if isinstance(value, str) and value and html.escape(value) not in report:
            bundle.failures.append(f"report omits {detail}")

    require_global(summary.get("identity"), "summary identity")
    summary_presentation = summary.get("presentation", {})
    if isinstance(summary_presentation, dict):
        require_global(summary_presentation.get("code"), "summary presentation code")
    approved = bundle.names.get("approved_batch.json", {})
    require_global(approved.get("identity"), "approved Batch identity")
    require_global(approved.get("review"), "approved Proposal review")
    proposal = next(
        (
            row
            for row in bundle.records.values()
            if row.get("kind") == "proposal_review"
            and row.get("identity") == approved.get("review")
        ),
        {},
    )
    for trial in summary.get("trials", []):
        if not isinstance(trial, dict):
            continue
        trial_id = trial.get("trial_id")
        section = trial_section(trial_id)
        if not section:
            bundle.failures.append(f"report omits Trial section {trial_id}")
            continue
        require(section, trial_id, "Trial identity")
        require(section, trial.get("disposition"), f"disposition for Trial {trial_id}")
        result = next(
            (
                row
                for row in proposal.get("results", [])
                if isinstance(row, dict) and row.get("trial_id") == trial_id
            ),
            None,
        )
        if isinstance(result, dict):
            target = result.get("target", {})
            reported = result.get("reported", {})
            if isinstance(target, dict):
                for field in (
                    "outcome_definition",
                    "measurement",
                    "time_point_or_window",
                    "intended_analysis_population",
                ):
                    require(section, target.get(field), f"target {field}")
            if isinstance(reported, dict):
                require(section, reported.get("reported_text"), "reported source text")
                for quantity in reported.get("quantities", reported.get("categories", [])):
                    if isinstance(quantity, dict):
                        for field in (
                            "statistic",
                            "group_or_category",
                            "value",
                            "unit",
                            "denominator_basis",
                        ):
                            require(section, quantity.get(field), f"reported {field}")
                effect = reported.get("effect")
                if isinstance(effect, dict):
                    for field in (
                        "statistic",
                        "group_or_category",
                        "value",
                        "unit",
                        "denominator_basis",
                    ):
                        require(section, effect.get(field), f"reported effect {field}")
                precision = reported.get("precision")
                if isinstance(precision, dict):
                    interval = precision.get("confidence_interval", {})
                    p_value = precision.get("p_value", {})
                    if isinstance(interval, dict):
                        for field in ("level", "lower", "upper"):
                            require(
                                section,
                                interval.get(field),
                                f"reported confidence interval {field}",
                            )
                    if isinstance(p_value, dict):
                        require(section, p_value.get("operator"), "reported P-value operator")
                        require(section, p_value.get("value"), "reported P-value value")
            if trial.get("disposition") == "assessed":
                snapshot = trial.get("snapshot", {})
                snapshot_id = snapshot.get("identity") if isinstance(snapshot, dict) else None
                hashes = {
                    str(item[1])
                    for row in bundle.records.values()
                    if row.get("kind") == "assessment_snapshot"
                    and row.get("identity") == snapshot_id
                    for item in row.get("checkpoint_hashes", [])
                    if isinstance(item, list) and len(item) == 2
                }
                for checkpoint in bundle.records.values():
                    if (
                        checkpoint.get("kind") == "domain_candidate"
                        and checkpoint.get("trial_id") == trial_id
                        and checkpoint.get("active_hash") in hashes
                    ):
                        require(section, checkpoint.get("domain_id"), "retained Domain")
                        require(section, checkpoint.get("proposed_judgment"), "Domain judgment")
                        for binding in checkpoint.get("evidence_bindings", []):
                            if isinstance(binding, dict):
                                reference = binding.get("evidence")
                                if isinstance(reference, dict):
                                    require(section, reference.get("identity"), "Domain Evidence")
            else:
                terminal = next(
                    (
                        row
                        for row in bundle.records.values()
                        if row.get("kind") == "trial_terminal" and row.get("trial_id") == trial_id
                    ),
                    {},
                )
                require(section, terminal.get("reason"), "terminal reason")
                for missing in terminal.get("missing_facts", []):
                    require(section, missing, "terminal missing fact")
                for reference in terminal.get("evidence", []):
                    if isinstance(reference, dict):
                        require(section, reference.get("identity"), "terminal Evidence")
                acknowledgment = terminal.get("acknowledgment", {})
                if isinstance(acknowledgment, dict):
                    require(
                        section,
                        acknowledgment.get("identity"),
                        "terminal researcher acknowledgment",
                    )
        else:
            terminal = next(
                (
                    row
                    for row in bundle.records.values()
                    if row.get("kind") == "trial_terminal" and row.get("trial_id") == trial_id
                ),
                {},
            )
            require(section, terminal.get("reason"), "terminal reason")
            for missing in terminal.get("missing_facts", []):
                require(section, missing, "terminal missing fact")
            for reference in terminal.get("evidence", []):
                if isinstance(reference, dict):
                    require(section, reference.get("identity"), "terminal Evidence")


def _assessed(
    bundle: _Bundle,
    summary: dict[str, Any],
    proposal: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
) -> None:
    if summary.get("counts") != {
        "total": 1,
        "pending": 0,
        "assessed": 1,
        "needs_input": 0,
        "failed": 0,
    }:
        bundle.failures.append("assessed final counts are invalid")
        return
    approved = bundle.names.get("approved_batch.json")
    if approved is None:
        bundle.failures.append("Approved Batch is unavailable")
        return
    base = {key: approved.get(key) for key in ("review", "acknowledgment", "dispositions")}
    if _canonical(base) != approved.get("identity") or approved.get("review") != proposal.get(
        "identity"
    ):
        bundle.failures.append("Approved Batch identity or Proposal chain is invalid")
    if summary["approved_batch"].get("identity") != approved.get("identity"):
        bundle.failures.append("finalization does not bind Approved Batch")
    ack = bundle.names.get("proposal_ack.json")
    ack_fields = ("record", "authority", "purpose", "caller", "observed_at")
    if (
        ack is None
        or ack.get("authority") != "researcher"
        or ack.get("purpose") != "proposal"
        or not str(ack.get("caller", "")).startswith(("cli:", "server:"))
        or not ack.get("observed_at")
    ):
        bundle.failures.append(
            "Proposal acknowledgment authority, purpose, caller, or time is invalid"
        )
    elif (
        _canonical({key: ack.get(key) for key in ack_fields}) != ack.get("identity")
        or ack.get("identity") != approved.get("acknowledgment")
        or ack.get("record") != _ref_record("proposal_review", proposal.get("identity"))
    ):
        bundle.failures.append("Proposal acknowledgment identity or binding is invalid")
    rows = [
        row
        for row in bundle.records.values()
        if row.get("kind") == "domain_candidate" and "active_hash" in row
    ]
    domain_order = tuple(domain.id for domain in SCIENTIFIC_PACK.domains)
    domain_questions = {domain.id: list(domain.question_ids) for domain in SCIENTIFIC_PACK.domains}
    retained_hashes: dict[str, str] = {}
    for row in rows:
        domain = row.get("domain_id")
        active_hash = row.get("active_hash")
        if (
            isinstance(domain, str)
            and domain in domain_questions
            and domain not in retained_hashes
            and isinstance(row.get("identity"), str)
            and isinstance(row.get("active_revision"), int)
            and _is_hash(active_hash)
            and _canonical({"candidate": row["identity"], "revision": row["active_revision"]})
            == active_hash
        ):
            retained_hashes[domain] = active_hash
    domains: dict[str, dict[str, Any]] = {}
    for row in rows:
        fields = (
            "kind",
            "packet",
            "trial_id",
            "result_id",
            "domain_id",
            "draft",
            "proposed_judgment",
            "inactive_questions",
            "evidence_bindings",
            "scientific_pack",
            "policy_pack",
        )
        if _canonical({key: row.get(key) for key in fields}) != row.get("identity"):
            bundle.failures.append("Domain candidate identity is invalid")
            continue
        if not isinstance(row.get("evidence_bindings"), list) or not row["evidence_bindings"]:
            bundle.failures.append("Domain candidate must have nonempty evidence bindings")
            continue
        if (
            row.get("scientific_pack") != SCIENTIFIC_PACK.content_hash
            or row.get("policy_pack") != MAINTAINER_POLICY_PACK.content_hash
        ):
            bundle.failures.append("Domain candidate does not bind the known pack catalog")
        if _canonical(
            {"candidate": row["identity"], "revision": row.get("active_revision")}
        ) != row.get("active_hash"):
            bundle.failures.append("Domain checkpoint identity is invalid")
        if _domain_oracle(row) != row.get("proposed_judgment"):
            bundle.failures.append("Domain checkpoint deterministic judgment is invalid")
        packet_ref = row.get("packet")
        packet_id = _ref(packet_ref, "work_packet")
        packet = bundle.records.get(packet_id or "")
        packet_fields = (
            "kind",
            "approved_batch",
            "trial_id",
            "result_id",
            "domain_id",
            "active_question_ids",
            "allowed_question_ids",
            "stable_aliases",
            "reusable_evidence",
            "prior_domain_hashes",
            "scientific_pack",
            "policy_pack",
        )
        if (
            packet is None
            or not _has_exact_record_keys(packet, packet_fields)
            or _canonical({key: packet.get(key) for key in packet_fields}) != packet_id
            or _ref(packet.get("approved_batch"), "approved_batch") != approved.get("identity")
            or any(
                packet.get(key) != row.get(key) for key in ("trial_id", "result_id", "domain_id")
            )
            or packet.get("scientific_pack") != SCIENTIFIC_PACK.content_hash
            or packet.get("policy_pack") != MAINTAINER_POLICY_PACK.content_hash
            or packet.get("scientific_pack") != row.get("scientific_pack")
            or packet.get("policy_pack") != row.get("policy_pack")
        ):
            bundle.failures.append("Domain work packet, Batch binding, or pack basis is invalid")
        domain = row.get("domain_id")
        if not isinstance(domain, str) or domain not in domain_questions:
            bundle.failures.append("Domain checkpoint is outside the SCIENTIFIC_PACK")
        else:
            expected_questions = domain_questions[domain]
            if (
                not isinstance(packet, dict)
                or not isinstance(packet.get("active_question_ids"), list)
                or not isinstance(packet.get("allowed_question_ids"), list)
                or packet.get("active_question_ids") != expected_questions
                or packet.get("allowed_question_ids") != expected_questions
            ):
                bundle.failures.append("Domain work packet question scope is invalid")
            prior = packet.get("prior_domain_hashes") if isinstance(packet, dict) else None
            prior_valid = isinstance(prior, list) and all(
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                and _is_hash(item[1])
                for item in prior
            )
            expected_prior = [
                [earlier, retained_hashes.get(earlier)]
                for earlier in domain_order[: domain_order.index(domain)]
            ]
            if not prior_valid or prior != expected_prior:
                bundle.failures.append("Domain work packet prior checkpoint chain is invalid")
        _verify_packet_catalog(bundle, packet or {}, evidence, sources, row.get("trial_id"))
        for binding in row.get("evidence_bindings", []):
            reference = binding.get("evidence") if isinstance(binding, dict) else None
            evidence_id = _evidence_ref(reference)
            record = evidence.get(evidence_id or "")
            if (
                not isinstance(binding, dict)
                or not isinstance(reference, dict)
                or not isinstance(binding.get("claim"), str)
                or not binding["claim"].strip()
                or record is None
                or record.get("trial_id") != row.get("trial_id")
                or reference.get("identity") != evidence_id
            ):
                bundle.failures.append(
                    "Domain evidence binding is missing, unrelated, or unprovenanced"
                )
            _verify_domain_binding_provenance(bundle, binding, record)
        domain = str(row.get("domain_id"))
        if domain in domains:
            bundle.failures.append("duplicate active Domain checkpoint")
        domains[domain] = row
    required = {
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    }
    if set(domains) != required:
        bundle.failures.append("assessed Trial does not have exactly five Domain checkpoints")
        return
    judgments = [str(row.get("proposed_judgment")) for row in domains.values()]
    overall = _overall_judgment(judgments)
    assessed = [row for row in summary["trials"] if row.get("disposition") == "assessed"]
    if len(assessed) != 1:
        bundle.failures.append("release assessed outcome must have assessed count one")
        return
    terminal = bundle.names.get(f"trial-outcome-{assessed[0].get('trial_id')}.json")
    snap_id = _ref(assessed[0].get("snapshot"), "assessment_snapshot")
    snapshot = bundle.records.get(snap_id or "")
    synthesis_id = _ref((snapshot or {}).get("synthesis"), "trial_synthesis")
    synthesis = bundle.records.get(synthesis_id or "")
    if (
        terminal is None
        or snapshot is None
        or terminal.get("snapshot", {}).get("identity") != snap_id
    ):
        bundle.failures.append("assessed terminal/snapshot chain is unavailable")
    elif snapshot.get("proposed_overall") != overall or snapshot.get("final_judgment") != overall:
        bundle.failures.append("AssessmentSnapshot deterministic overall is invalid")
    else:
        fields = (
            "synthesis",
            "checkpoint_hashes",
            "proposed_overall",
            "final_judgment",
            "caller",
            "observed_at",
        )
        if _canonical({key: snapshot.get(key) for key in fields}) != snapshot.get("identity"):
            bundle.failures.append("AssessmentSnapshot identity is invalid")
        synthesis_fields = (
            "approved_batch",
            "trial_id",
            "result_id",
            "checkpoint_hashes",
            "checkpoint_judgments",
            "proposed_overall",
            "combined_concerns",
        )
        if (
            synthesis is None
            or _canonical(
                {
                    key: (False if key == "combined_concerns" else synthesis.get(key))
                    for key in synthesis_fields
                }
            )
            != synthesis.get("identity")
            or synthesis.get("checkpoint_hashes") != snapshot.get("checkpoint_hashes")
            or {tuple(row) for row in synthesis.get("checkpoint_hashes", [])}
            != {(domain, value.get("active_hash")) for domain, value in domains.items()}
        ):
            bundle.failures.append("synthesis/checkpoint identity chain is invalid")
        terminal_fields = (
            "synthesis",
            "trial_id",
            "disposition",
            "reason",
            "failure_cause",
            "missing_facts",
            "available_evidence",
            "retained_checkpoints",
            "caller",
            "observed_at",
            "snapshot",
            "transition",
        )
        if (
            terminal.get("kind") != "trial_terminal"
            or _canonical({key: terminal.get(key) for key in terminal_fields})
            != terminal.get("identity")
            or assessed[0].get("outcome", {}).get("identity") != terminal.get("identity")
        ):
            bundle.failures.append("assessed terminal identity is invalid")
        else:
            finish_ack = next(
                (
                    row
                    for row in bundle.records.values()
                    if row.get("kind") == "review_ack"
                    and row.get("purpose") == "trial_finish"
                    and row.get("record") == _ref_record("trial_synthesis", synthesis_id)
                ),
                None,
            )
            finish_ack_payload = (
                {
                    key: finish_ack.get(key)
                    for key in ("record", "authority", "purpose", "caller", "observed_at")
                }
                if finish_ack is not None
                else None
            )
            if (
                finish_ack is None
                or finish_ack.get("authority") != "researcher"
                or not str(finish_ack.get("caller", "")).startswith(("cli:", "server:"))
                or _canonical(finish_ack_payload) != finish_ack.get("identity")
            ):
                bundle.failures.append("assessed Trial finish acknowledgment chain is invalid")


def _needs_input(
    bundle: _Bundle,
    summary: dict[str, Any],
    proposal: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> None:
    """Validate the preapproval terminal separately from the AE Result card."""
    approved = bundle.names.get("approved_batch.json")
    ack = bundle.names.get("proposal_ack.json")
    if approved is None or ack is None:
        bundle.failures.append("AE Approved Batch or Proposal acknowledgment is unavailable")
        return
    base = {key: approved.get(key) for key in ("review", "acknowledgment", "dispositions")}
    if _canonical(base) != approved.get("identity") or approved.get("review") != proposal.get(
        "identity"
    ):
        bundle.failures.append("AE Approved Batch identity or Proposal binding is invalid")
    ack_fields = ("record", "authority", "purpose", "caller", "observed_at")
    if (
        ack.get("authority") != "researcher"
        or ack.get("purpose") != "proposal"
        or not str(ack.get("caller", "")).startswith(("cli:", "server:"))
        or _canonical({key: ack.get(key) for key in ack_fields}) != ack.get("identity")
        or ack.get("identity") != approved.get("acknowledgment")
        or ack.get("record") != _ref_record("proposal_review", proposal.get("identity"))
    ):
        bundle.failures.append("AE Proposal acknowledgment chain is invalid")
    terminals = [row for row in summary["trials"] if row.get("disposition") == "needs_input"]
    if len(terminals) != 1:
        bundle.failures.append("AE needs-input terminal count is invalid")
        return
    terminal = bundle.names.get(f"trial-outcome-{terminals[0].get('trial_id')}.json")
    proposal_terminal = next(
        (
            item
            for item in proposal.get("needs_input", [])
            if isinstance(item, dict) and item.get("trial_id") == terminals[0].get("trial_id")
        ),
        None,
    )
    fields = ("trial_id", "disposition", "reason", "missing_facts", "evidence", "acknowledgment")
    if (
        terminal is None
        or terminal.get("kind") != "trial_terminal"
        or terminal.get("disposition") != "needs_input"
        or terminal.get("reason") != "comparator_unavailable"
        or _canonical({key: terminal.get(key) for key in fields}) != terminal.get("identity")
        or _ref(terminal.get("acknowledgment"), "review_ack") != ack.get("identity")
        or terminals[0].get("outcome", {}).get("identity") != terminal.get("identity")
        or not isinstance(proposal_terminal, dict)
        or terminal.get("reason") != proposal_terminal.get("reason")
        or terminal.get("missing_facts") != proposal_terminal.get("missing_facts")
        or terminal.get("evidence") != proposal_terminal.get("evidence")
    ):
        bundle.failures.append(
            "AE needs-input terminal identity, reason, or acknowledgment is invalid"
        )
    terminal_evidence = terminal.get("evidence") if terminal is not None else None
    if not isinstance(terminal_evidence, list) or not terminal_evidence:
        bundle.failures.append("AE needs-input terminal requires nonempty Evidence")
    else:
        trial_id = terminals[0].get("trial_id")
        for reference in terminal_evidence:
            evidence_id = _evidence_ref(reference)
            record = evidence.get(evidence_id or "")
            if record is None or record.get("trial_id") != trial_id:
                bundle.failures.append("AE terminal Evidence reference is unavailable or unrelated")
    if summary.get("presentation", {}).get("code") != "finalized_zero_assessed":
        bundle.failures.append("AE finalization presentation is invalid")


def verify_artifact(
    root: str | Path,
    objective: ObjectiveFactManifest,
    outcome_key: str,
    *,
    trace: tuple[TraceEvent, ...] | list[TraceEvent] | None = None,
) -> VerificationResult:
    """Verify bytes, identities, workflow chains, and independent RoB 2 logic."""
    failures: list[str] = []
    if trace:
        failures.extend(check_trace(trace))
        if outcome_key == "adverse_events":
            failures.extend(
                check_required_operations(
                    trace, (("clarify_adverse_events", "completed"),)
                )
            )
    else:
        failures.append("nonempty complete trace is required")
    bundle = _Bundle(Path(root), failures)
    bundle.load()
    summary, proposal = _summary(bundle), _proposal(bundle, outcome_key, objective)
    expected = objective.outcome(outcome_key).expected_terminal
    if summary is not None and proposal is not None:
        _verify_approved_dispositions(bundle, bundle.names.get("approved_batch.json"), proposal)
        evidence, sources = _sources_and_evidence(bundle, proposal)
        _verify_proposal_evidence(
            bundle, proposal, evidence, objective.outcome(outcome_key).required_evidence_context
        )
        facts = objective.outcome(outcome_key)
        for result in proposal.get("results", []):
            if isinstance(result, dict):
                _verify_result_evidence_facts(bundle, result, evidence, facts)
        if expected == "assessed":
            _assessed(bundle, summary, proposal, evidence, sources)
        elif summary.get("counts") != {
            "total": 1,
            "pending": 0,
            "assessed": 0,
            "needs_input": 1,
            "failed": 0,
        }:
            failures.append("adverse-events final counts are invalid")
        else:
            _needs_input(bundle, summary, proposal, evidence)
    if not (bundle.root / "report.html").is_file():
        failures.append("verified report artifact is unavailable")
    receipt = bundle.names.get("finalization-receipt.json")
    if (
        receipt is None
        or receipt.get("outcome") != "committed"
        or receipt.get("summary") != (summary or {}).get("identity")
        or receipt.get("kind") != "finalization_receipt"
        or _canonical({"summary": receipt.get("summary"), "outcome": receipt.get("outcome")})
        != receipt.get("identity")
    ):
        failures.append("durable finalization receipt is unavailable or unbound")
    try:
        report = (bundle.root / "report.html").read_text(encoding="utf-8")
        if summary is None:
            failures.append("report does not bind the finalized summary")
        else:
            _verify_report_semantics(bundle, summary, report)
    except (OSError, KeyError, TypeError):
        failures.append("verified report artifact is unavailable")
    return VerificationResult(not failures, tuple(failures), (outcome_key,) if proposal else ())
