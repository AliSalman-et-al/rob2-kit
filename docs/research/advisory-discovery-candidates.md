# Implementing advisory discovery candidates (issue #119)

> Historical note: Evidence-navigation v2 inspection now requires pinned
> historical code at `6f279e1b8d2de1a76ea5061060a5036c2153c675`; current HEAD
> intentionally no longer carries a v2 decoder.

## Scope and method

Issue #119 was already settled through a structured design-interview session.
The settled design lives in three committed ADRs
(`docs/adr/0003-discovery-candidates-are-advisory-never-binding.md`,
`docs/adr/0004-source-role-resolution-precedes-proposal.md`,
`docs/adr/0005-synchronous-evidence-index-rebind-on-result-resolution.md`) and
a full implementation-ready spec posted as the latest comment on issue #119
(titled "Grilled resolution"). Two smaller pieces of that spec are already
implemented and committed in `8d5ffd8` ("Rebind evidence index after Result
resolution; remove sole-candidate auto-bind"): the sole-Result-cardinality
auto-bind removal in `src/rob2_kit/application/proposals.py`, and the
evidence-index rebind in `submit_result_resolution`
(`src/rob2_kit/application/run_engine.py`, closing #113).

This note validates the remaining, unimplemented pieces against the current
code: (1) the `Discovery candidate` base shape and 4-state disposition, (2)
moving source-role resolution before proposal generation, and (3) the `Trial
discovery record`. It also investigates the ledger/`RunOperation` state
machine, the two closest existing precedents for a "candidate + disposition"
type and a "revision-tracked record" type, the exact write-back defect
motivating the reordering, and a size/risk estimate grounded in the actual
diff of the closest comparable prior change.

The report distinguishes three kinds of statement:

- **Repository observation**: directly supported by the cited file and line
  range, verified by reading the file in this session (not merely repeated
  from the ADRs or the issue comment).
- **External evidence**: none is used in this note; the question is entirely
  about this codebase's own existing mechanisms.
- **Inference/recommendation**: a design or sequencing conclusion, not a
  fact established by the code as it stands today.

No implementation or test change is made in this note.

## Executive conclusion

Both bugs the ADRs cite are real and confirmed by direct inspection, not just
by the issue comment's claims:

1. `submit_source_classification` (`run_engine.py:2672-2777`) commits the raw
   request to the ledger but never writes `SourceClassificationInput.roles`
   back into any `SourceDescriptor`. The only role value that has ever existed
   for a run's lifetime is `_classify`'s pre-review, ingestion-time cue
   (`ingestion/project.py:1053-1054`, `2037-2074`).
2. That unreviewed cue is already read authoritatively pre-confirmation by
   `validate_result_sources` (`proposals.py:713-721`, called from
   `submit_run_proposal`) and `_preferred_candidate`
   (`proposals.py:44-96`, reading `source.roles` at line 74).

The codebase already contains two usable precedents at different weights, and
they point in different directions:

- A **heavy, fully general precedent** for "candidate + disposition +
  revision" already exists: `EvidenceReviewRevision` in
  `src/rob2_kit/domain/evidence.py:119-161` is a standalone, independently
  submitted, independently superseded `Revision` record, built on the
  generic `Revision.supersedes: Supersession | None` primitive
  (`domain/revisions.py:45-60`) that the whole codebase already uses for
  revision-tracked history — this is not bespoke to Evidence.
- A **light, already-used precedent** for exactly the two candidate types the
  spec says do *not* need to move (`ResultCandidate`,
  `RegistryCandidate`) also already exists: they are plain `FrozenModel`
  structs embedded in the single `RunProposal` snapshot
  (`contracts.py:506-521`), and their disposition is expressed today through
  `RunProposalSelection.accepted` / `.removed` / `.exclusion_reason`
  (`contracts.py:442-457`) recorded at `confirm_run_definition` time — no
  separate candidate-level revision type, no separate submission call.

The `Trial discovery record`, as specified, wants the heavy pattern (a
standalone record that gains a new revision on every disposition change).
The two candidate types it wraps already work fine under the light pattern.
This is a real design tension the ADRs do not resolve, not a inconsistency
in the ADRs' reasoning — see "Detailed findings" section B/C below.

On the `RunOperation` mechanics (section A below): a new operation is not a
one-line addition. Grep-confirmed touch points span the enum, the work-item
derivation state machine, the MCP tool registration, a release-gating
canonical tool-name manifest, two adapter manifests, two forward-fixtures
files, and at least seven test files. This is a real, measurable cost, but it
is the same cost the codebase has already paid at least once before — an
`_OBSOLETE_DOCUMENTATION_TERMS` entry for `"classify_sources"` in
`release.py:30` is a fossil of an earlier rename to the current
`submit_source_classification`. ADR-0004's stated reasoning ("the contract
changed meaning: from 'declare final roles' to 'accept/reject/leave-unresolved
a Discovery candidate'") is a real, principled distinction, not a
post-hoc justification — reusing the same operation name for a materially
different write contract is exactly the kind of silent meaning-drift the
ledger's append-only, typed-operation design exists to prevent. A cheaper
compliant alternative (reuse `submit_source_classification`, just resequence
it and fix the write-back) is possible but only by weakening the operation's
contract meaning, which is what ADR-0004 explicitly rejected.

**Recommendation (inference, expanded in section E):** the write-back bug is
independently fixable, small, and high value on its own, without waiting for
the full `Discovery candidate` type system. It is worth landing first as an
isolated slice. The full `Discovery candidate`/`Trial discovery record` type
system is comparable in size to the largest recent schema-shaped change in
this repository (`8668a5d`, 16 files, ~1540/~325 lines) and should be scoped
and sequenced separately, after the write-back fix is in and the light-vs-heavy
tension above is resolved for `Trial discovery record` specifically.

## Detailed findings

### A. Ledger / WorkToken mechanics and the cost of a new `RunOperation`

**Repository observation — the state machine.** `WorkflowLedger` is an
append-only SQLite command/query boundary (`src/rob2_kit/storage/ledger.py`,
`WorkflowLedger` class starting at line 217). Every commit is a `Transition`
(`ledger.py:104-124`) carrying `dependencies: tuple[DependencyInput, ...]` and
an `expected_dependency_fingerprint` (`ledger.py:116`), checked against a live
fingerprint at commit time (`ledger.py:336`). `dependency_fingerprint()`
(`ledger.py:198-212`) is a pure function: it canonically sorts
`DependencyInput` entries by `(entity_id, revision_id, role, content_hash)`,
JSON-serializes them, and SHA-256s the result — a generic staleness primitive,
not something specific to evidence or Results. `WorkToken`
(`contracts.py:192-203`) binds one `RunOperation`, a `dependency_fingerprint`,
and optional `trial_id`/`result_id`/`domain_id` scope; it authorizes exactly
one typed submission kind.

`RunOperation` is a flat `StrEnum` of 17 members
(`contracts.py:61-79`), and `RUN_OPERATION_NAMES` (`contracts.py:81`) is
derived from it mechanically. Work items are derived deterministically by
`RunEngine._next_work_item` (`run_engine.py:8705-8812`), which walks
committed checkpoints in a fixed sequence — inventory-ready sources incomplete
→ unresolved Trial → unresolved Result → per-Domain evidence → per-Domain
answers — and returns at most one `WorkItem` via the shared `_work_item`
helper (`run_engine.py:8814-8847`), which digests `run_id|key|operation.value`
into both the `work_item_id` and the `WorkToken.token`/`dependency_fingerprint`.

**Repository observation — what actually needs to change for a new
`RunOperation` value.** Confirmed by direct grep, not just the issue
comment's claim:

1. The enum itself: `RunOperation` in `contracts.py:61-79`.
2. A new request/response contract pair in `contracts.py` (pattern:
   `SubmitSourceClassificationRequest`/`SourceClassificationInput` at
   `contracts.py:765-777`, `SubmitSourceClassificationResponse` at
   `contracts.py:1162-1163`).
3. `_next_work_item`'s sequencing logic in `run_engine.py:8705-8812` (branch
   selection) and a new `submit_*` handler method in `run_engine.py`, styled
   like `submit_source_classification` (`run_engine.py:2672-2777`) — idempotency
   retry check, `_submission_ledger` token validation, business-rule
   validation, `_commit_submission`, response construction.
4. `_source_classification_complete`-style completion predicate
   (`run_engine.py:9461-9491`) if the new operation gates work-item derivation
   the same way.
5. MCP tool registration: `src/rob2_kit/interfaces/mcp/server.py:671-687+` for
   the `submit_source_classification` case, using the `@server.tool(name=...)`
   pattern.
6. The release-gating canonical tool manifest: `SKILL_ALLOWED_TOOL_NAMES` in
   `src/rob2_kit/release.py:37-50`, which `server.py:76-81` imports directly as
   `CANONICAL_TOOL_NAMES` — this is the actual skill permission boundary, not
   just documentation.
7. `scripts/release_qualification.py` references `submit_source_classification`
   at lines 37, 1260, 1277, 1287, 1302, 1312 — a qualification/replay script
   that exercises named operations explicitly.
8. Both host adapter manifests, `adapters/claude/adapter.json:16` and
   `adapters/codex/adapter.json:16`.
9. Forward-fixtures manifests: `skills/rob2-init/forward-fixtures.json` and
   its adapter copies `adapters/claude/skills/rob2-init/forward-fixtures.json`,
   `adapters/codex/skills/rob2-init/forward-fixtures.json`.
10. `docs/HARNESS-WORKFLOW.md:17-22` documents the harness-facing procedure
    for "source classification" and "Result resolution" by name (not by
    operation enum value, but by workflow step) and would need updating for a
    reordered/renamed step.
11. At least seven test files reference `submit_source_classification` or
    `SUBMIT_SOURCE_CLASSIFICATION` by name: `tests/test_run_work_order.py` (2
    hits), `tests/test_issue101.py` (1), `tests/test_mcp_tracer.py` (3),
    `tests/test_input_reconciliation.py` (2), `tests/test_host_interfaces.py`
    (3), `tests/test_run_engine_contracts.py` (1), `tests/test_issue100.py` (1),
    plus the golden trace `tests/public_fixtures/traces/installed-replay.golden.json`.

Note `docs/RUN-DEFINITION.md` and `docs/EVIDENCE-SEARCH.md` were checked and do
**not** reference source classification by name — only `HARNESS-WORKFLOW.md`
does (`docs/HARNESS-WORKFLOW.md:17`).

**Repository observation — this is not the first time.**
`_OBSOLETE_DOCUMENTATION_TERMS` in `release.py:28-34` includes the literal
string `"classify_sources"`, checked against skill/documentation content at
`release.py:533`. `submit_source_classification` is therefore itself a renamed
operation from an earlier `classify_sources` — direct historical precedent
that this codebase has paid the "rename a `RunOperation`" cost before and has
a standing mechanism (the obsolete-terms check) specifically to prevent the
old name from silently surviving in docs after a rename.

**Inference — is a new operation name justified, or is there a cheaper
compliant alternative?** A cheaper mechanical alternative clearly exists:
keep `submit_source_classification`'s name, just (a) move its work-item
eligibility earlier — ahead of `confirm_run_definition` rather than gated
behind `_confirmed_definition(...)  is not None` at
`run_engine.py:8713-8714` — and (b) fix the write-back so
`_commit_submission`'s payload actually updates `SourceDescriptor.roles`
somewhere reconstructible by `validate_result_sources`/`_preferred_candidate`.
That would touch far fewer files: no enum/manifest/adapter changes, only
`run_engine.py`'s sequencing and write-back logic and the docs describing the
step's position.

ADR-0004's stated reason for rejecting this and minting a new operation name is
that the contract's *meaning* changes — "declare final roles" (today's
implicit semantics: the request payload is treated as the finished
classification) versus "accept/reject/leave-unresolved a Discovery candidate"
(explicit review of an engine-proposed candidate, with a real reject/unresolved
path). That distinction is real: `SubmitSourceClassificationRequest.classifications`
today (`contracts.py:772-777`) is a flat `tuple[SourceClassificationInput, ...]`
with no disposition field and no way to say "leave unresolved" — it's
structurally a declaration, not a review action. Reusing the name while
changing what a caller is permitted to submit would mean two different
historical meanings share one `RunOperation` value in the ledger's permanent,
append-only history, which is exactly the ambiguity the ledger's typed,
append-only operation design is built to prevent (each `Transition.operation`
is meant to have one stable meaning for its entity's whole history). Given the
codebase already has a working, low-drama precedent for doing exactly this
rename (`classify_sources` → `submit_source_classification`, with a durable
obsolete-term guard against relapse), the mechanical cost enumerated above,
while real (roughly a dozen touch points), is a cost this project has already
paid once and has tooling to do safely again. The ADR's reasoning holds up
under scrutiny; it is not overstated relative to the actual cost.

### B. Existing precedent for "candidate + disposition": `EvidenceCandidate` / `EvidenceReviewRevision`

**Repository observation.** `src/rob2_kit/domain/evidence.py` does not define
a class literally named `EvidenceCandidateDisposition`; the closest fully
worked example of "candidate visibility distinct from accepted disposition"
is:

- `EvidenceCandidate` (`evidence.py:208-215`): a `Revision` subtype (own
  `entity_id`/`revision_id`/`dependencies`/`supersedes`) wrapping a
  `canonical_unit` and `source` `RecordReference` plus a `relevance_reason`
  string — this is the "visible, not-yet-accepted" candidate shape.
- `EvidenceReviewRevision` (`evidence.py:119-161`): a separate `Revision`
  subtype keyed by `candidate_id`, carrying `trial_attribution`
  (`TrialAttribution` enum: `ACTIVE`/`OTHER`/`MIXED`/`NOT_EXPLICIT`/`UNRESOLVED`,
  `evidence.py:59-66`) and one or more `EvidenceReviewSpan` entries, each with
  its own `EvidenceReviewDisposition` (8-state:
  `SUPPORTING`/`CONTRADICTING`/`CONTEXTUAL`/`OUT_OF_SCOPE`/`IMMATERIAL`/
  `SUPERSEDED`/`DUPLICATE`/`NEEDS_VISUAL_REVIEW`/`UNRESOLVED`,
  `evidence.py:69-85`). Validators enforce shape (span extent, disposition/
  visual-review-condition pairing, disposition/duplicate-target pairing,
  `is_complete` excludes `NEEDS_VISUAL_REVIEW`/`UNRESOLVED`, `evidence.py:100-161`).
- `EvidenceConsiderationManifest` (`evidence.py:307-334`) aggregates
  per-item `ConsiderationDisposition` entries and is itself a `Revision`
  that can pre-exist its bundle (`bundle: RecordReference | None`) and later
  get superseded by the final manifest.

`EvidenceCandidate`/`EvidenceReviewRevision`/`EvidenceConsiderationManifest`
are each independently committed `Revision` records — they participate in the
ledger's generic `Transition`/`dependency_fingerprint` machinery like any
other durable record, and each is exposed over MCP through
`submit_domain_evidence` (`run_engine.py:2779-3109`ff handles the general
domain-evidence submission path; the review/disposition payload flows through
that same submission, not a separate tool).

**Inference — does this suggest lighter or heavier than the ADRs assume?**
Heavier, for the parts of `Discovery candidate` that need real revision
history (per ADR-0003, `Trial discovery record` gains a new revision per
disposition change). `EvidenceReviewRevision`'s pattern — a small, focused
`Revision` subtype per reviewed item, superseded independently via the
generic `Revision.supersedes` field — is the correct template, not something
lighter. But note precedent B is scoped to *evidence* review (post-Result,
per-question); it is not itself a template for identity resolution
(*which* Trial/Result/registry record something is), which is what
`Discovery candidate` is actually for. The naming overlap between "Evidence
candidate disposition" and "Discovery candidate disposition" that
`CONTEXT.md:132` explicitly calls out as distinct is real and already a
source of potential confusion worth flagging in any implementation PR
description.

### C. Existing precedent for "revision-tracked record, no closed state"

**Repository observation.** Two mechanisms exist and are meaningfully
different in weight:

1. **Generic primitive**: `Revision.supersedes: Supersession | None`
   (`domain/revisions.py:52-60`, `Supersession` at `domain/revisions.py:45-49`).
   Any `Revision` subtype gets independent, per-entity supersession for free;
   validators reject self-supersession and cross-entity supersession
   (`domain/revisions.py:73-77`). This is what `EvidenceReviewRevision` (see
   B) already rides on with no bespoke machinery.
2. **`RunProposal`'s whole-snapshot supersession**:
   `RunProposal` (`contracts.py:506-521`) is a plain `FrozenModel`, not a
   `Revision`. It carries its own hand-rolled `proposal_token` and
   `supersedes_proposal_id: Identifier | None` (`contracts.py:519`) —
   parallel machinery to `Revision.supersedes`, not reuse of it. Critically,
   `RunProposal` embeds `registry_candidates: tuple[RegistryCandidate, ...]`
   and `result_candidates: tuple[ResultCandidate, ...]` directly
   (`contracts.py:517-518`) as plain `FrozenModel` structs
   (`ResultCandidate` at `ingestion/project.py:540-549`, `RegistryCandidate`
   at `registry/clinicaltrials.py:59-79`) — when the whole proposal is
   superseded, every embedded candidate is implicitly superseded too, as a
   unit. There is no independent, per-candidate revision history for these
   two types today; supersession happens at the whole-proposal granularity.
   Their disposition today is carried not on the candidate itself but on a
   sibling structure recorded at confirmation time:
   `RunProposalSelection.accepted`/`.removed`/`.exclusion_reason`
   (`contracts.py:442-457`), matched to a candidate via
   `result_candidate_id`/`registry_candidate_id` (`contracts.py:445-446`).
   `docs/HARNESS-WORKFLOW.md:17-18` documents this as the harness's actual
   procedure today: "proposal registry candidates are orientation data unless
   that work context also issues them."

**Inference — is `RunProposal` the right template for `Trial discovery
record`, or does the code reveal something cheaper already used for a
similarly-shaped problem?** The code reveals *both* patterns already in
active use for two different granularities of the same general problem
("track a candidate's disposition over time, without a closed state"), and
they are not interchangeable:

- If `Trial discovery record` disposition changes are expected to happen
  together, in batches, driven by re-running discovery (matching how
  `RunProposal` gets superseded wholesale when a new snapshot is generated),
  the light `RunProposal`/`RunProposalSelection` pattern is cheaper and is
  exactly what `ResultCandidate`/`RegistryCandidate` already use successfully
  — no new type is needed for those two, matching ADR-0003's/ADR-0004's own
  conclusion that Result-candidate and Registry-candidate resolution should
  **not** move.
- If `Trial discovery record` disposition changes are expected to happen
  one candidate at a time, independently, and need their own audit trail
  distinct from the whole Trial's discovery snapshot (which is what "gains a
  new revision whenever *a contained candidate's* disposition changes" in
  `CONTEXT.md:148` literally describes), the heavier `Revision`/`Supersession`
  pattern that `EvidenceReviewRevision` already uses is the correct template,
  not `RunProposal`.

