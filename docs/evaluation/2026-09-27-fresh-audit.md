# Fresh September 27 benchmark audit

Audit of checkout `4e03e798` and the locally retained September 27 runs. This supplements the earlier audit of `8ae8016`; its scores and classifications must not be substituted for the new campaign.

The later `human-like-luna-medium-r1` workflow check shares the date directory but is a separate campaign. When its logs are present, `reproduce.py` lists them separately; they are not part of the frozen 102-segment audit inventory.

Evidence: [trace inventory](2026-09-27-fresh-audit-evidence/traces.md), [all 156 scored cells](2026-09-27-fresh-audit-evidence/trace-cells.csv), [machine-readable inventory](2026-09-27-fresh-audit-evidence/inventory.json), [source-based scientific review](2026-09-27-fresh-audit-evidence/science.md), [code/contract coverage](2026-09-27-fresh-audit-evidence/code.md), and [primary-source research](2026-09-27-fresh-audit-evidence/research.md). Recount the local logs and original score vectors with `.venv/Scripts/python.exe docs/evaluation/2026-09-27-fresh-audit-evidence/reproduce.py`. The script was run successfully and passes Ruff checks. The source PDFs and run artifacts are local inputs, not included in these audit notes.

## Findings established by the artifacts

The scored fresh Luna Medium campaign contains 26 finalized Trial–Result cases. Its provisional agreement is **83/130 Domains (63.8%)**, **96/130 Low/non-Low Domains (73.8%)**, and **2/26 exact overall labels (7.7%)**. D1 through D5 exact counts are 26, 14, 12, 19 and 12 out of 26. There are 47 Domain disagreements. OS agrees on 37/50 cells, PFS 26/45, and AE 20/35.

The reference contains 104 Low and 26 Some-concerns Domain labels, with no High. An all-Low prediction therefore reaches 80% agreement. This does not establish that the model is scientifically worse than that baseline; it establishes that 80% agreement alone is a weak target. Use independently adjudicated, exact-Result scientific validity with class support, unsupported reassurance and concern, scope, completion and uncertainty. This audit does not estimate an adjusted scientific accuracy percentage.

The model produces 80 Low, 32 Some-concerns and 18 High Domain labels. Twenty overall labels are High; four arise solely from multiple Some-concerns Domains: GETUG-AFU-15 OS, ENZAMET PFS, GETUG-AFU-15 PFS and ARASENS AE. The current aggregation follows ADR 0035 and must be analyzed separately from source interpretation. Changing it to improve overall agreement would not repair Domain reasoning.

The requested day contains 102 JSONL segments across three directories: 7 separate issue-465 E2E segments, 33 segments from the unfinished `latest-rob2-kit-luna-medium` campaign, and 62 from `rob2-trial-benchmark-fresh-4e03e798`, including retry material. Failed calls, unfinished campaigns and replacement attempts are not additional independent scientific cases.

All 102 files parsed without malformed JSON lines. A completed trace event does not necessarily mean a successful tool call. In the original fresh run tree's 56 segments, 2,464 MCP records comprise 2,378 completed-status and 86 failed-status calls; the six retry segments add 120 records. The original tree includes 602 Domain-context calls (436 continuations), 406 page reads, 170 single searches (54 observed zero-hit results), and no working-checkpoint saves. These are observed friction measures, not a causal explanation of scientific error.

Across the complete fresh tree including retries there are 2,584 MCP records, of which 89 have failed status. The catalog lists 28 Trial–outcome pairs; the 26-case manifest does not include ARASENS PFS or SWOG-1216 AE. Report its manifest denominator rather than implying complete catalog coverage. A separate phase-3 launcher summary records 22 metadata-binding preflight failures and one interruption; these are workflow observations, not additional scientific errors or evidence of failed finalized assessments.

The 86 failed-status calls are input-validation failures: 40 Proposal validation, 37 Domain saves, six intake, two page reads and one Domain-context call. They are distinct from 61 structured repair receipts. Recurrent errors include wrong discriminated-union tags, scalar counterevidence instead of arrays, canonical identities instead of Evidence handles, and lists instead of a single revision handle. Current tools already contain examples, so adding more text is only a hypothesis. Inspect actual installed-host delivery and test the smallest change.

Eight repaired Domain drafts changed a definite answer to a probable answer without intervening discovery, preserving polarity. This is repair-associated calibration, not demonstrated scientific error. A separate D5 polarity change followed substantial new visual inspection. The two repeated committed Domain histories are evidence-attributed corrections. Do not infer answer corruption merely from a repair or claim that review never changes a judgment.

