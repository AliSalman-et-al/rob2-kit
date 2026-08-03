# Evidence search reference

Use this reference when the engine issues an evidence work item. Start from the
bounded context it returns, search through the typed MCP tools, and inspect the
issued evidence units or visual candidates only. Follow returned pagination and
coverage constraints; do not treat a context limit or a lack of a convenient
hit as absence of evidence.

Record the required candidate dispositions and coverage through the supplied
typed submission. Material ambiguity, incomplete coverage, unreadable sources,
or a conflict remains a reported limitation or blocker. The pinned engine and
packs decide the evidence protocol and all decision-relevant behavior.

Use structured lexical input such as `{"terms": ["allocation"]}`. A
`guidance_seed` pass carries its issued `seed_family`; for `trial_follow_up` and
`contradiction`, omit `seed_family`. Terms are individual tokens, phrases belong
in `phrases`, and `any_of` is a list of token lists. Completion means every
required pass is complete, every pagination cursor is traversed, and every
unique returned unit has its engine-required disposition or recorded
limitation.

To cite readable canonical text, pass the `unit_id` returned by
`search_evidence` or `read_evidence` to `submit_domain_evidence.passages` with
the exact `span_start`, `span_end`, `claim_type`, and applicable
`question_ids`. rob2-kit materializes the quote and all immutable hashes and
references. Never calculate a quote hash or invent an entity, revision, or
artifact reference in the Harness.
