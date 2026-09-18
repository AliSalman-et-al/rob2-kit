from rob2_kit.application.domains import _comparison_cards
from rob2_kit.models import ConditionalActivation
from rob2_kit.packs import SCIENTIFIC_PACK


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
