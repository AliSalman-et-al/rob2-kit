"""Deterministic, read-only projections of a canonical Assessment revision."""

# ruff: noqa: E501

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
    questions: tuple[SignalingQuestionView, ...] = ()
    coverage: str = "not recorded"
    limitations: tuple[str, ...] = ()
    decision_trace: tuple[Identifier, ...] = ()


class VisualCitationView(ReportModel):
    citation_id: Identifier
    source_id: Identifier
    page: int = Field(ge=1)
    region: tuple[float, float, float, float]
    label: str = Field(min_length=1)
    exact_phrase: str | None = None
    render_provenance: str | None = None
    crop_path: str | None = None
    context_path: str | None = None


class EvidenceView(ReportModel):
    """Presentation-safe evidence with its attributable audit role."""

    evidence_id: Identifier
    disposition: str = Field(pattern=r"^(supporting|contradicting|contextual|residual)$")
    exact_phrase: str = Field(min_length=1)
    source_id: Identifier
    page: int = Field(ge=1)
    provenance: str = Field(min_length=1)
    visual_citation: VisualCitationView | None = None


class SignalingQuestionView(ReportModel):
    question_id: Identifier
    answer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: tuple[EvidenceView, ...] = ()
    coverage: str = "not recorded"
    limitations: tuple[str, ...] = ()
    no_information_basis: bool = False
    decision_trace: tuple[Identifier, ...] = ()


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
    execution_contract: str = "not recorded"


class RunIndexResultView(ReportModel):
    trial_id: Identifier
    result_id: Identifier
    state: str = Field(pattern=r"^(pending|assessing|report_ready|diagnostic_ready)$")
    report: str = ""
    overall_judgment: str | None = Field(default=None, pattern=r"^(low|some_concerns|high)$")
    domain_judgments: dict[Identifier, str] = Field(default_factory=dict)
    coverage: str = "not recorded"
    limitations: tuple[str, ...] = ()


class RunIndexView(ReportModel):
    run_id: Identifier
    execution_contract: str = "not recorded"
    results: tuple[RunIndexResultView, ...] = ()
    ancillary_outputs: tuple[str, ...] = ()


class DiagnosticView(ReportModel):
    result_id: Identifier
    trial_id: Identifier
    reason: str = Field(min_length=1)
    limitations: tuple[str, ...] = ()


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
        }
        return canonical_json_bytes(value) + b"\n"

    def html(self) -> bytes:
        assessment = self.assessment
        domain_navigation = "".join(
            f'<li><a href="#{_anchor(domain.domain_id)}">{html.escape(domain.label)}</a></li>'
            for domain in assessment.domains
        )
        domains = "".join(_render_domain(domain) for domain in assessment.domains)
        visual_citations = (
            "".join(_render_visual_citation(citation) for citation in assessment.visual_citations)
            or "<p>No visual citations were required for this Assessment.</p>"
        )
        body = (
            "<main>"
            '<header class="report-header"><p class="eyebrow">Static audit ledger</p>'
            "<h1>RoB 2 Result report</h1>"
            f"<p><strong>{_PREVIEW_LABEL}</strong>: read-only static evidence report.</p></header>"
            '<section aria-labelledby="identity-heading"><h2 id="identity-heading">'
            'Result identity</h2><dl class="identity-grid">'
            f"<div><dt>Assessment revision</dt><dd>{html.escape(assessment.assessment_revision_id)}</dd></div>"
            f"<div><dt>Result</dt><dd>{html.escape(assessment.result_id)}</dd></div>"
            f"<div><dt>Trial</dt><dd>{html.escape(assessment.trial)}</dd></div>"
            f"<div><dt>Comparison</dt><dd>{html.escape(assessment.comparison)}</dd></div>"
            f"<div><dt>Outcome and time point</dt><dd>{html.escape(assessment.outcome)}; {html.escape(assessment.time_point)}</dd></div>"
            f"<div><dt>Effect of interest</dt><dd>{html.escape(assessment.effect_of_interest)}</dd></div>"
            f"<div><dt>Execution contract</dt><dd><code>{html.escape(assessment.execution_contract)}</code></dd></div>"
            "</dl></section>"
            '<section class="audit-summary" aria-labelledby="summary-heading">'
            '<h2 id="summary-heading">Audit summary</h2>'
            f"{_judgment_badge(assessment.overall_judgment, label='Overall judgment')}"
            "</section>"
            '<nav aria-label="RoB 2 domains"><h2>Domain navigation</h2>'
            f"<ol>{domain_navigation}</ol></nav>"
            f'<section aria-label="Five ordered RoB 2 domains">{domains}</section>'
            '<section aria-labelledby="visual-heading"><h2 id="visual-heading">Visual citations</h2>'
            f"{visual_citations}</section></main>"
        )
        return _html_document("RoB 2 Result report", body).encode()

    def markdown(self) -> bytes:
        assessment = self.assessment
        lines = [
            "# RoB 2 assessment report",
            "",
            f"**{_PREVIEW_LABEL}** — read-only static evidence report.",
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
        for domain in assessment.domains:
            lines.extend(["", f"## {_escape_markdown(domain.label)}", ""])
            lines.append(f"Coverage: {_escape_markdown(domain.coverage)}")
            lines.extend(f"- Limitation: {_escape_markdown(item)}" for item in domain.limitations)
            for question in domain.questions:
                lines.extend(
                    [
                        "",
                        f"### Signaling question {_escape_markdown(question.question_id)}",
                        "",
                        f"Answer: {_escape_markdown(_display_answer(question.answer))}",
                        "",
                        f"AI rationale: {_escape_markdown(question.rationale)}",
                        "",
                        f"Coverage: {_escape_markdown(question.coverage)}",
                    ]
                )
                if question.no_information_basis:
                    lines.append("No-information basis: completed searchable-source coverage.")
                lines.extend(
                    f"- Limitation: {_escape_markdown(item)}" for item in question.limitations
                )
                for evidence in question.evidence:
                    lines.extend(
                        [
                            "",
                            f"- {_escape_markdown(evidence.disposition.title())} evidence: "
                            f"{_escape_markdown(evidence.exact_phrase)}",
                            f"  Source: {_escape_markdown(evidence.source_id)}, page {evidence.page}; "
                            f"{_escape_markdown(evidence.provenance)}",
                        ]
                    )
        lines.extend(
            [
                "",
                f"Overall: **{_display_judgment(assessment.overall_judgment)}**",
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
                        citation.model_dump(mode="json", exclude_none=True)
                        for citation in self.assessment.visual_citations
                    ],
                }
            )
            + b"\n",
        }


