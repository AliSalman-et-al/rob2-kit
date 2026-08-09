from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.domain.evidence import (
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    ReviewedEvidenceContext,
    ReviewedEvidenceFragment,
    TrialAttribution,
)
from rob2_kit.domain.revisions import Actor, ActorKind, RecordReference
from rob2_kit.evidence import (
    CandidateDisposition,
    CandidateDispositionKind,
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    CanonicalWordBox,
    ConsiderationDisposition,
    ConsideredEvidenceItem,
    DerivedFactInput,
    DocumentZone,
    EvidenceSearchIndex,
    ExecutedSearchQuery,
    SearchCoverageReceipt,
    SearchCoverageRecorder,
    SearchPassKind,
    SearchPolicy,
    SearchQuery,
    SearchResultDisposition,
    SearchResultDispositionKind,
    SourceSearchCoverage,
    SourceSearchState,
    VisualCandidateCoverage,
    VisualGate,
    build_consideration_manifest,
    canonicalize_evidence_units,
    derive_fact,
    freeze_evidence_bundle,
    materialize_evidence_claim,
    verify_complete_search_coverage_receipt,
)

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
ACTOR = Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="Test system")
HASH = "sha256:" + "a" * 64


def unit(number: int, text: str, *, page: int = 1) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=f"unit:report-{number:03}",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-initial",
        page=page,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        spatial=(10.0, 20.0, 500.0, 80.0),
        document_zone=DocumentZone.MAIN,
        section_path=("Methods",),
        hierarchy_path=("1",),
    )


def test_search_has_stable_order_and_snapshot_bound_cursors(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(
        (
            unit(2, "Allocation concealment was adequate."),
            unit(1, "Allocation was concealed using numbered envelopes."),
            unit(3, "Unrelated baseline information."),
        )
    )
    query = SearchQuery(terms=("allocation",), prefixes=("conceal",))
    policy = SearchPolicy(page_hit_target=1, page_character_target=8_000)

    first = index.search(query, policy=policy)
    second = index.search(query, policy=policy)

    assert [hit.unit.unit_id for hit in first.hits] == ["unit:report-002"]
    # next_cursor and each hit's location_handle are lookup-table tokens
    # issued fresh on every call (ADR-0011), so two calls with identical
    # inputs return equal *content* but different token strings.
    assert [hit.unit.unit_id for hit in second.hits] == ["unit:report-002"]
    assert first.model_copy(update={"next_cursor": None, "hits": ()}) == second.model_copy(
        update={"next_cursor": None, "hits": ()}
    )
    assert first.next_cursor is not None
    assert index.search(query, policy=policy, cursor=first.next_cursor).hits[0].unit.unit_id == (
        "unit:report-001"
    )

    index.replace_units((unit(1, "Allocation was concealed."),))
    with pytest.raises(ValueError, match="snapshot"):
        index.search(query, policy=policy, cursor=first.next_cursor)


def test_search_traverses_every_hit_beyond_one_page_and_resolves_projection_to_unit(
    tmp_path: Path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    long_text = "Allocation concealment sentence. " * 100
    index.replace_units(tuple(unit(number, long_text, page=number) for number in range(1, 46)))
    query = SearchQuery(phrases=("allocation concealment",))
    policy = SearchPolicy(page_hit_target=20, page_character_target=8_000)

    seen: list[str] = []
    cursor = None
    while True:
        page = index.search(query, policy=policy, cursor=cursor)
        seen.extend(hit.unit.unit_id for hit in page.hits)
        assert all(hit.projection.citable is False for hit in page.hits)
        assert all(hit.projection.canonical_unit_id == hit.unit.unit_id for hit in page.hits)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert seen == [f"unit:report-{number:03}" for number in range(1, 46)]


def test_structured_query_rejects_empty_or_executable_search_input() -> None:
    with pytest.raises(ValueError, match="structured"):
        SearchQuery()
    with pytest.raises(ValueError, match="raw FTS"):
        SearchQuery(terms=("allocation OR concealment",))


def test_canonicalization_preserves_block_page_and_spatial_provenance() -> None:
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-initial",
        pages=(
            CanonicalPage(
                page=7,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.HEADING,
                        text="Randomisation",
                        spatial=(20.0, 30.0, 400.0, 60.0),
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Allocation was concealed.",
                        spatial=(20.0, 70.0, 500.0, 120.0),
                    ),
                ),
            ),
        ),
    )

    assert all(item.unit_id.startswith("unit:report-") for item in units)
    assert len({item.unit_id for item in units}) == 2
    assert units[1].page == 7
    assert units[1].spatial == (20.0, 70.0, 500.0, 120.0)
    assert units[1].parse_id == "parse:report-initial"


