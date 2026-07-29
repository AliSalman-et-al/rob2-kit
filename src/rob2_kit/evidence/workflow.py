"""Complete-search receipts, exact claims, derived facts, and frozen bundles."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.domain.evidence import VerificationStatus
from rob2_kit.domain.revisions import (
    ContentHash,
    FrozenModel,
    Identifier,
    RecordReference,
)
from rob2_kit.evidence.search import CanonicalEvidenceUnit, SearchQuery


class SearchPassKind(StrEnum):
    GUIDANCE_SEED = "guidance_seed"
    TRIAL_FOLLOW_UP = "trial_follow_up"
    CONTRADICTION = "contradiction"


class SearchResultDispositionKind(StrEnum):
    IRRELEVANT = "irrelevant"
    RETAINED_CANDIDATE = "retained_candidate"
    DUPLICATE = "duplicate"


class SearchResultDisposition(FrozenModel):
    unit_id: Identifier
    kind: SearchResultDispositionKind
    candidate_id: Identifier | None = None
    duplicate_of: Identifier | None = None

    @model_validator(mode="after")
    def validate_duplicate(self) -> SearchResultDisposition:
        if self.kind is SearchResultDispositionKind.DUPLICATE and self.duplicate_of is None:
            raise ValueError("duplicate search results require the covered unit ID")
        if self.kind is not SearchResultDispositionKind.DUPLICATE and self.duplicate_of is not None:
            raise ValueError("duplicate_of is only valid for duplicate search results")
        retained = self.kind is SearchResultDispositionKind.RETAINED_CANDIDATE
        if retained != (self.candidate_id is not None):
            raise ValueError("retained search results require exactly one candidate ID")
        return self


class SourceSearchState(StrEnum):
    SEARCHED = "searched"
    UNOBTAINED = "unobtained"
    UNREADABLE = "unreadable"
    UNSEARCHED = "unsearched"
    SEARCH_LIMITED = "search_limited"


class SourceSearchCoverage(FrozenModel):
    source_id: Identifier
    state: SourceSearchState
    sufficiently_readable: bool


class VisualCandidateCoverage(FrozenModel):
    candidate_id: Identifier
    dispositioned: bool
    required: bool


class ExecutedSearchQuery(FrozenModel):
    query: SearchQuery
    query_hash: ContentHash
    pass_kind: SearchPassKind
    seed_family: Identifier | None = None
    returned_unit_ids: tuple[Identifier, ...]
    traversal_complete: bool
    broad_query: bool = False
    broad_query_justification: str | None = None

    @model_validator(mode="after")
    def validate_query(self) -> ExecutedSearchQuery:
        if self.query_hash != canonical_hash(self.query):
            raise ValueError("query hash must bind the exact structured query and filters")
        if self.pass_kind is SearchPassKind.GUIDANCE_SEED and self.seed_family is None:
            raise ValueError("Guidance-seed queries require their seed family")
        if self.pass_kind is not SearchPassKind.GUIDANCE_SEED and self.seed_family is not None:
            raise ValueError("seed families apply only to Guidance-seed queries")
        if self.broad_query and not self.broad_query_justification:
            raise ValueError("broad queries require a complete-traversal justification")
        return self


class SearchCoverageReceipt(FrozenModel):
    receipt_id: Identifier
    sq_id: Identifier
    snapshot_hash: ContentHash
    policy_id: Identifier
    result_spec: RecordReference
    source_inventory: RecordReference
    parse_record_hashes: tuple[ContentHash, ...]
    guidance_release_id: Identifier
    project_rule_ids: tuple[Identifier, ...] = ()
    coverage_limits: tuple[str, ...] = ()
    required_seed_families: tuple[Identifier, ...]
    completed_seed_families: tuple[Identifier, ...]
    completed_passes: tuple[SearchPassKind, ...]
    executed_queries: tuple[ExecutedSearchQuery, ...]
    returned_unit_ids: tuple[Identifier, ...]
    result_dispositions: tuple[SearchResultDisposition, ...]
    sources: tuple[SourceSearchCoverage, ...]
    inventory_source_ids: tuple[Identifier, ...]
    visual_candidates: tuple[VisualCandidateCoverage, ...] = ()
    latest_complete_round_new_material_candidates: int = Field(ge=0)
    traversal_complete: bool
    interrupted: bool
    broad_query_justifications: tuple[str, ...] = ()
    stopping_reason: str = (
        "mandatory protocol complete; latest complete round found no new material"
    )

    @model_validator(mode="after")
    def validate_protocol_accounting(self) -> SearchCoverageReceipt:
        passes = set(self.completed_passes)
        missing_passes = set(SearchPassKind) - passes
        if missing_passes:
            names = ", ".join(sorted(item.value for item in missing_passes))
            raise ValueError(f"mandatory search pass missing: {names}")
        missing_seeds = set(self.required_seed_families) - set(self.completed_seed_families)
        if missing_seeds:
            raise ValueError(f"mandatory Guidance seed families missing: {sorted(missing_seeds)}")
        executed_passes = {item.pass_kind for item in self.executed_queries}
        if executed_passes != passes:
            raise ValueError("completed passes must match the attributable executed queries")
        executed_seeds = {
            item.seed_family for item in self.executed_queries if item.seed_family is not None
        }
        if executed_seeds != set(self.completed_seed_families):
            raise ValueError("completed seed families must match the attributable queries")
        if self.traversal_complete and any(
            not item.traversal_complete for item in self.executed_queries
        ):
            raise ValueError("coverage cannot be complete while a query traversal is incomplete")
        returned = set(self.returned_unit_ids)
        query_returns = {
            unit_id for query in self.executed_queries for unit_id in query.returned_unit_ids
        }
        if returned != query_returns:
            raise ValueError("receipt results must match the union of executed-query results")
        disposition_ids = [item.unit_id for item in self.result_dispositions]
        if len(disposition_ids) != len(set(disposition_ids)):
            raise ValueError("each unique returned unit must have one disposition")
        if returned != set(disposition_ids):
            raise ValueError("every unique returned unit must have one disposition")
        if self.latest_complete_round_new_material_candidates != 0 and self.traversal_complete:
            raise ValueError(
                "search cannot stop while the latest complete round found new material"
            )
        if set(self.inventory_source_ids) != {source.source_id for source in self.sources}:
            raise ValueError("source coverage must account for the bound source inventory")
        return self

    def is_complete(self) -> bool:
        return (
            self.traversal_complete
            and not self.interrupted
            and self.latest_complete_round_new_material_candidates == 0
        )

    def establishes_no_information_basis(self) -> bool:
        return (
            self.is_complete()
            and bool(self.sources)
            and all(
                source.state is SourceSearchState.SEARCHED and source.sufficiently_readable
                for source in self.sources
            )
            and all(
                not candidate.required or candidate.dispositioned
                for candidate in self.visual_candidates
            )
        )

    def retained_candidate_ids(self) -> set[Identifier]:
        return {
            item.candidate_id
            for item in self.result_dispositions
            if item.candidate_id is not None
        }


class CandidateDispositionKind(StrEnum):
    ACCEPTED_SUPPORTING = "accepted_supporting"
    ACCEPTED_CONTRADICTING = "accepted_contradicting"
    ACCEPTED_CONTEXTUAL = "accepted_contextual"
    DUPLICATE = "duplicate"
    WRONG_SCOPE = "wrong_scope"
    IMMATERIAL = "immaterial"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


_ACCEPTED = {
    CandidateDispositionKind.ACCEPTED_SUPPORTING,
    CandidateDispositionKind.ACCEPTED_CONTRADICTING,
    CandidateDispositionKind.ACCEPTED_CONTEXTUAL,
}


class CandidateDisposition(FrozenModel):
    candidate_id: Identifier
    kind: CandidateDispositionKind
    claim_ids: tuple[Identifier, ...] = ()
    basis: str | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> CandidateDisposition:
        if self.kind in _ACCEPTED and not self.claim_ids:
            raise ValueError("accepted candidates require at least one materialized claim")
        if self.kind not in _ACCEPTED and self.claim_ids:
            raise ValueError("only accepted candidates may identify claims")
        if self.kind is CandidateDispositionKind.SUPERSEDED and not self.basis:
            raise ValueError("superseded candidates require a chronology or amendment basis")
        return self


class MaterializedEvidenceClaim(FrozenModel):
    claim_id: Identifier
    canonical_unit_id: Identifier
    source_id: Identifier
    source_artifact_hash: ContentHash
    parse_id: Identifier
    page: int = Field(ge=1)
    spatial: tuple[float, float, float, float] | None
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    quoted_text: str = Field(min_length=1)
    quoted_text_hash: ContentHash
    claim_type: Identifier
    verification_status: VerificationStatus


def materialize_evidence_claim(
    *,
    claim_id: Identifier,
    unit: CanonicalEvidenceUnit,
    span_start: int,
    span_end: int,
    claim_type: Identifier,
    verification_status: VerificationStatus = VerificationStatus.MACHINE_VERIFIED,
) -> MaterializedEvidenceClaim:
    """Materialize an exact quote from canonical text; callers never provide quote text."""
    if span_start < 0 or span_end <= span_start or span_end > len(unit.text):
        raise ValueError("claim span must select a non-empty range within the canonical unit")
    quote = unit.text[span_start:span_end]
    return MaterializedEvidenceClaim(
        claim_id=claim_id,
        canonical_unit_id=unit.unit_id,
        source_id=unit.source_id,
        source_artifact_hash=unit.source_artifact_hash,
        parse_id=unit.parse_id,
        page=unit.page,
        spatial=unit.spatial,
        span_start=span_start,
        span_end=span_end,
        quoted_text=quote,
        quoted_text_hash=sha256_digest(quote.encode()),
        claim_type=claim_type,
        verification_status=verification_status,
    )


class DerivedFactInput(FrozenModel):
    claim_id: Identifier
    role: RiskRatioInputRole
    value: str = Field(min_length=1)


class RiskRatioInputRole(StrEnum):
    EXPERIMENTAL_EVENTS = "experimental_events"
    EXPERIMENTAL_TOTAL = "experimental_total"
    COMPARATOR_EVENTS = "comparator_events"
    COMPARATOR_TOTAL = "comparator_total"


class MaterializedDerivedFact(FrozenModel):
    fact_id: Identifier
    derivation_id: Identifier
    inputs: tuple[DerivedFactInput, ...]
    population: str = Field(min_length=1)
    arms: tuple[str, str]
    analysis_set: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    units: str | None
    numerator: str
    denominator: str
    rounding_places: int = Field(ge=0, le=12)
    value: str
    content_hash: ContentHash


class DerivationDefinition(FrozenModel):
    derivation_id: Identifier
    required_roles: frozenset[RiskRatioInputRole]
    formula: str


_RISK_RATIO = DerivationDefinition(
    derivation_id="derivation:risk-ratio",
    required_roles=frozenset(RiskRatioInputRole),
    formula="(experimental_events / experimental_total) / "
    "(comparator_events / comparator_total)",
)
_DERIVATIONS = {_RISK_RATIO.derivation_id: _RISK_RATIO}


def derive_fact(
    *,
    fact_id: Identifier,
    derivation_id: Identifier,
    inputs: tuple[DerivedFactInput, ...],
    population: str,
    arms: tuple[str, str],
    analysis_set: str,
    outcome: str,
    time_point: str,
    units: str | None,
    rounding_places: int,
) -> MaterializedDerivedFact:
    """Execute one named deterministic derivation from the closed registry."""
    definition = _DERIVATIONS.get(derivation_id)
    if definition is None:
        raise ValueError(f"{derivation_id} is not in the closed registry")
    values: dict[RiskRatioInputRole, Decimal] = {}
    for item in inputs:
        if item.role in values:
            raise ValueError(f"derived-fact input role is duplicated: {item.role}")
        try:
            values[item.role] = Decimal(item.value)
        except InvalidOperation as error:
            raise ValueError(f"derived-fact input is not numeric: {item.role}") from error
    if set(values) != definition.required_roles:
        raise ValueError(
            "risk-ratio inputs must be exactly "
            f"{sorted(role.value for role in definition.required_roles)}"
        )
    if (
        values[RiskRatioInputRole.EXPERIMENTAL_TOTAL] <= 0
        or values[RiskRatioInputRole.COMPARATOR_TOTAL] <= 0
    ):
        raise ValueError("risk-ratio denominators must be positive")
    if not (
        0
        <= values[RiskRatioInputRole.EXPERIMENTAL_EVENTS]
        <= values[RiskRatioInputRole.EXPERIMENTAL_TOTAL]
        and 0
        <= values[RiskRatioInputRole.COMPARATOR_EVENTS]
        <= values[RiskRatioInputRole.COMPARATOR_TOTAL]
    ):
        raise ValueError("event counts must be between zero and their arm totals")
    comparator_risk = (
        values[RiskRatioInputRole.COMPARATOR_EVENTS]
        / values[RiskRatioInputRole.COMPARATOR_TOTAL]
    )
    if comparator_risk == 0:
        raise ValueError("risk ratio is undefined when comparator risk is zero")
    raw = (
        values[RiskRatioInputRole.EXPERIMENTAL_EVENTS]
        / values[RiskRatioInputRole.EXPERIMENTAL_TOTAL]
    ) / comparator_risk
    quantum = Decimal(1).scaleb(-rounding_places)
    value = format(raw.quantize(quantum, rounding=ROUND_HALF_EVEN), f".{rounding_places}f")
    payload = {
        "fact_id": fact_id,
        "derivation_id": derivation_id,
        "inputs": [item.model_dump(mode="json") for item in inputs],
        "population": population,
        "arms": arms,
        "analysis_set": analysis_set,
        "outcome": outcome,
        "time_point": time_point,
        "formula": definition.formula,
        "units": units,
        "numerator": "experimental_events / experimental_total",
        "denominator": "comparator_events / comparator_total",
        "rounding_places": rounding_places,
        "value": value,
    }
    return MaterializedDerivedFact(**payload, content_hash=canonical_hash(payload))


class VisualGate(FrozenModel):
    gate_id: Identifier
    required: bool
    complete: bool


class FrozenEvidenceBundle(FrozenModel):
    result_spec_id: Identifier
    receipt_ids: tuple[Identifier, ...]
    candidate_dispositions: tuple[CandidateDisposition, ...]
    claims: tuple[MaterializedEvidenceClaim, ...]
    derived_facts: tuple[MaterializedDerivedFact, ...]
    visual_item_ids: tuple[Identifier, ...]
    conflicts: tuple[tuple[Identifier, ...], ...]
    policy_ids: tuple[Identifier, ...]
    content_hash: ContentHash


class ConsiderationDisposition(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXTUAL = "contextual"
    DUPLICATE = "duplicate"
    UNRESOLVED = "unresolved"


class ConsideredEvidenceItem(FrozenModel):
    item_id: Identifier
    disposition: ConsiderationDisposition


class EvidenceConsiderationManifest(FrozenModel):
    manifest_id: Identifier
    sq_id: Identifier
    bundle_hash: ContentHash
    items: tuple[ConsideredEvidenceItem, ...]
    content_hash: ContentHash


def freeze_evidence_bundle(
    *,
    result_spec_id: Identifier,
    receipts: tuple[SearchCoverageReceipt, ...],
    candidate_dispositions: tuple[CandidateDisposition, ...],
    claims: tuple[MaterializedEvidenceClaim, ...] = (),
    derived_facts: tuple[MaterializedDerivedFact, ...] = (),
    visual_gates: tuple[VisualGate, ...] = (),
    visual_item_ids: tuple[Identifier, ...] = (),
    conflicts: tuple[tuple[Identifier, ...], ...] = (),
) -> FrozenEvidenceBundle:
    """Freeze only complete, fully dispositioned search and visual work."""
    if not receipts or any(not receipt.is_complete() for receipt in receipts):
        raise ValueError("all mandatory search coverage receipts must be complete")
    if {receipt.result_spec.entity_id for receipt in receipts} != {result_spec_id}:
        raise ValueError("coverage receipts must bind the bundle ResultSpec")
    if len({receipt.source_inventory for receipt in receipts}) != 1:
        raise ValueError("coverage receipts must bind one source-inventory revision")
    if len({receipt.snapshot_hash for receipt in receipts}) != 1:
        raise ValueError("coverage receipts must bind one index snapshot")
    if any(item.kind is CandidateDispositionKind.UNRESOLVED for item in candidate_dispositions):
        raise ValueError("potentially material candidates cannot remain unresolved")
    gate_by_id = {gate.gate_id: gate for gate in visual_gates}
    if len(gate_by_id) != len(visual_gates):
        raise ValueError("visual gate IDs must be unique")
    required_visuals = {
        candidate.candidate_id
        for receipt in receipts
        for candidate in receipt.visual_candidates
        if candidate.required
    }
    if any(
        visual_id not in gate_by_id or not gate_by_id[visual_id].complete
        for visual_id in required_visuals
    ):
        raise ValueError("every required visual candidate needs its completed visual gate")
    if any(gate.required and not gate.complete for gate in visual_gates):
        raise ValueError("every required visual gate must be complete")
    retained_candidates = set().union(
        *(receipt.retained_candidate_ids() for receipt in receipts)
    )
    disposition_ids = {item.candidate_id for item in candidate_dispositions}
    if len(disposition_ids) != len(candidate_dispositions):
        raise ValueError("each Evidence candidate must have exactly one disposition")
    if retained_candidates != disposition_ids:
        raise ValueError("every retained Evidence candidate requires exactly one disposition")
    claim_ids = {claim.claim_id for claim in claims}
    if len(claim_ids) != len(claims):
        raise ValueError("claim IDs must be unique")
    referenced_claims = {
        claim_id for item in candidate_dispositions for claim_id in item.claim_ids
    }
    if referenced_claims != claim_ids:
        raise ValueError("accepted candidate claims and frozen claims must match exactly")
    for conflict in conflicts:
        if len(conflict) < 2 or not set(conflict).issubset(claim_ids):
            raise ValueError("conflicts must preserve at least two frozen claims")
    ordered_receipts = tuple(sorted(receipts, key=lambda item: item.receipt_id))
    ordered_dispositions = tuple(
        sorted(candidate_dispositions, key=lambda item: item.candidate_id)
    )
    ordered_claims = tuple(sorted(claims, key=lambda item: item.claim_id))
    ordered_facts = tuple(sorted(derived_facts, key=lambda item: item.fact_id))
    ordered_visuals = tuple(sorted(visual_item_ids))
    ordered_conflicts = tuple(sorted(tuple(sorted(item)) for item in conflicts))
    policy_ids = tuple(sorted({receipt.policy_id for receipt in ordered_receipts}))
    payload = {
        "result_spec_id": result_spec_id,
        "receipt_ids": [item.receipt_id for item in ordered_receipts],
        "receipt_hashes": [
            canonical_hash(item) for item in ordered_receipts
        ],
        "candidate_dispositions": [
            item.model_dump(mode="json") for item in ordered_dispositions
        ],
        "claims": [item.model_dump(mode="json") for item in ordered_claims],
        "derived_facts": [item.model_dump(mode="json") for item in ordered_facts],
        "visual_item_ids": ordered_visuals,
        "conflicts": ordered_conflicts,
        "policy_ids": policy_ids,
    }
    return FrozenEvidenceBundle(
        result_spec_id=result_spec_id,
        receipt_ids=tuple(item.receipt_id for item in ordered_receipts),
        candidate_dispositions=ordered_dispositions,
        claims=ordered_claims,
        derived_facts=ordered_facts,
        visual_item_ids=ordered_visuals,
        conflicts=ordered_conflicts,
        policy_ids=policy_ids,
        content_hash=canonical_hash(payload),
    )


def build_consideration_manifest(
    *,
    manifest_id: Identifier,
    sq_id: Identifier,
    bundle: FrozenEvidenceBundle,
    items: tuple[ConsideredEvidenceItem, ...],
) -> EvidenceConsiderationManifest:
    """Account for how every frozen item was considered for one SQ answer."""
    required = {
        *(claim.claim_id for claim in bundle.claims),
        *(fact.fact_id for fact in bundle.derived_facts),
        *bundle.visual_item_ids,
    }
    item_ids = [item.item_id for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("consideration-manifest item IDs must be unique")
    if set(item_ids) != required:
        raise ValueError("every frozen evidence item requires one consideration disposition")
    ordered = tuple(sorted(items, key=lambda item: item.item_id))
    payload = {
        "manifest_id": manifest_id,
        "sq_id": sq_id,
        "bundle_hash": bundle.content_hash,
        "items": [item.model_dump(mode="json") for item in ordered],
    }
    return EvidenceConsiderationManifest(
        **payload,
        content_hash=canonical_hash(payload),
    )
