# rob2-kit

The greenfield RoB 2 Kit is a model-free FastMCP server. Codex or Claude Code is
the only model loop; this initial skeleton exposes an empty current-batch resource
and packages the portable workflow instructions for both hosts.

Install the wheel, register `rob2-mcp` as a stdio MCP server in the host, and copy
the two directories under `rob2_kit/skills` from the installed distribution into
that host's skill directory. The installed `rob2_kit/hosts` metadata names the two
hosts and the common skill location. No generated skill copies are shipped.

```powershell
python -m build
python -m pip install dist/rob2_kit-0.1.0-py3-none-any.whl
rob2-mcp
```

`rob2://current-batch` currently returns `{"active_batch": null}`. Scientific
workflow, persistence, and RoB 2 logic are intentionally deferred to later issues.
