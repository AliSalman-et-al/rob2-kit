from decimal import Decimal
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


def _structured_pfs(*, effect_value: object = "0.61"):
    result = {
        "target": {
            "outcome_definition": "Time to biochemical, symptomatic, or radiographic progression",
            "measurement": "Median time to progression",
            "time_point_or_window": "follow-up analysis",
            "intended_analysis_population": "Randomized patients",
            "effect_of_interest": (
                "effect on time to biochemical, symptomatic, or radiographic progression"
            ),
            "comparison_groups": [
                {"id": "g1", "label": "ADT plus docetaxel"},
                {"id": "g2", "label": "ADT alone"},
            ],
            "intended_effect_measure": "Hazard ratio",
        },
        "population": {
            "analyzed_population": "randomized patients",
            "outcome_measurement_coverage": [
                {"group_id": "g1", "status": "measured", "explanation": None},
                {"group_id": "g2", "status": "measured", "explanation": None},
            ],
        },
        "form": "comparative_effect",
        "effect_measure": "Hazard ratio",
        "reported_text": (
            "time to biochemical, symptomatic, or radiographic progression; 20.2 months; "
            "11.7 months; 0.61 (95% CI 0.51 to 0.72; P<0.001)"
        ),
        "effect": {
            "statistic": "Hazard ratio",
            "unit": "ratio",
            "group_or_category": "g1 vs g2",
            "value": effect_value,
            "denominator_basis": "time-to-event analysis",
        },
        "quantities": [
            {
                "statistic": "median",
                "unit": "Months",
                "group_or_category": "g1",
                "denominator_basis": "randomized arm",
                "value": 20.2,
            },
            {
                "statistic": "median",
                "unit": "Months",
                "group_or_category": "g2",
                "denominator_basis": "randomized arm",
                "value": 11.7,
            },
        ],
        "comparison_groups": ["g1", "g2"],
        "precision": {
            "confidence_interval": {"level": "95", "lower": "0.51", "upper": "0.72"},
            "p_value": {"operator": "<", "value": "0.001"},
        },
        "source_table_meaning": (
            "Secondary endpoint: time to biochemical, symptomatic, or radiographic progression"
        ),
    }
    result["reported"] = {
        key: result[key]
        for key in (
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
            "precision",
        )
    }
    return result


def _structured_overall_survival():
    result = {
        "target": {
            "outcome_definition": "Overall survival",
            "measurement": "Median survival",
            "time_point_or_window": "follow-up analysis",
            "intended_analysis_population": "Randomized patients",
            "effect_of_interest": "effect on overall survival",
            "comparison_groups": [
                {"id": "g1", "label": "ADT plus docetaxel"},
                {"id": "g2", "label": "ADT alone"},
            ],
            "intended_effect_measure": "Hazard ratio",
        },
        "population": {
            "analyzed_population": "randomized patients",
            "outcome_measurement_coverage": [
                {"group_id": "g1", "status": "measured", "explanation": None},
                {"group_id": "g2", "status": "measured", "explanation": None},
            ],
        },
        "form": "comparative_effect",
        "effect_measure": "Hazard ratio",
        "reported_text": (
            "overall survival; 57.6 months; 44.0 months; 0.61 (95% CI 0.47 to 0.80; P<0.001)"
        ),
        "effect": {
            "statistic": "Hazard ratio",
            "unit": "ratio",
            "group_or_category": "g1 vs g2",
            "value": "0.61",
            "denominator_basis": "time-to-event analysis",
        },
        "quantities": [
            {
                "statistic": "Median",
                "unit": "Months",
                "group_or_category": "g1",
                "denominator_basis": "randomized arm",
                "value": 57.6,
            },
            {
                "statistic": "Median",
                "unit": "Months",
                "group_or_category": "g2",
                "denominator_basis": "randomized arm",
                "value": 44.0,
            },
        ],
        "comparison_groups": ["g1", "g2"],
        "precision": {
            "confidence_interval": {"level": "95", "lower": "0.47", "upper": "0.80"},
            "p_value": {"operator": "<", "value": "0.001"},
        },
        "source_table_meaning": "Secondary endpoint: overall survival",
    }
    result["reported"] = {
        key: result[key]
        for key in (
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
            "precision",
        )
    }
    return result


