"""Assessment report: the reviewer-facing HTML view of one verified bundle.

The report is presentation only. It is rendered from a bundle that verifies,
carries no integrity of its own and can be regenerated at any time. A Batch
page summarizes every Trial and links to one Trial page per Trial.
"""

from __future__ import annotations

import base64
import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from rob2_kit import __version__
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs import SCIENTIFIC_PACK

# Bundles that carry a report-format marker share the canonical shape rendered
# here; earlier bundles predate it.
_RENDERABLE_FORMATS = {"rob2-kit.human-report.v1", "none"}

_DOMAINS = (
    ("domain:randomization", "D1", "Bias arising from the randomization process"),
    ("domain:deviations", "D2", "Bias due to deviations from intended interventions"),
    ("domain:missing", "D3", "Bias due to missing outcome data"),
    ("domain:measurement", "D4", "Bias in measurement of the outcome"),
    ("domain:selection", "D5", "Bias in selection of the reported result"),
)
_JUDGMENTS = {
    "low": ("Low risk", "✓", "low"),
    "some_concerns": ("Some concerns", "!", "concerns"),
    "high": ("High risk", "✗", "high"),
}
_ANSWERS = {
    "yes": "Yes",
    "probably_yes": "Probably yes",
    "probably_no": "Probably no",
    "no": "No",
    "no_information": "No information",
}
_OVERALL_RULES = {
    "overall.all_low": "Low risk of bias in every domain.",
    "overall.any_concerns": "Some concerns in at least one domain and no domain at high risk.",
    "overall.any_high": "High risk of bias in at least one domain.",
    "overall.multiple_some_concerns_high": (
        "Some concerns in several domains that together substantially lower confidence "
        "in the result."
    ),
    "overall.cumulative_concerns_high": (
        "Some concerns in several domains that together substantially lower confidence "
        "in the result."
    ),
}
_DISPOSITIONS = {
    "needs_input": "Not assessed: needs information",
    "unsupported_design": "Not assessed: design not covered by RoB 2 for parallel trials",
    "failed": "Not assessed: assessment failed",
}


def write_report(bundle: str | Path, output: str | Path) -> Path:
    """Render a verified bundle into ``output``; return the Batch page path."""
    bundle = Path(bundle)
    diagnostic: dict[str, object] = {}
    if not verify_bundle(bundle, diagnostic=diagnostic):
        reason = diagnostic.get("detail") or "the bundle could not be read as a rob2-kit bundle"
        raise ValueError(f"bundle verification failed: {bundle}: {reason} No report was written.")
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        identity = json.loads(archive.read("manifest.json"))["identity"]
        images = {
            name: archive.read(name) for name in archive.namelist() if name.startswith("visual/")
        }
    if canonical.get("report_format") not in _RENDERABLE_FORMATS:
        raise ValueError(
            "this bundle was made by an earlier rob2-kit; reports need the current bundle format"
        )
    view = _View(canonical, identity, images)
    output = Path(output)
    (output / "trials").mkdir(parents=True, exist_ok=True)
    for trial in view.trials:
        page = output / "trials" / f"{trial['id']}.html"
        page.write_text(view.trial_page(trial), encoding="utf-8")
    index = output / "index.html"
    index.write_text(view.batch_page(), encoding="utf-8")
    return index


def report_directory(workspace: Path, bundle: str | Path) -> Path:
    """The default report folder: ``reports/<finalization date>-<short bundle id>``."""
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        identity = json.loads(archive.read("manifest.json"))["identity"]
    date = _finalized_on(canonical)
    short = identity.removeprefix("sha256:")[:12]
    return workspace / "reports" / (f"{date}-{short}" if date else short)


