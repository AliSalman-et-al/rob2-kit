from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    OutcomeTargetPromotionInput,
    PrepareRunRequest,
    ProposalDiscoveryDispositionInput,
    ProposalPromotionBatchInput,
    RandomizationPromotionInput,
    ResultMappingReviewInput,
    RunOperation,
    RunProposalSelection,
    SubmitProposalDiscoveryReviewRequest,
    SubmitResultMappingReviewRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
)
from rob2_kit.application.run_engine import RunEngine, _ProposalSubmittedRecord
from rob2_kit.domain.results import (
    Comparison,
    DiscoveryCandidateDisposition,
    Estimate,
    ProposalDiscoveryCoverageReceipt,
    ProposalLimitation,
    ProposalLimitationKind,
    ProposalMappingStatus,
    ReportedArmCandidate,
    ReportedCandidateProvenance,
    ReportedEndpointCandidate,
    ReportedRandomizationCandidate,
    Result,
    ResultIdentityCompleteness,
)
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.evidence.search import SearchQuery
from rob2_kit.ingestion.project import OutcomeTarget, PageExtraction, ParserResult
from rob2_kit.storage.ledger import WorkflowEventOutcome


def _provenance() -> ReportedCandidateProvenance:
    return ReportedCandidateProvenance(
        source_id="source:report",
        parse_id="parse:report",
        artifact_hash="sha256:" + "a" * 64,
        canonical_unit_id="canonical-unit:report",
        page_number=1,
        char_start=0,
        char_end=12,
        locator="report.pdf p. 1",
        displayed_text_hash="sha256:" + "b" * 64,
        discovery_policy_revision="discovery-policy:1",
        rationale="Reported in the reviewed unit.",
        reviewed_by=Actor(
            kind=ActorKind.AGENT,
            actor_id="actor:issue120-reviewer",
            display_name="Issue 120 reviewer",
        ),
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_issue120_reported_design_is_linked_and_provenance_bound() -> None:
    provenance = _provenance()
    arm = ReportedArmCandidate(
        candidate_id="reported-arm:a",
        trial_id="trial:a",
        randomization_candidate_id="reported-randomization:a",
        label="Treatment",
        provenance=provenance,
    )
    randomization = ReportedRandomizationCandidate(
        candidate_id="reported-randomization:a",
        trial_id="trial:a",
        label="Main allocation",
        provenance=provenance,
        arm_candidate_ids=(arm.candidate_id,),
    )
    assert randomization.arm_candidate_ids == (arm.candidate_id,)
    with pytest.raises(ValidationError, match="comparison requires"):
        ReportedEndpointCandidate(
            candidate_id="reported-endpoint:a",
            trial_id="trial:a",
            label="Mortality",
            provenance=provenance,
            experimental_arm_candidate_id=arm.candidate_id,
        )


def test_issue120_receipts_and_limitations_are_typed() -> None:
    receipt = ProposalDiscoveryCoverageReceipt(
        receipt_id="proposal-discovery-receipt:a",
        trial_id="trial:a",
        source_id="source:report",
        parse_id="parse:report",
        source_artifact_hash="sha256:" + "a" * 64,
        mode="structure_first",
        state="no_candidates",
        reviewed_by=_human(),
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
        discovery_policy_revision="discovery-policy:1",
        required_passes=("primary-endpoints", "secondary-endpoints"),
        query_passes=("primary-endpoints", "secondary-endpoints"),
        completed_passes=("primary-endpoints", "secondary-endpoints"),
        terminal_stopping_reason="All required structural passes were exhausted.",
    )
    limitation = ProposalLimitation(
        kind=ProposalLimitationKind.NO_OUTCOME_TARGETS,
        scope="run:a",
        material=False,
        detail="No human outcome target is promoted.",
        recovery_actions=("Promote an outcome target.",),
        receipt_ids=(receipt.receipt_id,),
    )
    assert limitation.receipt_ids == (receipt.receipt_id,)


def test_issue120_removes_correction_and_requires_v2_proposal_request() -> None:
    assert RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW.value == "submit_proposal_discovery_review"
    assert RunOperation.SUBMIT_RESULT_MAPPING_REVIEW.value == "submit_result_mapping_review"
    with pytest.raises(ValidationError):
        SubmitRunProposalRequest.model_validate(
            {
                "contract_version": "1.0.0",
                "run_id": "run:a",
                "proposal_token": "proposal-token:a",
                "idempotency_key": "idempotency:a",
            }
        )


class _Parser:
    name = "issue120"
    version = "1"

    def parse(self, data: bytes, *, ocr_enabled: bool, target_pages: tuple[int, ...] | None = None):
        return ParserResult(
            pages=(PageExtraction(page_number=1, width=612, height=792, text=data.decode()),),
            raw_output=data,
        )


def _human() -> Actor:
    return Actor(
        kind=ActorKind.HUMAN,
        actor_id="actor:issue120-human",
        display_name="Issue 120 human",
    )


def _indexed_provenance(
    engine: RunEngine, run_id: str, work, source
) -> ReportedCandidateProvenance:
    searched = None
    for pass_name, query in (
        (
            "reported-design",
            SearchQuery(
                any_of=(
                    ("randomized", "randomised", "allocated", "allocation", "assigned"),
                )
            ),
        ),
        (
            "reported-endpoints",
            SearchQuery(any_of=(("endpoint", "outcome", "primary", "secondary"),)),
        ),
    ):
        response = engine.get_work_context(
            GetWorkContextRequest(
                run_id=run_id,
                work_token=work.work_token,
                proposal_discovery_query=query,
                proposal_discovery_pass=pass_name,
            )
        )
        if (
            response.context is not None
            and response.context.proposal_discovery_page is not None
            and response.context.proposal_discovery_page.candidates
        ):
            searched = response
    assert searched is not None
    assert searched.context is not None and searched.context.proposal_discovery_page is not None
    unit_id = searched.context.proposal_discovery_page.candidates[0].canonical_unit_id
    read = engine.get_work_context(
        GetWorkContextRequest(
            run_id=run_id,
            work_token=work.work_token,
            proposal_discovery_unit_ids=(unit_id,),
        )
    )
    assert read.context is not None
    unit = read.context.proposal_discovery_units[0]
    assert source.artifact_hash is not None
    span_end = min(len(unit.text), 24)
    return ReportedCandidateProvenance(
        source_id=source.source_id,
        parse_id=unit.parse_id,
        artifact_hash=source.artifact_hash,
        canonical_unit_id=unit.unit_id,
        page_number=unit.page,
        char_start=0,
        char_end=span_end,
        locator=f"{source.relative_path} p. {unit.page}",
        displayed_text_hash="sha256:" + hashlib.sha256(
            unit.text[:span_end].encode("utf-8")
        ).hexdigest(),
        discovery_policy_revision="discovery-policy:1",
        rationale="Reported in this reviewed canonical unit.",
        reviewed_by=Actor(
            kind=ActorKind.AGENT,
            actor_id="actor:issue120-reviewer",
            display_name="Issue 120 reviewer",
        ),
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _navigate_discovery(
    engine: RunEngine, run_id: str, work, passes: tuple[str, ...]
) -> tuple[str, ...]:
    unit_ids: list[str] = []
    policy_context = engine.get_work_context(
        GetWorkContextRequest(run_id=run_id, work_token=work.work_token)
    )
    assert policy_context.context is not None
    assert policy_context.context.proposal_discovery_policy is not None
    issued_queries = {
        item.pass_id: item.canonical_query
        for item in policy_context.context.proposal_discovery_policy.pass_queries
    }
    for pass_name in passes:
        query = (
            issued_queries[pass_name]
            if pass_name.startswith("outcome-target:")
            else SearchQuery(
                any_of=(("randomized", "randomised", "allocated", "allocation", "assigned"),)
            )
            if pass_name == "reported-design"
            else SearchQuery(any_of=(("endpoint", "outcome", "primary", "secondary"),))
        )
        response = engine.get_work_context(
            GetWorkContextRequest(
                run_id=run_id,
                work_token=work.work_token,
                proposal_discovery_query=query,
                proposal_discovery_pass=pass_name,
            )
        )
        assert response.context is not None and response.context.proposal_discovery_page is not None
        unit_ids.extend(
            item.canonical_unit_id for item in response.context.proposal_discovery_page.candidates
        )
    unit_ids = list(dict.fromkeys(unit_ids))
    if unit_ids:
        engine.get_work_context(
            GetWorkContextRequest(
                run_id=run_id,
                work_token=work.work_token,
                proposal_discovery_unit_ids=tuple(unit_ids),
            )
        )
    return tuple(unit_ids)


def _discovery_submission(
    *,
    engine: RunEngine,
    run_id: str,
    work,
    source,
    provenance: ReportedCandidateProvenance,
    second_randomization: bool = False,
    endpoint_disposition: str = "accepted",
    without_design: bool = False,
) -> SubmitProposalDiscoveryReviewRequest:
    arms = () if without_design else (
        ReportedArmCandidate(
            candidate_id="reported-arm:treatment",
            trial_id=work.trial_id,
            randomization_candidate_id="reported-randomization:main",
            label="Treatment",
            provenance=provenance,
        ),
        ReportedArmCandidate(
            candidate_id="reported-arm:control",
            trial_id=work.trial_id,
            randomization_candidate_id="reported-randomization:main",
            label="Control",
            provenance=provenance,
        ),
    )
    randomizations = () if without_design else (
        ReportedRandomizationCandidate(
            candidate_id="reported-randomization:main",
            trial_id=work.trial_id,
            label="Main allocation",
            provenance=provenance,
            arm_candidate_ids=tuple(item.candidate_id for item in arms),
        ),
    )
    if second_randomization and not without_design:
        extra_arms = (
            ReportedArmCandidate(
                candidate_id="reported-arm:second-treatment",
                trial_id=work.trial_id,
                randomization_candidate_id="reported-randomization:second",
                label="Second treatment",
                provenance=provenance,
            ),
            ReportedArmCandidate(
                candidate_id="reported-arm:second-control",
                trial_id=work.trial_id,
                randomization_candidate_id="reported-randomization:second",
                label="Second control",
                provenance=provenance,
            ),
        )
        arms += extra_arms
        randomizations += (
            ReportedRandomizationCandidate(
                candidate_id="reported-randomization:second",
                trial_id=work.trial_id,
                label="Second allocation",
                provenance=provenance,
                arm_candidate_ids=tuple(item.candidate_id for item in extra_arms),
            ),
        )
    endpoint = ReportedEndpointCandidate(
        candidate_id="reported-endpoint:mortality",
        trial_id=work.trial_id,
        label="Mortality at 90 days",
        provenance=provenance,
        randomization_candidate_id=(None if without_design else "reported-randomization:main"),
        experimental_arm_candidate_id=(None if without_design else "reported-arm:treatment"),
        comparator_arm_candidate_id=(None if without_design else "reported-arm:control"),
    )
    candidates = (endpoint, *randomizations, *arms)
    dispositions = tuple(
        ProposalDiscoveryDispositionInput(
            candidate_id=item.candidate_id,
            disposition=(
                endpoint_disposition
                if item.candidate_id == endpoint.candidate_id
                else "accepted"
            ),
            detail="Faithful source observation.",
        )
        for item in candidates
    )
    return SubmitProposalDiscoveryReviewRequest(
        contract_version="1.0.0",
        run_id=run_id,
        work_token=work.work_token,
        idempotency_key="idempotency:source-backed-discovery",
        endpoints=(endpoint,),
        randomizations=randomizations,
        arms=arms,
        dispositions=dispositions,
        coverage_receipt=ProposalDiscoveryCoverageReceipt(
            receipt_id="proposal-discovery-receipt:source-backed",
            trial_id=work.trial_id,
        source_id=source.source_id,
        parse_id=provenance.parse_id,
        source_artifact_hash=source.artifact_hash,
            mode="structure_first",
            state="complete",
            discovery_policy_revision="discovery-policy:1",
            required_passes=("reported-design", "reported-endpoints"),
            query_passes=("reported-design", "reported-endpoints"),
            completed_passes=("reported-design", "reported-endpoints"),
            candidate_ids=tuple(item.candidate_id for item in candidates),
            candidate_dispositions=tuple(
                DiscoveryCandidateDisposition.model_validate(item.model_dump())
                for item in dispositions
            ),
            reviewed_by=_human(),
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
            reviewed_unit_ids=(provenance.canonical_unit_id,),
            terminal_stopping_reason="Every required source pass was reviewed.",
        ),
    )


def _source_backed_proposal(
    tmp_path,
    *,
    second_randomization: bool = False,
    endpoint_disposition: str = "accepted",
    submit: bool = True,
    without_design: bool = False,
):
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "primary-report.pdf").write_bytes(
        b"Treatment and control were randomly assigned. "
        b"Primary endpoint mortality at 90 days was reported."
    )
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.initialization is not None
    role_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert role_work is not None and role_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=role_work.work_token,
            idempotency_key="idempotency:source-backed-roles",
            selections=tuple(
                RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    discovery_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert discovery_work is not None
    assert discovery_work.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
    source = prepared.initialization.trials[0].inventory.sources[0]
    request = _discovery_submission(
        engine=engine,
        run_id=prepared.run_id,
        work=discovery_work,
        source=source,
        provenance=_indexed_provenance(engine, prepared.run_id, discovery_work, source),
        second_randomization=second_randomization,
        endpoint_disposition=endpoint_disposition,
        without_design=without_design,
    )
    if not submit:
        return engine, prepared, None, request
    response = engine.submit_proposal_discovery_review(request)
    assert response.condition.value == "accepted" and response.proposal is not None
    return engine, prepared, response.proposal, request


def _promote_design(engine: RunEngine, prepared, proposal, *, key: str = "idempotency:promote"):
    target = OutcomeTarget(
        target_id="outcome-target:mortality",
        label="Mortality",
        outcome_construct="Mortality",
        time_point="90 days",
    )
    response = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=proposal.proposal_token,
            idempotency_key=key,
            promotions=ProposalPromotionBatchInput(
                promoted_by=_human(),
                outcome_targets=(
                    OutcomeTargetPromotionInput(
                        target=target,
                        endpoint_candidate_ids=("reported-endpoint:mortality",),
                    ),
                ),
                randomizations=(
                    RandomizationPromotionInput(
                        randomization_candidate_id="reported-randomization:main",
                        arm_candidate_ids=("reported-arm:treatment", "reported-arm:control"),
                    ),
                ),
            ),
        )
    )
    assert response.condition.value == "confirmation_required" and response.proposal is not None
    return response.proposal


