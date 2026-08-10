from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.evidence import (
    EvidenceSearchIndex,
    MaterializedEvidenceClaim,
    ReadContextMode,
    SearchCoverageReceipt,
    SearchCoverageRecorder,
    SearchPassKind,
    SearchPolicy,
    SearchQuery,
    SearchResultDisposition,
    SearchResultDispositionKind,
    materialize_evidence_claim,
)
from tests.test_evidence_workflow import HASH, complete_receipt, unit


def test_read_context_is_bounded_and_preserves_source_parse_provenance(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, f"Allocation context {number}.", page=1) for number in range(1, 9))
    index.replace_units(units)

    context = index.read_context(
        units[3].unit_id,
        mode=ReadContextMode.NEIGHBORS,
        neighbor_limit=2,
        character_target=len(units[3].text) * 3,
    )

    assert context.unit == units[3]
    assert [item.unit_id for item in context.neighbors] == [
        units[2].unit_id,
        units[4].unit_id,
    ]
    assert context.character_count <= context.character_target
    assert all(
        (item.source_artifact_hash, item.parse_id) == (HASH, "parse:report-initial")
        for item in context.all_units
    )


def test_read_context_orders_canonical_blocks_numerically(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, f"Allocation block {number}.", page=1) for number in (1, 2, 10, 11))
    # Canonical IDs use a page/block suffix; emulate a source with >9 blocks.
    units = tuple(
        item.model_copy(update={"unit_id": f"unit:report-p1-b{number}"})
        for item, number in zip(units, (1, 2, 10, 11))
    )
    index.replace_units(units)
    context = index.read_context(
        units[1].unit_id,
        neighbor_limit=3,
        mode=ReadContextMode.NEIGHBORS,
    )
    assert [item.unit_id for item in context.neighbors] == [
        "unit:report-p1-b1",
        "unit:report-p1-b10",
        "unit:report-p1-b11",
    ]


def test_oversized_unit_gets_explicit_dedicated_metadata(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    oversized = unit(1, "allocation " * 1_000)
    index.replace_units((oversized,))

    page = index.search(
        SearchQuery(terms=("allocation",)),
        policy=SearchPolicy(page_character_target=32),
    )
    context = index.read_context(
        oversized.unit_id,
        character_target=32,
        mode=ReadContextMode.NEIGHBORS,
    )

    assert page.next_cursor is None
    assert page.oversized_unit_ids == (oversized.unit_id,)
    assert page.character_count > 32
    assert context.oversized is True
    assert context.neighbors == ()
    assert context.unit.text == oversized.text


def test_multiple_oversized_units_are_each_reconstructable_dedicated_pages(
    tmp_path: Path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, "allocation " * 900) for number in range(1, 4))
    index.replace_units(units)
    query = SearchQuery(terms=("allocation",))
    policy = SearchPolicy(page_character_target=100)

    seen: list[str] = []
    cursor = None
    while True:
        page = index.search(query, policy=policy, cursor=cursor)
        assert len(page.hits) == 1
        assert page.oversized_unit_ids == (page.hits[0].unit.unit_id,)
        seen.extend(hit.unit.unit_id for hit in page.hits)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [item.unit_id for item in units]


def test_cursor_binds_policy_and_rejects_tampering(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, "allocation") for number in range(1, 4))
    index.replace_units(units)
    query = SearchQuery(terms=("allocation",))
    first = index.search(query, policy=SearchPolicy(page_hit_target=1))
    assert first.next_cursor is not None

    with pytest.raises(ValueError, match="policy"):
        index.search(query, policy=SearchPolicy(page_hit_target=2), cursor=first.next_cursor)
    with pytest.raises(ValueError):
        index.search(query, cursor="not-a-cursor")

    # There is no client-visible payload to tamper with anymore (ADR-0011):
    # a cursor is an unguessable random reference to a server-side row, not
    # a self-describing signed blob. A mutated token simply matches no row.
    last_character = first.next_cursor[-1]
    forged = first.next_cursor[:-1] + ("0" if last_character != "0" else "1")
    with pytest.raises(ValueError, match="token"):
        index.search(query, policy=SearchPolicy(page_hit_target=1), cursor=forged)

    with pytest.raises(ValueError, match="character_target"):
        index.read_context(units[0].unit_id, character_target=16_001)


