"""Observable policy-3 Search packing and returned-envelope contracts."""

from __future__ import annotations

import itertools

import pytest

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    CoverageProgress,
    SearchEvidenceRequest,
    SearchEvidenceResponse,
    WorkflowCondition,
    finalize_search_evidence_response,
    v2_model_facing_operation_payload,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.errors import OperationalRetrievalFailure, StaleSearchContinuation
from rob2_kit.evidence.search import (
    EVIDENCE_SEARCH_PACKING_ESTIMATOR_ID,
    EVIDENCE_SEARCH_POLICY_ID,
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    SearchContinuationReason,
    SearchPackingContext,
    SearchQuery,
    _maximum_coverage_progress_payload,
)
from rob2_kit.evidence.workflow import SearchPassKind, V2QueryAttemptKind
from tests.test_input_reconciliation import (
    _classify_current_sources,
    _config,
    _prepare_confirm,
    _result,
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


def _coverage(*passes: SearchPassKind) -> CoverageProgress:
    selected = tuple(passes)
    return CoverageProgress(
        sq_id="sq:one",
        required_seed_families=("seed:allocation",),
        completed_seed_families=("seed:allocation",)
        if SearchPassKind.GUIDANCE_SEED in selected
        else (),
        completed_passes=selected,
        missing_passes=tuple(item for item in SearchPassKind if item not in selected),
        coverage_complete=len(selected) == len(SearchPassKind),
    )


def test_policy_3_has_a_distinct_stable_packing_estimator() -> None:
    policy = EvidenceSearchPolicy()
    assert policy.policy_id == EVIDENCE_SEARCH_POLICY_ID == "policy:evidence-search-3.0.0"
    assert policy.packing_estimator_id == EVIDENCE_SEARCH_PACKING_ESTIMATOR_ID


def test_packing_context_reserves_every_coverage_progress_shape() -> None:
    maximum = _maximum_coverage_progress_payload()
    maximum_size = len(canonical_json_bytes(maximum))
    passes = tuple(SearchPassKind)
    for count in range(len(passes) + 1):
        for selected in itertools.combinations(passes, count):
            actual = _coverage(*selected).model_dump(mode="json")
            assert len(canonical_json_bytes(actual)) <= maximum_size
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
    first = index.search_v2(SearchQuery(terms=("allocation",)), policy=policy)
    pages = [first]
    while pages[-1].continuation:
        pages.append(
            index.search_v2(
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
    assert index.search_v2(SearchQuery(terms=("absent",)), policy=policy).condition == "zero_hits"
    oversized = EvidenceSearchIndex(tmp_path / "oversized.sqlite3")
    oversized.replace_units(
        (
            _unit(1, "Allocation " + "z" * 6_000).model_copy(
                update={"source_id": "source:" + "z" * 3_000}
            ),
        )
    )
    page = oversized.search_v2(
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
    first = index.search_v2(SearchQuery(terms=("allocation",)), policy=policy)
    second = index.search_v2(
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


def test_prior_policy_token_decodes_as_stale_cursor_under_policy_3(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    snapshot = index.replace_units((_unit(1), _unit(2)))
    query = SearchQuery(terms=("allocation",))
    old = EvidenceSearchPolicy(policy_id="policy:evidence-search-2.0.0")
    token = index._issue_stable_token(
        "v2cur",
        {
            "snapshot": snapshot,
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
        index.search_v2(query, continuation=token, policy=EvidenceSearchPolicy())
    assert error.value.code == "stale_cursor"


def test_underestimated_reservation_fails_after_selection_without_repacking(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "index.sqlite3")
    index.replace_units((_unit(1),))
    page = index.search_v2(SearchQuery(terms=("allocation",)))
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
        page=index.search_v2(SearchQuery(terms=("allocation",))),
        coverage_progress=_coverage(),
    )
    finalized = finalize_search_evidence_response(response)
    wire = v2_model_facing_operation_payload(finalized)
    accounting = wire["response_accounting"]
    assert finalized.page.serialized_response_bytes == accounting["serialized_response_bytes"]
    assert finalized.page.estimated_response_tokens == accounting["estimated_response_tokens"]
    assert (
        int(accounting["estimated_response_tokens"]) == (len(canonical_json_bytes(wire)) + 3) // 4
    )


def test_run_engine_continuation_survives_unrelated_coverage_progress(tmp_path) -> None:
    """Exercise the production persistence/finalizer path after progress changes."""
    trial = tmp_path / "input" / "scope"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_text("primary allocation detail", encoding="utf-8")
    engine, run_id = _prepare_confirm(
        tmp_path, config=_config(_result("result:scope", "trial:scope"))
    )
    _classify_current_sources(engine, run_id)
    # Narrow authoritative test setup: retain the issued Source/Parse lineage
    # but widen the indexed unit inventory to force a continuation.
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    with index._connect() as connection:
        row = connection.execute(
            "SELECT source_id, source_artifact_hash, parse_id FROM evidence_units LIMIT 1"
        ).fetchone()
    assert row is not None
    index.replace_units(
        tuple(
            _unit(number, "primary allocation detail").model_copy(
                update={
                    "source_id": row["source_id"],
                    "source_artifact_hash": row["source_artifact_hash"],
                    "parse_id": row["parse_id"],
                }
            )
            for number in range(1, 17)
        )
    )
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    request = SearchEvidenceRequest(
        contract_version="2.0.0",
        run_id=run_id,
        work_token=work.work_token,
        result_id="result:scope",
        sq_id="sq:randomization:sequence",
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:scope",
        query=SearchQuery(terms=("primary",)),
        attempt_id="attempt:guidance",
        attempt_kind=V2QueryAttemptKind.SELECTED,
    )
    first = engine.search_evidence(request)
    assert first.page.continuation is not None
    first_wire = v2_model_facing_operation_payload(first)
    assert (
        len(canonical_json_bytes(first_wire))
        <= first.page.traversal_cost.response_bytes_upper_bound
    )
    engine.search_evidence(
        request.model_copy(
            update={
                "pass_kind": SearchPassKind.TRIAL_FOLLOW_UP,
                "seed_family": None,
                "attempt_id": "attempt:follow-up",
                "query": SearchQuery(terms=("allocation",)),
            }
        )
    )
    second = engine.search_evidence(
        request.model_copy(
            update={
                "continuation": first.page.continuation,
                "continue_reason": SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
            }
        )
    )
    assert second.page.prior_candidate_count == first.page.returned_candidate_count
    assert second.coverage_progress.completed_passes != first.coverage_progress.completed_passes
    wire = v2_model_facing_operation_payload(second)
    accounting = wire["response_accounting"]
    assert accounting["serialized_response_bytes"] == len(canonical_json_bytes(wire))
    assert accounting["estimated_response_tokens"] == (len(canonical_json_bytes(wire)) + 3) // 4
    assert len(canonical_json_bytes(wire)) <= second.page.traversal_cost.response_bytes_upper_bound
    assert second.page.traversal_cost.current_cumulative_response_bytes_upper_bound >= (
        first.page.serialized_response_bytes + second.page.serialized_response_bytes
    )
