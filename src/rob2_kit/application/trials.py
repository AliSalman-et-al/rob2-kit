"""Deterministic Trial synthesis preparation and terminal disposition."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.logic.evaluator import evaluate_overall
from rob2_kit.models import Judgment, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.storage import workspace_mutation_lock

from ._state import identity, read_json, record_uri, write_jsons
from .acknowledgments import verify_acknowledgment
from .contracts import (
    Continuation,
    EvidenceReference,
    OperationOutcome,
    RecordKind,
    RecordReference,
    ResearcherReviewContinuation,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    ReviewAuthorityRequirement,
    TransitionReference,
    TrialDisposition,
    ValidateDomainJudgmentContinuation,
)
from .evidence import resolve_evidence
from .transitions import issue_transition, read_transition


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrialSynthesis(_Closed):
    kind: Literal["trial_synthesis"] = "trial_synthesis"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approved_batch: RecordReference
    trial_id: str
    result_id: str
    checkpoint_hashes: tuple[tuple[str, str], ...]
    checkpoint_judgments: tuple[tuple[str, Judgment], ...]
    proposed_overall: Judgment
    synthesis_hash: str

    @property
    def reference(self) -> RecordReference:
        return RecordReference(
            kind=RecordKind.SYNTHESIS,
            identity=self.identity,
            uri=record_uri("trial_synthesis", self.identity),
        )


class TrialPrepareResult(_Closed):
    outcome: OperationOutcome
    synthesis: RecordReference | None = None
    candidate: RecordReference | None = None
    trial_id: str
    missing_domains: tuple[str, ...] = ()
    transition: TransitionReference | None = None
    review: ReviewAuthorityRequirement = ReviewAuthorityRequirement(
        required=ReviewAuthority.NONE, satisfied=True
    )
    next_action: Continuation | None = None


class NeedsInputReason(StrEnum):
    COMPARATOR_UNAVAILABLE = "comparator_unavailable"
    OUTCOME_DEFINITION_UNCLEAR = "outcome_definition_unclear"
    SOURCE_EVIDENCE_INSUFFICIENT = "source_evidence_insufficient"


class FailureCause(StrEnum):
    VERIFIED_SERVER_FAILURE = "verified_server_failure"
    RESEARCHER_ABANDONMENT = "researcher_abandonment"


class TrialFinishCandidate(_Closed):
    disposition: TrialDisposition
    reason: NeedsInputReason | None = None
    failure_cause: FailureCause | None = None
    missing_facts: tuple[str, ...] = ()
    available_evidence: tuple[EvidenceReference, ...] = ()
    retained_checkpoints: tuple[RecordReference, ...] = ()

    @model_validator(mode="after")
    def terminal_basis_is_specific(self) -> TrialFinishCandidate:
        if self.disposition is TrialDisposition.ASSESSED:
            if self.reason or self.failure_cause or self.missing_facts or self.available_evidence:
                raise ValueError("an assessed Trial uses only the verified synthesis")
        elif self.disposition is TrialDisposition.NEEDS_INPUT:
            if self.reason is None or self.failure_cause is not None or not self.missing_facts:
                raise ValueError("needs_input requires one reason code and missing facts")
        elif self.disposition is TrialDisposition.FAILED:
            if self.failure_cause is None or self.reason is not None or not self.missing_facts:
                raise ValueError("failed requires one failure cause and missing facts")
        else:
            raise ValueError("a Trial finish requires a terminal disposition")
        return self


class TrialFinishRequest(_Closed):
    transition: TransitionReference
    acknowledgment: ReviewAcknowledgmentReference


class AssessmentSnapshot(_Closed):
    kind: Literal["assessment_snapshot"] = "assessment_snapshot"
    identity: str
    synthesis: RecordReference
    trial_id: str
    result_id: str
    checkpoint_hashes: tuple[tuple[str, str], ...]
    proposed_overall: Judgment
    final_judgment: Judgment
    caller: str
    observed_at: datetime
    snapshot_hash: str


class TrialOutcome(_Closed):
    kind: Literal["trial_terminal"] = "trial_terminal"
    identity: str
    trial_id: str
    disposition: TrialDisposition
    reason: NeedsInputReason | None = None
    failure_cause: FailureCause | None = None
    missing_facts: tuple[str, ...] = ()
    available_evidence: tuple[EvidenceReference, ...] = ()
    retained_checkpoints: tuple[RecordReference, ...] = ()
    synthesis: RecordReference
    snapshot: RecordReference | None = None
    observed_at: datetime


class TrialFinishResult(_Closed):
    outcome: OperationOutcome
    disposition: TrialDisposition
    trial_id: str
    outcome_ref: RecordReference
    snapshot: RecordReference | None = None
    continuation: None = None


def _work_packet(
    workspace: str | Path, reference: RecordReference
) -> tuple[dict[str, object], RecordReference]:
    if reference.kind is RecordKind.APPROVED_WORK_PACKET:
        raw = read_json(
            workspace, f"domain-packet-{reference.identity.removeprefix('sha256:')}.json"
        )
        if raw is None or raw.get("identity") != reference.identity:
            raise ValueError("work packet is unavailable or corrupt")
        from .domains import parse_application_work_packet

        raw = parse_application_work_packet(raw).model_dump(mode="json")
        approved = RecordReference.model_validate(raw.get("approved_batch"))
        return raw, approved
    if reference.kind is not RecordKind.APPROVED_BATCH:
        raise ValueError("Trial work requires an Approved Batch or work packet")
    raw = read_json(workspace, "approved_batch.json")
    if raw is None or raw.get("identity") != reference.identity:
        raise ValueError("Approved Batch reference is stale")
    return raw, reference


def _observation(workspace: str | Path, active_hash: str) -> dict[str, object]:
    raw = read_json(workspace, f"domain-observation-{active_hash.removeprefix('sha256:')}.json")
    if raw is None or raw.get("active_hash") != active_hash:
        raise ValueError("Domain observation is missing or corrupt")
    candidate = {
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
    if identity(candidate) != raw.get("identity"):
        raise ValueError("Domain candidate is corrupt")
    return raw


def prepare_trial_finish(
    workspace: str | Path,
    packet: RecordReference,
    candidate: TrialFinishCandidate,
    *,
    caller: str = "host",
    authority: ReviewAuthority = ReviewAuthority.HOST,
) -> TrialPrepareResult:
    work, approved = _work_packet(workspace, packet)
    if packet.kind is RecordKind.APPROVED_WORK_PACKET:
        trial_id = str(work["trial_id"])
        result_id = str(work.get("result_id", "result"))
    else:
        rows = cast(list[list[object]], work.get("dispositions", []))
        pending = sorted(str(row[0]) for row in rows if len(row) >= 2 and row[1] == "pending")
        trial_id = pending[0] if pending else ""
        result_id = "result"
    if not trial_id:
        raise ValueError("Approved Batch has no pending Trial")
    if candidate.disposition is not TrialDisposition.ASSESSED and (
        authority is not ReviewAuthority.RESEARCHER or not caller.startswith(("cli:", "server:"))
    ):
        raise PermissionError("needs_input and failed Trial finishes require researcher authority")
    for reference in candidate.available_evidence:
        record = resolve_evidence(workspace, reference)
        if record.trial_id != trial_id:
            raise ValueError("terminal Evidence is outside the Trial scope")
    domains = tuple(domain.id for domain in SCIENTIFIC_PACK.domains)
    state = read_json(workspace, "state.json") or {}
    stored = state.get("domains", {})
    rows: list[tuple[str, str]] = []
    judgments: list[tuple[str, Judgment]] = []
    missing: list[str] = []
    for domain in domains:
        key = f"{trial_id}:{result_id}:{domain}"
        values = stored.get(key, ()) if isinstance(stored, dict) else ()
        if not isinstance(values, list) or not values:
            missing.append(domain)
            continue
        active_hash = str(values[-1])
        try:
            observation = _observation(workspace, active_hash)
            if (
                str(observation.get("trial_id")) != trial_id
                or str(observation.get("result_id")) != result_id
                or str(observation.get("domain_id")) != domain
            ):
                raise ValueError("Domain observation scope mismatch")
            rows.append((domain, active_hash))
            judgments.append((domain, Judgment(str(observation["proposed_judgment"]))))
        except (KeyError, TypeError, ValueError):
            missing.append(domain)
    if missing and candidate.disposition is TrialDisposition.ASSESSED:
        return TrialPrepareResult(
            outcome=OperationOutcome.CONDITION,
            trial_id=trial_id,
            missing_domains=tuple(missing),
            next_action=ValidateDomainJudgmentContinuation(packet=packet),
        )
    retained = tuple(
        RecordReference(
            kind=RecordKind.DOMAIN_OBSERVATION,
            identity=active_hash,
            uri=record_uri("domain_checkpoint", active_hash),
        )
        for _domain, active_hash in rows
    )
    if candidate.retained_checkpoints:
        raise ValueError("retained checkpoints are server-derived")
    candidate = candidate.model_copy(update={"retained_checkpoints": retained})
    overall = (
        evaluate_overall(dict(judgments), combined_concerns=False).judgment
        if judgments
        else Judgment.LOW
    )
    payload = {
        "approved_batch": approved.model_dump(mode="json"),
        "trial_id": trial_id,
        "result_id": result_id,
        "checkpoint_hashes": rows,
        "checkpoint_judgments": [(domain, value.value) for domain, value in judgments],
        "proposed_overall": overall.value,
        "combined_concerns": False,
    }
    synthesis_identity = identity(payload)
    synthesis = TrialSynthesis(
        identity=synthesis_identity,
        approved_batch=approved,
        trial_id=trial_id,
        result_id=result_id,
        checkpoint_hashes=tuple(rows),
        checkpoint_judgments=tuple(judgments),
        proposed_overall=overall,
        synthesis_hash=sha256(payload),
    )
    write_jsons(
        workspace,
        {
            f"synthesis-{synthesis_identity.removeprefix('sha256:')}.json": synthesis.model_dump(
                mode="json"
            ),
            "state.json": {**state, "synthesis_identity": synthesis_identity},
        },
    )
    transition = issue_transition(
        workspace,
        "finish_trial",
        {
            "synthesis": synthesis.reference.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
        },
    )
    candidate_ref = RecordReference(
        kind=RecordKind.TRIAL_OUTCOME,
        identity=identity(
            {
                "synthesis": synthesis.reference.model_dump(mode="json"),
                "candidate": candidate.model_dump(mode="json"),
            }
        ),
        uri=record_uri(
            "trial_terminal",
            identity(
                {
                    "synthesis": synthesis.reference.model_dump(mode="json"),
                    "candidate": candidate.model_dump(mode="json"),
                }
            ),
        ),
    )
    write_jsons(
        workspace,
        {
            f"trial-finish-candidate-{candidate_ref.identity.removeprefix('sha256:')}.json": {
                "kind": "trial_terminal",
                "identity": candidate_ref.identity,
                "synthesis": synthesis.reference.model_dump(mode="json"),
                "candidate": candidate.model_dump(mode="json"),
            },
            "state.json": {
                **state,
                "synthesis_identity": synthesis_identity,
                "trial_finish_transition": transition.model_dump(mode="json"),
                "trial_finish_candidate": candidate.model_dump(mode="json"),
            },
        },
    )
    review = ReviewAuthorityRequirement(required=ReviewAuthority.RESEARCHER)
    return TrialPrepareResult(
        outcome=OperationOutcome.SUCCESS,
        synthesis=synthesis.reference,
        candidate=candidate_ref,
        trial_id=trial_id,
        transition=transition,
        review=review,
        next_action=ResearcherReviewContinuation(
            record=candidate_ref
            if candidate.disposition is not TrialDisposition.ASSESSED
            else synthesis.reference,
            purpose="trial_finish",
            unlocks="finish_trial",
        ),
    )


def acknowledge_trial_finish(
    workspace: str | Path, transition: TransitionReference, *, caller: str
) -> ReviewAcknowledgmentReference:
    if not caller.startswith(("cli:", "server:")):
        raise PermissionError("researcher acknowledgment must be observed by an adapter")
    raw = read_transition(workspace, transition)
    candidate = TrialFinishCandidate.model_validate(raw.get("candidate"))
    synthesis = RecordReference.model_validate(raw.get("synthesis"))
    reviewed = (
        synthesis
        if candidate.disposition is TrialDisposition.ASSESSED
        else RecordReference(
            kind=RecordKind.TRIAL_OUTCOME,
            identity=identity(
                {
                    "synthesis": synthesis.model_dump(mode="json"),
                    "candidate": candidate.model_dump(mode="json"),
                }
            ),
            uri=record_uri(
                "trial_terminal",
                identity(
                    {
                        "synthesis": synthesis.model_dump(mode="json"),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                ),
            ),
        )
    )
    observed_at = datetime.now(UTC)
    payload = {
        "record": reviewed.model_dump(mode="json"),
        "purpose": "trial_finish",
        "authority": "researcher",
        "caller": caller,
        "observed_at": observed_at.isoformat(),
    }
    ack_identity = identity(payload)
    ack = ReviewAcknowledgmentReference(
        kind="review_ack",
        identity=ack_identity, uri=record_uri("review_ack", ack_identity)
    )
    write_jsons(
        workspace,
        {
            f"trial-finish-ack-{ack_identity.removeprefix('sha256:')}.json": {
                **ack.model_dump(mode="json"),
                **payload,
            },
            "state.json": {
                **(read_json(workspace, "state.json") or {}),
                "trial_finish_ack_identity": ack_identity,
            },
        },
    )
    return ack


def finish_trial(
    workspace: str | Path,
    request: TrialFinishRequest,
    *,
    caller: str = "host",
) -> TrialFinishResult:
    if not caller.startswith(("cli:", "server:")):
        raise PermissionError("Trial finish must be observed by an adapter")
    with workspace_mutation_lock(workspace):
        transition = read_transition(workspace, request.transition)
        if transition.get("consumed"):
            existing = read_json(
                workspace, f"trial-outcome-{str(transition.get('trial_id', ''))}.json"
            )
            if existing is None or existing.get("transition") != request.transition.model_dump(
                mode="json"
            ):
                raise ValueError("transition_consumed_mismatch")
            return TrialFinishResult(
                outcome=OperationOutcome.SUCCESS,
                disposition=TrialDisposition(str(existing["disposition"])),
                trial_id=str(existing["trial_id"]),
                outcome_ref=RecordReference(
                    kind=RecordKind.TRIAL_OUTCOME,
                    identity=str(existing["identity"]),
                    uri=record_uri("trial_terminal", str(existing["identity"])),
                ),
                snapshot=None
                if existing.get("snapshot") is None
                else RecordReference.model_validate(existing["snapshot"]),
            )
        synthesis_ref = RecordReference.model_validate(transition.get("synthesis"))
        candidate = TrialFinishCandidate.model_validate(transition.get("candidate"))
        reviewed = (
            synthesis_ref
            if candidate.disposition is TrialDisposition.ASSESSED
            else RecordReference(
                kind=RecordKind.TRIAL_OUTCOME,
                identity=identity(
                    {
                        "synthesis": synthesis_ref.model_dump(mode="json"),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                ),
                uri=record_uri(
                    "trial_terminal",
                    identity(
                        {
                            "synthesis": synthesis_ref.model_dump(mode="json"),
                            "candidate": candidate.model_dump(mode="json"),
                        }
                    ),
                ),
            )
        )
        if verify_acknowledgment(
            workspace,
            f"trial-finish-ack-{request.acknowledgment.identity.removeprefix('sha256:')}.json",
            request.acknowledgment,
            record=reviewed,
            purpose="trial_finish",
            authority=ReviewAuthority.RESEARCHER,
        ) is None:
            raise ValueError("exact review acknowledgment is unavailable or corrupt")
        raw = read_json(
            workspace, f"synthesis-{synthesis_ref.identity.removeprefix('sha256:')}.json"
        )
        if raw is None:
            raise ValueError("synthesis reference is unavailable")
        synthesis = TrialSynthesis.model_validate(raw)
        synthesis_payload = {
            "approved_batch": synthesis.approved_batch.model_dump(mode="json"),
            "trial_id": synthesis.trial_id,
            "result_id": synthesis.result_id,
            "checkpoint_hashes": synthesis.checkpoint_hashes,
            "checkpoint_judgments": [
                (domain, judgment.value) for domain, judgment in synthesis.checkpoint_judgments
            ],
            "proposed_overall": synthesis.proposed_overall.value,
            "combined_concerns": False,
        }
        if (
            identity(synthesis_payload) != synthesis.identity
            or sha256(synthesis_payload) != synthesis.synthesis_hash
        ):
            raise ValueError("synthesis reference is corrupt")
        existing = read_json(workspace, f"trial-outcome-{synthesis.trial_id}.json")
        if existing is not None:
            if (
                existing.get("synthesis") != synthesis_ref.model_dump(mode="json")
                or existing.get("disposition") != candidate.disposition.value
            ):
                raise ValueError("transition_consumed_mismatch")
            return TrialFinishResult(
                outcome=OperationOutcome.SUCCESS,
                disposition=TrialDisposition(str(existing["disposition"])),
                trial_id=synthesis.trial_id,
                outcome_ref=RecordReference(
                    kind=RecordKind.TRIAL_OUTCOME,
                    identity=str(existing["identity"]),
                    uri=record_uri("trial_terminal", str(existing["identity"])),
                ),
                snapshot=None
                if existing.get("snapshot") is None
                else RecordReference.model_validate(existing["snapshot"]),
            )
        if candidate.disposition is TrialDisposition.ASSESSED:
            final = synthesis.proposed_overall
            observed = datetime.now(UTC)
            snapshot_payload = {
                "synthesis": synthesis_ref.model_dump(mode="json"),
                "checkpoint_hashes": synthesis.checkpoint_hashes,
                "proposed_overall": synthesis.proposed_overall.value,
                "final_judgment": final.value,
                "caller": caller,
                "observed_at": observed.isoformat().replace("+00:00", "Z"),
            }
            snapshot_identity = identity(snapshot_payload)
            snapshot = AssessmentSnapshot(
                identity=snapshot_identity,
                synthesis=synthesis_ref,
                trial_id=synthesis.trial_id,
                result_id=synthesis.result_id,
                checkpoint_hashes=synthesis.checkpoint_hashes,
                proposed_overall=synthesis.proposed_overall,
                final_judgment=final,
                caller=caller,
                observed_at=observed,
                snapshot_hash=sha256(snapshot_payload),
            )
            snapshot_ref = RecordReference(
                kind=RecordKind.ASSESSMENT_SNAPSHOT,
                identity=snapshot_identity,
                uri=record_uri("assessment_snapshot", snapshot_identity),
            )
        else:
            snapshot = None
            snapshot_ref = None
        observed = datetime.now(UTC)
        outcome_payload = {
            "synthesis": synthesis_ref.model_dump(mode="json"),
            "trial_id": synthesis.trial_id,
            "disposition": candidate.disposition.value,
            "reason": None if candidate.reason is None else candidate.reason.value,
            "failure_cause": (
                None if candidate.failure_cause is None else candidate.failure_cause.value
            ),
            "missing_facts": candidate.missing_facts,
            "available_evidence": [item.model_dump(mode="json") for item in candidate.available_evidence],
            "retained_checkpoints": [
                item.model_dump(mode="json") for item in candidate.retained_checkpoints
            ],
            "caller": caller,
            "observed_at": observed.isoformat(),
            "snapshot": None if snapshot_ref is None else snapshot_ref.model_dump(mode="json"),
            "transition": request.transition.model_dump(mode="json"),
        }
        outcome_identity = identity(outcome_payload)
        state = read_json(workspace, "state.json") or {}
        trial_dispositions = dict(state.get("trial_dispositions", {}))
        trial_dispositions[synthesis.trial_id] = candidate.disposition.value
        next_state = {
            **state,
            "trial_dispositions": trial_dispositions,
        }
        for key in ("synthesis_identity", "trial_finish_transition", "trial_finish_candidate", "trial_finish_ack_identity"):
            next_state.pop(key, None)
        writes = {
            f"trial-outcome-{synthesis.trial_id}.json": {
                "kind": "trial_terminal", "identity": outcome_identity,
                **outcome_payload,
            },
            "state.json": next_state,
        }
        transition_name = f"transition-{request.transition.identity.removeprefix('sha256:')}.json"
        transition["consumed"] = True
        transition["trial_id"] = synthesis.trial_id
        writes[transition_name] = transition
        if snapshot is not None:
            writes[f"assessment-snapshot-{snapshot_identity.removeprefix('sha256:')}.json"] = (
                snapshot.model_dump(mode="json")
            )
        write_jsons(workspace, writes)
        return TrialFinishResult(
            outcome=OperationOutcome.SUCCESS,
            disposition=candidate.disposition,
            trial_id=synthesis.trial_id,
            outcome_ref=RecordReference(
                kind=RecordKind.TRIAL_OUTCOME,
                identity=outcome_identity,
                uri=record_uri("trial_terminal", outcome_identity),
            ),
            snapshot=snapshot_ref,
        )


__all__ = [
    "AssessmentSnapshot",
    "TrialFinishCandidate",
    "TrialFinishRequest",
    "TrialFinishResult",
    "TrialOutcome",
    "TrialPrepareResult",
    "TrialSynthesis",
    "finish_trial",
    "acknowledge_trial_finish",
    "prepare_trial_finish",
]
