# RoB 2 Assessment

## Investigation vocabulary

**Search purpose**: The question or Domain motivating a discovery action. It is
distinct from the Sources searched and from the questions that may eventually
use the discovered Evidence.

**Scientific sufficiency**: The host's judgment that inspected Evidence supports
an answer or that a material unresolved premise has been honestly bounded. A
search receipt does not establish scientific sufficiency. A support status
preserves the host's stated relationship between a premise and Evidence; it is
not a server-verified entailment judgment.

**Premise record**: A compact working record for one material scientific
proposition. It keeps source-located observations, the host's tentative
inference, counterevidence, unresolved information, and the next discriminating
action separate. It is resumable working state, not Canonical Evidence or a
saved signaling answer.

**Scientific limitation**: A material unresolved premise together with the
reason the investigation stopped. It is not proof that the relevant fact is
absent from the captured Sources.

## Existing workflow contract

`rob2-kit` is a model-free FastMCP boundary for evidence-grounded Cochrane
Risk of Bias 2 assessment. Codex or Claude Code supplies the only model loop.
The server owns durable workflow state, source capture, evidence identity,
strict validation, deterministic RoB 2 logic, and verified artifact export.

## Workflow

A **Batch** contains one or more **Trials**. Researcher-authorized dossiers use
the fixed `input/{TRIAL NAME}/` layout. `prepare_batch` receives the requested
outcome and optional exact Trial labels. The server discovers immediate
non-hidden, non-link Trial directories, limits the Batch to named Trials when
provided, and derives stable Trial IDs from their names. It captures all
supported Sources in each selected directory. Intake records their content and
projection identities and attempts registry resolution. A typed Intake condition
remains visible to the model but does not create a researcher gate.

The closed workflow phases are `empty`, `proposal`, `assessment`,
`ready_to_finalize`, and `finalized`.

1. `prepare_batch` captures the Batch and advances to Proposal construction.
2. The model completes the required bounded main-report text pass, selects
   Evidence, submits complete cards and assessments through `validate_proposal`,
   then saves the exact returned receipt for one complete Result proposal per Trial.
3. **Proposal Review** is the only researcher gate. The researcher may approve,
   reject, or replace the chosen Result mapping.
4. For each approved Trial with a supported design, the model repeats the bounded
   text pass before its first Domain assessment. It submits the complete active
   answer draft through `validate_domain_assessment`, saves the exact returned
   receipt, and the server derives Domain and overall judgments.
5. The fifth Domain makes a supported Trial `reviewable`; its checkpoints can
   still be corrected. `review_trial` binds the approved Result and exact
   current checkpoint set, then `close_trial` makes that reviewed outcome
   immutable and advances the Batch. `finalize_batch` packages only closed
   Trial records. Proposal Review remains the only researcher gate.

An open Trial may have one replaceable **working checkpoint** containing
source-located observations, interpretations, terminology, unread ranges, open
questions, and unfinished drafts. It is bound to the Trial's captured Source
projections and exact current Result. It is resumable working memory, not
Evidence, a Domain answer, or Canonical state. `get_status` suppresses its
contents after a Source or Result mismatch; absence or staleness calls for
reorientation from the current sources.

Each text pass covers the same source-order prefix of the full captured Source,
up to 65,536 UTF-8 source-text bytes per report at whole-line boundaries. A
`budget_limited` pass permits progression with explicit partial coverage and
unread-range navigation. Relevant omitted passages remain subject to targeted
discovery. Appended material remains part of the captured Source; the host does
not select a report boundary. Coverage records prove delivery, not comprehension
or retention in a later host context.

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
text or a selected visual region. Returned handles have a fixed compact form;
the input schema admits plausibly copied handle shapes so the application can
return a scoped unknown-handle repair instead of a transport-level pattern
error. Canonical Evidence retains Source identity,
page, exact quote or transcription, and applicable render provenance. Search
hits are navigation results, not Evidence. Each search creates an immutable,
Trial- and projection-bound candidate ranking. Bounded responses carry stable
candidate ranks and an opaque cursor so lower-ranked passages can be inspected
without rerunning retrieval. The Source-diverse display order is that one
stable rank everywhere, and the active Domain is associated with the complete
session even before lower candidates are returned. A no-hit search receipt documents the search
performed; it does not prove scientific absence. The public `search_sources`
boundary requires an explicit lexical mode: `all`, `phrase`, `any`, or
`prefix`. A returned `any` ranking that is broad and truncated carries a
deterministic diagnostic built only from request and result facts (term count,
counts, truncation, and cursor availability) and one executable refinement or
continuation. The diagnostic is retrieval advice, never a relevance,
completeness, or scientific judgment; narrow, untruncated, and no-hit
responses do not receive a broad-query warning. An initial multi-token `all`
or `phrase` no-hit carries a separate deterministic one-step diagnostic
offering the same query as `any`, preserving Trial, Source scope, and limit.
It remains retrieval advice: the receipt documents only the issued lexical
query, and the host inspects returned passages rather than treating suggestions
or widening actions as a checklist.

