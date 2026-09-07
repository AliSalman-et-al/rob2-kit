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
    _option_for,
    _prepared_evidence,
    _proposal_args,
    _result,
    _result_for_trial,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.domains import reconcile_missing_data
from rob2_kit.application.evidence import _search_receipt
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import DomainAnswer


def _call_raw(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool("save_domain_judgment", arguments, raise_on_error=False)
            return dict(result.structured_content or {})

    return asyncio.run(invoke())


def _stored_checkpoint(workspace: Path, domain_id: str = "domain:randomization") -> dict[str, Any]:
    return _state(workspace)["domain_records"][f"trial:{domain_id}"]


def _assert_repairs(receipt: dict[str, Any]) -> None:
    assert receipt["outcome"] == "repair"
    assert all(set(item) == {"path", "code", "detail"} for item in receipt["repairs"])


def test_domain_public_shape_is_flat_and_closed() -> None:
    async def inspect() -> dict[str, Any]:
        async with Client(mcp) as client:
            tool = next(
                tool for tool in await client.list_tools() if tool.name == "save_domain_judgment"
            )
            return dict(tool.input_schema)

    schema = asyncio.run(inspect())
    draft = schema
    assert "clauses" not in draft["properties"]
    assert "evidence_uses" not in draft["properties"]
    assert "limitations" not in draft["properties"]
    answer = draft["properties"]["answers"]["items"]
    assert set(answer["properties"]) == {
        "question_id",
        "option_id",
        "bases",
        "justification",
        "missing_data",
    }
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
    missing_row = answer["properties"]["missing_data"]["anyOf"][0]["items"]
    assert missing_row["properties"]["basis"]["items"]["pattern"] == r"^eh_[0-9a-f]{16}$"


def test_option_id_repairs_are_atomic_and_valid_replay_is_idempotent(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    domain_id = SCIENTIFIC_PACK.domains[0].id
    draft = _domain_draft("trial", domain_id, revision, evidence)

    invalid = {**draft, "answers": [dict(item) for item in draft["answers"]]}
    invalid["answers"][0]["option_id"] = "opt:wrong-pack"
    repaired = _call(workspace, "save_domain_judgment", invalid)
    assert repaired["outcome"] == "repair"
    assert any(item["code"] == "invalid_answer_option" for item in repaired["repairs"])
    assert _state(workspace)["revision"] == revision

    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    retry = _call(workspace, "save_domain_judgment", draft)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True


def test_stale_inactive_option_and_evidence_are_ignored(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert first["outcome"] == "success", first
    draft = _domain_draft(
        "trial",
        "domain:deviations",
        int(first["head"]["state_revision"]),
        evidence,
    )
    by_question = {item["question_id"]: item for item in draft["answers"]}
    for question_id in (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
    ):
        by_question[question_id]["option_id"] = _option_for(question_id, "no")
    inactive = by_question["sq:deviations:context-deviations"]
    inactive["option_id"] = "opt_stale_inactive_option"
    inactive["bases"] = [{"kind": "direct_support", "evidence": "eh_0000000000000000"}]

    saved = _call(workspace, "save_domain_judgment", draft)

    assert saved["outcome"] == "success", saved
    stored_questions = {
        item["question_id"]
        for item in _stored_checkpoint(workspace, "domain:deviations")["answers"]
    }
    assert "sq:deviations:context-deviations" not in stored_questions


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
            "option_id": _option_for("sq:missing:data-available", "probably_no"),
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
                "option_id": _option_for("sq:missing:data-available", "probably_no"),
                "bases": [{"kind": "context", "evidence": "eh_0123456789abcdef"}],
                "missing_data": [row | {"basis": ["copied quote"]}],
            }
        )
    with pytest.raises(ValueError, match="only valid for question"):
        DomainAnswer.model_validate(
            {
                "question_id": "sq:missing:evidence-unbiased",
                "option_id": _option_for("sq:missing:evidence-unbiased", "no"),
                "bases": [{"kind": "context", "evidence": "eh_0123456789abcdef"}],
                "missing_data": [row],
            }
        )


def test_missing_data_reconciliation_derives_arithmetic_and_count_conflicts() -> None:
    first = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 100,
        "observed": 95,
        "analyzed": 95,
        "exclusions": ["five outcomes unavailable"],
        "basis": ["eh_0123456789abcdef"],
    }
    second = first | {
        "analyzed": 94,
        "basis": ["eh_fedcba9876543210"],
    }

    reconciled = reconcile_missing_data([first, second])

    assert [row["missing"] for row in reconciled["rows"]] == [5, 5]
    assert [row["missing_fraction"] for row in reconciled["rows"]] == [0.05, 0.05]
    assert reconciled["conflicts"] == [
        {
            "scope": reconciled["rows"][1]["scope"],
            "reports": reconciled["rows"],
        }
    ]


