from __future__ import annotations

import pytest
from pydantic import ValidationError

from rob2_kit.application.domains import reconcile_missing_data as reconcile_domain_missing_data
from rob2_kit.application.missing_data import normalize_missing_data, reconcile_missing_data
from rob2_kit.interfaces.mcp.contracts import MissingDataReconciliation
from rob2_kit.workflow_models import MissingDataRow, MissingDataSemantics


def test_legacy_row_keeps_explicit_observed_arithmetic() -> None:
    result = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "ITT",
                "unit": "participants",
                "time_point": "12m",
                "randomized": 10,
                "observed": 8,
            }
        ]
    )

    assert result["rows"][0]["missing"] == 2
    assert "semantics" not in result["rows"][0]


def test_event_count_does_not_become_outcome_availability() -> None:
    result = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "safety",
                "unit": "participants",
                "time_point": "12m",
                "randomized": 10,
                "analyzed": 9,
                "semantics": {
                    "population_role": "safety",
                    "event_count": 2,
                    "event_definition": "grade 3 or higher adverse event",
                },
            }
        ]
    )

    row = result["rows"][0]
    assert row["missing"] is None
    assert row["observed"] is None
    assert row["semantics"]["event_count"] == 2


def test_typed_semantics_round_trip() -> None:
    row = MissingDataRow(
        arm="A",
        population="ITT",
        unit="participants",
        time_point="12m",
        semantics=MissingDataSemantics(
            population_role="analyzed",
            outcome_status="unknown",
            post_randomization_exclusions=("withdrawal",),
            censoring={"kind": "administrative", "timing": "common cutoff"},
        ),
    )

    restored = MissingDataRow.model_validate(row.model_dump(mode="json"))
    assert restored.semantics == row.semantics


@pytest.mark.parametrize(
    "payload",
    [
        {"event_count": 2},
        {"population_role": "not-a-population"},
        {"censoring": {"kind": "not-a-kind"}},
    ],
)
def test_invalid_semantics_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MissingDataSemantics.model_validate(payload)


def test_event_definition_can_describe_the_outcome_without_an_event_count() -> None:
    semantics = MissingDataSemantics.model_validate({"event_definition": "death from any cause"})

    assert semantics.event_count is None
    assert semantics.event_definition == "death from any cause"


def test_normalization_accepts_typed_row() -> None:
    row = MissingDataRow(
        arm="A", population="ITT", unit="participants", time_point="12m", observed=10
    )
    assert normalize_missing_data(row)["observed"] == 10


def test_domain_reconciliation_uses_typed_semantics_and_public_contract() -> None:
    result = reconcile_domain_missing_data(
        [
            {
                "arm": "A",
                "population": "safety",
                "unit": "participants",
                "time_point": "12m",
                "randomized": 10,
                "observed": 9,
                "basis": ["sha256:" + "1" * 64],
                "semantics": {
                    "population_role": "safety",
                    "event_count": 2,
                    "event_definition": "grade 3 or higher adverse event",
                },
            }
        ]
    )

    parsed = MissingDataReconciliation.model_validate(result)
    row = parsed.rows[0]
    assert row.missing == 1
    assert row.semantics is not None
    assert row.semantics.event_count == 2
