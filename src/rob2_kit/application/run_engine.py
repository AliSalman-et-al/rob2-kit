"""Typed host-neutral application boundary for lean-v1 Runs."""
# ruff: noqa: E501

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image, ImageDraw
from pydantic import field_validator

from rob2_kit.application.active_question_frontier import (
    QuestionAnswerCommitStep,
    QuestionAnswerCorrection,
    QuestionDiagnosticStop,
    QuestionEvidenceBundleBinding,
    active_question_frontier,
    effective_question_steps,
    evidence_closure_from_workflow,
    evidence_diagnostic_from_workflow,
)
from rob2_kit.application.contracts import (
    ConfirmedRunDefinition,
    ConfirmRunDefinitionRequest,
    ConfirmRunDefinitionResponse,
    ContinueRunRequest,
    ContinueRunResponse,
    CorrectQuestionStepRequest,
    CorrectQuestionStepResponse,
    DomainContextPack,
    ErrorClass,
    EvidencePassageInput,
    GetWorkContextRequest,
    GetWorkContextResponse,
    InspectVisualCandidateRequest,
    InspectVisualCandidateResponse,
    IntegrityFailure,
    MaterializeQuestionEvidenceBundleRequest,
    MaterializeQuestionEvidenceBundleResponse,
    OperationError,
    PrepareRunRequest,
    PrepareRunResponse,
    ProposalDiscoveryPassQuery,
    ProposalDiscoveryPolicy,
    ProposalPromotionBatchInput,
    QuestionVisualProvenanceInput,
    ReadEvidenceRequest,
    ReadEvidenceResponse,
    ReopenResultRequest,
    ReprioritizeResultsRequest,
    ResultControlResponse,
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
    SubmitEvidenceReviewRequest,
    SubmitEvidenceReviewResponse,
    SubmitEvidenceStageOutcomeRequest,
    SubmitEvidenceStageOutcomeResponse,
    SubmitProposalDiscoveryReviewRequest,
    SubmitProposalDiscoveryReviewResponse,
    SubmitQuestionStepRequest,
    SubmitQuestionStepResponse,
    SubmitResultMappingReviewRequest,
    SubmitResultMappingReviewResponse,
    SubmitResultResolutionRequest,
    SubmitResultResolutionResponse,
    SubmitRunProposalRequest,
    SubmitRunProposalResponse,
    SubmitSourceChronologyReviewRequest,
    SubmitSourceChronologyReviewResponse,
    SubmitSourceRoleReviewRequest,
    SubmitSourceRoleReviewResponse,
    TrialContextSummary,
    WithdrawResultRequest,
    WorkContext,
    WorkflowCondition,
    WorkItem,
    WorkToken,
)
from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    EvidenceContextInventorySource,
    EvidenceContextUnitOrientation,
)
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.evidence_runtime import (
    V3EvidencePageTriageRequest,
    V3EvidenceSearchContinuationRequest,
    V3EvidenceSearchRequest,
)
from rob2_kit.application.lifecycle import (
    LifecycleIntegrityError,
    LifecycleProjection,
    ResultState,
    RunState,
    derive_lifecycle,
)
from rob2_kit.application.proposals import (
    _locator_binds_source,
    _locator_page,
    _source_pages,
    effective_result_ids,
    proposal_pairings,
    semantic_diff,
    validate_result_sources,
)
from rob2_kit.application.question_evidence_bundle import (
    QuestionEvidenceBundleMaterializationInput,
    ResolvedQuestionEvidenceClaim,
    ResolvedQuestionEvidenceReview,
    ResolvedQuestionVisualTranscription,
)
from rob2_kit.application.question_evidence_bundle import (
    materialize_question_evidence_bundle as build_question_evidence_bundle,
)
from rob2_kit.application.question_evidence_session import (
    QuestionEvidenceSessionProjection,
    QuestionEvidenceSessionService,
    QuestionEvidenceSessionStore,
    QuestionEvidenceTransitionReceipt,
    StaleQuestionEvidenceSession,
    new_question_evidence_session,
)
from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    DecisionTrace,
    FinalJudgmentRevision,
    JudgmentLevel,
    SQAnswerRevision,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes, sha256_digest
