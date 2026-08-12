from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    SubmitProposalDiscoveryReviewRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
    WorkflowCondition,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.results import ProposalDiscoveryCoverageReceipt
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.ingestion.project import PageExtraction, ParserResult
from rob2_kit.registry import (
    RegistryAcquisition,
    RegistryAcquisitionStatus,
    RegistryResolution,
)

OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:operator",
    display_name="Run operator",
)


class StubParser:
    name = "stub"
    version = "1"

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        return ParserResult(
            pages=(
                PageExtraction(
                    page_number=1,
                    width=612,
                    height=792,
                    text=data.decode(),
                ),
            ),
            raw_output=data,
        )


class StubRegistry:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def acquire(self, *, declared_nct_id: str | None, source_texts: tuple[object, ...]):
        self.calls.append(declared_nct_id)
        return RegistryAcquisition(
            status=RegistryAcquisitionStatus.REVIEW_REQUIRED,
            resolution=RegistryResolution(
                nct_id=declared_nct_id or "NCT01234567",
                locator="trial.yaml" if declared_nct_id else "report.pdf#page=1",
                explicit=declared_nct_id is not None,
            ),
            retrieved_at=datetime.now(UTC),
            policy_release="policy:source-recovery-1.0.0",
        )


def _first_proposal(engine: RunEngine, prepared):
    """Drive immutable inventory through role review and terminal discovery."""
    assert prepared.initialization is not None
    while True:
        work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
        if work is None:
            return prepared.model_copy(
                update={
                    "proposal": engine._latest_proposal(
                        engine._bound_ledger(prepared.run_id), prepared.run_id
                    )
                }
            )
        if work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
            engine.submit_source_role_review(
                SubmitSourceRoleReviewRequest(
                    contract_version="1.0.0",
                    run_id=prepared.run_id,
                    work_token=work.work_token,
                    idempotency_key=f"idempotency:test-roles:{prepared.run_id}",
                    selections=tuple(
                        RunProposalSelection(trial_id=item.trial_id, source_id=item.source_id)
                        for item in prepared.initialization.source_role_candidates
                    ),
                )
            )
            continue
        if work.operation is RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW:
            source = next(
                source
                for trial in prepared.initialization.trials
                if trial.trial_id == work.trial_id
                for source in trial.inventory.sources
                if source.source_id == work.source_id
            )
            context = engine.get_work_context(
                GetWorkContextRequest(run_id=prepared.run_id, work_token=work.work_token)
            )
            assert context.context is not None
            policy = context.context.proposal_discovery_policy
            assert policy is not None
            reviewed_unit_ids: list[str] = []
            for pass_name in policy.required_passes:
                query = next(item for item in policy.pass_queries if item.pass_id == pass_name)
                navigated = engine.get_work_context(
                    GetWorkContextRequest(
                        run_id=prepared.run_id,
                        work_token=work.work_token,
                        proposal_discovery_query=query.canonical_query,
                        proposal_discovery_pass=pass_name,
                    )
                )
                assert navigated.context is not None
                if navigated.context.proposal_discovery_page is not None:
                    reviewed_unit_ids.extend(
                        item.canonical_unit_id
                        for item in navigated.context.proposal_discovery_page.candidates
                    )
            for offset in range(0, len(dict.fromkeys(reviewed_unit_ids)), 4):
                unit_ids = tuple(dict.fromkeys(reviewed_unit_ids))[offset : offset + 4]
                engine.get_work_context(
                    GetWorkContextRequest(
                        run_id=prepared.run_id,
                        work_token=work.work_token,
                        proposal_discovery_unit_ids=unit_ids,
                    )
                )
            response = engine.submit_proposal_discovery_review(
                SubmitProposalDiscoveryReviewRequest(
                    contract_version="1.0.0",
                    run_id=prepared.run_id,
                    work_token=work.work_token,
                    idempotency_key=(
                        f"idempotency:test-discovery:{prepared.run_id}:{source.source_id}"
                    ),
                    coverage_receipt=ProposalDiscoveryCoverageReceipt(
                        receipt_id=f"proposal-discovery-receipt:{source.source_id.removeprefix('source:')}",
                        trial_id=work.trial_id,
                        source_id=source.source_id,
                        parse_id=source.parse_records[0].parse_id,
                        source_artifact_hash=source.artifact_hash,
                        mode=(
                            "target_guided"
                            if prepared.initialization.manifest.outcome_target_specs
                            else "structure_first"
                        ),
                        state="no_candidates",
                        reviewed_by=OPERATOR,
                        reviewed_at=datetime.now(UTC),
                        discovery_policy_revision=policy.policy_revision,
                        required_passes=policy.required_passes,
                        query_passes=policy.required_passes,
                        completed_passes=policy.required_passes,
                        reviewed_unit_ids=tuple(dict.fromkeys(reviewed_unit_ids)),
                        terminal_stopping_reason="Required pass exhausted.",
                    ),
                )
            )
            if response.proposal is not None:
                return prepared.model_copy(update={"proposal": response.proposal})
            continue
        raise AssertionError(work.operation)