## Result model

A **Result target** specifies the requested outcome, measurement, time point or
window, effect of assignment, comparison groups, analysis population, and effect
measure. A **Reported result** separately records what a Source actually reports.

The closed Target relation is `exact`, `broader`, `narrower`, `component`,
`related`, `ambiguous`, or `unavailable`. `exact` means equivalent scientific
scope across the complete requested and reported Result. Different names require
a source-grounded correspondence rationale; matching names or effect sizes alone
do not establish equivalence. When no equivalent Result exists, the model proposes
the closest complete Source-defined candidate with a visible non-exact rationale.
Historical bundles retain their recorded relation semantics, including the older
normalization-equivalent-name rule. The Proposal contains the
single best complete candidate per Trial; competing candidates inform the
choice but are not serialized as alternatives.

An assessable Reported result is a comparative effect or group-bound values
that contain both comparison groups. A single-group category profile is
descriptive and cannot support comparative RoB 2 assessment. If an otherwise
relevant report supplies only one group, use an unavailable Result, retain the
exact source passage as Evidence, and name the missing comparator or estimate
explicitly. Do not classify results as ineligible solely because the source
labels its population mITT, per-protocol, or as-treated; assess the reported
comparative result on its documented terms. Historical bundles retain their
recorded one-group semantics. Selected Evidence is durable workspace state,
not caller-supplied Proposal structure. On Proposal submission, the server binds
the Result to selected Evidence and derives canonical field bindings. Canonical
records retain Evidence used by the Result and its applicability assessment.
Structural identifiers such as `group_id` and `category_axis_names` connect typed
fields but are not Source claims. Source-owned reported labels, values, units,
denominators, endpoint definitions, and category
cells must remain bound to exact selected Evidence. Target method, timing,
population, effect measure, and arm assignments are researcher-reviewed
interpretation fields and do not require duplicate bindings. An unavailable Result requires one typed
basis for each missing fact. Normally, that basis is selected Evidence that
explicitly establishes missing reporting. For a Trial with zero captured Sources,
the basis is instead the exact captured `no_supported_sources` Intake condition.
Both forms still pass through Proposal Review.

The Proposal is atomic across the Batch. An approved Result that needs no Domain
assessment, such as an unavailable Result or a known unsupported design, first
becomes reviewable. `review_trial` records its typed outcome and supporting
facts; only `close_trial` makes it terminal. It does not enter Domain assessment.
Every assessable Result also records source-grounded pack applicability through
`design`, `rationale`, and `evidence`. The server determines pack support from
`design`; the installed pack supports individually randomized parallel trials.
Known designs require same-Trial Evidence. After Proposal
Review, known unsupported designs receive an `unsupported_design` outcome for
the appropriate pack; unresolved designs need source information establishing
the design and unit of randomization. Neither condition makes an available
Result unavailable.

## Domain assessment and revision

The scientific pack contains the fixed five RoB 2 Domains, deterministic question
activation and judgment logic, the licensed official question guidance, and
separately attributed rob2-kit operational guidance. The pack retains each
question's full nested official and operational guidance for authoritative
assessment and artifact/audit use. `get_domain_context` returns a compact typed
question-card projection with the full official excerpt and locator plus the
actionable operational fields needed to answer that question. The receipt's
`pack` object names the exact pack ID, version, and content hash. Each card also
contains a bounded, typed set of executable query suggestions with compact
query text, explicit lexical mode, an optional recommended Source role, and purpose.
Suggestions are maintained retrieval vocabulary and alternatives, not claims
that a Source uses those words or a mandatory search sequence. Operational guidance
supplements the official source; it never replaces or impersonates it. Cards
expose the official RoB 2 answer values allowed for each question. The caller
submits the selected value as `answer`; the server checks it against that
question's allowed values and the checkpoint retains the official answer. A
repair echoes the submitted proposition and explains the unmet requirement
without selecting a replacement answer. Each active
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

