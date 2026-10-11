from __future__ import annotations

import pytest
from pydantic import ValidationError

from rob2_kit.application.missing_data import normalize_missing_data, reconcile_missing_data
from rob2_kit.workflow_models import MissingDataRow, MissingDataSemantics


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


def test_normalization_accepts_typed_row() -> None:
    row = MissingDataRow(
        arm="A", population="ITT", unit="participants", time_point="12m", observed=10
    )
    assert normalize_missing_data(row)["observed"] == 10


def test_completion_conflicts_survive_canonical_bundle_validation() -> None:
    from rob2_kit.application.finalization import _valid_missing_data
    from scripts.verify_bundle import _valid_missing_data as independent_verifier

    result_id = "sha256:" + "a" * 64
    evidence_id = "sha256:" + "b" * 64
    row = {
        "arm": "A",
        "population": "randomized",
        "unit": "participants",
        "time_point": "12m",
        "randomized": 100,
        "completed": 90,
        "result_identity": result_id,
        "basis": [evidence_id],
    }
    data = reconcile_missing_data([row, row | {"completed": 85}])
    assert len(data["conflicts"]) == 1
    assert all(r["observed"] is None and r["missing"] is None for r in data["rows"])
    assert _valid_missing_data(
        data, "sq:missing:data-available", {evidence_id: {"trial_id": "trial"}}, "trial", result_id
    )
    assert independent_verifier(
        data, "sq:missing:data-available", {evidence_id: {"trial_id": "trial"}}, "trial", result_id
    )
    data["conflicts"] = []
    assert not _valid_missing_data(
        data, "sq:missing:data-available", {evidence_id: {"trial_id": "trial"}}, "trial", result_id
    )
    assert not independent_verifier(
        data, "sq:missing:data-available", {evidence_id: {"trial_id": "trial"}}, "trial", result_id
    )


def _scoped_imputation_row(**counts: int | None) -> dict:
    return {
        "arm": "A",
        "population": "all randomized participants",
        "unit": "participants",
        "time_point": "week 8",
        "window": "week 8",
        "endpoint": "selected endpoint",
        "result_identity": "sha256:" + "a" * 64,
        "basis": ["sha256:" + "b" * 64],
        "randomized": 100,
        "analyzed": 100,
        "imputed": 10,
        "semantics": {"population_role": "randomized", "outcome_status": "imputed"},
        **counts,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"imputed": None},  # A method mention without a count establishes no lower bound.
        {"semantics": {"population_role": "randomized", "outcome_status": "unknown"}},
        {"semantics": {"population_role": "analyzed", "outcome_status": "imputed"}},
        {"window": "another visit"},
        {"endpoint": None},
        {"unit": "components"},
        {
            "event_definition": "final composite",
            "semantics": {
                "population_role": "randomized",
                "outcome_status": "imputed",
                "event_definition": "one component",
            },
        },
    ],
)
def test_context_does_not_resolve_unknown_or_different_imputation_meaning(change) -> None:
    from rob2_kit.application.missing_data import missing_data_context

    canonical = reconcile_missing_data([_scoped_imputation_row(observed=100) | change])
    assert missing_data_context(canonical) == canonical
