from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastmcp import Client
from support.rob2 import (
    _answer_value,
    _assessment_workspace,
    _call,
    _domain_draft,
    _domain_submission,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import DirectEvidenceUse, DomainAnswer


def test_public_d2_and_d3_contexts_share_result_bound_source_flow(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    saved_d1 = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved_d1["outcome"] == "success", saved_d1
    revision = int(saved_d1["head"]["state_revision"])

    draft = _domain_draft("trial", "domain:deviations", revision, evidence)
    answer = next(
        item
        for item in draft["answers"]
        if item["question_id"] == "sq:deviations:context-deviations"
    )
    row = {
        "arm": "active",
        "population": "all randomized participants",
        "unit": "participants",
        "time_point": "end of follow-up",
        "randomized": 100,
        "observed": 92,
        "basis": [evidence["handle"]],
    }
    second_arm_row = {
        **row,
        "arm": "control",
        "randomized": 98,
        "observed": 91,
    }
    preview = _call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:deviations",
            "missing_data": [row, second_arm_row],
        },
    )
    assert preview["outcome"] == "success", preview
    preview_flow = preview["data"]["comparison_cards"][0]["participant_flow"]
    assert {item["scope"]["arm"] for item in preview_flow} == {"active", "control"}
    assert all(item["result_identity"] for item in preview_flow)
    assert all(item["passages"] for item in preview_flow)

    answer["missing_data"] = [{**row, "result_identity": "sha256:" + "f" * 64}]
    rejected = _call(workspace, "save_domain_judgment", draft)
    assert rejected["outcome"] == "repair", rejected
    assert any(repair["code"] == "missing_data_result_mismatch" for repair in rejected["repairs"])
    assert rejected["head"]["state_revision"] == revision

    answer["missing_data"] = [row, second_arm_row]
    saved_d2 = _call(workspace, "save_domain_judgment", draft)
    assert saved_d2["outcome"] == "success", saved_d2
    revision = int(saved_d2["head"]["state_revision"])

    state = _state(workspace)
    expected_identity = state["domain_records"]["trial:domain:deviations"]["result_identity"]
    saved_row = state["domain_records"]["trial:domain:deviations"]["answers"]
    saved_row = next(
        item["missing_data"]["rows"][0]
        for item in saved_row
        if item["question_id"] == "sq:deviations:context-deviations"
    )
    assert saved_row["result_identity"] == expected_identity

    for domain_id in ("domain:deviations", "domain:missing"):
        context = _call(
            workspace,
            "get_domain_context",
            {"trial_id": "trial", "domain_id": domain_id},
        )
        assert context["outcome"] == "success", context.get("condition", context)
        card = context["data"]["comparison_cards"][0]
        assert card["result_identity"] == expected_identity
        rows = card["participant_flow"]
        randomized = [item for item in rows if item["kind"] == "randomized"]
        unknown_stage = [item for item in rows if item["kind"] == "analyzed"]
        assert {item["value"] for item in randomized} == {98, 100}
        assert all(item["result_identity"] == expected_identity for item in randomized)
        assert {item["scope"]["arm"] for item in randomized} == {"active", "control"}
        assert all(item["passages"] for item in randomized)
        assert {item["scope"]["arm"] for item in unknown_stage} == {"active", "control"}
        assert all(item["value"] is None for item in unknown_stage)
        assert all(item["status"] == "unknown" for item in unknown_stage)
        assert all(item["passages"] for item in unknown_stage)
        if domain_id == "domain:missing":
            slots = {item["name"]: item for item in card["slots"]}
            assert slots["randomized"]["status"] == "supported"
            assert slots["observed"]["status"] == "supported"
            assert slots["randomized"]["passages"]
            assert slots["observed"]["passages"]
            assert card["missing_data"]["conflicts"] == []
            assert len(card["missing_data"]["rows"]) == 2


