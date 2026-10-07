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
supported Sources in each selected directory. The optional native
`acquire_registry_documents` initial-intake argument overrides manifest document
acquisition; true requires explicit Trial labels, false disables it, and omission
preserves existing settings. Current registry-linked planning PDFs become distinct
Sources with readable acquisition provenance. The choice binds the intake
declaration and cannot refresh an existing Batch. Capture is not host reading or
proof of prespecification; missing documents do not determine signaling answers. Intake records their content and
projection identities and attempts registry resolution. A typed Intake condition
remains visible to the model but does not create a researcher gate.

An approved open Trial can use `acquire_companion_source` with one explicit
Source/page/citation-bound public reference and the exact current revision. The
bounded fetcher stages immutable candidate bytes and provenance without admitting
or delivering Source pages. `admit_companion_source` explicitly appends that
candidate PDF and provenance as Other Sources in the same workspace. It preserves
prior Source bytes, IDs, projections and scientific records, creates an immutable
Batch inventory version, and invalidates only the target Trial's review and
search/context/working currency. Unaffected Trials retain their currency. Old
page delivery remains bound to exact immutable Source coordinates; the new PDF
requires `read_pages`. Both bundle verifiers authenticate the inventory lineage
and historical search accounts against their original versions. Closed Trials
cannot admit Sources. Acquisition dates and identifier mentions are not scientific
authority. The approved Result remains fixed; material mapping changes require
explicit researcher scope review, not an automatic rewrite (ADR0041/ADR0030).

The optional native `request_companion_source` tool records a supplied Source/page-bound
reference and returns an optional host acquisition handoff. It performs no network
request, staging, Source admission or reading, and leaves the current workflow
continuation intact. The host CLI `stage-companion` accepts native Source handles
and fetches supported cited public PDFs or exact DOI metadata-advertised PDF links
into a fresh workspace. It requires an explicit registry replay/refresh policy and
reports input versions, omitted captured Sources and potential refreshes. Input
copying is not necessarily captured-corpus preservation. Candidate/provenance are
Other Sources after prospective intake and review; requested protocol/SAP role is
a hint. Body identifiers are page-located observations, distinct from explicit
front-matter registration claims and registry-link evidence. Applicability remains
unverified. Original Sources, ledger and historical review bindings remain intact;
no optional reference forces restart, NI or a scientific judgment.

The closed workflow phases are `empty`, `proposal`, `assessment`,
`ready_to_finalize`, and `finalized`.

1. `prepare_batch` captures the Batch and advances to Proposal construction.
2. The model completes the required bounded main-report text pass, selects
   Evidence, submits one candidate with scope/population reasoning and citations per Trial
   through `validate_proposal(selections, expected_revision)`,
   then saves the exact returned receipt for one complete Result proposal per Trial.
3. **Proposal Review** is the only researcher gate. The researcher may approve,
   reject, or replace the chosen Result mapping.
4. For each approved Trial with a supported design, the host uses a current
   Result-bound working checkpoint to resume reading when one is available.
   It completes any unread report ranges and recovers exact passages needed
   for its answers. If the checkpoint is absent or stale, the host reorients
   from the current Sources. It submits each complete active answer draft once
   through `save_domain_judgment`. The server validates and commits the draft
   atomically, then derives Domain and overall judgments.
5. The fifth Domain makes a supported Trial `reviewable`; its checkpoints can
   still be corrected. `review_trial` binds the approved Result and exact
   current checkpoint set, then `close_trial` makes that reviewed outcome
   immutable and advances the Batch. `finalize_batch` packages only closed
   Trial records. Proposal Review remains the only researcher gate.

For paginated Domain context, `head.next_action` carries the exact pending
cursor and byte budget. `context_page.delivery_status` is `incomplete` until
the last ordered page; `section: complete` names the header section only.
Context delivery completion does not establish scientific sufficiency or
Domain, Trial, or Batch completion. Status and rejected calls recover a pending
page only while its Source, Result, pack, and Domain checkpoint basis remains current.

Proposal validation, pending status and approval display a read-only `scope_review`
of the exact target, reported endpoint/population and source-bound field paths.
Reported timing and estimand are not separately represented in the Result type;
their null projection calls for source interpretation, not an absence finding.
Exactness is a host assertion about equivalent scope, not a consequence of known
target metadata or bound numbers. Material conflict or uncertainty belongs in
clarity and rationale; exact relation with a declared non-specified facet is
repaired, while a supported non-exact candidate can proceed to researcher review.
Alternate wording is not compared heuristically. Historical Result identities
and approvals remain unchanged.

