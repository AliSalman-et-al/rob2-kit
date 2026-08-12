"""Focused durable-session coverage for the private v3 bridge seam."""
# ruff: noqa: E501

from pathlib import Path

import pytest

from rob2_kit.application.active_question_frontier import (
    QuestionAnswerCommitStep,
    QuestionDiagnosticStop,
    QuestionEvidenceBundleBinding,
    active_question_frontier,
    evidence_closure_from_workflow,
    evidence_diagnostic_from_workflow,
)
from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    EvidenceContextInventorySource,
    EvidenceContextUnitOrientation,
    materialize_evidence_context,
)
from rob2_kit.application.evidence_navigation import (
    V3EvidenceNavigationStore,
    new_v3_navigation_state,
)
from rob2_kit.application.question_evidence_session import (
    QuestionEvidenceSessionContextMismatch,
    QuestionEvidenceSessionService,
    QuestionEvidenceSessionStore,
    StaleQuestionEvidenceSession,
    new_question_evidence_session,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import EvidenceSearchPolicy, SearchQuery
from rob2_kit.evidence.workflow import (
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
    V3ExposedPage,
    V3NavigationCompletionReceipt,
    V3PageExposure,
    V3SearchAttempt,
    V3TriageKind,
)
from rob2_kit.logic.packs import LogicPack, load_guidance_pack, load_logic_pack


class _Search:
    """The session initializes runtimes without invoking retrieval."""

    def search_page(self, *_args, **_kwargs):  # pragma: no cover - defensive test double
        raise AssertionError("session initialization must not search")


PACK_ROOT = Path(__file__).parents[1] / "packs"


def _session(
    tmp_path: Path,
    *,
    inventory_revision_id: str = "revision:inventory:one",
    unavailable: bool = False,
):
    logic = load_logic_pack(PACK_ROOT / "logic" / "rob2-parallel-assignment-2019.1.yaml")
    guidance = load_guidance_pack(
        PACK_ROOT / "guidance" / "rob2-parallel-assignment-en-2019.1.yaml"
    )
    domain_id = "domain:randomization"
    domain = next(item for item in logic.domains if item.id == domain_id)
    obligations = tuple(
        item for item in guidance.obligations if item.question_id in domain.question_ids
    )
    sources = tuple(
        EvidenceContextInventorySource(
            source_id=f"source:session:{number:02d}",
            roles=(SourceRole.PRIMARY_REPORT,),
            source_artifact_hash=(None if unavailable else canonical_hash({"source": number})),
            parse_id=(None if unavailable else f"parse:session:{number:02d}"),
            parse_output_hash=(None if unavailable else canonical_hash({"parse": number})),
            availability=(
                SourceAvailability.UNAVAILABLE if unavailable else SourceAvailability.ACQUIRED
            ),
            processing=(SourceProcessing.NOT_ATTEMPTED if unavailable else SourceProcessing.USABLE),
            criticality=SourceCriticality.EXPECTED,
            page_count=1,
            indexed_unit_count=1,
            unit_orientation=EvidenceContextUnitOrientation.INDEXED_UNITS,
        )
        for number in range(25)
    )
    state = new_question_evidence_session(
        run_id="run:session",
        result_id="result:session",
        domain_id=domain_id,
        logic_pack=logic,
        guidance_release_id=guidance.release_id,
        obligations=obligations,
        obligation_revision_id="revision:guidance:one",
        inventory_revision_id=inventory_revision_id,
        inventory=EvidenceContextInventory(inventory_id="inventory:session", sources=sources),
    )
    return state, QuestionEvidenceSessionService(
        session=state,
        store=QuestionEvidenceSessionStore(tmp_path),
        navigation_store=V3EvidenceNavigationStore(tmp_path),
        search=_Search(),
    )


def test_session_initializes_full_revision_keyed_history_and_all_context_pages(
    tmp_path: Path,
) -> None:
    state, service = _session(tmp_path)

    # Projection is a pure deterministic read.  It may describe an
    # uninitialized runtime, but cannot create one as a hidden side effect.
    unprovisioned = service.project(state)
    assert all(item.runtime.navigation_state_hash is None for item in unprovisioned.active_contexts)
    assert not (tmp_path / ".rob2" / "evidence-navigation-v3").exists()

    projection = service.initialize()

    assert projection.status == "active"
    assert service.load() == state
    assert projection.active_contexts
    # The complete inventory is retained through deterministic fixed pages;
    # no public-sized source truncation is encoded in this private seam.
    pages = projection.active_contexts[0].context.pages
    assert len(pages) > 1
    assert pages[-1].remaining_page_count == 0
    source_ids = [
        entry.source_id for page in pages for entry in page.entries if entry.source_id is not None
    ]
    assert source_ids == [f"source:session:{number:02d}" for number in range(25)]
    first = service.runtime_for_question(projection.active_contexts[0].question_id)
    replay = service.runtime_for_question(projection.active_contexts[0].question_id)
    assert replay.state == first.state
    assert service.initialize() == projection


def test_session_save_is_optimistic_and_revision_keys_coexist(tmp_path: Path) -> None:
    first, first_service = _session(tmp_path)
    first_service.initialize()

    with pytest.raises(StaleQuestionEvidenceSession):
        first_service._store.save(first)

    second, second_service = _session(tmp_path, inventory_revision_id="revision:inventory:two")
    second_service.initialize()

    assert first_service.load().inventory_revision_id == "revision:inventory:one"
    assert second_service.load().inventory_revision_id == "revision:inventory:two"


def test_session_provisions_exact_unavailable_source_acquisition_receipts(
    tmp_path: Path,
) -> None:
    _, service = _session(tmp_path, unavailable=True)
    projection = service.initialize()
    runtime = service.runtime_for_question(projection.active_contexts[0].question_id)

    assert runtime.state.workflow.acquisition_receipts
    assert {item.issuance_id for item in runtime.state.workflow.acquisition_receipts} == {
        item[0] for item in runtime.state.workflow.issued_acquisition_receipt_hashes
    }
    assert all(
        item.inventory_snapshot_hash == runtime.context.inventory_snapshot_hash
        for item in runtime.state.workflow.acquisition_receipts
    )


def test_session_rejects_context_factory_outside_its_exact_revision(tmp_path: Path) -> None:
    state, _ = _session(tmp_path)

    def wrong_context(obligation, inventory):
        context = materialize_evidence_context(obligation, inventory)
        return context.model_copy(update={"inventory_id": "inventory:other"})

    service = QuestionEvidenceSessionService(
        session=state,
        store=QuestionEvidenceSessionStore(tmp_path),
        navigation_store=V3EvidenceNavigationStore(tmp_path),
        search=_Search(),
        context_factory=wrong_context,
        search_policy=EvidenceSearchPolicy(),
    )
    with pytest.raises(QuestionEvidenceSessionContextMismatch, match="outside the exact session"):
        service.initialize()


def _minimal_logic(*, conditional: bool) -> LogicPack:
    base = load_logic_pack(PACK_ROOT / "logic" / "rob2-parallel-assignment-2019.1.yaml")
    payload = base.model_dump(exclude={"content_hash"})
    second = {"id": "sq:session:second"}
    if conditional:
        second["active_if"] = {
            "op": "answer_in",
            "question_id": "sq:session:first",
            "answers": ["yes"],
        }
    payload.update(
        {
            "questions": [{"id": "sq:session:first"}, second],
            "domains": [
                {
                    "id": "domain:session",
                    "question_ids": ["sq:session:first", "sq:session:second"],
                    "judgment_rules": [
                        {
                            "id": "rule:session:domain",
                            "when": {
                                "op": "answer_in",
                                "question_id": "sq:session:first",
                                "answers": [
                                    "yes",
                                    "no",
                                    "probably_yes",
                                    "probably_no",
                                    "no_information",
                                ],
                            },
                            "judgment": "low",
                        }
                    ],
                }
            ],
            "assessor_inputs": [],
            "overall_rules": [
                {
                    "id": "rule:session:overall",
                    "when": {"op": "domain_all", "judgments": ["low"]},
                    "judgment": "low",
                }
            ],
            "inventory": [
                "sq:session:first",
                "sq:session:second",
                "domain:session",
                "rule:session:domain",
                "rule:session:overall",
            ],
        }
    )
    return LogicPack.model_validate(payload)


def _obligation(question_id: str) -> EvidenceSearchObligation:
    return EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": question_id,
            "propositions": [
                {
                    "id": f"proposition:session:{question_id[3:]}",
                    "statement": "Test.",
                    "accepted_source_roles": ["primary_report"],
                    "evidence_passes": [
                        {
                            "id": f"pass:session:{question_id[3:]}:seed",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": f"stage:session:{question_id[3:]}:seed",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": f"intent:session:{question_id[3:]}:seed",
                                            "kind": "structural_read",
                                            "structural_targets": ["methods"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": f"pass:session:{question_id[3:]}:contra",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": f"stage:session:{question_id[3:]}:contra",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": f"intent:session:{question_id[3:]}:contra",
                                            "kind": "structural_read",
                                            "structural_targets": ["results"],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def _search_obligation(question_id: str) -> EvidenceSearchObligation:
    payload = _obligation(question_id).model_dump(mode="json")
    for evidence_pass in payload["propositions"][0]["evidence_passes"]:
        intent = evidence_pass["coverage_stages"][0]["navigation_intents"][0]
        intent_id = intent["id"]
        intent.clear()
        intent.update({"id": intent_id, "kind": "search", "terms": ["term"]})
    return EvidenceSearchObligation.model_validate(payload)


def _two_peer_state(
    *,
    logic: LogicPack | None = None,
    obligations: tuple[EvidenceSearchObligation, ...] | None = None,
    obligation_revision_id: str = "revision:two-peer",
    inventory: EvidenceContextInventory | None = None,
):
    logic = logic or _minimal_logic(conditional=False)
    inventory = inventory or EvidenceContextInventory(
        inventory_id="inventory:two-peer",
        sources=(
            EvidenceContextInventorySource(
                source_id="source:two-peer",
                roles=(SourceRole.PRIMARY_REPORT,),
                source_artifact_hash=canonical_hash({"source": "two-peer"}),
                parse_id="parse:two-peer",
                parse_output_hash=canonical_hash({"parse": "two-peer"}),
                availability=SourceAvailability.ACQUIRED,
                processing=SourceProcessing.USABLE,
                criticality=SourceCriticality.EXPECTED,
                page_count=1,
                indexed_unit_count=1,
                unit_orientation=EvidenceContextUnitOrientation.INDEXED_UNITS,
            ),
        ),
    )
    obligations = obligations or (
        _obligation("sq:session:first"),
        _obligation("sq:session:second"),
    )
    return new_question_evidence_session(
        run_id="run:two-peer",
        result_id="result:two-peer",
        domain_id="domain:session",
        logic_pack=logic,
        guidance_release_id="guidance:two-peer",
        obligations=obligations,
        obligation_revision_id=obligation_revision_id,
        inventory_revision_id="inventory-revision:two-peer",
        inventory=inventory,
    )


def _service_for(
    state, store: QuestionEvidenceSessionStore, navigation: V3EvidenceNavigationStore
) -> QuestionEvidenceSessionService:
    return QuestionEvidenceSessionService(
        session=state, store=store, navigation_store=navigation, search=_Search()
    )


def _closed_workflow(service, navigation_store: V3EvidenceNavigationStore, question_id: str):
    opened = service.runtime_for_question(question_id)
    workflow = opened.state.workflow
    receipts, outcomes = [], []
    for scope in workflow.stage_scopes:
        stage = next(
            stage
            for prop in workflow.obligation.propositions
            if prop.id == scope.proposition_id
            for passed in prop.evidence_passes
            if passed.id == scope.pass_id
            for stage in passed.coverage_stages
            if stage.id == scope.stage_id
        )
        receipt_payload = {
            "receipt_id": f"receipt:{scope.scope_id[6:]}",
            "issuance_id": f"issuance:{scope.scope_id[6:]}",
            "proposition_id": scope.proposition_id,
            "pass_id": scope.pass_id,
            "stage_id": scope.stage_id,
            "intent_id": stage.navigation_intents[0].id,
            "kind": "structural_read",
            "source_scope_hash": scope.authorized_source_scope_hash,
            "snapshot_hash": workflow.snapshot_hash,
            "read_policy_id": workflow.read_policy_id,
            "read_policy_hash": workflow.read_policy_hash,
            "visual_policy_id": None,
            "visual_policy_hash": None,
            "receipt_hash": None,
        }
        receipt = V3NavigationCompletionReceipt.model_validate(
            receipt_payload | {"receipt_hash": canonical_hash(receipt_payload)}
        )
        receipts.append(receipt)
        outcome_payload = {
            "submission_id": f"outcome:{scope.scope_id[6:]}",
            "run_id": workflow.run_id,
            "result_id": workflow.result_id,
            "domain_id": workflow.domain_id,
            "question_id": question_id,
            "obligation_revision_id": workflow.obligation_revision_id,
            "obligation_hash": workflow.obligation_hash,
            "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
            "proposition_id": scope.proposition_id,
            "pass_id": scope.pass_id,
            "stage_id": scope.stage_id,
            "materialized_scope_id": scope.scope_id,
            "outcome_kind": "obligation_satisfied",
            "rationale": "Closed.",
            "trigger_dispositions": (),
            "acquisition_receipt_id": None,
            "content_hash": None,
        }
        outcomes.append(
            V3EvidenceStageOutcomeSubmission.model_validate(
                outcome_payload | {"content_hash": canonical_hash(outcome_payload)}
            )
        )
    closed = workflow.model_copy(
        update={
            "issued_receipt_hashes": tuple((r.issuance_id, r.receipt_hash) for r in receipts),
            "completion_receipts": tuple(receipts),
            "stage_outcomes": tuple(outcomes),
        }
    )
    navigation_store.save(
        new_v3_navigation_state(workflow=closed), expected_content_hash=opened.state.content_hash
    )
    return closed


def _bundle_binding(workflow, question_id: str) -> QuestionEvidenceBundleBinding:
    return QuestionEvidenceBundleBinding(
        question_id=question_id,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        bundle_revision_id=f"revision:bundle:{question_id[3:]}",
        bundle_content_hash=canonical_hash({"bundle": question_id}),
        supporting_evidence_ids=(f"claim:supporting:{question_id[3:]}",),
    )


def _semantic_terminal_workflow(
    service: QuestionEvidenceSessionService,
    navigation_store: V3EvidenceNavigationStore,
    question_id: str,
):
    """Persist a reducer-valid unresolved-search terminal workflow for one question."""

    runtime = service.runtime_for_question(question_id)
    workflow = runtime.state.workflow
    attempts, pages, exposures, triage, outcomes = [], [], [], [], []
    source = workflow.authorized_inventory[0]
    for index, scope in enumerate(workflow.stage_scopes, start=1):
        intent_id = next(
            stage.navigation_intents[0].id
            for proposition in workflow.obligation.propositions
            for evidence_pass in proposition.evidence_passes
            if evidence_pass.id == scope.pass_id
            for stage in evidence_pass.coverage_stages
            if stage.id == scope.stage_id
        )
        attempt = V3SearchAttempt(
            attempt_id=f"attempt:session:semantic:{index}",
            proposition_id=scope.proposition_id,
            pass_id=scope.pass_id,
            stage_id=scope.stage_id,
            intent_id=intent_id,
            query=SearchQuery(terms=("term",), source_ids=(source.source_id,)),
            query_hash=canonical_hash(SearchQuery(terms=("term",), source_ids=(source.source_id,))),
            source_scope_hash=scope.authorized_source_scope_hash,
        )
        attempts.append(attempt)
        outcome_kind = "obligation_satisfied" if index == 1 else "semantic_uncertainty_unresolved"
        page_handle = f"page:session:semantic:{index}"
        candidate_id = f"candidate:session:semantic:{index}"
        if outcome_kind == "obligation_satisfied":
            pages.append(
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_ids=(),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                )
            )
        else:
            pages.append(
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_ids=(candidate_id,),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                )
            )
            exposures.append(
                V3PageExposure(
                    attempt_id=attempt.attempt_id,
                    page_handle=page_handle,
                    candidate_id=candidate_id,
                    canonical_unit_id=f"unit:session:semantic:{index}",
                    location_handle=f"location:session:semantic:{index}",
                    source_id=source.source_id,
                    source_artifact_hash=source.source_artifact_hash,
                    parse_id=source.parse_id,
                    canonical_start=0,
                    canonical_end=1,
                    left_omitted_character_count=0,
                    right_omitted_character_count=0,
                    undisplayed_match_count=0,
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                    triage_flags={},
                )
            )
            triage.append(
                V3CandidateTriageRevision(
                    revision_id=f"triage:session:semantic:{index}",
                    attempt_id=attempt.attempt_id,
                    sq_id=question_id,
                    page_handle=page_handle,
                    candidate_id=candidate_id,
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="Material ambiguity remains.",
                )
            )
        outcome_payload = {
            "submission_id": f"outcome:session:semantic:{index}",
            "run_id": workflow.run_id,
            "result_id": workflow.result_id,
            "domain_id": workflow.domain_id,
            "question_id": workflow.question_id,
            "obligation_revision_id": workflow.obligation_revision_id,
            "obligation_hash": workflow.obligation_hash,
            "inventory_snapshot_hash": workflow.inventory_snapshot_hash,
            "proposition_id": scope.proposition_id,
            "pass_id": scope.pass_id,
            "stage_id": scope.stage_id,
            "materialized_scope_id": scope.scope_id,
            "outcome_kind": outcome_kind,
            "rationale": "Terminal evidence state.",
            "trigger_dispositions": (),
            "acquisition_receipt_id": None,
            "content_hash": None,
        }
        outcomes.append(
            V3EvidenceStageOutcomeSubmission.model_validate(
                outcome_payload | {"content_hash": canonical_hash(outcome_payload)}
            )
        )
    terminal = workflow.model_copy(
        update={
            "attempts": tuple(attempts),
            "pages": tuple(pages),
            "exposures": tuple(exposures),
            "triage_revisions": tuple(triage),
            "stage_outcomes": tuple(outcomes),
        }
    )
    navigation_store.save(
        new_v3_navigation_state(workflow=terminal), expected_content_hash=runtime.state.content_hash
    )
    return terminal


def test_answer_transition_activates_conditional_question_and_replays(tmp_path: Path) -> None:
    logic = _minimal_logic(conditional=True)
    inv = EvidenceContextInventory(
        inventory_id="inventory:min",
        sources=(
            EvidenceContextInventorySource(
                source_id="source:min",
                roles=(SourceRole.PRIMARY_REPORT,),
                source_artifact_hash=canonical_hash({"s": 1}),
                parse_id="parse:min",
                parse_output_hash=canonical_hash({"p": 1}),
                availability=SourceAvailability.ACQUIRED,
                processing=SourceProcessing.USABLE,
                criticality=SourceCriticality.EXPECTED,
                page_count=1,
                indexed_unit_count=1,
                unit_orientation=EvidenceContextUnitOrientation.INDEXED_UNITS,
            ),
        ),
    )
    state = new_question_evidence_session(
        run_id="run:min",
        result_id="result:min",
        domain_id="domain:session",
        logic_pack=logic,
        guidance_release_id="guidance:min",
        obligations=(_obligation("sq:session:first"), _obligation("sq:session:second")),
        obligation_revision_id="revision:min",
        inventory_revision_id="inventory-revision:min",
        inventory=inv,
    )
    store, nav = QuestionEvidenceSessionStore(tmp_path), V3EvidenceNavigationStore(tmp_path)
    service = QuestionEvidenceSessionService(
        session=state, store=store, navigation_store=nav, search=_Search()
    )
    before = service.initialize()
    workflow = _closed_workflow(service, nav, "sq:session:first")
    entry = active_question_frontier(service.load().ledger).entries[0]
    step = QuestionAnswerCommitStep(
        step_id="step:min",
        question_id="sq:session:first",
        answer="yes",
        rationale="Attributable answer rationale.",
        logic_pack_family_id=logic.family_id,
        logic_pack_release_id=logic.release_id,
        logic_pack_hash=logic.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, "sq:session:first"),
    )
    committed = service.commit_answer(
        expected_content_hash=before.session_content_hash, step=step, workflow=workflow
    )
    assert committed.projection.frontier.question_ids == ("sq:session:second",)
    assert service.load().ledger.steps == (step,)
    replay = service.commit_answer(
        expected_content_hash=before.session_content_hash, step=step, workflow=workflow
    )
    assert replay.replayed and replay.receipt == committed.receipt


def test_diagnostic_stop_preserves_an_active_peer_then_reaches_diagnostic_terminal(
    tmp_path: Path,
) -> None:
    state = _two_peer_state(
        obligations=(
            _search_obligation("sq:session:first"),
            _search_obligation("sq:session:second"),
        )
    )
    store = QuestionEvidenceSessionStore(tmp_path / "target")
    navigation = V3EvidenceNavigationStore(tmp_path / "target")
    service = _service_for(state, store, navigation)
    before = service.initialize()
    first, second = before.frontier.question_ids

    terminal_workflow = _semantic_terminal_workflow(service, navigation, first)
    first_entry = next(item for item in before.frontier.entries if item.question_id == first)
    stop = QuestionDiagnosticStop(
        stop_id="stop:session:first",
        question_id=first,
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=first_entry.entry_hash,
        evidence_diagnostic=evidence_diagnostic_from_workflow(terminal_workflow),
    )
    stopped = service.commit_diagnostic_stop(
        expected_content_hash=before.session_content_hash,
        stop=stop,
        workflow=terminal_workflow,
    )

    assert stopped.projection.status == "active"
    assert stopped.projection.frontier.question_ids == (second,)
    assert not service.load().ledger.steps
    assert service.load().ledger.diagnostic_stops == (stop,)

    peer_entry = stopped.projection.frontier.entries[0]
    peer_workflow = _semantic_terminal_workflow(service, navigation, second)
    peer_stop = QuestionDiagnosticStop(
        stop_id="stop:session:second",
        question_id=second,
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=peer_entry.entry_hash,
        evidence_diagnostic=evidence_diagnostic_from_workflow(peer_workflow),
    )
    completed = service.commit_diagnostic_stop(
        expected_content_hash=stopped.projection.session_content_hash,
        stop=peer_stop,
        workflow=peer_workflow,
    )

    assert completed.projection.status == "diagnostic_terminal"
    assert not completed.projection.frontier.complete
    assert completed.projection.status != "complete_with_answers"


def test_transitions_reject_workflows_from_other_exact_context_revisions(tmp_path: Path) -> None:
    logic = _minimal_logic(conditional=False)
    obligations = (_obligation("sq:session:first"), _obligation("sq:session:second"))
    alternate_obligation_payload = obligations[0].model_dump(mode="json")
    alternate_obligation_payload["propositions"][0]["statement"] = "Different evidence question."
    alternate_obligations = (
        EvidenceSearchObligation.model_validate(alternate_obligation_payload),
        obligations[1],
    )
    inventory = _two_peer_state(logic=logic, obligations=obligations).inventory
    alternate_inventory = inventory.model_copy(
        update={
            "sources": (
                inventory.sources[0].model_copy(
                    update={"source_artifact_hash": canonical_hash({"source": "alternate"})}
                ),
            )
        }
    )
    target = _two_peer_state(logic=logic, obligations=obligations)
    variants = (
        _two_peer_state(
            logic=logic,
            obligations=alternate_obligations,
            obligation_revision_id="revision:alternate-obligation",
        ),
        _two_peer_state(
            logic=logic,
            obligations=obligations,
            inventory=alternate_inventory,
        ),
        _two_peer_state(
            logic=logic,
            obligations=obligations,
            obligation_revision_id="revision:alternate-context",
        ),
    )
    store = QuestionEvidenceSessionStore(tmp_path / "answer-target")
    navigation = V3EvidenceNavigationStore(tmp_path / "answer-target")
    service = _service_for(target, store, navigation)
    before = service.initialize()
    first = before.frontier.question_ids[0]
    variant_contexts = tuple(
        (
            _service_for(
                variant,
                QuestionEvidenceSessionStore(tmp_path / f"answer-variant-{index}"),
                V3EvidenceNavigationStore(tmp_path / f"answer-variant-{index}"),
            ),
            V3EvidenceNavigationStore(tmp_path / f"answer-variant-{index}"),
        )
        for index, variant in enumerate(variants, start=1)
    )
    for variant_service, _ in variant_contexts:
        variant_service.initialize()

    closed = _closed_workflow(service, navigation, first)
    entry = before.frontier.entries[0]
    step = QuestionAnswerCommitStep(
        step_id="step:session:target",
        question_id=first,
        answer="yes",
        rationale="Attributable answer rationale.",
        logic_pack_family_id=logic.family_id,
        logic_pack_release_id=logic.release_id,
        logic_pack_hash=logic.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(closed),
        evidence_bundle=_bundle_binding(closed, first),
    )
    for variant_service, variant_navigation in variant_contexts:
        wrong_workflow = _closed_workflow(variant_service, variant_navigation, first)
        with pytest.raises(QuestionEvidenceSessionContextMismatch):
            service.commit_answer(
                expected_content_hash=before.session_content_hash,
                step=step,
                workflow=wrong_workflow,
            )

    terminal_obligations = (
        _search_obligation("sq:session:first"),
        _search_obligation("sq:session:second"),
    )
    alternate_terminal_payload = terminal_obligations[0].model_dump(mode="json")
    alternate_terminal_payload["propositions"][0]["statement"] = "Different evidence question."
    terminal_target = _two_peer_state(logic=logic, obligations=terminal_obligations)
    terminal_variants = (
        _two_peer_state(
            logic=logic,
            obligations=(
                EvidenceSearchObligation.model_validate(alternate_terminal_payload),
                terminal_obligations[1],
            ),
            obligation_revision_id="revision:alternate-obligation",
        ),
        _two_peer_state(
            logic=logic,
            obligations=terminal_obligations,
            inventory=alternate_inventory,
        ),
        _two_peer_state(
            logic=logic,
            obligations=terminal_obligations,
            obligation_revision_id="revision:alternate-context",
        ),
    )
    terminal_navigation = V3EvidenceNavigationStore(tmp_path / "diagnostic-target")
    terminal_service = _service_for(
        terminal_target,
        QuestionEvidenceSessionStore(tmp_path / "diagnostic-target"),
        terminal_navigation,
    )
    terminal_before = terminal_service.initialize()
    terminal_variant_contexts = tuple(
        (
            _service_for(
                variant,
                QuestionEvidenceSessionStore(tmp_path / f"diagnostic-variant-{index}"),
                V3EvidenceNavigationStore(tmp_path / f"diagnostic-variant-{index}"),
            ),
            V3EvidenceNavigationStore(tmp_path / f"diagnostic-variant-{index}"),
        )
        for index, variant in enumerate(terminal_variants, start=1)
    )
    for variant_service, _ in terminal_variant_contexts:
        variant_service.initialize()

    terminal = _semantic_terminal_workflow(terminal_service, terminal_navigation, first)
    terminal_entry = terminal_before.frontier.entries[0]
    stop = QuestionDiagnosticStop(
        stop_id="stop:session:target",
        question_id=first,
        logic_pack_family_id=logic.family_id,
        logic_pack_release_id=logic.release_id,
        logic_pack_hash=logic.content_hash,
        expected_frontier_entry_hash=terminal_entry.entry_hash,
        evidence_diagnostic=evidence_diagnostic_from_workflow(terminal),
    )
    for variant_service, variant_navigation in terminal_variant_contexts:
        wrong_workflow = _semantic_terminal_workflow(variant_service, variant_navigation, first)
        with pytest.raises(QuestionEvidenceSessionContextMismatch):
            terminal_service.commit_diagnostic_stop(
                expected_content_hash=terminal_before.session_content_hash,
                stop=stop,
                workflow=wrong_workflow,
            )


def test_different_transition_from_the_same_predecessor_is_stale(tmp_path: Path) -> None:
    state = _two_peer_state()
    store = QuestionEvidenceSessionStore(tmp_path)
    navigation = V3EvidenceNavigationStore(tmp_path)
    service = _service_for(state, store, navigation)
    before = service.initialize()
    question_id = before.frontier.question_ids[0]
    workflow = _closed_workflow(service, navigation, question_id)
    entry = before.frontier.entries[0]

    first = QuestionAnswerCommitStep(
        step_id="step:session:first-yes",
        question_id=question_id,
        answer="yes",
        rationale="Attributable answer rationale.",
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, question_id),
    )
    second = QuestionAnswerCommitStep(
        step_id="step:session:first-no",
        question_id=question_id,
        answer="no",
        rationale="Attributable answer rationale.",
        logic_pack_family_id=state.ledger.logic_pack.family_id,
        logic_pack_release_id=state.ledger.logic_pack.release_id,
        logic_pack_hash=state.ledger.logic_pack.content_hash,
        expected_frontier_entry_hash=entry.entry_hash,
        evidence_closure=evidence_closure_from_workflow(workflow),
        evidence_bundle=_bundle_binding(workflow, question_id),
    )
    service.commit_answer(
        expected_content_hash=before.session_content_hash, step=first, workflow=workflow
    )

    with pytest.raises(StaleQuestionEvidenceSession):
        service.commit_answer(
            expected_content_hash=before.session_content_hash, step=second, workflow=workflow
        )


def test_store_coexists_for_distinct_logic_and_obligation_content(tmp_path: Path) -> None:
    first_logic = _minimal_logic(conditional=False)
    alternate_logic_payload = first_logic.model_dump(exclude={"content_hash"}, mode="json")
    alternate_logic_payload["domains"][0]["judgment_rules"][0]["judgment"] = "high"
    second_logic = LogicPack.model_validate(alternate_logic_payload)
    first_obligations = (_obligation("sq:session:first"), _obligation("sq:session:second"))
    alternate_obligation_payload = first_obligations[0].model_dump(mode="json")
    alternate_obligation_payload["propositions"][0]["statement"] = "A distinct obligation."
    second_obligations = (
        EvidenceSearchObligation.model_validate(alternate_obligation_payload),
        first_obligations[1],
    )
    first = _two_peer_state(logic=first_logic, obligations=first_obligations)
    second = _two_peer_state(logic=second_logic, obligations=second_obligations)
    store = QuestionEvidenceSessionStore(tmp_path)
    navigation = V3EvidenceNavigationStore(tmp_path)
    first_service = _service_for(first, store, navigation)
    second_service = _service_for(second, store, navigation)

    first_service.initialize()
    second_service.initialize()

    assert first.logic_pack_hash != second.logic_pack_hash
    assert first.guidance_obligations_hash != second.guidance_obligations_hash
    assert store.load(first) == first
    assert store.load(second) == second
    assert first_service.load().ledger.logic_pack == first_logic
    assert second_service.load().ledger.logic_pack == second_logic
    assert first_service.load().obligations == first_obligations
    assert second_service.load().obligations == second_obligations
