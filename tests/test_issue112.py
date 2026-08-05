from typing import Any, cast

import pytest
from pydantic import ValidationError

from rob2_kit.evaluation.verifier import (
    BlindedVerifierContext,
    ReconsiderationRequest,
    TriggerFacts,
    VerifierReply,
    compare_verifier_modes,
    evaluate_blinded_verifier,
    replay_verifier_fixture,
)


def _context() -> BlindedVerifierContext:
    return BlindedVerifierContext(
        frozen_scope={"result_id": "result:aurora"},
        evidence=({"claim_id": "claim:registry", "text": "Allocation was concealed."},),
        guidance={"pack": "guidance:rob2-2019.1"},
        decision_need="Was allocation concealed?",
    )


def test_only_server_computable_pivotal_facts_trigger() -> None:
    eligible = (
        TriggerFacts(valid_no_information=True),
        TriggerFacts(pivotal_source_conflict=True),
        TriggerFacts(pivotal_probabilistic_inference_with_counter_evidence=True),
        TriggerFacts(pivotal_visual_or_derived_dependence=True),
        TriggerFacts(discrepancy_hotspot_policy="hotspots:1", discrepancy_hotspot=True),
    )
    assert all(facts.eligible_reasons() for facts in eligible)
    assert not TriggerFacts(
        raw_confidence_low=True,
        adverse_judgment=True,
        domain_number=3,
        mere_missing_evidence=True,
        deterministic_validation_failure=True,
        discrepancy_hotspot=True,
    ).eligible_reasons()
    with pytest.raises(ValidationError):
        TriggerFacts(discrepancy_hotspot_policy="unversioned", discrepancy_hotspot=True)


def test_blinded_disagreement_gets_one_evidence_linked_reconsideration_then_diagnostic() -> None:
    seen: list[tuple[BlindedVerifierContext, ReconsiderationRequest | None]] = []

    def verifier(
        context: BlindedVerifierContext, prior: ReconsiderationRequest | None
    ) -> VerifierReply:
        seen.append((context, prior))
        if prior is None:
            return VerifierReply(
                judgment="high", rationale="Registry conflicts.", evidence_ids=("claim:registry",)
            )
        return VerifierReply(
            judgment="high", rationale="Still conflicts.", evidence_ids=("claim:registry",)
        )

    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )

    assert len(seen) == 2
    assert seen[0][1] is None
    assert seen[1][1] is not None
    assert seen[1][1].primary_judgment == "low"
    assert seen[1][1].counter_evidence_ids == ("claim:registry",)
    assert not hasattr(seen[0][0], "primary_answer")
    assert result.outcome == "diagnostic_result"
    assert result.baseline_judgment == "low"
    assert result.metrics.extra_calls == 2
    assert result.metrics.repair_turns == 1
    assert result.metrics.disagreement_type == "judgment"
    assert result.metrics.judgment_impact == "material"
    assert result.metrics.evidence_effect == "cited_counter_evidence"


def test_unavailable_is_recorded_and_baseline_is_preserved() -> None:
    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(valid_no_information=True),
        baseline_judgment="some_concerns",
        verifier=None,
    )
    assert result.outcome == "verification_unavailable"
    assert result.baseline_judgment == "some_concerns"
    assert result.metrics.failures == 1


def test_failed_reconsideration_records_the_attempt_and_preserves_baseline() -> None:
    calls = 0

    def verifier(
        context: BlindedVerifierContext, request: ReconsiderationRequest | None
    ) -> VerifierReply:
        nonlocal calls
        calls += 1
        if request is not None:
            raise TimeoutError("isolated executor timed out")
        return VerifierReply(
            judgment="high", rationale="Conflict.", evidence_ids=("claim:registry",)
        )

    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )
    assert result.outcome == "verification_unavailable"
    assert result.baseline_judgment == "low"
    assert result.metrics.extra_calls == 2
    assert result.metrics.repair_turns == 1
    assert result.metrics.failures == 1


