# Read sources and cite Evidence

Use this reference while reading Sources, grounding a Result, and building
Domain answers.

## Receipt and continuation recovery

Most tools return a typed receipt in `structuredContent` with `head`, `data` and
sometimes `next_action`, `recovery` or a cursor. Keep the whole receipt.

- No `structuredContent`: read the text in `content`. For an input validation
  error, fix the named argument and retry. For
  `internal_output_contract_error` or `internal_evidence_integrity_error`, stop
  that operation and report it; retrying does not repair server state.
- `outcome:"repair"`: fix every listed path and resubmit the complete draft.
- Cursors (`next_cursor`, `data.context_page.next_cursor`): pass them unchanged
  until null. If a cursor is invalid, repeat the previous page; if stale,
  restart the scoped request without a cursor. Do not assess while a context
  cursor remains.
- An oversized header or item condition: repeat the same request with the
  returned `max_response_bytes`; otherwise omit that argument.
- Elicitation requests belong to the host. If proposal approval is declined or
  cancelled, leave the Review pending. If the host cannot elicit, report the
  returned condition; repeating the call does not add the capability.
- A missing receipt is not a search result and not evidence of absence.

## Keep returned handles distinct

`eh_` is an Evidence passage handle, `sh_` a Source handle, `sr_` a search
receipt and `sha256:` a content identity. Copy each value exactly from a
response; never retype, shorten or swap prefixes.

## Read, then search

Reading is how you learn what a Source says. For each Domain, read the sections
that bear on its questions in every relevant Source (see the Domain reference).
Use searches to find where those sections are, then read the pages.

`read_pages` takes either one Source and up to 10 pages:

```json
{"trial_id": "fictional_trial", "source_id": "sh_0123456789abcdef", "pages": [2, 3], "start_line": 1}
```

or independent windows:

```json
{"trial_id": "fictional_trial", "windows": [{"source_id": "sh_0123456789abcdef", "page": 4, "start_line": 10, "end_line": 40}]}
```

Read text from `data.pages[].numbered_text`. If `data.remaining_windows` is not
empty, call again with `windows` set to that list until it is empty. Page
numbers are 1-based Source page indexes, not printed page labels. A very long
line may arrive as character fragments with `next_start_char`; read them all
before citing that line. Never reconstruct PDF text from a preview.

## Reuse inspected passage handles

`search_sources` finds candidate pages in captured text. Modes: `phrase` for
known contiguous wording, `all` for every token on one page, `literal` for exact
wording without stemming, `any` for broad discovery, `prefix` for token
prefixes. Use the trial's own wording when you know it. `search_sources_batch`
runs up to eight independent searches; each item has its own result and cursor.
`term_feedback` after a miss shows which query terms occur anywhere in each
Source.

A zero-hit search only says that query matched no captured text. Different
wording, a table, an image-only page or another Source may still hold the fact.
Before concluding a fact is unreported, read the section where it would
normally appear (methods, flow, tables, supplements, protocol, registry). A
`no_sources` or `no_searchable_sources` condition means nothing was searched;
use `render_page` for image-only pages.

Each search hit and each `read_pages` window returns a `passage_ref` for the
exact text shown. After reading the complete passage, reuse that handle in
Proposal `source_passages` or Domain `bases`; no separate selection call is
needed. Use `select_text_evidence` only to narrow a passage: give either a
unique literal `selected_text` copied from `read_pages` on the same page, or
`start_line` and `end_line`. A passage crossing a page boundary needs one
selection per page. Include the header, unit, denominator or footnote a premise
depends on.

## Recover omitted Evidence

When an Evidence item shows `text_status:"omitted"` and you need its content:

1. Call `read_pages` with its `recovery.trial_id` and `recovery.windows`.
2. Repeat with `data.remaining_windows` until empty.
3. Read the complete passage before citing it.

## Use visual Evidence for visual meaning

Call `render_page` when layout carries meaning: tables with merged cells,
figures, flow diagrams, image-only pages. Inspect the returned image. Cite it
with its `delivery_receipt`, an optional normalized `region`
(`[x0, y0, x1, y1]`, top-left origin) and a literal `transcription` of the
labels, values, units and footnotes visible in that region:

