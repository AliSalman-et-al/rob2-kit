---
name: rob2-workflow
description: Manage an RoB 2 batch through the rob2-kit MCP server.
---

# RoB 2 workflow

rob2-kit is the durable, fail-closed assessment boundary. Keep scientific
reasoning in the model loop and persist only structured, attributable records.
Use `rob2-signalling` for proposal evidence and each Domain checkpoint.

## 1. Orientation and recovery

Read `rob2://current-batch` once when entering a live context, then again only
after restart or context loss, an uncertain mutation response, or a returned
state conflict. Use its frozen batch, saved checkpoints, and terminal markers as
the current truth; continue at the first durable boundary. Do not orient again
before every ordinary mutation.

Completion: the batch is identified as absent, proposal, approved, or stale and
the next unsaved action is known.

- **Absent.** Gather the intake below, then ingest.
- **Proposal.** Inspect its sources and ResultSpecs; repair the complete proposal
  through `save_proposal`, then obtain researcher approval before `approve_batch`.
- **Approved.** Resume each Trial from its saved checkpoints or terminal marker.
- **Stale or a returned condition.** Resume mechanically actionable incomplete
  or saved-bound work autonomously. Route preapproval input blockers to the
  researcher. A stale frozen batch never supplies a new basis for assessment.

For an uncertain response, retry only a supported content-idempotent mutation
with its exact original payload, including its UTC timestamp. A semantic action
has one terminal outcome, but its exact `finish_trial` or `finalize_batch` call
may be retried; a reconstructed timestamp can create a conflict. Do not auto-retry
`discard_active_batch`: reconcile current state and require renewed explicit
researcher direction whenever its effect is uncertain. Keep compact receipts
(request payload, returned state/hash, and next boundary), rather than
re-narrating evidence or deliberation.

## 2. Intake and proposal

Record the requested outcome target, each Trial identity, and every explicit
source path with its intended role. Call `ingest_batch`; retain its ingestion and
registry conditions, captured source identities, hashes, and any local condition.
Use `list_sources` to inspect the accepted immutable inventory by Trial.

With signalling evidence, form one complete proposal: exactly one Trial and one
fully specified `ResultSpec` per intake Trial, approved sources, and an anchor
whose source, hash, page, bounds, and quote bind the selected result. The
ResultSpec makes the effect, arms/comparison, outcome definition, measurement,
time point, population, analysis method/choices, effect measure, and applicable
values/denominators explicit.

Completion: `save_proposal` returns a complete proposal with every issue resolved,
and the researcher has seen the whole batch proposal and explicitly approved it.
Only then call `approve_batch`; retain its frozen hash and pack identities.

## 3. Trial sequence

For each nonterminal Trial, invoke signalling with the approved Trial, ResultSpec,
and only that Trial's approved Sources. Work Domains in order. A Domain advances
only after `save_domain_judgment` confirms its saved checkpoint; recover a
condition from current-batch and resume at the saved boundary.

Completion: the Trial has five confirmed saved Domain checkpoints, or a typed
terminal problem makes further assessment impossible.

After five checkpoints, call `finish_trial` once with its `assessment` envelope.
For a postapproval unrecoverable scientific problem, call `finish_trial` once
with the matching typed `needs_input` or `failed` problem envelope for that Trial.
This isolates the affected Trial: continue the remaining nonterminal Trials. A
preapproval input blocker returns to the researcher instead of producing a
terminal outcome.

## 4. Batch handoff

When every Trial has exactly one terminal outcome, call `finalize_batch` with the
actor and UTC observation time. On an uncertain result, retry the exact payload;
the tool rematerializes a committed identical summary if a prior export failed.
Hand off its typed receipt: workspace-relative bundle path, deterministic bundle
hash, file count, summary hash, and index hash, plus compact Trial
terminal statuses. Never claim an artifact for a conflicting summary.

Completion: the finalized artifact/hash is verified and reported once.

## 5. Destructive boundary

`discard_active_batch` is available only for an explicit researcher instruction
in the current conversation. Bind that instruction to the displayed current frozen
batch hash, exact confirmation literal, attributable actor, UTC observation time,
and nonempty reason. Recovery uses orientation, exact retry, and typed conditions;
it never uses discard.
