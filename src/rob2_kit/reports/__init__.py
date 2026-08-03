"""Deterministic, read-only projections of a canonical Assessment revision."""

from __future__ import annotations

import csv
import html
import io
import re
from collections import Counter
from datetime import UTC, datetime
from zipfile import ZipFile

from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    AssessmentSignOff,
    JudgmentOverride,
    SignOffWithdrawal,
)
from rob2_kit.domain.canonical import canonical_json_bytes
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import Identifier, RecordReference
from rob2_kit.reports._deterministic_zip import write_deterministic_zip
from rob2_kit.storage.ledger import RevisionProjection, WorkflowLedger

_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
_MARKDOWN_SPECIAL = re.compile(r"([\\`*{}[\]()#+.!_|<>~-])")
_PREVIEW_LABEL = "DRAFT-ONLY HANDS-ON PREVIEW"


class ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DomainView(ReportModel):
    domain_id: Identifier
    label: str = Field(min_length=1)
    judgment: str = Field(pattern=r"^(low|some_concerns|high)$")
    rationale: str = Field(min_length=1)


class VisualCitationView(ReportModel):
    citation_id: Identifier
    source_id: Identifier
    page: int = Field(ge=1)
    region: tuple[float, float, float, float]
    label: str = Field(min_length=1)


class AssessmentView(ReportModel):
    """Resolved, presentation-safe view of one immutable Assessment revision."""

    assessment_revision_id: Identifier
    result_id: Identifier
    trial: str = Field(min_length=1)
    comparison: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    effect_of_interest: str = Field(min_length=1)
    overall_judgment: str = Field(pattern=r"^(low|some_concerns|high)$")
    domains: tuple[DomainView, ...] = Field(min_length=1)
    visual_citations: tuple[VisualCitationView, ...] = ()
    signed_off: bool


