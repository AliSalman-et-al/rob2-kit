"""Terminal Trial outcomes, approved summaries, and public artifact receipts."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from rob2_kit.assessment import OutcomeTarget, ResultSpec, Trial
from rob2_kit.batch import ApprovedBatch, PackIdentity, StaleBatch, current_batch_in_transaction
from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.models import Judgment, StrictModel, canonical_json_bytes, sha256
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
    schema_version: Literal[1] = 1
    approved_batch_hash: str
    trial: Trial
    result_spec: ResultSpec
    category: Literal["needs_input", "failed"]
    problems: tuple[Problem, ...] = Field(min_length=1)
    pack_identities: tuple[PackIdentity, ...]
    actor: Annotated[str, Field(min_length=1)]
    observed_at: datetime
    terminal_hash: str

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
    schema_version: Literal[1] = 1
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
        incomplete = ProblemTerminal(
            approved_batch_hash=state.frozen_hash,
            trial=trial,
            result_spec=result,
            category=category,
            problems=problems,
            pack_identities=state.pack_identities,
            actor=problems[0].actor,
            observed_at=problems[0].observed_at,
            terminal_hash="pending",
        )
        terminal = incomplete.model_copy(
            update={"terminal_hash": sha256(terminal_content(incomplete))}
        )
        key = f"terminal_trial:{state.frozen_hash}:{trial_id}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (key, canonical_json_bytes(terminal)),
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
