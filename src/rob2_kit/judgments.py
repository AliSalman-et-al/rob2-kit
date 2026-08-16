"""Versioned working Domain judgments and immutable audit history for one RoB 2 domain."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, ValidationError

from rob2_kit.batch import (
    ApprovedBatch,
    StaleBatch,
    current_batch_in_transaction,
)
from rob2_kit.detail import DetailReference, detail_reference
from rob2_kit.judgment_models import (
    ActiveAnswer,
    DomainAnswerDraft,
    DomainCommitCondition,
    DomainCommitConflict,
    DomainCommitSuccess,
    DomainDraft,
    DomainDraftCommitOperation,
    DomainDraftOperation,
    DomainDraftRepair,
    DomainDraftRepairOutcome,
    DomainDraftRepairResult,
    DomainDraftValidated,
    DomainJudgment,
    DomainValidationReceipt,
    DomainWorkflowCondition,
    EvidenceUse,
    InactiveQuestion,
    Override,
    TextEvidenceRef,
    VisualEvidenceRef,
)
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.models import Judgment, StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.rendering import RenderedPage, render_page
from rob2_kit.retrieval import (
    RetrievalBasisError,
    build_retrieval_snapshot,
    handle_from_id,
    resolve_evidence_handle,
)
from rob2_kit.sources import Source
from rob2_kit.storage import read_only_transaction, transaction
from rob2_kit.telemetry import (
    NO_OP_EVENT_SINK,
    DurationOperation,
    EventSinkLike,
    RepairEvent,
    RepairOutcome,
    RepairSurface,
    emit_event,
    measured_duration,
)
from rob2_kit.text_projection import VerifiedProjection, canonical_projection_identity


class JudgmentValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class JudgmentRevision(StrictModel):
    active_key: str
    revision: int = Field(ge=1)
    previous_hash: str | None = None
    judgment: DomainJudgment
    commit_observation_hash: str | None = None


class JudgmentRevisionIndex(StrictModel):
    active_key: str
    active_revision: int = Field(ge=1)
    active_hash: str


class DomainValidationObservation(StrictModel):
    operation_hash: str
    draft_hash: str
    candidate: DomainJudgment
    receipt: DomainValidationReceipt
    result: DomainDraftValidated | None = None
    observation_hash: str = "pending"


class DomainReviewRecord(StrictModel):
    operation_hash: str
    observation_hash: str
    candidate: DomainJudgment
    receipt: DomainValidationReceipt


class DomainCommitObservation(StrictModel):
    success: DomainCommitSuccess
    candidate_hash: str
    active_revision: int = Field(ge=1)
    packet_content_hash: str
    actor: str
    approved_batch_hash: str
    pack_identities_hash: str
    observation_hash: str


def judgment_key(batch_hash: str, trial_id: str, result_id: str, domain_id: str) -> str:
    return f"domain_judgment:{batch_hash}:{trial_id}:{result_id}:{domain_id}"


def _revision_id(active_key: str) -> str:
    return sha256({"active_key": active_key}).removeprefix("sha256:")


def revision_key(active_key: str, revision: int) -> str:
    if not 1 <= revision < 10**20:
        raise ValueError("revision is outside the fixed-width key range")
    return f"domain_judgment_revision:{_revision_id(active_key)}:{revision:020d}"


def revision_index_key(active_key: str) -> str:
    return f"domain_judgment_revision_index:{_revision_id(active_key)}"


def remaining_domains(
    state: ApprovedBatch, trial_id: str, result_id: str, connection
) -> tuple[str, ...]:
    """Return the exact ordered set still unsaved for this Trial's ResultSpec."""
    return tuple(
        domain.id
        for domain in SCIENTIFIC_PACK.domains
        if connection.execute(
            "SELECT 1 FROM records WHERE name=?",
            (judgment_key(state.frozen_hash, trial_id, result_id, domain.id),),
        ).fetchone()
        is None
    )


def verify_revision_history(
    workspace: str | Path,
    connection,
    state: ApprovedBatch,
    trial_id: str,
    result_id: str,
    domain_id: str,
    active: DomainJudgment,
    projection: VerifiedProjection | None = None,
) -> tuple[int, str | None]:
    """Verify the exact append-only revision chain for one active checkpoint."""
    active_key = judgment_key(state.frozen_hash, trial_id, result_id, domain_id)
    projection = projection or VerifiedProjection(workspace)
    entries: dict[int, JudgmentRevision] = {}
    revision_namespace = f"domain_judgment_revision:{_revision_id(active_key)}:"
    for name, payload in connection.execute(
        "SELECT name,payload FROM records WHERE name GLOB ?",
        (revision_namespace + "[0-9]" * 20,),
    ):
        try:
            entry = JudgmentRevision.model_validate_json(bytes(payload))
        except (TypeError, ValueError) as error:
            raise ValueError("invalid Domain judgment revision record") from error
        if (
            entry.active_key != active_key
            or name != revision_key(active_key, entry.revision)
            or entry.revision in entries
        ):
            raise ValueError("invalid Domain judgment revision record")
        entries[entry.revision] = entry
    row = connection.execute(
        "SELECT payload FROM records WHERE name=?", (revision_index_key(active_key),)
    ).fetchone()
    if row is None:
        raise ValueError("Domain judgment revision history is missing its index")
    index = JudgmentRevisionIndex.model_validate_json(bytes(row[0]))
    if index.active_key != active_key or index.active_hash != active.checkpoint_hash:
        raise ValueError("Domain judgment revision index does not bind the active checkpoint")
    previous: DomainJudgment | None = None
    if set(entries) != set(range(1, index.active_revision + 1)):
        raise ValueError("Domain judgment revision history is not contiguous")
    for revision in range(1, index.active_revision + 1):
        entry = entries[revision]
        if entry.previous_hash != (None if previous is None else previous.checkpoint_hash):
            raise ValueError("Domain judgment revision history has an invalid predecessor")
        judgment = _verified_checkpoint(entry.judgment)
        if (
            judgment.approved_batch_hash != state.frozen_hash
            or judgment.trial_id != trial_id
            or judgment.result_id != result_id
            or judgment.domain_id != domain_id
            or judgment.scientific_pack not in state.pack_identities
            or judgment.policy_pack not in state.pack_identities
        ):
            raise ValueError("Domain judgment revision does not bind the approved batch")
        rebuilt = build_domain_judgment(
            state,
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
            raise ValueError("Domain judgment revision logic does not match saved content")
        for answer in judgment.active_answers:
            for use in answer.evidence_uses:
                for ref in use.refs:
                    _validate_evidence(workspace, state, trial_id, result_id, ref, projection)
        previous = judgment
    if previous != active:
        raise ValueError("active Domain judgment does not match revision history")
    return index.active_revision, entries[index.active_revision].previous_hash


def checkpoint_content(judgment: DomainJudgment) -> dict[str, object]:
    """Return exactly the checkpoint bytes protected by ``checkpoint_hash``."""
    return judgment.model_dump(mode="python", exclude={"checkpoint_hash"})


def _verified_checkpoint(judgment: DomainJudgment) -> DomainJudgment:
    if judgment.checkpoint_hash != sha256(checkpoint_content(judgment)):
        raise ValueError("checkpoint integrity verification failed")
    return judgment


def ensure_judgment_detail(
    connection, judgment: DomainJudgment, approved: ApprovedBatch
) -> DetailReference:
    """Verify canonical judgment authority and ensure its immutable Detail derivative."""

    checked = _verified_checkpoint(judgment)
    if (
        checked.approved_batch_hash != approved.frozen_hash
        or checked.scientific_pack not in approved.pack_identities
        or checked.policy_pack not in approved.pack_identities
        or checked.domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}
    ):
        raise ValueError("judgment Detail does not bind the Approved Batch")
    _result_spec(approved, checked.trial_id, checked.result_id)
    rebuilt = build_domain_judgment(
        approved,
        checked.trial_id,
        checked.result_id,
        checked.domain_id,
        checked.active_answers,
        checked.inactive_questions,
        checked.final_judgment,
        checked.override,
        checked.limitations,
        checked.actor,
        checked.observed_at,
    )
    if rebuilt != checked:
        raise ValueError("judgment Detail does not match canonical scientific content")
    payload = canonical_json_bytes(checked)
    key = f"detail:judgment:{checked.checkpoint_hash}"
    row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
    if row is not None and bytes(row[0]) != payload:
        raise ValueError("judgment Detail record is corrupt")
    if row is None:
        connection.execute("INSERT INTO records(name,payload) VALUES(?,?)", (key, payload))
    return detail_reference("judgment", checked.checkpoint_hash)


