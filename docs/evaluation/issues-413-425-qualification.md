# Issues #413–#425 qualification decision

Date: 22 September 2026

## Decision

**Hold promotion and leave issues #413–#425 open.** The implementation candidate
passes its repository gates and the three-case diagnostic completes, but #424's
qualification evidence is not complete. Promotion still requires supported-host
transcripts, a trial-separated evaluation across at least two model families or
materially different supported hosts, and independent scientific adjudication.

The frozen #423 cohort remains a baseline, not corrected ground truth. It contains
28 assessments, 140 Domain cells, 93 catalog matches, and 47 disagreements. Reviewer
classifications, provenance, and the prespecified agreement sample remain pending.

## Issue status

| Issue | Implementation | Remaining qualification evidence |
|---|---|---|
| #413 | Integrated evidence-access and premise-reasoning repairs are present. | Program-level closure depends on #424. |
| #414–#417 | Complete in code and focused tests. | No known implementation gap. |
| #418 | Stable context pages, cursors, compact deltas, and recovery are implemented. | Supported-host delivery and compaction transcript. |
| #419 | Host assertions and server-validated provenance are separated. | No known implementation gap. |
| #420 | D3 availability, mitigation, and missingness mechanisms are separated. | Independent adjudication of scientific disagreements. |
| #421 | D4 method, differential measurement, awareness, possibility, and likelihood are separated. | Supported-host exercise. |
| #422 | Exact Result scope, working-premise invalidation, and safe reuse are implemented. | Supported-host restart exercise. |
| #423 | Frozen cohort/importer and leakage checks are implemented. | Independent reviewers and agreement-sample review. |
| #424 | Qualification machinery and this decision record are implemented. | Required paired multi-host/model evaluation and adjudication. |
| #425 | D5 plan applicability, chronology, eligible alternatives, and result-based selection are separated. | Supported-host and independently adjudicated evidence. |

## Generalized boundary and context changes

- Renamed the misleading public `page_size` input to `max_response_bytes`, with
  byte-based bounds and recovery metadata.
- Removed caller-supplied reasoning identities from save operations. Saves now
  consume the unique validated draft for the returned revision and scope.
- Kept `estimate` as one point-estimate string and normalized common structured
  precision objects into a canonical string at the boundary.
- Allowed a missing-data event definition without inventing an event count.
- Moved plausible copied Evidence/search-handle typos past the Pydantic shape
  gate so the application can return a scoped unknown-handle repair.
- Corrected proposal Evidence repair codes and paths for unknown, cross-Trial,
  and counterevidence references.
- Tightened tool descriptions and examples around complete typed requests,
  visual Evidence ownership, response envelopes, and continuation.
- Simplified the portable skill, removed repeated legacy prose, and made its
  examples preserve the complete MCP response envelope.

The scientific question cards now make three Cochrane inference gates explicit:

1. D2.3 needs both a protocol-inconsistent change and a trial-context cause;
   subsequent treatment or crossover alone is insufficient.
2. D3.1 needs affirmative evidence for all/nearly-all availability and negative
   evidence for materially incomplete availability; unresolved extent is `NI`.
3. D5.3 needs evidence that selection among eligible analyses likely depended on
   results; multiplicity alone is insufficient.

These rules are generic. They do not name a model, trial, intervention, effect
size, or expected label.

## Three-case Overall Survival diagnostic

The reproducible random sample is bound in
`eval/reference/catalog/os-random-20260921.tsv`. Effect sizes came from each
main article abstract. Every run used Codex CLI `gpt-5.6-luna` at medium effort,
the minimal `/rob2-assess` prompt, a separate workspace and `CODEX_HOME`, and a
complete JSONL trace.

| Trial | Abstract effect | Final D1–D5 | Overall |
|---|---|---|---|
| GETUG-AFU-15 | HR 1.01; 95% CI 0.75–1.36 | L, L, L, L, S | Some concerns |
| ARASENS | HR 0.68; 95% CI 0.57–0.80; P<0.001 | L, L, H, L, L | High |
| CHAARTED | HR 0.61; 95% CI 0.47–0.80; P<0.001 | L, L, L, L, L | Low |

The final diagnostic is under
`eval/runs/22-Sep-26/os-random-luna-medium-20260922-current/`. All three bundles
pass the independent verifier. The catalog labels are provisional and were not
shown to the model. GETUG and CHAARTED match them. ARASENS differs in D3 because
the captured report did not establish outcome availability beyond the analysis
set and generic censoring rule; the corrected card preserved `NI` rather than
turning missing proof into an adverse fact. Independent adjudication is required
before classifying that disagreement as a model or reference error.

Earlier attempts remain under the dated run directories. They exposed and
preserve the bugs that motivated the generalized fixes; no best retry is selected
for an accuracy claim. The prior `verified` run self-repaired three copied-handle
Pydantic errors. The boundary now routes those plausible shapes to typed,
scope-aware application repairs. The exact current-code run completed with zero
failed MCP calls across all six JSONL phases.

Windows on this host provides separate workspace isolation with the unelevated
`workspace-write` sandbox, not the strict deny-by-default host isolation required
for promotion. WSL, Docker, and Podman were unavailable. This diagnostic must not
be represented as strict-host qualification.

## Verification

The final recorded gates are:

```text
ruff check .: passed
ty check: passed
git diff --check: passed (line-ending warnings only)
focused contract, scientific-guidance, repair, and release tests: passed
three finalized diagnostic bundles: independently verified
pytest: 785 passed, 2 skipped in 885.01s (0:14:45)
```

## Evidence still required for promotion

1. Capture supported-host delivery, continuation, compaction, restart, premise
   recovery, and review transcripts without answer coaching.
2. Run the prespecified trial-separated paired conditions on at least two model
   families or materially different supported hosts.
3. Independently adjudicate every material disagreement and the agreement sample,
   retaining reviewer identity, uncertainty, rationale, and version.
4. Report scientific and operational measures separately: label agreement,
   premise support, counterevidence handling, scope correctness, completion,
   errors, context bytes, calls, latency, and cost.
5. Revisit promotion using those observations and record gains, regressions,
   uncertainty, and residual failures.
