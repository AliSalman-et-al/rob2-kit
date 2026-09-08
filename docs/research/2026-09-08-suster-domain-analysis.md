# Suster run: domain errors and implementation priorities

The largest opportunities are broader source orientation, better use of already retrieved evidence, and clearer separation of source facts from scientific inference. Changing the overall scoring rule would not address these failures. None of the proposed changes has a measured accuracy gain yet.

## Evidence and limits

The supplied campaign used `37e47f1`, Luna Medium, and one draw for each of 75 trial-result rows across 33 trials. The current checkout, `f2304ed`, additionally contains the Domain text-budget fix from #296/#297. That later fix was not evaluated by this campaign.

I parsed every completed MCP call in `phase-*.jsonl`, avoiding double-counting the parallel `rollout-phase-*.jsonl` representation, and joined the observations with final bundle checkpoints. The parser reconciles all 3,651 calls against each run's recorded call count and all final signaling answers and Domain judgments against `results.json`. It retains attempted saves separately from accepted checkpoints. There are 345 final Domain checkpoints and one accepted revision, not 346 independently scored Domains.

The private reproducibility script is `../rob2-kit-testing/suster/analyze_logs.py`; its outputs and detailed source-bearing case records remain beside the private dataset in `suster/analysis/`. This document contains aggregate observations and paraphrased analysis, not redistributed transcript or article passages. Reference labels are attributed to Suster's [Zenodo release](https://doi.org/10.5281/zenodo.11243025), CC BY 4.0.

Agreement figures below come from the supplied `SCORES5m.md`. The transfer does not include its row-level gold-label/tier join, so I could verify predictions and checkpoint counts but could not independently reconstruct the reference confusion matrices or label each inspected case a Cochrane disagreement. The cases establish specific process or premise problems, not an exhaustively adjudicated count of scientifically wrong answers.

## Domain results

The 57.9% headline concerns 56 assessed tier-A rows in 27 trials, comprising 280 cells. It is not a score over all 375 possible cells. Across all rows, 69 were assessed and six were `needs_input`; the assessed-domain agreement was 205/345, or 59.4%, versus a 62.0% same-cell Low baseline.

| Domain | Tier-A agreement | Always-Low on these cells | Above-reference / below-reference risk |
|---|---:|---:|---:|
| D1 randomization | 41/56, 73.2% | 46/56, 82.1% | 15 / 0 |
| D2 deviations | 27/56, 48.2% | 27/56, 48.2% | 17 / 12 |
| D3 missing data | 34/56, 60.7% | 37/56, 66.1% | 16 / 6 |
| D4 measurement | 29/56, 51.8% | 31/56, 55.4% | 16 / 11 |
| D5 selection | 31/56, 55.4% | 35/56, 62.5% | 22 / 3 |

The score report gives a trial-clustered interval of -15.1 to +5.8 percentage points for the tier-A margin against always-Low. This run has not demonstrated superiority to that baseline. The 86 above-reference and 32 below-reference errors are descriptive directions, not evidence that the reference is always scientifically correct.

The model exactly reproduced 53/104 non-Low reference labels. Some-concerns recall in D3 was 0/8. Optimizing raw agreement by encouraging Low would hide these distinctions. The earlier Haiku campaign changed model, host, kit, prompt, and number of draws together; it cannot identify a model effect. Different reasoning settings also are not substitutes for repeated draws at a fixed setting.

## 1. Search is often narrow and vocabulary-led

Across all 75 attempts:

- 1,854 searches, including 645 with zero candidates, or 34.8%.
- 363 truncated search responses; only eight calls used a search cursor. Continuing every ranking is unnecessary, but the low continuation count means the existence of deep cached retrieval does not establish its use.
- 230 `broad_any_truncated` diagnostics and just three prefix-mode searches.
- 244 `read_pages` calls. Median distinct main-article pages returned through that tool was five; these were often partial windows, not whole pages. Before the first Domain context, the median was three. Search previews and Domain context are additional delivery routes, so this is not a complete reading/attention measurement.
- Common zero-hit query strings included allocation concealment, sequence generation, and multiple analyses. These are assessment concepts that need not occur literally in reports.

