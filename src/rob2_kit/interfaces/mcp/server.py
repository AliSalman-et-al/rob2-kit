"""The exact v0.5 FastMCP boundary."""

from __future__ import annotations

import base64
import json
import os
from typing import Annotated, Any, Literal

import mcp_types
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.context import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import InputRequiredToolResult, ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator
from pydantic.functional_validators import AfterValidator, BeforeValidator

from rob2_kit import __version__
from rob2_kit.application.contracts import TOOL_NAMES, WorkflowConflict
from rob2_kit.application.domains import get_domain_context as _get_domain_context
from rob2_kit.application.domains import save_domain_judgment as _save_domain_judgment
from rob2_kit.application.evidence import list_sources as _list_sources
from rob2_kit.application.evidence import read_pages as _read_pages
from rob2_kit.application.evidence import record_read_coverage as _record_read_coverage
from rob2_kit.application.evidence import render_page as _render_page
from rob2_kit.application.evidence import search_sources as _search_sources
from rob2_kit.application.evidence import (
    select_text_evidence_by_lines as _select_text_evidence_by_lines,
)
from rob2_kit.application.evidence import select_visual_evidence as _select_visual_evidence
from rob2_kit.application.finalization import finalize_batch as _finalize_batch
from rob2_kit.application.intake import approve_review as _approve_review
from rob2_kit.application.intake import prepare_batch_for_outcome as _prepare_batch
from rob2_kit.application.intake import proposal_approval_context as _proposal_approval_context
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
    MainReportScopeDraft,
    MissingDataRow,
    MultipleConcernsDecision,
    NormalizedCoordinate,
    PageNumber,
    ProposalDraft,
    ResultChoiceDraft,
    SourceId,
    StrictModel,
    TerminalRequest,
    TerminalRequestEnvelope,
    TrialId,
    VisualTranscription,
)

from .contracts import normalize, output_schema, validate_output

mcp = FastMCP(
    "rob2-kit",
    version=__version__,
    website_url="https://github.com/AliSalman-et-al/rob2-kit",
    # JSON arrays and enum values must be decoded by Pydantic before invoking
    # the typed workflow models. FastMCP 4's strict adapter rejects those
    # ordinary JSON representations (tuples/enums) before our models run;
    # semantic scalar strictness remains enforced by the model fields.
    strict_input_validation=False,
)
PUBLIC_TOOL_NAMES = TOOL_NAMES


def _reject_scalar_coercion(value: Any) -> Any:
    if type(value) not in (int, bool):
        raise ValueError("JSON scalar must use its declared type")
    return value


StrictJsonInt = Annotated[StrictInt, BeforeValidator(_reject_scalar_coercion)]
StrictJsonBool = Annotated[StrictBool, BeforeValidator(_reject_scalar_coercion)]
SearchLimit = Annotated[StrictJsonInt, Field(ge=1, le=100)]
Inline = StrictJsonBool
_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_MUTATION = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_INTAKE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)

# Keep every read_pages response small enough for clients with conservative
# tool-result limits.  The application still owns the complete captured
# projection; this is only a transport window.
_READ_PAGES_RESPONSE_CHARS = 24_000


def _compact_domain_context_transport(value: dict[str, Any]) -> dict[str, Any]:
    """Order high-signal context first and drop redundant option prose."""

    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    copied = json.loads(encoded)
    data = copied.get("data")
    if not isinstance(data, dict):
        return copied
    questions = data.get("questions")
    if isinstance(questions, list):
        for card in questions:
            if not isinstance(card, dict) or not isinstance(card.get("options"), list):
                continue
            for option in card["options"]:
                if isinstance(option, dict):
                    option.pop("meaning", None)
                    option.pop("consequence", None)
    ordered = {
        key: data[key]
        for key in (
            "trial_id",
            "domain_id",
            "result",
            "answers",
            "current_checkpoint",
            "guidance",
            "response_framework",
            "traps",
            "questions",
            "completion_rule",
            "comparison_cards",
            "evidence",
            "evidence_workspace",
            "reading_recovery",
        )
        if key in data
    }
    copied["data"] = ordered
    return copied


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
            "Outcome concept to assess across Trials; preserve only the researcher's outcome "
            "wording. Omit Trial names, population, comparison, effect estimate, follow-up, and "
            "other Result-specific scope; those belong in the Proposal."
        ),
    ),
    AfterValidator(_nonblank),
]


