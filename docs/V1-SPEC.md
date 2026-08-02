# RoB 2 Kit v1 specification

**Status:** canonical implementation specification  
**Product:** `rob2-kit`  
**Supported runtime:** Python 3.13  
**Last reconciled:** 2026-07-30

This document is the normative implementation source for v1. It supersedes
`BLUEPRINT-Codex.md` and `BLUEPRINT-Claude.md`, which remain as historical
research inputs. When this specification, a blueprint, and an implementation
note disagree, this specification governs.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**
describe normative requirements.

## 1. Product boundary

RoB 2 Kit is a local, host-neutral evidence and workflow engine used through a
Codex or Claude Code agent plugin. It prepares:

> A source-inventoried, coverage-explicit, provenance-preserving draft
> Cochrane RoB 2 assessment for attributable human verification and sign-off.

V1 supports:

- individually randomized, parallel-group trials;
- the effect of assignment to intervention;
- English-language PDF sources;
- current ClinicalTrials.gov records;
- Codex and Claude Code from the first Hands-on preview;
- one model-authored draft followed by one accountable human review and
  Assessment sign-off.

V1 does not support:

- cluster-randomized or crossover trials;
- the effect of adhering to intervention;
- a hosted application or plugin-owned inference service;
- autonomous human review, Judgment override, or Assessment sign-off;
- embeddings, vector databases, GraphRAG, or a second parser;
- arbitrary registry, URL, filesystem, shell, SQL, or raw-FTS access;
- validation-study execution, preregistration, or manuscript production.

The product is not an official Cochrane product. Permission to redistribute the
official wording has been obtained for this project. Official wording MUST
still be isolated in a versioned Guidance pack with attribution and provenance;
it MUST NOT be duplicated across code, prompts, tests, or host adapters.

## 2. Users and experience

The primary user is a biomedical researcher who may not be technically
experienced. The normal workflow MUST:

1. start from a plain-language request in the agent harness;
2. initialize or resume a project without configuration-file editing;
3. prepare every Trial autonomously without mid-run questions;
4. preserve progress across host, browser, or computer absence;
5. keep a reopenable local Companion workspace available from project start;
6. move every Trial × Result through Ready, Prepare, Review, and Complete with
   its exact identity and current state visible;
7. present the prepared answer together with its rationale, complete evidence
   set, relevant crops, coverage, and deterministic Decision trace;
8. commit each human action immediately; and
9. return a durable Review receipt to the agent harness.

The agent harness is the control plane for setup, preparation, progress, and
opening or resuming review. The Companion workspace is a deterministic
projection of durable project state and the only v1 surface for direct human
review actions. Opening, refreshing, reconnecting to, or closing it MUST NOT
invoke a model. The CLI is for CI, diagnostics, recovery, and expert use.
Researchers MUST NOT need to move back and forth between the CLI and the agent
harness.

Preparation MUST NOT pause to ask about uncertain source roles, optional-source
failures, registry candidates, or other reviewable conditions. It records them
as Review findings and continues as far as defensible. One consolidated
up-front question is permitted only when essential project intent—normally the
project root or Outcome target—cannot be inferred.

## 3. Canonical domain model

Implementations MUST use the definitions in `../CONTEXT.md`. In particular:

- an **Outcome target** is project-level batching intent;
- a **Result** is the stable identity of one trial-specific intervention-effect
  analysis;
- a **ResultSpec revision** is its immutable resolved numerical and
  provenance-bearing description;
- a **Trial** is the randomized experiment, not a folder, report, acronym, or
  registry record;
- an **Evidence candidate** is not citable;
- an **Evidence claim** is an immutable assertion over an engine-materialized
  span from a Canonical evidence unit;
- an **Evidence Bundle** is frozen before an SQ answer is authored;
- an **SQ Answer revision** is model-authored;
- an **Algorithmic judgment revision** is deterministically derived;
- a **Final judgment** is the Algorithmic judgment after an optional human
  Judgment override;
- an **Assessment revision** is the canonical source of truth;
- a **Review finding** is an operational or evidentiary review condition, not
  an RoB 2 answer;
- an **Assessment sign-off** is an attributable human approval of one exact
  Assessment revision.

### 3.1 Stable Result identity

A Result identity MUST contain:

```text
Trial
+ Randomization
+ ordered Comparison
+ effect of interest
+ outcome construct
+ measurement/instrument
+ time point
+ analysis population and model
+ effect measure
+ unique source locator
```

The extracted estimate, interval, denominators, and other numerical values MUST
belong to the ResultSpec revision, not the stable Result identity. Correcting
them creates a new ResultSpec revision, preserves the Result ID, and
invalidates dependent work.

Outcome-dependent assessment MUST NOT begin until exactly one ResultSpec
revision is resolved. An ambiguous Result cannot yield an Assessment revision.

### 3.2 Reuse

Domain 1 SQ 1.1 and SQ 1.2 MAY be reused only under the exact key:

```text
(trial_id, randomization_id, comparison_id, rob2_variant)
```

SQ 1.3 is Result-specific. Other reuse MUST reference the original immutable
claim, bundle, receipt, or answer rather than copy it. Reuse of a search
execution never implies reuse of a question-specific coverage conclusion.
The reuse policy MUST be versioned and project-selectable.

## 4. Immutable revisions and identifiers

Every decision-relevant record MUST:

- have a stable entity ID and an immutable revision ID;
- declare its schema version;
- record direct dependencies by entity ID, revision ID, semantic role, and
  content hash;
- record its Actor and observed UTC time;
- use explicit supersession rather than overwrite;
- use algorithm-labelled SHA-256 hashes such as `sha256:<hex>`.

Raw artifacts are hashed over exact bytes. Structured artifacts are stored as
canonical UTF-8 JSON and hashed over those stored bytes. Filenames, paths,
URLs, timestamps, and PDF metadata are provenance, not identity.

Decision-relevant revisions include at least:

- Project manifest;
- Reviewer profile;
- Source inventory;
- Source component annotations;
- Parse records and Coverage maps;
- search index and Search coverage receipts;
- Evidence claims, Derived facts, Visual transcriptions, and Evidence Bundles;
- Evidence consideration and Context view manifests;
- SQ Answers, Algorithmic judgments, Decision traces, and Judgment overrides;
- Review findings and dispositions;
- Assessment revisions and Assessment sign-offs;
- Preparation attempts and Review receipts;
- Logic, Guidance, Review, Evidence search, Recovery, parser-quality, reuse,
  and context-assembly policy releases.

