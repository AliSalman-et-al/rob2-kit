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
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _flow_navigation, get_domain_context
from rob2_kit.application.evidence import source_reading_status


def _clear_reads(workspace: Path) -> None:
    with sqlite3.connect(workspace / ".rob2-kit/derivative.sqlite3") as c:
        c.execute("DELETE FROM page_reads")


def _approved(workspace: Path) -> Path:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)
    return workspace


def test_context_does_not_embed_or_claim_unread_primary_text(tmp_path: Path) -> None:
    w = _workspace(tmp_path)
    main = w / "input/trial/main.txt"
    main.write_text(
        main.read_text() + "Endpoint follow-up continued after treatment stopped.\n" * 350
    )
    _approved(w)
    projected = get_domain_context(w, "trial", "domain:missing")
    assert projected["primary_report"] == []
    assert projected["reading_recovery"]["windows"]
    first = _call(
        w, "get_domain_context", {"domain_id": "domain:missing", "max_response_bytes": 24000}
    )
    assert first["outcome"] == "success", first
    assert first["data"]["questions"]
    cursor = first["data"]["context_page"]["next_cursor"]
    # Reading between context pages must not freeze a second copy of the report.
    _read_required_main_reports(w)
    while cursor:
        page = _call(w, "get_domain_context", {"cursor": cursor, "max_response_bytes": 24000})
        assert page["outcome"] == "success", page
        assert not page["data"].get("primary_report")
        cursor = page["data"]["context_page"]["next_cursor"]
    status = _call(w, "get_status", {})["data"]["main_report_reading"]["trial"]
    assert status["status"] == "complete"
    for domain in ["domain:deviations", "domain:missing", "domain:selection"]:
        fresh = get_domain_context(w, "trial", domain)
        assert fresh["primary_report"] == []
        assert fresh["reading_recovery"] is None
        assert fresh["coverage"][0]["read"] == "read_complete"
    # A new client can reuse persisted receipts; loss of them restores recovery.
    assert set(source_reading_status(w, "trial").values()) == {"read_complete"}
    _clear_reads(w)
    fresh = get_domain_context(w, "trial", "domain:missing")
    assert fresh["reading_recovery"]["windows"]
    assert fresh["coverage"][0]["read"] != "read_complete"


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
    context = _call(w, "get_domain_context", {"domain_id": "domain:deviations"})
    assert context["head"]["next_action"]["operation"] == "read_pages"
    assert context["head"]["next_action"]["windows"]
    _read_required_main_reports(w)
    context = _call(w, "get_domain_context", {"domain_id": "domain:deviations"})
    assert context["head"]["next_action"]["operation"] == "save_domain_judgment"
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
    assert reading["status"] == "required"
    assert reading["covered_prefix_bytes"] == 0
    _read_required_main_reports(w)
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
    _read_required_main_reports(w)
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


def test_partial_delivery_preserves_omitted_passage_and_rejects_changed_source(
    tmp_path: Path,
) -> None:
    import pytest

    w = _workspace(tmp_path)
    main = w / "input/trial/main.txt"
    main.write_text(main.read_text() + "Some endpoint measurements were not obtained.\n")
    _approved(w)
    source = _state(w)["batch"]["trials"][0]["sources"][0]
    _call(
        w,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": _call(w, "list_sources", {"trial_id": "trial"})["data"]["sources"][
                        0
                    ]["id"],
                    "page": 1,
                    "start_line": 1,
                    "end_line": 1,
                }
            ],
        },
    )
    context = get_domain_context(w, "trial", "domain:missing")
    assert context["coverage"][0]["read"] == "partially_read"
    assert context["reading_recovery"]["windows"][0]["start_line"] == 2
    # Content existence or prior delivery cannot make changed bytes trustworthy.
    captured = w / ".rob2-kit/sources/trial" / (source["id"] + ".bin")
    captured.write_bytes(captured.read_bytes() + b"Changed source content.\n")
    with pytest.raises(ValueError, match="Source bytes do not match Canonical identity"):
        source_reading_status(w, "trial")


def test_changed_result_invalidates_scientific_basis_without_forgetting_source_delivery(
    tmp_path: Path,
) -> None:
    import copy

    from rob2_kit.application.domains import _domain_context_basis_identity

    w, _evidence, _revision = _assessment_workspace(tmp_path)
    state = _state(w)
    original_basis = _domain_context_basis_identity(state, "trial", "domain:missing", None)
    changed = copy.deepcopy(state)
    changed["proposal"]["payload"]["results"][0]["target"]["outcome_definition"] = (
        "Different endpoint needing source relevance reassessment"
    )
    assert (
        _domain_context_basis_identity(changed, "trial", "domain:missing", None) != original_basis
    )
    assert set(source_reading_status(w, "trial").values()) == {"read_complete"}


def test_complete_delivery_does_not_erase_selected_counterevidence() -> None:
    from rob2_kit.application.domains import _compact_domain_evidence

    handle = "eh_0123456789abcdef"
    counterpoint = {
        "kind": "narrative",
        "handle": handle,
        "identity": "sha256:" + "1" * 64,
        "trial_id": "trial",
        "source_id": "sh_" + "2" * 16,
        "page": 1,
        "start_line": 2,
        "end_line": 2,
        "quote": "Some endpoint measurements were not obtained after early withdrawal.",
        "inclusion_reason": "contradiction",
    }
    implication = {
        "evidence": [handle],
        "implication": (
            "All randomized participants analyzed does not establish complete observation."
        ),
    }
    projected = _compact_domain_evidence(
        {
            "answers": [
                {"question_id": "sq:missing:data-available", "counterevidence": [implication]}
            ],
            "coverage": [{"source_id": counterpoint["source_id"], "read": "read_complete"}],
            "evidence": [counterpoint],
        }
    )
    assert projected["answers"][0]["counterevidence"] == [implication]
    assert projected["evidence"][0]["handle"] == handle
    assert projected["evidence"][0]["quote"] == counterpoint["quote"]
    assert projected["evidence"][0]["start_line"] == 2
