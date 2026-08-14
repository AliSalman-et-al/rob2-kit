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
    ProposedBatch,
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
from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.judgment_models import DomainJudgment
from rob2_kit.judgments import (
    _validate_evidence,
    _verified_checkpoint,
    build_domain_judgment,
    verify_revision_history,
)
from rob2_kit.models import StrictModel, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.reports import (
    _batch_bundle_complete,
    _complete_bundle,
    export_trial,
    export_verified_snapshot,
)
from rob2_kit.storage import _reparse, transaction, workspace_mutation_lock


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


class TrialProgress(StrictModel):
    trial_id: str
    status: Literal["pending", "assessed", "needs_input", "failed"]
    completed_domains: tuple[str, ...]
    pending_domains: tuple[str, ...]
    export_status: Literal["not_exported", "exported"]
    active_domain_checkpoints: tuple[ActiveDomainCheckpoint, ...] = ()


class RecoveryProgress(StrictModel):
    status: Literal["no_active", "proposal", "approved", "stale"]
    trials: tuple[TrialProgress, ...] = ()
    summary_committed: bool = False
    problems: tuple[Problem, ...] = ()
    active_batch: NoActiveBatch | ProposedBatch | ApprovedBatch | StaleBatch | None = None


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
    connection=None,
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
    revision = 1
    if connection is not None:
        revision, _predecessor_hash = verify_revision_history(
            root,
            connection,
            state,
            trial_id,
            result_id,
            domain_id,
            judgment,
        )
    for answer in judgment.active_answers:
        for use in answer.evidence_uses:
            for ref in use.refs:
                _validate_evidence(root, state, trial_id, result_id, ref)
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
            or entry.terminal_hash != terminal.terminal_hash
            or entry.problems != terminal.problems
        ):
            raise ValueError("summary problem entry is not cross-bound")
    return summary


def _preserve_frozen_assessments(root: Path, state: ApprovedBatch) -> None:
    """Verify frozen assessed terminals and publish their standalone durable bundles."""
    materialize: list[tuple[bytes, AssessmentSnapshot]] = []
    domains = tuple(item.id for item in SCIENTIFIC_PACK.domains)
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
                    root, state, trial.id, result.id, domain_id, bytes(row[0]), connection
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
        with transaction(root) as connection:
            state = current_batch_in_transaction(root, connection)
            if isinstance(state, NoActiveBatch):
                return RecoveryProgress(status="no_active", active_batch=state)
            if not isinstance(state, ApprovedBatch):
                if isinstance(state, StaleBatch):
                    return RecoveryProgress(
                        status="stale", problems=state.problems, active_batch=state
                    )
                return RecoveryProgress(status="proposal", active_batch=state)
            if not _frozen_is_exact(state):
                return _corrupt("approved batch frozen hash is invalid")
            domains = tuple(item.id for item in SCIENTIFIC_PACK.domains)
            checkpoints: dict[str, dict[str, DomainJudgment]] = {}
            revisions: dict[str, dict[str, int]] = {}
            terminals: dict[str, object] = {}
            snapshots: dict[str, AssessmentSnapshot] = {}
            snapshot_data: dict[str, bytes] = {}
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
                            root, state, trial.id, result.id, domain_id, bytes(row[0]), connection
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
            )
        )
    return RecoveryProgress(
        status="approved",
        trials=tuple(progress),
        summary_committed=summary is not None,
        active_batch=state,
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
