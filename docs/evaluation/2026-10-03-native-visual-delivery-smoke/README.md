# Native visual delivery smoke

One authorized native Codex CLI turn used `gpt-6-luna`, medium, on a randomly arranged, locally generated raster-only geometric page. The fixture, private expected observations, prompt, configuration, code SHA, and image-only coverage manifest were frozen before launch. The private expectations were outside the model workspace. No clinical dossier, OCR, paid baseline, retry, continuation, or full benchmark was used.

**Result: image delivery and provenance demonstrated; strict visual correctness failed.** The actual model-facing `render_page` output contains one `input_image`, whose PNG hash matches the receipt. Receipt JSON and full schema remain model-visible text and exactly match the offline compatibility form. The answer reproduces source ID, physical page, render identity, and delivery receipt correctly. Count and leftmost object are correct. Topmost/largest colors and object location are correct, but both shape labels say rectangle rather than the frozen square; uncertainty was explicit. The frozen all-four-observations-correct criterion therefore fails. Do not convert this partial result into a pass or clinical accuracy claim.

The CLI completed normally in 16.248 seconds with two MCP calls and three provider responses within one CLI turn. Durable usage totals: 27,899 input tokens, 13,824 cached, 14,075 uncached, and 235 output tokens (zero reasoning tokens reported). No guard triggered and no overshoot occurred. Limits were five tools, 1,000 output tokens, 180 seconds wall and 60 seconds idle. Guards are reactive; input usage was telemetry rather than a cap. The exact model and effort were verified from the native turn context.

## Evidence

- `manifest.json`, `expected-private.json`, `fixture-private.json`: pre-inference freeze and private criterion.
- `evidence-manifest.json`, `launch-preflight.json`: full image identity/page/pixels/dimensions and successful pre-launch coverage check; no invented text lines.
- `original-render-wire.json`, `offline-render-wire.json`, `metadata-preservation.json`: complete normal and opt-in MCP forms. Normal entrypoint retains structured content. Compatibility entrypoint keeps all existing text/image blocks and adds complete schema text; source, page, recovery actions and receipt fields are preserved.
- `native-model-tool-forms.json`: actual native calls and model-facing outputs, including image. Only tool call/output records are exported; no credentials or encrypted reasoning.
- `events.jsonl`, `response.txt`, `run.json`, `durable-token-usage-records.json`, `effective-model.json`, `comparison.json`: raw response, usage and strict comparison.
- `run_once.py`, `cli-config.toml`, `instructions.md`, `prompt.txt`, `source.pdf`: frozen launch and supplied fixture. Paths are host-specific; these artifacts document this run, not a portable launcher.

Focused controls passed: 18 tests for compatibility metadata/image preservation, unaffected non-render/error/metadata-only paths, and image preflight identity/page/hash/dimensions/bounds/omission rejection. The opt-in behavior addresses the installed Codex structured-content preference; it does not change the standard MCP entrypoint or scientific judgments. This is evidence about the tested host/version only, with no clinical gain claim.

## Offline interpretation audit and supported integration

The original strict comparison remains unchanged. `geometry-audit.json` records a
960×720 embedded image on a 960×720 PDF page and a 1440×1080 render, with equal
1.5 scaling in both dimensions. The purple fill's thresholded pixel bounds are
220×221 (aspect ratio 0.9955); the one-pixel raster boundary difference is not an
anisotropic stretch. The source geometry is a square. A square is also a
rectangle, and neither the prompt nor frozen criterion explicitly defined
exclusive categories or required the most specific name. The answer's
“rectangle” plus “roughly square” uncertainty is less specific rather than
mathematically inconsistent. This is rubric ambiguity, not a retrospective pass.

The installed supported command is now `rob2 mcp-codex`, using the same middleware
moved into the packaged source. The old diagnostic script delegates to it.
Packaged Codex host metadata and README configuration select this command;
Claude Code and ordinary `rob2 mcp` retain their original behavior. New runner
attempts generate `["mcp-codex"]`; continuations select their saved `["mcp"]` or
`["mcp-codex"]` binding and retain the existing compatibility checks. The server
probe verifies the original full schema retained in render metadata while binding
the explicitly selected command. No user-agent or host capability inference is
used. No installed global configuration or historical run was edited.

Recommended Codex configuration after installing this branch:

```toml
[mcp_servers.rob2]
command = "rob2"
args = ["mcp-codex"]
env = { ROB2_WORKSPACE = "/absolute/path/to/assessment" }
```

Use `["mcp"]` to opt out. The observed host is `codex-cli 0.159.0`.
For future versions, verify actual native `input_image` presence, decoded PNG
hash against the receipt, and observations against private source facts before
removing compatibility mode. An MCP image return alone does not prove delivery.
This batch has no new model calls: image transport and provenance are established
by the preserved smoke; clinical comprehension or accuracy is not established.

`integration-checks.json` records offline checks and limitations. Actual stdio
catalog probes passed for both installed CLI modes; image/text/error preservation
controls and public release-contract verification passed. A source-layout archive
fixture passed the wheel-content verifier with the Codex-specific host command.
A real wheel build was not completed because this shared Python environment lacks
`hatchling`; no dependency installation was attempted. Lint and production-source
type checks passed (existing unrelated line-length findings in the benchmark
script were excluded). Initial runner mock failures from the new explicit
entrypoint argument were corrected and the affected suite passed.
