"""Focused coverage for pure v3 evidence-context materialization."""

from copy import deepcopy

import pytest

from rob2_kit.application.evidence_context import (
    EvidenceContextInventory,
    EvidenceContextInventorySource,
    EvidenceContextPageEntryKind,
    EvidenceContextUnitOrientation,
    lookup_evidence_context_page,
    materialize_evidence_context,
)
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.evidence.obligations import EvidenceSearchObligation
from rob2_kit.evidence.workflow import (
    V3ChronologyStatus,
    V3EvidenceWorkflowState,
    V3ScopeLimitationKind,
    V3SourceChronologyFact,
)


def _obligation(
    *,
    roles: tuple[SourceRole, ...] = (SourceRole.PRIMARY_REPORT,),
    chronology=(),
    rule="all_applicable_revisions",
) -> EvidenceSearchObligation:
    return EvidenceSearchObligation.model_validate(
        {
            "schema_version": "1.0.0",
            "question_id": "sq:context:test",
            "propositions": [
                {
                    "id": "proposition:context:test",
                    "statement": "A test proposition.",
                    "accepted_source_roles": [item.value for item in roles],
                    "chronology_constraints": list(chronology),
                    "source_set_rule": rule,
                    "evidence_passes": [
                        {
                            "id": "pass:context:seed",
                            "kind": "guidance_seed",
                            "coverage_stages": [
                                {
                                    "id": "stage:context:seed",
                                    "applicable_source_roles": [item.value for item in roles],
                                    "chronology_constraints": list(chronology),
                                    "navigation_intents": [
                                        {
                                            "id": "intent:context:seed",
                                            "kind": "search",
                                            "terms": ["allocation"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "pass:context:contradiction",
                            "kind": "contradiction",
                            "coverage_stages": [
                                {
                                    "id": "stage:context:contradiction",
                                    "applicable_source_roles": [item.value for item in roles],
                                    "chronology_constraints": list(chronology),
                                    "navigation_intents": [
                                        {
                                            "id": "intent:context:contradiction",
                                            "kind": "structural_read",
                                            "structural_targets": ["methods"],
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


def _source(
    number: int,
    *,
    roles: tuple[SourceRole, ...] = (SourceRole.PRIMARY_REPORT,),
    availability: SourceAvailability = SourceAvailability.ACQUIRED,
    processing: SourceProcessing = SourceProcessing.USABLE,
    criticality: SourceCriticality = SourceCriticality.EXPECTED,
    orientation: EvidenceContextUnitOrientation = EvidenceContextUnitOrientation.INDEXED_UNITS,
    page_count: int = 10,
    indexed_unit_count: int = 20,
    chronology_facts=(),
    unresolved_roles=(),
    with_source_parse_identity: bool = True,
) -> EvidenceContextInventorySource:
    return EvidenceContextInventorySource(
        source_id=f"source:{number:02d}",
        roles=roles,
        source_artifact_hash=(
            canonical_hash({"artifact": number}) if with_source_parse_identity else None
        ),
        parse_id=f"parse:{number:02d}" if with_source_parse_identity else None,
        parse_output_hash=(
            canonical_hash({"parse": number}) if with_source_parse_identity else None
        ),
        availability=availability,
        processing=processing,
        criticality=criticality,
        page_count=page_count,
        indexed_unit_count=indexed_unit_count,
        unit_orientation=orientation,
        chronology_facts=chronology_facts,
        unresolved_potential_roles=unresolved_roles,
    )


def _materialize(obligation: EvidenceSearchObligation, *sources: EvidenceContextInventorySource):
    return materialize_evidence_context(
        obligation,
        EvidenceContextInventory(inventory_id="inventory:context:test", sources=sources),
    )


def _first_stage(context):
    return context.propositions[0].passes[0].stages[0]


def _rehash_context_payload(payload: dict) -> None:
    for page in payload["pages"]:
        page["page_hash"] = None
        page["page_hash"] = canonical_hash(page)
    payload["materialization_hash"] = None
    payload["materialization_hash"] = canonical_hash(payload)


def test_complete_fixed_pages_cover_more_than_twenty_sources_without_duplication() -> None:
    context = _materialize(_obligation(), *(_source(index) for index in range(25)))
    source_entries = [
        entry.source_id
        for page in context.pages
        for entry in page.entries
        if entry.kind is EvidenceContextPageEntryKind.SOURCE
    ]

    assert len(context.pages) == 2
    assert source_entries == [f"source:{index:02d}" for index in range(25)]
    assert len(source_entries) == len(set(source_entries))
    assert context.pages[-1].remaining_page_count == 0
    assert lookup_evidence_context_page(context, context.pages[1].page_id) == context.pages[1]


def test_materialization_has_no_progress_input_and_is_stable() -> None:
    obligation = _obligation()
    inventory = EvidenceContextInventory(
        inventory_id="inventory:context:test", sources=(_source(2), _source(1))
    )

    first = materialize_evidence_context(obligation, inventory)
    second = materialize_evidence_context(obligation, inventory)

    assert first == second
    assert first.stage_scopes == second.stage_scopes
    assert first.pages == second.pages


def test_multirole_source_is_retained_once_and_satisfies_every_applicable_role() -> None:
    context = _materialize(
        _obligation(roles=(SourceRole.PRIMARY_REPORT, SourceRole.SUPPLEMENT)),
        _source(1, roles=(SourceRole.PRIMARY_REPORT, SourceRole.SUPPLEMENT)),
    )

    stage = _first_stage(context)
    assert stage.scope.authorized_source_ids == ("source:01",)
    assert not stage.scope.role_limitations


def test_all_distinct_applicable_revisions_are_retained_without_representative_selection() -> None:
    context = _materialize(_obligation(), _source(2), _source(1))

    assert _first_stage(context).scope.authorized_source_ids == ("source:01", "source:02")


def test_unavailable_unreadable_unresolved_roles_and_chronology_are_typed_limitations() -> None:
    chronology = "before_result_reporting"
    context = _materialize(
        _obligation(
            roles=(SourceRole.PRIMARY_REPORT, SourceRole.PROTOCOL), chronology=(chronology,)
        ),
        _source(
            1,
            availability=SourceAvailability.UNAVAILABLE,
            chronology_facts=(
                V3SourceChronologyFact(
                    constraint=chronology,
                    status=V3ChronologyStatus.UNRESOLVED,
                    rationale="The report date is not established.",
                ),
            ),
        ),
        _source(
            2,
            roles=(SourceRole.OTHER,),
            processing=SourceProcessing.FAILED,
            unresolved_roles=(SourceRole.PROTOCOL,),
        ),
    )

    limitations = _first_stage(context).scope.role_limitations
    assert {item.role for item in limitations if item.role} == {
        SourceRole.PRIMARY_REPORT,
        SourceRole.PROTOCOL,
    }
    assert V3ScopeLimitationKind.SOURCE_UNAVAILABLE in {item.kind for item in limitations}
    assert V3ScopeLimitationKind.MATERIAL_UNRESOLVED in {item.kind for item in limitations}
    assert V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED in {item.kind for item in limitations}


def test_domain_five_chronology_excludes_unqualified_report_and_blocks_visibly() -> None:
    chronology = "before_unblinded_outcome_data"
    context = _materialize(
        _obligation(chronology=(chronology,)),
        _source(
            1,
            chronology_facts=(
                V3SourceChronologyFact(
                    constraint=chronology,
                    status=V3ChronologyStatus.DOES_NOT_SATISFY,
                    rationale="Report was finalized after outcome-data unblinding.",
                ),
            ),
        ),
    )

    stage = _first_stage(context)
    assert stage.scope.authorized_source_ids == ()
    assert stage.immediate_static_blockers[0].role is SourceRole.PRIMARY_REPORT


def test_missing_chronology_fact_is_unresolved_but_navigable_in_constrained_scope() -> None:
    chronology = "before_unblinded_outcome_data"
    context = _materialize(_obligation(chronology=(chronology,)), _source(1))

    stage = _first_stage(context)
    assert stage.scope.authorized_source_ids == ("source:01",)
    assert V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED in {
        item.kind for item in stage.immediate_static_blockers
    }


def test_inventory_source_requires_at_least_one_accepted_role() -> None:
    with pytest.raises(ValueError, match="roles must be non-empty"):
        _source(1, roles=())


def test_unavailable_unparsed_source_is_retained_but_excluded_from_search_scope() -> None:
    context = _materialize(
        _obligation(),
        _source(
            1,
            availability=SourceAvailability.UNAVAILABLE,
            processing=SourceProcessing.NOT_ATTEMPTED,
            with_source_parse_identity=False,
        ),
    )

    source = context.authorized_inventory[0]
    stage = _first_stage(context)
    page_source_ids = {
        entry.source_id
        for page in context.pages
        for entry in page.entries
        if entry.kind is EvidenceContextPageEntryKind.SOURCE
    }
    assert not source.has_exact_source_parse
    assert stage.scope.authorized_source_ids == ()
    assert page_source_ids == {"source:01"}
    assert V3ScopeLimitationKind.SOURCE_UNAVAILABLE in {
        item.kind for item in stage.immediate_static_blockers
    }


def test_acquired_usable_source_without_exact_parse_identity_is_rejected() -> None:
    with pytest.raises(
        ValueError, match="acquired usable Source requires exact artifact and Parse"
    ):
        _source(1, with_source_parse_identity=False)


def test_cross_source_rule_requires_distinct_sources_even_when_one_source_has_two_roles() -> None:
    context = _materialize(
        _obligation(
            roles=(SourceRole.PRIMARY_REPORT, SourceRole.PROTOCOL),
            rule="cross_source_comparison",
        ),
        _source(1, roles=(SourceRole.PRIMARY_REPORT, SourceRole.PROTOCOL)),
    )

    assert V3ScopeLimitationKind.CROSS_SOURCE_INSUFFICIENT in {
        item.kind for item in _first_stage(context).immediate_static_blockers
    }


def test_criticality_never_changes_scope_or_recommended_traversal_priority() -> None:
    obligation = _obligation()
    first = _materialize(
        obligation,
        _source(1, criticality=SourceCriticality.OPTIONAL),
        _source(2, criticality=SourceCriticality.REQUIRED),
    )
    second = _materialize(
        obligation,
        _source(1, criticality=SourceCriticality.REQUIRED),
        _source(2, criticality=SourceCriticality.OPTIONAL),
    )

    assert (
        _first_stage(first).scope.authorized_source_ids
        == _first_stage(second).scope.authorized_source_ids
    )
    assert _first_stage(first).recommended_source_ids == ("source:01", "source:02")
    assert _first_stage(second).recommended_source_ids == ("source:01", "source:02")


def test_recommended_order_is_role_then_cheap_orientation_cost_then_stable_source_id() -> None:
    context = _materialize(
        _obligation(roles=(SourceRole.PRIMARY_REPORT, SourceRole.PROTOCOL)),
        _source(3, roles=(SourceRole.PROTOCOL,)),
        _source(2, orientation=EvidenceContextUnitOrientation.PAGES, page_count=1),
        _source(1, orientation=EvidenceContextUnitOrientation.INDEXED_UNITS, indexed_unit_count=30),
    )

    assert _first_stage(context).recommended_source_ids == (
        "source:01",
        "source:02",
        "source:03",
    )


def test_same_traversal_shape_uses_projected_unit_or_page_cost_before_source_id() -> None:
    indexed = _materialize(
        _obligation(),
        _source(1, indexed_unit_count=40),
        _source(2, indexed_unit_count=5),
    )
    pages = _materialize(
        _obligation(),
        _source(1, orientation=EvidenceContextUnitOrientation.PAGES, page_count=20),
        _source(2, orientation=EvidenceContextUnitOrientation.PAGES, page_count=3),
    )

    assert _first_stage(indexed).recommended_source_ids == ("source:02", "source:01")
    assert _first_stage(pages).recommended_source_ids == ("source:02", "source:01")


def test_materialized_hashes_are_accepted_by_reducer_and_tampering_fails() -> None:
    context = _materialize(_obligation(), _source(1))
    state = V3EvidenceWorkflowState(
        run_id="run:context:test",
        result_id="result:context:test",
        domain_id="domain:context:test",
        question_id=context.question_id,
        snapshot_hash=canonical_hash({"snapshot": 1}),
        obligation_revision_id="revision:context:obligation",
        obligation=_obligation(),
        obligation_hash=context.obligation_hash,
        inventory_snapshot_hash=context.inventory_snapshot_hash,
        authorized_inventory=context.authorized_inventory,
        search_policy_id="policy:context:search",
        search_policy_hash=canonical_hash({"search": 1}),
        read_policy_id="policy:context:read",
        read_policy_hash=canonical_hash({"read": 1}),
        visual_policy_id="policy:context:visual",
        visual_policy_hash=canonical_hash({"visual": 1}),
        stage_scopes=context.stage_scopes,
    )
    assert state.stage_scopes == context.stage_scopes

    tampered = deepcopy(context.model_dump())
    tampered["pages"][0]["entries"] = []
    with pytest.raises(ValueError):
        type(context).model_validate(tampered)


@pytest.mark.parametrize("mutation", ("delete", "replace"))
def test_rehashed_page_tampering_cannot_remove_or_replace_required_coverage(mutation: str) -> None:
    context = _materialize(_obligation(), _source(1), _source(2))
    tampered = context.model_dump(mode="json")
    entries = tampered["pages"][0]["entries"]
    if mutation == "delete":
        entries.pop()
    else:
        entries[0] = deepcopy(entries[1])
    _rehash_context_payload(tampered)

    with pytest.raises(ValueError, match="cover each static stage and relevant Source"):
        type(context).model_validate(tampered)
