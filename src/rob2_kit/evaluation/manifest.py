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

    failures: list[str] = []
    text = json.dumps(reported, sort_keys=True).casefold()
    for required in (
        outcome.outcome_definition,
        outcome.measurement,
        outcome.time_point,
        outcome.intended_population,
        outcome.source_table_meaning,
    ):
        if required.casefold() not in text:
            failures.append(f"missing objective fact: {required}")
    for quantity in outcome.quantities:
        if quantity.value.casefold() not in text:
            failures.append(f"missing objective quantity: {quantity.value}")
    if outcome.effect_measure and outcome.effect_measure.casefold() not in text:
        failures.append(f"missing objective effect measure: {outcome.effect_measure}")
    if outcome.key == "adverse_events":
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
