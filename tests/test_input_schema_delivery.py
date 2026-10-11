"""Clients must see and be able to repair the actual closed argument shape."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from pydantic import ValidationError
from support.rob2 import _assessment_workspace, _domain_draft, _domain_submission

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import (
    MissingDataRow,
    MissingDataSemantics,
)


def _has_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_has_ref(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_ref(child) for child in value)
    return False


def test_revision_argument_error_returns_revision_grammar_without_answer_reconstruction(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_submission(_domain_draft("trial", "domain:randomization", revision, evidence))
    draft["revision_basis"] = {"kind": "self_correction", "reason": "PRIVATE scientific rationale"}
    before = _state(workspace)

    async def call():
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            return await client.call_tool("save_domain_judgment", draft, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    assert "/revision_basis/self_correction/rationale" in text
    assert "PRIVATE scientific rationale" not in text
    recovery = json.loads(text.split(" Argument recovery: ", 1)[1])
    schema = recovery["revision_basis_schemas"]["self_correction"]
    assert set(schema["required"]) == {"kind", "rationale"}
    assert schema["additionalProperties"] is False
    assert "minimal_answer_schema" not in recovery
    assert "Complete answer syntax example" not in text
    assert _state(workspace) == before


@pytest.mark.parametrize("model", [MissingDataRow, MissingDataSemantics])
@pytest.mark.parametrize(
    ("quantities", "valid"),
    [
        ({}, True),
        ({"event_count": None}, True),
        ({"event_count": 0}, False),
        ({"event_count": 3, "event_definition": None}, False),
        ({"event_count": 3, "event_definition": " "}, False),
        ({"event_count": 0, "event_definition": "Participants with first endpoint event"}, True),
        ({"event_count": 3, "event_definition": "Recurrent endpoint events"}, True),
    ],
)
def test_event_count_definition_requirement_matches_validated_branches(
    model: type[MissingDataRow] | type[MissingDataSemantics],
    quantities: dict[str, Any],
    valid: bool,
) -> None:
    scope = (
        {"arm": "A", "population": "randomized", "unit": "participants", "time_point": "30 days"}
        if model is MissingDataRow
        else {}
    )
    if valid:
        model.model_validate(scope | quantities)
    else:
        with pytest.raises(ValidationError):
            model.model_validate(scope | quantities)
