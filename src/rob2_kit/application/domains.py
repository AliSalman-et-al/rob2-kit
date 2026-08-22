"""Application Domain candidate validation and Transition-only commit."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.judgment_models import EvidenceRelationship
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.models import Activation, Answer, Judgment
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
from .evidence import (
    EvidenceCatalogSlice,
    list_sources,
    resolve_evidence,
    reusable_evidence_catalog,
)
from .transitions import issue_transition, read_transition


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationQuestionGuidance(_Closed):
    id: str = Field(min_length=1, strict=True)
    wording: str = Field(min_length=1, strict=True)
    allowed_answers: tuple[Answer, ...]
    activation: Activation


class ApplicationWorkPacket(_Closed):
    """The closed, content-addressed packet handed to a Domain worker."""

    kind: Literal["work_packet"]
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$", strict=True)
    approved_batch: RecordReference
    trial_id: str = Field(min_length=1, strict=True)
    result_id: str = Field(min_length=1, strict=True)
    domain_id: str = Field(min_length=1, strict=True)
    active_question_ids: tuple[str, ...]
    allowed_question_ids: tuple[str, ...]
    question_guidance: tuple[ApplicationQuestionGuidance, ...]
    stable_aliases: tuple[str, ...]
    reusable_evidence: EvidenceCatalogSlice
    prior_domain_hashes: tuple[tuple[str, str], ...]
    scientific_pack: str = Field(pattern=r"^sha256:[0-9a-f]{64}$", strict=True)
    policy_pack: str = Field(pattern=r"^sha256:[0-9a-f]{64}$", strict=True)


def _packet_payload(value: ApplicationWorkPacket) -> dict[str, object]:
    return value.model_dump(mode="json", exclude={"identity"})


def parse_application_work_packet(value: object) -> ApplicationWorkPacket:
    packet = ApplicationWorkPacket.model_validate(value)
    if identity(_packet_payload(packet)) != packet.identity:
        raise ValueError("Domain work packet identity is corrupt")
    return packet


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


def _current_prior_domain_hashes(
    state: dict[str, Any], trial_id: str, result_id: str, domain_id: str
) -> tuple[tuple[str, str], ...]:
    """Return every earlier Domain's current checkpoint in pack order."""
    domain_ids = _domain_ids()
    try:
        prior_domains = domain_ids[: domain_ids.index(domain_id)]
    except ValueError as error:
        raise ValueError("unknown Domain") from error
    if not prior_domains:
        return ()
    domains = state.get("domains")
    if not isinstance(domains, dict):
        raise ValueError("concurrent_domain_conflict")
    rows: list[tuple[str, str]] = []
    for prior_domain in prior_domains:
        values = domains.get(f"{trial_id}:{result_id}:{prior_domain}")
        if not isinstance(values, list) or not values or not isinstance(values[-1], str):
            raise ValueError("concurrent_domain_conflict")
        rows.append((prior_domain, values[-1]))
    return tuple(rows)


def _build_domain_packet(
    workspace: str | Path,
    approved_batch: RecordReference,
    *,
    trial_id: str,
    domain_id: str,
    result_id: str = "result",
    state: dict[str, Any] | None = None,
) -> ApplicationWorkPacket:
    """Build and validate a Domain packet without changing workspace state."""
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
    current_state = state if state is not None else (read_json(workspace, "state.json") or {})
    prior = _current_prior_domain_hashes(current_state, trial_id, result_id, domain_id)
    source_aliases = list_sources(workspace, trial_id)
    aliases = tuple(source.alias for source in source_aliases)
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
        "question_guidance": tuple(
            {
                "id": q.id,
                "wording": q.wording,
                "allowed_answers": tuple(answer.value for answer in q.allowed_answers),
                "activation": q.activation.model_dump(mode="json"),
            }
            for q in SCIENTIFIC_PACK.questions
            if q.domain_id == domain_id
        ),
        "stable_aliases": aliases,
        "reusable_evidence": reusable_evidence_catalog(
            workspace, trial_id, source_aliases
        ).model_dump(mode="json"),
        "prior_domain_hashes": prior,
        "scientific_pack": SCIENTIFIC_PACK.content_hash,
        "policy_pack": MAINTAINER_POLICY_PACK.content_hash,
    }
    return ApplicationWorkPacket(identity=identity(payload), **payload)


