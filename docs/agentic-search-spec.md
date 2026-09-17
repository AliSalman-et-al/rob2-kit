# Make adaptive search and Cochrane-guided assessment reliable

Approved for publication, 17 September 2026.
Synthesized from the confirmed agentic-search design session and its two supplied
plans. This is a successor to the earlier accuracy-refinement work, not a request
to recreate capabilities already implemented.

## Problem Statement

A researcher needs defensible signaling answers for the exact approved Result.
The host can instead spend its effort satisfying search-receipt properties,
repeating report reads, or repairing delivery without resolving a scientific
premise. Lexical discovery can miss useful word forms, return overlapping
passages, or fail to reveal chronology in combined documents. Even successfully
retrieved Evidence can be interpreted inconsistently when the right Cochrane
guidance is absent from the decision context.

Verified workflow completion is not proof of scientific correctness. The supplied
audit describes selected traces and historical snapshots; it is not a complete
execution audit or evidence of measured gains from these proposals. Current
implementation and existing issue coverage must be checked before choosing a fix.

## Solution

Keep one host reasoning loop and a model-free server. Let unresolved premises
drive searching, reading, image inspection, and revision. Make search observations
accurate, Evidence recoverable, and question-specific Cochrane guidance available
where the model answers. The server validates structure, ownership, provenance,
activation, and deterministic judgments; the host decides scientific sufficiency.

Use Porter search with exact source-span recovery, a precise literal mode, and
small source-scoped spelling suggestions. Retain durable progress through
approval, compaction, and interruption. Measure retrieval correctness, scientific
support, completion, and cost separately, retaining regressions and uncertainty.

## User Stories

1. As a researcher, I want answers about my exact approved Result, so that retrieval improvements do not silently change the scientific target.
2. As an agent, I want to investigate an unresolved premise before the next legal write, so that workflow order does not dictate research order.
3. As an agent, I want a limitation to state what remains unknown and why I stopped, so that an exhausted search ranking is not mistaken for scientific sufficiency.
4. As a researcher, I want zero-hit receipts to describe only the executed query, so that a wording miss cannot establish factual absence.
5. As an agent, I want to search for D5 Evidence while D1 remains open, so that useful discoveries survive out-of-order investigation.
6. As an agent, I want optional search purpose distinct from Source scope, so that a passage can later support several questions.
7. As an agent, I want related English word forms to match, so that a query for concealment can recover concealed allocation text.
8. As an agent, I want every retrieved match mapped to its exact Source wording, so that broader matching does not manufacture quotations.
9. As an agent, I want literal wording search, so that I can distinguish stem collisions and inspect identifiers precisely.
10. As an agent, I want phrase and prefix semantics explained, so that I do not mistake stemmed matches for verbatim wording.
11. As an agent, I want source-scoped alternatives for misspelled unmatched words, so that I can recover terminology without an external dictionary.
12. As an agent, I want corrections to remain optional, so that the tool cannot silently change my query or the meaning of its receipt.
13. As an agent, I want phrase-adjacency failure distinguished from missing vocabulary, so that spelling advice addresses the observed problem.
14. As an agent, I want successful sibling batch results and independent cursors preserved, so that one large or failed search does not hide others.
15. As an agent, I want technical localization failure distinguished from no matches, so that an implementation error cannot become a scientific conclusion.
16. As an agent, I want exact displayed Evidence extents and expansion actions, so that clipped qualifiers remain recoverable.
17. As an agent, I want combined-document headings, dates, versions, and references tied to Source locations, so that I can investigate chronology accurately.
18. As an agent, I want overlapping windows reduced without merging different cohorts or document versions, so that concise results preserve scientific distinctions.
19. As an agent, I want complete question-specific Cochrane guidance beside the proposition and answer choices, so that I apply the rubric consistently.
20. As an agent, I want surrounding licensed official sections recoverable, so that an ambiguous case can be interpreted in its proper context.
21. As a researcher, I want official wording separated from project-authored examples and advice, so that operational guidance cannot impersonate Cochrane rules.
22. As an agent, I want conditional questions and their activation visible, so that a changed draft answer does not conceal a newly relevant branch.
23. As an agent, I want less repeated orientation with reliable continuation, so that context savings do not omit decisive guidance or Evidence.
24. As an agent, I want valid working notes reused after approval, so that unchanged Sources do not force duplicate report reading.
25. As an agent, I want meaningful investigative progress saved, so that an abrupt interruption loses as little useful work as possible.
26. As a researcher, I want compaction to continue the assessment, so that a context boundary does not become a scientific stopping condition.
27. As a researcher, I want usage-limit recovery to preserve approval and saved Domains, so that resumption starts from the newest valid durable state.
28. As an agent, I want stale notes identified after a Source or Result change, so that recovery does not reuse an invalid scientific basis.
29. As an agent, I want visible image-only methods text usable with honest provenance, so that extraction failure does not make available methods inaccessible.
30. As a researcher, I want visual uncertainty and conflicting extracted text retained, so that host observation is not misrepresented as machine verification.
31. As an agent, I want D3 observation, analysis, imputation, and follow-up facts distinguished, so that unknown reporting does not become known missingness.
32. As an agent, I want possible and likely outcome-dependent missingness treated separately, so that uncertainty at one question does not answer every later question.
33. As an agent, I want D5 plan content, chronology, and eligible alternatives assessed for the Result, so that a generic SAP mention or template date is not decisive by itself.
34. As an agent, I want actual grouping and exclusions assessed against the assignment-effect target, so that familiar safety-analysis terminology does not excuse a mismatched analysis.
35. As an agent, I want stable allocation facts reusable across unchanged comparisons, so that changing the outcome does not arbitrarily change D1.
36. As an agent, I want D4 awareness, susceptibility, and likely influence distinguished, so that both justified reassurance and genuine concern remain possible.
37. As an agent, I want concrete contradictions surfaced before Trial closure, so that new Evidence or corrected interpretation can revise the affected Domain.
38. As a maintainer, I want actual warm-search work measured, so that cache counters do not conceal repeated indexing or verification.
39. As a researcher, I want upgrades to preserve Sources, Evidence, approved Results, and judgments, so that a retrieval improvement cannot rewrite scientific history.
40. As an evaluator, I want retained attempts and source-to-answer attribution, so that apparent label improvement cannot conceal unsupported premises.
41. As an evaluator, I want free-search and decisive-Evidence comparisons, so that retrieval failures can be distinguished from persistent interpretation errors.
42. As a maintainer, I want real host-delivery and interrupted-recovery checks, so that passing server tests does not overstate what the model actually received.

