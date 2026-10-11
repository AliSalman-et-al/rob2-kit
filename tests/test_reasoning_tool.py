"""Source-bound Proposal and Domain submission behavior."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _domain_submission,
    _prepared_evidence,
    _result,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import DomainAnswer


def _proposal_reasoning_request(
    workspace: Path,
    evidence: dict[str, Any],
    *,
    evidence_basis: list[str] | None = None,
    counterevidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "results": [_result(evidence)],
        "assessments": [
            {
                "trial_id": "trial",
                "evidence_basis": evidence_basis or [evidence["handle"]],
                "scope_justification": "The reported endpoint and time window match the target.",
                "population_justification": (
                    "The reported analysis population is distinguished from baseline eligibility."
                ),
                "unknowns": [],
                "counterevidence": counterevidence or [],
            }
        ],
        "expected_revision": int(_call(workspace, "get_status", {})["head"]["state_revision"]),
    }


def test_proposal_reasoning_reports_unknown_evidence_handle(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    # A plausible copied-handle typo must reach the application repair layer,
    # rather than failing as an opaque transport-level Pydantic error.
    request = _proposal_reasoning_request(workspace, evidence, evidence_basis=["eh_" + "0" * 15])

    repair = _call(workspace, "validate_proposal", request)

    assert repair["outcome"] == "repair"
    assert repair["repairs"] == [
        {
            "path": "/assessments/0/evidence_basis/0",
            "code": "unknown_evidence_handle",
            "detail": "Reasoning Evidence handle must resolve to selected material.",
            "answer_path": None,
        }
    ]


def test_proposal_reasoning_reports_unknown_counterevidence_handle(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    request = _proposal_reasoning_request(
        workspace,
        evidence,
        counterevidence=[
            {
                "evidence": "eh_" + "f" * 16,
                "implication": "This passage limits the strength of the conclusion.",
            }
        ],
    )

    repair = _call(workspace, "validate_proposal", request)

    assert repair["outcome"] == "repair"
    assert repair["repairs"] == [
        {
            "path": "/assessments/0/counterevidence/0/evidence",
            "code": "unknown_counterevidence_handle",
            "detail": "Counterevidence handle must resolve to selected material.",
            "answer_path": None,
        }
    ]


def _reasoning_draft_for_evidence(
    revision: int,
    evidence: dict[str, Any],
    *,
    domain_id: str | None = None,
    contradiction: bool = False,
) -> dict[str, Any]:
    draft = _domain_draft("trial", domain_id or SCIENTIFIC_PACK.domains[0].id, revision, evidence)
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


def test_limitation_expansion_remaps_counterevidence_from_original_bases() -> None:
    evidence = ["eh_" + digit * 16 for digit in "123"]
    payload = {
        "question_id": "sq:example",
        "answer": "probably_yes",
        "bases": [
            {"kind": "direct_support", "evidence": evidence[0]},
            {
                "kind": "limitation",
                "unresolved_premise": "One point remains unresolved.",
                "stopping_rationale": "The relevant passages were inspected.",
                "evidence": evidence[1:],
            },
            {"kind": "direct_support", "evidence": evidence[2]},
        ],
        "counterevidence": [
            {"basis_index": index, "implication": f"Basis {index} is limited."}
            for index in range(3)
        ],
    }

    parsed = DomainAnswer.model_validate(payload)

    assert [item.basis_index for item in parsed.counterevidence or ()] == [0, 1, 4]
    assert [basis.kind for basis in parsed.bases] == [
        "direct_support",
        "limitation",
        "context",
        "context",
        "direct_support",
    ]

    # This index exists only after expansion, so it must still be rejected as
    # invalid relative to the caller's three original bases.
    payload["counterevidence"][1]["basis_index"] = 3
    with pytest.raises(ValidationError, match="original answer basis"):
        DomainAnswer.model_validate(payload)

    # A persisted pre-fix record is already expanded, so leave its stored index
    # and canonical basis sequence intact instead of guessing its old target.
    historical = {
        **payload,
        "bases": [
            {
                "kind": "limitation",
                "unresolved_premise": "One point remains unresolved.",
                "stopping_rationale": "The relevant passages were inspected.",
            },
            {"kind": "context", "evidence": evidence[1]},
            {"kind": "direct_support", "evidence": evidence[2]},
        ],
        "counterevidence": [{"basis_index": 1, "implication": "Historical target."}],
    }
    historical_before = json.dumps(historical, sort_keys=True)
    restored = DomainAnswer.model_validate(historical)
    assert restored.counterevidence is not None
    assert restored.counterevidence[0].basis_index == 1
    assert json.dumps(historical, sort_keys=True) == historical_before


def test_reasoning_requires_counterevidence_for_contradiction(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)

    result = _call(
        workspace,
        "save_domain_judgment",
        _reasoning_draft_for_evidence(revision, evidence, contradiction=True),
    )

    assert result["outcome"] == "repair"
    assert any(
        item["code"] == "contradiction_counterevidence_required" for item in result["repairs"]
    )
    assert _state(workspace)["revision"] == before["revision"]


def test_stale_competing_domain_draft_cannot_overwrite_winner(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    winner = _reasoning_draft_for_evidence(revision, evidence)
    competitor = _reasoning_draft_for_evidence(revision, evidence)
    competitor["answers"][0]["justification"] = "A distinct draft races at the same revision."

    async def submit(draft: dict[str, Any]) -> dict[str, Any]:
        async with Client(mcp) as client:
            result = await client.call_tool("save_domain_judgment", _domain_submission(draft))
            return dict(result.structured_content or {})

    async def compete() -> list[dict[str, Any]]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        return list(await asyncio.gather(submit(winner), submit(competitor)))

    first, second = asyncio.run(compete())

    successes = [result for result in (first, second) if result["outcome"] == "success"]
    assert len(successes) == 1, (first, second)
    # The other call can return a condition before the winner commits.
    assert {first["outcome"], second["outcome"]} <= {
        "success",
        "conflict",
        "condition",
    }
    accepted = successes[0]
    stale_draft = competitor if first["outcome"] == "success" else winner
    stale = _call(workspace, "save_domain_judgment", stale_draft)
    assert stale["outcome"] == "conflict", stale
    state = _state(workspace)
    assert state["revision"] == accepted["head"]["state_revision"]
    assert (
        state["domain_records"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]["identity"]
        == (accepted["data"]["checkpoint"]["identity"])
    )
    assert len(state["domain_history"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]) == 1
