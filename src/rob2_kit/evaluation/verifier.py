"""Bounded, model-agnostic blinded-verifier experiment.

This module is evaluation infrastructure.  It neither calls a model nor changes
the authoritative single-assessor workflow.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel

Judgment = Literal["low", "some_concerns", "high"]


class TriggerFacts(FrozenModel):
    """Server-computable facts considered by verifier trigger policy v1."""

    valid_no_information: bool = False
    pivotal_source_conflict: bool = False
    pivotal_probabilistic_inference_with_counter_evidence: bool = False
    pivotal_visual_or_derived_dependence: bool = False
    discrepancy_hotspot_policy: str | None = Field(default=None, pattern=r"^hotspots:[1-9][0-9]*$")
    discrepancy_hotspot: bool = False

    # Recorded inputs that are intentionally never trigger reasons.
    raw_confidence_low: bool = False
    adverse_judgment: bool = False
    domain_number: int | None = None
    mere_missing_evidence: bool = False
    deterministic_validation_failure: bool = False

    def eligible_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.valid_no_information:
            reasons.append("valid_no_information")
        if self.pivotal_source_conflict:
            reasons.append("pivotal_source_conflict")
        if self.pivotal_probabilistic_inference_with_counter_evidence:
            reasons.append("pivotal_probabilistic_inference_with_counter_evidence")
        if self.pivotal_visual_or_derived_dependence:
            reasons.append("pivotal_visual_or_derived_dependence")
        if self.discrepancy_hotspot and self.discrepancy_hotspot_policy:
            reasons.append("versioned_discrepancy_hotspot")
        return tuple(reasons)


class BlindedVerifierContext(FrozenModel):
    """Initial verifier input, structurally unable to carry the primary decision."""

    frozen_scope: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    guidance: Mapping[str, Any]
    decision_need: str = Field(min_length=1)


class VerifierReply(FrozenModel):
    judgment: Judgment
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)


class ReconsiderationRequest(FrozenModel):
    """One evidence-linked disagreement package, disclosed only after blinding."""

    initial_reply: VerifierReply
    primary_judgment: Judgment
    primary_rationale: str
    counter_evidence_ids: tuple[str, ...]


class VerifierMetrics(FrozenModel):
    disagreement_type: Literal["none", "judgment", "unlinked"] = "none"
    judgment_impact: Literal["none", "material"] = "none"
    evidence_effect: Literal["none", "cited_counter_evidence", "unlinked"] = "none"
    extra_calls: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    repair_turns: int = Field(default=0, ge=0, le=1)


class VerifierEvaluation(FrozenModel):
    policy_version: str = "blinded-verifier-experiment:1"
    trigger_reasons: tuple[str, ...]
    outcome: Literal[
        "baseline_only", "verification_unavailable", "agreement", "diagnostic_result"
    ]
    baseline_judgment: Judgment
    verifier_judgment: Judgment | None = None
    metrics: VerifierMetrics
    independent_human_assessor: bool = False


class VerifierModeComparison(FrozenModel):
    without_verifier: VerifierEvaluation
    with_verifier: VerifierEvaluation


class VerifierReplayFixture(FrozenModel):
    schema_version: int = 1
    context: BlindedVerifierContext
    triggers: TriggerFacts
    baseline_judgment: Judgment
    verifier_replies: tuple[VerifierReply, ...]


class VerifierUnavailable(RuntimeError):
    """Isolated verifier execution is unavailable or interrupted."""


Verifier = Callable[
    [BlindedVerifierContext, ReconsiderationRequest | None], VerifierReply
]


def evaluate_blinded_verifier(
    *,
    context: BlindedVerifierContext,
    triggers: TriggerFacts,
    baseline_judgment: Judgment,
    baseline_rationale: str = "",
    verifier: Verifier | None,
) -> VerifierEvaluation:
    """Evaluate one fresh verifier and at most one evidence-linked reconsideration."""

    reasons = triggers.eligible_reasons()
    if not reasons:
        return _baseline(baseline_judgment, reasons)
    if verifier is None:
        return VerifierEvaluation(
            trigger_reasons=reasons,
            outcome="verification_unavailable",
            baseline_judgment=baseline_judgment,
            metrics=VerifierMetrics(failures=1),
        )

    replies: list[VerifierReply] = []
    attempted_calls = 0
    try:
        attempted_calls += 1
        first = verifier(_isolated_copy(context), None)
        replies.append(first)
        if first.judgment == baseline_judgment:
            return _completed(baseline_judgment, reasons, replies, "agreement")
        linked_ids = _linked_evidence_ids(context, first)
        sanitized_first = first.model_copy(update={"evidence_ids": linked_ids})
        replies[0] = sanitized_first
        if linked_ids:
            request = ReconsiderationRequest(
                initial_reply=sanitized_first,
                primary_judgment=baseline_judgment,
                primary_rationale=baseline_rationale,
                counter_evidence_ids=linked_ids,
            )
            attempted_calls += 1
            replies.append(verifier(_isolated_copy(context), request))
    except (VerifierUnavailable, TimeoutError, ConnectionError):
        return VerifierEvaluation(
            trigger_reasons=reasons,
            outcome="verification_unavailable",
            baseline_judgment=baseline_judgment,
            verifier_judgment=replies[-1].judgment if replies else None,
            metrics=_metrics(
                replies,
                baseline=baseline_judgment,
                failures=1,
                attempted_calls=attempted_calls,
                repair_attempted=attempted_calls == 2,
            ),
        )

    if replies[-1].judgment == baseline_judgment:
        return _completed(baseline_judgment, reasons, replies, "agreement")
    return _completed(baseline_judgment, reasons, replies, "diagnostic_result")


def compare_verifier_modes(
    *,
    context: BlindedVerifierContext,
    triggers: TriggerFacts,
    baseline_judgment: Judgment,
    baseline_rationale: str = "",
    verifier: Verifier | None,
) -> VerifierModeComparison:
    """Return stable present/absent records for public replay and owner evaluation."""

    return VerifierModeComparison(
        without_verifier=_baseline(baseline_judgment, triggers.eligible_reasons()),
        with_verifier=evaluate_blinded_verifier(
            context=context,
            triggers=triggers,
            baseline_judgment=baseline_judgment,
            baseline_rationale=baseline_rationale,
            verifier=verifier,
        ),
    )


def replay_verifier_fixture(path: Path) -> VerifierModeComparison:
    """Replay a checked-in fake without network access or commercial model calls."""

    fixture = VerifierReplayFixture.model_validate_json(path.read_text(encoding="utf-8"))
    replies = iter(fixture.verifier_replies)

    def fake(
        context: BlindedVerifierContext, prior: ReconsiderationRequest | None
    ) -> VerifierReply:
        del context, prior
        try:
            return next(replies)
        except StopIteration as error:
            raise ValueError("fixture exhausted its verifier replies") from error

    return compare_verifier_modes(
        context=fixture.context,
        triggers=fixture.triggers,
        baseline_judgment=fixture.baseline_judgment,
        verifier=fake,
    )


def _baseline(judgment: Judgment, reasons: tuple[str, ...]) -> VerifierEvaluation:
    return VerifierEvaluation(
        trigger_reasons=reasons,
        outcome="baseline_only",
        baseline_judgment=judgment,
        metrics=VerifierMetrics(),
    )


def _completed(
    baseline: Judgment,
    reasons: tuple[str, ...],
    replies: list[VerifierReply],
    outcome: Literal["agreement", "diagnostic_result"],
) -> VerifierEvaluation:
    return VerifierEvaluation(
        trigger_reasons=reasons,
        outcome=outcome,
        baseline_judgment=baseline,
        verifier_judgment=replies[-1].judgment,
        metrics=_metrics(replies, baseline=baseline),
    )


def _metrics(
    replies: list[VerifierReply],
    *,
    baseline: Judgment | None = None,
    failures: int = 0,
    attempted_calls: int | None = None,
    repair_attempted: bool | None = None,
) -> VerifierMetrics:
    # Preserve the initiating disagreement even when reconsideration resolves it.
    disagreement = bool(
        replies and baseline is not None and any(reply.judgment != baseline for reply in replies)
    )
    linked = bool(disagreement and replies[0].evidence_ids)
    return VerifierMetrics(
        disagreement_type=(
            "judgment" if disagreement and linked else "unlinked" if disagreement else "none"
        ),
        judgment_impact="material" if disagreement else "none",
        evidence_effect=(
            "cited_counter_evidence" if linked else "unlinked" if disagreement else "none"
        ),
        extra_calls=attempted_calls if attempted_calls is not None else len(replies),
        total_tokens=sum(reply.input_tokens + reply.output_tokens for reply in replies),
        latency_ms=sum(reply.latency_ms for reply in replies),
        failures=failures,
        repair_turns=(
            int(repair_attempted) if repair_attempted is not None else int(len(replies) == 2)
        ),
    )


def _linked_evidence_ids(
    context: BlindedVerifierContext, reply: VerifierReply
) -> tuple[str, ...]:
    available = {
        str(item["claim_id"])
        for item in context.evidence
        if isinstance(item.get("claim_id"), str)
    }
    return tuple(identity for identity in reply.evidence_ids if identity in available)


def _isolated_copy(context: BlindedVerifierContext) -> BlindedVerifierContext:
    """Prevent callback mutation from altering replay input or a later call."""

    return BlindedVerifierContext.model_validate_json(context.model_dump_json())


__all__ = [
    "BlindedVerifierContext",
    "Judgment",
    "ReconsiderationRequest",
    "TriggerFacts",
    "VerifierEvaluation",
    "VerifierMetrics",
    "VerifierModeComparison",
    "VerifierReply",
    "VerifierUnavailable",
    "compare_verifier_modes",
    "evaluate_blinded_verifier",
    "replay_verifier_fixture",
]
