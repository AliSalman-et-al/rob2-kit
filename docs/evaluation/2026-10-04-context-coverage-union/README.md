# Coverage union and frozen context replay

The coverage projection now unions overlapping or adjacent delivered line ranges within the same current source, page and delivery phase. Gaps, different phases/pages/sources and empty-page sentinels remain separate. Raw page-read receipts remain unchanged. Union occurs before the existing 128-range preview limit, so repeated reads no longer crowd out distinct coverage. `range_count` describes disjoint intervals. Scientific account, evidence, questions, comparison cards, source bindings and cursor invalidation rules are unchanged.

## Trace diagnosis

The account-first BeNeDuctus run delivered three complete four-page D5 contexts. The first and second differed in account and read/recovery state, requiring a fresh snapshot. The second and third full snapshots were identical; the third followed compaction. Neither chain arose from cursor invalidation. Existing immutable cursor snapshots already survive additional reads/search and unrelated domain commits. A receipt of earlier delivery cannot establish retained context after compaction, so automatic suppression would be unsafe. The existing larger-budget single-page capability remains unchanged; this adds no transport setting or wrapper.

## Offline measurement

Actual frozen context-cache snapshots were replayed through the existing 32,768-byte paginator. Baseline per-page wire-envelope byte counts reproduced the captured trace exactly. Coverage was recomputed by the changed application function in an isolated workspace; source/page/phase line unions and coverage states were identical. Reassembled candidate pages preserved every other full context field exactly.

Across all three deliveries: **214,477 → 209,265 bytes**, saving **5,212 bytes (2.43%)**; **12 → 12 actions**. Range counts changed 14→12, 72→46 and 72→46. Page allocation shifted under the existing paginator. These are operational byte measurements, with no provider-token, latency, compaction or accuracy gain claimed. There was no paid inference. Original paired judgments and all 106 terminal-frozen files remain intact.

## Account recovery and scientific review

Account recovery preserves host-authored unknowns; it does not automatically resolve their semantics when later source lines arrive. The account-route investigation projection does not prioritize old unknowns, turn them into NI, or gate confidence. Legacy premise-record ordering is a different path. This run lacked explicit answer-step dependency references, limiting reconsideration cues. Model anchoring on a retained severity-label unknown is plausible, but this trace does not establish a server certainty gate. No generic certainty gate or case-specific BPD equivalence was introduced.

Independent parent source review favors cautious D5 PY/PN/PN Low: severe-to-mild reclassification would affect the composite only if mild BPD lay outside its primary definition; original protocol defines BPD by oxygen need at 36 weeks. The unresolved severity-label objection is weak after the later source evidence. The genuine SAP/report centre-adjustment and Poisson-versus-adjusted-OR mismatch remains relevant, without inferring selection of the primary unadjusted result. This review does not mutate either frozen judgment and is separate from the transport fix.

## Validation and provenance

The new focused union test passed after correcting fixture initialization. The 27 existing working-checkpoint tests passed in the earlier run; four targeted cursor/snapshot tests passed. Ruff, changed-source type checks and diff whitespace checks passed. See `validation.json` for the exact run accounting, `replay-receipt.json` for each delivery, `reconstruction-conservation.json` for pagination conservation, and `freeze-receipt.json` for the private replay artifacts. No full benchmark or default account adoption was performed.