def _packet_record(workspace: str | Path, packet: RecordReference) -> dict[str, object]:
    """Resolve a server-issued packet; an Approved Batch is accepted for its first Domain."""
    if packet.kind is RecordKind.APPROVED_WORK_PACKET:
        raw = read_json(workspace, f"domain-packet-{packet.identity.removeprefix('sha256:')}.json")
        if raw is None or raw.get("identity") != packet.identity:
            raise ValueError("Domain work packet is unavailable or corrupt")
        return parse_application_work_packet(raw).model_dump(mode="json")
    if packet.kind is not RecordKind.APPROVED_BATCH:
        raise ValueError("Domain work requires the server-issued work packet")
    state = read_json(workspace, "state.json") or {}
    domains = state.get("domains")
    if (
        "work_packet_identity" in state
        or (isinstance(domains, dict) and domains)
        or (domains is not None and domains != {})
    ):
        raise ValueError("Approved Batch bootstrap is only valid before Domain work has started")
    raw = read_json(workspace, "approved_batch.json")
    if raw is None or raw.get("identity") != packet.identity:
        raise ValueError("Approved Batch reference is stale")
    rows = cast(list[list[object]], raw.get("dispositions", []))
    pending = sorted(str(row[0]) for row in rows if len(row) >= 2 and row[1] == "pending")
    if not pending:
        raise ValueError("Approved Batch has no pending Trial")
    return _build_domain_packet(
        workspace,
        packet,
        trial_id=pending[0],
        domain_id=_domain_ids()[0],
    ).model_dump(mode="json")


