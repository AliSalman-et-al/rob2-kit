"""Typed host-neutral application boundary for lean-v1 Runs."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from rob2_kit.application.contracts import (
    ConfirmedRunDefinition,
    ConfirmRunDefinitionRequest,
    ConfirmRunDefinitionResponse,
    ContinueRunRequest,
    ContinueRunResponse,
    GetWorkContextRequest,
    GetWorkContextResponse,
    InspectVisualCandidateRequest,
    InspectVisualCandidateResponse,
    IntegrityFailure,
    OperationError,
    PrepareRunRequest,
    PrepareRunResponse,
    ReadEvidenceRequest,
    ReadEvidenceResponse,
    ResultStatus,
    RunDirective,
    RunOperation,
    RunProposal,
    RunProposalAmbiguity,
    RunProposalSelection,
    RunStatusRequest,
    RunStatusResponse,
    SearchEvidenceRequest,
    SearchEvidenceResponse,
    SubmitDomainAnswersRequest,
    SubmitDomainAnswersResponse,
    SubmitDomainEvidenceRequest,
    SubmitDomainEvidenceResponse,
    SubmitResultResolutionRequest,
    SubmitResultResolutionResponse,
    SubmitRunProposalRequest,
    SubmitRunProposalResponse,
    SubmitSourceClassificationRequest,
    SubmitSourceClassificationResponse,
    WorkContext,
    WorkflowCondition,
    WorkItem,
    WorkToken,
)
from rob2_kit.application.lifecycle import (
    LifecycleIntegrityError,
    LifecycleProjection,
    ResultState,
    RunState,
    derive_lifecycle,
)
from rob2_kit.domain.assessment import JudgmentLevel
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import Actor, ActorKind, FrozenModel, Identifier
from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalPage,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.visual import VisualCandidate, VisualInspectionPolicy
from rob2_kit.ingestion.project import (
    DocumentParser,
    LiteParseAdapter,
    ProjectInitialization,
    initialize_project,
)
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import load_logic_pack
from rob2_kit.registry import ClinicalTrialsGovAdapter, RegistryAcquisitionStatus, RegistryPolicy
from rob2_kit.reports import AssessmentView, DomainView, ReportProjector
from rob2_kit.storage import (
    ArtifactStore,
    CommitResult,
    LeaseToken,
    LedgerSchemaRefusal,
    RunIntegrityFailure,
    Transition,
    WorkflowEvent,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)

ENGINE_ACTOR = Actor(
    kind=ActorKind.SYSTEM,
    actor_id="actor:run-engine",
    display_name="rob2-kit RunEngine",
    software_name="rob2-kit",
    software_version="0.1.0",
)


class SecondProjectRootError(ValueError):
    """Structured rejection for a process attempting to bind a second root."""

    code = "second_project_root"
    recovery = (
        "Reuse the RunEngine process for its already bound project root.",
        "Start a fresh process before preparing another project.",
    )

    def __init__(self, bound_root: Path, requested_root: Path) -> None:
        self.bound_root = bound_root
        self.requested_root = requested_root
        self.error = OperationError(
            code="second_project_root",
            detail=(
                f"RunEngine is already bound to project root {bound_root}; "
                f"cannot bind requested root {requested_root}."
            ),
            recovery=self.recovery,
        )
        super().__init__(self.error.detail)


class StaleWorkTokenError(ValueError):
    """A typed submission used an expired or mismatched work token."""

    def __init__(self, run_id: Identifier, expected: WorkItem | None) -> None:
        self.run_id = run_id
        self.expected = expected
        detail = (
            "the issued work item is no longer current"
            if expected is not None
            else "this Run has no currently issued work item"
        )
        super().__init__(detail)


class _PreparedRunRecord(FrozenModel):
    lifecycle_event: Literal["run_prepared"] = "run_prepared"
    run_id: Identifier
    proposal: RunProposal
    prepared_at: datetime


class _ProposalSubmittedRecord(FrozenModel):
    lifecycle_event: Literal["run_proposal_submitted"] = "run_proposal_submitted"
    run_id: Identifier
    proposal: RunProposal


class _ConfirmedRunRecord(FrozenModel):
    lifecycle_event: Literal["run_confirmed"] = "run_confirmed"
    run_id: Identifier
    run_definition: ConfirmedRunDefinition


class _ResultDiscoveredRecord(FrozenModel):
    lifecycle_event: Literal["result_discovered"] = "result_discovered"
    run_id: Identifier
    result_id: Identifier
    result_spec: ResultSpecRevision


class _ResultDiagnosticRecord(FrozenModel):
    """Terminal diagnostic outcome for a Trial-specific initialization failure."""

    lifecycle_event: Literal["result_diagnostic_ready"] = "result_diagnostic_ready"
    run_id: Identifier
    result_id: Identifier
    trial_id: Identifier
    reason: str


class _RunBlockedRecord(FrozenModel):
    lifecycle_event: Literal["run_blocked"] = "run_blocked"
    run_id: Identifier
    reason: str
    recovery: tuple[str, ...]


class _RunRetiredRecord(FrozenModel):
    lifecycle_event: Literal["run_retired"] = "run_retired"
    run_id: Identifier
    replacement_run_id: Identifier


class _ResultResolutionRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier
    result_spec: ResultSpecRevision


class _DomainEvidenceRecord(FrozenModel):
    """Normalized evidence checkpoint for one Result × domain."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    items: tuple[Identifier, ...] = ()
    coverage_state: str
    coverage_limitations: tuple[str, ...] = ()
    no_information_basis: bool = False
    conflicts: tuple[tuple[Identifier, ...], ...] = ()


