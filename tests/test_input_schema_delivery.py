"""Clients must see and be able to repair the actual closed argument shape."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from support.rob2 import _assessment_workspace, _domain_draft, _domain_submission

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import DomainSaveAnswer


def _has_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_has_ref(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_ref(child) for child in value)
    return False


def test_wire_input_fields_are_self_contained_while_outputs_stay_shared() -> None:
    async def inspect():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(inspect())
    assert all(not _has_ref(tool.input_schema) for tool in tools)
    assert any(_has_ref(tool.output_schema) for tool in tools)
    save = next(tool for tool in tools if tool.name == "save_domain_judgment")
    answer = save.input_schema["properties"]["answers"]["items"]
    assert set(answer["required"]) == {
        "question_id", "answer", "justification", "unknowns", "counterevidence"
    }
    assert answer["additionalProperties"] is False
    citation = answer["properties"]["bases"]["items"]
    assert set(citation["required"]) == {"evidence", "role"}
    assert citation["properties"]["evidence"]["type"] == "string"
    assert citation["additionalProperties"] is False
    point = answer["properties"]["counterevidence"]["items"]
    assert point["properties"]["evidence"]["type"] == "array"
    assert set(point["required"]) == {"evidence", "implication"}
    assert set(answer["properties"]["answer"]["enum"]) == {
        "yes", "probably_yes", "probably_no", "no", "no_information"
    }


@pytest.mark.parametrize("failure", ["wrong_names", "handle_list"])
def test_argument_error_supplies_correct_shape_without_saving_or_coercing(
    tmp_path: Path, failure: str
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_submission(_domain_draft("trial", "domain:randomization", revision, evidence))
    basis = draft["answers"][0]["bases"][0]
    if failure == "wrong_names":
        draft["answers"][0]["bases"][0] = {
            "evidence_handle": basis["evidence"], "relationship": basis["role"]
        }
    else:
        basis["evidence"] = [basis["evidence"]]
    before = _state(workspace)

    async def call():
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            return await client.call_tool("save_domain_judgment", draft, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    assert "invalid_tool_arguments" in text
    assert "/answers/0/bases/0/evidence" in text
    assert "errors.pydantic.dev" not in text
    example_text = text.split("real Evidence): ", 1)[1].split(" bases[].evidence", 1)[0]
    example = DomainSaveAnswer.model_validate(json.loads(example_text))
    assert isinstance(example.bases[0].evidence, str)
    assert "counterevidence[].evidence is a nonempty handle list" in text
    assert _state(workspace) == before
