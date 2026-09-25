# Fresh trial-specific rob2-kit benchmark

Run date: 24–25 September 2026.

## Protocol

- Latest local rob2-kit code used: `f80600fc6d614d9492fe227718835637` campaign, repository commit `f1f8a32ce68be6260cb1a5683e65f72c7af2059d`.
- Codex CLI 0.156.1 with `gpt-6-luna`, medium reasoning.
- The prompt policy was exactly: `Minimal user prompt: /rob2-assess Assess risk of bias for {concept} defined as {definition}, {effect size} in {trial}.`
- Thirty trial/outcome proposals were generated before batch review. Twenty-nine were assessable and approved after source-backed scope review; CHAARTED adverse events was left unapproved because the abstract reported only selected docetaxel-arm rates without a randomized comparator.
- Three proposals were corrected after source review: GETUG-AFU-15 to serious AE counts, LATITUDE to grade 3/4 AE rates, and PEACE-1 to include AE denominators for its docetaxel subgroup. The replacement SWOG-1216 AE proposal received a source-backed equivalence adjudication before its fresh assessment.
- Assessments were run in parallel with per-case JSONL logs. The original SWOG-1216 AE execution encountered a Codex HTTP 503 during a source search, so an independently approved fresh SWOG-1216 AE run replaced it for scoring. The failed original trace remains preserved.
- Frozen catalog labels were compared with finalized, independently verified bundles. Source adjudications normalize equivalent arm names and accept the source-refined scope; no case was admitted under `accepted_with_scope_difference`.

## Isolation limit

On this Windows host, Codex CLI refused `--require-isolated-host` without UAC. Runs used fresh per-case workspaces and Codex homes with `workspace-write` in non-strict exploratory mode. JSONL logs and artifact identities were retained, but this was not strict host isolation.

## Scoring population

- Thirty prompts across ten trials and three concepts; 28 cases had frozen catalog labels and were scored (10 OS, 10 PFS, 8 AE; 140 domain judgments).
- CHAARTED AE was unassessable from the article abstract because no randomized comparator AE result was reported. GETUG-AFU-15 AE was assessed, but its concept has no catalog reference label, so it is excluded from accuracy.
- Labels are provisional reference labels, not a new independent clinical adjudication. The catalog has no High reference labels, so High sensitivity cannot be estimated. Binary scoring treats Some Concerns and High as Non-Low.
- Primary/secondary classification follows the main article’s outcome hierarchy; co-primary outcomes count as Primary. ARASENS’ catalog PFS concept is represented by time to castration-resistant progression. For CHAARTED and STAMPEDE, the abstract did not report the exact PFS result; the prompts explicitly noted that, while the frozen scope used the matching article-body/table result for score comparison.

## Outputs

- [`report.md`](report.md): accuracy by outcome, domain, outcome-by-domain, and primary/secondary status.
- [`score.json`](score.json): case-level reference and observed labels, exclusions, and aggregate metrics.
- [`trial-benchmark-manifest-final.json`](trial-benchmark-manifest-final.json): prompts’ frozen definitions, effect estimates, roles, scope, and run directories; points SWOG-1216 AE to its replacement retry.
- [`scope-adjudications-final.json`](scope-adjudications-final.json): source-backed result-scope decisions used by the scorer.
- [`trial-metadata.tsv`](trial-metadata.tsv) and [`source-map.tsv`](source-map.tsv): outcome classification and source locators.
- Per-case JSONL logs and artifacts are under `runs/`; the separate retry is under `retry-swog1216-adverse-events/`.

Scoring completed: 28 labeled cases, 140 domain judgments, 0 scorer hard failures.
