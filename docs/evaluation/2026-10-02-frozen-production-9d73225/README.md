# Frozen current-version production repair checks

Both isolated production diagnostics used clean scientific/runtime SHA **9d73225752353916e641910a1f68bb7925a5bddb**, exact model **gpt-6-luna**, medium reasoning, CLI 0.159.0. One invocation per case; no further run or operator payload repair. No production feature changed during or after these checks. These are known-case repair checks, not holdout/generalization evidence or a full end-to-end benchmark.

## Setup and authority

New workspace copies come from the actual Code benchmark's October 1 canonical/derivative databases, with original approved Result and earlier Domain checkpoints retained (An D1; MONARCH-plus D1/D2). Tested/later active Domain records, retrieval handles, reads, context deliveries and working notes were cleared in the new copies; original cases and historical canonical rows were preserved. Raw local Sources were restored only after captured-byte hash verification. Model tools expose current production context, source reading/search/visual selection and Domain saving; no history/status tool, shell, network or reference label access was available.

An has one restored PDF. MONARCH-plus has restored article/supplement PDFs and one historical registry projection whose raw bytes remain unavailable. That known Source limitation was stated in the operator prompt; no replacement was fabricated. Original outcome/group/time/analysis scope was retained, not re-adjudicated. Context preflight only checked the current server; the model retrieved its own context and evidence. Prompt changes from the prior scoped attempts concerned current bounds and response delivery, not scientific answer hints. One model-owned correction was permitted within each invocation, stopping after two rejected submissions; “no retry” means no second invocation or continuation.

## Actual model-owned outcomes

| Case | Submission outcome | Server judgment | Tools / saves / rejections | Time | Limitation |
| --- | --- | --- | --- | ---: | --- |
| An 2021 D2 | No saved checkpoint | None | 14 / 2 / 2 | 144.22 s | First wire draft invented role `counterevidence` and field `explanation`; its correction omitted D2.3's required counterevidence array. |
| MONARCH-plus D3 | Saved at revision 14, checkpoint `1f18744f…` | High, driven by D3.4 NI | 9 / 1 / 0 | 71.16 s | Retrieval impairment and scientific uncertainty remain; completion is not accuracy. |

All rejections and exact unmodified arguments are in each `submissions.json`. MONARCH's accepted `final-domain-record.json` is server state, not operator reconstruction. An's file is null. `answer-only-mapping.json` maps the last An answer enums to Some concerns without repairing any payload; it is **not** an accepted judgment and is not scored as successful completion. The invalid An run has no final model response. A process exit code of zero after the stop does not imply completed scientific work.

An was not blocked by shared infrastructure: context, reading, searching, rendering and evidence selection worked. Its failures were model-owned contract omissions, so the second authorized case proceeded. MONARCH's scoped search failed with source/search projection integrity error; its report correctly records failure, not a no-hit. The model used restored local article/supplement sources and did not replace the registry.

## Scientific warrants and contradictions

**An awareness:** PY/PY distinguishes practical participant/provider awareness from the article's explicit blinding statement. The correction retained that statement as cited counterevidence and articulated distinguishable intervention delivery. This is more defensible than treating either the blinding label or intervention visibility as certainty; actual masking remains unresolved.

**An trial-context cause:** D2.3 NI avoids promoting intervention-related departures to proved trial-context causation. However, the draft says the report does not explain adherence/causes and its stopping rationale cites only a lexical phrase search and inspected regimen/flow. The actual PDF p.11 explicitly attributes two withdrawals to intensive training. The model read p.3–7 and p.8, not p.11; the selected evidence does not retain that paragraph. Thus the claim is overbroad if read as report-wide absence, and the investigation missed known available discriminating evidence. The paragraph supports ordinary regimen burden, without itself proving every departure was unrelated to trial participation. No source-grounded replacement answer is imposed.

**An analysis:** D2.6 PY preserves randomized group identity and distinguishes missing-outcome-only mITT exclusions from observed-but-omitted outcomes. It uses 53 analyzed versus 60 randomized and the flow categories as compatible with missing outcomes, while explicitly admitting that endpoint availability for all seven exclusions is unresolved. Compatibility alone is weaker than establishing the exclusion mechanism; the probable confidence still needs independent warrant review. This is not accepted or adjudicated science, and no favorable label is counted.

