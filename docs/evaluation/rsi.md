# Recursive assessment improvement

Use this development loop for one trial and one approved Result at a time. It is
diagnostic work, separate from release qualification and its held-out score.
The [evaluation contract](README.md) defines the observation limits.

## Frozen development comparisons (v0.3)

Use `rob2-kit.evaluation-comparisons.v0.3` for controlled development
comparisons. Its closed arms add `fact_binding` (`none` or
`scope_matched_facts`) and `review` (`baseline` or `targeted_warrant`). Each
pair declares one factor, and validation rejects arms that differ on another
factor. The required pairs compare one common baseline with supplied decisive
passages, scope-matched facts, compact context, and targeted warrant review.
Labels and answers remain forbidden in every evidence policy. Fact tables must
give source-linked facts, counterevidence, and unknowns without a RoB answer or
an evaluative conclusion.

The versioned plan freezes kit, scientific-pack, skill, tool-schema, prompt,
Source, and exact Result identities. It declares at least two distinct draw
IDs for each arm/case cell. Every draw gets an independent assessment session;
an attempt may link to its predecessor only when that predecessor failed for
infrastructure reasons. The paired comparison uses the terminal attempt under
that fixed rule. Unrun planned draws are emitted as `missing`, and labels can
be attached only to cases declared scope eligible. Scope-uncertain and
ineligible cases remain visible but cannot enter provisional-label scores.

[`development-comparison-v0.3.example.json`](development-comparison-v0.3.example.json)
is a one-case ARASENS PFS D3 template with two repeated draws and all four
required contrasts. Its zero digests and CLI version text are placeholders;
replace them with hashes of the exact run inputs before using it. It is an
example only, not an observed model comparison. Use only the existing ten
Trials as development material; they have already informed the audit and do
not form a held-out set.

The example is a plan template. Before launch, replace its placeholder hashes
and create an inputs sidecar with one row per selected intervention/case pair
(two rows per planned case):

```json
{
  "schema": "rob2-kit.development-comparison-inputs.v1",
  "runs": [
    {
      "intervention_id": "iv-baseline",
      "case_id": "ARASENS-pfs-D3",
      "case_file": "cases/baseline-arasens.json",
      "prompt_file": "prompt.txt"
    },
    {
      "intervention_id": "iv-passages",
      "case_id": "ARASENS-pfs-D3",
      "case_file": "cases/passages-arasens.json",
      "prompt_file": "prompt.txt"
    }
  ]
}
```

Paths are relative to the sidecar. Both case manifests must match the planned
Trial and outcome, and every prompt must match `plan.host.prompt_identity`.
Do not put labels, adjudications, or answer keys in case manifests, Source
files, or prompts. The launcher records Source digests and requires shared
Sources to have identical bytes across arms. After each runner phase, it also
checks that `run-inputs.json` records those exact digests and that the same
bytes exist in the isolated `workspace/input` directory.

For launcher preflight, each case's `result_identity` is the SHA-256 digest of
its `expected_result` object serialized as canonical JSON (sorted keys and
compact separators), with the `sha256:` prefix. This is a fingerprint of the
planned target scope; it is not the canonical identity of the approved Result
record. The case's `source_identity` is the digest of a canonical JSON array
containing each baseline Source's `name`, `role`, and raw SHA-256 digest,
sorted by name, with the `sha256:` prefix. A captured registry is included as
`registry.json` with role `registry`; arm-specific additions are excluded. The
launcher checks both digests against the materialized case and source bytes. A
`scope-matched-facts.json` treatment Source must sit beside its case manifest
inside the frozen comparison inputs; baseline Sources remain confined to the
declared trial source directory.

Run a preflight first, then remove `--dry-run` to launch one frozen pair. The
launcher supports `evidence_exposure` and `fact_binding`; make one launch per
pair. Each launch runs the declared baseline and treatment arms across every
case and draw:

```powershell
uv run python scripts/run_development_comparison.py `
  --config eval/runs/development-comparison/config.json `
  --interventions eval/runs/development-comparison/interventions.json `
  --inputs eval/runs/development-comparison/inputs.json `
  --campaign-dir eval/runs/development-comparison/campaign `
  --factor fact_binding `
  --dry-run
```

For `evidence_exposure`, the treatment adds its declared decisive-passage
Sources. For `fact_binding`, it adds exactly one
`scope-matched-facts.json` Source with this closed structure:

```json
{
  "schema": "rob2-kit.scope-matched-facts.v1",
  "trial_id": "ARASENS",
  "outcome_id": "Progression-Free Survival",
  "result_identity": "sha256:<frozen Result identity>",
  "facts": [
    {
      "domain_id": "domain:missing",
      "question_id": "<planned question identifier>",
      "statement": "A source-linked fact stated without a risk-of-bias conclusion.",
      "source_name": "main-article.pdf",
      "locator": "Table 1, row 4"
    }
  ],
  "counterevidence": [],
  "unknowns": []
}
```

