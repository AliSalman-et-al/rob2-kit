"""Application-owned persistence and v2-only navigation contract checks."""

from __future__ import annotations

import threading

import pytest

from rob2_kit.application.contracts import (
    ReadEvidenceRequest,
    RunOperation,
    SearchEvidenceRequest,
    SubmitEvidenceReviewRequest,
    WorkToken,
)
from rob2_kit.application.evidence_navigation import (
    ConcurrentEvidenceNavigationUpdate,
    EvidenceNavigationStore,
    IncompatibleEvidenceNavigationState,
    new_navigation_state,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.errors import StaleSearchContinuation
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceReadBatchItem,
    EvidenceReadBatchRequest,
    EvidenceReadBatchScope,
    EvidenceReadPolicy,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    ReadContextMode,
    SearchContinuationReason,
    SearchQuery,
)
from rob2_kit.evidence.workflow import (
    SearchPassKind,
    V2CandidateTriageRevision,
    V2EvidenceWorkflowState,
    V2IrrelevantReason,
    V2QueryAttemptKind,
    V2SearchAttempt,
    V2TriageBasis,
    V2TriageKind,
    record_v2_page_exposure,
    start_v2_search_attempt,
    submit_v2_page_triage,
)
from tests.test_input_reconciliation import (
    _classify_current_sources,
    _config,
    _prepare_confirm,
    _result,
)


def _token() -> WorkToken:
    return WorkToken(
        token="token:domain-evidence",
        run_id="run:one",
        work_item_id="work:one",
        operation=RunOperation.SUBMIT_DOMAIN_EVIDENCE,
        dependency_fingerprint=canonical_hash({"work": 1}),
        result_id="result:one",
        domain_id="domain:one",
    )


def _workflow(tmp_path):
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    snapshot = index.replace_units(
        (
            CanonicalEvidenceUnit(
                unit_id="unit:one",
                source_id="source:one",
                source_artifact_hash=canonical_hash({"source": 1}),
                parse_id="parse:one",
                page=1,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="Allocation source-authored text.",
                fragment_ids=("fragment:one",),
            ),
            CanonicalEvidenceUnit(
                unit_id="unit:two",
                source_id="source:one",
                source_artifact_hash=canonical_hash({"source": 1}),
                parse_id="parse:one",
                page=2,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="Allocation separate source-authored text.",
                fragment_ids=("fragment:two",),
            ),
        )
    )
    policy = EvidenceSearchPolicy(candidate_ceiling=1)
    query = SearchQuery(terms=("allocation",))
    attempt = V2SearchAttempt(
        attempt_id="attempt:one",
        sq_id="sq:one",
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        query=query,
        query_hash=canonical_hash(query),
        kind=V2QueryAttemptKind.EXPLORATORY,
    )
    workflow = V2EvidenceWorkflowState(
        result_id="result:one",
        domain_id="domain:one",
        snapshot_hash=snapshot,
        search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy),
    )
    page = index.search_v2(query, policy=policy)
    workflow = start_v2_search_attempt(workflow, attempt)
    workflow = record_v2_page_exposure(workflow, attempt_id=attempt.attempt_id, page=page)
    assert page.continuation is not None
    second = index.search_v2(
        query,
        policy=policy,
        continuation=page.continuation,
        continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
    )
    workflow = record_v2_page_exposure(workflow, attempt_id=attempt.attempt_id, page=second)
    return workflow, page, policy


