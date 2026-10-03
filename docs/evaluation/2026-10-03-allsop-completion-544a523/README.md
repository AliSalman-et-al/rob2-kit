# One Allsop completion mechanism check at 544a523

One authorized invocation used exact `gpt-6-luna` Medium against frozen clean production code `544a523aa3b0ccec7459a5be32e3c87f5a95fb1a`. Direct rob2 MCP tools were enabled; shell, web, apps, and other tools were disabled. Sources, approved target, and reported result were identical to the previous Allsop checks, restored from the required Code benchmark repository with verified hashes. No previous Domain answers, reference labels, answer/page hints, operator repairs, retries, or mid-run edits were supplied.

The model completed D1–D5, inspected and revised D3 through the native workflow, reviewed the current checkpoint set, closed against the exact current review, and finalized. This is a positive known-case completion observation following the continuation change, not causal proof, unseen validation, or evidence of general accuracy improvement. The earlier run stopped after opening D2; model sampling and diagnostic input policy also differ.

## Runtime and input policy

The diagnostic-only guard model explicitly accepts `null` for total and uncached input limits. Manifest and launcher require both to be null, and the monitor skips those two checks while recording total, cached, and uncached usage. The archived offline test result confirms large input counts do not trigger a stop, while remaining guards fire. Production code and production transport/source limits were unchanged.

The retained reactive guards were 20 minutes wall, 3 minutes idle, 60 tools, 15,000 output tokens, four save attempts per Domain, and two consecutive identical errors. These are observed reactive checks, not guaranteed hard billing limits.

Actual run: 274.79 seconds; 44 completed MCP calls; seven save calls (D3 used three, including one rejected stale-context revision); 4,974,118 input tokens, comprising 4,738,816 cached and 235,302 uncached; 8,813 output tokens, including 1,376 reported reasoning tokens. No guard fired and all retained-limit overshoots were zero. Uncached input passed the previous 200,000 threshold without stopping. No second invocation occurred.

## Scientific branches and qualifications

| Domain | Final judgment | Accepted active answers |
|---|---|---|
| D1 | Some concerns | 1.1 Yes; 1.2 NI; 1.3 No |
| D2 | Low | 2.1 No; 2.2 No; 2.6 Yes |
| D3 | Some concerns | 3.1 Probably no; 3.2 No; 3.3 Yes; 3.4 Probably no |
| D4 | Low | 4.1 Probably no; 4.2 Probably no; 4.3 No |
| D5 | Some concerns | 5.1 NI; 5.2 NI; 5.3 Probably no |

D2 treats the reported intention-to-treat analysis and inclusion of all 51 randomized participants as evidence of assignment-preserving analysis; it does not use that inclusion to declare outcome completeness. Personnel masking is answered No despite an explicit unknown about whether all caregivers were covered by the reported investigator blinding: that certainty warrants further scientific scrutiny.

D3 preserves actual questionnaire missingness despite all randomized participants being analyzed. On review, the model changed 3.4 from NI to Probably no using the reported predominant dissatisfaction with the inpatient environment, lack of significant dropout predictors, and Little's MCAR test. The first revision was rejected because the saved Domain changed the context basis; the model fetched a fresh ordered context and resubmitted successfully. No operator supplied this revision. Those counterpoints support a reasoned disagreement with stronger missingness concern, but a nonsignificant MCAR test does not prove independence. Missing-data percentages through days 7/9 do not quantify the exact days 1–6 target; arm-specific observed counts remain unknown.

D5 distinguishes unavailable plan timing from evidence of result-driven selection. It retains NI for 5.1/5.2 and Probably no for 5.3, referring to disclosed adjusted/unadjusted models and day-wise analyses while preserving the unknown about unreported eligible analyses. This remains a qualified, evidence-grounded disagreement with the provisional Low label; absence of a captured SAP does not prove an absence of prespecification or selective reporting.

The approved six-day medication window and reported days 1–9 mixed-model result remain mismatched in scope. The model preserved that limitation; completion did not resolve or authorize changing the target. Provisional human labels remain withheld during inference and are not treated as fully aligned adjudication. Overall High follows local ADR0035's multiple-Some-concerns rule; it is separate from Cochrane's qualified confidence interpretation and the provisional overall Some concerns label. No agreement or All-Low superiority statistic is reported.

All 11 main-report pages and all six supplement pages were returned in full, verified by merging assessment-phase line receipts against current source-hash/projection-verified text. No primary source text was embedded in context pages. Delivery establishes access, not comprehension. The production source-reading helper scopes to the current phase and returns an empty map after finalization; `coverage.json` therefore retains both that terminal projection and the independently computed assessment receipt coverage.

## Artifact verification blocker

The model exported the archived `.rob2.zip`; installed production verification passes. The frozen standalone verifier fails with `scientific pack descriptor differs`: its current descriptor hash is `c2650a6e…`, while the artifact contains `d6ff8a6a…`, which the installed pack accepts. Both verifier results and the unchanged standalone verifier are archived. No post-run verifier patch or artifact repair was performed. This is a completed native workflow, **not a bundle that passed both verifiers**.

Supporting records: `events.jsonl` contains every model-visible tool response; `submissions.json` and `domain-history-records.json` retain accepted/rejected drafts and revision history; `coverage.json` records delivery; `durable-token-usage-records.json` records provider usage; `bundle-check.json` records both verifiers. Authentication files and private rollout content were not archived. Original benchmark database hashes remained unchanged.
