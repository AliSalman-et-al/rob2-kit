from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest

from rob2_kit.application._state import _identity
from rob2_kit.application.proposal import _proposal_shape_repairs
from rob2_kit.application.result_scope import result_scope_review
from rob2_kit.workflow_models import ProposalDraft


def _allsop_result() -> dict:
    root = Path(__file__).resolve().parents[1]
    artifact = next(
        (root / "tests/fixtures/historical-evaluation/2026-10-03-allsop-completion-544a523").glob(
            "*.rob2.zip"
        )
    )
    with zipfile.ZipFile(artifact) as archive:
        return json.loads(archive.read("canonical.json"))["proposal"]["payload"]["results"][0]


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


def test_scope_gaps_are_explicit_without_relabeling_inherited_exactness() -> None:
    raw = _allsop_result()
    original = copy.deepcopy(raw)
    review = result_scope_review([raw])[0]
    assert review["result_identity"] == _identity(original)
    assert review["claimed_relation"] == "exact"
    assert review["target"]["window"] == original["target"]["time_point_or_window"]["description"]
    assert review["target"]["outcome"] == original["target"]["outcome_definition"]
    assert review["reported_endpoint"] == original["reported"]["endpoint"]
    assert review["reported_analysis_population"] == original["reported"]["analysis_population"]
    assert review["reported_effect_measure"] == original["reported"]["effect_measure"]
    assert review["reported_time_point_or_window"] is None
    assert review["reported_effect_of_interest"] is None
    assert review["verification"] == "requires_source_interpretation"
    assert "/reported/estimate" in review["source_bound_reported_fields"]
    assert "/reported/effect_measure" in review["source_bound_reported_fields"]
    assert not any("time" in path for path in review["source_bound_reported_fields"])
    assert raw == original


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
    requested: str, reported: str, facet: str, mismatch: str
) -> None:
    raw = _allsop_result()
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


def test_review_does_not_certify_observation_periods_as_randomized_assignments() -> None:
    raw = _allsop_result()
    raw["target"]["comparison_groups"] = [
        {"id": "on", "assignment": "Week 8 within one regimen, on exposure"},
        {"id": "off", "assignment": "Week 28 within the same regimen, off exposure"},
    ]
    raw["clarity"]["comparison_groups"] = "conflicting"
    raw["relation_rationale"] = "These periods were not the trial's randomized assignments."
    review = result_scope_review([raw])[0]
    assert review["target"]["comparison"] == [
        group["assignment"] for group in raw["target"]["comparison_groups"]
    ]
    assert "randomized assignment contrast" in review["instruction"]
    assert review["verification"] == "requires_source_interpretation"
    repairs = _proposal_shape_repairs(_draft(raw), {raw["trial_id"]: raw["requested_outcome"]})
    assert any(item["path"].endswith("/comparison_groups") for item in repairs)


@pytest.mark.parametrize("facet", ["outcome_definition", "time_point", "analysis_population"])
@pytest.mark.parametrize("status", ["unclear", "unavailable", "conflicting"])
def test_declared_scope_gap_repairs_exactness_but_keeps_nonexact_candidate(
    facet: str, status: str
) -> None:
    raw = _allsop_result()
    raw["clarity"][facet] = status
    if facet == "time_point":
        raw["relation_rationale"] = "Target days 1–6; source model days 1–9. Scope differs."
    repairs = _proposal_shape_repairs(_draft(raw), {"allsop-2014": raw["requested_outcome"]})
    assert any(
        r["code"] == "exact_result_scope_not_established" and r["path"].endswith("/" + facet)
        for r in repairs
    )
    raw["relation"] = "related"
    assert _proposal_shape_repairs(_draft(raw), {"allsop-2014": raw["requested_outcome"]}) == []


def test_compatible_alternate_wording_is_not_a_string_mismatch() -> None:
    raw = _allsop_result()
    # Keep the bound source label unchanged; only the caller's target wording varies.
    raw["target"]["outcome_definition"] = "Overall severity of cannabis withdrawal"
    raw["target"]["time_point_or_window"]["description"] = "During the nine inpatient study days"
    raw["relation_rationale"] = "Same scope under alternate source wording."
    assert _proposal_shape_repairs(_draft(raw), {"allsop-2014": raw["requested_outcome"]}) == []
    assert result_scope_review([raw])[0]["verification"] == "requires_source_interpretation"


def test_different_word_windows_are_not_certified_or_fuzzily_rejected() -> None:
    raw = _allsop_result()
    raw["relation_rationale"] = "Target days 1–6; reported model uses days 1–9."
    review = result_scope_review([raw])[0]
    assert review["relation_rationale"] == raw["relation_rationale"]
    assert review["reported_time_point_or_window"] is None
    assert review["verification"] == "requires_source_interpretation"
    # These are not two independently typed window bounds.
    assert _proposal_shape_repairs(_draft(raw), {"allsop-2014": raw["requested_outcome"]}) == []
