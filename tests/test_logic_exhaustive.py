"""Independent exhaustive transcription of every supported per-domain path."""

from collections.abc import Callable
from itertools import product
from pathlib import Path
from typing import cast

import pytest

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import load_logic_pack
from tests.test_logic_evaluator import low_answers

ANSWERS = tuple(answer.value for answer in SQAnswerCategory)
PACK = load_logic_pack(
    Path(__file__).parents[1] / "packs" / "logic" / "rob2-parallel-assignment-2019.1.yaml"
)


def paths(question_ids: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        dict(zip(question_ids, values, strict=True))
        for values in product(ANSWERS, repeat=len(question_ids))
    ]


def deviations_paths() -> list[dict[str, str]]:
    valid: list[dict[str, str]] = []
    for awareness in product(ANSWERS, repeat=2):
        partial = {
            "sq:deviations:participants-aware": awareness[0],
            "sq:deviations:personnel-aware": awareness[1],
        }
        context_values = (
            ANSWERS if {"yes", "probably_yes", "no_information"} & set(awareness) else (None,)
        )
        for context in context_values:
            if context is not None:
                partial["sq:deviations:context-deviations"] = context
            affected_values = ANSWERS if context in {"yes", "probably_yes"} else (None,)
            for affected in affected_values:
                if affected is not None:
                    partial["sq:deviations:affected-outcome"] = affected
                balanced_values = (
                    ANSWERS if affected in {"yes", "probably_yes", "no_information"} else (None,)
                )
                for balanced in balanced_values:
                    if balanced is not None:
                        partial["sq:deviations:balanced"] = balanced
                    for analysis in ANSWERS:
                        partial["sq:deviations:appropriate-analysis"] = analysis
                        impacts = (
                            ANSWERS
                            if analysis in {"probably_no", "no", "no_information"}
                            else (None,)
                        )
                        for impact in impacts:
                            candidate = dict(partial)
                            if impact is not None:
                                candidate["sq:deviations:substantial-impact"] = impact
                            valid.append(cast(dict[str, str], candidate))
                    partial.pop("sq:deviations:balanced", None)
                partial.pop("sq:deviations:affected-outcome", None)
            partial.pop("sq:deviations:context-deviations", None)
    return valid


def missing_paths() -> list[dict[str, str]]:
    valid: list[dict[str, str]] = []
    for available in ANSWERS:
        evidence_values = (
            ANSWERS if available in {"probably_no", "no", "no_information"} else (None,)
        )
        for evidence in evidence_values:
            dependent_values = ANSWERS if evidence in {"probably_no", "no"} else (None,)
            for dependent in dependent_values:
                likely_values = (
                    ANSWERS if dependent in {"yes", "probably_yes", "no_information"} else (None,)
                )
                for likely in likely_values:
                    candidate = {"sq:missing:data-available": available}
                    if evidence is not None:
                        candidate["sq:missing:evidence-unbiased"] = evidence
                    if dependent is not None:
                        candidate["sq:missing:true-value-dependent"] = dependent
                    if likely is not None:
                        candidate["sq:missing:likely-dependent"] = likely
                    valid.append(candidate)
    return valid


def measurement_paths() -> list[dict[str, str]]:
    valid: list[dict[str, str]] = []
    for method, differential in product(ANSWERS, repeat=2):
        assessor_values = (
            ANSWERS
            if method in {"probably_no", "no", "no_information"}
            and differential in {"probably_no", "no", "no_information"}
            else (None,)
        )
        for assessor in assessor_values:
            possible_values = (
                ANSWERS if assessor in {"yes", "probably_yes", "no_information"} else (None,)
            )
            for possible in possible_values:
                likely_values = (
                    ANSWERS if possible in {"yes", "probably_yes", "no_information"} else (None,)
                )
                for likely in likely_values:
                    candidate = {
                        "sq:measurement:method-inappropriate": method,
                        "sq:measurement:differential": differential,
                    }
                    if assessor is not None:
                        candidate["sq:measurement:assessor-aware"] = assessor
                    if possible is not None:
                        candidate["sq:measurement:influence-possible"] = possible
                    if likely is not None:
                        candidate["sq:measurement:influence-likely"] = likely
                    valid.append(candidate)
    return valid


