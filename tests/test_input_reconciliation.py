from __future__ import annotations

import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    CorrectDomainAnswersRequest,
    EvidencePassageInput,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    RunStatusRequest,
    SearchEvidenceRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
    WorkToken,
)
from rob2_kit.application.lifecycle import ResultState, RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import EvidenceClaim, VisualTranscription
from rob2_kit.domain.results import Estimate, Result
from rob2_kit.domain.revisions import Actor, ActorKind, Dependency, RecordReference
from rob2_kit.evidence.search import EvidenceScope, EvidenceSearchIndex, SearchQuery
from rob2_kit.evidence.workflow import (
    SearchCoverageReceipt,
    SearchPassKind,
    SearchResultDisposition,
    SearchResultDispositionKind,
    SourceSearchCoverage,
    SourceSearchState,
)
from rob2_kit.ingestion.project import PageExtraction, PageTextItem, ParserResult
from tests.test_mcp_tracer import DOMAINS, _active_answer_ids, _low_answers
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


def _config(*results: dict[str, object], with_target: bool | None = None) -> dict[str, object]:
    # Declared Result fixtures represent an explicit requested Outcome target
    # unless a test intentionally builds an empty project.  This keeps legacy
    # reconciliation journeys aligned with the strict Trial × Outcome
    # confirmation contract instead of relying on implicit result-ID fallback.
    if with_target is None:
        with_target = bool(results)
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


class StructuredPassageParser:
    name = "structured-passage-fixture"
    version = "1"

    def parse(self, data: bytes, *, ocr_enabled: bool, target_pages=None) -> ParserResult:
        text = data.decode()
        return ParserResult(
            pages=(
                PageExtraction(
                    page_number=1,
                    width=612,
                    height=792,
                    text=text,
                    markdown=text,
                    text_items=(
                        PageTextItem(
                            text=text,
                            x=10,
                            y=20,
                            width=200,
                            height=12,
                            unit_kind="paragraph",
                            document_zone="main",
                            discourse_scope="active",
                            domain_id="domain:randomization",
                            question_ids=(DOMAINS["domain:randomization"][0],),
                        ),
                    ),
                ),
            ),
            raw_output=data,
        )


def _prepare_confirm(
    root: Path,
    *,
    config: dict[str, object],
    parser: object | None = None,
) -> tuple[RunEngine, str]:
    config_payload = dict(config)
    if "outcome_targets" not in config_payload:
        config_payload["outcome_targets"] = [
            {
                "id": "mortality",
                "label": "mortality",
                "construct": "mortality",
                "timepoint": "30 days",
            }
        ]
    (root / "rob2.yaml").write_text(yaml.safe_dump(config_payload), encoding="utf-8")
    engine = RunEngine(parser=parser or StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    assert prepared.proposal is not None
    # A Result candidate is never auto-bound by cardinality alone (#119): even
    # a sole "resolved" candidate needs an explicit accepted selection, so
    # this helper always emits one rather than relying on any implicit
    # single-candidate fallback.
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
    # Source-role review resolves before the proposal (#119): every
    # Source-role candidate needs an explicit accept before submit_run_proposal
    # will trust any role.
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    if review_work is not None and review_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
        engine.submit_source_role_review(
            SubmitSourceRoleReviewRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                work_token=review_work.work_token,
                idempotency_key="idempotency:reconciliation-source-review",
                selections=tuple(
                    RunProposalSelection(
                        trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                    )
                    for candidate in prepared.proposal.source_role_candidates
                ),
            )
        )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-proposal",
            selections=selections,
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
    """Complete a pending Source-role review work item, if one remains.

    Most callers' sources are already reviewed pre-confirmation inside
    ``_prepare_confirm`` (#119), so this is a no-op then. A source that
    only appears (or changes) after confirmation, via reconciliation,
    still surfaces its own post-confirmation review work item here.
    """

    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    if work is None or work.operation is not RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
        return
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=run_id, work_token=work.work_token)
    ).context
    assert context is not None
    assert context.detailed_sources == ()
    assert all(source.page_count >= 0 for source in context.sources)
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    context_source_ids = {source.source_id for source in context.sources}
    response = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:reconciliation-sources",
            selections=tuple(
                RunProposalSelection(
                    trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                )
                for candidate in proposal.initialization.source_role_candidates
                if candidate.source_id in context_source_ids
            ),
        )
    )
    assert response.committed is True