The ADRs read as intending the heavier, per-candidate-revision pattern (their
prose explicitly separates "a contained candidate's disposition changes" from
the record as a whole), but the two candidate types the same ADR says are
already fine (`ResultCandidate`, `RegistryCandidate`) are living examples of
the lighter, whole-snapshot pattern working adequately in production. This is
a genuine open design question for the follow-up implementation, not
something this note resolves — see section E.

### D. The write-back fix: minimal correct interception point

**Repository observation — the flow from `_classify` to the two readers.**

1. `_classify` (`ingestion/project.py:2037-2074`) computes `roles` from
   explicit trial metadata, folder position, or filename regex, with no
   candidate wrapper.
2. It is called exactly once, at ingestion, in the per-source loop:
   `roles, classification = _classify(...)` at `ingestion/project.py:1053`,
   immediately followed by `criticality = _criticality(roles, path == primary)`
   at line 1054.
3. Both values are baked directly into the constructed `SourceDescriptor` at
   `ingestion/project.py:1076-1078` (and again at `1154-1156` for a second
   construction branch) — `SourceDescriptor` is a `FrozenModel`
   (`domain/sources.py:194-210`), so `roles`/`criticality` are immutable once
   built and become part of the immutable `TrialSourceInventory` /
   `ProjectInitialization` snapshot embedded in the `RunProposal`.
