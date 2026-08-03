"""Semantic, cross-format checks for the evidence-first report design."""

import csv
import io
import json
from decimal import Decimal
from zipfile import ZipFile

from rob2_kit.reports import (
    AssessmentView,
    DomainView,
    EstimateView,
    ReportProjector,
    RunIndexProjector,
    RunIndexResultView,
    RunIndexView,
    SignalingQuestionView,
)


def _assessment() -> AssessmentView:
    return AssessmentView(
        assessment_revision_id="revision:assessment-issue61",
        result_id="result:orbit-survival",
        trial="trial:orbit-2",
        comparison="arm:novaferon vs arm:control",
        outcome="Overall survival",
        time_point="36-month data cut",
        effect_of_interest="assignment",
        measurement_instrument="Death registry",
        analysis_population="all randomized participants",
        analysis_model="Cox proportional hazards model",
        effect_measure="HR",
        source_locator="source:primary/table:2/row:overall-survival",
        estimate=EstimateView(
            value=Decimal("0.61"),
            interval_lower=Decimal("0.50"),
            interval_upper=Decimal("0.75"),
        ),
        overall_judgment="some_concerns",
        domains=tuple(
            DomainView(
                domain_id=f"domain:{index}",
                label=label,
                judgment="low",
                rationale="Deterministic decision trace.",
                questions=(
                    SignalingQuestionView(
                        question_id=f"sq:{index}",
                        wording=f"Official wording {index}?",
                        answer="yes",
                        rationale="Rationale retained.",
                    ),
                ),
            )
            for index, label in enumerate(
                (
                    "Bias arising from the randomization process",
                    "Bias due to deviations from intended interventions",
                    "Bias due to missing outcome data",
                    "Bias in measurement of the outcome",
                    "Bias in selection of the reported result",
                ),
                start=1,
            )
        ),
    )


def test_extended_assessment_is_consistent_across_formats() -> None:
    projector = ReportProjector(_assessment())
    rendered = projector.html().decode()
    markdown = projector.markdown().decode()
    payload = json.loads(projector.json())
    csv_rows = list(csv.DictReader(io.StringIO(projector.robvis_csv().decode("utf-8-sig"))))
    with ZipFile(io.BytesIO(projector.xlsx())) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()

    for text in (rendered, markdown):
        assert "HR" in text
        assert "0.61" in text
        assert "0.50" in text and "0.75" in text
        assert "Official wording 1?" in text
    assert "0 accepted evidence claims" in rendered
    assert "Evidence claims: 0" in markdown
    assert payload["effect_measure"] == "HR"
    assert payload["estimate"]["value"] == "0.61"
    assert csv_rows[0]["Effect measure"] == "HR"
    assert csv_rows[0]["Estimate"] == "0.61"
    assert "Effect measure" in sheet and "0.61" in sheet


def test_run_index_has_trial_result_traffic_dashboard_and_zero_evidence() -> None:
    rendered = RunIndexProjector(
        RunIndexView(
            run_id="run:orbit",
            results=(
                RunIndexResultView(
                    trial_id="trial:orbit-2",
                    result_id="result:orbit-survival",
                    state="report_ready",
                    outcome="Overall survival",
                    time_point="36-month data cut",
                    comparison="arm:novaferon vs arm:control",
                    effect_measure="HR",
                    estimate=EstimateView(
                        value="0.61", interval_lower="0.50", interval_upper="0.75"
                    ),
                    evidence_count=0,
                    overall_judgment="some_concerns",
                    domain_judgments={"domain:randomization": "low"},
                ),
            ),
        )
    ).html().decode()
    assert "Trial × Result dashboard" in rendered
    assert "Overall survival" in rendered
    assert "Evidence claims" in rendered
    assert "0" in rendered
    assert "Some concerns" in rendered


def test_report_retains_material_conflicts_uncertainty_and_overall_policy() -> None:
    assessment = _assessment().model_copy(
        update={
            "overall_policy_id": "policy:overall-maximum-domain-1.0.0",
            "overall_policy_hash": "sha256:overall-policy",
            "overall_decision_trace": ("rule:overall:any-concerns",),
            "domains": (
                _assessment().domains[0].model_copy(
                    update={
                        "questions": (
                            _assessment().domains[0].questions[0].model_copy(
                                update={
                                    "conflicts": (("claim:one", "claim:two"),),
                                    "uncertainty": ("registry source unavailable",),
                                }
                            ),
                        )
                    }
                ),
                *_assessment().domains[1:],
            ),
        }
    )
    projector = ReportProjector(assessment)
    html = projector.html().decode()
    markdown = projector.markdown().decode()
    assert "Overall maximum-domain policy" in html
    assert "policy:overall-maximum-domain-1.0.0" in html
    assert "sha256:overall-policy" in html
    assert "claim:one, claim:two" in html
    assert "registry source unavailable" in html
    assert "Conflicts: claim:one, claim:two" in markdown
    assert r"Policy hash: sha256:overall\-policy" in markdown
