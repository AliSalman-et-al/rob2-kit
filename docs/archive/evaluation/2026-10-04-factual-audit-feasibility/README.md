# One full-Domain factual-audit feasibility response

**Decision: reject reviewer adoption for now.** The response detected the known Baby-OSCAR numeric attribution gap and another genuine SAP-method attribution gap, but its own feedback included a false alarm on a qualified inference and an inaccurate supporting line range. Detection alone is insufficient for a trustworthy citation reviewer. The deterministic exporter remains an offline, model-free diagnostic; no host reviewer, default stage or gate was added.

This is exactly one authorized, isolated **`gpt-6-luna` / medium** factual response, not another Baby-OSCAR assessment continuation. Both full Domains were exported from immutable, verified benchmark-derived bundles using the exporter at `d6bdae597e72d4ff6221bc2dc65aa1e44fc4ea2f`: Baby-OSCAR D4 and DAPA-HF D5. No bad clause was selected, no claim removed, no repair page added, and no desired outcome or operator critique entered the model input. Original assessments, bundles and prior rollouts remain unchanged. Full benchmark remains off.

## Preflight and execution

The panel includes all **six saved warrants**, their uncertainty/counterevidence fields, existing citation roles and **11 unique complete cited spans**. Exports preserve every claim and citation from the verified canonical bundle. The input contains exact source identity/hash, physical page/line metadata and all original selected text. Source spans were rendered without JSON string escaping to make line numbering readable. `claim-preflight.json` verifies export-to-bundle equality, every claim/role's presence, all citation joins and every exact supplied span. `panel-evidence-manifest.json` and immediate `launch_checked` receipt verify input/span hashes and coverage. Preflight establishes supplied coverage, not semantic sufficiency.

Size was reported before inference: 52,788 actual input bytes, approximately 24,259 tokens by the earlier panel's observed ratio, within the requested approximately 30k sizing target. Input remained telemetry only. Actual token count was lower; no claims or sources were trimmed to meet a hard input cap.

The existing isolated tool-free Codex setup was reused without reading/copying credentials or changing its configuration. Launcher and effective context both record `gpt-6-luna` / medium. Fresh `codex exec` did not resume assessment history. All tools/MCP/web features were disabled. One provider response and one final message completed with zero tools, no retry/continuation and no guard stop. Output was frozen in `answer-freeze.json` before adjudication. Raw stderr stays private with recorded provenance.

Limits: one response, 3,000 output tokens, 300 seconds wall, 120 seconds idle, zero tools. Output guards are reactive rather than a provider-enforced cap; observed output overshoot was zero.

## Full-panel findings

| Measure | Count |
| --- | ---: |
| Whole saved warrants / substantively addressed | 6 / 6 |
| Predeclared sentence-or-uncertainty units | 23 |
| Warrant sentences / uncertainty units / counterevidence units | 20 / 3 / 0 |
| Fully addressed / partially addressed / not explicitly addressed units | 17 / 5 / 1 |
| Predeclared numeric attribution gap detected | 1 / 1 |
| Additional real attribution gap | 1 |
| Confirmed false-alarm units on qualified inference | 1 |
| Wrong supporting-line-range units | 1 |
| Independently supported control facts preserved | 2 / 2 |
| False global-falsity claims / explicit false contradictions | 0 / 0 |
| Nonexistent source/page references / forced RoB revisions | 0 / 0 |

These are complete counts over mechanically frozen scoring units, **not** an accuracy rate over 23 independent clinical facts. Units can contain mixed clauses; partial coverage is not silently passed. The unaddressed unit is the final “probably not inappropriate” interpretation; the audit did not reassign that risk judgment. `unit-adjudication.json` reports every unit and its qualifications.

The response correctly said the selected citations do not support `13/86 vs 13/94`, without declaring the counts globally false or fabricating a replacement. It also correctly distinguished DAPA-HF's actual Cox model in the main report from a claim that the selected SAP p241 prespecified that model. The latter page defines endpoints and censoring rather than the Cox specification. This additional finding is credited rather than treated as an unwanted false alarm.

