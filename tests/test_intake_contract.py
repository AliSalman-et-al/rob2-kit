from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from support.rob2 import (
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.contracts import TOOL_NAMES
from rob2_kit.application.domains import get_domain_context
from rob2_kit.application.status import presentation
from rob2_kit.interfaces.mcp.contracts import (
    ResearcherReviewAction,
    SelectedNarrativeEvidence,
    normalize,
    output_schema,
    validate_output,
)
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.models import sha256


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


def test_domain_context_preserves_nullable_endpoint_definition_in_receipt(tmp_path: Path) -> None:
    """Required nullable endpoint definitions survive public receipt serialization."""

    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["endpoint"]["definition"] = None
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    _review(workspace)

    raw = get_domain_context(workspace, "trial", "domain:randomization")
    receipt = normalize("get_domain_context", raw)
    assert receipt["data"]["result"]["reported"]["endpoint"]["definition"] is None
    assert "current_checkpoint" not in receipt["data"]
    assert validate_output("get_domain_context", receipt) == receipt


def _prepare_schema() -> dict[str, object]:
    async def read_schema() -> dict[str, object]:
        async with Client(mcp) as client:
            tool = next(item for item in await client.list_tools() if item.name == "prepare_batch")
            return dict(tool.input_schema)

    return asyncio.run(read_schema())


def _tool_schema(name: str) -> dict[str, Any]:
    async def read_schema() -> dict[str, Any]:
        async with Client(mcp) as client:
            tool = next(item for item in await client.list_tools() if item.name == name)
            return dict(tool.input_schema)

    return asyncio.run(read_schema())


def _tool_description(name: str) -> str:
    async def read_description() -> str:
        async with Client(mcp) as client:
            tool = next(item for item in await client.list_tools() if item.name == name)
            return str(tool.description)

    return asyncio.run(read_description())


def _tool_output_schema(name: str) -> dict[str, Any]:
    async def read_schema() -> dict[str, Any]:
        async with Client(mcp) as client:
            tool = next(item for item in await client.list_tools() if item.name == name)
            return dict(tool.output_schema)

    return asyncio.run(read_schema())


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


def test_every_public_tool_publishes_closed_input_and_output_schemas() -> None:
    async def read_tools() -> list[Any]:
        async with Client(mcp) as client:
            return list(await client.list_tools())

    tools = asyncio.run(read_tools())
    assert [tool.name for tool in tools] == list(TOOL_NAMES)
    for tool in tools:
        assert tool.input_schema
        assert tool.output_schema
        for schema in (tool.input_schema, tool.output_schema):
            for path, obj in _walk_schema(schema):
                # Deliberate server-owned maps, such as trial dispositions, have
                # no named properties. Every modeled object remains closed.
                if "properties" in obj:
                    assert obj.get("additionalProperties") is False, path
            arrays: list[dict[str, Any]] = []

            def collect(value: object) -> None:
                if not isinstance(value, dict):
                    return
                if value.get("type") == "array":
                    arrays.append(cast(dict[str, Any], value))
                for child in value.values():
                    if isinstance(child, dict):
                        collect(child)
                    elif isinstance(child, list):
                        for item in child:
                            collect(item)

            collect(schema)
        assert all("items" in array or "prefixItems" in array for array in arrays)
        output = cast(dict[str, Any], tool.output_schema)
        assert output["type"] == "object"
        expected_outcomes = {
            "get_status": 2,
            "list_sources": 2,
            "search_sources": 2,
            "read_pages": 2,
            "select_text_evidence": 2,
            "render_page": 2,
            "select_visual_evidence": 2,
            "get_domain_context": 2,
            "prepare_batch": 3,
            "save_proposal": 5,
            "request_proposal_approval": 2,
            "save_domain_judgment": 4,
            "request_trial_terminal": 3,
            "finalize_batch": 3,
        }
        assert len(output["oneOf"]) == expected_outcomes[tool.name]
        for variant in output["oneOf"]:
            definition = variant
            if "$ref" in definition:
                reference = str(definition["$ref"]).removeprefix("#/$defs/")
                definition = output["$defs"][reference]
            assert set(("outcome", "head")) <= set(definition["required"])


def test_finalize_output_schema_requires_typed_assessment_summary() -> None:
    schema = output_schema("finalize_batch")
    definitions = cast(dict[str, Any], schema["$defs"])
    finalize = definitions["FinalizeData"]
    assert "assessment_summary" in finalize["required"]
    summary = definitions["AssessmentSummary"]
    assert summary["required"] == ["overall", "domains"]
    assert summary["properties"]["domains"]["minProperties"] == 5
    assert summary["properties"]["domains"]["maxProperties"] == 5
    assert summary["properties"]["domains"]["propertyNames"]["enum"] == [
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    ]


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


def test_prepare_batch_schema_is_closed_and_requires_outcome_request() -> None:
    schema = cast(dict[str, Any], _prepare_schema())
    assert schema["required"] == ["requested_outcome", "expected_revision"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "requested_outcome",
        "expected_revision",
        "trial_labels",
    }
    assert schema["properties"]["requested_outcome"]["type"] == "string"
    outcome_description = schema["properties"]["requested_outcome"]["description"]
    assert all(
        excluded in outcome_description
        for excluded in ("Trial names", "population", "comparison", "effect estimate")
    )
    trial_labels = schema["properties"]["trial_labels"]
    array_schema = next(item for item in trial_labels["anyOf"] if item.get("type") == "array")
    assert array_schema["minItems"] == 1
    assert array_schema["items"]["type"] == "string"
    assert array_schema["items"]["minLength"] == 1
    assert array_schema["items"]["description"]


def test_prepare_batch_discovers_server_owned_input_trial_directory(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "Trial A"
    trial.mkdir(parents=True)
    (trial / "trial-a.pdf").write_bytes(b"%PDF-1.4\n")

    async def prepare() -> dict[str, object]:
        os.environ["ROB2_WORKSPACE"] = str(tmp_path)
        async with Client(mcp) as client:
            result = await client.call_tool(
                "prepare_batch",
                {
                    "requested_outcome": "a requested outcome",
                    "expected_revision": 0,
                },
            )
            return dict(result.structured_content or {})

    result = cast(dict[str, Any], asyncio.run(prepare()))
    assert result["outcome"] in {"success", "review_required"}
    captured = cast(list[dict[str, Any]], result["data"]["trials"])
    assert captured[0]["id"] == "trial-a"
    assert captured[0]["label"] == "Trial A"
    assert captured[0]["requested_outcome"] == "a requested outcome"


def test_prepare_batch_discovers_multiple_trials_deterministically(tmp_path: Path) -> None:
    for name in ("Zeta Trial", "Alpha Trial"):
        trial = tmp_path / "input" / name
        trial.mkdir(parents=True)
        (trial / "main.txt").write_text(name, encoding="utf-8")

    result = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "overall survival", "expected_revision": 0},
    )
    assert [trial["id"] for trial in result["data"]["trials"]] == [
        "alpha-trial",
        "zeta-trial",
    ]
    assert [trial["label"] for trial in result["data"]["trials"]] == [
        "Alpha Trial",
        "Zeta Trial",
    ]
    assert {trial["requested_outcome"] for trial in result["data"]["trials"]} == {
        "overall survival"
    }


