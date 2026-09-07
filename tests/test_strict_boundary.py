from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

from rob2_kit.interfaces.mcp.contracts import PublicHead, SelectedFigureEvidence, normalize
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import (
    ExpectedRevision,
    MultipleConcernsDecision,
    NormalizedCoordinate,
    PageNumber,
)


@pytest.mark.parametrize(
    ("annotation", "value"),
    ((PageNumber, "1"), (NormalizedCoordinate, "0.5"), (ExpectedRevision, "0")),
)
def test_workflow_scalar_aliases_reject_string_numerics(annotation: Any, value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(value)


def test_multiple_concerns_rejects_string_boolean() -> None:
    with pytest.raises(ValidationError):
        MultipleConcernsDecision(raises_overall_to_high=cast(Any, "true"), rationale="reason")


def test_public_head_rejects_string_revision() -> None:
    with pytest.raises(ValidationError):
        PublicHead(
            phase="empty",
            state_revision="0",
            next_action=None,
            authoritative_wording="status",
        )


def test_finalized_receipt_keeps_nullable_next_action_field() -> None:
    receipt = normalize(
        "finalize_batch",
        {
            "outcome": "success",
            "phase": "finalized",
            "state_revision": 4,
            "artifact": {
                "path": ".rob2-kit/finalized/example.rob2.zip",
                "identity": "sha256:" + "0" * 64,
                "sha256": "sha256:" + "1" * 64,
                "files": ["canonical.json"],
            },
            "trial_dispositions": {"trial": "assessed"},
            "assessment_summary": {
                "trial": {
                    "overall": "some_concerns",
                    "domains": {
                        "domain:randomization": "some_concerns",
                        "domain:deviations": "low",
                        "domain:missing": "low",
                        "domain:measurement": "low",
                        "domain:selection": "low",
                    },
                }
            },
            "retry": False,
        },
    )
    assert "next_action" in receipt["head"]
    assert receipt["head"]["next_action"] is None


def test_public_figure_evidence_rejects_string_coordinates() -> None:
    with pytest.raises(ValidationError):
        SelectedFigureEvidence.model_validate(
            {
                "kind": "figure",
                "handle": "eh_" + "0" * 16,
                "identity": "sha256:" + "0" * 64,
                "trial_id": "trial",
                "source_id": "source_" + "0" * 64,
                "render": {
                    "identity": "sha256:" + "1" * 64,
                    "source_id": "source_" + "0" * 64,
                    "page": 1,
                    "png_sha256": "sha256:" + "2" * 64,
                    "recipe": "default",
                },
                "transcription": "values",
                "region": ["0.1", 0.2, 0.8, 0.9],
                "provenance": "host_visual",
            }
        )


def test_fastmcp_rejects_string_numeric_and_boolean_scalars() -> None:
    async def exercise() -> list[bool]:
        async with Client(mcp) as client:
            calls = (
                (
                    "prepare_batch",
                    {
                        "requested_outcome": "outcome",
                        "expected_revision": "0",
                    },
                ),
                (
                    "search_sources",
                    {"trial_id": "trial", "query": "term", "mode": "any", "limit": "20"},
                ),
                (
                    "render_page",
                    {
                        "trial_id": "trial",
                        "source_id": "source_" + "0" * 64,
                        "page": 1,
                        "inline": "false",
                    },
                ),
                (
                    "save_domain_judgment",
                    {
                        "trial_id": "trial",
                        "domain_id": "domain",
                        "expected_revision": 0,
                        "answers": [],
                        "multiple_concerns": {
                            "raises_overall_to_high": "true",
                            "rationale": "reason",
                        },
                    },
                ),
            )
            results = [
                await client.call_tool(name, arguments, raise_on_error=False)
                for name, arguments in calls
            ]
            return [result.is_error for result in results]

    assert asyncio.run(exercise()) == [True, True, True, True]


def test_fastmcp_requires_search_mode_at_public_boundary() -> None:
    async def search_without_mode() -> None:
        async with Client(mcp) as client:
            with pytest.raises(
                ToolError,
                match=r"(?s)1 validation error for call\[search_sources\].*"
                r"mode.*Missing required argument",
            ):
                await client.call_tool(
                    "search_sources",
                    {"trial_id": "trial", "query": "term"},
                )

    asyncio.run(search_without_mode())


def test_current_batch_resource_matches_get_status_receipt(tmp_path: Path) -> None:
    async def exercise() -> tuple[dict[str, Any], dict[str, Any]]:
        os.environ["ROB2_WORKSPACE"] = str(tmp_path)
        async with Client(mcp) as client:
            tool = dict((await client.call_tool("get_status", {})).structured_content or {})
            resource = await client.read_resource("rob2://current-batch")
            text = resource[0].text
            return tool, json.loads(text)

    tool, resource = asyncio.run(exercise())
    assert tool == resource
