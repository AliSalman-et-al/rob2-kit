# ruff: noqa: E501
"""Deterministic assessment and batch bundles.

Only batch publication, finalization, and receipt use the cooperative workspace-
lock mutation boundary. A batch receipt authenticates exact bytes captured at
finalization; direct concurrent batch filesystem edits are outside that boundary,
and later batch exports or receipts reject drift. Per-Trial bundle exporters do
not make this cooperative-boundary claim.
"""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from rob2_kit.batch_summary import ArtifactReceipt, BatchSummary, verified_summary
from rob2_kit.finish import AssessmentSnapshot, _verified
from rob2_kit.judgment_models import TextEvidenceRef, VisualEvidenceRef
from rob2_kit.models import canonical_json_bytes
from rob2_kit.projection_verify import reproduce_projection_identity
from rob2_kit.rendering import RenderedPage, render_page
from rob2_kit.sources import Source, sha256_bytes, verified_source_bytes
from rob2_kit.storage import _reparse, transaction, workspace_mutation_lock
from rob2_kit.text_projection import VerifiedProjection, canonical_projection_identity


def _redirected(path: Path) -> bool:
    return path.is_symlink() or (path.exists() and _reparse(path))


def _bundle_hash(files: list[tuple[str, bytes]]) -> str:
    """Hash exact file bytes in lexical, case-sensitive POSIX-name order."""
    digest = hashlib.sha256()
    for relative, data in sorted(files, key=lambda entry: entry[0]):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _report_escape(value: object) -> str:
    return html.escape(str(value))


def _report_values_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return ", ".join(str(item) for item in value)


def _report_judgment_class(value: object) -> str:
    return {
        "low": "low",
        "some_concerns": "some_concerns",
        "high": "high",
    }.get(str(value), "none")


def _report_quantity_text(item: dict[str, Any]) -> str:
    value = (
        f"{item.get('statistic', '')}; "
        f"{item.get('group_or_category', '')}: "
        f"{item.get('value', '')} {item.get('unit', '')}"
    )
    denominator = item.get("denominator_basis")
    if denominator:
        value += f"; denominator: {denominator}"
    return value.strip()