4. `submit_source_classification` (`run_engine.py:2672-2777`) accepts a
   `SubmitSourceClassificationRequest.classifications` payload
   (`contracts.py:772-777`) and commits it via `_commit_submission`
   (`run_engine.py:2737-2746`) — this writes an event to the ledger with the
   raw request as its artifact. Nothing in this method constructs a new
   `SourceDescriptor`, a new `TrialInitialization`, or a new `RunProposal`; it
   only records that the operation happened.
5. `_source_classification_complete` (`run_engine.py:9461-9491`) — the only
   downstream reader of these committed events — walks committed
   `operation:submit-source-classification` events and extracts
   `item["source_id"]` from each payload (`run_engine.py:9487-9490`) purely
   to build a *completion* set. It never reads `item["roles"]` and never
   writes anything back into a `SourceDescriptor`.
6. `validate_result_sources` (`proposals.py:682-756`) and `_preferred_candidate`
   (`proposals.py:44-96`) both read `source.roles` directly off
   `trial.inventory.sources` — i.e., off the `SourceDescriptor` instances
   still carrying `_classify`'s original, ingestion-time value from step 3.
   There is no code path anywhere that makes a submitted classification reach
   either reader.

**Repository observation — where `SourceDescriptor` could be
reconstructed.** `ProjectInitialization`/`TrialInitialization` are themselves
embedded, immutable snapshots inside `RunProposal.initialization`
(`contracts.py:513`); a new `RunProposal` revision is how the codebase
already re-derives a fresh snapshot (`supersedes_proposal_id`,
`contracts.py:519`, and the "reconciliation" path referenced by ADR-0005).
`_latest_proposal(ledger, run_id)` (used throughout `run_engine.py`, e.g.
`run_engine.py:2723`) is the read path that reconstructs the current
in-memory `ProjectInitialization` for any operation that needs it.

