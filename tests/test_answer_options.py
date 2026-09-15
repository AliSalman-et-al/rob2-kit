from __future__ import annotations

import runpy
from itertools import product

import pytest
from pydantic import TypeAdapter
from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.contracts import DomainQuestionCard
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.models import Answer
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import DomainAnswer


def test_public_question_card_uses_readable_question_scoped_answer_values() -> None:
    adapter = TypeAdapter(DomainAnswer)
    for question in SCIENTIFIC_PACK.questions:
        card = DomainQuestionCard(
            id=question.id,
            wording=question.wording,
            options=tuple(question.allowed_answers),
            activation_status="always_active",
            activation=question.activation.model_dump(mode="python"),
            official_guidance=question.guidance.official.source_excerpt,
            source_locator=question.guidance.official.source_locator,
            decision_rule=question.guidance.operational.decision_rule,
            evidence_needed=question.guidance.operational.evidence_needed,
            no_information_rule=question.guidance.operational.no_information_rule,
            considerations=question.guidance.operational.considerations,
            invalid_shortcuts=question.guidance.operational.invalid_shortcuts,
            query_suggestions=question.guidance.operational.query_suggestions,
        )
        assert [answer.value for answer in card.options] == [
            answer.value for answer in question.allowed_answers
        ]
        for answer in question.allowed_answers:
            assert (
                adapter.validate_python(
                    {
                        "question_id": question.id,
                        "answer": answer.value,
                        "bases": [{"kind": "context", "evidence": "eh_0000000000000000"}],
                    }
                ).answer
                == answer
            )


def test_each_readable_answer_round_trips_through_all_active_paths() -> None:
    independent_judgment = runpy.run_path("scripts/verify_bundle.py")["_domain_judgment"]
    for domain in SCIENTIFIC_PACK.domains:
        questions = [
            question for question in SCIENTIFIC_PACK.questions if question.domain_id == domain.id
        ]
        expected = {
            (question.id, answer.value)
            for question in questions
            for answer in question.allowed_answers
        }
        witness_paths: dict[tuple[str, str], dict[str, str]] = {}
        for values in product(*(question.allowed_answers for question in questions)):
            supplied = {
                question.id: answer.value
                for question, answer in zip(questions, values, strict=True)
            }
            active = set(active_questions(supplied)) & {question.id for question in questions}
            path = {
                question_id: answer
                for question_id, answer in supplied.items()
                if question_id in active
            }
            evaluate_domain(domain.id, path)
            for item in path.items():
                witness_paths.setdefault(item, path)
            if set(witness_paths) == expected:
                break
        assert set(witness_paths) == expected

        for (question_id, answer), path in witness_paths.items():
            question = next(item for item in questions if item.id == question_id)
            assert answer in {item.value for item in question.allowed_answers}
            assert evaluate_domain(domain.id, path).judgment.value == independent_judgment(
                domain.id, path
            )


@pytest.mark.parametrize("official_answer", [answer.value for answer in Answer])
def test_readable_answer_is_committed_as_the_official_value(tmp_path, official_answer: str) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["answer"] = official_answer

    saved = _call(workspace, "save_domain_judgment", draft)

    assert saved["outcome"] == "success", saved
    checkpoint = _state(workspace)["domain_records"]["trial:domain:randomization"]
    answer = next(
        item
        for item in checkpoint["answers"]
        if item["question_id"] == draft["answers"][0]["question_id"]
    )
    assert answer["answer"] == official_answer
    assert "option_id" not in answer


def test_question_scope_rejects_unlisted_value_without_rewriting_it(tmp_path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain_id in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace, "save_domain_judgment", _domain_draft("trial", domain_id, revision, evidence)
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][0]["answer"] = "no"
    draft["answers"][1]["answer"] = "no_information"  # 3.2 does not permit this value.
    for answer in draft["answers"]:
        answer.update(
            justification="The cited passage bears on this question.",
            unknowns=[],
            counterevidence=[],
        )
    original_answers = [dict(answer) for answer in draft["answers"]]
    before = _state(workspace)

    repaired = _call(workspace, "validate_domain_assessment", draft)

    assert repaired["outcome"] == "repair", repaired
    repair = next(item for item in repaired["repairs"] if item["code"] == "invalid_answer")
    assert repair["path"] == "/answers/1/answer"
    assert "no_information" in repair["detail"]
    assert draft["answers"] == original_answers
    assert _state(workspace) == before


def test_public_repair_preserves_negative_answer_and_unaffected_answers(tmp_path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["answer"] = "no"
    draft["answers"][0]["bases"] = [{"kind": "inference", "evidence": evidence["handle"]}]
    for answer in draft["answers"]:
        answer.update(
            justification="The cited bases support the submitted answer.",
            unknowns=[],
            counterevidence=[],
        )
    unaffected = [dict(answer) for answer in draft["answers"][1:]]

    repaired = _call(workspace, "validate_domain_assessment", draft)

    assert repaired["outcome"] == "repair", repaired
    repair = next(
        item for item in repaired["repairs"] if item["code"] == "answer_requires_direct_basis"
    )
    assert "'no'" in repair["detail"]
    assert "direct, indirect, or contradictory Evidence basis" in repair["detail"]
    assert "probably_yes" not in repair["detail"]
    assert "probably_no" not in repair["detail"]
    assert draft["answers"][0]["answer"] == "no"
    assert draft["answers"][1:] == unaffected


def test_readable_answers_keep_opposite_question_polarities() -> None:
    assert (
        evaluate_domain(
            "domain:randomization",
            {
                "sq:randomization:sequence": "yes",
                "sq:randomization:concealment": "yes",
                "sq:randomization:baseline-imbalance": "yes",
            },
        ).judgment.value
        == "some_concerns"
    )
    assert (
        evaluate_domain(
            "domain:missing",
            {
                "sq:missing:data-available": "no",
                "sq:missing:evidence-unbiased": "yes",
            },
        ).judgment.value
        == "low"
    )
