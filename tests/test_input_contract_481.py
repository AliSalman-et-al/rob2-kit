from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from support.rob2 import _assessment_workspace, _domain_draft, _domain_submission

from rob2_kit.application._state import _state
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import DomainAnswer, DomainSaveAnswer


def test_public_schema_examples_and_counterevidence_shape_match_the_model() -> None:
    async def inspect() -> tuple[Any, Any]:
        local_tool = next(
            tool for tool in await mcp.list_tools() if tool.name == "save_domain_judgment"
        )
        async with Client(mcp) as client:
            public_tool = next(
                tool for tool in await client.list_tools() if tool.name == "save_domain_judgment"
            )
        return local_tool, public_tool

    local_tool, public_tool = asyncio.run(inspect())
    assert public_tool.input_schema == local_tool.parameters

    schema = public_tool.input_schema
    counterevidence_shape = schema["properties"]["answers"]["items"]["properties"][
        "counterevidence"
    ]["items"]
    assert set(counterevidence_shape["required"]) == {"evidence", "implication"}
    assert counterevidence_shape["properties"]["evidence"]["items"]["type"] == "string"
    assert counterevidence_shape["properties"]["implication"]["type"] == "string"
    answer = DomainSaveAnswer.model_validate(
        {
            "question_id": "sq:randomization:sequence",
            "answer": "probably_no",
            "justification": "The inspected passage challenges this premise.",
            "unknowns": [],
            "bases": [{"role": "context", "evidence": "eh_0123456789abcdef"}],
            "counterevidence": [
                {
                    "evidence": ["eh_0123456789abcdef"],
                    "implication": "The cited passage limits the premise under assessment.",
                }
            ],
        }
    )
    assert answer.counterevidence is not None
    assert answer.counterevidence[0].evidence == ("eh_0123456789abcdef",)
    canonical = DomainAnswer.model_validate(answer.canonical_payload())
    assert canonical.counterevidence is not None
    assert canonical.counterevidence[0].basis_index == 0

    answer_example = schema["properties"]["answers"]["examples"][0][0]
    assert answer_example["counterevidence"] == []


@pytest.mark.parametrize(
    ("shape", "expected_error"),
    [
        ("obsolete_kind", "/answers/0/bases/0/evidence"),
        ("scalar_counterevidence", "/answers/0/counterevidence/0"),
        ("identity_as_handle", "/answers/0/bases/0/evidence"),
        ("array_evidence", "/answers/0/bases/0/evidence"),
        ("array_revision_evidence", "/revision_basis/new_evidence/evidence"),
    ],
)
def test_observed_domain_shapes_fail_at_public_boundary_without_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    expected_error: str,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)

    if shape == "obsolete_kind":
        draft["answers"][0]["bases"] = [
            {
                "kind": "evidence",
                "handle": evidence["handle"],
                "relationship": "direct_support",
            }
        ]
    elif shape == "scalar_counterevidence":
        draft["answers"][0]["counterevidence"] = [0]
    elif shape == "identity_as_handle":
        draft["answers"][0]["bases"][0]["evidence"] = evidence["identity"]
    elif shape == "array_evidence":
        draft["answers"][0]["bases"][0]["evidence"] = [evidence["handle"]]
    else:
        draft["supersedes"] = "sha256:" + "0" * 64
        draft["revision_basis"] = {
            "kind": "new_evidence",
            "evidence": [evidence["handle"]],
            "rationale": "A newly inspected passage changes the interpretation.",
        }

    before = deepcopy(_state(workspace))

    async def invoke() -> Any:
        async with Client(mcp) as client:
            return await client.call_tool(
                "save_domain_judgment", _domain_submission(draft), raise_on_error=False
            )

    result = asyncio.run(invoke())
    error = result.content[0].text
    assert result.is_error is True
    assert result.structured_content is None
    assert expected_error in error
    assert _state(workspace) == before


def test_obsolete_proposal_discriminator_fails_at_public_boundary_without_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _evidence, _revision = _assessment_workspace(tmp_path)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    before = deepcopy(_state(workspace))

    async def invoke() -> Any:
        async with Client(mcp) as client:
            return await client.call_tool(
                "validate_proposal",
                {
                    "results": [{"kind": "binary"}],
                    "assessments": [{"trial_id": "trial", "unknowns": []}],
                    "expected_revision": before["revision"],
                },
                raise_on_error=False,
            )

    result = asyncio.run(invoke())
    error = result.content[0].text
    assert result.is_error is True
    assert result.structured_content is None
    assert "invalid_proposal_arguments" in error
    assert _state(workspace) == before
