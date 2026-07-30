"""Researcher-facing Companion workspace projections derived from durable state."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel
from rob2_kit.storage.ledger import WorkflowEventOutcome, WorkflowLedger


class WorkspaceStage(StrEnum):
    READY = "ready"
    PREPARE = "prepare"
    REVIEW = "review"
    COMPLETE = "complete"


class SourcePreview(FrozenModel):
    source_id: str
    filename: str
    roles: tuple[str, ...]
    page_count: int
    custody_status: str
    parse_status: str
    preview_available: bool


class ResultCard(FrozenModel):
    result_id: str
    trial_id: str
    label: str
    identity: tuple[tuple[str, str], ...]
    sources: tuple[SourcePreview, ...] = ()
    column: str = "queue"
    checkpoint: str | None = None
    outcome: str | None = None
    reason: str | None = None
    next_action: str | None = None
    judgment: str | None = None


class WorkspaceProjection(FrozenModel):
    project_name: str
    stage: WorkspaceStage
    results: tuple[ResultCard, ...] = Field(min_length=1)
    selected_result_id: str
    agent_prompt: str
    connection_state: str
    review_locked: bool


def project_workspace(
    ledger: WorkflowLedger,
    *,
    connection_state: str,
    selected_result_id: str | None = None,
) -> WorkspaceProjection | None:
    """Join the current Companion view from ledger events and immutable artifacts."""
    events = ledger.events()
    initialization_event = next(
        (event for event in events if event.operation == "operation:initialize-project"),
        None,
    )
    if initialization_event is None:
        return None
    payload = json.loads(ledger.artifacts.read(initialization_event.output_revision_hashes[0]))
    initialization = payload["initialization"]
    manifest = initialization["manifest"]
    plans = {plan["trial_id"]: plan for plan in payload.get("preparation_plans", ())}
    results = tuple(
        _result_card(ledger, trial, plans.get(trial["trial_id"]), events)
        for trial in initialization["trials"]
    )
    selected = (
        selected_result_id
        if selected_result_id in {item.result_id for item in results}
        else None
    )
    selected = selected or results[0].result_id
    all_terminal = all(item.outcome is not None for item in results)
    any_started = any(
        item.column == "processing"
        or item.outcome in {"draft_ready", "preparation_incomplete"}
        for item in results
    )
    any_reviewable = any(item.outcome == "draft_ready" for item in results)
    stage = (
        WorkspaceStage.REVIEW
        if all_terminal and any_reviewable
        else WorkspaceStage.PREPARE
        if any_started
        else WorkspaceStage.READY
    )
    root = manifest["input_root"]
    action = "Resume" if any_started else "Start"
    prompt = (
        f"{action} uninterrupted autonomous preparation for project "
        f"“{manifest['project_name']}” at {root}. Use continue_preparation until every "
        "requested Trial reaches a terminal Preparation outcome; do not ask mid-preparation "
        "questions."
    )
    return WorkspaceProjection(
        project_name=manifest["project_name"],
        stage=stage,
        results=results,
        selected_result_id=selected,
        agent_prompt=prompt,
        connection_state=connection_state,
        review_locked=not all_terminal,
    )


def _result_card(
    ledger: WorkflowLedger,
    trial: dict[str, Any],
    plan: dict[str, Any] | None,
    events: tuple[Any, ...],
) -> ResultCard:
    trial_id = str(trial["trial_id"])
    scope = (
        str(plan["scope"])
        if plan is not None
        else f"preparation:{trial_id.removeprefix('trial:')}"
    )
    plan_operations = {
        step["operation"] for step in (plan or {}).get("steps", ())
    }
    scope_events = tuple(
        event
        for event in events
        if event.scope == scope
        and (
            event.operation in plan_operations
            or event.outcome
            in {
                WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
                WorkflowEventOutcome.RETRYABLE_INTERRUPTION,
            }
        )
    )
    result_payload = _operation_payload(ledger, scope_events, "operation:submit-result-resolution")
    result = result_payload.get("result", {}) if result_payload else {}
    result_id = str(result.get("result_id", f"result:{trial_id.removeprefix('trial:')}"))
    identity = _identity(result, trial_id)
    label = _result_label(result, trial_id)
    outcome, reason = _outcome(ledger, scope_events)
    if trial.get("status") == "trial_failed":
        failure = trial.get("failure") or {}
        outcome = "trial_failed"
        reason = str(failure.get("detail", "Required Trial material could not be prepared."))
    checkpoint = next(
        (event.checkpoint for event in reversed(scope_events) if event.checkpoint is not None),
        None,
    )
    column = "review_queue" if outcome is not None else "processing" if scope_events else "queue"
    return ResultCard(
        result_id=result_id,
        trial_id=trial_id,
        label=label,
        identity=identity,
        sources=tuple(
            _source_preview(source)
            for source in trial["inventory"]["sources"]
            if source.get("availability") == "acquired"
        ),
        column=column,
        checkpoint=checkpoint,
        outcome=outcome,
        reason=reason,
        next_action=_next_action(outcome, reason),
        judgment="Assessment committed" if outcome == "draft_ready" else None,
    )


def _operation_payload(
    ledger: WorkflowLedger, events: tuple[Any, ...], operation: str
) -> dict[str, Any] | None:
    event = next((item for item in reversed(events) if item.operation == operation), None)
    return (
        json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
        if event is not None
        else None
    )


def _outcome(
    ledger: WorkflowLedger, events: tuple[Any, ...]
) -> tuple[str | None, str | None]:
    event = next(
        (
            item
            for item in reversed(events)
            if item.outcome is WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED
        ),
        None,
    )
    if event is None:
        interruption = next(
            (
                item
                for item in reversed(events)
                if item.outcome is WorkflowEventOutcome.RETRYABLE_INTERRUPTION
            ),
            None,
        )
        reason = (
            "Preparation was interrupted safely; committed work is preserved."
            if interruption
            else None
        )
        return None, reason
    payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
    return str(payload["outcome"]), payload.get("detail")


def _source_preview(source: dict[str, Any]) -> SourcePreview:
    coverage = source.get("coverage") or ()
    roles = tuple(str(role).replace("_", " ") for role in source.get("roles") or ())
    return SourcePreview(
        source_id=str(source["source_id"]),
        filename=str(source["title"]),
        roles=roles,
        page_count=len(coverage),
        custody_status=str(source["availability"]).replace("_", " "),
        parse_status=str(source["processing"]).replace("_", " "),
        preview_available=bool(
            source.get("artifact_hash")
            and str(source.get("title", "")).lower().endswith(".pdf")
        ),
    )


def secured_source_pdf(ledger: WorkflowLedger, source_id: str) -> bytes | None:
    """Return acquired PDF bytes for a source issued by this project."""
    initialization_event = next(
        (
            event
            for event in ledger.events()
            if event.operation == "operation:initialize-project"
        ),
        None,
    )
    if initialization_event is None:
        return None
    payload = json.loads(ledger.artifacts.read(initialization_event.output_revision_hashes[0]))
    for trial in payload["initialization"]["trials"]:
        for source in trial["inventory"]["sources"]:
            if (
                source["source_id"] == source_id
                and source.get("availability") == "acquired"
                and source.get("artifact_hash")
                and str(source.get("title", "")).lower().endswith(".pdf")
            ):
                return ledger.artifacts.read(source["artifact_hash"])
    return None


def _identity(result: dict[str, Any], trial_id: str) -> tuple[tuple[str, str], ...]:
    if not result:
        return (("Trial", trial_id), ("Result", "Pending exact Result resolution"))
    comparison = result.get("comparison") or {}
    return (
        ("Trial", trial_id),
        ("Randomization", str(result.get("randomization_id", ""))),
        ("Outcome", str(result.get("outcome_construct", ""))),
        ("Measurement", str(result.get("measurement_instrument", ""))),
        ("Time point", str(result.get("time_point", ""))),
        (
            "Comparison",
            f"{comparison.get('experimental_arm_id', '')} vs "
            f"{comparison.get('comparator_arm_id', '')}",
        ),
        ("Effect", str(result.get("effect_of_interest", ""))),
        ("Analysis population", str(result.get("analysis_population", ""))),
        ("Analysis model", str(result.get("analysis_model", ""))),
        ("Measure", str(result.get("effect_measure", ""))),
        ("Source locator", str(result.get("source_locator", ""))),
    )


def _result_label(result: dict[str, Any], trial_id: str) -> str:
    if not result:
        return f"{trial_id} · Result identity pending"
    return (
        f"{trial_id} · {result.get('outcome_construct', 'Result')} · "
        f"{result.get('time_point', 'time point pending')}"
    )


def _next_action(outcome: str | None, reason: str | None) -> str | None:
    if outcome == "preparation_incomplete":
        return "Resolve the material preparation gap, then resume preparation."
    if outcome == "trial_failed":
        return "Repair or replace the required source or Result information."
    if outcome is None and reason:
        return "Reconnect the agent and resume from the last durable checkpoint."
    return None
