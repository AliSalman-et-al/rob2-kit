from __future__ import annotations

from rob2_kit.application.domains import _comparison_cards
from rob2_kit.application.missing_data import reconcile_missing_data


def _result() -> dict[str, object]:
    return {
        "kind": "assessable",
        "target": {
            "outcome_definition": "all-cause mortality",
            "measurement": {"method": "registry ascertainment"},
            "time_point_or_window": {
                "kind": "quantified",
                "description": "day 90 after randomization",
                "value": "90",
                "unit": "days",
            },
            "intended_analysis_population": "all randomized participants",
            "intended_effect_measure": "risk ratio",
            "comparison_groups": (
                {"id": "active", "assignment": "active"},
                {"id": "control", "assignment": "control"},
            ),
        },
        "reported": {"form": "group_bound_values"},
        "evidence": [],
    }


def test_missing_data_exposes_only_scope_compatible_bounds() -> None:
    result = reconcile_missing_data(
        [
            {
                "arm": "active",
                "population": "all randomized participants",
                "unit": "participants",
                "time_point": "day 90",
                "result_identity": "sha256:" + "a" * 64,
                "endpoint": "all-cause mortality",
                "severity": "all deaths",
                "window": "day 90 after randomization",
                "randomized": 100,
                "imputed": 4,
                "event_count": 2,
                "event_definition": "death by day 90",
            }
        ]
    )

    row = result["rows"][0]
    assert row["missing"] is None
    assert row["missing_bounds"] == {"lower": 4, "upper": 100, "kind": "bound"}
    assert row["event_count"] == 2
    assert row["endpoint"] == "all-cause mortality"


def test_different_endpoint_scopes_are_not_reconciled_as_conflicts() -> None:
    base = {
        "arm": "active",
        "population": "all randomized participants",
        "unit": "participants",
        "time_point": "day 90",
        "randomized": 100,
        "observed": 95,
        "basis": ["sha256:" + "b" * 64],
    }
    result = reconcile_missing_data(
        [base | {"endpoint": "mortality"}, base | {"endpoint": "hospitalization"}]
    )

    assert result["conflicts"] == []


def test_conflicting_reports_within_one_result_scope_are_retained() -> None:
    base = {
        "arm": "active",
        "population": "all randomized participants",
        "unit": "participants",
        "time_point": "day 90",
        "result_identity": "sha256:" + "d" * 64,
        "endpoint": "mortality",
        "window": "day 90",
        "randomized": 100,
        "basis": ["sha256:" + "b" * 64],
    }
    result = reconcile_missing_data([base | {"observed": 95}, base | {"observed": 92}])

    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["scope"]["result_identity"] == base["result_identity"]


def test_unknown_participant_flow_stages_remain_visible_per_result_scope() -> None:
    rows = [
        {
            "arm": "active",
            "population": "all randomized participants",
            "unit": "participants",
            "time_point": "day 90",
            "result_identity": "sha256:" + marker * 64,
            "endpoint": endpoint,
            "window": "day 90",
            "randomized": 100,
        }
        for marker, endpoint in (("e", "mortality"), ("f", "hospitalization"))
    ]

    cards = _comparison_cards("domain:missing", _result(), {}, [], [], preview_missing_data=rows)
    unknown_observed = [
        row
        for row in cards[0]["participant_flow"]
        if row["kind"] == "observed" and row["status"] == "unknown"
    ]

    assert len(unknown_observed) == 2
    assert {row["endpoint"] for row in unknown_observed} == {"mortality", "hospitalization"}


def test_incompatible_counts_do_not_produce_a_bound() -> None:
    result = reconcile_missing_data(
        [
            {
                "arm": "active",
                "population": "all randomized participants",
                "unit": "participants",
                "time_point": "day 90",
                "randomized": 10,
                "observed": 11,
            }
        ]
    )

    assert result["rows"][0]["missing"] is None
    assert result["rows"][0]["missing_bounds"] is None


def test_cards_keep_d3_d4_d5_propositions_and_neutral_pairs_separate() -> None:
    d3 = _comparison_cards(
        "domain:missing",
        _result(),
        {},
        [],
        [],
        preview_missing_data=[
            {
                "arm": "active",
                "population": "all randomized participants",
                "unit": "participants",
                "time_point": "day 90",
                "randomized": 100,
                "observed": 98,
                "basis": ["sha256:" + "c" * 64],
            }
        ],
    )[0]
    assert {item["name"] for item in d3["propositions"]} == {
        "availability",
        "mitigation",
        "possible_dependence",
        "likely_dependence",
    }
    assert {item["kind"] for item in d3["participant_flow"]} >= {
        "randomized",
        "eligible",
        "treated",
        "observed",
        "analyzed",
        "imputed",
        "excluded",
        "event",
    }
    assert (
        next(item for item in d3["participant_flow"] if item["kind"] == "analyzed")["value"] is None
    )
    assert not any("answer" in item for item in d3["paired_examples"])

    d4 = _comparison_cards("domain:measurement", _result(), {}, [], [])[0]
    assert {item["name"] for item in d4["propositions"]} == {
        "suitability",
        "differential_detection",
        "assessor_awareness",
        "susceptibility",
        "likely_influence",
    }
    assert {item["name"] for item in d4["slots"]} >= {
        "measurement_suitability",
        "detection_opportunity",
        "assessor_awareness",
        "susceptibility",
        "influence_possible",
        "influence_likely",
    }

    d5 = _comparison_cards("domain:selection", _result(), {}, [], [])[0]
    assert {item["name"] for item in d5["propositions"]} >= {
        "document_availability",
        "plan_applicability",
        "chronology",
        "eligible_measurements",
        "eligible_analyses",
        "results_based_selection",
    }
    assert d5["paired_examples"]


def test_participant_counts_do_not_answer_the_d3_availability_proposition() -> None:
    for counts in (
        {"analyzed": 10},
        {"event_count": 4, "event_definition": "death by day 90"},
        {"randomized": 100, "observed": 10},
    ):
        card = _comparison_cards(
            "domain:missing",
            _result(),
            {},
            [],
            [],
            preview_missing_data=[
                {
                    "arm": "active",
                    "population": "all randomized participants",
                    "unit": "participants",
                    "time_point": "day 90",
                    **counts,
                }
            ],
        )[0]
        availability = next(item for item in card["propositions"] if item["name"] == "availability")
        assert availability["status"] == "unknown"
