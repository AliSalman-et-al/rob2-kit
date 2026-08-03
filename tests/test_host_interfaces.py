"""Public host boundaries for the single typed RunEngine workflow."""

from __future__ import annotations

import anyio

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
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
    assert "seed_family only with pass_kind=guidance_seed" in search
    assert "omit seed_family" in search

    resolution = tools["submit_result_resolution"].description or ""
    assert "copy the issued Result identity" in resolution
    assert "experimental_arm_id" in resolution
    assert 'estimate={"value":' in resolution

    classification = tools["submit_source_classification"].description or ""
    assert "exactly the sources in get_work_context" in classification
    assert '"roles"' in classification

    answers = tools["submit_domain_answers"].description or ""
    assert "every active question in get_work_context" in answers
    assert "no_information" in answers