def test_prepare_batch_scopes_exact_trial_labels_in_directory_order(tmp_path: Path) -> None:
    for name in ("PEACE-1", "TITAN", "STAMPEDE"):
        trial = tmp_path / "input" / name
        trial.mkdir(parents=True)
        (trial / "main.txt").write_text(name, encoding="utf-8")

    result = _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "overall survival",
            "trial_labels": ["TITAN", "STAMPEDE"],
            "expected_revision": 0,
        },
    )

    assert [trial["label"] for trial in result["data"]["trials"]] == ["STAMPEDE", "TITAN"]


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


def test_prepare_batch_retries_subset_idempotently_when_label_order_changes(tmp_path: Path) -> None:
    for name in ("Trial A", "Trial B", "Trial C"):
        (tmp_path / "input" / name).mkdir(parents=True)

    first = _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "trial_labels": ["Trial B", "Trial A"],
            "expected_revision": 0,
        },
    )
    retry = _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "trial_labels": ["Trial A", "Trial B"],
            "expected_revision": first["head"]["state_revision"],
        },
    )

    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True
    assert retry["data"]["batch_identity"] == first["data"]["batch_identity"]


def test_prepare_batch_rejects_empty_trial_directory_set(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    result = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "overall survival", "expected_revision": 0},
    )
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "invalid_request"


