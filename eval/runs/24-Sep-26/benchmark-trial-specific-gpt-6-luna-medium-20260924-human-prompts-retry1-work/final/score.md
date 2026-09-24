# Trial-specific rob2-kit benchmark

This report measures agreement with the frozen provisional catalog labels. It is not an adjudicated estimate of scientific accuracy.

- Model: `gpt-6-luna` with `medium` reasoning.
- Manifest rows: 30 abstract-eligible outcome/trial cases.
- Finalized scored cases: 26 (130 domain cells).
- Cases excluded from scoring: 2.
- Exact scoring compares Low, Some Concerns, and High. Binary scoring maps Some Concerns and High to Non-Low.
- The frozen catalog contains no reference High labels, so High sensitivity is not estimable from this cohort.

## Pooled result

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (130 cells) | 84/130 (64.6%) | 95/130 (73.1%) |
| Overall final label (26 cases) | 3/26 (11.5%) | 21/26 (80.8%) |

## Scope-difference sensitivity

The primary results include exact scope matches and source-adjudicated `equivalent` cases. This sensitivity aggregate adds cases adjudicated `accepted_with_scope_difference` (broader or related).
- Added scope-difference cases: 2.

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (140 cells) | 87/140 (62.1%) | 99/140 (70.7%) |
| Overall final label (28 cases) | 3/28 (10.7%) | 23/28 (82.1%) |

## Accuracy by outcome

| Outcome | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10 | 37/50 (74.0%) | 40/50 (80.0%) | 2/10 (20.0%) | 7/10 (70.0%) |
| Progression-Free Survival | 9 | 30/45 (66.7%) | 34/45 (75.6%) | 1/9 (11.1%) | 8/9 (88.9%) |
| Adverse Events | 7 | 17/35 (48.6%) | 21/35 (60.0%) | 0/7 (0.0%) | 6/7 (85.7%) |

## Accuracy by domain

| Domain | Exact | Low vs Non-Low |
|---|---:|---:|
| D1 | 26/26 (100.0%) | 26/26 (100.0%) |
| D2 | 16/26 (61.5%) | 16/26 (61.5%) |
| D3 | 9/26 (34.6%) | 15/26 (57.7%) |
| D4 | 20/26 (76.9%) | 25/26 (96.2%) |
| D5 | 13/26 (50.0%) | 13/26 (50.0%) |

## Accuracy by outcome and domain

Exact agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 7/10 (70.0%) | 4/10 (40.0%) | 10/10 (100.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 9/9 (100.0%) | 7/9 (77.8%) | 3/9 (33.3%) | 6/9 (66.7%) | 5/9 (55.6%) |
| Adverse Events | 7/7 (100.0%) | 2/7 (28.6%) | 2/7 (28.6%) | 4/7 (57.1%) | 2/7 (28.6%) |

Low vs Non-Low agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 10/10 (100.0%) | 7/10 (70.0%) | 7/10 (70.0%) | 10/10 (100.0%) | 6/10 (60.0%) |
| Progression-Free Survival | 9/9 (100.0%) | 7/9 (77.8%) | 5/9 (55.6%) | 8/9 (88.9%) | 5/9 (55.6%) |
| Adverse Events | 7/7 (100.0%) | 2/7 (28.6%) | 3/7 (42.9%) | 7/7 (100.0%) | 2/7 (28.6%) |

## Accuracy by primary or secondary outcome

Co-primary and other explicitly primary endpoints are in the Primary row.

| Outcome role | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Primary | 12 | 43/60 (71.7%) | 46/60 (76.7%) | 2/12 (16.7%) | 9/12 (75.0%) |
| Secondary | 14 | 41/70 (58.6%) | 49/70 (70.0%) | 1/14 (7.1%) | 12/14 (85.7%) |

## Excluded cases

| Outcome | Trial | Reason |
|---|---|---|
| Adverse Events | CHAARTED | reference label unavailable |
| Adverse Events | GETUG-AFU-15 | reference label unavailable |

The complete case-level expected and observed labels are in the adjacent `score.json` file. The benchmark manifest records each trial-specific definition, abstract effect estimate, role, prompt, and run directory.
