"""Focused private-runtime coverage for issue #167's v3 vertical slice."""

from pathlib import Path

import pytest

from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    EvidenceContextInventorySource,
    EvidenceContextUnitOrientation,
    materialize_evidence_context,
)
from rob2_kit.application.evidence_navigation import (
    ConcurrentEvidenceNavigationUpdate,
    V3EvidenceNavigationStore,
    new_v3_navigation_state,
)
from rob2_kit.application.evidence_runtime import (
    UnsupportedV3EvidenceNavigationIntent,
    V3EvidenceNavigationRuntime,
    V3EvidenceContextMismatch,
    V3EvidencePageTriageRequest,
    V3EvidenceSearchContinuationRequest,
    V3EvidenceSearchRequest,
    V3EvidenceSourceScopeMismatch,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceScope,
    EvidenceSearchCandidate,
    EvidenceSearchIndex,
    EvidenceSearchPage,
    EvidenceSearchPolicy,
    EvidenceReadPolicy,
    EvidenceSearchReadAction,
    EvidenceSearchTraversalCost,
    EvidenceSearchTriageFlags,
    SearchContinuationReason,
    SearchQuery,
)
from rob2_kit.evidence.workflow import (
    V3AcquisitionAttemptReceipt,
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
    V3EvidenceWorkflowState,
    V3TriageKind,
    V3TriggerDisposition,
    V3TriggerDispositionKind,
    v3_coverage_progress,
)


class _Search:
    def __init__(
        self,
        *,
        snapshot_hash: str,
        policy: EvidenceSearchPolicy,
        sources: tuple[EvidenceContextInventorySource, ...],
        page_count: int = 1,
        include_candidates: bool = False,
    ) -> None:
        self.snapshot_hash = snapshot_hash
        self.policy = policy
        self.sources = {item.source_id: item for item in sources}
        self.page_count = page_count
        self.include_candidates = include_candidates
        self.calls: list[tuple[SearchQuery, EvidenceScope | None]] = []

    def search_page(
        self,
        query: SearchQuery,
        *,
        issuance_context: str | None = None,
        continuation: str | None = None,
        scope: EvidenceScope | None = None,
        continue_reason: SearchContinuationReason | None = None,
        continue_rationale: str | None = None,
        policy: EvidenceSearchPolicy | None = None,
    ) -> EvidenceSearchPage:
        assert policy == self.policy
        self.calls.append((query, scope, issuance_context))
        call_number = len(self.calls)
        page_number = 2 if continuation is not None else 1
        policy_hash = canonical_hash(self.policy)
        candidates = () if not self.include_candidates else (self._candidate(query, call_number),)
        return EvidenceSearchPage(
            snapshot_hash=self.snapshot_hash,
            query_hash=canonical_hash(query),
            policy_id=self.policy.policy_id,
            policy_hash=policy_hash,
            page_handle=f"page:{call_number}",
            continuation=(f"continuation:{page_number}" if page_number < self.page_count else None),
            candidate_ids=tuple(item.candidate_id for item in candidates),
            candidates=candidates,
            page_number=page_number,
            total_page_count=self.page_count,
            remaining_page_count=self.page_count - page_number,
            returned_candidate_count=len(candidates),
            prior_candidate_count=(page_number - 1 if self.include_candidates else 0),
            total_candidate_count=(self.page_count if self.include_candidates else 0),
            remaining_candidate_count=(
                self.page_count - page_number if self.include_candidates else 0
            ),
            estimated_response_tokens=0,
            serialized_response_bytes=0,
            omitted_candidate_count=0,
            omitted_estimated_response_bytes=0,
            traversal_complete=page_number == self.page_count,
            traversal_cost=EvidenceSearchTraversalCost(
                classification="ordinary",
                projected_page_count=1,
                response_bytes_upper_bound=0,
                estimated_tokens_upper_bound=0,
                current_cumulative_response_bytes_upper_bound=0,
                current_cumulative_estimated_tokens_upper_bound=0,
                projected_cumulative_response_bytes_upper_bound=0,
                projected_cumulative_estimated_tokens_upper_bound=0,
            ),
            condition="zero_hits",
        )

    def _candidate(self, query: SearchQuery, page_number: int) -> EvidenceSearchCandidate:
        source = self.sources[query.source_ids[0]]
        snippet = "allocation"
        location_handle = f"location:{page_number}"
        return EvidenceSearchCandidate(
            candidate_id=f"candidate:{page_number}",
            exposure_id=f"exposure:{page_number}",
            canonical_unit_id=f"unit:{page_number}",
            location_handle=location_handle,
            source_id=source.source_id,
            source_label=source.source_id,
            source_artifact_hash=source.source_artifact_hash,
            parse_id=source.parse_id,
            canonicalization_version="1.0.0",
            page=page_number,
            kind="paragraph",
            source_role=SourceRole.PRIMARY_REPORT,
            source_snippet=snippet,
            displayed_match_spans=((0, len(snippet)),),
            displayed_match_count=1,
            undisplayed_match_count=0,
            canonical_start=0,
            canonical_end=len(snippet),
            left_omitted_character_count=0,
            right_omitted_character_count=0,
            triage_flags=EvidenceSearchTriageFlags(),
            estimated_full_unit_bytes=len(snippet),
            estimated_full_unit_tokens=3,
            read_evidence=EvidenceSearchReadAction(location_handle=location_handle),
        )


