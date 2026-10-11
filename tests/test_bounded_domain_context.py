from __future__ import annotations

import asyncio
import copy
import os
import re
import sqlite3
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
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

import rob2_kit.application.domains as domain_application
import rob2_kit.interfaces.mcp.server as mcp_server
from rob2_kit.application._state import _commit, _identity, _state
from rob2_kit.application.domains import (
    _compact_domain_evidence,
)
from rob2_kit.interfaces.mcp.contracts import (
    DomainDerivedEvidence,
    DomainNarrativeEvidence,
    DomainTableEvidence,
    SelectedFigureEvidence,
)
from rob2_kit.interfaces.mcp.server import (
    _decode_domain_context_cursor,
    _domain_context_cursor,
    _domain_context_transport_bytes,
    _paginate_domain_context_transport,
    mcp,
)
from rob2_kit.packs import SCIENTIFIC_PACK
from scripts.profile_domain_context_delivery import _omit_empty_section_arrays, _reconstruct


def _wire_context(
    workspace: Path,
    arguments: dict[str, object] | None = None,
    *,
    drain: bool = True,
) -> tuple[dict, int]:
    async def invoke() -> mcp_types.CallToolResult:
        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                request = arguments or {}
                result = await client.call_tool("get_domain_context", request)
                if drain and "cursor" not in request and "max_response_bytes" not in request:
                    pages = [result]
                    structured = dict(result.structured_content or {})
                    while (
                        isinstance(structured.get("data"), dict)
                        and isinstance(structured["data"].get("context_page"), dict)
                        and structured["data"]["context_page"].get("next_cursor") is not None
                    ):
                        cursor = structured["data"]["context_page"]["next_cursor"]
                        result = await client.call_tool("get_domain_context", {"cursor": cursor})
                        pages.append(result)
                        structured = dict(result.structured_content or {})
                    if len(pages) > 1 and all(
                        isinstance(page.structured_content, dict)
                        and isinstance(page.structured_content.get("data"), dict)
                        for page in pages
                    ):
                        merged = dict(pages[0].structured_content or {})
                        data = dict(pages[0].structured_content["data"])
                        for section in (
                            "questions",
                            "assessment_guidance",
                            "reading_leads",
                            "comparison_cards",
                            "registry_outcomes",
                            "evidence",
                        ):
                            data[section] = [
                                item
                                for page in pages
                                for item in page.structured_content["data"].get(section, [])
                            ]
                        cores = [
                            page.structured_content["data"]["official_guidance"]
                            for page in pages
                            if page.structured_content["data"].get("official_guidance")
                        ]
                        if cores:
                            data["official_guidance"] = {
                                "pack": cores[0]["pack"],
                                "sections": [
                                    section for core in cores for section in core["sections"]
                                ],
                                "complete": True,
                                "next_cursor": None,
                            }
                        data.pop("context_page", None)
                        merged["data"] = data
                        merged["head"] = pages[-1].structured_content.get("head")
                        return mcp_types.CallToolResult(
                            content=[],
                            structured_content=merged,
                        )
                return result
        finally:
            if previous is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous

    result = asyncio.run(invoke())
    assert result.content == []
    assert isinstance(result.structured_content, dict)
    parsed = dict(result.structured_content)
    return parsed, _domain_context_transport_bytes(parsed)


def _pending_assessment_workspace(tmp_path: Path) -> tuple[Path, dict, int]:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    return workspace, evidence, revision


