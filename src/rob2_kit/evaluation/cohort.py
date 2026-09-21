"""Immutable post-audit evaluation cohort records.

The cohort is a post-hoc join between the approved assessment traces and the
reference catalog.  It deliberately does not turn a reference/model label
comparison into an adjudication or a corrected accuracy estimate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .adjudication import content_identity

SCHEMA = "rob2-kit.evaluation-cohort.v1"
COHORT_REVISION = 1
DOMAINS = (
    "domain:randomization",
    "domain:deviations",
    "domain:missing",
    "domain:measurement",
    "domain:selection",
)
OUTCOMES = ("overall-survival", "progression-free-survival", "adverse-events")
LABELS = ("low", "some_concerns", "high")
CLASSIFICATIONS = (
    "agreement",
    "defensible",
    "likely_model_error",
    "indeterminate",
    "reference_issue",
)
SAMPLE_DIMENSIONS = (
    "unsupported_reasoning",
    "denominator_mistakes",
    "scope_drift",
    "inconsistent_evidence_use",
)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_BANNED_KEYS = frozenset(
    {
        "corrected_accuracy",
        "adjusted_accuracy",
        "synthetic_accuracy",
        "synthetic_corrected_accuracy",
        "rationale",
        "adjudication_rationale",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class CohortLabel(StrEnum):
    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"


class CohortClassification(StrEnum):
    AGREEMENT = "agreement"
    DEFENSIBLE = "defensible"
    LIKELY_MODEL_ERROR = "likely_model_error"
    INDETERMINATE = "indeterminate"
    REFERENCE_ISSUE = "reference_issue"


class ReviewerProvenance(_StrictModel):
    """Reviewer state; pending records carry no invented reviewer identity."""

    status: Literal["pending_external_adjudication", "complete"] = "pending_external_adjudication"
    reviewer_identity: StrictStr | None = None
    reviewer_role: StrictStr | None = None
    reviewed_at: StrictStr | None = None
    note: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status(self) -> ReviewerProvenance:
        if self.status == "pending_external_adjudication":
            if any(
                value is not None
                for value in (self.reviewer_identity, self.reviewer_role, self.reviewed_at)
            ):
                raise ValueError("pending reviewer provenance must not invent reviewer details")
        elif any(
            value is None
            for value in (self.reviewer_identity, self.reviewer_role, self.reviewed_at)
        ):
            raise ValueError("complete reviewer provenance requires identity, role, and timestamp")
        return self


class CohortCell(_StrictModel):
    """One immutable domain cell from the pinned run."""

    schema_: StrictStr = Field(default=SCHEMA, alias="schema")
    identity: StrictStr | None = None
    revision: int = Field(default=0, ge=0)
    supersedes: StrictStr | None = None
    campaign_id: StrictStr = Field(min_length=1)
    case_identity: StrictStr = Field(min_length=1)
    trial_id: StrictStr = Field(min_length=1)
    outcome_id: StrictStr = Field(min_length=1)
    result_identity: StrictStr = Field(min_length=1)
    review_identity: StrictStr = Field(min_length=1)
    domain_id: StrictStr = Field(min_length=1)
    question_ids: tuple[StrictStr, ...] = Field(min_length=1)
    checkpoint_identity: StrictStr = Field(min_length=1)
    source_identities: tuple[StrictStr, ...] = Field(min_length=1)
    source_projection_ids: tuple[StrictStr, ...] = Field(min_length=1)
    source_projection_scope: Literal["answer_expansions", "case_source_inventory"]
    reference_label: CohortLabel
    model_label: CohortLabel
    comparison: Literal["agreement", "disagreement"] | None = None
    adjudication_status: Literal["pending_external_adjudication", "complete"] = (
        "pending_external_adjudication"
    )
    classification: CohortClassification | None = None
    uncertainty: Literal["pending", "low", "moderate", "high"] = "pending"
    reviewer_provenance: ReviewerProvenance
    trace_reference: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cell(self) -> CohortCell:
        if self.schema_ != SCHEMA:
            raise ValueError("cohort cell schema is invalid")
        for name in (
            "campaign_id",
            "case_identity",
            "trial_id",
            "outcome_id",
            "result_identity",
            "review_identity",
            "domain_id",
            "checkpoint_identity",
        ):
            if not _ID.fullmatch(getattr(self, name)) and not _HASH.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be an opaque identity")
        if self.outcome_id not in OUTCOMES:
            raise ValueError(f"unsupported outcome: {self.outcome_id}")
        if self.domain_id not in DOMAINS:
            raise ValueError(f"unsupported Domain: {self.domain_id}")
        if self.comparison is None:
            object.__setattr__(
                self,
                "comparison",
                "agreement" if self.reference_label == self.model_label else "disagreement",
            )
        elif self.comparison != (
            "agreement" if self.reference_label == self.model_label else "disagreement"
        ):
            raise ValueError("comparison must reflect original reference and model labels")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("question_ids must be distinct")
        if len(set(self.source_identities)) != len(self.source_identities):
            raise ValueError("source_identities must be distinct")
        if len(set(self.source_projection_ids)) != len(self.source_projection_ids):
            raise ValueError("source_projection_ids must be distinct")
        if not all(_HASH.fullmatch(value) for value in self.source_projection_ids):
            raise ValueError("source_projection_ids must be sha256 identities")
        if self.adjudication_status == "pending_external_adjudication":
            if self.classification is not None or self.uncertainty != "pending":
                raise ValueError(
                    "pending cells must not contain an adjudication classification or certainty"
                )
            if self.reviewer_provenance.status != "pending_external_adjudication":
                raise ValueError("pending cells require pending reviewer provenance")
        elif self.classification is None or self.uncertainty == "pending":
            raise ValueError("complete cells require classification and visible uncertainty")
        if self.supersedes is not None and not _HASH.fullmatch(self.supersedes):
            raise ValueError("supersedes must identify an earlier content hash")
        expected = content_identity(
            self.model_dump(mode="json", by_alias=True, exclude={"identity"})
        )
        if self.identity is None:
            object.__setattr__(self, "identity", expected)
        elif self.identity != expected:
            raise ValueError("cohort cell identity does not match content")
        return self


class PublishedTotals(_StrictModel):
    unit: Literal["outcome", "domain"]
    assessments: int = Field(ge=0)
    domain_cells: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    disagreements: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> PublishedTotals:
        if self.exact_matches + self.disagreements != self.domain_cells:
            raise ValueError("published totals do not reconcile")
        expected_cells = self.assessments * (len(DOMAINS) if self.unit == "outcome" else 1)
        if self.domain_cells != expected_cells:
            raise ValueError("published domain cell total does not match assessment count")
        return self


class AgreementSampleEntry(_StrictModel):
    cell_identity: StrictStr
    selection_seed: StrictStr = Field(min_length=1)
    selection_rank: int = Field(ge=0)
    dimensions: tuple[StrictStr, ...] = Field(min_length=1)
    review_status: Literal["pending_external_adjudication", "complete"] = (
        "pending_external_adjudication"
    )
    reviewer_provenance: ReviewerProvenance

    @model_validator(mode="after")
    def validate_sample(self) -> AgreementSampleEntry:
        if not _HASH.fullmatch(self.cell_identity):
            raise ValueError("sample cell_identity must be a content identity")
        if set(self.dimensions) != set(SAMPLE_DIMENSIONS):
            raise ValueError("agreement sample must cover all prespecified review dimensions")
        if (
            self.review_status == "pending_external_adjudication"
            and self.reviewer_provenance.status != self.review_status
        ):
            raise ValueError("pending agreement sample requires pending reviewer provenance")
        return self


class ModelAccess(_StrictModel):
    adjudication_labels_available: Literal[False] = False
    adjudication_rationales_available: Literal[False] = False
    prompt_capture_status: Literal["not_captured", "verified"] = "not_captured"
    note: StrictStr = Field(min_length=1)


class CohortPartitions(_StrictModel):
    development_case_ids: tuple[StrictStr, ...] = ()
    held_out_case_ids: tuple[StrictStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partitions(self) -> CohortPartitions:
        development = set(self.development_case_ids)
        held_out = set(self.held_out_case_ids)
        if len(development) != len(self.development_case_ids) or len(held_out) != len(
            self.held_out_case_ids
        ):
            raise ValueError("partition case identities must be unique")
        if development & held_out:
            raise ValueError("development and held-out cases overlap")
        return self


class CohortManifest(_StrictModel):
    schema_: StrictStr = Field(default=SCHEMA, alias="schema")
    identity: StrictStr | None = None
    cohort_revision: int = Field(default=COHORT_REVISION, ge=1)
    campaign_id: StrictStr = Field(min_length=1)
    pinned_run: StrictStr = Field(min_length=1)
    reference_catalog: StrictStr = Field(min_length=1)
    status: Literal["baseline_pending_external_adjudication", "adjudicated"] = (
        "baseline_pending_external_adjudication"
    )
    cells: tuple[CohortCell, ...] = Field(min_length=1)
    partitions: CohortPartitions
    published_outcome_totals: dict[str, PublishedTotals]
    published_domain_totals: dict[str, PublishedTotals]
    agreement_sample: tuple[AgreementSampleEntry, ...] = ()
    model_access: ModelAccess
    note: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> CohortManifest:
        if self.schema_ != SCHEMA:
            raise ValueError("cohort manifest schema is invalid")
        if not _ID.fullmatch(self.campaign_id):
            raise ValueError("campaign_id must be an opaque identity")
        identities = [cell.identity for cell in self.cells]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate cohort cell identity")
        keys = [(cell.case_identity, cell.domain_id, cell.revision) for cell in self.cells]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate case/Domain revision")
        if any(cell.campaign_id != self.campaign_id for cell in self.cells):
            raise ValueError("cell campaign binding does not match manifest")
        cases = {cell.case_identity for cell in self.cells}
        if cases != set(self.partitions.development_case_ids) | set(
            self.partitions.held_out_case_ids
        ):
            raise ValueError("partitions must account for every case exactly once")
        if self.status == "baseline_pending_external_adjudication" and any(
            cell.adjudication_status != "pending_external_adjudication" for cell in self.cells
        ):
            raise ValueError("baseline manifests cannot contain complete adjudications")
        if (
            self.model_access.adjudication_labels_available
            or self.model_access.adjudication_rationales_available
        ):
            raise ValueError("model access must exclude adjudication labels and rationales")
        expected_outcome = _totals(self.cells, key=lambda cell: cell.outcome_id, unit="outcome")
        expected_domain = _totals(self.cells, key=lambda cell: cell.domain_id, unit="domain")
        _assert_totals(expected_outcome, self.published_outcome_totals, "outcome")
        _assert_totals(expected_domain, self.published_domain_totals, "Domain")
        agreement_cells = {cell.identity for cell in self.cells if cell.comparison == "agreement"}
        sample_ids = [entry.cell_identity for entry in self.agreement_sample]
        if len(set(sample_ids)) != len(sample_ids) or not set(sample_ids) <= agreement_cells:
            raise ValueError("agreement sample contains non-agreement or duplicate cells")
        if len(set(entry.selection_rank for entry in self.agreement_sample)) != len(
            self.agreement_sample
        ):
            raise ValueError("agreement sample ranks must be unique")
        if any(key in self.model_dump(mode="python") for key in _BANNED_KEYS):
            raise ValueError("synthetic corrected accuracy or rationale fields are forbidden")
        expected = content_identity(
            self.model_dump(mode="json", by_alias=True, exclude={"identity"})
        )
        if self.identity is None:
            object.__setattr__(self, "identity", expected)
        elif self.identity != expected:
            raise ValueError("cohort manifest identity does not match content")
        return self


def _totals(
    cells: Iterable[CohortCell], *, key: Any, unit: Literal["outcome", "domain"]
) -> dict[str, PublishedTotals]:
    grouped: dict[str, list[CohortCell]] = {}
    for cell in cells:
        grouped.setdefault(key(cell), []).append(cell)
    return {
        group: PublishedTotals(
            unit=unit,
            assessments=len({cell.case_identity for cell in rows}),
            domain_cells=len(rows),
            exact_matches=sum(cell.comparison == "agreement" for cell in rows),
            disagreements=sum(cell.comparison == "disagreement" for cell in rows),
        )
        for group, rows in grouped.items()
    }


def _assert_totals(
    expected: Mapping[str, PublishedTotals], observed: Mapping[str, PublishedTotals], scope: str
) -> None:
    if set(expected) != set(observed):
        raise ValueError(f"published {scope} totals keys do not match cohort")
    for key, value in expected.items():
        if observed[key] != value:
            raise ValueError(f"published {scope} totals do not match cohort for {key}")


def content_hash(value: Mapping[str, Any] | CohortCell | CohortManifest) -> str:
    """Return the stable content identity for a cohort object."""

    if isinstance(value, (CohortCell, CohortManifest)):
        payload = value.model_dump(mode="json", by_alias=True, exclude={"identity"})
    else:
        payload = dict(value)
        payload.pop("identity", None)
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )


def validate_cohort(value: Mapping[str, Any] | CohortManifest) -> CohortManifest:
    """Parse and validate one immutable cohort manifest."""

    return value if isinstance(value, CohortManifest) else CohortManifest.model_validate(value)


def read_cohort(path: str | Path) -> CohortManifest:
    with Path(path).open(encoding="utf-8") as handle:
        return validate_cohort(json.load(handle))


def write_cohort(path: str | Path, value: Mapping[str, Any] | CohortManifest) -> None:
    cohort = validate_cohort(value)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            cohort.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def select_agreement_sample(
    cells: Iterable[CohortCell],
    *,
    seed: str = "rob2-kit-2026-09-21-agreement-sample-v1",
    size: int = 10,
) -> tuple[AgreementSampleEntry, ...]:
    """Select a deterministic, prespecified exact-agreement review sample."""

    if size < 1:
        raise ValueError("agreement sample size must be positive")
    candidates = [cell for cell in cells if cell.comparison == "agreement"]
    ranked = sorted(
        candidates,
        key=lambda cell: hashlib.sha256(f"{seed}:{cell.identity}".encode()).hexdigest(),
    )[:size]
    pending = ReviewerProvenance(
        note=(
            "Independent agreement review was not supplied with the pinned audit; "
            "review remains pending."
        )
    )
    return tuple(
        AgreementSampleEntry(
            cell_identity=cast(str, cell.identity),
            selection_seed=seed,
            selection_rank=rank,
            dimensions=SAMPLE_DIMENSIONS,
            reviewer_provenance=pending,
        )
        for rank, cell in enumerate(ranked)
    )


def summarize(cohort: CohortManifest) -> dict[str, Any]:
    """Return counts only; no corrected or adjudication-derived accuracy is computed."""

    return {
        "assessments": len({cell.case_identity for cell in cohort.cells}),
        "domain_cells": len(cohort.cells),
        "exact_matches": sum(cell.comparison == "agreement" for cell in cohort.cells),
        "disagreements": sum(cell.comparison == "disagreement" for cell in cohort.cells),
        "outcome_totals": {
            key: value.model_dump(mode="json")
            for key, value in cohort.published_outcome_totals.items()
        },
        "domain_totals": {
            key: value.model_dump(mode="json")
            for key, value in cohort.published_domain_totals.items()
        },
        "adjudication_status": cohort.status,
    }