def _call_raw(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            reasoning = {
                **arguments,
                "answers": [
                    {
                        **answer,
                        "justification": "The cited bases support the selected option.",
                        "unknowns": [],
                        "counterevidence": [],
                    }
                    for answer in arguments["answers"]
                ],
            }
            result = await client.call_tool(
                "save_domain_judgment", _domain_submission(reasoning), raise_on_error=False
            )
            return dict(result.structured_content or {})

    return asyncio.run(invoke())


def _assert_repairs(receipt: dict[str, Any]) -> None:
    assert receipt["outcome"] == "repair"
    assert all(
        set(item) == {"path", "code", "detail", "answer_path"} for item in receipt["repairs"]
    )


def test_nested_limitation_evidence_is_preserved_as_context() -> None:
    parsed = DomainAnswer.model_validate(
        {
            "question_id": "sq:randomization:sequence",
            "answer": "probably_no",
            "bases": [
                {
                    "kind": "limitation",
                    "unresolved_premise": "The report does not resolve the sequence method.",
                    "stopping_rationale": "The bounded read did not establish the method.",
                    "evidence": "eh_0123456789abcdef",
                }
            ],
        }
    )

    assert [basis.kind for basis in parsed.bases] == ["limitation", "context"]
    context_basis = parsed.bases[1]
    assert isinstance(context_basis, DirectEvidenceUse)
    assert context_basis.evidence == "eh_0123456789abcdef"


def test_answer_scope_repairs_are_atomic_and_valid_replay_is_idempotent(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for prior_domain in ("domain:randomization", "domain:deviations"):
        prior = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", prior_domain, revision, evidence),
        )
        assert prior["outcome"] == "success", prior
        revision = int(prior["head"]["state_revision"])
    domain_id = "domain:missing"
    draft = _domain_draft("trial", domain_id, revision, evidence)

    invalid = {**draft, "answers": [dict(item) for item in draft["answers"]]}
    invalid_answer = next(
        item for item in invalid["answers"] if item["question_id"] == "sq:missing:evidence-unbiased"
    )
    invalid_answer["answer"] = "no_information"
    repaired = _call(workspace, "save_domain_judgment", invalid)
    assert repaired["outcome"] == "repair"
    assert any(item["code"] == "invalid_answer" for item in repaired["repairs"])
    assert _state(workspace)["revision"] == revision

    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    retry = _call(workspace, "save_domain_judgment", draft)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True


def test_missing_data_is_typed_and_only_allowed_for_domain_3_1() -> None:
    row = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 100,
        "observed": 95,
    }
    parsed = DomainAnswer.model_validate(
        {
            "question_id": "sq:missing:data-available",
            "answer": _answer_value("sq:missing:data-available", "probably_no"),
            "bases": [{"kind": "context", "evidence": "eh_0123456789abcdef"}],
            "missing_data": [row],
        }
    )
    assert parsed.missing_data is not None
    assert parsed.missing_data[0].basis == ()
    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        DomainAnswer.model_validate(
            {
                "question_id": "sq:missing:data-available",
                "answer": _answer_value("sq:missing:data-available", "probably_no"),
                "bases": [{"kind": "context", "evidence": "eh_0123456789abcdef"}],
                "missing_data": [row | {"basis": ["copied quote"]}],
            }
        )
    with pytest.raises(ValueError, match="only valid for Domain 2.3, Domain 2.6, or Domain 3.1"):
        DomainAnswer.model_validate(
            {
                "question_id": "sq:missing:evidence-unbiased",
                "answer": _answer_value("sq:missing:evidence-unbiased", "no"),
                "bases": [{"kind": "context", "evidence": "eh_0123456789abcdef"}],
                "missing_data": [row],
            }
        )


def test_replayed_proposal_search_becomes_assessment_discovery_after_approval(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "assessment-only.txt").write_text(
        "assessment-only discovery passage\n", encoding="utf-8"
    )
    proposal_evidence = _prepared_evidence(workspace)
    assessment_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "assessment-only.txt"
    )
    first = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": assessment_source["id"],
            "query": "assessment-only discovery",
            "mode": "any",
        },
    )["data"]
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)

    second = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": assessment_source["id"],
            "query": "assessment-only discovery",
            "mode": "any",
        },
    )["data"]

    assert second["session_id"] == first["session_id"]
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        phase = connection.execute(
            "SELECT phase FROM search_evidence_provenance WHERE session_identity=? AND rank=?",
            (second["session_id"], second["hits"][0]["rank"]),
        ).fetchone()
    assert phase == ("assessment",)
    context = _call(
        workspace,
        "get_domain_context",
        {"domain_id": "domain:randomization", "include_candidates": True},
    )["data"]
    assert any(
        item.get("inclusion_reason") == "trial_discovery"
        and item["handle"] == second["hits"][0]["passage_ref"]
        for item in context["evidence"]
    )


