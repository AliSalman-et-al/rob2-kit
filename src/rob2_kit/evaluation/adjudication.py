"""Immutable, assessment-independent adjudication records.

Adjudication is deliberately a sidecar: this module contains no assessment
state and never accepts or produces a canonical domain label.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

SCHEMA = "rob2-kit.adjudication-sidecar.v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


class AdjudicationClassification(StrEnum):
    AGREEMENT = "agreement"
    DEFENSIBLE_DEVIATION = "defensible_deviation"
    LIKELY_MODEL_ERROR = "likely_model_error"
    INDETERMINATE = "indeterminate"
    REFERENCE_ISSUE = "reference_issue"


def _identity(value: str, field: str) -> str:
    if not _ID.fullmatch(value) and not _HASH.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identity")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class EvidenceLocator(_StrictModel):
    """A source-bound locator retained as audit evidence, not assessment input."""

    source_identity: StrictStr = Field(min_length=1)
    locator: StrictStr = Field(min_length=1)
    note: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def source_identity_is_valid(self) -> EvidenceLocator:
        _identity(self.source_identity, "source_identity")
        return self


class AdjudicationSidecar(_StrictModel):
    """One immutable adjudication observation for one result/question cell."""

    schema_: StrictStr = Field(default=SCHEMA, alias="schema")
    identity: StrictStr | None = None
    run_identity: StrictStr = Field(min_length=1)
    case_identity: StrictStr = Field(min_length=1)
    result_identity: StrictStr = Field(min_length=1)
    domain_identity: StrictStr = Field(min_length=1)
    question_identity: StrictStr = Field(min_length=1)
    checkpoint_identity: StrictStr = Field(min_length=1)
    source_identities: tuple[StrictStr, ...] = Field(min_length=1)
    reference_label: StrictStr = Field(min_length=1)
    model_label: StrictStr = Field(min_length=1)
    provisional_label: StrictStr = Field(min_length=1)
    classification: AdjudicationClassification
    evidence: tuple[EvidenceLocator, ...] = ()
    rationale: StrictStr = Field(min_length=1)
    unresolved_facts: tuple[StrictStr, ...] = ()
    follow_up: tuple[StrictStr, ...] = ()
    reviewer_identity: StrictStr = Field(min_length=1)
    reviewer_role: StrictStr = Field(min_length=1)
    adjudication_version: StrictStr = Field(min_length=1)
    reviewed_at: datetime
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_sidecar(self) -> AdjudicationSidecar:
        if self.schema_ != SCHEMA:
            raise ValueError("schema is invalid")
        for name in (
            "run_identity",
            "case_identity",
            "result_identity",
            "domain_identity",
            "question_identity",
            "checkpoint_identity",
        ):
            _identity(getattr(self, name), name)
        if not self.source_identities:
            raise ValueError("source_identities must not be empty")
        for source_identity in self.source_identities:
            _identity(source_identity, "source_identity")
        if len(set(self.source_identities)) != len(self.source_identities):
            raise ValueError("source_identities must be distinct")
        if not set(locator.source_identity for locator in self.evidence) <= set(
            self.source_identities
        ):
            raise ValueError("evidence references an undeclared source identity")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        expected = content_identity(
            self.model_dump(mode="json", by_alias=True, exclude={"identity"})
        )
        if self.identity is None:
            object.__setattr__(self, "identity", expected)
        elif self.identity != expected:
            raise ValueError("identity does not match sidecar content")
        return self


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_identity(value: Mapping[str, Any] | AdjudicationSidecar) -> str:
    """Return the deterministic identity of sidecar content, excluding its identity."""

    if isinstance(value, AdjudicationSidecar):
        payload = value.model_dump(mode="json", by_alias=True, exclude={"identity"})
    else:
        payload = dict(value)
        payload.pop("identity", None)
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def validate_sidecar(value: Mapping[str, Any] | AdjudicationSidecar) -> AdjudicationSidecar:
    """Parse and integrity-check one sidecar record."""

    return (
        value
        if isinstance(value, AdjudicationSidecar)
        else AdjudicationSidecar.model_validate(value)
    )


def write_sidecar(path: str | Path, value: Mapping[str, Any] | AdjudicationSidecar) -> None:
    """Write one canonical JSON sidecar atomically."""

    record = validate_sidecar(value)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical(record.model_dump(mode="json", by_alias=True)) + b"\n"
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


def read_sidecar(path: str | Path) -> AdjudicationSidecar:
    """Read and integrity-check one JSON sidecar."""

    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    return validate_sidecar(value)


def validate_sidecars(
    values: Iterable[Mapping[str, Any] | AdjudicationSidecar],
) -> tuple[AdjudicationSidecar, ...]:
    """Validate a collection and reject duplicate content identities."""

    records = tuple(validate_sidecar(value) for value in values)
    identities = [record.identity for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate adjudication identity")
    return records
