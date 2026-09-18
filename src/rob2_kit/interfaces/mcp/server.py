"""The exact v0.8 FastMCP boundary."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import uuid
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
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator
from pydantic.functional_validators import AfterValidator, BeforeValidator

from rob2_kit import __version__
from rob2_kit.application._state import _db, _identity, _root, _state
from rob2_kit.application.contracts import COUNTERS, TOOL_NAMES, WorkflowConflict
from rob2_kit.application.domains import (
    _domain_context_delivery,
    _domain_context_view,
    _domain_reasoning_matches_current,
    _record_domain_context_delivery,
    _record_domain_context_view,
)
from rob2_kit.application.domains import (
    get_domain_context as _get_domain_context,
)
from rob2_kit.application.domains import save_domain_judgment as _save_domain_judgment
from rob2_kit.application.domains import (
    validate_domain_assessment as _validate_domain_assessment,
)
from rob2_kit.application.evidence import (
    _cursor_handle,
)
from rob2_kit.application.evidence import list_sources as _list_sources
from rob2_kit.application.evidence import read_pages as _read_pages
from rob2_kit.application.evidence import (
    record_read_coverage_batch as _record_read_coverage_batch,
)
from rob2_kit.application.evidence import (
    record_visual_delivery as _record_visual_delivery,
)
from rob2_kit.application.evidence import render_page as _render_page
from rob2_kit.application.evidence import (
    search_sources as _search_sources,
)
from rob2_kit.application.evidence import (
    select_text_evidence_by_lines as _select_text_evidence_by_lines,
)
from rob2_kit.application.evidence import select_visual_evidence as _select_visual_evidence
from rob2_kit.application.finalization import finalize_batch as _finalize_batch
from rob2_kit.application.intake import approve_review as _approve_review
from rob2_kit.application.intake import prepare_batch_for_outcome as _prepare_batch
from rob2_kit.application.intake import proposal_approval_context as _proposal_approval_context
from rob2_kit.application.proposal import save_proposal as _save_proposal
from rob2_kit.application.proposal import validate_proposal as _validate_proposal
from rob2_kit.application.source_handles import (
    public_source_references as _public_source_references,
)
from rob2_kit.application.source_handles import (
    resolve_source_handle as _resolve_source_handle,
)
from rob2_kit.application.status import get_status as _get_status
from rob2_kit.application.status import get_status_head as _get_status_head
from rob2_kit.application.trials import close_trial as _close_trial
from rob2_kit.application.trials import review_trial as _review_trial
from rob2_kit.application.working import save_working_checkpoint as _save_working_checkpoint
from rob2_kit.models import canonical_json_bytes
from rob2_kit.workflow_models import (
    DomainDraft,
    DomainId,
    DomainReasoningAnswer,
    DomainRevisionBasis,
    ExpectedRevision,
    Identity,
    MissingDataRow,
    NormalizedCoordinate,
    PageNumber,
    ProposalDraft,
    ProposalReasoningAssessment,
    QuestionId,
    ResultChoiceDraft,
    SourceHandle,
    StrictModel,
    TerminalRequest,
    TrialClosureRequest,
    TrialId,
    TrialReviewRequest,
    VisualTranscription,
    WorkingCheckpointDraft,
)

from .contracts import SearchBatchRequest, normalize, output_schema, validate_output

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
SourceNavigationLimit = Annotated[StrictJsonInt, Field(ge=1, le=12)]
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
_READ_PAGES_RESPONSE_BYTES = 24_000
_SEARCH_BATCH_RESPONSE_BYTES = 32_000
_DOMAIN_CONTEXT_DEFAULT_PAGE_BYTES = 32_768
_DOMAIN_CONTEXT_MIN_PAGE_BYTES = 4_096
_DOMAIN_CONTEXT_MAX_PAGE_BYTES = 131_072
_DOMAIN_CONTEXT_PAGE_HEADROOM_BYTES = 1_024
_DOMAIN_CONTEXT_RETRY_MARGIN_BYTES = 64
_DOMAIN_CONTEXT_PAGE_SECTIONS = ("questions", "comparison_cards", "evidence")


def _compact_domain_context_transport(value: dict[str, Any]) -> dict[str, Any]:
    """Order high-signal context first without dropping pack guidance."""

    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    copied = json.loads(encoded)
    data = copied.get("data")
    if not isinstance(data, dict):
        return copied
    ordered = {
        key: data[key]
        for key in (
            "trial_id",
            "domain_id",
            "pack",
            "result",
            "reading_recovery",
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
        )
        if key in data
    }
    copied["data"] = ordered
    return copied


def _domain_context_cursor(payload: dict[str, Any]) -> str:
    view_id = payload.get("view_id")
    if isinstance(view_id, str):
        if not re.fullmatch(r"[0-9a-f]{32}", view_id):
            raise ValueError("domain_context_cursor_invalid: malformed view handle")
        page_index = payload.get("page_index")
        if not isinstance(page_index, int) or page_index < 0:
            raise ValueError("domain_context_cursor_invalid: invalid cursor position")
        return f"dcp2.{view_id}.{page_index}"
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "dcp1." + base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _domain_context_digest(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode_domain_context_cursor(cursor: str) -> dict[str, Any]:
    if cursor.startswith("dcp2."):
        match = re.fullmatch(r"dcp2\.([0-9a-f]{32})\.(\d+)", cursor)
        if match is None:
            raise ValueError("domain_context_cursor_invalid: malformed cursor")
        return {"view_id": match.group(1), "page_index": int(match.group(2))}
    if not cursor.startswith("dcp1."):
        raise ValueError("domain_context_cursor_invalid: unsupported cursor")
    encoded = cursor.removeprefix("dcp1.")
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (
        binascii.Error,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        raise ValueError("domain_context_cursor_invalid: malformed cursor") from error
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(key), expected)
        for key, expected in (
            ("trial_id", str),
            ("domain_id", str),
            ("state_revision", int),
            ("page_index", int),
            ("page_size", int),
            ("digest", str),
            ("basis_identity", str),
        )
    ):
        raise ValueError("domain_context_cursor_invalid: incomplete cursor")
    if payload["state_revision"] < 0 or payload["page_index"] < 0:
        raise ValueError("domain_context_cursor_invalid: invalid cursor position")
    if not _DOMAIN_CONTEXT_MIN_PAGE_BYTES <= payload["page_size"] <= _DOMAIN_CONTEXT_MAX_PAGE_BYTES:
        raise ValueError("domain_context_cursor_invalid: invalid page size")
    return payload


def _domain_context_transport_bytes(value: dict[str, Any]) -> int:
    # JSON tools use the single structured MCP payload. Keep the budget tied
    # to the response that is actually sent, not to a duplicated text copy.
    envelope = {
        "content": [],
        "structured_content": value,
    }
    return len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _read_pages_transport_bytes(value: dict[str, Any], head: dict[str, Any]) -> int:
    """Measure the serialized envelope that the read_pages caller receives."""

    visible = {key: item for key, item in value.items() if key != "_read_coverage"}
    enriched = {
        **visible,
        "phase": head.get("phase", "empty"),
        "state_revision": head.get("state_revision", 0),
        "continuation": visible.get(
            "continuation", head.get("continuation", head.get("next_action"))
        ),
        "authoritative_wording": head.get("authoritative_wording"),
    }
    normalized = validate_output("read_pages", normalize("read_pages", enriched))
    return len(
        json.dumps(
            {"content": [], "structured_content": normalized},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _compact_read_window_fields(value: Any) -> None:
    """Keep zero/default fragment coordinates out of ordinary public windows."""

    if isinstance(value, dict):
        if all(key in value for key in ("source_id", "page", "start_line", "end_line")):
            if value.get("start_char") in (None, 0):
                value.pop("start_char", None)
            if value.get("end_char") is None:
                value.pop("end_char", None)
        for item in value.values():
            _compact_read_window_fields(item)
    elif isinstance(value, list):
        for item in value:
            _compact_read_window_fields(item)


def _domain_context_page_data(
    data: dict[str, Any],
    section: str,
    items: list[dict[str, Any]],
    page: dict[str, Any],
) -> dict[str, Any]:
    result = dict(data)
    for name in _DOMAIN_CONTEXT_PAGE_SECTIONS:
        result[name] = items if name == section else []
    result["context_page"] = page
    return result


def _domain_context_page_template(data: dict[str, Any], index: int) -> dict[str, Any]:
    result = dict(data)
    if index:
        # Result, Evidence workspace, and recovery stay on every page. The
        # long prose header is delivered on page zero and reconstructed once.
        result["guidance"] = []
        result["traps"] = []
    return result


def _paginate_domain_context_transport(
    value: dict[str, Any],
    cursor: str | None,
    requested_page_size: int | None,
    basis_identity: str,
    context_state_revision: int,
    preview_missing_data: list[dict[str, Any]] | None = None,
    view_id: str | None = None,
) -> dict[str, Any]:
    data = value.get("data")
    head = value.get("head")
    if not isinstance(data, dict) or not isinstance(head, dict):
        return value
    trial_id = data.get("trial_id")
    domain_id = data.get("domain_id")
    state_revision = context_state_revision
    if (
        not isinstance(trial_id, str)
        or not isinstance(domain_id, str)
        or not isinstance(state_revision, int)
        or not isinstance(basis_identity, str)
    ):
        return value
    digest = _domain_context_digest(data)

    if cursor is None:
        page_size = requested_page_size or _DOMAIN_CONTEXT_DEFAULT_PAGE_BYTES
        page_index = 0
    else:
        decoded = _decode_domain_context_cursor(cursor)
        if isinstance(decoded.get("view_id"), str):
            view = _domain_context_view(_root(_workspace()), decoded["view_id"])
            if view is None:
                raise ValueError("domain_context_cursor_expired: context view is unavailable")
            decoded = {
                **view,
                "page_index": decoded["page_index"],
                "missing_data": view.get("preview_scope"),
            }
        if (
            decoded["trial_id"] != trial_id
            or decoded["domain_id"] != domain_id
            or decoded["state_revision"] != state_revision
            or decoded["digest"] != digest
            or decoded["basis_identity"] != basis_identity
        ):
            raise ValueError("domain_context_cursor_stale: context identity or projection changed")
        if requested_page_size is not None and requested_page_size != decoded["page_size"]:
            raise ValueError("domain_context_cursor_invalid: page size differs from cursor")
        decoded_page_size = decoded.get("page_size")
        decoded_page_index = decoded.get("page_index")
        if not isinstance(decoded_page_size, int) or not isinstance(decoded_page_index, int):
            raise ValueError("domain_context_cursor_invalid: incomplete cursor")
        page_size = decoded_page_size
        page_index = decoded_page_index
        view_id = decoded.get("view_id")

    data_template = dict(data)
    sections: list[tuple[str, list[dict[str, Any]]]] = []
    for section in _DOMAIN_CONTEXT_PAGE_SECTIONS:
        items = data.get(section)
        if isinstance(items, list) and items:
            sections.append((section, items))
        data_template[section] = []

    if not sections:
        sections = [("complete", [])]

    # Leave room for page metadata and the opaque cursor in the structured
    # envelope. Items remain indivisible.
    working_budget = page_size - _DOMAIN_CONTEXT_PAGE_HEADROOM_BYTES
    cursor_payload = {
        "trial_id": trial_id,
        "domain_id": domain_id,
        "state_revision": state_revision,
        "page_index": 999_999,
        "page_size": page_size,
        "digest": digest,
        "basis_identity": basis_identity,
        "missing_data": preview_missing_data,
    }
    if view_id is not None:
        cursor_payload["view_id"] = view_id
    cursor_placeholder = _domain_context_cursor(cursor_payload)
    header_probe = _domain_context_page_data(
        _domain_context_page_template(data_template, 0),
        "complete",
        [],
        {
            "trial_id": trial_id,
            "domain_id": domain_id,
            "state_revision": state_revision,
            "index": 0,
            "count": 1,
            "section": "complete",
            "item_start": 0,
            "item_count": 0,
            "page_size": page_size,
            "cursor": cursor_placeholder,
            "next_cursor": cursor_placeholder,
        },
    )
    header_bytes = _domain_context_transport_bytes({**value, "data": header_probe})
    if header_bytes > working_budget:
        required_page_size = (
            header_bytes + _DOMAIN_CONTEXT_PAGE_HEADROOM_BYTES + _DOMAIN_CONTEXT_RETRY_MARGIN_BYTES
        )
        if required_page_size > _DOMAIN_CONTEXT_MAX_PAGE_BYTES:
            raise ValueError(
                "domain_context_header_unrecoverable: "
                f"required_page_size={required_page_size};maximum_page_size="
                f"{_DOMAIN_CONTEXT_MAX_PAGE_BYTES}"
            )
        raise ValueError(
            "domain_context_header_oversized: "
            f"required_page_size={required_page_size};retry with a larger page_size"
        )
    records: list[tuple[str, int, list[dict[str, Any]]]] = []
    for section, section_items in sections:
        start = 0
        while start < len(section_items) or (not section_items and start == 0):
            if not section_items:
                records.append((section, 0, []))
                break
            end = start + 1
            while end <= len(section_items):
                candidate = section_items[start:end]
                probe = _domain_context_page_data(
                    _domain_context_page_template(data_template, len(records)),
                    section,
                    candidate,
                    {
                        "trial_id": trial_id,
                        "domain_id": domain_id,
                        "state_revision": state_revision,
                        "index": 0,
                        "count": 1,
                        "section": section,
                        "item_start": start,
                        "item_count": len(candidate),
                        "page_size": page_size,
                        "cursor": cursor_placeholder,
                        "next_cursor": cursor_placeholder,
                    },
                )
                probe_value = {**value, "data": probe}
                if _domain_context_transport_bytes(probe_value) <= working_budget:
                    end += 1
                    continue
                if end == start + 1:
                    required = (
                        _domain_context_transport_bytes(probe_value)
                        + _DOMAIN_CONTEXT_PAGE_HEADROOM_BYTES
                        + _DOMAIN_CONTEXT_RETRY_MARGIN_BYTES
                    )
                    if required > _DOMAIN_CONTEXT_MAX_PAGE_BYTES:
                        raise ValueError(
                            "domain_context_item_unrecoverable: "
                            f"section={section};item_start={start};required_page_size="
                            f"{required};maximum_page_size={_DOMAIN_CONTEXT_MAX_PAGE_BYTES}"
                        )
                    raise ValueError(
                        "domain_context_item_oversized: "
                        f"section={section};item_start={start};required_page_size={required}"
                    )
                break
            chosen_end = max(start + 1, end - 1)
            records.append((section, start, section_items[start:chosen_end]))
            start = chosen_end

    if page_index >= len(records):
        raise ValueError("domain_context_cursor_invalid: page is outside this context")

    page_count = len(records)
    section, item_start, items = records[page_index]
    current_cursor = (
        _domain_context_cursor(
            {
                **cursor_payload,
                "page_index": page_index,
            }
        )
        if page_index
        else None
    )
    next_cursor = (
        _domain_context_cursor(
            {
                **cursor_payload,
                "page_index": page_index + 1,
            }
        )
        if page_index + 1 < page_count
        else None
    )
    page = {
        "trial_id": trial_id,
        "domain_id": domain_id,
        "state_revision": state_revision,
        "index": page_index,
        "count": page_count,
        "section": section,
        "item_start": item_start,
        "item_count": len(items),
        "page_size": page_size,
        "cursor": current_cursor,
        "next_cursor": next_cursor,
    }
    paged = {
        **value,
        "data": _domain_context_page_data(
            _domain_context_page_template(data_template, page_index), section, items, page
        ),
    }
    if next_cursor is not None:
        paged["head"] = {
            **value["head"],
            "next_action": {
                "operation": "get_domain_context",
                "authority": "host",
                "trial_id": trial_id,
                "domain_id": domain_id,
            },
        }
    actual_bytes = _domain_context_transport_bytes(paged)
    if actual_bytes > page_size:
        required_page_size = actual_bytes + _DOMAIN_CONTEXT_RETRY_MARGIN_BYTES
        if required_page_size > _DOMAIN_CONTEXT_MAX_PAGE_BYTES:
            raise ValueError(
                "domain_context_page_unrecoverable: "
                f"required_page_size={required_page_size};maximum_page_size="
                f"{_DOMAIN_CONTEXT_MAX_PAGE_BYTES}"
            )
        raise ValueError(
            "domain_context_page_oversized: "
            f"required_page_size={required_page_size};restart with a larger page_size"
        )
    return paged


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

    source_id: SourceHandle = Field(
        description="Copy the returned source_id exactly. Use it with the same trial_id."
    )
    page: PageNumber = Field(description="One-based Source-page index.")
    start_line: StrictInt = Field(
        ge=1, default=1, description="First one-based numbered line to return."
    )
    end_line: StrictInt | None = Field(
        default=None, ge=1, description="Last one-based numbered line to return, inclusive."
    )
    start_char: StrictInt = Field(
        ge=0,
        default=0,
        description="Start character offset within start_line for a split line.",
    )
    end_char: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Optional exclusive end offset within the final line.",
    )

    @model_validator(mode="after")
    def line_range_is_ordered(self) -> ReadWindow:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        if self.end_char is not None and self.end_line is None:
            raise ValueError("end_char requires end_line")
        if (
            self.end_line == self.start_line
            and self.end_char is not None
            and self.end_char < self.start_char
        ):
            raise ValueError("end_char must be greater than or equal to start_char")
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


def _content(
    tool: str,
    value: dict[str, Any],
    *,
    render_trial_id: str | None = None,
    domain_cursor: str | None = None,
    domain_page_size: int | None = None,
    domain_preview_missing_data: list[dict[str, Any]] | None = None,
) -> ToolResult:
    # Pixel bytes are transport content, never part of the typed JSON receipt.
    png_bytes = value.get("_png_bytes")
    read_coverage = value.get("_read_coverage")
    render_value = value.get("render") if tool == "render_page" else None
    render_source_id = render_value.get("source_id") if isinstance(render_value, dict) else None
    domain_context_basis_identity = (
        value.pop("_context_basis_identity", None) if tool == "get_domain_context" else None
    )
    value = {
        key: item for key, item in value.items() if key not in {"_png_bytes", "_read_coverage"}
    }
    domain_context_digest: str | None = None
    domain_context_snapshot: dict[str, Any] | None = None
    domain_context_state_revision: int | None = None
    domain_context_view_id: str | None = None
    value = _public_source_references(value)
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
        # projection while preserving every question and pack-guidance field.
        # Read-window defaults are omitted from the public shape before the
        # digest is issued.  Otherwise the persisted dcp2 snapshot would hash
        # a pre-compaction value while the stored snapshot contains the
        # compacted value, making the first continuation look stale.
        _compact_read_window_fields(normalized)
        normalized = _compact_domain_context_transport(normalized)
        data = normalized.get("data")
        if isinstance(data, dict):
            if not isinstance(domain_context_basis_identity, str):
                raise ValueError("domain_context_delivery_unavailable: assessment basis is missing")
            domain_context_digest = _domain_context_digest(data)
        domain_context_snapshot = normalized
        normalized_head = normalized.get("head")
        if isinstance(normalized_head, dict):
            revision = normalized_head.get("state_revision")
            domain_context_state_revision = revision if isinstance(revision, int) else None
        if domain_cursor is not None:
            decoded_cursor = _decode_domain_context_cursor(domain_cursor)
            domain_context_view = None
            if isinstance(decoded_cursor.get("view_id"), str):
                domain_context_view_id = decoded_cursor["view_id"]
                domain_context_view = _domain_context_view(
                    _root(_workspace()), domain_context_view_id
                )
                if domain_context_view is None:
                    raise ValueError("domain_context_cursor_expired: context view is unavailable")
                cursor_scope = {
                    **domain_context_view,
                    "page_index": decoded_cursor["page_index"],
                    "missing_data": domain_context_view.get("preview_scope"),
                }
            else:
                cursor_scope = decoded_cursor
            cursor_trial_id = cursor_scope.get("trial_id")
            cursor_domain_id = cursor_scope.get("domain_id")
            cursor_state_revision = cursor_scope.get("state_revision")
            cursor_digest = cursor_scope.get("digest")
            cursor_basis_identity = cursor_scope.get("basis_identity")
            if (
                not isinstance(cursor_trial_id, str)
                or not isinstance(cursor_domain_id, str)
                or not isinstance(cursor_state_revision, int)
                or not isinstance(cursor_digest, str)
                or not isinstance(cursor_basis_identity, str)
            ):
                raise ValueError("domain_context_cursor_invalid: incomplete cursor")
            current_data = normalized.get("data")
            current_head = normalized.get("head")
            if (
                not isinstance(current_data, dict)
                or not isinstance(current_head, dict)
                or current_data.get("trial_id") != cursor_trial_id
                or current_data.get("domain_id") != cursor_domain_id
                or domain_context_basis_identity != cursor_basis_identity
                or cursor_scope.get("missing_data") != domain_preview_missing_data
            ):
                raise ValueError(
                    "domain_context_cursor_stale: context scope or assessment basis changed"
                )
            delivery = domain_context_view or _domain_context_delivery(
                _root(_workspace()),
                cursor_trial_id,
                cursor_domain_id,
                cursor_state_revision,
                prefer_views=False,
            )
            if delivery is None:
                raise ValueError("domain_context_cursor_stale: context snapshot was replaced")
            if delivery.get("digest") != cursor_digest:
                raise ValueError("domain_context_cursor_stale: context projection changed")
            if delivery.get("preview_scope") != cursor_scope.get("missing_data"):
                raise ValueError("domain_context_cursor_stale: preview scope changed")
            if delivery.get("basis_identity") != cursor_basis_identity:
                raise ValueError("domain_context_cursor_stale: assessment basis changed")
            stored_snapshot = delivery.get("snapshot")
            if not isinstance(stored_snapshot, dict):
                raise ValueError("domain_context_cursor_stale: context snapshot has expired")
            stored_data = stored_snapshot.get("data")
            stored_head = stored_snapshot.get("head")
            if (
                not isinstance(stored_data, dict)
                or not isinstance(stored_head, dict)
                or stored_data.get("trial_id") != cursor_trial_id
                or stored_data.get("domain_id") != cursor_domain_id
                or (
                    not domain_context_view
                    and stored_head.get("state_revision") != cursor_state_revision
                )
                or _domain_context_digest(stored_data) != cursor_digest
            ):
                raise ValueError("domain_context_cursor_stale: context snapshot is invalid")
            domain_context_snapshot = stored_snapshot
            normalized = {
                **stored_snapshot,
                **normalized,
                "data": stored_data,
                "head": current_head,
            }
            domain_context_digest = cursor_digest
            domain_context_state_revision = cursor_state_revision
        if (
            domain_cursor is not None
            or domain_page_size is not None
            or _domain_context_transport_bytes(normalized) > _DOMAIN_CONTEXT_DEFAULT_PAGE_BYTES
        ):
            normalized = _paginate_domain_context_transport(
                normalized,
                domain_cursor,
                domain_page_size,
                str(domain_context_basis_identity),
                domain_context_state_revision if domain_context_state_revision is not None else 0,
                domain_preview_missing_data,
                domain_context_view_id
                if domain_context_view_id is not None
                else (uuid.uuid4().hex if domain_cursor is None else None),
            )
        validate_output(tool, normalized)
    _compact_read_window_fields(normalized)
    if tool == "read_pages":
        data = normalized.get("data")
        pages = data.get("pages") if isinstance(data, dict) else None
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict) and not page.get("line_fragment"):
                    # Keep the legacy page shape compact; character coordinates
                    # are meaningful only for a physical-line fragment.
                    page.pop("returned_start_char", None)
                    page.pop("next_start_char", None)
                    page.pop("line_fragment", None)
    if tool == "get_domain_context" and domain_context_digest is not None:
        data = normalized.get("data")
        head = normalized.get("head")
        page = data.get("context_page") if isinstance(data, dict) else None
        state_revision = head.get("state_revision") if isinstance(head, dict) else None
        if (
            isinstance(data, dict)
            and isinstance(state_revision, int)
            and isinstance(domain_context_basis_identity, str)
        ):
            if isinstance(page, dict):
                page_cursor = page.get("next_cursor") or page.get("cursor")
                if domain_context_view_id is None and isinstance(page_cursor, str):
                    decoded_page_cursor = _decode_domain_context_cursor(page_cursor)
                    domain_context_view_id = decoded_page_cursor.get("view_id")
                if domain_context_view_id is not None:
                    _record_domain_context_view(
                        _root(_workspace()),
                        domain_context_view_id,
                        str(data["trial_id"]),
                        str(data["domain_id"]),
                        int(page["state_revision"]),
                        domain_context_digest,
                        int(page["page_size"]),
                        int(page["count"]),
                        int(page["index"]),
                        page.get("next_cursor")
                        if isinstance(page.get("next_cursor"), str)
                        else None,
                        domain_cursor,
                        domain_context_basis_identity,
                        domain_context_snapshot,
                        domain_preview_missing_data,
                    )
                    # Preserve the legacy projection for existing clients and
                    # diagnostics; its state is not authoritative for dcp2.
                    _record_domain_context_delivery(
                        _root(_workspace()),
                        str(data["trial_id"]),
                        str(data["domain_id"]),
                        int(page["state_revision"]),
                        domain_context_digest,
                        int(page["page_size"]),
                        int(page["count"]),
                        int(page["index"]),
                        page.get("next_cursor")
                        if isinstance(page.get("next_cursor"), str)
                        else None,
                        None,
                        domain_context_basis_identity,
                        domain_context_snapshot,
                        domain_preview_missing_data,
                    )
                else:
                    _record_domain_context_delivery(
                        _root(_workspace()),
                        str(data["trial_id"]),
                        str(data["domain_id"]),
                        int(page["state_revision"]),
                        domain_context_digest,
                        int(page["page_size"]),
                        int(page["count"]),
                        int(page["index"]),
                        page.get("next_cursor")
                        if isinstance(page.get("next_cursor"), str)
                        else None,
                        domain_cursor,
                        domain_context_basis_identity,
                        domain_context_snapshot,
                        domain_preview_missing_data,
                    )
            else:
                _record_domain_context_delivery(
                    _root(_workspace()),
                    str(data["trial_id"]),
                    str(data["domain_id"]),
                    state_revision,
                    domain_context_digest,
                    _DOMAIN_CONTEXT_DEFAULT_PAGE_BYTES,
                    1,
                    0,
                    None,
                    None,
                    domain_context_basis_identity,
                    domain_context_snapshot,
                    domain_preview_missing_data,
                )
    if tool == "read_pages":
        envelope_bytes = len(
            json.dumps(
                {"content": [], "structured_content": normalized},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if envelope_bytes > _READ_PAGES_RESPONSE_BYTES:
            raise ValueError(
                "read_pages_response_oversized: serialized response exceeds "
                f"{_READ_PAGES_RESPONSE_BYTES} UTF-8 bytes"
            )
    if tool == "read_pages" and isinstance(read_coverage, list):
        _record_read_coverage_batch(_workspace(), read_coverage)
    if tool != "render_page":
        COUNTERS["response_bytes"] += len(
            json.dumps(
                normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        )
        return ToolResult(content=[], structured_content=normalized)
    image_content = None
    data = normalized.get("data")
    if isinstance(data, dict) and isinstance(data.get("render"), dict):
        render = data["render"]
        receipt = None
        if isinstance(png_bytes, bytes):
            image_content = ImageContent(
                type="image",
                data=base64.b64encode(png_bytes).decode("ascii"),
                mime_type="image/png",
            )
            if render_trial_id is None or not isinstance(render.get("identity"), str):
                raise ValueError("render delivery has no verified Trial or render identity")
            if not isinstance(render_source_id, str):
                raise ValueError("render delivery has no verified Source")
            receipt = _record_visual_delivery(
                _workspace(),
                render_trial_id,
                render_source_id,
                render["identity"],
                png_bytes,
            )
        normalized = validate_output(
            tool,
            {**normalized, "data": {**data, "delivery_receipt": receipt}},
        )
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    COUNTERS["response_bytes"] += len(serialized.encode("utf-8"))
    if image_content is not None and isinstance(png_bytes, bytes):
        COUNTERS["response_bytes"] += len(base64.b64encode(png_bytes))
    content: list[TextContent | ImageContent] = [
        TextContent(
            type="text",
            text=serialized,
        )
    ]
    if image_content is not None:
        content.append(image_content)
    return ToolResult(content=content, structured_content=normalized)


def _invoke(
    tool: str,
    operation: Any,
    *,
    render_trial_id: str | None = None,
    domain_cursor: str | None = None,
    domain_page_size: int | None = None,
    domain_preview_missing_data: list[dict[str, Any]] | None = None,
) -> ToolResult:
    try:
        return _content(
            tool,
            operation(),
            render_trial_id=render_trial_id,
            domain_cursor=domain_cursor,
            domain_page_size=domain_page_size,
            domain_preview_missing_data=domain_preview_missing_data,
        )
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
        if condition.startswith("source_navigation_cursor_stale:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "source_navigation_cursor_stale",
                    "condition": condition.removeprefix("source_navigation_cursor_stale:"),
                },
            )
        if condition.startswith("source_navigation_cursor_expired:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "source_navigation_cursor_expired",
                    "condition": condition.removeprefix("source_navigation_cursor_expired:"),
                },
            )
        if condition.startswith("source_navigation_cursor_invalid:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "source_navigation_cursor_invalid",
                    "condition": condition.removeprefix("source_navigation_cursor_invalid:"),
                },
            )
        if condition.startswith("domain_context_cursor_stale:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_cursor_stale",
                    "condition": condition.removeprefix("domain_context_cursor_stale:"),
                },
            )
        if condition.startswith("domain_context_cursor_expired:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_cursor_expired",
                    "condition": condition.removeprefix("domain_context_cursor_expired:"),
                },
            )
        if condition.startswith("domain_context_cursor_invalid:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_cursor_invalid",
                    "condition": condition.removeprefix("domain_context_cursor_invalid:"),
                },
            )
        if condition.startswith("domain_context_header_oversized:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_header_oversized",
                    "condition": condition.removeprefix("domain_context_header_oversized:"),
                },
            )
        if condition.startswith("domain_context_header_unrecoverable:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_header_unrecoverable",
                    "condition": condition.removeprefix("domain_context_header_unrecoverable:"),
                },
            )
        if condition.startswith("domain_context_item_oversized:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_item_oversized",
                    "condition": condition.removeprefix("domain_context_item_oversized:"),
                },
            )
        if condition.startswith("domain_context_item_unrecoverable:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_item_unrecoverable",
                    "condition": condition.removeprefix("domain_context_item_unrecoverable:"),
                },
            )
        if condition.startswith("domain_context_page_oversized:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_page_oversized",
                    "condition": condition.removeprefix("domain_context_page_oversized:"),
                },
            )
        if condition.startswith("domain_context_page_unrecoverable:"):
            return _content(
                tool,
                {
                    "outcome": "condition",
                    "code": "domain_context_page_unrecoverable",
                    "condition": condition.removeprefix("domain_context_page_unrecoverable:"),
                },
            )
        for prefix, code in (
            ("domain_context_delivery_unavailable:", "domain_context_delivery_unavailable"),
            ("domain_context_delivery_stale:", "domain_context_delivery_stale"),
            (
                "domain_context_delivery_out_of_order:",
                "domain_context_delivery_out_of_order",
            ),
        ):
            if condition.startswith(prefix):
                return _content(
                    tool,
                    {
                        "outcome": "condition",
                        "code": code,
                        "condition": condition.removeprefix(prefix),
                    },
                )
        if tool in {
            "get_domain_context",
            "validate_domain_assessment",
            "save_domain_judgment",
            "review_trial",
            "close_trial",
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
        "valid Trial directories. The server resolves directories, so no listing is required. "
        "Inspect returned conditions for supplied files that were not included. DOCX captures "
        "ordinary paragraphs, table headers/cells in order, and footnotes as a synthetic page-1 "
        "text projection; that is not Word pagination and does not extract all embedded content. "
        "Legacy .doc remains unsupported. Image-only PDFs remain renderable through render_page "
        "even when they have no searchable text."
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
        "When reading status is required, read its required_ranges before scientific work. "
        "Check again after finishing the returned windows. Omitted Evidence quotes retain exact "
        "read_pages recovery; recover unfamiliar passages before using them."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("get_status"),
)
def get_status() -> ToolResult:
    return _invoke("get_status", lambda: _get_status(_workspace()))


@mcp.tool(
    name="save_working_checkpoint",
    title="Save working checkpoint",
    description=(
        "Replace the current Trial's small, source-linked working notes. Use notes for "
        "observations, interpretations, terminology, unread ranges, open questions, and drafts. "
        "Each note must cite exact source page and line ranges, or 0,0 for a whole-page visual "
        "locator. These notes are resumable working memory; they do not become Evidence, answer "
        "a question, change a Result, or commit a "
        "Domain. get_status returns them only while the captured source scope and Trial Result "
        "still match. If cited content is missing or uncertain, recover the passage with "
        "read_pages; use render_page for a whole-page visual locator. Saving replaces the prior "
        "checkpoint for this Trial."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("save_working_checkpoint"),
)
def save_working_checkpoint(
    checkpoint: Annotated[
        WorkingCheckpointDraft,
        Field(description="Bounded source-linked notes for resuming the current Trial."),
    ],
) -> ToolResult:
    return _invoke(
        "save_working_checkpoint",
        lambda: _save_working_checkpoint(_workspace(), checkpoint),
    )


@mcp.tool(
    name="list_sources",
    title="List Trial sources",
    description=(
        "List captured sources and their short source_id handles. Requires a Trial ID for "
        "multi-Trial batches. Copy a returned source_id exactly and use it with the same trial_id. "
        "The inventory includes captured intake conditions and declared omissions for this Trial, "
        "so unsupported or unreadable dossier files remain visible. "
        "For source-scoped navigation, pass source_id and optionally cursor to receive bounded "
        "literal heading candidates and leading page excerpts from the persisted text projection, "
        "including page numbers with no extracted text. "
        "Navigation is a routing aid, not Evidence; read the cited pages before relying on them."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("list_sources"),
)
def list_sources(
    trial_id: Annotated[
        TrialId | None,
        Field(description="Captured Trial ID; omit only when the batch has one Trial."),
    ] = None,
    source_id: Annotated[
        SourceHandle | None,
        Field(
            description=(
                "Optional source_id from this Trial. Supplying it returns bounded literal "
                "heading and leading-page navigation entries."
            )
        ),
    ] = None,
    limit: Annotated[
        SourceNavigationLimit,
        Field(
            description=(
                "Maximum navigation entries returned. Use an integer from 1 through 12; "
                "the default is 12. Follow cursor when more entries remain."
            )
        ),
    ] = 12,
    cursor: Annotated[
        StrictStr | None,
        Field(description="Opaque navigation cursor returned by the prior response."),
    ] = None,
) -> ToolResult:
    navigation_trial_id = trial_id
    if source_id is not None and navigation_trial_id is None:
        batch = (_state(_root(_workspace())) or {}).get("batch", {})
        trials = batch.get("trials", []) if isinstance(batch, dict) else []
        if len(trials) == 1 and isinstance(trials[0], dict):
            navigation_trial_id = trials[0].get("id")
    return _invoke(
        "list_sources",
        lambda: _list_sources(
            _workspace(),
            navigation_trial_id,
            (
                _resolve_source_handle(_workspace(), navigation_trial_id, source_id)
                if source_id is not None and navigation_trial_id is not None
                else source_id
            ),
            cursor,
            limit,
        ),
    )


@mcp.tool(
    name="search_sources",
    title="Search Trial sources",
    description=(
        "Search captured Trial sources. Provide trial_id, query, and mode. "
        "Use a returned cursor with the same search arguments to continue. Inspect a returned "
        "passage before selecting it as Evidence. A zero-hit receipt describes only the issued "
        "lexical query."
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
            description="Non-empty lexical wording from Sources or query suggestions.",
            examples=["central randomization"],
        ),
    ],
    mode: Annotated[
        Literal["all", "phrase", "any", "prefix", "literal"],
        Field(
            description=(
                "Required lexical intent: all=every token on one page; phrase=known contiguous "
                "wording; any=at least one query term on a page for broad discovery; "
                "prefix=token prefix; literal=exact contiguous presentation-normalized wording "
                "without stemming."
            )
        ),
    ],
    source_id: Annotated[
        SourceHandle | None,
        Field(
            description=(
                "Optional source_id from this Trial; copy the returned source_id exactly. "
                "Use it with the same trial_id. Omit to search all captured Sources for this Trial."
            )
        ),
    ] = None,
    purpose_domain_id: Annotated[
        DomainId | None,
        Field(
            description=(
                "Optional Domain purpose for attribution; omit it for unassigned Trial discovery."
            )
        ),
    ] = None,
    purpose_question_id: Annotated[
        QuestionId | None,
        Field(
            description=(
                "Optional scientific question purpose within purpose_domain_id; it affects "
                "attribution only, not the frozen ranking session."
            )
        ),
    ] = None,
    limit: Annotated[
        SearchLimit,
        Field(description="Maximum candidate passages returned in this batch (1-100); default 10."),
    ] = 10,
    cursor: Annotated[
        str | None,
        Field(description="Prior next_cursor; retain its query, mode, Source scope, and limit."),
    ] = None,
) -> ToolResult:
    return _invoke(
        "search_sources",
        lambda: _search_sources(
            _workspace(),
            trial_id,
            query,
            mode,
            limit,
            (
                _resolve_source_handle(_workspace(), trial_id, source_id)
                if source_id is not None
                else None
            ),
            cursor,
            purpose_domain_id,
            purpose_question_id,
        ),
    )


def _search_batch_transport_bytes(results: list[dict[str, Any]]) -> int:
    """Measure the complete structured envelope before returning a search batch."""

    current = _get_status_head(_workspace())
    value = _public_source_references(
        {
            "outcome": "success",
            "results": results,
            "phase": current.get("phase", "empty"),
            "state_revision": current.get("state_revision", 0),
            "continuation": current.get("continuation"),
            "authoritative_wording": current.get("authoritative_wording"),
        }
    )
    normalized = normalize("search_sources_batch", value)
    return len(
        json.dumps(
            {"content": [], "structured_content": normalized},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _set_search_batch_display_limit(data: dict[str, Any], keep: int) -> None:
    """Trim only displayed hits while retaining the frozen ranking cursor."""

    hits = list(data.get("hits", []))
    if keep >= len(hits):
        return
    retained = hits[:keep]
    data["hits"] = retained
    if retained:
        first_rank = int(retained[0]["rank"])
        last_rank = int(retained[-1]["rank"])
        data["returned_rank_start"] = first_rank
        data["returned_rank_end"] = last_rank
        data["next_cursor"] = _cursor_handle(str(data["session_id"]), last_rank)
        data["exhausted"] = False
        data["truncated"] = True
        for hit in retained:
            hit["range"] = {"start": first_rank, "end": last_rank}
        return
    raise ValueError("search batch cannot discard the only hit for an independent result")


def _mark_search_batch_item_oversized(item: dict[str, Any]) -> None:
    """Keep a compact item-level condition when one result cannot fit the batch."""

    item["result"] = {
        "outcome": "condition",
        "condition": {
            "code": "search_batch_item_oversized",
            "detail": (
                "This independent search result could not fit the aggregate batch response. "
                "Retry the same query separately, or with a smaller limit; other batch items "
                "remain independent and are not affected."
            ),
        },
    }


def _refresh_search_batch_receipt(data: dict[str, Any]) -> None:
    """Persist the receipt that exactly describes the displayed batch prefix."""

    receipt = data.get("search_receipt")
    hits = data.get("hits")
    if not isinstance(receipt, dict) or not isinstance(hits, list):
        return
    receipt = dict(receipt)
    receipt["hits"] = [
        {"source_id": hit["source_id"], "page": hit["page"]}
        for hit in hits
        if isinstance(hit, dict)
    ]
    ranks = {
        int(hit["rank"])
        for hit in hits
        if isinstance(hit, dict) and isinstance(hit.get("rank"), int)
    }
    receipt["returned_candidates"] = [
        item
        for item in receipt.get("returned_candidates", [])
        if isinstance(item, dict) and item.get("rank") in ranks
    ]
    receipt["returned_rank_start"] = min(ranks) if ranks else None
    receipt["returned_rank_end"] = max(ranks) if ranks else None
    receipt["returned_material"] = len(hits)
    receipt["truncated"] = bool(data.get("truncated"))
    receipt["exhausted"] = bool(data.get("exhausted"))
    receipt["next_cursor"] = data.get("next_cursor")
    receipt["identity"] = _identity(
        {key: value for key, value in receipt.items() if key not in {"identity", "handle"}}
    )
    receipt["handle"] = "sr_" + receipt["identity"].removeprefix("sha256:")[:16]
    data["search_receipt"] = receipt
    with _db(_root(_workspace()), "derivative.sqlite3") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO search_receipts VALUES (?,?)",
            (receipt["identity"], canonical_json_bytes(receipt)),
        )


def _bound_search_batch(results: list[dict[str, Any]]) -> None:
    """Fit a batch without rerunning any item or losing its continuation."""

    if _search_batch_transport_bytes(results) <= _SEARCH_BATCH_RESPONSE_BYTES:
        return
    # Feedback and no-hit navigation are useful, but neither has a continuation
    # of its own.  Drop these optional expansions only when the complete batch
    # would otherwise exceed the transport contract.
    for item in results:
        result = item.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("term_feedback"), list):
            data["term_feedback"] = []
            data["term_feedback_sources_truncated"] = True
        data["diagnostic"] = None

    while _search_batch_transport_bytes(results) > _SEARCH_BATCH_RESPONSE_BYTES:
        candidates = [
            (len(result["data"].get("hits", [])), index)
            for index, item in enumerate(results)
            if isinstance((result := item.get("result")), dict)
            and result.get("outcome") == "success"
            and isinstance(result.get("data"), dict)
            and len(result["data"].get("hits", [])) > 1
        ]
        if candidates:
            _count, index = max(candidates)
            result = results[index]["result"]
            _set_search_batch_display_limit(result["data"], len(result["data"]["hits"]) - 1)
            continue
        success_items = [
            (index, item)
            for index, item in enumerate(results)
            if isinstance(item.get("result"), dict) and item["result"].get("outcome") == "success"
        ]
        if not success_items:
            raise ValueError(
                "search_batch_response_oversized: independent result metadata exceeds "
                f"the {_SEARCH_BATCH_RESPONSE_BYTES} UTF-8 byte budget"
            )
        # A one-hit result may still be too large to carry alongside its
        # siblings. Replace only that item with an actionable condition so
        # successful independent results survive the aggregate bound.
        index, _item = max(
            success_items,
            key=lambda pair: len(
                json.dumps(pair[1], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ),
        )
        _mark_search_batch_item_oversized(results[index])
    for item in results:
        result = item.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict):
            _refresh_search_batch_receipt(data)


@mcp.tool(
    name="search_sources_batch",
    title="Search independent Trial queries",
    description=(
        "Run 1 to 8 independent search requests in one call. Validate every request before "
        "running it. Each item has its own explicit "
        "query mode, Source scope, passage limit, cursor, outcome, feedback, and next_cursor. "
        "Every item must satisfy the request schema before the call. After validation, each item "
        "returns its own success or condition; an item-level stale cursor or unavailable Source "
        "condition does not prevent other items from returning. "
        "Cursors continue only the "
        "corresponding item's query; each ranking and BM25 order remain independent. Use this "
        "only when all query inputs are already known; wait for a result before choosing a "
        "dependent reformulation. The response byte budget includes metadata."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("search_sources_batch"),
)
def search_sources_batch(
    requests: Annotated[
        list[SearchBatchRequest],
        Field(
            min_length=1,
            max_length=8,
            description="One to eight independent query requests with their own cursors.",
        ),
    ],
) -> ToolResult:
    results: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        try:
            source_id = (
                _resolve_source_handle(_workspace(), request.trial_id, request.source_id)
                if request.source_id is not None
                else None
            )
            data = _search_sources(
                _workspace(),
                request.trial_id,
                request.query,
                request.mode,
                request.limit,
                source_id,
                request.cursor,
                request.purpose_domain_id,
                request.purpose_question_id,
            )
            result = {"outcome": "success", "data": data}
        except ValueError as error:
            detail = str(error)
            if detail.startswith("search_cursor_stale:"):
                code = "search_cursor_stale"
                detail = detail.removeprefix("search_cursor_stale:")
            elif detail.startswith("search_cursor_expired:"):
                code = "search_cursor_expired"
                detail = detail.removeprefix("search_cursor_expired:")
            else:
                code = "invalid_request"
            result = {"outcome": "condition", "condition": {"code": code, "detail": detail}}
        results.append(
            {
                "index": index,
                "query": request.query,
                "mode": request.mode,
                "result": result,
            }
        )
    try:
        _bound_search_batch(results)
    except ValueError as error:
        return _content(
            "search_sources_batch",
            {
                "outcome": "condition",
                "code": "search_batch_response_oversized",
                "condition": str(error),
            },
        )
    return _content("search_sources_batch", {"outcome": "success", "results": results})


@mcp.tool(
    name="read_pages",
    title="Read source pages",
    description=(
        "Read source text as numbered lines. Pages are 1-based source indexes, not printed "
        "labels. Use windows across sources; each item preserves its source and line bounds. "
        "The single-source form uses trial_id, source_id, pages, and optional start_line; "
        "start_line applies to every page and there is no top-level end_line. The windows form "
        "uses trial_id and windows only, with source_id, page, start_line, and end_line in "
        'each window. For example, use {"trial_id":"trial-a","source_id":'
        '"sh_0123456789abcdef","pages":[2],"start_line":10} or '
        '{"trial_id":"trial-a","windows":[{"source_id":'
        '"sh_0123456789abcdef","page":2,"start_line":10,"end_line":20}]}. '
        "Each page includes page_remainder for unread physical lines after returned_end_line; "
        "truncated, next_start_line, and remaining_windows retain requested-window semantics. "
        "To finish a partial batch, call read_pages with the same trial_id and windows set to "
        "data.remaining_windows, omitting source_id, pages, and start_line. Repeat until no "
        "windows remain. Returned text is in data.pages[].numbered_text. If "
        "data.remaining_windows is nonempty, send that exact list as the next windows value. "
        "The complete structured response, including metadata, is bounded to 24000 UTF-8 bytes. "
        "Returned numbered text normally fits within that bound; a single "
        "oversized physical line is returned across lossless character fragments until complete. "
        "A partial fragment has no passage_ref or selectable Evidence handle. Copy a returned "
        "source_id exactly and use it with the same trial_id."
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
        SourceHandle | None,
        Field(
            description=(
                "source_id from this Trial for the source_id+pages form. Copy the returned "
                "source_id exactly and use it with the same trial_id. Example: "
                '{"trial_id":"trial-a","source_id":"sh_0123456789abcdef",'
                '"pages":[2],"start_line":10}.'
            )
        ),
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
    start_char: Annotated[
        StrictInt,
        Field(
            ge=0,
            description="Start character offset within start_line for a split line.",
        ),
    ] = 0,
    end_char: Annotated[
        StrictInt | None,
        Field(
            default=None,
            ge=0,
            description="Optional exclusive end offset within the final line.",
        ),
    ] = None,
    windows: Annotated[
        list[ReadWindow] | None,
        Field(
            min_length=1,
            max_length=20,
            description=(
                "Independent Source-page windows with their own line bounds. Supply trial_id "
                "and windows without source_id, pages, or top-level start_line. Every window "
                "owns source_id, page, start_line, and end_line. Example: "
                '{"trial_id":"trial-a","windows":[{"source_id":'
                '"sh_0123456789abcdef","page":2,"start_line":10,"end_line":20}]}.'
            ),
        ),
    ] = None,
) -> ToolResult:
    def read() -> dict[str, Any]:
        if trial_id is None:
            raise ValueError("trial_id is required")
        if windows is None and (source_id is None or pages is None):
            raise ValueError("source_id and pages are required unless windows is supplied")
        requests = [(trial_id, source_id, pages, start_line, None, start_char, end_char)]
        if windows:
            if (
                source_id is not None
                or pages is not None
                or start_line != 1
                or start_char != 0
                or end_char is not None
            ):
                raise ValueError("use windows alone for independent reads")
            requests = [
                (
                    trial_id,
                    _resolve_source_handle(_workspace(), trial_id, item.source_id),
                    [item.page],
                    item.start_line,
                    item.end_line,
                    item.start_char,
                    item.end_char,
                )
                for item in windows
            ]
        elif source_id is not None:
            requests = [
                (
                    trial_id,
                    _resolve_source_handle(_workspace(), trial_id, source_id),
                    pages,
                    start_line,
                    None,
                    start_char,
                    end_char,
                )
            ]
        raw_pages: list[dict[str, Any]] = []
        include_source = True
        for (
            request_trial,
            request_source,
            request_pages,
            request_start,
            request_end,
            request_start_char,
            request_end_char,
        ) in requests:
            assert request_trial is not None and request_source is not None
            result = _read_pages(_workspace(), request_trial, request_source, request_pages)
            raw_pages.extend(
                {
                    **item,
                    **({"source_id": request_source} if include_source else {}),
                    "requested_start": request_start,
                    "requested_end": request_end,
                    "requested_start_char": request_start_char,
                    "requested_end_char": request_end_char,
                }
                for item in result["pages"]
            )
        numbered_pages: list[dict[str, Any]] = []
        read_coverage: list[tuple[str, str, int, int, int]] = []
        remaining_windows: list[dict[str, Any]] = []
        transport_head = _get_status_head(_workspace())

        def window_record(
            item: dict[str, Any],
            start: int,
            end: int,
            *,
            start_char: int = 0,
            end_char: int | None = None,
        ) -> dict[str, Any]:
            # EvidenceReadWindow is intentionally line-addressable.  The
            # PageData next_start_char field carries a continuation inside a
            # physical line without pretending the line is complete.  Keep
            # the ordinary line-window shape compact; a nonzero offset is
            # required to resume a split line losslessly.
            record = {
                "source_id": item["source_id"],
                "page": item["page"],
                "start_line": start,
                "end_line": end,
            }
            if start_char:
                record["start_char"] = start_char
            if end_char is not None:
                record["end_char"] = end_char
            return record

        def pending_windows(
            index: int, current: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            def window_end(future: dict[str, Any]) -> int:
                lines = future["text"].splitlines()
                start = max(1, int(future["requested_start"]))
                requested_end = future["requested_end"]
                available = len(lines) or start
                return max(
                    start,
                    min(
                        available,
                        int(requested_end) if requested_end is not None else available,
                    ),
                )

            pending = [*remaining_windows]
            if current is not None:
                pending.append(current)
            pending.extend(
                window_record(
                    future,
                    int(future["requested_start"]),
                    window_end(future),
                    start_char=int(future.get("requested_start_char", 0)),
                    end_char=future.get("requested_end_char"),
                )
                for future in raw_pages[index + 1 :]
            )
            return pending

        def page_record(
            item: dict[str, Any],
            lines: list[str],
            requested_start: int,
            end_line: int,
            returned: list[str],
            *,
            fragment: bool,
            returned_start_char: int,
            next_char: int | None,
            truncated: bool,
        ) -> dict[str, Any]:
            next_line = end_line if fragment and next_char is not None else end_line + 1
            return {
                **({"source_id": item["source_id"]} if include_source else {}),
                "page": item["page"],
                "numbered_text": "\n".join(returned),
                "line_count": len(lines),
                "returned_start_line": requested_start,
                "returned_end_line": end_line,
                "page_remainder": (
                    {
                        "source_id": item["source_id"],
                        "page": item["page"],
                        "start_line": (
                            end_line if fragment and next_char is not None else end_line + 1
                        ),
                        "end_line": len(lines),
                        **({"start_char": next_char} if fragment and next_char is not None else {}),
                    }
                    if end_line < len(lines) or (fragment and next_char is not None)
                    else None
                ),
                "truncated": truncated,
                "next_start_line": next_line if truncated else None,
                "returned_start_char": returned_start_char if fragment else None,
                "next_start_char": next_char if truncated and fragment else None,
                "line_fragment": fragment,
                "passage_ref": None,
            }

        def fits(pages: list[dict[str, Any]], pending: list[dict[str, Any]]) -> bool:
            return (
                _read_pages_transport_bytes(
                    {
                        "outcome": "success",
                        "pages": pages,
                        "remaining_windows": pending,
                    },
                    transport_head,
                )
                <= _READ_PAGES_RESPONSE_BYTES
            )

        for index, item in enumerate(raw_pages):
            lines = item["text"].splitlines()
            requested_start = int(item["requested_start"])
            requested_end = item["requested_end"]
            requested_start_char = int(item.get("requested_start_char", 0))
            requested_end_char = item.get("requested_end_char")
            if not lines:
                empty_page = {
                    **({"source_id": item["source_id"]} if include_source else {}),
                    "page": item["page"],
                    "numbered_text": "",
                    "line_count": 0,
                    "returned_start_line": requested_start,
                    "returned_end_line": 0,
                    "page_remainder": None,
                    "truncated": False,
                    "next_start_line": None,
                    "returned_start_char": None,
                    "next_start_char": None,
                    "line_fragment": False,
                    "passage_ref": None,
                }
                if not fits([*numbered_pages, empty_page], pending_windows(index)):
                    remaining_windows.extend(
                        pending_windows(
                            index,
                            window_record(
                                item,
                                requested_start,
                                max(
                                    requested_start,
                                    int(requested_end)
                                    if requested_end is not None
                                    else requested_start,
                                ),
                                start_char=requested_start_char,
                                end_char=requested_end_char,
                            ),
                        )
                    )
                    break
                numbered_pages.append(empty_page)
                read_coverage.append((trial_id, item["source_id"], item["page"], 0, 0))
                continue
            if requested_start > len(lines):
                raise ValueError(
                    f"start_line {requested_start} is outside page {item['page']}; "
                    f"choose 1 <= start_line <= {len(lines)}"
                )
            if requested_start_char > len(lines[requested_start - 1]):
                raise ValueError(
                    f"start_char {requested_start_char} is outside line {requested_start}; "
                    f"choose 0 <= start_char <= {len(lines[requested_start - 1])}"
                )
            if requested_end is not None and requested_end < requested_start:
                raise ValueError("end_line must not precede start_line")
            available_end = min(
                len(lines), requested_end if requested_end is not None else len(lines)
            )
            if requested_end_char is not None:
                final_line = lines[available_end - 1]
                if requested_end_char > len(final_line):
                    raise ValueError(
                        f"end_char {requested_end_char} is outside line {available_end}; "
                        f"choose 0 <= end_char <= {len(final_line)}"
                    )
            returned: list[str] = []
            end_line = requested_start - 1
            fragment = False
            next_char: int | None = None
            last_complete_line = requested_start - 1
            stopped = False
            for line_number in range(requested_start, available_end + 1):
                line = lines[line_number - 1]
                line_start_char = requested_start_char if line_number == requested_start else 0
                line_end_char = (
                    requested_end_char
                    if requested_end_char is not None and line_number == available_end
                    else len(line)
                )
                if line_end_char < line_start_char:
                    raise ValueError("end_char must not precede start_char on the same line")
                candidate_text = line[line_start_char:line_end_char]
                candidate_fragment = fragment or line_start_char > 0 or line_end_char < len(line)
                explicit_end = requested_end_char is not None and line_number == available_end
                transport_truncated = line_end_char < len(line) and not explicit_end
                candidate_truncated = transport_truncated or line_number < available_end
                candidate_next_char = line_end_char if transport_truncated else None
                candidate_end_line = line_number
                candidate_numbered = f"{line_number}|{candidate_text}"
                candidate_returned = [*returned, candidate_numbered]
                candidate_page = page_record(
                    item,
                    lines,
                    requested_start,
                    candidate_end_line,
                    candidate_returned,
                    fragment=candidate_fragment,
                    returned_start_char=requested_start_char,
                    next_char=candidate_next_char,
                    truncated=candidate_truncated,
                )
                if not candidate_fragment and any(
                    line.strip() for line in lines[requested_start - 1 : candidate_end_line]
                ):
                    # A complete range receives a deterministic Evidence handle below.
                    # Reserve its fixed-width transport representation while packing so
                    # adding that handle cannot make the final envelope oversize.
                    candidate_page["passage_ref"] = "eh_" + ("0" * 16)
                current_pending = (
                    window_record(
                        item,
                        line_number if candidate_next_char is not None else line_number + 1,
                        available_end,
                        start_char=(candidate_next_char or 0),
                        end_char=requested_end_char,
                    )
                    if candidate_truncated
                    else None
                )
                if fits(
                    [*numbered_pages, candidate_page],
                    pending_windows(index, current_pending),
                ):
                    returned = candidate_returned
                    end_line = candidate_end_line
                    fragment = candidate_fragment
                    next_char = candidate_next_char
                    if not candidate_fragment:
                        last_complete_line = line_number
                    if candidate_truncated and candidate_next_char is not None:
                        stopped = True
                        break
                    continue
                if returned:
                    stopped = True
                    break

                # Even the first physical line may exceed the bound. Find the
                # largest UTF-8-safe character prefix that fits the complete
                # serialized envelope, then let the caller continue by offset.
                low, high = line_start_char, line_end_char
                best: tuple[int, dict[str, Any]] | None = None
                while low < high:
                    middle = (low + high + 1) // 2
                    partial_page = page_record(
                        item,
                        lines,
                        requested_start,
                        line_number,
                        [f"{line_number}|{line[line_start_char:middle]}"],
                        fragment=True,
                        returned_start_char=requested_start_char,
                        next_char=middle,
                        truncated=True,
                    )
                    if fits(
                        [*numbered_pages, partial_page],
                        pending_windows(
                            index,
                            window_record(
                                item,
                                line_number,
                                available_end,
                                start_char=middle,
                                end_char=requested_end_char,
                            ),
                        ),
                    ):
                        best = (middle, partial_page)
                        low = middle
                    else:
                        high = middle - 1
                if best is None:
                    if numbered_pages:
                        # The current page can be recovered on the next call;
                        # do not turn a full response into an unrecoverable
                        # error merely because its metadata no longer fits.
                        stopped = True
                        end_line = requested_start - 1
                        break
                    raise ValueError(
                        "read_pages_item_unrecoverable: one physical line cannot fit the "
                        "serialized response envelope"
                    )
                end_line = line_number
                returned = best[1]["numbered_text"].split("\n")
                fragment = True
                next_char = best[0]
                stopped = True
                break

            if returned:
                page = page_record(
                    item,
                    lines,
                    requested_start,
                    end_line,
                    returned,
                    fragment=fragment,
                    returned_start_char=requested_start_char,
                    next_char=next_char,
                    truncated=stopped or end_line < available_end,
                )
                if not fragment and any(
                    line.strip() for line in lines[requested_start - 1 : end_line]
                ):
                    passage = _select_text_evidence_by_lines(
                        _workspace(),
                        trial_id,
                        item["source_id"],
                        item["page"],
                        requested_start,
                        end_line,
                    )
                    page["passage_ref"] = passage.get("evidence", {}).get("handle")
                numbered_pages.append(page)
                if not fragment:
                    read_coverage.append(
                        (
                            trial_id,
                            item["source_id"],
                            item["page"],
                            requested_start,
                            last_complete_line,
                        )
                    )

            if stopped or end_line < available_end:
                remaining_windows.extend(
                    pending_windows(
                        index,
                        window_record(
                            item,
                            end_line if fragment and next_char is not None else end_line + 1,
                            available_end,
                            start_char=next_char or 0,
                            end_char=requested_end_char,
                        ),
                    )
                )
                # Every later raw page is already represented in the pending
                # windows. Defer it to the next call so it cannot be emitted
                # twice or consume the current response budget.
                break
        return {
            "outcome": "success",
            "pages": numbered_pages,
            "remaining_windows": remaining_windows,
            "_read_coverage": read_coverage,
        }

    return _invoke("read_pages", read)


@mcp.tool(
    name="select_text_evidence",
    title="Select text Evidence",
    description=(
        "Select one contiguous range after inspecting its source text. Reuse an existing "
        "passage_ref when its boundaries already cover the premise. Use the "
        "1-based source page and line numbers exactly as issued; split a page-boundary passage "
        "into one selection per page; never reconstruct text from a preview. "
        "The server stores the exact unnumbered source text and Source version; a query never "
        "changes that Evidence identity. Select split table fragments separately. "
        "Use visual Evidence when layout, symbols, or figure structure carry the meaning."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("select_text_evidence"),
)
def select_text_evidence(
    trial_id: Annotated[
        TrialId,
        Field(description="Captured Trial containing the source.", examples=["trial-a"]),
    ],
    source_id: Annotated[
        SourceHandle,
        Field(description="Copy the returned source_id exactly. Use it with the same trial_id."),
    ],
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
            _resolve_source_handle(_workspace(), trial_id, source_id),
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
    source_id: Annotated[
        SourceHandle,
        Field(description="Copy the returned source_id exactly. Use it with the same trial_id."),
    ],
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
        "render_page",
        lambda: _render_page(
            _workspace(),
            trial_id,
            _resolve_source_handle(_workspace(), trial_id, source_id),
            page,
            inline,
        ),
        render_trial_id=trial_id,
    )


@mcp.tool(
    name="select_visual_evidence",
    title="Select visual Evidence",
    description=(
        "Record visual Evidence from a rendered page. Transcription must be one exact, "
        "self-contained account containing every applicable title, axis, series, label, value, "
        "unit, uncertainty, denominator, and footnote. Select only with the delivery_receipt "
        "returned alongside an ImageContent block by render_page."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("select_visual_evidence"),
)
def select_visual_evidence(
    trial_id: Annotated[TrialId, Field(description="Captured Trial containing the source.")],
    source_id: Annotated[
        SourceHandle,
        Field(description="Copy the returned source_id exactly. Use it with the same trial_id."),
    ],
    delivery_receipt: Annotated[
        Identity,
        Field(
            description=(
                "Delivery receipt returned with the ImageContent block by render_page. "
                "Metadata-only renders do not issue a receipt."
            )
        ),
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
            _workspace(),
            trial_id,
            _resolve_source_handle(_workspace(), trial_id, source_id),
            delivery_receipt,
            transcription,
            list(region),
        ),
    )


@mcp.tool(
    name="validate_proposal",
    title="Validate Proposal draft",
    description=(
        "Before saving a Proposal, submit its Result cards and a brief evidence-based assessment "
        "for each submitted Trial. Explain why the reported result supports the target relation "
        "and chosen time point or window. Distinguish baseline eligibility from exclusions or "
        "missing observations in the reported analysis. Identify material conflicting evidence "
        "and unresolved facts; do not infer unavailable facts. The server validates structure, "
        "Evidence references and workflow requirements, not scientific correctness. Save using "
        "the returned reasoning_id."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("validate_proposal"),
)
def validate_proposal(
    results: Annotated[
        list[ResultChoiceDraft],
        Field(min_length=1, description="The exact Result cards for this Proposal save."),
    ],
    assessments: Annotated[
        list[ProposalReasoningAssessment],
        Field(
            min_length=1,
            description="One concise source-bound assessment for every submitted Trial card.",
        ),
    ],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current revision from get_status.")
    ],
) -> ToolResult:
    draft = {
        "results": [item.model_dump(mode="json") for item in results],
        "assessments": [item.model_dump(mode="json") for item in assessments],
        "expected_revision": expected_revision,
    }
    return _invoke("validate_proposal", lambda: _validate_proposal(_workspace(), draft))


@mcp.tool(
    name="save_proposal",
    title="Save Result proposal",
    description=(
        "Commit the exact Result cards stored by validate_proposal. Supply its reasoning_id and "
        "returned revision; do not resend Result cards. To change the draft, repeat "
        "validate_proposal with complete replacement cards and matching assessments, then pass "
        "its reasoning_id and revision here."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("save_proposal"),
)
def save_proposal(
    expected_revision: Annotated[
        ExpectedRevision,
        Field(description="Revision returned by validate_proposal."),
    ],
    reasoning_id: Annotated[
        Identity,
        Field(description="Exact reasoning_id returned by validate_proposal."),
    ],
) -> ToolResult:
    root = _root(_workspace())
    state = _state(root)
    records = state.get("reasoning_records")
    record = records.get(reasoning_id) if isinstance(records, dict) else None
    if not isinstance(record, dict) or record.get("kind") != "proposal_reasoning":
        return _content(
            "save_proposal",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, submit complete replacement Result "
                    "cards and matching assessments to validate_proposal, then save its returned "
                    "receipt. Otherwise follow head.next_action."
                ),
            },
        )
    current_revision = int(state.get("revision", 0))
    stored_draft = record.get("draft")
    if not isinstance(stored_draft, dict):
        return _content(
            "save_proposal",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, submit complete replacement Result "
                    "cards and matching assessments to validate_proposal, then save its returned "
                    "receipt. Otherwise follow head.next_action."
                ),
            },
        )
    if record.get("save_revision") != expected_revision or expected_revision != current_revision:
        proposal_record = state.get("proposal")
        if not isinstance(proposal_record, dict) or proposal_record.get("identity") != record.get(
            "proposal_identity"
        ):
            return _content(
                "save_proposal",
                {
                    "outcome": "condition",
                    "code": "reasoning_stale",
                    "condition": (
                        "Call get_status. If work remains active, submit complete replacement "
                        "Result cards and matching assessments to validate_proposal, then save "
                        "its returned receipt. Otherwise follow head.next_action."
                    ),
                },
            )
        expected_revision = current_revision
    try:
        proposal = ProposalDraft.model_validate(
            {
                "results": stored_draft["results"],
                "expected_revision": expected_revision,
            }
        )
    except ValueError:
        return _content(
            "save_proposal",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, submit complete replacement Result "
                    "cards and matching assessments to validate_proposal, then save its returned "
                    "receipt. Otherwise follow head.next_action."
                ),
            },
        )
    return _invoke("save_proposal", lambda: _save_proposal(_workspace(), proposal))


def _proposal_approval_json_schema_extra(schema: dict[str, Any]) -> None:
    schema.pop("title", None)
    schema.pop("additionalProperties", None)


class ProposalApprovalDecision(StrictModel):
    model_config = ConfigDict(json_schema_extra=_proposal_approval_json_schema_extra)

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
        "present that exact immutable Review, obtain explicit approval, then call "
        "request_proposal_approval with {} to "
        "record the approval through elicitation. Call get_status after the approval succeeds. "
        "This tool has no approval arguments: only a directly accepted elicitation with "
        "approved=true commits it. "
        "For corrections, inspect Sources, submit complete replacement Result cards and matching "
        "assessments to validate_proposal, then pass its reasoning_id and revision to "
        "save_proposal before presenting the fresh Review."
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
        "Read the approved Result, current Domain checkpoint, Evidence, comparison cards, and "
        "question cards. Complete required reading before answering. Use the returned revision "
        "and official answer values when validating. Follow context_page.next_cursor until it is "
        "null. If a cursor is stale, restart without a cursor. If cited content is missing or "
        "uncertain, recover the passage before relying on it."
    ),
    annotations=_READ_ONLY,
    output_schema=output_schema("get_domain_context"),
)
def get_domain_context(
    trial_id: Annotated[
        TrialId | None,
        Field(description=("Exact active Trial whose approved Result this call reads.")),
    ] = None,
    domain_id: Annotated[
        DomainId | None,
        Field(
            description=(
                "RoB 2 Domain ID; omit to receive the next uncommitted Domain, or specify any "
                "Domain in the active Trial for lookahead or review."
            )
        ),
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
    include_candidates: Annotated[
        StrictBool,
        Field(
            description=(
                "Include optional recoverable search and explicitly carried Evidence candidates. "
                "The default includes the approved Result and saved checkpoint Evidence without "
                "discovery candidates."
            )
        ),
    ] = False,
    cursor: Annotated[
        StrictStr | None,
        Field(
            default=None,
            description=(
                "Opaque context_page.next_cursor from the immediately preceding page. It is "
                "bound to the same Trial, Domain, approved Result, pack, current Domain "
                "checkpoint, preview, and page_size. Searches and unrelated Domain commits do "
                "not change this frozen page sequence."
            ),
        ),
    ] = None,
    page_size: Annotated[
        StrictJsonInt | None,
        Field(
            default=None,
            ge=_DOMAIN_CONTEXT_MIN_PAGE_BYTES,
            le=_DOMAIN_CONTEXT_MAX_PAGE_BYTES,
            description=(
                "Optional full structured transport byte budget override for bounded "
                "pages. The server auto-pages receipts above 32768 bytes; subsequent calls "
                "follow the returned cursor."
            ),
        ),
    ] = None,
) -> ToolResult:
    cursor_scope: dict[str, Any] | None = None
    if cursor is not None:
        try:
            cursor_scope = _decode_domain_context_cursor(cursor)
        except ValueError:
            # _invoke will return the typed cursor condition after the normal
            # workflow operation has supplied its current head.
            cursor_scope = None
    if cursor_scope is not None and isinstance(cursor_scope.get("view_id"), str):
        view = _domain_context_view(_root(_workspace()), cursor_scope["view_id"])
        if view is not None:
            cursor_scope = {**view, "page_index": cursor_scope["page_index"]}
        else:
            return _content(
                "get_domain_context",
                {
                    "outcome": "condition",
                    "code": "domain_context_cursor_expired",
                    "condition": (
                        "The frozen context view is unavailable. Restart get_domain_context "
                        "without a cursor and complete the new page chain."
                    ),
                },
            )
    if cursor_scope is not None:
        trial_id = trial_id or cursor_scope["trial_id"]
        domain_id = domain_id or cursor_scope["domain_id"]
        if missing_data is None and isinstance(cursor_scope.get("missing_data"), list):
            try:
                missing_data = [
                    MissingDataRow.model_validate(row) for row in cursor_scope["missing_data"]
                ]
            except (TypeError, ValueError):
                missing_data = None
        if missing_data is None and isinstance(cursor_scope.get("preview_scope"), list):
            try:
                missing_data = [
                    MissingDataRow.model_validate(row) for row in cursor_scope["preview_scope"]
                ]
            except (TypeError, ValueError):
                missing_data = None
    preview_rows = (
        [row.model_dump(mode="json", exclude_none=True) for row in missing_data]
        if missing_data is not None
        else None
    )
    return _invoke(
        "get_domain_context",
        lambda: _get_domain_context(
            _workspace(),
            trial_id,
            domain_id,
            [row.model_dump(mode="json", exclude_none=True) for row in missing_data]
            if missing_data is not None
            else None,
            include_candidates,
        ),
        domain_cursor=cursor,
        domain_page_size=page_size,
        domain_preview_missing_data=preview_rows,
    )


@mcp.tool(
    name="validate_domain_assessment",
    title="Check Domain reasoning",
    description=(
        "Before saving a Domain, submit the complete draft. For each active answer, briefly "
        "explain what its cited bases establish and why that supports the selected option for "
        "the approved Result. Before submitting, inspect the relevant captured Source section "
        "for any material unresolved fact, or record a bounded information limit. Identify "
        "material counterevidence and unresolved facts without treating uncertainty as a finding. "
        "The server validates structure, references, activation and workflow requirements, not "
        "scientific correctness. Save using the "
        "returned reasoning_id."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("validate_domain_assessment"),
)
def validate_domain_assessment(
    trial_id: Annotated[TrialId, Field(description="Trial being assessed.")],
    domain_id: Annotated[DomainId, Field(description="RoB 2 Domain being assessed.")],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current revision from get_domain_context.")
    ],
    answers: Annotated[
        list[DomainReasoningAnswer],
        Field(
            min_length=1,
            description=(
                "Complete answers for the current Domain path. Every active answer requires a "
                "nonblank justification, an unknowns array, and a counterevidence array whose "
                "basis_index values refer to the answer's original bases, not the returned "
                "deduplicated Evidence list; inactive branch answers may "
                "omit those reasoning fields."
            ),
            examples=[
                [
                    {
                        "question_id": "sq:randomization:sequence",
                        "answer": "probably_yes",
                        "bases": [
                            {"kind": "context", "evidence": "eh_0123456789abcdef"},
                            {
                                "kind": "limitation",
                                "unresolved_premise": "The sequence generator is not reported.",
                                "stopping_rationale": (
                                    "Relevant captured Sources were reviewed, but the premise "
                                    "remains unresolved."
                                ),
                                "search_receipt": "sr_0123456789abcdef",
                            },
                        ],
                        "justification": (
                            "The inspected passage states that a computer generated random "
                            "allocations. The report does not identify who generated the "
                            "sequence."
                        ),
                        "unknowns": ["The report does not identify the sequence generator."],
                        "counterevidence": [
                            {
                                "basis_index": 1,
                                "implication": "The unresolved generator limits confidence.",
                            }
                        ],
                    }
                ]
            ],
        ),
    ],
    supersedes: Annotated[
        Identity | None,
        Field(description="Exact prior checkpoint identity when revising a Domain."),
    ] = None,
    revision_basis: Annotated[
        DomainRevisionBasis | None,
        Field(
            description=(
                "Closed new_evidence, self_correction, or mechanical_repair basis for a revision."
            )
        ),
    ] = None,
) -> ToolResult:
    draft = {
        "trial_id": trial_id,
        "domain_id": domain_id,
        "expected_revision": expected_revision,
        "answers": [answer.model_dump(mode="json") for answer in answers],
        "supersedes": supersedes,
        "revision_basis": (
            revision_basis.model_dump(mode="json") if revision_basis is not None else None
        ),
    }
    return _invoke(
        "validate_domain_assessment",
        lambda: _validate_domain_assessment(_workspace(), draft),
    )


@mcp.tool(
    name="save_domain_judgment",
    title="Save Domain judgment",
    description=(
        "Commit the exact Domain draft stored by validate_domain_assessment. Supply its "
        "reasoning_id and returned revision; do not resend answers. To change the draft, repeat "
        "validate_domain_assessment with the revised draft. Complete the post-approval bounded "
        "main-report text pass and every Domain context page before reasoning. "
        "The fifth accepted Domain makes the Trial ready for review; it remains correctable "
        "until close_trial commits the exact current review."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("save_domain_judgment"),
)
def save_domain_judgment(
    trial_id: Annotated[TrialId, Field(description="Trial being assessed.")],
    domain_id: Annotated[DomainId, Field(description="RoB 2 Domain being assessed.")],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Revision returned by validate_domain_assessment.")
    ],
    reasoning_id: Annotated[
        Identity, Field(description="Exact reasoning_id returned by validate_domain_assessment.")
    ],
) -> ToolResult:
    root = _root(_workspace())
    state = _state(root)
    records = state.get("reasoning_records")
    record = records.get(reasoning_id) if isinstance(records, dict) else None
    if (
        not isinstance(record, dict)
        or record.get("kind") != "domain_reasoning"
        or record.get("trial_id") != trial_id
        or record.get("domain_id") != domain_id
    ):
        return _content(
            "save_domain_judgment",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, submit the complete Domain draft to "
                    "validate_domain_assessment, then save its returned receipt. Otherwise follow "
                    "head.next_action."
                ),
            },
        )
    current_revision = int(state.get("revision", 0))
    stored_draft = record.get("draft")
    if not isinstance(stored_draft, dict):
        return _content(
            "save_domain_judgment",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, refresh the explicit Trial and Domain, "
                    "complete context delivery, revalidate, and save its returned receipt. Otherwise "
                    "follow head.next_action."
                ),
            },
        )
    if expected_revision != record.get("save_revision") or not _domain_reasoning_matches_current(
        root, record, state
    ):
        return _content(
            "save_domain_judgment",
            {
                "outcome": "condition",
                "code": "reasoning_stale",
                "condition": (
                    "Call get_status. If work remains active, refresh the explicit Trial and Domain, "
                    "complete context delivery, revalidate, and save its returned receipt. Otherwise "
                    "follow head.next_action."
                ),
            },
        )
    expected_revision = current_revision
    draft = DomainDraft.model_validate({**stored_draft, "expected_revision": expected_revision})
    return _invoke("save_domain_judgment", lambda: _save_domain_judgment(_workspace(), draft))


@mcp.tool(
    name="review_trial",
    title="Review Trial",
    description=(
        "Prepare an exact current Trial review before closure. With no request, all five current "
        "Domains are reviewed as assessed; an approved unavailable or unsupported-design Result "
        "produces its typed unassessed outcome. For another genuine blocker, supply a needs_input "
        "or failed terminal request. Repairs, unfinished source review, context limits, ordinary "
        "missing Evidence, and uncertainty answerable with an allowed answer are not blockers. "
        "The overall judgment follows the deterministic Cochrane-style rule: any High Domain, "
        "or at least two Some concerns Domains with no High Domain, makes the Trial High; one "
        "Some concerns Domain makes it Some concerns; all Low Domains make it Low. A review is "
        "not closure: inspect its Result and checkpoint identities, correct any Domain if needed. "
        "Review expansion objects contain operation and Evidence metadata, not direct tool "
        "arguments; pass only each operation's declared arguments. Then close using the exact "
        "review reference."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("review_trial"),
)
def review_trial(
    trial_id: Annotated[TrialId, Field(description="Current Trial being reviewed.")],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current revision from get_status.")
    ],
    request: Annotated[
        TerminalRequest | None,
        Field(
            description=(
                "Optional typed needs_input or failed request for a genuine blocker. Omit for "
                "a normal review or an automatically terminal unavailable or unsupported Result. "
                "For uncertainty answerable by the active question card, submit its permitted "
                "uncertainty answer and record the limitation; reserve a terminal request for a "
                "supported workflow that cannot continue."
            ),
        ),
    ] = None,
) -> ToolResult:
    review_request = TrialReviewRequest(
        trial_id=trial_id,
        expected_revision=expected_revision,
        request=request,
    )
    return _invoke("review_trial", lambda: _review_trial(_workspace(), review_request))


@mcp.tool(
    name="close_trial",
    title="Close Trial",
    description=(
        "Close the Trial against the exact current review reference returned by review_trial. "
        "This makes the Trial immutable and advances to the next Trial, or to Batch finalization. "
        "A stale reference is rejected after any Result or Domain correction; searches alone do "
        "not change the reference. Retry the same closure safely with its returned reference."
    ),
    annotations=_MUTATION,
    output_schema=output_schema("close_trial"),
)
def close_trial(
    trial_id: Annotated[TrialId, Field(description="Trial to close.")],
    expected_revision: Annotated[
        ExpectedRevision, Field(description="Current revision from get_status.")
    ],
    review_reference: Annotated[
        Identity, Field(description="Exact current review identity returned by review_trial.")
    ],
) -> ToolResult:
    closure_request = TrialClosureRequest(
        trial_id=trial_id,
        expected_revision=expected_revision,
        review_reference=review_reference,
    )
    return _invoke("close_trial", lambda: _close_trial(_workspace(), closure_request))


@mcp.tool(
    name="finalize_batch",
    title="Finalize batch",
    description=(
        "Package the already-final Trial records into the verified Batch artifact. Call when "
        "get_status reports next_action.operation=finalize_batch. If the final receipt is "
        "unavailable, replay the call with the current revision to recover the artifact and "
        "summary."
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