def test_prepare_batch_retries_idempotently_from_discovered_directories(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "Trial A"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("source", encoding="utf-8")
    first = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "overall survival", "expected_revision": 0},
    )
    second = _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "overall survival",
            "expected_revision": first["head"]["state_revision"],
        },
    )
    assert second["outcome"] == "success"
    assert second["data"]["retry"] is True
    assert second["data"]["batch_identity"] == first["data"]["batch_identity"]


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


def test_receipt_head_uses_authoritative_post_operation_status(tmp_path: Path) -> None:
    (tmp_path / "input" / "trial").mkdir(parents=True)
    (tmp_path / "input" / "trial" / "main.txt").write_text("requested", encoding="utf-8")

    async def exercise() -> tuple[dict[str, Any], dict[str, Any]]:
        os.environ["ROB2_WORKSPACE"] = str(tmp_path)
        async with Client(mcp) as client:
            empty = dict((await client.call_tool("get_status", {})).structured_content or {})
            prepared = dict(
                (
                    await client.call_tool(
                        "prepare_batch",
                        {
                            "requested_outcome": "requested outcome",
                            "expected_revision": 0,
                        },
                    )
                ).structured_content
                or {}
            )
            return empty, prepared

    empty, prepared = asyncio.run(exercise())
    assert empty["head"]["next_action"] == {
        "operation": "prepare_batch",
        "authority": "host",
        "expected_revision": 0,
        "caller_inputs": ["requested_outcome", "trial_labels"],
    }
    assert prepared["head"]["phase"] == "proposal"
    assert prepared["head"]["next_action"] == {
        "operation": "save_proposal",
        "authority": "host",
        "expected_revision": prepared["head"]["state_revision"],
        "caller_inputs": ["results"],
    }


def test_next_action_is_operation_discriminated_and_closed() -> None:
    schema = output_schema("get_status")
    definitions = cast(dict[str, Any], schema["$defs"])
    head = definitions["PublicHead"]
    next_action = cast(dict[str, Any], head["properties"]["next_action"])["anyOf"][0]
    assert next_action["discriminator"] == {
        "mapping": {
            "prepare_batch": "#/$defs/PrepareBatchAction",
            "save_proposal": "#/$defs/SaveProposalAction",
            "get_domain_context": "#/$defs/GetDomainContextAction",
            "save_domain_judgment": "#/$defs/SaveDomainJudgmentAction",
            "finalize_batch": "#/$defs/FinalizeBatchAction",
            "researcher_review": "#/$defs/ResearcherReviewAction",
        },
        "propertyName": "operation",
    }
    for name in (
        "SaveProposalAction",
        "PrepareBatchAction",
        "GetDomainContextAction",
        "SaveDomainJudgmentAction",
        "FinalizeBatchAction",
        "ResearcherReviewAction",
    ):
        assert definitions[name]["additionalProperties"] is False

    with pytest.raises(ValidationError):
        validate_output(
            "get_status",
            {
                "outcome": "success",
                "head": {
                    "phase": "proposal",
                    "state_revision": 4,
                    "next_action": {
                        "operation": "invented_tool",
                        "authority": "host",
                    },
                    "authoritative_wording": "continue",
                },
                "data": {
                    "trial_dispositions": {},
                    "terminal_counts": {
                        "assessed": 0,
                        "needs_input": 0,
                        "failed": 0,
                        "pending": 0,
                    },
                    "review_required": False,
                    "authority_required": "host",
                    "selected_evidence": [],
                    "counters": {
                        "extraction_calls": 0,
                        "derivative_rebuilds": 0,
                        "source_projection_verifications": 0,
                        "database_queries": 0,
                        "serialized_bytes": 0,
                        "render_bytes": 0,
                        "elapsed_ms": 0,
                    },
                },
            },
        )


