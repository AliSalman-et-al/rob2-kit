from __future__ import annotations

from pathlib import Path

import pymupdf
from support.rob2 import (
    _call,
    _domain_draft,
    _proposal_args,
    _result,
    _review,
    _workspace,
)


def _source(workspace: Path, label: str) -> dict:
    return next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == label
    )


def _prepare_with_evidence(workspace: Path, *, read_main: bool) -> tuple[dict, dict]:
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    main = _source(workspace, "main.txt")
    if read_main:
        _call(
            workspace,
            "read_pages",
            {"trial_id": "trial", "source_id": main["id"], "pages": [1]},
        )
    evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": main["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    return main, evidence


def _read_window_to_end(
    workspace: Path,
    source: dict,
    *,
    page: int = 1,
    start_line: int = 1,
    end_line: int | None = None,
) -> None:
    while True:
        window = {
            "source_id": source["id"],
            "page": page,
            "start_line": start_line,
        }
        if end_line is not None:
            window["end_line"] = end_line
        page_data = _call(
            workspace,
            "read_pages",
            {
                "trial_id": "trial",
                "windows": [window],
            },
        )["data"]["pages"][0]
        next_start = page_data["next_start_line"]
        if next_start is None:
            if end_line is not None:
                assert page_data["returned_end_line"] == end_line
            return
        assert next_start == page_data["returned_end_line"] + 1
        if end_line is not None:
            assert next_start <= end_line
        start_line = next_start


def _write_large_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page(width=100_000, height=100_000)
            page.insert_text((36, 60), text, fontsize=1)
        path.write_bytes(document.tobytes())
    finally:
        document.close()


def test_first_proposal_save_requires_bounded_main_report_read(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _main, evidence = _prepare_with_evidence(workspace, read_main=False)

    blocked = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert blocked["outcome"] == "repair", blocked
    assert any(repair["code"] == "main_report_reading_required" for repair in blocked["repairs"])
    _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": _main["id"], "pages": [1]},
    )
    accepted = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert accepted["outcome"] == "review_required", accepted


def test_status_bounds_selected_narrative_text_with_exact_recovery(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        ("selected evidence " * 1_000).strip() + "\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _source(workspace, "main.txt")
    page = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )["data"]["pages"][0]
    _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": page["line_count"],
        },
    )

    selected = _call(workspace, "get_status", {})["data"]["selected_evidence"]
    assert len(selected) == 1
    item = selected[0]
    assert item["text_status"] == "omitted"
    assert item["quote"] is None
    assert item["recovery"] == {
        "operation": "read_pages",
        "trial_id": "trial",
        "windows": [
            {
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": page["line_count"],
            }
        ],
    }


def test_main_report_pass_includes_appended_pages_below_cap(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").unlink()
    _write_large_pdf(trial / "article.pdf", ["main article\n", "appended material\n"])
    (trial / "sources.toml").write_text(
        'roles = { "article.pdf" = "main_article" }\n',
        encoding="utf-8",
    )

    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    article = _source(workspace, "article.pdf")
    initial = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert {window["page"] for window in initial["required_ranges"]} == {1, 2}
    assert initial["unread_ranges"] == []

    for window in initial["required_ranges"]:
        _read_window_to_end(
            workspace,
            article,
            page=window["page"],
            start_line=window["start_line"],
            end_line=window["end_line"],
        )
    complete = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert complete["status"] == "complete"


def test_first_domain_save_requires_fresh_post_approval_read_and_context_recovers(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _main, evidence = _prepare_with_evidence(workspace, read_main=True)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)

    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    blocked = _call(workspace, "save_domain_judgment", draft)
    assert blocked["outcome"] == "repair", blocked
    assert any(
        repair["code"] == "post_approval_main_report_reading_required"
        for repair in blocked["repairs"]
    )

    context = _call(workspace, "get_domain_context", {})
    assert context["outcome"] == "success", context
    recovery = context["data"]["reading_recovery"]
    assert recovery["operation"] == "read_pages"
    assert recovery["trial_id"] == "trial"
    assert recovery["windows"]

    reread = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "windows": recovery["windows"]},
    )
    assert reread["outcome"] == "success", reread
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved


def test_main_report_budget_is_utf8_whole_line_and_per_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    protocol_text = (trial / "main.txt").read_text(encoding="utf-8")
    (trial / "main.txt").unlink()
    (trial / "protocol.txt").write_text(protocol_text, encoding="utf-8")
    (trial / "main-a.txt").write_text(("é" * 19_999) + "\n", encoding="utf-8")
    (trial / "main-b.txt").write_text(("ß" * 19_999) + "\n", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'roles = { "main-a.txt" = "main_article", "main-b.txt" = "main_article", '
        '"protocol.txt" = "protocol" }\n',
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    protocol = _source(workspace, "protocol.txt")
    _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": protocol["id"], "pages": [1]},
    )
    evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": protocol["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]

    blocked = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert blocked["outcome"] == "repair", blocked
    assert any(repair["code"] == "main_report_reading_required" for repair in blocked["repairs"])
    main_sources = [_source(workspace, "main-a.txt"), _source(workspace, "main-b.txt")]
    windows = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"][
        "required_ranges"
    ]
    assert {window["source_id"] for window in windows} == {source["id"] for source in main_sources}
    for source in main_sources:
        _read_window_to_end(workspace, source)
    status = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert status["status"] == "complete"
    assert status["budget_bytes"] == 65_536


def test_oversized_utf8_prefix_and_empty_page_need_explicit_reads_and_continue_cleanly(
    tmp_path: Path,
) -> None:
    long_workspace = _workspace(tmp_path / "long")
    (long_workspace / "input" / "trial" / "main.txt").write_text(
        ("é" * 40_000) + "\n", encoding="utf-8"
    )
    _call(
        long_workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _source(long_workspace, "main.txt")
    before = _call(long_workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert before["status"] == "required"
    assert before["unread_ranges"]
    prefix_end = before["unread_ranges"][0]["start_line"] - 1
    assert prefix_end > 1
    _read_window_to_end(long_workspace, source, end_line=prefix_end)
    after = _call(long_workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert after["status"] == "budget_limited"
    assert after["unread_ranges"]
    assert after["unread_ranges"][0]["start_line"] == prefix_end + 1
    assert 0 < after["covered_prefix_bytes"] <= after["budget_bytes"]
    for unread in after["unread_ranges"]:
        _read_window_to_end(
            long_workspace,
            source,
            page=unread["page"],
            start_line=unread["start_line"],
            end_line=unread["end_line"],
        )
    complete = _call(long_workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert complete["status"] == "complete"
    assert complete["unread_ranges"] == []

    empty_workspace = _workspace(tmp_path / "empty")
    (empty_workspace / "input" / "trial" / "main.txt").write_text("", encoding="utf-8")
    _call(
        empty_workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    empty_before = _call(empty_workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert empty_before["status"] == "required"
    empty_source = _source(empty_workspace, "main.txt")
    read = _call(
        empty_workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": empty_source["id"], "pages": [1]},
    )
    assert read["data"]["pages"][0]["line_count"] == 0
    empty_after = _call(empty_workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert empty_after["status"] == "complete"


def test_budget_deferred_ranges_cover_later_pages_and_overlap_replays(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").unlink()
    _write_large_pdf(
        trial / "article.pdf",
        [
            ("é" * 40_000) + "\n",
            "tail page two\n",
            "tail page three\n",
        ],
    )
    (trial / "sources.toml").write_text(
        'roles = { "article.pdf" = "main_article" }\n',
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    article = _source(workspace, "article.pdf")
    initial = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    required = initial["required_ranges"]
    assert required
    assert {window["page"] for window in required} == {1}
    for window in required:
        _read_window_to_end(
            workspace,
            article,
            page=window["page"],
            start_line=window["start_line"],
            end_line=window["end_line"],
        )

    limited = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert limited["status"] == "budget_limited"
    deferred = limited["unread_ranges"]
    page_one_tail = next(window for window in deferred if window["page"] == 1)
    assert page_one_tail["start_line"] == max(window["end_line"] for window in required) + 1
    assert {(window["page"], window["start_line"], window["end_line"]) for window in deferred} >= {
        (2, 1, 1),
        (3, 1, 1),
    }

    for window in reversed(deferred):
        start = window["start_line"]
        end = window["end_line"]
        midpoint = end if end == start else end - 1
        _read_window_to_end(
            workspace,
            article,
            page=window["page"],
            start_line=start,
            end_line=midpoint,
        )
        if midpoint < end:
            _read_window_to_end(
                workspace,
                article,
                page=window["page"],
                start_line=midpoint,
                end_line=end,
            )

    complete = _call(workspace, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert complete["status"] == "complete"
    assert complete["unread_ranges"] == []