def test_auto_domain_context_delivery_is_sequential_and_restartable(tmp_path: Path) -> None:
    workspace, evidence, revision = _pending_assessment_workspace(tmp_path)
    first, transport_bytes = _wire_context(workspace, {"max_response_bytes": 16_384}, drain=False)
    page = first["data"]["context_page"]
    assert page["index"] == 0
    assert page["next_cursor"]
    assert page["delivery_status"] == "incomplete"
    assert first["head"]["next_action"]["operation"] == "get_domain_context"
    assert first["head"]["next_action"]["cursor"] == page["next_cursor"]
    assert first["head"]["next_action"]["max_response_bytes"] == page["max_response_bytes"]
    assert transport_bytes <= 32_768
    first_cursor = page["next_cursor"]

    status = _call(workspace, "get_status", {})
    assert status["head"]["next_action"]["cursor"] == first_cursor
    premature = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert premature["outcome"] == "condition"
    assert premature["head"]["next_action"]["domain_id"] == "domain:randomization"
    assert premature["head"]["next_action"]["cursor"] == first_cursor

    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT next_index,complete FROM domain_context_delivery"
        ).fetchone()
    assert row == (1, 0)

    blocked = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert blocked["outcome"] == "condition"
    assert blocked["condition"]["code"] == "domain_context_delivery_pending"
    assert blocked["head"]["next_action"]["cursor"] == first_cursor
    recovery = blocked["condition"]["recovery"]
    assert recovery["operation"] == "get_domain_context"
    assert recovery["arguments"]["cursor"] == first_cursor
    assert recovery["arguments"]["max_response_bytes"] == page["max_response_bytes"]
    assert _domain_context_transport_bytes(blocked) <= 32_768

    stale_revision = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision + 1, evidence),
    )
    assert stale_revision["outcome"] == "conflict"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute(
            "SELECT next_index,complete FROM domain_context_delivery"
        ).fetchone() == (1, 0)

    if page["count"] > 2:
        skipped_payload = _decode_domain_context_cursor(first_cursor)
        skipped_payload["page_index"] = page["count"] - 1
        skipped = _domain_context_cursor(skipped_payload)
        out_of_order, _transport_bytes = _wire_context(workspace, {"cursor": skipped}, drain=False)
        assert out_of_order["outcome"] == "condition"
        assert out_of_order["condition"]["code"] == "domain_context_delivery_out_of_order"
        assert first_cursor in out_of_order["condition"]["detail"]

    continued, continued_transport_bytes = _wire_context(
        workspace, recovery["arguments"], drain=False
    )
    assert continued["data"]["context_page"]["index"] == 1
    assert continued_transport_bytes <= 32_768

    repeated, _transport_bytes = _wire_context(workspace, {"cursor": first_cursor}, drain=False)
    repeated_again, _transport_bytes = _wire_context(
        workspace, {"cursor": first_cursor}, drain=False
    )
    assert repeated == repeated_again
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute("SELECT next_index FROM domain_context_delivery").fetchone() == (
            2,
        )

    cursor = repeated["data"]["context_page"]["next_cursor"]
    while cursor is not None:
        next_page, _transport_bytes = _wire_context(workspace, {"cursor": cursor}, drain=False)
        cursor = next_page["data"]["context_page"]["next_cursor"]
        assert next_page["data"]["context_page"]["delivery_status"] == (
            "incomplete" if cursor is not None else "complete"
        )
        if cursor is not None:
            assert next_page["head"]["next_action"]["cursor"] == cursor
        else:
            assert next_page["head"]["next_action"]["operation"] == "save_domain_judgment"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute(
            "SELECT complete,next_cursor FROM domain_context_delivery"
        ).fetchone() == (1, None)
        completed_delivery = connection.execute(
            "SELECT digest,page_size,page_count,next_index,next_cursor,complete "
            "FROM domain_context_delivery"
        ).fetchone()

    refreshed, _transport_bytes = _wire_context(
        workspace, {"max_response_bytes": 16_384}, drain=False
    )
    assert refreshed["data"]["context_page"]["index"] == 0
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT digest,page_size,page_count,next_index,next_cursor,complete "
                "FROM domain_context_delivery"
            ).fetchone()
            == completed_delivery
        )

    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"
    assert saved["head"]["next_action"]["domain_id"] == "domain:deviations"
    assert saved["head"]["next_action"].get("cursor") is None


