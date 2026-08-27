"""The exact v0.3 FastMCP boundary."""

from __future__ import annotations

import base64
import json
import os
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import Field, StrictBool, StrictInt, StrictStr
from pydantic.functional_validators import AfterValidator

from rob2_kit.application.contracts import TOOL_NAMES, WorkflowConflict
from rob2_kit.application.domains import get_domain_context as _get_domain_context
from rob2_kit.application.domains import save_domain_judgment as _save_domain_judgment
from rob2_kit.application.evidence import list_sources as _list_sources
from rob2_kit.application.evidence import read_pages as _read_pages
from rob2_kit.application.evidence import render_page as _render_page
from rob2_kit.application.evidence import search_sources as _search_sources
from rob2_kit.application.evidence import (
    select_text_evidence_by_lines as _select_text_evidence_by_lines,
)
from rob2_kit.application.evidence import select_visual_evidence as _select_visual_evidence
from rob2_kit.application.finalization import finalize_batch as _finalize_batch
from rob2_kit.application.intake import prepare_batch_for_outcome as _prepare_batch
from rob2_kit.application.proposal import save_proposal as _save_proposal
from rob2_kit.application.status import get_status as _get_status
from rob2_kit.application.status import get_status_head as _get_status_head
from rob2_kit.application.trials import request_trial_terminal as _request_trial_terminal
from rob2_kit.workflow_models import (
    DomainAnswer,
    DomainDraft,
    DomainId,
    DomainRevisionBasis,
    ExpectedRevision,
    Identity,
    MultipleConcernsDecision,
    NormalizedCoordinate,
    PageNumber,
    ProposalDraft,
    ResultChoiceDraft,
    SourceId,
    TerminalRequest,
    TerminalRequestEnvelope,
    TrialId,
    VisualTranscription,
)

from .contracts import normalize, output_schema, validate_output

mcp = FastMCP("rob2-kit")
PUBLIC_TOOL_NAMES = TOOL_NAMES
SearchLimit = Annotated[StrictInt, Field(ge=1, le=100)]
Inline = StrictBool
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
_MUTATION = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
_INTAKE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
)


def _workspace() -> str:
    return os.environ.get("ROB2_WORKSPACE", ".")


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("requested_outcome must contain non-whitespace content")
    return value


RequestedOutcome = Annotated[
    StrictStr,
    Field(
        min_length=1,
        description=(
            "Outcome concept to assess across Trials; preserve the researcher's wording and "
            "omit Trial names and scope phrases."
        ),
    ),
    AfterValidator(_nonblank),
]


def _content(tool: str, value: dict[str, Any]) -> ToolResult:
    # Pixel bytes are transport content, never part of the typed JSON receipt.
    png_bytes = value.get("_png_bytes")
    value = {key: item for key, item in value.items() if key != "_png_bytes"}
    if tool != "get_status":
        current = _get_status_head(_workspace())
        value = {
            **value,
            "phase": current.get("phase", "empty"),
            "state_revision": current.get("state_revision", 0),
            "continuation": value.get("continuation", current.get("continuation")),
            "authoritative_wording": current.get("authoritative_wording"),
        }
    normalized = validate_output(tool, normalize(tool, value))
    outcome = str(normalized["outcome"])
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=f"{outcome}; inspect structured content.")
    ]
    if isinstance(png_bytes, bytes):
        content.append(
            ImageContent(
                type="image", data=base64.b64encode(png_bytes).decode("ascii"), mimeType="image/png"
            )
        )
    return ToolResult(content=content, structured_content=normalized)


def _invoke(tool: str, operation: Any) -> ToolResult:
    try:
        return _content(tool, operation())
    except WorkflowConflict as error:
        return _content(
            tool,
            {
                "outcome": "conflict",
                "code": "workflow_conflict",
                "expected_revision": error.expected,
                "current_revision": error.actual,
            },
        )
    except ValueError as error:
        condition = str(error)
        if tool in {
            "get_domain_context",
            "save_domain_judgment",
            "request_trial_terminal",
            "finalize_batch",
        }:
            # Application operations own lifecycle enforcement. Inspect status
            # only after rejection so successful Domain writes do not pay for a
            # redundant preflight query.
            head = _get_status_head(_workspace())
            continuation = head.get("continuation")
            next_operation = (
                continuation.get("operation") if isinstance(continuation, dict) else None
            )
            if next_operation == "researcher_review":
                condition = (
                    "Stop: Proposal Review is pending. Do not perform or report Domain "
                    "judgments. Present the exact Proposal Review. After researcher approval, "
                    "call get_status and follow next_action."
                )
            elif tool == "finalize_batch" and next_operation != "finalize_batch":
                condition = (
                    "finalize_batch is available only when next_action.operation is "
                    "finalize_batch; call get_status and follow next_action."
                )
            elif tool != "finalize_batch" and head.get("phase") not in {
                "assessment",
                "ready_to_finalize",
            }:
                condition = (
                    f"{tool} is available only during Domain assessment; call get_status "
                    "and follow next_action."
                )
        return _content(
            tool,
            {
                "outcome": "condition",
                "code": "invalid_request",
                "condition": condition,
            },
        )


