---
name: rob2-assess
description: Prepare an evidence-grounded RoB 2 assessment and materialize a static report.
---

# RoB 2 assessment

If the project is not initialized or needs a new run, hand initialization to
`rob2-init`. Otherwise use the static `rob2` tools to resume the confirmed run,
request the next engine-issued work item, inspect only bounded evidence and
visual candidates, and submit typed work with the supplied mutation context.

For progressively disclosed operating detail, consult
`../references/HARNESS-WORKFLOW.md`, `../references/EVIDENCE-SEARCH.md`, and
`../references/SIGNALING-QUESTIONS.md` only when their topic is active.
Narrate meaningful Trial, Result, and Domain milestones, blockers, interruption
consequences, and the terminal report summary in plain language. Do not narrate
raw protocol identifiers, work tokens, cursors, or polling noise.

Treat every structured status as authoritative. On `work_required`, complete
only the returned work item. On `review_pending`, end the turn without further
inference. On `retryable_interruption`, preserve state and retry only within
the returned bounds. On `trial_problem` or `run_integrity_failure`, report the
condition without inventing recovery.

When preparation reaches a terminal outcome, report the static Run/Result
artifacts and their limitations. Human audit happens outside the preparation
workflow; this skill never performs a review action, override, or sign-off.

All RoB 2 wording, branching, guidance, and judgments come from the pinned
packs and bounded tools. Do not reproduce or infer normative logic here.
