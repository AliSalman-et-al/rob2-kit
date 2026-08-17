---
name: rob2-workflow
description: Manage a v2 RoB 2 batch through the rob2-kit MCP server.
---

# rob2-kit workflow

Keep scientific reasoning in the host model loop. The server is the durable,
fail-closed boundary for captured Sources, verified projections, packets,
checkpoints, terminals, and artifacts.

## Orientation and intake

Read `rob2://current-batch` once at context entry and again after restart,
context loss, or an uncertain mutation. It is a compact projection, not a
canonical record. Follow its exact packet and Detail references.

For an empty or intake state, identify each Trial's main article and related
protocol, SAP, supplement, and report. Call `ingest_batch` with workspace-
relative paths and explicit Source roles. Preserve its compact conditions and
captured identities. Use `list_sources` for the authoritative inventory, then
use `retrieve_evidence` to deliberately select one captured-scope text anchor
handle for each Trial before constructing the Proposal.

Save a minimal `Proposal` draft with `save_proposal`; it contains one complete
Result draft per captured Trial and one text Evidence handle anchor. Repair all
returned RFC 6901 defects. Call `read_record` on the returned Proposal Detail
and deliberately review its exact hash with the researcher, then call
`approve_batch` with that reviewed hash. Do not substitute current state for a
stale identity.

After approval, the approved work packet is the sole post-approval context
boundary. A host may discard preapproval conversation and resume from its
packet, but it must not recreate Source text, hashes, coordinates, or workflow
identity from memory.

## Domain and Trial progression

Use the recommended packet. Retrieve Evidence in adaptive batches with
`retrieve_evidence`; only deliberate text or visual selection mints a
scope-bound immutable handle. Render selectively with `render_page`.

For each Domain, call `validate_domain_judgment` with the strict draft. Review
all independent repairs, then review the returned candidate Detail and exact
receipt. Call `commit_domain_judgment` only with the unchanged draft,
receipt-bound candidate hash, expected predecessor, and review acknowledgment.
Corrections repeat validation against the displayed active hash; they never
rewrite a prior revision.

After five active Domain checkpoints, review the exact synthesis packet. Call
`finish_trial` with the synthesis hash acknowledgment for an assessed Trial, or
with a compact typed problem draft for `needs_input` or `failed`. The server
derives final judgments, packs, timestamps, and terminal records. Responses are
compact references only.

When every Trial is terminal, call `finalize_batch` with the actor. Verify and
report only its Summary reference, ordered compact outcomes, and artifact
receipt. Never invent an artifact or present a full terminal in a mutation
response. Use `read_record` for deliberate whole-record review.

Retry only an operation with its exact original payload. Reconcile conflicts
from the current projection and verified references; never broaden or replay a
stale operation.

## Destructive boundary

`discard_active_batch` is researcher-only. Require a fresh explicit instruction,
the displayed frozen identity, exact confirmation literal, actor, UTC time, and
reason. It preserves exported bundles and recoverable residues. Never invoke it
to recover from an uncertain ordinary mutation.