@mcp.resource(
    "rob2://current-batch",
    description="Read current batch status. Returns the authoritative workflow snapshot.",
)
def current_batch() -> str:
    receipt = _content("get_status", _get_status(_workspace()))
    return json.dumps(receipt.structured_content, sort_keys=True)


@mcp.tool(
    name="prepare_batch",
    description=(
        "Start or retry intake for one requested outcome. The server discovers every immediate "
        "non-hidden, non-link Trial directory under input/{TRIAL NAME}/ and captures its sources; "
        "call this directly without listing input. requested_outcome is only the clinical outcome "
        "concept, without task framing, risk-of-bias wording, or Trial scope."
    ),
    annotations=_INTAKE,
    output_schema=output_schema("prepare_batch"),
)
def prepare_batch(
    requested_outcome: RequestedOutcome,
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Revision from the latest status.")
    ],
) -> ToolResult:
    return _invoke(
        "prepare_batch",
        lambda: _prepare_batch(_workspace(), requested_outcome, expected_revision),
    )


@mcp.tool(
    name="get_status",
    description="Read workflow status. Returns phase, revision, dispositions, and next action.",
    annotations=_READ_ONLY,
    output_schema=output_schema("get_status"),
)
def get_status() -> ToolResult:
    return _invoke("get_status", lambda: _get_status(_workspace()))


@mcp.tool(
    name="list_sources",
    description="List captured sources. Requires a Trial ID for multi-Trial batches.",
    annotations=_READ_ONLY,
    output_schema=output_schema("list_sources"),
)
def list_sources(
    trial_id: Annotated[
        TrialId | None,
        Field(description="Captured Trial ID; omit only when the batch has one Trial."),
    ] = None,
) -> ToolResult:
    return _invoke("list_sources", lambda: _list_sources(_workspace(), trial_id))