def _result_spec(approved: ApprovedBatch, trial_id: str, result_id: str):
    spec = next(
        (
            item
            for item in approved.proposal.result_specs
            if item.trial.id == trial_id and item.id == result_id
        ),
        None,
    )
    if spec is None:
        raise JudgmentValidationError(
            "result_identity_invalid", "ResultSpec does not belong to trial"
        )
    return spec


def _source(approved: ApprovedBatch, trial_id: str, result_id: str, source_id: str) -> Source:
    spec = _result_spec(approved, trial_id, result_id)
    source = next((item for item in approved.proposal.sources if item.id == source_id), None)
    if source is None or source.trial_id != spec.trial.id:
        raise JudgmentValidationError(
            "evidence_invalid", "evidence Source is outside approved inventory"
        )
    return source


def _validate_evidence(
    workspace: str | Path,
    approved: ApprovedBatch,
    trial_id: str,
    result_id: str,
    ref: TextEvidenceRef | VisualEvidenceRef,
    projection: VerifiedProjection | None = None,
) -> None:
    source = _source(approved, trial_id, result_id, ref.source_id)
    if source.sha256 != ref.source_sha256:
        raise JudgmentValidationError(
            "evidence_invalid", "evidence Source hash does not match approved inventory"
        )
    pages = (projection or VerifiedProjection(workspace)).pages(
        source, canonical_projection_identity(workspace, source)
    )
    if ref.page_number > len(pages):
        raise JudgmentValidationError(
            "evidence_invalid", "evidence page is outside captured Source"
        )
    page = pages[ref.page_number - 1]
    if ref.kind == "text":
        if (
            ref.end > len(page)
            or ref.end - ref.start != len(ref.quote)
            or page[ref.start : ref.end] != ref.quote
        ):
            raise JudgmentValidationError(
                "evidence_invalid", "text evidence coordinates do not match captured Source"
            )
        return
    if ref.transcription not in page:
        raise JudgmentValidationError(
            "evidence_invalid", "visual transcription is not attributable to captured Source page"
        )
    rendered = render_page(
        workspace,
        source,
        ref.page_number,
        None if ref.origin.value == "rendered_page" else ref.region,
    )
    if not isinstance(rendered, RenderedPage) or rendered.sha256 != ref.image_sha256:
        raise JudgmentValidationError(
            "evidence_invalid", "visual evidence does not match captured render"
        )


def build_domain_judgment(
    approved: ApprovedBatch,
    trial_id: str,
    result_id: str,
    domain_id: str,
    active_answers: tuple[ActiveAnswer, ...],
    inactive_questions: tuple[InactiveQuestion, ...],
    final_judgment: Judgment | None,
    override: Override | None,
    limitations: tuple[str, ...],
    actor: str,
    observed_at: datetime,
) -> DomainJudgment:
    """Build the complete deterministic checkpoint without accessing the workspace."""
    _result_spec(approved, trial_id, result_id)
    domain = next((item for item in SCIENTIFIC_PACK.domains if item.id == domain_id), None)
    if domain is None:
        raise JudgmentValidationError("domain_unknown", "unknown domain")
    mapping = {item.question_id: item.answer for item in active_answers}
    if len(mapping) != len(active_answers):
        raise JudgmentValidationError("question_partition_invalid", "active answers must be unique")
    active = set(active_questions(mapping)) & set(domain.question_ids)
    inactive = {item.question_id for item in inactive_questions}
    if set(mapping) != active or inactive != set(domain.question_ids) - active:
        raise JudgmentValidationError(
            "question_partition_invalid", "questions must exactly partition the Domain"
        )
    evaluation = evaluate_domain(domain_id, mapping)
    final = evaluation.judgment if final_judgment is None else final_judgment
    if (final != evaluation.judgment) != (override is not None):
        raise JudgmentValidationError(
            "override_invalid", "override is required exactly when final judgment differs"
        )
    packs = {item.id: item for item in approved.pack_identities}
    try:
        scientific_pack = packs[SCIENTIFIC_PACK.id]
        policy_pack = packs[MAINTAINER_POLICY_PACK.id]
    except KeyError as error:
        raise JudgmentValidationError(
            "pack_identities_invalid", "approved batch has incomplete pack identities"
        ) from error
    payload = {
        "approved_batch_hash": approved.frozen_hash,
        "trial_id": trial_id,
        "result_id": result_id,
        "domain_id": domain_id,
        "scientific_pack": scientific_pack,
        "policy_pack": policy_pack,
        "active_answers": active_answers,
        "inactive_questions": inactive_questions,
        "proposed_judgment": evaluation.judgment,
        "trace": evaluation.trace,
        "final_judgment": final,
        "override": override,
        "limitations": limitations,
        "actor": actor,
        "observed_at": observed_at,
    }
    incomplete = DomainJudgment(**payload, checkpoint_hash="pending")
    return incomplete.model_copy(update={"checkpoint_hash": sha256(checkpoint_content(incomplete))})


def _domain_repair(
    pointer: str,
    invariant: str,
    actual: str,
    action: str,
    *,
    subject: str | None = None,
    count: int | None = None,
) -> DomainDraftRepair:
    from typing import cast

    return DomainDraftRepair(
        pointer=pointer,
        subject=subject,
        invariant=cast(
            Literal[
                "question_scope",
                "question_duplicate",
                "question_activation",
                "evidence_required",
                "evidence_handle",
                "evidence_scope",
                "evidence_stale",
                "evidence_integrity",
                "override",
                "draft_shape",
            ],
            invariant,
        ),
        actual=cast(
            Literal[
                "missing",
                "duplicate",
                "unknown",
                "out_of_scope",
                "stale",
                "invalid",
                "mismatch",
            ],
            actual,
        ),
        action=cast(
            Literal[
                "add_answer",
                "remove_answer",
                "replace_handle",
                "correct_activation",
                "correct_override",
                "retry",
            ],
            action,
        ),
        count=count,
    )


