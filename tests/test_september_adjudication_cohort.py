from __future__ import annotations

import json
from pathlib import Path

from rob2_kit.evaluation.adjudication import validate_sidecar, validate_sidecars
from rob2_kit.evaluation.cohort import read_cohort, summarize

ROOT = Path(".")
RECONCILIATION = ROOT / "tests/fixtures/historical-evaluation/2026-09-27-cohort-reconciliation.json"
INVENTORY = ROOT / "tests/fixtures/historical-evaluation/2026-09-27-trace-inventory.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_september_campaigns_reproduce_published_all_case_and_scope_scores() -> None:
    expected = {
        "2026-09-26": (85, 45, 14, 70, 51, 17, 85, 63),
        "2026-09-27": (78, 52, 24, 120, 70, 26, 130, 78),
    }
    reconciliation = _json(RECONCILIATION)

    for campaign in reconciliation["campaigns"]:
        campaign_id = campaign["campaign_id"]
        (
            matches,
            disagreements,
            primary_cases,
            primary_cells,
            primary_matches,
            sensitivity_cases,
            sensitivity_cells,
            sensitivity_matches,
        ) = expected[campaign_id]
        cohort = read_cohort(ROOT / f"eval/cohorts/{campaign_id}.json")
        summary = summarize(cohort)

        assert cohort.status == "baseline_pending_external_adjudication"
        assert len(cohort.partitions.development_case_ids) == 26
        assert cohort.partitions.held_out_case_ids == ()
        assert all(
            cell.classification is None and cell.uncertainty == "pending" for cell in cohort.cells
        )
        assert summary["domain_cells"] == 130
        assert summary["exact_matches"] == matches
        assert summary["disagreements"] == disagreements
        assert campaign["primary_scope"]["eligible_assessments"] == primary_cases
        assert campaign["primary_scope"]["domain_cells"] == primary_cells
        assert campaign["primary_scope"]["exact_matches"] == primary_matches
        assert campaign["accepted_scope_sensitivity"]["eligible_assessments"] == sensitivity_cases
        assert campaign["accepted_scope_sensitivity"]["domain_cells"] == sensitivity_cells
        assert campaign["accepted_scope_sensitivity"]["exact_matches"] == sensitivity_matches

        sample = campaign["agreement_sample"]
        assert sample["declared_size"] == 10
        assert len(sample["entries"]) == 10
        assert all(entry["comparison"] == "agreement" for entry in sample["entries"])
        assert sample["reviewed"] == 10
        assert sample["pending"] == 0

    september_26 = reconciliation["campaigns"][0]["agreement_sample"]["entries"]
    assert september_26[0]["case_identity"] == "2026-09-26:overall-survival:arasens"
    assert september_26[0]["domain_id"] == "domain:missing"
    assert september_26[0]["review_status"] == "complete"
    assert september_26[0]["reviewer_provenance"]["reviewer_role"].startswith("AI ")
    assert september_26[0]["reviewer_provenance"]["reviewed_at"] == "2026-09-27T14:04:24+05:00"
    assert all(entry["review_status"] == "complete" for entry in september_26)
    assert all(
        entry["reviewer_provenance"]["reviewer_identity"]
        == "codex-agent-issue-475-agreement-sample-followup-2026-09-27"
        for entry in september_26[1:]
    )
    september_27 = reconciliation["campaigns"][1]["agreement_sample"]["entries"]
    assert all(
        entry["review_status"] == "complete"
        and entry["reviewer_provenance"]["reviewed_at"] == "2026-09-27T14:28:06+05:00"
        and entry["reviewer_provenance"]["reviewer_role"].startswith("AI ")
        for entry in september_27
    )


