# Preserve proposed and reasoned adopted Domain judgments

Status: accepted for explicit opt-in host adjudication

Cochrane RoB 2, 22 August 2019, p.4 sections 1.2.1 and 1.2.4 and the
Domain decision tables describe algorithmic labels as proposals and permit
reasoned assessor departures. Material bias remains the construct. Source PDF
SHA-256: `a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670`.
The omission of this representation from the atomic-save contract in ADR 0036
is corrected here; this does not change any signaling answer or decision table.

The existing `save_domain_judgment` accepts optional typed `adjudication` only
for an unchanged, already saved Domain assessment. It names the exact Result,
Domain, checkpoint and current scientific pack identity. The checkpoint must be
the direct superseded record and its complete canonical answers, source-bound
Evidence, reasoning and unknowns must match. Supporting and countervailing
Evidence must already be bound by that checkpoint's answers. Add newly relevant
answer Evidence to a deterministic checkpoint before adjudicating it.

The host records a distinct adopted judgment, an attributable assessor, a
source-linked rationale explaining why the default misrepresents material bias,
and an explicit counterevidence array (empty when none is identified). Host
attribution is an assertion, not researcher approval or authenticated identity.
Structural checks cannot certify the scientific inference or the adequacy of the
rationale. Desired agreement and gold labels are never evidence.

New checkpoints record `decision` under
`rob2-kit.domain.reasoned-adjudication.v1`: proposed/adopted labels, algorithm
or host authority, adjudication and `trace_authority: proposed_algorithm`.
The original evaluator trace and driver questions remain proposed-only.
`judgment` holds the adopted label, so existing review and overall aggregation
use it. Context, save receipts, bounded review summaries, overall driver receipts,
canonical export and final assessment summaries expose the distinction.

No prose implies adoption. Omission always saves the deterministic proposal.
Revision lineage and concurrency continue to apply; an identical retry remains
idempotent. A changed answer/evidence snapshot needs a new checkpoint and cannot
inherit the old adjudication. Any Domain save invalidates the exact Trial review.
Counterfactual answers recompute deterministic proposals and do not carry forward
an adjudication attached to another snapshot.

Both verifiers independently replay defaults, compare proposed traces/drivers,
check adopted labels and validate exact ancestor/Result/Domain/rule/Evidence
bindings. A new scientific descriptor names this contract and enumerates
unmarked historical checkpoint identities under
`rob2-kit.domain.algorithm-only.v1`. Existing records and bundles remain
immutable; historical descriptors and deterministic semantics remain recognized.
A stripped marker without matching historical provenance fails. Content hashes
are integrity bindings, not external signatures authenticating an assessor.

This is representational fidelity. There is no default model exhortation to
adjudicate, researcher gate, new assessment engine, trial-specific rule, or
accuracy claim. Paid evaluation and automatic adoption are outside this change.

## Pack changes and recovery

Domain context includes the exact active decision, including proposed/adopted
labels and the source-bound rationale. Its existing bounded header delivery may
require the advertised larger response budget for a long rationale; it does not
silently discard that decision.

Continuing an adjudicated workspace across a different pack hash is unsupported.
Domain context/save and new finalization explicitly reject mixed-pack adjudication
history without modifying it. Preserve and continue that workspace with its pinned
prior code/pack, or start a fresh assessment workspace. This is a format boundary,
not an assertion that guidance changes invalidate the science of the old judgment.
Untouched finalized bundles remain verifiable against their exact historical
pack descriptor. No migration or historical rewrite is performed.

## Structural recovery payload bound

Before writing an adoption, serialize the complete stable Domain context header
with its candidate canonical decision and checkpoint identity as UTF-8 JSON.
This includes rationale, assessor, every counterevidence implication and canonical
Evidence identifier, plus all other unpaged context fields. The existing paged
source/question/Evidence/comparison sections are excluded. Reserve 16 KiB for
native typed envelope, cursor/page metadata and transport headroom. Reject when
the total exceeds the existing 131072-byte maximum; return an explicit repair
before canonical mutation. This is a conservative storage/recovery bound, not a
scientific rationale-length rule. No text is truncated. Near-boundary multi-byte
text is tested through actual native recovery, alongside oversized counterevidence
rejection and unchanged canonical state. The ordinary long-rationale test remains.
