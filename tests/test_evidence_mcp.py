"""MCP evidence selection, rendering, and normalization behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from support.rob2 import *  # noqa: F401,F403

from rob2_kit.application import finalization
from rob2_kit.application._state import _identity, _state
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import (
    _cached_normalized_search_text,
    _normalized_contains,
    _search_receipt,
)


def test_list_sources_resolves_one_captured_trial_or_returns_boundary_error(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    inferred = _call(workspace, "list_sources", {})
    assert inferred["outcome"] == "success"
    assert [source["trial_id"] for source in inferred["data"]["sources"]] == ["trial"]

    unknown = _call(workspace, "list_sources", {"trial_id": "unknown"})
    assert unknown["outcome"] == "condition"
    assert unknown["condition"] == {
        "code": "invalid_request",
        "detail": "unknown captured Trial ID",
    }

    multi_trial = _workspace(tmp_path / "multi")
    second = multi_trial / "input" / "second"
    second.mkdir()
    (second / "main.txt").write_text("second trial", encoding="utf-8")
    _call(
        multi_trial,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    required = _call(multi_trial, "list_sources", {})
    assert required["outcome"] == "condition"
    assert required["condition"] == {
        "code": "invalid_request",
        "detail": "trial_id is required unless the Batch has exactly one captured Trial",
    }
    resolved = _call(multi_trial, "list_sources", {"trial_id": "second"})
    assert [source["trial_id"] for source in resolved["data"]["sources"]] == ["second"]


def test_list_sources_uses_the_same_source_priority_as_search(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    for name in ("z-other.txt", "protocol.txt", "supplement.txt", "registry.txt"):
        (trial / name).write_text(name, encoding="utf-8")
    (trial / "sources.toml").write_text(
        "roles = { "
        '"main.txt" = "main_article", '
        '"registry.txt" = "registry", '
        '"supplement.txt" = "supplement", '
        '"protocol.txt" = "protocol", '
        '"z-other.txt" = "other" }\n',
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )

    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]

    assert [source["role"] for source in sources] == [
        "main_article",
        "registry",
        "supplement",
        "protocol",
        "other",
    ]


def test_search_interleaves_sources_then_uses_fts_bm25_within_source(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    main = pymupdf.open()
    main.new_page().insert_text((72, 72), "alpha beta " + "filler " * 500)
    main.new_page().insert_text((72, 72), "alpha beta")
    main.new_page().insert_text((72, 72), "alpha beta alpha")
    (trial / "article.pdf").write_bytes(main.tobytes())
    main.close()
    protocol = pymupdf.open()
    protocol.new_page().insert_text((72, 72), "alpha beta alpha beta alpha beta")
    (trial / "protocol.pdf").write_bytes(protocol.tobytes())
    protocol.close()
    (trial / "sources.toml").write_text(
        'roles = { "article.pdf" = "main_article", "protocol.pdf" = "protocol" }\n',
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    article = next(source for source in sources if source["label"] == "article.pdf")
    protocol_source = next(source for source in sources if source["label"] == "protocol.pdf")
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        article_ranks = connection.execute(
            "SELECT page,bm25(pages_fts) FROM pages_fts "
            "WHERE pages_fts MATCH ? AND source_id=? ORDER BY bm25(pages_fts),page",
            ('"alpha" AND "beta"', article["id"]),
        ).fetchall()
    assert article_ranks[0][0] != 1

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "limit": 4},
    )
    pairs = [(item["source_id"], item["page"]) for item in result["data"]["hits"]]
    assert pairs == [
        (article["id"], int(article_ranks[0][0])),
        (protocol_source["id"], 1),
        (article["id"], int(article_ranks[1][0])),
        (article["id"], int(article_ranks[2][0])),
    ]
    receipt = _search_receipt(workspace, result["data"]["search_receipt"])
    state = _state(workspace)
    authoritative = {source["id"]: source for source in state["batch"]["trials"][0]["sources"]}
    assert finalization._valid_search_account(
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_valid_search_account"](
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )


def test_search_reserves_one_hit_per_matching_source_within_limit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    article = pymupdf.open()
    for text in (
        "alpha beta " * 40,
        "alpha beta alpha beta alpha beta",
        "alpha beta",
    ):
        article.new_page().insert_text((72, 72), text)
    (trial / "article.pdf").write_bytes(article.tobytes())
    article.close()
    protocol = pymupdf.open()
    protocol.new_page().insert_text((72, 72), "alpha beta")
    (trial / "protocol.pdf").write_bytes(protocol.tobytes())
    protocol.close()
    (trial / "sources.toml").write_text(
        'roles = { "article.pdf" = "main_article", "protocol.pdf" = "protocol" }\n',
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    article_source = next(source for source in sources if source["label"] == "article.pdf")
    protocol_source = next(source for source in sources if source["label"] == "protocol.pdf")

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "limit": 2},
    )
    pairs = [(hit["source_id"], hit["page"]) for hit in result["data"]["hits"]]

    assert result["data"]["total_matches"] == 4
    assert result["data"]["truncated"] is True
    assert pairs[0][0] == article_source["id"]
    assert pairs[1] == (protocol_source["id"], 1)
    expected_hits = [{"source_id": source_id, "page": page} for source_id, page in pairs]
    receipt = _search_receipt(workspace, result["data"]["search_receipt"])
    assert receipt["hits"] == expected_hits
    state = _state(workspace)
    authoritative = {
        source["id"]: source
        for trial_state in state["batch"]["trials"]
        if trial_state["id"] == "trial"
        for source in trial_state["sources"]
    }
    assert finalization._valid_search_account(
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )

    limited = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "limit": 1},
    )
    assert len(limited["data"]["hits"]) == 1
    assert limited["data"]["hits"][0]["source_id"] == article_source["id"]


def test_search_normalization_derivatives_are_bounded_and_reused() -> None:
    _cached_normalized_search_text.cache_clear()
    text = "A captured page with a typographic ﬁligature and a line-\nwrap."

    assert _cached_normalized_search_text(text) == _cached_normalized_search_text(text)
    assert _cached_normalized_search_text.cache_info().hits == 1
    assert _cached_normalized_search_text.cache_info().maxsize == 2048


def test_search_replays_bm25_order_from_the_selected_trial_only(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "input" / "trial"
    article = pymupdf.open()
    article.new_page().insert_text((72, 72), "alpha " * 10 + "beta")
    article.new_page().insert_text((72, 72), "alpha " + "beta " * 10)
    (target / "article.pdf").write_bytes(article.tobytes())
    article.close()
    (target / "sources.toml").write_text(
        'roles = { "article.pdf" = "main_article" }\n',
        encoding="utf-8",
    )

    unrelated = workspace / "input" / "unrelated"
    unrelated.mkdir()
    other = pymupdf.open()
    for _ in range(5):
        other.new_page().insert_text((72, 72), "alpha")
    other.new_page().insert_text((72, 72), "beta")
    (unrelated / "article.pdf").write_bytes(other.tobytes())
    other.close()

    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    article_source = next(source for source in sources if source["label"] == "article.pdf")

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta"},
    )
    assert result["outcome"] == "success"
    pairs = [(hit["source_id"], hit["page"]) for hit in result["data"]["hits"]]
    assert set(pairs) == {(article_source["id"], 1), (article_source["id"], 2)}
    assert result["data"]["total_matches"] == 2

    receipt = _search_receipt(workspace, result["data"]["search_receipt"])
    assert receipt["hits"] == [{"source_id": source_id, "page": page} for source_id, page in pairs]


def test_numbered_page_lines_select_exact_source_text(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "first line\nmiddle-\nline\nlast line\n", encoding="utf-8"
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    page = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )["data"]["pages"][0]
    assert set(page) == {
        "source_id",
        "page",
        "numbered_text",
        "line_count",
        "returned_start_line",
        "returned_end_line",
        "truncated",
        "next_start_line",
        "passage_ref",
    }
    assert page["returned_start_line"] == 1
    assert page["returned_end_line"] == 4
    assert page["truncated"] is False
    assert page["next_start_line"] is None
    assert page["numbered_text"] == ("1|first line\n2|middle-\n3|line\n4|last line")

    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 2,
            "end_line": 3,
        },
    )["data"]["evidence"]
    assert selected["quote"].splitlines() == ["middle-", "line"]

    invalid = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 3,
            "end_line": 5,
        },
    )
    assert invalid["outcome"] == "condition"
    assert invalid["condition"]["code"] == "invalid_request"
    assert invalid["condition"]["detail"] == (
        "line range is outside page 1; choose 1 <= start_line <= end_line <= 4 from read_pages"
    )


def test_read_pages_returns_independent_cross_source_windows_and_passage_refs(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("article one\narticle two\narticle three\n", encoding="utf-8")
    (trial / "protocol.txt").write_text(
        "protocol one\nprotocol two\nprotocol three\n", encoding="utf-8"
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    article = next(source for source in sources if source["label"] == "main.txt")
    protocol = next(source for source in sources if source["label"] == "protocol.txt")

    result = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": article["id"],
                    "page": 1,
                    "start_line": 2,
                    "end_line": 3,
                },
                {
                    "source_id": protocol["id"],
                    "page": 1,
                    "start_line": 1,
                    "end_line": 1,
                },
            ],
        },
    )

    assert result["outcome"] == "success"
    pages = result["data"]["pages"]
    returned_ranges = [
        (page["source_id"], page["returned_start_line"], page["returned_end_line"])
        for page in pages
    ]
    assert returned_ranges == [
        (article["id"], 2, 3),
        (protocol["id"], 1, 1),
    ]
    assert [page["numbered_text"] for page in pages] == [
        "2|article two\n3|article three",
        "1|protocol one",
    ]
    assert all(page["passage_ref"].startswith("eh_") for page in pages)
    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": article["id"],
            "page": 1,
            "start_line": 2,
            "end_line": 3,
        },
    )["data"]["evidence"]
    assert selected["handle"] == pages[0]["passage_ref"]


def test_read_pages_returns_bounded_line_windows_with_continuation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    # The application projection wraps this valid but unusually long source
    # line.  The MCP response must still be bounded and line-addressable.
    (workspace / "input" / "trial" / "main.txt").write_text(
        "word " * 20_000,
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    first = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )
    assert first["outcome"] == "success"
    page = first["data"]["pages"][0]
    assert len(first["data"]["pages"]) == 1
    assert len(page["numbered_text"]) <= 24_000
    assert page["line_count"] > page["returned_end_line"]
    assert page["truncated"] is True
    assert page["next_start_line"] == page["returned_end_line"] + 1

    second = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "pages": [1],
            "start_line": page["next_start_line"],
        },
    )
    next_page = second["data"]["pages"][0]
    assert next_page["returned_start_line"] == page["next_start_line"]
    assert next_page["numbered_text"].startswith(f"{next_page['returned_start_line']}|")


@pytest.mark.parametrize(
    "source_text, end_line",
    (
        ("# Characteristics of the\n", 1),
        ("- The following\n", 1),
        ("| Measure | the |\n", 1),
        ("Please Note\n", 1),
        ("The analysis was specified by\nprotocol.\n", 1),
        ("The analysis was specified by the\nprotocol.\n", 2),
        ("The analysis was specified by the protocol.\n", 1),
    ),
)
def test_select_text_evidence_accepts_exact_fragments(
    tmp_path: Path, source_text: str, end_line: int
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(source_text, encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": end_line,
        },
    )

    assert selected["outcome"] == "success"


@pytest.mark.parametrize(
    "source_text,end_line",
    (
        ("The allocation used permuted blocks.\nFurther methods were reported.\n", 1),
        ("Outcome Assessment\nMethods were prespecified.\n", 1),
        ("| Measure | Value |\n| Events | 12 |\n", 1),
        ("- Allocation was concealed\n- Sequence generation was random\n", 1),
    ),
)
def test_select_text_evidence_accepts_complete_mid_page_material(
    tmp_path: Path, source_text: str, end_line: int
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(source_text, encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": end_line,
        },
    )

    assert selected["outcome"] == "success"


def test_select_text_evidence_accepts_flattened_numeric_table(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "Event\nGrade 3\nGrade 4\nAllergic reaction\n7 (1.8)\n1 (0.3)\n"
        "Fatigue\n16 (4.1)\n0\nFollowing prose continues here.\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 9,
        },
    )

    assert selected["outcome"] == "success"
    assert selected["data"]["evidence"]["quote"].splitlines()[-2:] == ["16 (4.1)", "0"]


def test_product_and_standalone_text_normalization_match() -> None:
    cases = (
        (
            "The Doce\u00adtaxel Group reported a Hazard Ratio of 0.61\u20130.80.",
            "the docetaxel group reported a hazard ratio of 0.61-0.80.",
            True,
        ),
        ("Doce\u00ad\ntaxel", "Docetaxel", True),
        ("pro\u2010\ngression", "progression", True),
        ("pro-\n\u200bgression", "progression", True),
        ("pro\u200b-\ngression", "progression", True),
        ("follow-\nup", "follow-up", True),
        ("castrationresistant", "castration-resistant", False),
        ("e\u0301-\nvalue", "\u00e9value", True),
        (
            "The ﬁnal\u200b\u202e analysis\x00 was complete.\u00ad",
            "the final analysis was complete.",
            True,
        ),
        ("(-\nvalue", "(value", False),
        ("x-\n_axis", "x_axis", True),
    )

    for material, claim, expected in cases:
        assert _normalized_contains(material, claim) is expected
        assert standalone_normalized_contains(material, claim) is expected


def test_search_source_scope_preserves_broad_order_and_receipt_auditability(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("randomization\n", encoding="utf-8")
    protocol = pymupdf.open()
    protocol.new_page().insert_text((72, 72), "randomization")
    protocol.new_page().insert_text((72, 72), "randomization")
    (trial / "protocol.pdf").write_bytes(protocol.tobytes())
    protocol.close()
    (trial / "sources.toml").write_text(
        'roles = { "main.txt" = "main_article", "protocol.pdf" = "protocol" }\n',
        encoding="utf-8",
    )
    second = workspace / "input" / "second"
    second.mkdir()
    (second / "main.txt").write_text("randomization", encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    trial_sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    main = next(source for source in trial_sources if source["role"] == "main_article")
    protocol_source = next(source for source in trial_sources if source["role"] == "protocol")

    broad = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "randomization", "limit": 1},
    )
    assert broad["data"]["total_matches"] == 3
    assert broad["data"]["truncated"] is True
    assert broad["data"]["hits"][0]["source_id"] == main["id"]

    scoped = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "randomization",
            "source_id": protocol_source["id"],
            "limit": 1,
        },
    )
    assert scoped["data"]["total_matches"] == 2
    assert scoped["data"]["truncated"] is True
    assert [(hit["source_id"], hit["page"]) for hit in scoped["data"]["hits"]] == [
        (protocol_source["id"], 1)
    ]
    receipt = _search_receipt(workspace, scoped["data"]["search_receipt"])
    assert receipt["sources"] == [
        {"id": protocol_source["id"], "projection_hash": protocol_source["projection_hash"]}
    ]
    state = _state(workspace)
    trial_record = next(item for item in state["batch"]["trials"] if item["id"] == "trial")
    authoritative = {source["id"]: source for source in trial_record["sources"]}
    assert finalization._valid_search_account(
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_valid_search_account"](
        receipt,
        "trial",
        state["batch"]["identity"],
        authoritative,
        _identity,
    )
    retry = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "randomization",
            "source_id": protocol_source["id"],
            "limit": 1,
        },
    )
    assert retry["data"]["search_receipt"] == scoped["data"]["search_receipt"]

    unknown = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "randomization",
            "source_id": "source_" + "0" * 64,
        },
    )
    assert unknown["outcome"] == "condition"
    assert unknown["condition"]["code"] == "invalid_request"

    foreign_source = _call(workspace, "list_sources", {"trial_id": "second"})["data"]["sources"][0]
    cross_trial = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "randomization",
            "source_id": foreign_source["id"],
        },
    )
    assert cross_trial["outcome"] == "condition"
    assert cross_trial["condition"]["code"] == "invalid_request"


def test_render_cache_returns_pixels_by_default_and_allows_metadata_only(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A rendered table")
    (workspace / "input" / "trial" / "table.pdf").write_bytes(pdf.tobytes())
    pdf.close()
    _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "table.pdf"
    )
    before = int(COUNTERS["render_bytes"])
    reference = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    assert "png_base64" not in reference
    assert len(reference["_image_content"]) == 1
    after_first = int(COUNTERS["render_bytes"])
    assert after_first > before
    cached = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    assert "png_base64" not in cached
    assert len(cached["_image_content"]) == 1
    assert int(COUNTERS["render_bytes"]) == after_first
    inline = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1, "inline": False},
    )
    assert "png_base64" not in inline
    assert inline["_image_content"] == []
    assert inline["data"]["render"] == reference["data"]["render"]
    assert int(COUNTERS["render_bytes"]) == after_first
