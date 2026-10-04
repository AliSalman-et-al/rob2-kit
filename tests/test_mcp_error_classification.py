import pytest
from fastmcp.exceptions import ToolError

from rob2_kit.application.evidence import EvidenceIntegrityError
from rob2_kit.interfaces.mcp import server


def test_output_schema_failure_is_an_internal_tool_error() -> None:
    with pytest.raises(ToolError, match="internal_output_contract_error"):
        server._invoke(
            "get_status",
            lambda: {"outcome": "success", "phase": "empty", "state_revision": 0},
        )


def test_application_value_error_remains_a_typed_invalid_request() -> None:
    def invalid_request() -> dict[str, object]:
        raise ValueError("invalid caller input")

    result = server._invoke("get_status", invalid_request)

    assert result.structured_content is not None
    assert result.structured_content["outcome"] == "condition"
    assert result.structured_content["condition"]["code"] == "invalid_request"
    assert result.structured_content["condition"]["detail"] == "invalid caller input"


def test_source_integrity_failure_is_an_internal_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_workspace", lambda: "unused")

    def corrupt_source(*args: object, **kwargs: object) -> dict[str, object]:
        raise EvidenceIntegrityError("captured Source bytes do not match Canonical identity")

    monkeypatch.setattr(server, "_search_sources", corrupt_source)

    with pytest.raises(ToolError, match="internal_evidence_integrity_error") as raised:
        server.search_sources(trial_id="trial-a", query="allocation", mode="all")
    assert "captured Source bytes" not in str(raised.value)


def test_search_batch_preserves_integrity_and_no_source_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    continuation = {
        "operation": "prepare_batch",
        "authority": "host",
        "expected_revision": 0,
        "caller_inputs": ["requested_outcome", "trial_labels", "acquire_registry_documents"],
    }
    monkeypatch.setattr(server, "_workspace", lambda: "unused")
    monkeypatch.setattr(
        server,
        "_get_status_head",
        lambda _workspace: {
            "outcome": "success",
            "phase": "empty",
            "state_revision": 0,
            "continuation": continuation,
            "authoritative_wording": "No active Batch assessment exists.",
        },
    )

    def search(_workspace: str, _trial_id: str, query: str, *_args: object) -> dict[str, object]:
        if query == "damaged":
            raise EvidenceIntegrityError("text search projection is corrupt")
        code = "no_sources" if query == "missing" else "no_searchable_sources"
        return {
            "outcome": "condition",
            "code": code,
            "condition": "No searchable Source text is available.",
            "phase": "empty",
            "state_revision": 0,
            "continuation": continuation,
        }

    monkeypatch.setattr(server, "_search_sources", search)
    requests = [
        server.SearchBatchRequest(trial_id="trial-a", query="damaged", mode="all"),
        server.SearchBatchRequest(trial_id="trial-b", query="missing", mode="all"),
        server.SearchBatchRequest(trial_id="trial-c", query="blank", mode="all"),
    ]

    result = server.search_sources_batch(requests=requests)

    assert result.structured_content is not None
    items = result.structured_content["data"]["results"]
    assert [item["result"]["outcome"] for item in items] == [
        "condition",
        "condition",
        "condition",
    ]
    assert items[0]["result"]["condition"]["code"] == "internal_evidence_integrity_error"
    assert items[1]["result"]["condition"]["code"] == "no_sources"
    assert items[2]["result"]["condition"]["code"] == "no_searchable_sources"
    assert all("data" not in item["result"] for item in items)
