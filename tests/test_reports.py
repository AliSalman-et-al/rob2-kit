import csv
import hashlib
import io
import json
from zipfile import ZipFile

from rob2_kit.reports import AssessmentView, DomainView, ReportProjector


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
        signed_off=True,
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
        "signed_off": True,
    }


def test_spreadsheet_exports_neutralize_formula_cells() -> None:
    hostile = assessment_view().model_copy(update={"trial": "=HYPERLINK(\"bad\")"})
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

    assert {
        name: hashlib.sha256(content).hexdigest()
        for name, content in outputs.items()
    } == {
        "json": "790ec38413f41d7740f81b2e3fed9c38db185180220e1fadcea08e120cbe3e5d",
        "summary": "248b0cd8e9afc6e89cf5126536c4f8576896ff0cc4eb7b9f0b4dd686a0be1e78",
        "html": "5c1ed1ff2eec9874f20cd99450c274cd455d7faa22ae5352fe4d45d210e124bd",
        "markdown": "57e17588a1bee6982ffd16e8264df6d3e8409ff4ec91d4d3eac244bee2b37f8e",
        "csv": "c61ac51a9d471a6354be5a37af0e809f05c778f7990d5334c21d5c2a90285285",
        "xlsx": "b449a650c57a69d6f430c77e761cc6aa504dfc2b6e10c3fe564383c29da5f7b8",
    }