class ReadWindow(StrictModel):
    """One independent source-page window."""

    source_id: SourceId = Field(description="Captured Source ID.")
    page: PageNumber = Field(description="One-based Source-page index.")
    start_line: StrictInt = Field(
        ge=1, default=1, description="First one-based numbered line to return."
    )
    end_line: StrictInt | None = Field(
        default=None, ge=1, description="Last one-based numbered line to return, inclusive."
    )

    @model_validator(mode="after")
    def line_range_is_ordered(self) -> ReadWindow:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


def _nonblank_trial_label(value: str) -> str:
    if not value.strip():
        raise ValueError("trial label must contain non-whitespace content")
    return value


TrialLabel = Annotated[
    StrictStr,
    Field(min_length=1, description="Exact immediate input directory label for one Trial."),
    AfterValidator(_nonblank_trial_label),
]
TrialLabels = Annotated[
    list[TrialLabel],
    Field(min_length=1),
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
    if tool == "get_domain_context":
        # Validate the compact public variant as well as the application
        # projection.  This keeps structured and text consumers on one typed
        # contract while allowing the transport-only option prose omission.
        normalized = _compact_domain_context_transport(normalized)
        validate_output(tool, normalized)
    # MCP clients are allowed to expose only ``content`` to a model.  Carry
    # the same validated object in a compact JSON text block so text-only and
    # structured consumers receive identical workflow state.  Images remain
    # separate binary content and are intentionally not duplicated in JSON.
    content: list[TextContent | ImageContent] = [
        TextContent(
            type="text",
            text=json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=tool != "get_domain_context",
            ),
        )
    ]
    if isinstance(png_bytes, bytes):
        content.append(
            ImageContent(
                type="image",
                data=base64.b64encode(png_bytes).decode("ascii"),
                mime_type="image/png",
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
        if condition.startswith("search_cursor_stale:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "search_cursor_stale",
                    "condition": condition.removeprefix("search_cursor_stale:"),
                },
            )
        if condition.startswith("search_cursor_expired:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "search_cursor_expired",
                    "condition": condition.removeprefix("search_cursor_expired:"),
                },
            )
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
    title="Current batch status",
    description="Read current batch status. Returns the authoritative workflow snapshot.",
    mime_type="application/json",
)
def current_batch() -> str:
    receipt = _content("get_status", _get_status(_workspace()))
    return json.dumps(receipt.structured_content, sort_keys=True)


@mcp.tool(
    name="prepare_batch",
    title="Prepare batch",
    description=(
        "Use requested_outcome only for the outcome concept, excluding population, comparison, "
        "effect estimate, follow-up, and other Result facets. If the user names Trials, pass their "
        "exact input directory labels in trial_labels. Omit trial_labels to capture all immediate "
        "valid Trial directories. The server resolves directories, so no listing is required."
    ),
    annotations=_INTAKE,
    output_schema=output_schema("prepare_batch"),
)
def prepare_batch(
    requested_outcome: RequestedOutcome,
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Revision from the latest status.")
    ],
    trial_labels: Annotated[
        TrialLabels | None,
        Field(description="Exact input/{TRIAL NAME} directory labels. Omit to capture all."),
    ] = None,
) -> ToolResult:
    return _invoke(
        "prepare_batch",
        lambda: _prepare_batch(_workspace(), requested_outcome, expected_revision, trial_labels),
    )