## 5. Packs, policies, and executable logic

### 5.1 Logic pack

A Logic pack is immutable, normative declarative data for one instrument
edition, design, and effect of interest. It MUST contain:

- permanent semantic Logic element IDs;
- canonical SQ answer values:
  `yes`, `probably_yes`, `probably_no`, `no`, `no_information`;
- applicability and branch rules;
- domain and overall judgment tables;
- required assessor inputs, including the combined-concerns input;
- source provenance and release metadata.

`not_applicable` is an engine-derived branch state, never an assessor answer.
Logic IDs MUST exclude wording, release numbers, and display numbering. A
semantic or behavior change creates a new ID; wording-only changes preserve it.

Logic is authored in reviewable YAML, schema-validated, canonicalized to JSON,
and evaluated by one host-neutral deterministic evaluator. The rule vocabulary
MUST be closed. Embedded code, templates, arbitrary expressions, or
host-specific branches are forbidden.

Every Logic-pack release MUST pass an independently transcribed Conformance
suite that exhaustively covers valid paths and answer combinations, invalid
and impossible states, overall logic, expected judgments, and Decision traces.
Two named human reviewers MUST check the reference transcription and
representative golden cases against the official instrument. Mutation testing
MUST demonstrate that meaningful branch and table mutations fail.

### 5.2 Guidance pack

A Guidance pack contains authorized official wording and nonnormative
operational aids linked to Logic element IDs. Each item MUST declare
`content_origin` as `official` or `rob2_kit`.

The pack MAY contain:

- official SQ wording, elaborations, citations, labels, and translations;
- evidence cues and semantic query families;
- likely table/figure concepts and visual gates;
- reviewer explanations and retrieval terminology.

Guidance MUST NOT change answers, applicability, branching, required inputs, or
judgments. Compatibility with Logic-pack releases MUST be explicit, never
inferred from version numbering.

### 5.3 Releases and project policies

Every pack and policy release MUST have a stable family, human-readable release
ID, canonical content hash, schema requirement, authorship/provenance, and
complete inventory. Assessments pin exact IDs and hashes. Existing assessments
never auto-upgrade.

The Project manifest selects the exact releases. Policy seams MUST remain data,
not hard-coded UI or adapter behavior:

| Policy | Owns |
| --- | --- |
| Review policy | review granularity, findings requiring verification or acknowledgment, and sign-off eligibility |
| Evidence search policy | minimum search, traversal, context views, visual escalation, and operational ceilings |
| Recovery policy | acquisition retries, adapters, parsing/OCR recovery, and terminal categories |
| Parser-quality policy | interpretation of known LiteParse signals |
| Reuse policy | permitted SQ/evidence reuse and exact keys |
| Context-assembly policy | bounded orientation/SQ payload construction |
| Project rules | optional attributable conventions that may guide, but never replace, evidence or Logic |

Changing a policy creates a new revision. Dependency invalidation MUST affect
only the revisions whose scope or interpretation may change.

Each Project rule MUST declare its stable ID, scope, conditions, rationale,
author, and date. When it materially guides an answer, the SQ Answer MUST cite
it. A Project rule cannot force an answer, alter Logic-pack behavior, replace
required source evidence, or silently set a judgment.

Logic behavior changes always trigger recomputation. Guidance releases MUST
list affected Logic element IDs and classify each change as decision-relevant
or presentation-only. Wording, elaboration, or retrieval-aid changes invalidate
dependent search/answer/review work; spelling, display-label, citation, and
provenance-only corrections do not require substantive reassessment.

## 6. Architecture

```text
Codex adapter ─┐
               ├─ canonical rob2-assess skill ─ local stdio MCP ─┐
Claude adapter ┘                                                 │
                                                                 ▼
CLI ──────────────────────────────────────────────── application services
Local review GUI ────────────────────────────────────────────────┘
                                                                 │
                             domain model / workflows / policies │
                                                                 ▼
                         SQLite ledger + content-addressed artifacts
```

The Python package owns all application and domain behavior. The host adapters,
skill, MCP server, CLI, and GUI are thin interfaces. They MUST NOT call or
shell through one another.

The application service and Workflow ledger own the state machine. Commands
own leases, transactions, idempotency, dependency validation, and Workflow
events. Queries are side-effect free and read one consistent ledger snapshot.
Domain/application types MUST NOT contain MCP, FastAPI, Typer, browser, Codex,
or Claude types.

### 6.1 Package and repository shape

The implementation SHOULD converge on:

```text
src/rob2_kit/
  domain/              # immutable types and invariants
  logic/               # pack schemas, evaluator, Decision traces
  application/         # commands, queries, work-item derivation
  storage/             # SQLite ledger and artifact store
  ingestion/           # source discovery, acquisition, LiteParse
  evidence/            # canonicalization, FTS, claims, bundles, visuals
  registry/            # ClinicalTrials.gov adapter and projections
  review/              # queue derivation, receipts, local server
  reports/             # JSON/HTML/Markdown/CSV/XLSX/archive projections
  interfaces/
    mcp/
    cli/
    web/
packs/
  logic/
  guidance/
skills/
  rob2-init/
  rob2-assess/
adapters/
  codex/               # generated
  claude/              # generated
schemas/
tests/
```

One cross-host release lock MUST pin the package release, both canonical skill
hashes, application contract, frozen dependency set, packs, and both adapter
versions. Generated adapters MUST NOT be hand-edited; build tests reject
divergence.

### 6.2 Runtime and dependencies

Python 3.13 is the sole supported v1 baseline. `uv` is the only external
runtime prerequisite. The generated launcher MUST use a version-pinned isolated
invocation equivalent to:

```text
uvx --python 3.13 --from rob2-kit==<exact-version> rob2-mcp
```

First use MAY ask once for permission to install missing `uv` through its
official platform installer. Researchers do not manage Python or virtual
environments. Plugin updates change the exact package pin; they MUST NOT use
implicit `latest`.

The v1 dependency choices are:

