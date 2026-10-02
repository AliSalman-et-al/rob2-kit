"""Actual delivered text, not prior Domain existence, establishes bounded report coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _flow_navigation, get_domain_context
from rob2_kit.application.evidence import primary_report_context


def _clear_reads(workspace: Path) -> None:
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as c:
        c.execute("DELETE FROM page_reads")


def _approved(workspace: Path) -> Path:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)
    return workspace


def test_manageable_main_report_is_inline_before_questions_and_only_delivered_pages_count(
    tmp_path: Path,
) -> None:
    w = _workspace(tmp_path)
    original = (w / "input/trial/main.txt").read_text()
    text = original + "Primary endpoint follow-up continued after treatment stopped.\n" * 350
    (w / "input/trial/main.txt").write_text(text)
    _approved(w)
    # Building a snapshot does not record delivery of its projected source text.
    projected = get_domain_context(w, "trial", "domain:missing")
    assert projected["primary_report"]
    before = _call(w, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert before["covered_prefix_bytes"] == 0
    first = _call(
        w, "get_domain_context", {"domain_id": "domain:missing", "max_response_bytes": 24000}
    )
    assert first["outcome"] == "success", first
    assert first["data"]["questions"] == []
    assert first["data"]["primary_report"] == []
    assert (
        _call(w, "get_status", {})["data"]["main_report_reading"]["trial"]["covered_prefix_bytes"]
        == 0
    )
    pages = [first]
    while pages[-1]["data"]["context_page"]["next_cursor"]:
        pages.append(
            _call(
                w,
                "get_domain_context",
                {
                    "cursor": pages[-1]["data"]["context_page"]["next_cursor"],
                    "max_response_bytes": 24000,
                },
            )
        )
    chunks = [c for p in pages for c in p["data"].get("primary_report", [])]
    received = "\n".join(
        line.split("|", 1)[1] for c in chunks for line in c["numbered_text"].splitlines()
    )
    assert received == text.rstrip("\n")
    sections = [p["data"]["context_page"]["section"] for p in pages]
    assert sections.index("primary_report") < sections.index("questions")
    reading = _call(w, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert reading["status"] == "complete"
    assert primary_report_context(w, "trial") == []


def test_prior_domain_does_not_hide_unread_main_report(tmp_path: Path) -> None:
    w, evidence, revision = _assessment_workspace(tmp_path)
    saved = _call(
        w,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success", saved
    _clear_reads(w)
    revision = _state(w)["revision"]
    draft = _domain_draft("trial", "domain:deviations", revision, evidence)
    blocked = _call(w, "save_domain_judgment", draft)
    assert blocked["outcome"] == "repair", blocked
    assert blocked["repairs"][0]["code"] == "post_approval_main_report_reading_required"
    _call(w, "get_domain_context", {"domain_id": "domain:deviations"})
    accepted = _call(w, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted


def test_long_main_report_stays_bounded_and_exposes_unread_tail(tmp_path: Path) -> None:
    w = _workspace(tmp_path)
    main = w / "input/trial/main.txt"
    main.write_text(main.read_text() + "Long report methods and endpoint ascertainment.\n" * 2500)
    _approved(w)
    context = _call(w, "get_domain_context", {"domain_id": "domain:missing"})
    assert context["outcome"] == "success", context
    reading = _call(w, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert reading["status"] == "budget_limited"
    assert 0 < reading["covered_prefix_bytes"] <= 65536
    assert reading["unread_ranges"]
    fresh = get_domain_context(w, "trial", "domain:missing")
    assert fresh["primary_report"] == []
    assert fresh["reading_recovery"]["status"] == "budget_limited"


def test_flow_caption_navigation_is_not_count_evidence_and_stops_repeating_read_windows(
    tmp_path: Path,
) -> None:
    w = _workspace(tmp_path)
    appendix = w / "input/trial/appendix.txt"
    appendix.write_text(
        "Figure 2. Participant flow.\nThe diagram has no reported follow-up counts.\n"
    )
    (w / "input/trial/sources.toml").write_text(
        'roles = { "main.txt" = "main_article", "appendix.txt" = "supplement" }\n'
    )
    _approved(w)
    sources = _state(w)["batch"]["trials"][0]["sources"]
    nav = _flow_navigation(w, "trial", sources)
    source = next(s for s in sources if s["logical_path"] == "appendix.txt")
    assert nav[source["id"]] == [
        {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 2}
    ]
    context = _call(w, "get_domain_context", {"domain_id": "domain:missing"})
    coverage = next(c for c in context["data"]["coverage"] if c["source_role"] == "supplement")
    assert coverage["read"] == "unread"
    assert coverage["search"] == "unsearched"
    assert coverage["recovery"]
    assert not any(e["source_id"] == coverage["source_id"] for e in context["data"]["evidence"])
    # Unopened navigation is advisory: a scoped unknown can still be submitted.
    draft = _domain_draft("trial", "domain:missing", context["head"]["state_revision"])
    for answer in draft["answers"]:
        answer["bases"].insert(
            0,
            {
                "kind": "context",
                "evidence": context["data"]["evidence"][0]["handle"],
            },
        )
        answer["justification"] = (
            "The inspected main report does not establish complete endpoint follow-up or a "
            "performed missing-data robustness analysis. The unopened flow window is navigation, "
            "not count evidence. This scoped stopping rationale preserves the uncertainty."
        )
        answer["unknowns"] = ["Participant-flow navigation is not inspected count evidence."]
    saved = _call(w, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    _call(
        w,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [{**nav[source["id"]][0], "source_id": coverage["source_id"]}],
        },
    )
    assert source["id"] not in _flow_navigation(w, "trial", sources)