An open Trial may have one replaceable **working checkpoint** containing
source-located observations, interpretations, terminology, unread ranges, open
questions, and unfinished drafts. It is bound to the Trial's captured Source
projections and exact current Result. It is resumable working memory, not
Evidence, a Domain answer, or Canonical state. `get_status` suppresses its
contents after a Source or Result mismatch; absence or staleness calls for
reorientation from the current Sources. Its source locators are host assertions;
they do not establish that a passage was delivered or understood. Status reports
the ranges actually returned by `read_pages` or `primary_report` context pages
separately from Sources referenced in working notes.

Each text pass covers the same source-order prefix of the full captured Source,
up to 65,536 UTF-8 source-text bytes per report at whole-line boundaries. A
`budget_limited` pass permits progression with explicit partial coverage and
unread-range navigation. Relevant omitted passages remain subject to targeted
discovery. Appended material remains part of the captured Source; the host does
not select a report boundary. Coverage records prove delivery, not comprehension
or retention in a later host context.

`get_domain_context` keeps scientific guidance and selected Evidence separate from
primary-report reading. Its `reading_recovery` points to exact unread `read_pages`
windows; report text is not embedded in an immutable context snapshot. Only
successfully returned source ranges enter delivery coverage. Verified receipts
are reused across Domains; an existing Domain or cached text does not substitute
for source delivery. A manageable report is read completely once. Longer reports
retain the bounded prefix and exact unread-tail recovery. Source-wide coverage
can report `read_complete` only when all projected lines have delivery receipts;
selected quotes alone establish only partial coverage. A changed Result requires
reassessing source relevance, not automatically rereading identical source text.
Lost delivery receipts restore unread-window recovery. Identical accepted saves
and source-bound working checkpoint semantics remain unchanged.

D2/D3 context coverage exposes bounded, unread document-structure recovery for
flow/disposition captions and outcome/follow-up headings in captured supplements.
This reuses literal Source navigation and exact `read_pages` windows. It is not
selected Evidence, extracted participant counts, a lexical absence receipt, or
an automatic requirement to read every appendix page. A No information answer
retains the host's bounded scientific stopping rationale; the server does not
turn a navigation match into a signaling answer or risk label.

Main-report identification is separate from reading coverage. A unique declared
`main_article` role identifies the report. Inferred roles and fallback reading
remain visible but do not certify report identity. When identification is
unresolved, the host may inspect captured Sources and record the chosen
`main_report_source_id` with source-located observations in its working
checkpoint. Reading a fallback protocol or plan does not complete the required
pass for an unidentified report. If no report can be identified, the host
preserves that limitation rather than claiming complete coverage.

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

Routine `get_status` returns selected narrative Evidence identities and exact
recovery coordinates without repeating quotes. `include_evidence_text=true`
restores the bounded text for reorientation; omitted text is never a no-hit or
evidence of absence.

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
An assessable Proposal records Result clarity for the outcome definition,
measurement, time point, analysis population, comparison groups, effect measure,
source table meaning, and candidate choice as `specified`, `unclear`,
`unavailable`, or `conflicting`. Omitted clarity is stored as `unclear`. An
`exact` relation requires every facet to be specified. These are host
classifications shown at Proposal Review; `time_point` includes material
data-cut chronology, and `source_table_meaning` includes consistency of the
selected estimate and precision across the relevant material. They do not
establish semantic correspondence by themselves.

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
activation and judgment logic, and source-bound complete official guidance.
`get_domain_context` delivers one paginated official core with full question
elaborations, relevant background and scoped FAQ answers. Recover every page before
assessment. Question cards provide wording, options, activation, source locators and
retrieval suggestions; they do not duplicate scientific answering rules. The receipt's
`pack` object names the exact pack ID, version, and content hash. Each card also
contains a bounded, typed set of executable query suggestions with compact
query text, explicit lexical mode, an optional recommended Source role, and purpose.
Suggestions are maintained retrieval vocabulary and alternatives, not claims
that a Source uses those words or a mandatory search sequence. Navigation and
workflow guidance do not impose additional scientific answer rules. In D3,
outcome-driven rescue or switching does not establish that endpoint measurements
were unavailable. Available outcomes excluded from the assignment analysis belong
to D2; genuinely unobserved measurements require D3 appraisal. A scheduled visit
proves neither collection nor non-observation. Preserve the unknown observation
premise and compare the reported handling with the approved effect of interest;
matching the endpoint and time alone does not establish the same estimand. Cards
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
search scope containing unavailable captured bytes instead returns a typed
condition naming unavailable Sources and Sources whose bytes remain present.
It searches no text and issues no absence receipt. The host may search those
other Sources explicitly; each scoped search still verifies bytes and projection
integrity, and its receipt establishes only that narrower scope. A
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

