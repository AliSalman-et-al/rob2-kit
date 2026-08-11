"""Stable Result identity and immutable ResultSpec contracts."""

import hashlib
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from rob2_kit.domain.canonical import canonical_json_bytes
from rob2_kit.domain.revisions import Actor, ContentHash, FrozenModel, Identifier, Revision


class ProposalMappingStatus(StrEnum):
    """State of the semantic, pre-confirmation Result mapping."""

    UNMAPPED = "unmapped"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPETING = "competing"


class ResultIdentityCompleteness(StrEnum):
    ENDPOINT_ONLY = "endpoint_only"
    ANALYSIS_PARTIAL = "analysis_partial"
    RESULT_COMPLETE = "result_complete"


class DiscoveryCandidateDisposition(FrozenModel):
    """One attributable disposition for a surfaced discovery observation."""

    candidate_id: Identifier
    disposition: Literal["accepted", "rejected", "unresolved"]
    detail: str = Field(min_length=1)
    superseded_by_candidate_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_supersession(self) -> "DiscoveryCandidateDisposition":
        if self.superseded_by_candidate_id is not None:
            raise ValueError("discovery dispositions do not store supersession")
        return self


class ProposalLimitationKind(StrEnum):
    NO_OUTCOME_TARGETS = "no_outcome_targets"
    NO_REPORTED_ENDPOINTS = "no_reported_endpoints"
    DISCOVERY_LIMITED = "discovery_limited"
    DISCOVERY_FAILED = "discovery_failed"
    RESULT_MAPPING_INCOMPLETE = "result_mapping_incomplete"


class ReportedCandidateProvenance(FrozenModel):
    """Exact, source-authored location for one advisory discovery observation."""

    source_id: Identifier
    parse_id: Identifier
    artifact_hash: ContentHash
    canonical_unit_id: Identifier
    page_number: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    locator: str = Field(min_length=1)
    displayed_text_hash: ContentHash
    discovery_policy_revision: str = Field(min_length=1)
    supporting_locators: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
    uncertainty: str | None = None
    reviewed_by: Actor
    reviewed_at: datetime

    @model_validator(mode="after")
    def validate_extent(self) -> "ReportedCandidateProvenance":
        if self.char_end <= self.char_start:
            raise ValueError("reported candidate provenance must have positive extent")
        return self


class ReportedArmCandidate(FrozenModel):
    candidate_id: Identifier
    trial_id: Identifier
    randomization_candidate_id: Identifier
    label: str = Field(min_length=1)
    provenance: ReportedCandidateProvenance
    relationship: Literal["reported", "corroborating", "conflicting", "updated"] = "reported"
    related_candidate_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_relationship(self) -> "ReportedArmCandidate":
        if self.relationship == "reported" and self.related_candidate_ids:
            raise ValueError("reported candidate relationship cannot name related candidates")
        if self.relationship != "reported" and not self.related_candidate_ids:
            raise ValueError("cross-source candidate relationship requires related candidates")
        if self.candidate_id in self.related_candidate_ids or (
            len(set(self.related_candidate_ids)) != len(self.related_candidate_ids)
        ):
            raise ValueError("candidate relationships must be unique and cannot reference self")
        return self


class ReportedRandomizationCandidate(FrozenModel):
    candidate_id: Identifier
    trial_id: Identifier
    label: str = Field(min_length=1)
    provenance: ReportedCandidateProvenance
    arm_candidate_ids: tuple[Identifier, ...] = Field(min_length=1)
    relationship: Literal["reported", "corroborating", "conflicting", "updated"] = "reported"
    related_candidate_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_arms(self) -> "ReportedRandomizationCandidate":
        if len(set(self.arm_candidate_ids)) != len(self.arm_candidate_ids):
            raise ValueError("reported randomization arm_candidate_ids must be unique")
        if self.relationship == "reported" and self.related_candidate_ids:
            raise ValueError("reported candidate relationship cannot name related candidates")
        if self.relationship != "reported" and not self.related_candidate_ids:
            raise ValueError("cross-source candidate relationship requires related candidates")
        if self.candidate_id in self.related_candidate_ids or (
            len(set(self.related_candidate_ids)) != len(self.related_candidate_ids)
        ):
            raise ValueError("candidate relationships must be unique and cannot reference self")
        return self


