import pytest

from rob2_kit.application.evidence import (
    _all_search_match_spans,
    _literal_match_spans,
    _native_fts_match_spans,
    _osa_distance,
    _session_candidates,
    _source_navigation_entries,
)


def test_literal_search_casefolds_expanding_unicode_and_uses_alphanumeric_endpoints() -> None:
    assert _literal_match_spans("Straße", "STRASSE") == [(0, len("Straße"))]
    assert _literal_match_spans("grade 30; grade 3", "GRADE 3") == [(10, 17)]
    assert _literal_match_spans("_grade 3_", "grade 3") == [(1, 8)]
    assert _literal_match_spans("identifier.grade 3", "identifier.grade 3") == [
        (0, len("identifier.grade 3"))
    ]
    assert _literal_match_spans("\u200b", "\u200b") == []


def test_native_highlight_reports_marker_collision_as_localization_failure() -> None:
    text = "\x01\x02\ue000\ue001\u241e\u241f allocation"

    with pytest.raises(ValueError, match="localization failed"):
        _native_fts_match_spans(text, "allocation", "any")


def test_spelling_distance_supports_adjacent_transposition() -> None:
    assert _osa_distance("randomizaton", "randomization", 2) == 1


def test_source_navigation_preserves_split_heading_coordinates() -> None:
    page = (
        "Header\n\n1.2\nIntroduction\nBody text.\n\n2.0\n11-Oct-2017\n\n3\n"
        "This is a long prose sentence that should not become a heading candidate."
    )
    headings = [
        item
        for item in _source_navigation_entries((page,))
        if item["kind"] == "heading_candidate" and item["start_line"] != item["end_line"]
    ]
    assert len(headings) == 1
    assert headings[0]["text"] == "1.2\nIntroduction"
    assert (headings[0]["page"], headings[0]["start_line"], headings[0]["end_line"]) == (1, 3, 4)


def test_search_window_grouping_preserves_anchors_pages_and_source_versions() -> None:
    text = "alpha\ncontext\ncontext\nbeta\n"
    pages = {"protocol-v1": (text, text), "protocol-v2": (text,)}
    pairs = [("protocol-v1", 1), ("protocol-v1", 2), ("protocol-v2", 1)]
    current = _session_candidates(pages, "alpha beta", "any", list(pages), pairs)
    legacy = _session_candidates(
        pages,
        "alpha beta",
        "any",
        list(pages),
        pairs,
        candidate_version="rob2-kit.search-candidates.v0.9",
    )
    assert len(legacy) == 6
    assert len(current) == 3
    assert [(c["source_id"], c["page"]) for c in current] == pairs
    for c in current:
        quote = pages[c["source_id"]][c["page"] - 1][c["start"] : c["end"]]
        assert quote == text.rstrip("\n")
        assert all(
            c["start"] <= start < end <= c["end"]
            for start, end in _all_search_match_spans(text, "alpha beta", "any")
        )
    with pytest.raises(ValueError, match="unsupported search candidate recipe"):
        _session_candidates(pages, "alpha", "any", list(pages), pairs, candidate_version="unknown")
