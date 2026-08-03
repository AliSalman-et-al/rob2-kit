# RoB 2 Kit lean v1

RoB 2 Kit is a local, evidence-grounded assessment engine for individually
randomized parallel-group trials and the effect of assignment to intervention.
It is operated through the canonical Codex or Claude Code skills, which call a
local stdio MCP server.

## Public workflow

The sole assessment path is one typed `RunEngine` workflow. A Harness prepares
or resumes a Current run, obtains the required one-time confirmation, performs
only engine-issued work items, and receives one static report bundle or scoped
diagnostic report for every requested Result. The engine retains durable
Workflow-ledger state and materializes reports atomically.

The command-line interface exposes only `bootstrap` and `doctor`. The
`rob2-mcp` entry point is a stdio launcher, not a second interactive workflow.
There is no browser service, manual assessment command, review queue, report
editing, correction flow, override, sign-off record, or compatibility gateway.

## Boundary and dependencies

Host adapters and the CLI are thin interfaces. They depend on typed
application contracts and `RunEngine`; application and domain code never
depends on an interface. The release ships only the dependencies required for
the engine, MCP transport, static reports, archives, source acquisition, and
bounded visual work.

## Reports and verification

A Report bundle is a local, read-only human-audit projection. It includes a
Run index, one Result or diagnostic report per requested Result, visual assets,
and a Verification archive. Assessment revisions and the Workflow ledger remain
authoritative; reports never accept state changes.

Evidence claims, canonical source spans, visual citations, coverage receipts,
Decision traces, and stated limitations remain attributable and reproducible.
An unresolved material evidence or coverage condition produces a diagnostic
report rather than an invented judgment.
