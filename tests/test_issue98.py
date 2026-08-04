"""Audit-ledger report contract checks for issue #98."""

from __future__ import annotations

from rob2_kit.reports import EvidenceView, ReportProjector
from tests.test_issue61_report_design import _assessment


def test_extended_audit_report_is_offline_and_discloses_limitations_and_structure() -> None:
    assessment = _assessment()
    question = assessment.domains[0].questions[0].model_copy(
        update={
            "evidence": (
                EvidenceView(
                    evidence_id="claim:table",
                    disposition="supporting",
                    exact_phrase="Treatment arm had 4 events.",
                    source_id="source:report",
                    page=3,
                    provenance="canonical unit unit:report-p3-b2",
                    unit_kind="table_row",
                    table_headers=("Arm", "Events"),
                    context="Primary outcome table",
                ),
            )
        }
    )
    assessment = assessment.model_copy(
        update={
            "limitations": ("Registry source was unavailable.",),
            "domains": (
                assessment.domains[0].model_copy(update={"questions": (question,)}),
                *assessment.domains[1:],
            ),
        }
    )

    html = ReportProjector(assessment).html().decode()

    assert "Registry source was unavailable." in html
    assert "Header-aware table row" in html
    assert "Table headers:" in html and "Arm; Events" in html
    assert "Source context" in html
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "prefers-reduced-motion" in html
    assert "https://" not in html and "http://" not in html
