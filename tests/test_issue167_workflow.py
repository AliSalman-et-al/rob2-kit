"""Focused v3 evidence-coverage reducer and persistence contracts."""

from pathlib import Path

import pytest

from rob2_kit.application.evidence_navigation import (
    ConcurrentEvidenceNavigationUpdate,
    IncompatibleEvidenceNavigationState,
    V3EvidenceNavigationStore,
    new_v3_navigation_state,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.sources import SourceAvailability, SourceProcessing, SourceRole
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.search import SearchQuery
from rob2_kit.evidence.workflow import (
    IrrelevantReason,
    TriageBasis,
    V3AcquisitionAttemptReceipt,
    V3AttemptKind,
    V3AuthorizedSource,
    V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission,
    V3EvidenceWorkflowState,
    V3ExposedPage,
    V3MaterializedStageScope,
    V3NavigationCompletionReceipt,
    V3PageExposure,
    V3ScopeLimitationKind,
    V3SearchAttempt,
    V3StageScopeLimitation,
    V3TriageKind,
    V3TriggerDisposition,
    V3TriggerDispositionKind,
    provision_v3_scope_acquisition_receipts,
    record_v3_acquisition_attempt,
    record_v3_navigation_completion,
    start_v3_search_attempt,
    submit_evidence_stage_outcome,
    supersede_v3_search_attempt,
    v3_coverage_progress,
)


def _obligation(*, triggered: bool = False) -> EvidenceSearchObligation:
    later = {
        "id": "stage:seed:later",
        "applicable_source_roles": ["primary_report"],
        "activation": "triggered" if triggered else "mandatory",
        "activation_trigger_ids": ["trigger:later"] if triggered else [],
        "navigation_intents": [
            {
                "id": "intent:later:read",
                "kind": "structural_read",
                "structural_targets": ["methods"],
            }
        ],
    }
    return EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": "sq:test:one",
            "propositions": [
                {
                    "id": "proposition:test:one",
                    "statement": "test",
                    "accepted_source_roles": ["primary_report"],
                    "evidence_passes": [
                        {
                            "id": "pass:seed",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": "stage:seed:first",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:first:search",
                                            "kind": "search",
                                            "terms": ["allocation"],
                                        }
                                    ],
                                },
                                later,
                            ],
                        },
                        {
                            "id": "pass:contradiction",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": "stage:contradiction:first",
                                    "applicable_source_roles": ["primary_report"],
                                    "navigation_intents": [
                                        {
                                            "id": "intent:contradiction:read",
                                            "kind": "structural_read",
                                            "structural_targets": ["discussion"],
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
                        "id": "trigger:later",
                        "condition": "no_direct_evidence",
                        "source_stage_id": "stage:seed:first",
                        "target_stage_id": "stage:seed:later",
                    }
                ]
                if triggered
                else []
            ),
        }
    )


def _state(*, triggered: bool = False) -> V3EvidenceWorkflowState:
    obligation = _obligation(triggered=triggered)
    source = V3AuthorizedSource(
        source_id="source:one",
        roles=("primary_report",),
        source_artifact_hash=canonical_hash({"source": 1}),
        parse_id="parse:one",
        parse_output_hash=canonical_hash({"parse": 1}),
    )
    scopes = []
    for proposition in obligation.propositions:
        for evidence_pass in proposition.evidence_passes:
            for stage in evidence_pass.coverage_stages:
                ids = (source.source_id,)
                scopes.append(
                    V3MaterializedStageScope(
                        scope_id=f"scope:{stage.id[6:]}",
                        proposition_id=proposition.id,
                        pass_id=evidence_pass.id,
                        stage_id=stage.id,
                        authorized_source_ids=ids,
                        authorized_source_scope_hash=canonical_hash(ids),
                    )
                )
    return V3EvidenceWorkflowState(
        run_id="run:one",
        result_id="result:one",
        domain_id="domain:one",
        question_id=obligation.question_id,
        snapshot_hash=canonical_hash({"snapshot": 1}),
        obligation_revision_id="revision:obligation",
        obligation=obligation,
        obligation_hash=canonical_hash(obligation),
        inventory_snapshot_hash=canonical_hash((source.model_dump(mode="json"),)),
        authorized_inventory=(source,),
        search_policy_id="policy:search",
        search_policy_hash=canonical_hash({"search": 1}),
        read_policy_id="policy:read",
        read_policy_hash=canonical_hash({"read": 1}),
        visual_policy_id="policy:visual",
        visual_policy_hash=canonical_hash({"visual": 1}),
        stage_scopes=tuple(scopes),
    )