def test_missing_data_reuses_and_canonicalizes_answer_evidence(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains[:2]:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    answer = next(
        item for item in draft["answers"] if item["question_id"] == "sq:missing:data-available"
    )
    answer["missing_data"] = [
        {
            "arm": "intervention",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "week 12",
            "randomized": 100,
            "observed": 95,
        }
    ]

    saved = _call(workspace, "save_domain_judgment", draft)

    assert saved["outcome"] == "success", saved
    checkpoint = _stored_checkpoint(workspace, "domain:missing")
    stored = next(
        item for item in checkpoint["answers"] if item["question_id"] == "sq:missing:data-available"
    )
    assert stored["missing_data"]["rows"][0]["basis"] == [evidence["identity"]]


def test_domain_context_recovers_uncommitted_trial_evidence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.write_text(
        main.read_text(encoding="utf-8") + "Domain-specific participant flow.\n",
        encoding="utf-8",
    )
    proposal_evidence = _prepared_evidence(workspace)
    _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(proposal_evidence)]),
    )
    _review(workspace)
    domain_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": proposal_evidence["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]

    context = _call(workspace, "get_domain_context", {})["data"]

    recovered = {item["handle"]: item for item in context["evidence"]}
    assert recovered[domain_evidence["handle"]]["quote"] == domain_evidence["quote"]
    assert recovered[domain_evidence["handle"]]["identity"] == domain_evidence["identity"]
    assert recovered[domain_evidence["handle"]]["inclusion_reason"] == "explicit_carry_forward"


def test_domain_context_recovers_prior_checkpoint_evidence_after_cache_loss(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.write_text(
        main.read_text(encoding="utf-8") + "Domain-specific participant flow.\n",
        encoding="utf-8",
    )
    proposal_evidence = _prepared_evidence(workspace)
    _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(proposal_evidence)]),
    )
    _review(workspace)
    domain_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": proposal_evidence["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence=domain_evidence),
    )
    assert saved["outcome"] == "success", saved
    (workspace / ".rob2-kit" / "derivative.sqlite3").unlink()

    active_context = _call(workspace, "get_domain_context", {})["data"]
    assert domain_evidence["identity"] not in {
        item["identity"] for item in active_context["evidence"]
    }
    context = _call(
        workspace,
        "get_domain_context",
        {"domain_id": "domain:randomization"},
    )["data"]

    recovered = {item["identity"]: item for item in context["evidence"]}
    assert recovered[domain_evidence["identity"]]["handle"] == domain_evidence["handle"]
    assert recovered[domain_evidence["identity"]]["quote"] == domain_evidence["quote"]


def test_domain_context_scopes_candidates_before_applying_the_budget(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "decisive randomization detail")
    for index in range(70):
        page = document.new_page()
        page.insert_text((72, 72), f"later deviation noise {index}")
    (workspace / "input" / "trial" / "domain-noise.pdf").write_bytes(document.tobytes())
    document.close()

    proposal_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "domain-noise.pdf"
    )
    decisive = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "query": "decisive randomization detail",
            "mode": "all",
            "limit": 1,
        },
    )["data"]["hits"][0]
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, proposal_evidence),
    )
    assert saved["outcome"] == "success", saved
    noise = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "query": "later deviation noise",
            "mode": "all",
            "limit": 100,
        },
    )["data"]
    assert len(noise["hits"]) == 70

    context = _call(
        workspace,
        "get_domain_context",
        {"domain_id": "domain:randomization"},
    )["data"]
    candidates = {
        item["handle"]: item
        for item in context["evidence"]
        if item.get("inclusion_reason") == "active_domain_candidate"
    }
    assert decisive["passage_ref"] in candidates
    assert candidates[decisive["passage_ref"]]["domain_id"] == "domain:randomization"
    assert not ({hit["passage_ref"] for hit in noise["hits"]} & candidates.keys())
    candidate_group = next(
        item
        for item in context["evidence_workspace"]["groups"]
        if item["inclusion_reason"] == "active_domain_candidate"
    )
    assert decisive["passage_ref"] in candidate_group["evidence_handles"]
    assert set(candidate_group["question_ids"]) == {
        item.id for item in SCIENTIFIC_PACK.questions if item.domain_id == "domain:randomization"
    }


def test_proposal_search_candidates_do_not_leak_into_first_domain(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "proposal-only.txt").write_text(
        "proposal candidate unrelated to randomization\n", encoding="utf-8"
    )
    proposal_evidence = _prepared_evidence(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "proposal-only.txt"
    )
    proposal_candidate = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "query": "proposal candidate",
            "mode": "all",
        },
    )["data"]["hits"][0]
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)

    context = _call(workspace, "get_domain_context", {})["data"]

    assert proposal_candidate["passage_ref"] not in {item["handle"] for item in context["evidence"]}