**Inference — minimal correct fix.** Because `SourceDescriptor` is frozen and
`ProjectInitialization` is an embedded snapshot rather than an independently
queryable table, the interception point cannot be "mutate the descriptor in
place." Two minimal-diff options are consistent with the rest of the
codebase's patterns:

1. **Overlay at read time**: keep `SourceDescriptor.roles` as ingestion's
   original cue, but have the two readers (`validate_result_sources`,
   `_preferred_candidate`) accept an additional resolved-roles mapping
   (`source_id -> tuple[SourceRole, ...]`) derived from the latest committed
   `operation:submit-source-classification` event(s), and prefer that mapping
   over `source.roles` when present. This mirrors how `_source_classification_complete`
   already re-derives state by scanning committed events
   (`run_engine.py:9479-9490`) rather than mutating a stored snapshot, and
   requires no new `RunProposal` revision.
2. **New snapshot on accept**: construct a fresh `TrialInitialization`/
   `RunProposal` revision after an accepted classification, with
   `SourceDescriptor.roles` rebuilt from the accepted disposition — analogous
   to how a new `RunProposal` already supersedes the prior one elsewhere in
   the engine. This is more consistent with "immutable snapshot, new revision
   on change" as a project-wide convention, but is a larger diff (touches
   proposal construction/superseding code, not just the two readers).