def _mixed_unavailable_state(*, include_material_limitation: bool = False):
    state = _state()
    unavailable = V3AuthorizedSource(
        source_id="source:unavailable",
        roles=(SourceRole.SUPPLEMENT,),
        availability=SourceAvailability.UNAVAILABLE,
        processing=SourceProcessing.NOT_ATTEMPTED,
    )
    first = state.stage_scopes[0]
    limitations = [
        V3StageScopeLimitation(
            role=SourceRole.SUPPLEMENT,
            kind=V3ScopeLimitationKind.SOURCE_UNAVAILABLE,
            rationale="The supplement is unavailable after acquisition.",
        )
    ]
    if include_material_limitation:
        limitations.append(
            V3StageScopeLimitation(
                role=SourceRole.PRIMARY_REPORT,
                kind=V3ScopeLimitationKind.MATERIAL_UNRESOLVED,
                rationale="Some primary-report material remains unreadable.",
            )
        )
    mixed_scope = first.model_copy(
        update={
            "applicable_source_roles": (
                SourceRole.PRIMARY_REPORT,
                SourceRole.SUPPLEMENT,
            ),
            "role_limitations": tuple(limitations),
        }
    )
    inventory = (*state.authorized_inventory, unavailable)
    mixed = state.model_copy(
        update={
            "authorized_inventory": inventory,
            "inventory_snapshot_hash": canonical_hash(
                tuple(item.model_dump(mode="json") for item in inventory)
            ),
            "stage_scopes": tuple(
                mixed_scope if item.stage_id == mixed_scope.stage_id else item
                for item in state.stage_scopes
            ),
        }
    )
    provisioned = provision_v3_scope_acquisition_receipts(mixed)
    receipt = next(
        item for item in provisioned.acquisition_receipts if item.stage_id == mixed_scope.stage_id
    )
    return provisioned, mixed_scope, receipt


def _outcome(
    state: V3EvidenceWorkflowState,
    stage_id: str,
    *,
    kind: str = "obligation_satisfied",
    triggers=(),
    acquisition_receipt_id: str | None = None,
):
    scope = next(x for x in state.stage_scopes if x.stage_id == stage_id)
    payload = {
        "submission_id": f"submission:{stage_id[6:]}",
        "run_id": state.run_id,
        "result_id": state.result_id,
        "domain_id": state.domain_id,
        "question_id": state.question_id,
        "obligation_revision_id": state.obligation_revision_id,
        "obligation_hash": state.obligation_hash,
        "inventory_snapshot_hash": state.inventory_snapshot_hash,
        "proposition_id": scope.proposition_id,
        "pass_id": scope.pass_id,
        "stage_id": stage_id,
        "materialized_scope_id": scope.scope_id,
        "outcome_kind": kind,
        "rationale": "Attributable closure rationale.",
        "trigger_dispositions": tuple(x.model_dump(mode="json") for x in triggers),
        "acquisition_receipt_id": acquisition_receipt_id,
        "content_hash": None,
    }
    return V3EvidenceStageOutcomeSubmission.model_validate(
        payload | {"content_hash": canonical_hash(payload)}
    )


def test_v3_search_is_bound_to_one_intent_and_supersession_cannot_cross_it() -> None:
    state = _state()
    first = V3SearchAttempt(
        attempt_id="attempt:first",
        proposition_id="proposition:test:one",
        pass_id="pass:seed",
        stage_id="stage:seed:first",
        intent_id="intent:first:search",
        query=SearchQuery(terms=("allocation",), source_ids=("source:one",)),
        query_hash=canonical_hash(SearchQuery(terms=("allocation",), source_ids=("source:one",))),
        source_scope_hash=canonical_hash(("source:one",)),
    )
    state = start_v3_search_attempt(state, first)
    different_intent = first.model_copy(
        update={"attempt_id": "attempt:other", "intent_id": "intent:later:read"}
    )
    with pytest.raises(ValueError, match="issued Search"):
        start_v3_search_attempt(state, different_intent)
    replacement = first.model_copy(
        update={
            "attempt_id": "attempt:new",
            "query": SearchQuery(terms=("random",), source_ids=("source:one",)),
            "query_hash": canonical_hash(
                SearchQuery(terms=("random",), source_ids=("source:one",))
            ),
        }
    )
    state = supersede_v3_search_attempt(
        state,
        old_attempt_id=first.attempt_id,
        replacement=replacement,
        rationale="Narrower issued synonym.",
    )
    assert [x.kind for x in state.attempts] == [V3AttemptKind.SUPERSEDED, V3AttemptKind.SELECTED]


