from __future__ import annotations

import runpy
from itertools import product

from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.application._state import _state
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK


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

    repaired = _call(workspace, "save_domain_judgment", draft)

    assert repaired["outcome"] == "repair", repaired
    repair = next(item for item in repaired["repairs"] if item["code"] == "invalid_answer")
    assert repair["path"] == "/answers/1/answer"
    assert "no_information" in repair["detail"]
    assert draft["answers"] == original_answers
    assert _state(workspace) == before
