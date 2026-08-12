"""Observable stable Search packing and returned-envelope contracts."""

from __future__ import annotations

import pytest

from rob2_kit.application.contracts import (
    SearchEvidenceResponse,
    WorkflowCondition,
    finalize_search_evidence_response,
    model_facing_operation_payload,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.errors import (
    OperationalRetrievalFailure,
    StaleSearchContinuation,
    UnsupportedEvidenceNavigationContract,
)
from rob2_kit.evidence.search import (
    EVIDENCE_SEARCH_PACKING_ESTIMATOR_ID,
    EVIDENCE_SEARCH_POLICY_ID,
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceReadBatchItem,
    EvidenceReadBatchRequest,
    EvidenceReadBatchScope,
    EvidenceReadPolicy,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    SearchContinuationReason,
    SearchPackingContext,
    SearchQuery,
    _maximum_coverage_progress_payload,
    compact_coverage_progress,
)


def _unit(number: int, text: str = "Allocation detail") -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=f"unit:{number}",
        source_id="source:one",
        source_artifact_hash=canonical_hash({"source": 1}),
        parse_id="parse:one",
        page=number,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=f"{text} {number}",
        fragment_ids=(f"fragment:{number}",),
    )


def _coverage(*, ready: bool = False, blocked: bool = True) -> dict[str, object]:
    return {
        "question_id": "question:one",
        "question_ready": ready,
        "propositions": (
            {
                "proposition_id": "proposition:allocation-concealment",
                "passes": (
                    {
                        "pass_id": "pass:direct",
                        "active": True,
                        "stages": (
                            {
                                "stage_id": "stage:direct",
                                "active": True,
                                "outcome": "satisfied" if not blocked else None,
                                "intents": (),
                                "blockers": ("stage_outcome_missing",) if blocked else (),
                            },
                        ),
                    },
                ),
            },
        ),
    }


def test_policy_4_has_a_distinct_stable_packing_estimator() -> None:
    policy = EvidenceSearchPolicy()
    assert policy.policy_id == EVIDENCE_SEARCH_POLICY_ID == "policy:evidence-search-4.0.0"
    assert policy.packing_estimator_id == EVIDENCE_SEARCH_PACKING_ESTIMATOR_ID


def test_packing_context_reserves_compact_v3_coverage_progress_shapes() -> None:
    maximum = _maximum_coverage_progress_payload()
    maximum_size = len(canonical_json_bytes(compact_coverage_progress(maximum)))
    for actual in (_coverage(), _coverage(ready=True, blocked=False)):
        assert len(canonical_json_bytes(compact_coverage_progress(actual))) <= maximum_size
    context = SearchPackingContext(
        operation_id="operation:search",
        run_id="run:one",
        affected_scope=("result:one",),
        condition="completed",
        committed=False,
        policy_id=EvidenceSearchPolicy().policy_id,
        policy_hash=canonical_hash(EvidenceSearchPolicy()),
        snapshot_hash="sha256:" + "a" * 64,
        coverage_progress_maximum=maximum,
    )
    assert context.ledger_cursor_maximum == "ledger:18446744073709551615"


def test_search_ledger_cursor_publishes_actual_u64_value_and_rejects_invalid_counts() -> None:
    assert RunEngine._search_ledger_cursor(5) == "ledger:5"
    assert RunEngine._search_ledger_cursor(2**64 - 1) == "ledger:18446744073709551615"
    for invalid in (-1, 2**64):
        with pytest.raises(OperationalRetrievalFailure, match="u64 reservation"):
            RunEngine._search_ledger_cursor(invalid)


