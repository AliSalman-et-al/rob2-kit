"""Thin stdio MCP transport for the typed :class:`RunEngine` boundary.

The functions in this module only translate JSON-shaped MCP arguments into
Pydantic request contracts and serialize the resulting response.  Durable
workflow decisions, work-item sequencing, and report publication remain in
``RunEngine``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any, Literal

from rob2_kit.application.contracts import (
    RUN_OPERATION_NAMES,
    Actor,
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    Estimate,
    EvidenceConsiderationInput,
    EvidenceCoverageState,
    EvidencePassageInput,
    GetWorkContextRequest,
    InspectVisualCandidateRequest,
    OperationError,
    PrepareRunRequest,
    PrepareRunResponse,
    ReadEvidenceRequest,
    RecordReference,
    Result,
    RunOperation,
    RunProposalAmbiguity,
    RunProposalSelection,
    RunStatusRequest,
    SearchCoverageReceipt,
    SearchEvidenceRequest,
    SearchPassKind,
    SearchPolicy,
    SearchQuery,
    SourceClassificationInput,
    SQAnswerInput,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceClassificationRequest,
    VisualRenderRequest,
    WorkflowCondition,
    WorkToken,
)
from rob2_kit.application.determinism import QualificationDeterminism
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine, SecondProjectRootError


def registered_tool_names() -> tuple[str, ...]:
    """Return the fixed public RunEngine inventory in wire order."""

    return RUN_OPERATION_NAMES


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
    return response.model_dump(mode="json")


def create_server(*, determinism: QualificationDeterminism | None = None) -> Any:
    """Build one stdio server with exactly the 13 typed tools."""

    from mcp.server import MCPServer

    engine = RunEngine(determinism=determinism)
    server = MCPServer("rob2-kit", version="0.1.0")

    @server.tool(name="prepare_run")
    def prepare_run(
        project_root: str,
        authorized: bool = False,
        start_new: bool = False,
        method: str | None = None,
        supported_scope: str | None = None,
    ) -> dict[str, Any]:
        """Prepare or resume one project and return its authoritative proposal state."""
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
                next_permitted_action=RunOperation.PREPARE_RUN,
                run_id=rejected_run_id,
                run_state=RunState.BLOCKED,
                error=OperationError(
                    code="second_project_root",
                    detail=error.error.detail,
                    recovery=error.error.recovery,
                ),
            )
        return _dump(response)

    @server.tool(name="run_status")
    def run_status(
        run_id: str,
    ) -> dict[str, Any]:
        """Read the durable state and progress of a prepared run."""
        return _dump(engine.run_status(RunStatusRequest.model_validate({"run_id": run_id})))

    @server.tool(name="continue_run")
    def continue_run(
        run_id: str,
    ) -> dict[str, Any]:
        """Return the next authoritative run directive and bounded work item."""
        return _dump(engine.continue_run(ContinueRunRequest.model_validate({"run_id": run_id})))

    @server.tool(name="get_work_context")
    def get_work_context(
        run_id: str,
        work_token: WorkToken,
    ) -> dict[str, Any]:
        """Return bounded context for the exact engine-issued work token."""
        return _dump(
            engine.get_work_context(
                GetWorkContextRequest.model_validate({"run_id": run_id, "work_token": work_token})
            )
        )

    @server.tool(name="submit_run_proposal")
    def submit_run_proposal(
        run_id: str,
        proposal_token: str,
        idempotency_key: str,
        contract_version: Literal["1.0.0"],
        selections: list[RunProposalSelection] | None = None,
        ambiguities: list[RunProposalAmbiguity] | None = None,
    ) -> dict[str, Any]:
        """Submit selections using only candidate IDs issued by prepare_run."""
        return _dump(
            engine.submit_run_proposal(
                SubmitRunProposalRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": idempotency_key,
                        "selections": selections or (),
                        "ambiguities": ambiguities or (),
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="confirm_run_definition")
    def confirm_run_definition(
        run_id: str,
        proposal_token: str,
        idempotency_key: str,
        confirmed_by: Actor,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Record the operator's one-time confirmation of the submitted proposal."""
        return _dump(
            engine.confirm_run_definition(
                ConfirmRunDefinitionRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": idempotency_key,
                        "confirmed_by": confirmed_by,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="search_evidence")
    def search_evidence(
        run_id: str,
        query: SearchQuery,
        result_id: str | None = None,
        cursor: str | None = None,
        broad_query_justification: str | None = None,
        policy: SearchPolicy | None = None,
        sq_id: str | None = None,
        pass_kind: SearchPassKind | None = None,
        seed_family: str | None = None,
    ) -> dict[str, Any]:
        """Search canonical evidence with a typed lexical query and bounded pagination."""
        return _dump(
            engine.search_evidence(
                SearchEvidenceRequest.model_validate(
                    {
                        "run_id": run_id,
                        "query": query,
                        "result_id": result_id,
                        "cursor": cursor,
                        "broad_query_justification": broad_query_justification,
                        "policy": policy,
                        "sq_id": sq_id,
                        "pass_kind": pass_kind,
                        "seed_family": seed_family,
                    }
                )
            )
        )

    @server.tool(name="read_evidence")
    def read_evidence(
        run_id: str,
        unit_id: str,
        result_id: str | None = None,
        neighbor_limit: int = 6,
        context_character_target: int = 16_000,
    ) -> dict[str, Any]:
        """Read one engine-issued canonical evidence unit and its bounded neighbors."""
        return _dump(
            engine.read_evidence(
                ReadEvidenceRequest.model_validate(
                    {
                        "run_id": run_id,
                        "unit_id": unit_id,
                        "result_id": result_id,
                        "neighbor_limit": neighbor_limit,
                        "context_character_target": context_character_target,
                    }
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
        """Request or escalate a bounded render for an issued visual candidate."""
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

    @server.tool(name="submit_source_classification")
    def submit_source_classification(
        run_id: str,
        work_token: WorkToken,
        idempotency_key: str,
        classifications: list[SourceClassificationInput],
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Classify every issued source using the roles enumerated by the schema."""
        return _dump(
            engine.submit_source_classification(
                SubmitSourceClassificationRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": idempotency_key,
                        "classifications": classifications,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_result_resolution")
    def submit_result_resolution(
        run_id: str,
        work_token: WorkToken,
        idempotency_key: str,
        result: Result,
        estimate: Estimate,
        provenance_note: str,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Resolve the exact trial-specific Result and its reported estimate."""
        return _dump(
            engine.submit_result_resolution(
                SubmitResultResolutionRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": idempotency_key,
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
        run_id: str,
        work_token: WorkToken,
        idempotency_key: str,
        result_id: str,
        domain_id: str,
        contract_version: Literal["1.0.0"],
        passages: list[EvidencePassageInput] | None = None,
        items: list[RecordReference] | None = None,
        coverage_state: EvidenceCoverageState | None = None,
        coverage_limitations: list[str] | None = None,
        no_information_basis: bool = False,
        conflicts: list[list[str]] | None = None,
        evidence_by_question: dict[str, list[RecordReference]] | None = None,
        candidate_dispositions: list[EvidenceConsiderationInput] | None = None,
        coverage_receipts: list[SearchCoverageReceipt] | None = None,
        project_rules: list[RecordReference] | None = None,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        """Freeze exact canonical passages and coverage for one complete RoB 2 domain."""
        return _dump(
            engine.submit_domain_evidence(
                SubmitDomainEvidenceRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": idempotency_key,
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
                        "coverage_receipts": coverage_receipts or (),
                        "project_rules": project_rules or (),
                        "actor": actor,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    @server.tool(name="submit_domain_answers")
    def submit_domain_answers(
        run_id: str,
        work_token: WorkToken,
        idempotency_key: str,
        result_id: str,
        domain_id: str,
        answers: list[SQAnswerInput],
        contract_version: Literal["1.0.0"],
        project_rules: list[RecordReference] | None = None,
        actor: Actor | None = None,
    ) -> dict[str, Any]:
        """Submit typed answers for every active signaling question in one domain."""
        return _dump(
            engine.submit_domain_answers(
                SubmitDomainAnswersRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": idempotency_key,
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "answers": answers,
                        "project_rules": project_rules or (),
                        "actor": actor,
                        "contract_version": contract_version,
                    }
                )
            )
        )

    return server


def main() -> None:
    create_server(determinism=_qualification_determinism_from_environment()).run(transport="stdio")


if __name__ == "__main__":
    main()
