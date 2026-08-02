---
name: rob2-assess
description: Prepare an evidence-grounded RoB 2 assessment and hand it to a human reviewer.
---

# RoB 2 assessment

Use the static `rob2` tools to initialize or resume the project, request the
next engine-issued work item, inspect only bounded evidence and visual
candidates, and submit typed work with the supplied mutation context.

Treat every structured status as authoritative. On `work_required`, complete
only the returned work item. On `review_pending`, end the turn without further
inference. On `retryable_interruption`, preserve state and retry only within the
returned bounds. On `trial_problem` or `run_integrity_failure`, report the
condition without inventing recovery.

Open review when preparation reaches human handoff and consume durable review
receipts. Never perform a human review action, disposition, override, or
assessment sign-off.

All RoB 2 wording, branching, guidance, and judgments come from the pinned
packs and bounded tools. Do not reproduce or infer normative logic here.
