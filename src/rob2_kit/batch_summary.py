"""Terminal Trial outcomes, approved summaries, and public artifact receipts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from rob2_kit.assessment import OutcomeTarget, ResultSpec, Trial
from rob2_kit.batch import ApprovedBatch, PackIdentity, StaleBatch, current_batch_in_transaction
from rob2_kit.detail import DetailReference, detail_reference
from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.models import Judgment, StrictModel, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.storage import transaction

ContentHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def _utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamp must be UTC")
    return value


def _actor(value: str) -> str:
    if not value.strip():
        raise ValueError("actor must not be blank")
    return value.strip()


class Problem(StrictModel):
    code: Annotated[str, Field(min_length=1)]
    category: Literal["needs_input", "failed"]
    detail: Annotated[str, Field(min_length=1)]
    trial_id: Annotated[str, Field(min_length=1)]
    result_id: Annotated[str, Field(min_length=1)]
    actor: Annotated[str, Field(min_length=1)]
    observed_at: datetime

    _observed_at_utc = field_validator("observed_at")(_utc)
    _actor_nonblank = field_validator("actor")(_actor)


class ProblemTerminal(StrictModel):
    schema_id: Literal["rob2.problem_terminal"] = "rob2.problem_terminal"
    schema_version: Literal[2] = 2
    approved_batch_hash: str
    trial: Trial
    result_spec: ResultSpec
    category: Literal["needs_input", "failed"]
    problems: tuple[Problem, ...] = Field(min_length=1)
    pack_identities: tuple[PackIdentity, ...]
    actor: Annotated[str, Field(min_length=1)]
    observed_at: datetime
    terminal_hash: str
    operation_hash: str | None = None
    synthesis_hash: str | None = None

    _observed_at_utc = field_validator("observed_at")(_utc)
    _actor_nonblank = field_validator("actor")(_actor)

    @model_validator(mode="after")
    def binds_problems(self) -> ProblemTerminal:
        if self.result_spec.trial != self.trial or any(
            item.category != self.category
            or item.trial_id != self.trial.id
            or item.result_id != self.result_spec.id
            or item.actor != self.actor
            or item.observed_at != self.observed_at
            for item in self.problems
        ):
            raise ValueError("problem terminal does not bind its Trial and ResultSpec")
        return self


class AssessmentTerminal(StrictModel):
    """The small #190 terminal marker for a canonical assessment snapshot."""

    snapshot_hash: str


class AssessedEntry(StrictModel):
    status: Literal["assessed"] = "assessed"
    trial: Trial
    result_spec: ResultSpec
    snapshot_hash: str
    judgments: tuple[Judgment, ...] = Field(min_length=5)
    final_judgment: Judgment
    limitations: tuple[str, ...]


class NeedsInputEntry(StrictModel):
    status: Literal["needs_input"] = "needs_input"
    terminal_hash: str
    trial: Trial
    result_spec: ResultSpec
    problems: tuple[Problem, ...]


class FailedEntry(StrictModel):
    status: Literal["failed"] = "failed"
    terminal_hash: str
    trial: Trial
    result_spec: ResultSpec
    problems: tuple[Problem, ...]


SummaryEntry = Annotated[
    AssessedEntry | NeedsInputEntry | FailedEntry, Field(discriminator="status")
]


class Counts(StrictModel):
    assessed: Annotated[int, Field(ge=0)]
    needs_input: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]