def _obligation(*, structural: bool = False, triggered: bool = False) -> EvidenceSearchObligation:
    intent = {
        "id": "intent:runtime:seed",
        "kind": "structural_read" if structural else "search",
        "structural_targets": ["methods"] if structural else [],
        "terms": [] if structural else ["allocation"],
    }
    return EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": "sq:runtime:test",
            "propositions": [
                {
                    "id": "proposition:runtime:test",
                    "statement": "Runtime test proposition.",
                    "accepted_source_roles": (
                        ["primary_report", "protocol"] if triggered else ["primary_report"]
                    ),
                    "evidence_passes": [
                        {
                            "id": "pass:runtime:seed",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": "stage:runtime:seed",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [intent],
                                },
                                *(
                                    [
                                        {
                                            "id": "stage:runtime:wider",
                                            "applicable_source_roles": [
                                                "primary_report",
                                                "protocol",
                                            ],
                                            "activation": "triggered",
                                            "activation_trigger_ids": ["trigger:runtime:wider"],
                                            "navigation_intents": [
                                                {
                                                    "id": "intent:runtime:wider",
                                                    "kind": "search",
                                                    "terms": ["allocation"],
                                                }
                                            ],
                                        }
                                    ]
                                    if triggered
                                    else []
                                ),
                            ],
                        },
                        {
                            "id": "pass:runtime:contradiction",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": "stage:runtime:contradiction",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:runtime:contradiction",
                                            "kind": "search",
                                            "terms": ["allocation"],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
            "escalation_triggers": (
                [
                    {
                        "id": "trigger:runtime:wider",
                        "condition": "no_direct_evidence",
                        "source_stage_id": "stage:runtime:seed",
                        "target_stage_id": "stage:runtime:wider",
                    }
                ]
                if triggered
                else []
            ),
        }
    )