Each fact, counterexample, and unknown is bound to a planned Domain and cites
one of the common baseline Sources. The schema rejects answer fields and
checks the Trial/Result identity; it cannot determine whether free-text
statements contain a conclusion. Have a reviewer inspect that content before
launch. The extra Source's byte-for-byte presence is observable and recorded
as **available**. Whether the model read the Source, bound facts to the right
questions, or reasoned from them remains **unknown**. Do not interpret this
pair as an enforced or successful fact-use intervention.

The v0.3 plan also declares compact context and targeted warrant review, but
the current runner has no control that can change context without changing the
task inputs, and normal assessment review is mandatory with no treatment
switch. Those pairs remain excluded and unsupported in `launch.json`; no
condition delivery or effect should be inferred for them. Thus these launches
cover the observable Source-availability contrasts only and do not complete
all #463 conditions.

The launcher pins GPT-6 Luna Medium from the plan, requires deny-by-default
host isolation, and starts one phase-one `run_rsi_case.py` process in a fresh
directory for each selected arm/case/draw. It retains every JSONL trace,
launcher stdout/stderr, and source materialization result; it does not load
labels. It rechecks case, prompt, Source, and runner bytes before each draw.
The launch manifest also preserves host, model, and artifact identities copied
from the plan as declared values; it does not claim that these match observed
runtime identities. Phase one commonly stops at Proposal Review, so its exit
is not necessarily a completed assessment.

After inspecting and explicitly approving each Proposal Review with the
researcher-only `rob2 review` command, continue the same campaign with the
same frozen config and sidecars:

```powershell
uv run python scripts/run_development_comparison.py `
  --config eval/runs/development-comparison/config.json `
  --interventions eval/runs/development-comparison/interventions.json `
  --inputs eval/runs/development-comparison/inputs.json `
  --campaign-dir eval/runs/development-comparison/campaign `
  --factor fact_binding `
  --continue-approved
```

The continuation command selects only executions whose durable state is
`waiting_for_user`. It reuses each original run directory and Codex session,
and sends the fixed `Continue.` prompt recorded in `launch.json`; it does not
approve a Proposal Review. The runner checks the workspace's actual researcher
gate before starting each paid continuation and exits if review is still
pending. If a later phase reaches another researcher gate, approve it manually
and invoke the same continuation command again. The launcher retains each
continuation phase's JSONL and logs alongside phase one. Never change a case,
prompt, Source, runner, plan, or intervention sidecar between launch and
continuation.

Normalize the launch and runner records mechanically. The normalizer retains
every runner attempt and retry, extracts an overall judgment only from a
bundle that it independently verifies, and writes the scorer's JSON list plus
a separate restricted provenance report:

```powershell
uv run python scripts/normalize_development_comparison.py `
  --launch eval/runs/development-comparison/campaign/launch.json `
  --outcomes eval/restricted/development-comparison/outcomes.json `
  --provenance eval/restricted/development-comparison/normalization.json
```

The `outcomes.json` passed to the scorer contains one row per attempt,
including failed attempts and infrastructure retries. A minimal row is:

```json
{
  "attempt_id": "baseline-draw-1",
  "arm_id": "baseline",
  "cell_id": "ARASENS-pfs-D3",
  "draw_id": "draw-1",
  "session_id": "sha256:<hash of observed host session or null>",
  "status": "assessed",
  "prediction": "low",
  "support": "full",
  "completion": true,
  "latency_ms": 120000,
  "cost": null,
  "context_bytes": null,
  "tool_calls": null
}
```

Latency is the sum of runner phase durations when both timestamps are present.
This runner does not expose cost, actual model context bytes, or MCP call
counts to the normalizer, so those values stay null. `normalization.json`
records source/trace/bundle provenance, independently verified artifacts,
attempt states, and measurement coverage. Missing session IDs stay null and
cannot be treated as independent-session evidence. The scorer reports known
measurement totals with observed/unknown counts and marks a budget check
unverified when data is missing. A fact Source's availability is separately
reported from unknown fact uptake or binding correctness.

The scorer keeps retries and selects the terminal row under the frozen retry
rule. Once every planned run or missing draw is recorded, score the frozen
wave with:

```powershell
uv run python scripts/run_comparison.py `
  --config eval/runs/development-comparison/config.json `
  --interventions eval/runs/development-comparison/interventions.json `
  --outcomes eval/restricted/development-comparison/outcomes.json `
  --labels eval/restricted/development-comparison/provisional-labels.json `
  --output eval/restricted/development-comparison/receipt.json
```

`scripts/run_comparison.py` validates and scores retained outcomes. The v0.3 receipt preserves every attempt, planned
draw row (including missing draws), scope status, both assessed-only and
all-planned provisional-label denominators, and each baseline-paired contrast.
Its `evidence_status` labels recorded outcomes as observations, deterministic
schema checks as static contracts, and any explanation of a score difference
as a hypothesis. The receipt stores a digest of the label sidecar, not its
contents, and calls its metric provisional-label agreement; a paired change is
not an accuracy estimate or a causal mechanism finding. Preserve historical
provisional scores as separate input/output artifacts instead of replacing
them with any later interpretation.

