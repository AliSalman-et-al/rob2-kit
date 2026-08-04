"""Deterministic, read-only projections of a canonical Assessment revision."""

# ruff: noqa: E501

from __future__ import annotations

import csv
import html
import io
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    DecisionTrace,
    SQAnswerRevision,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes, sha256_digest
from rob2_kit.domain.evidence import (
    EvidenceBundle,
    EvidenceClaim,
    EvidenceConsiderationManifest,
    VisualTranscription,
)
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import ContentHash, Identifier, RecordReference
from rob2_kit.evidence.search import CanonicalEvidenceUnit
from rob2_kit.evidence.visual import build_visual_citation
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import LogicPack, load_guidance_pack, load_logic_pack
from rob2_kit.reports._deterministic_zip import write_deterministic_zip
from rob2_kit.storage.ledger import RevisionProjection, WorkflowLedger

_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
_MARKDOWN_SPECIAL = re.compile(r"([\\`*{}[\]()#+.!_|<>~-])")
_PREVIEW_LABEL = "DRAFT-ONLY HANDS-ON PREVIEW"


class ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EstimateView(ReportModel):
    """The reported numerical result, kept separate from the Result identity."""

    value: str = Field(min_length=1)
    interval_lower: str | None = None
    interval_upper: str | None = None
    denominator_experimental: int | None = Field(default=None, ge=0)
    denominator_comparator: int | None = Field(default=None, ge=0)

    @field_validator("value", "interval_lower", "interval_upper", mode="before")
    @classmethod
    def _stringify_decimal(cls, value: object) -> object:
        return str(value) if value is not None else value

    @property
    def interval(self) -> str | None:
        if self.interval_lower is None or self.interval_upper is None:
            return None
        return f"{self.interval_lower}–{self.interval_upper}"


class ResultIdentityView(ReportModel):
    """Compact, stable identity of the Result under assessment."""

    result_id: Identifier
    trial_id: Identifier
    comparison: str = Field(min_length=1)
    effect_of_interest: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    measurement_instrument: str = ""
    time_point: str = Field(min_length=1)
    analysis_population: str = ""
    analysis_model: str = ""
    effect_measure: str = ""
    source_locator: str = ""


class ResultDetailsView(ReportModel):
    """Revision-specific details kept outside the stable Result identity.

    A Result's identity deliberately excludes the extracted numerical value.
    The estimate and its denominators belong to the resolved ResultSpec
    revision and are therefore carried by this separate details seam.
    """

    measurement_instrument: str = ""
    analysis_population: str = ""
    analysis_model: str = ""
    effect_measure: str = ""
    source_locator: str = ""
    estimate: EstimateView | None = None


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
    boxes: tuple[tuple[float, float, float, float], ...] | None = None
    label: str = Field(min_length=1)
    exact_phrase: str | None = None
    render_provenance: str | None = None
    crop_path: str | None = None
    context_path: str | None = None
    # Structured provenance.  These fields intentionally remain separate from
    # ``render_provenance`` so an archive verifier can check identity without
    # parsing display text.
    canonical_unit_id: Identifier | None = None
    source_artifact_hash: ContentHash | None = None
    parse_id: Identifier | None = None
    span_start: int | None = Field(default=None, ge=0)
    span_end: int | None = Field(default=None, gt=0)
    quoted_text_hash: ContentHash | None = None
    geometry_scope: Literal["phrase_exact", "block", "visual_region"] | None = None
    geometry_hash: ContentHash | None = None
    render_hash: ContentHash | None = None
    render_mode: Literal["crop", "full_page"] | None = None
    dpi: Literal[144, 180, 216] | None = None
    base_render_hash: ContentHash | None = None
    derived_render_hash: ContentHash | None = None
    overlay_hash: ContentHash | None = None
    crop_hash: ContentHash | None = None
    context_hash: ContentHash | None = None
    agent_inspected: bool | None = None
    inspection_status: Literal["automatic_spatial_claim", "visual_only_transcription"] | None = None

    @model_validator(mode="after")
    def validate_structured_identity(self) -> VisualCitationView:
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError("visual citation span_start and span_end must be supplied together")
        if self.span_start is not None and self.span_end is not None and self.span_end <= self.span_start:
            raise ValueError("visual citation span_end must be greater than span_start")
        if (
            self.quoted_text_hash is not None
            and self.span_start is None
            and self.geometry_scope != "visual_region"
        ):
            raise ValueError("quoted_text_hash requires canonical span coordinates")
        if self.geometry_scope == "phrase_exact" and self.geometry_hash is None:
            raise ValueError("phrase-exact geometry requires a geometry hash")
        if self.inspection_status == "visual_only_transcription" and self.agent_inspected is not True:
            raise ValueError("visual transcriptions must be marked agent_inspected")
        if self.inspection_status == "automatic_spatial_claim" and self.agent_inspected is True:
            raise ValueError("automatic spatial claims cannot be marked agent_inspected")
        return self


class EvidenceView(ReportModel):
    """Presentation-safe evidence with its attributable audit role."""

    evidence_id: Identifier
    disposition: str = Field(pattern=r"^(supporting|contradicting|contextual|residual)$")
    exact_phrase: str = Field(min_length=1)
    source_id: Identifier
    page: int = Field(ge=1)
    provenance: str = Field(min_length=1)
    # Canonical evidence keeps authored structure rather than flattening every
    # hit into an opaque snippet.  These fields are optional for legacy report
    # projections, but terminal reports populate them from the canonical unit.
    unit_kind: Literal[
        "heading", "paragraph", "list_item", "caption", "footnote", "table_row"
    ] = "paragraph"
    context: str = ""
    table_headers: tuple[str, ...] = ()
    visual_citation: VisualCitationView | None = None


class SignalingQuestionView(ReportModel):
    question_id: Identifier
    # `wording` is copied from the immutable Guidance pack.  It is optional
    # for legacy projections, but a terminal Run always supplies it.
    wording: str = ""
    answer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: tuple[EvidenceView, ...] = ()
    coverage: str = "not recorded"
    limitations: tuple[str, ...] = ()
    no_information_basis: bool = False
    decision_trace: tuple[Identifier, ...] = ()
    # Material source conflicts and residual uncertainty are retained rather
    # than collapsed into a generic rationale or silently discarded.
    conflicts: tuple[tuple[Identifier, ...], ...] = ()
    uncertainty: tuple[str, ...] = ()


class AssessmentView(ReportModel):
    """Resolved, presentation-safe view of one immutable Assessment revision."""

    assessment_revision_id: Identifier
    result_id: Identifier
    trial: str = Field(min_length=1)
    comparison: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    time_point: str = Field(min_length=1)
    effect_of_interest: str = Field(min_length=1)
    measurement_instrument: str = ""
    analysis_population: str = ""
    analysis_model: str = ""
    effect_measure: str = ""
    source_locator: str = ""
    estimate: EstimateView | None = None
    limitations: tuple[str, ...] = ()
    result_identity: ResultIdentityView | None = None
    result_details: ResultDetailsView | None = None
    overall_judgment: str = Field(pattern=r"^(low|some_concerns|high)$")
    domains: tuple[DomainView, ...] = Field(min_length=1)
    visual_citations: tuple[VisualCitationView, ...] = ()
    execution_contract: str = "not recorded"
    overall_policy_id: Identifier | None = None
    overall_policy_hash: str | None = None
    overall_policy_text: str = ""
    overall_decision_trace: tuple[Identifier, ...] = ()


