# Next scientific evaluation: frozen design, no-go for inference

**Stopping decision: no launch.** A credible distinct actual case exists, AWARD-CHN3, but the evidence/input/cost prerequisites are not complete. This package preserves the specific comparison, primary evidence, preregistered private rubric and blockers. It does not manufacture a new implementation, fictional benchmark control or ready-to-run claim. No outputs have been generated.

## Implemented change and matched comparison

Test the target-versus-reported-result comparison-card presentation introduced in `56faa95`, using one tool-free baseline-versus-current pair on AWARD-CHN3. [Baseline](baseline-presentation.json) removes only `reported_result`, `target_relation`, target `scope_basis`, and the target/result instruction prefix from the [current card](current-presentation.json). All remaining current card content, including later D2 guidance improvements, stays identical. Card IDs are omitted equally as irrelevant transport metadata. This is a feature ablation within current code, not a historical whole-checkout comparison; the effect of individual fields versus the instruction cannot be separated.

Both arms must receive exactly the same [approved result, target, official question/guidance and generic task](common-target-and-question.json), full independently adjudicated relevant evidence, and output format. The reported result is also present in the common approved-result object in **both** arms. Thus the current card colocates/clarifies facts already available to baseline; it does not supply baseline with less scientific evidence. The question and task must not mention the known failure mechanism, desired answer or private rubric. Fresh sessions, identical verified `gpt-6-luna`, `medium`, no tools, browsing, prior domain judgments or old conversation; no provider substitution. Assign arm order before calls and withhold arm labels during adjudication. A single pair is descriptive, not a causal estimate robust to stochastic variation.

The generic question is exact RoB 2 2.6: “Was an appropriate analysis used to estimate the effect of assignment to intervention?” If N/PN/NI, evaluate exact conditional 2.7. The same fixed question applies to both arms, with the same permitted answers and captured official guidance. This targeted tool-free diagnostic does not save an incomplete domain or produce server labels; production activation and domain/overall labels remain server-owned. It cannot establish production completion or domain-label improvement.

AWARD-CHN3 was selected for a documented analysis-conduct mechanism, not its archived label. It is distinct from the closed Bendix, EMPEROR, RECOVERY and EXSCEL paid loops. It was included in the October 1 campaign, so is **not held out or a new corpus**. The archived relation is `exact`; this is preserved in both arms, not independently certified as full estimand alignment. Human reference alignment remains unresolved. No reference label or old domain answer enters the model input.

## Actual primary evidence and natural control

Authoritative source: October 1 AWARD-CHN3 archive in `/home/ali/Documents/Code/rob2-kit-benchmark`, hash and full path in [readiness record](readiness.json). Primary publication: Wang et al., *Diabetes Obesity and Metabolism* 2023;25:3690–3699, DOI `10.1111/dom.15263`, local Code corpus `trials/award-chn3-2023/dom.15263.pdf`. Page numbers below are native physical pages; line numbers are the frozen October 1 text projection, not re-extracted PDF coordinates. [Primary fact locations](primary-fact-locations.json) and [captured text packet](complete-captured-text-packet.txt) retain exact passage context.

- Main page 3, lines 89–101: efficacy/safety in randomized participants receiving ≥1 dose, efficacy censored at rescue therapy or premature study-drug discontinuation; continuous endpoints use MMRM. Page 3, lines 102–107: LOCF concerns additional secondary composite endpoints, not the primary continuous HbA1c analysis.
- Main page 3, lines 119–120 and page 4, lines 1–3: **all 291 randomized received treatment**, 144 dulaglutide / 147 placebo; 276 completed study. This is a decisive natural control against inventing a never-treated exclusion caused by the ≥1-dose rule. Completion is not proof of week-28 measurement or use of recorded values.
- Main page 3, lines 53–56: rescue treats severe persistent hyperglycaemia while study drug continues. This makes prognosis/analysis conduct relevant; it does not quantify the primary result's bias.
- Main page 5, lines 1–11, Figure 2 caption: primary HbA1c MMRM with data excluded after rescue/discontinuation. Original Figure 2A and archived visual transcription support ETD −1.0, 95% CI −1.1 to −0.8; visual verification remains a prerequisite, not an assumed scientific judgment.
- Main page 4 Figure 1: arm-specific disposition/counts/reasons require visual inspection, as text extraction does not capture all figure contents. Supplement pages 1–4 and captured registry participant-flow/primary-outcome entries must be reviewed for material complements or conflicts.

The approved target is assignment to weekly dulaglutide 1.5 mg versus placebo added to titrated glargine with metformin/acarbose, all randomized participants, change in HbA1c baseline to week 28. The selected reported ETD is −1.0 (95% CI −1.1 to −0.8), with efficacy data after rescue/discontinuation excluded. Neither randomized membership nor MMRM establishes observed endpoint availability. Conversely censoring does not alone prove that excluded observations were actually measured. These constitute **natural decisive and uncertainty controls within an actual case**, not an independent second case or a fictional qualifying amendment. No expected question response is forced.

