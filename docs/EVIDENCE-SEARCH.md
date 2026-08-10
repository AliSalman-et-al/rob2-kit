# Evidence search reference

Use this reference for an engine-issued evidence work item. Evidence work is a
bounded, repeatable workflow:

```
search -> read/expand -> semantic review -> exact-span freeze
```

The active Domain-evidence `work_token` supplies the mechanically authorized
Trial, Result, Domain, Source, and Parse scope. Copy it verbatim to every
evidence action. Do not reconstruct identifiers from chat history, widen the
scope, or infer that a search limit means there is no evidence.

## Visibility is not eligibility

Search is deliberately broad within the authorized scope. A hit can be a
canonical unit or an uncertain source fragment, including a bibliography,
footnote, table or caption, unclassified material, or text about any Trial.
Zone, unit-kind, filename, and cardinality are structural diagnostic cues
only: they can warn or rank, but do not hide a candidate or make it citable.
Parser output has no applicability or scientific-scope labels; those are
authorized by WorkTokens and established through attributable review.

Search returns a non-citable projection with an opaque `location_handle`,
lightweight source/Parse/location lineage, warnings, and a small source-text
preview. It is not a quotation or evidence claim. Keep the handle, not a
guessed unit ID or source path. A handle is stable for its bound Source,
Parse, fragment lineage, and canonicalization snapshot; an index ranking
change alone does not invalidate it. A stale-handle response is a typed
condition: discard the handle and search again under the current WorkToken.

Parser Trial-discourse labels are not an input, output, warning, filter, or
eligibility signal. Attribution is established only by the reviewed span.

## Search and continuation

Call `search_evidence` with structured lexical input, for example
`{"terms": ["allocation"]}`. Terms are individual tokens; phrases belong in
`phrases`; `any_of` is a list of token lists. Follow each returned opaque
continuation exactly. A bounded page declares omissions, returned candidates,
and the continuation needed to inspect the remainder. Do not manufacture,
alter, or reuse a continuation across changed scope or a stale WorkToken.

For a `guidance_seed` pass, pass the stable identifier-shaped `seed_family`
label supplied by the work context as its own top-level `search_evidence`
argument, a sibling of `query` rather than a field inside it, and reuse it
exactly in coverage:

```json
{
  "query": {"terms": ["allocation"]},
  "pass_kind": "guidance_seed",
  "seed_family": "seed:sq-1a"
}
```

For `trial_follow_up` and `contradiction`, omit `seed_family` entirely. Completion
requires every required pass and returned page to be traversed and reviewed or
explicitly limited; a convenient hit or a first page is never enough.

## Read and expand context

Pass the returned `location_handle` to `read_evidence`. Start with the smallest
useful view, then request bounded expansion as needed:

- `unit` reads the anchored canonical unit or source fragment.
- `neighbors` and `section` provide bounded same-source context.
- `window` provides a bounded character or line continuation for an oversized
  unit.
- `page` returns page-scoped source context.
- `render` supplies a bounded visual fallback when text order, provenance, or
  content cannot be established safely.

Read responses preserve source-authored text in deterministic order and expose
the original hit, Source artifact, Parse revision, page/geometry, source
bounds, fragment lineage, applied bounds, warnings, omissions, and any stable
continuation. Each response also issues an opaque `read_view_receipt` binding
the exact snapshot, requested/applied mode, continuation input/output, displayed units,
bounds, content hashes, and source/Parse/canonical lineage. Submit that receipt with a review span; never use
a location handle as frozen provenance. They never silently cross a Source, Parse revision, or requested
page boundary. Ambiguous reading order remains separate fragments with a
warning; it is not synthetic prose.

Use `inspect_visual_candidate` only through the issued visual route. A visual
render is a review aid, not an automatically citable screenshot. If a coherent
exact text span cannot be established, retain the typed parse or visual-review
limitation instead of reporting generic absence.

## Semantic review before freeze

Read enough context to identify the sentence subject and Result. Record each
exact span's Trial attribution as `active`, `other`, `not_explicit`, or
`unresolved`, with its issued read-view receipt and rationale. A revision is
for one `sq_id`, while one candidate can have separate revisions/spans for
different questions. Submit the 1.2.0 Domain-Evidence contract with `sq_id`
and span-level review inputs. Then record every material exact span as `supporting`, `contradicting`, `contextual`,
`out_of_scope`, `immaterial`, `superseded`, `duplicate`,
`needs_visual_review`, or `unresolved` using the installed typed review
submission. Review is append-only: correcting an attribution,
disposition, rationale, or considered context creates a later review revision;
it does not rewrite history.

Other-Trial and bibliography material may be read and explicitly rejected as
out of scope. Omission is not rejection. `other` and `not_explicit` spans may
complete only non-substantive dispositions. A passage whose Trial is not
explicit may become `active` only after bounded context is recorded in the
receipt descriptor and the reviewer records the resolution rationale. An
unresolved span or visual-review condition blocks freeze and must remain
visible as a limitation.

## Exact-span freeze

Only an `active` supporting or contradicting review of an exact source span can
authorize qualifying textual Evidence. The engine commits that review before
materializing the claim, which stores the authorizing review reference and
engine-derived span ID. The engine validates Result custody, WorkToken authorization, artifact/Parse
and fragment lineage, exact bounds, hashes and revisions, review completeness,
and immutable dependency materialization. Parsers and Canonical evidence units
carry source-preserving structure, not Trial, Result, Domain, or signaling-question
meaning; that scientific scope comes from the engine-issued work scope and the
attributable exact-span review. Search projections, snippets, and synthesized
reconstruction are never freezable Evidence.

Use the current typed freeze submission supplied by the work item; do not
invent quote text, hashes, revisions, artifact references, or span IDs. Do not
mix textual passages with visual-transcription items in one request.

An adequate complete search with no relevant evidence may support
`no_information` only when the engine verifies the complete search basis.
`complete_with_limitations` retains a material source or search uncertainty;
`incomplete` means required searching or inspection could not finish. Neither
coverage state nor an empty hit list converts an unresolved candidate into a
negative finding.