class BatchSummary(StrictModel):
    schema_id: Literal["rob2.batch_summary"] = "rob2.batch_summary"
    schema_version: Literal[2] = 2
    approved_batch_hash: str
    outcome_target: OutcomeTarget
    entries: tuple[SummaryEntry, ...] = Field(min_length=1)
    counts: Counts
    pack_identities: tuple[PackIdentity, ...]
    actor: Annotated[str, Field(min_length=1)]
    observed_at: datetime
    summary_hash: str

    _observed_at_utc = field_validator("observed_at")(_utc)
    _actor_nonblank = field_validator("actor")(_actor)

    @model_validator(mode="after")
    def counts_match_entries(self) -> BatchSummary:
        actual = Counts(
            assessed=sum(item.status == "assessed" for item in self.entries),
            needs_input=sum(item.status == "needs_input" for item in self.entries),
            failed=sum(item.status == "failed" for item in self.entries),
        )
        if actual != self.counts:
            raise ValueError("summary counts do not match entries")
        return self


class TerminalSaved(StrictModel):
    status: Literal["saved"] = "saved"
    terminal: ProblemTerminal


class TerminalConflict(StrictModel):
    status: Literal["conflict"] = "conflict"
    terminal: ProblemTerminal | AssessmentTerminal


class BatchSaved(StrictModel):
    status: Literal["saved"] = "saved"
    summary: BatchSummary


class ArtifactReceipt(StrictModel):
    """The verified, portable identity of one materialized batch bundle."""

    algorithm: Literal["sha256(sorted-relative-path-nul-bytes-nul)"] = (
        "sha256(sorted-relative-path-nul-bytes-nul)"
    )
    bundle_path: Annotated[str, Field(min_length=1)]
    bundle_hash: ContentHash
    file_count: Annotated[int, Field(ge=1)]
    summary_hash: ContentHash
    index_hash: ContentHash

    @field_validator("bundle_path")
    @classmethod
    def is_workspace_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.parts
            or value == "."
            or path.as_posix() != value
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or ":" in value
        ):
            raise ValueError("artifact path must be workspace-relative")
        return value


class FinalizedBatch(StrictModel):
    """Public finalize result: a committed summary and its verified bundle."""

    status: Literal["saved"] = "saved"
    summary: BatchSummary
    receipt: ArtifactReceipt


class BatchConflict(StrictModel):
    status: Literal["conflict"] = "conflict"
    summary: BatchSummary


class BatchCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


class TerminalOutcome(StrictModel):
    """Compact handoff identity for one finalized Trial."""

    trial_id: str
    status: Literal["assessed", "needs_input", "failed"]
    terminal_ref: DetailReference
    snapshot_ref: DetailReference | None = None


class FinalizationSuccess(StrictModel):
    """Compact v2 finalization receipt; the Summary remains a Detail record."""

    status: Literal["committed"] = "committed"
    approved_batch_hash: str
    summary_ref: DetailReference
    receipt: ArtifactReceipt
    outcomes: tuple[TerminalOutcome, ...] = Field(min_length=1)
    assessed: int = Field(ge=0)
    needs_input: int = Field(ge=0)
    failed: int = Field(ge=0)
    next_action: Literal["complete"] = "complete"


class FinalizationCondition(StrictModel):
    status: Literal["condition"] = "condition"
    code: str
    detail: str


def terminal_content(terminal: ProblemTerminal) -> dict[str, object]:
    return terminal.model_dump(mode="python", exclude={"terminal_hash"})


def verified_terminal(terminal: ProblemTerminal) -> ProblemTerminal:
    if terminal.terminal_hash != sha256(terminal_content(terminal)):
        raise ValueError("problem terminal integrity verification failed")
    return terminal


def summary_content(summary: BatchSummary) -> dict[str, object]:
    return summary.model_dump(mode="python", exclude={"summary_hash"})


def verified_summary(summary: BatchSummary) -> BatchSummary:
    if summary.summary_hash != sha256(summary_content(summary)):
        raise ValueError("batch summary integrity verification failed")
    return summary


def _approved_or_condition(workspace, connection):
    state = current_batch_in_transaction(workspace, connection)
    if not isinstance(state, ApprovedBatch):
        return None, BatchCondition(
            code="batch_stale" if isinstance(state, StaleBatch) else "batch_not_approved",
            detail="an approved nonstale batch is required",
        )
    return state, None