`search_sources` preserves the requested lexical mode and returns factual
zero-hit feedback for that mode, including complete-query and bounded per-term
page counts. Counts do not establish co-occurrence or scientific absence. A
scoped miss can expose literal Source navigation; `list_sources` also returns
the captured dossier inventory, intake conditions, declared omissions, and
bounded heading/page excerpts when given a Source ID. `search_sources_batch`
runs up to eight independent, already-known queries with separate outcomes and
cursors. It does not change BM25 ordering or impose a search sequence or count.

The model-facing Domain context is staged: the approved Result, complete
question semantics, and comparison cards precede bulk Evidence. Comparison
cards use `question_id` to resolve wording and options in exactly one returned
question card. Result scope, passage groups, and slots remain on the comparison
card. The 64-item disposable selection limit is separate from
the 12,288-byte budget for recoverable narrative Evidence text. When that text
is omitted, the selected narrative Evidence keeps its identity, handle,
coordinates, and executable `read_pages` recovery windows. Visual transcription,
table values, and derived values remain inline when the existing tools cannot
recover their exact canonical text. This projection does not alter canonical
Evidence, checkpoints, hashes, or final bundles.

Context cursors freeze the approved Result, pack, question view, preview, and
requested Domain checkpoint. Searches and unrelated Domain commits may advance
the current workflow revision without changing an existing page chain. A changed
Result, pack, preview, or same-Domain checkpoint requires a fresh scoped context.
Recoverable discovery candidates are omitted by default; set
`include_candidates=true` on a fresh `get_domain_context` request to include them.
The existing cursor continues its original snapshot, and a fresh opt-in view can
show newly discovered Evidence.

The Domain Evidence workspace has separate mandatory Result, active-checkpoint,
and contradiction tiers. Canonical tiers sit outside the 64-item disposable
selection limit and take priority within the recoverable narrative-text budget.
Opt-in search candidates are included only when their immutable session was
associated with the requested Trial and Domain. Explicit recoverable passages
also require `include_candidates=true`; nonrecoverable explicit Evidence remains
inline outside the 64-item recoverable disposable limit and is never silently
dropped. Other-Domain search fragments are excluded before the 64-item disposable
selection limit is applied. Typed groups expose inclusion reasons and question
scope. Candidate omissions carry an executable session cursor or exact text
recovery action; an unavailable search session is stated explicitly after
derivative cache loss.
Explicitly selected unscoped passages take priority as carry-forward material,
with exact read continuation if they exceed the 64-item selection limit. D2, D3,
and D5 additionally receive read-only comparison cards. The server fills only
known Result scope, Source provenance, passage groups, and compatible D3
arithmetic. The host classifies causation, follow-up, censoring, and plan
correspondence.

For Domain 4, the host's audit starts from the approved event and ascertainment
method, then checks method suitability, between-group detection opportunities,
assessor identity and awareness, and any influence mechanism in that order.
Awareness is separate from susceptibility to influence; mixed-outcome passages
require an explicit premise link or a stated inference/unresolved link.

A **Domain checkpoint** is an immutable, content-addressed record of the active
answers, inactive questions, Evidence uses, search accounts, deterministic
judgment, and evaluation trace. The first save has no revision basis.

While the Trial remains open, the model may replace an active checkpoint only
by naming its exact `supersedes` identity and one closed revision basis:

- `new_evidence` names selected Evidence absent from the prior checkpoint and
  actually used in the revised answers;
- `self_correction` records the model's concise reason for correcting its own
  prior decision.

Every prior checkpoint remains in immutable history. The server recomputes the
Domain, active snapshot, and overall judgment. Exact retries are idempotent, and
finalized artifacts cannot be revised. The researcher cannot invoke this mechanism
to coach an answer; disagreement requires discard and a fresh run.