def _domain_observation_key(operation_hash: str) -> str:
    return f"domain_validation_observation:{operation_hash}"


def _domain_review_key(operation_hash: str) -> str:
    return f"domain_review:{operation_hash}"


def _compact_domain_validation(
    observation: DomainValidationObservation,
) -> DomainDraftValidated:
    candidate = observation.candidate
    receipt = observation.receipt
    return DomainDraftValidated(
        approved_batch_hash=candidate.approved_batch_hash,
        trial_id=candidate.trial_id,
        result_id=candidate.result_id,
        domain_id=candidate.domain_id,
        draft_hash=observation.draft_hash,
        candidate_ref=detail_reference("judgment", candidate.checkpoint_hash),
        candidate_hash=candidate.checkpoint_hash,
        proposed_judgment=candidate.proposed_judgment,
        predecessor_observation=receipt.observed_active_hash,
        remaining_domains=tuple(
            item.id
            for item in SCIENTIFIC_PACK.domains
            if item.id in receipt.model_dump().get("remaining_domains", ())
        ),
        receipt=receipt,
    )


def _domain_receipt(
    operation: DomainDraftOperation,
    draft_hash: str,
    candidate: DomainJudgment,
    active_revision: int | None,
    active_hash: str | None,
    observed_at: datetime,
    remaining: tuple[str, ...],
) -> DomainValidationReceipt:
    content = {
        "approved_batch_hash": operation.approved_batch_hash,
        "trial_id": operation.trial_id,
        "result_id": operation.result_id,
        "domain_id": operation.domain_id,
        "draft_hash": draft_hash,
        "actor": operation.actor,
        "expected_predecessor_hash": operation.expected_predecessor_hash,
        "observed_active_revision": active_revision,
        "observed_active_hash": active_hash,
        "pack_identities_hash": sha256((candidate.scientific_pack, candidate.policy_pack)),
        "candidate_hash": candidate.checkpoint_hash,
        "observed_at": observed_at,
        "remaining_domains": remaining,
    }
    return DomainValidationReceipt(
        **content,
        receipt_hash=sha256(content),
    )


def _read_domain_observation(
    connection, operation_hash: str, approved: ApprovedBatch
) -> DomainValidationObservation | None:
    row = connection.execute(
        "SELECT payload FROM records WHERE name=?", (_domain_observation_key(operation_hash),)
    ).fetchone()
    if row is None:
        return None
    observation = DomainValidationObservation.model_validate_json(bytes(row[0]))
    if observation.operation_hash != operation_hash:
        raise ValueError("Domain validation observation identity is corrupt")
    content_row = connection.execute(
        "SELECT payload FROM records WHERE name=?",
        (f"domain_validation_observation_content:{observation.observation_hash}",),
    ).fetchone()
    if content_row is None or bytes(content_row[0]) != bytes(row[0]):
        raise ValueError("Domain validation observation content identity is corrupt")
    try:
        candidate = _verified_checkpoint(observation.candidate)
        _verified_domain_receipt(observation.receipt)
    except ValueError as error:
        raise ValueError("Domain validation observation content is corrupt") from error
    receipt = observation.receipt
    if (
        observation.draft_hash != receipt.draft_hash
        or receipt.candidate_hash != candidate.checkpoint_hash
        or receipt.approved_batch_hash != candidate.approved_batch_hash
        or receipt.trial_id != candidate.trial_id
        or receipt.result_id != candidate.result_id
        or receipt.domain_id != candidate.domain_id
        or receipt.actor != candidate.actor
        or receipt.observed_at != candidate.observed_at
        or receipt.expected_predecessor_hash != receipt.observed_active_hash
        or receipt.pack_identities_hash
        != sha256((candidate.scientific_pack, candidate.policy_pack))
        or observation.result is None
        or observation.result != _compact_domain_validation(observation)
        or observation.observation_hash
        != sha256(observation.model_dump(exclude={"observation_hash"}))
    ):
        raise ValueError("Domain validation observation candidate is corrupt")
    return observation


def _domain_basis(
    workspace: str | Path,
    connection,
    operation: DomainDraftOperation | DomainDraftCommitOperation,
    projection: VerifiedProjection | None = None,
) -> tuple[ApprovedBatch, int | None, str | None, tuple[str, ...]] | DomainDraftRepairResult:
    state = current_batch_in_transaction(workspace, connection, projection=projection)
    if not isinstance(state, ApprovedBatch):
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
            detail="an approved nonstale batch is required",
        )
    if state.frozen_hash != operation.approved_batch_hash:
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="approved_batch_mismatch",
            detail="operation does not bind the active Approved Batch",
        )
    if connection.execute(
        "SELECT 1 FROM records WHERE name=?",
        (f"terminal_trial:{state.frozen_hash}:{operation.trial_id}",),
    ).fetchone():
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="trial_terminal",
            detail="terminal Trials cannot accept Domain validation or commit",
        )
    try:
        _result_spec(state, operation.trial_id, operation.result_id)
        if operation.domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}:
            raise JudgmentValidationError("domain_unknown", "unknown domain")
    except JudgmentValidationError as error:
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code=error.code,
            detail=error.detail,
        )
    key = judgment_key(
        state.frozen_hash, operation.trial_id, operation.result_id, operation.domain_id
    )
    row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
    if row is None:
        if operation.expected_predecessor_hash is not None:
            return DomainWorkflowCondition(
                draft_hash=sha256(operation.draft),
                code="checkpoint_absent",
                detail="a first Domain draft must not specify a predecessor",
            )
        return (
            state,
            None,
            None,
            remaining_domains(state, operation.trial_id, operation.result_id, connection),
        )
    try:
        existing = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0])))
        revision, _predecessor = verify_revision_history(
            workspace,
            connection,
            state,
            operation.trial_id,
            operation.result_id,
            operation.domain_id,
            existing,
            projection,
        )
    except (ValidationError, ValueError, TypeError) as error:
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="revision_history_corrupt",
            detail=str(error),
        )
    if operation.expected_predecessor_hash != existing.checkpoint_hash:
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="predecessor_conflict",
            detail="expected predecessor does not match the active checkpoint",
        )
    return (
        state,
        revision,
        existing.checkpoint_hash,
        remaining_domains(state, operation.trial_id, operation.result_id, connection),
    )