```json
{
  "delivery_receipt": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "region": [0.1, 0.2, 0.9, 0.8],
  "transcription": "Literal labels, values, units and qualifications visible in this region.",
  "uncertainty": "The exact value of one marker is unclear; no value is inferred."
}
```

This object can go directly in Domain `bases` or `counterevidence`; call
`select_visual_evidence` first when you need a reusable handle (for example in
a Proposal). A receipt exists only when the response included an image block.
Keep interpretation in the justification, not in the transcription.

## Ground a Result

Put ordinary Result support in the selection's `source_passages` and design
support in `candidate.design_evidence`; never put Evidence objects inside
`reported`. At least one cited passage must contain the endpoint name together
with a complete quantitative tuple (effect measure and estimate, or a group's
statistic, value and unit). Copy endpoint names, estimates and intervals from
that passage. For a table whose title, header, row and footnote were selected
as separate passages, use a `table_multispan` object in `candidate.evidence`
with roles `title_or_definition`, `header`, `quantitative_row`, `unit` and
`footnote`. A generic row label such as `Total` is not an endpoint name. See
[Specify the Result](result.md) for the complete request.

## Build a Domain answer

Submit one object per question on the active path, with `question_id`, the
`answer` (one of the card's `options`), `bases`, `justification`, `unknowns`
and `counterevidence`. The example values are fictional:

```json
{
	"question_id": "sq:randomization:sequence",
	"answer": "yes",
	"bases": [
		{"role": "direct_support", "evidence": "eh_0123456789abcdef"}
	],
	"justification": "The inspected passage states that a computer generated random allocations.",
	"unknowns": [],
	"counterevidence": []
}
```

`bases` roles: `direct_support` (the passage states the premise),
`indirect_support` (it establishes the premise through a stated link),
`inference` (it supplies facts you reason from), `context` (it fixes scope or
meaning), `contradiction` (it conflicts with the premise). A basis can also be a
copied quote `{"source_id", "page", "selected_text"}`, a line range
`{"source_id", "page", "start_line", "end_line"}`, or a visual reference.

When a premise stays unresolved after reading the relevant sections, record it
alongside any Evidence:

```json
{
  "bases": [{"role": "context", "evidence": "eh_0123456789abcdef"}],
  "absence_searches": ["sr_0123456789abcdef"],
  "limitations": [{
    "premise": "The captured reports leave this premise unresolved.",
    "stopping_rationale": "The relevant section was read, but the premise remains unresolved."
  }]
}
```

`absence_searches` takes untruncated zero-hit search receipts; `limitations`
take a `premise` and `stopping_rationale`, with an optional `search_receipt`.
Counterevidence entries are `{"evidence": ["eh_..."], "implication": "..."}`.
Use `[]` for empty `unknowns` and `counterevidence`.

## Recover an unresolved premise

When a fact that would change an answer is still unknown:

1. Name the fact and the Source section where a trial would normally report it.
2. Read that section in each Source that could hold it (the comparison card's
   `passage_groups` list every captured Source with its `source_id` and
   `page_count`; `list_sources` shows intake conditions and omissions).
3. Search with the trial's own wording to find other locations; read the hits.
4. Stop when a passage settles the fact, or when the relevant sections have been
   read and it remains unreported. Then answer under the official rules for
   probable answers and No information, recording the limitation.

## Opt-in lean Domain drafting

`bases` may also hold plain handle strings or exact text references, which the
server saves as `indirect_support`:

```json
{
  "question_id": "sq:selection:prespecified-analysis",
  "answer": "probably_yes",
  "bases": [
    "eh_0123456789abcdef",
    {"source_id": "sh_0123456789abcdef", "page": 2, "start_line": 5, "end_line": 9},
    {"source_id": "sh_0123456789abcdef", "page": 2, "selected_text": "Literal contiguous text copied from read_pages."}
  ],
  "justification": "Explain the source-supported inference for this Result.",
  "unknowns": ["State the material unresolved fact."],
  "counterevidence": []
}
```

Optionally annotate a basis with a `working_observation` (`text` plus an optional
`scope` with `relation` and `meaning`) to record how a passage applies to this
Result; see [Selected Result reconstruction](result-account.md) for
working-checkpoint steps.
