# rob2-kit

> **Lean v1.** RoB 2 Kit runs one typed MCP workflow and materializes local,
> read-only static evidence reports.

Install the locked project-local Codex and Claude Code adapters, then verify the
exact execution contract:

```powershell
uv run --locked --project . rob2 bootstrap .
uv run --locked --project . rob2 doctor .
```

Start the stdio MCP entry point from the repository root:

```powershell
uv run --locked --project . rob2-mcp
```

To declare exact Trial × Result identities before preparation begins, see
[declaring exact Results](docs/RESULT-DECLARATIONS.md).