def _report_evidence_bindings(checkpoint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    bindings_by_identity: dict[str, dict[str, Any]] = {}
    bindings = checkpoint.get("evidence_bindings", [])
    if not isinstance(bindings, list):
        return bindings_by_identity
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        reference = binding.get("evidence")
        identity = reference.get("identity") if isinstance(reference, dict) else None
        if isinstance(identity, str) and identity:
            bindings_by_identity.setdefault(identity, binding)
    return bindings_by_identity


def _report_evidence_use(
    use: dict[str, Any], bindings_by_identity: dict[str, dict[str, Any]]
) -> str:
    relationship = str(use.get("relationship", ""))
    relationship_class = {
        "supporting": "supporting",
        "contradicting": "contradicting",
        "contextual": "contextual",
        "residual": "residual",
    }.get(relationship, "other")
    content = [
        f"<article class=\"evidence {relationship_class}\">",
        f"<h4>{_report_escape(relationship)}</h4>",
        f"<p class=\"claim\"><strong>Claim:</strong> {_report_escape(use.get('claim', ''))}</p>",
        "<details><summary>Evidence-use rationale</summary>"
        f"<p>{_report_escape(use.get('rationale', ''))}</p></details>",
    ]
    references = use.get("evidence", [])
    if not isinstance(references, list):
        references = []
    seen: set[str] = set()
    for reference in references:
        identity = reference.get("identity") if isinstance(reference, dict) else str(reference)
        if not isinstance(identity, str) or not identity or identity in seen:
            continue
        seen.add(identity)
        binding = bindings_by_identity.get(identity)
        if binding is None:
            content.append(
                f"<p class=\"unresolved-evidence\"><strong>Evidence identity:</strong> "
                f"<code>{_report_escape(identity)}</code> (binding unavailable)</p>"
            )
            continue
        quote = binding.get("quote")
        if not isinstance(quote, str):
            quote = binding.get("transcription")
        if isinstance(quote, str):
            content.append(f"<blockquote>\"{_report_escape(quote)}\"</blockquote>")
        provenance: list[str] = []
        if binding.get("source_id") is not None:
            provenance.append(f"Source: {binding.get('source_id')}")
        if binding.get("page") is not None:
            provenance.append(f"page {binding.get('page')}")
        if binding.get("start") is not None and binding.get("end") is not None:
            provenance.append(f"extent [{binding.get('start')}:{binding.get('end')}]")
        if provenance:
            content.append(
                f"<p class=\"provenance\">{_report_escape('; '.join(provenance))}</p>"
            )
        content.append(f"<p class=\"evidence-identity\"><code>{_report_escape(identity)}</code></p>")
    content.append("</article>")
    return "".join(content)


def _report_domain(
    checkpoint: dict[str, Any], trial_number: int, number: int
) -> tuple[str, str]:
    domain_id = str(checkpoint.get("domain_id", ""))
    anchor = f"domain-{trial_number}-{number}"
    proposed = str(checkpoint.get("proposed_judgment", ""))
    judgment = _report_judgment_class(proposed)
    bindings_by_identity = _report_evidence_bindings(checkpoint)
    nav = (
        f"<li><a href=\"#{anchor}\"><span class=\"domain-number\">{number}</span>"
        f"<span>{_report_escape(domain_id)}</span><span class=\"judgment judgment-{judgment}\">"
        f"{_report_escape(proposed)}</span><small class=\"domain-evidence\">Evidence: "
        f"{_report_escape(', '.join(bindings_by_identity) or 'none')}</small></a></li>"
    )
    draft = checkpoint.get("draft", {})
    draft = draft if isinstance(draft, dict) else {}
    inactive = checkpoint.get("inactive_questions", [])
    limitations = draft.get("limitations", [])
    answers = draft.get("active_answers", [])
    answers = answers if isinstance(answers, list) else []
    content = [
        f"<article class=\"domain\" id=\"{anchor}\" aria-labelledby=\"{anchor}-heading\">",
        f"<p class=\"judgment judgment-{judgment}\"><strong>Proposed judgment: "
        f"{_report_escape(proposed)}</strong></p>",
        f"<h2 id=\"{anchor}-heading\">{_report_escape(domain_id)}</h2>",
    ]
    if isinstance(inactive, list) and inactive:
        content.append(
            f"<p class=\"domain-meta\"><strong>Inactive questions:</strong> "
            f"{_report_escape(_report_values_text(inactive))}</p>"
        )
    if isinstance(limitations, list) and limitations:
        content.append(
            f"<p class=\"domain-meta\"><strong>Limitations:</strong> "
            f"{_report_escape(_report_values_text(limitations))}</p>"
        )
    content.append(
        f"<p class=\"domain-meta\"><strong>Active questions:</strong> {len(answers)}</p>"
    )
    content.append(
        f"<div class=\"questions\" aria-label=\"Signaling questions for "
        f"{_report_escape(domain_id)}\">"
    )
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        question_content = [
            "<div class=\"question\">",
            f"<h3>Signaling question <code>{_report_escape(answer.get('question_id', ''))}</code></h3>",
            f"<p><strong>Answer:</strong> {_report_escape(answer.get('answer', ''))}</p>",
            "<details><summary>Answer rationale</summary>"
            f"<p>{_report_escape(answer.get('rationale', ''))}</p></details>",
            "<div class=\"evidence-list\" aria-label=\"Evidence uses\">",
        ]
        uses = answer.get("evidence_uses", [])
        if isinstance(uses, list):
            question_content.extend(
                _report_evidence_use(use, bindings_by_identity)
                for use in uses
                if isinstance(use, dict)
            )
        question_content.extend(("</div>", "</div>"))
        content.append("".join(question_content))
    content.extend(("</div>", "</article>"))
    return nav, "".join(content)


def _report_ordered_checkpoints(
    records: list[dict[str, Any]], trial_id: str, checkpoint_order: tuple[tuple[str, str], ...]
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        if record.get("kind") != "domain_candidate" or record.get("trial_id") != trial_id:
            continue
        domain_id = record.get("domain_id")
        active_hash = record.get("active_hash")
        if isinstance(domain_id, str) and isinstance(active_hash, str):
            candidates.setdefault((domain_id, active_hash), []).append(record)
    return [
        candidates[key][0]
        for key in checkpoint_order
        if len(candidates.get(key, ())) == 1
    ]


def application_finalization_report(summary: dict[str, Any], records: list[dict[str, Any]]) -> str:
    """Render the portable application bundle from its persisted record basis."""

    escaped = _report_escape
    values_text = _report_values_text
    judgment_class = _report_judgment_class
    quantity_text = _report_quantity_text

    terminals = [
        record
        for record in records
        if record.get("kind") == "trial_terminal" and isinstance(record.get("trial_id"), str)
    ]
    snapshot_checkpoints = {
        (str(record.get("trial_id")), str(record.get("identity"))): tuple(
            (item[0], item[1])
            for item in record.get("checkpoint_hashes", [])
            if isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
        )
        for record in records
        if record.get("kind") == "assessment_snapshot" and isinstance(record.get("trial_id"), str)
    }
    approved_id = (
        summary.get("approved_batch", {}).get("identity")
        if isinstance(summary.get("approved_batch"), dict)
        else None
    )
    approved = next(
        (
            record
            for record in records
            if record.get("kind") == "approved_batch" and record.get("identity") == approved_id
        ),
        {},
    )
    proposal_id = approved.get("review")
    proposal = next(
        (
            record
            for record in records
            if record.get("kind") == "proposal_review"
            and isinstance(proposal_id, str)
            and record.get("identity") == proposal_id
        ),
        {},
    )
    proposal_results = {
        str(result.get("trial_id")): result
        for result in proposal.get("results", [])
        if isinstance(result, dict) and isinstance(result.get("trial_id"), str)
    }
    sections: list[str] = []
    for trial_number, trial in enumerate(summary.get("trials", []), 1):
        if not isinstance(trial, dict):
            continue
        trial_id = str(trial.get("trial_id", ""))
        disposition = str(trial.get("disposition", ""))
        outcome_ref = trial.get("outcome")
        outcome_id = outcome_ref.get("identity") if isinstance(outcome_ref, dict) else None
        terminal = next(
            (
                record
                for record in terminals
                if record.get("trial_id") == trial_id
                and (outcome_id is None or record.get("identity") == outcome_id)
            ),
            {},
        )
        result = proposal_results.get(trial_id)
        target = result.get("target", {}) if isinstance(result, dict) else {}
        reported = result.get("reported", {}) if isinstance(result, dict) else {}
        target = target if isinstance(target, dict) else {}
        reported = reported if isinstance(reported, dict) else {}

        details: list[str] = []
        if disposition != "assessed":
            details.append(f"<p>Disposition: <b>{escaped(disposition)}</b></p>")
        record_details: list[str] = []
        if result is not None:
            reported_text = reported.get("reported_text")
            if disposition != "assessed":
                details.append(
                    "<h3>Outcome</h3>"
                    f"<p><b>{escaped(target.get('outcome_definition', ''))}</b><br>"
                    f"Measurement: {escaped(target.get('measurement', ''))}<br>"
                    f"Time: {escaped(target.get('time_point_or_window', ''))}<br>"
                    "Analysis population: "
                    f"{escaped(target.get('intended_analysis_population', ''))}<br></p>"
                )
                if isinstance(reported_text, str):
                    details.append(f"<blockquote>{escaped(reported_text)}</blockquote>")
            effect = reported.get("effect")
            if isinstance(effect, dict):
                effect_text = (
                    f"{effect.get('statistic', '')}; {effect.get('group_or_category', '')}; "
                    f"{effect.get('value', '')} {effect.get('unit', '')}"
                )
                denominator = effect.get("denominator_basis")
                if denominator:
                    effect_text += f"; denominator: {denominator}"
                effect_detail = f"<p>Reported effect: {escaped(effect_text)}</p>"
                if disposition == "assessed":
                    record_details.append(effect_detail)
                else:
                    details.append(effect_detail)
            precision = reported.get("precision")
            if isinstance(precision, dict):
                interval = precision.get("confidence_interval", {})
                p_value = precision.get("p_value", {})
                if isinstance(interval, dict) or isinstance(p_value, dict):
                    interval = interval if isinstance(interval, dict) else {}
                    p_value = p_value if isinstance(p_value, dict) else {}
                    precision_detail = (
                        "<p>Reported precision: "
                        f"CI {escaped(interval.get('level', ''))}%; "
                        f"{escaped(interval.get('lower', ''))} to "
                        f"{escaped(interval.get('upper', ''))}; "
                        f"P{escaped(p_value.get('operator', ''))}"
                        f"{escaped(p_value.get('value', ''))}</p>"
                    )
                    if disposition == "assessed":
                        record_details.append(precision_detail)
                    else:
                        details.append(precision_detail)
            quantities = reported.get("quantities", reported.get("categories", []))
            if isinstance(quantities, list):
                values = [quantity_text(item) for item in quantities if isinstance(item, dict)]
                if values:
                    values_detail = f"<p>Reported values: {escaped('; '.join(values))}</p>"
                    if disposition == "assessed":
                        record_details.append(values_detail)
                    else:
                        details.append(values_detail)
            evidence = result.get("evidence", {})
            if isinstance(evidence, dict):
                evidence_ids = sorted(
                    {
                        str(reference.get("identity"))
                        for references in evidence.values()
                        if isinstance(references, list)
                        for reference in references
                        if isinstance(reference, dict) and reference.get("identity")
                    }
                )
                if evidence_ids:
                    evidence_detail = (
                        f"<p>Proposal evidence: {escaped(', '.join(evidence_ids))}</p>"
                    )
                    if disposition == "assessed":
                        record_details.append(evidence_detail)
                    else:
                        details.append(evidence_detail)

        snapshot = trial.get("snapshot")
        snapshot_id = snapshot.get("identity") if isinstance(snapshot, dict) else ""
        checkpoint_order = (
            snapshot_checkpoints.get((trial_id, str(snapshot_id)), ())
            if disposition == "assessed"
            else ()
        )
        checkpoints = _report_ordered_checkpoints(records, trial_id, checkpoint_order)
        if disposition != "assessed":
            # Keep the problem-terminal record content stable and directly sourced.
            missing = terminal.get("missing_facts", [])
            evidence = terminal.get("evidence", [])
            details.append(f"<p>Reason: {escaped(terminal.get('reason', ''))}</p>")
            details.append(
                f"<p>Missing facts: {escaped(values_text(missing) if isinstance(missing, list) else '')}</p>"
            )
            evidence_ids = [
                str(item.get("identity", "")) for item in evidence if isinstance(item, dict)
            ]
            details.append(f"<p>Evidence: {escaped(', '.join(evidence_ids))}</p>")
            acknowledgment = terminal.get("acknowledgment", {})
            if isinstance(acknowledgment, dict):
                details.append(
                    "<p>Researcher acknowledgment: "
                    f"{escaped(acknowledgment.get('identity', ''))}</p>"
                )

        result_id = (
            next(
                (
                    str(checkpoint.get("result_id"))
                    for checkpoint in checkpoints
                    if checkpoint.get("result_id")
                ),
                "",
            )
            if disposition == "assessed"
            else ""
        )
        groups = target.get("comparison_groups", [])
        group_labels = [
            str(group.get("label", ""))
            for group in groups
            if isinstance(group, dict) and group.get("label")
        ]
        outcome_definition = str(target.get("outcome_definition", ""))
        measurement = str(target.get("measurement", ""))
        time_point = str(target.get("time_point_or_window", ""))
        reported_text = reported.get("reported_text")
        effect = reported.get("effect")
        estimate = "Not reported"
        if isinstance(effect, dict):
            estimate = (
                f"{effect.get('value', '')} {effect.get('unit', '')}".strip()
                or str(effect.get("statistic", ""))
            )
        elif isinstance(reported_text, str) and reported_text:
            estimate = "Reported result"
        result_hero = (
            "<div class=\"result-hero\">"
            "<div><p class=\"eyebrow\">Reported outcome</p>"
            f"<h2>{escaped(outcome_definition or 'Result')}</h2>"
            f"<p>Measurement: {escaped(measurement)}; time point: {escaped(time_point)}.</p>"
            + (
                f"<blockquote class=\"result-quote\">{escaped(reported_text)}</blockquote>"
                if isinstance(reported_text, str)
                else ""
            )
            + (
                f"<details class=\"record-details\"><summary>Record details</summary>"
                f"{''.join(record_details)}</details>"
                if record_details
                else ""
            )
            + "</div>"
            f"<aside class=\"estimate-card\" aria-label=\"Reported result estimate\">"
            f"<span class=\"eyebrow\">{escaped(target.get('intended_effect_measure', 'Estimate'))}</span>"
            f"<strong>{escaped(estimate)}</strong>"
            + (
                f"<small>{escaped(effect.get('denominator_basis', ''))}</small>"
                if isinstance(effect, dict) and effect.get("denominator_basis")
                else ""
            )
            + "</aside></div>"
        ) if disposition == "assessed" else ""
        identity_items = [f"<div><dt>Trial</dt><dd>{escaped(trial_id)}</dd></div>"]
        if disposition == "assessed":
            identity_items.extend(
                (
                    f"<div><dt>Result</dt><dd>{escaped(result_id)}</dd></div>",
                    f"<div><dt>Disposition</dt><dd>{escaped(disposition)}</dd></div>",
                )
            )
            if group_labels:
                identity_items.append(
                    f"<div><dt>Comparison</dt><dd>{escaped(' vs. '.join(group_labels))}</dd></div>"
                )
            if target.get("effect_of_interest"):
                identity_items.append(
                    f"<div><dt>Effect of interest</dt><dd>{escaped(target.get('effect_of_interest', ''))}</dd></div>"
                )
            if target.get("intended_analysis_population"):
                identity_items.append(
                    f"<div><dt>Analysis population</dt><dd>{escaped(target.get('intended_analysis_population', ''))}</dd></div>"
                )
            identity_items.append(
                f"<div><dt>Assessment snapshot</dt><dd><code>{escaped(snapshot_id)}</code></dd></div>"
            )
        else:
            identity_items.append(f"<div><dt>Disposition</dt><dd>{escaped(disposition)}</dd></div>")
        identity_grid = f"<dl class=\"identity-grid\">{''.join(identity_items)}</dl>"
        trial_header = (
            "<header class=\"report-header trial-header\">"
            f"<p class=\"eyebrow\">Trial record</p>{identity_grid}</header>"
        )
        if disposition == "assessed":
            snapshot_record = next(
                (
                    record
                    for record in records
                    if record.get("kind") == "assessment_snapshot"
                    and record.get("trial_id") == trial_id
                    and record.get("identity") == snapshot_id
                ),
                {},
            )
            overall = snapshot_record.get("final_judgment") or snapshot_record.get(
                "proposed_overall", ""
            )
            if isinstance(overall, dict):
                overall = overall.get("judgment", "")
            overall_text = str(overall)
            domain_rail = [
                "<nav class=\"domain-rail\" aria-label=\"Domain navigation\"><h2>Domains</h2><ol>"
            ]
            domain_sections: list[str] = []
            for number, checkpoint in enumerate(checkpoints, 1):
                nav, domain = _report_domain(checkpoint, trial_number, number)
                domain_rail.append(nav)
                domain_sections.append(domain)
            domain_rail.append("</ol></nav>")
            audit = (
                "<div class=\"audit-summary\">"
                "<span><strong>Overall risk-of-bias judgment:</strong> "
                f"<span class=\"judgment judgment-{judgment_class(overall_text)}\">"
                f"{escaped(overall_text or 'not recorded')}</span></span>"
                f"<span class=\"summary-count\">{len(checkpoints)} domains assessed</span>"
                "</div>"
            )
            assessed_content = (
                audit
                + "<div class=\"report-layout\">"
                + "".join(domain_rail)
                + f"<div>{''.join(domain_sections)}</div></div>"
            )
        else:
            assessed_content = f"<div class=\"diagnostic\">{''.join(details)}</div>"
        sections.append(
            f"<section><h2>{escaped(trial_id)}</h2><div class=\"trial-report\" data-trial-id=\"{escaped(trial_id)}\">"
            + trial_header
            + result_hero
            + assessed_content
            + "</div></section>"
        )
    presentation = summary.get("presentation", {})
    headline = presentation.get("headline", "") if isinstance(presentation, dict) else ""
    message = presentation.get("summary", "") if isinstance(presentation, dict) else ""
    code = presentation.get("code", "") if isinstance(presentation, dict) else ""
    approved_summary = summary.get("approved_batch", {})
    approved_summary_id = (
        approved_summary.get("identity", "") if isinstance(approved_summary, dict) else ""
    )
    style = """
<style>
:root{color-scheme:light;font-family:system-ui,sans-serif;color:#17322d;background:#f7f4ed}
body{margin:0;line-height:1.5}main{max-width:90rem;margin:auto;padding:1rem}
h1,h2,h3{font-family:Georgia,serif}.report-header,.result-hero,.audit-summary,.domain,.question,.diagnostic{border:1px solid #c9c5ba;border-radius:.5rem;background:#fffdf8;padding:1rem;margin:1rem 0}
.report-header h1,.report-header h2{margin-top:0}.identity-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:.75rem}.identity-grid div{border-left:.25rem solid #40645a;padding-left:.5rem}.identity-grid dt{font-weight:700}.identity-grid dd{margin:0;overflow-wrap:anywhere}
.result-hero{display:flex;justify-content:space-between;gap:1.5rem;align-items:stretch}.result-hero>div{min-width:0}.estimate-card{min-width:12rem;display:flex;flex-direction:column;justify-content:center;padding:1rem;border-left:.25rem solid #9a5a12;background:#fff4dc}.estimate-card strong{font:1.7rem Georgia,serif}.estimate-card small{margin-top:.35rem}.eyebrow{font-size:.84rem;text-transform:uppercase;letter-spacing:.06em;color:#53635e}.result-quote,blockquote{margin-left:0;padding-left:.75rem;border-left:.2rem solid #777;white-space:pre-wrap}
.audit-summary{position:sticky;top:.25rem;z-index:4;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}.summary-count{color:#53635e;font-size:.9rem}.judgment{display:inline-block;padding:.25rem .5rem;border-radius:.25rem}.judgment-low{background:#dcefe3}.judgment-some_concerns{background:#fff0c9}.judgment-high{background:#f9ddd8}.judgment-none{background:#e4e7e5}
.report-layout{display:grid;grid-template-columns:minmax(15rem,18rem) minmax(0,1fr);gap:1rem;align-items:start}.domain-rail{position:sticky;top:5rem;border:1px solid #c9c5ba;border-radius:.5rem;background:#fffdf8;padding:.75rem}.domain-rail h2{font-size:1.15rem;margin-top:.25rem}.domain-rail ol{padding:0;margin:0;list-style:none}.domain-rail li+li{margin-top:.35rem}.domain-rail a{display:grid;grid-template-columns:1.7rem minmax(0,1fr);gap:.55rem;align-items:center;padding:.5rem;border-radius:.4rem;text-decoration:none;color:inherit}.domain-rail a:hover,.domain-rail a:focus-visible{background:#e4ede8}.domain-rail .judgment{grid-column:2;font-size:.7rem;padding:0;margin:0;background:transparent}.domain-number{display:grid;place-items:center;width:1.55rem;height:1.55rem;color:#fff;background:#40645a;border-radius:50%;font-weight:700}.domain-evidence{grid-column:2;overflow-wrap:anywhere}
.domain-meta,.provenance,.evidence-identity{font-size:.9rem;overflow-wrap:anywhere}.questions{margin-top:1rem}.question{margin:1rem 0}.question h3{margin-top:0}.evidence{border-left:.3rem solid #40645a;padding:.5rem 1rem;margin:.75rem 0;background:#f7f4ed}.evidence.contradicting{border-color:#9c3226}.evidence.contextual,.evidence.residual{border-color:#9a5a12}.evidence.other{border-color:#53635e}.evidence-list{margin-top:1rem}.evidence-list article h4{margin:.2rem 0}.evidence-identity{color:#53635e}.unresolved-evidence{border-left:.3rem solid #9a5a12;padding:.5rem 1rem;background:#fff4dc;overflow-wrap:anywhere}
code{overflow-wrap:anywhere}a{color:#064c87}a:focus-visible,summary:focus-visible{outline:.2rem solid #9a5a12;outline-offset:.2rem}summary{cursor:pointer;font-weight:700}
@media(max-width:58rem){.report-layout{grid-template-columns:1fr}.domain-rail{position:static}.domain-rail ol{display:flex;overflow-x:auto;gap:.35rem}.domain-rail li{min-width:13rem}.result-hero{flex-direction:column}}
@media print{body{background:#fff;color:#000}main{max-width:none}.domain-rail{display:none}.report-layout{display:block}.audit-summary{position:static;box-shadow:none}details,details[open]{display:block}details>* ,details:not([open])>*{display:block}details>summary{display:none}.report-header,.audit-summary,.domain,.question,.diagnostic{break-inside:avoid;box-shadow:none}a{color:inherit;text-decoration:none}}
</style>
"""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>RoB 2 batch report</title>"
        + style
        + "</head><body><main>"
        + "<header class=\"report-header\"><h1>RoB 2 batch report</h1>"
        + f"<p>{escaped(headline)}</p><p>{escaped(message)}</p>"
        + "<dl class=\"identity-grid\">"
        + f"<div><dt>Presentation code</dt><dd><code>{escaped(code)}</code></dd></div>"
        + f"<div><dt>Summary identity</dt><dd><code>{escaped(summary.get('identity', ''))}</code></dd></div>"
        + f"<div><dt>Approved batch</dt><dd><code>{escaped(approved_summary_id)}</code></dd></div>"
        + f"<div><dt>Proposal review</dt><dd><code>{escaped(proposal_id or '')}</code></dd></div>"
        + "<div><dt>Artifact integrity</dt><dd><code>manifest.json</code> binds the exact report and bundle files.</dd></div>"
        + "</dl></header>"
        + "".join(sections)
        + "</main></body></html>"
    )


def _receipt_files(target: Path) -> list[tuple[str, bytes]]:
    """Capture the exact regular-file bytes authenticated by one receipt."""
    files = []
    for path in target.rglob("*"):
        if _redirected(path):
            raise ValueError("batch artifact path is redirected")
        if path.is_file():
            files.append((path.relative_to(target).as_posix(), path.read_bytes()))
    return files


def _safe_child(parent: Path, name: str) -> Path:
    path = parent / name
    if path.parent != parent or _redirected(path):
        raise ValueError("assessment output path is redirected")
    return path


def _complete_bundle(path: Path, data: bytes, snapshot: AssessmentSnapshot) -> bool:
    try:
        if _redirected(path) or not path.is_dir():
            return False
        assessment = path / "assessment.json"
        report = path / "report.html"
        projections = path / "projections.json"
        sources = path / "sources"
        assets = path / "assets"
        if (
            any(_redirected(item) for item in (assessment, report, projections, sources, assets))
            or not assessment.is_file()
            or not report.is_file()
            or not projections.is_file()
            or not sources.is_dir()
            or not assets.is_dir()
            or assessment.read_bytes() != data
        ):
            return False
        for source in snapshot.sources:
            copied = sources / f"{source.id}{Path(source.captured_path).suffix}"
            if (
                _redirected(copied)
                or not copied.is_file()
                or sha256_bytes(copied.read_bytes()) != source.sha256
            ):
                return False
        if projections.read_bytes() != _projection_bytes(
            path.parents[2], snapshot.sources, VerifiedProjection(path.parents[2])
        ):
            return False
        return True
    except OSError:
        return False


def _recover(
    parent: Path, target: Path, backup: Path, data: bytes, snapshot: AssessmentSnapshot
) -> None:
    pattern = re.compile(rf"\.{re.escape(target.name)}-stage-[a-z0-9_]+")
    for item in parent.iterdir():
        if item.name.startswith(f".{target.name}-stage-"):
            if not pattern.fullmatch(item.name) or _redirected(item) or not item.is_dir():
                raise ValueError("ambiguous assessment staging residue")
            shutil.rmtree(item)
    target_valid = target.exists() and _complete_bundle(target, data, snapshot)
    backup_valid = backup.exists() and _complete_bundle(backup, data, snapshot)
    if target.exists() and backup.exists():
        if target_valid:
            shutil.rmtree(backup)
        elif backup_valid:
            shutil.rmtree(target)
            backup.replace(target)
        else:
            raise ValueError("assessment residue cannot be verified")
    elif not target.exists() and backup.exists():
        if not backup_valid:
            raise ValueError("assessment backup cannot be verified")
        backup.replace(target)
    elif target.exists() and not target_valid:
        raise ValueError("assessment target cannot be verified")


def _snapshot_bytes(workspace: Path, trial_id: str, result_id: str) -> bytes:
    with transaction(workspace) as connection:
        rows = connection.execute("SELECT name,payload FROM records").fetchall()
    matches = []
    for name, payload in rows:
        if not str(name).startswith("assessment_snapshot:"):
            continue
        snapshot = AssessmentSnapshot.model_validate_json(bytes(payload))
        if snapshot.trial.id == trial_id and snapshot.result_spec.id == result_id:
            matches.append(bytes(payload))
    if len(matches) != 1:
        raise ValueError("exact committed Trial ResultSpec snapshot is required")
    _verified(AssessmentSnapshot.model_validate_json(matches[0]))
    return matches[0]


def _text_ref(
    root: Path,
    sources: dict[str, Source],
    ref: TextEvidenceRef,
    projection: VerifiedProjection,
) -> str:
    source = sources[ref.source_id]
    page = projection.pages(source, canonical_projection_identity(root, source))[
        ref.page_number - 1
    ]
    if source.sha256 != ref.source_sha256 or page[ref.start : ref.end] != ref.quote:
        raise ValueError("text citation no longer matches committed captured source")
    before, after = page[max(0, ref.start - 120) : ref.start], page[ref.end : ref.end + 120]
    return (
        f"<code>{html.escape(ref.source_id)} p.{ref.page_number} [{ref.start}:{ref.end}]</code> "
        f"<span>{html.escape(before)}<mark>{html.escape(ref.quote)}</mark>{html.escape(after)}</span>"
    )


def _projection_bytes(
    root: Path, sources: tuple[Source, ...], projection: VerifiedProjection
) -> bytes:
    identities = []
    for source in sources:
        identity = canonical_projection_identity(root, source)
        pages = projection.pages(source, identity)
        if reproduce_projection_identity(
            source.model_dump(mode="json"), pages
        ) != identity.model_dump(mode="json"):
            raise ValueError("independent Text projection reproduction failed")
        identities.append(identity.model_dump(mode="json"))
    return canonical_json_bytes(
        {"schema": "rob2-kit.text-projection-identities.v1", "projections": identities}
    )


def _visual_ref(
    root: Path, assets: Path, sources: dict[str, Source], ref: VisualEvidenceRef
) -> str:
    source = sources[ref.source_id]
    rendered = render_page(
        root, source, ref.page_number, None if ref.origin.value == "rendered_page" else ref.region
    )
    if not isinstance(rendered, RenderedPage) or rendered.sha256 != ref.image_sha256:
        raise ValueError("visual citation no longer matches committed render")
    name = f"{ref.image_sha256.removeprefix('sha256:')}.png"
    (assets / name).write_bytes(rendered.image_bytes)
    return (
        f'<figure><img src="assets/{name}" alt="{html.escape(ref.transcription)}">'
        f"<figcaption>{html.escape(ref.origin)} p.{ref.page_number}: {html.escape(ref.transcription)}</figcaption></figure>"
    )


def _report(
    root: Path,
    snapshot: AssessmentSnapshot,
    stage: Path,
    projection: VerifiedProjection | None = None,
) -> bytes:
    sources = {source.id: source for source in snapshot.sources}
    projection = projection or VerifiedProjection(root)
    assets = stage / "assets"
    assets.mkdir()
    domains = []
    for judgment in snapshot.domain_judgments:
        answers = []
        for answer in judgment.active_answers:
            uses = []
            for use in answer.evidence_uses:
                refs = []
                for ref in use.refs:
                    refs.append(
                        _text_ref(root, sources, ref, projection)
                        if ref.kind == "text"
                        else _visual_ref(root, assets, sources, ref)
                    )
                uses.append(
                    f"<li><b>{html.escape(use.relationship)}</b>: {html.escape(use.claim)} — {html.escape(use.rationale)}<br>{''.join(refs)}</li>"
                )
            answers.append(
                f"<li>{html.escape(answer.question_id)} = {html.escape(answer.answer)} — {html.escape(answer.rationale)}<ul>{''.join(uses)}</ul></li>"
            )
        domains.append(
            f"<details open><summary>{html.escape(judgment.domain_id)}: {html.escape(judgment.final_judgment)}</summary>"
            f"<p>Proposed: {html.escape(judgment.proposed_judgment)}; trace: {html.escape(', '.join(judgment.trace))}</p>"
            f"<ul>{''.join(answers)}</ul><p>Inactive: {html.escape(', '.join(q.question_id for q in judgment.inactive_questions))}</p>"
            f"<p>Limitations: {html.escape(', '.join(judgment.limitations))}; actor: {html.escape(judgment.actor)}; time: {judgment.observed_at.isoformat()}</p></details>"
        )
    audit = {
        "batch": snapshot.approved_batch_hash,
        "snapshot": snapshot.snapshot_hash,
        "packs": [pack.model_dump(mode="json") for pack in snapshot.pack_identities],
        "sources": [source.model_dump(mode="json") for source in snapshot.sources],
        "result_spec": snapshot.result_spec.model_dump(mode="json"),
    }
    body = (
        "<!doctype html><meta charset=utf-8><title>RoB 2 assessment</title>"
        "<style>@media print{details{display:block}}body{font:16px sans-serif;max-width:960px;margin:auto}img{max-width:100%}details{margin:1em 0}</style>"
        f"<h1>{html.escape(snapshot.trial.label)}</h1><p>Overall proposed: {html.escape(snapshot.proposed_overall.judgment)}; final: {html.escape(snapshot.final_judgment)}</p>"
        f"<p>Override: {html.escape(snapshot.override.justification if snapshot.override else '')}; limitations: {html.escape(', '.join(snapshot.limitations))}; actor: {html.escape(snapshot.actor)}; time: {snapshot.observed_at.isoformat()}</p>"
        + "".join(domains)
        + f"<h2>Canonical audit</h2><pre>{html.escape(str(audit))}</pre>"
    )
    return body.encode()


def export_trial(workspace: str | Path, trial_id: str, result_id: str) -> Path:
    """Materialize a standalone bundle from the committed canonical snapshot bytes only."""
    root = Path(workspace).resolve(strict=True)
    data = _snapshot_bytes(root, trial_id, result_id)
    snapshot = _verified(AssessmentSnapshot.model_validate_json(data))
    return export_verified_snapshot(root, data, snapshot)


def export_verified_snapshot(root: Path, data: bytes, snapshot: AssessmentSnapshot) -> Path:
    """Publish a bundle after a caller has verified frozen approval identities."""
    root = root.resolve(strict=True)
    if _verified(AssessmentSnapshot.model_validate_json(data)) != snapshot:
        raise ValueError("snapshot bytes do not match verified snapshot")
    trial_id = snapshot.trial.id
    parent = root / ".rob2-kit" / "assessments"
    parent.mkdir(parents=True, exist_ok=True)
    if _redirected(parent):
        raise ValueError("assessment output directory is redirected")
    backup = _safe_child(parent, f".{trial_id}-backup")
    target = _safe_child(parent, trial_id)
    _recover(parent, target, backup, data, snapshot)
    stage = Path(tempfile.mkdtemp(prefix=f".{trial_id}-stage-", dir=parent))
    try:
        (stage / "assessment.json").write_bytes(data)
        projection = VerifiedProjection(root)
        (stage / "projections.json").write_bytes(
            _projection_bytes(root, snapshot.sources, projection)
        )
        source_dir = stage / "sources"
        source_dir.mkdir()
        for source in snapshot.sources:
            source_data = verified_source_bytes(root, source)
            if sha256_bytes(source_data) != source.sha256:
                raise ValueError("source copy does not match committed source hash")
            (source_dir / f"{source.id}{Path(source.captured_path).suffix}").write_bytes(
                source_data
            )
        (stage / "report.html").write_bytes(_report(root, snapshot, stage, projection))
        if target.exists():
            if backup.exists():
                raise ValueError("assessment backup already exists")
            target.replace(backup)
        try:
            stage.replace(target)
        except BaseException:
            if backup.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return target
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise


def _batch_index(summary: BatchSummary) -> str:
    links = []
    for entry in summary.entries:
        if entry.status == "assessed":
            links.append(
                f'<li>{html.escape(entry.trial.id)}: <a href="trials/{html.escape(entry.trial.id)}/report.html">'
                f"assessed</a>; result {html.escape(entry.result_spec.id)}; "
                f"judgments {html.escape(', '.join(entry.judgments))}; "
                f"limitations {html.escape(', '.join(entry.limitations))}; "
                f"snapshot {html.escape(entry.snapshot_hash)}</li>"
            )
        else:
            links.append(
                f"<li>{html.escape(entry.trial.id)}: {html.escape(entry.status)} — "
                f"{html.escape(str([problem.model_dump(mode='json') for problem in entry.problems]))}</li>"
            )
    return (
        "<!doctype html><meta charset=utf-8><title>RoB 2 batch</title>"
        + f"<h1>{html.escape(summary.outcome_target.label)}</h1>"
        + f"<p>{html.escape(summary.outcome_target.description)}</p>"
        + f"<p>{html.escape(str(summary.counts.model_dump()))}</p><ul>{''.join(links)}</ul>"
        + "<h2>Canonical provenance</h2><pre>"
        + html.escape(
            str(
                {
                    "approved_batch_hash": summary.approved_batch_hash,
                    "summary_hash": summary.summary_hash,
                    "pack_identities": [
                        item.model_dump(mode="json") for item in summary.pack_identities
                    ],
                }
            )
        )
        + "</pre>"
    )


def _batch_bundle_complete(root: Path, path: Path, data: bytes, summary: BatchSummary) -> bool:
    """Accept only the exact self-contained tree derivable from committed records."""
    try:
        if _redirected(path) or not path.is_dir():
            return False
        summary_path = path / "batch-summary.json"
        index_path = path / "index.html"
        if (
            _redirected(summary_path)
            or _redirected(index_path)
            or not summary_path.is_file()
            or not index_path.is_file()
            or summary_path.read_bytes() != data
        ):
            return False
        items = tuple(path.rglob("*"))
        if any(_redirected(item) for item in items):
            return False
        expected = {Path("batch-summary.json"), Path("index.html")}
        assessed = [entry for entry in summary.entries if entry.status == "assessed"]
        if assessed:
            expected.add(Path("trials"))
        index = index_path.read_text(encoding="utf-8")
        if index != _batch_index(summary):
            return False
        for entry in assessed:
            trial_dir = Path("trials") / entry.trial.id
            trial_path = path / trial_dir
            trials_path = path / "trials"
            if (
                _redirected(trials_path)
                or _redirected(trial_path)
                or not trials_path.is_dir()
                or not trial_path.is_dir()
            ):
                return False
            snapshot_data = _snapshot_bytes(root, entry.trial.id, entry.result_spec.id)
            snapshot = _verified(AssessmentSnapshot.model_validate_json(snapshot_data))
            if snapshot.snapshot_hash != entry.snapshot_hash:
                return False
            projection = VerifiedProjection(root)
            expected.update(
                {
                    trial_dir,
                    trial_dir / "assessment.json",
                    trial_dir / "report.html",
                    trial_dir / "projections.json",
                    trial_dir / "sources",
                    trial_dir / "assets",
                }
            )
            assessment_path = trial_path / "assessment.json"
            report_path = trial_path / "report.html"
            projections_path = trial_path / "projections.json"
            sources_path = trial_path / "sources"
            assets_path = trial_path / "assets"
            if any(
                _redirected(item)
                for item in (
                    assessment_path,
                    report_path,
                    projections_path,
                    sources_path,
                    assets_path,
                )
            ) or not all(
                (
                    assessment_path.is_file(),
                    report_path.is_file(),
                    projections_path.is_file(),
                    sources_path.is_dir(),
                    assets_path.is_dir(),
                )
            ):
                return False
            if assessment_path.read_bytes() != snapshot_data:
                return False
            if projections_path.read_bytes() != _projection_bytes(
                root, snapshot.sources, projection
            ):
                return False
            with tempfile.TemporaryDirectory() as directory:
                if report_path.read_bytes() != _report(root, snapshot, Path(directory), projection):
                    return False
            if f'href="trials/{entry.trial.id}/report.html"' not in index:
                return False
            for source in snapshot.sources:
                relative = trial_dir / "sources" / f"{source.id}{Path(source.captured_path).suffix}"
                source_path = path / relative
                if (
                    _redirected(source_path)
                    or not source_path.is_file()
                    or sha256_bytes(source_path.read_bytes()) != source.sha256
                ):
                    return False
                expected.add(relative)
            for judgment in snapshot.domain_judgments:
                for answer in judgment.active_answers:
                    for use in answer.evidence_uses:
                        for ref in use.refs:
                            if ref.kind == "visual":
                                relative = (
                                    trial_dir
                                    / "assets"
                                    / f"{ref.image_sha256.removeprefix('sha256:')}.png"
                                )
                                asset_path = path / relative
                                if (
                                    _redirected(asset_path)
                                    or not asset_path.is_file()
                                    or sha256_bytes(asset_path.read_bytes()) != ref.image_sha256
                                ):
                                    return False
                                expected.add(relative)
        actual = {item.relative_to(path) for item in items}
        return actual == expected
    except (OSError, ValueError):
        return False


def batch_artifact_receipt(root: Path, target: Path, summary: BatchSummary) -> ArtifactReceipt:
    """Return a receipt only for the exact standalone bundle derived from ``summary``.

    The bundle hash is SHA-256 over lexical POSIX-relative file paths, each followed
    by a NUL byte, then its exact bytes and a NUL byte.  This binds both names and
    contents without depending on filesystem traversal order.
    """
    from rob2_kit.batch_summary import AssessmentTerminal, ProblemTerminal, verified_terminal

    root = root.resolve(strict=True)
    if _redirected(root):
        raise ValueError("workspace root is redirected")
    try:
        relative_target = target.relative_to(root)
    except ValueError as error:
        raise ValueError("batch artifact path escapes workspace") from error
    current = root
    for part in relative_target.parts:
        current = current / part
        if _redirected(current):
            raise ValueError("batch artifact path is redirected")
    if not target.exists() or not target.is_dir():
        raise ValueError("batch artifact is missing")
    resolved_target = target.resolve(strict=True)
    try:
        resolved_target.relative_to(root)
    except ValueError as error:
        raise ValueError("batch artifact path escapes workspace") from error
    with transaction(root) as connection:
        for entry in summary.entries:
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"terminal_trial:{summary.approved_batch_hash}:{entry.trial.id}",),
            ).fetchone()
            if row is None:
                raise ValueError("batch artifact terminal basis is unavailable")
            raw = bytes(row[0])
            if entry.status == "assessed":
                marker = AssessmentTerminal.model_validate_json(raw)
                if marker.snapshot_hash != entry.snapshot_hash:
                    raise ValueError("batch artifact assessment status is not cross-bound")
            else:
                terminal = verified_terminal(ProblemTerminal.model_validate_json(raw))
                if (
                    terminal.category != entry.status
                    or terminal.terminal_hash != entry.terminal_hash
                ):
                    raise ValueError("batch artifact problem status is not cross-bound")
    data = (target / "batch-summary.json").read_bytes()
    committed = verified_summary(BatchSummary.model_validate_json(data))
    if committed != summary or not _batch_bundle_complete(root, target, data, summary):
        raise ValueError("batch artifact cannot be verified")
    files = _receipt_files(target)
    contents = dict(files)
    if contents.get("batch-summary.json") != data:
        raise ValueError("batch artifact changed while capturing receipt")
    index = contents.get("index.html")
    if index is None:
        raise ValueError("batch artifact is missing its index")
    return ArtifactReceipt(
        bundle_path=relative_target.as_posix(),
        bundle_hash=_bundle_hash(files),
        file_count=len(files),
        summary_hash=summary.summary_hash,
        index_hash=sha256_bytes(index),
    )


