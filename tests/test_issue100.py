from __future__ import annotations

import sqlite3
from pathlib import Path

import anyio
import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    ReadEvidenceRequest,
    ReadEvidenceResponse,
    RunOperation,
    SearchEvidenceRequest,
    SearchQueryEnvelope,
    WorkflowCondition,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.evidence import (
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    DocumentZone,
    EvidenceSearchIndex,
    SearchQuery,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.errors import (
    CursorScopeMismatch,
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    RetrievalErrorCode,
    RetrievalFailure,
    ScopeMismatch,
    StaleCursor,
    StaleWorkToken,
)
from rob2_kit.ingestion.project import (
    PageExtraction,
    PageTextItem,
    _optional_metadata,
)
from rob2_kit.interfaces.mcp.server import _retrieval_error, create_server

HASH = "sha256:" + "a" * 64


def _v3_question_scope() -> dict[str, str]:
    return {
        "result_id": "result:active",
        "domain_id": "domain:randomization",
        "question_id": "sq:randomization:sequence",
        "session_content_hash": HASH,
        "expected_navigation_state_hash": HASH,
    }


def test_retrieval_error_codes_preserve_scope_and_validation_boundaries() -> None:
    scope_error = _retrieval_error(
        CursorScopeMismatch("read continuation cursor belongs to a different Evidence scope")
    )
    assert scope_error.error.code is RetrievalErrorCode.CURSOR_SCOPE_MISMATCH
    assert scope_error.error.field == "cursor"
    assert scope_error.error.message.startswith("read continuation cursor")
    invalid_error = _retrieval_error(
        InvalidRetrievalRequest("query terms are invalid", field="query.terms")
    )
    assert invalid_error.error.code is RetrievalErrorCode.INVALID_REQUEST
    assert invalid_error.error.field == "query.terms"


def test_retrieval_error_transport_maps_every_typed_failure_without_substring_parsing() -> None:
    failures: tuple[RetrievalFailure, ...] = (
        StaleCursor("cursor is stale"),
        CursorScopeMismatch("cursor belongs to another scope"),
        ScopeMismatch("unit is outside scope", field="unit_id"),
        StaleWorkToken("token is stale"),
        InvalidRetrievalRequest("query is invalid", field="query"),
        OperationalRetrievalFailure("database is locked"),
    )
    expected = (
        RetrievalErrorCode.STALE_CURSOR,
        RetrievalErrorCode.CURSOR_SCOPE_MISMATCH,
        RetrievalErrorCode.SCOPE_MISMATCH,
        RetrievalErrorCode.STALE_WORK_TOKEN,
        RetrievalErrorCode.INVALID_REQUEST,
        RetrievalErrorCode.OPERATIONAL,
    )
    for failure, code in zip(failures, expected, strict=True):
        response = _retrieval_error(failure)
        assert response.error.code is code
        assert response.error.message == failure.message
        assert response.error.field == failure.field
        assert response.error.recovery == failure.recovery
        assert response.next_actions == failure.next_actions


def test_retrieval_error_transport_does_not_hide_programming_errors() -> None:
    with pytest.raises(RuntimeError, match="bug"):
        _retrieval_error(RuntimeError("bug"))


def test_line_wrap_hyphen_is_stripped_and_rejoined() -> None:
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Patient characteristics were well balanced be-",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="tween the two groups (Table 1).",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 1
    unit = units[0]
    assert unit.text == (
        "Patient characteristics were well balanced between the two groups (Table 1)."
    )
    assert "-" not in unit.text
    assert len(unit.fragment_ids) == 2
    # The deleted hyphen keeps a zero-width canonical mapping (ADR-0014):
    # the trailing span from the first fragment shrinks by one character and
    # a zero-width sibling span records the hyphen's own source position.
    first_fragment_id, second_fragment_id = unit.fragment_ids
    assert [span.fragment_id for span in unit.fragment_spans] == [
        first_fragment_id,
        first_fragment_id,
        second_fragment_id,
    ]
    shrunk_span, deleted_hyphen_span, second_fragment_span = unit.fragment_spans
    assert deleted_hyphen_span.canonical_start == deleted_hyphen_span.canonical_end
    assert deleted_hyphen_span.canonical_start == shrunk_span.canonical_end
    assert shrunk_span.canonical_end == len("Patient characteristics were well balanced be")
    assert second_fragment_span.canonical_start == shrunk_span.canonical_end
    assert second_fragment_span.canonical_end == len(unit.text)


def test_genuine_hyphenated_compound_at_line_break_is_also_rejoined() -> None:
    # ADR-0013: no dictionary check, so a genuine compound word landing on a
    # line break is merged too, accepted as a known limitation of the fix.
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Overall well-",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="being improved.",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 1
    assert units[0].text == "Overall wellbeing improved."


def test_non_hyphen_line_wraps_still_require_whitespace_boundary() -> None:
    # Ordinary line wraps (no trailing hyphen) must keep requiring a
    # whitespace boundary; two words separated only by page geometry, with no
    # space or hyphen, must not be silently mashed together.
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:1",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="randomly",
                        spatial=(20.0, 30.0, 400.0, 50.0),
                        reading_order=1,
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="assigned",
                        spatial=(20.0, 52.0, 400.0, 72.0),
                        reading_order=2,
                    ),
                ),
            ),
        ),
    )
    assert len(units) == 2