**MONARCH availability:** D3.1 NI correctly avoids equating 119 PFS events or ITT n=207/99 with ascertainment completeness. It distinguishes treatment discontinuation from outcome follow-up. Supplement PDF p.8 visibly supports the model's transcription: two placebo participants lost to follow-up, alongside separate progression, adverse-event and withdrawal categories. The categorical cause/count transcription was checked visually after the run.

**MONARCH missingness:** D3.2 No explicitly denies demonstrated protection, without asserting bias occurred, and retains the possibility of uninspected sensitivity analysis. Its actual accepted save demonstrates the scoped negative-evidence gate works in a model-owned production call. D3.3/3.4 NI retain unresolved reasons and timing for lost PFS follow-up; the correct deterministic path then yields High. That is **uncertainty-driven High**, not evidence that missingness likely depended on true PFS. The model did not quantitatively relate the known two losses (2/99, about 2.0% in placebo) to information loss, censoring, effect size or other possible loss. Two is not proved to be the total PFS missingness count: treatment withdrawals may or may not terminate ascertainment. Administrative censoring at an interim cutoff is not inherently missing outcome data. This is the main unresolved scientific warrant, requiring appraisal before defending the disagreement or selecting a Low replacement.

The main article/supplement were available, but neither run was a full dossier replay. `postrun-source-checks.json` marks operator-only review separately from model-delivered evidence. Source coordinates in `selected-evidence.json` prove provenance and retention, not scientific entailment.

## Original human labels and comparison scope

`human-reference-scope.json` pins the Code CSV hashes/rows. Both human references are Low, but their `label_outcome` is `(meta outcomes)`, extracted from color-grid figures (An eFigure 1; MONARCH supplementary Figure S14). The outcome metadata anchors align broadly with quadriceps strength interaction and cohort A PFS, respectively; exact effect-of-interest, comparison, time window, analysis population and analysis matching have **not** been independently confirmed for the human judgments. References were inspected by the operator after both runs and withheld from models. No exact accuracy, All-Low improvement or defensible disagreement rate is inferred.

## Durable usage and monitored bounds

| Case | Input | Cached input | Uncached input | Output | Recorded total tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| An | 429,018 | 380,160 | 48,858 | 4,827 | 433,845 |
| MONARCH-plus | 352,130 | 259,072 | 93,058 | 2,456 | 354,586 |
| Combined | 781,148 | 639,232 | 141,916 | 7,283 | 788,431 |

An recorded 15 generation-usage records; MONARCH 11. Reasoning output, included in output totals, is 1,708 and 501 respectively. These are durable recorded usage counts, not an invoice or dollar-price estimate.

Each run had 480-second wall / 120-second idle guards, 16 tools / 2 rejected submissions, 400k total input / 100k uncached / 5k output limits. The launcher reads durable `token_usage_record` totals while running and stops on observed bounds. An's stop sample recorded both two rejected submissions and input above threshold: an in-flight generation added **29,018 input tokens above 400k**. No uncached/output overshoot was recorded. The operator did not permit a third correction. Monitoring is reactive at event/generation flush boundaries, not a preauthorization billing cap; the stop reason records the rejection condition observed in that polling cycle, not finer causal ordering between contemporaneous limits. MONARCH finished below every limit. All owned CLI/MCP processes were gone afterward.

Raw events are preserved locally with hashes in `event-provenance.json`; sanitized Git traces omit only image base64, preserving image hashes, receipts, transcriptions, every tool argument/result and rejection. Credentials, full homes, databases and stderr remain outside Git. The source/runtime SHA stayed fixed throughout; these evidence files are a subsequent documentation checkpoint.

## Next step

Production repair is only partial: one of two known-case model-owned submissions completed. Do not launch another automatic known-case retry or a full campaign. First review the existing An source coverage/contract omissions and MONARCH's quantitative survival-outcome availability warrant offline. No new alias, schema field or rule is justified by completion alone.

Once that appraisal defines a scientifically defensible stopping criterion and the production boundary is reliable, the next genuinely unseen check should use one or two cases excluded from all prior diagnostics: independently match human judgment to the exact target, verify every raw Source, and prewrite source-supported warrant/counterwarrant without giving answer hints to the model. Freeze one implementation SHA/model/settings, retain failed drafts, use server labels, and separately assess coverage, entailment and structural completion. A successful MONARCH save licenses no claim of generalization. Full benchmark discussion, corpus alignment and independent adjudication remain prerequisites.