def test_domain_context_continuation_reaches_omissions_across_sessions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    for query in ("alpha candidate", "beta candidate"):
        for index in range(33):
            page = document.new_page()
            page.insert_text((72, 72), f"{query} {index}")
    (workspace / "input" / "trial" / "many-candidates.pdf").write_bytes(document.tobytes())
    document.close()

    proposal_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "many-candidates.pdf"
    )
    for query in ("alpha candidate", "beta candidate"):
        search = _call(
            workspace,
            "search_sources",
            {
                "trial_id": "trial",
                "source_id": source["id"],
                "query": query,
                "mode": "all",
                "limit": 100,
            },
        )["data"]
        assert len(search["hits"]) == 33

    context = _call(workspace, "get_domain_context", {})["data"]
    evidence_workspace = context["evidence_workspace"]
    assert evidence_workspace["omitted_count"] == 2
    assert evidence_workspace["omitted_by_category"]["active_domain_candidate"] == 2
    actions = evidence_workspace["continuations"]
    assert len(actions) == 2
    assert {action["query"] for action in actions} == {"alpha candidate", "beta candidate"}
    action = evidence_workspace["continuation"]
    assert action == actions[0]

    for action in actions:
        arguments = dict(action)
        continued = _call(workspace, arguments.pop("operation"), arguments)
        assert continued["outcome"] == "success", continued
        assert continued["data"]["hits"]


def test_saved_contradiction_is_projected_in_contradiction_group(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.write_text(main.read_text(encoding="utf-8") + "Contradictory report.\n", encoding="utf-8")
    result_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(result_evidence)]))
    _review(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    contradiction = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:randomization", revision, contradiction)
    for answer in draft["answers"]:
        answer["bases"][0]["kind"] = "contradiction"
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
    assert group["evidence_handles"] == [contradiction["handle"]]


def test_domain_context_continuation_reaches_unreturned_session_candidates(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path / "captured")
    trial = workspace / "input" / "trial"
    document = pymupdf.open()
    for index in range(70):
        page = document.new_page()
        page.insert_text((72, 72), f"deep candidate {index}")
    (trial / "deep.pdf").write_bytes(document.tobytes())
    document.close()
    proposal_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "deep.pdf"
    )

    first = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "query": "deep candidate",
            "mode": "all",
            "limit": 1,
        },
    )["data"]
    assert first["candidate_count"] == 70

    context = _call(workspace, "get_domain_context", {})["data"]
    evidence_workspace = context["evidence_workspace"]
    assert evidence_workspace["omitted_by_category"]["active_domain_candidate"] == 69
    action = dict(evidence_workspace["continuation"])
    continued = _call(workspace, action.pop("operation"), action)
    assert continued["data"]["hits"][0]["rank"] == 2


def test_explicit_carry_forward_has_budget_priority_and_exact_read_continuation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    extra = workspace / "input" / "trial" / "explicit.txt"
    extra.write_text(
        "".join(f"explicit evidence {index}\n" for index in range(130)), encoding="utf-8"
    )
    proposal_evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(proposal_evidence)]))
    _review(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "explicit.txt"
    )
    for line in range(1, 131):
        selected = _call(
            workspace,
            "select_text_evidence",
            {
                "trial_id": "trial",
                "source_id": source["id"],
                "page": 1,
                "start_line": line,
                "end_line": line,
            },
        )
        assert selected["outcome"] == "success"

    context = _call(workspace, "get_domain_context", {})["data"]
    workspace_data = context["evidence_workspace"]
    explicit = next(
        group
        for group in workspace_data["groups"]
        if group["inclusion_reason"] == "explicit_carry_forward"
    )
    assert len(explicit["evidence_handles"]) == 64
    assert workspace_data["omitted_by_category"]["explicit_carry_forward"] == 66
    assert [len(item["windows"]) for item in workspace_data["continuations"]] == [20, 20, 20, 6]
    action = dict(workspace_data["continuation"])
    assert action["operation"] == "read_pages"
    assert action["windows"][0]["start_line"] == 65
    continued = _call(workspace, action.pop("operation"), action)
    assert continued["outcome"] == "success"