def _resolve_domain_answers(
    workspace: str | Path,
    approved: ApprovedBatch,
    operation: DomainDraftOperation,
    projection: VerifiedProjection,
) -> tuple[tuple[ActiveAnswer, ...], tuple[DomainDraftRepair, ...]] | DomainWorkflowCondition:
    repairs: list[DomainDraftRepair] = []
    source_inventory = tuple(
        source for source in approved.proposal.sources if source.trial_id == operation.trial_id
    )
    try:
        retrieval_context = build_retrieval_snapshot(
            workspace,
            operation.trial_id,
            source_inventory,
            projection=projection,
        )
        if retrieval_context.snapshot.scope_kind != "approved_batch":
            raise RetrievalBasisError("Domain Evidence requires Approved Batch scope")
    except RetrievalBasisError as error:
        return DomainWorkflowCondition(
            draft_hash=sha256(operation.draft),
            code="projection_unavailable",
            detail=str(error),
        )
    domain = next(item for item in SCIENTIFIC_PACK.domains if item.id == operation.domain_id)
    allowed = set(domain.question_ids)
    seen: set[str] = set()
    valid_answers: list[tuple[int, DomainAnswerDraft]] = []
    for index, answer in enumerate(operation.draft.active_answers):
        pointer = f"/draft/active_answers/{index}/question_id"
        if answer.question_id not in allowed:
            repairs.append(
                _domain_repair(
                    pointer,
                    "question_scope",
                    "out_of_scope",
                    "remove_answer",
                    subject=answer.question_id,
                )
            )
            continue
        if answer.question_id in seen:
            repairs.append(
                _domain_repair(
                    pointer,
                    "question_duplicate",
                    "duplicate",
                    "remove_answer",
                    subject=answer.question_id,
                )
            )
            continue
        seen.add(answer.question_id)
        valid_answers.append((index, answer))

    resolved: dict[tuple[int, int, int], TextEvidenceRef | VisualEvidenceRef] = {}
    for answer_index, answer in valid_answers:
        for use_index, use in enumerate(answer.evidence_uses):
            for handle_index, handle_id in enumerate(use.handle_ids):
                pointer = (
                    f"/draft/active_answers/{answer_index}/evidence_uses/"
                    f"{use_index}/handle_ids/{handle_index}"
                )
                try:
                    handle = handle_from_id(handle_id)
                except ValueError:
                    repairs.append(
                        _domain_repair(pointer, "evidence_handle", "unknown", "replace_handle")
                    )
                    continue
                try:
                    if retrieval_context.snapshot.snapshot_hash != handle.scope_hash:
                        raise ValueError("Evidence handle scope is mismatched")
                    resolved[(answer_index, use_index, handle_index)] = resolve_evidence_handle(
                        retrieval_context, handle
                    )
                except (OSError, ValueError, IndexError):
                    repairs.append(
                        _domain_repair(pointer, "evidence_integrity", "invalid", "replace_handle")
                    )

    active: list[ActiveAnswer] = []
    for answer_index, answer in valid_answers:
        uses: list[EvidenceUse] = []
        answer_invalid = False
        for use_index, use in enumerate(answer.evidence_uses):
            refs: list[TextEvidenceRef | VisualEvidenceRef] = []
            for handle_index, _handle_id in enumerate(use.handle_ids):
                ref = resolved.get((answer_index, use_index, handle_index))
                if ref is None:
                    answer_invalid = True
                else:
                    refs.append(ref)
            if refs:
                uses.append(
                    EvidenceUse(
                        relationship=use.relationship,
                        claim=use.claim,
                        rationale=use.rationale,
                        refs=tuple(refs),
                        handle_ids=use.handle_ids,
                    )
                )
        if not answer_invalid:
            active.append(
                ActiveAnswer(
                    question_id=answer.question_id,
                    answer=answer.answer,
                    rationale=answer.rationale,
                    evidence_uses=tuple(uses),
                )
            )
    if not repairs:
        mapping = {item.question_id: item.answer for item in active}
        active_ids = set(active_questions(mapping)) & allowed
        missing = tuple(sorted(active_ids - set(mapping)))
        if missing:
            repairs.append(
                _domain_repair(
                    "/draft/active_answers",
                    "question_activation",
                    "missing",
                    "add_answer",
                    count=len(missing),
                )
            )
        extra = tuple(sorted(set(mapping) - active_ids))
        if extra:
            repairs.append(
                _domain_repair(
                    "/draft/active_answers",
                    "question_activation",
                    "out_of_scope",
                    "correct_activation",
                    count=len(extra),
                )
            )
    return tuple(active), tuple(sorted(repairs, key=lambda item: (item.pointer, item.invariant)))