- LiteParse as the only parser;
- SQLite/FTS5 for the ledger and lexical index;
- Pydantic for boundary schemas;
- the official Python MCP SDK over stdio;
- FastAPI/Uvicorn/Jinja with limited vanilla JavaScript and CSS for review;
- Typer for the expert CLI;
- HTTPX for allow-listed acquisition;
- Pillow for bounded image work;
- OpenPyXL for XLSX export.

## 7. Project and source inputs

### 7.1 Project layout

The default user-facing layout is:

```text
project/
  input/
    <trial>/
      trial.yaml          # optional; required to disambiguate multiple top-level PDFs
      <primary>.pdf       # normally the single top-level PDF
      supplements/
        *.pdf
  output/                 # derived reports and exports
  .rob2/                  # ledger and local artifacts
```

The Project manifest is created conversationally and is the canonical project
intent. It records roots, supported scope, Outcome targets, source adapters,
pack and policy releases, and export/archive preferences. Host instructions
and personal settings MUST NOT define assessment semantics.

Exactly one top-level PDF is proposed as the required primary report and
verified against Trial identity. If several exist, `trial.yaml` MUST identify
the primary report for an Assessment revision to become signable. The agent
MAY propose a candidate without pausing, but ambiguity becomes a Review finding.

### 7.2 Source role and criticality

Supported roles are:

```text
primary_report
secondary_report
supplement
protocol
statistical_analysis_plan
registry_current
registry_history
clinical_study_report
regulatory_document
author_correspondence
other
unclassified_supporting
```

Roles are nonexclusive and do not establish a universal authority ranking.
Criticality is separately assigned per Result preparation:

- `required`: no Assessment revision without acquired, sufficiently usable
  content;
- `expected`: bounded acquisition/processing is required when identifiable;
  failure becomes a Review finding;
- `optional`: used when available; potentially material failure is recorded
  but does not itself fail the Trial.

Defaults are:

- required: designated primary report, the artifact with the definitive
  ResultSpec locator when different, and project-declared required sources;
- expected when identifiable: linked current ClinicalTrials.gov record,
  protocol, and SAP;
- optional: all other roles unless promoted by configuration or dependency.

Every supplied supported PDF MUST be inventoried, parsed, indexed, and searched.
Optionality changes failure consequences, not evidence consideration.

### 7.3 Classification and compound PDFs

Classification uses, in descending authority:

1. explicit manifest/trial metadata or a human correction;
2. registry metadata;
3. folder position;
4. filename, title page, document title, table of contents, headings,
   bibliographic links, and relevant text.

Every inference records cues and classifier version. Weakly classified items
remain searchable as `unclassified_supporting`; preparation does not pause.

A long PDF containing a protocol, SAP, or appendix remains one Source artifact.
Lazy, coarse, possibly overlapping Source-component page ranges MAY carry
their own roles and provenance when boundaries are explicit or relevant.
Automatic segmentation is not required. Exact page citations remain valid
without components.

### 7.4 Acquisition and custody

Every local import, registry fetch, or download creates an Acquisition receipt.
Successful acquisition copies exact bytes into the project-local
content-addressed store. Identical bytes deduplicate while every receipt and
Source relationship remains attributable.

V1 directly supports PDFs and canonical registry JSON. ZIP MAY be accepted only
as a bounded container with traversal, expanded-size, and member-count checks.
Other formats remain inventoried as `unsupported_format` with a request to
export them to PDF. A batch continues unless the item is required.

The default Recovery policy permits one initial first-party network request and
at most two retries for transient failures. Deterministic failures and identical
corrupt/encrypted bytes are not blindly retried. Resume retries only after a
relevant input, adapter, configuration, or policy change. No arbitrary scraping
or paywall bypass is permitted.

Dates MUST remain typed: publication, internal finalization/version,
submission, posting, provider upload, acquisition, and user-declared dates are
not interchangeable.

Each Source-inventory entry MUST derive three independent status dimensions:

```text
availability: declared_or_discovered | acquired | unavailable |
              access_restricted | acquisition_failed
processing:   not_attempted | usable | coverage_limited | failed
use:          not_searched | searched | search_limited | evidence_used |
              reviewed_not_used
```

These dimensions keep absent information separate from an unobtained source,
failed processing, or incomplete search.

### 7.5 ClinicalTrials.gov

An explicitly declared NCT ID wins. An exact NCT ID found in supplied sources
MAY link automatically with its locator recorded. Fuzzy candidates MUST NOT
auto-link; they remain consolidated Review findings.

The adapter MUST preserve raw responses, request parameters, retrieval time,
response metadata, separately fetched API dataset timestamp, hashes, parsed
representations, and projection provenance. Field-filtered projections point to
stable JSON locations and never replace raw data.

Provider-uploaded protocols/SAPs are acquired automatically only when
structured metadata identifies them and document fetching is enabled. Registry
history is experimental, capability-probed, nonblocking, and MUST NOT by itself
label outcome switching.

## 8. Parsing, coverage, and visual recovery

### 8.1 Parse records

Each Parse record binds the artifact hash, LiteParse/configuration,
canonicalization version, output hashes, and quality observations. Every page
has one derived Coverage-map state:

```text
text_usable
visual_required
recovery_required
coverage_limited
intentionally_blank
```

Unknown LiteParse reason codes are preserved as diagnostics. Recovery layers
never silently replace the born-digital parse.

### 8.2 Calibrated parser defaults

V1 MUST implement these versioned defaults:

1. Parse every PDF fully with OCR off and complexity on.
2. Do not trigger OCR, failure, or visuals from `needs_ocr`, `vector-text`,
   `sparse-text`, `multi-column`, `table-likely`, or figure signals alone.
3. Nominate targeted OCR for `no-text` or `scanned` pages without trustworthy
   canonical text, or for decision-relevant parse/render discrepancies.
4. Allow whole-primary OCR only when representative early, middle, and late
   checks confirm the report is genuinely scanned throughout.
5. OCR supporting documents only on nominated decision-relevant pages.
6. Make one targeted LiteParse OCR attempt per page under one Recovery-policy
   revision; then use the Visual-inspection gate or record limited coverage.
7. Use no percentage-of-pages failure threshold. Materiality governs.

### 8.3 Visual inspection

A Visual candidate requires an active-SQ connection through a ResultSpec
locator, Guidance mapping, retrieved reference/caption/row, numerical conflict,
parse/render discrepancy, or attributable agent nomination explaining likely
decision impact. Complexity alone is insufficient.

