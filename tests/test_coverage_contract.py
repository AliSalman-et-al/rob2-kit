from typing import cast

import pytest

from rob2_kit.application.domains import _source_coverage
from rob2_kit.evaluation.coverage import (
    CoverageRecord,
    CoverageStatus,
    PremiseCoverage,
    RecoveryAction,
    RecoveryWindow,
    bounded_recovery,
)


def test_status_validity_and_state_consistency() -> None:
    record = CoverageRecord("source-a", "searched_no_match", search="searched_no_match")
    assert record.status == "searched_no_match"
    with pytest.raises(ValueError):
        CoverageRecord("source-a", cast(CoverageStatus, "not-a-status"))
    with pytest.raises(ValueError):
        CoverageRecord("source-a", "read_complete", read="unread")  # type: ignore[arg-type]


def test_identity_is_deterministic() -> None:
    first = CoverageRecord("source-a", "read_complete", read="read_complete", refs=("p1",))
    second = CoverageRecord("source-a", "read_complete", read="read_complete", refs=("p1",))
    assert first.identity == second.identity
    assert first.identity.startswith("sha256:")


def test_recovery_is_bounded_and_actions_are_executable_records() -> None:
    actions = tuple(RecoveryAction("read", "source-a", index, index + 1) for index in range(3))
    window = RecoveryWindow("source-a", 0, 4, actions, max_actions=3)
    assert len(window.bounded(2).actions) == 2
    assert len(bounded_recovery(actions, 1)) == 1
    with pytest.raises(ValueError):
        RecoveryWindow("source-a", 0, 2, (RecoveryAction("read", "other", 0, 1),))


def test_no_hit_does_not_claim_scientific_absence() -> None:
    record = CoverageRecord("source-a", "searched_no_match", search="searched_no_match")
    assert record.absence_claim is False
    with pytest.raises(ValueError):
        CoverageRecord(
            "source-a", "searched_no_match", search="searched_no_match", read="read_complete"
        )


def test_incomplete_retrieval_is_distinct_from_an_exhausted_no_hit() -> None:
    record = CoverageRecord("source-a", "retrieval_incomplete", search="retrieval_incomplete")
    assert record.absence_claim is False


def test_required_premise_names_missing_coverage() -> None:
    premise = PremiseCoverage("endpoint", required=True, covered=False, missing=("timepoint",))
    assert premise.missing == ("timepoint",)
    with pytest.raises(ValueError):
        PremiseCoverage("endpoint", required=True, covered=False)


def test_selected_passage_is_partial_source_read_not_source_complete() -> None:
    coverage = _source_coverage(
        "trial-a",
        [{"id": "source-a", "role": "main_article", "page_count": 4}],
        {"evidence-a": {"source_id": "source-a", "inclusion_reason": "result"}},
        {},
    )

    assert coverage == [
        {
            "source_id": "source-a",
            "source_role": "main_article",
            "page_count": 4,
            "status": "partially_read",
            "search": "unsearched",
            "read": "partially_read",
            "render": "not_delivered",
            "recovery": [],
        }
    ]


def test_multi_source_search_does_not_transfer_matches_between_sources() -> None:
    coverage = _source_coverage(
        "trial-a",
        [
            {"id": "source-a", "role": "main_article", "page_count": 4},
            {"id": "source-b", "role": "supplement", "page_count": 2},
        ],
        {},
        {
            "receipt": {
                "trial_id": "trial-a",
                "sources": [{"id": "source-a"}, {"id": "source-b"}],
                "hits": [{"source_id": "source-a", "page": 1}],
                "total_matches": 1,
                "condition": None,
                "truncated": False,
                "next_cursor": None,
                "exhausted": True,
            }
        },
    )

    by_source = {item["source_id"]: item for item in coverage}
    assert by_source["source-a"]["status"] == "candidate_only"
    assert by_source["source-a"]["search"] == "searched_match"
    assert by_source["source-b"]["status"] == "searched_no_match"
    assert by_source["source-b"]["search"] == "searched_no_match"


def test_completed_search_pagination_clears_prior_incompleteness_but_gaps_do_not() -> None:
    base = {
        "trial_id": "trial-a",
        "sources": [{"id": "source-a"}, {"id": "source-b"}],
        "total_matches": 3,
        "candidate_count": 3,
    }
    complete = _source_coverage(
        "trial-a",
        [
            {"id": "source-a", "role": "main_article", "page_count": 4},
            {"id": "source-b", "role": "supplement", "page_count": 2},
        ],
        {},
        {
            "page-1": base
            | {
                "session_id": "session-1",
                "hits": [{"source_id": "source-a", "page": 1}],
                "returned_candidates": [{"rank": 1}, {"rank": 2}],
                "truncated": True,
                "next_cursor": "cursor-2",
                "exhausted": False,
            },
            "page-2": base
            | {
                "session_id": "session-1",
                "hits": [],
                "returned_candidates": [{"rank": 3}],
                "truncated": False,
                "next_cursor": None,
                "exhausted": True,
            },
        },
    )
    complete_by_source = {item["source_id"]: item for item in complete}
    assert complete_by_source["source-a"]["status"] == "candidate_only"
    assert complete_by_source["source-b"]["status"] == "searched_no_match"

    gapped = _source_coverage(
        "trial-a",
        [{"id": "source-a", "role": "main_article", "page_count": 4}],
        {},
        {
            "page-1": base
            | {
                "session_id": "session-2",
                "hits": [{"source_id": "source-a", "page": 1}],
                "returned_candidates": [{"rank": 1}],
                "truncated": True,
                "next_cursor": "cursor-3",
                "exhausted": False,
            },
            "page-2": base
            | {
                "session_id": "session-2",
                "hits": [],
                "returned_candidates": [{"rank": 3}],
                "truncated": False,
                "next_cursor": None,
                "exhausted": True,
            },
        },
    )
    assert gapped[0]["status"] == "retrieval_incomplete"
    assert gapped[0]["search"] == "retrieval_incomplete"
