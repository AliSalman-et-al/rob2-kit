# September 27 trace and label audit

## Scope and campaign identity

I parsed every JSONL beneath `eval/runs/2026-09-27`: **102 segments, 79,086,897 bytes, no malformed lines, no byte-identical duplicate logs**. They belong to three distinct roots and must not be pooled as one scored run. `inventory.json` records every event/tool count by root; `trace-cells.csv` has every scored D1–D5 and derived overall row with the provisional reference label, model label, driver question, short trace rationale, and JSONL line reference.

- `issue-465-e2e`: 7 segments for 3 ENZAMET workflow checks; all 3 produced bundles. These are an E2E check, not the 26-case benchmark.
- `latest-rob2-kit-luna-medium`, campaign `4f5a555d…`: 33 segments for 26 cases (26 phase-1, 7 phase-2), 27/33 turns completed and no retained finalized bundles. It has no scoreable selected output. Nineteen cases have only phase-1 logs. Treat it as incomplete capture/workflow evidence, not a failed label sample.
- `rob2-trial-benchmark-fresh-4e03e798`, campaign `9da41712…`, model `gpt-6-luna` at medium effort: 62 segments for the scored fresh run, 62/62 turns completed, 26 finalized bundles, and no JSONL error events. A separate phase-3 launcher summary records 22 exit-code-2 metadata-binding failures, one exit-code-75 interruption, and three successes; the 26 retained finalized outputs still score. The 22 failures report that prior phase metadata did not bind the server-advertised inventory. They are orchestration/workflow failures, not scientific label errors.

The `trials.csv` catalog maps 28 Trial–outcome pairs. After normalizing `GETUG-AFU 15`/`GETUG-AFU-15`, the fresh manifest contains 26/28; it omits **ARASENS PFS and SWOG-1216 AE**. Thus the figures below are for the 26 labeled manifest cases, not full catalog coverage. The separate reference counts in `outcomes.csv` are not run-completion denominators.

## Label comparison

The current `scores.json` embeds the frozen provisional label vectors and explicitly calls its metric agreement with the catalog, not adjudicated scientific accuracy. Its scope denominator is 26 cases / 130 Domain cells: all 26 are scored after a scope decision of `equivalent`. The scope file records **15 exact relations and 11 narrower relations**, all adjudicated equivalent; 22/26 reuse the same generic rationale. Report the score as adjudication-inclusive. Proposal relation compares requested target to reported Result; it is not the benchmark expected-versus-observed mechanical comparison. All 26 scored rows required equivalence adjudication after mechanical mismatch. The 15/11 split must not be used as a mechanical-match denominator.

For the 26 included cases, exact Domain agreement is **83/130 (63.8%)**; Low-vs-non-Low agreement is **96/130 (73.8%)**. By Domain: D1 26/26, D2 14/26, D3 12/26, D4 19/26, D5 12/26. Outcome totals are OS 37/50, PFS 26/45, and AE 20/35 exact. Reference support is 104 Low and 26 Some Concerns (no reference High); observed model support is 80 Low, 32 Some Concerns, 18 High.

There are **47 Domain label disagreements across 24 cases**: D2 12, D3 14, D4 7, D5 14, and none in D1. Overall exact agreement is 2/26; Low-vs-non-Low is 20/26. All 24 overall mismatches are downstream of the five saved Domain labels and the deterministic aggregation rule, so they are not 24 additional independent reasoning errors. The model produced 20 High overall labels against zero reference High labels.

## Error and workflow taxonomy

The 47 Domain disagreements are **unadjudicated catalog differences**, not 47 established model errors. The trace table supplies per-cell evidence for source review, including the saved label and driver question. For example, ARASENS OS D3 is Low in the catalog and High in the model; the saved checkpoint names `sq:missing:likely-dependent` and the save response rationale explains its `no_information` assessment at `runs/overall-survival/ARASENS/phase-2.jsonl` line 120. This is a concrete review lead, not proof that either severity is scientifically correct. Matching catalog labels are also not independently checked for unsupported reasoning; the table marks them as unadjudicated agreements.

Observed non-scientific workflow friction is separate:

- The fresh run contains 2,584 `item.completed` MCP-call records (this count includes non-success outcomes), 639 context requests (465 with cursors), 186 single searches (54/184 observable zero-hit and 59/184 truncated), and 169 batch searches. These counts identify possible retrieval/context friction, not a demonstrated retrieval defect; the agent also used reads, evidence selection, and rendering.
- `save_domain_judgment` appears 194 times: 132 returned accepted saves and 38 were rejected at argument validation. The latter are input-contract failures, not scientific disagreement; at least one trace shows a malformed `counterevidence` value being corrected on retry (ARASENS OS phase-2 lines 76–84). Attribution between model formatting and tool-schema discoverability is unresolved. Final output still contains 130 scored Domain cells.
- The unscored `latest-rob2-kit-luna-medium` root lacks finalized artifacts; its cause cannot be established from the captured records. The later phase-3 metadata-binding failures and one interruption are explicit workflow failures, while the fresh selected outputs completed.

No paid reruns were made. No revised scientific accuracy estimate or model-capacity claim follows from these traces. The 47 disagreements remain uncertain until source-grounded adjudication classifies each as a model reasoning error, a defensible deviation, a label/scope issue, or indeterminate.

## Reproduction/evidence files

- `inventory.json`: complete JSONL inventory, score counters, response outcomes, scope adjudications, and catalog coverage.
- `trace-cells.csv`: 156 scored rows (130 Domain plus 26 derived overall), with raw trace line references and concise evidence excerpts.
- Primary scored inputs: `eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798/scores.json` and `scope-adjudications.json`.
