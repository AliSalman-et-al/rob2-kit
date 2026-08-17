import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from fastmcp import Client
from mcp.types import ResourceLink

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
from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.batch_summary import FinalizedBatch
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
        assert contents[0].text == '{"phase":"empty","next_action":"ingest"}'
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
        assert [str(item.uriTemplate) for item in templates] == [
            "rob2://detail/{kind}/{identity}",
            "rob2://registry/{trial_id}",
        ]
        return captured[0].text, missing[0].text

    captured, missing = asyncio.run(read())
    captured_payload = json.loads(captured)
    missing_payload = json.loads(missing)
    assert captured_payload["candidate"] is None
    assert captured_payload["captured"]["trial_id"] == "trial"
    assert captured_payload["captured"]["status"] == "captured"
    assert captured_payload["captured"]["source"]["trial_id"] == "trial"
    assert missing_payload == {
        "candidate": None,
        "captured": {"status": "not_captured", "trial_id": "missing"},
    }


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

    assert json.loads(asyncio.run(read())) == {
        "candidate": None,
        "captured": {"status": "not_captured", "trial_id": "trial"},
    }


def test_batch_tools_are_discoverable() -> None:
    async def discover() -> dict[str, Any]:
        async with Client(mcp) as client:
            tools = await client.list_tools()
        assert [tool.name for tool in tools] == [
            "ingest_batch",
            "list_sources",
            "retrieve_evidence",
            "render_page",
            "save_proposal",
            "approve_batch",
            "validate_domain_judgment",
            "commit_domain_judgment",
            "finish_trial",
            "finalize_batch",
            "read_record",
            "discard_active_batch",
        ]
        return {tool.name: tool for tool in tools}

    tools = asyncio.run(discover())
    expected_annotations = {
        "ingest_batch": (False, False, True, True),
        "list_sources": (True, False, True, False),
        "retrieve_evidence": (True, False, True, False),
        "render_page": (True, False, True, False),
        "save_proposal": (False, False, True, False),
        "approve_batch": (False, False, True, False),
        "validate_domain_judgment": (False, False, True, False),
        "commit_domain_judgment": (False, False, True, False),
        "finish_trial": (False, False, True, False),
        "finalize_batch": (False, False, True, False),
        "read_record": (True, False, True, False),
        "discard_active_batch": (False, True, False, False),
    }
    for name, expected in expected_annotations.items():
        annotation = tools[name].annotations
        assert annotation is not None
        assert (
            annotation.readOnlyHint,
            annotation.destructiveHint,
            annotation.idempotentHint,
            annotation.openWorldHint,
        ) == expected
    schemas = {name: tool.inputSchema for name, tool in tools.items()}
    assert schemas["save_proposal"]["required"] == ["draft"]
    assert schemas["approve_batch"]["required"] == ["request"]
    assert schemas["validate_domain_judgment"]["required"] == ["operation"]
    assert schemas["commit_domain_judgment"]["required"] == ["operation"]
    discard = tools["discard_active_batch"]
    assert discard.annotations is not None
    assert discard.annotations.model_dump() == {
        "title": None,
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    finalized = FinalizedBatch.model_json_schema()
    assert finalized["required"] == ["summary", "receipt"]
    receipt = finalized["$defs"]["ArtifactReceipt"]
    assert receipt["required"] == [
        "bundle_path",
        "bundle_hash",
        "file_count",
        "summary_hash",
        "index_hash",
    ]
    assert set(receipt["properties"]) == {
        "algorithm",
        "bundle_path",
        "bundle_hash",
        "file_count",
        "summary_hash",
        "index_hash",
    }
    assert all(
        receipt["properties"][name]["pattern"] == "^sha256:[0-9a-f]{64}$"
        for name in ("bundle_hash", "summary_hash", "index_hash")
    )
    request_schema = discard.inputSchema["properties"]["request"]
    assert request_schema["required"] == [
        "expected_frozen_hash",
        "confirmation",
        "actor",
        "observed_at",
        "reason",
    ]
    assert request_schema["properties"]["confirmation"]["const"] == (
        "I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH"
    )


def test_discard_requires_a_complete_exact_request_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from v2_helpers import approved_workspace

    approved_workspace(tmp_path)

    approved = current_batch(tmp_path)
    assert isinstance(approved, ApprovedBatch)
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    request = {
        "expected_frozen_hash": approved.frozen_hash,
        "confirmation": "I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH",
        "actor": "researcher",
        "observed_at": "2026-08-14T00:00:00Z",
        "reason": "The researcher explicitly requested this discard.",
    }

    async def call() -> tuple[Any, Any, Any, Any, Any]:
        async with Client(mcp) as client:
            missing = await client.call_tool("discard_active_batch", raise_on_error=False)
            wrong_literal = await client.call_tool(
                "discard_active_batch",
                {"request": {**request, "confirmation": "yes"}},
                raise_on_error=False,
            )
            invalid_time = await client.call_tool(
                "discard_active_batch",
                {"request": {**request, "observed_at": "2026-08-14T00:00:00+01:00"}},
                raise_on_error=False,
            )
            blank_reason = await client.call_tool(
                "discard_active_batch",
                {"request": {**request, "reason": "   "}},
                raise_on_error=False,
            )
            stale = await client.call_tool(
                "discard_active_batch",
                {"request": {**request, "expected_frozen_hash": "sha256:" + "0" * 64}},
            )
        return missing, wrong_literal, invalid_time, blank_reason, stale

    missing, wrong_literal, invalid_time, blank_reason, stale = asyncio.run(call())
    assert all(result.is_error for result in (missing, wrong_literal, invalid_time, blank_reason))
    assert stale.structured_content == {
        "result": {
            "status": "condition",
            "code": "discard_identity_mismatch",
            "detail": "expected_frozen_hash does not identify the current frozen batch",
        }
    }
    assert current_batch(tmp_path) == approved


def test_mcp_registry_ingest_matches_and_persists_candidate(tmp_path: Path, monkeypatch) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Example randomized trial NCT00000001")
    document.save(tmp_path / "main.pdf")
    document.close()
    payload = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "officialTitle": "Example randomized trial",
            },
            "designModule": {
                "designInfo": {"allocation": "RANDOMIZED"},
                "enrollmentInfo": {"count": 10},
            },
            "armsInterventionsModule": {"armGroups": [{"interventionNames": ["Drug A"]}]},
            "conditionsModule": {"conditions": []},
            "statusModule": {},
        }
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    import rob2_kit.server as server

    original_client = httpx.Client
    monkeypatch.setattr(server.httpx, "Client", lambda **_: original_client(transport=transport))
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    request = {
        "trial_inputs": [
            {
                "id": "trial",
                "label": "Trial",
                "sources": [{"role": "main_article", "path": "main.pdf", "label": "Main"}],
            }
        ],
        "registry_requests": [
            {
                "trial_id": "trial",
                "supplied_nct": "NCT00000001",
                "facts": {
                    "title": "Example randomized trial",
                    "randomized": True,
                    "enrollment": 10,
                    "interventions": ["Drug A"],
                },
            }
        ],
    }

    async def call() -> tuple[dict[str, Any], str]:
        async with Client(mcp) as client:
            result = await client.call_tool("ingest_batch", {"request": request})
            resource = await client.read_resource("rob2://registry/trial")
        return result.structured_content, resource[0].text

    result, resource = asyncio.run(call())
    trial = result["trials"][0]
    assert trial == {
        "trial_id": "trial",
        "status": "captured",
        "source_count": 2,
        "projection_count": 2,
        "registry_status": "matched",
        "condition_code": None,
    }
    resource_payload = json.loads(resource)
    assert resource_payload["candidate"]["match"]["status"] == "matched"
    assert resource_payload["captured"]["trial_id"] == "trial"
    assert resource_payload["captured"]["status"] == "captured"


