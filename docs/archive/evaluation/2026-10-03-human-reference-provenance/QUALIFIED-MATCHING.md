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

## Additional read-only reference audit supplied 2026-10-05

A separate reference audit supplied through the parent thread reconstructs two
additional unique main results. This entry preserves that audit's findings; it
does not represent a new prediction inspection or independent reinspection by
this implementation task. Benchmark data and labels remain unchanged.

The Code benchmark revision is `d04473df4a07a3117f3171df2d8471ec0defd522`,
`OUTCOMES/LABELS-batch.csv`, lines 80–81. The human source is Neuen et al.,
[JAMA DOI 10.1001/jama.2025.20834](https://jamanetwork.com/journals/jama/fullarticle/2841163),
Supplement 1, physical page 4, eTable 2 rows 6 and 7. Both rows explicitly assess
trial primary outcomes and report D1–D5 Low, with no overall judgment. Assessors
were B. L. Neuen and H. J. L. Heerspink. The separate audit checked the live
supplement and archived image independently; the archived locator is main-repo
revision `5cd5ccceead5b6f40be80f13050e78ece26fa97d`,
`docs/evaluation/2026-10-03-human-reference-provenance/new-public-etable2-page4.png`.

| Case | Reconstructed main Result | Primary report physical-page locators |
| --- | --- | --- |
| EMPEROR-Reduced, NCT03057977 | Empagliflozin 10 mg versus placebo; all 3,730 randomized participants, ITT; adjudicated cardiovascular death or heart-failure hospitalization, time to first event; HR 0.75 (0.65–0.86), 361/1,863 versus 462/1,867; cutoff 2020-04-29. Median 16 months describes follow-up, not a fixed endpoint. | `NEJMoa2022190.pdf`: definition p3; ITT/Cox p5; Table 2 p6; cutoff p7. |
| EMPEROR-Preserved, NCT03057951 | Same contrast and primary composite; all 5,988 randomized participants, ITT; HR 0.79 (0.69–0.90), 415/2,997 versus 511/2,991; cutoff 2021-04-26. Median 26.2 months describes follow-up, not a fixed endpoint. | `NEJMoa2107038.pdf`: definition/ITT/Cox p3; cutoff/results p4; Table 2 p7. |

Both belong only to the **reconstructed unique main result** stratum. The human
table does not explicitly restate the population, cutoff, or assignment estimand
and provides no signaling-question rationales; binding those elements from the
unique primary report remains a reconstruction assumption. These are not
author-confirmed exact-result worksheets. They add no non-Low label diversity.
The existing DAPA-HF reconstructed stratum is unchanged. No accuracy calculation,
new case launch, or prediction inspection follows from this entry.

## Bounded non-Low reference search supplied 2026-10-05

The parent supplied a separate, explicitly label-stratified reference audit that
found **zero fully qualified exact-result matches**. No predictions were
inspected. The following are verified discrepancy diagnostics from that audit,
not exact-result accuracy references; this implementation task preserves the
findings without changing benchmark labels, inputs, or model prompts.

| Case and Code row | Human RoB 2 rating and review result | Primary-report/Code result and binding limit |
| --- | --- | --- |
| Bausys 2023, NCT04223401; CSV line 48 | BJA review eFigure 1, second row: D1 Low, D2 Some concerns, D3–D5 Low, overall Some concerns. Complications forest Figure 2 uses 14/61 versus 36/61, RR 0.39 (0.23–0.64). | Primary Methods/Table 2: 64/64 randomized; intervention-starter analysis 61/61; operated primary 90-day complications 14/59 versus 35/59, RR 0.40 (0.24–0.66), matching the Code anchor. Both event counts and denominators differ from the review forest. Study-level human graphic lacks explicit outcome/window/population/estimand linkage. Exact label transfer is unestablished. |
| Einarsson 2017, NCT01566929; CSV line 44 | HRU RoB 2 Figure 2, fifth row, printed p114: D1–D4 Low, D5 Some concerns, overall Some concerns. Live-birth forest Figure 3, p117 uses 45/160 versus 42/157, OR 1.07 (0.65–1.76). | Primary full analysis set 45/152 versus 42/153 matches Code. FAS requires follow-up and IVF start or spontaneous pregnancy; one cycle includes postrandomization spontaneous pregnancy, follow-up ends February 2017, and is not a common fixed window. Human rating has no explicit assessed-result linkage; exact transfer remains unverified. |

Bausys sources: [review](https://pmc.ncbi.nlm.nih.gov/articles/PMC11947603/),
[original RoB 2 supplement](https://ars.els-cdn.com/content/image/1-s2.0-S0007091225000236-mmc1.docx),
and [primary report](https://academic.oup.com/bjs/article/110/12/1800/7282358).
The audit checked primary HTML; its primary PDF was unavailable. Prior Bausys
exposure was Source/preflight metadata only, with no paid assessment.

Einarsson sources: [review](https://pmc.ncbi.nlm.nih.gov/articles/PMC12766448/)
and [primary PDF](https://academic.oup.com/humrep/article-pdf/32/8/1621/18774991/dex235.pdf).
Primary locators are outcome/FAS p1623, flow p1624, and Table II p1626. The human
ratings are actual RoB 2 ratings; this is not a RoB 1 relabeling problem.
EMPEROR preparation remains separate and adds no non-Low reference diversity.
