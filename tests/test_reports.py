# ruff: noqa: E501

import csv
import hashlib
import html
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image
from pydantic import ValidationError

from rob2_kit.reports import (
    AssessmentView,
    DiagnosticReportProjector,
    DiagnosticView,
    DomainView,
    EvidenceView,
    ReportProjector,
    RunIndexProjector,
    RunIndexResultView,
    RunIndexView,
    SignalingQuestionView,
    VisualCitationView,
)


def assessment_view() -> AssessmentView:
    return AssessmentView(
        assessment_revision_id="revision:assessment-1",
        result_id="result:mortality-30d",
        trial="Trial <script>alert(1)</script>",
        comparison="Treatment & usual care",
        outcome="Mortality **at 30 days**",
        time_point="30 days",
        effect_of_interest="assignment",
        overall_judgment="some_concerns",
        domains=(
            DomainView(
                domain_id="domain:1",
                label="Randomization <img src=x onerror=alert(1)>",
                judgment="low",
                rationale="Allocation was adequately concealed & documented.",
            ),
            DomainView(
                domain_id="domain:2",
                label="Deviations",
                judgment="some_concerns",
                rationale="No information about deviations.",
            ),
        ),
    )


def test_json_projection_is_canonical_and_byte_stable() -> None:
    projector = ReportProjector(assessment_view())

    first = projector.json()
    second = ReportProjector(assessment_view()).json()

    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first)["assessment_revision_id"] == "revision:assessment-1"


def test_text_projections_escape_hostile_content() -> None:
    projector = ReportProjector(assessment_view())

    html = projector.html().decode()
    markdown = projector.markdown().decode()

    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in markdown
    assert r"\<img" in markdown
    assert r"\<script\>" in markdown
    assert r"\*\*at 30 days\*\*" in markdown
    assert "DRAFT-ONLY HANDS-ON PREVIEW" in html
    assert "DRAFT-ONLY HANDS-ON PREVIEW" in markdown


def test_distributable_prompt_injection_and_markup_are_inert() -> None:
    fixture_root = Path(__file__).parent / "public_fixtures" / "adversarial"
    payloads = (
        (fixture_root / "visible-prompt-injection.txt").read_text(encoding="utf-8"),
        (fixture_root / "hidden-prompt-injection.html").read_text(encoding="utf-8"),
        (fixture_root / "hostile-markup.html").read_text(encoding="utf-8"),
        (fixture_root / "hostile-unicode.txt").read_text(encoding="utf-8"),
    )

    for payload in payloads:
        rendered = (
            ReportProjector(assessment_view().model_copy(update={"trial": payload})).html().decode()
        )
        assert html.escape(payload) in rendered
        assert "<script>" not in rendered
        assert 'href="javascript:' not in rendered
        assert 'src="https://tracking.invalid' not in rendered


def test_robvis_csv_and_xlsx_share_the_canonical_assessment() -> None:
    projector = ReportProjector(assessment_view())

    rows = list(csv.DictReader(io.StringIO(projector.robvis_csv().decode("utf-8-sig"))))
    with ZipFile(io.BytesIO(projector.xlsx())) as workbook:
        shared_strings = b"".join(
            workbook.read(name)
            for name in workbook.namelist()
            if name.endswith("sharedStrings.xml") or name.endswith("sheet1.xml")
        ).decode()

    assert rows == [
        {
            "Assessment": "revision:assessment-1",
            "Study": "Trial <script>alert(1)</script>",
            "Result": "result:mortality-30d",
            "Domain 1": "Low",
            "Domain 2": "Some concerns",
            "Overall": "Some concerns",
        }
    ]
    assert "revision:assessment-1" in shared_strings
    assert "result:mortality-30d" in shared_strings
    assert projector.xlsx() == ReportProjector(assessment_view()).xlsx()