def test_pfs_cbdf2f8_shape_only_rejects_missing_hr_ci_and_p_value():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    assert check_reported_facts(outcome, _structured_pfs(effect_value="0.61")) == ()


def test_pfs_cbdf2f8_shape_rejects_omitted_denominator_bases():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs(effect_value="0.61")
    effect = result["effect"]
    assert isinstance(effect, dict)
    effect.pop("denominator_basis")
    quantities = result["quantities"]
    assert isinstance(quantities, list)
    for quantity in quantities:
        quantity.pop("denominator_basis")
    _sync_reported(result)

    failures = check_reported_facts(outcome, result)

    assert any("20.2" in failure for failure in failures)
    assert any("11.7" in failure for failure in failures)
    assert any("0.61" in failure for failure in failures)


def test_pfs_accepts_cbdf2f8_shape_with_complete_hr_value():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    assert check_reported_facts(outcome, _structured_pfs(effect_value="0.61")) == ()


def test_pfs_rejects_related_but_different_outcome_definition():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs(
        effect_value="hazard ratio in the combination group, 0.61; 95% CI, 0.51 to 0.72; P<0.001"
    )
    result["reported_text"] = (
        "development of castration-resistant prostate cancer (biochemical, symptomatic, or "
        "radiographic); median times 20.2 months and 11.7 months; hazard ratio in the "
        "combination group, 0.61; 95% CI, 0.51 to 0.72; P<0.001"
    )
    _sync_reported(result)
    assert "missing complete source-reported comparative statement" in check_reported_facts(
        outcome, result
    )


def test_pfs_uses_structured_precision_not_reported_text_punctuation():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    result["reported_text"] = (
        "time to biochemical, symptomatic, or radiographic progression; 20.2 months; "
        "11.7 months; 0.61 (95% CI 0.51 to 0.72; P<=0.001)"
    )
    _sync_reported(result)

    assert any("precision" in failure for failure in check_reported_facts(outcome, result))


def test_assessed_reported_text_requires_every_objective_value():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    result["reported_text"] = str(result["reported_text"]).replace("20.2 months; ", "")
    _sync_reported(result)

    assert "reported source statement omits an objective quantity" in check_reported_facts(
        outcome, result
    )


def test_precision_uses_standalone_ci_marker():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    result["reported_text"] = "decision context; " + str(result["reported_text"])
    _sync_reported(result)

    assert check_reported_facts(outcome, result) == ()


def test_assessed_outcomes_accept_decimal_equivalent_precision_and_quantities():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    precision = result["precision"]
    assert isinstance(precision, dict)
    precision["confidence_interval"] = {
        "level": Decimal("95.0"),
        "lower": Decimal("0.510"),
        "upper": Decimal("0.720"),
    }
    precision["p_value"] = {"operator": "<", "value": Decimal("0.0010")}
    effect = result["effect"]
    quantities = result["quantities"]
    assert isinstance(effect, dict) and isinstance(quantities, list)
    effect["value"] = Decimal("0.610")
    quantities[0]["value"] = Decimal("20.20")
    quantities[1]["value"] = Decimal("11.70")
    _sync_reported(result)

    assert check_reported_facts(outcome, result) == ()


def test_assessed_outcomes_reject_nested_reported_extra():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    reported = result["reported"]
    assert isinstance(reported, dict)
    reported["unexpected"] = "nested extra"

    assert any(
        "reported projection" in failure for failure in check_reported_facts(outcome, result)
    )


def test_pfs_rejects_hr_components_assigned_to_the_wrong_roles():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    for lower, upper, p_value in (("0.51", "0.001", "0.72"), ("0.72", "0.51", "0.001")):
        result = _structured_pfs()
        result["precision"] = {
            **cast(dict[str, object], result["precision"]),
            "confidence_interval": {"level": "95", "lower": lower, "upper": upper},
            "p_value": {"operator": "<", "value": p_value},
        }
        _sync_reported(result)
        assert any("0.61" in failure for failure in check_reported_facts(outcome, result))