def test_small_domain_context_receipt_remains_unpaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _evidence, _revision = _pending_assessment_workspace(tmp_path)
    monkeypatch.setattr(mcp_server, "_DOMAIN_CONTEXT_DEFAULT_PAGE_BYTES", 131_072)
    context, _transport_bytes = _wire_context(workspace, {}, drain=False)
    assert "context_page" not in context["data"]


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
        "max_response_bytes": 32_768,
    }
    while True:
        page, transport_bytes = _wire_context(workspace, arguments)
        pages.append(page)
        metadata = page["data"]["context_page"]
        assert metadata["trial_id"] == "trial"
        assert metadata["domain_id"] == "domain:deviations"
        assert metadata["state_revision"] == page["head"]["state_revision"]
        if metadata["index"] == 0:
            assert page["data"]["result"]
            assert page["data"]["evidence_workspace"]
            assert page["data"]["questions"]
        else:
            assert "result" not in page["data"]
            assert "evidence_workspace" not in page["data"]
            assert metadata["stable_recovery"] == {
                "operation": "get_domain_context",
                "cursor": pages[0]["data"]["context_page"]["stable_recovery"]["cursor"],
            }
        assert transport_bytes <= metadata["max_response_bytes"]
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
    question_ids = {
        question["id"] for page in pages for question in page["data"].get("questions", [])
    }
    expected_ids = {
        question.id
        for question in SCIENTIFIC_PACK.questions
        if question.domain_id == "domain:deviations"
    }
    assert question_ids == expected_ids
    assert "sq:deviations:substantial-impact" in question_ids

    reconstructed = _reconstruct({i: page for i, page in enumerate(pages)})
    full, _transport_bytes = _wire_context(
        workspace,
        {"trial_id": "trial", "domain_id": "domain:deviations"},
    )
    assert reconstructed == full["data"]


def test_empty_delta_arrays_are_omittable_without_changing_reconstructed_context(
    tmp_path: Path,
) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    pages: list[dict] = []
    request: dict[str, object] = {"max_response_bytes": 32_768}
    while True:
        page, _bytes = _wire_context(workspace, request)
        pages.append(page)
        cursor = page["data"]["context_page"]["next_cursor"]
        if cursor is None:
            break
        request = {"cursor": cursor}

    assert len(pages) > 1
    candidate_pages = [_omit_empty_section_arrays(page)[0] for page in pages]
    assert any(
        section not in candidate_pages[index]["data"]
        for index in range(1, len(candidate_pages))
        for section in ("questions", "evidence", "comparison_cards")
    )
    for candidate in candidate_pages[1:]:
        validated = mcp_server.validate_output("get_domain_context", candidate)
        assert validated["data"]["context_page"] == candidate["data"]["context_page"]

    reconstructed = _reconstruct({i: page for i, page in enumerate(candidate_pages)})
    full = _call(workspace, "get_domain_context", {})["data"]
    assert reconstructed == full


def test_domain_context_cursor_rejects_revision_change(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first, _transport_bytes = _wire_context(workspace, {"max_response_bytes": 32_768})
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor
    first_cursor = cursor

    while cursor is not None:
        page, _transport_bytes = _wire_context(workspace, {"cursor": cursor}, drain=False)
        cursor = page["data"]["context_page"]["next_cursor"]

    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        delivery_before = connection.execute(
            "SELECT next_index,complete FROM domain_context_delivery"
        ).fetchone()
    stale, _transport_bytes = _wire_context(workspace, {"cursor": first_cursor})
    assert stale["outcome"] == "condition"
    assert stale["condition"]["code"] == "domain_context_cursor_stale"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert (
            connection.execute("SELECT next_index,complete FROM domain_context_delivery").fetchone()
            == delivery_before
        )


def test_domain_context_cursor_keeps_snapshot_after_search_changes_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "methods.txt").write_text(
        "A separate searchable methods note was preserved.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    original, _transport_bytes = _wire_context(workspace)
    first, _transport_bytes = _wire_context(workspace, {"max_response_bytes": 16_384}, drain=False)
    first_page = first["data"]["context_page"]
    cursor = first_page["next_cursor"]
    assert cursor
    first_cursor = cursor

    searched = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "searchable methods note", "mode": "any"},
    )
    assert searched["outcome"] == "success"
    assert searched["data"]["total_matches"] > 0

    pages = [first]
    while cursor is not None:
        page, _transport_bytes = _wire_context(workspace, {"cursor": cursor}, drain=False)
        assert page["outcome"] == "success", page
        pages.append(page)
        cursor = page["data"]["context_page"]["next_cursor"]

    reconstructed = _reconstruct({i: page for i, page in enumerate(pages)})
    assert reconstructed == original["data"]

    replaced, _transport_bytes = _wire_context(
        workspace, {"max_response_bytes": 16_384}, drain=False
    )
    assert replaced["data"]["context_page"]["index"] == 0
    continued, _transport_bytes = _wire_context(workspace, {"cursor": first_cursor}, drain=False)
    assert continued["outcome"] == "success", continued
    assert continued["data"]["context_page"]["index"] == 1
    assert continued["head"]["state_revision"] == first["head"]["state_revision"]
    assert continued["data"]["context_page"]["state_revision"] == first_page["state_revision"]

    fresh_candidates, _transport_bytes = _wire_context(workspace, {"include_candidates": True})
    assert not any(
        item.get("inclusion_reason") == "active_domain_candidate"
        for item in fresh_candidates["data"]["evidence"]
    ), fresh_candidates["data"]["evidence_workspace"]


