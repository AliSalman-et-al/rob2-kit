# Select Evidence

Use this reference while locating Result support and answering Domain questions.

## Receipt and continuation recovery

Most MCP calls return their typed result in `structuredContent`. Keep the full
receipt, including `head`, `data`, and any `next_action`, `recovery`, or cursor.
When `structuredContent` is absent, inspect the text in `content`. If the result
is an error or a validation error, use the named schema path to correct the
argument and retry the call. A structured `outcome:"repair"` lists paths in
`repairs`; fix those paths in the complete draft and resubmit it. Increase a
host output limit only after the host reports truncation. A missing receipt is
not a no-hit result.

Context pages use `data.context_page.next_cursor`. Pass that value unchanged
until it is null. If a cursor is invalid, recapture the preceding page. If a
cursor is stale, restart the first scoped request. Read each page in a separate
host-visible output when the host can truncate a combined transcript.

Branch on the result before retrying:

- When a tool requests input or elicitation, let the host complete that interaction. Do not treat it as missing scientific data.
- When proposal approval is declined or cancelled, leave the Review pending and wait for researcher direction.
- When the host does not support elicitation, report that capability condition. Repeating the same call cannot add the capability.
- When a condition reports corrupt canonical or Source state, stop the affected operation and report the condition. Do not fabricate handles or resubmit the same request.
- When Domain context reports an oversized header, item, or page, restart the same explicit Trial and Domain scope with the returned larger `page_size`. This is different from following a valid cursor.

## Keep returned handles distinct

The prefixes identify different values. `eh_` is a passage Evidence handle,
`sh_` is a captured Source handle, `sr_` is a search receipt handle, and
`sha256:` is a content identity. Copy each value directly from the response.
Use an `eh_` value only after inspecting the complete returned passage. If a
handle is rejected, reread or relist the exact returned object and correct every
occurrence. Never replace one prefix with another or retype an opaque value.

## Reuse inspected passage handles

`search_sources` locates candidate pages. Copy each returned `source_id` exactly
and use it with the same `trial_id`. Each `data.hits[]` item returns a
`passage_ref` for its exact displayed window. A hit is a discovery candidate,
not retained Evidence, until you inspect the complete passage and select it.
Choose short Source wording or a returned query suggestion. Use `all` for every
token on one page, `phrase` for contiguous token matching under the tokenizer,
`literal` for contiguous wording after presentation normalization without
stemming, `any` for broad discovery, and `prefix` for token prefixes.
Suggestions are alternatives, not a checklist.
To inspect further candidates, pass `next_cursor` as `cursor` with the same
query, mode, Source scope, and limit. A truncated batch is not the full ranking.
A zero-hit response states what its explicit lexical mode matched and only
establishes that the issued query matched no captured text. It does not establish
that the method or fact is absent. Compare the complete-query page count with
the per-term counts; individual terms do not imply co-occurrence or a phrase
match. For a Source-scoped miss, inspect the returned navigation entries and
read relevant pages; use the progressive `list_sources` action only when more
entries remain. Use the observed gap and wording from inspected Sources to
choose whether to reformulate or read the relevant section directly. The
`search_sources_batch` tool accepts up to eight independent requests, each with
its own mode, outcome, and continuation cursor; use it only when all query
inputs are already known, and wait for a result before choosing a dependent
reformulation. No fixed number of queries proves completeness.
Each item has its own success, condition, error, and continuation state. A
bounded aggregate may return successful items alongside an omitted or
continuable item; keep those successes and resume only the affected item with
its own cursor. Do not treat an aggregate size condition as failure of every
query or retry the complete batch blindly.
Use `term_feedback` after an unhelpful combined search to distinguish absent
query vocabulary from terms present somewhere in a Source despite no full-query
match. It reports bounded distinct matching-page counts by Source and the count
for the complete query under its mode; counts do not establish relevance,
co-occurrence, or phrase adjacency. Reformulate with inspected study wording or
inspect the likely Source section when the counts guide the next query or read.
Per-term searches remain optional.
The Domain context may expose per-Source `coverage`. Use it to distinguish an
unsearched Source, a surfaced candidate, a searched no-hit, an incomplete
retrieval, and a read/selected passage. A protocol, SAP, or supplement shown as
`unsearched` or `candidate_only` is a recovery opportunity, not evidence that a
premise was not reported. `searched_no_match` remains a lexical fact and never
supports a scientific absence claim. Render delivery records pixels only; it
does not establish visual inspection or comprehension.
`read_pages` likewise prepares a `passage_ref` for each non-empty window. After
you inspect a complete passage, reuse that handle in Proposal `passage_refs` or
Domain `bases`; no separate text-selection call is required.
If the serialized UTF-8 response bound splits one physical line, the returned
fragment includes exact character offsets and `next_start_char` but has no
`passage_ref` or selectable Evidence handle. Receive every fragment, inspect
the full line, then select text Evidence with the original page and inclusive
line bounds. For Evidence already selected, retain its original handle; do not
replace it with a fragment handle. A page-boundary continuation uses the
returned line continuation in the same way.

