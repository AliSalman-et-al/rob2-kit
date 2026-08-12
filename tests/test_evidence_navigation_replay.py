"""Compact exercised replay for the active Evidence-navigation contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    EvidenceContextInventorySource,
    EvidenceContextUnitOrientation,
    materialize_evidence_context,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.application.evidence_runtime import (
    V3EvidenceNavigationRuntime,
    V3EvidencePageTriageRequest,
    V3EvidenceSearchContinuationRequest,
    V3EvidenceSearchRequest,
)
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceReadBatchItem,
    EvidenceReadBatchRequest,
    EvidenceReadBatchScope,
    EvidenceReadPolicy,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    SearchContinuationReason,
    SearchQuery,
)
from rob2_kit.evidence.errors import StaleSearchContinuation
from rob2_kit.evidence.obligations import (
    EvidenceCoverageStageOutcomeKind,
    EvidenceSearchObligation,
)
from rob2_kit.evidence.workflow import (
    IrrelevantReason, TriageBasis, V3AttemptKind, V3CandidateTriageRevision,
    V3EvidenceStageOutcomeSubmission, V3EvidenceWorkflowState,
)
from rob2_kit.domain.sources import SourceAvailability, SourceCriticality, SourceProcessing

def _runtime(
    tmp_path: Path, policy: EvidenceSearchPolicy
) -> tuple[V3EvidenceNavigationRuntime, EvidenceSearchIndex]:
    """Build the smallest public v3 runtime fixture without importing test helpers."""

    obligation = EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0", "question_id": "sq:replay:test",
            "propositions": [{
                "id": "proposition:replay:test", "statement": "Replay proposition.",
                "accepted_source_roles": ["primary_report"],
                "evidence_passes": [
                    {"id": "pass:replay:seed", "kind": "guidance_seed", "coverage_stages": [{
                        "id": "stage:replay:seed", "applicable_source_roles": ["primary_report"],
                        "navigation_intents": [{"id": "intent:replay:seed", "kind": "search", "terms": ["allocation"]}],
                    }]},
                    {"id": "pass:replay:contradiction", "kind": "contradiction", "coverage_stages": [{
                        "id": "stage:replay:contradiction", "applicable_source_roles": ["primary_report"],
                        "navigation_intents": [{"id": "intent:replay:contradiction", "kind": "search", "terms": ["allocation"]}],
                    }]},
                ],
            }],
        }
    )
    artifact_hash = canonical_hash({"source": "replay"})
    index = EvidenceSearchIndex(tmp_path / "replay.sqlite3")
    snapshot_hash = index.replace_units(
        tuple(
            _unit(number).model_copy(update={
                "source_id": "source:replay", "source_artifact_hash": artifact_hash,
                "parse_id": "parse:replay",
            })
            for number in (1, 2)
        )
    )
    source = EvidenceContextInventorySource(
        source_id="source:replay", roles=("primary_report",),
        source_artifact_hash=artifact_hash, parse_id="parse:replay",
        parse_output_hash=canonical_hash({"parse": "replay"}),
        availability=SourceAvailability.ACQUIRED, processing=SourceProcessing.USABLE,
        criticality=SourceCriticality.EXPECTED, page_count=2, indexed_unit_count=2,
        unit_orientation=EvidenceContextUnitOrientation.INDEXED_UNITS,
    )
    context = materialize_evidence_context(
        obligation, EvidenceContextInventory(inventory_id="inventory:replay", sources=(source,))
    )
    read_policy = EvidenceReadPolicy()
    workflow = V3EvidenceWorkflowState(
        run_id="run:replay", result_id="result:replay", domain_id="domain:replay",
        question_id=context.question_id, snapshot_hash=snapshot_hash,
        obligation_revision_id="revision:replay", obligation=context.obligation,
        obligation_hash=context.obligation_hash, inventory_snapshot_hash=context.inventory_snapshot_hash,
        authorized_inventory=context.authorized_inventory, search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy), read_policy_id=read_policy.policy_id,
        read_policy_hash=canonical_hash(read_policy), visual_policy_id="policy:visual:replay",
        visual_policy_hash=canonical_hash({"visual": "replay"}), stage_scopes=context.stage_scopes,
    )
    return V3EvidenceNavigationRuntime(
        context=context, workflow=workflow, store=V3EvidenceNavigationStore(tmp_path / "store"),
        search=index, search_policy=policy,
    ), index


FIXTURE = Path(__file__).parent / "public_fixtures" / "traces" / "evidence-navigation-v3.golden.json"


def _unit(number: int) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=f"unit:replay:{number}",
        source_id="source:one",
        source_artifact_hash=canonical_hash({"source": 1}),
        parse_id="parse:one",
        page=number,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=f"allocation replay evidence {number}",
        fragment_ids=(f"fragment:replay:{number}",),
    )


def _replay(tmp_path: Path) -> dict[str, object]:
    policy = EvidenceSearchPolicy(candidate_ceiling=1)
    runtime, index = _runtime(tmp_path, policy)
    workflow = runtime.expected_workflow
    state = runtime.initialize()
    target = {
        "proposition_id": "proposition:replay:test",
        "pass_id": "pass:replay:seed",
        "stage_id": "stage:replay:seed",
        "intent_id": "intent:replay:seed",
    }
    first = runtime.search_page(
        V3EvidenceSearchRequest(
            expected_content_hash=state.content_hash,
            attempt_id="attempt:a",
            query=SearchQuery(terms=("allocation",)),
            **target,
        )
    )
    second = runtime.continue_search_page(
        V3EvidenceSearchContinuationRequest(
            expected_content_hash=first.state.content_hash,
            attempt_id="attempt:a",
            continuation=first.page.continuation,
            continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
        )
    )
    current = second.state
    receipts: list[str] = []
    for number, page in enumerate((first.page, second.page), start=1):
        read = index.read_batch(
            EvidenceReadBatchRequest(
                scope=EvidenceReadBatchScope(
                    result_id=workflow.result_id, domain_id=workflow.domain_id,
                    snapshot_hash=workflow.snapshot_hash,
                ),
                items=(EvidenceReadBatchItem(
                    location_handle=page.candidates[0].location_handle,
                    question_ids=(workflow.question_id,), source_ids=("source:replay",),
                ),),
            )
        )
        receipt = read.outcomes[0].view.read_view_receipt
        assert receipt.startswith("read-view:")
        assert index.resolve_read_view_receipt(receipt).question_ids == (workflow.question_id,)
        receipts.append(receipt)
        revision = V3CandidateTriageRevision(
            revision_id=f"triage:{number}", attempt_id="attempt:a", sq_id=workflow.question_id,
            page_handle=page.page_handle, candidate_id=page.candidate_ids[0],
            kind="irrelevant", irrelevant_reason=IrrelevantReason.LEXICAL_FALSE_POSITIVE,
            basis=TriageBasis.READ_VIEW_RECEIPT, read_view_receipt=receipt,
        )
        current = runtime.submit_page_triage(
            V3EvidencePageTriageRequest(
                expected_content_hash=current.content_hash, submission_id=f"submission:{number}",
                attempt_id="attempt:a", page_handles=(page.page_handle,), revisions=(revision,),
            )
        ).state
    for identifier, old, term, rationale in (
        ("attempt:b", "attempt:a", "random", "Broaden terminology."),
        ("attempt:c", "attempt:b", "sequence", "Use issued synonym."),
    ):
        current = runtime.search_page(
            V3EvidenceSearchRequest(
                expected_content_hash=current.content_hash, attempt_id=identifier,
                query=SearchQuery(terms=(term,)), supersede_attempt_id=old,
                supersession_rationale=rationale, **target,
            )
        ).state
    scope = current.workflow.stage_scopes[0]
    outcome_payload = {
        "submission_id": "outcome:replay", "run_id": current.workflow.run_id,
        "result_id": current.workflow.result_id, "domain_id": current.workflow.domain_id,
        "question_id": current.workflow.question_id,
        "obligation_revision_id": current.workflow.obligation_revision_id,
        "obligation_hash": current.workflow.obligation_hash,
        "inventory_snapshot_hash": current.workflow.inventory_snapshot_hash,
        **{key: value for key, value in target.items() if key != "intent_id"},
        "materialized_scope_id": scope.scope_id,
        "outcome_kind": EvidenceCoverageStageOutcomeKind.OBLIGATION_SATISFIED,
        "rationale": "Exhaustive compact replay.", "trigger_dispositions": (), "content_hash": None,
    }
    unsigned_outcome = V3EvidenceStageOutcomeSubmission.model_construct(
        **(outcome_payload | {"content_hash": ""})
    )
    signed_outcome = unsigned_outcome.model_dump(mode="json")
    signed_outcome["content_hash"] = None
    outcome = V3EvidenceStageOutcomeSubmission.model_validate(
        signed_outcome | {"content_hash": canonical_hash(signed_outcome)}
    )
    current = runtime.submit_stage_outcome(expected_content_hash=current.content_hash, submission=outcome).state
    reloaded = runtime.load()
    return {
        "schema": "evidence-navigation-replay:3.0.0",
        "policy": {"search": policy.policy_id},
        "search_pages": [
            {"number": first.page.page_number, "candidates": list(first.page.candidate_ids), "complete": first.page.traversal_complete},
            {"number": second.page.page_number, "candidates": list(second.page.candidate_ids), "complete": second.page.traversal_complete},
        ],
        "selected_lineage": [
            {"id": item.attempt_id, "kind": item.kind.value, "before": item.supersedes_attempt_id, "after": item.superseded_by_attempt_id}
            for item in current.workflow.attempts
        ],
        "lineage_tail": next(item.attempt_id for item in current.workflow.attempts if item.kind is V3AttemptKind.SELECTED),
        "reloaded_state_hash": reloaded.content_hash,
        "outcome": current.workflow.stage_outcomes[0].outcome_kind.value,
        "read_receipt_count": len(receipts),
    }


def test_compact_v3_replay_is_generated_from_current_search_and_lineage(tmp_path: Path) -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _replay(tmp_path) == expected


def test_runtime_binds_identical_query_continuations_to_the_exact_attempt(tmp_path: Path) -> None:
    policy = EvidenceSearchPolicy(candidate_ceiling=1)
    runtime, _ = _runtime(tmp_path, policy)
    initial = runtime.initialize()
    target = {
        "proposition_id": "proposition:replay:test", "pass_id": "pass:replay:seed",
        "stage_id": "stage:replay:seed", "intent_id": "intent:replay:seed",
    }
    first = runtime.search_page(
        V3EvidenceSearchRequest(
            expected_content_hash=initial.content_hash, attempt_id="attempt:one",
            query=SearchQuery(terms=("allocation",)), **target,
        )
    )
    replacement = runtime.search_page(
        V3EvidenceSearchRequest(
            expected_content_hash=first.state.content_hash, attempt_id="attempt:two",
            query=SearchQuery(terms=("allocation",)), supersede_attempt_id="attempt:one",
            supersession_rationale="Restart the same exact query.", **target,
        )
    )
    assert replacement.page.page_handle != first.page.page_handle
    with pytest.raises(StaleSearchContinuation, match="different search attempt"):
        runtime.continue_search_page(
            V3EvidenceSearchContinuationRequest(
                expected_content_hash=replacement.state.content_hash, attempt_id="attempt:two",
                continuation=first.page.continuation,
                continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
            )
        )
    continued = runtime.continue_search_page(
        V3EvidenceSearchContinuationRequest(
            expected_content_hash=replacement.state.content_hash, attempt_id="attempt:two",
            continuation=replacement.page.continuation,
            continue_reason=SearchContinuationReason.COVERAGE_REQUIRES_BREADTH,
        )
    )
    assert continued.page.page_number == 2