def randomization_oracle(a: dict[str, str]) -> JudgmentLevel:
    if a["sq:randomization:concealment"] in {"probably_no", "no"}:
        return JudgmentLevel.HIGH
    if a["sq:randomization:concealment"] == "no_information" and a[
        "sq:randomization:baseline-imbalance"
    ] in {"yes", "probably_yes"}:
        return JudgmentLevel.HIGH
    if (
        a["sq:randomization:sequence"] in {"probably_no", "no"}
        or a["sq:randomization:concealment"] == "no_information"
        or a["sq:randomization:baseline-imbalance"] in {"yes", "probably_yes"}
    ):
        return JudgmentLevel.SOME_CONCERNS
    return JudgmentLevel.LOW


def deviations_oracle(a: dict[str, str]) -> JudgmentLevel:
    if (
        a.get("sq:deviations:context-deviations") in {"yes", "probably_yes"}
        and a.get("sq:deviations:affected-outcome") in {"yes", "probably_yes", "no_information"}
        and a.get("sq:deviations:balanced") in {"probably_no", "no", "no_information"}
    ) or (
        a["sq:deviations:appropriate-analysis"] in {"probably_no", "no", "no_information"}
        and a.get("sq:deviations:substantial-impact") in {"yes", "probably_yes", "no_information"}
    ):
        return JudgmentLevel.HIGH
    if (
        a.get("sq:deviations:context-deviations") == "no_information"
        or a.get("sq:deviations:affected-outcome") in {"probably_no", "no"}
        or a.get("sq:deviations:balanced") in {"yes", "probably_yes"}
        or a.get("sq:deviations:substantial-impact") in {"probably_no", "no"}
    ):
        return JudgmentLevel.SOME_CONCERNS
    return JudgmentLevel.LOW


def missing_oracle(a: dict[str, str]) -> JudgmentLevel:
    if a["sq:missing:data-available"] in {"yes", "probably_yes"}:
        return JudgmentLevel.LOW
    if a.get("sq:missing:evidence-unbiased") in {"yes", "probably_yes"}:
        return JudgmentLevel.LOW
    if a.get("sq:missing:true-value-dependent") in {"probably_no", "no"}:
        return JudgmentLevel.LOW
    if a.get("sq:missing:likely-dependent") in {"yes", "probably_yes", "no_information"}:
        return JudgmentLevel.HIGH
    return JudgmentLevel.SOME_CONCERNS


def measurement_oracle(a: dict[str, str]) -> JudgmentLevel:
    if (
        a["sq:measurement:method-inappropriate"] in {"yes", "probably_yes"}
        or a["sq:measurement:differential"] in {"yes", "probably_yes"}
        or a.get("sq:measurement:influence-likely") in {"yes", "probably_yes", "no_information"}
    ):
        return JudgmentLevel.HIGH
    if (
        a["sq:measurement:method-inappropriate"] == "no_information"
        or a["sq:measurement:differential"] == "no_information"
        or a.get("sq:measurement:assessor-aware") == "no_information"
        or a.get("sq:measurement:influence-likely") in {"probably_no", "no"}
    ):
        return JudgmentLevel.SOME_CONCERNS
    return JudgmentLevel.LOW


def selection_oracle(a: dict[str, str]) -> JudgmentLevel:
    if a["sq:selection:multiple-measurements"] in {"yes", "probably_yes"} or a[
        "sq:selection:multiple-analyses"
    ] in {"yes", "probably_yes"}:
        return JudgmentLevel.HIGH
    if (
        a["sq:selection:prespecified-analysis"] in {"probably_no", "no", "no_information"}
        or a["sq:selection:multiple-measurements"] == "no_information"
        or a["sq:selection:multiple-analyses"] == "no_information"
    ):
        return JudgmentLevel.SOME_CONCERNS
    return JudgmentLevel.LOW


