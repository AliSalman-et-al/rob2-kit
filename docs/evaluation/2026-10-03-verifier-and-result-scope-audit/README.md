# Offline verifier synchronization and Allsop scope audit

No paid inference, artifact edits, assessment repairs, or label changes occurred in this pass. The preceding all-Domain completion remains a positive known-case workflow observation, not broad accuracy evidence.

## Verification reproduction and repair

Exact source at `992bf68` was extracted into a disposable diagnostic directory. Against the unchanged completion bundle (SHA-256 `845b43ae089382cfd53c3f32dd492c5222752ce60e4cd1ddf880cb4427a0c6d6`), installed verification passed and standalone verification rejected `scientific pack descriptor differs`. Against an unchanged actual v0.8 Allsop artifact from the required Code benchmark, installed verification failed while standalone verification passed. `verification-before-after.json` records commands' outcomes, artifact hashes, and verifier source hashes.

Production computes its pack hash from all current guidance. Commit `e6b893b` changed operational guidance 1.0.7 to 1.0.8 and added the observation-versus-analysis-exclusion distinction, yielding `d6ff8a6a…`. Standalone verification still pinned `c2650a6e…`, and the explicit hash test was stale. Separately, the installed verifier's historical list omitted seven exact descriptors already recognized by standalone verification. This is version synchronization drift, not corrupt artifact bytes or a mismatch in the cited Cochrane version.

The standalone pin now matches the packaged current descriptor and retains `c2650a6e…` as a named historical descriptor. Installed verification restores the seven exact historical hash/semantics pairs. All comparisons still include the full closed descriptor, including official provenance and semantics; no arbitrary hash, altered provenance, unknown version, or extra field is accepted. The standalone script remains dependency-free and does not import the producing package. A parity test prevents future guidance/hash drift, while an actual historical artifact exercises old-version verification.

Both verifiers now pass both unchanged artifacts. Five descriptor controls pass, including rehashed mutations of content hash, version, semantics, official-source hash, and extra fields. Four further historical controls pass: three v0.7 pack versions and the historical envelope without Trial closure fields. Ruff, format checks, and production type checks pass. The initial synthetic historical test failed on an incomplete verification claim, not descriptor acceptance; it was replaced with the unchanged real Code benchmark artifact. Original archived failure results remain unchanged.

## Exact Result scope

The inherited approved target is overall CWS severity during days 1–6, with effect of assignment among all randomized participants. The bound reported number is Table 2's overall-withdrawal treatment-by-time `F=2.39`. Table 2's footnote explicitly says its mixed model uses days 1–9; the days 2–6 means are separately described. Thus the reported F statistic cannot be relabeled as an exact six-day interaction estimate merely because the clinical medication phase lasted six days.

The inherited Result nonetheless has `relation: exact` and all clarity facets marked specified. Its own `relation_rationale` acknowledges the nine-day model. That is an actual inconsistency in approved target-to-reported-result metadata, propagated faithfully into comparison cards as `target_relation: exact`. It predates this invocation. The model preserves the two windows in its final account but cannot resolve their mismatch by treating the approved target as changing the model's scope.

Numeric source binding is intact: the F statistic, measure, and endpoint are bound to the captured Table 2 passage. The proposal validator checks source-bound reported leaves and declared clarity, while target timing and interpretation are caller-owned; it does not certify entailment of every relation rationale. This audit therefore establishes a host-owned scope assertion error and a representation limitation (the reported projection has no separate structured time window), **not evidence that source bytes or numeric binding were falsely verified**. A stronger automatic semantic gate is not justified by this case. The target, relation, original judgments, and artifact were not rewritten. Exact outcome-level agreement remains unscorable without an independently resolved matching Result.

Source locators: selected Evidence `73e96ee9…`, physical main-report page 7, footnote at line 156; inherited target/relation/rationale in the unchanged bundle's approved proposal. The approved-source main PDF hash remains `7203667c…`.

## D2 masking and analysis

The main report, physical page 3 lines 32–36, says patients, investigators, and outcome assessors were masked until procedures were complete, describes matched placebo, and reports a pre-discharge patient blinding check. The abstract (page 1 lines 29–31) and page 5 lines 27–29 report that participants could not reliably distinguish assignments. Those statements support patient masking. The D2.1 draft cites page 3 and page 9; the latter does not contain the blinding check it invokes, although the model had delivered and selected the actual page 5 passage. This is an imprecise citation/support choice, not a fabricated source fact.

D2.2 cites the page 3 masking statement and answers No, yet retains the unknown of whether every intervention delivery caregiver was covered. Investigator masking supplies evidence, but the report does not explicitly name every caregiver. Probably no would express the model's residual uncertainty more faithfully; this audit does not replace the accepted answer or claim a different Domain judgment is mandatory. The masking evidence supports a defensible Low interpretation, while definite caregiver non-awareness is overstated relative to the model's own unknown.

D2.6 cites page 4's inclusion of all 51 randomized participants in the intention-to-treat analysis. The selected F statistic is from the unadjusted Table 2 model; adjusted Table 3 results are separate. Inclusion supports preservation of assignment, while multiple imputation does not establish complete observed CWS data. The model kept those concepts separate in D3. The target-window mismatch still qualifies any claim that this is precisely the requested six-day estimate.

No production semantic or scientific judgment rule was changed. Further scientific work should resolve the chosen Result and calibrate claim certainty before treating this case as accuracy evidence.

## Usage ledger

`usage-ledger.json` lists the three unique retained full-Allsop diagnostic invocations without counting copied archives as extra runs. This offline pass added zero paid invocations. The latest run used 4,974,118 total input, 4,738,816 cached input, 235,302 uncached input, and 8,813 output tokens. These are provider usage records, not inferred monetary costs or hard billing bounds. Input counts remain telemetry only; production and diagnostic input policy were unchanged here. `paid-case-inventory.json` preserves the updated exclusion inventory; Allsop remains a known development case.
