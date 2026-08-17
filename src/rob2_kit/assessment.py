"""Strict scientific identities used when proposing an RoB 2 batch."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Field, model_validator

from rob2_kit.detail import DetailReference
from rob2_kit.models import StrictModel, sha256
from rob2_kit.sources import Source, TrialInput
from rob2_kit.text_projection import TextProjectionIdentity


class ProposalEvidenceHandle(StrictModel):
    """The opaque retrieval handle allowed at the proposal boundary."""

    handle_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class OutcomeTarget(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    label: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]


class Trial(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    label: Annotated[str, Field(min_length=1)]


class Randomization(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    description: Annotated[str, Field(min_length=1)]


class Arm(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    label: Annotated[str, Field(min_length=1)]


class Comparison(StrictModel):
    intervention_arm_id: str
    comparator_arm_id: str

    @model_validator(mode="after")
    def distinct_arms(self) -> Comparison:
        if self.intervention_arm_id == self.comparator_arm_id:
            raise ValueError("comparison arms must differ")
        return self


class ResultAnchor(StrictModel):
    source_id: str
    source_sha256: str
    page_number: Annotated[int, Field(ge=1)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> ResultAnchor:
        if self.end <= self.start:
            raise ValueError("anchor end must follow start")
        return self


class ResultSpec(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    trial: Trial
    randomization: Randomization
    arms: tuple[Arm, ...] = Field(min_length=2)
    comparison: Comparison
    effect_of_interest: Annotated[str, Field(min_length=1)]
    outcome_definition: Annotated[str, Field(min_length=1)]
    measurement: Annotated[str, Field(min_length=1)]
    time_point: Annotated[str, Field(min_length=1)]
    population: Annotated[str, Field(min_length=1)]
    analysis_method: Annotated[str, Field(min_length=1)]
    analysis_choices: tuple[str, ...] = Field(min_length=1)
    effect_measure: Annotated[str, Field(min_length=1)]
    numerical_values: tuple[str, ...] = ()
    denominators: tuple[int, ...] = ()
    anchor: ResultAnchor

    @model_validator(mode="after")
    def references_arms_once(self) -> ResultSpec:
        ids = tuple(arm.id for arm in self.arms)
        if len(ids) != len(set(ids)):
            raise ValueError("arm ids must be unique")
        if (
            self.comparison.intervention_arm_id not in ids
            or self.comparison.comparator_arm_id not in ids
        ):
            raise ValueError("comparison must reference ResultSpec arms")
        if self.denominators and (
            not self.numerical_values or len(self.denominators) != len(self.numerical_values)
        ):
            raise ValueError("denominators require one numerical value each")
        if any(value < 1 for value in self.denominators):
            raise ValueError("denominators must be positive")
        return self


class BatchRequest(StrictModel):
    outcome_target: OutcomeTarget
    trial_inputs: tuple[TrialInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def trial_inputs_are_unique(self) -> BatchRequest:
        ids = tuple(item.id for item in self.trial_inputs)
        if len(ids) != len(set(ids)):
            raise ValueError("BatchRequest TrialInput ids must be unique")
        return self


class LocalSourceRecord(StrictModel):
    source: Source
    input_path: str
    occurrence: Annotated[int, Field(ge=0)]


class Proposal(StrictModel):
    request: BatchRequest
    trials: tuple[Trial, ...]
    result_specs: tuple[ResultSpec, ...]
    sources: tuple[Source, ...]

    @model_validator(mode="after")
    def proposal_is_complete(self) -> Proposal:
        trial_ids = {trial.id for trial in self.trials}
        request_ids = {trial.id for trial in self.request.trial_inputs}
        result_ids = {spec.trial.id for spec in self.result_specs}
        source_ids = {source.id for source in self.sources}
        if (
            trial_ids != request_ids
            or result_ids != request_ids
            or len(self.result_specs) != len(request_ids)
        ):
            raise ValueError(
                "proposal requires exactly one Trial and ResultSpec for every TrialInput"
            )
        if any(source.trial_id not in trial_ids for source in self.sources):
            raise ValueError("proposal Sources must belong to proposal Trials")
        request_labels = {item.id: item.label for item in self.request.trial_inputs}
        if any(trial.label != request_labels[trial.id] for trial in self.trials):
            raise ValueError("Trial labels must match requested TrialInputs")
        for spec in self.result_specs:
            trial = next(trial for trial in self.trials if trial.id == spec.trial.id)
            if spec.trial != trial:
                raise ValueError("ResultSpec Trial must exactly match proposal Trial")
            if spec.anchor.source_id not in source_ids:
                raise ValueError("ResultSpec anchor Source is not in proposal")
            source = next(source for source in self.sources if source.id == spec.anchor.source_id)
            if source.sha256 != spec.anchor.source_sha256 or source.trial_id != spec.trial.id:
                raise ValueError("ResultSpec anchor does not bind its Trial Source")
        return self


class ResultDraft(StrictModel):
    """The small, handle-based input used to reconstruct one canonical Result."""

    result_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")] = "result"
    randomization: Randomization
    arms: tuple[Arm, ...] = Field(min_length=2)
    comparison: Comparison
    effect_of_interest: Annotated[str, Field(min_length=1)]
    outcome_definition: Annotated[str, Field(min_length=1)]
    measurement: Annotated[str, Field(min_length=1)]
    time_point: Annotated[str, Field(min_length=1)]
    population: Annotated[str, Field(min_length=1)]
    analysis_method: Annotated[str, Field(min_length=1)]
    analysis_choices: tuple[str, ...] = Field(min_length=1)
    effect_measure: Annotated[str, Field(min_length=1)]
    numerical_values: tuple[str, ...] = ()
    denominators: tuple[int, ...] = ()
    anchor: ProposalEvidenceHandle

    @model_validator(mode="before")
    @classmethod
    def normalize_retrieval_handle(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("anchor"), BaseModel):
            anchor = value["anchor"]
            return {**value, "anchor": {"handle_id": anchor.handle_id}}
        return value

    @model_validator(mode="after")
    def text_anchor_only(self) -> ResultDraft:
        return self


class ProposalDraft(StrictModel):
    """Minimal v2 proposal input; all Trial/Source identity comes from capture."""

    outcome_target: OutcomeTarget
    results: tuple[ResultDraft, ...] = Field(min_length=1)


class ProposalRepair(StrictModel):
    pointer: Annotated[str, Field(pattern=r"^(?:/|/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*)$")]
    subject: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")] | None = None
    invariant: Literal[
        "captured_batch",
        "trial_set",
        "result_set",
        "result_anchor",
        "anchor_scope",
        "anchor_stale",
        "anchor_integrity",
        "outcome_target",
        "draft_schema",
    ]
    actual: Literal[
        "missing",
        "duplicate",
        "out_of_scope",
        "invalid",
        "stale",
        "mismatch",
        "wrong_type",
        "extra",
    ]
    action: Literal[
        "add_result",
        "remove_result",
        "replace_anchor",
        "refresh_capture",
        "retry",
        "correct_field",
        "remove_field",
    ]
    count: Annotated[int, Field(ge=0)] | None = None


class ProposalValid(StrictModel):
    status: Literal["valid"] = "valid"
    draft_hash: str
    captured_batch_hash: str
    proposal_hash: str


class ProposalInvalid(StrictModel):
    status: Literal["repair"] = "repair"
    draft_hash: str
    repairs: tuple[ProposalRepair, ...]


class ProposalValidationCondition(StrictModel):
    status: Literal["condition"] = "condition"
    draft_hash: str


ProposalValidation: TypeAlias = Annotated[
    ProposalValid | ProposalInvalid | ProposalValidationCondition, Field(discriminator="status")
]


class ProposalSaved(StrictModel):
    status: Literal["saved"] = "saved"
    proposal_ref: DetailReference
    draft_hash: str
    captured_batch_hash: str
    version_hash: str
    next_action: Literal["review_proposal"] = "review_proposal"


class ProposalDraftRepair(StrictModel):
    status: Literal["repair"] = "repair"
    draft_hash: str
    repairs: tuple[ProposalRepair, ...]
    next_action: Literal["repair_draft"] = "repair_draft"


class ProposalSaveCondition(StrictModel):
    status: Literal["condition"] = "condition"
    draft_hash: str
    next_action: Literal["refresh_capture"] = "refresh_capture"


ProposalReceipt: TypeAlias = Annotated[
    ProposalSaved | ProposalDraftRepair | ProposalSaveCondition, Field(discriminator="status")
]


class ApprovedTrialResult(StrictModel):
    trial_id: str
    result_id: str


class ProposalApproved(StrictModel):
    status: Literal["approved"] = "approved"
    approved_batch_hash: str
    proposal_hash: str
    captured_batch_hash: str
    first_packet_ref: DetailReference
    trial_results: tuple[ApprovedTrialResult, ...] = Field(min_length=1)
    next_action: Literal["answer_active_questions", "review_correction", "finish_trial"]


class ProposalApprovalCondition(StrictModel):
    status: Literal["condition"] = "condition"
    proposal_hash: str
    next_action: Literal["repair"] = "repair"


ProposalApprovalReceipt: TypeAlias = Annotated[
    ProposalApproved | ProposalApprovalCondition, Field(discriminator="status")
]


class CapturedRegistryOutcome(StrictModel):
    """Privacy-preserving registry outcome bound into a Captured Batch."""

    trial_id: str
    status: Literal[
        "matched",
        "ambiguous",
        "not_found",
        "unavailable",
        "not_attempted",
    ]
    record_hash: str | None = None
    captured_source_sha256: str | None = None


class CapturedTrial(StrictModel):
    """One ordered Trial declaration and its verified captured derivatives."""

    trial_input: TrialInput
    sources: tuple[Source, ...]
    source_inventory_hash: str
    projections: tuple[TextProjectionIdentity, ...]
    registry: CapturedRegistryOutcome

    @model_validator(mode="after")
    def inventory_is_bound(self) -> CapturedTrial:
        if self.registry.trial_id != self.trial_input.id:
            raise ValueError("registry outcome must bind its Trial")
        if any(source.trial_id != self.trial_input.id for source in self.sources):
            raise ValueError("captured Sources must bind their Trial")
        if self.source_inventory_hash != sha256(self.sources):
            raise ValueError("captured Source inventory hash mismatch")
        if tuple(identity.source_sha256 for identity in self.projections) != tuple(
            source.sha256 for source in self.sources if source.media_type
        ):
            raise ValueError("text projections must follow the Source inventory")
        return self


class CapturedBatch(StrictModel):
    """Immutable content-addressed intake completed after registry outcomes."""

    schema_version: Literal["rob2-kit.captured-batch.v2"] = "rob2-kit.captured-batch.v2"
    contract_version: Literal[2] = 2
    trial_inputs: tuple[TrialInput, ...] = Field(min_length=1)
    trials: tuple[CapturedTrial, ...] = Field(min_length=1)
    content_hash: str

    @model_validator(mode="after")
    def trials_are_ordered_and_complete(self) -> CapturedBatch:
        if tuple(item.trial_input.id for item in self.trials) != tuple(
            item.id for item in self.trial_inputs
        ):
            raise ValueError("Captured Batch Trial order must match declarations")
        return self


def captured_batch_hash(batch: CapturedBatch) -> str:
    """Return the identity over every Captured Batch field except its identity."""

    return sha256(batch.model_dump(exclude={"content_hash"}))