Defaults:

- render the smallest useful contextual crop at 144 DPI;
- include title, labels, legend, and relevant footnotes;
- escalate unclear small type to 180 DPI, then 216 DPI as the final automatic
  resolution;
- expand to full page when flow, panels, legends, or footnotes cross the crop;
- show one candidate per model view, or up to three tightly related crops from
  one source and SQ;
- paginate every candidate with a stable cursor;
- impose no total screenshot cap.

The bounded work unit is one nominated candidate and its crop-to-page and
resolution escalation. Continued ambiguity becomes `coverage_limited` and
opens the original page for review.

A legible but text-unanchorable reading is a Visual transcription. It remains
`visual_only` and `review_required`, even after human acceptance. Decision-
critical visual denominators, exclusions, missing-data counts, and analysis
populations require review beside the crop.

LiteParse 2.10.0 is the parsing and base-render dependency, not the durable
citation verifier. The adapter MUST preserve:

- 1-based page identity and page dimensions;
- spatial text and, when configured, word boxes in LiteParse's top-left,
  72-DPI viewport coordinate system;
- the complete requested parser configuration fingerprint; and
- a content-addressed reference to the spatial parse and base page PNG.

Rob2-kit MUST own the exact Canonical-span-to-one-or-more-box binding, coordinate
scaling, highlight overlays, contextual crops, DPI escalation, crop/full-page
navigation, content-addressed base and derived PNG storage, and dependency-based
stale invalidation. LiteParse `search_items()` is discovery-only because its
synthetic union box does not preserve the source indexes and character offsets
needed to verify a quote.

V1 MUST keep `render_form_fields=False`. A page whose decision-relevant content
depends on a form field is detected and marked `coverage_limited`; the system
MUST NOT execute PDF document actions to render filled values.

## 9. Evidence search and answer protocol

### 9.1 Canonical units and index

Headings, paragraphs, list items, captions, footnotes, and table rows are
immutable citable Canonical evidence units with page/spatial provenance.
Search aggregates and projections are non-citable and resolve to intact units.

Use SQLite FTS5 with `porter unicode61`. Agents submit structured terms,
phrases, prefixes, Boolean groups, and metadata filters. The engine compiles
raw FTS deterministically. Order by BM25 and Canonical-unit ID; ranking controls
inspection order, not relevance or authority.

Create a non-citable projection above 2,400 characters. Split at a sentence or
line boundary with one boundary sentence/line overlap. The evidence claim still
resolves to the intact Canonical unit.

### 9.2 Mandatory search

For each active SQ:

1. run every applicable Guidance seed-query family;
2. run at least one follow-up round using Trial terminology;
3. run a separate contradiction-seeking pass;
4. continue until the mandatory protocol is complete and the latest complete
   round yields no new decision-relevant candidate.

Search all usable acquired required, expected, and supplied optional sources.
Every unique returned unit from an accepted query receives a disposition:
irrelevant, retained candidate, or duplicate.

Before accepting a query, show its unique-hit count and source distribution. A
query matching both more than 100 units and more than 5% of the scoped index
requires refinement or a recorded justification for complete broad traversal.
This is not a hit cap.

Result pages target 20 hits or 8,000 characters, whichever comes first. An
oversized item gets its own page. Stable cursors MUST permit full traversal.
There is no total hit or evidence cap.

### 9.3 Context views

The Trial orientation pack targets 12,000 text characters. An SQ context pack
targets 24,000. Expanded passages target 16,000 characters and ordinarily at
most six Canonical evidence units. An oversized unit gets a dedicated view.

These are per-call transport targets, not evidence limits. Successive views
continue traversal. A Context view manifest records exact ordered items,
revisions, pagination, selection reasons, deterministic transformations, policy
identity, and host-payload hash. It MUST NOT claim hidden host prompts or
reasoning.

### 9.4 Candidates, claims, and conflicts

Every Evidence candidate is dispositioned before answering as accepted
supporting, contradicting, or contextual; duplicate; wrong scope; immaterial;
superseded with a stated chronology/amendment basis; or unresolved.

To create a text Evidence claim, the agent selects a Canonical unit and exact
character span. Deterministic code materializes the source text and binds the
artifact, Parse record, page, coordinates, and hashes. Agent-authored quote text
MUST NOT become canonical evidence. Fuzzy matching MAY locate but MUST NOT
verify a quote.

Conflicting accounts remain separate attributable claims. They may be resolved
only by defensible chronology, Guidance, or an applicable Project rule—never a
global source hierarchy. An unresolved material conflict becomes a Review
finding. If no answer survives it, preparation is incomplete.

Derived facts use a small closed registry of named deterministic derivations.
They record inputs, population, arm, analysis set, outcome/time point, formula,
units, numerator/denominator, rounding, and result. Agents select typed inputs;
they do not author calculations or choose ambiguous denominators.

### 9.5 Bundle then answer

Before an SQ answer:

1. all mandatory searches and visual gates complete;
2. every potentially material candidate is dispositioned;
3. deterministic code freezes a content-hashed Evidence Bundle;
4. every accepted item receives an Evidence consideration-manifest
   disposition;
5. the agent authors an SQ Answer revision only from that bundle.

The answering stage cannot add evidence. A discovered gap abandons the answer
attempt, returns to search, and creates a new bundle revision.

Answers are committed atomically per domain after schema and branch validation.
The logic engine then derives active/inactive SQs and the Algorithmic judgment.
The agent never supplies a domain or overall judgment.

### 9.6 No information

`no_information` is permitted only when the Search coverage receipt proves:

- every mandatory query family and follow-up completed;
- all accepted query results and required Visual candidates were traversed and
  dispositioned;
- acquired required sources and relevant obtained sources were sufficiently
  readable;
- no unresolved material candidate or coverage limitation remains.

Unavailable, unreadable, unsearched, search-limited, or interrupted material
cannot establish No information. An explicit source statement that something
was not done or reported is positive Evidence, not a search-absence inference.

## 10. Preparation workflow

### 10.1 Work-item protocol

The application derives the next Preparation work item from the Workflow
ledger. It binds exact dependencies, expected submission kind, and checkpoint.
It is not a mutable queue.

`continue_preparation` performs deterministic work until agent reasoning, human
action, cancellation, a cooperative host-safety yield, or a terminal outcome is
reached. Cooperative yielding is based on capabilities and progress, not a
fixed Trial/page budget.