def test_reconsideration_can_resolve_disagreement_without_replacing_baseline() -> None:
    replies = iter(
        (
            VerifierReply(
                judgment="high", rationale="Conflict.", evidence_ids=("claim:registry",)
            ),
            VerifierReply(
                judgment="low", rationale="Resolved.", evidence_ids=("claim:registry",)
            ),
        )
    )
    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=lambda context, request: next(replies),
    )
    assert result.outcome == "agreement"
    assert result.baseline_judgment == "low"
    assert result.metrics.disagreement_type == "judgment"
    assert result.metrics.judgment_impact == "material"
    assert result.metrics.repair_turns == 1


def test_unlinked_disagreement_cannot_start_reconsideration() -> None:
    calls = 0

    def verifier(
        context: BlindedVerifierContext, prior: ReconsiderationRequest | None
    ) -> VerifierReply:
        nonlocal calls
        calls += 1
        return VerifierReply(judgment="high", rationale="Unsupported disagreement.")

    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )
    assert calls == 1
    assert result.outcome == "diagnostic_result"
    assert result.metrics.disagreement_type == "unlinked"
    assert result.metrics.repair_turns == 0


def test_unknown_evidence_identity_cannot_start_reconsideration() -> None:
    calls = 0

    def verifier(
        context: BlindedVerifierContext, prior: ReconsiderationRequest | None
    ) -> VerifierReply:
        nonlocal calls
        calls += 1
        return VerifierReply(
            judgment="high", rationale="Fabricated link.", evidence_ids=("claim:unknown",)
        )

    result = evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )
    assert calls == 1
    assert result.metrics.evidence_effect == "unlinked"


def test_reconsideration_package_removes_unknown_evidence_identity() -> None:
    request_seen: ReconsiderationRequest | None = None

    def verifier(
        context: BlindedVerifierContext, request: ReconsiderationRequest | None
    ) -> VerifierReply:
        nonlocal request_seen
        if request is not None:
            request_seen = request
        return VerifierReply(
            judgment="high",
            rationale="Mixed links.",
            evidence_ids=("claim:registry", "claim:unknown"),
        )

    evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )
    assert request_seen is not None
    assert request_seen.initial_reply.evidence_ids == ("claim:registry",)


def test_each_verifier_call_receives_a_fresh_defensive_context_copy() -> None:
    observed: list[str] = []

    def verifier(
        context: BlindedVerifierContext, request: ReconsiderationRequest | None
    ) -> VerifierReply:
        observed.append(str(context.frozen_scope["result_id"]))
        cast(dict[str, Any], context.frozen_scope)["result_id"] = "result:mutated"
        return VerifierReply(
            judgment="high", rationale="Conflict.", evidence_ids=("claim:registry",)
        )

    evaluate_blinded_verifier(
        context=_context(),
        triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low",
        verifier=verifier,
    )
    assert observed == ["result:aurora", "result:aurora"]


def test_public_replay_compares_present_and_absent_reproducibly() -> None:
    def verifier(
        context: BlindedVerifierContext, prior: ReconsiderationRequest | None
    ) -> VerifierReply:
        return VerifierReply(
            judgment="low",
            rationale="Evidence supports baseline.",
            evidence_ids=("claim:registry",),
            input_tokens=17,
            output_tokens=5,
            latency_ms=3,
        )

    first = compare_verifier_modes(
        context=_context(), triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low", verifier=verifier,
    )
    second = compare_verifier_modes(
        context=_context(), triggers=TriggerFacts(pivotal_source_conflict=True),
        baseline_judgment="low", verifier=verifier,
    )
    assert first == second
    assert first.without_verifier.baseline_judgment == first.with_verifier.baseline_judgment
    assert first.with_verifier.metrics.total_tokens == 22
    assert first.with_verifier.metrics.evidence_effect == "none"


def test_checked_in_public_fixture_replays_without_a_model() -> None:
    comparison = replay_verifier_fixture(
        __import__("pathlib").Path("tests/public_fixtures/verifier/source-conflict.json")
    )
    assert comparison.without_verifier.outcome == "baseline_only"
    assert comparison.with_verifier.outcome == "diagnostic_result"
    assert comparison.with_verifier.metrics.model_dump() == {
        "disagreement_type": "judgment",
        "judgment_impact": "material",
        "evidence_effect": "cited_counter_evidence",
        "extra_calls": 2,
        "total_tokens": 57,
        "latency_ms": 7,
        "failures": 0,
        "repair_turns": 1,
    }
