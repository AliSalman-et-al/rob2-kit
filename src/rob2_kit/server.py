"""The model-free FastMCP boundary."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.assessment import Proposal
from rob2_kit.batch import ApproveBatchResult, SaveProposalResult, approve_batch, save_proposal
from rob2_kit.batch_summary import (
    BatchCondition,
    BatchConflict,
    BatchSaved,
    FinalizedBatch,
    Problem,
    TerminalConflict,
    TerminalSaved,
    finalize_batch,
    terminalize_problem,
)
from rob2_kit.finish import FinishTrialResult, finish_trial
from rob2_kit.ingestion import ingest_batch
from rob2_kit.ingestion.service import local_sources, registry_source
from rob2_kit.judgment_models import ActiveAnswer, InactiveQuestion, Override
from rob2_kit.judgments import SaveDomainJudgmentResult, save_domain_judgment
from rob2_kit.models import Judgment
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.recovery import (
    DiscardActiveBatchRequest,
    DiscardCondition,
    Discarded,
    discard_active_batch,
    recovery_progress,
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
from rob2_kit.reports import batch_artifact_receipt, export_batch
from rob2_kit.search import SearchHit, _source_bytes, search_sources
from rob2_kit.sources import (
    IngestedTrial,
    ReadPagesResult,
    Source,
    TrialInput,
    _extract_pages,
    list_sources,
    read_pages,
)
from rob2_kit.storage import WorkspaceLock, workspace_mutation_lock


class CurrentBatch(BaseModel):
    """The initial state before batch ingestion exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_batch: Literal[None] = None


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    source_id: str


class ReadPagesRequest(SourceRequest):
    page_numbers: tuple[int, ...] = Field(min_length=1)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    source_ids: tuple[str, ...] = Field(min_length=1)
    query: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class RenderRequest(SourceRequest):
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


class RegistryNotAttempted(BaseModel):
    """Registry matching is inapplicable when local ingestion has a condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_attempted"]
    trial_id: str
    reason: Literal["local_ingestion_condition"]


class LocalIngestionCondition(BaseModel):
    """One local ingestion condition and its explicitly inapplicable registry attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["local_condition"]
    trial: IngestedTrial
    registry: RegistryNotAttempted


class RegistryAttempt(BaseModel):
    """One successful local ingestion and its persisted categorical registry attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["registry_attempted"]
    trial: IngestedTrial
    registry: RegistryCandidateRecord


IngestionRegistryTrial = Annotated[
    LocalIngestionCondition | RegistryAttempt, Field(discriminator="status")
]


class IngestRegistryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trials: tuple[IngestionRegistryTrial, ...]


class AssessmentFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["assessment"]
    trial_id: str
    final_judgment: Judgment | None
    override: Override | None
    combined_concerns: bool | None
    limitations: tuple[str, ...]
    actor: str
    observed_at: datetime


class ProblemFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trial_id: str
    problems: tuple[Problem, ...] = Field(min_length=1)
    actor: str
    observed_at: datetime


class NeedsInputFinishRequest(ProblemFinishRequest):
    mode: Literal["needs_input"]


class FailedFinishRequest(ProblemFinishRequest):
    mode: Literal["failed"]


FinishTrialRequest = Annotated[
    AssessmentFinishRequest | NeedsInputFinishRequest | FailedFinishRequest,
    Field(discriminator="mode"),
]


mcp = FastMCP("rob2-kit")


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
    """Return active approval plus durable, derived restart progress."""
    workspace = os.environ.get("ROB2_WORKSPACE")
    return (
        CurrentBatch().model_dump_json()
        if not workspace
        else json.dumps(
            recovery_progress(workspace).model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


@mcp.tool(name="save_proposal")
def save_batch_proposal(proposal: Proposal) -> SaveProposalResult:
    """Save a replaceable complete batch proposal."""
    workspace = os.environ["ROB2_WORKSPACE"]
    return save_proposal(workspace, proposal)


@mcp.tool(name="ingest_batch")
def ingest_one_batch(request: IngestRequest) -> IngestRegistryResult:
    """Capture local inputs and pair every Trial with a registry attempt or condition."""
    workspace = os.environ["ROB2_WORKSPACE"]
    result = ingest_batch(workspace, request.trial_inputs)
    supplied = {item.trial_id: item for item in request.registry_requests}
    if len(supplied) != len(request.registry_requests) or set(supplied) - {
        item.id for item in request.trial_inputs
    }:
        raise ValueError("registry requests must be unique requested Trials")
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
                text = "\n".join(
                    _extract_pages(_source_bytes(Path(workspace), main), main.media_type)
                )
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
    return IngestRegistryResult(
        trials=tuple(
            LocalIngestionCondition(
                status="local_condition",
                trial=captured,
                registry=RegistryNotAttempted(
                    status="not_attempted",
                    trial_id=captured.trial_id,
                    reason="local_ingestion_condition",
                ),
            )
            if captured.condition is not None
            else RegistryAttempt(
                status="registry_attempted", trial=captured, registry=records[captured.trial_id]
            )
            for captured in result.trials
        )
    )


@mcp.tool(name="list_sources")
def list_trial_sources(trial_id: str) -> ListSourcesResult:
    """List the exact validated immutable Source inventory for one Trial."""
    workspace = os.environ["ROB2_WORKSPACE"]
    return ListSourcesResult(trial_id=trial_id, sources=_sources(workspace, trial_id))


@mcp.tool(name="read_pages")
def read_source_pages(request: ReadPagesRequest) -> ReadPagesResult:
    """Read exact page text from one inventory Source."""
    workspace = os.environ["ROB2_WORKSPACE"]
    source = _source(workspace, request.trial_id, request.source_id)
    return read_pages(workspace, source, request.page_numbers)


@mcp.tool(name="search_sources")
def search_trial_sources(request: SearchRequest) -> tuple[SearchHit, ...]:
    """Search an explicit subset of the Trial's authoritative immutable Sources."""
    workspace = os.environ["ROB2_WORKSPACE"]
    sources = tuple(_source(workspace, request.trial_id, item) for item in request.source_ids)
    return search_sources(
        workspace, request.trial_id, sources, request.query, request.offset, request.limit
    )