def test_status_counts_a_completed_trial_before_batch_finalization() -> None:
    status = presentation(
        {
            "phase": "assessment",
            "trial_dispositions": {"trial-a": "assessed", "trial-b": "pending"},
        }
    )
    assert status["counts"] == {
        "assessed": 1,
        "needs_input": 0,
        "failed": 0,
        "pending": 1,
    }
    assert status["wording"] == (
        "Batch incomplete: 1/2 Trials completed; 1 pending. Continue now with head.next_action. "
        "Never stop at a Trial boundary, ask whether to continue, infer pending Trial "
        "judgments, or reduce rigor for token or context limits."
    )


def test_status_keeps_incomplete_batch_authoritative_until_finalization() -> None:
    status = presentation(
        {
            "phase": "ready_to_finalize",
            "trial_dispositions": {"trial-a": "assessed", "trial-b": "needs_input"},
        }
    )
    assert status["wording"] == (
        "Batch incomplete. Continue now with head.next_action to finalize the Batch. Never stop, "
        "summarize, or ask whether to continue before finalization."
    )


def test_assessment_skill_spells_out_intake_mapping() -> None:
    skill = Path(__file__).parents[1] / "src/rob2_kit/skills/rob2-assess/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert '"requested_outcome":"a requested outcome","expected_revision":0' in text
    assert "Assess risk of bias for a requested outcome in Trial A" in text
    assert '"trial_labels":["Trial A"]' in text
    assert "across Trial A and Trial B" in text
    assert '"trial_labels":["Trial A","Trial B"]' in text
    assert "captured Trial labels match the requested scope" in normalized


def test_assessment_skill_preserves_result_choice_and_completion_guards() -> None:
    root = Path(__file__).parents[1] / "src/rob2_kit/skills/rob2-assess"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    result = (root / "references/result.md").read_text(encoding="utf-8")
    missing = (root / "references/missing.md").read_text(encoding="utf-8")
    randomization = (root / "references/randomization.md").read_text(encoding="utf-8")
    read_main = (root / "references/read-main-report.md").read_text(encoding="utf-8")
    selection = (root / "references/selection.md").read_text(encoding="utf-8")
    instructions = " ".join(
        (skill + result + missing + randomization + read_main + selection).split()
    )

    assert "an exact assessable Result" in instructions
    assert "closest complete non-exact assessable candidate or profile" in instructions
    assert "unavailable Result only when no complete assessable candidate exists" in instructions
    assert "Missing comparator values do not make" in instructions
    assert "single_group_category_profile" in instructions
    assert "Never invent comparator cells" in instructions
    for comparison in (
        "event set",
        "time origin or window",
        "population",
        "measurement",
        "state criteria",
    ):
        assert comparison in instructions
    assert "fewest added criteria" in instructions
    assert "materially competing candidates" in instructions
    assert "Matching numbers do not prove equivalent endpoints" in instructions
    assert "clinical salience" in instructions
    assert "abstract accessibility" in instructions
    assert "do not read every Source mechanically" in instructions
    assert "Proposal Review is the only researcher gate" in instructions
    assert "continue without asking" in instructions
    assert "request_proposal_approval` with the empty arguments object `{}`" in instructions
    assert "data.remaining_windows" in instructions
    assert "Draft an answer for every question returned for the Domain" in instructions
    assert "including questions whose `active` flag is currently false" in instructions
    assert "For 5.3, identify both the eligible alternatives" in instructions
    assert '"kind": "quantified"' in instructions
    assert '"15 days after randomization"' in instructions
    assert "fifth accepted checkpoint freezes the Trial snapshot" in instructions
    assert "`ready_to_finalize` is not completion" in instructions
    assert "`probably_no` or `no`" in instructions
    assert "Do not fabricate direct support" in instructions
    assert "Choose the option whose literal meaning follows from those passages" in instructions
    assert "progress confirmation" in instructions
    assert "Was allocation concealed until participants were enrolled and assigned?" in instructions

    terminal_description = _tool_description("request_trial_terminal")
    assert "missing direct evidence" in terminal_description.lower()
    assert "unfinished source review" in terminal_description
    assert "probably_yes" in terminal_description


