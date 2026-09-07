from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client
from mcp import types as mcp_types
from pydantic import ValidationError
from support.rob2 import _assessment_workspace

import rob2_kit.application.domains as domain_application
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
from rob2_kit.interfaces.mcp.server import mcp


def _wire_context(workspace: Path) -> tuple[dict, str]:
    async def invoke() -> mcp_types.CallToolResult:
        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                return await client.call_tool("get_domain_context", {})
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


def test_domain_context_text_is_compact_and_ordered(tmp_path: Path) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    context, text = _wire_context(workspace)
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
    assert len(text.encode("utf-8")) > 0


def test_oversized_narrative_has_exact_read_recovery_and_utf8_accounting() -> None:
    quote = "é" * (_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET // 2 + 1)
    item = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "source_" + "2" * 64,
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
                "source_id": "source_" + "2" * 64,
                "page": 3,
                "start_line": 12,
                "end_line": 80,
            }
        ],
    }
    workspace = projected["evidence_workspace"]
    assert workspace["recoverable_narrative_text_bytes"] == 0
    assert workspace["omitted_narrative_text_bytes"] == len(quote.encode("utf-8"))


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
            "source_id": "source_" + "2" * 64,
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
            "source_id": "source_" + "4" * 64,
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
        "source_id": "source_" + "2" * 64,
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
        "source_id": "source_" + "4" * 64,
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
    source_id = "source_" + "2" * 64
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


def test_narrative_projection_requires_matching_text_and_recovery_state() -> None:
    complete = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "source_" + "2" * 64,
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


def test_narrative_projection_rejects_missing_recovery_coordinates() -> None:
    incomplete = {
        "kind": "narrative",
        "handle": "eh_0123456789abcdef",
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "source_" + "2" * 64,
        "page": 3,
        "quote": "exact text",
        "text_status": "complete",
    }
    with pytest.raises(ValidationError):
        DomainNarrativeEvidence.model_validate(incomplete)


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