def test_pfs_rejects_nonrandomized_or_unrelated_populations():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    for population in (
        "790 randomized participants",
        "randomized men with hormone-sensitive metastatic prostate cancer",
    ):
        result = _structured_pfs()
        result["population"] = {"analyzed_population": population}
        assert any(
            "randomized patients" in failure for failure in check_reported_facts(outcome, result)
        )


def test_randomized_population_parenthetical_form_is_closed_for_target_and_analysis():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    positive = _structured_pfs()
    arm_count_population = "790 randomized patients (g1: 397, g2: 393)"
    positive["population"] = {"analyzed_population": arm_count_population}
    assert any(
        "randomized patients" in failure for failure in check_reported_facts(outcome, positive)
    )


def test_pfs_rejects_swapped_or_unbound_median_groups():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    for group_ids in (("g2", "g1"), ("other", "g2")):
        result = _structured_pfs()
        quantities = result["quantities"]
        assert isinstance(quantities, list)
        for quantity, group_id in zip(quantities, group_ids, strict=True):
            quantity["group_or_category"] = group_id
        failures = check_reported_facts(outcome, result)
        assert any("20.2" in failure for failure in failures)


def test_pfs_rejects_unrelated_source_table_meaning_and_reported_group_ids():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    unrelated = _structured_pfs()
    unrelated["source_table_meaning"] = "A laboratory biomarker result"
    assert any(
        "source-table meaning" in failure for failure in check_reported_facts(outcome, unrelated)
    )

    mismatched_groups = _structured_pfs()
    mismatched_groups["comparison_groups"] = ["g2", "g1"]
    _sync_reported(mismatched_groups)
    assert any(
        "ordered target comparison groups" in failure
        for failure in check_reported_facts(outcome, mismatched_groups)
    )

    for meaning in (
        "Secondary endpoint: not time to biochemical, symptomatic, or radiographic progression",
        "Secondary endpoint: no time to biochemical, symptomatic, or radiographic progression",
        "Secondary endpoint: without time to biochemical, symptomatic, or radiographic progression",
        "Secondary endpoint: unrelated to time to biochemical, symptomatic, or radiographic "
        "progression",
    ):
        negated = _structured_pfs()
        negated["source_table_meaning"] = meaning
        assert any(
            "source-table meaning" in failure for failure in check_reported_facts(outcome, negated)
        )


def test_pfs_rejects_wrong_denominator_bases():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    effect = result["effect"]
    assert isinstance(effect, dict)
    effect["denominator_basis"] = "randomized arm"
    _sync_reported(result)
    assert any("0.61" in failure for failure in check_reported_facts(outcome, result))

    result = _structured_pfs()
    quantities = result["quantities"]
    assert isinstance(quantities, list)
    quantities[0]["denominator_basis"] = "time-to-event analysis"
    assert any("20.2" in failure for failure in check_reported_facts(outcome, result))

    for denominator_basis in (
        "non-randomized arm",
        "nonrandomized arm",
        "non randomized arm",
        "not randomized arm",
    ):
        result = _structured_pfs()
        quantities = result["quantities"]
        assert isinstance(quantities, list)
        quantities[0]["denominator_basis"] = denominator_basis
        assert any("20.2" in failure for failure in check_reported_facts(outcome, result))

    result = _structured_pfs()
    effect = result["effect"]
    assert isinstance(effect, dict)
    effect["denominator_basis"] = "not a time-to-event analysis"
    _sync_reported(result)
    assert any("0.61" in failure for failure in check_reported_facts(outcome, result))


