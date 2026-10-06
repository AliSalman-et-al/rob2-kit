# Allsop 2014: one bounded full-assessment attempt

**The requested full D1–D5 assessment did not complete.** One exact `gpt-6-luna` / Medium invocation at frozen clean implementation `72bf943` accepted D1 and D2, rejected an incomplete D3 answer path, and stopped at the authorized total-input guard before D4/D5. There was no rerun, second case, operator answer, manual submission repair or mid-run implementation change. No overall label or accuracy score is inferred.

## Selection and frozen inputs

Selected from the required October 1 Code benchmark, outside the prior paid development inventory: Allsop 2014 is an individual parallel nabiximols–placebo RCT with 51 randomized participants, an 11-page main report and six-page supplement. Both captured PDFs were available and restored with matching source hashes. The report directly states the primary overall withdrawal treatment-by-time statistic F=2.39 (abstract/main page 4, Table 2 page 7). Suitability was checked from documents and the approved target, without reading reference/domain labels for selection.

The original approved assignment target and numeric reported Result were retained, with all five prior Domain records, histories and reasoning records removed only from the isolated copy. Source database hashes were unchanged after the run. This begins from an existing approved Result rather than a fresh result-selection workflow. The requested medication window is days 1–6, while Table 2 describes its repeated-measures model using days 1–9. This scope limitation was identified before launch and was not silently corrected or supplied as an answer hint. Human target alignment and label agreement remain provisional; no human/reference labels were read for scoring.

[Manifest](manifest.json), [exact prompt](prompt.txt), [CLI config](cli-config.toml), [preparation](prepare-allsop-full.py), [full-case launcher](run_full_case.py). The exact model and effort were checked in manifest, configuration and launcher before inference. Authentication files and private raw rollout metadata are not archived.

## Terminal outcome and cost

| Domain | Accepted judgment | Save attempts | Rejected saves |
| --- | --- | --- | --- |
| D1 randomization | Some concerns | 2 | 1: unread context continuation |
| D2 deviations | Low | 2 | 1: unread context continuation |
| D3 missing outcomes | None | 1 | 1: missing active 3.3 answer |
| D4 measurement | Not reached | 0 | 0 |
| D5 selection | Not reached | 0 | 0 |

[Exact five submissions and native results](submissions.json), [accepted records](accepted-domain-records.json), [all native events](events.jsonl). The D3 draft is preserved without repair or inferred label. No final assistant response was produced.

The invocation lasted **151.05 seconds**, with 31 completed direct MCP calls, zero model code calls and 31 durable usage records. Total input **2,080,700 = 1,950,208 cached + 130,492 uncached**; output **5,268**, including **777 reported reasoning tokens** (not additive). The total-input guard was 2M; the last in-flight generation overshot it by **80,700**. Uncached input, output, tool-start and per-domain save-start overshoots were zero. Wall/idle guards were 20 minutes/3 minutes, tool limit 60, uncached input 200k, output 15k, four saves per domain, and stop on two identical consecutive rejections in a domain. The monitor checks usage reactively; it cannot prevent an in-flight generation's overshoot. Stop reason is `total input threshold`; CLI process exit 0 does not mean scientific completion. [Run and monitored overshoot](run.json), [durable usage](durable-token-usage-records.json).

## Coverage and scientific review

Read receipts cover all **11 main-report pages and six supplement pages**; exact read windows and all native source/text continuations remain auditable. This is delivered/read coverage, not proof of comprehension or independent evidence validation. Selected evidence and warrants are retained in [selected-evidence.json](selected-evidence.json) and [coverage.json](coverage.json).

D1 grounds random sequence generation in an independent statistician's site-specific random blocks (main page 3), retains unknown concealment instead of using post-assignment blinding as proof, and discusses baseline CWS/disability differences. Adjustment is not itself proof of sound randomization; the rationale also uses the overall limited imbalance pattern. Some concerns follows the unresolved concealment proposition, not an asserted baseline process failure.

D2 uses documented matched placebo, formal blinding assessment and participants' inability to reliably distinguish groups (abstract/page 5), while preserving uncertainty about intervention-delivery personnel. The accepted path stops the trial-context-deviation branch because both awareness responses are Probably No. Its extra unresolved deviation discussion does not activate an unsupported harmful-deviation branch. The all-51 ITT statement supports assignment analysis without proving complete outcome observation; the model treats imputation separately in its D3 draft. These are source-backed warrants, not independently validated domain correctness.

The unaccepted D3 draft correctly distinguishes ITT inclusion from actual missing questionnaires, and does not treat multiple imputation or Little's MCAR test as demonstrating no bias. However, reported 14.4% missing data through day 7 and 28.6% through day 9 (main page 3) concern repeated questionnaires, not necessarily the percentage of randomized participants with a missing single terminal outcome. Neither exactly matches the approved days 1–6 window; the model acknowledges the window distinction but the extent/mechanism proposition remains unadjudicated. It omits active 3.3 and never completes 3.4. No answer coercion or gain claim follows from this partial record.

## High-signal implementation finding

Source-first delivery worked, but context delivery consumed the bounded end-to-end budget. There were **18 context calls** before D3 completion. D1 alone required **nine pages** at 18k bytes: six continuation pages carried large `primary_report` sections before the question/evidence pages. The model separately read the report through `read_pages`, duplicating delivered source text, and prematurely saved D1/D2 before finishing context. D2 required a page-size recovery and four successful context pages; D3 required four. Exact per-page section sizes and continuation arguments are recorded in coverage.json.

This trace justifies an offline investigation of context construction/delivery: retain full source coverage and complete scientific guidance while avoiding repeated delivery of already-read primary-report text and making pending context continuation unmistakable. It does not justify adding answer-specific prose, changing scientific branches, expanding paid guards or rerunning this case. The budget limitation is mostly repeated cached context; substantive source reading still costs 130k uncached input. Any proposed simplification needs a typed delivery/coverage control before another paid test. No production change was made after this result.

A separate pre-run CI snapshot showed the current `72bf943` run queued (https://github.com/AliSalman-et-al/rob2-kit/actions/runs/37094195100) and its predecessor in progress. CI was not used to gate the experiment and was not awaited. No merge or full benchmark occurred. Documentation diff checks only; no broad tests.