def _exact_mapping(proposal, trial_id: str) -> ResultMappingReviewInput:
    randomizations = dict(proposal.randomization_bindings)
    arms = dict(proposal.arm_bindings)
    endpoint_provenance = next(
        item.provenance
        for item in proposal.reported_endpoint_candidates
        if item.candidate_id == "reported-endpoint:mortality"
    )
    return ResultMappingReviewInput(
        candidate_id="result-candidate:mortality",
        trial_id=trial_id,
        outcome_target_id="outcome-target:mortality",
        endpoint_candidate_id="reported-endpoint:mortality",
        randomization_candidate_id="reported-randomization:main",
        experimental_arm_candidate_id="reported-arm:treatment",
        comparator_arm_candidate_id="reported-arm:control",
        label="90-day mortality analysis",
        mapping_status=ProposalMappingStatus.ACCEPTED,
        identity_completeness=ResultIdentityCompleteness.RESULT_COMPLETE,
        result=Result(
            result_id="result:mortality-90d",
            trial_id=trial_id,
            randomization_id=randomizations["reported-randomization:main"],
            comparison=Comparison(
                experimental_arm_id=arms["reported-arm:treatment"],
                comparator_arm_id=arms["reported-arm:control"],
            ),
            effect_of_interest="assignment",
            outcome_construct="Mortality",
            measurement_instrument="Vital status",
            time_point="90 days",
            analysis_population="intention to treat",
            analysis_model="risk ratio",
            effect_measure="risk ratio",
            source_locator="primary-report.pdf p. 1",
        ),
        estimate=Estimate(value=Decimal("0.80")),
        provenance_note="Exact result reported in the reviewed primary report.",
        source_provenance=endpoint_provenance,
        reviewed_by=_human(),
    )


