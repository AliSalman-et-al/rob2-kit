# Prior art on tool-surface and continuation-token design: Pi and oh-my-pi

## Scope

This note investigates external agent-harness prior art to inform two open
issues on the rob2-kit MCP server's tool design:

- **#149** — responses repeat large static content (guidance text, source
  lists) across calls, and error messages describe failure categories
  without naming the specific offending field/value.
- **#150** — `WorkToken` exposes 6+ model-visible, individually-editable
  fields (`token`, `run_id`, `work_item_id`, `operation`,
  `dependency_fingerprint`, plus optional `trial_id`/`result_id`/`domain_id`)
  that the agent must copy back verbatim on every mutating call, even though
  `dependency_fingerprint` is provably just `SHA256(run_id|key|operation)`
  with no server-side secret. The working hypothesis is that this should
  collapse to a single opaque string, matching `proposal_token` elsewhere in
  the same codebase.

It focuses on two minimal/extended terminal coding-agent harnesses — Pi
(`earendil-works/pi`) and its fork oh-my-pi (`can1357/oh-my-pi`) — as
concrete examples of tool-surface design under real model-facing constraints,
plus first-party MCP transport-spec text on opaque session identifiers.
Every claim below is sourced to a primary artifact (README, source file, or
spec page) fetched directly from the given repository or `modelcontextprotocol.io`,
not to a blog or secondary summary. Where no primary-source evidence was
found for a specific point, that is stated explicitly rather than guessed.

## Findings

### Pi's core tool surface

Verified from `earendil-works/pi`, file
[`packages/coding-agent/src/core/tools/index.ts`](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/index.ts)
(fetched via `gh api repos/earendil-works/pi/contents/...`, 2026-08-09).

