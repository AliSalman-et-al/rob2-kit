import asyncio
from pathlib import Path

import pymupdf
from fastmcp import Client

from rob2_kit.server import mcp


def _pdf(path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()


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
