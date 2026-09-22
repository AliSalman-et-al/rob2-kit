from __future__ import annotations

import runpy
from copy import deepcopy
from typing import Any

from rob2_kit.application.domains import (
    _counterfactual_answer_branch,
    _counterfactual_missing_reason,
    _overall_receipt,
)
from rob2_kit.logic.evaluator import active_questions, evaluate_domain, evaluate_overall
from rob2_kit.packs import SCIENTIFIC_PACK


def _deviation_answers() -> dict[str, str]:
    return {
        "sq:deviations:participants-aware": "no_information",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:context-deviations": "no_information",
        "sq:deviations:appropriate-analysis": "yes",
    }


def test_counterfactual_projection_handles_deactivation_and_independence() -> None:
    answers = _deviation_answers()

    projected, active, missing = _counterfactual_answer_branch(
        "domain:deviations",
        answers,
        "sq:deviations:participants-aware",
        "probably_no",
    )
    assert active == (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
        "sq:deviations:appropriate-analysis",
    )
    assert "sq:deviations:context-deviations" not in projected
    assert not missing

    projected, active, missing = _counterfactual_answer_branch(
        "domain:deviations",
        answers,
        "sq:deviations:personnel-aware",
        "probably_no",
    )
    assert "sq:deviations:participants-aware" in active
    assert projected["sq:deviations:participants-aware"] == "no_information"
    assert projected["sq:deviations:context-deviations"] == "no_information"
    assert not missing


def test_counterfactual_projection_identifies_newly_active_question() -> None:
    projected, active, missing = _counterfactual_answer_branch(
        "domain:deviations",
        _deviation_answers(),
        "sq:deviations:context-deviations",
        "probably_yes",
    )
    assert "sq:deviations:affected-outcome" in active
    assert "sq:deviations:affected-outcome" in missing
    assert "sq:deviations:affected-outcome" not in projected
    assert _counterfactual_missing_reason(missing) == (
        "missing active question IDs: [sq:deviations:affected-outcome]"
    )


def _complete_records() -> tuple[dict[str, Any], dict[str, str]]:
    records: dict[str, Any] = {}
    judgments: dict[str, str] = {}
    questions = {question.id: question for question in SCIENTIFIC_PACK.questions}
    for domain in SCIENTIFIC_PACK.domains:
        answers: dict[str, str] = {}
        while True:
            active = tuple(
                question_id
                for question_id in active_questions(answers)
                if question_id in domain.question_ids
            )
            missing = [question_id for question_id in active if question_id not in answers]
            if not missing:
                break
            answers.update(
                {
                    question_id: (
                        "no_information"
                        if "no_information" in questions[question_id].allowed_answers
                        else questions[question_id].allowed_answers[0].value
                    )
                    for question_id in missing
                }
            )
        evaluation = evaluate_domain(domain.id, answers)
        judgments[domain.id] = evaluation.judgment.value
        records[f"trial:{domain.id}"] = {
            "identity": f"checkpoint:{domain.id}",
            "trial_id": "trial",
            "domain_id": domain.id,
            "answers": [
                {"question_id": question_id, "answer": answers[question_id]}
                for question_id in active
            ],
            "active_questions": list(active),
            "inactive_questions": [
                question.id
                for question in SCIENTIFIC_PACK.questions
                if question.domain_id == domain.id and question.id not in active
            ],
            "judgment": evaluation.judgment.value,
            "trace": list(evaluation.trace),
            "driver_questions": list(evaluation.driver_questions),
            "evidence_sufficiency": {
                "claims": [
                    {"question_id": question_id, "status": "unresolved"} for question_id in active
                ]
            },
        }
    return records, judgments


def test_overall_receipt_projects_without_mutating_and_replays_consistently() -> None:
    records, judgments = _complete_records()
    original = deepcopy(records)
    evaluation = evaluate_overall(judgments)
    receipt = _overall_receipt("trial", records, judgments, evaluation)

    assert records == original
    snapshot = {"trial_id": "trial", "domain_judgments": judgments}
    from rob2_kit.application.finalization import _valid_overall_receipt

    assert _valid_overall_receipt(receipt, snapshot, records, evaluation)
    verifier = runpy.run_path("scripts/verify_bundle.py", run_name="verify_bundle_module")
    assert verifier["_valid_overall_receipt"](receipt, snapshot, records)

    pending = [
        item for item in receipt["alternatives"] if item["status"] == "requires_reassessment"
    ]
    assert pending
    assert all(item["reason"] and "sq:" in item["reason"] for item in pending)
