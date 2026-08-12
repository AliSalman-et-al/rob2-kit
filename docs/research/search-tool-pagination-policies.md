# Search-tool pagination policies for agent harnesses and rob2-kit

## Scope

This note investigates how current agent harnesses bound search and other large
tool results, then evaluates which patterns fit rob2-kit's evidence-search
contract. The comparison uses first-party source code, repository documentation,
and protocol specifications. It focuses on result sizing, truncation,
continuation, caller control, and model-context cost.

rob2-kit is not ordinary code search. A selected query may contribute to an
auditable Search coverage receipt, so every result must remain reachable in a
stable order and completion must be reproducible. Convenience-search behavior
that silently drops the tail is therefore evidence about context ergonomics,
not a policy rob2-kit can copy wholesale.

## Current rob2-kit contract and mismatch

`CONTEXT.md` defines an **Evidence result page** as a snapshot-bound,
policy-bounded page constrained by candidate count and estimated model tokens.
It requires declared omissions and an exact continuation action, and assigns
numeric limits to a versioned Evidence-search policy.

The current implementation is narrower than that domain contract:

- `SearchPolicy` fixes both `page_hit_target` and its maximum at 20, and fixes
  `page_character_target` and its maximum at 8,000 characters.
- Page construction greedily stops at either bound, but its character count is
  source-unit text only. It does not estimate the complete serialized response,
  including repeated unit metadata, projections, handles, warnings, and page
  metadata.
- The first page reports unique hits, scoped units, Source distribution, omitted
  characters, and whether a continuation exists, but not the deterministic
  number of pages or remaining search calls under the active policy.
- The broad-query flag uses a whole-scope ratio. It can therefore miss a query
  that is expensive within one long Source but small relative to a multi-trial
  index.

Issue #143 is consequently not just a request to raise a magic number. It is a
request to make the implementation honor the existing policy vocabulary while
preserving bounded, complete traversal.

## Primary-source findings

### OhMyPi: cap model-facing output and spill the complete artifact

