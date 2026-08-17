"""Verified restart progress and conservative disposal of active runtime state."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from rob2_kit.batch import (
    ApprovedBatch,
    NoActiveBatch,
    Problem,
    StaleBatch,
    current_batch_in_transaction,
)
from rob2_kit.batch_summary import (
    AssessmentTerminal,
    BatchSummary,
    ProblemTerminal,
    verified_summary,
    verified_terminal,
)
from rob2_kit.detail import DetailReference, detail_reference, read_record
from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.ingestion.service import read_captured_batch
from rob2_kit.judgment_models import DomainJudgment
from rob2_kit.judgments import (
    _validate_evidence,
    _verified_checkpoint,
    build_domain_judgment,
    ensure_judgment_detail,
    verify_revision_history,
)
from rob2_kit.models import StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.reports import (
    _batch_bundle_complete,
    _complete_bundle,
    export_trial,
    export_verified_snapshot,
)
from rob2_kit.storage import _reparse, transaction, workspace_mutation_lock
from rob2_kit.text_projection import VerifiedProjection


class DiscardActiveBatchRequest(StrictModel):
    """An explicit, batch-bound request to remove unfinished runtime state.

    This is an intent signal, not evidence that a person supplied the request.
    Hosts must enforce the researcher-instruction policy before exposing it.
    """

    expected_frozen_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    confirmation: Literal["I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH"]
    actor: str = Field(min_length=1)
    observed_at: datetime
    reason: str = Field(min_length=1)

    @field_validator("actor", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value


class ActiveDomainCheckpoint(StrictModel):
    """The exact compare-and-swap receipt for one resumable Domain."""

    domain_id: str
    active_revision: int = Field(ge=1)
    active_hash: str


class DomainPacketReference(StrictModel):
    domain_id: str
    packet_ref: DetailReference


class TrialProgress(StrictModel):
    trial_id: str
    status: Literal["pending", "assessed", "needs_input", "failed"]
    completed_domains: tuple[str, ...]
    pending_domains: tuple[str, ...]
    export_status: Literal["not_exported", "exported"]
    active_domain_checkpoints: tuple[ActiveDomainCheckpoint, ...] = ()
    terminal_ref: DetailReference | None = None
    synthesis_ref: DetailReference | None = None
    recommended_packet_ref: DetailReference | None = None
    correction_packet_refs: tuple[DomainPacketReference, ...] = ()


class RecoveryProgress(StrictModel):
    status: Literal["no_active", "approved", "stale"]
    trials: tuple[TrialProgress, ...] = ()
    summary_committed: bool = False
    problems: tuple[Problem, ...] = ()
    active_batch: NoActiveBatch | ApprovedBatch | StaleBatch | None = None
    summary_ref: DetailReference | None = None


class CurrentBatchProjection(StrictModel):
    """Compact mutable workflow view; canonical records remain Detail-only."""

    phase: Literal[
        "empty",
        "intake",
        "proposal",
        "approved",
        "partial",
        "synthesis_ready",
        "mixed_terminal",
        "stale",
        "finalized",
    ]
    captured_batch_ref: DetailReference | None = None
    proposal_ref: DetailReference | None = None
    approved_batch_ref: DetailReference | None = None
    summary_ref: DetailReference | None = None
    trials: tuple[TrialProgress, ...] = ()
    conditions: tuple[Problem, ...] = ()
    next_action: Literal[
        "ingest",
        "save_proposal",
        "read_record",
        "approve_batch",
        "work_trial",
        "review_synthesis",
        "finalize_batch",
        "discard",
        "complete",
    ]


class Discarded(StrictModel):
    status: Literal["discarded"] = "discarded"
    removed: tuple[str, ...]


class DiscardCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


def _corrupt(detail: str) -> RecoveryProgress:
    return RecoveryProgress(
        status="stale", problems=(Problem(code="corrupt_active_batch", detail=detail),)
    )


def _frozen_is_exact(state: ApprovedBatch) -> bool:
    return state.frozen_hash == sha256({"proposal": state.proposal, "packs": state.pack_identities})


def _result(state: ApprovedBatch, trial_id: str):
    return next(item for item in state.proposal.result_specs if item.trial.id == trial_id)


def _checkpoint(
    root: Path,
    state: ApprovedBatch,
    trial_id: str,
    result_id: str,
    domain_id: str,
    raw: bytes,
    connection,
    projection: VerifiedProjection | None = None,
):
    judgment = _verified_checkpoint(DomainJudgment.model_validate_json(raw))
    if (
        judgment.approved_batch_hash != state.frozen_hash
        or judgment.trial_id != trial_id
        or judgment.result_id != result_id
        or judgment.domain_id != domain_id
        or judgment.scientific_pack not in state.pack_identities
        or judgment.policy_pack not in state.pack_identities
    ):
        raise ValueError("checkpoint does not bind the approved batch")
    revision, _predecessor_hash = verify_revision_history(
        root,
        connection,
        state,
        trial_id,
        result_id,
        domain_id,
        judgment,
        projection,
    )
    for answer in judgment.active_answers:
        for use in answer.evidence_uses:
            for ref in use.refs:
                _validate_evidence(root, state, trial_id, result_id, ref, projection)
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
        raise ValueError("checkpoint logic does not match saved content")
    return judgment, revision


def _snapshot(
    state: ApprovedBatch, trial, result, raw: bytes, checkpoints: dict[str, DomainJudgment]
):
    snapshot = _verified(AssessmentSnapshot.model_validate_json(raw))
    expected_sources = tuple(
        source for source in state.proposal.sources if source.trial_id == trial.id
    )
    if (
        snapshot.approved_batch_hash != state.frozen_hash
        or snapshot.trial != trial
        or snapshot.result_spec != result
        or snapshot.pack_identities != state.pack_identities
        or snapshot.sources != expected_sources
        or {item.domain_id: item for item in snapshot.domain_judgments} != checkpoints
    ):
        raise ValueError("assessment snapshot does not bind the approved checkpoint set")
    return snapshot


def _summary(
    state: ApprovedBatch,
    raw: bytes,
    terminals: dict[str, object],
    snapshots: dict[str, AssessmentSnapshot],
):
    summary = verified_summary(BatchSummary.model_validate_json(raw))
    if (
        summary.approved_batch_hash != state.frozen_hash
        or summary.outcome_target != state.proposal.request.outcome_target
        or summary.pack_identities != state.pack_identities
        or len(summary.entries) != len(state.proposal.request.trial_inputs)
    ):
        raise ValueError("batch summary does not bind the approved batch")
    by_trial = {entry.trial.id: entry for entry in summary.entries}
    if len(by_trial) != len(summary.entries):
        raise ValueError("batch summary repeats a trial")
    for requested in state.proposal.request.trial_inputs:
        trial = next(item for item in state.proposal.trials if item.id == requested.id)
        result = _result(state, trial.id)
        entry = by_trial.get(trial.id)
        terminal = terminals.get(trial.id)
        if entry is None or entry.trial != trial or entry.result_spec != result or terminal is None:
            raise ValueError("batch summary has an incomplete terminal set")
        if entry.status == "assessed":
            snapshot = snapshots.get(trial.id)
            if (
                not isinstance(terminal, AssessmentTerminal)
                or snapshot is None
                or entry.snapshot_hash != snapshot.snapshot_hash
            ):
                raise ValueError("summary assessment entry is not cross-bound")
        elif (
            not isinstance(terminal, ProblemTerminal)
            or entry.status != terminal.category
            or entry.terminal_hash != terminal.terminal_hash
            or entry.problems != terminal.problems
        ):
            raise ValueError("summary problem entry is not cross-bound")
    return summary


def _preserve_frozen_assessments(root: Path, state: ApprovedBatch) -> None:
    """Verify frozen assessed terminals and publish their standalone durable bundles."""
    materialize: list[tuple[bytes, AssessmentSnapshot]] = []
    domains = tuple(item.id for item in SCIENTIFIC_PACK.domains)
    projection = VerifiedProjection(root)
    with transaction(root) as connection:
        for trial in state.proposal.trials:
            result = _result(state, trial.id)
            terminal_row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"terminal_trial:{state.frozen_hash}:{trial.id}",),
            ).fetchone()
            if terminal_row is None:
                continue
            try:
                marker = AssessmentTerminal.model_validate_json(bytes(terminal_row[0]))
            except ValueError:
                continue
            checkpoints = {}
            for domain_id in domains:
                row = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"domain_judgment:{state.frozen_hash}:{trial.id}:{result.id}:{domain_id}",),
                ).fetchone()
                if row is None:
                    raise ValueError("assessment terminal has incomplete checkpoints")
                checkpoints[domain_id], _revision = _checkpoint(
                    root,
                    state,
                    trial.id,
                    result.id,
                    domain_id,
                    bytes(row[0]),
                    connection,
                    projection,
                )
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"assessment_snapshot:{state.frozen_hash}:{trial.id}",),
            ).fetchone()
            if row is None:
                raise ValueError("assessment terminal snapshot is missing")
            raw = bytes(row[0])
            snapshot = _snapshot(state, trial, result, raw, checkpoints)
            if marker.snapshot_hash != snapshot.snapshot_hash:
                raise ValueError("assessment terminal is not cross-bound")
            materialize.append((raw, snapshot))
    for raw, snapshot in materialize:
        target = export_verified_snapshot(root, raw, snapshot)
        if not _complete_bundle(target, raw, snapshot):
            raise ValueError("materialized assessment bundle is invalid")


def recovery_progress(workspace: str | Path) -> RecoveryProgress:
    root = Path(workspace).resolve(strict=True)
    try:
        projection = VerifiedProjection(root)
        with transaction(root) as connection:
            state = current_batch_in_transaction(root, connection, projection=projection)
            if isinstance(state, NoActiveBatch):
                return RecoveryProgress(status="no_active", active_batch=state)
            if isinstance(state, StaleBatch):
                return RecoveryProgress(status="stale", problems=state.problems, active_batch=state)
            if not _frozen_is_exact(state):
                return _corrupt("approved batch frozen hash is invalid")
            approved_detail = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"detail:batch:{state.frozen_hash}",),
            ).fetchone()
            if approved_detail is None or bytes(approved_detail[0]) != canonical_json_bytes(state):
                return _corrupt("Approved Batch Detail is unavailable or corrupt")
            domains = tuple(item.id for item in SCIENTIFIC_PACK.domains)
            checkpoints: dict[str, dict[str, DomainJudgment]] = {}
            revisions: dict[str, dict[str, int]] = {}
            terminals: dict[str, object] = {}
            snapshots: dict[str, AssessmentSnapshot] = {}
            snapshot_data: dict[str, bytes] = {}
            recommended_packets: dict[str, tuple[str, str]] = {}
            correction_packets: dict[str, dict[str, str]] = {}
            synthesis_packets: dict[str, str] = {}
            for requested in state.proposal.request.trial_inputs:
                trial = next(item for item in state.proposal.trials if item.id == requested.id)
                result = _result(state, trial.id)
                completed: dict[str, DomainJudgment] = {}
                completed_revisions: dict[str, int] = {}
                for domain_id in domains:
                    row = connection.execute(
                        "SELECT payload FROM records WHERE name=?",
                        (
                            f"domain_judgment:{state.frozen_hash}:{trial.id}:{result.id}:{domain_id}",
                        ),
                    ).fetchone()
                    if row is not None:
                        completed[domain_id], completed_revisions[domain_id] = _checkpoint(
                            root,
                            state,
                            trial.id,
                            result.id,
                            domain_id,
                            bytes(row[0]),
                            connection,
                            projection,
                        )
                checkpoints[trial.id] = completed
                revisions[trial.id] = completed_revisions
                terminal_row = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"terminal_trial:{state.frozen_hash}:{trial.id}",),
                ).fetchone()
                if terminal_row is None:
                    continue
                raw = bytes(terminal_row[0])
                try:
                    terminal: object = verified_terminal(ProblemTerminal.model_validate_json(raw))
                    if (
                        terminal.approved_batch_hash != state.frozen_hash
                        or terminal.trial != trial
                        or terminal.result_spec != result
                        or terminal.pack_identities != state.pack_identities
                    ):
                        raise ValueError("problem terminal does not bind the approved batch")
                    terminal_detail = connection.execute(
                        "SELECT payload FROM records WHERE name=?",
                        (f"detail:terminal:{terminal.terminal_hash}",),
                    ).fetchone()
                    if terminal_detail is None or bytes(terminal_detail[0]) != raw:
                        raise ValueError("problem terminal Detail is unavailable or corrupt")
                    if (
                        len(completed) != len(SCIENTIFIC_PACK.domains)
                        and terminal.synthesis_hash is not None
                    ):
                        raise ValueError("partial problem terminal has a synthesis identity")
                except ValueError:
                    terminal = AssessmentTerminal.model_validate_json(raw)
                    snapshot_row = connection.execute(
                        "SELECT payload FROM records WHERE name=?",
                        (f"assessment_snapshot:{state.frozen_hash}:{trial.id}",),
                    ).fetchone()
                    if snapshot_row is None:
                        raise ValueError("assessment terminal snapshot is missing")
                    snapshot = _snapshot(state, trial, result, bytes(snapshot_row[0]), completed)
                    if terminal.snapshot_hash != snapshot.snapshot_hash:
                        raise ValueError("assessment terminal is not cross-bound")
                    for detail_key in (
                        f"detail:terminal:{snapshot.snapshot_hash}",
                        f"detail:trial:{snapshot.snapshot_hash}",
                    ):
                        detail = connection.execute(
                            "SELECT payload FROM records WHERE name=?", (detail_key,)
                        ).fetchone()
                        if detail is None or bytes(detail[0]) != bytes(snapshot_row[0]):
                            raise ValueError("assessment terminal Detail is unavailable or corrupt")
                    snapshots[trial.id] = snapshot
                    snapshot_data[trial.id] = bytes(snapshot_row[0])
                terminals[trial.id] = terminal
            summary_row = connection.execute(
                "SELECT payload FROM records WHERE name=?", (f"batch_summary:{state.frozen_hash}",)
            ).fetchone()
            summary = (
                None
                if summary_row is None
                else _summary(state, bytes(summary_row[0]), terminals, snapshots)
            )
            if summary is not None:
                summary_detail = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"detail:batch:{summary.summary_hash}",),
                ).fetchone()
                if summary_detail is None or bytes(summary_detail[0]) != bytes(summary_row[0]):
                    raise ValueError("Batch Summary Detail is unavailable or corrupt")
            from rob2_kit.packets import (
                ApprovedWorkPacket,
                TrialSynthesisPacket,
                VerifiedDomainPacketBasis,
                VerifiedSynthesisPacketBasis,
                build_approved_work_packet,
                build_trial_synthesis_packet,
                verify_approved_work_packet,
                verify_trial_synthesis_packet,
            )

            for name, payload in connection.execute(
                "SELECT name,payload FROM records WHERE name LIKE 'detail:domain:%' "
                "OR name LIKE 'detail:synthesis:%'"
            ).fetchall():
                try:
                    if name.startswith("detail:domain:"):
                        packet = verify_approved_work_packet(
                            ApprovedWorkPacket.model_validate_json(bytes(payload))
                        )
                        if name != f"detail:domain:{packet.packet_hash}":
                            raise ValueError("packet record key does not match identity")
                        if packet.approved_batch_hash != state.frozen_hash:
                            raise ValueError("packet does not bind the approved batch")
                        trial_id = packet.trial.id
                        if packet.domain_id not in checkpoints.get(trial_id, {}):
                            current = recommended_packets.get(trial_id)
                            if current is None or packet.domain_id < current[0]:
                                recommended_packets[trial_id] = (
                                    packet.domain_id,
                                    packet.packet_hash,
                                )
                    else:
                        packet = verify_trial_synthesis_packet(
                            TrialSynthesisPacket.model_validate_json(bytes(payload))
                        )
                        if name != f"detail:synthesis:{packet.packet_hash}":
                            raise ValueError("packet record key does not match identity")
                        if packet.approved_batch_hash != state.frozen_hash:
                            raise ValueError("packet does not bind the approved batch")
                        synthesis_packets[packet.trial.id] = packet.packet_hash
                except (TypeError, ValueError, KeyError) as error:
                    raise ValueError(f"invalid packet record {name}: {error}") from error
            for requested in state.proposal.request.trial_inputs:
                trial = next(item for item in state.proposal.trials if item.id == requested.id)
                if trial.id in terminals:
                    if not isinstance(terminals[trial.id], AssessmentTerminal) and len(
                        checkpoints[trial.id]
                    ) != len(SCIENTIFIC_PACK.domains):
                        continue
                result = _result(state, trial.id)
                completed = checkpoints[trial.id]
                ordered = tuple(
                    completed[domain.id]
                    for domain in SCIENTIFIC_PACK.domains
                    if domain.id in completed
                )
                for judgment in ordered:
                    ensure_judgment_detail(connection, judgment, state)
                correction_packets[trial.id] = {}
                for domain in SCIENTIFIC_PACK.domains:
                    if domain.id not in completed:
                        continue
                    active = completed[domain.id]
                    correction = build_approved_work_packet(
                        VerifiedDomainPacketBasis(
                            approved_batch=state,
                            trial_id=trial.id,
                            result_id=result.id,
                            domain_id=domain.id,
                            active_judgment=active,
                            active_revision=revisions[trial.id][domain.id],
                            predecessor_hash=active.checkpoint_hash,
                            prior_judgments=tuple(
                                item
                                for item in ordered
                                if domains.index(item.domain_id) < domains.index(domain.id)
                            ),
                            detail_refs=tuple(
                                detail_reference("judgment", item.checkpoint_hash)
                                for item in ordered
                            ),
                        )
                    )
                    correction_key = f"detail:domain:{correction.packet_hash}"
                    correction_payload = canonical_json_bytes(correction)
                    correction_row = connection.execute(
                        "SELECT payload FROM records WHERE name=?", (correction_key,)
                    ).fetchone()
                    if (
                        correction_row is not None
                        and bytes(correction_row[0]) != correction_payload
                    ):
                        raise ValueError(f"invalid correction packet record {correction_key}")
                    if correction_row is None:
                        connection.execute(
                            "INSERT INTO records(name,payload) VALUES(?,?)",
                            (correction_key, correction_payload),
                        )
                    correction_packets[trial.id][domain.id] = correction.packet_hash
                if len(ordered) == len(SCIENTIFIC_PACK.domains):
                    packet = build_trial_synthesis_packet(
                        VerifiedSynthesisPacketBasis(
                            approved_batch=state,
                            trial_id=trial.id,
                            result_id=result.id,
                            active_judgments=ordered,
                            detail_refs=tuple(
                                detail_reference("judgment", item.checkpoint_hash)
                                for item in ordered
                            ),
                        )
                    )
                    kind = "synthesis"
                    snapshot = snapshots.get(trial.id)
                    if snapshot is not None and snapshot.synthesis_hash != packet.packet_hash:
                        raise ValueError("assessment snapshot synthesis identity is stale")
                    terminal = terminals.get(trial.id)
                    if (
                        isinstance(terminal, ProblemTerminal)
                        and terminal.synthesis_hash != packet.packet_hash
                    ):
                        raise ValueError("problem terminal synthesis identity is stale")
                    synthesis_packets[trial.id] = packet.packet_hash
                else:
                    next_domain = next(
                        domain.id
                        for domain in SCIENTIFIC_PACK.domains
                        if domain.id not in completed
                    )
                    packet = build_approved_work_packet(
                        VerifiedDomainPacketBasis(
                            approved_batch=state,
                            trial_id=trial.id,
                            result_id=result.id,
                            domain_id=next_domain,
                            prior_judgments=ordered,
                            detail_refs=tuple(
                                detail_reference("judgment", item.checkpoint_hash)
                                for item in ordered
                            ),
                        )
                    )
                    kind = "domain"
                    recommended_packets[trial.id] = (next_domain, packet.packet_hash)
                key = f"detail:{kind}:{packet.packet_hash}"
                payload = canonical_json_bytes(packet)
                row = connection.execute(
                    "SELECT payload FROM records WHERE name=?", (key,)
                ).fetchone()
                if row is not None and bytes(row[0]) != payload:
                    raise ValueError(f"invalid regenerated packet record {key}")
                if row is None:
                    connection.execute(
                        "INSERT INTO records(name,payload) VALUES(?,?)", (key, payload)
                    )
    except (OSError, TypeError, ValueError, KeyError) as error:
        return _corrupt(str(error))

    # These are deliberately the exporters' exact validators, never directory existence checks.
    batch_exported = False
    if summary is not None:
        data = summary_row[0] if isinstance(summary_row[0], bytes) else str(summary_row[0]).encode()
        batch_path = root / ".rob2-kit" / "batches" / state.frozen_hash.removeprefix("sha256:")
        batch_exported = _batch_bundle_complete(root, batch_path, data, summary)
        if batch_path.exists() and not batch_exported:
            return _corrupt("committed batch export is invalid")
    progress = []
    for requested in state.proposal.request.trial_inputs:
        trial = next(item for item in state.proposal.trials if item.id == requested.id)
        result = _result(state, trial.id)
        completed_ids = tuple(domain for domain in domains if domain in checkpoints[trial.id])
        terminal = terminals.get(trial.id)
        status: Literal["pending", "assessed", "needs_input", "failed"] = "pending"
        if isinstance(terminal, AssessmentTerminal):
            status = "assessed"
        elif isinstance(terminal, ProblemTerminal):
            status = terminal.category
        snapshot = snapshots.get(trial.id)
        exported = snapshot is not None and _complete_bundle(
            root / ".rob2-kit" / "assessments" / trial.id, snapshot_data[trial.id], snapshot
        )
        assessment_path = root / ".rob2-kit" / "assessments" / trial.id
        if snapshot is not None and assessment_path.exists() and not exported:
            return _corrupt(f"committed assessment export for {trial.id} is invalid")
        terminal_identity = None
        if isinstance(terminal, AssessmentTerminal):
            if snapshot is None:
                return _corrupt(f"assessment snapshot for {trial.id} is unavailable")
            terminal_identity = snapshot.snapshot_hash
        elif isinstance(terminal, ProblemTerminal):
            terminal_identity = terminal.terminal_hash
        progress.append(
            TrialProgress(
                trial_id=trial.id,
                status=status,
                completed_domains=completed_ids,
                pending_domains=()
                if status != "pending"
                else tuple(domain for domain in domains if domain not in completed_ids),
                export_status="exported"
                if exported or batch_exported and status == "assessed"
                else "not_exported",
                active_domain_checkpoints=tuple(
                    ActiveDomainCheckpoint(
                        domain_id=domain_id,
                        active_revision=revisions[trial.id][domain_id],
                        active_hash=checkpoints[trial.id][domain_id].checkpoint_hash,
                    )
                    for domain_id in completed_ids
                ),
                terminal_ref=(
                    None
                    if terminal_identity is None
                    else detail_reference("terminal", terminal_identity)
                ),
                synthesis_ref=(
                    None
                    if summary is not None
                    or len(completed_ids) != len(SCIENTIFIC_PACK.domains)
                    or trial.id not in synthesis_packets
                    else detail_reference("synthesis", synthesis_packets[trial.id])
                ),
                recommended_packet_ref=(
                    None
                    if status != "pending" or trial.id not in recommended_packets
                    else detail_reference("domain", recommended_packets[trial.id][1])
                ),
                correction_packet_refs=tuple(
                    DomainPacketReference(
                        domain_id=domain_id,
                        packet_ref=detail_reference("domain", packet_hash),
                    )
                    for domain_id, packet_hash in (
                        correction_packets.get(trial.id, {}).items() if status == "pending" else ()
                    )
                ),
            )
        )
    return RecoveryProgress(
        status="approved",
        trials=tuple(progress),
        summary_committed=summary is not None,
        active_batch=state,
        summary_ref=None if summary is None else detail_reference("batch", summary.summary_hash),
    )


def current_batch_projection(workspace: str | Path) -> CurrentBatchProjection:
    """Return only compact, verified restart state for the mutable workflow."""

    progress = recovery_progress(workspace)
    from rob2_kit.batch import read_proposal_version

    try:
        proposal_version = read_proposal_version(workspace)
    except ValueError as error:
        return CurrentBatchProjection(
            phase="stale",
            conditions=(Problem(code="corrupt_proposal_version", detail=str(error)),),
            next_action="discard",
        )
    captured = read_captured_batch(workspace)
    captured_ref = None
    if captured is not None:
        try:
            captured_ref = _verified_recovery_ref(workspace, "batch", captured.content_hash)
        except ValueError as error:
            return _detail_stale("Captured Batch Detail", error)
    if progress.status == "no_active" and proposal_version is not None:
        if captured is None or proposal_version.captured_batch_hash != captured.content_hash:
            return CurrentBatchProjection(
                phase="stale",
                conditions=(
                    Problem(
                        code="corrupt_proposal_version",
                        detail="active Proposal version does not bind the Captured Batch",
                    ),
                ),
                next_action="discard",
            )
        try:
            proposal_ref = _verified_recovery_ref(
                workspace, "proposal", proposal_version.version_hash
            )
        except ValueError as error:
            return _detail_stale("Proposal Detail", error)
        return CurrentBatchProjection(
            phase="proposal",
            captured_batch_ref=captured_ref,
            proposal_ref=proposal_ref,
            next_action="read_record",
        )
    if progress.status == "no_active":
        if captured is not None:
            return CurrentBatchProjection(
                phase="intake",
                captured_batch_ref=captured_ref,
                next_action="save_proposal",
            )
        return CurrentBatchProjection(phase="empty", next_action="ingest")
    if progress.status == "stale":
        return CurrentBatchProjection(
            phase="stale",
            conditions=progress.problems,
            next_action="discard",
        )
    approved = progress.active_batch
    assert isinstance(approved, ApprovedBatch)
    if (
        captured is None
        or captured_ref is None
        or proposal_version is None
        or proposal_version.captured_batch_hash != captured.content_hash
        or proposal_version.proposal != approved.proposal
    ):
        return _detail_stale(
            "Approved Batch parent basis",
            ValueError("Captured Batch or active Proposal version is unavailable or mismatched"),
        )
    try:
        proposal_ref = _verified_recovery_ref(workspace, "proposal", proposal_version.version_hash)
        approved_ref = _verified_recovery_ref(workspace, "batch", approved.frozen_hash)
        summary_ref = (
            None
            if progress.summary_ref is None
            else _verified_recovery_ref(workspace, "batch", progress.summary_ref.identity)
        )
        for trial in progress.trials:
            if trial.terminal_ref is not None:
                _verified_recovery_ref(workspace, "terminal", trial.terminal_ref.identity)
    except ValueError as error:
        return _detail_stale("workflow Detail", error)
    phase: Literal["approved", "partial", "synthesis_ready", "mixed_terminal", "finalized"] = (
        "approved"
    )
    next_action: Literal["work_trial", "review_synthesis", "finalize_batch", "complete"] = (
        "work_trial"
    )
    if progress.summary_committed:
        phase = "finalized"
        next_action = "complete"
    elif all(item.status != "pending" for item in progress.trials):
        phase = "mixed_terminal"
        next_action = "finalize_batch"
    elif any(
        len(item.completed_domains) == len(SCIENTIFIC_PACK.domains) for item in progress.trials
    ):
        phase = "synthesis_ready"
        next_action = "review_synthesis"
    elif any(item.completed_domains for item in progress.trials):
        phase = "partial"
    return CurrentBatchProjection(
        phase=phase,
        captured_batch_ref=captured_ref,
        proposal_ref=proposal_ref,
        approved_batch_ref=approved_ref,
        summary_ref=summary_ref,
        trials=progress.trials,
        next_action=next_action,
    )


def _verified_recovery_ref(
    workspace: str | Path, kind: Literal["batch", "proposal", "terminal", "trial"], identity: str
) -> DetailReference:
    reference = detail_reference(kind, identity)
    read_record(workspace, reference)
    return reference


def _detail_stale(label: str, error: ValueError) -> CurrentBatchProjection:
    return CurrentBatchProjection(
        phase="stale",
        conditions=(Problem(code="detail_unavailable", detail=f"{label}: {error}"),),
        next_action="discard",
    )


def discard_active_batch(
    workspace: str | Path, request: DiscardActiveBatchRequest
) -> Discarded | DiscardCondition:
    """Recoverably discard only the exact unfinished frozen batch requested."""

    root = Path(workspace).resolve(strict=True)
    internal = root / ".rob2-kit"
    try:
        with workspace_mutation_lock(root):
            target = _discard_target(root, request)
            if isinstance(target, DiscardCondition):
                return target
            frozen, state = target
            progress = recovery_progress(root)
            if any(item.code == "corrupt_active_batch" for item in progress.problems):
                return DiscardCondition(
                    code="corrupt_active_batch", detail=progress.problems[0].detail
                )
            try:
                _preserve_frozen_assessments(root, frozen)
            except (OSError, ValueError, KeyError) as error:
                return DiscardCondition(code="corrupt_active_batch", detail=str(error))
            if isinstance(state, ApprovedBatch):
                for item in progress.trials:
                    if item.status == "assessed":
                        try:
                            export_trial(root, item.trial_id, _result(state, item.trial_id).id)
                        except (OSError, ValueError) as error:
                            return DiscardCondition(code="corrupt_active_batch", detail=str(error))
            revalidated = _discard_target(root, request)
            if isinstance(revalidated, DiscardCondition):
                return revalidated
            if internal.is_symlink() or _reparse(internal):
                return DiscardCondition(
                    code="corrupt_active_batch", detail="internal workspace directory is redirected"
                )
            # Published assessment and batch trees (including stages and backups) belong
            # to the exporters. Discard owns only the active SQLite runtime files.
            targets = [
                internal / name
                for name in (
                    "active-batch.sqlite3",
                    "active-batch.sqlite3-wal",
                    "active-batch.sqlite3-shm",
                    "active-batch.sqlite3-journal",
                    "text-projections.sqlite3",
                    "text-projections.sqlite3-wal",
                    "text-projections.sqlite3-shm",
                    "text-projections.sqlite3-journal",
                )
                if (internal / name).exists()
            ]
            try:
                for target in targets:
                    if target.is_symlink() or _reparse(target):
                        raise ValueError("discard target is redirected")
                trash = internal / f".discard-trash-{uuid.uuid4().hex}"
                trash.mkdir()
                if trash.is_symlink() or _reparse(trash):
                    raise ValueError("discard trash is redirected")
            except (OSError, ValueError) as error:
                return DiscardCondition(code="corrupt_active_batch", detail=str(error))
            moved: list[tuple[Path, Path]] = []
            try:
                for index, target in enumerate(targets):
                    destination = trash / str(index)
                    target.replace(destination)
                    moved.append((target, destination))
            except OSError as error:
                for target, destination in reversed(moved):
                    if destination.exists() and not target.exists():
                        destination.replace(target)
                shutil.rmtree(trash, ignore_errors=True)
                return DiscardCondition(code="discard_move_failed", detail=str(error))
            removed = tuple(target.relative_to(root).as_posix() for target, _ in moved)
            try:
                shutil.rmtree(trash)
            except OSError as error:
                location = trash.relative_to(root).as_posix()
                detail = (
                    "runtime state removed; recoverable trash retained " + f"at {location}: {error}"
                )
                return DiscardCondition(
                    code="discard_trash_retained",
                    detail=detail,
                )
            return Discarded(removed=removed)
    except (OSError, ValueError, KeyError) as error:
        return DiscardCondition(code="corrupt_active_batch", detail=str(error))


def _discard_target(
    root: Path, request: DiscardActiveBatchRequest
) -> tuple[ApprovedBatch, ApprovedBatch | StaleBatch] | DiscardCondition:
    """Read and validate the discard target in a closed SQLite transaction."""

    with transaction(root) as connection:
        state = current_batch_in_transaction(root, connection)
        if isinstance(state, NoActiveBatch):
            return DiscardCondition(code="no_active_batch", detail="there is no active batch")
        frozen = state.approved if isinstance(state, StaleBatch) else state
        if not isinstance(frozen, ApprovedBatch):
            return DiscardCondition(
                code="active_batch_not_frozen",
                detail="only a current frozen batch can be explicitly discarded",
            )
        if request.expected_frozen_hash != frozen.frozen_hash:
            return DiscardCondition(
                code="discard_identity_mismatch",
                detail="expected_frozen_hash does not identify the current frozen batch",
            )
        row = connection.execute(
            "SELECT 1 FROM records WHERE name=?", (f"batch_summary:{frozen.frozen_hash}",)
        ).fetchone()
        if row is not None:
            return DiscardCondition(
                code="batch_finalized",
                detail="committed batch summaries cannot be discarded",
            )
        if not isinstance(state, (ApprovedBatch, StaleBatch)):
            raise AssertionError("frozen active batch has an unexpected state")
        return frozen, state
