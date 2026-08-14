---
name: rob2-signalling
description: Apply evidence discipline while answering RoB 2 signalling questions.
---

# RoB 2 signalling

Use rob2-kit's packs as the authoritative question and decision rules. Keep one
evidence matrix per Trial and ResultSpec; evidence never crosses Trial boundaries.

## 1. Guidance orientation

Read these exact resources once per live context:

- `rob2://domain-guidance/domain:randomization`
- `rob2://domain-guidance/domain:deviations`
- `rob2://domain-guidance/domain:missing`
- `rob2://domain-guidance/domain:measurement`
- `rob2://domain-guidance/domain:selection`

Read them again after restart or context loss, pack mismatch, or unresolved skill
activation. They supply the official question wording, activation logic, and
judgment mappings; use their identifiers rather than reproducing rules from
memory.

Completion: all five guidance resources and their applicable rules are in the
live working context, and their shared scientific and policy identities agree.

## 2. Proposal evidence

For each intake Trial, use `list_sources` and orient first on the designated main
article and matched registry. Read the complete designated main article for
orientation, then revisit only pages that add information; use its source
identity, hash, exact page, bounds, and quote to anchor the proposed ResultSpec.
Do not infer a Source role or unrestricted evidence claim: assign only the role
the inventory supports, and stop for researcher input when a material ambiguity
cannot be resolved from approved Sources.
Registry/protocol/SAP
and supplements supply prespecification and supporting detail, with supplements a
lower-priority path except for prespecification.

Resolve the effect, randomization, arms/comparison, outcome definition,
measurement, time point, population, analysis method/choices, effect measure,
and values/denominators. Present the complete batch proposal for researcher
confirmation before approval.

Completion: every Trial has proposal evidence sufficient for one complete,
anchored ResultSpec, and whole-batch confirmation is ready for workflow.

## 3. Evidence matrix

For the approved Trial and ResultSpec, create a provisional activation-aware
matrix covering all 22 signalling questions. Each entry records its question ID,
active/inactive state, answer when active, exact coordinates, evidence uses
(`supporting`, `contradicting`, or `contextual`), rationale, and unresolved
questions. Re-evaluate activation as upstream answers resolve. Begin Domain 5
prespecification retrieval early from registry, protocol, SAP, or supplement.

Use `search_sources`, `read_pages`, and direct calls in an information-gain loop;
there is no arbitrary query or reread cap. Search or reread only when it can add
information, including a new source, citation precision, recovered truncation, or
a contradiction/priority check. Search or read when it can test a concrete
uncertainty, contradiction, synonym, endpoint definition, population, time point,
or source role. Widen or reformulate that concrete query when the current source
cannot resolve it. Reuse live context and compact receipts.

Completion: identified material uncertainties are resolved or documented, and
evidence sufficiency, contradiction, and source-priority checks are complete.
Stop then, not only when no conceivable further query remains. Pagination and
transport bounds only shape the next request; they never establish scientific
sufficiency.

## 4. Visual evidence

Render selectively for a CONSORT flow, table or figure, spatial footnote,
extraction discrepancy, blank page, or vector-only page. Bind each visual use to
the rendered page or region, normalized region, render hash, and a transcription
visible on that captured page.

Completion: each visual claim has a reproducible rendered origin and its
transcription.

## 5. Checkpoint

Partition every Domain exactly: active questions carry answers, rationales, and
cited evidence uses; inactive questions are explicitly declared. Build the
complete draft and verify this checklist before validation:

- The active and inactive IDs are the exact Domain/question partition from guidance.
- Every rationale and limitation is specific and final.
- Each citation is attributable, supports its claim, and has no unaddressed contradiction.
- Evidence stays within the approved Trial/ResultSpec inventory; no unrestricted evidence claim is used.
- The payload is complete; inspect the tool schema rather than probing with a save.

Use pack rules to obtain the deterministic proposed judgment. A different final
judgment carries an override with concise justification, actor, and UTC time.

Inspect the tool schema. First call `save_domain_judgment` with `phase: validate`
and the complete draft. Interpret a typed problem or conflict, resolve it, and
validate again. When validation returns `next_action: review_then_commit`, review
the whole identical payload and receipt, then call with `phase: commit`, that
receipt, and the explicit scientific preflight: payload final; citations checked
against cited pages; contradictions addressed; activation and partition reviewed.
The preflight records deliberate review; it does not authenticate an assessor or
establish scientific truth. A first draft supplies `expected_previous_hash: null`;
a correction before `finish_trial` supplies the exact active checkpoint hash.
Interpret `saved` as persisted or idempotently replayed and `revised` as an
appended active revision. Use `remaining_domains` to select the next Domain.
Completion: commit returns saved or revised. An uncertain commit response may be
retried only with its exact complete commit payload and matching receipt.

The working checkpoint is replaceable only before `finish_trial`; every saved
revision is an append-only audit entry, and `finish_trial` freezes the active
revisions into the immutable assessment snapshot.
