"""The small, typed MCP boundary for the RoB 2 application."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, ResourceLink, TextContent, ToolAnnotations

from rob2_kit.application import (
    AuthorizedSourceRoot,
    CandidateSource,
    CaptureRequest,
    IntakePlanEntry,
    PreflightRequest,
    ProposalInput,
    capture_batch,
    inspect_candidate_sources,
    preflight_sources,
    save_intake_plan,
    save_proposal,
)
from rob2_kit.application._state import read_json
from rob2_kit.application.contracts import (
    EvidenceReference,
    RecordReference,
    ReviewAcknowledgmentReference,
    TransitionReference,
)
from rob2_kit.application.domains import (
    DomainDraftInput,
    DomainValidationRequest,
    commit_domain_judgment,
    validate_domain_judgment,
)
from rob2_kit.application.evidence import (
    EvidenceCatalogRequest,
    EvidenceRetrievalRequest,
    ManualSelectionRequest,
    NormalSelectionRequest,
    PageReadRequest,
    SearchContinuation,
    SearchRequest,
    VisualSelectionRequest,
    list_sources,
    resolve_evidence,
    retrieve_evidence,
    source_records,
)
from rob2_kit.application.finalization import finalize_batch
from rob2_kit.application.proposal import ApprovalRequest, approve_batch
from rob2_kit.application.status import status_json
from rob2_kit.application.trials import (
    TrialFinishCandidate,
    TrialFinishRequest,
    finish_trial,
    prepare_trial_finish,
)
from rob2_kit.models import sha256
from rob2_kit.rendering import RenderCondition, read_render, render_page
from rob2_kit.storage import read_only_transaction

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


def _content(value: Any) -> ToolResult:
    """Structured content is the sole complete receipt; prose remains a headline."""
    dumped = (
        value.model_dump(mode="json", exclude_none=True) if hasattr(value, "model_dump") else value
    )
    outcome = dumped.get("outcome", "success") if isinstance(dumped, dict) else "success"
    return ToolResult(
        content=[
            TextContent(
                type="text", text=f"{outcome}; inspect structured content for the typed receipt."
            )
        ],
        structured_content=dumped,
    )


def _candidate_summary(candidate: CandidateSource) -> dict[str, Any]:
    return candidate.model_dump(mode="json", exclude={"pages"})


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    return status_json(_workspace())


def _detail(kind: str, identity: str) -> dict[str, object]:
    if kind == "evidence":
        raise ValueError("Evidence detail URI is unsupported")
    names = {
        "source_preflight": "preflight.json",
        "intake_plan": "intake_plan.json",
        "captured_batch": "captured_batch.json",
        "proposal_review": "proposal_review.json",
        "approved_batch": "approved_batch.json",
        "work_packet": f"domain-packet-{identity.removeprefix('sha256:')}.json",
        "review_ack": "review_ack.json",
        "trial_synthesis": f"synthesis-{identity.removeprefix('sha256:')}.json",
        "domain_candidate": f"domain-candidate-{identity.removeprefix('sha256:')}.json",
        "domain_checkpoint": f"domain-observation-{identity.removeprefix('sha256:')}.json",
        "trial_terminal": f"trial-outcome-{identity.removeprefix('sha256:')}.json",
        "assessment_snapshot": f"assessment-snapshot-{identity.removeprefix('sha256:')}.json",
        "batch_summary": "finalization-summary.json",
    }
    name = names.get(kind)
    value = None if name is None else read_json(_workspace(), name)
    if value is not None and _verified_detail(kind, identity, value):
        return value
    # Trial outcomes are keyed by Trial id, not their content identity.  The
    # remaining immutable records similarly need identity-based resolution.
    workspace = Path(_workspace())
    paths = list(workspace.glob("*.json"))
    if kind == "artifact_manifest":
        paths.extend(workspace.glob(".rob2-kit/finalized/*/manifest.json"))
    for path in paths:
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _verified_detail(kind, identity, candidate):
            return candidate
    with read_only_transaction(_workspace()) as connection:
        if connection is not None:
            rows = connection.execute(
                "SELECT payload FROM records WHERE name LIKE 'application:%'"
            ).fetchall()
            for row in rows:
                candidate = json.loads(bytes(row[0]).decode("utf-8"))
                if _verified_detail(kind, identity, candidate):
                    return candidate
    raise ValueError("Detail record is unavailable or does not match its identity")


def _verified_detail(kind: str, requested_identity: str, value: object) -> bool:
    """Per-kind verification prevents a self-reported identity becoming authority."""
    if not isinstance(value, dict):
        return False
    actual_identity = (
        value.get("manifest_hash")
        if kind == "artifact_manifest"
        else value.get("active_hash")
        if kind == "domain_checkpoint"
        else value.get("identity")
    )
    if actual_identity != requested_identity:
        return False
    try:
        if kind == "source_preflight":
            from rob2_kit.application.preflight import verify_source_preflight

            return verify_source_preflight(value).identity == requested_identity
        if kind == "intake_plan":
            from rob2_kit.application.intake import verify_intake_plan

            return verify_intake_plan(value).identity == requested_identity
        if kind == "review_ack":
            from rob2_kit.application._state import identity
            from rob2_kit.application.acknowledgments import StoredReviewAcknowledgment

            stored = StoredReviewAcknowledgment.model_validate(value)
            payload = {
                key: value[key]
                for key in ("record", "authority", "purpose", "caller", "observed_at")
            }
            return stored.identity == identity(payload)
        if kind == "captured_batch":
            from rob2_kit.application._state import identity

            return set(value) == {"kind", "identity", "plan", "acknowledgment", "sources"} and (
                value["kind"] == "captured_batch"
                and identity({key: value[key] for key in ("plan", "acknowledgment", "sources")})
                == requested_identity
            )
        from rob2_kit.application._state import identity

        if kind == "approved_batch":
            return (
                value.get("kind") == kind
                and identity(
                    {key: item for key, item in value.items() if key not in {"kind", "identity"}}
                )
                == requested_identity
            )
        if kind == "proposal_review":
            fields = ("captured_batch", "outcome_statement", "results", "needs_input")
            return (
                value.get("kind") == kind
                and identity({key: value.get(key) for key in fields}) == requested_identity
            )
        if kind == "work_packet":
            from rob2_kit.application.domains import parse_application_work_packet

            return parse_application_work_packet(value).identity == requested_identity
        if kind == "trial_synthesis":
            fields = (
                "approved_batch",
                "trial_id",
                "result_id",
                "checkpoint_hashes",
                "checkpoint_judgments",
                "proposed_overall",
            )
            payload = {key: value.get(key) for key in fields} | {"combined_concerns": False}
            return value.get("kind") == kind and identity(payload) == requested_identity
        if kind in {"domain_candidate", "domain_checkpoint"}:
            fields = (
                "kind",
                "packet",
                "trial_id",
                "result_id",
                "domain_id",
                "draft",
                "proposed_judgment",
                "inactive_questions",
                "evidence_bindings",
                "scientific_pack",
                "policy_pack",
            )
            candidate_identity = identity({key: value.get(key) for key in fields})
            if value.get("kind") != "domain_candidate" or candidate_identity != value.get(
                "identity"
            ):
                return False
            return (
                candidate_identity == requested_identity
                if kind == "domain_candidate"
                else identity(
                    {"candidate": candidate_identity, "revision": value.get("active_revision")}
                )
                == requested_identity
            )
        if kind == "batch_summary":
            fields = ("approved_batch", "counts", "trials", "presentation")
            return (
                value.get("kind") == "finalization"
                and identity({key: value.get(key) for key in fields}) == requested_identity
            )
        if kind == "assessment_snapshot":
            from rob2_kit.application.trials import AssessmentSnapshot

            snapshot = AssessmentSnapshot.model_validate(value)
            payload = {
                "synthesis": snapshot.synthesis.model_dump(mode="json"),
                "checkpoint_hashes": snapshot.checkpoint_hashes,
                "proposed_overall": snapshot.proposed_overall.value,
                "final_judgment": snapshot.final_judgment.value,
                "caller": snapshot.caller,
                "observed_at": snapshot.observed_at.isoformat().replace("+00:00", "Z"),
            }
            return (
                snapshot.identity == requested_identity
                and snapshot.snapshot_hash == sha256(payload)
                and identity(payload) == requested_identity
            )
        if kind == "trial_terminal":
            if "candidate" in value:
                payload = {"synthesis": value.get("synthesis"), "candidate": value.get("candidate")}
            elif "acknowledgment" in value and "synthesis" not in value:
                payload = {
                    "trial_id": value.get("trial_id"),
                    "disposition": value.get("disposition"),
                    "reason": value.get("reason"),
                    "missing_facts": value.get("missing_facts"),
                    "evidence": value.get("evidence"),
                    "acknowledgment": value.get("acknowledgment"),
                }
            else:
                payload = {
                    key: value.get(key)
                    for key in (
                        "synthesis",
                        "trial_id",
                        "disposition",
                        "reason",
                        "failure_cause",
                        "missing_facts",
                        "available_evidence",
                        "retained_checkpoints",
                        "caller",
                        "observed_at",
                        "snapshot",
                        "transition",
                    )
                }
            return value.get("kind") == kind and identity(payload) == requested_identity
        if kind == "artifact_manifest":
            payload = {"summary_hash": value.get("summary_hash"), "files": value.get("files")}
            return (
                value.get("manifest_hash") == requested_identity
                and identity(payload) == requested_identity
            )
        if kind == "diagnostic":
            return (
                value.get("kind") == kind
                and identity(
                    {key: item for key, item in value.items() if key not in {"kind", "identity"}}
                )
                == requested_identity
            )
    except (KeyError, TypeError, ValueError):
        return False
    return False


@mcp.resource("rob2://detail/{kind}/{identity}")
def detail_resource(kind: str, identity: str) -> str:
    return json.dumps(
        _detail(kind, identity), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


@mcp.resource("rob2://registry/{trial_id}")
def registry_resource(trial_id: str) -> str:
    preflight = read_json(_workspace(), "preflight.json") or {}
    outcomes = dict(preflight.get("registry_outcomes", ()))
    if trial_id not in outcomes:
        raise ValueError("registry record is unavailable")
    return json.dumps({"trial_id": trial_id, "status": outcomes[trial_id]}, separators=(",", ":"))


@mcp.resource("rob2://render/{identity}")
def render_resource(identity: str) -> bytes:
    return read_render(_workspace(), identity)[1]


@mcp.tool(name="preflight_sources", annotations=_PREFLIGHT)
def preflight(
    roots: tuple[AuthorizedSourceRoot, ...], expected_head: str | None = None
) -> ToolResult:
    result = preflight_sources(
        _workspace(), PreflightRequest(roots=roots, expected_head=expected_head)
    )
    return _content(
        {
            "kind": result.kind,
            "identity": result.identity,
            "roots": result.roots,
            "candidates": [_candidate_summary(item) for item in result.candidates],
            "conditions": result.conditions,
            "registry_attempts": result.registry_attempts,
            "registry_outcomes": result.registry_outcomes,
            "reference": result.reference.model_dump(mode="json"),
        }
    )


@mcp.tool(name="inspect_candidate_sources", annotations=_READ_ONLY)
def inspect(
    candidate_identity: str, query: str | None = None, page: int | None = None
) -> ToolResult:
    result = inspect_candidate_sources(_workspace(), candidate_identity, query=query, page=page)
    return _content(
        {
            "candidate": _candidate_summary(result.candidate),
            "page": result.page,
            "text": result.text,
            "hits": result.hits,
        }
    )


@mcp.tool(name="save_intake_plan", annotations=_MUTATION)
def save_plan(preflight: RecordReference, entries: tuple[IntakePlanEntry, ...]) -> ToolResult:
    # The caller is adapter-observed; it is intentionally absent from the
    # public model-facing schema.
    return _content(save_intake_plan(_workspace(), preflight, entries, host_caller="host:mcp"))


@mcp.tool(name="capture_batch", annotations=_MUTATION)
def capture(plan: RecordReference, acknowledgment: ReviewAcknowledgmentReference) -> ToolResult:
    return _content(
        capture_batch(_workspace(), CaptureRequest(plan=plan, acknowledgment=acknowledgment))
    )


@mcp.tool(name="list_sources", annotations=_READ_ONLY)
def list_trial_sources(trial_id: str) -> ToolResult:
    # ToolResult structured content is an object in MCP; keep the collection
    # under a named field instead of handing FastMCP a bare JSON array.
    return _content({"sources": list_sources(_workspace(), trial_id)})


@mcp.tool(name="retrieve_evidence", annotations=_READ_ONLY)
def retrieve(
    trial_id: str,
    searches: tuple[SearchRequest, ...] = (),
    continuations: tuple[SearchContinuation, ...] = (),
    page_reads: tuple[PageReadRequest, ...] = (),
    normal_selections: tuple[NormalSelectionRequest, ...] = (),
    manual_selections: tuple[ManualSelectionRequest, ...] = (),
    visual_selections: tuple[VisualSelectionRequest, ...] = (),
    catalog: EvidenceCatalogRequest | None = None,
) -> ToolResult:
    request = EvidenceRetrievalRequest(
        trial_id=trial_id,
        searches=searches,
        continuations=continuations,
        page_reads=page_reads,
        normal_selections=normal_selections,
        manual_selections=manual_selections,
        visual_selections=visual_selections,
        catalog=catalog,
    )
    return _content(retrieve_evidence(_workspace(), request))


@mcp.tool(name="render_page", annotations=_READ_ONLY)
def render_source_page(
    trial_id: str,
    source_id: str,
    page: int,
    region: tuple[float, float, float, float] | None = None,
) -> ToolResult | RenderCondition:
    source = next(
        (item for item in source_records(_workspace(), trial_id) if item.id == source_id), None
    )
    if source is None:
        raise ValueError("source is outside the Trial inventory")
    rendered = render_page(_workspace(), source, page, region)
    if isinstance(rendered, RenderCondition):
        return rendered
    structured = rendered.model_dump(mode="json", exclude={"image_bytes"})
    return ToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(rendered.image_bytes).decode(),
                mimeType="image/png",
            ),
            ResourceLink(
                type="resource_link",
                name="rob2-render",
                uri=f"rob2://render/{rendered.render_identity}",
                mimeType="image/png",
            ),
            TextContent(
                type="text", text="Rendered page; read the linked image resource if needed."
            ),
        ],
        structured_content=structured,
    )


@mcp.tool(name="save_proposal", annotations=_MUTATION)
def save_review(proposal: ProposalInput) -> ToolResult:
    return _content(save_proposal(_workspace(), proposal))


@mcp.tool(name="approve_batch", annotations=_MUTATION)
def approve(
    transition: TransitionReference, acknowledgment: ReviewAcknowledgmentReference
) -> ToolResult:
    return _content(
        approve_batch(
            _workspace(), ApprovalRequest(transition=transition, acknowledgment=acknowledgment)
        )
    )


@mcp.tool(name="validate_domain_judgment", annotations=_MUTATION)
def validate_domain(packet: RecordReference, draft: DomainDraftInput) -> ToolResult:
    return _content(
        validate_domain_judgment(_workspace(), DomainValidationRequest(packet=packet, draft=draft))
    )


@mcp.tool(name="commit_domain_judgment", annotations=_MUTATION)
def commit_domain(transition: TransitionReference) -> ToolResult:
    return _content(commit_domain_judgment(_workspace(), transition, caller="server:mcp"))


@mcp.tool(name="prepare_trial_finish", annotations=_MUTATION)
def prepare_trial(packet: RecordReference, candidate: TrialFinishCandidate) -> ToolResult:
    return _content(prepare_trial_finish(_workspace(), packet, candidate, caller="server:mcp"))


@mcp.tool(name="finish_trial", annotations=_MUTATION)
def finish(
    transition: TransitionReference, acknowledgment: ReviewAcknowledgmentReference
) -> ToolResult:
    return _content(
        finish_trial(
            _workspace(),
            TrialFinishRequest(transition=transition, acknowledgment=acknowledgment),
            caller="server:mcp",
        )
    )


@mcp.tool(name="finalize_batch", annotations=_MUTATION)
def finalize() -> ToolResult:
    return _content(finalize_batch(_workspace()))


@mcp.tool(name="read_record", annotations=_READ_ONLY)
def read_record(record: RecordReference | EvidenceReference) -> ToolResult:
    # Validate the complete caller-owned reference before resolving it.
    if isinstance(record, EvidenceReference):
        return _content(resolve_evidence(_workspace(), record))
    return _content(_detail(record.kind.value, record.identity))


def main() -> None:
    mcp.run()
