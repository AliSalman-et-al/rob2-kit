# Two-response D5 guidance diagnostic

Prospective hypothesis and exact comparison are preserved in `manifest.json`. Two isolated tool-free `gpt-6-luna`, medium, CLI 0.159.0 responses compared 7e311c1 versus c8eb139 question guidance. Frozen source input, instructions, question wording, ordering, model and settings were identical; only the guidance payload changed. Comparison cards, retrieval and public submission schema were not tested. Both responses were frozen before reviewing either prediction. No retries, tools or production checkpoints occurred.

CANVAS and Allsop use original captured passages and approved targets from the actual Code October 1 benchmark, with prior answers/rationales withheld. The source audit retains original hashes and coordinates. These are incomplete evidence excerpts, not cold case replays. Two explicitly synthetic controls share the same target, eligible analyses and absent plan; only the authors' reporting reason differs. The explicit favorable-choice sentence is not attributed to a real trial. All four vignettes appeared in each response, so within-response carryover remains possible. No gold answers were supplied.

| Vignette | Before 5.1 / 5.2 / 5.3 | After 5.1 / 5.2 / 5.3 | Offline D5 mapping | Interpretation |
| --- | --- | --- | --- | --- |
| CANVAS captured plan/report | NI / NI / NI | PY / NI / NI | Some concerns → Some concerns | Changed confidence without an articulated positive chronology warrant; not an improvement claim. |
| Allsop, uncaptured protocol | NI / NI / NI | NI / NI / NI | Some concerns → Some concerns | Uncertainty preserved. |
| Synthetic report A, unknown reason | NI / No / NI | NI / No / NI | Some concerns → Some concerns | Multiplicity did not become affirmative selection or reassurance. |
| Synthetic report B, explicit favorable choice | No / No / Yes | No / No / Yes | High → High | Positive selection control preserved, already recognized before. |

NI means No information; PY means Probably yes. `offline-mapping.json` comes from typed draft validation and the production `evaluate_domain` function. All question memberships, answer enums, source references for real cases, and short-output limits passed. Validation establishes admissible algorithm inputs, not evidence entailment or production acceptance.

The CANVAS after-rationale establishes correspondence and explicitly says early finalization is unestablished. It does not explain why the chronology conjunct is probably satisfied, despite available blinded-period and prior-plan material. This is a warrant gap in the response, not proof that PY is intrinsically wrong for CANVAS. The unchanged synthetic 5.2 No rationales also rely on “no alternative identified”; the frozen facts establish only an absence in this supplied dossier, not necessarily uniqueness across the outcome domain. Neither issue was silently repaired or counted as a scientific success. Explicit favorable selection supports concern for 5.1 even without knowing whether the original plan existed: the reported choice itself was made after results.

The predicted 5.3 improvement was not observed: the old guidance already detected the explicit favorable choice. The revised instructions remain consistent with source guidance, but this easy control neither proves a benefit nor estimates regression frequency. All four domain mappings are unchanged. No benchmark accuracy, All-Low advantage, or production completion gain can be inferred.

## Cost and execution evidence

| Invocation | Seconds | Input | Cached input | Uncached input | Output | Tools / retries |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Before | 35.57 | 17,050 | 0 | 17,050 | 1,271 | 0 / 0 |
| After | 32.39 | 17,310 | 3,840 | 13,470 | 1,424 | 0 / 0 |
| Total | 67.96 | 34,360 | 3,840 | 30,520 | 2,695 | 0 / 0 |

Total token count is 37,055; recorded reasoning output is zero. Token counts are usage, not a dollar-price estimate. Exact launcher commands, prompt/output hashes, sanitized durable usage records, frozen outputs and offline mappings are retained. Raw local homes, authentication and stderr are excluded. Each invocation finished below the 480-second wall, 120-second idle and 4,000-output-token guards. These are reactive stop guards, not provider billing caps.

Recommended next scientific step: offline human review of CANVAS's chronology warrant using the already captured dated SAP and blinded-period passages, and precise outcome-domain eligibility for the measurement control. Do not repeat these easy model examples or expand to a full benchmark. A future paid test should require a harder real, independently matched source case and an explicit adjudication rationale before execution. No feature change was made during this diagnostic.