def test_saved_contradiction_is_projected_in_contradiction_group(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    result_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(result_evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:randomization", revision, result_evidence)
    for answer in draft["answers"]:
        answer["bases"][0]["kind"] = "contradiction"
        answer["counterevidence"] = [
            {
                "basis_index": 0,
                "implication": "The cited contradiction weakens the selected conclusion.",
            }
        ]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved

    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )["data"]
    group = next(
        item
        for item in context["evidence_workspace"]["groups"]
        if item["inclusion_reason"] == "contradiction"
    )
    assert group["evidence_handles"] == [result_evidence["handle"]]
    result_group = next(
        item
        for item in context["evidence_workspace"]["groups"]
        if item["inclusion_reason"] == "result"
    )
    assert result_group["evidence_handles"] == [result_evidence["handle"]]


def test_domain_context_reports_unavailable_search_session_after_cache_loss(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    for index in range(70):
        page = document.new_page()
        page.insert_text((72, 72), f"lost candidate {index}")
    (workspace / "input" / "trial" / "lost.pdf").write_bytes(document.tobytes())
    document.close()
    (workspace / "input" / "trial" / "sources.toml").write_text(
        'roles = { "main.txt" = "main_article", "lost.pdf" = "supplement" }\n',
        encoding="utf-8",
    )
    proposal_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "lost.pdf"
    )
    search = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "query": "lost candidate",
            "mode": "all",
            "limit": 1,
            "purpose_domain_id": "domain:randomization",
        },
    )["data"]
    derivative = workspace / ".rob2-kit" / "derivative.sqlite3"
    with sqlite3.connect(derivative) as connection:
        connection.execute(
            "UPDATE search_domain_associations SET trial_id=NULL WHERE session_identity=?",
            (search["session_id"],),
        )
    _call(workspace, "get_domain_context", {"include_candidates": True})
    with sqlite3.connect(derivative) as connection:
        owner = connection.execute(
            "SELECT DISTINCT trial_id FROM search_domain_associations WHERE session_identity=?",
            (search["session_id"],),
        ).fetchone()
        assert owner == ("trial",)
        connection.execute("DELETE FROM search_sessions WHERE identity=?", (search["session_id"],))

    evidence_workspace = _call(workspace, "get_domain_context", {"include_candidates": True})[
        "data"
    ]["evidence_workspace"]
    assert evidence_workspace["continuation"] is None
    assert evidence_workspace["continuations"] == [
        {
            "operation": "unavailable",
            "trial_id": "trial",
            "search_session": search["session_id"],
            "reason": "derivative_search_session_unavailable",
        }
    ]
    assert evidence_workspace["omitted_by_category"]["active_domain_candidate"] == 69


def test_domain_rejects_unknown_answer_question(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision)
    draft["answers"][0]["bases"][0]["search_receipt"] = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
    draft["answers"][0]["question_id"] = "sq:randomization:not-active"
    receipt = _call_raw(workspace, draft)
    _assert_repairs(receipt)
    codes = {item["code"] for item in receipt["repairs"]}
    assert "invalid_answer_question" in codes
    assert "answers_must_match_active_questions" in codes


def test_copied_search_receipt_typo_gets_scoped_repair(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence=evidence)
    draft["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "unresolved_premise": "The sequence method remains unresolved.",
            "stopping_rationale": "The bounded search did not resolve the premise.",
            "search_receipt": "sr_" + "0" * 17,
        }
    ]

    repaired = _call_raw(workspace, draft)

    _assert_repairs(repaired)
    repair = next(item for item in repaired["repairs"] if item["path"].endswith("search_receipt"))
    assert repair["code"] == "invalid_search_receipt"
    assert "exact search_receipt handle" in repair["detail"]


def test_domain_rejects_truncated_search_as_absence_basis(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    pdf = pymupdf.open()
    for _ in range(2):
        page = pdf.new_page()
        page.insert_text((72, 72), "rare absence candidate")
    (workspace / "input" / "trial" / "repeated.pdf").write_bytes(pdf.tobytes())
    pdf.close()

    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    search = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "rare absence candidate", "mode": "any", "limit": 1},
    )
    assert search["data"]["truncated"] is True
    draft = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt=search["data"]["search_receipt"]
    )
    draft["answers"][0]["bases"] = [
        {"kind": "absence", "search_receipt": search["data"]["search_receipt"]}
    ]
    repaired = _call_raw(workspace, draft)
    _assert_repairs(repaired)
    repair = next(item for item in repaired["repairs"] if item["path"].endswith("search_receipt"))
    assert repair["code"] == "invalid_search_receipt"
    assert "question 'sq:randomization:sequence'" in repair["detail"]
    assert "exact search_receipt handle" in repair["detail"]
    assert "truncated" in repair["detail"]

    limitation = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt=search["data"]["search_receipt"]
    )
    limitation["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "unresolved_premise": "The report does not resolve this premise.",
            "stopping_rationale": (
                "The bounded search was stopped because the available material remains "
                "inconclusive."
            ),
            "search_receipt": search["data"]["search_receipt"],
        }
    ]
    accepted = _call(workspace, "save_domain_judgment", limitation)
    assert accepted["outcome"] == "success", accepted
