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


@pytest.mark.parametrize(
    ("observed", "missing"),
    [(50, 0), (40, 10), (None, None)],
)
def test_analysis_exclusion_does_not_determine_observation(
    observed: int | None, missing: int | None
) -> None:
    # The same outcome-linked analysis restriction can coexist with observed,
    # unobserved or unknown endpoint measurements. No label follows from counts.
    facts = {
        "arm": "active",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "endpoint visit",
        "randomized": 50,
        "analyzed": 40,
        "excluded": 10,
        "exclusions": ["post-change values omitted; collection was scheduled"],
    }
    if observed is not None:
        facts["observed"] = observed
    result = reconcile_missing_data([facts])
    row = result["rows"][0]
    assert row["observed"] == observed
    assert row["analyzed"] == 40 and row["excluded"] == 10
    assert row["missing"] == missing
    if observed is None:
        assert row["missing_bounds"]["lower"] == 0
        assert row["missing_bounds"]["upper"] == 50
    assert "judgment" not in result


@pytest.mark.parametrize(
    ("facts", "missing"),
    [
        ({"observed": 100, "completed": 80}, 0),
        ({"observed": 80, "analyzed": 100, "imputed": 20, "completed": 90}, 20),
        ({"completed": 100, "analyzed": 100}, None),
        ({"completed": 90, "imputed": 10}, None),
    ],
    ids=[
        "complete-outcomes",
        "complete-analysis-missing-outcomes",
        "completion-proxy",
        "unknown-overlap",
    ],
)
def test_completion_never_substitutes_for_endpoint_availability(
    facts: dict[str, int], missing: int | None
) -> None:
    rows = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "randomized",
                "unit": "participants",
                "time_point": "endpoint visit",
                "randomized": 100,
                **facts,
            }
        ]
    )
    row = rows["rows"][0]
    assert row["completed"] == facts["completed"]
    assert row["observed"] == facts.get("observed")
    assert row["missing"] == missing
    if missing is None:
        assert row["missing_bounds"]["upper"] == 100
        assert row["missing_bounds"]["lower"] == facts.get("imputed", 0)
    assert "judgment" not in rows


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
