from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from rob2_kit.application.interfaces import MutationContext, WorkflowStatus
from rob2_kit.application.preparation import (
    DraftReady,
    IncompleteReason,
    PreparationIncomplete,
    PreparationOutcome,
    TrialFailed,
    TrialFailureReason,
)
from rob2_kit.domain.assessment import SQAnswerCategory
from rob2_kit.domain.evidence import (
    EvidenceBundle,
    EvidenceClaim,
    VerificationStatus,
    VisualTranscription,
)
from rob2_kit.domain.releases import PackKind, PackRelease, PolicyKind, PolicyRelease
from rob2_kit.domain.results import Comparison, Estimate, Result, ResultSpecRevision
from tests.fixtures import HASH, dependency, reference, revision_fields


def result_spec() -> ResultSpecRevision:
    result = Result(
        result_id="result:trial-a-mortality",
        trial_id="trial:a",
        randomization_id="randomization:a",
        comparison=Comparison(
            experimental_arm_id="arm:experimental",
            comparator_arm_id="arm:control",
        ),
        effect_of_interest="assignment",
        outcome_construct="mortality",
        measurement_instrument="all-cause",
        time_point="30 days",
        analysis_population="intention-to-treat",
        analysis_model="risk ratio",
        effect_measure="risk_ratio",
        source_locator="report:primary/table:2/row:mortality",
    )
    return ResultSpecRevision(
        **revision_fields("result-spec"),
        result=result,
        estimate=Estimate(
            value=Decimal("0.82"),
            interval_lower=Decimal("0.70"),
            interval_upper=Decimal("0.96"),
            denominator_experimental=100,
            denominator_comparator=100,
        ),
        provenance_note="Primary report table 2",
    )


def test_result_spec_round_trip_preserves_stable_identity_and_numbers() -> None:
    spec = result_spec()
    restored = ResultSpecRevision.model_validate_json(spec.model_dump_json())
    assert restored == spec
    assert restored.result.result_id == "result:trial-a-mortality"
    assert restored.estimate.value == Decimal("0.82")


def test_evidence_bundle_round_trips() -> None:
    bundle = EvidenceBundle(
        **revision_fields("bundle"),
        dependencies=(
            dependency("result-spec", "dependency:result-spec"),
            dependency("disposition", "dependency:evidence-disposition"),
            dependency("claim", "dependency:evidence-item"),
        ),
        result_spec=reference("result-spec"),
        disposition=reference("disposition"),
        items=(reference("claim"),),
        frozen_content_hash=HASH,
    )
    assert EvidenceBundle.model_validate(bundle.model_dump(mode="json")) == bundle


@pytest.mark.parametrize(
    "outcome",
    [
        DraftReady(assessment=reference("assessment")),
        PreparationIncomplete(
            result_spec=reference("result-spec"),
            reason=IncompleteReason.INSUFFICIENT_READABLE_COVERAGE,
            detail="Unreadable appendix",
        ),
        TrialFailed(
            trial_id="trial:a",
            reason=TrialFailureReason.REQUIRED_PRIMARY_UNRECOVERABLE,
            detail="Primary report unrecoverable",
        ),
    ],
)
def test_all_preparation_outcomes_round_trip(outcome: PreparationOutcome) -> None:
    adapter = TypeAdapter(PreparationOutcome)
    assert adapter.validate_json(adapter.dump_json(outcome)) == outcome


def test_not_applicable_is_not_an_answer_category() -> None:
    with pytest.raises(ValueError):
        SQAnswerCategory("not_applicable")


def test_mutation_context_rejects_unlabelled_fingerprint() -> None:
    with pytest.raises(ValidationError):
        MutationContext(
            idempotency_key="request-1",
            work_item_id="work:item-1",
            contract_version="1.0.0",
            expected_dependency_fingerprint="abc",
        )


def test_interface_statuses_match_the_canonical_contract() -> None:
    assert {status.value for status in WorkflowStatus} == {
        "completed",
        "work_required",
        "review_pending",
        "preparation_outcome_reached",
        "retryable_interruption",
        "trial_problem",
        "run_integrity_failure",
    }


def test_evidence_claim_rejects_reversed_span() -> None:
    with pytest.raises(ValidationError):
        EvidenceClaim(
            **revision_fields("claim"),
            dependencies=(
                dependency("unit", "dependency:canonical-unit"),
                dependency("source", "dependency:source"),
            ),
            canonical_unit=reference("unit"),
            source=reference("source"),
            span_start=10,
            span_end=5,
            quoted_text_hash=HASH,
            claim_type="claim:randomization",
            verification_status=VerificationStatus.MACHINE_VERIFIED,
        )


def test_visual_transcription_is_permanently_visual_only_and_review_required() -> None:
    transcription = VisualTranscription(
        **revision_fields("visual-transcription"),
        dependencies=(dependency("source", "dependency:source"),),
        source=reference("source"),
        page=4,
        region=(10.0, 20.0, 300.0, 160.0),
        render_mode="crop",
        dpi=216,
        transcription="42 of 51 participants were analysed.",
        decision_critical=("content:denominator",),
    )

    assert transcription.verification_status is VerificationStatus.VISUAL_ONLY
    assert transcription.review_required is True
    with pytest.raises(ValidationError):
        VisualTranscription.model_validate(
            transcription.model_dump()
            | {"verification_status": VerificationStatus.MACHINE_VERIFIED}
        )


def test_pack_and_policy_release_kinds_are_disjoint() -> None:
    common = {
        **revision_fields("release"),
        "family_id": "family:test",
        "release_id": "2026.1",
        "canonical_content_hash": HASH,
        "required_schema_version": "1.0.0",
        "inventory": (),
    }
    assert PackRelease.model_validate({**common, "kind": PackKind.LOGIC}).kind is PackKind.LOGIC
    assert (
        PolicyRelease.model_validate({**common, "kind": PolicyKind.REVIEW_POLICY}).kind
        is PolicyKind.REVIEW_POLICY
    )
    with pytest.raises(ValidationError):
        PackRelease.model_validate({**common, "kind": "review_policy"})
    with pytest.raises(ValidationError):
        PolicyRelease.model_validate({**common, "kind": "logic"})