Option 1 is the smaller, more surgical fix and does not by itself require the
full `Discovery candidate` type or a new `RunOperation` — it only requires (a)
making the two readers accept resolved-role overlay data, and (b) deriving
that overlay from existing committed events (today's `classifications` payload
already carries `source_id` and `roles`; the missing step is purely a
read-side join, not a schema change). It does *not* by itself fix the
ordering bug (source classification currently only becomes a work item after
`confirm_run_definition`, per `_next_work_item`'s `definition is None` gate at
`run_engine.py:8713-8714`) — that still requires resequencing, independent of
whether Option 1 or 2 is chosen for the write-back itself.

## E. Risk assessment and sequencing (inference)

**Repository observation — size anchors from git history.**

| Commit | Description | Files | Lines (+/-) |
| --- | --- | --- | --- |
| `788a594` | "Allow explicitly scoped unclassified evidence units" — loosen one existing gate, no new type | 3 | +31/-2 |
| `8d5ffd8` | "Rebind evidence index after Result resolution; remove sole-candidate auto-bind" — the two pieces of this same ticket already shipped | 6 | +105/-9 |
| `8668a5d` | "Implement source-preserving evidence review" — added `EvidenceCandidate`/`EvidenceReviewRevision`/disposition contract, closest prior precedent for "add a new candidate/disposition concept" | 16 | +1540/-325 |