def test_navigation_state_survives_restart_and_triage_is_idempotent(tmp_path) -> None:
    workflow, page, policy = _workflow(tmp_path)
    read_policy = EvidenceReadPolicy()
    state = new_navigation_state(
        run_id="run:one",
        workflow=workflow,
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
    )
    store = EvidenceNavigationStore(tmp_path)
    store.save(state)
    restored = EvidenceNavigationStore(tmp_path).load(
        run_id="run:one",
        result_id="result:one",
        domain_id="domain:one",
        snapshot_hash=workflow.snapshot_hash,
        search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy),
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
    )
    assert restored == state
    revision = V2CandidateTriageRevision(
        revision_id="triage:one",
        candidate_id=page.candidate_ids[0],
        attempt_id="attempt:one",
        sq_id="sq:one",
        page_handle=page.page_handle,
        kind=V2TriageKind.IRRELEVANT,
        irrelevant_reason=V2IrrelevantReason.LEXICAL_FALSE_POSITIVE,
        basis=V2TriageBasis.PREVIEW,
    )
    reviewed = submit_v2_page_triage(
        restored.workflow,
        submission_id="submission:one",
        page_handles=(page.page_handle,),
        revisions=(revision,),
    )
    assert (
        submit_v2_page_triage(
            reviewed,
            submission_id="submission:one",
            page_handles=(page.page_handle,),
            revisions=(revision,),
        )
        == reviewed
    )
    # Every surfaced attempt remains disposition-required, even exploratory
    # history that cannot earn selected-query coverage credit.
    assert reviewed.outstanding_triage_candidate_ids() == (
        workflow.exposures[-1].candidate_id,
    )
    with pytest.raises(IncompatibleEvidenceNavigationState, match="supersede Preparation"):
        store.load(
            run_id="run:one",
            result_id="result:one",
            domain_id="domain:one",
            snapshot_hash=canonical_hash({"changed": True}),
            search_policy_id=policy.policy_id,
            search_policy_hash=canonical_hash(policy),
            read_policy_id=read_policy.policy_id,
            read_policy_hash=canonical_hash(read_policy),
        )


def test_navigation_store_rejects_lost_update_by_content_hash(tmp_path) -> None:
    workflow, _, policy = _workflow(tmp_path)
    read_policy = EvidenceReadPolicy()
    state = new_navigation_state(
        run_id="run:one",
        workflow=workflow,
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
    )
    store = EvidenceNavigationStore(tmp_path)
    store.save(state)
    with pytest.raises(ConcurrentEvidenceNavigationUpdate, match="changed"):
        store.save(state, expected_content_hash=canonical_hash({"stale": True}))


def test_concurrent_navigation_store_writers_preserve_or_report_a_cas_conflict(tmp_path) -> None:
    workflow, page, policy = _workflow(tmp_path)
    read_policy = EvidenceReadPolicy()
    state = new_navigation_state(
        run_id="run:one",
        workflow=workflow,
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
    )
    EvidenceNavigationStore(tmp_path).save(state)

    def updated(submission_id: str, revision_id: str):
        reviewed = submit_v2_page_triage(
            workflow,
            submission_id=submission_id,
            page_handles=(page.page_handle,),
            revisions=(
                V2CandidateTriageRevision(
                    revision_id=revision_id,
                    candidate_id=page.candidate_ids[0],
                    attempt_id="attempt:one",
                    sq_id="sq:one",
                    page_handle=page.page_handle,
                    kind=V2TriageKind.IRRELEVANT,
                    irrelevant_reason=V2IrrelevantReason.LEXICAL_FALSE_POSITIVE,
                    basis=V2TriageBasis.PREVIEW,
                ),
            ),
        )
        return new_navigation_state(
            run_id="run:one",
            workflow=reviewed,
            read_policy_id=read_policy.policy_id,
            read_policy_hash=canonical_hash(read_policy),
        )

    updates = (updated("submission:a", "triage:a"), updated("submission:b", "triage:b"))
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def writer(update) -> None:
        barrier.wait()
        try:
            EvidenceNavigationStore(tmp_path).save(update, expected_content_hash=state.content_hash)
            outcomes.append(update.content_hash)
        except ConcurrentEvidenceNavigationUpdate as error:
            outcomes.append(error)

    threads = tuple(threading.Thread(target=writer, args=(update,)) for update in updates)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([item for item in outcomes if isinstance(item, str)]) == 1
    assert (
        len([item for item in outcomes if isinstance(item, ConcurrentEvidenceNavigationUpdate)])
        == 1
    )
    restored = EvidenceNavigationStore(tmp_path).load(
        run_id="run:one",
        result_id="result:one",
        domain_id="domain:one",
        snapshot_hash=workflow.snapshot_hash,
        search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy),
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
    )
    assert restored is not None
    assert restored.content_hash in {update.content_hash for update in updates}


