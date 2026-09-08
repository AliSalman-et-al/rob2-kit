# Use an evidence-first v0.4 interaction without new workflow tools

Status: accepted

Amended for the v0.5 successor contract by issues 283-286, 288, 290, and 291.

Amended by issues 298-303 for bounded main-report reading and Result semantics v0.6.

## Bounded reading and scientific judgment amendment

Keep the existing public tools and Proposal Review gate. Require main-report
text delivery before Proposal submission and again after approval before the
first Domain save. Each pass covers a consecutive whole-line prefix of at most
65,536 UTF-8 source-text bytes per main report. `get_status` returns the next
required windows and reports `budget_limited` with navigation to unread text.
Long reports still require targeted discovery for relevant omitted premises.

The host may declare a source-backed suffix boundary in the Proposal for a
separate appended document. The last page containing article content stays in
scope. Proposal submission checks the first pass against that proposed scope;
the second pass uses the approved scope and same captured Source. Reading receipts
are derivative delivery records, not proof of comprehension or retained context;
after a restart, recover current progress and any needed passages.

Every assessable Result records pack applicability. Unsupported or unresolved
designs remain unassessed after approval. Result relation `exact` means equivalent
scientific scope; different endpoint names require a correspondence rationale.
Canonical provenance retains applicability and report-boundary Evidence.
Historical bundles retain their recorded relation semantics.

The host applies the existing RoB 2 response framework before selecting an
answer: consider defensible probable judgments from source facts and trial
circumstances before `no_information`. Question-specific evidence requirements
remain in force. The server validates structure and provenance, without a new
answer-order state machine or semantic classifier. D3 arithmetic can be previewed
through `get_domain_context`; captured plan metadata supplies navigation for D5,
without establishing historical plan timing or applicability.

### Upgrade boundary

This amendment applies to fresh assessment workspaces. Active v0.5 assessments
must finish with the previously installed version before upgrading, or restart
in a new workspace from the original inputs. Migration of active workspaces to
the amended workflow is untested and unsupported. Historical finalized v0.5
bundles still verify unchanged and retain their recorded semantics.

## Context

The v0.3 boundary exposed exact Evidence, but ordinary Proposal and Domain work
still required the host to copy coordinates through avoidable selection calls.
Assessment context also omitted Evidence selected after Proposal approval and
could not restore a saved checkpoint's short Evidence handles after derivative
cache loss. FastMCP 4 changes the transport and modern approval round trip, so
these contract changes require a versioned successor rather than edits to the
frozen v0.3 contract.

## Decision

- Keep the same 14 public tools. Search hits and page windows prepare exact,
  source-bound `passage_ref` handles. Proposal and Domain submissions resolve
  the chosen handles atomically into separate canonical Evidence records.
- Keep scientific choices with the host. The server supplies source metadata,
  exact passages, active questions, arithmetic reconciliation, state revisions,
  and canonical provenance; it does not infer Result correspondence, signaling
  answers, assessor identity, conduct from a plan, or semantic entailment.
- Make `get_domain_context` the recovery projection. It returns the approved
  target, current checkpoint, canonical Evidence from current and earlier
  checkpoints, and a bounded question/Domain-oriented workspace of disposable
  candidates. Approved Result and checkpoint Evidence are mandatory tiers and
  are never ranked against disposable candidates. Each disposable item carries
  a reproducible inclusion reason; omitted candidates remain reachable through
  their immutable search session/cursor. It never exposes another Trial's
  Evidence.
- Search is split into a complete deterministic derivative ranking and bounded
  rendering. A session identity binds Trial, projection identities, normalized
  query, lexical mode, and ranking versions, but excludes display limit,
  workflow revision, creation time, and viewed range. The Source-diverse order
  is the public candidate rank used by cache rows, receipts, cursors, and hits;
  there is no second presentation rank. Cursors are opaque,
  stable, and stale when the projection/configuration no longer matches.
