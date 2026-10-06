# One Allsop completion check at b54db92

**Incomplete: one accepted D1 judgment, no final bundle.** Exactly one `gpt-6-luna` / Medium invocation ended with its own incomplete final response after opening D2 and attempting premature finalization. No guard was exhausted, no external execution failure was observed, and no operator answer or repair was supplied. D2–D5 remain unassessed. No rerun or second case followed.

## Frozen inputs and authorized controls

This is a **known-case mechanism check**, not unseen validation. The original Code October 1 Allsop source/database hashes, approved target and reported Result match the previous run exactly. Both original PDFs were restored; all prior Domain records, histories, reasoning, closure/review state and delivery caches were cleared only in the isolated copy. The captured source projections total 72,190 UTF-8 bytes. No reference label, page/count/answer hint or alternative target was supplied to the model. [Manifest](manifest.json), [source-budget preflight](source-budget-preflight.json), [prompt](prompt.txt), [CLI config](cli-config.toml), [preparation](prepare-allsop-full-b54db92.py).

The current direct MCP launcher used exact `gpt-6-luna`, Medium effort and frozen clean implementation **b54db92ebef65ca20734bdf31a24ad8a25ced728**. In addition to assessment/source tools, status, review, closure and finalization were exposed so the model could produce a genuine bundle. This finalization requirement and additional tool exposure differ from the first attempt, which stopped its task after the five Domains. The runs are therefore not a blinded causal experiment on the delivery fix.

The explicitly approved cached-input-heavy guard was **5M total input**, retaining **200k uncached input, 15k output, 60 tools, 20-minute wall, 3-minute idle, four total saves per Domain and two identical consecutive errors**. It intentionally raises only the total-input ceiling from the previous 2M. Strict preflight validated manifest/configuration/prompt identity; no controls changed during execution. Reactive guards can overshoot within an in-flight generation and do not guarantee monetary billing caps. [Exact launcher](run_full_case_b54db92.py).

## Terminal outputs and cost

| Domain | Result | Save attempts / rejected saves |
| --- | --- | --- |
| D1 randomization | **Some concerns**, accepted | 1 / 0 |
| D2 deviations | Header opened; no answer submitted | 0 / 0 |
| D3–D5 | Not reached | 0 / 0 |
| Overall | None | No assessed snapshot, closure or artifact |

The invocation lasted **63.89 seconds**, used **13 completed direct MCP calls**, zero model code calls and 14 durable usage records. Input **519,863 = 449,280 cached + 70,583 uncached**; output **1,717**, with **187 reported reasoning tokens**. Every monitored input, uncached, output, tool-start and per-Domain save-start overshoot was **zero**. Monetary charges are not observed; these are the recorded cost components. [Run](run.json), [durable usage](durable-token-usage-records.json), [summary](summary.json).

`stop_reason` is null because no monitor guard stopped the process. CLI exit 0 records process completion, **not scientific completion**. There were two non-save conditions: a model-requested 6,500-byte context budget was too small (recovered at 20,000), and premature `finalize_batch` was rejected as `invalid_request`. No save rejection occurred. The final response correctly says the Trial remains pending. [Exact response](response.txt), [native trace](events.jsonl), [accepted D1 submission](submissions.json), [bundle/phase check](bundle-check.json).

## Delivery and scientific warrants

The model actually used `read_pages` recovery: four source calls returned the main report through its final physical lines, and verified coverage reports **read_complete for the main article**. All successful contexts contain **zero inline primary-report items**. D1 used three distinct scientific context pages plus a header recovery/re-read; source text was not replayed in these pages. On entering D2, the server reused the complete main-report receipt and returned no primary-reading recovery. The six-page supplement remained unread. [Delivery windows, context headers and verified status](coverage.json).

D1 answers are sequence **Yes**, concealment **No information**, baseline imbalance **Probably No**. The source describes an independent statistician's site-specific random-block list in Stata, supporting sequence generation. The model distinguishes post-assignment blinding from pre-assignment concealment and records a bounded concealment limitation rather than asserting concealment failure. It acknowledges CWS/disability baseline differences and retains source-linked counterpoints. [Accepted record](accepted-domain-records.json), [source evidence](selected-evidence.json).

One explanation overreaches: it calls baseline adjustment covariates “prespecified.” Main page 4 describes adjustment using variables known/suspected to influence withdrawal and variables significantly different between groups; these passages do **not establish pre-unblinding specification**. The source supports adjustment, not that timing claim. This is an unsupported temporal adjective, not proof that an opposite baseline answer is correct. Adjustment alone does not cure randomization problems. The selected main-report stopping rationale is not a verified absence claim over every captured source, since the supplement was not inspected. Neither issue was manually repaired or converted into another label.

The target still describes treatment days 1–6 while the reported F statistic's Table 2 model uses days 1–9. The full source/target distinction remains visible and unresolved for the unassessed later Domains. Complete source delivery proves neither comprehension nor correct scientific judgments.

## Post-terminal reference comparison and next decision

Only after terminal, the operator read the required Code `LABELS-batch.csv` and `OUTCOMES-batch.csv` rows. **D1 provisionally agrees** with the reference's Some concerns. The reference labels are scoped to “meta outcomes”; the day1–6 requested window versus day1–9 reported model and independent human target matching remain unresolved. No accuracy score, All-Low advantage, whole-case agreement or overall judgment is inferred from one accepted Domain. [Exact reference rows and hashes](provisional-reference.json). Missing human appendix was not a blocker; the model's continuation failure was. The reference's two Some concerns Domains with overall Some concerns also differs from local ADR0035's automatic aggregation rule, but no current overall result exists to compare.

The delivery change was enacted, but the model did not enact the full workflow despite ample remaining guards. D2's initial page had no question cards, a five-page context with a concrete `context_page.next_cursor`, and `head.next_action` naming `get_domain_context` without that cursor. The model instead tried finalization, was correctly directed back to D2, then stopped. This does not prove why it stopped or that the server's existing cursor contract was wrong: the cursor and full instructions were available, and the same model followed D1's chain.

The next bounded offline decision should inspect **first-page orientation and machine-actionable continuation** together: can the authoritative next action name the exact pending cursor/recovery arguments and make partial context unmistakable while preserving every conditional question and counterpoint? Keep finalization's rejection intact. Do not add trial-specific answer hints, force uncertain labels, buy another case immediately or treat the increased cached ceiling as a solution to this early stop. Actual all-Domain judgment quality and verified-bundle completion remain unproven.

Original Code database hashes remain unchanged. No implementation edits occurred during or after the invocation; this checkpoint archives evidence only. No broad tests, CI wait, full benchmark, merge or additional model invocation occurred. Authentication, private reasoning and raw private rollout metadata are excluded.