## A confirmed reporting defect

The scorer's `result_scope_denominators.exact` counts all primary-eligible cases, including adjudicated equivalents. All 26 fresh case records carry an equivalence adjudication, attached only after a mechanical expected-versus-observed scope mismatch. Thus the report's “exact 26” means primary-eligible after adjudication, not 26 mechanical matches.

Independently, the Proposal relations are 15 exact and 11 narrower. Proposal relation compares the requested target with the reported Result; benchmark scope comparison compares the frozen expected Result with the approved observed Result. These are different axes. Neither a string mismatch nor a narrower Proposal relation proves scientific non-equivalence. Conversely, matching point estimates do not establish equivalence of populations, grouping or outcome windows. Preserve both axes and show the source-grounded adjudication rationale.

## Model capacity versus system design

The source checks below distinguish an observed mechanism from a certified final label. A discrepancy can be defensible without proving the catalog wrong.

| Fresh case | Source observation | Audit disposition |
|---|---|---|
| PEACE-1 AE, D4 High versus Some concerns | Supplement PDF p.14 requires extra liver laboratory monitoring in abiraterone arms; the approved severe-AE outcome includes laboratory toxicities | A genuine differential-ascertainment mechanism supports the concern. Review whether it warrants the saved differential-measurement answer for this Result; once that answer is accepted, apply the official branch without inventing an additional quantitative-impact threshold. |
| TITAN OS, D3 High versus Low | Main article PDF p.4 distinguishes 45 treatment discontinuers still in survival follow-up from 39 lost/withdrawn from all further data collection | A real missing-outcome concern, not a confusion between treatment discontinuation and missingness. Arm allocation, reasons and outcome dependence remain unresolved. The final signaling path needs adjudication; metastatic disease alone does not prove informative missingness. |
| ARASENS OS, D3 High versus Low | Main article PDF p.4 describes 1305 analyzed of 1306 randomized and last-known-alive censoring, but not complete early-loss accounting | Analysis membership does not establish actual outcome availability. Neither a confident Low from the denominator nor a narrative claim that bias is established by absent reporting is justified. Preserve the official uncertainty branch while reviewing whether a probable answer is supportable. |
| TITAN PFS, D5 Low versus Some concerns | A dated September 2018 protocol amendment specifies a matching rPFS analysis before the November cutoff; the standalone SAP is later | A later SAP does not erase earlier applicable plan content. But before-cutoff timing alone does not establish before-unblinded-access timing. This is a defensible-alternative candidate, not a proven human-label error. |
| STAMPEDE PFS, D5 Some concerns versus Low | An applicable January 2017 SAP precedes the February data freeze; access chronology remains unspecified | Plan content is supported, historical access chronology is uncertain. Missing chronology is not evidence of result-driven selection; adjudicate probable versus No-information answers under the official guidance. |
| TITAN AE, D2 Some concerns versus Low | Blinded trial conduct and protocol-allowed AE stopping coexist with a saved No-information answer about trial-context deviations | A plausible over-conservatism candidate: absence of an explicit guarantee that no context-caused deviation occurred should not automatically defeat a source-supported probable answer. Possible awareness and the complete rationale still need adjudication; this is not a certified wrong label. |
| GETUG-AFU-15 PFS, D2 Some concerns versus Low | The rationale mentions post-progression crossover and two protocol-violation discontinuations | Post-progression care cannot alter an earlier PFS event. Investigate that irrelevant premise separately from the two discontinuations whose timing/cause remain unknown; the latter may still justify uncertainty. |
| PEACE-1 OS, D2 Low versus Some concerns | The report describes open-label treatment, ordinary post-progression care and ITT | Awareness alone is insufficient to establish trial-context deviations. The model's Low is a defensible alternative candidate, subject to the complete conduct evidence. |

These checks do not establish that all 47 mismatches are errors, nor that all conservative judgments are justified. They expose the principal reasoning distinction that needs testing: source-supported probable inference versus unsupported reassurance, unsupported concern, or honestly bounded uncertainty. Official algorithms remain unchanged; any reviewer override must be explicit and justified.

The selected fresh source checks did not certify a pure scientific model error with a uniquely established replacement label. The strongest weaknesses are questionable warrants and potentially excessive use of No information despite relevant circumstances. That is a limitation of the current evidence, not proof that the model made no scientific errors. It would be misleading to count those candidates as corrected answers or claim a new accuracy percentage. Confirmed engineering defects/friction—scope-report conflation and malformed input calls—are separately evidenced above.

