"""Pure, question-scoped v3 Evidence Bundle materialization.

The RunEngine supplies already-resolved immutable records and later commits the
returned records in one transaction.  This module deliberately has no ledger,
receipt registry, clock, or query dependency: it can only replay provenance
which is present in its input.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import model_validator

from rob2_kit.application.active_question_frontier import (
    EngineVerifiedNoInformationBasis,
    QuestionEvidenceBundleBinding,
    QuestionEvidenceClosure,
    evidence_closure_from_workflow,
)
from rob2_kit.application.question_evidence_session import QuestionEvidenceSession
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import (
    ConsiderationDisposition,
    EvidenceBundle,
    EvidenceCandidateDispositionRecord,
    EvidenceClaim,
    EvidenceConsideration,
    EvidenceConsiderationManifest,
    EvidenceCoverageState,
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    TrialAttribution,
    V3EvidenceCoverageLimitation,
    V3EvidenceCoverageLimitationKind,
    V3EvidenceCoverageOutcome,
    V3EvidenceCoverageReceiptRecord,
    V3EvidenceCoverageStageReceipt,
    VerificationStatus,
    VisualTranscription,
)
from rob2_kit.domain.revisions import (
    Actor,
    Dependency,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.evidence.workflow import V3EvidenceWorkflowState, V3TriageKind, v3_coverage_progress


class QuestionEvidenceBundleMaterializationError(ValueError):
    """The supplied immutable evidence cannot produce an answer-ready bundle."""


class ResolvedQuestionEvidenceReview(FrozenModel):
    """A review and the exact frozen artifact reference that names it."""

    review: EvidenceReviewRevision
    reference: RecordReference

    @model_validator(mode="after")
    def validate_reference(self) -> ResolvedQuestionEvidenceReview:
        if self.reference.entity_id != self.review.entity_id:
            raise ValueError("resolved review reference names a different review")
        if self.reference.revision_id != self.review.revision_id:
            raise ValueError("resolved review reference has a stale review revision")
        if self.reference.content_hash != canonical_hash(self.review):
            raise ValueError("resolved review reference has a stale or tampered content hash")
        return self


class ResolvedQuestionEvidenceClaim(FrozenModel):
    """A claim and its exact frozen artifact reference."""

    claim: EvidenceClaim
    reference: RecordReference

    @model_validator(mode="after")
    def validate_reference(self) -> ResolvedQuestionEvidenceClaim:
        if self.reference.entity_id != self.claim.entity_id:
            raise ValueError("resolved claim reference names a different claim")
        if self.reference.revision_id != self.claim.revision_id:
            raise ValueError("resolved claim reference has a stale claim revision")
        if self.reference.content_hash != canonical_hash(self.claim):
            raise ValueError("resolved claim reference has a stale or tampered content hash")
        return self


class ResolvedQuestionVisualTranscription(FrozenModel):
    """A visual-only item is retained only with its reviewing candidate/span."""

    transcription: VisualTranscription
    reference: RecordReference
    candidate_id: Identifier
    authorizing_review: RecordReference
    review_span_id: Identifier

    @model_validator(mode="after")
    def validate_reference(self) -> ResolvedQuestionVisualTranscription:
        if self.reference.entity_id != self.transcription.entity_id:
            raise ValueError("resolved visual reference names a different transcription")
        if self.reference.revision_id != self.transcription.revision_id:
            raise ValueError("resolved visual reference has a stale transcription revision")
        if self.reference.content_hash != canonical_hash(self.transcription):
            raise ValueError("resolved visual reference has a stale or tampered content hash")
        return self


class QuestionEvidenceBundleMaterializationInput(FrozenModel):
    """All resolved facts required to build one question's durable bundle."""

    materialization_id: Identifier
    session: QuestionEvidenceSession
    workflow: V3EvidenceWorkflowState
    evidence_closure: QuestionEvidenceClosure
    result_spec: RecordReference
    reviews: tuple[ResolvedQuestionEvidenceReview, ...] = ()
    claims: tuple[ResolvedQuestionEvidenceClaim, ...] = ()
    visual_transcriptions: tuple[ResolvedQuestionVisualTranscription, ...] = ()
    conflict_item_groups: tuple[tuple[Identifier, ...], ...] = ()
    actor: Actor
    observed_at: datetime
    require_answer_ready: bool = True

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> QuestionEvidenceBundleMaterializationInput:
        if len({item.reference.entity_id for item in self.reviews}) != len(self.reviews):
            raise ValueError("question evidence input cannot repeat a review")
        item_ids = (
            *[item.reference.entity_id for item in self.claims],
            *[item.reference.entity_id for item in self.visual_transcriptions],
        )
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("question evidence input cannot repeat a considered item")
        return self


