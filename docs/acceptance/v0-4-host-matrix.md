# v0.4 MCP host qualification matrix

This matrix records actual delivery probes separately from server and in-process
contract tests. Probes use an empty synthetic workspace and retain no Source
text, prompts, credentials, absolute workspace paths, or host transcripts in
the repository.

## Feature matrix

| Component | Previous | v0.4 target | Verified locally |
| --- | --- | --- | --- |
| FastMCP | 3.4.7 | 4.0.3 | Yes: locked runtime and installed-wheel release verifier |
| MCP Python SDK | 1.29.1 | 2.1.x | Yes: locked runtime |
| Tool result | Structured result with pointer text | One normalized structured object; `render_page` keeps image content | Yes: transport tests |
| Proposal approval | Legacy `ctx.elicit` | Input-required guard on the modern era; supported elicitation on older negotiated eras | Yes: accepted, declined, cancelled, stale and replay tests |
| Evidence delivery | One Source/page read at a time | Independent windows and source-bound passage references | Yes: in-process stdio and exact-Evidence tests |
| Recovery | Proposal Evidence only | Same-Trial uncommitted workspace plus current/prior canonical checkpoint Evidence | Yes: restart, cache-loss and Trial-isolation tests |

## Actual hosts

Checked on Windows 11 on 2026-09-06. `Produced` means the server emitted the
representation; `observed` means the named host exposed enough of it to its
model to return the synthetic marker. Protocol negotiation is `unknown` where
the host does not expose the negotiated value; it is not inferred from version.

| Host | Version | Transport | Skill path | Structured delivery | Image | Restart/lazy discovery | Negotiated protocol | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Codex CLI | 0.153.4 | local stdio | Project skill export supported; not loaded by the empty-workspace probe | Host trace exposed matching compact JSON text and structured content; model returned the requested empty-state fields | Not probed | Fresh startup and tool discovery passed; stateful restart not probed | Unknown | Partial |
| Claude Code | 2.1.250 | local stdio | Project skill export supported; not loaded by the empty-workspace probe | Server connected and all 14 tools were discovered, but the model call did not run because the local OAuth session was expired | Not probed | Fresh startup/discovery passed; delivery and restart not probed | Unknown | Incomplete |

Separate synthetic structured-only probe (2026-09-13): Codex CLI 0.154.0
showed the model the synthetic marker. The Claude Code 2.1.250 probe did not
run because its local OAuth session was expired; image detail was not proven.
This transport probe does not establish production accuracy.

The Codex probe used `get_status` once in a fresh empty workspace and observed
`success`, phase `empty`, revision `0`, and next operation `prepare_batch` in
both representations. The Claude probe incurred no model usage or cost.

The release is not scientifically qualified by this matrix. Real image
delivery, restart across Proposal Review, skill discovery, bounded Domain page
survival, and blinded multi-model assessment remain incomplete until recorded
with synthetic public fixtures. Server-produced output and in-process client
success do not count as host-observed delivery.

## Host rendering example

Render the one complete structured receipt. Projecting `data.questions` loses
the Result, Evidence, and recovery state.

```js
// @exec: {"max_output_tokens": 20000}
const raw = await tools.mcp__rob2__get_domain_context({
  trial_id: "trial-id-from-head.next_action",
  domain_id: "domain-id-from-head.next_action",
});
const structured = raw?.structuredContent ?? raw?.structured_content;
const receipt = structured ?? null;
if (!receipt) throw new Error("MCP receipt unavailable; delivery incomplete");
text(receipt);
```

The server auto-pages a full Domain receipt above 32 KB. Fetch every returned
`context_page.next_cursor` before deciding or saving; a pending save returns the
exact cursor to continue. Delivery completion records successful response generation
only, so verify the host-visible content and inspect Evidence as needed.

On Codex, set `functions.exec` `max_output_tokens` high enough for the measured
complete JSON object, and retry the identical scoped call with a larger value
after `Warning: truncated output`. Keep explicit Trial, Domain, and page/window
scope arguments applicable to that tool unchanged on every retry: Trial and
Domain for context, or source and page/window ranges for reads. If the cap
persists, use smaller exact page windows or lossless section rendering while
preserving the same fields. Inspect the rendered output for truncation; a JSON
parse alone does not prove complete host delivery. Keep the full receipt,
including `head`, `data.result`, `questions`, `comparison_cards`, `evidence`,
`evidence_workspace`, and recovery fields.
For `render_page`, keep image content blocks separate from deduplicated JSON and
render/inspect the image when layout carries meaning.
If the server returns `domain_context_header_oversized` or
`domain_context_item_oversized`, retry the same Trial/Domain scope with the
reported larger `required_page_size`; an unrecoverable condition requires
review without omitting the record.

Pass `context_page.next_cursor` unchanged. When the host supports variables,
reuse the returned value directly instead of retyping an opaque cursor. If it
is invalid, recapture the preceding page and reuse its exact cursor; if stale,
restart the initial scoped call with the same Trial, Domain, page size, and D3
preview when used. On a continuation condition or error, preserve the stored
cursor and advance or clear it only after a successful `context_page` response.
Never assess page zero while continuation remains.

Existing cursors preserve the original context snapshot across Evidence work at
the same revision. Inspect subsequent tool responses for updates; Evidence work
alone does not require re-traversal. A fresh no-cursor request may replace the
snapshot; finish any returned pages before saving.

In the Kalil r81 baseline replay, six Domain-context responses measured
88–123 KB as the raw MCP envelope and 43–61 KB as the then-used structured
representation. These pre-single-payload measurements are byte replay data,
not token counts or accuracy gains. The recovery run's
full Codex host rollout carried `Warning: truncated output` for Domain results,
although its phase JSONL retained the prior representations. No post-fix LLM
run has been made.