def terminalize_problem(workspace, trial_id: str, category, problems: tuple[Problem, ...]):
    with transaction(workspace) as connection:
        state, condition = _approved_or_condition(workspace, connection)
        if condition:
            return condition
        trial = next((item for item in state.proposal.trials if item.id == trial_id), None)
        result = next(
            (item for item in state.proposal.result_specs if item.trial.id == trial_id), None
        )
        if trial is None or result is None:
            raise ValueError("unknown approved Trial")
        if not problems:
            raise ValueError("at least one problem is required")
        from rob2_kit.finish import _synthesis_packet
        from rob2_kit.judgments import judgment_key
        from rob2_kit.text_projection import VerifiedProjection

        complete = all(
            connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (judgment_key(state.frozen_hash, trial.id, result.id, domain.id),),
            ).fetchone()
            is not None
            for domain in SCIENTIFIC_PACK.domains
        )
        synthesis = (
            _synthesis_packet(
                workspace,
                connection,
                state,
                trial.id,
                result.id,
                VerifiedProjection(workspace),
            )
            if complete
            else None
        )
        incomplete = ProblemTerminal(
            approved_batch_hash=state.frozen_hash,
            trial=trial,
            result_spec=result,
            category=category,
            problems=problems,
            pack_identities=state.pack_identities,
            actor=problems[0].actor,
            observed_at=problems[0].observed_at,
            synthesis_hash=None if synthesis is None else synthesis.packet_hash,
            terminal_hash="pending",
        )
        terminal = incomplete.model_copy(
            update={"terminal_hash": sha256(terminal_content(incomplete))}
        )
        key = f"terminal_trial:{state.frozen_hash}:{trial_id}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is None:
            payload = canonical_json_bytes(terminal)
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (key, payload),
            )
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (f"detail:terminal:{terminal.terminal_hash}", payload),
            )
            return TerminalSaved(terminal=terminal)
        try:
            existing = verified_terminal(ProblemTerminal.model_validate_json(bytes(row[0])))
        except ValueError:
            try:
                existing_assessment = AssessmentTerminal.model_validate_json(bytes(row[0]))
            except ValueError as error:
                raise ValueError("invalid existing Trial terminal") from error
            return TerminalConflict(terminal=existing_assessment)
        return (
            TerminalSaved(terminal=existing)
            if existing == terminal
            else TerminalConflict(terminal=existing)
        )


def _assessment_entry(
    state: ApprovedBatch, trial: Trial, result: ResultSpec, marker: AssessmentTerminal, connection
) -> AssessedEntry:
    row = connection.execute(
        "SELECT payload FROM records WHERE name=?",
        (f"assessment_snapshot:{state.frozen_hash}:{trial.id}",),
    ).fetchone()
    if row is None:
        raise ValueError("terminal assessment snapshot is missing")
    snapshot = _verified(AssessmentSnapshot.model_validate_json(bytes(row[0])))
    if (
        marker.snapshot_hash != snapshot.snapshot_hash
        or snapshot.approved_batch_hash != state.frozen_hash
        or snapshot.trial != trial
        or snapshot.result_spec != result
        or snapshot.pack_identities != state.pack_identities
    ):
        raise ValueError("assessment terminal does not bind the approved batch")
    return AssessedEntry(
        trial=trial,
        result_spec=result,
        snapshot_hash=snapshot.snapshot_hash,
        judgments=tuple(item.final_judgment for item in snapshot.domain_judgments),
        final_judgment=snapshot.final_judgment,
        limitations=snapshot.limitations,
    )


