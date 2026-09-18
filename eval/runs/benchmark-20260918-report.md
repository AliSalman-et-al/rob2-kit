# rob2-kit benchmark report

Date: 2026-09-18

This report covers the rob2-kit worktree based at commit
`2465744368950a0d945c38e9f60654a801fa878c`, with the implementation changes
under evaluation still uncommitted at run time. The retained bundles record
scientific pack hash `sha256:5c49411aedccf4cae2e3e97a955760ed83bd00283ff5a0ae5041272d13439b60`
under result semantics v0.8. That pack identity is preserved as historical
evidence; it is not a qualification claim for the later current pack hash.

## Method

- Model: Codex CLI `0.154.0`, `gpt-5.6-luna`, reasoning effort `medium`.
- Each eligible Trial/outcome used one fresh workspace and one minimal prompt:
  `/rob2-assess Assess risk of bias for <Outcome> in <Trial>.`
- Codex was run with JSONL output. Every phase, stderr stream, prompt, metadata
  record, and finalized bundle is retained under the outcome run directory.
- Proposal Review was approved only after checking the selected endpoint against
  the Trial abstract. Corrections changed proposal scope only; no Domain answer
  was supplied to the model.
- Trials without the requested outcome in `eval/reference/catalog/trials.csv` were
  skipped: PFS 10, OS 10, and AE 8 were eligible.
- Scores use the provisional labels in `eval/reference/catalog/provisional-labels`.
  `L` means `Low`, `S` means `Some Concerns`, and `H` means `High`.

The benchmark used workspace-level isolation with `sandbox_mode=workspace-write`
and a separate Codex home per Trial. Strict Windows host isolation was not
available without UAC, so this is not equivalent to a deny-by-default OS sandbox.

## Results

| Outcome | Eligible | Finalized | Proposal corrections | Exact Domains | Low vs non-Low Domains | Exact Overall | Low vs non-Low Overall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Progression Free Survival | 10 | 10 | 2 | 36/50 (72.0%) | 39/50 (78.0%) | 0/10 (0.0%) | 7/10 (70.0%) |
| Overall Survival | 10 | 10 | 0 | 40/50 (80.0%) | 42/50 (84.0%) | 2/10 (20.0%) | 5/10 (50.0%) |
| Adverse Events | 8 | 8 | 4 | 22/40 (55.0%) | 25/40 (62.5%) | 1/8 (12.5%) | 7/8 (87.5%) |
| All outcomes | 28 | 28 | 6 | 98/140 (70.0%) | 106/140 (75.7%) | 3/28 (10.7%) | 19/28 (67.9%) |

“Low vs non-Low” treats `Some Concerns` and `High` as one class. No reference
case has a `High` label.

### Domain accuracy

| Outcome | D1 | D2 | D3 | D4 | D5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Progression Free Survival, exact | 9/10 | 9/10 | 4/10 | 9/10 | 5/10 |
| Progression Free Survival, Low vs non-Low | 9/10 | 9/10 | 6/10 | 10/10 | 5/10 |
| Overall Survival, exact | 8/10 | 7/10 | 6/10 | 10/10 | 9/10 |
| Overall Survival, Low vs non-Low | 8/10 | 7/10 | 8/10 | 10/10 | 9/10 |
| Adverse Events, exact | 6/8 | 5/8 | 1/8 | 6/8 | 4/8 |
| Adverse Events, Low vs non-Low | 6/8 | 5/8 | 2/8 | 8/8 | 4/8 |

## Per-Trial mismatches

The notation `D3 L→H`, for example, means the reference was Low and the model
returned High. The full observed and expected maps are in each outcome’s
`rsi-wave.json`.

### Progression Free Survival

| Trial | Domain mismatches | Overall |
| --- | --- | --- |
| ARASENS | D3 L→H; D5 L→S | L→H |
| ARCHES | D3 S→L | S→L |
| CHAARTED | D3 L→H; D4 S→H | S→H |
| ENZAMET | D5 L→S | S→H |
| GETUG-AFU-15 | — | S→H |
| LATITUDE | D3 S→H | S→H |
| PEACE-1 | D2 S→L; D3 L→H | S→H |
| STAMPEDE | D3 S→H; D5 L→S | S→H |
| SWOG-1216 | D1 L→S; D5 L→S | S→H |
| TITAN | D5 S→L | S→L |

Proposal corrections: CHAARTED was changed to the abstract’s “time to
biochemical, symptomatic, or radiographic progression”; STAMPEDE was changed to
the abstract-reported failure-free-survival result.

### Overall Survival

| Trial | Domain mismatches | Overall |
| --- | --- | --- |
| ARASENS | — | — |
| ARCHES | D3 S→L | S→L |
| CHAARTED | D1 L→S | L→S |
| ENZAMET | — | — |
| GETUG-AFU-15 | D2 L→H | S→H |
| LATITUDE | D2 L→H; D3 S→H | S→H |
| PEACE-1 | D2 S→L | S→L |
| STAMPEDE | D3 S→H | S→H |
| SWOG-1216 | D1 L→S; D3 L→S | L→H |
| TITAN | D5 S→L | S→L |

