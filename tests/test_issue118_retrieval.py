from __future__ import annotations

from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    DocumentZone,
    EvidenceSearchIndex,
    SearchQuery,
    canonicalize_evidence_units,
)

HASH = "sha256:" + "1" * 64


def _unit(unit_id: str, text: str, *, zone: DocumentZone) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=unit_id,
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        spatial=(10, 10, 200, 30),
        document_zone=zone,
    )


def test_canonicalization_preserves_fragment_lineage_with_non_positional_identity() -> None:
    first = CanonicalBlock(
        kind=CanonicalUnitKind.PARAGRAPH,
        text="Allocation was concealed.",
        spatial=(10, 10, 200, 30),
        reading_order=8,
        fragment_ids=("fragment:parser-a",),
    )
    second = CanonicalBlock(
        kind=CanonicalUnitKind.PARAGRAPH,
        text="Follow-up was complete.",
        spatial=(10, 50, 200, 70),
        reading_order=9,
        fragment_ids=("fragment:parser-b",),
    )
    original = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        pages=(CanonicalPage(page=1, blocks=(first, second)),),
    )
    reordered = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        pages=(CanonicalPage(page=1, blocks=(second, first)),),
    )

    original_by_text = {unit.text: unit for unit in original}
    reordered_by_text = {unit.text: unit for unit in reordered}
    assert (
        original_by_text["Allocation was concealed."].unit_id
        == reordered_by_text["Allocation was concealed."].unit_id
    )
    assert original_by_text["Allocation was concealed."].fragment_ids == ("fragment:parser-a",)


def test_canonicalization_merges_unambiguous_vertical_fragments_with_exact_spans(tmp_path) -> None:
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="Allocation was ",
                        spatial=(10, 10, 200, 20),
                        reading_order=1,
                        fragment_ids=("fragment:first",),
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.PARAGRAPH,
                        text="concealed.",
                        spatial=(10, 22, 200, 32),
                        reading_order=2,
                        fragment_ids=("fragment:second",),
                    ),
                ),
            ),
        ),
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.text == "Allocation was concealed."
    assert unit.fragment_ids == ("fragment:first", "fragment:second")
    assert [
        (
            span.fragment_id,
            span.fragment_start,
            span.fragment_end,
            span.canonical_start,
            span.canonical_end,
        )
        for span in unit.fragment_spans
    ] == [
        ("fragment:first", 0, 15, 0, 15),
        ("fragment:second", 0, 10, 15, 25),
    ]
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units(units)
    assert index.read_unit(unit.unit_id).fragment_spans == unit.fragment_spans


def test_search_keeps_semantically_labeled_fragments_visible_and_issues_stale_handles(
    tmp_path,
) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    bibliography = _unit(
        "unit:bibliography",
        "allocation cited",
        zone=DocumentZone.BIBLIOGRAPHY,
    )
    unknown = _unit(
        "unit:unknown",
        "allocation uncertain",
        zone=DocumentZone.UNKNOWN,
    )
    index.replace_units((bibliography, unknown))

    page = index.search(SearchQuery(terms=("allocation",)))

    assert {hit.unit.unit_id for hit in page.hits} == {"unit:bibliography", "unit:unknown"}
    hit = next(hit for hit in page.hits if hit.unit.unit_id == "unit:bibliography")
    assert hit.location_handle != hit.unit.unit_id
    assert "document_zone:bibliography" in hit.warnings
    assert index.read_location(hit.location_handle).unit.unit_id == hit.unit.unit_id

    index.replace_units((unknown,))
    try:
        index.read_location(hit.location_handle)
    except ValueError as error:
        assert "stale" in str(error).lower()
    else:
        raise AssertionError("a handle from a replaced snapshot must be stale")


def test_ambiguous_fragments_remain_separate_search_candidates(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    units = canonicalize_evidence_units(
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        pages=(
            CanonicalPage(
                page=1,
                blocks=(
                    CanonicalBlock(
                        kind=CanonicalUnitKind.UNCLASSIFIED,
                        text="allocation left column",
                        spatial=(10, 10, 90, 30),
                        fragment_ids=("fragment:left",),
                        warnings=("reading_order_uncertain",),
                    ),
                    CanonicalBlock(
                        kind=CanonicalUnitKind.UNCLASSIFIED,
                        text="allocation right column",
                        spatial=(110, 10, 190, 30),
                        fragment_ids=("fragment:right",),
                        warnings=("reading_order_uncertain",),
                    ),
                ),
            ),
        ),
    )
    index.replace_units(units)

    page = index.search(SearchQuery(terms=("allocation",)))

    assert len(page.hits) == 2
    assert {hit.unit.fragment_ids for hit in page.hits} == {
        ("fragment:left",),
        ("fragment:right",),
    }
    assert all("reading_order_uncertain" in hit.warnings for hit in page.hits)


def test_read_location_continues_an_oversized_unit_by_character_window(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = _unit("unit:large", "large " * 8, zone=DocumentZone.MAIN)
    index.replace_units((unit,))
    handle = index.search(SearchQuery(terms=("large",))).hits[0].location_handle

    first = index.read_location(handle, character_target=16)
    assert first.text == ("large " * 8)[:16]
    assert first.continuation_cursor is not None
    second = index.read_location(handle, character_target=16, cursor=first.continuation_cursor)
    assert second.text == ("large " * 8)[16:32]
    assert second.continuation_cursor is not None
