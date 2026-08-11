"""Contract checks for the isolated v2 Evidence-search navigation seam."""

from __future__ import annotations

import pytest

from rob2_kit.application.contracts import (
    CoverageProgress,
    SearchEvidenceResponse,
    WorkflowCondition,
    v2_model_facing_operation_payload,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.errors import (
    OperationalRetrievalFailure,
    SearchPolicyMismatch,
    StaleSearchContinuation,
)
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    SearchContinuationReason,
    SearchQuery,
)
from rob2_kit.evidence.workflow import SearchPassKind


def _unit(number: int, text: str) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=f"unit:report-{number}",
        source_id="source:report",
        source_artifact_hash=canonical_hash({"source": "report"}),
        parse_id="parse:report",
        page=number,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        fragment_ids=(f"fragment:report-{number}",),
    )


def test_v2_page_is_lightweight_bound_and_continuable(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "v2.sqlite3")
    index.replace_units(
        tuple(
            _unit(number, f"Allocation concealment source text {number}.") for number in range(1, 5)
        )
    )
    policy = EvidenceSearchPolicy(
        estimated_token_target=700,
        serialized_byte_ceiling=2_800,
        candidate_ceiling=1,
        oversized_candidate_byte_ceiling=3_000,
        high_cost_page_threshold=2,
    )
    page = index.search_v2(SearchQuery(terms=("allocation",)), policy=policy)

    payload = page.model_dump(mode="json")
    assert "unit" not in payload["candidates"][0]
    assert payload["candidates"][0]["source_snippet"].lower().find("allocation") >= 0
    compact = page.model_facing_payload()
    assert page.serialized_response_bytes == len(canonical_json_bytes(compact))
    assert compact["source_diagnostics"]
    candidate = compact["candidates"][0]
    assert compact["catalog"]["candidates_citable"] is False
    assert compact["catalog"]["candidate_read_action"] == "read_evidence"
    assert candidate["source_ref"] == 0
    assert compact["catalog"]["sources"][0]["source_id"] == page.candidates[0].source_id
    assert page.estimated_response_tokens == (page.serialized_response_bytes + 3) // 4
    assert page.serialized_response_bytes <= (
        policy.oversized_candidate_byte_ceiling
        if "oversized_candidate" in page.limiting_bounds
        else policy.serialized_byte_ceiling
    )
    assert page.candidate_ids == tuple(candidate.candidate_id for candidate in page.candidates)
    assert page.continuation is not None
    assert page.traversal_cost.decision_required is True

    with pytest.raises(ValueError, match="reason code"):
        index.search_v2(
            SearchQuery(terms=("allocation",)),
            continuation=page.continuation,
            policy=policy,
        )
    second = index.search_v2(
        SearchQuery(terms=("allocation",)),
        continuation=page.continuation,
        continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
        policy=policy,
    )
    assert second.page_number == 2


def test_v2_continuations_bind_query_policy_and_snapshot(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "v2.sqlite3")
    index.replace_units((_unit(1, "Allocation concealment."), _unit(2, "Allocation schedule.")))
    policy = EvidenceSearchPolicy(candidate_ceiling=1)
    first = index.search_v2(SearchQuery(terms=("allocation",)), policy=policy)
    assert first.continuation is not None

    with pytest.raises(StaleSearchContinuation):
        index.search_v2(
            SearchQuery(terms=("concealment",)),
            continuation=first.continuation,
            policy=policy,
        )
    with pytest.raises(SearchPolicyMismatch):
        index.search_v2(
            SearchQuery(terms=("allocation",)),
            continuation=first.continuation,
            policy=policy.model_copy(update={"candidate_ceiling": 2}),
        )
    index.replace_units((_unit(1, "Allocation concealment changed."),))
    with pytest.raises(StaleSearchContinuation):
        index.search_v2(
            SearchQuery(terms=("allocation",)),
            continuation=first.continuation,
            policy=policy,
        )


def test_v2_source_diagnostics_include_query_wide_zero_hit_sources(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "source-diagnostics.sqlite3")
    first = _unit(1, "Allocation concealment.")
    second = _unit(2, "No matching terminology.").model_copy(
        update={"source_id": "source:nonmatching"}
    )
    index.replace_units((first, second))
    compact = index.search_v2(SearchQuery(terms=("allocation",))).model_facing_payload()
    diagnostics = compact["source_diagnostics"]
    assert len(diagnostics) == 2
    assert any(
        item.get("source_id") == "source:nonmatching" and item["candidate_count"] == 0
        for item in diagnostics
    )


def test_v2_duplicate_lineage_target_is_a_candidate_identity_not_a_unit_id(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "duplicate-target.sqlite3")
    unit = _unit(1, "Allocation concealment.").model_copy(
        update={"duplicate_group_id": "duplicate:one"}
    )
    index.replace_units((unit,))
    candidate = index.search_v2(SearchQuery(terms=("allocation",))).candidates[0]
    assert candidate.retained_duplicate_target_id == candidate.candidate_id
    assert candidate.retained_duplicate_target_id != candidate.canonical_unit_id