from rob2_kit.domain.evidence import (
    ConsiderationDisposition,
    EvidenceBundle,
    EvidenceClaim,
    EvidenceConsiderationManifest,
    EvidenceCoverageState,
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    TrialAttribution,
    V3EvidenceCoverageReceiptRecord,
    VisualTranscription,
)
from rob2_kit.domain.releases import PolicyKind, PolicyRelease
from rob2_kit.domain.results import (
    ProposalDiscoveryCoverageReceipt,
    ProposalLimitation,
    ProposalLimitationKind,
    ProposalMappingStatus,
    ReportedCandidateProvenance,
    ResultIdentityCompleteness,
    ResultSpecRevision,
    derive_result_spec_revision_id,
)
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
from rob2_kit.domain.sources import (
    SourceDescriptor,
    SourceInventoryRevision,
    SourceRole,
)
from rob2_kit.evidence.errors import (
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    RetrievalFailure,
    ScopeMismatch,
    StaleSearchContinuation,
    StaleWorkToken,
)
from rob2_kit.evidence.obligations import compile_guidance_obligations
from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalEvidenceUnit,
    CanonicalPage,
    CanonicalUnitKind,
    CanonicalWordBox,
    DocumentZone,
    EvidenceReadPolicy,
    EvidenceScope,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    SearchQuery,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.visual import (
    VisualCandidate,
    VisualInspectionPolicy,
    build_visual_citation,
)
from rob2_kit.evidence.workflow import (
    V3EvidenceWorkflowState,
    V3ScopeLimitationKind,
    V3SourceChronologyFact,
)
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
from rob2_kit.release import (
    installed_release_fingerprint,
    load_release_lock,
    release_root,
    verify_ownership_identities,
)
from rob2_kit.reports import (
    AssessmentView,
    DiagnosticReportProjector,
    DiagnosticView,
    DomainView,
    EstimateView,
    EvidenceView,
    ReportProjector,
    ResultDetailsView,
    ResultIdentityView,
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
    LeaseConflictError,
    LeaseToken,
    LedgerSchemaRefusal,
    RunIntegrityFailure,
    Transition,
    WorkflowEvent,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from rob2_kit.storage.ledger import ArtifactVerificationCache

ENGINE_ACTOR = Actor(
    kind=ActorKind.SYSTEM,
    actor_id="actor:run-engine",
    display_name="rob2-kit RunEngine",
    software_name="rob2-kit",
    software_version="0.1.0",
)


class VisualAssetMaterializationError(RuntimeError):
    """A visual citation could not be materialized atomically."""


_DEFAULT_EVIDENCE_RECOVERY = ("Resubmit only the corrected field(s).",)


def _evidence_violation(detail: str, *, recovery: tuple[str, ...] | None = None) -> OperationError:
    """Build one evidence-submission violation for a batched OperationError."""

    return OperationError(
        code="invalid_configuration",
        detail=detail,
        recovery=recovery or _DEFAULT_EVIDENCE_RECOVERY,
    )


def _canonical_word_boxes(text: str, words: tuple[object, ...]) -> tuple[CanonicalWordBox, ...]:
    """Retain parser word geometry only when it binds unambiguously to text."""

    if not words:
        return ()
    cursor = 0
    boxes: list[CanonicalWordBox] = []
    for word in words:
        token = str(getattr(word, "text", ""))
        if not token:
            return ()
        start = text.find(token, cursor)
        if start < 0:
            # Never guess character offsets from a parser's word stream.
            return ()
        end = start + len(token)
        try:
            x = float(getattr(word, "x"))
            y = float(getattr(word, "y"))
            width = float(getattr(word, "width"))
            height = float(getattr(word, "height"))
            boxes.append(
                CanonicalWordBox(
                    text=token,
                    span_start=start,
                    span_end=end,
                    spatial=(x, y, x + width, y + height),
                )
            )
        except (TypeError, ValueError):
            return ()
        cursor = end
    return tuple(boxes)


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
    initialization: ProjectInitialization
    input_snapshot_hash: ContentHash
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
    submission: SubmitRunProposalRequest | None = None
    next_action: RunOperation = RunOperation.CONFIRM_RUN_DEFINITION


class _ProposalDiscoveryNavigationRecord(FrozenModel):
    """Durable, engine-authored token navigation proof."""

    run_id: Identifier
    work_token: WorkToken
    navigation: dict[str, Any]


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


class _ResultAssessmentCorrectedRecord(FrozenModel):
    """Lifecycle marker reopening a completed assessment without refreezing Evidence."""

    run_id: Identifier
    result_id: Identifier
    correction_key: Identifier


class _ResultWorkOrderRecord(FrozenModel):
    """Attributable, confirmed-scope-preserving order for still-pending Results."""

    run_id: Identifier
    result_ids: tuple[Identifier, ...]
    requested_by: Actor


class _ResultWithdrawalRecord(FrozenModel):
    """A human Result withdrawal that intentionally yields a diagnostic terminal state."""

    run_id: Identifier
    result_id: Identifier
    trial_id: Identifier
    reason: str
    requested_by: Actor


class _ResultReopenedRecord(FrozenModel):
    """An explicit reopening of a previously withdrawn Result."""

    run_id: Identifier
    result_id: Identifier
    requested_by: Actor


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
    preparation_outcome: Literal["trial_failed", "preparation_incomplete", "result_withdrawn"] = (
        "preparation_incomplete"
    )
    recovery: tuple[str, ...] = (
        "Correct the documented Result-scoped problem and continue the Run.",
    )
    report_root: str | None = None
    artifact_names: tuple[str, ...] = ()
    staging_root: str | None = None

    @field_validator("recovery")
    @classmethod
    def validate_recovery(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("diagnostic recovery requires at least one nonblank action")
        return value


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
    review_revisions: tuple[RecordReference, ...] = ()
    # Historical submissions remain parseable without retaining their active
    # request contract at the application boundary.
    candidate_dispositions: tuple[dict[str, Any], ...] = ()
    project_rules: tuple[RecordReference, ...] = ()
    submission: dict[str, Any] | None = None


class _EvidenceReviewRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    submission: SubmitEvidenceReviewRequest
    workflow_state_hash: ContentHash


class _QuestionStepRecord(FrozenModel):
    """Run-ledger half of an already durable v3 session transition."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    frontier_entry_hash: ContentHash | None = None
    transition_receipt_hash: ContentHash
    diagnostic_terminal: bool = False
    submission: SubmitQuestionStepRequest


class _QuestionCorrectionRecord(FrozenModel):
    """Run-ledger receipt for a durable immutable question correction."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    transition_receipt_hash: ContentHash
    submission: CorrectQuestionStepRequest


class _QuestionEvidenceBundleProductionRecord(FrozenModel):
    """Receipt proving that the engine, rather than a caller, froze a bundle."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    question_id: Identifier
    session_content_hash: ContentHash
    navigation_state_hash: ContentHash
    evidence_bundle: QuestionEvidenceBundleBinding


class _SourceChronologyReviewRecord(FrozenModel):
    """One immutable source/parse-bound chronology fact."""

    run_id: Identifier
    submission: SubmitSourceChronologyReviewRequest


class _EvidenceStageOutcomeRecord(FrozenModel):
    run_id: Identifier
    submission: SubmitEvidenceStageOutcomeRequest
    navigation_state_hash: ContentHash


class _HistoricalFinalJudgmentInput(FrozenModel):
    """Read-only shape for final-judgment departures in older ledger records."""

    domain_id: Identifier
    judgment: JudgmentLevel
    alternative: JudgmentLevel
    material_bias_rationale: str
    cited_evidence: tuple[RecordReference, ...]


class _DomainAnswersRecord(FrozenModel):
    """Normalized signaling-question answers for one Result × domain."""

    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    answers: dict[Identifier, str]
    rationales: dict[Identifier, str]
    assessor_inputs: dict[Identifier, bool] = {}
    final_judgment_departures: tuple[_HistoricalFinalJudgmentInput, ...] = ()
    project_rules: tuple[RecordReference, ...] = ()
    answer_revisions: tuple[RecordReference, ...] = ()
    correction_token: WorkToken | None = None
    submission: dict[str, Any] | None = None


class _ResultStartedRecord(FrozenModel):
    run_id: Identifier
    result_id: Identifier


class _ResultAssessmentReadyRecord(FrozenModel):
    """Scientific assessment checkpoint retained when report rendering fails."""

    run_id: Identifier
    result_id: Identifier
    assessment_revision_id: Identifier
    assessment: AssessmentView
    answers: dict[Identifier, str]
    rationales: dict[Identifier, str]
    active_question_ids: tuple[Identifier, ...]
    inactive_question_ids: tuple[Identifier, ...]
    matched_rule_ids: tuple[Identifier, ...]
    assessor_inputs: dict[Identifier, bool]
    judgment_references: tuple[RecordReference, ...]
    final_judgment_references: tuple[RecordReference, ...]


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
        report_projector_factory: Callable[[Any], Any] | None = None,
        lease_acquirer: Callable[[WorkflowLedger, datetime], LeaseToken] | None = None,
    ) -> None:
        self._root: Path | None = None
        self._ownership_verified = False
        self._parser = parser
        # Keep the adapter injectable for recorded HTTP fixtures.  The default
        # is constructed lazily in ``prepare_run`` after the project root is
        # known, so its cache is always project-local.
        self._registry_adapter = registry_adapter or registry
        self._registry_client: Any | None = None
        self._authorized_root: Path | None = None
        self._owner_id = f"owner:run-engine:{os.getpid()}:{uuid.uuid4()}"
        self._report_projector_factory = report_projector_factory or ReportProjector
        self._lease_acquirer = lease_acquirer
        # Content-addressed Source artifacts are immutable once written, so a
        # hash verified once by preflight() needn't be re-read from disk by a
        # later call in this same process (#130). Process-lifetime only, like
        # A new process gets a fresh, empty set and re-verifies everything.
        self._verification_cache = ArtifactVerificationCache()
        # Compatibility projection for #130's observable process cache.
        self._verified_artifact_hashes = self._verification_cache.verified_hashes
        self._run_event_cache: dict[
            tuple[Path, Identifier], tuple[tuple[int, str], tuple[WorkflowEvent, ...]]
        ] = {}
        self._logic_pack_cache: tuple[str, Any] | None = None
        self._guidance_pack_cache: tuple[str, Any] | None = None
        # Proposal discovery is pre-confirmation navigation, not Evidence
        # workflow state. It is nevertheless tracked under the exact issued
        # work token so a receipt can only claim pages/units this engine
        # actually exposed in the current bounded review.
        self._proposal_discovery_navigation: dict[
            tuple[Identifier, Identifier], dict[str, Any]
        ] = {}

    def __getattr__(self, name: str) -> Any:
        """Expose the canonical status spelling without expanding the legacy API.

        ``run_status`` is retained as the compatibility operation during the
        expand phase.  Resolving ``get_run_status`` dynamically keeps the
        fixed RunEngine method inventory stable for existing callers while
        allowing the canonical MCP route to use the agreed name.
        """

        if name == "get_run_status":
            return self.run_status
        raise AttributeError(name)

    def _now(self) -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _search_ledger_cursor(event_count: int) -> str:
        """Validate and publish Search's actual numeric ledger cursor."""
        if event_count < 0 or event_count > 18_446_744_073_709_551_615:
            raise OperationalRetrievalFailure(
                "Search ledger event count exceeds the u64 reservation"
            )
        return f"ledger:{event_count}"

    def _ledger(self, path: Path, artifacts: ArtifactStore) -> WorkflowLedger:
        return WorkflowLedger(
            path,
            artifacts,
            now=self._now,
            event_identifiers=None,
            verification_cache=self._verification_cache,
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
        else:
            self._authorized_root = None
        state_root = root / ".rob2"
        ledger_path = state_root / "ledger.sqlite3"
        if not request.authorized and not ledger_path.is_file():
            return self._prepare_root_authorization_required(
                root,
                detail="Run preparation requires explicit project-root authorization.",
                recovery=(
                    "Retry prepare_run with authorized=true after explicit operator authorization.",
                ),
            )
        try:
            artifacts = ArtifactStore(state_root / "artifacts")
            ledger = self._ledger(ledger_path, artifacts)
            ledger.preflight()
            self._verify_project_ownership(root)
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
            if (
                projection.run_state is RunState.AWAITING_CONFIRMATION
                and not self._has_durable_proposal(ledger, current.run_id)
            ):
                try:
                    changed = self._input_snapshot_hash(root) != current.input_snapshot_hash
                except ValueError as error:
                    return self._prepare_configuration_error(root, ledger, error)
                if changed:
                    return self._prepare_authorization_error(
                        ledger,
                        current.run_id,
                        None,
                    )
                return PrepareRunResponse(
                    operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, current.run_id),
                    ledger_cursor=f"ledger:{len(ledger.events())}",
                    affected_scope=(current.run_id,),
                    condition=WorkflowCondition.CONFIRMATION_REQUIRED,
                    committed=False,
                    next_action=(
                        self._next_work_item(ledger, current.run_id).operation
                        if self._next_work_item(ledger, current.run_id) is not None
                        else RunOperation.CONTINUE_RUN
                    ),
                    run_id=current.run_id,
                    run_state=projection.run_state,
                    initialization=current.initialization,
                    proposal=None,
                )
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
                initialization = self._bind_declared_result_spec_supersessions(
                    ledger, initialization, run_id=current.run_id
                )
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
                                        entity_id=(
                                            f"run-result-spec-supersession:{supersede_suffix}"
                                        ),
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
                                        preparation_outcome="trial_failed",
                                        recovery=(
                                            "Provide the required readable Trial Source and "
                                            "continue the Run.",
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
                                        preparation_outcome="trial_failed",
                                        recovery=(
                                            "Provide the required readable Trial Source and "
                                            "continue the Run.",
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
                                        preparation_outcome="trial_failed",
                                        recovery=(
                                            "Provide the required readable Trial Source and "
                                            "continue the Run.",
                                        ),
                                    ),
                                    checkpoint=f"checkpoint:result-diagnostic-{diagnostic_suffix}",
                                    outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                                    observed_at=now,
                                ),
                            )
                        )
                    lease = self._acquire_lease(ledger, now)
                    committed = self._commit_transitions(ledger, tuple(transitions), lease, now=now)
                    result = committed[0]
                    return PrepareRunResponse(
                        operation_id=result.operation_id,
                        ledger_cursor=f"ledger:{committed[-1].sequence}",
                        affected_scope=(current.run_id,),
                        condition=WorkflowCondition.CONFIRMATION_REQUIRED,
                        committed=not result.duplicate,
                        next_action=RunOperation.SUBMIT_RUN_PROPOSAL,
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
                next_action=self._next_action_for_state(projection.run_state),
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
            return self._prepare_root_authorization_required(
                root,
                ledger=ledger,
                detail="Starting a new Run requires explicit project-root authorization.",
                recovery=(
                    "Retry prepare_run with authorized=true and start_new=true after "
                    "explicit operator authorization.",
                ),
            )

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
        initialization = self._bind_declared_result_spec_supersessions(ledger, initialization)
        # The typed boundary owns the evidence index used by its read/search
        # operations.  Indexing is deterministic and happens once at prepare
        # time, so a fresh MCP process can resume from the durable index.
        self._index_initial_evidence(root, initialization)
        run_id = self._new_run_id(root, len(ledger.events()))
        try:
            input_snapshot_hash = self._input_snapshot_hash(root)
        except ValueError as error:
            return self._prepare_configuration_error(root, ledger, error)
        now = self._now()
        prepared = _PreparedRunRecord(
            run_id=run_id,
            initialization=initialization,
            input_snapshot_hash=input_snapshot_hash,
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
                ),
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
                            preparation_outcome="trial_failed",
                            recovery=(
                                "Provide the required readable Trial Source and continue the Run.",
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
                            preparation_outcome="trial_failed",
                            recovery=(
                                "Provide the required readable Trial Source and continue the Run.",
                            ),
                        ),
                        checkpoint=f"checkpoint:result-diagnostic-{diagnostic_suffix}",
                        outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
                        observed_at=now,
                    ),
                )
            )
        lease = self._acquire_lease(ledger, now)
        committed = self._commit_transitions(ledger, tuple(transitions), lease, now=now)
        projection = self._projection(ledger, run_id)
        return PrepareRunResponse(
            operation_id=committed[prepared_transition_index].operation_id,
            ledger_cursor=f"ledger:{committed[-1].sequence}",
            affected_scope=tuple(item.run_id for item in unfinished) + (run_id,),
            condition=WorkflowCondition.CONFIRMATION_REQUIRED,
            committed=True,
            next_action=self._next_work_item(ledger, run_id).operation
            if self._next_work_item(ledger, run_id) is not None
            else RunOperation.CONTINUE_RUN,
            run_id=run_id,
            run_state=projection.run_state,
            initialization=initialization,
            proposal=None,
        )

    def reprioritize_results(self, request: ReprioritizeResultsRequest) -> ResultControlResponse:
        """Persist a complete replacement order for pending Results only."""

        ledger = self._bound_ledger(request.run_id)
        projection = self._projection(ledger, request.run_id)
        if request.requested_by.kind is not ActorKind.HUMAN:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REPRIORITIZE_RESULTS,
                projection,
                detail="Only a human may reprioritize pending Results.",
                recovery=("Resubmit this request with an attributable human actor.",),
                code="human_actor_required",
            )
        existing = self._event_for_operation_key(ledger, request.idempotency_key)
        if existing is not None:
            if existing.operation == "operation:result-work-order" and (
                _ResultWorkOrderRecord.model_validate(self._event_payload(ledger, existing))
                == _ResultWorkOrderRecord(
                    run_id=request.run_id,
                    result_ids=request.result_ids,
                    requested_by=request.requested_by,
                )
            ):
                return self._result_control_duplicate(
                    ledger, request.run_id, projection, existing, RunOperation.REPRIORITIZE_RESULTS
                )
            return self._result_control_key_conflict(
                ledger, request.run_id, RunOperation.REPRIORITIZE_RESULTS, projection
            )
        if projection.run_state is not RunState.ASSESSING:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REPRIORITIZE_RESULTS,
                projection,
                detail="Results can be reprioritized only while the Run is assessing.",
                recovery=("Continue the assessing Run from its durable checkpoint.",),
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        ordered = self._result_ids(ledger, request.run_id, proposal)
        states = {item.result_id: item.state for item in projection.results}
        pending = tuple(
            result_id
            for result_id in ordered
            if states.get(result_id, ResultState.PENDING) is ResultState.PENDING
        )
        if set(request.result_ids) != set(pending) or len(request.result_ids) != len(pending):
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REPRIORITIZE_RESULTS,
                projection,
                detail="Reprioritization must name each and only pending Results exactly once.",
                recovery=("Read run_status and resubmit the current pending Result order.",),
            )
        now = self._now()
        record = _ResultWorkOrderRecord(
            run_id=request.run_id,
            result_ids=request.result_ids,
            requested_by=request.requested_by,
        )
        transition = self._transition(
            scope=request.run_id,
            operation="operation:result-work-order",
            operation_key=request.idempotency_key,
            entity_id=f"result-work-order:{self._digest(f'{request.run_id}|{request.idempotency_key}')}",
            revision_id=f"revision:result-work-order-{self._digest(f'{request.run_id}|{request.idempotency_key}')}",
            artifact=record,
            checkpoint="checkpoint:result-work-order",
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=now,
            actor=request.requested_by,
        )
        committed = ledger.commit(transition, self._acquire_lease(ledger, now), now=now)
        result_order = self._result_ids(ledger, request.run_id, proposal)
        return ResultControlResponse(
            operation_id=committed.operation_id,
            ledger_cursor=f"ledger:{committed.sequence}",
            affected_scope=(request.run_id,) + result_order,
            condition=WorkflowCondition.ACCEPTED,
            committed=not committed.duplicate,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            result_order=result_order,
        )

    def withdraw_result(self, request: WithdrawResultRequest) -> ResultControlResponse:
        """Commit a Result-scoped diagnostic without blocking unaffected Results."""

        ledger = self._bound_ledger(request.run_id)
        projection = self._projection(ledger, request.run_id)
        if not self._has_durable_proposal(ledger, request.run_id):
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=(
                    self._next_work_item(ledger, request.run_id).operation
                    if self._next_work_item(ledger, request.run_id) is not None
                    else RunOperation.CONTINUE_RUN
                ),
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=None,
                error=OperationError(
                    code="invalid_configuration",
                    detail="The first RunProposal is issued only after terminal full-text discovery.",
                    recovery=("Complete every issued discovery review first.",),
                ),
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        if request.requested_by.kind is not ActorKind.HUMAN:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.WITHDRAW_RESULT,
                projection,
                detail="Only a human may withdraw a Result.",
                recovery=("Resubmit this request with an attributable human actor.",),
                code="human_actor_required",
                result_id=request.result_id,
            )
        existing = self._event_for_operation_key(ledger, request.idempotency_key)
        if existing is not None:
            withdrawal = self._event_for_operation_key(
                ledger, f"{request.idempotency_key}:withdrawal"
            )
            if (
                existing.operation == "operation:result-diagnostic-ready"
                and withdrawal is not None
                and withdrawal.operation == "operation:result-withdrawn"
                and _ResultWithdrawalRecord.model_validate(self._event_payload(ledger, withdrawal))
                == _ResultWithdrawalRecord(
                    run_id=request.run_id,
                    result_id=request.result_id,
                    trial_id=self._trial_id_for_result(request.result_id) or "trial:unknown",
                    reason=request.reason,
                    requested_by=request.requested_by,
                )
            ):
                return self._result_control_duplicate(
                    ledger,
                    request.run_id,
                    projection,
                    existing,
                    RunOperation.WITHDRAW_RESULT,
                    result_id=request.result_id,
                    result_state=ResultState.DIAGNOSTIC_READY,
                )
            return self._result_control_key_conflict(
                ledger,
                request.run_id,
                RunOperation.WITHDRAW_RESULT,
                projection,
                result_id=request.result_id,
            )
        allowed = self._result_ids(ledger, request.run_id, proposal)
        if projection.run_state is not RunState.ASSESSING or request.result_id not in allowed:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.WITHDRAW_RESULT,
                projection,
                detail="The requested Result is not active in this assessing Run.",
                recovery=("Read run_status and choose an active pending Result.",),
                result_id=request.result_id,
            )
        states = {item.result_id: item.state for item in projection.results}
        if states.get(request.result_id, ResultState.PENDING) is not ResultState.PENDING:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.WITHDRAW_RESULT,
                projection,
                detail="A Result can be withdrawn only at a pending safe boundary.",
                recovery=("Continue the Result to its next durable safe boundary.",),
                result_id=request.result_id,
            )
        trial_id = self._trial_id_for_result(request.result_id)
        if trial_id is None:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.WITHDRAW_RESULT,
                projection,
                detail="The requested Result has no exact Trial dependency.",
                recovery=("Resolve the Result against its Trial before withdrawing it.",),
                result_id=request.result_id,
            )
        now = self._now()
        record = _ResultWithdrawalRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            trial_id=trial_id,
            reason=request.reason,
            requested_by=request.requested_by,
        )
        suffix = self._digest(f"{request.run_id}|{request.result_id}|{request.idempotency_key}")
        withdrawal_transition = self._transition(
            scope=request.result_id,
            operation="operation:result-withdrawn",
            operation_key=f"{request.idempotency_key}:withdrawal",
            entity_id=f"result-withdrawal:{suffix}",
            revision_id=f"revision:result-withdrawal-{suffix}",
            artifact=record,
            checkpoint=f"checkpoint:result-withdrawal-{suffix}",
            outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
            observed_at=now,
            actor=request.requested_by,
        )
        diagnostic_transition = self._transition(
            scope=request.result_id,
            operation="operation:result-diagnostic-ready",
            operation_key=request.idempotency_key,
            entity_id=f"result-withdrawal-diagnostic:{suffix}",
            revision_id=f"revision:result-withdrawal-diagnostic-{suffix}",
            artifact=_ResultDiagnosticRecord(
                run_id=request.run_id,
                result_id=request.result_id,
                trial_id=trial_id,
                reason=f"Result withdrawn by {request.requested_by.display_name}: {request.reason}",
                preparation_outcome="result_withdrawn",
                recovery=(
                    "Reopen this withdrawn Result explicitly under the unchanged "
                    "confirmed Run definition.",
                ),
            ),
            checkpoint=f"checkpoint:result-diagnostic-{suffix}",
            outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
            observed_at=now,
            actor=request.requested_by,
        )
        committed = self._commit_transitions(
            ledger,
            (withdrawal_transition, diagnostic_transition),
            self._acquire_lease(ledger, now),
            now=now,
        )
        self._commit_run_completed_if_ready(ledger, request.run_id)
        next_projection = self._projection(ledger, request.run_id)
        return ResultControlResponse(
            operation_id=committed[-1].operation_id,
            ledger_cursor=f"ledger:{committed[-1].sequence}",
            affected_scope=(request.run_id, request.result_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=any(not item.duplicate for item in committed),
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=next_projection.run_state,
            result_id=request.result_id,
            result_state=ResultState.DIAGNOSTIC_READY,
            result_order=self._result_ids(ledger, request.run_id, proposal),
        )

    def reopen_result(self, request: ReopenResultRequest) -> ResultControlResponse:
        """Reopen only a human-withdrawn diagnostic under unchanged confirmed scope."""

        ledger = self._bound_ledger(request.run_id)
        projection = self._projection(ledger, request.run_id)
        if request.requested_by.kind is not ActorKind.HUMAN:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REOPEN_RESULT,
                projection,
                detail="Only a human may reopen a withdrawn Result.",
                recovery=("Resubmit this request with an attributable human actor.",),
                code="human_actor_required",
                result_id=request.result_id,
            )
        existing = self._event_for_operation_key(ledger, request.idempotency_key)
        if existing is not None:
            if existing.operation == "operation:result-reopened" and (
                _ResultReopenedRecord.model_validate(self._event_payload(ledger, existing))
                == _ResultReopenedRecord(
                    run_id=request.run_id,
                    result_id=request.result_id,
                    requested_by=request.requested_by,
                )
            ):
                return self._result_control_duplicate(
                    ledger,
                    request.run_id,
                    projection,
                    existing,
                    RunOperation.REOPEN_RESULT,
                    result_id=request.result_id,
                    result_state=ResultState.PENDING,
                )
            return self._result_control_key_conflict(
                ledger,
                request.run_id,
                RunOperation.REOPEN_RESULT,
                projection,
                result_id=request.result_id,
            )
        if projection.run_state not in {RunState.ASSESSING, RunState.COMPLETE}:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REOPEN_RESULT,
                projection,
                detail="A Result can be reopened only while the Run is assessing or complete.",
                recovery=("Resolve the Run blocker before reopening this Result.",),
                result_id=request.result_id,
            )
        if not any(
            event.operation == "operation:result-withdrawn" and event.scope == request.result_id
            for event in self._events_for_run(ledger, request.run_id)
        ):
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REOPEN_RESULT,
                projection,
                detail="Only an explicitly withdrawn Result can be reopened.",
                recovery=("Choose a Result with a durable human withdrawal record.",),
                result_id=request.result_id,
            )
        state = next(
            (item.state for item in projection.results if item.result_id == request.result_id), None
        )
        if state is not ResultState.DIAGNOSTIC_READY:
            return self._result_control_refusal(
                ledger,
                request.run_id,
                RunOperation.REOPEN_RESULT,
                projection,
                detail="A Result can be reopened only from its diagnostic-ready safe boundary.",
                recovery=("Wait for the Result diagnostic checkpoint, then retry.",),
                result_id=request.result_id,
            )
        now = self._now()
        suffix = self._digest(f"{request.run_id}|{request.result_id}|{request.idempotency_key}")
        transition = self._transition(
            scope=request.result_id,
            operation="operation:result-reopened",
            operation_key=request.idempotency_key,
            entity_id=f"result-reopened:{suffix}",
            revision_id=f"revision:result-reopened-{suffix}",
            artifact=_ResultReopenedRecord(
                run_id=request.run_id,
                result_id=request.result_id,
                requested_by=request.requested_by,
            ),
            checkpoint=f"checkpoint:result-reopened-{suffix}",
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=now,
            actor=request.requested_by,
        )
        transitions = (transition,)
        if projection.run_state is RunState.COMPLETE:
            proposal = self._latest_proposal(ledger, request.run_id)
            reopen_run = self._transition(
                scope=request.run_id,
                operation="operation:run-reopened",
                operation_key=f"{request.idempotency_key}:run",
                entity_id=f"run-reopened:{suffix}",
                revision_id=f"revision:run-reopened-{suffix}",
                artifact=_RunReopenedRecord(
                    run_id=request.run_id,
                    input_snapshot_hash=proposal.input_snapshot_hash,
                    invalidated_result_ids=(request.result_id,),
                ),
                checkpoint=f"checkpoint:run-reopened-{suffix}",
                outcome=WorkflowEventOutcome.WORK_REQUIRED,
                observed_at=now,
                actor=request.requested_by,
            )
            transitions = (reopen_run, transition)
        committed = self._commit_transitions(
            ledger,
            transitions,
            self._acquire_lease(ledger, now),
            now=now,
        )
        proposal = self._latest_proposal(ledger, request.run_id)
        return ResultControlResponse(
            operation_id=committed[-1].operation_id,
            ledger_cursor=f"ledger:{committed[-1].sequence}",
            affected_scope=(request.run_id, request.result_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=any(not item.duplicate for item in committed),
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            result_id=request.result_id,
            result_state=ResultState.PENDING,
            result_order=self._result_ids(ledger, request.run_id, proposal),
        )

    def _result_control_refusal(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        operation: RunOperation,
        projection: LifecycleProjection,
        *,
        detail: str,
        recovery: tuple[str, ...],
        code: Literal["invalid_result_control", "human_actor_required"] = "invalid_result_control",
        result_id: Identifier | None = None,
    ) -> ResultControlResponse:
        """Return an expected Result-control refusal through the public envelope."""

        proposal = self._latest_proposal(ledger, run_id)
        return ResultControlResponse(
            operation_id=self._read_operation_id(operation, run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=tuple(item for item in (run_id, result_id) if item is not None),
            condition=WorkflowCondition.STALE,
            committed=False,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=run_id,
            run_state=projection.run_state,
            result_id=result_id,
            result_state=self._result_state(projection, result_id)
            if result_id is not None
            else None,
            result_order=self._result_ids(ledger, run_id, proposal),
            error=OperationError(
                error_class=(
                    ErrorClass.AUTHORITY
                    if code == "human_actor_required"
                    else ErrorClass.CORRECTABLE
                ),
                code=code,
                detail=detail,
                recovery=recovery,
            ),
        )

    def _result_control_duplicate(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        projection: LifecycleProjection,
        event: WorkflowEvent,
        operation: RunOperation,
        *,
        result_id: Identifier | None = None,
        result_state: ResultState | None = None,
    ) -> ResultControlResponse:
        """Return the original durable control outcome for an identical retry."""

        proposal = self._latest_proposal(ledger, run_id)
        return ResultControlResponse(
            operation_id=event.operation_id,
            ledger_cursor=f"ledger:{event.sequence}",
            affected_scope=tuple(item for item in (run_id, result_id) if item is not None),
            condition=WorkflowCondition.ACCEPTED,
            committed=False,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=run_id,
            run_state=projection.run_state,
            result_id=result_id,
            result_state=result_state,
            result_order=self._result_ids(ledger, run_id, proposal),
        )

    def _result_control_key_conflict(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        operation: RunOperation,
        projection: LifecycleProjection,
        *,
        result_id: Identifier | None = None,
    ) -> ResultControlResponse:
        return self._result_control_refusal(
            ledger,
            run_id,
            operation,
            projection,
            detail=(
                "The idempotency key was already committed for different Result-control content."
            ),
            recovery=("Use a new idempotency key for this changed Result-control request.",),
            result_id=result_id,
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
            next_action=self._next_action_for_state(projection.run_state),
            run_id=request.run_id,
            run_state=projection.run_state,
            result_states=(
                tuple(
                    ResultStatus(result_id=item.result_id, state=item.state)
                    for item in projection.results
                    if item.result_id
                    in self._result_ids(
                        ledger,
                        request.run_id,
                        self._latest_proposal(ledger, request.run_id),
                    )
                )
                if self._has_durable_proposal(ledger, request.run_id)
                else ()
            ),
            progress=self._run_progress(ledger, request.run_id, projection),
        )

    def continue_run(self, request: ContinueRunRequest) -> ContinueRunResponse:
        try:
            ledger = self._bound_ledger(request.run_id)
            self._verify_project_ownership(self._required_root())
            current = self._current_prepared_record(ledger)
            if current is not None and current.run_id == request.run_id:
                self._reconcile_execution_contract(ledger, current)
            # The preparation snapshot deliberately precedes the first
            # durable proposal.  Reconciliation and report repair are
            # proposal-scoped, so invoking them during source-role/discovery
            # work would incorrectly require a Result proposal that does not
            # exist yet.
            if self._has_durable_proposal(ledger, request.run_id):
                # Reconciliation is part of every post-proposal continuation.
                # It compares the current confined input snapshot with the
                # last committed checkpoint and commits one idempotent batch
                # when bytes changed.
                self._reconcile_current_run(ledger, request.run_id)
                self._repair_report_publication(ledger, request.run_id)
                self._resume_assessment_ready_reports(ledger, request.run_id)
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
            # Source-role review (#119) is issued here, before proposal
            # submission, so it must be checked ahead of the usual
            # confirmation-required response.
            pending_work = self._next_work_item(ledger, request.run_id)
            if pending_work is not None:
                return self._continue_response(
                    ledger,
                    request.run_id,
                    projection,
                    RunDirective.AGENT_WORK_REQUIRED,
                    committed=False,
                    work_item=pending_work,
                )
            if not self._has_durable_proposal(ledger, request.run_id):
                initialization = self._initialization_with_resolved_source_roles(
                    ledger, request.run_id
                )
                if self._initialization_discovery_complete(initialization, ledger, request.run_id):
                    proposal = self._proposal_from_discovery(initialization, ledger, request.run_id)
                    now = self._now()
                    suffix = self._digest(
                        f"{request.run_id}|empty-discovery|{proposal.proposal_token}"
                    )
                    transition = self._transition(
                        scope=request.run_id,
                        operation="operation:run-proposal-discovery-reviewed",
                        operation_key=f"idempotency:empty-discovery-{suffix}",
                        entity_id=f"run-proposal-discovery:{suffix}",
                        revision_id=f"revision:run-proposal-discovery-{suffix}",
                        artifact=_ProposalSubmittedRecord(run_id=request.run_id, proposal=proposal),
                        checkpoint="checkpoint:run-proposal-discovery-reviewed",
                        outcome=WorkflowEventOutcome.WORK_REQUIRED,
                        observed_at=now,
                    )
                    self._commit_transitions(
                        ledger,
                        (transition,),
                        self._acquire_lease(ledger, now),
                        now=now,
                    )
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
        proposal = (
            self._latest_proposal(ledger, request.run_id)
            if self._has_durable_proposal(ledger, request.run_id)
            else None
        )
        initialization = (
            proposal.initialization
            if proposal is not None
            else self._initialization_with_resolved_source_roles(ledger, request.run_id)
        )
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
        if expected is None or expected.work_token != request.work_token:
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
                for spec in initialization.result_specs
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
                    for spec in initialization.result_specs
                    if spec.result.result_id == work_item.result_id
                ),
                next(
                    (
                        candidate.trial_id
                        for candidate in (
                            proposal.result_candidates
                            if proposal
                            else initialization.result_candidates
                        )
                        if candidate.result_id == work_item.result_id
                    ),
                    None,
                ),
            )
        is_global_source_work = (
            work_item.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
            and work_item.trial_id is None
        )
        is_discovery_work = work_item.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
        if (
            request.proposal_discovery_query is not None
            or request.proposal_discovery_unit_ids
            or request.proposal_discovery_continuation is not None
            or request.proposal_discovery_read_continuation is not None
        ) and not is_discovery_work:
            raise ValueError(
                "proposal discovery navigation is available only for the active discovery WorkToken"
            )
        # Pre-confirmation, no Trial selection is confirmed yet (#119), so
        # _active_trial_ids is unconditionally empty -- unlike
        # _source_role_review_complete, which already treats
        # selected_trial_ids=None as "scope to every inventory-ready Trial"
        # for this same reason. Filtering by it here would leave the
        # pre-confirmation source-role-review work item with no sources to
        # review at all (#136).
        selected_trial_ids = (
            None
            if projection.run_state is RunState.AWAITING_CONFIRMATION
            else self._active_trial_ids(ledger, request.run_id)
        )
        trial = (
            None
            if is_global_source_work
            else next(
                (item for item in initialization.trials if item.trial_id == trial_id),
                None,
            )
        )
        scoped_trial_id = (
            None if is_global_source_work else (trial.trial_id if trial is not None else trial_id)
        )
        sources = (
            tuple(
                source
                for item in initialization.trials
                if item.status == "inventory_ready"
                and (selected_trial_ids is None or item.trial_id in selected_trial_ids)
                for source in item.inventory.sources
                if SourceRole.REGISTRY_CURRENT not in source.roles
            )
            if is_global_source_work
            else tuple(
                source
                for item in initialization.trials
                if item.trial_id == work_item.trial_id
                for source in item.inventory.sources
                if source.source_id == work_item.source_id
            )
            if is_discovery_work
            else tuple(trial.inventory.sources)
            if trial is not None
            else ()
        )
        discovery_page = None
        discovery_units: tuple[CanonicalEvidenceUnit, ...] = ()
        discovery_read_continuation: str | None = None
        discovery_policy = (
            self._proposal_discovery_policy(
                initialization,
                "target_guided"
                if initialization.manifest.outcome_target_specs
                else "structure_first",
            )
            if is_discovery_work
            else None
        )
        if (
            is_discovery_work
            and (
                request.run_id,
                work_item.work_token.token,
            )
            not in self._proposal_discovery_navigation
        ):
            durable_navigation = self._durable_proposal_discovery_navigation(
                ledger, request.run_id, work_item.work_token
            )
            if durable_navigation is not None:
                self._proposal_discovery_navigation[
                    (request.run_id, work_item.work_token.token)
                ] = durable_navigation
        if is_discovery_work and request.proposal_discovery_query is not None:
            assert discovery_policy is not None
            policy_passes = discovery_policy.required_passes
            if request.proposal_discovery_pass not in policy_passes:
                raise ValueError("proposal discovery search pass was not issued by the engine")
            pass_query = next(
                item
                for item in discovery_policy.pass_queries
                if item.pass_id == request.proposal_discovery_pass
            )
            if request.proposal_discovery_query.model_dump(
                mode="json"
            ) != pass_query.canonical_query.model_dump(mode="json"):
                raise ValueError(
                    "proposal discovery query must exactly match the engine-issued pass template"
                )
            discovery_page = EvidenceSearchIndex(
                self._required_root() / ".rob2" / "evidence.sqlite3"
            ).search_page(
                request.proposal_discovery_query,
                issuance_context=(
                    f"proposal-discovery|{request.run_id}|{work_item.work_token.token}"
                ),
                continuation=request.proposal_discovery_continuation,
                scope=EvidenceScope(
                    trial_id=work_item.trial_id,
                    source_ids=(work_item.source_id,) if work_item.source_id else (),
                    parse_ids=(work_item.parse_id,) if work_item.parse_id else (),
                    work_token_id=work_item.work_token.token,
                ),
            )
            navigation = self._proposal_discovery_navigation.setdefault(
                (request.run_id, work_item.work_token.token),
                {"passes": {}, "read_unit_ids": set(), "read_continuations": {}},
            )
            pass_state = navigation["passes"].setdefault(
                request.proposal_discovery_pass,
                {
                    "continuations": [],
                    "candidate_unit_ids": set(),
                    "complete": False,
                    "qualifying_search": False,
                },
            )
            if request.proposal_discovery_continuation is not None:
                pass_state["continuations"].append(request.proposal_discovery_continuation)
            pass_state["candidate_unit_ids"].update(
                candidate.canonical_unit_id for candidate in discovery_page.candidates
            )
            pass_state["complete"] = discovery_page.traversal_complete
            pass_state["qualifying_search"] = True
        if is_discovery_work and (
            request.proposal_discovery_unit_ids
            or request.proposal_discovery_read_continuation is not None
        ):
            index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
            navigation = self._proposal_discovery_navigation.setdefault(
                (request.run_id, work_item.work_token.token),
                {"passes": {}, "read_unit_ids": set(), "read_continuations": {}},
            )
            if request.proposal_discovery_read_continuation is not None:
                requested_unit_ids = navigation["read_continuations"].get(
                    request.proposal_discovery_read_continuation, None
                )
                if requested_unit_ids is None:
                    raise ValueError(
                        "proposal discovery read continuation was not issued for this WorkToken"
                    )
            else:
                requested_unit_ids = request.proposal_discovery_unit_ids
                exposed_unit_ids = {
                    unit_id
                    for state in navigation["passes"].values()
                    for unit_id in state["candidate_unit_ids"]
                }
                if set(requested_unit_ids) - exposed_unit_ids:
                    raise ValueError(
                        "proposal discovery reads must use canonical units surfaced by this token's search"
                    )
            selected: list[CanonicalEvidenceUnit] = []
            remaining_ids: list[Identifier] = []
            character_count = 0
            for offset, unit_id in enumerate(requested_unit_ids):
                unit = index.read_unit(unit_id)
                if (
                    selected
                    and character_count + len(unit.text) > discovery_policy.read_character_ceiling
                ):
                    remaining_ids.extend(requested_unit_ids[offset:])
                    break
                if not selected and len(unit.text) > discovery_policy.read_character_ceiling:
                    raise ValueError(
                        "proposal discovery unit exceeds the engine-issued character ceiling"
                    )
                selected.append(unit)
                character_count += len(unit.text)
            units = tuple(selected)
            if any(
                unit.source_id != work_item.source_id or unit.parse_id != work_item.parse_id
                for unit in units
            ):
                raise ValueError(
                    "proposal discovery read is outside the issued Source and Parse scope"
                )
            discovery_units = units
            if remaining_ids:
                discovery_read_continuation = (
                    f"proposal-read:{self._digest('|'.join(remaining_ids))}"
                )
                navigation["read_continuations"][discovery_read_continuation] = tuple(remaining_ids)
            navigation["read_unit_ids"].update(unit.unit_id for unit in units)
        if is_discovery_work and (
            request.proposal_discovery_query is not None
            or request.proposal_discovery_unit_ids
            or request.proposal_discovery_read_continuation is not None
        ):
            self._persist_proposal_discovery_navigation(
                ledger, request.run_id, work_item.work_token, navigation
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
                for candidate in (
                    proposal.registry_candidates if proposal else initialization.registry_candidates
                )
                if scoped_trial_id is None or candidate.trial_id == scoped_trial_id
            ),
            result_candidates=tuple(
                candidate
                for candidate in (
                    proposal.result_candidates if proposal else initialization.result_candidates
                )
                if scoped_trial_id is None or candidate.trial_id == scoped_trial_id
            ),
            reported_endpoint_candidates=(
                proposal.reported_endpoint_candidates if proposal else ()
            ),
            reported_randomization_candidates=(
                proposal.reported_randomization_candidates if proposal else ()
            ),
            reported_arm_candidates=(proposal.reported_arm_candidates if proposal else ()),
            proposal_discovery_receipts=(proposal.proposal_discovery_receipts if proposal else ()),
            proposal_discovery_page=discovery_page,
            proposal_discovery_units=discovery_units,
            proposal_discovery_read_continuation=discovery_read_continuation,
            proposal_discovery_policy=discovery_policy,
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
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=None,
                error=OperationError(
                    code="invalid_configuration",
                    detail="A Run proposal can only be submitted before confirmation.",
                    recovery=("Call continue_run instead; this Run has already been confirmed.",),
                ),
            )
        if not self._has_durable_proposal(ledger, request.run_id):
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                # This response does not carry an issued WorkItem or WorkToken.
                # Let the scheduler mint the current token rather than inviting a
                # caller to submit a token-bound operation without one.
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=None,
                error=OperationError(
                    code="invalid_configuration",
                    detail="The first RunProposal is issued only after terminal full-text discovery.",
                    recovery=("Complete every issued discovery review first.",),
                ),
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        events = self._events_for_run(ledger, request.run_id)
        if not self._source_role_review_complete(proposal, ledger, events, selected_trial_ids=None):
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=proposal,
                error=OperationError(
                    code="invalid_configuration",
                    detail=(
                        "Source-role review must resolve every inventory-ready source "
                        "before a Run proposal can be submitted."
                    ),
                    recovery=("Call submit_source_role_review first.",),
                ),
            )
        # #119: nothing here may trust _classify's raw cue. Overlay every
        # accepted Source-role disposition onto the sources this proposal
        # (and everything derived from it below — validate_result_sources,
        # _preferred_candidate via proposal_pairings) reads.
        proposal = self._apply_resolved_source_roles(proposal, ledger, request.run_id)
        if not self._proposal_discovery_complete(proposal, ledger, request.run_id):
            return SubmitRunProposalResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RUN_PROPOSAL, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                proposal=proposal,
                error=OperationError(
                    code="invalid_configuration",
                    detail="Required eligible full-text discovery is unfinished.",
                    recovery=("Complete every issued proposal discovery work item.",),
                ),
            )
        selections = request.selections
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
            if existing_record.submission != request:
                raise ValueError("idempotency key was already used with a different payload")
            return SubmitRunProposalResponse(
                operation_id=existing_event.operation_id,
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.CONFIRMATION_REQUIRED,
                committed=False,
                next_action=existing_record.next_action,
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
                    next_action=RunOperation.PREPARE_RUN,
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
                next_action=RunOperation.PREPARE_RUN,
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
                next_action=RunOperation.PREPARE_RUN,
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
        promotion_only_submission = request.promotions is not None and not selections
        if request.promotions is not None:
            proposal = self._apply_proposal_promotions(proposal, request.promotions)
        # Human promotion is intentionally a distinct stage before semantic
        # Result mapping.  A newly promoted Outcome target has no issued
        # Result candidate yet, so forcing a selection here would make the
        # mapping operation unreachable.
        if not promotion_only_submission:
            self._validate_proposal_selections(proposal, selections)
        proposal = self._refresh_registry_candidates(
            proposal, selections, authorized=request.authorized
        )
        self._index_initial_evidence(self._required_root(), proposal.initialization)
        requested_ambiguities = request.ambiguities + request.unresolved_ambiguities
        self._validate_proposal_ambiguities(proposal, requested_ambiguities)
        submitted = proposal.model_copy(
            update={
                "selections": selections,
                "ambiguities": self._merge_ambiguities(
                    proposal.ambiguities,
                    requested_ambiguities,
                    selections=selections,
                ),
                "submission_request_hash": canonical_hash(request.model_dump(mode="json")),
            }
        )
        submitted = self._resolve_result_candidates(submitted, selections)
        included_result_ids = self._effective_proposal_result_ids(submitted)
        source_errors = validate_result_sources(
            submitted.initialization,
            included_result_ids,
            artifacts=ledger.artifacts,
        )
        if source_errors:
            raise ValueError("; ".join(source_errors))
        submitted = submitted.model_copy(
            update={
                "supersedes_proposal_id": proposal.proposal_id,
                "semantic_diff": semantic_diff(proposal, submitted),
            }
        )
        submitted = self._freeze_submitted_proposal(submitted)
        persisted_next_action = (
            RunOperation.SUBMIT_RESULT_MAPPING_REVIEW
            if submitted.reported_endpoint_candidates and submitted.randomization_bindings
            else RunOperation.CONFIRM_RUN_DEFINITION
        )
        record = _ProposalSubmittedRecord(
            run_id=request.run_id,
            proposal=submitted,
            submission=request,
            next_action=persisted_next_action,
        )
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
            next_action=persisted_next_action,
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
                next_action=RunOperation.SUBMIT_RUN_PROPOSAL,
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
                    next_action=RunOperation.PREPARE_RUN,
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
                next_action=RunOperation.PREPARE_RUN,
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
                next_action=RunOperation.CONTINUE_RUN,
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
                next_action=RunOperation.PREPARE_RUN,
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
                next_action=RunOperation.SUBMIT_RUN_PROPOSAL,
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
        if any(item.material for item in proposal.limitations):
            return ConfirmRunDefinitionResponse(
                operation_id=self._read_operation_id(
                    RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                # Confirmation responses are tokenless.  The caller must return
                # through the scheduler to receive any corrective work token.
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="material_ambiguity",
                    detail="Material proposal discovery or Result-mapping limitations remain.",
                    recovery=("Resolve the typed proposal limitations before confirmation.",),
                ),
            )
        accepted = tuple(item for item in proposal.selections if item.accepted)
        pairings = proposal_pairings(proposal)
        selected_pairings = tuple(item for item in pairings if item.disposition == "selected")
        result_ids_for_scope = self._effective_proposal_result_ids(proposal)
        trial_ids = (
            tuple(dict.fromkeys(item.trial_id for item in selected_pairings))
            if proposal.outcome_targets and selected_pairings
            else proposal.trial_ids
        )
        result_candidates = {item.candidate_id: item for item in proposal.result_candidates}
        selected_candidate_items = tuple(
            result_candidates[item.result_candidate_id]
            for item in accepted
            if item.result_candidate_id is not None
        )
        complete_mapped = tuple(
            item
            for item in proposal.result_candidates
            if (
                item.mapping_status is ProposalMappingStatus.ACCEPTED
                and item.identity_completeness is ResultIdentityCompleteness.RESULT_COMPLETE
                and item.result is not None
            )
        )
        for candidate in complete_mapped:
            assert candidate.result is not None
            if candidate.result.effect_of_interest != "assignment":
                raise ValueError("complete mapped Result has unsupported effect_of_interest")
            trial = next(
                item
                for item in proposal.initialization.trials
                if item.trial_id == candidate.result.trial_id
            )
            page_number = _locator_page(candidate.result.source_locator)
            endpoint = next(
                (
                    item
                    for item in proposal.reported_endpoint_candidates
                    if item.candidate_id == candidate.endpoint_candidate_id
                ),
                None,
            )
            if page_number is None or endpoint is None:
                raise ValueError(
                    "complete mapped Result source_locator requires a page and mapped endpoint provenance"
                )
            if candidate.source_provenance is None:
                raise ValueError(
                    "complete mapped Result requires exact endpoint canonical provenance"
                )
            observed_provenance = candidate.source_provenance
            endpoint_provenance = endpoint.provenance
            if (
                observed_provenance.source_id,
                observed_provenance.parse_id,
                observed_provenance.artifact_hash,
                observed_provenance.canonical_unit_id,
                observed_provenance.page_number,
                observed_provenance.char_start,
                observed_provenance.char_end,
                observed_provenance.locator,
            ) != (
                endpoint_provenance.source_id,
                endpoint_provenance.parse_id,
                endpoint_provenance.artifact_hash,
                endpoint_provenance.canonical_unit_id,
                endpoint_provenance.page_number,
                endpoint_provenance.char_start,
                endpoint_provenance.char_end,
                endpoint_provenance.locator,
            ):
                raise ValueError(
                    "complete mapped Result provenance must bind the exact accepted endpoint canonical unit, page, and span"
                )
            if candidate.result.source_locator != endpoint.provenance.locator:
                raise ValueError(
                    "complete mapped Result source_locator must exactly bind endpoint canonical provenance"
                )
            if not any(
                self._is_eligible_discovery_source(source)
                and _locator_binds_source(candidate.result.source_locator, source)
                and source.source_id == endpoint.provenance.source_id
                and any(
                    page.page_number == page_number and page.text.strip()
                    for page in (_source_pages(source, ledger.artifacts) or ())
                )
                for source in trial.inventory.sources
            ):
                raise ValueError(
                    "complete mapped Result source_locator is not an eligible readable source"
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
                next_action=RunOperation.SUBMIT_RUN_PROPOSAL,
                run_id=request.run_id,
                run_state=projection.run_state,
                run_definition=None,
                error=OperationError(
                    code="material_ambiguity",
                    detail="The selected Result candidate does not identify an exact ResultSpec.",
                    recovery=("Submit an exact Trial-specific Result mapping for the candidate.",),
                ),
            )
        promoted_target_ids = {
            item.target.target_id
            for batch in proposal.promotion_batches
            for item in batch.outcome_targets
        }
        if promoted_target_ids:
            unresolved_pairings = tuple(
                item
                for item in pairings
                if item.outcome_target_id in promoted_target_ids
                and item.disposition == "unresolved"
            )
            if unresolved_pairings:
                return ConfirmRunDefinitionResponse(
                    operation_id=self._read_operation_id(
                        RunOperation.CONFIRM_RUN_DEFINITION, request.run_id
                    ),
                    ledger_cursor=f"ledger:{len(ledger.events())}",
                    affected_scope=(request.run_id,),
                    condition=WorkflowCondition.RUN_BLOCKED,
                    committed=False,
                    # This tokenless response cannot authorize a mapping
                    # submission.  continue_run will issue the bounded work item.
                    next_action=RunOperation.CONTINUE_RUN,
                    run_id=request.run_id,
                    run_state=projection.run_state,
                    run_definition=None,
                    error=OperationError(
                        code="material_ambiguity",
                        detail=(
                            "Every promoted Trial × Outcome target must be mapped, excluded, "
                            "or removed before confirmation."
                        ),
                        recovery=(
                            "Submit a mapping or an explicit Trial × Outcome disposition ",
                            "for each promoted Outcome target.",
                        ),
                    ),
                )
        mapped_specs: list[ResultSpecRevision] = []
        now = self._now()
        for candidate in selected_candidate_items:
            if not (
                candidate.mapping_status is ProposalMappingStatus.ACCEPTED
                and candidate.identity_completeness is ResultIdentityCompleteness.RESULT_COMPLETE
            ):
                continue
            if (
                candidate.result is None
                or candidate.estimate is None
                or candidate.provenance_note is None
                or candidate.mapping_reviewed_by is None
            ):
                raise RuntimeError(
                    "complete selected mapping lost its reviewer or exact ResultSpec"
                )
            if (
                self._result_spec_for(ledger, request.run_id, candidate.result.result_id)
                is not None
            ):
                continue
            preimage = {
                "entity_id": f"result-spec:{candidate.result.result_id.removeprefix('result:')}",
                "actor": candidate.mapping_reviewed_by.model_dump(mode="json"),
                "observed_at": now.isoformat(),
                "result": candidate.result.model_dump(mode="json"),
                "estimate": candidate.estimate.model_dump(mode="json"),
                "provenance_note": candidate.provenance_note,
            }
            pending = ResultSpecRevision(**preimage, revision_id="revision:result-spec-pending")
            mapped_specs.append(
                pending.model_copy(
                    update={
                        "revision_id": derive_result_spec_revision_id(
                            pending.model_dump(mode="json", exclude={"revision_id"})
                        )
                    }
                )
            )
        result_ids = list(result_ids_for_scope)
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
        outcome_target_ids = tuple(
            dict.fromkeys(item.outcome_target_id for item in selected_pairings)
        )
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
        registrations = tuple(
            self._transition(
                scope=spec.result.result_id,
                operation="operation:run-register-result",
                operation_key=(
                    f"idempotency:register-confirmed-mapped-result-"
                    f"{self._digest(f'{request.run_id}|{request.idempotency_key}|{spec.result.result_id}')}"
                ),
                entity_id=spec.entity_id,
                revision_id=spec.revision_id,
                artifact=_ResultDiscoveredRecord(
                    run_id=request.run_id, result_id=spec.result.result_id, result_spec=spec
                ),
                checkpoint=f"checkpoint:result-confirmed-{spec.result.result_id.removeprefix('result:')}",
                outcome=WorkflowEventOutcome.COMPLETED,
                observed_at=now,
            )
            for spec in mapped_specs
        )
        lease = self._acquire_lease(ledger, now)
        committed = self._commit_transitions(ledger, (*registrations, transition), lease, now=now)
        result = committed[-1]
        return ConfirmRunDefinitionResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.AGENT_WORK_REQUIRED,
            committed=not result.duplicate,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            run_definition=definition,
        )

    def search_evidence(self, request: SearchEvidenceRequest) -> SearchEvidenceResponse:
        ledger = self._bound_ledger(request.run_id)
        expected = self._next_work_item(ledger, request.run_id)
        if expected is None or expected.work_token != request.work_token:
            raise StaleWorkToken("stale WorkToken: reload the active question work item")
        if (
            expected.operation is not RunOperation.SUBMIT_QUESTION_STEP
            or (expected.result_id, expected.domain_id, expected.question_id)
            != (request.result_id, request.domain_id, request.question_id)
            or expected.session_content_hash != request.session_content_hash
        ):
            raise ScopeMismatch("Search request is outside the active v3 question scope")
        if request.query.source_ids:
            raise ScopeMismatch(
                "Source IDs are engine-injected for v3 Search", field="query.source_ids"
            )
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        runtime = service.runtime_for_question(request.question_id)
        query = request.query.model_copy(update={"source_ids": ()})
        if request.continuation is None:
            outcome = runtime.runtime.search_page(
                V3EvidenceSearchRequest(
                    expected_content_hash=request.expected_navigation_state_hash,
                    proposition_id=request.proposition_id,
                    pass_id=request.pass_id,
                    stage_id=request.stage_id,
                    intent_id=request.intent_id,
                    attempt_id=request.attempt_id,
                    query=query,
                    supersede_attempt_id=request.supersede_attempt_id,
                    supersession_rationale=request.supersession_rationale,
                )
            )
        else:
            outcome = runtime.runtime.continue_search_page(
                V3EvidenceSearchContinuationRequest(
                    expected_content_hash=request.expected_navigation_state_hash,
                    attempt_id=request.attempt_id,
                    continuation=request.continuation,
                    continue_reason=request.continue_reason,
                    continue_rationale=request.continue_rationale,
                )
            )
        if outcome.page is None:
            raise OperationalRetrievalFailure(
                "v3 Search stage has no searchable materialized scope"
            )
        return SearchEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.SEARCH_EVIDENCE, request.run_id),
            ledger_cursor=self._search_ledger_cursor(len(ledger.events())),
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            page=outcome.page,
            coverage_progress=outcome.progress,
        )

    def read_evidence(self, request: ReadEvidenceRequest) -> ReadEvidenceResponse:
        ledger = self._bound_ledger(request.run_id)
        self._retrieval_scope(
            ledger, request.run_id, request.work_token, request.result_id, request.question_id
        )
        if (
            request.work_token.domain_id != request.domain_id
            or request.work_token.session_content_hash != request.session_content_hash
            or request.batch.scope.result_id != request.result_id
            or request.batch.scope.domain_id != request.domain_id
            or any(item.question_ids != (request.question_id,) for item in request.batch.items)
        ):
            raise ScopeMismatch(
                "read batch must bind exactly the active v3 question", field="batch"
            )
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        runtime = service.runtime_for_question(request.question_id)
        if runtime.state.content_hash != request.expected_navigation_state_hash:
            raise StaleSearchContinuation("v3 navigation state changed; reload before reading")
        if request.batch.scope.snapshot_hash != runtime.state.workflow.snapshot_hash:
            raise StaleSearchContinuation(
                "read batch snapshot differs from the current v3 workflow"
            )
        exposures = {item.location_handle: item for item in runtime.state.workflow.exposures}
        for item in request.batch.items:
            exposure = exposures.get(item.location_handle)
            if exposure is None:
                raise StaleSearchContinuation("read handle was not exposed for this v3 question")
            if item.source_ids and item.source_ids != (exposure.source_id,):
                raise ScopeMismatch("read item Source IDs do not match the exposed candidate")
        try:
            page = EvidenceSearchIndex(
                self._required_root() / ".rob2" / "evidence.sqlite3"
            ).read_batch(request.batch, policy=EvidenceReadPolicy())
        except (sqlite3.Error, OSError) as error:
            raise OperationalRetrievalFailure(
                "unable to read the evidence retrieval index"
            ) from error
        return ReadEvidenceResponse(
            operation_id=self._read_operation_id(RunOperation.READ_EVIDENCE, request.run_id),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.COMPLETED,
            committed=False,
            run_id=request.run_id,
            page=page,
        )

    def submit_evidence_review(
        self, request: SubmitEvidenceReviewRequest
    ) -> SubmitEvidenceReviewResponse:
        ledger = self._bound_ledger(request.run_id)
        expected = self._next_work_item(ledger, request.run_id)
        if expected is None or expected.work_token != request.work_token:
            raise StaleWorkTokenError(request.run_id, expected)
        if (
            expected.operation is not RunOperation.SUBMIT_QUESTION_STEP
            or (expected.result_id, expected.domain_id, expected.question_id)
            != (request.result_id, request.domain_id, request.question_id)
            or expected.session_content_hash != request.session_content_hash
        ):
            raise StaleWorkTokenError(request.run_id, expected)
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        runtime = service.runtime_for_question(request.question_id)
        if runtime.state.content_hash != request.expected_navigation_state_hash:
            raise StaleSearchContinuation("v3 navigation state changed; reload before triage")
        scope = self._retrieval_scope(
            ledger, request.run_id, request.work_token, request.result_id, request.question_id
        )
        exposures = {
            (item.attempt_id, item.page_handle, item.candidate_id): item
            for item in runtime.state.workflow.exposures
        }
        page_attempt_ids = {
            page.attempt_id
            for page in runtime.state.workflow.pages
            if page.page_handle in request.page_handles
        }
        if len(page_attempt_ids) != 1:
            raise StaleSearchContinuation("triage pages must belong to one exposed v3 attempt")
        attempt_id = next(iter(page_attempt_ids))
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")

        def receipt_displays(receipt: str, target: Any) -> bool:
            try:
                view = index.resolve_read_view_receipt(receipt, scope=scope)
            except RetrievalFailure:
                return False
            return any(
                fragment.unit_id == target.canonical_unit_id
                and fragment.source_id == target.source_id
                and fragment.parse_id == target.parse_id
                and fragment.span_start <= target.canonical_start
                and fragment.span_end >= target.canonical_end
                for fragment in view.fragments
            )

        for revision in request.triage_revisions:
            if revision.sq_id != request.question_id:
                raise ScopeMismatch("triage revision question differs from active work")
            if revision.attempt_id != attempt_id:
                raise StaleSearchContinuation(
                    "triage revision attempt differs from its page partition"
                )
            exposure = exposures.get(
                (revision.attempt_id, revision.page_handle, revision.candidate_id)
            )
            if exposure is None or revision.page_handle not in request.page_handles:
                raise StaleSearchContinuation("triage revision is not an exposed v3 candidate")
            if revision.read_view_receipt and not receipt_displays(
                revision.read_view_receipt, exposure
            ):
                raise InvalidRetrievalRequest(
                    "triage read-view receipt does not display the exposed candidate"
                )
            if revision.retained_target_read_view_receipt:
                target = next(
                    (
                        item
                        for item in runtime.state.workflow.exposures
                        if item.candidate_id == revision.retained_target_id
                    ),
                    None,
                )
                if target is None or not receipt_displays(
                    revision.retained_target_read_view_receipt, target
                ):
                    raise InvalidRetrievalRequest(
                        "duplicate target receipt does not display the retained candidate"
                    )
        outcome = runtime.runtime.submit_page_triage(
            V3EvidencePageTriageRequest(
                expected_content_hash=request.expected_navigation_state_hash,
                submission_id=request.submission_id,
                attempt_id=attempt_id,
                page_handles=request.page_handles,
                revisions=request.triage_revisions,
            )
        )
        return SubmitEvidenceReviewResponse(
            operation_id=self._read_operation_id(
                RunOperation.SUBMIT_EVIDENCE_REVIEW, request.run_id
            ),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=True,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            result_id=request.result_id,
            result_state=self._result_state(
                self._projection(ledger, request.run_id), request.result_id
            ),
            domain_id=request.domain_id,
            workflow_state_hash=outcome.state.content_hash,
            outstanding_triage_candidate_ids=tuple(
                item.candidate_id
                for item in outcome.state.workflow.exposures
                if item.candidate_id
                not in {
                    revision.candidate_id for revision in outcome.state.workflow.triage_revisions
                }
            ),
        )

    def materialize_question_evidence_bundle(
        self, request: MaterializeQuestionEvidenceBundleRequest
    ) -> MaterializeQuestionEvidenceBundleResponse:
        """Freeze the active v3 question workflow into an engine-owned bundle."""

        ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:materialize-question-evidence-bundle"},
        )
        if existing is not None:
            record = _QuestionEvidenceBundleProductionRecord.model_validate_json(
                ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if (
                record.run_id,
                record.result_id,
                record.domain_id,
                record.question_id,
                record.session_content_hash,
                record.navigation_state_hash,
            ) != (
                request.run_id,
                request.result_id,
                request.domain_id,
                request.question_id,
                request.session_content_hash,
                request.expected_navigation_state_hash,
            ):
                raise InvalidRetrievalRequest(
                    "question Evidence Bundle idempotency key was replayed outside its scope"
                )
            return self._question_bundle_response(
                ledger, request, record, existing, committed=False
            )
        expected = self._next_work_item(ledger, request.run_id)
        if (
            expected is None
            or expected.work_token != request.work_token
            or (
                expected.operation,
                expected.result_id,
                expected.domain_id,
                expected.question_id,
                expected.session_content_hash,
                expected.frontier_entry_hash,
            )
            != (
                RunOperation.SUBMIT_QUESTION_STEP,
                request.result_id,
                request.domain_id,
                request.question_id,
                request.session_content_hash,
                request.frontier_entry_hash,
            )
        ):
            raise StaleWorkTokenError(request.run_id, expected)
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        session = service.load()
        if session.content_hash != request.session_content_hash:
            raise StaleSearchContinuation(
                "question evidence session changed; reload before freezing"
            )
        runtime = service.runtime_for_question(request.question_id)
        if runtime.state.content_hash != request.expected_navigation_state_hash:
            raise StaleSearchContinuation("v3 navigation state changed; reload before freezing")
        result_spec, spec_transition = self._question_bundle_result_spec(
            ledger, request.run_id, request.result_id
        )
        reviews, claims, visuals = self._current_question_bundle_provenance(
            ledger, runtime.state.workflow, request.visual_transcriptions
        )
        now = self._now()
        staged_reviews, staged_claims, provenance_transitions = (
            self._stage_question_text_provenance(ledger, request, now)
        )
        if staged_reviews and reviews:
            raise InvalidRetrievalRequest(
                "question bundle cannot combine staged reviews with a current review revision"
            )
        reviews = (*reviews, *staged_reviews)
        claims = (*claims, *staged_claims)
        materialization = build_question_evidence_bundle(
            QuestionEvidenceBundleMaterializationInput(
                materialization_id=f"question-bundle:{self._digest(request.idempotency_key)}",
                session=session,
                workflow=runtime.state.workflow,
                evidence_closure=evidence_closure_from_workflow(runtime.state.workflow),
                result_spec=result_spec,
                reviews=reviews,
                claims=claims,
                visual_transcriptions=visuals,
                actor=ENGINE_ACTOR,
                observed_at=now,
            )
        )
        pending = materialization.pending_artifacts
        transitions: list[Transition] = []
        if spec_transition is not None:
            transitions.append(spec_transition)
        transitions.extend(provenance_transitions)
        for label, artifact in (
            ("disposition", pending.disposition),
            ("coverage", pending.coverage_receipt),
            ("manifest", pending.manifest),
            ("bundle", pending.bundle),
        ):
            transitions.append(
                self._transition(
                    scope=request.result_id,
                    operation=f"operation:question-evidence-{label}-frozen",
                    operation_key=f"{request.idempotency_key}:{label}",
                    entity_id=artifact.entity_id,
                    revision_id=artifact.revision_id,
                    artifact=artifact,
                    checkpoint=None,
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                    dependencies=tuple(
                        DependencyInput.model_validate(item.model_dump())
                        for item in artifact.dependencies
                    ),
                )
            )
        record = _QuestionEvidenceBundleProductionRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=session.content_hash,
            navigation_state_hash=runtime.state.content_hash,
            evidence_bundle=materialization.binding,
        )
        transitions.append(
            self._submission_transition(
                run_id=request.run_id,
                scope=request.result_id,
                operation="operation:materialize-question-evidence-bundle",
                operation_key=request.idempotency_key,
                artifact=record,
                checkpoint=None,
                observed_at=now,
            )
        )
        committed = ledger.commit_batch(
            tuple(transitions), self._acquire_lease(ledger, now), now=now
        )[-1]
        return self._question_bundle_response(ledger, request, record, committed, committed=True)

    def submit_question_step(
        self, request: SubmitQuestionStepRequest
    ) -> SubmitQuestionStepResponse:
        """Commit one v3 answer or terminal diagnostic and ledger receipt."""

        ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            ledger, request.run_id, request.idempotency_key, {"operation:submit-question-step"}
        )
        if existing is not None:
            record = _QuestionStepRecord.model_validate_json(
                ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if record.submission != request:
                raise InvalidRetrievalRequest(
                    "question-step idempotency key was replayed differently"
                )
            return self._question_step_response(
                ledger, request, record, existing, was_committed=False
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_QUESTION_STEP,
                request.idempotency_key,
            )
        except StaleWorkTokenError:
            # A session transition is intentionally durable before its Run
            # checkpoint. Reconcile only the exact predecessor hash; this is
            # not permission to replay a stale step into a different frontier.
            service = self._question_session_service(
                ledger, request.run_id, request.result_id, request.domain_id
            )
            state = service.load()
            if request.diagnostic_stop:
                committed_step = next(
                    (
                        item
                        for item in state.ledger.diagnostic_stops
                        if item.question_id == request.question_id
                    ),
                    None,
                )
                semantics_match = committed_step is not None
                kind = "diagnostic_stop"
            else:
                committed_step = next(
                    (
                        item
                        for item in state.ledger.steps
                        if item.question_id == request.question_id
                    ),
                    None,
                )
                semantics_match = (
                    committed_step is not None
                    and committed_step.answer == request.answer
                    and getattr(committed_step, "rationale", None) == request.rationale
                )
                kind = "answer"
            if not semantics_match or committed_step is None:
                raise
            transition = service.reconcile_transition(
                predecessor_session_hash=request.session_content_hash,
                kind=kind,
                transition_content_hash=committed_step.content_hash,
            )
            return self._commit_question_step(
                ledger, request, transition.receipt, transition.projection
            )

        token = request.work_token
        if (
            token.question_id != request.question_id
            or token.result_id != request.result_id
            or token.domain_id != request.domain_id
            or token.session_content_hash != request.session_content_hash
            or token.frontier_entry_hash != request.frontier_entry_hash
        ):
            raise StaleWorkTokenError(request.run_id, self._next_work_item(ledger, request.run_id))
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        runtime = service.runtime_for_question(request.question_id)
        logic = self._logic_pack()
        if request.diagnostic_stop:
            transition = service.commit_diagnostic_stop(
                expected_content_hash=request.session_content_hash,
                stop=QuestionDiagnosticStop(
                    stop_id=f"question-stop:{self._digest(request.idempotency_key)}",
                    question_id=request.question_id,
                    logic_pack_family_id=logic.family_id,
                    logic_pack_release_id=logic.release_id,
                    logic_pack_hash=logic.content_hash,
                    expected_frontier_entry_hash=request.frontier_entry_hash,
                    evidence_diagnostic=evidence_diagnostic_from_workflow(runtime.state.workflow),
                ),
                workflow=runtime.state.workflow,
            )
        else:
            assert request.answer is not None
            assert request.evidence_bundle is not None
            self._require_question_evidence_bundle(
                ledger,
                request,
                runtime.state.workflow.content_hash,
                runtime.state.content_hash,
                request.evidence_bundle,
            )
            transition = service.commit_answer(
                expected_content_hash=request.session_content_hash,
                step=QuestionAnswerCommitStep(
                    step_id=f"question-step:{self._digest(request.idempotency_key)}",
                    question_id=request.question_id,
                    answer=request.answer,
                    rationale=request.rationale or "",
                    logic_pack_family_id=logic.family_id,
                    logic_pack_release_id=logic.release_id,
                    logic_pack_hash=logic.content_hash,
                    expected_frontier_entry_hash=request.frontier_entry_hash,
                    evidence_closure=evidence_closure_from_workflow(runtime.state.workflow),
                    evidence_bundle=request.evidence_bundle,
                ),
                workflow=runtime.state.workflow,
            )
        return self._commit_question_step(
            ledger, request, transition.receipt, transition.projection
        )

    def _require_question_evidence_bundle(
        self,
        ledger: WorkflowLedger,
        request: SubmitQuestionStepRequest | CorrectQuestionStepRequest,
        workflow_hash: ContentHash,
        navigation_state_hash: ContentHash,
        binding: QuestionEvidenceBundleBinding,
        *,
        allow_historical_binding: bool = False,
    ) -> None:
        """Reject caller-created answer bases; only an exact frozen bundle may bind a step."""

        if (binding.question_id, binding.run_id, binding.result_id, binding.domain_id) != (
            request.question_id,
            request.run_id,
            request.result_id,
            request.domain_id,
        ):
            raise InvalidRetrievalRequest("question Evidence Bundle binding changed active scope")
        try:
            bundle = EvidenceBundle.model_validate_json(
                ledger.artifacts.read(binding.bundle_content_hash)
            )
        except (OSError, ValueError) as error:
            raise InvalidRetrievalRequest(
                "question Evidence Bundle is not an engine-frozen artifact"
            ) from error
        if canonical_hash(bundle) != binding.bundle_content_hash or (
            bundle.revision_id != binding.bundle_revision_id
            or bundle.sq_id != request.question_id
            or bundle.domain_id != request.domain_id
        ):
            raise InvalidRetrievalRequest(
                "question Evidence Bundle binding does not match its artifact"
            )
        try:
            manifest_ref = bundle.consideration_manifest
            coverage_ref = bundle.v3_coverage_receipt
            if manifest_ref is None or coverage_ref is None:
                raise ValueError("question bundle lacks v3 manifest or coverage receipt")
            manifest = EvidenceConsiderationManifest.model_validate_json(
                ledger.artifacts.read(manifest_ref.content_hash)
            )
            coverage = V3EvidenceCoverageReceiptRecord.model_validate_json(
                ledger.artifacts.read(coverage_ref.content_hash)
            )
        except (OSError, ValueError) as error:
            raise InvalidRetrievalRequest(
                "question Evidence Bundle has unreadable v3 provenance artifacts"
            ) from error
        if (
            canonical_hash(manifest) != manifest_ref.content_hash
            or (manifest.entity_id, manifest.revision_id)
            != (manifest_ref.entity_id, manifest_ref.revision_id)
            or manifest.sq_id != request.question_id
            or manifest.considered_items != bundle.items
            or canonical_hash(coverage) != coverage_ref.content_hash
            or (coverage.entity_id, coverage.revision_id)
            != (coverage_ref.entity_id, coverage_ref.revision_id)
            or (coverage.result_id, coverage.domain_id, coverage.sq_id)
            != (request.result_id, request.domain_id, request.question_id)
            or coverage.workflow_state_hash != workflow_hash
        ):
            raise InvalidRetrievalRequest(
                "question Evidence Bundle has stale or forged v3 scope provenance"
            )
        current = next(
            (
                item
                for item in ledger.current_revisions()
                if item.entity_id == bundle.result_spec.entity_id
            ),
            None,
        )
        if current is None or (current.revision_id, current.artifact_hash) != (
            bundle.result_spec.revision_id,
            bundle.result_spec.content_hash,
        ):
            raise InvalidRetrievalRequest(
                "question Evidence Bundle does not bind the current ResultSpec revision"
            )
        expected_frozen_hash = canonical_hash(
            {
                "result_spec": bundle.result_spec.model_dump(mode="json"),
                "disposition": bundle.disposition.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in bundle.items],
                "sq_id": bundle.sq_id,
                "domain_id": bundle.domain_id,
                "v3_coverage_receipt": coverage_ref.model_dump(mode="json"),
                "consideration_manifest": manifest_ref.model_dump(mode="json"),
                "review_revisions": [
                    item.model_dump(mode="json") for item in bundle.review_revisions
                ],
                "coverage_state": bundle.coverage_state.value,
                "coverage_limitations": bundle.coverage_limitations,
                "no_information_basis": bundle.no_information_basis,
                "conflicts": bundle.conflicts,
            }
        )
        if bundle.frozen_content_hash != expected_frozen_hash:
            raise InvalidRetrievalRequest("question Evidence Bundle canonical hash is forged")
        produced = False
        production_session_hash: ContentHash | None = None
        for event in self._events_for_run(ledger, request.run_id):
            if event.operation != "operation:materialize-question-evidence-bundle":
                continue
            try:
                production = _QuestionEvidenceBundleProductionRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                )
            except (OSError, ValueError):
                continue
            if (
                production.evidence_bundle == binding
                and (
                    production.session_content_hash == request.session_content_hash
                    or (
                        allow_historical_binding
                        and any(
                            step.question_id == request.question_id
                            and step.evidence_bundle == binding
                            for step in self._question_session_service(
                                ledger, request.run_id, request.result_id, request.domain_id
                            )
                            .load()
                            .ledger.steps
                        )
                    )
                )
                and production.navigation_state_hash == navigation_state_hash
            ):
                produced = True
                production_session_hash = production.session_content_hash
                break
        if not produced:
            raise InvalidRetrievalRequest(
                "question Evidence Bundle binding was not produced by this engine session"
            )
        dispositions = {item.item_id: item.disposition for item in manifest.dispositions}
        expected_supporting = tuple(
            sorted(
                item_id
                for item_id, disposition in dispositions.items()
                if disposition is ConsiderationDisposition.SUPPORTING
            )
        )
        expected_contradicting = tuple(
            sorted(
                item_id
                for item_id, disposition in dispositions.items()
                if disposition is ConsiderationDisposition.CONTRADICTING
            )
        )
        claims = {item.entity_id for item in bundle.items}
        if (
            binding.supporting_evidence_ids != expected_supporting
            or binding.contradicting_evidence_ids != expected_contradicting
            or not set((*expected_supporting, *expected_contradicting)) <= claims
        ):
            raise InvalidRetrievalRequest(
                "question Evidence Bundle polarity does not match its frozen manifest"
            )
        verification = binding.engine_verified_no_information_basis
        if bool(verification) != bundle.no_information_basis:
            raise InvalidRetrievalRequest(
                "question Evidence Bundle no-information state does not match its artifact"
            )
        if verification is not None:
            closure_hash = coverage.question_closure_hash
            expected = canonical_hash(
                {
                    "kind": "engine-verified-no-information:v3",
                    "session_content_hash": (
                        production_session_hash
                        if allow_historical_binding and production_session_hash is not None
                        else request.session_content_hash
                    ),
                    "closure_hash": closure_hash,
                    "workflow_state_hash": workflow_hash,
                    "policy": {
                        "search": coverage.search_policy_hash,
                        "read": coverage.read_policy_hash,
                        "visual": coverage.visual_policy_hash,
                    },
                }
            )
            if (
                bundle.items
                or expected_supporting
                or expected_contradicting
                or bundle.coverage_state is not EvidenceCoverageState.COMPLETE
                or bundle.coverage_limitations
                or verification.verification_hash != expected
                or verification.verification_id
                != f"verification:no-information-v3-{expected[7:31]}"
            ):
                raise InvalidRetrievalRequest("No-information basis was not engine-verified")

    def correct_question_step(
        self, request: CorrectQuestionStepRequest
    ) -> CorrectQuestionStepResponse:
        """Append one immutable correction and rematerialize a completed Domain.

        The correction token is derived from the exact current session, so a
        caller cannot reuse it after a competing answer or correction.  The
        evidence bundle is deliberately required to be the predecessor's
        engine-produced basis; correcting a conclusion never permits a
        caller-created basis to enter history.
        """

        ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:correct-question-step"},
        )
        if existing is not None:
            record = _QuestionCorrectionRecord.model_validate_json(
                ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if record.submission != request:
                raise InvalidRetrievalRequest(
                    "question correction idempotency key was replayed differently"
                )
            return self._question_correction_response(ledger, request, record, existing, False)

        expected = self._question_correction_work_item(
            request.run_id,
            request.result_id,
            request.domain_id,
            request.question_id,
            request.session_content_hash,
        )
        # Trial identity is informative on a correction token, not part of its
        # question-session authority. A process-local Result→Trial hint may be
        # absent after terminal materialization or restart; the signed token,
        # operation, and exact Result/Domain/question/session bindings remain
        # stable and are all checked here.
        if request.work_token.model_copy(update={"trial_id": None}) != (
            expected.work_token.model_copy(update={"trial_id": None})
        ):
            raise StaleWorkTokenError(request.run_id, self._next_work_item(ledger, request.run_id))
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        state = service.load()
        if state.content_hash != request.session_content_hash:
            raise StaleWorkTokenError(request.run_id, self._next_work_item(ledger, request.run_id))
        predecessor = next(
            (
                item
                for item in effective_question_steps(state.ledger)
                if item.question_id == request.question_id
            ),
            None,
        )
        if predecessor is None or predecessor.effective_step_hash != request.prior_step_hash:
            raise InvalidRetrievalRequest("question correction predecessor is stale or conflicting")
        if predecessor.evidence_bundle != request.evidence_bundle:
            raise InvalidRetrievalRequest(
                "question correction must retain its predecessor Evidence Bundle"
            )
        runtime = service.runtime_for_committed_question(request.question_id)
        self._require_question_evidence_bundle(
            ledger,
            request,
            runtime.state.workflow.content_hash,
            runtime.state.content_hash,
            request.evidence_bundle,
            allow_historical_binding=True,
        )
        logic = self._logic_pack()
        correction = QuestionAnswerCorrection(
            correction_id=f"question-correction:{self._digest(request.idempotency_key)}",
            question_id=request.question_id,
            prior_step_hash=request.prior_step_hash,
            answer=request.answer,
            rationale=request.rationale,
            logic_pack_family_id=logic.family_id,
            logic_pack_release_id=logic.release_id,
            logic_pack_hash=logic.content_hash,
            evidence_closure=evidence_closure_from_workflow(runtime.state.workflow),
            evidence_bundle=request.evidence_bundle,
        )
        try:
            transition = service.commit_correction(
                expected_content_hash=request.session_content_hash, correction=correction
            )
        except StaleQuestionEvidenceSession:
            transition = service.reconcile_transition(
                predecessor_session_hash=request.session_content_hash,
                kind="correction",
                transition_content_hash=correction.content_hash,
            )
        record = _QuestionCorrectionRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=transition.projection.session_content_hash,
            transition_receipt_hash=canonical_hash(transition.receipt),
            submission=request,
        )
        now = self._now()
        transitions = [
            self._submission_transition(
                run_id=request.run_id,
                scope=request.result_id,
                operation="operation:correct-question-step",
                operation_key=request.idempotency_key,
                artifact=record,
                checkpoint=(
                    f"checkpoint:question-correction-{request.domain_id.removeprefix('domain:')}-"
                    f"{request.question_id.removeprefix('sq:')}"
                ),
                observed_at=now,
            )
        ]
        projection_before = self._projection(ledger, request.run_id)
        prior_result_state = self._result_state(projection_before, request.result_id)
        if prior_result_state is ResultState.REPORT_READY:
            transitions.append(
                self._transition(
                    scope=request.result_id,
                    operation="operation:result-assessment-corrected",
                    operation_key=f"{request.idempotency_key}:result-assessment-corrected",
                    entity_id=(
                        f"result-assessment-correction:{request.result_id.removeprefix('result:')}-"
                        f"{self._digest(request.idempotency_key)}"
                    ),
                    revision_id=(
                        f"revision:result-assessment-correction-"
                        f"{self._digest(request.idempotency_key)}"
                    ),
                    artifact=_ResultAssessmentCorrectedRecord(
                        run_id=request.run_id,
                        result_id=request.result_id,
                        correction_key=request.idempotency_key,
                    ),
                    checkpoint=(
                        f"checkpoint:result-assessment-correction-"
                        f"{request.result_id.removeprefix('result:')}"
                    ),
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        if projection_before.run_state is RunState.COMPLETE:
            transitions.append(
                self._transition(
                    scope=request.run_id,
                    operation="operation:run-reopened",
                    operation_key=f"{request.idempotency_key}:run-reopened",
                    entity_id=f"run-question-correction:{self._digest(request.idempotency_key)}",
                    revision_id=f"revision:run-question-correction-{self._digest(request.idempotency_key)}",
                    artifact=_RunReopenedRecord(
                        run_id=request.run_id,
                        input_snapshot_hash=self._latest_proposal(
                            ledger, request.run_id
                        ).input_snapshot_hash,
                        invalidated_result_ids=(request.result_id,),
                    ),
                    checkpoint=f"checkpoint:run-question-correction-{self._digest(request.idempotency_key)}",
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                    observed_at=now,
                )
            )
        if transition.projection.frontier.status == "complete_with_answers":
            transitions.extend(self._final_question_domain_transitions(ledger, request, now))
        committed = ledger.commit_batch(
            tuple(transitions), self._acquire_lease(ledger, now), now=now
        )[0]
        return self._question_correction_response(ledger, request, record, committed, True)

    def _question_bundle_response(
        self,
        ledger: WorkflowLedger,
        request: MaterializeQuestionEvidenceBundleRequest,
        record: _QuestionEvidenceBundleProductionRecord,
        result: CommitResult | WorkflowEvent,
        *,
        committed: bool,
    ) -> MaterializeQuestionEvidenceBundleResponse:
        projection = self._projection(ledger, request.run_id)
        return MaterializeQuestionEvidenceBundleResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=committed,
            next_action=RunOperation.SUBMIT_QUESTION_STEP,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=record.session_content_hash,
            navigation_state_hash=record.navigation_state_hash,
            evidence_bundle=record.evidence_bundle,
        )

    def _question_bundle_result_spec(
        self, ledger: WorkflowLedger, run_id: Identifier, result_id: Identifier
    ) -> tuple[RecordReference, Transition | None]:
        """Return the current ResultSpec reference, staging its first freeze if needed."""

        result_spec = self._result_spec_for(ledger, run_id, result_id)
        if result_spec is None:
            raise InvalidRetrievalRequest("question Evidence Bundle requires a resolved ResultSpec")
        current = next(
            (
                item
                for item in ledger.current_revisions()
                if item.entity_id == result_spec.entity_id
            ),
            None,
        )
        if current is not None:
            try:
                frozen = ResultSpecRevision.model_validate_json(
                    ledger.artifacts.read(current.artifact_hash)
                )
            except (OSError, ValueError) as error:
                raise InvalidRetrievalRequest("current ResultSpec freeze is unreadable") from error
            if frozen != result_spec:
                raise InvalidRetrievalRequest(
                    "current ResultSpec revision differs from active question scope"
                )
            return RecordReference(
                entity_id=current.entity_id,
                revision_id=current.revision_id,
                content_hash=current.artifact_hash,
            ), None
        reference = RecordReference(
            entity_id=result_spec.entity_id,
            revision_id=result_spec.revision_id,
            content_hash=canonical_hash(result_spec),
        )
        return reference, self._transition(
            scope=result_id,
            operation="operation:result-spec-frozen",
            operation_key=(
                f"materialize:question-result-spec:{run_id}:{result_id}:{result_spec.revision_id}"
            ),
            entity_id=result_spec.entity_id,
            revision_id=result_spec.revision_id,
            artifact=result_spec,
            checkpoint=None,
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=result_spec.observed_at,
            actor=result_spec.actor,
            dependencies=tuple(
                DependencyInput.model_validate(item.model_dump())
                for item in result_spec.dependencies
            ),
            supersedes_revision_id=(
                result_spec.supersedes.revision_id if result_spec.supersedes is not None else None
            ),
        )

    def _current_question_bundle_provenance(
        self,
        ledger: WorkflowLedger,
        workflow: Any,
        visual_inputs: tuple[QuestionVisualProvenanceInput, ...],
    ) -> tuple[
        tuple[ResolvedQuestionEvidenceReview, ...],
        tuple[ResolvedQuestionEvidenceClaim, ...],
        tuple[ResolvedQuestionVisualTranscription, ...],
    ]:
        """Resolve only current immutable records that exactly bind this v3 workflow.

        Historical ``VisualTranscription`` records do not themselves carry a
        question/review/span link. A caller must therefore supply that typed
        linkage, which this method re-resolves against current immutable
        revisions before passing it to the pure builder.
        """

        reviews: list[ResolvedQuestionEvidenceReview] = []
        claims: list[ResolvedQuestionEvidenceClaim] = []
        candidate_ids = {item.candidate_id for item in workflow.exposures}
        for revision in ledger.current_revisions():
            reference = RecordReference(
                entity_id=revision.entity_id,
                revision_id=revision.revision_id,
                content_hash=revision.artifact_hash,
            )
            try:
                review = EvidenceReviewRevision.model_validate_json(
                    ledger.artifacts.read(revision.artifact_hash)
                )
            except (OSError, ValueError):
                review = None
            if review is not None:
                if canonical_hash(review) != revision.artifact_hash:
                    raise InvalidRetrievalRequest(
                        "current Evidence review has a forged content hash"
                    )
                if (review.result_id, review.domain_id, review.sq_id, review.candidate_id) == (
                    workflow.result_id,
                    workflow.domain_id,
                    workflow.question_id,
                    review.candidate_id,
                ) and review.candidate_id in candidate_ids:
                    reviews.append(
                        ResolvedQuestionEvidenceReview(review=review, reference=reference)
                    )
                continue
            try:
                claim = EvidenceClaim.model_validate_json(
                    ledger.artifacts.read(revision.artifact_hash)
                )
            except (OSError, ValueError):
                continue
            if canonical_hash(claim) != revision.artifact_hash:
                raise InvalidRetrievalRequest("current Evidence claim has a forged content hash")
            if claim.candidate_id in candidate_ids:
                claims.append(ResolvedQuestionEvidenceClaim(claim=claim, reference=reference))
        review_by_reference = {item.reference: item for item in reviews}
        visuals: list[ResolvedQuestionVisualTranscription] = []
        if len({item.transcription for item in visual_inputs}) != len(visual_inputs):
            raise InvalidRetrievalRequest("question visual provenance repeats a transcription")
        for item in visual_inputs:
            current = next(
                (
                    revision
                    for revision in ledger.current_revisions()
                    if (revision.entity_id, revision.revision_id, revision.artifact_hash)
                    == (
                        item.transcription.entity_id,
                        item.transcription.revision_id,
                        item.transcription.content_hash,
                    )
                ),
                None,
            )
            if current is None:
                raise InvalidRetrievalRequest(
                    "visual transcription is not a current immutable record"
                )
            try:
                transcription = VisualTranscription.model_validate_json(
                    ledger.artifacts.read(current.artifact_hash)
                )
            except (OSError, ValueError) as error:
                raise InvalidRetrievalRequest("visual transcription is unreadable") from error
            if canonical_hash(transcription) != item.transcription.content_hash:
                raise InvalidRetrievalRequest("visual transcription content hash is forged")
            review = review_by_reference.get(item.authorizing_review)
            if review is None or review.review.candidate_id != item.candidate_id:
                raise InvalidRetrievalRequest(
                    "visual transcription does not bind a current question review"
                )
            if not any(span.span_id == item.review_span_id for span in review.review.spans):
                raise InvalidRetrievalRequest(
                    "visual transcription names no authorizing review span"
                )
            visuals.append(
                ResolvedQuestionVisualTranscription(
                    transcription=transcription,
                    reference=item.transcription,
                    candidate_id=item.candidate_id,
                    authorizing_review=item.authorizing_review,
                    review_span_id=item.review_span_id,
                )
            )
        return (
            tuple(sorted(reviews, key=lambda item: item.reference.entity_id)),
            tuple(sorted(claims, key=lambda item: item.reference.entity_id)),
            tuple(sorted(visuals, key=lambda item: item.reference.entity_id)),
        )

    def _stage_question_text_provenance(
        self,
        ledger: WorkflowLedger,
        request: MaterializeQuestionEvidenceBundleRequest,
        observed_at: datetime,
    ) -> tuple[
        tuple[ResolvedQuestionEvidenceReview, ...],
        tuple[ResolvedQuestionEvidenceClaim, ...],
        tuple[Transition, ...],
    ]:
        """Resolve supplied v3 receipts into review and claim transitions without writing.

        The returned order is deliberate: review records precede their claims,
        and source/unit records precede claims that depend on them. The caller
        commits this complete sequence with the bundle artifacts in one ledger
        transaction.
        """

        if not request.review_revisions and not request.passages:
            return (), (), ()
        scope = self._retrieval_scope(
            ledger,
            request.run_id,
            request.work_token,
            request.result_id,
            request.question_id,
        )
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        units: dict[Identifier, CanonicalEvidenceUnit] = {}
        passages_by_candidate: dict[Identifier, list[EvidencePassageInput]] = {}
        for passage in request.passages:
            unit = index.read_unit(passage.unit_id, scope=scope)
            self._validate_citable_unit(unit, scope)
            end = passage.span_end if passage.span_end is not None else len(unit.text)
            if end <= passage.span_start or end > len(unit.text):
                raise InvalidRetrievalRequest(
                    "question passage span is empty or outside its canonical unit"
                )
            candidate_id = passage.candidate_id or passage.unit_id
            units[passage.unit_id] = unit
            passages_by_candidate.setdefault(candidate_id, []).append(passage)
        reviews: dict[Identifier, ResolvedQuestionEvidenceReview] = {}
        for submitted in request.review_revisions:
            candidate_passages = passages_by_candidate.get(submitted.candidate_id, [])
            if not candidate_passages:
                raise InvalidRetrievalRequest("review revision has no retained canonical passage")
            spans: list[EvidenceReviewSpan] = []
            for submitted_span in submitted.spans:
                context = index.resolve_read_view_receipt(
                    submitted_span.read_view_receipt, scope=scope
                )
                matching = [
                    unit
                    for passage in candidate_passages
                    for unit in (units[passage.unit_id],)
                    if any(fragment.unit_id == unit.unit_id for fragment in context.fragments)
                ]
                unique = {item.unit_id: item for item in matching}
                if len(unique) != 1:
                    raise InvalidRetrievalRequest(
                        "review receipt must display exactly one retained canonical candidate"
                    )
                unit = next(iter(unique.values()))
                fragment = next(item for item in context.fragments if item.unit_id == unit.unit_id)
                if (
                    submitted_span.span_start < fragment.span_start
                    or submitted_span.span_end > fragment.span_end
                    or fragment.content_hash
                    != sha256_digest(unit.text[fragment.span_start : fragment.span_end].encode())
                ):
                    raise InvalidRetrievalRequest(
                        "review span is not contained in its issued read receipt"
                    )
                span_id = f"review-span:{self._digest('|'.join((submitted.candidate_id, unit.unit_id, unit.parse_id, str(submitted_span.span_start), str(submitted_span.span_end))))}"
                spans.append(
                    EvidenceReviewSpan(
                        span_id=span_id,
                        span_start=submitted_span.span_start,
                        span_end=submitted_span.span_end,
                        trial_attribution=submitted_span.trial_attribution,
                        disposition=submitted_span.disposition,
                        rationale=submitted_span.rationale,
                        attribution_rationale=submitted_span.attribution_rationale,
                        reviewed_context=context,
                        visual_review_condition=submitted_span.visual_review_condition,
                        duplicate_of=submitted_span.duplicate_of,
                    )
                )
            review = EvidenceReviewRevision(
                entity_id=submitted.entity_id,
                revision_id=submitted.revision_id,
                actor=submitted.actor,
                observed_at=submitted.observed_at,
                supersedes=submitted.supersedes,
                candidate_id=submitted.candidate_id,
                result_id=request.result_id,
                domain_id=request.domain_id,
                sq_id=request.question_id,
                spans=tuple(spans),
            )
            reference = RecordReference(
                entity_id=review.entity_id,
                revision_id=review.revision_id,
                content_hash=canonical_hash(review),
            )
            reviews[review.candidate_id] = ResolvedQuestionEvidenceReview(
                review=review, reference=reference
            )
        transitions: list[Transition] = [
            self._transition(
                scope=request.result_id,
                operation="operation:question-evidence-review-frozen",
                operation_key=f"{request.idempotency_key}:review:{review.review.candidate_id}",
                entity_id=review.review.entity_id,
                revision_id=review.review.revision_id,
                artifact=review.review,
                checkpoint=None,
                outcome=WorkflowEventOutcome.COMPLETED,
                observed_at=observed_at,
                actor=review.review.actor,
            )
            for review in reviews.values()
        ]
        proposal = self._latest_proposal(ledger, request.run_id)
        result_spec = self._result_spec_for(ledger, request.run_id, request.result_id)
        if result_spec is None:
            raise InvalidRetrievalRequest("question passage requires a resolved Result")
        sources = {
            source.source_id: source
            for trial in proposal.initialization.trials
            if trial.trial_id == result_spec.result.trial_id
            for source in trial.inventory.sources
        }
        source_refs: dict[Identifier, RecordReference] = {}
        unit_refs: dict[Identifier, RecordReference] = {}
        claims: list[ResolvedQuestionEvidenceClaim] = []
        for passage in request.passages:
            unit = units[passage.unit_id]
            candidate_id = passage.candidate_id or passage.unit_id
            review = reviews.get(candidate_id)
            if review is None:
                raise InvalidRetrievalRequest("retained passage has no staged current review")
            end = passage.span_end if passage.span_end is not None else len(unit.text)
            span = next(
                (
                    item
                    for item in review.review.spans
                    if (item.span_start, item.span_end) == (passage.span_start, end)
                    and any(
                        fragment.unit_id == unit.unit_id
                        for fragment in item.reviewed_context.fragments
                    )
                ),
                None,
            )
            if (
                span is None
                or span.trial_attribution is not TrialAttribution.ACTIVE
                or span.disposition
                not in {
                    EvidenceReviewDisposition.SUPPORTING,
                    EvidenceReviewDisposition.CONTRADICTING,
                }
            ):
                raise InvalidRetrievalRequest(
                    "retained passage lacks an active substantive review span"
                )
            source = sources.get(unit.source_id)
            if source is None or source.artifact_hash != unit.source_artifact_hash:
                raise InvalidRetrievalRequest(
                    "canonical passage source is stale for the active Result"
                )
            source_ref = source_refs.get(source.source_id)
            if source_ref is None:
                digest = self._digest(
                    f"{request.run_id}|{unit.source_id}|{unit.source_artifact_hash}"
                )
                source_ref = RecordReference(
                    entity_id=f"evidence-source:{digest}",
                    revision_id=f"revision:evidence-source-{digest}",
                    content_hash=canonical_hash(source),
                )
                source_refs[source.source_id] = source_ref
                transitions.append(
                    self._transition(
                        scope=request.result_id,
                        operation="operation:question-evidence-source-frozen",
                        operation_key=f"{request.idempotency_key}:source:{digest}",
                        entity_id=source_ref.entity_id,
                        revision_id=source_ref.revision_id,
                        artifact=source,
                        checkpoint=None,
                        outcome=WorkflowEventOutcome.COMPLETED,
                        observed_at=observed_at,
                    )
                )
            unit_ref = unit_refs.get(unit.unit_id)
            if unit_ref is None:
                digest = self._digest(
                    f"{request.run_id}|{unit.unit_id}|{unit.parse_id}|{unit.source_artifact_hash}"
                )
                unit_ref = RecordReference(
                    entity_id=f"canonical-unit:{digest}",
                    revision_id=f"revision:canonical-unit-{digest}",
                    content_hash=canonical_hash(unit),
                )
                unit_refs[unit.unit_id] = unit_ref
                transitions.append(
                    self._transition(
                        scope=request.result_id,
                        operation="operation:question-canonical-unit-frozen",
                        operation_key=f"{request.idempotency_key}:unit:{digest}",
                        entity_id=unit_ref.entity_id,
                        revision_id=unit_ref.revision_id,
                        artifact=unit,
                        checkpoint=None,
                        outcome=WorkflowEventOutcome.COMPLETED,
                        observed_at=observed_at,
                    )
                )
            digest = self._digest(
                "|".join(
                    (
                        request.idempotency_key,
                        candidate_id,
                        unit.unit_id,
                        str(passage.span_start),
                        str(end),
                    )
                )
            )
            claim = EvidenceClaim(
                entity_id=f"evidence-claim:v3-{digest}",
                revision_id=f"revision:evidence-claim-v3-{digest}",
                dependencies=(
                    Dependency(**unit_ref.model_dump(), role="dependency:canonical-unit"),
                    Dependency(**source_ref.model_dump(), role="dependency:source"),
                    Dependency(**review.reference.model_dump(), role="dependency:evidence-review"),
                ),
                actor=ENGINE_ACTOR,
                observed_at=observed_at,
                canonical_unit=unit_ref,
                source=source_ref,
                authorizing_review=review.reference,
                review_span_id=span.span_id,
                candidate_id=candidate_id,
                span_start=passage.span_start,
                span_end=end,
                quoted_text_hash=sha256_digest(unit.text[passage.span_start : end].encode()),
                claim_type=passage.claim_type,
                verification_status="machine_verified",
            )
            reference = RecordReference(
                entity_id=claim.entity_id,
                revision_id=claim.revision_id,
                content_hash=canonical_hash(claim),
            )
            claims.append(ResolvedQuestionEvidenceClaim(claim=claim, reference=reference))
            transitions.append(
                self._transition(
                    scope=request.result_id,
                    operation="operation:question-evidence-claim-frozen",
                    operation_key=f"{request.idempotency_key}:claim:{digest}",
                    entity_id=claim.entity_id,
                    revision_id=claim.revision_id,
                    artifact=claim,
                    checkpoint=None,
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=observed_at,
                    dependencies=tuple(
                        DependencyInput.model_validate(item.model_dump())
                        for item in claim.dependencies
                    ),
                )
            )
        return tuple(reviews.values()), tuple(claims), tuple(transitions)

    def _commit_question_step(
        self,
        ledger: WorkflowLedger,
        request: SubmitQuestionStepRequest,
        receipt: QuestionEvidenceTransitionReceipt,
        session: QuestionEvidenceSessionProjection,
    ) -> SubmitQuestionStepResponse:
        record = _QuestionStepRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=session.session_content_hash,
            transition_receipt_hash=canonical_hash(receipt),
            diagnostic_terminal=session.frontier.status == "diagnostic_terminal",
            submission=request,
        )
        question_transition = self._submission_transition(
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-question-step",
            operation_key=request.idempotency_key,
            artifact=record,
            checkpoint=(
                f"checkpoint:question-step-{request.domain_id.removeprefix('domain:')}-"
                f"{request.question_id.removeprefix('sq:')}"
            ),
            observed_at=self._now(),
        )
        if not record.diagnostic_terminal:
            now = self._now()
            transitions = [question_transition]
            if session.frontier.status == "complete_with_answers":
                transitions.extend(self._final_question_domain_transitions(ledger, request, now))
            committed = ledger.commit_batch(
                tuple(transitions), self._acquire_lease(ledger, now), now=now
            )[0]
            if session.frontier.status == "complete_with_answers":
                # Domain products become current atomically above. Terminal
                # materialization then consumes only those committed
                # checkpoints; a rendering failure leaves the Result safely
                # assessment-ready for deterministic continuation.
                self._materialize_terminal(ledger, request.run_id, request.result_id)
                self._commit_run_completed_if_ready(ledger, request.run_id)
            return self._question_step_response(
                ledger, request, record, committed, was_committed=True
            )

        # A terminal evidence limitation is a Result safe boundary, not a
        # Domain answer. Publish its judgment-free diagnostic atomically with
        # the question checkpoint so a restarted scheduler cannot assess a
        # later Domain for the affected Result.
        result_spec = self._result_spec_for(ledger, request.run_id, request.result_id)
        if result_spec is None:
            raise ValueError("diagnostic question transition requires a resolved Result")
        diagnostic = self._materialize_diagnostic_bundle(
            _ResultDiagnosticRecord(
                run_id=request.run_id,
                result_id=request.result_id,
                trial_id=result_spec.result.trial_id,
                reason=(
                    "Question-scoped evidence workflow reached a terminal diagnostic limitation "
                    f"for {request.question_id}; no RoB 2 answer or Domain judgment was produced."
                ),
                recovery=self._evidence_diagnostic_recovery_actions(
                    self._question_session_service(
                        ledger, request.run_id, request.result_id, request.domain_id
                    )
                    .runtime_for_diagnostic_question(request.question_id)
                    .state.workflow
                ),
            )
        )
        suffix = self._digest(f"{request.run_id}|{request.idempotency_key}|diagnostic")
        diagnostic_transition = self._transition(
            scope=request.result_id,
            operation="operation:result-diagnostic-ready",
            operation_key=f"{request.idempotency_key}:diagnostic",
            entity_id=f"result-diagnostic:{suffix}",
            revision_id=f"revision:result-diagnostic-{suffix}",
            artifact=diagnostic,
            checkpoint=f"checkpoint:result-diagnostic-{suffix}",
            outcome=WorkflowEventOutcome.TRIAL_PROBLEM,
            observed_at=self._now(),
        )
        now = self._now()
        committed = self._commit_transitions(
            ledger,
            (question_transition, diagnostic_transition),
            self._acquire_lease(ledger, now),
            now=now,
        )
        self._commit_run_completed_if_ready(ledger, request.run_id)
        return self._question_step_response(
            ledger,
            request,
            record,
            committed[0],
            was_committed=any(not item.duplicate for item in committed),
        )

    def _final_question_domain_transitions(
        self,
        ledger: WorkflowLedger,
        request: SubmitQuestionStepRequest | CorrectQuestionStepRequest,
        now: datetime,
    ) -> tuple[Transition, ...]:
        """Stage the completed session's canonical Domain evidence and answers."""

        session = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        ).load()
        steps = effective_question_steps(session.ledger)
        if not steps:
            raise InvalidRetrievalRequest("completed question session has no answer steps")
        bundle_refs: list[RecordReference] = []
        manifests: list[RecordReference] = []
        receipts: list[RecordReference] = []
        for step in steps:
            binding = step.evidence_bundle
            bundle = EvidenceBundle.model_validate_json(
                ledger.artifacts.read(binding.bundle_content_hash)
            )
            if canonical_hash(bundle) != binding.bundle_content_hash:
                raise InvalidRetrievalRequest(
                    "completed question session references a forged bundle"
                )
            bundle_refs.append(
                RecordReference(
                    entity_id=bundle.entity_id,
                    revision_id=bundle.revision_id,
                    content_hash=binding.bundle_content_hash,
                )
            )
            assert (
                bundle.consideration_manifest is not None and bundle.v3_coverage_receipt is not None
            )
            manifests.append(bundle.consideration_manifest)
            receipts.append(bundle.v3_coverage_receipt)
        evidence = _DomainEvidenceRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            items=tuple(item.revision_id for item in bundle_refs),
            coverage_state="complete",
            evidence_bundles=tuple(bundle_refs),
            consideration_manifests=tuple(manifests),
            coverage_receipts=tuple(receipts),
        )
        slug = request.domain_id.removeprefix("domain:")
        prior_evidence = self._current_checkpoint_event(
            ledger, request.result_id, f"checkpoint:evidence-{slug}"
        )
        evidence_entity_id = (
            prior_evidence.entity_id
            if prior_evidence is not None
            else f"domain-evidence:v3-{request.result_id.removeprefix('result:')}-{slug}"
        )
        transitions = [
            self._transition(
                scope=request.result_id,
                operation="operation:submit-domain-evidence",
                operation_key=f"{request.idempotency_key}:domain-evidence",
                entity_id=evidence_entity_id,
                revision_id=f"revision:domain-evidence-v3-{self._digest(request.idempotency_key)}",
                artifact=evidence,
                checkpoint=f"checkpoint:evidence-{slug}",
                outcome=WorkflowEventOutcome.COMPLETED,
                observed_at=now,
                supersedes_revision_id=(
                    prior_evidence.revision_id if prior_evidence is not None else None
                ),
                dependencies=tuple(
                    DependencyInput(**item.model_dump(), role="dependency:evidence-bundle")
                    for item in bundle_refs
                ),
            )
        ]
        logic = self._logic_pack()
        domain = next(item for item in logic.domains if item.id == request.domain_id)
        answer_refs: list[RecordReference] = []
        answer_revision_superseded = False
        for step, bundle_ref in zip(steps, bundle_refs, strict=True):
            digest = self._digest(f"{request.idempotency_key}|{step.question_id}|answer")
            answer_entity_id = (
                f"sq-answer:{request.result_id.removeprefix('result:')}-"
                f"{step.question_id.removeprefix('sq:')}"
            )
            prior_answer = next(
                (item for item in ledger.current_revisions() if item.entity_id == answer_entity_id),
                None,
            )
            answer = SQAnswerRevision(
                entity_id=answer_entity_id,
                revision_id=f"revision:sq-answer-v3-{digest}",
                dependencies=(
                    Dependency(**bundle_ref.model_dump(), role="dependency:evidence-bundle"),
                ),
                actor=ENGINE_ACTOR,
                observed_at=now,
                sq_id=step.question_id,
                answer=step.answer,
                rationale=step.rationale,
                evidence_bundle=bundle_ref,
                logic_pack_release_id=logic.release_id,
                logic_pack_hash=logic.content_hash,
                guidance_pack_release_id=self._guidance_pack().release_id,
                guidance_pack_hash=self._guidance_pack().content_hash,
                evidence_policy_id=EvidenceSearchPolicy().policy_id,
                evidence_policy_hash=canonical_hash(EvidenceSearchPolicy()),
                decision_rule_ids=tuple(
                    rule.id
                    for rule in domain.judgment_rules
                    if step.question_id
                    in {
                        condition.question_id for condition in self._walk_pack_conditions(rule.when)
                    }
                ),
            )
            if prior_answer is not None:
                answer_revision_superseded = True
                answer = answer.model_copy(
                    update={
                        "supersedes": Supersession(
                            entity_id=answer_entity_id,
                            revision_id=prior_answer.revision_id,
                            content_hash=prior_answer.artifact_hash,
                            reason="question correction rematerialized the effective Domain answer",
                        )
                    }
                )
            ref = RecordReference(
                entity_id=answer.entity_id,
                revision_id=answer.revision_id,
                content_hash=canonical_hash(answer),
            )
            answer_refs.append(ref)
            transitions.append(
                self._transition(
                    scope=request.result_id,
                    operation="operation:sq-answer-revision",
                    operation_key=f"{request.idempotency_key}:domain-answer:{step.question_id}",
                    entity_id=answer.entity_id,
                    revision_id=answer.revision_id,
                    artifact=answer,
                    checkpoint=None,
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                    dependencies=tuple(
                        DependencyInput.model_validate(item.model_dump())
                        for item in answer.dependencies
                    ),
                    supersedes_revision_id=(
                        prior_answer.revision_id if prior_answer is not None else None
                    ),
                )
            )
        answers = _DomainAnswersRecord(
            run_id=request.run_id,
            result_id=request.result_id,
            domain_id=request.domain_id,
            answers={step.question_id: step.answer.value for step in steps},
            rationales={step.question_id: step.rationale for step in steps},
            answer_revisions=tuple(answer_refs),
        )
        prior_answers = self._current_checkpoint_event(
            ledger, request.result_id, f"checkpoint:answers-{slug}"
        )
        answers_entity_id = (
            prior_answers.entity_id
            if prior_answers is not None
            else f"domain-answers:v3-{request.result_id.removeprefix('result:')}-{slug}"
        )
        transitions.append(
            self._transition(
                scope=request.result_id,
                operation="operation:submit-domain-answers",
                operation_key=f"{request.idempotency_key}:domain-answers",
                entity_id=answers_entity_id,
                revision_id=f"revision:domain-answers-v3-{self._digest(request.idempotency_key)}",
                artifact=answers,
                checkpoint=f"checkpoint:answers-{slug}",
                outcome=WorkflowEventOutcome.COMPLETED,
                observed_at=now,
                # Superseding any constituent SQAnswer invalidates its dependent
                # DomainAnswers projection earlier in this same atomic batch. In
                # that case the replacement is a fresh current projection; its
                # audit ancestry is already explicit through the SQAnswer chain.
                supersedes_revision_id=(
                    prior_answers.revision_id
                    if prior_answers is not None and not answer_revision_superseded
                    else None
                ),
                dependencies=tuple(
                    DependencyInput(**item.model_dump(), role="dependency:sq-answer")
                    for item in answer_refs
                ),
            )
        )
        return tuple(transitions)

    @staticmethod
    def _current_checkpoint_event(
        ledger: WorkflowLedger, scope: Identifier, checkpoint: Identifier
    ) -> WorkflowEvent | None:
        """Return the current checkpoint event to supersede, if any."""

        return next(
            (
                event
                for event in reversed(ledger.events())
                if event.scope == scope and event.checkpoint == checkpoint
            ),
            None,
        )

    def _question_step_response(
        self,
        ledger: WorkflowLedger,
        request: SubmitQuestionStepRequest,
        record: _QuestionStepRecord,
        result: CommitResult | WorkflowEvent,
        *,
        was_committed: bool,
    ) -> SubmitQuestionStepResponse:
        projection = self._projection(ledger, request.run_id)
        recovery_token = None
        if record.diagnostic_terminal:
            service = self._question_session_service(
                ledger, request.run_id, request.result_id, request.domain_id
            )
            state = service.load()
            stop = next(
                item
                for item in reversed(state.ledger.diagnostic_stops)
                if item.question_id == request.question_id
            )
            runtime = service.runtime_for_diagnostic_question(request.question_id)
            if self._chronology_diagnostic_is_recoverable(runtime.state.workflow):
                recovery_token = self._evidence_diagnostic_recovery_work_item(
                    request.run_id,
                    request.result_id,
                    request.domain_id,
                    request.question_id,
                    record.session_content_hash,
                    runtime.context.materialization_hash,
                    stop.content_hash,
                ).work_token
        return SubmitQuestionStepResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=was_committed,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=record.session_content_hash,
            diagnostic_terminal=record.diagnostic_terminal,
            correction_token=(
                None
                if record.diagnostic_terminal
                else self._question_correction_work_item(
                    request.run_id,
                    request.result_id,
                    request.domain_id,
                    request.question_id,
                    record.session_content_hash,
                ).work_token
            ),
            evidence_recovery_token=recovery_token,
        )

    @staticmethod
    def _evidence_diagnostic_recovery_actions(
        workflow: V3EvidenceWorkflowState,
    ) -> tuple[str, ...]:
        outcome_stage_ids = {item.stage_id for item in workflow.stage_outcomes}
        kinds = {
            limitation.kind
            for scope in workflow.stage_scopes
            if scope.stage_id in outcome_stage_ids
            for limitation in scope.role_limitations
        }
        actions: list[str] = []
        if V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED in kinds:
            actions.append(
                "Submit a changed attributable chronology fact with the evidence recovery token."
            )
        if V3ScopeLimitationKind.SOURCE_UNAVAILABLE in kinds:
            actions.append(
                "Acquire the unavailable accepted Source, then reconcile the changed inventory."
            )
        if V3ScopeLimitationKind.MATERIAL_UNRESOLVED in kinds:
            actions.append(
                "Reprocess or replace the unreadable accepted Source, then reconcile the changed inventory."
            )
        if V3ScopeLimitationKind.CROSS_SOURCE_INSUFFICIENT in kinds:
            actions.append(
                "Add another applicable accepted Source, then reconcile the changed inventory."
            )
        if not actions:
            actions.append(
                "Resolve the documented semantic evidence uncertainty through a changed evidence revision."
            )
        return tuple(actions)

    @staticmethod
    def _chronology_diagnostic_is_recoverable(workflow: V3EvidenceWorkflowState) -> bool:
        inventory = workflow.authorized_inventory
        for scope in workflow.stage_scopes:
            if not any(
                item.kind is V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED
                for item in scope.role_limitations
            ):
                continue
            if any(
                source.has_exact_source_parse
                and set(source.roles).intersection(scope.applicable_source_roles)
                for source in inventory
            ):
                return True
        return False

    def _question_correction_response(
        self,
        ledger: WorkflowLedger,
        request: CorrectQuestionStepRequest,
        record: _QuestionCorrectionRecord,
        result: CommitResult | WorkflowEvent,
        was_committed: bool,
    ) -> CorrectQuestionStepResponse:
        state = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        ).load()
        effective_ids = {item.question_id for item in effective_question_steps(state.ledger)}
        invalidated = tuple(
            step.question_id for step in state.ledger.steps if step.question_id not in effective_ids
        )
        projection = self._projection(ledger, request.run_id)
        return CorrectQuestionStepResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=was_committed,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
            question_id=request.question_id,
            session_content_hash=record.session_content_hash,
            frontier_entry_hash=next(
                (
                    item.entry_hash
                    for item in active_question_frontier(state.ledger).entries
                    if item.question_id == request.question_id
                ),
                None,
            ),
            invalidated_question_ids=invalidated,
            correction_token=self._question_correction_work_item(
                request.run_id,
                request.result_id,
                request.domain_id,
                request.question_id,
                record.session_content_hash,
            ).work_token,
        )

    def submit_source_chronology_review(
        self, request: SubmitSourceChronologyReviewRequest
    ) -> SubmitSourceChronologyReviewResponse:
        """Append an attributable chronology fact and refresh the v3 inventory revision."""

        ledger = self._bound_ledger(request.run_id)
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        recovery = request.work_token.operation is RunOperation.SUBMIT_SOURCE_CHRONOLOGY_REVIEW
        if recovery:
            state = service.load()
            stop = next(
                (
                    item
                    for item in reversed(state.ledger.diagnostic_stops)
                    if item.question_id == request.question_id
                ),
                None,
            )
            if stop is None:
                raise StaleWorkTokenError(request.run_id, None)
            runtime = service.runtime_for_diagnostic_question(request.question_id)
            expected_recovery = self._evidence_diagnostic_recovery_work_item(
                request.run_id,
                request.result_id,
                request.domain_id,
                request.question_id,
                state.content_hash,
                runtime.context.materialization_hash,
                stop.content_hash,
            )
            if expected_recovery.work_token != request.work_token:
                raise StaleWorkTokenError(request.run_id, None)
        else:
            expected = self._next_work_item(ledger, request.run_id)
            if expected is None or expected.work_token != request.work_token:
                raise StaleWorkTokenError(request.run_id, expected)
            if (
                expected.question_id != request.question_id
                or expected.result_id != request.result_id
                or expected.domain_id != request.domain_id
                or expected.operation is not RunOperation.SUBMIT_QUESTION_STEP
            ):
                raise StaleWorkTokenError(request.run_id, expected)
            runtime = service.runtime_for_question(request.question_id)
        source = next(
            (
                item
                for item in runtime.context.authorized_inventory
                if item.source_id == request.source_id
            ),
            None,
        )
        if source is None or (
            source.source_artifact_hash,
            source.parse_id,
            source.parse_output_hash,
        ) != (
            request.source_artifact_hash,
            request.parse_id,
            request.parse_output_hash,
        ):
            raise InvalidRetrievalRequest(
                "chronology review must bind the exact session Source/Parse"
            )
        if recovery:
            prior_fact = next(
                (item for item in source.chronology_facts if item.constraint is request.constraint),
                None,
            )
            if prior_fact is not None and (
                prior_fact.status,
                prior_fact.rationale,
            ) == (request.status, request.rationale):
                raise InvalidRetrievalRequest(
                    "evidence diagnostic recovery requires a changed materialized chronology fact"
                )
        index = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3")
        scope = EvidenceScope(
            result_id=request.result_id,
            domain_id=request.domain_id,
            question_id=request.question_id,
            source_ids=(request.source_id,),
            parse_ids=(request.parse_id,),
        )
        try:
            index.resolve_read_view_receipt(request.evidence_read_receipt, scope=scope)
        except RetrievalFailure as error:
            raise InvalidRetrievalRequest(
                "chronology review requires an exact current evidence read receipt"
            ) from error
        record = _SourceChronologyReviewRecord(run_id=request.run_id, submission=request)
        if recovery:
            now = self._now()
            suffix = self._digest(
                f"{request.run_id}|{request.result_id}|{request.idempotency_key}|"
                f"{runtime.context.materialization_hash}"
            )
            review_transition = self._submission_transition(
                run_id=request.run_id,
                scope=request.result_id,
                operation="operation:submit-source-chronology-review",
                operation_key=request.idempotency_key,
                artifact=record,
                checkpoint=(
                    f"checkpoint:source-chronology-{request.source_id.removeprefix('source:')}-"
                    f"{request.constraint.value}"
                ),
                observed_at=now,
            )
            transitions: list[Transition] = []
            projection = self._projection(ledger, request.run_id)
            if projection.run_state is RunState.COMPLETE:
                transitions.append(
                    self._transition(
                        scope=request.run_id,
                        operation="operation:run-reopened",
                        operation_key=f"{request.idempotency_key}:run-reopened",
                        entity_id=f"run-evidence-recovery:{suffix}",
                        revision_id=f"revision:run-evidence-recovery-{suffix}",
                        artifact=_RunReopenedRecord(
                            run_id=request.run_id,
                            input_snapshot_hash=self._latest_proposal(
                                ledger, request.run_id
                            ).input_snapshot_hash,
                            invalidated_result_ids=(request.result_id,),
                        ),
                        checkpoint=f"checkpoint:run-evidence-recovery-{suffix}",
                        outcome=WorkflowEventOutcome.WORK_REQUIRED,
                        observed_at=now,
                    )
                )
            transitions.extend(
                (
                    review_transition,
                    self._transition(
                        scope=request.result_id,
                        operation="operation:result-invalidated",
                        operation_key=f"{request.idempotency_key}:result-invalidated",
                        entity_id=f"result-evidence-recovery:{suffix}",
                        revision_id=f"revision:result-evidence-recovery-{suffix}",
                        artifact=_ResultInvalidatedRecord(
                            run_id=request.run_id,
                            result_id=request.result_id,
                            reason="An attributable chronology fact changed after an evidence diagnostic.",
                            affected_trial_id=self._trial_id_for_result(request.result_id)
                            or "trial:unknown",
                            affected_source_ids=(request.source_id,),
                            input_snapshot_hash=self._latest_proposal(
                                ledger, request.run_id
                            ).input_snapshot_hash,
                        ),
                        checkpoint=f"checkpoint:result-evidence-recovery-{suffix}",
                        outcome=WorkflowEventOutcome.WORK_REQUIRED,
                        observed_at=now,
                    ),
                )
            )
            committed_results = self._commit_transitions(
                ledger, tuple(transitions), self._acquire_lease(ledger, now), now=now
            )
            # Review is always immediately before the Result invalidation;
            # an optional Run-reopened transition precedes both.
            committed = committed_results[-2]
        else:
            committed = self._commit_submission(
                ledger,
                run_id=request.run_id,
                scope=request.result_id,
                operation="operation:submit-source-chronology-review",
                operation_key=request.idempotency_key,
                artifact=record,
                checkpoint=(
                    f"checkpoint:source-chronology-{request.source_id.removeprefix('source:')}-"
                    f"{request.constraint.value}"
                ),
            )
        refreshed_service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        refreshed_service.initialize()
        refreshed_runtime = refreshed_service.runtime_for_question(request.question_id)
        if recovery and (
            refreshed_runtime.context.materialization_hash == request.work_token.context_hash
        ):
            raise RunIntegrityFailure(
                "evidence recovery did not produce a new materialized context revision"
            )
        projection = self._projection(ledger, request.run_id)
        return SubmitSourceChronologyReviewResponse(
            operation_id=committed.operation_id,
            ledger_cursor=f"ledger:{committed.sequence}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=not committed.duplicate,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
            question_id=request.question_id,
            source_id=request.source_id,
            inventory_revision_id=refreshed_service.load().inventory_revision_id,
            inventory_revision_hash=refreshed_service.load().inventory_revision_hash,
        )

    def submit_evidence_stage_outcome(
        self, request: SubmitEvidenceStageOutcomeRequest
    ) -> SubmitEvidenceStageOutcomeResponse:
        """Commit a reducer-validated v3 stage outcome under current question authority."""

        ledger = self._bound_ledger(request.run_id)
        expected = self._next_work_item(ledger, request.run_id)
        if expected is None or expected.work_token != request.work_token:
            raise StaleWorkTokenError(request.run_id, expected)
        if (
            expected.operation is not RunOperation.SUBMIT_QUESTION_STEP
            or expected.question_id != request.question_id
            or expected.session_content_hash != request.session_content_hash
            or (expected.result_id, expected.domain_id) != (request.result_id, request.domain_id)
        ):
            raise StaleWorkTokenError(request.run_id, expected)
        service = self._question_session_service(
            ledger, request.run_id, request.result_id, request.domain_id
        )
        runtime = service.runtime_for_question(request.question_id)
        result = runtime.runtime.submit_stage_outcome(
            expected_content_hash=request.expected_navigation_state_hash,
            submission=request.submission,
        )
        record = _EvidenceStageOutcomeRecord(
            run_id=request.run_id,
            submission=request,
            navigation_state_hash=result.state.content_hash,
        )
        committed = self._commit_submission(
            ledger,
            run_id=request.run_id,
            scope=request.result_id,
            operation="operation:submit-evidence-stage-outcome",
            operation_key=request.idempotency_key,
            artifact=record,
            checkpoint=(
                f"checkpoint:evidence-stage-{request.question_id.removeprefix('sq:')}-"
                f"{request.submission.stage_id.removeprefix('stage:')}"
            ),
        )
        projection = self._projection(ledger, request.run_id)
        return SubmitEvidenceStageOutcomeResponse(
            operation_id=committed.operation_id,
            ledger_cursor=f"ledger:{committed.sequence}",
            affected_scope=(request.result_id, request.domain_id, request.question_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=not committed.duplicate,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result_id,
            result_state=self._result_state(projection, request.result_id),
            domain_id=request.domain_id,
            question_id=request.question_id,
            navigation_state_hash=result.state.content_hash,
            progress=result.progress,
        )

    def _retrieval_scope(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        work_token: WorkToken,
        result_id: Identifier | None,
        sq_id: Identifier | None = None,
        *,
        require_question: bool = True,
    ) -> EvidenceScope:
        """Resolve retrieval scope from the active Work token before retrieval.

        Search and read routes require a signaling-question scope so every
        retrieval page is attributable to one active question.
        """

        expected = self._next_work_item(ledger, run_id)
        if expected is None or expected.work_token != work_token:
            raise StaleWorkToken(
                "stale WorkToken: call continue_run and use the current evidence work item"
            )
        if work_token.operation is not RunOperation.SUBMIT_QUESTION_STEP:
            raise ScopeMismatch(
                "retrieval is available only during an active evidence work item",
                field="work_token.operation",
            )
        if result_id is not None and result_id != work_token.result_id:
            raise ScopeMismatch(
                "result_id must match the active WorkToken scope", field="result_id"
            )
        if require_question and sq_id is None:
            raise InvalidRetrievalRequest(
                "sq_id is required for scoped evidence retrieval", field="sq_id"
            )
        if work_token.operation is RunOperation.SUBMIT_QUESTION_STEP:
            if sq_id != work_token.question_id:
                raise ScopeMismatch(
                    "sq_id must match the question bound into the current WorkToken",
                    field="sq_id",
                )
            if work_token.result_id is None or work_token.domain_id is None or sq_id is None:
                raise ScopeMismatch("question WorkToken has incomplete scope", field="work_token")
            runtime = self._question_session_service(
                ledger, run_id, work_token.result_id, work_token.domain_id
            ).runtime_for_question(sq_id)
            return EvidenceScope(
                trial_id=work_token.trial_id,
                result_id=work_token.result_id,
                domain_id=work_token.domain_id,
                question_id=sq_id,
                source_ids=tuple(
                    item.source_id
                    for item in runtime.context.authorized_inventory
                    if item.has_exact_source_parse
                ),
                parse_ids=tuple(
                    item.parse_id
                    for item in runtime.context.authorized_inventory
                    if item.has_exact_source_parse and item.parse_id is not None
                ),
                work_token_id=work_token.token,
            )
        if work_token.domain_id is not None:
            domain = next(
                (item for item in self._logic_pack().domains if item.id == work_token.domain_id),
                None,
            )
            if domain is None or (sq_id is not None and sq_id not in domain.question_ids):
                raise ScopeMismatch(
                    "sq_id is not an active question in the WorkToken Domain", field="sq_id"
                )
        source_ids: tuple[Identifier, ...] = ()
        if work_token.trial_id is not None:
            proposal = self._latest_proposal(ledger, run_id)
            trial = next(
                (
                    item
                    for item in proposal.initialization.trials
                    if item.trial_id == work_token.trial_id
                ),
                None,
            )
            if trial is not None:
                source_ids = tuple(
                    source.source_id
                    for source in trial.inventory.sources
                    if source.artifact_hash is not None
                )
        return EvidenceScope(
            trial_id=work_token.trial_id,
            result_id=work_token.result_id,
            domain_id=work_token.domain_id,
            question_id=sq_id,
            source_ids=source_ids,
            work_token_id=work_token.token,
        )

    @staticmethod
    def _validate_citable_unit(
        unit: CanonicalEvidenceUnit,
        scope: EvidenceScope,
    ) -> None:
        """Shared citation gate for passage and legacy EvidenceClaim paths."""
        # Parser/search labels are visibility diagnostics, never semantic
        # eligibility authorities, except where they say that the text is not
        # a deterministic canonical unit at all.  Those fragments remain
        # searchable/readable, but a text claim must await visual
        # transcription or successful re-canonicalization.
        if scope.source_ids and unit.source_id not in scope.source_ids:
            raise ValueError("canonical unit source is outside active WorkToken custody")
        fragment_warnings = {
            "canonical_kind_unclassified",
            "canonical_structure_unavailable",
            "reading_order_uncertain",
        }
        if unit.kind is CanonicalUnitKind.UNCLASSIFIED or fragment_warnings.intersection(
            unit.warnings
        ):
            raise ValueError(
                "ambiguous or unclassified fragment cannot ground a canonical Evidence claim; "
                "use a qualifying Visual transcription or re-canonicalize it"
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

    def submit_source_role_review(
        self, request: SubmitSourceRoleReviewRequest
    ) -> SubmitSourceRoleReviewResponse:
        bound_ledger = self._bound_ledger(request.run_id)
        existing = self._submission_retry_event(
            bound_ledger,
            request.run_id,
            request.idempotency_key,
            {"operation:submit-source-role-review"},
        )
        if existing is not None:
            if (
                SubmitSourceRoleReviewRequest.model_validate_json(
                    bound_ledger.artifacts.read(existing.output_revision_hashes[0])
                )
                != request
            ):
                return SubmitSourceRoleReviewResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(bound_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_SOURCE_ROLE_REVIEW,
                        bound_ledger,
                    )
                )
            projection = self._projection(bound_ledger, request.run_id)
            return SubmitSourceRoleReviewResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(bound_ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_SOURCE_ROLE_REVIEW,
                request.idempotency_key,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitSourceRoleReviewResponse(
                **self._stale_submission_kwargs(
                    error, RunOperation.SUBMIT_SOURCE_ROLE_REVIEW, ledger
                )
            )
        initialization = (
            self._latest_proposal(ledger, request.run_id).initialization
            if self._has_durable_proposal(ledger, request.run_id)
            else self._prepared_initialization(ledger, request.run_id)
        )
        # Before confirmation every inventory-ready source is in scope; after
        # reconciliation the current successor proposal likewise owns the
        # newly issued Source candidates rather than the historical prepared
        # inventory.
        issued_sources = {
            source.source_id
            for trial in initialization.trials
            if trial.status == "inventory_ready"
            for source in trial.inventory.sources
            if SourceRole.REGISTRY_CURRENT not in source.roles
        }
        projection = self._projection(ledger, request.run_id)
        violations: list[OperationError] = []
        if any(selection.source_id is None for selection in request.selections):
            violations.append(
                OperationError(
                    code="invalid_configuration",
                    detail="Source-role review selections must set source_id.",
                    recovery=("Resubmit with source_id set on every selection.",),
                )
            )
        submitted_sources = {
            selection.source_id
            for selection in request.selections
            if selection.source_id is not None
        }
        unissued_sources = submitted_sources - issued_sources
        if unissued_sources:
            violations.append(
                OperationError(
                    code="invalid_configuration",
                    detail="Source-role review includes an unissued source identifier.",
                    recovery=("Resubmit using only source IDs issued for this Run.",),
                )
            )
        missing_sources = issued_sources - submitted_sources
        if missing_sources:
            violations.append(
                OperationError(
                    code="invalid_configuration",
                    detail="Source-role review must include every inventory-ready source.",
                    recovery=("Resubmit including a disposition for every issued source.",),
                )
            )
        if violations:
            primary = violations[0]
            return SubmitSourceRoleReviewResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_SOURCE_ROLE_REVIEW, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                error=primary.model_copy(update={"violations": tuple(violations)}),
            )
        try:
            result = self._commit_submission(
                ledger,
                run_id=request.run_id,
                scope=request.run_id,
                operation="operation:submit-source-role-review",
                operation_key=request.idempotency_key,
                artifact=request,
                checkpoint="checkpoint:source-role-review",
            )
        except LeaseConflictError:
            projection = self._projection(ledger, request.run_id)
            return SubmitSourceRoleReviewResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_SOURCE_ROLE_REVIEW, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.RETRY,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=projection.run_state,
                error=OperationError(
                    error_class=ErrorClass.AUTHORITY,
                    code="authorization_required",
                    detail="Another live Run writer holds the project lease.",
                    recovery=("Wait for the active writer, then continue the Run.",),
                ),
            )
        projection = self._projection(ledger, request.run_id)
        return SubmitSourceRoleReviewResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=not result.duplicate,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
        )

    def submit_proposal_discovery_review(
        self, request: SubmitProposalDiscoveryReviewRequest
    ) -> SubmitProposalDiscoveryReviewResponse:
        """Persist one bounded full-text review; it cannot bind Run identity."""

        # A transport retry necessarily carries a consumed discovery token.
        # Resolve an exact durable replay before evaluating token freshness so
        # a lost response never turns a successful source review into STALE.
        replay_ledger = self._bound_ledger(request.run_id)
        existing = self._event_for_operation_key(
            replay_ledger, request.idempotency_key, run_id=request.run_id
        )
        if existing is not None:
            if existing.operation != "operation:submit-proposal-discovery-review":
                return SubmitProposalDiscoveryReviewResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(replay_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                        replay_ledger,
                    )
                )
            persisted = SubmitProposalDiscoveryReviewRequest.model_validate_json(
                replay_ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if persisted != request:
                return SubmitProposalDiscoveryReviewResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(replay_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                        replay_ledger,
                    )
                )
            proposal = next(
                (
                    _ProposalSubmittedRecord.model_validate_json(
                        replay_ledger.artifacts.read(event.output_revision_hashes[0])
                    ).proposal
                    for event in self._events_for_run(replay_ledger, request.run_id)
                    if event.operation == "operation:run-proposal-discovery-reviewed"
                    and any(
                        item.receipt_id == request.coverage_receipt.receipt_id
                        for item in _ProposalSubmittedRecord.model_validate_json(
                            replay_ledger.artifacts.read(event.output_revision_hashes[0])
                        ).proposal.proposal_discovery_receipts
                    )
                ),
                None,
            )
            return SubmitProposalDiscoveryReviewResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(replay_ledger.events())}",
                affected_scope=(request.run_id, request.work_token.trial_id or request.run_id),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=self._projection(replay_ledger, request.run_id).run_state,
                proposal=proposal,
            )

        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                request.idempotency_key,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitProposalDiscoveryReviewResponse(
                **self._stale_submission_kwargs(
                    error, RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW, ledger
                )
            )
        latest = (
            self._latest_proposal(ledger, request.run_id)
            if self._has_durable_proposal(ledger, request.run_id)
            else None
        )
        initialization = (
            latest.initialization
            if latest is not None
            else self._initialization_with_resolved_source_roles(ledger, request.run_id)
        )
        if request.work_token.source_id != request.coverage_receipt.source_id:
            raise ValueError(
                "proposal discovery receipt does not match the engine-issued Source scope"
            )
        source = self._discovery_source(
            initialization, request.work_token.trial_id, request.work_token.source_id
        )
        if source is None or not self._is_eligible_discovery_source(source):
            raise ValueError("proposal discovery must review one issued eligible full-text source")
        receipt = request.coverage_receipt
        issued_policy = self._proposal_discovery_policy(initialization, receipt.mode)
        if receipt.discovery_policy_revision != issued_policy.policy_revision:
            raise ValueError("proposal discovery receipt policy revision was not engine-issued")
        if receipt.trial_id != request.work_token.trial_id or receipt.source_id != source.source_id:
            raise ValueError("proposal discovery receipt does not match the issued work scope")
        if (
            request.work_token.parse_id is not None
            and receipt.parse_id != request.work_token.parse_id
        ):
            raise ValueError(
                "proposal discovery receipt does not match the engine-issued Parse scope"
            )
        if (
            source.artifact_hash is None
            or receipt.source_artifact_hash != source.artifact_hash
            or receipt.parse_id
            not in {
                record.parse_id
                for record in source.parse_records
                if record.artifact_hash == source.artifact_hash
            }
        ):
            raise ValueError(
                "proposal discovery receipt must bind the current Source artifact and Parse"
            )
        if (receipt.mode == "target_guided") != bool(initialization.manifest.outcome_target_specs):
            raise ValueError("proposal discovery mode must match the declared-target inventory")
        required_passes = issued_policy.required_passes
        if (
            receipt.required_passes != required_passes
            or receipt.completed_passes != required_passes
        ):
            raise ValueError(
                "proposal discovery passes must exactly match the engine-issued coverage policy"
            )
        if receipt.structural_passes or receipt.query_passes != required_passes:
            raise ValueError(
                "proposal discovery receipt pass classifications must exactly match engine-issued policy"
            )
        navigation = self._proposal_discovery_navigation.get(
            (request.run_id, request.work_token.token)
        )
        if navigation is None:
            navigation = self._durable_proposal_discovery_navigation(
                ledger, request.run_id, request.work_token
            )
            if navigation is not None:
                self._proposal_discovery_navigation[(request.run_id, request.work_token.token)] = (
                    navigation
                )
        if navigation is None:
            raise ValueError(
                "proposal discovery receipt requires engine-observed indexed navigation"
            )
        pass_states = navigation["passes"]
        if set(pass_states) != set(required_passes) or not all(
            state["complete"] and state.get("qualifying_search", False)
            for state in pass_states.values()
        ):
            raise ValueError(
                "proposal discovery receipt requires every engine-issued semantic pass to finish"
            )
        observed_continuations = tuple(
            continuation
            for pass_name in required_passes
            for continuation in pass_states[pass_name]["continuations"]
        )
        if receipt.traversed_continuations != observed_continuations:
            raise ValueError("proposal discovery receipt continuations were not engine-observed")
        observed_units = set().union(
            *(state["candidate_unit_ids"] for state in pass_states.values())
        )
        if not observed_units <= navigation["read_unit_ids"]:
            raise ValueError(
                "proposal discovery receipt requires reads of all surfaced canonical units"
            )
        if set(receipt.reviewed_unit_ids) != navigation["read_unit_ids"]:
            raise ValueError("proposal discovery receipt reviewed units were not engine-observed")
        candidates = (*request.endpoints, *request.randomizations, *request.arms)
        candidate_ids = {item.candidate_id for item in candidates}
        if len(candidate_ids) != len(candidates):
            raise ValueError("proposal discovery candidate IDs must be unique")
        issued_candidate_ids: set[Identifier] = set()
        for event in self._events_for_run(ledger, request.run_id):
            if event.operation != "operation:submit-proposal-discovery-review":
                continue
            payload = self._event_payload(ledger, event)
            issued_candidate_ids.update(
                item.get("candidate_id")
                for field in ("endpoints", "randomizations", "arms")
                for item in payload.get(field, ())
                if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
            )
        if candidate_ids.intersection(issued_candidate_ids):
            raise ValueError(
                "proposal discovery candidate IDs must be globally unique across sources"
            )
        if set(receipt.candidate_ids) != candidate_ids:
            raise ValueError("proposal discovery receipt must enumerate every submitted candidate")
        prior_candidates: dict[Identifier, Any] = {}
        for event in self._events_for_run(ledger, request.run_id):
            if event.operation != "operation:submit-proposal-discovery-review":
                continue
            payload = self._event_payload(ledger, event)
            for field in ("endpoints", "randomizations", "arms"):
                for item in payload.get(field, ()):
                    if isinstance(item, dict) and isinstance(item.get("candidate_id"), str):
                        prior_candidates[item["candidate_id"]] = item
        known_candidates = {
            **prior_candidates,
            **{item.candidate_id: item for item in candidates},
        }
        for candidate in candidates:
            if candidate.relationship == "reported":
                continue
            for related_candidate_id in candidate.related_candidate_ids:
                related = known_candidates.get(related_candidate_id)
                if related is None:
                    raise ValueError(
                        "cross-source candidate relationship references an unknown candidate"
                    )
                related_source_id = (
                    related.provenance.source_id
                    if not isinstance(related, dict)
                    else ((related.get("provenance") or {}).get("source_id"))
                )
                if related_source_id == candidate.provenance.source_id:
                    raise ValueError("cross-source candidate relationship must name another Source")
        if not candidate_ids and receipt.state not in {
            "no_candidates",
            "complete_with_limitations",
        }:
            raise ValueError(
                "empty discovery requires an explicit no-candidates or limited terminal receipt"
            )
        if receipt.state == "no_candidates" and (
            receipt.reviewed_by is None or receipt.reviewed_at is None
        ):
            raise ValueError(
                "empty discovery receipt requires attributable reviewer identity and timestamp"
            )
        request_dispositions = {
            item.candidate_id: item.model_dump(mode="json") for item in request.dispositions
        }
        receipt_dispositions = {
            item.candidate_id: item.model_dump(mode="json")
            for item in receipt.candidate_dispositions
        }
        if len(request_dispositions) != len(request.dispositions) or len(
            receipt_dispositions
        ) != len(receipt.candidate_dispositions):
            raise ValueError("discovery dispositions must contain exactly one entry per candidate")
        if set(request_dispositions) != candidate_ids:
            raise ValueError("every surfaced discovery candidate requires one disposition")
        if request_dispositions != receipt_dispositions:
            raise ValueError("coverage receipt dispositions must match the reviewed submission")
        for candidate in candidates:
            if candidate.trial_id != receipt.trial_id:
                raise ValueError("reported candidate crosses the issued Trial")
            provenance = candidate.provenance
            if provenance.discovery_policy_revision != receipt.discovery_policy_revision:
                raise ValueError(
                    "reported candidate policy revision does not match the issued receipt"
                )
            if provenance.source_id != source.source_id or provenance.parse_id != receipt.parse_id:
                raise ValueError(
                    "reported candidate provenance must bind the reviewed Source and Parse"
                )
            if provenance.artifact_hash != receipt.source_artifact_hash:
                raise ValueError(
                    "reported candidate provenance must bind the receipt Source artifact"
                )
            self._validate_discovery_provenance(provenance, source)
            if provenance.canonical_unit_id not in navigation["read_unit_ids"]:
                raise ValueError("reported candidate provenance was not read under this WorkToken")
        randomizations = {item.candidate_id: item for item in request.randomizations}
        for randomization in request.randomizations:
            if randomization.arm_candidate_ids != tuple(
                arm.candidate_id
                for arm in request.arms
                if arm.randomization_candidate_id == randomization.candidate_id
            ):
                raise ValueError(
                    "reported randomization must name its complete linked reported Arms in order"
                )
        for arm in request.arms:
            if arm.randomization_candidate_id not in randomizations:
                raise ValueError(
                    "reported Arm cannot be submitted independently of its Randomization"
                )
        for endpoint in request.endpoints:
            if endpoint.randomization_candidate_id is not None:
                randomization = randomizations.get(endpoint.randomization_candidate_id)
                if (
                    randomization is None
                    or endpoint.experimental_arm_candidate_id not in randomization.arm_candidate_ids
                    or endpoint.comparator_arm_candidate_id not in randomization.arm_candidate_ids
                ):
                    raise ValueError(
                        "reported endpoint comparison must use Arms from its one Randomization"
                    )
        next_proposal: RunProposal | None = None
        refreshed = initialization
        now = self._now()
        transitions = [
            self._submission_transition(
                run_id=request.run_id,
                scope=request.work_token.trial_id or request.run_id,
                operation="operation:submit-proposal-discovery-review",
                operation_key=request.idempotency_key,
                artifact=request,
                checkpoint="checkpoint:proposal-discovery-review",
                observed_at=now,
            )
        ]
        if self._initialization_discovery_complete(
            refreshed, ledger, request.run_id, pending_receipt=request.coverage_receipt
        ):
            next_proposal = self._proposal_from_discovery(
                refreshed, ledger, request.run_id, pending_request=request
            )
            suffix = self._digest(f"{request.run_id}|discovery|{next_proposal.proposal_token}")
            transition = self._transition(
                scope=request.run_id,
                operation="operation:run-proposal-discovery-reviewed",
                operation_key=f"idempotency:proposal-discovery-{suffix}",
                entity_id=f"run-proposal-discovery:{suffix}",
                revision_id=f"revision:run-proposal-discovery-{suffix}",
                artifact=_ProposalSubmittedRecord(run_id=request.run_id, proposal=next_proposal),
                checkpoint="checkpoint:run-proposal-discovery-reviewed",
                outcome=WorkflowEventOutcome.WORK_REQUIRED,
                observed_at=now,
            )
            transitions.append(transition)
        self._validate_idempotent_event(
            ledger,
            request.idempotency_key,
            transitions[0].operation,
            request,
            run_id=request.run_id,
        )
        committed = self._commit_transitions(
            ledger, tuple(transitions), self._acquire_lease(ledger, now), now=now
        )
        result = committed[0]
        self._run_event_cache.pop((ledger.path.resolve(), request.run_id), None)
        projection = self._projection(ledger, request.run_id)
        return SubmitProposalDiscoveryReviewResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.run_id, request.work_token.trial_id or request.run_id),
            condition=WorkflowCondition.ACCEPTED,
            committed=True,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            proposal=next_proposal,
        )

    def submit_result_mapping_review(
        self, request: SubmitResultMappingReviewRequest
    ) -> SubmitResultMappingReviewResponse:
        # A lost response is retried with a token that has necessarily been
        # consumed by the first commit.  Replay the exact durable successor
        # before applying the ordinary stale-work guard.
        replay_ledger = self._bound_ledger(request.run_id)
        existing = self._event_for_operation_key(
            replay_ledger, request.idempotency_key, run_id=request.run_id
        )
        if existing is not None:
            if existing.operation != "operation:submit-result-mapping-review":
                return SubmitResultMappingReviewResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(replay_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
                        replay_ledger,
                    )
                )
            persisted = SubmitResultMappingReviewRequest.model_validate_json(
                replay_ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if persisted != request:
                return SubmitResultMappingReviewResponse(
                    **self._stale_submission_kwargs(
                        StaleWorkTokenError(
                            request.run_id, self._next_work_item(replay_ledger, request.run_id)
                        ),
                        RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
                        replay_ledger,
                    )
                )
            successor_event = self._event_for_operation_key(
                replay_ledger, f"{request.idempotency_key}:proposal", run_id=request.run_id
            )
            if successor_event is None:
                raise RuntimeError("Result mapping successor disappeared during replay")
            successor = _ProposalSubmittedRecord.model_validate_json(
                replay_ledger.artifacts.read(successor_event.output_revision_hashes[0])
            ).proposal
            return SubmitResultMappingReviewResponse(
                operation_id=existing.operation_id,
                ledger_cursor=f"ledger:{len(replay_ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.ACCEPTED,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=self._projection(replay_ledger, request.run_id).run_state,
                proposal=successor,
            )
        try:
            ledger = self._submission_ledger(
                request.run_id,
                request.work_token,
                RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
                request.idempotency_key,
            )
        except StaleWorkTokenError as error:
            ledger = self._bound_ledger(request.run_id)
            return SubmitResultMappingReviewResponse(
                **self._stale_submission_kwargs(
                    error, RunOperation.SUBMIT_RESULT_MAPPING_REVIEW, ledger
                )
            )
        proposal = self._latest_proposal(ledger, request.run_id)
        if request.proposal_token != proposal.proposal_token:
            return SubmitResultMappingReviewResponse(
                operation_id=self._read_operation_id(
                    RunOperation.SUBMIT_RESULT_MAPPING_REVIEW, request.run_id
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(request.run_id,),
                condition=WorkflowCondition.STALE,
                committed=False,
                next_action=RunOperation.CONTINUE_RUN,
                run_id=request.run_id,
                run_state=self._projection(ledger, request.run_id).run_state,
                proposal=proposal,
                error=OperationError(
                    code="stale_proposal",
                    detail="A newer Run proposal has superseded this mapping proposal token.",
                    recovery=("Discard the stale token and request the current mapping work.",),
                ),
            )
        endpoints = {item.candidate_id: item for item in proposal.reported_endpoint_candidates}
        randomizations = {
            item.candidate_id: item for item in proposal.reported_randomization_candidates
        }
        arms = {item.candidate_id: item for item in proposal.reported_arm_candidates}
        randomization_bindings = dict(proposal.randomization_bindings)
        arm_bindings = dict(proposal.arm_bindings)
        discovery_dispositions = {
            disposition.candidate_id: disposition.disposition
            for receipt in proposal.proposal_discovery_receipts
            for disposition in receipt.candidate_dispositions
        }
        # A mapping review is an iterative proposal revision.  Retain prior
        # reviewed mappings and replace only the explicitly re-reviewed
        # candidate IDs; dropping a prior candidate would silently reopen a
        # mapping that was already attributable and selected.
        candidates_by_id = {item.candidate_id: item for item in proposal.result_candidates}
        for mapping in request.mappings:
            if mapping.outcome_target_id is not None and mapping.outcome_target_id not in {
                target.target_id for target in proposal.initialization.manifest.outcome_target_specs
            }:
                raise ValueError("Result mapping references an unissued Outcome target")
            endpoint = endpoints.get(mapping.endpoint_candidate_id)
            randomization = randomizations.get(mapping.randomization_candidate_id)
            if (
                endpoint is None
                or randomization is None
                or endpoint.trial_id != mapping.trial_id
                or randomization.trial_id != mapping.trial_id
            ):
                raise ValueError(
                    "Result mapping references unissued endpoint or Randomization candidates"
                )
            if any(
                discovery_dispositions.get(candidate_id) != "accepted"
                for candidate_id in (
                    mapping.endpoint_candidate_id,
                    mapping.randomization_candidate_id,
                    mapping.experimental_arm_candidate_id,
                    mapping.comparator_arm_candidate_id,
                )
            ):
                raise ValueError("Result mapping requires accepted reported candidates")
            if (
                endpoint.randomization_candidate_id is not None
                and endpoint.randomization_candidate_id != mapping.randomization_candidate_id
            ):
                raise ValueError("Result mapping crosses the reported endpoint Randomization")
            if endpoint.experimental_arm_candidate_id is not None and (
                endpoint.experimental_arm_candidate_id,
                endpoint.comparator_arm_candidate_id,
            ) != (
                mapping.experimental_arm_candidate_id,
                mapping.comparator_arm_candidate_id,
            ):
                raise ValueError("Result mapping crosses the reported endpoint comparison")
            if {mapping.experimental_arm_candidate_id, mapping.comparator_arm_candidate_id} - set(
                randomization.arm_candidate_ids
            ):
                raise ValueError("Result mapping comparison crosses the reported Randomization")
            if (
                mapping.experimental_arm_candidate_id not in arms
                or mapping.comparator_arm_candidate_id not in arms
            ):
                raise ValueError("Result mapping references unissued reported Arms")
            if mapping.randomization_candidate_id not in randomization_bindings or (
                mapping.experimental_arm_candidate_id not in arm_bindings
                or mapping.comparator_arm_candidate_id not in arm_bindings
            ):
                raise ValueError("Result mapping requires human-promoted Randomization and Arms")
            if mapping.result is not None and (
                mapping.result.trial_id != mapping.trial_id
                or mapping.result.randomization_id
                != randomization_bindings[mapping.randomization_candidate_id]
                or mapping.result.comparison.experimental_arm_id
                != arm_bindings[mapping.experimental_arm_candidate_id]
                or mapping.result.comparison.comparator_arm_id
                != arm_bindings[mapping.comparator_arm_candidate_id]
            ):
                raise ValueError(
                    "complete Result mapping must use engine-issued promoted design IDs"
                )
            if mapping.result is not None:
                if mapping.source_provenance is None:
                    raise ValueError("complete Result mapping requires exact endpoint provenance")
                endpoint_provenance = endpoint.provenance
                observed_provenance = mapping.source_provenance
                if (
                    observed_provenance.source_id,
                    observed_provenance.parse_id,
                    observed_provenance.artifact_hash,
                    observed_provenance.canonical_unit_id,
                    observed_provenance.page_number,
                    observed_provenance.char_start,
                    observed_provenance.char_end,
                    observed_provenance.locator,
                ) != (
                    endpoint_provenance.source_id,
                    endpoint_provenance.parse_id,
                    endpoint_provenance.artifact_hash,
                    endpoint_provenance.canonical_unit_id,
                    endpoint_provenance.page_number,
                    endpoint_provenance.char_start,
                    endpoint_provenance.char_end,
                    endpoint_provenance.locator,
                ) or mapping.result.source_locator != endpoint_provenance.locator:
                    raise ValueError(
                        "complete Result mapping must bind the exact accepted endpoint canonical unit, page, and span"
                    )
            if mapping.result is not None and mapping.outcome_target_id is not None:
                target = next(
                    item
                    for item in proposal.initialization.manifest.outcome_target_specs
                    if item.target_id == mapping.outcome_target_id
                )
                if (
                    target.outcome_construct
                    and (
                        mapping.result.outcome_construct.casefold()
                        != target.outcome_construct.casefold()
                    )
                    and mapping.construct_admissibility != "accepted_synonym"
                ):
                    raise ValueError(
                        "complete Result mapping outcome construct conflicts with target"
                    )
                if (
                    target.time_point
                    and mapping.result.time_point.casefold() != target.time_point.casefold()
                ):
                    raise ValueError("complete Result mapping time point conflicts with target")
                if (
                    target.accepted_instruments
                    and mapping.result.measurement_instrument not in target.accepted_instruments
                ):
                    raise ValueError("complete Result mapping instrument is not accepted by target")
                if (
                    target.accepted_effect_measures
                    and mapping.result.effect_measure not in target.accepted_effect_measures
                ):
                    raise ValueError(
                        "complete Result mapping effect measure is not accepted by target"
                    )
                if (
                    target.effect_of_interest
                    and mapping.result.effect_of_interest != target.effect_of_interest
                ):
                    raise ValueError(
                        "complete Result mapping effect of interest conflicts with target"
                    )
            complete_mapping = (
                mapping.mapping_status is ProposalMappingStatus.ACCEPTED
                and mapping.identity_completeness is ResultIdentityCompleteness.RESULT_COMPLETE
            )
            result_id = (
                mapping.result.result_id
                if complete_mapping and mapping.result is not None
                else (
                    f"result:pending-{self._digest(f'{request.run_id}|{mapping.candidate_id}')}"
                    if mapping.mapping_status is ProposalMappingStatus.PROPOSED
                    else None
                )
            )
            candidates_by_id[mapping.candidate_id] = ResultCandidate(
                candidate_id=mapping.candidate_id,
                trial_id=mapping.trial_id,
                outcome_target_id=mapping.outcome_target_id,
                result_id=result_id,
                label=mapping.label,
                source_locator=(
                    mapping.result.source_locator if mapping.result else endpoint.provenance.locator
                ),
                status="resolved" if complete_mapping else "needs_input",
                mapping_status=mapping.mapping_status,
                identity_completeness=mapping.identity_completeness,
                endpoint_candidate_id=mapping.endpoint_candidate_id,
                randomization_candidate_id=mapping.randomization_candidate_id,
                experimental_arm_candidate_id=mapping.experimental_arm_candidate_id,
                comparator_arm_candidate_id=mapping.comparator_arm_candidate_id,
                result=mapping.result,
                estimate=mapping.estimate,
                provenance_note=mapping.provenance_note,
                source_provenance=mapping.source_provenance,
                mapping_reviewed_by=mapping.reviewed_by,
            )
        candidates = list(candidates_by_id.values())
        limitations = tuple(
            item
            for item in proposal.limitations
            if item.kind is not ProposalLimitationKind.RESULT_MAPPING_INCOMPLETE
        )
        if any(
            item.mapping_status is not ProposalMappingStatus.ACCEPTED
            or item.identity_completeness is not ResultIdentityCompleteness.RESULT_COMPLETE
            for item in candidates
        ):
            limitations += (
                ProposalLimitation(
                    kind=ProposalLimitationKind.RESULT_MAPPING_INCOMPLETE,
                    scope=request.run_id,
                    # A promoted but incomplete mapping is deliberately
                    # routed to the existing structured Result-resolution
                    # checkpoint after the human selects its Result identity.
                    # It is visible in the proposal but not a reason to
                    # suppress that durable correction path.
                    material=False,
                    detail="One or more reviewed Result mappings remain structurally incomplete.",
                    recovery_actions=("Complete the issued Result mapping review.",),
                    candidate_ids=tuple(
                        item.candidate_id
                        for item in candidates
                        if item.mapping_status is not ProposalMappingStatus.ACCEPTED
                        or item.identity_completeness
                        is not ResultIdentityCompleteness.RESULT_COMPLETE
                    ),
                ),
            )
        now = self._now()
        # A complete mapping is still an unconfirmed candidate Run meaning.
        # ResultSpec revisions are only materialized atomically with human
        # confirmation, never while an agent is revising a proposal.
        result_specs = list(proposal.initialization.result_specs)
        initialization = proposal.initialization.model_copy(
            update={"result_specs": tuple(result_specs), "result_candidates": tuple(candidates)}
        )
        result_ids = list(proposal.result_ids)
        for candidate in candidates:
            if candidate.result_id is not None and candidate.result_id not in result_ids:
                result_ids.append(candidate.result_id)
        successor = proposal.model_copy(
            update={
                "initialization": initialization,
                "result_ids": tuple(result_ids),
                "result_candidates": tuple(candidates),
                "limitations": limitations,
                "supersedes_proposal_id": proposal.proposal_id,
            }
        )
        successor = successor.model_copy(
            update={"semantic_diff": semantic_diff(proposal, successor)}
        )
        successor = self._freeze_submitted_proposal(successor)
        transition = self._transition(
            scope=request.run_id,
            operation="operation:run-result-mapping-reviewed",
            operation_key=f"{request.idempotency_key}:proposal",
            entity_id=f"run-result-mapping:{self._digest(request.idempotency_key)}",
            revision_id=f"revision:run-result-mapping-{self._digest(request.idempotency_key)}",
            artifact=_ProposalSubmittedRecord(run_id=request.run_id, proposal=successor),
            checkpoint="checkpoint:run-result-mapping-reviewed",
            outcome=WorkflowEventOutcome.WORK_REQUIRED,
            observed_at=now,
        )
        submission_transition = self._submission_transition(
            run_id=request.run_id,
            scope=request.run_id,
            operation="operation:submit-result-mapping-review",
            operation_key=request.idempotency_key,
            artifact=request,
            checkpoint="checkpoint:result-mapping-review",
            observed_at=now,
        )
        self._validate_idempotent_event(
            ledger,
            request.idempotency_key,
            submission_transition.operation,
            request,
            run_id=request.run_id,
        )
        committed = self._commit_transitions(
            ledger,
            (submission_transition, transition),
            self._acquire_lease(ledger, now),
            now=now,
        )
        result = committed[0]
        return SubmitResultMappingReviewResponse(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(request.run_id,),
            condition=WorkflowCondition.ACCEPTED,
            committed=True,
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=self._projection(ledger, request.run_id).run_state,
            proposal=successor,
        )

    def _apply_proposal_promotions(
        self, proposal: RunProposal, batch: ProposalPromotionBatchInput
    ) -> RunProposal:
        """Bind human-approved design observations to engine-issued stable IDs."""

        randomizations = {
            item.candidate_id: item for item in proposal.reported_randomization_candidates
        }
        arms = {item.candidate_id: item for item in proposal.reported_arm_candidates}
        randomization_bindings = dict(proposal.randomization_bindings)
        arm_bindings = dict(proposal.arm_bindings)
        endpoints = {item.candidate_id: item for item in proposal.reported_endpoint_candidates}
        endpoint_ids = set(endpoints)
        dispositions = {
            disposition.candidate_id: disposition.disposition
            for receipt in proposal.proposal_discovery_receipts
            for disposition in receipt.candidate_dispositions
        }
        for promotion in batch.outcome_targets:
            if not set(promotion.endpoint_candidate_ids) <= endpoint_ids:
                raise ValueError(
                    "Outcome target promotion requires issued endpoint provenance seeds"
                )
            if any(
                dispositions.get(candidate_id) != "accepted"
                for candidate_id in promotion.endpoint_candidate_ids
            ):
                raise ValueError(
                    "Outcome target promotion requires accepted endpoint provenance seeds"
                )
        for promotion in batch.randomizations:
            randomization = randomizations.get(promotion.randomization_candidate_id)
            if randomization is None:
                raise ValueError("human promotion references an unissued reported Randomization")
            if dispositions.get(randomization.candidate_id) != "accepted":
                raise ValueError("human promotion requires accepted reported Randomization")
            if set(promotion.arm_candidate_ids) != set(randomization.arm_candidate_ids):
                raise ValueError(
                    "Randomization promotion must atomically promote its complete Arm set"
                )
            randomization_id = randomization_bindings.get(randomization.candidate_id)
            if randomization_id is None:
                randomization_id = f"randomization:{self._digest(f'{proposal.run_id}|{randomization.candidate_id}')}"
                randomization_bindings[randomization.candidate_id] = randomization_id
            for arm_candidate_id in randomization.arm_candidate_ids:
                arm = arms.get(arm_candidate_id)
                if arm is None or arm.randomization_candidate_id != randomization.candidate_id:
                    raise ValueError("promoted Arm must belong to its promoted Randomization")
                if dispositions.get(arm.candidate_id) != "accepted":
                    raise ValueError("human promotion requires accepted reported Arms")
                arm_bindings.setdefault(
                    arm_candidate_id,
                    f"arm:{self._digest(f'{proposal.run_id}|{randomization.candidate_id}|{arm_candidate_id}')}",
                )
        for promotion in batch.outcome_targets:
            for endpoint_candidate_id in promotion.endpoint_candidate_ids:
                endpoint = endpoints[endpoint_candidate_id]
                design_candidate_ids = (
                    endpoint.randomization_candidate_id,
                    endpoint.experimental_arm_candidate_id,
                    endpoint.comparator_arm_candidate_id,
                )
                if any(item is None for item in design_candidate_ids):
                    if promotion.admissibility_rule == "design_undiscovered" and not randomizations:
                        continue
                    raise ValueError(
                        "Outcome target promotion requires an accepted promoted Randomization and ordered Arms"
                    )
                randomization_candidate_id, experimental_arm_id, comparator_arm_id = (
                    cast(Identifier, item) for item in design_candidate_ids
                )
                if (
                    randomization_candidate_id not in randomization_bindings
                    or experimental_arm_id not in arm_bindings
                    or comparator_arm_id not in arm_bindings
                ):
                    if promotion.admissibility_rule == "design_undiscovered" and not randomizations:
                        continue
                    raise ValueError(
                        "Outcome target promotion must atomically include its accepted Randomization and ordered Arms"
                    )
        targets = list(proposal.initialization.manifest.outcome_target_specs)
        known_targets = {target.target_id: target for target in targets}
        for promotion in batch.outcome_targets:
            existing_target = known_targets.get(promotion.target.target_id)
            if existing_target is None:
                targets.append(promotion.target)
                known_targets[promotion.target.target_id] = promotion.target
            elif existing_target != promotion.target:
                raise ValueError(
                    "Outcome target promotion conflicts with the issued target meaning"
                )
        manifest = proposal.initialization.manifest.model_copy(
            update={
                "outcome_target_specs": tuple(targets),
                "outcome_targets": tuple(target.target_id for target in targets),
            }
        )
        initialization = proposal.initialization.model_copy(update={"manifest": manifest})
        limitations = (
            tuple(
                limitation
                for limitation in proposal.limitations
                if limitation.kind is not ProposalLimitationKind.NO_OUTCOME_TARGETS
            )
            if targets
            else proposal.limitations
        )
        design_recovery_identities = {
            (
                endpoints[endpoint_candidate_id].provenance.source_id,
                endpoints[endpoint_candidate_id].provenance.artifact_hash,
                endpoints[endpoint_candidate_id].provenance.parse_id,
            )
            for promotion in batch.outcome_targets
            if promotion.admissibility_rule == "design_undiscovered"
            for endpoint_candidate_id in promotion.endpoint_candidate_ids
        }
        if design_recovery_identities:
            limitations = tuple(
                limitation
                for limitation in limitations
                if not (
                    limitation.kind is ProposalLimitationKind.DISCOVERY_LIMITED
                    and limitation.detail
                    == "Reported Trial design remains undiscovered for a promoted endpoint."
                )
            ) + tuple(
                ProposalLimitation(
                    kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                    scope=source_id,
                    material=True,
                    detail="Reported Trial design remains undiscovered for a promoted endpoint.",
                    recovery_actions=(
                        "Complete the issued corrective discovery review for Trial design.",
                    ),
                    source_id=source_id,
                    source_artifact_hash=artifact_hash,
                    parse_id=parse_id,
                )
                for source_id, artifact_hash, parse_id in sorted(design_recovery_identities)
            )
        promotion_batches = proposal.promotion_batches
        if batch not in promotion_batches:
            promotion_batches = (*promotion_batches, batch)
        return proposal.model_copy(
            update={
                "initialization": initialization,
                "randomization_bindings": tuple(sorted(randomization_bindings.items())),
                "arm_bindings": tuple(sorted(arm_bindings.items())),
                "promotion_batches": promotion_batches,
                "limitations": limitations,
            }
        )

    @staticmethod
    def _proposal_contains_promotions(
        proposal: RunProposal, promotions: ProposalPromotionBatchInput
    ) -> bool:
        """Check replay identity against the attributable durable promotion batch."""

        return promotions in proposal.promotion_batches

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
                next_action=RunOperation.CONTINUE_RUN,
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
            next_action=RunOperation.CONTINUE_RUN,
            run_id=request.run_id,
            run_state=projection.run_state,
            result_id=request.result.result_id,
            result_state=self._result_state(projection, request.result.result_id),
            result_spec=result_spec,
        )

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

    def _verify_project_ownership(self, root: Path) -> None:
        """Verify this project's recorded release identity still matches what's installed.

        Runs lazily once ``project_root`` is known: the MCP server has no
        fixed project root at process startup, so this cannot happen any
        earlier than the first ``prepare_run``/``continue_run`` call. It is
        deliberately narrower than the full harness ownership-manifest check
        (``rob2 doctor``): it verifies only the release-identity fingerprint a
        project's ownership manifest declares, not host-configuration wiring
        or owned generated files, which are Harness bootstrap concerns
        outside what running a Run needs to trust. A successful check is
        cached for this engine's lifetime (one project root per instance); a
        failed check is not cached, so a since-repaired install is recognized
        on the next call rather than staying blocked for the process lifetime.
        """

        if self._ownership_verified:
            return
        manifest_path = root / "rob2.lock"
        if not manifest_path.is_file():
            # Unbootstrapped or source-checkout dev usage: nothing recorded
            # to verify the installed release against.
            self._ownership_verified = True
            return
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("project ownership manifest is not an object")
            installed_root = release_root()
            lock = load_release_lock(installed_root)
            verify_ownership_identities(raw, installed_root, lock)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RunIntegrityFailure(str(error)) from error
        self._ownership_verified = True

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
        proposal: RunProposal | None,
        selections: tuple[RunProposalSelection, ...],
        *,
        authorized: bool,
    ) -> RunProposal:
        """Fetch and durably project provenance for accepted registry candidates.

        Registry acquisition is an external capability, so it is only invoked
        during an explicitly authorized submit_run_proposal call. This method
        reads the caller's own ``authorized`` argument directly rather than
        any cross-call engine state, so acquisition cannot be triggered merely
        by resuming a previously authorized project on a later, unauthorized
        call. The immutable proposal carries the complete acquisition,
        source, and receipt projection; later assessment calls only read
        that projection.
        """

        accepted_ids = {
            selection.registry_candidate_id
            for selection in selections
            if selection.accepted and selection.registry_candidate_id is not None
        }
        if not accepted_ids:
            return proposal
        if not authorized:
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

        if self._lease_acquirer is not None:
            return self._lease_acquirer(ledger, now)
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

    @staticmethod
    def _normalize_parser_label(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
        return normalized or None

    @classmethod
    def _canonical_kind(
        cls, value: str | None, *, text: str = "", markdown: str = ""
    ) -> CanonicalUnitKind | None:
        normalized = cls._normalize_parser_label(value)
        aliases = {
            "text": CanonicalUnitKind.PARAGRAPH,
            "body": CanonicalUnitKind.PARAGRAPH,
            "list": CanonicalUnitKind.LIST_ITEM,
            "table": CanonicalUnitKind.TABLE_ROW,
            "table_cell": CanonicalUnitKind.TABLE_ROW,
            "table_row": CanonicalUnitKind.TABLE_ROW,
        }
        if normalized is not None:
            if normalized in aliases:
                return aliases[normalized]
            try:
                return CanonicalUnitKind(normalized)
            except ValueError:
                # An explicit parser label that is not in the closed enum is
                # unclassified; heuristics are reserved for absent labels.
                return None
        stripped = text.strip()
        if re.match(r"^(?:[-*•]|\d+[.)])\s+", stripped):
            return CanonicalUnitKind.LIST_ITEM
        if re.match(r"^(?:figure|fig\.?|table)\s+\d+", stripped, re.IGNORECASE):
            return CanonicalUnitKind.CAPTION
        if "|" in stripped and len(stripped.split("|")) >= 2:
            return CanonicalUnitKind.TABLE_ROW
        if re.match(r"^\s*\d+\s+", stripped) and len(stripped.split()) > 3:
            return CanonicalUnitKind.FOOTNOTE
        markdown_heading = any(
            line.lstrip().startswith("#") and line.lstrip("# ").strip() == stripped
            for line in markdown.splitlines()
        )
        if markdown_heading or (len(stripped.split()) <= 12 and stripped.endswith(":")):
            return CanonicalUnitKind.HEADING
        return None

    @classmethod
    def _canonical_zone(
        cls,
        value: str | None,
        *,
        page_text: str,
        structured: bool = False,
    ) -> DocumentZone:
        normalized = cls._normalize_parser_label(value)
        if normalized is not None:
            try:
                return DocumentZone(normalized)
            except ValueError:
                pass
        # Only an explicit heading is safe to infer from source text.  A
        # substring in ordinary prose (for example, "references previous
        # work") must remain UNKNOWN rather than hiding authored evidence.
        heading = next((line.strip() for line in page_text.splitlines() if line.strip()), "")
        heading = re.sub(r"^#{1,6}\s*", "", heading).rstrip(":").strip()
        if re.match(r"^(references|bibliography)\s*[:\-]?\s*$", heading, re.IGNORECASE):
            return DocumentZone.BIBLIOGRAPHY
        if re.match(r"^(contents|table\s+of\s+contents)\s*[:\-]?\s*$", heading, re.IGNORECASE):
            return DocumentZone.CONTENTS
        safe_heading_zones = {
            "introduction": DocumentZone.INTRODUCTION,
            "background": DocumentZone.INTRODUCTION,
            "methods": DocumentZone.METHODS,
            "materials and methods": DocumentZone.METHODS,
            "results": DocumentZone.RESULTS,
            "discussion": DocumentZone.DISCUSSION,
        }
        if (safe_zone := safe_heading_zones.get(heading.casefold())) is not None:
            return safe_zone
        if structured:
            # A parser-provided spatial block stream with no special heading
            # is a safe layout signal for ordinary body text.
            return DocumentZone.MAIN
        return DocumentZone.UNKNOWN

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
                pages_list: list[CanonicalPage] = []
                page_parse_ids: dict[int, Identifier | None] = {}
                reading_order_cursor = 0
                inherited_zone: DocumentZone | None = None
                for page in indexed_pages:
                    structure_metadata = page.structure_tree or {}
                    structure_zone = structure_metadata.get("document_zone")
                    if not isinstance(structure_zone, str):
                        structure_zone = None
                    parser_has_semantics = any(
                        item.unit_kind
                        or item.document_zone
                        or item.section_path
                        or item.hierarchy_path
                        for item in page.text_items
                    )
                    page_zone = self._canonical_zone(
                        page.document_zone or structure_zone,
                        page_text=page.text,
                        structured=bool(page.text_items)
                        and (getattr(parser, "name", "") != "liteparse" or parser_has_semantics),
                    )
                    if page_zone is DocumentZone.UNKNOWN and inherited_zone is not None:
                        page_zone = inherited_zone
                    elif page_zone is not DocumentZone.UNKNOWN:
                        # Carry explicit forbidden zones (bibliography/contents)
                        # across continuation pages too. A new explicit zone or
                        # safe heading replaces the inherited boundary.
                        inherited_zone = page_zone
                    page_zone_unknown = page_zone is DocumentZone.UNKNOWN
                    markdown_lines = [
                        line.strip() for line in page.markdown.splitlines() if line.strip()
                    ]
                    markdown_tables: list[tuple[tuple[str, ...], str | None, tuple[str, ...]]] = []
                    for line_number, line in enumerate(markdown_lines):
                        if (
                            "|" in line
                            and line_number + 1 < len(markdown_lines)
                            and re.match(r"^\s*\|?\s*:?-{3,}", markdown_lines[line_number + 1])
                        ):
                            table_headers = tuple(
                                cell.strip() for cell in line.strip("|").split("|") if cell.strip()
                            )
                            table_caption: str | None = None
                            if line_number:
                                candidate_caption = markdown_lines[line_number - 1]
                                if re.match(r"^(?:table|tbl\.)\s+\d+", candidate_caption, re.I):
                                    table_caption = candidate_caption
                            table_rows: list[str] = []
                            row_number = line_number
                            while (
                                row_number < len(markdown_lines)
                                and "|" in markdown_lines[row_number]
                            ):
                                table_rows.append(
                                    " ".join(markdown_lines[row_number].strip("|").split())
                                )
                                row_number += 1
                            markdown_tables.append(
                                (table_headers, table_caption, tuple(table_rows))
                            )
                    section_labels: list[tuple[int, str, int]] = []
                    heading_counts: dict[int, int] = {}
                    blocks: list[CanonicalBlock] = []
                    for number, text_item in enumerate(page.text_items, start=1):
                        if not text_item.text.strip():
                            continue
                        kind = self._canonical_kind(
                            text_item.unit_kind,
                            text=text_item.text,
                            markdown=page.markdown,
                        )
                        if (
                            kind is None
                            and getattr(parser, "name", "") == "liteparse"
                            and (
                                len(page.text_items) > 1
                                or any(
                                    text_item.text.strip() == line.lstrip("# ").strip()
                                    for line in markdown_lines
                                )
                            )
                        ):
                            # LiteParse text items carry geometry but may omit
                            # semantic kinds.  A markdown/text-item boundary
                            # is sufficient to call this authored prose; when
                            # absent we retain UNCLASSIFIED + visual limitation.
                            kind = CanonicalUnitKind.PARAGRAPH
                        heading_match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", text_item.text)
                        if kind is CanonicalUnitKind.HEADING:
                            heading_level = len(heading_match.group(1)) if heading_match else 1
                            while section_labels and section_labels[-1][0] >= heading_level:
                                section_labels.pop()
                            heading_counts[heading_level] = heading_counts.get(heading_level, 0) + 1
                            for level in tuple(heading_counts):
                                if level > heading_level:
                                    heading_counts.pop(level, None)
                            section_labels.append(
                                (
                                    heading_level,
                                    (
                                        heading_match.group(2) if heading_match else text_item.text
                                    ).strip(),
                                    heading_counts[heading_level],
                                )
                            )
                        inferred_section_path = tuple(label for _, label, _ in section_labels)
                        inferred_hierarchy_path = tuple(
                            str(index) for _, _, index in section_labels
                        )
                        table_headers = text_item.table_headers
                        caption = text_item.caption
                        if kind is CanonicalUnitKind.TABLE_ROW or "|" in text_item.text:
                            if not table_headers and not caption:
                                row_match = next(
                                    (
                                        (headers, table_caption)
                                        for headers, table_caption, table_rows in markdown_tables
                                        if " ".join(text_item.text.strip("|").split()) in table_rows
                                    ),
                                    None,
                                )
                                if row_match is not None:
                                    table_headers, caption = row_match
                        block_zone = (
                            page_zone
                            if text_item.document_zone is None
                            else self._canonical_zone(
                                text_item.document_zone,
                                page_text=text_item.text,
                            )
                        )
                        warnings = tuple(
                            warning
                            for warning, condition in (
                                ("canonical_kind_unclassified", kind is None),
                                (
                                    "document_zone_unclassified",
                                    page_zone_unknown or block_zone is DocumentZone.UNKNOWN,
                                ),
                            )
                            if condition
                        )
                        reading_order = text_item.reading_order or reading_order_cursor + 1
                        reading_order = max(reading_order, reading_order_cursor + 1)
                        reading_order_cursor = reading_order
                        fragment_id = getattr(text_item, "fragment_id", None)
                        blocks.append(
                            CanonicalBlock(
                                kind=kind or CanonicalUnitKind.UNCLASSIFIED,
                                text=text_item.text,
                                spatial=(
                                    text_item.x,
                                    text_item.y,
                                    text_item.x + text_item.width,
                                    text_item.y + text_item.height,
                                ),
                                word_boxes=_canonical_word_boxes(
                                    text_item.text,
                                    text_item.words,
                                ),
                                table_headers=table_headers,
                                caption=caption,
                                section_path=(
                                    text_item.section_path
                                    or page.section_path
                                    or inferred_section_path
                                ),
                                hierarchy_path=(
                                    text_item.hierarchy_path
                                    or page.hierarchy_path
                                    or inferred_hierarchy_path
                                ),
                                reading_order=reading_order,
                                fragment_ids=(fragment_id,) if isinstance(fragment_id, str) else (),
                                source_role=(source.roles[0].value if source.roles else None),
                                document_zone=block_zone,
                                warnings=warnings,
                            )
                        )
                    if not blocks and page.text.strip():
                        reading_order_cursor += 1
                        fallback_warnings = (
                            (
                                "canonical_structure_unavailable",
                                "document_zone_unclassified",
                            )
                            if page_zone_unknown or page_zone is DocumentZone.UNKNOWN
                            else ("canonical_structure_unavailable",)
                        )
                        blocks.append(
                            CanonicalBlock(
                                # The parser supplied page text but no unit
                                # boundaries or kind label; retain it as an
                                # explicit unclassified unit rather than
                                # inventing a paragraph classification.
                                kind=CanonicalUnitKind.UNCLASSIFIED,
                                text=page.text,
                                spatial=(0.0, 0.0, page.width, page.height),
                                section_path=page.section_path,
                                hierarchy_path=page.hierarchy_path,
                                reading_order=reading_order_cursor,
                                source_role=(source.roles[0].value if source.roles else None),
                                document_zone=page_zone,
                                warnings=fallback_warnings,
                            )
                        )
                    if blocks:
                        page_parse_ids[page.page_number] = page.parse_id
                        pages_list.append(
                            CanonicalPage(
                                page=page.page_number,
                                blocks=tuple(blocks),
                            )
                        )
                pages = tuple(pages_list)
                canonical_units = tuple(
                    unit
                    for page in pages
                    for unit in canonicalize_evidence_units(
                        source_id=source.source_id,
                        source_artifact_hash=source.artifact_hash,
                        parse_id=(
                            page_parse_ids.get(page.page) or source.parse_records[0].parse_id
                        ),
                        pages=(page,),
                    )
                )
                units.extend(
                    item.model_copy(
                        update={
                            "source_role": (source.roles[0] if source.roles else None),
                        }
                    )
                    for item in canonical_units
                )
        duplicate_keys: dict[str, list[int]] = {}
        for index, item in enumerate(units):
            key = canonical_hash(
                {
                    "source_artifact_hash": item.source_artifact_hash,
                    "kind": item.kind.value,
                    "text": " ".join(item.text.split()),
                    "document_zone": item.document_zone.value if item.document_zone else None,
                    "table_headers": item.table_headers,
                    "caption": item.caption,
                    "section_path": item.section_path,
                    "hierarchy_path": item.hierarchy_path,
                }
            )
            duplicate_keys.setdefault(key, []).append(index)
        for key, indexes in duplicate_keys.items():
            if len(indexes) < 2:
                continue
            duplicate_group_id = f"duplicate:{key.removeprefix('sha256:')}"
            for index in indexes:
                if units[index].duplicate_group_id is None:
                    units[index] = units[index].model_copy(
                        update={"duplicate_group_id": duplicate_group_id}
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
        reports: list[tuple[_ReportMaterializedRecord | _ResultDiagnosticRecord, Path]] = []
        for event in events:
            if event.operation not in {
                "operation:result-report-ready",
                "operation:result-diagnostic-ready",
            }:
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
            corrected_at = max(
                (
                    prior.sequence
                    for prior in events
                    if prior.operation == "operation:correct-question-step"
                    and prior.scope == event.scope
                ),
                default=0,
            )
            if event.sequence <= max(invalidated_at, corrected_at):
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
            if record.report_root is not None:
                reports.append((record, self._required_root() / record.report_root))
        if not reports:
            # A reconciliation may invalidate the only terminal Result and
            # leave it pending/assessing.  Refresh the index even when there
            # is no visible bundle to repair so stale report links disappear
            # while immutable historical files remain untouched.
            self._regenerate_run_index(ledger, run_id)
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
                try:
                    os.replace(staging, report_root)
                except OSError:
                    # Keep the committed write-ahead record and hidden stage
                    # for a later status/resume repair; never expose a partial
                    # terminal bundle when publication itself is interrupted.
                    continue
        self._regenerate_run_index(ledger, run_id)
        self._commit_run_completed_if_ready(ledger, run_id, lease=lease)

    def _resume_assessment_ready_reports(self, ledger: WorkflowLedger, run_id: Identifier) -> None:
        """Retry only deterministic report materialization after a rendering interruption."""

        projection = self._projection(ledger, run_id)
        if projection.run_state is not RunState.ASSESSING:
            return
        for result in projection.results:
            if result.state is ResultState.ASSESSMENT_READY:
                record = self._assessment_ready_record(ledger, run_id, result.result_id)
                if record is None:
                    raise RunIntegrityFailure(
                        "assessment-ready Result is missing its materialization checkpoint"
                    )
                self._materialize_assessment_report(ledger, record)
        self._repair_report_publication(ledger, run_id)

    def _assessment_ready_record(
        self, ledger: WorkflowLedger, run_id: Identifier, result_id: Identifier
    ) -> _ResultAssessmentReadyRecord | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.scope != result_id or event.operation != "operation:result-assessment-ready":
                continue
            return _ResultAssessmentReadyRecord.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            )
        return None

    def _materialize_assessment_report(
        self, ledger: WorkflowLedger, ready: _ResultAssessmentReadyRecord
    ) -> None:
        """Render one frozen Assessment checkpoint without re-evaluating scientific work."""

        try:
            citations, visual_assets = self._materialize_visual_assets(
                ledger, ready.run_id, ready.result_id, ready.assessment.visual_citations
            )
        except VisualAssetMaterializationError:
            # Rendering is an operational report concern.  Keep the durable
            # Assessment-ready checkpoint and let the next continuation retry
            # this method without re-evaluating answers or judgments.
            return
        citations_by_id = {citation.citation_id: citation for citation in citations}
        assessment = ready.assessment.model_copy(
            update={
                "visual_citations": citations,
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
                    for domain in ready.assessment.domains
                ),
            }
        )
        digest = ready.assessment_revision_id.removeprefix("assessment:")
        report_root = (
            self._required_root()
            / "output"
            / "report-bundle"
            / "runs"
            / self._report_path_component(ready.run_id)
            / "trials"
            / self._report_path_component(assessment.trial)
            / "results"
            / self._report_path_component(ready.result_id)
        )
        if report_root.exists():
            report_root = report_root / self._report_path_component(ready.assessment_revision_id)
        if report_root.exists():
            raise ValueError("the immutable report bundle already exists")
        staging = report_root.parent / f".report-bundle-staging-{digest}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            report_files = self._report_projector_factory(assessment).bundle_files()
        except (OSError, ValueError):
            # The assessment checkpoint is durable.  Leave it assessment-ready
            # so a later engine continuation can retry report publication.
            return
        report_files.update(visual_assets)
        report_files["answers.json"] = (
            json.dumps(
                {
                    "answers": ready.answers,
                    "rationales": ready.rationales,
                    "active_question_ids": ready.active_question_ids,
                    "inactive_question_ids": ready.inactive_question_ids,
                    "matched_rule_ids": ready.matched_rule_ids,
                    "assessor_inputs": ready.assessor_inputs,
                    "judgment_references": [
                        reference.model_dump(mode="json") for reference in ready.judgment_references
                    ],
                    "final_judgment_references": [
                        reference.model_dump(mode="json")
                        for reference in ready.final_judgment_references
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        archive = ArchiveBuilder(ledger).build(
            ready.assessment_revision_id,
            pinned_files=self._verification_pins(),
        )
        receipt = verify_archive(archive)
        if receipt.assessment_revision_id != ready.assessment_revision_id:
            raise ValueError("Verification archive identity does not match report")
        report_files["verification-archive.rob2.zip"] = archive
        domain_judgments = {
            domain.domain_id: JudgmentLevel(domain.judgment) for domain in assessment.domains
        }
        report_files["manifest.json"] = (
            json.dumps(
                {
                    "assessment_revision_id": ready.assessment_revision_id,
                    "result_id": ready.result_id,
                    "overall_judgment": assessment.overall_judgment,
                    "domains": domain_judgments,
                    "files": {
                        name: "sha256:" + hashlib.sha256(content).hexdigest()
                        for name, content in report_files.items()
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        for name, content in report_files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self._verify_staged_report_files(staging, report_files)
        now = self._now()
        report = _ReportMaterializedRecord(
            run_id=ready.run_id,
            result_id=ready.result_id,
            assessment_revision_id=ready.assessment_revision_id,
            overall_judgment=JudgmentLevel(assessment.overall_judgment),
            domain_judgments=domain_judgments,
            report_root=report_root.relative_to(self._required_root()).as_posix(),
            artifact_names=tuple(sorted(report_files)),
            staging_root=staging.relative_to(self._required_root()).as_posix(),
        )
        self._commit_transitions(
            ledger,
            (
                self._transition(
                    scope=ready.result_id,
                    operation="operation:result-report-ready",
                    operation_key=f"idempotency:result-report-ready-{digest}",
                    entity_id=f"report:{digest}",
                    revision_id=f"revision:report-{digest}",
                    artifact=report,
                    checkpoint="checkpoint:report-ready",
                    outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
                    observed_at=now,
                ),
            ),
            self._acquire_lease(ledger, now),
            now=now,
        )
        self._repair_report_publication(ledger, ready.run_id)

    def _commit_transitions(
        self,
        ledger: WorkflowLedger,
        transitions: tuple[Transition, ...],
        lease: LeaseToken,
        *,
        now: datetime,
    ) -> tuple[CommitResult, ...]:
        """Publish terminal bundles before recording their readiness events.

        A report transition carries a verified hidden stage in its immutable
        artifact.  The stage is atomically renamed into its final location
        before the ledger commit.  If the commit fails, each visible directory
        is atomically moved back to its hidden stage, leaving a stable retry
        point and, importantly, no orphan visible bundle without a readiness
        event.
        """

        published: list[tuple[Path, Path]] = []
        try:
            for transition in transitions:
                if transition.operation not in {
                    "operation:result-report-ready",
                    "operation:result-diagnostic-ready",
                }:
                    continue
                try:
                    payload = json.loads(transition.artifact)
                    report_root = payload.get("report_root")
                    staging_root = payload.get("staging_root")
                except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(report_root, str) or not isinstance(staging_root, str):
                    continue
                root = self._required_root()
                visible = root / report_root
                staging = root / staging_root
                if visible.exists():
                    continue
                if not staging.is_dir():
                    raise OSError(f"staged report bundle is missing: {staging}")
                visible.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, visible)
                published.append((visible, staging))
            committed = ledger.commit_batch(transitions, lease, now=now)
        except Exception:
            for visible, staging in reversed(published):
                try:
                    if visible.exists() and not staging.exists():
                        os.replace(visible, staging)
                    elif visible.exists():
                        shutil.rmtree(visible)
                except OSError:
                    # The original visible path is never retained merely
                    # because rollback encountered a second filesystem error.
                    try:
                        if visible.is_dir():
                            shutil.rmtree(visible)
                    except OSError:
                        pass
            raise
        return committed

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
            corrected_at = max(
                (
                    event.sequence
                    for event in events
                    if event.operation == "operation:correct-question-step"
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
                    and event.sequence > max(invalidated_at, corrected_at)
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

    def _commit_assessment_ready_checkpoint(
        self,
        ledger: WorkflowLedger,
        *,
        run_id: Identifier,
        result_id: Identifier,
        assessment_digest: str,
        assessment_record: AssessmentRevision,
        assessment: AssessmentView,
        answers: dict[str, str],
        rationales: dict[str, str],
        evaluation: Any,
        judgment_references: tuple[RecordReference, ...],
        final_judgment_references: tuple[RecordReference, ...],
    ) -> None:
        """Commit the scientific Assessment before attempting report rendering."""

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
        if assessment_ref.revision_id != assessment.assessment_revision_id:
            raise ValueError("frozen Assessment revision identity does not match report")
        assessment_state = self._result_state(self._projection(ledger, run_id), result_id)
        readiness_transitions: list[Transition] = []
        if assessment_state is ResultState.PENDING:
            readiness_transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:result-started",
                    operation_key=f"idempotency:result-started-{assessment_digest}",
                    entity_id=f"result-started:{assessment_digest}",
                    revision_id=f"revision:result-started-{assessment_digest}",
                    artifact=_ResultStartedRecord(run_id=run_id, result_id=result_id),
                    checkpoint="checkpoint:result-started",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=self._now(),
                )
            )
        if assessment_state in {ResultState.PENDING, ResultState.ASSESSING}:
            readiness_transitions.append(
                self._transition(
                    scope=result_id,
                    operation="operation:result-assessment-ready",
                    operation_key=f"idempotency:result-assessment-ready-{assessment_digest}",
                    entity_id=f"result-assessment:{assessment_digest}",
                    revision_id=f"revision:result-assessment-{assessment_digest}",
                    artifact=_ResultAssessmentReadyRecord(
                        run_id=run_id,
                        result_id=result_id,
                        assessment_revision_id=assessment.assessment_revision_id,
                        assessment=assessment,
                        answers=answers,
                        rationales=rationales,
                        active_question_ids=evaluation.active_question_ids,
                        inactive_question_ids=evaluation.inactive_question_ids,
                        matched_rule_ids=evaluation.matched_rule_ids,
                        assessor_inputs=evaluation.assessor_inputs,
                        judgment_references=judgment_references,
                        final_judgment_references=final_judgment_references,
                    ),
                    checkpoint="checkpoint:assessment-ready",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=self._now(),
                )
            )
        if readiness_transitions:
            now = self._now()
            self._commit_transitions(
                ledger,
                tuple(readiness_transitions),
                self._acquire_lease(ledger, now),
                now=now,
            )

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
        latest_correction = max(
            (
                event.sequence
                for event in events
                if event.operation == "operation:correct-question-step" and event.scope == result_id
            ),
            default=0,
        )
        if any(
            event.operation == "operation:result-report-ready"
            and event.scope == result_id
            and event.sequence > invalidated_at
            and event.sequence > latest_correction
            for event in events
        ):
            self._repair_report_publication(ledger, run_id)
            return ()
        if any(
            event.operation == "operation:result-diagnostic-ready"
            and event.scope == result_id
            and event.sequence > invalidated_at
            and event.sequence > latest_correction
            for event in events
        ):
            self._repair_report_publication(ledger, run_id)
            return ()
        # A question correction can make a previously absent dependent active.
        # Its former Domain checkpoint remains immutable audit history, but it
        # is not sufficient to recreate a terminal report while that session
        # is open for new evidence and an answer.
        for event in events:
            if (
                event.operation != "operation:correct-question-step"
                or event.scope != result_id
                or event.sequence < latest_correction
            ):
                continue
            try:
                corrected = _QuestionCorrectionRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                )
                session = self._question_session_service(
                    ledger, run_id, result_id, corrected.domain_id
                ).load()
            except (OSError, ValueError):
                raise RunIntegrityFailure(
                    "question correction receipt cannot be replayed"
                ) from None
            if active_question_frontier(session.ledger).status != "complete_with_answers":
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
        answer_payloads = self._current_domain_answer_payloads(
            ledger, run_id, result_id, invalidated_at
        )
        answer_domains = {payload.get("domain_id") for payload in answer_payloads}
        if not required_domains <= evidence_domains or not required_domains <= answer_domains:
            return ()
        coverage_by_domain: dict[str, tuple[str, tuple[str, ...]]] = {}
        incomplete_limitations: set[str] = set()
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
            coverage_state = str(payload.get("coverage_state", "complete"))
            if coverage_state == "incomplete" and not limitations:
                limitations = ("incomplete evidence coverage",)
            domain_id = payload.get("domain_id")
            if isinstance(domain_id, str):
                coverage_by_domain[domain_id] = (coverage_state, limitations)
            if coverage_state == "incomplete":
                incomplete_limitations.update(limitations)
        coverage_limitations = tuple(sorted(incomplete_limitations))
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
            self._commit_transitions(ledger, (transition,), lease, now=self._now())
            self._repair_report_publication(ledger, run_id)
            return ()
        # Each Domain contributes only its current immutable answer checkpoint.
        # A correction supersedes that Domain's earlier answers, assessor input,
        # and Final-judgment departure without discarding other Domains' work.
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
            raw_assessor_inputs = payload.get("assessor_inputs", {})
            if not isinstance(raw_assessor_inputs, dict):
                raise ValueError("assessor inputs must be a structured mapping")
            for input_id, value in raw_assessor_inputs.items():
                if not isinstance(input_id, str):
                    raise ValueError("assessor input IDs must be strings")
                if not isinstance(value, bool):
                    raise ValueError("assessor inputs must be boolean")
                if input_id in assessor_inputs and assessor_inputs[input_id] != value:
                    raise ValueError(f"conflicting assessor input supplied for {input_id}")
                assessor_inputs[input_id] = value
        evaluation = LogicEvaluator(logic).evaluate(
            EvaluationRequest(answers=answers, assessor_inputs=assessor_inputs)
        )
        # Every effective v3 answer is already bound to a reducer-closed,
        # engine-produced Evidence Bundle. The removed v2 candidate-level
        # insufficiency scan would duplicate that proof and no longer has an
        # active contract to evaluate.
        assessment_digest = self._digest(
            canonical_json_bytes(
                {
                    "run_id": run_id,
                    "result_id": result_id,
                    "answers": answers,
                    "rationales": rationales,
                    "assessor_inputs": assessor_inputs,
                    "final_judgment_departures": [
                        departure
                        for payload in answer_payloads
                        for departure in payload.get("final_judgment_departures", ())
                    ],
                    "invalidated_at": invalidated_at,
                }
            ).decode()
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
        final_judgment_references = self._materialize_final_judgment_revisions(
            ledger,
            result_id,
            logic=logic,
            evaluation=evaluation,
            judgment_references=judgment_references,
            evidence_references=evidence_refs,
            answer_payloads=answer_payloads,
            assessment_digest=assessment_digest,
        )
        final_judgments = tuple(
            FinalJudgmentRevision.model_validate_json(ledger.artifacts.read(reference.content_hash))
            for reference in final_judgment_references
        )
        final_by_domain = {judgment.domain_id: judgment for judgment in final_judgments}
        final_domain_judgments = {
            domain_id: judgment.judgment for domain_id, judgment in final_by_domain.items()
        }
        final_overall_rule = next(
            (
                rule
                for rule in logic.overall_rules
                if LogicEvaluator(logic)._matches(
                    rule.when, {}, final_domain_judgments, assessor_inputs
                )
            ),
            None,
        )
        if final_overall_rule is None:
            raise ValueError("no Overall policy rule matched Final Domain judgments")
        final_overall = final_overall_rule.judgment
        assessment_revision_id = f"assessment:{assessment_digest}"
        visual_citations = self._visual_citations(ledger, evidence_refs)
        questions_by_id = self._report_questions(
            ledger,
            evidence_refs,
            answers,
            rationales,
            evaluation.matched_rule_ids,
            visual_citations,
        )
        guidance = self._guidance_pack()
        guidance_by_id = {item.logic_element_id: item for item in guidance.items}
        questions_by_id = {
            question_id: question.model_copy(update={"wording": guidance_by_id[question_id].text})
            if question_id in guidance_by_id
            else question
            for question_id, question in questions_by_id.items()
        }
        result = result_spec.result
        estimate = EstimateView(
            value=str(result_spec.estimate.value),
            interval_lower=(
                str(result_spec.estimate.interval_lower)
                if result_spec.estimate.interval_lower is not None
                else None
            ),
            interval_upper=(
                str(result_spec.estimate.interval_upper)
                if result_spec.estimate.interval_upper is not None
                else None
            ),
            denominator_experimental=result_spec.estimate.denominator_experimental,
            denominator_comparator=result_spec.estimate.denominator_comparator,
        )
        result_identity = ResultIdentityView(
            result_id=result.result_id,
            trial_id=result.trial_id,
            comparison=(
                f"{result.comparison.experimental_arm_id} vs {result.comparison.comparator_arm_id}"
            ),
            effect_of_interest=result.effect_of_interest,
            outcome=result.outcome_construct,
            measurement_instrument=result.measurement_instrument,
            time_point=result.time_point,
            analysis_population=result.analysis_population,
            analysis_model=result.analysis_model,
            effect_measure=result.effect_measure,
            source_locator=result.source_locator,
        )
        overall_policy_id = f"{logic.family_id}:overall:{logic.release_id}"
        overall_policy_hash = logic.content_hash
        domain_labels = {
            "domain:randomization": "Bias arising from the randomization process",
            "domain:deviations": "Bias due to deviations from intended interventions",
            "domain:missing": "Bias due to missing outcome data",
            "domain:measurement": "Bias in measurement of the outcome",
            "domain:selection": "Bias in selection of the reported result",
        }
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
            measurement_instrument=result_spec.result.measurement_instrument,
            analysis_population=result_spec.result.analysis_population,
            analysis_model=result_spec.result.analysis_model,
            effect_measure=result_spec.result.effect_measure,
            source_locator=result_spec.result.source_locator,
            estimate=estimate,
            limitations=tuple(
                dict.fromkeys(
                    limitation
                    for _coverage, limitations in coverage_by_domain.values()
                    for limitation in limitations
                )
            ),
            result_identity=result_identity,
            result_details=ResultDetailsView(
                measurement_instrument=result_spec.result.measurement_instrument,
                analysis_population=result_spec.result.analysis_population,
                analysis_model=result_spec.result.analysis_model,
                effect_measure=result_spec.result.effect_measure,
                source_locator=result_spec.result.source_locator,
                estimate=estimate,
            ),
            overall_judgment=final_overall.value,
            domains=tuple(
                DomainView(
                    domain_id=domain.id,
                    label=domain_labels.get(domain.id, domain.id),
                    judgment=final_by_domain[domain.id].judgment.value,
                    algorithmic_judgment=evaluation.domain_judgments[domain.id].value,
                    rationale=(
                        final_by_domain[domain.id].material_bias_rationale
                        or "Deterministic Logic-pack evaluation; matched rules: "
                        + ", ".join(evaluation.matched_rule_ids)
                    ),
                    questions=tuple(
                        questions_by_id[question_id]
                        for question_id in domain.question_ids
                        if question_id in questions_by_id
                    ),
                    coverage=coverage_by_domain.get(domain.id, ("complete", ()))[0],
                    limitations=coverage_by_domain.get(domain.id, ("complete", ()))[1],
                    decision_trace=evaluation.matched_rule_ids,
                )
                for domain in logic.domains
            ),
            visual_citations=visual_citations,
            execution_contract=execution_contract,
            overall_policy_id=overall_policy_id,
            overall_policy_hash=overall_policy_hash,
            overall_policy_text=(
                "The versioned Logic pack evaluates Final Domain judgments, including its "
                "structured combined-concerns input when applicable."
            ),
            overall_decision_trace=(final_overall_rule.id,),
        )
        result_spec_ref = self._result_spec_reference(ledger, run_id, result_id)
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
                *(
                    Dependency(**reference.model_dump(), role="dependency:final-judgment")
                    for reference in final_judgment_references
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
            final_judgments=final_judgment_references,
            assessor_inputs=assessor_inputs,
        )
        try:
            visual_citations, visual_assets = self._materialize_visual_assets(
                ledger, run_id, result_id, assessment.visual_citations
            )
        except VisualAssetMaterializationError:
            # The Assessment itself is valid.  Persist its scientific
            # checkpoint and leave the Result assessment-ready so continuation
            # retries deterministic report rendering only.
            self._commit_assessment_ready_checkpoint(
                ledger,
                run_id=run_id,
                result_id=result_id,
                assessment_digest=assessment_digest,
                assessment_record=assessment_record,
                assessment=assessment,
                answers=answers,
                rationales=rationales,
                evaluation=evaluation,
                judgment_references=judgment_references,
                final_judgment_references=final_judgment_references,
            )
            self._repair_report_publication(ledger, run_id)
            return ()
        self._commit_assessment_ready_checkpoint(
            ledger,
            run_id=run_id,
            result_id=result_id,
            assessment_digest=assessment_digest,
            assessment_record=assessment_record,
            assessment=assessment,
            answers=answers,
            rationales=rationales,
            evaluation=evaluation,
            judgment_references=judgment_references,
            final_judgment_references=final_judgment_references,
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
        projector = self._report_projector_factory(assessment)
        lease = self._acquire_lease(ledger, self._now())
        report_base = self._required_root() / "output" / "report-bundle"
        # Keep every report under a deterministic manifest-rooted
        # run/trial/result hierarchy.  The identity path is stable across
        # process restarts and gives the Run index a direct, local link even
        # for the first terminal Result; assessment revisions remain immutable
        # within that Result directory when a superseding revision is needed.
        report_root = (
            report_base
            / "runs"
            / self._report_path_component(run_id)
            / "trials"
            / self._report_path_component(result.trial_id)
            / "results"
            / self._report_path_component(result_id)
        )
        if report_root.exists():
            report_root = report_root / self._report_path_component(assessment_revision_id)
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
                            "assessor_inputs": evaluation.assessor_inputs,
                            "judgment_references": [
                                reference.model_dump(mode="json")
                                for reference in judgment_references
                            ],
                            "final_judgment_references": [
                                reference.model_dump(mode="json")
                                for reference in final_judgment_references
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
            "overall_judgment": final_overall.value,
            "domains": final_domain_judgments,
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
            overall_judgment=final_overall,
            domain_judgments=final_domain_judgments,
            report_root=report_root.relative_to(self._required_root()).as_posix(),
            artifact_names=tuple(sorted(report_files)),
            staging_root=staging.relative_to(self._required_root()).as_posix(),
        )
        transitions = [
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
        self._commit_transitions(ledger, tuple(transitions), lease, now=now)
        # The readiness transition is committed only after publication.  A
        # failed commit is rolled back by ``_commit_transitions`` to the
        # hidden stage, ready for a deterministic retry.
        self._repair_report_publication(ledger, run_id)
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
        report_root = (
            root
            / "output"
            / "report-bundle"
            / "runs"
            / self._report_path_component(diagnostic.run_id)
            / "trials"
            / self._report_path_component(diagnostic.trial_id)
            / "results"
            / self._report_path_component(diagnostic.result_id)
            / "diagnostic"
        )
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
                preparation_outcome=diagnostic.preparation_outcome,
                recovery=diagnostic.recovery,
                limitations=(diagnostic.reason,),
            )
        )
        files = {
            "diagnostic.json": projector.json(),
            "diagnostic.md": (
                "# RoB 2 diagnostic report\n\n"
                f"- Result: {self._escape_markdown(diagnostic.result_id)}\n"
                f"- Trial: {self._escape_markdown(diagnostic.trial_id)}\n"
                "- Preparation outcome: "
                f"{self._escape_markdown(diagnostic.preparation_outcome.replace('_', ' '))}\n"
                f"- Limitation: {self._escape_markdown(diagnostic.reason)}\n"
                "\n## Recovery path\n\n"
                + "".join(f"- {self._escape_markdown(item)}\n" for item in diagnostic.recovery)
            ).encode(),
            "diagnostic.html": projector.html(),
        }
        files["manifest.json"] = (
            json.dumps(
                {
                    "result_id": diagnostic.result_id,
                    "trial_id": diagnostic.trial_id,
                    "preparation_outcome": diagnostic.preparation_outcome,
                    "recovery": list(diagnostic.recovery),
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
        self._verify_staged_report_files(staging, files)
        return diagnostic.model_copy(
            update={
                "report_root": report_root.relative_to(root).as_posix(),
                "artifact_names": tuple(sorted(files)),
                "staging_root": staging.relative_to(root).as_posix(),
            }
        )

    def _regenerate_run_index(self, ledger: WorkflowLedger, run_id: Identifier) -> None:
        """Publish a compact, ledger-derived Run index after terminal bundles change."""

        root = self._required_root()
        bundle_root = root / "output" / "report-bundle"
        if not bundle_root.exists():
            return
        run_root = bundle_root / "runs" / self._report_path_component(run_id)
        run_root.mkdir(parents=True, exist_ok=True)
        events = self._events_for_run(ledger, run_id)
        projection = self._projection(ledger, run_id)
        # The index is a projection of the *current* active Result set.  Old
        # report/diagnostic records remain immutable in the ledger and on disk,
        # but must not produce duplicate or stale rows after an invalidation.
        # Use the same Result projection as work-item derivation.  A Result
        # discovered after confirmation (the normal unresolved-candidate
        # path) is not part of the immutable ConfirmedRunDefinition.result_ids
        # tuple, but its committed ``result-discovered`` event makes it active
        # for this run.  Reading only ``_active_result_ids`` would therefore
        # publish an empty index even while the terminal bundle is visible.
        active_result_ids = set(
            self._result_ids(ledger, run_id, self._latest_proposal(ledger, run_id))
        )
        result_states = {item.result_id: item.state.value for item in projection.results}
        latest_invalidated: dict[str, int] = {}
        for event in events:
            if event.operation != "operation:result-invalidated" or not event.scope.startswith(
                "result:"
            ):
                continue
            latest_invalidated[event.scope] = max(
                latest_invalidated.get(event.scope, 0), event.sequence
            )

        terminal_events: dict[str, WorkflowEvent] = {}
        for event in events:
            if event.operation not in {
                "operation:result-report-ready",
                "operation:result-diagnostic-ready",
            }:
                continue
            result_id = event.scope
            if result_id not in active_result_ids:
                continue
            if event.sequence <= latest_invalidated.get(result_id, 0):
                continue
            prior = terminal_events.get(result_id)
            if prior is None or event.sequence > prior.sequence:
                terminal_events[result_id] = event

        entries: list[dict[str, Any]] = []
        ancillary_outputs: set[str] = set()
        # Exactly one row is emitted for each active Result.  A current
        # terminal event wins; otherwise retain the lifecycle's pending or
        # assessing projection with no report link.
        for result_id in sorted(active_result_ids):
            event = terminal_events.get(result_id)
            record: _ReportMaterializedRecord | _ResultDiagnosticRecord | None = None
            diagnostic = False
            if event is not None:
                diagnostic = event.operation == "operation:result-diagnostic-ready"
                try:
                    record = (
                        _ReportMaterializedRecord.model_validate_json(
                            ledger.artifacts.read(event.output_revision_hashes[0])
                        )
                        if not diagnostic
                        else _ResultDiagnosticRecord.model_validate_json(
                            ledger.artifacts.read(event.output_revision_hashes[0])
                        )
                    )
                except (IndexError, ValueError):
                    record = None

            # Invalid or unreadable terminal payloads are treated as a
            # non-linking lifecycle row rather than exposing a stale path.
            if record is None:
                diagnostic = False

            result_spec = self._result_spec_for(ledger, run_id, result_id)
            trial_id = result_spec.result.trial_id if result_spec is not None else ""
            if not trial_id and isinstance(record, _ResultDiagnosticRecord):
                # Generated diagnostics (for example a failed Trial with no
                # declared ResultSpec) still carry an authoritative Trial ID.
                trial_id = record.trial_id
            if not trial_id:
                trial_id = self._trial_id_for_result(result_id) or ""

            report_root = getattr(record, "report_root", None) if record is not None else None
            ancillary_outputs.update(getattr(record, "artifact_names", ()) if record else ())
            report_path = ""
            if report_root:
                report_directory = root / report_root
                if report_directory.is_dir():
                    try:
                        report_path = report_directory.relative_to(run_root).as_posix()
                    except ValueError:
                        report_path = ""
                    if report_path == ".":
                        report_path = ""

            state = (
                "diagnostic_ready"
                if diagnostic and record is not None
                else "report_ready"
                if not diagnostic and record is not None
                else result_states.get(result_id, "pending")
            )
            outcome = ""
            time_point = ""
            comparison = ""
            effect_measure = ""
            estimate_view: EstimateView | None = None
            evidence_count = 0
            overall_judgment = ""
            domain_judgments: dict[str, JudgmentLevel] = {}
            limitations: list[str] = []
            coverage = "not recorded"

            if result_spec is not None:
                outcome = result_spec.result.outcome_construct
                time_point = result_spec.result.time_point
                comparison = (
                    f"{result_spec.result.comparison.experimental_arm_id} vs "
                    f"{result_spec.result.comparison.comparator_arm_id}"
                )
                effect_measure = result_spec.result.effect_measure
                estimate_view = EstimateView(
                    value=str(result_spec.estimate.value),
                    interval_lower=(
                        str(result_spec.estimate.interval_lower)
                        if result_spec.estimate.interval_lower is not None
                        else None
                    ),
                    interval_upper=(
                        str(result_spec.estimate.interval_upper)
                        if result_spec.estimate.interval_upper is not None
                        else None
                    ),
                    denominator_experimental=result_spec.estimate.denominator_experimental,
                    denominator_comparator=result_spec.estimate.denominator_comparator,
                )

            if diagnostic and isinstance(record, _ResultDiagnosticRecord):
                limitations = [record.reason]
                coverage = "incomplete"
                # Diagnostic reports never inherit metadata from a prior
                # assessment report.  Only the current ResultSpec, when
                # present, contributes identity metadata above.
            elif isinstance(record, _ReportMaterializedRecord):
                overall_judgment = record.overall_judgment.value
                domain_judgments = record.domain_judgments
                coverage = "complete"
                if report_root and (root / report_root).is_dir():
                    try:
                        assessment_payload = json.loads(
                            (root / report_root / "assessment.json").read_text(encoding="utf-8")
                        )
                        outcome = str(assessment_payload.get("outcome", outcome))
                        time_point = str(assessment_payload.get("time_point", time_point))
                        comparison = str(assessment_payload.get("comparison", comparison))
                        effect_measure = str(
                            assessment_payload.get("effect_measure", effect_measure)
                        )
                        raw_estimate = assessment_payload.get("estimate")
                        if isinstance(raw_estimate, dict) and isinstance(
                            raw_estimate.get("value"), str
                        ):
                            estimate_view = EstimateView.model_validate(raw_estimate)
                        domains = assessment_payload.get("domains", ())
                        evidence_ids: set[str] = set()
                        for domain in domains:
                            if not isinstance(domain, dict):
                                continue
                            for question in domain.get("questions", ()):
                                if not isinstance(question, dict):
                                    continue
                                for evidence in question.get("evidence", ()):
                                    if isinstance(evidence, dict) and isinstance(
                                        evidence.get("evidence_id"), str
                                    ):
                                        evidence_ids.add(evidence["evidence_id"])
                        evidence_count = len(evidence_ids)
                        coverage_states = [item.get("coverage") for item in domains]
                        if "incomplete" in coverage_states:
                            coverage = "incomplete"
                        elif "complete_with_limitations" in coverage_states:
                            coverage = "complete_with_limitations"
                        limitations = [
                            limitation
                            for domain in domains
                            if isinstance(domain, dict)
                            for limitation in domain.get("limitations", ())
                        ]
                    except (OSError, ValueError, TypeError):
                        coverage = "not recorded"
            elif state in {"pending", "assessing"}:
                limitations = ["Result has no terminal report yet."]

            report = ""
            if report_path and state == "diagnostic_ready":
                report = f"{report_path}/diagnostic.html"
            elif report_path and state == "report_ready":
                report = f"{report_path}/assessment.html"
            entries.append(
                {
                    "result_id": result_id,
                    "trial_id": trial_id,
                    "state": state,
                    "report_root": report_path,
                    "report": report,
                    "overall_judgment": overall_judgment,
                    "domain_judgments": domain_judgments,
                    "outcome": outcome,
                    "time_point": time_point,
                    "comparison": comparison,
                    "effect_measure": effect_measure,
                    "estimate": estimate_view,
                    "evidence_count": evidence_count,
                    "limitations": limitations,
                    "coverage": coverage,
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
                        outcome=entry.get("outcome", ""),
                        time_point=entry.get("time_point", ""),
                        comparison=entry.get("comparison", ""),
                        effect_measure=entry.get("effect_measure", ""),
                        estimate=entry.get("estimate"),
                        evidence_count=int(entry.get("evidence_count", 0)),
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
            staging = run_root / f".{name}.staging"
            staging.write_bytes(content)
            os.replace(staging, run_root / name)
        # A run-level manifest is the stable root used by consumers to resolve
        # every direct report link.  Keep it separate from each Result's
        # content manifest so a new Result cannot invalidate prior hashes.
        run_manifest = {
            "run_id": run_id,
            "run_index": "run-index.html",
            "results": [
                {
                    "result_id": item.result_id,
                    "trial_id": item.trial_id,
                    "state": item.state,
                    "report": item.report,
                }
                for item in index.run.results
            ],
        }
        manifest_staging = run_root / ".manifest.json.staging"
        manifest_staging.write_bytes(
            json.dumps(run_manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        os.replace(manifest_staging, run_root / "manifest.json")

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
                "operation:correct-domain-answers",
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
                target[reference.entity_id] = reference
        return (
            tuple(bundles[key] for key in sorted(bundles)),
            tuple(answers[key] for key in sorted(answers)),
        )

    def _current_domain_answer_payloads(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        invalidated_at: int,
    ) -> list[dict[str, Any]]:
        """Return the latest answer checkpoint for each Domain in event order.

        Corrections are successor checkpoints, not additional answers.  Keeping
        just the latest payload per Domain makes corrections replace associated
        rationale, Overall-policy inputs, and Final-judgment metadata together.
        """

        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        for event in self._events_for_run(ledger, run_id):
            if (
                event.scope != result_id
                or event.sequence <= invalidated_at
                or event.operation
                not in {"operation:submit-domain-answers", "operation:correct-domain-answers"}
            ):
                continue
            payload = self._event_payload(ledger, event)
            domain_id = payload.get("domain_id")
            if isinstance(domain_id, str):
                latest[domain_id] = (event.sequence, payload)
        return [payload for _sequence, payload in sorted(latest.values())]

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
        visual_citations: tuple[VisualCitationView, ...] = (),
    ) -> dict[str, SignalingQuestionView]:
        """Materialize report phrases from canonical spans, never agent text."""

        result: dict[str, SignalingQuestionView] = {}
        citations_by_id = {citation.citation_id: citation for citation in visual_citations}
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
                    visual = citations_by_id.get(transcription.revision_id)
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
                            unit_kind="paragraph",
                            visual_citation=visual
                            or VisualCitationView(
                                citation_id=transcription.revision_id,
                                source_id=transcription.source.entity_id,
                                page=transcription.page,
                                region=transcription.region,
                                boxes=(transcription.region,),
                                label="Visual transcription",
                                exact_phrase=transcription.transcription,
                                render_provenance=(
                                    f"{transcription.render_mode} at {transcription.dpi} dpi; "
                                    "visual-only; not machine-verified"
                                ),
                                quoted_text_hash=sha256_digest(
                                    transcription.transcription.encode("utf-8")
                                ),
                                geometry_scope="visual_region",
                                geometry_hash=canonical_hash(
                                    {"region": transcription.region, "page": transcription.page}
                                ),
                                render_hash=canonical_hash(
                                    {
                                        "source_id": transcription.source.entity_id,
                                        "page": transcription.page,
                                        "mode": transcription.render_mode,
                                        "dpi": transcription.dpi,
                                        "region": transcription.region,
                                    }
                                ),
                                render_mode=transcription.render_mode,
                                dpi=transcription.dpi,
                                agent_inspected=True,
                                inspection_status="visual_only_transcription",
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
                visual_citation = None
                visual_failure = None
                try:
                    built_citation = build_visual_citation(
                        unit,
                        span_start=claim.span_start,
                        span_end=claim.span_end,
                    )
                    visual_citation = citations_by_id.get(built_citation.citation_id)
                except (TypeError, ValueError) as error:
                    # Spatial provenance is optional for canonical text.  Do
                    # not fabricate a visual region when it is absent or
                    # malformed; retain the reason in the report provenance.
                    visual_failure = str(error)
                provenance = (
                    f"canonical unit {unit.unit_id}; Parse record {unit.parse_id}; "
                    f"verification {claim.verification_status.value}"
                )
                if visual_failure:
                    provenance += f"; visual citation unavailable: {visual_failure}"
                items.append(
                    EvidenceView(
                        evidence_id=claim.revision_id,
                        disposition=disposition,
                        exact_phrase=phrase,
                        source_id=claim.source.entity_id,
                        page=unit.page,
                        provenance=provenance,
                        unit_kind=unit.kind.value,
                        visual_citation=visual_citation,
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
                conflicts=bundle.conflicts,
                uncertainty=(
                    (f"coverage state: {bundle.coverage_state.value}",)
                    if bundle.coverage_state.value != "complete"
                    else ()
                )
                + bundle.coverage_limitations
                + (("material source conflict retained",) if bundle.conflicts else ()),
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
        if not citations:
            return citations, {}
        if result_spec is None or prepared is None:
            raise VisualAssetMaterializationError(
                "visual citation assets require a resolved Result and prepared source inventory"
            )
        # Prepared-run records are proposal-free after #120.  Accept the
        # proposal-backed shape as well while reading older persisted records
        # and lightweight integrations that expose the same inventory.
        initialization = getattr(prepared, "initialization", None)
        if initialization is None:
            proposal = getattr(prepared, "proposal", None)
            initialization = getattr(proposal, "initialization", None)
        if initialization is None:
            raise VisualAssetMaterializationError(
                "visual citation assets require prepared source inventory"
            )
        trial = next(
            (
                item
                for item in initialization.trials
                if item.trial_id == result_spec.result.trial_id
            ),
            None,
        )
        sources = {item.source_id: item for item in trial.inventory.sources} if trial else {}
        try:
            parser = self._parser or LiteParseAdapter()
        except Exception as error:
            raise VisualAssetMaterializationError(
                f"visual citation renderer is unavailable: {error}"
            ) from error
        files: dict[str, bytes] = {}
        rendered: list[VisualCitationView] = []
        for citation in citations:
            source = sources.get(citation.source_id)
            if source is None or source.artifact_hash is None:
                raise VisualAssetMaterializationError(
                    f"source artifact for visual citation {citation.citation_id!r} is unavailable"
                )
            try:
                if (
                    citation.source_artifact_hash is not None
                    and source.artifact_hash != citation.source_artifact_hash
                ):
                    raise VisualAssetMaterializationError(
                        f"source artifact hash for visual citation {citation.citation_id!r} "
                        "does not match the bound citation"
                    )
                dpi = citation.dpi or 144
                page = parser.screenshot(
                    ledger.artifacts.read(source.artifact_hash),
                    page_numbers=(citation.page,),
                    dpi=dpi,
                )[0]
                context = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
                scale = page.dpi / 72
                left, top, right, bottom = (round(value * scale) for value in citation.region)
                left, right = max(0, left), min(context.width, right)
                top, bottom = max(0, top), min(context.height, bottom)
                if right <= left or bottom <= top:
                    raise VisualAssetMaterializationError(
                        f"visual citation {citation.citation_id!r} has an empty render region"
                    )
                crop = context.crop((left, top, right, bottom))
                # A translucent yellow fill keeps the authored source pixels
                # readable while making the accepted span continuously
                # visible.  The deterministic dark border is drawn on top
                # for contrast and print stability.
                highlight_color = (255, 235, 59, 96)
                overlay_layer = Image.new("RGBA", context.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay_layer)
                raw_boxes = citation.boxes or (citation.region,)
                pixel_boxes: list[tuple[int, int, int, int]] = []
                for box in raw_boxes:
                    box_left, box_top, box_right, box_bottom = (
                        round(value * scale) for value in box
                    )
                    box_left, box_right = max(0, box_left), min(context.width, box_right)
                    box_top, box_bottom = max(0, box_top), min(context.height, box_bottom)
                    if box_right <= box_left or box_bottom <= box_top:
                        raise VisualAssetMaterializationError(
                            f"visual citation {citation.citation_id!r} has invalid overlay geometry"
                        )
                    pixel_box = (box_left, box_top, box_right, box_bottom)
                    pixel_boxes.append(pixel_box)
                    overlay_draw.rectangle(pixel_box, fill=highlight_color)
                overlay = Image.alpha_composite(context.convert("RGBA"), overlay_layer).convert(
                    "RGB"
                )
                overlay_draw = ImageDraw.Draw(overlay)
                for pixel_box in pixel_boxes:
                    overlay_draw.rectangle(pixel_box, outline="#9a5a12", width=4)
                crop_layer = Image.new("RGBA", crop.size, (0, 0, 0, 0))
                crop_draw = ImageDraw.Draw(crop_layer)
                for box_left, box_top, box_right, box_bottom in pixel_boxes:
                    crop_draw.rectangle(
                        (
                            box_left - left,
                            box_top - top,
                            box_right - left,
                            box_bottom - top,
                        ),
                        fill=highlight_color,
                    )
                crop = Image.alpha_composite(crop.convert("RGBA"), crop_layer).convert("RGB")
                crop_draw = ImageDraw.Draw(crop)
                for box_left, box_top, box_right, box_bottom in pixel_boxes:
                    crop_draw.rectangle(
                        (
                            box_left - left,
                            box_top - top,
                            box_right - left,
                            box_bottom - top,
                        ),
                        outline="#9a5a12",
                        width=4,
                    )
                slug = hashlib.sha256(citation.citation_id.encode()).hexdigest()[:16]
                crop_path = f"visual-assets/{slug}-crop.png"
                context_path = f"visual-assets/{slug}-page.png"
                crop_output = io.BytesIO()
                crop.save(crop_output, format="PNG", optimize=False)
                crop_bytes = crop_output.getvalue()
                context_output = io.BytesIO()
                overlay.save(context_output, format="PNG", optimize=False)
                context_bytes = context_output.getvalue()
                files[crop_path] = crop_bytes
                files[context_path] = context_bytes
                rendered.append(
                    citation.model_copy(
                        update={
                            "crop_path": crop_path,
                            "context_path": context_path,
                            "base_render_hash": page.image_hash,
                            "derived_render_hash": sha256_digest(context_bytes),
                            "overlay_hash": sha256_digest(context_bytes),
                            "crop_hash": sha256_digest(crop_bytes),
                            "context_hash": sha256_digest(context_bytes),
                        }
                    )
                )
            except VisualAssetMaterializationError:
                raise
            except (OSError, TypeError, ValueError, IndexError) as error:
                raise VisualAssetMaterializationError(
                    f"visual citation {citation.citation_id!r} render failed: {error}"
                ) from error
        return tuple(rendered), files

    @staticmethod
    def _visual_citations(
        ledger: WorkflowLedger, evidence_bundles: tuple[RecordReference, ...]
    ) -> tuple[VisualCitationView, ...]:
        """Project every accepted spatial evidence span into a visual citation.

        Canonical text claims are accepted evidence even when no targeted
        visual candidate was inspected.  Their page and spatial provenance is
        sufficient to create a deterministic, agent-uninspected citation, so
        report materialization can render local crop and page assets without
        asking the model to inspect every page.  Visual transcriptions remain
        first-class citations and retain their explicit visual-only label.
        """

        citations: dict[str, VisualCitationView] = {}
        for bundle_ref in evidence_bundles:
            try:
                bundle = EvidenceBundle.model_validate_json(
                    ledger.artifacts.read(bundle_ref.content_hash)
                )
            except (TypeError, ValueError):
                continue
            for item in bundle.items:
                # Canonical EvidenceClaims are the normal accepted evidence
                # path.  Resolve the exact canonical unit bound by the claim;
                # never use agent-authored quotation text or a search
                # projection as visual provenance.
                try:
                    claim = EvidenceClaim.model_validate_json(
                        ledger.artifacts.read(item.content_hash)
                    )
                    unit = CanonicalEvidenceUnit.model_validate_json(
                        ledger.artifacts.read(claim.canonical_unit.content_hash)
                    )
                except (TypeError, ValueError):
                    claim = None
                    unit = None
                if claim is not None and unit is not None:
                    try:
                        citation = build_visual_citation(
                            unit,
                            span_start=claim.span_start,
                            span_end=claim.span_end,
                        )
                    except (TypeError, ValueError):
                        # A canonical unit may be text-citable without spatial
                        # bounds (for example, a recovered text fragment).
                        # Keep the evidence claim, but do not fabricate a
                        # geometry or a screenshot for it.
                        continue
                    phrase = unit.text[claim.span_start : claim.span_end]
                    if not phrase:
                        continue
                    region = (
                        min(box.left for box in citation.boxes),
                        min(box.top for box in citation.boxes),
                        max(box.right for box in citation.boxes),
                        max(box.bottom for box in citation.boxes),
                    )
                    geometry_note = (
                        "phrase-exact retained word geometry"
                        if citation.geometry_scope == "phrase_exact"
                        else "block-level geometry; phrase-exact overlay unavailable"
                    )
                    citations[citation.citation_id] = VisualCitationView(
                        citation_id=citation.citation_id,
                        source_id=citation.source_id,
                        page=citation.page,
                        region=region,
                        boxes=tuple(
                            (box.left, box.top, box.right, box.bottom) for box in citation.boxes
                        ),
                        label="Canonical evidence span",
                        exact_phrase=phrase,
                        render_provenance=(
                            f"canonical unit {unit.unit_id}; Parse record {citation.parse_id}; "
                            f"source artifact {citation.source_artifact_hash}; "
                            f"{citation.render.mode} at {citation.render.dpi} dpi; "
                            f"{geometry_note}; agent inspection not performed"
                        ),
                        canonical_unit_id=citation.canonical_unit_id,
                        source_artifact_hash=citation.source_artifact_hash,
                        parse_id=citation.parse_id,
                        span_start=citation.span_start,
                        span_end=citation.span_end,
                        quoted_text_hash=citation.quoted_text_hash,
                        geometry_scope=citation.geometry_scope,
                        geometry_hash=citation.geometry_hash,
                        render_hash=citation.render_hash,
                        render_mode=citation.render.mode.value,
                        dpi=citation.render.dpi,
                        agent_inspected=False,
                        inspection_status="automatic_spatial_claim",
                    )
                    continue

                try:
                    transcription = VisualTranscription.model_validate_json(
                        ledger.artifacts.read(item.content_hash)
                    )
                except (TypeError, ValueError):
                    continue
                source_artifact_hash = None
                parse_id = None
                try:
                    source_descriptor = SourceDescriptor.model_validate_json(
                        ledger.artifacts.read(transcription.source.content_hash)
                    )
                    source_artifact_hash = source_descriptor.artifact_hash
                    parse_id = (
                        source_descriptor.parse_records[0].parse_id
                        if source_descriptor.parse_records
                        else None
                    )
                except (TypeError, ValueError):
                    pass
                render_payload = {
                    "source_id": transcription.source.entity_id,
                    "source_artifact_hash": source_artifact_hash,
                    "page": transcription.page,
                    "mode": transcription.render_mode,
                    "dpi": transcription.dpi,
                    "region": transcription.region,
                }
                citations[transcription.revision_id] = VisualCitationView(
                    citation_id=transcription.revision_id,
                    source_id=transcription.source.entity_id,
                    page=transcription.page,
                    region=transcription.region,
                    boxes=(transcription.region,),
                    label="Visual transcription",
                    exact_phrase=transcription.transcription,
                    render_provenance=(
                        f"{transcription.render_mode} at {transcription.dpi} dpi; "
                        f"visual-only; not machine-verified"
                    ),
                    source_artifact_hash=source_artifact_hash,
                    parse_id=parse_id,
                    quoted_text_hash=sha256_digest(transcription.transcription.encode("utf-8")),
                    geometry_scope="visual_region",
                    geometry_hash=canonical_hash(
                        {"region": transcription.region, "page": transcription.page}
                    ),
                    render_hash=canonical_hash(render_payload),
                    render_mode=transcription.render_mode,
                    dpi=transcription.dpi,
                    agent_inspected=True,
                    inspection_status="visual_only_transcription",
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

        search_policy = EvidenceSearchPolicy()
        policy_id = search_policy.policy_id
        policy_hash = canonical_hash(search_policy)
        policy = PolicyRelease(
            entity_id=policy_id,
            revision_id=f"revision:evidence-policy-{self._digest(policy_hash)}",
            actor=ENGINE_ACTOR,
            observed_at=self._now(),
            kind=PolicyKind.EVIDENCE_SEARCH_POLICY,
            family_id="policy-family:evidence-search",
            release_id="2.0.0",
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
                overall_policy_id=f"{logic.family_id}:overall:{logic.release_id}",
                overall_policy_hash=logic.content_hash,
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

    def _materialize_final_judgment_revisions(
        self,
        ledger: WorkflowLedger,
        result_id: Identifier,
        *,
        logic: Any,
        evaluation: Any,
        judgment_references: tuple[RecordReference, ...],
        evidence_references: tuple[RecordReference, ...],
        answer_payloads: list[dict[str, Any]],
        assessment_digest: str,
    ) -> tuple[RecordReference, ...]:
        """Freeze one Final judgment per Domain without losing the algorithmic result."""

        departures: dict[str, _HistoricalFinalJudgmentInput] = {}
        answer_actors: dict[str, Actor] = {}
        for payload in answer_payloads:
            raw_submission = payload.get("submission")
            if isinstance(raw_submission, dict):
                domain_id = raw_submission.get("domain_id")
                raw_actor = raw_submission.get("actor")
                if isinstance(domain_id, str):
                    answer_actors[domain_id] = (
                        Actor.model_validate(raw_actor)
                        if isinstance(raw_actor, dict)
                        else ASSESSMENT_AGENT_ACTOR
                    )
            raw_departures = payload.get("final_judgment_departures", ())
            if not isinstance(raw_departures, (list, tuple)):
                raise ValueError("final judgment departures must be a structured list")
            for raw_departure in raw_departures:
                departure = _HistoricalFinalJudgmentInput.model_validate(raw_departure)
                if departure.domain_id in departures:
                    raise ValueError(
                        f"each Domain may declare at most one Final judgment departure: "
                        f"{departure.domain_id}"
                    )
                departures[departure.domain_id] = departure

        known_domains = {domain.id for domain in logic.domains}
        unknown_domains = set(departures) - known_domains
        if unknown_domains:
            raise ValueError(
                f"Final judgment departures name unknown Domains: {sorted(unknown_domains)}"
            )

        accepted_evidence: set[tuple[str, str, str]] = set()
        for bundle_reference in evidence_references:
            bundle = EvidenceBundle.model_validate_json(
                ledger.artifacts.read(bundle_reference.content_hash)
            )
            accepted_evidence.update(
                (item.entity_id, item.revision_id, item.content_hash) for item in bundle.items
            )

        references: list[RecordReference] = []
        now = self._now()
        for domain, algorithmic_reference in zip(logic.domains, judgment_references, strict=True):
            algorithmic = evaluation.domain_judgments[domain.id]
            departure = departures.get(domain.id)
            if departure is not None:
                if departure.alternative != algorithmic:
                    raise ValueError(
                        f"Final judgment alternative for {domain.id} must equal its "
                        "Algorithmic judgment"
                    )
                if departure.judgment == algorithmic:
                    raise ValueError(
                        f"Final judgment departure for {domain.id} must differ from "
                        "Algorithmic judgment"
                    )
                cited = tuple(departure.cited_evidence)
                if any(
                    (reference.entity_id, reference.revision_id, reference.content_hash)
                    not in accepted_evidence
                    for reference in cited
                ):
                    raise ValueError(
                        "Final judgment departures must cite accepted immutable Evidence claims"
                    )
                final_judgment = departure.judgment
                alternative = departure.alternative
                rationale = departure.material_bias_rationale
            else:
                cited = ()
                final_judgment = algorithmic
                alternative = None
                rationale = None
            suffix = self._digest(f"{assessment_digest}|final-judgment|{domain.id}")
            final = FinalJudgmentRevision(
                entity_id=(
                    f"final-judgment:{result_id.removeprefix('result:')}-"
                    f"{domain.id.removeprefix('domain:')}"
                ),
                revision_id=f"revision:final-judgment-{suffix}",
                dependencies=(
                    Dependency(
                        **algorithmic_reference.model_dump(), role="dependency:algorithmic-judgment"
                    ),
                    *(
                        Dependency(**reference.model_dump(), role="dependency:evidence-item")
                        for reference in cited
                    ),
                ),
                actor=answer_actors.get(domain.id, ASSESSMENT_AGENT_ACTOR),
                observed_at=now,
                domain_id=domain.id,
                judgment=final_judgment,
                algorithmic_judgment=algorithmic_reference,
                departure=departure is not None,
                alternative=alternative,
                material_bias_rationale=rationale,
                cited_evidence=cited,
            )
            references.append(
                self._commit_frozen_artifact(
                    ledger,
                    scope=result_id,
                    operation="operation:final-judgment-revision",
                    operation_key=f"idempotency:final-judgment-{suffix}",
                    entity_id=final.entity_id,
                    revision_id=final.revision_id,
                    artifact=final,
                    actor=answer_actors.get(domain.id, ASSESSMENT_AGENT_ACTOR),
                    dependencies=final.dependencies,
                )
            )
        return tuple(references)

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
        # Source-role review is the one submission that happens before
        # confirmation (#119: it must resolve before submit_run_proposal can
        # trust any role), so it alone also accepts AWAITING_CONFIRMATION.
        allowed_states = (
            {RunState.AWAITING_CONFIRMATION, RunState.ASSESSING}
            if expected_operation
            in {
                RunOperation.SUBMIT_SOURCE_ROLE_REVIEW,
                RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
                RunOperation.SUBMIT_RESULT_RESOLUTION,
            }
            else {RunState.ASSESSING}
        )
        if work_token.run_id != run_id or work_token.operation is not expected_operation:
            expected = (
                self._next_work_item(ledger, run_id)
                if projection.run_state in allowed_states
                else None
            )
            raise StaleWorkTokenError(run_id, expected)
        if projection.run_state not in allowed_states:
            raise StaleWorkTokenError(run_id, None)
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
        transition = self._submission_transition(
            run_id=run_id,
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            artifact=artifact,
            checkpoint=checkpoint,
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

    def _submission_transition(
        self,
        *,
        run_id: Identifier,
        scope: Identifier,
        operation: Identifier,
        operation_key: Identifier,
        artifact: FrozenModel,
        checkpoint: Identifier,
        observed_at: datetime,
    ) -> Transition:
        suffix = self._digest(f"{run_id}|{operation_key}")
        return self._transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            entity_id=f"run-submission:{suffix}",
            revision_id=f"revision:run-submission-{suffix}",
            artifact=artifact,
            checkpoint=checkpoint,
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=observed_at,
        )

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
        run_id: Identifier,
        result_id: Identifier,
    ) -> RecordReference:
        """Return the exact ledger reference for one resolved ResultSpec."""
        for event in reversed(self._events_for_run(ledger, run_id)):
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
            return self._freeze_result_spec_reference(ledger, run_id, result_id, spec)
        raise ValueError("a ResultSpec is required before freezing domain evidence")

    def _freeze_result_spec_reference(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        result_spec: ResultSpecRevision,
    ) -> RecordReference:
        """Commit the Run-held ResultSpec unchanged as this Run's freeze event."""
        current = next(
            (
                revision
                for revision in ledger.current_revisions()
                if revision.entity_id == result_spec.entity_id
            ),
            None,
        )
        if current is not None and current.revision_id == result_spec.revision_id:
            expected_hash = canonical_hash(result_spec)
            if current.artifact_hash != expected_hash:
                raise ValueError("current ResultSpec revision has changed immutable content")
            return RecordReference(
                entity_id=current.entity_id,
                revision_id=current.revision_id,
                content_hash=current.artifact_hash,
            )
        if result_spec.supersedes is not None and (
            current is None or current.revision_id != result_spec.revision_id
        ):
            historical = self._result_spec_by_revision(
                ledger, result_spec.entity_id, result_spec.supersedes.revision_id
            )
            if (
                historical is None
                or canonical_hash(historical) != result_spec.supersedes.content_hash
            ):
                raise ValueError("ResultSpec supersession predecessor is not recoverable")
            self._materialize_result_spec_history(ledger, run_id, historical)
            current = next(
                (
                    revision
                    for revision in ledger.current_revisions()
                    if revision.entity_id == result_spec.entity_id
                ),
                None,
            )
            if current is None or current.revision_id != result_spec.supersedes.revision_id:
                raise ValueError(
                    "ResultSpec supersession does not descend from the current revision"
                )
        suffix = self._digest(f"{run_id}|{result_id}|{result_spec.revision_id}")
        transition = self._transition(
            scope=run_id,
            operation="operation:result-spec-frozen",
            operation_key=f"idempotency:result-spec-frozen-{suffix}",
            entity_id=result_spec.entity_id,
            revision_id=result_spec.revision_id,
            artifact=result_spec,
            checkpoint=None,
            outcome=WorkflowEventOutcome.COMPLETED,
            observed_at=result_spec.observed_at,
            actor=result_spec.actor,
            dependencies=tuple(
                DependencyInput.model_validate(item.model_dump())
                for item in result_spec.dependencies
            ),
            supersedes_revision_id=(
                result_spec.supersedes.revision_id if result_spec.supersedes is not None else None
            ),
        )
        committed = ledger.commit(
            transition,
            self._acquire_lease(ledger, result_spec.observed_at),
            now=result_spec.observed_at,
        )
        return RecordReference(
            entity_id=result_spec.entity_id,
            revision_id=result_spec.revision_id,
            content_hash=committed.artifact_hash,
        )

    def _materialize_result_spec_history(
        self, ledger: WorkflowLedger, run_id: Identifier, result_spec: ResultSpecRevision
    ) -> None:
        """Advance direct history through only the missing descendants of current."""
        current = next(
            (
                revision
                for revision in ledger.current_revisions()
                if revision.entity_id == result_spec.entity_id
            ),
            None,
        )
        pending: list[ResultSpecRevision] = []
        candidate = result_spec
        while current is None or candidate.revision_id != current.revision_id:
            pending.append(candidate)
            if candidate.supersedes is None:
                if current is not None:
                    raise ValueError(
                        "ResultSpec history does not descend from the current revision"
                    )
                break
            predecessor = self._result_spec_by_revision(
                ledger, candidate.entity_id, candidate.supersedes.revision_id
            )
            if (
                predecessor is None
                or canonical_hash(predecessor) != candidate.supersedes.content_hash
            ):
                raise ValueError("ResultSpec supersession ancestor is not recoverable")
            candidate = predecessor
        for missing in reversed(pending):
            suffix = self._digest(f"{run_id}|{missing.revision_id}|history")
            ledger.commit(
                self._transition(
                    scope=run_id,
                    operation="operation:result-spec-historical-projected",
                    operation_key=f"idempotency:result-spec-history-{suffix}",
                    entity_id=missing.entity_id,
                    revision_id=missing.revision_id,
                    artifact=missing,
                    checkpoint=None,
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=missing.observed_at,
                    actor=missing.actor,
                    dependencies=tuple(
                        DependencyInput.model_validate(item.model_dump())
                        for item in missing.dependencies
                    ),
                    supersedes_revision_id=(
                        missing.supersedes.revision_id if missing.supersedes is not None else None
                    ),
                ),
                self._acquire_lease(ledger, missing.observed_at),
                now=missing.observed_at,
            )

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
    def _effective_proposal_result_ids(proposal: RunProposal) -> tuple[Identifier, ...]:
        """Resolve explicit corrections plus unambiguous default pairings."""

        return effective_result_ids(proposal)

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
            selected_candidate = (
                issued_result_candidates.get(selection.result_candidate_id)
                if selection.result_candidate_id is not None
                else None
            )
            candidate_supplies_exact_result = (
                selected_candidate is not None
                and selected_candidate.status == "resolved"
                and selected_candidate.mapping_status is ProposalMappingStatus.ACCEPTED
                and selected_candidate.identity_completeness
                is ResultIdentityCompleteness.RESULT_COMPLETE
                and selected_candidate.result is not None
                and selected_candidate.estimate is not None
                and selected_candidate.result_id == selection.result_id
            )
            if (
                issued_results.get(selection.result_id) != selection.trial_id
                and not (
                    selected_candidate is not None and selected_candidate.status == "needs_input"
                )
                and not candidate_supplies_exact_result
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

        # Keep cardinality and disposition validation on the same projection
        # used by MCP and confirmation; there must be no second default policy.
        candidate_proposal = proposal.model_copy(update={"selections": selections})
        pairings = proposal_pairings(candidate_proposal)
        for pairing in pairings:
            pair_selections = tuple(
                item
                for item in selections
                if item.trial_id == pairing.trial_id
                and item.outcome_target_id == pairing.outcome_target_id
            )
            accepted = tuple(item for item in pair_selections if item.accepted and not item.removed)
            explicit_removed = tuple(item for item in pair_selections if item.removed)
            excluded = tuple(
                item for item in pair_selections if not item.accepted and not item.removed
            )
            if len(accepted) > 1:
                raise ValueError(
                    f"Run proposal selects more than one Result for {pairing.trial_id} × "
                    f"{pairing.outcome_target_id}"
                )
            if sum(bool(items) for items in (accepted, explicit_removed, excluded)) > 1:
                raise ValueError(
                    f"Run proposal has conflicting dispositions for {pairing.trial_id} × "
                    f"{pairing.outcome_target_id}"
                )
            if pairing.disposition == "unresolved":
                raise ValueError(
                    f"Run proposal must select, exclude, or remove {pairing.trial_id} × "
                    f"{pairing.outcome_target_id}"
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
                if (
                    item.trial_id != original.trial_id
                    or item.outcome_target_id != original.outcome_target_id
                ):
                    raise ValueError("Run proposal ambiguity pairing scope cannot be rewritten")
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
    def _rebind_candidate_ambiguities(proposal: RunProposal) -> RunProposal:
        """Keep candidate-scoped ambiguities bound across deterministic ID remaps."""

        candidates = {
            (item.trial_id, item.outcome_target_id): item.candidate_id
            for item in proposal.result_candidates
        }
        current_ids = {item.candidate_id for item in proposal.result_candidates}
        ambiguities: list[RunProposalAmbiguity] = []
        changed = False
        for ambiguity in proposal.ambiguities:
            if (
                ambiguity.scope.startswith("result-candidate:")
                and ambiguity.scope not in current_ids
                and ambiguity.trial_id is not None
                and ambiguity.outcome_target_id is not None
            ):
                candidate_id = candidates.get((ambiguity.trial_id, ambiguity.outcome_target_id))
                if candidate_id is not None:
                    ambiguity = ambiguity.model_copy(update={"scope": candidate_id})
                    changed = True
            ambiguities.append(ambiguity)
        if changed:
            return proposal.model_copy(update={"ambiguities": tuple(ambiguities)})
        return proposal

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
        if projection.run_state is RunState.AWAITING_CONFIRMATION:
            # Source-role review must resolve before submit_run_proposal can
            # trust any role (#119) — no Trial selection is confirmed yet at
            # this point, so every inventory-ready Trial is in scope.
            initialization = self._prepared_initialization(ledger, run_id)
            events = self._events_for_run(ledger, run_id)
            if any(
                trial.status == "inventory_ready" for trial in initialization.trials
            ) and not self._source_role_review_complete(
                initialization, ledger, events, selected_trial_ids=None
            ):
                return self._work_item(
                    run_id, "source-roles", RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
                )
            initialization = self._initialization_with_resolved_source_roles(ledger, run_id)
            if not self._initialization_discovery_complete(initialization, ledger, run_id):
                reviewed = {
                    (
                        (item.get("coverage_receipt") or {}).get("source_id"),
                        (item.get("coverage_receipt") or {}).get("source_artifact_hash"),
                        (item.get("coverage_receipt") or {}).get("parse_id"),
                    )
                    for event in events
                    if event.operation == "operation:submit-proposal-discovery-review"
                    for item in (self._event_payload(ledger, event),)
                }
                for trial in initialization.trials:
                    if trial.status != "inventory_ready":
                        continue
                    for source in trial.inventory.sources:
                        if not self._is_eligible_discovery_source(source):
                            continue
                        for parse in source.parse_records:
                            if (
                                source.artifact_hash is None
                                or parse.artifact_hash != source.artifact_hash
                                or (source.source_id, source.artifact_hash, parse.parse_id)
                                in reviewed
                            ):
                                continue
                            return self._work_item(
                                run_id,
                                (
                                    f"proposal-discovery:{trial.trial_id}|{source.source_id}"
                                    f"|{parse.parse_id}"
                                ),
                                RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                                trial_id=trial.trial_id,
                                source_id=source.source_id,
                                parse_id=parse.parse_id,
                            )
            if self._has_durable_proposal(ledger, run_id):
                proposal = self._latest_proposal(ledger, run_id)
            else:
                proposal = None
            if proposal is not None:
                corrective_identities = {
                    (
                        limitation.source_id,
                        limitation.source_artifact_hash,
                        limitation.parse_id,
                    )
                    for limitation in proposal.limitations
                    if limitation.material
                    and limitation.kind
                    in {
                        ProposalLimitationKind.DISCOVERY_FAILED,
                        ProposalLimitationKind.DISCOVERY_LIMITED,
                    }
                    and limitation.source_id is not None
                }
                corrective_sources = {
                    limitation.scope
                    for limitation in proposal.limitations
                    if limitation.material
                    and limitation.kind
                    in {
                        ProposalLimitationKind.DISCOVERY_FAILED,
                        ProposalLimitationKind.DISCOVERY_LIMITED,
                    }
                    and limitation.source_id is None
                    and limitation.scope != run_id
                }
                candidate_identities = {
                    item.candidate_id: (
                        item.provenance.source_id,
                        item.provenance.artifact_hash,
                        item.provenance.parse_id,
                    )
                    for item in (
                        *proposal.reported_endpoint_candidates,
                        *proposal.reported_randomization_candidates,
                        *proposal.reported_arm_candidates,
                    )
                }
                receipt_identities = {
                    receipt.receipt_id: (
                        receipt.source_id,
                        receipt.source_artifact_hash,
                        receipt.parse_id,
                    )
                    for receipt in proposal.proposal_discovery_receipts
                }
                for limitation in proposal.limitations:
                    if (
                        not limitation.material
                        or limitation.kind
                        not in {
                            ProposalLimitationKind.DISCOVERY_FAILED,
                            ProposalLimitationKind.DISCOVERY_LIMITED,
                        }
                        or limitation.scope != run_id
                        or limitation.source_id is not None
                    ):
                        continue
                    corrective_identities.update(
                        candidate_identities[candidate_id]
                        for candidate_id in limitation.candidate_ids
                        if candidate_id in candidate_identities
                    )
                    corrective_identities.update(
                        receipt_identities[receipt_id]
                        for receipt_id in limitation.receipt_ids
                        if receipt_id in receipt_identities
                    )
                if (
                    not corrective_sources
                    and not corrective_identities
                    and any(
                        limitation.material
                        and limitation.kind
                        in {
                            ProposalLimitationKind.DISCOVERY_FAILED,
                            ProposalLimitationKind.DISCOVERY_LIMITED,
                        }
                        and limitation.scope == run_id
                        for limitation in proposal.limitations
                    )
                ):
                    corrective_sources.update(
                        source.source_id
                        for trial in proposal.initialization.trials
                        for source in trial.inventory.sources
                        if self._is_eligible_discovery_source(source)
                    )
                for trial in proposal.initialization.trials:
                    for source in trial.inventory.sources:
                        for parse in source.parse_records:
                            identity = (source.source_id, source.artifact_hash, parse.parse_id)
                            if (
                                identity not in corrective_identities
                                and source.source_id not in corrective_sources
                            ):
                                continue
                            return self._work_item(
                                run_id,
                                (
                                    "proposal-discovery-correction:"
                                    f"{proposal.proposal_token}:{source.source_id}:{parse.parse_id}"
                                ),
                                RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW,
                                trial_id=trial.trial_id,
                                source_id=source.source_id,
                                parse_id=parse.parse_id,
                            )
            partial_mapping = next(
                (
                    candidate
                    for candidate in (proposal.result_candidates if proposal else ())
                    if (
                        candidate.mapping_status is ProposalMappingStatus.PROPOSED
                        and candidate.identity_completeness
                        is ResultIdentityCompleteness.ANALYSIS_PARTIAL
                        and candidate.result_id is not None
                    )
                ),
                None,
            )
            if partial_mapping is not None and not self._has_result_resolution(
                events, partial_mapping.result_id
            ):
                return self._work_item(
                    run_id,
                    f"result-resolution:{proposal.proposal_token}:{partial_mapping.result_id}",
                    RunOperation.SUBMIT_RESULT_RESOLUTION,
                    result_id=partial_mapping.result_id,
                    trial_id=partial_mapping.trial_id,
                )
            if (
                proposal
                and proposal.reported_endpoint_candidates
                and proposal.randomization_bindings
                and {
                    item.candidate_id
                    for item in proposal.reported_endpoint_candidates
                    if (
                        item.randomization_candidate_id in dict(proposal.randomization_bindings)
                        and any(
                            disposition.candidate_id == item.candidate_id
                            and disposition.disposition == "accepted"
                            for receipt in proposal.proposal_discovery_receipts
                            for disposition in receipt.candidate_dispositions
                        )
                    )
                }
                - {
                    item.endpoint_candidate_id
                    for item in proposal.result_candidates
                    if (
                        item.endpoint_candidate_id is not None
                        and (
                            (
                                item.mapping_status is ProposalMappingStatus.ACCEPTED
                                and item.identity_completeness
                                is ResultIdentityCompleteness.RESULT_COMPLETE
                            )
                            or (
                                item.mapping_status is ProposalMappingStatus.PROPOSED
                                and item.identity_completeness
                                is ResultIdentityCompleteness.ANALYSIS_PARTIAL
                                and item.result_id is not None
                                and self._has_result_resolution(events, item.result_id)
                            )
                        )
                    )
                }
            ):
                return self._work_item(
                    run_id,
                    f"result-mapping:{proposal.proposal_token}",
                    RunOperation.SUBMIT_RESULT_MAPPING_REVIEW,
                )
            return None
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
        ) and not self._source_role_review_complete(
            proposal,
            ledger,
            events,
            selected_trial_ids=selected_trial_ids,
        ):
            return self._work_item(run_id, "sources", RunOperation.SUBMIT_SOURCE_ROLE_REVIEW)
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
        result_states = {item.result_id: item.state for item in projection.results}
        result_ids = tuple(
            result_id
            for result_id in all_result_ids
            if result_id not in failed_result_ids
            and result_states.get(result_id)
            not in {ResultState.DIAGNOSTIC_READY, ResultState.REPORT_READY}
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
                if self._result_spec_for(ledger, run_id, result_id) is None
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
                # The active evidence workflow is question-scoped in v3.  A
                # session is initialized before issuing work so its exact
                # frontier and materialized context can be part of the token.
                service = self._question_session_service(ledger, run_id, result_id, domain_id)
                projection = service.initialize()
                if projection.frontier.status == "active":
                    active = projection.active_contexts[0]
                    return self._work_item(
                        run_id,
                        f"{result_id}|{domain_id}|question|{active.question_id}|"
                        f"{projection.session_content_hash}|{active.frontier_entry_hash}",
                        RunOperation.SUBMIT_QUESTION_STEP,
                        result_id=result_id,
                        domain_id=domain_id,
                        question_id=active.question_id,
                        session_content_hash=projection.session_content_hash,
                        frontier_entry_hash=active.frontier_entry_hash,
                        context_id=active.context.context_id,
                        context_hash=active.context.materialization_hash,
                    )
                # No domain evidence/answer checkpoints are issued until the
                # immutable session has committed every active answer. A
                # diagnostic terminal has no answer or overall judgment path.
                if projection.frontier.status == "diagnostic_terminal":
                    # Do not advance to later Domains of this Result. The
                    # diagnostic publication bridge will mark this Result
                    # terminal; independent Results remain schedulable.
                    break
                if not self._has_domain_checkpoint(events, result_id, domain_id, "evidence"):
                    raise RunIntegrityFailure(
                        "completed question session lacks its atomic domain evidence checkpoint"
                    )
        return None

    def _question_session_service(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
    ) -> QuestionEvidenceSessionService:
        """Load the one authoritative v3 session for a Result × Domain.

        This intentionally has no v2 fallback: the session inventory contains
        only accepted immutable Source/Parse pairs and the materializer owns
        all later stage scope selection.
        """

        result_spec = self._result_spec_for(ledger, run_id, result_id)
        if result_spec is None:
            raise ValueError("question evidence work requires a resolved Result")
        proposal = self._latest_proposal(ledger, run_id)
        trial = next(
            (
                item
                for item in proposal.initialization.trials
                if item.trial_id == result_spec.result.trial_id
            ),
            None,
        )
        if trial is None:
            raise ValueError("resolved Result has no accepted trial inventory")
        inventory_sources: list[EvidenceContextInventorySource] = []
        for source in trial.inventory.sources:
            # Keep every accepted Source. Non-searchable Sources have no
            # invented identity and are represented by explicit materialized
            # limitations in context rather than disappearing from scope.
            parse = source.parse_records[-1] if source.parse_records else None
            has_exact_identity = source.artifact_hash is not None and parse is not None
            inventory_sources.append(
                EvidenceContextInventorySource(
                    source_id=source.source_id,
                    roles=source.roles,
                    source_artifact_hash=(source.artifact_hash if has_exact_identity else None),
                    parse_id=(parse.parse_id if has_exact_identity and parse is not None else None),
                    parse_output_hash=(
                        parse.output_hash if has_exact_identity and parse is not None else None
                    ),
                    availability=source.availability,
                    processing=source.processing,
                    criticality=source.criticality,
                    page_count=(parse.page_count if parse is not None else 0),
                    indexed_unit_count=0,
                    unit_orientation=EvidenceContextUnitOrientation.PAGES,
                    chronology_facts=(
                        self._source_chronology_facts(
                            ledger,
                            run_id,
                            source.source_id,
                            source.artifact_hash if has_exact_identity else None,
                            parse.parse_id if has_exact_identity and parse is not None else None,
                            parse.output_hash if has_exact_identity and parse is not None else None,
                        )
                    ),
                )
            )
        # Reconciliation may preserve Source identities while filesystem order
        # changes (for example, a content-preserving move).  The v3 context
        # treats inventory as a Source-ID ordered set, so use that same order
        # for the session revision key; otherwise an unchanged workflow can
        # be reopened against freshly-derived stage scope IDs.
        inventory_sources.sort(key=lambda item: item.source_id)
        inventory_revision_id = f"inventory-revision:{canonical_hash(tuple(item.model_dump(mode='json') for item in inventory_sources))[7:]}"
        inventory = EvidenceContextInventory(
            inventory_id=inventory_revision_id,
            sources=tuple(inventory_sources),
        )
        logic = self._logic_pack()
        guidance = self._guidance_pack()
        compilation = compile_guidance_obligations(logic, guidance)
        obligations = tuple(
            item
            for item in compilation.obligations
            if item.question_id
            in {
                question_id
                for question_id in next(
                    domain.question_ids for domain in logic.domains if domain.id == domain_id
                )
            }
        )
        if not obligations:
            raise ValueError("Guidance has no v3 obligations for the active Logic domain")
        obligation_revision_id = f"obligation-revision:{canonical_hash(tuple(item.model_dump(mode='json') for item in obligations))[7:]}"
        seed = new_question_evidence_session(
            run_id=run_id,
            result_id=result_id,
            domain_id=domain_id,
            logic_pack=logic,
            guidance_release_id=guidance.release_id,
            obligations=obligations,
            obligation_revision_id=obligation_revision_id,
            inventory_revision_id=inventory_revision_id,
            inventory=inventory,
        )
        root = self._required_root()
        store = QuestionEvidenceSessionStore(root)
        # The key excludes history; choose its durable successor when a
        # session was already initialized rather than treating it as a new
        # seed. This is also what makes run restart/reconciliation exact.
        existing = store.load(seed)
        session = existing or seed
        return QuestionEvidenceSessionService(
            session=session,
            store=store,
            navigation_store=V3EvidenceNavigationStore(root),
            search=EvidenceSearchIndex(root / ".rob2" / "evidence.sqlite3"),
        )

    def _source_chronology_facts(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        source_id: Identifier,
        source_artifact_hash: ContentHash | None,
        parse_id: Identifier | None,
        parse_output_hash: ContentHash | None,
    ) -> tuple[V3SourceChronologyFact, ...]:
        """Latest attributable chronology facts for one exact Source/Parse identity."""

        facts: dict[Any, V3SourceChronologyFact] = {}
        for event in self._events_for_run(ledger, run_id):
            if event.operation != "operation:submit-source-chronology-review":
                continue
            try:
                review = _SourceChronologyReviewRecord.model_validate(
                    self._event_payload(ledger, event)
                ).submission
            except ValueError:
                continue
            if (
                review.source_id,
                review.source_artifact_hash,
                review.parse_id,
                review.parse_output_hash,
            ) != (source_id, source_artifact_hash, parse_id, parse_output_hash):
                continue
            facts[review.constraint] = V3SourceChronologyFact(
                constraint=review.constraint,
                status=review.status,
                rationale=review.rationale,
            )
        return tuple(facts[key] for key in sorted(facts, key=lambda item: item.value))

    def _work_item(
        self,
        run_id: Identifier,
        key: str,
        operation: RunOperation,
        *,
        result_id: Identifier | None = None,
        domain_id: Identifier | None = None,
        trial_id: Identifier | None = None,
        source_id: Identifier | None = None,
        parse_id: Identifier | None = None,
        question_id: Identifier | None = None,
        session_content_hash: ContentHash | None = None,
        frontier_entry_hash: ContentHash | None = None,
        context_id: Identifier | None = None,
        context_hash: ContentHash | None = None,
        diagnostic_stop_hash: ContentHash | None = None,
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
            source_id=source_id,
            parse_id=parse_id,
            question_id=question_id,
            session_content_hash=session_content_hash,
            frontier_entry_hash=frontier_entry_hash,
            context_id=context_id,
            context_hash=context_hash,
            diagnostic_stop_hash=diagnostic_stop_hash,
        )
        return WorkItem(
            work_item_id=work_item_id,
            work_token=token,
            operation=operation,
            result_id=result_id,
            domain_id=domain_id,
            trial_id=scoped_trial_id,
            source_id=source_id,
            parse_id=parse_id,
            question_id=question_id,
            session_content_hash=session_content_hash,
            frontier_entry_hash=frontier_entry_hash,
            context_id=context_id,
            context_hash=context_hash,
            dependency_fingerprint=token.dependency_fingerprint,
        )

    def _question_correction_work_item(
        self,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
        question_id: Identifier,
        session_content_hash: ContentHash,
    ) -> WorkItem:
        """Mint a correction-only token bound to one current session revision."""

        return self._work_item(
            run_id,
            f"{result_id}|{domain_id}|question-correction|{question_id}|{session_content_hash}",
            RunOperation.CORRECT_QUESTION_STEP,
            result_id=result_id,
            domain_id=domain_id,
            question_id=question_id,
            session_content_hash=session_content_hash,
        )

    def _evidence_diagnostic_recovery_work_item(
        self,
        run_id: Identifier,
        result_id: Identifier,
        domain_id: Identifier,
        question_id: Identifier,
        session_content_hash: ContentHash,
        context_hash: ContentHash,
        diagnostic_stop_hash: ContentHash,
    ) -> WorkItem:
        """Mint authority to revise chronology only for one evidence diagnostic."""

        return self._work_item(
            run_id,
            f"{result_id}|{domain_id}|evidence-recovery|{question_id}|"
            f"{session_content_hash}|{context_hash}|{diagnostic_stop_hash}",
            RunOperation.SUBMIT_SOURCE_CHRONOLOGY_REVIEW,
            result_id=result_id,
            domain_id=domain_id,
            question_id=question_id,
            session_content_hash=session_content_hash,
            context_hash=context_hash,
            diagnostic_stop_hash=diagnostic_stop_hash,
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
        confirmed_order = tuple(
            result_id for result_id in proposal.result_ids if result_id in active_ids
        )
        confirmed_order += tuple(sorted(active_ids - set(confirmed_order)))
        ordered_ids = confirmed_order
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation != "operation:result-work-order":
                continue
            try:
                work_order = _ResultWorkOrderRecord.model_validate(
                    self._event_payload(ledger, event)
                )
            except ValueError:
                continue
            if set(work_order.result_ids).issubset(active_ids):
                ordered_ids = work_order.result_ids + tuple(
                    result_id
                    for result_id in confirmed_order
                    if result_id not in work_order.result_ids
                )
            break
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
        path = self._logic_pack_path()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if self._logic_pack_cache is None or self._logic_pack_cache[0] != content_hash:
            self._logic_pack_cache = (content_hash, load_logic_pack(path))
        return self._logic_pack_cache[1]

    def _guidance_pack(self):
        path = self._guidance_pack_path()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if self._guidance_pack_cache is None or self._guidance_pack_cache[0] != content_hash:
            self._guidance_pack_cache = (content_hash, load_guidance_pack(path))
        return self._guidance_pack_cache[1]

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
        guidance = self._guidance_pack()
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
        available_sources = tuple(trial.inventory.sources) if trial is not None else ()
        limitations = tuple(trial.inventory.coverage_limitations) if trial is not None else ()
        session_context: Any | None = None
        if work_item.question_id is not None:
            session_projection = self._question_session_service(
                ledger, run_id, work_item.result_id, work_item.domain_id
            ).project()
            session_context = next(
                (
                    item
                    for item in session_projection.active_contexts
                    if item.question_id == work_item.question_id
                ),
                None,
            )
            if session_context is None:
                raise ValueError("work token question is no longer on the active session frontier")
            active_questions = session_projection.frontier.question_ids
            inactive_questions = tuple(
                question_id
                for question_id in domain.question_ids
                if question_id not in active_questions
            )
        # A v3 context is materialized into engine-issued pages. Do not
        # silently cut the inventory at twenty Sources; the context page IDs
        # provide bounded progressive disclosure without hiding inventory.
        selected_sources = available_sources
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
            "session_content_hash": (
                work_item.session_content_hash if session_context is not None else None
            ),
            "frontier_entry_hash": (
                session_context.frontier_entry_hash if session_context is not None else None
            ),
            "context_id": session_context.context.context_id
            if session_context is not None
            else None,
            "context_hash": (
                session_context.context.materialization_hash
                if session_context is not None
                else None
            ),
            "context_page_ids": (
                tuple(item.page_id for item in session_context.context.pages)
                if session_context is not None
                else ()
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

        root = release_root()
        try:
            lock = load_release_lock(root)
        except ValueError as error:
            raise FileNotFoundError(
                "the installed rob2.lock release contract is missing"
            ) from error
        fingerprint = installed_release_fingerprint(root, lock)

        def fingerprint_hash(name: str) -> str:
            value = fingerprint.get(name)
            if not isinstance(value, str):
                raise ValueError(f"installed release fingerprint omitted {name}")
            return value

        skill_hashes = fingerprint.get("skill_hashes")
        if not isinstance(skill_hashes, dict):
            raise ValueError("installed release fingerprint omitted skill hashes")
        assessment_skill = skill_hashes.get("rob2-assess")
        initialization_skill = skill_hashes.get("rob2-init")
        if not isinstance(assessment_skill, str) or not isinstance(initialization_skill, str):
            raise ValueError("installed release fingerprint omitted required skill hashes")

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
        components: dict[str, str] = {
            "engine-schema": content_hash(
                f"{lock.package}|{lock.package_version}|"
                f"{lock.application_contract}|{SCHEMA_VERSION}"
            ),
            "dependency-lock": fingerprint_hash("dependency_lock_hash"),
            "logic-pack": fingerprint_hash("logic_pack_hash"),
            "guidance-pack": fingerprint_hash("guidance_pack_hash"),
            "assessment-skill": assessment_skill,
            "initialization-skill": initialization_skill,
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
                        input_snapshot_hash=prepared.input_snapshot_hash,
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
        self._commit_transitions(ledger, tuple(transitions), lease, now=now)

    def _events_for_run(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> tuple[WorkflowEvent, ...]:
        cursor, events = ledger.verified_event_snapshot()
        cache_key = (ledger.path.resolve(), run_id)
        cached = self._run_event_cache.get(cache_key)
        if cached is not None and cached[0] == cursor:
            return cached[1]
        selected = []
        for event in events:
            if event.scope == run_id:
                selected.append(event)
                continue
            payload = self._event_payload(ledger, event)
            if payload.get("run_id") == run_id:
                selected.append(event)
        result = tuple(selected)
        self._run_event_cache[cache_key] = (cursor, result)
        return result

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
            self._commit_transitions(ledger, tuple(transitions), lease, now=now)

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
    def _source_role_review_complete(
        initialization: ProjectInitialization | RunProposal,
        ledger: WorkflowLedger,
        events: tuple[WorkflowEvent, ...],
        *,
        selected_trial_ids: set[Identifier] | None,
    ) -> bool:
        """Return whether every inventory-ready source has a recorded disposition.

        ``selected_trial_ids=None`` scopes to every inventory-ready Trial —
        used pre-confirmation, before any Trial selection exists yet.
        """

        inventory = (
            initialization.initialization
            if isinstance(initialization, RunProposal)
            else initialization
        )
        issued_sources = {
            source.source_id
            for trial in inventory.trials
            if trial.status == "inventory_ready"
            and (selected_trial_ids is None or trial.trial_id in selected_trial_ids)
            for source in trial.inventory.sources
            if SourceRole.REGISTRY_CURRENT not in source.roles
        }
        if not issued_sources:
            return True
        reviewed: set[Identifier] = set()
        for event in events:
            if event.operation != "operation:submit-source-role-review":
                continue
            payload = RunEngine._event_payload(ledger, event)
            raw = payload.get("selections")
            if not isinstance(raw, (list, tuple)):
                continue
            for item in raw:
                source_id = item.get("source_id") if isinstance(item, dict) else None
                if isinstance(source_id, str):
                    reviewed.add(source_id)
        return issued_sources <= reviewed

    @staticmethod
    def _is_eligible_discovery_source(source: SourceDescriptor) -> bool:
        return (
            source.availability.value == "acquired"
            and source.processing.value == "usable"
            and bool(source.parse_records)
            and any(
                role in source.roles
                for role in (
                    SourceRole.PRIMARY_REPORT,
                    SourceRole.SECONDARY_REPORT,
                    SourceRole.CLINICAL_STUDY_REPORT,
                    SourceRole.REGULATORY_DOCUMENT,
                )
            )
        )

    @staticmethod
    def _discovery_source(
        initialization: ProjectInitialization | RunProposal,
        trial_id: Identifier | None,
        source_id: Identifier,
    ) -> SourceDescriptor | None:
        inventory = (
            initialization.initialization
            if isinstance(initialization, RunProposal)
            else initialization
        )
        return next(
            (
                source
                for trial in inventory.trials
                if trial.trial_id == trial_id
                for source in trial.inventory.sources
                if source.source_id == source_id
            ),
            None,
        )

    def _validate_discovery_provenance(
        self,
        provenance: ReportedCandidateProvenance,
        source: SourceDescriptor,
    ) -> None:
        """Bind advisory discovery observations to issued canonical source text."""

        if source.artifact_hash is None or provenance.artifact_hash != source.artifact_hash:
            raise ValueError("reported provenance must bind the issued Source artifact hash")
        unit = EvidenceSearchIndex(self._required_root() / ".rob2" / "evidence.sqlite3").read_unit(
            provenance.canonical_unit_id
        )
        if (
            unit.source_id != source.source_id
            or unit.source_artifact_hash != provenance.artifact_hash
            or unit.parse_id != provenance.parse_id
            or unit.page != provenance.page_number
        ):
            raise ValueError("reported provenance does not match the issued canonical unit")
        if provenance.char_end > len(unit.text):
            raise ValueError("reported provenance span exceeds the issued canonical unit")
        displayed_hash = (
            "sha256:"
            + hashlib.sha256(
                unit.text[provenance.char_start : provenance.char_end].encode("utf-8")
            ).hexdigest()
        )
        if provenance.displayed_text_hash != displayed_hash:
            raise ValueError(
                "reported provenance displayed-text hash does not match the exact span"
            )

    def _initialization_discovery_complete(
        self,
        initialization: ProjectInitialization | RunProposal,
        ledger: WorkflowLedger,
        run_id: Identifier,
        pending_receipt: ProposalDiscoveryCoverageReceipt | None = None,
    ) -> bool:
        inventory = (
            initialization.initialization
            if isinstance(initialization, RunProposal)
            else initialization
        )
        required = {
            (trial.trial_id, source.source_id, source.artifact_hash, parse.parse_id)
            for trial in inventory.trials
            if trial.status == "inventory_ready"
            for source in trial.inventory.sources
            if self._is_eligible_discovery_source(source) and source.artifact_hash is not None
            for parse in source.parse_records
            if parse.artifact_hash == source.artifact_hash
        }
        completed: set[tuple[Identifier, Identifier, ContentHash, Identifier]] = set()
        for event in self._events_for_run(ledger, run_id):
            if event.operation != "operation:submit-proposal-discovery-review":
                continue
            payload = self._event_payload(ledger, event)
            receipt = payload.get("coverage_receipt")
            if isinstance(receipt, dict) and receipt.get("state") in {
                "complete",
                "complete_with_limitations",
                "failed",
                "no_candidates",
            }:
                trial_id, source_id = receipt.get("trial_id"), receipt.get("source_id")
                artifact_hash, parse_id = (
                    receipt.get("source_artifact_hash"),
                    receipt.get("parse_id"),
                )
                if all(
                    isinstance(item, str) for item in (trial_id, source_id, artifact_hash, parse_id)
                ):
                    completed.add((trial_id, source_id, artifact_hash, parse_id))
        if pending_receipt is not None:
            completed.add(
                (
                    pending_receipt.trial_id,
                    pending_receipt.source_id,
                    pending_receipt.source_artifact_hash,
                    pending_receipt.parse_id,
                )
            )
        return required <= completed

    def _proposal_discovery_complete(
        self, proposal: RunProposal, ledger: WorkflowLedger, run_id: Identifier
    ) -> bool:
        return self._initialization_discovery_complete(proposal, ledger, run_id)

    def _persist_proposal_discovery_navigation(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        token: WorkToken,
        navigation: dict[str, Any],
    ) -> None:
        payload = {
            "passes": {
                key: {
                    "continuations": tuple(value["continuations"]),
                    "candidate_unit_ids": tuple(sorted(value["candidate_unit_ids"])),
                    "complete": value["complete"],
                    "qualifying_search": value.get("qualifying_search", False),
                }
                for key, value in navigation["passes"].items()
            },
            "read_unit_ids": tuple(sorted(navigation["read_unit_ids"])),
            "read_continuations": {
                key: tuple(value) for key, value in navigation["read_continuations"].items()
            },
        }
        record = _ProposalDiscoveryNavigationRecord(
            run_id=run_id, work_token=token, navigation=payload
        )
        digest = canonical_hash(payload).removeprefix("sha256:")
        revision_digest = self._digest(f"{token.token}|{digest}")
        operation_key = f"proposal-discovery-navigation:{token.token}:{digest}"
        existing = self._event_for_operation_key(ledger, operation_key, run_id=run_id)
        if existing is not None:
            persisted = _ProposalDiscoveryNavigationRecord.model_validate_json(
                ledger.artifacts.read(existing.output_revision_hashes[0])
            )
            if canonical_hash(persisted.navigation) == canonical_hash(payload):
                return
            raise ValueError("navigation snapshot operation key collision")
        now = self._now()
        self._commit_transitions(
            ledger,
            (
                self._transition(
                    scope=run_id,
                    operation="operation:proposal-discovery-navigation",
                    operation_key=operation_key,
                    entity_id=f"proposal-discovery-navigation:{token.token}:{digest}",
                    revision_id=f"revision:proposal-discovery-navigation:{revision_digest}",
                    artifact=record,
                    checkpoint="checkpoint:proposal-discovery-navigation",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                ),
            ),
            self._acquire_lease(ledger, now),
            now=now,
        )

    def _durable_proposal_discovery_navigation(
        self, ledger: WorkflowLedger, run_id: Identifier, token: WorkToken
    ) -> dict[str, Any] | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation != "operation:proposal-discovery-navigation":
                continue
            record = _ProposalDiscoveryNavigationRecord.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            )
            if record.work_token != token:
                continue
            raw = record.navigation
            return {
                "passes": {
                    key: {
                        "continuations": list(value["continuations"]),
                        "candidate_unit_ids": set(value["candidate_unit_ids"]),
                        "complete": value["complete"],
                        "qualifying_search": value.get("qualifying_search", False),
                    }
                    for key, value in raw["passes"].items()
                },
                "read_unit_ids": set(raw["read_unit_ids"]),
                "read_continuations": {
                    key: tuple(value) for key, value in raw["read_continuations"].items()
                },
            }
        return None

    @staticmethod
    def _required_discovery_passes(
        initialization: ProjectInitialization, mode: str
    ) -> tuple[str, ...]:
        """Return the fixed pre-confirmation coverage policy, never caller input."""

        if mode == "target_guided":
            return tuple(
                f"outcome-target:{target.target_id.removeprefix('outcome-target:')}"
                for target in initialization.manifest.outcome_target_specs
            )
        return ("reported-design", "reported-endpoints")

    @classmethod
    def _proposal_discovery_policy(
        cls, initialization: ProjectInitialization, mode: str
    ) -> ProposalDiscoveryPolicy:
        """Issue semantic search constraints with the pass labels.

        A coverage receipt therefore attests to an engine-defined search, not
        merely to a caller repeating an arbitrary no-hit query under each label.
        """

        required_passes = cls._required_discovery_passes(initialization, mode)
        if mode == "target_guided":
            queries = []
            for target in initialization.manifest.outcome_target_specs:
                pass_id = f"outcome-target:{target.target_id.removeprefix('outcome-target:')}"
                target_terms = (
                    target.target_id.removeprefix("outcome-target:").replace("-", " "),
                    target.label,
                    target.outcome_construct,
                )
                terms = tuple(
                    term.casefold()
                    for text in target_terms
                    if text is not None
                    for term in re.findall(r"[a-z0-9]+", text.casefold())
                    if term
                )
                terms = tuple(
                    dict.fromkeys(
                        (
                            *terms,
                            "endpoint",
                            "outcome",
                            "mortality",
                            "survival",
                            "death",
                            "progression",
                        )
                    )
                )
                queries.append(
                    ProposalDiscoveryPassQuery(
                        pass_id=pass_id,
                        required_any_terms=tuple(dict.fromkeys(terms)),
                        canonical_query=SearchQuery(any_of=(tuple(dict.fromkeys(terms)),)),
                    )
                )
        else:
            queries = [
                ProposalDiscoveryPassQuery(
                    pass_id="reported-design",
                    required_any_terms=(
                        "randomized",
                        "randomization",
                        "allocated",
                        "allocation",
                        "assigned",
                    ),
                    canonical_query=SearchQuery(
                        any_of=(
                            ("randomized", "randomised", "allocated", "allocation", "assigned"),
                        )
                    ),
                ),
                ProposalDiscoveryPassQuery(
                    pass_id="reported-endpoints",
                    required_any_terms=("endpoint", "outcome", "primary", "secondary"),
                    canonical_query=SearchQuery(
                        any_of=(("endpoint", "outcome", "primary", "secondary"),)
                    ),
                ),
            ]
        return ProposalDiscoveryPolicy(required_passes=required_passes, pass_queries=tuple(queries))

    def _has_durable_proposal(self, ledger: WorkflowLedger, run_id: Identifier) -> bool:
        try:
            self._latest_proposal(ledger, run_id)
        except ValueError:
            return False
        return True

    def _proposal_from_discovery(
        self,
        initialization: ProjectInitialization,
        ledger: WorkflowLedger,
        run_id: Identifier,
        pending_request: SubmitProposalDiscoveryReviewRequest | None = None,
    ) -> RunProposal:
        """Construct the first durable proposal only after terminal discovery."""

        prior_proposal = (
            self._latest_proposal(ledger, run_id)
            if self._has_durable_proposal(ledger, run_id)
            else None
        )
        proposal = (
            prior_proposal if prior_proposal is not None else self._proposal(run_id, initialization)
        ).model_copy(update={"input_snapshot_hash": self._prepared_snapshot_hash(ledger, run_id)})
        submissions: list[tuple[Any, tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]] = []
        for event in self._events_for_run(ledger, run_id):
            if event.operation != "operation:submit-proposal-discovery-review":
                continue
            payload = self._event_payload(ledger, event)
            receipt = payload.get("coverage_receipt")
            if receipt is not None:
                submissions.append(
                    (
                        receipt,
                        tuple(payload.get("endpoints", ())),
                        tuple(payload.get("randomizations", ())),
                        tuple(payload.get("arms", ())),
                    )
                )
        if pending_request is not None:
            submissions.append(
                (
                    pending_request.coverage_receipt,
                    pending_request.endpoints,
                    pending_request.randomizations,
                    pending_request.arms,
                )
            )
        # Pydantic validates ledger JSON again here, so malformed historical
        # artifacts cannot silently become discovery observations.
        from rob2_kit.domain.results import (
            ProposalDiscoveryCoverageReceipt,
            ReportedArmCandidate,
            ReportedEndpointCandidate,
            ReportedRandomizationCandidate,
        )

        receipt_by_source: dict[
            tuple[Identifier, ContentHash, Identifier],
            tuple[
                ProposalDiscoveryCoverageReceipt,
                tuple[Any, ...],
                tuple[Any, ...],
                tuple[Any, ...],
            ],
        ] = {}
        current_source_identities = {
            (source.source_id, source.artifact_hash, parse.parse_id)
            for trial in proposal.initialization.trials
            for source in trial.inventory.sources
            if source.artifact_hash is not None
            for parse in source.parse_records
            if parse.artifact_hash == source.artifact_hash
        }
        proposal_events: dict[Identifier, tuple[WorkflowEvent, RunProposal]] = {}
        for event in self._events_for_run(ledger, run_id):
            if event.operation not in {
                "operation:run-proposal-discovery-reviewed",
                "operation:run-proposal-submitted",
                "operation:run-result-mapping-reviewed",
                "operation:run-reconciled",
            }:
                continue
            try:
                record = (
                    _RunReconciledRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if event.operation == "operation:run-reconciled"
                    else _ProposalSubmittedRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                )
            except (IndexError, ValueError):
                continue
            proposal_events[record.proposal.proposal_id] = (event, record.proposal)

        def is_legacy_run_wide(proposal: RunProposal) -> bool:
            return any(
                limitation.kind
                in {
                    ProposalLimitationKind.DISCOVERY_FAILED,
                    ProposalLimitationKind.DISCOVERY_LIMITED,
                }
                and limitation.scope == run_id
                and limitation.source_id is None
                and (
                    limitation.material
                    or limitation.detail
                    == "Legacy run-wide discovery limitation requires corrective review."
                )
                for limitation in proposal.limitations
            )

        # A legacy run-wide limitation applies to every current source identity.
        # Its completed corrective reviews must survive *all* descendants, not
        # just the immediately preceding proposal revision.  Walk the immutable
        # supersession chain to the original limitation and use that event as the
        # correction marker; receipts before it are ordinary discovery, while all
        # later receipts are corrective completion evidence for this lineage.
        legacy_marker_sequence: int | None = None
        if prior_proposal is not None:
            lineage: list[tuple[WorkflowEvent, RunProposal]] = []
            ancestor = prior_proposal
            visited_proposal_ids: set[Identifier] = set()
            while ancestor.proposal_id not in visited_proposal_ids:
                visited_proposal_ids.add(ancestor.proposal_id)
                entry = proposal_events.get(ancestor.proposal_id)
                if entry is None:
                    break
                lineage.append(entry)
                if ancestor.supersedes_proposal_id is None:
                    break
                predecessor = proposal_events.get(ancestor.supersedes_proposal_id)
                if predecessor is None:
                    break
                ancestor = predecessor[1]
            markers = [event.sequence for event, item in lineage if is_legacy_run_wide(item)]
            if markers:
                legacy_marker_sequence = min(markers)
        legacy_run_wide = legacy_marker_sequence is not None
        corrected_identities = {
            (
                receipt.source_id,
                receipt.source_artifact_hash,
                receipt.parse_id,
            )
            for event in self._events_for_run(ledger, run_id)
            if legacy_marker_sequence is not None
            and event.sequence > legacy_marker_sequence
            and event.operation == "operation:submit-proposal-discovery-review"
            for payload in (self._event_payload(ledger, event),)
            for raw_receipt in (payload.get("coverage_receipt"),)
            if isinstance(raw_receipt, dict)
            for receipt in (ProposalDiscoveryCoverageReceipt.model_validate(raw_receipt),)
        }
        if pending_request is not None:
            corrected_identities.add(
                (
                    pending_request.coverage_receipt.source_id,
                    pending_request.coverage_receipt.source_artifact_hash,
                    pending_request.coverage_receipt.parse_id,
                )
            )
        for item, endpoints, randomizations, arms in submissions:
            receipt = ProposalDiscoveryCoverageReceipt.model_validate(item)
            if (
                receipt.source_id,
                receipt.source_artifact_hash,
                receipt.parse_id,
            ) not in current_source_identities:
                # The source changed or was reparsed.  This receipt is
                # immutable history, not current completion evidence.
                continue
            # A later corrective review replaces exactly this source-artifact-
            # parse inventory; other parses remain independent current evidence.
            receipt_by_source[
                (receipt.source_id, receipt.source_artifact_hash, receipt.parse_id)
            ] = (
                receipt,
                endpoints,
                randomizations,
                arms,
            )
        current_submissions = tuple(receipt_by_source.values())
        receipt_models = tuple(item[0] for item in current_submissions)
        current_identities = {
            (receipt.source_id, receipt.source_artifact_hash, receipt.parse_id)
            for receipt in receipt_models
        }
        endpoint_models = tuple(
            ReportedEndpointCandidate.model_validate(item)
            for _, endpoints, _, _ in current_submissions
            for item in endpoints
        )
        randomization_models = tuple(
            ReportedRandomizationCandidate.model_validate(item)
            for _, _, randomizations, _ in current_submissions
            for item in randomizations
        )
        arm_models = tuple(
            ReportedArmCandidate.model_validate(item)
            for _, _, _, arms in current_submissions
            for item in arms
        )
        endpoint_models = tuple(
            item
            for item in endpoint_models
            if (
                item.provenance.source_id,
                item.provenance.artifact_hash,
                item.provenance.parse_id,
            )
            in current_identities
        )
        randomization_models = tuple(
            item
            for item in randomization_models
            if (
                item.provenance.source_id,
                item.provenance.artifact_hash,
                item.provenance.parse_id,
            )
            in current_identities
        )
        arm_models = tuple(
            item
            for item in arm_models
            if (
                item.provenance.source_id,
                item.provenance.artifact_hash,
                item.provenance.parse_id,
            )
            in current_identities
        )
        all_candidate_ids = tuple(
            item.candidate_id for item in (*endpoint_models, *randomization_models, *arm_models)
        )
        if len(set(all_candidate_ids)) != len(all_candidate_ids):
            raise ValueError("proposal discovery aggregation contains duplicate candidate IDs")
        limitations: list[ProposalLimitation] = [
            item
            for item in proposal.limitations
            if item.kind
            not in {
                ProposalLimitationKind.NO_OUTCOME_TARGETS,
                ProposalLimitationKind.NO_REPORTED_ENDPOINTS,
                ProposalLimitationKind.DISCOVERY_LIMITED,
                ProposalLimitationKind.DISCOVERY_FAILED,
            }
        ]
        if not proposal.outcome_targets:
            limitations.append(
                ProposalLimitation(
                    kind=ProposalLimitationKind.NO_OUTCOME_TARGETS,
                    scope=run_id,
                    material=False,
                    detail="No Outcome targets have been declared; human promotion remains available.",
                    recovery_actions=(
                        "Promote an Outcome target if assessment scope is intended.",
                    ),
                )
            )
        if not endpoint_models:
            limitations.append(
                ProposalLimitation(
                    kind=ProposalLimitationKind.NO_REPORTED_ENDPOINTS,
                    scope=run_id,
                    material=bool(proposal.outcome_targets)
                    and not bool(proposal.initialization.result_specs),
                    detail="Completed eligible full-text discovery reported no endpoint candidates.",
                    recovery_actions=(
                        "Review source coverage or add an eligible full-text report.",
                    ),
                    receipt_ids=tuple(item.receipt_id for item in receipt_models),
                )
            )
        for receipt in receipt_models:
            if receipt.state == "complete_with_limitations":
                limitations.append(
                    ProposalLimitation(
                        kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                        scope=receipt.source_id,
                        material=bool(proposal.outcome_targets),
                        detail=receipt.detail or "Discovery was limited.",
                        recovery_actions=("Resolve the documented source limitation.",),
                        receipt_ids=(receipt.receipt_id,),
                        source_id=receipt.source_id,
                        source_artifact_hash=receipt.source_artifact_hash,
                        parse_id=receipt.parse_id,
                    )
                )
            if receipt.state == "failed":
                limitations.append(
                    ProposalLimitation(
                        kind=ProposalLimitationKind.DISCOVERY_FAILED,
                        scope=receipt.source_id,
                        material=True,
                        detail=receipt.detail or "Discovery failed.",
                        recovery_actions=("Repair or replace the eligible full-text source.",),
                        receipt_ids=(receipt.receipt_id,),
                        source_id=receipt.source_id,
                        source_artifact_hash=receipt.source_artifact_hash,
                        parse_id=receipt.parse_id,
                    )
                )
        unresolved_ids = {
            disposition.candidate_id
            for receipt in receipt_models
            for disposition in receipt.candidate_dispositions
            if disposition.disposition == "unresolved"
        }
        unresolved_by_identity: dict[
            tuple[Identifier, ContentHash, Identifier], list[Identifier]
        ] = {}
        for candidate in (*endpoint_models, *randomization_models, *arm_models):
            if candidate.candidate_id not in unresolved_ids:
                continue
            provenance = candidate.provenance
            unresolved_by_identity.setdefault(
                (provenance.source_id, provenance.artifact_hash, provenance.parse_id), []
            ).append(candidate.candidate_id)
        for (source_id, artifact_hash, parse_id), candidate_ids in unresolved_by_identity.items():
            limitations.append(
                ProposalLimitation(
                    kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                    scope=run_id,
                    material=True,
                    detail="Potentially material discovery candidates remain unresolved.",
                    recovery_actions=("Resolve each surfaced discovery disposition.",),
                    candidate_ids=tuple(candidate_ids),
                    receipt_ids=tuple(
                        receipt.receipt_id
                        for receipt in receipt_models
                        if (
                            receipt.source_id,
                            receipt.source_artifact_hash,
                            receipt.parse_id,
                        )
                        == (source_id, artifact_hash, parse_id)
                    ),
                    source_id=source_id,
                    source_artifact_hash=artifact_hash,
                    parse_id=parse_id,
                )
            )
        rejected_endpoint_ids = tuple(
            disposition.candidate_id
            for receipt in receipt_models
            for disposition in receipt.candidate_dispositions
            if (
                disposition.disposition == "rejected"
                and disposition.candidate_id in {item.candidate_id for item in endpoint_models}
            )
        )
        if rejected_endpoint_ids:
            limitations.append(
                ProposalLimitation(
                    kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                    scope=run_id,
                    material=False,
                    detail=(
                        "Reported endpoint candidates were rejected during discovery; "
                        "they are terminal exclusions and will not receive mapping work."
                    ),
                    recovery_actions=("Promote a different accepted endpoint if required.",),
                    candidate_ids=rejected_endpoint_ids,
                    receipt_ids=tuple(item.receipt_id for item in receipt_models),
                )
            )
        if legacy_run_wide:
            remaining_identities = current_source_identities - corrected_identities
            if remaining_identities:
                limitations.append(
                    ProposalLimitation(
                        kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                        scope=run_id,
                        material=False,
                        detail="Legacy run-wide discovery limitation requires corrective review.",
                        recovery_actions=("Complete every issued corrective discovery review.",),
                    )
                )
            for source_id, artifact_hash, parse_id in sorted(remaining_identities):
                limitations.append(
                    ProposalLimitation(
                        kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                        scope=run_id,
                        material=True,
                        detail="Legacy run-wide discovery limitation requires corrective review.",
                        recovery_actions=("Complete this issued corrective discovery review.",),
                        source_id=source_id,
                        source_artifact_hash=artifact_hash,
                        parse_id=parse_id,
                    )
                )
        successor = proposal.model_copy(
            update={
                "reported_endpoint_candidates": endpoint_models,
                "reported_randomization_candidates": randomization_models,
                "reported_arm_candidates": arm_models,
                "proposal_discovery_receipts": receipt_models,
                "limitations": tuple(limitations),
                "supersedes_proposal_id": (
                    prior_proposal.proposal_id if prior_proposal is not None else None
                ),
            }
        )
        successor = successor.model_copy(
            update={"semantic_diff": semantic_diff(proposal, successor)}
        )
        return self._freeze_submitted_proposal(successor)

    def _resolved_source_roles(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> dict[Identifier, tuple[SourceRole, ...]]:
        """Read every committed Source-role disposition for this Run.

        An accepted selection resolves to its own ``roles`` override when
        given, else the matching Source-role candidate's proposed roles. A
        rejected selection resolves to ``UNCLASSIFIED_SUPPORTING`` — the
        reviewer said the cue was wrong, so nothing downstream may keep
        trusting it. Later events win on repeated review of the same source.
        """

        initialization = (
            self._latest_proposal(ledger, run_id).initialization
            if self._has_durable_proposal(ledger, run_id)
            else self._prepared_initialization(ledger, run_id)
        )
        candidate_roles = {
            candidate.source_id: candidate.roles
            for candidate in initialization.source_role_candidates
        }
        resolved: dict[Identifier, tuple[SourceRole, ...]] = {}
        for event in self._events_for_run(ledger, run_id):
            if event.operation != "operation:submit-source-role-review":
                continue
            payload = self._event_payload(ledger, event)
            raw = payload.get("selections")
            if not isinstance(raw, (list, tuple)):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                source_id = item.get("source_id")
                if not isinstance(source_id, str):
                    continue
                if item.get("accepted", True):
                    roles = item.get("roles")
                    if isinstance(roles, (list, tuple)) and roles:
                        resolved[source_id] = tuple(SourceRole(value) for value in roles)
                    elif source_id in candidate_roles:
                        resolved[source_id] = candidate_roles[source_id]
                else:
                    resolved[source_id] = (SourceRole.UNCLASSIFIED_SUPPORTING,)
        return resolved

    def _apply_resolved_source_roles(
        self, proposal: RunProposal, ledger: WorkflowLedger, run_id: Identifier
    ) -> RunProposal:
        """Overlay accepted/rejected Source-role dispositions onto SourceDescriptor.roles.

        ``_classify``'s cue is never authoritative by itself (#119); this is
        the one place that turns a recorded disposition into the role value
        ``validate_result_sources``, ``_preferred_candidate``, and Source
        criticality read from the proposal built here onward.
        """

        resolved = self._resolved_source_roles(ledger, run_id)
        if not resolved:
            return proposal
        trials = tuple(
            trial.model_copy(
                update={
                    "inventory": trial.inventory.model_copy(
                        update={
                            "sources": tuple(
                                source.model_copy(update={"roles": resolved[source.source_id]})
                                if source.source_id in resolved
                                else source
                                for source in trial.inventory.sources
                            )
                        }
                    )
                }
            )
            for trial in proposal.initialization.trials
        )
        initialization = proposal.initialization.model_copy(update={"trials": trials})
        return proposal.model_copy(update={"initialization": initialization})

    def _initialization_with_resolved_source_roles(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> ProjectInitialization:
        """Overlay source-role reviews while the Run is still pre-proposal."""

        initialization = self._prepared_initialization(ledger, run_id)
        resolved = self._resolved_source_roles(ledger, run_id)
        if not resolved:
            return initialization
        trials = tuple(
            trial.model_copy(
                update={
                    "inventory": trial.inventory.model_copy(
                        update={
                            "sources": tuple(
                                source.model_copy(update={"roles": resolved[source.source_id]})
                                if source.source_id in resolved
                                else source
                                for source in trial.inventory.sources
                            )
                        }
                    )
                }
            )
            for trial in initialization.trials
        )
        return initialization.model_copy(update={"trials": trials})

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
        initialization = self._bind_declared_result_spec_supersessions(
            ledger, initialization, run_id=run_id
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
        refreshed = self._rebind_candidate_ambiguities(refreshed)
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
        resolved_candidate_pairs = {
            (candidate.trial_id, candidate.outcome_target_id)
            for candidate in initialization.result_candidates
            if candidate.status == "resolved" and candidate.result_id is not None
        }
        material_ambiguities.extend(
            item
            for item in refreshed.unresolved_ambiguities
            if item.scope not in added_candidate_ids
            and (item.trial_id, item.outcome_target_id) not in resolved_candidate_pairs
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

    def _result_spec_by_revision(
        self,
        ledger: WorkflowLedger,
        entity_id: Identifier,
        revision_id: Identifier,
        *,
        run_id: Identifier | None = None,
    ) -> ResultSpecRevision | None:
        events = self._events_for_run(ledger, run_id) if run_id is not None else ledger.events()
        for event in reversed(events):
            try:
                if event.entity_id == entity_id and event.revision_id == revision_id:
                    spec = ResultSpecRevision.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if spec.entity_id == entity_id and spec.revision_id == revision_id:
                        return spec
                payload = self._event_payload(ledger, event)
                raw_spec = payload.get("result_spec")
                if isinstance(raw_spec, dict):
                    spec = ResultSpecRevision.model_validate(raw_spec)
                    if spec.entity_id == entity_id and spec.revision_id == revision_id:
                        return spec
            except (IndexError, OSError, TypeError, ValueError):
                continue
        return None

    def _bind_declared_result_spec_supersessions(
        self,
        ledger: WorkflowLedger,
        initialization: ProjectInitialization,
        *,
        run_id: Identifier | None = None,
    ) -> ProjectInitialization:
        """Establish a declaration's predecessor before deriving its revision ID."""
        current_by_entity = {
            revision.entity_id: revision for revision in ledger.current_revisions()
        }
        bound: list[ResultSpecRevision] = []
        for spec in initialization.result_specs:
            # Within an existing Run, a later reconciliation envelope is the
            # authoritative predecessor even while an earlier frozen revision
            # remains project-current.  Otherwise a new Run retains the
            # project-wide current-revision behavior.
            predecessor = (
                self._latest_result_spec_for_entity(ledger, spec.entity_id, run_id=run_id)
                if run_id is not None
                else None
            )
            if predecessor is None:
                current = current_by_entity.get(spec.entity_id)
                predecessor = (
                    self._result_spec_by_revision(ledger, current.entity_id, current.revision_id)
                    if current is not None
                    else self._latest_result_spec_for_entity(ledger, spec.entity_id, run_id=None)
                )
            if predecessor is None:
                bound.append(spec)
                continue
            if spec.supersedes is not None and (
                spec.supersedes.revision_id != predecessor.revision_id
                or spec.supersedes.content_hash != canonical_hash(predecessor)
            ):
                raise ValueError(
                    "declared ResultSpec supersedes a revision other than the current "
                    "Project ResultSpec revision"
                )
            supersedes = Supersession(
                entity_id=spec.entity_id,
                revision_id=predecessor.revision_id,
                content_hash=canonical_hash(predecessor),
                reason="new declared ResultSpec observation supersedes the prior revision",
            )
            preimage = spec.model_dump(mode="json", exclude={"revision_id"})
            preimage["supersedes"] = supersedes.model_dump(mode="json")
            bound.append(
                spec.model_copy(
                    update={
                        "revision_id": derive_result_spec_revision_id(preimage),
                        "supersedes": supersedes,
                    }
                )
            )
        return initialization.model_copy(update={"result_specs": tuple(bound)})

    def _latest_result_spec_for_entity(
        self, ledger: WorkflowLedger, entity_id: Identifier, *, run_id: Identifier | None
    ) -> ResultSpecRevision | None:
        events = self._events_for_run(ledger, run_id) if run_id is not None else ledger.events()
        for event in reversed(events):
            try:
                if event.entity_id == entity_id:
                    spec = ResultSpecRevision.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    )
                    if spec.entity_id == entity_id:
                        return spec
                payload = self._event_payload(ledger, event)
                raw_spec = payload.get("result_spec")
                if isinstance(raw_spec, dict):
                    spec = ResultSpecRevision.model_validate(raw_spec)
                    if spec.entity_id == entity_id:
                        return spec
            except (OSError, TypeError, ValueError):
                continue
        return None

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
        for result_spec in record.proposal.initialization.result_specs:
            previous = self._result_spec_for(ledger, run_id, result_spec.result.result_id)
            if previous is None or previous == result_spec:
                continue
            suffix = self._digest(
                f"{run_id}|{result_spec.result.result_id}|{result_spec.revision_id}"
            )
            transitions.append(
                self._transition(
                    scope=result_spec.result.result_id,
                    operation="operation:result-spec-superseded",
                    operation_key=f"idempotency:reconcile-result-spec-superseded-{suffix}",
                    entity_id=f"run-result-spec-supersession:{suffix}",
                    revision_id=f"revision:run-result-spec-supersession-{suffix}",
                    artifact=_ResultDiscoveredRecord(
                        run_id=run_id,
                        result_id=result_spec.result.result_id,
                        result_spec=result_spec,
                    ),
                    checkpoint=f"checkpoint:result-spec-superseded-{suffix}",
                    outcome=WorkflowEventOutcome.COMPLETED,
                    observed_at=now,
                )
            )
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
                        preparation_outcome="trial_failed",
                        recovery=(
                            "Restore the required readable Trial Source and continue the Run.",
                        ),
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
        self._commit_transitions(ledger, tuple(transitions), lease, now=now)

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
        remapped_source_role_candidates = tuple(
            item.model_copy(
                update={
                    "trial_id": trial_map.get(item.trial_id, item.trial_id),
                    "source_id": source_maps.get(
                        trial_map.get(item.trial_id, item.trial_id), {}
                    ).get(item.source_id, item.source_id),
                }
            )
            for item in current.source_role_candidates
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
                "source_role_candidates": remapped_source_role_candidates,
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
                "operation:run-proposal-discovery-reviewed",
                "operation:run-result-mapping-reviewed",
                "operation:run-reconciled",
            }:
                if event.operation == "operation:run-reconciled":
                    return _RunReconciledRecord.model_validate_json(
                        ledger.artifacts.read(event.output_revision_hashes[0])
                    ).proposal
                return _ProposalSubmittedRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).proposal
        raise ValueError("Run has no durable proposal")

    def _prepared_initialization(
        self, ledger: WorkflowLedger, run_id: Identifier
    ) -> ProjectInitialization:
        """Return immutable pre-proposal inventory for a prepared Run."""

        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation == "operation:run-prepared":
                return _PreparedRunRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).initialization
        raise ValueError("Run has no durable ProjectInitialization")

    def _prepared_snapshot_hash(self, ledger: WorkflowLedger, run_id: Identifier) -> ContentHash:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation == "operation:run-prepared":
                return _PreparedRunRecord.model_validate_json(
                    ledger.artifacts.read(event.output_revision_hashes[0])
                ).input_snapshot_hash
        raise ValueError("Run has no durable ProjectInitialization")

    def _proposal_for_token(
        self,
        ledger: WorkflowLedger,
        run_id: Identifier,
        proposal_token: Identifier,
    ) -> RunProposal | None:
        for event in reversed(self._events_for_run(ledger, run_id)):
            if event.operation in {
                "operation:run-proposal-submitted",
                "operation:run-proposal-discovery-reviewed",
                "operation:run-result-mapping-reviewed",
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
                trial_id=candidate.trial_id,
                outcome_target_id=candidate.outcome_target_id,
            )
            for candidate in initialization.result_candidates
            if candidate.status == "needs_input"
        )
        competing_ambiguities: list[RunProposalAmbiguity] = []
        for trial_id in (
            item.trial_id for item in initialization.trials if item.status == "inventory_ready"
        ):
            for target in initialization.manifest.outcome_target_specs:
                candidates = tuple(
                    item
                    for item in initialization.result_candidates
                    if item.trial_id == trial_id
                    and item.outcome_target_id == target.target_id
                    and item.status == "resolved"
                    and item.result_id is not None
                )
                if len({item.result_id for item in candidates}) <= 1:
                    continue
                competing_ambiguities.append(
                    RunProposalAmbiguity(
                        ambiguity_id=(
                            f"ambiguity:{self._digest(f'{run_id}|competing-result|{trial_id}|{target.target_id}')}"
                        ),
                        scope=(f"target:{self._digest(f'{trial_id}|{target.target_id}')}"),
                        detail=(
                            f"Multiple Trial-specific Result analyses match {target.label!r} "
                            f"for {trial_id}; when time is omitted, a protocol-defined "
                            "primary analysis or prespecified cutoff is preferred when "
                            "source provenance identifies one. Alternatives remain visible; "
                            "select one explicitly or exclude this pairing."
                        ),
                        material=True,
                        trial_id=trial_id,
                        outcome_target_id=target.target_id,
                    )
                )
        ambiguities = (
            finding_ambiguities
            + registry_ambiguities
            + result_ambiguities
            + tuple(competing_ambiguities)
        )
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
            source_role_candidates=initialization.source_role_candidates,
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
            next_action=(
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
        proposal = (
            self._latest_proposal(ledger, run_id)
            if self._has_durable_proposal(ledger, run_id)
            else None
        )
        result_order = self._result_ids(ledger, run_id, proposal) if proposal else ()
        state_by_result = {item.result_id: item.state for item in projection.results}
        result_state_counts = {
            state.value: sum(
                1
                for result_id in result_order
                if state_by_result.get(result_id, ResultState.PENDING) is state
            )
            for state in ResultState
        }
        warning_items = list(proposal.source_limitations) if proposal else []
        reconciliation = self._latest_reconciliation(ledger, run_id)
        if reconciliation is not None:
            warning_items.extend(item.detail for item in reconciliation.material_ambiguities)
        warnings = tuple(dict.fromkeys(warning_items))
        terminal_sequences = {
            item.last_sequence
            for item in projection.results
            if item.state in {ResultState.REPORT_READY, ResultState.DIAGNOSTIC_READY}
            and item.last_sequence is not None
        }
        report_locations = tuple(
            sorted(
                {
                    str(payload["report_root"])
                    for event in events
                    if event.sequence in terminal_sequences
                    if event.operation
                    in {
                        "operation:report-materialized",
                        "operation:result-report-ready",
                        "operation:result-diagnostic-ready",
                    }
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
            warnings=warnings,
            result_state_counts=result_state_counts,
            terminal_result_counts=terminal_counts,
            report_locations=report_locations,
            result_order=result_order,
            next_action=(
                work_item.operation
                if work_item is not None
                else self._next_action_for_state(projection.run_state)
            ),
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
            next_action=RunOperation.PREPARE_RUN,
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
            next_action=RunOperation.PREPARE_RUN,
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
            next_action=RunOperation.PREPARE_RUN,
            run_id=run_id,
            run_state=run_state,
            proposal=proposal,
            error=OperationError(
                error_class=ErrorClass.AUTHORITY,
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

    def _prepare_root_authorization_required(
        self,
        root: Path,
        *,
        detail: str,
        recovery: tuple[str, ...],
        ledger: WorkflowLedger | None = None,
    ) -> PrepareRunResponse:
        run_id = f"run:rejected-{self._digest(str(root))}"
        return PrepareRunResponse(
            operation_id=self._read_operation_id(RunOperation.PREPARE_RUN, run_id),
            ledger_cursor=(
                f"ledger:{len(ledger.events())}" if ledger is not None else "ledger:unbound"
            ),
            affected_scope=(run_id,),
            condition=WorkflowCondition.RUN_BLOCKED,
            committed=False,
            next_action=RunOperation.PREPARE_RUN,
            run_id=run_id,
            run_state=RunState.BLOCKED,
            proposal=None,
            error=OperationError(
                error_class=ErrorClass.AUTHORITY,
                code="authorization_required",
                detail=detail,
                recovery=recovery,
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
            payload = ledger.artifact_json(event.output_revision_hashes[0])
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

    @staticmethod
    def _report_path_component(value: str) -> str:
        """Return a stable, confined path component for a manifest identity."""

        raw = str(value)
        readable = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
        # Sanitization alone is not injective (``a/b`` and ``a-b`` collide),
        # so retain a bounded readable prefix alongside a digest of the exact
        # identity.  The digest is always present, including for already-safe
        # identifiers, making collision resistance independent of the prefix.
        prefix = readable[:48] or "id"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}-{digest}"
