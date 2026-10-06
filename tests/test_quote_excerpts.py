"""Quoted excerpts retain source tokens and resolve to precise projection offsets."""

import pytest

from rob2_kit.application.source_check import resolve_quote_excerpt


@pytest.mark.parametrize(
    "quote", ["Alpha -12.5 at\nday 30", "Alpha -12.5 at day 30", "Alpha\t-12.5 at   day 30"]
)
def test_contiguous_excerpt_preserves_original_subspan(quote: str) -> None:
    source = "Before. Alpha -12.5 at\n day 30. Afterwards."
    start, end = resolve_quote_excerpt(source, quote)
    assert source[start:end] == "Alpha -12.5 at\n day 30"
    assert start == 8 and end == 30


@pytest.mark.parametrize(
    "quote",
    [
        "Alpha 12.5 at day 30",
        "Alpha -12.6 at day 30",
        "Alpha -12.5 on day 30",
        "Alpha -12.5 ... day 30",
        "Alpha day 30",
        "Alpha-12.5 at day 30",
        "alpha -12.5 at day 30",
        "12.5",
        ".5",
        "12",
        "-12",
        "Alpha\u00a0-12.5 at day 30",
    ],
)
def test_semantic_edits_omissions_and_numeric_fragments_rejected(quote: str) -> None:
    with pytest.raises(ValueError):
        resolve_quote_excerpt("Alpha -12.5 at\n day 30", quote)


def test_repeated_excerpt_needs_narrower_window_and_source_splicing_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_quote_excerpt("Alpha had 20. Beta had 20.", "had 20")
    assert resolve_quote_excerpt("Beta had 20.", "had 20") == (5, 11)
    with pytest.raises(ValueError):
        resolve_quote_excerpt("Alpha had 20.", "Alpha had 20. Beta had 30.")