class RunIndexProjector:
    """Render the static, ledger-derived entry point for a completed Run."""

    def __init__(self, run: RunIndexView) -> None:
        self.run = run

    def json(self) -> bytes:
        return canonical_json_bytes(self.run.model_dump(mode="json")) + b"\n"

    def html(self) -> bytes:
        run = self.run
        counts = Counter(item.state for item in run.results)
        rows = (
            "".join(
                "<tr>"
                f"<td>{html.escape(item.trial_id)}</td>"
                f"<td>{html.escape(item.result_id)}</td>"
                f"<td>{html.escape(item.state.replace('_', ' '))}</td>"
                f"<td>{_judgment_badge(item.overall_judgment, label='Text-labelled traffic-light judgment') if item.overall_judgment else '<span class="no-judgment">No valid judgment</span>'}</td>"
                f"<td>{html.escape(item.coverage.replace('_', ' '))}<br>"
                f"<small>{html.escape(_domain_judgments(item.domain_judgments))}</small></td>"
                f"<td>{_limitations(item.limitations)}</td>"
                f"<td>{f'<a href="{_local_href(item.report)}">Open report</a>' if item.report else 'No report yet'}</td>"
                "</tr>"
                for item in run.results
            )
            or '<tr><td colspan="7">No terminal Result outcomes are available.</td></tr>'
        )
        outputs = "".join(f"<li>{html.escape(item)}</li>" for item in run.ancillary_outputs)
        body = (
            '<main><header class="report-header"><p class="eyebrow">Static audit ledger</p>'
            "<h1>RoB 2 Run index</h1></header>"
            '<section aria-labelledby="run-identity-heading"><h2 id="run-identity-heading">Run identity</h2>'
            '<dl class="identity-grid">'
            f"<div><dt>Run</dt><dd>{html.escape(run.run_id)}</dd></div>"
            f"<div><dt>Execution contract</dt><dd><code>{html.escape(run.execution_contract)}</code></dd></div>"
            "</dl></section>"
            '<section aria-labelledby="terminal-heading"><h2 id="terminal-heading">Terminal outcomes</h2>'
            f"<p>{counts['report_ready']} report ready; {counts['diagnostic_ready']} diagnostic ready.</p>"
            '<div class="table-wrap"><table><thead><tr><th>Trial</th><th>Result</th><th>Outcome</th>'
            "<th>Judgment</th><th>Coverage</th><th>Limitations</th><th>Report</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
            '<section aria-labelledby="outputs-heading"><h2 id="outputs-heading">Ancillary outputs</h2>'
            f"<ul>{outputs or '<li>No ancillary outputs recorded.</li>'}</ul></section></main>"
        )
        return _html_document("RoB 2 Run index", body).encode()


