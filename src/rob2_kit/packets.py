"""Deterministic, bounded work and synthesis packets.

Packets are pure projections of caller-supplied verified state.  They are not
stored workflow records and deliberately omit Source text, captured paths,
full judgments, full packs, and free-form evidence rationales.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from rob2_kit.assessment import ResultSpec, Trial
from rob2_kit.batch import ApprovedBatch, PackIdentity, frozen_batch_hash
from rob2_kit.detail import DetailReference
from rob2_kit.judgment_models import (
    DomainJudgment,
    EvidenceRelationship,
    Override,
    TextEvidenceRef,
    VisualEvidenceRef,
)
from rob2_kit.judgments import _verified_checkpoint, build_domain_judgment
from rob2_kit.logic.evaluator import active_questions
from rob2_kit.models import Activation, Answer, Judgment, StrictModel, sha256
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.retrieval import handle_from_id
from rob2_kit.sources import Source, SourceRole


class PacketSource(StrictModel):
    alias: str
    source_id: str
    role: SourceRole
    label: str
    media_type: str
    page_count: int = Field(ge=1)


class PacketTrial(StrictModel):
    id: str
    label: str


class PacketResult(StrictModel):
    id: str
    trial_id: str
    randomization_id: str
    randomization_description: str
    arm_ids: tuple[str, ...]
    arm_labels: tuple[str, ...]
    comparison_intervention_arm_id: str
    comparison_comparator_arm_id: str
    effect_of_interest: str
    outcome_definition: str
    measurement: str
    time_point: str
    population: str
    analysis_method: str
    analysis_choices: tuple[str, ...]
    effect_measure: str
    numerical_values: tuple[str, ...]
    denominators: tuple[int, ...]
    anchor_source_id: str
    anchor_page_number: int
    anchor_start: int
    anchor_end: int


class GuidanceQuestion(StrictModel):
    question_id: str
    wording: str
    allowed_answers: tuple[Answer, ...]
    activation: Activation


class ActivationRule(StrictModel):
    question_id: str
    activation: Activation


class PackIdentityDigest(StrictModel):
    scientific: PackIdentity
    policy: PackIdentity


class GuidancePacket(StrictModel):
    domain_id: str
    questions: tuple[GuidanceQuestion, ...]
    activation_graph: tuple[ActivationRule, ...]
    packs: PackIdentityDigest


class DetailDigest(StrictModel):
    refs: tuple[DetailReference, ...] = ()


class EvidenceLocator(StrictModel):
    kind: Literal["text", "visual"]
    source_id: str
    source_sha256: str
    page_number: int = Field(ge=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, gt=0)
    origin: Literal["rendered_page", "rendered_region"] | None = None
    region: tuple[float, float, float, float] | None = None
    image_sha256: str | None = None


class EvidenceUseDigest(StrictModel):
    relationship: EvidenceRelationship
    claim: str
    locators: tuple[EvidenceLocator, ...] = Field(min_length=1)
    details: DetailDigest = DetailDigest()


class AnswerDigest(StrictModel):
    question_id: str
    wording: str
    answer: Answer
    evidence_uses: tuple[EvidenceUseDigest, ...] = ()


class PriorDomainDigest(StrictModel):
    domain_id: str
    checkpoint_hash: str
    proposed_judgment: Judgment
    final_judgment: Judgment
    limitations: tuple[str, ...]
    answers: tuple[AnswerDigest, ...]
    details: DetailDigest = DetailDigest()


class OpenRequirement(StrictModel):
    code: Literal["active_questions", "evidence", "review_correction", "terminal_outcome"]
    question_ids: tuple[str, ...] = ()


class CorrectionBasis(StrictModel):
    predecessor_hash: str | None = None
    active_revision: int | None = Field(default=None, ge=1)
    active_checkpoint_hash: str | None = None
    evidence_locators: tuple[EvidenceLocator, ...]
    evidence_handle_ids: tuple[str, ...]
    requires_reselection: bool


class ApprovedWorkPacket(StrictModel):
    schema_id: Literal["rob2.approved_work_packet"] = "rob2.approved_work_packet"
    schema_version: Literal[1] = 1
    approved_batch_hash: str
    trial: PacketTrial
    result: PacketResult
    domain_id: str
    sources: tuple[PacketSource, ...]
    source_inventory_hash: str
    packs: PackIdentityDigest
    guidance: GuidancePacket
    active_question_ids: tuple[str, ...]
    inactive_question_ids: tuple[str, ...]
    reachable_question_ids: tuple[str, ...]
    active_answers: tuple[AnswerDigest, ...]
    prior_domains: tuple[PriorDomainDigest, ...]
    correction: CorrectionBasis
    open_requirements: tuple[OpenRequirement, ...]
    detail_refs: tuple[DetailReference, ...]
    next_action: Literal["answer_active_questions", "review_correction", "finish_trial"]
    packet_hash: str


class VerifiedDomainPacketBasis(StrictModel):
    approved_batch: ApprovedBatch
    trial_id: str
    result_id: str
    domain_id: str
    active_judgment: DomainJudgment | None = None
    active_revision: int | None = Field(default=None, ge=1)
    predecessor_hash: str | None = None
    prior_judgments: tuple[DomainJudgment, ...] = ()
    detail_refs: tuple[DetailReference, ...] = ()


class DomainSynthesisDigest(StrictModel):
    domain_id: str
    checkpoint_hash: str
    proposed_judgment: Judgment
    final_judgment: Judgment
    override: Override | None = None
    limitations: tuple[str, ...]
    answers: tuple[AnswerDigest, ...]
    details: DetailDigest = DetailDigest()


class TrialSynthesisPacket(StrictModel):
    schema_id: Literal["rob2.trial_synthesis_packet"] = "rob2.trial_synthesis_packet"
    schema_version: Literal[1] = 1
    approved_batch_hash: str
    trial: PacketTrial
    result: PacketResult
    sources: tuple[PacketSource, ...]
    source_inventory_hash: str
    packs: PackIdentityDigest
    domains: tuple[DomainSynthesisDigest, ...] = Field(min_length=5, max_length=5)
    detail_refs: tuple[DetailReference, ...]
    packet_hash: str


class VerifiedSynthesisPacketBasis(StrictModel):
    approved_batch: ApprovedBatch
    trial_id: str
    result_id: str
    active_judgments: tuple[DomainJudgment, ...]
    detail_refs: tuple[DetailReference, ...] = ()


def build_approved_work_packet(basis: VerifiedDomainPacketBasis) -> ApprovedWorkPacket:
    approved = _verified_approved(basis.approved_batch)
    trial, result = _trial_result(approved, basis.trial_id, basis.result_id)
    if basis.domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}:
        raise ValueError("unknown Domain")
    source_inventory = tuple(
        source for source in approved.proposal.sources if source.trial_id == trial.id
    )
    if not source_inventory:
        raise ValueError("approved Trial Source inventory is unavailable")
    current = None
    if basis.active_judgment is not None:
        current = _verified_judgment(
            approved, basis.active_judgment, trial.id, result.id, basis.domain_id
        )
    guidance = _guidance(basis.domain_id)
    answers = (
        {}
        if current is None
        else {item.question_id: item.answer for item in current.active_answers}
    )
    active = tuple(
        item for item in guidance_question_ids(basis.domain_id) if item in active_questions(answers)
    )
    inactive = tuple(item for item in guidance_question_ids(basis.domain_id) if item not in active)
    required = tuple(item for item in active if item not in answers)
    prior = tuple(
        _prior_digest(approved, item, trial.id, result.id)
        for item in basis.prior_judgments
        if item.domain_id != basis.domain_id
    )
    current_answers = () if current is None else _answer_digests(current)
    locators = () if current is None else _locators(current)
    handle_ids = () if current is None else _live_handle_ids(current)
    correction = CorrectionBasis(
        predecessor_hash=basis.predecessor_hash,
        active_revision=basis.active_revision,
        active_checkpoint_hash=None if current is None else current.checkpoint_hash,
        evidence_locators=locators,
        evidence_handle_ids=handle_ids,
        requires_reselection=current is not None and not handle_ids,
    )
    requirements = (
        ()
        if current is not None and not required
        else (OpenRequirement(code="active_questions", question_ids=required),)
    )
    if basis.predecessor_hash is not None:
        next_action = "review_correction"
    elif current is not None and not requirements:
        next_action: Literal["answer_active_questions", "review_correction", "finish_trial"] = (
            "finish_trial"
        )
    else:
        next_action = "answer_active_questions"
    packet = ApprovedWorkPacket(
        approved_batch_hash=approved.frozen_hash,
        trial=_packet_trial(trial),
        result=_packet_result(result),
        domain_id=basis.domain_id,
        sources=tuple(
            _packet_source(source, index) for index, source in enumerate(source_inventory, 1)
        ),
        source_inventory_hash=sha256(source_inventory),
        packs=_pack_digest(approved),
        guidance=guidance,
        active_question_ids=active,
        inactive_question_ids=inactive,
        reachable_question_ids=guidance_question_ids(basis.domain_id),
        active_answers=current_answers,
        prior_domains=prior,
        correction=correction,
        open_requirements=requirements,
        detail_refs=basis.detail_refs,
        next_action=next_action,
        packet_hash="pending",
    )
    return packet.model_copy(
        update={"packet_hash": sha256(packet.model_dump(exclude={"packet_hash"}))}
    )


def build_trial_synthesis_packet(basis: VerifiedSynthesisPacketBasis) -> TrialSynthesisPacket:
    approved = _verified_approved(basis.approved_batch)
    trial, result = _trial_result(approved, basis.trial_id, basis.result_id)
    expected_domains = tuple(item.id for item in SCIENTIFIC_PACK.domains)
    if tuple(sorted(item.domain_id for item in basis.active_judgments)) != tuple(
        sorted(expected_domains)
    ):
        raise ValueError("synthesis requires exactly one active checkpoint for each Domain")
    checked = tuple(
        _verified_judgment(
            approved,
            next(item for item in basis.active_judgments if item.domain_id == domain_id),
            trial.id,
            result.id,
            domain_id,
        )
        for domain_id in expected_domains
    )
    packet = TrialSynthesisPacket(
        approved_batch_hash=approved.frozen_hash,
        trial=_packet_trial(trial),
        result=_packet_result(result),
        sources=tuple(
            _packet_source(source, index)
            for index, source in enumerate(
                (source for source in approved.proposal.sources if source.trial_id == trial.id), 1
            )
        ),
        source_inventory_hash=sha256(
            tuple(source for source in approved.proposal.sources if source.trial_id == trial.id)
        ),
        packs=_pack_digest(approved),
        domains=tuple(_synthesis_digest(item) for item in checked),
        detail_refs=basis.detail_refs,
        packet_hash="pending",
    )
    return packet.model_copy(
        update={"packet_hash": sha256(packet.model_dump(exclude={"packet_hash"}))}
    )


def verify_approved_work_packet(packet: ApprovedWorkPacket) -> ApprovedWorkPacket:
    if packet.packet_hash != sha256(packet.model_dump(exclude={"packet_hash"})):
        raise ValueError("Approved work packet identity is corrupt")
    return packet


def verify_trial_synthesis_packet(packet: TrialSynthesisPacket) -> TrialSynthesisPacket:
    if packet.packet_hash != sha256(packet.model_dump(exclude={"packet_hash"})):
        raise ValueError("Trial synthesis packet identity is corrupt")
    return packet


def _verified_approved(approved: ApprovedBatch) -> ApprovedBatch:
    if approved.frozen_hash != frozen_batch_hash(approved.proposal, approved.pack_identities):
        raise ValueError("Approved Batch identity is corrupt")
    expected = _pack_digest(approved)
    if expected != _pack_digest_from_current():
        raise ValueError("Approved Batch pack identities are stale")
    return approved


def _pack_digest(approved: ApprovedBatch) -> PackIdentityDigest:
    packs = {item.id: item for item in approved.pack_identities}
    try:
        return PackIdentityDigest(
            scientific=packs[SCIENTIFIC_PACK.id], policy=packs[MAINTAINER_POLICY_PACK.id]
        )
    except KeyError as error:
        raise ValueError("Approved Batch pack identities are incomplete") from error


def _pack_digest_from_current() -> PackIdentityDigest:
    return PackIdentityDigest(
        scientific=PackIdentity(
            id=SCIENTIFIC_PACK.id,
            version=SCIENTIFIC_PACK.version,
            content_hash=SCIENTIFIC_PACK.content_hash,
        ),
        policy=PackIdentity(
            id=MAINTAINER_POLICY_PACK.id,
            version=MAINTAINER_POLICY_PACK.version,
            content_hash=MAINTAINER_POLICY_PACK.content_hash,
        ),
    )


def _trial_result(
    approved: ApprovedBatch, trial_id: str, result_id: str
) -> tuple[Trial, ResultSpec]:
    trial = next((item for item in approved.proposal.trials if item.id == trial_id), None)
    result = next(
        (
            item
            for item in approved.proposal.result_specs
            if item.trial.id == trial_id and item.id == result_id
        ),
        None,
    )
    if trial is None or result is None:
        raise ValueError("packet Trial/Result identity is outside the Approved Batch")
    return trial, result


def _verified_judgment(
    approved: ApprovedBatch,
    judgment: DomainJudgment,
    trial_id: str,
    result_id: str,
    domain_id: str,
) -> DomainJudgment:
    judgment = _verified_checkpoint(judgment)
    if (
        judgment.approved_batch_hash != approved.frozen_hash
        or judgment.trial_id != trial_id
        or judgment.result_id != result_id
        or judgment.domain_id != domain_id
        or judgment.scientific_pack not in approved.pack_identities
        or judgment.policy_pack not in approved.pack_identities
    ):
        raise ValueError("Domain checkpoint does not bind the Approved Batch")
    rebuilt = build_domain_judgment(
        approved,
        trial_id,
        result_id,
        domain_id,
        judgment.active_answers,
        judgment.inactive_questions,
        judgment.final_judgment,
        judgment.override,
        judgment.limitations,
        judgment.actor,
        judgment.observed_at,
    )
    if rebuilt != judgment:
        raise ValueError("Domain checkpoint logic does not match saved content")
    return judgment


def _guidance(domain_id: str) -> GuidancePacket:
    domain = next((item for item in SCIENTIFIC_PACK.domains if item.id == domain_id), None)
    if domain is None:
        raise ValueError("unknown Domain")
    questions = tuple(
        GuidanceQuestion(
            question_id=question.id,
            wording=question.wording,
            allowed_answers=question.allowed_answers,
            activation=question.activation,
        )
        for question in SCIENTIFIC_PACK.questions
        if question.id in domain.question_ids
    )
    return GuidancePacket(
        domain_id=domain_id,
        questions=questions,
        activation_graph=tuple(
            ActivationRule(question_id=item.question_id, activation=item.activation)
            for item in questions
        ),
        packs=_pack_digest_from_current(),
    )


def guidance_question_ids(domain_id: str) -> tuple[str, ...]:
    return tuple(item.question_id for item in _guidance(domain_id).questions)


def _packet_trial(trial: Trial) -> PacketTrial:
    return PacketTrial(id=trial.id, label=trial.label)


def _packet_result(result: ResultSpec) -> PacketResult:
    return PacketResult(
        id=result.id,
        trial_id=result.trial.id,
        randomization_id=result.randomization.id,
        randomization_description=result.randomization.description,
        arm_ids=tuple(item.id for item in result.arms),
        arm_labels=tuple(item.label for item in result.arms),
        comparison_intervention_arm_id=result.comparison.intervention_arm_id,
        comparison_comparator_arm_id=result.comparison.comparator_arm_id,
        effect_of_interest=result.effect_of_interest,
        outcome_definition=result.outcome_definition,
        measurement=result.measurement,
        time_point=result.time_point,
        population=result.population,
        analysis_method=result.analysis_method,
        analysis_choices=result.analysis_choices,
        effect_measure=result.effect_measure,
        numerical_values=result.numerical_values,
        denominators=result.denominators,
        anchor_source_id=result.anchor.source_id,
        anchor_page_number=result.anchor.page_number,
        anchor_start=result.anchor.start,
        anchor_end=result.anchor.end,
    )


def _packet_source(source: Source, index: int) -> PacketSource:
    return PacketSource(
        alias=f"S{index}",
        source_id=source.id,
        role=source.role,
        label=source.label,
        media_type=source.media_type,
        page_count=source.page_count,
    )


def _answer_digests(judgment: DomainJudgment) -> tuple[AnswerDigest, ...]:
    return tuple(
        AnswerDigest(
            question_id=answer.question_id,
            wording=next(
                question.wording
                for question in SCIENTIFIC_PACK.questions
                if question.id == answer.question_id
            ),
            answer=answer.answer,
            evidence_uses=tuple(
                EvidenceUseDigest(
                    relationship=use.relationship,
                    claim=use.claim,
                    locators=tuple(_locator(ref) for ref in use.refs),
                )
                for use in answer.evidence_uses
            ),
        )
        for answer in judgment.active_answers
    )


def _locators(judgment: DomainJudgment) -> tuple[EvidenceLocator, ...]:
    return tuple(
        _locator(ref)
        for answer in judgment.active_answers
        for use in answer.evidence_uses
        for ref in use.refs
    )


def _live_handle_ids(judgment: DomainJudgment) -> tuple[str, ...]:
    handle_ids = tuple(
        handle_id
        for answer in judgment.active_answers
        for use in answer.evidence_uses
        for handle_id in use.handle_ids
    )
    try:
        for handle_id in handle_ids:
            handle_from_id(handle_id)
    except ValueError:
        return ()
    return handle_ids


def _locator(ref: TextEvidenceRef | VisualEvidenceRef) -> EvidenceLocator:
    if ref.kind == "text":
        return EvidenceLocator(
            kind="text",
            source_id=ref.source_id,
            source_sha256=ref.source_sha256,
            page_number=ref.page_number,
            start=ref.start,
            end=ref.end,
        )
    return EvidenceLocator(
        kind="visual",
        source_id=ref.source_id,
        source_sha256=ref.source_sha256,
        page_number=ref.page_number,
        origin=ref.origin.value,
        region=ref.region,
        image_sha256=ref.image_sha256,
    )


def _prior_digest(
    approved: ApprovedBatch, judgment: DomainJudgment, trial_id: str, result_id: str
) -> PriorDomainDigest:
    checked = _verified_judgment(approved, judgment, trial_id, result_id, judgment.domain_id)
    return PriorDomainDigest(
        domain_id=checked.domain_id,
        checkpoint_hash=checked.checkpoint_hash,
        proposed_judgment=checked.proposed_judgment,
        final_judgment=checked.final_judgment,
        limitations=checked.limitations,
        answers=_answer_digests(checked),
    )


def _synthesis_digest(judgment: DomainJudgment) -> DomainSynthesisDigest:
    return DomainSynthesisDigest(
        domain_id=judgment.domain_id,
        checkpoint_hash=judgment.checkpoint_hash,
        proposed_judgment=judgment.proposed_judgment,
        final_judgment=judgment.final_judgment,
        override=judgment.override,
        limitations=judgment.limitations,
        answers=_answer_digests(judgment),
    )


__all__ = [
    "ActivationRule",
    "AnswerDigest",
    "ApprovedWorkPacket",
    "CorrectionBasis",
    "DetailDigest",
    "DomainSynthesisDigest",
    "EvidenceLocator",
    "EvidenceUseDigest",
    "GuidancePacket",
    "GuidanceQuestion",
    "OpenRequirement",
    "PacketResult",
    "PacketSource",
    "PacketTrial",
    "PriorDomainDigest",
    "TrialSynthesisPacket",
    "VerifiedDomainPacketBasis",
    "VerifiedSynthesisPacketBasis",
    "build_approved_work_packet",
    "build_trial_synthesis_packet",
    "guidance_question_ids",
    "verify_approved_work_packet",
    "verify_trial_synthesis_packet",
]
