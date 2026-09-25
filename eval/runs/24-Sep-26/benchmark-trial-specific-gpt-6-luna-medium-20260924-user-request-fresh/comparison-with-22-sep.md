# Comparison with 22 September 2026 benchmark

## Summary

The headline exact scores are lower in the fresh run, but this is not a controlled before/after test. The model version, rob2-kit commit, prompts/result scopes, scored case set, and Codex CLI version all changed. The reference labels for the 24 shared scored cases did not change.

| Scoring set | Cases | Domain exact | Domain Low vs Non-Low | Overall exact | Overall Low vs Non-Low |
|---|---:|---:|---:|---:|---:|
| 22 Sep run | 24 | 77/120 (64.2%) | 87/120 (72.5%) | 4/24 (16.7%) | 18/24 (75.0%) |
| Fresh run, all scored cases | 28 | 87/140 (62.1%) | 98/140 (70.0%) | 4/28 (14.3%) | 22/28 (78.6%) |
| Fresh run, same 24 cases as 22 Sep | 24 | 74/120 (61.7%) | 84/120 (70.0%) | 4/24 (16.7%) | 19/24 (79.2%) |

On the matched 24 cases, exact final-label accuracy tied at 4/24. Binary final-label accuracy rose by 1 case. Exact domain accuracy fell by 3 of 120 judgments (2.5 percentage points). Across those same cases, 38/120 individual domain predictions changed. Correct final labels transitioned to incorrect in three cases and incorrect to correct in three; three additional cases changed category but stayed incorrect.

The matched outcome results localize the domain drop: Overall Survival rose from 30/40 to 32/40 exact domain judgments, and Progression-Free Survival rose from 24/40 to 25/40. Adverse Events fell from 23/40 to 17/40. AE overall exact labels fell from 2/8 to 0/8, while binary agreement rose from 6/8 to 7/8. In the domain-level matched comparison, D2 exact was 16/24 to 13/24 and D3 was 10/24 to 7/24; D1 and D5 improved.

The four cases present in the fresh scored set but not in the old scored set were Overall Survival—ARCHES, Overall Survival—STAMPEDE, Progression-Free Survival—ARASENS, and Progression-Free Survival—GETUG-AFU-15. The old STAMPEDE OS case was excluded as resumable; all four have incorrect exact overall labels in the fresh run (three of four agree under Low vs Non-Low). Adding those four therefore accounts for the 2.4-point fall in full-set exact overall accuracy, from 16.7% to 14.3%. They do not explain the matched domain-accuracy drop: they contributed 13/20 exact domain matches, slightly above the fresh matched rate.

## Run changes

| Dimension | 22 Sep | Fresh run |
|---|---|---|
| Model | `gpt-5.6-luna`, medium | `gpt-6-luna`, medium |
| Codex CLI | 0.155.1 | 0.156.1 |
| rob2-kit commit | `c340438fe650b448582fa9151e998f99b6a65d7e` | `f1f8a32ce68be6260cb1a5683e65f72c7af2059d` |
| Scored cases | 24 (25 manifest rows; STAMPEDE OS excluded) | 28 (30 manifest rows; 2 AE cases without labels excluded) |
| Prompt policy | One minimal trial-specific prompt | User's minimal `/rob2-assess` template |

The 24 prompts were all textually different. Some changes were formatting or added abstract statistics, but several changed the outcome actually specified. For example, the old ENZAMET AE prompt assessed serious AE rates (235/563 vs 189/558); the fresh prompt assessed treatment-discontinuation counts (33 vs 14). Old ARASENS and TITAN AE prompts assessed any AE; fresh prompts assessed grade 3/4 AEs. Old ENZAMET PFS used PSA-PFS (HR 0.39); fresh used clinical PFS (HR 0.40). The fresh CHAARTED and STAMPEDE PFS prompts also omitted the body/table HRs that the old prompts supplied, saying the exact estimates were not in the abstract. These are materially different inputs for RoB 2, even though each case keeps the same broad catalog label.

The code and assessment guidance changed too. The kit moved from `c340438` to `f1f8a32`; notable commits include “Harden agent contracts and benchmark evaluation,” “Implement scientific-faithful RoB 2 workflow,” “Harden assessment and benchmark workflows,” and “Complete trial-specific RoB2 benchmark and harden recovery.” The fresh assessment context added neutral paired-premise examples in D2–D5 and further evidence-to-answer checks. The earlier guidance already distinguished possible from likely missingness or measurement influence, so that distinction itself is not new. These changes could affect judgments, but the model, code, and prompt changes were not isolated from one another.

Both score reports use the same three-level exact comparison and the same Low-versus-Non-Low mapping. Both runs used workspace-write rather than strict host isolation, so that does not explain the difference.

## Interpretation

The fresh run shows a small decline in domain-label agreement on the matched cases, concentrated in AE and D2/D3 judgments, alongside improved binary final-label agreement. The larger-looking drop in exact final-label accuracy is caused by adding four newly scored cases, all of which missed the three-level label. Because the model, kit, and outcome prompts also changed, these runs cannot establish that the rob2-kit code alone regressed. A controlled attribution would freeze the 24 prompts and case set and vary model and kit version separately.