class QuestionEvidenceBundlePendingArtifacts(FrozenModel):
    """Ordered records for one atomic RunEngine append-only commit."""

    disposition: EvidenceCandidateDispositionRecord
    coverage_receipt: V3EvidenceCoverageReceiptRecord
    manifest: EvidenceConsiderationManifest
    bundle: EvidenceBundle

    @property
    def references(self) -> tuple[RecordReference, ...]:
        return tuple(
            _reference(item)
            for item in (
                self.disposition,
                self.coverage_receipt,
                self.manifest,
                self.bundle,
            )
        )


class QuestionEvidenceBundleMaterialization(FrozenModel):
    """Pure materialization result, ready for an atomic ledger commit."""

    pending_artifacts: QuestionEvidenceBundlePendingArtifacts
    binding: QuestionEvidenceBundleBinding
    supporting_evidence_ids: tuple[Identifier, ...] = ()
    contradicting_evidence_ids: tuple[Identifier, ...] = ()
    engine_verified_no_information_basis: EngineVerifiedNoInformationBasis | None = None

    @property
    def pending_references(self) -> tuple[RecordReference, ...]:
        return self.pending_artifacts.references


def materialize_question_evidence_bundle(
    input: QuestionEvidenceBundleMaterializationInput,
) -> QuestionEvidenceBundleMaterialization:
    """Replay one closed v3 workflow into ordered, uncommitted records.

    Qualifying polarity is derived solely from the reviewed exact span.  No
    caller input can designate a claim as supporting, contradicting, complete,
    or a No-information basis.
    """

    workflow = input.workflow
    _validate_identity(input)
    _validate_scope(input)
    review_by_ref = {item.reference.entity_id: item for item in input.reviews}
    triage_by_candidate = _triage_by_candidate(workflow)
    candidate_ids = _candidate_ids(workflow)
    claims_by_review_span: dict[tuple[str, str], ResolvedQuestionEvidenceClaim] = {}
    supporting: list[ResolvedQuestionEvidenceClaim] = []
    contradicting: list[ResolvedQuestionEvidenceClaim] = []

    for item in input.claims:
        review = review_by_ref.get(item.claim.authorizing_review.entity_id)
        if review is None or review.reference != item.claim.authorizing_review:
            raise QuestionEvidenceBundleMaterializationError(
                "claim does not name a current resolved authorizing review"
            )
        span = _validate_claim(item, review, workflow, candidate_ids, triage_by_candidate)
        key = (review.reference.entity_id, span.span_id)
        if key in claims_by_review_span:
            raise QuestionEvidenceBundleMaterializationError(
                "multiple claims cannot authorize the same review span"
            )
        claims_by_review_span[key] = item
        if span.disposition is EvidenceReviewDisposition.SUPPORTING:
            supporting.append(item)
        else:
            contradicting.append(item)

    _validate_reviews(input, candidate_ids, triage_by_candidate, claims_by_review_span)
    visual_dispositions = _validate_visuals(
        input, review_by_ref, candidate_ids, triage_by_candidate
    )
    limitations = _coverage_limitations(workflow)
    unresolved = [
        candidate_id
        for candidate_id, triage in triage_by_candidate.items()
        if triage.kind is V3TriageKind.UNRESOLVED
    ]
    if unresolved:
        limitations.append("unresolved_candidate:" + ",".join(sorted(unresolved)))

    ordered_claims = tuple(
        sorted((*supporting, *contradicting), key=lambda item: item.reference.entity_id)
    )
    ordered_visuals = tuple(
        sorted(visual_dispositions, key=lambda item: item[0].reference.entity_id)
    )
    item_refs = tuple(item.reference for item in ordered_claims) + tuple(
        item.reference for item, _ in ordered_visuals
    )
    dispositions = tuple(
        EvidenceConsideration(
            item_id=item.reference.entity_id,
            disposition=(
                ConsiderationDisposition.SUPPORTING
                if item in supporting
                else ConsiderationDisposition.CONTRADICTING
            ),
        )
        for item in ordered_claims
    ) + tuple(disposition for _, disposition in ordered_visuals)
    conflicts = _validate_conflicts(input.conflict_item_groups, item_refs)
    coverage_state = _coverage_state(workflow, limitations)
    no_information = _no_information_basis(
        input,
        candidate_ids=candidate_ids,
        triage_by_candidate=triage_by_candidate,
        item_refs=item_refs,
        qualifying_claims=ordered_claims,
        limitations=limitations,
    )
    if input.require_answer_ready and limitations:
        raise QuestionEvidenceBundleMaterializationError(
            "question evidence has material coverage limitations and cannot bind an answer"
        )
    qualifying_visuals = tuple(
        item
        for item, disposition in ordered_visuals
        if disposition.disposition
        in {ConsiderationDisposition.SUPPORTING, ConsiderationDisposition.CONTRADICTING}
    )
    if (
        input.require_answer_ready
        and not (*ordered_claims, *qualifying_visuals)
        and no_information is None
    ):
        raise QuestionEvidenceBundleMaterializationError(
            "contextual-only or zero-hit evidence has no verified answer basis"
        )

    ids = _derived_ids(input)
    disposition = EvidenceCandidateDispositionRecord(
        entity_id=ids["disposition_entity_id"],
        revision_id=ids["disposition_revision_id"],
        dependencies=tuple(
            Dependency(**reference.model_dump(), role="dependency:evidence-item")
            for reference in item_refs
        ),
        actor=input.actor,
        observed_at=input.observed_at,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        items=item_refs,
        dispositions=dispositions,
    )
    coverage_receipt = _coverage_receipt(input, ids)
    manifest = EvidenceConsiderationManifest(
        entity_id=ids["manifest_entity_id"],
        revision_id=ids["manifest_revision_id"],
        dependencies=tuple(
            Dependency(**reference.model_dump(), role="dependency:considered-item")
            for reference in item_refs
        ),
        actor=input.actor,
        observed_at=input.observed_at,
        sq_id=workflow.question_id,
        considered_items=item_refs,
        dispositions=dispositions,
    )
    bundle = _bundle(
        input,
        ids,
        disposition=disposition,
        coverage_receipt=coverage_receipt,
        manifest=manifest,
        item_refs=item_refs,
        conflicts=conflicts,
        coverage_state=coverage_state,
        limitations=tuple(sorted(set(limitations))),
        no_information=no_information is not None,
    )
    supporting_ids = tuple(
        sorted(
            [item.reference.entity_id for item in supporting]
            + [
                item.reference.entity_id
                for item, disposition in ordered_visuals
                if disposition.disposition is ConsiderationDisposition.SUPPORTING
            ]
        )
    )
    contradicting_ids = tuple(
        sorted(
            [item.reference.entity_id for item in contradicting]
            + [
                item.reference.entity_id
                for item, disposition in ordered_visuals
                if disposition.disposition is ConsiderationDisposition.CONTRADICTING
            ]
        )
    )
    binding = QuestionEvidenceBundleBinding(
        question_id=workflow.question_id,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        bundle_revision_id=bundle.revision_id,
        bundle_content_hash=canonical_hash(bundle),
        supporting_evidence_ids=supporting_ids,
        contradicting_evidence_ids=contradicting_ids,
        engine_verified_no_information_basis=no_information,
    )
    pending = QuestionEvidenceBundlePendingArtifacts(
        disposition=disposition,
        coverage_receipt=coverage_receipt,
        manifest=manifest,
        bundle=bundle,
    )
    return QuestionEvidenceBundleMaterialization(
        pending_artifacts=pending,
        binding=binding,
        supporting_evidence_ids=supporting_ids,
        contradicting_evidence_ids=contradicting_ids,
        engine_verified_no_information_basis=no_information,
    )


