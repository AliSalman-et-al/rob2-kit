# Three qualification repairs: two blinded supplied-evidence responses

One response per frozen condition completed normally with durable **gpt-6.1-sol / low** profiles in two separate initial sessions. Both outputs were sealed before scientific inspection and separate condition-blinded AI scoring. There were no outcome retries or other paid cases; the full benchmark remains off. [Readiness design](../2026-10-05-official-qualification-mechanism-readiness/README.md) and private hashes bind the pre-response cases, order and rubric.

**One observed answer changed in the intended direction; seven tied.** For general minimisation with unavailable settings and no contrary evidence, old guidance elicitedNI and a rationale requiring confirmation of a random element. Current guidance elicitedProbablyYes and explicitly used the official general minimisation inference while retaining uncertainty about actual settings. This is an observed mechanism-consistent behavior correction in this sample, not a causal effect estimate. Source-fidelity repair is independently established; broad behavioral benefit is not.

| Question/contrast | Old answer | Current answer | Blinded rationale grade old/current |
|---|---|---|---|
| D1.1 credible circumstantial sequence inference |ProbablyYes|ProbablyYes|strong / strong|
| D1.1 genuinely uninformative reporting |NI|NI|strong / strong|
| D1.1 general minimisation |NI|ProbablyYes|partial / strong|
| D1.1 explicit predictable minimisation |No|No|strong / strong|
| D3.2 plausible-range sensitivity, actual mechanism unknown |Yes|Yes|strong / strong|
| D3.2 LOCF/treatment-only imputation labels |No|No|strong / strong|
| D4.4 direct all-cause death/date, assessor aware |No|No|strong / strong|
| D4.4 participant pain rating, assessor aware |Yes|Yes|strong / strong|

Answer admissibility and rationale warrant were scored separately against frozen investigator ranges. Seven old-condition answers and eight current-condition answers were in those ranges; those counts are **not accuracy estimates**. The general complete response framework was intentionally shared and can rescue overstrict rules: circumstantial randomization, unknown-mechanism sensitivity and mortality already yielded supported answers in the old condition. No observed incremental benefit on those three contrasts. Contrary evidence, uninformative reporting and unsupported imputation retained appropriate negative/NI responses.

The separate reviewer used **gpt-6.1-sol / low**, with no history fork and no condition mapping, original assessor prompts or private reasoning traces. It reviewed only final submitted answers, neutral facts, official context and frozen criteria. Condition inference from response wording remains possible; same-model errors may correlate. This is AI source-aware scoring of constructed facts, not independent expert validation. [Full blinded review](blinded-source-aware-review.json) and [separate score projection](review-score-projection.json) retain all16scores. Reviewer token usage is unavailable through the collaboration interface.

Two source-warrant qualifications remain in both conditions. The supplied sensitivity range has elicitation support, but whether a0.26point shift counts as little change remains judgmental; confidence intervals on one side of zero alone do not establish protection against material bias. Mortality’s absence-of-pathway wording is bounded to supplied procedures and should not mean logical impossibility. No answers were repaired after scoring.

Actual assessor usage: **37,376input tokens**, including **13,824cached** and **23,552uncached**; **1,962output tokens**, including **134reasoning tokens**. The two calls took **52.64seconds** together. Frozen prompt byte/4 proxies were11,785and12,374tokens; actual CLI inputs also include shared generic system/developer/environment context and use actual tokenization. Dollar cost is unverified, and assessor totals exclude reviewer usage.

One offline prelaunch check stopped because a generic CLI instruction mentionedAGENTS.md; it produced no inference. The check was narrowed to actual workspace content and the failure preserved. Both inference sessions emitted the same unstable-feature warning and exited normally. A preliminary in-process seal included a changing supervisor log; the final settled post-exit seal was made **before** answers were read and remains valid. [Operational integrity](operational-integrity.json) binds outputs, profiles, warnings, failure, manifests and usage. Raw traces and private reasoning remain private and unchanged.

This small check uses eight synthetic supplied-evidence records instantiated from existing official-source-derived contrasts. It tests the supplied context interpretation, not source search, native full-trial workflow, benchmark agreement or clinical validity. Eight cases in a batch are dependent; one draw per condition cannot separate stochastic variation from context effects or support statistical generalization. Preserve the one difference and all ties without a preferred-label retry.