@pytest.mark.parametrize("domain_id", ["domain:deviations", "domain:missing"])
def test_stale_submission_restarts_attempted_domain(tmp_path: Path, domain_id: str) -> None:
    workspace, evidence, _revision = _assessment_workspace(tmp_path)
    scope: dict[str, object] = {"trial_id": "trial", "domain_id": domain_id}
    _call(workspace, "get_domain_context", scope)
    updated = _call(
        workspace,
        "save_working_checkpoint",
        {
            "checkpoint": {
                "trial_id": "trial",
                "result_account": [
                    {
                        "id": "ascertainment",
                        "aspect": "outcome_ascertainment",
                        "observation": {
                            "text": "The selected report supplies the assessment context.",
                            "sources": [
                                {
                                    "source_id": evidence["source_id"],
                                    "page": 1,
                                    "start_line": 1,
                                    "end_line": 1,
                                }
                            ],
                        },
                    }
                ],
            }
        },
    )
    assert updated["outcome"] == "success", updated
    revision = updated["head"]["state_revision"]
    before = _state(workspace)
    blocked = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert blocked["outcome"] == "condition", blocked
    assert blocked["condition"]["code"] == "domain_context_delivery_stale"
    action = blocked["head"]["next_action"]
    assert action["operation"] == "get_domain_context"
    assert action["trial_id"] == "trial"
    assert action["domain_id"] == domain_id
    assert action["cursor"] is None
    assert blocked["condition"]["recovery"] is None
    assert _state(workspace) == before
    assert _call(workspace, "get_status", {})["head"]["next_action"]["domain_id"] == (
        "domain:randomization"
    )
    _call(workspace, action["operation"], scope)
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert saved["outcome"] == "success", saved


