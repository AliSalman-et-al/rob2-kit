"""Expose caller-owned scope assertions without inferring meaning from wording."""

from typing import Any

from ..workflow_models import AssessableResult, ResultScopeReview
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
                target=result.target,
                reported_endpoint=result.reported.endpoint,
                reported_analysis_population=result.reported.analysis_population,
                source_bound_reported_fields=tuple(item.field.path for item in result.bindings),
                caller_declared_clarity=result.clarity,
            ).model_dump(mode="json")
        )
    return reviews