def test_assessment_skill_preserves_rigor_across_context_compaction() -> None:
    skill = Path(__file__).parents[1] / "src/rob2_kit/skills/rob2-assess/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "After a restart or context compaction, call `get_status`" in normalized
    assert "before any other workflow call" in normalized
    assert "resume its exact next action" in normalized
    assert "Use `get_domain_context` to restore Domain Evidence" in normalized
    assert "Do not recreate completed work from memory" in normalized
    assert "Save each Domain before moving on" in normalized
    assert "fifth accepted checkpoint freezes the Trial snapshot" in normalized
    assert (
        "When `head.next_action.operation` is `finalize_batch`, call it immediately" in normalized
    )


def test_result_relation_schema_has_only_visible_non_exact_categories() -> None:
    schema = _tool_schema("save_proposal")
    result_items = cast(dict[str, Any], schema["properties"]["results"]["items"])
    assessable = cast(dict[str, Any], result_items["oneOf"][0])
    relation = cast(dict[str, Any], assessable["properties"]["relation"])
    assert relation["enum"] == ["exact", "broader", "narrower", "component", "related"]
    relation_description = cast(dict[str, Any], assessable["properties"]["relation"])["description"]
    assert "event set" in relation_description
    assert "scope is a superset" in relation_description
    assert "subset or has additional restrictions" in relation_description
    assert "Added criteria make a candidate narrower" in relation_description
    assert "matching numbers do not prove equivalence" in relation_description
    assert "alternatives" not in relation_description
    assert "clinical salience" in result_items["description"]
    assert "complete non-exact candidate" in result_items["description"]
    assert "broader is a superset" in result_items["description"]
    assert "subset or has additional restrictions" in result_items["description"]
    results_description = cast(dict[str, Any], schema["properties"]["results"])["description"]
    assert "Initial save" in results_description
    assert "unmentioned cards are preserved" in results_description
    assert "Select Evidence first" in results_description
    tool_description = _tool_description("save_proposal")
    assert "supporting Evidence" in tool_description
    assert "source numbers as strings" in tool_description


def test_search_contract_exposes_match_summary_and_render_defaults_to_pixels() -> None:
    search_schema = _tool_output_schema("search_sources")
    data_objects = [
        schema
        for _, schema in _walk_schema(search_schema)
        if {"hits", "total_matches", "truncated"}.issubset(schema.get("properties", {}))
    ]
    assert data_objects
    assert "total_matches" in data_objects[0]["properties"]
    assert "truncated" in data_objects[0]["properties"]
    assert set(data_objects[0]["properties"]) == {
        "hits",
        "query",
        "mode",
        "total_matches",
        "truncated",
        "condition",
        "search_receipt",
        "session_id",
        "session_handle",
        "matching_page_count",
        "candidate_count",
        "ranking_complete",
        "returned_rank_start",
        "returned_rank_end",
        "next_cursor",
        "exhausted",
        "diagnostic",
    }
    hit_schema = data_objects[0]["properties"]["hits"]["items"]
    assert set(hit_schema["properties"]) == {
        "source_id",
        "source_role",
        "source_label",
        "page",
        "start_line",
        "end_line",
        "preview",
        "passage_ref",
        "rank",
        "within_source_rank",
        "range",
    }
    assert data_objects[0]["properties"]["search_receipt"]["pattern"] == r"^sr_[0-9a-f]{16}$"
    search_description = _tool_description("search_sources")
    assert "counts" in search_description
    assert "broad truncated any" in search_description.lower()
    render_schema = _tool_schema("render_page")
    assert render_schema["properties"]["inline"]["default"] is True
    assert "pixels as ImageContent by default" in _tool_description("render_page")
    assert "inline=false" in _tool_description("render_page")
    visual_description = _tool_description("select_visual_evidence")
    assert "self-contained" in visual_description
    assert "footnote" in visual_description
    region_description = _tool_schema("select_visual_evidence")["properties"]["region"][
        "description"
    ]
    assert "Normalized" in region_description