## Predeclared retrieval comparisons

The existing held-out manifest may include a `comparison_config` with schema
`rob2-kit.evaluation-comparisons.v0.1`. It declares named arms and diagnostic
pairs before runs begin, using only these dimensions: `free_search` or
`supplied_decisive_evidence`; `porter_only` or `optional_spelling`; and
`baseline`, `compact`, or `expanded` context with neutral guidance variants.
The supplied-Evidence arm may provide complete relevant passages, but its
policy must explicitly forbid labels and answers. The manifest validator
rejects undeclared interventions, duplicate arms/pairs, coaching fields, and
non-diagnostic pairs. Observation manifests additionally require an explicit,
independent session per comparison arm; missing or unrun attempts remain
`unknown`/incomplete.

An executable comparison also declares a closed `plan` object. `cases` names
the exact Trial, outcome, and Domains; `host` freezes the provider, interface,
version, and prompt identity; `model` freezes family, version, and effort;
`retry_policy` permits only bounded infrastructure retries; `scoring` names the
primary metric and separate support, completion, latency, cost, and optional
class-recall metrics; and `budget` limits attempts, cost, context bytes, and
tool calls. `scripts/run_comparison.py` rejects an outcome file without this
plan, retains every attempt, and does not select a winning retry. Historical
configs without a plan remain readable for manifest compatibility, but they are
not executable comparison runs.

These comparisons reuse the normal attempt attribution and evidence-stage
metrics. Evidence recovery, premise support, scientific labels, completion,
latency, and cost remain separate measures. Supplied Evidence is diagnostic of
the combined discovery/context burden, not production accuracy or a model
ceiling, and no candidate cohort is implied by declaring the configuration.

1. Rank assessed rows by **D1–D5** agreement, then choose a failure with a
   testable mechanism. Keep all outcomes from the same trial in one development
   or holdout partition. An overall judgment is not the optimization target.
2. Freeze the prompt, dossier bytes, registry capture, approved Result scope,
   model/version, reasoning effort, tool and skill revision, and evaluation
   rule. The overall Trial label uses the deterministic Cochrane convention:
   all five Low is Low; one Some concerns and no High is Some concerns; any
   High or at least two Some concerns is High. Describe the source allowlist
   and scope in a frozen `rob2-kit.rsi-case.v1`
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
   MCP runtime. The strict profile is unavailable on Windows without UAC and fails
   explicitly before a run is created. Ordinary Windows runs use
   `approval_policy = "on-request"` with `approvals_reviewer = "auto_review"`,
   plus `sandbox_mode = "workspace-write"` and
   `windows.sandbox = "unelevated"`; this permits required MCP mutations
   without interactive UAC prompts but does not prove deny-by-default label
   isolation. Keep raw traces restricted because they contain source text and
   host-visible agent messages or justifications.

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
reference. Eligible cases contribute one operational expected output for each
Domain, while `reference_available` records whether that Domain has an
adjudicated label and `scope_comparable` records whether the observed Result
has the same approved scope. A missing reference or non-comparable scope is
reported and excluded from the scored denominator; it is not converted into a
missing model output. `scope_uncertain` and `ineligible` cases are reported
separately and excluded from agreement denominators. Omit absent model outputs
from `observed`; they still count in operational expected and all-expected
denominators. A minimal posthoc record is:

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

It reports per-Domain, pooled, and per-outcome three-class exact agreement and
binary Low vs non-Low agreement, confusion matrices, false
positives/negatives, ordinal overcalls/undercalls, operational expected
outputs, reference-labelled opportunities, observed outputs, comparable
pairs, completion, missing-output and all-expected denominators, and known
versus unavailable cost and latency. It computes deterministic percentile
intervals by resampling whole Trials, so Domains and repeated draws from one
Trial stay clustered. With fewer than two Trial clusters, an interval is
unavailable. High-class sensitivity is `null` and explicitly marked
unestimable when no reference High cases exist; predicted High counts and the
High confusion-matrix cells remain visible.

When a case has retries, every attempt contributes to attempt count, cost,
latency, and failure accounting. Only the explicitly selected attempt (or the
documented first-attempt fallback) contributes observed labels to the scored
comparison; the analyzer never chooses a best retry. The diagnostic ledger
retains attempt identities and the earliest supported stage, and distinguishes
an unresolved cause from a defensible agreement. These joins are diagnostic
metadata, not model-facing input.

Optional expert adjudications are stored as immutable sidecars under a case's
`adjudication.json` or `adjudications/*.json`. Each sidecar is bound to the
verified run, Result, current Domain checkpoint, question, Source identities,
and model label before collection. The analyzer reports adjudication classes
separately from provisional-label agreement; they never rewrite scores or act
as model-facing feedback.

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
