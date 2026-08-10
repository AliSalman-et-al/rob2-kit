"""Server-side Search coverage recorder and evidence-insufficient reroute regressions.

Covers the #127 dogfooding failure (passages-only submissions were
structurally unusable because no tool ever issued a Search coverage
receipt) and its folded #128 companion (empty submissions silently
accepted, no route back after a downstream block). See ADR-0007 and
ADR-0008 for the accepted design.
"""

from pathlib import Path

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    WorkflowCondition,
)
from rob2_kit.evidence.search import EvidenceSearchIndex, SearchQuery
from rob2_kit.evidence.workflow import SearchPassKind
from tests.test_input_reconciliation import (
    StructuredPassageParser,
    _classify_current_sources,
    _config,
    _location_handle_for,
    _low_answers,
    _prepare_confirm,
    _result,
    _review_revision,
    _v2_search_and_triage,
)
from tests.test_mcp_tracer import DOMAINS


def _complete_real_search(engine, run_id, work, question_ids) -> None:
    """Drive the mandatory search protocol through the public tool, per question."""
    for question_id in question_ids:
        seed_family = "seed:" + question_id.removeprefix("sq:").replace(":", "-")
        for query, pass_kind, family in (
            (SearchQuery(terms=("primary",)), SearchPassKind.GUIDANCE_SEED, seed_family),
            (SearchQuery(terms=("followup",)), SearchPassKind.TRIAL_FOLLOW_UP, None),
            (SearchQuery(terms=("contradiction",)), SearchPassKind.CONTRADICTION, None),
        ):
            _v2_search_and_triage(
                engine,
                run_id,
                work.work_token,
                work.result_id,
                question_id,
                query,
                pass_kind,
                family,
            )


def test_passages_only_submission_succeeds_without_a_client_supplied_receipt(
    tmp_path: Path,
) -> None:
    """Reproduces the original #127 failure: real search + passages, no receipt object."""
    trial = tmp_path / "input" / "passages-127"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:passages-127", "trial:passages-127")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    _complete_real_search(engine, run_id, work, DOMAINS["domain:randomization"])

    question_id = DOMAINS["domain:randomization"][0]
    # Its hits also carry a real location_handle for the review_revisions binding below.
    location_handle = _location_handle_for(engine, run_id, work, question_id, unit_id)

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue127-passages",
            result_id=work.result_id,
            domain_id="domain:randomization",
            passages=(
                {
                    "unit_id": unit_id,
                    "span_start": 0,
                    "span_end": len(unit.text),
                    "claim_type": "claim-type:randomization-method",
                    "question_ids": (question_id,),
                },
            ),
            review_revisions=(
                _review_revision(
                    candidate_id=unit_id,
                    result_id=work.result_id,
                    domain_id="domain:randomization",
                    question_id=question_id,
                    location_handle=location_handle,
                    span_start=0,
                    span_end=len(unit.text),
                    entity_suffix="issue127-1",
                ),
            ),
        )
    )
    assert response.condition.value == "accepted"
    assert response.committed is True
    assert len(response.evidence_bundles) == len(DOMAINS["domain:randomization"])
    assert len(response.coverage_receipts) == len(DOMAINS["domain:randomization"])


def test_no_information_basis_succeeds_without_a_client_supplied_receipt(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "no-info-127"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path, config=_config(_result("result:no-info-127", "trial:no-info-127"))
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    question_ids = DOMAINS[work.domain_id]
    _complete_real_search(engine, run_id, work, question_ids)

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue127-no-info",
            result_id=work.result_id,
            domain_id=work.domain_id,
            coverage_state="complete",
            no_information_basis=True,
        )
    )
    assert response.condition.value == "accepted"
    assert response.committed is True
    assert len(response.coverage_receipts) == len(question_ids)


def test_empty_evidence_submission_is_rejected(tmp_path: Path) -> None:
    """#128: silent acceptance of an evidence-free submission is closed."""
    trial = tmp_path / "input" / "empty-128"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path, config=_config(_result("result:empty-128", "trial:empty-128"))
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue128-empty",
            result_id=work.result_id,
            domain_id=work.domain_id,
        )
    )
    # #125: business-rule violations are reported as a structured response,
    # not a raised exception, so every problem can be batched together.
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    assert "must include real passages/items" in response.error.detail


