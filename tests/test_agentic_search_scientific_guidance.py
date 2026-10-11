"""Independent neutral algorithm controls and factual comparison navigation.

Complete official-source fidelity and native delivery are checked separately in
 test_official_context.py. Historical local-paraphrase checks remain in Git.
"""

from typing import NotRequired, TypedDict, cast


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
