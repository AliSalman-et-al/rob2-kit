from typing import NotRequired, TypedDict, cast

from rob2_kit.application.domains import _comparison_cards
from rob2_kit.logic.evaluator import evaluate_domain
from rob2_kit.models import ConditionalActivation
from rob2_kit.packs import SCIENTIFIC_PACK


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


def _question(question_id: str):
    return next(question for question in SCIENTIFIC_PACK.questions if question.id == question_id)


def _guidance_text(question_ids: tuple[str, ...]) -> str:
    return " ".join(
        text
        for question_id in question_ids
        for text in (
            _question(question_id).guidance.operational.bias_construct,
            _question(question_id).guidance.operational.decision_rule,
            *_question(question_id).guidance.operational.evidence_needed,
            *_question(question_id).guidance.operational.considerations,
            *_question(question_id).guidance.operational.invalid_shortcuts,
        )
    ).lower()


def test_operational_guidance_separates_the_five_domain_premises() -> None:
    text = _guidance_text(tuple(question.id for question in SCIENTIFIC_PACK.questions))

    for distinction in (
        ("sequence generation", "concealment", "baseline imbalance"),
        ("observed", "analysis population", "follow-up", "missingness mechanism"),
        ("could depend", "likely depended"),
        ("applicable plan", "chronology", "results-driven selection", "eligible alternatives"),
        ("actual analysis population", "grouping", "exclusions", "ITT", "mITT", "as-treated"),
        (
            "assessor awareness",
            "measurement susceptibility",
            "detection opportunity",
            "likely influence",
        ),
    ):
        assert all(term.lower() in text for term in distinction), distinction


def test_question_context_keeps_official_fields_options_and_activation_operational() -> None:
    conditional = _question("sq:measurement:assessor-aware")
    assert isinstance(conditional.activation, ConditionalActivation)
    assert conditional.wording.startswith("If N/PN/NI to 4.1 and 4.2:")
    assert conditional.allowed_answers
    assert conditional.guidance.official.source_excerpt
    assert conditional.guidance.operational.answer_anchors
    assert conditional.guidance.operational.query_suggestions


def test_controlled_guidance_cases_do_not_collapse_distinct_premises() -> None:
    cases = {
        "sq:missing:data-available": (
            "randomized",
            "same population, time window, and mutually exclusive",
        ),
        "sq:missing:evidence-unbiased": (
            "plausible assumptions",
            "missingness mechanism",
        ),
        "sq:deviations:appropriate-analysis": (
            "never-treated",
            "no adverse event",
        ),
        "sq:selection:multiple-measurements": (
            "eligible alternatives",
            "no_information",
        ),
        "sq:selection:multiple-analyses": (
            "eligible analyses",
            "unresolved",
        ),
        "sq:measurement:influence-possible": (
            "assessor awareness",
            "judgement",
        ),
        "sq:measurement:influence-likely": (
            "strong beliefs",
            "likely influence",
        ),
    }
    for question_id, terms in cases.items():
        text = _guidance_text((question_id,))
        assert all(term.lower() in text for term in terms), question_id


def test_issue_420_guidance_keeps_availability_quantities_and_mechanism_distinct() -> None:
    d3 = _guidance_text(
        (
            "sq:missing:data-available",
            "sq:missing:evidence-unbiased",
            "sq:missing:true-value-dependent",
            "sq:missing:likely-dependent",
        )
    )
    for term in (
        "randomized",
        "outcome-observed",
        "analysed",
        "imputed",
        "excluded",
        "event count",
        "denominator",
        "administrative censoring",
        "treatment discontinuation",
        "last-known-alive",
        "group attribution",
        "unobserved outcome",
        "missingness mechanism",
        "no universal percentage threshold",
    ):
        assert term in d3, term

    suggestions = {
        suggestion.query
        for suggestion in _question(
            "sq:missing:data-available"
        ).guidance.operational.query_suggestions
    }
    assert {"participant flow", "CONSORT"} <= suggestions


def test_assignment_effect_does_not_misclassify_permitted_subsequent_care() -> None:
    d2 = _guidance_text(("sq:deviations:context-deviations",))
    for term in (
        "subsequent treatment",
        "after progression",
        "protocol inconsistency",
        "trial-context cause",
        "not itself a deviation",
    ):
        assert term in d2, term


def test_high_risk_inference_gates_are_explicit_in_delivered_question_cards() -> None:
    rules = {
        question_id: _question(question_id).guidance.operational.decision_rule.lower()
        for question_id in (
            "sq:deviations:context-deviations",
            "sq:missing:data-available",
            "sq:selection:multiple-analyses",
        )
    }
    assert all(
        term in rules["sq:deviations:context-deviations"]
        for term in ("inconsistent with the protocol", "trial context caused")
    )
    assert all(
        term in rules["sq:missing:data-available"]
        for term in (
            "all or nearly all",
            "materially incomplete",
            "extent remains unknown",
            "no_information",
        )
    )
    assert all(
        term in rules["sq:selection:multiple-analyses"]
        for term in (
            "multiplicity alone",
            "eligible alternatives",
            "why selection likely depended on the results",
        )
    )


def test_issue_421_guidance_keeps_measurement_influence_propositions_distinct() -> None:
    d4 = _guidance_text(
        (
            "sq:measurement:method-inappropriate",
            "sq:measurement:differential",
            "sq:measurement:assessor-aware",
            "sq:measurement:influence-possible",
            "sq:measurement:influence-likely",
        )
    )
    for term in (
        "validity",
        "detection opportunity",
        "identity",
        "awareness",
        "standardized",
        "elicitation",
        "attribution",
        "grading",
        "possible influence",
        "likely influence",
        "pathway",
        "mixed objective and subjective components",
    ):
        assert term in d4, term


