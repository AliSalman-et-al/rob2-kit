import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.logic.conformance import (
    ConformanceFailure,
    assert_conformance,
    load_conformance_suite,
)
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import (
    GuidancePack,
    LogicPack,
    load_guidance_pack,
    load_logic_pack,
    validate_guidance_compatibility,
)

PACK_ROOT = Path(__file__).parents[1] / "packs"


@pytest.fixture(scope="module")
def logic_pack() -> LogicPack:
    return load_logic_pack(PACK_ROOT / "logic" / "rob2-parallel-assignment-2019.1.yaml")


@pytest.fixture(scope="module")
def evaluator(logic_pack: LogicPack) -> LogicEvaluator:
    return LogicEvaluator(logic_pack)


def low_answers() -> dict[str, str]:
    return {
        "sq:randomization:sequence": "yes",
        "sq:randomization:concealment": "yes",
        "sq:randomization:baseline-imbalance": "no",
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:appropriate-analysis": "yes",
        "sq:missing:data-available": "yes",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no",
        "sq:selection:multiple-analyses": "no",
    }


def test_evaluator_rejects_noncanonical_answers_and_agent_judgments(
    logic_pack: LogicPack,
) -> None:
    with pytest.raises(ValidationError):
        EvaluationRequest(answers={"sq:randomization:sequence": "Y"})
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(
            {"answers": {}, "judgment": "low"},
        )
    with pytest.raises(ValueError, match="not_applicable"):
        LogicEvaluator(logic_pack).evaluate(
            EvaluationRequest.model_construct(
                answers={"sq:randomization:sequence": "not_applicable"},
                assessor_inputs={},
            )
        )


def test_low_risk_path_is_deterministic_and_traced(evaluator: LogicEvaluator) -> None:
    request = EvaluationRequest(answers=low_answers())
    first = evaluator.evaluate(request)
    second = evaluator.evaluate(request)

    assert first == second
    assert set(first.domain_judgments.values()) == {JudgmentLevel.LOW}
    assert first.overall_judgment is JudgmentLevel.LOW
    assert first.answers == {
        question_id: SQAnswerCategory(answer) for question_id, answer in low_answers().items()
    }
    assert first.assessor_inputs == {}
    assert "sq:deviations:context-deviations" in first.inactive_question_ids
    assert "rule:overall:all-low" in first.matched_rule_ids
    assert first.logic_pack_hash.startswith("sha256:")


def test_branch_state_is_derived_and_active_answers_are_required(
    evaluator: LogicEvaluator,
) -> None:
    answers = low_answers()
    answers["sq:missing:data-available"] = "no"
    with pytest.raises(ValueError, match="sq:missing:evidence-unbiased"):
        evaluator.evaluate(EvaluationRequest(answers=answers))

    answers["sq:missing:evidence-unbiased"] = "yes"
    result = evaluator.evaluate(EvaluationRequest(answers=answers))
    assert result.question_states["sq:missing:evidence-unbiased"] == "answered"
    assert result.question_states["sq:missing:true-value-dependent"] == "not_applicable"


def test_partial_answer_activation_is_incremental_and_exposes_dependencies(
    evaluator: LogicEvaluator,
) -> None:
    assert "sq:deviations:context-deviations" not in evaluator.active_question_ids_for_answers({})
    assert "sq:deviations:context-deviations" in evaluator.active_question_ids_for_answers(
        {"sq:deviations:participants-aware": SQAnswerCategory.YES}
    )
    assert "sq:deviations:context-deviations" not in evaluator.active_question_ids_for_answers(
        {"sq:deviations:participants-aware": SQAnswerCategory.NO}
    )
    dependencies = evaluator.activation_dependencies("sq:deviations:context-deviations")
    assert dependencies.answer_question_ids == (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
    )