def test_zero_hits_digit_boundaries_and_oversized_singleton_are_stable(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    index.replace_units(tuple(_unit(number, "Allocation " + "x" * 200) for number in range(1, 13)))
    policy = EvidenceSearchPolicy(
        candidate_ceiling=1,
        serialized_byte_ceiling=4_000,
        estimated_token_target=1_000,
        oversized_candidate_byte_ceiling=8_000,
    )
    first = index.search_page(SearchQuery(terms=("allocation",)), policy=policy)
    pages = [first]
    while pages[-1].continuation:
        pages.append(
            index.search_page(
                SearchQuery(terms=("allocation",)),
                policy=policy,
                continuation=pages[-1].continuation,
                continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
            )
        )
    assert [page.page_number for page in pages] == list(range(1, len(pages) + 1))
    assert all(page.total_page_count == len(pages) for page in pages)
    reservations = [page.traversal_cost.response_bytes_upper_bound for page in pages]
    assert all(
        page.traversal_cost.current_cumulative_response_bytes_upper_bound
        == sum(reservations[:number])
        for number, page in enumerate(pages, start=1)
    )
    assert all(
        page.traversal_cost.projected_cumulative_response_bytes_upper_bound == sum(reservations)
        for page in pages
    )
    assert all(
        sum(item.serialized_response_bytes for item in pages[:number])
        <= page.traversal_cost.current_cumulative_response_bytes_upper_bound
        for number, page in enumerate(pages, start=1)
    )
    assert index.search_page(SearchQuery(terms=("absent",)), policy=policy).condition == "zero_hits"
    oversized = EvidenceSearchIndex(tmp_path / "oversized.sqlite3")
    oversized.replace_units(
        (
            _unit(1, "Allocation " + "z" * 6_000).model_copy(
                update={"source_id": "source:" + "z" * 3_000}
            ),
        )
    )
    page = oversized.search_page(
        SearchQuery(terms=("allocation",)),
        policy=policy.model_copy(update={"oversized_candidate_byte_ceiling": 16_000}),
    )
    assert page.limiting_bounds == ("oversized_candidate",)


def test_mixed_page_reservations_sum_exactly_without_averaging(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "mixed.sqlite3")
    oversized = _unit(2, "Allocation detail").model_copy(
        update={
            "kind": CanonicalUnitKind.TABLE_ROW,
            "table_headers": ("z" * 5_000,),
        }
    )
    index.replace_units((_unit(1), oversized))
    policy = EvidenceSearchPolicy(
        candidate_ceiling=1,
        serialized_byte_ceiling=4_000,
        estimated_token_target=1_000,
        oversized_candidate_byte_ceiling=16_000,
    )
    first = index.search_page(SearchQuery(terms=("allocation",)), policy=policy)
    second = index.search_page(
        SearchQuery(terms=("allocation",)),
        policy=policy,
        continuation=first.continuation,
        continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
    )
    pages = (first, second)
    assert first.limiting_bounds != ("oversized_candidate",)
    assert second.limiting_bounds == ("oversized_candidate",)
    reservations = [page.traversal_cost.response_bytes_upper_bound for page in pages]
    assert first.traversal_cost.current_cumulative_response_bytes_upper_bound == reservations[0]
    assert second.traversal_cost.current_cumulative_response_bytes_upper_bound == sum(reservations)
    assert all(
        page.traversal_cost.projected_cumulative_response_bytes_upper_bound == sum(reservations)
        for page in pages
    )


def test_current_kind_stale_policy_token_decodes_as_stale_cursor(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    snapshot = index.replace_units((_unit(1), _unit(2)))
    query = SearchQuery(terms=("allocation",))
    old = EvidenceSearchPolicy(policy_id="policy:evidence-search-2.0.0")
    token = index._issue_stable_token(
        "search",
        {
            "snapshot": canonical_hash({"stale": "snapshot"}),
            "query": canonical_hash(query),
            "policy": canonical_hash(old),
            "scope": None,
            "issuance_context": None,
            "offset": 1,
            "reason_required": False,
            "packing_context": "sha256:" + "0" * 64,
        },
    )
    with pytest.raises(StaleSearchContinuation, match="earlier Evidence-search policy") as error:
        index.search_page(query, continuation=token, policy=EvidenceSearchPolicy())
    assert error.value.code == "stale_cursor"


def test_read_batch_policy_precedes_other_stale_token_bindings(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    snapshot = index.replace_units((_unit(1),))
    active = EvidenceReadPolicy()
    prior = EvidenceReadPolicy(policy_id="policy:evidence-read-" + "2.0.0")
    token = index._issue_token(
        "read-batch",
        {
            "snapshot": canonical_hash({"stale": "snapshot"}),
            "policy": canonical_hash(prior),
            "scope": canonical_hash({"stale": "scope"}),
            "request": canonical_hash({"stale": "request"}),
            "next_index": 0,
        },
    )
    request = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:one", domain_id="domain:one", snapshot_hash=snapshot
        ),
        items=(EvidenceReadBatchItem(
            location_handle="loc:unreached", question_ids=("sq:one",), source_ids=("source:one",)
        ),),
        continuation=token,
    )
    with pytest.raises(StaleSearchContinuation, match="different read policy"):
        index.read_batch(request, policy=active)


@pytest.mark.parametrize("suffix", ("cur", "page", "readcur", "itemread"))
def test_retired_token_kind_fails_as_an_unsupported_contract(tmp_path, suffix: str) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    index.replace_units((_unit(1),))
    with pytest.raises(UnsupportedEvidenceNavigationContract, match="supersede Preparation") as error:
        index.search_page(SearchQuery(terms=("allocation",)), continuation="v2" + suffix + ":old")
    assert error.value.code == "unsupported_contract"


def test_underestimated_reservation_fails_after_selection_without_repacking(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    index.replace_units((_unit(1),))
    page = index.search_page(SearchQuery(terms=("allocation",)))
    boundaries = page.candidate_ids
    tiny_cost = page.traversal_cost.model_copy(
        update={
            "projected_page_count": 1,
            "response_bytes_upper_bound": 1,
            "estimated_tokens_upper_bound": 1,
            "projected_cumulative_response_bytes_upper_bound": 1,
            "projected_cumulative_estimated_tokens_upper_bound": 1,
        }
    )
    response = SearchEvidenceResponse(
        operation_id="operation:one",
        ledger_cursor="ledger:18446744073709551615",
        affected_scope=("result:one",),
        condition=WorkflowCondition.COMPLETED,
        committed=False,
        run_id="run:one",
        page=page.model_copy(update={"traversal_cost": tiny_cost}),
        coverage_progress=_coverage(),
    )
    with pytest.raises(OperationalRetrievalFailure, match="stable packing reservation"):
        finalize_search_evidence_response(response)
    assert page.candidate_ids == boundaries


def test_finalized_search_wire_has_exact_page_and_outer_accounting(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    index.replace_units((_unit(1),))
    response = SearchEvidenceResponse(
        operation_id="operation:one",
        ledger_cursor="ledger:18446744073709551615",
        affected_scope=("result:one",),
        condition=WorkflowCondition.COMPLETED,
        committed=False,
        run_id="run:one",
        page=index.search_page(SearchQuery(terms=("allocation",))),
        coverage_progress=_coverage(),
    )
    finalized = finalize_search_evidence_response(response)
    wire = model_facing_operation_payload(finalized)
    accounting = wire["response_accounting"]
    assert finalized.page.serialized_response_bytes == accounting["serialized_response_bytes"]
    assert finalized.page.estimated_response_tokens == accounting["estimated_response_tokens"]
    assert (
        int(accounting["estimated_response_tokens"]) == (len(canonical_json_bytes(wire)) + 3) // 4
    )