def finalize_batch(workspace, actor: str, observed_at: datetime):
    with transaction(workspace) as connection:
        state, condition = _approved_or_condition(workspace, connection)
        if condition:
            return condition
        entries: list[SummaryEntry] = []
        incomplete: list[str] = []
        for requested in state.proposal.request.trial_inputs:
            trial = next(item for item in state.proposal.trials if item.id == requested.id)
            result = next(
                item for item in state.proposal.result_specs if item.trial.id == requested.id
            )
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"terminal_trial:{state.frozen_hash}:{trial.id}",),
            ).fetchone()
            if row is None:
                incomplete.append(trial.id)
                continue
            raw = bytes(row[0])
            try:
                problem = verified_terminal(ProblemTerminal.model_validate_json(raw))
            except ValueError:
                try:
                    marker = AssessmentTerminal.model_validate_json(raw)
                except ValueError as error:
                    raise ValueError("invalid Trial terminal") from error
                entries.append(_assessment_entry(state, trial, result, marker, connection))
                continue
            if (
                problem.approved_batch_hash != state.frozen_hash
                or problem.trial != trial
                or problem.result_spec != result
                or problem.pack_identities != state.pack_identities
            ):
                raise ValueError("problem terminal does not bind the approved batch")
            entry_type = NeedsInputEntry if problem.category == "needs_input" else FailedEntry
            entries.append(
                entry_type(
                    terminal_hash=problem.terminal_hash,
                    trial=trial,
                    result_spec=result,
                    problems=problem.problems,
                )
            )
        if incomplete:
            return BatchCondition(code="trials_incomplete", detail=",".join(incomplete))
        incomplete_summary = BatchSummary(
            approved_batch_hash=state.frozen_hash,
            outcome_target=state.proposal.request.outcome_target,
            entries=tuple(entries),
            counts=Counts(
                assessed=sum(e.status == "assessed" for e in entries),
                needs_input=sum(e.status == "needs_input" for e in entries),
                failed=sum(e.status == "failed" for e in entries),
            ),
            pack_identities=state.pack_identities,
            actor=actor,
            observed_at=observed_at,
            summary_hash="pending",
        )
        summary = incomplete_summary.model_copy(
            update={"summary_hash": sha256(summary_content(incomplete_summary))}
        )
        key = f"batch_summary:{state.frozen_hash}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (key, canonical_json_bytes(summary)),
            )
            return BatchSaved(summary=summary)
        existing = verified_summary(BatchSummary.model_validate_json(bytes(row[0])))
        return (
            BatchSaved(summary=existing) if existing == summary else BatchConflict(summary=existing)
        )


