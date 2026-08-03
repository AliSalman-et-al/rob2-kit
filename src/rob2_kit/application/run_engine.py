"""Typed host-neutral application boundary for lean-v1 Runs."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image, ImageDraw

from rob2_kit.application.contracts import (
    ConfirmedRunDefinition,
    ConfirmRunDefinitionRequest,
    ConfirmRunDefinitionResponse,
    ContinueRunRequest,
    ContinueRunResponse,
    DomainContextPack,
    EvidenceConsiderationInput,
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
    RunProgress,
    RunProposal,
    RunProposalAmbiguity,
    RunProposalSelection,
    RunStatusRequest,
    RunStatusResponse,
    SearchEvidenceRequest,
    SearchEvidenceResponse,
    SourceContextSummary,
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
    TrialContextSummary,
    WorkContext,
    WorkflowCondition,
    WorkItem,
    WorkToken,
)
from rob2_kit.application.determinism import QualificationDeterminism
from rob2_kit.application.lifecycle import (
    LifecycleIntegrityError,
    LifecycleProjection,
    ResultState,
    RunState,
    derive_lifecycle,
)
from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    DecisionTrace,
    JudgmentLevel,
    SQAnswerRevision,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import (
    ConsiderationDisposition,
    EvidenceBundle,
    EvidenceCandidateDispositionRecord,
    EvidenceClaim,
    EvidenceConsideration,
    EvidenceConsiderationManifest,
    EvidenceCoverageReceiptRecord,
    VisualTranscription,
)
from rob2_kit.domain.releases import PolicyKind, PolicyRelease
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import (
    SCHEMA_VERSION,
    Actor,
    ActorKind,
    ContentHash,
    Dependency,
    FrozenModel,
    Identifier,
    RecordReference,
    Revision,
    Supersession,
)
from rob2_kit.domain.sources import SourceInventoryRevision, SourceRole
from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.visual import VisualCandidate, VisualInspectionPolicy
from rob2_kit.evidence.workflow import ExecutedSearchQuery, SearchCoverageReceipt
from rob2_kit.ingestion.project import (
    DocumentParser,
    LiteParseAdapter,
    ProjectInitialization,
    ResultCandidate,
    TrialInitialization,
    _parse_index_pages,
    _parse_source,
    _registry_source_descriptor,
    initialize_project,
)
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import load_guidance_pack, load_logic_pack
from rob2_kit.registry import ClinicalTrialsGovAdapter, RegistryAcquisitionStatus, RegistryPolicy
from rob2_kit.reports import (
    AssessmentView,
    DiagnosticReportProjector,
    DiagnosticView,
    DomainView,
    EvidenceView,
    ReportProjector,
    RunIndexProjector,
    RunIndexResultView,
    RunIndexView,
    SignalingQuestionView,
    VisualCitationView,
)
from rob2_kit.reports.archives import ArchiveBuilder, verify_archive
from rob2_kit.storage import (
    ArtifactStore,
    CommitResult,
    DependencyInput,
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

# The host can provide a richer Actor on answer/evidence submissions.  When a
# thin MCP client omits it, this stable agent identity still records that the
# submission was authored by an assessment agent rather than silently by a
# human or by an un-attributed process.
ASSESSMENT_AGENT_ACTOR = Actor(
    kind=ActorKind.AGENT,
    actor_id="actor:assessment-agent",
    display_name="rob2-kit assessment agent",
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
    execution_contract: _ExecutionContract


class _ExecutionContract(FrozenModel):
    """Installed engine, schema, pack, policy, and skill identities for one attempt."""

    identity: ContentHash
    components: dict[str, ContentHash]


class _PreparationAttemptSupersededRecord(FrozenModel):
    run_id: Identifier
    previous_contract: _ExecutionContract
    execution_contract: _ExecutionContract
    changed_components: tuple[str, ...]
    invalidated_result_ids: tuple[Identifier, ...] = ()


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
    report_root: str | None = None
    artifact_names: tuple[str, ...] = ()


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
    work_token: WorkToken
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
    evidence_bundles: tuple[RecordReference, ...] = ()
    consideration_manifests: tuple[RecordReference, ...] = ()
    coverage_receipts: tuple[RecordReference, ...] = ()
    candidate_dispositions: tuple[EvidenceConsiderationInput, ...] = ()
    project_rules: tuple[RecordReference, ...] = ()
    submission: SubmitDomainEvidenceRequest


class _DomainEvidenceDispositionRecord(FrozenModel):
    """Immutable pre-freeze account of all candidate dispositions."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    items: tuple[RecordReference, ...] = ()
    dispositions: tuple[EvidenceConsiderationInput, ...] = ()


