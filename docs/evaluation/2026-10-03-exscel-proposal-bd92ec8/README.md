# EXSCEL fresh Proposal Review — approval pending

One authorized isolated `gpt-6-luna` medium invocation on clean frozen `bd92ec84fb1b24a05ac742db8ea01f3c9b7bcf6a`. Exact launcher and durable turn model/effort verified. Five original Code files hash-match; original metadata and roles unchanged. No prior approval, answers, benchmark labels, source-specific page hints or expected conclusions supplied. Current production skill/export and native MCP schema preflight used. No operator repair or second invocation.

## Human review packet

**Identity:** supplied primary report *Effects of Once-Weekly Exenatide on Cardiovascular Outcomes in Type 2 Diabetes*, NEJM 2017, EXSCEL. Article PDF page 1 identifies **NCT01144338**. Original sources.toml instead declares **NCT01455896**. The source identity is clear; the metadata discrepancy is unresolved. Registry transport was deliberately blocked at normal intake to avoid importing a wrong-study record; normal unavailable condition retained. No identifier rewrite, live retrieval or equivalence inference occurred. The original outcome row also identifies NCT01144338.

**Proposed target:** assignment to extended-release exenatide 2 mg subcutaneously weekly versus matching placebo weekly; all randomized EXSCEL participants; first cardiovascular death, nonfatal myocardial infarction or nonfatal stroke; from randomization through trial closeout/censoring; primary Cox time-to-first-event hazard ratio. Follow-up is variable, median 3.2 years, not a fixed-time risk. Population: 14,752 randomized, 7,356 exenatide and 7,396 placebo, all included in primary ITT.

**Reported Result:** literal `Primary composite outcome`, HR **0.91**, **95% CI 0.83–1.00**. Primary events 839/7356 versus 905/7396 are corroborating source counts, not an observed-at-closeout denominator. Coprimary noninferiority safety and superiority efficacy hypotheses concern the same selected primary effect; source reports noninferiority met, superiority not met. The saved reported endpoint definition is null; interpreted composite meaning remains in target/rationale.

**Claimed relation:** `exact`. No substantive change from the authoritative benchmark primary target, arms, assignment population or first-event measure/window is found. The model correctly keeps metadata uncertainty explicit. This exact relation is reasonable for the primary Result correspondence, qualified by incomplete investigation of detailed clinical event criteria. All eight clarity facets are marked specified; **complete measurement-definition clarity is not independently established** by this trace.

**Actual source evidence:** main report page 1 (trial identity/abstract), page 2 (assignment), page 3 (primary definition, blinded adjudication and all-randomized ITT), page 6 (primary quantity and Table 1 footnote). Exact source-bound passages and four reported-field bindings are retained in the immutable review. All 12 primary-report pages were delivered (55,415 source bytes). Protocol pages 1–3 were also read for identity. No appendix clinical-definition pages, MACE-flow Figure S2 or later protocol/SAP pages were read. Proposal construction establishes primary correspondence; it does not complete D2/D3/D5 or demonstrate the new cross-page reading guidance's benefit.

**Pending action:** `researcher_review`, authority `researcher`, purpose `proposal`, state revision 3. Actual immutable Review reference:
`sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66`.
Saved proposal:
`sha256:28982d105319fc9fddb2b437f6ffbac041a811e0b2fc209ea1213202ee4aba5d`.

The complete [immutable Review](immutable-proposal-review.json) is the approval object. No approval action/reference recording acceptance exists. The tool action after explicit conversation approval is `request_proposal_approval({})`, whose actual elicitation must bind to this Review. Parent/user must approve or request a concrete scope correction; old approval cannot be reused. Approval does not certify uninspected detailed criteria or prejudge Domain answers. No Domain may start until the gate is satisfied.

## Execution and limitations

Validation succeeded on attempt 2: first attempt failed joint endpoint-definition support and a reformulated raw effect-measure string; model omitted the optional raw definition and used the literal supported measure. `save_proposal` then returned `review_required`, persisted the Proposal and immutable Review. Model made four further calls: status, a working-checkpoint schema error, corrected working checkpoint, status; then exited normally with a review packet and approval pending. Working checkpoint recovery was autonomous. No domain/approval tools were enabled.

The runner mistakenly recognized only outcome `success` as saved; production's correct saved outcome is `review_required`. Consequently run.json has stop_reason null and natural exit 0, rather than the intended immediate observer stop. This is diagnostic accounting/control weakness, not a failed save or permission breach. Actual phase remains proposal/revision 3; no domains, approval, review closure or finalization occurred. Fix terminal recognition before any future run; do not relaunch this one.

Elapsed **138.7705 seconds**; **17 MCP calls**, zero custom-wrapper calls; two validation attempts. **939,302 total tokens**: 934,335 input, 844,544 cached, 89,791 uncached; 4,967 output including 787 reasoning. Input telemetry only; output6,000/tool30/wall600/idle180/four-attempt/two-identical-error limits not exhausted. Dollar billing unknown. Auth/model cache were reused through existing unchanged files, no login/auth modifications. A pre-inference relative-path inspection error was recovered against the already-completed normal intake; it did not rerun intake, repair model state or consume inference.

Development validation, originally benchmark-exposed; not heldout. No domain agreement or accuracy gain is claimed. Reference Result alignment remains unknown. Full post-fix CI remains unverified; no wait/log retrieval here.

## Remaining full workflow, not launched

After actual approval, resume this preserved working state using status and approved Result. The [frozen production plan](../2026-10-03-exscel-production-plan/README.md) supplies full lifecycle and independent scientific criteria: all five Domains, D2 cessation/assignment-analysis distinctions; D3 actual MACE coverage versus vital status/completion and missingness mechanism; D4 full applicable event definitions; D5 applicable protocol/SAP versions and executed versus planned analyses. Then expand decisive Trial review findings, correct concrete unsupported links only, close using exact review identity, finalize and verify the artifact. Preserve registration discrepancy and reference-scope qualifications. No domain labels, old answers or observer locators are model-facing coaching. Approval-dependent continuation is not launched prematurely.