@mcp.tool(
    name="get_status",
    title="Get workflow status",
    description=(
        "Read phase, revision, dispositions, next action, and main-report reading status. "
        "Check after bounded reads to determine whether the required pass is finished."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("get_status"),
)
def get_status() -> ToolResult:
    return _invoke("get_status", lambda: _get_status(_workspace()))


@mcp.tool(
    name="list_sources",
    title="List Trial sources",
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
    title="Search Trial sources",
    description=(
        "Search captured source pages (1-based source indexes). Required: trial_id, query, mode. "
        "Choose all for every token, phrase for known contiguous wording, any for broad OR "
        "discovery, or prefix for token-prefix matching. Optional: source_id, limit, cursor. "
        "Returns a "
        "bounded first batch with a stable session, counts, truncation, and opaque receipt; "
        "continue with next_cursor for the same ranking. Valid no-hit searches are returned; "
        "zero hits are specific only to the issued lexical query and never establish scientific "
        "absence; "
        "an initial multi-token all or phrase no-hit includes one executable any broadening "
        "step, while a broad truncated any response includes observable refinement advice; "
        "neither is a scientific conclusion."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("search_sources"),
)
def search_sources(
    trial_id: Annotated[
        TrialId, Field(description="Captured Trial to search.", examples=["trial-a"])
    ],
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="Concept or wording to search; must be non-empty.",
            examples=["central randomization"],
        ),
    ],
    mode: Annotated[
        Literal["all", "phrase", "any", "prefix"],
        Field(
            description=(
                "Required lexical intent: all=every token on one page; phrase=known contiguous "
                "wording; any=one token for broad discovery; prefix=token prefix."
            )
        ),
    ],
    source_id: Annotated[
        SourceId | None,
        Field(description="Optional Source ID; omit for all Trial sources in priority order."),
    ] = None,
    limit: Annotated[
        SearchLimit,
        Field(description="Maximum candidate passages returned in this batch (1-100); default 10."),
    ] = 10,
    cursor: Annotated[
        str | None,
        Field(description="Opaque continuation cursor returned by the prior search response."),
    ] = None,
) -> ToolResult:
    return _invoke(
        "search_sources",
        lambda: _search_sources(_workspace(), trial_id, query, mode, limit, source_id, cursor),
    )


