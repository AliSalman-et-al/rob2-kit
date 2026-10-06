# Two-response fictional D3.1 guidance contrast

**Inconclusive about incremental benefit: no correction or regression demonstrated.** Both old and new operational wording yielded `probably_yes` for fictional Case A and `no_information` for fictional Case B. No domain or overall judgment was requested or inferred. Both outputs were frozen before adjudication. This is supplied-evidence interpretation, not benchmark or clinical accuracy.

Both responses weighed approximate endpoint-specific temporal coverage instead of dismissing it solely for absent participant observation counts. Both explicitly distinguished person-time from participant completeness and known vital status from nonfatal/full composite ascertainment. Both rejected ITT membership and a censoring rule as proof of actual availability in Case B. Neither used a universal threshold, invented missing follow-up quantities, or required a formal HR bound to choose a probable answer.

The **impact explanation is brief in both arms**. Old: “the potential impact of missing outcomes cannot be determined precisely.” New: “its potential impact cannot be pinned down without individual loss timing, exact observation counts, or sensitivity results.” Neither relates plausible missing future first events to the selected HR/precision or explains why those events could or could not materially change the estimate. Neither substantively weighs continued endpoint ascertainment after treatment stopping or consent withdrawals. This is a transparency limitation, not evidence that the answers are scientifically wrong. No preregistered observable criterion is clearly unmet, and no calculation or numerical bound is required. Identical PY answers neither independently validate nor invalidate scientific adequacy. The new text is a defensible correction of an internal inconsistency, but this pair supplies no demonstrated behavioral gain.

## Frozen design and integrity

Protocol was committed as `2655a93` before either launch. Both received exactly the same two explicitly fictional cases and selected assignment result; only D3.1's implemented operational decision rule, first evidence-needed item and no-information rule differed. Official text, answer options, all other card fields, task, evidence order and complete evidence bytes were identical. No desired answers, reviewer preferences, real clinical names or evaluative control labels were included. Sources retained genuine unknowns; a justified NI was allowed.

Both manifest completeness preflights passed offline and again through `launch_checked`. Launcher command and runtime turn metadata independently identify `gpt-6-luna` at `medium`; CLI 0.159.0. Fresh isolated homes, empty working directories, no MCP and disabled tool features; neither response called tools. Inputs, private criteria, scope review, source manifests, command/config, native events, exact response text and unique-response token records are preserved. `answer-freeze.json` binds both outputs before `adjudication.json`. Raw stderr remains private outside the repository; committed stderr removes account email/identity only, without changing responses/events/usage.

## Exact observed usage

| Arm | Input | Cached input | Uncached input | Output | Reported reasoning | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|
| Old | 7,513 | 3,840 | 3,673 | 193 | 0 | 10.995 |
| New | 7,608 | 1,792 | 5,816 | 240 | 0 | 10.232 |
| Total | 15,121 | 5,632 | 9,489 | 433 | 0 | 21.226 |

Two CLI invocations, two unique provider responses, one final per arm, zero tools/retries/continuations. Both exited successfully; no wall/idle/output guard fired and no observed overshoot. Limits were 3,000 output tokens, five minutes wall and two minutes idle per arm, with input telemetry only. Token guards are reactive rather than provider billing caps. Dollar cost is unavailable. Different cache reuse limits cost-comparison interpretation.

## Useful offline continuation

`next-real-source/` prepares eleven complete EXSCEL primary-source pages and Figure S2/S9 images from the required original Code benchmark dossier, with exact PDF/projection/image hashes and the unchanged selected result. It targets the remaining availability/impact warrant weakness, without prescribing a clinical answer. It has no inference launch path and is explicitly not launch-ready or authorized. A new bounded decision, frozen actual input/delivery manifest and passed completeness preflight are required before any further call. The frozen EXSCEL assessment/labels were untouched. No full benchmark, merge or CI wait occurred.

Follow-up qualification: `qualification.json` preserves the distinction between a brief explanation and an indefensible answer. The original `adjudication.json` remains unchanged as an audit record; its “incomplete impact warrant” wording must be read with this qualification. No diagnostic was run in this follow-up.