def test_v3_search_rejects_omitted_extra_or_reordered_issued_source_scope() -> None:
    state = _state()
    for source_ids in ((), ("source:extra",), ("source:one", "source:extra")):
        query = SearchQuery(terms=("allocation",), source_ids=source_ids)
        attempt = V3SearchAttempt(
            attempt_id=f"attempt:{len(source_ids)}",
            proposition_id="proposition:test:one",
            pass_id="pass:seed",
            stage_id="stage:seed:first",
            intent_id="intent:first:search",
            query=query,
            query_hash=canonical_hash(query),
            source_scope_hash=canonical_hash(("source:one",)),
        )
        with pytest.raises(ValueError, match="Source IDs"):
            start_v3_search_attempt(state, attempt)


def test_full_fidelity_triage_requires_safe_preview_or_read_receipt() -> None:
    state = _state()
    query = SearchQuery(terms=("allocation",), source_ids=("source:one",))
    attempt = V3SearchAttempt(
        attempt_id="attempt:full",
        proposition_id="proposition:test:one",
        pass_id="pass:seed",
        stage_id="stage:seed:first",
        intent_id="intent:first:search",
        query=query,
        query_hash=canonical_hash(query),
        source_scope_hash=canonical_hash(("source:one",)),
    )
    state = start_v3_search_attempt(state, attempt)
    exposure = V3PageExposure(
        attempt_id=attempt.attempt_id,
        page_handle="v3page:one",
        candidate_id="candidate:one",
        canonical_unit_id="unit:one",
        location_handle="loc:one",
        source_id="source:one",
        source_artifact_hash=state.authorized_inventory[0].source_artifact_hash,
        parse_id="parse:one",
        canonical_start=0,
        canonical_end=10,
        left_omitted_character_count=1,
        right_omitted_character_count=0,
        undisplayed_match_count=0,
        warnings=("parser_warning",),
        page_number=1,
        total_page_count=1,
        traversal_complete=True,
        triage_flags={"has_context_dependency": True},
        table_headers=("Allocation",),
        caption="Table 2",
        duplicate_group_id="duplicate:one",
    )
    state = state.model_copy(
        update={
            "pages": (
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle="v3page:one",
                    candidate_ids=("candidate:one",),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                ),
            ),
            "exposures": (exposure,),
        }
    )
    preview = V3CandidateTriageRevision(
        revision_id="triage:preview",
        attempt_id=attempt.attempt_id,
        sq_id=state.question_id,
        page_handle="v3page:one",
        candidate_id="candidate:one",
        kind=V3TriageKind.IRRELEVANT,
        irrelevant_reason=IrrelevantReason.LEXICAL_FALSE_POSITIVE,
        basis=TriageBasis.PREVIEW,
    )
    from rob2_kit.evidence.workflow import submit_v3_page_triage

    with pytest.raises(ValueError, match="complete unambiguous preview"):
        submit_v3_page_triage(
            state,
            submission_id="submission:preview",
            attempt_id=attempt.attempt_id,
            page_handles=("v3page:one",),
            revisions=(preview,),
        )
    read = preview.model_copy(
        update={
            "revision_id": "triage:read",
            "basis": TriageBasis.READ_VIEW_RECEIPT,
            "read_view_receipt": "receipt:read",
        }
    )
    complete = submit_v3_page_triage(
        state,
        submission_id="submission:read",
        attempt_id=attempt.attempt_id,
        page_handles=("v3page:one",),
        revisions=(read,),
    )
    assert complete.triage_revisions[0].read_view_receipt == "receipt:read"


