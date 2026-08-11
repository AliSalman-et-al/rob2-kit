from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.domain.sources import SourceRole
from rob2_kit.evidence.obligations import (
    EvidenceCoverageStageOutcomeKind,
    EvidenceEscalationCondition,
    EvidenceNavigationIntent,
    EvidenceNavigationIntentKind,
    EvidenceSearchObligation,
    EvidenceStageActivation,
    compile_guidance_obligations,
)
from rob2_kit.logic.packs import (
    GuidancePack,
    load_guidance_pack,
    load_logic_pack,
    validate_guidance_compatibility,
)

PACK_ROOT = Path(__file__).parents[1] / "packs"


def _packs():
    logic = load_logic_pack(PACK_ROOT / "logic" / "rob2-parallel-assignment-2019.1.yaml")
    guidance = load_guidance_pack(
        PACK_ROOT / "guidance" / "rob2-parallel-assignment-en-2019.1.yaml"
    )
    return logic, guidance


def test_every_potentially_active_logic_question_has_one_static_plan() -> None:
    logic, guidance = _packs()

    validate_guidance_compatibility(logic, guidance)

    assert {plan.question_id for plan in guidance.obligations} == {
        question.id for question in logic.questions
    }
    assert all(
        {pass_.kind.value for pass_ in proposition.evidence_passes}
        >= {"guidance_seed", "contradiction"}
        for plan in guidance.obligations
        for proposition in plan.propositions
    )


def test_compiler_rejects_missing_duplicate_and_unknown_question_plans() -> None:
    logic, guidance = _packs()
    base = guidance.model_dump(exclude={"content_hash"})

    missing = deepcopy(base)
    missing["obligations"] = missing["obligations"][1:]
    with pytest.raises(ValueError, match="missing="):
        validate_guidance_compatibility(logic, GuidancePack.model_validate(missing))

    without_contract = deepcopy(base)
    without_contract.pop("obligations")
    with pytest.raises(ValidationError, match="obligations"):
        GuidancePack.model_validate(without_contract)

    duplicate = deepcopy(base)
    duplicate["obligations"] = (*duplicate["obligations"], duplicate["obligations"][0])
    with pytest.raises(ValueError, match="duplicate"):
        validate_guidance_compatibility(logic, GuidancePack.model_validate(duplicate))

    unknown = deepcopy(base)
    unknown["obligations"][0]["question_id"] = "sq:unknown:question"
    with pytest.raises(ValueError, match="unknown="):
        validate_guidance_compatibility(logic, GuidancePack.model_validate(unknown))


def test_obligation_rejects_cycles_and_invalid_navigation_shapes() -> None:
    _, guidance = _packs()
    plan = deepcopy(guidance.obligations[0].model_dump())
    plan["escalation_triggers"][0]["target_stage_id"] = plan["escalation_triggers"][0][
        "source_stage_id"
    ]
    with pytest.raises(ValidationError, match="later stage"):
        EvidenceSearchObligation.model_validate(plan)

    with pytest.raises(ValidationError, match="requires terms"):
        EvidenceNavigationIntent(
            id="intent:test:search",
            kind=EvidenceNavigationIntentKind.SEARCH,
        )


def test_canonical_roles_stages_and_closed_outcomes_are_explicit() -> None:
    _, guidance = _packs()
    canonical = set(SourceRole)
    for plan in guidance.obligations:
        for proposition in plan.propositions:
            assert set(proposition.accepted_source_roles) <= canonical
            for evidence_pass in proposition.evidence_passes:
                for stage in evidence_pass.coverage_stages:
                    assert stage.applicable_source_roles
                    assert set(stage.applicable_source_roles) <= set(
                        proposition.accepted_source_roles
                    )
                    assert "outcome_kind" not in stage.model_dump()
    assert set(EvidenceCoverageStageOutcomeKind).isdisjoint(set(EvidenceEscalationCondition))
    assert EvidenceCoverageStageOutcomeKind.OBLIGATION_SATISFIED.value == "obligation_satisfied"
    assert "maximum_source_count" not in EvidenceNavigationIntent.model_fields


