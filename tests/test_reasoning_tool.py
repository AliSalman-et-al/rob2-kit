"""Mandatory source-bound reasoning receipt behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _result,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.packs import SCIENTIFIC_PACK


def test_proposal_reasoning_receipt_is_required_and_consumed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    reasoned = _call(
        workspace,
        "reason_proposal",
        {
            "results": [_result(evidence)],
            "assessments": [
                {
                    "trial_id": "trial",
                    "evidence_basis": [evidence["handle"]],
                    "scope_justification": (
                        "The reported endpoint and time window match the target."
                    ),
                    "population_justification": (
                        "The reported analysis population is distinguished from baseline "
                        "eligibility."
                    ),
                    "unknowns": [],
                    "counterevidence": [],
                }
            ],
            "expected_revision": revision,
        },
    )
    assert reasoned["outcome"] == "success", reasoned
    saved = _call(workspace, "save_proposal", reasoned["data"]["next_action"])
    assert saved["outcome"] == "review_required", saved


def _reasoning_draft_for_evidence(
    revision: int, evidence: dict[str, Any], *, contradiction: bool = False
) -> dict[str, Any]:
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    for index, answer in enumerate(draft["answers"]):
        answer["justification"] = (
            "The cited basis supports this selected option for the approved Result."
        )
        answer["unknowns"] = (
            ["The report does not describe a secondary implementation detail."]
            if index == 0
            else []
        )
        answer["counterevidence"] = (
            [
                {
                    "basis_index": 0,
                    "implication": "This passage limits the strength of the conclusion.",
                }
            ]
            if index == 0 and not contradiction
            else []
        )
    if contradiction:
        draft["answers"][0]["bases"][0]["kind"] = "contradiction"
    return draft


def test_reasoning_binds_exact_draft_and_preserves_explanations(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)
    draft = _reasoning_draft_for_evidence(revision, evidence)

    reasoned = _call(workspace, "reason_domain_assessment", draft)

    assert reasoned["outcome"] == "success", reasoned
    assert reasoned["data"]["validation_scope"] == "structure_and_references_only"
    assert reasoned["data"]["next_action"]["reasoning_id"] == reasoned["data"]["reasoning_id"]
    assert _state(workspace).get("domain_records", {}) == before.get("domain_records", {})
    assert "reasoning_opt_in" not in _state(workspace)

    save = _call(workspace, "save_domain_judgment", reasoned["data"]["next_action"])

    assert save["outcome"] == "success", save
    stored = _state(workspace)["domain_records"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]
    assert stored["answers"][0]["unknowns"]
    assert stored["answers"][0]["counterevidence"][0]["basis_index"] == 0


def test_batch_requires_reasoning_id_for_save(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    reasoned = _call(
        workspace,
        "reason_domain_assessment",
        _reasoning_draft_for_evidence(revision, evidence),
    )
    current_revision = reasoned["head"]["state_revision"]
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, current_revision, evidence)

    with pytest.raises(ToolError, match="reasoning_id"):
        _call(workspace, "save_domain_judgment", draft, _raw=True)


def test_reasoning_requires_counterevidence_for_contradiction(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)

    result = _call(
        workspace,
        "reason_domain_assessment",
        _reasoning_draft_for_evidence(revision, evidence, contradiction=True),
    )

    assert result["outcome"] == "repair"
    assert any(
        item["code"] == "contradiction_counterevidence_required" for item in result["repairs"]
    )
    assert _state(workspace)["revision"] == before["revision"]


def test_reasoning_retry_reuses_record(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _reasoning_draft_for_evidence(revision, evidence)

    first = _call(workspace, "reason_domain_assessment", draft)
    second = _call(workspace, "reason_domain_assessment", draft)

    assert first["outcome"] == "success"
    assert second["outcome"] == "success"
    assert second["data"]["reasoning_id"] == first["data"]["reasoning_id"]
    assert second["head"]["state_revision"] == first["head"]["state_revision"]