@pytest.mark.parametrize(
    ("domain_id", "domain_paths", "oracle"),
    [
        (
            "domain:randomization",
            paths(
                (
                    "sq:randomization:sequence",
                    "sq:randomization:concealment",
                    "sq:randomization:baseline-imbalance",
                )
            ),
            randomization_oracle,
        ),
        ("domain:deviations", deviations_paths(), deviations_oracle),
        ("domain:missing", missing_paths(), missing_oracle),
        ("domain:measurement", measurement_paths(), measurement_oracle),
        (
            "domain:selection",
            paths(
                (
                    "sq:selection:prespecified-analysis",
                    "sq:selection:multiple-measurements",
                    "sq:selection:multiple-analyses",
                )
            ),
            selection_oracle,
        ),
    ],
)
def test_every_valid_answer_combination_matches_independent_transcription(
    domain_id: str,
    domain_paths: list[dict[str, str]],
    oracle: Callable[[dict[str, str]], JudgmentLevel],
) -> None:
    evaluator = LogicEvaluator(PACK)
    base = low_answers()
    domain_question_ids = next(
        set(domain.question_ids) for domain in PACK.domains if domain.id == domain_id
    )
    for domain_answers in domain_paths:
        answers = {
            **{key: value for key, value in base.items() if key not in domain_question_ids},
            **domain_answers,
        }
        result = evaluator.evaluate(EvaluationRequest(answers=answers))
        assert result.domain_judgments[domain_id] is oracle(domain_answers)
        expected_active = tuple(
            question.id for question in PACK.questions if question.id in answers
        )
        assert result.active_question_ids == expected_active
        assert result.inactive_question_ids == tuple(
            question.id for question in PACK.questions if question.id not in answers
        )
        assert result.answers == {
            question_id: SQAnswerCategory(answers[question_id]) for question_id in expected_active
        }
        assert result.evaluated_rule_ids
        assert result.matched_rule_ids


DOMAIN_REPRESENTATIVES = {
    "domain:randomization": {
        JudgmentLevel.LOW: {},
        JudgmentLevel.SOME_CONCERNS: {"sq:randomization:baseline-imbalance": "yes"},
        JudgmentLevel.HIGH: {"sq:randomization:concealment": "no"},
    },
    "domain:deviations": {
        JudgmentLevel.LOW: {},
        JudgmentLevel.SOME_CONCERNS: {
            "sq:deviations:appropriate-analysis": "no",
            "sq:deviations:substantial-impact": "no",
        },
        JudgmentLevel.HIGH: {
            "sq:deviations:appropriate-analysis": "no",
            "sq:deviations:substantial-impact": "yes",
        },
    },
    "domain:missing": {
        JudgmentLevel.LOW: {},
        JudgmentLevel.SOME_CONCERNS: {
            "sq:missing:data-available": "no",
            "sq:missing:evidence-unbiased": "no_information",
        },
        JudgmentLevel.HIGH: {
            "sq:missing:data-available": "no",
            "sq:missing:evidence-unbiased": "no",
            "sq:missing:true-value-dependent": "yes",
            "sq:missing:likely-dependent": "yes",
        },
    },
    "domain:measurement": {
        JudgmentLevel.LOW: {},
        JudgmentLevel.SOME_CONCERNS: {
            "sq:measurement:assessor-aware": "no_information",
            "sq:measurement:influence-possible": "no",
        },
        JudgmentLevel.HIGH: {
            "sq:measurement:assessor-aware": "yes",
            "sq:measurement:influence-possible": "yes",
            "sq:measurement:influence-likely": "yes",
        },
    },
    "domain:selection": {
        JudgmentLevel.LOW: {},
        JudgmentLevel.SOME_CONCERNS: {"sq:selection:prespecified-analysis": "no"},
        JudgmentLevel.HIGH: {"sq:selection:multiple-measurements": "yes"},
    },
}


def test_every_domain_judgment_combination_yields_expected_overall_trace() -> None:
    evaluator = LogicEvaluator(PACK)
    domain_ids = tuple(DOMAIN_REPRESENTATIVES)
    levels = tuple(JudgmentLevel)
    for combination in product(levels, repeat=len(domain_ids)):
        answers = low_answers()
        for domain_id, level in zip(domain_ids, combination, strict=True):
            answers.update(DOMAIN_REPRESENTATIVES[domain_id][level])
        result = evaluator.evaluate(EvaluationRequest(answers=answers))
        if JudgmentLevel.HIGH in combination:
            expected = JudgmentLevel.HIGH
            expected_rule = "rule:overall:any-high"
        elif JudgmentLevel.SOME_CONCERNS in combination:
            expected = JudgmentLevel.SOME_CONCERNS
            expected_rule = "rule:overall:any-concerns"
        else:
            expected = JudgmentLevel.LOW
            expected_rule = "rule:overall:all-low"
        assert tuple(result.domain_judgments.values()) == combination
        assert result.overall_judgment is expected
        assert result.matched_rule_ids[-1] == expected_rule
