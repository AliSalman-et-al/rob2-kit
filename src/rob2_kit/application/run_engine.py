"""Typed host-neutral application boundary for lean-v1 Runs."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
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
from rob2_kit.domain.revisions import Actor, ActorKind, ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import SourceRole
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
    ResultCandidate,
    TrialInitialization,
    _parse_source,
    _registry_source_descriptor,
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


class _ResultInvalidatedRecord(FrozenModel):
    """Durable marker for Result work invalidated by a changed input."""

    run_id: Identifier
    result_id: Identifier
    reason: str
    affected_trial_id: Identifier
    affected_source_ids: tuple[Identifier, ...] = ()
    input_snapshot_hash: ContentHash


class _RunReconciledRecord(FrozenModel):
    """The immutable input reconciliation checkpoint for one Current Run."""

    run_id: Identifier
    proposal: RunProposal
    input_snapshot_hash: ContentHash
    active_trial_ids: tuple[Identifier, ...]
    active_result_ids: tuple[Identifier, ...]
    added_trial_ids: tuple[Identifier, ...] = ()
    retired_trial_ids: tuple[Identifier, ...] = ()
    added_result_ids: tuple[Identifier, ...] = ()
    retired_result_ids: tuple[Identifier, ...] = ()
    affected_trial_ids: tuple[Identifier, ...] = ()
    affected_source_ids: tuple[Identifier, ...] = ()
    invalidated_result_ids: tuple[Identifier, ...] = ()
    diagnostic_result_ids: tuple[Identifier, ...] = ()
    material_ambiguities: tuple[RunProposalAmbiguity, ...] = ()


class _DiagnosticResultDiscoveredRecord(FrozenModel):
    """Typed lifecycle registration for a Trial with no assessable Result."""

    lifecycle_event: Literal["diagnostic_result_discovered"] = "diagnostic_result_discovered"
    run_id: Identifier
    result_id: Identifier
    trial_id: Identifier
    reason: str


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


class _RunUnblockedRecord(FrozenModel):
    run_id: Identifier
    input_snapshot_hash: ContentHash


class _RunReopenedRecord(FrozenModel):
    run_id: Identifier
    input_snapshot_hash: ContentHash
    invalidated_result_ids: tuple[Identifier, ...] = ()
    added_result_ids: tuple[Identifier, ...] = ()


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
        self._authorized_root: Path | None = None
        self._owner_id = f"owner:run-engine:{os.getpid()}:{uuid.uuid4()}"

    def prepare_run(self, request: PrepareRunRequest) -> PrepareRunResponse:
        root = request.project_root.resolve()
        self._bind(root)
        try:
            self._validate_project_root_layout(root)
        except ValueError as error:
            return self._prepare_root_configuration_error(root, error)
        if request.authorized:
            self._authorized_root = root
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
            if len(unfinished) > 1:
                self._retire_prior_unfinished(ledger, unfinished[:-1], current.run_id)
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
                    diagnostic_result_ids = {
                        event.scope
                        for event in self._events_for_run(ledger, current.run_id)
                        if event.operation == "operation:result-diagnostic-ready"
                    }
                    for result_spec in initialization.result_specs:
                        result_id = result_spec.result.result_id
                        failed_trial = next(
                            (
                                trial
                                for trial in initialization.trials
                                if trial.trial_id == result_spec.result.trial_id
                                and trial.status == "trial_failed"
                            ),
                            None,
                        )
                        if result_id in registered_result_ids:
                            prior_spec = self._result_spec_for(
                                ledger, current.run_id, result_id
                            )
                            if prior_spec is not None and prior_spec != result_spec:
                                supersede_suffix = self._digest(
                                    f"{current.run_id}|{result_id}|"
                                    f"{result_spec.model_dump_json()}"
                                )
                                transitions.append(
                                    self._transition(
                                        scope=result_id,
                                        operation="operation:result-spec-superseded",
                                        operation_key=(
                                            f"idempotency:result-spec-superseded-"
                                            f"{supersede_suffix}"
                                        ),
                                        entity_id=f"result-spec:{result_id.removeprefix('result:')}",
                                        revision_id=(
                                            f"revision:result-spec-superseded-{supersede_suffix}"
                                        ),
                                        artifact=_ResultDiscoveredRecord(
                                            run_id=current.run_id,
                                            result_id=result_id,
                                            result_spec=result_spec,
                                        ),
                                        checkpoint=(
                                            f"checkpoint:result-spec-superseded-{supersede_suffix}"
                                        ),
                                        outcome=WorkflowEventOutcome.COMPLETED,
                                        observed_at=now,
                                    )
                                )
                            if failed_trial is None or result_id in diagnostic_result_ids:
                                continue
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
                    registered_trial_ids = {
                        result_spec.result.trial_id for result_spec in initialization.result_specs
                    }
                    for trial in initialization.trials:
                        if trial.status != "trial_failed" or trial.trial_id in registered_trial_ids:
                            continue
                        result_id = self._diagnostic_result_id(current.run_id, trial.trial_id)
                        if result_id in diagnostic_result_ids:
                            continue
                        reason = (
                            trial.failure.detail
                            if trial.failure is not None
                            else "Trial-specific initialization failed"
                        )
                        diagnostic_suffix = self._digest(
                            f"{current.run_id}|{result_id}|diagnostic"
                        )
                        transitions.extend(
                            (
                                self._transition(
                                    scope=result_id,
                                    operation="operation:run-register-diagnostic-result",
                                    operation_key=(
                                        f"idempotency:register-diagnostic-{diagnostic_suffix}"
                                    ),
                                    entity_id=f"diagnostic-result:{diagnostic_suffix}",
                                    revision_id=f"revision:diagnostic-result-{diagnostic_suffix}",
                                    artifact=_DiagnosticResultDiscoveredRecord(
                                        run_id=current.run_id,
                                        result_id=result_id,
                                        trial_id=trial.trial_id,
                                        reason=reason,
                                    ),
                                    checkpoint=f"checkpoint:diagnostic-result-{diagnostic_suffix}",
                                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                                    observed_at=now,
                                ),
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
                                        trial_id=trial.trial_id,
                                        reason=reason,
                                    ),
                                    checkpoint=f"checkpoint:result-diagnostic-{diagnostic_suffix}",
                                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                                    observed_at=now,
                                ),
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
            # Once the Run definition is confirmed, local input changes are
            # reconciled against the immutable definition before the Harness
            # receives another continuation response.  An authorized
            # prepare_run may commit the reconciliation; a read-only resume
            # reports the same authorization requirement without mutating the
            # ledger.
            if projection.run_state in {
                RunState.ASSESSING,
                RunState.BLOCKED,
                RunState.COMPLETE,
            }:
                try:
                    changed = self._input_snapshot_hash(root) != self._latest_proposal(
                        ledger, current.run_id
                    ).input_snapshot_hash
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                if changed and not request.authorized:
                    return self._prepare_authorization_error(
                        ledger,
                        current.run_id,
                        self._latest_proposal(ledger, current.run_id),
                        run_state=projection.run_state,
                    )
                if changed and request.authorized:
                    self._reconcile_current_run(ledger, current.run_id)
                    projection = self._projection(ledger, current.run_id)
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
        registered_trial_ids = {
            result_spec.result.trial_id for result_spec in initialization.result_specs
        }
        for trial in initialization.trials:
            if trial.status != "trial_failed" or trial.trial_id in registered_trial_ids:
                continue
            result_id = self._diagnostic_result_id(run_id, trial.trial_id)
            reason = (
                trial.failure.detail
                if trial.failure is not None
                else "Trial-specific initialization failed"
            )
            diagnostic_suffix = self._digest(f"{run_id}|{result_id}|diagnostic")
            transitions.extend(
                (
                    self._transition(
                        scope=result_id,
                        operation="operation:run-register-diagnostic-result",
                        operation_key=f"idempotency:register-diagnostic-{diagnostic_suffix}",
                        entity_id=f"diagnostic-result:{diagnostic_suffix}",
                        revision_id=f"revision:diagnostic-result-{diagnostic_suffix}",
                        artifact=_DiagnosticResultDiscoveredRecord(
                            run_id=run_id,
                            result_id=result_id,
                            trial_id=trial.trial_id,
                            reason=reason,
                        ),
                        checkpoint=f"checkpoint:diagnostic-result-{diagnostic_suffix}",
                        outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                        observed_at=now,
                    ),
                    self._transition(
                        scope=result_id,
                        operation="operation:result-diagnostic-ready",
                        operation_key=f"idempotency:result-diagnostic-{diagnostic_suffix}",
                        entity_id=f"result-diagnostic:{diagnostic_suffix}",
                        revision_id=f"revision:result-diagnostic-{diagnostic_suffix}",
                        artifact=_ResultDiagnosticRecord(
                            run_id=run_id,
                            result_id=result_id,
                            trial_id=trial.trial_id,
                            reason=reason,
                        ),
                        checkpoint=f"checkpoint:result-diagnostic-{diagnostic_suffix}",
                        outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                        observed_at=now,
                    ),
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
                if item.result_id in self._result_ids(
                    ledger,
                    request.run_id,
                    self._latest_proposal(ledger, request.run_id),
                )
            ),
        )

    def continue_run(self, request: ContinueRunRequest) -> ContinueRunResponse:
        try:
            ledger = self._bound_ledger(request.run_id)
            # Reconciliation is part of every continuation.  It compares the
            # current confined input snapshot with the last committed
            # checkpoint and commits one idempotent batch when bytes changed.
            self._reconcile_current_run(ledger, request.run_id)
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
        reconciliation = self._latest_reconciliation(ledger, request.run_id)
        reconciliation_error = None
        if projection.run_state is RunState.BLOCKED and reconciliation is not None:
            ambiguity = next(iter(reconciliation.material_ambiguities), None)
            if ambiguity is not None:
                reconciliation_error = OperationError(
                    code="material_ambiguity",
                    detail=ambiguity.detail,
                    recovery=(
                        "Correct or remove the incompatible input and continue the Run.",
                        "Start a new Run explicitly if the confirmed meaning must change.",
                    ),
                )
        if (
            projection.run_state is RunState.ASSESSING
            and not self._result_ids(
                ledger,
                request.run_id,
                self._latest_proposal(ledger, request.run_id),
            )
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
            error=reconciliation_error,
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
                error=OperationError(
                    code="stale_work",
                    detail="The supplied WorkToken does not match the current WorkItem.",
                    recovery=(
                        "Discard the forged or stale token and use the token returned "
                        "by continue_run.",
                    ),
                ),
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
            if result_spec is not None:
                trial_id = result_spec.result.trial_id
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
        is_global_source_work = (
            work_item.operation is RunOperation.SUBMIT_SOURCE_CLASSIFICATION
            and work_item.trial_id is None
        )
        selected_trial_ids = self._active_trial_ids(ledger, request.run_id)
        trial = (
            None
            if is_global_source_work
            else next(
                (item for item in proposal.initialization.trials if item.trial_id == trial_id),
                None,
            )
        )
        scoped_trial_id = None if is_global_source_work else (
            trial.trial_id if trial is not None else trial_id
        )
        sources = (
            tuple(
                source
                for item in proposal.initialization.trials
                if item.status == "inventory_ready" and item.trial_id in selected_trial_ids
                for source in item.inventory.sources
            )
            if is_global_source_work
            else tuple(trial.inventory.sources) if trial is not None else ()
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
        proposal = self._latest_proposal(ledger, request.run_id)
        existing_event = self._event_for_operation_key(
            ledger, request.idempotency_key, run_id=request.run_id
        )
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
                    detail="The supplied Run proposal token was not issued by this Run.",
                    recovery=(
                        "Discard the unknown proposal token and call prepare_run again.",
                    ),
                ),
            )
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
        self._index_initial_evidence(self._required_root(), proposal.initialization)
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
            ledger,
            request.idempotency_key,
            transition.operation,
            record,
            run_id=request.run_id,
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
        if request.confirmed_by.kind is not ActorKind.HUMAN:
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
                    code="authorization_required",
                    detail="Run confirmation requires an attributable human Actor.",
                    recovery=(
                        "Provide a confirmed_by Actor with kind='human' and retry confirmation.",
                    ),
                ),
            )
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
                    detail="The supplied Run proposal token was not issued by this Run.",
                    recovery=(
                        "Discard the unknown proposal token and call prepare_run again.",
                    ),
                ),
            )
        existing = self._confirmed_for_idempotency(
            ledger, request.idempotency_key, run_id=request.run_id
        )
        if existing is not None:
            if existing.confirmed_by != request.confirmed_by:
                raise ValueError("idempotency key was already used with a different payload")
            existing_event = self._event_for_operation_key(
                ledger, request.idempotency_key, run_id=request.run_id
            )
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
        result_ids = list(selected_result_ids if proposal.selections else proposal.result_ids)
        # A selected failed Trial without a declared Result is represented by
        # an engine-issued diagnostic identity.  Keep that terminal diagnostic
        # inside the immutable confirmed scope so mixed batches can complete.
        failed_trial_ids = {
            trial.trial_id
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed" and trial.trial_id in trial_ids
        }
        for trial_id in failed_trial_ids:
            declared = tuple(
                spec.result.result_id
                for spec in proposal.initialization.result_specs
                if spec.result.trial_id == trial_id
            )
            for result_id in declared or (self._diagnostic_result_id(request.run_id, trial_id),):
                if result_id not in result_ids:
                    result_ids.append(result_id)
        result_ids = tuple(result_ids)
        selected_registry_candidate_ids = tuple(
            item.registry_candidate_id
            for item in accepted
            if item.registry_candidate_id is not None
        )
        explicit_registry_candidate_ids = tuple(
            item.candidate_id
            for item in proposal.registry_candidates
            if item.explicit and item.candidate_id not in selected_registry_candidate_ids
        )
        registry_candidate_ids = (
            selected_registry_candidate_ids + explicit_registry_candidate_ids
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
            ledger,
            request.idempotency_key,
            transition.operation,
            record,
            run_id=request.run_id,
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
        selected_trial_ids = self._active_trial_ids(ledger, request.run_id)
        issued_sources = {
            source.source_id
            for trial in proposal.initialization.trials
            if trial.status == "inventory_ready" and trial.trial_id in selected_trial_ids
            for source in trial.inventory.sources
            if SourceRole.REGISTRY_CURRENT not in source.roles
        }
        submitted_sources = {item.source_id for item in request.classifications}
        if not submitted_sources <= issued_sources:
            raise ValueError("Source classification includes an unissued source identifier")
        if submitted_sources != issued_sources:
            raise ValueError(
                "Source classification must include every inventory-ready source"
            )
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
        proposal = self._latest_proposal(ledger, request.run_id)
        trial = next(
            (
                item
                for item in proposal.initialization.trials
                if item.trial_id == request.result.trial_id
            ),
            None,
        )
        if trial is None and proposal.initialization.trials:
            raise ValueError("Result resolution references a Trial not issued by this Run")
        if trial is not None and trial.status == "trial_failed":
            raise ValueError("Result resolution is not permitted for a failed Trial")
        if request.result.effect_of_interest != "assignment":
            raise ValueError(
                "unsupported RoB 2 Result effect of interest "
                f"{request.result.effect_of_interest!r}; supported effect is 'assignment'"
            )
        expected = self._next_work_item(ledger, request.run_id)
        if (
            expected is None
            or expected.operation is not RunOperation.SUBMIT_RESULT_RESOLUTION
            or expected.result_id is None
            or request.result.result_id != expected.result_id
            or request.result.trial_id != expected.trial_id
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
        existing = self._event_for_operation_key(
            ledger, request.idempotency_key, run_id=request.run_id
        )
        if (
            existing is None
            and self._event_for_operation_key(ledger, request.idempotency_key) is not None
        ):
            raise ValueError("idempotency key was already used by another Run")
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
        """Fetch and durably project provenance for accepted registry candidates.

        Registry acquisition is an external capability, so it is only invoked
        during an explicitly authorized prepare/submit call.  The immutable
        proposal carries the complete acquisition, source, and receipt
        projection; later assessment calls only read that projection.
        """

        accepted_ids = {
            selection.registry_candidate_id
            for selection in selections
            if selection.accepted and selection.registry_candidate_id is not None
        }
        if not accepted_ids:
            return proposal
        if self._authorized_root is None or self._authorized_root != self._root:
            return proposal
        adapter = self._registry_adapter or self._registry_client
        if adapter is None:
            return proposal
        candidates = {item.candidate_id: item for item in proposal.registry_candidates}
        trials = {item.trial_id: item for item in proposal.initialization.trials}
        receipts = {
            item.receipt_id: item for item in proposal.initialization.acquisition_receipts
        }
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
            refreshed = candidate.model_copy(
                update={
                    "nct_id": acquisition.resolution.nct_id or candidate.nct_id,
                    "acquisition_status": acquisition.status,
                    "raw_record_hash": acquisition.raw_record_hash,
                    "projection": acquisition.projection,
                }
            )
            candidates[candidate_id] = refreshed
            trial = trials.get(candidate.trial_id)
            if trial is not None:
                registry_source, receipt = _registry_source_descriptor(
                    trial.trial_id,
                    acquisition,
                    ENGINE_ACTOR,
                )
                if registry_source is not None and registry_source.artifact_hash is not None:
                    try:
                        parser = self._parser or LiteParseAdapter()
                        artifacts = ArtifactStore(self._required_root() / ".rob2" / "artifacts")
                        parse_records, coverage = _parse_source(
                            parser,
                            artifacts.read(registry_source.artifact_hash),
                            registry_source.source_id,
                            registry_source.artifact_hash,
                            allow_recovery=False,
                        )
                        registry_source = registry_source.model_copy(
                            update={"parse_records": parse_records, "coverage": coverage}
                        )
                    except Exception:
                        pass
                sources = tuple(
                    source
                    for source in trial.inventory.sources
                    if SourceRole.REGISTRY_CURRENT not in source.roles
                )
                if registry_source is not None:
                    sources += (registry_source,)
                updated_candidates = tuple(
                    refreshed
                    if item.candidate_id == candidate_id
                    else item
                    for item in trial.registry_candidates
                )
                trials[candidate.trial_id] = trial.model_copy(
                    update={
                        "inventory": trial.inventory.model_copy(
                            update={"sources": sources}
                        ),
                        "registry_acquisition": acquisition,
                        "registry_candidates": updated_candidates,
                    }
                )
                if receipt is not None:
                    receipts[receipt.receipt_id] = receipt
            changed = True
        if not changed:
            return proposal
        initialization = proposal.initialization.model_copy(
            update={
                "trials": tuple(trials.values()),
                "acquisition_receipts": tuple(receipts.values()),
                "registry_candidates": tuple(candidates.values()),
            }
        )
        return proposal.model_copy(
            update={
                "initialization": initialization,
                "registry_candidates": tuple(candidates.values()),
            }
        )

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
            invalidated_at = max(
                (
                    prior.sequence
                    for prior in events
                    if prior.operation == "operation:result-invalidated"
                    and prior.scope == event.scope
                ),
                default=0,
            )
            if event.sequence <= invalidated_at:
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

        lifecycle_state = self._projection(ledger, run_id).run_state
        if lifecycle_state not in {RunState.ASSESSING, RunState.COMPLETE}:
            # A material reconciliation blocker takes precedence over any
            # diagnostic-only completion path.  Do not append run-completed
            # after run-blocked; lifecycle replay must remain valid.
            return
        events = self._events_for_run(ledger, run_id)
        latest_completed = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:run-completed"
            ),
            default=0,
        )
        latest_reopened = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:run-reopened"
            ),
            default=0,
        )
        if latest_completed and latest_reopened <= latest_completed:
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
            invalidated_at = max(
                (
                    event.sequence
                    for event in events
                    if event.operation == "operation:result-invalidated"
                    and event.scope == result_id
                ),
                default=0,
            )
            report_event = next(
                (
                    event
                    for event in events
                    if event.operation == "operation:result-report-ready"
                    and event.scope == result_id
                    and event.sequence > invalidated_at
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
        # A reopened completed Run may reach a fresh terminal checkpoint.  The
        # reconciliation sequence makes that completion idempotency key unique
        # while preserving retries within the same reconciliation cycle.
        completion_digest = self._digest(f"{run_id}|run-completed|{latest_reopened}")
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
        invalidated_at = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:result-invalidated"
                and event.scope == result_id
            ),
            default=0,
        )
        if any(
            event.operation == "operation:result-report-ready" and event.scope == result_id
            and event.sequence > invalidated_at
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
            and event.sequence > invalidated_at
        }
        answer_payloads = [
            self._event_payload(ledger, event)
            for event in events
            if event.operation == "operation:submit-domain-answers" and event.scope == result_id
            and event.sequence > invalidated_at
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
            f"{json.dumps(assessor_inputs, sort_keys=True)}|invalidated:{invalidated_at}"
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
                "operation:result-spec-superseded",
            }:
                continue
            try:
                if event.operation in {
                    "operation:run-register-result",
                    "operation:result-spec-superseded",
                }:
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
        # Every write requires the exact currently issued opaque token and
        # dependency fingerprint; this is the stale-work guard exposed to MCP
        # callers in every Run state.
        projection = self._projection(ledger, run_id)
        if work_token.run_id != run_id or work_token.operation is not expected_operation:
            expected = (
                self._next_work_item(ledger, run_id)
                if projection.run_state is RunState.ASSESSING
                else None
            )
            raise StaleWorkTokenError(run_id, expected)
        if projection.run_state is not RunState.ASSESSING:
            raise StaleWorkTokenError(run_id, None)
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
            self._validate_idempotent_event(
                ledger,
                operation_key,
                operation,
                artifact,
                run_id=run_id,
            )
        lease = self._acquire_lease(ledger, now)
        return ledger.commit(transition, lease, now=now)

    @staticmethod
    def _event_for_operation_key(
        ledger: WorkflowLedger,
        operation_key: Identifier,
        *,
        run_id: Identifier | None = None,
    ) -> WorkflowEvent | None:
        for event in ledger.events():
            if event.operation_key != operation_key:
                continue
            if run_id is None:
                return event
            if event.scope == run_id:
                return event
            try:
                payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
            except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("run_id") == run_id:
                return event
        return None

    def _confirmed_for_idempotency(
        self,
        ledger: WorkflowLedger,
        operation_key: Identifier,
        *,
        run_id: Identifier | None = None,
    ) -> ConfirmedRunDefinition | None:
        event = self._event_for_operation_key(ledger, operation_key, run_id=run_id)
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
        *,
        run_id: Identifier | None = None,
    ) -> None:
        existing = self._event_for_operation_key(ledger, operation_key, run_id=run_id)
        global_existing = self._event_for_operation_key(ledger, operation_key)
        if existing is None and global_existing is not None:
            raise ValueError("idempotency key was already used by another Run")
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
                and selection.result_id
                != issued_result_candidates[selection.result_candidate_id].result_id
            ):
                raise ValueError(
                    "resolved Result candidate must use its engine-issued Result identifier"
                )
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
        seen: set[Identifier] = set()
        for item in ambiguities:
            if item.ambiguity_id in seen:
                raise ValueError("Run proposal contains a duplicate ambiguity")
            seen.add(item.ambiguity_id)
            if item.ambiguity_id not in issued:
                raise ValueError(
                    "Run proposal ambiguity identifier was not issued by this Run"
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
                if (
                    item.resolved
                    and original.detail.startswith("Multiple top-level PDFs found;")
                ):
                    raise ValueError(
                        "primary-report ambiguity must be resolved by an explicit "
                        "trial.yaml primary_report declaration"
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
        initialization = proposal.initialization.model_copy(
            update={"result_candidates": tuple(candidates.values())}
        )
        return proposal.model_copy(
            update={
                "initialization": initialization,
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

    def _diagnostic_result_id(self, run_id: Identifier, trial_id: Identifier) -> Identifier:
        """Issue a Run-scoped identity for a terminal Trial diagnostic."""

        digest = self._digest(f"{run_id}|diagnostic-result|{trial_id}")
        return f"result:diagnostic-{digest}"

    def _confirmed_definition(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> ConfirmedRunDefinition | None:
        """Read the immutable definition that bounds post-confirmation work."""

        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation != "operation:run-confirmed":
                continue
            try:
                return _ConfirmedRunRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).run_definition
            except (IndexError, ValueError):
                return None
        return None

    def _active_trial_ids(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> set[Identifier]:
        reconciliation = self._latest_reconciliation(ledger, run_id)
        if reconciliation is not None:
            return set(reconciliation.active_trial_ids)
        definition = self._confirmed_definition(ledger, run_id)
        return set(definition.trial_ids) if definition is not None else set()

    def _active_result_ids(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> set[Identifier]:
        reconciliation = self._latest_reconciliation(ledger, run_id)
        if reconciliation is not None:
            return set(reconciliation.active_result_ids)
        definition = self._confirmed_definition(ledger, run_id)
        return set(definition.result_ids) if definition is not None else set()

    def _next_work_item(self, ledger: WorkflowLedger, run_id: Identifier) -> WorkItem | None:
        """Derive the next bounded submission from committed checkpoints."""

        projection = self._projection(ledger, run_id)
        if projection.run_state is not RunState.ASSESSING:
            return None
        proposal = self._latest_proposal(ledger, run_id)
        events = self._events_for_run(ledger, run_id)
        definition = self._confirmed_definition(ledger, run_id)
        if definition is None:
            return None
        selected_trial_ids = self._active_trial_ids(ledger, run_id)
        if (
            any(
                trial.status == "inventory_ready" and trial.trial_id in selected_trial_ids
                for trial in proposal.initialization.trials
            )
            and not self._source_classification_complete(
                proposal,
                ledger,
                events,
                selected_trial_ids=selected_trial_ids,
            )
        ):
            return self._work_item(run_id, "sources", RunOperation.SUBMIT_SOURCE_CLASSIFICATION)
        if not selected_trial_ids:
            return None

        all_result_ids = self._result_ids(ledger, run_id, proposal, definition=definition)
        failed_result_ids = self._failed_result_ids(proposal, result_ids=set(all_result_ids))
        failed_result_ids |= frozenset(
            self._diagnostic_result_id(run_id, trial.trial_id)
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed"
            and trial.trial_id in selected_trial_ids
            and not any(
                spec.result.trial_id == trial.trial_id
                for spec in proposal.initialization.result_specs
            )
        )
        unresolved_trial = self._unresolved_trial_id(
            proposal,
            ledger,
            events,
            definition=definition,
        )
        if unresolved_trial is not None:
            unresolved_result_id = self._issued_unresolved_result_id(
                run_id, unresolved_trial
            )
            return self._work_item(
                run_id,
                f"result:unresolved:{unresolved_trial.removeprefix('trial:')}",
                RunOperation.SUBMIT_RESULT_RESOLUTION,
                result_id=unresolved_result_id,
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
        *,
        definition: ConfirmedRunDefinition,
    ) -> Identifier | None:
        selected_trial_ids = self._active_trial_ids(ledger, definition.run_id)
        selected_result_ids = self._active_result_ids(ledger, definition.run_id)
        failed_trials = {
            trial.trial_id
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed" and trial.trial_id in selected_trial_ids
        }
        resolved_trials = {
            spec.result.trial_id
            for spec in proposal.initialization.result_specs
            if spec.result.result_id in selected_result_ids
        }
        resolved_trials.update(
            candidate.trial_id
            for candidate in proposal.result_candidates
            if candidate.result_id in selected_result_ids and candidate.status == "resolved"
        )
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
                result_id = raw_result.get("result_id")
                if (
                    isinstance(trial_id, str)
                    and isinstance(result_id, str)
                    and result_id
                    in selected_result_ids.union(
                        self._issued_unresolved_result_id(definition.run_id, trial_id)
                        for trial_id in selected_trial_ids
                    )
                ):
                    resolved_trials.add(trial_id)
        return next(
            (
                trial.trial_id
                for trial in proposal.initialization.trials
                if trial.status == "inventory_ready"
                and trial.trial_id in selected_trial_ids
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
        invalidated_at = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:result-invalidated"
                and event.scope == result_id
            ),
            default=0,
        )
        return any(
            event.operation == operation
            and event.scope == result_id
            and event.sequence > invalidated_at
            and event.checkpoint == f"checkpoint:{kind}-{domain_id.removeprefix('domain:')}"
            for event in events
        )

    def _result_ids(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal: RunProposal,
        *,
        definition: ConfirmedRunDefinition | None = None,
    ) -> tuple[Identifier, ...]:
        definition = definition or self._confirmed_definition(ledger, run_id)
        if definition is None:
            return ()
        active_ids = self._active_result_ids(ledger, run_id)
        ordered_ids = tuple(
            result_id
            for result_id in proposal.result_ids
            if result_id in active_ids
        )
        ids = list(ordered_ids)
        ids.extend(sorted(active_ids - set(ordered_ids)))
        allowed_event_ids = set(ids)
        allowed_event_ids.update(
            self._issued_unresolved_result_id(run_id, trial_id)
            for trial_id in self._active_trial_ids(ledger, run_id)
        )
        for event in self._events_for_run(ledger, run_id):
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
            }:
                continue
            payload = self._event_payload(ledger, event)
            result_id = payload.get("result_id")
            if (
                isinstance(result_id, str)
                and result_id in allowed_event_ids
                and result_id not in ids
            ):
                ids.append(result_id)
        return tuple(ids)

    def _issued_unresolved_result_id(
        self, run_id: Identifier, trial_id: Identifier
    ) -> Identifier:
        digest = self._digest(f"{run_id}|unresolved-result|{trial_id}")
        return f"result:unresolved-{digest}"

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
            candidate_trial = next(
                (
                    candidate.trial_id
                    for candidate in proposal.result_candidates
                    if candidate.result_id == result_id
                ),
                None,
            )
            if candidate_trial is not None:
                return candidate_trial
            for event in self._events_for_run(ledger, current.run_id):
                if event.operation not in {
                    "operation:result-discovered",
                    "operation:submit-result-resolution",
                }:
                    continue
                payload = self._event_payload(ledger, event)
                if payload.get("result_id") != result_id:
                    continue
                raw_spec = payload.get("result_spec")
                if isinstance(raw_spec, dict):
                    raw_result = raw_spec.get("result")
                    if isinstance(raw_result, dict) and isinstance(
                        raw_result.get("trial_id"), str
                    ):
                        raw_trial_id = raw_result.get("trial_id")
                        if isinstance(raw_trial_id, str):
                            return raw_trial_id
            return None
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

    def _retire_prior_unfinished(
        self,
        ledger: WorkflowLedger,
        records: tuple[_PreparedRunRecord, ...],
        replacement_run_id: Identifier,
    ) -> None:
        now = datetime.now(UTC)
        transitions: list[Transition] = []
        for prior in records:
            suffix = self._digest(f"{prior.run_id}|{replacement_run_id}|retired")
            transitions.append(
                self._transition(
                    scope=prior.run_id,
                    operation="operation:run-retired",
                    operation_key=f"idempotency:retire-run-{suffix}",
                    entity_id=f"run-retirement:{suffix}",
                    revision_id=f"revision:run-retirement-{suffix}",
                    artifact=_RunRetiredRecord(
                        run_id=prior.run_id,
                        replacement_run_id=replacement_run_id,
                    ),
                    checkpoint="checkpoint:run-retired",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                )
            )
        if transitions:
            lease = self._acquire_lease(ledger, now)
            ledger.commit_batch(tuple(transitions), lease, now=now)

    def _unfinished_prepared_records(
        self, ledger: WorkflowLedger
    ) -> tuple[_PreparedRunRecord, ...]:
        return tuple(
            record
            for record in self._prepared_records(ledger)
            if self._projection(ledger, record.run_id).run_state
            not in {RunState.COMPLETE, RunState.RETIRED}
        )

    @staticmethod
    def _source_classification_complete(
        proposal: RunProposal,
        ledger: WorkflowLedger,
        events: tuple[WorkflowEvent, ...],
        *,
        selected_trial_ids: set[Identifier],
    ) -> bool:
        """Return whether every inventory-ready source has a durable role set."""

        issued_sources = {
            source.source_id
            for trial in proposal.initialization.trials
            if trial.status == "inventory_ready" and trial.trial_id in selected_trial_ids
            for source in trial.inventory.sources
            if SourceRole.REGISTRY_CURRENT not in source.roles
        }
        if not issued_sources:
            return True
        classified: set[Identifier] = set()
        for event in events:
            if event.operation != "operation:submit-source-classification":
                continue
            payload = RunEngine._event_payload(ledger, event)
            raw = payload.get("classifications")
            if not isinstance(raw, (list, tuple)):
                continue
            for item in raw:
                source_id = item.get("source_id") if isinstance(item, dict) else None
                if isinstance(source_id, str):
                    classified.add(source_id)
        return issued_sources <= classified

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

    def _latest_reconciliation(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> _RunReconciledRecord | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation != "operation:run-reconciled":
                continue
            try:
                return _RunReconciledRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                )
            except (IndexError, ValueError):
                return None
        return None

    def _commit_snapshot_error_blocker(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        *,
        projection: LifecycleProjection,
        existing: RunProposal,
        definition: ConfirmedRunDefinition,
        previous_reconciliation: _RunReconciledRecord | None,
        error: ValueError,
    ) -> None:
        """Durably block an input snapshot that cannot be safely read.

        No reinventory or evidence mutation is attempted.  A deterministic
        synthetic hash marks the failed snapshot so correcting the path later
        always triggers a fresh reconciliation, even when the bytes return to
        the prior valid scan.
        """

        detail = f"Input reconciliation could not safely snapshot project inputs: {error}"
        invalid_hash = "sha256:" + hashlib.sha256(
            f"{run_id}|invalid-input-snapshot|{detail}".encode()
        ).hexdigest()
        ambiguity = RunProposalAmbiguity(
            ambiguity_id=f"ambiguity:{self._digest(f'{run_id}|{invalid_hash}|snapshot-error')}",
            scope=run_id,
            detail=detail,
            material=True,
        )
        proposal = existing.model_copy(
            update={
                "proposal_id": f"run-proposal:{self._digest(f'{run_id}|{invalid_hash}|ambiguous')}",
                "proposal_token": (
                    f"proposal-token:{self._digest(f'{run_id}|{invalid_hash}|ambiguous')}"
                ),
                "input_snapshot_hash": invalid_hash,
                "ambiguities": tuple(dict.fromkeys(existing.ambiguities + (ambiguity,))),
            }
        )
        record = _RunReconciledRecord(
            run_id=run_id,
            proposal=proposal,
            input_snapshot_hash=invalid_hash,
            active_trial_ids=(
                previous_reconciliation.active_trial_ids
                if previous_reconciliation is not None
                else definition.trial_ids
            ),
            active_result_ids=(
                previous_reconciliation.active_result_ids
                if previous_reconciliation is not None
                else definition.result_ids
            ),
            material_ambiguities=(ambiguity,),
        )
        self._commit_reconciliation_batch(
            ledger,
            run_id,
            record,
            material_ambiguity=ambiguity,
            projection=projection,
        )

    def _reconcile_current_run(self, ledger: WorkflowLedger, run_id: Identifier) -> bool:
        """Reconcile changed local inputs for a confirmed Current Run.

        The input hash is checked before any parser or registry work.  A
        changed snapshot is represented by one append-only ``run-reconciled``
        checkpoint and a single atomic batch of Result invalidations and scope
        transitions.  Replaying the same snapshot is therefore a no-op even
        when a host process was interrupted after the commit.
        """

        projection = self._projection(ledger, run_id)
        if projection.run_state not in {
            RunState.ASSESSING,
            RunState.BLOCKED,
            RunState.COMPLETE,
        }:
            return False
        existing = self._latest_proposal(ledger, run_id)
        definition = self._confirmed_definition(ledger, run_id)
        if definition is None:
            # A malformed ledger is surfaced through the normal lifecycle
            # integrity path by the caller; there is no safe scope to mutate.
            return False
        previous_reconciliation = self._latest_reconciliation(ledger, run_id)
        try:
            current_hash = self._input_snapshot_hash(self._required_root())
        except ValueError as error:
            self._commit_snapshot_error_blocker(
                ledger,
                run_id,
                projection=projection,
                existing=existing,
                definition=definition,
                previous_reconciliation=previous_reconciliation,
                error=error,
            )
            return True
        if current_hash == existing.input_snapshot_hash:
            return False
        previous_active_trials = set(
            previous_reconciliation.active_trial_ids
            if previous_reconciliation is not None
            else definition.trial_ids
        )
        previous_active_results = set(
            previous_reconciliation.active_result_ids
            if previous_reconciliation is not None
            else definition.result_ids
        )

        initialization: ProjectInitialization | None = None
        try:
            initialization = initialize_project(
                self._required_root(),
                actor=ENGINE_ACTOR,
                parser=self._parser,
                # A continuation may come from a fresh Harness process.  Do
                # not perform a new network request without explicit root
                # authorization; injected deterministic adapters remain safe.
                registry_adapter=(
                    self._registry_adapter
                    if self._registry_adapter is not None
                    else self._registry_for_prepare(
                        self._required_root(), self._authorized_root == self._required_root()
                    )
                ),
            )
        except ValueError as error:
            # A declaration that points at a Trial folder removed after
            # confirmation is a supported retirement, not semantic drift.
            # Preserve the old proposal as history while removing that Trial
            # and its Results from the active scope.
            missing_trials = set(existing.trial_ids) - self._input_trial_ids(
                self._required_root()
            )
            if missing_trials and "declared Result references unknown Trial" in str(error):
                # A Trial folder may have been renamed while its declared
                # Result still carries the confirmed identity.  Re-inventory
                # with that reference retained so the fingerprint mapper can
                # preserve the old Trial/Source IDs instead of retiring it.
                try:
                    initialization = initialize_project(
                        self._required_root(),
                        actor=ENGINE_ACTOR,
                        parser=self._parser,
                        registry_adapter=(
                            self._registry_adapter
                            if self._registry_adapter is not None
                            else self._registry_for_prepare(
                                self._required_root(),
                                self._authorized_root == self._required_root(),
                            )
                        ),
                        allow_unknown_result_trials=True,
                    )
                except ValueError:
                    initialization = None
            if (
                initialization is None
                and missing_trials
                and "declared Result references unknown Trial" in str(error)
            ):
                retired_results = {
                    result_id
                    for result_id in (
                        previous_reconciliation.active_result_ids
                        if previous_reconciliation is not None
                        else definition.result_ids
                    )
                    if self._trial_for_result(existing.initialization, result_id)
                    in missing_trials
                }
                active_trials = set(
                    previous_reconciliation.active_trial_ids
                    if previous_reconciliation is not None
                    else definition.trial_ids
                ) - missing_trials
                active_results = set(
                    previous_reconciliation.active_result_ids
                    if previous_reconciliation is not None
                    else definition.result_ids
                ) - retired_results
                proposal = existing.model_copy(
                    update={
                        "proposal_id": (
                            "run-proposal:"
                            f"{self._digest(f'{run_id}|{current_hash}|retired')}"
                        ),
                        "proposal_token": (
                            "proposal-token:"
                            f"{self._digest(f'{run_id}|{current_hash}|retired')}"
                        ),
                        "input_snapshot_hash": current_hash,
                        "trial_ids": tuple(
                            sorted(self._input_trial_ids(self._required_root()))
                        ),
                        "result_ids": tuple(sorted(active_results)),
                    }
                )
                record = _RunReconciledRecord(
                    run_id=run_id,
                    proposal=proposal,
                    input_snapshot_hash=current_hash,
                    active_trial_ids=tuple(sorted(active_trials)),
                    active_result_ids=tuple(sorted(active_results)),
                    retired_trial_ids=tuple(sorted(missing_trials)),
                    retired_result_ids=tuple(sorted(retired_results)),
                    affected_trial_ids=tuple(sorted(missing_trials)),
                    invalidated_result_ids=tuple(
                        item.result_id
                        for item in self._projection(ledger, run_id).results
                        if item.result_id in retired_results
                        and item.state
                        in {
                            ResultState.ASSESSING,
                            ResultState.REPORT_READY,
                            ResultState.DIAGNOSTIC_READY,
                        }
                    ),
                )
                self._commit_reconciliation_batch(
                    ledger,
                    run_id,
                    record,
                    projection=projection,
                    invalidated_result_ids=record.invalidated_result_ids,
                )
                return True
            if initialization is None:
                ambiguity = RunProposalAmbiguity(
                    ambiguity_id=(
                        f"ambiguity:{self._digest(f'{run_id}|reconcile|{current_hash}|{error}')}"
                    ),
                    scope=run_id,
                    detail=(
                        "Input reconciliation could not safely map the Confirmed run "
                        f"definition: {error}"
                    ),
                    material=True,
                )
                proposal = existing.model_copy(
                    update={
                        "proposal_id": (
                            "run-proposal:"
                            f"{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                        ),
                        "proposal_token": (
                            "proposal-token:"
                            f"{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                        ),
                        "input_snapshot_hash": current_hash,
                        "ambiguities": existing.ambiguities + (ambiguity,),
                    }
                )
                record = _RunReconciledRecord(
                    run_id=run_id,
                    proposal=proposal,
                    input_snapshot_hash=current_hash,
                    active_trial_ids=(
                        previous_reconciliation.active_trial_ids
                        if previous_reconciliation is not None
                        else definition.trial_ids
                    ),
                    active_result_ids=(
                        previous_reconciliation.active_result_ids
                        if previous_reconciliation is not None
                        else definition.result_ids
                    ),
                    material_ambiguities=(ambiguity,),
                )
                self._commit_reconciliation_batch(
                    ledger,
                    run_id,
                    record,
                    material_ambiguity=ambiguity,
                    projection=projection,
                )
                return True

        assert initialization is not None
        mapping_ambiguities = self._identity_mapping_ambiguities(
            existing.initialization, initialization
        )
        initialization = self._remap_initialization_identities(
            existing.initialization, initialization
        )
        historical_result_specs = self._historical_result_specs(ledger, run_id)
        initialization = self._preserve_reconciled_result_mappings(
            existing.initialization,
            initialization,
            historical_result_specs=historical_result_specs,
            previous_active_result_ids=previous_active_results,
            existing_result_ids=set(existing.result_ids),
            run_id=run_id,
        )
        try:
            refreshed = self._proposal(run_id, initialization)
        except ValueError as error:
            self._commit_snapshot_error_blocker(
                ledger,
                run_id,
                projection=projection,
                existing=existing,
                definition=definition,
                previous_reconciliation=previous_reconciliation,
                error=error,
            )
            return True
        # Index canonical units only after Trial/Source identity remapping.  A
        # path move can change discovery order and therefore the provisional
        # ordinal IDs emitted by the parser; indexing before remapping would
        # leave search/citation units under those stale IDs.  Build the
        # durable proposal first so a concurrent snapshot-read failure cannot
        # leave a partially refreshed evidence index behind.
        if not mapping_ambiguities:
            self._index_initial_evidence(self._required_root(), initialization)
        resolved_result_ids = tuple(
            candidate.result_id
            for candidate in initialization.result_candidates
            if candidate.status == "resolved" and candidate.result_id is not None
        )
        refreshed = refreshed.model_copy(
            update={
                "result_ids": tuple(
                    dict.fromkeys(refreshed.result_ids + resolved_result_ids)
                ),
                # Confirmation is immutable, but accepted proposal selections
                # remain useful orientation metadata after a reconciliation.
                "selections": tuple(
                    item
                    for item in existing.selections
                    if item.trial_id in {trial.trial_id for trial in initialization.trials}
                ),
            }
        )
        old_trial_ids = set(existing.trial_ids)
        new_trial_ids = {trial.trial_id for trial in initialization.trials}
        added_trial_ids = new_trial_ids - old_trial_ids
        retired_trial_ids = old_trial_ids - new_trial_ids
        result_mapping_ambiguities = self._result_definition_ambiguities(
            existing.initialization,
            initialization,
            set(existing.result_ids) | set(historical_result_specs),
            retired_trial_ids,
            added_trial_ids,
            historical_result_specs=historical_result_specs,
        )
        old_sources = self._sources_by_trial(existing.initialization)
        new_sources = self._sources_by_trial(initialization)
        affected_trial_ids: set[Identifier] = set()
        affected_source_ids: set[Identifier] = set()
        for trial_id in sorted(old_trial_ids | new_trial_ids):
            before = old_sources.get(trial_id, {})
            after = new_sources.get(trial_id, {})
            source_ids = set(before) | set(after)
            changed = False
            for source_id in source_ids:
                previous = before.get(source_id)
                current = after.get(source_id)
                if previous is None or current is None:
                    changed = True
                    affected_source_ids.add(source_id)
                    continue
                if self._source_semantics_differ(previous, current):
                    changed = True
                    affected_source_ids.add(source_id)
            if changed:
                affected_trial_ids.add(trial_id)
        affected_trial_ids.update(added_trial_ids)
        affected_trial_ids.update(retired_trial_ids)

        # A method/effect/Outcome-target change would silently alter the
        # confirmed meaning.  Keep the definition immutable and block the Run
        # until the input is corrected or a new Run is explicitly started.
        material_ambiguities: list[RunProposalAmbiguity] = []
        old_manifest = existing.initialization.manifest
        new_manifest = initialization.manifest
        semantic_changes = (
            old_manifest.supported_scope != new_manifest.supported_scope
            or old_manifest.method_version != new_manifest.method_version
            or old_manifest.effect_of_interest != new_manifest.effect_of_interest
            or old_manifest.outcome_targets != new_manifest.outcome_targets
            or old_manifest.outcome_target_specs != new_manifest.outcome_target_specs
        )
        if semantic_changes:
            material_ambiguities.append(
                RunProposalAmbiguity(
                    ambiguity_id=f"ambiguity:{self._digest(f'{run_id}|{current_hash}|semantic')}",
                    scope=run_id,
                    detail=(
                        "Project method, effect, or Outcome-target meaning changed "
                        "after Run confirmation."
                    ),
                    material=True,
                )
            )
        material_ambiguities.extend(
            RunProposalAmbiguity(
                ambiguity_id=(
                    f"ambiguity:{self._digest(f'{run_id}|{current_hash}|mapping|{detail}')}"
                ),
                scope=run_id,
                detail=detail,
                material=True,
            )
            for detail in mapping_ambiguities
        )
        material_ambiguities.extend(
            RunProposalAmbiguity(
                ambiguity_id=(
                    f"ambiguity:{self._digest(f'{run_id}|{current_hash}|result|{detail}')}"
                ),
                scope=run_id,
                detail=detail,
                material=True,
            )
            for detail in result_mapping_ambiguities
        )
        # A new Outcome-target candidate is an engine work item (the agent can
        # submit an exact ResultSpec); it is not itself a run-wide semantic
        # ambiguity.  Retain all other unresolved findings, especially source
        # identity and method drift, as material blockers.
        added_candidate_ids = {
            candidate.candidate_id
            for candidate in initialization.result_candidates
            if candidate.trial_id in added_trial_ids
        }
        material_ambiguities.extend(
            item
            for item in refreshed.unresolved_ambiguities
            if item.scope not in added_candidate_ids
        )
        if material_ambiguities:
            # Keep the last safe inventory/proposal as the reconciliation
            # baseline.  Persist only the new snapshot hash and blocker; if
            # the operator corrects the input, the next pass can compare it
            # against the immutable Confirmed meaning instead of comparing
            # against the unsafe proposal that caused the block.
            refreshed = existing.model_copy(
                update={
                    "proposal_id": (
                        "run-proposal:"
                        f"{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                    ),
                    "proposal_token": (
                        "proposal-token:"
                        f"{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                    ),
                    "input_snapshot_hash": current_hash,
                    "ambiguities": tuple(
                        dict.fromkeys(
                            existing.ambiguities + tuple(material_ambiguities)
                        )
                    )
                }
            )

        # Existing confirmed scope remains authoritative.  New Trials and
        # Result declarations are compatible additions; old rejected or
        # removed items never re-enter active outputs accidentally.
        active_trial_ids = (previous_active_trials - retired_trial_ids) | added_trial_ids
        active_trial_ids &= new_trial_ids
        refreshed_result_ids = {
            spec.result.result_id for spec in initialization.result_specs
        }
        refreshed_result_ids.update(
            candidate.result_id
            for candidate in initialization.result_candidates
            if candidate.result_id is not None and candidate.status == "resolved"
        )
        added_result_ids = refreshed_result_ids - set(existing.result_ids)
        added_result_ids = {
            result_id
            for result_id in added_result_ids
            if self._trial_for_result(initialization, result_id) in added_trial_ids
            or result_id not in existing.result_ids
        }
        retired_result_ids = {
            result_id
            for result_id in previous_active_results
            if result_id in existing.result_ids
            and self._trial_for_result(existing.initialization, result_id) in retired_trial_ids
        }
        # Result IDs on removed Trial folders and declarations are no longer
        # active, but their historical events remain in the ledger.
        active_result_ids = (previous_active_results - retired_result_ids) | added_result_ids
        active_result_ids = {
            result_id
            for result_id in active_result_ids
            if (
                self._trial_for_result(initialization, result_id) in active_trial_ids
                or result_id in added_result_ids
            )
        }
        added_diagnostic_result_ids: list[Identifier] = []
        for trial_id in added_trial_ids:
            for candidate in initialization.result_candidates:
                if candidate.trial_id == trial_id and candidate.result_id is not None:
                    active_result_ids.add(candidate.result_id)
            if not any(
                spec.result.trial_id == trial_id
                for spec in initialization.result_specs
            ):
                trial = next(
                    item for item in initialization.trials if item.trial_id == trial_id
                )
                if trial.status == "trial_failed":
                    diagnostic_id = self._diagnostic_result_id(run_id, trial_id)
                    active_result_ids.add(diagnostic_id)
                    added_diagnostic_result_ids.append(diagnostic_id)
                else:
                    active_result_ids.add(self._issued_unresolved_result_id(run_id, trial_id))

        projection = self._projection(ledger, run_id)
        events = self._events_for_run(ledger, run_id)
        invalidated_result_ids: list[Identifier] = []
        diagnostic_result_ids: list[Identifier] = []
        trial_status = {
            trial.trial_id: trial.status for trial in initialization.trials
        }
        for item in projection.results:
            if material_ambiguities:
                # A blocked mapping must not mutate active scope or invalidate
                # downstream work until the input is corrected.
                continue
            if item.result_id not in active_result_ids:
                continue
            trial_id = self._trial_for_result(existing.initialization, item.result_id)
            if not self._result_depends_on_affected_sources(
                item.result_id,
                existing.initialization,
                initialization,
                affected_source_ids,
                affected_trial_ids,
                added_trial_ids,
                retired_trial_ids,
                ledger,
                events,
            ):
                continue
            if trial_status.get(trial_id) == "trial_failed":
                diagnostic_result_ids.append(item.result_id)
            # Invalidate every affected active Result, including PENDING
            # Results that already have partial evidence/answer checkpoints.
            # The lifecycle transition preserves the PENDING coarse state but
            # establishes a durable boundary so those historical checkpoints
            # can never satisfy future work after a Source change/removal.
            invalidated_result_ids.append(item.result_id)

        record = _RunReconciledRecord(
            run_id=run_id,
            proposal=refreshed,
            input_snapshot_hash=current_hash,
            active_trial_ids=tuple(
                sorted(previous_active_trials if material_ambiguities else active_trial_ids)
            ),
            active_result_ids=tuple(
                sorted(previous_active_results if material_ambiguities else active_result_ids)
            ),
            added_trial_ids=() if material_ambiguities else tuple(sorted(added_trial_ids)),
            retired_trial_ids=() if material_ambiguities else tuple(sorted(retired_trial_ids)),
            added_result_ids=() if material_ambiguities else tuple(sorted(added_result_ids)),
            retired_result_ids=(
                () if material_ambiguities else tuple(sorted(retired_result_ids))
            ),
            affected_trial_ids=tuple(sorted(affected_trial_ids)),
            affected_source_ids=tuple(sorted(affected_source_ids)),
            invalidated_result_ids=tuple(sorted(invalidated_result_ids)),
            diagnostic_result_ids=(
                ()
                if material_ambiguities
                else tuple(sorted(set(diagnostic_result_ids).union(added_diagnostic_result_ids)))
            ),
            material_ambiguities=tuple(material_ambiguities),
        )
        self._commit_reconciliation_batch(
            ledger,
            run_id,
            record,
            material_ambiguity=(material_ambiguities[0] if material_ambiguities else None),
            projection=projection,
            invalidated_result_ids=record.invalidated_result_ids,
            diagnostic_result_ids=record.diagnostic_result_ids,
        )
        return True

    @staticmethod
    def _result_definition_ambiguities(
        previous: ProjectInitialization,
        current: ProjectInitialization,
        previous_result_ids: set[Identifier],
        retired_trial_ids: set[Identifier],
        added_trial_ids: set[Identifier],
        *,
        historical_result_specs: dict[Identifier, ResultSpecRevision] | None = None,
    ) -> tuple[str, ...]:
        """Reject unsafe Result declaration edits after confirmation.

        A Result declaration is part of the confirmed meaning, unlike a
        document path or byte-preserving Source move.  Existing declarations
        may be re-inventoried with fresh revision metadata, but changing their
        semantic payload, removing one from an active Trial, or introducing a
        declaration on an already-confirmed Trial cannot be reconciled by
        invalidating evidence alone.  A declaration for a genuinely added
        Trial remains a compatible new work item.
        """

        historical_result_specs = historical_result_specs or {}
        previous_specs = {
            spec.result.result_id: spec for spec in previous.result_specs
        }
        current_specs = {spec.result.result_id: spec for spec in current.result_specs}
        previous_mappings = RunEngine._result_mappings(previous)
        current_mappings = RunEngine._result_mappings(current)
        previous_mappings.update(
            {
                result_id: spec.result.trial_id
                for result_id, spec in historical_result_specs.items()
                if result_id not in previous_mappings
            }
        )
        details: list[str] = []

        for result_id in sorted(previous_result_ids):
            previous_trial = previous_mappings.get(result_id)
            if previous_trial in retired_trial_ids:
                # Retiring a Trial retires its dependent Result history; the
                # declaration need not remain in the current inventory.
                continue
            current_trial = current_mappings.get(result_id)
            if current_trial is None:
                details.append(
                    f"Confirmed Result {result_id} was removed or no longer maps to its Trial."
                )
                continue
            if previous_trial is not None and current_trial != previous_trial:
                details.append(
                    f"Confirmed Result {result_id} was remapped to a different Trial."
                )
                continue
            current_spec = current_specs.get(result_id)
            previous_spec = previous_specs.get(result_id)
            if (
                current_spec is not None
                and previous_spec is not None
                and RunEngine._result_spec_semantics(previous_spec)
                != RunEngine._result_spec_semantics(current_spec)
            ):
                details.append(
                    f"Confirmed Result {result_id} meaning changed after Run confirmation."
                )

        for result_id, current_trial in sorted(current_mappings.items()):
            if result_id in previous_result_ids:
                continue
            if current_trial not in added_trial_ids:
                details.append(
                    f"Result {result_id} was added to an existing confirmed Trial."
                )
        return tuple(details)

    @staticmethod
    def _result_spec_semantics(spec: ResultSpecRevision) -> tuple[Any, Any, str]:
        """Return only stable Result meaning, excluding revision metadata."""

        return (spec.result, spec.estimate, spec.provenance_note)

    def _result_depends_on_affected_sources(
        self,
        result_id: Identifier,
        previous: ProjectInitialization,
        current: ProjectInitialization,
        affected_source_ids: set[Identifier],
        affected_trial_ids: set[Identifier],
        added_trial_ids: set[Identifier],
        retired_trial_ids: set[Identifier],
        ledger: WorkflowLedger,
        events: tuple[WorkflowEvent, ...],
    ) -> bool:
        """Selectively invalidate only Results transitively citing changed Sources."""

        previous_trial_id = self._trial_for_result(previous, result_id)
        current_trial_id = self._trial_for_result(current, result_id)
        trial_id = previous_trial_id or current_trial_id
        if trial_id is None:
            return False
        if trial_id in added_trial_ids or trial_id in retired_trial_ids:
            return True
        if trial_id not in affected_trial_ids:
            return False

        old_sources = self._sources_by_trial(previous).get(trial_id, {})
        new_sources = self._sources_by_trial(current).get(trial_id, {})
        sources = tuple(old_sources.values()) + tuple(
            source
            for source_id, source in new_sources.items()
            if source_id not in old_sources
        )
        locators = {
            spec.result.source_locator
            for spec in (*previous.result_specs, *current.result_specs)
            if spec.result.result_id == result_id
        }
        locators.update(
            candidate.source_locator
            for candidate in (*previous.result_candidates, *current.result_candidates)
            if candidate.result_id == result_id and candidate.source_locator is not None
        )
        if not locators:
            # Post-confirmation Result resolutions are stored as ledger
            # events, not in either fresh ProjectInitialization.  Recover the
            # latest submitted locator so a changed/deleted cited Source still
            # invalidates this Result selectively.
            for event in reversed(events):
                if event.scope != result_id or event.operation not in {
                    "operation:result-discovered",
                    "operation:submit-result-resolution",
                    "operation:run-register-result",
                    "operation:result-spec-superseded",
                }:
                    continue
                payload = self._event_payload(ledger, event)
                raw_spec = payload.get("result_spec")
                if not isinstance(raw_spec, dict):
                    continue
                raw_result = raw_spec.get("result")
                if not isinstance(raw_result, dict):
                    continue
                locator = raw_result.get("source_locator")
                if isinstance(locator, str) and locator:
                    locators.add(locator)
                break
        explicitly_cited = {
            source.source_id
            for source in sources
            if any(
                source.source_id in locator
                or source.relative_path in locator
                or source.title in locator
                for locator in locators
            )
        }
        if explicitly_cited:
            return bool(explicitly_cited.intersection(affected_source_ids))

        # Evidence records retain parse revision IDs.  Those IDs encode the
        # Source identity and let us recover citations even when the Result
        # locator is a free-form page/table description.
        parse_to_source = {
            parse.parse_id: source.source_id
            for source in sources
            for parse in source.parse_records
        }
        evidence_citations: set[Identifier] = set()
        for event in events:
            if event.scope != result_id or event.operation != "operation:submit-domain-evidence":
                continue
            payload = self._event_payload(ledger, event)
            raw_items = payload.get("items", ())
            if not isinstance(raw_items, (list, tuple)):
                continue
            for item in raw_items:
                if isinstance(item, str) and item in parse_to_source:
                    evidence_citations.add(parse_to_source[item])
        if evidence_citations:
            return bool(evidence_citations.intersection(affected_source_ids))

        # A changed/deleted required primary report is the implicit basis for
        # every Result whose free-form locator cannot identify a narrower
        # Source.  Supporting-document additions remain non-transitive unless
        # they are explicitly cited by the Result or its evidence records.
        return any(
            source.source_id in affected_source_ids
            and SourceRole.PRIMARY_REPORT in source.roles
            for source in sources
        )

    @staticmethod
    def _source_semantics_differ(previous: Any, current: Any) -> bool:
        """Compare Source fields that affect downstream evidence meaning.

        ``relative_path`` and generated receipt/parse identifiers are deliberately
        excluded: a path move and a fresh immutable acquisition record do not
        change the cited Source when its bytes and declared semantics remain the
        same.
        """

        return any(
            before != after
            for before, after in (
                (previous.roles, current.roles),
                (previous.criticality, current.criticality),
                (previous.classification, current.classification),
                (previous.availability, current.availability),
                (previous.processing, current.processing),
                (previous.use, current.use),
                (previous.artifact_hash, current.artifact_hash),
                (previous.external_identifiers, current.external_identifiers),
                (previous.coverage, current.coverage),
                (previous.components, current.components),
                (previous.failure_category, current.failure_category),
            )
        )

    @staticmethod
    def _identity_mapping_ambiguities(
        previous: ProjectInitialization,
        current: ProjectInitialization,
    ) -> tuple[str, ...]:
        """Describe Trial/Source replacements that cannot be mapped safely.

        A unique content fingerprint is enough to preserve identity across a
        path move.  Duplicate fingerprints or a simultaneous unmatched removal
        and addition do not provide that guarantee, so reconciliation must stop
        with a material run-wide ambiguity instead of guessing.
        """

        old_trials = {trial.trial_id: trial for trial in previous.trials}
        used_old_trials: set[Identifier] = set()
        old_trial_fingerprints: dict[tuple[str, ...], list[Identifier]] = {}
        for trial in previous.trials:
            fingerprint = tuple(
                sorted(
                    source.artifact_hash
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
            )
            if fingerprint:
                old_trial_fingerprints.setdefault(fingerprint, []).append(trial.trial_id)
        current_trial_fingerprints: dict[tuple[str, ...], list[Identifier]] = {}
        for trial in current.trials:
            fingerprint = tuple(
                sorted(
                    source.artifact_hash
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
            )
            if fingerprint:
                current_trial_fingerprints.setdefault(fingerprint, []).append(trial.trial_id)

        trial_pairs: dict[Identifier, Identifier] = {}
        details: list[str] = []
        for fingerprint, old_ids in old_trial_fingerprints.items():
            current_ids = current_trial_fingerprints.get(fingerprint, [])
            exact_ids = set(old_ids).intersection(current_ids)
            unmatched_old = set(old_ids) - exact_ids
            unmatched_current = set(current_ids) - exact_ids
            if unmatched_old and unmatched_current and (
                len(unmatched_old) > 1 or len(unmatched_current) > 1
            ):
                details.append(
                    "Trial content fingerprints are shared by multiple unmatched "
                    "folders; their identities cannot be mapped safely."
                )
        for trial in current.trials:
            if trial.trial_id in old_trials:
                previous_fingerprint = tuple(
                    sorted(
                        source.artifact_hash
                        for source in old_trials[trial.trial_id].inventory.sources
                        if source.artifact_hash is not None
                    )
                )
                current_fingerprint = tuple(
                    sorted(
                        source.artifact_hash
                        for source in trial.inventory.sources
                        if source.artifact_hash is not None
                    )
                )
                if previous_fingerprint != current_fingerprint and previous_fingerprint:
                    moved_matches = [
                        item
                        for item in current_trial_fingerprints.get(previous_fingerprint, ())
                        if item != trial.trial_id
                    ]
                    if moved_matches:
                        details.append(
                            f"Trial {trial.trial_id} changed while its prior content "
                            "appears in another folder; the path/content identity "
                            "conflict cannot be mapped safely."
                        )
                trial_pairs[trial.trial_id] = trial.trial_id
                used_old_trials.add(trial.trial_id)
                continue
            fingerprint = tuple(
                sorted(
                    source.artifact_hash
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
            )
            candidates = [
                item
                for item in old_trial_fingerprints.get(fingerprint, ())
                if item not in used_old_trials
            ]
            if len(candidates) > 1:
                details.append(
                    f"Trial {trial.trial_id} has a non-unique content fingerprint; "
                    "its identity cannot be mapped safely."
                )
            elif len(candidates) == 1:
                trial_pairs[trial.trial_id] = candidates[0]
                used_old_trials.add(candidates[0])

        old_sources_by_trial = RunEngine._sources_by_trial(previous)
        current_sources_by_trial = RunEngine._sources_by_trial(current)
        for current_trial_id, old_trial_id in trial_pairs.items():
            before = old_sources_by_trial.get(old_trial_id, {})
            after = current_sources_by_trial.get(current_trial_id, {})
            by_path = {source.relative_path: source for source in before.values()}
            by_hash: dict[str, list[Any]] = {}
            for source in before.values():
                if source.artifact_hash is not None:
                    by_hash.setdefault(source.artifact_hash, []).append(source)
            current_by_hash: dict[str, list[Any]] = {}
            for source in after.values():
                if source.artifact_hash is not None:
                    current_by_hash.setdefault(source.artifact_hash, []).append(source)
            for source in after.values():
                historical = by_path.get(source.relative_path)
                if (
                    historical is None
                    or historical.artifact_hash is None
                    or source.artifact_hash is None
                    or historical.artifact_hash == source.artifact_hash
                ):
                    continue
                moved_matches = [
                    item
                    for item in current_by_hash.get(historical.artifact_hash, ())
                    if item.relative_path != source.relative_path
                ]
                if moved_matches:
                    details.append(
                        f"Source {source.relative_path} in {current_trial_id} changed "
                        "while its prior bytes appear at another path; the "
                        "path/content identity conflict cannot be mapped safely."
                    )
            for artifact_hash, current_group in current_by_hash.items():
                old_group = by_hash.get(artifact_hash, [])
                exact_old_ids = {
                    by_path[source.relative_path].source_id
                    for source in current_group
                    if source.relative_path in by_path
                    and by_path[source.relative_path].artifact_hash == artifact_hash
                }
                unmatched_old_count = len(
                    [source for source in old_group if source.source_id not in exact_old_ids]
                )
                unmatched_current_count = len(
                    [source for source in current_group if source.relative_path not in by_path]
                )
                if unmatched_old_count and unmatched_current_count and (
                    unmatched_old_count > 1 or unmatched_current_count > 1
                ):
                    details.append(
                        f"Sources in {current_trial_id} share a duplicate content hash "
                        "across unmatched paths; their identities cannot be mapped safely."
                    )
            used_sources: set[Identifier] = set()
            unmatched_current: list[Any] = []
            ordered_after = sorted(
                after.values(),
                key=lambda source: (source.relative_path not in by_path, source.relative_path),
            )
            for source in ordered_after:
                # A required-source placeholder (for example the synthetic
                # ``.`` descriptor emitted after a primary report is deleted)
                # intentionally has no artifact to map.  It is a Trial failure,
                # not an identity collision.
                if source.artifact_hash is None:
                    continue
                match = by_path.get(source.relative_path)
                if match is not None and match.source_id not in used_sources:
                    used_sources.add(match.source_id)
                    continue
                candidates = [
                    item
                    for item in by_hash.get(source.artifact_hash or "", ())
                    if item.source_id not in used_sources
                ]
                if len(candidates) > 1:
                    details.append(
                        f"Source {source.relative_path} in {current_trial_id} "
                        "matches multiple prior Sources with the same content hash."
                    )
                elif len(candidates) == 1:
                    used_sources.add(candidates[0].source_id)
                else:
                    unmatched_current.append(source)
            unmatched_old = [
                source
                for source in before.values()
                if source.source_id not in used_sources and source.artifact_hash is not None
            ]
            if unmatched_current and unmatched_old:
                details.append(
                    f"Sources in {current_trial_id} were removed and replaced without "
                    "a unique path or content-hash mapping."
                )

        unmatched_old_trials = set(old_trials) - set(trial_pairs.values())
        unmatched_current_trials = {
            trial.trial_id for trial in current.trials
        } - set(trial_pairs)
        if unmatched_old_trials and unmatched_current_trials:
            details.append(
                "Trial folders were removed and added without a unique content-hash "
                "mapping; their identities cannot be mapped safely."
            )

        return tuple(dict.fromkeys(details))

    def _historical_result_specs(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
    ) -> dict[Identifier, ResultSpecRevision]:
        """Recover Result mappings submitted after the initial inventory.

        A Result resolved through a post-confirmation work item is durable in
        the ledger, not in ``ProjectInitialization.result_specs``.  Carry the
        latest such mapping into reconciliation so an unrelated input change
        cannot make an already accepted Result appear to have been removed.
        """

        resolved: dict[Identifier, ResultSpecRevision] = {}
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
                "operation:run-register-result",
                "operation:result-spec-superseded",
            }:
                continue
            try:
                if event.operation in {
                    "operation:run-register-result",
                    "operation:result-spec-superseded",
                }:
                    record = _ResultDiscoveredRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                else:
                    record = _ResultResolutionRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
            except (IndexError, TypeError, ValueError):
                continue
            if record.result_id not in resolved:
                resolved[record.result_id] = record.result_spec
        return resolved

    @staticmethod
    def _result_mappings(
        initialization: ProjectInitialization,
    ) -> dict[Identifier, Identifier]:
        """Return exact Result-to-Trial mappings in one initialization."""

        mappings = {
            spec.result.result_id: spec.result.trial_id
            for spec in initialization.result_specs
        }
        mappings.update(
            {
                candidate.result_id: candidate.trial_id
                for candidate in initialization.result_candidates
                if candidate.status == "resolved" and candidate.result_id is not None
            }
        )
        return mappings

    def _preserve_reconciled_result_mappings(
        self,
        previous: ProjectInitialization,
        current: ProjectInitialization,
        *,
        historical_result_specs: dict[Identifier, ResultSpecRevision],
        previous_active_result_ids: set[Identifier],
        existing_result_ids: set[Identifier],
        run_id: Identifier,
    ) -> ProjectInitialization:
        """Carry accepted candidate and post-confirmation Result identities.

        ``initialize_project`` intentionally regenerates candidate IDs from the
        current Trial identity.  Reconciliation must instead match accepted
        candidates by their remapped Trial and Outcome target, preserving the
        confirmed Result ID and the candidate selection.  Historical Result
        resolutions have no candidate in a fresh inventory, so they receive a
        resolved synthetic candidate until the next declaration refresh.
        """

        current_candidates = list(current.result_candidates)
        current_by_key = {
            (candidate.trial_id, candidate.outcome_target_id): index
            for index, candidate in enumerate(current_candidates)
        }
        current_candidate_ids = {candidate.candidate_id for candidate in current_candidates}
        for previous_candidate in previous.result_candidates:
            if previous_candidate.status != "resolved" or previous_candidate.result_id is None:
                continue
            index = current_by_key.get(
                (previous_candidate.trial_id, previous_candidate.outcome_target_id)
            )
            if index is None:
                continue
            candidate_id = previous_candidate.candidate_id
            if (
                candidate_id in current_candidate_ids
                and current_candidates[index].candidate_id != candidate_id
            ):
                # A collision means the current inventory has two candidates
                # claiming one historical identity; leave it unresolved so
                # the normal Result ambiguity blocks rather than guessing.
                continue
            current_candidates[index] = current_candidates[index].model_copy(
                update={
                    "candidate_id": candidate_id,
                    "result_id": previous_candidate.result_id,
                    "status": "resolved",
                }
            )
            current_candidate_ids.add(candidate_id)

        previous_explicit_ids = {
            spec.result.result_id for spec in previous.result_specs
        }
        current_result_ids = self._result_mappings(
            current.model_copy(update={"result_candidates": tuple(current_candidates)})
        )
        current_trial_ids = {trial.trial_id for trial in current.trials}
        unresolved_result_ids = {
            self._issued_unresolved_result_id(run_id, spec.result.trial_id)
            for spec in historical_result_specs.values()
        }
        for result_id, spec in historical_result_specs.items():
            if result_id in previous_explicit_ids or result_id in current_result_ids:
                continue
            if result_id not in existing_result_ids and result_id not in previous_active_result_ids:
                if result_id not in unresolved_result_ids:
                    continue
            if spec.result.trial_id not in current_trial_ids:
                continue
            digest = self._digest(f"{run_id}|historical-result-candidate|{result_id}")
            candidate_id = f"result-candidate:historical-{digest}"
            if candidate_id in current_candidate_ids:
                continue
            current_candidates.append(
                ResultCandidate(
                    candidate_id=candidate_id,
                    trial_id=spec.result.trial_id,
                    label=(
                        f"{spec.result.outcome_construct} at {spec.result.time_point} "
                        f"({spec.result.effect_measure}, {spec.result.analysis_population})"
                    ),
                    result_id=result_id,
                    source_locator=spec.result.source_locator,
                    status="resolved",
                )
            )
            current_candidate_ids.add(candidate_id)
            current_result_ids[result_id] = spec.result.trial_id
        return current.model_copy(update={"result_candidates": tuple(current_candidates)})

    @staticmethod
    def _sources_by_trial(
        initialization: ProjectInitialization,
    ) -> dict[Identifier, dict[Identifier, Any]]:
        return {
            trial.trial_id: {
                source.source_id: source for source in trial.inventory.sources
            }
            for trial in initialization.trials
        }

    @staticmethod
    def _input_trial_ids(root: Path) -> set[Identifier]:
        input_root = root / "input"
        if not input_root.is_dir():
            return set()
        return {
            f"trial:{re.sub(r'[^a-z0-9._~-]+', '-', path.name.lower()).strip('-') or 'unnamed'}"
            for path in input_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        }

    @staticmethod
    def _trial_for_result(
        initialization: ProjectInitialization, result_id: Identifier
    ) -> Identifier | None:
        for spec in initialization.result_specs:
            if spec.result.result_id == result_id:
                return spec.result.trial_id
        for candidate in initialization.result_candidates:
            if candidate.result_id == result_id:
                return candidate.trial_id
        return None

    def _commit_reconciliation_batch(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        record: _RunReconciledRecord,
        *,
        projection: LifecycleProjection,
        material_ambiguity: RunProposalAmbiguity | None = None,
        invalidated_result_ids: tuple[Identifier, ...] = (),
        diagnostic_result_ids: tuple[Identifier, ...] = (),
    ) -> None:
        now = datetime.now(UTC)
        transitions: list[Transition] = [
            self._transition(
                scope=run_id,
                operation="operation:run-reconciled",
                operation_key=(
                    "idempotency:run-reconciled-"
                    f"{self._digest(f'{run_id}|{record.input_snapshot_hash}')}"
                ),
                entity_id=f"run-reconciliation:{self._digest(f'{run_id}|{record.input_snapshot_hash}')}",
                revision_id=f"revision:run-reconciliation-{self._digest(f'{run_id}|{record.input_snapshot_hash}')}",
                artifact=record,
                checkpoint="checkpoint:run-reconciled",
                outcome=(
                    WorkflowEventOutcome.WORK_REQUIRED
                    if material_ambiguity is not None
                    else WorkflowEventOutcome.COMPLETED
                ),
                observed_at=now,
            )
        ]
        recomputable_result_ids = tuple(
            result_id
            for result_id in invalidated_result_ids
            if result_id not in diagnostic_result_ids
        )
        reopen_run = projection.run_state is RunState.COMPLETE and (
            bool(recomputable_result_ids)
            or bool(record.added_result_ids)
            or bool(record.added_trial_ids)
        )
        if reopen_run and material_ambiguity is None:
            suffix = self._digest(
                f"{run_id}|{record.input_snapshot_hash}|reopened|"
                f"{','.join(sorted(recomputable_result_ids))}|"
                f"{','.join(sorted(record.added_result_ids))}"
            )
            transitions.append(
                self._transition(
                    scope=run_id,
                    operation="operation:run-reopened",
                    operation_key=f"idempotency:reconcile-reopened-{suffix}",
                    entity_id=f"run-reconciliation-reopened:{suffix}",
                    revision_id=f"revision:run-reconciliation-reopened-{suffix}",
                    artifact=_RunReopenedRecord(
                        run_id=run_id,
                        input_snapshot_hash=record.input_snapshot_hash,
                        invalidated_result_ids=tuple(sorted(recomputable_result_ids)),
                        added_result_ids=tuple(sorted(record.added_result_ids)),
                    ),
                    checkpoint="checkpoint:run-reopened",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        for result_id in invalidated_result_ids:
            trial_id = self._trial_for_result(record.proposal.initialization, result_id)
            if trial_id is None:
                trial_id = self._trial_for_result(
                    record.proposal.initialization, result_id
                )
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:result-invalidated",
                    operation_key=(
                        f"idempotency:result-invalidated-"
                        f"{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}"
                    ),
                    entity_id=f"result-invalidation:{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}",
                    revision_id=f"revision:result-invalidation-{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}",
                    artifact=_ResultInvalidatedRecord(
                        run_id=run_id,
                        result_id=result_id,
                        reason="A dependent Trial or Source input changed or was removed.",
                        affected_trial_id=trial_id or "trial:unknown",
                        affected_source_ids=record.affected_source_ids,
                        input_snapshot_hash=record.input_snapshot_hash,
                    ),
                    checkpoint=f"checkpoint:result-invalidated-{result_id.removeprefix('result:')}",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        # Register newly added explicit Results before their diagnostic
        # terminal transition.  Added Trial failures without a declared
        # Result receive a generated diagnostic Result identity here as well,
        # avoiding an impossible Result-resolution work item.
        existing_result_ids = {item.result_id for item in projection.results}
        diagnostic_trials = {
            self._diagnostic_result_id(run_id, trial.trial_id): trial
            for trial in record.proposal.initialization.trials
            if trial.status == "trial_failed"
        }
        for result_id in record.added_result_ids:
            if result_id in existing_result_ids:
                continue
            result_spec = next(
                (
                    spec
                    for spec in record.proposal.initialization.result_specs
                    if spec.result.result_id == result_id
                ),
                None,
            )
            if result_spec is None:
                continue
            suffix = self._digest(f"{run_id}|{result_id}|reconciled")
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:run-register-result",
                    operation_key=f"idempotency:reconcile-register-result-{suffix}",
                    entity_id=f"run-reconciled-result:{suffix}",
                    revision_id=f"revision:run-reconciled-result-{suffix}",
                    artifact=_ResultDiscoveredRecord(
                        run_id=run_id,
                        result_id=result_id,
                        result_spec=result_spec,
                    ),
                    checkpoint=f"checkpoint:result-{result_id.removeprefix('result:')}",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                )
            )
            existing_result_ids.add(result_id)
        for result_id, trial in diagnostic_trials.items():
            if result_id in existing_result_ids or result_id not in diagnostic_result_ids:
                continue
            suffix = self._digest(f"{run_id}|{result_id}|diagnostic")
            reason = (
                trial.failure.detail
                if trial.failure is not None
                else "Trial-specific initialization failed"
            )
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:run-register-diagnostic-result",
                    operation_key=f"idempotency:reconcile-register-diagnostic-{suffix}",
                    entity_id=f"diagnostic-result:{suffix}",
                    revision_id=f"revision:diagnostic-result-{suffix}",
                    artifact=_DiagnosticResultDiscoveredRecord(
                        run_id=run_id,
                        result_id=result_id,
                        trial_id=trial.trial_id,
                        reason=reason,
                    ),
                    checkpoint=f"checkpoint:diagnostic-result-{result_id.removeprefix('result:')}",
                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                    observed_at=now,
                )
            )
            existing_result_ids.add(result_id)
        for result_id in diagnostic_result_ids:
            trial_id = self._trial_for_result(record.proposal.initialization, result_id)
            if trial_id is None:
                diagnostic_trial = diagnostic_trials.get(result_id)
                trial_id = diagnostic_trial.trial_id if diagnostic_trial is not None else None
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:result-diagnostic-ready",
                    operation_key=(
                        f"idempotency:reconcile-diagnostic-"
                        f"{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}"
                    ),
                    entity_id=f"result-reconciliation-diagnostic:{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}",
                    revision_id=f"revision:result-reconciliation-diagnostic-{self._digest(f'{run_id}|{result_id}|{record.input_snapshot_hash}')}",
                    artifact=_ResultDiagnosticRecord(
                        run_id=run_id,
                        result_id=result_id,
                        trial_id=trial_id or "trial:unknown",
                        reason="A required Trial Source became unavailable or unreadable.",
                    ),
                    checkpoint=f"checkpoint:result-diagnostic-{result_id.removeprefix('result:')}",
                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                    observed_at=now,
                )
            )
        if material_ambiguity is not None and projection.run_state is not RunState.BLOCKED:
            suffix = self._digest(f"{run_id}|{record.input_snapshot_hash}|blocked")
            transitions.append(
                self._transition(
                    scope=run_id,
                    operation="operation:run-blocked",
                    operation_key=f"idempotency:reconcile-blocked-{suffix}",
                    entity_id=f"run-reconciliation-blocker:{suffix}",
                    revision_id=f"revision:run-reconciliation-blocker-{suffix}",
                    artifact=_RunBlockedRecord(
                        run_id=run_id,
                        reason=material_ambiguity.detail,
                        recovery=(
                            "Correct or remove the incompatible input and continue the Run.",
                            "Start a new Run explicitly if the confirmed meaning must change.",
                        ),
                    ),
                    checkpoint="checkpoint:run-blocked",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        elif material_ambiguity is None and projection.run_state is RunState.BLOCKED:
            suffix = self._digest(f"{run_id}|{record.input_snapshot_hash}|unblocked")
            transitions.append(
                self._transition(
                    scope=run_id,
                    operation="operation:run-unblocked",
                    operation_key=f"idempotency:reconcile-unblocked-{suffix}",
                    entity_id=f"run-reconciliation-unblocker:{suffix}",
                    revision_id=f"revision:run-reconciliation-unblocker-{suffix}",
                    artifact=_RunUnblockedRecord(
                        run_id=run_id,
                        input_snapshot_hash=record.input_snapshot_hash,
                    ),
                    checkpoint="checkpoint:run-unblocked",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        lease = self._acquire_lease(ledger, now)
        ledger.commit_batch(tuple(transitions), lease, now=now)

    @staticmethod
    def _remap_initialization_identities(
        previous: ProjectInitialization,
        current: ProjectInitialization,
    ) -> ProjectInitialization:
        """Preserve Trial/Source IDs across content-preserving path moves."""

        old_trials = {trial.trial_id: trial for trial in previous.trials}
        used_old: set[Identifier] = set()
        trial_map: dict[Identifier, Identifier] = {}
        old_fingerprints: dict[tuple[str, ...], list[Identifier]] = {}
        for trial in previous.trials:
            fingerprint = tuple(
                sorted(
                    source.artifact_hash
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
            )
            if fingerprint:
                old_fingerprints.setdefault(fingerprint, []).append(trial.trial_id)
        for trial in current.trials:
            if trial.trial_id in old_trials:
                trial_map[trial.trial_id] = trial.trial_id
                used_old.add(trial.trial_id)
                continue
            fingerprint = tuple(
                sorted(
                    source.artifact_hash
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
            )
            candidates = [
                item
                for item in old_fingerprints.get(fingerprint, ())
                if item not in used_old
            ]
            if len(candidates) == 1:
                trial_map[trial.trial_id] = candidates[0]
                used_old.add(candidates[0])

        remapped_trials: list[TrialInitialization] = []
        source_maps: dict[Identifier, dict[Identifier, Identifier]] = {}
        for trial in current.trials:
            trial_id = trial_map.get(trial.trial_id, trial.trial_id)
            old = old_trials.get(trial_id)
            old_sources = tuple(old.inventory.sources) if old is not None else ()
            by_path = {source.relative_path: source for source in old_sources}
            by_hash: dict[str, list[Any]] = {}
            for source in old_sources:
                if source.artifact_hash is not None:
                    by_hash.setdefault(source.artifact_hash, []).append(source)
            used_sources: set[Identifier] = set()
            # Provisional IDs are ordinal (``source:<trial>-<index>``), so an
            # added document can legitimately reuse an ID that belongs to a
            # historical document whose path still exists.  Keep every
            # historical ID reserved and allocate a deterministic replacement
            # for such an unmatched document rather than emitting duplicate
            # canonical unit IDs during evidence indexing.
            allocated_source_ids: set[Identifier] = {
                source.source_id for source in old_sources
            }
            remapped_by_current_id: dict[Identifier, Any] = {}
            source_map: dict[Identifier, Identifier] = {}
            ordered_sources = sorted(
                trial.inventory.sources,
                key=lambda source: (
                    source.relative_path not in by_path,
                    source.relative_path,
                ),
            )
            for source in ordered_sources:
                match = by_path.get(source.relative_path)
                if match is None or match.source_id in used_sources:
                    hashed = [
                        item
                        for item in by_hash.get(source.artifact_hash or "", ())
                        if item.source_id not in used_sources
                    ]
                    match = hashed[0] if len(hashed) == 1 else None
                if match is None:
                    assigned = source
                    if source.source_id in allocated_source_ids:
                        digest = hashlib.sha256(
                            (
                                f"{trial_id}|{source.relative_path}|"
                                f"{source.artifact_hash or ''}"
                            ).encode()
                        ).hexdigest()[:24]
                        candidate: Identifier = f"source:reconciled-{digest}"
                        counter = 1
                        while candidate in allocated_source_ids:
                            candidate = f"source:reconciled-{digest}-{counter}"
                            counter += 1
                        assigned = source.model_copy(
                            update={
                                "source_id": candidate,
                                "parse_records": tuple(
                                    item.model_copy(update={"source_id": candidate})
                                    for item in source.parse_records
                                ),
                            }
                        )
                    allocated_source_ids.add(assigned.source_id)
                    remapped_by_current_id[source.source_id] = assigned
                    continue
                used_sources.add(match.source_id)
                allocated_source_ids.add(match.source_id)
                source_map[source.source_id] = match.source_id
                parse_records = source.parse_records
                if source.artifact_hash == match.artifact_hash and match.parse_records:
                    parse_records = match.parse_records
                else:
                    parse_records = tuple(
                        item.model_copy(update={"source_id": match.source_id})
                        for item in parse_records
                    )
                remapped_by_current_id[source.source_id] = source.model_copy(
                    update={"source_id": match.source_id, "parse_records": parse_records}
                )
            source_maps[trial_id] = source_map
            # Restore discovery order after matching exact paths first.  The
            # ordering is part of the user-facing proposal even though it must
            # not influence identity allocation.
            remapped_sources = tuple(
                remapped_by_current_id[source.source_id]
                for source in trial.inventory.sources
            )
            inventory = trial.inventory.model_copy(
                update={"trial_id": trial_id, "sources": remapped_sources}
            )
            remapped_trials.append(
                trial.model_copy(
                    update={
                        "trial_id": trial_id,
                        "inventory": inventory,
                        "registry_candidates": tuple(
                            item.model_copy(update={"trial_id": trial_id})
                            for item in trial.registry_candidates
                        ),
                    }
                )
            )
        remapped_specs = tuple(
            spec.model_copy(
                update={
                    "result": spec.result.model_copy(
                        update={
                            "trial_id": trial_map.get(
                                spec.result.trial_id, spec.result.trial_id
                            )
                        }
                    )
                }
            )
            for spec in current.result_specs
        )
        remapped_candidates = tuple(
            item.model_copy(update={"trial_id": trial_map.get(item.trial_id, item.trial_id)})
            for item in current.result_candidates
        )
        remapped_findings = tuple(
            item.model_copy(update={"trial_id": trial_map.get(item.trial_id, item.trial_id)})
            for item in current.review_findings
        )
        return current.model_copy(
            update={
                "trials": tuple(remapped_trials),
                "result_specs": remapped_specs,
                "result_candidates": remapped_candidates,
                "review_findings": remapped_findings,
                "registry_candidates": tuple(
                    item.model_copy(
                        update={
                            "trial_id": trial_map.get(item.trial_id, item.trial_id)
                        }
                    )
                    for item in current.registry_candidates
                ),
            }
        )

    def _latest_proposal(self, ledger: WorkflowLedger, run_id: Identifier) -> RunProposal:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation in {
                "operation:run-proposal-submitted",
                "operation:run-reconciled",
            }:
                if event.operation == "operation:run-reconciled":
                    return _RunReconciledRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    ).proposal
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
            if event.operation in {
                "operation:run-proposal-submitted",
                "operation:run-reconciled",
            }:
                if event.operation == "operation:run-reconciled":
                    proposal = _RunReconciledRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    ).proposal
                else:
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
    def _failed_result_ids(
        proposal: RunProposal,
        *,
        result_ids: set[Identifier] | None = None,
    ) -> frozenset[Identifier]:
        failed_trials = {
            trial.trial_id
            for trial in proposal.initialization.trials
            if trial.status == "trial_failed"
        }
        return frozenset(
            spec.result.result_id
            for spec in proposal.initialization.result_specs
            if spec.result.trial_id in failed_trials
            and (result_ids is None or spec.result.result_id in result_ids)
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
            "conflicting_registry_identifiers",
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
                material=False,
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
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"project input escapes project root: {path}")
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] in {".rob2", "output", "__pycache__"}:
                continue
            if path.is_dir():
                # Directory identities matter even when a newly added Trial
                # is still empty (or a Trial folder is renamed).  Include a
                # stable marker so reconciliation cannot mistake that change
                # for an identical byte-only scan.
                entries.append((relative.as_posix() + "/", "directory"))
                continue
            if not path.is_file():
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
        error: OperationError | None = None,
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
            error=error,
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

    @staticmethod
    def _validate_project_root_layout(root: Path) -> None:
        for path in (
            root / "rob2.yaml",
            root / "input",
            root / "output",
            root / ".rob2",
        ):
            if path.is_symlink():
                raise ValueError(f"project path symlinks are not permitted: {path}")
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"project path escapes project root: {path}")
            if path.name == "rob2.yaml":
                if path.exists() and not path.is_file():
                    raise ValueError(f"project configuration must be a file: {path}")
            elif path.exists() and not path.is_dir():
                raise ValueError(f"project layout path must be a directory: {path}")
            if not path.is_dir():
                continue
            for nested in path.rglob("*"):
                if nested.is_symlink():
                    raise ValueError(
                        f"project path symlinks are not permitted: {nested}"
                    )
                if not nested.resolve().is_relative_to(root):
                    raise ValueError(f"project path escapes project root: {nested}")

    def _prepare_root_configuration_error(
        self,
        root: Path,
        error: ValueError,
    ) -> PrepareRunResponse:
        run_id = f"run:rejected-{self._digest(str(root))}"
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor="ledger:refused",
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_BLOCKED,
            committed=False,
            next_permitted_action=RunOperation.PREPARE_RUN,
            run_id=run_id,
            run_state=RunState.BLOCKED,
            error=OperationError(
                code="invalid_configuration",
                detail=str(error),
                recovery=(
                    "Remove symlinks from the project root and keep input, output, "
                    ".rob2, and rob2.yaml confined.",
                    "Retry prepare_run after correcting the project layout.",
                ),
            ),
        )

    def _prepare_authorization_error(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal: RunProposal,
        *,
        run_state: RunState = RunState.AWAITING_CONFIRMATION,
    ) -> PrepareRunResponse:
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_BLOCKED,
            committed=False,
            next_permitted_action=RunOperation.PREPARE_RUN,
            run_id=run_id,
            run_state=run_state,
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