def test_retained_triage_requires_and_retains_read_view_receipt() -> None:
    payload = {
        "revision_id": "triage:retained",
        "attempt_id": "attempt:retained",
        "sq_id": "sq:test:one",
        "page_handle": "v3page:retained",
        "candidate_id": "candidate:retained",
        "kind": V3TriageKind.RETAINED,
    }
    with pytest.raises(ValueError, match="retained v3 triage requires a read-view receipt"):
        V3CandidateTriageRevision.model_validate(payload)
    accepted = V3CandidateTriageRevision.model_validate(
        payload | {"read_view_receipt": "receipt:reviewed-read"}
    )
    assert accepted.read_view_receipt == "receipt:reviewed-read"


def test_inventory_hash_binds_multirole_source_payload() -> None:
    state = _state()
    source = state.authorized_inventory[0].model_copy(
        update={"roles": (SourceRole.PRIMARY_REPORT, SourceRole.SUPPLEMENT)}
    )
    valid = state.model_copy(
        update={
            "authorized_inventory": (source,),
            "inventory_snapshot_hash": canonical_hash((source.model_dump(mode="json"),)),
        }
    )
    assert valid.authorized_inventory[0].roles == (SourceRole.PRIMARY_REPORT, SourceRole.SUPPLEMENT)
    with pytest.raises(ValueError, match="inventory snapshot hash"):
        V3EvidenceWorkflowState.model_validate(
            valid.model_dump() | {"inventory_snapshot_hash": canonical_hash({"wrong": 1})}
        )


def test_unavailable_scope_closes_limited_work_without_fake_search_traversal() -> None:
    state = _state()
    original = next(item for item in state.stage_scopes if item.stage_id == "stage:seed:first")

    def limited_scope(scope: V3MaterializedStageScope) -> V3MaterializedStageScope:
        return scope.model_copy(
            update={
                "authorized_source_ids": (),
                "authorized_source_scope_hash": canonical_hash(()),
                "role_limitations": (
                    V3StageScopeLimitation(
                        role=SourceRole.PRIMARY_REPORT,
                        kind=V3ScopeLimitationKind.SOURCE_UNAVAILABLE,
                        rationale="The required report was unavailable after acquisition.",
                    ),
                ),
            }
        )

    limited = limited_scope(original)
    state = state.model_copy(
        update={
            "stage_scopes": tuple(
                limited if item == original else limited_scope(item) for item in state.stage_scopes
            ),
            "authorized_inventory": (
                state.authorized_inventory[0].model_copy(
                    update={
                        "availability": SourceAvailability.UNAVAILABLE,
                        "processing": SourceProcessing.NOT_ATTEMPTED,
                        "source_artifact_hash": None,
                        "parse_id": None,
                        "parse_output_hash": None,
                    }
                ),
            ),
        }
    )
    inventory_hash = canonical_hash(
        tuple(item.model_dump(mode="json") for item in state.authorized_inventory)
    )
    state = state.model_copy(update={"inventory_snapshot_hash": inventory_hash})
    receipt_payload = {
        "receipt_id": "receipt:acquisition:unavailable",
        "issuance_id": "issuance:acquisition:unavailable",
        "run_id": state.run_id,
        "result_id": state.result_id,
        "domain_id": state.domain_id,
        "question_id": state.question_id,
        "proposition_id": limited.proposition_id,
        "pass_id": limited.pass_id,
        "stage_id": limited.stage_id,
        "materialized_scope_id": limited.scope_id,
        "inventory_snapshot_hash": state.inventory_snapshot_hash,
        "unavailable_source_ids": ("source:one",),
        "limitation_hash": canonical_hash(
            tuple(
                item.model_dump(mode="json")
                for item in limited.role_limitations
                if item.kind is V3ScopeLimitationKind.SOURCE_UNAVAILABLE
            )
        ),
        "receipt_hash": None,
    }
    receipt = V3AcquisitionAttemptReceipt.model_validate(
        receipt_payload | {"receipt_hash": canonical_hash(receipt_payload)}
    )
    state = state.model_copy(
        update={"issued_acquisition_receipt_hashes": ((receipt.issuance_id, receipt.receipt_hash),)}
    )
    state = record_v3_acquisition_attempt(state, receipt)
    closed = submit_evidence_stage_outcome(
        state,
        _outcome(
            state,
            limited.stage_id,
            kind="source_unavailable_after_attempt",
            acquisition_receipt_id=receipt.receipt_id,
        ),
    )
    progress = v3_coverage_progress(closed)
    assert progress["question_ready"] is False
    assert progress["propositions"][0]["passes"][0]["stages"][0]["blockers"] == (
        "source_unavailable_after_attempt",
    )