def _validate_identity(input: QuestionEvidenceBundleMaterializationInput) -> None:
    workflow = input.workflow
    session = input.session
    if (session.run_id, session.result_id, session.domain_id) != (
        workflow.run_id,
        workflow.result_id,
        workflow.domain_id,
    ):
        raise QuestionEvidenceBundleMaterializationError("session does not bind workflow scope")
    if session.obligation_revision_id != workflow.obligation_revision_id:
        raise QuestionEvidenceBundleMaterializationError(
            "session does not bind workflow obligation identity"
        )
    obligation = next(
        (item for item in session.obligations if item.question_id == workflow.question_id), None
    )
    if obligation != workflow.obligation:
        raise QuestionEvidenceBundleMaterializationError("workflow question is absent from session")
    session_inventory = {item.source_id: item for item in session.inventory.sources}
    workflow_inventory = {item.source_id: item for item in workflow.authorized_inventory}
    if set(session_inventory) != set(workflow_inventory) or any(
        (
            session_inventory[source_id].source_artifact_hash,
            session_inventory[source_id].parse_id,
            session_inventory[source_id].parse_output_hash,
        )
        != (
            workflow_inventory[source_id].source_artifact_hash,
            workflow_inventory[source_id].parse_id,
            workflow_inventory[source_id].parse_output_hash,
        )
        for source_id in session_inventory
    ):
        raise QuestionEvidenceBundleMaterializationError(
            "session inventory does not bind workflow inventory identity"
        )
    if input.evidence_closure != evidence_closure_from_workflow(workflow):
        raise QuestionEvidenceBundleMaterializationError(
            "evidence closure is stale or does not bind the closed v3 workflow"
        )


