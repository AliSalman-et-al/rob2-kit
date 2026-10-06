# Existing completion-controller integration: offline only

No paid call, resume, global Codex configuration change, assessment repair or new
supervisor. The normal Chua control remains failed/incomplete at
3b0778994f2718adc65c0412c5dbc1952846dfdb; it is not relabeled a prototype gain.

## Existing capability and why Chua bypassed it

`scripts/workflow_completion.py:drive` already owns bounded same-session turns,
reads authoritative status, retains failures and usage, respects researcher gates,
and stops for session mismatch, transport exit, shared wall, no progress or repeated
errors. EXSCEL host recovery used that capability. Commit
02a4c3a5c99eaa8328d1d1c7cc999e947c7135da added the RSI ledger's `resumable`
classification for unfinished controller outcomes; it did not create the controller.

Chua's private frozen `run_once.py` deliberately launched exactly one standalone
native invocation, with no retry/resume/continuation authorized. It monitored
accepted D2/D3/D5 checkpoints but never called `drive`. The prompt's requested work
was still incomplete at voluntary exit. The single-invocation policy was explicit
experiment design, not a failure of the existing controller. The integration gap
was that the supported controller/RSI goal was verified full-batch finalization,
whereas this diagnostic requested only three Domains, forbidding closure/finalization.
A single-turn comparator under that policy cannot establish workflow reliability.
The bespoke diagnostic manifest is not an RSI execution ledger and is not silently
converted or automatically resumed by this change.

## Actual changes

- Extend the existing controller with an optional prospectively bound
  `AssessmentScope`: Trial ID, approved Result identity and requested Domain IDs.
  Scope files reject labels, unknown keys, duplicate/invalid Domains and bad identity
  types. No new judgement rules or scientific input structure.
- Add `--completion-scope FILE` to the existing RSI runner. It reads canonical
  current Result/domain identities and existing reading status, recovers a matching
  current-revision in-scope native cursor, and calls the SAME `drive`. Bound Result
  changes or new/changed out-of-scope canonical checkpoints stop the workflow.
  Canonical history is observed, never rewritten. Existing `budget_limited` reading
  policy remains valid; no new mandatory exhaustive-reading/scientific gate.
- Scoped generic continuations contain only scope IDs and authoritative action
  metadata. They supply no source prose, labels, preferred answers or question
  coaching. They do not request review/closure/finalization. The existing same-session
  handoff, approval, no-progress/repeated-error and shared-wall safeguards remain.
- Resumes stay **off by default**. An explicit scope with zero resumes performs one
  turn and classifies unfinished work accurately; positive resumes require explicit
  configuration and a shared wall budget. No unrelated work acquires paid resumes.
- Legacy single-turn RSI execution now explicitly remains `resumable` when canonical
  host work is actionable, even if an artifact hint exists. Model final prose is
  irrelevant. A scoped goal can be technically complete while the full-batch RSI
  ledger remains resumable, preventing partial diagnostics being scored as finalized
  benchmark runs.
- RSI metadata declares controller/goal/scope hash, actual host invocations and
  same-session resumes, completed-turn receipt count, usage availability and basis.
  Missing usage is unknown, not free. Dollar cost remains unavailable; durable
  provider records are still needed for interrupted-turn billing, as in the existing
  diagnostic telemetry. No new billing subsystem.
- Add a receipt-based reading report written by RSI for every phase, including
  single-turn mode. It uses successful native rob2 required-window and numbered-text
  receipts, never narrative claims. Uncertified partial-line fragments and truncated
  requirement envelopes cannot silently certify completeness. Delivery remains
  distinct from comprehension; unlisted sources are not certified.

Existing RSI isolation/runtime bindings and handoff checks were not bypassed. A
pre-existing type-narrowing omission in the registered MCP args check was clarified
while checking this touched runner; its accepted args remain mcp/mcp-codex.

## Offline evidence

58 controller/RSI/auth checks passed. They cover premature final with unread pages,
unsubmitted Domains, scoped-complete stop without finalization, genuine blocker,
researcher gate, changed Result, failed/mismatched handoff, no-progress/identical
errors, current-versus-stale cursor, out-of-scope history, budget-limited reading,
missing usage and narrative/fragment-independent receipt verification. Full
source/test/release plus touched-script type checks, scoped lint and whitespace
checks passed. No claim of live behavioral reliability follows from offline checks.

Copied-workspace replay of frozen native receipts classifies the normal control
**unfinished**, with pages 11–12 undelivered and the original actionable D2 cursor.
It classifies the prototype's requested scope complete without finalizing its batch.
The first control's “all main read” claim is contradicted by successful delivery
receipts and required ranges. Existing canonical reading enforcement would already
prevent submission with this reading gap; no new scientific gate was necessary.
Prototype CLI turn usage is absent because its monitor stopped immediately at the
third accepted checkpoint; its preserved durable provider records report usage.
The replay marks that distinction rather than substituting zero cost.

All replays used copied workspaces. Original completed prototype, first blocked
prototype and normal control terminal files remain immutable. Replay outputs and
checks are separate artifacts, not revised assessments or new model outputs.

## One minimal follow-through option, not launched

After separate authorization, permit **one bounded same-session host-assisted turn
for the existing normal control**, preserving frozen f46 scientific runtime, input
and guidance. First verify/import the existing hash-bound handoff through the
supported ownership checks and a compatible native invoke adapter; its bespoke
manifest is not presently an RSI phase directory. If that handoff fails, do not
spend or create a replacement session. Use only the generic scoped continuation.
Retain the original failure, new host-assisted outcome, every invocation/turn and
combined durable cost separately. A further premature stop consumes that allowance;
no automatic additional turn follows.

This could close practical control work, but would remain sequential host-assisted
recovery, not a prospectively matched causal A/B comparison. Any later scientific
comparison must give both routes the SAME predeclared completion policy, including
resume/no-progress/wall/review boundaries. Keep the prototype experimental; no
accuracy, default-adoption or completion-gain claim from this development case.
