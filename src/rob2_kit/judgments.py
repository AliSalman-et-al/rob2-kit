"""Versioned working Domain judgments and immutable audit history for one RoB 2 domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

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
from rob2_kit.storage import read_only_transaction, transaction


class _ActiveJudgmentResult(StrictModel):
    judgment: DomainJudgment
    active_revision: int = Field(ge=1)
    active_hash: str
    remaining_domains: tuple[str, ...]

    @model_validator(mode="after")
    def active_hash_matches_judgment(self):
        if self.active_hash != self.judgment.checkpoint_hash:
            raise ValueError("active hash must match the returned judgment")
        return self


class JudgmentSaved(_ActiveJudgmentResult):
    status: Literal["saved"] = "saved"


class JudgmentRevised(_ActiveJudgmentResult):
    status: Literal["revised"] = "revised"


class JudgmentConflict(_ActiveJudgmentResult):
    status: Literal["conflict"] = "conflict"


class JudgmentCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


class JudgmentValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


SaveDomainJudgmentResult = JudgmentSaved | JudgmentRevised | JudgmentConflict | JudgmentCondition


class DomainJudgmentPayload(StrictModel):
    """The complete payload that is first checked, then committed unchanged."""

    trial_id: str
    result_id: str
    domain_id: str
    active_answers: tuple[ActiveAnswer, ...]
    inactive_questions: tuple[InactiveQuestion, ...]
    final_judgment: Judgment | None
    override: Override | None
    limitations: tuple[str, ...]
    actor: str
    observed_at: datetime
    expected_previous_hash: str | None = None


class ValidationReceipt(StrictModel):
    """Deterministic proof that this exact payload passed the read-only gate."""

    approved_batch_hash: str
    trial_id: str
    result_id: str
    domain_id: str
    payload_hash: str
    expected_previous_hash: str | None
    observed_active_revision: int | None = None
    observed_active_hash: str | None = None
    proposed_status: Literal["saved", "revised"]
    proposed_judgment_hash: str
    remaining_domains: tuple[str, ...]
    pack_identities_hash: str
    receipt_hash: str
    commit_token: str


class JudgmentValidated(StrictModel):
    status: Literal["validated"] = "validated"
    judgment: DomainJudgment
    receipt: ValidationReceipt
    next_action: Literal["review_then_commit"] = "review_then_commit"


class ScientificPreflight(StrictModel):
    """A deliberate review assertion, not a claim of scientific truth or identity."""

    payload_final: bool
    citations_checked_against_pages: bool
    contradictions_addressed: bool
    activation_and_partition_reviewed: bool


ValidateDomainJudgmentResult = JudgmentValidated | JudgmentConflict | JudgmentCondition


@dataclass(frozen=True)
class _Evaluation:
    judgment: DomainJudgment
    existing: DomainJudgment | None
    active_revision: int | None
    active_hash: str | None
    remaining_domains: tuple[str, ...]


class JudgmentRevision(StrictModel):
    """One append-only audit entry; the unversioned checkpoint key is the active revision."""

    active_key: str
    revision: int = Field(ge=1)
    previous_hash: str | None = None
    judgment: DomainJudgment


class JudgmentRevisionIndex(StrictModel):
    active_key: str
    active_revision: int = Field(ge=1)
    active_hash: str


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
) -> tuple[int, str | None]:
    """Verify audit revisions; an index-less record is legacy only when no audit entry binds it."""
    active_key = judgment_key(state.frozen_hash, trial_id, result_id, domain_id)
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
        if entries:
            raise ValueError("Domain judgment revision history is missing its index")
        return 1, None
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
                    _validate_evidence(workspace, state, trial_id, result_id, ref)
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


def _result_spec(approved: ApprovedBatch, trial_id: str, result_id: str):
    spec = next((item for item in approved.proposal.result_specs if item.id == result_id), None)
    if spec is None or spec.trial.id != trial_id:
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
) -> None:
    source = _source(approved, trial_id, result_id, ref.source_id)
    if source.sha256 != ref.source_sha256:
        raise JudgmentValidationError(
            "evidence_invalid", "evidence Source hash does not match approved inventory"
        )
    root = Path(workspace).resolve(strict=True)
    pages = _extract_pages(_source_bytes(root, source), source.media_type)
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


def _receipt(
    state: ApprovedBatch,
    payload: DomainJudgmentPayload,
    judgment: DomainJudgment,
    active_revision: int | None,
    active_hash: str | None,
    proposed_status: Literal["saved", "revised"],
    remaining: tuple[str, ...],
) -> ValidationReceipt:
    content = {
        "approved_batch_hash": state.frozen_hash,
        "trial_id": payload.trial_id,
        "result_id": payload.result_id,
        "domain_id": payload.domain_id,
        "payload_hash": sha256(payload),
        "expected_previous_hash": payload.expected_previous_hash,
        "observed_active_revision": active_revision,
        "observed_active_hash": active_hash,
        "proposed_status": proposed_status,
        "proposed_judgment_hash": judgment.checkpoint_hash,
        "remaining_domains": remaining,
        "pack_identities_hash": sha256(state.pack_identities),
    }
    receipt_hash = sha256(content)
    return ValidationReceipt(
        **content,
        receipt_hash=receipt_hash,
        commit_token=sha256({"purpose": "domain_judgment_commit", "receipt_hash": receipt_hash}),
    )


def _evaluate(
    workspace: str | Path, connection, state: ApprovedBatch, payload: DomainJudgmentPayload
) -> _Evaluation | JudgmentCondition | JudgmentConflict:
    if connection.execute(
        "SELECT 1 FROM records WHERE name=?",
        (f"terminal_trial:{state.frozen_hash}:{payload.trial_id}",),
    ).fetchone():
        return JudgmentCondition(
            code="trial_terminal", detail="terminal Trials cannot accept revised Domain judgments"
        )
    judgment = build_domain_judgment(
        state,
        payload.trial_id,
        payload.result_id,
        payload.domain_id,
        payload.active_answers,
        payload.inactive_questions,
        payload.final_judgment,
        payload.override,
        payload.limitations,
        payload.actor,
        payload.observed_at,
    )
    for answer in payload.active_answers:
        for use in answer.evidence_uses:
            for ref in use.refs:
                _validate_evidence(workspace, state, payload.trial_id, payload.result_id, ref)
    key = judgment_key(state.frozen_hash, payload.trial_id, payload.result_id, payload.domain_id)
    row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
    remaining = remaining_domains(state, payload.trial_id, payload.result_id, connection)
    if row is None:
        if payload.expected_previous_hash is not None:
            return JudgmentCondition(
                code="checkpoint_absent",
                detail="a first Domain judgment must not specify expected_previous_hash",
            )
        return _Evaluation(
            judgment,
            None,
            None,
            None,
            tuple(item for item in remaining if item != payload.domain_id),
        )
    try:
        existing = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0])))
    except (ValidationError, ValueError) as error:
        return JudgmentCondition(code="revision_history_corrupt", detail=str(error))
    try:
        revision, predecessor = verify_revision_history(
            workspace,
            connection,
            state,
            payload.trial_id,
            payload.result_id,
            payload.domain_id,
            existing,
        )
    except (TypeError, ValueError) as error:
        return JudgmentCondition(code="revision_history_corrupt", detail=str(error))
    if existing == judgment and (
        payload.expected_previous_hash == existing.checkpoint_hash
        or payload.expected_previous_hash == predecessor
        or payload.expected_previous_hash is None
        and revision == 1
    ):
        return _Evaluation(judgment, existing, revision, existing.checkpoint_hash, remaining)
    if payload.expected_previous_hash != existing.checkpoint_hash:
        return JudgmentConflict(
            judgment=existing,
            active_revision=revision,
            active_hash=existing.checkpoint_hash,
            remaining_domains=remaining,
        )
    return _Evaluation(judgment, existing, revision, existing.checkpoint_hash, remaining)


def validate_domain_judgment(
    workspace: str | Path, payload: DomainJudgmentPayload
) -> ValidateDomainJudgmentResult:
    """Run all deterministic checks without writing a checkpoint or revision history."""
    with read_only_transaction(workspace) as connection:
        if connection is None:
            return JudgmentCondition(
                code="batch_not_approved", detail="an approved nonstale batch is required"
            )
        state = current_batch_in_transaction(workspace, connection)
        if not isinstance(state, ApprovedBatch):
            return JudgmentCondition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        try:
            evaluated = _evaluate(workspace, connection, state, payload)
        except JudgmentValidationError as error:
            return JudgmentCondition(code=error.code, detail=error.detail)
        except ValidationError as error:
            return JudgmentCondition(code="judgment_invalid", detail=str(error))
        if isinstance(evaluated, JudgmentCondition | JudgmentConflict):
            return evaluated
        judgment = evaluated.judgment
        existing = evaluated.existing
        revision = evaluated.active_revision
        active_hash = evaluated.active_hash
        remaining = evaluated.remaining_domains
        status: Literal["saved", "revised"] = (
            "saved" if existing is None or existing == judgment else "revised"
        )
        return JudgmentValidated(
            judgment=judgment,
            receipt=_receipt(state, payload, judgment, revision, active_hash, status, remaining),
        )


def commit_domain_judgment(
    workspace: str | Path,
    payload: DomainJudgmentPayload,
    receipt: ValidationReceipt | None,
    preflight: ScientificPreflight | None,
) -> SaveDomainJudgmentResult:
    """Commit only a whole-payload review that still matches its validation receipt."""
    if receipt is None:
        return JudgmentCondition(
            code="validation_receipt_required", detail="commit requires a validation receipt"
        )
    if preflight is None:
        return JudgmentCondition(
            code="scientific_preflight_required",
            detail="commit requires all preflight attestations",
        )
    if not all(preflight.model_dump().values()):
        return JudgmentCondition(
            code="scientific_preflight_invalid",
            detail="all scientific preflight attestations must be true",
        )
    with transaction(workspace) as connection:
        state = current_batch_in_transaction(workspace, connection)
        if not isinstance(state, ApprovedBatch):
            return JudgmentCondition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        try:
            evaluated = _evaluate(workspace, connection, state, payload)
        except JudgmentValidationError as error:
            return JudgmentCondition(code=error.code, detail=error.detail)
        except ValidationError as error:
            return JudgmentCondition(code="judgment_invalid", detail=str(error))
        if isinstance(evaluated, JudgmentCondition | JudgmentConflict):
            return evaluated
        judgment = evaluated.judgment
        existing = evaluated.existing
        revision = evaluated.active_revision
        active_hash = evaluated.active_hash
        remaining = evaluated.remaining_domains
        status: Literal["saved", "revised"] = (
            "saved" if existing is None or existing == judgment else "revised"
        )
        expected_receipt = _receipt(
            state, payload, judgment, revision, active_hash, status, remaining
        )
        replay_receipt = None
        if existing == judgment:
            if payload.expected_previous_hash is None and revision == 1:
                replay_receipt = _receipt(
                    state,
                    payload,
                    judgment,
                    None,
                    None,
                    "saved",
                    remaining,
                )
            elif payload.expected_previous_hash is not None and revision is not None:
                replay_receipt = _receipt(
                    state,
                    payload,
                    judgment,
                    revision - 1,
                    payload.expected_previous_hash,
                    "revised",
                    remaining,
                )
        if receipt not in (expected_receipt, replay_receipt):
            return JudgmentCondition(
                code="validation_receipt_mismatch",
                detail="receipt, token, payload, active state, or pack identities no longer match",
            )
        key = judgment_key(
            state.frozen_hash, payload.trial_id, payload.result_id, payload.domain_id
        )
        if existing is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (key, canonical_json_bytes(judgment)),
            )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (
                    revision_key(key, 1),
                    canonical_json_bytes(
                        JudgmentRevision(active_key=key, revision=1, judgment=judgment)
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (
                    revision_index_key(key),
                    canonical_json_bytes(
                        JudgmentRevisionIndex(
                            active_key=key, active_revision=1, active_hash=judgment.checkpoint_hash
                        )
                    ),
                ),
            )
            return JudgmentSaved(
                judgment=judgment,
                active_revision=1,
                active_hash=judgment.checkpoint_hash,
                remaining_domains=remaining,
            )
        if existing == judgment:
            return JudgmentSaved(
                judgment=existing,
                active_revision=revision or 1,
                active_hash=existing.checkpoint_hash,
                remaining_domains=remaining,
            )
        if (
            revision == 1
            and connection.execute(
                "SELECT 1 FROM records WHERE name=?", (revision_index_key(key),)
            ).fetchone()
            is None
        ):
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (
                    revision_key(key, 1),
                    canonical_json_bytes(
                        JudgmentRevision(active_key=key, revision=1, judgment=existing)
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (
                    revision_index_key(key),
                    canonical_json_bytes(
                        JudgmentRevisionIndex(
                            active_key=key,
                            active_revision=1,
                            active_hash=existing.checkpoint_hash,
                        )
                    ),
                ),
            )
        next_revision = (revision or 0) + 1
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (
                revision_key(key, next_revision),
                canonical_json_bytes(
                    JudgmentRevision(
                        active_key=key,
                        revision=next_revision,
                        previous_hash=existing.checkpoint_hash,
                        judgment=judgment,
                    )
                ),
            ),
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?", (canonical_json_bytes(judgment), key)
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (
                canonical_json_bytes(
                    JudgmentRevisionIndex(
                        active_key=key,
                        active_revision=next_revision,
                        active_hash=judgment.checkpoint_hash,
                    )
                ),
                revision_index_key(key),
            ),
        )
        return JudgmentRevised(
            judgment=judgment,
            active_revision=next_revision,
            active_hash=judgment.checkpoint_hash,
            remaining_domains=remaining,
        )
