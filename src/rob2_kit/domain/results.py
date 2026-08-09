"""Stable Result identity and immutable ResultSpec contracts."""

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from rob2_kit.domain.canonical import canonical_json_bytes
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
    # Optional typed basis for omitted-time proposal preference.  A lexical
    # word in a Result label/provenance note is never enough to rank analyses;
    # the basis must name an acquired protocol/SAP source explicitly.
    analysis_priority: Literal["protocol_primary", "prespecified_cutoff"] | None = None
    preference_source_locator: str | None = None


def derive_result_spec_revision_id(preimage: Mapping[str, Any]) -> Identifier:
    """Derive a ResultSpec revision ID from its complete non-circular preimage."""
    if "revision_id" in preimage:
        raise ValueError("ResultSpec revision preimage must not contain revision_id")
    digest = hashlib.sha256(canonical_json_bytes(dict(preimage))).hexdigest()[:24]
    return f"revision:result-spec-{digest}"
