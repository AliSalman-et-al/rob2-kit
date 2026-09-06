from __future__ import annotations

import runpy
from itertools import product
from pathlib import Path

import pytest
from support.rob2 import _assessment_workspace, _call, _domain_draft, _option_for

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _answer_option
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK


def test_every_pack_answer_has_one_stable_literal_option() -> None:
    options = [
        (question, answer, _answer_option(question, answer))
        for question in SCIENTIFIC_PACK.questions
        for answer in question.allowed_answers
    ]
    assert len({option["id"] for _question, _answer, option in options}) == len(options)
    for question, answer, option in options:
        assert option == _answer_option(question, answer)
        assert option["official_answer"] == answer.value
        assert option["proposition"] == (
            "true"
            if answer.value in {"yes", "probably_yes"}
            else "false"
            if answer.value in {"no", "probably_no"}
            else "unknown"
        )
        assert option["certainty"] == (
            "certain"
            if answer.value in {"yes", "no"}
            else "probable"
            if answer.value in {"probably_yes", "probably_no"}
            else "unknown"
        )
        assert option["decision_table_value"] == (
            "yes"
            if answer.value in {"yes", "probably_yes"}
            else "no"
            if answer.value in {"no", "probably_no"}
            else "no_information"
        )
        assert question.wording not in option["meaning"]
        assert option["anchor"]
        assert "complete active answer path" in option["consequence"]


def test_every_option_round_trips_through_evaluator_and_independent_rules() -> None:
    independent = runpy.run_path("scripts/verify_bundle.py")
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
            canonical = {
                question_id: answer
                for question_id, answer in supplied.items()
                if question_id in active
            }
            evaluation = evaluate_domain(domain.id, canonical)
            for item in canonical.items():
                witness_paths.setdefault(item, canonical)
            if set(witness_paths) == expected:
                break
        assert set(witness_paths) == expected

        for (question_id, official_answer), path in witness_paths.items():
            question = next(item for item in questions if item.id == question_id)
            answer = next(
                item for item in question.allowed_answers if item.value == official_answer
            )
            option = _answer_option(question, answer)
            option_table = {
                _answer_option(question, candidate)["id"]: candidate.value
                for candidate in question.allowed_answers
            }
            assert option_table[option["id"]] == official_answer
            evaluation = evaluate_domain(domain.id, path)
            independent_active, _independent_inactive = independent["_domain_question_sets"](
                domain.id,
                path,
            )
            assert set(independent_active) == set(path)
            assert independent["_domain_judgment"](domain.id, path) == evaluation.judgment.value


@pytest.mark.parametrize(
    "official_answer",
    ["yes", "probably_yes", "probably_no", "no", "no_information"],
)
def test_option_submission_persists_only_the_official_answer(
    tmp_path: Path,
    official_answer: str,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["option_id"] = _option_for(
        "sq:randomization:sequence",
        official_answer,
    )

    saved = _call(workspace, "save_domain_judgment", draft)

    assert saved["outcome"] == "success", saved
    checkpoint = _state(workspace)["domain_records"]["trial:domain:randomization"]
    answer = next(
        item for item in checkpoint["answers"] if item["question_id"] == "sq:randomization:sequence"
    )
    assert answer["answer"] == official_answer
    assert "option_id" not in answer


def test_option_polarity_remains_literal_for_opposite_risk_directions() -> None:
    imbalance = next(
        question
        for question in SCIENTIFIC_PACK.questions
        if question.id == "sq:randomization:baseline-imbalance"
    )
    unbiased = next(
        question
        for question in SCIENTIFIC_PACK.questions
        if question.id == "sq:missing:evidence-unbiased"
    )
    imbalance_yes = next(a for a in imbalance.allowed_answers if a.value == "yes")
    assert _answer_option(imbalance, imbalance_yes)["proposition"] == "true"
    assert (
        _answer_option(unbiased, next(a for a in unbiased.allowed_answers if a.value == "yes"))[
            "proposition"
        ]
        == "true"
    )
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


def test_option_and_evidence_defects_are_aggregated_without_mutation(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["option_id"] = _option_for(
        "sq:randomization:concealment",
        "yes",
    )
    draft["answers"][1]["bases"] = [{"kind": "direct_support", "evidence": "eh_0000000000000000"}]
    before = _state(workspace)

    repaired = _call(workspace, "save_domain_judgment", draft)

    assert repaired["outcome"] == "repair"
    assert {item["code"] for item in repaired["repairs"]} >= {
        "invalid_answer_option",
        "answers_must_match_active_questions",
        "invalid_evidence",
    }
    option_repair = next(
        item for item in repaired["repairs"] if item["code"] == "invalid_answer_option"
    )
    assert "Use one current card option" in option_repair["detail"]
    assert _state(workspace) == before


def test_invalid_fifth_save_does_not_freeze_then_corrected_save_does(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains[:4]:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    fifth = _domain_draft("trial", "domain:selection", revision, evidence)
    fifth["answers"][0]["option_id"] = "opt_stale_fifth_save_value"

    repaired = _call(workspace, "save_domain_judgment", fifth)

    assert repaired["outcome"] == "repair"
    assert _state(workspace)["phase"] == "assessment"
    assert "trial" not in _state(workspace).get("snapshots", {})
    fifth["answers"][0]["option_id"] = _option_for(
        fifth["answers"][0]["question_id"],
        "no_information",
    )
    saved = _call(workspace, "save_domain_judgment", fifth)
    assert saved["outcome"] == "success", saved
    assert saved["data"]["trial_completed"] is True
    assert _state(workspace)["phase"] == "ready_to_finalize"
