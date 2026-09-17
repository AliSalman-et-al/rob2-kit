# Refine Domain accuracy through evidence, context, and workflow

Approved on 2026-09-16. Synthesized from the
2026-09-16 session and the supplied accuracy refinement plan. This is a successor
to [the adaptive assessment overhaul](https://github.com/AliSalman-et-al/rob2-kit/issues/349),
not an instruction to recreate functionality already present.

## Problem Statement

Researchers need scientifically defensible D1-D5 assessments of the specific
comparative Result they approved. rob2-kit can complete and verify an assessment
while the host confuses what a Source establishes with what a signaling question
asks. Useful guidance may not reach the decision point, incomplete passages may
hide qualifications, and mechanical recovery can consume the attention needed
for interpretation. More warnings or a more permissive default cannot reliably
solve these problems.

The supplied post-overhaul reports cover 25 Trial-Result assessments across ten
Trials and 125 Domain outputs. Their displayed labels give 76/125 exact and
88/125 Low/non-Low agreement with provisional references. D3 and D5 account for
28/49 disagreements. All seven D4 disagreements cross Some Concerns to High;
all eight AE D5 predictions are Some Concerns. These patterns prioritize
investigation, but do not establish a shared cause or prove that the kit is wrong.

The references contain 101 Low, 24 Some Concerns, and no High labels. Six initial
Result proposals needed scope correction. Agreement is therefore conditional on
approved scope and is not independently adjudicated scientific accuracy. The
overall Trial label follows the deterministic Cochrane convention: all five
Low is Low; one Some concerns and no High is Some concerns; any High or at
least two Some concerns is High. Overall and Domain agreement remain separate;
neither overall agreement nor fewer High predictions is the optimization target.

## Solution

Improve the complete path from approved Result through inspected Evidence to
each official signaling answer. Keep one adaptive host agent and a deterministic,
model-free server. Make relevant scientific distinctions easy to apply, preserve
complete recoverable Evidence, and remove avoidable copying, rereading, stale
receipts, and repeated retrieval work.

Use available assessment artifacts to identify the earliest demonstrated faulty
transition. Distinguish kit defects from unsupported model inferences, defensible
differences from Suster references, reference/scope uncertainty, and unresolved
causes. Review changes autonomously against Sources and official guidance; do
not wait for human adjudication. Prioritize high-yield general mechanisms,
especially D3 and D5, and test both their benefits and their regressions.

## User Stories

1. As a researcher, I want D1-D5 judgments supported for my approved Result, so that the assessment addresses the question I actually asked.
2. As a researcher, I want overall judgments reported separately, so that an aggregation rule does not conceal Domain performance.
3. As a researcher, I want defensible differences from provisional labels retained, so that benchmark agreement does not replace scientific judgment.
4. As a maintainer, I want failure causes supported by observable artifacts, so that I fix kit weaknesses without assuming a model capability ceiling.
5. As an evaluator, I want original references and attempts preserved, so that revised interpretations cannot rewrite the benchmark history.
6. As an evaluator, I want scope comparability recorded explicitly, so that different Results are not silently scored as the same assessment.
7. As an evaluator, I want eligible cases without labels counted operationally, so that missing references do not look like missing outputs.
8. As an evaluator, I want representative agreements inspected too, so that a matching label cannot hide a wrong premise.
9. As an agent, I want the official proposition, permitted answers, and applicable guidance together, so that I distinguish neighboring answers correctly.
10. As an agent, I want project guidance distinguished from official rules, so that a convenience instruction cannot silently alter RoB 2.
11. As an agent, I want complete Evidence and expansion routes near my draft, so that qualifiers and counterevidence remain inspectable.
12. As an agent, I want observations, inferences, and unknowns separated, so that absence of reporting does not become a stronger claim.
13. As an agent, I want randomized, analyzed, observed, and imputed counts distinguished, so that D3 arithmetic uses comparable quantities.
14. As an agent, I want follow-up cessation reasons and timing visible, so that administrative censoring is not mistaken for missing outcomes.
15. As an agent, I want D3 availability, bias mitigation, possible dependence, and likely dependence considered separately, so that one uncertainty does not answer several questions.
16. As an agent, I want missingness assessed relative to the Result, so that an arbitrary percentage does not decide risk of bias.
17. As a researcher, I want AE severity, event definition, units, population, and window distinguished in the Proposal, so that a related endpoint is not silently substituted.
18. As a researcher, I want progression and failure-free endpoints compared explicitly, so that the numerical Result retains its actual definition.
19. As an evaluator, I want the benchmark selection convention available before Proposal selection, so that scope correction is not needed to reveal the task.
20. As an agent, I want a competing candidate shown when ambiguity is consequential, so that I can explain my proposed Result without listing every endpoint.
21. As an agent, I want plan content and timing matched to the Result, so that document existence or retrieval date does not stand in for prespecification.
22. As an agent, I want contextual D5 judgments permitted where official guidance supports them, so that an inaccessible SAP is not an automatic veto.
23. As an agent, I want eligible measurements distinguished from eligible analyses, so that multiplicity alone does not establish results-based selection.
24. As an agent, I want assessor awareness distinguished from possible and likely influence, so that D4 does not reuse open-label status as every premise.
25. As an agent, I want D1 grounded in the actual randomized comparison, so that unchanged allocation evidence is interpreted consistently across outcomes.
26. As an agent, I want D2 based on analysis membership and group assignment, so that ITT or safety-set labels do not substitute for the facts.
27. As an agent, I want complete long lines and continued tables recoverable, so that transport limits do not remove decisive evidence.
28. As an agent, I want partial batches to retain independent successes and exact continuations, so that one oversized result does not erase useful work.
29. As an agent, I want short server-bound context handles, so that continuing a frozen view does not require copying encoded payloads.
30. As an agent, I want visual methodological Evidence usable with honest provenance, so that image-only methods can support an answer.
31. As an agent, I want valid Domain receipts to survive unrelated progress, so that investigation does not force scientific answers to be resubmitted or changed.
32. As an agent, I want actionable repair conditions, so that a structural repair does not pressure me to reverse an answer.
33. As an agent, I want source-bound working notes after approval and compaction, so that I can recover open questions without compulsory duplicate reading.
34. As an agent, I want missing or stale notes to trigger reorientation, so that working memory never becomes scientific authority.
35. As an agent, I want retrieval reuse to avoid actual recomputation, so that more of the operating budget remains for useful investigation.
36. As an agent, I want compact preclosure review of concrete tensions, so that I can correct affected Domains without repeating the whole assessment.
37. As an auditor, I want corrections and closure bound to exact checkpoints, so that exported history remains attributable and independently verifiable.
38. As an evaluator, I want unavailable Results to finish with truthful terminal metadata, so that absence of a comparative Result does not crash continuation.
39. As an evaluator, I want platform-aware launch preflight and byte-preserving arguments, so that infrastructure failures do not contaminate evaluation.
40. As a maintainer, I want balanced fictional controls and all retained evaluation draws, so that improvements generalize beyond familiar Trials and Luna.
41. As a maintainer, I want scientific gains, regressions, completion, and cost reported separately, so that I can make an informed promotion decision.
42. As a maintainer, I want autonomous methodological review with stated uncertainty, so that progress does not depend on a new human review gate.

## Implementation Decisions

- **Architecture and authority.** Keep the host as the only assessment model and the server as the owner of deterministic rules, durable state, exact Evidence, validation, and export. Preserve individually randomized parallel-group trials and the effect of assignment. Proposal Review remains the researcher gate. Offline agent review of evaluation evidence adds no production answer authority.
- **Source boundary.** Use the captured dossier and supported intake registry capture. During assessment, do not acquire other documents or unseen historical registry versions. Product behavior and controlled registry replay remain distinct. Preserve missing-source conditions instead of pretending unavailable material was inspected.
- **Evidence status.** Label findings as measured, code-observed, reproduced, hypothesized, or proposed. A selected Evidence handle or completed delivery receipt does not prove a premise was understood. Trace approved Result, captured Source/version, delivered passage, selected Evidence, justification/unknowns, answer history, and deterministic rule. Preserve an unresolved classification when evidence is insufficient.
- **Attribution and priorities.** Diagnose D3 and D5 first, followed by D4 and D1/D2, while independent correctness and efficiency repairs proceed. A residual interpretation failure with adequate delivered context is a possible host limitation, not proof of an intrinsic model ceiling. Do not insert case names, expected benchmark labels, or Luna-specific scientific rules into production assets.
- **Question context.** Reuse the scientific pack and existing Domain context projection. Deliver the exact proposition, legal answers, applicable bias construct, concise answer distinctions, Result scope, and current supporting/counterevidence together. Preserve complete official guidance through recoverable continuation. Keep unrelated discovery candidates optional. Compare a concise decision view with the existing view before making additional content compulsory.
- **Scientific rules.** Verify the pinned official wording, activation, legal responses, uncertainty branches, and Domain rule mapping. Correct genuine implementation discrepancies, but do not alter a valid evaluator branch to compensate for an unsupported upstream answer. Mechanical checks validate identity, scope, coordinates, numeric consistency, and dependencies; they do not infer entailment from keywords or nonempty prose.
- **D3.** Reuse existing comparison records and arithmetic. Classify counts by meaning, arm, population, outcome, and window before comparison. Unknown is not zero; analyzed is not observed; discontinuation is not automatically loss to follow-up. Make observed follow-up and reasons for cessation inspectable for time-to-event Results. Keep availability, bias mitigation, possible dependence, and likely dependence distinct. Preserve legitimate No information and High branches, outcome-sensitive materiality, and balanced sensitivity-analysis reasoning.
- **Result selection.** Reuse Result fields before adding types. Distinguish AE severity, seriousness, attribution, participant/event units, population, comparison, and window. Preserve exact progression definitions and numerical Results. Show a competing candidate only for consequential ambiguity. Abstract selection is an evaluation convention, not a product eligibility rule. Scope replacement requires renewed Proposal approval and fresh affected assessments, with history preserved.
- **D5.** Inspect actual answers to 5.1-5.3 before attributing the repeated AE judgment. Match plan content, population, comparison, endpoint, analysis, timing, and captured version. A posting/update/retrieval date does not automatically establish plan finalization. Audit restrictions against official contextual judgments without assuming a plan's existence proves correspondence. Separate eligible measurements, eligible analyses, and actual results-based selection.
- **D4.** Present the assessor, measurement method, detection opportunities, awareness, susceptibility, and circumstances supporting likely influence. Do not require direct empirical proof of bias where methodological circumstances suffice. Do not make open-label AE automatically High or OS automatically Low.
- **D1/D2.** Test allocation invariance only when the randomized comparison, cohort, and Sources are unchanged. Reuse source facts rather than prior labels. Keep sequence generation and concealment separate. For D2, inspect actual exclusions and grouping, trial-context deviations, and missing versus available-but-excluded outcomes; a customary safety set does not change the assignment-effect target.
- **Domain validity and Trial review.** Decouple unchanged Domain receipt validity from requirements caused by other Domains. Compute the overall decision at the fifth Domain checkpoint with the deterministic Cochrane convention above; do not ask the researcher to override or explain the aggregation. Keep exact retries, stale scientific-dependency rejection, and immutable history. Extend existing review with concise answers, decisive justifications, unknowns, counterevidence, and Evidence expansion. Reinvestigate concrete tensions; do not add a compulsory second assessment or endless critic loop.
- **Transport.** Budget complete serialized UTF-8 responses, including metadata, cursors, and errors. Use lossless fragment continuation for oversized physical lines with truthful line/character extents. Preserve successful independent batch items and continuations for undisplayed content. Never let a partial handle certify unseen text. Keep search-ranking exhaustion distinct from delivery completeness.
- **Frozen context.** Replace encoded snapshot payloads with short opaque server-bound references to existing frozen views. Preserve Trial, Source, Result, pack, preview, and relevant checkpoint binding. Unrelated discovery must not make a valid frozen page chain unusable. Expired or genuinely stale references need actionable recovery without silently adopting a different scientific basis.
- **Visual Evidence.** Align tool descriptions and skills with supported host-observed methodological transcription. Require actual image delivery and exact Source/page/region/render provenance. Keep host observations distinct from machine-verified text and preserve uncertainty and contradictions.
- **Recovery.** Reuse valid working checkpoints for orientation after approval or compaction. Remove unconditional duplicate prefix reading when recovery context remains usable. Reinspect material uncertainty and reorient when notes are missing or stale. Notes and delivery receipts never certify understanding; a cold retrieval cache is not lost scientific context.
- **Retrieval efficiency.** Reuse verified positive and negative rankings and requested windows without rebuilding FTS/candidates on every warm call. Preserve exact scoped ranking, authoritative Source checks, restart validation, and corruption rejection. Use bounded local reuse, grouped work, and page-offset reuse where demonstrated useful. Measure actual builds, inserted rows, queries, candidate reconstruction, bytes, transactions, latency, and cost, not just a counter named cache build.
- **Evaluation plumbing.** Project scope metadata by Result kind without inventing absent fields. Preflight platform-specific executables and supported isolation before artifacts or paid work. Preserve Unicode/space arguments, no-UAC behavior, explicit unsupported-mode failure, and all failed attempts. Separate eligibility, available reference labels by Domain, scope comparability, output completion, and scored-attempt selection.
- **Change discipline.** Make each improvement a complete observable behavior across affected models, public contracts, generated examples, skills, and verification. Prefer existing seams and fields, remove obsolete assumptions, and amend conflicting ADR text explicitly. No speculative framework, wide compatibility migration, or stand-alone prefactor is required by this spec.

## Testing Decisions

- Use the existing public application/MCP workflow as the primary behavioral boundary, driven as a real caller from intake through Proposal, approval, Evidence access, Domain commitment, review, closure, and export. Existing lifecycle, comparison-card, receipt-replay, working-checkpoint, bounded-context, and evidence-delivery tests provide prior art. Reuse their setup rather than introducing another harness.
- Verify official activation and judgment behavior at the existing pure evaluator/oracle boundary. These tests prove rule mapping, not model interpretation. Independently verify persisted artifacts through the existing standalone verifier.
- Use installed-host checks where actual visibility matters, especially complete text, required question context, errors, and image pixels. Count server response, transport delivery, and model use separately. A direct function test cannot establish host-visible delivery.
- Extend existing fictional contrasts with premise-changing pairs, paraphrases, distractors, negations, omitted qualifiers, continued tables, and visual contradictions. Cover both justified concern and justified reassurance. Review expected answers autonomously against the official version and Source evidence, recording defensible alternatives and uncertainty. Do not depend on human adjudication or another model family to proceed.
- For scientific guidance changes, require a demonstrated general failure mechanism and paired controls. If archived artifacts are unavailable, use an explicit reproducible fictional mechanism and leave its relevance to the benchmark unproven. Do not reconstruct missing rollouts or silently invent a causal explanation.
- Reproduce engineering defects at the public boundary before fixing them. Test multibyte long-line reconstruction, exact fragment Evidence, bounded whole batches, stale handles, unchanged receipts after unrelated commits, genuine dependency changes, unavailable Result completion, truthful denominator counts, and warm/restart/corruption retrieval equivalence.
- Use the existing qualification runner with predeclared small development comparisons and retain every draw. Freeze candidate build/pack/skill, Sources and registry bytes, prompts, scope convention, host/model settings, budget, scorer, and retry rules before one updated cohort wave. Use the established Codex Luna Medium configuration for comparability; production policy remains model-agnostic. Do not rerun the archived baseline or selectively retry scientific disagreements.
- Report first-Proposal acceptance and scope corrections separately from postapproval D1-D5 agreement. Report per-Domain and per-outcome exact/binary agreement, full confusion matrices, both disagreement directions, reference availability, scope uncertainty, completion, failed/retried attempts, and cost. Cluster uncertainty by Trial. High sensitivity is unestimable in the supplied cohort because no reference is High; use separate genuine-High fictional challenges without presenting them as cohort sensitivity.
- Balance source-supported scientific gains and regressions explicitly. Do not impose zero label regressions, a preferred distribution, or an arbitrary accuracy threshold. Distinguish defensible label differences from new unsupported reassurance or missed genuine concerns. Engineering integrity, official rule correctness, authority, and provenance remain requirements, not score trade-offs. If evidence does not support a net benefit, retain or revise the candidate rather than claiming improvement.
- Previously inspected Trials are development evidence, not an untouched holdout. One wave does not establish repeatability, cross-model performance, or unseen-trial accuracy. Later reliability work needs fixed repeats with every draw retained; broader claims require appropriate independent evidence. Neither is a new prerequisite for this refinement.

## Out of Scope

- Optimizing the published overall aggregation beyond the deterministic Cochrane convention, forcing Suster-label agreement, suppressing High judgments, or trial-specific/model-specific scientific policy.
- A second production assessor, human answer/adjudication gate, new judgment override, or conversational answer coaching after Proposal approval.
- Additional trial designs/effects, runtime acquisition of other documents, unseen historical registry versions, or silent OCR authority.
- Vector databases, neural rerankers, fine-tuning, self-evolving memory, generic agent frameworks, private reasoning transcripts, and mandatory Claude qualification.
- Recreating already implemented overhaul features, closing existing parent issues, rerunning historical baselines, selective scientific retries, or claiming generalization from this exposed cohort.
- Code implementation and paid evaluation execution during the specification/ticket handoff itself.

## Further Notes

The examined basis is commit `5f5bca7f64ef21c95d8af9eee39178248d483a87`,
rob2-kit 0.9.0. Preserve its supplied report comparison separately from the older
baseline referenced by the overhaul issue. The benchmark counts above were
independently recomputed from the supplied plan's embedded trial-level tables
during this handoff. The diagnostic ledger must also reconcile retained
machine-readable labels and attempt identities without assuming that this table
recomputation verifies the underlying assessments.

This session supersedes older planning requirements for mandatory human
adjudication, a blanket ban on any scientific regression, and compulsory
postapproval prefix rereading when valid orientation exists. It preserves
researcher Result approval, official decision rules, independent artifact
verification, and the captured-source boundary. Related existing work includes
[D3 interpretation](https://github.com/AliSalman-et-al/rob2-kit/issues/347),
[reference scope](https://github.com/AliSalman-et-al/rob2-kit/issues/348),
[context delivery](https://github.com/AliSalman-et-al/rob2-kit/issues/315), and
[overhaul qualification](https://github.com/AliSalman-et-al/rob2-kit/issues/361).
Their open status alone does not mean their original behavior is unimplemented.
New tickets specify remaining gaps and do not close or rewrite these issues.

Primary-source guidance informs design choices, not claimed rob2-kit effects:

- Clear tool schemas, structured outputs, and observable tool failures support predictable recovery. Verify behavior against the implementation's negotiated MCP version; this [MCP tool specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) is a dated reference, not a mandate to change protocol versions.
- Distinct workflow-oriented tools, meaningful response content, and bounded responses support the proposed interface review. Transfer to rob2-kit remains a hypothesis to test. [Anthropic tool guidance](https://www.anthropic.com/engineering/writing-tools-for-agents).
- Outcome, trajectory, cost, and repeated-run performance are different evaluation dimensions. Accept valid alternative tool paths. [Anthropic agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
- Use contextual scientific judgments and preserve uncertainty rather than substituting universal missingness thresholds or an automatic missing-SAP rule. Check every operational anchor against the pinned RoB 2 materials. [Cochrane RoB 2 FAQ](https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2).
