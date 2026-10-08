from __future__ import annotations

import copy

import pytest

from rob2_kit.application.finalization import _valid_missing_data
from rob2_kit.application.missing_data import reconcile_missing_data
from rob2_kit.interfaces.mcp.contracts import MissingDataReconciliation
from scripts.verify_bundle import _valid_missing_data as independent_verifier


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            {
                "observed": 20,
                "event_count": 4,
                "event_definition": "first primary event",
                "semantics": {
                    "censoring": {
                        "kind": "withdrawal",
                        "count": 4,
                        "reason": "later withdrawal after an already ascertained first event",
                    }
                },
            },
            0,
        ),
        (
            {
                "observed": 20,
                "semantics": {
                    "event_count": 2,
                    "event_definition": "non-CV competing death resolving endpoint follow-up",
                },
            },
            0,
        ),
        (
            {
                "unavailable": 3,
                "analyzed": 20,
                "semantics": {
                    "censoring": {
                        "kind": "loss_to_follow_up",
                        "count": 3,
                        "reason": "reported incomplete endpoint follow-up before first event",
                    }
                },
            },
            3,
        ),
        (
            {
                "observed": 20,
                "semantics": {
                    "censoring": {
                        "kind": "administrative",
                        "count": 16,
                        "reason": "complete event-free assessment at planned cutoff",
                    }
                },
            },
            0,
        ),
        (
            {
                "event_count": 4,
                "event_definition": "first primary event",
                "semantics": {
                    "censoring": {
                        "kind": "unknown",
                        "count": 3,
                        "reason": "overlap with already observed first events is unknown",
                    }
                },
            },
            None,
        ),
    ],
    ids=[
        "event-before-later-loss",
        "known-competing-death",
        "loss-before-first-event",
        "complete-administrative-censoring",
        "unknown-overlap",
    ],
)
def test_scoped_availability_counts_preserve_time_to_event_distinctions(facts, expected):
    result_id = "sha256:" + "a" * 64
    evidence_id = "sha256:" + "b" * 64
    source = {
        "arm": "A",
        "population": "randomized",
        "unit": "participants",
        "time_point": "primary endpoint follow-up",
        "randomized": 20,
        "result_identity": result_id,
        "basis": [evidence_id],
        **facts,
    }
    before = copy.deepcopy(source)
    data = reconcile_missing_data([source])
    row = data["rows"][0]
    assert row["missing"] == expected
    assert row["observed"] == facts.get("observed")
    if expected is None:
        assert row["missing_bounds"] == {"lower": 0, "upper": 20, "kind": "bound"}
    else:
        assert row["missing_bounds"] == {"lower": expected, "upper": expected, "kind": "exact"}
    assert source == before and "judgment" not in data
    assert MissingDataReconciliation.model_validate(data).rows[0].missing == expected
    evidence = {evidence_id: {"trial_id": "trial"}}
    for validator in [_valid_missing_data, independent_verifier]:
        assert validator(data, "sq:missing:data-available", evidence, "trial", result_id)


@pytest.mark.parametrize(
    "facts",
    [
        {"observed": 19, "unavailable": 3},
        {"unavailable": 21},
        {"observed": 21},
    ],
)
def test_incompatible_availability_counts_do_not_produce_exact_missingness(facts):
    row = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "randomized",
                "unit": "participants",
                "time_point": "endpoint",
                "randomized": 20,
                **facts,
            }
        ]
    )["rows"][0]
    assert row["missing"] is None and row["missing_bounds"] is None
    assert row.get("unavailable") == facts.get("unavailable")


def test_unavailable_count_without_denominator_does_not_invent_observed_count():
    row = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "randomized",
                "unit": "participants",
                "time_point": "endpoint",
                "unavailable": 3,
            }
        ]
    )["rows"][0]
    assert row["unavailable"] == 3 and row["observed"] is None
    assert row["missing"] is None and row["missing_fraction"] is None


def test_unavailable_reports_and_tampering_are_checked_by_both_verifiers():
    result_id = "sha256:" + "a" * 64
    evidence_id = "sha256:" + "b" * 64
    source = {
        "arm": "A",
        "population": "randomized",
        "unit": "participants",
        "time_point": "endpoint",
        "randomized": 20,
        "unavailable": 3,
        "result_identity": result_id,
        "basis": [evidence_id],
    }
    data = reconcile_missing_data([source, source | {"unavailable": 4}])
    evidence = {evidence_id: {"trial_id": "trial"}}
    assert len(data["conflicts"]) == 1
    for validator in [_valid_missing_data, independent_verifier]:
        assert validator(data, "sq:missing:data-available", evidence, "trial", result_id)
        tampered = copy.deepcopy(data)
        tampered["rows"][0]["missing_bounds"]["upper"] = 20
        assert not validator(tampered, "sq:missing:data-available", evidence, "trial", result_id)
        tampered = copy.deepcopy(data)
        tampered["conflicts"] = []
        assert not validator(tampered, "sq:missing:data-available", evidence, "trial", result_id)
