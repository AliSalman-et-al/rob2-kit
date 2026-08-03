# Harness workflow reference

Use this reference only when a run-control choice or a user-facing progress
update is needed. The MCP response remains authoritative.

## Start, resume, or start new

Call `prepare_run` with the required `project_root` on every new session. If it binds a Current run, describe it
as a resume and continue from its returned state. Start a new run only after
the operator explicitly asks to replace the Current run; pass the explicit
start-new intent rather than inferring it from a new conversation.

Present the Run proposal in plain language, identify material ambiguity, and
obtain the one-time confirmation before preparation. Do not represent proposal
acceptance as assessment approval.

For source classification, classify exactly the sources returned by
`get_work_context`; proposal registry candidates are orientation data unless
that work context also issues them. For Result resolution, copy the issued
Result identity and its identifier-shaped fields, then add only the observed
estimate and attributable locator. Completion means every object submitted was
issued for the current work token.

If the engine returns `retry` or a dynamic branch, rebind the next operation to
the newly returned work item: call `get_work_context` with its fresh token and
copy the current `result_id` and `domain_id` verbatim. Do not reuse stale
tokens, prior context, or a project root inferred from conversation history.

## Progress narration

Surface only meaningful milestones: proposal ready, confirmation recorded,
Trial or Result preparation started, Domain evidence ready, a correctable
blocker, interruption and its retry boundary, and the terminal report summary.
Name Trials, Results, and Domains using returned display information. Do not
expose opaque work tokens, cursor values, operation IDs, raw protocol
identifiers, or polling updates as narration.

On interruption, say what committed and what the next `prepare_run` or
`continue_run` response will resume. On a terminal Result, link or name the
static report and plainly state any limitations. A Harness does not modify a
completed Assessment or its reports.
