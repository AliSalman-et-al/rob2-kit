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

During evidence work, use the generalized bounded loop: `search_evidence`,
`read_evidence` or its issued visual route, semantic review, then exact-span
freeze. Search results are visible candidates, not eligible Evidence. They may
include uncertain fragments, bibliography, tables, footnotes, unclassified
text, and apparent other-Trial text. Labels can explain or rank a result, but
never make it disappear or make it citable.

Keep the opaque `location_handle` returned by search and pass it unchanged to
reading. Expand only by the bounded `unit`, `neighbors`, `section`, `window`,
`page`, or `render` operation the response supports, and follow its opaque
continuation verbatim. A stale handle or continuation is a typed recovery
condition: discard it and restart from the current WorkToken. Handles navigate
only; they are never frozen provenance.

Before freeze, call `read_evidence` and submit its opaque `read_view_receipt`
on every exact review span. A review revision is one candidate and one `sq_id`;
it may aggregate independently attributed spans. Each span records
`trial_attribution` as `active`, `other`, `not_explicit`, or `unresolved`, an
exact-span disposition, and rationale. An `active` span also records an
attributable bounded-context rationale. Other-Trial or reference material may
be explicitly reviewed and rejected, but omission is not rejection. An
unresolved retained span, uncertain source order, or visual-review condition
remains a typed limitation and blocks an unsupported freeze. Never cite a
non-citable search projection, snippet, parser label, inferred applicability,
or synthetic reconstruction.

Use the `submit_domain_evidence` 1.2.0 review-and-passage shape. Each review
has `sq_id`; each span supplies `read_view_receipt`, exact bounds,
`trial_attribution`, disposition, and rationale. Only an `active` span with a
`supporting` or `contradicting` disposition authorizes an exact textual claim.
Other and not-explicit spans can record non-substantive dispositions only.

For the legacy `submit_domain_evidence` branch, prefer `passages`. It is
mutually exclusive with legacy `items`, `evidence_by_question`,
`candidate_dispositions`, and `conflicts`; choose one branch and do not send
empty fields from another branch. Use the exact field name
`coverage_limitations` (never `limitation`). This compatibility branch does not
replace the current review-and-freeze contract when that contract is available.

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
