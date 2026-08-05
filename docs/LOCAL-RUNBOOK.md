# Local Codex and Claude Code runbook

This runbook is opt-in local practice, not CI and not a coded sign-off gate.
It helps an owner observe the actual installed Codex or Claude Code journey and
then perform the required private full-corpus evaluation.

## Smoke one installed host

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
