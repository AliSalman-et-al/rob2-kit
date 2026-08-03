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
from typing import Annotated, Any, Literal

from pydantic import Field

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


def _submission_key(operation: str, issued_token: str) -> str:
    digest = hashlib.sha256(f"{operation}|{issued_token}".encode()).hexdigest()[:24]
    return f"mcp:{operation}-{digest}"


def create_server(*, determinism: QualificationDeterminism | None = None) -> Any:
    """Build one stdio server with exactly the 13 typed tools."""

    from mcp.server import MCPServer

    engine = RunEngine(determinism=determinism)
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
        """Prepare or resume a project.

        ``project_root`` is required on every new session, including a resumed
        conversation. Pass ``authorized=true`` only after explicit operator
        authorization. A changed project root is a distinct-root error; do not
        weaken that invariant or infer a root from prior context.
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
        run_id: Annotated[str, Field(description="Run ID returned by prepare_run; copy verbatim.")],
    ) -> dict[str, Any]:
        """Return the next authoritative run directive and bounded work item.

        After a retry or dynamic branch, discard prior work context and use only
        the newly issued work token and identifiers from this response.
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
        """Return bounded context for the issued work token.

        Include source details only to inspect page coverage or parsing.
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
    ) -> dict[str, Any]:
        """Submit proposal objects by copying their complete fields exactly as issued."""
        return _dump(
            engine.submit_run_proposal(
                SubmitRunProposalRequest.model_validate(
                    {
                        "run_id": run_id,
                        "proposal_token": proposal_token,
                        "idempotency_key": _submission_key("proposal", proposal_token),
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
        confirmed_by: Actor,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Confirm once with an attributable Actor.

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
        """Search evidence, e.g. query={"terms":["allocation"]}.

        With pass_kind="guidance_seed", choose a stable identifier-shaped family
        label such as seed_family="seed:allocation" and reuse that exact label in
        the coverage receipt. For pass_kind="trial_follow_up" or "contradiction",
        omit seed_family.
        """
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
        classifications: list[SourceClassificationInput],
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Classify exactly the sources in get_work_context.

        Use {"source_id":...,"roles":[...]}; proposal registry candidates are not issued.
        """
        return _dump(
            engine.submit_source_classification(
                SubmitSourceClassificationRequest.model_validate(
                    {
                        "run_id": run_id,
                        "work_token": work_token,
                        "idempotency_key": _submission_key(
                            "source-classification", work_token.token
                        ),
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
        result: Result,
        estimate: Estimate,
        provenance_note: str,
        contract_version: Literal["1.0.0"],
    ) -> dict[str, Any]:
        """Resolve a Result, not a ResultCandidate.

        Set result_id from work_token.result_id and include randomization_id,
        effect/outcome/analysis fields, source_locator, and comparison with
        experimental_arm_id and comparator_arm_id. Use
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
            Field(description="Set true only with complete search receipts and readable coverage."),
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
        coverage_receipts: Annotated[
            list[SearchCoverageReceipt] | None,
            Field(
                description=(
                    "Complete typed receipts returned by search_evidence; omit partial receipts."
                )
            ),
        ] = None,
        project_rules: Annotated[
            list[RecordReference] | None,
            Field(description="Issued project-rule references that materially guide this bundle."),
        ] = None,
    ) -> dict[str, Any]:
        """Freeze one Domain Evidence Bundle using the current work context.

        Use passages using issued ``unit_id``, exact spans, and active
        ``question_ids``; this branch is mutually exclusive with legacy
        ``items``, ``evidence_by_question``, ``candidate_dispositions``, and
        ``conflicts``. Legacy candidate dispositions accept only the enum values
        ``supporting``, ``contradicting``, ``contextual``, ``duplicate``,
        ``out_of_scope``, ``immaterial``, ``superseded``, and ``unresolved``;
        ``irrelevant`` is not valid. Rebind every identifier and token from the
        latest ``get_work_context`` after a retry or dynamic branch.

        Use claim-type IDs. An adequate completed search with no evidence stays
        coverage_state="complete" and may support no_information with complete
        receipts. Use coverage_state="complete_with_limitations" only for a
        material residual source/search uncertainty, and coverage_state="incomplete"
        only when required searching or reading could not finish. Omit
        coverage_receipts unless a tool supplied the complete typed receipt object.
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
                        "coverage_receipts": coverage_receipts or (),
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
        project_rules: list[RecordReference] | None = None,
    ) -> dict[str, Any]:
        """Answer every active question in get_work_context.

        Use yes, probably_yes, probably_no, no, or no_information. Omit inactive questions.
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
                        "project_rules": project_rules or (),
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
