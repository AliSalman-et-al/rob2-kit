"""Expose caller-owned scope assertions without inferring meaning from wording."""

from typing import Any

from ..workflow_models import (
    AssessableResult,
    ResultScopeReview,
    ScopeEndpointSummary,
    ScopeTargetSummary,
)
from ._state import _identity


def result_scope_review(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for raw in results:
        if raw.get("kind") != "assessable":
            continue
        result = AssessableResult.model_validate(raw)
        reviews.append(
            ResultScopeReview(
                trial_id=result.trial_id,
                result_identity=_identity(raw),
                claimed_relation=result.relation,
                relation_rationale=result.relation_rationale,
                target=ScopeTargetSummary(
                    outcome=result.target.outcome_definition,
                    measurement=result.target.measurement.method,
                    window=result.target.time_point_or_window.description,
                    population=result.target.intended_analysis_population,
                    effect_measure=result.target.intended_effect_measure,
                    comparison=tuple(group.assignment for group in result.target.comparison_groups),
                ),
                reported_endpoint=ScopeEndpointSummary(**result.reported.endpoint.model_dump()),
                reported_analysis_population=result.reported.analysis_population,
                source_bound_reported_fields=tuple(item.field.path for item in result.bindings),
                caller_declared_clarity=result.clarity,
            ).model_dump(mode="json")
        )
    return reviews