def _runtime(
    tmp_path: Path,
    *,
    source_count: int = 1,
    source_available: bool = True,
    structural: bool = False,
    triggered: bool = False,
    page_count: int = 1,
    include_candidates: bool = False,
):
    obligation = _obligation(structural=structural, triggered=triggered)
    if triggered:
        source_specs = (
            ("source:runtime:primary", (SourceRole.PRIMARY_REPORT,)),
            ("source:runtime:protocol", (SourceRole.PROTOCOL,)),
        )
    else:
        source_specs = tuple(
            (source_id, (SourceRole.PRIMARY_REPORT,))
            for source_id in (
                ("source:runtime",)
                if source_count == 1
                else tuple(f"source:runtime:{number:02d}" for number in range(source_count))
            )
        )
    source_ids = tuple(source_id for source_id, _ in source_specs)
    inventory_sources = tuple(
        EvidenceContextInventorySource(
            source_id=source_id,
            roles=roles,
            source_artifact_hash=canonical_hash({"source": source_id}),
            parse_id=f"parse:{source_id[7:]}",
            parse_output_hash=canonical_hash({"parse": source_id}),
            availability=(
                SourceAvailability.ACQUIRED if source_available else SourceAvailability.UNAVAILABLE
            ),
            processing=SourceProcessing.USABLE,
            criticality=SourceCriticality.EXPECTED,
            page_count=1,
            indexed_unit_count=1,
            unit_orientation=EvidenceContextUnitOrientation.INDEXED_UNITS,
        )
        for source_id, roles in source_specs
    )
    if source_count == 0:
        inventory_sources = ()
    context = materialize_evidence_context(
        obligation,
        EvidenceContextInventory(inventory_id="inventory:runtime", sources=inventory_sources),
    )
    policy = EvidenceSearchPolicy()
    read_policy = EvidenceReadPolicy()
    snapshot_hash = canonical_hash({"snapshot": "runtime"})
    workflow = V3EvidenceWorkflowState(
        run_id="run:runtime",
        result_id="result:runtime",
        domain_id="domain:runtime",
        question_id=context.question_id,
        snapshot_hash=snapshot_hash,
        obligation_revision_id="revision:runtime",
        obligation=context.obligation,
        obligation_hash=context.obligation_hash,
        inventory_snapshot_hash=context.inventory_snapshot_hash,
        authorized_inventory=context.authorized_inventory,
        search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy),
        read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy),
        visual_policy_id="policy:runtime:visual",
        visual_policy_hash=canonical_hash({"visual": "runtime"}),
        stage_scopes=context.stage_scopes,
    )
    issued_acquisition_receipt = None
    if not source_available:
        issued_acquisition_receipt = _acquisition_receipt(workflow, "stage:runtime:seed")
        workflow = workflow.model_copy(
            update={
                "issued_acquisition_receipt_hashes": (
                    (
                        issued_acquisition_receipt.issuance_id,
                        issued_acquisition_receipt.receipt_hash,
                    ),
                )
            }
        )
    search = _Search(
        snapshot_hash=snapshot_hash,
        policy=policy,
        sources=inventory_sources,
        page_count=page_count,
        include_candidates=include_candidates,
    )
    runtime = V3EvidenceNavigationRuntime(
        context=context,
        workflow=workflow,
        store=V3EvidenceNavigationStore(tmp_path),
        search=search,
        search_policy=policy,
    )
    return runtime, search, source_ids, issued_acquisition_receipt


def _request(
    content_hash: str,
    *,
    source_ids: tuple[str, ...] = ("source:runtime",),
    stage: str = "stage:runtime:seed",
    intent: str = "intent:runtime:seed",
):
    return V3EvidenceSearchRequest(
        expected_content_hash=content_hash,
        proposition_id="proposition:runtime:test",
        pass_id=(
            "pass:runtime:seed"
            if stage.endswith(("seed", "wider"))
            else "pass:runtime:contradiction"
        ),
        stage_id=stage,
        intent_id=intent,
        attempt_id=f"attempt:{stage[6:]}",
        query=SearchQuery(terms=("allocation",), source_ids=source_ids),
    )


def test_runtime_uses_engine_scope_and_rejects_source_mismatch(tmp_path: Path) -> None:
    runtime, search, _, _ = _runtime(tmp_path)
    initial = runtime.initialize()
    with pytest.raises(V3EvidenceSourceScopeMismatch):
        runtime.search_page(
            _request(initial.content_hash).model_copy(
                update={
                    "query": SearchQuery(
                        terms=("allocation",), source_ids=("source:outside-scope",)
                    )
                }
            )
        )

    result = runtime.search_page(
        _request(initial.content_hash).model_copy(
            update={"query": SearchQuery(terms=("allocation",))}
        )
    )
    assert search.calls[0][0].source_ids == ("source:runtime",)
    assert search.calls[0][1].source_ids == ("source:runtime",)
    assert result.page is not None