Participant-flow rows keep study/follow-up completion (`completed`) separate
from endpoint observation, analysis inclusion and imputation. Completion never
enters missing-outcome arithmetic. Comparison projections retain the row's
outcome-status and censoring semantics together with Result scope and source
coordinates; they do not infer overlap or a signaling answer.
Visual row bases retain their Source, render identity, image region, delivery
receipt, host provenance and uncertainty in `figures`; extracted-text bases
remain in `passages`. Neither projection verifies the host's interpretation.

For Domain 4, the host's audit starts from the approved event and ascertainment
method, then checks method suitability, between-group detection opportunities,
assessor identity and awareness, and any influence mechanism in that order.
Awareness is separate from susceptibility to influence; mixed-outcome passages
require an explicit premise link or a stated inference/unresolved link.

A **Domain checkpoint** is an immutable, content-addressed record of the active
answers, inactive questions, Evidence uses, search accounts, proposed/adopted
judgments, and the proposed algorithm evaluation trace. The first save has no revision basis.

An optional explicit host adjudication under ADR 0040 binds an unchanged saved
checkpoint, exact Result/Domain, scientific pack and its immutable answer Evidence.
It records why the default misrepresents material bias, the adopted label, assessor
attribution and source-linked counterevidence. Omission preserves the proposal.
Answers and evaluator drivers remain unchanged; their trace is proposed-only.
Changed answers require a new checkpoint and cannot inherit adjudication. Both
verifiers check these bindings; structural validity does not prove the rationale.

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
proposes the overall judgment at the fifth checkpoint from adopted Domain labels
under ADR 0039. Multiple Some concerns escalate to High only with an explicit
Result/checkpoint-bound cumulative-concerns assessment that concludes their
combination substantially lowers confidence. Historical unmarked snapshots
retain ADR 0035 semantics solely for verification.
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

New static reports project the approved Result, saved Domain answers and warrants,
unresolved premises, proposed/adopted judgments, and local selected-Evidence links
from Canonical records. Algorithm routes describe derivations, not empirical
findings; an included No information answer remains explicitly unresolved without
asserting that it determined the judgment. New exports bind
`report_format: rob2-kit.human-report.v1` into the Canonical bundle identity. Both
verifiers require that format's exact report; unmarked historical bundles retain
their aggregate-only HTML. Result, Domain and Evidence identities are unchanged;
the format marker changes the bundle identity. Existing valid artifacts are not
rewritten. Replacing the report or stripping its marker cannot retain that bundle
identity. Hashes do not authenticate provenance against wholesale re-identification.

Result semantics v0.9 allow an explicitly null group statistic when its meaning
is not identified in the Source. Values, units, and endpoint identifiers remain
source-bound, and unclear statistic meaning cannot be marked specified.
Historical result semantics v0.8 continue to require nonblank statistic labels.

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

The current typed tool catalog is generated in `docs/release/public-contract.json`.
It includes packaged guidance, optional arithmetic, immutable companion source acquisition
and admission, source reading, proposal and assessment workflows.

`validate_proposal` must validate the complete Proposal draft before
`save_proposal` consumes its exact receipt. `save_domain_judgment` accepts a
complete Domain draft, validates it, and commits it at the expected revision in
one operation. Invalid drafts leave canonical state unchanged. These calls
validate structure, Evidence references, and workflow requirements. They do not
establish scientific correctness. Proposal
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
single operation, required caller inputs, and server-owned fields.
MCP input schemas inline their shared definitions so code-mode clients can expose
the nested required fields instead of unknown argument objects. Output schemas
retain shared definitions. Domain argument errors include a complete fictitious
syntax example; neither schema delivery nor error formatting changes validation
or the caller's scientific choices. The live `rob2://current-batch` resource is the restart-safe projection. The package ships
one portable, progressive-disclosure `rob2-assess` skill shared by Codex and
Claude Code.