class RunIndexResultView(ReportModel):
    trial_id: Identifier
    result_id: Identifier
    state: str = Field(pattern=r"^(pending|assessing|report_ready|diagnostic_ready)$")
    report: str = ""
    outcome: str = ""
    time_point: str = ""
    comparison: str = ""
    effect_measure: str = ""
    estimate: EstimateView | None = None
    evidence_count: int = Field(default=0, ge=0)
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
        return canonical_json_bytes(_assessment_payload(self.assessment)) + b"\n"

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
        if _has_extended_identity(self.assessment):
            value.update(
                {
                    "effect_measure": self.assessment.effect_measure or "not recorded",
                    "estimate": _estimate_text(self.assessment.estimate),
                    "effect_of_interest": self.assessment.effect_of_interest,
                    "outcome": self.assessment.outcome,
                    "measurement_instrument": self.assessment.measurement_instrument or "not recorded",
                    "time_point": self.assessment.time_point,
                    "analysis_population": self.assessment.analysis_population or "not recorded",
                    "analysis_model": self.assessment.analysis_model or "not recorded",
                    "source_locator": self.assessment.source_locator or "not recorded",
                    "denominator_experimental": (
                        self.assessment.estimate.denominator_experimental
                        if self.assessment.estimate
                        else None
                    ),
                    "denominator_comparator": (
                        self.assessment.estimate.denominator_comparator
                        if self.assessment.estimate
                        else None
                    ),
                    "evidence_count": _evidence_count(self.assessment),
                }
            )
        if self.assessment.limitations:
            value["limitations"] = self.assessment.limitations
        return canonical_json_bytes(value) + b"\n"

    def html(self) -> bytes:
        assessment = self.assessment
        # Keep the v0 projection byte-stable for callers that only supplied
        # the original compact AssessmentView fields. Extended terminal
        # reports take the evidence-first layout below.
        if not _has_extended_identity(assessment) and not any(
            question.wording
            for domain in assessment.domains
            for question in domain.questions
        ):
            return self._legacy_html()
        ordered_domains = _ordered_domains(assessment.domains)
        domain_navigation = "".join(
            f'<li><a href="#{_anchor(domain.domain_id)}"><span class="domain-number">{index}</span>'
            f'<span>{html.escape(domain.label)}</span>{_judgment_badge(domain.judgment, label="")}</a></li>'
            for index, domain in enumerate(ordered_domains, start=1)
        )
        domains = "".join(_render_domain(domain) for domain in ordered_domains)
        visual_citations = (
            "".join(_render_visual_citation(citation) for citation in assessment.visual_citations)
            or "<p>No visual citations were required for this Assessment.</p>"
        )
        body = (
            "<main>"
            '<header class="report-header"><p class="eyebrow">Static audit ledger</p>'
            "<h1>RoB 2 Result report</h1>"
            f"<p><strong>{_PREVIEW_LABEL}</strong>: read-only static evidence report.</p></header>"
            '<section class="result-hero" aria-labelledby="identity-heading"><div>'
            '<p class="eyebrow">Result under assessment</p><h2 id="identity-heading">'
            'Result identity</h2><dl class="identity-grid">'
            f"<div><dt>Assessment revision</dt><dd>{html.escape(assessment.assessment_revision_id)}</dd></div>"
            f"<div><dt>Result</dt><dd>{html.escape(assessment.result_id)}</dd></div>"
            f"<div><dt>Trial</dt><dd>{html.escape(assessment.trial)}</dd></div>"
            f"<div><dt>Comparison</dt><dd>{html.escape(assessment.comparison)}</dd></div>"
            f"<div><dt>Outcome and time point</dt><dd>{html.escape(assessment.outcome)}; {html.escape(assessment.time_point)}</dd></div>"
            f"<div><dt>Effect of interest</dt><dd>{html.escape(assessment.effect_of_interest)}</dd></div>"
            f"{_optional_identity_cells(assessment)}"
            f"<div><dt>Execution contract</dt><dd><code>{html.escape(assessment.execution_contract)}</code></dd></div>"
            "</dl></div>"
            f"{_estimate_card(assessment)}"
            "</section>"
            '<section class="audit-summary" aria-labelledby="summary-heading">'
            '<h2 id="summary-heading">Audit summary</h2>'
            f"{_judgment_badge(assessment.overall_judgment, label='Overall judgment')}"
            f"<span class=\"summary-count\">{_evidence_count(assessment)} accepted evidence claims</span>"
            "</section>"
            f"{_limitations(assessment.limitations)}"
            f"{_render_overall_policy(assessment)}"
            '<div class="report-layout"><nav class="domain-rail" aria-label="RoB 2 domains"><h2>Domain navigation</h2>'
            f"<ol>{domain_navigation}</ol></nav>"
            f'<section class="domain-stack" aria-label="Five ordered RoB 2 domains">{domains}</section></div>'
            '<section aria-labelledby="visual-heading"><h2 id="visual-heading">Visual citations</h2>'
            f"{visual_citations}</section></main>"
        )
        return _html_document("RoB 2 Result report", body).encode()

    def _legacy_html(self) -> bytes:
        assessment = self.assessment
        ordered_domains = _ordered_domains(assessment.domains)
        domain_navigation = "".join(
            f'<li><a href="#{_anchor(domain.domain_id)}">{html.escape(domain.label)}</a></li>'
            for domain in ordered_domains
        )
        domains = "".join(_render_domain(domain) for domain in ordered_domains)
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
            f"{_limitations(assessment.limitations)}"
            '<nav aria-label="RoB 2 domains"><h2>Domain navigation</h2>'
            f"<ol>{domain_navigation}</ol></nav>"
            f'<section aria-label="Five ordered RoB 2 domains">{domains}</section>'
            '<section aria-labelledby="visual-heading"><h2 id="visual-heading">Visual citations</h2>'
            f"{visual_citations}</section></main>"
        )
        return _html_document(
            "RoB 2 Result report", body, css=_LEGACY_AUDIT_CSS, include_csp=False
        ).encode()

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
            *(
                [
                    f"- Effect of interest: {_escape_markdown(assessment.effect_of_interest)}",
                    f"- Measurement instrument: {_escape_markdown(assessment.measurement_instrument or 'not recorded')}",
                    f"- Analysis population: {_escape_markdown(assessment.analysis_population or 'not recorded')}",
                    f"- Analysis model: {_escape_markdown(assessment.analysis_model or 'not recorded')}",
                    f"- Effect measure: {_escape_markdown(assessment.effect_measure or 'not recorded')}",
                    f"- Value: {_escape_markdown(assessment.estimate.value if assessment.estimate else 'not recorded')}",
                    f"- 95% CI: {_escape_markdown(assessment.estimate.interval if assessment.estimate and assessment.estimate.interval else 'not recorded')}",
                    f"- Denominator experimental: {_escape_markdown(str(assessment.estimate.denominator_experimental) if assessment.estimate and assessment.estimate.denominator_experimental is not None else 'not recorded')}",
                    f"- Denominator comparator: {_escape_markdown(str(assessment.estimate.denominator_comparator) if assessment.estimate and assessment.estimate.denominator_comparator is not None else 'not recorded')}",
                    f"- Source locator: {_escape_markdown(assessment.source_locator or 'not recorded')}",
                ]
                if _has_extended_identity(assessment)
                else []
            ),
            *(
                [
                    "",
                    "## Limitations",
                    "",
                    *(f"- {_escape_markdown(item)}" for item in assessment.limitations),
                ]
                if assessment.limitations
                else []
            ),
            "",
            "| Domain | Judgment | Rationale |",
            "|---|---|---|",
        ]
        lines.extend(
            f"| {_escape_markdown(_domain_code(domain.domain_id) + ': ' if _domain_code(domain.domain_id) else '')}{_escape_markdown(domain.label)} | "
            f"{_display_judgment(domain.judgment)} | "
            f"{_escape_markdown(domain.rationale)} |"
            for domain in _ordered_domains(assessment.domains)
        )
        if assessment.overall_policy_id or assessment.overall_policy_hash or assessment.overall_decision_trace:
            lines.extend(
                [
                    "",
                    "## Overall maximum-domain policy",
                    "",
                    f"Policy: {_escape_markdown(assessment.overall_policy_text or 'Low when all domains are Low; High when any domain is High; otherwise Some concerns.')}",
                    f"Policy id: {_escape_markdown(assessment.overall_policy_id or 'not recorded')}",
                    f"Policy hash: {_escape_markdown(assessment.overall_policy_hash or 'not recorded')}",
                    f"Decision trace: {_escape_markdown(', '.join(assessment.overall_decision_trace) or 'not recorded')}",
                ]
            )
        lines.extend(
            [
                "",
                f"Evidence claims: {_evidence_count(assessment)}",
                f"Result identity: {_escape_markdown(_result_identity_text(assessment))}",
            ]
            if assessment.effect_measure or assessment.estimate or any(
                question.wording
                for domain in assessment.domains
                for question in domain.questions
            )
            else []
        )
        if assessment.effect_measure or assessment.estimate:
            insertion = [
                f"- Effect measure: {_escape_markdown(assessment.effect_measure or 'not recorded')}",
                f"- Estimate: {_escape_markdown(_estimate_text(assessment.estimate)).replace(r'\.', '.')}",
            ]
            lines[6:6] = insertion
        for domain in _ordered_domains(assessment.domains):
            prefix = f"{_domain_code(domain.domain_id)}: " if _domain_code(domain.domain_id) else ""
            lines.extend(["", f"## {_escape_markdown(prefix + domain.label)}", ""])
            lines.append(f"Coverage: {_escape_markdown(domain.coverage)}")
            lines.extend(f"- Limitation: {_escape_markdown(item)}" for item in domain.limitations)
            for question in domain.questions:
                lines.extend(
                    [
                        "",
                        f"### Signaling question {_escape_markdown(question.question_id)}",
                        "",
                        *(
                            [f"Question: {_escape_markdown(question.wording)}", ""]
                            if question.wording
                            else []
                        ),
                        f"Answer: {_escape_markdown(_display_answer(question.answer))}",
                        "",
                        f"AI rationale: {_escape_markdown(question.rationale)}",
                        "",
                        f"Coverage: {_escape_markdown(question.coverage)}",
                    ]
                )
                if question.no_information_basis:
                    lines.append("No-information basis: completed searchable-source coverage.")
                if question.conflicts:
                    lines.append(
                        "Conflicts: "
                        + "; ".join(", ".join(group) for group in question.conflicts)
                    )
                lines.extend(f"- Uncertainty: {_escape_markdown(item)}" for item in question.uncertainty)
                lines.extend(
                    f"- Limitation: {_escape_markdown(item)}" for item in question.limitations
                )
                for evidence in question.evidence:
                    kind = _EVIDENCE_KIND_LABELS[evidence.unit_kind]
                    lines.extend(
                        [
                            "",
                            f"- {_escape_markdown(evidence.disposition.title())} evidence: "
                            f"{_escape_markdown(evidence.exact_phrase)}",
                            f"  Unit: {_escape_markdown(kind)}",
                            *(
                                [
                                    "  Table headers: "
                                    + _escape_markdown("; ".join(evidence.table_headers))
                                ]
                                if evidence.table_headers
                                else []
                            ),
                            f"  Source: {_escape_markdown(evidence.source_id)}, page {evidence.page}; "
                            f"{_escape_markdown(evidence.provenance)}",
                            *(
                                [f"  Context: {_escape_markdown(evidence.context)}"]
                                if evidence.context
                                else []
                            ),
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
        extended = _has_extended_identity(self.assessment)
        fieldnames = [
            "Assessment",
            "Study",
            "Result",
            *(
                (
                    "Effect of interest",
                    "Outcome",
                    "Measurement instrument",
                    "Time point",
                    "Analysis population",
                    "Analysis model",
                    "Effect measure",
                    "Estimate",
                    "95% CI",
                    "Denominator experimental",
                    "Denominator comparator",
                    "Source locator",
                    "Evidence claims",
                )
                if extended
                else ()
            ),
            *(
                (f"D{index}" if extended else f"Domain {index}")
                for index in range(1, len(self.assessment.domains) + 1)
            ),
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
        if extended:
            row.update(
                {
                    "Effect of interest": _spreadsheet_cell(self.assessment.effect_of_interest),
                    "Outcome": _spreadsheet_cell(self.assessment.outcome),
                    "Measurement instrument": _spreadsheet_cell(self.assessment.measurement_instrument or "not recorded"),
                    "Time point": _spreadsheet_cell(self.assessment.time_point),
                    "Analysis population": _spreadsheet_cell(self.assessment.analysis_population or "not recorded"),
                    "Analysis model": _spreadsheet_cell(self.assessment.analysis_model or "not recorded"),
                    "Effect measure": _spreadsheet_cell(self.assessment.effect_measure or "not recorded"),
                    "Estimate": _spreadsheet_cell(self.assessment.estimate.value if self.assessment.estimate else "not recorded"),
                    "95% CI": _spreadsheet_cell(
                        self.assessment.estimate.interval if self.assessment.estimate and self.assessment.estimate.interval else "not recorded"
                    ),
                    "Denominator experimental": _spreadsheet_cell(
                        str(self.assessment.estimate.denominator_experimental)
                        if self.assessment.estimate and self.assessment.estimate.denominator_experimental is not None
                        else "not recorded"
                    ),
                    "Denominator comparator": _spreadsheet_cell(
                        str(self.assessment.estimate.denominator_comparator)
                        if self.assessment.estimate and self.assessment.estimate.denominator_comparator is not None
                        else "not recorded"
                    ),
                    "Source locator": _spreadsheet_cell(self.assessment.source_locator or "not recorded"),
                    "Evidence claims": str(_evidence_count(self.assessment)),
                }
            )
        row.update(
            {
                (f"D{index}" if extended else f"Domain {index}"): _display_judgment(domain.judgment)
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
        extended = _has_extended_identity(self.assessment)
        headings = [
            "Assessment",
            "Study",
            "Result",
            *(
                (
                    "Effect of interest",
                    "Outcome",
                    "Measurement instrument",
                    "Time point",
                    "Analysis population",
                    "Analysis model",
                    "Effect measure",
                    "Estimate",
                    "95% CI",
                    "Denominator experimental",
                    "Denominator comparator",
                    "Source locator",
                    "Evidence claims",
                )
                if extended
                else ()
            ),
            *(
                (f"D{index}" if extended else f"Domain {index}")
                for index in range(1, len(self.assessment.domains) + 1)
            ),
            "Overall",
        ]
        sheet.append(headings)
        sheet.append(
            [
                self.assessment.assessment_revision_id,
                _spreadsheet_cell(self.assessment.trial),
                self.assessment.result_id,
                *(
                    (
                        _spreadsheet_cell(self.assessment.effect_of_interest),
                        _spreadsheet_cell(self.assessment.outcome),
                        _spreadsheet_cell(self.assessment.measurement_instrument or "not recorded"),
                        _spreadsheet_cell(self.assessment.time_point),
                        _spreadsheet_cell(self.assessment.analysis_population or "not recorded"),
                        _spreadsheet_cell(self.assessment.analysis_model or "not recorded"),
                        _spreadsheet_cell(self.assessment.effect_measure or "not recorded"),
                        _spreadsheet_cell(self.assessment.estimate.value if self.assessment.estimate else "not recorded"),
                        _spreadsheet_cell(
                            self.assessment.estimate.interval
                            if self.assessment.estimate and self.assessment.estimate.interval
                            else "not recorded"
                        ),
                        _spreadsheet_cell(
                            str(self.assessment.estimate.denominator_experimental)
                            if self.assessment.estimate and self.assessment.estimate.denominator_experimental is not None
                            else "not recorded"
                        ),
                        _spreadsheet_cell(
                            str(self.assessment.estimate.denominator_comparator)
                            if self.assessment.estimate and self.assessment.estimate.denominator_comparator is not None
                            else "not recorded"
                        ),
                        _spreadsheet_cell(self.assessment.source_locator or "not recorded"),
                        str(_evidence_count(self.assessment)),
                    )
                    if extended
                    else ()
                ),
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
        observed_domain_ids = {domain_id for item in run.results for domain_id in item.domain_judgments}
        # Keep the official D1–D5 cells in every Run index, including scoped
        # diagnostic rows where no domain judgment exists.  Unknown extension
        # domains remain visible after the official columns.
        domain_ids = _DOMAIN_ORDER + tuple(sorted(observed_domain_ids - set(_DOMAIN_ORDER)))
        traffic_headers = "".join(
            f'<th scope="col">{html.escape(_domain_code(domain_id) + ": " if _domain_code(domain_id) else "")}'
            f"{html.escape(_domain_label(domain_id))}</th>"
            for domain_id in domain_ids
        )
        rows = (
            "".join(
                "<tr>"
                f'<th scope="row"><strong>{html.escape(item.trial_id)}</strong><br><small>{html.escape(item.result_id)}</small>'
                f"{('<br><small>' + html.escape(item.outcome) + (' · ' + html.escape(item.time_point) if item.time_point else '') + '</small>') if item.outcome else ''}</th>"
                f"<td>{html.escape(item.state.replace('_', ' '))}</td>"
                f"<td>{html.escape(item.comparison or 'not recorded')}<br><small>{html.escape(item.effect_measure or '')}</small></td>"
                f"<td>{item.evidence_count}</td>"
                f"{''.join(_traffic_cell(item.domain_judgments.get(domain_id)) for domain_id in domain_ids)}"
                f"<td>{_judgment_badge(item.overall_judgment, label='Text-labelled traffic-light judgment') if item.overall_judgment else '<span class="no-judgment">No valid judgment</span>'}</td>"
                f"<td>{html.escape(item.coverage.replace('_', ' '))}<br>"
                f"<small>{html.escape(_domain_judgments(item.domain_judgments))}</small></td>"
                f"<td>{_limitations(item.limitations)}</td>"
                f"<td>{f'<a href="{_local_href(item.report)}">Open report</a>' if item.report else 'No report yet'}</td>"
                "</tr>"
                for item in run.results
            )
            or f'<tr><td colspan="{8 + len(domain_ids)}">No terminal Result outcomes are available.</td></tr>'
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
            '<section class="run-dashboard" aria-labelledby="terminal-heading"><h2 id="terminal-heading">Terminal outcomes</h2>'
            f"<p>{counts['report_ready']} report ready; {counts['diagnostic_ready']} diagnostic ready.</p>"
            '<div class="table-wrap"><table><caption>Trial × Result dashboard</caption><thead><tr><th scope="col">Trial × Result</th><th scope="col">State</th><th scope="col">Comparison</th><th scope="col">Evidence claims</th>'
            f"{traffic_headers}<th scope=\"col\">Overall judgment</th><th scope=\"col\">Coverage</th><th scope=\"col\">Limitations</th><th scope=\"col\">Report</th>"
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
    code = _domain_code(domain.domain_id)
    heading = f"{code}: " if code else ""
    return (
        f'<article class="domain" id="{_anchor(domain.domain_id)}">'
        f"<h2>{html.escape(heading + domain.label)}</h2>"
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
    conflicts = (
        "<section class=\"conflicts\"><h4>Material source conflicts</h4><ul>"
        + "".join(
            f"<li>{html.escape(', '.join(group))}</li>" for group in question.conflicts
        )
        + "</ul></section>"
        if question.conflicts
        else ""
    )
    uncertainty = (
        '<section class="uncertainty"><h4>Uncertainty retained</h4><ul>'
        + "".join(f"<li>{html.escape(item)}</li>" for item in question.uncertainty)
        + "</ul></section>"
        if question.uncertainty
        else ""
    )
    return (
        f'<article class="question" id="{_anchor(question.question_id)}">'
        f"<h3>Signaling question {html.escape(question.question_id)}"
        f"{(': ' + html.escape(question.wording)) if question.wording else ''}</h3>"
        f'<p class="evidence-count" aria-label="Evidence count">{len(question.evidence)} evidence claims</p>'
        f"<p><strong>Answer:</strong> {html.escape(_display_answer(question.answer))}</p>"
        f"<p><strong>Coverage:</strong> {html.escape(question.coverage.replace('_', ' '))}</p>"
        f"{no_information}{_limitations(question.limitations)}{conflicts}{uncertainty}"
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
    structure = _evidence_structure(evidence)
    context = (
        f'<details class="evidence-context"><summary>Source context</summary>'
        f"<p>{html.escape(evidence.context)}</p></details>"
        if evidence.context
        else ""
    )
    return (
        f'<article class="evidence {html.escape(evidence.disposition)}">'
        f"<h4>{label}</h4>{structure}<blockquote>{html.escape(evidence.exact_phrase)}</blockquote>"
        '<p class="provenance">'
        f"Source: {html.escape(evidence.source_id)}; page {evidence.page}; "
        f"provenance: {html.escape(evidence.provenance)}; claim: {html.escape(evidence.evidence_id)}."
        f"</p>{context}{visual}</article>"
    )


def _evidence_structure(evidence: EvidenceView) -> str:
    """Describe the authored unit without turning it into a search snippet."""

    rendered = (
        f'<p class="evidence-kind"><strong>Unit:</strong> '
        f"{_EVIDENCE_KIND_LABELS[evidence.unit_kind]}</p>"
    )
    if evidence.table_headers:
        headers = "; ".join(html.escape(header) for header in evidence.table_headers)
        rendered += f'<p class="table-headers"><strong>Table headers:</strong> {headers}</p>'
    return rendered


def _render_visual_citation(citation: VisualCitationView) -> str:
    phrase = citation.exact_phrase or "Exact phrase is retained with the source claim."
    provenance = citation.render_provenance or "render provenance not recorded"
    region = ", ".join(f"{value:g}" for value in citation.region)
    inspected = citation.agent_inspected is True
    if citation.inspection_status == "visual_only_transcription" or inspected:
        state = "agent inspected; visual-only transcription"
        asset_caption = "Agent inspected this rendered region; transcription remains visual-only."
    else:
        # Keep the stable phrase used by existing audit snapshots while
        # making the automatic-vs-visual distinction explicit.
        state = "agent inspection not performed (automatic spatial claim)"
        asset_caption = "Agent inspection not performed; geometry is a deterministic spatial binding."
    assets = (
        f'<figure><img src="{_local_href(citation.crop_path)}" '
        f'alt="Highlighted local crop for {html.escape(citation.label)}">'
        f'<figcaption><a href="{_local_href(citation.context_path)}">Open local full-page context</a>. '
        f"{html.escape(asset_caption)}</figcaption></figure>"
        if citation.crop_path and citation.context_path
        else "<p>Local render assets were unavailable; this citation is retained as provenance only.</p>"
    )
    return (
        f'<details class="visual-citation"><summary>Visual citation — {html.escape(state)}</summary>'
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
    if not label:
        return (
            f'<span class="judgment judgment-{html.escape(judgment)}" '
            f'aria-label="{html.escape(text)}">{html.escape(text)}</span>'
        )
    if "traffic-light" in label:
        # Keep the visual traffic-light wording available to assistive
        # technology while presenting one non-duplicated sighted label.
        return (
            f'<p class="judgment judgment-{html.escape(judgment)}"><span aria-hidden="true">o</span> '
            f'<strong>Text-labelled judgment: {html.escape(text)}</strong>'
            f'<span class="sr-only">{html.escape(label)}</span></p>'
        )
    return (
        f'<p class="judgment judgment-{html.escape(judgment)}"><span aria-hidden="true">o</span> '
        f"<strong>{html.escape(label)}: Text-labelled judgment: {html.escape(text)}</strong></p>"
    )


def _traffic_cell(judgment: str | None) -> str:
    if judgment not in {"low", "some_concerns", "high"}:
        return '<td><span class="traffic-cell traffic-none" aria-label="No judgment">—</span></td>'
    return (
        f'<td><span class="traffic-cell traffic-{html.escape(judgment)}" '
        f'aria-label="{html.escape(_display_judgment(judgment))}">{html.escape(_display_judgment(judgment)[0])}</span></td>'
    )


_DOMAIN_LABELS = {
    "domain:randomization": "Bias arising from the randomization process",
    "domain:deviations": "Bias due to deviations from intended interventions",
    "domain:missing": "Bias due to missing outcome data",
    "domain:measurement": "Bias in measurement of the outcome",
    "domain:selection": "Bias in selection of the reported result",
}

_EVIDENCE_KIND_LABELS = {
    "heading": "Heading",
    "paragraph": "Authored paragraph",
    "list_item": "Authored list item",
    "caption": "Figure or table caption",
    "footnote": "Authored footnote",
    "table_row": "Header-aware table row",
}

_DOMAIN_ORDER = tuple(_DOMAIN_LABELS)
_DOMAIN_CODES = {domain_id: f"D{index}" for index, domain_id in enumerate(_DOMAIN_ORDER, start=1)}


def _ordered_domains(domains: tuple[DomainView, ...]) -> tuple[DomainView, ...]:
    """Apply the official RoB 2 D1–D5 order to every human projection."""

    return tuple(
        sorted(
            domains,
            key=lambda domain: (
                _DOMAIN_CODES.get(domain.domain_id, "D99"),
                domain.domain_id,
            ),
        )
    )


def _domain_code(domain_id: str) -> str:
    return _DOMAIN_CODES.get(domain_id, "")


def _render_overall_policy(assessment: AssessmentView) -> str:
    if not (
        assessment.overall_policy_id
        or assessment.overall_policy_hash
        or assessment.overall_decision_trace
    ):
        return ""
    policy_text = assessment.overall_policy_text or (
        "Low when all five domain judgments are Low; High when any domain judgment is High; "
        "otherwise Some concerns."
    )
    trace = assessment.overall_decision_trace or ("not recorded",)
    trace_html = "".join(f"<li><code>{html.escape(item)}</code></li>" for item in trace)
    return (
        '<section class="overall-policy" aria-labelledby="overall-policy-heading">'
        '<h2 id="overall-policy-heading">Overall maximum-domain policy</h2>'
        f"<p>{html.escape(policy_text)}</p>"
        f"<dl class=\"identity-grid\"><div><dt>Policy id</dt><dd><code>{html.escape(assessment.overall_policy_id or 'not recorded')}</code></dd></div>"
        f"<div><dt>Policy hash</dt><dd><code>{html.escape(assessment.overall_policy_hash or 'not recorded')}</code></dd></div></dl>"
        f"<h3>Decision trace</h3><ul>{trace_html}</ul></section>"
    )


def _domain_label(domain_id: str) -> str:
    return _DOMAIN_LABELS.get(domain_id, domain_id)


def _estimate_text(estimate: EstimateView | None) -> str:
    if estimate is None:
        return "not recorded"
    if estimate.interval:
        return f"{estimate.value} (95% CI {estimate.interval})"
    return estimate.value


def _result_identity_text(assessment: AssessmentView) -> str:
    parts = [assessment.trial, assessment.result_id, assessment.comparison, assessment.outcome]
    if assessment.time_point:
        parts.append(assessment.time_point)
    if assessment.effect_measure:
        parts.append(assessment.effect_measure)
    return " · ".join(parts)


def _optional_identity_cells(assessment: AssessmentView) -> str:
    fields = (
        ("Measurement instrument", assessment.measurement_instrument),
        ("Analysis population", assessment.analysis_population),
        ("Analysis model", assessment.analysis_model),
        ("Effect measure", assessment.effect_measure),
        ("Source locator", assessment.source_locator),
    )
    return "".join(
        f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>"
        for label, value in fields
        if value
    )


def _estimate_card(assessment: AssessmentView) -> str:
    if assessment.estimate is None and not assessment.effect_measure:
        return ""
    estimate = assessment.estimate
    denominators = ""
    if estimate and estimate.denominator_experimental is not None and estimate.denominator_comparator is not None:
        denominators = (
            f"<small>Denominators: {estimate.denominator_experimental} experimental; "
            f"{estimate.denominator_comparator} comparator</small>"
        )
    return (
        '<aside class="estimate-card" aria-label="Reported result estimate">'
        f"<span class=\"eyebrow\">{html.escape(assessment.effect_measure or 'Reported estimate')}</span>"
        f"<strong>{html.escape(_estimate_text(estimate))}</strong>{denominators}</aside>"
    )


def _evidence_count(assessment: AssessmentView) -> int:
    return len(
        {
            evidence.evidence_id
            for domain in assessment.domains
            for question in domain.questions
            for evidence in question.evidence
        }
    )


def _has_extended_identity(assessment: AssessmentView) -> bool:
    return bool(
        assessment.effect_measure
        or assessment.estimate
        or assessment.measurement_instrument
        or assessment.analysis_population
        or assessment.analysis_model
        or assessment.source_locator
    )


def _assessment_payload(assessment: AssessmentView) -> dict[str, object]:
    """Serialize legacy views byte-for-byte while retaining populated extensions."""

    payload = assessment.model_dump(mode="json")
    if not _has_extended_identity(assessment):
        for key in (
            "measurement_instrument",
            "analysis_population",
            "analysis_model",
            "effect_measure",
            "source_locator",
            "estimate",
            "result_identity",
            "result_details",
            "overall_policy_id",
            "overall_policy_hash",
            "overall_policy_text",
            "overall_decision_trace",
            "limitations",
        ):
            payload.pop(key, None)
    elif not assessment.limitations:
        payload.pop("limitations", None)
    for domain_payload, domain in zip(payload.get("domains", ()), assessment.domains, strict=False):
        if not any(question.wording for question in domain.questions):
            for question_payload in domain_payload.get("questions", ()):
                question_payload.pop("wording", None)
                question_payload.pop("conflicts", None)
                question_payload.pop("uncertainty", None)
        for question_payload, question in zip(
            domain_payload.get("questions", ()), domain.questions, strict=False
        ):
            for evidence_payload, evidence in zip(
                question_payload.get("evidence", ()), question.evidence, strict=False
            ):
                if evidence.unit_kind == "paragraph":
                    evidence_payload.pop("unit_kind", None)
                if not evidence.context:
                    evidence_payload.pop("context", None)
                if not evidence.table_headers:
                    evidence_payload.pop("table_headers", None)
    return payload


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


def _html_document(
    title: str, body: str, *, css: str | None = None, include_csp: bool = True
) -> str:
    csp = (
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src \'unsafe-inline\'; img-src \'self\'; font-src \'none\'; "
        "connect-src \'none\'; object-src \'none\'; frame-src \'none\'; "
        'base-uri \'none\'; form-action \'none\'">'
        if include_csp
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{csp}"
        f"<title>{html.escape(title)}</title><style>{css if css is not None else _AUDIT_CSS}</style></head><body>{body}</body></html>\n"
    )


_LEGACY_AUDIT_CSS = """
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


_AUDIT_CSS = """
:root { --sr-only: 1px; }
.sr-only { position: absolute; width: var(--sr-only); height: var(--sr-only); padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #17322d; background: #f7f4ed; }
body { margin: 0; line-height: 1.5; } main { max-width: 90rem; margin: auto; padding: 1rem; }
h1, h2 { font-family: Georgia, serif; } .report-header, .result-hero, .audit-summary, .domain, .question, .diagnostic { border: 1px solid #c9c5ba; border-radius: .5rem; background: #fffdf8; padding: 1rem; margin: 1rem 0; }
.result-hero { display: flex; justify-content: space-between; gap: 1.5rem; align-items: stretch; } .estimate-card { min-width: 12rem; display: flex; flex-direction: column; justify-content: center; padding: 1rem; border-left: .25rem solid #9a5a12; background: #fff4dc; } .estimate-card strong { font: 1.7rem Georgia, serif; } .estimate-card small { margin-top: .35rem; }
.audit-summary { position: sticky; top: .25rem; z-index: 4; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; } .summary-count { color: #53635e; font-size: .9rem; }
.report-layout { display: grid; grid-template-columns: minmax(15rem, 18rem) minmax(0, 1fr); gap: 1rem; align-items: start; } .domain-rail { position: sticky; top: 5rem; border: 1px solid #c9c5ba; border-radius: .5rem; background: #fffdf8; padding: .75rem; } .domain-rail h2 { font-size: 1.15rem; margin-top: .25rem; } .domain-rail ol { padding: 0; margin: 0; list-style: none; } .domain-rail li + li { margin-top: .35rem; } .domain-rail a { display: grid; grid-template-columns: 1.7rem minmax(0, 1fr); gap: .55rem; align-items: center; padding: .5rem; border-radius: .4rem; text-decoration: none; color: inherit; } .domain-rail a:hover, .domain-rail a:focus-visible { background: #e4ede8; } .domain-rail .judgment { grid-column: 2; font-size: .7rem; padding: 0; margin: 0; background: transparent; }
.domain-number { display: grid; place-items: center; width: 1.55rem; height: 1.55rem; color: #fff; background: #40645a; border-radius: 50%; font-weight: 700; }
.identity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: .75rem; } .identity-grid div { border-left: .25rem solid #40645a; padding-left: .5rem; } dt { font-weight: 700; } dd { margin: 0; overflow-wrap: anywhere; }
.judgment { display: inline-block; padding: .25rem .5rem; border-radius: .25rem; } .judgment-low { background: #dcefe3; } .judgment-some_concerns { background: #fff0c9; } .judgment-high { background: #f9ddd8; } .no-judgment { font-weight: 700; }
nav ol { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; padding-left: 1.25rem; } .questions { margin-top: 1rem; } .evidence { border-left: .3rem solid #40645a; padding: .5rem 1rem; margin: .75rem 0; background: #f7f4ed; } .evidence.contradicting { border-color: #9c3226; } .evidence.contextual, .evidence.residual { border-color: #9a5a12; } .evidence-count { color: #53635e; font-size: .84rem; }
blockquote { margin-left: 0; padding-left: .75rem; border-left: .2rem solid #777; } .provenance, figcaption { font-size: .9rem; overflow-wrap: anywhere; } .table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; } th, td { padding: .5rem; text-align: left; vertical-align: top; border-bottom: 1px solid #c9c5ba; } th { background: #e4ede8; }
a { color: #064c87; } a:focus-visible, summary:focus-visible { outline: .2rem solid #9a5a12; outline-offset: .2rem; } summary { cursor: pointer; font-weight: 700; } svg { display: block; max-width: 22rem; width: 100%; height: auto; }
.run-dashboard caption { text-align: left; padding: .6rem 0; font-weight: 700; } .traffic-cell { display: inline-grid; place-items: center; width: 1.7rem; height: 1.7rem; border-radius: 50%; color: #fff; font-size: .7rem; font-weight: 800; } .traffic-low { background: #26734d; } .traffic-some_concerns { background: #a56b0b; } .traffic-high { background: #9c3226; } .traffic-none { color: #53635e; background: #e4e7e5; }
@media (max-width: 58rem) { .report-layout { grid-template-columns: 1fr; } .domain-rail { position: static; } .domain-rail ol { display: flex; overflow-x: auto; gap: .35rem; } .domain-rail li { min-width: 13rem; } .result-hero { flex-direction: column; } }
@media (max-width: 20rem) { main { padding: .5rem; } nav ol { display: block; } nav li { margin: .5rem 0; } .identity-grid { grid-template-columns: 1fr; } }
@media print { body { background: #fff; color: #000; } main { max-width: none; } nav, .domain-rail, .prototype-controls, [data-prototype-control] { display: none !important; } details, details[open] { display: block; } details > *, details:not([open]) > * { display: block !important; } details > summary { display: none; } .report-header, .audit-summary, .domain, .question, .diagnostic { break-inside: avoid; box-shadow: none; } a { color: inherit; text-decoration: none; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; } }
@media (forced-colors: active) { .judgment, .traffic-cell { border: 1px solid CanvasText; forced-color-adjust: none; } }
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
    traces = tuple(
        _load_reference(ledger, current, judgment.decision_trace, DecisionTrace)
        for judgment in judgments
    )
    answers_by_sq: dict[str, SQAnswerRevision] = {}
    for reference in assessment.answers:
        try:
            answer = _load_reference(ledger, current, reference, SQAnswerRevision)
        except (TypeError, ValueError):
            continue
        answers_by_sq[answer.sq_id] = answer
    logic = _load_pinned_logic_pack(judgments, tuple(answers_by_sq.values()))
    active_question_ids = {
        question_id for trace in traces for question_id in trace.active_question_ids
    }
    overall_decision_trace: tuple[Identifier, ...] = ()
    if logic is not None:
        evaluation_answers = {
            question_id: answer.answer
            for question_id, answer in answers_by_sq.items()
            if not active_question_ids or question_id in active_question_ids
        }
        evaluation = LogicEvaluator(logic).evaluate(EvaluationRequest(answers=evaluation_answers))
        expected = {judgment.domain_id: judgment.judgment for judgment in judgments}
        if evaluation.domain_judgments != expected:
            raise ValueError("stored domain judgments do not match the pinned Logic evaluation")
        active_question_ids = set(evaluation.active_question_ids)
        overall_judgment = evaluation.overall_judgment.value
        # Preserve the complete evaluator trace (domain matches followed by
        # the matched overall rule); consumers can identify the overall rule
        # by its ``rule:overall:`` prefix without losing domain provenance.
        overall_decision_trace = evaluation.matched_rule_ids
    else:
        overall_judgment = _overall_judgment(
            tuple(judgment.judgment.value for judgment in judgments)
        )
    question_order = (
        {question.id: index for index, question in enumerate(logic.questions)}
        if logic is not None
        else {}
    )
    _question_views, question_domains, visual_citations = _latest_question_views(
        ledger,
        current,
        assessment,
        answers_by_sq,
        active_question_ids=frozenset(active_question_ids),
        question_order=question_order,
    )
    result = result_spec.result
    domain_order = (
        {domain.id: index for index, domain in enumerate(logic.domains, start=1)}
        if logic is not None
        else {domain_id: index for index, domain_id in enumerate(_DOMAIN_LABELS, start=1)}
    )
    ordered = sorted(judgments, key=lambda judgment: domain_order.get(judgment.domain_id, 99))
    report_limitations = tuple(
        dict.fromkeys(
            limitation
            for domain in question_domains.values()
            for question in domain
            for limitation in question.limitations
        )
    )
    estimate = EstimateView(
        value=str(result_spec.estimate.value),
        interval_lower=(
            str(result_spec.estimate.interval_lower)
            if result_spec.estimate.interval_lower is not None
            else None
        ),
        interval_upper=(
            str(result_spec.estimate.interval_upper)
            if result_spec.estimate.interval_upper is not None
            else None
        ),
        denominator_experimental=result_spec.estimate.denominator_experimental,
        denominator_comparator=result_spec.estimate.denominator_comparator,
    )
    identity = ResultIdentityView(
        result_id=result.result_id,
        trial_id=result.trial_id,
        comparison=(
            f"{result.comparison.experimental_arm_id} vs {result.comparison.comparator_arm_id}"
        ),
        effect_of_interest=result.effect_of_interest,
        outcome=result.outcome_construct,
        measurement_instrument=result.measurement_instrument,
        time_point=result.time_point,
        analysis_population=result.analysis_population,
        analysis_model=result.analysis_model,
        effect_measure=result.effect_measure,
        source_locator=result.source_locator,
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
        measurement_instrument=result.measurement_instrument,
        analysis_population=result.analysis_population,
        analysis_model=result.analysis_model,
        effect_measure=result.effect_measure,
        source_locator=result.source_locator,
        estimate=estimate,
        limitations=report_limitations,
        result_identity=identity,
        result_details=ResultDetailsView(
            measurement_instrument=result.measurement_instrument,
            analysis_population=result.analysis_population,
            analysis_model=result.analysis_model,
            effect_measure=result.effect_measure,
            source_locator=result.source_locator,
            estimate=estimate,
        ),
        overall_judgment=overall_judgment,
        domains=_ordered_domains(tuple(
            DomainView(
                domain_id=judgment.domain_id,
                label=_domain_label(judgment.domain_id),
                judgment=judgment.judgment.value,
                rationale=(f"Algorithmic judgment from {judgment.decision_trace.revision_id}."),
                questions=tuple(
                    sorted(
                        question_domains.get(judgment.domain_id, ()),
                        key=lambda question: (
                            question_order.get(
                                str(getattr(question, "question_id", "")), 10_000
                            ),
                            str(getattr(question, "question_id", "")),
                        ),
                    )
                ),
                decision_trace=(judgment.decision_trace.revision_id,),
                coverage=(
                    "incomplete"
                    if any(question.coverage == "incomplete" for question in question_domains.get(judgment.domain_id, ()))
                    else "complete"
                ),
                limitations=tuple(
                    limitation
                    for question in question_domains.get(judgment.domain_id, ())
                    for limitation in question.limitations
                ),
            )
            for judgment in ordered
        )),
        visual_citations=visual_citations,
        overall_policy_id=(ordered[0].overall_policy_id if ordered else None),
        overall_policy_hash=(ordered[0].overall_policy_hash if ordered else None),
        overall_policy_text=(
            "Low when all five domain judgments are Low; High when any domain judgment is High; otherwise Some concerns."
            if ordered and ordered[0].overall_policy_id
            else ""
        ),
        overall_decision_trace=overall_decision_trace,
    )


def _latest_question_views(
    ledger: WorkflowLedger,
    current: dict[str, RevisionProjection],
    assessment: AssessmentRevision,
    answers: dict[str, SQAnswerRevision],
    *,
    active_question_ids: frozenset[str] = frozenset(),
    question_order: dict[str, int] | None = None,
) -> tuple[
    dict[str, SignalingQuestionView],
    dict[str, tuple[SignalingQuestionView, ...]],
    tuple[VisualCitationView, ...],
]:
    """Rehydrate evidence-first questions from the Assessment dependencies.

    ``latest_assessment_view`` is a read-only compatibility projection, but it
    must not silently discard the evidence, coverage, conflict, and uncertainty
    fields that terminal reports expose.  Every phrase below is reconstructed
    from the frozen canonical span or visual transcription artifact.
    """

    result: dict[str, SignalingQuestionView] = {}
    domains: dict[str, list[SignalingQuestionView]] = {}
    visual_citations: dict[str, VisualCitationView] = {}
    question_order = question_order or {}
    guidance = _guidance_wording()
    for reference in assessment.evidence_bundles:
        try:
            bundle = _load_reference(ledger, current, reference, EvidenceBundle)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Assessment evidence bundle {reference.revision_id!r} cannot be reconstructed"
            ) from error
        if bundle.sq_id is None:
            continue
        answer = answers.get(bundle.sq_id)
        if answer is None or (
            active_question_ids and bundle.sq_id not in active_question_ids
        ):
            # Inactive Logic branches and bundles without a durable answer
            # revision are not questions in the current Assessment view.
            continue
        dispositions: dict[str, str] = {}
        if bundle.consideration_manifest is not None:
            try:
                manifest = _load_reference(
                    ledger, current, bundle.consideration_manifest, EvidenceConsiderationManifest
                )
                dispositions = {
                    item.item_id: item.disposition.value for item in manifest.dispositions
                }
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Evidence consideration manifest for {bundle.sq_id!r} cannot be reconstructed"
                ) from error
        evidence: list[EvidenceView] = []
        for item in bundle.items:
            disposition = dispositions.get(item.entity_id, "contextual")
            if disposition not in {"supporting", "contradicting", "contextual"}:
                disposition = "residual"
            try:
                claim = _load_reference(ledger, current, item, EvidenceClaim)
                unit = _load_reference(ledger, current, claim.canonical_unit, CanonicalEvidenceUnit)
                phrase = unit.text[claim.span_start : claim.span_end]
                if not phrase:
                    continue
                if sha256_digest(phrase.encode("utf-8")) != claim.quoted_text_hash:
                    raise ValueError(
                        f"canonical EvidenceClaim {claim.revision_id} quoted-text hash mismatch"
                    )
                visual = None
                try:
                    citation = build_visual_citation(
                        unit, span_start=claim.span_start, span_end=claim.span_end
                    )
                    region = (
                        min(box.left for box in citation.boxes),
                        min(box.top for box in citation.boxes),
                        max(box.right for box in citation.boxes),
                        max(box.bottom for box in citation.boxes),
                    )
                    visual = VisualCitationView(
                        citation_id=citation.citation_id,
                        source_id=citation.source_id,
                        page=citation.page,
                        region=region,
                        boxes=tuple(
                            (box.left, box.top, box.right, box.bottom)
                            for box in citation.boxes
                        ),
                        label="Canonical evidence span",
                        exact_phrase=phrase,
                        render_provenance=(
                            f"canonical unit {unit.unit_id}; Parse record {citation.parse_id}; "
                            f"source artifact {citation.source_artifact_hash}; "
                            f"{citation.render.mode.value} at {citation.render.dpi} dpi; "
                            "agent inspection not performed"
                        ),
                        canonical_unit_id=citation.canonical_unit_id,
                        source_artifact_hash=citation.source_artifact_hash,
                        parse_id=citation.parse_id,
                        span_start=citation.span_start,
                        span_end=citation.span_end,
                        quoted_text_hash=citation.quoted_text_hash,
                        geometry_scope=citation.geometry_scope,
                        geometry_hash=citation.geometry_hash,
                        render_hash=citation.render_hash,
                        render_mode=citation.render.mode.value,
                        dpi=citation.render.dpi,
                        agent_inspected=False,
                        inspection_status="automatic_spatial_claim",
                    )
                    visual_citations[visual.citation_id] = visual
                except (TypeError, ValueError):
                    # Text-only canonical units remain valid evidence; their
                    # absence of geometry is retained in provenance below.
                    pass
                evidence.append(
                    EvidenceView(
                        evidence_id=claim.revision_id,
                        disposition=disposition,
                        exact_phrase=phrase,
                        source_id=claim.source.entity_id,
                        page=unit.page,
                        provenance=(
                            f"canonical unit {unit.unit_id}; Parse record {unit.parse_id}; "
                            f"verification {claim.verification_status.value}"
                        ),
                        unit_kind=unit.kind.value,
                        visual_citation=visual,
                    )
                )
                continue
            except (TypeError, IndexError, ValidationError):
                pass
            try:
                transcription = _load_reference(ledger, current, item, VisualTranscription)
            except (TypeError, ValueError):
                continue
            visual = VisualCitationView(
                citation_id=transcription.revision_id,
                source_id=transcription.source.entity_id,
                page=transcription.page,
                region=transcription.region,
                boxes=(transcription.region,),
                label="Visual transcription",
                exact_phrase=transcription.transcription,
                render_provenance=(
                    f"{transcription.render_mode} at {transcription.dpi} dpi; "
                    "visual-only; not machine-verified"
                ),
                quoted_text_hash=sha256_digest(transcription.transcription.encode("utf-8")),
                geometry_scope="visual_region",
                geometry_hash=canonical_hash(
                    {"region": transcription.region, "page": transcription.page}
                ),
                render_hash=canonical_hash(
                    {
                        "source_id": transcription.source.entity_id,
                        "page": transcription.page,
                        "mode": transcription.render_mode,
                        "dpi": transcription.dpi,
                        "region": transcription.region,
                    }
                ),
                render_mode=transcription.render_mode,
                dpi=transcription.dpi,
                agent_inspected=True,
                inspection_status="visual_only_transcription",
            )
            evidence.append(
                EvidenceView(
                    evidence_id=transcription.revision_id,
                    disposition=disposition,
                    exact_phrase=transcription.transcription,
                    source_id=transcription.source.entity_id,
                    page=transcription.page,
                    provenance=(
                        f"visual-only transcription; {transcription.render_mode} at "
                        f"{transcription.dpi} dpi; not machine-verified"
                    ),
                    visual_citation=visual,
                )
            )
            visual_citations[visual.citation_id] = visual
        uncertainty = (
            (f"coverage state: {bundle.coverage_state.value}",)
            if bundle.coverage_state.value != "complete"
            else ()
        ) + bundle.coverage_limitations + (
            ("material source conflict retained",) if bundle.conflicts else ()
        )
        question = SignalingQuestionView(
            question_id=bundle.sq_id,
            wording=guidance.get(bundle.sq_id, ""),
            answer=answer.answer.value,
            rationale=answer.rationale,
            evidence=tuple(evidence),
            coverage=bundle.coverage_state.value,
            limitations=bundle.coverage_limitations,
            no_information_basis=bundle.no_information_basis,
            conflicts=bundle.conflicts,
            uncertainty=uncertainty,
            decision_trace=answer.decision_rule_ids,
        )
        result[bundle.sq_id] = question
        if bundle.domain_id is not None:
            domains.setdefault(bundle.domain_id, []).append(question)
    return (
        result,
        {domain_id: tuple(items) for domain_id, items in domains.items()},
        tuple(visual_citations[key] for key in sorted(visual_citations)),
    )


def _guidance_wording() -> dict[str, str]:
    """Load official Guidance wording when the pinned pack is available.

    The compatibility projection is ledger-only, so a missing pack is
    surfaced as empty wording rather than inventing paraphrases.  Terminal
    reports still carry the authoritative wording materialized by RunEngine.
    """

    candidates = (
        Path(__file__).resolve().parents[1]
        / "packs"
        / "guidance"
        / "rob2-parallel-assignment-en-2019.1.yaml",
        Path(__file__).resolve().parents[3]
        / "packs"
        / "guidance"
        / "rob2-parallel-assignment-en-2019.1.yaml",
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                pack = load_guidance_pack(candidate)
            except (OSError, ValueError):
                continue
            return {item.logic_element_id: item.text for item in pack.items}
    return {}


def _load_pinned_logic_pack(
    judgments: tuple[AlgorithmicJudgmentRevision, ...],
    answers: tuple[SQAnswerRevision, ...],
) -> LogicPack | None:
    """Load the installed Logic release only when its immutable pin matches."""

    expected_hash = next(
        (
            value
            for value in (
                *(judgment.logic_pack_hash for judgment in judgments),
                *(answer.logic_pack_hash for answer in answers),
            )
            if value
        ),
        None,
    )
    expected_release = next(
        (
            value
            for value in (
                *(judgment.logic_pack_release_id for judgment in judgments),
                *(answer.logic_pack_release_id for answer in answers),
            )
            if value
        ),
        None,
    )
    if expected_hash is None and expected_release is None:
        return None
    roots = (
        Path(__file__).resolve().parents[1] / "packs" / "logic",
        Path(__file__).resolve().parents[3] / "packs" / "logic",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.yaml")):
            try:
                pack = load_logic_pack(path)
            except (OSError, ValueError):
                continue
            if expected_hash is not None and pack.content_hash != expected_hash:
                continue
            if expected_release is not None and pack.release_id != expected_release:
                continue
            return pack
    raise ValueError("the pinned Logic pack release is unavailable")


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
