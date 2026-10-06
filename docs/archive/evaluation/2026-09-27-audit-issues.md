# Published September 27 audit issues

Published as [parent #472](https://github.com/AliSalman-et-al/rob2-kit/issues/472), with native sub-issues [#473](https://github.com/AliSalman-et-al/rob2-kit/issues/473), [#474](https://github.com/AliSalman-et-al/rob2-kit/issues/474), [#475](https://github.com/AliSalman-et-al/rob2-kit/issues/475), and [#476](https://github.com/AliSalman-et-al/rob2-kit/issues/476). All have `ready-for-agent`. The user's subsequent accuracy-first instruction adds #476 as the direct residual scientific-reasoning repair, natively blocked by #475's adjudications.

Delivery order: scientific accuracy (#475 → #476, using existing #463/#468 comparisons and #464 qualification), then efficiency (#473/#474 under scientific non-degradation), then cost among scientifically qualifying candidates. Scheduling priority is distinct from code dependencies; the original three slices remain independently implementable.

The user approved this breakdown and its test seams on 2026-09-27, emphasizing maximum scientific accuracy as the primary objective and efficiency alongside it. Existing parent issues will not be modified or closed. The implementation work uses existing public MCP lifecycle and evaluator seams.

## Parent spec: Qualify scientific reasoning and reduce context friction after the September 27 benchmark

### Problem Statement

Researchers receive completed, independently verifiable assessments whose scientific warrants may still be unsupported. September 27 provisional agreement is 78/130 Domain labels, and an all-Low baseline already reaches 104/130. Existing infrastructure and scientific guidance cover many earlier defects, but their presence does not demonstrate accurate use. The latest campaign has extensive context delivery, no established model-capacity comparison, and no independently adjudicated correctness estimate.

### Solution

Keep the host-owned Reason–Act loop and model-free server. Make the existing factual checkpoint handoff usable, test a smaller complete context delivery path, and register source-grounded adjudications of the current development runs. Reuse the existing D2–D5, review, controlled-comparison, and held-out-qualification issues. Treat 80% as an adjudicated scientific target accompanied by class support, unsupported reassurance/concern, scope, completion, and cost.

### User Stories

1. As a researcher, I want each judgment to concern my approved Result, so that nearby endpoints cannot substitute for it.
2. As a researcher, I want defensible deviations retained, so that a provisional label does not override source evidence.
3. As a researcher, I want matching labels inspected too, so that unsupported reassurance is visible.
4. As a researcher, I want uncertain classifications preserved, so that an audit does not manufacture ground truth.
5. As a host, I want factual orientation retained across Proposal Review, so that useful reading need not be repeated mechanically.
6. As a host, I want changed Results to invalidate dependent interpretations, so that memory reuse remains scientifically scoped.
7. As a host, I want exact passages recoverable, so that notes cannot replace Evidence.
8. As a host, I want complete scientific guidance with less repeated scaffolding, so that important qualifiers remain usable.
9. As a host, I want partial or truncated delivery clearly recoverable, so that reduced output cannot hide missing context.
10. As an evaluator, I want all attempts retained, so that retries cannot inflate success.
11. As an evaluator, I want delivered evidence separated from available evidence, so that retrieval and reasoning can be distinguished.
12. As an evaluator, I want model and effort comparisons under a fixed harness, so that capacity claims are testable.
13. As an evaluator, I want Trial-separated qualification, so that repeatedly studied cases cannot masquerade as held-out evidence.
14. As a maintainer, I want measured improvements and acceptable no-change results, so that hypotheses do not become permanent machinery.
15. As a maintainer, I want existing issues reused, so that this audit does not create another overlapping rewrite.

### Implementation Decisions

- Preserve Proposal Review as the only researcher gate; add no embedded model, automatic reviewer agent, provider-specific scientific rule, search quota, or new evidence graph.
- Use the existing working checkpoint, including explicit host reassessment against the saved Result. Preserve Source/projection/Result identity checks and exact Evidence recovery.
- Measure the complete serialized/context delivery path before choosing a compact representation. Compare total bytes, calls, repairs, successful reconstruction, and premise validity. Keep official guidance and recovery routes intact; do not assume more aggressive summarization improves accuracy.
- Scientific accuracy is primary. Reject a cheaper/faster candidate that increases unsupported answers or loses decisive evidence. Predeclare the adjudication rubric and accuracy criterion before comparing candidates; an inconclusive small experiment is not evidence of equivalence.
- Extend the existing immutable adjudication/observation machinery for these development campaigns. Freeze run, Result, checkpoint, Source, pack, and reference identities. Do not overwrite human labels.
- Reuse scientific-reasoning and review work in #455–#458 and #462; model/effort comparisons in #463/#468; held-out qualification in #464. Several open issue capabilities already exist in the checkout.
- Preserve ADR 0035 aggregation and historical artifact semantics. Report its effect separately from model errors.

### Testing Decisions

- Primary behavior seam: public MCP/application lifecycle from captured Sources through Proposal Review, Domain saves, review, closure, and independent bundle verification.
- Checkpoint handoff: test unchanged versus changed Results, projection changes, absent/empty/stale notes, and restart. Count actual postapproval reads; test helpers must not secretly perform them.
- Context: reconstruct the same complete scientific view, preserve conditional question guidance and exact expansion, and test truncation/resume on supported hosts. Measure observed delivery rather than infer model comprehension.
- Adjudication: deterministic import and immutable provenance validation, scope exclusions, disagreements plus a prespecified agreement sample, and held-out leakage controls. Avoid testing an exact preferred search sequence.
- Existing suites are the prior art. No new evaluator or permanent generic framework is required.

### Out of Scope

Implementing all historical issues again; changing official Domain rules to match labels; claiming an accuracy gain without a controlled campaign; modifying overall policy; new retrieval backends without evidence; paid runs during this audit; production model lock-in.

### Further Notes

The audit is source-grounded triage, not independent expert adjudication. Higher effort or model capacity could improve interpretation of delivered evidence, but the observed runs cannot quantify that gain. New tickets below are narrow residual work; existing comparison and qualification tickets retain ownership of the larger experiment.

## Ticket 1: Carry report orientation through Proposal Review using the existing checkpoint

### What to build

The ordinary assessment workflow retains useful source-located observations across Proposal Review. Once the complete Proposal has been saved, the host reassesses and saves relevant observations against that Result before yielding for review. After approval it recovers current notes, resumes any unfinished reading, and retrieves exact passages as needed instead of mechanically repeating completed orientation.

This operationalizes an existing capability. A pre-Proposal checkpoint has no Result identity and becomes stale after Proposal creation; blindly copying stale Result-dependent notes is not the solution. Avoid another store, a new tool, or automatic claims of comprehension.

### Acceptance criteria

- [ ] Demonstrate the current checkpoint handoff through the public lifecycle and document the supported sequence in the portable assessment skill, consolidating contradictory or redundant instructions.
- [ ] Reassess observations and interpretations against the saved Result before rebinding; do not carry unsupported drafts across a change in scope.
- [ ] Unchanged approval and restart preserve valid factual orientation; changed Result/projection and absent notes retain identity-based recovery. Inadequate notes trigger host reorientation verified through trace/source review; do not imply that the server can determine semantic adequacy or add another approval gate.
- [ ] Exact Evidence remains recoverable; note presence does not establish comprehension or scientific sufficiency.
- [ ] A behavior test records actual read calls and proves useful notes can avoid redundant completed reading without helpers automatically satisfying the gate.
- [ ] A bounded development comparison reports checkpoint adoption, repeated source bytes, total calls, repairs, scope and decisive-premise validity. Keep no scientific accuracy claim without adjudication.

### Blocked by

None. The underlying checkpoint capability is implemented; #454 is related prior work, not a prerequisite to reimplement.

## Ticket 2: Qualify a compact complete Domain-context delivery path

### What to build

An assessment host obtains and recovers complete relevant Domain guidance and Evidence with less serial transport work, while retaining official qualifiers, active/conditional question semantics, source identities, contrary evidence, and exact expansion routes. Profile the existing paginated path first and evaluate the smallest compact candidate through the existing comparison harness; retain current behavior if no candidate improves the measured tradeoff.

### Acceptance criteria

- [ ] Freeze a representative set of complete context snapshots and installed-host captures, including large Result/Evidence sets and conditional branches.
- [ ] Before comparing candidates, record the primary efficiency measure, minimum useful reduction, scientific non-degradation criterion, adjudicator/rubric, and sample. Accuracy takes priority over efficiency; inconclusive results cannot establish scientific equivalence.
- [ ] Report first-page and continuation counts, serialized bytes, duplicated content, repairs, latency and available host token data separately. Image/base64 and structured/text duplicates must not be called model-context tokens.
- [ ] Test a bounded simplification of repeated instructions or transport scaffolding using the existing API. Do not add tools, another context store, or an unmeasured mandatory summary layer.
- [ ] The reconstructed scientific view retains full official guidance, Evidence identity, qualifiers, counterevidence, unknowns and exact recovery; stale views and partial delivery remain explicit.
- [ ] Compare against baseline with the same model, Sources, Result, pack, prompts other than the declared intervention, and stopping budget; retain all draws.
- [ ] Measure decisive-premise validity and unsupported answers alongside cost. Accept a documented no-change result when compression harms those outcomes or gives no material benefit.
- [ ] Record any actual live-contract/ADR change explicitly and preserve historical verification.

### Blocked by

None. Existing compact deltas and comparison machinery are present. This concerns model-facing delivery, distinct from server retrieval profiling in #461 and broad experimental capability in #463.

## Ticket 3: Register the September 26–27 scientific audit in the existing adjudication cohort

### What to build

Evaluators can reproduce the complete two-date trace inventory and both original scores, then inspect immutable source-grounded classifications tied to exact Results and decisive questions. Include every disagreement for triage and a prespecified agreement sample. Unreviewed cases remain unreviewed; this work does not create a retrospectively corrected accuracy score.

### Acceptance criteria

- [ ] Reconcile all JSONL files, retries, continuations and selected attempts; separate the September 27 issue-465 E2E checks from the 26-case benchmark.
- [ ] Reproduce 85/130 and 78/130 original Domain agreement and their different scope-eligible denominators without treating the campaigns as a controlled code/model comparison.
- [ ] Bind each reviewed classification to Trial, exact approved Result, Domain/question, checkpoint, Source/page or projection locator, reference/model labels, and reviewer provenance.
- [ ] Distinguish likely model error, defensible alternative, reference/scope issue, and indeterminate; separately annotate availability, retrieval, context delivery, interpretation, response mapping, and policy attribution.
- [ ] Review a declared sample of agreements for unsupported reassurance and concern; retain disagreements between reviewers and immutable revisions.
- [ ] Preserve all original labels and isolate development annotations from assessment workspaces. These Trials remain development material.
- [ ] Report adjudication coverage and class support; distinguish a defensible alternative from a certified human-label error. No model-capacity claim without the existing controlled comparisons.

### Blocked by

None. Reuse the adjudication machinery associated with #423; its September 21 cohort remains unchanged. #463/#468 and #464 consume the resulting development evidence under their existing obligations.

## Ticket 4: Improve scientific source-to-answer reasoning before optimizing transport and cost

## Parent

#472

## What to build

Improve the host's scientific source-to-answer reasoning on adjudicated, generalizable premise contrasts before optimizing transport or cost. Reproduce the residual errors with the current scientific pack and review path, then implement the smallest guidance or context-presentation change that improves those decisions. Keep the official signaling questions and deterministic decision tables intact.

The September 26 ARASENS OS assessment gives Q3.1 Probably yes because deaths plus censorings equal the analysis denominators, despite unknown censoring reasons. This is an unsupported warrant even though its Low label matches the catalog. September 27 CHAARTED OS infers trial-context causation from unmasked treatment refusals; that is an adjudication candidate, not an established error. TITAN AE infers differential measurement from longer median exposure despite a shared assessment schedule; the exact safety estimand must be adjudicated before selecting the expected response. Conversely, PEACE-1 AE documents extra laboratory surveillance in one set of arms, and TITAN D3 follows the official No-information branch: fixes must preserve defensible concern and uncertainty.

Use these observations to define mechanisms, not trial-specific answers. Existing #455–#458 and #462 already provide comparison cards, scientific distinctions, and decisive-claim review. This is a residual live-behavior repair and qualification of those capabilities, not another implementation of them.

## Acceptance criteria

- [ ] Use the immutable adjudications from #475 to select demonstrated unsupported warrants and clearly mark unresolved cases. Include matching-label errors and defensible deviations; do not optimize toward catalog labels alone.
- [ ] Build blinded, Trial-independent paired contrasts: analyzed/event/censor totals versus actual outcome completeness; ordinary care/non-initiation versus trial-context departures; unequal exposure versus genuinely different ascertainment opportunities; uncertain versus established plan applicability/chronology. Change one decisive premise at a time and retain official branch semantics.
- [ ] Trace whether the decisive passage and question guidance were actually delivered. Separate failed retrieval from incorrect interpretation of available evidence; do not call an available-but-unread document an oracle intervention.
- [ ] Implement and compare a minimal change to existing question guidance, portable skill, or existing context/review presentation at the demonstrated failure point. Remove superseded or repetitive instructions rather than append another generic checklist, schema, or mandatory reviewer agent.
- [ ] With model, effort, Sources, Result, tools, pack semantics, draw policy, and budget controlled except for the declared intervention, demonstrate improved adjudicated premise validity and no new unsupported reassurance or concern. Prespecify the rubric, cases, repeats, and acceptance rule; retain failures and inconclusive results.
- [ ] Preserve legitimate High/Some-concerns outputs and uncertainty branches. Do not impose a generic severity threshold or automatically convert uncertain answers to Low.
- [ ] Run the same contrasts using supported higher effort/model conditions through #468 to distinguish capacity-sensitive failures from system failures. Keep production behavior model-agnostic; do not require a particular provider to make the science work.
- [ ] Verify the complete public assessment path through correction, review, closure, and independent artifact verification. Feed qualifying improvements into #464's untouched Trial-separated evaluation; development contrasts cannot establish an 80% generalization claim.
- [ ] Optimize in this order: scientific accuracy, then efficiency, then cost. A cheaper/faster candidate cannot pass by sacrificing scientific validity; inconclusive accuracy evidence means hold, not promote.

## Blocked by

- #475: source-grounded adjudications establish which warrants are errors and which concerns must be preserved.

## Relationship to existing work

#455–#458/#462 own the scientific capability already present; #463/#468 own controlled comparison infrastructure; #464 owns held-out qualification. This ticket owns the concrete measured repair of residual inference failures after those capabilities were integrated. #473 and #474 remain useful follow-ups, evaluated under the same accuracy-first rule; scheduling priority is not an artificial code dependency.