class ReportedEndpointCandidate(FrozenModel):
    candidate_id: Identifier
    trial_id: Identifier
    label: str = Field(min_length=1)
    provenance: ReportedCandidateProvenance
    randomization_candidate_id: Identifier | None = None
    experimental_arm_candidate_id: Identifier | None = None
    comparator_arm_candidate_id: Identifier | None = None
    outcome_construct: str | None = None
    time_point: str | None = None
    measurement_instrument: str | None = None
    effect_measure: str | None = None
    population: str | None = None
    analysis: str | None = None
    estimate: "Estimate | None" = None
    relationship: Literal["reported", "corroborating", "conflicting", "updated"] = "reported"
    related_candidate_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_comparison(self) -> "ReportedEndpointCandidate":
        arms = (self.experimental_arm_candidate_id, self.comparator_arm_candidate_id)
        if any(arm is not None for arm in arms) and (
            self.randomization_candidate_id is None or any(arm is None for arm in arms)
        ):
            raise ValueError(
                "reported endpoint comparison requires one randomization and both arms"
            )
        if (
            self.experimental_arm_candidate_id == self.comparator_arm_candidate_id
            and self.experimental_arm_candidate_id
        ):
            raise ValueError("reported endpoint comparison arms must differ")
        if self.relationship == "reported" and self.related_candidate_ids:
            raise ValueError("reported candidate relationship cannot name related candidates")
        if self.relationship != "reported" and not self.related_candidate_ids:
            raise ValueError("cross-source candidate relationship requires related candidates")
        if self.candidate_id in self.related_candidate_ids or (
            len(set(self.related_candidate_ids)) != len(self.related_candidate_ids)
        ):
            raise ValueError("candidate relationships must be unique and cannot reference self")
        return self


class ProposalDiscoveryCoverageReceipt(FrozenModel):
    receipt_id: Identifier
    trial_id: Identifier
    source_id: Identifier
    parse_id: Identifier
    source_artifact_hash: ContentHash
    mode: Literal["target_guided", "structure_first"]
    state: Literal["complete", "complete_with_limitations", "failed", "no_candidates"]
    discovery_policy_revision: str = Field(min_length=1)
    required_passes: tuple[str, ...] = Field(min_length=1)
    completed_passes: tuple[str, ...] = ()
    structural_passes: tuple[str, ...] = ()
    query_passes: tuple[str, ...] = ()
    traversed_continuations: tuple[str, ...] = ()
    reviewed_unit_ids: tuple[Identifier, ...] = ()
    omitted_or_unreadable_regions: tuple[str, ...] = ()
    candidate_ids: tuple[Identifier, ...] = ()
    candidate_dispositions: tuple[DiscoveryCandidateDisposition, ...] = ()
    reviewed_by: Actor | None = None
    reviewed_at: datetime | None = None
    terminal_stopping_reason: str = Field(min_length=1)
    detail: str | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> "ProposalDiscoveryCoverageReceipt":
        terminal = {"complete", "complete_with_limitations", "no_candidates", "failed"}
        if self.state in terminal and not set(self.required_passes) <= set(self.completed_passes):
            raise ValueError("terminal discovery receipt is missing required passes")
        if self.state in {"complete_with_limitations", "failed"} and not self.detail:
            raise ValueError("limited or failed discovery receipt requires detail")
        dispositions = {item.candidate_id for item in self.candidate_dispositions}
        if dispositions != set(self.candidate_ids):
            raise ValueError(
                "coverage receipt requires one disposition for every surfaced candidate"
            )
        if len(dispositions) != len(self.candidate_dispositions):
            raise ValueError("coverage receipt requires exactly one disposition per candidate")
        if self.state in terminal and (
            self.reviewed_by is None or self.reviewed_at is None
        ):
            raise ValueError(
                "terminal discovery receipt requires reviewer identity and timestamp"
            )
        return self


class ProposalLimitation(FrozenModel):
    kind: ProposalLimitationKind
    scope: Identifier
    material: bool
    detail: str = Field(min_length=1)
    recovery_actions: tuple[str, ...] = Field(min_length=1)
    receipt_ids: tuple[Identifier, ...] = ()
    candidate_ids: tuple[Identifier, ...] = ()
    source_id: Identifier | None = None
    source_artifact_hash: ContentHash | None = None
    parse_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ProposalLimitation":
        identity = (self.source_id, self.source_artifact_hash, self.parse_id)
        if any(item is not None for item in identity) and any(item is None for item in identity):
            raise ValueError(
                "proposal limitation source identity requires Source, artifact, and Parse"
            )
        return self


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