def test_domain_context_does_not_expose_another_trials_uncommitted_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial_b = workspace / "input" / "trial-b"
    trial_b.mkdir()
    text = (workspace / "input" / "trial" / "main.txt").read_text(encoding="utf-8")
    for trial_id in ("trial", "trial-b"):
        path = workspace / "input" / trial_id / "main.txt"
        path.write_text(text + "Domain-only evidence.\n", encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    selected: dict[str, dict[str, Any]] = {}
    for trial_id in ("trial", "trial-b"):
        source = _call(workspace, "list_sources", {"trial_id": trial_id})["data"]["sources"][0]
        selected[trial_id] = _call(
            workspace,
            "select_text_evidence",
            {
                "trial_id": trial_id,
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )["data"]["evidence"]
    _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [
                _result_for_trial(selected["trial"], "trial"),
                _result_for_trial(selected["trial-b"], "trial-b"),
            ],
        ),
    )
    _review(workspace)
    other = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial-b",
            "source_id": selected["trial-b"]["source_id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]

    context = _call(workspace, "get_domain_context", {"trial_id": "trial"})["data"]

    exposed = {item["handle"] for item in context["evidence"]}
    assert selected["trial"]["handle"] in exposed
    assert selected["trial-b"]["handle"] not in exposed
    assert other["handle"] not in exposed


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
        "options",
        "active",
        "activation",
        "official_guidance",
        "source_locator",
        "decision_rule",
        "evidence_needed",
        "no_information_rule",
        "considerations",
        "invalid_shortcuts",
        "query_suggestions",
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
        "query_suggestions",
    }
    assert pack_question.guidance.official.source_excerpt == question_card["official_guidance"]
    assert pack_question.guidance.official.source_locator == question_card["source_locator"]
    assert pack_question.guidance.operational.decision_rule == question_card["decision_rule"]
    assert pack_question.guidance.operational.considerations == tuple(
        question_card["considerations"]
    )
    assert {item["id"] for item in data["questions"]} == {
        item.id for item in SCIENTIFIC_PACK.questions if item.domain_id == data["domain_id"]
    }


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


def test_domain_source_is_derived_from_selected_evidence(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
    draft = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    draft["answers"][0]["bases"][0] = {
        "kind": "direct_support",
        "evidence": evidence["handle"],
    }
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted
    assert "clauses" not in accepted["data"]["checkpoint"]
    basis = _stored_checkpoint(workspace)["answers"][0]["bases"][0]
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
    receipt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
    probable = _domain_draft("trial", "domain:randomization", revision, search_receipt=receipt)
    probable["answers"][0]["option_id"] = _option_for("sq:randomization:sequence", probable_answer)
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
    firm["answers"][0]["option_id"] = _option_for("sq:deviations:participants-aware", firm_answer)
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
    branch_context = _call(workspace, "get_domain_context", {})["data"]
    assert {item["id"] for item in branch_context["questions"]} == {
        item.id for item in SCIENTIFIC_PACK.questions if item.domain_id == "domain:deviations"
    }
    assert any(not item["active"] for item in branch_context["questions"])
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
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
    draft = _domain_draft("trial", "domain:deviations", revision, evidence, limitation_receipt)
    for answer in draft["answers"]:
        if answer["question_id"] in {
            "sq:deviations:participants-aware",
            "sq:deviations:personnel-aware",
            "sq:deviations:context-deviations",
        }:
            answer["option_id"] = _option_for(answer["question_id"], "no_information")
            answer["bases"] = [
                {
                    "kind": "limitation",
                    "text": "The report does not describe this circumstance.",
                    "search_receipt": limitation_receipt,
                }
            ]
        elif answer["question_id"] == "sq:deviations:appropriate-analysis":
            answer["option_id"] = _option_for(answer["question_id"], appropriate_answer)
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
    search = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "absent-term", "mode": "any"}
    )
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
    assert _stored_checkpoint(workspace)["answers"][0]["bases"] == [
        {"kind": "absence", "search_receipt": receipt["identity"]}
    ]


def test_domain_absence_basis_resolves_server_receipt_handle(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "absent-term", "mode": "any"}
    )
    receipt = _search_receipt(workspace, search["data"]["search_receipt"])
    draft = _domain_draft(
        "trial", "domain:randomization", revision, search_receipt=receipt["handle"]
    )
    draft["answers"][0]["bases"] = [{"kind": "absence", "search_receipt": receipt["handle"]}]

    accepted = _call(workspace, "save_domain_judgment", draft)

    assert accepted["outcome"] == "success", accepted
    assert _stored_checkpoint(workspace)["answers"][0]["bases"] == [
        {"kind": "absence", "search_receipt": receipt["identity"]}
    ]


def test_domain_limitation_requires_and_stores_nontruncated_receipt(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )
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
    checkpoint = _stored_checkpoint(workspace)
    assert checkpoint["answers"][0]["bases"] == [
        {
            "kind": "limitation",
            "text": draft["answers"][0]["bases"][0]["text"],
            "search_receipt": receipt["identity"],
        }
    ]
    assert len(checkpoint["search_accounts"]) == 1
    assert {
        key: checkpoint["search_accounts"][0][key]
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
    } == {
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


def test_domain_limitation_accepts_positive_nontruncated_receipt(tmp_path: Path) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    search = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any"},
    )
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


def test_domain_duplicate_nested_basis_is_repaired_without_mutating_state(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    receipt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "not-in-source", "mode": "any"}
    )["data"]["search_receipt"]
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