def test_declared_registry_identity_is_bound_and_shown(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"NCT01234567 trial report")
    (trial / "trial.yaml").write_text("schema_version: 1\nnct: NCT01234567\n")
    registry = StubRegistry()

    engine = RunEngine(parser=StubParser(), registry=registry)
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    assert registry.calls == ["NCT01234567"]
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    candidate = prepared.proposal.registry_candidates[0]
    assert candidate.nct_id == "NCT01234567"
    assert candidate.explicit is True
    assert candidate.source == "trial.yaml"
    assert candidate.candidate_id.startswith("registry-candidate:")


def test_input_change_returns_structured_stale_proposal(tmp_path: Path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    (tmp_path / "rob2.yaml").write_text("schema_version: 1\n")

    response = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:stale-proposal",
        )
    )

    assert response.condition is WorkflowCondition.STALE
    assert response.committed is False
    assert response.error is not None
    assert response.error.code == "stale_proposal"


def test_unsupported_method_is_a_structured_prepare_outcome(tmp_path: Path) -> None:
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "rob2": {"variant": "cluster-randomized"}})
    )

    prepared = RunEngine().prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    assert prepared.condition is WorkflowCondition.RUN_BLOCKED
    assert prepared.error is not None
    assert prepared.error.code == "unsupported_method"
    assert "cluster-randomized" in prepared.error.detail


def test_confirmation_is_idempotent_and_only_current_token_succeeds(tmp_path: Path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:proposal",
        )
    )
    request = ConfirmRunDefinitionRequest(
        contract_version="1.0.0",
        run_id=prepared.run_id,
        proposal_token=submitted.proposal.proposal_token,
        idempotency_key="idempotency:confirmation",
        confirmed_by=OPERATOR,
    )

    first = engine.confirm_run_definition(request)
    repeated = engine.confirm_run_definition(request)

    assert first.run_definition is not None
    assert repeated.committed is False
    assert repeated.run_definition == first.run_definition
    with pytest.raises(ValueError, match="already left confirmation"):
        engine.confirm_run_definition(
            request.model_copy(update={"idempotency_key": "idempotency:other"})
        )


def test_submit_run_proposal_after_confirmation_is_a_structured_run_blocked_condition(
    tmp_path: Path,
) -> None:
    """Issue #123: this gate used to raise a bare ValueError instead of
    returning through the normal tool result contract."""

    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:proposal",
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:confirmation",
            confirmed_by=OPERATOR,
        )
    )

    response = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:proposal-after-confirmation",
        )
    )

    assert response.committed is False
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    assert response.error.code == "invalid_configuration"
    assert "before confirmation" in response.error.detail


def test_submit_run_proposal_before_source_role_review_is_a_structured_run_blocked_condition(
    tmp_path: Path,
) -> None:
    """Issue #123: this gate used to raise a bare ValueError instead of
    returning through the normal tool result contract."""

    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"unreviewed report")

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is None
    work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert work is not None and work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW

    response = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token="proposal-token:pre-role-review",
            idempotency_key="idempotency:proposal-before-review",
        )
    )

    assert response.committed is False
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    assert response.error.code == "invalid_configuration"
    assert "first RunProposal" in response.error.detail


