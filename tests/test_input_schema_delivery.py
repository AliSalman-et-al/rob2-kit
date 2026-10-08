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
from rob2_kit.interfaces.mcp.server import _construction_schema, mcp
from rob2_kit.workflow_models import (
    DomainEvidenceCitation,
    DomainSaveAnswer,
    MissingDataRow,
    MissingDataSemantics,
)


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
        "question_id",
        "answer",
        "justification",
        "unknowns",
        "counterevidence",
    }
    row = answer["properties"]["missing_data"]["anyOf"][0]["items"]
    semantics = row["properties"]["semantics"]["anyOf"][0]
    for model, advertised in ((MissingDataRow, row), (MissingDataSemantics, semantics)):
        repair = _construction_schema(model)
        for branch in ("if", "then"):
            for field, schema in advertised[branch]["properties"].items():
                assert schema["description"]
                assert {k: v for k, v in schema.items() if k != "description"} == (
                    repair[branch]["properties"][field]
                )
        assert (
            {**advertised["if"], "properties": repair["if"]["properties"]}
            == repair["if"]
            == {
                "required": ["event_count"],
                "properties": {
                    "event_count": {
                        "type": "integer",
                    }
                },
            }
        )
        assert (
            {**advertised["then"], "properties": repair["then"]["properties"]}
            == repair["then"]
            == {
                "required": ["event_definition"],
                "properties": {
                    "event_definition": {
                        "type": "string",
                        "minLength": 1,
                    }
                },
            }
        )
        assert (
            "Required when event_count is supplied"
            in advertised["properties"]["event_definition"]["description"]
        )
    assert answer["additionalProperties"] is False
    variants = answer["properties"]["bases"]["items"]["anyOf"]
    assert any(item.get("type") == "string" for item in variants)
    citation = next(item for item in variants if "evidence" in item.get("properties", {}))
    shortcut = next(item for item in variants if "step_identity" in item.get("properties", {}))
    assert set(shortcut["required"]) == {"step_identity", "role"}
    assert set(shortcut["properties"]) == {"step_identity", "role", "transfer"}
    assert shortcut["additionalProperties"] is False
    assert set(citation["required"]) == {"evidence", "role"}
    references = citation["properties"]["evidence"]["anyOf"]
    assert references[0]["type"] == "string"
    objects = [item for item in references if item.get("type") == "object"]
    assert {frozenset(item["required"]) for item in objects} == {
        frozenset({"source_id", "page", "start_line", "end_line"}),
        frozenset({"delivery_receipt", "transcription"}),
        frozenset({"source_id", "page", "selected_text"}),
    }
    visual = next(item for item in objects if "delivery_receipt" in item["properties"])
    region = visual["properties"]["region"]
    assert region["default"] is None
    bounds = next(item for item in region["anyOf"] if item["type"] == "array")
    assert bounds["minItems"] == bounds["maxItems"] == 4
    assert all(item["additionalProperties"] is False for item in objects)
    assert citation["additionalProperties"] is False
    point = answer["properties"]["counterevidence"]["items"]
    assert point["properties"]["evidence"]["type"] == "array"
    assert set(point["required"]) == {"evidence", "implication"}
    assert set(answer["properties"]["answer"]["enum"]) == {
        "yes",
        "probably_yes",
        "probably_no",
        "no",
        "no_information",
    }


@pytest.mark.parametrize(
    "failure", ["wrong_names", "handle_list", "missing_data", "event_definition"]
)
def test_argument_error_supplies_correct_shape_without_saving_or_coercing(
    tmp_path: Path, failure: str
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_submission(_domain_draft("trial", "domain:randomization", revision, evidence))
    basis = draft["answers"][0]["bases"][0]
    if failure == "wrong_names":
        draft["answers"][0]["bases"][0] = {
            "evidence_handle": basis["evidence"],
            "relationship": basis["role"],
        }
    elif failure == "handle_list":
        basis["evidence"] = [basis["evidence"]]
    else:
        draft["answers"][0]["missing_data"] = [
            {
                "arm": "trial arm",
                "population": "randomized participants",
                "unit": "participants",
                "time_point": "follow-up",
                "randomized": 100,
                "observed": 80,
                "outcome_status": "unknown",
                "population_role": "randomized",
                "post_randomization_exclusions": [],
            }
        ]
    if failure == "event_definition":
        draft["answers"][0]["missing_data"][0] = {
            "arm": "trial arm",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "follow-up",
            "event_count": 3,
        }
    before = _state(workspace)

    async def call():
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            return await client.call_tool("save_domain_judgment", draft, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    assert "invalid_tool_arguments" in text
    if failure in {"missing_data", "event_definition"}:
        if failure == "missing_data":
            assert "/answers/0/missing_data/0/outcome_status" in text
        else:
            assert "event_count requires event_definition" in text
        recovery = json.loads(text.split(" Argument recovery: ", 1)[1])
        row_schema = recovery["missing_data_row_schema"]
        assert row_schema["then"]["required"] == ["event_definition"]
        assert row_schema["additionalProperties"] is False
        assert {"arm", "population", "unit", "time_point"} <= set(row_schema["required"])
        assert not {"outcome_status", "population_role", "post_randomization_exclusions"} & set(
            row_schema["properties"]
        )
        assert {"semantics", "exclusions", "observed"} <= set(row_schema["properties"])
    else:
        assert "/answers/0/bases/0/evidence" in text
    assert "errors.pydantic.dev" not in text
    example_text = text.split("real Evidence): ", 1)[1].split(" bases[].evidence", 1)[0]
    example = DomainSaveAnswer.model_validate(json.loads(example_text))
    assert isinstance(example.bases[0], DomainEvidenceCitation)
    assert isinstance(example.bases[0].evidence, str)
    assert "counterevidence[].evidence is a nonempty handle list" in text
    assert _state(workspace) == before


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


def test_malformed_account_citation_reports_public_role_path_without_committing(tmp_path: Path):
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_submission(_domain_draft("trial", "domain:randomization", revision, evidence))
    draft["answers"][0]["bases"] = [{"step_identity": "sha256:" + "a" * 64, "role": "unknown"}]
    before = _state(workspace)

    async def call():
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            return await client.call_tool("save_domain_judgment", draft, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    assert "/answers/0/bases/0/role" in text
    assert "DomainAccountStepCitation" not in text
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