def prepare_domain_packet(
    workspace: str | Path,
    approved_batch: RecordReference,
    *,
    trial_id: str,
    domain_id: str,
    result_id: str = "result",
) -> RecordReference:
    """Create a deterministic per-Domain packet from the approved Batch."""
    state = read_json(workspace, "state.json") or {}
    packet_record = _build_domain_packet(
        workspace,
        approved_batch,
        trial_id=trial_id,
        domain_id=domain_id,
        result_id=result_id,
        state=state,
    )
    state["work_packet_identity"] = packet_record.identity
    write_jsons(
        workspace,
        {
            f"domain-packet-{packet_record.identity.removeprefix('sha256:')}.json": {
                **packet_record.model_dump(mode="json"),
            },
            "state.json": state,
        },
    )
    return RecordReference(
        kind=RecordKind.APPROVED_WORK_PACKET,
        identity=packet_record.identity,
        uri=record_uri(RecordKind.APPROVED_WORK_PACKET.value, packet_record.identity),
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
        active_ids = tuple(
            question_id for question_id in active_questions(answers) if question_id in known
        )
        active = set(active_ids)
    except ValueError as error:
        repairs.append(DomainRepair(pointer="/active_answers", code="invalid", detail=str(error)))
        active_ids = ()
        active = set()
    if set(answers) != active:
        repairs.append(
            DomainRepair(
                pointer="/active_answers",
                code="mismatch",
                detail=f"active questions must be exactly {sorted(active)}",
            )
        )
    elif tuple(item.question_id for item in draft.active_answers) != active_ids:
        repairs.append(
            DomainRepair(
                pointer="/active_answers",
                code="order",
                detail=(f"active answers must follow packet/scientific-pack order: {active_ids!r}"),
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
        packet_payload = raw.get("packet")
        packet = RecordReference.model_validate(packet_payload)
        if packet.kind is RecordKind.APPROVED_WORK_PACKET:
            # A validated packet is usable only while it remains the current
            # packet.  Checking this before the prior-checkpoint comparison
            # prevents an old packet from being treated as a concurrent basis.
            if state.get("work_packet_identity") != packet.identity:
                raise ValueError("concurrent_domain_conflict")
        elif packet.kind is RecordKind.APPROVED_BATCH:
            # Bootstrap candidates are valid only before any Domain work has
            # started.  A candidate validated from the Batch must not race a
            # later packet materialization or checkpoint commit.
            state_domains = state.get("domains")
            if (
                "work_packet_identity" in state
                or (isinstance(state_domains, dict) and state_domains)
                or (state_domains is not None and state_domains != {})
            ):
                raise ValueError("concurrent_domain_conflict")
        domains = dict(state.get("domains", {}))
        key = f"{raw['trial_id']}:{raw['result_id']}:{raw['domain_id']}"
        prior = domains.get(key, ())
        packet_model: ApplicationWorkPacket | None = None
        if (
            isinstance(packet_payload, dict)
            and packet_payload.get("kind") == RecordKind.APPROVED_WORK_PACKET.value
        ):
            packet_reference = RecordReference.model_validate(packet_payload)
            packet_record = read_json(
                workspace,
                f"domain-packet-{packet_reference.identity.removeprefix('sha256:')}.json",
            )
            if packet_record is None:
                raise ValueError("Domain work packet is unavailable")
            packet_model = parse_application_work_packet(packet_record)
            if packet_model.identity != packet_reference.identity:
                raise ValueError("Domain work packet reference is stale")
            current_prior = _current_prior_domain_hashes(
                state,
                str(raw["trial_id"]),
                str(raw["result_id"]),
                str(raw["domain_id"]),
            )
            if tuple(packet_model.prior_domain_hashes) != current_prior:
                raise ValueError("concurrent_domain_conflict")
        revision = len(prior) + 1
        active_hash = identity({"candidate": candidate_ref.identity, "revision": revision})
        domains[key] = [active_hash]
        remaining = tuple(
            item
            for item in _domain_ids()
            if f"{raw['trial_id']}:{raw['result_id']}:{item}" not in domains
        )
        state_for_write = {**state, "domains": domains, "phase": "assessment"}
        next_packet_record: ApplicationWorkPacket | None = None
        if remaining:
            approved_batch = packet_model.approved_batch if packet_model is not None else packet
            next_packet_record = _build_domain_packet(
                workspace,
                approved_batch,
                trial_id=str(raw["trial_id"]),
                domain_id=remaining[0],
                result_id=str(raw["result_id"]),
                state=state_for_write,
            )
            next_packet = RecordReference(
                kind=RecordKind.APPROVED_WORK_PACKET,
                identity=next_packet_record.identity,
                uri=record_uri(RecordKind.APPROVED_WORK_PACKET.value, next_packet_record.identity),
            )
            state_for_write["work_packet_identity"] = next_packet_record.identity
            next_action: Continuation = ValidateDomainJudgmentContinuation(packet=next_packet)
        else:
            next_action = PrepareTrialFinishContinuation(packet=packet)
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
            identity=acknowledgment_identity,
            uri=record_uri("review_ack", acknowledgment_identity),
        )
        receipt = DomainCommitResult(
            candidate=candidate_ref,
            active_revision=revision,
            active_hash=active_hash,
            acknowledgment=acknowledgment,
            remaining_domains=remaining,
            next_action=next_action,
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
        writes = {
            f"domain-observation-{active_hash.removeprefix('sha256:')}.json": observation,
            f"domain-commit-{transition.identity.removeprefix('sha256:')}.json": receipt.model_dump(
                mode="json"
            ),
            f"transition-{transition.identity.removeprefix('sha256:')}.json": raw_transition,
            "state.json": state_for_write,
        }
        if next_packet_record is not None:
            writes[f"domain-packet-{next_packet_record.identity.removeprefix('sha256:')}.json"] = (
                next_packet_record.model_dump(mode="json")
            )
        write_jsons(workspace, writes)
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
