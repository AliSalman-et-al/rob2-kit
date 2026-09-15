# Recursive assessment improvement

Use this development loop for one trial and one approved Result at a time. It is
diagnostic work, separate from release qualification and its held-out score.
The [evaluation contract](README.md) defines the observation limits.

1. Rank assessed rows by **D1–D5** agreement, then choose a failure with a
   testable mechanism. Keep all outcomes from the same trial in one development
   or holdout partition. An overall judgment is not the optimization target.
2. Freeze the prompt, dossier bytes, registry capture, approved Result scope,
   model/version, reasoning effort, tool and skill revision, and evaluation
   rule. Describe the source allowlist and scope in a frozen `rob2-kit.rsi-case.v1`
   JSON manifest. Each source entry names one relative path, its assessment
   filename, and role. A captured registry entry also records its original
   capture time, SHA-256, and provenance. Start an empty run directory. Use
   `scripts/run_rsi_case.py` with `--case`, `--prompt`, `--run-dir`, and
   `--phase 1`. The runner constructs a new workspace from only those listed
   source bytes and generated intake metadata; it never copies a prior workspace.
   It records the original registry capture identity and a separate replay time.
   The directory contains its own copied input, exported skill, Codex session
   store, metadata, full CLI JSONL and stderr. The runner removes the temporary
   auth copy after each phase. For qualification, add
   `--require-isolated-host`; this creates a deny-by-default Codex permission
   profile with write access only to the run workspace, run artifacts, and the
   MCP runtime. This strict profile is unavailable on Windows: the runner rejects
   it before creating artifacts rather than starting an elevated backend or
   triggering UAC. Ordinary Windows evals explicitly use `approval_policy =
   "never"`, `sandbox_mode = "workspace-write"`, and
   `windows.sandbox = "unelevated"`; that prevents prompts while preserving
   workspace write access, but it does not prove deny-by-default label isolation.
   Keep raw traces restricted because they contain source text and host-visible
   agent messages or justifications.

   The case manifest has this shape; source paths resolve relative to the
   manifest and only listed files enter `workspace/input`:

   ```json
   {
     "schema": "rob2-kit.rsi-case.v1",
     "trial": "TRIAL-A",
     "requested_outcome": "Progression-Free Survival",
     "approved_scope": "abstract-based Result scope reviewed for this case",
     "sources": [
       {"path": "sources/main.pdf", "name": "main-article.pdf", "role": "main_article"}
     ],
     "registry_capture": {
       "path": "captures/registry.json",
       "registry_id": "NCT01234567",
       "captured_at": "2026-08-01T12:30:00Z",
       "sha256": "<lowercase SHA-256 of the original bytes>",
       "provenance": "captured response retained from baseline"
     }
   }
   ```

   `registry_capture` may be omitted when no captured registry record exists.
   Its stored bytes are replayed as a local Source; no network lookup is made.
   When a replay has an authoritative `registry_id`, the runner writes a
   `[registry]` declaration into the fresh workspace. Intake validates the
   retained response against that NCT and projects it as the same
   `registry/NCT...json` Source used for a live capture. The JSON projection is
   deterministic sorted leaf paths on one line-addressable page, so search,
   reads, navigation, and Evidence selection use the ordinary public seams.
   A manifest below `eval/runs` or `eval/reference` may point to another
   retained file under the same `eval` root. The preparer rejects paths outside
   that root and never copies an unlisted file.
3. At Proposal Review, inspect the exact Result mapping. Approve only the
   intended source-reported Result through the supported researcher gate. For
   subsequent phases, rerun the script with the same run directory and an unused
   `--phase N`, using `--session` from the prior JSONL and a file containing
   `Continue.`. If phase 1 used `--require-isolated-host`, repeat that flag on
   every continuation; the runner records the requirement and rejects a
   downgrade. The runner rejects a reused phase before touching its trace,
   metadata, stderr, or last-message file, so failed attempts remain available
   for diagnosis; use the next phase number or a fresh run directory for a retry.
   It checks the isolated `rob2 status` before starting a paid continuation and stops
   if the researcher Proposal Review is still pending; acknowledge that exact
   Review with the researcher-only `rob2 review` command first. Keep the full
   Codex session rollout with the phase traces: it retains encrypted reasoning
   records and exposed agent messages or justifications, while the phase JSONL
   alone is not the complete host rollout. Neither artifact exposes readable
   model reasoning or a complete raw chain of thought. Use a new run directory
   for the intervention; never reuse an assessment workspace.
4. Audit the actual host-visible trace, committed Evidence, question premises,
   and final bundle. Distinguish retrieved, surfaced, delivered, selected,
   cited, and premise-supporting material. For a Codex host probe, unwrap one
   `structured_content`/`structuredContent` receipt (or parse its one JSON text
   fallback) before rendering it. Set `functions.exec` `max_output_tokens` high
   enough for the complete object and retry the same call when the host reports
   `Warning: truncated output`; record the measured structured/text byte sizes.
   Keep `head`, `result`, `questions`, `comparison_cards`, Evidence, and
   recovery fields together. A tool receipt does not establish model attention.
   Compare the five domains and class-specific errors against the reference;
   record scientifically defensible disagreements separately.
