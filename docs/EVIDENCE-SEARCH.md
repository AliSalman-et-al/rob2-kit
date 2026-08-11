# Evidence search reference

Evidence navigation is question-scoped and obligation-driven:

```text
engine materializes exact stage scope
  -> bounded Search traversal
  -> complete-page triage and reviewed reads
  -> engine-validated stage outcome
  -> frozen question Evidence Bundle
  -> question answer or diagnostic stop
```

Use these operations only with the current engine-issued question WorkToken and
the session, frontier, context, and navigation hashes returned with it. Those
identities bind the Run, Result, Domain, signaling question, Guidance
obligation, complete Source inventory, and policy revisions. A stale or altered
identity fails closed.

## Staged breadth

Guidance defines propositions, purpose-specific passes, additive coverage
stages, and navigation intents for every signaling question. The first stage
usually searches the cheapest directly applicable report evidence. Wider
protocol, SAP, registry, supplement, or later-report roles become active only
when Guidance makes them mandatory or an attributable escalation trigger
fires. Domain 5 plan-versus-report questions include mandatory dated plan and
registry stages where those Sources are available.

The engine owns procedural breadth: complete inventory projection, exact Source
scope, traversal, triage, stage activation, receipts, and stopping outcomes.
Treat every issued scope identity as opaque and reuse it exactly in coverage
and completion calls; never reconstruct it from the visible Source list.
The agent chooses semantic query terms and judges the meaning of evidence and
trigger observations. Agent confidence cannot waive a mandatory stage, omit a
surfaced candidate, or convert a material limitation into No-information.

Source `criticality` describes the consequence of unavailability. It is not an
authority or search-priority ranking. Role, evidence purpose, chronology, and
estimated traversal cost determine stage order.

## Search

`search_evidence` uses contract `3.0.0`. Name the exact proposition, pass,
stage, intent, attempt, question, session, and expected navigation state from
the current context. Supply semantic query refinements only; the engine injects
the stage's ordered Source IDs and Parse identities. Caller-supplied Source IDs
are rejected.

```json
{
  "contract_version": "3.0.0",
  "run_id": "run:…",
  "work_token": {"token": "work-token:…"},
  "result_id": "result:…",
  "domain_id": "domain:randomization",
  "question_id": "sq:randomization:sequence",
  "session_content_hash": "sha256:…",
  "expected_navigation_state_hash": "sha256:…",
  "proposition_id": "proposition:…",
  "pass_id": "pass:…",
  "stage_id": "stage:…",
  "intent_id": "intent:…",
  "attempt_id": "attempt:…",
  "query": {"terms": ["allocation", "random"]}
}
```

Continue with the returned opaque continuation and the same attempt identity.
Replacing a selected query requires `supersede_attempt_id` and a nonblank
`supersession_rationale`. Superseded attempts remain auditable, and every
candidate they exposed still requires terminal triage.

Search pages are bounded navigation projections, not citable evidence. They can
contain ambiguous reading order, tables, captions, bibliography, duplicates,
or other-Trial material. Never freeze a preview, handle, or reconstruction.

## Reads and triage

`read_evidence` accepts an ordered batch bound to exactly the active question
and current navigation state. Every location handle must have been exposed in
that workflow. A successful view preserves canonical Source/Parse lineage,
bounded text, omissions, warnings, and an opaque `read_view_receipt`.
Copy each returned `location_handle` and `read_view_receipt` exactly. Never
reconstruct either value from preview text, Source metadata, or prior pages.

`submit_evidence_review` appends one exhaustive partition for exposed pages
from a single attempt. Its idempotency key is the reducer submission identity.
Retained candidates require an exact read receipt. Risk-bearing irrelevant,
unresolved non-self-contained, and non-lineage duplicate decisions also require
the appropriate receipt. A duplicate target must be an exposed, retained,
read-backed candidate in the same question; its target receipt is verified
against that candidate rather than the dismissed occurrence.

## Outcomes and stopping

Once every active intent in a stage is exhaustively navigated and triaged,
`submit_evidence_stage_outcome` records one closed outcome:

- `obligation_satisfied`
- `escalation_required`
- `source_unavailable_after_attempt`
- `scope_limitation_unresolved`
- `semantic_uncertainty_unresolved`

Escalation names observed closed triggers and activates their exact later
stages. Source-unavailable closure requires an engine-issued acquisition-attempt
receipt; an empty Search is not a substitute. Chronology-constrained stages use
attributable Source/Parse review facts and rematerialize a new inventory/session
revision when those facts change.

Use `scope_limitation_unresolved` only for an exact engine-materialized
unreadable, chronology, or cross-source limitation. A nonempty limited scope
still requires exhaustive traversal and triage. If source unavailability
coexists with another limitation, the outcome must also bind the exact
engine-issued acquisition receipt. Chronology diagnostics return a
recovery token only when an exact changed chronology fact can rematerialize the
context; unavailable, unreadable, and cross-source diagnostics instead require
source acquisition, reprocessing, or inventory reconciliation as directed.

A question can be answered only from a closed workflow plus an engine-frozen,
question-scoped Evidence Bundle. The bundle derives supporting and
contradicting claim identities from exact current review spans. Clean exhaustive
coverage with no qualifying evidence may produce an engine-verified basis: no
relevant evidence may support `no_information` only after the engine verifies
the exact closed workflow. The caller cannot assert either polarity or
No-information.

Material source or semantic uncertainty is terminal for scientific answering,
not answer-ready. The engine records a judgment-free diagnostic stop, publishes
the Result as diagnostic-ready, and continues unrelated Results. It never
fabricates a signaling-question answer or Domain judgment.
`complete_with_limitations` retains a material source or search uncertainty;
it is therefore diagnostic-terminal, never a successful evidence basis.

## Historical records

V2 navigation artifacts remain decodable for audit and release compatibility.
They are not accepted by active public contracts and no active path writes or
dual-writes v2 state.