Durable checkpoints include acquisition and parsing, completed search
traversals, visual inspections, frozen bundles, SQ Answers, judgments,
Assessment revisions, and human actions. Reads, navigation, partial model
responses, and unsubmitted forms are not checkpoints.

Each work unit has an operation key and dependency fingerprint. Committed work
is reused. Started but uncommitted work is retried and never converted into an
RoB 2 finding.

### 10.2 Preparation outcomes

The canonical outcome enum is:

- `draft_ready`: every active SQ has a defensible answer and an Assessment
  revision exists; nonblocking Review findings MAY remain;
- `preparation_incomplete`: a usable primary report and Result exist, but a
  material operational/evidence gap prevents a defensible active-SQ answer; no
  signable Assessment revision is emitted;
- `trial_failed`: the required primary report or Result is unrecoverable after
  bounded recovery, or page attribution is untrustworthy; no Assessment
  revision is emitted.

Earlier blueprint wording `draft_ready_with_findings` is not a separate state.
Findings are orthogonal records associated with `draft_ready`.

A batch continues after Trial-specific failure or incompleteness. Only a Run
integrity failure—untrustworthy ledger/transaction state, hash mismatch,
invalid schemas/packs/policies, unsafe writes, unsupported migration, or an
unisolatable unauthorized operation—stops the batch.

Host, model, tool, or usage-window interruption is a resumable pause, not a
Preparation outcome or Review finding.

### 10.3 Batch presentation and review gate

The Companion workspace presents Preparation as a Result-level board:

```text
Queue → Processing → Review queue
```

Each card represents one Trial × Result. A prepared judgment MUST appear only
after that card reaches the Review queue; Queue and Processing MUST NOT imply
that a decision exists. The board is read-only while preparation owns the
single-writer lease and shows the last durable checkpoint, connection state,
plain-language interruption or terminal reason, and a copyable resume prompt
where applicable.

Prepared Results MAY accumulate in the Review queue, but human review remains
locked until every Trial in the requested batch has reached a terminal
Preparation outcome. `preparation_incomplete` and `trial_failed` cards remain
visible with their consequences and available recovery action.

## 11. Ledger, invalidation, and replay

SQLite is the single live Workflow ledger. JSONL is a generated archive view,
not another source of truth. A transition transactionally appends its Workflow
event and updates derived current/checkpoint projections. Prewritten artifacts
from a failed transaction remain unreachable.

Events contain sequence, ID, scope, Actor, observed time, operation,
causation/correlation IDs, input/output revision hashes, typed outcome, and the
previous-event hash. Ledger sequence defines order.

V1 uses one project-wide writer and multiple readers. A renewable process/run
lease is transferred transactionally. Safe takeover requires expiry or
confirmed process death plus integrity validation. Commit-time dependency
checks reject stale writers.

Changing a dependency preserves history and makes only transitive descendants
inactive. Resume begins at the earliest stale checkpoint. Unaffected evidence,
answers, and Domain review dispositions remain current. Any decision-relevant
change to a signed Assessment makes its sign-off inactive.

Resume MUST run a deterministic preflight over SQLite integrity, schema
compatibility, event ordering/hash links, referenced artifact hashes, pinned
packs/policies, lease state, and checkpoint dependencies.

The Replay guarantee covers committed agent outputs and deterministic state. It
does not promise identical commercial-model output or hidden reasoning. A
deliberate model rerun creates a superseding Preparation attempt and retains the
prior output.

## 12. Human review and sign-off

### 12.1 Continuous Companion workspace

The local Companion workspace uses one reopenable shell with a persistent:

```text
Ready → Prepare → Review → Complete
```

lifecycle rail. Project → Trial → Result → Assessment is the navigation
hierarchy. Cards and consequential actions repeat the exact Trial × Result
identity in researcher-facing language; raw identifiers and hashes remain under
technical details.

Ready uses Trial × Result cards. Selecting a card shows only its secured sources
with a compact first-page preview, filename, source type, page count, and
custody/LiteParse status. Ready leads with a context-aware copyable agent prompt
for starting or resuming uninterrupted preparation.

Prepare uses the read-only board in section 10.3. Review uses the Guided review
and Full evidence audit views below. Complete progressively shows signed Results
and their outputs as specified in sections 12.6 and 15.

The UI reads joined, researcher-facing projections over the Workflow ledger,
artifact store, evidence index, pinned packs/policies, and generated outputs.
It MUST NOT infer authoritative state from board position or present a declared
schema as if the runtime had materialized its canonical revision. Required
projections include:

- current batch, Trial, Result, Assessment, and revision status;
- source inventory, acquisition, parsing, coverage, and limitations;
- Domain/SQ answers, rationales, Evidence consideration, and Decision traces;
- required actions and attention reasons;
- correction, supersession, sign-off, withdrawal, and invalidation history; and
- report, export, archive, and verification readiness.

### 12.2 Review queue and attention

The Review queue is derived from authoritative revisions and Review policy. The
v1 default requires individual review of every Domain and has no bulk
approve-all action. Guided review uses three policy-derived attention tiers:

1. **Action required** — a condition blocks sign-off: incomplete preparation or
   unresolved identity; required evidence/visual verification; a required
   limitation acknowledgment; stale review; or correction awaiting rework.
2. **Inspect carefully** — work is signable after the required scrutiny:
   Some concerns or High; accepted contradiction or Source conflict;
   acknowledged coverage limitation; elevated Visual transcription;
   `no_information`; or materially influential Project rule or override.
3. **Routine review** — no higher-tier condition applies.

`Probably yes` and `Probably no` do not by themselves elevate attention.
Several reasons may apply; the highest tier controls placement while every
reason remains visible.

Trial × Result cards are ranked by their highest tier. After the reviewer opens
a Result, ordering stays Result-scoped: Action required, Inspect carefully,
Routine review, then D1–D5 and stable item order as tie-breakers. Action-required
items follow dependency order:

1. Result/source repair;
2. evidence or visual verification;
3. limitation acknowledgment;
4. Domain review; and
5. Assessment sign-off.

Items waiting on targeted agent work remain visible but do not displace an
action the human can perform now. Each item states why it appears, the exact
Result/Domain/SQ and sign-off consequence it affects, and one concrete next
action linked to the same context in Full evidence audit.