`8668a5d`'s diff touched `CONTEXT.md`, `docs/EVIDENCE-SEARCH.md`, a new ADR,
`skills/rob2-assess/SKILL.md`, `application/contracts.py`,
`application/run_engine.py`, `domain/evidence.py`, `evidence/search.py`,
`evidence/workflow.py`, `ingestion/project.py`,
`interfaces/mcp/server.py`, and four test files (three of them new).

**Inference — effort estimate.** Given section A's touch-point inventory
(RunOperation enum, contracts, run_engine sequencing/handler, MCP
registration, release manifest, two adapter manifests, two forward-fixtures
files, ~7 test files) is a strict superset of what a same-shaped 8668a5d-class
change already cost, and given the `Discovery candidate` piece additionally
needs new types (`SourceRoleCandidate`) plus disposition retrofits on two
existing types (`ResultCandidate`, `RegistryCandidate`) plus the
`Trial discovery record` aggregate itself, a realistic estimate for
implementing pieces 1-3 in one pass is **comparable to or somewhat larger
than `8668a5d`** — plausibly 15-20 files and 1500-2500 changed lines,
including tests, docs, and both adapter manifests. This is a large single
change for one PR to review safely, especially given the unresolved
light-vs-heavy tension identified in section C.

**Inference — recommended sequencing.** Land the write-back fix (section D,
Option 1) plus the reordering (moving source-role resolution's work-item
eligibility ahead of `confirm_run_definition` in `_next_work_item`) as an
independent, small, first slice, **before** the full `Discovery candidate`
type system:

- It closes the two concrete, actively-biasing bugs (proposal generation
  reading a never-reviewed cue) on its own, independent of whether
  `Trial discovery record` ends up using the light or heavy revision pattern.
- It does not require a new `RunOperation` under Option 1 (D), so it avoids
  the ~12-touch-point mechanical cost from section A entirely for this slice
  — though note ADR-0004 explicitly prefers the new-operation-name approach
  for principled reasons (section A), so this smaller slice would need to
  either accept reusing the existing operation name as a deliberate, scoped
  exception, or fold in the (still much smaller than the full type system)
  cost of the rename now while the "declare vs. review" contract distinction
  is fresh.
- It gives an empirical basis (does source-role disposition actually change
  more than once per Trial in practice? does a UI/harness ever need to see a
  *rejected* Source-role candidate distinct from an unresolved one?) for
  resolving section C's open design question before committing to a specific
  `Trial discovery record` shape.
- The full `SourceRoleCandidate`/`Trial discovery record` type system,
  `Registry`/`Result` candidate disposition retrofits, and the deferred
  fixtures/metrics slice (explicitly deferred in the issue's own "Deferred to
  a follow-up ticket" section) can then follow as a second, separately
  reviewable change, sized similarly to `8668a5d`.

## If we implement this next (inference)

Slice 1 — write-back fix + reordering only (no new `RunOperation`, no new
types):

- `src/rob2_kit/application/run_engine.py`: `_next_work_item`
  (`run_engine.py:8705-8812`, remove/relax the `definition is None` gate
  ordering relative to source classification), `submit_source_classification`
  read-side join, and `_source_classification_complete` extended to build a
  `source_id -> roles` overlay map.
- `src/rob2_kit/application/proposals.py`: `validate_result_sources`
  (`proposals.py:682-756`) and `_preferred_candidate` (`proposals.py:44-96`)
  signatures extended to accept the resolved-role overlay and prefer it over
  `source.roles`.
- `docs/HARNESS-WORKFLOW.md`: update the ordering description at lines 17-22.
- New/updated tests in `tests/test_run_work_order.py`,
  `tests/test_input_reconciliation.py`, `tests/test_issue101.py` (the files
  already touching this operation).

Slice 2 — full `Discovery candidate` system (separate change):

- `src/rob2_kit/ingestion/project.py`: new `SourceRoleCandidate` type near
  `ResultCandidate` (`ingestion/project.py:540-549`); disposition field added
  to `ResultCandidate`.
- `src/rob2_kit/registry/clinicaltrials.py`: disposition field added to
  `RegistryCandidate` (`registry/clinicaltrials.py:59-79`).
- `src/rob2_kit/application/contracts.py`: `RunOperation` new member; new
  request/response contracts; possible new `TrialDiscoveryRecord` type (or
  reuse of `Revision`/`Supersession` directly, per section C's resolution).
- `src/rob2_kit/application/run_engine.py`: new `submit_*` handler,
  `_next_work_item` branch, completion predicate.
- `src/rob2_kit/interfaces/mcp/server.py`: new tool registration.
- `src/rob2_kit/release.py`: `SKILL_ALLOWED_TOOL_NAMES` addition; possibly a
  new `_OBSOLETE_DOCUMENTATION_TERMS` entry if `submit_source_classification`
  is renamed rather than kept as a distinct new operation.
- `scripts/release_qualification.py`: new operation exercised in replay.
- `adapters/claude/adapter.json`, `adapters/codex/adapter.json`: tool name
  addition.
- `skills/rob2-init/forward-fixtures.json` and its two adapter copies.
- `docs/HARNESS-WORKFLOW.md`, `docs/RUN-DEFINITION.md`,
  `skills/rob2-init/SKILL.md` (or `rob2-assess`, depending on which skill owns
  the step) content updates.
- `CONTEXT.md`: already updated with the new glossary terms per the issue
  comment; verify no further terminology drift once the concrete types exist.
- New test files, analogous to `tests/test_issue118_contract.py`,
  `tests/test_issue118_retrieval.py`, `tests/test_issue118_review.py` added by
  `8668a5d` for the evidence-review precedent.
