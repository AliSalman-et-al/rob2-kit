---
name: rob2-assess
description: assess or judge RoB 2, continue a Run, or explain its terminal static report.
---

# RoB 2 assessment

If the project is uninitialized, has an unconfirmed Run definition, or needs a
new run, hand initialization to `rob2-init` and use
`../references/RUN-DEFINITION.md` only for that handoff.
Otherwise use the static `rob2` tools to resume the confirmed run,
request the next engine-issued work item, inspect only bounded evidence and
visual candidates, and submit typed work with the supplied mutation context.

Drive one engine-issued item at a time: `continue_run`, `get_work_context`, then
the named submission tool with the returned work token and identifiers copied
verbatim. After a successful submission, return to `continue_run`. Completion
means the directive is terminal, not merely that all five Domains were visited.

For `submit_domain_evidence`, prefer `passages`. The `passages` branch is
mutually exclusive with legacy `items`, `evidence_by_question`,
`candidate_dispositions`, and `conflicts`; choose one branch and do not send
empty legacy fields alongside passages. Use the exact field name
`coverage_limitations` (never `limitation`). Candidate dispositions accept only
`supporting`, `contradicting`, `contextual`, `duplicate`, `out_of_scope`,
`immaterial`, `superseded`, or `unresolved`; `irrelevant` is not an alias.

When a retry or dynamic branch returns, discard the previous work token and
context, call `get_work_context` for the new token, and copy its current
`result_id` and `domain_id` verbatim. This preserves strict dependency and
branch validation while allowing legitimate engine-directed retries.

For progressively disclosed operating detail, consult
`../references/HARNESS-WORKFLOW.md`, `../references/EVIDENCE-SEARCH.md`, and
`../references/SIGNALING-QUESTIONS.md` only when their topic is active.
Narrate meaningful Trial, Result, and Domain milestones, blockers, interruption
consequences, and the terminal report summary in plain language. Do not narrate
raw protocol identifiers, work tokens, cursors, or polling noise.

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