One underlying limitation produces one finding with its source, role,
criticality, attempts, coverage, affected scope, available text/visual,
consequence, and action—not copies under every SQ.

### 12.3 Guided review and Full evidence audit

Guided review and Full evidence audit are two views of the same current
Assessment and review state. Switching views preserves Result, Domain, SQ,
selected Evidence claim, completed actions, and return position.

Full evidence audit uses the selected Pinned Evidence Desk:

- persistent Domain/SQ navigation showing answer state, judgment, limitation,
  and contradiction markers;
- a central evidence canvas pairing exact selectable text with its highlighted
  LiteParse crop or full-page context and source locator; and
- a decision inspector showing the prepared answer and rationale, preserved
  contradicting evidence, deterministic Decision trace, and coverage and
  provenance details.

Every active SQ exposes its prepared answer, rationale, complete ordered
Evidence set, coverage limitations, and Decision trace. Every Evidence item is
an explicit Supporting, Contradicting, or Context item pairing exact text with
its source/page locator, highlighted region, and provenance. Selecting among
multiple items changes the paired text-and-visual view without losing decision
context. Contradicting evidence MUST NOT be collapsed into a rationale or
hidden by Guided review.

A Routine Domain begins as a compact card showing its full name, accessible
judgment label, active-SQ and evidence counts, coverage status, and one-sentence
deterministic basis. The reviewer MUST open every Domain before confirming it
individually. Opening exposes every active answer and rationale, with each
Evidence set one action away; policy need not require opening every claim.

Every explicit human action commits immediately. Stale pages are read-only and
cannot overwrite a newer revision. Refresh, back, reopen, retry, and
double-click MUST neither lose work nor duplicate decisions.

### 12.4 Corrections and superseding work

Correction uses an impact sidecar that keeps the triggering SQ, Evidence claim,
exact text, highlighted region, and prepared decision pinned while the reviewer
writes the request.

The smallest starting target is derived from the invocation context. The
reviewer MAY expand it to a Domain or Result/source-identity repair but MUST NOT
remove downstream consequences derived from recorded dependencies. Submission
creates an attributable Review receipt bound to the challenged Assessment,
immediately blocks the affected Domain and sign-off as **pending targeted
rework**, and leaves the challenged revision immutable and valid history.

The workspace then becomes read-only for affected work and provides a
context-aware copyable agent prompt bound to the receipt. It shows only the
affected dependency path regenerating. Interruption preserves the request,
draft, blocked/current dispositions, last checkpoint, failure reason, and a
copyable resume prompt.

A successful run makes the regenerated Assessment the current proposed
revision. The comparison covers changed Evidence consideration, answer and
rationale, Domain/overall judgments, limitations, and reopened review decisions,
plus a compact list of reused unaffected work. The actions are **Continue
review** and **Request another correction**. Continue returns to the corrected
SQ and its evidence; the affected Domain requires review again. Repeated
corrections form a visible linear chain.

### 12.5 Handoff and connection state

The Companion workspace runs as a separate resumable loopback process, not a
daemon or hosted service. `open_review` idempotently starts or reconnects it,
transfers write authority when appropriate, attempts one host-supported
embedded launch, and always returns a URL. Embedded side-by-side display is a
preferred enhancement, never a portability or durability requirement. If
embedded launch is unavailable, use the system browser or returned URL.

The page self-updates from local durable state through SSE or polling without
model inference. Browser closure is harmless; reopening obtains a fresh
URL/session. No host adapter may treat pane placement, visibility, or browser
process survival as authoritative.

The workspace reports:

```text
connected—waiting
working—updating
not connected—review saved
reconnect needed
review complete
```

It also shows last contact and the plain-language consequence. `wait_for_review`
is one cancellable, activity-aware long-running call. After configurable
inactivity it returns `review_pending`, ends the agent turn, and preserves the
workspace and ledger.

A Review receipt has one typed outcome:

```text
action_completed
correction_requested
deferred
assessment_signed_off
```

It binds the exact action, Assessment/review revisions, Actor, and ledger event.
Conversation history is never required to interpret it.

### 12.6 Result sign-off and human attribution

Human actions bind an immutable Reviewer profile revision, review session,
Review policy, and Assessment revision. Display name is required; affiliation,
email, and ORCID are optional. V1 Sign-off assurance is local attribution bound
to an integrity-verifiable Assessment revision; it is neither independently
verified nor cryptographic. Passwords, PINs, routine typed-name ceremonies, and
project-held signing keys are excluded.

Sign-off is a dedicated Result-level checkpoint available only when every
Domain disposition is current and no Action required item remains. It shows the
exact Trial × Result, Assessment revision, overall and D1–D5 judgments, Domain
review state, accepted caveats, reviewer identity, and invalidation
consequences. Each summary item links to Full evidence audit. There is no bulk
sign-off.

The control reads **Sign this Result as [display name]**. Retyping is required
only after session expiry or a Reviewer profile change. The attestation is:

> I reviewed this exact Result Assessment under the stated Review policy and
> approve its recorded answers, final judgments, overrides, and acknowledged
> limitations as the current assessment.

The UI explains that signing does not claim exhaustive source discovery,
absence of error, or independently verified identity. Only explicit human
action in the Companion workspace may create a Domain disposition,
acknowledgment, Judgment override, Assessment sign-off, or Sign-off withdrawal.

Sign-off commits atomically before deterministic output materialization. Output
failure preserves **Signed — outputs incomplete** and offers retry. **Reopen
review** creates a Sign-off withdrawal without deleting the signed revision or
its outputs. A dependency change retains the old sign-off and outputs as
**Invalidated — review required**, identifies the changed path, and returns only
the affected Result to Review.

### 12.7 Clinical canvas visual system

Ready, Prepare, Review, and Complete use the selected Clinical canvas system:
deep evergreen structure, warm neutral surfaces, restrained shadows, and
amber/red only for semantic attention and RoB states. Serif is reserved for
major headings and prominent prepared answers, sans-serif for controls and
operational content, and monospace for copyable prompts and technical records.

One workspace shell, lifecycle rail, contextual guidance banner, heading/status
pill, and local-state footer frame all four stages. Reusable components are:
agent-prompt panels, Trial × Result cards, source-preview cards, Preparation
columns, Result judgment cards, the Pinned Evidence Desk, attention notices,
accessible traffic-light previews, output cards, and action groups. Semantic
variants—neutral, active, complete, attention, blocking, coverage-limited, and
signed—always retain textual labels.

