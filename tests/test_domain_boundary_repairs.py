from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastmcp import Client
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application.evidence import _search_receipt
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.packs import SCIENTIFIC_PACK


def _call_raw(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool("save_domain_judgment", arguments, raise_on_error=False)
            return dict(result.structured_content or {})

    return asyncio.run(invoke())


def _assert_repairs(receipt: dict[str, Any]) -> None:
    assert receipt["outcome"] == "repair"
    assert all(set(item) == {"path", "code", "detail"} for item in receipt["repairs"])


def test_domain_public_shape_is_flat_and_closed() -> None:
    async def inspect() -> dict[str, Any]:
        async with Client(mcp) as client:
            tool = next(
                tool for tool in await client.list_tools() if tool.name == "save_domain_judgment"
            )
            return dict(tool.inputSchema)

    schema = asyncio.run(inspect())
    draft = schema
    assert "clauses" not in draft["properties"]
    assert "evidence_uses" not in draft["properties"]
    assert "limitations" not in draft["properties"]
    answer = draft["properties"]["answers"]["items"]
    assert set(answer["properties"]) == {"question_id", "answer", "bases"}
    bases = answer["properties"]["bases"]["items"]["oneOf"]
    kinds = {
        item["properties"]["kind"].get("const") or item["properties"]["kind"]["enum"][0]
        for item in bases
    }
    assert kinds == {
        "direct_support",
        "absence",
        "limitation",
    }
    assert all("question_id" not in item["properties"] for item in bases)
    direct = next(
        item
        for item in bases
        if item["properties"]["kind"].get("enum")
        == ["direct_support", "indirect_support", "contradiction", "context", "inference"]
    )
    assert set(direct["properties"]) == {"kind", "evidence"}
    absence = next(item for item in bases if item["properties"]["kind"].get("const") == "absence")
    assert absence["properties"]["search_receipt"]["pattern"] == r"^sr_[0-9a-f]{16}$"
    limitation = next(
        item for item in bases if item["properties"]["kind"].get("const") == "limitation"
    )
    assert set(limitation["properties"]) == {"kind", "text", "search_receipt"}
    assert limitation["properties"]["search_receipt"]["pattern"] == r"^sr_[0-9a-f]{16}$"


def test_domain_context_result_projection_omits_canonical_bindings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert saved["outcome"] == "review_required"
    _review(workspace)

    context = _call(workspace, "get_domain_context", {})
    data = context["data"]
    result = data["result"]
    assert "bindings" not in result
    assert set(result["evidence"][0]) == {"kind", "handle", "identity"}
    assert "alternatives" not in result
    assert "complete bounded question-specific discovery" in data["completion_rule"]
    assert any("protocol or SAP" in item for item in data["guidance"])
    assert any("does not by itself prove" in item for item in data["traps"])
    question_card = data["questions"][0]
    assert set(question_card) == {
        "id",
        "wording",
        "allowed_answers",
        "active",
        "activation",
        "official_guidance",
        "source_locator",
        "decision_rule",
        "evidence_needed",
        "answer_anchors",
        "no_information_rule",
        "invalid_shortcuts",
    }
    assert question_card["official_guidance"]
    assert question_card["source_locator"].startswith("Full guidance ")
    pack_question = next(
        item for item in SCIENTIFIC_PACK.questions if item.id == question_card["id"]
    )
    assert set(pack_question.guidance.model_dump(mode="json")) == {"official", "operational"}
    assert set(pack_question.guidance.official.model_dump(mode="json")) == {
        "version",
        "source_locator",
        "source_sha256",
        "source_excerpt",
    }
    assert set(pack_question.guidance.operational.model_dump(mode="json")) == {
        "id",
        "version",
        "attribution",
        "bias_construct",
        "decision_rule",
        "evidence_needed",
        "no_information_rule",
        "answer_anchors",
        "considerations",
        "invalid_shortcuts",
    }
    assert pack_question.guidance.official.source_excerpt == question_card["official_guidance"]
    assert pack_question.guidance.official.source_locator == question_card["source_locator"]
    assert pack_question.guidance.operational.decision_rule == question_card["decision_rule"]


def test_domain_rejects_unknown_answer_question(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision)
    draft["answers"][0]["bases"][0]["search_receipt"] = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"}
    )["data"]["search_receipt"]
    draft["answers"][0]["question_id"] = "sq:randomization:not-active"
    receipt = _call_raw(workspace, draft)
    _assert_repairs(receipt)
    codes = {item["code"] for item in receipt["repairs"]}
    assert "invalid_answer" in codes
    assert "answers_must_match_active_questions" in codes