def test_summary_is_a_small_projection_of_the_same_revision() -> None:
    summary = json.loads(ReportProjector(assessment_view()).summary())

    assert summary == {
        "assessment_revision_id": "revision:assessment-1",
        "domain_counts": {"high": 0, "low": 1, "some_concerns": 1},
        "overall_judgment": "some_concerns",
        "result_id": "result:mortality-30d",
    }


def test_bundle_files_are_complete_and_derived_from_the_canonical_assessment() -> None:
    projector = ReportProjector(assessment_view())

    files = projector.bundle_files()

    assert set(files) == {
        "assessment.html",
        "assessment.json",
        "assessment.md",
        "assessment.summary.json",
        "robvis.csv",
        "robvis.xlsx",
        "visual-citations.json",
    }
    assert files["assessment.json"] == projector.json()
    assert files["assessment.html"] == projector.html()
    assert files["assessment.md"] == projector.markdown()
    assert files["assessment.summary.json"] == projector.summary()
    assert files["robvis.csv"] == projector.robvis_csv()
    assert files["robvis.xlsx"] == projector.xlsx()
    assert json.loads(files["visual-citations.json"]) == {
        "assessment_revision_id": "revision:assessment-1",
        "visual_citations": [],
    }


def test_visual_citations_are_preserved_in_every_human_audit_projection() -> None:
    assessment = assessment_view().model_copy(
        update={
            "visual_citations": (
                VisualCitationView(
                    citation_id="revision:visual-1",
                    source_id="source:report",
                    page=2,
                    region=(1.0, 2.0, 3.0, 4.0),
                    label="Primary-outcome table",
                ),
            )
        }
    )
    projector = ReportProjector(assessment)

    assert json.loads(projector.bundle_files()["visual-citations.json"])["visual_citations"] == [
        {
            "citation_id": "revision:visual-1",
            "label": "Primary-outcome table",
            "page": 2,
            "region": [1.0, 2.0, 3.0, 4.0],
            "source_id": "source:report",
        }
    ]
    assert "Primary-outcome table" in projector.html().decode()
    assert "Primary\\-outcome table" in projector.markdown().decode()


def test_static_audit_html_is_semantic_disclosable_printable_and_local_only() -> None:
    assessment = assessment_view().model_copy(
        update={
            "execution_contract": "sha256:execution-contract",
            "domains": (
                DomainView(
                    domain_id="domain:1",
                    label="Bias arising from the randomization process",
                    judgment="low",
                    rationale="The allocation sequence was concealed.",
                    questions=(
                        SignalingQuestionView(
                            question_id="sq:1.1",
                            answer="probably_yes",
                            rationale="The report states that allocation was concealed.",
                            evidence=(
                                EvidenceView(
                                    evidence_id="claim:1",
                                    disposition="supporting",
                                    exact_phrase="Allocation was concealed in sequential envelopes.",
                                    source_id="source:report",
                                    page=2,
                                    provenance="parse:report-v1",
                                    visual_citation=VisualCitationView(
                                        citation_id="visual:1",
                                        source_id="source:report",
                                        page=2,
                                        region=(1.0, 2.0, 3.0, 4.0),
                                        label="Allocation paragraph",
                                        exact_phrase="Allocation was concealed in sequential envelopes.",
                                        render_provenance="crop at 144 dpi",
                                        crop_path="visual-assets/citation-crop.png",
                                        context_path="visual-assets/citation-page.png",
                                    ),
                                ),
                                EvidenceView(
                                    evidence_id="claim:2",
                                    disposition="contradicting",
                                    exact_phrase="Envelope opacity was not described.",
                                    source_id="source:report",
                                    page=3,
                                    provenance="parse:report-v1",
                                ),
                            ),
                            coverage="complete",
                            decision_trace=("rule:1.1",),
                        ),
                    ),
                    coverage="complete",
                    decision_trace=("rule:domain-1",),
                ),
            ),
        }
    )

    rendered = ReportProjector(assessment).html().decode()

    assert '<nav aria-label="RoB 2 domains">' in rendered
    assert 'id="domain-domain-1"' in rendered
    assert "Text-labelled judgment: Low" in rendered
    assert "Signaling question sq:1.1" in rendered
    assert "AI rationale" in rendered
    assert "Supporting evidence" in rendered
    assert "Contradicting evidence" in rendered
    assert "Allocation was concealed in sequential envelopes." in rendered
    assert "Visual citation — agent inspection not performed" in rendered
    assert "crop at 144 dpi" in rendered
    assert 'src="visual-assets/citation-crop.png"' in rendered
    assert 'href="visual-assets/citation-page.png"' in rendered
    assert "<details" in rendered
    assert "@media print" in rendered
    assert ":focus-visible" in rendered
    assert "https://" not in rendered
    assert "http://" not in rendered