def test_evidence_insufficient_block_reroutes_and_preserves_recorder_state(
    tmp_path: Path,
) -> None:
    """#128: recovery text says resubmit evidence; continue_run must actually route there,
    and previously found evidence must not have to be re-searched (ADR-0008)."""
    trial = tmp_path / "input" / "reroute-128"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:reroute-128", "trial:reroute-128")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    result_id = work.result_id
    domain_id = "domain:randomization"
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    _complete_real_search(engine, run_id, work, DOMAINS[domain_id])

    # An honest declared gap: coverage_state=incomplete, no items/passages.
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue128-first-evidence",
            result_id=result_id,
            domain_id=domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Intentionally deferred for reroute regression.",),
        )
    )
    answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert answer is not None
    assert answer.domain_id == domain_id
    blocked = engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=answer.work_token,
            idempotency_key="idempotency:issue128-blocked-answers",
            result_id=result_id,
            domain_id=domain_id,
            answers=tuple(
                {
                    "question_id": question_id,
                    "answer": _low_answers()[question_id],
                    "rationale": "x",
                }
                for question_id in DOMAINS[domain_id]
            ),
        )
    )
    assert blocked.condition is WorkflowCondition.RUN_BLOCKED
    assert blocked.committed is False
    assert blocked.error is not None
    assert blocked.error.code == "evidence_insufficient"

    # continue_run reroutes back to submit_domain_evidence for the same
    # Domain instead of re-offering the same blocked answer work item.
    rerouted = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert rerouted is not None
    assert rerouted.operation.value == "submit_domain_evidence"
    assert rerouted.domain_id == domain_id
    assert rerouted.result_id == result_id

    # A preview search call carries a real location_handle for the
    # review_revisions binding below; it is not itself a fresh accounted pass.
    question_id = DOMAINS[domain_id][0]
    location_handle = _location_handle_for(engine, run_id, rerouted, question_id, unit_id)

    # No further accounted search_evidence calls: the recorder accumulated
    # before the block is carried forward, so the already-found unit remains
    # citable.
    resubmitted = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=rerouted.work_token,
            idempotency_key="idempotency:issue128-second-evidence",
            result_id=result_id,
            domain_id=domain_id,
            passages=(
                {
                    "unit_id": unit_id,
                    "span_start": 0,
                    "span_end": len(unit.text),
                    "claim_type": "claim-type:randomization-method",
                    "question_ids": (question_id,),
                },
            ),
            review_revisions=(
                _review_revision(
                    candidate_id=unit_id,
                    result_id=result_id,
                    domain_id=domain_id,
                    question_id=question_id,
                    location_handle=location_handle,
                    span_start=0,
                    span_end=len(unit.text),
                    entity_suffix="issue128-1",
                ),
            ),
        )
    )
    assert resubmitted.condition.value == "accepted"
    assert resubmitted.committed is True
    assert len(resubmitted.evidence_bundles) == len(DOMAINS[domain_id])


def test_evidence_insufficient_block_reroute_also_accepts_no_information_resubmission(
    tmp_path: Path,
) -> None:
    """The carried-forward recorder (ADR-0008) serves either accept path after a reroute,
    not just passages -- an honest no_information_basis resubmission needs no re-search."""
    trial = tmp_path / "input" / "reroute-no-info-128"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:reroute-no-info-128", "trial:reroute-no-info-128")),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    result_id = work.result_id
    domain_id = work.domain_id
    question_ids = DOMAINS[domain_id]

    _complete_real_search(engine, run_id, work, question_ids)

    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue128-no-info-first-evidence",
            result_id=result_id,
            domain_id=domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Intentionally deferred for reroute regression.",),
        )
    )
    answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert answer is not None
    blocked = engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=answer.work_token,
            idempotency_key="idempotency:issue128-no-info-blocked-answers",
            result_id=result_id,
            domain_id=domain_id,
            answers=tuple(
                {
                    "question_id": question_id,
                    "answer": _low_answers()[question_id],
                    "rationale": "x",
                }
                for question_id in question_ids
            ),
        )
    )
    assert blocked.condition is WorkflowCondition.RUN_BLOCKED

    rerouted = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert rerouted is not None
    assert rerouted.operation.value == "submit_domain_evidence"
    assert rerouted.domain_id == domain_id

    # No further search_evidence calls: the recorder accumulated before the
    # block is carried forward for the no_information_basis path too.
    resubmitted = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=rerouted.work_token,
            idempotency_key="idempotency:issue128-no-info-second-evidence",
            result_id=result_id,
            domain_id=domain_id,
            coverage_state="complete",
            no_information_basis=True,
        )
    )
    assert resubmitted.condition.value == "accepted"
    assert resubmitted.committed is True
    assert len(resubmitted.coverage_receipts) == len(question_ids)
