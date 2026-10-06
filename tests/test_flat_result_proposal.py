from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.application.proposal import _proposal_shape_repairs
from rob2_kit.workflow_models import AssessableResultDraft, ProposalDraft, ProposalSelection
from tests.test_result_scope_review import _allsop_result, _draft


def flat_result() -> dict:
    from support.rob2 import _public_proposal_records

    old = _draft(_allsop_result()).results[0].model_dump(mode="json")
    return _public_proposal_records([old])["selections"][0]


def test_flat_route_preserves_canonical_draft_without_tags() -> None:
    flat = flat_result()
    assert not {"kind", "form", "target", "reported"} & flat.keys()
    result = ProposalSelection.model_validate(flat).to_result_draft()
    assert isinstance(result, AssessableResultDraft)
    new = result.model_dump(mode="json")
    old = _draft(_allsop_result()).results[0].model_dump(mode="json")
    assert new.pop("passage_refs") == [item["handle"] for item in old["evidence"]]
    new.pop("evidence")
    old.pop("evidence")
    old.pop("passage_refs")
    assert new == old


@pytest.mark.parametrize("relation", ["supports", "quantitative"])
def test_scientific_relation_is_not_guessed(relation: str) -> None:
    flat = flat_result()
    flat["relation"] = relation
    with pytest.raises(ValidationError):
        ProposalSelection.model_validate(flat)


def test_actual_invalid_attempts_still_require_explicit_scientific_choices() -> None:
    root = Path(__file__).resolve().parents[1]
    attempts = json.loads(
        (
            root
            / "docs/archive/evaluation/2026-10-03-allsop-proposal-b12fe45/proposal-attempts.json"
        ).read_text(encoding="utf-8")
    )
    for attempt in attempts:
        with pytest.raises(ValidationError):
            ProposalSelection.model_validate(attempt["arguments"]["results"][0])


def test_uncertainty_cannot_be_laundered_into_exactness_or_rewrite_target() -> None:
    flat = flat_result()
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
        {"estimate": None},
        {"design_evidence": []},
        {"target_time_value": "6"},
        {"estimate": None, "effect_measure": None, "group_values": []},
    ],
)
def test_incomplete_scientific_inputs_remain_rejected(changes: dict) -> None:
    flat = flat_result()
    flat["candidate"].update(changes)
    with pytest.raises(ValidationError):
        ProposalSelection.model_validate(flat)


def test_public_documented_examples_match_live_flat_input() -> None:
    import re

    root = Path(__file__).resolve().parents[1]
    reference = root / "src/rob2_kit/skills/rob2-assess/references/result.md"
    count = 0
    for block in re.findall(
        r"```json\n(.*?)\n```", reference.read_text(encoding="utf-8"), flags=re.S
    ):
        request = json.loads(block)
        for selection in request.get("selections", []):
            parsed = ProposalSelection.model_validate(selection)
            assert parsed.to_result_draft().trial_id == selection["trial_id"]
            count += 1
    assert count == 2


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
