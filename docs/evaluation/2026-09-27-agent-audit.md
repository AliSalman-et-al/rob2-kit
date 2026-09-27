# September 26–27 agent and scientific audit

Audit date: 2026-09-27. Checkout: `8ae8016225afbb4586693655fd2a5ebdece08d48`.

Published work: [parent #472](https://github.com/AliSalman-et-al/rob2-kit/issues/472). Accuracy comes first: [adjudication #475](https://github.com/AliSalman-et-al/rob2-kit/issues/475) feeds [scientific reasoning repair #476](https://github.com/AliSalman-et-al/rob2-kit/issues/476). [Checkpoint continuity #473](https://github.com/AliSalman-et-al/rob2-kit/issues/473) and [context delivery #474](https://github.com/AliSalman-et-al/rob2-kit/issues/474) address efficiency subject to scientific validity. Cost is optimized only among scientifically qualifying candidates.

Evidence: [complete run/label findings](2026-09-27-audit-evidence/eval-findings.md), [scientific source review](2026-09-27-audit-evidence/scientific-findings.md), [code coverage and checkpoint experiment](2026-09-27-audit-evidence/code-findings.md), [research](2026-09-27-audit-evidence/research.md), [all 156 paired cells](2026-09-27-audit-evidence/case-cell-comparison.csv), and [machine-readable trace inventory](2026-09-27-audit-evidence/log-and-paired-scores.json). Reproduce the inventory with `.venv/Scripts/python.exe docs/evaluation/2026-09-27-audit-evidence/audit_run_logs.py` from this checkout; the frozen score files contain local bundle paths.

## Conclusions

The system completes an evidence-grounded workflow, but a verified artifact can contain an unsupported scientific inference. The September 27 benchmark does not establish 80% scientific accuracy. Its provisional Domain agreement is 78/130 (60.0%), versus 85/130 (65.4%) on September 26. These campaigns changed prompts, Result selections, scope eligibility, and code; their difference is not an identified causal regression.

The architecture already supports ReAct: the host chooses a scientific question, searches or reads, inspects an observation, updates its interpretation, and can correct a Domain before closure. The missing ingredient is not another orchestrator. Prioritize whether the host actually resolves the decisive premise, distinguishes observation from inference, and responds to counterevidence. Keep the server model-free and keep scientific sufficiency with the host.

Most broad remedies already have issues and substantial implementation. Reopening the same design with more schemas, mandatory review agents, embeddings, or longer instructions would add cost without demonstrated benefit. Reuse the existing scientific comparison cards, premise records, working checkpoint, review projection, and evaluation machinery. New work should address demonstrated residual gaps and test its benefit.

## What the scores establish

| Cohort | September 26 | September 27 |
| --- | ---: | ---: |
| All requested cases, Domain agreement | 85/130 (65.4%) | 78/130 (60.0%) |
| Scope-matched/equivalent primary score | 51/70 (72.9%) | 70/120 (58.3%) |
| All cases, overall exact agreement | 4/26 (15.4%) | 3/26 (11.5%) |
| All cases, overall Low/non-Low agreement | 21/26 (80.8%) | 21/26 (80.8%) |

The scope-matched denominators differ. September 27 includes 24 exact/equivalent cases and two accepted scope differences in its sensitivity score; September 26 has 14 primary-eligible cases, three accepted proxies, and nine other scope differences in its all-case report. Pairing by Trial and outcome alone does not establish identical Results.

September 27 all-case Domain matches are D1 25/26, D2 15/26, D3 11/26, D4 15/26, and D5 12/26. OS is 38/50; PFS 26/45; AE 14/35. The weakest strata involve analysis populations, missingness, ascertainment, and correspondence between plans and the selected Result.

The catalog is provisional and contains no reference High labels. An all-Low Domain baseline already matches 104/130 labels (80%). Therefore an 80% label-agreement target alone is inadequate. Keep the user's 80% aspiration, but assess it against independent, exact-Result, source-grounded adjudications; report unsupported reassurance, unsupported concern, non-Low/High support, scope correctness, completion, and cost alongside it. Review agreements as well as disagreements.

Sources: [September 26 report](../../eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium/trial-benchmark-report.md), [September 27 report](../../eval/runs/2026-09-27/rob2-trial-benchmark-latest-8ae8016/benchmark-report.md), and their machine-readable scores. The separate September 27 issue-465 E2E runs are workflow evidence, not additional independent benchmark cases.

## Trace findings

All 123 JSONL files under the requested dates were parsed: 59 on September 26 and 64 on September 27, including seven separate issue-465 E2E segments. There were no malformed JSON lines or byte-identical duplicate files. The inventory includes failed/retried attempts, not only the final selected bundles.

The latest official benchmark's 57 segments contain 2,345 completed MCP calls: 625 Domain-context calls (449 cursor continuations), 428 page reads, 184 single searches, 168 search batches, 60 renders, 24 visual-Evidence selections, and no working-checkpoint saves. The host is using search and visual tools; the absence of agentic tools is not the cause. Domain-context delivery accounts for 26.7% of completed MCP calls. Whether reducing it improves scientific reasoning remains an experimental question.

The latest run returned approximately 40.2 MB of serialized MCP results. This includes image payloads and potentially repeated structured/text representations; it is not a model-token or retained-context measurement. Of 184 single-search calls, 182 have observable match counts and 59 returned zero matches; two have no observable count and must not be counted as no-hits. This excludes queries inside search batches and does not prove a retrieval failure or scientific absence. Structured receipts include 46 repair responses and ten condition responses; 34 completed MCP records have no recognized structured outcome, rather than being presumed successful.

There were three reconnect/timeout error events. Raw save calls include repairs, retries, and unselected attempts: 153 Domain-save calls must not be described as 23 scientific corrections. The 26 selected bundles contain 131 Domain-history records, with only one repeated Domain history (ARASENS AE D3, Low to Low). The artifacts show no label-changing saved revision. They do not reveal whether the host internally reconsidered an unchanged answer.

The latest 20 High overall judgments include 16 cases with at least one High Domain and four produced solely by multiple Some concerns. The latter are GETUG-AFU-15 OS, STAMPEDE OS, ENZAMET PFS, and ARCHES AE. Overall-policy choice matters, but cannot explain most High outputs. There are 19 High Domain cells: D2 one, D3 ten, D4 eight.

## Source-to-answer examples

These classifications concern the recorded warrant, not a claim that a replacement final label has been established. Canonical records are reachable through each case's `bundle` field in the corresponding score JSON; question identifiers and source pages below make the findings auditable.

| Case and saved branch | Evidence and reasoning | Classification |
| --- | --- | --- |
| September 26 ARASENS OS, Q3.1 Probably yes; D3 Low, matching catalog | The justification adds deaths and censorings to recover analyzed denominators (229+422=651; 304+350=654), then concludes nearly complete availability. It acknowledges unknown censoring reasons. Registry counts and the CONSORT diagram establish analysis accounting, not whether censoring represents complete observation or lost follow-up. | Demonstrated unsupported inference in a matching label. Do not claim the final Low is necessarily false. This is a reasoning weakness after relevant facts were retrieved. |
| September 27 CHAARTED OS, Q2.3 Probably yes, Q2.4 Probably yes, Q2.5 No; D2 High | The model infers trial-context deviations from five withdrawals/refusals and one medical decision before starting chemotherapy, in an unmasked trial. It recognizes subsequent discretionary therapy as permitted care and preserves ITT. Individual refusal reasons are unknown. | Candidate causal-inference weakness: awareness and non-initiation do not alone distinguish trial-context effects from ordinary treatment decisions. Expert review must assess whether the circumstances justify Probably yes. |
| September 27 TITAN AE, Q4.2 Probably yes; D4 High | Main article PDF pp. 2–4 gives shared monthly CTCAE assessment and exposure medians 20.5 versus 18.3 months. The model infers differential ascertainment from unequal exposure despite the shared post-dose window. | Questionable premise requiring exact safety-estimand review. Exposure/time at risk is not automatically unequal measurement. Do not call it a proven error or prescribe Low without evaluating the observation window. |
| September 27 TITAN AE, Q3.1 NI, Q3.2 Probably no, Q3.3 NI, Q3.4 NI; D3 High | Main article PDF p. 4 reports 39 losses/withdrawals from all data collection; their AE-window timing and arm allocation are unavailable. The model explicitly rejects treating the safety denominator or planned follow-up as actual completeness. | Indeterminate scientific disagreement with catalog Low; the High follows the saved official uncertainty branch. A small overall loss fraction does not itself refute that branch. |
| September 27 PEACE-1 AE, Q4.2 Yes; D4 High | The saved answer cites additional AST/ALT/bilirubin monitoring in abiraterone arms, increasing opportunities to detect laboratory AEs within the severe-AE endpoint. | Scientifically defensible deviation from Some concerns. This is a concrete ascertainment mechanism, not merely an open-label or assessor-awareness inference. |
| September 27 STAMPEDE AE, Q4.2 Probably yes; D4 High | The saved answer links extra combination-arm assessments to visit-linked AE reporting. Separately, Q5.1 NI notes a SAP treatment-plus-30-day window versus the published entire-trial summary. Main article PDF pp. 6 and 10; SAP safety section. | Differential-visit concern is source-grounded; D5 plan applicability remains genuinely unresolved. Neither should be automatically optimized toward the reference label. |
| September 27 PEACE-1 PFS, D5 Some concerns | Supplement PDF p. 9 describes endpoint/testing amendments and says they were made without reference to outcomes. Amendment approval followed the reported cutoff; first unblinded access and final applicable SAP timing remain unresolved. | Defensible uncertainty, with counterevidence against result-driven selection retained. A chronology gap is not proof of misconduct or selective reporting. |

The audit deliberately rejected two initially tempting diagnoses: TITAN D3 High is not a decision-table bug simply because missingness is uncertain, and PEACE-1 AE High is not merely an overreaction to open labeling. Checking the exact question branch changed those classifications. This is why independent source-grounded adjudication is needed before claiming a scientifically adjusted accuracy percentage.

## Attribution rules

Use four scientific categories: likely model error, defensible alternative, reference/Result-scope problem, and indeterminate. Separately record the failure stage: source availability/projection, retrieval, delivered context, interpretation, response mapping, or deterministic policy. An incorrect premise can accompany a matching label; a mismatching label can be scientifically defensible.

Do not infer absence from a zero-hit search, correctness from an Evidence handle, comprehension from delivered text, or successful semantic review from calling `review_trial`. A structured support relationship is the host's assertion, not an entailment check.

D3 needs particular care. Analysis membership, event-plus-censor counts, and treatment discontinuation are not interchangeable with outcome availability. Conversely, the official Q3.2 asks for evidence that missing data did not bias the result; No/Probably no in the absence of such evidence is not itself a bug or proof of bias. Follow the official activation and decision rules rather than modifying them to match Low catalog labels.

For D4, distinguish method suitability, detection opportunities, assessor awareness, susceptibility, and likely influence. For D5, distinguish an unavailable plan, an inapplicable plan, uncertain chronology, multiple eligible analyses, and evidence of result-dependent selection. These distinctions already appear in the scientific guidance; qualification must test whether they survive actual use.

## What a stronger model might fix

| Failure | Capacity hypothesis | Engineering response |
| --- | --- | --- |
| Relevant passage delivered, but wrong proposition inferred | Higher effort or a stronger model may help | Test with identical supplied evidence and exact Result; inspect answer warrant |
| Host fails to seek a relevant plan, qualifier, or contrary fact | Either search policy or model ability may matter | Contrast natural retrieval with actually delivered decisive passages |
| Long context, unused working notes, repeated reading | A larger context/model may tolerate it; benefit unmeasured | Use existing durable notes and focused recovery; measure total calls and bytes |
| Tool output validation/projection/transport error | Model upgrades cannot repair server behavior | Fix the demonstrated boundary defect and verify recovery |
| Ambiguous reference Result or label | Model upgrades cannot establish ground truth | Preserve labels, adjudicate separately, retain uncertainty |
| Overall aggregation convention | Not a model-capacity failure | Report ADR 0035 policy separately; change only by explicit versioned decision |

Neither existing campaign isolates model capacity. Run the existing frozen launcher with the same tools, prompts, Sources, approved Results, pack, stopping budget, draws, and scorer. First compare baseline repeats with delivered decisive evidence; then compare effort and model while holding the harness fixed. Persist all failed and resumed draws, runtime identity where observable, and total cost. A supplied-evidence arm diagnoses reasoning; it is not production accuracy.

## Design direction

1. Make the next action discriminate between plausible scientific answers. A search should resolve a material premise or bounded uncertainty, not satisfy a search-count ritual. Batch only independent known queries; choose reformulations after inspecting observations.
2. Carry useful source orientation through Proposal Review using the existing working checkpoint. Reassess notes against the saved Result; do not silently transfer Result-dependent drafts when scope changes. Avoid adding a second memory layer.
3. Reduce model-visible repetition only after measuring actual delivery. Preserve full official guidance and exact passage recovery. A byte count is not a token count or an attention measurement. Do not remove scientific qualifiers merely to reduce context size.
4. Use the existing Trial review to inspect judgment-driving links, then correct only affected Domains. Add no mandatory second model or extra researcher gate. Self-review may share the original error and must be evaluated.
5. Qualify scientific behavior on Trial-separated cases with contrasting mechanisms, including genuine High and non-Low cases. Use the current oncology Trials for development; they have already informed the design repeatedly.

A public-lifecycle scratch test verified the existing checkpoint path: current before Proposal, stale after Proposal save, current after a host save against that Result, still current after approval, then successful first Domain save without a postapproval report reread. The helpers used do not automatically read the main report at that step. The test passed (one test, 9.50 seconds). This establishes mechanical feasibility, not adequacy of the notes or an accuracy improvement.

The model-facing static inventory is substantial: 18 tools expose 73,082 UTF-8 bytes of serialized input schemas and 11,811 description bytes. The main skill is 27,201 bytes; nine on-demand references total 67,935 bytes. These are asset measurements, not proof that every host loads all assets at once. Test compactness at the actual host boundary. Scientific accuracy takes priority: predeclare the rubric, sample, and scientific acceptance criterion, and reject cost savings that lose decisive evidence or increase unsupported answers.

## Existing work to reuse

| Area | Existing issues | Audit implication |
| --- | --- | --- |
| Working observations and compact context | #454 | Current checkpoint capability exists; qualify its use across Proposal Review |
| D2–D5 scientific reasoning | #455, #456, #457, #458 | Test residual source-to-answer errors; do not duplicate broad guidance tickets |
| Navigation and projection | #459, #460, #327, #339 | Diagnose a missing decisive passage before adding a retrieval backend |
| Retrieval performance | #461 | Optimize measured costs only |
| Decisive-claim review | #462 | Existing projection must be used scientifically, not merely called |
| Controlled comparisons and models | #463, #468 | Capability exists in the checkout; execution and scientific qualification remain distinct |
| Held-out qualification | #464 | Remains necessary; current development scores cannot satisfy it |
| September 26 fixes | #465–#469 | Several are implemented despite open issue state; do not recreate them |
| Immutable adjudication | #423 | Reuse its machinery; its original cohort is September 21 |

## Research basis

[ReAct](https://arxiv.org/abs/2210.03629) supports interleaved reasoning and external actions, not unlimited tool calls. [Anthropic's tool-design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents) supports inspecting trace-level tool friction before adding tools. [Context engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) supports focused retrieval and durable context. [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) provide typed communication, not scientific validation. [OpenAI agent evaluations](https://developers.openai.com/api/docs/guides/agent-evals) and [reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning) support controlled, representative evaluation rather than assumed gains from more effort.

[Cochrane Chapter 8](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08) makes RoB 2 Result-specific and distinguishes probable answers from No information. Its multiple-Some-concerns overall criterion includes substantially lowered confidence; the repository's fixed threshold is an explicit policy under ADR 0035. This audit does not change that policy.

## Verification and limits

The focused suite passed 128 tests covering deterministic logic, scientific semantics/guidance, Trial review, bounded Domain context, comparison launching, and benchmark scoring. Command: `.venv/Scripts/python.exe -m pytest -q tests/test_logic_evaluator.py tests/test_scientific_semantics.py tests/test_agentic_search_scientific_guidance.py tests/test_trial_review_projection.py tests/test_bounded_domain_context.py tests/test_development_comparison_launcher.py tests/test_score_trial_benchmark.py` (92.17 seconds).

`uv run pytest -q` could not launch because the local uv trampoline failed to canonicalize its script path. The focused run used the existing virtual environment directly. This is not a full-suite pass, and no paid model benchmark was launched.

The audit covers architecture and critical code paths across the active package, skills, MCP, scientific pack, workflow, retrieval/projection, storage/provenance, evaluator, and benchmark scripts. It does not claim line-by-line review of every historical fixture/test or expert adjudication of every Domain cell. Source-grounded examples are triage evidence, not a corrected scientific-accuracy estimate.
