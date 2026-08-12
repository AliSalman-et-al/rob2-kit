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
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from mcp.types import CallToolResult, TextContent
from pydantic import Field, ValidationError

from rob2_kit.application.contracts import (
    Actor,
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    CorrectQuestionStepRequest,
    ErrorClass,
    Estimate,
    EvidencePassageInput,
    EvidenceReviewRevisionInput,
    GetWorkContextRequest,
    InspectVisualCandidateRequest,
    MaterializeQuestionEvidenceBundleRequest,
    NextAction,
    NextActionArguments,
    OperationError,
    PrepareRunRequest,
    PrepareRunResponse,
    ProposalDiscoveryCoverageReceipt,
    ProposalDiscoveryDispositionInput,
    ProposalPromotionBatchInput,
    QuestionEvidenceBundleBinding,
    QuestionVisualProvenanceInput,
    ReadEvidenceRequest,
    ReportedArmCandidate,
    ReportedEndpointCandidate,
    ReportedRandomizationCandidate,
    Result,
    ResultMappingReviewInput,
    RetrievalErrorResponse,
    RunOperation,
    RunProposal,
    RunProposalAmbiguity,
    RunProposalSelection,
    SearchEvidenceRequest,
    SearchQuery,
    SearchQueryEnvelope,
    SubmitEvidenceReviewRequest,
    SubmitEvidenceStageOutcomeRequest,
    SubmitProposalDiscoveryReviewRequest,
    SubmitQuestionStepRequest,
    SubmitResultMappingReviewRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceChronologyReviewRequest,
    SubmitSourceRoleReviewRequest,
    VisualRenderRequest,
    WorkflowCondition,
    WorkToken,
    model_facing_operation_payload,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine, SecondProjectRootError
from rob2_kit.evidence.errors import (
    OperationalRetrievalFailure,
    RetrievalFailure,
    invalid_request_from_validation,
)
from rob2_kit.evidence.search import (
    EvidenceReadBatchRequest,
    SearchContinuationReason,
)
from rob2_kit.evidence.workflow import (
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
)
from rob2_kit.interfaces.harness import verify_runtime_self_consistency
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
    """Return the fixed release-owned model-visible inventory in wire order."""

    return CANONICAL_TOOL_NAMES


def canonical_tool_names() -> tuple[str, ...]:
    """Return the one release-owned model-visible MCP catalog."""

    return CANONICAL_TOOL_NAMES


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
    if page is not None and hasattr(page, "model_facing_payload") and "page" in payload:
        # Discovery pages retain their complete typed shape for workflow
        # persistence, while models receive this authoritative compact
        # catalogue.  It deliberately excludes repeated defaults and source
        # diagnostics but keeps all conservative-triage facts and read action.
        payload["page"] = page.model_facing_payload()
    elif page is not None and hasattr(page, "hits") and "page" in payload:
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
    if getattr(response, "evidence_navigation_contract_version", None) == "3.0.0":
        # Search/read pages already carry their engine-authored concrete next
        # actions.  The generic lifecycle continuation duplicates that data
        # for every page and is not a navigation instruction.
        # Search packing uses this exact same composition function, including
        # coverage progress and response accounting, before a page is emitted.
        payload = model_facing_operation_payload(response)
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
            "violations": [
                {"field": violation.field, "message": violation.message}
                for violation in error.violations
            ],
        },
        next_actions=error.next_actions,
    )