The successor interaction and field ownership are recorded in ADR 0031. Its
historical sections are superseded by the live contract above. Actual
host delivery is tracked separately in `docs/acceptance/v0-4-host-matrix.md`;
unrun or unobservable checks remain explicitly incomplete.

Working observations may carry host-asserted Result/group/stage/window/population/method scope. Evidence bases accept a compact optional interpretation during ordinary Domain submission; the server captures the cited Evidence locator, retaining exact source material separately. No working-checkpoint ceremony is required. Existing unchanged checkpoint links remain valid for resumed work. Scope categories expose mismatch, partial overlap, unknown applicability, and shared trial context without deciding relevance or labels. Neither typing nor source binding certifies entailment. Legacy notes/bases omit these fields.

Opt-in lean Domain drafting uses the existing bases list: compact selected handles or exact text source ranges assert supporting facts, normalized as indirect_support through the existing selector and canonical validator. Full citations preserve explicit roles and optional annotations. Counterpoints accept the same references. No extra drafting tool, ledger, source-fact duplication, scope inference or answer coercion is introduced; official guidance, active-path and uncertainty checks remain unchanged. Inline annotations omit redundant Domain/question copies supplied by their parent; historical note fields remain valid.

Delivered visual references use the same opt-in Domain basis/counterpoint path:
`{delivery_receipt, region, transcription, uncertainty?}` resolves through the
existing visual selector. Source, page, render and PNG hash come from the authentic
current-Trial image receipt; transcription and uncertainty remain host observations,
not OCR truth or entailment certification. Explicit-role citations accept these
references too. Text ranges retain narrative provenance and never cover graphical
cells by attaching a rendered page. Proposal construction still uses selected visual
Evidence; reusable selected handles remain available for long repeated transcriptions.

Opt-in source checking reviews the existing selected-Trial question answers in a
fresh context through the existing exporter. It pairs each complete accepted answer
with its official question guidance and asks for retain/revise/uncertain findings,
using precise canonical entry IDs and captured Source handles. It validates advisory
locators against current captured Sources and immutable checkpoint identities.
It certifies provenance only, never semantic support or reviewer correctness.
There is no automatic application, new canonical ledger or finalization gate; the
original assessor accepts/rejects findings through ordinary Domain submission.
See `docs/source-checking.md`. No default paid reviewer stage is enabled.

## Optional selected-Result reconstruction

An open Trial's existing working checkpoint may use `result_account` instead of
its overlapping observation/interpretation/premise/draft collections. Source-linked
factual steps describe how the selected Result was produced, with counterevidence,
uncertainty and optional existing participant-flow rows. These rows feed Domain
context before judgments. Existing Evidence warrants can reference a step identity;
its original observation and full step are snapshotted without changing source
scope. Known scope differences require a rationale for the relevant use as context,
contradiction or inference, preserving the original scope. Changed relied-on steps
flag affected answers for reconsideration, never change labels. Historical
checkpoints and bundles retain their original identities. The format is supported
and optional;
behavioral scientific improvement has not been demonstrated. See ADR0038 and the
skill's selected-Result reconstruction reference for the host procedure.

Native Trial review retains an Evidence basis's original source-bound working
observation snapshot, including a linked Result-account step's inference,
unknowns, counterevidence and count-Evidence bindings. It is the warrant's
relied-on snapshot, not a current account revision or server-verified entailment.
Existing bounded review detail recovery preserves this optional state without
adding a consistency gate, scientific answer coercion or default account-first
workflow. Proposed/adopted judgments remain separate and unchanged.

Reported group units may be null when no literal source unit is established.
A non-null unit remains source-bound; null neither asserts dimensionless nor
resolves a conflict. Put scientific unit interpretations and limitations in the
existing scope rationale, and keep source-table clarity unresolved when a unit
is null. Result semantics v0.10 records this distinction; historical v0.9 and
older exports retain their original non-null unit requirements. This changes
representation, not RoB judgments or source-entailment authority.