def test_navigation_lock_never_deletes_a_foreign_owner_lock(tmp_path, monkeypatch) -> None:
    workflow, _, _ = _workflow(tmp_path)
    store = EvidenceNavigationStore(tmp_path)
    path = store._path("run:one", "result:one", "domain:one")
    path.parent.mkdir(parents=True)
    lock = path.with_suffix(".lock")
    lock.write_text("foreign-owner", encoding="utf-8")
    ticks = iter((0.0, 6.0))
    monkeypatch.setattr(
        "rob2_kit.application.evidence_navigation.time.monotonic", lambda: next(ticks)
    )
    with pytest.raises(ConcurrentEvidenceNavigationUpdate, match="busy"):
        with store._mutation_lock(path):
            pytest.fail("foreign lock must not be acquired")
    assert lock.read_text(encoding="utf-8") == "foreign-owner"


def _issued_read_request(tmp_path):
    trial = tmp_path / "input" / "scope"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path, config=_config(_result("result:scope", "trial:scope"))
    )
    _classify_current_sources(engine, run_id)
    from rob2_kit.application.contracts import ContinueRunRequest

    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    response = engine.search_evidence(
        SearchEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            result_id="result:scope",
            sq_id="sq:randomization:sequence",
            pass_kind=SearchPassKind.GUIDANCE_SEED,
            seed_family="seed:scope",
            query=SearchQuery(terms=("primary",)),
            attempt_id="attempt:scope",
            attempt_kind=V2QueryAttemptKind.EXPLORATORY,
        )
    )
    candidate = response.page.candidates[0]
    request = ReadEvidenceRequest(
        contract_version="2.0.0",
        run_id=run_id,
        work_token=work.work_token,
        result_id="result:scope",
        batch=EvidenceReadBatchRequest(
            scope=EvidenceReadBatchScope(
                result_id="result:scope",
                domain_id="domain:randomization",
                snapshot_hash=response.page.snapshot_hash,
            ),
            items=(
                EvidenceReadBatchItem(
                    location_handle=candidate.location_handle,
                    question_ids=("sq:randomization:sequence",),
                ),
            ),
        ),
    )
    return engine, run_id, request, response, candidate


@pytest.mark.parametrize("attack", ("result", "domain", "question", "source"))
def test_application_read_scope_attacks_fail_atomically(tmp_path, attack: str) -> None:
    engine, _, request, _, _ = _issued_read_request(tmp_path)
    item = request.batch.items[0]
    if attack == "result":
        request = request.model_copy(update={"result_id": "result:wrong"})
    elif attack == "domain":
        scope = request.batch.scope.model_copy(update={"domain_id": "domain:wrong"})
        request = request.model_copy(
            update={"batch": request.batch.model_copy(update={"scope": scope})}
        )
    elif attack == "question":
        wrong_item = item.model_copy(update={"question_ids": ("sq:missing:data-available",)})
        request = request.model_copy(
            update={"batch": request.batch.model_copy(update={"items": (wrong_item,)})}
        )
    else:
        wrong_item = item.model_copy(update={"source_ids": ("source:wrong",)})
        request = request.model_copy(
            update={"batch": request.batch.model_copy(update={"items": (wrong_item,)})}
        )
    with pytest.raises(Exception) as failure:
        engine.read_evidence(request)
    assert type(failure.value).__name__ in {
        "ScopeMismatch",
        "InvalidRetrievalRequest",
        "StaleWorkToken",
    }


def test_v2_old_or_unexposed_read_handle_is_a_typed_stale_navigation_failure(tmp_path) -> None:
    engine, _, request, _, _ = _issued_read_request(tmp_path)
    stale_item = request.batch.items[0].model_copy(update={"location_handle": "loc:old"})
    stale_request = request.model_copy(
        update={"batch": request.batch.model_copy(update={"items": (stale_item,)})}
    )
    with pytest.raises(StaleSearchContinuation) as failure:
        engine.read_evidence(stale_request)
    assert failure.value.code.value == "stale_cursor"
    assert failure.value.field == "batch.items"


def test_mcp_v2_search_accounting_binds_the_complete_operation_envelope(tmp_path) -> None:
    _, _, _, response, _ = _issued_read_request(tmp_path)
    from rob2_kit.interfaces.mcp.server import _dump

    payload = _dump(response)
    accounting = payload["response_accounting"]
    assert payload["coverage_progress"]["sq_id"] == "sq:randomization:sequence"
    assert accounting["scope"] == "complete_mcp_operation_envelope"
    assert accounting["serialized_response_bytes"] == len(canonical_json_bytes(payload))
    assert (
        accounting["estimated_response_tokens"]
        == (accounting["serialized_response_bytes"] + 3) // 4
    )
    diagnostics = payload["page"]["source_diagnostics"]
    assert diagnostics and diagnostics[0]["source_ref"] == 0


