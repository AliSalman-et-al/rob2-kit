"""Versioned scientific facts for the blinded release gate."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Literal, cast


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Quantity:
    statistic: str
    unit: str
    group_or_category: str
    value: str
    denominator_basis: str


@dataclass(frozen=True)
class EffectPrecision:
    confidence_level: str
    lower: str
    upper: str
    p_operator: Literal["=", "<", "<=", ">", ">="]
    p_value: str


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
    effect_precision: EffectPrecision | None
    quantities: tuple[Quantity, ...]
    source_table_meaning: str
    required_evidence_context: tuple[str, ...]


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
        raise ValueError(f"unknown outcome: {key}")


_GROUPS = ("ADT plus docetaxel", "ADT alone")
_CONTEXT = ("target_basis", "reported_values", "reported_context", "population_basis")

CHAARTED_MANIFEST = ObjectiveFactManifest(
    schema_version="chaarted-objective-facts/v1",
    trial="E3805 CHAARTED",
    outcomes=(
        OutcomeFacts(
            "pfs",
            "assessed",
            "time to biochemical, symptomatic, or radiographic progression",
            "median time to progression",
            "follow-up analysis",
            _GROUPS,
            "randomized patients",
            "hazard ratio",
            EffectPrecision("95", "0.51", "0.72", "<", "0.001"),
            (
                Quantity("median", "months", "ADT plus docetaxel", "20.2", "randomized arm"),
                Quantity("median", "months", "ADT alone", "11.7", "randomized arm"),
                Quantity("hazard ratio", "ratio", "comparison", "0.61", "time-to-event analysis"),
            ),
            "comparative time-to-event efficacy result",
            _CONTEXT,
        ),
        OutcomeFacts(
            "overall_survival",
            "assessed",
            "overall survival",
            "median survival",
            "follow-up analysis",
            _GROUPS,
            "randomized patients",
            "hazard ratio",
            EffectPrecision("95", "0.47", "0.80", "<", "0.001"),
            (
                Quantity("median", "months", "ADT plus docetaxel", "57.6", "randomized arm"),
                Quantity("median", "months", "ADT alone", "44.0", "randomized arm"),
                Quantity("hazard ratio", "ratio", "comparison", "0.61", "time-to-event analysis"),
            ),
            "comparative time-to-event efficacy result",
            _CONTEXT,
        ),
        OutcomeFacts(
            "adverse_events",
            "needs_input",
            "adverse events during the docetaxel-containing regimen",
            "CTCAE severity grade",
            "during docetaxel-containing regimen follow-up",
            _GROUPS,
            "390 patients receiving the docetaxel-containing regimen with follow-up data",
            None,
            None,
            (
                Quantity(
                    "count",
                    "participants",
                    "Grade 3 any event",
                    "65 (16.7%)",
                    "390 docetaxel-cohort patients with follow-up",
                ),
                Quantity(
                    "count",
                    "participants",
                    "Grade 4 any event",
                    "49 (12.6%)",
                    "390 docetaxel-cohort patients with follow-up",
                ),
                Quantity(
                    "count",
                    "participants",
                    "Grade 5 any event",
                    "1 (0.3%)",
                    "390 docetaxel-cohort patients with follow-up",
                ),
            ),
            "adverse events during the docetaxel-containing regimen",
            _CONTEXT,
        ),
    ),
)


def check_reported_facts(outcome: OutcomeFacts, card: Mapping[str, object]) -> tuple[str, ...]:
    """Check closed scientific fields by role; text provenance is checked by verifier."""

    target, population = (_mapping(card.get(name)) for name in ("target", "population"))
    reported = _mapping(card.get("reported")) or card
    failures: list[str] = []
    if "reported" not in card and outcome.expected_terminal == "assessed":
        failures.append("reported projection differs from its nested reported form")
    elif "reported" in card and not _same_mapping_projection(card, reported):
        failures.append("reported projection differs from its nested reported form")
    for field, expected in (
        ("outcome_definition", outcome.outcome_definition),
        ("measurement", outcome.measurement),
        ("time_point_or_window", outcome.time_point),
        ("intended_analysis_population", outcome.intended_population),
    ):
        if _normalized(target.get(field)) != _normalized(expected):
            failures.append(f"missing objective fact: {expected}")
    if _normalized(population.get("analyzed_population")) != _normalized(
        outcome.intended_population
    ):
        failures.append(f"missing objective fact: {outcome.intended_population}")
    if outcome.expected_terminal == "assessed" and not _source_table_meaning(
        card.get("source_table_meaning"), outcome
    ):
        failures.append("source-table meaning is invalid")
    if outcome.expected_terminal == "needs_input" and _normalized(
        card.get("source_table_meaning")
    ) != _normalized(outcome.source_table_meaning):
        failures.append("source-table meaning does not exactly bind the adverse-event outcome")
    if not _target_groups(target.get("comparison_groups"), outcome.groups):
        failures.append("target comparison groups are invalid")
    group_ids = _group_ids(target.get("comparison_groups"))
    if group_ids is None:
        failures.append("distinct valid target group IDs are invalid")
    if outcome.expected_terminal == "assessed":
        failures.extend(_check_assessed(outcome, target, population, reported, group_ids))
    else:
        failures.extend(_check_single_group(outcome, target, population, reported))
    return tuple(failures)


def _source_table_meaning(value: object, outcome: OutcomeFacts) -> bool:
    normalized = _normalized(value)
    if normalized == _normalized(outcome.source_table_meaning):
        return True
    expected = _normalized(outcome.outcome_definition)
    return expected in normalized and not any(
        f"{prefix} {expected}" in normalized for prefix in ("not", "no", "without", "unrelated to")
    )


def _check_assessed(
    outcome: OutcomeFacts,
    target: Mapping[str, object],
    population: Mapping[str, object],
    reported: Mapping[str, object],
    group_ids: tuple[str, str] | None,
) -> list[str]:
    failures: list[str] = []
    if not _assessed_coverage(population.get("outcome_measurement_coverage"), group_ids):
        failures.append("assessed outcome measurement coverage is invalid")
    if reported.get("form") != "comparative_effect":
        failures.append("assessed outcomes must be comparative effects")
    if _normalized(target.get("effect_of_interest")) != _normalized(
        f"effect on {outcome.outcome_definition}"
    ):
        failures.append("effect of interest is invalid")
    if _normalized(target.get("intended_effect_measure")) != _normalized(outcome.effect_measure):
        failures.append("intended effect measure is invalid")
    if _normalized(reported.get("effect_measure")) != _normalized(outcome.effect_measure):
        failures.append("reported effect measure is invalid")
    reported_text = reported.get("reported_text")
    if not isinstance(reported_text, str) or not reported_text.strip():
        failures.append("reported source statement is missing")
    elif _normalized(outcome.outcome_definition) not in _normalized(reported_text):
        failures.append("missing complete source-reported comparative statement")
    elif not _source_values_match(reported_text, outcome.quantities):
        failures.append("reported source statement omits an objective quantity")
    elif not _source_precision_matches(reported_text, outcome.effect_precision):
        failures.append("reported source precision does not bind structured CI/P roles")
    comparison_groups = reported.get("comparison_groups")
    if not isinstance(comparison_groups, (list, tuple)) or tuple(comparison_groups) != group_ids:
        failures.append("reported comparison groups must bind ordered target comparison groups")
    quantities = reported.get("quantities")
    if not isinstance(quantities, (list, tuple)) or len(quantities) != 2:
        failures.append("assessed outcomes require exactly two ordered group quantities")
    elif group_ids is not None:
        for actual, expected, group_id in zip(
            quantities, outcome.quantities[:2], group_ids, strict=True
        ):
            if not _quantity_matches(actual, expected, group_id):
                failures.append(f"missing objective quantity: {expected.value}")
    effect = _mapping(reported.get("effect"))
    expected_effect = outcome.quantities[2]
    effect_role = f"{group_ids[0]} vs {group_ids[1]}" if group_ids else ""
    if not _quantity_matches(effect, expected_effect, effect_role):
        failures.append(f"missing objective quantity: {expected_effect.value}")
    if not _precision_matches(reported.get("precision"), outcome.effect_precision):
        failures.append("missing objective quantity: 0.61 (reported effect precision is invalid)")
    return failures


def _check_single_group(
    outcome: OutcomeFacts,
    target: Mapping[str, object],
    population: Mapping[str, object],
    reported: Mapping[str, object],
) -> list[str]:
    failures: list[str] = []
    if reported.get("form") != "single_group_category_profile":
        failures.append("adverse events must be a single-group category profile")
    groups = target.get("comparison_groups")
    first = _mapping(groups[0]) if isinstance(groups, (list, tuple)) and groups else {}
    if _normalized(reported.get("group_id")) != _normalized(first.get("id")):
        failures.append("single-group profile does not bind the single docetaxel cohort")
    if not _single_group_coverage(population.get("outcome_measurement_coverage"), groups):
        failures.append("single-group comparator coverage is invalid")
    if reported.get("effect_measure") is not None or reported.get("derived") is not None:
        failures.append("single-group profile must not assert a comparative effect")
    categories = reported.get("categories")
    if not isinstance(categories, (list, tuple)) or len(categories) != len(outcome.quantities):
        failures.append("single-group category rows are incomplete")
    else:
        for actual, expected in zip(categories, outcome.quantities, strict=True):
            if not _quantity_matches(actual, expected, expected.group_or_category):
                failures.append(f"missing objective category row: {expected.group_or_category}")
    if isinstance(categories, (list, tuple)):
        present = {_normalized(_mapping(item).get("group_or_category")) for item in categories}
        for expected in outcome.quantities:
            if _normalized(expected.group_or_category) not in present:
                category = " ".join(expected.group_or_category.split()[:2])
                failures.append(
                    f"adverse events must retain the {category} category"
                )
    return failures


def _same_mapping_projection(card: Mapping[str, object], reported: Mapping[str, object]) -> bool:
    keys = {
        "comparative_effect": {
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "quantities",
            "comparison_groups",
            "precision",
        },
        "group_bound_values": {"form", "quantities", "comparison_groups"},
        "single_group_category_profile": {"form", "group_id", "categories"},
        "unavailable": {"form", "reason", "explanation"},
    }.get(reported.get("form"))
    return keys is not None and set(reported) == keys and all(
        card.get(key) == reported.get(key) for key in keys
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _normalized(value: object) -> str:
    return (
        " ".join(str(value).casefold().replace("+", " plus ").replace("–", "-").split())
        if isinstance(value, str)
        else ""
    )


def _target_groups(value: object, expected: tuple[str, str]) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and tuple(_normalized(_mapping(item).get("label")) for item in value)
        == tuple(_normalized(item) for item in expected)
    )


def _group_ids(value: object) -> tuple[str, str] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    ids = tuple(_mapping(item).get("id") for item in value)
    if (
        not all(
            isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item)
            for item in ids
        )
        or ids[0] == ids[1]
    ):
        return None
    return cast(tuple[str, str], ids)


def _quantity_matches(value: object, expected: Quantity, role: str) -> bool:
    actual = _mapping(value)
    return (
        set(actual) == {"statistic", "unit", "group_or_category", "value", "denominator_basis"}
        and _normalized(actual.get("statistic")) == _normalized(expected.statistic)
        and _normalized(actual.get("unit")) == _normalized(expected.unit)
        and _normalized(actual.get("group_or_category")) == _normalized(role)
        and _same_quantity_value(actual.get("value"), expected.value)
        and _normalized(actual.get("denominator_basis")) == _normalized(expected.denominator_basis)
    )


def _precision_matches(value: object, expected: EffectPrecision | None) -> bool:
    if expected is None:
        return value is None
    precision = _mapping(value)
    interval, p_value = (
        _mapping(precision.get("confidence_interval")),
        _mapping(precision.get("p_value")),
    )
    return (
        set(precision) == {"confidence_interval", "p_value"}
        and set(interval) == {"level", "lower", "upper"}
        and set(p_value) == {"operator", "value"}
        and _same_number(interval.get("level"), expected.confidence_level)
        and _same_number(interval.get("lower"), expected.lower)
        and _same_number(interval.get("upper"), expected.upper)
        and p_value.get("operator") == expected.p_operator
        and _same_number(p_value.get("value"), expected.p_value)
    )


def _number_tokens(value: str) -> tuple[tuple[int, int, str], ...]:
    tokens: list[tuple[int, int, str]] = []
    index = 0
    while index < len(value):
        if not (
            value[index].isdigit()
            or (
                value[index] == "."
                and index + 1 < len(value)
                and value[index + 1].isdigit()
            )
        ):
            index += 1
            continue
        start = index
        if start and value[start - 1] in "+-" and (start == 1 or not value[start - 2].isalnum()):
            start -= 1
        index = start + 1
        while index < len(value) and value[index] in "0123456789.eE+-":
            index += 1
        token = value[start:index]
        try:
            Decimal(token)
        except InvalidOperation:
            index = max(index, start + 1)
        else:
            tokens.append((start, index, token))
    return tuple(tokens)


def _source_p_value_matches(value: str, operator: str, expected_value: str) -> bool:
    for index, character in enumerate(value):
        if character != "p" or (index and value[index - 1].isalnum()):
            continue
        cursor = index + 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if not value.startswith(operator, cursor):
            continue
        cursor += len(operator)
        if operator in {"<", ">"} and cursor < len(value) and value[cursor] == "=":
            continue
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        candidates = _number_tokens(value[cursor:])
        if not candidates or candidates[0][0] != 0:
            continue
        end = cursor + candidates[0][1]
        if end < len(value) and (value[end].isalnum() or value[end] == "."):
            continue
        if _same_number(candidates[0][2], expected_value):
            return True
    return False


def _source_precision_matches(value: object, expected: EffectPrecision | None) -> bool:
    if expected is None:
        return True
    if not isinstance(value, str):
        return False
    text = _normalized(value)
    marker = next(
        (
            index
            for index in range(len(text) - 1)
            if text[index : index + 2] == "ci"
            and (index == 0 or not text[index - 1].isalnum())
            and (index + 2 == len(text) or not text[index + 2].isalnum())
        ),
        -1,
    )
    if marker < 0:
        return False
    numbers = _number_tokens(text)
    level = next(
        (
            token
            for token in numbers
            if token[1] <= marker
            and "%" in text[token[1] : marker]
            and _same_number(token[2], expected.confidence_level)
        ),
        None,
    )
    if level is None:
        return False
    after = [token for token in numbers if token[0] >= marker + 2]
    pair = next(
        (
            (lower, upper)
            for lower, upper in zip(after, after[1:])
            if "to" in text[lower[1] : upper[0]]
            and _same_number(lower[2], expected.lower)
            and _same_number(upper[2], expected.upper)
        ),
        None,
    )
    if pair is None:
        return False
    return _source_p_value_matches(text, expected.p_operator, expected.p_value)


def _source_values_match(value: str, expected: tuple[Quantity, ...]) -> bool:
    tokens = tuple(token for _start, _end, token in _number_tokens(_normalized(value)))
    return all(
        any(_same_number(token, quantity.value) for token in tokens) for quantity in expected
    )


def _single_group_coverage(value: object, groups: object) -> bool:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not isinstance(groups, (list, tuple))
        or len(groups) != 2
    ):
        return False
    rows = {_mapping(row).get("group_id"): _mapping(row).get("status") for row in value}
    ids = (_mapping(groups[0]).get("id"), _mapping(groups[1]).get("id"))
    return rows == {ids[0]: "measured", ids[1]: "not_measured"}


def _assessed_coverage(value: object, group_ids: tuple[str, str] | None) -> bool:
    if group_ids is None or not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    rows: list[Mapping[str, object]] = []
    for item in value:
        row = _mapping(item)
        if (
            set(row) != {"group_id", "status", "explanation"}
            or not isinstance(row.get("group_id"), str)
            or row.get("status") != "measured"
            or (row.get("explanation") is not None and not isinstance(row.get("explanation"), str))
        ):
            return False
        rows.append(row)
    ids = [row["group_id"] for row in rows]
    return len(set(ids)) == 2 and set(ids) == set(group_ids)


def _same_number(value: object, expected: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        return False
    try:
        return Decimal(str(value)) == Decimal(expected)
    except InvalidOperation:
        return False


def _same_quantity_value(value: object, expected: str) -> bool:
    try:
        Decimal(expected)
    except InvalidOperation:
        return _normalized(value) == _normalized(expected)
    return _same_number(value, expected)
