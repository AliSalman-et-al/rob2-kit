from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
from fastmcp import Client
from mcp import types as mcp_types
from pydantic import ValidationError
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

import rob2_kit.application.domains as domain_application
from rob2_kit.application._state import _commit, _identity, _state
from rob2_kit.application.domains import (
    _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET,
    _compact_domain_evidence,
    _evidence_text_bytes,
)
from rob2_kit.interfaces.mcp.contracts import (
    DomainDerivedEvidence,
    DomainNarrativeEvidence,
    DomainTableEvidence,
    SelectedFigureEvidence,
)
from rob2_kit.interfaces.mcp.server import _paginate_domain_context_transport, mcp
from rob2_kit.packs import SCIENTIFIC_PACK


def _wire_context(workspace: Path, arguments: dict[str, object] | None = None) -> tuple[dict, str]:
    async def invoke() -> mcp_types.CallToolResult:
        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                return await client.call_tool("get_domain_context", arguments or {})
        finally:
            if previous is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous

    result = asyncio.run(invoke())
    text = next(item.text for item in result.content if isinstance(item, mcp_types.TextContent))
    assert result.structured_content is not None
    parsed = json.loads(text)
    assert parsed == result.structured_content
    return parsed, text


def test_domain_context_pages_retain_scope_and_all_conditional_questions(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"

    pages: list[dict] = []
    arguments: dict[str, object] = {
        "trial_id": "trial",
        "domain_id": "domain:deviations",
        "page_size": 32_768,
    }
    while True:
        page, text = _wire_context(workspace, arguments)
        pages.append(page)
        metadata = page["data"]["context_page"]
        assert metadata["trial_id"] == "trial"
        assert metadata["domain_id"] == "domain:deviations"
        assert metadata["state_revision"] == page["head"]["state_revision"]
        assert page["data"]["result"]
        assert page["data"]["evidence_workspace"]
        transport_bytes = len(
            json.dumps(
                {
                    "content": [{"type": "text", "text": text}],
                    "structured_content": page,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        assert transport_bytes <= metadata["page_size"]
        cursor = metadata["next_cursor"]
        if cursor is not None:
            assert page["head"]["next_action"]["operation"] == "get_domain_context"
        if cursor is None:
            break
        arguments = {"cursor": cursor}

    assert len(pages) > 1
    assert [page["data"]["context_page"]["index"] for page in pages] == list(range(len(pages)))
    assert all(page["data"]["context_page"]["count"] == len(pages) for page in pages)
    assert pages[-1]["head"]["next_action"]["operation"] == "save_domain_judgment"
    question_ids = {question["id"] for page in pages for question in page["data"]["questions"]}
    expected_ids = {
        question.id
        for question in SCIENTIFIC_PACK.questions
        if question.domain_id == "domain:deviations"
    }
    assert question_ids == expected_ids
    assert "sq:deviations:substantial-impact" in question_ids

    reconstructed = dict(pages[0]["data"])
    for section in ("questions", "comparison_cards", "evidence"):
        reconstructed[section] = [item for page in pages for item in page["data"][section]]
    reconstructed.pop("context_page")
    full, _text = _wire_context(
        workspace,
        {"trial_id": "trial", "domain_id": "domain:deviations"},
    )
    assert reconstructed == full["data"]


def test_domain_context_cursor_rejects_revision_change(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first, _text = _wire_context(workspace, {"page_size": 32_768})
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor

    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"
    stale, _text = _wire_context(workspace, {"cursor": cursor})
    assert stale["outcome"] == "condition"
    assert stale["condition"]["code"] == "domain_context_cursor_stale"


def test_domain_context_cursor_only_continuation_keeps_nonactive_domain(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"
    first, _text = _wire_context(
        workspace,
        {
            "trial_id": "trial",
            "domain_id": "domain:randomization",
            "page_size": 32_768,
        },
    )
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor

    continuation, _text = _wire_context(workspace, {"cursor": cursor})

    assert continuation["data"]["domain_id"] == "domain:randomization"
    assert continuation["data"]["context_page"]["domain_id"] == "domain:randomization"


def test_domain_context_cursor_rejects_changed_missing_data_preview(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first_save = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert first_save["outcome"] == "success"
    second_save = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft(
            "trial",
            "domain:deviations",
            int(first_save["head"]["state_revision"]),
            evidence,
        ),
    )
    assert second_save["outcome"] == "success"
    preview = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 1,
        "observed": 1,
        "basis": [evidence["handle"]],
    }
    first, _text = _wire_context(
        workspace,
        {"missing_data": [preview], "page_size": 32_768},
    )
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor
    changed = preview | {"observed": 0}

    stale, _text = _wire_context(
        workspace,
        {"cursor": cursor, "missing_data": [changed]},
    )

    assert stale["outcome"] == "condition"
    assert stale["condition"]["code"] == "domain_context_cursor_stale"


def test_domain_context_intermediate_page_bounds_large_missing_preview(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first_save = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert first_save["outcome"] == "success"
    second_save = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft(
            "trial",
            "domain:deviations",
            int(first_save["head"]["state_revision"]),
            evidence,
        ),
    )
    assert second_save["outcome"] == "success"
    preview = [
        {
            "arm": f"intervention-{index}-" + ("a" * 160),
            "population": "randomized participants " + ("p" * 160),
            "unit": "participants",
            "time_point": f"week-{index + 1}",
            "randomized": 100 + index,
            "observed": 90 + index,
            "basis": [evidence["handle"]],
        }
        for index in range(18)
    ]
    arguments: dict[str, object] = {"missing_data": preview, "page_size": 131_072}
    pages: list[tuple[dict, str]] = []
    while True:
        page, text = _wire_context(workspace, arguments)
        assert page["outcome"] == "success"
        pages.append((page, text))
        metadata = page["data"]["context_page"]
        transport_bytes = len(
            json.dumps(
                {
                    "content": [{"type": "text", "text": text}],
                    "structured_content": page,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        assert transport_bytes <= metadata["page_size"]
        if metadata["next_cursor"] is None:
            break
        arguments = {"cursor": metadata["next_cursor"]}

    assert len(pages) > 2
    intermediate = pages[1][0]["data"]["context_page"]
    assert intermediate["cursor"] is not None
    assert intermediate["next_cursor"] is not None


def test_domain_context_pagination_rejects_oversized_unicode_evidence(
    tmp_path: Path,
) -> None:
    quote = "é" * 20_000
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    value, _text = _wire_context(workspace)
    value["data"]["evidence"][0]["quote"] = quote

    with pytest.raises(
        ValueError, match="domain_context_item_oversized: section=evidence"
    ) as error:
        _paginate_domain_context_transport(value, None, 32_768)
    required_match = re.search(r"required_page_size=(\d+)", str(error.value))
    assert required_match is not None
    required = int(required_match.group(1))
    page = _paginate_domain_context_transport(value, None, required)
    assert page["data"]["context_page"]["page_size"] == required


def test_domain_context_page_digest_rejects_same_revision_evidence_change(
    tmp_path: Path,
) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    value, _text = _wire_context(workspace)
    first = _paginate_domain_context_transport(value, None, 32_768)
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor
    value["data"]["evidence"][0]["quote"] = "changed"

    with pytest.raises(ValueError, match="domain_context_cursor_stale"):
        _paginate_domain_context_transport(value, cursor, None)


def test_domain_context_small_budget_returns_header_condition(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    page_size = 4_096
    context, _text = _wire_context(workspace, {"page_size": page_size})

    assert context["outcome"] == "condition"
    assert context["condition"]["code"] == "domain_context_header_oversized"
    for _ in range(3):
        required_match = re.search(r"required_page_size=(\d+)", context["condition"]["detail"])
        assert required_match is not None
        page_size = int(required_match.group(1))
        context, _text = _wire_context(workspace, {"page_size": page_size})
        if context["outcome"] == "success":
            break
        assert context["condition"]["code"] in {
            "domain_context_header_oversized",
            "domain_context_item_oversized",
        }
    assert context["outcome"] == "success"


def test_domain_context_text_is_compact_and_ordered(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    context, _text = _wire_context(workspace)
    data = context["data"]
    keys = list(data)
    assert keys.index("result") < keys.index("questions") < keys.index("evidence")
    assert keys.index("comparison_cards") < keys.index("evidence")
    assert "meaning" not in data["questions"][0]["options"][0]
    assert "consequence" not in data["questions"][0]["options"][0]
    assert (
        data["evidence_workspace"]["recoverable_narrative_text_bytes"]
        <= _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET
    )


def test_oversized_narrative_has_exact_read_recovery_and_utf8_accounting() -> None:
    quote = "é" * (_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET // 2 + 1)
    item = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "2" * 16,
        "page": 3,
        "start_line": 12,
        "end_line": 80,
        "quote": quote,
        "inclusion_reason": "active_domain_candidate",
    }
    projected = _compact_domain_evidence(
        {
            "answers": [],
            "evidence": [item],
            "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
        }
    )
    output = projected["evidence"][0]
    assert output["quote"] is None
    assert output["text_status"] == "omitted"
    assert output["recovery"] == {
        "operation": "read_pages",
        "trial_id": "trial",
        "windows": [
            {
                "source_id": "sh_" + "2" * 16,
                "page": 3,
                "start_line": 12,
                "end_line": 80,
            }
        ],
    }
    workspace = projected["evidence_workspace"]
    assert workspace["recoverable_narrative_text_bytes"] == 0
    assert workspace["omitted_narrative_text_bytes"] == len(quote.encode("utf-8"))


def test_coordinate_less_legacy_narrative_is_reported_outside_recoverable_budget() -> None:
    quote = "legacy " * _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET
    projected = _compact_domain_evidence(
        {
            "answers": [],
            "evidence": [
                {
                    "kind": "narrative",
                    "handle": "eh_0123456789abcdef",
                    "identity": "sha256:" + "1" * 64,
                    "trial_id": "trial",
                    "source_id": "sh_" + "2" * 16,
                    "page": 3,
                    "quote": quote,
                }
            ],
            "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
        }
    )
    workspace = projected["evidence_workspace"]
    assert projected["evidence"][0]["text_status"] == "complete"
    assert workspace["recoverable_narrative_text_bytes"] == 0
    assert workspace["unrecoverable_inline_text_bytes"] == len(quote.encode("utf-8"))


def test_checkpoint_basis_quote_is_not_repeated_in_context() -> None:
    context = {
        "answers": [
            {
                "question_id": "sq:randomization:sequence",
                "answer": "yes",
                "bases": [
                    {
                        "kind": "direct_support",
                        "evidence": "sha256:" + "1" * 64,
                        "source": "exact source-bound quote",
                    }
                ],
            }
        ],
        "evidence": [],
        "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
    }
    projected = _compact_domain_evidence(context)
    assert "source" not in projected["answers"][0]["bases"][0]
    assert projected["evidence_workspace"]["omitted_narrative_text_bytes"] == len(
        b"exact source-bound quote"
    )


def test_derived_text_bytes_include_each_non_ascii_input_value() -> None:
    item = {
        "kind": "derived",
        "value": "Δ",
        "inputs": [
            {"handle": "eh_0123456789abcdef", "value": "é"},
            {"handle": "eh_abcdef0123456789", "value": "ß"},
        ],
    }
    assert _evidence_text_bytes(item) == len("Δéß".encode())


def test_multiple_narratives_accumulate_recoverable_text_bytes() -> None:
    evidence = [
        {
            "kind": "narrative",
            "handle": "eh_0123456789abcdef",
            "identity": "sha256:" + "1" * 64,
            "trial_id": "trial",
            "source_id": "sh_" + "2" * 16,
            "page": 1,
            "start_line": 1,
            "end_line": 1,
            "quote": "first é",
        },
        {
            "kind": "narrative",
            "handle": "eh_abcdef0123456789",
            "identity": "sha256:" + "3" * 64,
            "trial_id": "trial",
            "source_id": "sh_" + "4" * 16,
            "page": 2,
            "start_line": 2,
            "end_line": 3,
            "quote": "second Δ",
        },
    ]
    projected = _compact_domain_evidence(
        {
            "answers": [],
            "evidence": evidence,
            "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
        }
    )
    assert projected["evidence_workspace"]["recoverable_narrative_text_bytes"] == sum(
        _evidence_text_bytes(item) for item in evidence
    )


def test_explicit_carry_forward_has_priority_over_active_candidate_budget() -> None:
    active_candidate = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "2" * 16,
        "page": 1,
        "start_line": 1,
        "end_line": 20,
        "quote": "x" * (_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET + 1),
        "inclusion_reason": "active_domain_candidate",
    }
    explicit = {
        "kind": "narrative",
        "handle": "eh_abcdef0123456789",
        "identity": "sha256:" + "3" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "4" * 16,
        "page": 2,
        "start_line": 1,
        "end_line": 1,
        "quote": "explicit passage",
        "inclusion_reason": "explicit_carry_forward",
    }
    projected = _compact_domain_evidence(
        {
            "answers": [],
            "evidence": [active_candidate, explicit],
            "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
        }
    )
    by_handle = {item["handle"]: item for item in projected["evidence"]}
    assert by_handle[active_candidate["handle"]]["text_status"] == "omitted"
    assert by_handle[explicit["handle"]]["text_status"] == "complete"


def test_non_narrative_evidence_stays_valid_in_compact_projection() -> None:
    source_id = "sh_" + "2" * 16
    figure = {
        "kind": "figure",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": source_id,
        "render": {
            "identity": "sha256:" + "3" * 64,
            "source_id": source_id,
            "page": 3,
            "png_sha256": "sha256:" + "4" * 64,
            "recipe": "page-png-v1",
        },
        "transcription": "figure values",
        "provenance": "host_visual",
        "region": [0.1, 0.1, 0.9, 0.9],
    }
    table = {
        "kind": "table",
        "handle": "eh_abcdef0123456789",
        "basis": "text",
        "title": "outcome",
        "scope": "randomized population",
        "cohort": "randomized population",
        "row": "events",
        "columns": ["group A", "group B"],
        "group_or_category_axes": ["group"],
        "cells": ["1", "2"],
        "units": ["events"],
        "denominators": ["100", "100"],
    }
    derived = {
        "kind": "derived",
        "operation": "difference",
        "inputs": [{"handle": figure["handle"], "value": "1"}],
        "value": "1",
    }
    projected = _compact_domain_evidence(
        {
            "answers": [],
            "evidence": [figure, table, derived],
            "evidence_workspace": {"selection_policy_version": "rob2-kit.domain-projection.v0.5"},
        }
    )
    output = projected["evidence"]
    assert all("text_status" not in item for item in output)
    SelectedFigureEvidence.model_validate(output[0])
    DomainTableEvidence.model_validate(output[1])
    DomainDerivedEvidence.model_validate(output[2])


def test_nonrecoverable_explicit_evidence_does_not_disappear_at_item_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _result_evidence, _revision = _assessment_workspace(tmp_path)
    source_id = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]["id"]
    figures = {
        "sha256:" + f"{index:064x}": {
            "kind": "figure",
            "handle": "eh_" + f"{index:016x}",
            "identity": "sha256:" + f"{index:064x}",
            "trial_id": "trial",
            "source_id": source_id,
            "render": {
                "identity": "sha256:" + f"{index + 100:064x}",
                "source_id": source_id,
                "page": 1,
                "png_sha256": "sha256:" + f"{index + 200:064x}",
                "recipe": "page-png-v1",
            },
            "transcription": f"visual transcription {index}",
            "provenance": "host_visual",
            "region": [0.1, 0.1, 0.9, 0.9],
        }
        for index in range(1, 66)
    }
    monkeypatch.setattr(domain_application, "_evidence_catalog", lambda *_args, **_kwargs: figures)

    context = domain_application.get_domain_context(workspace)
    visible = {item["handle"] for item in context["evidence"]}
    assert {item["handle"] for item in figures.values()} <= visible
    assert context["evidence_workspace"]["omitted_by_category"]["explicit_carry_forward"] == 0


def test_narrative_projection_requires_matching_text_and_recovery_state() -> None:
    complete = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "2" * 16,
        "page": 3,
        "start_line": 1,
        "end_line": 1,
        "quote": "exact text",
        "text_status": "complete",
    }
    DomainNarrativeEvidence.model_validate(complete)
    omitted = {
        **complete,
        "quote": None,
        "text_status": "omitted",
        "start_line": 12,
        "end_line": 80,
        "recovery": {
            "operation": "read_pages",
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": complete["source_id"],
                    "page": 3,
                    "start_line": 12,
                    "end_line": 80,
                }
            ],
        },
    }
    DomainNarrativeEvidence.model_validate(omitted)


def test_complete_legacy_narrative_allows_missing_coordinates_but_recovery_is_exact() -> None:
    incomplete = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "2" * 16,
        "page": 3,
        "quote": "exact text",
        "text_status": "complete",
    }
    DomainNarrativeEvidence.model_validate(incomplete)
    with pytest.raises(ValidationError):
        DomainNarrativeEvidence.model_validate(
            {
                **incomplete,
                "quote": None,
                "text_status": "omitted",
                "start_line": 12,
                "end_line": 80,
                "recovery": {
                    "operation": "read_pages",
                    "trial_id": "trial",
                    "windows": [
                        {
                            "source_id": incomplete["source_id"],
                            "page": 3,
                            "start_line": 1,
                            "end_line": 80,
                        }
                    ],
                },
            }
        )


def test_domain_context_accepts_legacy_complete_narrative_without_coordinates(
    tmp_path: Path,
) -> None:
    workspace, evidence, _revision = _assessment_workspace(tmp_path)
    state = _state(workspace)
    stored = next(
        item
        for item in state["proposal"]["evidence"].values()
        if item["handle"] == evidence["handle"]
    )
    stored.pop("start_line")
    stored.pop("end_line")
    state["proposal"]["identity"] = _identity(state["proposal"]["payload"])
    _commit(workspace, state, int(state["revision"]))

    context = _call(workspace, "get_domain_context", {})["data"]
    projected = next(item for item in context["evidence"] if item["handle"] == evidence["handle"])
    assert projected["text_status"] == "complete"
    assert projected["quote"] == evidence["quote"]
    assert projected["start_line"] is None
    assert projected["end_line"] is None
    assert context["evidence_workspace"]["recoverable_narrative_text_bytes"] == 0
    assert context["evidence_workspace"]["unrecoverable_inline_text_bytes"] == len(
        evidence["quote"].encode("utf-8")
    )


def test_domain_context_projects_derived_result_and_unique_input_evidence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.write_text(main.read_text(encoding="utf-8") + "3\n", encoding="utf-8")
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    source_id = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]["id"]
    derived_input = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source_id,
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    state = _state(workspace)
    result = state["proposal"]["payload"]["results"][0]
    derived = {
        "kind": "derived",
        "operation": "sum",
        "inputs": [{"handle": derived_input["handle"], "value": "3"}],
        "value": "3",
    }
    result["evidence"].append(derived)
    state["proposal"]["identity"] = _identity(state["proposal"]["payload"])
    _commit(workspace, state, int(state["revision"]))

    context = _call(workspace, "get_domain_context", {})["data"]
    assert context["result"]["evidence"][-1] == derived
    assert derived_input["handle"] in {item["handle"] for item in context["evidence"]}
    assert context["evidence_workspace"]["unrecoverable_inline_text_bytes"] >= len(b"33")


def test_domain_context_preserves_complete_category_profile_result(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    state = _state(workspace)
    reported = state["proposal"]["payload"]["results"][0]["reported"]
    reported.clear()
    reported.update(
        {
            "form": "single_group_category_profile",
            "endpoint": {"name": "requested outcome", "definition": None},
            "group_id": "a",
            "denominator_basis": "randomized population",
            "category_axis_names": ["event", "grade"],
            "categories": [
                {"category_axes": ["Any event", "Grade 3"], "value": "65"},
                {"category_axes": ["Any event", "Grade 4"], "value": "17"},
            ],
        }
    )
    state["proposal"]["identity"] = _identity(state["proposal"]["payload"])
    _commit(workspace, state, int(state["revision"]))

    context = _call(workspace, "get_domain_context", {})["data"]
    assert context["result"]["reported"] == reported


def test_public_boundary_exposes_executable_narrative_recovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(domain_application, "_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET", 0)
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    context, _text = _wire_context(workspace)
    omitted = [item for item in context["data"]["evidence"] if item.get("text_status") == "omitted"]
    assert omitted
    recovery = omitted[0]["recovery"]
    assert set(recovery) == {"operation", "trial_id", "windows"}
    assert recovery["operation"] == "read_pages"

    async def invoke() -> mcp_types.CallToolResult:
        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                return await client.call_tool(
                    "read_pages",
                    {"trial_id": recovery["trial_id"], "windows": recovery["windows"]},
                )
        finally:
            if previous is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous

    read_result = asyncio.run(invoke())
    assert read_result.structured_content is not None
    assert read_result.structured_content["outcome"] == "success"
