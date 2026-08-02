"""Host-neutral application gateway shared by CLI and MCP transports."""

from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rob2_kit.application.interfaces import (
    SUBMISSION_ARGUMENTS,
    MutationContext,
    OperationEnvelope,
    WorkflowStatus,
)
from rob2_kit.application.preparation import (
    AutonomousPreparation,
    DraftReady,
    PreparationPlan,
    PreparationStep,
    PreparationWorkItem,
    SubmissionKind,
    WorkSubmission,
)
from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    DecisionTrace,
)
from rob2_kit.domain.evidence import EvidenceBundle
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import Actor, Dependency, RecordReference
from rob2_kit.domain.sources import SourceInventoryRevision
from rob2_kit.evidence.search import (
    CanonicalBlock,
    CanonicalPage,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    SearchQuery,
    canonicalize_evidence_units,
)
from rob2_kit.evidence.visual import (
    VisualCandidate,
    VisualInspectionPolicy,
    VisualInspectionQueue,
)
from rob2_kit.ingestion.project import (
    DocumentParser,
    LiteParseAdapter,
    ProjectInitialization,
)
from rob2_kit.ingestion.project import initialize_project as ingest_project
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import (
    load_guidance_pack,
    load_logic_pack,
    validate_guidance_compatibility,
)
from rob2_kit.reports import ReportProjector, latest_assessment_view
from rob2_kit.reports.archives import ArchiveBuilder
from rob2_kit.review.handoff import ReviewHandoff, ReviewWaitOutcome
from rob2_kit.review.service import (
    ActionKind,
    CorrectionReworkCommand,
    CorrectionReworkStatus,
    DomainQuestionSummary,
    DomainReviewSummary,
    FindingRequirement,
    ReviewAction,
    ReviewCase,
    ReviewPolicy,
    ReviewService,
)
from rob2_kit.review.web import ReviewWebConfig
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
    LeaseToken,
    Transition,
    WorkflowEvent,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)

CONTRACT_VERSION = "1.0.0"
# The gateway's historical protocol is retained for expert/preview callers,
# but is no longer the published stdio surface.  The MCP adapter imports the
# typed RunEngine operation names below instead of these legacy names.
LEGACY_TOOL_NAMES = (
    "initialize_project",
    "project_status",
    "continue_preparation",
    "get_next_work",
    "get_trial_orientation",
    "list_sources",
    "search_evidence",
    "read_evidence_context",
    "inspect_visual_candidate",
    "submit_source_classification",
    "submit_result_resolution",
    "submit_evidence_dispositions",
    "submit_visual_transcription",
    "freeze_evidence_bundle",
    "submit_sq_answers",
    "review_queue",
    "open_review",
    "wait_for_review",
    "submit_targeted_rework",
)
STATIC_TOOL_NAMES = (
    "prepare_run",
    "run_status",
    "continue_run",
    "get_work_context",
    "submit_run_proposal",
    "confirm_run_definition",
    "search_evidence",
    "read_evidence",
    "inspect_visual_candidate",
    "submit_source_classification",
    "submit_result_resolution",
    "submit_domain_evidence",
    "submit_domain_answers",
)
MUTATION_TOOLS = frozenset(
    {
        "submit_source_classification",
        "submit_result_resolution",
        "submit_evidence_dispositions",
        "submit_visual_transcription",
        "freeze_evidence_bundle",
        "submit_sq_answers",
        "submit_targeted_rework",
    }
)
SUBMISSION_KINDS = {
    "submit_source_classification": SubmissionKind.SOURCE_CLASSIFICATION,
    "submit_result_resolution": SubmissionKind.RESULT_RESOLUTION,
    "submit_evidence_dispositions": SubmissionKind.EVIDENCE_DISPOSITIONS,
    "submit_visual_transcription": SubmissionKind.VISUAL_INSPECTION,
    "freeze_evidence_bundle": SubmissionKind.EVIDENCE_BUNDLE,
    "submit_sq_answers": SubmissionKind.SQ_ANSWERS,
}


