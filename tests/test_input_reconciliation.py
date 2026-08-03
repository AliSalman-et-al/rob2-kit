from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunProposalSelection,
    RunStatusRequest,
    SourceClassificationInput,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceClassificationRequest,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.results import Estimate, Result
from rob2_kit.domain.revisions import Actor, ActorKind
from tests.test_mcp_tracer import DOMAINS, _low_answers
from tests.test_run_proposal import StubParser

OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:reconciliation-test",
    display_name="Reconciliation test operator",
)


def _result(result_id: str, trial_id: str) -> dict[str, object]:
    return {
        "result": {
            "result_id": result_id,
            "trial_id": trial_id,
            "randomization_id": f"randomization:{trial_id}",
            "comparison": {
                "experimental_arm_id": "arm:experimental",
                "comparator_arm_id": "arm:control",
            },
            "effect_of_interest": "assignment",
            "outcome_construct": "mortality",
            "measurement_instrument": "all-cause",
            "time_point": "30 days",
            "analysis_population": "intention-to-treat",
            "analysis_model": "risk ratio",
            "effect_measure": "risk_ratio",
            "source_locator": "report:primary/table:1",
        },
        "estimate": {"value": 0.8},
        "provenance_note": "reconciliation fixture",
    }


def _config(*results: dict[str, object], with_target: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "acquisition": {"clinicaltrials_gov": False},
        "results": list(results),
    }
    if with_target:
        payload["outcome_targets"] = [
            {
                "id": "mortality",
                "label": "mortality",
                "construct": "mortality",
                "timepoint": "30 days",
            }
        ]
    return payload


def _prepare_confirm(root: Path, *, config: dict[str, object]) -> tuple[RunEngine, str]:
    (root / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-proposal",
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-confirmation",
            confirmed_by=OPERATOR,
        )
    )
    return engine, prepared.run_id


def _classify_current_sources(engine: RunEngine, run_id: str) -> None:
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=run_id, work_token=work.work_token)
    ).context
    assert context is not None
    response = engine.submit_source_classification(
        SubmitSourceClassificationRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:reconciliation-sources",
            classifications=tuple(
                SourceClassificationInput(source_id=source.source_id, roles=source.roles)
                for source in context.sources
            ),
        )
    )
    assert response.committed is True


def _finish_current_result(
    engine: RunEngine, run_id: str, *, prefix: str = "reconciliation"
) -> None:
    answers = _low_answers()
    for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
        evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert evidence is not None
        engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=evidence.work_token,
                idempotency_key=f"idempotency:{prefix}-evidence-{index}",
                result_id=evidence.result_id,
                domain_id=evidence.domain_id,
            )
        )
        answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert answer is not None
        engine.submit_domain_answers(
            SubmitDomainAnswersRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=answer.work_token,
                idempotency_key=f"idempotency:{prefix}-answers-{index}",
                result_id=answer.result_id,
                domain_id=answer.domain_id,
                answers=tuple(
                    {
                        "question_id": question_id,
                        "answer": answers[question_id],
                        "rationale": "Reconciliation fixture.",
                    }
                    for question_id in question_ids
                ),
            )
        )