def test_domain_context_cursor_survives_unrelated_domain_commit(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    scope: dict[str, object] = {"trial_id": "trial", "domain_id": "domain:deviations"}
    original, _transport_bytes = _wire_context(workspace, scope)
    first, _transport_bytes = _wire_context(
        workspace, {**scope, "max_response_bytes": 16_384}, drain=False
    )
    first_page = first["data"]["context_page"]
    cursor = first_page["next_cursor"]
    assert cursor is not None

    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"

    pages = [first]
    while cursor is not None:
        page, _transport_bytes = _wire_context(workspace, {"cursor": cursor}, drain=False)
        assert page["outcome"] == "success"
        pages.append(page)
        cursor = page["data"]["context_page"]["next_cursor"]

    assert pages[-1]["head"]["state_revision"] > first["head"]["state_revision"]
    assert pages[-1]["data"]["context_page"]["state_revision"] == first_page["state_revision"]
    reconstructed = _reconstruct({i: page for i, page in enumerate(pages)})
    assert reconstructed == original["data"]


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
    state_revision = int(second_save["head"]["state_revision"])
    preview = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 1,
        "observed": 1,
        "basis": [evidence["handle"]],
    }
    first, _transport_bytes = _wire_context(
        workspace,
        {"missing_data": [preview], "max_response_bytes": 32_768},
    )
    context_domain = first["data"]["domain_id"]
    recovery_cursor = first["data"]["context_page"]["stable_recovery"]["cursor"]
    original_digest = first["data"]["context_page"]["snapshot_digest"]
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor
    changed = preview | {"observed": 0}

    stale, _transport_bytes = _wire_context(
        workspace,
        {"cursor": cursor, "missing_data": [changed]},
    )

    assert stale["outcome"] == "condition"
    assert stale["condition"]["code"] == "domain_context_cursor_stale"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        pending_digest = connection.execute(
            "SELECT digest FROM domain_context_delivery "
            "WHERE trial_id=? AND domain_id=? AND state_revision=?",
            ("trial", context_domain, state_revision),
        ).fetchone()[0]
    restarted, _transport_bytes = _wire_context(
        workspace,
        {"missing_data": [changed], "max_response_bytes": 32_768},
        drain=False,
    )
    assert restarted["data"]["context_page"]["index"] == 0
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        delivery = connection.execute(
            "SELECT digest,next_index,complete FROM domain_context_delivery "
            "WHERE trial_id=? AND domain_id=? AND state_revision=?",
            ("trial", context_domain, state_revision),
        ).fetchone()
    assert delivery[0] != pending_digest
    assert delivery[1:] == (1, 0)

    searched = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "randomized", "mode": "any"},
    )
    assert searched["outcome"] == "success"
    recovered, _transport_bytes = _wire_context(workspace, {"cursor": recovery_cursor}, drain=False)
    assert recovered["outcome"] == "success"
    assert recovered["data"]["context_page"]["index"] == 0
    assert recovered["data"]["context_page"]["snapshot_digest"] == original_digest


def test_domain_context_pagination_rejects_oversized_unicode_evidence(
    tmp_path: Path,
) -> None:
    quote = "é" * 20_000
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    value, _transport_bytes = _wire_context(workspace)
    value["data"]["evidence"][0]["quote"] = quote

    with pytest.raises(
        ValueError, match="domain_context_item_oversized: section=evidence"
    ) as error:
        _paginate_domain_context_transport(
            value, None, 32_768, "test-basis", value["head"]["state_revision"]
        )
    required_match = re.search(r"required_page_size=(\d+)", str(error.value))
    assert required_match is not None
    required = int(required_match.group(1))
    page = _paginate_domain_context_transport(
        value, None, required, "test-basis", value["head"]["state_revision"]
    )
    assert page["data"]["context_page"]["max_response_bytes"] == required


