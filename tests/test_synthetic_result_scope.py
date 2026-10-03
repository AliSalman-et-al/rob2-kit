"""Check synthetic specimen identity and factual consistency, not desired judgments."""

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rob2_kit.workflow_models import ComparativeEffectResult, ResultTarget

_ROOT = Path(__file__).parents[1] / "docs/evaluation/2026-10-03-d27-synthetic-scope-correction"
_SPECIMENS = json.loads((_ROOT / "specimens.json").read_text())["scenarios"]


@pytest.mark.parametrize("specimen", _SPECIMENS, ids=[s["scenario_id"] for s in _SPECIMENS])
def test_specimen_names_one_complete_reported_result(specimen: dict[str, Any]) -> None:
    target = ResultTarget.model_validate(specimen["target"])
    reported = ComparativeEffectResult.model_validate(specimen["reported"])
    assert target.effect_of_interest == "assignment"
    assert reported.analysis_population == specimen["actual_analysis"]["population_description"]
    assert specimen["reported_time_point_or_window"] == specimen["target"]["time_point_or_window"]
    ids = [specimen["assessed_result_id"]] + [
        alternative["result_id"] for alternative in specimen["alternative_results"]
    ]
    assert len(ids) == len(set(ids))
    for alternative in specimen["alternative_results"]:
        assert alternative["role"] == "sensitivity_evidence_only"
        ComparativeEffectResult.model_validate(alternative["reported"])
    values = {value.group_id: Decimal(value.value) for value in reported.group_values}
    if values:
        assert set(values) == {group.id for group in target.comparison_groups}
        assert values["active"] - values["placebo"] == Decimal(reported.estimate)
    assert reported.precision is not None
    lower, upper = reported.precision.split(",", 1)[1].split("to")
    assert Decimal(lower) <= Decimal(reported.estimate) <= Decimal(upper)
    for group in target.comparison_groups:
        analyzed = specimen["actual_analysis"]["analyzed_by_group"][group.id]
        measured = specimen["actual_analysis"]["measured_at_endpoint_by_group"][group.id]
        if analyzed is not None:
            assert measured is not None
            assert 0 <= analyzed <= measured <= 100
        else:
            assert measured is None
            assert "not reported" in reported.analysis_population.lower()


def test_missing_population_is_not_accepted_as_complete_reported_specimen() -> None:
    broken = copy.deepcopy(_SPECIMENS[0]["reported"])
    del broken["analysis_population"]
    with pytest.raises(ValidationError):
        ComparativeEffectResult.model_validate(broken)


def test_corrected_pair_has_identical_scope_and_no_private_answers() -> None:
    packets = [(_ROOT / f"{arm}-input.txt").read_text() for arm in ("baseline", "current")]
    before, after = [json.loads(packet.splitlines()[1]) for packet in packets]
    assert before["specimens"] == after["specimens"]
    assert (
        packets[0].split("SOURCE synthetic:", 1)[1] == packets[1].split("SOURCE synthetic:", 1)[1]
    )
    assert packets[0].splitlines()[0] == packets[1].splitlines()[0]
    assert before["questions"][0] == after["questions"][0]
    assert before["questions"][1]["operational_guidance"].pop("considerations") != after[
        "questions"
    ][1]["operational_guidance"].pop("considerations")
    assert before["questions"] == after["questions"]
    for specimen in before["specimens"]:
        assert not {"expected_answer", "judgment", "risk", "review", "gold_label"} & specimen.keys()
