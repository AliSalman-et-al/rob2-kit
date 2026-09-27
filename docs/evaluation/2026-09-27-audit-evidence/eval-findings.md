# Benchmark trace audit: September 26–27, 2026

## What was scored

The official September 26 all-case report scores 26 trial/outcome rows and 130 domain labels, including results whose scope was later classified as mismatched. It records 85/130 exact domain labels (65.4%), 96/130 Low-vs-Non-Low, and 4/26 exact overall labels (15.4%); overall Low-vs-Non-Low is 21/26 (80.8%). Its exact-scope sensitivity is much smaller: 14 exact scope cases plus 3 approved proxies, with 9 excluded mismatches.

The September 27 official run completed all 26 cases: 24 exact result scopes and two source-adjudicated scope differences. Across all 26 it achieved 78/130 exact domains (60.0%), 88/130 Low-vs-Non-Low (67.7%), and 3/26 exact overall labels (11.5%); overall Low-vs-Non-Low remains 21/26 (80.8%). On exact scopes only (24 cases), it is 70/120 domains exact (58.3%), 80/120 Low-vs-Non-Low (66.7%), 3/24 overall exact, and 21/24 overall Low-vs-Non-Low.

The catalog has 104 Low and 26 Some Concerns domain labels, with no reference High label; High sensitivity cannot be measured. Latest exact misses are 52/130 domains and 23/26 overall labels. The overall label is downstream of the domain judgments, so those 23 cases are not 23 independent reasoning failures. The model produces 20 High overall labels; the reference has none. Latest exact domain agreement by outcome is OS 38/50 (76.0%), PFS 26/45 (57.8%), and adverse events 14/35 (40.0%); adverse-events binary agreement is 17/35 (48.6%).

Comparing by trial and outcome gives the same 26 cases and unchanged catalog labels, but it does **not** establish that the selected result is identical between runs. Paired exact domain counts were D1 25→25, D2 16→15, D3 10→11, D4 20→15, D5 14→12, and overall 4→3. The cross-run label-agreement decline is concentrated in D4 and D5. The run also changed source/result selection and scope handling, so this is descriptive, not a causal estimate of a code regression.

## Complete latest disagreements

Each cell shows reference label → model label. “Accepted scope difference” is the recorded scope decision, not scientific endorsement of every domain label. The adjacent CSV provides all 156 paired cells (all cases × five domains plus overall), with separate mismatch and agreement subsets.

| Outcome | Trial | Scope | Label differences |
|---|---|---|---|
| Overall Survival | ARASENS | equivalent | D2 low→some_concerns; Overall low→some_concerns |
| Overall Survival | ARCHES | equivalent | D3 some_concerns→high; D4 low→some_concerns; Overall some_concerns→high |
| Overall Survival | CHAARTED | equivalent | D2 low→high; Overall low→high |
| Overall Survival | ENZAMET | equivalent | All labels agree |
| Overall Survival | GETUG-AFU-15 | equivalent | D2 low→some_concerns; Overall some_concerns→high |
| Overall Survival | LATITUDE | equivalent | D3 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Overall Survival | PEACE-1 | equivalent | All labels agree |
| Overall Survival | STAMPEDE | equivalent | D2 low→some_concerns; D3 some_concerns→low; D4 low→some_concerns; Overall some_concerns→high |
| Overall Survival | SWOG-1216 | equivalent | All labels agree |
| Overall Survival | TITAN | equivalent | D3 low→high; D5 some_concerns→low; Overall some_concerns→high |
| Progression-Free Survival | CHAARTED | equivalent | D2 low→some_concerns; D4 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | ENZAMET | equivalent | D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | GETUG-AFU-15 | equivalent | D2 low→some_concerns; D4 some_concerns→high; Overall some_concerns→high |
| Progression-Free Survival | LATITUDE | equivalent | D3 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | PEACE-1 | equivalent | D1 low→some_concerns; D3 low→high; D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | STAMPEDE | equivalent | D3 some_concerns→high; D4 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | SWOG-1216 | equivalent | D3 low→high; D5 low→some_concerns; Overall some_concerns→high |
| Progression-Free Survival | TITAN | equivalent | D3 low→high; D5 some_concerns→low; Overall some_concerns→high |
| Adverse Events | ARASENS | equivalent | D2 low→some_concerns; D4 low→high; D5 low→some_concerns; Overall low→high |
| Adverse Events | ARCHES | equivalent | D2 low→some_concerns; D3 some_concerns→low; D4 low→some_concerns; D5 low→some_concerns; Overall some_concerns→high |
| Adverse Events | ENZAMET | equivalent | D2 low→some_concerns; D3 low→high; D4 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Adverse Events | PEACE-1 | equivalent | D4 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Adverse Events | STAMPEDE | equivalent | D2 low→some_concerns; D3 some_concerns→low; D4 some_concerns→high; D5 low→some_concerns; Overall some_concerns→high |
| Adverse Events | TITAN | equivalent | D2 low→some_concerns; D3 low→high; D4 low→high; Overall some_concerns→high |
| Progression-Free Survival | ARCHES | accepted_with_scope_difference | D3 some_concerns→low; Overall some_concerns→low |
| Adverse Events | LATITUDE | accepted_with_scope_difference | D3 some_concerns→low; Overall some_concerns→low |

