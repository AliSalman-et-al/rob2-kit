"""Registry PDFs cross the actual public MCP intake/read boundary without inference."""

import asyncio
import hashlib
import json
import socket

import httpx
import pymupdf
import pytest
from fastmcp import Client

from rob2_kit.application import intake
from rob2_kit.application._state import _state
from rob2_kit.application.guidance import _ROOT
from rob2_kit.interfaces.mcp.server import mcp

NCT = "NCT00000001"


def _record(docs):
    return json.dumps(
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": NCT,
                    "briefTitle": "Neutral parallel randomized trial",
                }
            },
            "documentSection": {"largeDocumentModule": {"largeDocs": docs}},
        }
    ).encode()


def _pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        return doc.tobytes()


@pytest.mark.parametrize(
    "mode",
    [
        "opt_in",
        "disabled",
        "replay",
        "augmented_replay",
        "no_links",
        "failed_fetch",
        "no_identifier",
    ],
)
def test_public_native_registry_intake_and_reading(tmp_path, monkeypatch, mode):
    directory = tmp_path / "input" / "trial"
    directory.mkdir(parents=True)
    main = b"Original main report: neutral randomized trial NCT00000001; primary outcome."
    (directory / "main.txt").write_bytes(main)
    archived = _record([])
    replay = mode in {"disabled", "replay", "augmented_replay"}
    manifest = "" if mode == "no_identifier" else '[registry]\nnct = "' + NCT + '"\n'
    if replay:
        (directory / "retained.json").write_bytes(archived)
        manifest += (
            'replay = "retained.json"\ncaptured_at = "2020-01-01T00:00:00Z"\n'
            'sha256 = "' + hashlib.sha256(archived).hexdigest() + '"\n'
            'provenance = "neutral archived registry response"\n'
        )
    if mode == "disabled":
        manifest += "acquire_documents = true\n"  # Native false must override host opt-in.
    (directory / "sources.toml").write_text(manifest)
    input_before = {p.name: p.read_bytes() for p in directory.iterdir()}
    rows = (
        []
        if mode == "no_links"
        else [
            {
                "filename": "Prot_000.pdf",
                "typeAbbrev": "Prot",
                "date": "2018-01-01",
                "uploadDate": "2020-01-02T10:00",
            },
            {
                "filename": "SAP_001.pdf",
                "typeAbbrev": "SAP",
                "date": "2019-01-01",
                "uploadDate": "2020-01-02T10:01",
            },
        ]
    )
    current = _record(rows)
    files = {
        "Prot_000.pdf": _pdf("Protocol planned primary outcome NCT00000001"),
        "SAP_001.pdf": _pdf("Statistical analysis planned primary outcome NCT00000001"),
    }
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, content=current, request=httpx.Request("GET", url))

    original_client = httpx.Client

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            404 if mode == "failed_fetch" else 200,
            stream=httpx.ByteStream(files[request.url.path.rsplit("/", 1)[-1]]),
        )

    monkeypatch.setattr(intake.httpx, "get", get)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))

    async def inspect():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert "acquire_registry_documents" in tools["prepare_batch"].input_schema["properties"]
            pending, delivered = ["SKILL.md"], set()
            while pending:
                document = pending.pop()
                if document in delivered:
                    continue
                guidance = (
                    await client.call_tool("read_guidance", {"document": document})
                ).structured_content
                assert guidance["outcome"] == "success"
                assert (
                    guidance["data"]["content_sha256"]
                    == "sha256:" + hashlib.sha256((_ROOT / document).read_bytes()).hexdigest()
                )
                delivered.add(document)
                pending.extend(guidance["data"]["links"])
            assert "references/selection.md" in delivered
            arguments = {
                "requested_outcome": "primary outcome",
                "expected_revision": 0,
                "trial_labels": ["trial"],
            }
            if mode != "replay":
                arguments["acquire_registry_documents"] = mode != "disabled"
            prepared = (await client.call_tool("prepare_batch", arguments)).structured_content
            assert prepared["outcome"] == "success" and prepared["head"]["phase"] == "proposal"
            sources = (
                await client.call_tool("list_sources", {"trial_id": "trial"})
            ).structured_content["data"]["sources"]
            report = next(s for s in sources if s["logical_path"] == "main.txt")
            assert report["sha256"] == "sha256:" + hashlib.sha256(main).hexdigest()
            await client.call_tool(
                "read_pages", {"trial_id": "trial", "source_id": report["id"], "pages": [1]}
            )
            plans = [s for s in sources if s["role"] in {"protocol", "sap"}]
            acquired = mode in {"opt_in", "augmented_replay"}
            assert len(plans) == (2 if acquired else 0)
            if acquired:
                assert len({s["id"] for s in plans}) == 2 and len({s["sha256"] for s in plans}) == 2
                for source in plans:
                    assert source["id"].startswith("sh_") and source["origin"] == "registry"
                    assert "prespecification" not in source
                    filename = source["logical_path"].rsplit("/", 1)[-1]
                    assert (
                        source["sha256"] == "sha256:" + hashlib.sha256(files[filename]).hexdigest()
                    )
                    read = (
                        await client.call_tool(
                            "read_pages",
                            {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
                        )
                    ).structured_content
                    assert "planned primary outcome" in read["data"]["pages"][0]["numbered_text"]
                    search = (
                        await client.call_tool(
                            "search_sources",
                            {
                                "trial_id": "trial",
                                "source_id": source["id"],
                                "query": "planned",
                                "mode": "any",
                            },
                        )
                    ).structured_content
                    assert search["data"]["hits"] and all(
                        h["source_id"] == source["id"] for h in search["data"]["hits"]
                    )
                    rendered = await client.call_tool(
                        "render_page", {"trial_id": "trial", "source_id": source["id"], "page": 1}
                    )
                    assert rendered.structured_content["outcome"] == "success"
                    assert any(block.type == "image" for block in rendered.content)
            if mode not in {"disabled", "replay"}:
                metadata = next(s for s in sources if s["logical_path"].endswith("/capture.json"))
                read = (
                    await client.call_tool(
                        "read_pages",
                        {"trial_id": "trial", "source_id": metadata["id"], "pages": [1]},
                    )
                ).structured_content
                text = read["data"]["pages"][0]["numbered_text"]
                assert "new_public_capture_not_historical_replay" in text
                assert "prepare_batch_argument" in text
                if acquired:
                    assert "not proof of prespecification" in text
                    assert (
                        "document_date" in text and "upload_date" in text and "retrieved_at" in text
                    )
                if mode == "no_links":
                    assert "no_linked_documents_in_current_record" in text
                if mode == "failed_fetch":
                    assert "fetch_unavailable" in text
                if mode == "no_identifier":
                    assert "registry_unavailable_or_unmatched" in text
            frozen = _state(tmp_path)
            before_calls = list(calls)
            retry = (await client.call_tool("prepare_batch", arguments)).structured_content
            assert retry["outcome"] == "success" and retry["data"]["retry"]
            assert calls == before_calls and _state(tmp_path) == frozen
            changed = {
                **arguments,
                "expected_revision": frozen["revision"],
                "acquire_registry_documents": not arguments.get(
                    "acquire_registry_documents", False
                ),
            }
            rejected = (await client.call_tool("prepare_batch", changed)).structured_content
            assert (
                rejected["outcome"] == "condition"
                and _state(tmp_path) == frozen
                and calls == before_calls
            )
            assert frozen["review"] is None and frozen["proposal"] is None

    asyncio.run(inspect())
    assert input_before == {p.name: p.read_bytes() for p in directory.iterdir()}
    if mode in {"disabled", "replay"}:
        assert not calls
    if replay:
        registry = next(
            s for s in _state(tmp_path)["batch"]["trials"][0]["sources"] if s["role"] == "registry"
        )
        assert registry["sha256"] == "sha256:" + hashlib.sha256(archived).hexdigest()


def test_native_opt_in_requires_explicit_trial_scope(tmp_path, monkeypatch):
    directory = tmp_path / "input" / "trial"
    directory.mkdir(parents=True)
    (directory / "main.txt").write_text("Original report")
    monkeypatch.setenv("ROB2_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        intake.httpx, "get", lambda *a, **k: pytest.fail("unscoped request fetched")
    )

    async def reject():
        async with Client(mcp) as client:
            result = (
                await client.call_tool(
                    "prepare_batch",
                    {
                        "requested_outcome": "primary outcome",
                        "expected_revision": 0,
                        "acquire_registry_documents": True,
                    },
                )
            ).structured_content
            assert result["outcome"] == "condition"
            assert "explicit trial_labels" in result["condition"]["detail"]

    asyncio.run(reject())
    assert _state(tmp_path)["phase"] == "empty"