def test_domain_source_is_derived_from_selected_evidence(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"})[
        "data"
    ]["search_receipt"]
    draft = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    draft["answers"][0]["bases"][0] = {
        "kind": "direct_support",
        "evidence": evidence["handle"],
    }
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted
    assert "clauses" not in accepted["data"]["checkpoint"]
    basis = accepted["data"]["checkpoint"]["answers"][0]["bases"][0]
    assert basis["source"] == evidence["quote"]
    assert "rationale" not in basis


@pytest.mark.parametrize(
    ("probable_answer", "circumstance"),
    [
        (
            "probably_yes",
            "The sequence was described as apparently random, but the report did not "
            "provide enough detail for a definitive judgment.",
        ),
        (
            "probably_no",
            "The sequence was described as apparently predictable rather than random, "
            "but the report did not provide enough detail for a definitive judgment.",
        ),
    ],
)
@pytest.mark.parametrize("firm_answer", ["yes", "no"])
def test_probable_answers_accept_limitation_but_firm_answers_require_direct_evidence(
    tmp_path: Path,
    probable_answer: str,
    circumstance: str,
    firm_answer: str,
) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"})[
        "data"
    ]["search_receipt"]
    probable = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    probable["answers"][0]["answer"] = probable_answer
    probable["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "text": circumstance,
            "search_receipt": receipt,
        }
    ]
    accepted = _call(workspace, "save_domain_judgment", probable)
    assert accepted["outcome"] == "success", accepted

    firm = _domain_draft(
        "trial",
        "domain:deviations",
        accepted["head"]["state_revision"],
        search_receipt=receipt,
    )
    firm["answers"][0]["answer"] = firm_answer
    repaired = _call_raw(workspace, firm)
    _assert_repairs(repaired)
    repair = next(
        item for item in repaired["repairs"] if item["code"] == "answer_requires_direct_basis"
    )
    assert "question 'sq:deviations:participants-aware'" in repair["detail"]
    assert "probably_yes/probably_no" in repair["detail"]


@pytest.mark.parametrize("appropriate_answer", ["yes", "probably_yes"])
def test_domain_two_judgment_with_itt_premise_advances_to_domain_three(
    tmp_path: Path,
    appropriate_answer: str,
) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    itt_premise = (
        "The intention-to-treat analysis included all randomized participants in the groups "
        "to which they were assigned."
    )
    main.write_text(main.read_text(encoding="utf-8") + " " + itt_premise, encoding="utf-8")
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    first = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert first["outcome"] == "success", first
    revision = int(first["head"]["state_revision"])
    itt = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": evidence["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    limitation_receipt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"}
    )["data"]["search_receipt"]
    draft = _domain_draft("trial", "domain:deviations", revision, evidence, limitation_receipt)
    for answer in draft["answers"]:
        if answer["question_id"] in {
            "sq:deviations:participants-aware",
            "sq:deviations:personnel-aware",
            "sq:deviations:context-deviations",
        }:
            answer["answer"] = "no_information"
            answer["bases"] = [
                {
                    "kind": "limitation",
                    "text": "The report does not describe this circumstance.",
                    "search_receipt": limitation_receipt,
                }
            ]
        elif answer["question_id"] == "sq:deviations:appropriate-analysis":
            answer["answer"] = appropriate_answer
            answer["bases"] = [
                {
                    "kind": "direct_support",
                    "evidence": itt["handle"],
                }
            ]
    draft["answers"] = [
        item
        for item in draft["answers"]
        if item["question_id"]
        not in {
            "sq:deviations:affected-outcome",
            "sq:deviations:balanced",
            "sq:deviations:substantial-impact",
        }
    ]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    assert saved["data"]["checkpoint"]["judgment"] == "some_concerns"
    context = _call(workspace, "get_domain_context", {})
    assert context["head"]["next_action"]["domain_id"] == "domain:missing"


