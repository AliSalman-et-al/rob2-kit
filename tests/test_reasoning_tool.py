"""Mandatory source-bound reasoning receipt behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _read_required_main_reports,
    _result,
    _workspace,
)

from rob2_kit.application._state import _state
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


def test_reasoning_binds_exact_draft_and_preserves_explanations(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    before = _state(workspace)
    draft = _reasoning_draft_for_evidence(revision, evidence)

    reasoned = _call(workspace, "validate_domain_assessment", draft)

    assert reasoned["outcome"] == "success", reasoned
    assert reasoned["data"]["validation_scope"] == "structure_and_references_only"
    assert "reasoning_id" not in reasoned["data"]
    assert _state(workspace).get("domain_records", {}) == before.get("domain_records", {})
    assert "reasoning_opt_in" not in _state(workspace)

    save = _call(workspace, "save_domain_judgment", reasoned["data"]["next_action"])

    assert save["outcome"] == "success", save
    stored = _state(workspace)["domain_records"][f"trial:{SCIENTIFIC_PACK.domains[0].id}"]
    assert stored["answers"][0]["unknowns"]
    assert stored["answers"][0]["counterevidence"][0]["basis_index"] == 0


def test_domain_save_requires_a_validated_revision(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    result = _call(
        workspace,
        "save_domain_judgment",
        {
            "trial_id": "trial",
            "domain_id": SCIENTIFIC_PACK.domains[0].id,
            "expected_revision": revision,
        },
    )

    assert result["outcome"] == "condition"
    assert result.get("code") == "reasoning_stale" or result["condition"]["code"] == (
        "reasoning_stale"
    )


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
        "validate_domain_assessment",
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

    first = _call(workspace, "validate_domain_assessment", draft)
    second = _call(workspace, "validate_domain_assessment", draft)

    assert first["outcome"] == "success"
    assert second["outcome"] == "success"
    assert second["head"]["state_revision"] == first["head"]["state_revision"]
    assert len(_state(workspace)["reasoning_records"]) == 2


def test_validated_domain_survives_later_domain_save(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first_domain, later_domain = (domain.id for domain in SCIENTIFIC_PACK.domains[:2])
    first = _call(
        workspace,
        "validate_domain_assessment",
        _reasoning_draft_for_evidence(revision, evidence, domain_id=first_domain),
    )
    assert first["outcome"] == "success", first

    later_context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": later_domain},
    )
    assert later_context["outcome"] == "success", later_context
    later = _call(
        workspace,
        "validate_domain_assessment",
        _reasoning_draft_for_evidence(
            int(later_context["head"]["state_revision"]),
            evidence,
            domain_id=later_domain,
        ),
    )
    assert later["outcome"] == "success", later
    saved_later = _call(workspace, "save_domain_judgment", later["data"]["next_action"])
    assert saved_later["outcome"] == "success", saved_later

    saved_first = _call(workspace, "save_domain_judgment", first["data"]["next_action"])

    assert saved_first["outcome"] == "success", saved_first
    state = _state(workspace)
    assert f"trial:{first_domain}" in state["domain_records"]
    assert f"trial:{later_domain}" in state["domain_records"]


def test_validated_domain_is_stale_after_its_predecessor_changes(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _reasoning_draft_for_evidence(revision, evidence)
    first = _call(workspace, "validate_domain_assessment", draft)
    assert first["outcome"] == "success", first

    changed = _reasoning_draft_for_evidence(int(first["head"]["state_revision"]), evidence)
    question_id = changed["answers"][0]["question_id"]
    question = next(item for item in SCIENTIFIC_PACK.questions if item.id == question_id)
    current = changed["answers"][0]["answer"]
    changed["answers"][0]["answer"] = next(
        answer.value for answer in question.allowed_answers if answer.value != current
    )
    second = _call(workspace, "validate_domain_assessment", changed)
    assert second["outcome"] == "success", second
    saved = _call(workspace, "save_domain_judgment", second["data"]["next_action"])
    assert saved["outcome"] == "success", saved

    stale = _call(workspace, "save_domain_judgment", first["data"]["next_action"])

    assert stale["outcome"] == "condition", stale
    assert (
        stale.get("code") == "reasoning_stale"
        or stale.get("condition", {}).get("code") == "reasoning_stale"
    )