def _receipt_review_request(request, page, candidate, receipt: str, suffix: str):
    return SubmitEvidenceReviewRequest(
        contract_version="2.0.0",
        run_id=request.run_id,
        work_token=request.work_token,
        idempotency_key=f"idempotency:receipt:{suffix}",
        result_id=request.result_id,
        domain_id=request.work_token.domain_id,
        submission_id=f"submission:receipt:{suffix}",
        page_handles=(page.page_handle,),
        triage_revisions=(
            V2CandidateTriageRevision(
                revision_id=f"triage:receipt:{suffix}",
                candidate_id=candidate.candidate_id,
                attempt_id="attempt:scope",
                sq_id="sq:randomization:sequence",
                page_handle=page.page_handle,
                kind=V2TriageKind.IRRELEVANT,
                irrelevant_reason=V2IrrelevantReason.LEXICAL_FALSE_POSITIVE,
                basis=V2TriageBasis.READ_VIEW_RECEIPT,
                read_view_receipt=receipt,
            ),
        ),
    )


def test_review_rejects_forged_read_receipt(tmp_path) -> None:
    engine, _, request, response, candidate = _issued_read_request(tmp_path)
    with pytest.raises(Exception, match="receipt"):
        engine.submit_evidence_review(
            _receipt_review_request(request, response.page, candidate, "read-view:forged", "forged")
        )


def test_review_rejects_valid_receipt_bound_to_another_question(tmp_path) -> None:
    engine, _, request, response, candidate = _issued_read_request(tmp_path)
    view = engine.read_evidence(request).page.outcomes[0].view
    assert view is not None
    index = EvidenceSearchIndex(engine._required_root() / ".rob2" / "evidence.sqlite3")
    reviewed = index.resolve_read_view_receipt(view.read_view_receipt)
    unit = index.read_unit(candidate.canonical_unit_id)
    wrong_question_receipt = index.issue_read_view_receipt(
        snapshot_hash=response.page.snapshot_hash,
        requested_mode=ReadContextMode.UNIT,
        applied_mode=ReadContextMode.UNIT,
        continuation_input=None,
        continuation=None,
        fragments=reviewed.fragments,
        displayed_units=(unit,),
        read_policy_id=EvidenceReadPolicy().policy_id,
        read_policy_hash=canonical_hash(EvidenceReadPolicy()),
        question_ids=("sq:randomization:concealment",),
    )
    with pytest.raises(Exception, match="receipt"):
        engine.submit_evidence_review(
            _receipt_review_request(
                request, response.page, candidate, wrong_question_receipt, "wrong-question"
            )
        )


def test_review_rejects_valid_receipt_bound_to_another_read_policy(tmp_path) -> None:
    engine, _, request, response, candidate = _issued_read_request(tmp_path)
    view = engine.read_evidence(request).page.outcomes[0].view
    assert view is not None
    index = EvidenceSearchIndex(engine._required_root() / ".rob2" / "evidence.sqlite3")
    reviewed = index.resolve_read_view_receipt(view.read_view_receipt)
    unit = index.read_unit(candidate.canonical_unit_id)
    foreign_policy = EvidenceReadPolicy(policy_id="policy:evidence-read-test-foreign")
    foreign_policy_receipt = index.issue_read_view_receipt(
        snapshot_hash=response.page.snapshot_hash,
        requested_mode=ReadContextMode.UNIT,
        applied_mode=ReadContextMode.UNIT,
        continuation_input=None,
        continuation=None,
        fragments=reviewed.fragments,
        displayed_units=(unit,),
        read_policy_id=foreign_policy.policy_id,
        read_policy_hash=canonical_hash(foreign_policy),
        question_ids=("sq:randomization:sequence",),
    )
    with pytest.raises(Exception, match="receipt"):
        engine.submit_evidence_review(
            _receipt_review_request(
                request, response.page, candidate, foreign_policy_receipt, "wrong-policy"
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("unit_id", "unit:wrong"),
        ("source_id", "source:wrong"),
        ("parse_id", "parse:wrong"),
    ),
)
def test_review_rejects_valid_stored_receipt_with_wrong_target_lineage(
    tmp_path, field: str, value: str
) -> None:
    engine, _, request, response, candidate = _issued_read_request(tmp_path)
    view = engine.read_evidence(request).page.outcomes[0].view
    assert view is not None
    index = EvidenceSearchIndex(engine._required_root() / ".rob2" / "evidence.sqlite3")
    reviewed = index.resolve_read_view_receipt(view.read_view_receipt)
    fragment = reviewed.fragments[0].model_copy(update={field: value})
    unit = index.read_unit(candidate.canonical_unit_id)
    displayed_unit = unit.model_copy(update={"unit_id": value}) if field == "unit_id" else unit
    wrong_lineage_receipt = index.issue_read_view_receipt(
        snapshot_hash=response.page.snapshot_hash,
        requested_mode=ReadContextMode.UNIT,
        applied_mode=ReadContextMode.UNIT,
        continuation_input=None,
        continuation=None,
        fragments=(fragment,),
        displayed_units=(displayed_unit,),
        read_policy_id=EvidenceReadPolicy().policy_id,
        read_policy_hash=canonical_hash(EvidenceReadPolicy()),
        question_ids=("sq:randomization:sequence",),
    )
    with pytest.raises(Exception, match="receipt"):
        engine.submit_evidence_review(
            _receipt_review_request(
                request,
                response.page,
                candidate,
                wrong_lineage_receipt,
                f"wrong-{field}",
            )
        )


