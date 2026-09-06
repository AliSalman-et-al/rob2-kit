# RoB 2 Assessment

`rob2-kit` is a model-free FastMCP boundary for evidence-grounded Cochrane
Risk of Bias 2 assessment. Codex or Claude Code supplies the only model loop.
The server owns durable workflow state, source capture, evidence identity,
strict validation, deterministic RoB 2 logic, and verified artifact export.

## Workflow

A **Batch** contains one or more **Trials**. Researcher-authorized dossiers use
the fixed `input/{TRIAL NAME}/` layout. `prepare_batch` receives only the exact
requested outcome; the server discovers every immediate non-hidden, non-link
Trial directory, derives a stable Trial ID from its name, and captures all
supported Sources in that directory. Intake records their content and
projection identities and attempts registry resolution. A typed Intake condition
remains visible to the model but does not create a researcher gate.

The closed workflow phases are `empty`, `proposal`, `assessment`,
`ready_to_finalize`, and `finalized`.

1. `prepare_batch` captures the Batch and advances to Proposal construction.
2. The model retrieves Source material, selects Evidence, and saves one complete
   Result proposal per Trial.
3. **Proposal Review** is the only researcher gate. The researcher may approve,
   reject, or replace the chosen Result mapping.
4. After approval, the model answers all active signaling questions and the
   server derives Domain and overall judgments.
5. Accepting the fifth Domain freezes that Trial's AssessmentSnapshot and marks
   it `assessed`. `finalize_batch` packages the terminal Trial records into the
   verified bundle. There is no Assessment Review or final approval.

A **State revision** is the optimistic-concurrency basis for one mutation. A
stale revision returns a typed conflict and never adopts newer state silently.
An identical retry returns the same logical record without duplicating history.

## Authority

Researcher authority enters through `rob2 review` or capability-backed MCP
elicitation, either of which acknowledges one exact Proposal Review record. A
model-authored tool call cannot approve the record by itself: the MCP path
commits only a directly accepted client elicitation. The researcher may change
the Result only before that approval.

After approval, signaling answers are model-owned. User messages that prescribe
or revise answers are not scientific authority. The server exposes no researcher
answer-edit field, and the skill tells the host to ignore such instructions.
Because the server cannot infer conversational causation, enforcement is split at
the honest boundary: the skill controls conversation policy and the server
requires typed, auditable revision lineage.

`rob2 discard` is a separate researcher-only CLI action. It records a tombstone,
keeps any finalized artifact, clears the active workflow and derivative source
state, and permits a new Result target. It is not an MCP tool.

## Sources, projections, and Evidence

A **Source** is an immutable captured document with a Trial-scoped identifier,
content hash, page count, logical path, role, origin, and text-projection hash.
Absolute paths and Source bytes do not enter the finalized bundle.

A **Text projection** is a deterministic, page-preserving derivative used for
search and exact text selection. PDF pages use plain text plus compact Markdown
tables only when table structure is meaningful. Raw PyMuPDF4LLM JSON is not a
model-facing contract. Captured JSON is presented as a sorted, canonical
path-value projection with arrays preserved by index; the captured bytes remain
the content authority. A **Verified render** is a content-addressed PNG derivative
used when layout, axes, footnotes, or table geometry affect meaning.

The exact page projection is Evidence authority. Capture normalizes Unicode
compatibility forms, ligatures, ordinary punctuation variants, line endings,
PDF line-end hyphenation, and nonprinting formatting artifacts once. Search,
page reads, and selected quotations use that same readable projection. A
separate versioned FTS derivative adds case folding and tokenization for
discovery without becoming Evidence. `read_pages` presents stable
one-based source-page indexes and bounded windows of numbered lines from the
authoritative projection. A typed line cursor continues a large page without
changing its coordinates. Text selection names one inclusive, contiguous line
range on one page; the server stores that exact projected text. Rebuilding the
disposable FTS derivative must not change Source, projection, Evidence, or
workflow identities. The immutable captured bytes remain available for audit.

An **Evidence handle** is a short, Trial-scoped transport pointer to selected
text or a selected visual region. Canonical Evidence retains Source identity,
page, exact quote or transcription, and applicable render provenance. Search
hits are navigation results, not Evidence. Each search creates an immutable,
Trial- and projection-bound candidate ranking. Bounded responses carry stable
candidate ranks and an opaque cursor so lower-ranked passages can be inspected
without rerunning retrieval. The Source-diverse display order is that one
stable rank everywhere, and the active Domain is associated with the complete
session even before lower candidates are returned. A no-hit search receipt documents the search
performed; it does not prove scientific absence.

## Result model

A **Result target** specifies the requested outcome, measurement, time point or
window, effect of assignment, comparison groups, analysis population, and effect
measure. A **Reported result** separately records what a Source actually reports.

The closed Target relation is `exact`, `broader`, `narrower`, `component`,
`related`, `ambiguous`, or `unavailable`. `exact` is
reserved for a normalization-equivalent target and reported endpoint name. When
the requested endpoint is absent, the model proposes the closest complete
Source-defined candidate with a visible non-exact rationale. It must compare
scientific definitions, not names or effect sizes. The Proposal contains the
single best complete candidate per Trial; competing candidates inform the
choice but are not serialized as alternatives.