def test_partially_available_source_scope_requires_traversal_before_unavailable_closure() -> None:
    state, scope, receipt = _mixed_unavailable_state()
    outcome = _outcome(
        state,
        scope.stage_id,
        kind="source_unavailable_after_attempt",
        acquisition_receipt_id=receipt.receipt_id,
    )

    with pytest.raises(ValueError, match="partially available scope requires exhaustive traversal"):
        submit_evidence_stage_outcome(state, outcome)

    traversed = _terminal_empty_search(state, "attempt:mixed-unavailable")
    closed = submit_evidence_stage_outcome(traversed, outcome)
    assert v3_coverage_progress(closed)["question_ready"] is False


def test_mixed_scope_limitation_cannot_bypass_unavailable_source_receipt() -> None:
    state, scope, receipt = _mixed_unavailable_state(include_material_limitation=True)
    traversed = _terminal_empty_search(state, "attempt:mixed-limitation")
    without_receipt = _outcome(
        traversed,
        scope.stage_id,
        kind="scope_limitation_unresolved",
    )

    with pytest.raises(ValueError, match="source unavailability requires a recorded"):
        submit_evidence_stage_outcome(traversed, without_receipt)

    with_receipt = _outcome(
        traversed,
        scope.stage_id,
        kind="scope_limitation_unresolved",
        acquisition_receipt_id=receipt.receipt_id,
    )
    closed = submit_evidence_stage_outcome(traversed, with_receipt)
    assert v3_coverage_progress(closed)["question_ready"] is False


def test_semantic_uncertainty_requires_and_preserves_unresolved_review() -> None:
    state = _state()
    query = SearchQuery(terms=("allocation",), source_ids=("source:one",))
    attempt = V3SearchAttempt(
        attempt_id="attempt:uncertain",
        proposition_id="proposition:test:one",
        pass_id="pass:seed",
        stage_id="stage:seed:first",
        intent_id="intent:first:search",
        query=query,
        query_hash=canonical_hash(query),
        source_scope_hash=canonical_hash(("source:one",)),
    )
    state = start_v3_search_attempt(state, attempt)
    exposure = V3PageExposure(
        attempt_id=attempt.attempt_id,
        page_handle="v3page:uncertain",
        candidate_id="candidate:uncertain",
        canonical_unit_id="unit:uncertain",
        location_handle="loc:uncertain",
        source_id="source:one",
        source_artifact_hash=state.authorized_inventory[0].source_artifact_hash,
        parse_id="parse:one",
        canonical_start=0,
        canonical_end=8,
        left_omitted_character_count=0,
        right_omitted_character_count=0,
        undisplayed_match_count=0,
        page_number=1,
        total_page_count=1,
        traversal_complete=True,
        triage_flags={},
    )
    state = state.model_copy(
        update={
            "pages": (
                V3ExposedPage(
                    attempt_id=attempt.attempt_id,
                    page_handle=exposure.page_handle,
                    candidate_ids=(exposure.candidate_id,),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                ),
            ),
            "exposures": (exposure,),
            "triage_revisions": (
                V3CandidateTriageRevision(
                    revision_id="triage:uncertain",
                    attempt_id=attempt.attempt_id,
                    sq_id=state.question_id,
                    page_handle=exposure.page_handle,
                    candidate_id=exposure.candidate_id,
                    kind=V3TriageKind.UNRESOLVED,
                    rationale="A material ambiguity remains after reading.",
                ),
            ),
        }
    )
    closed = submit_evidence_stage_outcome(
        state, _outcome(state, "stage:seed:first", kind="semantic_uncertainty_unresolved")
    )
    assert v3_coverage_progress(closed)["question_ready"] is False


