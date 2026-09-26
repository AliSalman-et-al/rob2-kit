from __future__ import annotations

import json
from pathlib import Path

import pytest

from rob2_kit.evaluation.cohort import (
    CohortCell,
    CohortManifest,
    ReviewerProvenance,
    read_cohort,
    select_agreement_sample,
    summarize,
)

COHORT_PATH = Path("eval/cohorts/2026-09-21.json")


def _completed_cohort_payload() -> dict:
    cohort = read_cohort(COHORT_PATH)
    payload = cohort.model_dump(mode="json", by_alias=True)
    payload.pop("identity")
    payload["status"] = "adjudicated"
    original_ids = {
        cell["identity"]: (cell["case_identity"], cell["domain_id"]) for cell in payload["cells"]
    }
    for cell in payload["cells"]:
        cell.pop("identity")
        cell.update(
            {
                "adjudication_status": "complete",
                "classification": "indeterminate",
                "uncertainty": "moderate",
                "reviewer_provenance": {
                    "status": "complete",
                    "reviewer_identity": "reviewer-one",
                    "reviewer_role": "independent adjudicator",
                    "reviewed_at": "2026-09-25T10:00:00Z",
                    "note": "The source record was reviewed.",
                },
            }
        )
    completed_ids = {}
    for cell in payload["cells"]:
        completed = CohortCell.model_validate(cell)
        cell["identity"] = completed.identity
        completed_ids[(cell["case_identity"], cell["domain_id"])] = completed.identity
    for entry in payload["agreement_sample"]:
        key = original_ids[entry["cell_identity"]]
        entry["cell_identity"] = completed_ids[key]
    return payload


def test_pinned_cohort_reproduces_audit_counts_and_published_totals() -> None:
    cohort = read_cohort(COHORT_PATH)
    summary = summarize(cohort)

    assert summary["assessments"] == 28
    assert summary["domain_cells"] == 140
    assert summary["exact_matches"] == 93
    assert summary["disagreements"] == 47
    assert summary["outcome_totals"] == {
        "overall-survival": {
            "unit": "outcome",
            "assessments": 10,
            "domain_cells": 50,
            "exact_matches": 39,
            "disagreements": 11,
        },
        "progression-free-survival": {
            "unit": "outcome",
            "assessments": 10,
            "domain_cells": 50,
            "exact_matches": 34,
            "disagreements": 16,
        },
        "adverse-events": {
            "unit": "outcome",
            "assessments": 8,
            "domain_cells": 40,
            "exact_matches": 20,
            "disagreements": 20,
        },
    }
    assert {key: value["exact_matches"] for key, value in summary["domain_totals"].items()} == {
        "domain:randomization": 24,
        "domain:deviations": 22,
        "domain:missing": 13,
        "domain:measurement": 23,
        "domain:selection": 11,
    }


def test_cohort_binds_real_run_provenance_and_keeps_adjudication_pending() -> None:
    cohort = read_cohort(COHORT_PATH)
    assert cohort.status == "baseline_pending_external_adjudication"
    assert len(cohort.partitions.held_out_case_ids) == 28
    assert not cohort.partitions.development_case_ids
    assert not cohort.model_access.adjudication_labels_available
    assert not cohort.model_access.adjudication_rationales_available
    assert len(cohort.agreement_sample) == 10
    assert all(
        entry.review_status == "pending_external_adjudication"
        and set(entry.dimensions)
        == {
            "unsupported_reasoning",
            "denominator_mistakes",
            "scope_drift",
            "inconsistent_evidence_use",
        }
        for entry in cohort.agreement_sample
    )
    for cell in cohort.cells:
        assert cell.result_identity.startswith("sha256:")
        assert cell.review_identity.startswith("sha256:")
        assert cell.checkpoint_identity.startswith("sha256:")
        assert cell.question_ids
        assert cell.source_projection_ids
        assert cell.reviewer_provenance.status == "pending_external_adjudication"
        assert cell.classification is None
        assert cell.uncertainty == "pending"


def test_agreement_sample_selection_is_stable() -> None:
    cohort = read_cohort(COHORT_PATH)
    first = select_agreement_sample(cohort.cells)
    second = select_agreement_sample(cohort.cells)
    assert first == second == cohort.agreement_sample


def test_original_labels_cannot_be_overwritten_by_classification() -> None:
    cohort = read_cohort(COHORT_PATH)
    payload = cohort.model_dump(mode="json", by_alias=True)
    payload["cells"][0]["classification"] = "likely_model_error"
    with pytest.raises(ValueError, match="pending cells"):
        CohortManifest.model_validate(payload)


