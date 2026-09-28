from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from rob2_kit.evaluation.cohort import (
    CohortLabel,
    read_cohort,
    select_agreement_sample,
    summarize,
)
from scripts.build_fresh_adjudication_cohort import _segments, build

COHORT_PATH = Path("eval/cohorts/2026-09-27-fresh.json")
RECONCILIATION_PATH = Path("eval/cohorts/2026-09-27-fresh-reconciliation.json")
RUN_ROOT = Path("eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798")
AUDIT_ROOT = Path("eval/runs/2026-09-27")


def test_fresh_inventory_ignores_later_campaigns(tmp_path: Path) -> None:
    later = tmp_path / "later-campaign" / "runs" / "overall-survival" / "ENZAMET"
    later.mkdir(parents=True)
    (later / "phase-1.jsonl").write_text('{"type":"turn.started"}\n', encoding="utf-8")
    assert _segments(tmp_path, tmp_path, {}, "frozen-campaign") == []


def test_fresh_campaign_is_reproducible_development_evidence() -> None:
    cohort = read_cohort(COHORT_PATH)
    summary = summarize(cohort)

    assert len(cohort.partitions.development_case_ids) == 26
    assert cohort.partitions.held_out_case_ids == ()
    assert summary["domain_cells"] == 130
    assert summary["exact_matches"] == 83
    assert summary["disagreements"] == 47
    assert (
        sum(
            (cell.reference_label == CohortLabel.LOW) == (cell.model_label == CohortLabel.LOW)
            for cell in cohort.cells
        )
        == 96
    )
    assert sum(cell.reference_label == CohortLabel.LOW for cell in cohort.cells) == 104
    assert all(
        cell.adjudication_status == "pending_external_adjudication"
        and cell.classification is None
        and cell.uncertainty == "pending"
        and cell.reviewer_provenance.reviewer_identity is None
        for cell in cohort.cells
    )
    assert cohort.agreement_sample == select_agreement_sample(
        cohort.cells, seed="rob2-kit-2026-09-27-fresh-agreement-sample-v1", size=10
    )

    checked_in = json.loads(RECONCILIATION_PATH.read_text(encoding="utf-8"))
    assert checked_in["coverage"] == {
        "assessment_cases": 26,
        "domain_cells": 130,
        "exact_domain_agreements": 83,
        "low_vs_non_low_agreements": 96,
        "exact_overall_agreements": 2,
        "all_low_baseline_agreements": 104,
        "disagreement_cells": 47,
        "matching_label_sample_cells": 10,
        "pending_ai_triage_rows": 57,
        "independent_reviews_complete": 0,
        "scope_decisions_recorded": 26,
        "scope_decisions_independently_certified": 0,
    }


@pytest.mark.skipif(not RUN_ROOT.is_dir(), reason="retained campaign logs are unavailable")
def test_fresh_campaign_rebuild_matches_published_artifacts() -> None:
    rebuilt_cohort, rebuilt = build(Path("eval/reference"), RUN_ROOT, AUDIT_ROOT)
    assert rebuilt_cohort.identity == read_cohort(COHORT_PATH).identity
    assert rebuilt == json.loads(RECONCILIATION_PATH.read_text(encoding="utf-8"))


