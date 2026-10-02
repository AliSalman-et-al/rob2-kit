import pytest

from rob2_kit.application import evidence


def test_large_page_cache_preserves_unicode_raw_and_normalized_offsets(
    monkeypatch: pytest.MonkeyPatch,
):
    text = ("padding " * 9000) + "allocation\nallo-\ncation Straße nai\u0308ve café\n"
    expected, spans = evidence._canonical_search_text_with_spans(text)
    evidence._cached_large_search_projection.cache_clear()
    normalized, starts, ends = evidence._cached_large_search_projection(text)
    assert normalized == expected
    assert list(zip(starts, ends)) == spans
    for query, mode in [
        ("allocation", "any"),
        ("strasse", "any"),
        ("naive", "any"),
        ("allo", "prefix"),
    ]:
        got = evidence._native_fts_match_spans(text, query, mode)
        with monkeypatch.context() as patch:
            patch.setattr(
                evidence, "_cached_large_search_projection", lambda _text: (expected, starts, ends)
            )
            assert evidence._native_fts_match_spans(text, query, mode) == got
    assert evidence._cached_large_search_projection.cache_info().hits >= 4


def test_projection_cache_is_keyed_by_complete_captured_text():
    text = "noise " * 11000 + "allocation"
    evidence._cached_large_search_projection.cache_clear()
    assert evidence._native_fts_match_spans(text, "allocation", "any") == [(66000, 66010)]
    changed = text.replace("allocation", "concealment")
    assert evidence._native_fts_match_spans(changed, "allocation", "any") == []
    assert evidence._native_fts_match_spans(changed, "concealment", "any") == [(66000, 66011)]
    assert evidence._cached_large_search_projection.cache_info().misses == 2


def test_cached_offsets_are_packed_and_retention_is_bounded():
    assert evidence._cached_large_search_projection.cache_info().maxsize == 2
    text = "word " * 14000
    normalized, starts, ends = evidence._cached_large_search_projection(text)
    assert starts.itemsize == ends.itemsize == 8
    assert len(starts) == len(ends) == len(normalized)