class DiagnosticReportProjector:
    """Render a scoped terminal blocker without inventing a judgment."""

    def __init__(self, diagnostic: DiagnosticView) -> None:
        self.diagnostic = diagnostic

    def json(self) -> bytes:
        return canonical_json_bytes(self.diagnostic.model_dump(mode="json")) + b"\n"

    def html(self) -> bytes:
        diagnostic = self.diagnostic
        body = (
            '<main><header class="report-header"><p class="eyebrow">Scoped diagnostic</p>'
            "<h1>RoB 2 diagnostic report</h1></header>"
            '<section aria-labelledby="diagnostic-identity"><h2 id="diagnostic-identity">'
            'Result identity</h2><dl class="identity-grid">'
            f"<div><dt>Result</dt><dd>{html.escape(diagnostic.result_id)}</dd></div>"
            f"<div><dt>Trial</dt><dd>{html.escape(diagnostic.trial_id)}</dd></div>"
            '</dl></section><section class="diagnostic" aria-labelledby="blocker-heading">'
            '<h2 id="blocker-heading">Scoped blocker</h2>'
            f"<p>{html.escape(diagnostic.reason)}</p>"
            "<p><strong>No valid judgment is available</strong> while this blocker remains. "
            "The report intentionally omits judgments rather than using a placeholder or guess.</p>"
            f"<h3>Limitations</h3>{_limitations(diagnostic.limitations)}</section></main>"
        )
        return _html_document("RoB 2 diagnostic report", body).encode()


def _render_domain(domain: DomainView) -> str:
    questions = "".join(_render_question(question) for question in domain.questions)
    if not questions:
        questions = "<p>No signaling-question projection was recorded for this domain.</p>"
    return (
        f'<article class="domain" id="{_anchor(domain.domain_id)}">'
        f"<h2>{html.escape(domain.label)}</h2>"
        f"{_judgment_badge(domain.judgment, label='Domain judgment')}"
        f"<p><strong>Coverage:</strong> {html.escape(domain.coverage.replace('_', ' '))}</p>"
        f"{_limitations(domain.limitations)}"
        "<details><summary>Deterministic domain basis and Decision trace</summary>"
        f"<p>{html.escape(domain.rationale)}</p>{_trace(domain.decision_trace)}</details>"
        f'<section class="questions" aria-label="Signaling questions for {html.escape(domain.label)}">'
        f"{questions}</section></article>"
    )


def _render_question(question: SignalingQuestionView) -> str:
    evidence = "".join(_render_evidence(item) for item in question.evidence)
    if not evidence:
        evidence = "<p>No accepted Evidence claims were recorded for this signaling question.</p>"
    no_information = (
        "<p><strong>No-information basis:</strong> completed searchable-source coverage.</p>"
        if question.no_information_basis
        else ""
    )
    return (
        f'<article class="question" id="{_anchor(question.question_id)}">'
        f"<h3>Signaling question {html.escape(question.question_id)}</h3>"
        f"<p><strong>Answer:</strong> {html.escape(_display_answer(question.answer))}</p>"
        f"<p><strong>Coverage:</strong> {html.escape(question.coverage.replace('_', ' '))}</p>"
        f"{no_information}{_limitations(question.limitations)}"
        "<details><summary>AI rationale</summary>"
        f"<p>{html.escape(question.rationale)}</p></details>"
        "<details><summary>Evidence, provenance, and Decision trace</summary>"
        f'<section class="evidence-list" aria-label="Evidence for {html.escape(question.question_id)}">'
        f"{evidence}</section>{_trace(question.decision_trace)}</details></article>"
    )


def _render_evidence(evidence: EvidenceView) -> str:
    label = {
        "supporting": "Supporting evidence",
        "contradicting": "Contradicting evidence",
        "contextual": "Contextual evidence",
        "residual": "Residual evidence",
    }[evidence.disposition]
    visual = _render_visual_citation(evidence.visual_citation) if evidence.visual_citation else ""
    return (
        f'<article class="evidence {html.escape(evidence.disposition)}">'
        f"<h4>{label}</h4><blockquote>{html.escape(evidence.exact_phrase)}</blockquote>"
        '<p class="provenance">'
        f"Source: {html.escape(evidence.source_id)}; page {evidence.page}; "
        f"provenance: {html.escape(evidence.provenance)}; claim: {html.escape(evidence.evidence_id)}."
        f"</p>{visual}</article>"
    )


def _render_visual_citation(citation: VisualCitationView) -> str:
    phrase = citation.exact_phrase or "Exact phrase is retained with the source claim."
    provenance = citation.render_provenance or "render provenance not recorded"
    region = ", ".join(f"{value:g}" for value in citation.region)
    assets = (
        f'<figure><img src="{_local_href(citation.crop_path)}" '
        f'alt="Highlighted local crop for {html.escape(citation.label)}">'
        f'<figcaption><a href="{_local_href(citation.context_path)}">Open local full-page context</a>. '
        "Agent inspection not performed.</figcaption></figure>"
        if citation.crop_path and citation.context_path
        else "<p>Local render assets were unavailable; this citation is retained as provenance only.</p>"
    )
    return (
        '<details class="visual-citation"><summary>Visual citation — agent inspection not performed</summary>'
        f"<p><strong>{html.escape(citation.label)}</strong></p>"
        f"<blockquote>{html.escape(phrase)}</blockquote>"
        f"{assets}"
        f'<p class="provenance">Source: {html.escape(citation.source_id)}; page {citation.page}; '
        f"region ({html.escape(region)}); {html.escape(provenance)}; citation: {html.escape(citation.citation_id)}.</p>"
        "</details>"
    )


