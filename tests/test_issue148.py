"""Shared-ledger ResultSpec integrity regressions for issue #148."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    CorrectDomainAnswersRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.assessment import AssessmentRevision
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.ingestion.project import DocumentParser
from rob2_kit.storage import ArtifactStore, WorkflowLedger
from tests.test_input_reconciliation import (
    OPERATOR,
    _active_answer_ids,
    _complete_empty_receipts,
    _config,
    _finish_current_result,
    _low_answers,
    _result,
    _synthetic_visual_ref,
)
from tests.test_mcp_tracer import DOMAINS
from tests.test_run_proposal import StubParser


def _confirm(engine: RunEngine, root: Path, run_id: str, *, key: str) -> None:
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root))
    assert prepared.run_id == run_id
    assert prepared.proposal is not None
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    if work is not None and work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
        engine.submit_source_role_review(
            SubmitSourceRoleReviewRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:{key}:source-review",
                selections=tuple(
                    RunProposalSelection(
                        trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                    )
                    for candidate in prepared.proposal.source_role_candidates
                ),
            )
        )
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
            contract_version="1.0.0",
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


def test_second_run_freezes_its_own_declared_result_spec(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(_config(_result("result:trial-a", "trial:trial-a"))), encoding="utf-8"
    )
    engine = RunEngine(parser=cast(DocumentParser, StubParser()))

    first = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    _confirm(engine, tmp_path, first.run_id, key="issue148:first")
    first_evidence = engine.continue_run(ContinueRunRequest(run_id=first.run_id)).work_item
    assert first_evidence is not None
    assert first_evidence.result_id is not None
    assert first_evidence.domain_id is not None
    first_freeze = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=first.run_id,
            work_token=first_evidence.work_token,
            idempotency_key="idempotency:issue148:first:freeze",
            result_id=first_evidence.result_id,
            domain_id=first_evidence.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )
    second = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    _confirm(engine, tmp_path, second.run_id, key="issue148:second")
    second_evidence = engine.continue_run(ContinueRunRequest(run_id=second.run_id)).work_item
    assert second_evidence is not None
    assert second_evidence.result_id is not None
    assert second_evidence.domain_id is not None
    second_freeze = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=second.run_id,
            work_token=second_evidence.work_token,
            idempotency_key="idempotency:issue148:second:freeze",
            result_id=second_evidence.result_id,
            domain_id=second_evidence.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )

    assert first.proposal is not None
    assert second.proposal is not None
    assert (
        first.proposal.initialization.result_specs[0].revision_id
        != second.proposal.initialization.result_specs[0].revision_id
    )
    assert first_freeze.evidence_bundles
    assert second_freeze.evidence_bundles


def test_awaiting_confirmation_refreshes_chain_before_first_result_spec_freeze(
    tmp_path: Path,
) -> None:
    """Each public awaiting-confirmation refresh binds the prior nested ResultSpec."""
    trial = tmp_path / "input" / "refresh"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    configuration = _config(_result("result:refresh", "trial:refresh"))
    config_path = tmp_path / "rob2.yaml"
    config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    engine = RunEngine(parser=cast(DocumentParser, StubParser()))

    initial = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert initial.proposal is not None
    initial_spec = initial.proposal.initialization.result_specs[0]

    config_path.write_text(
        "# first awaiting-confirmation reconciliation\n" + yaml.safe_dump(configuration),
        encoding="utf-8",
    )
    first_refresh = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert first_refresh.run_id == initial.run_id
    assert first_refresh.proposal is not None
    first_spec = first_refresh.proposal.initialization.result_specs[0]
    assert first_spec.supersedes is not None
    assert first_spec.supersedes.revision_id == initial_spec.revision_id

    config_path.write_text(
        "# second awaiting-confirmation reconciliation\n" + yaml.safe_dump(configuration),
        encoding="utf-8",
    )
    second_refresh = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert second_refresh.run_id == initial.run_id
    assert second_refresh.proposal is not None
    final_spec = second_refresh.proposal.initialization.result_specs[0]
    assert final_spec.supersedes is not None
    assert final_spec.supersedes.revision_id == first_spec.revision_id

    _confirm(engine, tmp_path, initial.run_id, key="issue148:awaiting-refresh")
    evidence = engine.continue_run(ContinueRunRequest(run_id=initial.run_id)).work_item
    assert evidence is not None
    assert evidence.result_id is not None
    assert evidence.domain_id is not None
    frozen = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=initial.run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:issue148:awaiting-refresh:freeze",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )
    assert frozen.evidence_bundles

    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3", ArtifactStore(tmp_path / ".rob2" / "artifacts")
    )
    direct_specs = [
        (
            event,
            ResultSpecRevision.model_validate_json(
                ledger.artifacts.read(event.output_revision_hashes[0])
            ),
        )
        for event in ledger.events()
        if event.operation
        in {"operation:result-spec-historical-projected", "operation:result-spec-frozen"}
    ]
    assert [spec.revision_id for _, spec in direct_specs] == [
        initial_spec.revision_id,
        first_spec.revision_id,
        final_spec.revision_id,
    ]
    assert direct_specs[1][0].supersedes_revision_id == initial_spec.revision_id
    assert direct_specs[1][1].supersedes is not None
    assert direct_specs[1][1].supersedes.revision_id == initial_spec.revision_id
    assert direct_specs[2][0].supersedes_revision_id == first_spec.revision_id
    assert direct_specs[2][1].supersedes is not None
    assert direct_specs[2][1].supersedes.revision_id == first_spec.revision_id


def test_reconciliation_refreshes_after_freeze_extend_the_run_result_spec_chain(
    tmp_path: Path,
) -> None:
    """A later Run-scoped envelope supersedes the prior refresh, not frozen history."""
    trial = tmp_path / "input" / "post-freeze-refresh"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    configuration = _config(_result("result:post-freeze-refresh", "trial:post-freeze-refresh"))
    config_path = tmp_path / "rob2.yaml"
    config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    engine = RunEngine(parser=cast(DocumentParser, StubParser()))

    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    _confirm(engine, tmp_path, prepared.run_id, key="issue148:post-freeze-refresh")
    initial_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert initial_work is not None
    assert initial_work.result_id is not None
    assert initial_work.domain_id is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=prepared.run_id,
            work_token=initial_work.work_token,
            idempotency_key="idempotency:issue148:post-freeze-refresh:freeze",
            result_id=initial_work.result_id,
            domain_id=initial_work.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )
    frozen_spec = _latest_frozen_result_spec(tmp_path)

    config_path.write_text(
        "# first post-freeze reconciliation\n" + yaml.safe_dump(configuration),
        encoding="utf-8",
    )
    engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    first_refresh = _latest_enveloped_result_spec(tmp_path, prepared.run_id)
    assert first_refresh.supersedes is not None
    assert first_refresh.supersedes.revision_id == frozen_spec.revision_id

    config_path.write_text(
        "# second post-freeze reconciliation\n" + yaml.safe_dump(configuration),
        encoding="utf-8",
    )
    engine.continue_run(ContinueRunRequest(run_id=prepared.run_id))
    second_refresh = _latest_enveloped_result_spec(tmp_path, prepared.run_id)

    assert second_refresh.revision_id != first_refresh.revision_id
    assert second_refresh.supersedes is not None
    assert second_refresh.supersedes.revision_id == first_refresh.revision_id
    assert second_refresh.supersedes.revision_id != frozen_spec.revision_id

    refreshed_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert refreshed_work is not None
    assert refreshed_work.result_id == initial_work.result_id
    assert refreshed_work.domain_id == initial_work.domain_id
    refreshed_freeze = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=prepared.run_id,
            work_token=refreshed_work.work_token,
            idempotency_key="idempotency:issue148:post-freeze-refresh:freeze-c",
            result_id=refreshed_work.result_id,
            domain_id=refreshed_work.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )
    assert refreshed_freeze.evidence_bundles
    ledger = _issue148_ledger(tmp_path)
    assert any(
        revision.entity_id == second_refresh.entity_id
        and revision.revision_id == second_refresh.revision_id
        for revision in ledger.current_revisions()
    )


def _latest_frozen_result_spec(root: Path) -> ResultSpecRevision:
    ledger = _issue148_ledger(root)
    event = max(
        (event for event in ledger.events() if event.operation == "operation:result-spec-frozen"),
        key=lambda event: event.sequence,
    )
    return ResultSpecRevision.model_validate_json(
        ledger.artifacts.read(event.output_revision_hashes[0])
    )


def _latest_enveloped_result_spec(root: Path, run_id: str) -> ResultSpecRevision:
    ledger = _issue148_ledger(root)
    event = max(
        (
            event
            for event in ledger.events()
            if event.operation == "operation:result-spec-superseded"
            and json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))["run_id"]
            == run_id
        ),
        key=lambda event: event.sequence,
    )
    payload = json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))
    return ResultSpecRevision.model_validate(payload["result_spec"])


def _issue148_ledger(root: Path) -> WorkflowLedger:
    return WorkflowLedger(
        root / ".rob2" / "ledger.sqlite3", ArtifactStore(root / ".rob2" / "artifacts")
    )


def test_second_run_terminal_report_materializes_its_active_result_spec(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "terminal"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    first_config = _config(_result("result:terminal", "trial:terminal"))
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(first_config), encoding="utf-8")
    engine = RunEngine(parser=cast(DocumentParser, StubParser()))

    first = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    _confirm(engine, tmp_path, first.run_id, key="issue148:terminal:first")
    first_evidence = engine.continue_run(ContinueRunRequest(run_id=first.run_id)).work_item
    assert first_evidence is not None
    assert first_evidence.result_id is not None
    assert first_evidence.domain_id is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=first.run_id,
            work_token=first_evidence.work_token,
            idempotency_key="idempotency:issue148:terminal:first:freeze",
            result_id=first_evidence.result_id,
            domain_id=first_evidence.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )

    second_config: dict[str, Any] = _config(_result("result:terminal", "trial:terminal"))
    second_config["results"][0]["estimate"] = {"value": 0.91}
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(second_config), encoding="utf-8")
    second = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    _confirm(engine, tmp_path, second.run_id, key="issue148:terminal:second")
    _finish_current_result(engine, second.run_id, prefix="issue148-terminal-second")
    completed = engine.continue_run(ContinueRunRequest(run_id=second.run_id))

    assert completed.run_state is RunState.COMPLETE
    assert first.proposal is not None
    assert second.proposal is not None
    assert (
        first.proposal.initialization.result_specs[0].revision_id
        != second.proposal.initialization.result_specs[0].revision_id
    )
    reports = tuple((tmp_path / "output" / "report-bundle").rglob("assessment.json"))
    second_report = max(reports, key=lambda path: path.stat().st_mtime_ns)
    report = json.loads(second_report.read_text(encoding="utf-8"))
    assert report["result_details"]["estimate"]["value"] == "0.91"
    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3", ArtifactStore(tmp_path / ".rob2" / "artifacts")
    )
    assessment_event = max(
        (
            event
            for event in ledger.events()
            if event.operation == "operation:assessment-revision-frozen"
        ),
        key=lambda event: event.sequence,
    )
    assessment = AssessmentRevision.model_validate_json(
        ledger.artifacts.read(assessment_event.output_revision_hashes[0])
    )
    second_result_spec = second.proposal.initialization.result_specs[0]
    assert assessment.result_spec.revision_id == second_result_spec.revision_id
    assert any(
        dependency.role == "dependency:result-spec"
        and dependency.revision_id == second_result_spec.revision_id
        for dependency in assessment.dependencies
    )


def test_second_run_detects_a_superseded_result_spec_as_stale_evidence(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "stale"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    configuration = _config(_result("result:stale", "trial:stale"))
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(configuration), encoding="utf-8")
    engine = RunEngine(parser=cast(DocumentParser, StubParser()))

    first = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    _confirm(engine, tmp_path, first.run_id, key="issue148:stale:first")
    first_work = engine.continue_run(ContinueRunRequest(run_id=first.run_id)).work_item
    assert first_work is not None
    assert first_work.result_id is not None
    assert first_work.domain_id is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=first.run_id,
            work_token=first_work.work_token,
            idempotency_key="idempotency:issue148:stale:first-freeze",
            result_id=first_work.result_id,
            domain_id=first_work.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture deliberately has no search coverage.",),
        )
    )
    second = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    _confirm(engine, tmp_path, second.run_id, key="issue148:stale:second")
    evidence = engine.continue_run(ContinueRunRequest(run_id=second.run_id)).work_item
    assert evidence is not None
    assert evidence.result_id is not None
    assert evidence.domain_id is not None
    visual_ref = _synthetic_visual_ref(engine, second.run_id, evidence.result_id)
    setattr(engine, "_visual_citations", lambda *_args: ())
    question_ids = DOMAINS[evidence.domain_id]
    _complete_empty_receipts(
        engine,
        second.run_id,
        evidence,
        domain_id=evidence.domain_id,
        question_ids=question_ids,
    )
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=second.run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:issue148:stale:current-freeze",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
            items=(visual_ref,),
            evidence_by_question={question_id: (visual_ref,) for question_id in question_ids},
            candidate_dispositions=(
                {"item_id": visual_ref.entity_id, "disposition": "supporting"},
            ),
            coverage_state="complete",
        )
    )
    answer_work = engine.continue_run(ContinueRunRequest(run_id=second.run_id)).work_item
    assert answer_work is not None
    assert answer_work.result_id is not None
    assert answer_work.domain_id is not None
    answers = tuple(
        {
            "question_id": question_id,
            "answer": _low_answers()[question_id],
            "rationale": "Current ResultSpec evidence is valid.",
        }
        for question_id in _active_answer_ids(answer_work.domain_id)
    )
    answer_response = engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=second.run_id,
            work_token=answer_work.work_token,
            idempotency_key="idempotency:issue148:stale:current-answer",
            result_id=answer_work.result_id,
            domain_id=answer_work.domain_id,
            answers=answers,
        )
    )
    assert answer_response.condition.value == "accepted"
    assert answer_response.correction_token is not None

    # A harmless YAML comment changes the reconciled observation timestamp,
    # creating a new ResultSpec revision without changing the Result meaning.
    (tmp_path / "rob2.yaml").write_text(
        "# issue148 superseding observation\n" + yaml.safe_dump(configuration), encoding="utf-8"
    )
    engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    stale = engine.correct_domain_answers(
        CorrectDomainAnswersRequest.model_validate(
            {
                "contract_version": "1.0.0",
                "run_id": second.run_id,
                "work_token": answer_response.correction_token.model_dump(mode="json"),
                "idempotency_key": "idempotency:issue148:stale:correction",
                "result_id": answer_work.result_id,
                "domain_id": answer_work.domain_id,
                "answers": answers,
            }
        )
    )

    assert stale.condition.value == "run_blocked"
    assert {item.reason.value for item in stale.evidence_insufficiencies} == {
        "stale_evidence_dependency"
    }