A concrete retrieval failure is visible within Krolewiecki. Run r52 committed D1 sequence/concealment uncertainty without reading the main article's randomization section. The same captured article and projection contain an explicit sequence and allocation procedure on page 4. Run r89 selected it as Evidence and answered affirmatively. In r52, a page-4 randomization/masking preview appeared later during D2 discovery, but there was no D1 revision. This is a recoverable discovery and evidence-integration gap, without needing to assume a gold label.

The current server already has cached rankings, cursors, source diversity, explicit lexical modes, and no-hit widening. Reimplementing those would duplicate #283, #288, and #290. The missing workflow is to understand the report before translating questions into lexical searches, then retrieve for unresolved premises and contradictions.

Main-paper reading needs bounded coverage. Of 33 main sources, 23 have at most 15 pages, but ten exceed that and one has 100. Manuscripts and combined article/appendix files invalidate a universal 15-page cutoff. The required workflow in #300 now uses two text-only passes, before Proposal formation and after approval, with a 64 KiB source-text ceiling per report. The initial implementation allowed source-backed appended-document boundaries to shorten the scope; #305 subsequently removed that caller choice and retained the bounded full-Source prefix. Budget-limited coverage stays explicit, and targeted reading must resolve relevant premises beyond that prefix. A short source-linked orientation identifies trial design, randomized groups, analysis populations, ascertainment, flow, and available plans; delivery does not establish comprehension.

The companion Codex rollout logs show a median per-run peak of 131,281 input tokens and a maximum of 184,341; 42 runs exceeded 128,000. These are captured token-count observations, not unique new evidence tokens. Test orientation on the current text-budget baseline. Do not repeat the complete paper in every Domain context. Preserve exact handles and recoverable source ranges across approval/restart.

## 2. Domain 3 exposes interpretation failures after retrieval

Across the 69 assessed rows, D3 produced 38 Low, one Some concerns, and 30 High. Of those 30 High checkpoints, 24 used `no_information` at 3.4. The published decision table intentionally maps that active path to High. Rewriting the table or automatically converting NI to Probably no would be invalid.

The upstream reasoning is nevertheless inconsistent:

- Spencer r41 cites two departures among 83 recruited children and justifies a negative 3.1 answer by saying data were not available for all. That does not complete the separate nearly-all assessment. Other Spencer runs use the report's small overall missing-score fraction. The latter also needs endpoint-specific scrutiny; it is not automatically the correct answer.
- Wang r95 cites a passage describing one loss and one refusal in each of three groups plus two additional worsening-related dropouts. Its justification counts five rather than eight. Other Wang rows derive eight or nine, and differ over whether the fraction is nearly all. This is a source-to-count reasoning error, not a lexical retrieval miss.
- Beigel r50 uses the safety-analysis membership definition to justify unavailable outcome information, whereas r51 uses similar safety denominators to support nearly complete availability. Neither membership alone nor a small unexamined fraction establishes ascertainment.
- Barros r39 and Kalil r92 describe possible dependence or lack of contrary information as a reason for probable likelihood at 3.4. Possibility, probability, and inability to judge need distinct reasoning. This observation does not establish that their final High labels are wrong.

The existing D3 reference and #293 already warn against analysis-denominator proxies. Merely appending that warning again is low value. The current reconciliation helper computes from host-entered rows after submission; the first D3 comparison card has no such rows. Only 22 assessed runs submitted count rows. Make the existing arithmetic available before committing the scientific answer and give the host one compact availability/reason comparison to interpret. Arithmetic cannot establish that a count was correctly extracted or that missingness is outcome-dependent; those remain source-grounding tasks.

## 3. Operational instructions conflict with scientific judgment

The official response framework correctly permits probable judgments from trial circumstances. However, `get_domain_context` also sends the host the unqualified instruction `Do not infer semantic entailment`. ADR 0031 puts that restriction on the server, which cannot do scientific interpretation. Sending it as a host prohibition conflicts with the host's responsibility to interpret evidence.

