from rob2_kit.application.evidence import (
    _literal_match_spans,
    _native_fts_match_spans,
    _osa_distance,
)


def test_literal_search_is_contiguous_and_respects_alphanumeric_boundaries() -> None:
    text = "Randomization; randomizationX. naïve café"

    assert _literal_match_spans(text, "randomization") == [(0, 13)]
    assert _literal_match_spans(text, "naive cafe") == []


def test_porter_highlight_maps_a_related_source_word_to_raw_offsets() -> None:
    text = "Allocation was concealed before enrollment."

    assert _native_fts_match_spans(text, "concealment", "any") == [(15, 24)]


def test_native_prefix_highlight_returns_the_matched_source_form() -> None:
    text = "Randomization was recorded; randomised centrally."

    assert _native_fts_match_spans(text, "random", "prefix") == [
        (0, 13),
        (28, 38),
    ]


def test_native_highlight_unions_raw_and_normalized_occurrences() -> None:
    text = "allocation\nnoise\nnoise\nallo-\ncation"

    assert _native_fts_match_spans(text, "allocation", "any") == [(0, 10), (23, 35)]


def test_spelling_distance_supports_adjacent_transposition() -> None:
    assert _osa_distance("randomizaton", "randomization", 2) == 1
