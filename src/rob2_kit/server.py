"""The model-free FastMCP boundary."""

import json
import os
import re
from functools import wraps
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from rob2_kit.assessment import (
    ProposalApprovalReceipt,
    ProposalApproved,
    ProposalDraft,
    ProposalReceipt,
    ProposalSaved,
)
from rob2_kit.batch import (
    ApprovedBatch,
    approve_proposal,
    save_proposal_mapping,
)
from rob2_kit.batch import (
    current_batch as canonical_current_batch,
)
from rob2_kit.batch_summary import FinalizationCondition, FinalizationSuccess, finalize_batch_v2
from rob2_kit.detail import DetailReference, detail_reference, parse_detail_uri, resource_link
from rob2_kit.detail import read_record as read_detail_record
from rob2_kit.finish import (
    AssessmentFinishOperation as InternalAssessmentFinishOperation,
)
from rob2_kit.finish import (
    AssessmentFinishSuccess,
    FinishV2Condition,
    FinishV2Conflict,
    OverallOverrideDraft,
    ProblemDraft,
    ProblemFinishSuccess,
    finish_assessment_v2,
    finish_problem_v2,
)
from rob2_kit.finish import (
    ProblemFinishOperation as InternalProblemFinishOperation,
)
from rob2_kit.ingestion import ingest_batch, publish_captured_batch, read_captured_batch
from rob2_kit.ingestion.service import local_sources, registry_source
from rob2_kit.judgment_models import (
    DomainCommitCondition,
    DomainCommitConflict,
    DomainCommitSuccess,
    DomainDraftCommitOperation,
    DomainDraftOperation,
    DomainDraftRepairResult,
    DomainDraftValidated,
)
from rob2_kit.judgments import commit_domain_draft, validate_domain_draft_mapping
from rob2_kit.recovery import (
    CurrentBatchProjection,
    DiscardActiveBatchRequest,
    DiscardCondition,
    Discarded,
    current_batch_projection,
    discard_active_batch,
)
from rob2_kit.registry import (
    RegistryCandidateRecord,
    RegistryNotCaptured,
    TrialFacts,
    http_request,
    match_registry,
    read_captured_registry,
    read_registry_match,
    record_registry_match,
)
from rob2_kit.rendering import RenderCondition, RenderedPage, render_page
from rob2_kit.retrieval import (
    EvidenceRetrievalBatch,
    RetrievalBatchCondition,
    RetrievalBatchResult,
    retrieve_batch,
)
from rob2_kit.sources import (
    Source,
    TrialInput,
    list_sources,
)
from rob2_kit.storage import WorkspaceLock, workspace_mutation_lock


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    source_id: str
    page_number: int = Field(ge=1)
    region: tuple[float, float, float, float] | None = None


class ListSourcesResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    sources: tuple[Source, ...]


class RegistryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    supplied_nct: str | None = None
    facts: TrialFacts | None = None


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_inputs: tuple[TrialInput, ...] = Field(min_length=1)
    registry_requests: tuple[RegistryRequest, ...] = ()


class IngestTrialReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_id: str
    status: Literal["captured", "condition"]
    source_count: int = Field(ge=0)
    projection_count: int = Field(ge=0)
    registry_status: Literal["matched", "ambiguous", "not_found", "unavailable", "not_attempted"]
    condition_code: str | None = None


class IngestRegistryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    captured_batch_ref: DetailReference
    trials: tuple[IngestTrialReceipt, ...]
    next_action: Literal["save_proposal"] = "save_proposal"


class ApproveBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewed_proposal_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ProposalDraftTransport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: object


class ProposalDraftCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: ProposalDraft


class DomainDraftTransport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approved_batch_hash: str = Field(min_length=1)
    trial_id: str = Field(min_length=1)
    result_id: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    expected_predecessor_hash: str | None = None
    draft: object


class DomainDraftTransportCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: DomainDraftOperation


class ReadRecordResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: DetailReference
    record: object


class AssessedFinishOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["assessed"] = "assessed"
    approved_batch_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_id: str
    reviewed_synthesis_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    actor: str = Field(min_length=1)
    combined_concerns: bool | None = None
    limitations: tuple[str, ...] = ()
    override: OverallOverrideDraft | None = None


class NeedsInputFinishOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["needs_input"] = "needs_input"
    approved_batch_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_id: str
    actor: str = Field(min_length=1)
    problems: tuple[ProblemDraft, ...] = Field(min_length=1)


class FailedFinishOperation(NeedsInputFinishOperation):
    mode: Literal["failed"] = "failed"