The same context requires a new bounded search for every active question, even if sufficient passages are already available. This is stronger than checking evidence adequacy and can turn assessment into a sequence of vocabulary searches and uncertainty receipts.

Question-specific anchors can reinforce the problem. The D2.3 negative anchor describes ordinary non-adherence or protocol-consistent changes, instead of the full negative proposition that no trial-context-caused, protocol-inconsistent deviation occurred. No deviation at all should remain expressible. Probable options mechanically inherit definite-option anchors.

Observed consequences include Beigel r49 versus r50/r51 interpreting the same online randomization method differently, and Chalmers r53/r74 treating pragmatic adherence/contamination as trial-context causation while r93 treats it as ordinary behavior. D4 r64 in Ader moves directly to differential measurement based on awareness despite a stated common schedule; that requires examining actual detection differences separately from assessor influence. Existing D4 warnings did not prevent the shortcut.

Replace conflicting rules and overly narrow anchors with source-grounded decision criteria. Preserve the official NI conditions and uncertainty. A generic instruction to be less conservative, a target NI rate, or a new self-critique loop would be poorly justified.

## 4. D5 needs plan content, chronology, and cohort correspondence together

D5 had 39 NI answers at 5.1 and 42 Some-concerns Domain judgments across assessed rows. This is not itself a defect: sometimes the captured evidence really cannot establish a pre-unblinding plan. On the tier-A cut, however, 22 cells were above the reference risk level and three below it, making this a useful adjudication target.

The traces show inconsistent proof standards. Ader r86 used a currently captured registry endpoint to support probable prespecification. That registry's descriptive material refers to a later intervention phase of the platform, while the approved Result concerns an earlier comparison. A matching endpoint and registry ID do not establish that the same version applied to that cohort before outcome access. Conversely, Agarwal r8/r9 differ on accepting report-level plan statements without independently resolving the actual plan and timing.

The D5 comparison card currently fills the reported Result but leaves plan, unblinded access, amendment, and correspondence as unknown slots. Supply compact provenance and navigation for the existing Sources, and make the host compare the relevant plan passage, version/date, recruitment/intervention cohort, amendment, and performed analysis together. Unknown dates stay unknown. Current registry capture must not silently become historical protocol evidence. This prevents both unsupported reassurance and premature claims that no relevant plan exists.

## 5. The Result contract creates semantic and clerical friction

There were 212 Proposal save attempts: 75 reached review, 116 returned structured repairs, and 21 had no decoded domain response in the normalized capture. Sixty-eight runs encountered at least one structured Proposal repair. Repair items included 414 unsupported-value items, 52 endpoint-definition binding items, and 47 exact-name mismatch items. Multiple repair items can occur in one response; these are not counts of wrong final Results or false-positive repairs.

The exact-name rule is a concrete design problem. Scientific scope and lexical equality are different. The current contract rejects `exact` for normalization-unequal names and offers only broader/narrower/component/related alternatives. Spencer r41 records a broader relation while its rationale describes representation by the named instrument rather than an actual superset, illustrating the ambiguity. Separate exact source transcription from host/researcher-reviewed scientific correspondence. Continue to reject invented source quantities.

The 37 nonverbatim requested-outcome strings are an exposure flag, not 37 established scope errors. The skill explicitly moves timing and other facets into the Proposal; Ader r65 retains time-to-event semantics there. Evaluate whether requested facets survive into the reviewed target, rather than demanding literal full-string identity. A numeric pin also does not establish equivalent event definitions.

There were 70 structured Domain repair responses, including 50 missing-active-question items and 25 invalid-option items. These categories can overlap. Audit their causes under #295 before changing the branch API. The current post-run text-budget fix should also be evaluated before adding another general context compaction mechanism.

## 6. Confirm the scientific pack applies

