"""Run-scoped ResultSpec reconciliation regressions (#148)."""

from pathlib import Path

import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    PrepareRunRequest,
    RunProposalSelection,
    SubmitRunProposalRequest,
)
from rob2_kit.application.run_engine import RunEngine
from tests.test_input_reconciliation import OPERATOR, _config, _result
from tests.test_run_proposal import StubParser, _first_proposal


def _confirm(engine: RunEngine, root: Path, run_id: str, *, key: str) -> None:
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root))
    if prepared.proposal is None:
        prepared = _first_proposal(engine, prepared)
    assert prepared.run_id == run_id
    assert prepared.proposal is not None
    selections = tuple(
        RunProposalSelection(
            trial_id=candidate.trial_id,
            outcome_target_id=candidate.outcome_target_id,
            result_id=candidate.result_id,
            result_candidate_id=candidate.candidate_id,
            accepted=True,
        )
        for candidate in prepared.proposal.result_candidates
        if candidate.status in ("needs_input", "resolved") and candidate.result_id is not None
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key=f"idempotency:{key}:proposal",
            selections=selections,
        )
    )
    assert submitted.proposal is not None
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key=f"idempotency:{key}:confirmation",
            confirmed_by=OPERATOR,
        )
    )


def test_second_run_keeps_its_own_declared_result_spec(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(_config(_result("result:trial-a", "trial:trial-a"))), encoding="utf-8"
    )
    engine = RunEngine(parser=StubParser())

    first = _first_proposal(
        engine, engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    )
    _confirm(engine, tmp_path, first.run_id, key="issue148:first")
    second = _first_proposal(
        engine,
        engine.prepare_run(
            PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
        ),
    )
    _confirm(engine, tmp_path, second.run_id, key="issue148:second")

    assert first.proposal is not None
    assert second.proposal is not None
    assert first.proposal.initialization.result_specs[0].revision_id != (
        second.proposal.initialization.result_specs[0].revision_id
    )


def test_awaiting_confirmation_refreshes_the_result_spec_chain(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "refresh"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    configuration = _config(_result("result:refresh", "trial:refresh"))
    path = tmp_path / "rob2.yaml"
    path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    engine = RunEngine(parser=StubParser())

    initial = _first_proposal(
        engine, engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    )
    assert initial.proposal is not None
    initial_spec = initial.proposal.initialization.result_specs[0]
    path.write_text("# reconciliation one\n" + yaml.safe_dump(configuration), encoding="utf-8")
    first_refresh = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    path.write_text("# reconciliation two\n" + yaml.safe_dump(configuration), encoding="utf-8")
    second_refresh = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    assert first_refresh.proposal is not None
    assert second_refresh.proposal is not None
    first_spec = first_refresh.proposal.initialization.result_specs[0]
    second_spec = second_refresh.proposal.initialization.result_specs[0]
    assert first_spec.supersedes is not None
    assert first_spec.supersedes.revision_id == initial_spec.revision_id
    assert second_spec.supersedes is not None
    assert second_spec.supersedes.revision_id == first_spec.revision_id
