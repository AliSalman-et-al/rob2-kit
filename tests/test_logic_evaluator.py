from itertools import product
from typing import Any, cast

import pytest
from oracle.rob2_parallel import QIDS, cases, judgment
from pydantic import ValidationError

from rob2_kit.logic import active_questions, evaluate_domain, evaluate_overall
from rob2_kit.models import Answer, ConditionalActivation, Judgment, sha256
from rob2_kit.packs import (
    MAINTAINER_POLICY_PACK,
    SCIENTIFIC_PACK,
    load_policy_pack,
    load_scientific_pack,
)


def test_pack_ids_wording_provenance_and_hashes():
    assert len(SCIENTIFIC_PACK.questions) == 22
    # Independently reviewed against the cited 22 August 2019 Boxes 4, 6, 8, 10 and 11.
    assert sha256(
        tuple((question.id, question.wording) for question in SCIENTIFIC_PACK.questions)
    ) == ("sha256:96ff2d1a649d6b40f40fe7fa73c3127c5eb1725e8392b8728f9d25f951338425")
    assert SCIENTIFIC_PACK.questions[16].wording.startswith("If N/PN/NI to 4.1 and 4.2")
    assert SCIENTIFIC_PACK.content_hash == (
        "sha256:bb4f07a86662df2decaad739013e1178a6767aceb9b63e6b438c7f98074d5d84"
    )
    assert "not attributed to Cochrane" in MAINTAINER_POLICY_PACK.attribution
    assert MAINTAINER_POLICY_PACK.id != SCIENTIFIC_PACK.id
    assert load_scientific_pack(SCIENTIFIC_PACK.model_dump(mode="json")) == SCIENTIFIC_PACK
    assert (
        load_policy_pack(MAINTAINER_POLICY_PACK.model_dump(mode="json")) == MAINTAINER_POLICY_PACK
    )
    with pytest.raises(ValueError, match="hash"):
        load_scientific_pack({**SCIENTIFIC_PACK.model_dump(mode="json"), "version": "tampered"})
    with pytest.raises(ValueError, match="hash"):
        load_policy_pack({**MAINTAINER_POLICY_PACK.model_dump(mode="json"), "version": "tampered"})


def test_policy_lexical_seeds_are_deeply_immutable_and_deterministic():
    assert MAINTAINER_POLICY_PACK.seeds_for("randomization") == ("random", "allocation", "conceal")
    assert MAINTAINER_POLICY_PACK.source_priority == (
        "main_article",
        "registry",
        "supplement",
        "sap",
        "protocol",
        "other",
    )
    with pytest.raises(TypeError):
        cast(Any, MAINTAINER_POLICY_PACK.lexical_seeds)[0] = MAINTAINER_POLICY_PACK.lexical_seeds[0]
    with pytest.raises(ValidationError):
        cast(Any, MAINTAINER_POLICY_PACK.lexical_seeds[0]).terms += ("changed",)


@pytest.mark.parametrize("domain", tuple(QIDS))
def test_all_admissible_domain_paths_against_independent_oracle(domain):
    paths = list(cases(domain))
    assert paths
    for answers in paths:
        actual = evaluate_domain(domain, answers)
        assert actual.judgment.value == judgment(domain, answers)
        assert actual.trace


def test_all_overall_combinations_against_independent_oracle():
    domain_ids = tuple(QIDS)
    for values in product(("low", "some_concerns", "high"), repeat=5):
        judgments = dict(zip(domain_ids, values, strict=True))
        if "high" in values or values.count("some_concerns") >= 2:
            expected = "high"
        elif "some_concerns" in values:
            expected = "some_concerns"
        else:
            expected = "low"
        assert evaluate_overall(judgments).judgment.value == expected


def test_domain_driver_questions_follow_pack_order_and_are_empty_for_low():
    high = evaluate_domain(
        "domain:randomization",
        {
            "sq:randomization:sequence": "no",
            "sq:randomization:concealment": "yes",
            "sq:randomization:baseline-imbalance": "no",
        },
    )
    assert high.driver_questions == ("sq:randomization:sequence",)

    low = evaluate_domain(
        "domain:randomization",
        {
            "sq:randomization:sequence": "yes",
            "sq:randomization:concealment": "yes",
            "sq:randomization:baseline-imbalance": "no",
        },
    )
    assert low.driver_questions == ()


