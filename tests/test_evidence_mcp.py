"""MCP evidence selection, rendering, and normalization behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

import hashlib
import json
import runpy
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastmcp.exceptions import ToolError
from support.rob2 import *  # noqa: F401,F403

import rob2_kit.interfaces.mcp.server as mcp_server
from rob2_kit.application import finalization
from rob2_kit.application._state import _identity, _normalized_text_with_spans, _state
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import (
    _evidence_catalog,
    _normalized_contains,
    _normalized_match,
    _result_value_contains,
    _search_receipt,
)
from rob2_kit.application.source_handles import resolve_source_handle


def test_native_quote_selection_requires_delivered_text_and_preserves_range_identity(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input/trial/quotes.txt").write_text(
        "Header.\nUnique outcome at 3 years.\nRepeated phrase.\nRepeated phrase.\n"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "quotes.txt"
    )
    args = {"trial_id": "trial", "source_id": source["id"], "page": 1}
    _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "Unique outcome", "mode": "all"}
    )
    rejected = _call(
        workspace,
        "select_text_evidence",
        {**args, "selected_text": "Unique outcome at 3 years."},
    )
    assert rejected["outcome"] != "success"
    assert "not fully delivered by read_pages" in json.dumps(rejected)
    _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [{"source_id": source["id"], "page": 1, "start_line": 2, "end_line": 2}],
        },
    )
    quote = _call(
        workspace, "select_text_evidence", {**args, "selected_text": "Unique outcome at 3 years."}
    )["data"]["evidence"]
    ranged = _call(workspace, "select_text_evidence", {**args, "start_line": 2, "end_line": 2})[
        "data"
    ]["evidence"]
    assert quote == ranged
    assert quote["quote"] == "Unique outcome at 3 years."
    assert quote["start_line"] == quote["end_line"] == 2
    for text, message in (
        ("Repeated phrase.", "ambiguous"),
        ("Unique outcome at 4 years.", "not an exact page selection"),
    ):
        rejected = _call(workspace, "select_text_evidence", {**args, "selected_text": text})
        assert rejected["outcome"] != "success"
        assert message in json.dumps(rejected)
    rejected = _call(
        workspace,
        "select_text_evidence",
        {**args, "selected_text": "Header.", "start_line": 1, "end_line": 1},
    )
    assert rejected["outcome"] != "success"
    assert "not both" in json.dumps(rejected)
    assert _state(workspace)["revision"] == 1


def test_native_quote_preserves_numeric_hyphens_and_source_line_wraps(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input/trial/hyphens.txt").write_text(
        "Risk 1 3 years.\nDose 50 69 mg.\nChange 3 points.\n"
        "A multi-\nstage procedure.\nRange 50-\n69 mg.\n"
        "Repeated multistage.\nRepeated multi-\nstage.\n"
        "follow-up\nfollow-\nup\n"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "hyphens.txt"
    )
    args = {"trial_id": "trial", "source_id": source["id"], "page": 1}
    _call(workspace, "read_pages", {"trial_id": "trial", "source_id": source["id"], "pages": [1]})
    for quote in (
        "Risk 1-3 years.",
        "Dose 50-69 mg.",
        "Change -3 points.",
        "Range 5069 mg.",
    ):
        rejected = _call(workspace, "select_text_evidence", {**args, "selected_text": quote})
        assert rejected["outcome"] != "success"
        assert "not an exact page selection" in json.dumps(rejected)
    for quote, raw in (
        ("A multistage procedure.", "A multi-\nstage procedure."),
        ("A multi-stage procedure.", "A multi-\nstage procedure."),
        ("A multi-\nstage procedure.", "A multi-\nstage procedure."),
        ("Range 50-69 mg.", "Range 50-\n69 mg."),
    ):
        selected = _call(workspace, "select_text_evidence", {**args, "selected_text": quote})
        assert selected["data"]["evidence"]["quote"] == raw
    rejected = _call(
        workspace, "select_text_evidence", {**args, "selected_text": "Repeated multistage."}
    )
    assert rejected["outcome"] != "success"
    assert "ambiguous" in json.dumps(rejected)
    rejected = _call(workspace, "select_text_evidence", {**args, "selected_text": "follow-up"})
    assert rejected["outcome"] != "success"
    assert "ambiguous" in json.dumps(rejected)


def test_native_quote_selection_rejects_coverage_gaps_and_wrong_physical_page(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    document.new_page().insert_text((48, 48), "First line.\nMiddle line.\nLast line.")
    document.new_page().insert_text((48, 48), "Unique second page.")
    (workspace / "input/trial/quotes.pdf").write_bytes(document.tobytes())
    document.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "quotes.pdf"
    )
    args = {"trial_id": "trial", "source_id": source["id"], "page": 1}
    _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {"source_id": source["id"], "page": 1, "start_line": line, "end_line": line}
                for line in (1, 3)
            ],
        },
    )
    rejected = _call(
        workspace,
        "select_text_evidence",
        {**args, "selected_text": "First line. Middle line. Last line."},
    )
    assert rejected["outcome"] != "success"
    assert "not fully delivered by read_pages" in json.dumps(rejected)
    _call(workspace, "read_pages", {"trial_id": "trial", "source_id": source["id"], "pages": [2]})
    rejected = _call(
        workspace, "select_text_evidence", {**args, "selected_text": "Unique second page."}
    )
    assert rejected["outcome"] != "success"
    assert "not an exact page selection" in json.dumps(rejected)
    second = _call(
        workspace,
        "select_text_evidence",
        {**args, "page": 2, "selected_text": "Unique second page."},
    )["data"]["evidence"]
    assert second["page"] == 2
    _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [{"source_id": source["id"], "page": 1, "start_line": 2, "end_line": 2}],
        },
    )
    joined = _call(
        workspace,
        "select_text_evidence",
        {**args, "selected_text": "First line. Middle line. Last line."},
    )["data"]["evidence"]
    assert joined["quote"] == "First line.\nMiddle line.\nLast line."


def test_search_feedback_includes_matching_terms_beyond_source_prefix(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    for index in range(65):
        text = "alpha only\n" if index == 64 else "control only\n"
        (trial / f"source-{index:02d}.txt").write_text(text, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    data = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "all"},
    )["data"]

    target = next(
        source
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if source["label"] == "source-64.txt"
    )
    source = next(item for item in data["term_feedback"] if item["source_id"] == target["id"])
    assert data["total_matches"] == 0
    assert data["term_feedback_sources_truncated"] is True
    assert len(data["term_feedback"]) == 64
    assert source["query_matching_page_count"] == 0
    assert {row["term"]: row["matching_page_count"] for row in source["term_page_counts"]} == {
        "alpha": 1,
        "beta": 0,
    }


def test_oversized_candidate_exposes_read_pages_recovery(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    text = "target " + ("é" * 1_980) + " needle\n"
    (workspace / "input" / "trial" / "main.txt").write_text(text, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "target needle", "mode": "all", "limit": 10},
    )["data"]
    [hit] = result["hits"]

    assert hit["candidate_truncated"] is True
    recovery = hit["candidate_recovery"]
    assert recovery["operation"] == "read_pages"
    assert recovery["trial_id"] == "trial"
    assert recovery["windows"] == [
        {
            "source_id": hit["source_id"],
            "page": hit["page"],
            "start_line": 1,
            "end_line": 1,
        }
    ]
    assert len(hit["preview"].encode("utf-8")) <= 2_048
    assert hit["preview"].startswith("target ")
    catalog = _evidence_catalog(workspace, "trial")
    assert any(
        item["handle"] == hit["passage_ref"] and item["quote"] == hit["preview"]
        for item in catalog.values()
    )


def test_search_session_identity_uses_normalized_query(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )

    plain = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "all"},
    )["data"]
    punctuated = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "  REQUESTED, outcome!! ", "mode": "all"},
    )["data"]

    assert punctuated["session_id"] == plain["session_id"]
    assert [hit["rank"] for hit in punctuated["hits"]] == [hit["rank"] for hit in plain["hits"]]


def test_search_cursor_conditions_are_typed_and_source_scope_is_bound(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("needle one\nneedle two\n", encoding="utf-8")
    protocol = pymupdf.open()
    for page_number in (1, 2):
        protocol.new_page().insert_text((72, 72), f"needle protocol page {page_number}")
    protocol.save(trial / "protocol.pdf")
    protocol.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    main_source = next(source for source in sources if source["logical_path"].endswith("main.txt"))
    protocol_source = next(
        source for source in sources if source["logical_path"].endswith("protocol.pdf")
    )
    first = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "needle", "mode": "any", "limit": 1},
    )["data"]
    stale = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "different", "mode": "any", "cursor": first["next_cursor"]},
    )
    assert stale["condition"]["code"] == "search_cursor_stale"
    scoped = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "needle",
            "mode": "any",
            "source_id": protocol_source["id"],
            "limit": 1,
        },
    )["data"]
    assert scoped["next_cursor"] is not None, scoped
    mismatch = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "needle",
            "mode": "any",
            "source_id": main_source["id"],
            "cursor": scoped["next_cursor"],
        },
    )
    assert mismatch["condition"]["code"] == "search_cursor_stale"
    expired = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "needle",
            "mode": "any",
            "cursor": first["next_cursor"].rsplit("_", 1)[0] + "_999",
        },
    )
    assert expired["condition"]["code"] == "search_cursor_expired"


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


def test_source_navigation_is_literal_bounded_and_cursor_stable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    for text in ("Protocol cover" for _ in range(5)):
        document.new_page().insert_textbox((48, 48, 540, 760), text)
    document.new_page().insert_textbox(
        (48, 48, 540, 760),
        "5. Randomisation",
    )
    document.new_page().insert_textbox(
        (48, 48, 540, 760),
        "The study will randomise participants using a central process.\n6. Withdrawal of Subjects",
    )
    (workspace / "input" / "trial" / "protocol.pdf").write_bytes(document.tobytes())
    document.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "protocol.pdf"
    )

    first = _call(
        workspace,
        "list_sources",
        {"trial_id": "trial", "source_id": source["id"], "limit": 2},
    )["data"]["navigation"]
    assert first["source_id"] == source["id"]
    assert first["projection_hash"] == source["projection_hash"]
    assert first["navigation_version"] == "rob2-kit.source-navigation.v0.5"
    assert first["pages_examined"] == 7
    assert all(len(entry["text"]) <= 512 for entry in first["entries"])

    entries = list(first["entries"])
    cursor = first["next_cursor"]
    while cursor is not None:
        page = _call(
            workspace,
            "list_sources",
            {"trial_id": "trial", "source_id": source["id"], "limit": 2, "cursor": cursor},
        )["data"]["navigation"]
        entries.extend(page["entries"])
        cursor = page["next_cursor"]
    assert len({(entry["page"], entry["start_line"], entry["kind"]) for entry in entries}) == len(
        entries
    )
    assert any(
        entry["kind"] == "heading_candidate" and entry["text"] == "5. Randomisation"
        for entry in entries
    )
    assert any(
        entry["kind"] == "page_excerpt" and "randomise participants" in entry["text"]
        for entry in entries
    )

    other_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["id"] != source["id"]
    )
    wrong_source = _call(
        workspace,
        "list_sources",
        {
            "trial_id": "trial",
            "source_id": other_source["id"],
            "cursor": first["next_cursor"],
        },
    )
    assert wrong_source["outcome"] == "condition"
    assert wrong_source["condition"]["code"] == "source_navigation_cursor_stale"

    stale = _call(
        workspace,
        "list_sources",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "cursor": first["next_cursor"].replace("sn1.", "bad.")
            if first["next_cursor"]
            else "bad.cursor",
        },
    )
    assert stale["outcome"] == "condition"
    assert stale["condition"]["code"] == "source_navigation_cursor_invalid"

    no_hit = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "allocation concealment",
            "mode": "all",
            "source_id": source["id"],
        },
    )["data"]
    preview = no_hit["diagnostic"]["navigation"]
    assert any(
        entry["page"] == 6
        and entry["kind"] == "heading_candidate"
        and entry["text"] == "5. Randomisation"
        for entry in preview["entries"]
    )
    assert any(
        entry["page"] == 7
        and entry["kind"] == "page_excerpt"
        and "randomise participants" in entry["text"]
        for entry in preview["entries"]
    )
    reformulated = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "randomise participants",
            "mode": "all",
            "source_id": source["id"],
        },
    )["data"]
    assert reformulated["hits"]
    assert reformulated["hits"][0]["page"] == 7


def test_source_navigation_pages_metadata_spans_and_preserves_exact_recovery(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    leads = [
        f"Revision {index}.0; amended 2026-01-{(index % 28) + 1:02d}" for index in range(1, 201)
    ]
    (workspace / "input" / "trial" / "protocol.txt").write_text("\n".join(leads), encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "protocol.txt"
    )

    def span_key(span: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            span.get(field) for field in ("page", "start_line", "end_line", "kind", "text")
        )

    entries: list[dict[str, Any]] = []
    version_spans: list[dict[str, Any]] = []
    date_spans: list[dict[str, Any]] = []
    cursor = None
    while True:
        args: dict[str, object] = {
            "trial_id": "trial",
            "source_id": source["id"],
            "limit": 12,
        }
        if cursor is not None:
            args["cursor"] = cursor
        page = _call(workspace, "list_sources", args)["data"]["navigation"]
        page_entries = page["entries"]
        entries.extend(page_entries)
        version_spans.extend(page["version_spans"])
        date_spans.extend(page["date_spans"])

        assert len(page_entries) <= 12
        assert page["returned_entries"] == len(page_entries)
        assert len(page["version_spans"]) <= len(page_entries)
        assert len(page["date_spans"]) <= len(page_entries)
        entry_keys = {span_key(entry) for entry in page_entries}
        assert {span_key(span) for span in page["version_spans"]} <= entry_keys
        assert {span_key(span) for span in page["date_spans"]} <= entry_keys
        assert (
            len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            <= 24_000
        )

        cursor = page["next_cursor"]
        if cursor is None:
            assert page["terminal"] is True
            break

    assert len(version_spans) == 200
    assert len(date_spans) == 200
    assert len({span_key(span) for span in version_spans}) == 200
    assert len({span_key(span) for span in date_spans}) == 200
    assert len(entries) == 401

    span = version_spans[-1]
    recovered = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": source["id"],
                    "page": span["page"],
                    "start_line": span["start_line"],
                    "end_line": span["end_line"],
                }
            ],
        },
    )["data"]["pages"][0]
    assert recovered["numbered_text"] == f"{span['start_line']}|{span['text']}"


def test_long_source_navigation_metadata_is_bounded_and_recoverable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    long_sources = {
        "version.txt": f"Version v{'2' * 700} amendment.",
        "date.txt": f"Protocol approved on January 1, 2026 {'d' * 700}.",
        "contents.txt": f"Table of contents {'c' * 700}.",
        "cross-reference.txt": f"See section 5 {'r' * 700}.",
        "heading.txt": f"Section 5 Methods\n\nSee section 5 {'h' * 700}.",
    }
    for label, text in long_sources.items():
        (workspace / "input" / "trial" / label).write_text(text, encoding="utf-8")
    (workspace / "input" / "trial" / "control.txt").write_text(
        "Ordinary short control.", encoding="utf-8"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    sources = {
        source["label"]: source["id"]
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    }

    def navigation(source_id: str) -> dict[str, Any]:
        return _call(
            workspace,
            "list_sources",
            {"trial_id": "trial", "source_id": source_id},
        )["data"]["navigation"]

    navigations = {label: navigation(sources[label]) for label in long_sources}
    for page in navigations.values():
        for entry in (*page["entries"], *page["version_spans"], *page["date_spans"]):
            for field in ("text", "logical_section", "embedded_version"):
                if entry.get(field) is not None:
                    assert len(entry[field]) <= 512

    version = next(
        entry
        for entry in navigations["version.txt"]["version_spans"]
        if entry["kind"] == "version_lead"
    )
    date = navigations["date.txt"]["date_spans"][0]
    contents = next(
        entry for entry in navigations["contents.txt"]["entries"] if entry["kind"] == "page_excerpt"
    )
    cross_reference = next(
        entry
        for entry in navigations["cross-reference.txt"]["entries"]
        if entry["kind"] == "cross_reference_lead"
    )
    heading_cross_reference = next(
        entry
        for entry in navigations["heading.txt"]["entries"]
        if entry["kind"] == "cross_reference_lead"
    )
    recoverable_entries = [
        ("version.txt", version),
        ("date.txt", date),
        ("contents.txt", contents),
        ("cross-reference.txt", cross_reference),
        ("heading.txt", heading_cross_reference),
    ]
    for label, entry in recoverable_entries:
        expected_window = {
            "source_id": sources[label],
            "page": entry["page"],
            "start_line": entry["start_line"],
            "end_line": entry["end_line"],
        }
        recovery = json.dumps(
            {"trial_id": "trial", "windows": [expected_window]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert "omitted" in entry["text"]
        assert f"read_pages {recovery}" in entry["text"]
        recovered = _call(
            workspace,
            "read_pages",
            {"trial_id": "trial", "windows": [expected_window]},
        )["data"]["pages"][0]
        full_line = long_sources[label].splitlines()[entry["start_line"] - 1]
        assert recovered["numbered_text"] == f"{entry['start_line']}|{full_line}"

    heading_section = next(
        entry["logical_section"]
        for entry in navigations["heading.txt"]["entries"]
        if entry["kind"] == "cross_reference_lead"
    )
    assert heading_section == "Section 5 Methods"

    short_control = navigation(sources["control.txt"])
    assert any(entry["text"] == "Ordinary short control." for entry in short_control["entries"])

    no_hit = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "source_id": sources["version.txt"],
            "query": "absent concept",
            "mode": "phrase",
        },
    )["data"]
    assert no_hit["condition"] == "no_hits"
    assert no_hit["diagnostic"]["code"] == "no_hits"
    assert "issued lexical query matched no captured text" in no_hit["diagnostic"]["detail"]
    for entry in no_hit["diagnostic"]["navigation"]["entries"]:
        for field in ("text", "logical_section", "embedded_version"):
            if entry.get(field) is not None:
                assert len(entry[field]) <= 512

    batch = _call(
        workspace,
        "search_sources_batch",
        {
            "requests": [
                {
                    "trial_id": "trial",
                    "source_id": sources["version.txt"],
                    "query": "absent concept",
                    "mode": "phrase",
                },
                {
                    "trial_id": "trial",
                    "source_id": "sh_0000000000000000",
                    "query": "absent concept",
                    "mode": "phrase",
                },
                {
                    "trial_id": "trial",
                    "source_id": sources["control.txt"],
                    "query": "ordinary short control",
                    "mode": "phrase",
                },
            ]
        },
    )["data"]["results"]
    assert [item["result"]["outcome"] for item in batch] == [
        "success",
        "condition",
        "success",
    ]
    assert batch[0]["result"]["data"]["diagnostic"]["code"] == "no_hits"
    assert batch[1]["result"]["condition"]["code"] == "invalid_request"
    assert batch[2]["result"]["data"]["hits"]


def test_search_batch_schema_failure_is_not_reported_as_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    monkeypatch.setattr(mcp_server, "_search_sources", lambda *_args: {})

    with pytest.raises(ToolError, match="internal_output_contract_error"):
        _call(
            workspace,
            "search_sources_batch",
            {
                "requests": [
                    {"trial_id": "trial", "query": "alpha", "mode": "any"},
                ]
            },
        )


def test_source_navigation_reports_empty_text_projection(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").unlink()
    document = pymupdf.open()
    document.new_page()
    (workspace / "input" / "trial" / "image-only.pdf").write_bytes(document.tobytes())
    document.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    navigation = _call(
        workspace,
        "list_sources",
        {"trial_id": "trial", "source_id": source["id"]},
    )
    assert navigation["outcome"] == "success"
    assert navigation["data"]["navigation"]["condition"] == "no_text_projection"
    assert navigation["data"]["navigation"]["entries"] == []
    assert navigation["data"]["navigation"]["pages_without_text_projection"] == [1]


def test_search_uses_global_fts_bm25_with_deterministic_ties(
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
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        article_ranks = connection.execute(
            "SELECT page,bm25(pages_fts) FROM pages_fts "
            "WHERE pages_fts MATCH ? AND source_id=? ORDER BY bm25(pages_fts),page",
            ('"alpha" AND "beta"', resolve_source_handle(workspace, "trial", article["id"])),
        ).fetchall()
        global_ranks = connection.execute(
            "SELECT source_id,page,bm25(pages_fts) FROM pages_fts WHERE pages_fts MATCH ?",
            ('"alpha" OR "beta"',),
        ).fetchall()
    assert article_ranks[0][0] != 1

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 4},
    )
    pairs = [(item["source_id"], item["page"]) for item in result["data"]["hits"]]
    public_by_internal = {
        resolve_source_handle(workspace, "trial", source["id"]): source["id"] for source in sources
    }
    source_order = {
        resolve_source_handle(workspace, "trial", source["id"]): index
        for index, source in enumerate(sources)
    }
    global_ranks.sort(key=lambda row: (float(row[2]), source_order[row[0]], int(row[1])))
    assert pairs == [
        (public_by_internal[source_id], int(page)) for source_id, page, _rank in global_ranks[:4]
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


def test_read_pages_budget_includes_pending_assessment_context_cursor(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input/trial/supplement.txt").write_text(
        "\n".join("é" * 30 for _ in range(1000)), encoding="utf-8"
    )
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required"
    _review(workspace)
    too_small = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization", "max_response_bytes": 4096},
    )
    assert too_small["outcome"] == "condition"
    assert "domain_context_header_oversized" in json.dumps(too_small)
    _read_required_main_reports(workspace)
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization", "max_response_bytes": 16384},
    )
    assert context["outcome"] == "success", context
    assert context["data"]["context_page"]["next_cursor"] is not None
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "supplement.txt"
    )
    request: dict[str, object] = {
        "trial_id": "trial",
        "windows": [{"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1000}],
    }
    first = _call(workspace, "read_pages", request)
    assert first["outcome"] == "success"
    continuation = first["head"]["next_action"]
    assert continuation["cursor"] == context["data"]["context_page"]["next_cursor"]
    assert continuation["max_response_bytes"] == 16384
    wire_bytes = len(
        json.dumps(
            {
                "content": [],
                "structured_content": {
                    key: value for key, value in first.items() if key != "_image_content"
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ROB2_WORKSPACE", str(workspace))
        assert (
            mcp_server._read_pages_transport_bytes(
                {"outcome": "success", **first["data"]}, mcp_server._get_status_head(workspace)
            )
            == wire_bytes
        )
    assert 23_000 < wire_bytes <= 24_000
    assert first["data"]["remaining_windows"]

    internal_id = resolve_source_handle(workspace, "trial", source["id"])
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT MAX(end_line) FROM page_reads WHERE source_id=?", (internal_id,)
            ).fetchone()[0]
            == first["data"]["pages"][0]["returned_end_line"]
        )


@pytest.mark.parametrize(
    "oversized_text", ["x" * 30_000, "é🧪|数\t" * 6_000], ids=["ascii", "unicode-table"]
)
def test_read_pages_oversized_single_line_makes_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oversized_text: str
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(oversized_text, encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    def fake_read_pages(
        _workspace_path: Path, _trial_id: str, _source_id: str, _pages: list[int]
    ) -> dict[str, Any]:
        return {"pages": [{"page": 1, "text": oversized_text}]}

    monkeypatch.setattr(mcp_server, "_read_pages", fake_read_pages)
    result = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )
    page = result["data"]["pages"][0]
    assert page["line_count"] == page["returned_end_line"] == 1
    assert page["line_fragment"] is True
    assert page["returned_start_char"] == 0
    assert page["next_start_char"] > 0
    assert page["passage_ref"] is None

    chunks = [page["numbered_text"].split("|", 1)[1]]
    next_start_char = page["next_start_char"]
    while next_start_char is not None:
        continued = _call(
            workspace,
            "read_pages",
            {
                "trial_id": "trial",
                "source_id": source["id"],
                "pages": [1],
                "start_line": 1,
                "start_char": next_start_char,
            },
        )
        next_page = continued["data"]["pages"][0]
        chunks.append(next_page["numbered_text"].split("|", 1)[1])
        assert next_page["returned_start_line"] == 1
        assert next_page["returned_start_char"] == next_start_char
        assert next_page["passage_ref"] is None
        next_start_char = next_page["next_start_char"]

    assert "".join(chunks) == oversized_text


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
        ("A1-\nB2", "A1B2", True),
    )

    for material, claim, expected in cases:
        assert _normalized_contains(material, claim) is expected
        assert standalone_normalized_contains(material, claim) is expected


def test_numeric_line_wrap_does_not_create_scalar_matches_or_invalid_spans() -> None:
    standalone = runpy.run_path("scripts/verify_bundle.py")
    standalone_normalized_with_spans = standalone["_normalized_with_spans"]
    cases = (
        ("Age 1-\n3 years", "13", "1-3", "1-\n3"),
        ("Age 50-\r\n69 years", "5069", "50-69", "50-\r\n69"),
        ("D-dimer 0.8-\n1.2", "0.81.2", "0.8-1.2", "0.8-\n1.2"),
    )

    for material, scalar, numeric_range, expected_raw in cases:
        assert _normalized_contains(material, scalar) is False
        assert _normalized_match(material, scalar) == (None, "absent")
        assert standalone_normalized_contains(material, scalar) is False
        assert _normalized_contains(material, numeric_range) is True
        assert standalone_normalized_contains(material, numeric_range) is True
        assert _normalized_match(material, numeric_range) == (expected_raw, None)
        for normalize in (_normalized_text_with_spans, standalone_normalized_with_spans):
            for dehyphenate in (True, False):
                normalized, spans = normalize(material, dehyphenate_line_ends=dehyphenate)
                assert scalar not in normalized
                assert numeric_range in normalized
                assert len(normalized) == len(spans)
                assert all(0 <= start <= end <= len(material) for start, end in spans)


def test_numeric_result_binding_requires_complete_literal_expressions() -> None:
    standalone = runpy.run_path("scripts/verify_bundle.py")
    standalone_contains = standalone["_result_value_contains"]
    cases = (
        ("Deaths: 34; ratio 0.84 (CI 0.64 to 1.14).", "4", "/reported/estimate", False),
        ("Deaths: 34; ratio 0.84 (CI 0.64 to 1.14).", "0.8", "/reported/estimate", False),
        ("Deaths: 34; ratio 0.84 (CI 0.64 to 1.14).", "0.84", "/reported/estimate", True),
        ("Age 1-\n3 years", "13", "/reported/group_values/0/value", False),
        ("Age 1-\n3 years", "1-3", "/reported/group_values/0/value", True),
        ("Age 1-\n3 years", "1", "/reported/group_values/0/value", True),
        ("Age 1-\n3 years", "3", "/reported/group_values/0/value", True),
        ("1 2 participants", "1", "/reported/estimate", True),
        ("NCT003 and 3 patients", "3", "/reported/estimate", True),
        ("NCT003", "3", "/reported/estimate", False),
        ("3a", "3", "/reported/estimate", False),
        ("estimate -2", "2", "/reported/estimate", False),
        ("estimate -2", "-2", "/reported/estimate", True),
        ("estimate 3 - marker", "3", "/reported/estimate", True),
        ("estimate 3-ABC", "3", "/reported/estimate", False),
        ("Deaths 2 (12)b", "2 (12)", "/reported/estimate", True),
        ("Deaths 2 (12)a,b", "2 (12)", "/reported/estimate", True),
        ("Deaths 2 (12)abc", "2 (12)", "/reported/estimate", False),
        ("Deaths 2 (12)b", "2", "/reported/estimate", False),
        ("Deaths 2 (12)b", "12", "/reported/estimate", False),
        ("Change -3.32±0.54a", "-3.32±0.54", "/reported/estimate", True),
        ("Change -3.32±0.54a,b", "-3.32±0.54", "/reported/estimate", True),
        ("Change -3.32±0.54abc", "-3.32±0.54", "/reported/estimate", False),
        ("Change -3.32±0.54a", "0.54", "/reported/estimate", False),
        ("Change -3.32±0.54a", "3.32±0.54", "/reported/estimate", False),
        ("Change T-3.32±0.54a", "-3.32±0.54", "/reported/estimate", False),
        ("Change -3.32±0.54a", "-3.3±0.54", "/reported/estimate", False),
        ("estimate 1e-3", "1", "/reported/estimate", False),
        ("estimate 1e-3", "1e-3", "/reported/estimate", True),
        ("estimate 1,234", "1", "/reported/estimate", False),
        ("estimate 1,234", "1,234", "/reported/estimate", True),
        ("estimate 1,5", "1,5", "/reported/estimate", True),
        ("estimate > 5", "5", "/reported/estimate", False),
        ("estimate > 5", "> 5", "/reported/estimate", True),
        ("estimate 5%", "5", "/reported/group_values/0/value", True),
        ("estimate 5%", "5", "/reported/estimate", False),
        ("estimate 5%", "5%", "/reported/estimate", True),
    )
    for material, phrase, path, expected in cases:
        assert _result_value_contains(material, phrase, path) is expected
        assert standalone_contains(material, phrase, path) is expected


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
        {"trial_id": "trial", "query": "randomization", "mode": "any", "limit": 1},
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
            "mode": "any",
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
        {
            "id": resolve_source_handle(workspace, "trial", protocol_source["id"]),
            "projection_hash": protocol_source["projection_hash"],
        }
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
            "mode": "any",
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
            "mode": "any",
            "source_id": "sh_" + "0" * 16,
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
            "mode": "any",
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
    assert reference["data"]["delivery_receipt"].startswith("sha256:")
    assert reference["_image_content"][0].mime_type == "image/png"
    after_first = int(COUNTERS["render_bytes"])
    assert after_first > before
    cached = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1},
    )
    assert "png_base64" not in cached
    assert len(cached["_image_content"]) == 1
    assert cached["data"]["delivery_receipt"] == reference["data"]["delivery_receipt"]
    assert int(COUNTERS["render_bytes"]) == after_first
    inline = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": source["id"], "page": 1, "inline": False},
    )
    assert "png_base64" not in inline
    assert inline["_image_content"] == []
    assert inline["data"]["render"] == reference["data"]["render"]
    assert inline["data"]["delivery_receipt"] is None
    assert int(COUNTERS["render_bytes"]) == after_first
    unavailable = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "delivery_receipt": "sha256:" + "0" * 64,
            "transcription": "A rendered table",
            "region": [0.0, 0.0, 1.0, 1.0],
        },
    )
    assert unavailable["outcome"] == "condition"
    assert "delivered ImageContent" in unavailable["condition"]["detail"]


@pytest.mark.parametrize("start_char,end_char", [(9, 20), (9, 9)])
def test_read_pages_deferred_window_preserves_character_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start_char: int, end_char: int
) -> None:
    workspace = _workspace(tmp_path)
    line = "Observed évents; exclusions remain unexplained."
    (workspace / "input" / "trial" / "main.txt").write_text(line, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    window = {
        "source_id": source["id"],
        "page": 1,
        "start_line": 1,
        "end_line": 1,
        "start_char": start_char,
        "end_char": end_char,
    }
    original = mcp_server._read_pages_transport_bytes

    def one_page_budget(value: dict[str, Any], head: dict[str, Any]) -> int:
        if len(value["pages"]) > 1:
            return mcp_server._READ_PAGES_RESPONSE_BYTES + 1
        return original(value, head)

    with monkeypatch.context() as patch:
        patch.setattr(mcp_server, "_read_pages_transport_bytes", one_page_budget)
        first = _call(
            workspace,
            "read_pages",
            {
                "trial_id": "trial",
                "windows": [
                    {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1},
                    window,
                ],
            },
        )["data"]
    assert len(first["pages"]) == 1
    assert first["remaining_windows"] == [window]
    resumed = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": first["remaining_windows"],
        },
    )["data"]
    assert resumed["remaining_windows"] == []
    assert resumed["pages"][0]["numbered_text"] == "1|" + line[start_char:end_char]
    assert resumed["pages"][0]["passage_ref"] is None


def test_historical_anchor_recipe_receipt_remains_verifiable(tmp_path: Path) -> None:
    from rob2_kit.application.evidence import _session_candidates

    workspace = _workspace(tmp_path)
    text = "alpha\ncontext\ncontext\nbeta\n"
    (workspace / "input" / "trial" / "main.txt").write_text(text, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 10},
    )["data"]
    current_receipt = _search_receipt(workspace, result["search_receipt"])
    connection = sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3")
    current_session = json.loads(
        connection.execute(
            "SELECT payload FROM search_sessions WHERE identity=?", (result["session_id"],)
        ).fetchone()[0]
    )
    spec: dict[str, Any] = {
        **current_session["spec"],
        "candidate_version": "rob2-kit.search-candidates.v0.9",
    }
    identity = _identity(spec)
    source_id = spec["sources"][0]["id"]
    candidates = _session_candidates(
        {source_id: (text,)},
        "alpha beta",
        "any",
        [source_id],
        [(source_id, 1)],
        candidate_version="rob2-kit.search-candidates.v0.9",
    )
    session = {
        **current_session,
        "spec": spec,
        "identity": identity,
        "handle": "ss_" + identity.removeprefix("sha256:")[:16],
        "candidate_count": 2,
    }
    receipt = {k: v for k, v in current_receipt.items() if k not in {"identity", "handle"}}
    receipt.update(
        session_id=identity,
        session_handle=session["handle"],
        candidate_count=2,
        returned_rank_end=2,
        returned_material=2,
        hits=[{"source_id": source_id, "page": 1}] * 2,
        returned_candidates=[
            {k: c[k] for k in ("rank", "source_id", "page", "start_line", "end_line")}
            for c in candidates
        ],
    )
    receipt["identity"] = _identity(receipt)
    handle = "sr_" + receipt["identity"].removeprefix("sha256:")[:16]
    receipt["handle"] = handle
    connection.execute(
        "INSERT INTO search_sessions VALUES (?,?)", (identity, json.dumps(session).encode("utf-8"))
    )
    connection.executemany(
        "INSERT INTO search_candidates VALUES (?,?,?)",
        [(identity, c["rank"], json.dumps(c).encode("utf-8")) for c in candidates],
    )
    connection.execute(
        "INSERT INTO search_receipts VALUES (?,?)",
        (receipt["identity"], json.dumps(receipt).encode("utf-8")),
    )
    connection.commit()
    connection.close()
    assert _search_receipt(workspace, handle) == receipt
    assert _search_receipt(workspace, result["search_receipt"]) == current_receipt

    stale = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "alpha beta",
            "mode": "any",
            "limit": 1,
            "cursor": "sc_" + identity.removeprefix("sha256:")[:16] + "_1",
        },
    )
    assert stale["condition"]["code"] == "search_cursor_stale"
    assert _search_receipt(workspace, handle) == receipt


def test_pdf_bookmark_navigation_preserves_metadata_and_reading_boundaries(tmp_path: Path) -> None:
    from rob2_kit.application.evidence import source_reading_status

    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    for page in range(15):
        document.new_page().insert_text((48, 48), f"Body on physical page {page + 1}.")
    outline = [
        [1, "Cover metadata", 1],
        [2, "Long authored label " + "x" * 600, 2],
        [1, "Unmapped destination", -1],
    ]
    outline.extend([1, f"Section {page}", page] for page in range(3, 16))
    document.set_toc(outline)
    (workspace / "input" / "trial" / "protocol.pdf").write_bytes(document.tobytes())
    document.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source = next(
        s
        for s in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if s["label"] == "protocol.pdf"
    )
    before = source_reading_status(workspace, "trial")
    action = source["navigation_action"]
    data = _call(
        workspace, action["operation"], {k: v for k, v in action.items() if k != "operation"}
    )["data"]["navigation"]
    assert data["source_sha256"] == source["sha256"]
    assert data["pdf_bookmark_count"] == 15
    assert data["unmapped_pdf_bookmark_count"] == 1
    assert data["returned_entries"] == 12
    assert source_reading_status(workspace, "trial") == before
    import base64

    encoded = data["next_cursor"].split(".", 1)[1]
    old_cursor = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    old_cursor["version"] = "rob2-kit.source-navigation.v0.4"
    old_cursor = "sn1." + base64.urlsafe_b64encode(json.dumps(old_cursor).encode()).decode().rstrip(
        "="
    )
    stale = _call(
        workspace,
        "list_sources",
        {"trial_id": "trial", "source_id": source["id"], "cursor": old_cursor},
    )
    assert stale["condition"]["code"] == "source_navigation_cursor_stale"
    entries = list(data["entries"])
    assert entries[0]["text"] == "Cover metadata"
    assert entries[1]["outline_level"] == 2 and entries[1]["label_truncated"] is True
    assert (
        entries[1]["label_sha256"]
        == "sha256:"
        + hashlib.sha256(("Long authored label " + "x" * 600).encode("utf-8")).hexdigest()
    )
    cursor = data["next_cursor"]
    while cursor:
        data = _call(
            workspace,
            "list_sources",
            {"trial_id": "trial", "source_id": source["id"], "cursor": cursor},
        )["data"]["navigation"]
        entries.extend(data["entries"])
        cursor = data["next_cursor"]
    bookmarks = [entry for entry in entries if entry["kind"] == "pdf_bookmark"]
    assert [entry["outline_index"] for entry in bookmarks] == [0, 1, *range(3, 16)]
    assert all("start_line" not in entry and "end_line" not in entry for entry in bookmarks)
    assert all(len(entry["text"]) <= 512 for entry in entries)
    assert source_reading_status(workspace, "trial") == before
    read_action = bookmarks[1]["read_action"]
    read = _call(
        workspace,
        read_action["operation"],
        {k: v for k, v in read_action.items() if k != "operation"},
    )["data"]
    assert "Body on physical page 2" in read["pages"][0]["numbered_text"]
    assert read["navigation_actions"][0]["source_id"] == source["id"]
    assert source_reading_status(workspace, "trial") != before
    assert _state(workspace)["revision"] == 1

    internal_source = next(
        s["id"]
        for s in _state(workspace)["batch"]["trials"][0]["sources"]
        if s["label"] == "protocol.pdf"
    )
    captured = workspace / ".rob2-kit" / "sources" / "trial" / f"{internal_source}.bin"
    captured.write_bytes(captured.read_bytes() + b"changed bytes")
    with pytest.raises(ToolError, match="internal_evidence_integrity_error"):
        _call(workspace, "list_sources", {"trial_id": "trial", "source_id": source["id"]})
