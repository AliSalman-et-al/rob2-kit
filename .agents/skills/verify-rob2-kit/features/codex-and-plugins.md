# Codex entrypoint and plugin install

Codex prefers a tool's structured content over its content blocks, so it drops
rendered page images. `rob2 mcp-codex` advertises `render_page` without an
output schema and returns the receipt as text beside the PNG. The Claude Code
and Codex plugins install the skill and launch the server with `uvx`.

## Sub-features

- `codex-render`: `render_page` over `mcp-codex` returns no structured content. Its blocks are the receipt text, the PNG and the schema text, and the receipt works with `select_visual_evidence`.
- `claude-plugin`: `.claude-plugin/plugin.json` runs `uvx --from ${CLAUDE_PLUGIN_ROOT} rob2 mcp` and loads the skills from `src/rob2_kit/skills/`.
- `codex-plugin`: `.codex-plugin/plugin.json` and `mcp.json` run `uvx --from git+...@v<version> rob2 mcp-codex`.
- `marketplace`: one `.claude-plugin/marketplace.json` serves both hosts.

## How to get to it (user POV)

- Claude Code: `/plugin marketplace add AliSalman-et-al/rob2-kit`, then `/plugin install rob2-kit@rob2-kit`.
- Codex: `codex plugin marketplace add AliSalman-et-al/rob2-kit`, then `codex plugin add rob2-kit@rob2-kit`.

## Driving it with the e2e Agent

Preconditions: the doctor passes, and `claude` and `codex` are on PATH for the plugin checks.

- **Codex render.** Run `drive.py codex-render`. `outcome.json` shows `advertised_output_schema: null`, `structured_content: null`, three content blocks and a visual evidence handle, and `page-2.png` is written.
- **Claude plugin, live.** Follow the Plugin packaging section of [../SKILL.md](../SKILL.md). `get_status` returns phase `empty` with `next_action.operation == "prepare_batch"`.
- **Codex plugin, install.** Use a throwaway `CODEX_HOME`. `codex mcp list` shows `rob2` with the tagged `mcp-codex` command.
- **Validation.** `claude plugin validate .` passes.

## Gotchas

- The first `uvx` launch builds the package and can outlast the host's MCP startup wait. Retry once.
- The Codex plugin needs the git tag `v<version>` to exist. `tests/test_plugin_manifests.py` keeps the tag pin and versions in step.
- A local-path Codex marketplace install copies the entire checkout, including `.venv`.