| Observed failure stage | What higher effort/capacity could change | Required evidence or repair |
|---|---|---|
| Wrong inference from a delivered, relevant passage | Plausibly capacity-sensitive | Same Result and decisive passages; compare baseline repeats, effort and model with frozen harness |
| Failure to seek or inspect a decisive passage | Search policy and capacity can both matter | Compare natural retrieval with actually delivered decisive evidence |
| Tool validation or unavailable content | May improve tool-call construction; cannot repair missing content or incorrect server behavior | Reproduce the boundary failure and fix the narrow contract or delivery defect |
| Excessive context and absent working notes | A larger model may tolerate it; benefit is unmeasured | Reuse the existing checkpoint, test complete compact delivery, preserve scientific qualifiers |
| Ambiguous reference/Result mapping | Cannot create scientific ground truth | Independent source-grounded adjudication; retain unresolved coverage |
| Overall aggregation convention | Not a capacity failure | Report policy separately; any change requires an explicit versioned decision |

No available campaign isolates the causal effect of a stronger model or higher effort. The model/effort comparison capability already exists. There is no basis to promise that a model upgrade alone reaches 80% scientific accuracy.

## Design direction and delivery order

The host already owns a Reason–Act loop: identify an unresolved premise, choose a search/read/render action, inspect the observation, revise the inference, and correct a Domain before closure. The server correctly owns identity, provenance, workflow and deterministic logic. A valid Evidence handle or successful Trial review does not establish scientific entailment.

1. Adjudicate the fresh campaign's decisive claims, including matching-label controls. Feed demonstrated generalizable errors into the existing minimal reasoning repair rather than append another generic checklist.
2. Compare reasoning with natural retrieval and supplied decisive passages; compare effort/model only under frozen Sources, Results, tools, pack, prompts, budget and declared draws. Retain failed attempts.
3. Use existing question guidance, comparison cards, premise records and Trial review to focus on the specific unresolved proposition and counterevidence. Do not add another model loop, mandatory reviewer agent, embedding backend or search quota without demonstrated benefit.
4. Operationalize existing working-checkpoint handoff and test a smaller complete Domain-context delivery. Measure actual host-visible delivery; serialized bytes are not model tokens or comprehension.
5. Optimize retrieval latency and cost only among scientifically qualifying candidates. Use untouched Trial-separated material and genuine non-Low/High controls for qualification.

This order follows [Cochrane's Result-specific assessment guidance](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08), uses the existing [ReAct](https://arxiv.org/abs/2210.03629) architecture, and treats [tool-design](https://www.anthropic.com/engineering/writing-tools-for-agents) and [context-position research](https://aclanthology.org/2024.tacl-1.9/) as experiment design guidance, not evidence of a rob2-kit accuracy gain.

## Published work

- [#478 — Fresh-benchmark spec](https://github.com/AliSalman-et-al/rob2-kit/issues/478).
- [#479 — Adjudicate the fresh source-to-answer decisions](https://github.com/AliSalman-et-al/rob2-kit/issues/479), accuracy first, no blocker.
- [#480 — Distinguish mechanical matches from adjudicated equivalence](https://github.com/AliSalman-et-al/rob2-kit/issues/480), no blocker.
- [#481 — Reduce recurring invalid assessment inputs](https://github.com/AliSalman-et-al/rob2-kit/issues/481), efficiency after accuracy, no code blocker.

All three child issues are native sub-issues with `ready-for-agent`. Existing work remains authoritative: #476 scientific reasoning repair; #332/#399 population and safety grouping; #455–#458/#462 scientific distinctions and review; #463/#468 controlled comparisons; #464 untouched qualification; #473/#474 checkpoint and context efficiency; #461 retrieval profiling. #475 retains its earlier 85/130 and 78/130 campaigns. Closure of a predecessor issue does not establish successful scientific qualification.

No production code, provisional labels, Source PDFs or historical run artifacts were changed. No paid benchmark reruns were launched. This is an engineering and source-grounded model audit, not independent expert adjudication or proof of 80% accuracy.

The code pass covered the major source, Evidence, MCP, workflow, scientific-pack, evaluation and host-guidance paths and inspected related tests. It was not a line-by-line correctness proof of every module or an exhaustive PDF-layout review. All trace files and scored label cells were inventoried; scientific source review is a selected-case investigation, and unreviewed cells remain explicitly unadjudicated. The separate code reviewer preferred recording input friction under existing work; the integrated plan isolates #481 because input construction is distinct from #474's output-context delivery and #343's repaired historical v0.8 shapes. It mandates a bounded comparison, not a speculative schema rewrite.