def test_manifest_rejects_partition_leakage_and_synthetic_accuracy() -> None:
    cohort = read_cohort(COHORT_PATH)
    payload = cohort.model_dump(mode="json", by_alias=True)
    payload["partitions"]["development_case_ids"] = [payload["partitions"]["held_out_case_ids"][0]]
    with pytest.raises(ValueError, match="overlap"):
        CohortManifest.model_validate(payload)

    payload = cohort.model_dump(mode="json", by_alias=True)
    payload["synthetic_corrected_accuracy"] = 0.5
    with pytest.raises(ValueError):
        CohortManifest.model_validate(payload)


def test_pending_reviewer_provenance_cannot_carry_identity() -> None:
    with pytest.raises(ValueError, match="must not invent"):
        ReviewerProvenance(
            reviewer_identity="reviewer-a",
            note="pending",
        )


def test_completed_cell_requires_completed_reviewer_provenance() -> None:
    cell = read_cohort(COHORT_PATH).cells[0].model_dump(mode="json", by_alias=True)
    cell.pop("identity")
    cell.update(
        {
            "adjudication_status": "complete",
            "classification": "agreement",
            "uncertainty": "low",
        }
    )

    with pytest.raises(ValueError, match="complete reviewer provenance"):
        CohortCell.model_validate(cell)


def test_complete_reviewer_provenance_cannot_use_empty_identity() -> None:
    with pytest.raises(ValueError):
        ReviewerProvenance.model_validate(
            {
                "status": "complete",
                "reviewer_identity": "",
                "reviewer_role": "independent adjudicator",
                "reviewed_at": "2026-09-25T10:00:00Z",
                "note": "The source record was reviewed.",
            }
        )


def test_adjudicated_manifest_requires_complete_cells_and_full_domain_set() -> None:
    payload = _completed_cohort_payload()
    valid = CohortManifest.model_validate(payload)
    assert valid.status == "adjudicated"

    missing_domain = _completed_cohort_payload()
    first = missing_domain["cells"][0]
    missing_domain["cells"].remove(
        next(
            cell
            for cell in missing_domain["cells"]
            if cell["case_identity"] == first["case_identity"]
        )
    )
    with pytest.raises(ValueError, match="complete Domain cell set"):
        CohortManifest.model_validate(missing_domain)

    incomplete = _completed_cohort_payload()
    incomplete["cells"][0].update(
        {
            "adjudication_status": "pending_external_adjudication",
            "classification": None,
            "uncertainty": "pending",
            "reviewer_provenance": {
                "status": "pending_external_adjudication",
                "note": "Review is pending.",
            },
        }
    )
    incomplete["cells"][0].pop("identity", None)
    with pytest.raises(ValueError, match="require every cell to be complete"):
        CohortManifest.model_validate(incomplete)


def test_completed_adjudication_changes_keep_a_validated_revision_chain() -> None:
    payload = _completed_cohort_payload()
    first = CohortCell.model_validate(payload["cells"][0])
    revised = first.model_dump(mode="json", by_alias=True)
    revised.update(
        {
            "revision": 1,
            "supersedes": first.identity,
            "classification": "likely_model_error",
            "uncertainty": "high",
            "reviewer_provenance": {
                "status": "complete",
                "reviewer_identity": "reviewer-two",
                "reviewer_role": "independent adjudicator",
                "reviewed_at": "2026-09-25T11:00:00Z",
                "note": "A second review changed the classification.",
            },
        }
    )
    revised.pop("identity")
    revised_cell = CohortCell.model_validate(revised)
    payload["cells"].append(revised_cell.model_dump(mode="json", by_alias=True))
    payload["cohort_revision"] = 2

    cohort = CohortManifest.model_validate(payload)
    assert cohort.cells[-1].supersedes == first.identity
    assert cohort.cells[-1].identity != first.identity
    assert summarize(cohort)["domain_cells"] == 140

    broken = cohort.model_dump(mode="json", by_alias=True)
    broken.pop("identity")
    broken["cells"][-1]["supersedes"] = "sha256:" + "f" * 64
    broken["cells"][-1].pop("identity")
    with pytest.raises(ValueError, match="must supersede the prior immutable cell"):
        CohortManifest.model_validate(broken)


def test_manifest_identity_detects_label_tampering() -> None:
    payload = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    payload["cells"][0]["model_label"] = "high"
    with pytest.raises(ValueError, match="comparison|identity"):
        CohortManifest.model_validate(payload)
