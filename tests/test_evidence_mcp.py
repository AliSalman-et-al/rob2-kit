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
from rob2_kit.application.evidence import _normalized_contains, _search_receipt


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


def test_search_preserves_source_priority_then_uses_fts_bm25_within_source(
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
    assert pairs[:3] == [(article["id"], int(page)) for page, _rank in article_ranks]
    assert pairs[3] == (protocol_source["id"], 1)


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
    assert set(page) == {"page", "numbered_text", "line_count"}
    assert page["numbered_text"] == ("0001|first line\n0002|middle-\n0003|line\n0004|last line")

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


def test_boundary_text_selects_one_sentence_from_shared_lines(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "Prior sentence. An intention-to-treat analy-\n"
        "sis included all randomly assigned patients. P values were\n"
        "two-sided.\n",
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
            "end_line": 2,
            "start_text": "An intention-to-treat analy-",
            "end_text": "patients.",
        },
    )

    assert selected["outcome"] == "success"
    assert selected["data"]["evidence"]["quote"].splitlines() == [
        "An intention-to-treat analy-",
        "sis included all randomly assigned patients.",
    ]


def test_boundary_text_must_be_unique_within_its_numbered_line(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "same text, same text.\n", encoding="utf-8"
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    result = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
            "start_text": "same text",
        },
    )

    assert result["outcome"] == "condition"
    assert result["condition"]["detail"] == (
        "boundary text must match exactly once within its numbered boundary line"
    )


@pytest.mark.parametrize("source_text", ("The analysis was specified by the\n", "Please note\n"))
def test_select_text_evidence_rejects_incomplete_page_boundary_fragment(
    tmp_path: Path, source_text: str
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(source_text, encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    invalid = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )

    assert invalid["outcome"] == "condition"
    assert invalid["condition"]["code"] == "invalid_request"
    assert "incomplete" in invalid["condition"]["detail"]
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence_handles").fetchone()[0] == 0


@pytest.mark.parametrize(
    "source_text, end_line",
    (
        ("# Characteristics of the\n", 1),
        ("- The following\n", 1),
        ("| Measure | the |\n", 1),
        ("Please Note\n", 1),
        ("The analysis was specified by the\nprotocol.\n", 2),
        ("The analysis was specified by the protocol.\n", 1),
    ),
)
def test_select_text_evidence_preserves_structural_and_complete_fragments(
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
        ("If a dose was reduced\nfor toxicity.\n", 1),
        ("The assessment used CTCAE\nversion 4.0.\n", 1),
        ("The analysis accounted for the use of the\nplanned model.\n", 1),
        ("The treatment continued for\nsix cycles.\n", 1),
        ("The hazard ratio was 0.61;\n95% confidence interval, 0.47 to 0.80.\n", 1),
    ),
)
def test_select_text_evidence_rejects_incomplete_mid_page_prose(
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

    invalid = _call(
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

    assert invalid["outcome"] == "condition"
    assert invalid["condition"]["code"] == "invalid_request"
    assert "incomplete" in invalid["condition"]["detail"]


def test_select_text_evidence_rejects_cross_page_continuation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Treatment was planned for six")
    document.new_page().insert_text((72, 72), "cycles.")
    (trial / "article.pdf").write_bytes(document.tobytes())
    document.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    invalid = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )

    assert invalid["outcome"] == "condition"
    assert "incomplete" in invalid["condition"]["detail"]


def test_select_text_evidence_ignores_footer_before_cross_page_continuation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    document = pymupdf.open()
    document.new_page().insert_text(
        (72, 72),
        "Treatment was planned for six\nThe Journal is produced by Example Publisher.",
    )
    document.new_page().insert_text((72, 72), "journal.example\n12\ncycles.")
    (trial / "article.pdf").write_bytes(document.tobytes())
    document.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    invalid = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 2,
        },
    )

    assert invalid["outcome"] == "condition"
    assert "incomplete" in invalid["condition"]["detail"]


def test_select_text_evidence_rejects_long_footnote_ending_in_connector(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "* There were no significant differences between groups when analyzed with the use of the\n"
        "Wilcoxon rank-sum test.\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    invalid = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )

    assert invalid["outcome"] == "condition"
    assert "incomplete" in invalid["condition"]["detail"]


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
        ("e\u0301-\nvalue", "\u00e9value", True),
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