@mcp.tool(
    name="read_pages",
    title="Read source pages",
    description=(
        "Read source text as numbered lines. Pages are 1-based source indexes, not printed "
        "labels; continue large pages with next_start_line. Use windows across sources; each "
        "item preserves its source and line bounds."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("read_pages"),
)
def read_pages(
    trial_id: Annotated[
        TrialId,
        Field(description="Captured Trial that owns the Source pages; required for every read."),
    ],
    source_id: Annotated[
        SourceId | None, Field(description="Source ID for a single-source read.")
    ] = None,
    pages: Annotated[
        list[PageNumber] | None,
        Field(
            min_length=1,
            max_length=10,
            description="One to ten integer source-page indexes, for example [1, 3].",
            examples=[[1, 3]],
        ),
    ] = None,
    start_line: Annotated[
        StrictInt,
        Field(
            ge=1,
            description="First line; use next_start_line to continue.",
            examples=[1],
        ),
    ] = 1,
    windows: Annotated[
        list[ReadWindow] | None,
        Field(
            min_length=1,
            max_length=20,
            description=(
                "Independent Source-page windows with their own line bounds. Supply trial_id "
                "and windows without source_id, pages, or top-level start_line."
            ),
        ),
    ] = None,
) -> ToolResult:
    def read() -> dict[str, Any]:
        if trial_id is None:
            raise ValueError("trial_id is required")
        if windows is None and (source_id is None or pages is None):
            raise ValueError("source_id and pages are required unless windows is supplied")
        requests = [(trial_id, source_id, pages, start_line, None)]
        if windows:
            if source_id is not None or pages is not None or start_line != 1:
                raise ValueError("use windows alone for independent reads")
            requests = [
                (trial_id, item.source_id, [item.page], item.start_line, item.end_line)
                for item in windows
            ]
        raw_pages: list[dict[str, Any]] = []
        include_source = True
        for request_trial, request_source, request_pages, request_start, request_end in requests:
            assert request_trial is not None and request_source is not None
            result = _read_pages(_workspace(), request_trial, request_source, request_pages)
            raw_pages.extend(
                {
                    **item,
                    **({"source_id": request_source} if include_source else {}),
                    "requested_start": request_start,
                    "requested_end": request_end,
                }
                for item in result["pages"]
            )
        page_budget = max(1, _READ_PAGES_RESPONSE_CHARS // max(1, len(raw_pages)))
        numbered_pages = []
        for item in raw_pages:
            lines = item["text"].splitlines()
            requested_start = item["requested_start"]
            requested_end = item["requested_end"]
            if not lines:
                _record_read_coverage(
                    _workspace(),
                    request_trial,
                    item["source_id"],
                    item["page"],
                    0,
                    0,
                )
                numbered_pages.append(
                    {
                        **({"source_id": item["source_id"]} if include_source else {}),
                        "page": item["page"],
                        "numbered_text": "",
                        "line_count": 0,
                        "returned_start_line": requested_start,
                        "returned_end_line": 0,
                        "truncated": False,
                        "next_start_line": None,
                        "passage_ref": None,
                    }
                )
                continue
            if requested_start > len(lines):
                raise ValueError(
                    f"start_line {requested_start} is outside page {item['page']}; "
                    f"choose 1 <= start_line <= {len(lines)}"
                )
            returned: list[str] = []
            used = 0
            end_line = requested_start - 1
            for line_number in range(requested_start, len(lines) + 1):
                if requested_end is not None and line_number > requested_end:
                    break
                numbered = f"{line_number}|{lines[line_number - 1]}"
                additional = len(numbered) + (1 if returned else 0)
                if returned and used + additional > page_budget:
                    break
                returned.append(numbered)
                used += additional
                end_line = line_number
            truncated = end_line < len(lines) and (
                requested_end is None or end_line < requested_end
            )
            passage_ref = None
            if end_line >= requested_start:
                passage = _select_text_evidence_by_lines(
                    _workspace(),
                    request_trial,
                    item["source_id"],
                    item["page"],
                    requested_start,
                    end_line,
                )
                passage_ref = passage.get("evidence", {}).get("handle")
            numbered_pages.append(
                {
                    **({"source_id": item["source_id"]} if include_source else {}),
                    "page": item["page"],
                    "numbered_text": "\n".join(returned),
                    "line_count": len(lines),
                    "returned_start_line": requested_start,
                    "returned_end_line": end_line,
                    "truncated": truncated,
                    "next_start_line": end_line + 1 if truncated else None,
                    "passage_ref": passage_ref,
                }
            )
            if end_line >= requested_start:
                _record_read_coverage(
                    _workspace(),
                    request_trial,
                    item["source_id"],
                    item["page"],
                    requested_start,
                    end_line,
                )
        return {"outcome": "success", "pages": numbered_pages}

    return _invoke("read_pages", read)


@mcp.tool(
    name="select_text_evidence",
    title="Select text Evidence",
    description=(
        "Select one contiguous range of numbered lines from one read_pages page. The usual call "
        "needs only trial_id, source_id, page, start_line, and end_line. Use the "
        "1-based source page and line numbers exactly as issued; split a page-boundary passage "
        "into one selection per page; never reconstruct text from a preview. "
        "The server stores the exact unnumbered source text. Use visual Evidence when layout, "
        "symbols, or figure structure carry the meaning."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("select_text_evidence"),
)
def select_text_evidence(
    trial_id: Annotated[
        TrialId,
        Field(description="Captured Trial containing the source.", examples=["trial-a"]),
    ],
    source_id: Annotated[SourceId, Field(description="Server-issued source ID from list_sources.")],
    page: Annotated[
        PageNumber, Field(description="1-based page containing the passage.", examples=[7])
    ],
    start_line: Annotated[
        StrictInt,
        Field(ge=1, description="First numbered read_pages line to include.", examples=[5]),
    ],
    end_line: Annotated[
        StrictInt,
        Field(
            ge=1,
            description="Last numbered read_pages line to include, inclusive.",
            examples=[8],
        ),
    ],
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
        ),
    )


@mcp.tool(
    name="render_page",
    title="Render source page",
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
    title="Select visual Evidence",
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
    title="Save Result proposal",
    description=(
        "Submit typed Result cards after the required bounded main-article text pass and selecting "
        "supporting Evidence. The first save needs one "
        "card per Trial; a pending Review accepts only cards being replaced and preserves the "
        "rest. Each card is assessable or unavailable (Evidence is separate). Assessable cards "
        "require target facets, at least two randomized groups, intended population/effect "
        "measure, and one complete "
        "reported quantitative tuple. Keep source numbers as strings; revise before approval."
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
                "Initial save: one typed Result card per Trial. Pending Review: only cards to "
                "replace; unmentioned cards are preserved. Select Evidence first. Result kind is "
                "assessable or unavailable; narrative, table, and figure are Evidence kinds."
            ),
        ),
    ],
    expected_revision: Annotated[
        ExpectedRevision,
        Field(description="Current revision from get_status; required for a non-stale proposal."),
    ],
    main_report_scopes: Annotated[
        list[MainReportScopeDraft] | None,
        Field(
            description=(
                "Optional per-Trial suffix scope. Omit for full main-Source scope. A shortened "
                "scope needs boundary Evidence and a reason; the reading ceiling still applies."
            )
        ),
    ] = None,
) -> ToolResult:
    proposal = ProposalDraft(
        results=tuple(results),
        main_report_scopes=tuple(main_report_scopes or ()),
        expected_revision=expected_revision,
    )
    return _invoke("save_proposal", lambda: _save_proposal(_workspace(), proposal))