def _validate_scope(input: QuestionEvidenceBundleMaterializationInput) -> None:
    workflow = input.workflow
    for item in input.reviews:
        review = item.review
        if (review.result_id, review.domain_id, review.sq_id) != (
            workflow.result_id,
            workflow.domain_id,
            workflow.question_id,
        ):
            raise QuestionEvidenceBundleMaterializationError(
                "review is outside the materialized question scope"
            )


def _candidate_ids(workflow: V3EvidenceWorkflowState) -> set[Identifier]:
    return {item.candidate_id for item in workflow.exposures}


def _triage_by_candidate(workflow: V3EvidenceWorkflowState) -> dict[Identifier, object]:
    triage: dict[Identifier, object] = {}
    for item in workflow.triage_revisions:
        if item.sq_id != workflow.question_id:
            raise QuestionEvidenceBundleMaterializationError("triage is outside workflow question")
        if item.candidate_id in triage:
            raise QuestionEvidenceBundleMaterializationError(
                "candidate has multiple current triages"
            )
        triage[item.candidate_id] = item
    return triage


def _validate_claim(
    item: ResolvedQuestionEvidenceClaim,
    resolved_review: ResolvedQuestionEvidenceReview,
    workflow: V3EvidenceWorkflowState,
    candidate_ids: set[Identifier],
    triage_by_candidate: dict[Identifier, object],
):
    claim = item.claim
    review = resolved_review.review
    if claim.candidate_id != review.candidate_id or claim.candidate_id not in candidate_ids:
        raise QuestionEvidenceBundleMaterializationError(
            "claim candidate is outside question workflow"
        )
    triage = triage_by_candidate.get(claim.candidate_id)
    if triage is None or triage.kind is not V3TriageKind.RETAINED:
        raise QuestionEvidenceBundleMaterializationError(
            "claim requires a retained current candidate"
        )
    span = next((span for span in review.spans if span.span_id == claim.review_span_id), None)
    if span is None:
        raise QuestionEvidenceBundleMaterializationError(
            "claim names no span in authorizing review"
        )
    if (
        span.disposition
        not in {
            EvidenceReviewDisposition.SUPPORTING,
            EvidenceReviewDisposition.CONTRADICTING,
        }
        or span.trial_attribution is not TrialAttribution.ACTIVE
    ):
        raise QuestionEvidenceBundleMaterializationError(
            "only active supporting or contradicting review spans can authorize claims"
        )
    if claim.verification_status is not VerificationStatus.MACHINE_VERIFIED:
        raise QuestionEvidenceBundleMaterializationError(
            "visual-only or review-required claims cannot ground an answer bundle"
        )
    if (claim.span_start, claim.span_end) != (span.span_start, span.span_end):
        raise QuestionEvidenceBundleMaterializationError(
            "claim span does not exactly match its review"
        )
    fragments = span.reviewed_context.fragments
    if not any(
        fragment.unit_id == claim.canonical_unit.entity_id
        and fragment.source_id == claim.source.entity_id
        and fragment.span_start <= claim.span_start
        and fragment.span_end >= claim.span_end
        for fragment in fragments
    ):
        raise QuestionEvidenceBundleMaterializationError(
            "claim provenance is not contained in its reviewed exact fragment"
        )
    return span


