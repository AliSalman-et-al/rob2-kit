from __future__ import annotations

import json
from pathlib import Path

import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    ReopenResultRequest,
    ReprioritizeResultsRequest,
    RunOperation,
    RunProposalSelection,
    RunStatusRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
    WithdrawResultRequest,
)
from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.revisions import Actor, ActorKind
from tests.test_run_proposal import StubParser, _first_proposal

OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:work-order-test",
    display_name="Work-order test operator",
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
        "provenance_note": "work-order fixture",
    }


def _confirmed_multi_result_run(root: Path) -> tuple[RunEngine, str, tuple[str, str]]:
    result_ids = ("result:trial-a-mortality", "result:trial-b-mortality")
    for directory in ("trial-a", "trial-b"):
        trial = root / "input" / directory
        trial.mkdir(parents=True)
        label = "CHAARTED" if directory == "trial-a" else "ENZAMET"
        filename = "chaarted.pdf" if directory == "trial-a" else "enzamet.pdf"
        (trial / filename).write_bytes(f"primary {label} trial report".encode())
    (root / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "acquisition": {"clinicaltrials_gov": False},
                "outcome_targets": [
                    {
                        "id": "mortality",
                        "label": "mortality",
                        "construct": "mortality",
                        "timepoint": "30 days",
                    }
                ],
                "results": [
                    _result(result_ids[0], "trial:trial-a"),
                    _result(result_ids[1], "trial:trial-b"),
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    # Neither Trial's sole Result candidate is auto-bound by cardinality
    # alone (#119); each pairing needs its own explicit accepted selection.
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:work-order-proposal",
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:mortality",
                    result_id=result_ids[0],
                    accepted=True,
                ),
                RunProposalSelection(
                    trial_id="trial:trial-b",
                    outcome_target_id="outcome-target:mortality",
                    result_id=result_ids[1],
                    accepted=True,
                ),
            ),
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:work-order-confirmation",
            confirmed_by=OPERATOR,
        )
    )
    return engine, prepared.run_id, result_ids


def test_pending_results_can_be_reprioritized_without_changing_confirmed_scope(
    tmp_path: Path,
) -> None:
    engine, run_id, result_ids = _confirmed_multi_result_run(tmp_path)

    response = engine.reprioritize_results(
        ReprioritizeResultsRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_ids=tuple(reversed(result_ids)),
            idempotency_key="idempotency:reprioritize",
            requested_by=OPERATOR,
        )
    )
    next_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item

    assert response.committed is True
    assert response.result_order == tuple(reversed(result_ids))
    assert next_work is not None
    assert next_work.operation is RunOperation.SUBMIT_DOMAIN_EVIDENCE
    assert next_work.result_id == result_ids[1]
    context = engine.get_work_context(
        GetWorkContextRequest(
            run_id=run_id,
            work_token=next_work.work_token,
            include_source_details=True,
        )
    ).context
    assert context is not None
    assert {source.relative_path for source in context.detailed_sources} == {"enzamet.pdf"}
    assert (
        tuple(
            item.result_id
            for item in engine.run_status(RunStatusRequest(run_id=run_id)).result_states
        )
        == result_ids
    )
    progress = engine.run_status(RunStatusRequest(run_id=run_id)).progress
    assert progress is not None
    assert progress.result_state_counts[ResultState.PENDING.value] == 2
    assert progress.warnings == ()
    assert progress.next_action is RunOperation.SUBMIT_DOMAIN_EVIDENCE


def test_withdrawn_pending_result_is_diagnostic_and_can_be_reopened(tmp_path: Path) -> None:
    engine, run_id, result_ids = _confirmed_multi_result_run(tmp_path)

    withdrawn = engine.withdraw_result(
        WithdrawResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[1],
            reason="Operator no longer needs this Result in the current pass.",
            idempotency_key="idempotency:withdraw",
            requested_by=OPERATOR,
        )
    )
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    diagnostic_root = tmp_path / status.progress.report_locations[0]
    diagnostic = json.loads((diagnostic_root / "diagnostic.json").read_text(encoding="utf-8"))
    reopened = engine.reopen_result(
        ReopenResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[1],
            idempotency_key="idempotency:reopen",
            requested_by=OPERATOR,
        )
    )

    assert withdrawn.committed is True
    assert (
        engine.withdraw_result(
            WithdrawResultRequest(
                contract_version="1.0.0",
                run_id=run_id,
                result_id=result_ids[1],
                reason="Operator no longer needs this Result in the current pass.",
                idempotency_key="idempotency:withdraw",
                requested_by=OPERATOR,
            )
        ).committed
        is False
    )
    assert next(item for item in status.result_states if item.result_id == result_ids[1]).state is (
        ResultState.DIAGNOSTIC_READY
    )
    assert diagnostic["preparation_outcome"] == "result_withdrawn"
    assert diagnostic["recovery"] == [
        "Reopen this withdrawn Result explicitly under the unchanged confirmed Run definition."
    ]
    assert reopened.committed is True
    assert reopened.result_state is ResultState.PENDING
    assert (
        next(
            item
            for item in engine.run_status(RunStatusRequest(run_id=run_id)).result_states
            if item.result_id == result_ids[1]
        ).state
        is ResultState.PENDING
    )


