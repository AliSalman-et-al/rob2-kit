"""Offline preparation checks, including real stdio source/image delivery; no inference."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.tools import ToolResult
from jsonschema import validate as validate_schema
from mcp.types import TextContent

from rob2_kit.application._state import _identity, _state
from rob2_kit.logic.evaluator import active_questions
from rob2_kit.packs import SCIENTIFIC_PACK

HERE = Path(__file__).parent.resolve()
spec = importlib.util.spec_from_file_location("minimal_diagnostic", HERE / "diagnostic.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ROOT = Path(sys.argv[1]).resolve()
PYTHON = Path(sys.executable)
CODEX = Path("/home/ali/.nvm/versions/node/v24.21.0/bin/codex")


def rejected(fn):
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("invalid diagnostic input accepted")


async def checks():
    workspace = ROOT / (sys.argv[2] if len(sys.argv) > 2 else "offline-check") / "workspace"
    shutil.copytree(ROOT / "seed", workspace)
    # Guidance server lookup is relative to an arm/workspace, so the scratch
    # arm is intentionally at the same depth as the two frozen model arms.
    source = json.loads((ROOT / "sources.json").read_text())[0]
    args = {"trial_id": module.CASE, "source_id": source["id"], "pages": [2]}
    os.environ["ROB2_WORKSPACE"] = str(workspace)
    from rob2_kit.interfaces.mcp.server import mcp

    async with Client(mcp) as c:
        native_tools = {t.name: t for t in await c.list_tools()}
        native_read = (await c.call_tool("read_pages", args)).structured_content
        native_pages = {}
        for page in range(1, 8):
            row = await c.call_tool("read_pages", {**args, "pages": [page]})
            native_pages[page] = row.structured_content["data"]
        native_image = await c.call_tool(
            "render_page", {"trial_id": module.CASE, "source_id": source["id"], "page": 2}
        )
    command = [str(PYTHON), str(HERE / "diagnostic.py"), "serve", str(workspace)]
    transport = StdioTransport(
        command=command[0], args=command[1:], env={**os.environ, "ROB2_WORKSPACE": str(workspace)}
    )
    async with Client(transport) as c:
        tools = await c.list_tools()
        assert {t.name for t in tools} == set(module.SOURCE_TOOLS)
        module.write(ROOT / "actual-tool-schemas.json", [t.model_dump(mode="json") for t in tools])
        assert not await c.list_resources() and not await c.list_resource_templates()
        for tool in tools:
            if tool.name in native_tools:
                assert tool.input_schema == native_tools[tool.name].input_schema
        denied = await c.call_tool("get_status", {}, raise_on_error=False)
        assert denied.is_error
        thin_read = (await c.call_tool("read_pages", args)).structured_content
        assert thin_read["data"] == native_read["data"]
        assert "head" not in thin_read and "next_action" not in thin_read
        for page, original in native_pages.items():
            delivered = await c.call_tool("read_pages", {**args, "pages": [page]})
            assert delivered.structured_content["data"] == original
            for block in delivered.content:
                if block.type == "text":
                    value = json.loads(block.text)
                    assert "head" not in value and "next_action" not in value
        # Includes report primary wording, exclusions and unblinded-study limitations.
        assert "mean drop" in native_pages[3]["pages"][0]["numbered_text"]
        assert "lack of exhaustive data" in native_pages[4]["pages"][0]["numbered_text"]
        assert "could not be blinded" in native_pages[6]["pages"][0]["numbered_text"]
        await c.call_tool(
            "search_sources",
            {"trial_id": module.CASE, "query": "exhaustive data", "mode": "phrase"},
        )
        await c.call_tool(
            "search_sources_batch",
            {"requests": [{"trial_id": module.CASE, "query": "intubation", "mode": "all"}]},
        )
        thin_image = await c.call_tool(
            "render_page", {"trial_id": module.CASE, "source_id": source["id"], "page": 2}
        )
        native_png = next(x.data for x in native_image.content if x.type == "image")
        thin_png = next(x.data for x in thin_image.content if x.type == "image")
        assert native_png == thin_png and thin_image.structured_content is None
        receipt = json.loads(next(x.text for x in thin_image.content if x.type == "text"))
        image_data = receipt["data"]
        text_blocks = [x for x in thin_image.content if x.type == "text"]
        assert len(text_blocks) == 1
        assert "head" not in receipt and "next_action" not in receipt
        assert receipt["data"] == native_image.structured_content["data"]
        guidance = await c.call_tool("render_guidance_page", {"page": 33})
        assert any(x.type == "image" for x in guidance.content)
        for page in [1, 34, 38, 68]:
            assert (
                await c.call_tool("render_guidance_page", {"page": page}, raise_on_error=False)
            ).is_error
    # Independent middleware probe: non-receipt contrary prose is never removed.
    native = ToolResult(
        content=[TextContent(type="text", text="Contrary source fact")],
        structured_content={
            "data": {"facts": ["Contrary source fact"]},
            "head": {},
            "next_action": {},
        },
    )

    async def next_receipt(context):
        return native

    retained = await module.SourcesOnly().on_call_tool(
        SimpleNamespace(message=SimpleNamespace(name="read_pages")), next_receipt
    )
    assert retained.content[0].text == "Contrary source fact"
    assert native.structured_content is not None
    assert retained.structured_content["data"] == native.structured_content["data"]
    # Synthetic syntax checks exercise this actual frozen Source without making
    # any scientific claim about the case. No fixture answer enters model input.
    values = {}
    while True:
        pending = [q for q in active_questions(values) if q not in values]
        if not pending:
            break
        for qid in pending:
            q = next(q for q in SCIENTIFIC_PACK.questions if q.id == qid)
            options = {a.value for a in q.allowed_answers}
            values[qid] = "no_information" if "no_information" in options else "probably_no"
    citation = {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 2}
    draft = {
        "result_identity": _identity(json.loads((ROOT / "diagnostic-result.json").read_text())),
        "domains": [
            {
                "domain_id": d.id,
                "answers": [
                    {
                        "question_id": q,
                        "answer": values[q],
                        "rationale": "Synthetic interface fixture, not a clinical warrant.",
                        "citations": [citation],
                        "unknowns": ["Synthetic fixture"],
                        "counterevidence": [],
                    }
                    for q in d.question_ids
                    if q in values
                ],
            }
            for d in SCIENTIFIC_PACK.domains
        ],
    }
    fixture = ROOT / "offline-synthetic-response.json"
    module.write(fixture, draft)
    validate_schema(draft, json.loads((ROOT / "response-schema.json").read_text()))
    result = module.validate(ROOT, fixture, workspace)
    assert set(result["computed_proposed_domain_labels"]) == {d.id for d in SCIENTIFIC_PACK.domains}
    invalid = json.loads(json.dumps(draft))
    invalid["overall"] = "low"
    module.write(ROOT / "invalid.json", invalid)
    rejected(lambda: module.validate(ROOT, ROOT / "invalid.json", workspace))
    invalid = json.loads(json.dumps(draft))
    invalid["domains"][2]["answers"] = invalid["domains"][2]["answers"][:1]
    module.write(ROOT / "invalid-branch.json", invalid)
    rejected(lambda: module.validate(ROOT, ROOT / "invalid-branch.json", workspace))
    invalid = json.loads(json.dumps(draft))
    invalid["domains"][0]["answers"][0]["citations"][0]["source_id"] = "sh_" + "0" * 16
    module.write(ROOT / "invalid-source.json", invalid)
    rejected(lambda: module.validate(ROOT, ROOT / "invalid-source.json", workspace))
    # Validate every raw handle, including independently referenced counterevidence.
    for role in ["citation", "counterevidence"]:
        invalid = json.loads(json.dumps(draft))
        answer = invalid["domains"][0]["answers"][0]
        if role == "citation":
            answer["citations"] = ["eh_" + "0" * 16]
        else:
            answer["counterevidence"] = [
                {"evidence": ["eh_" + "0" * 16], "implication": "Synthetic negative fixture"}
            ]
        path = ROOT / f"invalid-handle-{role}.json"
        module.write(path, invalid)
        rejected(lambda: module.validate(ROOT, path, workspace))
    selected = next(iter(result["selected_evidence"].values()))
    valid_handles = json.loads(json.dumps(draft))
    valid_handles["domains"][0]["answers"][0]["citations"] = [selected["handle"]]
    valid_handles["domains"][0]["answers"][0]["counterevidence"] = [
        {"evidence": [selected["handle"]], "implication": "Synthetic valid locator fixture"}
    ]
    module.write(ROOT / "offline-valid-handles.json", valid_handles)
    module.validate(ROOT, ROOT / "offline-valid-handles.json", workspace)
    # A real selector creates an existing foreign-Trial handle in a separate fixture.
    foreign_root = ROOT / (workspace.parent.name + "-foreign-fixture")
    shutil.copytree(module.RAW, foreign_root / "input" / "foreign-trial")
    os.environ["ROB2_WORKSPACE"] = str(foreign_root)
    async with Client(mcp) as c:
        await c.call_tool(
            "prepare_batch",
            {
                "requested_outcome": "Fixture",
                "trial_labels": ["foreign-trial"],
                "expected_revision": 0,
                "acquire_registry_documents": False,
            },
        )
        foreign_source = (
            await c.call_tool("list_sources", {"trial_id": "foreign-trial"})
        ).structured_content["data"]["sources"][0]
        foreign_evidence = (
            await c.call_tool(
                "select_text_evidence",
                {
                    "trial_id": "foreign-trial",
                    "source_id": foreign_source["id"],
                    "page": 1,
                    "start_line": 1,
                    "end_line": 2,
                },
            )
        ).structured_content["data"]["evidence"]
    from rob2_kit.application.evidence import _evidence_for_handles

    _evidence_for_handles(foreign_root, {foreign_evidence["handle"]}, "foreign-trial")
    with sqlite3.connect(foreign_root / ".rob2-kit/derivative.sqlite3") as db:
        foreign_row = db.execute(
            "SELECT identity,payload FROM evidence_handles WHERE identity=?",
            (foreign_evidence["identity"],),
        ).fetchone()
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as db:
        db.execute("INSERT INTO evidence_handles(identity,payload) VALUES (?,?)", foreign_row)
    for role in ["citation", "counterevidence"]:
        invalid = json.loads(json.dumps(draft))
        answer = invalid["domains"][0]["answers"][0]
        if role == "citation":
            answer["citations"] = [foreign_evidence["handle"]]
        else:
            answer["counterevidence"] = [
                {
                    "evidence": [foreign_evidence["handle"]],
                    "implication": "Synthetic foreign locator",
                }
            ]
        path = ROOT / f"invalid-foreign-{role}.json"
        module.write(path, invalid)
        rejected(lambda: module.validate(ROOT, path, workspace))
    # The same canonical mechanism rejects modified immutable Source bytes.
    corrupted = ROOT / (workspace.parent.name + "-corrupt-source-fixture")
    shutil.copytree(workspace, corrupted)
    pdf = next((corrupted / ".rob2-kit/sources").rglob("*.bin"))
    with pdf.open("ab") as f:
        f.write(b"synthetic-integrity-negative")
    rejected(lambda: module.validate(ROOT, ROOT / "offline-valid-handles.json", corrupted))
    # Record an actual inspected-image citation through the same existing resolver.
    visual = {
        "delivery_receipt": image_data["delivery_receipt"],
        "region": [0.0, 0.0, 1.0, 1.0],
        "transcription": "Synthetic image locator fixture; not a scientific extraction.",
    }
    visual_draft = json.loads(json.dumps(draft))
    visual_draft["domains"][0]["answers"][0]["citations"] = [visual]
    module.write(ROOT / "offline-visual-response.json", visual_draft)
    module.validate(ROOT, ROOT / "offline-visual-response.json", workspace)
    retained = json.loads(
        (
            HERE.parent
            / "2026-10-03-tool-free-observation-contrast"
            / "condition_a/durable-token-usage-records.json"
        ).read_text()
    )
    usage = module.usage([{"type": "token_usage_record", "payload": r} for r in retained * 2])
    assert usage["responses"] == 1 and usage["usage"]["input_tokens"] == 7829
    assert usage["usage"]["output_tokens"] == 476 and usage["uncached_input_tokens"] == 6037
    assert module.usage([])["missing_usage"] is True
    for arm in ["rich", "minimal"]:
        state = _state(ROOT / arm / "workspace")
        assert not state.get("domain_records") and not state.get("snapshots")
    return {
        "source_tools": [t.name for t in tools],
        "native_source_inputs_unchanged": True,
        "all_seven_page_data_exact": True,
        "contrary_source_facts_preserved": True,
        "all_text_blocks_without_workflow_metadata": True,
        "existing_foreign_and_nonexistent_handles_rejected": True,
        "counterevidence_handles_validated": True,
        "source_integrity_checked": True,
        "trial_png_exact": True,
        "trial_png_sha256": module.digest(base64.b64decode(thin_png)),
        "official_image_available": True,
        "workflow_and_resources_unavailable": True,
        "output_schema_and_branching_checked": True,
        "source_citations_resolved": True,
        "invalid_labels_branch_sources_rejected": True,
        "visual_receipt_resolved": True,
        "duplicate_usage_deduplicated": usage,
        "model_workspaces_without_domain_history": True,
        "paid_calls": 0,
    }


proof = asyncio.run(checks())
proof["codex_version"] = subprocess.check_output([str(CODEX), "--version"], text=True).strip()
proof["model_plan"] = {
    "model": "gpt-6-luna",
    "reasoning_effort": "medium",
    "executable": str(CODEX),
}
module.write(ROOT / "offline-proof.json", proof)
print(json.dumps(proof, indent=2))
