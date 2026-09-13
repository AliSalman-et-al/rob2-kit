"""MCP evidence selection, rendering, and normalization behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from support.rob2 import *  # noqa: F401,F403

import rob2_kit.interfaces.mcp.server as mcp_server
from rob2_kit.application import finalization
from rob2_kit.application._state import _identity, _normalized_text_with_spans, _state
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import (
    _associated_search_ranks,
    _cached_normalized_search_text,
    _evidence_catalog,
    _normalized_contains,
    _normalized_match,
    _preview_window_bounds,
    _result_value_contains,
    _search_receipt,
)
from rob2_kit.application.source_handles import resolve_source_handle
from rob2_kit.packs import SCIENTIFIC_PACK


def test_broad_truncated_any_search_exposes_observable_refinement_only(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").unlink()
    document = pymupdf.open()
    for text in ("alpha beta one", "alpha beta two", "alpha beta three"):
        document.new_page().insert_text((72, 72), text)
    (workspace / "input" / "trial" / "main.pdf").write_bytes(document.tobytes())
    document.close()
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    broad = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 1},
    )["data"]
    diagnostic = broad["diagnostic"]
    assert diagnostic["code"] == "broad_any_truncated"
    assert diagnostic["normalized_term_count"] == 2
    assert diagnostic["next_action"] == {
        "kind": "refine",
        "operation": "search_sources",
        "trial_id": "trial",
        "query": "alpha beta",
        "mode": "all",
        "source_id": None,
        "limit": 1,
        "cursor": None,
    }

    narrow = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "all", "limit": 10},
    )["data"]
    assert narrow["diagnostic"] is None

    single_term = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha", "mode": "any", "limit": 1},
    )["data"]
    assert single_term["diagnostic"]["next_action"] == {
        "kind": "continue",
        "operation": "search_sources",
        "trial_id": "trial",
        "query": "alpha",
        "mode": "any",
        "source_id": None,
        "limit": 1,
        "cursor": single_term["next_cursor"],
    }

    no_hit = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "absent", "mode": "any", "limit": 1},
    )["data"]
    assert no_hit["diagnostic"] is None


@pytest.mark.parametrize("mode", ["all", "phrase"])
def test_initial_multi_token_narrow_no_hit_offers_same_scoped_any_search(
    tmp_path: Path, mode: str
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "the source contains unrelated wording only\n", encoding="utf-8"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    source_id = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]["id"]

    no_hit = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "alpha beta",
            "mode": mode,
            "source_id": source_id,
            "limit": 3,
        },
    )["data"]
    assert no_hit["condition"] == "no_hits"
    assert no_hit["diagnostic"]["code"] == "narrow_no_hits"
    assert no_hit["diagnostic"]["next_action"] == {
        "kind": "refine",
        "operation": "search_sources",
        "trial_id": "trial",
        "query": "alpha beta",
        "mode": "any",
        "source_id": source_id,
        "limit": 3,
        "cursor": None,
    }
    assert "matched nothing" in no_hit["diagnostic"]["detail"]
    assert "scientific completeness" in no_hit["diagnostic"]["detail"]

    action = no_hit["diagnostic"]["next_action"]
    widened = _call(
        workspace,
        "search_sources",
        {key: value for key, value in action.items() if key not in {"kind", "operation"}},
    )["data"]
    assert widened["mode"] == "any"
    assert _search_receipt(workspace, widened["search_receipt"])["sources"][0]["id"] == (
        resolve_source_handle(workspace, "trial", source_id)
    )


def test_narrow_no_hit_diagnostic_excludes_ineligible_searches(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "alpha beta\nalpha beta\n", encoding="utf-8"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    for mode in ("any", "prefix"):
        result = _call(
            workspace,
            "search_sources",
            {"trial_id": "trial", "query": "missing terms", "mode": mode},
        )["data"]
        assert result["diagnostic"] is None
    for mode in ("all", "phrase"):
        result = _call(
            workspace,
            "search_sources",
            {"trial_id": "trial", "query": "missing", "mode": mode},
        )["data"]
        assert result["condition"] == "no_hits"
        assert result["diagnostic"] is None
    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "all", "limit": 1},
    )["data"]
    assert result["diagnostic"] is None


def test_search_session_cursor_reuses_stable_ranking_after_derivative_restart(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "alpha beta one\nunrelated\nalpha beta two\nunrelated\nalpha beta three\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )

    first = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 1},
    )["data"]
    assert first["next_cursor"]
    first_session = first["session_id"]
    second = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "alpha beta",
            "mode": "any",
            "limit": 2,
            "cursor": first["next_cursor"],
        },
    )["data"]
    assert second["session_id"] == first_session
    assert [hit["rank"] for hit in first["hits"]] == [1]
    assert [hit["rank"] for hit in second["hits"]] == [2, 3]
    assert second["returned_rank_start"] == 2
    assert second["returned_rank_end"] == 3
    assert second["exhausted"] is True

    (workspace / ".rob2-kit" / "derivative.sqlite3").unlink()
    restarted = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "alpha beta",
            "mode": "any",
            "limit": 2,
            "cursor": first["next_cursor"],
        },
    )["data"]
    assert restarted["session_id"] == first_session
    assert [hit["rank"] for hit in restarted["hits"]] == [2, 3]


def test_search_returns_multiple_source_windows_for_one_matching_page(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "alpha\ncontext\ncontext\nbeta\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 10},
    )["data"]
    assert len(result["hits"]) == 2
    assert [hit["rank"] for hit in result["hits"]] == [1, 2]
    assert [hit["start_line"] for hit in result["hits"]] == [1, 1]
    assert [hit["end_line"] for hit in result["hits"]] == [4, 4]
    receipt = _search_receipt(workspace, result["search_receipt"])
    assert receipt["hits"] == [
        {
            "source_id": resolve_source_handle(workspace, "trial", result["hits"][0]["source_id"]),
            "page": 1,
        },
        {
            "source_id": resolve_source_handle(workspace, "trial", result["hits"][1]["source_id"]),
            "page": 1,
        },
    ]


def test_all_mode_keeps_two_separated_complete_clusters_on_one_page(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "alpha beta first\nnoise\nnoise\nalpha beta second\n",
        encoding="utf-8",
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "all", "limit": 10},
    )["data"]

    assert [hit["rank"] for hit in result["hits"]] == [1, 2]
    assert [hit["start_line"] for hit in result["hits"]] == [1, 1]
    assert [hit["end_line"] for hit in result["hits"]] == [4, 4]


def test_search_preview_and_passage_ref_share_one_bounded_window(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    lines = ["target early", *(["unrelated context"] * 200), "target late"]
    (workspace / "input" / "trial" / "main.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "target", "mode": "any", "limit": 10},
    )["data"]
    assert len(result["hits"]) == 2
    catalog = _evidence_catalog(workspace, "trial")
    evidence_by_handle = {item["handle"]: item for item in catalog.values()}
    for hit in result["hits"]:
        evidence = evidence_by_handle[hit["passage_ref"]]
        assert hit["preview"] == evidence["quote"]
        assert hit["start_line"] == evidence["start_line"]
        assert hit["end_line"] == evidence["end_line"]
        assert hit["candidate_truncated"] is False
        assert hit["candidate_recovery"] is None
        assert len(hit["preview"].encode("utf-8")) <= 512
    assert "target early" in result["hits"][0]["preview"]
    assert "target late" not in result["hits"][0]["preview"]
    assert "target late" in result["hits"][1]["preview"]
    assert "target early" not in result["hits"][1]["preview"]


def test_explicit_preview_anchor_does_not_reselect_an_earlier_occurrence() -> None:
    text = "target early\n" + "unrelated context\n" * 200 + "target late\n"
    late_start = text.rindex("target late")
    left, right = _preview_window_bounds(
        text, [(late_start, late_start + len("target late"))], radius=20
    )
    preview = text[left:right]
    assert "target late" in preview
    assert "target early" not in preview


def test_long_candidate_clusters_remain_complete_under_hard_cap(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    for index in range(9):
        (workspace / "input" / "trial" / f"cluster-{index}.txt").write_text(
            f"target {'x ' * 350}needle\n", encoding="utf-8"
        )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "target needle", "mode": "all", "limit": 10},
    )["data"]

    assert len(result["hits"]) == 9
    for hit in result["hits"]:
        assert hit["candidate_truncated"] is False
        assert hit["candidate_recovery"] is None
        assert hit["preview"].startswith("target ")
        assert hit["preview"].rstrip().endswith("needle")
        assert len(hit["preview"].encode("utf-8")) <= 2_048


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


def test_search_premise_windows_retain_huhn_and_blalock_qualifiers(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    text = (
        "\n".join(
            [
                "Huhn analysis plan",
                "The primary statistical analysis followed the intention-to-treat principle.",
                "The analysis used all randomized participants (ITT).",
                "Secondary outcomes were exploratory.",
                "Blalock analysis",
                "The CES-D was the depression measure.",
                "A mixed models regression approach was the primary analytic strategy.",
            ]
        )
        + "\n"
    )
    (workspace / "input" / "trial" / "main.txt").write_text(text, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    huhn = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "analysis plan", "mode": "any", "limit": 10},
    )["data"]["hits"]
    blalock = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "CES-D", "mode": "phrase", "limit": 10},
    )["data"]["hits"]

    huhn_preview = next(hit["preview"] for hit in huhn if "primary statistical" in hit["preview"])
    blalock_preview = next(hit["preview"] for hit in blalock if "CES-D" in hit["preview"])
    assert "randomized participants" in huhn_preview
    assert "Secondary outcomes" in huhn_preview
    assert "mixed models" in blalock_preview


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


def test_search_pagination_is_page_size_independent_and_source_diverse(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("needle one\nneedle two\nneedle three\n", encoding="utf-8")
    (trial / "protocol.txt").write_text("needle protocol\n", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'roles = { "main.txt" = "main_article", "protocol.txt" = "protocol" }\n',
        encoding="utf-8",
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})

    def traverse(limit: int) -> tuple[list[tuple[int, str]], dict[str, object]]:
        cursor = None
        rows: list[tuple[int, str]] = []
        last: dict[str, object] = {}
        while True:
            args = {"trial_id": "trial", "query": "needle", "mode": "any", "limit": limit}
            if cursor:
                args["cursor"] = cursor
            last = _call(workspace, "search_sources", args)["data"]
            rows.extend((hit["rank"], hit["passage_ref"]) for hit in last["hits"])
            cursor = last["next_cursor"]
            if not cursor:
                return rows, last

    one, last_one = traverse(1)
    five, last_five = traverse(5)
    ten, last_ten = traverse(10)
    assert one == five == ten
    assert [rank for rank, _ref in one] == [1, 2]
    assert last_one["truncated"] is False and last_one["exhausted"] is True
    assert last_five["truncated"] is False and last_ten["truncated"] is False
    first_two = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "needle", "mode": "any", "limit": 2},
    )["data"]["hits"]
    assert len({hit["source_id"] for hit in first_two}) == 2
    assert [hit["rank"] for hit in first_two] == [1, 2]


def test_all_mode_matches_widely_separated_terms_without_changing_exact_quote(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    text = "alpha " + "x " * 30 + "beta\n"
    (workspace / "input" / "trial" / "main.txt").write_text(text, encoding="utf-8")
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    result = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "alpha beta", "mode": "all"}
    )["data"]
    assert result["hits"]
    evidence = _search_receipt(workspace, result["search_receipt"])
    assert evidence["candidate_count"] >= 1


def test_search_cursor_conditions_are_typed_and_source_scope_is_bound(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("needle one\nneedle two\n", encoding="utf-8")
    (trial / "protocol.txt").write_text(
        "needle protocol\n" + "context\n" * 12 + "needle protocol again\n",
        encoding="utf-8",
    )
    _call(workspace, "prepare_batch", {"requested_outcome": "outcome", "expected_revision": 0})
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
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
            "source_id": sources[0]["id"],
            "limit": 1,
        },
    )["data"]
    mismatch = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": "needle",
            "mode": "any",
            "source_id": sources[-1]["id"],
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


def test_search_candidate_identity_is_invariant_across_active_domains(tmp_path: Path) -> None:
    from support.rob2 import _assessment_workspace, _domain_draft

    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )
    assert first["outcome"] == "success"
    randomization = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any"},
    )["data"]
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success"
    second = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:deviations"},
    )
    assert second["outcome"] == "success"
    missing = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any"},
    )["data"]
    assert randomization["session_id"] == missing["session_id"]
    assert [hit["passage_ref"] for hit in randomization["hits"]] == [
        hit["passage_ref"] for hit in missing["hits"]
    ]
    rank = randomization["hits"][0]["rank"]
    assert (randomization["session_id"], rank) in _associated_search_ranks(
        workspace, "trial", "domain:randomization"
    )
    assert (randomization["session_id"], rank) in _associated_search_ranks(
        workspace, "trial", "domain:deviations"
    )


def test_missing_question_card_exposes_explicit_availability_premise(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain_id in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:missing"},
    )
    assert context["outcome"] == "success"
    card = next(
        item for item in context["data"]["questions"] if item["id"] == "sq:missing:data-available"
    )
    pack_question = next(
        item for item in SCIENTIFIC_PACK.questions if item.id == "sq:missing:data-available"
    )
    assert card["official_guidance"] == pack_question.guidance.official.source_excerpt
    assert card["source_locator"] == pack_question.guidance.official.source_locator

    evidence = " ".join(card["evidence_needed"]).casefold()
    assert "yes or probably yes" in evidence
    assert "actual outcome-availability evidence" in evidence
    assert "observed-outcome counts" in evidence
    assert "loss-to-follow-up or censoring accounting" in evidence
    assert "complete/nearly-complete ascertainment" in evidence

    shortcuts = [item.casefold() for item in card["invalid_shortcuts"]]
    assert any("analysis denominator" in item and "itt membership" in item for item in shortcuts)
    assert any("planned or scheduled follow-up" in item for item in shortcuts)
    assert any("treatment continuation" in item and "discontinuation" in item for item in shortcuts)
    assert any(
        "generic censoring rule" in item
        and "actual rates" in item
        and "follow-up accounting" in item
        for item in shortcuts
    )
    considerations = " ".join(card["considerations"]).casefold()
    assert "administrative censoring" in considerations
    assert "missing follow-up" in considerations


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
            ('"alpha" AND "beta"', resolve_source_handle(workspace, "trial", article["id"])),
        ).fetchall()
    assert article_ranks[0][0] != 1

    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 4},
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
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 2},
    )
    pairs = [(hit["source_id"], hit["page"]) for hit in result["data"]["hits"]]

    assert result["data"]["total_matches"] == 4
    assert result["data"]["truncated"] is True
    assert pairs[0][0] == article_source["id"]
    assert pairs[1] == (protocol_source["id"], 1)
    expected_hits = [
        {
            "source_id": resolve_source_handle(workspace, "trial", source_id),
            "page": page,
        }
        for source_id, page in pairs
    ]
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
        {"trial_id": "trial", "query": "alpha beta", "mode": "any", "limit": 1},
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
        {"trial_id": "trial", "query": "alpha beta", "mode": "any"},
    )
    assert result["outcome"] == "success"
    pairs = [(hit["source_id"], hit["page"]) for hit in result["data"]["hits"]]
    assert set(pairs) == {(article_source["id"], 1), (article_source["id"], 2)}
    assert result["data"]["total_matches"] == 2

    receipt = _search_receipt(workspace, result["data"]["search_receipt"])
    assert receipt["hits"] == [
        {
            "source_id": resolve_source_handle(workspace, "trial", source_id),
            "page": page,
        }
        for source_id, page in pairs
    ]


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
        "page_remainder",
        "truncated",
        "next_start_line",
        "passage_ref",
    }
    assert page["returned_start_line"] == 1
    assert page["returned_end_line"] == 4
    assert page["page_remainder"] is None
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


def test_read_pages_passage_uses_trimmed_line_bounds(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "first line\nsecond line\n\nfourth line\n",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    result = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": source["id"],
                    "page": 1,
                    "start_line": 1,
                    "end_line": 3,
                }
            ],
        },
    )
    page = result["data"]["pages"][0]

    assert page["returned_end_line"] == 3
    assert page["page_remainder"] == {
        "source_id": source["id"],
        "page": 1,
        "start_line": 4,
        "end_line": 4,
    }
    assert page["truncated"] is False
    assert page["next_start_line"] is None
    assert result["data"]["remaining_windows"] == []
    passage = next(
        item
        for item in _evidence_catalog(workspace).values()
        if item["handle"] == page["passage_ref"]
    )
    assert passage["quote"] == "first line\nsecond line"
    assert passage["start_line"] == 1
    assert passage["end_line"] == 2


def test_read_pages_blank_fragment_has_no_passage_or_empty_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "first line\n\nlast line\n", encoding="utf-8"
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    before = set(_evidence_catalog(workspace))

    page = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {
                    "source_id": source["id"],
                    "page": 1,
                    "start_line": 2,
                    "end_line": 2,
                }
            ],
        },
    )["data"]["pages"][0]

    assert page["numbered_text"] == "2|"
    assert page["passage_ref"] is None
    assert set(_evidence_catalog(workspace)) == before


def test_read_pages_two_pages_commits_coverage_after_valid_response(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.unlink()
    document = pymupdf.open()
    for text in ("first page", "second page"):
        document.new_page().insert_text((72, 72), text)
    (main.with_suffix(".pdf")).write_bytes(document.tobytes())
    document.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]

    result = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1},
                {"source_id": source["id"], "page": 2, "start_line": 1, "end_line": 1},
            ],
        },
    )

    assert result["outcome"] == "success"
    assert [page["numbered_text"] for page in result["data"]["pages"]] == [
        "1|first page",
        "1|second page",
    ]
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT page,start_line,end_line FROM page_reads WHERE source_id=? ORDER BY page",
            (resolve_source_handle(workspace, "trial", source["id"]),),
        ).fetchall()
    assert rows == [(1, 1, 1), (2, 1, 1)]


def test_read_pages_late_failure_does_not_commit_prior_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    main = workspace / "input" / "trial" / "main.txt"
    main.unlink()
    document = pymupdf.open()
    for text in ("first page", "second page"):
        document.new_page().insert_text((72, 72), text)
    (main.with_suffix(".pdf")).write_bytes(document.tobytes())
    document.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    original = mcp_server._select_text_evidence_by_lines
    calls = 0

    def fail_on_second(
        workspace: str | Path,
        trial_id: str,
        source_id: str,
        page: int,
        start_line: int,
        end_line: int,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic late read failure")
        return original(workspace, trial_id, source_id, page, start_line, end_line)

    monkeypatch.setattr(mcp_server, "_select_text_evidence_by_lines", fail_on_second)
    result = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1},
                {"source_id": source["id"], "page": 2, "start_line": 1, "end_line": 1},
            ],
        },
    )

    assert calls == 2
    assert result["outcome"] == "condition"
    assert result["condition"]["code"] == "invalid_request"
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert connection.execute("SELECT 1 FROM page_reads LIMIT 1").fetchone() is None


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
    assert page["page_remainder"] == {
        "source_id": source["id"],
        "page": 1,
        "start_line": page["returned_end_line"] + 1,
        "end_line": page["line_count"],
    }
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


def test_read_pages_packs_request_order_and_returns_remaining_windows(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "main.txt").write_text("short\n", encoding="utf-8")
    (trial / "supplement.txt").write_text(
        "\n".join("é" * 30 for _ in range(1_000)) + "\n",
        encoding="utf-8",
    )
    (trial / "protocol.txt").write_text("later requested text " * 10 + "\n", encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    main = next(source for source in sources if source["label"] == "main.txt")
    supplement = next(source for source in sources if source["label"] == "supplement.txt")
    protocol = next(source for source in sources if source["label"] == "protocol.txt")

    first = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "windows": [
                {"source_id": main["id"], "page": 1, "start_line": 1, "end_line": 1},
                {
                    "source_id": supplement["id"],
                    "page": 1,
                    "start_line": 1,
                    "end_line": 1_000,
                },
                {"source_id": protocol["id"], "page": 1, "start_line": 1, "end_line": 1},
            ],
        },
    )
    assert first["outcome"] == "success"
    pages = first["data"]["pages"]
    assert [page["source_id"] for page in pages] == [main["id"], supplement["id"]]
    supplement_page = pages[1]
    assert len(supplement_page["numbered_text"]) > 12_000
    assert sum(len(page["numbered_text"]) for page in pages) <= 24_000
    remaining = first["data"]["remaining_windows"]
    assert remaining == [
        {
            "source_id": supplement["id"],
            "page": 1,
            "start_line": supplement_page["returned_end_line"] + 1,
            "end_line": 1_000,
        },
        {"source_id": protocol["id"], "page": 1, "start_line": 1, "end_line": 1},
    ]
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM page_reads WHERE source_id=?", (protocol["id"],)
            ).fetchone()
            is None
        )

    seen = list(range(1, supplement_page["returned_end_line"] + 1))
    while remaining:
        continuation = _call(
            workspace,
            "read_pages",
            {"trial_id": "trial", "windows": remaining},
        )
        assert continuation["outcome"] == "success"
        for page in continuation["data"]["pages"]:
            assert page["source_id"] in {supplement["id"], protocol["id"]}
            if page["source_id"] == supplement["id"]:
                seen.extend(range(page["returned_start_line"], page["returned_end_line"] + 1))
        remaining = continuation["data"]["remaining_windows"]
    assert seen == list(range(1, 1_001))


def test_read_pages_oversized_single_line_makes_progress(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text("x" * 30_000, encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    result = _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": source["id"], "pages": [1]},
    )
    page = result["data"]["pages"][0]
    assert page["returned_end_line"] >= 1
    assert page["passage_ref"] is not None


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
        ("Age 1-\n3 years", "13", "/reported/values/0/value", False),
        ("Age 1-\n3 years", "1-3", "/reported/values/0/value", True),
        ("Age 1-\n3 years", "1", "/reported/values/0/value", True),
        ("Age 1-\n3 years", "3", "/reported/values/0/value", True),
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
        ("estimate 5%", "5", "/reported/values/0/value", True),
        ("estimate 5%", "5", "/reported/estimate", False),
        ("estimate 5%", "5%", "/reported/estimate", True),
    )
    for material, phrase, path, expected in cases:
        assert _result_value_contains(material, phrase, path) is expected
        assert standalone_contains(material, phrase, path) is expected


def test_search_sources_finds_numeric_range_without_scalar_match(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text("Age 1-\n3 years\n", encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )

    numeric_range = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "1-3", "mode": "phrase"},
    )
    assert numeric_range["outcome"] == "success"
    assert numeric_range["data"]["total_matches"] == 1
    assert numeric_range["data"]["hits"][0]["page"] == 1

    scalar = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "13", "mode": "phrase"},
    )
    assert scalar["outcome"] == "success"
    assert scalar["data"]["total_matches"] == 0
    assert scalar["data"]["condition"] == "no_hits"


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
