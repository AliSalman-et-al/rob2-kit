from __future__ import annotations

import copy

import pytest
from support.rob2 import _saved_result

from rob2_kit.application.proposal import _proposal_shape_repairs
from rob2_kit.application.result_scope import result_scope_review
from rob2_kit.workflow_models import ProposalDraft


@pytest.fixture(scope="module")
def saved_result(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _saved_result(tmp_path_factory.mktemp("assessed"))


def _draft(raw: dict) -> ProposalDraft:
    result = copy.deepcopy(raw)
    result.pop("requested_outcome")
    result.pop("bindings")
    target = result["target"]
    result["target"] = {
        "measurement": {"method": target["measurement"]["method"]},
        "time_point_or_window": target["time_point_or_window"],
        "comparison_groups": target["comparison_groups"],
        "baseline_subgroup": None,
        "intended_effect_measure": target["intended_effect_measure"],
    }
    return ProposalDraft.model_validate({"results": [result], "expected_revision": 0})


@pytest.mark.parametrize(
    ("requested", "reported", "facet", "mismatch"),
    [
        (
            "Overall survival",
            "Survival or hospitalization composite",
            "outcome_definition",
            "The selected composite adds hospitalization; it is not overall survival alone.",
        ),
        (
            "Patients surviving one year",
            "Recurrence-free survival at six months",
            "time_point",
            "Both the recurrence-free construct and six-month horizon differ.",
        ),
        (
            "Patients surviving one year",
            "Overall survival hazard ratio",
            "measurement",
            "The source time-to-event analysis is not a one-year landmark probability.",
        ),
    ],
)
def test_material_matching_conflicts_remain_visible_and_cannot_claim_exactness(
    saved_result: dict, requested: str, reported: str, facet: str, mismatch: str
) -> None:
    raw = copy.deepcopy(saved_result)
    raw["requested_outcome"] = requested
    raw["target"]["outcome_definition"] = requested
    raw["target"]["measurement"]["metric"] = requested
    raw["reported"]["endpoint"] = {"name": reported, "definition": None}
    raw["clarity"][facet] = "conflicting"
    raw["relation_rationale"] = mismatch
    original = copy.deepcopy(raw)
    review = result_scope_review([raw])[0]
    assert review["target"]["outcome"] == requested
    assert review["reported_endpoint"]["name"] == reported
    assert review["relation_rationale"] == mismatch
    assert review["verification"] == "requires_source_interpretation"
    repairs = _proposal_shape_repairs(_draft(raw), {raw["trial_id"]: requested})
    assert any(item["path"].endswith("/" + facet) for item in repairs)
    assert raw == original


def test_different_word_windows_are_not_certified_or_fuzzily_rejected(saved_result: dict) -> None:
    raw = copy.deepcopy(saved_result)
    raw["relation_rationale"] = "Target days 1–6; reported model uses days 1–9."
    review = result_scope_review([raw])[0]
    assert review["relation_rationale"] == raw["relation_rationale"]
    assert review["reported_time_point_or_window"] is None
    assert review["verification"] == "requires_source_interpretation"
    # These are not two independently typed window bounds.
    assert _proposal_shape_repairs(_draft(raw), {raw["trial_id"]: raw["requested_outcome"]}) == []