def test_save_proposal_schema_is_closed_and_discriminated() -> None:
    schema = _tool_schema("save_proposal")
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["results", "expected_revision"]
    assert "proposal" not in schema["properties"]
    assert "expected_revision" in schema["properties"]
    result_items = cast(dict[str, Any], schema["properties"]["results"]["items"])
    assert "exact assessable first" in result_items["description"]
    assert "Missing comparator values" in result_items["description"]
    assert [item["properties"]["kind"]["const"] for item in result_items["oneOf"]] == [
        "assessable",
        "unavailable",
    ]
    assessable = cast(dict[str, Any], result_items["oneOf"][0])
    reported = cast(dict[str, Any], assessable["properties"]["reported"])
    category_profile = next(
        item
        for item in reported["oneOf"]
        if item["properties"]["form"]["const"] == "single_group_category_profile"
    )
    assert "fully reports category cells" in category_profile["description"]
    assert "denominator_basis" in category_profile["properties"]
    assert "statistic" not in category_profile["properties"]
    assert "unit" not in category_profile["properties"]
    category_value = cast(dict[str, Any], category_profile["properties"]["categories"]["items"])
    assert "categories must never be invented" in category_value["description"]
    assert set(category_value["properties"]) == {"category_axes", "value"}
    unavailable = cast(dict[str, Any], result_items["oneOf"][1])
    assert "only when no complete assessable candidate" in unavailable["description"]
    assert "bindings" not in assessable["properties"]
    assert "clarity" not in assessable["properties"]
    assert "alternatives" not in assessable["properties"]
    assert "evidence" not in assessable["properties"]
    assert "relation_rationale" in assessable["required"]
    target = cast(dict[str, Any], assessable["properties"]["target"])
    assert "effect_of_interest" not in target["properties"]
    assert "outcome_definition" not in target["properties"]
    measurement = cast(dict[str, Any], target["properties"]["measurement"])
    assert measurement["required"] == ["method"]
    assert "baseline_subgroup" in target["properties"]
    assert "baseline_subgroup" in target["required"]
    assert "intended_analysis_population" not in target["properties"]
    timing = cast(dict[str, Any], target["properties"]["time_point_or_window"])
    assert [item["properties"]["kind"]["const"] for item in timing["oneOf"]] == [
        "described",
        "quantified",
    ]
    quantified = next(
        item for item in timing["oneOf"] if item["properties"]["kind"]["const"] == "quantified"
    )
    timing_description = quantified["properties"]["description"]["description"]
    assert "for example, '15 days after randomization'" in timing_description
    assert "alongside value and unit" in timing_description
    comparison_group = target["properties"]["comparison_groups"]["items"]
    assert "label" not in comparison_group["properties"]
    assert "assignment" in comparison_group["properties"]
    comparative_variant = next(
        item
        for item in reported["oneOf"]
        if item["properties"]["form"]["const"] == "comparative_effect"
    )
    comparative = comparative_variant["properties"]
    assert "endpoint" in comparative
    endpoint = comparative["endpoint"]
    assert endpoint["required"] == ["name"]
    assert endpoint["properties"]["definition"]["default"] is None
    assert "group_values" in comparative
    assert "quantities" not in comparative
    assert "comparison_groups" not in comparative
    assert "analysis_population" in comparative_variant["required"]
    assert "analysis_population" in comparative
    for form in reported["oneOf"]:
        assert "analysis_population" in form["required"]
    for name, definition in _walk_schema(schema):
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False, name
    # Every nested caller field is self-describing; keep the complete proposal
    # schema, including design applicability, compact enough for one definition.
    assert len(json.dumps(schema, separators=(",", ":")).encode()) < 16500
    assert len(_walk_schema(schema)) <= 22


def test_save_domain_judgment_schema_is_closed_and_typed() -> None:
    schema = _tool_schema("save_domain_judgment")
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["trial_id", "domain_id", "expected_revision", "answers"]
    draft = schema
    assert draft["additionalProperties"] is False
    assert "multiple_concerns" in draft["properties"]
    assert draft["required"] == [
        "trial_id",
        "domain_id",
        "expected_revision",
        "answers",
    ]
    answers = cast(dict[str, Any], draft["properties"]["answers"])["items"]
    assert answers["additionalProperties"] is False
    assert set(answers["properties"]) == {
        "question_id",
        "option_id",
        "bases",
        "justification",
        "missing_data",
    }
    variants = cast(dict[str, Any], answers["properties"]["bases"]["items"])["oneOf"]
    assert len(variants) == 3
    assert all(variant["additionalProperties"] is False for variant in variants)
    kinds = {
        variant["properties"]["kind"].get("const") or variant["properties"]["kind"]["enum"][0]
        for variant in variants
    }
    assert kinds == {
        "direct_support",
        "absence",
        "limitation",
    }