- Signalling cards expose server-issued self-describing answer options bound to
  the pack version, exact question, official answer, proposition, certainty,
  anchor, and decision-table consequence. Public submissions select one option
  identity; canonical checkpoints continue to store official RoB 2 codes.
- Add an optional concise justification to each Domain answer. Add typed
  participant-flow rows only to question 3.1; the server computes comparable
  missing counts and fractions and preserves conflicts without choosing a
  scientific answer.
- Upgrade to FastMCP 4.0.3 and MCP SDK 2.1.x. Use FastMCP's input-required
  result for modern Proposal approval and the supported elicitation path for
  negotiated legacy sessions. Both paths bind the response to the exact pending
  Review and call the same approval implementation.
- Return one normalized result as both structured content and compact JSON text.
  Image content remains a separate binary block.
- Require an explicit lexical mode on the public `search_sources` call. Keep
  `any` as an intentional broad-OR discovery mode, and when its returned
  ranking is both broad and truncated, expose a deterministic diagnostic from
  observable request/result facts plus one executable refinement or cursor
  continuation. This is retrieval advice, not a scientific conclusion.
- Add bounded typed query suggestions to each scientific question card. A
  suggestion contains query text, lexical mode, an optional recommended Source
  role, and a short purpose. Suggestions are maintained alternatives and vocabulary, not a
  mandatory workflow or a claim that a Source uses those words.
- Preserve a bounded recovery path for an initial multi-token `all` or `phrase`
  no-hit: return one executable same-query `any` search with the same Trial,
  Source scope, and limit. The action is retrieval advice only; a zero-hit
  receipt remains specific to its issued lexical query, and broad `any`
  truncation/cursor behavior is unchanged.
- Present `get_domain_context` in stages. The approved Result, complete
  question semantics, and comparison cards precede bulk Evidence in the
  model-facing text. Comparison cards retain Result scope, passage groups, and
  slots. They use `question_id` to refer to wording and options in exactly one
  returned question card. The 64-item disposable selection limit is separate
  from the 12,288-byte budget for recoverable narrative Evidence text. Narrative
  overflow retains the selected narrative Evidence identity, coordinates, and
  executable `read_pages` recovery windows. Visual transcription, table values,
  derived values, and coordinate-less legacy narrative text remain inline when
  no exact existing recovery operation exists, even beyond the recoverable
  disposable-item limit; their additional bytes are reported separately.
  Missing derivative search sessions are reported explicitly rather than
  silently erased. This is a transport projection, not a canonical or
  scientific-state change.
- Keep Domain 4 host reasoning outcome-specific. The host audits the approved
  event and method, between-group ascertainment opportunities, assessor identity
  and awareness, and any influence mechanism in that order. Mixed-outcome
  passages require an explicit premise link or an unresolved/inferred statement;
  mortality and endpoint labels do not receive automatic judgments.

## Domain projection ownership

| Tier | Inclusion and ownership |
| --- | --- |
| Approved Result Evidence | Always included from the approved canonical Result. |
| Active checkpoint Evidence | Always included from the requested Domain checkpoint; Evidence from other Domain checkpoints is not copied into this context. |
| Active checkpoint contradictions | Always included and indexed separately as contradictions. |
| Active-Domain search candidates | Ranked deterministically by stable candidate rank and session identity, then selected within the 64-item disposable limit; selected narrative quotes use the recoverable narrative-text budget. |
| Explicit carry-forward | Exact passages selected outside a search session take priority within the 64-item disposable limit and the recoverable narrative-text budget; overflow remains reachable through executable `read_pages` windows. |
| Other-Domain search candidates | Excluded. They remain reachable through their original immutable session while derivative session state exists. |

Canonical tiers never compete with the 64-item disposable limit. They take
priority within the recoverable narrative-text budget. The response groups
Evidence handles by inclusion reason and question scope, reports every omitted
candidate, and supplies an executable search cursor whenever an associated
candidate is omitted. Loss of disposable state never invalidates canonical
Result or checkpoint Evidence.