def test_runtime_persists_traversal_triage_and_outcomes_with_optimistic_writes(
    tmp_path: Path,
) -> None:
    runtime, _, _, _ = _runtime(tmp_path)
    initial = runtime.initialize()
    first = runtime.search_page(_request(initial.content_hash))
    with pytest.raises(ConcurrentEvidenceNavigationUpdate):
        runtime.submit_page_triage(
            V3EvidencePageTriageRequest(
                expected_content_hash=initial.content_hash,
                submission_id="triage:stale",
                attempt_id="attempt:runtime:seed",
                page_handles=("page:1",),
                revisions=(),
            )
        )
    triaged = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=first.state.content_hash,
            submission_id="triage:seed",
            attempt_id="attempt:runtime:seed",
            page_handles=("page:1",),
            revisions=(),
        )
    )
    closed = runtime.submit_stage_outcome(
        expected_content_hash=triaged.state.content_hash,
        submission=_outcome(triaged.state.workflow, "stage:runtime:seed"),
    )
    assert closed.progress["question_ready"] is False
    contradiction = runtime.search_page(
        _request(
            closed.state.content_hash,
            stage="stage:runtime:contradiction",
            intent="intent:runtime:contradiction",
        )
    )
    contradiction_triage = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=contradiction.state.content_hash,
            submission_id="triage:contradiction",
            attempt_id="attempt:runtime:contradiction",
            page_handles=("page:2",),
            revisions=(),
        )
    )
    complete = runtime.submit_stage_outcome(
        expected_content_hash=contradiction_triage.state.content_hash,
        submission=_outcome(contradiction_triage.state.workflow, "stage:runtime:contradiction"),
    )
    assert complete.progress["question_ready"] is True


def test_runtime_empty_scope_is_audited_without_an_unscoped_search(tmp_path: Path) -> None:
    runtime, search, _, _ = _runtime(tmp_path, source_count=0)
    initial = runtime.initialize()
    request = _request(initial.content_hash).model_copy(
        update={"query": SearchQuery(terms=("allocation",), source_ids=())}
    )
    result = runtime.search_page(request)
    assert result.blockers == ("materialized_source_scope_empty",)
    assert not search.calls
    assert not result.state.workflow.attempts


def test_runtime_rejects_non_search_intent_with_a_typed_error(tmp_path: Path) -> None:
    runtime, _, _, _ = _runtime(tmp_path, structural=True)
    initial = runtime.initialize()
    with pytest.raises(UnsupportedV3EvidenceNavigationIntent):
        runtime.search_page(_request(initial.content_hash))


def test_runtime_continuation_reuses_the_selected_query_scope_and_records_page_two(
    tmp_path: Path,
) -> None:
    runtime, search, source_ids, _ = _runtime(tmp_path, page_count=2)
    initial = runtime.initialize()
    first = runtime.search_page(_request(initial.content_hash, source_ids=source_ids))
    second = runtime.continue_search_page(
        V3EvidenceSearchContinuationRequest(
            expected_content_hash=first.state.content_hash,
            attempt_id="attempt:runtime:seed",
            continuation="continuation:1",
        )
    )
    assert search.calls[1] == search.calls[0]
    assert second.page is not None and second.page.page_number == 2
    assert [page.page_number for page in second.state.workflow.pages] == [1, 2]


def test_runtime_supersession_preserves_old_candidates_until_they_are_triaged(
    tmp_path: Path,
) -> None:
    runtime, _, source_ids, _ = _runtime(tmp_path, include_candidates=True)
    initial = runtime.initialize()
    first = runtime.search_page(_request(initial.content_hash, source_ids=source_ids))
    replacement = runtime.search_page(
        _request(first.state.content_hash, source_ids=source_ids).model_copy(
            update={
                "attempt_id": "attempt:runtime:replacement",
                "query": SearchQuery(terms=("concealment",), source_ids=source_ids),
                "supersede_attempt_id": "attempt:runtime:seed",
                "supersession_rationale": "Try the issued synonym.",
            }
        )
    )
    assert [item.kind.value for item in replacement.state.workflow.attempts] == [
        "superseded",
        "selected",
    ]
    replacement_triage = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=replacement.state.content_hash,
            submission_id="triage:replacement",
            attempt_id="attempt:runtime:replacement",
            page_handles=("page:2",),
            revisions=(
                _retained_revision(
                    "revision:replacement",
                    "attempt:runtime:replacement",
                    "page:2",
                    "candidate:2",
                ),
            ),
        )
    )
    assert "superseded_search_candidate_undispositioned" in _intent_blockers(
        replacement_triage.state.workflow
    )
    old_triage = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=replacement_triage.state.content_hash,
            submission_id="triage:old",
            attempt_id="attempt:runtime:seed",
            page_handles=("page:1",),
            revisions=(
                _retained_revision("revision:old", "attempt:runtime:seed", "page:1", "candidate:1"),
            ),
        )
    )
    assert "superseded_search_candidate_undispositioned" not in _intent_blockers(
        old_triage.state.workflow
    )