def test_identical_domain_evidence_retry_returns_the_committed_result(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "retry"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:retry", "trial:retry")),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    event_count = len(engine._bound_ledger(run_id).events())
    request = SubmitDomainEvidenceRequest(
        contract_version="1.0.0",
        run_id=run_id,
        work_token=work.work_token,
        idempotency_key="idempotency:retry-domain-evidence",
        result_id=work.result_id,
        domain_id=work.domain_id,
    )

    first = engine.submit_domain_evidence(request)
    event_count_after_first = len(engine._bound_ledger(run_id).events())
    repeated = engine.submit_domain_evidence(request)
    changed = engine.submit_domain_evidence(
        request.model_copy(update={"coverage_limitations": ("changed",)})
    )

    assert first.condition.value == "accepted"
    assert first.committed is True
    assert repeated.condition.value == "accepted"
    assert repeated.committed is False
    assert repeated.operation_id == first.operation_id
    assert event_count_after_first > event_count
    assert len(engine._bound_ledger(run_id).events()) == event_count_after_first
    assert changed.condition.value == "stale"
    assert changed.committed is False
    assert changed.error is not None
    assert changed.error.code == "stale_work"


def test_execution_contract_change_records_attempt_and_invalidates_declared_results(
    tmp_path: Path, monkeypatch
) -> None:
    trial = tmp_path / "input" / "contract"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:contract", "trial:contract")),
    )
    _classify_current_sources(engine, run_id)
    baseline = engine._installed_execution_contract()
    initialization_only = baseline.model_copy(
        update={
            "identity": "sha256:" + ("b" * 64),
            "components": {
                **baseline.components,
                "initialization-skill": "sha256:" + ("c" * 64),
            },
        }
    )
    monkeypatch.setattr(engine, "_installed_execution_contract", lambda: initialization_only)

    preserved = engine.continue_run(ContinueRunRequest(run_id=run_id))

    assert preserved.work_item is not None
    assert not any(
        event.operation == "operation:result-invalidated"
        for event in engine._bound_ledger(run_id).events()
    )
    logic_changed = initialization_only.model_copy(
        update={
            "identity": "sha256:" + ("d" * 64),
            "components": {
                **initialization_only.components,
                "logic-pack": "sha256:" + ("e" * 64),
            },
        }
    )
    monkeypatch.setattr(engine, "_installed_execution_contract", lambda: logic_changed)

    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    events = engine._bound_ledger(run_id).events()

    assert resumed.work_item is not None
    assert resumed.work_item.result_id == "result:contract"
    attempts = tuple(
        event for event in events if event.operation == "operation:preparation-attempt-superseded"
    )
    prepared_event = next(event for event in events if event.operation == "operation:run-prepared")
    assert len(attempts) == 2
    assert attempts[0].supersedes_revision_id == prepared_event.revision_id
    assert attempts[1].supersedes_revision_id == attempts[0].revision_id
    assert [
        event.scope for event in events if event.operation == "operation:result-invalidated"
    ] == [
        "result:contract"
    ]


def test_resolved_outcome_candidate_survives_unrelated_source_change(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "support.pdf"
    support.parent.mkdir()
    support.write_bytes(b"support")
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(_config(with_target=True)), encoding="utf-8"
    )
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    candidate = prepared.proposal.result_candidates[0]
    ambiguity = next(
        item
        for item in prepared.proposal.ambiguities
        if item.scope == candidate.candidate_id
    )
    selection = RunProposalSelection(
        trial_id=candidate.trial_id,
        result_id=candidate.result_id,
        result_candidate_id=candidate.candidate_id,
        outcome_target_id=candidate.outcome_target_id,
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-candidate-proposal",
            selections=(selection,),
            ambiguities=(
                ambiguity.model_copy(
                    update={"resolved": True, "resolution": "mapped by operator"}
                ),
            ),
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-candidate-confirmation",
            confirmed_by=OPERATOR,
        )
    )
    _classify_current_sources(engine, prepared.run_id)
    support.write_bytes(b"changed support")

    continued = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.error is None
    assert continued.work_item is not None
    assert continued.work_item.result_id == candidate.result_id


def test_post_confirmation_result_resolution_keeps_source_dependency_on_change(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "support.pdf"
    support.parent.mkdir()
    support.write_bytes(b"support")
    engine, run_id = _prepare_confirm(tmp_path, config=_config())
    _classify_current_sources(engine, run_id)
    resolution_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resolution_work is not None
    assert resolution_work.result_id is not None
    resolved_result = Result.model_validate(
        _result(resolution_work.result_id, "trial:trial-a")["result"]
    ).model_copy(update={"source_locator": "supplements/support.pdf"})
    engine.submit_result_resolution(
        SubmitResultResolutionRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=resolution_work.work_token,
            idempotency_key="idempotency:reconciliation-resolution",
            result=resolved_result,
            estimate=Estimate(value=Decimal("0.8")),
            provenance_note="resolved in reconciliation fixture",
        )
    )
    support.write_bytes(b"changed support")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.result_id == resolution_work.result_id
    assert continued.work_item.operation.value == "submit_domain_evidence"
    assert any(
        event.operation == "operation:result-invalidated"
        and event.scope == resolution_work.result_id
        for event in engine._bound_ledger(run_id).events()
    )


