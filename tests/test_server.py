from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from rob2_kit.application._state import identity, read_json, write_json
from rob2_kit.application.contracts import EvidenceReference
from rob2_kit.application.evidence import (
    EvidenceRetrievalRequest,
    ManualSelectionRequest,
    retrieve_evidence,
)
from rob2_kit.interfaces.mcp.server import detail_resource, mcp, read_record


def test_public_catalog_is_exact_and_annotated() -> None:
    async def discover():
        async with Client(mcp) as client:
            return (
                await client.list_tools(),
                await client.list_resources(),
                await client.list_resource_templates(),
            )

    tools, resources, templates = asyncio.run(discover())
    assert [tool.name for tool in tools] == [
        "preflight_sources",
        "inspect_candidate_sources",
        "save_intake_plan",
        "capture_batch",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "save_proposal",
        "approve_batch",
        "validate_domain_judgment",
        "commit_domain_judgment",
        "prepare_trial_finish",
        "finish_trial",
        "finalize_batch",
        "read_record",
    ]
    assert [str(item.uri) for item in resources] == ["rob2://current-batch"]
    assert [str(item.uriTemplate) for item in templates] == [
        "rob2://detail/{kind}/{identity}",
        "rob2://registry/{trial_id}",
        "rob2://render/{identity}",
    ]
    read_only = {
        "inspect_candidate_sources",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "read_record",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is (tool.name in read_only)
        assert not tool.annotations.destructiveHint
        assert bool(tool.annotations.openWorldHint) is (tool.name == "preflight_sources")


def test_current_batch_is_a_typed_json_resource(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def read() -> str:
        async with Client(mcp) as client:
            return (await client.read_resource("rob2://current-batch"))[0].text

    assert json.loads(asyncio.run(read()))["phase"] == "empty"


def test_read_record_evidence_uses_authoritative_resolution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    from test_application_evidence import _workspace as prepare_workspace

    prepare_workspace(tmp_path)
    reference = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
            ),
        ),
    ).evidence[0]

    valid = read_record(reference)
    assert dict(valid.structured_content or {})["identity"] == reference.identity

    tampered = read_json(
        tmp_path, f"evidence-{reference.identity.removeprefix('sha256:')}.json"
    )
    assert tampered is not None
    tampered["source_sha256"] = "sha256:" + "f" * 64
    fields = (
        "kind",
        "trial_id",
        "snapshot",
        "source_id",
        "source_sha256",
        "projection_hash",
        "page",
        "start",
        "end",
        "quote",
        "quote_sha256",
    )
    tampered["identity"] = identity({key: tampered[key] for key in fields})
    write_json(
        tmp_path,
        f"evidence-{tampered['identity'].removeprefix('sha256:')}.json",
        tampered,
    )

    with pytest.raises(ValueError, match="Evidence Source is outside its scope"):
        read_record(EvidenceReference(kind="evidence", identity=tampered["identity"]))

    with pytest.raises(ValueError, match="Evidence detail URI is unsupported"):
        detail_resource("evidence", tampered["identity"])

    async def read_unsupported_detail() -> object:
        async with Client(mcp) as client:
            return await client.read_resource(
                f"rob2://detail/evidence/{tampered['identity']}"
            )

    with pytest.raises(Exception, match="Evidence detail URI is unsupported"):
        asyncio.run(read_unsupported_detail())