def test_runtime_rejects_inactive_triggered_search_then_uses_wider_scope_after_escalation(
    tmp_path: Path,
) -> None:
    runtime, search, source_ids, _ = _runtime(tmp_path, triggered=True)
    initial = runtime.initialize()
    wider = _request(
        initial.content_hash,
        source_ids=source_ids,
        stage="stage:runtime:wider",
        intent="intent:runtime:wider",
    )
    with pytest.raises(ValueError, match="inactive triggered"):
        runtime.search_page(wider)

    seed = runtime.search_page(
        _request(initial.content_hash, source_ids=("source:runtime:primary",))
    )
    triaged = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=seed.state.content_hash,
            submission_id="triage:trigger-seed",
            attempt_id="attempt:runtime:seed",
            page_handles=("page:1",),
            revisions=(),
        )
    )
    escalated = runtime.submit_stage_outcome(
        expected_content_hash=triaged.state.content_hash,
        submission=_outcome(
            triaged.state.workflow,
            "stage:runtime:seed",
            kind="escalation_required",
            triggers=(
                V3TriggerDisposition(
                    trigger_id="trigger:runtime:wider",
                    kind=V3TriggerDispositionKind.TRUE,
                    rationale="Direct evidence requires broader coverage.",
                ),
            ),
        ),
    )
    wider = runtime.search_page(
        wider.model_copy(update={"expected_content_hash": escalated.state.content_hash})
    )
    assert search.calls[-1][0].source_ids == source_ids
    assert search.calls[-1][1].source_ids == source_ids
    assert wider.page is not None


def test_runtime_audits_empty_scope_as_source_unavailable_with_an_explicit_blocker(
    tmp_path: Path,
) -> None:
    runtime, _, _, receipt = _runtime(tmp_path, source_available=False)
    assert receipt is not None
    initial = runtime.initialize()
    empty = runtime.search_page(
        _request(initial.content_hash).model_copy(
            update={"query": SearchQuery(terms=("allocation",), source_ids=())}
        )
    )
    outcome = _outcome(
        empty.state.workflow,
        "stage:runtime:seed",
        kind="source_unavailable_after_attempt",
        acquisition_receipt_id=receipt.receipt_id,
    )
    with pytest.raises(ValueError, match="recorded acquisition receipt"):
        runtime.submit_stage_outcome(
            expected_content_hash=empty.state.content_hash,
            submission=outcome,
        )
    with pytest.raises(ValueError, match="forged or stale"):
        runtime.record_acquisition_attempt(
            expected_content_hash=empty.state.content_hash,
            receipt=receipt.model_copy(update={"unavailable_source_ids": ("source:forged",)}),
        )
    wrong_source_payload = receipt.model_dump(mode="json")
    wrong_source_payload["unavailable_source_ids"] = ("source:wrong",)
    wrong_source_payload["receipt_hash"] = None
    wrong_source = V3AcquisitionAttemptReceipt.model_validate(
        wrong_source_payload | {"receipt_hash": canonical_hash(wrong_source_payload)}
    )
    with pytest.raises(ValueError, match="exact unavailable Source"):
        runtime.record_acquisition_attempt(
            expected_content_hash=empty.state.content_hash,
            receipt=wrong_source,
        )
    stale_payload = receipt.model_dump(mode="json")
    stale_payload["inventory_snapshot_hash"] = canonical_hash({"stale": "inventory"})
    stale_payload["receipt_hash"] = None
    stale = V3AcquisitionAttemptReceipt.model_validate(
        stale_payload | {"receipt_hash": canonical_hash(stale_payload)}
    )
    with pytest.raises(ValueError, match="stale work, scope, or inventory"):
        runtime.record_acquisition_attempt(
            expected_content_hash=empty.state.content_hash,
            receipt=stale,
        )
    recorded = runtime.record_acquisition_attempt(
        expected_content_hash=empty.state.content_hash,
        receipt=receipt,
    )
    closed = runtime.submit_stage_outcome(
        expected_content_hash=recorded.state.content_hash,
        submission=outcome,
    )
    assert _stage_blockers(closed.state.workflow) == ("source_unavailable_after_attempt",)


