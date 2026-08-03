"""Stable Result identity and immutable ResultSpec contracts."""

from decimal import Decimal

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel, Identifier, Revision


class Comparison(FrozenModel):
    experimental_arm_id: Identifier = Field(description="Stable ID such as arm:docetaxel.")
    comparator_arm_id: Identifier = Field(description="Stable ID such as arm:control.")


class Result(FrozenModel):
    result_id: Identifier
    trial_id: Identifier
    randomization_id: Identifier
    comparison: Comparison
    effect_of_interest: str = Field(min_length=1)
    outcome_construct: str = Field(min_length=1)
    measurement_instrument: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    analysis_population: str = Field(min_length=1)
    analysis_model: str = Field(min_length=1)
    effect_measure: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)


class Estimate(FrozenModel):
    value: Decimal = Field(description="Reported point estimate.")
    interval_lower: Decimal | None = Field(
        default=None, description="Reported lower interval bound."
    )
    interval_upper: Decimal | None = Field(
        default=None, description="Reported upper interval bound."
    )
    denominator_experimental: int | None = Field(default=None, ge=0)
    denominator_comparator: int | None = Field(default=None, ge=0)


class ResultSpecRevision(Revision):
    result: Result
    estimate: Estimate
    provenance_note: str = Field(min_length=1)