## What the traces show

All 123 JSONL files were parsed line-by-line; there are no malformed lines and no byte-identical duplicate logs. September 26 has 59 phase-log segments (one benchmark root); September 27 has 64 segments (57 in the official benchmark and 7 in the separate `issue-465-e2e` tree). Across both dates the logs contain 6,461 completed items, 5,716 started items, 123 thread starts, and three timeout/reconnect errors. The three are in OS/ARCHES, PFS/CHAARTED, and PFS/TITAN. The official benchmark retained follow-on phase logs for OS/ARCHES and PFS/TITAN.

The latest official benchmark's 57 trace segments contain 2,345 completed MCP calls: 625 `get_domain_context`, 428 `read_pages`, 222 `select_text_evidence`, 184 single `search_sources`, 168 `search_sources_batch`, 60 `render_page`, 24 `select_visual_evidence`, 153 raw `save_domain_judgment`, 28 raw `save_proposal`, and 27 `review_trial` calls. The calls returned 40.2 MB of serialized result payloads (median 8.4 KB, 95th percentile 33.1 KB, maximum 837.7 KB for a rendered ARCHES adverse-events page). These are tool-response bytes, not a measurement of model context tokens; image responses may inflate them.

Of 184 single source-search calls, 182 have observable match counts and 59 returned zero matches; two have no observable count and are not no-hits. The maximum observed count was 212 and 50 responses were truncated. These are candidates for query/retrieval analysis, not proof of a defect or a need for a new tool. Agents also used batch search, direct page reads, and visual tools. The full log metrics JSON records all tools and no-hit examples.

Raw save calls are not accepted checkpoint counts. In the 26 final output bundles there are 131 domain-history records: 26 per domain except D3 with 27. Only one selected bundle has a repeated history (ARASENS adverse-events D3, Low→Low); no final label repair is evident. All 26 outputs were closed and finalized. The traces show use of the full source/search/read/render/evidence loop, so the main failure pattern is not absence of agentic calls alone; it is whether the evidence was interpreted and mapped to RoB 2 signaling questions appropriately.

## Provisional error versus defensible-deviation triage

The labels are provisional human catalog references, not gold-standard scientific truth. Every mismatch above remains an adjudication candidate unless source evidence establishes a better reading. The available independent source audit supports these nuanced examples:

- **TITAN adverse-events D4 (model High, catalog Low): candidate inference weakness, not an established label error.** Q4.2 is Probably yes. The protocol specifies CTCAE v4.03, monthly follow-up, and AE collection through 30 days after the last dose. The model infers differential measurement opportunities from median exposure duration (20.5 vs 18.3 months). Whether this is a bias-relevant observation difference requires the exact safety-estimand adjudication; shared grading alone does not settle ascertainment comparability.
- **ARCHES overall-survival D4 (model Some Concerns, catalog Low): unresolved and likely scientifically defensible under current workflow rules.** The assessment says all-cause death is objective and that assessor knowledge probably cannot influence whether death is recorded, yet the separate detection-comparability and assessor-awareness questions are No information. The current rule maps that uncertainty to Some Concerns. Since complete and comparable death ascertainment is a distinct issue from subjective outcome measurement, the recorded answer set does not establish a model branch-mapping error; the Low catalog label may simply reflect a more favorable judgment.
- **STAMPEDE PFS D5 (model Some Concerns, catalog Low) and STAMPEDE AE D5 (model Some Concerns, catalog Low): unresolved, potentially defensible.** The SAP predates the report and says analyses were prespecified, but the report/SAP timelines leave some ambiguity about unblinded access and the AE observation window differs. Neither the model's concern nor the human Low can yet be called clearly wrong.
- **PEACE-1 PFS D5 (model Some Concerns, catalog Low): potentially defensible.** Protocol/SAP amendments changed endpoint and analysis details; the deviation can be material to selecting among reported analyses.

Do not translate all Low→Some Concerns into scientific errors: several may be defensible conservative judgments. The source audit does not yet show an exact signaling-answer contradiction that would prove an independent model reasoning defect; the strongest candidate is the TITAN adverse-events D4 call, where the only stated differential-measurement premise appears to be longer median exposure despite the same protocol-defined assessment method. Higher reasoning effort or a stronger model could improve nuanced synthesis, but the no-hit and broad-search patterns call for query/tool improvements regardless of model.

## Reproduction artifacts

- `audit_run_logs.py` parses every JSONL under both date roots, records per-tool counts/result bytes, duplicate-log hashes, final bundle history counts, and paired score comparisons.
- `log-and-paired-scores.json` is the machine-readable inventory and summary.
- `case-cell-comparison.csv` has all 156 paired labels; `case-cell-mismatches.csv` and `case-cell-agreements.csv` split the latest rows by correctness.
- The latest casewise score and scope adjudications remain in `eval/runs/2026-09-27/rob2-trial-benchmark-latest-8ae8016/accuracy.json` and `scope-adjudications.json`.

This is not a full page-by-page adjudication of all trial PDFs. Source adjudication here is limited to the cases called out above; other differences need case-level scientific review before making claims about true accuracy or the 80% target.
