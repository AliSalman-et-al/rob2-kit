# STOP-IgAN: matched D3 guidance-only diagnostic

**Verdict: no demonstrated scientific gain; revise before adoption.** Retain the opt-in profile. The user's conditional direction to replace guidance across all five domains is not triggered by this result. No runtime or canonical-pack change was made from this single failure.

This authorized run used exactly two fresh `gpt-6-luna`, **medium** responses: one current D3 context and one `official_d3_prototype` context. Only the D3 guidance mode differed. The same instructions, approved Result, source inventory, 66 full-page windows, factual Figure 2 transcription and output requirements were frozen before launch. No saved judgments, previous answers, human/reference labels or desired label appeared in input. Empty isolated workspaces and identical instruction hashes were checked. The existing bounded harness was reused with a no-progress guard; there were no tools, retries or continuations.

## Source provenance and scope

Sources come from the user's required **Code benchmark**, October 1 cases and September 29 raw dossiers. All four STOP-IgAN PDF hashes and all five PIONEER-6 PDF hashes match their archived canonical inventory. Registry original bytes are unavailable for both; they were not fabricated or silently replaced. This is an explicitly fingerprinted original-PDF dossier comparison, **not an exact archived production replay**. No paid PIONEER-6 response was launched.

The exact selected Result is assignment to supportive care versus care plus immunosuppression, full clinical remission at the end of three years: protein/creatinine <0.2 and eGFR decrease <5. The primary reported OR is 4.82 (95% CI 1.43–16.30), full-analysis denominators 80/82 with missing classified as failure. It is not the second primary eGFR-decline endpoint.

Original PDF pixels checked the flow and both Figure 2 panels. All article and appendix pages were supplied, with relevant original/final protocol and SAP sections, including uncited missing-data and sensitivity sections. The combined protocol identifies final protocol 4.1 (13 April 2012) and original SAP 1.0 (11 July 2012). Planned best/worst scenarios do not establish their execution. The article reports actual MI/permutation analyses and similar available-case results, but supplies no detailed MI assumptions or numerical MI estimates in these article/appendix windows.

Official guidance provenance is [22 August 2019, complete Box 8 elaborations plus relevant shared sections](../2026-10-04-d3-authoritative-prototype/source-provenance.json). The undated [Cochrane FAQ](https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2), captured4 October 2026, addresses unknown extent at3.1 and missing-data-method lists at3.2. The prototype includes short exact excerpts and full-source locators, **not the entire FAQ answers**. Method names alone do not establish correction; plausible missing-outcome assumptions matter. Probable judgments remain permissible without exact counts, and prespecification is not a requirement for3.2.

## Findings

| Arm | Active answers | Server algorithm outcome | Evidence/path finding |
|---|---|---|---|
| Current |3.1NI,3.2N,3.3NI;3.4 missing | Incomplete: no label | Correctly retained available-case72/71 and uncertainty;3.1 may be overcautious, but no forced contrary verdict. Missed active3.4. |
| Prototype |3.1PN,3.2PY | Low, after production ignores extra3.3/3.4 | Incorrectly equated four non-completers per arm with endpoint missingness and95% observed. Insufficient support for robustness across plausible missingness assumptions. |

Neither output was repaired. `server-evaluation.json` records both strict direct-evaluator errors and the **actual production projection behavior**: inactive extras are ignored, while missing active answers remain an error. Prototype Low was computed with the unchanged server algorithm after that documented projection. No native assessment commit, citation validation or production completion is claimed.

The available-case endpoint denominators are72/80 and 71/82, while study completion is 76/80 and 78/82. The prototype saw both but used the latter as observed endpoint counts. Its uncertainty caveat does not support that exact assertion. Similar available-case OR 5.38, reported MI execution and significance are real reassurance. They do not, by themselves, justify robustness to the relevant missingness mechanisms; permutation testing serves another purpose. This is a reasoning defect, not proof that PY can never be defensible here. No exact-count gate, mandatory MNAR procedure or preferred reference label was imposed.

**This pair cannot compare completed domain labels, estimate benchmark accuracy, demonstrate better agreement than All-Low, or support all-domain adoption.** Shorter serialized context is not scientific evidence of gain. Actual input-token telemetry was higher for the prototype.

## Execution and validation

| Measure | Current | Prototype |
|---|---:|---:|
| Wall seconds |21.85|28.56|
| Input tokens |63,769|68,573|
| Output tokens |836|1,184|
| Cached input / tools / retries |0 /0 /0|0 /0 /0|

Both exit 0, one final/provider response each, exact model/effort verified from launcher and new rollout context. Output cap 3000, wall 300s, idle 120s, no-progress 120s; no overshoot. Guards are reactive and do not enforce a provider token cap. Input was telemetry only. The control/current and prototype outputs were frozen together before review.

Focused prototype/model-facing tests: **15 passed**. Original bundle/PDF hashes remained unchanged; all supplied source spans match between arms. The archived runner/recipe are documentation of this one run, not permission to rerun. Frozen full inputs, raw logs and renders remain preserved in the private artifact index. No extra paid call, full benchmark, merge or CI wait occurred.

Next: discuss source-complete PIONEER-6 corroboration and inspect independent official-guidance fidelity before deciding adoption. See the [conditional coherent-pack design](all-domain-replacement-design.md). Do not tune to a desired STOP-IgAN label or add another normative rule merely to make this example pass.

The preceding prototype CI run [37181804605](https://github.com/AliSalman-et-al/rob2-kit/actions/runs/37181804605) failed one stale skill-text test (1,390 passed,8 skipped in reported jobs). Two assertions in that same test required removed wording. They now verify existing official-context routing and source-entailment requirements instead. The affected test passed; ruff and diff checks passed. Runtime guidance and the matched-run scientific verdict are unchanged. New checkpoint CI is reported as a snapshot, not awaited.