class ProposalApprovalDecision(StrictModel):
    approved: StrictBool = Field(
        title="Approve Proposal Review",
        description=(
            "Approve the exact displayed Result mapping and begin automated RoB 2 assessment."
        ),
    )


@mcp.tool(
    name="request_proposal_approval",
    title="Request Proposal approval",
    description=(
        "After the researcher explicitly approves the current Proposal Review in conversation, "
        "ask the client to confirm that exact immutable Review. This tool has no approval "
        "arguments: only a directly accepted elicitation with approved=true commits it. "
        "For corrections, inspect Sources and replace each corrected Trial's complete Result "
        "card with save_proposal."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("request_proposal_approval"),
)
async def request_proposal_approval(ctx: Context) -> ToolResult:
    approval_context = _proposal_approval_context(_workspace())
    review = approval_context.review
    if not isinstance(review, dict) or review.get("purpose") != "proposal":
        if approval_context.acknowledgment is not None:
            approved = _approve_review(
                _workspace(),
                None,
                caller="researcher",
                method="mcp_elicitation",
            )
            return _content("request_proposal_approval", approved)
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_review_not_pending",
                "condition": "Proposal Review is not pending.",
            },
        )
    review_reference = review.get("identity")
    if not isinstance(review_reference, str):
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_approval_stale",
                "condition": "The pending Proposal Review identity is invalid.",
            },
        )
    capabilities = getattr(ctx.session, "client_capabilities", None)
    if capabilities is None or getattr(capabilities, "elicitation", None) is None:
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_approval_unsupported",
                "condition": "The connected client does not support researcher elicitation.",
            },
        )
    # MCP 2026-07-28 removed server-initiated back-channel elicitation.  Use
    # FastMCP 4's supported guard/result round trip there; the echoed state
    # binds the accepted response to this exact pending review.  Older
    # negotiated protocol versions continue through ctx.elicit below.
    if getattr(ctx, "_is_modern_protocol", lambda: False)():
        responses = ctx.input_responses
        if responses is None:
            request = mcp_types.ElicitRequest(
                params=mcp_types.ElicitRequestFormParams(
                    message=(
                        "Confirm whether to approve this exact Proposal Review. Decline or "
                        "cancel to leave it pending.\n" + json.dumps(review, sort_keys=True)
                    ),
                    requested_schema=ProposalApprovalDecision.model_json_schema(),
                )
            )
            return InputRequiredToolResult(
                mcp_types.InputRequiredResult(
                    input_requests={"proposal_review": request},
                    request_state=review_reference,
                )
            )
        if ctx.request_state != review_reference:
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_stale",
                    "condition": "The Proposal Review response is stale or mismatched.",
                },
            )
        response = responses.get("proposal_review")
        if not isinstance(response, mcp_types.ElicitResult):
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_unsupported",
                    "condition": "The connected client did not return an elicitation response.",
                },
            )
        if response.action == "cancel":
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_cancelled",
                    "condition": "cancel",
                },
            )
        if response.action == "decline":
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_declined",
                    "condition": "decline",
                },
            )
        try:
            decision = ProposalApprovalDecision.model_validate(response.content or {})
        except ValueError:
            decision = None
        if decision is None or not decision.approved:
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_declined",
                    "condition": "The researcher did not approve the Proposal Review.",
                },
            )
        try:
            approved = _approve_review(
                _workspace(), review_reference, caller="researcher", method="mcp_elicitation"
            )
        except ValueError as error:
            return _content(
                "request_proposal_approval",
                {
                    "outcome": "condition",
                    "code": "proposal_approval_stale",
                    "condition": str(error),
                },
            )
        return _content("request_proposal_approval", approved)
    try:
        response = await ctx.elicit(
            "Confirm whether to approve this exact Proposal Review. Decline or cancel to leave "
            "it pending.\n" + json.dumps(review, sort_keys=True),
            ProposalApprovalDecision,
        )
    except (MCPError, ToolError):
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_approval_unsupported",
                "condition": "The connected client does not support researcher elicitation.",
            },
        )
    if isinstance(response, (DeclinedElicitation, CancelledElicitation)):
        code = (
            "proposal_approval_declined"
            if isinstance(response, DeclinedElicitation)
            else "proposal_approval_cancelled"
        )
        return _content(
            "request_proposal_approval",
            {"outcome": "condition", "code": code, "condition": response.action},
        )
    if not isinstance(response, AcceptedElicitation) or not response.data.approved:
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_approval_declined",
                "condition": "The researcher did not approve the Proposal Review.",
            },
        )
    try:
        approved = _approve_review(
            _workspace(),
            review_reference,
            caller="researcher",
            method="mcp_elicitation",
        )
    except ValueError as error:
        return _content(
            "request_proposal_approval",
            {
                "outcome": "condition",
                "code": "proposal_approval_stale",
                "condition": str(error),
            },
        )
    return _content("request_proposal_approval", approved)


