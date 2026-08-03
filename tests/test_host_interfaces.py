"""Public host boundaries for the single typed RunEngine workflow."""

from __future__ import annotations

import anyio
import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    RUN_OPERATION_NAMES,
    EvidenceConsiderationInput,
    EvidencePassageInput,
    RunOperation,
    SubmitDomainEvidenceRequest,
    WorkToken,
)
from rob2_kit.domain.revisions import RecordReference
from rob2_kit.interfaces.mcp.server import create_server, registered_tool_names


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
    assert registered_tool_names() == RUN_OPERATION_NAMES
    assert "open_review" not in registered_tool_names()


def test_mcp_tool_schemas_explain_nested_inputs_and_expose_passage_freezing() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    assert all(tool.description for tool in tools.values())
    for tool_name, property_name in {
        "get_work_context": "work_token",
        "submit_run_proposal": "selections",
        "confirm_run_definition": "confirmed_by",
        "search_evidence": "query",
        "submit_source_classification": "classifications",
        "submit_result_resolution": "result",
        "submit_domain_answers": "answers",
    }.items():
        schema_text = str(tools[tool_name].input_schema["properties"][property_name])
        assert "additionalProperties': True" not in schema_text, tool_name

    evidence_schema = tools["submit_domain_evidence"].input_schema
    assert "passages" in evidence_schema["properties"]
    assert "EvidencePassageInput" in str(evidence_schema)
    assert "include_source_details" in tools["get_work_context"].input_schema["properties"]
    for tool_name in (
        "submit_run_proposal",
        "confirm_run_definition",
        "submit_source_classification",
        "submit_result_resolution",
        "submit_domain_evidence",
        "submit_domain_answers",
    ):
        assert "idempotency_key" not in tools[tool_name].input_schema["properties"]


def test_mcp_tool_descriptions_prevent_cleanroom_schema_guessing() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    assert "authorized=true" in (tools["prepare_run"].description or "")
    assert 'confirmed_by={"kind":"human"' in (tools["confirm_run_definition"].description or "")

    search = tools["search_evidence"].description or ""
    assert 'query={"terms":["allocation"]}' in search
    assert 'seed_family="seed:allocation"' in search
    assert "reuse that exact label in" in search
    assert 'pass_kind="guidance_seed"' in search
    assert "omit seed_family" in search

    resolution = tools["submit_result_resolution"].description or ""
    assert "not a ResultCandidate" in resolution
    assert "experimental_arm_id" in resolution
    assert 'estimate={"value":' in resolution
    assert "work_token.result_id" in resolution

    classification = tools["submit_source_classification"].description or ""
    assert "exactly the sources in get_work_context" in classification
    assert '"roles"' in classification

    answers = tools["submit_domain_answers"].description or ""
    assert "every active question in get_work_context" in answers
    assert "no_information" in answers
    assert "actor" not in tools["submit_domain_evidence"].input_schema["properties"]
    assert "actor" not in tools["submit_domain_answers"].input_schema["properties"]
    evidence = tools["submit_domain_evidence"].description or ""
    assert 'coverage_state="complete_with_limitations"' in evidence
    assert 'coverage_state="complete"' in evidence
    assert "may support no_information" in evidence
    assert 'coverage_state="incomplete"' in evidence


def test_mcp_schema_names_the_friction_prone_evidence_contract() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}

    prepare = tools["prepare_run"]
    assert "required" in prepare.input_schema["properties"]["project_root"]["description"].lower()
    assert "every new session" in (prepare.description or "").lower()

    evidence = tools["submit_domain_evidence"]
    properties = evidence.input_schema["properties"]
    assert "coverage_limitations" in properties
    assert "limitation" in properties["coverage_limitations"]["description"].lower()
    assert "passages" in properties["passages"]["description"]
    assert "mutually exclusive" in properties["passages"]["description"].lower()
    assert "items" in properties["items"]["description"]
    assert "evidence_by_question" in properties["evidence_by_question"]["description"]
    assert "conflicts" in properties["conflicts"]["description"]

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
    disposition_field = evidence.input_schema["$defs"]["EvidenceConsiderationInput"]["properties"][
        "disposition"
    ]
    assert "valid" in disposition_field["description"].lower()


def test_domain_evidence_contract_rejects_aliases_and_mixed_branches() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        EvidenceConsiderationInput.model_validate(
            {"item_id": "candidate:test", "disposition": "irrelevant"}
        )

    token = WorkToken(
        token="token:test",
        run_id="run:test",
        work_item_id="work-item:test",
        operation=RunOperation.SUBMIT_DOMAIN_EVIDENCE,
        dependency_fingerprint="sha256:" + "0" * 64,
    )
    passage = EvidencePassageInput(
        unit_id="unit:test",
        span_start=0,
        claim_type="claim:test",
        question_ids=("sq:test",),
    )
    reference = RecordReference(
        entity_id="evidence:test",
        revision_id="revision:test",
        content_hash="sha256:" + "1" * 64,
    )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        SubmitDomainEvidenceRequest(
            contract_version="1.0.0",
            run_id="run:test",
            work_token=token,
            idempotency_key="idempotency:test",
            result_id="result:test",
            domain_id="domain:test",
            passages=(passage,),
            items=(reference,),
        )
