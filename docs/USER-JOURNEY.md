# Natural-language user journey

<!-- rob2-kit-contract-version: 1.0.0 -->

This is the human path through rob2-kit. You ask Codex or Claude Code to do
the work in ordinary language; the installed skills choose the bounded MCP
workflow. You never need to construct tool JSON or retain opaque identifiers.

## Install once in each assessment project

Create a project folder, put Trial materials under `input/`, then install the
locked local adapters from the frozen release:

```powershell
uv run --locked --project . rob2 bootstrap .
uv run --locked --project . rob2 doctor .
```

`doctor` is read-only. Keep its JSON receipt when it reports a problem; it
names the failed check and recovery action. Bootstrap adds only rob2-kit-owned
Codex and Claude Code entries, project-local skills, references, and runtime.

## Arrange inputs

Use one folder per Trial under `input/`. Put a readable result-bearing full
text in the relevant Trial folder. A protocol, SAP, registry export,
supplement, or later report is optional: add it when available, but do not
block a valid Result merely because an optional Source is absent.

```text
my-assessment/
├── input/
│   ├── trial-a/
│   │   ├── primary-report.pdf
│   │   └── protocol.pdf                 # optional
│   └── trial-b/
│       └── primary-report.pdf
└── output/                              # generated reports appear here
```

Use ordinary names for folders and files; they are orientation, not proof of a
Trial identity. Do not put `output/` or `.rob2/` inside `input/`.

## Ask naturally, then confirm the meaning

For one Trial and one Result, ask either Harness (Codex or Claude Code) something like:

> Assess 30-day mortality for Trial A in this rob2-kit project. Use the primary
> report and protocol if useful, then show me the final report.

For many Trials or Results, name the coverage you want:

> Prepare RoB 2 assessments for mortality in every Trial under `input/`. Treat
> all-cause death and mortality as the same outcome target only where the
> source context supports it; show each Trial-specific Result separately.

Name a synonym only when you want the proposal to evaluate whether the source
context supports that conceptual equivalence; differently defined constructs
remain separate Results unless the approved outcome-target rule includes them.

State a requested time point or window when it matters. If you do not, the
proposal explains the Trial's protocol-defined primary analysis or prespecified
primary cutoff and keeps competing landmarks visible. Ask for a correction in
plain language, for example: “Use 90-day mortality, not the 30-day analysis,”
or “Exclude Trial B because this is a different randomization.” The Harness shows
the revised proposal and its semantic difference before asking again.

Read the compact proposal: it identifies each Trial, Comparison, Result,
outcome, measurement, analysis, time point, locator, optional-Source limit,
and any material ambiguity. Confirm only when that meaning is right. Your
confirmation starts preparation; it does not approve an assessment finding.

## Follow progress and find outputs

The Harness reports meaningful milestones: proposal ready, confirmation recorded,
Trial or Result started, Domain evidence ready, a correctable blocker,
interruption, and terminal report summary. It should not expose internal token
or cursor values.

At any point, ask “What is the status of this rob2-kit assessment?” The Harness
summarizes the current Result, committed checkpoint, limitations, and safe next
step without exposing tool JSON.

Each completed Result receives a read-only static report in the Report bundle
under `output/`; the Run index links all Result reports and diagnostics. A
Result-scoped diagnostic means other Results may still continue. It explains
the missing, unreadable, conflicting, or incomplete evidence condition and its
limitation rather than inventing a judgment.

To audit a report, follow its domain sections to the cited source phrases,
provenance, visual citations where relevant, evidence coverage, decision trace,
and stated limitations. Auditing is outside rob2-kit: the report has no edit,
override, or sign-off control.

## Pause, resume, or start a new run

You can stop after a safe checkpoint. Later, say “resume the rob2-kit
assessment in this project.” The Harness resumes the sole Current run from its
durable checkpoint and tells you what is already committed.

If your next request could mean a different assessment, say explicitly “start a
new run for …”. The host will not guess from a new chat, a changed project root,
or a different outcome. Starting a new run retires the unfinished Current run
without deleting its ledger or reports. A compatible corrected input can reopen
a completed run; a changed Trial, Result, population, analysis, or time-policy
meaning needs a new proposal.

## Corrections are revisions

Do not edit a generated static report to correct it. Explain the source or
scope correction to the host and let it create a successor immutable revision.
The workflow retains the earlier assessment and invalidates only the affected
dependencies. Preserve `.rob2/` until the returned recovery action says
otherwise.

## Troubleshoot safely

| Condition | Safe action |
| --- | --- |
| Bootstrap, locked runtime, or version check fails | Keep the receipt, install the exact frozen release and `uv`, then rerun `rob2 bootstrap` followed by `rob2 doctor`. |
| A readable report cannot be parsed | Add a readable first-hand full text or follow the reported bounded recovery/visual-inspection path; do not paste reconstructed text as evidence. |
| Search or retrieval is incomplete | Let the host follow its returned scope and limitation. Do not broaden to unrelated Trials or treat no hit as no information. |
| Work is stale or a retry is requested | Let the host obtain the newly issued work context; it must not reuse a prior token or Result context. |
| A Result report cannot be materialized | Keep the Assessment checkpoint, rerun from the reported report boundary, and inspect the diagnostic; do not repeat completed evidence work. |
| Integrity or schema check fails | Stop assessment writes, preserve `.rob2/`, run `rob2 doctor`, and use only its stated migration, archive, or start-new action. |

## Maintain the installation

Every lifecycle change is preview-first. Inspect the receipt before using
`--apply`:

```powershell
uv run --locked --project . rob2 upgrade .
uv run --locked --project . rob2 upgrade --apply .
uv run --locked --project . rob2 rollback .
uv run --locked --project . rob2 rollback --apply .
uv run --locked --project . rob2 uninstall .
uv run --locked --project . rob2 uninstall --apply .
```

Upgrade creates one rollback point only after the candidate passes its checks.
Rollback and uninstall refuse changed generated content rather than deleting
ambiguous user work. If recovery is interrupted, preserve `.rob2/` and rerun a
lifecycle command; it restores the last complete transaction before continuing.
The project owner owns inputs, confirmation, and any private reports; rob2-kit
owns only manifest-recorded generated files.

## Optional local evaluation

For a hands-on Codex or Claude Code smoke and the release owner's blinded
private corpus evaluation, follow [the local runbook](LOCAL-RUNBOOK.md). It is
deliberately local, opt-in, and outside CI.