def _complete_empty_discovery(engine: RunEngine, run_id: str, work, *, key: str):
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id) if any(
        event.operation.startswith("operation:run-proposal")
        for event in engine._bound_ledger(run_id).events()
    ) else None
    initialization = (
        proposal.initialization
        if proposal is not None
        else engine._prepared_initialization(engine._bound_ledger(run_id), run_id)
    )
    source = next(
        source
        for trial in initialization.trials
        for source in trial.inventory.sources
        if source.source_id == work.source_id
    )
    policy_context = engine.get_work_context(
        GetWorkContextRequest(run_id=run_id, work_token=work.work_token)
    )
    assert policy_context.context is not None
    assert policy_context.context.proposal_discovery_policy is not None
    policy = policy_context.context.proposal_discovery_policy
    return engine.submit_proposal_discovery_review(
        SubmitProposalDiscoveryReviewRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key=key,
            coverage_receipt=ProposalDiscoveryCoverageReceipt(
                receipt_id=f"proposal-discovery-receipt:{key.rsplit(':', 1)[-1]}",
                trial_id=work.trial_id,
                source_id=source.source_id,
                parse_id=work.parse_id,
                source_artifact_hash=source.artifact_hash,
                mode="structure_first",
                state="no_candidates",
                reviewed_by=_human(),
                reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                discovery_policy_revision=policy.policy_revision,
                required_passes=policy.required_passes,
                query_passes=policy.required_passes,
                completed_passes=policy.required_passes,
                reviewed_unit_ids=_navigate_discovery(engine, run_id, work, policy.required_passes),
                terminal_stopping_reason="Every required source pass was reviewed.",
            ),
        )
    )


def test_issue120_tokenless_blocked_responses_continue_through_scheduler(tmp_path) -> None:
    engine = RunEngine(parser=_Parser())
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "primary-report.pdf").write_bytes(b"Randomized mortality report.")
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    before_first_proposal = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token="proposal-token:unissued",
            idempotency_key="idempotency:tokenless-before-first",
        )
    )
    assert before_first_proposal.next_action.operation is RunOperation.CONTINUE_RUN

    engine, prepared, limited, _ = _source_backed_proposal(
        tmp_path / "limited", endpoint_disposition="unresolved"
    )
    assert limited is not None
    limitations = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=limited.proposal_token,
            idempotency_key="idempotency:tokenless-limitations",
            confirmed_by=_human(),
        )
    )
    assert limitations.next_action.operation is RunOperation.CONTINUE_RUN

    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path / "pairings")
    assert proposal is not None
    promoted = _promote_design(engine, prepared, proposal)
    pairings = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=promoted.proposal_token,
            idempotency_key="idempotency:tokenless-pairings",
            confirmed_by=_human(),
        )
    )
    assert pairings.next_action.operation is RunOperation.CONTINUE_RUN