def test_result_controls_return_structured_refusals_for_nonhuman_and_wrong_state(
    tmp_path: Path,
) -> None:
    engine, run_id, result_ids = _confirmed_multi_result_run(tmp_path)
    agent = Actor(
        kind=ActorKind.AGENT,
        actor_id="actor:nonhuman",
        display_name="Nonhuman controller",
        software_name="test-agent",
        software_version="1",
    )

    nonhuman = engine.reprioritize_results(
        ReprioritizeResultsRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_ids=result_ids,
            idempotency_key="idempotency:nonhuman-priority",
            requested_by=agent,
        )
    )
    wrong_state = engine.reopen_result(
        ReopenResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[0],
            idempotency_key="idempotency:unwithdrawn-reopen",
            requested_by=OPERATOR,
        )
    )

    assert nonhuman.committed is False
    assert nonhuman.error is not None
    assert nonhuman.error.code == "human_actor_required"
    assert wrong_state.committed is False
    assert wrong_state.error is not None
    assert wrong_state.error.code == "invalid_result_control"


def test_reopening_a_withdrawn_result_reopens_a_completed_run(
    tmp_path: Path,
) -> None:
    engine, run_id, result_ids = _confirmed_multi_result_run(tmp_path)
    for index, result_id in enumerate(result_ids):
        engine.withdraw_result(
            WithdrawResultRequest(
                contract_version="1.0.0",
                run_id=run_id,
                result_id=result_id,
                reason="Operator stopped this Result before preparation.",
                idempotency_key=f"idempotency:withdraw-{index}",
                requested_by=OPERATOR,
            )
        )
    reopened = engine.reopen_result(
        ReopenResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[0],
            idempotency_key="idempotency:reopen-completed-run",
            requested_by=OPERATOR,
        )
    )

    assert engine.run_status(RunStatusRequest(run_id=run_id)).run_state is RunState.ASSESSING
    assert reopened.run_state is RunState.ASSESSING
    assert reopened.result_state is ResultState.PENDING


def test_result_control_key_reuse_from_a_retired_run_is_structured_for_every_control(
    tmp_path: Path,
) -> None:
    engine, run_id, result_ids = _confirmed_multi_result_run(tmp_path)
    engine.reprioritize_results(
        ReprioritizeResultsRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_ids=tuple(reversed(result_ids)),
            idempotency_key="idempotency:cross-run-priority",
            requested_by=OPERATOR,
        )
    )
    engine.withdraw_result(
        WithdrawResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[1],
            reason="Cross-Run idempotency fixture withdrawal.",
            idempotency_key="idempotency:cross-run-withdraw",
            requested_by=OPERATOR,
        )
    )
    engine.reopen_result(
        ReopenResultRequest(
            contract_version="1.0.0",
            run_id=run_id,
            result_id=result_ids[1],
            idempotency_key="idempotency:cross-run-reopen",
            requested_by=OPERATOR,
        )
    )
    replacement = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    replacement = _first_proposal(engine, replacement)
    assert replacement.proposal is not None
    review_work = engine.continue_run(ContinueRunRequest(run_id=replacement.run_id)).work_item
    assert review_work is not None
    assert review_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
    replacement_proposal = engine._latest_proposal(
        engine._bound_ledger(replacement.run_id), replacement.run_id
    )
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=replacement.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:replacement-source-review",
            selections=tuple(
                RunProposalSelection(
                    trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                )
                for candidate in replacement_proposal.initialization.source_role_candidates
            ),
        )
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=replacement.run_id,
            proposal_token=replacement.proposal.proposal_token,
            idempotency_key="idempotency:replacement-proposal",
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:mortality",
                    result_id=result_ids[0],
                    accepted=True,
                ),
                RunProposalSelection(
                    trial_id="trial:trial-b",
                    outcome_target_id="outcome-target:mortality",
                    result_id=result_ids[1],
                    accepted=True,
                ),
            ),
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=replacement.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:replacement-confirmation",
            confirmed_by=OPERATOR,
        )
    )

    responses = (
        engine.reprioritize_results(
            ReprioritizeResultsRequest(
                contract_version="1.0.0",
                run_id=replacement.run_id,
                result_ids=result_ids,
                idempotency_key="idempotency:cross-run-priority",
                requested_by=OPERATOR,
            )
        ),
        engine.withdraw_result(
            WithdrawResultRequest(
                contract_version="1.0.0",
                run_id=replacement.run_id,
                result_id=result_ids[1],
                reason="Changed Run must not replay the old withdrawal.",
                idempotency_key="idempotency:cross-run-withdraw",
                requested_by=OPERATOR,
            )
        ),
        engine.reopen_result(
            ReopenResultRequest(
                contract_version="1.0.0",
                run_id=replacement.run_id,
                result_id=result_ids[1],
                idempotency_key="idempotency:cross-run-reopen",
                requested_by=OPERATOR,
            )
        ),
    )

    for response in responses:
        assert response.committed is False
        assert response.error is not None
        assert response.error.code == "invalid_result_control"
