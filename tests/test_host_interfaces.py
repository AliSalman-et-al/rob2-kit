"""Public host boundaries for the single typed RunEngine workflow."""

from __future__ import annotations

import anyio
import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    EvidencePassageInput,
    MaterializeQuestionEvidenceBundleRequest,
    RunOperation,
    WorkToken,
)
from rob2_kit.interfaces.mcp.server import (
    CANONICAL_TOOL_NAMES,
    create_server,
    registered_tool_names,
)


def blank_pdf() -> bytes:
    """Return the small valid PDF fixture shared by stdio workflow tests."""

    stream = b"BT /F1 12 Tf 10 36 Td (Trial report) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def test_stdio_mcp_surface_is_the_fixed_run_engine_inventory() -> None:
    assert registered_tool_names() == CANONICAL_TOOL_NAMES
    assert len(registered_tool_names()) == 18
    assert "open_review" not in registered_tool_names()


def test_mcp_tool_schemas_explain_question_scoped_evidence_freezing() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    assert all(
        tools[name].description
        for name in {
            "prepare_run",
            "continue_run",
            "get_work_context",
            "search_evidence",
            "read_evidence",
        }
    )
    for tool_name, property_name in {
        "get_work_context": "work_token",
        "submit_run_proposal": "selections",
        "confirm_run_definition": "confirmed_by",
        "search_evidence": "query",
        "submit_source_role_review": "selections",
        "submit_result_resolution": "result",
        "materialize_question_evidence_bundle": "passages",
        "submit_question_step": "question_id",
    }.items():
        schema_text = str(tools[tool_name].input_schema["properties"][property_name])
        assert "additionalProperties': True" not in schema_text, tool_name

    evidence_schema = tools["materialize_question_evidence_bundle"].input_schema
    assert "passages" in evidence_schema["properties"]
    assert "EvidencePassageInput" in str(evidence_schema)
    assert "include_source_details" in tools["get_work_context"].input_schema["properties"]
    assert "proposal_discovery_pass" in tools["get_work_context"].input_schema["properties"]
    assert (
        "proposal_discovery_read_continuation"
        in tools["get_work_context"].input_schema["properties"]
    )
    for tool_name in (
        "submit_run_proposal",
        "confirm_run_definition",
        "submit_source_role_review",
        "submit_result_resolution",
    ):
        assert "idempotency_key" not in tools[tool_name].input_schema["properties"]
    for tool_name in ("materialize_question_evidence_bundle", "submit_question_step"):
        assert "idempotency_key" in tools[tool_name].input_schema["properties"]
    assert "correct_domain_answers" not in tools


def test_mcp_tool_descriptions_prevent_cleanroom_schema_guessing() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    assert "authorized=true" in (tools["prepare_run"].description or "")
    assert 'confirmed_by={"kind":"human"' in (tools["confirm_run_definition"].description or "")

    search = tools["search_evidence"].description or ""
    search_guidance = " ".join(search.split())
    assert 'query={"terms":["allocation"]}' in search_guidance
    assert "proposition" in search_guidance
    assert "pass, stage, intent, attempt" in search_guidance
    assert "copied from the current context" in search_guidance
    assert "never widen that scope" in search_guidance

    resolution = tools["submit_result_resolution"].description or ""
    assert "not a ResultCandidate" in resolution
    assert "experimental_arm_id" in resolution
    assert 'estimate={"value":' in resolution
    assert "work_token.result_id" in resolution

    classification = tools["submit_source_role_review"].description or ""
    assert "exactly the sources in get_work_context" in classification
    assert '"roles"' in classification

    assert "actor" not in tools["materialize_question_evidence_bundle"].input_schema["properties"]
    assert "correct_domain_answers" not in tools
    assert "correct_question_step" in tools


def test_mcp_schema_names_the_friction_prone_evidence_contract() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    prepare = tools["prepare_run"]
    assert "required" in prepare.input_schema["properties"]["project_root"]["description"].lower()
    assert "every new session" in (prepare.description or "").lower()

    evidence = tools["materialize_question_evidence_bundle"]
    properties = evidence.input_schema["properties"]
    assert {"question_id", "passages", "review_revisions", "expected_navigation_state_hash"} <= set(
        properties
    )
    assert "conflicts" not in properties

    disposition = evidence.input_schema["$defs"]["ConsiderationDisposition"]
    assert disposition["enum"] == [
        "supporting",
        "contradicting",
        "contextual",
        "duplicate",
        "out_of_scope",
        "immaterial",
        "superseded",
        "unresolved",
    ]
    assert "irrelevant" not in disposition["enum"]


def test_question_bundle_contract_rejects_cross_question_passages() -> None:
    token = WorkToken(
        token="token:test",
        run_id="run:test",
        work_item_id="work-item:test",
        operation=RunOperation.MATERIALIZE_QUESTION_EVIDENCE_BUNDLE,
        dependency_fingerprint="sha256:" + "0" * 64,
    )
    passage = EvidencePassageInput(
        unit_id="unit:test",
        span_start=0,
        claim_type="claim:test",
        question_ids=("sq:test",),
    )
    with pytest.raises(ValidationError, match="active question"):
        MaterializeQuestionEvidenceBundleRequest(
            contract_version="3.0.0",
            run_id="run:test",
            work_token=token,
            idempotency_key="idempotency:test",
            result_id="result:test",
            domain_id="domain:test",
            question_id="sq:other",
            session_content_hash="sha256:" + "2" * 64,
            frontier_entry_hash="sha256:" + "3" * 64,
            expected_navigation_state_hash="sha256:" + "4" * 64,
            passages=(passage,),
        )