def test_overall_driver_domains_follow_pack_order_for_each_rule():
    assert evaluate_overall({domain_id: "low" for domain_id in QIDS}).driver_domains == ()
    assert evaluate_overall(
        {
            "domain:randomization": "some_concerns",
            "domain:deviations": "low",
            "domain:missing": "high",
            "domain:measurement": "some_concerns",
            "domain:selection": "low",
        }
    ).driver_domains == ("domain:missing",)
    assert evaluate_overall(
        {
            "domain:randomization": "some_concerns",
            "domain:deviations": "low",
            "domain:missing": "low",
            "domain:measurement": "some_concerns",
            "domain:selection": "low",
        }
    ).driver_domains == ("domain:randomization", "domain:measurement")


def test_overall_drivers_follow_each_aggregation_category_in_pack_order():
    domain_ids = tuple(QIDS)
    low = {domain_id: Judgment.LOW for domain_id in domain_ids}
    assert evaluate_overall(low).driver_domains == ()

    one_concern = {**low, domain_ids[3]: Judgment.SOME_CONCERNS}
    assert evaluate_overall(one_concern).driver_domains == (domain_ids[3],)

    multiple_concerns = {
        **low,
        domain_ids[4]: Judgment.SOME_CONCERNS,
        domain_ids[1]: Judgment.SOME_CONCERNS,
    }
    assert evaluate_overall(multiple_concerns).driver_domains == (domain_ids[1], domain_ids[4])

    high = {
        **low,
        domain_ids[4]: Judgment.HIGH,
        domain_ids[0]: Judgment.HIGH,
        domain_ids[2]: Judgment.SOME_CONCERNS,
    }
    result = evaluate_overall(high)
    assert result.judgment is Judgment.HIGH
    assert result.trace == ("overall.any_high",)
    assert result.driver_domains == (domain_ids[0], domain_ids[4])


def test_domain_drivers_are_exact_and_pack_ordered_without_changing_rule_trace():
    randomization = evaluate_domain(
        "domain:randomization",
        {
            "sq:randomization:sequence": "no",
            "sq:randomization:concealment": "no_information",
            "sq:randomization:baseline-imbalance": "yes",
        },
    )
    assert randomization.judgment is Judgment.HIGH
    assert randomization.trace == ("randomization.unknown_concealment_and_imbalance",)
    assert randomization.driver_questions == (
        "sq:randomization:concealment",
        "sq:randomization:baseline-imbalance",
    )

    measurement = evaluate_domain(
        "domain:measurement",
        {
            "sq:measurement:method-inappropriate": "no",
            "sq:measurement:differential": "no_information",
            "sq:measurement:assessor-aware": "yes",
            "sq:measurement:influence-possible": "no",
        },
    )
    assert measurement.judgment is Judgment.SOME_CONCERNS
    assert measurement.trace == ("measurement.some_concerns",)
    assert measurement.driver_questions == ("sq:measurement:differential",)

    low = evaluate_domain(
        "domain:selection",
        {
            "sq:selection:prespecified-analysis": "yes",
            "sq:selection:multiple-measurements": "no",
            "sq:selection:multiple-analyses": "no",
        },
    )
    assert low.judgment is Judgment.LOW
    assert low.trace == ("selection.low",)
    assert low.driver_questions == ()


def test_corrected_domain_four_no_information_paths():
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "yes",
                "sq:measurement:differential": "probably_no",
            },
        ).judgment
        is Judgment.HIGH
    )
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "no_information",
                "sq:measurement:differential": "no",
                "sq:measurement:assessor-aware": "no",
            },
        ).judgment
        is Judgment.LOW
    )
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "no",
                "sq:measurement:differential": "no",
                "sq:measurement:assessor-aware": "no_information",
                "sq:measurement:influence-possible": "no",
            },
        ).judgment
        is Judgment.LOW
    )


def test_rejects_unknown_inactive_and_missing_answers():
    with pytest.raises(ValueError, match="unknown signalling answer"):
        evaluate_domain("domain:randomization", {"sq:randomization:sequence": "wat"})
    with pytest.raises(ValueError, match="missing"):
        evaluate_domain("domain:measurement", {"sq:measurement:method-inappropriate": "no"})
    with pytest.raises(ValueError, match="unknown signalling question"):
        evaluate_domain(
            "domain:randomization",
            {
                "sq:randomization:sequence": "yes",
                "sq:randomization:concealment": "yes",
                "sq:randomization:baseline-imbalance": "no",
                "sq:not-real": "yes",
            },
        )


