from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rob2_kit.evaluation.adjudication import (
    SCHEMA,
    AdjudicationClassification,
    AdjudicationSidecar,
    EvidenceLocator,
    content_identity,
    read_sidecar,
    validate_sidecars,
    write_sidecar,
)


def _record() -> dict:
    return {
        "schema": SCHEMA,
        "run_identity": "run-1",
        "case_identity": "case-1",
        "result_identity": "sha256:" + "1" * 64,
        "domain_identity": "domain-1",
        "question_identity": "question-1",
        "checkpoint_identity": "sha256:" + "2" * 64,
        "source_identities": ("source-1",),
        "reference_label": "reference-label",
        "model_label": "model-label",
        "provisional_label": "provisional-label",
        "classification": "defensible_deviation",
        "evidence": (
            {"source_identity": "source-1", "locator": "page:4", "note": "plan states X"},
        ),
        "rationale": "The retained evidence supports a defensible interpretation.",
        "unresolved_facts": ("timing remains unclear",),
        "follow_up": ("review the supplement",),
        "reviewer_identity": "reviewer-1",
        "reviewer_role": "adjudicator",
        "adjudication_version": "2026-09-20",
        "reviewed_at": datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        "confidence": 0.75,
    }


def test_valid_sidecar_is_frozen_and_cannot_mutate_assessment_labels() -> None:
    record = AdjudicationSidecar.model_validate(_record())
    assert record.identity == content_identity(record)
    assert record.model_label == "model-label"
    external = record.model_dump(mode="json", by_alias=True)
    assert external["schema"] == SCHEMA
    assert "schema_" not in external
    with pytest.raises(ValidationError):
        setattr(record, "model_label", "changed")


def test_unknown_missing_stale_and_orphaned_records_reject() -> None:
    raw = _record()
    unknown = {**raw, "unexpected": True}
    with pytest.raises(ValidationError):
        AdjudicationSidecar.model_validate(unknown)
    missing = dict(raw)
    del missing["reviewer_identity"]
    with pytest.raises(ValidationError):
        AdjudicationSidecar.model_validate(missing)
    stale = {**raw, "identity": "sha256:" + "f" * 64}
    with pytest.raises(ValidationError):
        AdjudicationSidecar.model_validate(stale)
    orphan = {**raw, "evidence": ({"source_identity": "source-2", "locator": "p:1", "note": "x"},)}
    with pytest.raises(ValidationError):
        AdjudicationSidecar.model_validate(orphan)


def test_identical_inputs_have_identical_identity_and_write_is_readable(tmp_path) -> None:
    first = AdjudicationSidecar.model_validate(deepcopy(_record()))
    second = AdjudicationSidecar.model_validate(deepcopy(_record()))
    assert first.identity == second.identity
    path = tmp_path / "adjudication.json"
    write_sidecar(path, first)
    assert read_sidecar(path) == first


def test_duplicate_records_are_rejected_without_touching_canonical_state() -> None:
    record = AdjudicationSidecar.model_validate(_record())
    with pytest.raises(ValueError, match="duplicate"):
        validate_sidecars((record, record))


def test_classification_is_closed_and_source_identity_is_checked() -> None:
    raw = _record()
    raw["classification"] = "correct"
    with pytest.raises(ValidationError):
        AdjudicationSidecar.model_validate(raw)
    with pytest.raises(ValidationError):
        EvidenceLocator.model_validate(
            {"source_identity": "not valid", "locator": "page:1", "note": "x"}
        )
    assert set(AdjudicationClassification) == {
        AdjudicationClassification.AGREEMENT,
        AdjudicationClassification.DEFENSIBLE_DEVIATION,
        AdjudicationClassification.LIKELY_MODEL_ERROR,
        AdjudicationClassification.INDETERMINATE,
        AdjudicationClassification.REFERENCE_ISSUE,
    }
