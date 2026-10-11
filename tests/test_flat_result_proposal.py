from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import _public_proposal_records, _saved_result

from rob2_kit.application.proposal import _proposal_shape_repairs
from rob2_kit.workflow_models import AssessableResultDraft, ProposalDraft, ProposalSelection
from tests.test_result_scope_review import _draft


@pytest.fixture(scope="module")
def saved(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _saved_result(tmp_path_factory.mktemp("assessed"))


@pytest.fixture
def flat(saved: dict) -> dict:
    old = _draft(saved).results[0].model_dump(mode="json")
    return _public_proposal_records([old])["selections"][0]


def test_uncertainty_cannot_be_laundered_into_exactness_or_rewrite_target(flat: dict) -> None:
    original = copy.deepcopy(flat)
    flat["candidate"]["clarity"]["time_point"] = "conflicting"
    flat["scope_rationale"] = "Target days 1–6; source model days 1–9."
    result = ProposalSelection.model_validate(flat).to_result_draft()
    assert isinstance(result, AssessableResultDraft)
    draft = ProposalDraft(results=(result,), expected_revision=0)
    assert any(
        r["code"] == "exact_result_scope_not_established"
        for r in _proposal_shape_repairs(draft, {result.trial_id: "Cannabis withdrawal severity"})
    )
    flat["relation"] = "related"
    result = ProposalSelection.model_validate(flat).to_result_draft()
    assert isinstance(result, AssessableResultDraft)
    assert result.target.time_point_or_window.description == original["candidate"]["target_window"]
    assert not _proposal_shape_repairs(
        ProposalDraft(results=(result,), expected_revision=0),
        {result.trial_id: "Cannabis withdrawal severity"},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"design_evidence": []},
        {"target_time_value": "6"},
        {"estimate": None, "effect_measure": None, "group_values": []},
    ],
)
def test_incomplete_scientific_inputs_remain_rejected(flat: dict, changes: dict) -> None:
    flat["candidate"].update(changes)
    with pytest.raises(ValidationError):
        ProposalSelection.model_validate(flat)


def test_flat_proposal_rejects_unsupported_estimate_without_persisting(tmp_path: Path) -> None:
    from support.rob2 import (
        _call,
        _proposal_args,
        _public_proposal_records,
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
            **_public_proposal_records([internal]),
            "expected_revision": proposal["expected_revision"],
        },
        _raw=True,
    )
    assert response["outcome"] == "repair"
    assert any("estimate" in repair["path"] for repair in response["repairs"])
    assert _call(workspace, "get_status", {})["head"]["phase"] == "proposal"