def _finalized_on(canonical: dict[str, Any]) -> str | None:
    stamps: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "observed_at" and isinstance(child, str):
                    stamps.append(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(canonical)
    return max(stamps)[:10] if stamps else None


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pill(judgment: str | None, *, large: bool = False) -> str:
    label, symbol, css = _JUDGMENTS.get(judgment or "", ("Not assessed", "?", "none"))
    size = " pill-lg" if large else ""
    return (
        f'<span class="pill {css}{size}" title="{_e(label)}">'
        f'<span class="dot" aria-hidden="true">{symbol}</span>{_e(label)}</span>'
    )


def _dot(judgment: str | None) -> str:
    label, symbol, css = _JUDGMENTS.get(judgment or "", ("Not assessed", "", "none"))
    return f'<span class="dot {css}" title="{_e(label)}" aria-label="{_e(label)}">{symbol}</span>'


class _View:
    def __init__(self, canonical: dict[str, Any], identity: str, images: dict[str, bytes]):
        self.canonical = canonical
        self.identity = identity
        self.images = images
        self.evidence: dict[str, dict[str, Any]] = canonical["proposal"]["evidence"]
        self.by_handle = {item.get("handle"): identity for identity, item in self.evidence.items()}
        self.results = {
            item["trial_id"]: item for item in canonical["proposal"]["payload"]["results"]
        }
        self.trials: list[dict[str, Any]] = sorted(
            canonical["batch"]["trials"], key=lambda trial: trial["label"].casefold()
        )
        self.sources = {
            source["id"]: source for trial in self.trials for source in trial.get("sources", [])
        }
        self.registry_urls = {
            source["id"]: trial["registry"]["url"]
            for trial in self.trials
            for source in trial.get("sources", [])
            if source.get("role") == "registry" and (trial.get("registry") or {}).get("url")
        }
        self.dispositions: dict[str, str] = canonical.get("dispositions", {})
        self.reviews: dict[str, dict[str, Any]] = canonical.get("trial_reviews", {})
        self.snapshots: dict[str, dict[str, Any]] = canonical.get("snapshots", {})
        self.questions = {question.id: question for question in SCIENTIFIC_PACK.questions}
        provenance = SCIENTIFIC_PACK.provenance
        self.guidance_version = getattr(provenance, "version", "")
        self.finalized_on = _finalized_on(canonical)
        self.outcome = next(
            (
                trial.get("requested_outcome")
                for trial in self.trials
                if trial.get("requested_outcome")
            ),
            "",
        )

    # -- shared page frame ----------------------------------------------------

    def _page(self, title: str, body: str, *, root: str) -> str:
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
            f'<header class="masthead"><div class="wrap"><a class="brand" href="{root}index.html">'
            '<span class="mark" aria-hidden="true">RoB&nbsp;2</span>Risk of bias assessment</a>'
            f'<span class="meta">{_e(self.outcome)}</span></div></header>'
            f'<main class="wrap">{body}</main>'
            f'<footer class="wrap footer">{self._provenance()}</footer>'
            "</body></html>"
        )

    def _provenance(self) -> str:
        date = f" on {_e(self.finalized_on)}" if self.finalized_on else ""
        return (
            f"<p>Rendered by rob2-kit {_e(__version__)} from finalized bundle "
            f"<code>{_e(self.identity.removeprefix('sha256:')[:16])}</code>{date}, which passed "
            "verification when this report was made. The bundle, not this page, is the record; "
            "verify it with <code>rob2 verify</code>.</p>"
            "<p>Signalling questions and algorithms: RoB 2 for individually randomized "
            f"parallel-group trials, version of {_e(self.guidance_version)}, reproduced with "
            "permission.</p>"
        )

    def _meta(self) -> str:
        items = [
            f"Finalized {_e(self.finalized_on)}" if self.finalized_on else "",
            f"Bundle <code>{_e(self.identity.removeprefix('sha256:')[:12])}</code>",
            f"rob2-kit {_e(__version__)}",
            f"RoB 2 guidance of {_e(self.guidance_version)}",
        ]
        return '<p class="meta-line">' + " · ".join(item for item in items if item) + "</p>"

    def _notice(self) -> str:
        return (
            '<aside class="notice"><strong>Produced by an AI assessor.</strong> The answers, '
            "justifications and quotations were written by an AI model working through "
            "rob2-kit; the domain and overall judgments follow from those answers by the "
            "official RoB 2 algorithms. A reviewer must check every judgment before relying "
            'on it.<br><span class="cite">RoB 2: Sterne JAC, Savović J, Page MJ, et al. '
            "RoB 2: a revised tool for assessing risk of bias in randomised trials. "
            "<i>BMJ</i> 2019;366:l4898.</span></aside>"
        )

    # -- Batch page -------------------------------------------------------------

    def batch_page(self) -> str:
        counts: dict[str, int] = {}
        for trial in self.trials:
            disposition = self.dispositions.get(trial["id"], "pending")
            counts[disposition] = counts.get(disposition, 0) + 1
        summary = ", ".join(
            f"{count} {name.replace('_', ' ')}" for name, count in sorted(counts.items())
        )
        head_cells = "".join(
            f'<th class="d" scope="col" title="{_e(title)}">{code}</th>'
            for _id, code, title in _DOMAINS
        )
        rows = "".join(self._batch_row(trial) for trial in self.trials)
        legend = "".join(
            f"<li>{_dot(key)} {_e(label)}</li>" for key, (label, _s, _c) in _JUDGMENTS.items()
        )
        domain_key = "".join(f"<li><b>{code}</b> {_e(title)}</li>" for _i, code, title in _DOMAINS)
        body = (
            '<section class="hero"><p class="eyebrow">Batch report</p>'
            f"<h1>{_e(self.outcome) or 'Assessment'}</h1>"
            f'<p class="lede">{len(self.trials)} trial{"s" if len(self.trials) != 1 else ""} '
            f"· {_e(summary)}</p>{self._meta()}</section>"
            f"{self._notice()}"
            '<div class="table-wrap"><table class="summary"><thead><tr>'
            '<th scope="col">Trial</th><th scope="col">Assessed result</th>'
            f'{head_cells}<th class="d overall" scope="col">Overall</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
            '<div class="keys"><ul class="legend">'
            f'{legend}</ul><ul class="domain-key">{domain_key}</ul></div>'
        )
        return self._page(f"RoB 2: {self.outcome}", body, root="")

    def _batch_row(self, trial: dict[str, Any]) -> str:
        trial_id = trial["id"]
        link = f'<a class="trial-link" href="trials/{_e(trial_id)}.html">{_e(trial["label"])}</a>'
        registry = trial.get("registry") or {}
        nct = (
            f'<span class="sub">{_e(registry["registry_id"])}</span>'
            if registry.get("kind") == "matched"
            else ""
        )
        disposition = self.dispositions.get(trial_id)
        if disposition != "assessed":
            review = self.reviews.get(trial_id) or {}
            reason = " ".join(
                [
                    review.get("reason", ""),
                    *(f"Missing: {fact}." for fact in review.get("facts", [])),
                ]
            )
            return (
                f'<tr class="not-assessed"><th scope="row">{link}{nct}</th>'
                f'<td colspan="7"><span class="status">{_e(_DISPOSITIONS.get(disposition or "", "Not assessed"))}</span>'
                f'<span class="sub">{_e(reason)}</span></td></tr>'
            )
        judgments = self.snapshots.get(trial_id, {}).get("domain_judgments", {})
        cells = "".join(f'<td class="d">{_dot(judgments.get(d))}</td>' for d, _c, _t in _DOMAINS)
        overall = self.snapshots.get(trial_id, {}).get("overall")
        return (
            f'<tr><th scope="row">{link}{nct}</th><td class="result">{self._result_line(trial_id)}</td>'
            f'{cells}<td class="d overall">{_dot(overall)}</td></tr>'
        )

    def _result_line(self, trial_id: str) -> str:
        result = self.results.get(trial_id) or {}
        reported = result.get("reported") or {}
        endpoint = (reported.get("endpoint") or {}).get("name") or result.get(
            "requested_outcome", ""
        )
        estimate = " ".join(
            str(part) for part in (reported.get("effect_measure"), reported.get("estimate")) if part
        )
        if reported.get("precision"):
            estimate += f" ({reported['precision']})"
        if not estimate and reported.get("group_values"):
            estimate = "; ".join(
                f"{item.get('group_id')}: {item.get('value')} {item.get('unit') or ''}".strip()
                for item in reported["group_values"]
            )
        population = reported.get("analysis_population")
        return (
            f"<span>{_e(endpoint)}</span>"
            + (f'<span class="est">{_e(estimate)}</span>' if estimate else "")
            + (f'<span class="sub">{_e(population)}</span>' if population else "")
        )

    # -- Trial page -------------------------------------------------------------

    def trial_page(self, trial: dict[str, Any]) -> str:
        trial_id = trial["id"]
        disposition = self.dispositions.get(trial_id)
        snapshot = self.snapshots.get(trial_id, {})
        registry = trial.get("registry") or {}
        registry_line = (
            f'<p class="lede"><a href="{_e(registry["url"])}">{_e(registry["registry_id"])}</a> · '
            f"{_e(registry.get('title', ''))}</p>"
            if registry.get("kind") == "matched" and registry.get("url")
            else ""
        )
        parts = [
            '<nav class="crumbs"><a href="../index.html">← All trials</a></nav>',
            f'<section class="hero"><p class="eyebrow">Trial report</p><h1>{_e(trial["label"])}</h1>',
            registry_line,
            self._meta(),
        ]
        if disposition == "assessed":
            rule = (snapshot.get("overall_trace") or [""])[0]
            parts.append(
                f'<div class="overall-line"><span class="status">Assessed · overall</span>'
                f"{_pill(snapshot.get('overall'), large=True)}"
                f"<span>{_e(_OVERALL_RULES.get(rule, ''))}</span></div></section>"
            )
        else:
            review = self.reviews.get(trial_id) or {}
            facts = "".join(f"<li>{_e(fact)}</li>" for fact in review.get("facts", []))
            parts.append(
                f'<div class="overall-line"><span class="status">'
                f"{_e(_DISPOSITIONS.get(disposition or '', 'Not assessed'))}</span></div></section>"
                f'<section class="card"><h2>Why this trial was not assessed</h2>'
                f"<p>{_e(review.get('reason', ''))}</p>"
                + (f"<ul>{facts}</ul>" if facts else "")
                + "</section>"
            )
        parts.append(self._notice())
        parts.append(self._result_card(trial_id))
        if disposition == "assessed":
            judgments = snapshot.get("domain_judgments", {})
            parts.append(
                '<nav class="domain-nav" aria-label="Domains">'
                + "".join(
                    f'<a href="#{code.lower()}">{_dot(judgments.get(d))}<span>{code}</span></a>'
                    for d, code, _t in _DOMAINS
                )
                + "</nav>"
            )
            records = self.canonical.get("domain_records", {})
            for domain_id, code, title in _DOMAINS:
                record = records.get(f"{trial_id}:{domain_id}")
                if record:
                    parts.append(self._domain(record, code, title))
        parts.append(self._sources(trial))
        return self._page(f"{trial['label']}: RoB 2", "".join(parts), root="../")

    def _result_card(self, trial_id: str) -> str:
        result = self.results.get(trial_id)
        if not result:
            return ""
        if result.get("kind") != "assessable":
            missing = "".join(
                f"<li>{_e(item.get('fact', ''))}{self._basis(item.get('basis') or {})}</li>"
                for item in result.get("missing_facts", [])
            )
            return (
                '<section class="card"><h2>Requested result</h2>'
                f"<p>{_e(result.get('requested_outcome', ''))}: not available from the sources.</p>"
                + (f'<ul class="facts">{missing}</ul>' if missing else "")
                + "</section>"
            )
        reported = result.get("reported") or {}
        target = result.get("target") or {}
        groups = "; ".join(
            str(group.get("assignment") or group.get("id"))
            for group in target.get("comparison_groups", [])
        )
        rows = [
            ("Requested outcome", result.get("requested_outcome")),
            ("Reported outcome", (reported.get("endpoint") or {}).get("name")),
            ("Definition", (reported.get("endpoint") or {}).get("definition")),
            ("Time point", (target.get("time_point_or_window") or {}).get("description")),
            ("Measurement", (target.get("measurement") or {}).get("method")),
            ("Comparison", groups),
            (
                "Effect estimate",
                " ".join(
                    str(p) for p in (reported.get("effect_measure"), reported.get("estimate")) if p
                ),
            ),
            ("Precision", reported.get("precision")),
            ("Other statistics", ", ".join(reported.get("reported_statistics") or [])),
            (
                "Group values",
                "; ".join(
                    f"{item.get('group_id')}: {item.get('value')} {item.get('unit') or ''}".strip()
                    for item in reported.get("group_values") or []
                ),
            ),
            ("Analysis population", reported.get("analysis_population")),
            ("Effect of interest", "Effect of assignment to intervention (intention to treat)"),
            (
                "Match to request",
                f"{str(result.get('relation', '')).capitalize()}. {result.get('relation_rationale', '')}",
            ),
        ]
        table = "".join(
            f'<tr><th scope="row">{_e(label)}</th><td>{_e(value)}</td></tr>'
            for label, value in rows
            if value
        )
        handles = [
            *(item.get("handle") for item in result.get("evidence", []) if isinstance(item, dict)),
            *((result.get("applicability") or {}).get("evidence") or []),
        ]
        quotes = "".join(
            self._evidence(self.by_handle.get(handle)) for handle in dict.fromkeys(handles)
        )
        return (
            '<section class="card"><h2>Assessed result</h2>'
            '<p class="hint">The researcher approved this result before the domains were assessed.</p>'
            f'<table class="kv">{table}</table>'
            + (
                f'<details class="quotes"><summary>Supporting passages</summary>{quotes}</details>'
                if quotes
                else ""
            )
            + "</section>"
        )

    def _domain(self, record: dict[str, Any], code: str, title: str) -> str:
        decision = record.get("decision") or {}
        proposed = decision.get("proposed", record.get("judgment"))
        adopted = record.get("judgment")
        claims = {
            claim["question_id"]: claim
            for claim in (record.get("evidence_sufficiency") or {}).get("claims", [])
        }
        searches = {
            account.get("identity"): account for account in record.get("search_accounts") or []
        }
        drivers = set(record.get("driver_questions") or [])
        head = (
            f'<section class="domain" id="{code.lower()}"><header class="domain-head">'
            f'<div><p class="eyebrow">Domain {code[1:]}</p><h2>{_e(title)}</h2></div>'
            f"{_pill(adopted, large=True)}</header>"
            '<p class="derivation">'
            + (
                f"Algorithm result {_pill(proposed)} adopted unchanged."
                if proposed == adopted
                else f"Algorithm result {_pill(proposed)}, adjudicated to {_pill(adopted)}."
            )
            + (
                ' Questions marked <span class="badge">Decisive</span> determined it.'
                if drivers
                else ""
            )
            + "</p>"
        )
        adjudication = decision.get("adjudication")
        if adjudication:
            cited = "".join(
                self._evidence(identity) for identity in adjudication.get("evidence", [])
            )
            count = len(adjudication.get("evidence", []))
            head += (
                '<div class="adjudication"><p><strong>Judgment adjudicated.</strong> '
                f"{_e(adjudication.get('rationale', ''))}</p>"
                + (
                    f'<details class="quotes adjudication-quotes"><summary>{count} supporting '
                    f"{'item' if count == 1 else 'items'}</summary>{cited}</details>"
                    if cited
                    else ""
                )
                + "</div>"
            )
        answers = "".join(
            self._answer(
                answer,
                claims.get(answer["question_id"]),
                searches,
                answer["question_id"] in drivers,
            )
            for answer in record.get("answers", [])
        )
        inactive = "".join(
            f'<li class="question skipped"><div class="q-head"><span class="q-num">{_e(self._number(qid))}</span>'
            f'<span class="q-text">{_e(self._wording(qid))}</span>'
            '<span class="answer na">Not applicable</span></div></li>'
            for qid in record.get("inactive_questions") or []
        )
        return f'{head}<ol class="questions">{answers}{inactive}</ol></section>'

    def _answer(
        self,
        answer: dict[str, Any],
        claim: dict[str, Any] | None,
        searches: dict[str, dict[str, Any]],
        driver: bool,
    ) -> str:
        qid = answer["question_id"]
        value = answer.get("answer", "")
        bases = answer.get("bases") or []
        quotes = "".join(self._basis(basis, searches) for basis in bases)
        cited_searches = {basis.get("search_receipt") for basis in bases}
        quotes += "".join(
            self._basis({"kind": "absence", "search_receipt": receipt}, searches)
            for receipt in (claim or {}).get("search_receipts") or []
            if receipt not in cited_searches
        )
        extra = []
        for item in answer.get("counterevidence") or []:
            index = item.get("basis_index")
            basis = bases[index] if isinstance(index, int) and 0 <= index < len(bases) else {}
            source = re.sub(r"\s*\n\s*", " ", str(basis.get("source") or ""))
            quoted = f" <q>{_e(source)}</q>" if source else ""
            extra.append(
                f'<li class="counter"><b>Against:</b> {_e(item.get("implication", ""))}{quoted}</li>'
            )
        for unknown in answer.get("unknowns") or []:
            extra.append(f'<li class="unknown"><b>Unknown:</b> {_e(unknown)}</li>')
        for premise in (claim or {}).get("unresolved_premises") or []:
            text = premise.get("premise") if isinstance(premise, dict) else premise
            extra.append(f'<li class="unknown"><b>Unresolved:</b> {_e(text)}</li>')
        notes = f'<ul class="notes">{"".join(extra)}</ul>' if extra else ""
        count = sum(1 for basis in bases if basis.get("evidence") or basis.get("search_receipt"))
        count += sum(
            1
            for receipt in (claim or {}).get("search_receipts") or []
            if receipt not in cited_searches
        )
        driver_badge = (
            '<span class="badge" title="This answer determined the domain judgment">Decisive</span>'
            if driver
            else ""
        )
        return (
            f'<li class="question{" driver" if driver else ""}"><div class="q-head">'
            f'<span class="q-num">{_e(self._number(qid))}</span>'
            f'<span class="q-text">{_e(self._wording(qid))}</span>{driver_badge}'
            f'<span class="answer a-{_e(value)}">{_e(_ANSWERS.get(value, value))}</span></div>'
            f'<p class="why">{_e(answer.get("justification", ""))}</p>{notes}'
            + (
                f'<details class="quotes"><summary>{count} supporting '
                f"{'item' if count == 1 else 'items'}</summary>{quotes}</details>"
                if quotes
                else ""
            )
            + "</li>"
        )

    def _basis(
        self, basis: dict[str, Any], searches: dict[str, dict[str, Any]] | None = None
    ) -> str:
        if basis.get("kind") == "absence":
            account = (searches or {}).get(basis.get("search_receipt"), {})
            query = account.get("normalized_query") or account.get("query") or "search"
            return (
                '<div class="evidence absence"><span class="where">Search · no matches</span>'
                f"<p>Searched the trial's sources for “{_e(query)}” and found nothing.</p></div>"
            )
        identity = basis.get("evidence")
        if not identity:
            text = basis.get("unresolved_premise") or basis.get("source") or ""
            return f'<div class="evidence"><p>{_e(text)}</p></div>' if text else ""
        role = basis.get("kind", "direct_support")
        return self._evidence(identity, role)

    def _evidence(self, identity: str | None, role: str = "direct_support") -> str:
        item = self.evidence.get(identity or "")
        if not item:
            return ""
        source = self.sources.get(item.get("source_id", ""), {})
        label = source.get("label") or "source"
        url = self.registry_urls.get(item.get("source_id", ""))
        tag = (
            ""
            if role == "direct_support"
            else f'<span class="role">{_e(role.replace("_", " "))}</span>'
        )
        if item.get("kind") == "figure":
            render = item.get("render") or {}
            png = self.images.get(
                f"visual/{str(render.get('identity', '')).removeprefix('sha256:')}.png"
            )
            image = (
                f'<img alt="Rendered page {_e(render.get("page", ""))} of {_e(label)}" '
                f'src="data:image/png;base64,{base64.b64encode(png).decode()}">'
                if png
                else ""
            )
            return (
                f'<figure class="evidence figure"><span class="where">{_e(label)} · page '
                f"{_e(render.get('page', ''))} · figure</span>{tag}{image}"
                f"<figcaption>Assessor transcription: {_e(item.get('transcription', ''))}</figcaption></figure>"
            )
        lines = (
            f"line {item['start_line']}"
            if item.get("start_line") == item.get("end_line")
            else f"lines {item.get('start_line')}–{item.get('end_line')}"
        )
        quote = re.sub(r"\s*\n\s*", " ", str(item.get("quote", "")))
        return (
            '<blockquote class="evidence"><span class="where">'
            + (f'<a href="{_e(url)}">{_e(label)}</a>' if url else _e(label))
            + " · page "
            f"{_e(item.get('page', ''))} · {_e(lines)}</span>{tag}<p>{_e(quote)}</p></blockquote>"
        )

    def _sources(self, trial: dict[str, Any]) -> str:
        rows = "".join(
            f"<tr><td>{_e(source.get('label', ''))}</td><td>{_e(str(source.get('role', '')).replace('_', ' '))}</td>"
            f"<td>{_e(source.get('page_count', ''))}</td></tr>"
            for source in trial.get("sources", [])
        )
        return (
            '<section class="card"><h2>Sources</h2><table class="sources"><thead><tr>'
            "<th>File</th><th>Role</th><th>Pages</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            '<p class="hint">Source files are not part of the bundle. Quotations above are '
            "exact excerpts from these files.</p></section>"
        )

    def _number(self, question_id: str) -> str:
        question = self.questions.get(question_id)
        if question is None:
            return ""
        locator = question.guidance.official.source_locator if question.guidance.official else ""
        match = re.search(r"signalling question (\d+\.\d+)", locator or "")
        return match.group(1) if match else ""

    def _wording(self, question_id: str) -> str:
        question = self.questions.get(question_id)
        return question.wording if question is not None else question_id