class _DomainCoverageReceiptRecord(FrozenModel):
    """Immutable wrapper that lets bundles bind otherwise frozen receipts."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    receipts: tuple[SearchCoverageReceipt, ...] = ()


class _DomainAnswersRecord(FrozenModel):
    """Normalized signaling-question answers for one Result × domain."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    answers: dict[Identifier, str]
    rationales: dict[Identifier, str]
    project_rules: tuple[RecordReference, ...] = ()
    answer_revisions: tuple[RecordReference, ...] = ()
    submission: SubmitDomainAnswersRequest


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
        determinism: QualificationDeterminism | None = None,
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
        self._determinism = determinism

    def _now(self) -> datetime:
        return self._determinism.now() if self._determinism is not None else datetime.now(UTC)

    def _ledger(self, path: Path, artifacts: ArtifactStore) -> WorkflowLedger:
        return WorkflowLedger(
            path,
            artifacts,
            now=self._now,
            event_identifiers=(
                self._determinism.event_identifiers if self._determinism is not None else None
            ),
        )

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
            ledger = self._ledger(ledger_path, artifacts)
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
            self._reconcile_execution_contract(ledger, current)
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
                        now=self._now,
                    )
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                existing = self._latest_proposal(ledger, current.run_id)
                try:
                    inputs_changed = self._input_snapshot_hash(root) != existing.input_snapshot_hash
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                if inputs_changed:
                    self._index_initial_evidence(root, initialization)
                    refreshed = self._proposal(current.run_id, initialization)
                    now = self._now()
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
                            prior_spec = self._result_spec_for(ledger, current.run_id, result_id)
                            if prior_spec is not None and prior_spec != result_spec:
                                supersede_suffix = self._digest(
                                    f"{current.run_id}|{result_id}|{result_spec.model_dump_json()}"
                                )
                                transitions.append(
                                    self._transition(
                                        scope=result_id,
                                        operation="operation:result-spec-superseded",
                                        operation_key=(
                                            f"idempotency:result-spec-superseded-{supersede_suffix}"
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
                        diagnostic_suffix = self._digest(f"{current.run_id}|{result_id}|diagnostic")
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
                    changed = (
                        self._input_snapshot_hash(root)
                        != self._latest_proposal(ledger, current.run_id).input_snapshot_hash
                    )
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
                    return self._prepare_authorization_error(ledger, current.run_id, existing)
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
                now=self._now,
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
        now = self._now()
        prepared = _PreparedRunRecord(
            run_id=run_id,
            proposal=proposal,
            prepared_at=now,
            execution_contract=self._installed_execution_contract(),
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
                if item.result_id
                in self._result_ids(
                    ledger,
                    request.run_id,
                    self._latest_proposal(ledger, request.run_id),
                )
            ),
            progress=self._run_progress(ledger, request.run_id, projection),
        )

    def continue_run(self, request: ContinueRunRequest) -> ContinueRunResponse:
        try:
            ledger = self._bound_ledger(request.run_id)
            current = self._current_prepared_record(ledger)
            if current is not None and current.run_id == request.run_id:
                self._reconcile_execution_contract(ledger, current)
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
            now = self._now()
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
                operation_id=self._read_operation_id(RunOperation.GET_WORK_CONTEXT, request.run_id),
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
        if projection.run_state is RunState.ASSESSING and (
            expected is None or expected.work_token != request.work_token
        ):
            return GetWorkContextResponse(
                operation_id=self._read_operation_id(RunOperation.GET_WORK_CONTEXT, request.run_id),
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
        scoped_trial_id = (
            None if is_global_source_work else (trial.trial_id if trial is not None else trial_id)
        )
        sources = (
            tuple(
                source
                for item in proposal.initialization.trials
                if item.status == "inventory_ready" and item.trial_id in selected_trial_ids
                for source in item.inventory.sources
                if SourceRole.REGISTRY_CURRENT not in source.roles
            )
            if is_global_source_work
            else tuple(trial.inventory.sources)
            if trial is not None
            else ()
        )
        context = WorkContext(
            work_item=work_item,
            trial=(
                TrialContextSummary(
                    trial_id=trial.trial_id,
                    status=trial.status,
                    inventory_id=trial.inventory.inventory_id,
                    coverage_limitations=trial.inventory.coverage_limitations,
                )
                if trial is not None
                else None
            ),
            result_spec=result_spec,
            sources=tuple(SourceContextSummary.from_descriptor(source) for source in sources),
            detailed_sources=sources if request.include_source_details else (),
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
            domain_context=(
                self._domain_context_pack(
                    ledger,
                    request.run_id,
                    work_item,
                    trial=trial,
                )
                if work_item.domain_id is not None and work_item.result_id is not None
                else None
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
            if existing_record.proposal.selections != request.selections or any(
                existing_ambiguities.get(item.ambiguity_id) != item
                for item in requested_ambiguities
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
                        recovery=("Discard the stale proposal and call prepare_run again.",),
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
                    recovery=("Discard the unknown proposal token and call prepare_run again.",),
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
        now = self._now()
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
                        recovery=("Discard the stale proposal and call prepare_run again.",),
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
                    recovery=("Discard the unknown proposal token and call prepare_run again.",),
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
            tuple(item.trial_id for item in accepted) if proposal.selections else proposal.trial_ids
        )
        result_candidates = {item.candidate_id: item for item in proposal.result_candidates}
        selected_candidate_items = tuple(
            result_candidates[item.result_candidate_id]
            for item in accepted
            if item.result_candidate_id is not None
        )
        if any(
            item.status != "resolved" or item.result_id is None for item in selected_candidate_items
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
                    recovery=("Submit an exact Trial-specific Result mapping for the candidate.",),
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
            item.outcome_target_id for item in accepted if item.outcome_target_id is not None
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
                item.target_id for item in proposal.initialization.manifest.outcome_target_specs
            )
        )
        now = self._now()
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
            policy=request.policy,
            cursor=request.cursor,
            broad_query_justification=request.broad_query_justification,
        )
        executed_query = None
        if request.pass_kind is not None:
            executed_query = ExecutedSearchQuery(
                sq_id=request.sq_id,
                query=request.query,
                query_hash=page.query_hash,
                pass_kind=request.pass_kind,
                seed_family=request.seed_family,
                returned_unit_ids=tuple(hit.unit.unit_id for hit in page.hits),
                traversal_complete=page.next_cursor is None,
                broad_query=page.preview.requires_broad_query_justification,
                broad_query_justification=request.broad_query_justification,
                snapshot_hash=page.snapshot_hash,
                policy_id=page.policy_id,
                policy_hash=page.policy_hash,
            )
        return SearchEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.SEARCH_EVIDENCE, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id or request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            page=page,
            executed_query=executed_query,
        )

    def read_evidence(self, request: ReadEvidenceRequest) -> ReadEvidenceResponse:
        ledger = self._bound_ledger(request.run_id)
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        context = index.read_context(
            request.unit_id,
            neighbor_limit=request.neighbor_limit,
            character_target=request.context_character_target,
        )
        return ReadEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.READ_EVIDENCE, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id or request.run_id,),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            unit=context.unit,
            context=context,
        )

    def inspect_visual_candidate(
        self, request: InspectVisualCandidateRequest
    ) -> InspectVisualCandidateResponse:
        ledger = self._bound_ledger(request.run_id)
        candidate = next(
            (
                candidate
                for candidate in self._visual_candidates(
                    ledger,
                    request.run_id,
                    result_id=request.result_id,
                )
                if candidate.candidate_id == request.candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("Visual candidate identifier was not issued by this Run")
        policy = VisualInspectionPolicy()
        render = (
            policy.initial_request(candidate)
            if request.current_render is None
            else policy.escalate(
                candidate,
                request.current_render,
                still_ambiguous=request.still_ambiguous,
            )
            or request.current_render
        )
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
            render=render,
        )

    def submit_source_classification(
        self, request: SubmitSourceClassificationRequest
    ) -> SubmitSourceClassificationResponse:
        bound_ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            bound_ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:submit-source-classification"},
        )
        if existing is not None:
            if (
                SubmitSourceClassificationRequest.model_validate_json(
                    bound_ledger.artifacts.read(existing.output_revision_hashes[0])
                )
                != request
            ):
                return SubmitSourceClassificationResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(bound_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_SOURCE_CLASSIFICATION,
                        bound_ledger,
                    )
                )
            projection = self._projection(bound_ledger, request.run_id)
            return SubmitSourceClassificationResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(bound_ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_permitted_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_SOURCE_CLASSIFICATION,
                request.idempotency_key,
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
            raise ValueError("Source classification must include every inventory-ready source")
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
        bound_ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            bound_ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:submit-result-resolution", "operation:result-discovered"},
        )
        if existing is not None:
            record = _ResultResolutionRecord.model_validate_json(
                bound_ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if (
                record.work_token != request.work_token
                or record.result_spec.result != request.result
                or record.result_spec.estimate != request.estimate
                or record.result_spec.provenance_note != request.provenance_note
            ):
                return SubmitResultResolutionResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(bound_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_RESULT_RESOLUTION,
                        bound_ledger,
                        result_id=request.result.result_id,
                    )
                )
            projection = self._projection(bound_ledger, request.run_id)
            return SubmitResultResolutionResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(bound_ledger.events())}",
                affected_scope=(request.result.result_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_permitted_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                result_id=request.result.result_id,
                result_state=self._result_state(projection, request.result.result_id),
                result_spec=record.result_spec,
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_RESULT_RESOLUTION,
                request.idempotency_key,
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
            now = self._now()
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
                work_token=request.work_token,
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
        original_request = request
        bound_ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            bound_ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:submit-domain-evidence"},
        )
        if existing is not None:
            record = _DomainEvidenceRecord.model_validate_json(
                bound_ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if record.submission != original_request:
                return SubmitDomainEvidenceResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(bound_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_DOMAIN_EVIDENCE,
                        bound_ledger,
                        result_id=request.result_id,
                        domain_id=request.domain_id,
                    ),
                    domain_id=request.domain_id,
                )
            projection = self._projection(bound_ledger, request.run_id)
            return SubmitDomainEvidenceResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(bound_ledger.events())}",
                affected_scope=(request.result_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_permitted_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                result_id=request.result_id,
                result_state=self._result_state(projection, request.result_id),
                domain_id=request.domain_id,
                evidence_bundles=record.evidence_bundles,
                consideration_manifests=record.consideration_manifests,
                coverage_receipts=record.coverage_receipts,
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_DOMAIN_EVIDENCE,
                request.idempotency_key,
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
        if request.passages:
            self._validate_domain_evidence_submission(
                ledger, request.model_copy(update={"passages": ()})
            )
            request = self._resolve_evidence_passages(ledger, request)
        self._validate_domain_evidence_submission(ledger, request)
        evidence_bundles, manifests, receipts = self._freeze_domain_evidence(ledger, request)
        normalized = _DomainEvidenceRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            items=tuple(item.revision_id for item in request.items),
            coverage_state=request.coverage_state.value,
            coverage_limitations=request.coverage_limitations,
            no_information_basis=request.no_information_basis,
            conflicts=request.conflicts,
            evidence_bundles=evidence_bundles,
            consideration_manifests=manifests,
            coverage_receipts=receipts,
            candidate_dispositions=request.candidate_dispositions,
            project_rules=request.project_rules,
            submission=original_request,
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
            evidence_bundles=evidence_bundles,
            consideration_manifests=manifests,
            coverage_receipts=receipts,
        )

    def _resolve_evidence_passages(
        self,
        ledger: WorkflowLedger,
        request: SubmitDomainEvidenceRequest,
    ) -> SubmitDomainEvidenceRequest:
        """Freeze engine-issued canonical spans into immutable Evidence claims."""

        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        actor = request.actor or ASSESSMENT_AGENT_ACTOR
        proposal = self._latest_proposal(ledger, request.run_id)
        result_spec = self._result_spec_for(ledger, request.run_id, request.result_id)
        if result_spec is None:
            raise ValueError("passage submission requires a resolved Result")
        sources = {
            source.source_id: source
            for trial in proposal.initialization.trials
            if trial.trial_id == result_spec.result.trial_id and trial.inventory is not None
            for source in trial.inventory.sources
        }
        item_refs: list[RecordReference] = []
        domain = next(item for item in self._logic_pack().domains if item.id == request.domain_id)
        evidence_by_question: dict[Identifier, list[RecordReference]] = {
            question_id: [] for question_id in domain.question_ids
        }
        dispositions: list[EvidenceConsiderationInput] = []
        prepared_passages = []
        claim_suffixes: set[str] = set()
        for passage in request.passages:
            unknown_questions = set(passage.question_ids) - set(domain.question_ids)
            if unknown_questions:
                raise ValueError(
                    f"passage maps to another domain's questions: {sorted(unknown_questions)}"
                )
            unit = index.read_unit(passage.unit_id)
            span_end = passage.span_end if passage.span_end is not None else len(unit.text)
            if span_end <= passage.span_start or span_end > len(unit.text):
                raise ValueError(
                    f"passage span is empty or exceeds canonical unit {passage.unit_id!r} text"
                )
            suffix = self._digest(
                "|".join(
                    (
                        request.run_id,
                        request.result_id,
                        request.domain_id,
                        passage.unit_id,
                        str(passage.span_start),
                        str(span_end),
                        passage.claim_type,
                    )
                )
            )
            source = sources.get(unit.source_id)
            if source is None or source.artifact_hash != unit.source_artifact_hash:
                raise ValueError("canonical passage source is not current for this Run")
            if suffix in claim_suffixes:
                raise ValueError("duplicate canonical passage selection")
            claim_suffixes.add(suffix)
            prepared_passages.append((passage, unit, source, suffix, span_end))

        for passage, unit, source, suffix, span_end in prepared_passages:
            source_suffix = self._digest(
                f"{request.run_id}|{unit.source_id}|{unit.source_artifact_hash}"
            )
            source_ref = self._commit_frozen_artifact(
                ledger,
                scope=request.result_id,
                operation="operation:evidence-source-frozen",
                operation_key=f"materialize:evidence-source:{source_suffix}",
                entity_id=f"evidence-source:{source_suffix}",
                revision_id=f"revision:evidence-source-{source_suffix}",
                artifact=source,
                actor=actor,
            )
            unit_suffix = self._digest(
                f"{request.run_id}|{unit.unit_id}|{unit.parse_id}|{unit.source_artifact_hash}"
            )
            canonical_ref = self._commit_frozen_artifact(
                ledger,
                scope=request.result_id,
                operation="operation:canonical-evidence-unit-frozen",
                operation_key=f"materialize:canonical-unit:{unit_suffix}",
                entity_id=f"canonical-unit:{unit_suffix}",
                revision_id=f"revision:canonical-unit-{unit_suffix}",
                artifact=unit,
                actor=actor,
            )
            quote = unit.text[passage.span_start : span_end]
            claim = EvidenceClaim(
                entity_id=f"evidence-claim:{suffix}",
                revision_id=f"revision:evidence-claim-{suffix}",
                dependencies=(
                    Dependency(**canonical_ref.model_dump(), role="dependency:canonical-unit"),
                    Dependency(**source_ref.model_dump(), role="dependency:source"),
                ),
                actor=actor,
                observed_at=self._now(),
                canonical_unit=canonical_ref,
                source=source_ref,
                span_start=passage.span_start,
                span_end=span_end,
                quoted_text_hash=("sha256:" + hashlib.sha256(quote.encode()).hexdigest()),
                claim_type=passage.claim_type,
                verification_status="machine_verified",
            )
            claim_ref = self._commit_frozen_artifact(
                ledger,
                scope=request.result_id,
                operation="operation:evidence-claim-materialized",
                operation_key=f"{request.idempotency_key}:claim:{suffix}",
                entity_id=claim.entity_id,
                revision_id=claim.revision_id,
                artifact=claim,
                actor=actor,
                dependencies=claim.dependencies,
            )
            item_refs.append(claim_ref)
            for question_id in passage.question_ids:
                evidence_by_question[question_id].append(claim_ref)
            dispositions.append(
                EvidenceConsiderationInput(
                    item_id=claim.entity_id,
                    disposition=passage.disposition,
                    basis=passage.basis,
                )
            )
        return request.model_copy(
            update={
                "items": tuple(item_refs),
                "passages": (),
                "evidence_by_question": {
                    question_id: tuple(references)
                    for question_id, references in evidence_by_question.items()
                },
                "candidate_dispositions": tuple(dispositions),
            }
        )

    def submit_domain_answers(
        self, request: SubmitDomainAnswersRequest
    ) -> SubmitDomainAnswersResponse:
        bound_ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            bound_ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:submit-domain-answers"},
        )
        if existing is not None:
            record = _DomainAnswersRecord.model_validate_json(
                bound_ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if record.submission != request:
                return SubmitDomainAnswersResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(bound_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_DOMAIN_ANSWERS,
                        bound_ledger,
                        result_id=request.result_id,
                        domain_id=request.domain_id,
                    ),
                    domain_id=request.domain_id,
                )
            projection = self._projection(bound_ledger, request.run_id)
            return SubmitDomainAnswersResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(bound_ledger.events())}",
                affected_scope=(request.result_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_permitted_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                result_id=request.result_id,
                result_state=self._result_state(projection, request.result_id),
                domain_id=request.domain_id,
                answer_revisions=record.answer_revisions,
                judgments=self._materialize_terminal(
                    bound_ledger, request.run_id, request.result_id
                ),
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_DOMAIN_ANSWERS,
                request.idempotency_key,
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
        if len(supplied) != len(request.answers):
            raise ValueError("each signaling question may be answered only once")
        unknown = supplied - question_ids
        if unknown:
            raise ValueError(f"answers supplied for another domain: {sorted(unknown)}")
        answer_values = {item.question_id: item.answer for item in request.answers}
        evaluator = LogicEvaluator(logic)
        question_by_id = {question.id: question for question in logic.questions}
        active = {
            question_id
            for question_id in domain.question_ids
            if (
                question_by_id[question_id].active_if is None
                or evaluator._matches(
                    question_by_id[question_id].active_if,
                    answer_values,
                    {},
                    {},
                )
            )
        }
        missing = active - supplied
        inactive = supplied - active
        if missing:
            raise ValueError(f"answers required for active questions: {sorted(missing)}")
        if inactive:
            raise ValueError(f"answers supplied for not_applicable questions: {sorted(inactive)}")
        if not self._has_domain_checkpoint(
            self._events_for_run(ledger, request.run_id),
            request.result_id,
            request.domain_id,
            "evidence",
        ):
            raise ValueError("domain evidence must be frozen before answers")
        if any(item.answer.value == "no_information" for item in request.answers):
            for item in request.answers:
                if item.answer.value == "no_information" and not self._has_no_information_basis(
                    ledger, request, item.question_id
                ):
                    raise ValueError(
                        "no-information SQ answers require their own complete Search coverage basis"
                    )
        answer_revisions = self._commit_domain_answers(ledger, request, domain)
        normalized = _DomainAnswersRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            answers={item.question_id: item.answer.value for item in request.answers},
            rationales={item.question_id: item.rationale for item in request.answers},
            project_rules=request.project_rules,
            answer_revisions=answer_revisions,
            submission=request,
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
        judgments = self._materialize_terminal(ledger, request.run_id, request.result_id)
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
            answer_revisions=answer_revisions,
            judgments=judgments,
        )

    def _validate_domain_evidence_submission(
        self,
        ledger: WorkflowLedger,
        request: SubmitDomainEvidenceRequest,
    ) -> None:
        """Validate the evidence-first freeze boundary before writing anything."""
        domain = next(
            (item for item in self._logic_pack().domains if item.id == request.domain_id),
            None,
        )
        if domain is None:
            raise ValueError(f"unknown Logic domain {request.domain_id!r}")
        domain_questions = set(domain.question_ids)
        supplied_question_ids = set(request.evidence_by_question)
        unknown_question_ids = supplied_question_ids - domain_questions
        if unknown_question_ids:
            raise ValueError(
                f"Evidence mapping includes another domain's signaling questions: "
                f"{sorted(unknown_question_ids)}"
            )
        if request.items and supplied_question_ids != domain_questions:
            raise ValueError("each domain signaling question requires an explicit evidence mapping")
        mapped_item_ids = {
            item.entity_id for items in request.evidence_by_question.values() for item in items
        }
        if any(receipt.sq_id not in domain_questions for receipt in request.coverage_receipts):
            raise ValueError("Search coverage receipts must bind this domain's signaling questions")
        if request.coverage_state.value == "incomplete" and not request.coverage_limitations:
            raise ValueError("incomplete evidence coverage requires an explicit limitation")
        if request.no_information_basis:
            if request.coverage_state.value != "complete" or request.coverage_limitations:
                raise ValueError("no-information answers require complete, unlimited coverage")
            if not request.coverage_receipts:
                raise ValueError("no-information basis requires complete Search coverage receipts")
            if any(
                not receipt.establishes_no_information_basis()
                for receipt in request.coverage_receipts
            ):
                raise ValueError(
                    "no-information basis requires adequate readable-source Search coverage"
                )
        item_ids = tuple(item.entity_id for item in request.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Evidence Bundle items must be unique")
        for reference in request.items:
            try:
                ledger.artifacts.read(reference.content_hash)
            except Exception as error:  # ArtifactStore exposes several typed read failures.
                raise ValueError(
                    f"Evidence item {reference.entity_id!r} is not an immutable artifact"
                ) from error
        dispositions = request.candidate_dispositions
        disposition_ids = tuple(item.item_id for item in dispositions)
        if len(disposition_ids) != len(set(disposition_ids)):
            raise ValueError("every Evidence candidate requires exactly one disposition")
        if dispositions:
            if not set(disposition_ids).issubset(set(item_ids)):
                raise ValueError(
                    "candidate dispositions must be attributable to submitted Evidence items"
                )
            if not set(item_ids).issubset(set(disposition_ids)):
                raise ValueError(
                    "every accepted Evidence item must appear in the consideration manifest"
                )
            if any(
                item.disposition is ConsiderationDisposition.UNRESOLVED for item in dispositions
            ):
                raise ValueError("material Evidence candidates cannot remain unresolved")
        if request.items and mapped_item_ids != set(item_ids):
            raise ValueError(
                "every submitted Evidence item must be attributed to at least one "
                "signaling question"
            )
        for conflict in request.conflicts:
            if len(conflict) < 2 or not set(conflict).issubset(set(item_ids)):
                raise ValueError("source conflicts must bind at least two frozen Evidence items")

    def _freeze_domain_evidence(
        self,
        ledger: WorkflowLedger,
        request: SubmitDomainEvidenceRequest,
    ) -> tuple[
        tuple[RecordReference, ...],
        tuple[RecordReference, ...],
        tuple[RecordReference, ...],
    ]:
        """Materialize one immutable Evidence Bundle and manifest per domain SQ."""
        logic = self._logic_pack()
        domain = next(item for item in logic.domains if item.id == request.domain_id)
        result_spec = self._result_spec_reference(ledger, request.result_id)
        actor = request.actor or ASSESSMENT_AGENT_ACTOR
        suffix = self._digest(f"{request.run_id}|{request.idempotency_key}|dispositions")
        disposition_record = EvidenceCandidateDispositionRecord(
            entity_id=f"evidence-disposition:{suffix}",
            revision_id=f"revision:evidence-disposition-{suffix}",
            actor=actor,
            observed_at=self._now(),
            dependencies=tuple(
                Dependency(**item.model_dump(), role="dependency:evidence-item")
                for item in request.items
            ),
            result_id=request.result_id,
            domain_id=request.domain_id,
            items=request.items,
            dispositions=tuple(
                EvidenceConsideration.model_validate(item.model_dump())
                for item in request.candidate_dispositions
            ),
        )
        disposition_ref = self._commit_frozen_artifact(
            ledger,
            scope=request.result_id,
            operation="operation:evidence-candidate-dispositions",
            operation_key=f"{request.idempotency_key}:dispositions",
            entity_id=f"evidence-disposition:{suffix}",
            revision_id=f"revision:evidence-disposition-{suffix}",
            artifact=disposition_record,
            actor=actor,
            dependencies=disposition_record.dependencies,
        )
        coverage_refs: tuple[RecordReference, ...] = ()
        if request.coverage_receipts:
            coverage_suffix = self._digest(f"{request.run_id}|{request.idempotency_key}|coverage")
            coverage_record = EvidenceCoverageReceiptRecord(
                entity_id=f"search-coverage:{coverage_suffix}",
                revision_id=f"revision:search-coverage-{coverage_suffix}",
                actor=actor,
                observed_at=self._now(),
                result_id=request.result_id,
                domain_id=request.domain_id,
                receipts=tuple(
                    receipt.model_dump(mode="json") for receipt in request.coverage_receipts
                ),
            )
            coverage_refs = (
                self._commit_frozen_artifact(
                    ledger,
                    scope=request.result_id,
                    operation="operation:search-coverage-receipt",
                    operation_key=f"{request.idempotency_key}:coverage",
                    entity_id=f"search-coverage:{coverage_suffix}",
                    revision_id=f"revision:search-coverage-{coverage_suffix}",
                    artifact=coverage_record,
                    actor=actor,
                ),
            )
        bundles: list[RecordReference] = []
        manifests: list[RecordReference] = []
        for question_id in domain.question_ids:
            slug = question_id.removeprefix("sq:").replace(":", "-")
            bundle_suffix = self._digest(
                f"{request.run_id}|{request.idempotency_key}|bundle|{question_id}"
            )
            question_items = request.evidence_by_question.get(question_id, request.items)
            question_item_ids = {item.entity_id for item in question_items}
            if not question_item_ids.issubset({item.entity_id for item in request.items}):
                raise ValueError(
                    f"Evidence for {question_id} must reference the domain submission items"
                )
            manifest_items = tuple(question_items)
            manifest_dispositions = tuple(
                item for item in request.candidate_dispositions if item.item_id in question_item_ids
            )
            if manifest_items and not manifest_dispositions:
                raise ValueError(f"Evidence consideration manifest is incomplete for {question_id}")
            manifest = EvidenceConsiderationManifest(
                entity_id=f"evidence-manifest:{request.result_id.removeprefix('result:')}-{slug}",
                revision_id=f"revision:evidence-manifest-{bundle_suffix}",
                dependencies=tuple(
                    Dependency(**item.model_dump(), role="dependency:considered-item")
                    for item in manifest_items
                ),
                actor=actor,
                observed_at=self._now(),
                sq_id=question_id,
                considered_items=manifest_items,
                dispositions=tuple(
                    EvidenceConsideration(
                        item_id=item.item_id,
                        disposition=item.disposition,
                        basis=item.basis,
                    )
                    for item in manifest_dispositions
                ),
            )
            manifest_ref = self._commit_frozen_artifact(
                ledger,
                scope=request.result_id,
                operation="operation:evidence-consideration-manifest",
                operation_key=f"{request.idempotency_key}:manifest:{slug}",
                entity_id=manifest.entity_id,
                revision_id=manifest.revision_id,
                artifact=manifest,
                actor=actor,
                dependencies=manifest.dependencies,
            )
            dependencies = [
                Dependency(**result_spec.model_dump(), role="dependency:result-spec"),
                Dependency(**disposition_ref.model_dump(), role="dependency:evidence-disposition"),
                Dependency(**manifest_ref.model_dump(), role="dependency:evidence-consideration"),
                *(
                    Dependency(**item.model_dump(), role="dependency:evidence-item")
                    for item in question_items
                ),
                *(
                    Dependency(**receipt.model_dump(), role="dependency:search-coverage")
                    for receipt in coverage_refs
                ),
            ]
            bundle_payload = {
                "result_spec": result_spec.model_dump(mode="json"),
                "disposition": disposition_ref.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in question_items],
                "sq_id": question_id,
                "domain_id": request.domain_id,
                "coverage_state": request.coverage_state.value,
                "coverage_limitations": request.coverage_limitations,
                "no_information_basis": request.no_information_basis,
                "conflicts": request.conflicts,
                "coverage_receipts": [receipt.model_dump(mode="json") for receipt in coverage_refs],
                "consideration_manifest": manifest_ref.model_dump(mode="json"),
            }
            bundle_hash = canonical_hash(bundle_payload)
            bundle = EvidenceBundle(
                entity_id=f"bundle:{request.result_id.removeprefix('result:')}-{slug}",
                revision_id=f"revision:evidence-bundle-{bundle_suffix}",
                dependencies=tuple(dependencies),
                actor=actor,
                observed_at=self._now(),
                result_spec=result_spec,
                disposition=disposition_ref,
                items=tuple(question_items),
                frozen_content_hash=bundle_hash,
                sq_id=question_id,
                domain_id=request.domain_id,
                coverage_receipts=coverage_refs,
                consideration_manifest=manifest_ref,
                coverage_limitations=request.coverage_limitations,
                coverage_state=request.coverage_state,
                no_information_basis=request.no_information_basis,
                conflicts=request.conflicts,
            )
            bundle_ref = self._commit_frozen_artifact(
                ledger,
                scope=request.result_id,
                operation="operation:evidence-bundle-frozen",
                operation_key=f"{request.idempotency_key}:bundle:{slug}",
                entity_id=bundle.entity_id,
                revision_id=bundle.revision_id,
                artifact=bundle,
                actor=actor,
                dependencies=tuple(dependencies),
            )
            bundles.append(bundle_ref)
            manifests.append(manifest_ref)
        return tuple(bundles), tuple(manifests), coverage_refs

    def _has_no_information_basis(
        self,
        ledger: WorkflowLedger,
        request: SubmitDomainAnswersRequest,
        question_id: Identifier,
    ) -> bool:
        """Verify one SQ's frozen receipt rather than trusting another SQ's search."""
        evidence_payload = next(
            (
                self._event_payload(ledger, event)
                for event in reversed(self._events_for_run(ledger, request.run_id))
                if event.operation == "operation:submit-domain-evidence"
                and event.scope == request.result_id
                and self._event_payload(ledger, event).get("domain_id") == request.domain_id
            ),
            {},
        )
        raw_bundles = evidence_payload.get("evidence_bundles", ())
        if not isinstance(raw_bundles, (list, tuple)):
            return False
        for raw_bundle in raw_bundles:
            try:
                bundle_ref = RecordReference.model_validate(raw_bundle)
                bundle = EvidenceBundle.model_validate_json(
                    ledger.artifacts.read(bundle_ref.content_hash)
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if bundle.sq_id != question_id or not bundle.no_information_basis:
                continue
            for coverage_ref in bundle.coverage_receipts:
                try:
                    receipt_record = EvidenceCoverageReceiptRecord.model_validate_json(
                        ledger.artifacts.read(coverage_ref.content_hash)
                    )
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
                if any(
                    receipt.sq_id == question_id and receipt.establishes_no_information_basis()
                    for raw_receipt in receipt_record.receipts
                    for receipt in (SearchCoverageReceipt.model_validate(raw_receipt),)
                ):
                    return True
        return False

    def _commit_domain_answers(
        self,
        ledger: WorkflowLedger,
        request: SubmitDomainAnswersRequest,
        domain: Any,
    ) -> tuple[RecordReference, ...]:
        logic = self._logic_pack()
        guidance = load_guidance_pack(self._guidance_pack_path())
        evidence_events = [
            self._event_payload(ledger, event)
            for event in self._events_for_run(ledger, request.run_id)
            if event.operation == "operation:submit-domain-evidence"
            and event.scope == request.result_id
            and self._event_payload(ledger, event).get("domain_id") == request.domain_id
        ]
        if not evidence_events:
            raise ValueError("domain evidence must be frozen before answers")
        bundle_by_sq = {}
        raw_bundle_refs = evidence_events[-1].get("evidence_bundles", ())
        if not isinstance(raw_bundle_refs, (list, tuple)):
            raw_bundle_refs = ()
        for reference in raw_bundle_refs:
            try:
                ref = RecordReference.model_validate(reference)
                payload = json.loads(ledger.artifacts.read(ref.content_hash))
                bundle_by_sq[payload.get("sq_id")] = ref
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        actor = request.actor or ASSESSMENT_AGENT_ACTOR
        answer_refs: list[RecordReference] = []
        for item in request.answers:
            bundle_ref = bundle_by_sq.get(item.question_id)
            if bundle_ref is None:
                raise ValueError(f"no frozen Evidence Bundle exists for {item.question_id}")
            rules = tuple(
                rule.id
                for rule in domain.judgment_rules
                if item.question_id
                in {condition.question_id for condition in self._walk_pack_conditions(rule.when)}
            )
            suffix = self._digest(
                f"{request.run_id}|{request.idempotency_key}|answer|{item.question_id}"
            )
            answer = SQAnswerRevision(
                entity_id=(
                    f"sq-answer:{request.result_id.removeprefix('result:')}-"
                    f"{item.question_id.removeprefix('sq:').replace(':', '-')}"
                ),
                revision_id=f"revision:sq-answer-{suffix}",
                dependencies=(
                    Dependency(**bundle_ref.model_dump(), role="dependency:evidence-bundle"),
                    *(
                        Dependency(**rule.model_dump(), role="dependency:project-rule")
                        for rule in request.project_rules
                    ),
                ),
                actor=actor,
                observed_at=self._now(),
                sq_id=item.question_id,
                answer=item.answer,
                rationale=item.rationale,
                evidence_bundle=bundle_ref,
                project_rules=request.project_rules,
                logic_pack_release_id=logic.release_id,
                logic_pack_hash=logic.content_hash,
                guidance_pack_release_id=guidance.release_id,
                guidance_pack_hash=guidance.content_hash,
                evidence_policy_id="policy:evidence-search-1.0.0",
                evidence_policy_hash=canonical_hash({"policy_id": "policy:evidence-search-1.0.0"}),
                decision_rule_ids=rules,
            )
            answer_refs.append(
                self._commit_frozen_artifact(
                    ledger,
                    scope=request.result_id,
                    operation="operation:sq-answer-revision",
                    operation_key=f"{request.idempotency_key}:answer:{item.question_id}",
                    entity_id=answer.entity_id,
                    revision_id=answer.revision_id,
                    artifact=answer,
                    actor=actor,
                    dependencies=answer.dependencies,
                )
            )
        return tuple(answer_refs)

    @staticmethod
    def _walk_pack_conditions(condition: Any) -> tuple[Any, ...]:
        return (condition,) + tuple(
            nested
            for child in getattr(condition, "conditions", ())
            for nested in RunEngine._walk_pack_conditions(child)
        )

    def _commit_frozen_artifact(
        self,
        ledger: WorkflowLedger,
        *,
        scope: Identifier,
        operation: Identifier,
        operation_key: Identifier,
        entity_id: Identifier,
        revision_id: Identifier,
        artifact: FrozenModel,
        actor: Actor,
        dependencies: tuple[Dependency, ...] = (),
    ) -> RecordReference:
        existing = self._event_for_operation_key(ledger, operation_key, run_id=None)
        if existing is not None:
            return RecordReference(
                entity_id=existing.entity_id,
                revision_id=existing.revision_id,
                content_hash=existing.output_revision_hashes[0],
            )
        now = getattr(artifact, "observed_at", None) or self._now()
        current = next(
            (
                revision
                for revision in ledger.current_revisions()
                if revision.entity_id == entity_id
            ),
            None,
        )
        supersedes_revision_id = current.revision_id if current is not None else None
        if supersedes_revision_id is not None and isinstance(artifact, Revision):
            assert current is not None
            artifact = artifact.model_copy(
                update={
                    "supersedes": Supersession(
                        entity_id=entity_id,
                        revision_id=supersedes_revision_id,
                        content_hash=current.artifact_hash,
                        reason="new immutable assessment checkpoint supersedes prior revision",
                    )
                }
            )
        dependency_inputs = tuple(
            DependencyInput.model_validate(item.model_dump()) for item in dependencies
        )
        transition = self._transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            entity_id=entity_id,
            revision_id=revision_id,
            artifact=artifact,
            checkpoint=None,
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=now,
            actor=actor,
            dependencies=dependency_inputs,
            supersedes_revision_id=supersedes_revision_id,
        )
        result = ledger.commit(
            transition,
            self._acquire_lease(ledger, now),
            now=now,
        )
        return RecordReference(
            entity_id=entity_id,
            revision_id=revision_id,
            content_hash=result.artifact_hash,
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
                clock=lambda: self._now(),
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
        receipts = {item.receipt_id: item for item in proposal.initialization.acquisition_receipts}
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
                            artifact_store=artifacts,
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
                    refreshed if item.candidate_id == candidate_id else item
                    for item in trial.registry_candidates
                )
                trials[candidate.trial_id] = trial.model_copy(
                    update={
                        "inventory": trial.inventory.model_copy(update={"sources": sources}),
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
        owners remain protected by the ledger's normal lease conflict checks.
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
                indexed_pages = _parse_index_pages(
                    parser,
                    artifacts.read(source.artifact_hash),
                    source.parse_records,
                    artifacts,
                )
                pages = tuple(
                    CanonicalPage(
                        page=item.page_number,
                        blocks=(
                            tuple(
                                CanonicalBlock(
                                    kind=CanonicalUnitKind.PARAGRAPH,
                                    text=text_item.text,
                                    spatial=(
                                        text_item.x,
                                        text_item.y,
                                        text_item.x + text_item.width,
                                        text_item.y + text_item.height,
                                    ),
                                )
                                for text_item in item.text_items
                                if text_item.text.strip()
                            )
                            or (
                                (
                                    CanonicalBlock(
                                        kind=CanonicalUnitKind.PARAGRAPH,
                                        text=item.text,
                                        spatial=(0.0, 0.0, item.width, item.height),
                                    ),
                                )
                                if item.text.strip()
                                else ()
                            )
                        ),
                    )
                    for item in indexed_pages
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
        ledger = self._ledger(
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
            lease = self._acquire_lease(ledger, self._now())
            for staging, report_root in missing:
                if report_root.exists():
                    continue
                report_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, report_root)
        self._regenerate_run_index(ledger, run_id)
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
            (event.sequence for event in events if event.operation == "operation:run-completed"),
            default=0,
        )
        latest_reopened = max(
            (event.sequence for event in events if event.operation == "operation:run-reopened"),
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
            report_records[-1].result_id if report_records else next(iter(result_ids))
        )
        latest_assessment = (
            report_records[-1].assessment_revision_id if report_records else "assessment:none"
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
            observed_at=self._now(),
        )
        active_lease = lease or self._acquire_lease(ledger, self._now())
        ledger.commit(transition, active_lease, now=self._now())

    def _materialize_terminal(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
    ) -> tuple[RecordReference, ...]:
        """Evaluate all five domains and publish a minimal static bundle once."""

        events = self._events_for_run(ledger, run_id)
        invalidated_at = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:result-invalidated" and event.scope == result_id
            ),
            default=0,
        )
        if any(
            event.operation == "operation:result-report-ready"
            and event.scope == result_id
            and event.sequence > invalidated_at
            for event in events
        ):
            self._repair_report_publication(ledger, run_id)
            return ()
        logic = self._logic_pack()
        required_domains = {domain.id for domain in logic.domains}
        evidence_domains = {
            self._event_payload(ledger, event).get("domain_id")
            for event in events
            if event.operation == "operation:submit-domain-evidence"
            and event.scope == result_id
            and event.sequence > invalidated_at
        }
        answer_payloads = [
            self._event_payload(ledger, event)
            for event in events
            if event.operation == "operation:submit-domain-answers"
            and event.scope == result_id
            and event.sequence > invalidated_at
        ]
        answer_domains = {payload.get("domain_id") for payload in answer_payloads}
        if not required_domains <= evidence_domains or not required_domains <= answer_domains:
            return ()
        coverage_limitations_set: set[str] = set()
        for event in events:
            if (
                event.operation != "operation:submit-domain-evidence"
                or event.scope != result_id
                or event.sequence <= invalidated_at
            ):
                continue
            payload = self._event_payload(ledger, event)
            raw_limitations = payload.get("coverage_limitations")
            limitations = (
                tuple(str(item) for item in raw_limitations)
                if isinstance(raw_limitations, (list, tuple))
                else ()
            )
            if payload.get("coverage_state") == "incomplete" and not limitations:
                limitations = ("incomplete evidence coverage",)
            coverage_limitations_set.update(limitations)
        coverage_limitations = tuple(sorted(coverage_limitations_set))
        result_spec = self._result_spec_for(ledger, run_id, result_id)
        if result_spec is None:
            raise ValueError("a ResultSpec is required before terminal assessment")
        if coverage_limitations:
            diagnostic_suffix = self._digest(
                f"{run_id}|{result_id}|coverage-diagnostic|{coverage_limitations}"
            )
            reason = "Result evidence coverage is unresolved: " + "; ".join(coverage_limitations)
            diagnostic = _ResultDiagnosticRecord(
                run_id=run_id,
                result_id=result_id,
                trial_id=result_spec.result.trial_id,
                reason=reason,
            )
            diagnostic = self._materialize_diagnostic_bundle(diagnostic)
            transition = self._transition(
                scope=result_id,
                operation="operation:result-diagnostic-ready",
                operation_key=f"idempotency:coverage-diagnostic-{diagnostic_suffix}",
                entity_id=f"result-diagnostic:{diagnostic_suffix}",
                revision_id=f"revision:result-diagnostic-{diagnostic_suffix}",
                artifact=diagnostic,
                checkpoint=f"checkpoint:coverage-diagnostic-{diagnostic_suffix}",
                outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                observed_at=self._now(),
            )
            lease = self._acquire_lease(ledger, self._now())
            ledger.commit(transition, lease, now=self._now())
            self._regenerate_run_index(ledger, run_id)
            return ()
        # A Result may only have one immutable answer checkpoint per domain.
        answers: dict[str, str] = {}
        rationales: dict[str, str] = {}
        for payload in answer_payloads:
            raw_answers = payload.get("answers", {})
            if isinstance(raw_answers, dict):
                answers.update(cast(dict[str, str], raw_answers))
            raw_rationales = payload.get("rationales", {})
            if isinstance(raw_rationales, dict):
                rationales.update(cast(dict[str, str], raw_rationales))
        evaluation = LogicEvaluator(logic).evaluate(EvaluationRequest(answers=answers))
        assessment_digest = self._digest(
            f"{run_id}|{result_id}|{json.dumps(answers, sort_keys=True)}|"
            f"invalidated:{invalidated_at}"
        )
        evidence_refs, answer_refs = self._assessment_inputs(
            ledger, run_id, result_id, invalidated_at
        )
        judgment_references = self._materialize_judgment_revisions(
            ledger,
            run_id,
            result_id,
            logic=logic,
            evaluation=evaluation,
            answer_payloads=answer_payloads,
            assessment_digest=assessment_digest,
        )
        assessment_revision_id = f"assessment:{assessment_digest}"
        questions_by_id = self._report_questions(
            ledger, evidence_refs, answers, rationales, evaluation.matched_rule_ids
        )
        execution_contract = self._execution_contract_identity(ledger)
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
                    questions=tuple(
                        questions_by_id[question_id]
                        for question_id in domain.question_ids
                        if question_id in questions_by_id
                    ),
                    coverage="complete",
                    decision_trace=evaluation.matched_rule_ids,
                )
                for domain in logic.domains
            ),
            visual_citations=self._visual_citations(ledger, evidence_refs),
            execution_contract=execution_contract,
        )
        result_spec_ref = self._result_spec_reference(ledger, result_id)
        source_inventory_ref = self._freeze_source_inventory(
            ledger, run_id, result_id, result_spec_ref
        )
        policy_ref = self._freeze_evidence_policy(ledger, run_id, result_id)
        assessment_record = AssessmentRevision(
            entity_id=f"assessment-record:{assessment_digest}",
            revision_id=assessment_revision_id,
            dependencies=(
                Dependency(**result_spec_ref.model_dump(), role="dependency:result-spec"),
                Dependency(**source_inventory_ref.model_dump(), role="dependency:source-inventory"),
                *(
                    Dependency(**reference.model_dump(), role="dependency:evidence-bundle")
                    for reference in evidence_refs
                ),
                *(
                    Dependency(**reference.model_dump(), role="dependency:sq-answer")
                    for reference in answer_refs
                ),
                *(
                    Dependency(**reference.model_dump(), role="dependency:algorithmic-judgment")
                    for reference in judgment_references
                ),
                Dependency(**policy_ref.model_dump(), role="dependency:policy-release"),
            ),
            actor=ENGINE_ACTOR,
            observed_at=self._now(),
            result_spec=result_spec_ref,
            source_inventory=source_inventory_ref,
            evidence_bundles=evidence_refs,
            answers=answer_refs,
            judgments=judgment_references,
        )
        assessment_ref = self._commit_frozen_artifact(
            ledger,
            scope=result_id,
            operation="operation:assessment-revision-frozen",
            operation_key=f"idempotency:assessment-revision-{assessment_digest}",
            entity_id=assessment_record.entity_id,
            revision_id=assessment_record.revision_id,
            artifact=assessment_record,
            actor=ENGINE_ACTOR,
            dependencies=assessment_record.dependencies,
        )
        if assessment_ref.revision_id != assessment_revision_id:
            raise ValueError("frozen Assessment revision identity does not match report")
        visual_citations, visual_assets = self._materialize_visual_assets(
            ledger, run_id, result_id, assessment.visual_citations
        )
        citations_by_id = {citation.citation_id: citation for citation in visual_citations}
        assessment = assessment.model_copy(
            update={
                "visual_citations": visual_citations,
                "domains": tuple(
                    domain.model_copy(
                        update={
                            "questions": tuple(
                                question.model_copy(
                                    update={
                                        "evidence": tuple(
                                            evidence.model_copy(
                                                update={
                                                    "visual_citation": citations_by_id.get(
                                                        evidence.visual_citation.citation_id,
                                                        evidence.visual_citation,
                                                    )
                                                }
                                            )
                                            if evidence.visual_citation is not None
                                            else evidence
                                            for evidence in question.evidence
                                        )
                                    }
                                )
                                for question in domain.questions
                            )
                        }
                    )
                    for domain in assessment.domains
                ),
            }
        )
        projector = ReportProjector(assessment)
        lease = self._acquire_lease(ledger, self._now())
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
        report_files = projector.bundle_files()
        report_files.update(visual_assets)
        report_files.update(
            {
                "answers.json": (
                    json.dumps(
                        {
                            "answers": answers,
                            "rationales": rationales,
                            "active_question_ids": evaluation.active_question_ids,
                            "inactive_question_ids": evaluation.inactive_question_ids,
                            "matched_rule_ids": evaluation.matched_rule_ids,
                            "judgment_references": [
                                reference.model_dump(mode="json")
                                for reference in judgment_references
                            ],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                ),
            }
        )
        archive = ArchiveBuilder(ledger).build(
            assessment_revision_id,
            pinned_files=self._verification_pins(),
        )
        receipt = verify_archive(archive)
        if receipt.assessment_revision_id != assessment_revision_id:
            raise ValueError("Verification archive identity does not match report")
        report_files["verification-archive.rob2.zip"] = archive
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
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self._verify_staged_report_files(staging, report_files)
        now = self._now()
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
        # A terminal readiness event must never lead the visible immutable
        # bundle.  Staging is verified above and this rename is atomic on the
        # containing filesystem.
        os.replace(staging, report_root)
        ledger.commit_batch(tuple(transitions), lease, now=now)
        self._regenerate_run_index(ledger, run_id)
        self._commit_run_completed_if_ready(ledger, run_id, lease=lease)
        return judgment_references

    @staticmethod
    def _verify_staged_report_files(staging: Path, files: dict[str, bytes]) -> None:
        """Reject an incomplete, unsafe, or hash-inconsistent staged bundle."""

        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in files):
            raise ValueError("report artifact name is not confined to its bundle")
        if {
            path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()
        } != set(files):
            raise ValueError("staged report artifacts do not match the manifest input")
        for name, content in files.items():
            if (staging / name).read_bytes() != content:
                raise ValueError(f"staged report artifact {name!r} failed verification")
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        expected = {
            name: "sha256:" + hashlib.sha256(content).hexdigest()
            for name, content in files.items()
            if name != "manifest.json"
        }
        if manifest.get("files") != expected:
            raise ValueError("staged report manifest does not match artifact hashes")

    def _materialize_diagnostic_bundle(
        self, diagnostic: _ResultDiagnosticRecord
    ) -> _ResultDiagnosticRecord:
        """Atomically publish a judgment-free diagnostic report before its checkpoint."""

        root = self._required_root()
        digest = self._digest(f"{diagnostic.run_id}|{diagnostic.result_id}|{diagnostic.reason}")
        report_root = root / "output" / "report-bundle" / "diagnostics" / digest
        if report_root.exists():
            return diagnostic.model_copy(
                update={
                    "report_root": report_root.relative_to(root).as_posix(),
                    "artifact_names": tuple(
                        sorted(path.name for path in report_root.iterdir() if path.is_file())
                    ),
                }
            )
        staging = report_root.parent / f".diagnostic-staging-{digest}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        projector = DiagnosticReportProjector(
            DiagnosticView(
                result_id=diagnostic.result_id,
                trial_id=diagnostic.trial_id,
                reason=diagnostic.reason,
                limitations=(diagnostic.reason,),
            )
        )
        files = {
            "diagnostic.json": projector.json(),
            "diagnostic.md": (
                "# RoB 2 diagnostic report\n\n"
                f"- Result: {self._escape_markdown(diagnostic.result_id)}\n"
                f"- Trial: {self._escape_markdown(diagnostic.trial_id)}\n"
                f"- Limitation: {self._escape_markdown(diagnostic.reason)}\n"
            ).encode(),
            "diagnostic.html": projector.html(),
        }
        files["manifest.json"] = (
            json.dumps(
                {
                    "result_id": diagnostic.result_id,
                    "trial_id": diagnostic.trial_id,
                    "files": {
                        name: "sha256:" + hashlib.sha256(content).hexdigest()
                        for name, content in files.items()
                    },
                    "limitations": [diagnostic.reason],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        for name, content in files.items():
            (staging / name).write_bytes(content)
        os.replace(staging, report_root)
        return diagnostic.model_copy(
            update={
                "report_root": report_root.relative_to(root).as_posix(),
                "artifact_names": tuple(sorted(files)),
            }
        )

    def _regenerate_run_index(self, ledger: WorkflowLedger, run_id: Identifier) -> None:
        """Publish a compact, ledger-derived Run index after terminal bundles change."""

        root = self._required_root()
        bundle_root = root / "output" / "report-bundle"
        if not bundle_root.exists():
            return
        entries: list[dict[str, Any]] = []
        ancillary_outputs: set[str] = set()
        for event in self._events_for_run(ledger, run_id):
            if event.operation not in {
                "operation:result-report-ready",
                "operation:result-diagnostic-ready",
            }:
                continue
            try:
                record = (
                    _ReportMaterializedRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if event.operation == "operation:result-report-ready"
                    else _ResultDiagnosticRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                )
            except (IndexError, ValueError):
                continue
            report_root = getattr(record, "report_root", None)
            ancillary_outputs.update(getattr(record, "artifact_names", ()))
            report_path = ""
            if report_root:
                report_directory = root / report_root
                try:
                    report_path = report_directory.relative_to(bundle_root).as_posix()
                except ValueError:
                    continue
                if report_path == ".":
                    report_path = ""
            result_spec = self._result_spec_for(ledger, run_id, record.result_id)
            trial_id = result_spec.result.trial_id if result_spec is not None else ""
            diagnostic = event.operation == "operation:result-diagnostic-ready"
            if diagnostic:
                assert isinstance(record, _ResultDiagnosticRecord)
                overall_judgment = ""
                domain_judgments: dict[str, JudgmentLevel] = {}
                limitations = [record.reason]
                coverage = "incomplete"
            else:
                assert isinstance(record, _ReportMaterializedRecord)
                overall_judgment = record.overall_judgment.value
                domain_judgments = record.domain_judgments
                limitations = []
                coverage = "complete"
                if report_root:
                    try:
                        assessment_payload = json.loads(
                            (root / report_root / "assessment.json").read_text(encoding="utf-8")
                        )
                        domains = assessment_payload.get("domains", ())
                        coverage_states = [item.get("coverage") for item in domains]
                        if "incomplete" in coverage_states:
                            coverage = "incomplete"
                        elif "complete_with_limitations" in coverage_states:
                            coverage = "complete_with_limitations"
                        limitations = [
                            limitation
                            for domain in domains
                            for limitation in domain.get("limitations", ())
                        ]
                    except (OSError, ValueError, TypeError):
                        coverage = "not recorded"
            entries.append(
                {
                    "result_id": record.result_id,
                    "trial_id": trial_id,
                    "state": "diagnostic_ready" if diagnostic else "report_ready",
                    "report_root": report_path,
                    "report": (
                        f"{report_path}/diagnostic.html"
                        if diagnostic and report_path
                        else "diagnostic.html"
                        if diagnostic
                        else f"{report_path}/assessment.html"
                        if report_path
                        else "assessment.html"
                    ),
                    "overall_judgment": overall_judgment,
                    "domain_judgments": domain_judgments,
                    "limitations": limitations,
                    "coverage": coverage,
                }
            )
        entries.sort(key=lambda entry: (entry["result_id"], entry["state"]))
        known_result_ids = {entry["result_id"] for entry in entries}
        states = {
            item.result_id: item.state.value for item in self._projection(ledger, run_id).results
        }
        for pending_result_id in self._active_result_ids(ledger, run_id):
            if pending_result_id in known_result_ids:
                continue
            result_spec = self._result_spec_for(ledger, run_id, pending_result_id)
            entries.append(
                {
                    "result_id": pending_result_id,
                    "trial_id": result_spec.result.trial_id if result_spec else "trial:unresolved",
                    "state": states.get(pending_result_id, "pending"),
                    "report": "",
                    "overall_judgment": "",
                    "domain_judgments": {},
                    "limitations": ["Result has no terminal report yet."],
                    "coverage": "not recorded",
                }
            )
        entries.sort(key=lambda entry: (entry["result_id"], entry["state"]))
        execution_contract = self._execution_contract_identity(ledger)
        index = RunIndexProjector(
            RunIndexView(
                run_id=run_id,
                execution_contract=execution_contract,
                ancillary_outputs=tuple(sorted(ancillary_outputs)),
                results=tuple(
                    RunIndexResultView(
                        trial_id=entry["trial_id"] or "trial:unresolved",
                        result_id=entry["result_id"],
                        state=entry["state"],
                        report=entry["report"],
                        overall_judgment=entry["overall_judgment"] or None,
                        domain_judgments={
                            domain_id: judgment.value
                            for domain_id, judgment in entry["domain_judgments"].items()
                        },
                        coverage=entry["coverage"],
                        limitations=tuple(entry["limitations"]),
                    )
                    for entry in entries
                ),
            )
        )
        for name, content in {
            "run-index.json": index.json(),
            "run-index.html": index.html(),
        }.items():
            staging = bundle_root / f".{name}.staging"
            staging.write_bytes(content)
            os.replace(staging, bundle_root / name)

    def _assessment_inputs(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        invalidated_at: int,
    ) -> tuple[tuple[RecordReference, ...], tuple[RecordReference, ...]]:
        """Collect the frozen evidence and answers used by this terminal Result."""

        bundles: dict[str, RecordReference] = {}
        answers: dict[str, RecordReference] = {}
        for event in self._events_for_run(ledger, run_id):
            if event.scope != result_id or event.sequence <= invalidated_at:
                continue
            if event.operation not in {
                "operation:submit-domain-evidence",
                "operation:submit-domain-answers",
            }:
                continue
            payload = self._event_payload(ledger, event)
            field = (
                "evidence_bundles"
                if event.operation == "operation:submit-domain-evidence"
                else "answer_revisions"
            )
            target = bundles if field == "evidence_bundles" else answers
            raw = payload.get(field, ())
            if not isinstance(raw, (list, tuple)):
                continue
            for item in raw:
                try:
                    reference = RecordReference.model_validate(item)
                except (TypeError, ValueError):
                    continue
                target[reference.revision_id] = reference
        return (
            tuple(bundles[key] for key in sorted(bundles)),
            tuple(answers[key] for key in sorted(answers)),
        )

    @staticmethod
    def _escape_markdown(value: str) -> str:
        return (
            re.sub(r"([\\`*{}\[\]()#+.!_|<>~-])", r"\\\1", value)
            .replace("\r", " ")
            .replace("\n", " ")
        )

    def _execution_contract_identity(self, ledger: WorkflowLedger) -> str:
        prepared = self._latest_prepared_record(ledger)
        return self._attempt_contract(ledger, prepared).identity if prepared else "not recorded"

    @staticmethod
    def _report_questions(
        ledger: WorkflowLedger,
        evidence_bundles: tuple[RecordReference, ...],
        answers: dict[str, str],
        rationales: dict[str, str],
        decision_trace: tuple[Identifier, ...],
    ) -> dict[str, SignalingQuestionView]:
        """Materialize report phrases from canonical spans, never agent text."""

        result: dict[str, SignalingQuestionView] = {}
        for bundle_ref in evidence_bundles:
            try:
                bundle = EvidenceBundle.model_validate_json(
                    ledger.artifacts.read(bundle_ref.content_hash)
                )
            except (TypeError, ValueError):
                continue
            if bundle.sq_id is None or bundle.sq_id not in answers:
                continue
            dispositions: dict[str, str] = {}
            if bundle.consideration_manifest is not None:
                try:
                    manifest = EvidenceConsiderationManifest.model_validate_json(
                        ledger.artifacts.read(bundle.consideration_manifest.content_hash)
                    )
                    dispositions = {
                        item.item_id: item.disposition.value for item in manifest.dispositions
                    }
                except (TypeError, ValueError):
                    pass
            items: list[EvidenceView] = []
            for item in bundle.items:
                try:
                    claim = EvidenceClaim.model_validate_json(
                        ledger.artifacts.read(item.content_hash)
                    )
                    unit = CanonicalEvidenceUnit.model_validate_json(
                        ledger.artifacts.read(claim.canonical_unit.content_hash)
                    )
                except (TypeError, ValueError):
                    try:
                        transcription = VisualTranscription.model_validate_json(
                            ledger.artifacts.read(item.content_hash)
                        )
                    except (TypeError, ValueError):
                        continue
                    disposition = dispositions.get(item.entity_id, "contextual")
                    if disposition not in {"supporting", "contradicting", "contextual"}:
                        disposition = "residual"
                    items.append(
                        EvidenceView(
                            evidence_id=transcription.revision_id,
                            disposition=disposition,
                            exact_phrase=transcription.transcription,
                            source_id=transcription.source.entity_id,
                            page=transcription.page,
                            provenance=(
                                f"visual-only transcription; {transcription.render_mode} at "
                                f"{transcription.dpi} dpi; not machine-verified"
                            ),
                            visual_citation=VisualCitationView(
                                citation_id=transcription.revision_id,
                                source_id=transcription.source.entity_id,
                                page=transcription.page,
                                region=transcription.region,
                                label="Visual transcription",
                                exact_phrase=transcription.transcription,
                                render_provenance=(
                                    f"{transcription.render_mode} at {transcription.dpi} dpi; "
                                    "visual-only; not machine-verified"
                                ),
                            ),
                        )
                    )
                    continue
                phrase = unit.text[claim.span_start : claim.span_end]
                if not phrase:
                    continue
                disposition = dispositions.get(item.entity_id, "contextual")
                if disposition not in {"supporting", "contradicting", "contextual"}:
                    disposition = "residual"
                items.append(
                    EvidenceView(
                        evidence_id=claim.revision_id,
                        disposition=disposition,
                        exact_phrase=phrase,
                        source_id=claim.source.entity_id,
                        page=unit.page,
                        provenance=(
                            f"canonical unit {unit.unit_id}; Parse record {unit.parse_id}; "
                            f"verification {claim.verification_status.value}"
                        ),
                    )
                )
            result[bundle.sq_id] = SignalingQuestionView(
                question_id=bundle.sq_id,
                answer=answers[bundle.sq_id],
                rationale=rationales.get(
                    bundle.sq_id, "No rationale was recorded for this signaling question."
                ),
                evidence=tuple(items),
                coverage=bundle.coverage_state.value,
                limitations=bundle.coverage_limitations,
                no_information_basis=bundle.no_information_basis,
                decision_trace=decision_trace,
            )
        return result

    def _materialize_visual_assets(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        citations: tuple[VisualCitationView, ...],
    ) -> tuple[tuple[VisualCitationView, ...], dict[str, bytes]]:
        """Render confined local crop and context assets for visual citations."""

        result_spec = self._result_spec_for(ledger, run_id, result_id)
        prepared = self._latest_prepared_record(ledger)
        if result_spec is None or prepared is None:
            return citations, {}
        trial = next(
            (
                item
                for item in prepared.proposal.initialization.trials
                if item.trial_id == result_spec.result.trial_id
            ),
            None,
        )
        sources = {item.source_id: item for item in trial.inventory.sources} if trial else {}
        parser = self._parser or LiteParseAdapter()
        files: dict[str, bytes] = {}
        rendered: list[VisualCitationView] = []
        for citation in citations:
            source = sources.get(citation.source_id)
            if source is None or source.artifact_hash is None:
                rendered.append(citation)
                continue
            try:
                page = parser.screenshot(
                    ledger.artifacts.read(source.artifact_hash),
                    page_numbers=(citation.page,),
                    dpi=144,
                )[0]
                context = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
                scale = page.dpi / 72
                left, top, right, bottom = (round(value * scale) for value in citation.region)
                left, right = max(0, left), min(context.width, right)
                top, bottom = max(0, top), min(context.height, bottom)
                if right <= left or bottom <= top:
                    rendered.append(citation)
                    continue
                crop = context.crop((left, top, right, bottom))
                overlay = context.copy()
                ImageDraw.Draw(overlay).rectangle(
                    (left, top, right, bottom), outline="#9a5a12", width=4
                )
                slug = hashlib.sha256(citation.citation_id.encode()).hexdigest()[:16]
                crop_path = f"visual-assets/{slug}-crop.png"
                context_path = f"visual-assets/{slug}-page.png"
                for path, image in ((crop_path, crop), (context_path, overlay)):
                    output = io.BytesIO()
                    image.save(output, format="PNG", optimize=False)
                    files[path] = output.getvalue()
                rendered.append(
                    citation.model_copy(
                        update={"crop_path": crop_path, "context_path": context_path}
                    )
                )
            except (OSError, ValueError, IndexError):
                rendered.append(citation)
        return tuple(rendered), files

    @staticmethod
    def _visual_citations(
        ledger: WorkflowLedger, evidence_bundles: tuple[RecordReference, ...]
    ) -> tuple[VisualCitationView, ...]:
        """Project frozen visual transcriptions into report-visible citations."""

        citations: dict[str, VisualCitationView] = {}
        for bundle_ref in evidence_bundles:
            try:
                bundle = EvidenceBundle.model_validate_json(
                    ledger.artifacts.read(bundle_ref.content_hash)
                )
            except (TypeError, ValueError):
                continue
            for item in bundle.items:
                try:
                    transcription = VisualTranscription.model_validate_json(
                        ledger.artifacts.read(item.content_hash)
                    )
                except (TypeError, ValueError):
                    continue
                citations[transcription.revision_id] = VisualCitationView(
                    citation_id=transcription.revision_id,
                    source_id=transcription.source.entity_id,
                    page=transcription.page,
                    region=transcription.region,
                    label="Visual transcription",
                    exact_phrase=transcription.transcription,
                    render_provenance=(
                        f"{transcription.render_mode} at {transcription.dpi} dpi; "
                        f"visual-only; not machine-verified"
                    ),
                )
        return tuple(citations[key] for key in sorted(citations))

    def _freeze_source_inventory(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        result_spec: RecordReference,
    ) -> RecordReference:
        """Persist the exact source inventory that constrains this Assessment."""

        resolved = self._result_spec_for(ledger, run_id, result_id)
        if resolved is None:
            raise ValueError("a ResultSpec is required before freezing source inventory")
        proposal = self._latest_proposal(ledger, run_id)
        trial = next(
            (
                item
                for item in proposal.initialization.trials
                if item.trial_id == resolved.result.trial_id
            ),
            None,
        )
        if trial is None:
            raise ValueError("the Result Trial is absent from the frozen input inventory")
        suffix = self._digest(f"{run_id}|{result_id}|{result_spec.content_hash}|source-inventory")
        inventory = SourceInventoryRevision(
            entity_id=f"source-inventory:{result_id.removeprefix('result:')}",
            revision_id=f"revision:source-inventory-{suffix}",
            dependencies=(Dependency(**result_spec.model_dump(), role="dependency:result-spec"),),
            actor=ENGINE_ACTOR,
            observed_at=self._now(),
            result_spec=result_spec,
            sources=trial.inventory.sources,
            coverage_limitations=trial.inventory.coverage_limitations,
        )
        return self._commit_frozen_artifact(
            ledger,
            scope=result_id,
            operation="operation:source-inventory-frozen",
            operation_key=f"idempotency:source-inventory-{suffix}",
            entity_id=inventory.entity_id,
            revision_id=inventory.revision_id,
            artifact=inventory,
            actor=ENGINE_ACTOR,
            dependencies=inventory.dependencies,
        )

    def _freeze_evidence_policy(
        self, ledger: WorkflowLedger, run_id: Identifier, result_id: Identifier
    ) -> RecordReference:
        """Freeze the policy identity required for a complete archive closure."""

        policy_id = "policy:evidence-search-1.0.0"
        policy_hash = canonical_hash({"policy_id": policy_id, "version": "1.0.0"})
        policy = PolicyRelease(
            entity_id=policy_id,
            revision_id=f"revision:evidence-policy-{self._digest(policy_hash)}",
            actor=ENGINE_ACTOR,
            observed_at=self._now(),
            kind=PolicyKind.EVIDENCE_SEARCH_POLICY,
            family_id="policy-family:evidence-search",
            release_id="1.0.0",
            canonical_content_hash=policy_hash,
            required_schema_version=SCHEMA_VERSION,
            inventory=(),
        )
        return self._commit_frozen_artifact(
            ledger,
            scope=result_id,
            operation="operation:evidence-policy-frozen",
            operation_key=f"idempotency:evidence-policy-{self._digest(policy_hash)}",
            entity_id=policy.entity_id,
            revision_id=policy.revision_id,
            artifact=policy,
            actor=ENGINE_ACTOR,
        )

    @staticmethod
    def _verification_pins() -> dict[str, bytes]:
        """Provide the installed schemas and packs needed for offline verification."""

        package_root = Path(__file__).resolve().parents[1]
        source_root = Path(__file__).resolve().parents[3]
        pins: dict[str, bytes] = {}
        pin_root = next(
            (
                candidate
                for candidate in (package_root, source_root)
                if (candidate / "schemas").is_dir() and (candidate / "packs").is_dir()
            ),
            None,
        )
        if pin_root is None:
            raise FileNotFoundError("the installed verification schemas and packs are missing")
        for path in sorted((pin_root / "schemas").glob("*.json")):
            pins[f"schemas/{path.name}"] = path.read_bytes()
        for kind in ("logic", "guidance"):
            for path in sorted((pin_root / "packs" / kind).glob("*.yaml")):
                pins[f"packs/{kind}/{path.name}"] = path.read_bytes()
        return pins

    def _materialize_judgment_revisions(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        *,
        logic: Any,
        evaluation: Any,
        answer_payloads: list[dict[str, Any]],
        assessment_digest: str,
    ) -> tuple[RecordReference, ...]:
        """Persist deterministic Decision traces and domain judgments exactly once."""
        answer_refs_by_question: dict[str, RecordReference] = {}
        for payload in answer_payloads:
            raw_refs = payload.get("answer_revisions", ())
            if not isinstance(raw_refs, (list, tuple)):
                continue
            for raw_ref in raw_refs:
                try:
                    reference = RecordReference.model_validate(raw_ref)
                    answer_payload = json.loads(ledger.artifacts.read(reference.content_hash))
                    question_id = answer_payload.get("sq_id")
                    if isinstance(question_id, str):
                        answer_refs_by_question[question_id] = reference
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    continue
        judgment_refs: list[RecordReference] = []
        now = self._now()
        for domain in logic.domains:
            question_ids = set(domain.question_ids)
            active = tuple(
                question_id
                for question_id in evaluation.active_question_ids
                if question_id in question_ids
            )
            inactive = tuple(
                question_id
                for question_id in evaluation.inactive_question_ids
                if question_id in question_ids
            )
            domain_rule_ids = tuple(rule.id for rule in domain.judgment_rules)
            matched = tuple(
                rule_id for rule_id in evaluation.matched_rule_ids if rule_id in domain_rule_ids
            )
            evaluated = tuple(
                rule_id for rule_id in evaluation.evaluated_rule_ids if rule_id in domain_rule_ids
            )
            trace_suffix = self._digest(f"{assessment_digest}|trace|{domain.id}")
            trace = DecisionTrace(
                entity_id=f"decision-trace:{result_id.removeprefix('result:')}-{domain.id.removeprefix('domain:')}",
                revision_id=f"revision:decision-trace-{trace_suffix}",
                actor=ENGINE_ACTOR,
                observed_at=now,
                active_question_ids=active,
                inactive_question_ids=inactive,
                matched_rule_ids=matched,
                resulting_judgment=evaluation.domain_judgments[domain.id],
                domain_id=domain.id,
                evaluated_rule_ids=evaluated,
                logic_pack_release_id=logic.release_id,
                logic_pack_hash=logic.content_hash,
            )
            trace_ref = self._commit_frozen_artifact(
                ledger,
                scope=result_id,
                operation="operation:decision-trace-derived",
                operation_key=f"idempotency:decision-trace-{trace_suffix}",
                entity_id=trace.entity_id,
                revision_id=trace.revision_id,
                artifact=trace,
                actor=ENGINE_ACTOR,
            )
            answer_refs = tuple(
                answer_refs_by_question[question_id]
                for question_id in active
                if question_id in answer_refs_by_question
            )
            dependencies = (
                *(
                    Dependency(**reference.model_dump(), role="dependency:sq-answer")
                    for reference in answer_refs
                ),
                Dependency(**trace_ref.model_dump(), role="dependency:decision-trace"),
            )
            judgment_suffix = self._digest(f"{assessment_digest}|judgment|{domain.id}")
            judgment = AlgorithmicJudgmentRevision(
                entity_id=f"judgment:{result_id.removeprefix('result:')}-{domain.id.removeprefix('domain:')}",
                revision_id=f"revision:judgment-{judgment_suffix}",
                dependencies=dependencies,
                actor=ENGINE_ACTOR,
                observed_at=now,
                domain_id=domain.id,
                judgment=evaluation.domain_judgments[domain.id],
                answer_revisions=answer_refs,
                decision_trace=trace_ref,
                logic_pack_release_id=logic.release_id,
                logic_pack_hash=logic.content_hash,
                overall_policy_id="policy:overall-maximum-domain-1.0.0",
                overall_policy_hash=canonical_hash(
                    {
                        "policy_id": "policy:overall-maximum-domain-1.0.0",
                        "order": ["low", "some_concerns", "high"],
                        "rules": (
                            "all_low",
                            "any_high",
                            "otherwise_some_concerns",
                        ),
                    }
                ),
            )
            judgment_refs.append(
                self._commit_frozen_artifact(
                    ledger,
                    scope=result_id,
                    operation="operation:algorithmic-judgment-derived",
                    operation_key=f"idempotency:algorithmic-judgment-{judgment_suffix}",
                    entity_id=judgment.entity_id,
                    revision_id=judgment.revision_id,
                    artifact=judgment,
                    actor=ENGINE_ACTOR,
                    dependencies=dependencies,
                )
            )
        return tuple(judgment_refs)

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
        operation_key: Identifier,
    ) -> WorkflowLedger:
        ledger = self._bound_ledger(run_id)
        # Every write requires the exact currently issued opaque token and
        # dependency fingerprint; this is the stale-work guard exposed to MCP
        # callers in every Run state.
        existing = self._event_for_operation_key(ledger, operation_key, run_id=run_id)
        global_existing = self._event_for_operation_key(ledger, operation_key)
        allowed_operations = {f"operation:{expected_operation.value.replace('_', '-')}"}
        if expected_operation is RunOperation.SUBMIT_RESULT_RESOLUTION:
            allowed_operations.add("operation:result-discovered")
        if (existing is None and global_existing is not None) or (
            existing is not None and existing.operation not in allowed_operations
        ):
            raise StaleWorkTokenError(run_id, self._next_work_item(ledger, run_id))
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

    def _submission_retry_event(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        operation_key: Identifier,
        allowed_operations: set[Identifier],
    ) -> WorkflowEvent | None:
        """Find a committed typed submission before rejecting its consumed token."""

        existing = self._event_for_operation_key(ledger, operation_key, run_id=run_id)
        if existing is None:
            return None
        if existing.operation not in allowed_operations:
            return None
        return existing

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
        now = observed_at or self._now()
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

    def _result_spec_reference(
        self,
        ledger: WorkflowLedger,
        result_id: Identifier,
    ) -> RecordReference:
        """Return the exact ledger reference for one resolved ResultSpec."""
        for event in reversed(self._events_for_run(ledger, self._run_id_for_ledger(ledger))):
            if event.operation not in {
                "operation:result-discovered",
                "operation:submit-result-resolution",
                "operation:run-register-result",
                "operation:result-spec-superseded",
            }:
                continue
            payload = self._event_payload(ledger, event)
            if payload.get("result_id") != result_id:
                continue
            raw_spec = payload.get("result_spec")
            if not isinstance(raw_spec, dict):
                continue
            try:
                spec = ResultSpecRevision.model_validate(raw_spec)
            except (ValueError, TypeError):
                continue
            # Result resolution stores a typed submission envelope.  Project
            # the nested ResultSpec as its own immutable artifact so bundles
            # can bind the exact semantic Result revision rather than the
            # mutable envelope around it.
            suffix = self._digest(f"{result_id}|{spec.revision_id}")
            return self._commit_frozen_artifact(
                ledger,
                scope=result_id,
                operation="operation:result-spec-frozen",
                operation_key=f"idempotency:result-spec-frozen-{suffix}",
                entity_id=spec.entity_id,
                revision_id=spec.revision_id,
                artifact=spec,
                actor=ENGINE_ACTOR,
            )
        raise ValueError("a ResultSpec is required before freezing domain evidence")

    @staticmethod
    def _run_id_for_ledger(ledger: WorkflowLedger) -> Identifier:
        for event in ledger.events():
            payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
            if isinstance(payload, dict) and isinstance(payload.get("run_id"), str):
                return payload["run_id"]
        raise ValueError("ledger does not contain a Run identifier")

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
        issued_result_candidates = {item.candidate_id: item for item in proposal.result_candidates}
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
                candidates = {item.candidate_id: item for item in proposal.registry_candidates}
                candidate = candidates.get(selection.registry_candidate_id)
                if candidate is None:
                    raise ValueError("Run proposal registry candidate was not issued by this Run")
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
                    raise ValueError("Run proposal Result and candidate identify different Results")
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
                    and issued_result_candidates[selection.result_candidate_id].result_id
                    is not None
                ):
                    continue
                continue
            if issued_results.get(selection.result_id) != selection.trial_id and not (
                selection.result_candidate_id is not None
                and issued_result_candidates[selection.result_candidate_id].status == "needs_input"
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
                raise ValueError("Run proposal ambiguity identifier was not issued by this Run")
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
                if item.resolved and original.detail.startswith("Multiple top-level PDFs found;"):
                    raise ValueError(
                        "primary-report ambiguity must be resolved by an explicit "
                        "trial.yaml primary_report declaration"
                    )
            elif item.resolved and item.material and not (item.resolution or "").strip():
                raise ValueError("a resolved material Run proposal ambiguity requires a resolution")

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

    def _active_trial_ids(self, ledger: WorkflowLedger, run_id: Identifier) -> set[Identifier]:
        reconciliation = self._latest_reconciliation(ledger, run_id)
        if reconciliation is not None:
            return set(reconciliation.active_trial_ids)
        definition = self._confirmed_definition(ledger, run_id)
        return set(definition.trial_ids) if definition is not None else set()

    def _active_result_ids(self, ledger: WorkflowLedger, run_id: Identifier) -> set[Identifier]:
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
        if any(
            trial.status == "inventory_ready" and trial.trial_id in selected_trial_ids
            for trial in proposal.initialization.trials
        ) and not self._source_classification_complete(
            proposal,
            ledger,
            events,
            selected_trial_ids=selected_trial_ids,
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
            unresolved_result_id = self._issued_unresolved_result_id(run_id, unresolved_trial)
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
                "sha256:" + hashlib.sha256(f"{run_id}|{key}|{operation.value}".encode()).hexdigest()
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
                if event.operation == "operation:result-invalidated" and event.scope == result_id
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
            result_id for result_id in proposal.result_ids if result_id in active_ids
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

    def _issued_unresolved_result_id(self, run_id: Identifier, trial_id: Identifier) -> Identifier:
        digest = self._digest(f"{run_id}|unresolved-result|{trial_id}")
        return f"result:unresolved-{digest}"

    def _trial_id_for_result(self, result_id: Identifier | None) -> Identifier | None:
        if result_id is None or self._root is None:
            return None
        try:
            ledger = self._ledger(
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
                    if isinstance(raw_result, dict) and isinstance(raw_result.get("trial_id"), str):
                        raw_trial_id = raw_result.get("trial_id")
                        if isinstance(raw_trial_id, str):
                            return raw_trial_id
            return None
        except (StopIteration, AttributeError, ValueError):
            return None

    def _logic_pack(self):
        return load_logic_pack(self._logic_pack_path())

    @staticmethod
    def _guidance_pack_path() -> Path:
        candidates = (
            Path(__file__).resolve().parents[1]
            / "packs"
            / "guidance"
            / "rob2-parallel-assignment-en-2019.1.yaml",
            Path(__file__).resolve().parents[3]
            / "packs"
            / "guidance"
            / "rob2-parallel-assignment-en-2019.1.yaml",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise FileNotFoundError("the pinned RoB 2 Guidance pack is not installed")

    def _domain_context_pack(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        work_item: WorkItem,
        *,
        trial: TrialInitialization | None,
    ) -> DomainContextPack:
        """Build a deterministic bounded Domain context without mutating state."""
        if work_item.domain_id is None or work_item.result_id is None:
            raise ValueError("a Domain context requires Result and domain scope")
        logic = self._logic_pack()
        guidance = load_guidance_pack(self._guidance_pack_path())
        domain = next((item for item in logic.domains if item.id == work_item.domain_id), None)
        if domain is None:
            raise ValueError(f"unknown Logic domain {work_item.domain_id!r}")
        guidance_by_id = {item.logic_element_id: item for item in guidance.items}
        evaluator = LogicEvaluator(logic)
        active_questions = tuple(
            question.id
            for question in logic.questions
            if question.id in domain.question_ids
            and (question.active_if is None or evaluator._matches(question.active_if, {}, {}, {}))
        )
        inactive_questions = tuple(
            question_id
            for question_id in domain.question_ids
            if question_id not in active_questions
        )
        source_limit = 20
        available_sources = tuple(trial.inventory.sources) if trial is not None else ()
        selected_sources = available_sources[:source_limit]
        limitations = tuple(trial.inventory.coverage_limitations) if trial is not None else ()
        if len(available_sources) > source_limit:
            limitations += (
                f"Domain context lists the first {source_limit} sources; "
                "use the pinned source inventory for the remainder.",
            )
        # Reusable accepted Evidence is deliberately reference-only.  Reading
        # the full bundle here would turn a bounded context pack into a dossier.
        reusable: list[RecordReference] = []
        project_rules: list[RecordReference] = []
        for event in self._events_for_run(ledger, run_id):
            if event.scope != work_item.result_id:
                continue
            payload = self._event_payload(ledger, event)
            if (
                event.operation == "operation:evidence-bundle-frozen"
                and payload.get("domain_id") == work_item.domain_id
            ):
                reusable.append(
                    RecordReference(
                        entity_id=event.entity_id,
                        revision_id=event.revision_id,
                        content_hash=event.output_revision_hashes[0],
                    )
                )
            if (
                event.operation == "operation:submit-domain-evidence"
                and payload.get("domain_id") == work_item.domain_id
            ):
                raw_project_rules = payload.get("project_rules", ())
                if not isinstance(raw_project_rules, (list, tuple)):
                    raw_project_rules = ()
                project_rules.extend(
                    RecordReference.model_validate(item)
                    for item in raw_project_rules
                    if isinstance(item, dict)
                )
        raw = {
            "result_id": work_item.result_id,
            "domain_id": work_item.domain_id,
            "logic_pack_release_id": logic.release_id,
            "logic_pack_hash": logic.content_hash,
            "guidance_pack_release_id": guidance.release_id,
            "guidance_pack_hash": guidance.content_hash,
            "active_question_ids": active_questions,
            "inactive_question_ids": inactive_questions,
            "guidance_items": tuple(
                guidance_by_id[question_id]
                for question_id in domain.question_ids
                if question_id in guidance_by_id
            ),
            "project_rules": tuple(dict.fromkeys(project_rules)),
            "sources": tuple(
                SourceContextSummary.from_descriptor(source) for source in selected_sources
            ),
            "source_limitations": limitations,
            "reusable_evidence": tuple(reusable),
            "required_protocol": (
                "mandatory_search_coverage",
                "candidate_disposition",
                "contradiction_pass",
                "visual_gate",
            ),
        }
        typed_raw = cast(dict[str, Any], raw)
        hash_payload = DomainContextPack.model_construct(
            **typed_raw,
            content_hash="sha256:" + ("0" * 64),
        ).model_dump(mode="json", exclude={"content_hash"})
        return DomainContextPack(
            **typed_raw,
            content_hash=canonical_hash(hash_payload),
        )

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
        *,
        result_id: Identifier | None = None,
    ) -> tuple[VisualCandidate, ...]:
        candidates: dict[str, VisualCandidate] = {}
        for event in ledger.events():
            payload = self._event_payload(ledger, event)
            if payload.get("run_id") not in {None, run_id}:
                continue
            if result_id is not None and event.scope not in {
                result_id,
                f"preparation:{result_id.removeprefix('result:')}",
            }:
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

    def _installed_execution_contract(self) -> _ExecutionContract:
        """Digest the installed execution dependencies pinned by ``rob2.lock``."""

        lock_path = next(
            (
                candidate
                for candidate in (
                    Path(__file__).resolve().parents[1] / "rob2.lock",
                    Path(__file__).resolve().parents[3] / "rob2.lock",
                )
                if candidate.is_file()
            ),
            None,
        )
        if lock_path is None:
            raise FileNotFoundError("the installed rob2.lock release contract is missing")
        raw = json.loads(lock_path.read_text(encoding="utf-8"))

        def content_hash(value: str) -> ContentHash:
            return "sha256:" + hashlib.sha256(value.encode()).hexdigest()

        parser = self._parser or LiteParseAdapter()
        parser_configuration = getattr(parser, "configuration", getattr(parser, "config", None))
        parser_identity = (
            f"{type(parser).__module__}.{type(parser).__qualname__}|"
            f"{getattr(parser, 'name', '')}|{getattr(parser, 'version', '')}|"
            f"{json.dumps(parser_configuration, default=str, sort_keys=True)}"
        )
        project_policy = self._required_root() / "rob2.yaml"
        components = {
            "engine-schema": content_hash(
                f"{raw['package']}|{raw['package_version']}|"
                f"{raw['application_contract']}|{SCHEMA_VERSION}"
            ),
            "dependency-lock": raw["dependency_lock_hash"],
            "logic-pack": raw["logic_pack_hash"],
            "guidance-pack": raw["guidance_pack_hash"],
            "assessment-skill": raw["skills"]["rob2-assess"]["content_hash"],
            "initialization-skill": raw["skills"]["rob2-init"]["content_hash"],
            "parser": content_hash(parser_identity),
            "project-policies": (
                "sha256:" + hashlib.sha256(project_policy.read_bytes()).hexdigest()
                if project_policy.is_file()
                else content_hash("no-project-policy")
            ),
        }
        return _ExecutionContract(
            identity=content_hash(json.dumps(components, sort_keys=True)),
            components=components,
        )

    def _attempt_contract(
        self, ledger: WorkflowLedger, prepared: _PreparedRunRecord
    ) -> _ExecutionContract:
        for event in reversed(self._events_for_run(ledger, prepared.run_id)):
            if event.operation != "operation:preparation-attempt-superseded":
                continue
            return _PreparationAttemptSupersededRecord.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            ).execution_contract
        return prepared.execution_contract

    def _reconcile_execution_contract(
        self, ledger: WorkflowLedger, prepared: _PreparedRunRecord
    ) -> None:
        """Supersede only Result work declared dependent on changed installed inputs."""

        projection = self._projection(ledger, prepared.run_id)
        if projection.run_state in {RunState.RETIRED, RunState.INTEGRITY_FAILED}:
            return
        previous = self._attempt_contract(ledger, prepared)
        current = self._installed_execution_contract()
        if current.identity == previous.identity:
            return
        changed = tuple(
            sorted(
                key
                for key in set(previous.components).union(current.components)
                if previous.components.get(key) != current.components.get(key)
            )
        )
        result_dependency_components = {
            "engine-schema",
            "dependency-lock",
            "logic-pack",
            "guidance-pack",
            "assessment-skill",
            "parser",
            "project-policies",
        }
        result_states = {item.result_id: item.state for item in projection.results}
        invalidated_result_ids = (
            tuple(
                sorted(
                    result_id
                    for result_id in self._active_result_ids(ledger, prepared.run_id)
                    if result_states.get(result_id) is not ResultState.DIAGNOSTIC_READY
                )
            )
            if set(changed).intersection(result_dependency_components)
            else ()
        )
        record = _PreparationAttemptSupersededRecord(
            run_id=prepared.run_id,
            previous_contract=previous,
            execution_contract=current,
            changed_components=changed,
            invalidated_result_ids=invalidated_result_ids,
        )
        now = self._now()
        suffix = self._digest(f"{prepared.run_id}|{previous.identity}|{current.identity}")
        prior_attempt = next(
            (
                event
                for event in reversed(self._events_for_run(ledger, prepared.run_id))
                if event.operation == "operation:preparation-attempt-superseded"
            ),
            next(
                event
                for event in reversed(self._events_for_run(ledger, prepared.run_id))
                if event.operation == "operation:run-prepared"
            ),
        )
        transitions = [
            self._transition(
                scope=prepared.run_id,
                operation="operation:preparation-attempt-superseded",
                operation_key=f"idempotency:preparation-attempt-superseded-{suffix}",
                entity_id=prior_attempt.entity_id,
                revision_id=f"revision:preparation-attempt-{suffix}",
                artifact=record,
                checkpoint=f"checkpoint:preparation-attempt-{suffix}",
                outcome=WorkflowEventOutcome.WORK_REQUIRED,
                observed_at=now,
                supersedes_revision_id=prior_attempt.revision_id,
            )
        ]
        if projection.run_state is RunState.COMPLETE and invalidated_result_ids:
            transitions.append(
                self._transition(
                    scope=prepared.run_id,
                    operation="operation:run-reopened",
                    operation_key=f"idempotency:contract-reopened-{suffix}",
                    entity_id=f"run-contract-reopened:{suffix}",
                    revision_id=f"revision:run-contract-reopened-{suffix}",
                    artifact=_RunReopenedRecord(
                        run_id=prepared.run_id,
                        input_snapshot_hash=prepared.proposal.input_snapshot_hash,
                        invalidated_result_ids=invalidated_result_ids,
                    ),
                    checkpoint=f"checkpoint:contract-reopened-{suffix}",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        for result_id in invalidated_result_ids:
            transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:result-invalidated",
                    operation_key=f"idempotency:contract-invalidated-{suffix}-{result_id.removeprefix('result:')}",
                    entity_id=f"result-contract-invalidation:{suffix}-{result_id.removeprefix('result:')}",
                    revision_id=f"revision:result-contract-invalidation:{suffix}-{result_id.removeprefix('result:')}",
                    artifact=_ResultInvalidatedRecord(
                        run_id=prepared.run_id,
                        result_id=result_id,
                        reason="A declared installed Execution-contract dependency changed.",
                        affected_trial_id=self._trial_id_for_result(result_id) or "trial:unknown",
                        input_snapshot_hash=current.identity,
                    ),
                    checkpoint=f"checkpoint:contract-invalidated-{result_id.removeprefix('result:')}",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        lease = self._acquire_lease(ledger, now)
        ledger.commit_batch(tuple(transitions), lease, now=now)

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
        now = self._now()
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
        invalid_hash = (
            "sha256:"
            + hashlib.sha256(f"{run_id}|invalid-input-snapshot|{detail}".encode()).hexdigest()
        )
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
                now=self._now,
            )
        except ValueError as error:
            # A declaration that points at a Trial folder removed after
            # confirmation is a supported retirement, not semantic drift.
            # Preserve the old proposal as history while removing that Trial
            # and its Results from the active scope.
            missing_trials = set(existing.trial_ids) - self._input_trial_ids(self._required_root())
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
                        now=self._now,
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
                    if self._trial_for_result(existing.initialization, result_id) in missing_trials
                }
                active_trials = (
                    set(
                        previous_reconciliation.active_trial_ids
                        if previous_reconciliation is not None
                        else definition.trial_ids
                    )
                    - missing_trials
                )
                active_results = (
                    set(
                        previous_reconciliation.active_result_ids
                        if previous_reconciliation is not None
                        else definition.result_ids
                    )
                    - retired_results
                )
                proposal = existing.model_copy(
                    update={
                        "proposal_id": (
                            f"run-proposal:{self._digest(f'{run_id}|{current_hash}|retired')}"
                        ),
                        "proposal_token": (
                            f"proposal-token:{self._digest(f'{run_id}|{current_hash}|retired')}"
                        ),
                        "input_snapshot_hash": current_hash,
                        "trial_ids": tuple(sorted(self._input_trial_ids(self._required_root()))),
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
                            f"run-proposal:{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                        ),
                        "proposal_token": (
                            f"proposal-token:{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
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
                "result_ids": tuple(dict.fromkeys(refreshed.result_ids + resolved_result_ids)),
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
                        f"run-proposal:{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                    ),
                    "proposal_token": (
                        f"proposal-token:{self._digest(f'{run_id}|{current_hash}|ambiguous')}"
                    ),
                    "input_snapshot_hash": current_hash,
                    "ambiguities": tuple(
                        dict.fromkeys(existing.ambiguities + tuple(material_ambiguities))
                    ),
                }
            )

        # Existing confirmed scope remains authoritative.  New Trials and
        # Result declarations are compatible additions; old rejected or
        # removed items never re-enter active outputs accidentally.
        active_trial_ids = (previous_active_trials - retired_trial_ids) | added_trial_ids
        active_trial_ids &= new_trial_ids
        refreshed_result_ids = {spec.result.result_id for spec in initialization.result_specs}
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
            if not any(spec.result.trial_id == trial_id for spec in initialization.result_specs):
                trial = next(item for item in initialization.trials if item.trial_id == trial_id)
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
        trial_status = {trial.trial_id: trial.status for trial in initialization.trials}
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
            retired_result_ids=(() if material_ambiguities else tuple(sorted(retired_result_ids))),
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
        previous_specs = {spec.result.result_id: spec for spec in previous.result_specs}
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
                details.append(f"Confirmed Result {result_id} was remapped to a different Trial.")
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
                details.append(f"Result {result_id} was added to an existing confirmed Trial.")
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
            source for source_id, source in new_sources.items() if source_id not in old_sources
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
            parse.parse_id: source.source_id for source in sources for parse in source.parse_records
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
            source.source_id in affected_source_ids and SourceRole.PRIMARY_REPORT in source.roles
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
            if (
                unmatched_old
                and unmatched_current
                and (len(unmatched_old) > 1 or len(unmatched_current) > 1)
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
                if (
                    unmatched_old_count
                    and unmatched_current_count
                    and (unmatched_old_count > 1 or unmatched_current_count > 1)
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
        unmatched_current_trials = {trial.trial_id for trial in current.trials} - set(trial_pairs)
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
            spec.result.result_id: spec.result.trial_id for spec in initialization.result_specs
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

        previous_explicit_ids = {spec.result.result_id for spec in previous.result_specs}
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
            trial.trial_id: {source.source_id: source for source in trial.inventory.sources}
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
        now = self._now()
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
                trial_id = self._trial_for_result(record.proposal.initialization, result_id)
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
                item for item in old_fingerprints.get(fingerprint, ()) if item not in used_old
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
            allocated_source_ids: set[Identifier] = {source.source_id for source in old_sources}
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
                                f"{trial_id}|{source.relative_path}|{source.artifact_hash or ''}"
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
                remapped_by_current_id[source.source_id] for source in trial.inventory.sources
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
                            "trial_id": trial_map.get(spec.result.trial_id, spec.result.trial_id)
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
            for item in current.diagnostics
        )
        return current.model_copy(
            update={
                "trials": tuple(remapped_trials),
                "result_specs": remapped_specs,
                "result_candidates": remapped_candidates,
                "diagnostics": remapped_findings,
                "registry_candidates": tuple(
                    item.model_copy(
                        update={"trial_id": trial_map.get(item.trial_id, item.trial_id)}
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
            for index, finding in enumerate(initialization.diagnostics)
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
                raise ValueError(f"project input symlinks are not permitted: {path} -> {resolved}")
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
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )

    def _new_run_id(self, root: Path, event_count: int) -> Identifier:
        if self._determinism is not None:
            return self._determinism.run_id(self._digest("qualification"), root, event_count)
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
        checkpoint: Identifier | None,
        outcome: WorkflowEventOutcome,
        observed_at: datetime,
        actor: Actor = ENGINE_ACTOR,
        dependencies: tuple[DependencyInput, ...] = (),
        supersedes_revision_id: Identifier | None = None,
    ) -> Transition:
        if (
            operation == "operation:result-diagnostic-ready"
            and isinstance(artifact, _ResultDiagnosticRecord)
            and artifact.report_root is None
        ):
            artifact = self._materialize_diagnostic_bundle(artifact)
        return Transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            actor=actor,
            observed_at=observed_at,
            entity_id=entity_id,
            revision_id=revision_id,
            artifact=artifact.model_dump_json().encode(),
            artifact_media_type="application/json",
            dependencies=dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(dependencies),
            checkpoint=checkpoint,
            outcome=outcome,
            supersedes_revision_id=supersedes_revision_id,
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
            progress=self._run_progress(ledger, run_id, projection, work_item=work_item),
            error=error,
        )

    def _run_progress(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        projection: LifecycleProjection,
        *,
        work_item: WorkItem | None = None,
    ) -> RunProgress:
        """Project resume-critical state solely from committed ledger records."""

        events = self._events_for_run(ledger, run_id)
        checkpoint = next(
            (event.checkpoint for event in reversed(events) if event.checkpoint), None
        )
        if work_item is None and projection.run_state is RunState.ASSESSING:
            work_item = self._next_work_item(ledger, run_id)
        blockers = ()
        if projection.run_state is RunState.BLOCKED:
            latest_blocker = next(
                (
                    self._event_payload(ledger, event).get("reason")
                    for event in reversed(events)
                    if event.operation == "operation:run-blocked"
                ),
                None,
            )
            if isinstance(latest_blocker, str):
                blockers = (latest_blocker,)
        terminal_counts = {
            state.value: sum(1 for item in projection.results if item.state is state)
            for state in (ResultState.REPORT_READY, ResultState.DIAGNOSTIC_READY)
        }
        report_locations = tuple(
            sorted(
                {
                    str(payload["report_root"])
                    for event in events
                    if event.operation == "operation:report-materialized"
                    for payload in (self._event_payload(ledger, event),)
                    if isinstance(payload.get("report_root"), str)
                }
            )
        )
        return RunProgress(
            committed_checkpoint=checkpoint,
            current_scope=tuple(
                item
                for item in (
                    work_item.trial_id if work_item is not None else None,
                    work_item.result_id if work_item is not None else None,
                    work_item.domain_id if work_item is not None else None,
                )
                if item is not None
            ),
            blockers=blockers,
            terminal_result_counts=terminal_counts,
            report_locations=report_locations,
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
            code: Literal["unsupported_method", "invalid_configuration"] = "unsupported_method"
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
                    raise ValueError(f"project path symlinks are not permitted: {nested}")
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
