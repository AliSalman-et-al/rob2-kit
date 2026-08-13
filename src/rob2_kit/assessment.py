"""Strict scientific identities used when proposing an RoB 2 batch."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from rob2_kit.models import StrictModel
from rob2_kit.sources import Source, TrialInput


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
