# Evidence search reference

Use this reference only with an engine-issued Domain-Evidence work item. The
v2 workflow is bounded and auditable:

```
selected search attempts -> complete-page triage -> ordered batch read -> review -> freeze
```

The active WorkToken authorizes the Trial, Result, Domain, and signaling
question scope. Copy it verbatim. Search candidates are lightweight,
non-citable navigation projections: they may include tables, captions,
footnotes, duplicate lineage, bibliography, ambiguous reading order, and
other-Trial material. Never freeze a candidate, preview, location handle, or
synthetic reconstruction.

## Search v2

`search_evidence` accepts a semantic `query`, `sq_id`, mandatory `pass_kind`,
stable `attempt_id`, and `attempt_kind` (`selected` or `exploratory`). A
guidance pass also has its exact `seed_family`; reuse it exactly in coverage. A selected attempt is required
for each `guidance_seed`, `trial_follow_up`, and `contradiction` pass of every
active SQ. These are distinct queries and must each be traversed to their last
page. For `trial_follow_up` and `contradiction`, omit `seed_family`.

```json
{
  "run_id": "run:…",
  "work_token": {"token": "work-token:…"},
  "result_id": "result:…",
  "sq_id": "sq:randomization:sequence",
  "query": {"terms": ["allocation"]},
  "pass_kind": "guidance_seed",
  "seed_family": "seed:allocation",
  "attempt_id": "attempt:allocation-guidance",
  "attempt_kind": "selected"
}
```

The page exposes `candidates`, opaque `continuation`, page/traversal metadata,
serialized response bytes, deterministic estimated response tokens, candidate
counts, source-character counts, limiting bounds, and warnings. Continue only
with the returned opaque continuation plus a closed `continue_reason` and
`continue_rationale`; never use a cursor.

Refinement is an explicit high-cost choice. Start a replacement attempt with
`supersedes_attempt_id` and `supersession_rationale`; do not overwrite or
silently abandon the earlier attempt. Superseded and exploratory attempts stay
in the audit universe and their exposed pages still require triage.

## Page triage and batch reads

For every exposed page, call `submit_evidence_review` before freeze. Submit the
exact complete `page_handles` partition and append-only triage revisions for
every candidate on those pages. Repeated submission with the exact same
idempotency key is safe; changing its content is not. Do not use automatic
disposition or omit an irrelevant/duplicate/ambiguous candidate.

`read_evidence` accepts one ordered batch rather than a single location read:

```json
{
  "run_id": "run:…",
  "work_token": {"token": "work-token:…"},
  "result_id": "result:…",
  "batch": {
    "scope": {
      "result_id": "result:…",
      "domain_id": "domain:randomization",
      "snapshot_hash": "sha256:…"
    },
    "items": [
      {
        "location_handle": "loc:…",
        "question_ids": ["sq:randomization:sequence"]
      }
    ]
  }
}
```

Batch outcomes retain input order. A successful view has source/Parse/canonical
lineage, bounded text, omissions, warnings, limiting bounds, response byte and
token measurements, and a `read_view_receipt`. Use that receipt for every
review span. Read views are non-mutating except for opaque-token storage.

## Freeze gate

Before `submit_domain_evidence`, every active SQ must have all mandatory
selected passes traversed and every candidate exposed by selected,
superseded, or exploratory attempts triaged with no unresolved item. The
engine materializes the durable coverage receipt and dependencies from that v2
state. Complete/no-information/passage scientific freezes fail closed if this
gate is not satisfied; an explicitly limited incomplete submission follows its
own declared limitation path and does not pretend to have complete coverage.
A complete search with no relevant evidence may support `no_information` only
when this v2 coverage and triage gate is satisfied.
`complete_with_limitations` retains a material source or search uncertainty;
`incomplete` records required searching or inspection that could not finish.

An exact scientific span still requires an issued `read_view_receipt`, bounds,
attribution, disposition, and rationale. Only the engine can materialize
frozen Evidence and its dependencies.

For a duplicate classification without engine-known duplicate lineage, submit
both the dismissed candidate's `read_view_receipt` and the retained target's
`retained_target_read_view_receipt`; each must display the exact exposed
context for the same signaling question. Duplicate target IDs are candidate
IDs, not canonical unit IDs.