## Implementation Decisions

1. Preserve the model-free server, one Proposal Review gate, approved Result,
   captured-Source boundary, deterministic official activation/mapping, and exact
   revision lineage. Do not change valid scientific rules to improve agreement.
2. Remove untruncated-ranking and zero-hit requirements as scientific limitation
   gates. Require an explicit unresolved premise and stopping rationale, with
   valid referenced Evidence and retrieval provenance where used. Keep source
   ownership, locator, delivery, and dependency checks. The server cannot certify
   semantic sufficiency or entailment.
3. Keep the next legal write visible as a workflow precondition, without making
   it the obligatory research action. Reads, searches, visual inspection, and
   working-note updates remain available during an open assessment.
4. Add optional Domain/question search purpose. Unassigned searches remain
   Trial-level discoveries. Never infer purpose from the first unfinished Domain;
   an initial purpose does not restrict subsequent scientific use.
5. Recover native FTS matches consistently across searchable representations and
   map them to authoritative Source coordinates. Treat unmappable matches as
   technical failures, not no-hit searches. Preserve query-unit semantics and
   safe application-owned query compilation.
6. Use one Porter-based FTS configuration throughout indexing, scoped search,
   recomputation, and verification. Keep scoped BM25 and deterministic ties.
   Identifier fields do not compete with document text. Phrase and prefix modes
   follow the indexed word forms and must be documented accordingly.
7. Add literal mode: case-insensitive contiguous wording under the existing
   presentation normalization, without stemming, numeric conversion, or fuzzy
   substitution. Enforce alphanumeric endpoint boundaries; scan the selected
   scope independently of Porter candidates. Use deterministic Source/page/offset
   ordering and no second unstemmed FTS index.