@mcp.tool(
    name="search_sources",
    description=(
        "Search captured source-page text. Returned page values are 1-based source indexes, not "
        "printed page labels. Use phrase only for known contiguous wording; use all or any for "
        "concept discovery. Returns bounded hits, total_matches, truncated, and an opaque "
        "search_receipt in data, including for valid no-hit searches; refine a truncated search "
        "before treating discovery as complete or using it for absence."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("search_sources"),
)
def search_sources(
    trial_id: Annotated[TrialId, Field(description="Captured Trial to search.")],
    query: Annotated[str, Field(min_length=1, description="Non-empty text query.")],
    source_id: Annotated[
        SourceId | None,
        Field(
            description=(
                "Optional captured Source ID. When supplied, search only this Source; omit for "
                "the Trial's normal source-priority search."
            )
        ),
    ] = None,
    mode: Annotated[
        Literal["all", "phrase", "any", "prefix"],
        Field(
            description=(
                "Mode: all=every token on the same page; phrase=adjacent ordered tokens; "
                "any=at least one token; prefix=token-prefix."
            )
        ),
    ] = "all",
    limit: Annotated[
        SearchLimit, Field(description="Maximum number of matching pages (1-100); default 10.")
    ] = 10,
) -> ToolResult:
    return _invoke(
        "search_sources",
        lambda: _search_sources(_workspace(), trial_id, query, mode, limit, source_id),
    )


@mcp.tool(
    name="read_pages",
    description=(
        "Read exact captured source-page text as numbered lines. Page numbers are 1-based "
        "source indexes, not printed labels. Use the issued line numbers with "
        "select_text_evidence; only copy a unique boundary substring when trimming shared first "
        "or last lines. Never reconstruct PDF text. Every requested page must be valid; mixed "
        "valid/invalid requests fail atomically. Pass page numbers in pages; there is no limit "
        "or range parameter."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("read_pages"),
)
def read_pages(
    trial_id: Annotated[TrialId, Field(description="Captured Trial containing the source.")],
    source_id: Annotated[SourceId, Field(description="Server-issued source ID from list_sources.")],
    pages: Annotated[
        list[PageNumber],
        Field(min_length=1, max_length=10, description="One to ten 1-based page numbers to read."),
    ],
) -> ToolResult:
    def read() -> dict[str, Any]:
        result = _read_pages(_workspace(), trial_id, source_id, pages)
        numbered_pages = []
        for item in result["pages"]:
            lines = item["text"].splitlines()
            numbered_pages.append(
                {
                    "page": item["page"],
                    "numbered_text": "\n".join(
                        f"{line_number:04d}|{line}" for line_number, line in enumerate(lines, 1)
                    ),
                    "line_count": len(lines),
                }
            )
        return {"outcome": "success", "pages": numbered_pages}

    return _invoke("read_pages", read)


@mcp.tool(
    name="select_text_evidence",
    description=(
        "Select one contiguous range of numbered lines from one read_pages page. Use the "
        "1-based source page and line numbers exactly as issued; split a page-boundary passage "
        "into one selection per page. If the desired passage shares its first or last line with "
        "other text, copy a unique start_text or end_text from that boundary line to trim it. "
        "The server stores the exact unnumbered source text. Use visual Evidence when layout, "
        "symbols, or figure structure carry the meaning."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("select_text_evidence"),
)
def select_text_evidence(
    trial_id: Annotated[TrialId, Field(description="Captured Trial containing the source.")],
    source_id: Annotated[SourceId, Field(description="Server-issued source ID from list_sources.")],
    page: Annotated[PageNumber, Field(description="1-based page containing the passage.")],
    start_line: Annotated[
        StrictInt,
        Field(ge=1, description="First numbered read_pages line to include."),
    ],
    end_line: Annotated[
        StrictInt,
        Field(ge=1, description="Last numbered read_pages line to include, inclusive."),
    ],
    start_text: Annotated[
        StrictStr | None,
        Field(
            min_length=1,
            description=(
                "Optional unique text within start_line where the selection begins; omit when "
                "the whole first line belongs to the passage."
            ),
        ),
    ] = None,
    end_text: Annotated[
        StrictStr | None,
        Field(
            min_length=1,
            description=(
                "Optional unique text within end_line where the selection ends; omit when the "
                "whole last line belongs to the passage."
            ),
        ),
    ] = None,
) -> ToolResult:
    return _invoke(
        "select_text_evidence",
        lambda: _select_text_evidence_by_lines(
            _workspace(),
            trial_id,
            source_id,
            page,
            start_line,
            end_line,
            start_text,
            end_text,
        ),
    )


@mcp.tool(
    name="render_page",
    description=(
        "Render one PDF page. Returns metadata and pixels as ImageContent by default; "
        "pass inline=false for metadata/cache-only use."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("render_page"),
)
def render_page(
    trial_id: Annotated[TrialId, Field(description="Captured Trial containing the source.")],
    source_id: Annotated[SourceId, Field(description="Server-issued source ID from list_sources.")],
    page: Annotated[PageNumber, Field(description="1-based PDF page to render.")],
    inline: Annotated[
        Inline,
        Field(
            description=(
                "Return pixels as MCP ImageContent; default is true, while false is "
                "metadata/cache-only."
            )
        ),
    ] = True,
) -> ToolResult:
    return _invoke(
        "render_page", lambda: _render_page(_workspace(), trial_id, source_id, page, inline)
    )


@mcp.tool(
    name="select_visual_evidence",
    description=(
        "Record visual Evidence from a rendered page. Transcription must be one exact, "
        "self-contained account containing every applicable title, axis, series, label, value, "
        "unit, uncertainty, denominator, and footnote."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("select_visual_evidence"),
)
def select_visual_evidence(
    trial_id: Annotated[TrialId, Field(description="Captured Trial containing the source.")],
    source_id: Annotated[SourceId, Field(description="Server-issued source ID from list_sources.")],
    render_identity: Annotated[
        Identity, Field(description="Render identity returned by render_page.")
    ],
    transcription: Annotated[
        VisualTranscription,
        Field(
            min_length=1,
            description=(
                "One exact self-contained account of the region containing every applicable "
                "title, axis, series, label, value, unit, uncertainty, denominator, and footnote."
            ),
        ),
    ],
    region: tuple[
        NormalizedCoordinate, NormalizedCoordinate, NormalizedCoordinate, NormalizedCoordinate
    ] = Field(
        description=("Normalized x0,y0,x1,y1 bounds in [0,1]; use [0,0,1,1] for the whole page."),
    ),
) -> ToolResult:
    return _invoke(
        "select_visual_evidence",
        lambda: _select_visual_evidence(
            _workspace(), trial_id, source_id, render_identity, transcription, list(region)
        ),
    )


@mcp.tool(
    name="save_proposal",
    description=(
        "Submit one typed Result card per Trial after selecting its supporting Evidence. "
        "Every results item has kind=assessable or kind=unavailable; an Evidence object is "
        "never a Result card. "
        "For an assessable Result, one selected passage, table block, or figure must join an "
        "endpoint identifier to one complete quantitative tuple. "
        "The server binds already-selected Evidence and keeps only material used by the Result. "
        "Proposal Review is the only researcher gate; revise and resubmit before approval "
        "if the source-reported candidate is wrong."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("save_proposal"),
)
def save_proposal(
    results: Annotated[
        list[ResultChoiceDraft],
        Field(
            min_length=1,
            description=(
                "One typed Result card per Trial. Select supporting Evidence first; do not "
                "submit an Evidence object as a Result or repeat Evidence handles in the card. "
                "Revise before researcher approval when "
                "another source-reported candidate is better."
            ),
        ),
    ],
    expected_revision: Annotated[
        ExpectedRevision,
        Field(description="Current revision from get_status; required for a non-stale proposal."),
    ],
) -> ToolResult:
    proposal = ProposalDraft(results=tuple(results), expected_revision=expected_revision)
    return _invoke("save_proposal", lambda: _save_proposal(_workspace(), proposal))


@mcp.tool(
    name="get_domain_context",
    description=(
        "Read active RoB 2 question cards after get_status reports "
        "next_action.operation=get_domain_context. Before saving, perform the bounded "
        "question-specific discovery required by the returned cards; read positive hits "
        "and do not claim missing information from Result Evidence alone."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("get_domain_context"),
)
def get_domain_context(
    trial_id: Annotated[
        TrialId | None, Field(description="Captured Trial whose result is being assessed.")
    ] = None,
    domain_id: Annotated[
        DomainId | None,
        Field(description="RoB 2 Domain ID; omit to receive the current active Domain."),
    ] = None,
) -> ToolResult:
    return _invoke(
        "get_domain_context", lambda: _get_domain_context(_workspace(), trial_id, domain_id)
    )


@mcp.tool(
    name="save_domain_judgment",
    description=(
        "Save one RoB 2 Domain judgment after get_domain_context; call only during active "
        "Domain assessment and after its bounded question-specific source searches. Every "
        "Evidence premise must state the question proposition; treatment assignment alone "
        "does not prove awareness, differential measurement, or lack of analysis choices. "
        "Supply every active question. Extra inactive future branch answers are ignored."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("save_domain_judgment"),
)
def save_domain_judgment(
    trial_id: Annotated[TrialId, Field(description="Trial being assessed.")],
    domain_id: Annotated[DomainId, Field(description="RoB 2 Domain being assessed.")],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current revision from get_domain_context.")
    ],
    answers: Annotated[
        list[DomainAnswer],
        Field(
            description=(
                "One typed answer for every active question. Inactive branch answers are "
                "ignored and never committed."
            )
        ),
    ],
    multiple_concerns: Annotated[
        MultipleConcernsDecision | None,
        Field(description="Optional Domain 2 multiple-concerns decision."),
    ] = None,
    supersedes: Annotated[
        Identity | None,
        Field(description="Exact prior checkpoint identity when revising a Domain."),
    ] = None,
    revision_basis: Annotated[
        DomainRevisionBasis | None,
        Field(description="Closed new_evidence or self_correction basis for a revision."),
    ] = None,
) -> ToolResult:
    draft = DomainDraft(
        trial_id=trial_id,
        domain_id=domain_id,
        expected_revision=expected_revision,
        answers=tuple(answers),
        multiple_concerns=multiple_concerns,
        supersedes=supersedes,
        revision_basis=revision_basis,
    )
    return _invoke("save_domain_judgment", lambda: _save_domain_judgment(_workspace(), draft))


@mcp.tool(
    name="request_trial_terminal",
    description=(
        "Request a needs_input or failed terminal only when the Trial cannot continue after "
        "ordinary conservative Domain work. Do not use it for missing direct evidence, repairs, "
        "unfinished source review, context or token limits, or uncertainty answerable as "
        "probably_yes, probably_no, or no_information under the question card."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("request_trial_terminal"),
)
def request_trial_terminal(
    request: Annotated[
        TerminalRequest,
        Field(
            description=(
                "Typed terminal for a Trial that cannot continue after ordinary conservative "
                "Domain work; not a shortcut for evidence or workflow incompleteness."
            )
        ),
    ],
    expected_revision: Annotated[ExpectedRevision, Field(description="Revision from get_status.")],
) -> ToolResult:
    envelope = TerminalRequestEnvelope(request=request, expected_revision=expected_revision)
    return _invoke(
        "request_trial_terminal", lambda: _request_trial_terminal(_workspace(), envelope)
    )


@mcp.tool(
    name="finalize_batch",
    description=(
        "Finalize terminal Trial assessments only when get_status reports "
        "next_action.operation=finalize_batch."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("finalize_batch"),
)
def finalize_batch(
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current state revision from get_status.")
    ],
) -> ToolResult:
    return _invoke("finalize_batch", lambda: _finalize_batch(_workspace(), expected_revision))


def main() -> None:
    mcp.run()


__all__ = ["PUBLIC_TOOL_NAMES", "current_batch", "main", "mcp"]
