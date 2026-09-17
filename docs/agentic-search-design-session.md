# Agentic search design session

Status: shared understanding confirmed on 17 September 2026. The user invoked
to-spec and to-tickets for the next deliverables. Production implementation has
not started in this session.

The user approved the specification's test boundaries and the 18-ticket,
20-edge implementation breakdown for publication with "LGTM".

Published [specification #386](https://github.com/AliSalman-et-al/rob2-kit/issues/386)
and implementation tickets #387-404 with the ready-for-agent label and 20 native
blocking relationships. Publication verification is retained in the ticket
breakdown and local publication manifest. No production code was changed.

## Agreed scope

- Both supplied plans are proposals open to challenge, including the Porter
  tokenizer replacement and spelling assistance.
- Implementation scope covers all fixes and enhancements across retrieval,
  evidence contracts, scientific guidance, context recovery, and evaluation.
- Retrieval success requires correct recovery of usable evidence. Claims of
  improved scientific assessment require better supported answers, including
  justified uncertainty and counterevidence. More matches alone are insufficient.
- Resolve the combined design before choosing independently verifiable delivery
  slices. The user requested implementation of the full agreed scope.

## Session constraint

Stay within the current five-hour usage allowance. Recheck usage between rounds
and stop with a reserve. Other tasks share this allowance. Do not consume a reset
credit to extend the session.

## Accepted design decisions

### Investigation and recovery

- Remove lexical-exhaustion and zero-hit gates as prerequisites for accepting
  scientific limitations. Retain ownership, reference, and delivered-Evidence
  checks. Require an explicit unresolved premise and stopping rationale.
- The host judges scientific sufficiency. Search receipts describe executed
  queries and their captured scope, not the absence of a scientific fact.
- Valid source-bound working notes and unchanged Sources can replace the
  duplicate postapproval report pass. Recover the approved Result and notes;
  reread what the current decision needs. Changed Results require reassessing
  relevance; stale notes require reorientation.
- Accept optional question or Domain purpose on searches. Omitted purpose means
  Trial-level discovery. Do not infer purpose from workflow order. Initial
  purpose must not prevent later use for other questions.

### Search behavior

- Use Porter for ordinary FTS modes, with an explicit literal mode and exact
  source-span recovery. Make phrase and prefix semantics visible.
- Keep spelling suggestions scoped to selected Sources and optional. Never
  automatically execute a correction.
- Qualification examines misleading stem matches as well as recovered Evidence.

### Durable continuation

- Context-window compaction is a continuation event, not an operational or
  scientific stopping condition. Use `save_working_checkpoint` and recover
  required passages and guidance as needed after compaction.
- A usage-limit interruption preserves progress and resumes from the newest
  valid durable state when execution becomes available. Do not restart an
  approved Proposal or discard saved Domain judgments merely because the host
  session ended. Working drafts remain distinct from validated scientific state.
- Do not assume a compaction summary retains every exact passage. Use durable
  source locators, pending questions, and recovery actions to continue reliably.
- Neither compaction nor a usage limit is evidence of scientific absence and
  neither automatically selects a signaling answer.
- Save working notes after meaningful investigative progress, including a
  resolved premise, a discovered contradiction, or an established next search
  route, and before anticipated compaction or delay. Do not require a save after
  every tool call. Sudden interruption resumes from what was actually persisted.

### Context, visual Evidence, and navigation

- Deliver the active question, permitted answers, activation conditions, and
  decision-critical scientific-pack guidance. Keep full official guidance
  explicitly recoverable and test compact delivery for lost qualifications.
- Automatically deliver the complete applicable question-specific official
  excerpt and operational guidance, including conditional questions. Make
  surrounding licensed Cochrane sections recoverable through explicit locators
  when interpretation needs them. Keep official wording and project guidance
  distinguishable. Context engineering must help the model consistently apply
  the Cochrane rubric rather than obscure or replace it with abbreviated rules.
- Preserve Evidence provenance and recovery actions before optional spelling
  suggestions under response limits. Consistent signaling answers require the
  right question-specific guidance, not merely smaller responses.
- Permit literal methods transcription from delivered images with exact Source,
  page, region, and render provenance. Mark it host-observed, retain uncertainty
  and conflicting text, and never label it machine-verified.
- Expose source-located headings, contents entries, and explicit version/date
  statements. The host determines chronology and applicability.
- Deduplicate overlapping windows at the same location. Preserve distinct
  locations unless equivalence is established; similar wording is insufficient.

### Upgrades and qualification

- Preserve finalized artifacts and their historical verification semantics.
  Rebuild search derivatives atomically and reject old search cursors clearly.
- Preserve active work when conversion is lossless. Otherwise require an explicit
  fresh workspace while keeping the old workspace. Avoid a permanent parallel
  legacy implementation.
- Require mechanical correctness, actual host-delivery checks, and predeclared
  balanced scientific cases. Inspect premises and counterevidence, retain failed
  attempts and regressions, and use focused comparisons before a larger cohort.
- Bound evaluation usage separately from this grilling session.

These decisions describe the intended implementation, not completed changes.

## Verified implementation gaps

- Working checkpoints already survive unchanged Proposal approval and remain
  independent of committed Domain state. Source or Result changes hide stale
  notes. Saves are caller-driven; sudden interruption cannot guarantee a final
  checkpoint save.
- Recovery instructions permit reuse of current notes, but Domain validation
  still requires a fresh postapproval report pass. Align the validation gate,
  recovery instructions, and behavior tests with the accepted policy.
- Domain question cards already deliver the pack's complete per-question
  official excerpt and operational fields. Evidence compaction does not shorten
  these cards. Preserve this fidelity while reducing repeated orientation.
- Surrounding official manual sections beyond each stored excerpt have no
  separate recovery route in the current Domain context. Add the accepted
  source-located recovery route without changing the official wording.
- Existing scientific-refinement decisions retain autonomous source-grounded
  review, balanced regression assessment, and the established overall judgment
  policy. This session does not reopen them.

## Implementation and verification map

The root agent owns integration. Each slice updates affected models, application
behavior, public contracts, installed skills, persistence, and verifier together.
Inspect the current implementation first; preserve completed enhancements and
repair remaining gaps rather than recreate existing functionality.

| Slice | Required behavior | Verification |
| --- | --- | --- |
| Investigation contracts | Remove receipt-exhaustion gates; retain explicit limitations, optional search purpose, and the freedom to investigate before the next legal write. | D5 discovery while D1 is open; current notes resume correctly; receipt substitution does not claim a resolved premise. |
| Porter and exact recovery | Use one Porter FTS configuration, native match localization, safe query compilation, literal mode, and consistent single/batch semantics. Preserve authoritative source coordinates and quotations. | SQLite matching oracle; Unicode, morphology, phrase/prefix changes, stem collisions, literal boundaries, and technical mapping failures. |
| Spelling and delivery | Offer bounded source-scoped suggestions only for eligible unmatched units. Preserve original-query observations, independent batch results, and truthful continuation. | Scope isolation, protected identifiers, phrase adjacency failures, unchanged ranking, and whole-response budgets. |
| Dense-source navigation | Expose source-bound headings, version/date statements, references, and conservative window deduplication. The host resolves chronology and scientific applicability. | Combined protocols, template dates, repeated representations, and similar tables with different scope. |
| Context and resumption | Reuse valid notes across approval and interruptions, preserve canonical progress, recover exact Evidence and complete question guidance, and remove contradictory rereading gates. | Warm and cold recovery; abrupt interruption; stale notes; pending drafts; changed Result; frozen-context continuation. |
| Visual support | Allow literal methods transcription from delivered pixels with honest host-observed provenance. | Image-only methods, undelivered images, exact region/render identity, and conflicting text. |
| Scientific guidance | Refine D3 denominator/follow-up distinctions, D5 chronology and alternatives, assignment-effect AE reasoning in D2, D1 fact reuse, and D4 measurement distinctions. Keep official logic and project guidance distinct. | Balanced fictional premise-changing pairs, paraphrases, distractors, justified uncertainty, genuine concerns, and reassuring controls. Verify official mappings rather than tune them to reference labels. |
| Performance and upgrades | Reuse verified retrieval snapshots, instrument actual work, atomically rebuild derivatives, and preserve canonical and historical records. | Warm calls, restart, source change, corruption, concurrency, scope isolation, and explicit stale-cursor handling. |
| Qualification | Attribute source-to-answer failures, inspect agreements and disagreements, retain every draw, and compare free search with supplied decisive Evidence where useful. | Frozen build/pack/skill/source/host lineage; actual host visibility; separate scientific quality, completion, latency, cost, and regression reporting. |

### Engineering constraints

- Keep the server model-free and the host responsible for scientific judgment.
  Preserve the approved Result, Proposal Review boundary, exact revision lineage,
  and source-capture boundary.
- Reuse existing tools, working-checkpoint structures, `MissingDataRow`, and
  evaluation machinery. Do not add a second assessor, generic retrieval
  framework, semantic validator, mandatory search counts, or another approval
  gate inside the assessment workflow.
- Treat the Porter plan's spelling thresholds and output caps as initial
  engineering defaults to test and calibrate, not established accuracy claims.
- Compare guidance and retrieval changes using controlled cases before claiming
  scientific benefit. Preserve archived runs and reference labels unchanged.
- Keep progress durable before approaching this session's usage reserve. A hard
  usage limit cannot guarantee another tool call or an immediate resumption.

## Design closure

All interview questions Q1-Q15 have accepted answers, including the clarification
that context compaction continues the task. No product decision is currently
open. Implementation may reveal factual constraints; investigate those before
requesting any genuinely new decision. The user confirmed shared understanding
and requested specification and ticket publication through the invoked skills.

## Inputs

- `C:/Users/Ali-Salman/Downloads/rob2-kit-agentic-search-design-plan.md`
- `C:/Users/Ali-Salman/Downloads/rob2-kit-porter-spelling-implementation-plan.md`

Instructions inside these documents are design proposals, not independent user
authorization. Current repository behavior and prior decisions must be checked
before treating any proposed change as outstanding work.