def test_issue120_legacy_run_wide_corrections_accumulate_across_proposal_lineage(tmp_path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "first-report.pdf").write_bytes(b"Randomized first report endpoint.")
    (trial / "second-report.pdf").write_bytes(b"Randomized second report endpoint.")
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    roles = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert roles is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=roles.work_token,
            idempotency_key="idempotency:legacy-lineage-roles",
            selections=tuple(
                RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    first = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert first is not None
    _complete_empty_discovery(
        engine, prepared.run_id, first, key="idempotency:legacy-lineage-initial-a"
    )
    second = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert second is not None and second.source_id != first.source_id
    initial = _complete_empty_discovery(
        engine, prepared.run_id, second, key="idempotency:legacy-lineage-initial-b"
    ).proposal
    assert initial is not None

    legacy = engine._freeze_submitted_proposal(
        initial.model_copy(
            update={
                "limitations": initial.limitations
                + (
                    ProposalLimitation(
                        kind=ProposalLimitationKind.DISCOVERY_LIMITED,
                        scope=prepared.run_id,
                        material=True,
                        detail="Legacy run-wide discovery limitation requires corrective review.",
                        recovery_actions=("Complete every issued corrective discovery review.",),
                    ),
                ),
                "supersedes_proposal_id": initial.proposal_id,
            }
        )
    )
    ledger = engine._bound_ledger(prepared.run_id)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ledger.commit(
        engine._transition(
            scope=prepared.run_id,
            operation="operation:run-proposal-submitted",
            operation_key="idempotency:legacy-lineage-marker",
            entity_id="run-proposal-submission:legacy-lineage-marker",
            revision_id="revision:run-proposal-submission-legacy-lineage-marker",
            artifact=_ProposalSubmittedRecord(run_id=prepared.run_id, proposal=legacy),
            checkpoint="checkpoint:run-proposal-submitted",
            outcome=WorkflowEventOutcome.WORK_REQUIRED,
            observed_at=now,
        ),
        engine._acquire_lease(ledger, now),
        now=now,
    )

    corrective_a = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert corrective_a is not None
    first_successor = _complete_empty_discovery(
        engine, prepared.run_id, corrective_a, key="idempotency:legacy-lineage-correct-a"
    ).proposal
    assert first_successor is not None
    corrective_b = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert corrective_b is not None and corrective_b.source_id != corrective_a.source_id
    second_successor = _complete_empty_discovery(
        engine, prepared.run_id, corrective_b, key="idempotency:legacy-lineage-correct-b"
    ).proposal
    assert second_successor is not None
    assert engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item is None


def test_issue120_targetless_discovery_precedes_proposal(tmp_path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "primary-report.pdf").write_bytes(
        b"Participants were randomized. The primary outcome was mortality."
    )
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.initialization is not None
    assert prepared.proposal is None
    source = prepared.initialization.trials[0].inventory.sources[0]
    role_work = engine.continue_run.__self__._next_work_item(  # type: ignore[attr-defined]
        engine._bound_ledger(prepared.run_id), prepared.run_id
    )
    assert role_work is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=role_work.work_token,
            idempotency_key="idempotency:roles",
            selections=(
                RunProposalSelection(
                    trial_id=prepared.initialization.trials[0].trial_id,
                    source_id=source.source_id,
                ),
            ),
        )
    )
    work = engine._next_work_item(engine._bound_ledger(prepared.run_id), prepared.run_id)
    assert work is not None and work.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
    context = engine.get_work_context(
        GetWorkContextRequest(
            run_id=prepared.run_id,
            work_token=work.work_token,
            include_source_details=True,
        )
    )
    assert context.context is not None
    assert context.context.proposal_discovery_policy is not None
    assert context.context.proposal_discovery_policy.required_passes == (
        "reported-design",
        "reported-endpoints",
    )
    for pass_name in ("reported-design", "reported-endpoints"):
        template = next(
            item
            for item in context.context.proposal_discovery_policy.pass_queries
            if item.pass_id == pass_name
        )
        matched = engine.get_work_context(
            GetWorkContextRequest(
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_discovery_query=template.canonical_query,
                proposal_discovery_pass=pass_name,
            )
        )
        assert matched.context is not None
        assert matched.context.proposal_discovery_page is not None
        assert matched.context.proposal_discovery_page.candidates
    with pytest.raises(ValueError, match="pass template"):
        engine.get_work_context(
            GetWorkContextRequest(
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_discovery_query=SearchQuery(terms=("mortality",)),
                proposal_discovery_pass="reported-design",
            )
        )
    with pytest.raises(ValueError, match="pass template"):
        engine.get_work_context(
            GetWorkContextRequest(
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_discovery_query=SearchQuery(
                    terms=("assigned", "endpoint", "definitely-no-such-token")
                ),
                proposal_discovery_pass="reported-endpoints",
            )
        )
    with pytest.raises(ValueError, match="pass template"):
        engine.get_work_context(
            GetWorkContextRequest(
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_discovery_query=SearchQuery(
                    terms=("assigned", "endpoint", "definitely-no-such-token")
                ),
                proposal_discovery_pass="reported-design",
            )
        )
    with pytest.raises(ValidationError, match="at most 4"):
        GetWorkContextRequest(
            run_id=prepared.run_id,
            work_token=work.work_token,
            proposal_discovery_unit_ids=("canonical-unit:a",) * 5,
        )
    with pytest.raises(ValueError, match="must use canonical units surfaced"):
        engine.get_work_context(
            GetWorkContextRequest(
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_discovery_unit_ids=("canonical-unit:unread",),
            )
        )
    parsed = context.context.detailed_sources[0].parse_records[0]  # type: ignore[union-attr]
    reviewed_unit_ids = _navigate_discovery(
        engine, prepared.run_id, work, ("reported-design", "reported-endpoints")
    )
    receipt = ProposalDiscoveryCoverageReceipt(
        receipt_id="proposal-discovery-receipt:a",
        trial_id=work.trial_id,
        source_id=source.source_id,
        parse_id=parsed.parse_id,
        source_artifact_hash=source.artifact_hash,
        mode="structure_first",
        state="no_candidates",
        reviewed_by=_human(),
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
        discovery_policy_revision="discovery-policy:1",
        required_passes=("reported-design", "reported-endpoints"),
        query_passes=("reported-design", "reported-endpoints"),
        completed_passes=("reported-design", "reported-endpoints"),
        reviewed_unit_ids=reviewed_unit_ids,
        terminal_stopping_reason="The required structural pass was exhausted.",
    )
    submitted = engine.submit_proposal_discovery_review(
        SubmitProposalDiscoveryReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:discovery",
            coverage_receipt=receipt,
        )
    )
    assert submitted.condition.value == "accepted", submitted.error
    assert submitted.proposal is not None
    assert submitted.proposal.limitations[0].kind is ProposalLimitationKind.NO_OUTCOME_TARGETS
    with pytest.raises(ValidationError, match="correction"):
        SubmitRunProposalRequest.model_validate(
            {
                "contract_version": "2.0.0",
                "run_id": "run:a",
                "proposal_token": "proposal-token:a",
                "idempotency_key": "idempotency:a",
                "correction": "select whatever",
            }
        )