Five active Domain checkpoints produce an **AssessmentSnapshot** and make the
Trial `reviewable`; the Trial is still correctable until closed. The server
computes the overall judgment at the fifth checkpoint using the deterministic
Cochrane rule; the model does not submit or override that aggregation.
`review_trial` binds the approved Result and
pack-ordered checkpoint identities to an assessed or typed terminal outcome.
The server rejects closure when that review is stale. `close_trial` accepts only
the exact current review identity, makes the outcome immutable, and advances to
the next Trial or Batch finalization.

## Terminals and artifacts

Each closed Trial has exactly one of `assessed`, `needs_input`,
`unsupported_design`, or `failed`. `review_trial` assigns a typed outcome and
binds its concrete missing facts, design limit, or failure facts to the current
Result and checkpoints. `close_trial` makes that reviewed outcome terminal.
Unavailable Results and unclear designs become `needs_input`; designs outside
the installed pack become `unsupported_design`. A failed terminal cannot be
inferred from an unsuccessful tool call. Non-assessed Trials have no Domain
judgment.

A **Finalized artifact bundle** is a deterministic `.rob2.zip` containing
Canonical JSON, static HTML, selected Evidence records, claims, content hashes,
and independent-verifier input. It excludes Source files, credentials, prompts,
host traces, and absolute paths. The product verifier and standalone verifier
replay the same scientific and integrity invariants independently.

Fresh v0.9 Proposals contain Result cards without caller-selected report scopes
and require a source-bound reasoning assessment before the receipt-only save.
Historical v0.5 through v0.8 bundles retain their recorded semantics for
verification, including v0.6 report scopes and boundary Evidence.

Canonical state lives in SQLite. Rebuildable text, search, render, and handle
indexes live in a separate derivative SQLite store. The small working
checkpoint has its own durable noncanonical store, so a cold search-cache
rebuild does not discard it. Losing derivative indexes cannot change Canonical
records or scientific judgments.

## Public boundary

The v0.9 FastMCP surface exposes exactly 19 strictly typed tools:

`prepare_batch`, `get_status`, `save_working_checkpoint`, `list_sources`,
`search_sources`, `search_sources_batch`, `read_pages`,
`select_text_evidence`, `render_page`, `select_visual_evidence`,
`validate_proposal`, `save_proposal`, `request_proposal_approval`,
`get_domain_context`, `validate_domain_assessment`, `save_domain_judgment`,
`review_trial`, `close_trial`, and `finalize_batch`.

`validate_proposal` must validate the complete Proposal draft before
`save_proposal` consumes its exact receipt. `validate_domain_assessment` must
validate the complete Domain draft before `save_domain_judgment`
consumes its receipt. These calls validate structure, Evidence references, and
workflow requirements. They do not establish scientific correctness. Proposal
Review remains the only researcher approval gate.

DOCX Sources project ordinary paragraphs, table rows and cells, and footnotes
onto synthetic page 1. Legacy `.doc` files remain unsupported, and image-only
PDFs remain renderable through `render_page` without searchable text. Intake
conditions are visible in status and current receipts.

Visual Evidence requires a `delivery_receipt` issued with a returned MCP
`ImageContent` block. The receipt binds the Trial, Source, render, and PNG hash;
it attests that the server returned image pixels, not that a host inspected or
understood them. Metadata-only renders do not issue a receipt.

Historical v0.5 through v0.8 surfaces and Result semantics are contract notes.
Their finalized bundles remain independently verifiable. The live tool list and
schemas are generated from `src/rob2_kit/interfaces/mcp/server.py`; regenerate
`docs/release/public-contract.json` to inspect them.

Input and output schemas are closed Pydantic unions. Tool descriptions state the
single operation, required caller inputs, and server-owned fields. The live
`rob2://current-batch` resource is the restart-safe projection. The package ships
one portable, progressive-disclosure `rob2-assess` skill shared by Codex and
Claude Code.

The successor interaction and field ownership are recorded in ADR 0031. Its
historical sections are superseded by the live contract above. Actual
host delivery is tracked separately in `docs/acceptance/v0-4-host-matrix.md`;
unrun or unobservable checks remain explicitly incomplete.