No proposal correction was needed for OS.

### Adverse Events

| Trial | Domain mismatches | Overall |
| --- | --- | --- |
| ARASENS | D2 L→S; D5 L→S | L→H |
| ARCHES | D1 L→S; D2 L→S; D3 S→H | S→H |
| ENZAMET | D3 L→H; D4 S→H; D5 L→S | S→H |
| LATITUDE | D3 S→L; D5 L→S | — |
| PEACE-1 | D3 L→S; D5 L→S | S→H |
| STAMPEDE | D2 L→S; D3 S→L; D4 S→H | S→H |
| SWOG-1216 | D1 L→H; D3 L→H | S→H |
| TITAN | D3 L→H | S→H |

Proposal corrections: ARCHES to grade 3-or-greater AEs; ENZAMET to treatment
discontinuation due to AEs; LATITUDE to grade 3 hypertension, because the
abstract did not provide a combined hypertension/hypokalemia endpoint; TITAN to
grade 3-or-4 AEs.

## Why the model fell short

The retained Domain justifications show a consistent pattern rather than random
errors.

1. **Missing outcome data was overcalled.** D3 was the weakest Domain for PFS
   (4/10 exact) and AE (1/8 exact). The model repeatedly required explicit,
   outcome-specific completeness, censoring, loss-to-follow-up accounting, or a
   missing-data sensitivity analysis before selecting Low. It therefore returned
   High for ARASENS, CHAARTED, LATITUDE, PEACE-1, and STAMPEDE on PFS, and for
   ARCHES, ENZAMET, SWOG-1216, and TITAN on AE. The reference labels are less
   conservative for several of the same reports.

2. **Selection of the reported result was too conservative.** The D5
   justifications commonly said that the captured SAP or protocol did not prove
   that the plan predated unblinding. That produced Some Concerns where the
   reference was Low (PFS ARASENS, ENZAMET, STAMPEDE, and SWOG-1216; AE several
   cases), while it returned Low for TITAN PFS where the protocol evidence was
   clearer. This is a chronology-evidence mismatch, not a failure to find an
   endpoint.

3. **AE Domain 2 conflated awareness with deviations.** For open-label AE cases,
   the final justifications treated participant or personnel awareness as a
   reason to raise D2, even when the reference was Low. Safety-population
   exclusions also contributed to concern. This explains the AE D2 score of
   5/8, while D4 still achieved 8/8 after pooling Some Concerns and High.

4. **AE measurement judgments sometimes penalized plausible differential
   ascertainment.** ENZAMET and STAMPEDE received High for D4 despite standard
   CTCAE grading. The model’s justifications focused on possible differences in
   follow-up or safety assessment schedules; the reference labels accepted the
   standard measurement approach as Some Concerns.

5. **Randomization and overall synthesis were asymmetric.** The model required
   explicit sequence-generation or concealment evidence and raised D1 for
   CHAARTED OS, SWOG-1216 OS/AE, and related cases. At the summary level it also
   produced 17 High Domain labels and 19 High overall labels; the reference has
   no High labels. That conservative aggregation explains why exact overall
   agreement was only 0/10 for PFS and 1/8 for AE even though binary overall
   agreement was 70.0% and 87.5%, respectively.

## Harness observations and fixes

- The runner initially could not resume a pending Proposal Review with a
  correction prompt. I added `--proposal-correction` with host-state validation
  to `scripts/run_rsi_case.py`; its focused test suite passed (7 tests).
- CHAARTED PFS phase 1 was the canary started before that runner patch and used
  an equivalent minimal prompt file; its replacement proposal and continuation
  used the patched runner. The rob2-kit product commit was unchanged.
- One OS launcher attempt pre-created trial directories, which the runner
  correctly rejects for phase 1. Those four pre-model launcher errors are
  retained separately; the clean rerun produced the scored OS cohort.
- Several Codex stderr streams contain PowerShell snapshot warnings and curated
  plugin-sync/manifest warnings. They did not alter the rob2-kit traces or
  prevent any scored case from finalizing, and are not counted as rob2-kit
  scientific failures.

## Artifacts

- PFS: `eval/runs/benchmark-current-pfs-luna-medium-20260918`
- OS: `eval/runs/benchmark-current-os-luna-medium-20260918-rerun`
- AE: `eval/runs/benchmark-current-ae-luna-medium-20260918`
- Each outcome directory contains `rsi-wave.json`, `rsi-analysis.json`, and
  `benchmark-details.json`; each Trial directory retains JSONL traces and its
  finalized `.rob2.zip`.
- All 28 finalized bundles passed `scripts/verify_bundle.py`.
