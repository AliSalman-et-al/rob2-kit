# Post-benchmark accuracy successor design session

Session date: 2026-09-22.

This document records the owner's decisions after reviewing the 22 September
accuracy audit and the live repository at commit
`38826298e583a3d1a2a40c6482c749577f5d6f6e`. The two supplied audit documents
have identical substantive content; one additionally contains a table of
contents. They are source material, not implementation instructions.

## Agreed objective

Improve the scientific faithfulness and operational reliability of the path
from an approved Result through investigation, Domain answers, Trial review,
and benchmark scoring. The successor must target generalized failure
mechanisms rather than agreement with the provisional catalog, a particular
Trial, or one model family.

The program may report provisional-label agreement, but without independent
human adjudication it must not claim independently validated scientific
accuracy. Promotion evidence instead combines source-grounded autonomous
review against official RoB 2 guidance, paired premise-changing controls,
Trial-held-out evaluation, and runs across at least two model families or
materially different supported hosts.

## Scope decisions

- Publish one new successor specification and entirely new implementation
  tickets.
- Leave all existing GitHub issues unchanged. Cite overlapping issues only as
  related prior work; do not close, relabel, rewrite, or use them as blockers.
- Include the audit's P0, P1, and P2 work.
- Exclude P3 experiments until a controlled comparison demonstrates a residual
  need. This excludes hybrid or vector retrieval, a routine fresh-context
  critic, and speculative compound write tools.
- Preserve the model-free server, the installed host as the only model loop,
  Proposal Review as the only researcher gate, deterministic official RoB 2
  evaluation, immutable Evidence, and the current overall aggregation policy.
- Add no human scientific adjudication gate and no second-model scientific
  authority.

## Investigation and review decisions

- Reuse the existing premise record and working checkpoint. Do not create a
  second investigation ledger or scientific workflow engine.
- Expose a compact typed investigation projection through the existing status,
  Domain-context, validation, and Trial-review surfaces. It presents the active
  proposition, observed coverage, supporting and contrary Evidence, unresolved
  material information, recovery choices, and stopping rationale.
- Keep investigation state host-authored and advisory. It is not Canonical
  Evidence, server-verified entailment, a saved signaling answer, or a save
  gate.
- Separate the next permitted mutation from scientific sufficiency. Structural
  validation may permit a save while search, read, revise, and accept-limitation
  actions remain visible.
- Require no fixed query count, compulsory full-document pass, or automatic
  severity cap. The host stops after reaching a supported answer or honestly
  bounding a material unresolved premise.
- Enrich the existing mandatory Trial review in the same host. Present the
  facts-to-warrant-to-answer chain, counterevidence, scope or chronology
  conflicts, and uninvestigated routes; allow affected Domains to be revised
  before closure.

## Working-context decisions

- Keep immutable source observations reusable while the captured Source
  projections and approved Result remain unchanged.
- When a Domain checkpoint changes, mark only dependent inferences, drafts,
  and stopping decisions stale. Do not hide still-valid source observations.
- A changed Source or Result invalidates affected material and requires
  reorientation.
- Present focused context in this order: exact Result, active proposition,
  material gap or contradiction, decisive Evidence, relevant compact guidance,
  and recoverable supporting material.
- Preserve exact recovery and Canonical records. Context reduction must never
  turn a summary into Evidence authority.

## Benchmark and scoring decisions

- Extend the existing manifest, attempt, observation, comparison, and
  qualification machinery. Do not build a new orchestration service.
- Make one immutable run record bind the case, selected attempt policy, source
  and build identities, host/model/effort settings, tool contract, resumptions,
  terminal outcome, artifact identity, verification result, and scorer inputs.
- Make model and reasoning effort manifest-owned. Any command-line override is
  explicit and recorded.
- Repair session recovery for current and supported legacy event shapes and
  diagnose missing tool inventory before repeated resumptions.
- Hard-fail new benchmark cases whose verified artifact does not match the
  expected Trial, comparison, endpoint definition, population, time
  window/cutoff, estimate, and precision. Preserve historical mismatches as
  explicitly unscored artifacts.
- Retain every attempt and declare selection policy before execution. Never
  choose the best-scoring retry after observing results.

## Verification decisions

- Use the public application/MCP contract as the primary deterministic behavior
  seam.
- Use the pure evaluator for official question activation and deterministic
  Domain/overall mapping.
- Use installed-host campaigns for actual context delivery, tool visibility,
  continuation, compaction, restart, premise recovery, review behavior, and
  cross-model/host comparisons.
- Use paired fictional cases in which the decisive causal or methodological
  premise changes while surface wording remains similar.
- Report Result-scope correctness, premise support, contradiction handling,
  unsupported concern, unsupported reassurance, completion, errors, context
  bytes, calls, latency, cost, and provisional-label agreement separately.
- Treat matching labels as eligible for review; agreement is not proof of sound
  reasoning.

## Documentation decision

No glossary or ADR change is required for this planning step. The existing
terms `Scientific sufficiency`, `Premise record`, and `Scientific limitation`
already express the agreed domain model. The successor refines their projection
and lifecycle without changing the authority boundaries recorded in ADRs 0026,
0031, 0032, and 0035.

## Shared understanding

The owner accepted every recommendation in the final design tree and explicitly
confirmed this shared understanding before specification work began.