Official guidance is preserved in the [common question object](common-target-and-question.json), from the repository's source-bound `SCIENTIFIC_PACK`. Exact source locator: *RoB 2 full guidance*, p.29, Box 6, questions 2.6 and 2.7; version/source hash are in the captured official objects. 2.6 considers ITT and mITT excluding missing outcomes appropriate, and naïve per-protocol/as-treated or inappropriate post-randomization exclusions inappropriate. 2.7 has no precise percentage threshold and asks potential substantial impact, including prognostic exclusions. Existing local guidance permits justified probable responses and distinguishes observed values excluded from analysis from unavailable outcomes. This package does not replace those criteria with a new rule.

## Private criteria and implementation decisions

The [private rubric](private-adjudication-rubric.json) is fixed before outputs. It is **not model input**. Each driving factual claim must be checked against its cited original source and context, including figures; role tags or coverage are not citation entailment. Reviewers distinguish direct fact, supported inference, unresolved premise and contradiction. They assess unsupported certainty, correct source interpretation, justified probable answers, and **material** omissions. Omission counts only when relevant to the exact claim, not every fact left unmentioned. NI is not universally preferred; decisive membership evidence must survive alongside legitimate uncertainty about observed values, exclusions and impact. Labels alone are insufficient.

Possible outcomes have explicit decisions:

| Outcome | Implementation decision |
|---|---|
| Current corrects baseline substitution with supported warrants and preserves natural controls | Retain the presentation; discuss one independent matched case before a generalization claim |
| Both scientifically adequate | Retain for usability if cost neutral, claim no scientific gain, stop this evaluation |
| Both fail the same mechanism | Stop adding target/result prose; examine evidence integration offline; no same-case paid repair loop |
| Current introduces unsupported certainty, material omission or unjustified blanket NI | Simplify/revert the tested presentation component after offline review; keep canonical target/result separation |
| Labels differ without a support improvement | No benefit claim; independent calibration needed, no automatic rerun |
| Missing evidence, unequal treatment, source defect or cost gate failure | Invalid/not launched; complete offline prerequisites or abandon |

These decisions do not entail source-judgment automation, automatic reassignment of target relation, new schema obligations or scientific production gates.

## Readiness and maximum useful cost

The [text manifest](text-packet-manifest.json) and [offline preflight receipt](text-coverage-preflight.json) cover **all 16 captured text pages across four sources**, including the full registry projection. Packet length is **267,137 UTF-8 bytes**. The byte-range check passes. It verifies only declared text delivery; it does not certify scientific completeness, visual content, a launch-ready input, or cost. No output or inference launcher exists in this package.

No-go blockers are concrete: Figure 1/2 and supplementary figures need independently checked visual content; a bounded source-complete subset must be adjudicated against the full captured registry and article; exact token count and final arm inputs/manifests/configuration must be frozen. The complete registry projection alone contains about 201k characters. Do not pay to ingest all of it merely to avoid offline source selection, or trim it by keeping only old citations. No missing registry fact is silently declared irrelevant.

Maximum useful diagnostic budget, **if prerequisites are later satisfied and authorization exists**: two calls only, ≤15,000 input tokens per arm, ≤1,500 output tokens per arm, 90 seconds per arm / 180 seconds total, zero tools, no resume or automatic repeat. If adequate evidence cannot fit, do not launch; reconsider scope offline. Token counts must use the applicable tokenizer rather than a byte estimate. The existing approved exact Luna model/effort must be verified from actual runtime metadata. Each launch must use `diagnostic_evidence_preflight.py:launch_checked` against the frozen assembled input and independently declared necessary uncited windows, preserving failed checks. The present text-packet preflight cannot be reused as that launch check.

Maximum dollar cost cannot be stated without provider pricing. Record per-response cached and uncached input/output; never treat cache hits as free or 30k total input as a dollar quote. Prior tool-free pair cost was 34,681 input (3,584 cached / 31,097 uncached), whereas native HOST-EXAM used 1,325,696 (1,222,400 cached / 103,296 uncached). The campaign durable subset is 27,046,202 input, of which 24,647,168 cached and 2,399,034 uncached. These are evidence for preferring an adjudicated compact pair over another native loop, not evidence of scientific benefit or complete billing.

## CI and stopping point

One latest-completed CI check: [a542232, run 37136316526](https://github.com/AliSalman-et-al/rob2-kit/actions/runs/37136316526). Same seven Windows failures per matrix: newline conversion of a hash-frozen fixture and select-on-pipe monitoring. Both were already fixed in `7c5e1cf`; its 60 focused local tests, Ruff and ty passed. [CI snapshot](ci-snapshot.json) records the failed-log hash. Newer runs were incomplete and were not waited on or polled. No distinct remaining regression was identified from this completed snapshot; no green current CI claim or redundant suite run.

Artifact-only verification checked the presentation delta and equal remaining card content, exact captured text window hashes/coverage, and primary/archive provenance. This pass changes no production behavior. Current offline work stops here with a **well-supported no-go**, frozen design and explicit prerequisites; no additional corpus audit, paid run, approval request or schema edit is needed to close this task.