def test_fresh_reconciliation_covers_attempts_evidence_and_pending_matrix() -> None:
    cohort = read_cohort(COHORT_PATH)
    artifact = json.loads(RECONCILIATION_PATH.read_text(encoding="utf-8"))
    segments = artifact["segments"]["items"]
    assert len(segments) == 102
    assert Counter(item["selection"] for item in segments) == {
        "selected_scored_attempt": 59,
        "superseded_original_attempt": 3,
        "unfinished_unscored": 33,
        "e2e_workflow_check": 7,
    }
    assert len({item["path"] for item in segments}) == 102
    assert all(
        item["campaign_directory"]
        and item["case"]
        and item["attempt"] >= 1
        and item["phase"] >= 1
        and item["sha256"].startswith("sha256:")
        for item in segments
    )
    replacement = next(
        item
        for item in artifact["selected_cases"]
        if item["trial"] == "PEACE-1" and item["outcome"] == "progression-free-survival"
    )
    assert replacement["selected_attempt"] == 2
    assert [attempt["selected"] for attempt in replacement["attempts"]] == [False, True]

    matrix = artifact["review_matrix"]
    assert len(matrix) == 57
    assert Counter(row["review_kind"] for row in matrix) == {
        "disagreement": 47,
        "matching_label_sample": 10,
    }
    cells = {cell.identity: cell for cell in cohort.cells}
    assert {row["cohort_cell_identity"] for row in matrix} <= set(cells)
    for row in matrix:
        cell = cells[row["cohort_cell_identity"]]
        assert row["result_identity"] == cell.result_identity
        assert row["review_identity"] == cell.review_identity
        assert row["question_ids"] == list(cell.question_ids)
        assert set(row["driver_question_ids"]) <= set(row["question_ids"])
        assert row["checkpoint_identity"] == cell.checkpoint_identity
        assert row["source_identities"] == list(cell.source_identities)
        assert row["source_projection_ids"] == list(cell.source_projection_ids)
        bindings = {
            item["source_id"]: item["projection_id"] for item in row["source_projection_bindings"]
        }
        assert set(bindings) == set(cell.source_identities)
        assert set(bindings.values()) == set(cell.source_projection_ids)
        assert row["trace_reference"] == cell.trace_reference
        assert row["trace_phase"] == int(Path(row["trace_reference"]).stem.removeprefix("phase-"))
        assert row["trace_event_line"] > 0
        assert row["domain_judgment_trace_phase"] == int(
            Path(row["domain_judgment_trace_reference"]).stem.removeprefix("phase-")
        )
        assert row["domain_judgment_event_line"] > 0
        assert row["reference_provenance"]["catalog_version"].startswith("sha256:")
        assert {
            locator["source_id"] for locator in row["source_locators"] if locator["source_id"]
        } <= set(cell.source_identities)
        assert row["review_status"] == "pending_ai_triage_and_evidence_status_audit"
        assert row["independent_adjudication_status"] == "pending_external_adjudication"
        assert row["classification"] is None
        assert row["uncertainty"] == "pending"
        assert row["reviewer_provenance"]["reviewer_identity"] is None
        assert row["evidence_interpretation_status"] == "pending_source_review"
        assert "questions" not in row

    arasens_os_d3 = next(
        row
        for row in matrix
        if row["trial"] == "arasens"
        and row["outcome"] == "overall-survival"
        and row["domain"] == "domain:missing"
    )
    assert len(arasens_os_d3["source_projection_bindings"]) > 1
    assert {
        item["source_id"]: item["projection_id"]
        for item in arasens_os_d3["source_projection_bindings"]
    } == {
        "sh_5e324053fa0ea301": (
            "sha256:c35fcccc9196ec602eb79ec1e5ec5547c13f0d4db445562df96481657658cbc3"
        ),
        "sh_a9168ea65d92ce2e": (
            "sha256:97fcec4057278f8f5ca69b844f1212c53e098782e6eadf7195c35755c8a3d00a"
        ),
    }
    expected_driver_lines = {
        ("overall-survival", "peace-1", "domain:deviations"): 88,
        ("progression-free-survival", "chaarted", "domain:measurement"): 103,
        ("progression-free-survival", "peace-1", "domain:measurement"): 150,
        ("adverse-events", "peace-1", "domain:measurement"): 174,
    }
    for key, event_line in expected_driver_lines.items():
        row = next(row for row in matrix if (row["outcome"], row["trial"], row["domain"]) == key)
        assert row["domain_judgment_event_line"] == event_line

    assert artifact["coverage"]["scope_decisions_independently_certified"] == 0
    assert any(
        item["id"] == "approved-safety-result-scope"
        and item["status"] == "independent_result_scope_review_pending"
        for item in artifact["premise_contrasts"]
    )
    for contrast in artifact["premise_contrasts"]:
        for candidate in contrast["cells"]:
            cell = cells[candidate["cohort_cell_identity"]]
            assert candidate["question_ids"] == list(cell.question_ids)
            assert set(candidate["driver_question_ids"]) <= set(candidate["question_ids"])
            assert candidate["trace_reference"] == cell.trace_reference
            assert candidate["trace_event_line"] > 0

    addendum = artifact["source_triage_addendum"]
    assert addendum["status"] == "provisional_ai_source_triage_recorded"
    assert addendum["independent_adjudication_status"] == "pending_external_adjudication"
    assert addendum["labels_corrected"] is False
    triaged_candidates = addendum["disagreements"]["defensible_alternative_candidates"]
    assert len(triaged_candidates) == 4
    assert addendum["disagreements"]["indeterminate_count"] == 43
    assert (
        {row["cohort_cell_identity"] for row in triaged_candidates}
        | set(addendum["disagreements"]["indeterminate_cell_identities"])
    ) == {row["cohort_cell_identity"] for row in matrix if row["review_kind"] == "disagreement"}
    assert len(addendum["matching_label_controls"]["rows"]) == 10
    assert {row["cohort_cell_identity"] for row in addendum["matching_label_controls"]["rows"]} == {
        row["cohort_cell_identity"]
        for row in matrix
        if row["review_kind"] == "matching_label_sample"
    }
    assert len(addendum["disagreements"]["result_scope_caveats"]) == 2
    assert len(addendum["matching_label_controls"]["caveats"]) == 1
    assert {
        cells[item["cohort_cell_identity"]].domain_id
        for item in addendum["disagreements"]["result_scope_caveats"]
    } == {"domain:deviations", "domain:selection"}
    assert all(
        item["status"] == "unresolved_caveat_not_confirmed_scope_mismatch"
        for item in addendum["disagreements"]["result_scope_caveats"]
    )
    matrix_by_identity = {row["cohort_cell_identity"]: row for row in matrix}
    triage_records = triaged_candidates + addendum["matching_label_controls"]["rows"]
    for record in triage_records:
        row = matrix_by_identity[record["cohort_cell_identity"]]
        assert record["trace_locator"] == {
            "path": row["trace_reference"],
            "phase": row["trace_phase"],
            "event_line": row["trace_event_line"],
        }
        assert record["domain_judgment_locator"] == {
            "path": row["domain_judgment_trace_reference"],
            "phase": row["domain_judgment_trace_phase"],
            "event_line": row["domain_judgment_event_line"],
        }
        assert record["source_projection_bindings"] == row["source_projection_bindings"]
        assert all("source_id" in locator for locator in record["source_locator_refs"])
