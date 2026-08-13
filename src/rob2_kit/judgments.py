"""Immutable, evidence-bound checkpoints for one RoB 2 domain."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from rob2_kit.batch import (
    ApprovedBatch,
    StaleBatch,
    current_batch_in_transaction,
)
from rob2_kit.judgment_models import (
    ActiveAnswer,
    DomainJudgment,
    InactiveQuestion,
    Override,
    TextEvidenceRef,
    VisualEvidenceRef,
)
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.models import Judgment, StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.rendering import RenderedPage, render_page
from rob2_kit.search import _source_bytes
from rob2_kit.sources import Source, _extract_pages
from rob2_kit.storage import transaction


class JudgmentSaved(StrictModel):
    status: Literal["saved"] = "saved"
    judgment: DomainJudgment


class JudgmentConflict(StrictModel):
    status: Literal["conflict"] = "conflict"
    judgment: DomainJudgment


class JudgmentCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


SaveDomainJudgmentResult = JudgmentSaved | JudgmentConflict | JudgmentCondition


def checkpoint_content(judgment: DomainJudgment) -> dict[str, object]:
    """Return exactly the checkpoint bytes protected by ``checkpoint_hash``."""
    return judgment.model_dump(mode="python", exclude={"checkpoint_hash"})


def _verified_checkpoint(judgment: DomainJudgment) -> DomainJudgment:
    if judgment.checkpoint_hash != sha256(checkpoint_content(judgment)):
        raise ValueError("checkpoint integrity verification failed")
    return judgment


def _result_spec(approved: ApprovedBatch, trial_id: str, result_id: str):
    spec = next((item for item in approved.proposal.result_specs if item.id == result_id), None)
    if spec is None or spec.trial.id != trial_id:
        raise ValueError("ResultSpec does not belong to trial")
    return spec


def _source(approved: ApprovedBatch, trial_id: str, result_id: str, source_id: str) -> Source:
    spec = _result_spec(approved, trial_id, result_id)
    source = next((item for item in approved.proposal.sources if item.id == source_id), None)
    if source is None or source.trial_id != spec.trial.id:
        raise ValueError("evidence Source is not in ResultSpec trial approved inventory")
    return source


def _validate_evidence(
    workspace: str | Path,
    approved: ApprovedBatch,
    trial_id: str,
    result_id: str,
    ref: TextEvidenceRef | VisualEvidenceRef,
) -> None:
    source = _source(approved, trial_id, result_id, ref.source_id)
    if source.sha256 != ref.source_sha256:
        raise ValueError("evidence Source hash does not match approved inventory")
    root = Path(workspace).resolve(strict=True)
    pages = _extract_pages(_source_bytes(root, source), source.media_type)
    if ref.page_number > len(pages):
        raise ValueError("evidence page is outside captured Source")
    page = pages[ref.page_number - 1]
    if ref.kind == "text":
        if (
            ref.end > len(page)
            or ref.end - ref.start != len(ref.quote)
            or page[ref.start : ref.end] != ref.quote
        ):
            raise ValueError("text evidence coordinates do not match captured Source")
        return
    if ref.transcription not in page:
        raise ValueError("visual transcription is not attributable to captured Source page")
    rendered = render_page(
        workspace,
        source,
        ref.page_number,
        None if ref.origin.value == "rendered_page" else ref.region,
    )
    if not isinstance(rendered, RenderedPage) or rendered.sha256 != ref.image_sha256:
        raise ValueError("visual evidence does not match captured render")


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
        raise ValueError("unknown domain")
    mapping = {item.question_id: item.answer for item in active_answers}
    if len(mapping) != len(active_answers):
        raise ValueError("active answers must be unique")
    active = set(active_questions(mapping)) & set(domain.question_ids)
    inactive = {item.question_id for item in inactive_questions}
    if set(mapping) != active or inactive != set(domain.question_ids) - active:
        raise ValueError("active and inactive questions must exactly partition the Domain")
    evaluation = evaluate_domain(domain_id, mapping)
    final = evaluation.judgment if final_judgment is None else final_judgment
    if (final != evaluation.judgment) != (override is not None):
        raise ValueError("override is required exactly when final judgment differs")
    packs = {item.id: item for item in approved.pack_identities}
    try:
        scientific_pack = packs[SCIENTIFIC_PACK.id]
        policy_pack = packs[MAINTAINER_POLICY_PACK.id]
    except KeyError as error:
        raise ValueError("approved batch has incomplete pack identities") from error
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


def save_domain_judgment(
    workspace: str | Path,
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
) -> SaveDomainJudgmentResult:
    """Validate and atomically save an immutable domain checkpoint."""
    with transaction(workspace) as connection:
        state = current_batch_in_transaction(workspace, connection)
        if not isinstance(state, ApprovedBatch):
            return JudgmentCondition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        judgment = build_domain_judgment(
            state,
            trial_id,
            result_id,
            domain_id,
            active_answers,
            inactive_questions,
            final_judgment,
            override,
            limitations,
            actor,
            observed_at,
        )
        for answer in active_answers:
            for use in answer.evidence_uses:
                for ref in use.refs:
                    _validate_evidence(workspace, state, trial_id, result_id, ref)
        key = f"domain_judgment:{state.frozen_hash}:{trial_id}:{result_id}:{domain_id}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (key, canonical_json_bytes(judgment)),
            )
            return JudgmentSaved(judgment=judgment)
        existing = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0])))
        return (
            JudgmentSaved(judgment=existing)
            if existing == judgment
            else JudgmentConflict(judgment=existing)
        )