5. Make one generalized change supported by a bounded mechanism test. Rerun
   the same frozen case with the same budget. Check newly broken controls as
   well as recovered failures. A one-draw label change is a diagnostic signal,
   not evidence of population-level accuracy gain.
6. Commit and push a reviewed change only after focused tests and direct
   artifact verification. Keep its issue open if the trial-separated,
   multi-model promotion gate remains untested. Move to the next failure case.
   After three completed cycles, create one focused pull request and squash
   merge it into `main` once checks and review pass.

The first three cycles may share a branch, but each intervention needs its own
fresh assessment workspace and trace. If corpus bytes, registry capture, Result
mapping, or host behavior differ, record that difference and do not attribute
the resulting score delta solely to the kit. Reserve untouched trials and
document families for independent evaluation. Avoid tuning a rule to a trial
name, reference label, or one model's preferred phrasing.

## Verified Luna smoke test

The following command was run against the frozen CHAARTED qualification case
for Progression-Free Survival:

```powershell
uv run --no-project python scripts/run_rsi_case.py `
  --case eval/reference/qualification-cases/CHAARTED.json `
  --prompt eval/runs/qualification-pfs/prompt.txt `
  --run-dir eval/runs/verification-chaarted-pfs-luna-medium `
  --phase 1 --model gpt-5.6-luna --effort medium
```

After the Proposal Review was approved with `rob2 review`, the same session
continued with a `Continue.` prompt. The run finalized CHAARTED across all five
Domains and `scripts/verify_bundle.py` accepted the resulting archive. The
trace had semantic repairs where evidence or Result wording was incomplete,
but no Pydantic or tool-schema error loop. This single run validates the
workflow plumbing; it is not a release qualification score or a scientific
accuracy estimate.

## Posthoc run analysis

Keep labels, scope adjudications, and failure-cause annotations out of every
model-facing prompt, workspace, and continuation. Freeze the run outputs first;
then prepare a restricted JSON sidecar with one row per expected run. Do not
select a best retry. For the first wave, use one uncoached run per eligible
Trial/outcome and retain incomplete and failed runs. Use distinct `case_id`
values for separate draws; repeated draws remain separate rows and are never
collapsed to each case's best result.

The input uses `rob2-kit.rsi-run-analysis.v1`. Labels use `low`,
`some_concerns`, and `high`; `D1` through `D5` follow the order in the retained
reference. Eligible cases require all five adjudicated labels. `scope_uncertain`
and `ineligible` cases are reported separately and excluded from agreement
denominators. Omit absent model outputs from `observed`; they still count in the
all-expected denominator. A minimal posthoc record is:

```json
{
  "schema": "rob2-kit.rsi-run-analysis.v1",
  "cases": [
    {
      "case_id": "run-a-trial-1",
      "trial_id": "trial-1",
      "outcome": "PFS",
      "scope": "eligible",
      "completion": "finalized",
      "expected": {
        "D1": "low", "D2": "some_concerns", "D3": "low",
        "D4": "some_concerns", "D5": "low"
      },
      "observed": {
        "D1": "low", "D2": "high", "D3": "low",
        "D4": "some_concerns", "D5": "low"
      },
      "cost_usd": null,
      "failure_causes": {"D2": "delivery_unknown"}
    }
  ]
}
```

Run the analyzer only after the run records and posthoc annotations are frozen:

```powershell
uv run python scripts/analyze_rsi_runs.py eval/restricted/rsi-wave.json --output eval/restricted/rsi-analysis.json
```

It reports per-Domain and pooled three-class exact agreement and binary Low vs
non-Low agreement, confusion matrices, false positives/negatives, ordinal
overcalls/undercalls, completion, missing-output and all-expected denominators,
and known versus unavailable run cost. It computes deterministic percentile
intervals by resampling whole Trials, so Domains and repeated draws from one
Trial stay clustered. With fewer than two Trial clusters, an interval is
unavailable. High-class sensitivity is `null` and explicitly marked
unestimable when no reference High cases exist; predicted High counts and the
High confusion-matrix cells remain visible.

Failure causes are posthoc review annotations, not inferred from agreement or
tool-call counts. Use `passage_not_found` when the needed passage was not
discovered in the captured Sources, `passage_not_delivered` when it was useful
but absent from the delivered context, `citation_incomplete` when delivered
material was cited incompletely, and `interpretation_error` when the complete
passage was cited but interpreted incorrectly. Use `delivery_unknown` when the
trace cannot establish delivery. `workflow_incomplete`, `scope_error`,
`infrastructure`, and `other` cover distinct remaining explanations. An
unannotated missing or incorrect Domain output is counted as
`delivery_unknown`; do not silently infer absence from a truncated or missing
trace. Scope-uncertain comparisons stay out of scored results and are counted
separately. These provisional-label metrics are not estimates of scientific
accuracy, and a single draw does not support reliability or pass-at-k claims.