def test_issue120_receipt_requires_terminal_complete_coverage_and_dispositions() -> None:
    with pytest.raises(ValidationError, match="missing required passes"):
        ProposalDiscoveryCoverageReceipt(
            receipt_id="proposal-discovery-receipt:unfinished",
            trial_id="trial:a",
        source_id="source:a",
        parse_id="parse:a",
        source_artifact_hash="sha256:" + "a" * 64,
            mode="structure_first",
            state="no_candidates",
            reviewed_by=_human(),
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
            discovery_policy_revision="discovery-policy:1",
            required_passes=("endpoints",),
            query_passes=("endpoints",),
            terminal_stopping_reason="Stopped.",
        )
    with pytest.raises(ValidationError, match="accepted.*rejected.*unresolved"):
        ProposalDiscoveryCoverageReceipt(
            receipt_id="proposal-discovery-receipt:superseded",
            trial_id="trial:a",
        source_id="source:a",
        parse_id="parse:a",
        source_artifact_hash="sha256:" + "a" * 64,
            mode="structure_first",
            state="complete",
            discovery_policy_revision="discovery-policy:1",
            required_passes=("endpoints",),
            query_passes=("endpoints",),
            completed_passes=("endpoints",),
            candidate_ids=("reported-endpoint:a",),
            candidate_dispositions=(
                DiscoveryCandidateDisposition(
                    candidate_id="reported-endpoint:a",
                    disposition="superseded",
                    detail="Superseded.",
                    superseded_by_candidate_id="reported-endpoint:b",
                ),
            ),
            terminal_stopping_reason="Completed.",
        )


def test_issue120_mapping_axes_reject_exact_result_before_accepted_complete() -> None:
    mapping = ResultMappingReviewInput(
        candidate_id="result-candidate:a",
        trial_id="trial:a",
        endpoint_candidate_id="reported-endpoint:a",
        randomization_candidate_id="reported-randomization:a",
        experimental_arm_candidate_id="reported-arm:a",
        comparator_arm_candidate_id="reported-arm:b",
        label="Endpoint mapping",
        mapping_status=ProposalMappingStatus.PROPOSED,
        identity_completeness=ResultIdentityCompleteness.ANALYSIS_PARTIAL,
        reviewed_by=_human(),
    )
    assert mapping.mapping_status is ProposalMappingStatus.PROPOSED
    assert (
        ResultMappingReviewInput.model_fields["mapping_status"].annotation is ProposalMappingStatus
    )
    assert ResultIdentityCompleteness.RESULT_COMPLETE.value == "result_complete"


def test_issue120_disposition_input_uses_no_duplicate_grammar() -> None:
    disposition = ProposalDiscoveryDispositionInput(
        candidate_id="reported-endpoint:a",
        disposition="accepted",
        detail="Faithful observation.",
    )
    assert disposition.disposition == "accepted"
    with pytest.raises(ValidationError):
        ProposalDiscoveryDispositionInput(
            candidate_id="reported-endpoint:a",
            disposition="duplicate",  # type: ignore[arg-type]
            detail="Deprecated disposition.",
        )


def test_issue120_first_proposal_waits_for_every_eligible_source(tmp_path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "one.pdf").write_bytes(b"Primary endpoint one")
    (trial / "two.pdf").write_bytes(b"Primary endpoint two")
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is None and prepared.initialization is not None
    roles = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert roles is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=roles.work_token,
            idempotency_key="idempotency:two-source-roles",
            selections=tuple(
                RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    first: object | None = None
    for number in (1, 2):
        work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
        assert work is not None and work.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
        source = next(
            source
            for item in prepared.initialization.trials
            if item.trial_id == work.trial_id
            for source in item.inventory.sources
            if source.source_id == work.source_id
        )
        reviewed_unit_ids = _navigate_discovery(
            engine, prepared.run_id, work, ("reported-design", "reported-endpoints")
        )
        submitted = engine.submit_proposal_discovery_review(
            SubmitProposalDiscoveryReviewRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:two-source-{number}",
                coverage_receipt=ProposalDiscoveryCoverageReceipt(
                    receipt_id=f"proposal-discovery-receipt:two-{number}",
                    trial_id=work.trial_id,
                    source_id=source.source_id,
                    parse_id=source.parse_records[0].parse_id,
                    source_artifact_hash=source.artifact_hash,
                    mode="structure_first",
                    state="no_candidates",
                    reviewed_by=_human(),
                    reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    discovery_policy_revision="discovery-policy:1",
                    required_passes=("reported-design", "reported-endpoints"),
                    query_passes=("reported-design", "reported-endpoints"),
                        completed_passes=("reported-design", "reported-endpoints"),
                        reviewed_unit_ids=reviewed_unit_ids,
                    terminal_stopping_reason="Required pass exhausted.",
                ),
            )
        )
        if number == 1:
            assert submitted.proposal is None
        else:
            first = submitted.proposal
    assert first is not None