def validate_domain_draft(
    workspace: str | Path,
    operation: DomainDraftOperation,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
    observed_at: datetime | None = None,
    reuse_observation: bool = True,
    persist_observation: bool = True,
    include_candidate: bool = False,
    projection: VerifiedProjection | None = None,
) -> DomainDraftRepairResult | DomainDraftValidated | tuple[DomainDraftValidated, DomainJudgment]:
    """Validate one v2 Domain draft and persist only successful observations."""

    with measured_duration(event_sink, DurationOperation.DOMAIN_VALIDATION):
        projection = projection or VerifiedProjection(workspace, event_sink=event_sink)
        draft_hash = sha256(operation.draft)
        operation_hash = sha256(operation)
        with read_only_transaction(workspace) as connection:
            if connection is None:
                return DomainWorkflowCondition(
                    draft_hash=draft_hash,
                    code="batch_not_approved",
                    detail="an approved nonstale batch is required",
                )
            basis = _domain_basis(workspace, connection, operation, projection)
            if isinstance(basis, (DomainDraftRepairOutcome, DomainWorkflowCondition)):
                return basis
            approved, active_revision, active_hash, remaining = basis
            existing_observation = _read_domain_observation(connection, operation_hash, approved)
            if existing_observation is not None and reuse_observation:
                if existing_observation.draft_hash != draft_hash:
                    raise ValueError("Domain validation observation draft identity is corrupt")
                if persist_observation:
                    try:
                        with transaction(workspace) as detail_connection:
                            ensure_judgment_detail(
                                detail_connection, existing_observation.candidate, approved
                            )
                    except (ValueError, TypeError) as error:
                        return DomainWorkflowCondition(
                            draft_hash=draft_hash,
                            code="judgment_detail_corrupt",
                            detail=str(error),
                        )
                compact = _compact_domain_validation(existing_observation)
                return (compact, existing_observation.candidate) if include_candidate else compact
            resolved_answers = _resolve_domain_answers(workspace, approved, operation, projection)
            if isinstance(resolved_answers, DomainWorkflowCondition):
                return resolved_answers
            active_answers, repairs = resolved_answers
            if repairs:
                emit_event(
                    event_sink,
                    RepairEvent(
                        surface=RepairSurface.DOMAIN,
                        outcome=RepairOutcome.DEFECTS,
                        defect_count=len(repairs),
                    ),
                )
                return DomainDraftRepairOutcome(
                    draft_hash=draft_hash,
                    repairs=repairs,
                )
            validation_time = datetime.now(UTC) if observed_at is None else observed_at
            mapping = {item.question_id: item.answer for item in active_answers}
            evaluation = evaluate_domain(operation.domain_id, mapping)
            override = None
            final_judgment = None
            if operation.draft.override is not None:
                final_judgment = operation.draft.override.final_judgment
                if final_judgment == evaluation.judgment:
                    repair = _domain_repair(
                        "/draft/override",
                        "override",
                        "mismatch",
                        "correct_override",
                    )
                    return DomainDraftRepairOutcome(
                        draft_hash=draft_hash,
                        repairs=(repair,),
                    )
                override = Override(
                    justification=operation.draft.override.justification,
                    actor=operation.actor,
                    observed_at=validation_time,
                )
            try:
                candidate = build_domain_judgment(
                    approved,
                    operation.trial_id,
                    operation.result_id,
                    operation.domain_id,
                    active_answers,
                    tuple(
                        InactiveQuestion(question_id=item)
                        for item in SCIENTIFIC_PACK.domains[
                            tuple(item.id for item in SCIENTIFIC_PACK.domains).index(
                                operation.domain_id
                            )
                        ].question_ids
                        if item not in mapping
                    ),
                    final_judgment,
                    override,
                    operation.draft.limitations,
                    operation.actor,
                    validation_time,
                )
            except (JudgmentValidationError, ValidationError):
                return DomainDraftRepairOutcome(
                    draft_hash=draft_hash,
                    repairs=(
                        _domain_repair(
                            "/draft",
                            "draft_shape",
                            "invalid",
                            "retry",
                        ),
                    ),
                )
            remaining = tuple(item for item in remaining if item != operation.domain_id)
            receipt = _domain_receipt(
                operation,
                draft_hash,
                candidate,
                active_revision,
                active_hash,
                validation_time,
                remaining,
            )
            observation = DomainValidationObservation(
                operation_hash=operation_hash,
                draft_hash=draft_hash,
                candidate=candidate,
                receipt=receipt,
            )
            result = _compact_domain_validation(observation)
            observation = observation.model_copy(update={"result": result})
            observation = observation.model_copy(
                update={
                    "observation_hash": sha256(observation.model_dump(exclude={"observation_hash"}))
                }
            )

        if not persist_observation:
            emit_event(
                event_sink,
                RepairEvent(
                    surface=RepairSurface.DOMAIN,
                    outcome=RepairOutcome.VALID,
                    defect_count=0,
                ),
            )
            compact = _compact_domain_validation(observation)
            return (compact, observation.candidate) if include_candidate else compact

        with transaction(workspace) as connection:
            current_basis = _domain_basis(workspace, connection, operation, projection)
            if isinstance(current_basis, (DomainDraftRepairOutcome, DomainWorkflowCondition)):
                return current_basis
            _approved, current_revision, current_hash, _current_remaining = current_basis
            if current_revision != active_revision or current_hash != active_hash:
                return DomainWorkflowCondition(
                    draft_hash=draft_hash,
                    code="predecessor_conflict",
                    detail="Domain state changed during validation",
                )
            existing = _read_domain_observation(connection, operation_hash, _approved)
            try:
                ensure_judgment_detail(
                    connection, candidate if existing is None else existing.candidate, _approved
                )
            except (ValueError, TypeError) as error:
                return DomainWorkflowCondition(
                    draft_hash=draft_hash,
                    code="judgment_detail_corrupt",
                    detail=str(error),
                )
            if existing is None:
                review = DomainReviewRecord(
                    operation_hash=operation_hash,
                    observation_hash=observation.observation_hash,
                    candidate=candidate,
                    receipt=receipt,
                )
                connection.execute(
                    "INSERT INTO records(name,payload) VALUES(?,?)",
                    (_domain_observation_key(operation_hash), canonical_json_bytes(observation)),
                )
                connection.execute(
                    "INSERT INTO records(name,payload) VALUES(?,?)",
                    (
                        f"domain_validation_observation_content:{observation.observation_hash}",
                        canonical_json_bytes(observation),
                    ),
                )
                connection.execute(
                    "INSERT INTO records(name,payload) VALUES(?,?)",
                    (_domain_review_key(operation_hash), canonical_json_bytes(review)),
                )
            else:
                observation = existing
        emit_event(
            event_sink,
            RepairEvent(
                surface=RepairSurface.DOMAIN,
                outcome=RepairOutcome.VALID,
                defect_count=0,
            ),
        )
        compact = _compact_domain_validation(observation)
        return (compact, observation.candidate) if include_candidate else compact


def _verified_domain_receipt(receipt: DomainValidationReceipt) -> None:
    if receipt.receipt_hash != sha256(receipt.model_dump(exclude={"receipt_hash"})):
        raise ValueError("Domain validation receipt identity is corrupt")


def _receipt_matches_candidate(
    receipt: DomainValidationReceipt,
    candidate: DomainJudgment,
    approved: ApprovedBatch,
) -> bool:
    """Check every receipt observation that can be reconstructed at commit time."""

    return (
        receipt.approved_batch_hash == approved.frozen_hash
        and receipt.pack_identities_hash
        == sha256((candidate.scientific_pack, candidate.policy_pack))
        and receipt.candidate_hash == candidate.checkpoint_hash
        and receipt.observed_at == candidate.observed_at
    )


def _same_commit_authority(
    original: DomainValidationReceipt, regenerated: DomainValidationReceipt
) -> bool:
    """Compare only the receipt facts that authorize this Domain commit.

    Other Domains may advance after validation. Their progress changes transport
    guidance, not the reviewed candidate or its same-Domain predecessor basis.
    """

    excluded = {"remaining_domains", "receipt_hash"}
    return original.model_dump(exclude=excluded) == regenerated.model_dump(exclude=excluded)