PublicFinishTrialOperation = Annotated[
    AssessedFinishOperation | NeedsInputFinishOperation | FailedFinishOperation,
    Field(discriminator="mode"),
]


mcp = FastMCP("rob2-kit")


def _linked_result(result: BaseModel, references: tuple[DetailReference, ...]) -> ToolResult:
    structured = result.model_dump(mode="json")
    return ToolResult(
        content=[
            TextContent(
                type="text", text=json.dumps(structured, sort_keys=True, separators=(",", ":"))
            ),
            *(resource_link(reference) for reference in references),
        ],
        structured_content=structured,
    )


def _object_union_schema(value: object) -> dict[str, object]:
    schema = TypeAdapter(value).json_schema(mode="serialization")
    schema["type"] = "object"
    return schema


def _sources(workspace: str, trial_id: str) -> tuple[Source, ...]:
    """Read the exact validated local plus optional captured registry inventory."""
    local = local_sources(workspace, trial_id)
    registry = registry_source(workspace, trial_id)
    return list_sources(local + (() if registry is None else (registry,)))


def _source(workspace: str, trial_id: str, source_id: str) -> Source:
    source = next((item for item in _sources(workspace, trial_id) if item.id == source_id), None)
    if source is None:
        raise ValueError("source is not in the Trial's authoritative inventory")
    return source


@mcp.resource("rob2://current-batch")
def current_batch() -> str:
    """Return the compact mutable workflow projection."""
    workspace = os.environ.get("ROB2_WORKSPACE")
    return (
        current_batch_projection(workspace).model_dump_json(
            exclude_none=True, exclude_defaults=True
        )
        if workspace
        else CurrentBatchProjection(phase="empty", next_action="ingest").model_dump_json(
            exclude_none=True, exclude_defaults=True
        )
    )


@mcp.resource("rob2://detail/{kind}/{identity}")
def detail_record(kind: str, identity: str) -> str:
    """Read one immutable, identity-bound Detail resource."""
    reference = parse_detail_uri(f"rob2://detail/{kind}/{identity}")
    return json.dumps(
        read_detail_record(os.environ["ROB2_WORKSPACE"], reference),
        sort_keys=True,
        separators=(",", ":"),
    )


def _locked_intake(function):
    @wraps(function)
    def locked(request):
        with workspace_mutation_lock(os.environ["ROB2_WORKSPACE"]):
            return function(request)

    return locked


@mcp.tool(
    name="ingest_batch",
    output_schema=IngestRegistryResult.model_json_schema(),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
    ),
)
@_locked_intake
def ingest_one_batch(request: IngestRequest) -> ToolResult:
    """Capture local inputs and pair every Trial with a registry attempt or condition."""
    workspace = os.environ["ROB2_WORKSPACE"]
    supplied = {item.trial_id: item for item in request.registry_requests}
    if len(supplied) != len(request.registry_requests) or set(supplied) - {
        item.id for item in request.trial_inputs
    }:
        raise ValueError("registry requests must be unique requested Trials")
    existing_captured = read_captured_batch(workspace)
    if existing_captured is not None:
        if existing_captured.trial_inputs != request.trial_inputs:
            raise ValueError("completed Captured Batch is immutable until explicit discard")
        receipt = IngestRegistryResult(
            captured_batch_ref=detail_reference("batch", existing_captured.content_hash),
            trials=tuple(
                IngestTrialReceipt(
                    trial_id=trial.trial_input.id,
                    status="captured" if trial.sources else "condition",
                    source_count=len(trial.sources),
                    projection_count=len(trial.projections),
                    registry_status=trial.registry.status,
                )
                for trial in existing_captured.trials
            ),
        )
        return _linked_result(receipt, (receipt.captured_batch_ref,))
    result = ingest_batch(workspace, request.trial_inputs)
    records: dict[str, RegistryCandidateRecord] = {}
    successful = tuple(captured for captured in result.trials if captured.condition is None)
    if successful:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            request_provider = http_request(client)
            for captured in successful:
                main = next(
                    source for source in captured.sources if source.role.value == "main_article"
                )
                registry = supplied.get(captured.trial_id)
                main_index = captured.sources.index(main)
                text = "\n".join(captured.projection_pages[main_index])
                facts = (
                    TrialFacts() if registry is None or registry.facts is None else registry.facts
                )
                match = match_registry(
                    facts,
                    request_provider,
                    supplied_nct=None if registry is None else registry.supplied_nct,
                    main_article_text=text,
                )
                records[captured.trial_id] = record_registry_match(
                    workspace, captured.trial_id, match
                )
    captured_batch = publish_captured_batch(workspace, request.trial_inputs, result, records)
    receipt = IngestRegistryResult(
        captured_batch_ref=detail_reference("batch", captured_batch.content_hash),
        trials=tuple(
            IngestTrialReceipt(
                trial_id=trial.trial_input.id,
                status="condition" if captured.condition is not None else "captured",
                source_count=len(trial.sources),
                projection_count=len(trial.projections),
                registry_status=trial.registry.status,
                condition_code=(None if captured.condition is None else captured.condition.code),
            )
            for captured, trial in zip(result.trials, captured_batch.trials, strict=True)
        ),
    )
    return _linked_result(receipt, (receipt.captured_batch_ref,))


