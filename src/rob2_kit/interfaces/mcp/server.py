"""Thin stdio MCP transport for the typed :class:`RunEngine` boundary.

The functions in this module only translate JSON-shaped MCP arguments into
Pydantic request contracts and serialize the resulting response.  Durable
workflow decisions, work-item sequencing, and report publication remain in
``RunEngine``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from mcp.types import CallToolResult, TextContent
from pydantic import Field, ValidationError

from rob2_kit.application.contracts import (
    Actor,
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    ErrorClass,
    Estimate,
    EvidenceConsiderationInput,
    EvidenceCoverageState,
    EvidencePassageInput,
    EvidenceReviewRevision,
    FinalJudgmentInput,
    GetWorkContextRequest,
    InspectVisualCandidateRequest,
    NextAction,
    NextActionArguments,
    OperationError,
    PrepareRunRequest,
    PrepareRunResponse,
    ReadEvidenceRequest,
    RecordReference,
    Result,
    RetrievalErrorResponse,
    RunOperation,
    RunProposal,
    RunProposalAmbiguity,
    RunProposalSelection,
    SearchEvidenceRequest,
    SearchPassKind,
    SearchQuery,
    SearchQueryEnvelope,
    SQAnswerInput,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
    VisualRenderRequest,
    WorkflowCondition,
    WorkToken,
)
from rob2_kit.application.determinism import QualificationDeterminism
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine, SecondProjectRootError
from rob2_kit.evidence.errors import (
    InvalidRetrievalRequest,
    OperationalRetrievalFailure,
    RetrievalFailure,
    invalid_request_from_validation,
)
from rob2_kit.evidence.search import ReadContextMode
from rob2_kit.release import SKILL_ALLOWED_TOOL_NAMES

# This is the release-owned, model-visible contract.  Engine maintenance
# operations deliberately remain Python APIs; exposing them as MCP aliases
# would make a running Harness depend on a different public contract.
CANONICAL_TOOL_NAMES = SKILL_ALLOWED_TOOL_NAMES


class MCPRouteGroup(Protocol):
    """Composable registration seam for one coherent MCP route family."""

    name: str

    def register(self, server: Any, engine: RunEngine) -> None:
        """Register typed tools against a server and shared RunEngine."""


@dataclass(frozen=True)
class RouteGroup:
    """Small adapter used by later slices to extend the MCP catalog."""

    name: str
    register: Callable[[Any, RunEngine], None]


def register_route_groups(
    server: Any,
    engine: RunEngine,
    route_groups: Sequence[MCPRouteGroup],
) -> None:
    """Register route families in deterministic order with unique names."""

    seen: set[str] = set()
    for group in route_groups:
        if not group.name or group.name in seen:
            raise ValueError(f"MCP route group names must be non-empty and unique: {group.name!r}")
        seen.add(group.name)
        group.register(server, engine)


def registered_tool_names() -> tuple[str, ...]:
    """Return the fixed twelve-tool model-visible inventory in wire order."""

    return CANONICAL_TOOL_NAMES


def canonical_tool_names() -> tuple[str, ...]:
    """Return the one release-owned model-visible MCP catalog."""

    return CANONICAL_TOOL_NAMES


def _qualification_determinism_from_environment() -> QualificationDeterminism | None:
    """Build an explicit optional qualification contract at the stdio composition root."""

    value = os.environ.get("ROB2_QUALIFICATION_UTC_NOW")
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("ROB2_QUALIFICATION_UTC_NOW must be an ISO-8601 UTC instant") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("ROB2_QUALIFICATION_UTC_NOW must include a UTC offset")
    return QualificationDeterminism(observed_at=parsed.astimezone(UTC))


def _dump(response: Any) -> dict[str, Any]:
    # Keep the wire envelope compact: absent optional payloads (especially a
    # terminal response's ``next_action``) are omitted rather than repeated as
    # JSON nulls.  The typed response model remains available to Python hosts.
    payload = response.model_dump(mode="json", exclude_none=True)
    # Full discovery records remain durable and available to typed Python
    # hosts, but MCP responses use the compact human proposal projection so
    # parser output and raw source inventories do not consume the conversation
    # context.  Tokens and candidate identifiers are preserved verbatim for
    # the next typed action.
    proposal = getattr(response, "proposal", None)
    if isinstance(proposal, RunProposal):
        payload["proposal"] = proposal.compact_payload()
    page = getattr(response, "page", None)
    if page is not None and hasattr(page, "hits") and "page" in payload:
        # Search is a discovery projection. Keep stable IDs and a bounded
        # exact projection snippet on the wire; read_evidence fetches the full
        # canonical unit and immutable provenance when needed for citation.
        compact_hits = []
        for hit in page.hits:
            compact_projection = hit.projection.model_dump(mode="json")
            compact_projection.pop("text", None)
            compact_hits.append(
                {
                    # Opaque source/Parse-bound navigation identity.  It is
                    # intentionally separate from the canonical or fragment
                    # preview below: the preview can never be frozen directly.
                    "location_handle": hit.location_handle,
                    "unit": {
                        "unit_id": hit.unit.unit_id,
                        "source_id": hit.unit.source_id,
                        "page": hit.unit.page,
                        "kind": hit.unit.kind.value,
                        "document_zone": (
                            hit.unit.document_zone.value if hit.unit.document_zone else None
                        ),
                        "source_role": hit.unit.source_role,
                        "section_path": hit.unit.section_path,
                        "applicability": hit.unit.applicability.value,
                        "warnings": hit.unit.warnings,
                        "table_headers": hit.unit.table_headers,
                        "caption": hit.unit.caption,
                        "estimated_size": len(hit.unit.text),
                    },
                    "projection": compact_projection,
                    "projection_preview": _coherent_wire_snippet(hit.projection.text),
                    "rank": hit.rank,
                    "oversized": hit.oversized,
                    "match_explanation": hit.match_explanation,
                    "warnings": hit.warnings,
                    "duplicate_group_id": hit.duplicate_group_id,
                    "next_actions": ("read_evidence",),
                }
            )
        payload["page"]["hits"] = compact_hits
    context = getattr(response, "context", None)
    if context is not None and "context" in payload and "unit" in payload:
        # The response anchor is already present once at the top level.
        # Replace the context's duplicate canonical payload with its stable ID.
        payload["context"].pop("unit", None)
        payload["context"]["unit_id"] = payload["unit"]["unit_id"]
    return payload


def _wire_result(response: Any) -> CallToolResult:
    """Preserve the compact, unwrapped MCP envelope while retaining output validation."""

    payload = (
        response.model_dump(mode="json", exclude_none=True)
        if isinstance(response, RetrievalErrorResponse)
        else _dump(response)
    )
    fallback = {
        "condition": payload.get("condition"),
        "run_id": payload.get("run_id"),
        "unit_id": payload.get("unit", {}).get("unit_id")
        if isinstance(payload.get("unit"), dict)
        else None,
        "error": payload.get("error"),
    }
    return CallToolResult(
        content=[TextContent(text=json.dumps(fallback, separators=(",", ":")))],
        structured_content=payload,
    )


def _coherent_wire_snippet(text: str, limit: int = 480) -> str:
    """Bound discovery text while preserving a source-authored word boundary."""

    if len(text) <= limit:
        return text
    prefix = text[:limit].rsplit(" ", 1)[0].rstrip()
    return (prefix or text[:limit].rstrip()) + "…"


def _submission_key(operation: str, issued_token: str) -> str:
    digest = hashlib.sha256(f"{operation}|{issued_token}".encode()).hexdigest()[:24]
    return f"mcp:{operation}-{digest}"


def _retrieval_error(error: RetrievalFailure) -> RetrievalErrorResponse:
    """Serialize one typed retrieval failure without inspecting exception text."""

    if not isinstance(error, RetrievalFailure):
        # Programming errors are intentionally not converted into a normal
        # retrieval outcome.  This keeps defects visible to the host/tests.
        raise error
    return RetrievalErrorResponse(
        error={
            "code": error.code,
            "field": error.field,
            "message": error.message,
            "recovery": error.recovery,
        },
        next_actions=error.next_actions,
    )


def create_server(
    *,
    determinism: QualificationDeterminism | None = None,
    engine: RunEngine | None = None,
    route_groups: Sequence[MCPRouteGroup] = (),
) -> Any:
    """Build one stdio server with the release-owned canonical tools.

    ``route_groups`` is deliberately additive for test and host composition,
    but the standard server registers no compatibility aliases.
    """

    from mcp.server import MCPServer

    engine = engine or RunEngine(determinism=determinism)
    server = MCPServer("rob2-kit", version="0.1.0")

    @server.tool(name="prepare_run")
    def prepare_run(
        project_root: Annotated[
            str,
            Field(
                description=(
                    "Required project root path for this session. Provide it on every new "
                    "session; use the same root to resume a Current run."
                )
            ),
        ],
        authorized: Annotated[
            bool,
            Field(description="Set true only after explicit operator authorization."),
        ] = False,
        start_new: Annotated[
            bool,
            Field(
                description="Set true only when the operator explicitly replaces the Current run."
            ),
        ] = False,
        method: Annotated[
            str | None,
            Field(
                description="Optional supported RoB 2 method; omit to use project configuration."
            ),
        ] = None,
        supported_scope: Annotated[
            str | None,
            Field(description="Optional supported scope; omit to use project configuration."),
        ] = None,
    ) -> dict[str, Any]:
        """When to use: begin or reconnect to one assessment project.

        Prerequisite: provide the explicit project root and operator authorization.
        Safe default: resume the Current run at the same root. Not for: silently
        replacing it; use ``start_new`` only after an explicit replacement request.

        Provide ``project_root`` on every new session and set ``authorized=true``
        only after explicit operator authorization.
        """
        request = PrepareRunRequest.model_validate(
            {
                "project_root": project_root,
                "authorized": authorized,
                "start_new": start_new,
                "method": method,
                "supported_scope": supported_scope,
            }
        )
        try:
            response = engine.prepare_run(request)
        except SecondProjectRootError as error:
            digest = hashlib.sha256(str(request.project_root.resolve()).encode()).hexdigest()[:24]
            rejected_run_id = f"run:rejected-{digest}"
            response = PrepareRunResponse(
                operation_id=f"operation:prepare-run-second-root-{digest}",
                ledger_cursor="ledger:unbound",
                affected_scope=(rejected_run_id,),
                condition=WorkflowCondition.RUN_BLOCKED,
                committed=False,
                next_action=NextAction(
                    operation=RunOperation.PREPARE_RUN,
                    reason="Prepare the explicitly selected project root.",
                    arguments=NextActionArguments(run_id=rejected_run_id),
                ),
                run_id=rejected_run_id,
                run_state=RunState.BLOCKED,
                error=OperationError(
                    error_class=ErrorClass.AUTHORITY,
                    code="second_project_root",
                    detail=error.error.detail,
                    recovery=error.error.recovery,
                ),
            )
        return _dump(response)

    @server.tool(name="continue_run")
    def continue_run(
        run_id: Annotated[str, Field(description="Run ID returned by prepare_run; copy verbatim.")],
    ) -> dict[str, Any]:
        """When to use: ask the ledger for the next step in an active run.

        Prerequisite: copy the run ID from ``prepare_run``. Safe default: follow
        only this returned directive. Not for: reusing a prior work item after a retry.
        """
        return _dump(engine.continue_run(ContinueRunRequest.model_validate({"run_id": run_id})))

    @server.tool(name="get_work_context")
    def get_work_context(
        run_id: Annotated[
            str, Field(description="Run ID returned by continue_run; copy verbatim.")
        ],
        work_token: Annotated[
            WorkToken,
            Field(description="Opaque token returned by continue_run for this exact work item."),
        ],
        include_source_details: Annotated[
            bool,
            Field(description="Set true only when page coverage or parsing details are required."),
        ] = False,
    ) -> dict[str, Any]:
        """When to use: inspect the bounded context for the current work item.

        Prerequisite: use the fresh ``continue_run`` token. Safe default: leave
        source details off. Not for: reconstructing scope from chat history.
        """
        return _dump(
            engine.get_work_context(
                GetWorkContextRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "include_source_details": include_source_details,
                    }
                )
            )
        )

    @server.tool(name="submit_run_proposal")
    def submit_run_proposal(
        run_id: str,
        proposal_token: str,
        contract_version: Literal["1.0.0"],
        selections: list[RunProposalSelection] | None = None,
        ambiguities: list[RunProposalAmbiguity] | None = None,
        correction: str | None = None,
    ) -> dict[str, Any]:
        """When to use: revise an unconfirmed Run proposal or submit its selection.

        Prerequisite: copy the issued proposal token. Safe default: submit the
        complete issued selection. Not for: free-form scope changes without issued IDs.
        """
        return _dump(
            engine.submit_run_proposal(
                SubmitRunProposalRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": _submission_key("proposal", proposal_token),
                        "selections": selections or (),
                        "ambiguities": ambiguities or (),
                        "correction": correction,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="confirm_run_definition")
    def confirm_run_definition(
        run_id: str,
        proposal_token: str,
        confirmed_by: Actor,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """When to use: record the human's approval of the latest Run definition.

        Prerequisite: a current proposal token and attributable human Actor.
        Safe default: confirm only after the proposal is understood. Not for:
        approving evidence findings or an already superseded proposal.

        Example: confirmed_by={"kind":"human","actor_id":"actor:operator"}.
        """
        return _dump(
            engine.confirm_run_definition(
                ConfirmRunDefinitionRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": _submission_key("confirmation", proposal_token),
                        "confirmed_by": confirmed_by,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="search_evidence", structured_output=False)
    def search_evidence(
        run_id: Annotated[
            str, Field(min_length=1, description="Run identifier returned by prepare_run.")
        ],
        query: Annotated[
            SearchQueryEnvelope,
            Field(
                description=(
                    "Bounded structured query object; semantic SearchQuery validation "
                    "returns typed invalid_request recovery."
                )
            ),
        ],
        work_token: Annotated[
            WorkToken,
            Field(
                description="Opaque token copied from the active submit_domain_evidence WorkItem."
            ),
        ],
        sq_id: Annotated[str, Field(min_length=1, description="Active signaling-question scope.")],
        result_id: Annotated[
            str | None, Field(min_length=1, description="Optional active Result identifier.")
        ] = None,
        cursor: Annotated[
            str | None,
            Field(min_length=1, description="Opaque next_cursor returned by a prior page."),
        ] = None,
        pass_kind: SearchPassKind | None = None,
        seed_family: Annotated[
            str | None,
            Field(
                description="Stable identifier-shaped guidance seed family, e.g. seed:allocation."
            ),
        ] = None,
        include_other_trial: Annotated[
            bool | None,
            Field(
                deprecated=True,
                description=(
                    "Retired semantic-visibility override. Any supplied value is rejected with "
                    "typed upgrade_required recovery; candidates are now visible by default."
                ),
            ),
        ] = None,
        include_uncertain: Annotated[
            bool | None,
            Field(
                deprecated=True,
                description=(
                    "Retired semantic-visibility override. Any supplied value is rejected with "
                    "typed upgrade_required recovery; uncertain candidates are now visible "
                    "by default."
                ),
            ),
        ] = None,
    ) -> CallToolResult:
        """When to use: search evidence for the active Domain question.

        Prerequisite: a current ``submit_domain_evidence`` WorkToken. Safe default:
        use structured terms and traverse returned pages. Search returns visible,
        non-citable candidates (including uncertain, reference, and other-Trial
        material) with diagnostic labels and opaque location handles. Not for: raw
        FTS, caller budgets, semantic eligibility filtering, or widening scope
        beyond the issued Result.

        For example, use query={"terms":["allocation"]}. With
        pass_kind="guidance_seed", reuse that exact label in the coverage receipt,
        e.g. seed_family="seed:allocation"; for trial_follow_up or contradiction,
        omit seed_family.

        During Domain evidence work, copy ``work_token`` from the active
        ``continue_run`` item. It supplies Trial/Result/Domain scope; never
        widen that scope with IDs from conversation history.

        Do not send retired ``include_other_trial`` or ``include_uncertain``
        overrides. They receive typed ``upgrade_required`` recovery instead of
        silently changing candidate visibility.
        """
        try:
            if include_other_trial is not None or include_uncertain is not None:
                return _wire_result(
                    _retrieval_error(
                        InvalidRetrievalRequest(
                            "upgrade_required: semantic visibility overrides are retired; "
                            "search candidates are visible by default",
                            field=(
                                "include_other_trial"
                                if include_other_trial is not None
                                else "include_uncertain"
                            ),
                            recovery=(
                                "remove the retired override",
                                "retry the same bounded search with the active WorkToken",
                            ),
                        )
                    )
                )
            request = SearchEvidenceRequest.model_validate(
                {
                    "run_id": run_id,
                    "work_token": work_token,
                    "query": SearchQuery.model_validate(query.model_dump()),
                    "result_id": result_id,
                    "cursor": cursor,
                    "sq_id": sq_id,
                    "pass_kind": pass_kind,
                    "seed_family": seed_family,
                }
            )
            return _wire_result(engine.search_evidence(request))
        except RetrievalFailure as error:
            return _wire_result(_retrieval_error(error))
        except ValidationError as error:
            return _wire_result(_retrieval_error(invalid_request_from_validation(error)))
        except (sqlite3.OperationalError, OSError):
            return _wire_result(
                _retrieval_error(
                    OperationalRetrievalFailure("unable to search the evidence retrieval index")
                )
            )

    @server.tool(name="read_evidence", structured_output=False)
    def read_evidence(
        run_id: Annotated[
            str, Field(min_length=1, description="Run identifier returned by prepare_run.")
        ],
        location_handle: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Opaque source/Parse-bound location handle returned by search_evidence."
                ),
            )
        ],
        work_token: Annotated[
            WorkToken,
            Field(
                description="Opaque token copied from the active submit_domain_evidence WorkItem."
            ),
        ],
        sq_id: Annotated[str, Field(min_length=1, description="Active signaling-question scope.")],
        result_id: Annotated[
            str | None, Field(min_length=1, description="Optional active Result identifier.")
        ] = None,
        mode: ReadContextMode = ReadContextMode.UNIT,
        cursor: Annotated[
            str | None,
            Field(min_length=1, description="Opaque section cursor returned by a prior read."),
        ] = None,
    ) -> CallToolResult:
        """When to use: read one source-preserving candidate returned by scoped search.

        Prerequisite: the issued location handle and current
        evidence WorkToken. Safe default: use ``unit`` mode. Not for: unbounded
        document reading; use bounded neighbors, section, window, page, or visual
        expansion only when the returned context calls for it. A read preserves
        source/Parse/fragment lineage, omissions, warnings, and stable continuation;
        it does not turn a search projection into citable Evidence.
        """
        try:
            return _wire_result(
                engine.read_evidence(
                    ReadEvidenceRequest.model_validate(
                        {
                            "run_id": run_id,
                            "location_handle": location_handle,
                            "work_token": work_token,
                            "result_id": result_id,
                            "sq_id": sq_id,
                            "mode": mode,
                            "cursor": cursor,
                        }
                    )
                )
            )
        except RetrievalFailure as error:
            return _wire_result(_retrieval_error(error))
        except ValidationError as error:
            return _wire_result(_retrieval_error(invalid_request_from_validation(error)))
        except (sqlite3.OperationalError, OSError):
            return _wire_result(
                _retrieval_error(
                    OperationalRetrievalFailure("unable to read the evidence retrieval index")
                )
            )

    @server.tool(name="inspect_visual_candidate")
    def inspect_visual_candidate(
        run_id: str,
        candidate_id: str,
        result_id: str | None = None,
        current_render: VisualRenderRequest | None = None,
        still_ambiguous: bool = True,
    ) -> dict[str, Any]:
        """When to use: inspect an issued table, figure, or suspect text region.

        Prerequisite: a visual candidate from current work. Safe default: request its
        bounded render. Not for: rendering whole documents without a visual-inspection gate.
        """
        return _dump(
            engine.inspect_visual_candidate(
                InspectVisualCandidateRequest.model_validate(
                    {
                        "run_id": run_id,
                        "candidate_id": candidate_id,
                        "result_id": result_id,
                        "current_render": current_render,
                        "still_ambiguous": still_ambiguous,
                    }
                )
            )
        )

    @server.tool(name="submit_source_role_review")
    def submit_source_role_review(
        run_id: str,
        work_token: WorkToken,
        selections: list[RunProposalSelection],
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """When to use: review every Source-role candidate before proposing the Run.

        Prerequisite: Source-role candidates issued by ``get_work_context``. Safe default:
        accept each candidate's proposed roles as-is. Not for: treating an unreviewed
        classifier cue as a settled role.

        Review exactly the sources in get_work_context with
        {"source_id":...,"accepted":true}. Supply "roles" only to override
        the candidate's proposed roles, and exclusion_reason when rejecting.
        """
        return _dump(
            engine.submit_source_role_review(
                SubmitSourceRoleReviewRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key(
                            "source-role-review", work_token.token
                        ),
                        "selections": selections,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_result_resolution")
    def submit_result_resolution(
        run_id: str,
        work_token: WorkToken,
        result: Result,
        estimate: Estimate,
        provenance_note: str,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """When to use: resolve the one issued Trial-specific Result.

        Prerequisite: a current resolution token and attributable result locator.
        Safe default: copy the issued Result ID and observed fields. Not for:
        resolving a ResultCandidate or transferring evidence between Trials.

        This is not a ResultCandidate: set ``result_id`` from ``work_token.result_id``
        and include comparison arms such as ``experimental_arm_id``. For example,
        estimate={"value":0.61,"interval_lower":0.50,"interval_upper":0.75}.
        """
        return _dump(
            engine.submit_result_resolution(
                SubmitResultResolutionRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key("result-resolution", work_token.token),
                        "result": result,
                        "estimate": estimate,
                        "provenance_note": provenance_note,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_domain_evidence")
    def submit_domain_evidence(
        run_id: Annotated[
            str, Field(description="Run ID from the current work context; copy verbatim.")
        ],
        work_token: Annotated[
            WorkToken,
            Field(
                description=(
                    "Fresh token issued for this domain evidence work item; rebind after retry."
                )
            ),
        ],
        result_id: Annotated[
            str, Field(description="Result ID issued by get_work_context; copy verbatim.")
        ],
        domain_id: Annotated[
            str, Field(description="Domain ID issued by get_work_context; copy verbatim.")
        ],
        contract_version: Annotated[
            Literal["1.0.0"],
            Field(description="Exact contract version returned by the installed release."),
        ],
        passages: Annotated[
            list[EvidencePassageInput] | None,
            Field(
                description=(
                    "Preferred exact passages. Mutually exclusive with items, "
                    "evidence_by_question, "
                    "candidate_dispositions, and conflicts."
                )
            ),
        ] = None,
        items: Annotated[
            list[RecordReference] | None,
            Field(
                description="Legacy items evidence references; use only when passages is omitted."
            ),
        ] = None,
        coverage_state: Annotated[
            EvidenceCoverageState | None,
            Field(description="Use complete, complete_with_limitations, or incomplete."),
        ] = None,
        coverage_limitations: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Material limitations; exact field name is coverage_limitations, "
                    "not limitation."
                )
            ),
        ] = None,
        no_information_basis: Annotated[
            bool,
            Field(
                description=(
                    "Set true only after search_evidence reports coverage_complete=true for "
                    "every active question in this Domain and every Source was readable."
                )
            ),
        ] = False,
        conflicts: Annotated[
            list[list[str]] | None,
            Field(
                description=(
                    "Legacy conflicts candidate-ID groups; mutually exclusive with passages."
                )
            ),
        ] = None,
        evidence_by_question: Annotated[
            dict[str, list[RecordReference]] | None,
            Field(
                description=(
                    "Legacy evidence_by_question mapping; mutually exclusive with passages."
                )
            ),
        ] = None,
        candidate_dispositions: Annotated[
            list[EvidenceConsiderationInput] | None,
            Field(
                description=(
                    "Legacy candidate dispositions; use exact enum values and mutually exclusive "
                    "with passages."
                )
            ),
        ] = None,
        review_revisions: Annotated[
            list[EvidenceReviewRevision] | None,
            Field(
                description=(
                    "Append-only semantic review revisions. Each records Trial attribution, "
                    "reviewed context handles, exact spans, dispositions, and rationale; "
                    "unresolved or needs_visual_review spans block freeze."
                )
            ),
        ] = None,
        project_rules: Annotated[
            list[RecordReference] | None,
            Field(description="Issued project-rule references that materially guide this bundle."),
        ] = None,
    ) -> dict[str, Any]:
        """When to use: freeze the reviewed evidence for one active Domain.

        Prerequisite: current Domain context, completed required search coverage,
        and append-only semantic review of every material candidate. Safe default:
        submit the issued exact spans and review revisions. Not for: treating a
        search projection, parser label, or incomplete search as citable Evidence
        or as no information.

        ``review_revisions`` bind Trial attribution, Result scope, considered read
        handles, exact source spans, dispositions, and rationale. They are
        append-only; correction creates a later revision. A material unresolved or
        ``needs_visual_review`` span prevents freeze. Other-Trial or reference text
        may be reviewed and rejected explicitly, but omission is not rejection.

        Use passages using issued ``unit_id``, exact spans, and active
        ``question_ids``; this branch is mutually exclusive with legacy
        ``items``, ``evidence_by_question``, ``candidate_dispositions``, and
        ``conflicts``. Legacy candidate dispositions accept only the enum values
        ``supporting``, ``contradicting``, ``contextual``, ``duplicate``,
        ``out_of_scope``, ``immaterial``, ``superseded``, and ``unresolved``;
        ``irrelevant`` is not valid. Rebind every identifier and token from the
        latest ``get_work_context`` after a retry or dynamic branch.

        Use claim-type IDs. An adequate completed search (call search_evidence until
        its coverage_progress reports coverage_complete=true) with no evidence stays
        coverage_state="complete" and may support no_information_basis=true; the
        engine looks up your accumulated Search coverage itself, so there is no
        receipt to construct or submit. Use coverage_state="complete_with_limitations"
        only for a material residual source/search uncertainty, and
        coverage_state="incomplete" only when required searching or reading could
        not finish.
        """
        return _dump(
            engine.submit_domain_evidence(
                SubmitDomainEvidenceRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key("domain-evidence", work_token.token),
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "items": items or (),
                        "passages": passages or (),
                        "coverage_state": coverage_state or EvidenceCoverageState.COMPLETE,
                        "coverage_limitations": coverage_limitations or (),
                        "no_information_basis": no_information_basis,
                        "conflicts": conflicts or (),
                        "evidence_by_question": evidence_by_question or {},
                        "candidate_dispositions": candidate_dispositions or (),
                        "review_revisions": review_revisions or (),
                        "project_rules": project_rules or (),
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_domain_answers")
    def submit_domain_answers(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        answers: list[SQAnswerInput],
        contract_version: Literal["1.0.0"],
        assessor_inputs: dict[str, bool] | None = None,
        final_judgment_departures: list[FinalJudgmentInput] | None = None,
        project_rules: list[RecordReference] | None = None,
    ) -> dict[str, Any]:
        """When to use: answer every active question after its evidence is frozen.

        Prerequisite: current Domain answer token and bounded evidence context.
        Safe default: answer active questions only. Not for: answering inactive questions
        or editing a published report; corrections require an issued correction path.

        Answer every active question in get_work_context with yes, probably_yes,
        probably_no, no, or no_information.
        """
        return _dump(
            engine.submit_domain_answers(
                SubmitDomainAnswersRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key("domain-answers", work_token.token),
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "answers": answers,
                        "assessor_inputs": assessor_inputs or {},
                        "final_judgment_departures": final_judgment_departures or (),
                        "project_rules": project_rules or (),
                        "contract_version": contract_version,
                    }
                )
            )
        )

    register_route_groups(server, engine, route_groups)
    return server


def main() -> None:
    pending = Path.cwd() / ".rob2" / "pending-release-transaction.json"
    if pending.exists() and os.environ.get("ROB2_LIFECYCLE_DOCTOR") != "1":
        raise RuntimeError(
            "a release transaction is pending recovery; run a rob2 lifecycle command before "
            "starting the MCP server"
        )
    determinism = _qualification_determinism_from_environment()
    qualification_flags = (
        "ROB2_QUALIFICATION_ABSENT_FIXTURES",
        "ROB2_QUALIFICATION_INJECTED_FAULT",
        "ROB2_QUALIFICATION_RELEASE_FIXTURE",
    )
    if any(os.environ.get(flag) for flag in qualification_flags):
        from rob2_kit.evaluation.qualification import qualification_engine_from_environment

        engine = qualification_engine_from_environment(determinism, dict(os.environ))
        create_server(engine=engine).run(transport="stdio")
        return
    create_server(determinism=determinism).run(transport="stdio")


if __name__ == "__main__":
    main()
