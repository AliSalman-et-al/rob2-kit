from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from support.proposal import _state_proposal
from support.rob2 import (
    _call,
    _prepared_evidence,
    _proposal_args,
    _proposal_assessments,
    _result,
    _workspace,
)

from rob2_kit.workflow_models import ComparativeEffectResult


def test_removed_equivalence_relation_is_rejected_at_typed_boundary(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "source_defined_equivalent"

    proposal = _proposal_args(workspace, [result])
    with pytest.raises(ToolError, match=r"invalid_proposal_arguments"):
        _call(
            workspace,
            "validate_proposal",
            {
                "results": proposal["results"],
                "assessments": _proposal_assessments(proposal["results"]),
                "expected_revision": proposal["expected_revision"],
            },
            _raw=True,
        )


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


@pytest.mark.parametrize(
    ("precision", "expected"),
    [
        (
            {"confidence_level": "95%", "lower": "0.57", "upper": "0.80"},
            "95% CI, 0.57 to 0.80",
        ),
        (
            {"type": "95% CI", "lower": "0.75", "upper": "1.36"},
            "95% CI, 0.75 to 1.36",
        ),
        (
            {"confidence_level": 95, "lower": 0.57, "upper": 0.8},
            "95% CI, 0.57 to 0.8",
        ),
    ],
)
def test_common_precision_objects_are_sanitized_to_the_public_string(
    precision: dict[str, object], expected: str
) -> None:
    result = ComparativeEffectResult.model_validate(
        {
            "form": "comparative_effect",
            "effect_measure": "hazard ratio",
            "estimate": "0.68",
            "precision": precision,
            "analysis_population": "all randomized participants",
            "endpoint": {"name": "overall survival"},
        }
    )

    assert result.precision == expected