def test_every_disagreement_is_in_trace_reconciliation_and_audit_records_bind_to_cells() -> None:
    reconciliation = _json(RECONCILIATION)
    cohorts = {
        campaign: read_cohort(ROOT / f"eval/cohorts/{campaign}.json")
        for campaign in ("2026-09-26", "2026-09-27")
    }
    sidecars = validate_sidecars(
        validate_sidecar(item)
        for item in _json(ROOT / "eval/cohorts/2026-09-27-source-audits.json")
    )
    assert len(sidecars) == 65

    source_cells: set[tuple[str, str, str]] = set()
    for sidecar in sidecars:
        cohort = cohorts[sidecar.run_identity]
        cell = next(
            item
            for item in cohort.cells
            if item.case_identity == sidecar.case_identity
            and item.domain_id == sidecar.domain_identity
        )
        assert sidecar.result_identity == cell.result_identity
        assert sidecar.checkpoint_identity == cell.checkpoint_identity
        assert sidecar.reference_label == cell.reference_label.value
        assert sidecar.model_label == cell.model_label.value
        assert sidecar.question_identity in cell.question_ids
        source_cells.add((sidecar.run_identity, sidecar.case_identity, sidecar.domain_identity))

    arasens_missing = next(
        record
        for record in sidecars
        if record.case_identity == "2026-09-26:overall-survival:arasens"
        and record.question_identity == "sq:missing:data-available"
    )
    assert arasens_missing.classification.value == "likely_model_error"
    assert arasens_missing.reference_label == arasens_missing.model_label == "low"
    assert "not thereby proven false" in arasens_missing.rationale
    latitude_differential = next(
        record
        for record in sidecars
        if record.case_identity == "2026-09-26:adverse-events:latitude"
        and record.question_identity == "sq:measurement:differential"
    )
    assert latitude_differential.classification.value == "likely_model_error"
    assert latitude_differential.reference_label == latitude_differential.model_label == "low"
    assert "final Domain label is unresolved" in latitude_differential.rationale
    assert latitude_differential.rationale.startswith(
        "Saved answer justification: The same CTCAE grading"
    )
    assert any(
        "PDF p. 4, lines 68–76" in locator.locator and "eh_e8d8c5be69654304" in locator.locator
        for locator in latitude_differential.evidence
    )
    assert "2026-09-27T14:28:06+05:00" == latitude_differential.reviewed_at.isoformat()
    assert len(source_cells) == 28

    latitude_reconciliation = next(
        campaign
        for campaign in reconciliation["campaigns"]
        if campaign["campaign_id"] == "2026-09-26"
    )
    latitude_case = next(
        row
        for row in latitude_reconciliation["cases"]
        if row["case_identity"] == "2026-09-26:adverse-events:latitude"
    )
    latitude_cell = next(
        cell for cell in latitude_case["cells"] if cell["domain_id"] == "domain:measurement"
    )
    assert latitude_cell["source_availability"] == "projection_observed_in_trace"
    assert latitude_cell["retrieval"] == "saved_answer_has_source_window"
    assert latitude_cell["context_delivery"] == "not_observable_in_jsonl"
    assert latitude_cell["interpretation"] == "source_audit_sidecar"
    assert latitude_cell["response_mapping"] == "trace_judgment_matches_score_label"
    assert latitude_cell["policy_attribution"] == "not_assessed"

    for campaign in ("2026-09-26", "2026-09-27"):
        cohort = cohorts[campaign]
        sample_ids = {entry.cell_identity for entry in cohort.agreement_sample}
        sample_cells = {cell.identity: cell for cell in cohort.cells}
        expected_questions = {
            (campaign, sample_cells[identity].case_identity, sample_cells[identity].domain_id, qid)
            for identity in sample_ids
            for qid in sample_cells[identity].question_ids
        }
        actual_questions = {
            (
                record.run_identity,
                record.case_identity,
                record.domain_identity,
                record.question_identity,
            )
            for record in sidecars
            if record.run_identity == campaign
        }
        assert expected_questions <= actual_questions
        assert all(
            record.source_identities
            and all(source_id.startswith("source_") for source_id in record.source_identities)
            and all("source version sha256:" in locator.locator for locator in record.evidence)
            for record in sidecars
            if record.run_identity == campaign
            and record.adjudication_version == "2026-09-27-agreement-sample-source-review-v1"
        )

    for campaign in reconciliation["campaigns"]:
        cohort = cohorts[campaign["campaign_id"]]
        rows = {row["case_identity"]: row for row in campaign["cases"]}
        mismatches = {
            (cell.case_identity, cell.domain_id)
            for cell in cohort.cells
            if cell.revision == 0 and cell.comparison == "disagreement"
        }
        reconciled_mismatches = {
            (case_id, cell["domain_id"])
            for case_id, row in rows.items()
            for cell in row["cells"]
            if cell["comparison"] == "disagreement"
        }
        assert reconciled_mismatches == mismatches
        if campaign["campaign_id"] == "2026-09-26":
            assert campaign["source_audit_coverage"]["source_reviewed_disagreement_cells"] == 0
            assert campaign["source_audit_coverage"]["source_reviewed_agreement_cells"] == 10
            assert campaign["source_audit_coverage"]["class_support"] == {
                "agreement": 8,
                "likely_model_error": 2,
            }
        else:
            assert campaign["source_audit_coverage"]["source_reviewed_disagreement_cells"] == 8
            assert campaign["source_audit_coverage"]["unreviewed_disagreement_cells"] == 44
            assert campaign["source_audit_coverage"]["class_support"] == {
                "agreement": 10,
                "indeterminate": 5,
                "defensible_deviation": 3,
            }


def test_trace_inventory_accounts_for_all_attempts_and_separates_issue_465() -> None:
    inventory = _json(INVENTORY)
    totals = inventory["totals"]

    assert sum(row["files"] for row in totals.values()) == 123
    assert totals["2026-09-26"]["files"] == 59
    assert totals["2026-09-27"]["files"] == 64
    assert totals["2026-09-26"]["selected_segments"] == 52
    assert totals["2026-09-27"]["selected_segments"] == 54
    assert totals["2026-09-27"]["issue_465_e2e_segments"] == 7
    assert sum(row["malformed_lines"] for row in totals.values()) == 0
    assert inventory["duplicate_content_groups"] == []
    assert all("sha256" in row and row["bytes"] > 0 for row in inventory["files"])