def _validate_reviews(
    input: QuestionEvidenceBundleMaterializationInput,
    candidate_ids: set[Identifier],
    triage_by_candidate: dict[Identifier, object],
    claims_by_review_span: dict[tuple[str, str], ResolvedQuestionEvidenceClaim],
) -> None:
    reviews_by_candidate = {item.review.candidate_id: item for item in input.reviews}
    if len(reviews_by_candidate) != len(input.reviews):
        raise QuestionEvidenceBundleMaterializationError("candidate has multiple current reviews")
    for candidate_id, triage in triage_by_candidate.items():
        if triage.kind is V3TriageKind.RETAINED:
            review = reviews_by_candidate.get(candidate_id)
            if review is None or not review.review.is_complete:
                raise QuestionEvidenceBundleMaterializationError(
                    "retained candidate lacks a substantive resolved review"
                )
    for item in input.reviews:
        review = item.review
        if review.candidate_id not in candidate_ids:
            raise QuestionEvidenceBundleMaterializationError(
                "review candidate is outside question workflow"
            )
        triage = triage_by_candidate.get(review.candidate_id)
        if triage is None or triage.kind is not V3TriageKind.RETAINED:
            if any(
                span.disposition
                in {EvidenceReviewDisposition.SUPPORTING, EvidenceReviewDisposition.CONTRADICTING}
                for span in review.spans
            ):
                raise QuestionEvidenceBundleMaterializationError(
                    "substantive review does not match a retained current candidate"
                )
        for span in review.spans:
            if (
                span.disposition
                in {
                    EvidenceReviewDisposition.SUPPORTING,
                    EvidenceReviewDisposition.CONTRADICTING,
                }
                and (item.reference.entity_id, span.span_id) not in claims_by_review_span
            ):
                raise QuestionEvidenceBundleMaterializationError(
                    "substantive review span has no matching immutable claim"
                )


def _validate_visuals(
    input: QuestionEvidenceBundleMaterializationInput,
    reviews: dict[Identifier, ResolvedQuestionEvidenceReview],
    candidate_ids: set[Identifier],
    triage_by_candidate: dict[Identifier, object],
) -> list[tuple[ResolvedQuestionVisualTranscription, EvidenceConsideration]]:
    result: list[tuple[ResolvedQuestionVisualTranscription, EvidenceConsideration]] = []
    for item in input.visual_transcriptions:
        review = reviews.get(item.authorizing_review.entity_id)
        if review is None or review.reference != item.authorizing_review:
            raise QuestionEvidenceBundleMaterializationError(
                "visual transcription lacks its current authorizing review"
            )
        if (
            item.candidate_id != review.review.candidate_id
            or item.candidate_id not in candidate_ids
        ):
            raise QuestionEvidenceBundleMaterializationError(
                "visual candidate is outside question workflow"
            )
        triage = triage_by_candidate.get(item.candidate_id)
        if (
            triage is None
            or triage.kind is not V3TriageKind.RETAINED
            or not review.review.is_complete
        ):
            raise QuestionEvidenceBundleMaterializationError(
                "visual transcription has no substantive resolved candidate review"
            )
        span = next(
            (span for span in review.review.spans if span.span_id == item.review_span_id), None
        )
        if span is None or item.transcription.source.entity_id not in {
            fragment.source_id for fragment in span.reviewed_context.fragments
        }:
            raise QuestionEvidenceBundleMaterializationError(
                "visual transcription provenance does not match its reviewed span"
            )
        disposition = _consideration_disposition(span.disposition)
        if disposition is None:
            raise QuestionEvidenceBundleMaterializationError(
                "unresolved visual review cannot freeze in an answer-ready bundle"
            )
        result.append(
            (item, EvidenceConsideration(item_id=item.reference.entity_id, disposition=disposition))
        )
    return result