@pytest.mark.parametrize(
    ("sources", "expected_code"),
    [
        ([], "main_article_required"),
        (
            [
                {"role": "main_article", "path": "main.pdf", "label": "Main one"},
                {"role": "main_article", "path": "main.pdf", "label": "Main two"},
            ],
            "main_article_ambiguous",
        ),
        (
            [{"role": "main_article", "path": "main.txt", "label": "Main"}],
            "main_article_must_be_pdf",
        ),
    ],
)
def test_mcp_ingest_local_conditions_do_not_attempt_registry(
    tmp_path: Path, monkeypatch, sources: list[dict[str, str]], expected_code: str
) -> None:
    (tmp_path / "main.txt").write_text("not a PDF")
    _pdf(tmp_path / "main.pdf")
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    import rob2_kit.server as server

    monkeypatch.setattr(
        server.httpx,
        "Client",
        lambda **_: pytest.fail("registry client must not be created for local conditions"),
    )
    request = {
        "trial_inputs": [{"id": "trial", "label": "Trial", "sources": sources}],
        "registry_requests": [{"trial_id": "trial", "facts": _registry_facts()}],
    }

    async def call() -> dict[str, Any]:
        async with Client(mcp) as client:
            return (await client.call_tool("ingest_batch", {"request": request})).structured_content

    result = asyncio.run(call())
    assert result["next_action"] == "save_proposal"
    assert result["captured_batch_ref"]["kind"] == "batch"
    assert result["trials"] == [
        {
            "trial_id": "trial",
            "status": "condition",
            "source_count": 0,
            "projection_count": 0,
            "registry_status": "not_attempted",
            "condition_code": expected_code,
        }
    ]


