# Active-question architecture investigation

**Decision: reject runtime adoption on this evidence.** Keep the isolated offline projection for inspection. No MCP tool, parameter, schema, default or canonical state changed. The corrected synthetic protocol remains unrun. Smaller context is a transport finding, not evidence of better science.

## Actual delivery

We measured two completed native runs: AWARD-10 D3 at fbe8a88 and HOST-EXAM D5 at 6d0ac5e. Their question wording and official/operational D3/D5 text match current HEAD exactly; historical pack identities and captured source/result data remain intact. These are actual recorded deliveries, not newly generated current-HEAD model responses.

Each first complete frozen context was reconstructed from its four pages, deduplicating events by tool-call ID. Compact UTF-8 JSON sizes are not token counts or measures of attention or hidden reasoning.

| Component, bytes | AWARD-10 D3 | HOST-EXAM D5 |
| --- | ---: | ---: |
| Result: target and reported | 2,212 | 3,016 |
| Question cards | 17,074 | 14,518 |
| Separate official-guidance copy | 3,025 | 2,355 |
| Generic guidance/framework/traps | 4,620 | 4,620 |
| Evidence catalog | 10,421 | 15,644 |
| Comparison cards | 8,449 | 10,531 |
| Complete merged context | 51,066 | 56,912 |
| Actual structured transport across four calls | 55,449 | 61,269 |
| Accepted save arguments | 2,178 | 4,450 |
| Justification/unknown/counterevidence strings | 1,795 | 2,214 |

AWARD had one initially active question, 3.1, plus three questions conditional on draft answers. They were not known inactive branches. At its requested 20 KB limit, page zero contained no question; page one contained all four cards. Only 3.1 was ultimately submitted. HOST-EXAM had three always-active questions, 5.1–5.3; page zero at 32 KB included 5.1. All three remain necessary for its complete D5 assessment. Each context was fetched once through four pagination calls, not repeatedly per question.

Exact repetition is modest. Official excerpt text appears twice: 1,820/1,379 bytes. Comparison cards repeat the reported result: 493/466 bytes. Duplicate leaf strings of at least 80 characters total 2,191/2,562 bytes; this lexical measure does not establish that semantically related guidance is redundant. Official elaboration and operational interpretation cannot safely be collapsed merely because their topics overlap.

The current submission type already derives canonical identities, bindings, traces and labels. Much of the accepted submission is scientific explanation. These traces do not demonstrate that canonical construction consumes scientific attention.

## Existing tools and parameters

`get_domain_context` supports Domain lookahead, candidate inclusion, flow preview, cursor and byte budget. It has no question selector. Candidate inclusion defaults to false and controls optional discovery material, not scientific activation. AWARD explicitly enabled it; the prototype preserves every delivered candidate to avoid hiding counterevidence.

The evidence workspace already associates groups with question IDs and supplies exact source/search/read recovery. Search has an optional question purpose, without restricting later scientific use. `review_trial(domain_id, question_id)` focuses saved-answer detail; final Trial review still supports reasoning across Domains. Targeted source work therefore does not require a new tool or one call per question.

Page budget affects turns independently of scientific focus. The offline current paginator fits both complete contexts into one 64 KB response, versus four at 32 KB. This is not a recommendation to change defaults: native client limits were not validated, and the current tool description discourages manual budget changes except oversized-page recovery. At 32 KB, the active projection needs three AWARD calls versus four, and four HOST calls versus four. At AWARD's actual 20 KB limit it still needs four calls.

## Offline projection and hypothetical interaction

`prototype.py` returns the complete context by default. Its explicit offline flag retains the recorded active set, without selecting answers. It preserves:

- Every selected question card, complete activation map, question wording/options and official-source provenance.
- All evidence, comparison cards, propositions, counterevidence, source recovery and coverage.
- The approved target and reported result, saved answers and probability framework.
- Exact omitted guidance through a SHA-256-bound full snapshot.

No evidence is filtered by inferred relevance. The projection is not a valid current MCP focused response or executable cursor. Live exposure was deliberately not implemented.

With those safeguards, AWARD projects to 40,103 bytes: 10,963 fewer, or 21.47%. HOST projects to 56,876 bytes: only 36 fewer, or 0.06%. D5 has no conditional guidance to defer, and provenance/dependency/recovery metadata consumes most deduplication savings. Dropping its other always-active questions would be a different intervention requiring their guidance before a complete answer.

**Before:** call `get_domain_context`, follow three cursors, inspect sources, then submit one complete active path with `save_domain_judgment`. Final `review_trial` is unchanged.

**Hypothetical after, unavailable today:** call the same tool with an optional `view="active_questions"`, defaulting to `"domain"`; follow projected cursors and inspect unchanged sources. Save once if the path is complete. If draft answers activate additional questions, or other guidance is scientifically relevant, request the complete Domain view once and follow its cursors before saving. This introduces no compulsory call per question. At 32 KB, AWARD would need three initial calls; full recovery adds four, making seven versus four before unchanged source calls/save. HOST still needs four initial calls.

The simulator uses deterministic dcp1 cursors; original native runs used shorter dcp2 handles. These are offline paginator results, not measured native-turn savings.

Minimum runtime work would be one optional view parameter on the existing tool, a typed question-index/recovery projection, and focus-bound frozen cursor identities with a complete counterpart. It would need delivery, completion, staleness and exact-guidance recovery tests. Defaults, server activation and atomic saving must remain unchanged. Filtering the questions array alone would falsely mark incomplete scientific context complete. No new tool, per-question commit, premise gate or answer classifier is needed, but the change has real maintenance and recovery costs.

## Scientific decision and falsifiable test

HOST-EXAM's known omission was a planned multiple-imputation sensitivity analysis after its full paragraph was delivered. All three D5 questions were active; the measured projection barely changes that context. AWARD's current trace already avoided analysis-denominator substitution; its remaining importance inference needs methodological review, not an assumed overload fix. Neither trace establishes that conditional guidance or bookkeeping caused its reasoning weakness. Deferring later guidance could also remove useful information for an early question's importance judgment.

**Reject the runtime redesign now.** The modest D3 savings and negligible D5 savings do not justify new recovery semantics or another paid presentation experiment by habit. The offline prototype is retained as concrete evidence, not adopted for production testing.

If independent evidence revives the hypothesis, `hypothetical-scientific-test.json` specifies an actual Code AWARD-10 comparison: the exact 24-week HbA1c LSM difference −0.79% (CI −0.97 to −0.61), preserved target/reported population distinction and complete original published sources. Compare complete Domain versus active-set delivery with full recovery. Judge observed-versus-analyzed distinctions, a source-backed importance warrant and complete conditional activation—not PY/Low or bytes. Falsify the proposal if relevant guidance or uncertainty is lost, branches are skipped, compulsory turns increase, or warrants fail to improve. Reference alignment remains unknown; this would be a repeated development mechanism test, not accuracy/generalization evidence. No test was authorized or run here.

Three offline preservation tests passed, plus lint, formatting and typing for the prototype/tests. They verify default identity, immutability, exact source/result/counterevidence preservation, dependency/provenance recovery and retention of all three D5 questions. Original traces, sources and saved artifacts are unchanged. No model calls, production edits, benchmark, merge or CI wait.
