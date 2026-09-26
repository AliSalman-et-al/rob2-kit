# rob2-kit RCT benchmark: Overall Survival, Progression-Free Survival, and Adverse Events

## Result summary

Across 26 requested outcome/trial cases, rob2-kit matched the catalog labels exactly on **85/130 domain judgments (65.4%)**. Grouping Some Concerns and High together as non-low, agreement was **96/130 (73.8%)**. For the overall risk-of-bias judgment, exact agreement was **4/26 (15.4%)** and Low vs. non-low agreement was **21/26 (80.8%)**.

| Outcome | Cases | Domain exact | Domain Low vs. non-low | Overall judgment exact | Overall Low vs. non-low |
|---|---:|---:|---:|---:|---:|
| Adverse Events | 7 | 17/35 (48.6%) | 22/35 (62.9%) | 0/7 (0.0%) | 6/7 (85.7%) |
| Overall Survival | 10 | 39/50 (78.0%) | 41/50 (82.0%) | 2/10 (20.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 9 | 29/45 (64.4%) | 33/45 (73.3%) | 2/9 (22.2%) | 9/9 (100.0%) |

### Accuracy by RoB 2 domain

| Domain | Exact labels | Low vs. non-low |
|---|---:|---:|
| D1 — Randomization process | 25/26 (96.2%) | 25/26 (96.2%) |
| D2 — Deviations from intended interventions | 16/26 (61.5%) | 16/26 (61.5%) |
| D3 — Missing outcome data | 10/26 (38.5%) | 16/26 (61.5%) |
| D4 — Measurement of the outcome | 20/26 (76.9%) | 25/26 (96.2%) |
| D5 — Selection of the reported result | 14/26 (53.8%) | 14/26 (53.8%) |

### Primary vs. secondary outcomes

Co-primary outcomes are grouped with primary outcomes. Each domain cell below reports exact / Low-vs-non-low agreement.

| Status | Cases | D1 | D2 | D3 | D4 | D5 | Pooled domains | Overall judgment |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary | 13 | 13/13 (100.0%) / 13/13 (100.0%) | 10/13 (76.9%) / 10/13 (76.9%) | 5/13 (38.5%) / 7/13 (53.8%) | 13/13 (100.0%) / 13/13 (100.0%) | 9/13 (69.2%) / 9/13 (69.2%) | 50/65 (76.9%) / 52/65 (80.0%) | 3/13 (23.1%) / 9/13 (69.2%) |
| Secondary | 13 | 12/13 (92.3%) / 12/13 (92.3%) | 6/13 (46.2%) / 6/13 (46.2%) | 5/13 (38.5%) / 9/13 (69.2%) | 7/13 (53.8%) / 12/13 (92.3%) | 5/13 (38.5%) / 5/13 (38.5%) | 35/65 (53.8%) / 44/65 (67.7%) | 1/13 (7.7%) / 12/13 (92.3%) |

### Outcome by primary/secondary status

| Outcome | Status | Cases | Domain exact | Domain Low vs. non-low | Overall exact | Overall Low vs. non-low |
|---|---|---:|---:|---:|---:|---:|
| Adverse Events | secondary | 7 | 17/35 (48.6%) | 22/35 (62.9%) | 0/7 (0.0%) | 6/7 (85.7%) |
| Overall Survival | primary | 9 | 36/45 (80.0%) | 37/45 (82.2%) | 2/9 (22.2%) | 5/9 (55.6%) |
| Overall Survival | secondary | 1 | 3/5 (60.0%) | 4/5 (80.0%) | 0/1 (0.0%) | 1/1 (100.0%) |
| Progression-Free Survival | primary | 4 | 14/20 (70.0%) | 15/20 (75.0%) | 1/4 (25.0%) | 4/4 (100.0%) |
| Progression-Free Survival | secondary | 5 | 15/25 (60.0%) | 18/25 (72.0%) | 1/5 (20.0%) | 5/5 (100.0%) |

## Scope-matched sensitivity

The main score above includes every case requested by the user when both a catalog label and a trial-specific definition were available, including source-adjudicated broader/related results and narrower reported populations. The repository scope-aware scorer yields a more conservative comparison:

| Scope cohort | Cases | Domain exact | Domain Low vs. non-low | Overall exact | Overall Low vs. non-low |
|---|---:|---:|---:|---:|---:|
| Scope-matched / equivalent | 14 | 51/70 (72.9%) | 56/70 (80.0%) | 1/14 (7.1%) | 11/14 (78.6%) |
| Adding approved broader or related proxies | 17 | 63/85 (74.1%) | 69/85 (81.2%) | 3/17 (17.6%) | 14/17 (82.4%) |

The 26 cases classify as 14 scope-matched/equivalent, 3 accepted broader or related proxies, and 9 narrower reported scopes. The strict cohort scores 14 cases; adding the accepted proxies scores 17. The nine narrower cases are excluded from that sensitivity, while they remain in the user-requested all-case score. See [scope-matched-score.json](scope-matched-score.json) for case-level exclusions and [scope-matched-score.md](scope-matched-score.md) for the repository scorer output.

## Trial definitions, primary/secondary status, and reported estimates

Definitions follow Supplement eTable 1. Effect estimates/results are taken from the main article abstract or Results; the source locator is shown for each row. Adverse-event rows use the counts or percentages reported by the article where no comparative effect measure was reported.

| Outcome | Trial | Trial role | Trial-specific definition | Main article estimate/result | Source locator |
|---|---|---|---|---|---|
| Overall Survival | ARASENS | Primary | The time from randomization to death resulting from any cause. | hazard ratio 0.68; 95% CI, 0.57 to 0.80; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | ARCHES | Secondary | The time from randomization to death resulting from any cause. | hazard ratio 0.81; 95% CI, 0.53 to 1.25; P=0.3361 | Main article, interim overall-survival Results/Table 2, PDF pp. 4-5. |
| Overall Survival | CHAARTED | Primary | The time from randomization to death resulting from any cause. | hazard ratio 0.61; 95% CI, 0.47 to 0.80; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | ENZAMET | Primary | The time from randomization to death resulting from any cause or to the date at which the patient was last known to be alive. | hazard ratio 0.67; 95% CI, 0.52 to 0.86; P=0.002 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | GETUG-AFU-15 | Primary | The time from randomization to death resulting from any cause. | hazard ratio 1.01; 95% CI, 0.75 to 1.36 | Main article abstract, Findings, PDF p. 1. |
| Overall Survival | LATITUDE | Co-primary | The time from randomization to death resulting from any cause. | hazard ratio 0.62; 95% CI, 0.51 to 0.76; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | PEACE-1 | Co-primary | The time between randomization and death from any cause; patients without events were censored at the date of last follow-up. | hazard ratio 0.82; 95.1% CI, 0.69 to 0.98; P=0.030 | Main article abstract, Findings, PDF p. 1. |
| Overall Survival | STAMPEDE | Primary | The time from randomization to death from any cause. | hazard ratio 0.63; 95% CI, 0.52 to 0.76; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | SWOG-1216 | Primary | The time from randomization to death resulting from any cause. | hazard ratio 0.86; 95% CI, 0.72 to 1.02; one-sided P=0.040 | Main article abstract, Results, PDF p. 1. |
| Overall Survival | TITAN | Co-primary | The time from randomization to death resulting from any cause. | hazard ratio 0.67; 95% CI, 0.51 to 0.89; P=0.005 | Main article abstract, Results, PDF p. 1. |
| Progression-Free Survival | ARCHES | Primary | The time from randomization to the appearance of first radiological evidence of progressive disease assessed by independent central review or death from any cause within 24 weeks of drug discontinuation; radiographic disease progression is defined as progressive disease by RECIST version 1.1. | hazard ratio 0.39; 95% CI, 0.30 to 0.50; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Progression-Free Survival | CHAARTED | Secondary | Clinical progression-free survival: time to the appearance of symptomatic bone metastases, progression according to RECIST version 1.0, or clinical deterioration due to cancer in the investigator’s opinion. | hazard ratio 0.61; 95% CI, 0.50 to 0.75; P<0.001 | Main article Results/Table 2, secondary end points, PDF pp. 4-5. |
| Progression-Free Survival | ENZAMET | Secondary | Clinical progression-free survival: time to the earliest sign of radiographic progression according to PCWG2 for bone lesions and RECIST version 1.1 for soft-tissue lesions; development of symptoms attributable to cancer progression; or initiation of another anticancer treatment for prostate cancer. | hazard ratio 0.40; 95% CI, 0.33 to 0.49; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Progression-Free Survival | GETUG-AFU-15 | Secondary | Clinical progression-free survival: progression of pre-existing lesions according to RECIST version 1.0 or occurrence of new bone lesions, whichever occurred first. | hazard ratio 0.75; 95% CI, 0.59 to 0.94; P=0.015 | Main article Results, clinical progression-free survival, Figure 3, PDF p. 4. |
| Progression-Free Survival | LATITUDE | Co-primary | Radiographic progression-free survival: time from randomization to the first radiological evidence of progressive disease or death; soft-tissue lesions were evaluated by CT or MRI using RECIST version 1.1, and new bone lesions by PCWG2. | hazard ratio 0.47; 95% CI, 0.39 to 0.55; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Progression-Free Survival | PEACE-1 | Co-primary | Radiographic progression-free survival: time from randomization to the appearance of first radiological evidence of progressive disease or death; progressively increasing soft-tissue lesions or new bone lesions according to PCWG2. | hazard ratio 0.54; 99.9% CI, 0.41 to 0.71; p<0.0001 | Main article abstract, Findings, PDF p. 1. |
| Progression-Free Survival | STAMPEDE | Secondary | Progression-free survival defined as failure-free survival excluding patients with biochemical (PSA progression) failure. | hazard ratio 0.40; 95% CI, 0.34 to 0.47; P<0.001 | Main article Results, Other Efficacy Outcome Measures, PDF p. 5. |
| Progression-Free Survival | SWOG-1216 | Secondary | Progression-free survival from the date of randomization to first occurrence of PSA or radiographic progression, symptomatic deterioration, or death due to any cause. | hazard ratio 0.58; 95% CI, 0.51 to 0.67; P<0.0001 | Main article abstract, Results, PDF p. 1. |
| Progression-Free Survival | TITAN | Co-primary | Radiographic progression-free survival: time from randomization to first imaging-based documentation of progressive disease or death, whichever occurred first. | hazard ratio 0.48; 95% CI, 0.39 to 0.60; P<0.001 | Main article abstract, Results, PDF p. 1. |
| Adverse Events | ARASENS | Secondary | Grade 3 or higher adverse events; adverse events were graded with NCI-CTCAE version 4.0.3. | 66.1% vs 63.5% had grade 3 or 4 adverse events. | Main article abstract, Results, PDF p. 1. |
| Adverse Events | ARCHES | Secondary | Grade 3 or higher adverse events; adverse events were graded with NCI-CTCAE version 4.0.3. | 24.3% vs 25.6% had grade 3 or higher adverse events. | Main article abstract, Results, PDF p. 1. |
| Adverse Events | ENZAMET | Secondary | Grade 3 adverse events; NCI-CTCAE version 4.0.2 was used to grade adverse events. | Grade 3: 277/563 (49%) vs 194/558 (35%). | Main article Table 2, Any Adverse Event severity, Grade 3 row, PDF p. 9. |
| Adverse Events | LATITUDE | Secondary | Grade 3 or higher adverse events; adverse events were graded with NCI-CTCAE version 4.0. | 63% vs 48% had grade 3 or 4 adverse events. | Main article Results, Safety, PDF p. 5. |
| Adverse Events | PEACE-1 | Secondary | Grade 3 or higher adverse events; NCI-CTCAE version 4.0 was used to grade adverse events. | In the docetaxel population, 217/347 (63%) with abiraterone vs 181/350 (52%) without abiraterone had grade 3 or worse adverse events. | Main article abstract, Findings, docetaxel population of interest, PDF p. 1. |
| Adverse Events | STAMPEDE | Secondary | Grade 3 or higher adverse events; NCI-CTCAE initially version 3.0 and later version 4.0 was used. | 443/948 (47%) vs 315/960 (33%) had grade 3 or higher adverse events. | Main article abstract and Results, Adverse Events, PDF pp. 1 and 6. |
| Adverse Events | TITAN | Secondary | Grade 3 or higher adverse events; adverse events were graded with NCI-CTCAE version 4.0.3. | 42.2% vs 40.8% had grade 3 or 4 adverse events. | Main article abstract, Results, PDF p. 1. |

## Cohort and exclusions

The scored cohort contains **10 Overall Survival**, **9 Progression-Free Survival**, and **7 Adverse Events** cases (26 total). Primary status comprises 7 primary and 6 co-primary outcomes (13 grouped as primary); the remaining 13 are secondary.

Skipped combinations:

- Progression-Free Survival / ARASENS: no catalog label for the concept.
- Adverse Events / CHAARTED and GETUG-AFU-15: no catalog label for the concept.
- Adverse Events / SWOG-1216: a catalog label exists, but the supplied eTable 1 does not define an adverse-event outcome for that trial.

## ENZAMET Grade 3 handling

Per the user’s direction, ENZAMET is scored using **Grade 3 alone**: 277/563 (49%) vs. 194/558 (35%), from the Grade 3 row of main article Table 2, PDF p. 9. No Grade 3–5 total was constructed. The proposal selected this Grade 3 row. It targets all randomized participants while the article reports the counts for the safety population (participants who received at least one dose); this narrower scope was approved for the requested all-case score and is excluded from the scope-matched sensitivity. Only `adverse-events/ENZAMET-grade3-assessment` is scored. Earlier Grade 3-or-higher and experimental combined-grade runs remain in the raw archive for audit but are excluded. Two launcher-only index-binding attempts also remain there; both failed before Codex started and were not scored.

## Run and verification details

- Model: `gpt-6-luna` with `medium` reasoning, launched through Codex CLI `0.157.1`.
- rob2-kit source commit: `d5528044066bc0300bd96ea4e99c25a35d58f6b0`.
- The model received the minimal `/rob2-assess` outcome/definition/estimate/trial prompt and was not told primary/secondary status.
- Proposals were reviewed and approved before assessments; all 26 assessment turns exited successfully.
- All 26 finalized bundles passed independent bundle verification and artifact hash/identity checks. Per-case expected and observed labels are in [case-scores.tsv](case-scores.tsv); machine-readable metrics are in [all-case-accuracy.json](all-case-accuracy.json).
- JSONL traces and finalized bundles are preserved under `isolated-worktree-run/rob2-trial-benchmark/`.
- The work ran in a managed Git worktree with per-case workspaces. The Windows host used Codex `workspace-write` with `windows.sandbox=unelevated` and the campaign was marked non-strict exploratory; this was workspace isolation, not a strict OS-level sandbox. The catalog label CSVs were absent from the assessment worktree.

## Interpretation and source files

Accuracy is agreement with the frozen provisional catalog labels, not an independently adjudicated estimate of scientific truth. No High labels occur in this cohort; binary scoring therefore treats Some Concerns and High as non-low, as requested.

Definitions came from [the supplied supplement PDF](C:/Users/Ali-Salman/Downloads/coi220099supp1_prod_1684353132.64521.pdf); main articles are in `C:/Users/Ali-Salman/Documents/Code/rob2-kit/eval/reference/sources/<TRIAL>/main_article.pdf`. The frozen labels are in `C:/Users/Ali-Salman/Documents/Code/rob2-kit/eval/reference/catalog/provisional-labels/`.

Supporting artifacts:

- [All-case metrics](all-case-accuracy.json)
- [Per-case labels and bundle identities](case-scores.tsv)
- [Trial definitions and estimates](prepared/final-case-metadata.v3.tsv)
- [Scoring manifest](prepared/trial-benchmark-manifest.v3.json)
- [Scope-aware sensitivity JSON](scope-matched-score.json)
- [Scope-aware sensitivity Markdown](scope-matched-score.md)
- [Scope and proposal review records](prepared/)