Controls use one visually primary action per decision context, with secondary
actions beside it and technical/exhaustive detail behind explicit disclosure.
Progressive disclosure MUST NOT hide material evidence, limitations,
contradictions, exact Result/revision identity, or action consequences.

The three density tiers are:

1. **Orientation** — spacious Ready and Complete summaries.
2. **Operational** — moderately compact boards, sources, and Result cards.
3. **Evidence** — dense Guided review and Full evidence audit.

Desktop uses a bounded canvas with multi-column boards and the pinned evidence
desk. Intermediate widths collapse secondary columns first. At 320 CSS pixels,
content has a single-column reading order, actions become full-width where
needed, secondary header navigation recedes, and stage/next action remain
explicit. Domain strips, evidence sets, metrics, and the page image MAY scroll
within bounded regions, but equivalent exact text, provenance, decision context,
and essential controls remain readable without page-level horizontal scrolling.
Keyboard access, visible focus, programmatic labels, and non-color cues apply at
every width.

The approved prototype at
`prototype/final-companion-visual-system@c03d356` is a visual reference only.
Production code MUST implement these rules deliberately and MUST NOT promote the
throwaway prototype directly.

## 13. Interfaces

### 13.1 Canonical skill

Exactly two canonical skills are shared between hosts. `rob2-init`:

- establishes supported scope and the exact Run meaning;
- inventories inputs and presents the Run proposal;
- obtains one-time operator confirmation; and
- hands the confirmed Run to `rob2-assess`.

`rob2-assess`:

- resumes the confirmed Run;
- requests work items;
- uses bounded evidence/visual tools;
- submits typed work;
- handles structured outcomes;
- materializes terminal static reports;
- never performs a human action.

The skills obtain wording and behavior through pinned packs and tools. They
MUST not duplicate normative RoB 2 logic. Both adapters expose the same trigger
description, skill hashes, and activation fixtures.

### 13.2 MCP tools

The typed tracer stdio surface is the fixed RunEngine inventory below.  The
legacy preview gateway remains available to expert CLI callers but is not
published through MCP.

```text
prepare_run
run_status
continue_run
get_work_context
submit_run_proposal
confirm_run_definition
search_evidence
read_evidence
inspect_visual_candidate
submit_source_classification
submit_result_resolution
submit_domain_evidence
submit_domain_answers
```

Every mutation requires an idempotency key, work-item ID, negotiated contract
version, and expected dependency fingerprint. Results include operation ID,
ledger cursor, affected scope, status, findings/conditions, commit status, and
next permitted action.

After one meaningful project-scoped authorization, bounded reads and
non-destructive preparation writes MAY proceed without repetitive prompts. A
new project root, network adapter, external pack, or repair operation requires
fresh authorization. Project authorization can never authorize a human review
action.

Expected workflow envelopes are:

```text
completed
work_required
review_pending
preparation_outcome_reached
retryable_interruption
trial_problem
run_integrity_failure
```

Protocol errors are reserved for malformed calls, unavailable transport, or
unexpected faults. List/search responses use stable snapshot-bound opaque
cursors and deterministic subdivision for oversized single content.

After initialization, tools accept only engine-issued identifiers. Only
initialization accepts a user-selected root, which is resolved and confined
before mutation.

### 13.3 CLI

The expert CLI covers:

```text
rob2 init
rob2 doctor
rob2 status [--json]
rob2 continue
rob2 review
rob2 report
rob2 export
rob2 archive
rob2 verify
rob2 events
rob2 repair
rob2 mcp
```

`repair` MUST be narrow and preflighted. CLI commands use the same application
services and stable JSON/exit codes where automation needs them. The CLI cannot
fabricate agent reasoning or create human review/sign-off records.

## 14. Local GUI security and untrusted input

The GUI binds only to `127.0.0.1` on an available port. It MUST use:

- a one-time URL token exchanged for an expiring HttpOnly, SameSite session;
- CSRF protection and strict origin checking;
- a strict Content Security Policy;
- Jinja autoescaping asserted by tests;
- no source use of `safe`/equivalent bypasses;
- no remote assets or requests;
- allow-listed URL schemes;
- a fixed authorized project root.

Source content is untrusted data. It cannot authorize tools, policies, paths,
URLs, identifiers, or transitions. Boundary schemas and allow-lists enforce
this independently of prompts.

Suspicious hidden, tiny, off-page, white-on-white, invisible, bidirectional, or
parse/render-discrepant text cannot become machine-verified evidence without
the required visual route. HTML, SVG, Markdown, registry metadata, filenames,
and report content MUST be escaped and inert in GUI and exports.

## 15. Canonical output and archives

The immutable Assessment revision is the canonical output. It binds exact:

- ResultSpec and Source inventory revisions;
- Evidence Bundles, claims, facts, visuals, and coverage receipts;
- SQ Answers and applicable Project rules;
- Algorithmic judgments, Decision traces, and active overrides;
- Review findings and dispositions;
- Project manifest, packs, policies, schemas, engine, skill, and Actor
  provenance;
- active Assessment sign-off, if any.

Signing one Result triggers deterministic materialization of:

- a self-contained, print-friendly HTML report and equivalent portable Markdown
  report containing exact identity and status, overall/D1–D5 judgments, every
  active SQ answer and rationale, numbered exact-text citations, contradictions,
  conflicts, limitations, `no_information` bases, Visual transcriptions,
  overrides, review attribution, and concise provenance;
- lossless, schema-versioned canonical Assessment JSON;
- a judgment-only robvis CSV compatibility projection; and
- a researcher-facing Project XLSX with separate Result, Domain, SQ, evidence,
  limitation, and review-attribution sheets.

A Project completion report lists every expected Trial × Result, terminal
disposition, judgment and sign-off state, key limitations, and links to its
Result report. Project CSV/XLSX exports include signed, excluded, incomplete,
and failed Results without implying a signed Assessment for non-signed rows.
HTML, Markdown, robvis CSV, XLSX, and summary reports are deterministic derived
views and MUST NOT be editable inputs.