def validate_domain_draft_mapping(
    workspace: str | Path,
    *,
    approved_batch_hash: str,
    trial_id: str,
    result_id: str,
    domain_id: str,
    actor: str,
    expected_predecessor_hash: str | None,
    raw_draft: object,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> DomainDraftRepairResult | DomainDraftValidated:
    """Verify workflow authority before offering author-correctable Draft advice."""

    draft_hash = sha256(raw_draft)
    probe = DomainDraftOperation.model_construct(
        approved_batch_hash=approved_batch_hash,
        trial_id=trial_id,
        result_id=result_id,
        domain_id=domain_id,
        actor=actor,
        expected_predecessor_hash=expected_predecessor_hash,
        draft=raw_draft,
    )
    projection = VerifiedProjection(workspace, event_sink=event_sink)
    try:
        with read_only_transaction(workspace) as connection:
            if connection is None:
                return DomainWorkflowCondition(
                    draft_hash=draft_hash,
                    code="batch_not_approved",
                    detail="an approved nonstale batch is required",
                )
            basis = _domain_basis(workspace, connection, probe, projection)
            if isinstance(basis, (DomainDraftRepairOutcome, DomainWorkflowCondition)):
                return basis
    except (ValidationError, ValueError, TypeError) as error:
        return DomainWorkflowCondition(
            draft_hash=draft_hash,
            code="workflow_integrity_failure",
            detail=str(error),
        )
    try:
        draft = DomainDraft.model_validate(raw_draft)
    except ValidationError as error:
        repairs: list[DomainDraftRepair] = []
        for item in error.errors(include_url=False, include_context=False, include_input=False):
            location = tuple(str(part) for part in item["loc"])
            pointer = "/draft" + (
                ""
                if not location
                else "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in location)
            )
            error_type = str(item["type"])
            if error_type == "missing":
                actual = "missing"
                action = "correct_field"
            elif error_type == "extra_forbidden":
                actual = "extra"
                action = "remove_field"
            elif "type" in error_type or "parsing" in error_type:
                actual = "wrong_type"
                action = "correct_field"
            else:
                actual = "invalid"
                action = "correct_field"
            repairs.append(
                DomainDraftRepair(
                    pointer=pointer,
                    invariant="draft_schema",
                    actual=actual,
                    action=action,
                )
            )

        def repair_key(repair: DomainDraftRepair) -> tuple[str, str, str, str]:
            return (repair.pointer, repair.invariant, repair.actual, repair.action)

        return DomainDraftRepairOutcome(
            draft_hash=draft_hash,
            repairs=tuple(sorted(repairs, key=repair_key)),
        )
    return cast(
        DomainDraftRepairResult | DomainDraftValidated,
        validate_domain_draft(
            workspace,
            DomainDraftOperation(
                approved_batch_hash=approved_batch_hash,
                trial_id=trial_id,
                result_id=result_id,
                domain_id=domain_id,
                actor=actor,
                expected_predecessor_hash=expected_predecessor_hash,
                draft=draft,
            ),
            event_sink=event_sink,
            projection=projection,
        ),
    )


def _commit_condition(code: str, detail: str) -> DomainCommitCondition:
    return DomainCommitCondition(code=code, detail=detail)


def _changed_domain_paths(candidate: DomainJudgment, current: DomainJudgment) -> tuple[str, ...]:
    return tuple(
        f"/{field}"
        for field in DomainJudgment.model_fields
        if field != "checkpoint_hash" and getattr(candidate, field) != getattr(current, field)
    )


def _commit_success(
    workspace: str | Path,
    connection,
    approved: ApprovedBatch,
    candidate: DomainJudgment,
    active_revision: int,
) -> DomainCommitSuccess:
    from rob2_kit.packets import (
        VerifiedDomainPacketBasis,
        VerifiedSynthesisPacketBasis,
        build_approved_work_packet,
        build_trial_synthesis_packet,
    )

    success_key = f"domain_commit_success:{candidate.checkpoint_hash}"
    stored_success = connection.execute(
        "SELECT payload FROM records WHERE name=?", (success_key,)
    ).fetchone()
    observation_key = f"domain_commit_observation:{candidate.checkpoint_hash}"
    stored_observation = connection.execute(
        "SELECT payload FROM records WHERE name=?", (observation_key,)
    ).fetchone()
    active_key = judgment_key(
        approved.frozen_hash, candidate.trial_id, candidate.result_id, candidate.domain_id
    )
    committed_revision_row = connection.execute(
        "SELECT payload FROM records WHERE name=?",
        (revision_key(active_key, active_revision),),
    ).fetchone()
    if committed_revision_row is None:
        raise ValueError("Domain commit revision audit entry is unavailable")
    committed_revision = JudgmentRevision.model_validate_json(bytes(committed_revision_row[0]))
    if (stored_success is None) != (stored_observation is None):
        raise ValueError("Domain commit replay observation is incomplete")
    if (
        stored_success is None
        and stored_observation is None
        and committed_revision.commit_observation_hash is not None
    ):
        raise ValueError("Domain commit replay observation is incomplete")
    if stored_success is not None and stored_observation is not None:
        success = DomainCommitSuccess.model_validate_json(bytes(stored_success[0]))
        observation = DomainCommitObservation.model_validate_json(bytes(stored_observation[0]))
        expected_static = (
            success.approved_batch_hash == approved.frozen_hash
            and success.trial_id == candidate.trial_id
            and success.result_id == candidate.result_id
            and success.domain_id == candidate.domain_id
            and success.candidate_ref == detail_reference("judgment", candidate.checkpoint_hash)
            and success.active_revision == active_revision
            and success.active_hash == candidate.checkpoint_hash
        )
        packet_row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (f"detail:{success.next_packet_ref.kind}:{success.next_packet_ref.identity}",),
        ).fetchone()
        packet_valid = False
        expected_remaining: tuple[str, ...] = ()
        expected_action = success.next_action
        if packet_row is not None and success.next_packet_ref.kind == "domain":
            from rob2_kit.packets import ApprovedWorkPacket, verify_approved_work_packet

            packet = verify_approved_work_packet(
                ApprovedWorkPacket.model_validate_json(bytes(packet_row[0]))
            )
            packet_valid = (
                packet.packet_hash == success.next_packet_ref.identity
                and packet.approved_batch_hash == approved.frozen_hash
                and packet.trial.id == candidate.trial_id
                and packet.result.id == candidate.result_id
            )
            completed = {item.domain_id for item in packet.prior_domains}
            expected_remaining = tuple(
                item.id for item in SCIENTIFIC_PACK.domains if item.id not in completed
            )
            expected_action = packet.next_action
            packet_valid = (
                packet_valid
                and bool(expected_remaining)
                and (packet.domain_id == expected_remaining[0])
            )
        elif packet_row is not None and success.next_packet_ref.kind == "synthesis":
            from rob2_kit.packets import TrialSynthesisPacket, verify_trial_synthesis_packet

            packet = verify_trial_synthesis_packet(
                TrialSynthesisPacket.model_validate_json(bytes(packet_row[0]))
            )
            packet_valid = (
                packet.packet_hash == success.next_packet_ref.identity
                and packet.approved_batch_hash == approved.frozen_hash
                and packet.trial.id == candidate.trial_id
                and packet.result.id == candidate.result_id
            )
            expected_action = "finish_trial"
        expected_success = DomainCommitSuccess(
            approved_batch_hash=approved.frozen_hash,
            trial_id=candidate.trial_id,
            result_id=candidate.result_id,
            domain_id=candidate.domain_id,
            candidate_ref=detail_reference("judgment", candidate.checkpoint_hash),
            active_revision=active_revision,
            active_hash=candidate.checkpoint_hash,
            remaining_domains=expected_remaining,
            next_packet_ref=success.next_packet_ref,
            next_action=expected_action,
        )
        revision_row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (
                revision_key(
                    judgment_key(
                        approved.frozen_hash,
                        candidate.trial_id,
                        candidate.result_id,
                        candidate.domain_id,
                    ),
                    active_revision,
                ),
            ),
        ).fetchone()
        revision = (
            None
            if revision_row is None
            else JudgmentRevision.model_validate_json(bytes(revision_row[0]))
        )
        observation_content = observation.model_dump(exclude={"observation_hash"})
        content_row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (f"domain_commit_observation_content:{observation.observation_hash}",),
        ).fetchone()
        observation_valid = (
            observation.observation_hash == sha256(observation_content)
            and observation.success == success
            and observation.candidate_hash == candidate.checkpoint_hash
            and observation.active_revision == active_revision
            and observation.packet_content_hash
            == "sha256:" + hashlib.sha256(bytes(packet_row[0])).hexdigest()
            and observation.actor == candidate.actor
            and observation.approved_batch_hash == approved.frozen_hash
            and observation.pack_identities_hash == sha256(approved.pack_identities)
            and content_row is not None
            and bytes(content_row[0]) == bytes(stored_observation[0])
            and revision is not None
            and revision.commit_observation_hash == observation.observation_hash
        )
        if (
            not expected_static
            or not packet_valid
            or success != expected_success
            or not observation_valid
        ):
            raise ValueError("Domain commit success observation is corrupt")
        return success
    remaining = remaining_domains(approved, candidate.trial_id, candidate.result_id, connection)
    active = []
    for domain in SCIENTIFIC_PACK.domains:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (
                judgment_key(
                    approved.frozen_hash,
                    candidate.trial_id,
                    candidate.result_id,
                    domain.id,
                ),
            ),
        ).fetchone()
        if row is not None:
            active.append(_verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0]))))
    for judgment in active:
        ensure_judgment_detail(connection, judgment, approved)
    if remaining:
        packet = build_approved_work_packet(
            VerifiedDomainPacketBasis(
                approved_batch=approved,
                trial_id=candidate.trial_id,
                result_id=candidate.result_id,
                domain_id=remaining[0],
                prior_judgments=tuple(active),
                detail_refs=tuple(
                    detail_reference("judgment", item.checkpoint_hash) for item in active
                ),
            )
        )
        packet_kind = "domain"
        next_action = packet.next_action
    else:
        packet = build_trial_synthesis_packet(
            VerifiedSynthesisPacketBasis(
                approved_batch=approved,
                trial_id=candidate.trial_id,
                result_id=candidate.result_id,
                active_judgments=tuple(active),
                detail_refs=tuple(
                    detail_reference("judgment", item.checkpoint_hash) for item in active
                ),
            )
        )
        packet_kind = "synthesis"
        next_action = "finish_trial"
    connection.execute(
        "INSERT INTO records(name,payload) VALUES(?,?) "
        "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
        (f"detail:{packet_kind}:{packet.packet_hash}", canonical_json_bytes(packet)),
    )
    domain_ids = tuple(item.id for item in SCIENTIFIC_PACK.domains)
    correction_packet = build_approved_work_packet(
        VerifiedDomainPacketBasis(
            approved_batch=approved,
            trial_id=candidate.trial_id,
            result_id=candidate.result_id,
            domain_id=candidate.domain_id,
            active_judgment=candidate,
            active_revision=active_revision,
            predecessor_hash=candidate.checkpoint_hash,
            prior_judgments=tuple(
                item
                for item in active
                if domain_ids.index(item.domain_id) < domain_ids.index(candidate.domain_id)
            ),
            detail_refs=tuple(
                detail_reference("judgment", item.checkpoint_hash) for item in active
            ),
        )
    )
    connection.execute(
        "INSERT INTO records(name,payload) VALUES(?,?) "
        "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
        (
            f"detail:domain:{correction_packet.packet_hash}",
            canonical_json_bytes(correction_packet),
        ),
    )
    success = DomainCommitSuccess(
        approved_batch_hash=approved.frozen_hash,
        trial_id=candidate.trial_id,
        result_id=candidate.result_id,
        domain_id=candidate.domain_id,
        candidate_ref=detail_reference("judgment", candidate.checkpoint_hash),
        active_revision=active_revision,
        active_hash=candidate.checkpoint_hash,
        remaining_domains=remaining,
        next_packet_ref=detail_reference(packet_kind, packet.packet_hash),
        next_action=next_action,
    )
    connection.execute(
        "INSERT INTO records(name,payload) VALUES(?,?)",
        (success_key, canonical_json_bytes(success)),
    )
    packet_payload = canonical_json_bytes(packet)
    observation = DomainCommitObservation(
        success=success,
        candidate_hash=candidate.checkpoint_hash,
        active_revision=active_revision,
        packet_content_hash="sha256:" + hashlib.sha256(packet_payload).hexdigest(),
        actor=candidate.actor,
        approved_batch_hash=approved.frozen_hash,
        pack_identities_hash=sha256(approved.pack_identities),
        observation_hash="pending",
    )
    observation = observation.model_copy(
        update={"observation_hash": sha256(observation.model_dump(exclude={"observation_hash"}))}
    )
    observation_payload = canonical_json_bytes(observation)
    connection.execute(
        "INSERT INTO records(name,payload) VALUES(?,?)",
        (observation_key, observation_payload),
    )
    connection.execute(
        "INSERT INTO records(name,payload) VALUES(?,?)",
        (
            f"domain_commit_observation_content:{observation.observation_hash}",
            observation_payload,
        ),
    )
    revision_name = revision_key(active_key, active_revision)
    revision_row = connection.execute(
        "SELECT payload FROM records WHERE name=?", (revision_name,)
    ).fetchone()
    if revision_row is None:
        raise ValueError("Domain commit revision audit entry is unavailable")
    revision = JudgmentRevision.model_validate_json(bytes(revision_row[0])).model_copy(
        update={"commit_observation_hash": observation.observation_hash}
    )
    connection.execute(
        "UPDATE records SET payload=? WHERE name=?",
        (canonical_json_bytes(revision), revision_name),
    )
    return success


