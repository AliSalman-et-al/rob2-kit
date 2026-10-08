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


@pytest.mark.parametrize("counts", [{"observed": 100}, {"unavailable": 5}])
def test_context_withholds_arithmetic_inconsistent_with_selected_outcome_imputation(counts) -> None:
    import copy

    from rob2_kit.application.missing_data import missing_data_context
    from rob2_kit.packs import SCIENTIFIC_PACK

    official = next(q for q in SCIENTIFIC_PACK.questions if q.id == "sq:missing:data-available")
    assert "imputed" in official.guidance.official.source_excerpt.lower()
    canonical = reconcile_missing_data([_scoped_imputation_row(**counts)])
    before = copy.deepcopy(canonical)
    context = missing_data_context(canonical)
    row = context["rows"][0]
    assert row["quantity_conflict"] and "question 3.1" in row["quantity_conflict"]
    assert row["missing"] is row["missing_fraction"] is row["missing_bounds"] is None
    assert row["imputed"] == 10 and row["analyzed"] == 100
    assert row["basis"] == before["rows"][0]["basis"]
    assert canonical == before
    MissingDataReconciliation.model_validate(context)
    assert "answer" not in row and "judgment" not in row


@pytest.mark.parametrize("observed", [90, None])
def test_coherent_imputation_keeps_exact_or_bounded_arithmetic(observed) -> None:
    from rob2_kit.application.missing_data import missing_data_context

    canonical = reconcile_missing_data([_scoped_imputation_row(observed=observed)])
    assert missing_data_context(canonical) == canonical
    assert canonical["rows"][0]["missing_bounds"]["lower"] == 10


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


def test_context_does_not_transfer_imputation_between_row_scopes() -> None:
    from rob2_kit.application.missing_data import missing_data_context

    first = _scoped_imputation_row(observed=100, imputed=None)
    second = _scoped_imputation_row(observed=90) | {
        "time_point": "week 4",
        "window": "week 4",
        "endpoint": "another endpoint",
    }
    canonical = reconcile_missing_data([first, second])
    assert missing_data_context(canonical) == canonical


def test_context_withholds_conflicted_reports_arithmetic_without_editing_facts() -> None:
    from rob2_kit.application.missing_data import missing_data_context

    canonical = reconcile_missing_data(
        [
            _scoped_imputation_row(observed=100),
            _scoped_imputation_row(observed=100, imputed=12),
        ]
    )
    context = missing_data_context(canonical)
    assert len(context["conflicts"]) == 1
    reports = context["conflicts"][0]["reports"]
    assert [row["imputed"] for row in reports] == [10, 12]
    assert all(row["quantity_conflict"] and row["missing"] is None for row in reports)
    assert all(row["missing"] == 0 for row in canonical["conflicts"][0]["reports"])
    MissingDataReconciliation.model_validate(context)