class _DomainAnswersRecord(FrozenModel):
    """Normalized signaling-question answers for one Result × domain."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    answers: dict[Identifier, str]
    rationales: dict[Identifier, str]
    assessor_inputs: dict[Identifier, bool] = {}


class _ResultStartedRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier


class _ReportMaterializedRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier
    assessment_revision_id: Identifier
    overall_judgment: JudgmentLevel
    domain_judgments: dict[Identifier, JudgmentLevel]
    report_root: str
    artifact_names: tuple[str, ...]
    staging_root: str | None = None


class _RunCompletedRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier
    assessment_revision_id: Identifier


class RunEngine:
    """Coordinate capabilities through one method per fixed public operation.

    Only the process/root binding is held in memory.  Authoritative Run state,
    proposal content, and lifecycle transitions live in the concrete Workflow
    ledger and content-addressed Artifact store.
    """

    def __init__(
        self,
        *,
        parser: DocumentParser | None = None,
        registry_adapter: Any | None = None,
        registry: Any | None = None,
    ) -> None:
        self._root: Path | None = None
        self._parser = parser
        # Keep the adapter injectable for recorded HTTP fixtures.  The default
        # is constructed lazily in ``prepare_run`` after the project root is
        # known, so its cache is always project-local.
        self._registry_adapter = registry_adapter or registry
        self._registry_client: Any | None = None
        self._owner_id = f"owner:run-engine:{os.getpid()}:{uuid.uuid4()}"

    def prepare_run(self, request: PrepareRunRequest) -> PrepareRunResponse:
        root = request.project_root.resolve()
        self._bind(root)
        state_root = root / ".rob2"
        ledger_path = state_root / "ledger.sqlite3"
        if not request.authorized and not ledger_path.is_file():
            raise PermissionError("Run preparation requires explicit project-root authorization")
        try:
            artifacts = ArtifactStore(state_root / "artifacts")
            ledger = WorkflowLedger(ledger_path, artifacts)
            ledger.preflight()
        except LedgerSchemaRefusal as error:
            return self._schema_refusal(root, error)
        except RunIntegrityFailure as error:
            return self._prepare_integrity_failure(root, str(error))

        try:
            self._validate_method_request(request)
        except ValueError as error:
            return self._prepare_configuration_error(root, ledger, error)

        try:
            current = self._current_prepared_record(ledger)
            unfinished = self._unfinished_prepared_records(ledger)
        except LifecycleIntegrityError as error:
            return self._prepare_integrity_failure(root, str(error))
        if current is not None and not request.start_new:
            projection = self._projection(ledger, current.run_id)
            # A confirmed/blocked/assessing Current run resumes from durable
            # state without reopening semantic initialization.  An awaiting
            # proposal, however, is still mutable input: re-inventory it on
            # every invocation so added Trials/documents and registry identity
            # candidates are issued before the operator confirms meaning.
            if projection.run_state is RunState.AWAITING_CONFIRMATION and request.authorized:
                try:
                    initialization = initialize_project(
                        root,
                        actor=ENGINE_ACTOR,
                        parser=self._parser,
                        registry_adapter=self._registry_for_prepare(root, request.authorized),
                    )
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                existing = self._latest_proposal(ledger, current.run_id)
                try:
                    inputs_changed = (
                        self._input_snapshot_hash(root) != existing.input_snapshot_hash
                    )
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                if inputs_changed:
                    self._index_initial_evidence(root, initialization)
                    refreshed = self._proposal(current.run_id, initialization)
                    now = datetime.now(UTC)
                    suffix = self._digest(
                        f"{current.run_id}|reconcile|{refreshed.input_snapshot_hash}"
                    )
                    transition = self._transition(
                        scope=current.run_id,
                        operation="operation:run-proposal-submitted",
                        operation_key=f"idempotency:reconcile-proposal-{suffix}",
                        entity_id=f"run-proposal-reconciliation:{suffix}",
                        revision_id=f"revision:run-proposal-reconciliation-{suffix}",
                        artifact=_ProposalSubmittedRecord(
                            run_id=current.run_id,
                            proposal=refreshed,
                        ),
                        checkpoint="checkpoint:run-proposal-reconciled",
                        outcome=WorkflowEventOutcome.WORK_REQUIRED,
                        observed_at=now,
                    )
                    transitions = [transition]
                    registered_result_ids = {
                        spec.result.result_id for spec in existing.initialization.result_specs
                    }
                    for result_spec in initialization.result_specs:
                        result_id = result_spec.result.result_id
                        if result_id in registered_result_ids:
                            continue
                        result_suffix = self._digest(f"{current.run_id}|{result_id}")
                        transitions.append(
                            self._transition(
                                scope=result_id,
                                operation="operation:run-register-result",
                                operation_key=f"idempotency:register-result-{result_suffix}",
                                entity_id=f"run-result:{result_suffix}",
                                revision_id=f"revision:run-result-{result_suffix}",
                                artifact=_ResultDiscoveredRecord(
                                    run_id=current.run_id,
                                    result_id=result_id,
                                    result_spec=result_spec,
                                ),
                                checkpoint=f"checkpoint:result-{result_suffix}",
                                outcome=WorkflowEventOutcome.COMPLETED,
                                observed_at=now,
                            )
                        )
                        failed_trial = next(
                            (
                                trial
                                for trial in initialization.trials
                                if trial.trial_id == result_spec.result.trial_id
                                and trial.status == "trial_failed"
                            ),
                            None,
                        )
                        if failed_trial is not None:
                            diagnostic_suffix = self._digest(
                                f"{current.run_id}|{result_id}|diagnostic"
                            )
                            transitions.append(
                                self._transition(
                                    scope=result_id,
                                    operation="operation:result-diagnostic-ready",
                                    operation_key=(
                                        f"idempotency:result-diagnostic-{diagnostic_suffix}"
                                    ),
                                    entity_id=f"result-diagnostic:{diagnostic_suffix}",
                                    revision_id=f"revision:result-diagnostic-{diagnostic_suffix}",
                                    artifact=_ResultDiagnosticRecord(
                                        run_id=current.run_id,
                                        result_id=result_id,
                                        trial_id=failed_trial.trial_id,
                                        reason=(
                                            failed_trial.failure.detail
                                            if failed_trial.failure is not None
                                            else "Trial-specific initialization failed"
                                        ),
                                    ),
                                    checkpoint=(
                                        f"checkpoint:result-diagnostic-{diagnostic_suffix}"
                                    ),
                                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                                    observed_at=now,
                                )
                            )
                    lease = self._acquire_lease(ledger, now)
                    committed = ledger.commit_batch(tuple(transitions), lease, now=now)
                    result = committed[0]
                    return PrepareRunResponse(
                        operation_id=result.operation_id,
                        ledger_cursor=f"ledger:{committed[-1].sequence}",
                        affected_scope=(current.run_id,),
                        condition=WorkflowCondition.CONFIRMATION_REQUIRED,
                        committed=not result.duplicate,
                        next_permitted_action=RunOperation.SUBMIT_RUN_PROPOSAL,
                        run_id=current.run_id,
                        run_state=projection.run_state,
                        proposal=refreshed,
                    )
            if projection.run_state is RunState.AWAITING_CONFIRMATION and not request.authorized:
                existing = self._latest_proposal(ledger, current.run_id)
                try:
                    changed = self._input_snapshot_hash(root) != existing.input_snapshot_hash
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                if changed:
                    return self._prepare_authorization_error(
                        ledger, current.run_id, existing
                    )
            self._repair_report_publication(ledger, current.run_id)
            return PrepareRunResponse(
                operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, current.run_id),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(current.run_id,),
                condition=self._condition_for_state(projection.run_state),
                committed=False,
                next_permitted_action=self._next_action_for_state(projection.run_state),
                run_id=current.run_id,
                run_state=projection.run_state,
                proposal=self._latest_proposal(ledger, current.run_id),
            )
        if current is None and not request.start_new and not request.authorized:
            latest = self._latest_prepared_record(ledger)
            if latest is not None:
                self._repair_report_publication(ledger, latest.run_id)
                projection = self._projection(ledger, latest.run_id)
                if projection.run_state is RunState.COMPLETE:
                    return PrepareRunResponse(
                        operation_id=self._read_operation_id(
                            RunOperation.PREPARE_RUN, latest.run_id
                        ),
                        ledger_cursor=f"ledger:{len(ledger.events())}",
                        affected_scope=(latest.run_id,),
                        condition=WorkflowCondition.RUN_COMPLETE,
                        committed=False,
                        run_id=latest.run_id,
                        run_state=projection.run_state,
                        proposal=self._latest_proposal(ledger, latest.run_id),
                    )
        if not request.authorized:
            raise PermissionError("Starting a new Run requires project-root authorization")

        try:
            initialization = initialize_project(
                root,
                actor=ENGINE_ACTOR,
                parser=self._parser,
                registry_adapter=self._registry_for_prepare(root, request.authorized),
            )
        except ValueError as error:
            return self._prepare_configuration_error(root, ledger, error)
        # The typed boundary owns the evidence index used by its read/search
        # operations.  Indexing is deterministic and happens once at prepare
        # time, so a fresh MCP process can resume from the durable index.
        self._index_initial_evidence(root, initialization)
        run_id = self._new_run_id(root, len(ledger.events()))
        try:
            proposal = self._proposal(run_id, initialization)
        except ValueError as error:
            return self._prepare_configuration_error(root, ledger, error)
        now = datetime.now(UTC)
        prepared = _PreparedRunRecord(
            run_id=run_id,
            proposal=proposal,
            prepared_at=now,
        )
        transitions: list[Transition] = []
        for prior in unfinished:
            retirement_suffix = self._digest(f"{prior.run_id}|{run_id}|retired")
            transitions.append(
                self._transition(
                    scope=prior.run_id,
                    operation="operation:run-retired",
                    operation_key=f"idempotency:retire-run-{retirement_suffix}",
                    entity_id=f"run-retirement:{retirement_suffix}",
                    revision_id=f"revision:run-retirement-{retirement_suffix}",
                    artifact=_RunRetiredRecord(
                        run_id=prior.run_id,
                        replacement_run_id=run_id,
                    ),
                    checkpoint="checkpoint:run-retired",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                )
            )
        prepared_transition_index = len(transitions)
        transitions.append(
            self._transition(
                scope=run_id,
                operation="operation:run-prepared",
                operation_key=f"idempotency:prepare-{run_id.removeprefix('run:')}",
                entity_id=f"run-record:{run_id.removeprefix('run:')}",
                revision_id=f"revision:run-{run_id.removeprefix('run:')}-prepared",
                artifact=prepared,
                checkpoint="checkpoint:run-prepared",
                outcome=WorkflowEventOutcome.WORK_REQUIRED,
                observed_at=now,
            )
        )
        for result_spec in initialization.result_specs:
            result_id = result_spec.result.result_id
            suffix = self._digest(f"{run_id}|{result_id}")
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:run-register-result",
                    operation_key=f"idempotency:register-result-{suffix}",
                    entity_id=f"run-result:{suffix}",
                    revision_id=f"revision:run-result-{suffix}",
                    artifact=_ResultDiscoveredRecord(
                        run_id=run_id,
                        result_id=result_id,
                        result_spec=result_spec,
                    ),
                    checkpoint=f"checkpoint:result-{suffix}",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                )
            )
            failed_trial = next(
                (
                    trial
                    for trial in initialization.trials
                    if trial.trial_id == result_spec.result.trial_id
                    and trial.status == "trial_failed"
                ),
                None,
            )
            if failed_trial is not None:
                diagnostic_suffix = self._digest(f"{run_id}|{result_id}|diagnostic")
                transitions.append(
                    self._transition(
                        scope=result_id,
                        operation="operation:result-diagnostic-ready",
                        operation_key=f"idempotency:result-diagnostic-{diagnostic_suffix}",
                        entity_id=f"result-diagnostic:{diagnostic_suffix}",
                        revision_id=f"revision:result-diagnostic-{diagnostic_suffix}",
                        artifact=_ResultDiagnosticRecord(
                            run_id=run_id,
                            result_id=result_id,
                            trial_id=failed_trial.trial_id,
                            reason=(
                                failed_trial.failure.detail
                                if failed_trial.failure is not None
                                else "Trial-specific initialization failed"
                            ),
                        ),
                        checkpoint=f"checkpoint:result-diagnostic-{diagnostic_suffix}",
                        outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                        observed_at=now,
                    )
                )
        lease = self._acquire_lease(ledger, now)
        committed = ledger.commit_batch(tuple(transitions), lease, now=now)
        projection = self._projection(ledger, run_id)
        return PrepareRunResponse(
            operation_id=committed[prepared_transition_index].operation_id,
            ledger_cursor=f"ledger:{committed[-1].sequence}",
            affected_scope=tuple(item.run_id for item in unfinished) + (run_id,),
            condition=WorkflowCondition.CONFIRMATION_REQUIRED,
            committed=True,
            next_permitted_action=RunOperation.SUBMIT_RUN_PROPOSAL,
            run_id=run_id,
            run_state=projection.run_state,
            proposal=proposal,
        )

    def run_status(self, request: RunStatusRequest) -> RunStatusResponse:
        try:
            ledger = self._bound_ledger(request.run_id)
            self._repair_report_publication(ledger, request.run_id)
            projection = self._projection(ledger, request.run_id)
        except (LifecycleIntegrityError, RunIntegrityFailure) as error:
            return RunStatusResponse(
                operation_id=self._read_operation_id(RunOperation.RUN_STATUS, request.run_id),
                ledger_cursor="ledger:integrity-failure",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_INTEGRITY_FAILURE,
                committed=False,
                run_id=request.run_id,
                run_state=RunState.INTEGRITY_FAILED,
                integrity=self._integrity_from_error(error),
            )
        return RunStatusResponse(
            operation_id=self._read_operation_id(RunOperation.RUN_STATUS, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            next_permitted_action=self._next_action_for_state(projection.run_state),
            run_id=request.run_id,
            run_state=projection.run_state,
            result_states=tuple(
                ResultStatus(result_id=item.result_id, state=item.state)
                for item in projection.results
            ),
        )

    def continue_run(self, request: ContinueRunRequest) -> ContinueRunResponse:
        try:
            ledger = self._bound_ledger(request.run_id)
            self._repair_report_publication(ledger, request.run_id)
            projection = self._projection(ledger, request.run_id)
        except (LifecycleIntegrityError, RunIntegrityFailure) as error:
            return ContinueRunResponse(
                operation_id=self._read_operation_id(RunOperation.CONTINUE_RUN, request.run_id),
                ledger_cursor="ledger:integrity-failure",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_INTEGRITY_FAILURE,
                committed=False,
                run_id=request.run_id,
                run_state=RunState.INTEGRITY_FAILED,
                directive=RunDirective.RUN_INTEGRITY_FAILURE,
                integrity=self._integrity_from_error(error),
            )
        if projection.run_state is RunState.AWAITING_CONFIRMATION:
            return self._continue_response(
                ledger,
                request.run_id,
                projection,
                RunDirective.CONFIRMATION_REQUIRED,
                committed=False,
            )
        if (
            projection.run_state is RunState.ASSESSING
            and not projection.results
            and self._next_work_item(ledger, request.run_id) is None
        ):
            now = datetime.now(UTC)
            blocked = _RunBlockedRecord(
                run_id=request.run_id,
                reason="No exact Trial-specific Result is available for assessment.",
                recovery=("Add or resolve an exact Result and start a new Run proposal.",),
            )
            transition = self._transition(
                scope=request.run_id,
                operation="operation:run-blocked",
                operation_key=(
                    f"idempotency:block-no-results-{request.run_id.removeprefix('run:')}"
                ),
                entity_id=f"run-blocker:{request.run_id.removeprefix('run:')}",
                revision_id=(
                    f"revision:run-blocker-no-results-{request.run_id.removeprefix('run:')}"
                ),
                artifact=blocked,
                checkpoint="checkpoint:run-blocked",
                outcome=WorkflowEventOutcome.WORK_REQUIRED,
                observed_at=now,
            )
            lease = self._acquire_lease(ledger, now)
            result = ledger.commit(transition, lease, now=now)
            projection = self._projection(ledger, request.run_id)
            return self._continue_response(
                ledger,
                request.run_id,
                projection,
                RunDirective.RUN_BLOCKED,
                committed=not result.duplicate,
                operation_id=result.operation_id,
            )
        if projection.run_state is RunState.ASSESSING:
            work_item = self._next_work_item(ledger, request.run_id)
            if work_item is not None:
                return self._continue_response(
                    ledger,
                    request.run_id,
                    projection,
                    RunDirective.AGENT_WORK_REQUIRED,
                    committed=False,
                    work_item=work_item,
                )
            # A terminal Result checkpoint is committed together with the
            # final answer.  If no work remains but the ledger is still in an
            # assessing state, leave an explicit blocker rather than guessing.
            directive = RunDirective.RUN_BLOCKED
        else:
            directive = {
                RunState.ASSESSING: RunDirective.AGENT_WORK_REQUIRED,
                RunState.BLOCKED: RunDirective.RUN_BLOCKED,
                RunState.COMPLETE: RunDirective.RUN_COMPLETE,
                RunState.INTEGRITY_FAILED: RunDirective.RUN_INTEGRITY_FAILURE,
                RunState.RETIRED: RunDirective.RUN_BLOCKED,
            }[projection.run_state]
        return self._continue_response(
            ledger,
            request.run_id,
            projection,
            directive,
            committed=False,
        )

    def get_work_context(self, request: GetWorkContextRequest) -> GetWorkContextResponse:
        ledger = self._bound_ledger(request.run_id)
        proposal = self._latest_proposal(ledger, request.run_id)
        expected = self._next_work_item(ledger, request.run_id)
        projection = self._projection(ledger, request.run_id)
        if request.work_token.run_id != request.run_id or expected is None:
            return GetWorkContextResponse(
                operation_id=self._read_operation_id(
                    RunOperation.GET_WORK_CONTEXT, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.STALE,
                committed=False,
                run_id=request.run_id,
                run_state=projection.run_state,
                work_item=expected,
                context=None,
                error=OperationError(
                    code="stale_work",
                    detail="No matching engine-issued WorkItem is available for this Run.",
                    recovery=(
                        "Confirm the current Run proposal before requesting work context.",
                        "Use the WorkToken returned by continue_run for the current WorkItem.",
                    ),
                ),
            )
        if (
            projection.run_state is RunState.ASSESSING
            and (expected is None or expected.work_token != request.work_token)
        ):
            return GetWorkContextResponse(
                operation_id=self._read_operation_id(
                    RunOperation.GET_WORK_CONTEXT, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.STALE,
                committed=False,
                run_id=request.run_id,
                run_state=projection.run_state,
                work_item=expected,
                context=None,
            )
        work_item = expected or WorkItem(
            work_item_id=request.work_token.work_item_id,
            work_token=request.work_token,
            operation=request.work_token.operation,
            dependency_fingerprint=request.work_token.dependency_fingerprint,
        )
        result_spec = next(
            (
                spec
                for spec in proposal.initialization.result_specs
                if spec.result.result_id == work_item.result_id
            ),
            None,
        )
        if result_spec is None and work_item.result_id is not None:
            result_spec = self._result_spec_for(ledger, request.run_id, work_item.result_id)
        trial_id = work_item.trial_id
        if trial_id is None and work_item.result_id is not None:
            trial_id = next(
                (
                    spec.result.trial_id
                    for spec in proposal.initialization.result_specs
                    if spec.result.result_id == work_item.result_id
                ),
                next(
                    (
                        candidate.trial_id
                        for candidate in proposal.result_candidates
                        if candidate.result_id == work_item.result_id
                    ),
                    None,
                ),
            )
        trial = next(
            (item for item in proposal.initialization.trials if item.trial_id == trial_id),
            proposal.initialization.trials[0]
            if proposal.initialization.trials
            else None,
        )
        scoped_trial_id = trial.trial_id if trial is not None else trial_id
        sources = (
            tuple(trial.inventory.sources)
            if trial is not None
            else tuple(
                source
                for item in proposal.initialization.trials
                if item.status == "inventory_ready"
                for source in item.inventory.sources
            )
        )
        context = WorkContext(
            work_item=work_item,
            trial=trial,
            result_spec=result_spec,
            sources=sources,
            registry_candidates=tuple(
                candidate
                for candidate in proposal.registry_candidates
                if scoped_trial_id is None or candidate.trial_id == scoped_trial_id
            ),
            result_candidates=tuple(
                candidate
                for candidate in proposal.result_candidates
                if scoped_trial_id is None or candidate.trial_id == scoped_trial_id
            ),
        )
        return GetWorkContextResponse(
            operation_id=self._read_operation_id(RunOperation.GET_WORK_CONTEXT, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.run_id,),
            condition=(
                WorkflowCondition.CONFIRMATION_REQUIRED
                if projection.run_state is RunState.AWAITING_CONFIRMATION
                else WorkflowCondition.AGENT_WORK_REQUIRED
            ),
            committed=False,
            run_id=request.run_id,
            run_state=projection.run_state,
            work_item=work_item,
            context=context,
        )

    def submit_run_proposal(self, request: SubmitRunProposalRequest) -> SubmitRunProposalResponse:
        ledger = self._bound_ledger(request.run_id)
        projection = self._projection(ledger, request.run_id)
        if projection.run_state is not RunState.AWAITING_CONFIRMATION:
            raise ValueError("a Run proposal can only be submitted before confirmation")
        existing_event = self._event_for_operation_key(ledger, request.idempotency_key)
        if (
            existing_event is not None
            and existing_event.operation == "operation:run-proposal-submitted"
        ):
            existing_record = _ProposalSubmittedRecord.model_validate_json(
                ledger.artifacts.read(existing_event.output_revision_hashes[0])
            )
            requested_ambiguities = request.ambiguities + request.unresolved_ambiguities
            existing_ambiguities = {
                item.ambiguity_id: item for item in existing_record.proposal.ambiguities
            }
            if (
                existing_record.proposal.selections != request.selections
                or any(
                    existing_ambiguities.get(item.ambiguity_id) != item
                    for item in requested_ambiguities
                )
            ):
                raise ValueError("idempotency key was already used with a different payload")
            return SubmitRunProposalResponse(
                operation_id=existing_event.operation_id,
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.CONFIRMATION_REQUIRED,
                committed=False,
                next_permitted_action=RunOperation.CONFIRM_RUN_DEFINITION,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=existing_record.proposal,
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        if request.proposal_token != proposal.proposal_token:
            historical = self._proposal_for_token(ledger, request.run_id, request.proposal_token)
            if historical is not None:
                return SubmitRunProposalResponse(
                    operation_id=self._read_operation_id(
                        RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                    ),
                    ledger_cursor=f"ledger:{len(ledger.events())}",
                    affected_scope=(request.run_id,),
                    condition=WorkflowCondition.STALE,
                    committed=False,
                    next_permitted_action=RunOperation.PREPARE_RUN,
                    run_id=request.run_id,
                    run_state=projection.run_state,
                    proposal=historical,
                    error=OperationError(
                        code="stale_proposal",
                        detail="A newer Run proposal has superseded this proposal token.",
                        recovery=(
                            "Discard the stale proposal and call prepare_run again.",
                        ),
                    ),
                )
            raise ValueError("Run proposal token is stale or was not issued by this Run")
        if self._input_snapshot_hash(self._required_root()) != proposal.input_snapshot_hash:
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.STALE,
                committed=False,
                next_permitted_action=RunOperation.PREPARE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=proposal,
                error=OperationError(
                    code="stale_proposal",
                    detail="Project inputs changed after this Run proposal was issued.",
                    recovery=(
                        "Discard the stale proposal and call prepare_run again.",
                        "Review the newly issued Trial, Source, registry, and Result candidates.",
                    ),
                ),
            )
        self._validate_proposal_selections(proposal, request.selections)
        proposal = self._refresh_registry_candidates(proposal, request.selections)
        requested_ambiguities = request.ambiguities + request.unresolved_ambiguities
        self._validate_proposal_ambiguities(proposal, requested_ambiguities)
        submitted = proposal.model_copy(
            update={
                "selections": request.selections,
                "ambiguities": self._merge_ambiguities(
                    proposal.ambiguities,
                    requested_ambiguities,
                    selections=request.selections,
                ),
            }
        )
        submitted = self._resolve_result_candidates(submitted, request.selections)
        submitted = self._freeze_submitted_proposal(submitted)
        record = _ProposalSubmittedRecord(run_id=request.run_id, proposal=submitted)
        now = datetime.now(UTC)
        suffix = self._digest(request.idempotency_key)
        transition = self._transition(
            scope=request.run_id,
            operation="operation:run-proposal-submitted",
            operation_key=request.idempotency_key,
            entity_id=f"run-proposal-submission:{suffix}",
            revision_id=f"revision:run-proposal-submission-{suffix}",
            artifact=record,
            checkpoint="checkpoint:run-proposal-submitted",
            outcome=WorkflowEventOutcome.WORK_REQUIRED,
            observed_at=now,
        )
        self._validate_idempotent_event(
            ledger, request.idempotency_key, transition.operation, record
        )
        lease = self._acquire_lease(ledger, now)
        result = ledger.commit(transition, lease, now=now)
        return SubmitRunProposalResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.CONFIRMATION_REQUIRED,
            committed=not result.duplicate,
            next_permitted_action=RunOperation.CONFIRM_RUN_DEFINITION,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            proposal=submitted,
        )

    def confirm_run_definition(
        self, request: ConfirmRunDefinitionRequest
    ) -> ConfirmRunDefinitionResponse:
        ledger = self._bound_ledger(request.run_id)
        projection = self._projection(ledger, request.run_id)
        proposal = self._latest_proposal(ledger, request.run_id)
        if request.proposal_token != proposal.proposal_token:
            historical = self._proposal_for_token(ledger, request.run_id, request.proposal_token)
            if historical is not None:
                return ConfirmRunDefinitionResponse(
                    operation_id=self._read_operation_id(
                        RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                    ),
                    ledger_cursor=f"ledger:{len(ledger.events())}",
                    affected_scope=(request.run_id,),
                    condition=WorkflowCondition.STALE,
                    committed=False,
                    next_permitted_action=RunOperation.PREPARE_RUN,
                    run_id=request.run_id,
                    run_state=projection.run_state,
                    run_definition=None,
                    error=OperationError(
                        code="stale_proposal",
                        detail="A newer Run proposal has superseded this proposal token.",
                        recovery=(
                            "Discard the stale proposal and call prepare_run again.",
                        ),
                    ),
                )
            raise ValueError("Run proposal token is stale or was not issued by this Run")
        existing = self._confirmed_for_idempotency(ledger, request.idempotency_key)
        if existing is not None:
            if existing.confirmed_by != request.confirmed_by:
                raise ValueError("idempotency key was already used with a different payload")
            existing_event = self._event_for_operation_key(ledger, request.idempotency_key)
            if existing_event is None:
                raise RuntimeError("confirmed idempotency record disappeared during replay")
            return ConfirmRunDefinitionResponse(
                operation_id=existing_event.operation_id,
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.AGENT_WORK_REQUIRED,
                committed=False,
                next_permitted_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=existing,
            )
        if projection.run_state is not RunState.AWAITING_CONFIRMATION:
            raise ValueError("the Run definition has already left confirmation")
        if self._input_snapshot_hash(self._required_root()) != proposal.input_snapshot_hash:
            return ConfirmRunDefinitionResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.STALE,
                committed=False,
                next_permitted_action=RunOperation.PREPARE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="stale_proposal",
                    detail="Project inputs changed after this Run proposal was issued.",
                    recovery=(
                        "Discard the stale proposal and call prepare_run again.",
                        "Review the newly issued Trial, Source, registry, and Result candidates.",
                    ),
                ),
            )
        if proposal.unresolved_ambiguities:
            return ConfirmRunDefinitionResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_permitted_action=RunOperation.SUBMIT_RUN_PROPOSAL,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="material_ambiguity",
                    detail="Material initialization ambiguities remain unresolved.",
                    recovery=(
                        "Resolve or explicitly remove each material ambiguity in the proposal.",
                        "Submit the resolved proposal before confirming the Run definition.",
                    ),
                ),
            )
        accepted = tuple(item for item in proposal.selections if item.accepted)
        addressed_registry_ids = {
            item.registry_candidate_id
            for item in proposal.selections
            if item.registry_candidate_id is not None
        }
        unconfirmed_registry = tuple(
            item
            for item in proposal.registry_candidates
            if item.status in {"discovered", "fuzzy"}
            and item.candidate_id not in addressed_registry_ids
        )
        selected_registry = {
            item.registry_candidate_id: item
            for item in accepted
            if item.registry_candidate_id is not None
        }
        unfetched_selected_registry = tuple(
            candidate
            for candidate_id, candidate in {
                item.candidate_id: item for item in proposal.registry_candidates
            }.items()
            if candidate_id in selected_registry
            and selected_registry[candidate_id].accepted
            and candidate.status in {"discovered", "fuzzy"}
            and (
                candidate.acquisition_status is not RegistryAcquisitionStatus.ACQUIRED
                or candidate.raw_record_hash is None
                or candidate.projection is None
            )
        )
        if unconfirmed_registry or unfetched_selected_registry:
            return ConfirmRunDefinitionResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_permitted_action=RunOperation.SUBMIT_RUN_PROPOSAL,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="material_ambiguity",
                    detail=(
                        "Registry candidates require explicit confirmation and a fetched "
                        "record before the Run definition can be confirmed."
                    ),
                    recovery=(
                        "Select or explicitly reject each discovered registry candidate.",
                        "Only confirm a discovered candidate after its immutable registry "
                        "record is fetched and hashed.",
                    ),
                ),
            )
        trial_ids = (
            tuple(item.trial_id for item in accepted)
            if proposal.selections
            else proposal.trial_ids
        )
        result_candidates = {item.candidate_id: item for item in proposal.result_candidates}
        selected_candidate_items = tuple(
            result_candidates[item.result_candidate_id]
            for item in accepted
            if item.result_candidate_id is not None
        )
        if any(
            item.status != "resolved" or item.result_id is None
            for item in selected_candidate_items
        ):
            return ConfirmRunDefinitionResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_permitted_action=RunOperation.SUBMIT_RUN_PROPOSAL,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="material_ambiguity",
                    detail="The selected Result candidate does not identify an exact ResultSpec.",
                    recovery=(
                        "Submit an exact Trial-specific Result mapping for the candidate.",
                    ),
                ),
            )
        selected_result_ids = tuple(
            dict.fromkeys(item.result_id for item in accepted if item.result_id is not None)
        )
        selected_result_ids += tuple(
            item.result_id
            for item in selected_candidate_items
            if item.result_id is not None and item.result_id not in selected_result_ids
        )
        result_ids = selected_result_ids if proposal.selections else proposal.result_ids
        selected_registry_candidate_ids = tuple(
            item.registry_candidate_id
            for item in accepted
            if item.registry_candidate_id is not None
        )
        registry_candidate_ids = (
            selected_registry_candidate_ids
            if proposal.selections
            else tuple(item.candidate_id for item in proposal.registry_candidates if item.explicit)
        )
        selected_outcome_target_ids = tuple(
            item.outcome_target_id
            for item in accepted
            if item.outcome_target_id is not None
        )
        selected_outcome_target_ids += tuple(
            item.outcome_target_id
            for item in selected_candidate_items
            if item.outcome_target_id is not None
            and item.outcome_target_id not in selected_outcome_target_ids
        )
        outcome_target_ids = (
            selected_outcome_target_ids
            if proposal.selections
            else tuple(
                item.target_id
                for item in proposal.initialization.manifest.outcome_target_specs
            )
        )
        now = datetime.now(UTC)
        definition = ConfirmedRunDefinition(
            run_id=request.run_id,
            proposal_id=proposal.proposal_id,
            proposal_token=proposal.proposal_token,
            supported_scope=proposal.supported_scope,
            trial_ids=trial_ids,
            result_ids=result_ids,
            confirmed_by=request.confirmed_by,
            confirmed_at=now,
            registry_candidate_ids=registry_candidate_ids,
            outcome_target_ids=outcome_target_ids,
        )
        record = _ConfirmedRunRecord(
            run_id=request.run_id,
            run_definition=definition,
        )
        suffix = self._digest(request.idempotency_key)
        transition = self._transition(
            scope=request.run_id,
            operation="operation:run-confirmed",
            operation_key=request.idempotency_key,
            entity_id=f"run-confirmation:{suffix}",
            revision_id=f"revision:run-confirmation-{suffix}",
            artifact=record,
            checkpoint="checkpoint:run-confirmed",
            outcome=WorkflowEventOutcome.WORK_REQUIRED,
            observed_at=now,
        )
        self._validate_idempotent_event(
            ledger, request.idempotency_key, transition.operation, record
        )
        lease = self._acquire_lease(ledger, now)
        result = ledger.commit(transition, lease, now=now)
        return ConfirmRunDefinitionResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.AGENT_WORK_REQUIRED,
            committed=not result.duplicate,
            next_permitted_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            run_definition=definition,
        )

    def search_evidence(self, request: SearchEvidenceRequest) -> SearchEvidenceResponse:
        ledger = self._bound_ledger(request.run_id)
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        page = index.search(
            request.query,
            cursor=request.cursor,
            broad_query_justification=request.broad_query_justification,
        )
        return SearchEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.SEARCH_EVIDENCE, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id or request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            page=page,
        )

    def read_evidence(self, request: ReadEvidenceRequest) -> ReadEvidenceResponse:
        ledger = self._bound_ledger(request.run_id)
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        unit = index.read_unit(request.unit_id)
        return ReadEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.READ_EVIDENCE, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id or request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            unit=unit,
        )

    def inspect_visual_candidate(
        self, request: InspectVisualCandidateRequest
    ) -> InspectVisualCandidateResponse:
        ledger = self._bound_ledger(request.run_id)
        candidate = next(
            (
                candidate
                for candidate in self._visual_candidates(ledger, request.run_id)
                if candidate.candidate_id == request.candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("Visual candidate identifier was not issued by this Run")
        return InspectVisualCandidateResponse(
            operation_id=self._read_operation_id(
                RunOperation.INSPECT_VISUAL_CANDIDATE, request.run_id
            ),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id or request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            candidate=candidate,
            render=VisualInspectionPolicy().initial_request(candidate),
        )

    def submit_source_classification(
        self, request: SubmitSourceClassificationRequest
    ) -> SubmitSourceClassificationResponse:
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_SOURCE_CLASSIFICATION,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitSourceClassificationResponse(
                **self._stale_submission_kwargs(
                    error, RunOperation.SUBMIT_SOURCE_CLASSIFICATION, ledger
                )
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        issued_sources = {
            source.source_id
            for trial in proposal.initialization.trials
            if trial.status == "inventory_ready"
            for source in trial.inventory.sources
        }
        submitted_sources = {item.source_id for item in request.classifications}
        if not submitted_sources <= issued_sources:
            raise ValueError("Source classification includes an unissued source identifier")
        result = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.run_id,
            operation="operation:submit-source-classification",
            operation_key=request.idempotency_key,
            artifact=request,
            checkpoint="checkpoint:source-classification",
        )
        projection = self._projection(ledger, request.run_id)
        return SubmitSourceClassificationResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=not result.duplicate,
            next_permitted_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
        )

    def submit_result_resolution(
        self, request: SubmitResultResolutionRequest
    ) -> SubmitResultResolutionResponse:
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_RESULT_RESOLUTION,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitResultResolutionResponse(
                **self._stale_submission_kwargs(
                    error,
                    RunOperation.SUBMIT_RESULT_RESOLUTION,
                    ledger,
                    result_id=request.result.result_id,
                )
            )
        expected = self._next_work_item(ledger, request.run_id)
        if (
            expected is not None
            and expected.operation is RunOperation.SUBMIT_RESULT_RESOLUTION
            and expected.result_id is not None
            and (
                request.result.result_id != expected.result_id
                or request.result.trial_id != expected.trial_id
            )
        ):
            stale = StaleWorkTokenError(request.run_id, expected)
            return SubmitResultResolutionResponse(
                **self._stale_submission_kwargs(
                    stale,
                    RunOperation.SUBMIT_RESULT_RESOLUTION,
                    ledger,
                    result_id=request.result.result_id,
                )
            )
        if (
            expected is not None
            and expected.operation is RunOperation.SUBMIT_RESULT_RESOLUTION
            and expected.result_id is None
            and expected.trial_id is not None
            and request.result.trial_id != expected.trial_id
        ):
            stale = StaleWorkTokenError(request.run_id, expected)
            return SubmitResultResolutionResponse(
                **self._stale_submission_kwargs(
                    stale,
                    RunOperation.SUBMIT_RESULT_RESOLUTION,
                    ledger,
                    result_id=request.result.result_id,
                )
            )
        existing_spec = self._result_spec_for(ledger, request.run_id, request.result.result_id)
        if existing_spec is not None and existing_spec.result.trial_id != request.result.trial_id:
            stale = StaleWorkTokenError(request.run_id, expected)
            return SubmitResultResolutionResponse(
                **self._stale_submission_kwargs(
                    stale,
                    RunOperation.SUBMIT_RESULT_RESOLUTION,
                    ledger,
                    result_id=request.result.result_id,
                )
            )
        existing = self._event_for_operation_key(ledger, request.idempotency_key)
        suffix = self._digest(request.idempotency_key)
        if existing is not None:
            if existing.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
            }:
                raise ValueError("idempotency key was already used for another operation")
            record = _ResultResolutionRecord.model_validate_json(
                ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            result_spec = record.result_spec
            if (
                result_spec.result != request.result
                or result_spec.estimate != request.estimate
                or result_spec.provenance_note != request.provenance_note
            ):
                raise ValueError("idempotency key was already used with a different payload")
            now = result_spec.observed_at
            operation = existing.operation
        else:
            now = datetime.now(UTC)
            result_spec = ResultSpecRevision(
                entity_id=f"result-spec:{suffix}",
                revision_id=f"revision:result-spec-{suffix}",
                actor=ENGINE_ACTOR,
                observed_at=now,
                result=request.result,
                estimate=request.estimate,
                provenance_note=request.provenance_note,
            )
            known_result_ids = {
                item.result_id for item in self._projection(ledger, request.run_id).results
            }
            operation = (
                "operation:submit-result-resolution"
                if request.result.result_id in known_result_ids
                else "operation:result-discovered"
            )
        committed = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result.result_id,
            operation=operation,
            operation_key=request.idempotency_key,
            artifact=_ResultResolutionRecord(
                run_id=request.run_id,
                result_id=request.result.result_id,
                result_spec=result_spec,
            ),
            checkpoint="checkpoint:result-resolution",
            observed_at=now,
            idempotency_validated=True,
        )
        projection = self._projection(ledger, request.run_id)
        return SubmitResultResolutionResponse(
            operation_id=committed.operation_id,
            ledger_cursor=f"ledger:{committed.sequence}",
            affected_scope=(request.result.result_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=not committed.duplicate,
            next_permitted_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result.result_id,
            result_state=self._result_state(projection, request.result.result_id),
            result_spec=result_spec,
        )

    def submit_domain_evidence(
        self, request: SubmitDomainEvidenceRequest
    ) -> SubmitDomainEvidenceResponse:
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_DOMAIN_EVIDENCE,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitDomainEvidenceResponse(
                **self._stale_submission_kwargs(
                    error,
                    RunOperation.SUBMIT_DOMAIN_EVIDENCE,
                    ledger,
                    result_id=request.result_id,
                    domain_id=request.domain_id,
                ),
                domain_id=request.domain_id,
            )
        expected = self._next_work_item(ledger, request.run_id)
        if (
            expected is not None
            and expected.operation is RunOperation.SUBMIT_DOMAIN_EVIDENCE
            and (expected.result_id != request.result_id or expected.domain_id != request.domain_id)
        ):
            stale = StaleWorkTokenError(request.run_id, expected)
            return SubmitDomainEvidenceResponse(
                **self._stale_submission_kwargs(
                    stale,
                    RunOperation.SUBMIT_DOMAIN_EVIDENCE,
                    ledger,
                    result_id=request.result_id,
                    domain_id=request.domain_id,
                ),
                domain_id=request.domain_id,
            )
        self._validate_result_domain(ledger, request.run_id, request.result_id, request.domain_id)
        normalized = _DomainEvidenceRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            items=tuple(item.revision_id for item in request.items),
            coverage_state=request.coverage_state.value,
            coverage_limitations=request.coverage_limitations,
            no_information_basis=request.no_information_basis,
            conflicts=request.conflicts,
        )
        result = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-domain-evidence",
            operation_key=request.idempotency_key,
            artifact=normalized,
            checkpoint=f"checkpoint:evidence-{request.domain_id.removeprefix('domain:')}",
        )
        projection = self._projection(ledger, request.run_id)
        return SubmitDomainEvidenceResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.result_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=not result.duplicate,
            next_permitted_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
        )

    def submit_domain_answers(
        self, request: SubmitDomainAnswersRequest
    ) -> SubmitDomainAnswersResponse:
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_DOMAIN_ANSWERS,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitDomainAnswersResponse(
                **self._stale_submission_kwargs(
                    error,
                    RunOperation.SUBMIT_DOMAIN_ANSWERS,
                    ledger,
                    result_id=request.result_id,
                    domain_id=request.domain_id,
                ),
                domain_id=request.domain_id,
            )
        expected = self._next_work_item(ledger, request.run_id)
        if (
            expected is not None
            and expected.operation is RunOperation.SUBMIT_DOMAIN_ANSWERS
            and (expected.result_id != request.result_id or expected.domain_id != request.domain_id)
        ):
            stale = StaleWorkTokenError(request.run_id, expected)
            return SubmitDomainAnswersResponse(
                **self._stale_submission_kwargs(
                    stale,
                    RunOperation.SUBMIT_DOMAIN_ANSWERS,
                    ledger,
                    result_id=request.result_id,
                    domain_id=request.domain_id,
                ),
                domain_id=request.domain_id,
            )
        self._validate_result_domain(ledger, request.run_id, request.result_id, request.domain_id)
        logic = self._logic_pack()
        domain = next(item for item in logic.domains if item.id == request.domain_id)
        question_ids = set(domain.question_ids)
        supplied = {item.question_id for item in request.answers}
        unknown = supplied - question_ids
        if unknown:
            raise ValueError(f"answers supplied for another domain: {sorted(unknown)}")
        if not self._has_domain_checkpoint(
            self._events_for_run(ledger, request.run_id),
            request.result_id,
            request.domain_id,
            "evidence",
        ):
            raise ValueError("domain evidence must be frozen before answers")
        normalized = _DomainAnswersRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            answers={item.question_id: item.answer.value for item in request.answers},
            rationales={item.question_id: item.rationale for item in request.answers},
            assessor_inputs=request.assessor_inputs,
        )
        result = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-domain-answers",
            operation_key=request.idempotency_key,
            artifact=normalized,
            checkpoint=f"checkpoint:answers-{request.domain_id.removeprefix('domain:')}",
        )
        self._materialize_terminal(ledger, request.run_id, request.result_id)
        projection = self._projection(ledger, request.run_id)
        return SubmitDomainAnswersResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.result_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=not result.duplicate,
            next_permitted_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
        )

    def _bind(self, root: Path) -> None:
        if self._root is not None and self._root != root:
            raise SecondProjectRootError(self._root, root)
        self._root = root

    def _registry(self, root: Path) -> Any:
        if self._registry_adapter is not None:
            return self._registry_adapter
        if self._registry_client is None:
            import httpx

            self._registry_client = ClinicalTrialsGovAdapter(
                client=httpx.Client(timeout=10.0, follow_redirects=False),
                artifacts=ArtifactStore(root / ".rob2" / "artifacts"),
                policy=RegistryPolicy(),
                clock=lambda: datetime.now(UTC),
            )
        return self._registry_client

    def _registry_for_prepare(self, root: Path, authorized: bool) -> Any | None:
        if not authorized:
            return None
        # Injected adapters are external acquisition capabilities too.  They
        # are useful for deterministic fixtures, but must not be invoked while
        # a caller is merely resuming a previously authorized project.
        if self._registry_adapter is not None:
            return self._registry_adapter
        return self._registry(root)

    def _refresh_registry_candidates(
        self,
        proposal: RunProposal,
        selections: tuple[RunProposalSelection, ...],
    ) -> RunProposal:
        """Fetch provenance for accepted discovered candidates before confirmation."""

        accepted_ids = {
            selection.registry_candidate_id
            for selection in selections
            if selection.accepted and selection.registry_candidate_id is not None
        }
        if not accepted_ids:
            return proposal
        adapter = self._registry_adapter or self._registry_client
        if adapter is None:
            return proposal
        candidates = {item.candidate_id: item for item in proposal.registry_candidates}
        changed = False
        for candidate_id in accepted_ids:
            candidate = candidates.get(candidate_id)
            if (
                candidate is None
                or candidate.status not in {"discovered", "fuzzy"}
                or candidate.nct_id is None
                or candidate.acquisition_status is RegistryAcquisitionStatus.ACQUIRED
            ):
                continue
            try:
                acquisition = adapter.acquire(
                    declared_nct_id=candidate.nct_id,
                    source_texts=(),
                )
            except Exception:
                continue
            candidates[candidate_id] = candidate.model_copy(
                update={
                    "nct_id": acquisition.resolution.nct_id or candidate.nct_id,
                    "acquisition_status": acquisition.status,
                    "raw_record_hash": acquisition.raw_record_hash,
                    "projection": acquisition.projection,
                }
            )
            changed = True
        if not changed:
            return proposal
        return proposal.model_copy(update={"registry_candidates": tuple(candidates.values())})

    @staticmethod
    def _validate_method_request(request: PrepareRunRequest) -> None:
        supported_scope = "rob2:individually-randomized-parallel"
        if request.supported_scope is not None and request.supported_scope != supported_scope:
            raise ValueError(
                "unsupported RoB 2 trial design request "
                f"{request.supported_scope!r}; supported scope is {supported_scope!r}"
            )
        if request.method is None:
            return
        normalized = request.method.casefold().replace("_", "-")
        accepted = {
            "rob2:individually-randomized-parallel",
            "individually-randomized-parallel",
            "rob2:2019-08-22",
            "2019-08-22",
        }
        if normalized not in accepted:
            raise ValueError(
                "unsupported RoB 2 method request "
                f"{request.method!r}; supported method is {supported_scope!r}"
            )

    def _acquire_lease(self, ledger: WorkflowLedger, now: datetime):
        """Reclaim a lease left by a stopped RunEngine process.

        RunEngine owners are process-scoped opaque IDs.  A new MCP process can
        therefore safely take over a prior RunEngine lease; unrelated writer
        owners (for example the review UI) remain protected by the ledger's
        normal lease conflict checks.
        """

        return ledger.acquire_lease(
            self._owner_id,
            now,
            timedelta(minutes=5),
            owner_is_dead=self._owner_is_dead,
        )

    @staticmethod
    def _owner_is_dead(owner: str) -> bool:
        """Return true only when a persisted RunEngine process is gone."""

        prefix = "owner:run-engine:"
        if not owner.startswith(prefix):
            return False
        pid_text = owner.removeprefix(prefix).split(":", 1)[0]
        try:
            pid = int(pid_text)
        except ValueError:
            # Owners written by an older pre-PID release cannot be proven
            # dead.  Wait for expiry rather than risking a live-writer steal.
            return False
        if os.name == "nt":
            # ``os.kill(pid, 0)`` maps to TerminateProcess on Windows rather
            # than a harmless liveness probe.  Query the process exit code via
            # the documented kernel API instead.
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                # ERROR_INVALID_PARAMETER means no such process.  Access
                # denied and all other API failures are indeterminate and
                # must not be treated as proof of death.
                return ctypes.get_last_error() == 87
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value != 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # The process exists but this user cannot inspect it.
            return False
        except OSError as error:
            return error.errno == errno.ESRCH
        return False

    def _index_initial_evidence(self, root: Path, initialization: ProjectInitialization) -> None:
        """Materialize canonical text units for a prepared Run."""

        parser = self._parser or LiteParseAdapter()
        artifacts = ArtifactStore(root / ".rob2" / "artifacts")
        units = []
        for trial in initialization.trials:
            for source in trial.inventory.sources:
                if source.artifact_hash is None or not source.parse_records:
                    continue
                parsed = parser.parse(artifacts.read(source.artifact_hash), ocr_enabled=False)
                pages = tuple(
                    CanonicalPage(
                        page=item.page_number,
                        blocks=(
                            CanonicalBlock(
                                kind=CanonicalUnitKind.PARAGRAPH,
                                text=item.text,
                                spatial=(0.0, 0.0, item.width, item.height),
                            ),
                        )
                        if item.text.strip()
                        else (),
                    )
                    for item in parsed.pages
                )
                units.extend(
                    canonicalize_evidence_units(
                        source_id=source.source_id,
                        source_artifact_hash=source.artifact_hash,
                        parse_id=source.parse_records[0].parse_id,
                        pages=pages,
                    )
                )
        EvidenceSearchIndex(root / ".rob2" / "evidence.sqlite3").replace_units(tuple(units))

    def _required_root(self) -> Path:
        if self._root is None:
            raise ValueError("prepare_run must bind a project root before other operations")
        return self._root

    def _bound_ledger(self, run_id: Identifier) -> WorkflowLedger:
        root = self._required_root()
        ledger = WorkflowLedger(
            root / ".rob2" / "ledger.sqlite3",
            ArtifactStore(root / ".rob2" / "artifacts"),
        )
        ledger.preflight()
        if not any(record.run_id == run_id for record in self._prepared_records(ledger)):
            raise ValueError("Run identifier was not issued for the bound project root")
        self._projection(ledger, run_id)
        return ledger

    def _validate_result_domain(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
    ) -> None:
        proposal = self._latest_proposal(ledger, run_id)
        if result_id not in self._result_ids(ledger, run_id, proposal):
            raise ValueError("Result identifier was not issued by this Run")
        if domain_id not in {domain.id for domain in self._logic_pack().domains}:
            raise ValueError("Domain identifier was not issued by the pinned Logic pack")

    def _repair_report_publication(self, ledger: WorkflowLedger, run_id: Identifier) -> None:
        """Publish committed report stages and finish a pending Run completion.

        Report transitions are write-ahead records: the final directory is
        published only after the ledger has accepted the immutable metadata.
        A process may therefore stop between those two steps; a later status,
        resume, or continue call repairs the hidden stage before exposing the
        terminal Run state.
        """

        events = self._events_for_run(ledger, run_id)
        reports: list[tuple[_ReportMaterializedRecord, Path]] = []
        for event in events:
            if event.operation != "operation:result-report-ready":
                continue
            try:
                record = _ReportMaterializedRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                )
            except (IndexError, ValueError):
                continue
            reports.append((record, self._required_root() / record.report_root))
        if not reports:
            self._commit_run_completed_if_ready(ledger, run_id)
            return

        missing: list[tuple[Path, Path]] = []
        for record, report_root in reports:
            if report_root.exists() or record.staging_root is None:
                continue
            staging = self._required_root() / record.staging_root
            if staging.exists():
                missing.append((staging, report_root))
        lease = None
        if missing:
            lease = self._acquire_lease(ledger, datetime.now(UTC))
            for staging, report_root in missing:
                if report_root.exists():
                    continue
                report_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, report_root)
        self._commit_run_completed_if_ready(ledger, run_id, lease=lease)

    def _commit_run_completed_if_ready(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        *,
        lease: LeaseToken | None = None,
    ) -> None:
        """Commit the terminal Run event only after every report is visible."""

        events = self._events_for_run(ledger, run_id)
        if any(event.operation == "operation:run-completed" for event in events):
            return
        proposal = self._latest_proposal(ledger, run_id)
        result_ids = self._result_ids(ledger, run_id, proposal)
        if not result_ids:
            return
        projection = self._projection(ledger, run_id)
        diagnostic_results = {
            item.result_id
            for item in projection.results
            if item.state is ResultState.DIAGNOSTIC_READY
        }
        report_records: list[_ReportMaterializedRecord] = []
        for result_id in result_ids:
            if result_id in diagnostic_results:
                continue
            report_event = next(
                (
                    event
                    for event in events
                    if event.operation == "operation:result-report-ready"
                    and event.scope == result_id
                ),
                None,
            )
            if report_event is None:
                return
            try:
                record = _ReportMaterializedRecord.model_validate_json(
                    ledger.artifacts.read(report_event.output_revision_hashes[0])
                )
            except (IndexError, ValueError):
                return
            if not (self._required_root() / record.report_root).exists():
                return
            report_records.append(record)
        if not report_records and (
            len(diagnostic_results.intersection(result_ids)) != len(result_ids)
        ):
            return
        latest_result_id = (
            report_records[-1].result_id
            if report_records
            else next(iter(result_ids))
        )
        latest_assessment = (
            report_records[-1].assessment_revision_id
            if report_records
            else "assessment:none"
        )
        completion_digest = self._digest(f"{run_id}|run-completed")
        transition = self._transition(
            scope=run_id,
            operation="operation:run-completed",
            operation_key=f"idempotency:run-completed-{completion_digest}",
            entity_id=f"run-completion:{completion_digest}",
            revision_id=f"revision:run-completion-{completion_digest}",
            artifact=_RunCompletedRecord(
                run_id=run_id,
                result_id=latest_result_id,
                assessment_revision_id=latest_assessment,
            ),
            checkpoint="checkpoint:run-completed",
            outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
            observed_at=datetime.now(UTC),
        )
        active_lease = lease or self._acquire_lease(ledger, datetime.now(UTC))
        ledger.commit(transition, active_lease, now=datetime.now(UTC))

    def _materialize_terminal(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
    ) -> None:
        """Evaluate all five domains and publish a minimal static bundle once."""

        events = self._events_for_run(ledger, run_id)
        if any(
            event.operation == "operation:result-report-ready" and event.scope == result_id
            for event in events
        ):
            self._repair_report_publication(ledger, run_id)
            return
        logic = self._logic_pack()
        required_domains = {domain.id for domain in logic.domains}
        evidence_domains = {
            self._event_payload(ledger, event).get("domain_id")
            for event in events
            if event.operation == "operation:submit-domain-evidence" and event.scope == result_id
        }
        answer_payloads = [
            self._event_payload(ledger, event)
            for event in events
            if event.operation == "operation:submit-domain-answers" and event.scope == result_id
        ]
        answer_domains = {payload.get("domain_id") for payload in answer_payloads}
        if not required_domains <= evidence_domains or not required_domains <= answer_domains:
            return
        # A Result may only have one immutable answer checkpoint per domain.
        answers: dict[str, str] = {}
        rationales: dict[str, str] = {}
        assessor_inputs: dict[str, bool] = {}
        for payload in answer_payloads:
            raw_answers = payload.get("answers", {})
            if isinstance(raw_answers, dict):
                answers.update(cast(dict[str, str], raw_answers))
            raw_rationales = payload.get("rationales", {})
            if isinstance(raw_rationales, dict):
                rationales.update(cast(dict[str, str], raw_rationales))
            raw_inputs = payload.get("assessor_inputs", {})
            if isinstance(raw_inputs, dict):
                assessor_inputs.update(cast(dict[str, bool], raw_inputs))
        evaluation = LogicEvaluator(logic).evaluate(
            EvaluationRequest(answers=answers, assessor_inputs=assessor_inputs)
        )
        result_spec = self._result_spec_for(ledger, run_id, result_id)
        if result_spec is None:
            raise ValueError("a ResultSpec is required before terminal assessment")
        assessment_digest = self._digest(
            f"{run_id}|{result_id}|{json.dumps(answers, sort_keys=True)}|"
            f"{json.dumps(assessor_inputs, sort_keys=True)}"
        )
        assessment_revision_id = f"assessment:{assessment_digest}"
        assessment = AssessmentView(
            assessment_revision_id=assessment_revision_id,
            result_id=result_id,
            trial=result_spec.result.trial_id,
            comparison=(
                f"{result_spec.result.comparison.experimental_arm_id} vs "
                f"{result_spec.result.comparison.comparator_arm_id}"
            ),
            outcome=result_spec.result.outcome_construct,
            time_point=result_spec.result.time_point,
            effect_of_interest=result_spec.result.effect_of_interest,
            overall_judgment=evaluation.overall_judgment.value,
            domains=tuple(
                DomainView(
                    domain_id=domain.id,
                    label=domain.id,
                    judgment=evaluation.domain_judgments[domain.id].value,
                    rationale=(
                        "Deterministic Logic-pack evaluation; matched rules: "
                        + ", ".join(evaluation.matched_rule_ids)
                    ),
                )
                for domain in logic.domains
            ),
            signed_off=False,
        )
        projector = ReportProjector(assessment)
        lease = self._acquire_lease(ledger, datetime.now(UTC))
        report_base = self._required_root() / "output" / "report-bundle"
        report_root = report_base
        if report_root.exists():
            # Preserve an earlier immutable bundle when another Result reaches
            # a terminal checkpoint in the same project.
            report_root = report_base / assessment_revision_id.replace(":", "_")
        if report_root.exists():
            raise ValueError("the immutable report bundle already exists")
        staging = report_root.parent / f".report-bundle-staging-{assessment_digest}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        report_files: dict[str, bytes] = {
            "assessment.json": projector.json(),
            "assessment.html": projector.html(),
            "assessment.md": projector.markdown(),
            "answers.json": (
                json.dumps(
                    {
                        "answers": answers,
                        "rationales": rationales,
                        "assessor_inputs": assessor_inputs,
                        "active_question_ids": evaluation.active_question_ids,
                        "inactive_question_ids": evaluation.inactive_question_ids,
                        "matched_rule_ids": evaluation.matched_rule_ids,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            ),
        }
        manifest = {
            "assessment_revision_id": assessment_revision_id,
            "result_id": result_id,
            "overall_judgment": evaluation.overall_judgment.value,
            "domains": evaluation.domain_judgments,
            "files": {
                name: "sha256:" + hashlib.sha256(content).hexdigest()
                for name, content in report_files.items()
            },
        }
        report_files["manifest.json"] = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        for name, content in report_files.items():
            (staging / name).write_bytes(content)
        now = datetime.now(UTC)
        report_record = _ReportMaterializedRecord(
            run_id=run_id,
            result_id=result_id,
            assessment_revision_id=assessment_revision_id,
            overall_judgment=evaluation.overall_judgment,
            domain_judgments=evaluation.domain_judgments,
            report_root=report_root.relative_to(self._required_root()).as_posix(),
            artifact_names=tuple(sorted(report_files)),
            staging_root=staging.relative_to(self._required_root()).as_posix(),
        )
        result_started = _ResultStartedRecord(run_id=run_id, result_id=result_id)
        transitions = [
            self._transition(
                scope=result_id,
                operation="operation:result-started",
                operation_key=f"idempotency:result-started-{assessment_digest}",
                entity_id=f"result-started:{assessment_digest}",
                revision_id=f"revision:result-started-{assessment_digest}",
                artifact=result_started,
                checkpoint="checkpoint:result-started",
                outcome=WorkflowEventOutcome.COMPLETED,
                observed_at=now,
            ),
            self._transition(
                scope=result_id,
                operation="operation:result-report-ready",
                operation_key=f"idempotency:result-report-ready-{assessment_digest}",
                entity_id=f"report:{assessment_digest}",
                revision_id=f"revision:report-{assessment_digest}",
                artifact=report_record,
                checkpoint="checkpoint:report-ready",
                outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
                observed_at=now,
            ),
        ]
        ledger.commit_batch(tuple(transitions), lease, now=now)
        # The ledger is authoritative before the final directory is exposed.
        # If publication is interrupted, the committed staging path is
        # repaired by a later status/resume/continue call.
        os.replace(staging, report_root)
        self._commit_run_completed_if_ready(ledger, run_id, lease=lease)

    def _result_spec_for(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
    ) -> ResultSpecRevision | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
                "operation:run-register-result",
            }:
                continue
            try:
                if event.operation == "operation:run-register-result":
                    record = _ResultDiscoveredRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if record.result_id == result_id:
                        return record.result_spec
                else:
                    record = _ResultResolutionRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if record.result_id == result_id:
                        return record.result_spec
            except (ValueError, TypeError):
                continue
        return None

    def _submission_ledger(
        self,
        run_id: Identifier,
        work_token: WorkToken,
        expected_operation: RunOperation,
    ) -> WorkflowLedger:
        ledger = self._bound_ledger(run_id)
        # Before confirmation, the historical unit tests exercise the typed
        # idempotency record directly.  Once a Run is assessing, every write
        # must use the exact currently issued opaque token and dependency
        # fingerprint; this is the stale-work guard exposed to MCP callers.
        projection = self._projection(ledger, run_id)
        if work_token.run_id != run_id or work_token.operation is not expected_operation:
            expected = (
                self._next_work_item(ledger, run_id)
                if projection.run_state is RunState.ASSESSING
                else None
            )
            raise StaleWorkTokenError(run_id, expected)
        if projection.run_state is RunState.ASSESSING:
            expected = self._next_work_item(ledger, run_id)
            if expected is None or expected.work_token != work_token:
                raise StaleWorkTokenError(run_id, expected)
        return ledger

    def _stale_submission_kwargs(
        self,
        error: StaleWorkTokenError,
        operation: RunOperation,
        ledger: WorkflowLedger,
        *,
        result_id: Identifier | None = None,
        domain_id: Identifier | None = None,
    ) -> dict[str, Any]:
        projection = self._projection(ledger, error.run_id)
        expected = error.expected
        return {
            "operation_id": self._read_operation_id(operation, error.run_id),
            "ledger_cursor": f"ledger:{len(ledger.events())}",
            "affected_scope": tuple(
                item
                for item in (
                    result_id or (expected.result_id if expected else None) or error.run_id,
                    domain_id or (expected.domain_id if expected else None),
                )
                if item is not None
            ),
            "condition": WorkflowCondition.STALE,
            "committed": False,
            "next_permitted_action": expected.operation if expected else RunOperation.CONTINUE_RUN,
            "run_id": error.run_id,
            "run_state": projection.run_state,
            "result_id": result_id,
            "result_state": (
                self._result_state(projection, result_id) if result_id is not None else None
            ),
            "work_item": expected,
            "error": OperationError(
                code="stale_work",
                detail="The supplied WorkToken is stale or its payload scope does not match.",
                recovery=(
                    "Discard the stale submission and call continue_run for the current WorkItem.",
                    "Use the newly issued WorkToken and preserve its Result/domain scope.",
                ),
            ),
        }

    def _commit_submission(
        self,
        ledger: WorkflowLedger,
        *,
        run_id: Identifier,
        scope: Identifier,
        operation: Identifier,
        operation_key: Identifier,
        artifact: FrozenModel,
        checkpoint: Identifier,
        observed_at: datetime | None = None,
        idempotency_validated: bool = False,
    ) -> CommitResult:
        now = observed_at or datetime.now(UTC)
        suffix = self._digest(f"{run_id}|{operation_key}")
        transition = self._transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            entity_id=f"run-submission:{suffix}",
            revision_id=f"revision:run-submission-{suffix}",
            artifact=artifact,
            checkpoint=checkpoint,
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=now,
        )
        if not idempotency_validated:
            self._validate_idempotent_event(ledger, operation_key, operation, artifact)
        lease = self._acquire_lease(ledger, now)
        return ledger.commit(transition, lease, now=now)

    @staticmethod
    def _event_for_operation_key(
        ledger: WorkflowLedger, operation_key: Identifier
    ) -> WorkflowEvent | None:
        return next(
            (event for event in ledger.events() if event.operation_key == operation_key),
            None,
        )

    def _confirmed_for_idempotency(
        self, ledger: WorkflowLedger, operation_key: Identifier
    ) -> ConfirmedRunDefinition | None:
        event = self._event_for_operation_key(ledger, operation_key)
        if event is None or event.operation != "operation:run-confirmed":
            return None
        try:
            return _ConfirmedRunRecord.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            ).run_definition
        except (IndexError, ValueError):
            return None

    def _validate_idempotent_event(
        self,
        ledger: WorkflowLedger,
        operation_key: Identifier,
        operation: Identifier,
        artifact: FrozenModel,
    ) -> None:
        existing = self._event_for_operation_key(ledger, operation_key)
        if existing is None:
            return
        if existing.operation != operation:
            raise ValueError("idempotency key was already used for another operation")
        submitted = artifact.model_dump_json().encode()
        persisted = ledger.artifacts.read(existing.output_revision_hashes[0])
        if persisted != submitted:
            raise ValueError("idempotency key was already used with a different payload")

    @staticmethod
    def _freeze_submitted_proposal(proposal: RunProposal) -> RunProposal:
        """Issue a new immutable proposal identity for each accepted revision."""

        payload = proposal.model_dump(mode="json")
        payload.pop("proposal_id", None)
        payload.pop("proposal_token", None)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return proposal.model_copy(
            update={
                "proposal_id": f"run-proposal:{digest}",
                "proposal_token": f"proposal-token:{digest}",
            }
        )

    @staticmethod
    def _validate_proposal_selections(
        proposal: RunProposal,
        selections: tuple[RunProposalSelection, ...],
    ) -> None:
        issued_trials = set(proposal.trial_ids)
        issued_results = {
            item.result.result_id: item.result.trial_id
            for item in proposal.initialization.result_specs
        }
        issued_result_candidates = {
            item.candidate_id: item for item in proposal.result_candidates
        }
        issued_outcome_targets = {
            item.target_id for item in proposal.initialization.manifest.outcome_target_specs
        }
        seen: set[
            tuple[
                Identifier,
                Identifier | None,
                Identifier | None,
                Identifier | None,
                Identifier | None,
            ]
        ] = set()
        seen_result_candidates: set[Identifier] = set()
        seen_registry_candidates: set[Identifier] = set()
        for selection in selections:
            identity = (
                selection.trial_id,
                selection.result_id,
                selection.result_candidate_id,
                selection.registry_candidate_id,
                selection.outcome_target_id,
            )
            if identity in seen:
                raise ValueError("Run proposal contains a duplicate selection")
            seen.add(identity)
            if selection.trial_id not in issued_trials:
                raise ValueError("Run proposal selection was not issued by this Run")
            if selection.outcome_target_id is not None:
                if selection.outcome_target_id not in issued_outcome_targets:
                    raise ValueError("Run proposal Outcome target was not issued by this Run")
            if selection.registry_candidate_id is not None:
                if selection.registry_candidate_id in seen_registry_candidates:
                    raise ValueError(
                        "Run proposal contains a duplicate registry candidate selection"
                    )
                seen_registry_candidates.add(selection.registry_candidate_id)
                candidates = {
                    item.candidate_id: item for item in proposal.registry_candidates
                }
                candidate = candidates.get(selection.registry_candidate_id)
                if candidate is None:
                    raise ValueError(
                        "Run proposal registry candidate was not issued by this Run"
                    )
                if candidate.trial_id != selection.trial_id:
                    raise ValueError(
                        "Run proposal registry candidate was not issued for the selected Trial"
                    )
            if selection.result_candidate_id is not None:
                if selection.result_candidate_id in seen_result_candidates:
                    raise ValueError("Run proposal contains a duplicate Result candidate selection")
                seen_result_candidates.add(selection.result_candidate_id)
                result_candidate = issued_result_candidates.get(selection.result_candidate_id)
                if result_candidate is None:
                    raise ValueError("Run proposal Result candidate was not issued by this Run")
                if result_candidate.trial_id != selection.trial_id:
                    raise ValueError(
                        "Run proposal Result candidate was not issued for the selected Trial"
                    )
                if (
                    selection.result_id is not None
                    and result_candidate.result_id is not None
                    and result_candidate.result_id != selection.result_id
                ):
                    raise ValueError(
                        "Run proposal Result and candidate identify different Results"
                    )
                if (
                    selection.outcome_target_id is not None
                    and result_candidate.outcome_target_id != selection.outcome_target_id
                ):
                    raise ValueError(
                        "Run proposal Outcome target and Result candidate identify "
                        "different targets"
                    )
            if selection.result_id is None:
                if (
                    selection.result_candidate_id is not None
                    and issued_result_candidates[
                        selection.result_candidate_id
                    ].result_id
                    is not None
                ):
                    continue
                continue
            if (
                issued_results.get(selection.result_id) != selection.trial_id
                and not (
                    selection.result_candidate_id is not None
                    and issued_result_candidates[selection.result_candidate_id].status
                    == "needs_input"
                )
            ):
                raise ValueError("Run proposal Result was not issued for the selected Trial")
            if (
                selection.result_candidate_id is not None
                and issued_result_candidates[selection.result_candidate_id].status == "needs_input"
                and selection.result_id in issued_results
                and issued_results[selection.result_id] != selection.trial_id
            ):
                raise ValueError(
                    "Run proposal Result candidate cannot adopt a Result from another Trial"
                )
            if (
                selection.result_candidate_id is not None
                and issued_result_candidates[selection.result_candidate_id].status == "needs_input"
                and not selection.result_id.startswith("result:")
            ):
                raise ValueError("resolved Result candidate requires a result: identifier")
            if selection.result_id in issued_results and selection.outcome_target_id is not None:
                existing_target_ids = {
                    candidate.outcome_target_id
                    for candidate in issued_result_candidates.values()
                    if candidate.result_id == selection.result_id
                }
                if existing_target_ids and selection.outcome_target_id not in existing_target_ids:
                    raise ValueError(
                        "Run proposal Result is already mapped to a different Outcome target"
                    )
            if (
                selection.outcome_target_id is not None
                and not any(
                    candidate.result_id == selection.result_id
                    and candidate.outcome_target_id == selection.outcome_target_id
                    for candidate in issued_result_candidates.values()
                )
                and not (
                    selection.result_candidate_id is not None
                    and issued_result_candidates[selection.result_candidate_id].status
                    == "needs_input"
                )
            ):
                raise ValueError(
                    "Run proposal Result was not issued for the selected Outcome target"
                )

    @staticmethod
    def _validate_proposal_ambiguities(
        proposal: RunProposal,
        ambiguities: tuple[RunProposalAmbiguity, ...],
    ) -> None:
        issued = {item.ambiguity_id: item for item in proposal.ambiguities}
        allowed_scopes = set(proposal.trial_ids) | set(proposal.result_ids)
        allowed_scopes.update(item.candidate_id for item in proposal.result_candidates)
        allowed_scopes.update(item.candidate_id for item in proposal.registry_candidates)
        seen: set[Identifier] = set()
        for item in ambiguities:
            if item.ambiguity_id in seen:
                raise ValueError("Run proposal contains a duplicate ambiguity")
            seen.add(item.ambiguity_id)
            if item.ambiguity_id not in issued and item.scope not in allowed_scopes:
                raise ValueError(
                    "Run proposal ambiguity must reference an issued Trial, Result, or candidate"
                )
            if item.ambiguity_id in issued:
                original = issued[item.ambiguity_id]
                if item.scope != original.scope:
                    raise ValueError("Run proposal ambiguity scope does not match the issued item")
                if item.detail != original.detail:
                    raise ValueError("Run proposal ambiguity detail cannot be rewritten")
                if original.material and not item.material:
                    raise ValueError("material Run proposal ambiguities cannot be downgraded")
                if item.resolved and item.material and not (item.resolution or "").strip():
                    raise ValueError(
                        "a resolved material Run proposal ambiguity requires a resolution"
                    )
            elif item.resolved and item.material and not (item.resolution or "").strip():
                raise ValueError(
                    "a resolved material Run proposal ambiguity requires a resolution"
                )

    @staticmethod
    def _merge_ambiguities(
        issued: tuple[RunProposalAmbiguity, ...],
        updates: tuple[RunProposalAmbiguity, ...],
        *,
        selections: tuple[RunProposalSelection, ...] = (),
    ) -> tuple[RunProposalAmbiguity, ...]:
        by_id = {item.ambiguity_id: item for item in issued}
        by_id.update({item.ambiguity_id: item for item in updates})
        selected_registry = {
            selection.registry_candidate_id: selection
            for selection in selections
            if selection.registry_candidate_id is not None
        }
        if selected_registry:
            for ambiguity_id, ambiguity in by_id.items():
                selection = selected_registry.get(ambiguity.scope)
                if selection is None or not ambiguity.material:
                    continue
                by_id[ambiguity_id] = ambiguity.model_copy(
                    update={
                        "resolved": True,
                        "resolution": (
                            f"Selected registry candidate {ambiguity.scope}"
                            if selection.accepted
                            else f"Explicitly rejected registry candidate {ambiguity.scope}"
                        ),
                    }
                )
        return tuple(by_id[key] for key in by_id)

    @staticmethod
    def _resolve_result_candidates(
        proposal: RunProposal,
        selections: tuple[RunProposalSelection, ...],
    ) -> RunProposal:
        candidates = {item.candidate_id: item for item in proposal.result_candidates}
        ambiguities = {item.ambiguity_id: item for item in proposal.ambiguities}
        changed = False
        for selection in selections:
            if not selection.accepted or selection.result_candidate_id is None:
                continue
            candidate = candidates.get(selection.result_candidate_id)
            if (
                candidate is None
                or candidate.status != "needs_input"
                or selection.result_id is None
            ):
                continue
            candidates[candidate.candidate_id] = candidate.model_copy(
                update={"result_id": selection.result_id, "status": "resolved"}
            )
            for ambiguity_id, ambiguity in ambiguities.items():
                if ambiguity.scope == candidate.candidate_id and ambiguity.material:
                    ambiguities[ambiguity_id] = ambiguity.model_copy(
                        update={
                            "resolved": True,
                            "resolution": f"Resolved to {selection.result_id}",
                        }
                    )
            changed = True
        if not changed:
            return proposal
        result_ids = list(proposal.result_ids)
        for candidate in candidates.values():
            if candidate.result_id is not None and candidate.result_id not in result_ids:
                result_ids.append(candidate.result_id)
        return proposal.model_copy(
            update={
                "result_candidates": tuple(candidates.values()),
                "ambiguities": tuple(ambiguities.values()),
                "result_ids": tuple(result_ids),
            }
        )

    @staticmethod
    def _result_state(
        projection: LifecycleProjection,
        result_id: Identifier,
    ) -> ResultState:
        return next(
            (item.state for item in projection.results if item.result_id == result_id),
            ResultState.PENDING,
        )

    def _next_work_item(self, ledger: WorkflowLedger, run_id: Identifier) -> WorkItem | None:
        """Derive the next bounded submission from committed checkpoints."""

        projection = self._projection(ledger, run_id)
        if projection.run_state is not RunState.ASSESSING:
            return None
        proposal = self._latest_proposal(ledger, run_id)
        events = self._events_for_run(ledger, run_id)
        if not any(event.operation == "operation:run-confirmed" for event in events):
            return None
        if (
            any(trial.status == "inventory_ready" for trial in proposal.initialization.trials)
            and not any(
                event.operation == "operation:submit-source-classification"
                for event in events
            )
        ):
            return self._work_item(run_id, "sources", RunOperation.SUBMIT_SOURCE_CLASSIFICATION)
        if not proposal.initialization.trials:
            return None

        all_result_ids = self._result_ids(ledger, run_id, proposal)
        failed_result_ids = self._failed_result_ids(proposal)
        unresolved_trial = self._unresolved_trial_id(proposal, ledger, events)
        if unresolved_trial is not None:
            return self._work_item(
                run_id,
                f"result:unresolved:{unresolved_trial.removeprefix('trial:')}",
                RunOperation.SUBMIT_RESULT_RESOLUTION,
                trial_id=unresolved_trial,
            )
        result_ids = tuple(
            result_id for result_id in all_result_ids if result_id not in failed_result_ids
        )
        if not result_ids and all_result_ids:
            return None
        if not result_ids:
            return None
        # Every Result without an exact immutable ResultSpec receives its own
        # resolution checkpoint.  This remains true for mixed Runs where one
        # declared Result shares a batch with newly mapped candidates.
        unresolved = next(
            (
                result_id
                for result_id in result_ids
                if not any(
                    spec.result.result_id == result_id
                    for spec in proposal.initialization.result_specs
                )
                and not self._has_result_resolution(events, result_id)
            ),
            None,
        )
        if unresolved is not None:
            return self._work_item(
                run_id,
                f"result:{unresolved.removeprefix('result:')}",
                RunOperation.SUBMIT_RESULT_RESOLUTION,
                result_id=unresolved,
            )

        logic = self._logic_pack()
        for result_id in result_ids:
            for domain in logic.domains:
                domain_id = domain.id
                if not self._has_domain_checkpoint(events, result_id, domain_id, "evidence"):
                    return self._work_item(
                        run_id,
                        f"{result_id}|{domain_id}|evidence",
                        RunOperation.SUBMIT_DOMAIN_EVIDENCE,
                        result_id=result_id,
                        domain_id=domain_id,
                    )
                if not self._has_domain_checkpoint(events, result_id, domain_id, "answers"):
                    return self._work_item(
                        run_id,
                        f"{result_id}|{domain_id}|answers",
                        RunOperation.SUBMIT_DOMAIN_ANSWERS,
                        result_id=result_id,
                        domain_id=domain_id,
                    )
        return None

    def _work_item(
        self,
        run_id: Identifier,
        key: str,
        operation: RunOperation,
        *,
        result_id: Identifier | None = None,
        domain_id: Identifier | None = None,
        trial_id: Identifier | None = None,
    ) -> WorkItem:
        digest = self._digest(f"{run_id}|{key}|{operation.value}")
        work_item_id = f"work-item:{digest}"
        scoped_trial_id = trial_id or self._trial_id_for_result(result_id)
        token = WorkToken(
            token=f"work-token:{digest}",
            run_id=run_id,
            work_item_id=work_item_id,
            operation=operation,
            dependency_fingerprint=(
                "sha256:"
                + hashlib.sha256(f"{run_id}|{key}|{operation.value}".encode()).hexdigest()
            ),
            trial_id=scoped_trial_id,
            result_id=result_id,
            domain_id=domain_id,
        )
        return WorkItem(
            work_item_id=work_item_id,
            work_token=token,
            operation=operation,
            result_id=result_id,
            domain_id=domain_id,
            trial_id=scoped_trial_id,
            dependency_fingerprint=token.dependency_fingerprint,
        )

    def _unresolved_trial_id(
        self,
        proposal: RunProposal,
        ledger: WorkflowLedger,
        events: tuple[WorkflowEvent, ...],
    ) -> Identifier | None:
        failed_trials = {
            trial.trial_id
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed"
        }
        resolved_trials = {
            spec.result.trial_id for spec in proposal.initialization.result_specs
        }
        for event in events:
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
            }:
                continue
            payload = self._event_payload(ledger, event)
            raw_spec = payload.get("result_spec")
            if not isinstance(raw_spec, dict):
                continue
            raw_result = raw_spec.get("result")
            if isinstance(raw_result, dict):
                trial_id = raw_result.get("trial_id")
                if isinstance(trial_id, str):
                    resolved_trials.add(trial_id)
        return next(
            (
                trial.trial_id
                for trial in proposal.initialization.trials
                if trial.status == "inventory_ready"
                and trial.trial_id not in failed_trials
                and trial.trial_id not in resolved_trials
            ),
            None,
        )

    @staticmethod
    def _has_result_resolution(events: tuple[WorkflowEvent, ...], result_id: Identifier) -> bool:
        return any(
            event.operation in {"operation:result-discovered", "operation:submit-result-resolution"}
            and event.scope == result_id
            for event in events
        )

    @staticmethod
    def _has_domain_checkpoint(
        events: tuple[WorkflowEvent, ...],
        result_id: Identifier,
        domain_id: Identifier,
        kind: str,
    ) -> bool:
        operation = f"operation:submit-domain-{kind}"
        return any(
            event.operation == operation
            and event.scope == result_id
            and event.checkpoint == f"checkpoint:{kind}-{domain_id.removeprefix('domain:')}"
            for event in events
        )

    def _result_ids(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal: RunProposal,
    ) -> tuple[Identifier, ...]:
        ids = list(proposal.result_ids)
        for event in self._events_for_run(ledger, run_id):
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
            }:
                continue
            payload = self._event_payload(ledger, event)
            result_id = payload.get("result_id")
            if isinstance(result_id, str) and result_id not in ids:
                ids.append(result_id)
        return tuple(ids)

    def _trial_id_for_result(self, result_id: Identifier | None) -> Identifier | None:
        if result_id is None or self._root is None:
            return None
        try:
            ledger = WorkflowLedger(
                self._root / ".rob2" / "ledger.sqlite3",
                ArtifactStore(self._root / ".rob2" / "artifacts"),
            )
            current = self._current_prepared_record(ledger)
            if current is None:
                return None
            proposal = self._latest_proposal(ledger, current.run_id)
            result_trial = next(
                (
                    spec.result.trial_id
                    for spec in proposal.initialization.result_specs
                    if spec.result.result_id == result_id
                ),
                None,
            )
            if result_trial is not None:
                return result_trial
            return next(
                (
                    candidate.trial_id
                    for candidate in proposal.result_candidates
                    if candidate.result_id == result_id
                ),
                None,
            )
        except (StopIteration, AttributeError, ValueError):
            return None

    def _logic_pack(self):
        return load_logic_pack(self._logic_pack_path())

    @staticmethod
    def _logic_pack_path() -> Path:
        candidates = (
            Path(__file__).resolve().parents[1]
            / "packs"
            / "logic"
            / "rob2-parallel-assignment-2019.1.yaml",
            Path(__file__).resolve().parents[3]
            / "packs"
            / "logic"
            / "rob2-parallel-assignment-2019.1.yaml",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise FileNotFoundError("the pinned RoB 2 Logic pack is not installed")

    def _visual_candidates(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
    ) -> tuple[VisualCandidate, ...]:
        candidates: dict[str, VisualCandidate] = {}
        for event in ledger.events():
            payload = self._event_payload(ledger, event)
            if payload.get("run_id") not in {None, run_id}:
                continue
            raw_candidates = payload.get("visual_candidates", ())
            if not isinstance(raw_candidates, (list, tuple)):
                continue
            for item in raw_candidates:
                candidate = VisualCandidate.model_validate(item)
                candidates[candidate.candidate_id] = candidate
        return tuple(candidates[key] for key in sorted(candidates))

    def _projection(self, ledger: WorkflowLedger, run_id: Identifier) -> LifecycleProjection:
        return derive_lifecycle(self._events_for_run(ledger, run_id))

    def _events_for_run(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> tuple[WorkflowEvent, ...]:
        selected = []
        for event in ledger.events():
            if event.scope == run_id:
                selected.append(event)
                continue
            payload = self._event_payload(ledger, event)
            if payload.get("run_id") == run_id:
                selected.append(event)
        return tuple(selected)

    def _current_prepared_record(self, ledger: WorkflowLedger) -> _PreparedRunRecord | None:
        records = self._unfinished_prepared_records(ledger)
        return records[-1] if records else None

    def _unfinished_prepared_records(
        self, ledger: WorkflowLedger
    ) -> tuple[_PreparedRunRecord, ...]:
        return tuple(
            record
            for record in self._prepared_records(ledger)
            if self._projection(ledger, record.run_id).run_state
            not in {RunState.COMPLETE, RunState.RETIRED}
        )

    def _latest_prepared_record(self, ledger: WorkflowLedger) -> _PreparedRunRecord | None:
        records = self._prepared_records(ledger)
        return records[-1] if records else None

    def _prepared_records(self, ledger: WorkflowLedger) -> tuple[_PreparedRunRecord, ...]:
        return tuple(
            _PreparedRunRecord.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            )
            for event in ledger.events()
            if event.operation == "operation:run-prepared"
        )

    def _latest_proposal(self, ledger: WorkflowLedger, run_id: Identifier) -> RunProposal:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation == "operation:run-proposal-submitted":
                return _ProposalSubmittedRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).proposal
            if event.operation == "operation:run-prepared":
                return _PreparedRunRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).proposal
        raise ValueError("Run has no durable proposal")

    def _proposal_for_token(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal_token: Identifier,
    ) -> RunProposal | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation == "operation:run-proposal-submitted":
                proposal = _ProposalSubmittedRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).proposal
            elif event.operation == "operation:run-prepared":
                proposal = _PreparedRunRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).proposal
            else:
                continue
            if proposal.proposal_token == proposal_token:
                return proposal
        return None

    @staticmethod
    def _failed_result_ids(proposal: RunProposal) -> frozenset[Identifier]:
        failed_trials = {
            trial.trial_id
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed"
        }
        return frozenset(
            spec.result.result_id
            for spec in proposal.initialization.result_specs
            if spec.result.trial_id in failed_trials
        )

    def _proposal(
        self,
        run_id: Identifier,
        initialization: ProjectInitialization,
    ) -> RunProposal:
        # Proposal validity is bound to durable input bytes and declarations,
        # not volatile parser timestamps or network retrieval times.
        snapshot_hash = self._input_snapshot_hash(self._required_root())
        suffix = self._digest(f"{run_id}|{snapshot_hash}")
        non_material_findings = {
            "optional_source_acquisition_failed",
            "optional_source_processing_failed",
            "registry_unavailable",
            "registry_acquisition_failed",
            "registry_candidates",
            "trial_failed",
        }
        finding_ambiguities = tuple(
            RunProposalAmbiguity(
                ambiguity_id=(
                    f"ambiguity:{self._digest(f'{run_id}|{index}|{finding.kind.value}|{finding.detail}')}"
                ),
                scope=finding.source_id or finding.trial_id,
                detail=finding.detail,
                material=finding.kind.value not in non_material_findings,
            )
            for index, finding in enumerate(initialization.review_findings)
        )
        registry_ambiguities = tuple(
            RunProposalAmbiguity(
                ambiguity_id=(
                    f"ambiguity:{self._digest(f'{run_id}|registry-candidate|{candidate.candidate_id}')}"
                ),
                scope=candidate.candidate_id,
                detail=(
                    f"Registry candidate {candidate.nct_id or 'unavailable'} "
                    f"for {candidate.trial_id} requires explicit confirmation."
                ),
                material=True,
            )
            for candidate in initialization.registry_candidates
            if candidate.status in {"discovered", "fuzzy"}
        )
        result_ambiguities = tuple(
            RunProposalAmbiguity(
                ambiguity_id=(
                    f"ambiguity:{self._digest(f'{run_id}|result-candidate|{candidate.candidate_id}')}"
                ),
                scope=candidate.candidate_id,
                detail=(
                    f"Result candidate {candidate.label!r} for {candidate.trial_id} "
                    "requires an exact Trial-specific Result mapping."
                ),
                material=True,
            )
            for candidate in initialization.result_candidates
            if candidate.status == "needs_input"
        )
        ambiguities = finding_ambiguities + registry_ambiguities + result_ambiguities
        return RunProposal(
            proposal_id=f"run-proposal:{suffix}",
            proposal_token=f"proposal-token:{suffix}",
            run_id=run_id,
            supported_scope=initialization.manifest.supported_scope,
            trial_ids=tuple(item.trial_id for item in initialization.trials),
            result_ids=tuple(item.result.result_id for item in initialization.result_specs),
            input_snapshot_hash=snapshot_hash,
            initialization=initialization,
            registry_candidates=initialization.registry_candidates,
            result_candidates=initialization.result_candidates,
            ambiguities=ambiguities,
        )

    @staticmethod
    def _input_snapshot_hash(root: Path) -> str:
        """Hash the confined project inputs while excluding derived state."""

        entries: list[tuple[str, str]] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                resolved = path.resolve()
                raise ValueError(
                    f"project input symlinks are not permitted: {path} -> {resolved}"
                )
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"project input escapes project root: {path}")
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] in {".rob2", "output", "__pycache__"}:
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                raise ValueError(f"unable to snapshot project input {relative}") from error
            entries.append((relative.as_posix(), digest))
        return "sha256:" + hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _new_run_id(self, root: Path, event_count: int) -> Identifier:
        return f"run:{self._digest(f'{root}|{event_count}')}"

    def _transition(
        self,
        *,
        scope: Identifier,
        operation: Identifier,
        operation_key: Identifier,
        entity_id: Identifier,
        revision_id: Identifier,
        artifact: FrozenModel,
        checkpoint: Identifier,
        outcome: WorkflowEventOutcome,
        observed_at: datetime,
    ) -> Transition:
        return Transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            actor=ENGINE_ACTOR,
            observed_at=observed_at,
            entity_id=entity_id,
            revision_id=revision_id,
            artifact=artifact.model_dump_json().encode(),
            artifact_media_type="application/json",
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint=checkpoint,
            outcome=outcome,
        )

    def _continue_response(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        projection: LifecycleProjection,
        directive: RunDirective,
        *,
        committed: bool,
        operation_id: Identifier | None = None,
        work_item: WorkItem | None = None,
    ) -> ContinueRunResponse:
        return ContinueRunResponse(
            operation_id=operation_id or self._read_operation_id(RunOperation.CONTINUE_RUN, run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(run_id,),
            condition=WorkflowCondition(directive.value),
            committed=committed,
            next_permitted_action=(
                RunOperation.SUBMIT_RUN_PROPOSAL
                if directive is RunDirective.CONFIRMATION_REQUIRED
                else work_item.operation
                if work_item is not None
                else None
            ),
            run_id=run_id,
            run_state=projection.run_state,
            directive=directive,
            work_item=work_item,
        )

    def _schema_refusal(
        self,
        root: Path,
        error: LedgerSchemaRefusal,
    ) -> PrepareRunResponse:
        run_id = f"run:{self._digest(str(root))}"
        integrity = IntegrityFailure(
            code="incompatible_ledger_schema",
            detail=str(error),
            expected_schema_version=str(error.expected_version),
            found_schema_version=error.found_version,
            recovery=(
                "Preserve the existing .rob2 directory; no migration or rewrite was performed.",
                "Run rob2 doctor against the project root for schema diagnostics.",
                "Archive the incompatible state, then start a new Run explicitly.",
            ),
        )
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor="ledger:refused",
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_INTEGRITY_FAILURE,
            committed=False,
            run_id=run_id,
            run_state=RunState.INTEGRITY_FAILED,
            integrity=integrity,
        )

    def _prepare_configuration_error(
        self,
        root: Path,
        ledger: WorkflowLedger,
        error: ValueError,
    ) -> PrepareRunResponse:
        detail = str(error)
        if "unsupported RoB 2" in detail or "unsupported method" in detail:
            code: Literal["unsupported_method", "invalid_configuration"] = (
                "unsupported_method"
            )
            recovery = (
                "Edit rob2.yaml to use RoB 2 2019 individually-randomized parallel assignment.",
                "Start a new Run after correcting the project method configuration.",
            )
        else:
            code = "invalid_configuration"
            recovery = (
                "Correct the project YAML and rerun prepare_run.",
                "Preserve the existing .rob2 state while diagnosing the configuration.",
            )
        rejected_run_id = f"run:rejected-{self._digest(str(root))}"
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, rejected_run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(rejected_run_id,),
            condition=WorkflowCondition.RUN_BLOCKED,
            committed=False,
            next_permitted_action=RunOperation.PREPARE_RUN,
            run_id=rejected_run_id,
            run_state=RunState.BLOCKED,
            error=OperationError(code=code, detail=detail, recovery=recovery),
        )

    def _prepare_authorization_error(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal: RunProposal,
    ) -> PrepareRunResponse:
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_BLOCKED,
            committed=False,
            next_permitted_action=RunOperation.PREPARE_RUN,
            run_id=run_id,
            run_state=RunState.AWAITING_CONFIRMATION,
            proposal=proposal,
            error=OperationError(
                code="authorization_required",
                detail=(
                    "Project inputs changed and registry re-inventory requires fresh "
                    "project authorization."
                ),
                recovery=(
                    "Retry prepare_run with authorized=true to reconcile local inputs "
                    "and registry provenance.",
                    "Do not submit the existing proposal token after changing project inputs.",
                ),
            ),
        )

    def _prepare_integrity_failure(self, root: Path, detail: str) -> PrepareRunResponse:
        run_id = f"run:{self._digest(str(root))}"
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor="ledger:integrity-failure",
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_INTEGRITY_FAILURE,
            committed=False,
            run_id=run_id,
            run_state=RunState.INTEGRITY_FAILED,
            integrity=self._integrity_failure(detail),
        )

    @staticmethod
    def _integrity_failure(detail: str) -> IntegrityFailure:
        return IntegrityFailure(
            code="ledger_integrity_failure",
            detail=detail,
            recovery=(
                "Preserve the existing .rob2 directory.",
                "Run rob2 doctor and do not continue assessment writes.",
            ),
        )

    @classmethod
    def _integrity_from_error(
        cls, error: LifecycleIntegrityError | RunIntegrityFailure
    ) -> IntegrityFailure:
        if isinstance(error, LedgerSchemaRefusal):
            return IntegrityFailure(
                code="incompatible_ledger_schema",
                detail=str(error),
                expected_schema_version=str(error.expected_version),
                found_schema_version=error.found_version,
                recovery=(
                    "Preserve the existing .rob2 directory; no rewrite was performed.",
                    "Run rob2 doctor for schema diagnostics before starting a new Run.",
                ),
            )
        return cls._integrity_failure(str(error))

    @staticmethod
    def _event_payload(ledger: WorkflowLedger, event: WorkflowEvent) -> dict[str, object]:
        try:
            payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _condition_for_state(state: RunState) -> WorkflowCondition:
        return {
            RunState.AWAITING_CONFIRMATION: WorkflowCondition.CONFIRMATION_REQUIRED,
            RunState.ASSESSING: WorkflowCondition.AGENT_WORK_REQUIRED,
            RunState.BLOCKED: WorkflowCondition.RUN_BLOCKED,
            RunState.COMPLETE: WorkflowCondition.RUN_COMPLETE,
            RunState.INTEGRITY_FAILED: WorkflowCondition.RUN_INTEGRITY_FAILURE,
            RunState.RETIRED: WorkflowCondition.COMPLETED,
        }[state]

    @staticmethod
    def _next_action_for_state(state: RunState) -> RunOperation | None:
        if state is RunState.AWAITING_CONFIRMATION:
            return RunOperation.SUBMIT_RUN_PROPOSAL
        if state is RunState.ASSESSING:
            return RunOperation.CONTINUE_RUN
        return None

    @classmethod
    def _read_operation_id(cls, operation: RunOperation, run_id: Identifier) -> Identifier:
        return f"operation:{cls._digest(f'{operation.value}|{run_id}')}"

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:24]
