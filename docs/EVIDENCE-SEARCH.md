# Evidence search reference

Use this reference when the engine issues an evidence work item. Start from the
bounded context it returns, search through the typed MCP tools, and inspect the
issued evidence units or visual candidates only. Follow returned pagination and
coverage constraints; do not treat a context limit or a lack of a convenient
hit as absence of evidence.

Copy the active Domain-evidence `work_token` from `continue_run` into both
`search_evidence` and `read_evidence`. The token supplies the Trial, Result,
Domain, and eligible Source scope; do not reconstruct those IDs from chat
history or broaden a failed search. Search returns non-citable projections;
only exact spans from the returned canonical unit can be submitted as evidence.
Search and read are engine-bounded (hit, character, and neighbor limits are not
caller-controlled). Use the returned `unit_id` with `read_evidence` next and
copy any `next_cursor` verbatim; after review, call `submit_domain_evidence` to
record coverage and dispositions.
Use `read_evidence` with `mode="unit"` by default, `mode="neighbors"` for a
small same-section expansion, or `mode="section"` for bounded paginated
section context. Continue a section only with its returned opaque cursor.

Record the required candidate dispositions and coverage through the supplied
typed submission. Material ambiguity, incomplete coverage, unreadable sources,
or a conflict remains a reported limitation or blocker. The pinned engine and
packs decide the evidence protocol and all decision-relevant behavior.
Do not construct abbreviated coverage receipts: submit a receipt only when a
tool has supplied the complete typed receipt object; otherwise omit it.

For the legacy candidate-disposition branch, use only the exact enum values
`supporting`, `contradicting`, `contextual`, `duplicate`, `out_of_scope`,
`immaterial`, `superseded`, or `unresolved`; `irrelevant` is not accepted.
When using exact `passages`, do not also send legacy `items`,
`evidence_by_question`, `candidate_dispositions`, or `conflicts`—these branches
are mutually exclusive. Record residual source/search issues in the
`coverage_limitations` list (the singular `limitation` field does not exist).

An adequate completed search with no relevant evidence remains `complete` and
may support `no_information` when complete receipts establish that basis. Use
`complete_with_limitations` only when completed work retains a material source
or search uncertainty. Use `incomplete` only when required searching or source
inspection could not be completed; only this state prevents an assessment
report from being generated.

Use structured lexical input such as `{"terms": ["allocation"]}`. A
`guidance_seed` pass uses a stable identifier-shaped `seed_family` label chosen
by the caller and reused exactly in its coverage receipt; for `trial_follow_up`
and `contradiction`, omit `seed_family`. Terms are individual tokens, phrases
belong in `phrases`, and `any_of` is a list of token lists. Completion means every
required pass is complete, every pagination cursor is traversed, and every
unique returned unit has its engine-required disposition or recorded
limitation.

To cite readable canonical text, pass the `unit_id` returned by
`search_evidence` or `read_evidence` to `submit_domain_evidence.passages` with
the exact `span_start`, `claim_type`, and applicable `question_ids`. Supply
`span_end` for a partial unit or omit it to select through the unit's end.
rob2-kit materializes the quote and all immutable hashes and
references. Never calculate a quote hash or invent an entity, revision, or
artifact reference in the Harness. Passage submission is checked against the
active Domain WorkToken; each passage's `question_ids` supplies its own
question attribution, so one submission may contain passages for multiple
questions in that Domain.