class ReportProjector:
    """Render formats that can never be read back as assessment state."""

    def __init__(self, assessment: AssessmentView) -> None:
        self.assessment = assessment

    def json(self) -> bytes:
        return canonical_json_bytes(self.assessment.model_dump(mode="json")) + b"\n"

    def summary(self) -> bytes:
        counts = Counter(domain.judgment for domain in self.assessment.domains)
        value = {
            "assessment_revision_id": self.assessment.assessment_revision_id,
            "domain_counts": {
                judgment: counts[judgment] for judgment in ("high", "low", "some_concerns")
            },
            "overall_judgment": self.assessment.overall_judgment,
            "result_id": self.assessment.result_id,
            "signed_off": self.assessment.signed_off,
        }
        return canonical_json_bytes(value) + b"\n"

    def html(self) -> bytes:
        assessment = self.assessment
        domain_rows = "".join(
            "<tr>"
            f'<th scope="row">{html.escape(domain.label)}</th>'
            f"<td>{html.escape(_display_judgment(domain.judgment))}</td>"
            f"<td>{html.escape(domain.rationale)}</td>"
            "</tr>"
            for domain in assessment.domains
        )
        visual_citations = "".join(
            "<li>"
            f"{html.escape(citation.label)} — {html.escape(citation.source_id)}, "
            f"page {citation.page}, region {html.escape(str(citation.region))}"
            "</li>"
            for citation in assessment.visual_citations
        )
        document = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>RoB 2 assessment report</title></head><body>"
            "<main><h1>RoB 2 assessment report</h1>"
            f"<p><strong>{_PREVIEW_LABEL}</strong>: not a public-v1 release. "
            "Only a human reviewer can sign off an exact Assessment revision.</p>"
            f"<p><strong>Assessment revision:</strong> "
            f"{html.escape(assessment.assessment_revision_id)}</p>"
            f"<p><strong>Trial:</strong> {html.escape(assessment.trial)}</p>"
            f"<p><strong>Comparison:</strong> {html.escape(assessment.comparison)}</p>"
            f"<p><strong>Outcome:</strong> {html.escape(assessment.outcome)}</p>"
            f"<p><strong>Time point:</strong> {html.escape(assessment.time_point)}</p>"
            "<table><thead><tr><th>Domain</th><th>Judgment</th>"
            f"<th>Rationale</th></tr></thead><tbody>{domain_rows}</tbody></table>"
            f"<p><strong>Overall:</strong> "
            f"{html.escape(_display_judgment(assessment.overall_judgment))}</p>"
            f"<p><strong>Status:</strong> "
            f"{'Signed off' if assessment.signed_off else 'Unsigned draft'}</p>"
            "<h2>Visual citations</h2>"
            f"<ul>{visual_citations}</ul>"
            "</main></body></html>\n"
        )
        return document.encode()

    def markdown(self) -> bytes:
        assessment = self.assessment
        lines = [
            "# RoB 2 assessment report",
            "",
            f"**{_PREVIEW_LABEL}** — not a public-v1 release. "
            "Only a human reviewer can sign off an exact Assessment revision.",
            "",
            f"- Assessment revision: {_escape_markdown(assessment.assessment_revision_id)}",
            f"- Trial: {_escape_markdown(assessment.trial)}",
            f"- Comparison: {_escape_markdown(assessment.comparison)}",
            f"- Outcome: {_escape_markdown(assessment.outcome)}",
            f"- Time point: {_escape_markdown(assessment.time_point)}",
            "",
            "| Domain | Judgment | Rationale |",
            "|---|---|---|",
        ]
        lines.extend(
            f"| {_escape_markdown(domain.label)} | "
            f"{_display_judgment(domain.judgment)} | "
            f"{_escape_markdown(domain.rationale)} |"
            for domain in assessment.domains
        )
        lines.extend(
            [
                "",
                f"Overall: **{_display_judgment(assessment.overall_judgment)}**",
                "",
                f"Status: **{'Signed off' if assessment.signed_off else 'Unsigned draft'}**",
                "",
            ]
        )
        lines.extend(["", "## Visual citations", ""])
        lines.extend(
            "- "
            f"{_escape_markdown(citation.label)} — "
            f"{_escape_markdown(citation.source_id)}, page {citation.page}, "
            f"region {_escape_markdown(str(citation.region))}"
            for citation in assessment.visual_citations
        )
        lines.append("")
        return "\n".join(lines).encode()

    def robvis_csv(self) -> bytes:
        stream = io.StringIO(newline="")
        fieldnames = [
            "Assessment",
            "Study",
            "Result",
            *(f"Domain {index}" for index in range(1, len(self.assessment.domains) + 1)),
            "Overall",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        row = {
            "Assessment": self.assessment.assessment_revision_id,
            "Study": _spreadsheet_cell(self.assessment.trial),
            "Result": self.assessment.result_id,
            "Overall": _display_judgment(self.assessment.overall_judgment),
        }
        row.update(
            {
                f"Domain {index}": _display_judgment(domain.judgment)
                for index, domain in enumerate(self.assessment.domains, start=1)
            }
        )
        writer.writerow(row)
        return b"\xef\xbb\xbf" + stream.getvalue().encode()

    def xlsx(self) -> bytes:
        workbook = Workbook()
        workbook.iso_dates = True
        workbook.properties.creator = "rob2-kit"
        workbook.properties.created = _FIXED_TIME.replace(tzinfo=None)
        workbook.properties.modified = _FIXED_TIME.replace(tzinfo=None)
        sheet = workbook.active
        sheet.title = "RoB 2"
        headings = [
            "Assessment",
            "Study",
            "Result",
            *(f"Domain {index}" for index in range(1, len(self.assessment.domains) + 1)),
            "Overall",
        ]
        sheet.append(headings)
        sheet.append(
            [
                self.assessment.assessment_revision_id,
                _spreadsheet_cell(self.assessment.trial),
                self.assessment.result_id,
                *(_display_judgment(domain.judgment) for domain in self.assessment.domains),
                _display_judgment(self.assessment.overall_judgment),
            ]
        )
        raw = io.BytesIO()
        workbook.save(raw)
        return _normalize_zip(raw.getvalue())

    def bundle_files(self) -> dict[str, bytes]:
        """Return every report-format projection from this exact Assessment view.

        The mapping is intentionally the sole format boundary used by report
        materializers.  This keeps HTML, machine-readable exports, and visual
        citation metadata tied to one immutable assessment identity.
        """

        return {
            "assessment.html": self.html(),
            "assessment.json": self.json(),
            "assessment.md": self.markdown(),
            "assessment.summary.json": self.summary(),
            "robvis.csv": self.robvis_csv(),
            "robvis.xlsx": self.xlsx(),
            "visual-citations.json": canonical_json_bytes(
                {
                    "assessment_revision_id": self.assessment.assessment_revision_id,
                    "visual_citations": [
                        citation.model_dump(mode="json")
                        for citation in self.assessment.visual_citations
                    ],
                }
            )
            + b"\n",
        }


def latest_assessment_view(ledger: WorkflowLedger) -> AssessmentView:
    """Resolve the current canonical Assessment revision through its exact references."""
    current = {revision.revision_id: revision for revision in ledger.current_revisions()}
    events = {event.revision_id: event for event in ledger.events() if event.revision_id in current}
    assessments: list[tuple[int, AssessmentRevision]] = []
    for revision_id, event in events.items():
        content = ledger.artifacts.read(current[revision_id].artifact_hash)
        try:
            assessment = AssessmentRevision.model_validate_json(content)
        except ValidationError:
            continue
        if assessment.revision_id == event.revision_id:
            assessments.append((event.sequence, assessment))
    if not assessments:
        raise ValueError("project has no current canonical Assessment revision")
    _, assessment = max(assessments, key=lambda item: item[0])
    result_spec = _load_reference(ledger, current, assessment.result_spec, ResultSpecRevision)
    judgments = tuple(
        _load_reference(ledger, current, reference, AlgorithmicJudgmentRevision)
        for reference in assessment.judgments
    )
    assessment_projection = current[assessment.revision_id]
    signed_off = any(
        _is_sign_off_for(
            ledger,
            current,
            revision_id,
            assessment,
            assessment_projection.artifact_hash,
        )
        for revision_id in current
    )
    result = result_spec.result
    overrides = _active_overrides(ledger, current, judgments, assessment.judgment_overrides)
    ordered = sorted(judgments, key=lambda judgment: judgment.domain_id)
    effective = tuple(
        overrides.get(judgment.revision_id, judgment.judgment.value) for judgment in ordered
    )
    return AssessmentView(
        assessment_revision_id=assessment.revision_id,
        result_id=result.result_id,
        trial=result.trial_id,
        comparison=(
            f"{result.comparison.experimental_arm_id} vs {result.comparison.comparator_arm_id}"
        ),
        outcome=result.outcome_construct,
        time_point=result.time_point,
        effect_of_interest=result.effect_of_interest,
        overall_judgment=_overall_judgment(effective),
        domains=tuple(
            DomainView(
                domain_id=judgment.domain_id,
                label=judgment.domain_id,
                judgment=overrides.get(judgment.revision_id, judgment.judgment.value),
                rationale=(f"Algorithmic judgment from {judgment.decision_trace.revision_id}."),
            )
            for judgment in ordered
        ),
        signed_off=signed_off,
    )


def _load_reference[ReportRevision: BaseModel](
    ledger: WorkflowLedger,
    current: dict[str, RevisionProjection],
    reference: RecordReference,
    model: type[ReportRevision],
) -> ReportRevision:
    projection = current.get(reference.revision_id)
    if projection is None:
        raise ValueError(f"current dependency {reference.revision_id} is unavailable")
    artifact_hash = projection.artifact_hash
    if artifact_hash != reference.content_hash:
        raise ValueError(f"dependency hash mismatch for {reference.revision_id}")
    return model.model_validate_json(ledger.artifacts.read(artifact_hash))


def _is_sign_off_for(
    ledger: WorkflowLedger,
    current: dict[str, RevisionProjection],
    revision_id: str,
    assessment: AssessmentRevision,
    assessment_hash: str,
) -> bool:
    projection = current[revision_id]
    try:
        sign_off = AssessmentSignOff.model_validate_json(
            ledger.artifacts.read(projection.artifact_hash)
        )
    except ValidationError:
        return False
    for candidate in current.values():
        try:
            withdrawal = SignOffWithdrawal.model_validate_json(
                ledger.artifacts.read(candidate.artifact_hash)
            )
        except ValidationError:
            continue
        if (
            withdrawal.sign_off.entity_id == sign_off.entity_id
            and withdrawal.sign_off.revision_id == sign_off.revision_id
            and withdrawal.sign_off.content_hash == projection.artifact_hash
        ):
            return False
    return (
        sign_off.assessment.entity_id == assessment.entity_id
        and sign_off.assessment.revision_id == assessment.revision_id
        and sign_off.assessment.content_hash == assessment_hash
    )


def _active_overrides(
    ledger: WorkflowLedger,
    current: dict[str, RevisionProjection],
    judgments: tuple[AlgorithmicJudgmentRevision, ...],
    references: tuple[RecordReference, ...],
) -> dict[str, str]:
    judgment_hashes = {
        judgment.revision_id: current[judgment.revision_id].artifact_hash for judgment in judgments
    }
    overrides: dict[str, str] = {}
    for override_reference in references:
        override = _load_reference(ledger, current, override_reference, JudgmentOverride)
        judgment_reference = override.judgment_revision
        if judgment_hashes.get(judgment_reference.revision_id) != judgment_reference.content_hash:
            continue
        overrides[judgment_reference.revision_id] = override.replacement.value
    return overrides


def _overall_judgment(judgments: tuple[str, ...]) -> str:
    if not judgments:
        raise ValueError("Assessment has no algorithmic judgments")
    rank = {"low": 0, "some_concerns": 1, "high": 2}
    return max(judgments, key=rank.__getitem__)


def _escape_markdown(value: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value).replace("\r", " ").replace("\n", " ")


def _display_judgment(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _spreadsheet_cell(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def _normalize_zip(content: bytes) -> bytes:
    with ZipFile(io.BytesIO(content)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    return write_deterministic_zip(members, transform=_normalize_xlsx_member)


def _normalize_xlsx_member(name: str, content: bytes) -> bytes:
    if name != "docProps/core.xml":
        return content
    return re.sub(
        rb"<dcterms:modified[^>]*>.*?</dcterms:modified>",
        (b'<dcterms:modified xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:modified>'),
        content,
    )