The supported assessor-blinding statement was preserved with its actual main p2 locator. DAPA-HF's before-unblinding amendment requirement was preserved as a plan/commitment, without pretending it directly establishes SAP edition finalization before access to unblinded data. The response accepted structured/clinically relevant characterization and common application as reasonable inference, and retained timing/opportunity uncertainty. It did not separately evaluate the proportional-similarity adjective once the numerical support was absent; do not claim every inferential control passed.

The false alarm concerns the claim that the BPD component requires some clinical judgment. The response says the selected spans do not establish it, while the cited appendix p14 lines 33–36 explicitly describes oxygen need as subjective. Some clinical judgment is a defensible qualified inference from that text; treating it as unsupported is excessive literalism. This is distinct from appropriately limiting an external-validation or actual-adjudication-conduct assertion.

The inaccurate locator appears in DAPA-HF's primary-composite/components finding. Main p5 lines 19–26 report the primary composite, but its cited lines 42–55 report the secondary composite/recurrent analysis, not the primary component-result passage at lines 27–38. Supporting component information exists within the supplied p5 span, so this is a source-range attribution defect, not a fabricated fact or nonexistent page. A citation auditor that reproduces an attribution defect in its own feedback is not ready for adoption.

A further limitation is source pooling: the response uses main p2 blinding support, exported for the assessor-awareness warrant, in its differential-measurement discussion without explicitly distinguishing its absence from that warrant's original citation bindings. Whole-panel factual support and original claim-specific attribution are different. No automatic citation replacement occurred.

The direction is rejected **for now** under the predeclared material-factual-failure criterion. No extra model call was used to repair or retest the response. This does not prove that every separate factual context is ineffective; it establishes that this particular bounded reviewer is not sufficiently dependable to adopt. Optional-review guidance alone has not solved attribution.

## Exact extra cost

| Usage | This separate factual audit | Native fork continuation | Earlier focused panel |
| --- | ---: | ---: | ---: |
| Input tokens | 20,806 | 765,107 | 16,807 |
| Cached input tokens | 1,792 | 683,520 | 0 |
| Uncached input tokens | 19,014 | 81,587 | 16,807 |
| Output tokens | 1,106 | 2,476 | 663 |
| Reasoning output, included in output | 0 | 566 | 0 |
| Model turns/responses | 1 | 1 turn, multiple provider responses | 1 |
| Tools | 0 | 13 | 0 |
| Wall seconds | 27.458 | 77.219 | 18.678 |

This is additional cost, not a cost saving. Audit input is 2.72% of native cumulative input but uncached input is 23.31% of native uncached input; the tasks and history differ. No inherited totals were counted as new audit usage. No monetary price is inferred from token counts.

## Native presentation versus recovery follow-through

Read-only replay loaded the exact native cached review snapshot with its digest verified. The D4 target was 38,861 serialized characters; its first returned fragment ended at 20,041. The numerical clause begins at character **22,950**, and therefore was genuinely absent from that first D4 fragment. One additional fragment of 18,820 characters reconstructs the exact complete target. The derivative database hash remains unchanged.

The fragment boundary and ordering impose an observable presentation burden: source/fact serialization precedes the relevant warrant, so the first Domain response does not expose that claim/source pair. Existing question selectors offer smaller targets (the differential-answer target is 13,075 UTF-8 bytes; that is target size, not a promise about the entire wire response). These are concrete ergonomic observations.

Recovery itself is not broken or inaccessible. The native response had an explicit next cursor and incomplete flag; both the installed skill and tool description instructed continuation/reassembly. The model did not follow the cursor before requesting other Domains and closing. That is a separately observable follow-through failure. The correct numerical page was separately present in the D3 review prefix and older assessment history, rather than co-located with the missing D4 warrant. Neither this replay nor the factual response justifies an anchoring or model-capacity explanation.

No runtime presentation/recovery change was made. A future model-neutral presentation investigation can examine warrant placement and duplicated source context against exact byte budgets, without adding a reviewer stage or gate. The read-only replay is evidence for that bounded investigation, not permission to restart this assessment or run another paid audit.
