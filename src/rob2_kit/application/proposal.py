"""Scientifically explicit, immutable Proposal review and approval records.

This is deliberately a small structural boundary.  It does not infer scientific
meaning from prose: a host states the target and the reported table structure,
and the server only checks their explicit, closed fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

from rob2_kit.storage import workspace_mutation_lock

from ._state import identity, read_json, record_uri, write_jsons
from .acknowledgments import verify_acknowledgment
from .contracts import (
    Continuation,
    EvidenceReference,
    OperationOutcome,
    RecordKind,
    RecordReference,
    ResearcherReviewContinuation,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    ReviewAuthorityRequirement,
    SaveProposalContinuation,
    TransitionReference,
    ValidateDomainJudgmentContinuation,
)
from .evidence import EvidenceRecord, TextEvidenceRecord, resolve_evidence, source_layout_projection


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Quantity(_Closed):
    statistic: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    group_or_category: str = Field(min_length=1)
    value: float | int | str
    denominator_basis: str | None = Field(default=None, min_length=1)


class ComparisonGroup(_Closed):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1)


class ResultTarget(_Closed):
    outcome_definition: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    time_point_or_window: str = Field(min_length=1)
    effect_of_interest: str = Field(min_length=1)
    comparison_groups: tuple[ComparisonGroup, ComparisonGroup]
    intended_analysis_population: str = Field(min_length=1)
    intended_effect_measure: str = Field(min_length=1)

    @model_validator(mode="after")
    def groups_differ(self) -> ResultTarget:
        if self.comparison_groups[0].id == self.comparison_groups[1].id:
            raise ValueError("comparison groups must differ")
        return self


class CoverageStatus(StrEnum):
    MEASURED = "measured"
    NOT_MEASURED = "not_measured"
    UNCLEAR = "unclear"


class OutcomeMeasurementCoverage(_Closed):
    group_id: str
    status: CoverageStatus
    explanation: str | None = None

    @model_validator(mode="after")
    def explanation_for_nonmeasurement(self) -> OutcomeMeasurementCoverage:
        if self.status is not CoverageStatus.MEASURED and not self.explanation:
            raise ValueError("unmeasured or unclear coverage requires an explanation")
        return self


class PopulationAccount(_Closed):
    randomized_enrollment: tuple[Quantity, ...] = ()
    outcome_measurement_coverage: tuple[OutcomeMeasurementCoverage, ...] = ()
    analyzed_population: str = Field(min_length=1)


class ConfidenceInterval(_Closed):
    level: str = Field(min_length=1)
    lower: str = Field(min_length=1)
    upper: str = Field(min_length=1)


class PValue(_Closed):
    operator: Literal["=", "<", "<=", ">", ">="]
    value: str = Field(min_length=1)


class EffectPrecision(_Closed):
    confidence_interval: ConfidenceInterval | None = None
    p_value: PValue | None = None


class ComparativeEffect(_Closed):
    form: Literal["comparative_effect"]
    effect_measure: str = Field(min_length=1)
    reported_text: str = Field(min_length=1)
    effect: Quantity
    quantities: tuple[Quantity, ...] = Field(min_length=2)
    comparison_groups: tuple[str, str]
    precision: EffectPrecision | None = None

    @model_validator(mode="after")
    def denominator_bases_are_labeled(self) -> ComparativeEffect:
        if (
            not self.effect.denominator_basis
            or not self.effect.denominator_basis.strip()
            or any(
                not quantity.denominator_basis or not quantity.denominator_basis.strip()
                for quantity in self.quantities
            )
        ):
            raise ValueError(
                "comparative effects require a denominator basis for the effect and every "
                "group quantity"
            )
        return self


class GroupBoundValues(_Closed):
    form: Literal["group_bound_values"]
    quantities: tuple[Quantity, ...] = Field(min_length=2)
    comparison_groups: tuple[str, str]


class SingleGroupCategoryProfile(_Closed):
    form: Literal["single_group_category_profile"]
    group_id: str = Field(min_length=1)
    categories: tuple[Quantity, ...] = Field(min_length=1)


class UnavailableResult(_Closed):
    form: Literal["unavailable"]
    reason: Literal["not_reported", "not_measured", "not_estimable"]
    explanation: str = Field(min_length=1)


ReportedResult: TypeAlias = Annotated[
    ComparativeEffect | GroupBoundValues | SingleGroupCategoryProfile | UnavailableResult,
    Field(discriminator="form"),
]


class DerivedResult(_Closed):
    operation: Literal["risk_ratio", "risk_difference"]
    numerator_inputs: tuple[Quantity, Quantity]
    denominator_inputs: tuple[Quantity, Quantity]

    @model_validator(mode="after")
    def deterministic_inputs_are_labeled(self) -> DerivedResult:
        if any(not item.denominator_basis for item in self.denominator_inputs):
            raise ValueError("derivation denominators require a denominator basis")
        return self


def derive_effect(derivation: DerivedResult) -> float:
    """Recompute a supported two-group effect from the exact labeled inputs."""

    try:
        events = tuple(float(item.value) for item in derivation.numerator_inputs)
        denominators = tuple(float(item.value) for item in derivation.denominator_inputs)
    except (TypeError, ValueError) as error:
        raise ValueError("derivation inputs must be numeric") from error
    if any(value < 0 for value in events) or any(value <= 0 for value in denominators):
        raise ValueError("derivation inputs must be nonnegative events and positive denominators")
    first, second = events[0] / denominators[0], events[1] / denominators[1]
    if derivation.operation == "risk_ratio":
        if second == 0:
            raise ValueError("risk ratio is not estimable with a zero comparator risk")
        return first / second
    return first - second


class EvidenceSet(_Closed):
    target_basis: tuple[EvidenceReference, ...] = Field(min_length=1)
    reported_values: tuple[EvidenceReference, ...] = Field(min_length=1)
    reported_context: tuple[EvidenceReference, ...] = Field(min_length=1)
    population_basis: tuple[EvidenceReference, ...] = Field(min_length=1)


class ClarityState(StrEnum):
    SPECIFIED = "specified"
    UNCLEAR = "unclear"
    UNAVAILABLE = "unavailable"


class ClarityItem(_Closed):
    state: ClarityState
    explanation: str | None = None

    @model_validator(mode="after")
    def uncertainty_is_explained(self) -> ClarityItem:
        if self.state is not ClarityState.SPECIFIED and not self.explanation:
            raise ValueError("unclear or unavailable clarity requires an explanation")
        if self.state is ClarityState.SPECIFIED and self.explanation is not None:
            raise ValueError("specified clarity cannot carry an explanation")
        return self


class ClarityDeclaration(_Closed):
    outcome_definition: ClarityItem
    measurement: ClarityItem
    time_point: ClarityItem
    analysis_population: ClarityItem
    comparison_groups: ClarityItem
    effect_measure: ClarityItem
    source_table_meaning: ClarityItem
    choice_among_eligible_results: ClarityItem


class Compatibility(StrEnum):
    COMPATIBLE = "compatible"
    REVIEW_REQUIRED = "review_required"
    INCOMPATIBLE = "incompatible"


class CompatibilityFinding(_Closed):
    status: Compatibility
    reasons: tuple[str, ...] = ()


class ResultCardInput(_Closed):
    trial_id: str
    target: ResultTarget
    reported: ReportedResult
    derived: DerivedResult | None = None
    population: PopulationAccount
    source_table_meaning: str = Field(min_length=1)
    evidence: EvidenceSet
    clarity: ClarityDeclaration


class ResultCard(ResultCardInput):
    compatibility: CompatibilityFinding

    @model_validator(mode="before")
    @classmethod
    def _discard_reported_projection(cls, value: object) -> object:
        if not isinstance(value, dict) or "reported" not in value:
            return value
        projected = dict(value)
        for key in (
            "form",
            "effect_measure",
            "reported_text",
            "effect",
            "comparison_groups",
            "quantities",
            "precision",
            "group_id",
            "categories",
            "reason",
            "explanation",
        ):
            projected.pop(key, None)
        return projected

    @model_serializer
    def _wire(self) -> dict[str, object]:
        """Keep the complete Result card while exposing its reported form to portable readers."""
        value = {
            "trial_id": self.trial_id,
            "target": self.target.model_dump(mode="json"),
            "reported": self.reported.model_dump(mode="json"),
            "derived": None if self.derived is None else self.derived.model_dump(mode="json"),
            "population": self.population.model_dump(mode="json"),
            "source_table_meaning": self.source_table_meaning,
            "evidence": self.evidence.model_dump(mode="json"),
            "clarity": self.clarity.model_dump(mode="json"),
            "compatibility": self.compatibility.model_dump(mode="json"),
        }
        value.update(self.reported.model_dump(mode="json"))
        return value


class NeedsInputReason(StrEnum):
    OUTCOME_NOT_REPORTED = "outcome_not_reported"
    OUTCOME_NOT_MEASURED = "outcome_not_measured"
    COMPARATOR_UNAVAILABLE = "comparator_unavailable"
    POPULATION_UNCLEAR = "population_unclear"
    RESULT_NOT_ESTIMABLE = "result_not_estimable"


class PreapprovalNeedsInput(_Closed):
    trial_id: str
    reason: NeedsInputReason
    missing_facts: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)


class ProposalInput(_Closed):
    outcome_statement: str = Field(min_length=1)
    results: tuple[ResultCardInput, ...] = ()
    needs_input: tuple[PreapprovalNeedsInput, ...] = ()


class ProposalReview(_Closed):
    kind: Literal["proposal_review"] = "proposal_review"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    captured_batch: RecordReference
    outcome_statement: str
    results: tuple[ResultCard, ...]
    needs_input: tuple[PreapprovalNeedsInput, ...]
    review: ReviewAuthorityRequirement
    transition: TransitionReference

    @property
    def reference(self) -> RecordReference:
        return RecordReference(
            kind=RecordKind.PROPOSAL_REVIEW,
            identity=self.identity,
            uri=record_uri("proposal_review", self.identity),
        )


class ProposalReceipt(_Closed):
    outcome: OperationOutcome
    review: RecordReference
    compatibility: tuple[CompatibilityFinding, ...]
    review_requirement: ReviewAuthorityRequirement
    transition: TransitionReference | None = None
    next_action: Continuation | None = None


class ProposalRepair(_Closed):
    pointer: str = Field(pattern=r"^(?:|/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*)$")
    code: Literal["missing", "invalid", "extra", "wrong_type"]
    detail: str = Field(min_length=1)


class ProposalRepairReceipt(_Closed):
    outcome: Literal[OperationOutcome.REPAIR] = OperationOutcome.REPAIR
    repairs: tuple[ProposalRepair, ...] = Field(min_length=1)
    next_action: Continuation | None = None


class ClarificationAlternative(_Closed):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    replacement: object


class ResultClarification(_Closed):
    review: RecordReference
    trial_id: str
    field_path: str = Field(
        pattern=r"^/results/[0-9]+/(?:target|reported|derived|population|evidence|clarity)$"
    )
    alternatives: tuple[ClarificationAlternative, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def alternatives_are_exclusive(self) -> ResultClarification:
        ids = tuple(item.id for item in self.alternatives)
        if len(ids) != len(set(ids)) or {
            "none_apply",
            "cannot_determine_from_available_sources",
        } - set(ids):
            raise ValueError(
                "clarification alternatives must be unique and include the two required "
                "fallback choices"
            )
        return self


class ClarificationSelection(_Closed):
    clarification: ResultClarification
    alternative_id: str
    acknowledge: bool = False


class ClarificationReceipt(_Closed):
    outcome: OperationOutcome
    review: RecordReference
    acknowledgment: ReviewAcknowledgmentReference | None = None
    next_action: Continuation | None = None


class ApprovalRequest(_Closed):
    transition: TransitionReference
    acknowledgment: ReviewAcknowledgmentReference


class ApprovalReceipt(_Closed):
    outcome: OperationOutcome
    approved_batch: RecordReference
    review: RecordReference
    acknowledgment: ReviewAcknowledgmentReference
    trial_dispositions: tuple[tuple[str, Literal["pending", "needs_input"]], ...]
    next_action: Continuation | None = None


def _captured(workspace: str | Path) -> tuple[dict[str, object], RecordReference]:
    raw = read_json(workspace, "captured_batch.json")
    if raw is None or not isinstance(raw.get("identity"), str):
        raise ValueError("a captured Batch is required")
    reference = RecordReference(
        kind=RecordKind.CAPTURED_BATCH,
        identity=str(raw["identity"]),
        uri=record_uri("captured_batch", str(raw["identity"])),
    )
    return raw, reference


def _trial_ids(captured: dict[str, object]) -> tuple[str, ...]:
    rows = captured.get("sources", ())
    if not isinstance(rows, list):
        raise ValueError("captured Batch is corrupt")
    return tuple(sorted({str(item["trial_id"]) for item in rows if isinstance(item, dict)}))


def _compatibility(card: ResultCardInput) -> CompatibilityFinding:
    target_ids = tuple(group.id for group in card.target.comparison_groups)
    if isinstance(card.reported, SingleGroupCategoryProfile):
        return CompatibilityFinding(
            status=Compatibility.REVIEW_REQUIRED,
            reasons=("single_group_category_profile_requires_review",),
        )
    if isinstance(card.reported, UnavailableResult):
        return CompatibilityFinding(
            status=Compatibility.INCOMPATIBLE, reasons=(card.reported.reason,)
        )
    reported_groups = card.reported.comparison_groups
    coverage = {item.group_id: item.status for item in card.population.outcome_measurement_coverage}
    if reported_groups != target_ids or any(
        coverage.get(item) is not CoverageStatus.MEASURED for item in target_ids
    ):
        return CompatibilityFinding(
            status=Compatibility.INCOMPATIBLE, reasons=("comparison_coverage_incomplete",)
        )
    if isinstance(card.reported, ComparativeEffect):
        if card.reported.effect_measure != card.target.intended_effect_measure:
            return CompatibilityFinding(
                status=Compatibility.INCOMPATIBLE, reasons=("effect_measure_mismatch",)
            )
    elif card.derived is None:
        return CompatibilityFinding(
            status=Compatibility.REVIEW_REQUIRED, reasons=("derivation_required",)
        )
    else:
        try:
            derive_effect(card.derived)
        except ValueError:
            return CompatibilityFinding(
                status=Compatibility.INCOMPATIBLE, reasons=("derivation_not_estimable",)
            )
    uncertain = any(
        item.state is not ClarityState.SPECIFIED for item in card.clarity.__dict__.values()
    )
    return CompatibilityFinding(
        status=Compatibility.REVIEW_REQUIRED if uncertain else Compatibility.COMPATIBLE,
        reasons=("clarity_declared_uncertain",) if uncertain else (),
    )


def _validate_evidence(
    workspace: str | Path, card: ResultCardInput, outcome_statement: str | None = None
) -> tuple[ProposalRepair, ...]:
    role_refs = (
        ("target_basis", card.evidence.target_basis),
        ("reported_values", card.evidence.reported_values),
        ("reported_context", card.evidence.reported_context),
        ("population_basis", card.evidence.population_basis),
    )
    resolved_by_role: dict[str, list[EvidenceRecord]] = {}
    resolution_repairs: list[ProposalRepair] = []
    for role, references in role_refs:
        resolved: list[EvidenceRecord] = []
        for reference in references:
            try:
                evidence = resolve_evidence(workspace, reference)
            except ValueError as error:
                detail = (
                    _evidence_minting_repair_detail(reference)
                    if str(error) == "Evidence is unavailable"
                    else str(error)
                )
                resolution_repairs.append(
                    ProposalRepair(
                        pointer=f"/evidence/{role}",
                        code="invalid",
                        detail=detail,
                    )
                )
                continue
            if evidence.trial_id != card.trial_id:
                resolution_repairs.append(
                    ProposalRepair(
                        pointer=f"/evidence/{role}",
                        code="invalid",
                        detail="Result Evidence must bind its Trial",
                    )
                )
                continue
            resolved.append(evidence)
        resolved_by_role[role] = resolved
    if resolution_repairs:
        return tuple(resolution_repairs)
    reported_evidence = resolved_by_role["reported_values"]
    text_reported_evidence = [
        item for item in reported_evidence if isinstance(item, TextEvidenceRecord)
    ]
    if len(text_reported_evidence) != len(reported_evidence):
        return (
            ProposalRepair(
                pointer="/evidence/reported_values",
                code="invalid",
                detail="reported-values Evidence must be text Evidence with an exact source quote",
            ),
        )
    repairs: list[ProposalRepair] = []
    if isinstance(card.reported, ComparativeEffect):
        statement = source_layout_projection(card.reported.reported_text)[0].strip()
        if not statement.strip():
            repairs.append(
                ProposalRepair(
                    pointer="/reported/reported_text",
                    code="invalid",
                    detail="reported_text must not be empty",
                )
            )
        declared_outcome = source_layout_projection(card.target.outcome_definition)[0].strip()
        declared_label, _, explicit_target = _declared_outcome_parts(outcome_statement or "")
        if explicit_target and declared_outcome:
            declared_terms = (
                source_layout_projection(declared_label, casefold=True)[0].strip(),
                source_layout_projection(declared_outcome, casefold=True)[0].strip(),
            )
            projected_statement_folded = source_layout_projection(statement, casefold=True)[0]
            if not any(term and term in projected_statement_folded for term in declared_terms):
                repairs.append(
                    ProposalRepair(
                        pointer="/reported/reported_text",
                        code="invalid",
                        detail=(
                            "reported_text must name the declared outcome label or definition "
                            f"({declared_label!r} or {card.target.outcome_definition!r})"
                        ),
                    )
                )
        quotes = tuple(
            source_layout_projection(item.quote)[0].strip() for item in text_reported_evidence
        )
        if statement.strip() and not any(statement in quote for quote in quotes):
            identities = ", ".join(item.identity for item in reported_evidence)
            repairs.append(
                ProposalRepair(
                    pointer="/reported/reported_text",
                    code="invalid",
                    detail=(
                        "reported_text is not contiguous in reported-values Evidence; copy one "
                        "complete contiguous source passage from a single cited reported-values "
                        f"Evidence record ({identities}), preserving case, wording, punctuation, "
                        "CI, and P-value. Only PDF whitespace and line-end hyphenation are "
                        "normalized"
                    ),
                )
            )
    return tuple(repairs)


def _comparative_structure_repairs(card: ResultCardInput) -> tuple[ProposalRepair, ...]:
    if not isinstance(card.reported, ComparativeEffect):
        return ()
    group_ids = tuple(group.id for group in card.target.comparison_groups)
    expected_effect_group = f"{group_ids[0]} vs {group_ids[1]}"
    repairs: list[ProposalRepair] = []
    if tuple(quantity.group_or_category for quantity in card.reported.quantities) != group_ids:
        repairs.append(
            ProposalRepair(
                pointer="/reported/quantities",
                code="invalid",
                detail=(
                    "reported.quantities must contain exactly two ordered quantities bound to "
                    f"target comparison group IDs {group_ids!r}"
                ),
            )
        )
    if card.reported.comparison_groups != group_ids:
        repairs.append(
            ProposalRepair(
                pointer="/reported/comparison_groups",
                code="invalid",
                detail=(
                    "reported.comparison_groups must exactly equal ordered target comparison "
                    f"group IDs {group_ids!r}"
                ),
            )
        )
    if card.reported.effect.group_or_category != expected_effect_group:
        repairs.append(
            ProposalRepair(
                pointer="/reported/effect/group_or_category",
                code="invalid",
                detail=(
                    "reported.effect.group_or_category must be exactly "
                    f"{expected_effect_group!r} using the target comparison group IDs"
                ),
            )
        )
    return tuple(repairs)


def _declared_outcome_parts(statement: str) -> tuple[str, str, bool]:
    value = statement.strip()
    if value.casefold().startswith("effect on "):
        value = value[10:].strip()
    marker = ", defined as "
    for index in range(len(value) - len(marker) + 1):
        if value[index : index + len(marker)].casefold() == marker:
            return value[:index].strip(), value[index + len(marker) :].strip(), True
    return value, value, False


def _declared_outcome_definition(statement: str) -> str:
    return _declared_outcome_parts(statement)[1]


def _evidence_minting_repair_detail(reference: EvidenceReference) -> str:
    return (
        f"Evidence reference {reference.identity} is not persisted Evidence; call "
        "retrieve_evidence with an exact normal, manual, or visual selection, then use "
        "the returned Evidence identity."
    )


def _card_contract_repairs(
    card: ResultCardInput, outcome_statement: str
) -> tuple[ProposalRepair, ...]:
    expected = _declared_outcome_definition(outcome_statement)
    normalized_expected = " ".join(expected.casefold().split())
    expected_effect = f"effect on {expected}"
    repairs: list[ProposalRepair] = []
    if " ".join(card.target.outcome_definition.casefold().split()) != normalized_expected:
        repairs.append(
            ProposalRepair(
                pointer="/target/outcome_definition",
                code="invalid",
                detail=f"target outcome definition must be exactly {expected!r}",
            )
        )
    if " ".join(card.target.effect_of_interest.casefold().split()) != " ".join(
        expected_effect.casefold().split()
    ):
        repairs.append(
            ProposalRepair(
                pointer="/target/effect_of_interest",
                code="invalid",
                detail=f"effect of interest must be exactly {expected_effect!r}",
            )
        )
    return tuple(repairs)


def _compatibility_repairs(
    index: int, finding: CompatibilityFinding, card: ResultCardInput
) -> tuple[ProposalRepair, ...]:
    pointer_by_reason = {
        "comparison_coverage_incomplete": "population/outcome_measurement_coverage",
        "effect_measure_mismatch": "reported/effect_measure",
        "reported_values_require_derivation": "derived",
        "derivation_required": "derived",
        "derivation_not_estimable": "derived",
        "clarity_declared_uncertain": "clarity",
    }

    target_ids = tuple(group.id for group in card.target.comparison_groups)
    reported_groups = (
        ()
        if isinstance(card.reported, (SingleGroupCategoryProfile, UnavailableResult))
        else card.reported.comparison_groups
    )
    coverage = {
        item.group_id: item.status.value for item in card.population.outcome_measurement_coverage
    }
    incomplete_coverage = tuple(
        (group_id, coverage.get(group_id, "missing"))
        for group_id in target_ids
        if coverage.get(group_id) != CoverageStatus.MEASURED.value
    )

    def details(reason: str) -> tuple[tuple[str, str], ...]:
        if reason == "comparison_coverage_incomplete":
            repairs: list[tuple[str, str]] = []
            if set(reported_groups) != set(target_ids):
                repairs.append(
                    (
                        "reported/comparison_groups",
                        (
                            "server-derived compatibility: comparison_coverage_incomplete; "
                            f"target comparison group IDs (ordered): {target_ids!r}; "
                            f"reported comparison group IDs: {reported_groups!r}; "
                            "align reported IDs to target IDs only when Evidence supports the "
                            "target bindings; otherwise correct target.comparison_groups or use "
                            "the appropriate needs_input disposition"
                        ),
                    )
                )
            if incomplete_coverage:
                repairs.append(
                    (
                        "population/outcome_measurement_coverage",
                        (
                            "server-derived compatibility: comparison_coverage_incomplete; "
                            "missing/non-measured target IDs and current statuses: "
                            f"{incomplete_coverage!r}; "
                            "set each target group to measured only when Evidence supports "
                            "outcome measurement, otherwise use the appropriate needs_input "
                            "disposition"
                        ),
                    )
                )
            return tuple(repairs)
        if reason == "effect_measure_mismatch":
            assert isinstance(card.reported, ComparativeEffect)
            return (
                (
                    "reported/effect_measure",
                    (
                        "server-derived compatibility: effect_measure_mismatch; "
                        f"target intended effect measure: {card.target.intended_effect_measure!r}; "
                        f"reported effect measure: {card.reported.effect_measure!r}; "
                        "make reported.effect_measure exactly match "
                        "target.intended_effect_measure only when that is the source-reported "
                        "measure for the requested outcome; otherwise correct the target or use "
                        "the appropriate needs_input disposition, preserving Evidence"
                    ),
                ),
            )
        return (
            (pointer_by_reason.get(reason, "reported"), f"server-derived compatibility: {reason}"),
        )

    return tuple(
        ProposalRepair(pointer=f"/results/{index}/{pointer}", code="invalid", detail=detail)
        for reason in finding.reasons
        for pointer, detail in details(reason)
    )


def _repair_pointer(location: tuple[int | str, ...]) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in location)


def _proposal_repairs(error: ValidationError) -> ProposalRepairReceipt:
    repairs: list[ProposalRepair] = []
    for item in error.errors():
        kind = str(item["type"])
        code: Literal["missing", "invalid", "extra", "wrong_type"]
        if kind == "missing":
            code = "missing"
        elif kind == "extra_forbidden":
            code = "extra"
        elif "type" in kind or kind in {"model_attributes_type", "model_type"}:
            code = "wrong_type"
        else:
            code = "invalid"
        location = tuple(
            part for part in item["loc"] if part not in {"function-after", "tagged-union"}
        )
        repairs.append(
            ProposalRepair(pointer=_repair_pointer(location), code=code, detail=str(item["msg"]))
        )
    unique = {(repair.pointer, repair.code, repair.detail): repair for repair in repairs}
    return ProposalRepairReceipt(repairs=tuple(unique[key] for key in sorted(unique)))


def save_proposal(
    workspace: str | Path, proposal: ProposalInput | object
) -> ProposalReceipt | ProposalRepairReceipt:
    if not isinstance(proposal, ProposalInput):
        try:
            proposal = ProposalInput.model_validate(proposal)
        except ValidationError as error:
            return _proposal_repairs(error)
    captured, captured_ref = _captured(workspace)
    trial_ids = _trial_ids(captured)
    if not trial_ids:
        raise ValueError("captured Batch has no Trial sources")
    result_by_trial = {item.trial_id: item for item in proposal.results}
    input_by_trial = {item.trial_id: item for item in proposal.needs_input}
    if len(result_by_trial) != len(proposal.results) or len(input_by_trial) != len(
        proposal.needs_input
    ):
        raise ValueError("Proposal contains duplicate Trial dispositions")
    if set(result_by_trial) | set(input_by_trial) != set(trial_ids):
        raise ValueError("Proposal requires exactly one disposition for every captured Trial")
    reviewed: list[tuple[int, ResultCard]] = []
    repairs: list[ProposalRepair] = []
    result_index_by_trial = {item.trial_id: index for index, item in enumerate(proposal.results)}
    for trial_id in trial_ids:
        card = result_by_trial.get(trial_id)
        if card is None:
            continue
        input_index = result_index_by_trial[trial_id]
        contract_repairs = _card_contract_repairs(card, proposal.outcome_statement)
        repairs.extend(
            item.model_copy(update={"pointer": f"/results/{input_index}{item.pointer}"})
            for item in contract_repairs
        )
        structural_repairs = _comparative_structure_repairs(card)
        repairs.extend(
            item.model_copy(update={"pointer": f"/results/{input_index}{item.pointer}"})
            for item in structural_repairs
        )
        evidence_repairs = _validate_evidence(workspace, card, proposal.outcome_statement)
        repairs.extend(
            item.model_copy(update={"pointer": f"/results/{input_index}{item.pointer}"})
            for item in evidence_repairs
        )
        found = _compatibility(card)
        compatibility_repairs = (
            _compatibility_repairs(input_index, found, card)
            if found.status is not Compatibility.COMPATIBLE and trial_id not in input_by_trial
            else ()
        )
        repairs.extend(compatibility_repairs)
        if contract_repairs or structural_repairs or evidence_repairs or compatibility_repairs:
            continue
        reviewed.append(
            (
                input_index,
                ResultCard.model_validate(
                    {
                        **card.model_dump(mode="json"),
                        "compatibility": found.model_dump(mode="json"),
                    }
                ),
            )
        )
    for disposition_index, disposition in enumerate(proposal.needs_input):
        for evidence_index, reference in enumerate(disposition.evidence):
            try:
                evidence = resolve_evidence(workspace, reference)
            except ValueError as error:
                detail = (
                    _evidence_minting_repair_detail(reference)
                    if str(error) == "Evidence is unavailable"
                    else str(error)
                )
                repairs.append(
                    ProposalRepair(
                        pointer=f"/needs_input/{disposition_index}/evidence/{evidence_index}",
                        code="invalid",
                        detail=detail,
                    )
                )
                continue
            if evidence.trial_id != disposition.trial_id:
                repairs.append(
                    ProposalRepair(
                        pointer=f"/needs_input/{disposition_index}/evidence/{evidence_index}",
                        code="invalid",
                        detail="needs-input Evidence must bind its Trial",
                    )
                )
    if repairs:
        unique: dict[tuple[str, str, str], ProposalRepair] = {}
        for item in repairs:
            unique.setdefault((item.pointer, item.code, item.detail), item)
        return ProposalRepairReceipt(
            repairs=tuple(unique.values()),
            next_action=SaveProposalContinuation(captured_batch=captured_ref),
        )
    base = {
        "captured_batch": captured_ref.model_dump(mode="json"),
        "outcome_statement": proposal.outcome_statement,
        "results": [item.model_dump(mode="json") for _, item in reviewed],
        "needs_input": [
            input_by_trial[item].model_dump(mode="json") for item in sorted(input_by_trial)
        ],
    }
    review_identity = identity(base)
    transition = TransitionReference(
        operation="approve_batch",
        identity=identity({"operation": "approve_batch", "review": review_identity}),
    )
    review = ProposalReview(
        identity=review_identity,
        captured_batch=captured_ref,
        outcome_statement=proposal.outcome_statement,
        results=tuple(item for _, item in reviewed),
        needs_input=tuple(input_by_trial[item] for item in sorted(input_by_trial)),
        review=ReviewAuthorityRequirement(required=ReviewAuthority.RESEARCHER),
        transition=transition,
    )
    state = read_json(workspace, "state.json") or {}
    state.update(
        {
            "phase": "proposal",
            "proposal_review_identity": review.identity,
            "review_authority": "researcher",
            "review_satisfied": False,
        }
    )
    write_jsons(
        workspace,
        {
            "proposal_review.json": review.model_dump(mode="json"),
            f"proposal_review-{review.identity.removeprefix('sha256:')}.json": review.model_dump(
                mode="json"
            ),
            f"transition-{transition.identity.removeprefix('sha256:')}.json": {
                "identity": transition.identity,
                "operation": transition.operation,
                "review": review.identity,
                "consumed": False,
            },
            "state.json": state,
        },
    )
    compatible = tuple(card.compatibility for card in review.results)
    return ProposalReceipt(
        outcome=OperationOutcome.SUCCESS
        if all(item.status is Compatibility.COMPATIBLE for item in compatible)
        else OperationOutcome.CONDITION,
        review=review.reference,
        compatibility=compatible,
        review_requirement=review.review,
        transition=transition,
        next_action=ResearcherReviewContinuation(
            record=review.reference, purpose="proposal", unlocks="approve_batch"
        ),
    )


def _current_review(workspace: str | Path) -> ProposalReview:
    raw = read_json(workspace, "proposal_review.json")
    if raw is None:
        raise ValueError("Proposal Review is unavailable")
    review = ProposalReview.model_validate(raw)
    payload = review.model_dump(mode="json", exclude={"identity", "review", "transition", "kind"})
    if identity(payload) != review.identity:
        raise ValueError("Proposal Review is corrupt")
    return review


def acknowledge_proposal(
    workspace: str | Path,
    review: RecordReference,
    *,
    caller: str,
    observed_at: datetime | None = None,
) -> ReviewAcknowledgmentReference:
    current = _current_review(workspace)
    if review.kind is not RecordKind.PROPOSAL_REVIEW or review.identity != current.identity:
        raise ValueError("acknowledgment must name the current exact Proposal Review")
    if not caller.startswith(("cli:", "server:")):
        raise PermissionError(
            "Proposal acknowledgment requires researcher-mediated adapter authority"
        )
    observation = (observed_at or datetime.now(UTC)).astimezone(UTC)
    payload = {
        "record": review.model_dump(mode="json"),
        "authority": "researcher",
        "purpose": "proposal",
        "caller": caller,
        "observed_at": observation.isoformat(),
    }
    ack_identity = identity(payload)
    acknowledgment = ReviewAcknowledgmentReference(
        kind="review_ack", identity=ack_identity, uri=record_uri("review_ack", ack_identity)
    )
    state = read_json(workspace, "state.json") or {}
    state.update(
        {
            "ack_identity": acknowledgment.identity,
            "review_satisfied": True,
            "review_authority": "researcher",
        }
    )
    write_jsons(
        workspace,
        {
            "proposal_ack.json": {**acknowledgment.model_dump(mode="json"), **payload},
            "state.json": state,
        },
    )
    return acknowledgment


def apply_clarification(
    workspace: str | Path,
    selection: ClarificationSelection,
    *,
    caller: str | None = None,
) -> ClarificationReceipt:
    """Apply one displayed replacement, never a caller-supplied patch or free text."""

    current = _current_review(workspace)
    clarification = selection.clarification
    if clarification.review != current.reference:
        raise ValueError("clarification binds a stale Proposal Review")
    index = int(clarification.field_path.split("/")[2])
    if index >= len(current.results) or current.results[index].trial_id != clarification.trial_id:
        raise ValueError("clarification field path does not bind its Trial Result")
    alternative = next(
        (item for item in clarification.alternatives if item.id == selection.alternative_id), None
    )
    if alternative is None:
        raise ValueError("clarification alternative is unavailable")
    if alternative.id in {"none_apply", "cannot_determine_from_available_sources"}:
        return ClarificationReceipt(
            outcome=OperationOutcome.CONDITION,
            review=current.reference,
            next_action=SaveProposalContinuation(captured_batch=_captured(workspace)[1]),
        )
    field = clarification.field_path.rsplit("/", 1)[1]
    cards = list(current.results)
    payload = cards[index].model_dump(mode="json")
    payload[field] = alternative.replacement
    cards[index] = ResultCard.model_validate(payload)
    next_review = save_proposal(
        workspace,
        ProposalInput(
            outcome_statement=current.outcome_statement,
            results=tuple(cards),
            needs_input=current.needs_input,
        ),
    )
    if isinstance(next_review, ProposalRepairReceipt):
        raise ValueError("validated clarification replacement produced an invalid Proposal")
    acknowledgment = None
    if selection.acknowledge:
        if caller is None:
            raise PermissionError("acknowledgment requires researcher adapter authority")
        acknowledgment = acknowledge_proposal(workspace, next_review.review, caller=caller)
    return ClarificationReceipt(
        outcome=next_review.outcome,
        review=next_review.review,
        acknowledgment=acknowledgment,
        next_action=next_review.next_action,
    )


def approve_batch(workspace: str | Path, request: ApprovalRequest) -> ApprovalReceipt:
    with workspace_mutation_lock(workspace):
        review = _current_review(workspace)
        if request.transition != review.transition:
            raise ValueError("approval requires the returned exact Transition")
        state = read_json(workspace, "state.json") or {}
        if state.get("ack_identity") != request.acknowledgment.identity or not state.get(
            "review_satisfied"
        ):
            raise PermissionError("approval requires the exact Proposal Review acknowledgment")
        if (
            verify_acknowledgment(
                workspace,
                "proposal_ack.json",
                request.acknowledgment,
                record=review.reference,
                purpose="proposal",
                authority=ReviewAuthority.RESEARCHER,
            )
            is None
        ):
            raise ValueError("Proposal acknowledgment is stale or corrupt")
        raw_transition = read_json(
            workspace, f"transition-{request.transition.identity.removeprefix('sha256:')}.json"
        )
        if raw_transition is None or raw_transition.get("review") != review.identity:
            raise ValueError("Transition is unavailable or stale")
        if raw_transition.get("consumed"):
            replay = read_json(
                workspace, f"approval-{review.identity.removeprefix('sha256:')}.json"
            )
            if replay is None:
                raise ValueError("consumed Transition replay is corrupt")
            return ApprovalReceipt.model_validate(replay)
        terminal_trials = {item.trial_id for item in review.needs_input}
        if any(
            item.compatibility.status is not Compatibility.COMPATIBLE
            and item.trial_id not in terminal_trials
            for item in review.results
        ):
            raise ValueError("only structurally compatible Results may be approved")
        dispositions = tuple(
            sorted(
                [
                    (item.trial_id, "pending")
                    for item in review.results
                    if item.trial_id not in terminal_trials
                ]
                + [(item.trial_id, "needs_input") for item in review.needs_input]
            )
        )
        approved_payload = {
            "review": review.identity,
            "acknowledgment": request.acknowledgment.identity,
            "dispositions": dispositions,
        }
        approved_identity = identity(approved_payload)
        approved = RecordReference(
            kind=RecordKind.APPROVED_BATCH,
            identity=approved_identity,
            uri=record_uri("approved_batch", approved_identity),
        )
        terminal_writes: dict[str, dict[str, object]] = {}
        for item in review.needs_input:
            terminal_payload = {
                "trial_id": item.trial_id,
                "disposition": "needs_input",
                "reason": item.reason.value,
                "missing_facts": list(item.missing_facts),
                "evidence": [reference.model_dump(mode="json") for reference in item.evidence],
                "acknowledgment": request.acknowledgment.model_dump(mode="json"),
            }
            terminal_identity = identity(terminal_payload)
            terminal_writes[f"trial-outcome-{item.trial_id}.json"] = {
                "kind": "trial_terminal",
                "identity": terminal_identity,
                **terminal_payload,
            }
        receipt = ApprovalReceipt(
            outcome=OperationOutcome.SUCCESS,
            approved_batch=approved,
            review=review.reference,
            acknowledgment=request.acknowledgment,
            trial_dispositions=dispositions,
            next_action=ValidateDomainJudgmentContinuation(packet=approved)
            if any(value == "pending" for _, value in dispositions)
            else None,
        )
        raw_transition["consumed"] = True
        state.update(
            {
                "phase": "assessment"
                if any(value == "pending" for _, value in dispositions)
                else "ready_to_finalize",
                "trial_dispositions": dict(dispositions),
                "approved_batch_identity": approved_identity,
            }
        )
        transition_name = f"transition-{request.transition.identity.removeprefix('sha256:')}.json"
        write_jsons(
            workspace,
            {
                transition_name: raw_transition,
                "approved_batch.json": {
                    "kind": "approved_batch",
                    "identity": approved_identity,
                    **approved_payload,
                },
                f"approval-{review.identity.removeprefix('sha256:')}.json": receipt.model_dump(
                    mode="json"
                ),
                "state.json": state,
                **terminal_writes,
            },
        )
        if any(value == "pending" for _, value in dispositions):
            # Packet issuance is server-owned: callers never manufacture the
            # trial/result/domain identity needed for the first validation.
            from rob2_kit.packs import SCIENTIFIC_PACK

            from .domains import prepare_domain_packet

            first_trial = next(trial for trial, value in dispositions if value == "pending")
            packet = prepare_domain_packet(
                workspace,
                approved,
                trial_id=first_trial,
                domain_id=SCIENTIFIC_PACK.domains[0].id,
            )
            receipt = receipt.model_copy(
                update={"next_action": ValidateDomainJudgmentContinuation(packet=packet)}
            )
            write_jsons(
                workspace,
                {
                    f"approval-{review.identity.removeprefix('sha256:')}.json": receipt.model_dump(
                        mode="json"
                    )
                },
            )
        return receipt


__all__ = [
    "ApprovalReceipt",
    "ApprovalRequest",
    "ClarificationAlternative",
    "ClarificationReceipt",
    "ClarificationSelection",
    "ClarityDeclaration",
    "ClarityItem",
    "ClarityState",
    "ComparisonGroup",
    "Compatibility",
    "CompatibilityFinding",
    "DerivedResult",
    "EvidenceSet",
    "EffectPrecision",
    "ConfidenceInterval",
    "PValue",
    "GroupBoundValues",
    "NeedsInputReason",
    "OutcomeMeasurementCoverage",
    "PopulationAccount",
    "PreapprovalNeedsInput",
    "ProposalInput",
    "ProposalRepair",
    "ProposalRepairReceipt",
    "ProposalReceipt",
    "ProposalReview",
    "Quantity",
    "ReportedResult",
    "ResultCard",
    "ResultCardInput",
    "ResultClarification",
    "ResultTarget",
    "SingleGroupCategoryProfile",
    "UnavailableResult",
    "ComparativeEffect",
    "acknowledge_proposal",
    "apply_clarification",
    "approve_batch",
    "save_proposal",
]