@pytest.mark.parametrize(
    ("kind", "response"),
    [
        ("not_found", lambda request: httpx.Response(404)),
        (
            "ambiguous",
            lambda request: httpx.Response(
                200,
                json={
                    "studies": [
                        _registry_payload("NCT00000002"),
                        _registry_payload("NCT00000003"),
                    ]
                },
            ),
        ),
        ("unavailable", lambda request: (_ for _ in ()).throw(httpx.ConnectError("down"))),
    ],
)
def test_mcp_registry_nonmatched_outcomes_are_categorical_and_nonblocking(
    tmp_path: Path, monkeypatch, kind: str, response
) -> None:
    _registry_pdf(tmp_path / "main.pdf", "no identifier")
    import rob2_kit.server as server

    original_client = httpx.Client
    monkeypatch.setattr(
        server.httpx,
        "Client",
        lambda **_: original_client(transport=httpx.MockTransport(response)),
    )
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    facts = {
        "title": "Example randomized trial",
        "randomized": True,
        "enrollment": 10,
        "interventions": ["Drug A"],
    }

    async def call() -> tuple[dict[str, Any], str]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "ingest_batch", {"request": _registry_ingest_request(facts)}
            )
            resource = await client.read_resource("rob2://registry/trial")
        return result.structured_content, resource[0].text

    result, resource = asyncio.run(call())
    trial = result["trials"][0]
    assert trial["status"] == "captured"
    assert trial["trial_id"] == "trial"
    assert trial["source_count"] == 1
    assert trial["registry_status"] == kind
    resource_value = json.loads(resource)
    assert resource_value["candidate"]["match"]["status"] == kind
    assert resource_value["captured"] == {"status": "not_captured", "trial_id": "trial"}


def test_public_ingest_extracts_each_textual_source_once_for_registry_matching(
    tmp_path: Path, monkeypatch
) -> None:
    _registry_pdf(tmp_path / "main.pdf", "no identifier")
    import rob2_kit.ingestion.service as service
    import rob2_kit.server as server

    calls = 0
    original_extract = service._extract_pages

    def counted(data: bytes, media_type: str) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return original_extract(data, media_type)

    original_client = httpx.Client
    monkeypatch.setattr(service, "_extract_pages", counted)
    monkeypatch.setattr(
        server.httpx,
        "Client",
        lambda **_: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ),
    )
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def call() -> None:
        async with Client(mcp) as client:
            await client.call_tool(
                "ingest_batch", {"request": _registry_ingest_request(_registry_facts())}
            )

    asyncio.run(call())
    assert calls == 1


def test_mcp_registry_uses_article_nct_without_supplied_identifier(
    tmp_path: Path, monkeypatch
) -> None:
    _registry_pdf(tmp_path / "main.pdf", "NCT00000001")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "?" in str(request.url):
            return httpx.Response(200, json={"studies": []})
        return httpx.Response(200, json=_registry_payload("NCT00000001"))

    import rob2_kit.server as server

    original_client = httpx.Client
    monkeypatch.setattr(
        server.httpx, "Client", lambda **_: original_client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def call() -> dict[str, Any]:
        async with Client(mcp) as client:
            return (
                await client.call_tool(
                    "ingest_batch", {"request": _registry_ingest_request(_registry_facts())}
                )
            ).structured_content

    assert asyncio.run(call())["trials"][0]["registry_status"] == "matched"
    assert any(url.endswith("/NCT00000001") for url in requested)


def _registry_payload(nct: str) -> dict[str, object]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "officialTitle": "Example randomized trial"},
            "designModule": {
                "designInfo": {"allocation": "RANDOMIZED"},
                "enrollmentInfo": {"count": 10},
            },
            "armsInterventionsModule": {"armGroups": [{"interventionNames": ["Drug A"]}]},
            "conditionsModule": {"conditions": []},
            "statusModule": {},
        }
    }


