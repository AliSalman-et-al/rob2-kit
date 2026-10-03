from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.application.proposal import _proposal_shape_repairs
from rob2_kit.workflow_models import ProposalDraft, ResultProposal
from tests.test_result_scope_review import _allsop_result, _draft


def flat_result() -> dict:
    old = _draft(_allsop_result()).results[0].model_dump(mode="json")
    target, reported, design = old["target"], old["reported"], old["applicability"]
    return {
        "trial_id": old["trial_id"],
        "relation": old["relation"],
        "relation_rationale": old["relation_rationale"],
        "clarity": old["clarity"],
        "design": design["design"],
        "design_rationale": design["rationale"],
        "design_evidence": design["evidence"],
        "target_measurement": target["measurement"]["method"],
        "target_window": target["time_point_or_window"]["description"],
        "comparison_groups": target["comparison_groups"],
        "baseline_subgroup": None,
        "intended_effect_measure": target["intended_effect_measure"],
        "reported_outcome": reported["endpoint"]["name"],
        "reported_definition": reported["endpoint"]["definition"],
        "analysis_population": reported["analysis_population"],
        "effect_measure": reported["effect_measure"],
        "estimate": reported["estimate"],
        "precision": reported["precision"],
        "group_values": reported["group_values"],
        "evidence": old["evidence"],
    }


def test_flat_route_preserves_canonical_draft_without_tags() -> None:
    flat = flat_result()
    assert not {"kind", "form", "target", "reported"} & flat.keys()
    result = ResultProposal.model_validate(flat).to_draft()
    assert result.model_dump(mode="json") == _draft(_allsop_result()).results[0].model_dump(
        mode="json"
    )


@pytest.mark.parametrize("relation", ["supports", "quantitative"])
def test_scientific_relation_is_not_guessed(relation: str) -> None:
    flat = flat_result()
    flat["relation"] = relation
    with pytest.raises(ValidationError):
        ResultProposal.model_validate(flat)


def test_actual_invalid_attempts_still_require_explicit_scientific_choices() -> None:
    root = Path(__file__).resolve().parents[1]
    attempts = json.loads(
        (
            root / "docs/evaluation/2026-10-03-allsop-proposal-b12fe45/proposal-attempts.json"
        ).read_text()
    )
    for attempt in attempts:
        with pytest.raises(ValidationError):
            ResultProposal.model_validate(attempt["arguments"]["results"][0])


def test_uncertainty_cannot_be_laundered_into_exactness_or_rewrite_target() -> None:
    flat = flat_result()
    original = copy.deepcopy(flat)
    flat["clarity"]["time_point"] = "conflicting"
    flat["relation_rationale"] = "Target days 1–6; source model days 1–9."
    result = ResultProposal.model_validate(flat).to_draft()
    draft = ProposalDraft(results=(result,), expected_revision=0)
    assert any(
        r["code"] == "exact_result_scope_not_established"
        for r in _proposal_shape_repairs(draft, {result.trial_id: "Cannabis withdrawal severity"})
    )
    flat["relation"] = "related"
    result = ResultProposal.model_validate(flat).to_draft()
    assert result.target.time_point_or_window.description == original["target_window"]
    assert not _proposal_shape_repairs(
        ProposalDraft(results=(result,), expected_revision=0),
        {result.trial_id: "Cannabis withdrawal severity"},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"estimate": None},
        {"design_evidence": []},
        {"target_time_value": "6"},
        {"estimate": None, "effect_measure": None, "group_values": []},
    ],
)
def test_incomplete_scientific_inputs_remain_rejected(changes: dict) -> None:
    flat = flat_result()
    flat.update(changes)
    with pytest.raises(ValidationError):
        ResultProposal.model_validate(flat)


def test_public_documented_examples_match_live_flat_input() -> None:
    import re

    from rob2_kit.workflow_models import MissingResultProposal

    root = Path(__file__).resolve().parents[1]
    reference = root / "src/rob2_kit/skills/rob2-assess/references/result.md"
    for block in re.findall(r"```json\n(.*?)\n```", reference.read_text(), flags=re.S):
        request = json.loads(block)
        for result in request.get("results", []):
            model = MissingResultProposal if result["relation"] == "unavailable" else ResultProposal
            parsed = model.model_validate(result)
            assert parsed.to_draft().trial_id == result["trial_id"]
            assert "kind" not in model.model_json_schema()["properties"]


def test_flat_proposal_rejects_unsupported_estimate_without_persisting(tmp_path: Path) -> None:
    from support.rob2 import (
        _call,
        _proposal_args,
        _proposal_assessments,
        _public_result,
        _result,
        _workspace,
    )

    from tests.test_proposal_contract import _prepared_evidence

    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    internal = _result(evidence)
    internal["reported"] = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "estimate": "999",
        "analysis_population": "randomized population",
        "endpoint": {"name": "requested outcome"},
    }
    proposal = _proposal_args(workspace, [internal])
    response = _call(
        workspace,
        "validate_proposal",
        {
            "results": [_public_result(internal)],
            "assessments": _proposal_assessments([internal]),
            "expected_revision": proposal["expected_revision"],
        },
        _raw=True,
    )
    assert response["outcome"] == "repair"
    assert any("estimate" in repair["path"] for repair in response["repairs"])
    assert _call(workspace, "get_status", {})["head"]["phase"] == "proposal"