def test_issue_425_guidance_matches_exact_result_and_separates_chronology() -> None:
    d5 = _guidance_text(
        (
            "sq:selection:prespecified-analysis",
            "sq:selection:multiple-measurements",
            "sq:selection:multiple-analyses",
        )
    )
    for term in (
        "comparison",
        "cohort",
        "endpoint",
        "time window",
        "population",
        "analysis",
        "effect measure",
        "original plan",
        "amended plan",
        "source-located chronology",
        "applicability",
        "current registry content",
        "unseen historical intent",
        "data cutoff",
        "investigator unblinding",
        "embedded sap",
        "platform",
        "multiple eligible analyses",
    ):
        assert term in d5, term


def test_issues_455_to_458_guidance_preserves_endpoint_specific_seams() -> None:
    d2 = _guidance_text(("sq:deviations:appropriate-analysis", "sq:deviations:substantial-impact"))
    for term in (
        "after randomization",
        "before the endpoint was measured",
        "after an outcome value was recorded",
        "not thereby missing outcome data",
        "outcome rarity",
        "prognostic relevance",
    ):
        assert term in d2, term

    d3 = _guidance_text(
        (
            "sq:missing:data-available",
            "sq:missing:true-value-dependent",
            "sq:missing:likely-dependent",
        )
    )
    for term in (
        "discontinuation is not loss to follow-up",
        "whether the outcome was observed",
        "administrative cutoff",
        "worsening",
        "likely depend",
        "no_information",
    ):
        assert term in d3, term

    d4 = _guidance_text(
        (
            "sq:measurement:differential",
            "sq:measurement:assessor-aware",
            "sq:measurement:influence-possible",
        )
    )
    for term in (
        "extra visits for toxicity monitoring",
        "complete registry",
        "lab-detected toxicity",
        "mortality-specific pathway",
        "median progression-free survival",
        "observation window",
    ):
        assert term in d4, term

    d5 = _guidance_text(
        (
            "sq:selection:prespecified-analysis",
            "sq:selection:multiple-measurements",
            "sq:selection:multiple-analyses",
        )
    )
    for term in (
        "protocol or ethics approval",
        "plan finalization",
        "amendment effective dates",
        "registry posting",
        "data cutoff",
        "database lock",
        "investigators' access",
        "separate sap file is not required",
        "multiplicity alone",
        "results-driven selection",
    ):
        assert term in d5, term


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


def test_reference_assets_repeat_the_decision_seams() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1] / "src" / "rob2_kit" / "skills" / "rob2-assess" / "references"
    references = {
        name: " ".join((root / name).read_text(encoding="utf-8").lower().split())
        for name in ("deviations.md", "missing.md", "measurement.md", "selection.md")
    }
    for term in (
        "outcome-observed",
        "event count",
        "no universal percentage threshold",
        "last-known-alive",
        "group attribution",
        "standardized instrument",
        "detection opportunity",
        "possible influence",
        "likely influence",
        "mixed objective and subjective",
        "original and amended plans",
        "source-located",
        "current registry content",
        "data cutoff",
        "embedded sap",
        "platform",
        "multiple eligible analyses",
        "excluded participants and reasons fixed",
        "does not become missing outcome data",
        "treatment discontinuation does not establish loss to follow-up",
        "mortality-specific pathway",
        "median time to disease progression",
        "database lock",
        "separately named sap file is not",
    ):
        assert any(term in text for text in references.values()), term


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
        assert "empty passage group is unopened" in card["prompt"]


def test_domain_cards_hold_d2_and_d5_paired_controls_constant() -> None:
    d2 = _comparison_cards("domain:deviations", {}, {}, [], [])[0]["paired_examples"]
    d2_by_id = {item["pair_id"]: item for item in d2}
    protocol_pair = d2_by_id["d2-protocol-status-same-trial-context"]
    protocol_left = " ".join(protocol_pair["left_facts"]).casefold()
    protocol_right = " ".join(protocol_pair["right_facts"]).casefold()
    assert "trial staff encouraged" in protocol_left and "permitted" in protocol_left
    assert "trial staff encouraged the same" in protocol_right and "prohibited" in protocol_right

    cause_pair = d2_by_id["d2-cause-same-protocol-inconsistency"]
    cause_left = " ".join(cause_pair["left_facts"]).casefold()
    cause_right = " ".join(cause_pair["right_facts"]).casefold()
    assert "protocol prohibited rescue treatment" in cause_left
    assert "protocol prohibited rescue treatment" in cause_right
    assert "ordinary care" in cause_left
    assert "trial staff directed" in cause_right

    d5 = _comparison_cards("domain:selection", {}, {}, [], [])[0]["paired_examples"]
    selection_pair = next(
        item for item in d5 if item["pair_id"] == "d5-multiplicity-versus-selection"
    )
    selection_left = " ".join(selection_pair["left_facts"]).casefold()
    selection_right = " ".join(selection_pair["right_facts"]).casefold()
    for phrase in (
        "three eligible analyses",
        "all three were conducted",
        "only the adjusted model was reported",
    ):
        assert phrase in selection_left
        assert phrase in selection_right
    assert "before unblinded results" in selection_left
    assert "after unblinding" in selection_right
    assert "because its estimate was favorable" in selection_right
