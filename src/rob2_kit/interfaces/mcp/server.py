"""Compact, repair-oriented MCP boundary for the RoB 2 application."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, ResourceLink, TextContent, ToolAnnotations
from pydantic import ValidationError

from rob2_kit.application import (
    AuthorizedSourceRoot,
    CaptureRequest,
    IntakePlanEntry,
    PreflightRequest,
    capture_batch,
    inspect_candidate_sources,
    preflight_sources,
    save_intake_plan,
)
from rob2_kit.application._state import read_json
from rob2_kit.application.contracts import (
    EvidenceReference,
    RecordReference,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    TransitionReference,
)
from rob2_kit.application.domain_runtime import validate_domain_runtime
from rob2_kit.application.domains import commit_domain_judgment
from rob2_kit.application.evidence import list_sources, resolve_evidence, source_records
from rob2_kit.application.evidence_runtime import retrieve_agent_evidence
from rob2_kit.application.finalization_runtime import finalize_with_archive
from rob2_kit.application.proposal_runtime import (
    approve_proposal,
    read_review_provenance,
    submit_proposal,
)
from rob2_kit.application.registry_runtime import (
    ensure_registry_snapshot,
    registry_record,
)
from rob2_kit.application.render_runtime import render_cached
from rob2_kit.application.status import current_status
from rob2_kit.application.transitions import read_transition
from rob2_kit.application.transport import (
    actionable_dump,
    annotate_handles,
    resolve_handles,
    validation_repairs,
)
from rob2_kit.application.trials import (
    TrialFinishCandidate,
    TrialFinishRequest,
    finish_trial,
    prepare_trial_finish,
)
from rob2_kit.rendering import read_render

from . import server_legacy as _legacy

PUBLIC_TOOL_NAMES = (
    "preflight_sources",
    "inspect_candidate_sources",
    "save_intake_plan",
    "capture_batch",
    "list_sources",
    "retrieve_evidence",
    "render_page",
    "save_proposal",
    "approve_batch",
    "validate_domain_judgment",
    "commit_domain_judgment",
    "prepare_trial_finish",
    "finish_trial",
    "finalize_batch",
    "read_record",
)

mcp = FastMCP("rob2-kit")
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
_MUTATION = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)
_PREFLIGHT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


def _workspace() -> str:
    return os.environ.get("ROB2_WORKSPACE", ".")


def _wire(value: object) -> dict[str, object]:
    rendered = annotate_handles(_workspace(), actionable_dump(value))
    if isinstance(rendered, dict):
        return rendered
    return {"outcome": "success", "result": rendered}


def _content(value: object) -> ToolResult:
    dumped = _wire(value)
    outcome = str(dumped.get("outcome", "success"))
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=f"{outcome}; inspect structured content for the authoritative receipt.",
            )
        ],
        structured_content=dumped,
    )


def _repair(error: Exception, *, pointer: str = "") -> ToolResult:
    if isinstance(error, ValidationError):
        return _content(validation_repairs(error, prefix=pointer))
    return _content(
        {
            "outcome": "repair",
            "repairs": [
                {"pointer": pointer, "code": "invalid", "detail": str(error)}
            ],
        }
    )


def _resolve(value: object) -> object:
    return resolve_handles(_workspace(), value)


def _source_id(value: str) -> str:
    resolved = _resolve(value)
    if isinstance(resolved, Mapping):
        source_id = resolved.get("source_id")
        if isinstance(source_id, str):
            return source_id
    if isinstance(resolved, str):
        return resolved
    raise ValueError("source_id must be a Source identity or source handle")


def _proposal_detail(reference: RecordReference) -> dict[str, object]:
    value = _legacy._detail(reference.kind.value, reference.identity)
    if reference.kind.value == "proposal_review":
        provenance = read_review_provenance(_workspace(), reference)
        if provenance is not None:
            value = {**value, "provenance": provenance}
    return value


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    return json.dumps(
        _wire(current_status(_workspace())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@mcp.resource("rob2://detail/{kind}/{identity}")
def detail_resource(kind: str, identity: str) -> str:
    reference = RecordReference(
        kind=kind,
        identity=identity,
        uri=f"rob2://detail/{kind}/{identity}",
    )
    return json.dumps(
        _wire(_proposal_detail(reference)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@mcp.resource("rob2://registry/{trial_id}")
def registry_resource(trial_id: str) -> str:
    return json.dumps(
        registry_record(_workspace(), trial_id),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@mcp.resource("rob2://render/{identity}")
def render_resource(identity: str) -> bytes:
    return read_render(_workspace(), identity)[1]


@mcp.tool(name="preflight_sources", annotations=_PREFLIGHT)
def preflight(
    roots: tuple[AuthorizedSourceRoot, ...], expected_head: str | None = None
) -> ToolResult:
    try:
        result = preflight_sources(
            _workspace(), PreflightRequest(roots=roots, expected_head=expected_head)
        )
        registry = ensure_registry_snapshot(_workspace(), result)
        return _content(
            {
                "outcome": (
                    "success" if registry.get("outcome") == "success" else "condition"
                ),
                "kind": result.kind,
                "identity": result.identity,
                "roots": result.roots,
                "candidates": [
                    item.model_dump(mode="json", exclude={"pages"})
                    for item in result.candidates
                ],
                "conditions": [
                    *result.conditions,
                    *list(registry.get("conditions", ())),
                ],
                "registry_attempts": result.registry_attempts,
                "registry_outcomes": result.registry_outcomes,
                "registry_sources": registry.get("sources", ()),
                "reference": result.reference.model_dump(mode="json"),
            }
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="inspect_candidate_sources", annotations=_READ_ONLY)
def inspect(
    candidate_identity: str, query: str | None = None, page: int | None = None
) -> ToolResult:
    try:
        result = inspect_candidate_sources(
            _workspace(), candidate_identity, query=query, page=page
        )
        return _content(
            {
                "outcome": "success",
                "candidate": result.candidate.model_dump(
                    mode="json", exclude={"pages"}
                ),
                "page": result.page,
                "text": result.text,
                "hits": result.hits,
            }
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="save_intake_plan", annotations=_MUTATION)
def save_plan(
    preflight: dict[str, Any] | str, entries: list[dict[str, Any]]
) -> ToolResult:
    try:
        reference = RecordReference.model_validate(_resolve(preflight))
        typed_entries = tuple(IntakePlanEntry.model_validate(item) for item in entries)
        return _content(
            save_intake_plan(
                _workspace(), reference, typed_entries, host_caller="host:mcp"
            )
        )
    except (TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="capture_batch", annotations=_MUTATION)
def capture(
    plan: dict[str, Any] | str,
    acknowledgment: dict[str, Any] | str,
) -> ToolResult:
    try:
        request = CaptureRequest(
            plan=RecordReference.model_validate(_resolve(plan)),
            acknowledgment=ReviewAcknowledgmentReference.model_validate(
                _resolve(acknowledgment)
            ),
        )
        result = capture_batch(_workspace(), request)
        ensure_registry_snapshot(_workspace())
        return _content(result)
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="list_sources", annotations=_READ_ONLY)
def list_trial_sources(trial_id: str) -> ToolResult:
    try:
        ensure_registry_snapshot(_workspace())
        return _content(
            {"outcome": "success", "sources": list_sources(_workspace(), trial_id)}
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="retrieve_evidence", annotations=_READ_ONLY)
def retrieve(
    trial_id: str,
    searches: list[dict[str, Any]] | None = None,
    continuations: list[dict[str, Any]] | None = None,
    page_reads: list[dict[str, Any]] | None = None,
    normal_selections: list[dict[str, Any]] | None = None,
    manual_selections: list[dict[str, Any]] | None = None,
    visual_selections: list[dict[str, Any]] | None = None,
    quote_selections: list[dict[str, Any]] | None = None,
    table_selections: list[dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> ToolResult:
    raw = {
        "trial_id": trial_id,
        "searches": searches or [],
        "continuations": continuations or [],
        "page_reads": page_reads or [],
        "normal_selections": normal_selections or [],
        "manual_selections": manual_selections or [],
        "visual_selections": visual_selections or [],
        "quote_selections": quote_selections or [],
        "table_selections": table_selections or [],
        "catalog": catalog,
    }
    try:
        ensure_registry_snapshot(_workspace())
        resolved = _resolve(raw)
        if not isinstance(resolved, Mapping):
            raise TypeError("retrieval request must be an object")
        return _content(retrieve_agent_evidence(_workspace(), resolved))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="render_page", annotations=_READ_ONLY)
def render_source_page(
    trial_id: str,
    source_id: str,
    page: int,
    region: tuple[float, float, float, float] | None = None,
    force_inline: bool = False,
) -> ToolResult:
    try:
        ensure_registry_snapshot(_workspace())
        canonical_source_id = _source_id(source_id)
        source = next(
            (
                item
                for item in source_records(_workspace(), trial_id)
                if item.id == canonical_source_id
            ),
            None,
        )
        if source is None:
            raise ValueError("source is outside the Trial inventory")
        delivery = render_cached(
            _workspace(), source, page, region, force_inline=force_inline
        )
        if delivery.condition is not None:
            return _content(delivery.condition)
        rendered = delivery.rendered
        if rendered is None:
            raise ValueError("rendering produced no page or condition")
        structured = rendered.model_dump(mode="json", exclude={"image_bytes"})
        structured.update(
            {
                "outcome": "success",
                "cached": delivery.cached,
                "inline_image_included": delivery.include_inline_image,
            }
        )
        content: list[ImageContent | ResourceLink | TextContent] = []
        if delivery.include_inline_image:
            content.append(
                ImageContent(
                    type="image",
                    data=base64.b64encode(rendered.image_bytes).decode(),
                    mimeType="image/png",
                )
            )
        content.extend(
            [
                ResourceLink(
                    type="resource_link",
                    name="rob2-render",
                    uri=f"rob2://render/{rendered.render_identity}",
                    mimeType="image/png",
                ),
                TextContent(
                    type="text",
                    text=(
                        "Cached render; use the linked immutable image resource."
                        if delivery.cached and not delivery.include_inline_image
                        else "Rendered page; the immutable image resource is linked."
                    ),
                ),
            ]
        )
        return ToolResult(content=content, structured_content=_wire(structured))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="save_proposal", annotations=_MUTATION)
def save_review(proposal: dict[str, Any]) -> ToolResult:
    try:
        resolved = _resolve(proposal)
        if not isinstance(resolved, Mapping):
            raise TypeError("Proposal must be an object")
        return _content(submit_proposal(_workspace(), resolved))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="approve_batch", annotations=_MUTATION)
def approve(
    transition: dict[str, Any] | str,
    acknowledgment: dict[str, Any] | str,
) -> ToolResult:
    try:
        return _content(
            approve_proposal(
                _workspace(), _resolve(transition), _resolve(acknowledgment)
            )
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="validate_domain_judgment", annotations=_MUTATION)
def validate_domain(
    packet: dict[str, Any] | str,
    draft: dict[str, Any],
) -> ToolResult:
    try:
        resolved_draft = _resolve(draft)
        if not isinstance(resolved_draft, Mapping):
            raise TypeError("Domain draft must be an object")
        return _content(
            validate_domain_runtime(_workspace(), _resolve(packet), resolved_draft)
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="commit_domain_judgment", annotations=_MUTATION)
def commit_domain(transition: dict[str, Any] | str) -> ToolResult:
    try:
        reference = TransitionReference.model_validate(_resolve(transition))
        transition_record = read_transition(_workspace(), reference)
        candidate = RecordReference.model_validate(transition_record.get("candidate"))
        scientific = read_json(
            _workspace(),
            f"domain-scientific-{candidate.identity.removeprefix('sha256:')}.json",
        )
        if not isinstance(scientific, dict) or scientific.get(
            "candidate"
        ) != candidate.model_dump(mode="json"):
            return _content(
                {
                    "outcome": "condition",
                    "code": "scientific_validation_unavailable",
                    "detail": (
                        "commit requires the admissibility-audited scientific draft "
                        "returned by validate_domain_judgment"
                    ),
                    "next_action": "validate_domain_judgment",
                }
            )
        return _content(
            commit_domain_judgment(_workspace(), reference, caller="server:mcp")
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="prepare_trial_finish", annotations=_MUTATION)
def prepare_trial(
    packet: dict[str, Any] | str, candidate: dict[str, Any]
) -> ToolResult:
    try:
        if "retained_checkpoints" in candidate:
            return _content(
                {
                    "outcome": "repair",
                    "repairs": [
                        {
                            "pointer": "/candidate/retained_checkpoints",
                            "code": "server_owned",
                            "detail": "retained checkpoints are derived by the server",
                        }
                    ],
                }
            )
        typed = TrialFinishCandidate.model_validate(_resolve(candidate))
        reference = RecordReference.model_validate(_resolve(packet))
        authority = (
            ReviewAuthority.RESEARCHER
            if typed.disposition.value in {"needs_input", "failed"}
            else ReviewAuthority.HOST
        )
        return _content(
            prepare_trial_finish(
                _workspace(),
                reference,
                typed,
                caller="server:mcp",
                authority=authority,
            )
        )
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="finish_trial", annotations=_MUTATION)
def finish(
    transition: dict[str, Any] | str,
    acknowledgment: dict[str, Any] | str,
) -> ToolResult:
    try:
        request = TrialFinishRequest(
            transition=TransitionReference.model_validate(_resolve(transition)),
            acknowledgment=ReviewAcknowledgmentReference.model_validate(
                _resolve(acknowledgment)
            ),
        )
        return _content(finish_trial(_workspace(), request, caller="server:mcp"))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="finalize_batch", annotations=_MUTATION)
def finalize() -> ToolResult:
    try:
        return _content(finalize_with_archive(_workspace()))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


@mcp.tool(name="read_record", annotations=_READ_ONLY)
def read_record(record: dict[str, Any] | str) -> ToolResult:
    try:
        resolved = _resolve(record)
        if not isinstance(resolved, Mapping):
            raise TypeError("record must be a reference object or short handle")
        if resolved.get("kind") == "evidence":
            return _content(
                resolve_evidence(
                    _workspace(), EvidenceReference.model_validate(resolved)
                )
            )
        reference = RecordReference.model_validate(resolved)
        return _content(_proposal_detail(reference))
    except (OSError, TypeError, ValueError, ValidationError) as error:
        return _repair(error)


def main() -> None:
    mcp.run(show_banner=False)