@mcp.tool(
    name="list_sources",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def list_trial_sources(trial_id: str) -> ListSourcesResult:
    """List the exact validated immutable Source inventory for one Trial."""
    workspace = os.environ["ROB2_WORKSPACE"]
    return ListSourcesResult(trial_id=trial_id, sources=_sources(workspace, trial_id))


@mcp.tool(
    name="retrieve_evidence",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def retrieve_evidence(
    request: EvidenceRetrievalBatch,
) -> RetrievalBatchResult | RetrievalBatchCondition:
    """Evaluate one snapshot-bound batch of independent retrieval operations."""
    return retrieve_batch(os.environ["ROB2_WORKSPACE"], request)


@mcp.tool(
    name="render_page",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def render_source_page(request: RenderRequest) -> RenderedPage | RenderCondition:
    """Render an exact captured PDF page; image bytes are structured base64 by MCP."""
    workspace = os.environ["ROB2_WORKSPACE"]
    source = _source(workspace, request.trial_id, request.source_id)
    return render_page(workspace, source, request.page_number, request.region)


@mcp.tool(
    name="save_proposal",
    output_schema=_object_union_schema(ProposalReceipt),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def save_public_proposal(draft: object) -> ToolResult:
    """Validate and save one strict minimal Proposal draft."""
    receipt = save_proposal_mapping(os.environ["ROB2_WORKSPACE"], draft)
    refs = (receipt.proposal_ref,) if isinstance(receipt, ProposalSaved) else ()
    return _linked_result(receipt, refs)


@mcp.tool(
    name="approve_batch",
    output_schema=_object_union_schema(ProposalApprovalReceipt),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def approve_public_batch(request: ApproveBatchRequest) -> ToolResult:
    """Freeze only the exact Proposal hash deliberately reviewed."""
    receipt = approve_proposal(os.environ["ROB2_WORKSPACE"], request.reviewed_proposal_hash)
    refs = (receipt.first_packet_ref,) if isinstance(receipt, ProposalApproved) else ()
    return _linked_result(receipt, refs)


@mcp.tool(
    name="validate_domain_judgment",
    output_schema=_object_union_schema(DomainDraftRepairResult | DomainDraftValidated),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def validate_public_domain_judgment(
    operation: DomainDraftTransport,
) -> ToolResult:
    """Validate a strict Domain draft and return compact repairs or receipt."""
    result = validate_domain_draft_mapping(
        os.environ["ROB2_WORKSPACE"],
        approved_batch_hash=operation.approved_batch_hash,
        trial_id=operation.trial_id,
        result_id=operation.result_id,
        domain_id=operation.domain_id,
        actor=operation.actor,
        expected_predecessor_hash=operation.expected_predecessor_hash,
        raw_draft=operation.draft,
    )
    refs = () if not isinstance(result, DomainDraftValidated) else (result.candidate_ref,)
    return _linked_result(result, refs)


@mcp.tool(
    name="commit_domain_judgment",
    output_schema=_object_union_schema(
        DomainCommitSuccess | DomainCommitConflict | DomainCommitCondition
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def commit_public_domain_judgment(
    operation: DomainDraftCommitOperation,
) -> ToolResult:
    """Commit only the exact receipt-bound Domain candidate."""
    result = commit_domain_draft(os.environ["ROB2_WORKSPACE"], operation)
    refs = (
        (result.candidate_ref, result.next_packet_ref)
        if isinstance(result, DomainCommitSuccess)
        else (
            ()
            if not isinstance(result, DomainCommitConflict) or result.current_ref is None
            else (result.current_ref,)
        )
    )
    return _linked_result(result, refs)


@mcp.tool(
    name="finish_trial",
    output_schema=_object_union_schema(
        AssessmentFinishSuccess | ProblemFinishSuccess | FinishV2Conflict | FinishV2Condition
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def finish_public_trial(
    operation: PublicFinishTrialOperation,
) -> ToolResult:
    """Finish a Trial from an exact synthesis review or typed problem draft."""
    workspace = os.environ["ROB2_WORKSPACE"]
    state = canonical_current_batch(workspace)
    if not isinstance(state, ApprovedBatch):
        return _linked_result(
            FinishV2Condition(code="batch_not_approved", detail="an Approved Batch is required"),
            (),
        )
    result_spec = next(
        (item for item in state.proposal.result_specs if item.trial.id == operation.trial_id),
        None,
    )
    if result_spec is None:
        return _linked_result(
            FinishV2Condition(
                code="result_identity_invalid",
                detail="Trial does not identify an Approved Result",
            ),
            (),
        )
    result_id = result_spec.id
    if isinstance(operation, AssessedFinishOperation):
        result = finish_assessment_v2(
            workspace,
            InternalAssessmentFinishOperation(
                **operation.model_dump(exclude={"mode"}), result_id=result_id
            ),
        )
    else:
        result = finish_problem_v2(
            workspace,
            InternalProblemFinishOperation(
                **operation.model_dump(exclude={"mode"}),
                result_id=result_id,
                category=operation.mode,
            ),
        )
    if isinstance(result, AssessmentFinishSuccess):
        refs = (result.terminal_ref, result.snapshot_ref)
    elif isinstance(result, (ProblemFinishSuccess, FinishV2Conflict)):
        refs = (result.terminal_ref,)
    else:
        refs = ()
    return _linked_result(result, refs)


@mcp.tool(
    name="finalize_batch",
    output_schema=_object_union_schema(FinalizationSuccess | FinalizationCondition),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def finalize_public_batch(actor: str) -> ToolResult:
    """Finalize all terminal Trials and return only compact handoff identities."""
    result = finalize_batch_v2(os.environ["ROB2_WORKSPACE"], actor)
    refs = (
        ()
        if isinstance(result, FinalizationCondition)
        else (
            result.summary_ref,
            *(
                reference
                for outcome in result.outcomes
                for reference in (outcome.terminal_ref, outcome.snapshot_ref)
                if reference is not None
            ),
        )
    )
    return _linked_result(result, refs)


@mcp.tool(
    name="read_record",
    output_schema=ReadRecordResult.model_json_schema(),
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
)
def read_public_record(reference: DetailReference) -> ToolResult:
    """Read one deliberate immutable Detail record by exact identity."""
    result = ReadRecordResult(
        reference=reference,
        record=read_detail_record(os.environ["ROB2_WORKSPACE"], reference),
    )
    return _linked_result(result, (reference,))


@mcp.tool(
    name="discard_active_batch",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def discard_one_active_batch(
    request: DiscardActiveBatchRequest,
) -> Discarded | DiscardCondition:
    """DESTRUCTIVE: discard only the explicitly identified unfinished frozen batch."""
    return discard_active_batch(os.environ["ROB2_WORKSPACE"], request)


@mcp.resource("rob2://registry/{trial_id}")
def registry_record(trial_id: str) -> str:
    """Read a validated captured ClinicalTrials.gov record for one Trial."""
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", trial_id) is None:
        raise ValueError("invalid trial identifier")
    workspace = os.environ.get("ROB2_WORKSPACE")
    if not workspace:
        return RegistryNotCaptured(trial_id=trial_id, status="not_captured").model_dump_json()
    candidate = read_registry_match(workspace, trial_id)
    return json.dumps(
        {
            "candidate": None if candidate is None else candidate.model_dump(mode="json"),
            "captured": read_captured_registry(workspace, trial_id).model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _advertise_authoritative_draft_schemas() -> None:
    """Keep raw nested validation while publishing the strict owning schemas."""

    components = mcp._local_provider._components
    for name, schema in (
        ("save_proposal", ProposalDraftCall.model_json_schema()),
        ("validate_domain_judgment", DomainDraftTransportCall.model_json_schema()),
    ):
        key = f"tool:{name}@"
        components[key] = components[key].model_copy(update={"parameters": schema})


_advertise_authoritative_draft_schemas()


def main() -> None:
    """Run the stdio MCP server."""
    workspace = os.environ.get("ROB2_WORKSPACE")
    if workspace is None:
        mcp.run()
        return
    with WorkspaceLock(workspace):
        mcp.run()