def test_receipt_staleness_tracks_exact_dependencies_and_interruptions() -> None:
    receipt = complete_receipt()
    assert receipt.is_stale() is False
    assert receipt.model_copy(update={"returned_unit_ids": ()}).is_complete() is False
    assert receipt.is_stale(current_snapshot_hash="sha256:" + "b" * 64) is True
    assert receipt.stale_reasons(current_policy_id="policy:other") == ("policy_id",)
    assert receipt.content_hash == canonical_hash(receipt.model_dump(mode="json"))
    # A resume cursor only needs to look like an engine-issued lookup-table
    # token here (ADR-0011); this test exercises the receipt's own shape
    # validation, not the index's token lookup.
    resume_cursor = "cur:" + secrets.token_urlsafe(16)

    interrupted = SearchCoverageReceipt.model_validate(
        receipt.model_dump(mode="json")
        | {
            "completed_passes": ["guidance_seed"],
            "executed_queries": [
                receipt.executed_queries[0].model_dump(mode="json") | {"last_cursor": resume_cursor}
            ],
            "completed_seed_families": ["seed:allocation"],
            "returned_unit_ids": ["unit:report-001"],
            "result_dispositions": [receipt.result_dispositions[0].model_dump(mode="json")],
            "interrupted": True,
            "traversal_complete": False,
            "resume_cursor": resume_cursor,
            "resume_query_hash": canonical_hash(receipt.executed_queries[0].query),
            "resume_snapshot_hash": HASH,
            "resume_policy_id": receipt.policy_id,
            "recorder_proof": None,
        }
    )
    assert interrupted.is_complete() is False
    assert interrupted.resumable is True
    assert interrupted.establishes_no_information_basis() is False


def test_search_coverage_recorder_rejects_unverified_query_metadata() -> None:
    receipt = complete_receipt()
    recorder = SearchCoverageRecorder(
        receipt_id=receipt.receipt_id,
        sq_id=receipt.sq_id,
        snapshot_hash=receipt.snapshot_hash,
        policy_id=receipt.policy_id,
        result_spec=receipt.result_spec,
        source_inventory=receipt.source_inventory,
        parse_record_hashes=receipt.parse_record_hashes,
        guidance_release_id=receipt.guidance_release_id,
        required_seed_families=receipt.required_seed_families,
        sources=receipt.sources,
        inventory_source_ids=receipt.inventory_source_ids,
    )
    with pytest.raises(ValueError, match="record_page"):
        recorder.record_query(receipt.executed_queries[0])


def test_search_coverage_recorder_verifies_resumable_pages_and_pass_separation(
    tmp_path: Path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, "Allocation result") for number in range(1, 3))
    snapshot = index.replace_units(units)
    query = SearchQuery(terms=("allocation",))
    policy = SearchPolicy(page_hit_target=1)
    base = complete_receipt()
    recorder = SearchCoverageRecorder(
        receipt_id=base.receipt_id,
        sq_id=base.sq_id,
        snapshot_hash=snapshot,
        policy_id=policy.policy_id,
        policy_hash=canonical_hash(policy),
        result_spec=base.result_spec,
        source_inventory=base.source_inventory,
        parse_record_hashes=base.parse_record_hashes,
        guidance_release_id=base.guidance_release_id,
        required_seed_families=base.required_seed_families,
        sources=base.sources,
        inventory_source_ids=base.inventory_source_ids,
    )
    page = index.search(query, policy=policy)
    executed = recorder.record_page(
        page,
        index=index,
        policy=policy,
        query=query,
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
    )
    recorder.record_disposition(
        SearchResultDisposition(
            unit_id=executed.returned_unit_ids[0],
            kind=SearchResultDispositionKind.IRRELEVANT,
        )
    )
    with pytest.raises(ValueError, match="distinct query"):
        recorder.record_page(
            page,
            index=index,
            policy=policy,
            query=query,
            pass_kind=SearchPassKind.CONTRADICTION,
        )
    receipt = recorder.freeze(
        completed_seed_families=("seed:allocation",),
        interrupted=True,
        traversal_complete=False,
        resume_cursor=page.next_cursor,
        resume_query_hash=canonical_hash(query),
        resume_snapshot_hash=snapshot,
        resume_policy_id=policy.policy_id,
        resume_index=index,
        resume_query=query,
        resume_policy=policy,
    )
    assert receipt.resumable is True
    assert receipt.validate_resume_cursor(index, query, policy=policy) is True
    assert receipt.establishes_no_information_basis() is False