def test_submit_source_role_review_shape_violations_are_structured_run_blocked_conditions(
    tmp_path: Path,
) -> None:
    """Issue #123: these three gates used to raise bare ValueErrors instead of
    returning through the normal tool result contract."""

    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"first report")
    (trial / "protocol.pdf").write_bytes(b"second report")

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is None
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert review_work is not None
    issued_sources = [
        source.source_id
        for candidate_trial in prepared.initialization.trials
        for source in candidate_trial.inventory.sources
    ]
    assert len(issued_sources) == 2

    missing_source_id = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:review-missing-source-id",
            selections=(RunProposalSelection(trial_id="trial:trial-a"),),
        )
    )
    unissued_source_id = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:review-unissued-source-id",
            selections=(RunProposalSelection(trial_id="trial:trial-a", source_id="source:bogus"),),
        )
    )
    incomplete_review = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:review-incomplete",
            selections=(
                RunProposalSelection(trial_id="trial:trial-a", source_id=issued_sources[0]),
            ),
        )
    )

    for response, expected_detail_fragment in (
        (missing_source_id, "must set source_id"),
        (unissued_source_id, "unissued source identifier"),
        (incomplete_review, "must include every inventory-ready source"),
    ):
        assert response.committed is False
        assert response.condition is WorkflowCondition.RUN_BLOCKED
        assert response.error is not None
        assert response.error.code == "invalid_configuration"
        assert expected_detail_fragment in response.error.detail


def test_refresh_registry_candidates_reads_its_own_authorized_argument(tmp_path: Path) -> None:
    """Issue #123 / #129: _refresh_registry_candidates used to read the
    engine's stale, process-lifetime ``_authorized_root`` latch instead of a
    per-call argument. It must now be gated by its own ``authorized``
    parameter, independent of whatever the latch currently holds."""

    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    # No trial.yaml declaration: leaving the NCT id only in source text keeps
    # the resulting candidate's status "discovered" rather than "declared",
    # which is required for _refresh_registry_candidates to consider it
    # eligible for re-acquisition at all.
    (trial / "report.pdf").write_bytes(b"NCT01234567 trial report")
    registry = StubRegistry()

    engine = RunEngine(parser=StubParser(), registry=registry)
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    assert prepared.proposal.registry_candidates[0].status == "discovered"
    # The engine's process-lifetime latch is still set from the authorized
    # prepare_run call above (self._authorized_root == self._root); a caller
    # reading the stale latch instead of its own argument would wrongly
    # treat both calls below as authorized.
    assert engine._authorized_root == engine._root
    registry.calls.clear()
    candidate = prepared.proposal.registry_candidates[0]
    selections = (
        RunProposalSelection(
            trial_id="trial:trial-a",
            registry_candidate_id=candidate.candidate_id,
            accepted=True,
        ),
    )

    unauthorized_proposal = engine._refresh_registry_candidates(
        prepared.proposal, selections, authorized=False
    )

    assert registry.calls == []
    assert unauthorized_proposal == prepared.proposal

    engine._refresh_registry_candidates(prepared.proposal, selections, authorized=True)

    assert registry.calls == ["NCT01234567"]


def test_prepare_run_authorization_latch_resets_when_call_is_unauthorized(
    tmp_path: Path,
) -> None:
    """Issue #123 / #129: an authorized prepare_run call used to leave
    ``_authorized_root`` latched for the rest of the process, with no reset
    when a later call arrives unauthorized. continue_run's parameter-free
    reconciliation (_reconcile_current_run) reads this latch, so a stale
    latch would leave registry acquisition unlocked indefinitely."""

    engine = RunEngine()
    engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert engine._authorized_root == engine._root

    engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=False))

    assert engine._authorized_root is None
