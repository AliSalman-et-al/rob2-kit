# Brittle evidence guards and semantic review in rob2-kit

## Scope and method

This note investigates whether rob2-kit should use deterministic document-zone
and Trial-discourse guards to decide what an agent may inspect or cite. It
covers the current source, the CHAARTED progression-free-survival failure, the
existing retrieval/assessment design decisions in issues [#90](https://github.com/AliSalman-et-al/rob2-kit/issues/90),
[#113](https://github.com/AliSalman-et-al/rob2-kit/issues/113),
[#114](https://github.com/AliSalman-et-al/rob2-kit/issues/114), and
[#116](https://github.com/AliSalman-et-al/rob2-kit/issues/116), and primary
sources on RoB 2 support, provenance, MCP tool contracts, and document reading
order.

The report distinguishes three kinds of statement:

- **Repository observation**: directly supported by the cited file and line
  range.
- **External evidence**: supported by a linked first-party specification or
  peer-reviewed/standards source.
- **Inference/recommendation**: a design conclusion for rob2-kit, not a claim
  established by an external source.

No implementation or test change is proposed in this note.

## Executive conclusion

The current indexing guard is too brittle to be the primary evidence-discovery
boundary. It conflates three different questions:

1. **Where can the agent look?**
2. **What does a passage mean, and which Trial/Result does it describe?**
3. **What exact source span is admissible as Evidence for a signaling question?**

The code currently answers all three partly through deterministic labels and
filters. That is safe against some obvious bibliography false positives, but
it fails open operationally when labels are missing (the CHAARTED run produced
searchable text but no citable passages), and fails closed scientifically when
non-standard headings, mixed paragraphs, or layout fragments are classified
incorrectly.

**Recommended direction (inference):** make indexing and retrieval broad enough
to expose all source-authored material, while retaining immutable provenance and
a deterministic freeze gate. Treat `document_zone`, Trial discourse, and
canonical kind as *signals and warnings*, not irreversible retrieval
exclusions. Let the agent inspect bounded full context and explicitly prune
candidate material before freeze. Accept Evidence only when the retained span
has exact source provenance, a stable source/parse identity, an attributable
semantic scope, and an explicit disposition. Bibliography/reference text can
be visible for source discovery and context, but should normally be disposed as
out of scope rather than silently removed or accepted as trial-conduct Evidence.

This retains a scientific safety boundary without requiring a regex to recognize
every journal's heading or a keyword to decide which Trial a sentence concerns.
It also avoids treating “the model is intelligent enough” as an unmeasured
correctness guarantee: model interpretation should improve recall and propose
semantic links, while the engine preserves the audit trail and refuses
ambiguous retained claims.

## External evidence relevant to the design

### RoB 2 requires support for each answer and judgment

The RoB 2 paper describes a workflow of signaling questions, domain judgments,
and free-text support. It recommends brief direct quotations from study reports
and protocols whenever possible, while allowing the assessor to use judgment
when reporting is incomplete. The paper also distinguishes the algorithmic
judgment from the assessor's supported final judgment. This supports a design
where an agent may interpret surrounding context, but every factual claim still
needs a traceable source passage and an explicit explanation of uncertainty.
[RoB 2, BMJ 2019](https://www.bmj.com/content/366/bmj.l4898)

### Provenance should describe derivation, not merely a label

W3C PROV-O models provenance using Entities, Activities, and Agents, with
relationships such as `wasDerivedFrom`, `wasGeneratedBy`, and
`wasAttributedTo`. A retrieved projection, an agent's semantic classification,
and a frozen Evidence claim are therefore better represented as linked
derivations than as one mutable boolean such as `citable=true`.
[W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/)

### MCP supports bounded, structured, recoverable retrieval

The MCP tools specification gives tools descriptions, input schemas, optional
output schemas, structured results, resource links, and tool-execution errors.
That is enough to expose a broad candidate/disposition workflow without
returning an unbounded document dump or hiding semantic uncertainty in a
transport error. A result can carry the exact canonical identity, surrounding
context, warnings, and a continuation/resource link as structured data.
[MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

OpenAI's tool guidance likewise treats descriptions and schemas as part of the
model-facing contract, and recommends testing metadata against positive,
negative, incomplete, and edge-case requests. That favors explicit retrieval
purposes such as `evidence_mining`, `source_discovery`, and `context_review`,
rather than making the model infer an unspoken exception to a blacklist.
[OpenAI: Define tools](https://developers.openai.com/plugins/plan/tools),
[OpenAI: Optimize metadata](https://developers.openai.com/plugins/guides/optimize-metadata)

### PDF reading order and section classification are known hard problems

Peer-reviewed document extraction work reports that ordinary PDF-to-text tools
can interrupt sentences with column changes, captions, footnotes, and headers.
The LA-PDFText system therefore separates block detection, rhetorical
classification, and stitching, and notes that stitching depends on classification
accuracy. This directly supports treating LiteParse geometry and inferred
reading order as uncertainty-bearing provenance, not as a reliable paragraph
boundary merely because text exists.
[LA-PDFText, BMC/PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3441580/)

Recent EMNLP work similarly frames reading order as relations among layout
elements rather than assuming one universally correct flat permutation.
[Modeling Layout Reading Order as Ordering Relations, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.540/)

## Inventory of brittle components

### 1. Zone blacklist is an irreversible retrieval decision

`src/rob2_kit/evidence/search.py:60-83` defines a closed `DocumentZone` enum
and a hard `FORBIDDEN_RETRIEVAL_ZONES` set containing bibliography, contents,
page furniture, and extraction artifacts. `SearchQuery` rejects queries naming
those zones at `src/rob2_kit/evidence/search.py:414-470`.

The SQL scope builder then unconditionally removes forbidden zones, null zones,
and `unknown` zones at `src/rob2_kit/evidence/search.py:1583-1600`. The direct
unit scope check repeats the same exclusions at
`src/rob2_kit/evidence/search.py:1603-1645`. Thus `include_uncertain` and
`include_other_trial` are optional semantic exceptions, but no caller can
request bibliography or unknown-zone material through the normal retrieval
path.

**Brittleness:** zone names are not a stable property of arbitrary PDFs. A
reference section may be headed `Literature cited`, `References and notes`, or
not headed at all. A page may contain a two-column mixture of body text,
footnotes, and references. Conversely, the word “reference” can occur in valid
body prose. A hard blacklist converts an imperfect classifier into a recall
boundary.

**Impact:** the agent cannot inspect excluded material to explain why it is
irrelevant, find a primary source for source discovery, or recover from a bad
zone label. In CHAARTED, the more severe failure was the complementary one:
unknown-zone units were searchable in the raw index but all became non-citable,
which produced “no exact citable passages” everywhere.

### 2. Zone inference is heading/continuation regex logic

`RunEngine._canonical_zone` at
`src/rob2_kit/application/run_engine.py:4547-4583` accepts parser labels,
then recognizes only exact first-line headings for References/Bibliography,
Contents, Introduction, Methods, Results, and Discussion. It carries a
non-unknown page zone over subsequent pages at
`src/rob2_kit/application/run_engine.py:4645-4658`.

This is conservative about ordinary prose, but it is still a regex and
continuation heuristic. A section can begin mid-page, use a journal-specific
label, or share a page with another zone. A mistaken heading or inherited zone
can hide a whole continuation page.

### 3. Trial discourse is inferred from three phrases

`_canonical_discourse` at
`src/rob2_kit/application/run_engine.py:4585-4603` normalizes explicit parser
labels, maps a few aliases, and otherwise marks a unit `OTHER` only when its
lower-cased text contains `another trial`, `other trial`, or `external trial`.
Everything else becomes `UNCERTAIN`.

The design has a good safety property—unknown text is not silently asserted to
be the active Trial—but it is not semantic classification. It misses indirect
references (“the earlier study”, a named trial acronym, a cited comparison) and
cannot split a mixed paragraph containing both the active and another Trial.
It also makes the unit rather than the claim the classification boundary.

The retrieval and citation consequences are hard-coded at
`src/rob2_kit/evidence/search.py:1583-1588`, `src/rob2_kit/evidence/search.py:1638-1644`,
and `src/rob2_kit/application/run_engine.py:2584-2603`: uncertain material may
be surfaced in the engine-issued scope, but citation still requires
`ACTIVE`, a resolved Result, a classified kind, a Trial/Domain/question mapping,
and exact Result applicability.

### 4. Canonical unit kind uses text-shape heuristics

`_canonical_kind` at `src/rob2_kit/application/run_engine.py:4507-4544`
recognizes list items, captions, tables, footnotes, and headings using regular
expressions, punctuation, word counts, and Markdown coincidence. If LiteParse
has multiple text items, the index may promote an unlabeled item to a paragraph
at `src/rob2_kit/application/run_engine.py:4705-4720`; if it has no items, the
page becomes one unclassified unit at `src/rob2_kit/application/run_engine.py:4856-4895`.

These rules are useful fallbacks for synthetic fixtures, but they do not prove
that a fragment is a source-authored paragraph, that a numeric line is a
footnote, or that a short colon-ended line is a heading. The CHAARTED finding
that LiteParse produced many short/interleaved items is therefore a structural
problem, not only a missing zone label; see [#116](https://github.com/AliSalman-et-al/rob2-kit/issues/116).

### 5. Result applicability can be inferred from cardinality

When a parser does not supply applicability, `_index_initial_evidence` assigns
`RESULT` whenever the Trial has exactly one Result at
`src/rob2_kit/application/run_engine.py:4773-4790`, and the canonicalization
fallback repeats the same default at
`src/rob2_kit/application/run_engine.py:4905-4924`.

This is a dangerous adjacent heuristic. A single selected Result does not mean
every paragraph, reference, protocol statement, or unrelated outcome is
Result-specific. Rebinding the index after Result resolution is necessary for
freshness ([#113](https://github.com/AliSalman-et-al/rob2-kit/issues/113)), but
reindexing must not turn lack of semantic mapping into affirmative Result
provenance.

### 6. Source-role classification uses folder position and filenames

`_classify` at `src/rob2_kit/ingestion/project.py:2025-2062` uses explicit trial
metadata when available, otherwise treats the top-level PDF as primary,
classifies nested files as protocol when `protocol` appears in the filename,
as SAP when a filename regex matches, and labels remaining files as supporting.

This is appropriate as an inventory proposal, but it is not enough to determine
the scientific role of a document. A file named `protocol-deviations.pdf` may be
a results report; a supplement may contain the decisive analysis; a registry
record may describe a different Result. Source role should remain an attributed,
revisable orientation signal and should not by itself decide passage eligibility.

### 7. Result discovery and registry identification also contain keyword gates

Outcome/result candidate matching uses case-folded substring comparisons for
construct, time point, effect measure, and instrument at
`src/rob2_kit/ingestion/project.py:840-861`. Registry discovery uses an exact
NCT regular expression and a minimum extracted-text length at
`src/rob2_kit/ingestion/project.py:1230-1251`.

Those gates are useful candidate generators, but they should not be described
as semantic identity resolution. They can miss non-NCT identifiers, aliases,
abbreviations, OCR variants, or a Result whose defining information is expressed
without the requested keyword. The repository's own domain model says that
acronyms, isolated citations, and keywords cannot alone establish Trial identity
or Result availability (`CONTEXT.md`, Trial and Result definitions).

### 8. Freeze and terminal readiness currently encode brittle assumptions

The evidence freeze validator requires complete typed coverage receipts and exact
canonical passages at `src/rob2_kit/application/run_engine.py:3581-3720`. That
boundary is valuable, but it assumes the index has already assigned enough
semantic IDs for an agent to produce those passages. There is no alternate
“candidate reviewed but semantic classification unresolved” path that preserves
the full context for later adjudication.

The terminal materializer only turns coverage limitations into a diagnostic when
the submitted `coverage_state` is `incomplete` at
`src/rob2_kit/application/run_engine.py:5510-5564`. This is the issue documented
in [#114](https://github.com/AliSalman-et-al/rob2-kit/issues/114): an empty
Evidence trail can be labelled `complete_with_limitations` and still proceed to
answers and judgment. This is not a zone heuristic, but it is an adjacent
eligibility gate that amplifies the consequences of brittle classification.

Finally, question and Domain report traces currently receive the complete
evaluator rule list at `src/rob2_kit/application/run_engine.py:5654-5764`; see
[#115](https://github.com/AliSalman-et-al/rob2-kit/issues/115). This is a
provenance projection problem rather than a retrieval gate, but it makes the
resulting decision trace harder to audit.

### 9. MCP instructions reinforce the hard boundary

The MCP surface deliberately tells the agent to inspect only issued units and
never broaden scope. `search_evidence` rejects raw FTS and caller budgets in
`src/rob2_kit/interfaces/mcp/server.py:450-500`; the shared reference says search
returns non-citable projections and only exact spans from returned canonical
units may be submitted (`docs/EVIDENCE-SEARCH.md:1-60`).

That is a good anti-hallucination rule, but it currently means a semantic
classification defect is experienced as “no evidence” instead of “candidate
found; subject/zone/Result scope needs review.” The skill should teach the
agent how to inspect and prune broad candidates, not tell it that the engine's
first classifier is infallible.

## Design options and tradeoffs

| Option | Discovery behavior | Safety boundary | Main benefit | Main failure mode |
| --- | --- | --- | --- | --- |
| A. Keep the current hard guards | Hide forbidden/unknown zones and uncertain discourse | Deterministic labels plus exact citation checks | Low false-positive exposure for weak agents | Non-standard documents become invisible; CHAARTED-style zero-citable runs; no recovery path |
| B. Remove all guards and trust the agent | Agent sees full text and decides what matters | Exact span/source hash only | Highest recall and simplest ingestion | Bibliography, another-Trial text, tables, and parser fragments can be accepted if the agent misreads context; “intelligent enough” is not a measured guarantee |
| C. Broad candidates plus explicit semantic review (recommended) | Index all authored material; rank/annotate zones and scope signals; expose bounded context | Freeze requires exact provenance, explicit disposition, attributable subject/Result scope, and no unresolved material candidate | Separates recall from acceptance; supports recovery and pruning; preserves auditability | More candidate-review calls and a richer protocol; requires evaluation and careful defaults |
| D. Model-only preclassification | A model labels zone/Trial/Result before indexing | Deterministic checks validate shape and source identity | Better semantic recall than regex alone | A model error is converted into a durable hidden exclusion unless every alternative and revision is preserved |

Option C is the only option that addresses both observed failure classes: it
removes brittle discovery exclusions while keeping a deterministic scientific
acceptance boundary. Option D can be an internal candidate-generation aid, but
its labels must remain revisable signals, never the sole reason a unit is absent
from search or a claim is citable.

## Recommended direction

### Change the meaning of indexing

Index every preserved source-authored unit that has text or visual provenance,
including unknown and likely reference material. Keep `document_zone`,
`discourse_scope`, `applicability`, and parser warnings as nullable, versioned
metadata. Remove their role as an irreversible *discovery* exclusion.

The index should distinguish at least:

- `candidate_visible`: may be returned for inspection;
- `machine_citable`: exact deterministic provenance and structure are adequate;
- `agent_review_required`: semantic subject, Result, zone, or reading order is
  unresolved; and
- `excluded_by_disposition`: an attributable review decision says the candidate
  is out of scope, immaterial, duplicate, or superseded.

These are not interchangeable. In particular, `candidate_visible` must never
imply `machine_citable`, and a bibliography candidate may be visible for source
discovery while remaining ineligible as conduct Evidence.

### Make semantic review claim- and context-oriented

Use the agent for interpretation where deterministic rules are weakest:

1. Search returns coherent candidates from all zones, with source title/role,
   page, section/geometry, parser quality, current scope, and warnings.
2. Read returns the full bounded source-authored unit and nearby same-section
   context. If a sentence crosses parser fragments, the agent sees the fragments
   and the reading-order/visual limitation rather than a fabricated paragraph.
3. The agent submits a semantic review record for each retained or potentially
   material candidate. The record identifies exact spans, the Trial/Result it
   describes, whether it is active-Trial, other-Trial, mixed, or unresolved, and
   why the passage is supporting, contradicting, contextual, or out of scope.
4. The engine verifies identity, span bounds, source/parse hashes, Work-token
   scope, and disposition completeness. It does not reclassify the agent's
   prose by regex.
5. Freeze creates immutable Evidence Bundles only from accepted exact spans.
   Material unresolved or ambiguous candidates block the affected question or
   produce a diagnostic; they are not silently dropped.

This is an agent-assisted *review* workflow, not an agent override of the
scientific contract. A source-discovery pass may deliberately inspect
bibliography/reference text to locate primary reports, but the discovered
reference is then a separate Source candidate and the bibliography entry itself
does not become support for a RoB 2 answer.

### Replace binary Trial labels with span-level subject attribution

Keep deterministic Trial identity from confirmed Results and source custody.
Replace the current unit-wide `ACTIVE`/`OTHER` exclusion semantics with an
attribution record that can say:

- the span describes the active Trial's Result;
- the span describes another named or identifiable Trial;
- the span compares or mixes Trials;
- the subject is not explicit; or
- the reading order/identity is unresolved.

Mixed paragraphs should be split only when exact source geometry and text spans
support the split. Otherwise retain the whole context as a limited candidate and
require the agent to select a narrower exact span or mark it unresolved. A
sentence about another Trial should not poison the entire section, and a mention
of another Trial should not be allowed to make an active-Trial claim without
subject-level attribution.

### Preserve provenance as a chain

Every semantic review should link:

`source artifact -> parse revision -> canonical unit/fragment span -> bounded read view -> agent review -> disposition -> frozen Evidence claim -> answer/judgment`.

Store the classifier/reviewer identity, model/tool version, input context IDs,
decision, alternatives considered, and warning state. A later correction creates
a new classification/index revision and invalidates dependent Evidence rather
than editing a boolean in place. This follows the provenance shape of PROV-O
without requiring rob2-kit to adopt RDF.

## Proposed agent/MCP workflow changes

The existing two read tools and separate mutation boundary are a good base; the
semantic contract needs to become more explicit.

### Candidate discovery

`search_evidence` should accept a purpose such as `assessment`,
`contradiction`, `source_discovery`, or `context_review`. Ordinary assessment
search may rank likely conduct sections first, but it should return a structured
warning when reference/unknown/other-Trial candidates are present rather than
silently removing them. A source-discovery purpose may prioritize bibliography
and citation-like material and must state that returned text is not Evidence.

Search results should include an applied-scope summary, excluded count only for
policy/operational limits, candidate status, zone/discourse/applicability
signals, and a safe next action. Do not expose raw FTS syntax or make the agent
provide ranking weights.

### Context review

`read_evidence` should default to one intact unit and offer bounded neighbors or
section context. It should return fragment lineage, geometry, reading-order
confidence/limitation, surrounding headings, and whether a visual check is
available. It must never silently concatenate fragments into a citable quote.

### Semantic review and pruning before freeze

Add a typed review/disposition step—either a new tool or an expanded
`submit_domain_evidence` branch—that can record:

- exact candidate/unit/span identity;
- active/other/mixed/unknown subject attribution;
- current Result/other Result/unresolved Result;
- supporting/contradicting/contextual/out-of-scope/immaterial/duplicate/
  superseded/unresolved disposition;
- short agent rationale and the bounded context IDs used; and
- a visual-inspection request when text order or layout is material.

Pruning should happen before freeze, but “pruned” must mean an explicit
disposition, not omission from the agent's final prose. The freeze validator
should require every returned unique candidate to be dispositioned and every
retained candidate to resolve to an exact accepted span. A bibliography item
can therefore be reviewed and marked out of scope; it cannot disappear without
an audit record.

### Skill changes

Update `docs/EVIDENCE-SEARCH.md`, `docs/SIGNALING-QUESTIONS.md`, and
`skills/rob2-assess/SKILL.md` to teach:

- search visibility is not Evidence eligibility;
- zone/discourse labels are hints and warnings, not truth;
- read surrounding source-authored context before deciding subject or scope;
- bibliography/reference text is useful for source discovery but is normally
  not trial-conduct Evidence;
- mixed/uncertain attribution must be narrowed to an exact supported span or
  recorded as unresolved;
- agents must explicitly disposition candidates before freeze; and
- exact canonical text, not agent-authored quotation text, remains the source of
  the frozen quote.

The tool schemas should encode the finite dispositions and the distinction
between `candidate_visible`, `review_required`, and `accepted_citable`. MCP's
structured output and tool-execution-error mechanisms are suitable for this
contract; a generic “no passages found” response is not.

## Acceptance criteria

These criteria are intentionally design-level; they do not prescribe an
implementation in this research note.

### Recall and classification

- A permitted adversarial fixture with a non-standard references heading,
  mixed body/reference page, and another-Trial Discussion makes all relevant
  text candidates visible to the agent.
- A reference-only keyword cannot become Evidence merely by being returned by
  search; its explicit out-of-scope disposition remains visible.
- A paragraph containing both active-Trial and other-Trial statements can be
  narrowed to exact supported spans when geometry and text permit; otherwise it
  remains limited/unresolved.
- Unknown zone, unknown Trial subject, and unresolved Result applicability are
  warnings/review states, not silent disappearance and not automatic citable
  promotion.

### Canonical text and provenance

- Every accepted claim resolves to exact source-authored text, immutable source
  artifact, Parse revision, page/geometry or visual crop, canonical unit/fragment
  lineage, and the semantic review record that accepted it.
- Search projections, generated previews, agent rationales, and model labels are
  never accepted as quoted source text.
- Reclassification or parser reconstruction creates a new revision and makes
  affected Evidence/answers stale rather than mutating prior provenance.

### Freeze and readiness

- Freeze cannot complete while a potentially material candidate remains
  undispositioned or unresolved.
- Each non-`no_information` signaling-question answer has at least one frozen
  exact Evidence claim or a separately valid visual/transcription basis.
- `no_information` requires complete, readable, dispositioned search coverage;
  zero hits, hidden hits, or an exhausted heuristic ceiling alone do not suffice.
- An unresolved semantic/index condition produces a scoped diagnostic and no
  unsupported Domain/Overall judgment.

### MCP/agent usability

- The agent can perform assessment, contradiction, source-discovery, and
  context-review passes with structured purpose and scope in the tool result.
- Tool results expose bounded context, warnings, continuation, and typed next
  actions; they do not require raw FTS expressions or hidden policy knowledge.
- The clean-room CHAARTED PFS run no longer reports the same generic absence for
  every question: it either discovers and reviews candidates or reports a
  typed, scoped semantic/parse limitation.

### Evaluation

Compare the current and proposed contracts on the existing public dossier and
private `eval/` corpus, including non-standard headings, bibliography traps,
another-Trial passages, mixed paragraphs, multiple Results, protocol/SAP
supplements, tables with headers, two-column reading order, OCR noise, duplicate
reports, and stale revisions. Measure separately:

- relevant-passage recall;
- bibliography and other-Trial false-positive acceptance;
- active-Trial/Result attribution accuracy;
- exact-span/provenance validity;
- unresolved-material detection;
- no-information validity;
- unsupported answer/judgment rate;
- calls, tokens, and latency per accepted claim; and
- recovery after parser/index/classification revision.

Do not collapse these into one score. The desired result is higher discovery
recall with unchanged or lower unsupported-claim and provenance failure rates.

## Bottom line

The user's proposal is directionally right about discovery: a regex/keyword
blacklist should not decide what an intelligent assessor is allowed to inspect.
It is incomplete if interpreted as “remove all scientific gates and trust the
agent.” The robust boundary is **broad, provenance-rich discovery plus explicit
agent review and deterministic, fail-closed freeze**. That lets the agent see
the paragraph, understand whether a reference or another Trial is relevant, and
prune it before freeze—while preserving an auditable reason for every retained
or rejected candidate and preventing model interpretation from becoming an
unrecorded source claim.
