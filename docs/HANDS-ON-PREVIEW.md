# Hands-on preview gate

This repository is a **draft-only hands-on preview**, not a public-v1 release.
Generated reports remain preview artifacts even after a human signs an exact
Assessment revision. Agents cannot sign.

## Start the pinned project

From the repository root on Windows:

```powershell
uv run --locked --project . rob2 doctor
uv run --locked --project . rob2-mcp
```

The committed `uv.lock` is the dependency pin. `--locked` fails instead of
changing an absent or outdated lockfile. The generated Codex and Claude adapter
descriptors in `adapters/` carry the same MCP launcher and explicitly require
the host to start it with the repository root as its working directory.

## Gate record

Do not mark the preview gate passed until every row has dated evidence. On the
owner's machine, use the private `ARASENS` Overall Survival entry in
`eval/reference/manifest.csv` as the same hands-on fixture Trial and use a fresh
project copy for each host. Its CSV judgment is a Provisional reference label,
not a correctness oracle. The private PDFs must not be copied into distributable
fixtures or committed.

| Check | Required evidence |
|---|---|
| Codex on Windows | Host/version, adapter hash, start transcript, completed Assessment revision |
| Claude Code on Windows | Host/version, adapter hash, start transcript, completed Assessment revision |
| Cross-host equivalence | Matching normalized submissions, judgments, and ledger consequences |
| Evidence review | Reviewer screenshot or notes showing exact source evidence in the GUI |
| Human-only sign-off | Rejected agent sign-off plus human sign-off bound to the exact revision/hash |
| Resume | Status before close, status after host/browser restart, and matching ledger cursor/progress |
| Preservation | Verified complete archive or a copied-project migration/recovery transcript |
| Owner critical flow | Dated owner outcome and any blocker or dangerous misunderstanding |
| Small lab trial | Dated participants, blocker/dangerous-misunderstanding findings, and retest evidence |

Formal accessibility audit, broad usability research, validation research, and
cosmetic polish are outside this preview gate. Minor friction should be filed
as follow-up work. A critical blocker or dangerous misunderstanding keeps the
gate open until it is fixed and the affected checks are repeated.

## Automated supporting checks

Run:

```powershell
uv run pytest
uv run ty check
uv run ruff check .
```

These checks support the gate but do not substitute for the two real-host runs,
owner completion, or lab feedback.
