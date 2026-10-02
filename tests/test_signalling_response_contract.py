"""Independent response sets from Cochrane 22 August 2019 Boxes 6, 8 and 11."""

import runpy

import pytest

from rob2_kit.logic import active_questions, evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK

ALL = {"yes", "probably_yes", "probably_no", "no", "no_information"}
# NA is represented by omission from the dependency-closed active path.
OFFICIAL = {
    "sq:deviations:participants-aware": ALL,
    "sq:deviations:personnel-aware": ALL,
    "sq:deviations:context-deviations": ALL,
    "sq:deviations:affected-outcome": ALL,
    "sq:deviations:balanced": ALL,
    "sq:deviations:appropriate-analysis": ALL,
    "sq:deviations:substantial-impact": ALL,
    "sq:missing:data-available": ALL,
    "sq:missing:evidence-unbiased": ALL - {"no_information"},
    "sq:missing:true-value-dependent": ALL,
    "sq:missing:likely-dependent": ALL,
    "sq:selection:prespecified-analysis": ALL,
    "sq:selection:multiple-measurements": ALL,
    "sq:selection:multiple-analyses": ALL,
}


@pytest.mark.parametrize("question_id, options", OFFICIAL.items())
def test_official_active_response_sets(question_id: str, options: set[str]) -> None:
    question = next(q for q in SCIENTIFIC_PACK.questions if q.id == question_id)
    assert {answer.value for answer in question.allowed_answers} == options


@pytest.mark.parametrize("answer", ["yes", "probably_yes", "probably_no", "no", "no_information"])
def test_d32_response_boundary_matches_export_verifier(answer: str) -> None:
    answers = {
        "sq:missing:data-available": "no_information",
        "sq:missing:evidence-unbiased": answer,
    }
    if answer in {"no", "probably_no"}:
        answers.update(
            {
                "sq:missing:true-value-dependent": "no_information",
                "sq:missing:likely-dependent": "no_information",
            }
        )
    standalone = runpy.run_path("scripts/verify_bundle.py")["_domain_question_sets"]
    if answer == "no_information":
        with pytest.raises(ValueError):
            evaluate_domain("domain:missing", answers)
        with pytest.raises(ValueError):
            standalone("domain:missing", answers)
    else:
        evaluate_domain("domain:missing", answers)
        active, _ = standalone("domain:missing", answers)
        assert set(active) == set(answers)


@pytest.mark.parametrize(
    "answer, active", [("yes", False), ("probably_yes", False), ("no", True), ("probably_no", True)]
)
def test_no_reassurance_activates_mechanism_question(answer: str, active: bool) -> None:
    values = {"sq:missing:data-available": "no_information", "sq:missing:evidence-unbiased": answer}
    assert ("sq:missing:true-value-dependent" in active_questions(values)) is active