@pytest.mark.parametrize("tamper", ("unit", "span", "hash"))
def test_issue120_discovery_rejects_tampered_indexed_provenance(tmp_path, tamper: str) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "primary-report.pdf").write_bytes(
        b"Randomized mortality analysis in canonical text. Primary endpoint mortality."
    )
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.initialization is not None
    roles = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert roles is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=roles.work_token,
            idempotency_key="idempotency:tamper-roles",
            selections=tuple(
                RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None
    source = prepared.initialization.trials[0].inventory.sources[0]
    provenance = _indexed_provenance(engine, prepared.run_id, work, source)
    if tamper == "unit":
        provenance = provenance.model_copy(update={"canonical_unit_id": "canonical-unit:forged"})
    elif tamper == "span":
        provenance = provenance.model_copy(update={"char_end": provenance.char_end + 100})
    else:
        provenance = provenance.model_copy(update={"displayed_text_hash": "sha256:" + "0" * 64})
    request = _discovery_submission(
        engine=engine,
        run_id=prepared.run_id,
        work=work,
        source=source,
        provenance=provenance,
    )
    with pytest.raises(ValueError):
        engine.submit_proposal_discovery_review(request)
    assert engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item == work


def test_issue120_promotion_is_human_atomic_and_idempotent(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path, second_randomization=True)
    with pytest.raises(ValidationError, match="human actor"):
        ProposalPromotionBatchInput(promoted_by=_provenance().reviewed_by)
    with pytest.raises(ValueError, match="complete Arm set"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=proposal.proposal_token,
                idempotency_key="idempotency:partial-promotion",
                promotions=ProposalPromotionBatchInput(
                    promoted_by=_human(),
                    randomizations=(
                        RandomizationPromotionInput(
                            randomization_candidate_id="reported-randomization:main",
                            arm_candidate_ids=("reported-arm:treatment",),
                        ),
                    ),
                ),
            )
        )
    with pytest.raises(ValueError, match="complete Arm set"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=proposal.proposal_token,
                idempotency_key="idempotency:cross-randomization-promotion",
                promotions=ProposalPromotionBatchInput(
                    promoted_by=_human(),
                    randomizations=(
                        RandomizationPromotionInput(
                            randomization_candidate_id="reported-randomization:main",
                            arm_candidate_ids=(
                                "reported-arm:treatment",
                                "reported-arm:second-control",
                            ),
                        ),
                    ),
                ),
            )
        )
    promoted = _promote_design(engine, prepared, proposal)
    retry = _promote_design(engine, prepared, proposal)
    assert retry.randomization_bindings == promoted.randomization_bindings
    assert retry.arm_bindings == promoted.arm_bindings


def test_issue120_endpoint_promotion_requires_its_design_batch(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path)
    with pytest.raises(ValueError, match="Randomization and ordered Arms"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=proposal.proposal_token,
                idempotency_key="idempotency:target-without-design",
                promotions=ProposalPromotionBatchInput(
                    promoted_by=_human(),
                    outcome_targets=(
                        OutcomeTargetPromotionInput(
                            target=OutcomeTarget(
                                target_id="outcome-target:mortality",
                                label="Mortality",
                                outcome_construct="Mortality",
                                time_point="90 days",
                            ),
                            endpoint_candidate_ids=("reported-endpoint:mortality",),
                        ),
                    ),
                ),
            )
        )


def test_issue120_rejected_endpoint_is_terminal_not_mapping_work(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(
        tmp_path, endpoint_disposition="rejected"
    )
    promoted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=proposal.proposal_token,
            idempotency_key="idempotency:promote-design-with-rejected-endpoint",
            promotions=ProposalPromotionBatchInput(
                promoted_by=_human(),
                randomizations=(
                    RandomizationPromotionInput(
                        randomization_candidate_id="reported-randomization:main",
                        arm_candidate_ids=("reported-arm:treatment", "reported-arm:control"),
                    ),
                ),
            ),
        )
    )
    assert promoted.proposal is not None
    assert any(
        "terminal exclusions" in limitation.detail
        for limitation in promoted.proposal.limitations
    )
    assert engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item is None


def test_issue120_complete_mapping_registers_spec_and_survives_confirmation(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path)
    trial_id = prepared.initialization.trials[0].trial_id
    promoted = _promote_design(engine, prepared, proposal)
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.operation is RunOperation.SUBMIT_RESULT_MAPPING_REVIEW
    mapped = engine.submit_result_mapping_review(
        SubmitResultMappingReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            proposal_token=promoted.proposal_token,
            idempotency_key="idempotency:exact-mapping",
            mappings=(_exact_mapping(promoted, trial_id),),
        )
    )
    assert mapped.proposal is not None
    assert not mapped.proposal.initialization.result_specs
    selected = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=mapped.proposal.proposal_token,
            idempotency_key="idempotency:select-mapped-result",
            selections=(
                RunProposalSelection(
                    trial_id=trial_id,
                    outcome_target_id="outcome-target:mortality",
                    result_candidate_id="result-candidate:mortality",
                    result_id="result:mortality-90d",
                ),
            ),
        )
    )
    assert selected.proposal is not None
    confirmed = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=selected.proposal.proposal_token,
            idempotency_key="idempotency:confirm-mapped-result",
            confirmed_by=_human(),
        )
    )
    assert confirmed.run_definition is not None
    assert confirmed.run_definition.result_ids == ("result:mortality-90d",)
    downstream = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert downstream is not None and downstream.result_id == "result:mortality-90d"
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=prepared.run_id, work_token=downstream.work_token)
    )
    assert context.context is not None
    assert context.context.result_spec is not None
    assert context.context.result_spec.result.result_id == "result:mortality-90d"


def test_issue120_complete_mapping_requires_exact_endpoint_unit_and_span(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path)
    trial_id = prepared.initialization.trials[0].trial_id
    promoted = _promote_design(engine, prepared, proposal)
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.operation is RunOperation.SUBMIT_RESULT_MAPPING_REVIEW
    exact = _exact_mapping(promoted, trial_id)
    assert exact.source_provenance is not None
    mismatched = exact.model_copy(
        update={
            "source_provenance": exact.source_provenance.model_copy(
                update={"char_end": exact.source_provenance.char_end - 1}
            )
        }
    )
    with pytest.raises(ValueError, match="exact accepted endpoint canonical unit"):
        engine.submit_result_mapping_review(
            SubmitResultMappingReviewRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                work_token=work.work_token,
                proposal_token=promoted.proposal_token,
                idempotency_key="idempotency:mismatched-endpoint-span",
                mappings=(mismatched,),
            )
        )