def test_partial_activation_validates_input_and_prior_domain_context(logic_pack: LogicPack) -> None:
    payload = logic_pack.model_dump(exclude={"content_hash"})
    questions = {item["id"]: item for item in payload["questions"]}
    questions["sq:deviations:context-deviations"]["active_if"] = {
        "op": "input_equals",
        "input_id": "input:combined-concerns",
        "value": True,
    }
    questions["sq:deviations:affected-outcome"]["active_if"] = {
        "op": "domain_all",
        "judgments": ["low"],
    }
    custom_pack = LogicPack.model_validate(payload)
    evaluator = LogicEvaluator(custom_pack)

    assert "sq:deviations:context-deviations" in evaluator.active_question_ids_for_answers(
        {}, {"input:combined-concerns": True}
    )
    assert "sq:deviations:context-deviations" not in evaluator.active_question_ids_for_answers(
        {}, {"input:combined-concerns": False}
    )
    assert "sq:deviations:affected-outcome" in evaluator.active_question_ids_for_answers(
        {}, prior_domain_judgments={"domain:randomization": JudgmentLevel.LOW}
    )
    assert "sq:deviations:affected-outcome" not in evaluator.active_question_ids_for_answers(
        {}, prior_domain_judgments={"domain:randomization": JudgmentLevel.HIGH}
    )
    assert evaluator.activation_dependencies(
        "sq:deviations:context-deviations"
    ).assessor_input_ids == ("input:combined-concerns",)
    assert evaluator.activation_dependencies("sq:deviations:affected-outcome").domain_ids == tuple(
        sorted(domain.id for domain in custom_pack.domains)
    )
    with pytest.raises(ValueError, match="unknown assessor inputs"):
        evaluator.active_question_ids_for_answers({}, {"input:unknown": True})
    with pytest.raises(ValueError, match="unknown Logic domain IDs"):
        evaluator.active_question_ids_for_answers(
            {}, prior_domain_judgments={"domain:unknown": JudgmentLevel.LOW}
        )


def test_missing_data_exoneration_rejects_no_information_for_q3_2(
    evaluator: LogicEvaluator,
) -> None:
    answers = low_answers()
    answers["sq:missing:data-available"] = "no"
    answers["sq:missing:evidence-unbiased"] = "no_information"
    with pytest.raises(ValueError, match="outside the question vocabulary"):
        evaluator.evaluate(EvaluationRequest(answers=answers))


def test_high_domain_controls_overall_judgment(evaluator: LogicEvaluator) -> None:
    answers = low_answers()
    answers["sq:randomization:concealment"] = "no"
    result = evaluator.evaluate(EvaluationRequest(answers=answers))
    assert result.domain_judgments["domain:randomization"] is JudgmentLevel.HIGH
    assert result.overall_judgment is JudgmentLevel.HIGH


def test_multiple_concerns_use_the_structured_assessor_input(
    evaluator: LogicEvaluator,
) -> None:
    answers = low_answers()
    answers["sq:randomization:baseline-imbalance"] = "yes"
    answers["sq:selection:prespecified-analysis"] = "no"

    result = evaluator.evaluate(
        EvaluationRequest(
            answers=answers,
            assessor_inputs={"input:combined-concerns": False},
        )
    )
    assert result.overall_judgment is JudgmentLevel.SOME_CONCERNS
    assert result.assessor_inputs == {"input:combined-concerns": False}
    assert result.required_assessor_input_ids == ("input:combined-concerns",)

    high = evaluator.evaluate(
        EvaluationRequest(
            answers=answers,
            assessor_inputs={"input:combined-concerns": True},
        )
    )
    assert high.overall_judgment is JudgmentLevel.HIGH

    with pytest.raises(ValueError, match="unknown assessor inputs"):
        evaluator.evaluate(
            EvaluationRequest(
                answers=answers,
                assessor_inputs={"input:unknown": True},
            )
        )


def test_guidance_is_hash_pinned_and_cannot_change_behavior(
    evaluator: LogicEvaluator,
    logic_pack: LogicPack,
) -> None:
    guidance = load_guidance_pack(
        PACK_ROOT / "guidance" / "rob2-parallel-assignment-en-2019.1.yaml"
    )
    validate_guidance_compatibility(logic_pack, guidance)
    assert guidance.compatible_logic_hashes == (logic_pack.content_hash,)
    baseline = evaluator.evaluate(EvaluationRequest(answers=low_answers()))
    changed = GuidancePack.model_validate(
        {
            **guidance.model_dump(exclude={"content_hash"}),
            "items": [
                {**item.model_dump(), "text": f"{item.text} presentation-only"}
                for item in guidance.items
            ],
        }
    )
    assert changed.content_hash != guidance.content_hash
    assert evaluator.evaluate(EvaluationRequest(answers=low_answers())) == baseline


