"""Independent neutral algorithm controls and factual comparison navigation.

Complete official-source fidelity and native delivery are checked separately in
 test_official_context.py. Historical local-paraphrase checks remain in Git.
"""

from typing import NotRequired, TypedDict, cast

from rob2_kit.application.domains import _comparison_cards
from rob2_kit.logic.evaluator import evaluate_domain


class _GuidanceCase(TypedDict):
    case_id: str
    domain: str
    contrast: str
    severity: str
    facts: list[str]
    expected_answer_path: dict[str, str]
    neutral: NotRequired[bool]
    result_scope: NotRequired[str]
    changed_premise: NotRequired[str]
    pair_id: NotRequired[str]


def _fixture_cases() -> list[_GuidanceCase]:
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "scientific_guidance.json").read_text(
            encoding="utf-8"
        )
    )
    return cast(list[_GuidanceCase], fixture["cases"])


def test_issue_455_to_458_paired_fixtures_change_one_premise_and_follow_the_evaluator() -> None:
    cases = _fixture_cases()
    expected_pairs = {
        "d2-exclusion-timing",
        "d3-stop-treatment-versus-followup",
        "d4-endpoint-specific-toxicity-monitoring",
        "d4-safety-observation-window",
        "d5-amendment-access-order",
        "d5-multiplicity-versus-results-based-reporting",
    }
    paired = {
        pair_id: [case for case in cases if case.get("pair_id") == pair_id]
        for pair_id in expected_pairs
    }
    assert all(len(pair) == 2 for pair in paired.values())

    for pair_id, pair in paired.items():
        left, right = pair
        assert left["neutral"] and right["neutral"]
        assert left["domain"] == right["domain"], pair_id
        if pair_id == "d4-endpoint-specific-toxicity-monitoring":
            assert left["result_scope"] != right["result_scope"]
            assert "approved endpoint" in left["changed_premise"]
        else:
            assert left["result_scope"] == right["result_scope"], pair_id
        assert left["changed_premise"] == right["changed_premise"], pair_id
        assert len(set(left["facts"]) ^ set(right["facts"])) == 2, pair_id
        for case in pair:
            outcome = evaluate_domain(case["domain"], case["expected_answer_path"])
            assert outcome.judgment.value == case["severity"], case["case_id"]


def test_neutral_fixtures_cover_requested_d3_d4_d5_contrasts() -> None:
    cases = _fixture_cases()
    assert {case["domain"] for case in cases} == {
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    }
    assert {case["severity"] for case in cases} >= {"low", "some_concerns", "high"}
    required = {
        "time_to_event",
        "adverse_event",
        "valid_reassurance",
        "possible_influence",
        "likely_influence",
        "genuine_high",
        "embedded_sap",
        "absent_plan",
        "ambiguous_chronology",
        "platform_comparison",
        "multiple_eligible_analyses",
        "analysis_exclusion_timing",
        "stopped_treatment_followup",
        "endpoint_specific_monitoring",
        "safety_observation_window",
        "plan_event_chronology",
        "multiplicity_and_result_dependence",
        "no_information_to_high_official_path",
    }
    assert required <= {case["contrast"] for case in cases}
    assert all(case["neutral"] for case in cases)
    facts_by_contrast = {
        str(case["contrast"]): " ".join(
            str(fact) for fact in cast(list[object], case["facts"])
        ).lower()
        for case in cases
    }
    for contrast, terms in {
        "time_to_event": ("discontinued", "day 90", "administrative censoring"),
        "adverse_event": ("event count", "denominator", "group attribution"),
        "valid_reassurance": ("same registry", "blinded", "no intervention-related"),
        "possible_influence": ("standardized questionnaire", "judgment", "no source evidence"),
        "likely_influence": ("objective laboratory", "extra visits", "expected benefit"),
        "embedded_sap": ("embedded sap", "comparison", "signed before"),
        "absent_plan": ("no protocol", "does not prove selective"),
        "ambiguous_chronology": ("original plan", "amended plan", "data cutoff"),
        "platform_comparison": (
            "platform master protocol",
            "one cohort",
            "not establish applicability",
        ),
        "multiple_eligible_analyses": ("adjusted", "complete-case", "multiplicity"),
    }.items():
        assert all(term in facts_by_contrast[contrast] for term in terms), contrast


def test_comparison_cards_keep_premise_specific_slots_and_question_bindings() -> None:
    expected = {
        "domain:deviations": (
            "sq:deviations:context-deviations",
            {
                "intended_intervention",
                "observed_conduct",
                "trial_context_cause",
                "protocol_consistency",
                "outcome_effect",
                "group_balance",
            },
        ),
        "domain:missing": (
            "sq:missing:data-available",
            {
                "approved_outcome",
                "randomized",
                "observed",
                "follow_up_availability",
                "censoring",
                "missingness_reason",
            },
        ),
        "domain:selection": (
            "sq:selection:prespecified-analysis",
            {"reported_result", "analysis_plan", "unblinded_access", "amendment", "correspondence"},
        ),
    }
    for domain_id, (question_id, slot_names) in expected.items():
        card = _comparison_cards(domain_id, {}, {}, [], [])[0]
        assert card["question_id"] == question_id
        assert {slot["name"] for slot in card["slots"]} == slot_names
        assert all(slot["status"] == "unknown" for slot in card["slots"])
        assert "Empty passage groups denote unopened source material" in card["prompt"]