_CSS = """
:root{--bg:#f7f5f0;--paper:#fffdf8;--ink:#1d1f24;--muted:#5f6470;--line:#e4dfd3;--accent:#2b4c7e;
--low:#1f8a4c;--low-bg:#e3f3e8;--concerns:#b8860b;--concerns-bg:#fbf1d3;--high:#b42b27;--high-bg:#f8e1df;
--none:#8a8f99;--none-bg:#eceef1;--quote:#f3efe5;--shadow:0 1px 2px rgba(20,20,30,.06),0 4px 16px rgba(20,20,30,.05);
--serif:"Iowan Old Style","Charter","Palatino Linotype","Book Antiqua",Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--paper:#1d2025;--ink:#e8e6e1;--muted:#a3a7b0;
--line:#30343b;--accent:#8fb3ea;--low:#5cc488;--low-bg:#173326;--concerns:#e2b53f;--concerns-bg:#3a3018;
--high:#ef6b66;--high-bg:#3d1f1e;--none:#9aa0aa;--none-bg:#2a2d33;--quote:#24282e}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 var(--sans)}
.wrap{max-width:68rem;margin:0 auto;padding:0 1.25rem}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
code{font-size:.9em}
.masthead{background:var(--paper);border-bottom:1px solid var(--line)}
.masthead .wrap{display:flex;gap:1rem;align-items:center;justify-content:space-between;min-height:3.5rem;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:.6rem;color:var(--ink);text-decoration:none;font-weight:600}
.mark{font:700 .75rem/1 var(--sans);letter-spacing:.04em;color:var(--paper);background:var(--ink);padding:.35rem .45rem;border-radius:.3rem}
.meta{color:var(--muted);font-size:.9rem}
.hero{padding:2.5rem 0 1rem}.hero h1{font:600 clamp(1.8rem,3.5vw,2.6rem)/1.15 var(--serif);margin:.2rem 0 .5rem}
.eyebrow{margin:0;text-transform:uppercase;letter-spacing:.12em;font-size:.72rem;font-weight:600;color:var(--muted)}
.lede{color:var(--muted);margin:.25rem 0}
.notice{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:.5rem;padding:.9rem 1.1rem;margin:1rem 0 1.5rem;font-size:.92rem;color:var(--muted)}
.notice strong{color:var(--ink)}.cite{display:block;margin-top:.4rem;font-size:.85rem}
.table-wrap{overflow-x:auto;background:var(--paper);border:1px solid var(--line);border-radius:.75rem;box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%}
.summary th,.summary td{padding:.85rem 1rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
.summary thead th{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600}
.summary tbody tr:last-child>*{border-bottom:0}.summary tbody tr:hover{background:var(--quote)}
.summary .d{text-align:center;width:3.4rem;padding-left:.25rem;padding-right:.25rem}
.summary .overall{border-left:1px solid var(--line)}
.summary{min-width:44rem}.summary tbody th{white-space:nowrap}.summary .result{min-width:13rem}
.trial-link{font-weight:600}.sub{display:block;color:var(--muted);font-size:.82rem;font-weight:400}
.result span{display:block}.est{font-variant-numeric:tabular-nums;font-weight:500}
.not-assessed .status{font-weight:600;color:var(--muted)}
.dot{display:inline-grid;place-items:center;width:1.9rem;height:1.9rem;border-radius:50%;font:700 1.05rem/1 var(--sans);color:#fff}
.dot.low{background:var(--low)}.dot.concerns{background:var(--concerns)}.dot.high{background:var(--high)}.dot.none{background:var(--none-bg);color:var(--none)}
.pill{display:inline-flex;align-items:center;gap:.45rem;border-radius:999px;padding:.15rem .7rem .15rem .2rem;font-weight:600;font-size:.88rem;vertical-align:middle}
.pill .dot{width:1.35rem;height:1.35rem;font-size:.8rem}
.pill.low{background:var(--low-bg);color:var(--low)}.pill.low .dot{background:var(--low)}
.pill.concerns{background:var(--concerns-bg);color:var(--concerns)}.pill.concerns .dot{background:var(--concerns)}
.pill.high{background:var(--high-bg);color:var(--high)}.pill.high .dot{background:var(--high)}
.pill.none{background:var(--none-bg);color:var(--none)}.pill.none .dot{background:var(--none)}
.pill-lg{font-size:1rem;padding:.3rem .95rem .3rem .3rem}.pill-lg .dot{width:1.7rem;height:1.7rem;font-size:.95rem}
.keys{display:flex;flex-wrap:wrap;gap:1rem 2.5rem;margin:1.25rem 0 2rem;color:var(--muted);font-size:.88rem}
.keys ul{list-style:none;margin:0;padding:0;display:grid;gap:.4rem}.legend li{display:flex;align-items:center;gap:.5rem}
.legend .dot{width:1.3rem;height:1.3rem;font-size:.8rem}.domain-key b{color:var(--ink);margin-right:.35rem}
.crumbs{padding-top:1.25rem;font-size:.9rem}.crumbs a{text-decoration:none}
.meta-line{color:var(--muted);font-size:.82rem;margin:.4rem 0 0}.meta-line code{font-size:.95em}
.derivation{color:var(--muted);font-size:.9rem;margin:.3rem 0 .2rem}.derivation .pill{font-size:.8rem}
q{font-family:var(--serif);color:var(--muted)}
.overall-line{display:flex;align-items:center;gap:.9rem;flex-wrap:wrap;margin:1rem 0 .5rem;color:var(--muted)}
.card,.domain{background:var(--paper);border:1px solid var(--line);border-radius:.75rem;box-shadow:var(--shadow);padding:1.4rem 1.5rem;margin:1.25rem 0}
.card h2,.domain h2{font:600 1.3rem/1.25 var(--serif);margin:.15rem 0 .6rem}
.hint{color:var(--muted);font-size:.88rem;margin:.2rem 0 1rem}
.kv th{width:13rem;color:var(--muted);font-weight:500;padding:.45rem 1rem .45rem 0;vertical-align:top;text-align:left}
.kv td{padding:.45rem 0;border-bottom:1px dashed var(--line)}.kv tr:last-child td{border-bottom:0}
.domain-nav{position:sticky;top:0;z-index:2;display:flex;gap:.5rem;flex-wrap:wrap;padding:.6rem 0;background:var(--bg)}
.domain-nav a{display:inline-flex;align-items:center;gap:.4rem;background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:.2rem .75rem .2rem .25rem;color:var(--ink);text-decoration:none;font-weight:600;font-size:.88rem}
.domain-nav .dot{width:1.4rem;height:1.4rem;font-size:.8rem}
.domain{scroll-margin-top:4rem}.domain-head{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:.9rem;margin-bottom:.4rem}
.adjudication{background:var(--quote);border-radius:.5rem;padding:.8rem 1rem;margin:.9rem 0}
.adjudication p{margin:.3rem 0}.adjudication details.adjudication-quotes{margin-left:0}
.questions{list-style:none;margin:0;padding:0}
.question{padding:1rem 0;border-bottom:1px solid var(--line)}.question:last-child{border-bottom:0}
.q-head{display:grid;grid-template-columns:2.6rem 1fr auto auto;gap:.75rem;align-items:baseline}
.q-num{font:600 .95rem var(--serif);color:var(--muted)}.q-text{font-weight:500}
.answer{justify-self:end;white-space:nowrap;font-size:.82rem;font-weight:700;border-radius:.35rem;padding:.12rem .55rem;background:var(--none-bg);color:var(--ink)}
.a-yes,.a-no{background:var(--ink);color:var(--paper)}.a-probably_yes,.a-probably_no{border:1.5px solid var(--ink);background:transparent}
.a-no_information{background:var(--concerns-bg);color:var(--concerns)}.answer.na{background:transparent;color:var(--muted);font-weight:500}
.badge{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);border:1px solid currentColor;border-radius:.3rem;padding:.05rem .35rem}
.why{margin:.45rem 0 0 3.35rem}.notes{margin:.4rem 0 0 3.35rem;padding:0;list-style:none;font-size:.92rem}
.notes li{margin:.2rem 0}.counter b{color:var(--high)}.unknown b{color:var(--concerns)}
.skipped .q-text{color:var(--muted)}
details.quotes{margin:.55rem 0 0 3.35rem}details.quotes summary{cursor:pointer;color:var(--accent);font-size:.88rem;font-weight:600}
.evidence{margin:.6rem 0;padding:.65rem .9rem;background:var(--quote);border-left:3px solid var(--line);border-radius:0 .4rem .4rem 0}
blockquote.evidence p{margin:.25rem 0 0;font-family:var(--serif);font-size:1rem}
.where{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
.role{margin-left:.5rem;font-size:.72rem;color:var(--accent);font-weight:600}
.absence{border-left-color:var(--concerns)}.absence p{margin:.25rem 0 0}
figure.evidence img{display:block;max-width:100%;margin:.5rem 0;border:1px solid var(--line);border-radius:.3rem;background:#fff}
figcaption{font-size:.9rem}
.sources td,.sources th{padding:.45rem .75rem .45rem 0;border-bottom:1px solid var(--line);text-align:left}
.sources th{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.footer{color:var(--muted);font-size:.82rem;padding-top:1rem;padding-bottom:3rem;border-top:1px solid var(--line);margin-top:2.5rem}
@media (max-width:640px){.q-head{grid-template-columns:2rem 1fr}.answer,.badge{grid-column:2;justify-self:start}
.why,.notes,details.quotes{margin-left:2.75rem}.kv th{width:auto;display:block;padding-bottom:0}.kv td{display:block}}
@media print{:root{--bg:#fff;--paper:#fff;--shadow:none}body{font-size:11pt}.masthead,.domain-nav,.crumbs{display:none}
.card,.domain,.table-wrap{box-shadow:none;break-inside:auto}.question{break-inside:avoid}a{color:inherit;text-decoration:none}
.dot,.pill,.answer{-webkit-print-color-adjust:exact;print-color-adjust:exact}
details::details-content{content-visibility:visible;height:auto}details>summary{list-style:none}}
"""
