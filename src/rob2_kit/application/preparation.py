"""Preparation contracts and the ledger-derived autonomous work-item protocol."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from rob2_kit.domain.revisions import (
    Actor,
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
    Revision,
)
from rob2_kit.storage.ledger import (
    CommitResult,
    DependencyInput,
    LeaseToken,
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)


class PreparationOutcomeKind(StrEnum):
    DRAFT_READY = "draft_ready"
    PREPARATION_INCOMPLETE = "preparation_incomplete"
    TRIAL_FAILED = "trial_failed"


class IncompleteReason(StrEnum):
    MATERIAL_EVIDENCE_GAP = "material_evidence_gap"
    INSUFFICIENT_READABLE_COVERAGE = "insufficient_readable_coverage"
    UNRESOLVED_MATERIAL_CONFLICT = "unresolved_material_conflict"


class TrialFailureReason(StrEnum):
    REQUIRED_PRIMARY_UNRECOVERABLE = "required_primary_unrecoverable"
    RESULT_UNRECOVERABLE = "result_unrecoverable"
    PAGE_ATTRIBUTION_UNTRUSTWORTHY = "page_attribution_untrustworthy"


class DraftReady(FrozenModel):
    outcome: Literal["draft_ready"] = "draft_ready"
    assessment: RecordReference


class PreparationIncomplete(FrozenModel):
    outcome: Literal["preparation_incomplete"] = "preparation_incomplete"
    result_spec: RecordReference
    reason: IncompleteReason
    detail: str = Field(min_length=1)


class TrialFailed(FrozenModel):
    outcome: Literal["trial_failed"] = "trial_failed"
    trial_id: Identifier
    reason: TrialFailureReason
    detail: str = Field(min_length=1)


PreparationOutcome = DraftReady | PreparationIncomplete | TrialFailed


class PreparationAttempt(Revision):
    dependency_roles = {
        "project_manifest": "dependency:project-manifest",
        "result_spec": "dependency:result-spec",
    }
    project_manifest: RecordReference
    result_spec: RecordReference
    outcome: PreparationOutcome | None = None


class SubmissionKind(StrEnum):
    SOURCE_CLASSIFICATION = "source_classification"
    RESULT_RESOLUTION = "result_resolution"
    SOURCE_INVENTORY = "source_inventory"
    EVIDENCE_DISPOSITIONS = "evidence_dispositions"
    ACQUISITION = "acquisition"
    PARSE = "parse"
    SEARCH_COVERAGE = "search_coverage"
    VISUAL_INSPECTION = "visual_inspection"
    EVIDENCE_BUNDLE = "evidence_bundle"
    SQ_ANSWERS = "sq_answers"
    JUDGMENT = "judgment"
    ASSESSMENT = "assessment"


class PreparationStep(FrozenModel):
    step_id: Identifier
    operation: Identifier
    checkpoint: Identifier
    submission_kind: SubmissionKind


class PreparationPlan(FrozenModel):
    scope: Identifier
    trial_id: Identifier
    result_id: Identifier | None = None
    steps: tuple[PreparationStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_steps(self) -> PreparationPlan:
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("preparation step IDs must be unique")
        if len({step.checkpoint for step in self.steps}) != len(self.steps):
            raise ValueError("preparation checkpoints must be unique")
        return self


class PreparationWorkItem(FrozenModel):
    work_item_id: Identifier
    scope: Identifier
    trial_id: Identifier
    result_id: Identifier | None = None
    step_id: Identifier
    operation: Identifier
    checkpoint: Identifier
    submission_kind: SubmissionKind
    dependencies: tuple[DependencyInput, ...]
    dependency_fingerprint: ContentHash


class WorkSubmission(FrozenModel):
    work_item_id: Identifier
    operation_key: Identifier
    expected_dependency_fingerprint: ContentHash
    submission_kind: SubmissionKind
    entity_id: Identifier
    revision_id: Identifier
    artifact: bytes
    artifact_media_type: str = Field(min_length=1)
    outcome: WorkflowEventOutcome = WorkflowEventOutcome.COMPLETED
    terminal_outcome: PreparationOutcome | None = None

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> WorkSubmission:
        reached = self.outcome is WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED
        if reached != (self.terminal_outcome is not None):
            raise ValueError(
                "terminal_outcome is required exactly when a preparation outcome is reached"
            )
        return self


class AutonomousPreparation:
    """Derive and commit bounded preparation work from authoritative ledger state."""

    def __init__(
        self,
        ledger: WorkflowLedger,
        lease: LeaseToken,
        actor: Actor,
        plans: Iterable[PreparationPlan],
    ) -> None:
        self.ledger = ledger
        self.lease = lease
        self.actor = actor
        plan_items = tuple(plans)
        self._plans = {plan.scope: plan for plan in plan_items}
        if len(self._plans) != len(plan_items):
            raise ValueError("preparation plan scopes must be unique")
        self.ledger.preflight()

    def next_work_item(self, scope: Identifier) -> PreparationWorkItem | None:
        plan = self._plans[scope]
        if self._terminal_outcome(scope) is not None:
            return None
        completed = {
            checkpoint.checkpoint
            for checkpoint in self.ledger.checkpoints()
            if checkpoint.scope == scope
        }
        step = next((item for item in plan.steps if item.checkpoint not in completed), None)
        if step is None:
            return None
        dependencies = self._scope_dependencies(scope)
        fingerprint = dependency_fingerprint(dependencies)
        digest = hashlib.sha256(f"{scope}|{step.step_id}|{fingerprint}".encode()).hexdigest()[:24]
        return PreparationWorkItem(
            work_item_id=f"work-item:{digest}",
            scope=scope,
            trial_id=plan.trial_id,
            result_id=plan.result_id,
            step_id=step.step_id,
            operation=step.operation,
            checkpoint=step.checkpoint,
            submission_kind=step.submission_kind,
            dependencies=dependencies,
            dependency_fingerprint=fingerprint,
        )

    def submit(
        self,
        work_item: PreparationWorkItem,
        submission: WorkSubmission,
        *,
        now: datetime | None = None,
    ) -> CommitResult:
        prior = next(
            (
                event
                for event in self.ledger.events()
                if event.operation_key == submission.operation_key
            ),
            None,
        )
        duplicate = prior is not None
        if prior is not None and (
            prior.scope != work_item.scope
            or prior.operation != work_item.operation
            or prior.entity_id != submission.entity_id
            or prior.revision_id != submission.revision_id
            or prior.dependencies != work_item.dependencies
        ):
            raise ValueError("operation key was already used for a different work submission")
        current = self.next_work_item(work_item.scope)
        if not duplicate and (current is None or current != work_item):
            raise ValueError("work item is stale or no longer permitted")
        if submission.work_item_id != work_item.work_item_id:
            raise ValueError("submission does not match work item")
        if submission.submission_kind is not work_item.submission_kind:
            raise ValueError("submission kind does not match work item")
        if submission.expected_dependency_fingerprint != work_item.dependency_fingerprint:
            raise ValueError("submission dependency fingerprint does not match work item")
        checkpoint = (
            None
            if submission.outcome is WorkflowEventOutcome.RETRYABLE_INTERRUPTION
            else work_item.checkpoint
        )
        artifact = submission.artifact
        media_type = submission.artifact_media_type
        if submission.terminal_outcome is not None:
            self._validate_terminal_submission(work_item, submission)
            artifact = submission.terminal_outcome.model_dump_json().encode()
            media_type = "application/json"
        return self.ledger.commit(
            Transition(
                scope=work_item.scope,
                operation=work_item.operation,
                operation_key=submission.operation_key,
                actor=self.actor,
                observed_at=now or datetime.now(UTC),
                entity_id=submission.entity_id,
                revision_id=submission.revision_id,
                artifact=artifact,
                artifact_media_type=media_type,
                dependencies=work_item.dependencies,
                expected_dependency_fingerprint=work_item.dependency_fingerprint,
                checkpoint=checkpoint,
                outcome=submission.outcome,
            ),
            self.lease,
            now=now,
        )

    def continue_preparation(self) -> tuple[PreparationWorkItem, ...]:
        """Run deterministic derivation until external agent work is required."""
        return tuple(
            work_item
            for scope in self._plans
            if (work_item := self.next_work_item(scope)) is not None
        )

    def batch_status(self) -> dict[str, str]:
        return {
            scope: outcome.value
            for scope in self._plans
            if (outcome := self._terminal_outcome(scope)) is not None
        }

    def _scope_dependencies(self, scope: str) -> tuple[DependencyInput, ...]:
        current = {revision.revision_id: revision for revision in self.ledger.current_revisions()}
        dependencies = []
        for event in self.ledger.events():
            revision = current.get(event.revision_id)
            if event.scope == scope and revision is not None:
                dependencies.append(
                    DependencyInput(
                        entity_id=event.entity_id,
                        revision_id=event.revision_id,
                        role="dependency:preparation-state",
                        content_hash=revision.artifact_hash,
                    )
                )
        return tuple(dependencies)

    def _terminal_outcome(self, scope: str) -> PreparationOutcomeKind | None:
        for event in reversed(self.ledger.events()):
            if (
                event.scope == scope
                and event.outcome is WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED
            ):
                payload = json.loads(self.ledger.artifacts.read(event.output_revision_hashes[0]))
                return PreparationOutcomeKind(payload["outcome"])
        return None

    def _validate_terminal_submission(
        self,
        work_item: PreparationWorkItem,
        submission: WorkSubmission,
    ) -> None:
        outcome = submission.terminal_outcome
        if isinstance(outcome, DraftReady):
            if submission.submission_kind is not SubmissionKind.ASSESSMENT:
                raise ValueError("draft_ready requires an assessment submission")
            submitted_matches = (
                outcome.assessment.entity_id == submission.entity_id
                and outcome.assessment.revision_id == submission.revision_id
            )
            dependency_matches = any(
                dependency.entity_id == outcome.assessment.entity_id
                and dependency.revision_id == outcome.assessment.revision_id
                and dependency.content_hash == outcome.assessment.content_hash
                for dependency in work_item.dependencies
            )
            if not submitted_matches and not dependency_matches:
                raise ValueError(
                    "draft_ready must reference the submitted or deterministically "
                    "derived assessment"
                )
        elif isinstance(outcome, PreparationIncomplete):
            if not work_item.dependencies:
                raise ValueError(
                    "preparation_incomplete requires committed usable Result preparation"
                )