8. Build a disposable source-form catalogue bound to the selected Sources and
   projections. Use RapidFuzz OSA only to suggest eligible unmatched word forms.
   Start with the supplied plan's conservative English-word thresholds: no words
   shorter than five or longer than forty letters; one edit for lengths five to
   nine and two for ten to forty; exclude uppercase units, digits, and identifier
   punctuation. Disable assistance for literal and prefix modes. Calibrate these
   defaults on fixtures rather than claiming established scientific benefit.
9. Rank suggestions by edit distance, normalized distance, scoped page frequency,
   and lexical tie-break. Initially cap at three per unit and eight per result.
   Replace one specific query unit in an executable alternative while retaining
   mode and Source scope. Never execute corrections automatically, alter passage
   ranking, or conflate candidate-word frequency with replacement-query results.
   Report bounded or unavailable feedback as unknown rather than zero.
10. Budget complete responses, including advice and continuation. Preserve
    Evidence identity, exact displayed extents, independent batch outcomes, and
    recovery actions before optional suggestion metadata. Retain existing batch
    limits and oversized-passage recovery.
11. Expose source-located headings, contents entries, explicit version/date
    statements, and cross-references through existing navigation. The host
    determines chronology and applicability. Deduplicate overlapping windows at
    the same location conservatively; preserve different versions, cohorts, and
    locations unless equivalence is established.
12. Automatically expose complete applicable per-question official excerpts,
    wording, permitted answers, activation, and operational guidance, including
    conditional questions. Preserve pack identity and exact official locators.
    Make surrounding licensed official sections recoverable through a bounded
    existing context/resource boundary. Do not add another workflow tool solely
    for guidance or replace official text with generated summaries.
13. Reduce repeated orientation and unrelated context while keeping required
    scientific material recoverable. Guidance presence, comprehension, and correct
    application are distinct; delivery checks cannot certify the latter two.
    Evaluate compact views for missed qualifications and answer regressions.
14. Reuse valid source-bound notes across unchanged approval and remove the
    conflicting validation requirement for a duplicate postapproval report pass.
    Recover the exact approved Result, newest canonical progress, pending
    questions, and needed Evidence. Source or Result mismatch requires truthful
    reorientation or relevance reassessment.
15. Save working notes after meaningful progress and before anticipated delay or
    compaction, without a save-after-every-call rule. Compaction continues the
    task. A hard usage interruption resumes when execution is available from
    what actually persisted. Do not rely on a final tool call at exhaustion or on
    conversational summaries retaining every passage. Neither event selects a
    scientific answer or establishes absence.
16. Permit literal host-observed methods transcription from delivered images.
    Preserve Source/page/region/render identity, honest visual provenance,
    uncertainty, and conflicting text across validation and independent export
    verification. Do not relabel transcription as machine-verified text.
17. Reuse existing missing-data structures and question cards. Improve D3
    observation and follow-up distinctions; D5 applicable plans and chronology;
    assignment-effect AE analysis; D1 allocation-fact consistency; and D4 actual
    measurement circumstances. Pair every substantive guidance change with a
    demonstrated mechanism and balanced fictional contrasts. No trial-name or
    host-model-specific scientific rules.
18. Use the existing preclosure Trial review to expose concrete contradictions,
    denominator ambiguity, unresolved accessible routes, and unsupported
    inferences. Record whether revisions reflect new Evidence, corrected
    interpretation, or mechanical repair. Do not add a universal second assessor
    or mandatory full reassessment.
19. Version retrieval semantics independently of scientific-pack and projection
    identities. Rebuild derivatives atomically, reject obsolete cursors clearly,
    and preserve historical receipt semantics. Preserve active work through
    lossless conversions; otherwise require an explicit fresh supported workspace
    while retaining the old workspace. Do not silently reinterpret state.
20. Reuse verified immutable retrieval snapshots with bounded, scope-sensitive
    caches. Measure bytes hashed, projection reads, index construction, candidate
    reconstruction, database work, response bytes, and latency. Preserve source
    integrity; an mtime or checksum stored beside editable derivatives is not
    independent verification.
21. Preserve archived attempts and references. Attribute the earliest demonstrated
    source-to-answer failure, retain unresolved attribution when evidence is
    insufficient, and inspect selected agreements as well as disagreements.
    Compare free search with supplied decisive passages without supplying answers.
