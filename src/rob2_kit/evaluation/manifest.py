"""Versioned scientific facts for the blinded CHAARTED release gate."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal


def _digest(value: object) -> str:
    return (
        "sha256:"
        + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


@dataclass(frozen=True)
class Quantity:
    label: str
    value: str
    denominator_basis: str


@dataclass(frozen=True)
class OutcomeFacts:
    key: Literal["pfs", "overall_survival", "adverse_events"]
    expected_terminal: Literal["assessed", "needs_input"]
    outcome_definition: str
    measurement: str
    time_point: str
    groups: tuple[str, str]
    intended_population: str
    effect_measure: str | None
    quantities: tuple[Quantity, ...]
    source_table_meaning: str
    required_evidence_context: tuple[str, ...]
    # Judgment labels are intentionally absent: defensible RoB 2 labels are not oracle facts.


@dataclass(frozen=True)
class ObjectiveFactManifest:
    schema_version: Literal["chaarted-objective-facts/v1"]
    trial: str
    outcomes: tuple[OutcomeFacts, ...]

    @property
    def identity(self) -> str:
        return _digest(asdict(self))

    def outcome(self, key: str) -> OutcomeFacts:
        for item in self.outcomes:
            if item.key == key:
                return item
        raise ValueError(f"unknown CHAARTED outcome: {key}")


_GROUPS = ("ADT plus docetaxel", "ADT alone")
_CONTEXT = ("outcome target", "reported values", "table meaning", "population basis")

CHAARTED_MANIFEST = ObjectiveFactManifest(
    schema_version="chaarted-objective-facts/v1",
    trial="E3805 CHAARTED",
    outcomes=(
        OutcomeFacts(
            key="pfs",
            expected_terminal="assessed",
            outcome_definition="time to biochemical, symptomatic, or radiographic progression",
            measurement="median time to progression",
            time_point="follow-up analysis",
            groups=_GROUPS,
            intended_population="randomized patients",
            effect_measure="hazard ratio",
            quantities=(
                Quantity("ADT plus docetaxel median", "20.2 months", "randomized arm"),
                Quantity("ADT alone median", "11.7 months", "randomized arm"),
                Quantity(
                    "hazard ratio", "0.61 (95% CI 0.51 to 0.72; P<0.001)", "time-to-event analysis"
                ),
            ),
            source_table_meaning="comparative time-to-event efficacy result",
            required_evidence_context=_CONTEXT,
        ),
        OutcomeFacts(
            key="overall_survival",
            expected_terminal="assessed",
            outcome_definition="overall survival",
            measurement="median survival",
            time_point="follow-up analysis",
            groups=_GROUPS,
            intended_population="randomized patients",
            effect_measure="hazard ratio",
            quantities=(
                Quantity("ADT plus docetaxel median", "57.6 months", "randomized arm"),
                Quantity("ADT alone median", "44.0 months", "randomized arm"),
                Quantity(
                    "hazard ratio", "0.61 (95% CI 0.47 to 0.80; P<0.001)", "time-to-event analysis"
                ),
            ),
            source_table_meaning="comparative time-to-event efficacy result",
            required_evidence_context=_CONTEXT,
        ),
        OutcomeFacts(
            key="adverse_events",
            expected_terminal="needs_input",
            outcome_definition="adverse events during the docetaxel-containing regimen",
            measurement="CTCAE severity grade",
            time_point="during docetaxel-containing regimen follow-up",
            groups=_GROUPS,
            intended_population=(
                "390 patients receiving the docetaxel-containing regimen with follow-up data"
            ),
            effect_measure=None,
            quantities=(
                Quantity(
                    "Grade 3 any event",
                    "65 (16.7%)",
                    "390 docetaxel-cohort patients with follow-up",
                ),
                Quantity(
                    "Grade 4 any event",
                    "49 (12.6%)",
                    "390 docetaxel-cohort patients with follow-up",
                ),
                Quantity(
                    "Grade 5 any event", "1 (0.3%)", "390 docetaxel-cohort patients with follow-up"
                ),
            ),
            source_table_meaning=(
                "single-group docetaxel-cohort Grade 3/4/5 category profile; "
                "no ADT-alone comparator coverage"
            ),
            required_evidence_context=_CONTEXT,
        ),
    ),
)


def check_reported_facts(outcome: OutcomeFacts, reported: Mapping[str, object]) -> tuple[str, ...]:
    """Return objective fact failures without judging any RoB 2 domain label."""

    if outcome.key == "adverse_events":
        return _check_adverse_event_facts(outcome, reported)

    failures: list[str] = []
    target = _mapping(reported.get("target"))
    population = _mapping(reported.get("population"))
    projection = {
        key: reported.get(key)
        for key in (
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
        )
    }
    if dict(_mapping(reported.get("reported"))) != projection:
        failures.append(
            "assessed outcome reported projection differs from its nested reported form"
        )
    if _normalized(target.get("outcome_definition")) != _normalized(outcome.outcome_definition):
        failures.append(f"missing objective fact: {outcome.outcome_definition}")
    if _normalized(target.get("measurement")) != _normalized(outcome.measurement):
        failures.append(f"missing objective fact: {outcome.measurement}")
    if not _matches_time_point(target.get("time_point_or_window"), outcome.time_point):
        failures.append(f"missing objective fact: {outcome.time_point}")
    if outcome.effect_measure and _normalized(target.get("intended_effect_measure")) != _normalized(
        outcome.effect_measure
    ):
        failures.append(f"missing intended effect measure: {outcome.effect_measure}")
    if not _has_explicit_randomized_population(target.get("intended_analysis_population")):
        failures.append("missing explicit randomized intended analysis population")
    if not _has_effect_of_interest(target.get("effect_of_interest"), outcome.outcome_definition):
        failures.append("missing explicit effect of interest")
    if not _matches_population(population.get("analyzed_population"), outcome.intended_population):
        failures.append(f"missing objective fact: {outcome.intended_population}")
    if not _matches_source_table_meaning(
        reported.get("source_table_meaning"),
        outcome.outcome_definition,
        outcome.source_table_meaning,
    ):
        failures.append(f"missing source-table meaning: {outcome.outcome_definition}")
    if reported.get("form") != "comparative_effect":
        failures.append("assessed outcomes must be comparative effects")
    if not _has_target_groups(target.get("comparison_groups"), outcome.groups):
        failures.append("assessed outcomes must retain the expected comparison groups")
    target_group_ids = _target_group_ids(target.get("comparison_groups"))
    if target_group_ids is None:
        failures.append("assessed outcomes must retain distinct valid target group IDs")
    if not _has_reported_groups(reported.get("comparison_groups"), target_group_ids):
        failures.append("assessed outcomes must bind the ordered target comparison groups")
    if outcome.effect_measure and _normalized(reported.get("effect_measure")) != _normalized(
        outcome.effect_measure
    ):
        failures.append(f"missing objective effect measure: {outcome.effect_measure}")
    if not _has_reported_text(reported.get("reported_text"), outcome):
        failures.append("missing complete source-reported comparative statement")
    quantities = reported.get("quantities")
    if not isinstance(quantities, (list, tuple)) or len(quantities) != 2:
        failures.append("assessed outcomes must retain exactly two ordered group quantities")
    else:
        for index, expected_quantity in enumerate(outcome.quantities[:2]):
            group_id = target_group_ids[index] if target_group_ids else ""
            if not _matches_quantity(quantities[index], expected_quantity, group_id):
                failures.append(f"missing objective quantity: {expected_quantity.value}")
    effect = _mapping(reported.get("effect"))
    effect_quantity = outcome.quantities[2]
    valid_effect_shape = _has_exact_quantity_keys(effect)
    valid_effect_metadata = _has_effect_metadata(
        effect, outcome.effect_measure, target_group_ids, effect_quantity.denominator_basis
    )
    valid_effect = _has_complete_effect(effect.get("value"), effect_quantity.value)
    valid_effect_denominator = _matches_denominator(
        effect.get("denominator_basis"), effect_quantity.denominator_basis
    )
    if (
        not valid_effect_shape
        or not valid_effect_metadata
        or not valid_effect
        or not valid_effect_denominator
    ):
        failures.append(f"missing objective quantity: {effect_quantity.value}")
    return tuple(failures)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _normalized(value: object) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _matches_population(value: object, expected: str) -> bool:
    normalized_expected = _normalized(expected)
    if normalized_expected != "randomized patients":
        return _normalized(value) == normalized_expected
    return _normalized(value) in {
        "randomized patients",
        "790 randomized patients (g1: 397, g2: 393)",
    }


def _has_explicit_randomized_population(value: object) -> bool:
    return _normalized(value) in {
        "randomized patients",
        "randomized men with metastatic hormone-sensitive prostate cancer",
    }


def _has_effect_of_interest(value: object, outcome_definition: str) -> bool:
    return _normalized(value) == f"effect on {_normalized(outcome_definition)}"


def _has_reported_text(value: object, outcome: OutcomeFacts) -> bool:
    text = _normalized(value)
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    expected_numbers = re.findall(
        r"\d+(?:\.\d+)?", " ".join(quantity.value for quantity in outcome.quantities)
    )
    expected_effect = _effect_components(outcome.quantities[-1].value)
    return (
        isinstance(value, str)
        and _normalized(outcome.outcome_definition) in text
        and all(number in numbers for number in expected_numbers)
        and _effect_components(text, embedded=True) == expected_effect
    )


def _matches_source_table_meaning(
    value: object, outcome_definition: str, declared_meaning: str | None = None
) -> bool:
    normalized_value = _normalized(value)
    normalized_outcome = _normalized(outcome_definition)
    if any(
        phrase in normalized_value
        for phrase in (
            f"not {normalized_outcome}",
            f"no {normalized_outcome}",
            f"without {normalized_outcome}",
            f"unrelated to {normalized_outcome}",
        )
    ):
        return False
    allowed = {
        normalized_outcome,
        f"primary endpoint: {normalized_outcome}",
        f"secondary endpoint: {normalized_outcome}",
        f"reported outcome: {normalized_outcome}",
        f"outcome: {normalized_outcome}",
    }
    if declared_meaning is not None:
        allowed.add(_normalized(declared_meaning))
    return normalized_value in allowed


def _matches_time_point(value: object, expected: str) -> bool:
    normalized = _normalized(value)
    return normalized == _normalized(expected) or (
        expected == "follow-up analysis" and normalized == "during study follow-up"
    )


def _has_target_groups(value: object, expected: tuple[str, str]) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    labels = tuple(_normalized(_mapping(group).get("label")) for group in value)
    return labels == tuple(_normalized(label) for label in expected)


def _target_group_ids(value: object) -> tuple[str, str] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    first = _mapping(value[0]).get("id")
    second = _mapping(value[1]).get("id")
    if (
        not isinstance(first, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", first) is None
        or not isinstance(second, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", second) is None
        or first == second
    ):
        return None
    return first, second


def _has_reported_groups(value: object, expected: tuple[str, str] | None) -> bool:
    return expected is not None and isinstance(value, (list, tuple)) and tuple(value) == expected


def _has_effect_metadata(
    effect: Mapping[str, object],
    effect_measure: str | None,
    group_ids: tuple[str, str] | None,
    denominator_basis: str,
) -> bool:
    if effect_measure is None or group_ids is None:
        return False
    first, second = group_ids
    group = _normalized(effect.get("group_or_category"))
    normalized_first, normalized_second = _normalized(first), _normalized(second)
    return (
        _normalized(effect.get("statistic")) == _normalized(effect_measure)
        and _normalized(effect.get("unit")) == "ratio"
        and group
        in {
            f"{normalized_first} vs {normalized_second}",
            f"{normalized_first} versus {normalized_second}",
        }
        and _matches_denominator(effect.get("denominator_basis"), denominator_basis)
    )


def _matches_quantity(quantity: object, expected: Quantity, group_id: str) -> bool:
    expected_value, expected_unit = expected.value.rsplit(" ", maxsplit=1)
    reported = _mapping(quantity)
    return (
        _has_exact_quantity_keys(reported)
        and _normalized(reported.get("statistic")) in {"median", "median time"}
        and _normalized(reported.get("unit")) == _normalized(expected_unit)
        and _normalized(reported.get("group_or_category")) == _normalized(group_id)
        and _matches_denominator(reported.get("denominator_basis"), expected.denominator_basis)
        and _same_number(reported.get("value"), expected_value)
    )


def _has_exact_quantity_keys(value: Mapping[str, object]) -> bool:
    return set(value) == {"statistic", "unit", "group_or_category", "value", "denominator_basis"}


def _matches_denominator(value: object, expected: str) -> bool:
    normalized = _normalized(value)
    return normalized == _normalized(expected)


def _same_number(value: object, expected: str) -> bool:
    return (
        isinstance(value, (int, float, str))
        and not isinstance(value, bool)
        and str(value) == expected
    )


def _has_complete_effect(value: object, expected: str) -> bool:
    expected_components = _effect_components(expected)
    actual_components = _effect_components(value)
    if expected_components is None or actual_components is None:
        return False
    return all(
        actual_components[name] == expected_components[name]
        for name in ("point", "confidence_level", "lower", "upper", "p_operator", "p_value")
    )


def _effect_components(value: object, *, embedded: bool = False) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    matcher = re.search if embedded else re.fullmatch
    matched = matcher(
        r"(?P<point>\d+(?:\.\d+)?)\s*\(\s*"
        r"(?P<confidence_level>\d+(?:\.\d+)?)\s*%\s*"
        r"(?:ci|confidence interval)\s*[,;:]?\s*"
        r"(?P<lower>\d+(?:\.\d+)?)(?:\s+to\s+|-)"
        r"(?P<upper>\d+(?:\.\d+)?)\s*"
        r";\s*p\s*(?P<p_operator><=|<)\s*(?P<p_value>\d+(?:\.\d+)?)\s*\)",
        normalized,
    )
    if matched is None:
        matched = matcher(
            r"(?:hazard ratio,\s*)?(?P<point>\d+(?:\.\d+)?)\s*;\s*"
            r"(?P<confidence_level>\d+(?:\.\d+)?)\s*%\s*"
            r"(?:ci|confidence interval)\s*[,;:]\s*"
            r"(?P<lower>\d+(?:\.\d+)?)(?:\s+to\s+|-)"
            r"(?P<upper>\d+(?:\.\d+)?)\s*"
            r";\s*p\s*(?P<p_operator><=|<)\s*(?P<p_value>\d+(?:\.\d+)?)",
            normalized,
        )
    return matched.groupdict() if matched else None


def _check_adverse_event_facts(
    outcome: OutcomeFacts, reported: Mapping[str, object]
) -> tuple[str, ...]:
    """Keep the adverse-event release gate deliberately strict."""

    failures: list[str] = []
    text = json.dumps(reported, sort_keys=True).casefold()
    for required in (
        outcome.outcome_definition,
        outcome.measurement,
        outcome.time_point,
        outcome.intended_population,
    ):
        if required.casefold() not in text:
            failures.append(f"missing objective fact: {required}")
    if not _matches_source_table_meaning(
        reported.get("source_table_meaning"), outcome.outcome_definition
    ):
        failures.append("source-table meaning must name the adverse-event outcome")
    for quantity in outcome.quantities:
        if quantity.value.casefold() not in text:
            failures.append(f"missing objective quantity: {quantity.value}")
    if reported.get("form") != "single_group_category_profile":
        failures.append("adverse events must be a single-group category profile")
    group = str(reported.get("group_id", "")).casefold()
    if "docetaxel" not in group or any(token in group for token in (" versus ", " vs ", "/")):
        failures.append("adverse events must identify the single docetaxel cohort")
    categories = json.dumps(reported.get("categories", ()), sort_keys=True).casefold()
    for grade in ("grade 3", "grade 4", "grade 5"):
        if grade not in categories:
            failures.append(f"adverse events must retain the {grade} category")
    if reported.get("effect_measure") or reported.get("derived") or "risk ratio" in text:
        failures.append("adverse events must not assert a comparative effect or derivation")
    if "comparator" not in text or not any(
        word in text for word in ("unavailable", "missing", "not measured")
    ):
        failures.append("adverse events must disclose missing comparator coverage")
    if re.search(r"(?:65|49).{0,48}randomi[sz]ed|randomi[sz]ed.{0,48}(?:65|49)", text):
        failures.append("65 and 49 must not be represented as randomized-arm counts")
    return tuple(failures)
