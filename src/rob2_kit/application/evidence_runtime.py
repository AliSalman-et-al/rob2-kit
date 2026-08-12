"""Private v3 evidence-navigation runtime.

This is intentionally an application seam, rather than a public transport
contract. It binds engine-materialized context to the v3 reducer and bounded
Search implementation.
"""

from __future__ import annotations

from typing import Protocol

from rob2_kit.application.evidence_context import EvidenceContextStage, MaterializedEvidenceContext
from rob2_kit.application.evidence_navigation import (
    ConcurrentEvidenceNavigationUpdate,
    V3EvidenceNavigationState,
    V3EvidenceNavigationStore,
    new_v3_navigation_state,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.evidence.obligations import EvidenceNavigationIntent, EvidenceNavigationIntentKind
from rob2_kit.evidence.search import (
    EvidenceReadPolicy,
    EvidenceScope,
    EvidenceSearchPage,
    EvidenceSearchPolicy,
    SearchContinuationReason,
    SearchQuery,
)
from rob2_kit.evidence.workflow import (
    V3AcquisitionAttemptReceipt,
    V3AttemptKind,
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
    V3EvidenceWorkflowState,
    V3NavigationCompletionReceipt,
    V3SearchAttempt,
    record_v3_acquisition_attempt,
    record_v3_navigation_completion,
    record_v3_page_exposure,
    start_v3_search_attempt,
    submit_evidence_stage_outcome,
    submit_v3_page_triage,
    supersede_v3_search_attempt,
    v3_coverage_progress,
    v3_stage_is_active,
)


class V3EvidenceSearchDependency(Protocol):
    """The small bounded-Search capability required by the v3 runtime."""

    def search_page(
        self,
        query: SearchQuery,
        *,
        issuance_context: str | None = None,
        continuation: str | None = None,
        scope: EvidenceScope | None = None,
        continue_reason: SearchContinuationReason | None = None,
        continue_rationale: str | None = None,
        policy: EvidenceSearchPolicy | None = None,
    ) -> EvidenceSearchPage: ...


class V3EvidenceRuntimeError(ValueError):
    """A request cannot be authorized by the private v3 runtime."""


class V3EvidenceContextMismatch(V3EvidenceRuntimeError):
    """The engine context and reducer state do not describe the same work."""


class V3EvidenceUnknownNavigationTarget(V3EvidenceRuntimeError):
    """A request did not name one exact materialized proposition/pass/stage/intent."""


class V3EvidenceSourceScopeMismatch(V3EvidenceRuntimeError):
    """Caller-selected Sources differ from the engine-issued stage scope."""


class UnsupportedV3EvidenceNavigationIntent(V3EvidenceRuntimeError):
    """This private slice currently executes only Search navigation intents."""


class V3EvidenceSearchRequest(FrozenModel):
    """Start one Search attempt, optionally replacing its current selected attempt."""

    expected_content_hash: ContentHash
    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    intent_id: Identifier
    attempt_id: Identifier
    query: SearchQuery
    supersede_attempt_id: Identifier | None = None
    supersession_rationale: str | None = None


class V3EvidenceSearchContinuationRequest(FrozenModel):
    """Fetch the next bounded page for a current selected Search attempt."""

    expected_content_hash: ContentHash
    attempt_id: Identifier
    continuation: str
    continue_reason: SearchContinuationReason | None = None
    continue_rationale: str | None = None


class V3EvidencePageTriageRequest(FrozenModel):
    expected_content_hash: ContentHash
    submission_id: Identifier
    attempt_id: Identifier
    page_handles: tuple[str, ...]
    revisions: tuple[V3CandidateTriageRevision, ...]


class V3EvidenceRuntimeResult(FrozenModel):
    """The durable update plus the reducer's deterministic readiness projection."""

    state: V3EvidenceNavigationState
    progress: dict[str, object]
    page: EvidenceSearchPage | None = None
    blockers: tuple[str, ...] = ()


class V3EvidenceNavigationRuntime:
    """Persist exactly one materialized v3 workflow.

    The supplied ``workflow`` is the engine-owned initial reducer state.  Each
    mutation reloads its durable successor and uses the supplied content hash
    as an optimistic concurrency precondition.
    """

    def __init__(
        self,
        *,
        context: MaterializedEvidenceContext,
        workflow: V3EvidenceWorkflowState,
        store: V3EvidenceNavigationStore,
        search: V3EvidenceSearchDependency,
        search_policy: EvidenceSearchPolicy,
    ) -> None:
        self._context = context
        self._initial_workflow = workflow
        self._store = store
        self._search = search
        self._search_policy = search_policy
        self._validate_initial_state()

    def initialize(self) -> V3EvidenceNavigationState:
        """Create the v3 record once; an existing record is never overwritten."""

        state = new_v3_navigation_state(workflow=self._initial_workflow)
        self._store.save(state)
        return state

    @property
    def expected_workflow(self) -> V3EvidenceWorkflowState:
        """The exact initial identity every loaded successor must preserve."""

        return self._initial_workflow

    def load(self) -> V3EvidenceNavigationState:
        """Load the durable v3 state bound to this exact context."""

        state = self._store.load(
            run_id=self._initial_workflow.run_id,
            result_id=self._initial_workflow.result_id,
            domain_id=self._initial_workflow.domain_id,
            question_id=self._initial_workflow.question_id,
            obligation_hash=self._context.obligation_hash,
            inventory_snapshot_hash=self._context.inventory_snapshot_hash,
        )
        if state is None:
            raise V3EvidenceRuntimeError("v3 evidence navigation state has not been initialized")
        self._validate_workflow(state.workflow)
        return state

    def search_page(self, request: V3EvidenceSearchRequest) -> V3EvidenceRuntimeResult:
        """Start or supersede an exact Search attempt and persist its first page."""

        state = self._current(request.expected_content_hash)
        stage, intent = self._resolve_search_target(
            request.proposition_id, request.pass_id, request.stage_id, request.intent_id
        )
        if not v3_stage_is_active(
            state.workflow,
            request.proposition_id,
            request.pass_id,
            request.stage_id,
        ):
            raise V3EvidenceRuntimeError("cannot start Search for an inactive triggered v3 stage")
        self._require_exact_source_ids(request.query.source_ids, stage)
        if not stage.scope.authorized_source_ids:
            return V3EvidenceRuntimeResult(
                state=state,
                progress=v3_coverage_progress(state.workflow),
                blockers=("materialized_source_scope_empty",),
            )
        query = request.query.model_copy(update={"source_ids": stage.scope.authorized_source_ids})
        attempt = V3SearchAttempt(
            attempt_id=request.attempt_id,
            proposition_id=request.proposition_id,
            pass_id=request.pass_id,
            stage_id=request.stage_id,
            intent_id=intent.id,
            query=query,
            query_hash=canonical_hash(query),
            source_scope_hash=stage.scope.authorized_source_scope_hash,
        )
        if request.supersede_attempt_id is None:
            if request.supersession_rationale is not None:
                raise V3EvidenceRuntimeError(
                    "a supersession rationale requires an attempt to supersede"
                )
            workflow = start_v3_search_attempt(state.workflow, attempt)
        else:
            if not request.supersession_rationale or not request.supersession_rationale.strip():
                raise V3EvidenceRuntimeError("superseding a Search attempt requires a rationale")
            workflow = supersede_v3_search_attempt(
                state.workflow,
                old_attempt_id=request.supersede_attempt_id,
                replacement=attempt,
                rationale=request.supersession_rationale,
            )
            attempt = next(
                item for item in workflow.attempts if item.attempt_id == request.attempt_id
            )
        page = self._search.search_page(
            attempt.query,
            issuance_context=self._attempt_issuance_context(attempt.attempt_id),
            scope=self._search_scope(stage),
            policy=self._search_policy,
        )
        workflow = record_v3_page_exposure(workflow, attempt_id=attempt.attempt_id, page=page)
        return self._persist(workflow, expected_content_hash=state.content_hash, page=page)

    def continue_search_page(
        self, request: V3EvidenceSearchContinuationRequest
    ) -> V3EvidenceRuntimeResult:
        """Continue only the exact selected attempt under its stored query and scope."""

        state = self._current(request.expected_content_hash)
        attempt = next(
            (item for item in state.workflow.attempts if item.attempt_id == request.attempt_id),
            None,
        )
        if attempt is None or attempt.kind is not V3AttemptKind.SELECTED:
            raise V3EvidenceUnknownNavigationTarget(
                "continuation requires a current selected Search attempt"
            )
        stage, _ = self._resolve_search_target(
            attempt.proposition_id, attempt.pass_id, attempt.stage_id, attempt.intent_id
        )
        if not stage.scope.authorized_source_ids:
            raise V3EvidenceRuntimeError("an empty materialized source scope cannot be continued")
        page = self._search.search_page(
            attempt.query,
            issuance_context=self._attempt_issuance_context(attempt.attempt_id),
            continuation=request.continuation,
            scope=self._search_scope(stage),
            continue_reason=request.continue_reason,
            continue_rationale=request.continue_rationale,
            policy=self._search_policy,
        )
        workflow = record_v3_page_exposure(state.workflow, attempt_id=attempt.attempt_id, page=page)
        return self._persist(workflow, expected_content_hash=state.content_hash, page=page)

    def submit_page_triage(self, request: V3EvidencePageTriageRequest) -> V3EvidenceRuntimeResult:
        """Append a complete, one-time triage partition for exposed candidate pages."""

        state = self._current(request.expected_content_hash)
        workflow = submit_v3_page_triage(
            state.workflow,
            submission_id=request.submission_id,
            attempt_id=request.attempt_id,
            page_handles=request.page_handles,
            revisions=request.revisions,
        )
        return self._persist(workflow, expected_content_hash=state.content_hash)

    def record_navigation_completion(
        self, *, expected_content_hash: ContentHash, receipt: V3NavigationCompletionReceipt
    ) -> V3EvidenceRuntimeResult:
        """Persist an engine-issued non-Search completion receipt when supported later."""

        state = self._current(expected_content_hash)
        _, intent = self._resolve_target(
            receipt.proposition_id, receipt.pass_id, receipt.stage_id, receipt.intent_id
        )
        if intent.kind is EvidenceNavigationIntentKind.SEARCH:
            raise UnsupportedV3EvidenceNavigationIntent(
                "Search intents complete through bounded traversal, not a completion receipt"
            )
        workflow = record_v3_navigation_completion(state.workflow, receipt)
        return self._persist(workflow, expected_content_hash=state.content_hash)

    def record_acquisition_attempt(
        self, *, expected_content_hash: ContentHash, receipt: V3AcquisitionAttemptReceipt
    ) -> V3EvidenceRuntimeResult:
        """Persist an exact engine-issued unavailable-Source acquisition receipt."""

        state = self._current(expected_content_hash)
        workflow = record_v3_acquisition_attempt(state.workflow, receipt)
        return self._persist(workflow, expected_content_hash=state.content_hash)

    def submit_stage_outcome(
        self, *, expected_content_hash: ContentHash, submission: V3EvidenceStageOutcomeSubmission
    ) -> V3EvidenceRuntimeResult:
        """Append a reducer-validated stage outcome, including trigger dispositions."""

        state = self._current(expected_content_hash)
        self._resolve_stage(submission.proposition_id, submission.pass_id, submission.stage_id)
        scope = next(
            item
            for item in state.workflow.stage_scopes
            if (
                item.proposition_id,
                item.pass_id,
                item.stage_id,
            )
            == (
                submission.proposition_id,
                submission.pass_id,
                submission.stage_id,
            )
        )
        source_unavailability_contributes = any(
            item.kind.value == "source_unavailable" for item in scope.role_limitations
        )
        needs_acquisition_receipt = (
            submission.outcome_kind.value == "source_unavailable_after_attempt"
            or (
                submission.outcome_kind.value == "scope_limitation_unresolved"
                and source_unavailability_contributes
            )
        )
        if needs_acquisition_receipt and submission.acquisition_receipt_id is None:
            matching = tuple(
                item
                for item in state.workflow.acquisition_receipts
                if (
                    item.proposition_id,
                    item.pass_id,
                    item.stage_id,
                    item.materialized_scope_id,
                )
                == (
                    submission.proposition_id,
                    submission.pass_id,
                    submission.stage_id,
                    submission.materialized_scope_id,
                )
            )
            if len(matching) != 1:
                raise V3EvidenceRuntimeError(
                    "source-unavailable outcome has no exact engine-issued acquisition receipt"
                )
            enriched = submission.model_copy(
                update={"acquisition_receipt_id": matching[0].receipt_id, "content_hash": ""}
            )
            payload = enriched.model_dump(mode="json")
            payload["content_hash"] = None
            submission = enriched.model_copy(update={"content_hash": canonical_hash(payload)})
        workflow = submit_evidence_stage_outcome(state.workflow, submission)
        return self._persist(workflow, expected_content_hash=state.content_hash)

    def _current(self, expected_content_hash: ContentHash) -> V3EvidenceNavigationState:
        state = self.load()
        if state.content_hash != expected_content_hash:
            raise ConcurrentEvidenceNavigationUpdate(
                "v3 navigation state changed; reload and retry"
            )
        return state

    def _persist(
        self,
        workflow: V3EvidenceWorkflowState,
        *,
        expected_content_hash: ContentHash,
        page: EvidenceSearchPage | None = None,
        blockers: tuple[str, ...] = (),
    ) -> V3EvidenceRuntimeResult:
        state = new_v3_navigation_state(workflow=workflow)
        self._store.save(state, expected_content_hash=expected_content_hash)
        return V3EvidenceRuntimeResult(
            state=state,
            progress=v3_coverage_progress(workflow),
            page=page,
            blockers=blockers,
        )

    def _validate_initial_state(self) -> None:
        self._validate_workflow(self._initial_workflow)
        if (
            self._search_policy.policy_id,
            canonical_hash(self._search_policy),
        ) != (
            self._initial_workflow.search_policy_id,
            self._initial_workflow.search_policy_hash,
        ):
            raise V3EvidenceContextMismatch(
                "injected Search policy does not match the engine-owned workflow policy"
            )
        read_policy = EvidenceReadPolicy()
        if (
            self._initial_workflow.read_policy_id,
            self._initial_workflow.read_policy_hash,
        ) != (read_policy.policy_id, canonical_hash(read_policy)):
            raise V3EvidenceContextMismatch(
                "workflow Read policy is unsupported; supersede Preparation"
            )

    def _validate_workflow(self, workflow: V3EvidenceWorkflowState) -> None:
        context = self._context
        if (
            workflow.question_id != context.question_id
            or workflow.obligation_hash != context.obligation_hash
            or workflow.inventory_snapshot_hash != context.inventory_snapshot_hash
            or workflow.obligation != context.obligation
            or workflow.authorized_inventory != context.authorized_inventory
            or workflow.stage_scopes != context.stage_scopes
        ):
            raise V3EvidenceContextMismatch(
                "workflow state does not bind the supplied materialized evidence context"
            )
        if (
            workflow.search_policy_id,
            workflow.search_policy_hash,
        ) != (self._search_policy.policy_id, canonical_hash(self._search_policy)):
            raise V3EvidenceContextMismatch(
                "workflow Search policy is unsupported; supersede Preparation"
            )
        read_policy = EvidenceReadPolicy()
        if (workflow.read_policy_id, workflow.read_policy_hash) != (
            read_policy.policy_id,
            canonical_hash(read_policy),
        ):
            raise V3EvidenceContextMismatch(
                "workflow Read policy is unsupported; supersede Preparation"
            )

    def _resolve_search_target(
        self,
        proposition_id: Identifier,
        pass_id: Identifier,
        stage_id: Identifier,
        intent_id: Identifier,
    ) -> tuple[EvidenceContextStage, EvidenceNavigationIntent]:
        stage, intent = self._resolve_target(proposition_id, pass_id, stage_id, intent_id)
        if intent.kind is not EvidenceNavigationIntentKind.SEARCH:
            raise UnsupportedV3EvidenceNavigationIntent(
                f"v3 runtime supports Search only; {intent.kind.value} is not implemented"
            )
        return stage, intent

    def _resolve_target(
        self,
        proposition_id: Identifier,
        pass_id: Identifier,
        stage_id: Identifier,
        intent_id: Identifier | None,
    ) -> tuple[EvidenceContextStage, EvidenceNavigationIntent]:
        stage = self._resolve_stage(proposition_id, pass_id, stage_id)
        if intent_id is not None:
            intent = next((item for item in stage.navigation_intents if item.id == intent_id), None)
            if intent is not None:
                return stage, intent
        raise V3EvidenceUnknownNavigationTarget(
            "request must name one exact materialized proposition, pass, stage, and intent"
        )

    def _resolve_stage(
        self, proposition_id: Identifier, pass_id: Identifier, stage_id: Identifier
    ) -> EvidenceContextStage:
        for proposition in self._context.propositions:
            if proposition.proposition_id != proposition_id:
                continue
            for evidence_pass in proposition.passes:
                if evidence_pass.pass_id != pass_id:
                    continue
                for stage in evidence_pass.stages:
                    if stage.stage_id != stage_id:
                        continue
                    return stage
        raise V3EvidenceUnknownNavigationTarget(
            "request must name one exact materialized proposition, pass, and stage"
        )

    def _require_exact_source_ids(
        self, source_ids: tuple[Identifier, ...], stage: EvidenceContextStage
    ) -> None:
        # Public v3 Search carries semantic terms only. The engine injects
        # the materialized scope; callers may not narrow or widen it.
        if source_ids not in {(), stage.scope.authorized_source_ids}:
            raise V3EvidenceSourceScopeMismatch(
                "caller Source IDs cannot differ from the engine-authorized stage scope"
            )

    def _search_scope(self, stage: EvidenceContextStage) -> EvidenceScope:
        selected = {
            item.source_id: item
            for item in self._context.authorized_inventory
            if item.source_id in stage.scope.authorized_source_ids
        }
        if tuple(selected) != stage.scope.authorized_source_ids:
            raise V3EvidenceContextMismatch(
                "materialized stage scope names an unknown inventory Source"
            )
        return EvidenceScope(
            result_id=self._initial_workflow.result_id,
            domain_id=self._initial_workflow.domain_id,
            question_id=self._initial_workflow.question_id,
            source_ids=stage.scope.authorized_source_ids,
            parse_ids=tuple(
                selected[source_id].parse_id for source_id in stage.scope.authorized_source_ids
            ),
        )

    def _attempt_issuance_context(self, attempt_id: Identifier) -> str:
        """Namespace index tokens to the exact durable v3 Search attempt."""

        return f"evidence-navigation-v3:{self._initial_workflow.run_id}:{attempt_id}"
