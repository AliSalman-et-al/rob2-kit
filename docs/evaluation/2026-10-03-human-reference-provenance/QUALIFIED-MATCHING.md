# Qualified matching addendum — independent AI methodological review

This addendum supersedes the earlier recommendation to exclude DAPA-HF from every reconstructed subset. It preserves the historical October 1 alignment finding: **0 fully aligned**, with 80 unknown and 26 mismatched targets, among 106 examined; 98 assessments accepted. Newly retrieved evidence and a separately declared reconstruction stratum do not retroactively alter that audit or original Code benchmark labels/inputs.

The independent source-scope review was supplied by the parent on October 3. It is **AI methodological matching**, not a new human bias adjudication or an author-confirmed assessment worksheet. Matching was decided from source scope before this agreement extraction; the inclusion rule is independent of model agreement.

## Inclusion rule

1. **Confirmed/unambiguous reference crosslink:** reference explicitly binds the selected result, or a unique crosslink establishes its scientifically equivalent scope without material alternatives. Identical phrasing of every field is unnecessary.
2. **Reconstructed unique main result:** reference identifies trial primary outcome/contrast and cited report identifies a unique main primary result; record population, time and estimand assumptions. Keep separate from confirmed references.
3. **Ambiguous material alternatives:** multiple substantively different eligible results/populations remain; exclude from the principal reconstructed denominator. Any conditional comparison must name its assumption separately.
4. **Unknown:** available source linkage cannot establish even a defensible reconstruction. Do not substitute trial-level labels for selected-result assessments.

## Two-case application

**DAPA-HF: reconstructed unique main result.** Published eTable 2 links dapagliflozin/placebo ratings to the trial primary outcome; cited report identifies the main full-cohort primary composite HR0.74 (95%CI0.65–0.85), all4744 randomized under ITT, through trial follow-up, median18.2months. No competing primary population was identified in this review. Explicit assumption: ratings refer to that main ITT result and assignment-effect question. This is defensible reconstruction, not original-workbook custody or author confirmation. Requiring the RoB table to repeat every field would be overstrict.

**DELIVER: materially population-ambiguous.** The original report describes concurrent primary analyses in the overall population (HR0.82) and LVEF<60% population (HR0.83). The eTable 2 primary-outcome wording does not choose between them; full-trial N6263 in eTable 1 is context, not unique label-population binding. Exclude from the principal reconstructed denominator. No conditional agreement numbers were newly assembled.

Sources: [JAMA review DOI10.1001/jama.2025.20834](https://jamanetwork.com/journals/jama/fullarticle/2841163), [Supplement1 eTable2 physicalp4](https://cdn.jamanetwork.com/ama/content_public/journal/jama/939771/joi250094supp1_prod_1767896097.23085.pdf), [DAPA-HF primary report](https://eprints.gla.ac.uk/197128/1/197128.pdf), [DELIVER primary report, printed1091](https://eprints.gla.ac.uk/278117/1/278117.pdf). Public retrieval is distinct from original archived workbook custody. Exact archived fields and retrieval hashes remain in the preceding audit files.

## Frozen assessment comparison

| Complete assessment | D1 | D2 | D3 | D4 | D5 | Published-domain agreement |
| --- | --- | --- | --- | --- | --- | --- |
| Original October1 Code benchmark | Low | Low | Low | Low | Low | 5/5 |
| Latest complete retained DAPA development assessment, October2 ad312a4 | Low | Low | Low | Low | Low | 5/5 |
| All-Low comparator | Low | Low | Low | Low | Low | 5/5 |

`qualified-dapa-frozen-comparison.json` extracts each entire finalized archive separately, with SHA256, snapshot/checkpoint identities and selected-result fields. Later D3-only diagnostics are excluded: they are not new complete assessments, and older D1/D2/D4/D5 records were not stitched into a supposed current full assessment. The latest complete row is a retained development checkpoint, not an assessment of today's code. Human overall is absent, so model overall is not scored and no human overall is derived from domain counts.

This is **one case with five correlated domains**, already used in development. Both frozen assessments and All-Low agree5/5. No discrimination, accuracy gain, generalization or current-code whole-assessment gain is established; agreement does not certify every scientific warrant.

## Remaining blocker and future protocol

Broader performance evidence requires a sufficiently diverse independently scope-matched case set, with material non-Low cases and scientific disagreement adjudication, frozen selection independent of outputs, then prospectively authorized evaluation of complete assessments against All-Low. One reconstructed all-Low case cannot establish superiority. DELIVER requires population-scope resolution before principal inclusion.

The ready future protocol entry point is [proposal-diagnostic-protocol.md](../proposal-diagnostic-protocol.md), with frozen evidence/criteria/manifests and `scripts/diagnostic_evidence_preflight.py:launch_checked` where applicable. This path is preparation, not authorization to run. No further research, implementation edits, paid calls, benchmark, merge or CI wait occurred. Prior CI snapshot6178e93green does not establish current-HEAD green.
