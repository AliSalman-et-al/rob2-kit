# Select Evidence

Use this reference while locating Result support and answering Domain questions.

## Reuse inspected passage handles

`search_sources` locates candidate pages. Copy each returned `source_id` exactly
and use it with the same `trial_id`. A hit is navigation, not scientific
proof, but its `passage_ref` already identifies the exact returned passage.
Choose short Source wording or a returned query suggestion. Use `all` for every
token on one page, `phrase` for contiguous wording, `any` for broad discovery,
and `prefix` for token prefixes. Suggestions are alternatives, not a checklist.
To inspect further candidates, pass `next_cursor` as `cursor` with the same
query, mode, Source scope, and limit. A truncated batch is not the full ranking.
A zero-hit receipt
establishes only that the issued lexical query matched nothing. For an eligible
initial multi-token `all` or `phrase` no-hit, broaden once with the returned
`mode:"any"` action and inspect the passages; if retrieval remains unhelpful,
inspect the relevant section of an available Source and other relevant Sources
before recording an unresolved limitation. One widening step is not adequate
discovery by itself.
`read_pages` likewise prepares a `passage_ref` for each non-empty window. After
you inspect a complete passage, reuse that handle in Proposal `passage_refs` or
Domain `bases`; no separate text-selection call is required.

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
meaning. Inspect the returned pixels, then call `select_visual_evidence` with a
normalized region and a literal, self-contained transcription. Include every
applicable title, axis, series, label, value, unit, uncertainty, denominator, and
footnote visible in the region.

The server owns the render identity and assigns `text_corroborated` or
`host_visual` provenance. Host-visual Evidence can support only literal visible
labels, endpoint text, values, axes, arm labels, and stated timing. Use narrative
or text-corroborated Evidence for population, analysis or measurement methods,
prespecification, and conduct. Put interpretation in the Result rationale or
Domain justification, not in the transcription.

## Ground a Result

Do not send an `evidence` field at the top level of an assessable Result card,
or place Evidence objects in `reported`. Use `passage_refs` for Result support
and `applicability.evidence` for design support. The server retains supporting
Evidence and derives canonical bindings.

Every Source-owned reported leaf must have exact or normalization-equivalent
support. Caller-owned target interpretation, timing and arm assignments do not
need duplicate source quotations. Comparison-group IDs and structural
`category_axis_names` do not need them either. Source-owned endpoint labels,
definitions, group or category labels, quantities, units, and denominators do.

At least one Evidence item must contain `reported.endpoint.name` and a complete
quantitative tuple. Follow the tuple rules in [Specify the Result](result.md).
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
- `limitation`: a concise unresolved information limit plus an untruncated
  current-Trial search receipt.

Non-absence Evidence relationships use a selected Evidence handle, except
`limitation`, which uses text and a search receipt. An `absence` receipt must
report `truncated:false`, `total_matches:0`, and `condition:"no_hits"`. A
positive untruncated search may support a limitation after you inspect the
relevant material, but it cannot support absence.

A relationship label never expands what the passage says. Keep plans separate
from conduct, analysis populations from observed outcomes, endpoint definitions
from measurement properties, and absence of reporting from absence of bias.
Reuse Result Evidence only when its exact premise answers the Domain question.
State inferred conclusions in the answer's `justification`, with the source
facts and any unresolved link. The server checks Evidence identity and structure;
you judge whether those facts support the answer.

Completion: each Source-owned assessable Result leaf has exact support, and each
active Domain answer has a valid basis for its stated premise and uncertainty.