An assessable Reported result is a comparative effect, group-bound values, or a
single-group category profile. Selected Evidence is durable workspace state,
not caller-supplied Proposal structure. On Proposal submission, the server binds
the Result to selected Evidence, retains only material used by the Result, and
derives canonical field bindings. Structural identifiers such as `group_id` and
`category_axis_names` connect typed fields but are not Source claims. Source-owned
reported labels, values, units, denominators, endpoint definitions, and category
cells must remain bound to exact selected Evidence. Target method, timing,
population, effect measure, and arm assignments are researcher-reviewed
interpretation fields and do not require duplicate bindings. An unavailable Result requires one typed
basis for each missing fact. Normally, that basis is selected Evidence that
explicitly establishes missing reporting. For a Trial with zero captured Sources,
the basis is instead the exact captured `no_supported_sources` Intake condition.
Both forms still pass through Proposal Review.

The Proposal is atomic across the Batch. A researcher-approved unavailable Result
becomes a `needs_input` terminal automatically; it does not enter Domain assessment.

## Domain assessment and revision

The scientific pack contains the fixed five RoB 2 Domains, deterministic question
activation and judgment logic, the licensed official question guidance, and
separately attributed rob2-kit operational guidance. The pack retains each
question's full nested official and operational guidance for authoritative
assessment and artifact/audit use. `get_domain_context` returns a compact typed
question-card projection with the full official excerpt and locator plus the
actionable operational fields needed to answer that question. Operational guidance
supplements the official source; it never replaces or impersonates it. Cards
replace bare answer strings with server-issued options that bind the exact
question and pack version to the official code, literal proposition, certainty,
anchor, branch activation, and decision-table value. The caller submits only
`option_id`; the checkpoint retains only the official RoB 2 answer. Each active
answer has at least one typed basis: a selected Evidence handle, a scoped
absence receipt, or an explicit limitation. For selected Evidence, the server
derives the exact quote or transcription stored in the checkpoint; the caller
does not copy a second source fragment. Before using an absence receipt or
limitation, the model must perform bounded, question-specific discovery across
the relevant Sources; the current Result Evidence set is never treated as an
exhaustive search. Plans do not prove conduct, endpoint labels do not prove
measurement properties or prespecification, and relationship labels never add
facts to a Source premise. Activation is dependency-closed: a dependent
question can become active only when its parent path is active. The server
ignores and does not commit extra inactive branch answers, but still requires
every active answer. The caller evaluates predicates transitively against
earlier answers in the same Domain save rather than discovering one branch per
repair cycle.

The Domain Evidence workspace has separate mandatory Result, active-checkpoint,
and contradiction tiers. Disposable search candidates are included only when
their immutable session was associated with the requested Trial and Domain;
other-Domain search fragments are excluded before the 64-candidate budget is
applied. Typed groups expose inclusion reasons and question scope, and any
omission carries an executable session cursor. Explicitly selected unscoped
passages take priority as carry-forward material, with exact read continuation
if they exceed the disposable budget. D2, D3, and D5 additionally
receive read-only comparison cards: the server fills only known Result scope,
Source provenance, and compatible D3 arithmetic, leaving causal, follow-up,
censoring, and plan-correspondence classifications to the host.

A **Domain checkpoint** is an immutable, content-addressed record of the active
answers, inactive questions, Evidence uses, search accounts, deterministic
judgment, and evaluation trace. The first save has no revision basis.

While the Trial remains pending, the model may replace an active checkpoint only
by naming its exact `supersedes` identity and one closed revision basis:

- `new_evidence` names selected Evidence absent from the prior checkpoint and
  actually used in the revised answers;
- `self_correction` records the model's concise reason for correcting its own
  prior decision.

Every prior checkpoint remains in immutable history. The server recomputes the
Domain, active snapshot, and overall judgment. Exact retries are idempotent, and
finalized artifacts cannot be revised. The researcher cannot invoke this mechanism
to coach an answer; disagreement requires discard and a fresh run.

Five active Domain checkpoints produce an immutable **AssessmentSnapshot**,
freeze the Trial, and change its disposition to `assessed`. Where multiple
`some_concerns` judgments require an overall decision, the model must submit the
typed `multiple_concerns` decision requested by the server before that fifth
checkpoint can be accepted. Batch finalization only packages Trial records that
are already terminal.

## Terminals and artifacts

Each finalized Trial is exactly one of `assessed`, `needs_input`, or `failed`.
Typed terminal requests commit automatically after Proposal approval and carry
concrete missing facts or failure facts. A failed terminal cannot be inferred from
an unsuccessful tool call. Terminal Trials are unassessed.

A **Finalized artifact bundle** is a deterministic `.rob2.zip` containing
Canonical JSON, static HTML, selected Evidence records, claims, content hashes,
and independent-verifier input. It excludes Source files, credentials, prompts,
host traces, and absolute paths. The product verifier and standalone verifier
replay the same scientific and integrity invariants independently.

Canonical state lives in SQLite. Rebuildable text, search, render, and handle
indexes live in a separate derivative SQLite store. Losing derivatives cannot
change Canonical records or scientific judgments.

## Public boundary

The v0.5 FastMCP surface preserves exactly 14 strictly typed tools:

`prepare_batch`, `get_status`, `list_sources`, `search_sources`, `read_pages`,
`select_text_evidence`, `render_page`, `select_visual_evidence`, `save_proposal`,
`request_proposal_approval`, `get_domain_context`, `save_domain_judgment`,
`request_trial_terminal`, and `finalize_batch`.

Input and output schemas are closed Pydantic unions. Tool descriptions state the
single operation, required caller inputs, and server-owned fields. The live
`rob2://current-batch` resource is the restart-safe projection. The package ships
one portable, progressive-disclosure `rob2-assess` skill shared by Codex and
Claude Code.

The successor interaction and field ownership are recorded in ADR 0031. Actual
host delivery is tracked separately in `docs/acceptance/v0-4-host-matrix.md`;
unrun or unobservable checks remain explicitly incomplete.