def _registry_facts() -> dict[str, object]:
    return {
        "title": "Example randomized trial",
        "randomized": True,
        "enrollment": 10,
        "interventions": ["Drug A"],
    }


def _registry_ingest_request(facts: Mapping[str, object]) -> dict[str, object]:
    return {
        "trial_inputs": [
            {
                "id": "trial",
                "label": "Trial",
                "sources": [{"role": "main_article", "path": "main.pdf", "label": "Main"}],
            }
        ],
        "registry_requests": [{"trial_id": "trial", "facts": facts}],
    }


def _registry_pdf(path: Path, text: str) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_v2_public_surface_rejects_legacy_names_and_uses_strict_drafts() -> None:
    async def discover() -> tuple[list[str], list[str], dict[str, Any]]:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
        return (
            [tool.name for tool in tools],
            [str(item.uri) for item in resources] + [str(item.uriTemplate) for item in templates],
            {tool.name: tool.inputSchema for tool in tools},
        )

    tools, resources, schemas = asyncio.run(discover())
    assert tools == [
        "ingest_batch",
        "list_sources",
        "retrieve_evidence",
        "render_page",
        "save_proposal",
        "approve_batch",
        "validate_domain_judgment",
        "commit_domain_judgment",
        "finish_trial",
        "finalize_batch",
        "read_record",
        "discard_active_batch",
    ]
    assert resources == [
        "rob2://current-batch",
        "rob2://detail/{kind}/{identity}",
        "rob2://registry/{trial_id}",
    ]
    assert schemas["save_proposal"]["additionalProperties"] is False
    assert schemas["save_proposal"]["required"] == ["draft"]
    assert schemas["approve_batch"]["required"] == ["request"]
    assert schemas["validate_domain_judgment"]["required"] == ["operation"]
    assert schemas["commit_domain_judgment"]["required"] == ["operation"]


def test_public_raw_drafts_aggregate_nested_repairs_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def call() -> tuple[dict[str, Any], dict[str, Any]]:
        async with Client(mcp) as client:
            proposal = await client.call_tool(
                "save_proposal",
                {
                    "draft": {
                        "outcome_target": {"id": 1, "extra": True},
                        "results": "wrong",
                        "extra": True,
                    }
                },
            )
            domain = await client.call_tool(
                "validate_domain_judgment",
                {
                    "operation": {
                        "approved_batch_hash": "sha256:" + "0" * 64,
                        "trial_id": "trial",
                        "result_id": "result",
                        "domain_id": "domain:randomization",
                        "actor": "reviewer",
                        "draft": {
                            "active_answers": "wrong",
                            "limitations": [1],
                            "extra": True,
                        },
                    }
                },
            )
        return proposal.structured_content, domain.structured_content

    proposal, domain = asyncio.run(call())
    assert proposal["status"] == "repair"
    assert len(proposal["repairs"]) >= 3
    assert domain["status"] == "condition"
    assert domain["code"] == "batch_not_approved"
    assert not (tmp_path / ".rob2-kit" / "active-batch.sqlite3").exists()


def test_finish_unknown_trial_returns_typed_identity_condition(tmp_path: Path, monkeypatch) -> None:
    from v2_helpers import approved_workspace

    approved_workspace(tmp_path)
    approved = current_batch(tmp_path)
    assert isinstance(approved, ApprovedBatch)
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def call() -> dict[str, Any]:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "finish_trial",
                {
                    "operation": {
                        "mode": "needs_input",
                        "approved_batch_hash": approved.frozen_hash,
                        "trial_id": "unknown",
                        "actor": "finisher",
                        "problems": [{"code": "missing", "detail": "Missing input."}],
                    }
                },
            )
        return result.structured_content

    result = asyncio.run(call())
    assert result["status"] == "condition"
    assert result["code"] == "result_identity_invalid"


def test_compact_ingest_emits_actual_resource_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def call():
        async with Client(mcp) as client:
            return await client.call_tool(
                "ingest_batch",
                {
                    "request": {
                        "trial_inputs": [{"id": "trial", "label": "Trial", "sources": []}],
                        "registry_requests": [],
                    }
                },
            )

    result = asyncio.run(call())
    assert result.structured_content["trials"][0]["status"] == "condition"
    assert "captured_path" not in json.dumps(result.structured_content)
    links = [item for item in result.content if isinstance(item, ResourceLink)]
    assert len(links) == 1
    assert str(links[0].uri).startswith("rob2://detail/batch/sha256:")