def test_cross_source_limitation_requires_available_scope_traversal_then_terminalizes() -> None:
    state = _state()
    first = state.stage_scopes[0]
    limited = first.model_copy(
        update={
            "source_set_rule": "cross_source_comparison",
            "role_limitations": (
                V3StageScopeLimitation(
                    source_set_rule="cross_source_comparison",
                    kind=V3ScopeLimitationKind.CROSS_SOURCE_INSUFFICIENT,
                    rationale="Only one applicable source revision exists.",
                ),
            ),
        }
    )
    state = state.model_copy(
        update={
            "stage_scopes": tuple(
                limited if item.stage_id == limited.stage_id else item
                for item in state.stage_scopes
            )
        }
    )
    outcome = _outcome(state, limited.stage_id, kind="scope_limitation_unresolved")
    with pytest.raises(ValueError, match="exhaustive traversal"):
        submit_evidence_stage_outcome(state, outcome)

    traversed = _terminal_empty_search(state, "attempt:cross-source")
    closed = submit_evidence_stage_outcome(traversed, outcome)
    assert v3_coverage_progress(closed)["question_ready"] is False


def _terminal_empty_search(
    state: V3EvidenceWorkflowState, attempt_id: str
) -> V3EvidenceWorkflowState:
    query = SearchQuery(terms=("allocation",), source_ids=("source:one",))
    attempt = V3SearchAttempt(
        attempt_id=attempt_id,
        proposition_id="proposition:test:one",
        pass_id="pass:seed",
        stage_id="stage:seed:first",
        intent_id="intent:first:search",
        query=query,
        query_hash=canonical_hash(query),
        source_scope_hash=canonical_hash(("source:one",)),
    )
    state = start_v3_search_attempt(state, attempt)
    return state.model_copy(
        update={
            "pages": (
                V3ExposedPage(
                    attempt_id=attempt_id,
                    page_handle=f"v3page:{attempt_id}",
                    candidate_ids=(),
                    page_number=1,
                    total_page_count=1,
                    traversal_complete=True,
                ),
            )
        }
    )


def _receipt(
    state: V3EvidenceWorkflowState, stage_id: str, intent_id: str
) -> tuple[V3EvidenceWorkflowState, V3NavigationCompletionReceipt]:
    scope = next(item for item in state.stage_scopes if item.stage_id == stage_id)
    payload = {
        "receipt_id": f"receipt:{stage_id[6:]}",
        "issuance_id": f"issuance:{stage_id[6:]}",
        "proposition_id": scope.proposition_id,
        "pass_id": scope.pass_id,
        "stage_id": stage_id,
        "intent_id": intent_id,
        "kind": "structural_read",
        "source_scope_hash": scope.authorized_source_scope_hash,
        "snapshot_hash": state.snapshot_hash,
        "read_policy_id": state.read_policy_id,
        "read_policy_hash": state.read_policy_hash,
        "visual_policy_id": None,
        "visual_policy_hash": None,
        "receipt_hash": None,
    }
    receipt = V3NavigationCompletionReceipt.model_validate(
        payload | {"receipt_hash": canonical_hash(payload)}
    )
    state = state.model_copy(
        update={
            "issued_receipt_hashes": (
                *state.issued_receipt_hashes,
                (receipt.issuance_id, receipt.receipt_hash),
            )
        }
    )
    return state, receipt


def test_escalation_chain_resolves_to_question_ready_and_rejects_false_or_satisfied_trigger() -> (
    None
):
    state = _terminal_empty_search(_state(triggered=True), "attempt:escalate")
    false = V3TriggerDisposition(
        trigger_id="trigger:later",
        kind=V3TriggerDispositionKind.FALSE,
        rationale="Direct evidence exists.",
    )
    with pytest.raises(ValueError, match="true or unresolved trigger"):
        submit_evidence_stage_outcome(
            state,
            _outcome(state, "stage:seed:first", kind="escalation_required", triggers=(false,)),
        )
    true = false.model_copy(
        update={"kind": V3TriggerDispositionKind.TRUE, "rationale": "Escalation is required."}
    )
    with pytest.raises(ValueError, match="obligation_satisfied"):
        submit_evidence_stage_outcome(state, _outcome(state, "stage:seed:first", triggers=(true,)))
    state = submit_evidence_stage_outcome(
        state, _outcome(state, "stage:seed:first", kind="escalation_required", triggers=(true,))
    )
    state, receipt = _receipt(state, "stage:seed:later", "intent:later:read")
    state = record_v3_navigation_completion(state, receipt)
    state = submit_evidence_stage_outcome(state, _outcome(state, "stage:seed:later"))
    state, receipt = _receipt(state, "stage:contradiction:first", "intent:contradiction:read")
    state = record_v3_navigation_completion(state, receipt)
    state = submit_evidence_stage_outcome(state, _outcome(state, "stage:contradiction:first"))
    assert v3_coverage_progress(state)["question_ready"] is True


