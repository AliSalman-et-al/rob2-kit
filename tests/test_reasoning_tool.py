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
    _read_required_main_reports,
    _result,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import DomainAnswer


def test_proposal_reasoning_receipt_is_required_and_consumed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    reasoned = _call(
        workspace,
        "validate_proposal",
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
        }
    ]


def test_proposal_reasoning_reports_cross_trial_evidence_handle(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    second = workspace / "input" / "second"
    second.mkdir(parents=True)
    (second / "main.txt").write_text(
        (workspace / "input" / "trial" / "main.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    primary_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    foreign_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "second"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    primary = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": primary_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    foreign = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "second",
            "source_id": foreign_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    request = _proposal_reasoning_request(workspace, primary, evidence_basis=[foreign["handle"]])

    repair = _call(workspace, "validate_proposal", request)

    assert repair["outcome"] == "repair"
    assert repair["repairs"] == [
        {
            "path": "/assessments/0/evidence_basis/0",
            "code": "cross_trial_evidence",
            "detail": "Reasoning Evidence must resolve to selected material from this Trial.",
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


def test_domain_submission_commits_complete_draft_in_one_public_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)
    draft = _reasoning_draft_for_evidence(revision, evidence)
    calls: list[str] = []
    call_tool = Client.call_tool

    async def tracked_call_tool(
        self: Client,
        name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        calls.append(name)
        return await call_tool(self, name, arguments, **kwargs)

    monkeypatch.setattr(Client, "call_tool", tracked_call_tool)
    saved = _call(workspace, "save_domain_judgment", draft)

    assert calls == ["save_domain_judgment"]
    assert saved["outcome"] == "success", saved
    assert saved["head"]["state_revision"] == before["revision"] + 1
    stored = _state(workspace)["domain_records"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]
    assert stored["identity"] == saved["data"]["checkpoint"]["identity"]
    assert stored["answers"][0]["justification"] == draft["answers"][0]["justification"]
    assert stored["answers"][0]["unknowns"] == draft["answers"][0]["unknowns"]
    assert stored["answers"][0]["counterevidence"] == draft["answers"][0]["counterevidence"]
    assert not any(
        isinstance(record, dict) and record.get("kind") == "domain_reasoning"
        for record in _state(workspace).get("reasoning_records", {}).values()
    )


def test_invalid_domain_reasoning_repairs_without_canonical_mutation(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)
    draft = _reasoning_draft_for_evidence(revision, evidence)
    del draft["answers"][0]["unknowns"]

    result = _call(workspace, "save_domain_judgment", draft)

    assert result["outcome"] == "repair", result
    assert any(item["code"] == "unknowns_required" for item in result["repairs"])
    after = _state(workspace)
    assert after["revision"] == before["revision"]
    assert after.get("domain_records", {}) == before.get("domain_records", {})


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


def test_domain_submission_retry_after_restart_keeps_identity_and_history(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _reasoning_draft_for_evidence(revision, evidence)

    first = _call(workspace, "save_domain_judgment", draft)
    second = _call(workspace, "save_domain_judgment", draft)

    assert first["outcome"] == "success", first
    assert second["outcome"] == "success", second
    assert second["data"]["retry"] is True
    assert second["data"]["checkpoint"]["identity"] == first["data"]["checkpoint"]["identity"]
    assert second["head"]["state_revision"] == first["head"]["state_revision"]
    assert len(_state(workspace)["domain_history"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]) == 1


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


def test_domain_correction_uses_supersession_and_exact_retry(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first_draft = _reasoning_draft_for_evidence(revision, evidence)
    first = _call(workspace, "save_domain_judgment", first_draft)
    assert first["outcome"] == "success", first

    refreshed = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    assert refreshed["outcome"] == "success", refreshed
    corrected = _reasoning_draft_for_evidence(int(refreshed["head"]["state_revision"]), evidence)
    corrected["supersedes"] = first["data"]["checkpoint"]["identity"]
    corrected["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "The first submission omitted the source-bound uncertainty note.",
    }
    corrected["answers"][0]["unknowns"] = ["A material implementation detail is unresolved."]
    second = _call(workspace, "save_domain_judgment", corrected)
    assert second["outcome"] == "success", second

    retry = _call(workspace, "save_domain_judgment", corrected)

    assert retry["outcome"] == "success", retry
    assert retry["data"]["retry"] is True
    assert retry["data"]["checkpoint"]["identity"] == second["data"]["checkpoint"]["identity"]
    history = _state(workspace)["domain_history"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]
    assert len(history) == 2
