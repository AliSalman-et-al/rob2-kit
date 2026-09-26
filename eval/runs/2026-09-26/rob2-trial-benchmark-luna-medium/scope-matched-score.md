# Trial-specific rob2-kit benchmark

This report measures agreement with the frozen provisional catalog labels. It is not an adjudicated estimate of scientific accuracy.

- Model: `gpt-6-luna` with `medium` reasoning.
- Manifest rows: 26 abstract-eligible outcome/trial cases.
- Finalized scored cases: 14 (70 domain cells).
- Cases excluded from scoring: 9.
- Result-scope cases: exact 14; approved proxy 3; unavailable 0; mismatch 9.
- Exact scoring compares Low, Some Concerns, and High. Binary scoring maps Some Concerns and High to Non-Low.
- The frozen catalog contains no reference High labels, so High sensitivity is not estimable from this cohort.

## Pooled result

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (70 cells) | 51/70 (72.9%) | 56/70 (80.0%) |
| Overall final label (14 cases) | 1/14 (7.1%) | 11/14 (78.6%) |

## Scope-difference sensitivity

The primary results include exact scope matches and source-adjudicated `equivalent` cases. This sensitivity aggregate adds cases adjudicated `accepted_with_scope_difference` (broader or related).
- Added scope-difference cases: 3.

| Measure | Exact | Low vs Non-Low |
|---|---:|---:|
| Five domains (85 cells) | 63/85 (74.1%) | 69/85 (81.2%) |
| Overall final label (17 cases) | 3/17 (17.6%) | 14/17 (82.4%) |

## Accuracy by outcome

| Outcome | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 8 | 30/40 (75.0%) | 32/40 (80.0%) | 1/8 (12.5%) | 5/8 (62.5%) |
| Progression-Free Survival | 5 | 17/25 (68.0%) | 19/25 (76.0%) | 0/5 (0.0%) | 5/5 (100.0%) |
| Adverse Events | 1 | 4/5 (80.0%) | 5/5 (100.0%) | 0/1 (0.0%) | 1/1 (100.0%) |

## Accuracy by domain

| Domain | Exact | Low vs Non-Low |
|---|---:|---:|
| D1 | 14/14 (100.0%) | 14/14 (100.0%) |
| D2 | 9/14 (64.3%) | 9/14 (64.3%) |
| D3 | 6/14 (42.9%) | 10/14 (71.4%) |
| D4 | 13/14 (92.9%) | 14/14 (100.0%) |
| D5 | 9/14 (64.3%) | 9/14 (64.3%) |

## Accuracy by outcome and domain

Exact agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 8/8 (100.0%) | 5/8 (62.5%) | 4/8 (50.0%) | 8/8 (100.0%) | 5/8 (62.5%) |
| Progression-Free Survival | 5/5 (100.0%) | 3/5 (60.0%) | 2/5 (40.0%) | 4/5 (80.0%) | 3/5 (60.0%) |
| Adverse Events | 1/1 (100.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 1/1 (100.0%) | 1/1 (100.0%) |

Low vs Non-Low agreement:

| Outcome | D1 | D2 | D3 | D4 | D5 |
|---|---:|---:|---:|---:|---:|
| Overall Survival | 8/8 (100.0%) | 5/8 (62.5%) | 6/8 (75.0%) | 8/8 (100.0%) | 5/8 (62.5%) |
| Progression-Free Survival | 5/5 (100.0%) | 3/5 (60.0%) | 3/5 (60.0%) | 5/5 (100.0%) | 3/5 (60.0%) |
| Adverse Events | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |

## Accuracy by primary or secondary outcome

Co-primary and other explicitly primary endpoints are in the Primary row.

| Outcome role | Cases | Domains exact | Domains Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| Primary | 9 | 34/45 (75.6%) | 35/45 (77.8%) | 1/9 (11.1%) | 6/9 (66.7%) |
| Secondary | 5 | 17/25 (68.0%) | 21/25 (84.0%) | 0/5 (0.0%) | 5/5 (100.0%) |

## Excluded cases

| Outcome | Trial | Reason |
|---|---|---|
| Overall Survival | ARASENS | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, precision, reported_scope |
| Overall Survival | SWOG-1216 | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, precision, reported_scope |
| Progression-Free Survival | SWOG-1216 | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, precision, reported_scope |
| Adverse Events | ARASENS | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |
| Adverse Events | ARCHES | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |
| Adverse Events | ENZAMET | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |
| Adverse Events | PEACE-1 | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |
| Adverse Events | STAMPEDE | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |
| Adverse Events | TITAN | result scope mismatch: comparison, endpoint_definition, population, window_or_cutoff, reported_scope |

The complete case-level expected and observed labels are in the adjacent `score.json` file. The benchmark manifest records each trial-specific definition, abstract effect estimate, role, prompt, and run directory.