## Recover omitted Evidence

Use this procedure when an omitted passage needs inspection or its content is
no longer available to you.

1. Call `read_pages` with `recovery.trial_id` and `recovery.windows`.
2. If `data.remaining_windows` is nonempty, call `read_pages` with the same
   `trial_id` and `windows` set to that list. Omit `source_id`, `pages`, and
   top-level `start_line`.
3. Repeat until no windows remain. The returned lines then cover every requested
   window through its original `end_line`.
4. Inspect the complete passage before citing it.

The original Evidence handle identifies the complete passage. A partial
`passage_ref` from `read_pages` identifies only the range returned in that call.

Tool page numbers are 1-based Source indexes, not printed page labels. Read the
numbered Source text; never reconstruct PDF text from a preview. For comparison
across Sources, use independent `windows`. A passage crossing a page boundary needs one
selection on each page.

Use `select_text_evidence` after inspecting the source text when the prepared
passage needs different boundaries. Select one contiguous inclusive line range containing
the complete premise and its needed header, list, cohort, denominator, unit, or
footnote. A heading or list-introducing lead-in alone is incomplete.

## Use visual Evidence for visual meaning

Call `render_page` when layout, axes, columns, symbols, or footnotes affect the
meaning. Inspect the returned pixels, then call `select_visual_evidence` with the
`delivery_receipt` from the same response, a normalized region, and a literal,
self-contained transcription. A receipt is issued only when the response includes
an MCP `ImageContent` block; `inline=false` returns metadata without a receipt and
cannot support visual Evidence. Include every applicable title, axis, series,
label, value, unit, uncertainty, denominator, and footnote visible in the region.

The server binds the receipt to the exact Trial, Source, render, and PNG hash.
It records that it returned the image block; the receipt does not establish that a
person or model inspected or understood it. The host supplies the transcription;
`text_corroborated` means the complete-page transcription also occurs in extracted
Source text, while `host_visual` means it is grounded in the delivered pixels.
Host-visual Evidence can support only literal visible labels, endpoint text,
values, axes, arm labels, and stated timing. Use narrative or text-corroborated
Evidence for population, analysis or measurement methods, prespecification, and
conduct. Put interpretation in the Result rationale or Domain justification,
not in the transcription.

## Ground a Result

Use `passage_refs` for ordinary Result support and `applicability.evidence` for
design support. Do not place Evidence objects in `reported`. Use ordinary
selected Evidence for a single passage; use `table_multispan` only when a table
title or definition, header, quantitative row, unit, or footnote was selected
as separate passages. Give each selection its actual role and handle. Those
spans remain separate citations: do not concatenate their text, assume they
are adjacent, or claim that they scientifically belong together merely because
they are used by one Result.

