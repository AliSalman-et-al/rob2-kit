# Selected review: complete saved claims before deferred support

The selected-Domain packer now returns a bounded typed summary containing the **complete saved judgment, rationale, unknowns, counterevidence, citation identities/roles and exact Result scope** when that set fits. Supporting/context source prose and investigation detail remain explicitly deferred, with `complete:false` and the existing stable recovery action. If the complete claim set cannot fit, it retains the existing lossless fragment path. No assessment, RoB logic, byte budget, production reviewer stage or mandatory gate changed. No model calls occurred.

This corrects a concrete presentation issue: the native Baby-OSCAR D4 prefix contained only the first answer's question identifier and omitted the differential warrant. It does not establish that a model will inspect support, correct attribution or improve a scientific judgment. The earlier extra-reviewer experiment remains rejected for adoption; it was not repeated.

## Precise before/after first views

| Preserved receipt | Before | After |
| --- | --- | --- |
| Exact cached Baby-OSCAR D4 | 24,000-byte fragment; only `method-inappropriate` question ID visible; numeric warrant absent | **14,970-byte summary**; all three complete saved answers, exact Result scope and citation bindings visible; numeric warrant present |
| Unrelated EXSCEL D5 saved projection | 24,000-byte fragment; only `prespecified-analysis` question ID visible | **17,798-byte summary**; all three complete saved answers, scope and citation bindings visible |
| Source inspection | Incomplete fragment with next cursor | Explicitly incomplete: `complete:false`, named deferred `facts`/`investigation`, full counts and stable recovery at offset 0 |

`baby-before-first-view.json` and `baby-after-first-view.json` preserve the exact contents, as do the EXSCEL counterparts. `before-replay.json` / `after-replay.json` compare all saved core fields and all original expansion-locator fields. Normal typed serialization can add default character-window fields (`start_char:0`, `end_char:null`); existing source identity, page, line range and evidence identity remain unchanged.

The complete saved differential warrant now visible in the first Baby view remains:

> The same 36-week assessment point, BPD criteria, and oxygen-reduction approach apply to both randomized groups; trial personnel and outcome assessors were blinded. For eligible infants, oxygen-reduction testing was not performed in similar proportions (13/86 vs 13/94). No group-specific threshold or assessment method is reported. This supports probably no differential measurement; the exact assessment opportunity for every participant is not fully detailed.

Its unknown about unavailable outcome information and incomplete reasons for missing oxygen assessments is also retained in full. Its original selected citations remain `eh_324148091d5038f7` (appendix p14), `eh_664cb2e87a63db02` (main p3), and `eh_d6d5b2bf301983ce` (main p6). No main p7 repair citation was inserted. The saved scientific judgment and existing attribution defect are unchanged.

The other two Baby warrants/unknowns, and all three EXSCEL D5 warrants, are similarly complete rather than relocated to a later claim fragment. Thus this does not merely move an omitted decision-critical saved claim to another first-page boundary in either control. Oversized claim/uncertainty sets remain an explicitly tested limitation: full fidelity takes precedence over clipping them into a purported complete summary.

## Reuse of d789ea8 and recovery integrity

`d789ea8` added a whole-Trial compact fallback that preserves bounded warrant/unknown previews before source prose, with progressively shorter preview limits. It still applies unchanged to unselected Trial summaries. Selected oversized Domains previously bypassed it and went directly to alphabetical JSON fragments; their `facts`/source expansions could precede a later question's `justification`/`warrant`.

This change extends the **existing `_review_summary` path**, rather than adding a second projection/reviewer system. The selected variant copies saved claim fields in full; support/context facts are named as deferred. Counterevidence facts, counterevidence implications, conflicts, limitations, unknowns, basis roles and all citation identities remain in the first view. If these fields or exact Result scope make the summary too large, the original fragment path is used rather than truncating contrary information.

