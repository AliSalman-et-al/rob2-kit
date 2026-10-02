# Offline guard and context audit

No model invocation was made for this checkpoint. It examines the preserved DELIVER D3 run at runtime db8e68d, using the required Code benchmark corpus. No accepted judgment exists, so there is no scientific agreement or accuracy claim.

## Guard reliability

The historical launcher silently used 500,000 total input tokens while the authorized threshold was 400,000. An operator terminated it after durable usage reached 441,823. Its preserved raw run record must not be mistaken for a correctly enforced automatic stop. The previous generation ended at 384,822; the next added 57,001. Even correct reactive enforcement can overshoot within a generation.

`scripts/domain_probe_limits.json` now provides the sole numeric configuration: 480 wall seconds, 120 idle seconds, 16 tool calls, two rejected submissions, 400,000 total input tokens, 100,000 uncached input tokens, and 5,000 output tokens. Preparation derives manifest and prompt from that configuration. Before process creation, the launcher verifies exact guards, identity, prompt hash and generated guard section, exact gpt-6-luna / medium settings, a fresh isolated rollout home, and the frozen clean checkout. The monitor uses the same validated object. No numeric override, automatic retry, or campaign loop exists.

Use `domain_probe_controls.write_controls(root, manifest, task)` from fixture preparation instead of editing historical launcher strings. Then `python scripts/run_domain_probe.py ROOT --check-only` performs preflight without inference; actual execution requires separate authorization. Existing recorded preparations are never overwritten. The launcher runs one already-prepared fixture and does not create credentials or fixtures. It records completed saves before evaluating the completed-tool limit, drains final events, and retains cumulative cached and uncached accounting separately.

Focused validation: 17 guard/control tests passed; Ruff and ty passed on the new scripts. Threshold drift, prompt drift, and identity drift are rejected before a mocked process could be created. No broad tests or paid calls were made. The subprocess monitor itself has not been exercised in a paid invocation.

## Exact usage and attribution limits

[Generation ledger](generation-ledger.json) derives per-generation usage from the preserved durable records, and UTF-8 payload sizes from actual model tool outputs. Totals: 441,823 input tokens, of which 381,952 were cached and 59,871 uncached; 2,415 output tokens, including 728 reasoning tokens. Cached prefill is a context/latency measure with separate billing treatment, not an equivalent uncached cash expense. Dollar cost and any interrupted generation without a durable record are unavailable here.

| Initiating stage | Input | Cached | Uncached | Output |
|---|---:|---:|---:|---:|
| Declaration discovery (two generations) | 14,139 | 8,704 | 5,435 | 178 |
| Domain context | 16,609 | 6,912 | 9,697 | 64 |
| Required main-report reading (three) | 101,801 | 75,008 | 26,793 | 741 |
| Searches (two) | 93,753 | 88,576 | 5,177 | 644 |
| Targeted source reading (three) | 158,520 | 146,688 | 11,832 | 654 |
| Evidence selection | 57,001 | 56,064 | 937 | 134 |

These are exact generation totals, not causal category charges: each generation includes prior context. No tokenizer-based allocation of individual sections is available.

The second discovery call printed every tool's full declaration, including output signatures: 36,667 bytes. The first had already obtained the submission input declaration (3,177 bytes). The next generation's input grew by 9,116 tokens, including wrappers and output; that growth cannot be assigned exactly to the catalog. The unnecessary catalog persists in later prefixes. The generated probe instructions now request only the needed input declaration and prohibit the full catalog dump. This is a demonstrated workflow inefficiency, not evidence of a core runtime defect.

All nine tools remain available: get_domain_context, read_pages, select_text_evidence, search_sources, search_sources_batch, list_sources, render_page, select_visual_evidence, save_domain_judgment. Actual scientific work used context, page reading, batch searches, and evidence selection; no submission occurred. There is no reason to remove visual or recovery capabilities merely because this trace did not use them.

The initial context response was clipped by the code-mode output budget (reported original 13,866 tokens; visible body 40,106 bytes). Native context sections included questions (15,507 compact JSON bytes), evidence (13,323), comparison cards (9,760), official guidance (3,046), Result (2,868), and other guidance (2,724). The card includes source coordinates, paired examples, propositions and exact target/reported-result distinctions. Some selected main-report passages recur in mandatory complete reading; that repetition alone does not justify deleting evidence or guidance. Context/head/scope metadata recur in tool responses, but no measured safe core reduction is established. No application schema or context contents were changed in this pass.

Required main-report reading consumed three calls because returned continuations had to be completed. One unscoped batch returned captured_source_unavailable rather than absence receipts; a later source-scoped batch searched available PDFs. The appendix flow evidence appeared in generation 10. Only a protocol continuation and two evidence selections followed before interruption. This was not an endless late search loop. The protocol describes planned sensitivity procedures; it does not prove they were performed. There is no scientific draft from which to infer what the next judgment would have been.

## Lean next diagnostic policy, pending discussion

Keep every existing threshold unchanged. The 400,000 total-input cap halted after decisive evidence selection despite much lower uncached and output usage; it measures repeatedly processed history and can prevent a useful submission. That finding is not permission to increase it. First avoid the catalog dump and repeated hosted-schema demonstration, preserve complete context through an adequate code-mode output budget or server continuations, and use returned available source handles when a capture is unavailable. Do not inject gold answers, page hints, or reference certainty.

Stop on accepted save, the first observed guard, or two rejected submissions. Allow at most one model-owned construction correction within those same guards; no second invocation or automatic retry. A future diagnostic should aim for a complete scientifically inspectable checkpoint with modest uncached/output usage. Removing the catalog may leave more room, but no completed run or measured token saving establishes that yet. No further model call is authorized in this pass.
