from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from support.proposal import _state_proposal
from support.rob2 import _call, _prepared_evidence, _proposal_args, _result, _workspace


def test_target_interpretation_leaves_do_not_require_exact_source_support(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["target"]["time_point_or_window"]["description"] = "unsupported window"
    result["target"]["comparison_groups"][0]["assignment"] = "unsupported assignment"

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert saved["outcome"] == "review_required", saved
    bindings = {
        item["field"]["path"] for item in _state_proposal(workspace)["results"][0]["bindings"]
    }
    assert "/target/comparison_groups/0/assignment" not in bindings
    assert "/target/time_point_or_window/description" not in bindings


def test_assessable_relation_enum_excludes_unavailable_values(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "unavailable"
    result["relation_rationale"] = "Use unavailable Result kind instead."

    with pytest.raises(ToolError, match=r"validation error for call\[save_proposal\]"):
        _call(workspace, "save_proposal", _proposal_args(workspace, [result]))


def test_removed_equivalence_relation_is_rejected_at_typed_boundary(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "source_defined_equivalent"

    with pytest.raises(ToolError, match=r"validation error for call\[save_proposal\]"):
        _call(workspace, "save_proposal", _proposal_args(workspace, [result]))


def test_exact_relation_rationale_is_preserved(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation_rationale"] = (
        "The selected Evidence supports this exact endpoint correspondence."
    )

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert saved["outcome"] == "review_required"
    canonical = _state_proposal(workspace)["results"][0]
    assert canonical["relation_rationale"] == result["relation_rationale"]


def test_canonical_target_is_reconstructed_from_captured_outcome(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["target"]["measurement"]["method"] = "death ascertainment"

    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert repair["outcome"] == "review_required"
    canonical = _state_proposal(workspace)["results"][0]
    assert canonical["requested_outcome"] == "requested outcome"
    assert canonical["target"]["outcome_definition"] == "requested outcome"
    assert canonical["target"]["measurement"]["metric"] == "requested outcome"
    assert canonical["target"]["intended_analysis_population"] == (
        "All randomized participants in the comparison groups"
    )
    assert "baseline_subgroup" not in canonical["target"]


def test_baseline_subgroup_is_appended_to_canonical_target_population(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["target"]["baseline_subgroup"] = "participants aged 65 years or older"

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert saved["outcome"] == "review_required", saved
    canonical = _state_proposal(workspace)["results"][0]
    assert canonical["target"]["intended_analysis_population"] == (
        "All randomized participants in the comparison groups; baseline subgroup: "
        "participants aged 65 years or older"
    )
    assert "baseline_subgroup" not in canonical["target"]


def test_absent_comparative_precision_is_not_source_bound(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"] = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "estimate": "1",
        "precision": None,
        "analysis_population": "analyzed population",
        "endpoint": result["reported"]["endpoint"],
        "group_values": result["reported"]["values"],
    }

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required"
    paths = {
        binding["field"]["path"] for binding in _state_proposal(workspace)["results"][0]["bindings"]
    }
    assert "/reported/precision" not in paths


def test_complete_comparative_effect_does_not_require_group_values(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"] = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "estimate": "1",
        "precision": None,
        "analysis_population": "analyzed population",
        "endpoint": result["reported"]["endpoint"],
    }

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert saved["outcome"] == "review_required"
    assert _state_proposal(workspace)["results"][0]["reported"]["group_values"] == []


def test_endpoint_definition_can_be_omitted_when_no_coherent_definition_is_selected(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["endpoint"].pop("definition")

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert saved["outcome"] == "review_required"
    assert _state_proposal(workspace)["results"][0]["reported"]["endpoint"]["definition"] is None


@pytest.mark.parametrize("field", ("statistic", "value", "unit"))
def test_whitespace_reported_scalars_fail_at_typed_boundary(tmp_path: Path, field: str) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["values"][0][field] = "   "

    with pytest.raises(ToolError):
        _call(workspace, "save_proposal", _proposal_args(workspace, [result]))


def test_structural_group_references_and_assignments_need_no_source_mapping(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["target"]["comparison_groups"][0]["assignment"] = "unmapped assignment"

    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert repair["outcome"] == "review_required", repair
    bindings = {
        item["field"]["path"] for item in _state_proposal(workspace)["results"][0]["bindings"]
    }
    assert "/target/comparison_groups/0/id" not in bindings
    assert "/target/comparison_groups/0/assignment" not in bindings


def test_structural_category_dimensions_need_no_mapping_but_labels_do(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"] = {
        "form": "single_group_category_profile",
        "analysis_population": "randomized population",
        "endpoint": {
            "name": "requested outcome",
            "definition": "reported by event and grade",
        },
        "group_id": "a",
        "denominator_basis": "randomized participants",
        "category_axis_names": ["event", "grade"],
        "categories": [
            {
                "category_axes": ["unmapped event", "All"],
                "value": "7",
            }
        ],
    }
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert any(
        item["code"] == "category_profile_values_not_supported"
        and item["path"] == "/results/0/reported/categories"
        and "/results/0/reported/categories/0/category_axes/0='unmapped event'" in item["detail"]
        for item in repair["repairs"]
    )
    assert not any(
        item["code"] == "result_value_not_supported" and "/reported/categories/" in item["path"]
        for item in repair["repairs"]
    )
    assert not any(
        "/reported/category_axis_names/" in item["path"]
        or item["path"] == "/results/0/reported/group_id"
        for item in repair["repairs"]
    )