def test_runtime_resolves_omitted_acquisition_receipt_from_exact_stage(tmp_path: Path) -> None:
    runtime, _, _, receipt = _runtime(tmp_path, source_available=False)
    assert receipt is not None
    initial = runtime.initialize()
    recorded = runtime.record_acquisition_attempt(
        expected_content_hash=initial.content_hash,
        receipt=receipt,
    )
    closed = runtime.submit_stage_outcome(
        expected_content_hash=recorded.state.content_hash,
        submission=_outcome(
            recorded.state.workflow,
            "stage:runtime:seed",
            kind="source_unavailable_after_attempt",
        ),
    )
    persisted = closed.state.workflow.stage_outcomes[-1]
    assert persisted.acquisition_receipt_id == receipt.receipt_id
    assert _stage_blockers(closed.state.workflow) == ("source_unavailable_after_attempt",)


def test_runtime_audits_exhaustive_semantic_uncertainty_with_an_explicit_blocker(
    tmp_path: Path,
) -> None:
    runtime, _, source_ids, _ = _runtime(tmp_path, include_candidates=True)
    initial = runtime.initialize()
    searched = runtime.search_page(_request(initial.content_hash, source_ids=source_ids))
    triaged = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=searched.state.content_hash,
            submission_id="triage:unresolved",
            attempt_id="attempt:runtime:seed",
            page_handles=("page:1",),
            revisions=(
                V3CandidateTriageRevision(
                    revision_id="revision:unresolved",
                    attempt_id="attempt:runtime:seed",
                    sq_id="sq:runtime:test",
                    page_handle="page:1",
                    candidate_id="candidate:1",
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="The source meaning remains materially ambiguous.",
                ),
            ),
        )
    )
    closed = runtime.submit_stage_outcome(
        expected_content_hash=triaged.state.content_hash,
        submission=_outcome(
            triaged.state.workflow,
            "stage:runtime:seed",
            kind="semantic_uncertainty_unresolved",
        ),
    )
    assert _stage_blockers(closed.state.workflow) == ("semantic_uncertainty_unresolved",)


def test_runtime_preserves_an_exact_authorized_scope_larger_than_sixty_four_sources(
    tmp_path: Path,
) -> None:
    runtime, search, source_ids, _ = _runtime(tmp_path, source_count=65)
    initial = runtime.initialize()
    runtime.search_page(_request(initial.content_hash, source_ids=source_ids))
    assert search.calls[0][0].source_ids == source_ids
    assert search.calls[0][1].source_ids == source_ids


def test_real_search_index_handles_scope_larger_than_sqlite_variable_limit(tmp_path: Path) -> None:
    source_ids = tuple(f"source:sqlite:{number:05d}" for number in range(33_000))
    parse_ids = tuple(f"parse:sqlite:{number:05d}" for number in range(33_000))
    index = EvidenceSearchIndex(tmp_path / "large-scope.sqlite3")
    index.replace_units(
        (
            CanonicalEvidenceUnit(
                unit_id="unit:sqlite:one",
                source_id=source_ids[0],
                source_artifact_hash=canonical_hash({"source": "sqlite"}),
                parse_id=parse_ids[0],
                page=1,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="Allocation concealment was centrally controlled.",
            ),
        )
    )
    page = index.search_page(
        SearchQuery(terms=("allocation",), source_ids=source_ids),
        scope=EvidenceScope(source_ids=source_ids, parse_ids=parse_ids),
    )
    assert page.candidate_ids and page.candidates[0].source_id == source_ids[0]


