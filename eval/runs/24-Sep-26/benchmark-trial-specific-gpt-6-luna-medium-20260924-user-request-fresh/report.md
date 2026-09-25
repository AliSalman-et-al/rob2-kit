# Trial-specific rob2-kit benchmark

This report measures agreement with the frozen provisional catalog labels. It is not an adjudicated estimate of scientific accuracy.

- Model: `gpt-6-luna` with `medium` reasoning.
- Manifest rows: 30 abstract-eligible outcome/trial cases.
- Finalized scored cases: 28 (140 domain cells).
- Cases excluded from scoring: 2.
- Exact scoring compares Low, Some Concerns, and High. Binary scoring maps Some Concerns and High to Non-Low.
- The frozen catalog contains no reference High labels, so High sensitivity is not estimable from this cohort.

## Pooled result

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (140 cells) | 87/140 (62.1%) | 98/140 (70.0%) |
| Overall final label (28 cases) | 4/28 (14.3%) | 22/28 (78.6%) |

## Scope-difference sensitivity

The primary results include exact scope matches and source-adjudicated `equivalent` cases. This sensitivity aggregate adds cases adjudicated `accepted_with_scope_difference` (broader or related).
- Added scope-difference cases: 0.

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (140 cells) | 87/140 (62.1%) | 98/140 (70.0%) |
| Overall final label (28 cases) | 4/28 (14.3%) | 22/28 (78.6%) |

## Accuracy by outcome

| Outcome | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10 | 37/50 (74.0%) | 38/50 (76.0%) | 3/10 (30.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 10 | 33/50 (66.0%) | 38/50 (76.0%) | 1/10 (10.0%) | 9/10 (90.0%) |
| Adverse Events | 8 | 17/40 (42.5%) | 22/40 (55.0%) | 0/8 (0.0%) | 7/8 (87.5%) |

## Accuracy by domain

D1 = bias arising from randomization; D2 = deviations from intended interventions; D3 = missing outcome data; D4 = measurement of the outcome; D5 = selection of the reported result.

| Domain | Exact | Low vs Non-Low |
|---|---:|---:|
| D1 | 26/28 (92.9%) | 26/28 (92.9%) |
| D2 | 15/28 (53.6%) | 15/28 (53.6%) |
| D3 | 8/28 (28.6%) | 12/28 (42.9%) |
| D4 | 18/28 (64.3%) | 25/28 (89.3%) |
| D5 | 20/28 (71.4%) | 20/28 (71.4%) |

## Accuracy by outcome and domain

Exact agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 6/10 (60.0%) | 4/10 (40.0%) | 9/10 (90.0%) | 8/10 (80.0%) |
| Progression-Free Survival | 10/10 (100.0%) | 7/10 (70.0%) | 3/10 (30.0%) | 6/10 (60.0%) | 7/10 (70.0%) |
| Adverse Events | 6/8 (75.0%) | 2/8 (25.0%) | 1/8 (12.5%) | 3/8 (37.5%) | 5/8 (62.5%) |

Low vs Non-Low agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 6/10 (60.0%) | 5/10 (50.0%) | 9/10 (90.0%) | 8/10 (80.0%) |
| Progression-Free Survival | 10/10 (100.0%) | 7/10 (70.0%) | 5/10 (50.0%) | 9/10 (90.0%) | 7/10 (70.0%) |
| Adverse Events | 6/8 (75.0%) | 2/8 (25.0%) | 2/8 (25.0%) | 7/8 (87.5%) | 5/8 (62.5%) |

## Accuracy by primary or secondary outcome

Co-primary and other explicitly primary endpoints are in the Primary row.

| Outcome role | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Primary | 13 | 47/65 (72.3%) | 49/65 (75.4%) | 4/13 (30.8%) | 9/13 (69.2%) |
| Secondary | 15 | 40/75 (53.3%) | 49/75 (65.3%) | 0/15 (0.0%) | 13/15 (86.7%) |

## Excluded cases

| Outcome | Trial | Reason |
|---|---|---|
| Adverse Events | CHAARTED | reference label unavailable |
| Adverse Events | GETUG-AFU-15 | reference label unavailable |

The complete case-level expected and observed labels are in the adjacent `score.json` file. The benchmark manifest records each trial-specific definition, abstract effect estimate, role, prompt, and run directory.