def _consideration_disposition(
    disposition: EvidenceReviewDisposition,
) -> ConsiderationDisposition | None:
    mapping = {
        EvidenceReviewDisposition.SUPPORTING: ConsiderationDisposition.SUPPORTING,
        EvidenceReviewDisposition.CONTRADICTING: ConsiderationDisposition.CONTRADICTING,
        EvidenceReviewDisposition.CONTEXTUAL: ConsiderationDisposition.CONTEXTUAL,
        EvidenceReviewDisposition.OUT_OF_SCOPE: ConsiderationDisposition.OUT_OF_SCOPE,
        EvidenceReviewDisposition.IMMATERIAL: ConsiderationDisposition.IMMATERIAL,
        EvidenceReviewDisposition.SUPERSEDED: ConsiderationDisposition.SUPERSEDED,
        EvidenceReviewDisposition.DUPLICATE: ConsiderationDisposition.DUPLICATE,
    }
    return mapping.get(disposition)


def _coverage_limitations(workflow: V3EvidenceWorkflowState) -> list[str]:
    progress = v3_coverage_progress(workflow)
    active = {
        stage["stage_id"]
        for proposition in progress["propositions"]
        for evidence_pass in proposition["passes"]
        for stage in evidence_pass["stages"]
        if stage["active"]
    }
    limitations: list[str] = []
    outcomes = {item.stage_id: item for item in workflow.stage_outcomes}
    for scope in workflow.stage_scopes:
        if scope.stage_id not in active:
            continue
        for limitation in scope.role_limitations:
            limitations.append(
                f"scope:{scope.stage_id}:{limitation.kind.value}:{limitation.rationale}"
            )
        outcome = outcomes.get(scope.stage_id)
        if outcome is None:
            limitations.append(f"outcome:{scope.stage_id}:missing")
        elif outcome.outcome_kind.value != "obligation_satisfied":
            limitations.append(f"outcome:{scope.stage_id}:{outcome.outcome_kind.value}")
    return limitations


def _coverage_state(
    workflow: V3EvidenceWorkflowState, limitations: list[str]
) -> EvidenceCoverageState:
    if not limitations:
        return EvidenceCoverageState.COMPLETE
    progress = v3_coverage_progress(workflow)
    all_active_have_outcome = all(
        stage["outcome"] is not None
        for proposition in progress["propositions"]
        for evidence_pass in proposition["passes"]
        for stage in evidence_pass["stages"]
        if stage["active"]
    )
    return (
        EvidenceCoverageState.COMPLETE_WITH_LIMITATIONS
        if all_active_have_outcome
        else EvidenceCoverageState.INCOMPLETE
    )


def _no_information_basis(
    input: QuestionEvidenceBundleMaterializationInput,
    *,
    candidate_ids: set[Identifier],
    triage_by_candidate: dict[Identifier, object],
    item_refs: tuple[RecordReference, ...],
    qualifying_claims: tuple[ResolvedQuestionEvidenceClaim, ...],
    limitations: list[str],
) -> EngineVerifiedNoInformationBasis | None:
    if limitations or item_refs or qualifying_claims:
        return None
    if any(
        triage.kind in {V3TriageKind.RETAINED, V3TriageKind.UNRESOLVED}
        for triage in triage_by_candidate.values()
    ):
        return None
    # A candidate without a current disposition is itself material, even if no
    # claim was emitted.  Duplicate/irrelevant candidates are closed evidence.
    if candidate_ids != set(triage_by_candidate):
        return None
    verification_hash = canonical_hash(
        {
            "kind": "engine-verified-no-information:v3",
            "session_content_hash": input.session.content_hash,
            "closure_hash": input.evidence_closure.closure_hash,
            "workflow_state_hash": input.workflow.content_hash,
            "policy": {
                "search": input.workflow.search_policy_hash,
                "read": input.workflow.read_policy_hash,
                "visual": input.workflow.visual_policy_hash,
            },
        }
    )
    return EngineVerifiedNoInformationBasis(
        verification_id=f"verification:no-information-v3-{verification_hash[7:31]}",
        verification_hash=verification_hash,
    )


