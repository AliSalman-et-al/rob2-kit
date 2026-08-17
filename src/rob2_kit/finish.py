"""Atomic terminal assessment snapshots for one approved Trial."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rob2_kit.assessment import ResultSpec, Trial
from rob2_kit.batch import ApprovedBatch, PackIdentity, StaleBatch, current_batch_in_transaction
from rob2_kit.detail import DetailReference, detail_reference
from rob2_kit.judgment_models import DomainJudgment, Override
from rob2_kit.judgments import (
    _validate_evidence,
    _verified_checkpoint,
    build_domain_judgment,
    ensure_judgment_detail,
    judgment_key,
    verify_revision_history,
)
from rob2_kit.logic.evaluator import evaluate_overall
from rob2_kit.models import Judgment, OverallEvaluation, StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.sources import Source
from rob2_kit.storage import transaction
from rob2_kit.text_projection import VerifiedProjection


class AssessmentSnapshot(StrictModel):
    schema_id: Literal["rob2.assessment_snapshot"] = "rob2.assessment_snapshot"
    schema_version: Literal[2] = 2
    approved_batch_hash: str
    trial: Trial
    result_spec: ResultSpec
    domain_judgments: tuple[DomainJudgment, ...] = Field(min_length=5)
    proposed_overall: OverallEvaluation
    combined_concerns: bool | None = None
    final_judgment: Judgment
    override: Override | None = None
    limitations: tuple[str, ...] = ()
    sources: tuple[Source, ...]
    pack_identities: tuple[PackIdentity, ...]
    actor: str
    observed_at: datetime
    synthesis_hash: str
    operation_hash: str | None = None
    snapshot_hash: str

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value

    @model_validator(mode="after")
    def coherent(self) -> AssessmentSnapshot:
        if (self.final_judgment != self.proposed_overall.judgment) != (self.override is not None):
            raise ValueError("override is required exactly when final judgment differs")
        if {item.domain_id for item in self.domain_judgments} != {
            item.id for item in SCIENTIFIC_PACK.domains
        }:
            raise ValueError("all five Domain judgments are required")
        return self


class FinishSaved(StrictModel):
    status: Literal["saved"] = "saved"
    snapshot: AssessmentSnapshot
    next_action: Literal["finalize_batch"] = "finalize_batch"


class FinishConflict(StrictModel):
    status: Literal["conflict"] = "conflict"
    snapshot: AssessmentSnapshot | None = None
    terminal_hash: str | None = None

    @model_validator(mode="after")
    def has_existing_terminal(self) -> FinishConflict:
        if (self.snapshot is None) == (self.terminal_hash is None):
            raise ValueError("conflict requires exactly one existing terminal")
        return self


class FinishCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


FinishTrialResult = FinishSaved | FinishConflict | FinishCondition


class OverallOverrideDraft(StrictModel):
    final_judgment: Judgment
    justification: str = Field(min_length=1)


class AssessmentFinishOperation(StrictModel):
    approved_batch_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_id: str
    result_id: str
    reviewed_synthesis_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    actor: str = Field(min_length=1)
    combined_concerns: bool | None = None
    limitations: tuple[str, ...] = ()
    override: OverallOverrideDraft | None = None


class ProblemDraft(StrictModel):
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ProblemFinishOperation(StrictModel):
    approved_batch_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_id: str
    result_id: str
    category: Literal["needs_input", "failed"]
    actor: str = Field(min_length=1)
    problems: tuple[ProblemDraft, ...] = Field(min_length=1)


class AssessmentFinishSuccess(StrictModel):
    status: Literal["committed"] = "committed"
    approved_batch_hash: str
    trial_id: str
    result_id: str
    terminal_ref: DetailReference
    snapshot_ref: DetailReference
    synthesis_hash: str
    final_judgment: Judgment
    next_action: Literal["finalize_batch"] = "finalize_batch"


class ProblemFinishSuccess(StrictModel):
    status: Literal["committed"] = "committed"
    approved_batch_hash: str
    trial_id: str
    result_id: str
    category: Literal["needs_input", "failed"]
    terminal_ref: DetailReference
    next_action: Literal["finalize_batch"] = "finalize_batch"


class FinishV2Conflict(StrictModel):
    status: Literal["conflict"] = "conflict"
    terminal_ref: DetailReference
    next_action: Literal["review_and_retry"] = "review_and_retry"


class FinishV2Condition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


def snapshot_content(snapshot: AssessmentSnapshot) -> dict[str, object]:
    return snapshot.model_dump(mode="python", exclude={"snapshot_hash"})


def _verified(snapshot: AssessmentSnapshot) -> AssessmentSnapshot:
    if snapshot.snapshot_hash != sha256(snapshot_content(snapshot)):
        raise ValueError("assessment snapshot integrity verification failed")
    return snapshot


def _synthesis_packet(
    workspace: str | Path,
    connection,
    state: ApprovedBatch,
    trial_id: str,
    result_id: str,
    projection: VerifiedProjection | None = None,
):
    from rob2_kit.packets import (
        VerifiedSynthesisPacketBasis,
        build_trial_synthesis_packet,
        verify_trial_synthesis_packet,
    )

    judgments: list[DomainJudgment] = []
    projection = projection or VerifiedProjection(workspace)
    for domain in SCIENTIFIC_PACK.domains:
        key = judgment_key(state.frozen_hash, trial_id, result_id, domain.id)
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is None:
            raise ValueError("all five Domain checkpoints are required")
        checkpoint = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0])))
        verify_revision_history(
            workspace,
            connection,
            state,
            trial_id,
            result_id,
            domain.id,
            checkpoint,
            projection,
        )
        if (
            checkpoint.approved_batch_hash != state.frozen_hash
            or checkpoint.trial_id != trial_id
            or checkpoint.result_id != result_id
            or checkpoint.domain_id != domain.id
            or checkpoint.scientific_pack not in state.pack_identities
            or checkpoint.policy_pack not in state.pack_identities
        ):
            raise ValueError("Domain checkpoint identity does not match Approved Batch")
        rebuilt = build_domain_judgment(
            state,
            trial_id,
            result_id,
            domain.id,
            checkpoint.active_answers,
            checkpoint.inactive_questions,
            checkpoint.final_judgment,
            checkpoint.override,
            checkpoint.limitations,
            checkpoint.actor,
            checkpoint.observed_at,
        )
        if rebuilt != checkpoint:
            raise ValueError("Domain checkpoint logic does not match saved content")
        for answer in checkpoint.active_answers:
            for use in answer.evidence_uses:
                for ref in use.refs:
                    _validate_evidence(workspace, state, trial_id, result_id, ref, projection)
        judgments.append(checkpoint)
        ensure_judgment_detail(connection, checkpoint, state)
    packet = verify_trial_synthesis_packet(
        build_trial_synthesis_packet(
            VerifiedSynthesisPacketBasis(
                approved_batch=state,
                trial_id=trial_id,
                result_id=result_id,
                active_judgments=tuple(judgments),
                detail_refs=tuple(
                    detail_reference("judgment", item.checkpoint_hash) for item in judgments
                ),
            )
        )
    )
    key = f"detail:synthesis:{packet.packet_hash}"
    row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
    payload = canonical_json_bytes(packet)
    if row is None:
        raise ValueError("synthesis Detail record is unavailable")
    if bytes(row[0]) != payload:
        raise ValueError("synthesis Detail record is corrupt")
    return packet


def finish_assessment_v2(
    workspace: str | Path,
    operation: AssessmentFinishOperation,
) -> AssessmentFinishSuccess | FinishV2Conflict | FinishV2Condition:
    """Freeze an assessed Trial only after exact synthesis review."""

    operation_hash = sha256(operation)
    from rob2_kit.batch_summary import AssessmentTerminal, ProblemTerminal, verified_terminal

    projection = VerifiedProjection(workspace)
    with transaction(workspace) as connection:
        state = current_batch_in_transaction(workspace, connection, projection=projection)
        if not isinstance(state, ApprovedBatch):
            return FinishV2Condition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        if state.frozen_hash != operation.approved_batch_hash:
            return FinishV2Condition(
                code="approved_batch_mismatch",
                detail="operation does not bind the Approved Batch",
            )
        trial = next(
            (item for item in state.proposal.trials if item.id == operation.trial_id), None
        )
        result = next(
            (
                item
                for item in state.proposal.result_specs
                if item.trial.id == operation.trial_id and item.id == operation.result_id
            ),
            None,
        )
        if trial is None or result is None or result.trial.id != trial.id:
            return FinishV2Condition(
                code="result_identity_invalid", detail="Trial/Result is not approved"
            )
        terminal_key = f"terminal_trial:{state.frozen_hash}:{trial.id}"
        existing_terminal = connection.execute(
            "SELECT payload FROM records WHERE name=?", (terminal_key,)
        ).fetchone()
        try:
            packet = _synthesis_packet(
                workspace, connection, state, trial.id, result.id, projection
            )
        except (OSError, ValueError) as error:
            return FinishV2Condition(code="synthesis_invalid", detail=str(error))
        if packet.packet_hash != operation.reviewed_synthesis_hash:
            return FinishV2Condition(
                code="synthesis_acknowledgment_mismatch",
                detail="reviewed synthesis hash does not match current verified synthesis",
            )
        if existing_terminal is not None:
            try:
                marker = AssessmentTerminal.model_validate_json(bytes(existing_terminal[0]))
                snapshot_row = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"assessment_snapshot:{state.frozen_hash}:{trial.id}",),
                ).fetchone()
                if snapshot_row is None:
                    raise ValueError("assessment snapshot is missing")
                snapshot = _verified(AssessmentSnapshot.model_validate_json(bytes(snapshot_row[0])))
                if (
                    marker.snapshot_hash == snapshot.snapshot_hash
                    and snapshot.operation_hash == operation_hash
                ):
                    return _assessment_finish_success(snapshot, packet)
                return FinishV2Conflict(
                    terminal_ref=detail_reference("terminal", snapshot.snapshot_hash)
                )
            except ValueError:
                try:
                    problem = verified_terminal(
                        ProblemTerminal.model_validate_json(bytes(existing_terminal[0]))
                    )
                except ValueError as error:
                    raise ValueError("invalid existing Trial terminal") from error
                return FinishV2Conflict(
                    terminal_ref=detail_reference("terminal", problem.terminal_hash)
                )
        # Read the exact five checkpoints from the synthesis packet's bound basis.
        domain_judgments = tuple(
            _verified_checkpoint(
                DomainJudgment.model_validate_json(
                    bytes(
                        connection.execute(
                            "SELECT payload FROM records WHERE name=?",
                            (judgment_key(state.frozen_hash, trial.id, result.id, domain.id),),
                        ).fetchone()[0]
                    )
                )
            )
            for domain in SCIENTIFIC_PACK.domains
        )
        try:
            proposed = evaluate_overall(
                {item.domain_id: item.proposed_judgment for item in domain_judgments},
                combined_concerns=operation.combined_concerns,
            )
        except ValueError as error:
            return FinishV2Condition(code="combined_concerns_required", detail=str(error))
        final = (
            proposed.judgment if operation.override is None else operation.override.final_judgment
        )
        if (final != proposed.judgment) != (operation.override is not None):
            return FinishV2Condition(
                code="overall_override_invalid",
                detail="overall override is required exactly when final judgment differs",
            )
        observed_at = datetime.now(UTC)
        override = (
            None
            if operation.override is None
            else Override(
                justification=operation.override.justification,
                actor=operation.actor,
                observed_at=observed_at,
            )
        )
        incomplete = AssessmentSnapshot(
            approved_batch_hash=state.frozen_hash,
            trial=trial,
            result_spec=result,
            domain_judgments=domain_judgments,
            proposed_overall=proposed,
            combined_concerns=operation.combined_concerns,
            final_judgment=final,
            override=override,
            limitations=operation.limitations,
            sources=tuple(
                source for source in state.proposal.sources if source.trial_id == trial.id
            ),
            pack_identities=state.pack_identities,
            actor=operation.actor,
            observed_at=observed_at,
            synthesis_hash=packet.packet_hash,
            operation_hash=operation_hash,
            snapshot_hash="pending",
        )
        snapshot = incomplete.model_copy(
            update={"snapshot_hash": sha256(snapshot_content(incomplete))}
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (f"assessment_snapshot:{state.frozen_hash}:{trial.id}", canonical_json_bytes(snapshot)),
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (
                terminal_key,
                canonical_json_bytes(AssessmentTerminal(snapshot_hash=snapshot.snapshot_hash)),
            ),
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (f"detail:trial:{snapshot.snapshot_hash}", canonical_json_bytes(snapshot)),
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (f"detail:terminal:{snapshot.snapshot_hash}", canonical_json_bytes(snapshot)),
        )
        return _assessment_finish_success(snapshot, packet)


def _assessment_finish_success(snapshot: AssessmentSnapshot, packet) -> AssessmentFinishSuccess:
    return AssessmentFinishSuccess(
        approved_batch_hash=snapshot.approved_batch_hash,
        trial_id=snapshot.trial.id,
        result_id=snapshot.result_spec.id,
        terminal_ref=detail_reference("terminal", snapshot.snapshot_hash),
        snapshot_ref=detail_reference("trial", snapshot.snapshot_hash),
        synthesis_hash=packet.packet_hash,
        final_judgment=snapshot.final_judgment,
    )


def _verify_extant_checkpoints(
    workspace: str | Path,
    connection,
    state: ApprovedBatch,
    trial: Trial,
    result: ResultSpec,
    projection: VerifiedProjection,
) -> None:
    for domain in SCIENTIFIC_PACK.domains:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (judgment_key(state.frozen_hash, trial.id, result.id, domain.id),),
        ).fetchone()
        if row is None:
            continue
        checkpoint = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(row[0])))
        verify_revision_history(
            workspace,
            connection,
            state,
            trial.id,
            result.id,
            domain.id,
            checkpoint,
            projection,
        )
        if (
            checkpoint.approved_batch_hash != state.frozen_hash
            or checkpoint.trial_id != trial.id
            or checkpoint.result_id != result.id
            or checkpoint.domain_id != domain.id
            or checkpoint.scientific_pack not in state.pack_identities
            or checkpoint.policy_pack not in state.pack_identities
        ):
            raise ValueError("Domain checkpoint does not bind the Approved Batch")
        rebuilt = build_domain_judgment(
            state,
            trial.id,
            result.id,
            domain.id,
            checkpoint.active_answers,
            checkpoint.inactive_questions,
            checkpoint.final_judgment,
            checkpoint.override,
            checkpoint.limitations,
            checkpoint.actor,
            checkpoint.observed_at,
        )
        if rebuilt != checkpoint:
            raise ValueError("Domain checkpoint logic does not match saved content")
        for answer in checkpoint.active_answers:
            for use in answer.evidence_uses:
                for ref in use.refs:
                    _validate_evidence(workspace, state, trial.id, result.id, ref, projection)


def finish_problem_v2(
    workspace: str | Path,
    operation: ProblemFinishOperation,
) -> ProblemFinishSuccess | FinishV2Conflict | FinishV2Condition:
    """Freeze a compact needs-input/failed Trial problem terminal."""

    from rob2_kit.batch_summary import (
        AssessmentTerminal,
        Problem,
        ProblemTerminal,
        terminal_content,
        verified_terminal,
    )

    operation_hash = sha256(operation)
    projection = VerifiedProjection(workspace)
    with transaction(workspace) as connection:
        state = current_batch_in_transaction(workspace, connection, projection=projection)
        if not isinstance(state, ApprovedBatch):
            return FinishV2Condition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        if state.frozen_hash != operation.approved_batch_hash:
            return FinishV2Condition(
                code="approved_batch_mismatch",
                detail="operation does not bind the Approved Batch",
            )
        trial = next(
            (item for item in state.proposal.trials if item.id == operation.trial_id), None
        )
        result = next(
            (
                item
                for item in state.proposal.result_specs
                if item.trial.id == operation.trial_id and item.id == operation.result_id
            ),
            None,
        )
        if trial is None or result is None or result.trial.id != trial.id:
            return FinishV2Condition(
                code="result_identity_invalid", detail="Trial/Result is not approved"
            )
        try:
            _verify_extant_checkpoints(workspace, connection, state, trial, result, projection)
        except (OSError, ValueError, TypeError) as error:
            return FinishV2Condition(code="checkpoint_invalid", detail=str(error))
        terminal_key = f"terminal_trial:{state.frozen_hash}:{trial.id}"
        existing_row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (terminal_key,)
        ).fetchone()
        completed_count = sum(
            connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (judgment_key(state.frozen_hash, trial.id, result.id, domain.id),),
            ).fetchone()
            is not None
            for domain in SCIENTIFIC_PACK.domains
        )
        synthesis_packet = None
        if completed_count == len(SCIENTIFIC_PACK.domains):
            try:
                synthesis_packet = _synthesis_packet(
                    workspace, connection, state, trial.id, result.id, projection
                )
            except (OSError, ValueError) as error:
                return FinishV2Condition(code="synthesis_invalid", detail=str(error))
        if existing_row is not None:
            raw = bytes(existing_row[0])
            try:
                existing = verified_terminal(ProblemTerminal.model_validate_json(raw))
                if existing.operation_hash == operation_hash:
                    if existing.synthesis_hash != (
                        None if synthesis_packet is None else synthesis_packet.packet_hash
                    ):
                        raise ValueError("problem terminal synthesis identity is corrupt")
                    return ProblemFinishSuccess(
                        approved_batch_hash=state.frozen_hash,
                        trial_id=trial.id,
                        result_id=result.id,
                        category=existing.category,
                        terminal_ref=detail_reference("terminal", existing.terminal_hash),
                    )
                return FinishV2Conflict(
                    terminal_ref=detail_reference("terminal", existing.terminal_hash)
                )
            except ValueError:
                try:
                    marker = AssessmentTerminal.model_validate_json(raw)
                except ValueError as error:
                    raise ValueError("invalid existing Trial terminal") from error
                snapshot_row = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"assessment_snapshot:{state.frozen_hash}:{trial.id}",),
                ).fetchone()
                if snapshot_row is None:
                    raise ValueError("assessment snapshot is missing")
                snapshot = _verified(AssessmentSnapshot.model_validate_json(bytes(snapshot_row[0])))
                if marker.snapshot_hash != snapshot.snapshot_hash:
                    raise ValueError("assessment terminal does not bind its snapshot")
                return FinishV2Conflict(
                    terminal_ref=detail_reference("terminal", marker.snapshot_hash)
                )
        observed_at = datetime.now(UTC)
        problems = tuple(
            Problem(
                code=item.code,
                category=operation.category,
                detail=item.detail,
                trial_id=trial.id,
                result_id=result.id,
                actor=operation.actor,
                observed_at=observed_at,
            )
            for item in operation.problems
        )
        incomplete = ProblemTerminal(
            approved_batch_hash=state.frozen_hash,
            trial=trial,
            result_spec=result,
            category=operation.category,
            problems=problems,
            pack_identities=state.pack_identities,
            actor=operation.actor,
            observed_at=observed_at,
            operation_hash=operation_hash,
            synthesis_hash=(None if synthesis_packet is None else synthesis_packet.packet_hash),
            terminal_hash="pending",
        )
        terminal = incomplete.model_copy(
            update={"terminal_hash": sha256(terminal_content(incomplete))}
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (terminal_key, canonical_json_bytes(terminal)),
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (f"detail:terminal:{terminal.terminal_hash}", canonical_json_bytes(terminal)),
        )
        return ProblemFinishSuccess(
            approved_batch_hash=state.frozen_hash,
            trial_id=trial.id,
            result_id=result.id,
            category=terminal.category,
            terminal_ref=detail_reference("terminal", terminal.terminal_hash),
        )
