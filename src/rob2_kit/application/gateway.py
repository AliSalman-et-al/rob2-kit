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
from rob2_kit.domain.revisions import Actor
from rob2_kit.evidence.search import EvidenceSearchIndex, SearchQuery
from rob2_kit.evidence.visual import VisualInspectionQueue
from rob2_kit.ingestion.project import ProjectInitialization
from rob2_kit.ingestion.project import initialize_project as ingest_project
from rob2_kit.review.handoff import ReviewHandoff, ReviewWaitOutcome
from rob2_kit.review.service import ReviewCase, ReviewService
from rob2_kit.review.web import ReviewWebConfig
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)

CONTRACT_VERSION = "1.0.0"
STATIC_TOOL_NAMES = (
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
)
MUTATION_TOOLS = frozenset(
    {
        "submit_source_classification",
        "submit_result_resolution",
        "submit_evidence_dispositions",
        "submit_visual_transcription",
        "freeze_evidence_bundle",
        "submit_sq_answers",
    }
)


class ApplicationGateway:
    """Expose bounded application operations without transport-specific types."""

    def __init__(self) -> None:
        self._projects: dict[str, Path] = {}

    def initialize_project(self, project_root: Path, *, authorized: bool) -> OperationEnvelope:
        if not authorized:
            raise PermissionError("project initialization requires explicit authorization")
        root = project_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        state_dir = root / ".rob2"
        state_dir.mkdir(exist_ok=True)
        project_id = _project_identifier(root)
        self._projects[project_id] = root
        ledger = _ledger(root)
        existing = ledger.events()
        if not existing:
            initialization = ingest_project(root, actor=_actor("initializer"))
            EvidenceSearchIndex(state_dir / "evidence.sqlite3").replace_units(())
            now = datetime.now(UTC)
            lease = ledger.acquire_lease(
                "interface:initializer", now, timedelta(minutes=1)
            )
            payload = json.dumps(
                {
                    "project_id": project_id,
                    "root": str(root),
                    "authorized": True,
                    "initialization": initialization.model_dump(mode="json"),
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
                    outcome=WorkflowEventOutcome.WORK_REQUIRED,
                ),
                lease,
            )
            existing = ledger.events()
        work_item = _work_item(ledger)
        event = existing[0]
        return OperationEnvelope(
            operation_id=event.operation_id,
            ledger_cursor=f"ledger:{len(existing)}",
            affected_scope=(project_id,),
            status=WorkflowStatus.WORK_REQUIRED,
            committed=True,
            next_permitted_action="action:get-next-work",
            payload={
                "project_id": project_id,
                "contract_version": CONTRACT_VERSION,
                "work_item": work_item,
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

    def expert_command(self, project_root: Path, command: str) -> dict[str, Any]:
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
        if command in {"report", "export", "archive"}:
            return {
                "command": command,
                "status": WorkflowStatus.WORK_REQUIRED,
                "condition": "condition:projection-owned-by-issue-24",
                "committed": False,
            }
        raise ValueError(f"unknown expert command {command!r}")

    def register_review_case(self, project_root: Path, review_case: ReviewCase) -> None:
        """Persist the immutable review input needed for cross-process handoff."""
        self.resume_project(project_root)
        path = project_root.resolve() / ".rob2" / "review-case.json"
        path.write_text(review_case.model_dump_json(indent=2), encoding="utf-8")

    def call(
        self,
        tool_name: str,
        project_id: str,
        *,
        arguments: dict[str, Any] | None = None,
        mutation_context: dict[str, Any] | MutationContext | None = None,
    ) -> OperationEnvelope:
        if tool_name not in STATIC_TOOL_NAMES or tool_name == "initialize_project":
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
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|search-evidence"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload=page.model_dump(mode="json"),
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
            page = VisualInspectionQueue(()).page(
                limit=int((arguments or {}).get("limit", 1)),
                cursor=(arguments or {}).get("cursor"),
            )
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|inspect-visual"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.COMPLETED,
                committed=False,
                payload=page.model_dump(mode="json"),
            )
        if tool_name in {"continue_preparation", "get_next_work"}:
            latest_status = WorkflowStatus(ledger.events()[-1].outcome.value)
            if latest_status not in {
                WorkflowStatus.WORK_REQUIRED,
                WorkflowStatus.COMPLETED,
            }:
                return self._project_status(project_id, ledger)
            work_item = _work_item(ledger)
            return OperationEnvelope(
                operation_id=_identifier("operation", f"{project_id}|{tool_name}"),
                ledger_cursor=f"ledger:{len(ledger.events())}",
                affected_scope=(project_id,),
                status=WorkflowStatus.WORK_REQUIRED,
                committed=False,
                next_permitted_action="action:submit-work",
                payload={"work_item": work_item},
            )
        if tool_name == "wait_for_review":
            return self._wait_for_review(
                project_id, ledger, root, arguments or {}
            )
        if tool_name == "review_queue":
            handoff = self._review_handoff(root, ledger)
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
            handoff = self._review_handoff(root, ledger)
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
        if tool_name in MUTATION_TOOLS:
            if mutation_context is None:
                raise ValueError("mutation context is required")
            context = MutationContext.model_validate(mutation_context)
            prior = next(
                (
                    event
                    for event in ledger.events()
                    if event.operation_key == context.idempotency_key
                ),
                None,
            )
            if prior is not None:
                expected_operation = f"operation:{tool_name.replace('_', '-')}"
                if prior.operation != expected_operation:
                    raise ValueError("idempotency key was already used for another operation")
                return OperationEnvelope(
                    operation_id=prior.operation_id,
                    ledger_cursor=f"ledger:{prior.sequence}",
                    affected_scope=(project_id,),
                    status=WorkflowStatus.COMPLETED,
                    committed=True,
                    next_permitted_action="action:get-next-work",
                    payload={"tool": tool_name},
                )
            expected = _work_item(ledger)
            if context.work_item_id != expected["work_item_id"]:
                raise ValueError("work item identifier was not issued by the engine")
            if context.contract_version != CONTRACT_VERSION:
                raise ValueError("unsupported application contract version")
            if context.expected_dependency_fingerprint != expected["dependency_fingerprint"]:
                raise ValueError("work item dependency fingerprint is stale")
            return self._commit(tool_name, project_id, ledger, context, arguments or {})
        return OperationEnvelope(
            operation_id=_identifier("operation", f"{project_id}|{tool_name}"),
            ledger_cursor=f"ledger:{len(ledger.events())}",
            affected_scope=(project_id,),
            status=WorkflowStatus.WORK_REQUIRED,
            committed=False,
            next_permitted_action="action:get-next-work",
            payload={"tool": tool_name, "arguments": arguments or {}},
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
        result = self._review_handoff(root, ledger).wait_for_review(
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
        self, root: Path, ledger: WorkflowLedger
    ) -> ReviewHandoff:
        case_path = root / ".rob2" / "review-case.json"
        if not case_path.is_file():
            raise ValueError("no durable review case is registered for this project")
        review_case = ReviewCase.model_validate_json(
            case_path.read_text(encoding="utf-8")
        )
        now = datetime.now(UTC)
        lease = ledger.acquire_lease(
            "owner:review-gui",
            now,
            timedelta(minutes=30),
            owner_is_dead=lambda _owner: True,
        )
        service = ReviewService(ledger, lease, review_case)
        config = ReviewWebConfig(
            project_root=root,
            session_lifetime=timedelta(minutes=30),
            allowed_origin="http://127.0.0.1:0",
        )
        return ReviewHandoff(service, config)

    def _commit(
        self,
        tool_name: str,
        project_id: str,
        ledger: WorkflowLedger,
        context: MutationContext,
        arguments: dict[str, Any],
    ) -> OperationEnvelope:
        dependencies = _current_dependencies(ledger)
        normalized = SUBMISSION_ARGUMENTS[tool_name].validate_python(arguments)
        payload = normalized.model_dump_json().encode()
        digest = hashlib.sha256(
            f"{tool_name}|{context.idempotency_key}".encode()
        ).hexdigest()[:24]
        now = datetime.now(UTC)
        lease = ledger.acquire_lease(
            "interface:mutation",
            now,
            timedelta(minutes=1),
            owner_is_dead=lambda _owner: True,
        )
        result = ledger.commit(
            Transition(
                scope=project_id,
                operation=f"operation:{tool_name.replace('_', '-')}",
                operation_key=context.idempotency_key,
                actor=_actor("host-interface"),
                observed_at=now,
                entity_id=f"submission:{digest}",
                revision_id=f"revision:{digest}",
                artifact=payload,
                artifact_media_type="application/json",
                dependencies=dependencies,
                expected_dependency_fingerprint=context.expected_dependency_fingerprint,
                checkpoint=f"checkpoint:{tool_name.replace('_', '-')}",
                outcome=WorkflowEventOutcome.COMPLETED,
            ),
            lease,
        )
        return OperationEnvelope(
            operation_id=result.operation_id,
            ledger_cursor=f"ledger:{result.sequence}",
            affected_scope=(project_id,),
            status=WorkflowStatus.COMPLETED,
            committed=True,
            next_permitted_action="action:get-next-work",
            payload={"tool": tool_name},
        )


def _ledger(root: Path) -> WorkflowLedger:
    state = root / ".rob2"
    return WorkflowLedger(state / "ledger.sqlite3", ArtifactStore(state / "artifacts"))


def _current_dependencies(ledger: WorkflowLedger) -> tuple[DependencyInput, ...]:
    revisions = {item.revision_id: item for item in ledger.current_revisions()}
    return tuple(
        DependencyInput(
            entity_id=event.entity_id,
            revision_id=event.revision_id,
            role="dependency:workflow-state",
            content_hash=revisions[event.revision_id].artifact_hash,
        )
        for event in ledger.events()
        if event.revision_id in revisions
    )


def _work_item(ledger: WorkflowLedger) -> dict[str, str]:
    fingerprint = dependency_fingerprint(_current_dependencies(ledger))
    return {
        "work_item_id": _identifier("work-item", fingerprint),
        "dependency_fingerprint": fingerprint,
    }


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