A Complete Verification archive contains the canonical manifest and every
transitive source/decision dependency, including source bytes and pinned
schemas/packs/policies. The workspace shows size, source count, generation time,
SHA-256, latest verification result, and a copyrighted/sensitive-content
warning. A Reference archive MAY omit source bytes but MUST say
`source integrity not independently verifiable`. Verification recomputes
hashes, validates schemas, dependencies, event order, and completeness, and
produces a plain-language receipt without requiring the live SQLite file.

Every artifact binds one exact Assessment or Project-state revision and remains
immutable. Stable current links MAY resolve to the latest valid artifact;
historical and invalidated artifacts remain available with unmistakable status.

Raw PDFs, registry payloads, renders, crops, and local state are excluded from
Git and ordinary shareable exports by default.

## 16. Failure semantics

The following distinctions MUST remain explicit:

| Condition | Consequence |
| --- | --- |
| Required primary/Result unrecoverable or attribution unstable | `trial_failed` |
| Primary and Result usable, but active SQ lacks a defensible basis | `preparation_incomplete` |
| All active SQs defensible, with nonblocking limitations | `draft_ready` plus Review findings |
| Expected/optional source unavailable | Review finding; may remain `draft_ready` if nonmaterial |
| Text-unanchorable but legible visual | `visual_only`, `review_required` |
| Exact region cannot be recovered | `coverage_limited`, never No information |
| Time, usage, host, or tool interruption | resumable pause / `search_limited` receipt where applicable |
| Shared ledger/hash/schema/policy integrity lost | Run integrity failure |

An operational ceiling MUST be observable, cancellable, and resumable. It MUST
never silently truncate evidence, establish No information, or allow sign-off
when missing coverage may be material.

## 17. Release milestones and acceptance

### 17.1 Hands-on preview

The earliest owner build is ready when both Codex and Claude Code can:

- install and start on the owner’s Windows environment;
- process the same supported Trial end to end;
- produce equivalent deterministic judgments and ledger consequences;
- open the same GUI with inspectable evidence;
- resume after host disconnection;
- make preview/unsigned status unmistakable;
- prevent all nonhuman sign-off paths.

Preview schemas may change incompatibly, but upgrades MUST retain a recoverable
archive or migrate a copy and explain incompatibility. External usability
testing, formal accessibility review, research validation, and cosmetic polish
are not preview blockers.

### 17.2 Public v1 blockers

Public v1 requires executable gates for:

- Logic-pack conformance, invalid states, and mutation detection;
- unambiguous Result identity and correct Domain 1 reuse;
- exact evidence provenance, bundle completeness, visual typing, and
  No-information basis;
- adversarial input and inert report/GUI rendering;
- checkpoint transactions, interruption, safe resume, and targeted invalidation;
- required-primary, optional-source, and Run-integrity failure isolation;
- cross-host contract, deterministic, and workflow equivalence;
- human-only, exact-revision sign-off and stale-session handling;
- critical GUI usability and accessibility;
- loopback/privacy/path/network boundaries;
- installation, canonical outputs, exports, and archive verification.

WCAG 2.2 AA is the design target. Known defects that prevent or dangerously
mislead the critical workflow block public v1. A formal conformance audit and
external usability study do not.

The owner completes the critical flow without step-by-step assistance.
Dangerous misunderstandings and blockers are fixed and their affected scenarios
rerun; cosmetic issues, extra clicks, and recoverable friction with a clear safe
path become follow-up work. Owner-only acceptance MUST NOT be described as
independent validation of first-time-user comprehension.

Automated acceptance includes three end-to-end journeys:

1. multi-Result preparation, evidence review, Result sign-off, and export;
2. interruption/resume followed by correction and a superseding revision; and
3. a material limitation and terminal preparation failure plus rejected stale
   or wrong-Result action.

Representative Ready, Prepare, Review, correction, sign-off, and Complete states
MUST have no serious or critical accessibility scanner findings, expose
programmatic names and keyboard activation, manage dialog focus, announce
important state changes, retain textual status equivalents, and keep the
critical path usable at 320 CSS pixels. The owner smoke check confirms keyboard
operation and a comfortably enlarged display size.

### 17.3 Platform claims

Hands-on preview is manually verified on Windows. Public-v1 core/package CI
covers Windows, macOS, and Linux. Both real hosts receive a manual end-to-end
Windows check. Other host/OS combinations remain unverified until the same
checklist passes.

## 18. Required fixtures

Keep a small distributable suite covering:

- every supported Logic path and invalid state;
- multiple Results, reports, Randomizations, instruments, measures, and time
  points;
- correct and incorrect reuse;
- born-digital, scanned, sparse, blank, garbled, table, flowchart, and
  parse/render-discrepant pages;
- compound protocol/SAP PDFs;
- missing/corrupt required sources and failed optional sources;
- source conflicts and ambiguous denominators;
- visible and hidden prompt injection, hostile markup/links/Unicode/metadata,
  malformed PDFs, and path/container attacks;
- interruption before/after commit, host disconnection, stale GUI actions,
  duplicate submissions, targeted invalidation, and archive verification;
- identical normalized submissions through both host adapters.

The private `eval/reference/` corpus is for feasibility and hands-on work only.
Its PDFs are not redistributed. Its CSV judgments are Provisional reference
labels, not a correctness oracle.

## 19. Calibration provenance and change rule

The numeric defaults in sections 8 and 9 come from
`FEASIBILITY-CALIBRATION.md`: 37 PDFs, 2,680 pages, and LiteParse 2.10.0. They
are policy defaults rather than universal correctness thresholds.

Remeasure when LiteParse, canonicalization, host image handling, or corpus mix
changes materially. A changed measurement MAY produce a new policy release; it
MUST NOT weaken these invariants:

- complete source/search/candidate accounting;
- no silent truncation;
- no operational failure converted to No information;
- no unreviewed visual transcription treated as verified text;
- no sign-off over a material unresolved gap.

## 20. Implementation completion definition

This specification is implemented when:

1. every normative boundary has one owning module and schema;
2. the application can execute the complete supported workflow through both
   generated adapters;
3. the acceptance gates in section 17 are executable or explicitly manual;
4. canonical artifacts and archives independently verify;
5. no blueprint-only behavior is needed to understand or operate v1.

Implementation sequencing belongs to the separate backlog derived from this
specification. Research validation remains a later track consuming a frozen
release.
