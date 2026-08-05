# rob2-kit

> **Lean v1.** RoB 2 Kit runs one typed MCP workflow and materializes local,
> read-only static evidence reports.

Install the locked project-local Codex and Claude Code adapters, then verify the
exact execution contract:

```powershell
uv run --locked --project . rob2 bootstrap .
uv run --locked --project . rob2 doctor .
```

## Release lifecycle

Every lifecycle mutation is previewed first. Review the JSON receipt, then rerun
the same command with `--apply`; do not use `--apply` until the preview reports
compatible durable state.

```powershell
uv run --locked --project . rob2 upgrade .
uv run --locked --project . rob2 upgrade --apply .
uv run --locked --project . rob2 rollback .
uv run --locked --project . rob2 rollback --apply .
uv run --locked --project . rob2 uninstall .
uv run --locked --project . rob2 uninstall --apply .
```

An upgrade records one rollback point after its candidate passes verification.
Rollback and uninstall refuse changed generated artifacts rather than removing
ambiguous user content. If a command reports interrupted-transaction recovery
or incompatible durable state, preserve `.rob2` and follow the receipt's
recovery guidance before retrying.

Start the stdio MCP entry point from the repository root:

```powershell
uv run --locked --project . rob2-mcp
```

To declare exact Trial × Result identities before preparation begins, see
[declaring exact Results](docs/RESULT-DECLARATIONS.md).