def commit_domain_draft(
    workspace: str | Path,
    operation: DomainDraftCommitOperation,
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> DomainCommitSuccess | DomainCommitConflict | DomainCommitCondition:
    """Commit only the exact receipt-bound candidate deliberately reviewed."""

    with measured_duration(event_sink, DurationOperation.DOMAIN_COMMIT):
        projection = VerifiedProjection(workspace, event_sink=event_sink)
        receipt = operation.validation_receipt
        try:
            _verified_domain_receipt(receipt)
        except ValueError as error:
            return _commit_condition("validation_receipt_corrupt", str(error))
        expected = {
            "approved_batch_hash": operation.approved_batch_hash,
            "trial_id": operation.trial_id,
            "result_id": operation.result_id,
            "domain_id": operation.domain_id,
            "draft_hash": sha256(operation.draft),
            "actor": operation.actor,
            "expected_predecessor_hash": operation.expected_predecessor_hash,
        }
        if any(getattr(receipt, key) != value for key, value in expected.items()):
            return _commit_condition(
                "validation_receipt_mismatch",
                "receipt does not bind the exact operation draft and actor",
            )
        if operation.reviewed_candidate_hash != receipt.candidate_hash:
            return _commit_condition(
                "reviewed_candidate_mismatch",
                "commit target is not the candidate in the validation receipt",
            )
        with read_only_transaction(workspace) as connection:
            if connection is None:
                return _commit_condition(
                    "batch_not_approved", "an approved nonstale batch is required"
                )
            state = current_batch_in_transaction(workspace, connection, projection=projection)
            if not isinstance(state, ApprovedBatch):
                return _commit_condition(
                    "batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                    "an approved nonstale batch is required",
                )
            if state.frozen_hash != operation.approved_batch_hash:
                return _commit_condition(
                    "approved_batch_mismatch",
                    "operation does not bind the active Approved Batch",
                )
            terminal = connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (f"terminal_trial:{state.frozen_hash}:{operation.trial_id}",),
            ).fetchone()
            if terminal is not None:
                return _commit_condition(
                    "trial_terminal", "Domain commits are forbidden after Trial terminalization"
                )
            key = judgment_key(
                state.frozen_hash,
                operation.trial_id,
                operation.result_id,
                operation.domain_id,
            )
            row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
            current_before: DomainJudgment | None = None
            current_revision_before: int | None = None
            if row is not None:
                try:
                    current_before = _verified_checkpoint(
                        DomainJudgment.model_validate_json(bytes(row[0]))
                    )
                    current_revision_before, _predecessor = verify_revision_history(
                        workspace,
                        connection,
                        state,
                        operation.trial_id,
                        operation.result_id,
                        operation.domain_id,
                        current_before,
                        projection,
                    )
                except (ValidationError, ValueError, TypeError) as error:
                    return _commit_condition("revision_history_corrupt", str(error))
            receipt_basis_matches = (
                (None if current_before is None else current_before.checkpoint_hash)
                == receipt.observed_active_hash
                and current_revision_before == receipt.observed_active_revision
            )
            revalidation_predecessor = (
                None if current_before is None else current_before.checkpoint_hash
            )
            validation_operation = DomainDraftOperation(
                approved_batch_hash=operation.approved_batch_hash,
                trial_id=operation.trial_id,
                result_id=operation.result_id,
                domain_id=operation.domain_id,
                actor=operation.actor,
                expected_predecessor_hash=operation.expected_predecessor_hash,
                draft=operation.draft,
            )
            try:
                observation = _read_domain_observation(
                    connection, sha256(validation_operation), state
                )
            except (ValidationError, ValueError, TypeError) as error:
                return _commit_condition("validation_observation_corrupt", str(error))
            if observation is None:
                return _commit_condition(
                    "validation_observation_missing",
                    "the immutable validation observation is unavailable",
                )
            observed_result = observation.result
            if observed_result is None or observed_result.receipt != receipt:
                return _commit_condition(
                    "validation_receipt_mismatch",
                    "the receipt does not match the immutable validation observation",
                )
            if (
                observed_result.candidate_hash != operation.reviewed_candidate_hash
                or observation.candidate.checkpoint_hash != operation.reviewed_candidate_hash
                or observation.candidate.actor != operation.actor
                or observation.candidate.observed_at != receipt.observed_at
                or observation.candidate.approved_batch_hash != state.frozen_hash
                or observation.candidate.trial_id != operation.trial_id
                or observation.candidate.result_id != operation.result_id
                or observation.candidate.domain_id != operation.domain_id
                or receipt.pack_identities_hash
                != sha256(
                    (
                        observation.candidate.scientific_pack,
                        observation.candidate.policy_pack,
                    )
                )
            ):
                return _commit_condition(
                    "validation_observation_mismatch",
                    "the immutable validation observation does not authorize this commit",
                )
        revalidated = validate_domain_draft(
            workspace,
            validation_operation.model_copy(
                update={"expected_predecessor_hash": revalidation_predecessor}
            ),
            event_sink=event_sink,
            observed_at=receipt.observed_at,
            reuse_observation=False,
            persist_observation=False,
            include_candidate=True,
            projection=projection,
        )
        if not isinstance(revalidated, tuple):
            if isinstance(revalidated, DomainWorkflowCondition):
                return _commit_condition(revalidated.code, revalidated.detail)
            return _commit_condition(
                "candidate_invalidated",
                "draft or Evidence no longer reconstructs the reviewed candidate",
            )
        revalidated, candidate_judgment = revalidated
        if revalidated.candidate_hash != operation.reviewed_candidate_hash:
            return _commit_condition(
                "candidate_hash_mismatch",
                "reconstructed candidate differs from the reviewed candidate",
            )
        if not _receipt_matches_candidate(receipt, candidate_judgment, state):
            return _commit_condition(
                "validation_receipt_mismatch",
                "receipt does not bind the reconstructed candidate and Approved Batch packs",
            )
        if receipt_basis_matches and not _same_commit_authority(receipt, revalidated.receipt):
            return _commit_condition(
                "validation_receipt_mismatch",
                "revalidation does not reproduce the validation receipt",
            )
        with transaction(workspace) as connection:
            state = current_batch_in_transaction(workspace, connection, projection=projection)
            if not isinstance(state, ApprovedBatch):
                return _commit_condition(
                    "batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                    "an approved nonstale batch is required",
                )
            if state.frozen_hash != operation.approved_batch_hash:
                return _commit_condition(
                    "approved_batch_mismatch",
                    "operation does not bind the active Approved Batch",
                )
            terminal = connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (f"terminal_trial:{state.frozen_hash}:{operation.trial_id}",),
            ).fetchone()
            if terminal is not None:
                return _commit_condition(
                    "trial_terminal", "Domain commits are forbidden after Trial terminalization"
                )
            key = judgment_key(
                state.frozen_hash,
                operation.trial_id,
                operation.result_id,
                operation.domain_id,
            )
            row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
            current: DomainJudgment | None = None
            current_revision: int | None = None
            if row is not None:
                try:
                    current = _verified_checkpoint(
                        DomainJudgment.model_validate_json(bytes(row[0]))
                    )
                    current_revision, _predecessor = verify_revision_history(
                        workspace,
                        connection,
                        state,
                        operation.trial_id,
                        operation.result_id,
                        operation.domain_id,
                        current,
                        projection,
                    )
                except (ValidationError, ValueError, TypeError) as error:
                    return _commit_condition("revision_history_corrupt", str(error))
            current_hash = None if current is None else current.checkpoint_hash
            try:
                ensure_judgment_detail(connection, candidate_judgment, state)
                if current is not None:
                    ensure_judgment_detail(connection, current, state)
            except (ValueError, TypeError) as error:
                return _commit_condition("judgment_detail_corrupt", str(error))
            if current is not None and current_hash == candidate_judgment.checkpoint_hash:
                return _commit_success(workspace, connection, state, current, current_revision or 1)
            if (
                current_hash != receipt.observed_active_hash
                or current_revision != receipt.observed_active_revision
            ):
                if current is None:
                    current_ref = None
                else:
                    current_ref = detail_reference("judgment", current.checkpoint_hash)
                return DomainCommitConflict(
                    approved_batch_hash=state.frozen_hash,
                    trial_id=operation.trial_id,
                    result_id=operation.result_id,
                    domain_id=operation.domain_id,
                    expected_predecessor_hash=operation.expected_predecessor_hash,
                    current_ref=current_ref,
                    current_active_revision=current_revision,
                    current_active_hash=current_hash,
                    changed_paths=()
                    if current is None
                    else _changed_domain_paths(candidate_judgment, current),
                )
            next_revision = 1 if current is None else (current_revision or 0) + 1
            if current is None:
                connection.execute(
                    "INSERT INTO records(name,payload) VALUES(?,?)",
                    (key, canonical_json_bytes(candidate_judgment)),
                )
                previous_hash = None
            else:
                previous_hash = current.checkpoint_hash
                connection.execute(
                    "UPDATE records SET payload=? WHERE name=?",
                    (canonical_json_bytes(candidate_judgment), key),
                )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (
                    revision_key(key, next_revision),
                    canonical_json_bytes(
                        JudgmentRevision(
                            active_key=key,
                            revision=next_revision,
                            previous_hash=previous_hash,
                            judgment=candidate_judgment,
                        )
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                (
                    revision_index_key(key),
                    canonical_json_bytes(
                        JudgmentRevisionIndex(
                            active_key=key,
                            active_revision=next_revision,
                            active_hash=candidate_judgment.checkpoint_hash,
                        )
                    ),
                ),
            )
            return _commit_success(workspace, connection, state, candidate_judgment, next_revision)
