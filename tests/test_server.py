import asyncio
from pathlib import Path
from typing import Any

import pymupdf
from fastmcp import Client

from rob2_kit.assessment import (
    Arm,
    BatchRequest,
    Comparison,
    OutcomeTarget,
    Proposal,
    Randomization,
    ResultAnchor,
    ResultSpec,
    Trial,
)
from rob2_kit.batch import ApproveBatchResult, SaveProposalResult
from rob2_kit.ingestion import ingest_batch
from rob2_kit.server import mcp
from rob2_kit.sources import SourceInput, SourceRole, TrialInput


def _pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "anchor")
    document.save(path)
    document.close()


def _proposal(workspace: Path) -> Proposal:
    _pdf(workspace / "main.pdf")
    input_source = SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main")
    source = (
        ingest_batch(workspace, (TrialInput(id="trial", label="Trial", sources=(input_source,)),))
        .trials[0]
        .sources[0]
    )
    return Proposal(
        request=BatchRequest(
            outcome_target=OutcomeTarget(id="outcome", label="Outcome", description="Description"),
            trial_inputs=(TrialInput(id="trial", label="Trial", sources=(input_source,)),),
        ),
        trials=(Trial(id="trial", label="Trial"),),
        result_specs=(
            ResultSpec(
                id="result",
                trial=Trial(id="trial", label="Trial"),
                randomization=Randomization(id="random", description="Random"),
                arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
                comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
                effect_of_interest="assignment",
                outcome_definition="outcome",
                measurement="measure",
                time_point="time",
                population="all",
                analysis_method="method",
                analysis_choices=("choice",),
                effect_measure="RR",
                anchor=ResultAnchor(
                    source_id=source.id,
                    source_sha256=source.sha256,
                    page_number=1,
                    start=0,
                    end=6,
                    quote="anchor",
                ),
            ),
        ),
        sources=(source,),
    )


def test_current_batch_is_discoverable_and_empty() -> None:
    async def discover() -> list[str]:
        async with Client(mcp) as client:
            resources = await client.list_resources()
            contents = await client.read_resource("rob2://current-batch")
        assert contents[0].text == '{"active_batch":null}'
        return [str(resource.uri) for resource in resources]

    resources = asyncio.run(discover())

    assert resources == ["rob2://current-batch"]


def test_registry_resource_reads_captured_record_and_reports_missing(
    tmp_path: Path, monkeypatch
) -> None:
    from rob2_kit.ingestion import ingest_batch
    from rob2_kit.registry import TrialFacts, capture_registry_source, match_registry
    from rob2_kit.sources import SourceInput, TrialInput

    _pdf(tmp_path / "main.pdf")
    ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="trial",
                label="Trial",
                sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
            ),
        ),
    )
    payload = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "officialTitle": "Example"},
            "designModule": {"designInfo": {"allocation": "RANDOMIZED"}},
        }
    }
    match = match_registry(
        TrialFacts(title="Example", randomized=True), lambda _: payload, supplied_nct="NCT00000001"
    )
    capture_registry_source(str(tmp_path), "trial", match)
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def read() -> tuple[str, str]:
        async with Client(mcp) as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            captured = await client.read_resource("rob2://registry/trial")
            missing = await client.read_resource("rob2://registry/missing")
        assert any(str(item.uri) == "rob2://current-batch" for item in resources)
        assert [str(item.uriTemplate) for item in templates] == ["rob2://registry/{trial_id}"]
        return captured[0].text, missing[0].text

    captured, missing = asyncio.run(read())
    assert '"status":"captured"' in captured
    assert '"status":"not_captured"' in missing


def test_registry_resource_reports_existing_trial_without_capture(
    tmp_path: Path, monkeypatch
) -> None:
    from rob2_kit.ingestion import ingest_batch
    from rob2_kit.sources import SourceInput, TrialInput

    _pdf(tmp_path / "main.pdf")
    ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="trial",
                label="Trial",
                sources=(SourceInput(role="main_article", path="main.pdf", label="Main"),),
            ),
        ),
    )
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def read() -> str:
        async with Client(mcp) as client:
            result = await client.read_resource("rob2://registry/trial")
        return result[0].text

    assert asyncio.run(read()) == '{"trial_id":"trial","status":"not_captured"}'


def test_batch_tools_are_discoverable() -> None:
    async def discover() -> dict[str, dict[str, Any]]:
        async with Client(mcp) as client:
            tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["save_proposal", "approve_batch"]
        return {tool.name: tool.outputSchema for tool in tools}

    schemas = asyncio.run(discover())
    for schema in schemas.values():
        assert "oneOf" in schema["properties"]["state"]
        assert {
            variant["properties"]["status"]["const"]
            for variant in schema["properties"]["state"]["oneOf"]
        } == {"no_active", "proposal", "approved", "stale"}
    for result in (SaveProposalResult, ApproveBatchResult):
        state_schema = result.model_json_schema()["properties"]["state"]
        assert state_schema["discriminator"]["propertyName"] == "status"
        assert set(state_schema["discriminator"]["mapping"]) == {
            "no_active",
            "proposal",
            "approved",
            "stale",
        }


def test_batch_tools_return_typed_structured_conditions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    proposal = _proposal(tmp_path)
    invalid_anchor = proposal.result_specs[0].anchor.model_copy(update={"end": 1, "quote": "x"})
    incomplete = proposal.model_copy(
        update={
            "result_specs": (
                proposal.result_specs[0].model_copy(update={"anchor": invalid_anchor}),
            )
        }
    )

    async def call() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        async with Client(mcp) as client:
            no_proposal = await client.call_tool("approve_batch")
            saved = await client.call_tool(
                "save_proposal", {"proposal": incomplete.model_dump(mode="json")}
            )
            incomplete_approval = await client.call_tool("approve_batch")
            saved_complete = await client.call_tool(
                "save_proposal", {"proposal": proposal.model_dump(mode="json")}
            )
            assert saved_complete.structured_content["state"]["status"] == "proposal"
            approved = await client.call_tool("approve_batch")
            assert approved.structured_content["state"]["status"] == "approved"
            already_approved = await client.call_tool(
                "save_proposal", {"proposal": proposal.model_dump(mode="json")}
            )
        return (
            no_proposal.structured_content,
            saved.structured_content,
            incomplete_approval.structured_content,
            already_approved.structured_content,
        )

    no_proposal, saved, incomplete_approval, already_approved = asyncio.run(call())
    assert no_proposal["state"]["status"] == "no_active"
    assert saved["state"]["status"] == "proposal"
    assert saved["state"]["problems"][0]["code"] == "anchor_invalid"
    assert incomplete_approval["state"]["status"] == "proposal"
    assert already_approved["state"]["status"] == "stale"
    assert already_approved["state"]["problems"][0]["code"] == "batch_already_approved"