def test_triggered_stage_is_additive_and_untraversed_mandatory_stage_cannot_be_waived() -> None:
    state = _state(triggered=True)
    with pytest.raises(ValueError, match="completed navigation"):
        submit_evidence_stage_outcome(
            state,
            _outcome(
                state,
                "stage:seed:first",
                kind="escalation_required",
                triggers=(
                    V3TriggerDisposition(
                        trigger_id="trigger:later",
                        kind=V3TriggerDispositionKind.TRUE,
                        rationale="No direct evidence.",
                    ),
                ),
            ),
        )
    progress = v3_coverage_progress(state)
    stages = progress["propositions"][0]["passes"][0]["stages"]
    assert stages[0]["active"] is True
    assert stages[1]["active"] is False


def test_v3_persistence_rejects_stale_identity_and_uses_optimistic_concurrency(
    tmp_path: Path,
) -> None:
    state = new_v3_navigation_state(workflow=_state())
    store = V3EvidenceNavigationStore(tmp_path)
    store.save(state)
    restored = store.load(
        run_id="run:one",
        result_id="result:one",
        domain_id="domain:one",
        question_id="sq:test:one",
        obligation_hash=state.workflow.obligation_hash,
        inventory_snapshot_hash=state.workflow.inventory_snapshot_hash,
    )
    assert restored == state
    with pytest.raises(ConcurrentEvidenceNavigationUpdate):
        store.save(state, expected_content_hash=canonical_hash({"stale": 1}))
    assert (
        store.load(
            run_id="run:one",
            result_id="result:one",
            domain_id="domain:one",
            question_id="sq:test:one",
            obligation_hash=canonical_hash({"other": 1}),
            inventory_snapshot_hash=state.workflow.inventory_snapshot_hash,
        )
        is None
    )


def test_v3_persistence_archives_prior_inventory_revision_under_its_exact_key(
    tmp_path: Path,
) -> None:
    store = V3EvidenceNavigationStore(tmp_path)
    original = new_v3_navigation_state(workflow=_state())
    store.save(original)
    revised_source = original.workflow.authorized_inventory[0].model_copy(
        update={"source_artifact_hash": canonical_hash({"source": "revised"})}
    )
    revised_workflow = original.workflow.model_copy(
        update={
            "authorized_inventory": (revised_source,),
            "inventory_snapshot_hash": canonical_hash((revised_source.model_dump(mode="json"),)),
        }
    )
    revised = new_v3_navigation_state(workflow=revised_workflow)
    store.save(revised)
    assert (
        store.load(
            run_id=original.run_id,
            result_id=original.result_id,
            domain_id=original.domain_id,
            question_id=original.question_id,
            obligation_hash=original.workflow.obligation_hash,
            inventory_snapshot_hash=original.workflow.inventory_snapshot_hash,
        )
        == original
    )
    assert (
        store.load(
            run_id=revised.run_id,
            result_id=revised.result_id,
            domain_id=revised.domain_id,
            question_id=revised.question_id,
            obligation_hash=revised.workflow.obligation_hash,
            inventory_snapshot_hash=revised.workflow.inventory_snapshot_hash,
        )
        == revised
    )
    with pytest.raises(ConcurrentEvidenceNavigationUpdate):
        store.save(original, expected_content_hash=canonical_hash({"stale": "write"}))


def test_v2_payload_cannot_be_loaded_or_reinterpreted_as_v3(tmp_path: Path) -> None:
    workflow = _state()
    store = V3EvidenceNavigationStore(tmp_path)
    path = store._path(
        workflow.run_id,
        workflow.result_id,
        workflow.domain_id,
        workflow.question_id,
        workflow.obligation_hash,
        workflow.inventory_snapshot_hash,
    )
    path.parent.mkdir(parents=True)
    path.write_text('{"state_version":"evidence-navigation-state:2.0.0"}', encoding="utf-8")

    with pytest.raises(IncompatibleEvidenceNavigationState, match="compatible v3"):
        store.load(
            run_id=workflow.run_id,
            result_id=workflow.result_id,
            domain_id=workflow.domain_id,
            question_id=workflow.question_id,
            obligation_hash=workflow.obligation_hash,
            inventory_snapshot_hash=workflow.inventory_snapshot_hash,
        )