Preserve exact Source labels and quantities, or values equivalent after normalization.
For `analysis_population`, a supported summary may combine passages when it preserves
the reported inclusion criteria and exclusions. Caller-owned target interpretation,
timing, and arm assignments do not need duplicate source quotations.
For a categorical profile, `category_axis_names` names the ordered non-treatment
dimensions; it does not replace Evidence for source-reported category labels or
cells. Source-owned endpoint labels,
definitions, group or category labels, quantities, units, and denominators do.

For ordinary narrative, table, or figure Evidence, at least one item must contain
`reported.endpoint.name` and a complete quantitative tuple. A multi-span table
instead needs a cited header and quantitative-row span; the endpoint must occur
in its cited title/definition or header, and each tuple value must occur in one
of the cited header, row, unit, or footnote spans. `Total`, `Overall`, or a
similar aggregate label is not an endpoint name. Follow the tuple rules in
[Specify the Result](result.md).
Repair unsupported leaves with exact Source wording and better Evidence; a
support defect does not make the Result unavailable.

## Ground a Domain answer

Attach each basis to the active question it informs:

- `direct_support`: the passage states the answer premise;
- `indirect_support`: the passage establishes it through an explicit link;
- `contradiction`: the passage conflicts with the premise;
- `context`: the passage fixes scope or meaning;
- `inference`: the passage supplies facts from which you draw a stated conclusion;
- `absence`: an untruncated scoped search found no hits;
- `limitation`: an explicit unresolved premise and stopping rationale, with an
  optional current-Trial search receipt when retrieval provenance is useful.

Non-absence Evidence relationships use a selected Evidence handle, except
`limitation`, which uses an unresolved premise and a stopping rationale. A
directly read passage does not require a search receipt. An
`absence` receipt must
report `truncated:false`, `total_matches:0`, and `condition:"no_hits"`. A
positive search may support a limitation after you inspect the
relevant material, but it cannot support absence.

For example:

```json
{"kind":"limitation","unresolved_premise":"The report leaves the outcome ascertainment process unresolved after scoped discovery.","stopping_rationale":"Relevant captured Sources were reviewed, but the premise remains unresolved.","search_receipt":"sr_0123456789abcdef"}
```

If you include a search receipt, use the actual receipt returned for the
current Trial. The handle above is fictional.

A relationship label never expands what the passage says. Keep plans separate
from conduct, analysis populations from observed outcomes, endpoint definitions
from measurement properties, and absence of reporting from absence of bias.
Reuse Result Evidence only when its exact premise answers the Domain question.
State inferred conclusions in the answer's `justification`, with the source
facts and any unresolved link. The server checks Evidence identity and structure;
you judge whether those facts support the answer.

## Build a Domain answer

Read this section before the first `validate_domain_assessment` call. Submit
one object for each question on the dependency-closed active path. The object
needs `question_id`, the exact permitted `answer`, at least one `bases` item,
`justification`, `unknowns`, and `counterevidence` for an active question.
Use the question card's `options`; the example values are fictional.

```json
{
	"question_id": "sq:randomization:sequence",
	"answer": "yes",
	"bases": [
		{"kind": "direct_support", "evidence": "eh_0123456789abcdef"}
	],
	"justification": "The inspected passage states that a computer generated random allocations.",
	"unknowns": [],
	"counterevidence": []
}
```

Use a limitation basis separately when the source leaves a premise unresolved.

Use these exact shapes for the three basis forms:

```json
{"kind": "context", "evidence": "eh_0123456789abcdef"}
{"kind": "absence", "search_receipt": "sr_0123456789abcdef"}
{"kind": "limitation", "unresolved_premise": "The captured reports leave this premise unresolved.", "stopping_rationale": "Relevant retrieval was reviewed, but the premise remains unresolved.", "search_receipt": "sr_0123456789abcdef"}
{"kind": "limitation", "unresolved_premise": "The captured reports leave this premise unresolved.", "stopping_rationale": "The relevant section was read, but the premise remains unresolved."}
```

`context`, `direct_support`, `indirect_support`, `contradiction`, and
`inference` use a selected `evidence` handle. `absence` uses an untruncated
zero-hit `search_receipt`. `limitation` uses an explicit `unresolved_premise`
and `stopping_rationale`. Its current-Trial `search_receipt` is optional and
may be truncated. A basis kind describes how the premise is used;
it does not add facts to the cited passage.

