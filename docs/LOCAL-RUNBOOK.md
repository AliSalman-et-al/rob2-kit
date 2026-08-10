# Local Codex and Claude Code runbook

This runbook is opt-in local practice, not CI and not a coded sign-off gate.
It helps an owner observe the actual installed Codex or Claude Code journey and
then perform the required private full-corpus evaluation.

## Synthetic Issue #143 baseline

The checked-in public workload is deterministic and contains no private study
material. Reproduce its frozen old-contract navigation metrics with:

```powershell
uv run pytest tests/test_issue143_scale_baseline.py -q
```

Inspect `tests/public_fixtures/issue143/scale-baseline.json` for the workload
identity, serialized-byte and provider-neutral-token estimator calibration,
candidate/universe hashes, scientific-equivalence evidence, and the
predeclared later-policy target. The target is a synthetic gate, not a
CHAARTED empirical performance claim.

For a private CHAARTED replay, use the private-corpus workflow below and record
only approved private evaluation material outside this repository. Do not copy
sources, reports, extracted evidence, or results into the public fixture.

## Smoke one installed host

The automated local orchestrator is deliberately unreachable from CI. It needs
two independent opt-ins in an owner's interactive shell and installs a named
wheel into two new projects before running either commercial host:

```powershell
$env:ROB2_LOCAL_COMMERCIAL_HOST_SMOKE = "1"
uv run --frozen python scripts/local_host_smoke.py --execute `
  --wheel C:\releases\rob2_kit-0.1.0-py3-none-any.whl `
  --workspace C:\rob2-local-smoke\candidate-0.1.0 `
  --codex-model MODEL --claude-model MODEL
```

The script never reads, copies, or serializes credentials. Codex and Claude
inherit their existing secure local login/configuration in the normal way.
Never place keys in the project, command line, or prompt. Each direction uses
one project and one Run: Codex stops at a Preparation checkpoint for Claude to
resume, then Claude stops in a fresh project for Codex to resume. The receipt
records the wheel hash, adapter/skill capabilities, host/model, latency, usage
when exposed, outcome, and bounded redacted diagnostics. Compare the two runs
only by normalized Run state, Durable run state, next actions, report inventory,
and repair count—not prose or scientific-judgment equality.

Failed projects and their partial `.rob2` state are retained by default. After
inspection, delete only a scenario directory whose `.rob2-local-host-smoke`
marker contains its exact resolved path; never recursively clean the workspace
root or an unmarked path. Pass `--cleanup-successful-projects` to remove the two
marked scenario projects after a passing comparison; the receipt is retained.

1. Create a disposable project with `input/<trial>/` and a readable
   result-bearing full text.
2. From the exact frozen release, run `uv run --frozen rob2 bootstrap
   PROJECT_ROOT` and `uv run --frozen rob2 doctor PROJECT_ROOT`.
3. Open Codex or Claude Code in that project and ask, in ordinary language, to
   assess a named Result, show the proposal, wait for confirmation, and open the
   generated static report.
4. Repeat a resume request after a safe interruption. Observe that progress,
   limitations, and a Result-scoped diagnostic are presented without asking you
   for tool JSON.
5. Keep the doctor receipt and local notes. Do not turn this smoke into a CI
   assertion or a product correctness claim.

## Evaluate the private corpus

Keep the corpus and provisional labels private. From the repository root:

```powershell
uv run --frozen python eval/workspace.py validate
uv run --frozen python eval/workspace.py list
uv run --frozen python eval/workspace.py create --trial CHAARTED --outcome "Progression-Free Survival" --host codex
```

Use a fresh generated project for each Trial/outcome and host. Run the natural
language journey without opening `eval/reference/catalog/provisional-labels/`.
After the Assessment completes, retrieve a label only for discrepancy review:

```powershell
uv run --frozen python eval/workspace.py reference --trial CHAARTED --outcome "Progression-Free Survival"
```

Record the frozen candidate wheel hash, date, host, assessor, report/evidence
review, recovery observations, and clinically material unexplained
disagreements in `release/private-release-evaluation.md`. Provisional reference
labels are comparison inputs, never an oracle. Do not commit private sources,
reports, screenshots, labels, or archives.
