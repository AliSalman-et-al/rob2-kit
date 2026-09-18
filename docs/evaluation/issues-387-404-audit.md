# Issues #387–#404 audit

Date: 19 September 2026

This audit checks the implementation against the acceptance criteria in GitHub
issues #387–#404. `Implemented` means that the behavior has a production path,
an updated public contract where needed, and focused repository evidence.
`Host hold` means that the code is present but the issue also requires an
installed-host qualification that was not observed here. A host hold is not
converted into a passing result by server tests.

| Issue | Status | Verification and remaining qualification boundary |
| --- | --- | --- |
| #387 | Implemented | Limitation bases require an unresolved premise and stopping rationale; a receipt is optional after direct inspection. Absence remains a scoped lexical no-hit claim, clipped decisive Evidence is not citable, and the lifecycle/export paths preserve the distinction. |
| #388 | Implemented | Single and batch searches validate optional Domain/question purpose. Omitted purpose is retained as Trial discovery in append-only provenance history; bounded candidates are opt-in and recoverable without assigning them to the first open Domain. |
| #389 | Implemented | Native SQLite highlighting is mapped to authoritative projection offsets. Repeated matches, shared occurrences, Unicode/dehyphenation, punctuation, and marker collisions have distinct regression coverage; localization failure is not reported as no match. |
| #390 | Implemented | Literal mode is shared by single/batch search, receipts, cursors, and recovery. It scans the verified projection directly with case-folded contiguous spans and alphanumeric boundaries, without FTS, stemming, or spelling suggestions. |
| #391 | Implemented | Ordinary search uses the versioned `porter-unicode61-v1` profile, scoped BM25 ranking, deterministic ties, atomic derivative rebuild, profile/version-bound cursors, and historical receipt semantics. |
| #392 | Implemented | Source/projection/profile-bound catalogues use RapidFuzz OSA with protected-unit filters, deterministic three-per-unit/eight-total caps, one-unit executable alternatives, and original-query receipt preservation. Literal, prefix, phrase-adjacency, uppercase, and already-matched cases remain ineligible. |
| #393 | Implemented | Navigation returns bounded contents, heading, version/date, and cross-reference leads with source/page locators. Same-location windows are reduced conservatively while distinct metadata and source identities remain separate. |
| #394 | Implemented | Valid source-bound working notes bypass only the conflicting duplicate read gate. Canonical Domain heads supersede stale notes; changed Result/Source scopes reorient, and status exposes the recovery distinction. |
| #395 | Implemented; host hold | Visual Evidence requires delivered image provenance, exact Source/page/region/render/image identities, and honest transcription limits through export and independent verification. Installed-host image visibility was not part of the current smoke. |
| #396 | Implemented; host hold | `get_domain_context` carries complete active question cards and `official_guidance` recovery with pack/version/hash, source locators, exact excerpts, and an explicit continuation state. No network manual fetch or generated replacement summary is used. A separate installed-host surrounding-guidance check remains unobserved. |
| #397 | Implemented; host hold | D3 guidance separates availability, observed/analyzed membership, mitigation, possible dependence, and likely dependence while preserving No Information and High branches. Balanced installed-host discovery/submission qualification was not rerun for this change. |
| #398 | Implemented; host hold | D5 guidance keeps plan timing, access, correspondence, eligible alternatives, and results-driven selection distinct. Chronology/template controls are covered by pack and evaluator tests; a new paid host comparison was not run. |
| #399 | Implemented; host hold | Allocation facts remain separate from imbalance, and assignment-effect guidance distinguishes ITT/mITT, exclusions, observed outcomes, and safety-set grouping. A new cross-outcome installed-host qualification was not run. |
| #400 | Implemented; host hold | D4 guidance distinguishes awareness, detection opportunity, susceptibility, possible influence, and likely influence without endpoint-name defaults or numeric cutoffs. A new installed-host influence comparison was not run. |
| #401 | Implemented | Observation import now retains revision before/after identities, answer values, Evidence locators, rationale digests, and mechanical validation-repair codes separately from scientific revision lineage; private prose is excluded. |
| #402 | Implemented | Counters cover bytes, projection/FTS work, candidate reconstruction, database work, response bytes, and latency. Scoped cache reuse, restart rebuild, tamper checks, bounded retention, and a JSONL-reproducible benchmark artifact are present. The retained CHAARTED probe reports actual deltas; it does not promise a universal speedup. |
| #403 | Implemented | Comparison plans freeze cases, targets, host/model, prompt identity, retries, scoring, and budgets. The runner retains every attempt and reports support, class recall, labels, completion, latency, cost, context, and tool calls without choosing a retry or coaching the model. |
| #404 | Host hold | The qualification report and manifest can freeze the build, contract, pack, skill, sources, host, model, prompt, scorer, and delivery matrix, and hold when a required observation is absent. A current Luna Medium CHAARTED Overall Survival smoke finalized and passed independent bundle verification, but the required image and repairable-error matrix, focused comparisons, and full cohort requalification were not all observed. |

## Focused verification

The full suite was intentionally not run. The final targeted xdist run covered
search, scientific guidance, evaluator, context, working recovery, observation
import, qualification, cache, lifecycle, finalization, bundle verification,
and visual delivery:

```text
245 passed in 402.14s (0:06:42), pytest -n 4
```

The public-contract, model-facing-asset, release-manifest, observation, and
qualification regression group also passed:

```text
73 passed in 14.92s, pytest -n 4
```

Ruff passed on the changed Python paths. The current CHAARTED Overall Survival
run used the minimal prompt:

```text
/rob2-assess Assess risk of bias for Overall Survival in CHAARTED.
```

It used Codex CLI with `gpt-5.6-luna` at medium effort and JSONL logging. The
abstract-defined Result was approved through the researcher gate. All five
Domains finalized as Low, and the resulting archive passed the independent
`scripts/verify_bundle.py` consumer. On Windows, this run used the documented
unelevated workspace-write host because strict deny-by-default isolation needs
UAC.

The retained search-work artifact is
[`search-cache-benchmark-chaarted-os.json`](search-cache-benchmark-chaarted-os.json).
It contains before/after snapshots and deltas for cold, warm-repeat, new-query,
and restart phases scoped to the CHAARTED main article.

## Historical outcome benchmark

The 28-trial Luna Medium benchmark remains historical evidence for its recorded
working-tree build and pack. It is not a replacement for requalification of
the current candidate. Trials without the requested abstract outcome were
skipped.

| Outcome | Trials | Domain exact | Domain Low vs non-Low | Overall exact | Overall binary |
| --- | ---: | ---: | ---: | ---: | ---: |
| Progression Free Survival | 10 | 72.0% | 78.0% | 0.0% | 70.0% |
| Overall Survival | 10 | 80.0% | 84.0% | 20.0% | 50.0% |
| Adverse Events | 8 | 55.0% | 62.5% | 12.5% | 87.5% |
| Combined | 28 | 70.0% | 75.7% | 10.7% | 67.9% |

“Binary” treats Some concerns and High as the same non-Low class. The detailed
trial-level report, traces, and attribution are in
[`benchmark-20260918-report.md`](../../eval/runs/benchmark-20260918-report.md).
The largest observed scientific disagreements were conservative D3 judgments,
selection-chronology mistakes in D5, adverse-event D2/D4 distinctions, and
inflated overall High labels. These results guide review; they do not establish
zero regression or promotion of #404.

## Decision

The repository implementation for #387–#403 is complete enough to merge with
focused evidence. #404 remains correctly held until its required installed-host
and cohort evidence exists. Merging this code does not turn the current smoke
test into a scientific qualification claim.