def _complete_passage_receipts(
    engine: RunEngine,
    run_id: str,
    work: object,
    *,
    unit_id: str,
) -> tuple[SearchCoverageReceipt, ...]:
    """Build a real three-pass receipt for the structured passage fixture."""
    token = getattr(work, "work_token")
    result_id = getattr(work, "result_id")
    result_spec = engine._result_spec_for(engine._bound_ledger(run_id), run_id, result_id)
    assert result_spec is not None
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    trial = next(item for item in proposal.initialization.trials if item.trial_id == token.trial_id)
    inventory = trial.inventory
    assert inventory is not None
    result_ref = RecordReference(
        entity_id=result_spec.entity_id,
        revision_id=result_spec.revision_id,
        content_hash=canonical_hash(result_spec),
    )
    inventory_suffix = engine._digest(
        f"{run_id}|{result_id}|{result_ref.content_hash}|source-inventory"
    )
    receipts: list[SearchCoverageReceipt] = []
    primary_question = DOMAINS["domain:randomization"][0]
    for question_id in DOMAINS["domain:randomization"]:
        seed_family = "seed:" + question_id.removeprefix("sq:").replace(":", "-")
        queries = (
            (SearchQuery(terms=("primary",)), SearchPassKind.GUIDANCE_SEED, seed_family),
            (SearchQuery(terms=("followup",)), SearchPassKind.TRIAL_FOLLOW_UP, None),
            (SearchQuery(terms=("contradiction",)), SearchPassKind.CONTRADICTION, None),
        )
        responses = tuple(
            engine.search_evidence(
                SearchEvidenceRequest(
                    run_id=run_id,
                    work_token=token,
                    result_id=result_id,
                    sq_id=question_id,
                    query=query,
                    pass_kind=pass_kind,
                    seed_family=seed_family,
                )
            )
            for query, pass_kind, seed_family in queries
        )
        assert all(response.executed_query is not None for response in responses)
        retained = question_id == primary_question
        receipt = SearchCoverageReceipt(
            receipt_id=f"coverage:passage-{question_id.removeprefix('sq:').replace(':', '-')}",
            sq_id=question_id,
            snapshot_hash=responses[0].page.snapshot_hash,
            policy_id=responses[0].page.policy_id,
            policy_hash=responses[0].page.policy_hash,
            result_spec=result_ref,
            source_inventory=RecordReference(
                entity_id=f"source-inventory:{result_id.removeprefix('result:')}",
                revision_id=f"revision:source-inventory-{inventory_suffix}",
                content_hash=canonical_hash(inventory),
            ),
            parse_record_hashes=tuple(
                sorted(
                    parse.output_hash
                    for source in inventory.sources
                    for parse in source.parse_records
                )
            ),
            guidance_release_id="guidance:rob2-2019.1",
            required_seed_families=(seed_family,),
            completed_seed_families=(seed_family,),
            completed_passes=tuple(pass_kind for _query, pass_kind, _seed in queries),
            executed_queries=tuple(response.executed_query for response in responses),
            returned_unit_ids=(unit_id,) if retained else (),
            result_dispositions=(
                (
                    SearchResultDisposition(
                        unit_id=unit_id,
                        kind=SearchResultDispositionKind.RETAINED_CANDIDATE,
                        candidate_id=unit_id,
                    ),
                )
                if retained
                else ()
            ),
            sources=tuple(
                SourceSearchCoverage(
                    source_id=source.source_id,
                    state=SourceSearchState.SEARCHED,
                    sufficiently_readable=True,
                    artifact_hash=source.artifact_hash,
                )
                for source in inventory.sources
            ),
            inventory_source_ids=tuple(source.source_id for source in inventory.sources),
            traversal_complete=True,
            interrupted=False,
        )
        proof = receipt.model_dump(mode="json")
        proof["recorder_proof"] = None
        receipts.append(
            SearchCoverageReceipt.model_validate(
                receipt.model_dump(mode="json") | {"recorder_proof": canonical_hash(proof)}
            )
        )
    return tuple(receipts)


def _complete_empty_receipts(
    engine: RunEngine,
    run_id: str,
    work: object,
    *,
    domain_id: str,
    question_ids: tuple[str, ...],
) -> tuple[SearchCoverageReceipt, ...]:
    """Build complete, zero-hit receipts for synthetic visual fixtures."""

    token = getattr(work, "work_token")
    result_id = getattr(work, "result_id")
    ledger = engine._bound_ledger(run_id)
    result_spec = engine._result_spec_for(ledger, run_id, result_id)
    assert result_spec is not None
    proposal = engine._latest_proposal(ledger, run_id)
    trial = next(item for item in proposal.initialization.trials if item.trial_id == token.trial_id)
    inventory = trial.inventory
    assert inventory is not None
    result_ref = RecordReference(
        entity_id=result_spec.entity_id,
        revision_id=result_spec.revision_id,
        content_hash=canonical_hash(result_spec),
    )
    inventory_suffix = engine._digest(
        f"{run_id}|{result_id}|{result_ref.content_hash}|source-inventory"
    )
    receipts: list[SearchCoverageReceipt] = []
    for question_id in question_ids:
        slug = question_id.removeprefix("sq:").replace(":", "-")
        queries = (
            (SearchQuery(terms=(f"absent-{slug}",)), SearchPassKind.GUIDANCE_SEED, f"seed:{slug}"),
            (SearchQuery(terms=(f"followup-{slug}",)), SearchPassKind.TRIAL_FOLLOW_UP, None),
            (SearchQuery(terms=(f"contradiction-{slug}",)), SearchPassKind.CONTRADICTION, None),
        )
        responses = tuple(
            engine.search_evidence(
                SearchEvidenceRequest(
                    run_id=run_id,
                    work_token=token,
                    result_id=result_id,
                    sq_id=question_id,
                    query=query,
                    pass_kind=pass_kind,
                    seed_family=seed_family,
                )
            )
            for query, pass_kind, seed_family in queries
        )
        receipt = SearchCoverageReceipt(
            receipt_id=f"coverage:synthetic-{slug}",
            sq_id=question_id,
            snapshot_hash=responses[0].page.snapshot_hash,
            policy_id=responses[0].page.policy_id,
            policy_hash=responses[0].page.policy_hash,
            result_spec=result_ref,
            source_inventory=RecordReference(
                entity_id=f"source-inventory:{result_id.removeprefix('result:')}",
                revision_id=f"revision:source-inventory-{inventory_suffix}",
                content_hash=canonical_hash(inventory),
            ),
            parse_record_hashes=tuple(
                sorted(
                    parse.output_hash
                    for source in inventory.sources
                    for parse in source.parse_records
                )
            ),
            guidance_release_id="guidance:rob2-2019.1",
            required_seed_families=(f"seed:{slug}",),
            completed_seed_families=(f"seed:{slug}",),
            completed_passes=tuple(pass_kind for _query, pass_kind, _seed in queries),
            executed_queries=tuple(response.executed_query for response in responses),
            returned_unit_ids=(),
            result_dispositions=(),
            sources=tuple(
                SourceSearchCoverage(
                    source_id=source.source_id,
                    state=SourceSearchState.SEARCHED,
                    sufficiently_readable=True,
                    artifact_hash=source.artifact_hash,
                )
                for source in inventory.sources
            ),
            inventory_source_ids=tuple(source.source_id for source in inventory.sources),
            traversal_complete=True,
            interrupted=False,
        )
        proof = receipt.model_dump(mode="json")
        proof["recorder_proof"] = None
        receipts.append(
            SearchCoverageReceipt.model_validate(
                receipt.model_dump(mode="json") | {"recorder_proof": canonical_hash(proof)}
            )
        )
    return tuple(receipts)