def _finalization_success(workspace: str | Path, summary: BatchSummary) -> FinalizationSuccess:
    """Materialize and verify the portable handoff for one exact Summary."""

    from rob2_kit.reports import batch_artifact_receipt, export_batch

    with transaction(workspace) as connection:
        payload = canonical_json_bytes(summary)
        key = f"detail:batch:{summary.summary_hash}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is not None and bytes(row[0]) != payload:
            raise ValueError("batch Summary Detail record is corrupt")
        if row is None:
            connection.execute("INSERT INTO records(name,payload) VALUES(?,?)", (key, payload))
        for entry in summary.entries:
            terminal_key = f"terminal_trial:{summary.approved_batch_hash}:{entry.trial.id}"
            terminal_row = connection.execute(
                "SELECT payload FROM records WHERE name=?", (terminal_key,)
            ).fetchone()
            if terminal_row is None:
                raise ValueError("finalized Trial terminal is unavailable")
            if entry.status == "assessed":
                snapshot_row = connection.execute(
                    "SELECT payload FROM records WHERE name=?",
                    (f"assessment_snapshot:{summary.approved_batch_hash}:{entry.trial.id}",),
                ).fetchone()
                if snapshot_row is None:
                    raise ValueError("finalized assessment snapshot is unavailable")
                snapshot = _verified(AssessmentSnapshot.model_validate_json(bytes(snapshot_row[0])))
                marker = AssessmentTerminal.model_validate_json(bytes(terminal_row[0]))
                if (
                    marker.snapshot_hash != snapshot.snapshot_hash
                    or entry.snapshot_hash != snapshot.snapshot_hash
                ):
                    raise ValueError("finalized assessment terminal is not cross-bound")
                terminal_payload = bytes(snapshot_row[0])
                trial_detail_key = f"detail:trial:{snapshot.snapshot_hash}"
                existing_trial = connection.execute(
                    "SELECT payload FROM records WHERE name=?", (trial_detail_key,)
                ).fetchone()
                if existing_trial is not None and bytes(existing_trial[0]) != terminal_payload:
                    raise ValueError("assessment Trial Detail record is corrupt")
                if existing_trial is None:
                    connection.execute(
                        "INSERT INTO records(name,payload) VALUES(?,?)",
                        (trial_detail_key, terminal_payload),
                    )
            else:
                terminal = verified_terminal(
                    ProblemTerminal.model_validate_json(bytes(terminal_row[0]))
                )
                if (
                    terminal.terminal_hash != entry.terminal_hash
                    or terminal.category != entry.status
                ):
                    raise ValueError("finalized problem terminal is not cross-bound")
                terminal_payload = bytes(terminal_row[0])
            terminal_identity = (
                entry.snapshot_hash if entry.status == "assessed" else entry.terminal_hash
            )
            terminal_detail_key = f"detail:terminal:{terminal_identity}"
            existing_terminal = connection.execute(
                "SELECT payload FROM records WHERE name=?", (terminal_detail_key,)
            ).fetchone()
            if existing_terminal is not None and bytes(existing_terminal[0]) != terminal_payload:
                raise ValueError("terminal Detail record is corrupt")
            if existing_terminal is None:
                connection.execute(
                    "INSERT INTO records(name,payload) VALUES(?,?)",
                    (terminal_detail_key, terminal_payload),
                )
    target = export_batch(workspace, summary.approved_batch_hash)
    receipt = batch_artifact_receipt(Path(workspace).resolve(strict=True), target, summary)
    outcomes = tuple(
        TerminalOutcome(
            trial_id=entry.trial.id,
            status=entry.status,
            terminal_ref=detail_reference(
                "terminal",
                entry.snapshot_hash if entry.status == "assessed" else entry.terminal_hash,
            ),
            snapshot_ref=(
                detail_reference("trial", entry.snapshot_hash)
                if entry.status == "assessed"
                else None
            ),
        )
        for entry in summary.entries
    )
    return FinalizationSuccess(
        approved_batch_hash=summary.approved_batch_hash,
        summary_ref=detail_reference("batch", summary.summary_hash),
        receipt=receipt,
        outcomes=outcomes,
        assessed=summary.counts.assessed,
        needs_input=summary.counts.needs_input,
        failed=summary.counts.failed,
    )


def finalize_batch_v2(
    workspace: str | Path, actor: str
) -> FinalizationSuccess | FinalizationCondition:
    """Finalize using server time and return only compact verified identities."""

    from datetime import UTC

    try:
        with transaction(workspace) as connection:
            state, condition = _approved_or_condition(workspace, connection)
            if condition is not None:
                return FinalizationCondition(code=condition.code, detail=condition.detail)
            assert isinstance(state, ApprovedBatch)
            key = f"batch_summary:{state.frozen_hash}"
            row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
            summary = (
                None
                if row is None
                else verified_summary(BatchSummary.model_validate_json(bytes(row[0])))
            )
        if summary is None:
            saved = finalize_batch(workspace, actor, datetime.now(UTC))
            if not isinstance(saved, BatchSaved):
                if isinstance(saved, BatchConflict):
                    summary = saved.summary
                else:
                    return FinalizationCondition(code=saved.code, detail=saved.detail)
            else:
                summary = saved.summary
        return _finalization_success(workspace, summary)
    except (OSError, ValueError, KeyError) as error:
        return FinalizationCondition(code="artifact_unavailable", detail=str(error))
