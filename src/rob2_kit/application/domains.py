"""Application Domain candidate validation and Transition-only commit."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.judgment_models import EvidenceRelationship
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.models import Answer, Judgment
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.storage import workspace_mutation_lock

from ._state import identity, read_json, record_uri, write_jsons
from .contracts import (
    Continuation,
    EvidenceReference,
    PrepareTrialFinishContinuation,
    RecordKind,
    RecordReference,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    TransitionReference,
    ValidateDomainJudgmentContinuation,
)
from .evidence import list_sources, resolve_evidence
from .transitions import issue_transition, read_transition


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DomainEvidenceUseInput(_Closed):
    relationship: EvidenceRelationship
    claim: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)


class DomainAnswerInput(_Closed):
    question_id: str = Field(min_length=1)
    answer: Answer
    rationale: str = Field(min_length=1)
    evidence_uses: tuple[DomainEvidenceUseInput, ...] = Field(min_length=1)


class DomainOverrideInput(_Closed):
    final_judgment: Judgment
    justification: str = Field(min_length=1)


class DomainDraftInput(_Closed):
    active_answers: tuple[DomainAnswerInput, ...]
    limitations: tuple[str, ...] = ()
    override: DomainOverrideInput | None = None


class DomainValidationRequest(_Closed):
    packet: RecordReference
    draft: DomainDraftInput


class DomainRepair(_Closed):
    pointer: str
    code: str
    detail: str
    next_action: str = "correct_field"


class DomainValidationResult(_Closed):
    outcome: Literal["success"] = "success"
    candidate: RecordReference
    transition: TransitionReference
    candidate_hash: str
    draft_hash: str
    proposed_judgment: Judgment
    inactive_questions: tuple[str, ...]
    next_action: Literal["review_then_commit"] = "review_then_commit"


class DomainRepairResult(_Closed):
    outcome: Literal["repair"] = "repair"
    draft_hash: str
    repairs: tuple[DomainRepair, ...]


class DomainCondition(_Closed):
    outcome: Literal["condition"] = "condition"
    code: str
    detail: str
    next_action: Continuation


def _domain_ids() -> tuple[str, ...]:
    return tuple(domain.id for domain in SCIENTIFIC_PACK.domains)


def _packet_record(workspace: str | Path, packet: RecordReference) -> dict[str, object]:
    """Resolve a server-issued packet; an Approved Batch is accepted for its first Domain."""
    if packet.kind is RecordKind.APPROVED_WORK_PACKET:
        raw = read_json(workspace, f"domain-packet-{packet.identity.removeprefix('sha256:')}.json")
        if raw is None or raw.get("identity") != packet.identity:
            raise ValueError("Domain work packet is unavailable or corrupt")
        return raw
    if packet.kind is not RecordKind.APPROVED_BATCH:
        raise ValueError("Domain work requires the server-issued work packet")
    raw = read_json(workspace, "approved_batch.json")
    if raw is None or raw.get("identity") != packet.identity:
        raise ValueError("Approved Batch reference is stale")
    rows = cast(list[list[object]], raw.get("dispositions", []))
    pending = sorted(str(row[0]) for row in rows if len(row) >= 2 and row[1] == "pending")
    if not pending:
        raise ValueError("Approved Batch has no pending Trial")
    domain_id = _domain_ids()[0]
    return {
        "kind": "work_packet",
        "approved_batch": packet.model_dump(mode="json"),
        "trial_id": pending[0],
        "result_id": "result",
        "domain_id": domain_id,
        "active_question_ids": tuple(
            q.id for q in SCIENTIFIC_PACK.questions if q.domain_id == domain_id
        ),
        "allowed_question_ids": tuple(
            q.id for q in SCIENTIFIC_PACK.questions if q.domain_id == domain_id
        ),
        "stable_aliases": (),
        "prior_domain_hashes": (),
        "scientific_pack": SCIENTIFIC_PACK.content_hash,
        "policy_pack": MAINTAINER_POLICY_PACK.content_hash,
    }


def prepare_domain_packet(
    workspace: str | Path,
    approved_batch: RecordReference,
    *,
    trial_id: str,
    domain_id: str,
    result_id: str = "result",
) -> RecordReference:
    """Create a deterministic per-Domain packet from the approved Batch."""
    if approved_batch.kind is not RecordKind.APPROVED_BATCH:
        raise ValueError("a work packet starts at an Approved Batch")
    approved_raw = read_json(workspace, "approved_batch.json")
    if approved_raw is None or approved_raw.get("identity") != approved_batch.identity:
        raise ValueError("Approved Batch reference is stale")
    rows = cast(list[list[object]], approved_raw.get("dispositions", []))
    pending = {str(row[0]) for row in rows if len(row) >= 2 and row[1] == "pending"}
    if trial_id not in pending:
        raise ValueError("Trial is not pending in the Approved Batch")
    if domain_id not in _domain_ids():
        raise ValueError("unknown Domain")
    state = read_json(workspace, "state.json") or {}
    domains = state.get("domains", {})
    prior = (
        tuple(
            sorted(
                (key.rsplit(":", 1)[-1], str(value[-1]))
                for key, value in domains.items()
                if key.startswith(f"{trial_id}:{result_id}:") and isinstance(value, list) and value
            )
        )
        if isinstance(domains, dict)
        else ()
    )
    aliases = tuple(source.alias for source in list_sources(workspace, trial_id))
    payload = {
        "kind": "work_packet",
        "approved_batch": approved_batch.model_dump(mode="json"),
        "trial_id": trial_id,
        "result_id": result_id,
        "domain_id": domain_id,
        "active_question_ids": tuple(
            q.id for q in SCIENTIFIC_PACK.questions if q.domain_id == domain_id
        ),
        "allowed_question_ids": tuple(
            q.id for q in SCIENTIFIC_PACK.questions if q.domain_id == domain_id
        ),
        "stable_aliases": aliases,
        "prior_domain_hashes": prior,
        "scientific_pack": SCIENTIFIC_PACK.content_hash,
        "policy_pack": MAINTAINER_POLICY_PACK.content_hash,
    }
    packet_identity = identity(payload)
    state["work_packet_identity"] = packet_identity
    write_jsons(
        workspace,
        {
            f"domain-packet-{packet_identity.removeprefix('sha256:')}.json": {
                **payload,
                "identity": packet_identity,
            },
            "state.json": state,
        },
    )
    return RecordReference(
        kind=RecordKind.APPROVED_WORK_PACKET,
        identity=packet_identity,
        uri=record_uri(RecordKind.APPROVED_WORK_PACKET.value, packet_identity),
    )


def _evidence(
    workspace: str | Path, use: DomainEvidenceUseInput, trial_id: str
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for reference in use.evidence:
        record = resolve_evidence(workspace, reference)
        if record.trial_id != trial_id:
            raise ValueError("Evidence is outside the Trial scope")
        records.append(
            {
                "evidence": reference.model_dump(mode="json"),
                "relationship": use.relationship.value,
                "claim": use.claim,
                "rationale": use.rationale,
                **record.model_dump(mode="json"),
            }
        )
    return records


def _candidate(
    workspace: str | Path, packet: RecordReference, draft: DomainDraftInput
) -> tuple[dict[str, object], tuple[DomainRepair, ...]]:
    raw = _packet_record(workspace, packet)
    trial_id = str(raw["trial_id"])
    result_id = str(raw.get("result_id", "result"))
    domain_id = str(raw["domain_id"])
    known = set(cast(list[str] | tuple[str, ...], raw.get("active_question_ids", ())))
    if not known:
        known = {item.id for item in SCIENTIFIC_PACK.questions if item.domain_id == domain_id}
    answers = {item.question_id: item.answer for item in draft.active_answers}
    repairs: list[DomainRepair] = []
    evidence_bindings: list[dict[str, object]] = []
    if len(answers) != len(draft.active_answers):
        repairs.append(
            DomainRepair(
                pointer="/active_answers", code="duplicate", detail="question IDs must be unique"
            )
        )
    for index, answer in enumerate(draft.active_answers):
        if answer.question_id not in known:
            repairs.append(
                DomainRepair(
                    pointer=f"/active_answers/{index}/question_id",
                    code="unknown",
                    detail="question is not active in this Domain",
                )
            )
        for use_index, use in enumerate(answer.evidence_uses):
            try:
                evidence_bindings.extend(_evidence(workspace, use, trial_id))
            except ValueError as error:
                repairs.append(
                    DomainRepair(
                        pointer=f"/active_answers/{index}/evidence_uses/{use_index}",
                        code="invalid",
                        detail=str(error),
                        next_action="replace_evidence",
                    )
                )
    try:
        active = set(active_questions(answers)) & known
    except ValueError as error:
        repairs.append(DomainRepair(pointer="/active_answers", code="invalid", detail=str(error)))
        active = set()
    if set(answers) != active:
        repairs.append(
            DomainRepair(
                pointer="/active_answers",
                code="mismatch",
                detail=f"active questions must be exactly {sorted(active)}",
            )
        )
    if repairs:
        return {}, tuple(sorted(repairs, key=lambda item: (item.pointer, item.code, item.detail)))
    try:
        proposed = (
            draft.override.final_judgment
            if draft.override is not None
            else evaluate_domain(domain_id, answers).judgment
        )
    except ValueError as error:
        return {}, (DomainRepair(pointer="/active_answers", code="invalid", detail=str(error)),)
    candidate = {
        "kind": "domain_candidate",
        "packet": packet.model_dump(mode="json"),
        "trial_id": trial_id,
        "result_id": result_id,
        "domain_id": domain_id,
        "draft": draft.model_dump(mode="json"),
        "proposed_judgment": proposed.value,
        "inactive_questions": sorted(known - active),
        "evidence_bindings": evidence_bindings,
        "scientific_pack": SCIENTIFIC_PACK.content_hash,
        "policy_pack": MAINTAINER_POLICY_PACK.content_hash,
    }
    candidate["identity"] = identity(candidate)
    return candidate, ()


def validate_domain_judgment(
    workspace: str | Path, request: DomainValidationRequest, *, caller: str = "host"
) -> DomainValidationResult | DomainRepairResult | DomainCondition:
    del caller
    # The public continuation starts at the Approved Batch. Materialize its
    # first durable Domain work packet before binding the candidate so every
    # checkpoint has the same packet chain in the final artifact.
    if request.packet.kind is RecordKind.APPROVED_BATCH:
        try:
            work = _packet_record(workspace, request.packet)
            request = request.model_copy(
                update={
                    "packet": prepare_domain_packet(
                        workspace,
                        request.packet,
                        trial_id=str(work["trial_id"]),
                        domain_id=str(work["domain_id"]),
                        result_id=str(work.get("result_id", "result")),
                    )
                }
            )
        except ValueError as error:
            return DomainCondition(
                outcome="condition",
                code="packet_unavailable",
                detail=str(error),
                next_action=ValidateDomainJudgmentContinuation(packet=request.packet),
            )
    draft_hash = identity(request.draft.model_dump(mode="json"))
    try:
        candidate, repairs = _candidate(workspace, request.packet, request.draft)
    except ValueError as error:
        return DomainCondition(
            outcome="condition",
            code="packet_unavailable",
            detail=str(error),
            next_action=ValidateDomainJudgmentContinuation(packet=request.packet),
        )
    if repairs:
        return DomainRepairResult(draft_hash=draft_hash, repairs=repairs)
    candidate_ref = RecordReference(
        kind=RecordKind.DOMAIN_CANDIDATE,
        identity=str(candidate["identity"]),
        uri=record_uri("domain_candidate", str(candidate["identity"])),
    )
    transition = issue_transition(
        workspace,
        "commit_domain_judgment",
        {
            "candidate": candidate_ref.model_dump(mode="json"),
            "packet": request.packet.model_dump(mode="json"),
        },
    )
    candidate["transition"] = transition.model_dump(mode="json")
    write_jsons(
        workspace,
        {f"domain-candidate-{candidate_ref.identity.removeprefix('sha256:')}.json": candidate},
    )
    inactive = cast(list[Any], candidate["inactive_questions"])
    return DomainValidationResult(
        candidate=candidate_ref,
        transition=transition,
        candidate_hash=candidate_ref.identity,
        draft_hash=draft_hash,
        proposed_judgment=Judgment(str(candidate["proposed_judgment"])),
        inactive_questions=tuple(str(item) for item in inactive),
    )


class DomainCommitResult(_Closed):
    outcome: Literal["success"] = "success"
    candidate: RecordReference
    active_revision: int
    active_hash: str
    acknowledgment: ReviewAcknowledgmentReference
    remaining_domains: tuple[str, ...]
    next_action: Continuation


def commit_domain_judgment(
    workspace: str | Path, transition: TransitionReference, *, caller: str = "host"
) -> DomainCommitResult:
    with workspace_mutation_lock(workspace):
        raw_transition = read_transition(workspace, transition)
        if raw_transition.get("consumed"):
            replay = read_json(
                workspace, f"domain-commit-{transition.identity.removeprefix('sha256:')}.json"
            )
            if replay is None:
                raise ValueError("consumed Domain Transition replay is corrupt")
            return DomainCommitResult.model_validate(replay)
        if raw_transition.get("operation") != "commit_domain_judgment":
            raise ValueError("Transition operation does not match commit_domain_judgment")
        candidate_ref = RecordReference.model_validate(raw_transition.get("candidate"))
        raw = read_json(
            workspace, f"domain-candidate-{candidate_ref.identity.removeprefix('sha256:')}.json"
        )
        if raw is None or raw.get("identity") != candidate_ref.identity:
            raise ValueError("Domain candidate is unavailable or corrupt")
        candidate_payload = {
            key: raw[key]
            for key in (
                "kind",
                "packet",
                "trial_id",
                "result_id",
                "domain_id",
                "draft",
                "proposed_judgment",
                "inactive_questions",
                "evidence_bindings",
                "scientific_pack",
                "policy_pack",
            )
            if key in raw
        }
        if identity(candidate_payload) != candidate_ref.identity:
            raise ValueError("transition_consumed_mismatch")
        state = read_json(workspace, "state.json") or {}
        domains = dict(state.get("domains", {}))
        key = f"{raw['trial_id']}:{raw['result_id']}:{raw['domain_id']}"
        prior = domains.get(key, ())
        packet_payload = raw.get("packet")
        if (
            isinstance(packet_payload, dict)
            and packet_payload.get("kind") == RecordKind.APPROVED_WORK_PACKET.value
        ):
            packet_record = read_json(
                workspace,
                f"domain-packet-{str(packet_payload.get('identity', '')).removeprefix('sha256:')}.json",
            )
            if packet_record is None:
                raise ValueError("Domain work packet is unavailable")
            prior_rows = dict(packet_record.get("prior_domain_hashes", ()))
            expected = prior_rows.get(str(raw["domain_id"]))
            current = str(prior[-1]) if isinstance(prior, list) and prior else None
            if expected != current:
                raise ValueError("concurrent_domain_conflict")
        revision = len(prior) + 1
        active_hash = identity({"candidate": candidate_ref.identity, "revision": revision})
        domains[key] = [active_hash]
        remaining = tuple(
            item
            for item in _domain_ids()
            if f"{raw['trial_id']}:{raw['result_id']}:{item}" not in domains
        )
        observed_at = datetime.now(UTC)
        acknowledgment_identity = identity(
            {
                "candidate": candidate_ref.model_dump(mode="json"),
                "authority": ReviewAuthority.HOST.value,
                "caller": caller,
                "observed_at": observed_at.isoformat(),
            }
        )
        acknowledgment = ReviewAcknowledgmentReference(
            kind="review_ack",
            identity=acknowledgment_identity, uri=record_uri("review_ack", acknowledgment_identity)
        )
        packet = RecordReference.model_validate(raw["packet"])
        receipt = DomainCommitResult(
            candidate=candidate_ref,
            active_revision=revision,
            active_hash=active_hash,
            acknowledgment=acknowledgment,
            remaining_domains=remaining,
            next_action=ValidateDomainJudgmentContinuation(packet=packet)
            if remaining
            else PrepareTrialFinishContinuation(packet=packet),
        )
        raw_transition["consumed"] = True
        observation = {
            **raw,
            "active_hash": active_hash,
            "active_revision": revision,
            "caller": caller,
            "acknowledgment": acknowledgment.model_dump(mode="json"),
            "observed_at": observed_at.isoformat(),
        }
        write_jsons(
            workspace,
            {
                f"domain-observation-{active_hash.removeprefix('sha256:')}.json": observation,
                f"domain-commit-{transition.identity.removeprefix('sha256:')}.json": receipt.model_dump(
                    mode="json"
                ),
                f"transition-{transition.identity.removeprefix('sha256:')}.json": raw_transition,
                "state.json": {**state, "domains": domains, "phase": "assessment"},
            },
        )
        if remaining:
            next_packet = prepare_domain_packet(
                workspace,
                RecordReference(
                    kind=RecordKind.APPROVED_BATCH,
                    identity=str(state["approved_batch_identity"]),
                    uri=record_uri(RecordKind.APPROVED_BATCH.value, str(state["approved_batch_identity"])),
                ),
                trial_id=str(raw["trial_id"]),
                domain_id=remaining[0],
                result_id=str(raw["result_id"]),
            )
            receipt = receipt.model_copy(
                update={"next_action": ValidateDomainJudgmentContinuation(packet=next_packet)}
            )
            write_jsons(
                workspace,
                {
                    f"domain-commit-{transition.identity.removeprefix('sha256:')}.json": receipt.model_dump(
                        mode="json"
                    )
                },
            )
        return receipt


__all__ = [
    "DomainAnswerInput",
    "DomainCondition",
    "DomainDraftInput",
    "DomainEvidenceUseInput",
    "DomainOverrideInput",
    "DomainRepair",
    "DomainRepairResult",
    "DomainValidationRequest",
    "DomainValidationResult",
    "DomainCommitResult",
    "prepare_domain_packet",
    "validate_domain_judgment",
    "commit_domain_judgment",
]