def test_domain_absence_basis_contains_only_search_receipt(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(workspace, "search_sources", {"trial_id": "trial", "query": "absent-term"})
    receipt = _search_receipt(workspace, search["data"]["search_receipt"])
    draft = _domain_draft(
        "trial",
        "domain:randomization",
        revision,
        search_receipt=search["data"]["search_receipt"],
    )
    draft["answers"][0]["bases"] = [
        {"kind": "absence", "search_receipt": search["data"]["search_receipt"]}
    ]
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success"
    assert accepted["data"]["checkpoint"]["answers"][0]["bases"] == [
        {"kind": "absence", "search_receipt": receipt["identity"]}
    ]


def test_domain_absence_basis_resolves_server_receipt_handle(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(workspace, "search_sources", {"trial_id": "trial", "query": "absent-term"})
    receipt = _search_receipt(workspace, search["data"]["search_receipt"])
    draft = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt=receipt["handle"]
    )
    draft["answers"][0]["bases"] = [{"kind": "absence", "search_receipt": receipt["handle"]}]

    accepted = _call(workspace, "save_domain_judgment", draft)

    assert accepted["outcome"] == "success", accepted
    assert accepted["data"]["checkpoint"]["answers"][0]["bases"] == [
        {"kind": "absence", "search_receipt": receipt["identity"]}
    ]


def test_domain_limitation_requires_and_stores_nontruncated_receipt(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"})
    draft = _domain_draft(
        "trial",
        "domain:randomization",
        revision,
        search_receipt=search["data"]["search_receipt"],
    )
    draft["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "text": "The report does not describe this circumstance.",
            "search_receipt": search["data"]["search_receipt"],
        }
    ]
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted
    receipt = _search_receipt(workspace, search["data"]["search_receipt"])
    checkpoint = accepted["data"]["checkpoint"]
    assert checkpoint["answers"][0]["bases"] == [
        {
            "kind": "limitation",
            "text": draft["answers"][0]["bases"][0]["text"],
            "search_receipt": receipt["identity"],
        }
    ]
    assert checkpoint["search_accounts"] == [
        {
            key: receipt[key]
            for key in (
                "identity",
                "handle",
                "trial_id",
                "query",
                "mode",
                "total_matches",
                "truncated",
                "condition",
            )
        }
    ]


def test_domain_limitation_accepts_positive_nontruncated_receipt(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(workspace, "search_sources", {"trial_id": "trial", "query": "requested outcome"})
    assert search["data"]["total_matches"] > 0
    assert search["data"]["truncated"] is False
    draft = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt=search["data"]["search_receipt"]
    )
    draft["answers"][0]["bases"] = [
        {
            "kind": "limitation",
            "text": "The selected positive passage does not settle this question.",
            "search_receipt": search["data"]["search_receipt"],
        }
    ]
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted


def test_domain_limitation_without_receipt_is_repaired(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt="sr_" + "0" * 16
    )
    draft["answers"][0]["bases"] = [
        {"kind": "limitation", "text": "Not reported.", "search_receipt": "sr_" + "0" * 16}
    ]
    repaired = _call_raw(workspace, draft)
    _assert_repairs(repaired)
    assert any(item["code"] == "invalid_search_receipt" for item in repaired["repairs"])


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
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    search = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "rare absence candidate", "limit": 1},
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


def test_domain_duplicate_nested_basis_is_repaired_without_mutating_state(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source"})[
        "data"
    ]["search_receipt"]
    draft = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    use = {
        "kind": "direct_support",
        "evidence": evidence["handle"],
    }
    draft["answers"][0]["bases"] = [use, dict(use)]
    receipt = _call_raw(workspace, draft)
    _assert_repairs(receipt)
    assert any(item["code"] == "duplicate_answer_basis" for item in receipt["repairs"])
    assert receipt["head"]["state_revision"] == revision