def test_overall_survival_accepts_complete_structure_and_rejects_negated_facts():
    outcome = CHAARTED_MANIFEST.outcome("overall_survival")
    assert check_reported_facts(outcome, _structured_overall_survival()) == ()
    primary_endpoint = _structured_overall_survival()
    primary_endpoint["source_table_meaning"] = "Primary endpoint: overall survival"
    assert check_reported_facts(outcome, primary_endpoint) == ()
    declared_meaning = _structured_overall_survival()
    declared_meaning["source_table_meaning"] = outcome.source_table_meaning
    assert check_reported_facts(outcome, declared_meaning) == ()
    operator_mismatch = _structured_overall_survival()
    precision = cast(dict[str, object], operator_mismatch["precision"])
    precision["p_value"] = {"operator": "<=", "value": "0.001"}
    _sync_reported(operator_mismatch)
    assert any("0.61" in failure for failure in check_reported_facts(outcome, operator_mismatch))

    for denominator_basis in ("non randomized arm", "not randomized arm"):
        result = _structured_overall_survival()
        quantities = result["quantities"]
        assert isinstance(quantities, list)
        quantities[0]["denominator_basis"] = denominator_basis
        assert any("57.6" in failure for failure in check_reported_facts(outcome, result))

    result = _structured_overall_survival()
    effect = result["effect"]
    assert isinstance(effect, dict)
    effect["denominator_basis"] = "not a time-to-event analysis"
    _sync_reported(result)
    assert any("0.61" in failure for failure in check_reported_facts(outcome, result))

    for meaning in (
        "Secondary endpoint: not overall survival",
        "Secondary endpoint: no overall survival",
        "Secondary endpoint: without overall survival",
        "Secondary endpoint: unrelated to overall survival",
    ):
        result = _structured_overall_survival()
        result["source_table_meaning"] = meaning
        assert any(
            "source-table meaning" in failure for failure in check_reported_facts(outcome, result)
        )