@pytest.mark.parametrize(
    ("answers", "question_id", "expected"),
    (
        ({"sq:deviations:participants-aware": "yes"}, "sq:deviations:context-deviations", True),
        (
            {
                "sq:deviations:participants-aware": "no",
                "sq:deviations:personnel-aware": "no",
            },
            "sq:deviations:context-deviations",
            False,
        ),
        (
            {
                "sq:measurement:method-inappropriate": "no",
                "sq:measurement:differential": "probably_no",
            },
            "sq:measurement:assessor-aware",
            True,
        ),
        (
            {
                "sq:measurement:method-inappropriate": "yes",
                "sq:measurement:differential": "no",
            },
            "sq:measurement:assessor-aware",
            False,
        ),
    ),
)
def test_typed_activation_rules_preserve_any_and_all_behavior(answers, question_id, expected):
    assert (question_id in active_questions(answers)) is expected


def test_every_conditional_activation_matches_its_typed_predicates():
    by_id = {question.id: question for question in SCIENTIFIC_PACK.questions}

    def activate(question_id: str, answers: dict[str, str]) -> None:
        question = by_id[question_id]
        if question.activation.kind == "always":
            return
        for predicate in question.activation.predicates:
            activate(predicate.question_id, answers)
            answers[predicate.question_id] = predicate.accepted_answers[0].value

    conditional_questions = [
        question for question in SCIENTIFIC_PACK.questions if question.activation.kind == "rule"
    ]
    assert len(conditional_questions) == 10
    for question in conditional_questions:
        activation = question.activation
        assert isinstance(activation, ConditionalActivation)
        answers: dict[str, str] = {}
        activate(question.id, answers)
        assert question.id in active_questions(answers)

        misses = dict(answers)
        misses.update(
            {
                predicate.question_id: next(
                    answer.value for answer in Answer if answer not in predicate.accepted_answers
                )
                for predicate in activation.predicates
            }
        )
        assert (question.id in active_questions(misses)) is False


def test_allowed_answer_restrictions_still_apply_to_active_questions():
    with pytest.raises(ValueError):
        evaluate_domain(
            "domain:missing",
            {
                "sq:missing:data-available": "no",
                "sq:missing:evidence-unbiased": "no_information",
            },
        )


def test_assignment_analysis_quality_is_separate_from_potential_impact():
    mitt = {
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:appropriate-analysis": "yes",
    }
    assert evaluate_domain("domain:deviations", mitt).judgment is Judgment.LOW

    excluded = {
        **mitt,
        "sq:deviations:appropriate-analysis": "no",
        "sq:deviations:substantial-impact": "no",
    }
    assert evaluate_domain("domain:deviations", excluded).judgment is Judgment.SOME_CONCERNS
    excluded["sq:deviations:substantial-impact"] = "yes"
    assert evaluate_domain("domain:deviations", excluded).judgment is Judgment.HIGH


def test_measurement_evaluation_keeps_awareness_possible_and_likely_influence_distinct():
    possible_not_likely = {
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "yes",
        "sq:measurement:influence-possible": "yes",
        "sq:measurement:influence-likely": "no",
    }
    assert (
        evaluate_domain("domain:measurement", possible_not_likely).judgment
        is Judgment.SOME_CONCERNS
    )

    likely = {**possible_not_likely, "sq:measurement:influence-likely": "yes"}
    assert evaluate_domain("domain:measurement", likely).judgment is Judgment.HIGH

    detection_difference = {
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "yes",
    }
    assert evaluate_domain("domain:measurement", detection_difference).judgment is Judgment.HIGH


def test_selection_uncertainty_is_not_observed_results_driven_selection():
    unresolved = {
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no_information",
        "sq:selection:multiple-analyses": "no",
    }
    assert evaluate_domain("domain:selection", unresolved).judgment is Judgment.SOME_CONCERNS

    selected = {**unresolved, "sq:selection:multiple-measurements": "yes"}
    assert evaluate_domain("domain:selection", selected).judgment is Judgment.HIGH