@mcp.tool(name="render_page")
def render_source_page(request: RenderRequest) -> RenderedPage | RenderCondition:
    """Render an exact captured PDF page; image bytes are structured base64 by MCP."""
    workspace = os.environ["ROB2_WORKSPACE"]
    source = _source(workspace, request.trial_id, request.source_id)
    return render_page(workspace, source, request.page_number, request.region)


@mcp.tool(name="approve_batch")
def approve_batch_proposal() -> ApproveBatchResult:
    """Atomically approve the one complete current proposal."""
    return approve_batch(os.environ["ROB2_WORKSPACE"])


@mcp.tool(name="save_domain_judgment")
def save_one_domain_judgment(
    trial_id: str,
    result_id: str,
    domain_id: str,
    active_answers: tuple[ActiveAnswer, ...],
    inactive_questions: tuple[InactiveQuestion, ...],
    final_judgment: Judgment | None,
    override: Override | None,
    limitations: tuple[str, ...],
    actor: str,
    observed_at: datetime,
) -> SaveDomainJudgmentResult:
    """Insert one evidence-grounded, immutable Domain checkpoint."""
    return save_domain_judgment(
        os.environ["ROB2_WORKSPACE"],
        trial_id,
        result_id,
        domain_id,
        active_answers,
        inactive_questions,
        final_judgment,
        override,
        limitations,
        actor,
        observed_at,
    )


@mcp.tool(name="finish_trial")
def finish_one_trial(
    request: FinishTrialRequest,
) -> FinishTrialResult | TerminalSaved | TerminalConflict | BatchCondition:
    """Atomically record one assessment, needs-input, or failed Trial terminal outcome."""
    return finish_trial_request(os.environ["ROB2_WORKSPACE"], request)


def finish_trial_request(
    workspace: str, request: FinishTrialRequest
) -> FinishTrialResult | TerminalSaved | TerminalConflict | BatchCondition:
    """Dispatch the single public terminal-outcome envelope to its internal service."""
    if isinstance(request, AssessmentFinishRequest):
        return finish_trial(
            workspace,
            request.trial_id,
            request.final_judgment,
            request.override,
            request.combined_concerns,
            request.limitations,
            request.actor,
            request.observed_at,
        )
    if any(
        item.actor != request.actor or item.observed_at != request.observed_at
        for item in request.problems
    ):
        raise ValueError("problem actor and timestamp must match the terminal request")
    return terminalize_problem(workspace, request.trial_id, request.mode, request.problems)


@mcp.tool(name="finalize_batch")
def finalize_one_batch(
    actor: str,
    observed_at: datetime,
) -> FinalizedBatch | BatchConflict | BatchCondition:
    """Commit the batch summary, materialize its standalone bundle, and verify it."""
    workspace = os.environ["ROB2_WORKSPACE"]
    with workspace_mutation_lock(workspace):
        finalized = finalize_batch(workspace, actor, observed_at)
        if not isinstance(finalized, BatchSaved):
            return finalized
        target = export_batch(workspace, finalized.summary.approved_batch_hash)
        return FinalizedBatch(
            summary=finalized.summary,
            receipt=batch_artifact_receipt(Path(workspace), target, finalized.summary),
        )


@mcp.tool(
    name="discard_active_batch",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
    ),
)
def discard_one_active_batch(
    request: DiscardActiveBatchRequest,
) -> Discarded | DiscardCondition:
    """DESTRUCTIVE: discard only the explicitly identified unfinished frozen batch."""
    return discard_active_batch(os.environ["ROB2_WORKSPACE"], request)


@mcp.resource("rob2://domain-guidance/{domain_id}")
def domain_guidance(domain_id: str) -> str:
    """Return pinned Domain questions and the separate maintainer-policy identity."""
    domain = next((item for item in SCIENTIFIC_PACK.domains if item.id == domain_id), None)
    if domain is None:
        raise ValueError("unknown domain")
    return json.dumps(
        {
            "domain": domain,
            "questions": [q for q in SCIENTIFIC_PACK.questions if q.id in domain.question_ids],
            "scientific_pack": {
                "id": SCIENTIFIC_PACK.id,
                "version": SCIENTIFIC_PACK.version,
                "content_hash": SCIENTIFIC_PACK.content_hash,
            },
            "policy_pack": {
                "id": MAINTAINER_POLICY_PACK.id,
                "version": MAINTAINER_POLICY_PACK.version,
                "content_hash": MAINTAINER_POLICY_PACK.content_hash,
            },
        },
        default=lambda item: item.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


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


def main() -> None:
    """Run the stdio MCP server."""
    workspace = os.environ.get("ROB2_WORKSPACE")
    if workspace is None:
        mcp.run()
        return
    with WorkspaceLock(workspace):
        mcp.run()