def test_v2_search_stabilizes_self_reporting_envelopes_at_digit_boundaries(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "digit-boundary.sqlite3")
    index.replace_units(
        tuple(_unit(number, f"Allocation {'x' * 180} {number:02d}") for number in range(1, 13))
    )
    policy = EvidenceSearchPolicy(
        candidate_ceiling=2,
        serialized_byte_ceiling=6_500,
        oversized_candidate_byte_ceiling=8_000,
        estimated_token_target=2_000,
    )
    page = index.search_v2(SearchQuery(terms=("allocation",)), policy=policy)
    pages = [page]
    while pages[-1].continuation is not None:
        pages.append(
            index.search_v2(
                SearchQuery(terms=("allocation",)),
                continuation=pages[-1].continuation,
                continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
                policy=policy,
            )
        )
    projected_bytes = sum(item.serialized_response_bytes for item in pages)
    projected_tokens = sum(item.estimated_response_tokens for item in pages)
    cumulative_bytes = 0
    cumulative_tokens = 0
    for number, materialized in enumerate(pages, start=1):
        cumulative_bytes += materialized.serialized_response_bytes
        cumulative_tokens += materialized.estimated_response_tokens
        assert materialized.serialized_response_bytes == len(
            canonical_json_bytes(materialized.model_facing_payload())
        )
        assert (
            materialized.estimated_response_tokens
            == (materialized.serialized_response_bytes + 3) // 4
        )
        assert materialized.page_number == number
        assert materialized.total_page_count == len(pages)
        assert materialized.current_cumulative_response_bytes == cumulative_bytes
        assert materialized.current_cumulative_estimated_tokens == cumulative_tokens
        assert materialized.projected_cumulative_response_bytes == projected_bytes
        assert materialized.projected_cumulative_estimated_tokens == projected_tokens
        assert materialized.remaining_page_count == len(pages) - number


def _exact_mcp_envelope_measure(page) -> tuple[int, int]:
    payload = v2_model_facing_operation_payload(
        SearchEvidenceResponse(
            operation_id="operation:" + "o" * 400,
            ledger_cursor="ledger:" + "l" * 400,
            affected_scope=("result:" + "r" * 400,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id="run:" + "n" * 400,
            page=page,
            coverage_progress=CoverageProgress(
                sq_id="sq:" + "q" * 400,
                required_seed_families=(),
                completed_seed_families=(),
                completed_passes=(SearchPassKind.GUIDANCE_SEED,),
                missing_passes=(),
                coverage_complete=False,
            ),
        )
    )
    accounting = payload["response_accounting"]
    return int(accounting["serialized_response_bytes"]), int(
        accounting["estimated_response_tokens"]
    )


def test_v2_search_packs_against_the_exact_long_identifier_mcp_envelope(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "long-envelope.sqlite3")
    source_id = "source:" + "s" * 400
    index.replace_units(
        tuple(
            _unit(number, f"Allocation detail {number}").model_copy(update={"source_id": source_id})
            for number in range(1, 4)
        )
    )
    policy = EvidenceSearchPolicy(
        candidate_ceiling=3,
        serialized_byte_ceiling=7_200,
        estimated_token_target=1_500,
        oversized_candidate_byte_ceiling=10_000,
    )
    first = index.search_v2(
        SearchQuery(terms=("allocation",)),
        policy=policy,
        envelope_measure=_exact_mcp_envelope_measure,
    )
    pages = [first]
    while pages[-1].continuation is not None:
        pages.append(
            index.search_v2(
                SearchQuery(terms=("allocation",)),
                continuation=pages[-1].continuation,
                continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
                policy=policy,
                envelope_measure=_exact_mcp_envelope_measure,
            )
        )
    assert len(pages) > 1
    for page in pages:
        exact_bytes, exact_tokens = _exact_mcp_envelope_measure(page)
        assert (page.serialized_response_bytes, page.estimated_response_tokens) == (
            exact_bytes,
            exact_tokens,
        )
        assert exact_tokens <= policy.estimated_token_target


def test_v2_search_rejects_an_irreducible_exact_envelope(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "irreducible-envelope.sqlite3")
    index.replace_units(
        (_unit(1, "Allocation detail").model_copy(update={"source_id": "source:" + "s" * 12_000}),)
    )
    with pytest.raises(OperationalRetrievalFailure, match="absolute response ceiling"):
        index.search_v2(
            SearchQuery(terms=("allocation",)),
            policy=EvidenceSearchPolicy(
                serialized_byte_ceiling=7_200,
                estimated_token_target=1_800,
                oversized_candidate_byte_ceiling=10_000,
            ),
            envelope_measure=_exact_mcp_envelope_measure,
        )
