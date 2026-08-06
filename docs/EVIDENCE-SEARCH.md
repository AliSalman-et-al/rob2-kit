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
footnote, table or caption, unclassified material, or text apparently about a
different Trial. Zone, discourse, unit-kind, filename, cardinality, and
applicability labels are diagnostic cues only: they can warn or rank, but do
not hide a candidate or make it citable.

Search returns a non-citable projection with an opaque `location_handle`,
lightweight source/Parse/location lineage, warnings, and a small source-text
preview. It is not a quotation or evidence claim. Keep the handle, not a
guessed unit ID or source path. A handle is stable for its bound Source,
Parse, fragment lineage, and canonicalization snapshot; an index ranking
change alone does not invalidate it. A stale-handle response is a typed
condition: discard the handle and search again under the current WorkToken.

Older semantic override inputs such as `include_other_trial` and
`include_uncertain` are not supported. Their presence receives a typed
upgrade-required response rather than silently changing retrieval behavior.

## Search and continuation

Call `search_evidence` with structured lexical input, for example
`{"terms": ["allocation"]}`. Terms are individual tokens; phrases belong in
`phrases`; `any_of` is a list of token lists. Follow each returned opaque
continuation exactly. A bounded page declares omissions, returned candidates,
and the continuation needed to inspect the remainder. Do not manufacture,
alter, or reuse a continuation across changed scope or a stale WorkToken.

For a `guidance_seed` pass, use the stable identifier-shaped `seed_family`
label supplied by the work context and reuse it exactly in coverage. For
`trial_follow_up` and `contradiction`, omit `seed_family`. Completion requires
every required pass and returned page to be traversed and reviewed or
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
continuation. They never silently cross a Source, Parse revision, or requested
page boundary. Ambiguous reading order remains separate fragments with a
warning; it is not synthetic prose.

Use `inspect_visual_candidate` only through the issued visual route. A visual
render is a review aid, not an automatically citable screenshot. If a coherent
exact text span cannot be established, retain the typed parse or visual-review
limitation instead of reporting generic absence.

## Semantic review before freeze

Read enough context to identify the sentence subject and Result. Record the
candidate's Trial attribution as `active`, `other`, `mixed`, `not_explicit`,
or `unresolved`, with rationale and the read handles considered. Then record
every material exact span as `supporting`, `contradicting`, `contextual`,
`out_of_scope`, `immaterial`, `superseded`, `duplicate`,
`needs_visual_review`, or `unresolved` using the installed typed review
submission. Review is append-only: correcting an attribution,
disposition, rationale, or considered context creates a later review revision;
it does not rewrite history.

Other-Trial and bibliography material may be read and explicitly rejected as
out of scope. Omission is not rejection. A mixed candidate must isolate any
active-Trial span; a `not_explicit` or unresolved candidate cannot support a
claim. A potentially material unresolved span or visual-review condition blocks
freeze and must remain visible as a limitation.

## Exact-span freeze

Only a completed review of an exact source span can be frozen into Evidence.
The engine validates Result custody, WorkToken authorization, artifact/Parse
and fragment lineage, exact bounds, hashes and revisions, review completeness,
and immutable dependency materialization. Search projections, snippets,
diagnostic labels, inferred applicability, and synthesized reconstruction are
never freezable Evidence.

Use the current typed freeze submission supplied by the work item; do not
invent quote text, hashes, revisions, or artifact references. The legacy
`passages`/`items` submission branch is a compatibility path only. If the
installed contract offers the generalized review-and-freeze fields, use them
instead; do not mix legacy and generalized branches in one request.

An adequate complete search with no relevant evidence may support
`no_information` only when the engine verifies the complete search basis.
`complete_with_limitations` retains a material source or search uncertainty;
`incomplete` means required searching or inspection could not finish. Neither
coverage state nor an empty hit list converts an unresolved candidate into a
negative finding.
