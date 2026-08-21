---
name: rob2-workflow
description: Run a RoB 2 batch through the typed rob2-kit MCP workflow, including researcher review and finalization.
---

# RoB 2 workflow

Use `rob2://current-batch` at entry, after a restart, and after an uncertain mutation. Its authoritative status, conditions, review requirement, and typed continuation choose the next operation. Preserve every returned reference unchanged; the generated public contract is the schema source of truth.

## Intake to approval

1. `preflight_sources` the authorized roots; use `inspect_candidate_sources` for a candidate condition or inspection. Complete when the returned preflight reference is current.
2. `save_intake_plan`, obtain the required intake acknowledgment through the CLI review path, then `capture_batch`. Complete when status offers Proposal work.
3. `list_sources`, `retrieve_evidence`, and selectively `render_page` to make deliberate scoped Evidence. Complete when each Proposal fact has its exact Evidence reference.
4. `save_proposal`, then deliberately read its returned Detail with `read_record`. The researcher reviews it only through `rob2 review`; use the returned acknowledgment and Transition with `approve_batch`. Complete when status supplies the approved Batch/work continuation or terminal preparation.

`needs_input` and `failed` terminals are researcher decisions: prepare them with `prepare_trial_finish`, acknowledge through `rob2 review`, and complete with `finish_trial`. They may preserve partial Domain checkpoints. CLI review and CLI discard are the only human-review/destructive boundaries; MCP has no discard operation.

## Assessment, recovery, and completion

For an assessment continuation, hand the exact `work_packet` reference to `rob2-signalling`. Resume here when it returns a synthesis reference or a condition. Review an assessed Trial synthesis through `rob2 review`, then call `finish_trial` with the exact Transition and acknowledgment.

On a condition or conflict, read current status and follow its continuation; do not replay a prior payload or reconstruct records. When every Trial is terminal, call `finalize_batch`. Report only the returned summary, ordered outcomes, and artifact receipt. A finalized result is complete only when the authoritative status verifies it.

The available MCP tools are exactly: `preflight_sources`, `inspect_candidate_sources`, `save_intake_plan`, `capture_batch`, `list_sources`, `retrieve_evidence`, `render_page`, `save_proposal`, `approve_batch`, `validate_domain_judgment`, `commit_domain_judgment`, `prepare_trial_finish`, `finish_trial`, `finalize_batch`, and `read_record`.
