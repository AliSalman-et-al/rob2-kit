"""Frozen public scale baseline for issue #143's Evidence-navigation shape."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pytest

from rob2_kit.application.contracts import (
    CoverageProgress,
    SearchEvidenceResponse,
    WorkflowCondition,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalPage,
    CanonicalUnitKind,
    EvidenceReadBatchItem,
    EvidenceReadBatchRequest,
    EvidenceReadBatchScope,
    EvidenceReadPolicy,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    ReadContextMode,
    SearchContinuationReason,
    SearchPolicy,
    SearchQuery,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.workflow import (
    SearchCoverageRecorder,
    SearchPassKind,
    SearchResultDisposition,
    SearchResultDispositionKind,
    SourceSearchCoverage,
    SourceSearchState,
    V2CandidateTriageRevision,
    V2EvidenceWorkflowState,
    V2IrrelevantReason,
    V2QueryAttemptKind,
    V2SearchAttempt,
    V2TriageBasis,
    V2TriageKind,
    materialize_evidence_claim,
    record_v2_page_exposure,
    start_v2_search_attempt,
    submit_v2_page_triage,
    verify_complete_search_coverage_receipt,
)
from tests.fixtures import reference

FIXTURE = Path(__file__).parent / "public_fixtures" / "issue143" / "scale-baseline.json"
BROAD_JUSTIFICATION = "Synthetic broad-term traversal is intentionally exhausted for baseline."


def _mcp_search_response(
    page, *, pass_kind: SearchPassKind, workflow: V2EvidenceWorkflowState
) -> dict[str, object]:
    """Measure the actual compact MCP operation envelope, not its nested page."""

    from rob2_kit.interfaces.mcp.server import _dump

    completed = tuple(
        attempt.pass_kind
        for attempt in workflow.attempts
        if attempt.kind is V2QueryAttemptKind.SELECTED
        and attempt.sq_id == "sq:synthetic-allocation"
    )
    return _dump(
        SearchEvidenceResponse(
            operation_id=f"operation:synthetic:{pass_kind.value}:{page.page_number}",
            ledger_cursor=f"ledger:synthetic:{pass_kind.value}:{page.page_number}",
            affected_scope=("result:synthetic",),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id="run:synthetic",
            page=page,
            coverage_progress=CoverageProgress(
                sq_id="sq:synthetic-allocation",
                required_seed_families=("seed:allocation",)
                if pass_kind is SearchPassKind.GUIDANCE_SEED
                else (),
                completed_seed_families=("seed:allocation",)
                if pass_kind is SearchPassKind.GUIDANCE_SEED
                else (),
                completed_passes=completed,
                missing_passes=tuple(item for item in SearchPassKind if item not in completed),
                coverage_complete=workflow.coverage_complete(),
            ),
        )
    )


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _block(
    text: str,
    *,
    order: int,
    role: str,
    kind: CanonicalUnitKind = CanonicalUnitKind.PARAGRAPH,
    page: int,
    duplicate_group_id: str | None = None,
    caption: str | None = None,
    headers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> CanonicalBlock:
    return CanonicalBlock(
        kind=kind,
        text=text,
        spatial=(20.0, float((order % 30) * 12), 560.0, float((order % 30) * 12 + 10)),
        reading_order=order,
        source_role=SourceRole(role),
        section_path=("Results",),
        hierarchy_path=("Results",),
        duplicate_group_id=duplicate_group_id,
        caption=caption,
        table_headers=headers,
        warnings=warnings,
    )


def _source_units(source: dict[str, object]) -> tuple:
    source_id = str(source["source_id"])
    role = str(source["role"])
    count = int(source["repetitive_units"])
    pages: dict[int, list[CanonicalBlock]] = {}
    for number in range(count):
        page = number // 20 + 1
        pages.setdefault(page, []).append(
            _block(
                f"Allocation terminology appears in synthetic background passage {number:03d}; "
                "this repetitive broad-query hit is scientifically irrelevant.",
                order=number * 2 + 1,
                role=role,
                page=page,
            )
        )
    final_page = count // 20 + 2
    extras = pages.setdefault(final_page, [])
    if role == SourceRole.PRIMARY_REPORT.value:
        extras.extend(
            (
                _block(
                    "Allocation was concealed by a central service before enrolment.",
                    order=501,
                    role=role,
                    page=final_page,
                ),
                _block(
                    "Allocation wording is ambiguous because the parser reading "
                    "order is uncertain.",
                    order=503,
                    role=role,
                    page=final_page,
                    warnings=("reading_order_uncertain", "parse_render_discrepancy"),
                ),
                _block(
                    "Allocation sequence duplicate lineage retained for explicit review.",
                    order=505,
                    role=role,
                    page=final_page,
                    duplicate_group_id="duplicate:synthetic-allocation-lineage",
                ),
                _block(
                    "Allocation sequence duplicate lineage retained for explicit review.",
                    order=507,
                    role=role,
                    page=final_page,
                    duplicate_group_id="duplicate:synthetic-allocation-lineage",
                ),
                _block(
                    "Allocation concealed | central service | yes",
                    order=509,
                    role=role,
                    page=final_page,
                    kind=CanonicalUnitKind.TABLE_ROW,
                    headers=("Allocation", "Method", "Confirmed"),
                    caption="Table 2. Allocation implementation details.",
                ),
                _block(
                    "open | local envelope | no",
                    order=511,
                    role=role,
                    page=final_page,
                    kind=CanonicalUnitKind.TABLE_ROW,
                    headers=("Allocation", "Method", "Confirmed"),
                    caption="Table 2. Allocation implementation details.",
                ),
                _block(
                    "allocation " + ("source-authored-long-unit " * 430),
                    order=513,
                    role=role,
                    page=final_page + 1,
                    warnings=("long_unit_requires_windowed_read",),
                ),
            )
        )
    elif role == SourceRole.PROTOCOL.value:
        extras.append(
            _block(
                "Randomization used a concealed allocation schedule defined before recruitment.",
                order=501,
                role=role,
                page=final_page,
            )
        )
    else:
        extras.append(
            _block(
                "A later supplement describes an open allocation envelope, "
                "contradicting the report.",
                order=501,
                role=role,
                page=final_page,
            )
        )
    return canonicalize_evidence_units(
        source_id=source_id,
        source_artifact_hash=canonical_hash({"public_fixture_source": source_id}),
        parse_id=f"parse:{source_id.removeprefix('source:')}",
        pages=tuple(
            CanonicalPage(page=page, blocks=tuple(blocks)) for page, blocks in pages.items()
        ),
    )


def _units(workload: dict[str, object]) -> tuple:
    return tuple(unit for source in workload["sources"] for unit in _source_units(source))  # type: ignore[index]


def _response_bytes(value: object) -> int:
    return len(canonical_json_bytes(value))


def _estimated_tokens(byte_count: int) -> int:
    return (byte_count + 3) // 4


def _all_pages(
    index: EvidenceSearchIndex,
    query: SearchQuery,
    *,
    justification: str | None,
) -> Iterable:
    cursor = None
    while True:
        page = index.search(query, cursor=cursor, broad_query_justification=justification)
        yield page
        cursor = page.next_cursor
        if cursor is None:
            return


def _measure(tmp_path: Path, fixture: dict[str, object]) -> dict[str, object]:
    workload = fixture["workload"]
    assert isinstance(workload, dict)
    units = _units(workload)
    index = EvidenceSearchIndex(tmp_path / "issue143.sqlite3")
    snapshot_hash = index.replace_units(units)
    policy = SearchPolicy()
    recorder = SearchCoverageRecorder(
        receipt_id="coverage:issue143-synthetic",
        sq_id="sq:synthetic-allocation",
        snapshot_hash=snapshot_hash,
        policy_id=policy.policy_id,
        policy_hash=canonical_hash(policy),
        result_spec=reference("issue143-result-spec"),
        source_inventory=reference("issue143-source-inventory"),
        parse_record_hashes=tuple(sorted({unit.source_artifact_hash for unit in units})),
        guidance_release_id="guidance:rob2-2019.1",
        required_seed_families=("seed:allocation",),
        sources=tuple(
            SourceSearchCoverage(
                source_id=str(source["source_id"]),
                state=SourceSearchState.SEARCHED,
                sufficiently_readable=True,
            )
            for source in workload["sources"]  # type: ignore[index]
        ),
        inventory_source_ids=tuple(str(source["source_id"]) for source in workload["sources"]),  # type: ignore[index]
    )
    responses: list[tuple[str, object]] = []
    query_pages: dict[str, list] = {}
    for specification in workload["queries"]:  # type: ignore[index]
        pass_kind = SearchPassKind(specification["pass_kind"])
        query = SearchQuery(terms=tuple(specification["terms"]))
        pages = list(
            _all_pages(
                index,
                query,
                justification=BROAD_JUSTIFICATION
                if pass_kind is SearchPassKind.GUIDANCE_SEED
                else None,
            )
        )
        query_pages[pass_kind.value] = pages
        cursor = None
        for page_number, page in enumerate(pages, start=1):
            responses.append((f"search:{pass_kind.value}:{page_number}", page))
            recorder.record_page(
                page,
                index=index,
                query=query,
                pass_kind=pass_kind,
                seed_family=specification.get("seed_family"),
                cursor=cursor,
                broad_query_justification=(
                    BROAD_JUSTIFICATION if pass_kind is SearchPassKind.GUIDANCE_SEED else None
                ),
            )
            cursor = page.next_cursor
    returned = recorder.returned_unit_ids()
    supporting = next(unit for unit in units if unit.text.startswith("Allocation was concealed"))
    contradicting = next(unit for unit in units if unit.text.startswith("A later supplement"))
    ambiguous = next(unit for unit in units if "ambiguous" in unit.text)
    duplicate = next(
        unit for unit in units if unit.duplicate_group_id is not None and unit.unit_id in returned
    )
    table = next(unit for unit in units if unit.kind is CanonicalUnitKind.TABLE_ROW)
    oversized = next(unit for unit in units if len(unit.text) > 8_000)
    handles = {
        hit.unit.unit_id: hit.location_handle
        for pages in query_pages.values()
        for page in pages
        for hit in page.hits
    }
    for label, unit in (
        ("supporting", supporting),
        ("contradicting", contradicting),
        ("ambiguous", ambiguous),
    ):
        read = index.read_location(handles[unit.unit_id])
        responses.append((f"read_location:{label}", read))
    table_context = index.read_context(
        table.unit_id, mode=ReadContextMode.NEIGHBORS, neighbor_limit=2
    )
    oversized_context = index.read_context(
        oversized.unit_id, mode=ReadContextMode.UNIT, character_target=8_000
    )
    responses.extend(
        (("read_context:table", table_context), ("read_context:oversized", oversized_context))
    )
    for unit_id in returned:
        if unit_id in {supporting.unit_id, contradicting.unit_id, table.unit_id}:
            recorder.record_disposition(
                SearchResultDisposition(
                    unit_id=unit_id,
                    kind=SearchResultDispositionKind.RETAINED_CANDIDATE,
                    candidate_id=f"candidate:{unit_id.removeprefix('unit:')}",
                )
            )
        elif unit_id == duplicate.unit_id:
            recorder.record_disposition(
                SearchResultDisposition(
                    unit_id=unit_id,
                    kind=SearchResultDispositionKind.DUPLICATE,
                    duplicate_of=supporting.unit_id,
                )
            )
        else:
            recorder.record_disposition(
                SearchResultDisposition(
                    unit_id=unit_id, kind=SearchResultDispositionKind.IRRELEVANT
                )
            )
    receipt = recorder.freeze(completed_seed_families=("seed:allocation",))
    verify_complete_search_coverage_receipt(receipt, index=index)
    claims = (
        materialize_evidence_claim(
            claim_id="claim:synthetic-concealed",
            unit=supporting,
            span_start=0,
            span_end=len("Allocation was concealed"),
            claim_type="claim_type:allocation-concealment",
        ),
        materialize_evidence_claim(
            claim_id="claim:synthetic-open",
            unit=contradicting,
            span_start=contradicting.text.index("open"),
            span_end=contradicting.text.index("open") + len("open"),
            claim_type="claim_type:allocation-concealment",
        ),
    )
    response_metrics = [
        {"response": label, "serialized_utf8_bytes": _response_bytes(response)}
        for label, response in responses
    ]
    page_limits = [
        {
            "response": f"search:{pass_kind}:{number}",
            "hit_count": len(page.hits),
            "projection_character_count": page.character_count,
            "limiting_bound": (
                "oversized_unit"
                if page.oversized_unit_ids
                else "page_hit_target"
                if len(page.hits) == policy.page_hit_target and page.next_cursor is not None
                else "page_character_target"
                if page.character_count >= policy.page_character_target
                and page.next_cursor is not None
                else "exhausted"
            ),
        }
        for pass_kind, pages in query_pages.items()
        for number, page in enumerate(pages, start=1)
    ]
    review_operations = (
        {"candidate_id": supporting.unit_id, "disposition": "supporting"},
        {"candidate_id": contradicting.unit_id, "disposition": "contradicting"},
        {"candidate_id": ambiguous.unit_id, "disposition": "needs_visual_review"},
        {"candidate_id": duplicate.unit_id, "disposition": "duplicate"},
        {
            "candidate_id": next(
                unit_id
                for unit_id in returned
                if unit_id
                not in {
                    supporting.unit_id,
                    contradicting.unit_id,
                    ambiguous.unit_id,
                    duplicate.unit_id,
                }
            ),
            "disposition": "irrelevant",
        },
    )
    selected = tuple(
        disposition.candidate_id
        for disposition in receipt.result_dispositions
        if disposition.candidate_id is not None
    )
    return {
        "snapshot_hash": snapshot_hash,
        "old_policy_identity": policy.model_dump(mode="json"),
        "old_policy_hash": canonical_hash(policy),
        "search_calls_and_pages_to_exhaustion": {
            pass_kind: {"calls": len(pages), "pages": len(pages)}
            for pass_kind, pages in query_pages.items()
        },
        "read_calls_used_by_scripted_review_path": len(response_metrics)
        - sum(len(pages) for pages in query_pages.values()),
        "review_disposition_operations": review_operations,
        "per_response_complete_serialized_utf8_bytes": response_metrics,
        "estimated_model_facing_tokens": {
            "estimator_id": "utf8-byte-div4-ceil:v1",
            "total": sum(
                _estimated_tokens(item["serialized_utf8_bytes"]) for item in response_metrics
            ),
            "per_response": [
                {
                    "response": item["response"],
                    "tokens": _estimated_tokens(item["serialized_utf8_bytes"]),
                }
                for item in response_metrics
            ],
        },
        "candidate_counts": {
            "returned_hits_across_passes": sum(
                len(page.hits) for pages in query_pages.values() for page in pages
            ),
            "unique_candidate_universe": len(returned),
            "retained_candidates": len(selected),
            "duplicate_lineage_groups": len(
                {unit.duplicate_group_id for unit in units if unit.duplicate_group_id}
            ),
        },
        "source_character_counts": {
            source_id: sum(len(unit.text) for unit in units if unit.source_id == source_id)
            for source_id in sorted({unit.source_id for unit in units})
        },
        "limiting_bound_under_old_policy": {
            "page_hit_target": policy.page_hit_target,
            "page_character_target": policy.page_character_target,
            "pages": page_limits,
            "max_complete_response_serialized_utf8_bytes": max(
                item["serialized_utf8_bytes"] for item in response_metrics
            ),
        },
        "ordered_candidate_universe_hash": canonical_hash(returned),
        "scientific_equivalence_evidence": {
            "selection_semantics_version": "synthetic-exact-span-selection:1",
            "selected_candidate_ids": selected,
            "selected_candidate_hash": canonical_hash(selected),
            "exact_claim_hash": canonical_hash(
                [claim.model_dump(mode="json", exclude={"canonical_unit"}) for claim in claims]
            ),
            "review_disposition_hash": canonical_hash(review_operations),
        },
        "coverage_receipt_hash": receipt.content_hash,
        "shape_evidence": {
            "oversized_context": oversized_context.oversized,
            "table_context_has_caption": table_context.unit.caption is not None,
            "table_context_neighbor_count": len(table_context.neighbors),
            "ambiguous_warnings": ambiguous.warnings,
            "source_roles": sorted({unit.source_role.value for unit in units if unit.source_role}),
            "unit_count": len(units),
            "source_ids": sorted({unit.source_id for unit in units}),
        },
    }


def _measure_v2(tmp_path: Path, fixture: dict[str, object]) -> dict[str, object]:
    """Replay the public shape through v2 navigation without application state."""

    workload = fixture["workload"]
    assert isinstance(workload, dict)
    units = _units(workload)
    index = EvidenceSearchIndex(tmp_path / "issue143-v2.sqlite3")
    snapshot_hash = index.replace_units(units)
    search_policy = EvidenceSearchPolicy()
    read_policy = EvidenceReadPolicy()
    workflow = V2EvidenceWorkflowState(
        result_id="result:synthetic",
        domain_id="domain:synthetic",
        snapshot_hash=snapshot_hash,
        search_policy_id=search_policy.policy_id,
        search_policy_hash=canonical_hash(search_policy),
    )
    responses: list[tuple[str, object]] = []
    candidates = []
    exposed_pages = []
    handles: dict[str, str] = {}
    for specification in workload["queries"]:  # type: ignore[index]
        pass_kind = SearchPassKind(specification["pass_kind"])
        query = SearchQuery(terms=tuple(specification["terms"]))
        attempt_id = f"attempt:synthetic:{pass_kind.value}"
        attempt = V2SearchAttempt(
            attempt_id=attempt_id,
            sq_id="sq:synthetic-allocation",
            pass_kind=pass_kind,
            query=query,
            query_hash=canonical_hash(query),
            kind=V2QueryAttemptKind.SELECTED,
        )
        workflow = start_v2_search_attempt(workflow, attempt)
        continuation = None
        pages = []

        def exact_envelope_measure(candidate_page) -> tuple[int, int]:
            payload = _mcp_search_response(
                candidate_page, pass_kind=pass_kind, workflow=workflow
            )
            accounting = payload["response_accounting"]
            return (
                int(accounting["serialized_response_bytes"]),
                int(accounting["estimated_response_tokens"]),
            )

        while True:
            page = index.search_v2(
                query,
                policy=search_policy,
                continuation=continuation,
                continue_reason=(
                    SearchContinuationReason.COVERAGE_REQUIRES_BREADTH
                    if continuation is not None
                    else None
                ),
                envelope_measure=exact_envelope_measure,
            )
            pages.append(page)
            workflow = record_v2_page_exposure(workflow, attempt_id=attempt_id, page=page)
            responses.append(
                (
                    f"search:{pass_kind.value}:{page.page_number}",
                    _mcp_search_response(page, pass_kind=pass_kind, workflow=workflow),
                )
            )
            candidates.extend(page.candidates)
            exposed_pages.append(page)
            handles.update(
                {
                    candidate.canonical_unit_id: candidate.location_handle
                    for candidate in page.candidates
                }
            )
            continuation = page.continuation
            if continuation is None:
                break
        del pages
    supporting = next(unit for unit in units if unit.text.startswith("Allocation was concealed"))
    contradicting = next(unit for unit in units if unit.text.startswith("A later supplement"))
    selected_unit_ids = {
        supporting.unit_id,
        contradicting.unit_id,
        next(unit.unit_id for unit in units if unit.kind is CanonicalUnitKind.TABLE_ROW),
    }
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    risky = {
        candidate.canonical_unit_id
        for candidate in candidates_by_id.values()
        if (
            candidate.left_omitted_character_count
            or candidate.right_omitted_character_count
            or candidate.undisplayed_match_count
            or candidate.warnings
            or candidate.table_headers
            or candidate.caption is not None
            or candidate.triage_flags.has_reading_order_uncertainty
            or candidate.triage_flags.has_visual_uncertainty
            or candidate.triage_flags.has_duplicate_lineage
        )
    }.union(selected_unit_ids)
    batch = EvidenceReadBatchRequest(
        scope=EvidenceReadBatchScope(
            result_id="result:synthetic", domain_id="domain:synthetic", snapshot_hash=snapshot_hash
        ),
        items=tuple(
            EvidenceReadBatchItem(
                location_handle=handles[unit.unit_id],
                question_ids=("sq:synthetic-allocation",),
            )
            for unit_id in sorted(risky)
            for unit in (next(unit for unit in units if unit.unit_id == unit_id),)
        ),
    )
    read_page = index.read_batch_v2(batch, policy=read_policy)
    responses.append(("read:scripted-review", read_page))
    receipts = {
        candidates_by_id[
            next(
                candidate_id
                for candidate_id, candidate in candidates_by_id.items()
                if candidate.location_handle == outcome.location_handle
            )
        ].canonical_unit_id: outcome.view.read_view_receipt
        for outcome in read_page.outcomes
        if outcome.view is not None
    }
    attempts_by_id = {attempt.attempt_id: attempt for attempt in workflow.attempts}
    revisions = tuple(
        V2CandidateTriageRevision(
            revision_id=(
                f"triage:synthetic:{edge.attempt_id}:{edge.page_handle}:{edge.candidate_id}"
            ),
            candidate_id=edge.candidate_id,
            attempt_id=edge.attempt_id,
            sq_id=attempts_by_id[edge.attempt_id].sq_id,
            page_handle=edge.page_handle,
            kind=(
                V2TriageKind.RETAINED
                if candidate.canonical_unit_id in selected_unit_ids
                else V2TriageKind.IRRELEVANT
            ),
            irrelevant_reason=(
                None
                if candidate.canonical_unit_id in selected_unit_ids
                else V2IrrelevantReason.LEXICAL_FALSE_POSITIVE
            ),
            basis=(
                None
                if candidate.canonical_unit_id in selected_unit_ids
                else (
                    V2TriageBasis.READ_VIEW_RECEIPT
                    if candidate.canonical_unit_id in receipts
                    else V2TriageBasis.PREVIEW
                )
            ),
            read_view_receipt=receipts.get(candidate.canonical_unit_id),
        )
        for edge in workflow.exposures
        for candidate in (candidates_by_id[edge.candidate_id],)
    )
    workflow = submit_v2_page_triage(
        workflow,
        submission_id="submission:synthetic:all-pages",
        page_handles=tuple(page.page_handle for page in exposed_pages),
        revisions=revisions,
    )
    responses.extend(
        (
            ("review:all-pages", workflow.triage_submissions[-1]),
            (
                "review-progress:all-pages",
                {
                    "coverage_complete": workflow.coverage_complete(),
                    "freeze_valid": workflow.freeze_valid(),
                    "outstanding_triage_candidate_ids": workflow.outstanding_triage_candidate_ids(),
                },
            ),
        )
    )
    canonical_universe = tuple(
        dict.fromkeys(candidate.canonical_unit_id for candidate in candidates)
    )
    selected = tuple(sorted(selected_unit_ids))
    claims = (
        materialize_evidence_claim(
            claim_id="claim:synthetic-concealed",
            unit=supporting,
            span_start=0,
            span_end=len("Allocation was concealed"),
            claim_type="claim_type:allocation-concealment",
        ),
        materialize_evidence_claim(
            claim_id="claim:synthetic-open",
            unit=contradicting,
            span_start=contradicting.text.index("open"),
            span_end=contradicting.text.index("open") + len("open"),
            claim_type="claim_type:allocation-concealment",
        ),
    )
    metrics = [
        {"response": label, "serialized_utf8_bytes": _response_bytes(response)}
        for label, response in responses
    ]
    category_totals = {
        category: sum(
            _estimated_tokens(item["serialized_utf8_bytes"])
            for item in metrics
            if item["response"].startswith(category)
        )
        for category in ("search", "read", "review")
    }
    return {
        "navigation_contract_version": "2.0.0",
        "snapshot_hash": snapshot_hash,
        "search_policy_hash": canonical_hash(search_policy),
        "read_policy_hash": canonical_hash(read_policy),
        "per_response_complete_serialized_utf8_bytes": metrics,
        "estimated_model_facing_tokens": {
            "estimator_id": "utf8-byte-div4-ceil:v1",
            "total": sum(_estimated_tokens(item["serialized_utf8_bytes"]) for item in metrics),
            "by_response_category": category_totals,
        },
        "candidate_counts": {
            "returned_across_passes": len(candidates),
            "unique_canonical_unit_universe": len(canonical_universe),
        },
        "ordered_canonical_unit_universe_hash": canonical_hash(canonical_universe),
        "scientific_equivalence_evidence": {
            "selected_underlying_unit_ids": selected,
            "selected_underlying_unit_hash": canonical_hash(selected),
            "exact_claim_hash": canonical_hash(
                [claim.model_dump(mode="json", exclude={"canonical_unit"}) for claim in claims]
            ),
        },
    }


def test_issue143_frozen_old_contract_navigation_baseline(tmp_path: Path) -> None:
    fixture = _fixture()
    measured = _measure(tmp_path, fixture)
    old_policy = {
        "identity": measured.pop("old_policy_identity"),
        "hash": measured.pop("old_policy_hash"),
    }
    measured_json = json.loads(canonical_json_bytes(measured))
    if not fixture["baseline"]:
        pytest.fail(
            "Populate frozen baseline with:\n" + json.dumps(measured_json, indent=2, sort_keys=True)
        )
    assert fixture["old_policy"] == old_policy
    assert measured_json == fixture["baseline"]


def test_issue143_predeclared_improvement_gate_is_scientifically_strict(tmp_path: Path) -> None:
    fixture = _fixture()
    measured = _measure(tmp_path, fixture)
    target = fixture["later_policy_improvement_target"]
    assert target["not_chaarted_empirical_target"] is True
    assert (
        target["maximum_per_response_serialized_utf8_bytes"]
        == measured["limiting_bound_under_old_policy"][
            "max_complete_response_serialized_utf8_bytes"
        ]
    )
    assert target["hard_gates"] == {
        "candidate_loss": 0,
        "candidate_duplication": 0,
        "identical_scientific_selection_semantics": True,
        "no_relaxation_of_old_maximum_response_bytes": True,
    }
    assert target["minimum_estimated_model_facing_token_reduction_fraction"] == 0.30
    assert measured["shape_evidence"]["oversized_context"] is True
    assert measured["shape_evidence"]["table_context_has_caption"] is True
    assert "reading_order_uncertain" in measured["shape_evidence"]["ambiguous_warnings"]


def test_issue143_v2_navigation_compaction_meets_the_frozen_gate(tmp_path: Path) -> None:
    fixture = _fixture()
    legacy = fixture["baseline"]
    target = fixture["later_policy_improvement_target"]
    assert isinstance(legacy, dict)
    assert isinstance(target, dict)
    measured = _measure_v2(tmp_path, fixture)

    # The full candidate page remains typed and durable.  This is deliberately
    # the compact MCP/model projection plus the ordered batch-read and one
    # exhaustive review submission—the public v2 workflow a capable agent uses.
    assert json.loads(canonical_json_bytes(measured)) == fixture["v2_measured"]
    max_response = max(
        item["serialized_utf8_bytes"]
        for item in measured["per_response_complete_serialized_utf8_bytes"]
    )
    assert max_response <= target["maximum_per_response_serialized_utf8_bytes"]
    assert (
        measured["estimated_model_facing_tokens"]["total"] * 100
        <= legacy["estimated_model_facing_tokens"]["total"] * 70
    )
    assert measured["candidate_counts"] == {
        "returned_across_passes": legacy["candidate_counts"]["returned_hits_across_passes"],
        "unique_canonical_unit_universe": legacy["candidate_counts"]["unique_candidate_universe"],
    }
    assert (
        measured["ordered_canonical_unit_universe_hash"]
        == legacy["ordered_candidate_universe_hash"]
    )
    legacy_selected = tuple(
        sorted(
            candidate_id.replace("candidate:", "unit:", 1)
            for candidate_id in legacy["scientific_equivalence_evidence"]["selected_candidate_ids"]
        )
    )
    assert (
        measured["scientific_equivalence_evidence"]["selected_underlying_unit_ids"]
        == legacy_selected
    )
    assert (
        measured["scientific_equivalence_evidence"]["exact_claim_hash"]
        == legacy["scientific_equivalence_evidence"]["exact_claim_hash"]
    )