def test_canonical_models_reject_parser_scientific_semantics() -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        CanonicalBlock.model_validate(
            {
                "kind": "paragraph",
                "text": "source statement",
                "spatial": (0, 0, 10, 10),
                "result_id": "result:one",
            }
        )


def test_legacy_semantic_index_is_physically_replaced(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE evidence_units ("
            "unit_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
            "source_artifact_hash TEXT NOT NULL, parse_id TEXT NOT NULL, page INTEGER NOT NULL, "
            "kind TEXT NOT NULL, text TEXT NOT NULL, spatial TEXT, word_boxes TEXT, "
            "trial_id TEXT, result_id TEXT, "
            "document_zone TEXT)"
        )
        connection.execute(
            "INSERT INTO evidence_units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "unit:legacy",
                "source:legacy",
                HASH,
                "parse:legacy",
                1,
                "paragraph",
                "allocation",
                None,
                None,
                "trial:legacy",
                None,
                "methods",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    index = EvidenceSearchIndex(path)
    replacement = _unit("unit:replacement", "source:replacement", "allocation")
    index.replace_units((replacement,))
    assert index.read_unit(replacement.unit_id) == replacement


def _unit(
    unit_id: str,
    source_id: str,
    text: str,
    *,
    trial_id: str = "trial:active",
    result_id: str | None = "result:active",
    section: tuple[str, ...] = ("Methods",),
    zone: DocumentZone = DocumentZone.METHODS,
    duplicate_group_id: str | None = None,
    reading_order: int = 0,
    domain_id: str | None = None,
    question_ids: tuple[str, ...] = (),
) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=unit_id,
        source_id=source_id,
        source_artifact_hash=HASH,
        parse_id=f"parse:{source_id.removeprefix('source:')}",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        section_path=section,
        reading_order=reading_order,
        document_zone=zone,
        duplicate_group_id=duplicate_group_id,
    )


def test_table_row_context_round_trips_with_headers_and_caption(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = _unit("unit:table-row", "source:report", "Treatment | 0.8").model_copy(
        update={
            "kind": CanonicalUnitKind.TABLE_ROW,
            "table_headers": ("Arm", "Risk ratio"),
            "caption": "Mortality at 30 days",
        }
    )
    index.replace_units((unit,))
    assert index.read_unit(unit.unit_id) == unit


def test_public_retrieval_requests_require_a_work_token() -> None:
    with pytest.raises(ValidationError, match="work_token"):
        SearchEvidenceRequest.model_validate(
            {"run_id": "run:test", "query": {"terms": ["allocation"]}}
        )
    token = {
        "token": "token:test",
        "run_id": "run:test",
        "work_item_id": "work-item:test",
        "operation": "submit_domain_evidence",
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValidationError, match="policy"):
        SearchEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "query": {"terms": ["allocation"]},
                "work_token": token,
                "policy": {"page_hit_target": 1},
            }
        )
    with pytest.raises(ValidationError, match="neighbor_limit"):
        ReadEvidenceRequest.model_validate(
            {
                "run_id": "run:test",
                "unit_id": "unit:test",
                "work_token": token,
                "neighbor_limit": 1,
            }
        )


def test_parser_extraction_preserves_structure_metadata() -> None:
    page = PageExtraction(
        page_number=1,
        width=612,
        height=792,
        text="Methods",
        section_path=("Methods", "Allocation"),
        hierarchy_path=("2", "2.1"),
        document_zone="methods",
        text_items=(
            PageTextItem(
                text="Allocation was concealed.",
                x=10,
                y=20,
                width=200,
                height=12,
                unit_kind="paragraph",
                section_path=("Methods", "Allocation"),
                hierarchy_path=("2", "2.1"),
                reading_order=4,
                document_zone="methods",
            ),
        ),
    )
    assert page.text_items[0].unit_kind == "paragraph"
    assert page.text_items[0].section_path == ("Methods", "Allocation")
    assert page.document_zone == "methods"
    assert _optional_metadata(None) is None
    assert _optional_metadata("  methods  ") == "methods"
    with pytest.raises(ValidationError, match="work_token"):
        ReadEvidenceRequest.model_validate({"run_id": "run:test", "unit_id": "unit:test"})


def test_zone_inference_requires_a_heading_not_a_prose_substring() -> None:
    assert (
        RunEngine._canonical_zone(
            None,
            page_text="This paragraph references previous work.",
        )
        is DocumentZone.UNKNOWN
    )
    assert RunEngine._canonical_zone(None, page_text="References\n") is DocumentZone.BIBLIOGRAPHY
    assert (
        RunEngine._canonical_zone(None, page_text="# Methods\nAllocation was concealed.")
        is DocumentZone.METHODS
    )
    assert (
        RunEngine._canonical_zone(None, page_text="Allocation was concealed.")
        is DocumentZone.UNKNOWN
    )