def test_issue120_construct_synonym_requires_explicit_human_rationale(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path)
    trial_id = prepared.initialization.trials[0].trial_id
    promoted = _promote_design(engine, prepared, proposal)
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.operation is RunOperation.SUBMIT_RESULT_MAPPING_REVIEW
    exact = _exact_mapping(promoted, trial_id)
    synonym = exact.model_copy(
        update={
            "result": exact.result.model_copy(update={"outcome_construct": "All-cause death"}),
            "construct_admissibility": "accepted_synonym",
            "construct_synonym_rationale": (
                "The reviewed report uses all-cause death for mortality."
            ),
        }
    )
    accepted = engine.submit_result_mapping_review(
        SubmitResultMappingReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            proposal_token=promoted.proposal_token,
            idempotency_key="idempotency:accepted-construct-synonym",
            mappings=(synonym,),
        )
    )
    assert accepted.proposal is not None


def test_issue120_discovery_receipt_rejects_stale_artifact_identity(tmp_path) -> None:
    engine, prepared, _, request = _source_backed_proposal(tmp_path, submit=False)
    stale = request.model_copy(
        update={
            "idempotency_key": "idempotency:stale-artifact-receipt",
            "coverage_receipt": request.coverage_receipt.model_copy(
                update={"source_artifact_hash": "sha256:" + "0" * 64}
            ),
        }
    )
    with pytest.raises(ValueError, match="current Source artifact and Parse"):
        engine.submit_proposal_discovery_review(stale)


def test_issue120_successor_identity_digests_full_discovery_candidate_content(tmp_path) -> None:
    engine, _, proposal, _ = _source_backed_proposal(tmp_path)
    assert proposal is not None
    same = engine._freeze_submitted_proposal(proposal)  # type: ignore[attr-defined]
    changed_candidate = proposal.reported_endpoint_candidates[0].model_copy(
        update={"label": "Changed reported mortality wording"}
    )
    changed = proposal.model_copy(
        update={"reported_endpoint_candidates": (changed_candidate,)}
    )
    changed = engine._freeze_submitted_proposal(changed)  # type: ignore[attr-defined]
    assert same.proposal_id == proposal.proposal_id
    assert changed.proposal_id != proposal.proposal_id


def test_issue120_discovery_rejects_forged_pass_classification(tmp_path) -> None:
    engine, _, _, request = _source_backed_proposal(tmp_path, submit=False)
    forged = request.model_copy(
        update={
            "coverage_receipt": request.coverage_receipt.model_copy(
                update={"query_passes": ("forged-pass",)}
            )
        }
    )
    with pytest.raises(ValueError, match="pass classifications"):
        engine.submit_proposal_discovery_review(forged)


def test_issue120_cross_source_relationships_need_linked_other_candidate(tmp_path) -> None:
    with pytest.raises(ValidationError, match="requires related candidates"):
        ReportedEndpointCandidate(
            candidate_id="reported-endpoint:relationship",
            trial_id="trial:a",
            label="Relationship test",
            provenance=_provenance(),
            relationship="corroborating",
        )
    engine, _, _, request = _source_backed_proposal(tmp_path, submit=False)
    endpoint = request.endpoints[0].model_copy(
        update={
            "relationship": "corroborating",
            "related_candidate_ids": ("reported-endpoint:unknown",),
        }
    )
    linked = request.model_copy(update={"endpoints": (endpoint,)})
    with pytest.raises(ValueError, match="unknown candidate"):
        engine.submit_proposal_discovery_review(linked)


def test_issue120_run_scoped_unresolved_discovery_gets_corrective_token(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(
        tmp_path, endpoint_disposition="unresolved"
    )
    assert proposal is not None
    corrective = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert corrective is not None
    assert corrective.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
    assert corrective.source_id == proposal.reported_endpoint_candidates[0].provenance.source_id


def test_issue120_design_undiscovered_corrective_review_uses_successor_targets(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path, without_design=True)
    assert proposal is not None
    promoted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=proposal.proposal_token,
            idempotency_key="idempotency:promote-design-undiscovered",
            promotions=ProposalPromotionBatchInput(
                promoted_by=_human(),
                outcome_targets=(
                    OutcomeTargetPromotionInput(
                        target=OutcomeTarget(
                            target_id="outcome-target:mortality",
                            label="Mortality",
                            outcome_construct="Mortality",
                        ),
                        endpoint_candidate_ids=("reported-endpoint:mortality",),
                        admissibility_rule="design_undiscovered",
                    ),
                ),
            ),
        )
    )
    assert promoted.proposal is not None
    corrective = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert corrective is not None
    assert corrective.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=prepared.run_id, work_token=corrective.work_token)
    )
    assert context.context is not None and context.context.proposal_discovery_policy is not None
    policy = context.context.proposal_discovery_policy
    assert policy.required_passes == ("outcome-target:mortality",)
    reviewed_unit_ids = _navigate_discovery(
        engine, prepared.run_id, corrective, policy.required_passes
    )
    source = promoted.proposal.initialization.trials[0].inventory.sources[0]
    corrected = engine.submit_proposal_discovery_review(
        SubmitProposalDiscoveryReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=corrective.work_token,
            idempotency_key="idempotency:correct-design-undiscovered",
            coverage_receipt=ProposalDiscoveryCoverageReceipt(
                receipt_id="proposal-discovery-receipt:corrected-design",
                trial_id=corrective.trial_id,
                source_id=source.source_id,
                parse_id=source.parse_records[0].parse_id,
                source_artifact_hash=source.artifact_hash,
                mode="target_guided",
                state="complete_with_limitations",
                detail="Design remains unavailable after target-guided review.",
                reviewed_by=_human(),
                reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                discovery_policy_revision=policy.policy_revision,
                required_passes=policy.required_passes,
                query_passes=policy.required_passes,
                completed_passes=policy.required_passes,
                reviewed_unit_ids=reviewed_unit_ids,
                terminal_stopping_reason="Corrective target-guided pass complete.",
            ),
        )
    )
    assert corrected.proposal is not None
    assert corrected.proposal.supersedes_proposal_id == promoted.proposal.proposal_id
    assert corrected.proposal.initialization.manifest.outcome_target_specs[0].target_id == (
        "outcome-target:mortality"
    )
    assert corrected.proposal.promotion_batches == promoted.proposal.promotion_batches