def _validate_conflicts(
    groups: tuple[tuple[Identifier, ...], ...], item_refs: tuple[RecordReference, ...]
) -> tuple[tuple[Identifier, ...], ...]:
    item_ids = {item.entity_id for item in item_refs}
    normalized: list[tuple[Identifier, ...]] = []
    for group in groups:
        canonical = tuple(sorted(group))
        if (
            len(canonical) < 2
            or len(canonical) != len(set(canonical))
            or not set(canonical) <= item_ids
        ):
            raise QuestionEvidenceBundleMaterializationError(
                "conflict references an item outside this question bundle"
            )
        normalized.append(canonical)
    if len(normalized) != len(set(normalized)):
        raise QuestionEvidenceBundleMaterializationError("question bundle repeats a conflict group")
    return tuple(sorted(normalized))


def _derived_ids(input: QuestionEvidenceBundleMaterializationInput) -> dict[str, Identifier]:
    digest = canonical_hash(
        {
            "materialization_id": input.materialization_id,
            "session_content_hash": input.session.content_hash,
            "closure_hash": input.evidence_closure.closure_hash,
            "workflow_state_hash": input.workflow.content_hash,
            "result_spec": input.result_spec.model_dump(mode="json"),
        }
    )[7:31]
    return {
        "disposition_entity_id": f"evidence-disposition:v3-{digest}",
        "disposition_revision_id": f"revision:v3-disposition-{digest}",
        "coverage_entity_id": f"search-coverage:v3-{digest}",
        "coverage_revision_id": f"revision:v3-coverage-{digest}",
        "manifest_entity_id": f"evidence-manifest:v3-{digest}",
        "manifest_revision_id": f"revision:v3-manifest-{digest}",
        "bundle_entity_id": f"bundle:v3-{digest}",
        "bundle_revision_id": f"revision:v3-bundle-{digest}",
    }


def _coverage_receipt(
    input: QuestionEvidenceBundleMaterializationInput, ids: dict[str, Identifier]
) -> V3EvidenceCoverageReceiptRecord:
    workflow = input.workflow
    progress = v3_coverage_progress(workflow)
    active = {
        stage["stage_id"]: stage["active"]
        for proposition in progress["propositions"]
        for evidence_pass in proposition["passes"]
        for stage in evidence_pass["stages"]
    }
    outcomes = {item.stage_id: item for item in workflow.stage_outcomes}
    stages = []
    for scope in sorted(
        workflow.stage_scopes, key=lambda item: (item.proposition_id, item.pass_id, item.stage_id)
    ):
        stage_receipts = sorted(
            receipt.receipt_hash
            for receipt in workflow.completion_receipts
            if receipt.stage_id == scope.stage_id
        )
        attempts = sorted(
            item.attempt_id for item in workflow.attempts if item.stage_id == scope.stage_id
        )
        limitations = sorted(
            (
                V3EvidenceCoverageLimitation(
                    kind=V3EvidenceCoverageLimitationKind(item.kind.value),
                    target=(
                        item.role.value
                        if item.role is not None
                        else item.chronology_constraint.value
                        if item.chronology_constraint is not None
                        else item.source_set_rule.value
                    ),
                    source_ids=scope.authorized_source_ids,
                    rationale=item.rationale,
                )
                for item in scope.role_limitations
            ),
            key=lambda item: item.sort_key,
        )
        outcome = outcomes.get(scope.stage_id)
        stages.append(
            V3EvidenceCoverageStageReceipt(
                proposition_id=scope.proposition_id,
                pass_id=scope.pass_id,
                stage_id=scope.stage_id,
                materialized_scope_id=scope.scope_id,
                active=active[scope.stage_id],
                outcome=(
                    None
                    if outcome is None
                    else V3EvidenceCoverageOutcome(outcome.outcome_kind.value)
                ),
                intent_receipt_hashes=tuple(stage_receipts),
                attempt_ids=tuple(attempts),
                limitations=tuple(limitations),
            )
        )
    return V3EvidenceCoverageReceiptRecord(
        entity_id=ids["coverage_entity_id"],
        revision_id=ids["coverage_revision_id"],
        actor=input.actor,
        observed_at=input.observed_at,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        sq_id=workflow.question_id,
        workflow_state_hash=workflow.content_hash,
        question_closure_hash=input.evidence_closure.closure_hash,
        obligation_revision_id=workflow.obligation_revision_id,
        obligation_hash=workflow.obligation_hash,
        inventory_snapshot_hash=workflow.inventory_snapshot_hash,
        search_policy_id=workflow.search_policy_id,
        search_policy_hash=workflow.search_policy_hash,
        read_policy_id=workflow.read_policy_id,
        read_policy_hash=workflow.read_policy_hash,
        visual_policy_id=workflow.visual_policy_id,
        visual_policy_hash=workflow.visual_policy_hash,
        stages=tuple(stages),
    )