def test_review_rejects_genuine_receipt_after_snapshot_reprocessing(tmp_path) -> None:
    engine, _, request, response, candidate = _issued_read_request(tmp_path)
    view = engine.read_evidence(request).page.outcomes[0].view
    assert view is not None
    index = EvidenceSearchIndex(engine._required_root() / ".rob2" / "evidence.sqlite3")
    index.replace_units(())
    with pytest.raises(Exception, match="stale|snapshot|supersede"):
        engine.submit_evidence_review(
            _receipt_review_request(
                request, response.page, candidate, view.read_view_receipt, "stale-snapshot"
            )
        )


def test_read_rejects_genuine_handle_issued_for_another_work_scope(tmp_path) -> None:
    engine_a, _, request_a, _, _ = _issued_read_request(tmp_path / "scope-a")
    _, _, _, _, candidate_b = _issued_read_request(tmp_path / "scope-b")
    item = request_a.batch.items[0].model_copy(
        update={"location_handle": candidate_b.location_handle}
    )
    foreign_handle_request = request_a.model_copy(
        update={"batch": request_a.batch.model_copy(update={"items": (item,)})}
    )
    with pytest.raises(Exception, match="exposed|scope|stale"):
        engine_a.read_evidence(foreign_handle_request)


def test_application_contracts_accept_only_v2_ordered_navigation() -> None:
    token = _token()
    query = SearchQuery(terms=("allocation",))
    request = SearchEvidenceRequest(
        contract_version="2.0.0",
        run_id="run:one",
        work_token=token,
        result_id="result:one",
        sq_id="sq:one",
        pass_kind=SearchPassKind.GUIDANCE_SEED,
        seed_family="seed:one",
        query=query,
        attempt_id="attempt:one",
        attempt_kind=V2QueryAttemptKind.SELECTED,
    )
    assert "cursor" not in request.model_dump(mode="json")
    read = ReadEvidenceRequest(
        contract_version="2.0.0",
        run_id="run:one",
        work_token=token,
        result_id="result:one",
        batch=EvidenceReadBatchRequest(
            scope=EvidenceReadBatchScope(
                result_id="result:one", domain_id="domain:one", snapshot_hash=canonical_hash({})
            ),
            items=(EvidenceReadBatchItem(location_handle="loc:issued", question_ids=("sq:one",)),),
        ),
    )
    assert len(read.batch.items) == 1
    review = SubmitEvidenceReviewRequest(
        contract_version="2.0.0",
        run_id="run:one",
        work_token=token,
        idempotency_key="idempotency:one",
        result_id="result:one",
        domain_id="domain:one",
        submission_id="submission:one",
        page_handles=("v2page:one",),
        triage_revisions=(),
    )
    assert review.work_token.operation is RunOperation.SUBMIT_DOMAIN_EVIDENCE
    with pytest.raises(ValueError, match="Extra inputs"):
        SearchEvidenceRequest.model_validate(request.model_dump() | {"cursor": "cur:old"})
