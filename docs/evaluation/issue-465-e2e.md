# Issues 465–469: ENZAMET live assessment check

Run date: 2026-09-27. The case manifests and raw traces are retained under
`eval/runs/2026-09-27/issue-465-e2e/`.

Three independent workspaces received only the frozen ENZAMET source allowlist,
generated source roles, and the exported `rob2-assess` skill. Each first prompt
was exactly `/rob2-assess Assess risk of bias for {concept} in ENZAMET.` with
Overall Survival, Progression Free Survival, or Adverse Events substituted for
`{concept}`. Codex CLI 0.157.1 ran `gpt-6-luna` at `medium` effort and wrote a
JSONL trace for every phase. Continuations said only `Continue.`. The
researcher reviewed and approved each model-selected Proposal Result through
the CLI gate. No frozen expected Result or provisional label was placed in a
model workspace or used to steer a continuation.

| Request | Model-selected Result | Relation to frozen Result | Overall judgment | Phases | MCP calls | Domain submission calls |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Overall Survival | First interim OS, HR 0.67 (95% CI 0.52–0.86) | Exact | Low | 2 | 65 | 7 |
| Progression Free Survival | PSA PFS, HR 0.39 (95% CI 0.33–0.47) | Related; frozen target was clinical PFS, HR 0.40 (95% CI 0.33–0.49) | High | 2 | 102 | 6 |
| Adverse Events | Serious-event rate during treatment exposure, 0.34 versus 0.33 events/year | Component; frozen target was patients with grade 3–5 events, 321/563 versus 241/558 | High | 3 | 92 | 7 |

The model made the PFS ambiguity and the narrower AE choice explicit at Proposal
Review. AE initially stopped before proposing a Result, then selected the
serious-event component after one generic continuation. These completed bundles
show workflow completion, not exact-Result success for PFS or AE. The judgments
are the assessor's saved outputs and deterministic aggregation; this check did
not independently adjudicate their scientific correctness. No MCP tool-call
errors were recorded in the three traces. None of the runs saved a working
checkpoint, so they do not measure whether that optional context improves
reasoning.

Each finalized bundle passed both `rob2 verify` and the independent
`scripts/verify_bundle.py`. The installed v0.10 wheel also passed
`docs/release/verify.py`. On this Windows host the runner used separate
workspaces and `CODEX_HOME` directories with `workspace-write`; the strict
deny-by-default host isolation profile is unavailable without UAC. The
allowlisted Sources and generated `sources.toml` were inside each workspace,
while expected Results remained in runner metadata outside it.

These are development cases. Report provisional agreement separately from
adjudicated correctness, and retain the two scope misses when comparing future
model or effort settings.