def test_selected_evidence_and_typed_proposal_survive_host_restart(tmp_path: Path) -> None:
    quote = (
        "requested outcome; death ascertainment; follow-up; assigned intervention; "
        "assigned control; randomized population; risk ratio; reported endpoint; "
        "measured endpoint definition; risk; 1; events; 2"
    )
    (tmp_path / "input" / "trial").mkdir(parents=True)
    (tmp_path / "input" / "trial" / "main.txt").write_text(quote, encoding="utf-8")

    prepared = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    assert prepared["head"]["phase"] == "proposal"
    _read_required_main_reports(tmp_path)
    source = _call(tmp_path, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    selected = _call(
        tmp_path,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]

    # A new Client invocation stands in for a fresh host process.  The only
    # material it needs from the old process is the bounded selection record.
    resumed = _call(tmp_path, "get_status", {})
    recovered = next(
        item
        for item in resumed["data"]["selected_evidence"]
        if item["handle"] == selected["handle"]
    )
    assert recovered["quote"] == quote
    target = {
        "measurement": {"method": "death ascertainment"},
        "time_point_or_window": {"kind": "described", "description": "follow-up"},
        "comparison_groups": [
            {"id": "A", "assignment": "assigned intervention"},
            {"id": "B", "assignment": "assigned control"},
        ],
        "baseline_subgroup": None,
        "intended_effect_measure": "risk ratio",
    }
    reported = {
        "form": "group_bound_values",
        "analysis_population": "randomized population",
        "endpoint": {
            "name": "reported endpoint",
            "definition": "measured endpoint definition",
        },
        "values": [
            {"group_id": "A", "statistic": "risk", "value": "1", "unit": "events"},
            {"group_id": "B", "statistic": "risk", "value": "2", "unit": "events"},
        ],
    }
    result = {
        "kind": "assessable",
        "trial_id": "trial",
        "relation": "related",
        "relation_rationale": ("Related endpoints use different captured names and definitions."),
        "applicability": {
            "design": "individual_parallel",
            "rationale": (
                "The captured allocation describes an individually randomized parallel comparison."
            ),
            "evidence": [selected["handle"]],
        },
        "target": target,
        "reported": reported,
    }
    saved = _call(
        tmp_path,
        "save_proposal",
        {"results": [result], "expected_revision": resumed["head"]["state_revision"]},
    )
    assert saved["outcome"] == "review_required"
    assert saved["head"]["next_action"]["operation"] == "researcher_review"
    assert saved["head"]["next_action"]["purpose"] == "proposal"
    canonical = _state(tmp_path)["proposal"]["payload"]
    canonical_result = canonical["results"][0]
    expected_digests = {
        path: sha256(value)
        for path, value in {
            **_leaves(canonical_result["target"], "/target"),
            **_leaves(canonical_result["reported"], "/reported"),
        }.items()
    }
    assert all(
        binding["value_digest"] == expected_digests[binding["field"]["path"]]
        for binding in canonical_result["bindings"]
    )
    caller_owned = {
        "/target/outcome_definition",
        "/target/measurement/metric",
        "/target/effect_of_interest",
        "/target/measurement/method",
        "/target/intended_analysis_population",
        "/target/intended_effect_measure",
        "/target/time_point_or_window/description",
        "/target/comparison_groups/0/id",
        "/target/comparison_groups/0/assignment",
        "/target/comparison_groups/1/id",
        "/target/comparison_groups/1/assignment",
        "/reported/analysis_population",
        "/reported/values/0/group_id",
        "/reported/values/1/group_id",
    }
    assert {binding["field"]["path"] for binding in canonical_result["bindings"]} == (
        set(expected_digests) - caller_owned
    )


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