OhMyPi exposes general tool-output controls rather than an auditable search-page
protocol. Its official settings define a per-line output cap and an artifact
spill threshold; when output spills, bounded head and tail portions remain
inline. The same settings document gives `read` a default line limit of 300.
These controls acknowledge that the relevant budget is the complete
model-facing tool result, not just the underlying source text.
[OhMyPi settings](https://github.com/can1357/oh-my-pi/blob/main/docs/settings.md)

OhMyPi also reduced the default per-line search/grep cap from 1,024 to 512
characters specifically to keep minified lines from consuming excessive model
context. This is a useful example of calibrating presentation cost from observed
agent workloads.
[OhMyPi releases](https://github.com/can1357/oh-my-pi/releases)

The transferable lessons are:

- budget the rendered tool result, including structural overhead;
- retain a hard pathological-item cap even when aggregate output is bounded;
- preserve complete material outside the inline response when possible; and
- calibrate limits from observed harness behavior.

Artifact spill is not a substitute for rob2-kit's continuation protocol. A
generic transcript artifact is not automatically snapshot-bound, query-bound,
ordered, or eligible for a Search coverage receipt.

### OpenCode grep: fixed top-N truncation with an explicit narrowing hint

OpenCode's current `grep` tool runs ripgrep with a limit of 100 matches. Its
response records a `truncated` boolean, says when more matches are available,
and advises the model to use a more specific path or pattern. It does not expose
a continuation cursor for the omitted grep matches.
[OpenCode grep source](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/grep.ts)

This is a sensible contract for exploratory code search: cap the common case,
make truncation unmistakable, and teach the caller how to narrow. It is not
sufficient for rob2-kit because an omitted result cannot silently become
unreachable when full traversal is part of procedural search adequacy.

The transferable part is the response ergonomics: state the applied bound,
state that more results exist, and give a concrete recovery action. The
non-transferable part is irreversible top-N truncation.

### OpenCode CodeMode: explicit pagination plus host-owned execution budgets

OpenCode's CodeMode tool-catalog search accepts `limit` and `offset`, returns a
`next` object that can be spread into the subsequent request, and documents
pagination as the normal way to continue discovery. CodeMode separately exposes
execution limits for wall time, tool-call count, and model-facing output bytes;
the host is responsible for selecting those limits or handling truncation.
[OpenCode CodeMode documentation](https://github.com/anomalyco/opencode/blob/dev/packages/codemode/README.md)

Two patterns matter for rob2-kit:

1. Search continuation and overall execution budgets are separate concerns.
2. Output bytes/tool calls are first-class resource measures, rather than an
   accidental consequence of a hit count.

The caller-selected `limit` and transparent numeric `offset` do not transfer
cleanly. rob2-kit already has stronger replay and authorization requirements;
an opaque cursor bound to the snapshot, query, scope, and policy is safer than a
caller-edited offset, and engine-owned bounds prevent agents from trading away
context safety.

### MCP: server-selected pages and opaque continuation

The MCP pagination specification uses an opaque cursor supplied by the server.
Clients must not assume its format, and the server may choose page size. The
cursor appears only when more results remain.
[MCP pagination specification](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination)

MCP's standard pagination applies to protocol list operations, not directly to
domain-specific tool results. Nevertheless, its ownership boundary matches
rob2-kit's needs: the server controls page construction and the caller returns
an opaque continuation unchanged.

### Prior Pi/OhMyPi research in this repository

The existing `docs/research/pi-harness-tool-design-lessons.md` establishes a
broader pattern in Pi and OhMyPi: model-facing references tend to be compact and
opaque, and correctness-critical constraints belong in the callable interface.
That supports retaining an opaque continuation rather than exposing pagination
internals, but it does not establish an exhaustive search-coverage design; those
harnesses do not have rob2-kit's scientific freeze gate.

## What transfers to rob2-kit

The primary sources converge on five useful practices:

1. **Bound the whole model-facing response.** Text characters alone are an
   incomplete proxy because per-hit metadata can dominate short matches.
2. **Keep a hard item ceiling.** A token/byte estimator can be imperfect, so a
   candidate-count ceiling remains a defense against pathological structures.
3. **Declare truncation and the next action.** The response should say which
   bound fired and how much work remains.
4. **Keep continuation server-owned and opaque.** The caller should refine
   semantics, not manipulate pagination state.
5. **Calibrate against real traces.** Fixed limits are policy choices to be
   evaluated, versioned, and changed—not scientific constants.

Three common harness practices must not be copied:

- top-N truncation with no way to retrieve the tail;
- artifact spill that is not bound to the search snapshot and audit record; and
- caller-selected numeric limits that can weaken the evidence-coverage
  procedure.

## Recommended policy for rob2-kit

### 1. Use dual engine-owned page bounds

Replace the current fixed 20-hit target as the ordinary stopping rule with a
deterministic estimate of the **complete serialized SearchPage cost**. The
versioned policy should contain:

- a target for estimated model-facing tokens or a conservative byte-derived
  proxy;
- a hard maximum serialized-byte allowance;
- a hard maximum candidate count; and
- explicit handling for one indivisible oversized candidate.

The candidate maximum remains a safety ceiling, not the normal page size. The
estimator must include hit text, repeated identifiers and provenance, preview
and projection fields, warnings, handles, and page-level metadata. It need not
predict every provider tokenizer exactly; it must be deterministic, versioned,
conservative, and calibrated against measured fixture tokens.

### 2. Pack each page deterministically

After stable filtering, deduplication, and diversification, greedily take the
largest ordered prefix that fits all active bounds. Apply the same algorithm to
every page. Bind its policy identity into the cursor and coverage receipt.

This permits short candidates to batch more densely without allowing long or
metadata-heavy candidates to overflow context. It also preserves deterministic
page membership and replay.

### 3. Report exact traversal cost under the active snapshot and policy

Because the search implementation already materializes and orders the complete
matching row set before slicing a page, it can simulate the same deterministic
packing algorithm over the remainder. Prefer exact fields over a vague
estimate:

- `page_number`;
- `total_page_count`;
- `remaining_page_count`;
- `returned_candidate_count` and `remaining_candidate_count`;
- `estimated_response_tokens` and/or `serialized_bytes` for the current page;
- `limiting_bounds` such as `token_budget`, `byte_ceiling`,
  `candidate_ceiling`, or `oversized_candidate`; and
- the existing opaque `next_cursor`.

If implementation constraints make the page count approximate, name the field
and its uncertainty honestly. With the current in-memory ordered result set,
however, exact page count should be achievable.

### 4. Define broadness by traversal cost, with Source diagnostics

Whole-index hit fraction is poorly aligned with the observed failure. Make the
primary broad-query signal a versioned projected-page or projected-token-cost
threshold. Retain per-Source hit distribution and add per-Source scoped
fractions as diagnostics so callers can see which Source makes the query broad.

This directly targets the agent cost that #143 describes while avoiding a rule
that behaves differently merely because unrelated Trials were added to the
index.

### 5. Keep caller control semantic

Do not expose `page_hit_target`, token budget, byte budget, or offset to the MCP
caller. Continue accepting semantic refinements such as terms, phrases, Source
scope, and page scope. Return the engine's applied policy identity and bounds so
the behavior is transparent and auditable.

### 6. Coordinate with query supersession

Issue #153 is a prerequisite for cost-aware narrowing to save work. If the first
page shows that a query is too broad, the caller must be able to select a
replacement query for that signaling-question pass without being required to
finish the abandoned query. The receipt should retain the abandoned attempt for
audit, while completion should require full traversal only for the explicitly
selected query in each mandatory pass.

Do not merge #143 and #153: pagination policy and query-selection semantics are
different mechanisms with different acceptance tests. Deliver them in an order
that makes the cost signal actionable.

### 7. Do not add server-side automatic full traversal

An internal “traverse all remaining pages” loop would hide model-facing cost and
could recreate unbounded tool results. Keep one bounded page per call. Smarter
packing reduces unnecessary round trips without removing caller-visible control
over how much context is consumed.

## Measurable acceptance criteria

Before choosing numeric budgets, capture the current policy's performance on
the existing public fixtures and the CHAARTED PFS generalized-workflow replay.
Then version the new fixture budgets. At minimum, test that:

1. Identical snapshot, scope, query, and policy inputs produce identical page
   membership, ordering, page counts, bound reasons, and replayed receipt
   content; only intentionally opaque issued handles may differ.
2. Every ordinary page stays within the configured serialized-byte ceiling,
   estimated-token target, and candidate ceiling. One indivisible oversized
   candidate receives a dedicated page with an explicit warning.
3. Concatenating all pages yields every unique ordered candidate exactly once;
   no tail becomes unreachable and stale or cross-policy cursors fail closed.
4. The first page reports exact remaining-page cost and the bound that limited
   it.
5. Adding unrelated Trials or Sources does not suppress a high-cost warning for
   a query concentrated in one Source.
6. On the issue #143 CHAARTED broad-term trace, search round trips fall by a
   predeclared material percentage without increasing the maximum model-facing
   page budget. Record the baseline and target in the fixture rather than using
   an unsupported universal number.
7. After #153, abandoning a broad query and fully traversing its selected
   replacement satisfies that pass while preserving the abandoned attempt as
   non-crediting audit history.
8. Full five-Domain replay remains scientifically identical: the same ordered
   candidate universe is available, coverage still fails closed on an
   untraversed selected query, and frozen Evidence semantics do not change.

## Conclusion

General agent harnesses strongly support bounding complete model-facing output,
making omissions explicit, and teaching callers to narrow. They do not provide
a ready-made scientific coverage protocol: OpenCode grep deliberately truncates
at a convenient top N, while OhMyPi can spill large output outside the inline
response. rob2-kit should borrow their context-economy techniques but retain its
stronger semantics.

The best fit is a versioned, engine-owned dual-budget policy with deterministic
per-page packing, opaque continuation, exact traversal-cost metadata, and a
cost-based broad-query warning. Combined with explicit selected-query
supersession from #153, this should reduce round trips without weakening
complete, reproducible Search coverage.