def test_assessed_outcomes_reject_invalid_target_fields():
    cases = (
        ("intended_effect_measure", "risk ratio", "intended effect measure"),
        ("intended_effect_measure", "", "intended effect measure"),
        ("effect_of_interest", "", "effect of interest"),
        ("effect_of_interest", "not available", "effect of interest"),
    )
    for key, factory in (
        ("pfs", _structured_pfs),
        ("overall_survival", _structured_overall_survival),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        for field, value, expected_failure in cases:
            result = factory()
            target = result["target"]
            assert isinstance(target, dict)
            target[field] = value
            assert any(
                expected_failure in failure for failure in check_reported_facts(outcome, result)
            )


def test_assessed_outcomes_reject_wrong_structured_effect_precision():
    for key, factory in (
        ("pfs", _structured_pfs),
        ("overall_survival", _structured_overall_survival),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        result = factory()
        precision = cast(dict[str, object], result["precision"])
        precision["confidence_interval"] = {"level": "95", "lower": "0.62", "upper": "0.72"}
        _sync_reported(result)
        assert any("0.61" in failure for failure in check_reported_facts(outcome, result))


def _sync_reported(result: dict[str, object]) -> None:
    result["reported"] = {
        key: result[key]
        for key in (
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
            "precision",
        )
    }


def test_assessed_outcomes_reject_projection_and_target_integrity_failures():
    for key, factory in (
        ("pfs", _structured_pfs),
        ("overall_survival", _structured_overall_survival),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        missing = factory()
        missing.pop("reported")
        assert any(
            "reported projection" in failure for failure in check_reported_facts(outcome, missing)
        )

        contradictory = factory()
        nested = contradictory["reported"]
        assert isinstance(nested, dict)
        nested["effect_measure"] = "risk ratio"
        assert any(
            "reported projection" in failure
            for failure in check_reported_facts(outcome, contradictory)
        )

        suffix_negation = factory()
        target = suffix_negation["target"]
        assert isinstance(target, dict)
        target["effect_of_interest"] = "Progression or survival without censoring"
        assert any(
            "effect of interest" in failure
            for failure in check_reported_facts(outcome, suffix_negation)
        )

        for first_id, second_id in (("g1", "g1"), ("g!", "g2"), ("", "g2")):
            invalid_groups = factory()
            target = invalid_groups["target"]
            assert isinstance(target, dict)
            groups = target["comparison_groups"]
            assert isinstance(groups, list)
            groups[0]["id"] = first_id
            groups[1]["id"] = second_id
            assert any(
                "distinct valid target group IDs" in failure
                for failure in check_reported_facts(outcome, invalid_groups)
            )


def test_assessed_outcomes_reject_unrelated_effect_metadata():
    for key, factory in (
        ("pfs", _structured_pfs),
        ("overall_survival", _structured_overall_survival),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        for field, value in (
            ("statistic", "risk ratio"),
            ("unit", "time-to-event analysis"),
            ("group_or_category", "g2 versus g1"),
        ):
            result = factory()
            effect = result["effect"]
            assert isinstance(effect, dict)
            effect[field] = value
            _sync_reported(result)
            assert any("0.61" in failure for failure in check_reported_facts(outcome, result))


def test_assessed_outcomes_accept_digit_and_uppercase_group_ids():
    for key, factory in (
        ("pfs", _structured_pfs),
        ("overall_survival", _structured_overall_survival),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        result = factory()
        target = result["target"]
        assert isinstance(target, dict)
        groups = target["comparison_groups"]
        assert isinstance(groups, list)
        groups[0]["id"] = "1G"
        groups[1]["id"] = "Control_ARM"
        result["comparison_groups"] = ["1G", "Control_ARM"]
        quantities = result["quantities"]
        assert isinstance(quantities, list)
        quantities[0]["group_or_category"] = "1G"
        quantities[1]["group_or_category"] = "Control_ARM"
        effect = result["effect"]
        assert isinstance(effect, dict)
        effect["group_or_category"] = "1g vs control_arm"
        population = result["population"]
        assert isinstance(population, dict)
        coverage = population["outcome_measurement_coverage"]
        assert isinstance(coverage, list)
        coverage[0]["group_id"] = "1G"
        coverage[1]["group_id"] = "Control_ARM"
        _sync_reported(result)
        assert check_reported_facts(outcome, result) == ()


def test_assessed_outcomes_reject_extra_or_negated_group_quantities():
    for key, factory, expected_value in (
        ("pfs", _structured_pfs, "20.2"),
        ("overall_survival", _structured_overall_survival, "57.6"),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        extra = factory()
        quantities = extra["quantities"]
        assert isinstance(quantities, list)
        conflicting = dict(quantities[0])
        conflicting["value"] = "999"
        quantities.append(conflicting)
        _sync_reported(extra)
        assert any(
            "exactly two ordered" in failure for failure in check_reported_facts(outcome, extra)
        )

        negated = factory()
        quantities = negated["quantities"]
        assert isinstance(quantities, list)
        quantities[0]["statistic"] = "not median"
        quantities[0]["value"] = f"not {quantities[0]['value']}"
        _sync_reported(negated)
        assert any(expected_value in failure for failure in check_reported_facts(outcome, negated))


def test_assessed_outcomes_reject_cross_outcome_effect_interests():
    for key, factory, other_interest in (
        ("pfs", _structured_pfs, "effect on laboratory progression"),
        ("overall_survival", _structured_overall_survival, "effect on bacterial survival"),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        result = factory()
        target = result["target"]
        assert isinstance(target, dict)
        target["effect_of_interest"] = other_interest
        assert any(
            "effect of interest" in failure for failure in check_reported_facts(outcome, result)
        )


def test_pfs_accepts_declared_source_table_meaning():
    outcome = CHAARTED_MANIFEST.outcome("pfs")
    result = _structured_pfs()
    result["source_table_meaning"] = outcome.source_table_meaning
    assert check_reported_facts(outcome, result) == ()


def test_assessed_outcomes_reject_extra_quantity_keys():
    for key, factory, expected_value in (
        ("pfs", _structured_pfs, "0.61"),
        ("overall_survival", _structured_overall_survival, "0.61"),
    ):
        outcome = CHAARTED_MANIFEST.outcome(key)
        effect_extra = factory()
        effect = effect_extra["effect"]
        assert isinstance(effect, dict)
        effect["extra"] = "contradiction"
        _sync_reported(effect_extra)
        assert any(
            expected_value in failure for failure in check_reported_facts(outcome, effect_extra)
        )

        median_extra = factory()
        quantities = median_extra["quantities"]
        assert isinstance(quantities, list)
        quantities[0]["extra"] = "contradiction"
        _sync_reported(median_extra)
        assert any(
            "missing objective quantity" in failure
            for failure in check_reported_facts(outcome, median_extra)
        )


def test_adverse_event_oracle_rejects_comparison_and_randomized_count_claims():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    bad = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "categories": [{"value": "65 (16.7%)", "denominator_basis": "randomized arm"}],
        "comparator": "available",
    }
    failures = check_reported_facts(outcome, bad)
    assert any("single-group" in value for value in failures)
    assert any("comparative" in value for value in failures)
    assert any("category" in value for value in failures)


def _adverse_event_profile() -> dict[str, object]:
    return {
        "target": {
            "outcome_definition": "adverse events during the docetaxel-containing regimen",
            "measurement": "CTCAE severity grade",
            "time_point_or_window": "during docetaxel-containing regimen follow-up",
            "intended_analysis_population": (
                "390 patients receiving the docetaxel-containing regimen with follow-up data"
            ),
            "comparison_groups": [
                {"id": "docetaxel", "label": "ADT plus docetaxel"},
                {"id": "adt", "label": "ADT alone"},
            ],
        },
        "population": {
            "analyzed_population": (
                "390 patients receiving the docetaxel-containing regimen with follow-up data"
            ),
            "outcome_measurement_coverage": [
                {"group_id": "docetaxel", "status": "measured"},
                {"group_id": "adt", "status": "not_measured"},
            ],
        },
        "form": "single_group_category_profile",
        "group_id": "docetaxel",
        "categories": [
            {
                "statistic": "count",
                "unit": "participants",
                "group_or_category": "Grade 3 any event",
                "value": "65 (16.7%)",
                "denominator_basis": "390 docetaxel-cohort patients with follow-up",
            },
            {
                "statistic": "count",
                "unit": "participants",
                "group_or_category": "Grade 4 any event",
                "value": "49 (12.6%)",
                "denominator_basis": "390 docetaxel-cohort patients with follow-up",
            },
            {
                "statistic": "count",
                "unit": "participants",
                "group_or_category": "Grade 5 any event",
                "value": "1 (0.3%)",
                "denominator_basis": "390 docetaxel-cohort patients with follow-up",
            },
        ],
        "source_table_meaning": ("adverse events during the docetaxel-containing regimen"),
    }


def test_adverse_event_oracle_requires_outcome_bound_source_table_meaning():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    assert check_reported_facts(outcome, _adverse_event_profile()) == ()

    legacy = _adverse_event_profile()
    legacy["source_table_meaning"] = (
        "Reported outcome: adverse events during the docetaxel-containing regimen"
    )
    assert (
        "source-table meaning does not exactly bind the adverse-event outcome"
        in check_reported_facts(outcome, legacy)
    )


def test_adverse_event_oracle_rejects_each_missing_grade():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    for grade in ("Grade 3", "Grade 4", "Grade 5"):
        value = _adverse_event_profile()
        categories = cast(list[dict[str, str]], value["categories"])
        value["categories"] = [
            row for row in categories if row["group_or_category"] != f"{grade} any event"
        ]
        assert (
            f"retain the {grade.casefold()} category"
            in " ".join(check_reported_facts(outcome, value)).casefold()
        )


def test_adverse_event_oracle_rejects_each_comparison_invariant():
    outcome = CHAARTED_MANIFEST.outcome("adverse_events")
    cases = (
        ({"form": "comparative_effect"}, "single-group"),
        ({"group_id": "ADT versus ADT plus docetaxel"}, "single docetaxel cohort"),
        (
            {
                "population": {
                    "analyzed_population": (
                        "390 patients receiving the docetaxel-containing regimen with "
                        "follow-up data"
                    ),
                    "outcome_measurement_coverage": [
                        {"group_id": "docetaxel", "status": "measured"},
                        {"group_id": "adt", "status": "measured"},
                    ],
                }
            },
            "comparator coverage",
        ),
        ({"effect_measure": "risk ratio"}, "comparative effect"),
        (
            {"categories": [{"value": "65 (16.7%)", "denominator_basis": "randomized arm"}]},
            "category",
        ),
        (
            {"categories": [{"value": "65 (16.7%)", "statistic": "randomized count"}]},
            "category",
        ),
        (
            {"categories": [{"value": "49 (12.6%)", "group_or_category": "randomized cohort"}]},
            "category",
        ),
    )
    for changes, expected in cases:
        assert expected in " ".join(
            check_reported_facts(outcome, _adverse_event_profile() | changes)
        )