The full recovery snapshot/serialization is unchanged. Baby digest remains `sha256:26dc91a79a978295c368afde423fc66c0a3d926db6ad5b99e46a30b9d291caa6`, with the same 20,041 + 18,820 character fragments. EXSCEL digest remains `sha256:4a487f0878d28f65c3587aba7f037efb7e65bf4f41acda3041a2abdb2db144f4`, with the same 20,188 + 19,900 + 5,844 fragments. Old `rv1` offset cursors still recover the same text; no cursor-version migration, snapshot edit or canonical digest rewrite occurred. New selected summaries point to the existing stored selected target at offset 0. Sources can also be inspected through the preserved exact Evidence expansion actions.

The transport ceiling remains **24,000 bytes**, including the same native wrapper allowance. First-view byte reduction is not a scientific metric. The summary still requires source-grounded interpretation; visibility does not certify support, source truth, plan execution or completeness of source reading. Guidance explicitly says `complete:false` does not mean source inspection is complete. Workflow continuation remains the existing close action; no new approval/review gate was introduced.

## Provenance and tests

Baby uses the exact digest-verified cached review snapshot through read-only SQLite access. EXSCEL uses the original `item_35` review envelope and saved final state, with current source findings reconstructed on a separate copy of its preserved workspace; the obsolete summary flag is removed from that reconstructed input. This is an unrelated long saved-review control, not a new model response or fabricated assessment history. Both arms receive identical scientific snapshots. Before code is frozen from `5b968820d17f5f7a0432df364353792c46a0f016`; after uses current code. Replay uses `persist=False`. Originals and historical bundle hashes are unchanged.

Focused tests cover exact Baby/EXSCEL claims and scope, source/citation bindings, explicit deferred support, counterfact preservation, unbounded-claim fallback, byte limits, full selected-target reconstruction, pre-change cursor offsets, existing stale/corrupt cursor behavior and the unchanged whole-Trial fallback. Both producer and independent verifiers passed for the unchanged Baby and historical EXSCEL bundles. Public input/output schemas are unchanged; the current public contract synchronizes only the new `review_trial` description.

The first focused run had 46 passes and one release-description mismatch because the synchronized description changed while its Python process retained the earlier imported description. That failed output is retained. After final files, fresh contract/native-stdio checks passed **8 tests**, and final packing checks passed **11 tests**. This completes the 47 distinct focused checks across runs, without a full-suite or broad rerun loop. Lint, formatting and typing pass across `src tests docs/release`.

## d6bdae5 CI triage

Read the representative completed Windows 3.12 failed job once. It had two failures (`mcp` and `mcp-codex` stdio probes), 1,382 passes and eight skips; the same failure class occurred only on Windows 3.11/3.12/3.13. The new test had created a POSIX shebang file and attempted to execute it as a native Windows application, producing `WinError 193` before MCP startup.

The fix uses the installed platform-native `rob2.exe` on Windows / `rob2` on POSIX beside the active interpreter, with explicit test `PYTHONPATH` pointing to this checkout. It retains both real stdio/inventory tests, with no skip or larger timeout. Both probes pass locally. Windows execution itself awaits ordinary CI; no CI wait was performed. `ci-findings.json` records provenance, before/after results and the transient local check failures.

## Next supported scientific test

A future authorized test should use **one fresh native assessment of an unrelated, scope-matched Code benchmark case that produces a long selected review**, through the ordinary production workflow and existing isolated `gpt-6-luna` Medium setup. Do not reopen Baby-OSCAR or repeat the rejected factual-audit response. Freeze the case, sources, scope, interpretation criteria and unchanged tool/token/time limits before inference; provide no bad-clause hint, repair page or desired reference label.

Primary observations should be: complete saved-claim delivery, actual source inspection/recovery, ordinary model-owned source/rationale revisions, correct retained uncertainty and false alarms across all saved review warrants. Preserve cases where no revision is justified. Label agreement is secondary and only interpretable after outcome/population/time/effect alignment is established. A first-view visibility check or smaller fragments alone cannot count as a scientific gain. No such inference is authorized or run in this pass.