def _judgment_badge(judgment: str | None, *, label: str) -> str:
    if judgment is None:
        return f'<span class="no-judgment">{html.escape(label)}: No valid judgment</span>'
    text = _display_judgment(judgment)
    return (
        f'<p class="judgment judgment-{html.escape(judgment)}"><span aria-hidden="true">o</span> '
        f"<strong>{html.escape(label)}: Text-labelled judgment: {html.escape(text)}</strong></p>"
    )


def _trace(items: tuple[Identifier, ...]) -> str:
    if not items:
        return "<p>Decision trace identifiers were not recorded.</p>"
    values = "".join(f"<li><code>{html.escape(item)}</code></li>" for item in items)
    return f"<h4>Decision trace</h4><ul>{values}</ul>"


def _limitations(items: tuple[str, ...]) -> str:
    if not items:
        return ""
    values = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    return f'<section class="limitations"><h4>Limitations</h4><ul>{values}</ul></section>'


def _anchor(value: str) -> str:
    return "domain-" + re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _local_href(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value) or ".." in value.split("/"):
        return "#invalid-local-report-link"
    return html.escape(value, quote=True)


def _display_answer(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _domain_judgments(values: dict[Identifier, str]) -> str:
    if not values:
        return "Domain judgments: not available"
    rendered = "; ".join(
        f"{domain}: {_display_judgment(judgment)}" for domain, judgment in sorted(values.items())
    )
    return f"Domain judgments: {rendered}"


def _html_document(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_AUDIT_CSS}</style></head><body>{body}</body></html>\n"
    )


_AUDIT_CSS = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #17322d; background: #f7f4ed; }
body { margin: 0; line-height: 1.5; } main { max-width: 70rem; margin: auto; padding: 1rem; }
h1, h2 { font-family: Georgia, serif; } .report-header, .audit-summary, .domain, .question, .diagnostic { border: 1px solid #c9c5ba; border-radius: .5rem; background: #fffdf8; padding: 1rem; margin: 1rem 0; }
.identity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: .75rem; } .identity-grid div { border-left: .25rem solid #40645a; padding-left: .5rem; } dt { font-weight: 700; } dd { margin: 0; overflow-wrap: anywhere; }
.judgment { display: inline-block; padding: .25rem .5rem; border-radius: .25rem; } .judgment-low { background: #dcefe3; } .judgment-some_concerns { background: #fff0c9; } .judgment-high { background: #f9ddd8; } .no-judgment { font-weight: 700; }
nav ol { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; padding-left: 1.25rem; } .questions { margin-top: 1rem; } .evidence { border-left: .3rem solid #40645a; padding: .5rem 1rem; margin: .75rem 0; background: #f7f4ed; } .evidence.contradicting { border-color: #9c3226; } .evidence.contextual, .evidence.residual { border-color: #9a5a12; }
blockquote { margin-left: 0; padding-left: .75rem; border-left: .2rem solid #777; } .provenance, figcaption { font-size: .9rem; overflow-wrap: anywhere; } .table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; } th, td { padding: .5rem; text-align: left; vertical-align: top; border-bottom: 1px solid #c9c5ba; } th { background: #e4ede8; }
a { color: #064c87; } a:focus-visible, summary:focus-visible { outline: .2rem solid #9a5a12; outline-offset: .2rem; } summary { cursor: pointer; font-weight: 700; } svg { display: block; max-width: 22rem; width: 100%; height: auto; }
@media (max-width: 20rem) { main { padding: .5rem; } nav ol { display: block; } nav li { margin: .5rem 0; } .identity-grid { grid-template-columns: 1fr; } }
@media print { body { background: #fff; color: #000; } main { max-width: none; } details { display: block; } details > * { display: block !important; } .report-header, .audit-summary, .domain, .question, .diagnostic { break-inside: avoid; box-shadow: none; } a { color: inherit; text-decoration: none; } }
"""


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
    result = result_spec.result
    ordered = sorted(judgments, key=lambda judgment: judgment.domain_id)
    effective = tuple(judgment.judgment.value for judgment in ordered)
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
                judgment=judgment.judgment.value,
                rationale=(f"Algorithmic judgment from {judgment.decision_trace.revision_id}."),
            )
            for judgment in ordered
        ),
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