@mcp.tool(
    name="get_domain_context",
    title="Get Domain context",
    description=(
        "Read the approved Result, current checkpoint, Evidence workspace, comparison cards, "
        "and questions for a Domain. Question cards contain scientific guidance, activation "
        "predicates, server-issued answer options, and executable search suggestions. "
        "Before the first Domain answer, repeat the bounded main-report text pass after approval. "
        "Reuse adequate Evidence. Search unresolved premises with wording from inspected Sources. "
        "For a D3 count preview, pass missing_data; the call does not commit those rows. "
        "If omitted Evidence is unfamiliar or uncertain after a restart or compaction, call "
        "read_pages with recovery.trial_id and recovery.windows. Use the returned revision and "
        "option IDs when saving active answers."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("get_domain_context"),
)
def get_domain_context(
    trial_id: Annotated[
        TrialId | None,
        Field(
            description=(
                "Exact Trial whose approved Result and current Domain checkpoint this call reads."
            )
        ),
    ] = None,
    domain_id: Annotated[
        DomainId | None,
        Field(description="RoB 2 Domain ID; omit to receive the current active Domain."),
    ] = None,
    missing_data: Annotated[
        list[MissingDataRow] | None,
        Field(
            description=(
                "Optional D3.1 count rows to preview scope-matched arithmetic before answering. "
                "Each preview row requires a nonempty basis of current-Trial Evidence references; "
                "there is no answer Evidence to inherit. "
                "The preview neither commits rows nor establishes that counts were extracted "
                "correctly. Submit chosen rows with D3.1 when saving; row basis may then be "
                "omitted to reuse the answer Evidence."
            )
        ),
    ] = None,
) -> ToolResult:
    return _invoke(
        "get_domain_context",
        lambda: _get_domain_context(
            _workspace(),
            trial_id,
            domain_id,
            [row.model_dump(mode="json", exclude_none=True) for row in missing_data]
            if missing_data is not None
            else None,
        ),
    )


@mcp.tool(
    name="save_domain_judgment",
    title="Save Domain judgment",
    description=(
        "Atomically save answers for one Domain of the Trial's approved Result. Complete the "
        "post-approval bounded main-report text pass before the first Domain save. Supply a "
        "current option ID and bases for every active question. Inactive answers are ignored. "
        "Invalid input returns grouped repairs without "
        "committing. Before saving, check each basis against the approved Result and literal "
        "question; justify any inference or unresolved linkage. "
        "The fifth accepted Domain freezes the Trial snapshot and advances "
        "next_action; no separate Trial-finalization call is required."
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
            min_length=1,
            description=(
                "One typed answer per active question: question_id, option_id, bases. Definitive "
                "yes/no needs direct/indirect/contradictory Evidence; probable answers may use "
                "limitation, absence receipt, context, or inference. List, not map; inactive "
                "branches ignored."
            ),
            examples=[
                [
                    {
                        "question_id": "sq:randomization:sequence",
                        "option_id": "opt_0123456789abcdef01234567",
                        "bases": [
                            {
                                "kind": "direct_support",
                                "evidence": "eh_0123456789abcdef",
                            }
                        ],
                    }
                ]
            ],
        ),
    ],
    multiple_concerns: Annotated[
        MultipleConcernsDecision | None,
        Field(
            description=(
                "Omit unless a repair requests it. Object only: raises_overall_to_high:boolean, "
                "rationale:string; never boolean/string."
            ),
            examples=[
                {
                    "raises_overall_to_high": False,
                    "rationale": "Concerns remain below threshold.",
                }
            ],
        ),
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
    title="Request Trial terminal",
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
    title="Finalize batch",
    description=(
        "Package the already-final Trial records into the verified Batch artifact. Call only "
        "when get_status reports next_action.operation=finalize_batch; this operation does "
        "not complete an individual Trial."
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