def test_mcp_retrieval_routes_advertise_token_scope_and_read_modes() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search = tools["search_evidence"].input_schema["properties"]
    read = tools["read_evidence"].input_schema["properties"]
    assert "work_token" in search
    assert "work_token" in read
    assert "batch" in read
    assert "mode" not in read
    assert "WorkToken" in str(search["work_token"])


def test_mcp_tools_list_exposes_bounded_closed_search_query_schema() -> None:
    tools = {tool.name: tool for tool in anyio.run(create_server().list_tools)}
    search_tool = tools["search_evidence"]
    query_schema = search_tool.input_schema["$defs"]["SearchQueryEnvelope"]
    properties = query_schema["properties"]

    assert query_schema["additionalProperties"] is False
    assert properties["terms"]["maxItems"] == 32
    assert properties["terms"]["examples"] == [["allocation"]]
    assert {
        "kinds",
        "trial_id",
        "result_id",
        "domain_id",
        "question_id",
        "source_roles",
        "document_zones",
    }.isdisjoint(properties)
    with pytest.raises(ValidationError):
        SearchQueryEnvelope.model_validate({"kinds": ["paragraph"]})


def test_search_query_and_transport_envelope_have_schema_parity() -> None:
    engine_schema = SearchQuery.model_json_schema()
    envelope_schema = SearchQueryEnvelope.model_json_schema()

    assert engine_schema["additionalProperties"] is False
    assert envelope_schema["additionalProperties"] is False
    assert engine_schema["properties"] == envelope_schema["properties"]


def test_mcp_search_semantic_query_errors_are_structured(monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", FakeEngine)
    server = create_server()
    token = {
        "token": "token:mcp-search",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_QUESTION_STEP.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "search_evidence",
            {
                "run_id": "run:mcp",
                "query": {"terms": ["allocation OR concealment"]},
                "work_token": token,
                **_v3_question_scope(),
                "proposition_id": "proposition:allocation",
                "pass_id": "pass:direct-report",
                "stage_id": "stage:direct-report",
                "intent_id": "intent:allocation",
                "attempt_id": "attempt:mcp:invalid-query",
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "invalid_request"


def test_mcp_retrieval_operational_failures_are_structured(monkeypatch) -> None:
    class LockedEngine:
        def __init__(self, **_kwargs):
            pass

        def search_evidence(self, _request):
            raise sqlite3.OperationalError("database is locked")

        def read_evidence(self, _request):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", LockedEngine)
    server = create_server()
    token = {
        "token": "token:mcp-locked",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_QUESTION_STEP.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "search_evidence",
            {
                "run_id": "run:mcp",
                "query": {"terms": ["allocation"]},
                "work_token": token,
                **_v3_question_scope(),
                "proposition_id": "proposition:allocation",
                "pass_id": "pass:direct-report",
                "stage_id": "stage:direct-report",
                "intent_id": "intent:allocation",
                "attempt_id": "attempt:mcp:locked",
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "retrieval_operational"


def test_mcp_read_evidence_executes_typed_route_deterministically(monkeypatch) -> None:
    captured = {}

    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

        def read_evidence(self, request):
            captured["request"] = request
            return ReadEvidenceResponse(
                operation_id="operation:read-evidence",
                ledger_cursor="ledger:1",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.COMPLETED,
                committed=False,
                run_id=request.run_id,
                page={
                    "snapshot_hash": HASH,
                    "policy_id": "policy:evidence-read-2.0.0",
                    "policy_hash": HASH,
                    "scope": {
                        "result_id": "result:active",
                        "domain_id": "domain:randomization",
                        "snapshot_hash": HASH,
                    },
                    "outcomes": (),
                    "next_index": 0,
                    "serialized_response_bytes": 0,
                    "estimated_response_tokens": 0,
                },
            )

    monkeypatch.setattr("rob2_kit.interfaces.mcp.server.RunEngine", FakeEngine)
    server = create_server()
    token = {
        "token": "token:mcp-read",
        "run_id": "run:mcp",
        "work_item_id": "work-item:mcp",
        "operation": RunOperation.SUBMIT_QUESTION_STEP.value,
        "dependency_fingerprint": "sha256:" + "0" * 64,
    }

    async def invoke():
        return await server.call_tool(
            "read_evidence",
            {
                "run_id": "run:mcp",
                "work_token": token,
                **_v3_question_scope(),
                "batch": {
                    "scope": {
                        "result_id": "result:active",
                        "domain_id": "domain:randomization",
                        "snapshot_hash": HASH,
                    },
                    "items": [
                        {
                            "location_handle": "location:mcp",
                            "question_ids": ["sq:randomization"],
                        }
                    ],
                },
            },
        )

    result = anyio.run(invoke)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["run_id"] == "run:mcp"
    assert result.structured_content["page"]["outcomes"] == []
    assert captured["request"].work_token.token == token["token"]
