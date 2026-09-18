# Issues #387–#404 audit

Date: 18 September 2026

This audit checks the implementation against the acceptance criteria in GitHub
issues #387–#404. “Pass” means the behavior is present and has focused
repository evidence. “Partial” means the production path exists but an
acceptance boundary or qualification is still missing. “Hold” means the
integrated claim is not supported.

| Issue | Status | Evidence and remaining risk |
| --- | --- | --- |
| #387 | Partial | Limitation bases require an unresolved premise and stopping rationale; direct reads do not need a receipt. Absence remains a separate, scoped no-hit claim. The requested complete zero-hit/decisive-tail/unresolved-premise validation-to-export matrix is not yet demonstrated. |
| #388 | Partial | Purpose is optional. Purpose-less assessment searches are now Trial-level discoveries with bounded `get_domain_context` recovery and cursor continuation, and replayed proposal sessions advance to assessment provenance. Full single/batch/restart/attachment coverage is still incomplete. |
| #389 | Partial | Native localization now unions raw and normalized FTS spans. The focused regression is fixed, but the full acceptance matrix for repeated units, overlapping highlights, marker collisions, and membership failures is not yet represented by tests. |
| #390 | Partial | Literal normalized matching, endpoint boundaries, independent scope scanning, and deterministic coordinates exist. The edge-case matrix for Unicode case folding and numeric/underscore boundaries is incomplete. |
| #391 | Partial | A versioned Porter profile is used across the active search paths. Atomic rebuild, scoped-statistics, old-cursor, and historical-semantics qualification are not complete enough to claim the whole issue. |
| #392 | Partial | RapidFuzz OSA, source-scoped catalogue entries, exact examples, full tie-breaking, bounded suggestions, one-unit replacement, and dehyphenated-source crash protection are implemented and focused-tested. The full protected-unit, response-budget, correction-to-Evidence, and misleading-alternative matrix is still incomplete. |
| #393 | Partial | Source navigation exposes headings, contents, dates, versions, and cross-references. Combined-document chronology and conservative deduplication still lack an end-to-end qualification case. |
| #394 | Partial | Valid source-bound working notes bypass the duplicate post-approval read gate and recovery uses canonical state first. The lost-acknowledgment crash window still lacks a behavioral test. |
| #395 | Partial | Host-observed visual provenance is represented and export-checked. No real installed-host image-delivery qualification was observed in this audit. |
| #396 | Hold | Question cards are complete, but surrounding licensed official sections have no bounded, model-callable recovery route beyond the current per-question excerpts. |
| #397 | Partial | D3 distinctions and missingness safeguards are encoded in the pack. The required balanced host reasoning qualification is not present. |
| #398 | Partial | D5 chronology and eligible-alternative wording was corrected. A controlled chronology case has not established the resulting host behavior. |
| #399 | Partial | Allocation consistency and assignment-effect guidance is present. A controlled AE analysis-grouping qualification is missing. |
| #400 | Partial | D4 awareness, susceptibility, detection, and influence distinctions are present. Installed-host qualification is missing. |
| #401 | Partial | Trial review records new evidence, self-correction, and mechanical repair attribution. The evaluation projection does not retain complete before/after answers, justifications, uncertainty, locators, and reasons. |
| #402 | Partial | The confirmed cache-connection lifetime bug is fixed; ranking reuse is bounded with LRU eviction and counters. The requested warm-work matrix and retained performance artifact are missing. |
| #403 | Partial | Comparison configuration validation and independent-session observation import exist. There is no executable end-to-end comparison runner that retains all arm outcomes. |
| #404 | Hold | The integrated qualification report is conservative and records a hold. The requested frozen installed-host matrix, including successful and repairable error delivery, has not been demonstrated. |

## Focused verification

The full suite was intentionally not run. Targeted xdist checks covered the
agentic-search, context, contract, recovery, cache, bundle, evaluator, and
qualification paths. The broad targeted run passed 422 tests before the final
compatibility and regression tests; the final regression groups also passed.

All 28 retained benchmark bundles passed the independent bundle verifier after
adding explicit compatibility for their recorded v0.8 prior-guidance pack hash
(`sha256:5c49411a…`). They are historical evidence for that recorded pack, not
qualification of the current pack hash or an installed host. The benchmark used
Luna Medium with JSONL logging and fresh workspaces. Trials without the requested
abstract outcome were skipped.

| Outcome | Trials | Domain exact | Domain Low vs non-Low | Overall exact | Overall binary |
| --- | ---: | ---: | ---: | ---: | ---: |
| Progression Free Survival | 10 | 72.0% | 78.0% | 0.0% | 70.0% |
| Overall Survival | 10 | 80.0% | 84.0% | 20.0% | 50.0% |
| Adverse Events | 8 | 55.0% | 62.5% | 12.5% | 87.5% |
| Combined | 28 | 70.0% | 75.7% | 10.7% | 67.9% |

“Binary” treats Some concerns and High as the same non-Low class. The exact
benchmark report contains trial-level labels, traces, and attribution:
[benchmark-20260918-report.md](../../eval/runs/benchmark-20260918-report.md).

The largest observed scientific shortfalls were conservative D3 judgments,
selection-chronology mistakes in D5, adverse-event D2/D4 distinctions, and
inflated overall High labels. These results support the mechanical repairs above
but do not support promoting #404.
