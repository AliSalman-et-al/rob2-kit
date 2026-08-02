from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    PrepareRunRequest,
    SubmitRunProposalRequest,
    WorkflowCondition,
)
from rob2_kit.application.run_engine import RunEngine
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


def test_declared_registry_identity_is_bound_and_shown(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"NCT01234567 trial report")
    (trial / "trial.yaml").write_text("schema_version: 1\nnct: NCT01234567\n")
    registry = StubRegistry()

    prepared = RunEngine(parser=StubParser(), registry=registry).prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True)
    )

    assert registry.calls == ["NCT01234567"]
    assert prepared.proposal is not None
    candidate = prepared.proposal.registry_candidates[0]
    assert candidate.nct_id == "NCT01234567"
    assert candidate.explicit is True
    assert candidate.source == "trial.yaml"
    assert candidate.candidate_id.startswith("registry-candidate:")


def test_input_change_returns_structured_stale_proposal(tmp_path: Path) -> None:
    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    (tmp_path / "rob2.yaml").write_text("schema_version: 1\n")

    response = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
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
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
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
