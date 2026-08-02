"""Typed host-neutral application boundary for lean-v1 Runs."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
    PrepareRunRequest,
    PrepareRunResponse,
    ReadEvidenceRequest,
    ReadEvidenceResponse,
    ResultStatus,
    RunDirective,
    RunOperation,
    RunProposal,
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
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import Actor, ActorKind, FrozenModel, Identifier
from rob2_kit.evidence.search import EvidenceSearchIndex
from rob2_kit.evidence.visual import VisualCandidate, VisualInspectionPolicy
from rob2_kit.ingestion.project import (
    DocumentParser,
    ProjectInitialization,
    initialize_project,
)
from rob2_kit.storage import (
    ArtifactStore,
    CommitResult,
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


class RunEngine:
    """Coordinate capabilities through one method per fixed public operation.

    Only the process/root binding is held in memory.  Authoritative Run state,
    proposal content, and lifecycle transitions live in the concrete Workflow
    ledger and content-addressed Artifact store.
    """

    def __init__(self, *, parser: DocumentParser | None = None) -> None:
        self._root: Path | None = None
        self._parser = parser
        self._owner_id = f"owner:run-engine:{uuid.uuid4()}"

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
            current = self._current_prepared_record(ledger)
        except LifecycleIntegrityError as error:
            return self._prepare_integrity_failure(root, str(error))
        if current is not None and not request.start_new:
            projection = self._projection(ledger, current.run_id)
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
        if not request.authorized:
            raise PermissionError("Starting a new Run requires project-root authorization")

        initialization = initialize_project(root, actor=ENGINE_ACTOR, parser=self._parser)
        run_id = self._new_run_id(root, len(ledger.events()))
        proposal = self._proposal(run_id, initialization)
        now = datetime.now(UTC)
        prepared = _PreparedRunRecord(
            run_id=run_id,
            proposal=proposal,
            prepared_at=now,
        )
        transitions: list[Transition] = []
        if current is not None:
            retirement_suffix = self._digest(f"{current.run_id}|{run_id}|retired")
            transitions.append(
                self._transition(
                    scope=current.run_id,
                    operation="operation:run-retired",
                    operation_key=f"idempotency:retire-run-{retirement_suffix}",
                    entity_id=f"run-retirement:{retirement_suffix}",
                    revision_id=f"revision:run-retirement-{retirement_suffix}",
                    artifact=_RunRetiredRecord(
                        run_id=current.run_id,
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
        lease = ledger.acquire_lease(self._owner_id, now, timedelta(minutes=5))
        committed = ledger.commit_batch(tuple(transitions), lease, now=now)
        projection = self._projection(ledger, run_id)
        return PrepareRunResponse(
            operation_id=committed[prepared_transition_index].operation_id,
            ledger_cursor=f"ledger:{committed[-1].sequence}",
            affected_scope=(current.run_id, run_id) if current is not None else (run_id,),
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
            projection = self._projection(ledger, request.run_id)
        except (LifecycleIntegrityError, RunIntegrityFailure) as error:
            return ContinueRunResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONTINUE_RUN, request.run_id
                ),
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
        if projection.run_state is RunState.ASSESSING and not projection.results:
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
            lease = ledger.acquire_lease(self._owner_id, now, timedelta(minutes=5))
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
        if request.work_token.run_id != request.run_id:
            raise ValueError("Work token belongs to a different Run")
        proposal = self._latest_proposal(ledger, request.run_id)
        work_item = WorkItem(
            work_item_id=request.work_token.work_item_id,
            work_token=request.work_token,
            operation=request.work_token.operation,
            dependency_fingerprint=request.work_token.dependency_fingerprint,
        )
        sources = tuple(
            source for trial in proposal.initialization.trials for source in trial.inventory.sources
        )
        result_spec = (
            proposal.initialization.result_specs[0]
            if (proposal.initialization.result_specs)
            else None
        )
        context = WorkContext(
            work_item=work_item,
            trial=(proposal.initialization.trials[0] if proposal.initialization.trials else None),
            result_spec=result_spec,
            sources=sources,
        )
        projection = self._projection(ledger, request.run_id)
        return GetWorkContextResponse(
            operation_id=self._read_operation_id(RunOperation.GET_WORK_CONTEXT, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.AGENT_WORK_REQUIRED,
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
        if request.proposal_token != proposal.proposal_token:
            raise ValueError("Run proposal token is stale or was not issued by this Run")
        self._validate_proposal_selections(proposal, request.selections)
        submitted = proposal.model_copy(update={"selections": request.selections})
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
        lease = ledger.acquire_lease(self._owner_id, now, timedelta(minutes=5))
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
        if projection.run_state is not RunState.AWAITING_CONFIRMATION:
            raise ValueError("the Run definition has already left confirmation")
        proposal = self._latest_proposal(ledger, request.run_id)
        if request.proposal_token != proposal.proposal_token:
            raise ValueError("Run proposal token is stale or was not issued by this Run")
        accepted = tuple(item for item in proposal.selections if item.accepted)
        trial_ids = tuple(item.trial_id for item in accepted) or proposal.trial_ids
        selected_result_ids = tuple(
            item.result_id for item in accepted if item.result_id is not None
        )
        result_ids = selected_result_ids or proposal.result_ids
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
        lease = ledger.acquire_lease(self._owner_id, now, timedelta(minutes=5))
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
        ledger = self._submission_ledger(
            request.run_id,
            request.work_token,
            RunOperation.SUBMIT_SOURCE_CLASSIFICATION,
        )
        proposal = self._latest_proposal(ledger, request.run_id)
        issued_sources = {
            source.source_id
            for trial in proposal.initialization.trials
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
        ledger = self._submission_ledger(
            request.run_id,
            request.work_token,
            RunOperation.SUBMIT_RESULT_RESOLUTION,
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
                item.result_id
                for item in self._projection(ledger, request.run_id).results
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
        ledger = self._submission_ledger(
            request.run_id,
            request.work_token,
            RunOperation.SUBMIT_DOMAIN_EVIDENCE,
        )
        result = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-domain-evidence",
            operation_key=request.idempotency_key,
            artifact=request,
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
        ledger = self._submission_ledger(
            request.run_id,
            request.work_token,
            RunOperation.SUBMIT_DOMAIN_ANSWERS,
        )
        result = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-domain-answers",
            operation_key=request.idempotency_key,
            artifact=request,
            checkpoint=f"checkpoint:answers-{request.domain_id.removeprefix('domain:')}",
        )
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
            raise ValueError(f"RunEngine is already bound to project root {self._root}")
        self._root = root

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

    def _submission_ledger(
        self,
        run_id: Identifier,
        work_token: WorkToken,
        expected_operation: RunOperation,
    ) -> WorkflowLedger:
        if work_token.run_id != run_id:
            raise ValueError("Work token belongs to a different Run")
        if work_token.operation is not expected_operation:
            raise ValueError("Work token does not permit this typed submission")
        return self._bound_ledger(run_id)

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
        lease = ledger.acquire_lease(self._owner_id, now, timedelta(minutes=5))
        return ledger.commit(transition, lease, now=now)

    @staticmethod
    def _event_for_operation_key(
        ledger: WorkflowLedger, operation_key: Identifier
    ) -> WorkflowEvent | None:
        return next(
            (event for event in ledger.events() if event.operation_key == operation_key),
            None,
        )

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
    def _validate_proposal_selections(
        proposal: RunProposal,
        selections: tuple[RunProposalSelection, ...],
    ) -> None:
        issued_trials = set(proposal.trial_ids)
        issued_results = {
            item.result.result_id: item.result.trial_id
            for item in proposal.initialization.result_specs
        }
        seen: set[tuple[Identifier, Identifier | None]] = set()
        for selection in selections:
            identity = (selection.trial_id, selection.result_id)
            if identity in seen:
                raise ValueError("Run proposal contains a duplicate selection")
            seen.add(identity)
            if selection.trial_id not in issued_trials:
                raise ValueError("Run proposal selection was not issued by this Run")
            if selection.result_id is None:
                continue
            if issued_results.get(selection.result_id) != selection.trial_id:
                raise ValueError("Run proposal Result was not issued for the selected Trial")

    @staticmethod
    def _result_state(
        projection: LifecycleProjection,
        result_id: Identifier,
    ) -> ResultState:
        return next(
            (item.state for item in projection.results if item.result_id == result_id),
            ResultState.PENDING,
        )

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
        for record in reversed(self._prepared_records(ledger)):
            state = self._projection(ledger, record.run_id).run_state
            if state not in {RunState.COMPLETE, RunState.RETIRED}:
                return record
        return None

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

    def _proposal(
        self,
        run_id: Identifier,
        initialization: ProjectInitialization,
    ) -> RunProposal:
        snapshot_hash = canonical_hash(initialization)
        suffix = self._digest(f"{run_id}|{snapshot_hash}")
        return RunProposal(
            proposal_id=f"run-proposal:{suffix}",
            proposal_token=f"proposal-token:{suffix}",
            run_id=run_id,
            supported_scope=initialization.manifest.supported_scope,
            trial_ids=tuple(item.trial_id for item in initialization.trials),
            result_ids=tuple(item.result.result_id for item in initialization.result_specs),
            input_snapshot_hash=snapshot_hash,
            initialization=initialization,
        )

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
                else None
            ),
            run_id=run_id,
            run_state=projection.run_state,
            directive=directive,
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
