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

During evidence work, use only the v2 bounded loop: selected search attempts,
complete-page triage, ordered batch reads, exact-span review, then freeze.
Search candidates are lightweight and non-citable. They can include uncertain
fragments, bibliography, tables, captions, footnotes, unclassified text, and
apparent other-Trial text. Labels can explain or rank a candidate, but never
hide it or make it citable.

For every active signaling question, issue distinct selected attempts for the
mandatory `guidance_seed`, `trial_follow_up`, and `contradiction` passes. Give
each attempt a stable `attempt_id`; selected and exploratory attempts are
different. Use a high-cost decision to refine or explicitly supersede an
attempt, recording the superseded attempt ID and rationale. When continuing a
page, use the opaque continuation with its closed continuation reason and
rationale. Traverse every page of each selected attempt; a convenient hit or
first page never completes coverage.

After every exposed page—including a superseded or exploratory attempt—call
`submit_evidence_review` with its exact page handles and append-only candidate
triage revisions. Triage every candidate on those pages. Do not auto-dispose,
drop, or silently reclassify candidates. Retain the receipt/audit trail when a
candidate is irrelevant, duplicated, or needs more review.

Batch selected `location_handle` values through `read_evidence` using the
ordered v2 batch request. Read views are bounded, preserve source/Parse
lineage and warnings, and issue a `read_view_receipt`. Use that receipt on each
exact review span. A stale handle, continuation, or batch outcome is a typed
recovery condition: follow its recovery, obtain current work context when
needed, and do not reuse stale inputs. Handles and search previews navigate
only; they are never frozen provenance.

Only freeze through the current `submit_domain_evidence` contract after v2
coverage and triage are ready: all selected mandatory passes traversed and all
exposed candidates resolved. Exact review spans remain append-only and bind
their read-view receipt, bounds, trial attribution, disposition, and rationale.
An unresolved candidate, uncertain reading order, or visual-review condition
remains a typed limitation and blocks an unsupported complete/no-information
freeze. Never cite a search candidate, snippet, parser label, inferred
applicability, or synthetic reconstruction.

When a retry or dynamic branch returns, discard the previous work token and
context, call `get_work_context` for the new token, and copy its current
`result_id` and `domain_id` verbatim. This preserves strict dependency and
branch validation while allowing legitimate engine-directed retries.

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
