# Offline discovery and delivery boundary fix

No inference or model request was made. Runtime scientific schemas, evidence, guards and thresholds are unchanged. The focused change is in the repository-owned single-probe launcher, using a supported Codex CLI setting rather than another verbal prohibition.

## Exact ownership

The first recorded model call was `ALL_TOOLS.filter(x => /rob2|domain_context|save_domain_judgment/i.test(x.name+" "+x.description)); text(a)`. `ALL_TOOLS` is installed by Codex's `install_globals` / `build_all_tools_array` in [runtime/globals.rs at rust-v0.159.0](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/code-mode-runtime/src/runtime/globals.rs). Its descriptions are built from tool definitions with generated TypeScript declarations. The server supplies MCP names, descriptions and JSON schemas through FastMCP `tools/list`; it does not implement the JavaScript catalog or decide what the model prints. Replacing server discovery with a new compact catalog would not change the harness-owned `ALL_TOOLS`, and hiding schemas there would repeat the previous schema defect.

The server returned a complete native `get_domain_context` response of 55,449 serialized bytes, with a single complete context page and no next cursor, after the model explicitly requested 131,072 bytes. The model then printed the response with `functions.exec` max_output_tokens=8000. The actual tool output reports original 13,866 tokens and truncation. There was no model-written slice operation and no hard MCP transport loss. Codex's [handle_runtime_response / truncate_code_mode_result](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/core/src/tools/code_mode/mod.rs) applies this output budget after the tool result is emitted. The server cannot detect which portions were clipped downstream; a completed server page does not establish complete model reading.

## Controlled structural change

`run_domain_probe.py` now forces this isolated CLI configuration:

```toml
[features.code_mode]
enabled = true
direct_only_tool_namespaces = ["mcp__rob2"]
```

The official [0.159.0 configuration schema](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/core/config.schema.json) describes direct-only namespaces as bypassing deferral, remaining direct in code-mode-only sessions, and being omitted from nested code mode. [spec_plan.rs](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/core/src/tools/spec_plan.rs) applies DirectModelOnly, excludes those tools when registering code-mode executors, and retains their ordinary specifications. Codex's [namespace normalization](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/codex-mcp/src/tools.rs) gives server rob2 the namespace mcp__rob2; all nine selected tools belong to it. Upstream tests explicitly cover direct-only visibility in code-mode-only sessions. This prevents rob2 definitions from entering ALL_TOOLS rather than changing its formatting.

An offline `codex app-server --strict-config` initialize + config/read exchange accepted the setting on the installed 0.159.0 binary. It returned model gpt-6-luna, enabled code mode with direct_only_tool_namespaces=[mcp__rob2], approval_policy=never and sandbox_mode=read-only. No thread/turn or inference request was started. `codex features --strict-config` was not a valid validation route and was rejected without inference; the app-server config read supplied actual validation. No model cache override, model substitution, permission bypass or unsupported binary modification is involved.

The launcher retains all nine enabled tools and full typed input schemas. It does not create a names-only discovery API or replace them with unknown arguments. Those schemas total 30,018 compact JSON bytes; [exact selected schemas](selected-input-schemas.json) are recorded. Direct exposure incurs schema input cost, so this is not a claim that discovery is free or that total model usage is lower. It removes the demonstrated 38,283-byte *additional printed* catalog and code-mode result clipping path for rob2 calls. Native direct-client truncation remains a separate boundary; no paid model trace verifies it here.

The redundant prompt discovery/clipping instructions were removed. The guard section retains scientific uncertainty and continuation requirements. Existing history and diagnostic preparations are untouched; new preparation must use the current prompt/guard identity. The launcher still validates the frozen clean checkout, exact Luna Medium settings and existing approved guards, runs one invocation, and stops on success or first guard.

## Lossless offline delivery replay

[scripts/replay_domain_probe_delivery.py](../../../scripts/replay_domain_probe_delivery.py) replays the exact recorded native context through the existing 32,768-byte default pagination. It yields four pages of 28,684, 11,662, 9,652 and 11,367 bytes. Reassembly equals every original scientific data field exactly, including questions, evidence, comparison cards, guidance, Result, recovery information and uncertainties; every page retains stable recovery and next-cursor semantics. No evidence or required schema was deleted, abbreviated or manually restaged. [Replay result](context-replay.json).

Twenty-two focused tests passed: control drift and every guard, direct launcher model/access preservation, exact recorded context reassembly, and complete nested MCP input schema/repair behavior. Ruff and ty pass. No broad tests, full benchmark or paid retries ran. This does not prove that the model will choose default pagination, submit a scientifically sound judgment, or complete under 400k input; it establishes a supported way around the reproducible catalog/exec clipping mechanism at the controlled harness-configuration layer. No core server pagination rewrite is justified by this trace.
