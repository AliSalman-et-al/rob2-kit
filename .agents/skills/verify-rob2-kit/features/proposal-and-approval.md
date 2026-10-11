# Proposal and researcher approval

The host proposes one result per trial for the requested outcome, or declares
that none is available. The researcher approves the exact proposal before any
domain work. This is the workflow's only human gate.

## Sub-features

- `validate` checks a selection with `validate_proposal`. It returns `repair` with typed codes, or the exact `save_proposal` arguments.
- `save` stores the validated draft with `save_proposal`, whose outcome is `review_required`.
- `reading-gate` blocks validation with `main_report_reading_required` until the required windows have been read. That repair arrives together with the other repairs.
- `unavailable` handles a selection with `relation: "unavailable"`, `candidate: None` and `missing_facts` citing the absence. The trial later ends as `needs_input`.
- `approve-elicit` is `request_proposal_approval` on a host that supports elicitation.
- `approve-cli` is `rob2 review` (or `rob2 review --review-reference <ref>`) with `yes` on stdin.

## How to get to it (user POV)

- The host calls `validate_proposal` and then `save_proposal` after reading.
- The researcher accepts the host's approval prompt, or runs `rob2 review` in the assessment folder.

## Driving it with the e2e Agent

Preconditions: the batch is prepared and the required reading is done (see intake).

- **Repair first.** Validate before `read_required()`, or with an estimate absent from the cited passage. `agent.call("validate_proposal", ...)` returns `outcome == "repair"`, and its `repairs[*].code` includes `main_report_reading_required` or `result_value_not_supported`.
- **Valid proposal.** Run `agent.propose(selection(agent))`. The outcome is `review_required`, and `get_status` shows a pending review reference.
- **Approve through the CLI.** Run `agent.approve()`. Its subprocess output is `rob2 review ... yes`. Afterwards `get_status` shows a `read_pages` or domain next action.
- **Decline.** `rob2(ws, "review", input="no\n")` exits non-zero, and the review stays pending.

## Gotchas

- In `tests/e2e/test_assessment.py`, the `selection()` table citation must span both `Table 2. Primary outcome` and `Hazard ratio 0.59`. A label without its estimate is rejected.
- An `exact` relation needs all eight clarity facets. `group_values: null` is treated as empty.
- In-process stdio clients have no elicitation, so `request_proposal_approval` returns a condition. That is expected. Use the CLI route.