def _outcome(
    workflow: V3EvidenceWorkflowState,
    stage_id: str,
    *,
    kind: str = "obligation_satisfied",
    triggers: tuple[V3TriggerDisposition, ...] = (),
    acquisition_receipt_id: str | None = None,
) -> V3EvidenceStageOutcomeSubmission:
    scope = next(item for item in workflow.stage_scopes if item.stage_id == stage_id)
    payload = {
        "submission_id": f"outcome:{stage_id[6:]}",
        "run_id": workflow.run_id,
        "result_id": workflow.result_id,
        "domain_id": workflow.domain_id,
        "question_id": workflow.question_id,
        "obligation_revision_id": workflow.obligation_revision_id,
        "obligation_hash": workflow.obligation_hash,
        "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
        "proposition_id": scope.proposition_id,
        "pass_id": scope.pass_id,
        "stage_id": stage_id,
        "materialized_scope_id": scope.scope_id,
        "outcome_kind": kind,
        "rationale": "The bounded Search traversal found no candidates.",
        "trigger_dispositions": tuple(item.model_dump(mode="json") for item in triggers),
        "acquisition_receipt_id": acquisition_receipt_id,
        "content_hash": None,
    }
    return V3EvidenceStageOutcomeSubmission.model_validate(
        payload | {"content_hash": canonical_hash(payload)}
    )


def _retained_revision(
    revision_id: str, attempt_id: str, page_handle: str, candidate_id: str
) -> V3CandidateTriageRevision:
    return V3CandidateTriageRevision(
        revision_id=revision_id,
        attempt_id=attempt_id,
        sq_id="sq:runtime:test",
        page_handle=page_handle,
        candidate_id=candidate_id,
        kind=V3TriageKind.RETAINED,
        read_view_receipt=f"read:{candidate_id}",
    )


def _acquisition_receipt(
    workflow: V3EvidenceWorkflowState, stage_id: str
) -> V3AcquisitionAttemptReceipt:
    scope = next(item for item in workflow.stage_scopes if item.stage_id == stage_id)
    source_ids = tuple(
        source.source_id
        for source in workflow.authorized_inventory
        if source.availability is SourceAvailability.UNAVAILABLE
    )
    limitation_hash = canonical_hash(
        tuple(
            item.model_dump(mode="json")
            for item in scope.role_limitations
            if item.kind.value == "source_unavailable"
        )
    )
    payload = {
        "receipt_id": "acquisition:runtime:seed",
        "issuance_id": "issuance:acquisition:runtime:seed",
        "run_id": workflow.run_id,
        "result_id": workflow.result_id,
        "domain_id": workflow.domain_id,
        "question_id": workflow.question_id,
        "proposition_id": scope.proposition_id,
        "pass_id": scope.pass_id,
        "stage_id": scope.stage_id,
        "materialized_scope_id": scope.scope_id,
        "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
        "unavailable_source_ids": source_ids,
        "limitation_hash": limitation_hash,
        "receipt_hash": None,
    }
    return V3AcquisitionAttemptReceipt.model_validate(
        payload | {"receipt_hash": canonical_hash(payload)}
    )


def _intent_blockers(workflow: V3EvidenceWorkflowState) -> tuple[str, ...]:
    item = v3_coverage_progress(workflow)["propositions"][0]["passes"][0]["stages"][0]
    return item["intents"][0]["blockers"]


def _stage_blockers(workflow: V3EvidenceWorkflowState) -> tuple[str, ...]:
    return v3_coverage_progress(workflow)["propositions"][0]["passes"][0]["stages"][0]["blockers"]


@pytest.mark.parametrize("policy_kind", ("search", "read"))
def test_runtime_rejects_prior_policy_state_before_search_or_mutation(
    tmp_path: Path, policy_kind: str
) -> None:
    runtime, search, _, _ = _runtime(tmp_path)
    created = runtime.initialize()
    workflow = created.workflow
    if policy_kind == "search":
        prior = EvidenceSearchPolicy(policy_id="policy:evidence-search-" + "3.0.0")
        workflow = workflow.model_copy(
            update={"search_policy_id": prior.policy_id, "search_policy_hash": canonical_hash(prior)}
        )
    else:
        prior = EvidenceReadPolicy(policy_id="policy:evidence-read-" + "2.0.0")
        workflow = workflow.model_copy(
            update={"read_policy_id": prior.policy_id, "read_policy_hash": canonical_hash(prior)}
        )
    stale = new_v3_navigation_state(workflow=workflow)
    runtime._store.save(stale, expected_content_hash=created.content_hash)
    with pytest.raises(V3EvidenceContextMismatch, match="supersede Preparation"):
        runtime.load()
    with pytest.raises(V3EvidenceContextMismatch, match="supersede Preparation"):
        runtime.search_page(_request(stale.content_hash))
    assert search.calls == []