def test_search_coverage_recorder_aggregates_complete_paginated_passes(tmp_path: Path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = tuple(unit(number, "Allocation result") for number in range(1, 3))
    snapshot = index.replace_units(units)
    policy = SearchPolicy(page_hit_target=1)
    base = complete_receipt()
    recorder = SearchCoverageRecorder(
        receipt_id=base.receipt_id,
        sq_id=base.sq_id,
        snapshot_hash=snapshot,
        policy_id=policy.policy_id,
        policy_hash=canonical_hash(policy),
        result_spec=base.result_spec,
        source_inventory=base.source_inventory,
        parse_record_hashes=base.parse_record_hashes,
        guidance_release_id=base.guidance_release_id,
        required_seed_families=base.required_seed_families,
        sources=base.sources,
        inventory_source_ids=base.inventory_source_ids,
    )
    query = SearchQuery(terms=("allocation",))
    first = index.search(query, policy=policy)
    merged = recorder.record_page(
        first,
        index=index,
        policy=policy,
        query=query,
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
    )
    recorder.record_disposition(
        SearchResultDisposition(
            unit_id=merged.returned_unit_ids[0],
            kind=SearchResultDispositionKind.IRRELEVANT,
        )
    )
    second = index.search(query, policy=policy, cursor=first.next_cursor)
    merged = recorder.record_page(
        second,
        index=index,
        policy=policy,
        query=query,
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
        cursor=first.next_cursor,
    )
    recorder.record_disposition(
        SearchResultDisposition(
            unit_id=merged.returned_unit_ids[-1],
            kind=SearchResultDispositionKind.IRRELEVANT,
        )
    )
    assert merged.pages_traversed == 1
    assert merged.traversal_complete is True

    for pass_kind, terms in (
        (SearchPassKind.TRIAL_FOLLOW_UP, ("envelope",)),
        (SearchPassKind.CONTRADICTION, ("open",)),
    ):
        follow_up = SearchQuery(terms=terms)
        recorder.record_page(
            index.search(follow_up, policy=policy),
            index=index,
            policy=policy,
            query=follow_up,
            pass_kind=pass_kind,
        )
    receipt = recorder.freeze(
        completed_seed_families=("seed:allocation",),
        traversal_complete=True,
        interrupted=False,
    )
    assert receipt.is_complete() is True
    assert receipt.executed_queries[0].pages_traversed == 2
    assert receipt.establishes_no_information_basis() is True


def test_materialized_claim_cannot_forge_quote_hash() -> None:
    claim = materialize_evidence_claim(
        claim_id="claim:exact",
        unit=unit(1, "Allocation was concealed."),
        span_start=0,
        span_end=10,
        claim_type="claim:allocation",
    )
    assert claim.quoted_text_hash == sha256_digest(claim.quoted_text.encode())
    with pytest.raises(ValueError, match="quoted text hash"):
        MaterializedEvidenceClaim.model_validate(
            claim.model_copy(update={"quoted_text_hash": "sha256:" + "b" * 64}).model_dump()
        )
    with pytest.raises(ValueError, match="canonical unit"):
        MaterializedEvidenceClaim.model_validate(
            claim.model_dump(mode="json") | {"canonical_unit": None}
        )
    with pytest.raises(ValueError, match="page"):
        MaterializedEvidenceClaim.model_validate(
            claim.model_dump(mode="json") | {"page": claim.page + 1}
        )