def test_identical_scan_is_noop_and_content_preserving_move_keeps_source_id(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (trial / "supplements" / "support.pdf").write_bytes(b"support")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    support = next(
        source
        for source in proposal.initialization.trials[0].inventory.sources
        if source.relative_path != "report.pdf"
    )
    _classify_current_sources(engine, run_id)
    before = len(engine._bound_ledger(run_id).events())
    (trial / "other").mkdir()
    shutil.move(
        str(trial / "supplements" / "support.pdf"),
        str(trial / "other" / "moved.pdf"),
    )
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    assert continued.work_item.operation.value == "submit_domain_evidence"
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    moved = next(
        source
        for source in refreshed.initialization.trials[0].inventory.sources
        if source.relative_path == "other/moved.pdf"
    )
    assert moved.source_id == support.source_id
    after_move = len(engine._bound_ledger(run_id).events())
    assert after_move > before
    repeated = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert repeated.committed is False
    assert len(engine._bound_ledger(run_id).events()) == after_move


def test_content_preserving_trial_folder_move_keeps_trial_and_source_ids(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    before = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    before_trial = before.initialization.trials[0]
    before_source = before_trial.inventory.sources[0]

    shutil.move(str(trial), str(tmp_path / "input" / "trial-renamed"))
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    current_trial = refreshed.initialization.trials[0]
    current_source = current_trial.inventory.sources[0]

    assert current_trial.trial_id == before_trial.trial_id
    assert current_source.source_id == before_source.source_id
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    assert definition.trial_ids == (before_trial.trial_id,)


def test_trial_folder_move_with_changed_bytes_blocks_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    renamed = tmp_path / "input" / "trial-renamed"
    shutil.move(str(trial), str(renamed))
    (renamed / "report.pdf").write_bytes(b"changed primary")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_trial_path_replacement_conflict_blocks_hash_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"old primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    renamed = tmp_path / "input" / "trial-z"
    shutil.move(str(trial), str(renamed))
    replacement = tmp_path / "input" / "trial-a"
    replacement.mkdir()
    (replacement / "report.pdf").write_bytes(b"new primary")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"


def test_renamed_trial_with_same_content_copy_blocks_duplicate_identity_mapping(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    renamed = tmp_path / "input" / "trial-z"
    shutil.move(str(trial), str(renamed))
    copied = tmp_path / "input" / "trial-a-new"
    copied.mkdir()
    shutil.copy2(renamed / "report.pdf", copied / "report.pdf")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_source_path_replacement_conflict_blocks_hash_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "a.pdf"
    support.write_bytes(b"old support")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    moved = trial / "moved" / "a.pdf"
    moved.parent.mkdir()
    shutil.move(str(support), str(moved))
    support.write_bytes(b"new support")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"


def test_compatible_added_trial_gets_only_new_result_work(tmp_path: Path) -> None:
    first = tmp_path / "input" / "trial-a"
    first.mkdir(parents=True)
    (first / "report.pdf").write_bytes(b"primary a")
    config = _config(_result("result:a", "trial:trial-a"), with_target=True)
    engine, run_id = _prepare_confirm(tmp_path, config=config)
    added = tmp_path / "input" / "trial-b"
    added.mkdir()
    (added / "report.pdf").write_bytes(b"primary b")
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    _classify_current_sources(engine, run_id)
    resolution = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resolution is not None
    assert resolution.operation.value == "submit_result_resolution"
    assert resolution.trial_id == "trial:trial-b"
    assert resolution.result_id is not None


def test_added_failed_trial_gets_terminal_diagnostic_without_resolution_work(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    (tmp_path / "input" / "trial-b").mkdir()

    first = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert first.work_item is not None
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:run-register-diagnostic-result" for event in events)
    assert any(event.operation == "operation:result-diagnostic-ready" for event in events)
    _classify_current_sources(engine, run_id)
    next_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert next_work is not None
    assert next_work.result_id == "result:a"


def test_recovering_failed_trial_with_primary_addition_reopens_assessment(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    (trial / "report.pdf").write_bytes(b"primary")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.operation.value == "submit_source_classification"
    assert not any(
        event.operation == "operation:run-blocked"
        for event in engine._bound_ledger(run_id).events()
    )


def test_material_reconciliation_blocks_diagnostic_only_run_without_integrity_failure(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    (trial / "first.pdf").write_bytes(b"first")
    (trial / "second.pdf").write_bytes(b"second")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert not any(
        event.operation == "operation:run-completed"
        and event.sequence > max(
            item.sequence
            for item in engine._bound_ledger(run_id).events()
            if item.operation == "operation:run-blocked"
        )
        for event in engine._bound_ledger(run_id).events()
    )


def test_changed_support_only_invalidates_results_that_cite_it(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "supplement.pdf"
    support.write_bytes(b"support")
    first = _result("result:a", "trial:trial-a")
    first["result"]["source_locator"] = "report.pdf p. 1"
    second = _result("result:b", "trial:trial-a")
    second["result"]["source_locator"] = "supplements/supplement.pdf p. 1"
    engine, run_id = _prepare_confirm(tmp_path, config=_config(first, second))
    _classify_current_sources(engine, run_id)
    support.write_bytes(b"changed support")

    engine.continue_run(ContinueRunRequest(run_id=run_id))
    invalidated = {
        event.scope
        for event in engine._bound_ledger(run_id).events()
        if event.operation == "operation:result-invalidated"
    }
    assert invalidated == {"result:b"}


def test_result_declaration_edits_block_without_rewriting_confirmed_definition(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    original = _config(_result("result:a", "trial:trial-a"))
    engine, run_id = _prepare_confirm(tmp_path, config=original)
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None

    changed = _config(_result("result:a", "trial:trial-a"))
    changed["results"][0]["estimate"]["value"] = 0.9
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(changed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition

    added = _config(
        _result("result:a", "trial:trial-a"),
        _result("result:b", "trial:trial-a"),
    )
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(added), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert "added to an existing confirmed Trial" in blocked.error.detail

    removed = _config()
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(removed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert "was removed" in blocked.error.detail

    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(original), encoding="utf-8")
    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert resumed.run_state is RunState.ASSESSING


def test_material_semantic_drift_blocks_then_unblocks_after_correction(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    config = _config(_result("result:a", "trial:trial-a"))
    engine, run_id = _prepare_confirm(tmp_path, config=config)
    changed = _config(_result("result:a", "trial:trial-a"))
    changed["rob2"] = {"effect_of_interest": "hypothetical"}
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(changed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert resumed.run_state is RunState.ASSESSING


def test_deleted_trial_is_retired_from_active_status_but_history_remains(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    shutil.rmtree(trial)
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    assert status.result_states == ()
    assert any(
        event.operation == "operation:run-register-result"
        and event.scope == "result:a"
        for event in engine._bound_ledger(run_id).events()
    )


def test_retired_run_does_not_reconcile_later_input_changes(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    replacement = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    assert replacement.run_id != run_id
    before = len(engine._bound_ledger(run_id).events())
    report.write_bytes(b"changed primary")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.RETIRED
    assert len(engine._bound_ledger(run_id).events()) == before


def test_unreadable_input_snapshot_is_a_durable_material_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )

    def fail_snapshot(_: Path) -> str:
        raise ValueError("project input symlinks are not permitted")

    monkeypatch.setattr(RunEngine, "_input_snapshot_hash", staticmethod(fail_snapshot))
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert any(
        event.operation == "operation:run-blocked"
        for event in engine._bound_ledger(run_id).events()
    )


def test_ambiguous_source_move_blocks_without_rewriting_confirmed_definition(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (trial / "supplements" / "first.pdf").write_bytes(b"duplicate")
    (trial / "supplements" / "second.pdf").write_bytes(b"duplicate")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    (trial / "moved").mkdir()
    shutil.move(str(trial / "supplements" / "first.pdf"), str(trial / "moved" / "one.pdf"))
    shutil.move(str(trial / "supplements" / "second.pdf"), str(trial / "moved" / "two.pdf"))
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    current = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert current == definition


def test_source_move_with_same_content_copy_blocks_duplicate_identity_mapping(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    source = trial / "supplements" / "z.pdf"
    source.write_bytes(b"same content")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    (trial / "moved").mkdir()
    shutil.move(str(source), str(trial / "moved" / "z.pdf"))
    copied = trial / "aaa" / "copy.pdf"
    copied.parent.mkdir()
    copied.write_bytes(b"same content")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_added_same_content_source_does_not_steal_existing_path_identity(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    source = trial / "supplements" / "z.pdf"
    source.write_bytes(b"same content")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    before = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    before_source = next(
        item
        for item in before.initialization.trials[0].inventory.sources
        if item.relative_path == "supplements/z.pdf"
    )
    copied = trial / "aaa" / "copy.pdf"
    copied.parent.mkdir()
    copied.write_bytes(b"same content")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    current_sources = {
        item.relative_path: item
        for item in refreshed.initialization.trials[0].inventory.sources
    }
    assert current_sources["supplements/z.pdf"].source_id == before_source.source_id
    assert current_sources["aaa/copy.pdf"].source_id != before_source.source_id


def test_completed_changed_source_reopens_only_affected_result_work(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    _classify_current_sources(engine, run_id)
    _finish_current_result(engine, run_id)
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    ledger = engine._bound_ledger(run_id)
    report_events_before = tuple(
        event for event in ledger.events() if event.operation == "operation:result-report-ready"
    )
    report.write_bytes(b"changed primary")
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.result_id == "result:a"
    assert (
        engine.run_status(RunStatusRequest(run_id=run_id)).result_states[0].state.value
        == "pending"
    )
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:run-reopened" for event in events)
    assert any(event.operation == "operation:result-invalidated" for event in events)
    assert len(
        [event for event in events if event.operation == "operation:result-report-ready"]
    ) == len(report_events_before)
    _finish_current_result(engine, run_id, prefix="reconciliation-rerun")
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    assert len(
        [event for event in engine._bound_ledger(run_id).events()
         if event.operation == "operation:run-completed"]
    ) == 2


def test_changed_source_invalidates_partial_pending_checkpoints(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:partial-evidence",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
        )
    )
    report.write_bytes(b"changed primary")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    assert continued.work_item.result_id == "result:a"
    events = engine._bound_ledger(run_id).events()
    assert any(
        event.operation == "operation:result-invalidated" and event.scope == "result:a"
        for event in events
    )


def test_completed_deleted_required_source_becomes_terminal_diagnostic(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    _classify_current_sources(engine, run_id)
    _finish_current_result(engine, run_id)
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    report_events_before = tuple(
        event
        for event in engine._bound_ledger(run_id).events()
        if event.operation == "operation:result-report-ready"
    )
    report.unlink()
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.COMPLETE
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    assert status.result_states[0].state.value == "diagnostic_ready"
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:result-invalidated" for event in events)
    assert any(event.operation == "operation:result-diagnostic-ready" for event in events)
    assert len(
        [event for event in events if event.operation == "operation:result-report-ready"]
    ) == len(report_events_before)