def test_meaningful_rule_mutation_is_detected_by_golden_case(logic_pack: LogicPack) -> None:
    mutated = deepcopy(logic_pack.model_dump(exclude={"content_hash"}))
    rule = next(
        rule
        for domain in mutated["domains"]
        for rule in domain["judgment_rules"]
        if rule["id"] == "rule:randomization:concealment-failed"
    )
    rule["judgment"] = "low"
    result = LogicEvaluator(LogicPack.model_validate(mutated)).evaluate(
        EvaluationRequest(
            answers={
                **low_answers(),
                "sq:randomization:concealment": SQAnswerCategory.NO,
            }
        )
    )
    assert result.domain_judgments["domain:randomization"] is not JudgmentLevel.HIGH


def test_pack_rejects_undeclared_logic_element_references(logic_pack: LogicPack) -> None:
    invalid = deepcopy(logic_pack.model_dump(exclude={"content_hash"}))
    invalid["questions"][5]["active_if"]["conditions"][0]["question_id"] = "sq:typo"
    with pytest.raises(ValidationError, match="undeclared Logic elements"):
        LogicPack.model_validate(invalid)


def test_distributable_schemas_match_runtime_pack_validators() -> None:
    logic_schema = PACK_ROOT.parents[0] / "schemas" / "logic-pack.schema.json"
    guidance_schema = PACK_ROOT.parents[0] / "schemas" / "guidance-pack.schema.json"
    assert json.loads(logic_schema.read_text()) == LogicPack.model_json_schema()
    assert json.loads(guidance_schema.read_text()) == GuidancePack.model_json_schema()


def test_exact_release_passes_independent_conformance_suite(logic_pack: LogicPack) -> None:
    suite = load_conformance_suite(
        PACK_ROOT.parents[0] / "tests" / "conformance" / "rob2-2019.1.yaml"
    )
    assert_conformance(logic_pack, suite)
    assert len(suite.reviewer_slots) == 2
    assert not any(slot.completed for slot in suite.reviewer_slots)


def test_conformance_rejects_a_meaningful_mutation(logic_pack: LogicPack) -> None:
    suite = load_conformance_suite(
        PACK_ROOT.parents[0] / "tests" / "conformance" / "rob2-2019.1.yaml"
    )
    mutated = deepcopy(logic_pack.model_dump(exclude={"content_hash"}))
    rule = next(
        rule
        for domain in mutated["domains"]
        for rule in domain["judgment_rules"]
        if rule["id"] == "rule:randomization:concealment-failed"
    )
    rule["judgment"] = "low"
    mutated_pack = LogicPack.model_validate(mutated)
    mutation_pinned_suite = suite.model_copy(
        update={"logic_content_hash": mutated_pack.content_hash}
    )
    with pytest.raises(ConformanceFailure):
        assert_conformance(mutated_pack, mutation_pinned_suite)


def test_conformance_rejects_a_branch_mutation(logic_pack: LogicPack) -> None:
    suite = load_conformance_suite(
        PACK_ROOT.parents[0] / "tests" / "conformance" / "rob2-2019.1.yaml"
    )
    mutated = deepcopy(logic_pack.model_dump(exclude={"content_hash"}))
    question = next(
        item for item in mutated["questions"] if item["id"] == "sq:deviations:context-deviations"
    )
    question["active_if"]["conditions"][0]["answers"] = ["probably_yes", "no_information"]
    mutated_pack = LogicPack.model_validate(mutated)
    mutation_pinned_suite = suite.model_copy(
        update={"logic_content_hash": mutated_pack.content_hash}
    )
    with pytest.raises(ConformanceFailure):
        assert_conformance(mutated_pack, mutation_pinned_suite)
