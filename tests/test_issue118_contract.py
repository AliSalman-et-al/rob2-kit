from rob2_kit.interfaces.mcp.server import create_server
from rob2_kit.application.contracts import EvidenceReviewRevisionInput


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


def test_freeze_schema_is_question_specific_and_receipt_bound() -> None:
    properties = _tools()["submit_domain_evidence"].parameters["properties"]
    review = properties["review_revisions"]
    assert "receipt" in review["description"]
    schema = EvidenceReviewRevisionInput.model_json_schema()
    assert "sq_id" in str(schema)
    assert "trial_attribution" in str(schema)


def test_freeze_contract_requires_1_1_0() -> None:
    schema = _tools()["submit_domain_evidence"].parameters
    assert schema["properties"]["contract_version"]["const"] == "1.1.0"
