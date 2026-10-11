from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from rob2_kit.interfaces.mcp.contracts import (
    ResearcherReviewAction,
    SelectedNarrativeEvidence,
    validate_output,
)
from rob2_kit.interfaces.mcp.server import mcp


def test_researcher_review_purpose_is_closed() -> None:
    with pytest.raises(ValidationError):
        ResearcherReviewAction.model_validate(
            {
                "operation": "researcher_review",
                "authority": "researcher",
                "reference": "sha256:" + "0" * 64,
                "purpose": "arbitrary",
            }
        )


def _walk_schema(schema: object, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(schema, dict):
        return []
    found: list[tuple[str, dict[str, Any]]] = []
    if schema.get("type") == "object":
        found.append((path, cast(dict[str, Any], schema)))
    for key in ("properties", "$defs", "definitions"):
        values = schema.get(key)
        if isinstance(values, dict):
            for name, child in values.items():
                found.extend(_walk_schema(child, f"{path}/{key}/{name}"))
    for key in ("items", "additionalProperties", "contains", "not", "if", "then", "else"):
        child = schema.get(key)
        if isinstance(child, dict):
            found.extend(_walk_schema(child, f"{path}/{key}"))
    for key in ("oneOf", "anyOf", "allOf", "prefixItems"):
        values = schema.get(key)
        if isinstance(values, list):
            for index, child in enumerate(values):
                found.extend(_walk_schema(child, f"{path}/{key}/{index}"))
    return found


def test_receipt_and_evidence_variants_reject_cross_variant_fields() -> None:
    with pytest.raises(ValidationError):
        SelectedNarrativeEvidence.model_validate(
            {
                "kind": "narrative",
                "handle": "eh_0000000000000000",
                "identity": "sha256:" + "0" * 64,
                "trial_id": "trial",
                "source_id": "source_" + "0" * 64,
                "page": 1,
                "quote": "quoted",
                "render": {"identity": "sha256:" + "0" * 64},
            }
        )
    with pytest.raises(ValidationError):
        validate_output(
            "list_sources",
            {
                "outcome": "success",
                "head": {
                    "phase": "empty",
                    "state_revision": 0,
                    "next_action": {"operation": "get_status", "authority": "host"},
                    "authoritative_wording": "status",
                },
                "data": {"sources": []},
                "repairs": [{"path": "x", "code": "y"}],
            },
        )


@pytest.mark.parametrize(
    ("labels", "detail"),
    (
        (["STAMPEDE", "STAMPEDE"], "trial_labels must not contain duplicate directory labels"),
        (["MISSING"], "unknown trial label: input/MISSING"),
    ),
)
def test_prepare_batch_rejects_invalid_trial_labels(
    tmp_path: Path, labels: list[str], detail: str
) -> None:
    for name in ("STAMPEDE", "PEACE-1"):
        (tmp_path / "input" / name).mkdir(parents=True)

    result = _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "overall survival",
            "trial_labels": labels,
            "expected_revision": 0,
        },
    )

    assert result["outcome"] == "condition"
    assert result["condition"] == {"code": "invalid_request", "detail": detail}


@pytest.mark.parametrize("labels", ([], [" "]))
def test_prepare_batch_rejects_empty_or_blank_trial_labels(
    tmp_path: Path, labels: list[str]
) -> None:
    (tmp_path / "input" / "Trial A").mkdir(parents=True)

    async def prepare() -> None:
        os.environ["ROB2_WORKSPACE"] = str(tmp_path)
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "prepare_batch",
                    {
                        "requested_outcome": "requested outcome",
                        "trial_labels": labels,
                        "expected_revision": 0,
                    },
                )

    asyncio.run(prepare())


def test_prepare_batch_rejects_empty_trial_directory_set(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    result = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "overall survival", "expected_revision": 0},
    )
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "invalid_request"


def test_prepare_batch_rejects_extra_fields_at_fastmcp_boundary(tmp_path: Path) -> None:
    (tmp_path / "input" / "Trial").mkdir(parents=True)

    async def prepare() -> None:
        os.environ["ROB2_WORKSPACE"] = str(tmp_path)
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "prepare_batch",
                    {
                        "requested_outcome": "overall survival",
                        "expected_revision": 0,
                        "trials": [],
                    },
                )

    asyncio.run(prepare())


def test_prepare_batch_rejects_colliding_derived_trial_ids(tmp_path: Path) -> None:
    for name in ("Trial A", "trial-a"):
        (tmp_path / "input" / name).mkdir(parents=True)
        (tmp_path / "input" / name / "main.txt").write_text(name, encoding="utf-8")
    result = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "overall survival", "expected_revision": 0},
    )
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "invalid_request"


def _leaves(value: Any, path: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            child_path: child
            for key, item in value.items()
            if key not in {"form", "kind"}
            for child_path, child in _leaves(item, f"{path}/{key}").items()
        }
    if isinstance(value, list):
        return {
            child_path: child
            for index, item in enumerate(value)
            for child_path, child in _leaves(item, f"{path}/{index}").items()
        }
    return {path: value}


def _call(workspace: Path, tool: str, arguments: dict[str, object]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
            return dict(result.structured_content or {})

    return asyncio.run(invoke())