def _synthetic_visual_ref(engine: RunEngine, run_id: str, result_id: str) -> RecordReference:
    """Persist one scoped visual transcription for legacy synthetic journeys."""

    ledger = engine._bound_ledger(run_id)
    proposal = engine._latest_proposal(ledger, run_id)
    result_spec = engine._result_spec_for(ledger, run_id, result_id)
    assert result_spec is not None
    trial = next(
        item
        for item in proposal.initialization.trials
        if item.trial_id == result_spec.result.trial_id
    )
    inventory = trial.inventory
    assert inventory is not None
    source = inventory.sources[0]
    source_suffix = engine._digest(f"{run_id}|{source.source_id}|{source.artifact_hash}")
    source_ref = engine._commit_frozen_artifact(
        ledger,
        scope=result_id,
        operation="operation:test-visual-source-frozen",
        operation_key=f"idempotency:test-visual-source:{source_suffix}",
        # Scope validation binds visual transcriptions to the issued source ID.
        entity_id=source.source_id,
        revision_id=f"revision:evidence-source-{source_suffix}",
        artifact=source,
        actor=OPERATOR,
    )
    suffix = engine._digest(
        f"{run_id}|{result_id}|{source.source_id}|{source.artifact_hash}|synthetic-visual"
    )
    transcription = VisualTranscription(
        entity_id=f"visual-transcription:{suffix}",
        revision_id=f"revision:visual-transcription-{suffix}",
        dependencies=(Dependency(**source_ref.model_dump(), role="dependency:source"),),
        actor=OPERATOR,
        observed_at=engine._now(),
        source=source_ref,
        page=1,
        region=(1.0, 1.0, 20.0, 20.0),
        render_mode="crop",
        dpi=144,
        transcription="Synthetic visual evidence supports the scoped answer.",
    )
    return engine._commit_frozen_artifact(
        ledger,
        scope=result_id,
        operation="operation:test-visual-transcription-frozen",
        operation_key=f"idempotency:test-visual-transcription:{suffix}",
        entity_id=transcription.entity_id,
        revision_id=transcription.revision_id,
        artifact=transcription,
        actor=OPERATOR,
        dependencies=transcription.dependencies,
    )


def _finish_current_result(
    engine: RunEngine,
    run_id: str,
    *,
    prefix: str = "reconciliation",
    answers: dict[str, str] | None = None,
    assessor_inputs: dict[str, bool] | None = None,
    assessor_inputs_by_domain: dict[str, dict[str, bool]] | None = None,
) -> dict[str, SubmitDomainAnswersRequest]:
    answer_values = answers or _low_answers()
    submissions: dict[str, SubmitDomainAnswersRequest] = {}
    # The legacy reconciliation journeys intentionally exercise answer and
    # report lifecycle behaviour rather than retrieval.  Freeze one scoped
    # visual transcription plus complete search accounting at this public
    # evidence boundary so the strict terminal checkpoint has a qualifying
    # basis for every active question.
    visual_ref: RecordReference | None = None
    for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
        evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert evidence is not None
        if visual_ref is None:
            visual_ref = _synthetic_visual_ref(engine, run_id, evidence.result_id)
            # StubParser has no screenshot implementation.  These fixtures
            # assert lifecycle/report state, so keep the visual-only evidence
            # citation textual and avoid coupling them to rendering support.
            engine._visual_citations = lambda *_args: ()
        actual_question_ids = next(
            domain.question_ids for domain in engine._logic_pack().domains if domain.id == domain_id
        )
        engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=evidence.work_token,
                idempotency_key=f"idempotency:{prefix}-evidence-{index}",
                result_id=evidence.result_id,
                domain_id=evidence.domain_id,
                items=(visual_ref,),
                evidence_by_question={
                    question_id: (visual_ref,) for question_id in actual_question_ids
                },
                candidate_dispositions=(
                    {
                        "item_id": visual_ref.entity_id,
                        "disposition": "supporting",
                    },
                ),
                coverage_receipts=_complete_empty_receipts(
                    engine,
                    run_id,
                    evidence,
                    domain_id=domain_id,
                    question_ids=actual_question_ids,
                ),
                coverage_state="complete",
            )
        )
        answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert answer is not None
        submission = SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=answer.work_token,
            idempotency_key=f"idempotency:{prefix}-answers-{index}",
            result_id=answer.result_id,
            domain_id=answer.domain_id,
            answers=tuple(
                {
                    "question_id": question_id,
                    "answer": answer_values[question_id],
                    "rationale": "Reconciliation fixture.",
                }
                for question_id in _active_answer_ids(answer.domain_id)
            ),
            assessor_inputs=(assessor_inputs_by_domain or {}).get(
                answer.domain_id, assessor_inputs or {}
            ),
        )
        engine.submit_domain_answers(submission)
        submissions[answer.domain_id] = submission
    return submissions


