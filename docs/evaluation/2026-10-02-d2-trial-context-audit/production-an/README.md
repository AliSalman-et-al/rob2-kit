# One bounded production D2 diagnostic

Model: exact launcher ID `gpt-6-luna`, medium reasoning, Codex CLI 0.159.0.
Code frozen at cb7cae02d1b1b95e06ab1852a18a93c03a488599 (the causal-context
correction, before the subsequent D2.6 clarification). Neutral prompt and source
hashes were pinned before inference. Same approved three-group quadriceps-strength
Result as the retained Code benchmark; seeded proposal/D1, no prior D2/reference
answer supplied, derivative retrieval evidence cleared. Sole captured local PDF
restored with matching hash. This is not a cold full assessment or matched
reference-label accuracy test. Shell/web/apps/other-model access were disabled.

Guards: 240s wall, 90s idle, 12 tools, one save, no retry; monitored thresholds
200,000 cumulative input, 75,000 uncached input and 6,000 output. Thresholds can
overshoot by an in-flight generation. The run stopped after the first rejected
submission in 70.51s, seven tools, one save. No correction or second inference
was launched. No owned diagnostic MCP/CLI process remained afterward.

## Outcome and science

The production call was **not accepted**. Two counterpoints used plural
`basis_indexes:[0]` instead of the required singular `basis_index:0`. It ended
without a final response or D2 checkpoint. Schema aliases were not added.

D2.3 changed from retained Probably yes to Probably no with a source-grounded
rationale distinguishing ordinary intervention burden/clinical events from
trial-specific recruitment, engagement or personnel decisions. It retained
unknown protocol adherence and causation. That directly addresses the diagnosed
faulty inference. One post-change sample on a newer seeded workflow cannot
isolate a causal improvement or establish accuracy/generalization.

Other answers changed too. D2.6 became Probably no based on 60 randomized versus
53 analyzed and absence of proof that exclusions were missing outcomes. D2.7
became Probably yes, so the draft still yields High. Attrition counts alone do
not establish an assignment-analysis failure: the missing-outcome-only mITT
exception, observed-but-excluded outcomes and grouping must be distinguished.
Participant-awareness No also relies on literal reported blinding despite visibly
different interventions; this warrants careful scientific review and is not
validated by this diagnostic.

An independent offline copy changed only the two counterpoint field names,
retaining all answers, rationale, unknowns, source handles and roles. The server
accepted that clerically corrected draft and computed **High**, driven by the
assignment-analysis branch. This is an offline control, not a successful model
submission, retry or clinical/reference validation.

Review exposed an internal D2.6 guidance conflict: one rule accepted mITT with
missing outcomes, but a later rule characterized all eligible post-randomization
exclusions as analysis concerns. Cochrane printed p.29 explicitly permits mITT
excluding missing outcomes. The refinement now separates missing-only exclusions
(D3), observed-but-omitted outcomes/wrong grouping (D2), and an unknown exclusion
mechanism (cannot infer inappropriate analysis from counts alone). The
clarification was tested offline; no model call was made against it.

## Durable usage

Eight `token_usage_record` generations sum exactly to the final durable turn
usage: **225,640 input; 178,432 cached; 47,208 uncached; 2,739 output**, including
984 reasoning output; 228,379 total. Run.json contains the earlier monitor
snapshot, seven token_count updates; it omitted a generation completed during
cancellation. The final input exceeded the 200,000 monitoring threshold by
25,640. Use `final-durable-usage.json`, not the monitor snapshot, for recorded
usage. These are recorded generation totals, not an account-invoice claim.

The original owned rollout and credential-bearing home remain local. Public
events preserve source-text/tool receipts; image blobs are replaced with encoded
content hashes. No credentials, raw homes or stderr are committed.