22. Freeze candidate, pack, skill, contract, Sources, registry capture, host/model
    settings, prompts, selection convention, retry policy, scorer, and evaluation
    budget. Retain every draw. Distinguish defensibility from provisional label
    agreement, and report improvements alongside regressions without a
    zero-regression rule or guaranteed percentage gain.

## Testing Decisions

- Primary seam: the existing public MCP/application workflow, exercised through
  real caller operations from Source intake to search/read/render, validation,
  save, recovery, review, and verified export. Prefer observable behavior over
  assertions about private helpers or call counts without a performance claim.
- Use targeted SQLite oracle checks only where native lexical semantics and
  exact localization need independent verification. Use projection reconstruction
  and the independent artifact verifier separately for Evidence integrity.
- Reuse existing bounded-context, result-delivery, search-ranking/cache,
  working-checkpoint, read-first, visual-delivery, and evaluation test patterns.
  No new general testing framework or test-only production API is needed.
- For recovery, interrupt between durable operations and reopen the same
  workspace. Verify approval, saved Domains, current notes, stale-note handling,
  and exact next recovery actions. Simulate compaction as loss of conversational
  context; do not claim a host compaction event was observed when it was not.
- Check actual installed-host visibility of text, guidance, images, tool schemas,
  and continuation. Record host/version details and unrun or unobservable checks
  explicitly. Server response construction alone does not establish delivery.
- Scientific cases must use normal discovery and answer submission. Include
  premise-changing pairs, invariant paraphrases, distractors, counterevidence,
  unknown reporting, genuine High controls, and justified reassurance. Supplying
  answers to a deterministic evaluator tests mappings, not host interpretation.
- Separate component correctness, complete useful Evidence recovery, answer
  support, class recall, both disagreement directions, scope corrections,
  completion, infrastructure failures, latency, context, and cost. Cluster cohort
  uncertainty by Trial. A cohort without reference High labels cannot estimate
  High sensitivity; report separate controls honestly.
- Predeclare a small Porter-only versus Porter-plus-suggestions comparison and
  focused context/guidance comparisons before a larger cohort wave. Use the
  existing evaluation harness and retain failures and inconclusive outcomes.
- Each implementation ticket carries the relevant public contract, installed
  guidance, persistence, and verifier checks. The final frozen qualification
  consumes completed feature slices; independent slices do not inherit arbitrary
  ordering or shared-file scheduling as product dependencies.

## Out of Scope

- A second reasoning model, embeddings, general retrieval framework, external
  spelling dictionary, fuzzy passage reranker, or new scientific approval gate.
- Automatic query correction, automatic scientific inference from filenames or
  dates, server-side semantic sufficiency scoring, or required search counts.
- Changing Source projections or canonical scientific records merely to upgrade
  retrieval, rewriting archived attempts, or relabeling references to favor the
  candidate.
- Trial-specific rules, model-specific scientific answers, changing a valid
  Cochrane mapping to reduce concerning judgments, or promising an accuracy gain.
- New document acquisition outside the approved Source boundary, indiscriminate
  OCR, or a claim that host visual interpretation is machine-verified.
- Unbounded evaluation spending, automatic purchase/reset of usage, or a promise
  that execution can continue while the host enforces a hard usage limit.

## Further Notes

- The accepted design covers all fixes and enhancements in the two supplied
  plans, with compaction treated as continuation and question-specific Cochrane
  guidance protected. Engineering defaults remain subject to observable tests.
- Preserve prior decisions on autonomous scientific review, the overall judgment
  policy, and balanced regression assessment. Existing issue closure is not proof
  that every newly specified behavior works; reproduce a remaining gap before
  changing completed functionality.
- The earlier [accuracy refinement specification](https://github.com/AliSalman-et-al/rob2-kit/issues/365)
  and [adaptive overhaul](https://github.com/AliSalman-et-al/rob2-kit/issues/349)
  provide lineage. New tickets must describe their incremental deliverable and
  reference overlapping work without silently closing or modifying old issues.
- Baseline inspected for this handoff: commit
  `ac9a3b30f8edf7b7037edf2f5d9c722d28f4280c`, plus session documentation edits.
  The Porter input plan cites a different historical snapshot; its code claims
  require verification against the implementation checkout.
- This document is a specification, not a claim of implemented behavior or
  completed host/scientific qualification.