def _current_correction_token(
    engine: RunEngine, run_id: str, result_id: str, domain_id: str
) -> WorkToken:
    ledger = engine._bound_ledger(run_id)
    event = next(
        event
        for event in reversed(engine._events_for_run(ledger, run_id))
        if event.operation
        in {"operation:submit-domain-answers", "operation:correct-domain-answers"}
        and event.scope == result_id
        and json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))["domain_id"]
        == domain_id
    )
    return WorkToken.model_validate(
        json.loads(ledger.artifacts.read(event.output_revision_hashes[0]))["correction_token"]
    )


def test_report_render_failure_preserves_assessment_ready_and_retries_only_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public continuation seam retries report publication without redoing science."""

    trial = tmp_path / "input" / "report-retry"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:report-retry", "trial:report-retry")),
    )
    _classify_current_sources(engine, run_id)
    from rob2_kit.application.run_engine import ReportProjector

    original = ReportProjector.bundle_files
    calls = 0

    def fail_once(projector: ReportProjector) -> dict[str, bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("render backend interrupted")
        return original(projector)

    monkeypatch.setattr(ReportProjector, "bundle_files", fail_once)
    with pytest.raises(OSError, match="render backend interrupted"):
        _finish_current_result(engine, run_id, prefix="report-retry")

    ledger = engine._bound_ledger(run_id)
    assessment_events = [
        event
        for event in ledger.events()
        if event.operation == "operation:assessment-revision-frozen"
    ]
    assert len(assessment_events) == 1
    assert engine.run_status(RunStatusRequest(run_id=run_id)).result_states[0].state is (
        ResultState.ASSESSMENT_READY
    )

    monkeypatch.setattr(ReportProjector, "bundle_files", original)
    monkeypatch.setattr(
        engine,
        "_materialize_terminal",
        lambda *_args: pytest.fail("resume must not re-evaluate a frozen Assessment"),
    )
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))

    assert continued.run_state is RunState.COMPLETE
    assert len(
        [
            event
            for event in ledger.events()
            if event.operation == "operation:assessment-revision-frozen"
        ]
    ) == 1
    assert engine.run_status(RunStatusRequest(run_id=run_id)).result_states[0].state is (
        ResultState.REPORT_READY
    )


def test_terminal_assessment_uses_structured_combined_concerns_input(tmp_path: Path) -> None:
    """The public answer submission seam carries the required Overall-policy input."""

    trial = tmp_path / "input" / "combined-concerns"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:combined-concerns", "trial:combined-concerns")),
    )
    _classify_current_sources(engine, run_id)
    answers = _low_answers() | {
        "sq:randomization:baseline-imbalance": "yes",
        "sq:selection:prespecified-analysis": "no",
    }

    _finish_current_result(
        engine,
        run_id,
        prefix="combined-concerns",
        answers=answers,
        assessor_inputs={"input:combined-concerns": True},
    )

    report = next((tmp_path / "output" / "report-bundle").rglob("assessment.json"))
    assert json.loads(report.read_text(encoding="utf-8"))["overall_judgment"] == "high"


def test_correct_domain_answers_creates_successors_without_refreezing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = tmp_path / "input" / "answer-correction"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:answer-correction", "trial:answer-correction")),
    )
    _classify_current_sources(engine, run_id)
    original = _finish_current_result(engine, run_id, prefix="answer-correction")
    request = original["domain:randomization"]
    original_correction_token = _current_correction_token(
        engine, run_id, request.result_id, request.domain_id
    )
    unsupported_no_information = CorrectDomainAnswersRequest.model_validate(
        request.model_dump(mode="json")
        | {
            "idempotency_key": "idempotency:answer-correction-no-information",
            "work_token": original_correction_token.model_dump(mode="json"),
            "answers": [
                item.model_dump(mode="json")
                | (
                    {"answer": "no_information", "rationale": "No information correction."}
                    if item.question_id == request.answers[0].question_id
                    else {}
                )
                for item in request.answers
            ],
        }
    )
    with pytest.raises(ValueError, match="complete Search coverage basis"):
        engine.correct_domain_answers(unsupported_no_information)
    correction = CorrectDomainAnswersRequest.model_validate(
        request.model_dump(mode="json")
        | {
            "idempotency_key": "idempotency:answer-correction-successor",
            "work_token": original_correction_token.model_dump(mode="json"),
            "answers": [
                item.model_dump(mode="json") | {"rationale": "Corrected rationale."}
                for item in request.answers
            ],
        }
    )
    response = engine.correct_domain_answers(correction).model_dump(mode="json")
    repeated = engine.correct_domain_answers(correction).model_dump(mode="json")
    successor = CorrectDomainAnswersRequest.model_validate(
        correction.model_dump(mode="json")
        | {
            "idempotency_key": "idempotency:answer-correction-successor-two",
            "work_token": response["correction_token"],
            "answers": [
                item.model_dump(mode="json") | {"rationale": "Second corrected rationale."}
                for item in correction.answers
            ],
        }
    )
    second = engine.correct_domain_answers(successor).model_dump(mode="json")
    stale_correction = CorrectDomainAnswersRequest.model_validate(
        correction.model_dump(mode="json")
        | {
            "idempotency_key": "idempotency:answer-correction-stale-token",
            "answers": [
                item.model_dump(mode="json") | {"rationale": "Stale token correction."}
                for item in correction.answers
            ],
        }
    )

    assert response["committed"] is True
    assert repeated["committed"] is False
    assert second["committed"] is True
    assert response["answer_revisions"] != second["answer_revisions"]
    with pytest.raises(ValueError, match="current engine-issued correction WorkToken"):
        engine.correct_domain_answers(stale_correction)
    assert len(list((tmp_path / "output" / "report-bundle").rglob("assessment.json"))) == 3
    status = engine.get_run_status(RunStatusRequest(run_id=run_id))
    assert status.run_state is RunState.COMPLETE
    index = json.loads(
        next((tmp_path / "output" / "report-bundle").rglob("run-index.json")).read_text(
            encoding="utf-8"
        )
    )
    assert len(index["results"]) == 1
    current = index["results"][0]
    assert current["result_id"] == request.result_id
    assert current["trial_id"] == "trial:answer-correction"
    assert current["state"] == "report_ready"
    assert "assessment-" in current["report"]


def test_correction_replaces_prior_assessor_inputs_in_terminal_assessment(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "corrected-overall-input"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:corrected-overall-input", "trial:corrected-overall-input")),
    )
    _classify_current_sources(engine, run_id)
    answers = _low_answers() | {
        "sq:randomization:baseline-imbalance": "yes",
        "sq:selection:prespecified-analysis": "no",
    }
    original = _finish_current_result(
        engine,
        run_id,
        prefix="corrected-overall-input",
        answers=answers,
        assessor_inputs_by_domain={
            "domain:randomization": {"input:combined-concerns": False}
        },
    )
    before = next((tmp_path / "output" / "report-bundle").rglob("assessment.json"))
    assert json.loads(before.read_text(encoding="utf-8"))["overall_judgment"] == "some_concerns"

    request = original["domain:randomization"]
    correction = CorrectDomainAnswersRequest.model_validate(
        request.model_dump(mode="json")
        | {
            "idempotency_key": "idempotency:corrected-overall-input",
            "work_token": _current_correction_token(
                engine, run_id, request.result_id, request.domain_id
            ).model_dump(mode="json"),
            "assessor_inputs": {"input:combined-concerns": True},
            "answers": [
                item.model_dump(mode="json") | {"rationale": "Corrected Overall-policy input."}
                for item in request.answers
            ],
        }
    )

    engine.correct_domain_answers(correction)

    reports = tuple((tmp_path / "output" / "report-bundle").rglob("assessment.json"))
    assert len(reports) == 2
    assert {
        json.loads(report.read_text(encoding="utf-8"))["overall_judgment"]
        for report in reports
    } == {"some_concerns", "high"}


def test_final_judgment_departure_must_bind_the_authorized_domain(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "departure-scope"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:departure-scope", "trial:departure-scope")),
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:departure-scope-evidence",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
        )
    )
    answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert answer is not None

    with pytest.raises(ValueError, match="authorized by this WorkToken"):
        engine.submit_domain_answers(
            SubmitDomainAnswersRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=answer.work_token,
                idempotency_key="idempotency:departure-scope-answers",
                result_id=answer.result_id,
                domain_id=answer.domain_id,
                answers=tuple(
                    {
                        "question_id": question_id,
                        "answer": _low_answers()[question_id],
                        "rationale": "Fixture rationale.",
                    }
                    for question_id in DOMAINS[answer.domain_id]
                ),
                final_judgment_departures=(
                    {
                        "domain_id": "domain:selection",
                        "judgment": "high",
                        "alternative": "some_concerns",
                        "material_bias_rationale": "Fixture departure.",
                        "cited_evidence": [
                            {
                                "entity_id": "evidence:fixture",
                                "revision_id": "revision:evidence-fixture",
                                "content_hash": "sha256:" + ("a" * 64),
                            }
                        ],
                    },
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


def test_domain_evidence_freezes_engine_issued_passages_without_host_hashes(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "passages"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:passages", "trial:passages")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    detailed = engine.get_work_context(
        GetWorkContextRequest(
            run_id=run_id,
            work_token=work.work_token,
            include_source_details=True,
        )
    ).context
    assert detailed is not None
    assert detailed.detailed_sources
    assert {source.source_id for source in detailed.detailed_sources} == {
        source.source_id for source in detailed.sources
    }
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    request = SubmitDomainEvidenceRequest(
        contract_version="1.0.0",
        run_id=run_id,
        work_token=work.work_token,
        idempotency_key="idempotency:passage-domain-evidence",
        result_id="result:passages",
        domain_id="domain:randomization",
        passages=(
            EvidencePassageInput(
                unit_id=unit_id,
                span_start=0,
                span_end=len(unit.text),
                claim_type="claim-type:randomization-method",
                candidate_id=unit_id,
                question_ids=(DOMAINS["domain:randomization"][0],),
            ),
        ),
        coverage_receipts=_complete_passage_receipts(engine, run_id, work, unit_id=unit_id),
    )
    response = engine.submit_domain_evidence(request)

    assert response.condition.value == "accepted"
    assert len(response.evidence_bundles) == len(DOMAINS["domain:randomization"])
    ledger = engine._bound_ledger(run_id)
    bundles = [
        json.loads(ledger.artifacts.read(reference.content_hash))
        for reference in response.evidence_bundles
    ]
    bundle = next(item for item in bundles if item["sq_id"] == DOMAINS["domain:randomization"][0])
    claim_ref = bundle["items"][0]
    claim = EvidenceClaim.model_validate_json(ledger.artifacts.read(claim_ref["content_hash"]))
    assert claim.span_start == 0
    assert claim.span_end == len(unit.text)
    assert claim.quoted_text_hash == "sha256:" + hashlib.sha256(unit.text.encode()).hexdigest()
    assert all(
        not item["items"] for item in bundles if item["sq_id"] != DOMAINS["domain:randomization"][0]
    )
    event_count = len(ledger.events())
    repeated = engine.submit_domain_evidence(request)
    assert repeated.committed is False
    assert repeated.operation_id == response.operation_id
    assert len(ledger.events()) == event_count


def test_domain_evidence_passage_can_select_to_unit_end_without_counting_characters(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "passage-end"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:passage-end", "trial:passage-end")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit = index.read_unit(next(iter(index.unit_ids())))

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:passage-to-end",
            result_id="result:passage-end",
            domain_id="domain:randomization",
            passages=(
                EvidencePassageInput(
                    unit_id=unit.unit_id,
                    span_start=0,
                    claim_type="claim-type:randomization-method",
                    candidate_id=unit.unit_id,
                    question_ids=(DOMAINS["domain:randomization"][0],),
                ),
            ),
            coverage_receipts=_complete_passage_receipts(
                engine, run_id, work, unit_id=unit.unit_id
            ),
        )
    )

    ledger = engine._bound_ledger(run_id)
    bundles = [
        json.loads(ledger.artifacts.read(reference.content_hash))
        for reference in response.evidence_bundles
    ]
    bundle = next(item for item in bundles if item["sq_id"] == DOMAINS["domain:randomization"][0])
    claim = EvidenceClaim.model_validate_json(
        ledger.artifacts.read(bundle["items"][0]["content_hash"])
    )
    assert claim.span_end == len(unit.text)


def test_unstructured_units_require_visual_or_classification_recovery(tmp_path: Path) -> None:
    from rob2_kit.evidence.search import CanonicalEvidenceUnit, CanonicalUnitKind, DocumentZone

    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = CanonicalEvidenceUnit(
        unit_id="unit:unstructured",
        source_id="source:report",
        source_artifact_hash="sha256:" + "a" * 64,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.UNCLASSIFIED,
        text="unstructured prose",
        trial_id="trial:active",
        result_id="result:active",
        document_zone=DocumentZone.UNKNOWN,
        applicability="result",
    )
    index.replace_units((unit,))
    with pytest.raises(ValueError, match="outside the active retrieval scope"):
        index.read_unit(
            unit.unit_id,
            scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
        )


def test_invalid_late_passage_writes_no_artifacts_or_ledger_events(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "invalid-passage"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:invalid-passage", "trial:invalid-passage")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)
    ledger = engine._bound_ledger(run_id)
    events_before = ledger.events()
    revisions_before = ledger.current_revisions()
    artifacts_before = tuple(sorted((tmp_path / ".rob2" / "artifacts").rglob("*")))

    with pytest.raises(ValueError, match="another domain's questions"):
        engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key="idempotency:invalid-late-passage",
                result_id="result:invalid-passage",
                domain_id="domain:randomization",
                passages=(
                    EvidencePassageInput(
                        unit_id=unit_id,
                        span_start=0,
                        span_end=len(unit.text),
                        claim_type="claim-type:randomization-method",
                        question_ids=(DOMAINS["domain:randomization"][0],),
                    ),
                    EvidencePassageInput(
                        unit_id=unit_id,
                        span_start=0,
                        span_end=len(unit.text),
                        claim_type="claim-type:wrong-domain",
                        question_ids=(DOMAINS["domain:deviations"][0],),
                    ),
                ),
            )
        )

    assert ledger.events() == events_before
    assert ledger.current_revisions() == revisions_before
    assert tuple(sorted((tmp_path / ".rob2" / "artifacts").rglob("*"))) == artifacts_before

    for span_start in (len(unit.text), len(unit.text) + 1):
        with pytest.raises(ValueError, match="passage span is empty or exceeds"):
            engine.submit_domain_evidence(
                SubmitDomainEvidenceRequest(
                    contract_version="1.0.0",
                    run_id=run_id,
                    work_token=work.work_token,
                    idempotency_key=f"idempotency:invalid-open-span-{span_start}",
                    result_id="result:invalid-passage",
                    domain_id="domain:randomization",
                    passages=(
                        EvidencePassageInput(
                            unit_id=unit_id,
                            span_start=span_start,
                            claim_type="claim-type:randomization-method",
                            question_ids=(DOMAINS["domain:randomization"][0],),
                        ),
                    ),
                )
            )
        assert ledger.events() == events_before
        assert ledger.current_revisions() == revisions_before
        assert tuple(sorted((tmp_path / ".rob2" / "artifacts").rglob("*"))) == artifacts_before

    with pytest.raises(ValueError, match="question_ids must be unique"):
        engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key="idempotency:duplicate-question-passage",
                result_id="result:invalid-passage",
                domain_id="domain:randomization",
                passages=(
                    EvidencePassageInput(
                        unit_id=unit_id,
                        span_start=0,
                        span_end=len(unit.text),
                        claim_type="claim-type:randomization-method",
                        question_ids=(
                            DOMAINS["domain:randomization"][0],
                            DOMAINS["domain:randomization"][0],
                        ),
                    ),
                ),
            )
        )
    assert ledger.events() == events_before
    assert ledger.current_revisions() == revisions_before
    assert tuple(sorted((tmp_path / ".rob2" / "artifacts").rglob("*"))) == artifacts_before


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
    ] == ["result:contract"]


def test_resolved_outcome_candidate_survives_unrelated_source_change(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "support.pdf"
    support.parent.mkdir()
    support.write_bytes(b"support")
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(_config(with_target=True)), encoding="utf-8")
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    candidate = prepared.proposal.result_candidates[0]
    ambiguity = next(
        item for item in prepared.proposal.ambiguities if item.scope == candidate.candidate_id
    )
    selection = RunProposalSelection(
        trial_id=candidate.trial_id,
        result_id=candidate.result_id,
        result_candidate_id=candidate.candidate_id,
        outcome_target_id=candidate.outcome_target_id,
    )
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert review_work is not None
    engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:reconciliation-candidate-source-review",
            selections=tuple(
                RunProposalSelection(
                    trial_id=source_candidate.trial_id,
                    source_id=source_candidate.source_id,
                    accepted=True,
                )
                for source_candidate in prepared.proposal.source_role_candidates
            ),
        )
    )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-candidate-proposal",
            selections=(selection,),
            ambiguities=(
                ambiguity.model_copy(update={"resolved": True, "resolution": "mapped by operator"}),
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


def test_first_terminal_unresolved_result_refreshes_run_index_on_continue(
    tmp_path: Path,
) -> None:
    """A post-confirmation Result must be included in the first terminal index."""

    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(tmp_path, config=_config())
    _classify_current_sources(engine, run_id)
    resolution_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resolution_work is not None and resolution_work.result_id is not None
    result = Result.model_validate(_result(resolution_work.result_id, "trial:trial-a")["result"])
    engine.submit_result_resolution(
        SubmitResultResolutionRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=resolution_work.work_token,
            idempotency_key="idempotency:first-terminal-index-resolution",
            result=result,
            estimate=Estimate(value=Decimal("0.8")),
            provenance_note="first terminal index fixture",
        )
    )
    _finish_current_result(engine, run_id, prefix="first-terminal-index")

    terminal = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert terminal.run_state is RunState.COMPLETE
    indexes = tuple((tmp_path / "output" / "report-bundle").rglob("run-index.json"))
    assert len(indexes) == 1
    index = json.loads(indexes[0].read_text(encoding="utf-8"))
    assert len(index["results"]) == 1
    row = index["results"][0]
    assert row["result_id"] == resolution_work.result_id
    assert row["state"] == "report_ready"
    assert row["report"].endswith("/assessment.html")
    assert index["ancillary_outputs"]

    events_before_retry = len(engine._bound_ledger(run_id).events())
    repeated = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert repeated.run_state is RunState.COMPLETE
    assert len(engine._bound_ledger(run_id).events()) == events_before_retry
    assert json.loads(indexes[0].read_text(encoding="utf-8")) == index


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
    run_index_path = next((tmp_path / "output" / "report-bundle").rglob("run-index.json"))
    run_index = json.loads(run_index_path.read_text(encoding="utf-8"))
    diagnostic_row = next(
        item for item in run_index["results"] if item["result_id"].startswith("result:diagnostic-")
    )
    assert diagnostic_row["trial_id"] == "trial:trial-b"
    assert diagnostic_row["outcome"] == ""
    diagnostic_root = run_index_path.parent / diagnostic_row["report"].replace(
        "diagnostic.html", ""
    )
    diagnostic = json.loads((diagnostic_root / "diagnostic.json").read_text(encoding="utf-8"))
    assert diagnostic["preparation_outcome"] == "trial_failed"
    assert diagnostic["recovery"] == [
        "Restore the required readable Trial Source and continue the Run."
    ]
    _classify_current_sources(engine, run_id)
    next_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert next_work is not None
    assert next_work.result_id == "result:a"


def test_initial_failed_trial_publishes_a_recoverable_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "input" / "trial-failed").mkdir(parents=True)
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(_config(with_target=False)), encoding="utf-8"
    )

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    events = engine._bound_ledger(prepared.run_id).events()
    diagnostic_event = next(
        event for event in events if event.operation == "operation:result-diagnostic-ready"
    )
    diagnostic_record = json.loads(
        engine._bound_ledger(prepared.run_id).artifacts.read(
            diagnostic_event.output_revision_hashes[0]
        )
    )
    assert diagnostic_record["preparation_outcome"] == "trial_failed"
    assert diagnostic_record["recovery"] == [
        "Provide the required readable Trial Source and continue the Run."
    ]


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
    assert continued.work_item.operation.value == "submit_source_role_review"
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
        and event.sequence
        > max(
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
    (trial / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "path": "supplements/supplement.pdf",
                        "roles": ["clinical_study_report"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first = _result("result:a", "trial:trial-a")
    first["result"]["source_locator"] = "report.pdf p. 1"
    second = _result("result:b", "trial:trial-a")
    second["result"]["outcome_construct"] = "morbidity"
    second["result"]["source_locator"] = "supplements/supplement.pdf p. 1"
    config = _config(first, second)
    config["outcome_targets"].append(
        {"id": "morbidity", "label": "morbidity", "construct": "morbidity", "timepoint": "30 days"}
    )
    engine, run_id = _prepare_confirm(tmp_path, config=config)
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

    removed = _config(with_target=True)
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(removed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.ASSESSING
    assert blocked.error is None

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
        event.operation == "operation:run-register-result" and event.scope == "result:a"
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
        item.relative_path: item for item in refreshed.initialization.trials[0].inventory.sources
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
    report_record = json.loads(
        ledger.artifacts.read(report_events_before[-1].output_revision_hashes[0])
    )
    prior_report_root = tmp_path / report_record["report_root"]
    assert prior_report_root.is_dir()
    report.write_bytes(b"changed primary")
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.result_id == "result:a"
    assert (
        engine.run_status(RunStatusRequest(run_id=run_id)).result_states[0].state.value == "pending"
    )
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:run-reopened" for event in events)
    assert any(event.operation == "operation:result-invalidated" for event in events)
    assert len(
        [event for event in events if event.operation == "operation:result-report-ready"]
    ) == len(report_events_before)
    run_index = json.loads(
        next((tmp_path / "output" / "report-bundle").rglob("run-index.json")).read_text(
            encoding="utf-8"
        )
    )
    assert len(run_index["results"]) == 1
    assert run_index["results"][0]["state"] == "pending"
    assert run_index["results"][0]["report"] == ""
    assert prior_report_root.is_dir()
    _finish_current_result(engine, run_id, prefix="reconciliation-rerun")
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    assert (
        len(
            [
                event
                for event in engine._bound_ledger(run_id).events()
                if event.operation == "operation:run-completed"
            ]
        )
        == 2
    )


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
    report_record = json.loads(
        engine._bound_ledger(run_id).artifacts.read(
            report_events_before[-1].output_revision_hashes[0]
        )
    )
    prior_report_root = tmp_path / report_record["report_root"]
    assert prior_report_root.is_dir()
    report.unlink()
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.COMPLETE
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    assert status.result_states[0].state.value == "diagnostic_ready"
    assert len(status.progress.report_locations) == 1
    diagnostic_root = tmp_path / status.progress.report_locations[0]
    assert (diagnostic_root / "diagnostic.html").is_file()
    diagnostic = json.loads((diagnostic_root / "diagnostic.json").read_text(encoding="utf-8"))
    manifest = json.loads((diagnostic_root / "manifest.json").read_text(encoding="utf-8"))
    markdown = (diagnostic_root / "diagnostic.md").read_text(encoding="utf-8")
    assert diagnostic["preparation_outcome"] == "trial_failed"
    assert diagnostic["recovery"] == [
        "Restore the required readable Trial Source and continue the Run."
    ]
    assert manifest["preparation_outcome"] == diagnostic["preparation_outcome"]
    assert manifest["recovery"] == diagnostic["recovery"]
    assert "## Recovery path" in markdown
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:result-invalidated" for event in events)
    assert any(event.operation == "operation:result-diagnostic-ready" for event in events)
    assert len(
        [event for event in events if event.operation == "operation:result-report-ready"]
    ) == len(report_events_before)
    run_index = json.loads(
        next((tmp_path / "output" / "report-bundle").rglob("run-index.json")).read_text(
            encoding="utf-8"
        )
    )
    assert len(run_index["results"]) == 1
    current = run_index["results"][0]
    assert current["state"] == "diagnostic_ready"
    assert current["report"].endswith("/diagnostic.html")
    assert "assessment.html" not in current["report"]
    assert current["overall_judgment"] is None
    assert prior_report_root.is_dir()
