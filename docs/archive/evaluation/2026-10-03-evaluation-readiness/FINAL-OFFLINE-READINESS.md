# Final offline receipt: source/input ready, no-go under the 15k budget

The actionable source and input prerequisites are complete. **Paid diagnostics remain paused. No launch occurred.** [Final receipt](final-readiness-receipt.json) supersedes the initial `readiness.json` blockers. The remaining blocker is budget fit / exact token measurement, not unavailable figures, unresolved source selection or unfrozen model inputs.

## Verified sources and meaningful scientific contrast

Rendered and inspected main PDF pages4–7 and supplement pages1–4 directly from the supplied Code corpus. [Visual transcriptions and reconciliation](visual-transcriptions.json), [rendered images](figures/) and [image hashes](figure-render-hashes.json) retain the evidence. This is a single agent's direct inspection, not an independent second human adjudication. The original captured text and full packet are unchanged; visual transcription is separately identified with visual line coordinates and must not be mistaken for native extracted text lines.

Figure1 confirms randomized144/147; study completion134/142; treatment completion134/143. All randomized received at least one dose. Registry flow agrees with study counts/reasons. Primary registry MMRM denominator133/142 has the explicit definition baseline plus at least one post-baseline HbA1c value. Paper and registry therefore supply distinct membership, completion and analysis-eligibility facts, **not** a known week28 measured-value denominator.

Dulaglutide drug discontinuation10: AE4, withdrawal4, noncompliance1, unknown1. Dulaglutide study discontinuation10: AE4, withdrawal5, noncompliance1. Placebo drug discontinuation4: withdrawal3, investigator decision1; study discontinuation5 additionally includes death1. Main safety text places death during safety follow-up and describes the acute-kidney-injury participant's study discontinuation131days after drug discontinuation. Do not assign that death a pre-week28 HbA1c missingness effect or equate study/drug stopping individuals by totals.

One dulaglutide patient required rescue for severe persistent hyperglycaemia. Primary analysis censors after rescue/drug discontinuation. The registry's exact ETD−0.95 (−1.14,−0.77) is consistent with paper rounding−1.0 (−1.1,−0.8); negative signs were checked visually because some extracted text loses them. Supplement139/147 and LOCF refer to secondary composite analyses and must not replace primary MMRM counts/method. Titration SMBG rules and insulin dose are separate measures. These source distinctions make this a real analysis-conduct question; no desired label is supplied.

The frozen assignment target, arms, primary continuous HbA1c, baseline-to-week28 contrast and reported ETD are identical across arms. The archived `exact` relation is preserved as host metadata, not certified as whole-estimand correspondence: post-rescue/discontinuation data exclusion is scientifically relevant to the assignment-effect question. Whether excluded recorded values existed, full week28 measurement availability, overlap of eligibility/completion/rescue sets, and effect importance remain unresolved. Supported probable responses are allowed; neither a blanket NI nor ITT-based certainty is preferred by design.

## Scientifically complete bounded selection

[Selection](bounded-source-selection.json) retains main pages1–8 (all methods/results/discussion), all four supplement PDF pages, the whole captured original-DOCX supplement projection, and registry study identity/arms/design, primary protocol outcome, entire posted primary result and complete participant-flow module. It includes necessary previously uncited facts:133/142 eligibility definition, exact registry estimate, all flow reasons, rescue count and death timing. Main pages9–10 are acknowledgments/data-access/references; other registry endpoints, adverse-event/baseline tables and administrative material are outside this narrowly declared2.6/conditional2.7 question. Full captured packet remains available to audit selection. This is completeness for the declared scientific question, not every possible trial/domain question or independent semantic certification.

## Frozen inputs and difference check

- [Baseline input](baseline-input.txt) and [current input](current-input.txt).
- [Baseline manifest](baseline-manifest.json) / [preflight](baseline-preflight.json); [current manifest](current-manifest.json) / [preflight](current-preflight.json).
- [Identical model configuration](frozen-model-config.toml): exact existing `gpt-6-luna`, medium, tools/browser/apps disabled, no MCP server. This freezes intended settings; actual runtime model/effort must still be verified if a future authorized call occurs.
- [Private preregistered rubric](private-adjudication-rubric.json) remains outside both inputs. It distinguishes source interpretation, unsupported certainty, legitimate probability/uncertainty, material omissions and citation entailment. No outputs exist.

Both assembled inputs pass declared byte-range/hash coverage checks. Exact comparison verified equal common task/target/questions/guidance and **byte-identical evidence bodies**, including visual transcriptions. Differences are solely implemented target/reported-result card fields, scope annotation and instruction prefix; subsequent instruction text and later card guidance are identical. The same reported-result facts remain in the shared approved-result object, so baseline loses presentation colocation, not source knowledge. No prior domain labels or reference labels are included. Manifest hashes and model-config hash are in the final receipt; any later launch must pass `launch_checked` again with those frozen hashes.

## Token and budget decision

The shared environment has no `tiktoken`, `tokenizers` or `transformers`, and no official local `gpt-6-luna` tokenizer was available. No network install or provider token-count request was made. **Exact token count is unavailable.** Explicit character-based estimates are only estimates, not guaranteed bounds or billing quantities:

| Arm | UTF-8 bytes | Unicode characters | Estimate at4chars/token | Estimate at3chars/token |
|---|---:|---:|---:|---:|
| Baseline | 95,091 | 94,898 | 23,725 | 31,633 |
| Current | 95,776 | 95,583 | 23,896 | 31,861 |

Both estimates exceed the preregistered15,000-input-token limit. Source preservation takes precedence over that target; no critical evidence or scientific alternatives were removed to manufacture a budget pass. Fixed full card/question presentation also occupies context; compressing that selectively would introduce another treatment. The output/time/call ceilings remain1,500output/90seconds per arm/two calls/zero tools/no repeat. Dollar cost is unavailable, and cached versus uncached input must be measured from actual responses rather than assumed.

**Final status: no-go on the existing15k budget.** The precise next prerequisite is an applicable local tokenizer measurement and/or an explicitly redesigned budget, not more scientific source collection. No budget increase is authorized by this artifact. These frozen inputs can be reviewed without inference; if the limit is retained, stop rather than run an oversized pair. No routine approval question or further offline audit is needed. Production code is unchanged; this task stops with pushed inputs/config/manifests, successful offline coverage receipts and the qualified budget blocker.