class ApplicationGateway:
    """Expose bounded application operations without transport-specific types."""

    def __init__(self, *, parser: DocumentParser | None = None) -> None:
        self._projects: dict[str, Path] = {}
        self._review_handoffs: dict[tuple[str, bool], ReviewHandoff] = {}
        self._parser = parser

    def initialize_project(self, project_root: Path, *, authorized: bool) -> OperationEnvelope:
        root = project_root.resolve()
        already_initialized = (root / ".rob2" / "ledger.sqlite3").is_file()
        if not authorized and not already_initialized:
            raise PermissionError("project initialization requires explicit authorization")
        root.mkdir(parents=True, exist_ok=True)
        state_dir = root / ".rob2"
        state_dir.mkdir(exist_ok=True)
        project_id = _project_identifier(root)
        self._projects[project_id] = root
        ledger = _ledger(root)
        existing = ledger.events()
        if not existing:
            initialization = ingest_project(
                root,
                actor=_actor("initializer"),
                parser=self._parser,
            )
            plans = _preparation_plans(initialization)
            _index_initial_evidence(
                root,
                initialization,
                self._parser or LiteParseAdapter(),
            )
            now = datetime.now(UTC)
            lease = ledger.acquire_lease(
                "owner:application", now, timedelta(minutes=5)
            )
            payload = json.dumps(
                {
                    "project_id": project_id,
                    "root": str(root),
                    "authorized": True,
                    "initialization": initialization.model_dump(mode="json"),
                    "preparation_plans": [
                        plan.model_dump(mode="json") for plan in plans
                    ],
                },
                sort_keys=True,
            ).encode()
            ledger.commit(
                Transition(
                    scope=project_id,
                    operation="operation:initialize-project",
                    operation_key=(
                        f"idempotency:initialize-{project_id.removeprefix('project:')}"
                    ),
                    actor=_actor("initializer"),
                    observed_at=now,
                    entity_id=f"authorization:{project_id.removeprefix('project:')}",
                    revision_id=(
                        f"revision:{project_id.removeprefix('project:')}-authorization"
                    ),
                    artifact=payload,
                    artifact_media_type="application/json",
                    expected_dependency_fingerprint=dependency_fingerprint(()),
                    checkpoint="checkpoint:initialized",
                    outcome=(
                        WorkflowEventOutcome.WORK_REQUIRED
                        if plans
                        else WorkflowEventOutcome.TRIAL_PROBLEM
                    ),
                ),
                lease,
            )
            plans_by_result = {
                plan.result_id: plan for plan in plans if plan.result_id is not None
            }
            for result_spec in initialization.result_specs:
                plan = plans_by_result.get(result_spec.result.result_id)
                if plan is None:
                    continue
                ledger.commit(
                    Transition(
                        scope=plan.scope,
                        operation="operation:register-result-spec",
                        operation_key=(
                            "idempotency:register-"
                            f"{result_spec.result.result_id.removeprefix('result:')}"
                        ),
                        actor=result_spec.actor,
                        observed_at=result_spec.observed_at,
                        entity_id=result_spec.entity_id,
                        revision_id=result_spec.revision_id,
                        artifact=result_spec.model_dump_json().encode(),
                        artifact_media_type="application/json",
                        expected_dependency_fingerprint=dependency_fingerprint(()),
                        checkpoint="checkpoint:result-resolution",
                        outcome=WorkflowEventOutcome.COMPLETED,
                    ),
                    lease,
                    now=result_spec.observed_at,
                )
            existing = ledger.events()
        plans = _stored_plans(ledger)
        work_items = _available_work_items(ledger, plans)
        event = existing[0]
        status = (
            WorkflowStatus.WORK_REQUIRED
            if work_items
            else WorkflowStatus.TRIAL_PROBLEM
        )
        return OperationEnvelope(
            operation_id=event.operation_id,
            ledger_cursor=f"ledger:{len(existing)}",
            affected_scope=(project_id,),
            status=status,
            committed=True,
            next_permitted_action=(
                "action:get-next-work" if work_items else "action:add-trial-input"
            ),
            payload={
                "project_id": project_id,
                "contract_version": CONTRACT_VERSION,
                "work_item": _work_item_payload(work_items[0]) if work_items else None,
            },
        )

    def resume_project(self, project_root: Path) -> str:
        """Reopen an initialized project and validate its engine-issued identity."""
        root = project_root.resolve()
        ledger = _ledger(root)
        ledger.preflight()
        events = ledger.events()
        if not events or events[0].operation != "operation:initialize-project":
            raise ValueError("project root has not been initialized")
        payload = json.loads(ledger.artifacts.read(events[0].output_revision_hashes[0]))
        project_id = payload["project_id"]
        if project_id != _project_identifier(root):
            raise ValueError("stored project identity does not match the confined root")
        self._projects[project_id] = root
        return project_id

    def expert_command(
        self,
        project_root: Path,
        command: str,
        *,
        archive_kind: str = "complete",
    ) -> dict[str, Any]:
        """Execute CLI-only diagnostics or report an explicitly deferred projection."""
        project_id = self.resume_project(project_root)
        ledger = _ledger(project_root.resolve())
        if command in {"doctor", "verify", "repair"}:
            receipt = ledger.preflight()
            return {
                "command": command,
                "ok": receipt.ok,
                "event_count": receipt.event_count,
                "artifact_count": receipt.artifact_count,
                "repair_performed": False,
            }
        if command == "events":
            return {
                "command": command,
                "project_id": project_id,
                "events": [
                    event.model_dump(mode="json") for event in ledger.events()
                ],
            }
        if command in {"report", "export"}:
            assessment = latest_assessment_view(ledger)
            projector = ReportProjector(assessment)
            output = project_root.resolve() / "output"
            output.mkdir(exist_ok=True)
            stem = assessment.assessment_revision_id.replace(":", "_")
            projections = (
                {
                    f"{stem}.html": projector.html(),
                    f"{stem}.md": projector.markdown(),
                }
                if command == "report"
                else {
                    f"{stem}.json": projector.json(),
                    f"{stem}.summary.json": projector.summary(),
                    f"{stem}.robvis.csv": projector.robvis_csv(),
                    f"{stem}.xlsx": projector.xlsx(),
                }
            )
            paths = []
            for name, content in projections.items():
                path = output / name
                path.write_bytes(content)
                paths.append(str(path))
            return {
                "command": command,
                "status": WorkflowStatus.COMPLETED,
                "assessment_revision_id": assessment.assessment_revision_id,
                "outputs": paths,
                "committed": False,
            }
        if command == "archive":
            if archive_kind not in {"complete", "reference"}:
                raise ValueError("archive kind must be complete or reference")
            assessment = latest_assessment_view(ledger)
            output = project_root.resolve() / "output"
            output.mkdir(exist_ok=True)
            stem = assessment.assessment_revision_id.replace(":", "_")
            path = output / f"{stem}.{archive_kind}.rob2.zip"
            path.write_bytes(
                ArchiveBuilder(ledger).build(
                    assessment.assessment_revision_id,
                    kind=archive_kind,
                    pinned_files=_archive_pins(),
                )
            )
            return {
                "command": command,
                "status": WorkflowStatus.COMPLETED,
                "assessment_revision_id": assessment.assessment_revision_id,
                "archive_kind": archive_kind,
                "output": str(path),
                "committed": False,
            }
        raise ValueError(f"unknown expert command {command!r}")

    def register_review_case(self, project_root: Path, review_case: ReviewCase) -> None:
        """Persist the immutable review input needed for cross-process handoff."""
        self.resume_project(project_root)
        ledger = _ledger(project_root.resolve())
        now = datetime.now(UTC)
        lease = ledger.acquire_lease(
            "owner:application",
            now,
            timedelta(minutes=5),
            owner_is_dead=lambda _owner: True,
        )
        _commit_review_case(ledger, lease, review_case, now)

    def call(
        self,
        tool_name: str,
        project_id: str,
        *,
        arguments: dict[str, Any] | None = None,
        mutation_context: dict[str, Any] | MutationContext | None = None,
    ) -> OperationEnvelope:
        if tool_name not in LEGACY_TOOL_NAMES or tool_name == "initialize_project":
            raise ValueError(f"unknown post-initialization tool {tool_name!r}")
        root = self._projects.get(project_id)
        if root is None:
            root = _root_from_project_identifier(project_id)
            if root is not None:
                try:
                    resumed_id = self.resume_project(root)
                except (OSError, ValueError):
                    resumed_id = None
                if resumed_id != project_id:
                    root = None
        if root is None:
            raise ValueError("project identifier was not issued by this initialized engine")
        ledger = _ledger(root)
        ledger.preflight()
        if tool_name == "project_status":
            return self._project_status(project_id, ledger)
        if tool_name in {"get_trial_orientation", "list_sources"}:
            return self._initialization_read(tool_name, project_id, ledger, arguments or {})
        if tool_name == "search_evidence":
            query = SearchQuery.model_validate((arguments or {}).get("query", arguments or {}))
            page = EvidenceSearchIndex(root / ".rob2" / "evidence.sqlite3").search(
                query,
                cursor=(arguments or {}).get("cursor"),
                broad_query_justification=(arguments or {}).get(
                    "broad_query_justification"
                ),
            )
            search_payload = page.model_dump(mode="json")
            search_payload["hits"] = [
                {
                    **hit,
                    "candidate_id": _candidate_identifier(hit["unit"]["unit_id"]),
                }
                for hit in search_payload["hits"]
            ]
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|search-evidence"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload=search_payload,
            )
        if tool_name == "read_evidence_context":
            unit_id = (arguments or {}).get("unit_id")
            if not isinstance(unit_id, str):
                raise ValueError("unit_id is required")
            unit = EvidenceSearchIndex(
                root / ".rob2" / "evidence.sqlite3"
            ).read_unit(unit_id)
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|read-evidence-context"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload={"unit": unit.model_dump(mode="json")},
            )
        if tool_name == "inspect_visual_candidate":
            trial_id = (arguments or {}).get("trial_id")
            if trial_id is not None and not any(
                plan.trial_id == trial_id for plan in _stored_plans(ledger)
            ):
                raise ValueError("trial identifier was not issued by this project")
            scope = (
                f"preparation:{trial_id.removeprefix('trial:')}"
                if isinstance(trial_id, str)
                else None
            )
            candidates = _visual_candidates(ledger, scope)
            page = VisualInspectionQueue(candidates).page(
                limit=int((arguments or {}).get("limit", 1)),
                cursor=(arguments or {}).get("cursor"),
            )
            policy = VisualInspectionPolicy()
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|inspect-visual"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload={
                    **page.model_dump(mode="json"),
                    "render_requests": [
                        policy.initial_request(candidate).model_dump(mode="json")
                        for candidate in page.candidates
                    ],
                },
            )
        if tool_name in {"continue_preparation", "get_next_work"}:
            return self._continue_or_next(
                tool_name, project_id, ledger, root
            )
        if tool_name == "wait_for_review":
            return self._wait_for_review(
                project_id, ledger, root, arguments or {}
            )
        if tool_name == "review_queue":
            handoff = self._review_handoff(
                root, ledger, (arguments or {}).get("review_id")
            )
            if handoff.review_service is None:
                raise ValueError("human review remains locked until preparation is terminal")
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|review-queue"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload={
                    "queue": [
                        item.model_dump(mode="json")
                        for item in handoff.review_service.queue()
                    ]
                },
            )
        if tool_name == "open_review":
            handoff = self._review_handoff(
                root,
                ledger,
                (arguments or {}).get("review_id"),
                writable=True,
            )
            opened = handoff.open_review(
                start_server=bool((arguments or {}).get("start_server", True))
            )
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|open-review"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.REVIEW_PENDING,
                committed=False,
                next_permitted_action="action:wait-for-review",
                payload=opened.model_dump(mode="json"),
            )
        if tool_name == "submit_targeted_rework":
            if mutation_context is None:
                raise ValueError("mutation context is required")
            context = MutationContext.model_validate(mutation_context)
            submitted = arguments or {}
            handoff = self._review_handoff(
                root,
                ledger,
                submitted.get("review_id"),
                writable=True,
            )
            if handoff.review_service is None:
                raise ValueError("targeted rework requires a prepared Review handoff")
            status = CorrectionReworkStatus(submitted.get("status"))
            state = handoff.review_service.submit_targeted_rework(
                CorrectionReworkCommand(
                    operation_key=context.idempotency_key,
                    correction_receipt_revision_id=submitted.get(
                        "correction_receipt_revision_id", ""
                    ),
                    actor=_submission_actor(context.idempotency_key),
                    observed_at=datetime.now(UTC),
                    status=status,
                    last_checkpoint=submitted.get("last_checkpoint", ""),
                    failure_reason=submitted.get("failure_reason"),
                    resume_action=submitted.get("resume_action"),
                    superseding_assessment_revision_id=submitted.get(
                        "superseding_assessment_revision_id"
                    ),
                    assessment_artifact=(
                        json.dumps(
                            submitted["assessment"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                        if submitted.get("assessment") is not None
                        else None
                    ),
                    corrected_sq_id=submitted.get("corrected_sq_id"),
                    corrected_evidence_id=submitted.get("corrected_evidence_id"),
                    superseding_review_case=(
                        ReviewCase.model_validate(submitted["review_case"])
                        if submitted.get("review_case") is not None
                        else None
                    ),
                )
            )
            return OperationEnvelope(
                operation_id=_identifier(
                    "operation",
                    f"{project_id}|targeted-rework|{state.revision_id}",
                ),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(
                    state.comparison.reopened_decisions
                    if state.comparison is not None
                    else (state.correction_receipt_revision_id,)
                ),
                status=(
                    WorkflowStatus.COMPLETED
                    if state.status is CorrectionReworkStatus.SUCCEEDED
                    else WorkflowStatus.RETRYABLE_INTERRUPTION
                ),
                committed=True,
                next_permitted_action=(
                    "action:open-review"
                    if state.status is CorrectionReworkStatus.SUCCEEDED
                    else "action:submit-targeted-rework"
                ),
                payload=state.model_dump(mode="json"),
            )
        if tool_name in MUTATION_TOOLS:
            if mutation_context is None:
                raise ValueError("mutation context is required")
            context = MutationContext.model_validate(mutation_context)
            return self._commit(
                tool_name, project_id, ledger, root, context, arguments or {}
            )
        raise AssertionError(f"static tool {tool_name!r} has no application handler")

    def _continue_or_next(
        self,
        tool_name: str,
        project_id: str,
        ledger: WorkflowLedger,
        root: Path,
    ) -> OperationEnvelope:
        plans = _stored_plans(ledger)
        coordinator = _coordinator(ledger, plans)
        work_items = list(coordinator.continue_preparation())
        committed = False
        writable_coordinator: AutonomousPreparation | None = None
        for item in tuple(work_items):
            result_key = _work_item_result_key(item)
            if (
                item.submission_kind is SubmissionKind.VISUAL_INSPECTION
                and not _visual_candidates(ledger, item.scope)
            ):
                if writable_coordinator is None:
                    writable_coordinator = _coordinator(ledger, plans, writable=True)
                writable_item = writable_coordinator.next_work_item(item.scope)
                if writable_item != item:
                    raise ValueError(
                        "visual-inspection work item changed before deterministic skip"
                    )
                writable_coordinator.submit(
                    writable_item,
                    WorkSubmission(
                        work_item_id=writable_item.work_item_id,
                        operation_key=(
                            "idempotency:skip-visual-"
                            f"{result_key}"
                        ),
                        expected_dependency_fingerprint=(
                            writable_item.dependency_fingerprint
                        ),
                        submission_kind=SubmissionKind.VISUAL_INSPECTION,
                        entity_id=(
                            "visual-inspection:"
                            f"{result_key}"
                        ),
                        revision_id=_derived_revision_id(
                            "visual-inspection-not-required",
                            writable_item.dependency_fingerprint,
                        ),
                        artifact=b'{"status":"not_required"}',
                        artifact_media_type="application/json",
                    ),
                )
                committed = True
                continue
            if item.submission_kind is SubmissionKind.SOURCE_INVENTORY:
                if writable_coordinator is None:
                    writable_coordinator = _coordinator(ledger, plans, writable=True)
                writable_item = writable_coordinator.next_work_item(item.scope)
                if writable_item != item:
                    raise ValueError(
                        "source-inventory work item changed before deterministic commit"
                    )
                result_spec = _result_spec_reference(ledger, item.scope)
                initialization = _stored_initialization(ledger)
                trial = next(
                    trial
                    for trial in initialization.trials
                    if trial.trial_id == item.trial_id
                )
                inventory = SourceInventoryRevision(
                    entity_id=f"source-inventory:{result_key}",
                    revision_id=_derived_revision_id(
                        "source-inventory", item.dependency_fingerprint
                    ),
                    actor=_actor("application"),
                    observed_at=datetime.now(UTC),
                    dependencies=(
                        Dependency(
                            **result_spec.model_dump(),
                            role="dependency:result-spec",
                        ),
                    ),
                    result_spec=result_spec,
                    sources=trial.inventory.sources,
                    coverage_limitations=trial.inventory.coverage_limitations,
                )
                writable_coordinator.submit(
                    writable_item,
                    WorkSubmission(
                        work_item_id=writable_item.work_item_id,
                        operation_key=(
                            "idempotency:derive-source-inventory-"
                            f"{result_key}"
                        ),
                        expected_dependency_fingerprint=(
                            writable_item.dependency_fingerprint
                        ),
                        submission_kind=SubmissionKind.SOURCE_INVENTORY,
                        entity_id=inventory.entity_id,
                        revision_id=inventory.revision_id,
                        artifact=inventory.model_dump_json().encode(),
                        artifact_media_type="application/json",
                    ),
                )
                committed = True
                continue
            if item.submission_kind is not SubmissionKind.ASSESSMENT:
                continue
            if writable_coordinator is None:
                writable_coordinator = _coordinator(ledger, plans, writable=True)
            writable_item = writable_coordinator.next_work_item(item.scope)
            if writable_item != item:
                raise ValueError("assessment work item changed before deterministic commit")
            assessment, domain_ids, domain_summaries, review_actions = _derive_assessment(
                ledger,
                writable_coordinator.lease,
                item,
            )
            writable_item = writable_coordinator.next_work_item(item.scope)
            if writable_item is None:
                raise ValueError("assessment finalization work item disappeared")
            writable_coordinator.submit(
                writable_item,
                WorkSubmission(
                    work_item_id=writable_item.work_item_id,
                    operation_key=(
                        "idempotency:finalize-"
                        f"{result_key}"
                    ),
                    expected_dependency_fingerprint=(
                        writable_item.dependency_fingerprint
                    ),
                    submission_kind=SubmissionKind.ASSESSMENT,
                    entity_id=(
                        "preparation-outcome:"
                        f"{result_key}"
                    ),
                    revision_id=(
                        "revision:preparation-outcome-"
                        f"{result_key}"
                    ),
                    artifact=b"{}",
                    artifact_media_type="application/json",
                    outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
                    terminal_outcome=DraftReady(
                        assessment=assessment
                    ),
                ),
            )
            review_hash = "sha256:" + ("0" * 64)
            review_case = ReviewCase(
                review_id=f"review:{result_key}",
                review_revision=RecordReference(
                    entity_id=f"review:{result_key}",
                    revision_id=f"revision:review-{result_key}",
                    content_hash=review_hash,
                ),
                assessment=assessment,
                policy=ReviewPolicy(
                    reference=RecordReference(
                        entity_id="policy:review",
                        revision_id="revision:review-policy-1",
                        content_hash=review_hash,
                    ),
                    domain_ids=domain_ids,
                ),
                assessment_revision_id=assessment.revision_id,
                assessment_content_hash=assessment.content_hash,
                result_label=item.result_id or item.trial_id,
                domain_ids=domain_ids,
                domain_summaries=domain_summaries,
                actions=review_actions,
                preparation_scopes=(item.scope,),
            )
            _commit_review_case(
                ledger,
                writable_coordinator.lease,
                review_case,
                datetime.now(UTC),
            )
            committed = True
        coordinator = writable_coordinator or coordinator
        work_items = list(coordinator.continue_preparation())
        if work_items:
            first = work_items[0]
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|{tool_name}"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=tuple(item.scope for item in work_items),
                status=WorkflowStatus.WORK_REQUIRED,
                committed=committed,
                next_permitted_action="action:submit-work",
                payload={"work_item": _work_item_payload(first)},
            )
        statuses = coordinator.batch_status()
        status = (
            WorkflowStatus.PREPARATION_OUTCOME_REACHED
            if statuses
            else WorkflowStatus.TRIAL_PROBLEM
        )
        return OperationEnvelope(
            operation_id=_identifier("operation", f"{project_id}|{tool_name}"),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=tuple(statuses) or (project_id,),
            status=status,
            committed=committed,
            next_permitted_action=(
                "action:open-review"
                if status is WorkflowStatus.PREPARATION_OUTCOME_REACHED
                else None
            ),
            payload={"batch_status": statuses},
        )

    def _initialization_read(
        self,
        tool_name: str,
        project_id: str,
        ledger: WorkflowLedger,
        arguments: dict[str, Any],
    ) -> OperationEnvelope:
        payload = json.loads(ledger.artifacts.read(ledger.events()[0].output_revision_hashes[0]))
        initialization = ProjectInitialization.model_validate(payload["initialization"])
        trial_id = arguments.get("trial_id")
        trials = (
            initialization.trials
            if trial_id is None
            else tuple(item for item in initialization.trials if item.trial_id == trial_id)
        )
        if trial_id is not None and not trials:
            raise ValueError("trial identifier was not issued by this project")
        response: dict[str, Any]
        if tool_name == "list_sources":
            response = {
                "sources": [
                    source.model_dump(mode="json")
                    for trial in trials
                    for source in trial.inventory.sources
                ]
            }
        else:
            response = {
                "manifest": initialization.manifest.model_dump(mode="json"),
                "trials": [trial.model_dump(mode="json") for trial in trials],
                "review_findings": [
                    finding.model_dump(mode="json")
                    for finding in initialization.review_findings
                    if trial_id is None or finding.trial_id == trial_id
                ],
            }
        return OperationEnvelope(
            operation_id=_identifier("operation", f"{project_id}|{tool_name}"),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(project_id,),
            status=WorkflowStatus.COMPLETED,
            committed=False,
            payload=response,
        )

    def _project_status(
        self, project_id: str, ledger: WorkflowLedger
    ) -> OperationEnvelope:
        events = ledger.events()
        latest = events[-1]
        status = WorkflowStatus(latest.outcome.value)
        return OperationEnvelope(
            operation_id=_identifier("operation", f"{project_id}|project-status"),
            ledger_cursor=f"ledger:{latest.sequence}",
            affected_scope=(project_id,),
            status=status,
            committed=False,
            next_permitted_action=(
                "action:get-next-work"
                if status in {WorkflowStatus.WORK_REQUIRED, WorkflowStatus.COMPLETED}
                else None
            ),
            payload={"event_count": len(events)},
        )

    def _wait_for_review(
        self,
        project_id: str,
        ledger: WorkflowLedger,
        root: Path,
        arguments: dict[str, Any],
    ) -> OperationEnvelope:
        after_sequence = int(arguments.get("after_sequence", len(ledger.events())))
        timeout = max(0.0, min(float(arguments.get("inactivity_timeout_seconds", 30)), 300.0))
        result = self._review_handoff(
            root, ledger, arguments.get("review_id")
        ).wait_for_review(
            after_sequence=after_sequence,
            inactivity_timeout=timedelta(seconds=timeout),
        )
        events = ledger.events()
        if result.outcome is ReviewWaitOutcome.RECEIPT_AVAILABLE:
            assert result.receipt is not None
            return OperationEnvelope(
                operation_id=_identifier(
                    "operation", result.receipt.review_action_id
                ),
                ledger_cursor=f"ledger:{len(events)}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload={"receipt": result.receipt.model_dump(mode="json")},
            )
        return OperationEnvelope(
            operation_id=_identifier("operation", f"{project_id}|wait-for-review"),
            ledger_cursor=f"ledger:{len(events)}",
            affected_scope=(project_id,),
            status=WorkflowStatus.REVIEW_PENDING,
            committed=False,
            next_permitted_action="action:end-turn",
            payload={"after_sequence": after_sequence},
        )

    def _review_handoff(
        self,
        root: Path,
        ledger: WorkflowLedger,
        review_id: str | None = None,
        *,
        writable: bool = False,
    ) -> ReviewHandoff:
        cases = tuple(
            event
            for event in ledger.events()
            if event.operation == "operation:create-review-case"
            and (review_id is None or event.entity_id == review_id)
        )
        if not cases or (len(cases) > 1 and review_id is None):
            cache_key = ("workspace:project", False)
            cached = self._review_handoffs.get(cache_key)
            if cached is not None:
                return cached
            config = ReviewWebConfig(
                project_root=root,
                session_lifetime=timedelta(minutes=30),
                allowed_origin="http://127.0.0.1:0",
            )
            handoff = ReviewHandoff(None, config, ledger=ledger)
            self._review_handoffs[cache_key] = handoff
            return handoff
        case_event = cases[0]
        cache_key = (case_event.entity_id, writable)
        cached = (
            self._review_handoffs.get((case_event.entity_id, True))
            if not writable
            else None
        ) or self._review_handoffs.get(cache_key)
        if cached is not None:
            return cached
        review_case = ReviewCase.model_validate_json(
            ledger.artifacts.read(case_event.output_revision_hashes[0])
        )
        now = datetime.now(UTC)
        lease = (
            ledger.acquire_lease(
                "owner:review-gui",
                now,
                timedelta(minutes=30),
                owner_is_dead=lambda owner: owner
                in {"owner:application", "owner:preparation"},
            )
            if writable
            else LeaseToken(
                owner_id="owner:read-only",
                fencing_token=0,
                expires_at=now,
            )
        )
        service = ReviewService(ledger, lease, review_case)
        config = ReviewWebConfig(
            project_root=root,
            session_lifetime=timedelta(minutes=30),
            allowed_origin="http://127.0.0.1:0",
        )
        handoff = ReviewHandoff(service, config)
        self._review_handoffs[cache_key] = handoff
        return handoff

    def _commit(
        self,
        tool_name: str,
        project_id: str,
        ledger: WorkflowLedger,
        root: Path,
        context: MutationContext,
        arguments: dict[str, Any],
    ) -> OperationEnvelope:
        submitted = SUBMISSION_ARGUMENTS[tool_name].validate_python(
            arguments
        ).model_dump(mode="json")
        submission_actor = _submission_actor(context.idempotency_key)
        if context.contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported application contract version")
        prior = next(
            (
                event
                for event in ledger.events()
                if event.operation_key == context.idempotency_key
            ),
            None,
        )
        if prior is not None:
            normalized = _normalize_submission(
                tool_name,
                submitted,
                root,
                ledger,
                context.work_item_id,
                next(
                    plan.trial_id
                    for plan in _stored_plans(ledger)
                    if plan.scope == prior.scope
                ),
                next(
                    plan.result_id
                    for plan in _stored_plans(ledger)
                    if plan.scope == prior.scope
                ),
                prior.scope,
                submission_actor,
            )
            payload = _canonical_json(normalized)
            return _event_envelope(project_id, prior, tool_name, payload, ledger)
        coordinator = _coordinator(
            ledger,
            _stored_plans(ledger),
            writable=True,
            actor=submission_actor,
        )
        work_item = next(
            (
                item
                for item in coordinator.continue_preparation()
                if item.work_item_id == context.work_item_id
            ),
            None,
        )
        if work_item is None:
            raise ValueError("work item identifier was not issued by the engine")
        if work_item.submission_kind is not SUBMISSION_KINDS[tool_name]:
            raise ValueError("submission tool is not permitted for this work item")
        if context.expected_dependency_fingerprint != work_item.dependency_fingerprint:
            raise ValueError("work item dependency fingerprint is stale")
        normalized = _normalize_submission(
            tool_name,
            submitted,
            root,
            ledger,
            work_item.work_item_id,
            work_item.trial_id,
            work_item.result_id,
            work_item.scope,
            submission_actor,
        )
        payload = _canonical_json(normalized)
        digest = hashlib.sha256(
            f"{tool_name}|{context.idempotency_key}".encode()
        ).hexdigest()[:24]
        result = coordinator.submit(
            work_item,
            WorkSubmission(
                work_item_id=work_item.work_item_id,
                operation_key=context.idempotency_key,
                expected_dependency_fingerprint=work_item.dependency_fingerprint,
                submission_kind=work_item.submission_kind,
                entity_id=f"submission:{digest}",
                revision_id=f"revision:{digest}",
                artifact=payload,
                artifact_media_type="application/json",
            ),
        )
        return OperationEnvelope(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(work_item.scope,),
            status=WorkflowStatus.COMPLETED,
            committed=True,
            next_permitted_action="action:get-next-work",
            payload={"tool": tool_name},
        )


def _ledger(root: Path) -> WorkflowLedger:
    state = root / ".rob2"
    return WorkflowLedger(state / "ledger.sqlite3", ArtifactStore(state / "artifacts"))


def _index_initial_evidence(
    root: Path,
    initialization: ProjectInitialization,
    parser: DocumentParser,
) -> None:
    artifacts = ArtifactStore(root / ".rob2" / "artifacts")
    units = []
    for trial in initialization.trials:
        for source in trial.inventory.sources:
            if source.artifact_hash is None or not source.parse_records:
                continue
            parsed = parser.parse(
                artifacts.read(source.artifact_hash),
                ocr_enabled=False,
            )
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
    EvidenceSearchIndex(root / ".rob2" / "evidence.sqlite3").replace_units(
        tuple(units)
    )


def _visual_candidates(
    ledger: WorkflowLedger,
    scope: str | None = None,
) -> tuple[VisualCandidate, ...]:
    candidates: dict[str, VisualCandidate] = {}
    for event in ledger.events():
        if (
            event.operation != "operation:submit-evidence-dispositions"
            or (scope is not None and event.scope != scope)
        ):
            continue
        payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
        for item in payload.get("visual_candidates", ()):
            candidate = VisualCandidate.model_validate(item)
            candidates[candidate.candidate_id] = candidate
    return tuple(candidates.values())


def _normalize_submission(
    tool_name: str,
    submitted: dict[str, Any],
    root: Path,
    ledger: WorkflowLedger,
    work_item_id: str,
    trial_id: str,
    expected_result_id: str | None,
    preparation_scope: str,
    actor: Actor,
) -> dict[str, Any]:
    if tool_name == "submit_source_classification":
        source_ids = {
            source["source_id"]
            for source in _initialization_payload(ledger)["sources"]
        }
        submitted_ids = {
            item["source_id"] for item in submitted["classifications"]
        }
        initialization = _stored_initialization(ledger)
        expected_ids = {
            source.source_id
            for trial in initialization.trials
            if trial.trial_id == trial_id
            for source in trial.inventory.sources
        }
        if not submitted_ids <= source_ids:
            raise ValueError("source identifier was not issued by this project")
        if submitted_ids != expected_ids:
            raise ValueError("classifications must account for every issued trial source")
    elif tool_name == "submit_result_resolution":
        expected = expected_result_id or f"result:{trial_id.removeprefix('trial:')}"
        result_id = submitted["result"].get("result_id")
        if result_id != expected:
            raise ValueError(f"result identifier must be the engine-issued {expected}")
        digest = hashlib.sha256(_canonical_json(submitted)).hexdigest()[:24]
        result_spec = ResultSpecRevision(
            entity_id=f"result-spec:{trial_id.removeprefix('trial:')}",
            revision_id=f"revision:result-spec-{digest}",
            actor=actor,
            observed_at=ledger.events()[0].observed_at,
            result=submitted["result"],
            estimate=submitted["estimate"],
            provenance_note=submitted["provenance_note"],
        )
        submitted = result_spec.model_dump(mode="json")
    elif tool_name == "submit_evidence_dispositions":
        issued_candidates = {
            _candidate_identifier(unit_id)
            for unit_id in EvidenceSearchIndex(
                root / ".rob2" / "evidence.sqlite3"
            ).unit_ids()
        }
        if any(
            item.get("candidate_id") not in issued_candidates
            for item in submitted["dispositions"]
        ):
            raise ValueError("evidence candidate identifier was not issued by search")
        visual_candidates = []
        for index, item in enumerate(submitted["visual_candidates"], start=1):
            if item.get("candidate_id") is not None:
                raise ValueError("visual candidate identifiers are assigned by the engine")
            item["candidate_id"] = _identifier(
                "visual", f"{work_item_id}|{index}"
            )
            visual_candidates.append(
                VisualCandidate.model_validate(item).model_dump(mode="json")
            )
        submitted["visual_candidates"] = visual_candidates
    elif tool_name == "submit_visual_transcription":
        candidate_id = submitted["transcription"].get("candidate_id")
        if candidate_id not in {
            candidate.candidate_id
            for candidate in _visual_candidates(
                ledger,
                preparation_scope,
            )
        }:
            raise ValueError("visual candidate identifier was not issued by the engine")
    elif tool_name == "freeze_evidence_bundle":
        result_key = (expected_result_id or trial_id).split(":", 1)[1]
        expected = f"bundle:{result_key}"
        result_spec = _result_spec_reference(ledger, preparation_scope)
        disposition = _reference_for_operation(
            ledger,
            preparation_scope,
            "operation:submit-evidence-dispositions",
        )
        dependencies = (
            Dependency(
                **result_spec.model_dump(),
                role="dependency:result-spec",
            ),
            Dependency(
                **disposition.model_dump(),
                role="dependency:evidence-disposition",
            ),
            *(
                Dependency(
                    **RecordReference.model_validate(item).model_dump(),
                    role="dependency:evidence-item",
                )
                for item in submitted["items"]
            ),
        )
        digest = hashlib.sha256(_canonical_json(submitted)).hexdigest()[:24]
        bundle = EvidenceBundle(
            entity_id=expected,
            revision_id=f"revision:evidence-bundle-{digest}",
            actor=_actor("application"),
            observed_at=ledger.events()[0].observed_at,
            dependencies=dependencies,
            result_spec=result_spec,
            disposition=disposition,
            items=tuple(
                RecordReference.model_validate(item) for item in submitted["items"]
            ),
            frozen_content_hash=submitted["frozen_content_hash"],
            coverage_state=submitted["coverage_state"],
            coverage_limitations=tuple(submitted["coverage_limitations"]),
            no_information_basis=submitted["no_information_basis"],
            conflicts=tuple(tuple(item) for item in submitted["conflicts"]),
        )
        submitted = bundle.model_dump(mode="json")
    elif tool_name == "submit_sq_answers":
        known_questions = {
            question.id for question in load_logic_pack(_logic_pack_path()).questions
        }
        if any(
            answer.get("question_id") not in known_questions
            for answer in submitted["answers"]
        ):
            raise ValueError("SQ identifier was not issued by the pinned Logic pack")
        LogicEvaluator(load_logic_pack(_logic_pack_path())).evaluate(
            EvaluationRequest(
                answers={
                    answer["question_id"]: answer["answer"]
                    for answer in submitted["answers"]
                },
                assessor_inputs=submitted.get("assessor_inputs", {}),
            )
        )
    return submitted


def _initialization_payload(ledger: WorkflowLedger) -> dict[str, Any]:
    initialization = _stored_initialization(ledger)
    return {
        "sources": [
            source.model_dump(mode="json")
            for trial in initialization.trials
            for source in trial.inventory.sources
        ]
    }


def _stored_initialization(ledger: WorkflowLedger) -> ProjectInitialization:
    first = ledger.events()[0]
    payload = json.loads(ledger.artifacts.read(first.output_revision_hashes[0]))
    return ProjectInitialization.model_validate(payload["initialization"])


def _reference_for_operation(
    ledger: WorkflowLedger,
    scope: str,
    operation: str,
) -> RecordReference:
    event = next(
        (
            item
            for item in reversed(ledger.events())
            if item.scope == scope and item.operation == operation
        ),
        None,
    )
    if event is None:
        raise ValueError(f"required operation has not completed: {operation}")
    return RecordReference(
        entity_id=event.entity_id,
        revision_id=event.revision_id,
        content_hash=event.output_revision_hashes[0],
    )


def _result_spec_reference(
    ledger: WorkflowLedger,
    scope: str,
) -> RecordReference:
    for operation in (
        "operation:register-result-spec",
        "operation:submit-result-resolution",
    ):
        try:
            return _reference_for_operation(ledger, scope, operation)
        except ValueError:
            continue
    raise ValueError("required ResultSpec has not been resolved")


def _derived_revision_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(f"{prefix}|{seed}".encode()).hexdigest()[:24]
    return f"revision:{prefix}-{digest}"


def _commit_derived_revision(
    ledger: WorkflowLedger,
    lease: LeaseToken,
    *,
    scope: str,
    operation: str,
    operation_key: str,
    record: DecisionTrace | AlgorithmicJudgmentRevision | AssessmentRevision,
) -> RecordReference:
    dependencies = tuple(
        DependencyInput.model_validate(item.model_dump())
        for item in record.dependencies
    )
    result = ledger.commit(
        Transition(
            scope=scope,
            operation=operation,
            operation_key=operation_key,
            actor=record.actor,
            observed_at=record.observed_at,
            entity_id=record.entity_id,
            revision_id=record.revision_id,
            artifact=record.model_dump_json().encode(),
            artifact_media_type="application/json",
            dependencies=dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(dependencies),
            checkpoint=None,
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        lease,
        now=record.observed_at,
    )
    return RecordReference(
        entity_id=record.entity_id,
        revision_id=record.revision_id,
        content_hash=result.artifact_hash,
    )


def _commit_review_case(
    ledger: WorkflowLedger,
    lease: LeaseToken,
    review_case: ReviewCase,
    observed_at: datetime,
) -> RecordReference:
    current = {
        (item.entity_id, item.revision_id, item.artifact_hash)
        for item in ledger.current_revisions()
    }
    assessment = review_case.assessment
    dependencies = (
        (
            DependencyInput(
                **assessment.model_dump(),
                role="dependency:assessment",
            ),
        )
        if (
            assessment.entity_id,
            assessment.revision_id,
            assessment.content_hash,
        )
        in current
        else ()
    )
    result = ledger.commit(
        Transition(
            scope=review_case.review_id,
            operation="operation:create-review-case",
            operation_key=(
                "idempotency:create-"
                f"{review_case.review_id.removeprefix('review:')}"
            ),
            actor=_actor("application"),
            observed_at=observed_at,
            entity_id=review_case.review_id,
            revision_id=review_case.review_revision.revision_id,
            artifact=review_case.model_dump_json().encode(),
            artifact_media_type="application/json",
            dependencies=dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(dependencies),
            checkpoint="checkpoint:review-pending",
            outcome=WorkflowEventOutcome.REVIEW_PENDING,
        ),
        lease,
        now=observed_at,
    )
    return RecordReference(
        entity_id=review_case.review_id,
        revision_id=review_case.review_revision.revision_id,
        content_hash=result.artifact_hash,
    )


def _derive_assessment(
    ledger: WorkflowLedger,
    lease: LeaseToken,
    work_item: PreparationWorkItem,
) -> tuple[
    RecordReference,
    tuple[str, ...],
    tuple[DomainReviewSummary, ...],
    tuple[ReviewAction, ...],
]:
    scope = work_item.scope
    result_key = _work_item_result_key(work_item)
    result_spec = _result_spec_reference(ledger, scope)
    source_inventory = _reference_for_operation(
        ledger, scope, "operation:derive-source-inventory"
    )
    evidence_bundle = _reference_for_operation(
        ledger, scope, "operation:freeze-evidence-bundle"
    )
    bundle_payload = json.loads(ledger.artifacts.read(evidence_bundle.content_hash))
    disposition_payload = json.loads(
        ledger.artifacts.read(
            RecordReference.model_validate(bundle_payload["disposition"]).content_hash
        )
    )
    sq_answers = _reference_for_operation(
        ledger, scope, "operation:submit-sq-answers"
    )
    sq_payload = json.loads(ledger.artifacts.read(sq_answers.content_hash))
    evaluation = LogicEvaluator(load_logic_pack(_logic_pack_path())).evaluate(
        EvaluationRequest(
            answers={
                item["question_id"]: item["answer"]
                for item in sq_payload["answers"]
            },
            assessor_inputs=sq_payload.get("assessor_inputs", {}),
        )
    )
    observed_at = datetime.now(UTC)
    answer_dependency = Dependency(
        **sq_answers.model_dump(),
        role="dependency:sq-answer",
    )
    judgments: list[RecordReference] = []
    for domain_id, judgment_level in evaluation.domain_judgments.items():
        domain_slug = domain_id.removeprefix("domain:")
        trace = DecisionTrace(
            entity_id=f"decision-trace:{result_key}-{domain_slug}",
            revision_id=_derived_revision_id(
                f"decision-trace-{result_key}-{domain_slug}",
                work_item.dependency_fingerprint,
            ),
            actor=_actor("application"),
            observed_at=observed_at,
            active_question_ids=evaluation.active_question_ids,
            inactive_question_ids=evaluation.inactive_question_ids,
            matched_rule_ids=evaluation.matched_rule_ids,
            resulting_judgment=judgment_level,
        )
        trace_ref = _commit_derived_revision(
            ledger,
            lease,
            scope=scope,
            operation="operation:derive-decision-trace",
            operation_key=f"idempotency:derive-trace-{result_key}-{domain_slug}",
            record=trace,
        )
        trace_dependency = Dependency(
            **trace_ref.model_dump(),
            role="dependency:decision-trace",
        )
        judgment = AlgorithmicJudgmentRevision(
            entity_id=f"judgment:{result_key}-{domain_slug}",
            revision_id=_derived_revision_id(
                f"judgment-{result_key}-{domain_slug}",
                work_item.dependency_fingerprint,
            ),
            actor=_actor("application"),
            observed_at=observed_at,
            dependencies=(answer_dependency, trace_dependency),
            domain_id=domain_id,
            judgment=judgment_level,
            answer_revisions=(sq_answers,),
            decision_trace=trace_ref,
        )
        judgments.append(
            _commit_derived_revision(
                ledger,
                lease,
                scope=scope,
                operation="operation:derive-judgment",
                operation_key=(
                    f"idempotency:derive-judgment-{result_key}-{domain_slug}"
                ),
                record=judgment,
            )
        )
    dependencies = (
        Dependency(**result_spec.model_dump(), role="dependency:result-spec"),
        Dependency(
            **source_inventory.model_dump(),
            role="dependency:source-inventory",
        ),
        Dependency(
            **evidence_bundle.model_dump(),
            role="dependency:evidence-bundle",
        ),
        answer_dependency,
        *(
            Dependency(
                **judgment.model_dump(),
                role="dependency:algorithmic-judgment",
            )
            for judgment in judgments
        ),
    )
    assessment = AssessmentRevision(
        entity_id=f"assessment:{result_key}",
        revision_id=_derived_revision_id(
            f"assessment-{result_key}",
            work_item.dependency_fingerprint,
        ),
        actor=_actor("application"),
        observed_at=observed_at,
        dependencies=dependencies,
        result_spec=result_spec,
        source_inventory=source_inventory,
        evidence_bundles=(evidence_bundle,),
        answers=(sq_answers,),
        judgments=tuple(judgments),
    )
    assessment_ref = _commit_derived_revision(
        ledger,
        lease,
        scope=scope,
        operation="operation:derive-assessment-record",
        operation_key=f"idempotency:derive-assessment-record-{result_key}",
        record=assessment,
    )
    domain_names = {
        "domain:randomization": "Bias arising from the randomization process",
        "domain:deviations": "Bias due to deviations from intended interventions",
        "domain:missing": "Bias due to missing outcome data",
        "domain:measurement": "Bias in measurement of the outcome",
        "domain:selection": "Bias in selection of the reported result",
    }
    answers_by_id = {
        answer["question_id"]: answer for answer in sq_payload["answers"]
    }
    guidance_by_id = {
        item.logic_element_id: item.text
        for item in load_guidance_pack(_guidance_pack_path()).items
    }
    domain_summaries = []
    review_actions = []
    accepted_contradiction_claims = {
        claim_id
        for item in disposition_payload["dispositions"]
        if item["kind"] == "accepted_contradicting"
        for claim_id in item.get("claim_ids", ())
    }
    source_conflict_claims = {
        claim_id
        for conflict in bundle_payload["conflicts"]
        for claim_id in conflict
    }
    elevated_visual_questions: set[str] = set()
    claim_question_ids: dict[str, set[str]] = {}
    references_by_entity: dict[str, RecordReference] = {}
    for item in bundle_payload["items"]:
        reference = RecordReference.model_validate(item)
        references_by_entity[reference.entity_id] = reference
        payload = json.loads(ledger.artifacts.read(reference.content_hash))
        if payload.get("review_required"):
            elevated_visual_questions.update(payload.get("decision_critical", ()))
        if sq_id := payload.get("sq_id"):
            claim_ids = set(payload.get("evidence_claim_ids", ()))
            for considered in payload.get("considered_items", ()):
                considered_reference = RecordReference.model_validate(considered)
                considered_payload = json.loads(
                    ledger.artifacts.read(considered_reference.content_hash)
                )
                if item_id := considered_payload.get("item_id"):
                    claim_ids.add(item_id)
            for claim_id in claim_ids:
                claim_question_ids.setdefault(claim_id, set()).add(sq_id)
    for question_id, answer in answers_by_id.items():
        for claim_id in answer.get("evidence_claim_ids", ()):
            claim_question_ids.setdefault(claim_id, set()).add(question_id)
    judgment_override_domains: set[str] = set()
    for override_reference in assessment.judgment_overrides:
        override_payload = json.loads(
            ledger.artifacts.read(override_reference.content_hash)
        )
        judgment_reference = RecordReference.model_validate(
            override_payload["judgment_revision"]
        )
        judgment_payload = json.loads(
            ledger.artifacts.read(judgment_reference.content_hash)
        )
        judgment_override_domains.add(judgment_payload["domain_id"])
    for domain_id, judgment_level in evaluation.domain_judgments.items():
        domain_key = domain_id.removeprefix("domain:")
        active_questions = tuple(
            DomainQuestionSummary(
                sq_id=question_id,
                guidance=guidance_by_id[question_id],
                answer=answers_by_id[question_id]["answer"].replace("_", " ").title(),
                rationale=answers_by_id[question_id]["rationale"],
                evidence_count=sum(
                    question_id in question_ids
                    for question_ids in claim_question_ids.values()
                ),
            )
            for question_id in evaluation.active_question_ids
            if question_id.startswith(f"sq:{domain_key}:")
        )
        judgment_display = judgment_level.value.replace("_", " ").title()
        domain_summaries.append(
            DomainReviewSummary(
                domain_id=domain_id,
                full_name=domain_names[domain_id],
                judgment=judgment_display,
                active_sq_count=len(active_questions),
                evidence_count=sum(
                    question.evidence_count for question in active_questions
                ),
                coverage=bundle_payload["coverage_state"].replace("_", " ").title(),
                deterministic_basis=(
                    "The pinned Logic pack maps the active answers to "
                    f"{judgment_display}."
                ),
                active_questions=active_questions,
            )
        )
        domain_question_ids = {question.sq_id for question in active_questions}
        review_actions.append(
            ReviewAction(
                action_id=(
                    "review-action:domain-"
                    f"{domain_id.removeprefix('domain:')}"
                ),
                kind=ActionKind.DOMAIN_REVIEW,
                domain_id=domain_id,
                title=f"Review {domain_names[domain_id]}",
                judgment_override=domain_id in judgment_override_domains,
            )
        )
        for question_id in sorted(domain_question_ids):
            question_claims = {
                claim_id
                for claim_id, question_ids in claim_question_ids.items()
                if question_id in question_ids
            }
            contradiction_claims = (
                question_claims & accepted_contradiction_claims
            )
            conflict_claims = question_claims & source_conflict_claims
            influential_project_rule = bool(
                answers_by_id[question_id].get("project_rule_ids")
                or answers_by_id[question_id].get("project_rules")
            )
            flags = (
                contradiction_claims,
                conflict_claims,
                question_id in elevated_visual_questions,
                answers_by_id[question_id]["answer"] == "no_information",
                influential_project_rule,
            )
            if any(flags):
                linked_claim_id = next(
                    iter(sorted(contradiction_claims | conflict_claims)),
                    None,
                )
                review_actions.append(
                    ReviewAction(
                        action_id=(
                            "review-action:inspect-"
                            f"{question_id.removeprefix('sq:').replace(':', '-')}"
                        ),
                        kind=ActionKind.INSPECT_FINDING,
                        domain_id=domain_id,
                        sq_id=question_id,
                        title=f"Inspect {guidance_by_id[question_id]}",
                        evidence_claim=(
                            references_by_entity.get(linked_claim_id)
                            if linked_claim_id is not None
                            else None
                        ),
                        accepted_contradiction=bool(contradiction_claims),
                        source_conflict=bool(conflict_claims),
                        elevated_visual_transcription=(
                            question_id in elevated_visual_questions
                        ),
                        no_information=(
                            answers_by_id[question_id]["answer"]
                            == "no_information"
                        ),
                        influential_project_rule=influential_project_rule,
                    )
                )
    scoped_claims = set(claim_question_ids)
    unscoped_contradictions = accepted_contradiction_claims - scoped_claims
    unscoped_conflicts = source_conflict_claims - scoped_claims
    if unscoped_contradictions or unscoped_conflicts:
        review_actions.append(
            ReviewAction(
                action_id="review-action:inspect-result-evidence",
                kind=ActionKind.INSPECT_FINDING,
                title="Inspect Result-level contradictory or conflicting evidence",
                accepted_contradiction=bool(unscoped_contradictions),
                source_conflict=bool(unscoped_conflicts),
            )
        )
    if bundle_payload["coverage_limitations"]:
        review_actions.append(
            ReviewAction(
                action_id="review-action:coverage-limitation",
                kind=ActionKind.ACKNOWLEDGE_LIMITATION,
                title="Acknowledge material evidence coverage limitations",
                finding_requirement=FindingRequirement.ACKNOWLEDGE,
                finding_id="finding:evidence-coverage",
                consequence="Result sign-off remains blocked until acknowledgment.",
                affected_scope=tuple(evaluation.domain_judgments),
            )
        )
    return (
        assessment_ref,
        tuple(evaluation.domain_judgments),
        tuple(domain_summaries),
        tuple(review_actions),
    )


def _logic_pack_path() -> Path:
    package_path = (
        Path(__file__).resolve().parents[1]
        / "packs"
        / "logic"
        / "rob2-parallel-assignment-2019.1.yaml"
    )
    if package_path.is_file():
        return package_path
    return (
        Path(__file__).resolve().parents[3]
        / "packs"
        / "logic"
        / "rob2-parallel-assignment-2019.1.yaml"
    )


def _guidance_pack_path() -> Path:
    package_path = (
        Path(__file__).resolve().parents[1]
        / "packs"
        / "guidance"
        / "rob2-parallel-assignment-en-2019.1.yaml"
    )
    if package_path.is_file():
        return package_path
    return (
        Path(__file__).resolve().parents[3]
        / "packs"
        / "guidance"
        / "rob2-parallel-assignment-en-2019.1.yaml"
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _candidate_identifier(unit_id: str) -> str:
    return _identifier("candidate", unit_id)


def _archive_pins() -> dict[str, bytes]:
    package_root = Path(__file__).resolve().parents[1]
    repository_root = Path(__file__).resolve().parents[3]
    pins: dict[str, bytes] = {}
    for directory_name in ("schemas", "packs"):
        candidates = (
            package_root / directory_name,
            repository_root / directory_name,
        )
        directory = next((path for path in candidates if path.is_dir()), None)
        if directory is None:
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative = path.relative_to(directory).as_posix()
            pins[f"{directory_name}/{relative}"] = path.read_bytes()
    return pins


def _preparation_plans(
    initialization: ProjectInitialization,
) -> tuple[PreparationPlan, ...]:
    steps = (
        (
            "source-classification",
            "submit-source-classification",
            SubmissionKind.SOURCE_CLASSIFICATION,
        ),
        ("result-resolution", "submit-result-resolution", SubmissionKind.RESULT_RESOLUTION),
        (
            "source-inventory",
            "derive-source-inventory",
            SubmissionKind.SOURCE_INVENTORY,
        ),
        (
            "evidence-dispositions",
            "submit-evidence-dispositions",
            SubmissionKind.EVIDENCE_DISPOSITIONS,
        ),
        ("visual-transcription", "submit-visual-transcription", SubmissionKind.VISUAL_INSPECTION),
        ("evidence-bundle", "freeze-evidence-bundle", SubmissionKind.EVIDENCE_BUNDLE),
        ("sq-answers", "submit-sq-answers", SubmissionKind.SQ_ANSWERS),
        ("assessment", "derive-assessment", SubmissionKind.ASSESSMENT),
    )
    legacy = tuple(
        PreparationPlan(
            scope=f"preparation:{trial.trial_id.removeprefix('trial:')}",
            trial_id=trial.trial_id,
            steps=tuple(
                PreparationStep(
                    step_id=f"step:{name}",
                    operation=f"operation:{operation}",
                    checkpoint=f"checkpoint:{name}",
                    submission_kind=kind,
                )
                for name, operation, kind in steps
            ),
        )
        for trial in initialization.trials
        if trial.status == "inventory_ready"
        and not any(
            spec.result.trial_id == trial.trial_id
            for spec in initialization.result_specs
        )
    )
    declared = tuple(
        PreparationPlan(
            scope=f"preparation:{spec.result.result_id.removeprefix('result:')}",
            trial_id=spec.result.trial_id,
            result_id=spec.result.result_id,
            steps=tuple(
                PreparationStep(
                    step_id=f"step:{name}",
                    operation=f"operation:{operation}",
                    checkpoint=f"checkpoint:{name}",
                    submission_kind=kind,
                )
                for name, operation, kind in steps
                if kind is not SubmissionKind.RESULT_RESOLUTION
            ),
        )
        for spec in initialization.result_specs
        if next(
            trial
            for trial in initialization.trials
            if trial.trial_id == spec.result.trial_id
        ).status
        == "inventory_ready"
    )
    return (*legacy, *declared)


def _stored_plans(ledger: WorkflowLedger) -> tuple[PreparationPlan, ...]:
    first = ledger.events()[0]
    payload = json.loads(ledger.artifacts.read(first.output_revision_hashes[0]))
    return tuple(
        PreparationPlan.model_validate(item)
        for item in payload.get("preparation_plans", ())
    )


def _coordinator(
    ledger: WorkflowLedger,
    plans: tuple[PreparationPlan, ...],
    *,
    writable: bool = False,
    actor: Actor | None = None,
) -> AutonomousPreparation:
    if writable:
        now = datetime.now(UTC)
        lease = ledger.acquire_lease(
            "owner:application",
            now,
            timedelta(minutes=5),
        )
    else:
        lease = LeaseToken(
            owner_id="owner:read-only",
            fencing_token=0,
            expires_at=datetime.now(UTC),
        )
    return AutonomousPreparation(
        ledger,
        lease,
        actor or _actor("application"),
        plans,
    )


def _available_work_items(
    ledger: WorkflowLedger, plans: tuple[PreparationPlan, ...]
) -> tuple[PreparationWorkItem, ...]:
    return _coordinator(ledger, plans).continue_preparation() if plans else ()


def _work_item_result_key(work_item: PreparationWorkItem) -> str:
    return (work_item.result_id or work_item.trial_id).split(":", 1)[1]


def _work_item_payload(work_item: PreparationWorkItem) -> dict[str, Any]:
    tool_name = next(
        name
        for name, kind in SUBMISSION_KINDS.items()
        if kind is work_item.submission_kind
    )
    issued_identifiers: dict[str, str] = {}
    trial_slug = work_item.trial_id.removeprefix("trial:")
    if work_item.submission_kind is SubmissionKind.RESULT_RESOLUTION:
        issued_identifiers["result_id"] = work_item.result_id or f"result:{trial_slug}"
    elif work_item.submission_kind is SubmissionKind.EVIDENCE_BUNDLE:
        issued_identifiers["bundle_id"] = f"bundle:{_work_item_result_key(work_item)}"
    elif work_item.submission_kind is SubmissionKind.VISUAL_INSPECTION:
        issued_identifiers["visual_candidate_source"] = "inspect_visual_candidate"
    payload = {
        **work_item.model_dump(mode="json"),
        "permitted_tool": tool_name,
        "contract_version": CONTRACT_VERSION,
        "issued_identifiers": issued_identifiers,
    }
    if work_item.submission_kind is SubmissionKind.SQ_ANSWERS:
        logic = load_logic_pack(_logic_pack_path())
        guidance = load_guidance_pack(_guidance_pack_path())
        validate_guidance_compatibility(logic, guidance)
        wording = {
            item.logic_element_id: item.text for item in guidance.items
        }
        payload["sq_context"] = [
            {"sq_id": question.id, "guidance": wording[question.id]}
            for question in logic.questions
        ]
    return payload


def _event_envelope(
    project_id: str,
    event: WorkflowEvent,
    tool_name: str,
    payload: bytes,
    ledger: WorkflowLedger,
) -> OperationEnvelope:
    expected_operation = f"operation:{tool_name.replace('_', '-')}"
    if event.operation != expected_operation:
        raise ValueError("idempotency key was already used for another operation")
    if ledger.artifacts.read(event.output_revision_hashes[0]) != payload:
        raise ValueError("idempotency key was already used with a different payload")
    return OperationEnvelope(
        operation_id=event.operation_id,
        ledger_cursor=f"ledger:{event.sequence}",
        affected_scope=(event.scope,),
        status=WorkflowStatus.COMPLETED,
        committed=True,
        next_permitted_action="action:get-next-work",
        payload={"tool": tool_name},
    )


def _identifier(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _project_identifier(root: Path) -> str:
    normalized = str(root).casefold()
    encoded = urlsafe_b64encode(normalized.encode()).decode().rstrip("=")
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"project:{encoded}.{digest}"


def _root_from_project_identifier(project_id: str) -> Path | None:
    if not project_id.startswith("project:") or "." not in project_id:
        return None
    encoded, digest = project_id.removeprefix("project:").rsplit(".", 1)
    try:
        padding = "=" * (-len(encoded) % 4)
        normalized = urlsafe_b64decode(encoded + padding).decode()
    except (UnicodeDecodeError, ValueError):
        return None
    if hashlib.sha256(normalized.encode()).hexdigest()[:16] != digest:
        return None
    return Path(normalized)


def _actor(component: str) -> Actor:
    return Actor(
        actor_id=f"system:{component}",
        kind="system",
        display_name=component,
        software_name="rob2-kit",
        software_version="0.1.0",
    )


def _submission_actor(idempotency_key: str) -> Actor:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
    return Actor(
        actor_id=f"agent:submission-{digest}",
        kind="agent",
        display_name="Host agent submission",
        software_name="rob2-kit",
        software_version="0.1.0",
    )