def export_batch(workspace: str | Path, approved_batch_hash: str) -> Path:
    """Materialize the committed BatchSummary and its assessed Trial bundles."""
    root = Path(workspace).resolve(strict=True)
    with workspace_mutation_lock(root):
        return _export_batch(root, approved_batch_hash)


def _export_batch(root: Path, approved_batch_hash: str) -> Path:
    with transaction(root) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (f"batch_summary:{approved_batch_hash}",)
        ).fetchone()
    if row is None:
        raise ValueError("batch summary is not committed")
    data = row[0] if isinstance(row[0], bytes) else str(row[0]).encode()
    summary = verified_summary(BatchSummary.model_validate_json(data))
    parent = root / ".rob2-kit" / "batches"
    parent.mkdir(parents=True, exist_ok=True)
    if _redirected(parent):
        raise ValueError("batch output directory is redirected")
    name = approved_batch_hash.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", name):
        raise ValueError("invalid approved batch hash")
    target = _safe_child(parent, name)
    backup = _safe_child(parent, f".{name}-backup")

    def complete(path: Path) -> bool:
        return _batch_bundle_complete(root, path, data, summary)

    # A prior interrupted publish is recoverable only when its committed summary is exact.
    for residue in parent.glob(f".{name}-stage-*"):
        if (
            re.fullmatch(rf"\.{re.escape(name)}-stage-[a-z0-9_]+", residue.name) is None
            or _redirected(residue)
            or not residue.is_dir()
        ):
            raise ValueError("ambiguous batch staging residue")
        shutil.rmtree(residue)
    if target.exists() and backup.exists():
        if complete(target):
            shutil.rmtree(backup)
        else:
            raise ValueError("batch publication residue cannot be verified")
    elif backup.exists() and not target.exists():
        if not complete(backup):
            raise ValueError("batch backup cannot be verified")
        backup.replace(target)
    elif target.exists() and not complete(target):
        raise ValueError("batch target cannot be verified")
    stage = Path(tempfile.mkdtemp(prefix=f".{name}-stage-", dir=parent))
    try:
        (stage / "batch-summary.json").write_bytes(data)
        for entry in summary.entries:
            if entry.status != "assessed":
                continue
            trial_id = entry.trial.id
            snapshot_data = _snapshot_bytes(root, trial_id, entry.result_spec.id)
            snapshot = _verified(AssessmentSnapshot.model_validate_json(snapshot_data))
            if snapshot.snapshot_hash != entry.snapshot_hash:
                raise ValueError("summary assessment entry does not match committed snapshot")
            destination = stage / "trials" / trial_id
            destination.parent.mkdir(exist_ok=True)
            destination.mkdir()
            (destination / "assessment.json").write_bytes(snapshot_data)
            projection = VerifiedProjection(root)
            (destination / "projections.json").write_bytes(
                _projection_bytes(root, snapshot.sources, projection)
            )
            sources = destination / "sources"
            sources.mkdir()
            for source in snapshot.sources:
                source_data = verified_source_bytes(root, source)
                if sha256_bytes(source_data) != source.sha256:
                    raise ValueError("source copy does not match committed source hash")
                (sources / f"{source.id}{Path(source.captured_path).suffix}").write_bytes(
                    source_data
                )
            (destination / "report.html").write_bytes(
                _report(root, snapshot, destination, projection)
            )
        (stage / "index.html").write_text(_batch_index(summary), encoding="utf-8")
        if not complete(stage):
            raise ValueError("staged batch bundle cannot be verified")
        if target.exists():
            if backup.exists():
                raise ValueError("batch backup already exists")
            target.replace(backup)
        try:
            stage.replace(target)
        except BaseException:
            if backup.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return target
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