def _bundle(
    input: QuestionEvidenceBundleMaterializationInput,
    ids: dict[str, Identifier],
    *,
    disposition: EvidenceCandidateDispositionRecord,
    coverage_receipt: V3EvidenceCoverageReceiptRecord,
    manifest: EvidenceConsiderationManifest,
    item_refs: tuple[RecordReference, ...],
    conflicts: tuple[tuple[Identifier, ...], ...],
    coverage_state: EvidenceCoverageState,
    limitations: tuple[str, ...],
    no_information: bool,
) -> EvidenceBundle:
    reviews = tuple(
        sorted((item.reference for item in input.reviews), key=lambda item: item.entity_id)
    )
    disposition_ref = _reference(disposition)
    coverage_ref = _reference(coverage_receipt)
    manifest_ref = _reference(manifest)
    dependency_pairs = (
        (input.result_spec, "dependency:result-spec"),
        (disposition_ref, "dependency:evidence-disposition"),
        (coverage_ref, "dependency:v3-search-coverage"),
        (manifest_ref, "dependency:evidence-consideration"),
        *((item, "dependency:evidence-item") for item in item_refs),
        *((item, "dependency:evidence-review") for item in reviews),
    )
    dependencies = tuple(
        Dependency(**reference.model_dump(), role=role) for reference, role in dependency_pairs
    )
    frozen_content_hash = canonical_hash(
        {
            "result_spec": input.result_spec.model_dump(mode="json"),
            "disposition": disposition_ref.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in item_refs],
            "sq_id": input.workflow.question_id,
            "domain_id": input.workflow.domain_id,
            "v3_coverage_receipt": coverage_ref.model_dump(mode="json"),
            "consideration_manifest": manifest_ref.model_dump(mode="json"),
            "review_revisions": [item.model_dump(mode="json") for item in reviews],
            "coverage_state": coverage_state.value,
            "coverage_limitations": limitations,
            "no_information_basis": no_information,
            "conflicts": conflicts,
        }
    )
    return EvidenceBundle(
        entity_id=ids["bundle_entity_id"],
        revision_id=ids["bundle_revision_id"],
        dependencies=dependencies,
        actor=input.actor,
        observed_at=input.observed_at,
        result_spec=input.result_spec,
        disposition=disposition_ref,
        items=item_refs,
        frozen_content_hash=frozen_content_hash,
        sq_id=input.workflow.question_id,
        domain_id=input.workflow.domain_id,
        v3_coverage_receipt=coverage_ref,
        consideration_manifest=manifest_ref,
        review_revisions=reviews,
        coverage_state=coverage_state,
        coverage_limitations=limitations,
        no_information_basis=no_information,
        conflicts=conflicts,
    )


def _reference(record: FrozenModel) -> RecordReference:
    entity_id = getattr(record, "entity_id")
    revision_id = getattr(record, "revision_id")
    return RecordReference(
        entity_id=entity_id,
        revision_id=revision_id,
        content_hash=canonical_hash(record),
    )


__all__ = [
    "QuestionEvidenceBundleMaterialization",
    "QuestionEvidenceBundleMaterializationError",
    "QuestionEvidenceBundleMaterializationInput",
    "QuestionEvidenceBundlePendingArtifacts",
    "ResolvedQuestionEvidenceClaim",
    "ResolvedQuestionEvidenceReview",
    "ResolvedQuestionVisualTranscription",
    "materialize_question_evidence_bundle",
]