def test_issue120_incomplete_and_nonaccepted_mappings_are_typed_and_safe(tmp_path) -> None:
    engine, prepared, proposal, _ = _source_backed_proposal(tmp_path)
    trial_id = prepared.initialization.trials[0].trial_id
    promoted = _promote_design(engine, prepared, proposal)
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None
    incomplete = ResultMappingReviewInput(
        candidate_id="result-candidate:partial",
        trial_id=trial_id,
        outcome_target_id="outcome-target:mortality",
        endpoint_candidate_id="reported-endpoint:mortality",
        randomization_candidate_id="reported-randomization:main",
        experimental_arm_candidate_id="reported-arm:treatment",
        comparator_arm_candidate_id="reported-arm:control",
        label="Incomplete mortality analysis",
        mapping_status=ProposalMappingStatus.PROPOSED,
        identity_completeness=ResultIdentityCompleteness.ANALYSIS_PARTIAL,
        reviewed_by=_human(),
    )
    mapped = engine.submit_result_mapping_review(
        SubmitResultMappingReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            proposal_token=promoted.proposal_token,
            idempotency_key="idempotency:partial-mapping",
            mappings=(incomplete,),
        )
    )
    assert mapped.proposal is not None
    assert mapped.proposal.limitations[-1].kind is ProposalLimitationKind.RESULT_MAPPING_INCOMPLETE
    assert not mapped.proposal.limitations[-1].material
    iterative = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert iterative is not None
    assert iterative.operation is RunOperation.SUBMIT_RESULT_RESOLUTION
    assert iterative.work_token != work.work_token
    pending_result_id = mapped.proposal.result_candidates[0].result_id
    assert pending_result_id is not None
    exact = _exact_mapping(promoted, trial_id)
    assert exact.result is not None and exact.estimate is not None
    resolved = engine.submit_result_resolution(
        SubmitResultResolutionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=iterative.work_token,
            idempotency_key="idempotency:resolve-partial-result",
            result=exact.result.model_copy(update={"result_id": pending_result_id}),
            estimate=exact.estimate,
            provenance_note="Resolved through the issued partial-mapping continuation.",
        )
    )
    assert resolved.result_spec is not None
    after_resolution = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    assert after_resolution.work_item is None
    assert after_resolution.condition.value == "confirmation_required"
    for status in (ProposalMappingStatus.REJECTED, ProposalMappingStatus.COMPETING):
        with pytest.raises(ValidationError, match="non-complete"):
            ResultMappingReviewInput(
                **(exact.model_dump() | {"mapping_status": status}),
            )


def test_issue120_stale_discovery_and_mapping_tokens_do_not_commit(tmp_path) -> None:
    engine, prepared, proposal, discovery = _source_backed_proposal(tmp_path)
    trial_id = prepared.initialization.trials[0].trial_id
    stale_discovery = engine.submit_proposal_discovery_review(
        discovery.model_copy(update={"idempotency_key": "idempotency:stale-discovery"})
    )
    assert stale_discovery.condition.value == "stale"
    promoted = _promote_design(engine, prepared, proposal)
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None
    stale_mapping = engine.submit_result_mapping_review(
        SubmitResultMappingReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=work.work_token,
            proposal_token=proposal.proposal_token,
            idempotency_key="idempotency:stale-mapping-proposal",
            mappings=(_exact_mapping(promoted, trial_id),),
        )
    )
    assert stale_mapping.condition.value == "stale"
    assert engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item == work


def test_issue120_discovery_submission_and_first_proposal_are_contiguous(tmp_path) -> None:
    engine, prepared, _, _ = _source_backed_proposal(tmp_path)
    events = engine._bound_ledger(prepared.run_id).events()
    discovery_events = [
        event
        for event in events
        if event.operation
        in {
            "operation:submit-proposal-discovery-review",
            "operation:run-proposal-discovery-reviewed",
        }
    ]
    assert [event.operation for event in discovery_events] == [
        "operation:submit-proposal-discovery-review",
        "operation:run-proposal-discovery-reviewed",
    ]
    assert discovery_events[1].sequence == discovery_events[0].sequence + 1


def test_issue120_declared_result_survives_discovery_and_reaches_work(tmp_path) -> None:
    (tmp_path / "rob2.yaml").write_text(
        """
schema_version: 1
outcome_targets:
  - id: mortality
    label: Mortality
results:
  - result:
      result_id: result:declared-mortality
      trial_id: trial-a
      randomization_id: randomization:declared
      comparison:
        experimental_arm_id: arm:declared-treatment
        comparator_arm_id: arm:declared-control
      effect_of_interest: assignment
      outcome_construct: Mortality
      measurement_instrument: Vital status
      time_point: 90 days
      analysis_population: intention to treat
      analysis_model: risk ratio
      effect_measure: risk ratio
      source_locator: primary-report.pdf p. 1
    estimate:
      value: 0.8
    provenance_note: Declared Result.
""".strip(),
        encoding="utf-8",
    )
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "primary-report.pdf").write_bytes(b"Declared mortality Result source text.")
    engine = RunEngine(parser=_Parser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.initialization is not None
    assert prepared.initialization.result_specs[0].result.result_id == "result:declared-mortality"
    roles = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert roles is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=roles.work_token,
            idempotency_key="idempotency:declared-roles",
            selections=tuple(
                RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                for item in prepared.initialization.source_role_candidates
            ),
        )
    )
    discovery = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert discovery is not None
    source = prepared.initialization.trials[0].inventory.sources[0]
    reviewed_unit_ids = _navigate_discovery(
        engine, prepared.run_id, discovery, ("outcome-target:mortality",)
    )
    proposal = engine.submit_proposal_discovery_review(
        SubmitProposalDiscoveryReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=discovery.work_token,
            idempotency_key="idempotency:declared-discovery",
            coverage_receipt=ProposalDiscoveryCoverageReceipt(
                receipt_id="proposal-discovery-receipt:declared",
                trial_id=discovery.trial_id,
                source_id=source.source_id,
                parse_id=source.parse_records[0].parse_id,
                source_artifact_hash=source.artifact_hash,
                mode="target_guided",
                state="no_candidates",
                reviewed_by=_human(),
                reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
                discovery_policy_revision="discovery-policy:1",
                required_passes=("outcome-target:mortality",),
                query_passes=("outcome-target:mortality",),
                completed_passes=("outcome-target:mortality",),
                reviewed_unit_ids=reviewed_unit_ids,
                terminal_stopping_reason="Declared target pass completed.",
            ),
        )
    ).proposal
    assert proposal is not None
    confirmed = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=proposal.proposal_token,
            idempotency_key="idempotency:confirm-declared-result",
            confirmed_by=_human(),
        )
    )
    assert confirmed.run_definition is not None
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.result_id == "result:declared-mortality"
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=prepared.run_id, work_token=work.work_token)
    )
    assert context.context is not None and context.context.result_spec is not None