def test_broad_query_preview_requires_refinement_or_justification(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(tuple(unit(number, "trial") for number in range(1, 102)))

    preview = index.preview(SearchQuery(terms=("trial",)))

    assert preview.unique_hit_count == 101
    assert preview.requires_broad_query_justification is True
    with pytest.raises(ValueError, match="broad query"):
        index.search(SearchQuery(terms=("trial",)))
    assert index.search(
        SearchQuery(terms=("trial",)),
        broad_query_justification="All 101 results will be traversed with stable cursors.",
    ).hits


def test_boundary_free_long_unit_projects_with_monotonic_progress(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units((unit(1, "allocation " * 600),))

    result = index.search(SearchQuery(terms=("allocation",)))

    assert result.hits[0].projection.canonical_unit_id == "unit:report-001"


def complete_receipt(*, retain_second: bool = False) -> SearchCoverageReceipt:
    seed_query = SearchQuery(terms=("allocation",))
    follow_up_query = SearchQuery(terms=("envelope",))
    contradiction_query = SearchQuery(terms=("open",))
    receipt = SearchCoverageReceipt(
        receipt_id="coverage:sq1-1",
        sq_id="sq:1.1",
        snapshot_hash=HASH,
        policy_id="policy:evidence-search-1.0.0",
        policy_hash=canonical_hash(SearchPolicy()),
        result_spec=RecordReference(
            entity_id="result_spec:trial-1",
            revision_id="revision:result-spec-1",
            content_hash=HASH,
        ),
        source_inventory=RecordReference(
            entity_id="inventory:trial-1",
            revision_id="revision:inventory-1",
            content_hash=HASH,
        ),
        parse_record_hashes=(HASH,),
        guidance_release_id="guidance:rob2-2019.1",
        required_seed_families=("seed:allocation",),
        completed_passes=(
            SearchPassKind.GUIDANCE_SEED,
            SearchPassKind.TRIAL_FOLLOW_UP,
            SearchPassKind.CONTRADICTION,
        ),
        completed_seed_families=("seed:allocation",),
        executed_queries=(
            ExecutedSearchQuery(
                query=seed_query,
                query_hash=canonical_hash(seed_query),
                pass_kind=SearchPassKind.GUIDANCE_SEED,
                seed_family="seed:allocation",
                returned_unit_ids=("unit:report-001",),
                traversal_complete=True,
            ),
            ExecutedSearchQuery(
                query=follow_up_query,
                query_hash=canonical_hash(follow_up_query),
                pass_kind=SearchPassKind.TRIAL_FOLLOW_UP,
                returned_unit_ids=("unit:report-002",),
                traversal_complete=True,
            ),
            ExecutedSearchQuery(
                query=contradiction_query,
                query_hash=canonical_hash(contradiction_query),
                pass_kind=SearchPassKind.CONTRADICTION,
                returned_unit_ids=(),
                traversal_complete=True,
            ),
        ),
        result_dispositions=(
            SearchResultDisposition(
                unit_id="unit:report-001",
                kind=SearchResultDispositionKind.RETAINED_CANDIDATE,
                candidate_id="candidate:one",
            ),
            SearchResultDisposition(
                unit_id="unit:report-002",
                kind=(
                    SearchResultDispositionKind.RETAINED_CANDIDATE
                    if retain_second
                    else SearchResultDispositionKind.IRRELEVANT
                ),
                candidate_id="candidate:two" if retain_second else None,
            ),
        ),
        returned_unit_ids=("unit:report-001", "unit:report-002"),
        sources=(
            SourceSearchCoverage(
                source_id="source:report",
                state=SourceSearchState.SEARCHED,
                sufficiently_readable=True,
            ),
        ),
        inventory_source_ids=("source:report",),
        visual_candidates=(
            VisualCandidateCoverage(
                candidate_id="visual:table-1",
                dispositioned=True,
                required=True,
            ),
        ),
        latest_complete_round_new_material_candidates=0,
        traversal_complete=True,
        interrupted=False,
    )
    proof_payload = receipt.model_dump(mode="json")
    proof_payload["recorder_proof"] = None
    return SearchCoverageReceipt.model_validate(
        receipt.model_dump(mode="json") | {"recorder_proof": canonical_hash(proof_payload)}
    )


def test_canonical_word_box_text_must_match_exact_unit_span() -> None:
    with pytest.raises(ValueError, match="word box text"):
        CanonicalEvidenceUnit(
            unit_id="unit:word-box",
            source_id="source:report",
            source_artifact_hash=HASH,
            parse_id="parse:report-initial",
            page=1,
            kind=CanonicalUnitKind.PARAGRAPH,
            text="Allocation concealed",
            word_boxes=(
                CanonicalWordBox(
                    text="wrong",
                    span_start=0,
                    span_end=10,
                    spatial=(1.0, 1.0, 50.0, 20.0),
                ),
            ),
        )


def test_coverage_receipt_requires_all_passes_results_and_safe_no_information_basis() -> None:
    receipt = complete_receipt()
    assert receipt.establishes_no_information_basis() is True

    with pytest.raises(ValueError, match="contradiction"):
        complete_receipt().model_copy(
            update={
                "completed_passes": (
                    SearchPassKind.GUIDANCE_SEED,
                    SearchPassKind.TRIAL_FOLLOW_UP,
                )
            }
        ).model_validate(
            complete_receipt().model_dump()
            | {
                "completed_passes": [
                    SearchPassKind.GUIDANCE_SEED,
                    SearchPassKind.TRIAL_FOLLOW_UP,
                ]
            }
        )

    limited = complete_receipt().model_dump()
    limited["sources"] = [
        {
            "source_id": "source:report",
            "state": SourceSearchState.SEARCH_LIMITED,
            "sufficiently_readable": True,
        }
    ]
    limited["interrupted"] = True
    limited["recorder_proof"] = None
    receipt = SearchCoverageReceipt.model_validate(limited)
    assert receipt.establishes_no_information_basis() is False

    omitted = complete_receipt().model_dump()
    omitted["sources"] = []
    with pytest.raises(ValueError, match="source inventory"):
        SearchCoverageReceipt.model_validate(omitted)


def test_complete_coverage_receipt_replays_every_scoped_page(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units((unit(1, "allocation envelope open"),))
    recorder = SearchCoverageRecorder(
        receipt_id="coverage:replay",
        sq_id="sq:1.1",
        snapshot_hash=index.search(SearchQuery(terms=("allocation",))).snapshot_hash,
        policy_id="policy:evidence-search-1.0.0",
        result_spec=RecordReference(
            entity_id="result_spec:trial-1",
            revision_id="revision:result-spec-1",
            content_hash=HASH,
        ),
        source_inventory=RecordReference(
            entity_id="inventory:trial-1",
            revision_id="revision:inventory-1",
            content_hash=HASH,
        ),
        parse_record_hashes=(HASH,),
        guidance_release_id="guidance:rob2-2019.1",
        required_seed_families=("seed:allocation",),
        sources=(
            SourceSearchCoverage(
                source_id="source:report",
                state=SourceSearchState.SEARCHED,
                sufficiently_readable=True,
            ),
        ),
        inventory_source_ids=("source:report",),
    )
    queries = (
        (SearchQuery(terms=("allocation",)), SearchPassKind.GUIDANCE_SEED, "seed:allocation"),
        (SearchQuery(terms=("envelope",)), SearchPassKind.TRIAL_FOLLOW_UP, None),
        (SearchQuery(terms=("open",)), SearchPassKind.CONTRADICTION, None),
    )
    for query, pass_kind, seed_family in queries:
        page = index.search(query)
        recorder.record_page(
            page,
            index=index,
            query=query,
            pass_kind=pass_kind,
            seed_family=seed_family,
        )

    duplicated_pass = complete_receipt().model_dump(mode="json")
    duplicated_pass["executed_queries"][1]["query"] = duplicated_pass["executed_queries"][0][
        "query"
    ]
    duplicated_pass["executed_queries"][1]["query_hash"] = duplicated_pass["executed_queries"][0][
        "query_hash"
    ]
    duplicated_pass["recorder_proof"] = None
    duplicated_pass["recorder_proof"] = canonical_hash(duplicated_pass)
    with pytest.raises(ValueError, match="every mandatory"):
        SearchCoverageReceipt.model_validate(duplicated_pass)
    duplicated_interrupted = dict(duplicated_pass)
    duplicated_interrupted["interrupted"] = True
    duplicated_interrupted["recorder_proof"] = None
    duplicated_interrupted["recorder_proof"] = canonical_hash(duplicated_interrupted)
    with pytest.raises(ValueError, match="every mandatory"):
        SearchCoverageReceipt.model_validate(duplicated_interrupted)
    recorder.record_disposition(
        SearchResultDisposition(
            unit_id="unit:report-001",
            kind=SearchResultDispositionKind.IRRELEVANT,
        )
    )
    receipt = recorder.freeze(completed_seed_families=("seed:allocation",))

    verify_complete_search_coverage_receipt(receipt, index=index)

    changed = receipt.model_dump(mode="json")
    for query in changed["executed_queries"]:
        query["returned_unit_ids"] = []
    changed["returned_unit_ids"] = []
    changed["result_dispositions"] = []
    changed["recorder_proof"] = None
    changed["recorder_proof"] = canonical_hash(changed)
    tampered = SearchCoverageReceipt.model_validate(changed)
    with pytest.raises(ValueError, match="omits or changes"):
        verify_complete_search_coverage_receipt(tampered, index=index)

    forged_policy = receipt.model_dump(mode="json")
    forged_policy["policy_id"] = "policy:caller-selected"
    forged_policy["policy_hash"] = canonical_hash(SearchPolicy(policy_id="policy:caller-selected"))
    for query in forged_policy["executed_queries"]:
        query["policy_id"] = "policy:caller-selected"
        query["policy_hash"] = forged_policy["policy_hash"]
    forged_policy["recorder_proof"] = None
    forged_policy["recorder_proof"] = canonical_hash(forged_policy)
    with pytest.raises(ValueError, match="engine-owned"):
        verify_complete_search_coverage_receipt(
            SearchCoverageReceipt.model_validate(forged_policy), index=index
        )

    incomplete_visual = receipt.model_dump(mode="json")
    incomplete_visual["visual_candidates"] = [
        {"candidate_id": "visual:required", "required": True, "dispositioned": False}
    ]
    incomplete_visual["recorder_proof"] = None
    incomplete_visual["recorder_proof"] = canonical_hash(incomplete_visual)
    with pytest.raises(ValueError, match="Visual candidates"):
        verify_complete_search_coverage_receipt(
            SearchCoverageReceipt.model_validate(incomplete_visual), index=index
        )

    inconsistent_stop = receipt.model_dump(mode="json")
    inconsistent_stop["stopping_reason"] = "agent decided the search was enough"
    inconsistent_stop["recorder_proof"] = None
    inconsistent_stop["recorder_proof"] = canonical_hash(inconsistent_stop)
    with pytest.raises(ValueError, match="canonical stopping reason"):
        SearchCoverageReceipt.model_validate(inconsistent_stop)


def test_exact_claim_is_materialized_from_canonical_text_and_conflicts_are_preserved() -> None:
    canonical = unit(1, "Allocation was concealed, but the later report says it was open.")
    start = canonical.text.index("concealed")
    claim = materialize_evidence_claim(
        claim_id="claim:allocation-1",
        unit=canonical,
        span_start=start,
        span_end=start + len("concealed"),
        claim_type="claim_type:allocation-concealment",
    )
    contradiction_start = canonical.text.index("open")
    contradiction = materialize_evidence_claim(
        claim_id="claim:allocation-2",
        unit=canonical,
        span_start=contradiction_start,
        span_end=contradiction_start + len("open"),
        claim_type="claim_type:allocation-concealment",
    )

    assert claim.quoted_text == "concealed"
    assert claim.canonical_unit_id == canonical.unit_id
    assert claim.source_artifact_hash == canonical.source_artifact_hash
    assert claim.quoted_text_hash != contradiction.quoted_text_hash

    bundle = freeze_evidence_bundle(
        result_spec_id="result_spec:trial-1",
        receipts=(complete_receipt(retain_second=True),),
        candidate_dispositions=(
            CandidateDisposition(
                candidate_id="candidate:one",
                kind=CandidateDispositionKind.ACCEPTED_SUPPORTING,
                claim_ids=(claim.claim_id,),
            ),
            CandidateDisposition(
                candidate_id="candidate:two",
                kind=CandidateDispositionKind.ACCEPTED_CONTRADICTING,
                claim_ids=(contradiction.claim_id,),
            ),
        ),
        claims=(claim, contradiction),
        conflicts=(("claim:allocation-1", "claim:allocation-2"),),
        visual_gates=(VisualGate(gate_id="visual:table-1", required=True, complete=True),),
        review_revisions=tuple(
            EvidenceReviewRevision(
                entity_id=f"evidence-review:{candidate_id}",
                revision_id=f"revision:evidence-review-{candidate_id}-v1",
                actor=ACTOR,
                observed_at=NOW,
                candidate_id=candidate_id,
                result_id="result:one",
                domain_id="domain:one",
                sq_id="sq:1.1",
                spans=(
                    EvidenceReviewSpan(
                        span_id=f"review-span:{candidate_id}",
                        span_start=span_start,
                        span_end=span_end,
                        trial_attribution=TrialAttribution.ACTIVE,
                        disposition=disposition,
                        rationale="Reviewed exact source span.",
                        attribution_rationale="Bounded context identifies the active Result.",
                        reviewed_context=ReviewedEvidenceContext(
                            receipt_hash=canonical_hash({"handle": handle}),
                            snapshot_hash=canonical_hash({"snapshot": handle}),
                            requested_mode="unit",
                            applied_mode="unit",
                            fragments=(
                                ReviewedEvidenceFragment(
                                    unit_id=canonical.unit_id,
                                    source_id=canonical.source_id,
                                    source_artifact_hash=canonical.source_artifact_hash,
                                    parse_id=canonical.parse_id,
                                    canonicalization_version=canonical.canonicalization_version,
                                    unit_content_hash=sha256_digest(canonical.text.encode()),
                                    span_start=span_start,
                                    span_end=span_end,
                                    content_hash=sha256_digest(
                                        canonical.text[span_start:span_end].encode()
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            )
            for candidate_id, handle, span_start, span_end, disposition in (
                (
                    "candidate:one",
                    "handle:concealed",
                    start,
                    start + len("concealed"),
                    EvidenceReviewDisposition.SUPPORTING,
                ),
                (
                    "candidate:two",
                    "handle:open",
                    contradiction_start,
                    contradiction_start + len("open"),
                    EvidenceReviewDisposition.CONTRADICTING,
                ),
            )
        ),
    )
    assert bundle.conflicts == (("claim:allocation-1", "claim:allocation-2"),)


def test_derived_fact_registry_is_closed_and_records_calculation_provenance() -> None:
    fact = derive_fact(
        fact_id="fact:risk-ratio-1",
        derivation_id="derivation:risk-ratio",
        inputs=(
            DerivedFactInput(
                claim_id="claim:events-experimental",
                role="experimental_events",
                value="12",
            ),
            DerivedFactInput(
                claim_id="claim:total-experimental",
                role="experimental_total",
                value="100",
            ),
            DerivedFactInput(
                claim_id="claim:events-comparator",
                role="comparator_events",
                value="20",
            ),
            DerivedFactInput(
                claim_id="claim:total-comparator",
                role="comparator_total",
                value="100",
            ),
        ),
        population="randomized participants",
        arms=("experimental", "comparator"),
        analysis_set="intention-to-treat",
        outcome="mortality",
        time_point="30 days",
        units="ratio",
        rounding_places=2,
    )

    assert fact.value == "0.60"
    assert fact.formula == "(experimental_events / experimental_total) / " + (
        "(comparator_events / comparator_total)"
    )
    with pytest.raises(ValueError, match="closed registry"):
        derive_fact(
            fact_id="fact:invented",
            derivation_id="derivation:model-authored",
            inputs=(),
            population="all",
            arms=("a", "b"),
            analysis_set="all",
            outcome="outcome",
            time_point="end",
            units=None,
            rounding_places=2,
        )

    impossible = list(fact.inputs)
    impossible[0] = impossible[0].model_copy(update={"value": "101"})
    with pytest.raises(ValueError, match="event counts"):
        derive_fact(
            fact_id="fact:impossible",
            derivation_id="derivation:risk-ratio",
            inputs=tuple(impossible),
            population="randomized participants",
            arms=("experimental", "comparator"),
            analysis_set="intention-to-treat",
            outcome="mortality",
            time_point="30 days",
            units="ratio",
            rounding_places=2,
        )


def test_bundle_freeze_rejects_incomplete_work_and_has_stable_hash() -> None:
    canonical = unit(1, "Allocation was concealed.")
    claim = materialize_evidence_claim(
        claim_id="claim:one",
        unit=canonical,
        span_start=0,
        span_end=10,
        claim_type="claim_type:allocation",
    )
    disposition = CandidateDisposition(
        candidate_id="candidate:one",
        kind=CandidateDispositionKind.ACCEPTED_SUPPORTING,
        claim_ids=(claim.claim_id,),
    )
    arguments = {
        "result_spec_id": "result_spec:trial-1",
        "receipts": (complete_receipt(),),
        "candidate_dispositions": (disposition,),
        "claims": (claim,),
        "visual_gates": (VisualGate(gate_id="visual:table-1", required=True, complete=True),),
        "review_revisions": (
            EvidenceReviewRevision(
                entity_id="evidence-review:candidate-one",
                revision_id="revision:evidence-review-candidate-one-v1",
                actor=ACTOR,
                observed_at=NOW,
                candidate_id="candidate:one",
                result_id="result:one",
                domain_id="domain:one",
                sq_id="sq:1.1",
                spans=(
                    EvidenceReviewSpan(
                        span_id="review-span:candidate-one",
                        span_start=0,
                        span_end=10,
                        trial_attribution=TrialAttribution.ACTIVE,
                        disposition=EvidenceReviewDisposition.SUPPORTING,
                        rationale="Allocation concealment supports the assessment.",
                        attribution_rationale="Bounded context identifies the active Result.",
                        reviewed_context=ReviewedEvidenceContext(
                            receipt_hash=canonical_hash({"handle": "handle:one"}),
                            snapshot_hash=canonical_hash({"snapshot": "one"}),
                            requested_mode="unit", applied_mode="unit",
                            fragments=(
                                ReviewedEvidenceFragment(
                                    unit_id=canonical.unit_id,
                                    source_id=canonical.source_id,
                                    source_artifact_hash=canonical.source_artifact_hash,
                                    parse_id=canonical.parse_id,
                                    canonicalization_version=canonical.canonicalization_version,
                                    unit_content_hash=sha256_digest(canonical.text.encode()),
                                    span_start=0,
                                    span_end=10,
                                    content_hash=sha256_digest(canonical.text[:10].encode()),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    }

    first = freeze_evidence_bundle(**arguments)
    second = freeze_evidence_bundle(
        **(arguments | {"claims": tuple(reversed(arguments["claims"]))})
    )
    assert first.content_hash == second.content_hash
    manifest = build_consideration_manifest(
        manifest_id="consideration:sq1-1",
        sq_id="sq:1.1",
        bundle=first,
        items=(
            ConsideredEvidenceItem(
                item_id=claim.claim_id,
                disposition=ConsiderationDisposition.SUPPORTING,
            ),
        ),
    )
    assert manifest.bundle_hash == first.content_hash

    with pytest.raises(ValueError, match="every frozen evidence item"):
        build_consideration_manifest(
            manifest_id="consideration:sq1-incomplete",
            sq_id="sq:1.1",
            bundle=first,
            items=(),
        )

    with pytest.raises(ValueError, match="unresolved"):
        freeze_evidence_bundle(
            **(
                arguments
                | {
                    "candidate_dispositions": (
                        CandidateDisposition(
                            candidate_id="candidate:one",
                            kind=CandidateDispositionKind.UNRESOLVED,
                        ),
                    )
                }
            )
        )
    with pytest.raises(ValueError, match="visual gate"):
        freeze_evidence_bundle(
            **(
                arguments
                | {
                    "visual_gates": (
                        VisualGate(gate_id="visual:table", required=True, complete=False),
                    )
                }
            )
        )
