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
| Tool result | Structured result with pointer text | Same normalized object in structured content and compact JSON text | Yes: transport tests |
| Proposal approval | Legacy `ctx.elicit` | Input-required guard on the modern era; supported elicitation on older negotiated eras | Yes: accepted, declined, cancelled, stale and replay tests |
| Evidence delivery | One Source/page read at a time | Independent windows and source-bound passage references | Yes: in-process stdio and exact-Evidence tests |
| Recovery | Proposal Evidence only | Same-Trial uncommitted workspace plus current/prior canonical checkpoint Evidence | Yes: restart, cache-loss and Trial-isolation tests |

## Actual hosts

Checked on Windows 11 on 2026-09-06. `Produced` means the server emitted the
representation; `observed` means the named host exposed enough of it to its
model to return the synthetic marker. Protocol negotiation is `unknown` where
the host does not expose the negotiated value; it is not inferred from version.

| Host | Version | Transport | Skill path | Structured/text delivery | Image | Restart/lazy discovery | Negotiated protocol | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Codex CLI | 0.153.4 | local stdio | Project skill export supported; not loaded by the empty-workspace probe | Host trace exposed matching compact JSON text and structured content; model returned the requested empty-state fields | Not probed | Fresh startup and tool discovery passed; stateful restart not probed | Unknown | Partial |
| Claude Code | 2.1.250 | local stdio | Project skill export supported; not loaded by the empty-workspace probe | Server connected and all 14 tools were discovered, but the model call did not run because the local OAuth session was expired | Not probed | Fresh startup/discovery passed; delivery and restart not probed | Unknown | Incomplete |

The Codex probe used `get_status` once in a fresh empty workspace and observed
`success`, phase `empty`, revision `0`, and next operation `prepare_batch` in
both representations. The Claude probe incurred no model usage or cost.

The release is not scientifically qualified by this matrix. Real image
delivery, restart across Proposal Review, skill discovery, oversized marker
survival, and blinded multi-model assessment remain incomplete until recorded
with synthetic public fixtures. Server-produced output and in-process client
success do not count as host-observed delivery.
