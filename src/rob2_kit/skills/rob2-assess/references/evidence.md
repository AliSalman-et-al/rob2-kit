# Select Evidence

Use this reference during source navigation, Result preparation, and Domain work.

## Navigate before you select

1. Use `search_sources` to locate candidate pages.
   Each hit includes its Source role and label. Source-first order is a
   navigation priority; use a targeted follow-up query when the active question
   points to a protocol, SAP, registry, or other later-ranked Source.
   If `truncated` is true, a positive exact passage remains usable, but refine
   the query before treating candidate discovery as complete or using the
   search as an absence basis.
2. Use `read_pages` to inspect exact page text with server-issued line numbers.
   Page values are 1-based source-page indexes, not printed page labels.
   Pass the explicit `pages` list; there is no `limit` or range argument.
3. Use `render_page` when visual structure changes the meaning.
4. Call `select_text_evidence` or `select_visual_evidence` only after you identify the exact support.

A search hit is navigation, not Evidence. A no-hit search does not prove absence.

## Select one immutable Evidence item

Use `select_text_evidence` with the page, first line, and last line issued by
`read_pages`. If unrelated text shares the first or last selected line, copy a
unique `start_text` or `end_text` from that boundary line to trim the range.
Never otherwise copy or reconstruct PDF text. If a passage crosses a page
boundary, make one selection on each page. Select the lines for one complete
`[Extracted table N]` block. If extraction interleaves adjacent tables or you
cannot isolate the table with boundary text, render the page and select only
the relevant visual region. The selected passage must
contain the complete fact and every applicable row, column, header, cohort,
unit, denominator, cell, or footnote needed to interpret it. Expand a truncated
passage before using it. For Domain Evidence, select the complete premise,
sentence, or list: a heading, colon, or lead-in such as “the following” is
incomplete on its own.

Use `select_visual_evidence` only after you inspect a verified render. A normal
`render_page` call returns the pixels as ImageContent; pass `inline:false` only
when metadata/cache-only behavior is explicitly wanted. Selection persists the
figure; do not repeat its handle in a Result card. The visual Evidence consists of the
render identity, normalized `x0,y0,x1,y1` region, and one exact, self-contained
transcription containing every applicable title, axis, series, label, value,
unit, uncertainty, denominator, and footnote. Use `[0,0,1,1]` for the whole
page. Do not invent typed axes, series, or extraction fields.
The server assigns figure provenance automatically as `text_corroborated` or
`host_visual`; never provide that label. Prefer text corroboration: it is used
only for a full-page region whose transcription has an exact normalized span in
the persisted page text. `host_visual` is valid for image-only figures and
diagrams. Every Result leaf must occur in the selected transcription. Host
visual Evidence may support only literal endpoint/name/definition, reported
values or category axes, arm-assignment labels, and stated time points/windows.
Claims about intended population, analysis or measurement method,
prespecification, or conduct require text-corroborated or narrative Evidence.
Transcription must contain literal visible content only; put interpretation in
the Result relation rationale or Domain rationale/basis. Proposal review shows
the provenance, transcription, render, and region.

## Bind Result fields to selected material

Do not send an `evidence` field, Evidence objects, copied table fields, figure
metadata, derived calculations, bindings, clauses, or source-to-value mappings
in an assessable Proposal. The server resolves durable text and visual
selections, derives Result bindings, and retains only material used by the
Result. Do not invent or collapse labels or values absent from selected
material; proposed Result values must be reported by the Source.

Before saving, check the mechanical support rules: every Source-bound target
leaf and every reported leaf has exact support from selected Evidence. The
server reconstructs `/target/outcome_definition`, `/target/measurement/metric`,
and `/target/effect_of_interest` from Intake and the fixed contract.
Comparison-group IDs are caller-supplied structural identifiers; repeated
reported group IDs are structural references that must match target IDs but do
not need separate Evidence mappings. `category_axis_names` likewise declares
dimensions structurally; source-owned category labels remain in each
`category_axes` tuple. Direct narrative, table, and figure leaves use normalized
containment against the selected immutable Evidence item; repeated labels,
units, or values do not require a unique occurrence once the Evidence handle
has been selected.
Use the shortest complete Source wording that identifies each structured leaf.
Do not expand an arm-assignment value with dosage or schedule detail unless that
detail is needed to distinguish the randomized arms.
Repair all other reported unsupported leaf values and Evidence
defects together. A draft repair is not evidence that the result is unavailable.
For `result_value_not_supported`, use exact source wording and select Evidence
containing the supplied value.

## Write Evidence uses for Domain answers

Bind each Domain Evidence use to its active question:

- `direct_support` when the Evidence states the answer premise;
- `indirect_support` when the Evidence supports the answer premise through an explicit link;
- `contradiction` when the Evidence conflicts with the answer premise;
- `context` when the Evidence defines scope or meaning;
- `absence` when a scoped search account supports an absence claim; or
- `inference` only when the selected premise directly warrants the answer.

For an absence use, record the Source scope, exact query, lexical mode, and
retrieval result in the search receipt. The receipt must be an untruncated
no-hit result (`truncated:false`, `total_matches:0`, `condition:no_hits`);
refine the search before using a truncated or positive receipt. Add a
limitation when the answer remains uncertain. A no-hit query alone is
insufficient for a confident scientific conclusion.

For every non-absence Domain use, select Evidence for the active question and
send its handle. The server derives the exact stored quote or transcription as
the checkpoint `source`. Reuse Result Evidence only when that complete selected
premise supports the answer. This exact-premise rule
applies regardless of whether the relationship is `direct_support`,
`indirect_support`, `context`, `contradiction`, or `inference`. For
`indirect_support`, the passage must prove the stated premise through an
explicit link. A relationship label never licenses extra facts. An absence use
has only a search receipt and no selected Evidence. Do not mistake stratification
or central registration for allocation concealment, a table header for baseline
balance, an ITT/all-randomized sentence for no deviations, an endpoint label or
time origin for follow-up completeness or equal assessment, or an outcome
definition for objectivity, blinding, prespecification, or absence of
alternative analyses. Use an absence search account or a limitation when the
source does not prove the claim.

Completion: every structured Result fact and every active Domain answer has an
exact Evidence use or an explicit limitation.
