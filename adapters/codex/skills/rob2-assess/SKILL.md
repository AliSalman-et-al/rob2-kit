---
name: rob2-assess
description: assess or judge RoB 2, continue a Run, or explain its terminal static report.
---

# RoB 2 assessment

If the project is uninitialized, has an unconfirmed Run definition, or needs a
new run, hand initialization to `rob2-init` and use
`../references/RUN-DEFINITION.md` only for that handoff.
Otherwise use the static `rob2` tools to resume the confirmed run, request the
next engine-issued work item, inspect only bounded evidence and visual
candidates, and submit typed work with the supplied mutation context.

Drive one engine-issued item at a time: `continue_run`, `get_work_context`, then
the named submission tool with the returned work token and identifiers copied
verbatim. After a successful submission, return to `continue_run`. Completion
means the directive is terminal, not merely that all five Domains were visited.

During evidence work, use only the v3 question workflow: read the issued
Guidance obligation and all bounded context pages, complete its additive Search
stages, freeze one question Evidence Bundle, then submit that question step.
Search candidates are lightweight and non-citable. They can include uncertain
fragments, bibliography, tables, captions, footnotes, unclassified text, and
apparent other-Trial text. Labels can explain or rank a candidate, but never
hide it or make it citable.

Treat the engine-issued question frontier, propositions, passes, stage
activations, navigation intents, Source inventory, chronology constraints, and
limitations as authoritative. Follow the engine's recommended cheap-to-
expensive Source order, but do not confuse Source `criticality` with search
priority or authority. The engine owns procedural breadth and exact stage
scope. The agent chooses semantic query terms, reads context, identifies
support and contradiction, and judges whether an observed trigger requires
escalation. Agent confidence cannot waive a mandatory stage, omit a surfaced
candidate, or turn a material limitation into No-information.

Copy the current `question_id`, `session_content_hash`, `frontier_entry_hash`,
`expected_navigation_state_hash`, proposition, pass, stage, intent, and Source/
Parse identities exactly. Inspect every issued context page needed to understand
the obligation before searching. If chronology is unresolved, use
`submit_source_chronology_review` only with an exact read receipt. Its accepted
fact rematerializes the inventory/session: discard stale tokens and hashes and
obtain fresh context before continuing.

Within each active stage, give every selected Search attempt a stable
`attempt_id`. Use a high-cost decision to refine or explicitly supersede an
attempt, recording the superseded attempt and rationale. Continue with the
opaque continuation and its closed continuation reason. Traverse every page of
each selected attempt; a convenient hit, first page, or zero-hit query never
establishes coverage or absence.

After every exposed page—including a superseded or exploratory attempt—call
`submit_evidence_review` with its exact page handles and append-only candidate
triage revisions. Triage every candidate on those pages. Do not auto-dispose,
drop, or silently reclassify candidates. Retain the receipt/audit trail when a
candidate is irrelevant, duplicated, or needs more review.

Batch selected `location_handle` values through `read_evidence` using the
ordered v3 question request. Read views are bounded, preserve source/Parse
lineage and warnings, and issue a `read_view_receipt`. Use that receipt on each
exact review span. A stale handle, continuation, or batch outcome is a typed
recovery condition: follow its recovery, obtain current work context when
needed, and do not reuse stale inputs. Handles and search previews navigate
only; they are never frozen provenance.

After exhaustive navigation and triage for an active stage, call
`submit_evidence_stage_outcome` with exactly one permitted closed outcome:
`obligation_satisfied`, `escalation_required`,
`source_unavailable_after_attempt`, `scope_limitation_unresolved`, or
`semantic_uncertainty_unresolved`.
Escalation names observed closed triggers. Source-unavailable closure requires
the engine-issued acquisition-attempt receipt. Never substitute an empty Search
or a free-text assertion for an exact receipt. Traverse every available Source
in a mixed limited scope, and retain the receipt requirement when unavailability
coexists with another limitation.

When the question workflow is answer-ready, call
`materialize_question_evidence_bundle` with exact current review revisions,
passages, visual transcriptions, frontier identity, and idempotency context.
Then call `submit_question_step` once with the returned question-scoped bundle
binding, permitted answer, and concise rationale. The engine derives claim
polarity and any No-information basis; do not assert either through prose.
To correct an accepted answer, use only its returned `correction_token` with
`correct_question_step`, the exact predecessor hash, and the same Evidence
Bundle; a correction may invalidate dependent answers and requires fresh work.
Material source or semantic uncertainty is diagnostic, not answer-ready: submit
the engine-authorized diagnostic stop without an answer, rationale, or Evidence
Bundle. Use a returned evidence-recovery token only for a changed attributable
chronology fact. Otherwise acquire, reprocess, or add the Source named by the
diagnostic and let inventory reconciliation reopen the affected Result.
Continue unrelated active questions or Results as directed.

Exact review spans remain append-only and bind their read receipt, bounds,
Trial attribution, disposition, and rationale. An unresolved candidate,
uncertain reading order, chronology gap, or visual-review condition remains a
typed limitation and blocks unsupported answering. Never cite a Search
candidate, snippet, parser label, inferred applicability, or synthetic
reconstruction.

After each accepted question answer, diagnostic stop, chronology revision,
retry, or dynamic branch, discard the previous work token and context. Return
to `continue_run`, load every bounded page named by the new work item through
`get_work_context`, and copy its current Result, Domain, question, frontier,
session, and navigation identities verbatim.

For progressively disclosed operating detail, consult
`../references/HARNESS-WORKFLOW.md`, `../references/EVIDENCE-SEARCH.md`, and
`../references/SIGNALING-QUESTIONS.md` only when their topic is active.
Narrate meaningful Trial, Result, and Domain milestones, blockers, interruption
consequences, and the terminal report summary in plain language. Do not narrate
raw protocol identifiers, work tokens, opaque continuations, or polling noise.

Treat every structured status as authoritative. On `agent_work_required`, complete
only the returned work item. On `run_complete`, present the static report
summary and end the turn. On `retry`, preserve state and retry only within
the returned bounds. On `trial_problem` or `run_integrity_failure`, report the
condition without inventing recovery.

When preparation reaches a terminal outcome, report the static Run/Result
artifacts and their limitations. Human audit happens outside the preparation
workflow; this skill never edits or mutates a static report.

All RoB 2 wording, branching, guidance, and judgments come from the pinned
packs and bounded tools. Do not reproduce or infer normative logic here.