Spencer's source describes allocation by classroom, but the product uses the individually randomized parallel-assignment pack. This calls for explicit applicability review, not silently relabeling the benchmark or treating children as the randomization units. The cluster variant includes additional recruitment considerations. Detect unsupported designs during the existing Proposal stage and expose the limitation; implementing all RoB 2 variants is a separate project. Keep these rows visible in evaluation coverage and report any adjudicated eligibility exclusions transparently.

## Toolkit versus model

| Finding | What can be attributed now | What remains unknown |
|---|---|---|
| Conflicting host instructions, mandatory searches, lexical-only exact relation | Concrete toolkit design weaknesses | Size of their accuracy effect |
| Main-paper section missed in one run and used in another | Recoverable workflow/retrieval failure | Whether broader reading reliably repairs it across models |
| Wrong dropout arithmetic despite a cited passage | Model interpretation error on delivered evidence | Whether pre-decision arithmetic or a stronger model repairs it reliably |
| Awareness/cause/likelihood shortcuts | Model reasoning weakness, despite existing guidance | How much improved prompts change behavior |
| Missing historical plan or unsupported design | Evidence/applicability limit | What additional sources or variant support would resolve it |
| Luna versus older Haiku scores | Confounded end-to-end comparison | Intrinsic model-capability difference |

No defensible percentage partition into kit errors and model limitations is possible from this one draw. A supplied-evidence condition with the same model isolates much of the discovery burden; the same evidence condition across models tests interpretation. Neither replay nor a model-generated rationale establishes expert correctness.

## Research implications and priority

The [Luna research note](2026-09-08-agent-evidence-research.md) covers Pi-Serini, long-context versus RAG, Lost in the Middle, BRIGHT, iterative rewriting, OpenScholar, and primary MCP/agent guidance. The transferable lesson is to control evidence delivery and measure its use. Pi-Serini does not prove BM25 is universally sufficient, and the other papers do not prove full-paper injection will improve RoB 2.

Prioritize bounded main-paper orientation and removal of contradictory Domain instructions, then D3 pre-decision reconciliation. Follow with D5 version/cohort evidence and Result-relation semantics. Add a small pack-applicability check for correctness. Defer dense retrieval, rerankers, model voting, extra critics, and new tool families until the simpler interventions have been tested.

Use #282 for blinded, expert-adjudicated reference construction and #295 for importing real observations. Split by trial/document family; do not tune on held-out outcomes from a trial already inspected here. Freeze source bytes, approved Result, kit, skill, model, and budget; compare one intervention at a time using repeated development draws and at least two model families. Report D1-D5 confusions, class recall, unsupported premises, evidence coverage, abstention, and total calls/tokens. Count trial clusters, not 280 independent observations. No accuracy uplift or estimated number of repaired cells is claimed in advance.

## Filed work

Astra Low reviewed the concrete drafts, requested narrower claims and explicit contract decisions, then approved the revised issues for publication. All six have `needs-triage` status.

- [#298 Remove conflicting Domain instructions on inference and discovery](https://github.com/AliSalman-et-al/rob2-kit/issues/298)
- [#299 Check trial-design applicability before using the parallel-assignment pack](https://github.com/AliSalman-et-al/rob2-kit/issues/299)
- [#300 Enforce bounded main-report reading before targeted evidence search](https://github.com/AliSalman-et-al/rob2-kit/issues/300)
- [#301 Evaluate D3 count reconciliation before committing scientific answers](https://github.com/AliSalman-et-al/rob2-kit/issues/301)
- [#302 Separate Result equivalence from endpoint-name equality](https://github.com/AliSalman-et-al/rob2-kit/issues/302)
- [#303 Project captured plan provenance and recovery paths into D5 context](https://github.com/AliSalman-et-al/rob2-kit/issues/303)

The existing [#282](https://github.com/AliSalman-et-al/rob2-kit/issues/282) and [#295](https://github.com/AliSalman-et-al/rob2-kit/issues/295) receive campaign-specific evidence and reconciliation counts instead of duplicate evaluation issues. D3 preview remains optional. Main-report reading is required by the revised #300 workflow; its accuracy benefit still needs evaluation. This note records the analysis behind those changes.
