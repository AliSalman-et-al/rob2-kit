"""Pure, deterministic v3 evidence-obligation context materialization.

This module is deliberately independent of Run progress and public request
models.  It is the one place that turns an accepted static obligation and a
complete Source/Parse inventory into reducer-authorized scopes and bounded
orientation pages.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import (
    SourceAvailability,
    SourceCriticality,
    SourceProcessing,
    SourceRole,
)
from rob2_kit.evidence.obligations import (
    ChronologyConstraint,
    EvidenceNavigationIntent,
    EvidencePassActivation,
    EvidenceSearchObligation,
    EvidenceStageActivation,
    SourceSetRule,
)
from rob2_kit.evidence.workflow import (
    V3AuthorizedSource,
    V3ChronologyStatus,
    V3MaterializedStageScope,
    V3ScopeLimitationKind,
    V3SourceChronologyFact,
    V3StageScopeLimitation,
    _v3_inventory_hash,
)

EVIDENCE_CONTEXT_PAGE_POLICY_ID = "evidence-context-page:1.0.0"
"""The fixed, engine-owned page decomposition policy."""

EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT = 16


class EvidenceContextUnitOrientation(StrEnum):
    """The cheapest deterministic navigation shape known for a Source."""

    INDEXED_UNITS = "indexed_units"
    PAGES = "pages"


class EvidenceContextInventorySource(FrozenModel):
    """One accepted Source/Parse revision supplied to context materialization."""

    source_id: Identifier
    roles: tuple[SourceRole, ...]
    source_artifact_hash: ContentHash | None = None
    parse_id: Identifier | None = None
    parse_output_hash: ContentHash | None = None
    availability: SourceAvailability
    processing: SourceProcessing
    criticality: SourceCriticality
    page_count: int = Field(ge=0)
    indexed_unit_count: int = Field(ge=0)
    unit_orientation: EvidenceContextUnitOrientation
    chronology_facts: tuple[V3SourceChronologyFact, ...] = ()
    unresolved_potential_roles: tuple[SourceRole, ...] = ()
    lineage_source_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_source(self) -> EvidenceContextInventorySource:
        if not self.roles:
            raise ValueError("inventory Source roles must be non-empty")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("inventory Source roles must be unique")
        if len(self.unresolved_potential_roles) != len(set(self.unresolved_potential_roles)):
            raise ValueError("unresolved potential Source roles must be unique")
        if set(self.roles).intersection(self.unresolved_potential_roles):
            raise ValueError("a Source role cannot be both accepted and unresolved")
        facts = [item.constraint for item in self.chronology_facts]
        if len(facts) != len(set(facts)):
            raise ValueError("Source chronology facts must be unique per constraint")
        identity_values = (
            self.source_artifact_hash,
            self.parse_id,
            self.parse_output_hash,
        )
        if any(item is None for item in identity_values) and any(
            item is not None for item in identity_values
        ):
            raise ValueError(
                "inventory Source artifact and Parse identity must be complete together"
            )
        if self.is_searchable and not self.has_exact_source_parse:
            raise ValueError("acquired usable Source requires exact artifact and Parse identity")
        return self

    @property
    def has_exact_source_parse(self) -> bool:
        return (
            self.source_artifact_hash is not None
            and self.parse_id is not None
            and self.parse_output_hash is not None
        )

    @property
    def is_searchable(self) -> bool:
        return self.availability is SourceAvailability.ACQUIRED and self.processing in {
            SourceProcessing.USABLE,
            SourceProcessing.COVERAGE_LIMITED,
        }


class EvidenceContextInventory(FrozenModel):
    """The complete accepted inventory snapshot, before any stage selection."""

    inventory_id: Identifier
    sources: tuple[EvidenceContextInventorySource, ...]

    @model_validator(mode="after")
    def validate_sources(self) -> EvidenceContextInventory:
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("context inventory cannot repeat Source revisions")
        return self


class EvidenceContextPageEntryKind(StrEnum):
    SOURCE = "source"
    STAGE = "stage"


class EvidenceContextPageEntry(FrozenModel):
    """A compact page item; full immutable data remains on the materialization."""

    entry_id: Identifier
    kind: EvidenceContextPageEntryKind
    source_id: Identifier | None = None
    scope_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> EvidenceContextPageEntry:
        if (self.source_id is None) == (self.scope_id is None):
            raise ValueError("context page entry must reference exactly one Source or stage scope")
        if self.kind is EvidenceContextPageEntryKind.SOURCE and self.source_id is None:
            raise ValueError("a Source page entry must reference a Source")
        if self.kind is EvidenceContextPageEntryKind.STAGE and self.scope_id is None:
            raise ValueError("a stage page entry must reference a stage scope")
        return self


class EvidenceContextPage(FrozenModel):
    page_id: Identifier
    page_hash: ContentHash
    page_number: int = Field(ge=1)
    total_page_count: int = Field(ge=1)
    remaining_page_count: int = Field(ge=0)
    policy_id: str = EVIDENCE_CONTEXT_PAGE_POLICY_ID
    entries: tuple[EvidenceContextPageEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page(self) -> EvidenceContextPage:
        if self.remaining_page_count != self.total_page_count - self.page_number:
            raise ValueError("context page remaining count must match its position")
        payload = self.model_dump(mode="json")
        payload["page_hash"] = None
        if self.page_hash != canonical_hash(payload):
            raise ValueError("context page hash must bind its exact page content")
        return self


class EvidenceContextStage(FrozenModel):
    """One static stage with its exact reducer scope and orientation metadata."""

    proposition_id: Identifier
    pass_id: Identifier
    stage_id: Identifier
    pass_activation: EvidencePassActivation
    pass_activation_trigger_ids: tuple[str, ...]
    stage_activation: EvidenceStageActivation
    stage_activation_trigger_ids: tuple[str, ...]
    navigation_intents: tuple[EvidenceNavigationIntent, ...]
    scope: V3MaterializedStageScope
    recommended_source_ids: tuple[Identifier, ...]
    priority_hash: ContentHash
    immediate_static_blockers: tuple[V3StageScopeLimitation, ...] = ()

    @model_validator(mode="after")
    def validate_stage(self) -> EvidenceContextStage:
        if (
            self.proposition_id,
            self.pass_id,
            self.stage_id,
        ) != (
            self.scope.proposition_id,
            self.scope.pass_id,
            self.scope.stage_id,
        ):
            raise ValueError("context stage must bind its exact materialized scope")
        if set(self.recommended_source_ids) != set(self.scope.authorized_source_ids):
            raise ValueError("recommended Source order must cover exactly the stage scope")
        if len(self.recommended_source_ids) != len(set(self.recommended_source_ids)):
            raise ValueError("recommended Source order cannot repeat a Source")
        if self.immediate_static_blockers != self.scope.role_limitations:
            raise ValueError("context blockers must equal the materialized limitations")
        payload = {
            "scope_id": self.scope.scope_id,
            "recommended_source_ids": self.recommended_source_ids,
        }
        if self.priority_hash != canonical_hash(payload):
            raise ValueError("priority hash must bind the exact scope and Source order")
        return self


class EvidenceContextPass(FrozenModel):
    proposition_id: Identifier
    pass_id: Identifier
    activation: EvidencePassActivation
    activation_trigger_ids: tuple[str, ...]
    stages: tuple[EvidenceContextStage, ...] = Field(min_length=1)


class EvidenceContextProposition(FrozenModel):
    proposition_id: Identifier
    statement: str = Field(min_length=1)
    source_set_rule: SourceSetRule
    passes: tuple[EvidenceContextPass, ...] = Field(min_length=1)


class MaterializedEvidenceContext(FrozenModel):
    """Complete immutable context for one accepted static evidence obligation."""

    context_id: Identifier
    materialization_hash: ContentHash
    question_id: Identifier
    obligation: EvidenceSearchObligation
    obligation_hash: ContentHash
    inventory_id: Identifier
    inventory_snapshot_hash: ContentHash
    page_policy_id: str = EVIDENCE_CONTEXT_PAGE_POLICY_ID
    authorized_inventory: tuple[V3AuthorizedSource, ...]
    propositions: tuple[EvidenceContextProposition, ...]
    pages: tuple[EvidenceContextPage, ...]

    @model_validator(mode="after")
    def validate_materialization(self) -> MaterializedEvidenceContext:
        if self.question_id != self.obligation.question_id:
            raise ValueError("context question must bind its exact obligation")
        if self.obligation_hash != canonical_hash(self.obligation):
            raise ValueError("context obligation hash must bind its exact obligation")
        if self.inventory_snapshot_hash != _v3_inventory_hash(self.authorized_inventory):
            raise ValueError("context inventory hash must use the reducer canonical inventory rule")
        if self.page_policy_id != EVIDENCE_CONTEXT_PAGE_POLICY_ID:
            raise ValueError("context must use the fixed engine-owned page policy")
        static_stage_keys = tuple(
            (proposition.id, evidence_pass.id, stage.id)
            for proposition in self.obligation.propositions
            for evidence_pass in proposition.evidence_passes
            for stage in evidence_pass.coverage_stages
        )
        context_stages = tuple(
            stage
            for proposition in self.propositions
            for evidence_pass in proposition.passes
            for stage in evidence_pass.stages
        )
        if (
            tuple((stage.proposition_id, stage.pass_id, stage.stage_id) for stage in context_stages)
            != static_stage_keys
        ):
            raise ValueError("context must materialize every static obligation stage exactly once")
        relevant_roles = {
            role
            for proposition in self.obligation.propositions
            for role in proposition.accepted_source_roles
        }
        expected_entries = tuple(
            [
                EvidenceContextPageEntry(
                    entry_id=f"plan:{stage.scope.scope_id.split(':', maxsplit=1)[1]}",
                    kind=EvidenceContextPageEntryKind.STAGE,
                    scope_id=stage.scope.scope_id,
                )
                for stage in context_stages
            ]
            + [
                EvidenceContextPageEntry(
                    entry_id=f"source:{source.source_id.split(':', maxsplit=1)[1]}",
                    kind=EvidenceContextPageEntryKind.SOURCE,
                    source_id=source.source_id,
                )
                for source in sorted(self.authorized_inventory, key=lambda item: item.source_id)
                if set(source.roles).intersection(relevant_roles)
                or set(source.unresolved_potential_roles).intersection(relevant_roles)
            ]
        )
        page_entries = [entry for page in self.pages for entry in page.entries]
        if tuple(page_entries) != expected_entries:
            raise ValueError(
                "context pages must cover each static stage and relevant Source exactly once"
            )
        expected_page_count = (
            len(expected_entries) + EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT - 1
        ) // EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT
        if len(self.pages) != expected_page_count:
            raise ValueError("context pages must use the fixed page decomposition")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("context pages must use consecutive deterministic positions")
        if any(
            page.policy_id != self.page_policy_id
            or len(page.entries) > EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT
            or page.total_page_count != len(self.pages)
            for page in self.pages
        ):
            raise ValueError("context pages must share the fixed policy, bound, and total count")
        payload = self.model_dump(mode="json")
        payload["materialization_hash"] = None
        if self.materialization_hash != canonical_hash(payload):
            raise ValueError("materialization hash must bind the complete context")
        return self

    @property
    def stage_scopes(self) -> tuple[V3MaterializedStageScope, ...]:
        return tuple(
            stage.scope
            for proposition in self.propositions
            for evidence_pass in proposition.passes
            for stage in evidence_pass.stages
        )


def materialize_evidence_context(
    obligation: EvidenceSearchObligation,
    inventory: EvidenceContextInventory,
) -> MaterializedEvidenceContext:
    """Materialize every static stage and every obligation-relevant inventory item.

    The function has no Run, ledger, cursor, or caller-selected budget input;
    equal obligation and inventory values always yield equal scopes and pages.
    """

    sources = tuple(sorted(inventory.sources, key=lambda item: item.source_id))
    authorized_inventory = tuple(_authorized_source(item) for item in sources)
    inventory_snapshot_hash = _v3_inventory_hash(authorized_inventory)
    obligation_hash = canonical_hash(obligation)
    context_id = _stable_id(
        "context",
        {
            "obligation_hash": obligation_hash,
            "inventory_id": inventory.inventory_id,
            "inventory_snapshot_hash": inventory_snapshot_hash,
            "page_policy_id": EVIDENCE_CONTEXT_PAGE_POLICY_ID,
        },
    )

    propositions: list[EvidenceContextProposition] = []
    for proposition in obligation.propositions:
        passes: list[EvidenceContextPass] = []
        for evidence_pass in proposition.evidence_passes:
            stages: list[EvidenceContextStage] = []
            for stage in evidence_pass.coverage_stages:
                scope = _materialize_scope(
                    context_id=context_id,
                    proposition_id=proposition.id,
                    pass_id=evidence_pass.id,
                    stage=stage,
                    source_set_rule=proposition.source_set_rule,
                    sources=sources,
                    inventory_snapshot_hash=inventory_snapshot_hash,
                )
                recommended_source_ids = _recommended_source_order(scope, stage, sources)
                priority_hash = canonical_hash(
                    {
                        "scope_id": scope.scope_id,
                        "recommended_source_ids": recommended_source_ids,
                    }
                )
                stages.append(
                    EvidenceContextStage(
                        proposition_id=proposition.id,
                        pass_id=evidence_pass.id,
                        stage_id=stage.id,
                        pass_activation=evidence_pass.activation,
                        pass_activation_trigger_ids=evidence_pass.activation_trigger_ids,
                        stage_activation=stage.activation,
                        stage_activation_trigger_ids=stage.activation_trigger_ids,
                        navigation_intents=stage.navigation_intents,
                        scope=scope,
                        recommended_source_ids=recommended_source_ids,
                        priority_hash=priority_hash,
                        immediate_static_blockers=scope.role_limitations,
                    )
                )
            passes.append(
                EvidenceContextPass(
                    proposition_id=proposition.id,
                    pass_id=evidence_pass.id,
                    activation=evidence_pass.activation,
                    activation_trigger_ids=evidence_pass.activation_trigger_ids,
                    stages=tuple(stages),
                )
            )
        propositions.append(
            EvidenceContextProposition(
                proposition_id=proposition.id,
                statement=proposition.statement,
                source_set_rule=proposition.source_set_rule,
                passes=tuple(passes),
            )
        )

    pages = _materialize_pages(tuple(propositions), sources, obligation)
    payload = {
        "context_id": context_id,
        "materialization_hash": None,
        "question_id": obligation.question_id,
        "obligation": obligation.model_dump(mode="json"),
        "obligation_hash": obligation_hash,
        "inventory_id": inventory.inventory_id,
        "inventory_snapshot_hash": inventory_snapshot_hash,
        "page_policy_id": EVIDENCE_CONTEXT_PAGE_POLICY_ID,
        "authorized_inventory": tuple(
            item.model_dump(mode="json") for item in authorized_inventory
        ),
        "propositions": tuple(item.model_dump(mode="json") for item in propositions),
        "pages": tuple(item.model_dump(mode="json") for item in pages),
    }
    return MaterializedEvidenceContext(
        context_id=context_id,
        materialization_hash=canonical_hash(payload),
        question_id=obligation.question_id,
        obligation=obligation,
        obligation_hash=obligation_hash,
        inventory_id=inventory.inventory_id,
        inventory_snapshot_hash=inventory_snapshot_hash,
        authorized_inventory=authorized_inventory,
        propositions=tuple(propositions),
        pages=pages,
    )


def lookup_evidence_context_page(
    context: MaterializedEvidenceContext, page_id: Identifier
) -> EvidenceContextPage:
    """Return one pre-materialized page without accepting a public cursor."""

    for page in context.pages:
        if page.page_id == page_id:
            return page
    raise ValueError("unknown materialized evidence-context page")


def _authorized_source(source: EvidenceContextInventorySource) -> V3AuthorizedSource:
    return V3AuthorizedSource(
        source_id=source.source_id,
        roles=source.roles,
        source_artifact_hash=source.source_artifact_hash,
        parse_id=source.parse_id,
        parse_output_hash=source.parse_output_hash,
        chronology_facts=source.chronology_facts,
        availability=source.availability,
        processing=source.processing,
        criticality=source.criticality,
        page_count=source.page_count,
        indexed_unit_count=source.indexed_unit_count,
        unit_orientation=source.unit_orientation.value,
        unresolved_potential_roles=source.unresolved_potential_roles,
        lineage_source_id=source.lineage_source_id,
    )


def _materialize_scope(
    *,
    context_id: Identifier,
    proposition_id: Identifier,
    pass_id: Identifier,
    stage: object,
    source_set_rule: SourceSetRule,
    sources: tuple[EvidenceContextInventorySource, ...],
    inventory_snapshot_hash: ContentHash,
) -> V3MaterializedStageScope:
    # ``stage`` is deliberately structural: it is owned by the immutable
    # obligation model and has the fields validated during Guidance compilation.
    stage_roles = tuple(stage.applicable_source_roles)
    stage_constraints = tuple(stage.chronology_constraints)
    applicable = tuple(source for source in sources if set(source.roles).intersection(stage_roles))
    usable = tuple(source for source in applicable if _is_usable(source))
    selected = tuple(
        source for source in usable if _is_chronologically_applicable(source, stage_constraints)
    )
    limitations = _role_limitations(
        stage_roles=stage_roles,
        stage_constraints=stage_constraints,
        sources=sources,
        selected=selected,
    )
    limitations = (*limitations, *_chronology_limitations(applicable, stage_constraints))
    if source_set_rule is SourceSetRule.CROSS_SOURCE_COMPARISON and len(selected) < 2:
        limitations = (
            *limitations,
            V3StageScopeLimitation(
                source_set_rule=SourceSetRule.CROSS_SOURCE_COMPARISON,
                kind=V3ScopeLimitationKind.CROSS_SOURCE_INSUFFICIENT,
                rationale=(
                    "Cross-source comparison requires two distinct applicable Source revisions."
                ),
            ),
        )
    source_ids = tuple(source.source_id for source in selected)
    scope_id = _stable_id(
        "scope",
        {
            "context_id": context_id,
            "proposition_id": proposition_id,
            "pass_id": pass_id,
            "stage_id": stage.id,
            "inventory_snapshot_hash": inventory_snapshot_hash,
            "authorized_source_ids": source_ids,
        },
    )
    return V3MaterializedStageScope(
        scope_id=scope_id,
        proposition_id=proposition_id,
        pass_id=pass_id,
        stage_id=stage.id,
        authorized_source_ids=source_ids,
        authorized_source_scope_hash=canonical_hash(source_ids),
        chronology_constraints=stage_constraints,
        applicable_source_roles=stage_roles,
        source_set_rule=source_set_rule,
        role_limitations=limitations,
    )


def _role_limitations(
    *,
    stage_roles: tuple[SourceRole, ...],
    stage_constraints: tuple[ChronologyConstraint, ...],
    sources: tuple[EvidenceContextInventorySource, ...],
    selected: tuple[EvidenceContextInventorySource, ...],
) -> tuple[V3StageScopeLimitation, ...]:
    limitations: list[V3StageScopeLimitation] = []
    selected_roles = {role for source in selected for role in source.roles}
    for role in stage_roles:
        if role in selected_roles:
            continue
        candidates = tuple(
            source
            for source in sources
            if role in source.roles or role in source.unresolved_potential_roles
        )
        if candidates and any(
            source.availability is not SourceAvailability.ACQUIRED for source in candidates
        ):
            kind = V3ScopeLimitationKind.SOURCE_UNAVAILABLE
            rationale = (
                f"No acquired accepted Source revision is available for required role {role.value}."
            )
        elif candidates and any(not _is_usable(source) for source in candidates):
            kind = V3ScopeLimitationKind.MATERIAL_UNRESOLVED
            rationale = (
                f"No readable accepted Source revision is available for required role {role.value}."
            )
        elif candidates and stage_constraints:
            kind = V3ScopeLimitationKind.MATERIAL_UNRESOLVED
            rationale = (
                f"No accepted Source revision for required role {role.value} satisfies the "
                "stage chronology constraints."
            )
        else:
            kind = V3ScopeLimitationKind.MATERIAL_UNRESOLVED
            rationale = f"Required role {role.value} has no resolved accepted Source revision."
        limitations.append(V3StageScopeLimitation(role=role, kind=kind, rationale=rationale))
    return tuple(limitations)


def _chronology_limitations(
    applicable: tuple[EvidenceContextInventorySource, ...],
    constraints: tuple[ChronologyConstraint, ...],
) -> tuple[V3StageScopeLimitation, ...]:
    limitations: list[V3StageScopeLimitation] = []
    for constraint in constraints:
        if any(
            _chronology_status(source, constraint) is V3ChronologyStatus.UNRESOLVED
            for source in applicable
        ):
            limitations.append(
                V3StageScopeLimitation(
                    chronology_constraint=constraint,
                    kind=V3ScopeLimitationKind.CHRONOLOGY_UNRESOLVED,
                    rationale=(
                        "Potentially applicable Source chronology is unresolved for "
                        f"{constraint.value}."
                    ),
                )
            )
    return tuple(limitations)


def _recommended_source_order(
    scope: V3MaterializedStageScope,
    stage: object,
    sources: tuple[EvidenceContextInventorySource, ...],
) -> tuple[Identifier, ...]:
    by_id = {source.source_id: source for source in sources}
    role_order = {role: index for index, role in enumerate(stage.applicable_source_roles)}
    orientation_order = {
        EvidenceContextUnitOrientation.INDEXED_UNITS: 0,
        EvidenceContextUnitOrientation.PAGES: 1,
    }

    def priority(source_id: Identifier) -> tuple[int, int, int, int, str]:
        source = by_id[source_id]
        matching_roles = [role_order[role] for role in source.roles if role in role_order]
        chronology_relevance = sum(
            _chronology_status(source, constraint) is V3ChronologyStatus.SATISFIES
            for constraint in stage.chronology_constraints
        )
        projected_cost = (
            source.indexed_unit_count
            if source.unit_orientation is EvidenceContextUnitOrientation.INDEXED_UNITS
            else source.page_count
        )
        return (
            min(matching_roles),
            -chronology_relevance,
            orientation_order[source.unit_orientation],
            projected_cost,
            source.source_id,
        )

    return tuple(sorted(scope.authorized_source_ids, key=priority))


def _materialize_pages(
    propositions: tuple[EvidenceContextProposition, ...],
    sources: tuple[EvidenceContextInventorySource, ...],
    obligation: EvidenceSearchObligation,
) -> tuple[EvidenceContextPage, ...]:
    relevant_roles = {
        role
        for proposition in obligation.propositions
        for role in proposition.accepted_source_roles
    }
    entries = [
        EvidenceContextPageEntry(
            entry_id=f"plan:{stage.scope.scope_id.split(':', maxsplit=1)[1]}",
            kind=EvidenceContextPageEntryKind.STAGE,
            scope_id=stage.scope.scope_id,
        )
        for proposition in propositions
        for evidence_pass in proposition.passes
        for stage in evidence_pass.stages
    ]
    entries.extend(
        EvidenceContextPageEntry(
            entry_id=f"source:{source.source_id.split(':', maxsplit=1)[1]}",
            kind=EvidenceContextPageEntryKind.SOURCE,
            source_id=source.source_id,
        )
        for source in sources
        if set(source.roles).intersection(relevant_roles)
        or set(source.unresolved_potential_roles).intersection(relevant_roles)
    )
    chunks = tuple(
        tuple(entries[index : index + EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT])
        for index in range(0, len(entries), EVIDENCE_CONTEXT_PAGE_ENTRY_LIMIT)
    )
    # Every valid obligation has at least one stage, so the fixed decomposition
    # always produces at least one page.
    pages: list[EvidenceContextPage] = []
    for index, chunk in enumerate(chunks, start=1):
        payload = {
            "page_id": _stable_id(
                "page",
                {
                    "obligation_hash": canonical_hash(obligation),
                    "entry_ids": tuple(item.entry_id for item in chunk),
                    "page_number": index,
                    "policy_id": EVIDENCE_CONTEXT_PAGE_POLICY_ID,
                },
            ),
            "page_hash": None,
            "page_number": index,
            "total_page_count": len(chunks),
            "remaining_page_count": len(chunks) - index,
            "policy_id": EVIDENCE_CONTEXT_PAGE_POLICY_ID,
            "entries": tuple(item.model_dump(mode="json") for item in chunk),
        }
        pages.append(EvidenceContextPage(**(payload | {"page_hash": canonical_hash(payload)})))
    return tuple(pages)


def _is_usable(source: EvidenceContextInventorySource) -> bool:
    return source.is_searchable and source.has_exact_source_parse


def _is_chronologically_applicable(
    source: EvidenceContextInventorySource,
    constraints: tuple[ChronologyConstraint, ...],
) -> bool:
    return all(
        _chronology_status(source, constraint) is not V3ChronologyStatus.DOES_NOT_SATISFY
        for constraint in constraints
    )


def _chronology_status(
    source: EvidenceContextInventorySource, constraint: ChronologyConstraint
) -> V3ChronologyStatus:
    for fact in source.chronology_facts:
        if fact.constraint is constraint:
            return fact.status
    return V3ChronologyStatus.UNRESOLVED


def _stable_id(prefix: str, value: object) -> Identifier:
    return f"{prefix}:ctx-{canonical_hash(value).split(':', maxsplit=1)[1][:24]}"