def test_nested_visual_assets_are_confined_and_verified(tmp_path: Path) -> None:
    from rob2_kit.application.run_engine import RunEngine

    files = {
        "assessment.html": b"<html></html>",
        "visual-assets/citation-crop.png": b"crop-bytes",
        "visual-assets/citation-page.png": b"page-bytes",
    }
    files["manifest.json"] = (
        json.dumps(
            {
                "files": {
                    name: "sha256:" + hashlib.sha256(content).hexdigest()
                    for name, content in files.items()
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    RunEngine._verify_staged_report_files(tmp_path, files)


def test_visual_asset_materialization_uses_local_page_pixels_and_exact_region() -> None:
    from rob2_kit.application.run_engine import RunEngine
    from rob2_kit.ingestion.project import PageRender

    image = Image.new("RGB", (100, 60), "white")
    raw = io.BytesIO()
    image.save(raw, format="PNG")

    class Parser:
        def screenshot(self, data: bytes, *, page_numbers: tuple[int, ...], dpi: int):
            assert data == b"local-source-bytes"
            assert page_numbers == (2,)
            assert dpi == 144
            return (
                PageRender(
                    page_number=2,
                    dpi=144,
                    pixel_width=100,
                    pixel_height=60,
                    image_hash="sha256:" + "0" * 64,
                    image_bytes=raw.getvalue(),
                ),
            )

    engine = RunEngine(parser=Parser())
    engine._result_spec_for = lambda *_args: SimpleNamespace(
        result=SimpleNamespace(trial_id="trial:1")
    )
    engine._latest_prepared_record = lambda _ledger: SimpleNamespace(
        proposal=SimpleNamespace(
            initialization=SimpleNamespace(
                trials=(
                    SimpleNamespace(
                        trial_id="trial:1",
                        inventory=SimpleNamespace(
                            sources=(
                                SimpleNamespace(
                                    source_id="source:1", artifact_hash="sha256:" + "1" * 64
                                ),
                            )
                        ),
                    ),
                )
            )
        )
    )
    ledger = SimpleNamespace(artifacts=SimpleNamespace(read=lambda digest: b"local-source-bytes"))
    citation = VisualCitationView(
        citation_id="visual:crop",
        source_id="source:1",
        page=2,
        region=(2.0, 3.0, 20.0, 12.0),
        label="Primary table",
    )

    views, assets = engine._materialize_visual_assets(ledger, "run:1", "result:1", (citation,))

    assert views[0].crop_path and views[0].context_path
    assert set(assets) == {views[0].crop_path, views[0].context_path}
    crop = Image.open(io.BytesIO(assets[views[0].crop_path]))
    context = Image.open(io.BytesIO(assets[views[0].context_path]))
    assert crop.size == (36, 18)
    assert context.getpixel((4, 6)) == (154, 90, 18)


def test_run_index_and_diagnostic_reports_preserve_auditable_terminal_state() -> None:
    index = (
        RunIndexProjector(
            RunIndexView(
                run_id="run:1",
                execution_contract="sha256:execution-contract",
                ancillary_outputs=("run-index.json", "project.xlsx"),
                results=(
                    RunIndexResultView(
                        trial_id="trial:1",
                        result_id="result:1",
                        state="report_ready",
                        report="assessment.html",
                        overall_judgment="some_concerns",
                        coverage="complete_with_limitations",
                        limitations=("Expected registry record was unavailable.",),
                    ),
                    RunIndexResultView(
                        trial_id="trial:2",
                        result_id="result:2",
                        state="diagnostic_ready",
                        report="diagnostics/result-2/diagnostic.html",
                        coverage="incomplete",
                        limitations=("Required source is unreadable.",),
                    ),
                ),
            )
        )
        .html()
        .decode()
    )
    diagnostic = (
        DiagnosticReportProjector(
            DiagnosticView(
                result_id="result:2",
                trial_id="trial:2",
                reason="Required source is unreadable.",
                preparation_outcome="trial_failed",
                recovery=("Provide a readable required source and continue the Run.",),
                limitations=("Required source is unreadable.",),
            )
        )
        .html()
        .decode()
    )

    assert "Execution contract" in index
    assert "Terminal outcomes" in index
    assert "Text-labelled traffic-light judgment" in index
    assert "Some concerns" in index
    assert "No valid judgment" in index
    assert "project.xlsx" in index
    assert "Required source is unreadable." in diagnostic
    assert "Preparation outcome:" in diagnostic
    assert "trial failed" in diagnostic
    assert "Recovery path" in diagnostic
    assert "Provide a readable required source and continue the Run." in diagnostic
    assert "No valid judgment is available" in diagnostic
    assert "Overall judgment" not in diagnostic


def test_diagnostic_reports_require_a_nonblank_recovery_path() -> None:
    with pytest.raises(ValidationError, match="diagnostic recovery"):
        DiagnosticView(
            result_id="result:2",
            trial_id="trial:2",
            reason="Required source is unreadable.",
            recovery=(),
        )
    with pytest.raises(ValidationError, match="diagnostic recovery"):
        DiagnosticView(
            result_id="result:2",
            trial_id="trial:2",
            reason="Required source is unreadable.",
            recovery=("   ",),
        )


def test_spreadsheet_exports_neutralize_formula_cells() -> None:
    hostile = assessment_view().model_copy(update={"trial": '=HYPERLINK("bad")'})
    projector = ReportProjector(hostile)

    csv_text = projector.robvis_csv().decode("utf-8-sig")
    with ZipFile(io.BytesIO(projector.xlsx())) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()

    assert "'=HYPERLINK" in csv_text
    assert "<f>" not in sheet
    assert "&apos;=HYPERLINK" in sheet or "'=HYPERLINK" in sheet


def test_all_formats_match_golden_hashes() -> None:
    projector = ReportProjector(assessment_view())
    outputs = {
        "json": projector.json(),
        "summary": projector.summary(),
        "html": projector.html(),
        "markdown": projector.markdown(),
        "csv": projector.robvis_csv(),
        "xlsx": projector.xlsx(),
    }

    assert {name: hashlib.sha256(content).hexdigest() for name, content in outputs.items()} == {
        "json": "fe7b3207a23fde1e25f43fb3ee65eb0a2f7350e876c8b27f6e65f987a9f47d72",
        "summary": "619849d91e243fceb6fdb396480611c4b73fe13502a2bb1037b877766e7bc39e",
        "html": "26aeeef8fd25db33ba577bda4925c9a76a067f0ff15795e05fb94c89500d69b1",
        "markdown": "1788fc4cd40f65cbd6a406d8a22afccfc07f29cb87f476284e176bb9c9253ac0",
        "csv": "c61ac51a9d471a6354be5a37af0e809f05c778f7990d5334c21d5c2a90285285",
        "xlsx": "b449a650c57a69d6f430c77e761cc6aa504dfc2b6e10c3fe564383c29da5f7b8",
    }