## Recover an unresolved premise

Use this gap-directed Reason–Act loop when inspected Evidence leaves a material
fact unresolved. Keep the loop in one working assessment across searches and
cursors.

1. Reason. Start from the approved Result and inspected main-report passages.
   Record the exact unresolved fact, the named method or section reference and
   concrete study wording that would distinguish the possible answers, what
   inspected Evidence leaves open, and the likely Source that could resolve it.
   Prefer wording from an inspected passage over a methodological label from
   the question card.
2. Act. Inspect the active comparison card's complete `passage_groups` inventory
   when one is returned. `passage_groups` navigate captured Sources; they do
   not contain every intake condition. For declared omissions or file-level
   intake conditions, inspect `get_status.data.conditions` or call
   `list_sources(trial_id)`. Use each group's `source_id`, `page_count`, and
   `logical_path` to navigate it. Source navigation identifies pages with no extracted text; those
   pages may contain visual or otherwise unextracted material. A supplement,
   `other` document, or combined
   protocol can contain the needed plan or participant-flow detail. A Source
   role is a routing hint, never evidence about its contents or applicability.
3. Search the likely Source with concrete study wording. Use a methodological
   label only to supplement that wording. Use a no-hit's exact mode and
   per-term counts to decide whether another explicit query or direct section
   read could resolve the premise. If a result is truncated and has a
   `next_cursor`, continue the same query first when deeper ranked passages
   could resolve the premise. Use the final untruncated receipt when recording
   `absence`; a limitation may keep a truncated receipt or omit it. Change the
   query only when its wording or the premise warrants a change. For a
   Source-scoped miss, inspect the navigation entries. Use
   the unresolved fact, Trial context, term feedback, and literal Source wording
   to choose whether another query or direct section read could resolve it. Read
   relevant returned pages. Continue navigation when the displayed entries do
   not identify a useful page or query. Navigation entries guide inspection;
   cite Evidence from the inspected passage. Do not treat a no-hit or an
   uninspected hit as scientific absence.
4. After each search or read, update the fact to exactly one state: supported,
   contradicted, or still unknown. A hit remains a candidate until you inspect
   the complete passage.
5. If the returned hits do not address the fact, inspect the relevant section
   of the likely Source, including its contents or front-matter pages when
   needed, before recording a limitation. Exhausted query results or ranking
   pages are not an inspected section. If that section does not resolve the
   fact, use another relevant search or read when it could narrow the unresolved
   premise. Do not run every query suggestion or read every appendix by default.
6. Investigate the upstream premise first. If it remains unknown, preserve that
   uncertainty and follow the question card's activation rules. Before
   `validate_domain_assessment` and `save_domain_judgment`, revisit every
   still-material unknown against the Source inventory. Record the relevant
   section inspected and the facts that remain unavailable. If a fact
   remains discoverable within captured Sources and bounded cursor or page
   windows, make the next relevant search or read. Otherwise record a concise
   limitation with an explicit stopping rationale and, when applicable, the
   current-Trial search receipt. Stop as soon as an inspected passage contains
   the complete premise and select its exact boundaries. The limitation
   documents the information reached, not absence of the fact.

An unreported result does not show that participant outcomes were unobserved.
Missing reporting alone does not establish differential measurement or result-based
selection. This loop separates four observations: a page was retrieved, a useful
candidate was surfaced, a complete source window was read, and the premise was
actually supported. Only the last two can ground a Domain answer.

The Domain context also reports source-specific retrieval coverage. A match in a
multi-Source search belongs only to the Source that returned it. A paginated
session remains `retrieval_incomplete` until a terminal receipt closes a gap-free
rank sequence; a completed no-hit Source is a retrieval observation, not a
scientific absence claim.

Completion: each Source-owned assessable Result leaf has exact support, and each
active Domain answer has a valid basis for its stated premise and uncertainty.
