"""#137: any_of/terms are AND-combined, contrary to naming/example, with silent zero_hits.

Covers the accepted fix scope from the grill session: the any_of/terms field
docs are rewritten to state the AND-of-ORs semantics explicitly, a shared
heuristic flags query shapes that almost certainly meant OR but got AND
semantics (surfaced on both ``QueryPreview`` and ``SearchPage``), and the
``SearchCoverageRecorder`` no longer credits a mandatory pass for a
flagged, structurally-unmatchable zero-hit query.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rob2_kit.domain.revisions import RecordReference
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    DocumentZone,
    EvidenceSearchIndex,
    SearchQuery,
    SearchQueryFields,
)
from rob2_kit.evidence.workflow import (
    SearchCoverageRecorder,
    SearchPassKind,
    SourceSearchCoverage,
    SourceSearchState,
)

HASH = "sha256:" + "a" * 64


def unit(number: int, text: str) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=f"unit:report-{number:03}",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-initial",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        spatial=(10.0, 20.0, 500.0, 80.0),
        document_zone=DocumentZone.MAIN,
        section_path=("Methods",),
        hierarchy_path=("1",),
    )


def _index(tmp_path: Path) -> EvidenceSearchIndex:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units((unit(1, "Allocation concealment used sealed opaque envelopes."),))
    return index


def _recorder(index: EvidenceSearchIndex) -> SearchCoverageRecorder:
    return SearchCoverageRecorder(
        receipt_id="coverage:issue137",
        sq_id="sq:1.1",
        snapshot_hash=index.search(SearchQuery(terms=("allocation",))).snapshot_hash,
        policy_id="policy:evidence-search-1.1.0",
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


def test_any_of_field_description_states_and_of_ors_semantics() -> None:
    field = SearchQueryFields.model_fields["any_of"]
    assert "AND-of-ORs" in field.description
    assert field.examples == [[["sealed", "central", "opaque"]]]


def test_terms_field_description_clarifies_and_semantics() -> None:
    field = SearchQueryFields.model_fields["terms"]
    assert "AND" in field.description
    assert "any_of" in field.description


def test_singleton_any_of_groups_hint_on_zero_hits(tmp_path: Path) -> None:
    index = _index(tmp_path)
    page = index.search(SearchQuery(any_of=(("randomization",), ("blinding",))))
    assert page.condition == "zero_hits"
    assert len(page.malformed_query_hints) == 1
    assert "any_of group has exactly one term" in page.malformed_query_hints[0]
    assert page.malformed_query_hints[0] in page.next_actions
    assert page.preview.malformed_query_hints == page.malformed_query_hints


def test_multi_term_hint_on_zero_hits(tmp_path: Path) -> None:
    index = _index(tmp_path)
    page = index.search(SearchQuery(terms=("randomization", "blinding")))
    assert page.condition == "zero_hits"
    assert len(page.malformed_query_hints) == 1
    assert "terms are AND'd together" in page.malformed_query_hints[0]


def test_both_hints_fire_independently_when_both_shapes_present(tmp_path: Path) -> None:
    index = _index(tmp_path)
    page = index.search(
        SearchQuery(
            terms=("randomization", "blinding"),
            any_of=(("registration",), ("schedule",)),
        )
    )
    assert page.condition == "zero_hits"
    assert len(page.malformed_query_hints) == 2


def test_no_hint_for_well_formed_single_group_zero_hits(tmp_path: Path) -> None:
    index = _index(tmp_path)
    page = index.search(SearchQuery(any_of=(("randomization", "blinding", "masking"),)))
    assert page.condition == "zero_hits"
    assert page.malformed_query_hints == ()


def test_no_hint_when_query_actually_matches(tmp_path: Path) -> None:
    index = _index(tmp_path)
    # Same singleton-groups shape as the misuse case, but it happens to match.
    page = index.search(SearchQuery(any_of=(("sealed",), ("opaque",))))
    assert page.condition == "results"
    assert page.malformed_query_hints == ()


def test_no_hint_on_excluded_only_condition(tmp_path: Path) -> None:
    from rob2_kit.evidence.search import EvidenceScope

    index = _index(tmp_path)
    # Two AND'd terms would also trip the malformed-query heuristic on their
    # own, but a source-scope exclusion is the reason these zero hits happen,
    # so the hint must not fire here.
    page = index.search(
        SearchQuery(terms=("allocation", "concealment")),
        scope=EvidenceScope(source_ids=("source:other",)),
    )
    assert page.condition == "excluded_only"
    assert page.malformed_query_hints == ()


def test_preview_surfaces_the_same_hint(tmp_path: Path) -> None:
    index = _index(tmp_path)
    preview = index.preview(SearchQuery(any_of=(("randomization",), ("blinding",))))
    assert preview.unique_hit_count == 0
    assert len(preview.malformed_query_hints) == 1
    assert "any_of group has exactly one term" in preview.malformed_query_hints[0]


def test_preview_no_hint_when_zero_hits_are_a_scope_exclusion(tmp_path: Path) -> None:
    from rob2_kit.evidence.search import EvidenceScope

    index = _index(tmp_path)
    # Same singleton-groups shape as the misuse case, and the words *do*
    # appear in the corpus -- the zero result here is caused entirely by
    # scoping to a source with no units, not by the query shape.
    preview = index.preview(
        SearchQuery(any_of=(("sealed",), ("opaque",))),
        scope=EvidenceScope(source_ids=("source:other",)),
    )
    assert preview.unique_hit_count == 0
    assert preview.malformed_query_hints == ()


def test_record_page_excludes_flagged_zero_hit_from_pass_credit(tmp_path: Path) -> None:
    index = _index(tmp_path)
    recorder = _recorder(index)
    recorder.record_page(
        index.search(SearchQuery(terms=("allocation",))),
        index=index,
        query=SearchQuery(terms=("allocation",)),
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
    )
    recorder.record_page(
        index.search(SearchQuery(terms=("concealment",))),
        index=index,
        query=SearchQuery(terms=("concealment",)),
        pass_kind=SearchPassKind.TRIAL_FOLLOW_UP,
    )
    malformed_query = SearchQuery(any_of=(("randomization",), ("blinding",)))
    recorder.record_page(
        index.search(malformed_query),
        index=index,
        query=malformed_query,
        pass_kind=SearchPassKind.CONTRADICTION,
    )
    assert SearchPassKind.CONTRADICTION not in recorder.completed_passes()
    assert recorder.is_coverage_complete() is False

    corrected_query = SearchQuery(terms=("envelopes",))
    recorder.record_page(
        index.search(corrected_query),
        index=index,
        query=corrected_query,
        pass_kind=SearchPassKind.CONTRADICTION,
    )
    assert SearchPassKind.CONTRADICTION in recorder.completed_passes()
    assert recorder.is_coverage_complete() is True


def test_freeze_rejects_a_pass_backed_only_by_a_flagged_query(tmp_path: Path) -> None:
    index = _index(tmp_path)
    recorder = _recorder(index)
    recorder.record_page(
        index.search(SearchQuery(terms=("allocation",))),
        index=index,
        query=SearchQuery(terms=("allocation",)),
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
    )
    recorder.record_page(
        index.search(SearchQuery(terms=("concealment",))),
        index=index,
        query=SearchQuery(terms=("concealment",)),
        pass_kind=SearchPassKind.TRIAL_FOLLOW_UP,
    )
    malformed_query = SearchQuery(any_of=(("randomization",), ("blinding",)))
    recorder.record_page(
        index.search(malformed_query),
        index=index,
        query=malformed_query,
        pass_kind=SearchPassKind.CONTRADICTION,
    )
    with pytest.raises(ValueError, match="mandatory search pass missing"):
        recorder.freeze(completed_seed_families=("seed:allocation",))


def test_freeze_succeeds_once_the_flagged_pass_is_corrected(tmp_path: Path) -> None:
    index = _index(tmp_path)
    recorder = _recorder(index)
    recorder.record_page(
        index.search(SearchQuery(terms=("allocation",))),
        index=index,
        query=SearchQuery(terms=("allocation",)),
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:allocation",
    )
    recorder.record_page(
        index.search(SearchQuery(terms=("concealment",))),
        index=index,
        query=SearchQuery(terms=("concealment",)),
        pass_kind=SearchPassKind.TRIAL_FOLLOW_UP,
    )
    malformed_query = SearchQuery(any_of=(("randomization",), ("blinding",)))
    recorder.record_page(
        index.search(malformed_query),
        index=index,
        query=malformed_query,
        pass_kind=SearchPassKind.CONTRADICTION,
    )
    corrected_query = SearchQuery(terms=("envelopes",))
    recorder.record_page(
        index.search(corrected_query),
        index=index,
        query=corrected_query,
        pass_kind=SearchPassKind.CONTRADICTION,
    )
    recorder.auto_disposition(())
    receipt = recorder.freeze(completed_seed_families=("seed:allocation",))
    assert set(receipt.completed_passes) == set(SearchPassKind)
    # The malformed dead-end attempt is still present in the audit trail,
    # just not required for pass credit -- no separate persisted flag (#137
    # grill decision: not worth the schema growth for a superseded attempt).
    executed_hashes = {query.query_hash for query in receipt.executed_queries}
    assert index.search(malformed_query).query_hash in executed_hashes
