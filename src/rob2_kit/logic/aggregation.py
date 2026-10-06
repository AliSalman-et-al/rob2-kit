"""Versioned result-specific overall aggregation; historical records are immutable."""

from typing import Any

from ..models import Judgment, OverallEvaluation
from ..workflow_models import CumulativeConcernsAssessment
from .evaluator import evaluate_historical_overall, evaluate_overall

AGGREGATION_CONTRACT = "rob2-kit.overall.cochrane-conditional.v1"
LEGACY_AGGREGATION_CONTRACT = "rob2-kit.overall.count-policy.v1"


def aggregation_record(
    snapshot: dict[str, Any], assessment: CumulativeConcernsAssessment | None = None
) -> tuple[dict[str, Any], OverallEvaluation]:
    proposed = evaluate_overall(snapshot["domain_judgments"])
    evaluation = proposed
    if assessment is not None:
        if (
            assessment.result_identity != snapshot["result_identity"]
            or list(assessment.checkpoints) != snapshot["checkpoints"]
        ):
            raise ValueError(
                "cumulative concerns must bind the exact current Result and checkpoints"
            )
        if proposed.judgment is not Judgment.SOME_CONCERNS or len(proposed.driver_domains) < 2:
            raise ValueError(
                "cumulative concerns require multiple Some concerns and no High Domain"
            )
        if assessment.conclusion == "substantially_lowers_confidence":
            evaluation = OverallEvaluation(
                judgment=Judgment.HIGH,
                trace=("overall.cumulative_concerns_high",),
                driver_domains=proposed.driver_domains,
            )
    return {
        "contract": AGGREGATION_CONTRACT,
        "proposed": proposed.judgment.value,
        "adopted": evaluation.judgment.value,
        "rule": evaluation.trace[0],
        "assessment_status": "omitted" if assessment is None else assessment.conclusion,
        "assessment": None if assessment is None else assessment.model_dump(mode="json"),
        "authority": "algorithm" if assessment is None else "host",
    }, evaluation


def snapshot_evaluation(snapshot: dict[str, Any]) -> OverallEvaluation:
    """Validate provenance before evaluating a frozen snapshot."""
    record = snapshot.get("aggregation")
    if "aggregation" not in snapshot:
        return evaluate_historical_overall(snapshot["domain_judgments"])
    if not isinstance(record, dict) or record.get("contract") != AGGREGATION_CONTRACT:
        raise ValueError("unknown aggregation contract")
    assessment = (
        CumulativeConcernsAssessment.model_validate(record["assessment"])
        if record.get("assessment") is not None
        else None
    )
    expected, evaluation = aggregation_record(snapshot, assessment)
    if record != expected:
        raise ValueError("aggregation provenance does not match the bound assessment")
    return evaluation
