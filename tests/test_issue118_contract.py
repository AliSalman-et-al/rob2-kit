from rob2_kit.application.contracts import EvidenceReviewRevisionInput
from rob2_kit.interfaces.mcp.server import create_server


def _tools():
    return {tool.name: tool for tool in create_server()._tool_manager.list_tools()}


def test_public_evidence_guidance_documents_read_view_receipts() -> None:
    text = open("docs/EVIDENCE-SEARCH.md", encoding="utf-8").read()
    assert "read_view_receipt" in text
    assert "location_handle" in text


def test_search_schema_has_no_retired_visibility_overrides() -> None:
    properties = _tools()["search_evidence"].parameters["properties"]
    assert "include_other_trial" not in properties
    assert "include_uncertain" not in properties


def test_question_bundle_schema_is_question_specific_and_receipt_bound() -> None:
    parameters = _tools()["materialize_question_evidence_bundle"].parameters
    properties = parameters["properties"]

    assert "question_id" in parameters["required"]
    assert "review_revisions" in properties
    schema = EvidenceReviewRevisionInput.model_json_schema()
    assert "sq_id" in str(schema)
    assert "read_view_receipt" in str(schema)
    assert "trial_attribution" in str(schema)


def test_question_bundle_contract_requires_v3() -> None:
    schema = _tools()["materialize_question_evidence_bundle"].parameters
    assert schema["properties"]["contract_version"]["const"] == "3.0.0"