def test_cheap_first_and_domain_five_chronology_are_static() -> None:
    _, guidance = _packs()
    domain_five = [
        item for item in guidance.obligations if item.question_id.startswith("sq:selection:")
    ]
    assert len(domain_five) == 3
    for plan in domain_five:
        proposition = plan.propositions[0]
        seed, contradiction = proposition.evidence_passes
        assert len(seed.coverage_stages) == 2
        first_stage, plan_stage = seed.coverage_stages
        assert first_stage.applicable_source_roles == (SourceRole.PRIMARY_REPORT,)
        assert {
            SourceRole.PROTOCOL,
            SourceRole.STATISTICAL_ANALYSIS_PLAN,
            SourceRole.REGISTRY_CURRENT,
            SourceRole.REGISTRY_HISTORY,
        } <= set(plan_stage.applicable_source_roles)
        assert plan_stage.activation is EvidenceStageActivation.MANDATORY
        assert not plan_stage.activation_trigger_ids
        assert "before_unblinded_outcome_data" in plan_stage.chronology_constraints
        contradiction_stage = contradiction.coverage_stages[0]
        assert set(plan_stage.applicable_source_roles) <= set(
            contradiction_stage.applicable_source_roles
        )
        assert "before_unblinded_outcome_data" in contradiction_stage.chronology_constraints
    non_domain_five = next(
        item for item in guidance.obligations if item.question_id == "sq:randomization:sequence"
    )
    triggered_stage = non_domain_five.propositions[0].evidence_passes[0].coverage_stages[1]
    trigger = non_domain_five.escalation_triggers[0]
    assert triggered_stage.activation is EvidenceStageActivation.TRIGGERED
    assert triggered_stage.activation_trigger_ids == (trigger.id,)
    assert trigger.target_stage_id == triggered_stage.id

    invalid = deepcopy(domain_five[1].model_dump())
    invalid["propositions"][0]["evidence_passes"][0]["coverage_stages"][1][
        "chronology_constraints"
    ] = ()
    with pytest.raises(ValidationError, match="chronology"):
        EvidenceSearchObligation.model_validate(invalid)


def test_domains_one_to_four_widen_contradiction_search_only_on_findings() -> None:
    _, guidance = _packs()
    companion_roles = {
        SourceRole.SECONDARY_REPORT,
        SourceRole.SUPPLEMENT,
        SourceRole.PROTOCOL,
        SourceRole.STATISTICAL_ANALYSIS_PLAN,
        SourceRole.REGISTRY_CURRENT,
        SourceRole.REGISTRY_HISTORY,
    }
    plans = [
        plan for plan in guidance.obligations if not plan.question_id.startswith("sq:selection:")
    ]
    assert len(plans) == 19

    for plan in plans:
        proposition = plan.propositions[0]
        seed = next(
            evidence_pass
            for evidence_pass in proposition.evidence_passes
            if evidence_pass.kind.value == "guidance_seed"
        )
        contradiction = next(
            evidence_pass
            for evidence_pass in proposition.evidence_passes
            if evidence_pass.kind.value == "contradiction"
        )
        primary_stage, widening_stage = contradiction.coverage_stages

        assert seed.coverage_stages[0].applicable_source_roles == (SourceRole.PRIMARY_REPORT,)
        assert primary_stage.applicable_source_roles == (SourceRole.PRIMARY_REPORT,)
        assert primary_stage.activation is EvidenceStageActivation.MANDATORY
        assert companion_roles <= set(widening_stage.applicable_source_roles)
        assert widening_stage.activation is EvidenceStageActivation.TRIGGERED

        widening_triggers = {
            trigger.id: trigger
            for trigger in plan.escalation_triggers
            if trigger.target_stage_id == widening_stage.id
        }
        assert {trigger.condition for trigger in widening_triggers.values()} == {
            EvidenceEscalationCondition.CONFLICTING_EVIDENCE,
            EvidenceEscalationCondition.STRUCTURAL_AMBIGUITY,
        }
        assert set(widening_stage.activation_trigger_ids) == set(widening_triggers)
        assert {trigger.source_stage_id for trigger in widening_triggers.values()} == {
            primary_stage.id
        }


def test_compilation_summary_is_deterministic_and_propositions_require_passes() -> None:
    logic, guidance = _packs()
    first = compile_guidance_obligations(logic, guidance)
    second = compile_guidance_obligations(logic, guidance)
    assert first == second
    assert first.cardinality.model_dump() == {
        "propositions": 22,
        "passes": 44,
        "stages": 85,
        "intents": 85,
        "triggers": 57,
    }

    plan = deepcopy(guidance.obligations[0].model_dump())
    plan["propositions"][0]["evidence_passes"] = plan["propositions"][0]["evidence_passes"][1:]
    with pytest.raises(ValidationError, match="each proposition lacks mandatory"):
        EvidenceSearchObligation.model_validate(plan)
