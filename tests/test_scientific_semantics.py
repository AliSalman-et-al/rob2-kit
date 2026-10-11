from __future__ import annotations

from rob2_kit.application.domains import _comparison_cards


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


def test_participant_counts_do_not_generate_d3_answers() -> None:
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
        assert not {"propositions", "answers", "judgment"} & card.keys()
        assert any(row["value"] is not None for row in card["participant_flow"])
