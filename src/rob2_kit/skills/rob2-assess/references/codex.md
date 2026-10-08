# Codex receipt snippets

Use these snippets only when `functions.exec` renders each host output separately.
The shared receipt and pagination rules live in [Receipt and continuation recovery](evidence.md#receipt-and-continuation-recovery).
Keep each result's `isError` flag beside `content` when structured content is
absent. Treat the flag as transport status, not as scientific evidence.

## Finish a pending host call

When `functions.exec` returns `Script running with cell ID ...`, the awaited
MCP call is still running. Use `functions.wait` with that exact cell ID until
the call completes. An empty wait interval is not an intake failure or evidence
that no Sources exist. PDF capture can take several minutes, especially for
long protocols. Do not launch another `prepare_batch`, terminate the cell, or
end the turn while that call is pending merely because several waits were empty.
If the host returns a terminal error or timeout, inspect it and recover through
`get_status` before retrying; a completed capture may already have committed.

## Inspect a receipt or error

```javascript
// @exec: {"max_output_tokens": 20000}
const status = await tools.mcp__rob2__get_status();
const head = status?.structuredContent?.head;
if (!head?.next_action || head.next_action.operation !== "get_domain_context") {
  text(status?.structuredContent ?? status?.content ?? []);
  throw new Error("get_status did not return a get_domain_context action");
}
const r = await tools.mcp__rob2__get_domain_context({
  trial_id: head.next_action.trial_id,
  domain_id: head.next_action.domain_id,
});
text({ isError: r?.isError ?? false, payload: r?.structuredContent ?? r?.content ?? [] });
```

## Store the first cursor

```javascript
const r = await tools.mcp__rob2__get_domain_context({ trial_id, domain_id });
const page = r?.structuredContent ?? null;
text({ isError: r?.isError ?? false, payload: page ?? r?.content ?? [] });
if (page?.outcome === "success") {
  store(`domain-next-cursor:${trial_id}:${domain_id}`, page.data?.context_page?.next_cursor ?? null);
}
```

## Pass a cursor

```javascript
const cursor = load(`domain-next-cursor:${trial_id}:${domain_id}`);
const r = await tools.mcp__rob2__get_domain_context({ cursor });
const page = r?.structuredContent ?? null;
text({ isError: r?.isError ?? false, payload: page ?? r?.content ?? [] });
if (page?.outcome === "success") {
  store(`domain-next-cursor:${trial_id}:${domain_id}`, page.data?.context_page?.next_cursor ?? null);
}
```
