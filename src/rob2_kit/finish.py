"""Atomic terminal assessment snapshots for one approved Trial."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rob2_kit.assessment import ResultSpec, Trial
from rob2_kit.batch import ApprovedBatch, PackIdentity, StaleBatch, current_batch_in_transaction
from rob2_kit.judgment_models import DomainJudgment, Override
from rob2_kit.judgments import (
    _validate_evidence,
    _verified_checkpoint,
    build_domain_judgment,
    judgment_key,
    verify_revision_history,
)
from rob2_kit.logic.evaluator import evaluate_overall
from rob2_kit.models import Judgment, OverallEvaluation, StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.sources import Source
from rob2_kit.storage import transaction


class AssessmentSnapshot(StrictModel):
    schema_id: Literal["rob2.assessment_snapshot"] = "rob2.assessment_snapshot"
    schema_version: Literal[1] = 1
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


def snapshot_content(snapshot: AssessmentSnapshot) -> dict[str, object]:
    return snapshot.model_dump(mode="python", exclude={"snapshot_hash"})


def _verified(snapshot: AssessmentSnapshot) -> AssessmentSnapshot:
    if snapshot.snapshot_hash != sha256(snapshot_content(snapshot)):
        raise ValueError("assessment snapshot integrity verification failed")
    return snapshot


def finish_trial(
    workspace: str | Path,
    trial_id: str,
    final_judgment: Judgment | None,
    override: Override | None,
    combined_concerns: bool | None,
    limitations: tuple[str, ...],
    actor: str,
    observed_at: datetime,
) -> FinishTrialResult:
    with transaction(workspace) as connection:
        state = current_batch_in_transaction(workspace, connection)
        if not isinstance(state, ApprovedBatch):
            return FinishCondition(
                code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
                detail="an approved nonstale batch is required",
            )
        trial = next((item for item in state.proposal.trials if item.id == trial_id), None)
        result = next(
            (item for item in state.proposal.result_specs if item.trial.id == trial_id), None
        )
        if trial is None or result is None:
            raise ValueError("unknown approved Trial")
        terminal_key = f"terminal_trial:{state.frozen_hash}:{trial_id}"
        existing_terminal = connection.execute(
            "SELECT payload FROM records WHERE name=?", (terminal_key,)
        ).fetchone()
        if existing_terminal is not None:
            try:
                from rob2_kit.batch_summary import (
                    AssessmentTerminal,
                    ProblemTerminal,
                    verified_terminal,
                )

                verified_terminal(ProblemTerminal.model_validate_json(bytes(existing_terminal[0])))
            except ValueError:
                try:
                    AssessmentTerminal.model_validate_json(bytes(existing_terminal[0]))
                except ValueError as error:
                    raise ValueError("invalid existing Trial terminal") from error
            else:
                return FinishConflict(
                    terminal_hash=verified_terminal(
                        ProblemTerminal.model_validate_json(bytes(existing_terminal[0]))
                    ).terminal_hash
                )
        expected = {item.id for item in SCIENTIFIC_PACK.domains}
        judgments = []
        for domain_id in expected:
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (judgment_key(state.frozen_hash, trial_id, result.id, domain_id),),
            ).fetchone()
            if row is None:
                continue
            data = row[0]
            checkpoint = _verified_checkpoint(DomainJudgment.model_validate_json(bytes(data)))
            verify_revision_history(
                workspace,
                connection,
                state,
                trial_id,
                result.id,
                domain_id,
                checkpoint,
            )
            if (
                checkpoint.approved_batch_hash != state.frozen_hash
                or checkpoint.trial_id != trial_id
                or checkpoint.result_id != result.id
                or checkpoint.domain_id != domain_id
                or checkpoint.scientific_pack not in state.pack_identities
                or checkpoint.policy_pack not in state.pack_identities
            ):
                raise ValueError("checkpoint identity does not match approved batch")
            rebuilt = build_domain_judgment(
                state,
                trial_id,
                result.id,
                checkpoint.domain_id,
                checkpoint.active_answers,
                checkpoint.inactive_questions,
                checkpoint.final_judgment,
                checkpoint.override,
                checkpoint.limitations,
                checkpoint.actor,
                checkpoint.observed_at,
            )
            if rebuilt != checkpoint:
                raise ValueError("checkpoint logic does not match saved content")
            for answer in checkpoint.active_answers:
                for use in answer.evidence_uses:
                    for ref in use.refs:
                        _validate_evidence(workspace, state, trial_id, result.id, ref)
            judgments.append(checkpoint)
        if {item.domain_id for item in judgments} != expected:
            return FinishCondition(
                code="domains_incomplete", detail="all five Domain checkpoints are required"
            )
        judgments.sort(key=lambda item: item.domain_id)
        proposed = evaluate_overall(
            {item.domain_id: item.proposed_judgment for item in judgments},
            combined_concerns=combined_concerns,
        )
        final = proposed.judgment if final_judgment is None else final_judgment
        incomplete = AssessmentSnapshot(
            approved_batch_hash=state.frozen_hash,
            trial=trial,
            result_spec=result,
            domain_judgments=tuple(judgments),
            proposed_overall=proposed,
            combined_concerns=combined_concerns,
            final_judgment=final,
            override=override,
            limitations=limitations,
            sources=tuple(s for s in state.proposal.sources if s.trial_id == trial_id),
            pack_identities=state.pack_identities,
            actor=actor,
            observed_at=observed_at,
            snapshot_hash="pending",
        )
        snapshot = incomplete.model_copy(
            update={"snapshot_hash": sha256(snapshot_content(incomplete))}
        )
        key = f"assessment_snapshot:{state.frozen_hash}:{trial_id}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is not None:
            existing = _verified(AssessmentSnapshot.model_validate_json(bytes(row[0])))
            return (
                FinishSaved(snapshot=existing)
                if existing == snapshot
                else FinishConflict(snapshot=existing)
            )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)", (key, canonical_json_bytes(snapshot))
        )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES(?,?)",
            (
                terminal_key,
                canonical_json_bytes({"snapshot_hash": snapshot.snapshot_hash}),
            ),
        )
        return FinishSaved(snapshot=snapshot)
