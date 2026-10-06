# Bounded offline audit of the current domain interface

Recommendation: **no production contract or context change in this pass**. The current interface already removes canonical record construction from the model. The sampled traces demonstrate one small construction omission, but do not support another schema redesign or a claim that premise bookkeeping dominates scientific comparison. No paid calls, benchmark, provider change, CI wait or merge occurred.

## Current contract, rather than obsolete schemas

`DomainSaveAnswer` in `src/rob2_kit/workflow_models.py` is the current public submission type. An answer supplies question ID, permitted response, evidence handles with scientific roles, a justification, explicit unknowns and counterevidence. Optional absence searches and limitations are separate. The model does **not** construct canonical identities, basis kinds for absence/limitation, counterevidence indexes, evidence-sufficiency claim records, result binding, inactive-question lists, algorithm traces, drivers or domain/overall labels. `canonical_payload()` adds canonical tags and indexes; application code binds the result, evaluates the path and produces server labels. The current role distinction is a model assertion of scientific use, not server entailment.

A limitation records an unresolved premise and a stopping rationale; it is not proof of scientific absence. A no-hit receipt records a bounded query; it is not proof that the trial omitted a fact. Explicit unknowns preserve the unresolved scientific proposition even when no limitation/search provenance is applicable. Counterevidence preserves a source-backed alternative that limits the chosen answer, and may cite handles outside the primary bases without requiring model-generated indexes. These distinctions should remain.

Working premise records are optional resumable source-grounded notes, current only for the approved result/source projection; they are not an additional mandatory submission. The context's question cards preserve exact questions/options/activation. Comparison cards colocate target, reported result, relation, source passages and question-specific seams. The evidence workspace groups source-bound material and exposes exact recovery for omitted text. Official guidance, unknowns and alternative interpretations cannot safely be replaced by a generic summary. Server-derived claim statuses remain marked host-asserted rather than independently established.

## Actual trace evidence

[Metrics](trace-metrics.json) deduplicate event updates by tool-call ID; started and completed events are not two calls. These five native runs use payloads accepted by the current schema, rather than earlier proposal/domain schemas. [Offline checks](offline-checks.json) revalidate five accepted submissions and reproduce the one rejected submission against today's type.

| Trace | Native calls | Save attempts | Accepted argument bytes | Working-checkpoint calls | Observed issue |
|---|---:|---:|---:|---:|---|
| HOST-EXAM D5 | 21 | 1 | 4,450 | 0 | Omitted planned imputation in warrant, not construction rejection |
| RECOVERY D5 | 20 | 1 | 5,381 | 0 | Unsupported PY correspondence warrant, not construction rejection |
| Bendix D2 | 15 | 2 | 5,890 | 0 | First submission omitted required counterevidence on one answer; repaired |
| Guitton D2 | 16 | 1 | 3,389 | 0 | Dropped relevant exclusions / weakened scientific comparison |
| AWARD-10 D3 | 13 | 1 | 2,178 | 0 | Improved denominator distinction, incomplete importance warrant |

Four of five cases saved first attempt; one of six save attempts failed construction. This is a descriptive same-case sample, not a rate estimate or causal interface evaluation. The current schema already accepts HOST-EXAM/RECOVERY payloads without optional empty arrays. In HOST-EXAM, approximately 3,226 characters of its submission are justification, unknowns and limitation prose: cutting those fields would primarily cut scientific explanation, not internal record construction. Repetition between unknowns, justification and limitations is visible, but their meanings differ; neither the exact missing proposition nor reason for stopping is deterministically recoverable from a question or evidence handle.

Serialized result sizes are roughly 56–68 KB for `get_domain_context` across these runs and 38–128 KB across `read_pages` results, versus 2–6 KB per accepted submission. These are JSON byte proxies including result envelope representations, **not tokenizer measurements, delivered unique-source bytes or evidence of attention/time allocation**. They suggest examining context reuse before expanding schema work. Traces cannot quantify private thought devoted to bookkeeping versus science. No inference about hidden reasoning effort is made from byte counts.

## Redundancy and minimum payload

Already removed by server derivation: canonical tags/identities, result binding, index cross-references, claim summaries and labels. Already optional: empty `absence_searches`, `limitations`, and absent participant-flow rows. Keep explicit empty `unknowns` and `counterevidence`: they distinguish an asserted absence of material issues from a field accidentally omitted, as demonstrated by Bendix's repair. The model's support/context/inference/contradiction role, response and warrant cannot be derived from selected evidence without semantic judgment. A generic default role would silently resolve that judgment. Selected target identity cannot supply observed-outcome counts or planned-versus-executed conduct.

[Before/after minimum payloads](minimum-payloads.json) contain two neutral fictional examples. “Before” explicitly emits optional empty arrays; “after” omits them under the **same existing interface**, with typed canonical equivalence verified offline. This is an illustration, not an implemented redesign or claimed behavioral gain.

The decisive example preserves a computer-generated sequence citation, Yes and a warrant limited to sequence generation; it does not infer concealment. The uncertain example preserves an early dated Cox plan, a reported Fine–Gray model, NI, a possible qualifying amendment, counterevidence against universal post-outcome planning, and bounded stopping rationale. Exact question IDs/options, sources, uncertainty and alternatives survive. Placeholder handles demonstrate syntax only and are not live evidence.

A conceptual replacement of unknowns plus limitations with one combined field could remove repeated wording, but would require a new public grammar, migration and uncertain reconstruction of distinct scientific versus retrieval facts. No current trace demonstrates sufficient benefit. Do not implement it. Likewise, automatically copying limitation premises into unknowns or inferring source absence from coverage would manufacture semantics.

## Cost-aware next scientific evaluation

First perform a bounded offline comparison using existing exact frozen inputs: test whether a compact presentation of already captured planned/executed/reported facts and known contradictions would preserve all material premises. Independently adjudicate warrant entailment and target correspondence before selecting a test case. Source-window requirements must include necessary uncited evidence, not just existing citations. Agree on what would justify a response and what uncertainty must remain; label agreement alone is insufficient.

If that comparison establishes a useful presentation candidate, discuss **one** tool-free matched diagnostic pair, with identical source facts and only presentation changed, before any native continuation. Freeze task, criteria, model input and coverage manifest; launch only through the existing checked preflight. Keep implementation model and existing approved Luna launcher distinct; verify its exact model ID. Prefer a bounded input near 15k rather than recreating 20+ native calls, freeze outputs before review, record response-level cached/uncached usage, and stop on the agreed output/time limit. A synthetic qualifying-change control can test calibration separately but must not count as corpus accuracy. No such call is authorized or launched by this report.

The campaign checkpoint's [durable ledger subset](../2026-10-03-campaign-checkpoint/durable-usage-subset.json) distinguishes 27,046,202 total input from **24,647,168 cached** and **2,399,034 uncached**; output is 108,569, including 23,199 reasoning. Native HOST-EXAM alone used 1,325,696 input (1,222,400 cached / 103,296 uncached), while the prior tool-free D5 pair used 34,681 input (3,584 cached / 31,097 uncached). The tool-free pair is much smaller in total input but not proportionally smaller in uncached input; runtime, output and provider pricing matter. Tokens are not cash cost. Pricing and complete project billing are unavailable, and these costs do not establish scientific gains.

This pass added only audit artifacts. Two example pairs were typed and canonical-equivalent; five accepted native payloads validated; the recorded Bendix omission remained rejected. No production code or tests were changed, so no repeated broad suite was needed. The best-supported next direction remains improving material evidence integration while reusing existing context, rather than adding a reasoning bureaucracy.