def create_server(
    *,
    engine: RunEngine | None = None,
    route_groups: Sequence[MCPRouteGroup] = (),
) -> Any:
    """Build one stdio server with the release-owned canonical tools.

    ``route_groups`` is deliberately additive for test and host composition,
    but the standard server registers no compatibility aliases.
    """

    from mcp.server import MCPServer

    engine = engine or RunEngine()
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
        proposal_discovery_query: SearchQuery | None = None,
        proposal_discovery_unit_ids: list[str] | None = None,
        proposal_discovery_continuation: str | None = None,
        proposal_discovery_read_continuation: str | None = None,
        proposal_discovery_pass: str | None = None,
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
                        "proposal_discovery_query": proposal_discovery_query,
                        "proposal_discovery_unit_ids": proposal_discovery_unit_ids or (),
                        "proposal_discovery_continuation": proposal_discovery_continuation,
                        "proposal_discovery_read_continuation": (
                            proposal_discovery_read_continuation
                        ),
                        "proposal_discovery_pass": proposal_discovery_pass,
                    }
                )
            )
        )

    @server.tool(name="submit_run_proposal")
    def submit_run_proposal(
        run_id: str,
        proposal_token: str,
        contract_version: Literal["2.0.0"],
        authorized: Annotated[
            bool,
            Field(description="Set true only after explicit operator authorization."),
        ] = False,
        selections: list[RunProposalSelection] | None = None,
        ambiguities: list[RunProposalAmbiguity] | None = None,
        promotions: ProposalPromotionBatchInput | None = None,
    ) -> dict[str, Any]:
        """When to use: revise an unconfirmed Run proposal or submit its selection.

        Prerequisite: copy the issued proposal token. Safe default: submit the
        complete issued selection. Not for: free-form scope changes without issued IDs.

        Set ``authorized=true`` only after explicit operator authorization; it
        permits registry acquisition for accepted registry candidates on this
        call only.
        """
        return _dump(
            engine.submit_run_proposal(
                SubmitRunProposalRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": _submission_key("proposal", proposal_token),
                        "authorized": authorized,
                        "selections": selections or (),
                        "ambiguities": ambiguities or (),
                        "promotions": promotions,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_proposal_discovery_review")
    def submit_proposal_discovery_review(
        run_id: str,
        work_token: WorkToken,
        coverage_receipt: ProposalDiscoveryCoverageReceipt,
        endpoints: list[ReportedEndpointCandidate] | None = None,
        randomizations: list[ReportedRandomizationCandidate] | None = None,
        arms: list[ReportedArmCandidate] | None = None,
        dispositions: list[ProposalDiscoveryDispositionInput] | None = None,
        contract_version: Literal["1.0.0"] = "1.0.0",
    ) -> dict[str, Any]:
        """When to use: submit one source-bound full-text discovery review.

        Prerequisite: the engine must have issued the current source-bound
        discovery WorkToken. Use only with exact engine-issued
        provenance. Safe default: submit only observations and coverage that
        can be traced to the reviewed source. Not for: binding Run identity or
        inventing Outcome targets.
        """
        return _dump(
            engine.submit_proposal_discovery_review(
                SubmitProposalDiscoveryReviewRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key("proposal-discovery", work_token.token),
                        "coverage_receipt": coverage_receipt,
                        "endpoints": endpoints or (),
                        "randomizations": randomizations or (),
                        "arms": arms or (),
                        "dispositions": dispositions or (),
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_result_mapping_review")
    def submit_result_mapping_review(
        run_id: str,
        work_token: WorkToken,
        proposal_token: str,
        mappings: list[ResultMappingReviewInput],
        contract_version: Literal["1.0.0"] = "1.0.0",
    ) -> dict[str, Any]:
        """When to use: submit semantic Result mappings after human design promotion.

        Prerequisite: the proposal must contain human-promoted design
        identities and the current mapping WorkToken. Mapping is bounded to
        the current proposal token and promoted design identities. Safe default:
        leave uncertain mappings partial. Not for: inferring or
        binding identity. Complete mappings carry an exact Result, Estimate,
        and the accepted endpoint's canonical provenance; a construct synonym
        is permitted only with an explicit human-reviewed rationale. Partial
        mappings remain structured resolution work.
        """
        return _dump(
            engine.submit_result_mapping_review(
                SubmitResultMappingReviewRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "proposal_token": proposal_token,
                        "idempotency_key": _submission_key("result-mapping", work_token.token),
                        "mappings": mappings,
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
            Field(description="Opaque token copied from the active submit_question_step WorkItem."),
        ],
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        expected_navigation_state_hash: str,
        proposition_id: str,
        pass_id: str,
        stage_id: str,
        intent_id: str,
        attempt_id: str,
        continuation: Annotated[
            str | None,
            Field(min_length=1, description="Opaque continuation returned by a prior page."),
        ] = None,
        supersede_attempt_id: str | None = None,
        supersession_rationale: str | None = None,
        continue_reason: SearchContinuationReason | None = None,
        continue_rationale: str | None = None,
    ) -> CallToolResult:
        """When to use: search evidence for the active Domain question.

        Prerequisite: a current question-scoped evidence WorkToken. Safe default:
        use structured terms and traverse returned pages. Search returns visible,
        non-citable candidates with opaque location handles. Not for: raw
        FTS, caller budgets, semantic eligibility filtering, or widening scope
        beyond the issued Result.

        For example, use query={"terms":["allocation"]} with the proposition,
        pass, stage, intent, attempt, session, and navigation-state identities
        copied from the current context.

        During Domain evidence work, copy ``work_token`` from the active
        ``continue_run`` item. It supplies Trial/Result/Domain scope; never
        widen that scope with IDs from conversation history.

        """
        try:
            request = SearchEvidenceRequest.model_validate(
                {
                    "run_id": run_id,
                    "work_token": work_token,
                    "query": SearchQuery.model_validate(query.model_dump()),
                    "result_id": result_id,
                    "domain_id": domain_id,
                    "question_id": question_id,
                    "session_content_hash": session_content_hash,
                    "expected_navigation_state_hash": expected_navigation_state_hash,
                    "contract_version": "3.0.0",
                    "continuation": continuation,
                    "proposition_id": proposition_id,
                    "pass_id": pass_id,
                    "stage_id": stage_id,
                    "intent_id": intent_id,
                    "attempt_id": attempt_id,
                    "supersede_attempt_id": supersede_attempt_id,
                    "supersession_rationale": supersession_rationale,
                    "continue_reason": continue_reason,
                    "continue_rationale": continue_rationale,
                }
            )
            return _wire_result(engine.search_evidence(request))
        except RetrievalFailure as error:
            return _wire_result(_retrieval_error(error))
        except ValidationError as error:
            return _wire_result(
                _retrieval_error(
                    invalid_request_from_validation(error, sibling_model=SearchEvidenceRequest)
                )
            )
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
        batch: EvidenceReadBatchRequest,
        work_token: Annotated[
            WorkToken,
            Field(description="Opaque token copied from the active submit_question_step WorkItem."),
        ],
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        expected_navigation_state_hash: str,
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
                            "contract_version": "3.0.0",
                            "work_token": work_token,
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "session_content_hash": session_content_hash,
                            "expected_navigation_state_hash": expected_navigation_state_hash,
                            "batch": batch,
                        }
                    )
                )
            )
        except RetrievalFailure as error:
            return _wire_result(_retrieval_error(error))
        except ValidationError as error:
            return _wire_result(
                _retrieval_error(
                    invalid_request_from_validation(error, sibling_model=ReadEvidenceRequest)
                )
            )
        except (sqlite3.OperationalError, OSError):
            return _wire_result(
                _retrieval_error(
                    OperationalRetrievalFailure("unable to read the evidence retrieval index")
                )
            )

    @server.tool(name="submit_evidence_review", structured_output=False)
    def submit_evidence_review(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        expected_navigation_state_hash: str,
        submission_id: str,
        page_handles: tuple[str, ...],
        triage_revisions: tuple[V3CandidateTriageRevision, ...],
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: record the exact page-level triage audit before Evidence freeze.

        Prerequisite: an active question-scoped evidence WorkToken and complete exposed
        page handles from v3 search attempts. Safe default: submit one exact
        append-only partition, including selected and superseded
        pages, and triage every candidate. Not for: creating a scientific
        passage or silently auto-disposing candidates; use batch reads and
        materialize_question_evidence_bundle after coverage and triage are ready.
        """
        try:
            request = SubmitEvidenceReviewRequest.model_validate(
                {
                    "contract_version": contract_version,
                    "run_id": run_id,
                    "work_token": work_token,
                    "idempotency_key": idempotency_key or submission_id,
                    "result_id": result_id,
                    "domain_id": domain_id,
                    "question_id": question_id,
                    "session_content_hash": session_content_hash,
                    "expected_navigation_state_hash": expected_navigation_state_hash,
                    "submission_id": submission_id,
                    "page_handles": page_handles,
                    "triage_revisions": triage_revisions,
                }
            )
            return _wire_result(engine.submit_evidence_review(request))
        except RetrievalFailure as error:
            return _wire_result(_retrieval_error(error))
        except ValidationError as error:
            return _wire_result(
                _retrieval_error(
                    invalid_request_from_validation(
                        error, sibling_model=SubmitEvidenceReviewRequest
                    )
                )
            )

    @server.tool(name="submit_evidence_stage_outcome", structured_output=False)
    def submit_evidence_stage_outcome(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        expected_navigation_state_hash: str,
        submission: V3EvidenceStageOutcomeSubmission,
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: close one exhaustively traversed evidence coverage stage.

        Prerequisite: every active intent is fully paged and every exposed candidate
        has terminal triage. Safe default: report the observed closed outcome and
        exact trigger dispositions. Not for: claiming source unavailability without
        an engine-issued acquisition receipt or bypassing a mandatory later stage.
        """
        try:
            return _wire_result(
                engine.submit_evidence_stage_outcome(
                    SubmitEvidenceStageOutcomeRequest.model_validate(
                        {
                            "contract_version": contract_version,
                            "run_id": run_id,
                            "work_token": work_token,
                            "idempotency_key": idempotency_key
                            or _submission_key("evidence-stage-outcome", submission.submission_id),
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "session_content_hash": session_content_hash,
                            "expected_navigation_state_hash": expected_navigation_state_hash,
                            "submission": submission,
                        }
                    )
                )
            )
        except (RetrievalFailure, ValidationError) as error:
            return _wire_result(
                _retrieval_error(
                    error
                    if isinstance(error, RetrievalFailure)
                    else invalid_request_from_validation(
                        error, sibling_model=SubmitEvidenceStageOutcomeRequest
                    )
                )
            )

    @server.tool(name="materialize_question_evidence_bundle", structured_output=False)
    def materialize_question_evidence_bundle(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        frontier_entry_hash: str,
        expected_navigation_state_hash: str,
        review_revisions: list[EvidenceReviewRevisionInput] | None = None,
        passages: list[EvidencePassageInput] | None = None,
        visual_transcriptions: list[QuestionVisualProvenanceInput] | None = None,
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: freeze the reviewed evidence basis for one active question.

        Prerequisite: the question's v3 navigation workflow is closed and every
        supplied review, passage, and visual provenance identity is current. Safe default:
        submit only exact engine-issued revisions and read receipts. Not for:
        selecting polarity, asserting No-information, or freezing search previews.
        """
        try:
            return _wire_result(
                engine.materialize_question_evidence_bundle(
                    MaterializeQuestionEvidenceBundleRequest.model_validate(
                        {
                            "contract_version": contract_version,
                            "run_id": run_id,
                            "work_token": work_token,
                            "idempotency_key": idempotency_key
                            or _submission_key("question-evidence-bundle", work_token.token),
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "session_content_hash": session_content_hash,
                            "frontier_entry_hash": frontier_entry_hash,
                            "expected_navigation_state_hash": expected_navigation_state_hash,
                            "review_revisions": review_revisions or (),
                            "passages": passages or (),
                            "visual_transcriptions": visual_transcriptions or (),
                        }
                    )
                )
            )
        except (RetrievalFailure, ValidationError) as error:
            return _wire_result(
                _retrieval_error(
                    error
                    if isinstance(error, RetrievalFailure)
                    else invalid_request_from_validation(
                        error, sibling_model=MaterializeQuestionEvidenceBundleRequest
                    )
                )
            )

    @server.tool(name="submit_question_step", structured_output=False)
    def submit_question_step(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        frontier_entry_hash: str,
        answer: str | None = None,
        rationale: str | None = None,
        diagnostic_stop: bool = False,
        evidence_bundle: QuestionEvidenceBundleBinding | None = None,
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: commit the active question's answer or diagnostic stop.

        Prerequisite: use the current frontier entry and, for an answer, the exact
        engine-materialized Evidence Bundle. Safe default: submit one active question
        only. Not for: inventing evidence, answering through a material limitation,
        or revising a committed answer; use the issued correction workflow.
        """
        try:
            return _wire_result(
                engine.submit_question_step(
                    SubmitQuestionStepRequest.model_validate(
                        {
                            "contract_version": contract_version,
                            "run_id": run_id,
                            "work_token": work_token,
                            "idempotency_key": idempotency_key
                            or _submission_key("question-step", work_token.token),
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "session_content_hash": session_content_hash,
                            "frontier_entry_hash": frontier_entry_hash,
                            "answer": answer,
                            "rationale": rationale,
                            "diagnostic_stop": diagnostic_stop,
                            "evidence_bundle": evidence_bundle,
                        }
                    )
                )
            )
        except (RetrievalFailure, ValidationError) as error:
            return _wire_result(
                _retrieval_error(
                    error
                    if isinstance(error, RetrievalFailure)
                    else invalid_request_from_validation(
                        error, sibling_model=SubmitQuestionStepRequest
                    )
                )
            )

    @server.tool(name="correct_question_step", structured_output=False)
    def correct_question_step(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        session_content_hash: str,
        prior_step_hash: str,
        answer: str,
        rationale: str,
        evidence_bundle: QuestionEvidenceBundleBinding,
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: replace one effective answer through an issued correction item.

        Prerequisite: copy the correction WorkToken and exact prior effective step
        hash, then bind the replacement to the current Evidence Bundle. Safe default:
        correct only the named question and let the engine invalidate affected later
        work. Not for: editing history or reusing a stale correction token.
        """
        try:
            return _wire_result(
                engine.correct_question_step(
                    CorrectQuestionStepRequest.model_validate(
                        {
                            "contract_version": contract_version,
                            "run_id": run_id,
                            "work_token": work_token,
                            "idempotency_key": idempotency_key
                            or _submission_key("question-correction", work_token.token),
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "session_content_hash": session_content_hash,
                            "prior_step_hash": prior_step_hash,
                            "answer": answer,
                            "rationale": rationale,
                            "evidence_bundle": evidence_bundle,
                        }
                    )
                )
            )
        except (RetrievalFailure, ValidationError) as error:
            return _wire_result(
                _retrieval_error(
                    error
                    if isinstance(error, RetrievalFailure)
                    else invalid_request_from_validation(
                        error, sibling_model=CorrectQuestionStepRequest
                    )
                )
            )

    @server.tool(name="submit_source_chronology_review", structured_output=False)
    def submit_source_chronology_review(
        run_id: str,
        work_token: WorkToken,
        result_id: str,
        domain_id: str,
        question_id: str,
        source_id: str,
        source_artifact_hash: str,
        parse_id: str,
        parse_output_hash: str,
        constraint: str,
        status: str,
        rationale: str,
        evidence_read_receipt: str,
        idempotency_key: str | None = None,
        contract_version: Literal["3.0.0"] = "3.0.0",
    ) -> CallToolResult:
        """When to use: resolve one source's chronology for a constrained stage.

        Prerequisite: an exact source/parse identity and evidence read receipt from
        the active question. Safe default: report only attributable dated evidence.
        Not for: inferring chronology from filenames or unaudited metadata.
        """
        try:
            return _wire_result(
                engine.submit_source_chronology_review(
                    SubmitSourceChronologyReviewRequest.model_validate(
                        {
                            "contract_version": contract_version,
                            "run_id": run_id,
                            "work_token": work_token,
                            "idempotency_key": idempotency_key
                            or _submission_key("source-chronology", work_token.token),
                            "result_id": result_id,
                            "domain_id": domain_id,
                            "question_id": question_id,
                            "source_id": source_id,
                            "source_artifact_hash": source_artifact_hash,
                            "parse_id": parse_id,
                            "parse_output_hash": parse_output_hash,
                            "constraint": constraint,
                            "status": status,
                            "rationale": rationale,
                            "evidence_read_receipt": evidence_read_receipt,
                        }
                    )
                )
            )
        except (RetrievalFailure, ValidationError) as error:
            return _wire_result(
                _retrieval_error(
                    error
                    if isinstance(error, RetrievalFailure)
                    else invalid_request_from_validation(
                        error, sibling_model=SubmitSourceChronologyReviewRequest
                    )
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
        Sources already carrying a registry_current role are deliberately
        excluded from get_work_context's list and must not be submitted here.
        """
        return _dump(
            engine.submit_source_role_review(
                SubmitSourceRoleReviewRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key("source-role-review", work_token.token),
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

    register_route_groups(server, engine, route_groups)
    return server


def main() -> None:
    verify_runtime_self_consistency()
    pending = Path.cwd() / ".rob2" / "pending-release-transaction.json"
    if pending.exists() and os.environ.get("ROB2_LIFECYCLE_DOCTOR") != "1":
        raise RuntimeError(
            "a release transaction is pending recovery; run a rob2 lifecycle command before "
            "starting the MCP server"
        )
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
