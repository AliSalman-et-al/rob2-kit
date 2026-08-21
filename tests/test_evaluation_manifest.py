from typing import cast

from rob2_kit.evaluation.manifest import CHAARTED_MANIFEST, check_reported_facts


def test_manifest_is_versioned_and_does_not_prescribe_domain_labels():
    assert CHAARTED_MANIFEST.schema_version == "chaarted-objective-facts/v1"
    assert {item.key: item.expected_terminal for item in CHAARTED_MANIFEST.outcomes} == {
        "pfs": "assessed",
        "overall_survival": "assessed",
        "adverse_events": "needs_input",
    }
    assert "judgment" not in str(CHAARTED_MANIFEST).casefold()


def test_adverse_event_oracle_rejects_comparison_and_randomized_count_claims():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    bad = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "groups": "65 randomized vs 49 randomized",
        "comparator": "available",
    }
    failures = check_reported_facts(outcome, bad)
    assert any("single-group" in value for value in failures)
    assert any("comparative" in value for value in failures)
    assert any("randomized-arm" in value for value in failures)


def _adverse_event_profile() -> dict[str, object]:
    return {
        "form": "single_group_category_profile",
        "group_id": "docetaxel cohort",
        "categories": [
            {"label": "Grade 3", "value": "65 (16.7%)"},
            {"label": "Grade 4", "value": "49 (12.6%)"},
            {"label": "Grade 5", "value": "1 (0.3%)"},
        ],
        "comparator_coverage": "unavailable",
    }


def test_adverse_event_oracle_rejects_each_missing_grade():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    for grade in ("Grade 3", "Grade 4", "Grade 5"):
        value = _adverse_event_profile()
        categories = cast(list[dict[str, str]], value["categories"])
        value["categories"] = [row for row in categories if row["label"] != grade]
        assert (
            f"retain the {grade.casefold()} category"
            in " ".join(check_reported_facts(outcome, value)).casefold()
        )


def test_adverse_event_oracle_rejects_each_comparison_invariant():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    cases = (
        ({"form": "comparative_effect"}, "single-group"),
        ({"group_id": "ADT versus ADT plus docetaxel"}, "single docetaxel cohort"),
        ({"comparator_coverage": "reported"}, "missing comparator"),
        ({"effect_measure": "risk ratio"}, "comparative effect"),
        ({"groups": "65 randomized intervention; 49 randomized comparator"}, "randomized-arm"),
    )
    for changes, expected in cases:
        assert expected in " ".join(
            check_reported_facts(outcome, _adverse_event_profile() | changes)
        )