Pi ships seven named tool implementations in total —
`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls` (see
`export type ToolName = "read" | "bash" | "edit" | "write" | "grep" | "find" | "ls"`
and `allToolNames`). However, the function `createCodingToolDefinitions`
(the harness's default "coding" preset) wires up exactly four:

```ts
export function createCodingToolDefinitions(cwd: string, options?: ToolsOptions): ToolDef[] {
	return [
		createReadToolDefinition(cwd, options?.read),
		createBashToolDefinition(cwd, options?.bash),
		createEditToolDefinition(cwd, options?.edit),
		createWriteToolDefinition(cwd, options?.write),
	];
}
```

This **confirms** the secondhand "4-tool core: Read/Write/Edit/Bash" claim,
with the caveat that it is specifically the default *coding* preset, not the
full tool inventory — `grep`/`find`/`ls` form a separate `createReadOnlyToolDefinitions`
preset, and all seven are always available to compose.

Pi's `edit` tool (`packages/coding-agent/src/core/tools/edit.ts`) uses plain
`oldText`/`newText` exact-string matching per edit — no content-hash anchor,
no continuation/session token of any kind appears in its input schema. The
README (`earendil-works/pi/README.md`) states Pi "does not include a
built-in permission system" by default and recommends external
containerization; it says nothing about continuation-token design, because
its core tool set is stateless request/response per call — there is no
concept comparable to rob2-kit's `WorkToken` in vanilla Pi at all.

Actionable implications for rob2-kit:

- Pi's own default preset treats 4 tools as the practical minimum for a
  capable coding agent; rob2-kit's 12-tool surface is not unusual for a
  domain-specific multi-step workflow (Pi's full inventory is 7, oh-my-pi's
  is 31 — tool count is not itself evidence rob2-kit's surface is too large).
  This does not bear on #149/#150 directly but is useful calibration if tool
  count is ever raised as a concern.
- Pi's `edit` schema shows a useful negative example for #149: the tool
  *description* embeds the correctness-critical constraint ("must be unique
  in the original file and must not overlap with any other edits[].oldText")
  directly in the field's `Field`/`Type.String({description})` rather than
  in prose elsewhere — reinforcing mcp-agent-friction.md's "put the callable
  contract in the schema" recommendation already tracked for rob2-kit.

### oh-my-pi's unified-interface and hash-anchoring philosophy

Verified from `can1357/oh-my-pi/README.md` (fetched via `gh api
repos/can1357/oh-my-pi/readme`, 2026-08-09) and
`can1357/oh-my-pi/packages/hashline/README.md`.

**Unified interfaces ("GitHub is just another filesystem").** The README's
own stated reasoning (section "12 · GitHub is just another filesystem"):

> "Other harnesses bolt on `gh_issue_view`, `gh_pr_view`, `gh_search` — each
> with its own parameters the agent has to learn and you have to debug. We
> skipped that. `read` already handles paths; PRs are paths. One interface
> to teach the model, one surface to keep correct."

This is confirmed further in section 17: `read pr://1428` returns "the same
shape as `read src/foo.ts`", and the README enumerates 16 internal URI
schemes (`pr://`, `issue://`, `agent://`, `skill://`, `ssh://`, etc.) that
resolve transparently inside "every FS-shaped tool the agent already calls."
The stated design goal is explicitly reducing the number of *distinct
parameter shapes* the model must learn, not reducing the number of tools for
its own sake — a scheme-prefixed opaque string (`pr://1428`) substitutes for
what would otherwise be a structured `{owner, repo, number}` argument object.

**Hash-anchored edits ("Hashline").** From `packages/hashline/README.md`:

> "Hashline is a diff format designed for LLM-driven file edits. It binds
> every hunk to a file-content hash so stale anchors are rejected before
> they corrupt code... Each file section starts with `[PATH#TAG]`. The tag
> is a 4-hex content hash of the full normalized file text recorded by the
> `SnapshotStore`, and it is not meaningful outside that store."

Concretely, the model emits `[hello.ts#a1b2]` — path plus a bare 4-hex-digit
opaque tag — not a structured object with named fields for the file path,
hash algorithm, timestamp, etc. The tag is meaningless outside the
server-side `SnapshotStore` that minted it (directly analogous to an opaque
continuation reference: the client carries an unexplained short token, the
server does the lookup). The top-level README frames the payoff in token/reliability
terms, not just correctness: "Grok 4 Fast spends 61% fewer output tokens on
the same work" attributed to anchors replacing full-text retyping and
eliminating "string-not-found loops."

Actionable implications for rob2-kit:

- The unified-interface pattern (`pr://1428` as a single opaque-ish string
  standing in for a structured identifier) is a direct, verified precedent
  for collapsing a multi-field reference into one string the model treats as
  a black box, matching the shape of the WorkToken-collapse hypothesis —
  though it addresses tool *count/surface* reduction, not specifically
  mutation-authorization state, so treat it as supporting analogy rather
  than a proof.
- Hashline's tag design is the closest verified real-world analogue to
  `dependency_fingerprint`: both are hashes used purely for staleness
  detection (reject an operation against content that has changed since the
  reference was issued), not for cryptographic authorization. Hashline
  deliberately keeps that hash *short* (4 hex chars) and *opaque* to the
  model, embedded inline in the edit syntax, and never asks the model to
  supply or reconstruct the algorithm's inputs. This is evidence against
  exposing `dependency_fingerprint`'s inputs (`run_id|key|operation`) to the
  model as separate editable fields, since oh-my-pi's own design explicitly
  avoids that shape for a same-purpose mechanism.

### Continuation/reference-token design in these harnesses

Honest finding: **neither Pi nor oh-my-pi has a tool-call-level continuation
token directly analogous to `WorkToken`.** Both are interactive, single-process
terminal agents whose "state" lives in an in-memory/on-disk session object the
harness itself manages — the model is not asked to round-trip a
work-identity object between tool calls the way an MCP server must, because
Pi/oh-my-pi tool calls are not going through a stateless network boundary
back to a separate server process the way rob2-kit's MCP tools do. This is a
structural difference, not just a design choice, and should be stated
plainly rather than stretched into a false equivalence.

The closest adjacent patterns, both already covered above, are:
1. Hashline's `[PATH#TAG]` — an inline opaque staleness-check reference
   (same *function* as `dependency_fingerprint`, different granularity: a
   single 4-hex tag rather than a fingerprint plus a parallel structured
   `WorkToken` wrapper).
2. oh-my-pi's `--resume` / on-disk sessions and `agent://<id>/findings.0.path`
   addressing (README section "Shell completions" and "05 · First-class
   subagents") — sessions and subagent outputs are addressed by a bare `id`
   string used as a path segment, not a structured object. No primary-source
   text was found describing the internal shape of that session `id` (e.g.
   whether it embeds a hash or is a random UUID) — this is stated as
   unverified rather than assumed.

Actionable implications for rob2-kit:

- Do not claim Pi/oh-my-pi "solve" the multi-step-MCP-continuation problem
  rob2-kit has — they don't have it in the same form, because they aren't
  stateless-RPC-to-a-separate-server systems. The supporting evidence for
  collapsing `WorkToken` has to come from the *function* match (staleness
  hash, opaque reference) in Hashline and from MCP's own session-ID
  convention (next section), not from a false "Pi does this exact thing"
  claim.
- Every reference/continuation identifier surfaced in either harness's
  model-facing surface, without exception, is a single opaque value (a
  4-hex tag, a scheme-prefixed URI, a bare session/agent id) — none is a
  structured multi-field object the model must reconstruct or edit. That
  consistency, across two independently-designed systems, is itself weak
  but real supporting evidence for the WorkToken hypothesis.

### MCP/Anthropic first-party guidance on opaque tokens

Verified from `modelcontextprotocol.io/specification/2025-11-25/basic/transports`
(fetched 2026-08-09), section "Session Management":

> "A server using the Streamable HTTP transport MAY assign a session ID at
> initialization time, by including it in an `MCP-Session-Id` header... The
> session ID SHOULD be globally unique and cryptographically secure (e.g., a
> securely generated UUID, a JWT, or a cryptographic hash). The session ID
> MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E)."

This is MCP's own general-purpose recommended pattern for *any* stateful
multi-step session over Streamable HTTP — not the `tools/list` pagination
cursor already cited in `mcp-agent-friction.md`, but a separate,
protocol-level mechanism for exactly the "carry continuation state across
calls" problem `WorkToken` is solving. It is unambiguously a **single opaque
string** value, carried in one HTTP header on every subsequent request,
never decomposed into named sub-fields for the client to inspect or edit.
The spec explicitly permits the server to construct that string as "a
cryptographic hash," i.e. the same category of value as
`dependency_fingerprint`, and still requires it be transported as one
undifferentiated string.

No equivalent explicit general-purpose recommendation ("use opaque tokens for
stateful multi-step tool workflows broadly, not just pagination or HTTP
session IDs") was found stated as a standalone principle in the MCP tools
specification (`2025-11-25/server/tools`) itself — the tools spec (already
cited in `mcp-agent-friction.md`) covers `inputSchema`/`outputSchema` and
structured content, but does not separately editorialize about token
opacity for tool-call arguments. The generalization from "pagination
cursors are opaque" + "session IDs are opaque" to "continuation tokens for
stateful tool-call sequences should be opaque" is drawn by this note, not
asserted verbatim by the spec — flagged here so it isn't mistaken for a
direct quote.

Actionable implications for rob2-kit:

- MCP's own transport layer treats a stateful continuation reference,
  including one that MAY be "a cryptographic hash," as a single opaque
  string end-to-end. This is the strongest first-party precedent available
  for collapsing `WorkToken` to one string: the protocol rob2-kit is built
  on already does this for its own session concept, at the exact point
  (client-must-echo-back-a-server-issued-reference) that `WorkToken`
  occupies.
  - Reasonable design borrow: mint one opaque `work_token` string
    server-side (may internally encode/hash `run_id`, `work_item_id`,
    `operation`, and the dependency fingerprint), return it from
    `prepare_run`/`continue_run`, and require every mutating call to send it
    back unexamined — matching both `proposal_token`'s existing shape and
    MCP's own `MCP-Session-Id` convention.
  - If any of the currently-separate fields (`trial_id`, `result_id`,
    `domain_id`) are needed by the *model* to decide what to submit next
    (not just by the server to validate the submission), keep those as
    separate, genuinely-informative fields in the response body — but do not
    ask the model to copy them back into the next request if the token
    already encodes them server-side.

## Closing note

The research **supports** the #150 hypothesis that `WorkToken` should
collapse to a single opaque string, but on narrower grounds than "everyone
does it this way":

1. Neither Pi nor oh-my-pi has a directly analogous mechanism to grade
   against, because neither is a stateless-RPC-to-a-separate-server system
   the way rob2-kit's MCP tools are — that comparison had to be made
   honestly rather than forced.
2. oh-my-pi's Hashline `[PATH#TAG]` anchor is the closest functional
   analogue found (a staleness-detection hash, not a cryptographic secret,
   exposed to the model as a short opaque value embedded inline rather than
   as a structured object) and is consistent with collapsing
   `dependency_fingerprint`'s role into an opaque token.
3. The decisive first-party evidence is MCP's own `MCP-Session-Id` transport
   convention: a protocol-level, general-purpose (not pagination-specific)
   stateful continuation reference that MAY be "a cryptographic hash" and
   MUST be carried as one opaque string, never as named sub-fields. Since
   rob2-kit's `WorkToken` occupies exactly this role (a server-issued,
   client-echoed continuation reference for a stateful multi-step
   interaction) and MCP's own spec already establishes the opaque-string
   convention for that role, `WorkToken` collapsing to a single string is
   the more spec-consistent design, not just a stylistic preference
   borrowed from `proposal_token`.

Nothing found in either harness or the MCP transport spec argues *for*
keeping `dependency_fingerprint` and the identifier fields separately
editable; the field-level exposure in the current `WorkToken` design has no
supporting precedent in any primary source reviewed here.