def test_non_narrative_evidence_stays_valid_in_compact_projection() -> None:
    source_id = "sh_" + "2" * 16
    figure = {
        "kind": "figure",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": source_id,
        "delivery_receipt": "sha256:" + "5" * 64,
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


def test_public_boundary_exposes_executable_narrative_recovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(domain_application, "_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET", 0)
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    context, _transport_bytes = _wire_context(workspace)
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


def test_question_scoped_discoveries_keep_their_premises_without_hiding_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    supplement = workspace / "input" / "trial" / "supplement.txt"
    supplement.write_text(
        "Ascertainment was incomplete at the outcome visit.\n\n"
        + "An unrelated neutral passage.\n" * 20
        + "\nSensitivity analysis varied the unobserved outcome assumptions.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    source_id = next(
        source["id"]
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if source["label"] == "supplement.txt"
    )
    domain = "domain:missing"
    availability = "sq:missing:data-available"
    bias = "sq:missing:evidence-unbiased"
    handles = {}
    for query, question in (("Ascertainment", availability), ("Sensitivity", bias)):
        searched = _call(
            workspace,
            "search_sources",
            {
                "trial_id": "trial",
                "source_id": source_id,
                "query": query,
                "mode": "all",
                "purpose_domain_id": domain,
                "purpose_question_id": question,
            },
        )["data"]
        handles[question] = searched["hits"][0]["passage_ref"]

    arguments: dict[str, object] = {
        "trial_id": "trial",
        "domain_id": domain,
        "include_candidates": True,
    }
    context, _bytes = _wire_context(workspace, arguments)
    data = context["data"]
    groups = data["evidence_workspace"]["groups"]
    scopes = {
        handle: set(group["question_ids"])
        for group in groups
        if group["inclusion_reason"] == "active_domain_candidate"
        for handle in group["evidence_handles"]
    }
    assert scopes[handles[availability]] == {availability}
    assert scopes[handles[bias]] == {bias}
    identities = {item["handle"]: item["identity"] for item in data["evidence"]}
    for card in data["comparison_cards"]:
        refs = {ref["handle"]: ref for group in card["passage_groups"] for ref in group["passages"]}
        for question, handle in handles.items():
            assert refs[handle]["retrieval_question_ids"] == [question]

    reused = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source_id,
            "query": "Ascertainment",
            "mode": "all",
            "purpose_domain_id": domain,
            "purpose_question_id": bias,
        },
    )["data"]
    assert reused["hits"][0]["passage_ref"] == handles[availability]
    shared, _bytes = _wire_context(workspace, arguments)
    shared_scope = next(
        group["question_ids"]
        for group in shared["data"]["evidence_workspace"]["groups"]
        if handles[availability] in group["evidence_handles"]
    )
    assert availability in shared_scope and bias in shared_scope
    assert identities == {item["handle"]: item["identity"] for item in shared["data"]["evidence"]}

    # An unqualified reuse must broaden discovery scope, rather than implying
    # that a search purpose determines where the passage can be scientific support.
    _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": source_id,
            "query": "Ascertainment",
            "mode": "all",
            "purpose_domain_id": domain,
        },
    )
    widened, _bytes = _wire_context(workspace, arguments)
    widened_groups = widened["data"]["evidence_workspace"]["groups"]
    scope = next(
        group["question_ids"]
        for group in widened_groups
        if handles[availability] in group["evidence_handles"]
    )
    assert availability in scope and bias in scope
    assert identities == {item["handle"]: item["identity"] for item in widened["data"]["evidence"]}
    original = refs[handles[availability]]
    adjacent = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": original["source_id"],
                    "page": original["page"],
                    "start_line": original["start_line"],
                    "end_line": original["end_line"] + 2,
                }
            ],
        },
    )["data"]["pages"][0]["numbered_text"]
    assert "Ascertainment was incomplete" in adjacent
    assert "An unrelated neutral passage" in adjacent


def test_imputation_quantity_conflict_is_source_bound_in_native_preview(tmp_path: Path) -> None:
    workspace, evidence, _ = _assessment_workspace(tmp_path)
    before = copy.deepcopy(_state(workspace))
    first, _ = _wire_context(
        workspace,
        {
            "trial_id": "trial",
            "domain_id": "domain:missing",
            "missing_data": [
                {
                    "arm": "A",
                    "population": "all randomized participants",
                    "unit": "participants",
                    "time_point": "week 8",
                    "window": "week 8",
                    "endpoint": "selected endpoint",
                    "randomized": 20,
                    "observed": 20,
                    "analyzed": 20,
                    "imputed": 3,
                    "semantics": {"population_role": "randomized", "outcome_status": "imputed"},
                    "basis": [evidence["handle"]],
                }
            ],
        },
    )
    card = first["data"]["comparison_cards"][0]
    row = card["missing_data"]["rows"][0]
    assert row["quantity_conflict"] and row["missing"] is None
    assert row["missing_fraction"] is row["missing_bounds"] is None
    assert row["basis"] == [evidence["identity"]]
    assert all(
        r["status"] == "conflicted" and r["passages"]
        for r in card["participant_flow"]
        if r["kind"] in {"observed", "imputed"}
    )
    assert _state(workspace) == before
