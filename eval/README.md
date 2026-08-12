# Private evaluation workspace

This directory supports hands-on rob2-kit evaluation with real randomized
controlled trial materials. Source PDFs, provisional labels, and generated
projects remain local and are ignored by Git.

## Layout

```text
eval/
├── README.md
├── workspace.py
├── reference/                         # private, ignored
│   ├── catalog/
│   │   ├── trials.csv
│   │   └── provisional-labels/
│   │       ├── adverse-events.csv
│   │       ├── overall-survival.csv
│   │       └── progression-free-survival.csv
│   └── sources/
│       └── <TRIAL>/
│           ├── primary/
│           └── supplements/
└── runs/                              # generated, ignored
    └── <timestamp>-<host>-<trial>-<outcome>/
        ├── eval-run.yaml
        ├── input/
        ├── output/
        └── .rob2/                     # appears after initialization
```

`reference/` is the private evaluation corpus. `runs/` contains disposable,
independent rob2-kit projects. Never place provisional labels inside a run:
the preparing agent must not see the comparison label before completing its
Assessment.

## Validate and inspect the corpus

From the repository root:

```powershell
uv run --frozen python eval/workspace.py validate
uv run --frozen python eval/workspace.py list
```

The `list` command reports which Trial/outcome combinations can be materialized
without printing provisional judgments.

## Create a fresh project for Codex

```powershell
uv run --frozen python eval/workspace.py create `
  --trial CHAARTED `
  --outcome "Progression-Free Survival" `
  --host codex
```

The command prints the new project root and the exact initialization command.
Then ask Codex:

> Use rob2-kit to prepare the requested Result in the newly created evaluation
> run. Do not inspect `eval/reference/catalog/provisional-labels/` until the
> Assessment is complete. Open the generated static report bundle when it is
> available.

Each evaluation should use a fresh run so ledger state and report artifacts
from earlier tests cannot influence it.

## Compare after completion

Only after the Assessment is complete:

```powershell
uv run --frozen python eval/workspace.py reference `
  --trial CHAARTED `
  --outcome "Progression-Free Survival"
```

These CSV judgments are **Provisional reference labels**, not correctness
oracles. Their assessor provenance, evidence, rationale, and adjudication method
are incomplete. Use them for discrepancy review, not automatic pass/fail.

## Privacy rules

- Do not commit or redistribute anything below `eval/reference/`.
- Do not attach private PDFs, filenames, extracted text, or provisional labels
  to public CI fixtures or release evidence.
- Do not copy provisional labels into `eval/runs/`.
- Reports, screenshots, and Verification archives derived from private sources
  remain private unless their distribution rights are established separately.
