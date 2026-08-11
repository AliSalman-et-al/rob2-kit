"""Static, versioned evidence-obligation language for Guidance packs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.sources import SourceRole


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidencePassKind(StrEnum):
    GUIDANCE_SEED = "guidance_seed"
    TRIAL_FOLLOW_UP = "trial_follow_up"
    CONTRADICTION = "contradiction"


class EvidenceNavigationIntentKind(StrEnum):
    SEARCH = "search"
    STRUCTURAL_READ = "structural_read"
    LOCATOR_FOLLOW_UP = "locator_follow_up"
    VISUAL_REVIEW = "visual_review"


class ChronologyConstraint(StrEnum):
    BEFORE_RANDOMIZATION = "before_randomization"
    BEFORE_UNBLINDED_OUTCOME_DATA = "before_unblinded_outcome_data"
    BEFORE_RESULT_REPORTING = "before_result_reporting"
    AFTER_RANDOMIZATION = "after_randomization"


class SourceSetRule(StrEnum):
    ALL_APPLICABLE_REVISIONS = "all_applicable_revisions"
    EACH_DECLARED_ROLE_WHEN_AVAILABLE = "each_declared_role_when_available"
    CROSS_SOURCE_COMPARISON = "cross_source_comparison"


class EvidenceCoverageStageOutcomeKind(StrEnum):
    OBLIGATION_SATISFIED = "obligation_satisfied"
    ESCALATION_REQUIRED = "escalation_required"
    SOURCE_UNAVAILABLE_AFTER_ATTEMPT = "source_unavailable_after_attempt"
    SCOPE_LIMITATION_UNRESOLVED = "scope_limitation_unresolved"
    SEMANTIC_UNCERTAINTY_UNRESOLVED = "semantic_uncertainty_unresolved"


class EvidenceEscalationCondition(StrEnum):
    NO_DIRECT_EVIDENCE = "no_direct_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    CHRONOLOGY_UNRESOLVED = "chronology_unresolved"
    SOURCE_ROLE_UNAVAILABLE = "source_role_unavailable"
    STRUCTURAL_AMBIGUITY = "structural_ambiguity"


class EvidencePassActivation(StrEnum):
    MANDATORY = "mandatory"
    GUIDANCE_DECLARED = "guidance_declared"
    TRIGGERED = "triggered"


class EvidenceStageActivation(StrEnum):
    MANDATORY = "mandatory"
    TRIGGERED = "triggered"


class EvidenceNavigationIntent(_FrozenModel):
    """One purpose for a later evidence-navigation operation, never a source cap."""

    id: str = Field(pattern=r"^intent:[a-z0-9:-]+$")
    kind: EvidenceNavigationIntentKind
    terms: tuple[str, ...] = Field(default=(), max_length=12)
    structural_targets: tuple[str, ...] = Field(default=(), max_length=12)
    depends_on_intent_ids: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_shape(self) -> EvidenceNavigationIntent:
        if self.kind is EvidenceNavigationIntentKind.SEARCH and not self.terms:
            raise ValueError("lexical Search intent requires terms")
        if self.kind is not EvidenceNavigationIntentKind.SEARCH and not self.structural_targets:
            raise ValueError("non-Search navigation intent requires structural targets")
        if (
            self.kind is EvidenceNavigationIntentKind.LOCATOR_FOLLOW_UP
            and not self.depends_on_intent_ids
        ):
            raise ValueError("locator follow-up intent requires a prior intent")
        if (
            self.kind is not EvidenceNavigationIntentKind.LOCATOR_FOLLOW_UP
            and self.depends_on_intent_ids
        ):
            raise ValueError("only locator follow-up intents may depend on another intent")
        return self


class EvidenceCoverageStage(_FrozenModel):
    """An ordered additive source scope; runtime work records its outcome later."""

    id: str = Field(pattern=r"^stage:[a-z0-9:-]+$")
    applicable_source_roles: tuple[SourceRole, ...] = Field(min_length=1, max_length=12)
    chronology_constraints: tuple[ChronologyConstraint, ...] = Field(default=(), max_length=4)
    activation: EvidenceStageActivation = EvidenceStageActivation.MANDATORY
    activation_trigger_ids: tuple[str, ...] = Field(default=(), max_length=12)
    navigation_intents: tuple[EvidenceNavigationIntent, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_roles(self) -> EvidenceCoverageStage:
        if len(set(self.applicable_source_roles)) != len(self.applicable_source_roles):
            raise ValueError("stage source roles must be unique")
        return self


class EvidencePass(_FrozenModel):
    """A named pass through one proposition's explicitly staged source scopes."""

    id: str = Field(pattern=r"^pass:[a-z0-9:-]+$")
    kind: EvidencePassKind
    activation: EvidencePassActivation = EvidencePassActivation.MANDATORY
    guidance_condition: str = ""
    activation_trigger_ids: tuple[str, ...] = Field(default=(), max_length=12)
    coverage_stages: tuple[EvidenceCoverageStage, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_activation(self) -> EvidencePass:
        if self.kind in {EvidencePassKind.GUIDANCE_SEED, EvidencePassKind.CONTRADICTION}:
            if self.activation is not EvidencePassActivation.MANDATORY:
                raise ValueError(f"{self.kind.value} pass must be mandatory")
        elif self.activation is EvidencePassActivation.MANDATORY:
            raise ValueError("trial follow-up must be guidance-declared or triggered")
        if self.activation is EvidencePassActivation.GUIDANCE_DECLARED:
            if not self.guidance_condition.strip() or self.activation_trigger_ids:
                raise ValueError("guidance-declared pass requires only a guidance condition")
        elif self.activation is EvidencePassActivation.TRIGGERED:
            if not self.activation_trigger_ids or self.guidance_condition:
                raise ValueError("triggered pass requires only activation trigger IDs")
        elif self.guidance_condition or self.activation_trigger_ids:
            raise ValueError("mandatory pass cannot declare conditional activation")
        return self


class EvidentiaryProposition(_FrozenModel):
    """A question-specific claim with finite acceptable roles and staged passes."""

    id: str = Field(pattern=r"^proposition:[a-z0-9:-]+$")
    statement: str = Field(min_length=1)
    accepted_source_roles: tuple[SourceRole, ...] = Field(min_length=1, max_length=12)
    chronology_constraints: tuple[ChronologyConstraint, ...] = Field(default=(), max_length=4)
    source_set_rule: SourceSetRule = SourceSetRule.ALL_APPLICABLE_REVISIONS
    evidence_passes: tuple[EvidencePass, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def validate_proposition(self) -> EvidentiaryProposition:
        if len(set(self.accepted_source_roles)) != len(self.accepted_source_roles):
            raise ValueError("proposition source roles must be unique")
        kinds = {item.kind for item in self.evidence_passes}
        required = {EvidencePassKind.GUIDANCE_SEED, EvidencePassKind.CONTRADICTION}
        if missing := required - kinds:
            raise ValueError(
                "each proposition lacks mandatory evidence passes: "
                f"{sorted(item.value for item in missing)}"
            )
        for evidence_pass in self.evidence_passes:
            for stage in evidence_pass.coverage_stages:
                if not set(stage.applicable_source_roles).issubset(self.accepted_source_roles):
                    raise ValueError("stage source roles must be a subset of proposition roles")
                if not set(stage.chronology_constraints).issubset(self.chronology_constraints):
                    raise ValueError(
                        "stage chronology constraints must be a subset of proposition constraints"
                    )
        mandatory_roles = {
            role
            for evidence_pass in self.evidence_passes
            for stage in evidence_pass.coverage_stages
            if stage.activation is EvidenceStageActivation.MANDATORY
            for role in stage.applicable_source_roles
        }
        if self.source_set_rule is SourceSetRule.EACH_DECLARED_ROLE_WHEN_AVAILABLE and not set(
            self.accepted_source_roles
        ).issubset(mandatory_roles):
            raise ValueError("each-role source rule requires mandatory stages to cover every role")
        if (
            self.source_set_rule is SourceSetRule.CROSS_SOURCE_COMPARISON
            and len(mandatory_roles.intersection(self.accepted_source_roles)) < 2
        ):
            raise ValueError("cross-source rule requires mandatory stages to cover two roles")
        if self.chronology_constraints:
            required_chronology = set(self.chronology_constraints)
            mandatory_stages = [
                stage
                for evidence_pass in self.evidence_passes
                for stage in evidence_pass.coverage_stages
                if stage.activation is EvidenceStageActivation.MANDATORY
            ]
            if not any(
                required_chronology.issubset(stage.chronology_constraints)
                for stage in mandatory_stages
            ):
                raise ValueError(
                    "proposition chronology constraints must be exercised by a mandatory stage"
                )
            chronology_roles = {
                SourceRole.PROTOCOL,
                SourceRole.STATISTICAL_ANALYSIS_PLAN,
                SourceRole.REGISTRY_CURRENT,
                SourceRole.REGISTRY_HISTORY,
            }
            for stage in mandatory_stages:
                if set(stage.applicable_source_roles).intersection(
                    chronology_roles
                ) and not required_chronology.issubset(stage.chronology_constraints):
                    raise ValueError(
                        "mandatory dated plan stages must exercise proposition chronology"
                    )
        return self


class EvidenceEscalationTrigger(_FrozenModel):
    """A closed finding that activates a later stage; it is not a stage outcome."""

    id: str = Field(pattern=r"^trigger:[a-z0-9:-]+$")
    condition: EvidenceEscalationCondition
    source_stage_id: str = Field(pattern=r"^stage:[a-z0-9:-]+$")
    target_stage_id: str = Field(pattern=r"^stage:[a-z0-9:-]+$")


class EvidenceSearchObligation(_FrozenModel):
    """The complete finite plan required before one signaling question activates."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    question_id: str = Field(pattern=r"^sq:[a-z0-9:-]+$")
    propositions: tuple[EvidentiaryProposition, ...] = Field(min_length=1, max_length=8)
    escalation_triggers: tuple[EvidenceEscalationTrigger, ...] = Field(default=(), max_length=48)

    @model_validator(mode="after")
    def validate_plan(self) -> EvidenceSearchObligation:
        proposition_ids = [item.id for item in self.propositions]
        pass_items = [
            item for proposition in self.propositions for item in proposition.evidence_passes
        ]
        pass_ids = [item.id for item in pass_items]
        stages = [stage for item in pass_items for stage in item.coverage_stages]
        stage_ids = [item.id for item in stages]
        intents = [intent for stage in stages for intent in stage.navigation_intents]
        intent_ids = [item.id for item in intents]
        trigger_ids = [item.id for item in self.escalation_triggers]
        for label, values in (
            ("proposition", proposition_ids),
            ("pass", pass_ids),
            ("stage", stage_ids),
            ("intent", intent_ids),
            ("trigger", trigger_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"obligation {label} IDs must be unique")
        stage_index = {item.id: index for index, item in enumerate(stages)}
        intent_index = {item.id: index for index, item in enumerate(intents)}
        for intent in intents:
            if any(reference not in intent_index for reference in intent.depends_on_intent_ids):
                raise ValueError("navigation intent references an unknown intent")
            if any(
                intent_index[reference] >= intent_index[intent.id]
                for reference in intent.depends_on_intent_ids
            ):
                raise ValueError("navigation intents must depend only on earlier intents")
        trigger_by_id = {item.id: item for item in self.escalation_triggers}
        for trigger in self.escalation_triggers:
            if (
                trigger.source_stage_id not in stage_index
                or trigger.target_stage_id not in stage_index
            ):
                raise ValueError("escalation trigger references an unknown stage")
            if stage_index[trigger.source_stage_id] >= stage_index[trigger.target_stage_id]:
                raise ValueError("escalation triggers must target a later stage")
        for evidence_pass in pass_items:
            if any(
                reference not in trigger_by_id for reference in evidence_pass.activation_trigger_ids
            ):
                raise ValueError("evidence pass references an unknown activation trigger")
            for index, stage in enumerate(evidence_pass.coverage_stages):
                if index == 0 and (
                    stage.activation is not EvidenceStageActivation.MANDATORY
                    or stage.activation_trigger_ids
                ):
                    raise ValueError("the first stage in a pass must be unconditionally available")
                if (
                    stage.activation is EvidenceStageActivation.MANDATORY
                    and stage.activation_trigger_ids
                ):
                    raise ValueError("a mandatory stage cannot declare activation triggers")
                if (
                    stage.activation is EvidenceStageActivation.TRIGGERED
                    and not stage.activation_trigger_ids
                ):
                    raise ValueError("a triggered stage requires activation triggers")
                for reference in stage.activation_trigger_ids:
                    trigger = trigger_by_id.get(reference)
                    if trigger is None:
                        raise ValueError("stage references an unknown activation trigger")
                    if trigger.target_stage_id != stage.id:
                        raise ValueError("stage activation trigger must target that later stage")
        return self


class ObligationCardinalitySummary(_FrozenModel):
    propositions: int = Field(ge=1)
    passes: int = Field(ge=1)
    stages: int = Field(ge=1)
    intents: int = Field(ge=1)
    triggers: int = Field(ge=0)


class GuidanceObligationCompilation(_FrozenModel):
    obligations: tuple[EvidenceSearchObligation, ...]
    cardinality: ObligationCardinalitySummary


def compile_guidance_obligations(logic: object, guidance: object) -> GuidanceObligationCompilation:
    """Validate exact Logic coverage and produce a deterministic plan summary."""

    logic_question_ids = {question.id for question in logic.questions}
    obligations = tuple(guidance.obligations)
    obligation_ids = [item.question_id for item in obligations]
    if len(obligation_ids) != len(set(obligation_ids)):
        raise ValueError("Guidance obligations cannot duplicate a Logic question")
    unknown = set(obligation_ids) - logic_question_ids
    missing = logic_question_ids - set(obligation_ids)
    if unknown or missing:
        raise ValueError(
            "Guidance obligations must cover every Logic question exactly once: "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    passes = [
        item
        for plan in obligations
        for proposition in plan.propositions
        for item in proposition.evidence_passes
    ]
    stages = [item for evidence_pass in passes for item in evidence_pass.coverage_stages]
    intents = [item for stage in stages for item in stage.navigation_intents]
    return GuidanceObligationCompilation(
        obligations=obligations,
        cardinality=ObligationCardinalitySummary(
            propositions=sum(len(item.propositions) for item in obligations),
            passes=len(passes),
            stages=len(stages),
            intents=len(intents),
            triggers=sum(len(item.escalation_triggers) for item in obligations),
        ),
    )