## Input ownership

| Data | Owner | Public input |
| --- | --- | --- |
| Trial IDs, Source IDs, current phase and revision | Server state | References only |
| Exact quote, coordinates, Source identity and Evidence identity | Server | Short `passage_ref`/Evidence handle |
| Requested outcome | Researcher at intake | `prepare_batch.requested_outcome` |
| Chosen reported Result and its relation to the request | Host scientific judgment | Proposal Result card |
| Target measurement, timing, groups, population and effect measure | Host interpretation reviewed by researcher | Proposal Result card |
| Source-reported endpoint labels and quantitative values | Host selects; server binds to exact Evidence | Proposal Result card plus `passage_refs` |
| Proposal approval | Researcher through client elicitation or CLI | Never a model-authored tool argument |
| Active signaling answers and evidence relationships | Host scientific judgment | `answers[].option_id` and `answers[].bases` |
| Active branches, Domain/overall judgments and checkpoint provenance | Server | Derived, never repeated by caller |
| D3 comparable flow scope and reported counts | Host interprets scope; server computes arithmetic and reuses answer Evidence as row provenance | Optional `answers[].missing_data` on 3.1 only |
| Scientific explanation and unresolved facts | Host | Optional `answers[].justification` |

## Concrete call transcripts

Synthetic identifiers are shortened only in prose; each JSON example uses the
actual public shape.

### Proposal

Before v0.4, the ordinary path was `search_sources` -> `read_pages` ->
`select_text_evidence` -> `save_proposal`. In v0.4 the search response includes
an exact passage handle:

```json
{"hits":[{"source_id":"source_<hash>","page":2,"start_line":14,"end_line":16,"preview":"...mortality at day 28...","passage_ref":"eh_0123456789abcdef"}]}
```

The host submits its scientific Result card with
`"passage_refs":["eh_0123456789abcdef"]`. The server removes that convenience
field from the canonical Result and retains the resolved Evidence separately.

### Simple Domain

```json
{"trial_id":"trial-a","domain_id":"domain:randomization","expected_revision":3,"answers":[{"question_id":"sq:randomization:sequence","option_id":"opt_0123456789abcdef01234567","bases":[{"kind":"direct_support","evidence":"eh_0123456789abcdef"}],"justification":"The cited passage describes a computer-generated sequence; concealment is addressed separately."}]}
```

### Multi-document Domain

One call reads independent windows from two Sources:

```json
{"trial_id":"trial-a","windows":[{"source_id":"source_<article>","page":3,"start_line":20,"end_line":24},{"source_id":"source_<sap>","page":7,"start_line":4,"end_line":9}]}
```

Each returned page carries its own `source_id`, coordinates and `passage_ref`.
The answer cites both handles as separate bases; the server never concatenates
them into a false contiguous quotation.

### Stale retry

A save using `expected_revision:3` after revision 4 returns a typed conflict and
does not persist. The host calls `get_status`/`get_domain_context`, keeps the
same scientific answer if still applicable, and retries with revision 4. An
identical retry at the accepted revision resolves to the existing record.

### Restart

After a host restart, `get_status` supplies the active Trial and operation.
`get_domain_context` then restores the approved Result, exact selected passages,
and handle-to-identity mappings from current and prior checkpoints. Loss of
`derivative.sqlite3` removes only uncommitted derivative handles; canonical
checkpoint Evidence remains recoverable with the same handle and identity.

## Consequences

The common path has fewer coordinate-copying calls while preserving exact
Evidence and atomic commits. The response can be larger because it includes a
bounded recovery workspace and text fallback. Host delivery and scientific
accuracy remain qualification results, not properties inferred from unit tests.
The FastMCP dependency change stays separable in history so it can be reverted
without migrating canonical v0.3 records.
