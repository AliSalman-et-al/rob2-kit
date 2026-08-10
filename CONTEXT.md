# RoB 2 Assessment

This context describes the evidence-grounded assessment of bias in a specific randomized-trial Result and its transparent static report.

## Language

**Outcome target**:
A project-level description of the clinical concept, admissibility rule, and time policy that researchers intend to assess across trials. It may unify differently worded outcome labels only when source context supports conceptual equivalence. Related but non-identical operational definitions are construct variants rather than synonyms and may share a broader Outcome target only when its explicit human-approved admissibility rule includes them; otherwise they remain separate targets. Every mapped Result retains its original wording, definition, measurement, analysis, and time-point details. An explicit requested time point or window constrains candidate mapping. When the request omits one, the proposed policy defaults to each Trial's protocol-defined primary analysis or prespecified primary cutoff, while competing landmarks or updated analyses remain visible when they could change the selected Result. It guides batching and discovery but is not itself an assessment identity.
_Avoid_: Outcome specification, assessment outcome

**Result**:
The stable, trial-specific intervention-effect analysis to which one RoB 2 assessment applies. Its identity includes the Trial, Randomization, Comparison, effect of interest, outcome definition, measurement, time point or cutoff, analysis choices, and effect measure, but not the extracted numerical value or every document that reports it. Multiple Source locators may corroborate or conflict about one Result, with one result-bearing locator serving as its proposal anchor. A materially updated cutoff, population, analysis set, or outcome definition is a distinct Result candidate rather than a duplicate report.
_Avoid_: Paper assessment, study-level risk of bias

**ResultSpec revision**:
An immutable resolved description of a Result at a point in time, including its numerical values, denominators, locators, provenance, actor, and observation time. Within one Project ledger, its entity and revision identities bind exactly one canonical byte sequence: changing any bound content, including observing the same declaration at a different time, creates a new revision and invalidates dependent judgments and signatures without changing the Result’s identity.
_Avoid_: Result, outcome target

**Trial**:
The underlying randomized experiment, independent of any particular publication, folder, acronym, or registry record. External identifiers and multiple reports may refer to the same Trial only when corroborating identifiers and design facts support the linkage; an acronym, title, folder, isolated citation, or bibliography relationship is insufficient. Materials that may instead describe another Trial, substudy, extension, follow-up cohort, or separate Randomization remain unresolved rather than being merged. Evidence and Result identity never transfer between Trials merely because one report mentions or compares the other.
_Avoid_: Paper, report, study folder

**Randomization**:
A distinct random allocation process within a Trial. It is the boundary within which randomization evidence may be considered for reuse.
_Avoid_: Trial arm, comparison

**Comparison**:
The ordered experimental and comparator Arms selected from one Randomization for a Result. It identifies the intervention contrast being assessed.
_Avoid_: Trial, intervention pair

**Evidence candidate**:
A potentially relevant retrieval result that has not yet been accepted as support for an assessment claim. It may resolve to a Canonical evidence unit or an Evidence fragment candidate and carries source provenance, source-preserving structural metadata, warnings, and bounded navigation actions; it cannot be cited by a signaling-question answer, and parser output carries no Trial, Result, Domain, or signaling-question meaning.
_Avoid_: Evidence, verified quote

**Evidence candidate duplication**:
The attributable relationship between a candidate and the retained candidate or reviewed span it repeats. Lineage duplicates share underlying source fragments and collapse to one candidate; repetitions within one Source remain visibly linked and cannot double-count; independently located cross-Source text remains distinct unless review establishes that it is merely a reproduced copy.
_Avoid_: Text similarity, silent deduplication

**Evidence fragment candidate**:
A source-preserving parser fragment or fragment group whose coherent reading order or unit boundary has not been established deterministically. It remains searchable and readable with exact lineage and warnings, but cannot ground an Evidence claim unless deterministic canonicalization succeeds or Visual review produces a qualifying transcription.
_Avoid_: Canonical evidence unit, synthetic paragraph

**Evidence candidate disposition**:
The attributable semantic review record for one retained Evidence candidate, combining exact-span Trial attributions and decisions classified as supporting, contradicting, contextual, out of scope, immaterial, superseded, duplicate, or unresolved and bound to a Result, signaling-question scope, rationale, and at least one Evidence read view containing the span and reviewer-chosen context. Retaining a candidate makes it potentially material until every identified relevant span has a terminal disposition or is explicitly unresolved; search previews alone cannot support substantive review.
_Avoid_: Silent exclusion, answer-driven selection

**Evidence span Trial attribution**:
The reviewer's attributable classification of an exact span's relationship to the assessment Trial: active, other, not explicit, or unresolved. Only a span attributed as active may support or contradict the active Result. A span whose subject is not explicit may become active only through a rationale bound to issued surrounding-context views; a candidate that mixes Trials must be divided into exact attributable spans or remain unresolved.
_Avoid_: Evidence candidate Trial attribution, Trial discourse scope, agent confidence

**Evidence review revision**:
An immutable candidate-level semantic review aggregating independently identified exact-span decisions and their resolved Reviewed evidence contexts, superseding rather than modifying an earlier review. Each reviewed span has a stable identity within the revision. Changing attribution, span bounds, disposition, rationale, or considered context invalidates dependent Evidence claims, Evidence Bundles, and downstream assessment and verification artifacts.
_Avoid_: Mutable disposition, review edit

**Evidence contract revision**:
The versioned canonicalization, retrieval, review, and policy identities under which evidence work is interpreted and reproduced. Historical runs retain their original revisions read-only; the new contract has no semantic-eligibility override parameters, and explicit reprocessing creates new Parse, canonical, index, and review dependencies rather than reinterpreting old records in place.
_Avoid_: In-place migration, compatibility guess

**Evidence review submission**:
An attributable, idempotent, append-only batch that durably records Search-result dispositions, candidate and span review revisions, rationales, considered Evidence read views, and duplicate relationships throughout evidence work. It is separate from repeatable read-only search and reading; the later Domain freeze validates and closes accumulated review into immutable question-specific Evidence Bundles rather than receiving its first and only copy.
_Avoid_: Search side effect, chat-memory shortlist, mutable bundle

**Canonical evidence unit**:
The smallest coherently reconstructed, page-bound source-authored unit that may ground an Evidence claim, identified deterministically from artifact, Parse, page, source bounds, fragment lineage, and canonicalization revision rather than ordinal position or normalized text. Fragments merge only when order, column geometry, and structural role are unambiguous, with complete fragment-to-canonical character mapping; cross-page continuity links separate units and ambiguous material remains an Evidence fragment candidate.
_Avoid_: Generated chunk, search aggregate

**Evidence location handle**:
An opaque engine-issued navigation reference to one Canonical evidence unit or Evidence fragment candidate, bound to its Source artifact, Parse revision, location kind, fragment lineage, and canonicalization revision. It is reusable within that snapshot and becomes explicitly stale when any bound source or canonicalization identity changes, while index-only ranking changes do not invalidate it. It is submission-only and is resolved into Reviewed evidence context before a semantic review freezes.
_Avoid_: Unit ID, source path, search cursor

**Search projection**:
A versioned, non-citable retrieval representation derived from Canonical evidence units or independently indexed source fragments. Related uncertain fragments may be grouped as one candidate but remain separate in previews without an implied reading order; generated neighbor terms, normalization, headings, or aliases may aid ranking but never become displayed source prose, an Evidence claim, or a quoted Source phrase.
_Avoid_: Evidence candidate, source quotation, citable chunk

**Evidence read view**:
A bounded, non-authoritative presentation that dereferences one Evidence location handle and, when explicitly requested, expands by neighbors, section, line or character window, page, or render. Requests express desired extent while versioned Evidence-search policy applies maximum units, characters, pages, and render size; responses declare applied bounds, size, omissions, and stable continuation, including character or line continuation for oversized units. Uncertain material remains separate source fragments rather than concatenated prose; semantic boundaries may be crossed with warnings, but Source, Parse revision, and requested page scope are never crossed silently.
_Avoid_: New search, full document dump, flat block adjacency

**Reviewed evidence context**:
The immutable descriptor created when the engine resolves an Evidence read view used for semantic review, binding its snapshot identity, Canonical evidence unit or source-fragment references, displayed bounds, and displayed-text hashes. It records exactly what informed the reviewer without making surrounding context citable Evidence or preserving a stale navigation token as provenance.
_Avoid_: Evidence location handle, Evidence claim, chat context

**Visual-review condition**:
An unresolved requirement attached to a retained Evidence candidate or exact span whose meaning or provenance cannot yet be established from canonical text. It closes only through a reviewed Visual transcription, successful deterministic re-canonicalization, or an attributable substantive rejection after sufficient visual context, and blocks freeze while potentially material.
_Avoid_: Needs-visual-review disposition, terminal rejection

**Evidence result page**:
A snapshot-bound, policy-bounded page of unique Evidence candidates constrained by both candidate count and estimated model tokens. Within mechanically authorized Source and Parse scope, lineage duplicates collapse and deterministic ordering is diversified across Sources and Source roles so one document or copy cluster cannot monopolize the page; parser-inferred scientific scope neither filters nor ranks candidates. Truncation declares omissions and an exact continuation action, while numeric limits belong to the versioned Evidence-search policy and are calibrated by evaluation rather than treated as scientific constants.
_Avoid_: Unbounded results, rank cutoff as evidence, agent-chosen raw character budget

**Evidence retrieval condition**:
An expected structured outcome such as zero hits, excluded-zone-only hits, truncation, stale or wrong-scope identity, structural boundary, or unreadable canonical content. It reports applied scientific scope, exclusions or limitations, and one or two safe next actions without silently broadening scope or masquerading as an internal error; invalid arguments identify the failed field and a corrected-call shape.
_Avoid_: Generic tool failure, automatic scope expansion, free-text retry advice

**Visual citation**:
A deterministic report view binding an Evidence claim's exact Canonical evidence unit span to the source page render and one or more highlight boxes. It exposes provenance for human audit without implying that an agent inspected the image or creating a separate evidence item.
_Avoid_: Visual candidate, Visual transcription, screenshot evidence

**Evidence claim**:
An immutable, typed assertion linked to an exact reviewed span selected from a Canonical evidence unit and its source provenance, or to a qualifying Visual transcription. A textual claim directly depends on the content-bound Evidence review revision and stable reviewed-span identity that authorized it. Deterministic code materializes canonical quoted text and validates mechanical provenance, bounds, custody, authorization, review completeness, and dependency revisions rather than accepting agent-authored quotation text or classifier labels as semantic authority.
_Avoid_: Retrieval hit, evidence snippet

**Derived fact**:
An immutable value produced by a named, deterministic RoB 2-relevant derivation from typed Evidence claims, with explicit population, arm, analysis set, outcome, time point, units, formula, and rounding provenance. It inherits uncertainty and review requirements from its inputs and is never a model-authored calculation.
_Avoid_: Narrative calculation, general statistical analysis

**Evidence Bundle**:
The immutable, content-hashed, question-specific set of accepted supporting and contradicting Evidence claims, their authorizing review revisions, derived facts, Visual transcriptions, Search coverage receipts, and declared limitations frozen before a signaling-question answer is made. Reviews or reviewed spans outside that signaling question are excluded. Discovering or correcting evidence requires a new bundle revision rather than changing an existing bundle or silently extending it during answering.
_Avoid_: Context window, search results

**Evidence consideration manifest**:
The complete account of how every accepted item in an Evidence Bundle was considered for one signaling-question answer, including whether it was supporting, contradicting, contextual, duplicate, or unresolved and which bounded Context view exposed it. It permits a large bundle to be traversed through successive reproducible views without treating a context-window limit or conversation compaction as an evidence limit.
_Avoid_: Context summary, model memory

**Search coverage receipt**:
An immutable account of the versioned minimum search protocol performed for one signaling question, including the exact ResultSpec, Source inventory, Parses, index, Guidance, rules, and Evidence search policy used; required passes; Source roles and visual regions covered or unavailable; queries, every traversed page and unique returned candidate's lightweight disposition, retained-candidate reviews, conflicts, stopping reason, and operational limits. It establishes procedural search adequacy rather than proving absence; untraversed continuations are incomplete coverage, while truncation, zero hits, or an exhausted ceiling alone cannot establish a No-information basis.
_Avoid_: Search confidence, retrieval log

**Search query**:
A structured, attributable expression of a plain-language evidence need with optional exact phrases or lexical terms, search purpose, and Source or page refinements. One generalized search/read contract serves all purposes; purpose selects protocol obligations, ranking, diversification, and coverage accounting but never visibility, while Source, Trial, registry, and Result discovery or revision remain outside evidence navigation.
_Avoid_: Raw FTS expression, prompt

**Search result disposition**:
The attributable lightweight classification of each unique Evidence candidate actually returned on traversed Search-result pages as irrelevant, retained, or duplicate. Irrelevant requires a compact reason code and may include a short rationale; duplicate requires a retained-candidate target, while ambiguity requires retention and an Evidence read view rather than preview-only pruning.
_Avoid_: Rank cutoff, implicit omission

**Trial orientation pack**:
A bounded summary that orients an assessor to one Trial preparation through its ResultSpec, Source inventory, coverage limitations, document outlines, registry projection, and applicable pack and policy identities. It points to complete searchable sources rather than attempting to reproduce the full dossier.
_Avoid_: Full-text context, trial dossier

**Discovery candidate**:
A proposed but unconfirmed identity for a Source's role, a Trial's Result, or a Trial's registry record, produced by a bounded heuristic (folder or filename cues, lexical or identifier-shape matches) and carrying its originating cue, source location, parser or revision identity, and stated uncertainty. It ranks and explains itself but never binds identity by itself, including when it is the only candidate found; an attributable disposition is what establishes or excludes it.
_Avoid_: Auto-classification, inferred identity, sole-match binding

**Discovery candidate disposition**:
The outcome recognized for one Discovery candidate: accepted, rejected, superseded by a different accepted candidate in the same slot, or left unresolved. Accepted and rejected are attributable, explicitly recorded reviews; superseded is derived, never separately recorded — a candidate whose slot holds a different accepted candidate is superseded by that fact alone, so only one explicit review establishes both outcomes at once. It is distinct from an Evidence candidate disposition, which judges a span's relevance to a signaling-question answer rather than a Source's, Trial's, or registry record's identity.
_Avoid_: Evidence candidate disposition, auto-accept, cardinality default, stored superseded flag

**Result candidate**:
A Discovery candidate proposing that one ResultSpec-shaped analysis in a Trial's Sources satisfies a requested Outcome target, produced by matching outcome construct, time point, effect measure, or instrument wording. A Trial with exactly one Result candidate for a target is not automatically citable for it; its disposition still requires recorded review.
_Avoid_: Auto-selected Result, sole-candidate binding

**Registry candidate**:
A Discovery candidate proposing that a specific registry record (for example a ClinicalTrials.gov NCT number) identifies a Trial, produced by an identifier-shaped match or declared text. An unrecognized or non-standard identifier remains a visible, reviewable candidate rather than being silently dropped for not matching an expected shape.
_Avoid_: Auto-linked registry record, NCT inference

**Source-role candidate**:
A Discovery candidate proposing one or more Source roles from folder position, filename cues, or an explicit Trial declaration. Until it is accepted, dependent decisions — a Result's required-Source check, which protocol or SAP a proposal shows as preferred, and a Source's computed criticality — must not treat the cue as settled.
_Avoid_: Auto-classified role, forced label

**Trial discovery record**:
The pre-confirmation view of one proposed Trial's identity candidates — its Source-role, Result, and Registry candidates — together with relevant document sections, coherent supporting passages, conflicts, and unresolved alternatives, bound to the exact Source artifacts and Parse records inspected. It is not a separate persisted type: no consumer needs one candidate's disposition history independent of the others, so it is the same whole-snapshot Run proposal that already carries this content, superseded atomically as one revision rather than accruing independent per-candidate history. It lets an agent form and resume a robust Run proposal without treating its prose summary or context window as authority.
_Avoid_: Agent memory, Trial orientation pack, Evidence Bundle, full dossier, standalone revision-tracked record

**Domain context pack**:
The bounded, reproducible starting view for one Domain assessment work item, containing its Trial, Result, and Domain identity; applicable signaling questions, exact decision need, guidance, and Project rules; accepted supporting, contradicting, and contextual Evidence claims grouped by question and Source chronology; relevant unresolved candidates; Source, search, and parse limitations; and the next permitted action. It points to bounded retrieval capabilities and successive Context view manifests rather than reproducing a complete Evidence Bundle or source dossier.
_Avoid_: Evidence Bundle, entire source document, SQ context pack

**Context view manifest**:
The host-neutral, ordered account of the exact domain items, revisions, pagination state, selection reasons, and deterministic transformations used to render one Trial orientation pack or Domain context pack. Host-specific payloads bind back to this manifest without claiming access to hidden provider prompts or reasoning.
_Avoid_: Full prompt log, model context

**SQ Answer revision**:
An immutable signaling-question answer and rationale bound to a specific Evidence Bundle, guidance and logic versions, decision rules, and author. Corrections create a new revision, while branch-inactive questions are marked not applicable by the logic rather than answered by an assessor.
_Avoid_: Mutable answer, model judgment

**SQ answer category**:
One of the five canonical assessor-selectable answers: Yes, Probably yes, Probably no, No, or No information. Not applicable is a branch state assigned by the Logic pack rather than an answer category.
_Avoid_: Not applicable answer, localized stored value

**No-information basis**:
The completed Search coverage receipts showing that every required pass reached its deterministic stopping condition, every returned candidate was dispositioned, every retained candidate was substantively reviewed, all potentially material unresolved or Visual-review conditions were closed, and required Sources and regions were readable and covered. Explicitly rejected bibliography or other-Trial material may contribute reviewed coverage, while missing, unreadable, unsearched, truncated, or policy-limited material produces a limitation or diagnostic outcome rather than establishing this basis.
_Avoid_: No search hit, tool failure

**Terminal evidence checkpoint**:
The deterministic publication gate that recomputes the active signaling questions from the latest committed answers and bound Logic pack, then requires each to have either a frozen, question-scoped supporting or contradicting Evidence claim, a qualifying Visual transcription with one of those roles, or an engine-verified complete No-information basis. Contextual items, Derived facts without their underlying claims, receipts, and limitation strings do not independently satisfy the gate; any unsupported active answer makes the Result diagnostic-ready without Domain or Overall judgments, while inactive questions and evidence-backed disclosed limitations do not block publication.
_Avoid_: Bundle-exists check, limitation-string check, report-time guess

**Evidence insufficiency reason**:
A stable typed explanation for why an active signaling-question answer failed evidence validation, paired with human-readable scoped details. It distinguishes missing qualifying Evidence, an invalid No-information basis, a stale Evidence dependency, and Evidence that cannot be deterministically resolved into its claimed source content; failure to render an otherwise valid report asset is not Evidence insufficiency.
_Avoid_: Free-text limitation, report-rendering error, hidden validation failure

**Logic element ID**:
The permanent semantic identity of a signaling question, branch, rule, judgment table, or required assessor input. Changes to wording or display labels preserve the identity, while changes to meaning, applicability, or decision behavior require a new identity.
_Avoid_: Official question number, wording-derived ID

**Logic pack**:
An immutable normative definition of one supported RoB 2 instrument edition, trial design, and effect of interest. It contains logic-element identities, allowed answers, applicability, branching, and deterministic judgment rules, but not official explanatory wording.
_Avoid_: Guidance pack, prompt instructions

**Guidance pack**:
An immutable interpretive companion containing authorized question wording, elaborations, citations, display labels, translations, and links to Logic elements. It may clarify their presentation but cannot change applicability, branching, or judgment behavior.
_Avoid_: Logic pack, hidden decision rules

**Pack release**:
An immutable release of a Logic pack or Guidance pack identified by its stable family, human-readable release label, and content hash. Compatibility with another pack is declared explicitly rather than inferred from version numbering.
_Avoid_: Latest pack, mutable rule set

**Conformance suite**:
The immutable, independently derived set of exhaustive valid paths, invalid inputs, expected judgments, decision traces, and representative golden cases that a Logic-pack release must pass. It is reviewed against the official instrument and bound to the exact Logic-pack release it validates.
_Avoid_: Unit-test examples, engine-generated oracle

**Algorithmic judgment revision**:
A reproducible proposed Domain or overall RoB 2 judgment derived from an exact answer set, any required Overall judgment policy input, and Logic-pack version. Its Decision trace explains the branch taken. It remains preserved even when the assessor selects a different Final judgment with justification.
_Avoid_: Final judgment, assessor judgment, hidden recommendation

**Decision trace**:
The deterministic, structured explanation of a Logic-pack evaluation, identifying its exact inputs, active and inactive questions, evaluated and matched rules, and resulting judgments. It records reproducible rule execution rather than hidden model reasoning.
_Avoid_: Chain of thought, narrative rationale

**Overall judgment policy**:
The deterministic roll-up in which all Low Domain judgments produce Low overall, any High Domain judgment produces High overall, and multiple Some-concerns Domains require a versioned assessor input stating whether the concerns together substantially lower confidence in the Result. A Yes input produces High overall; otherwise the overall judgment is Some concerns. The policy uses no numeric Domain-count heuristic.
_Avoid_: Fixed maximum-domain roll-up, model roll-up, numeric escalation threshold

**Final judgment**:
The assessor-attributed Domain or overall judgment for an Assessment revision. It normally accepts the Algorithmic judgment revision; a departure requires an explicit alternative, a material-bias rationale, and cited Evidence, while preserving the proposed judgment and Decision trace. Published Final judgments are immutable; corrections create a new Assessment revision rather than editing or overriding the report in place.
_Avoid_: Proposed judgment, mutable judgment, in-report override

**Source descriptor**:
The identity and expected roles of an obtained, missing, or discovered information source, including relevant dates and external identifiers. A role is the accepted disposition of that source's Source-role candidate, not a forced label, and the descriptor can exist even when no content was acquired.
_Avoid_: PDF, source file

**Source–Trial association**:
An attributable relationship stating why a Source or Source component pertains to a Trial and what role it may play. One Source may have separately justified associations with multiple Trials, but an association permits scoped inspection rather than making every passage Evidence for each Trial. Bibliography entries, background discussion, and descriptions of another Trial do not create an association or transfer Evidence; an uncertain association remains excluded from proposal and assessment support until resolved.
_Avoid_: Folder membership, whole-document evidence, citation-based linkage

**Retrieval classification correction**:
An attributable revision correcting a Canonical evidence unit's document zone, hierarchy, or reading-order classification after diagnostic inspection. Correction updates the applicable Parse/index lineage and returns structurally misclassified material to ordinary scoped retrieval without an “ignore warning” override.
_Avoid_: Filter bypass, agent-confidence override, silent reclassification

**Source criticality**:
The consequence of a source’s unavailability for a particular Result preparation: required sources must be acquired and sufficiently readable, expected sources receive a bounded acquisition attempt, and optional sources are used when available. Criticality is contextual and distinct from source role or authority, and it is derived from a Source-role candidate's accepted disposition, recomputed whenever that disposition changes rather than fixed at ingestion.
_Avoid_: Source role, global evidence ranking

**Result-bearing full-text report**:
A user-provided, sufficiently readable first-hand full-text Source that contains the selected Result and enough contextual information to establish its semantic identity. Each included Trial-specific Result requires at least one such report before Run definition confirmation; one report may support multiple Results, and supported full-text formats are not limited to PDF. Abstracts, registry records, citations, slide decks, and automatically discovered web records cannot satisfy this requirement. Protocols, SAPs, supplements, registry histories, and additional reports remain optional inputs unless a later Result preparation establishes a more specific criticality.
_Avoid_: Abstract-only inclusion, registry-only Result, mandatory complete dossier

**Source conflict**:
Two or more acquired source statements that materially disagree about the same event, population, analysis, outcome, or time point after accounting for chronology and amendments. Each statement remains separately attributable; resolution requires an explicit methodological or chronological basis rather than a universal source hierarchy.
_Avoid_: Any source difference, automatic precedence

**Acquisition receipt**:
An immutable record of one attempt to obtain a Source, including its method, origin, time, actor, declared metadata, outcome, and any failure category. Multiple receipts may point to the same content-hashed Source artifact without losing where each copy came from.
_Avoid_: Download log, Source artifact

**Recovery policy**:
The versioned project policy that classifies failures, bounds safe acquisition and processing retries, permits adapters, defines terminal failure categories, and states when changed input may be attempted again. Transient failures may receive a small recorded automatic retry allowance; deterministic validation, stale-work, unsupported-input, and integrity failures are never retried unchanged. Repeated structured rejection requires the stated recovery action rather than blind agent regeneration, and exhausted retries pause or terminate only the affected scope without looping indefinitely.
_Avoid_: Infinite retry, ad hoc fallback

**Source artifact**:
Immutable acquired source content identified by its content hash. Parsing, OCR, or replacement produces related artifacts or events without changing the original.
_Avoid_: Source descriptor, mutable document

**Source component**:
A coarse, optional page-range annotation for a logically distinct part of a Source artifact, such as a protocol or SAP appended within one PDF. It carries its own roles and classification provenance but is never required for the parent artifact to be searched or cited.
_Avoid_: Separate file, copied document

**Parse record**:
An immutable account of one transformation of a Source artifact into canonical document content, bound to the artifact hash, parser and configuration versions, output hashes, and quality observations. Initial extraction and recovery attempts remain distinct records.
_Avoid_: Current parse, Source artifact

**Parser-quality policy**:
The versioned mapping from parser observations and decision relevance to page Coverage-map states and bounded recovery actions. LiteParse reason codes remain observations rather than confidence scores or standalone OCR, failure, or visual-inspection gates.
_Avoid_: Parser confidence, OCR-all fallback, document quality score

**Coverage map**:
The page- and component-level account of what was read reliably, requires visual inspection or recovery, remains limited, or is intentionally blank. Aggregate source quality is derived from this map rather than represented by one opaque confidence score.
_Avoid_: Parser confidence, pass/fail document

**Source inventory revision**:
An immutable snapshot of Source availability, processing coverage, and assessment use for a Result preparation. It distinguishes information absent from adequately searched readable sources from sources not obtained, not processed, or not completely searched.
_Avoid_: Input folder, bibliography

**Source conflict**:
Two or more Evidence claims that cannot all describe the same relevant event, population, analysis, outcome, or time point after accounting for chronology and amendments. Each account remains preserved; resolution requires an explicit methodological or chronological basis, and an unresolved material conflict prevents a complete assessment and overall judgment for the affected Result.
_Avoid_: Any wording difference, automatic source precedence

**Assessment revision**:
The immutable, schema-versioned source of truth for one Result assessment, binding all exact input, evidence, answer, deterministic judgment, pack, policy, and provenance revisions. Reports and exports are derived views, while a portable archive materializes every referenced artifact needed for independent verification.
_Avoid_: Current assessment, report

**Dependency invalidation**:
The derived loss of current usability when an exact dependency of a revision changes, propagated only through its explicit dependency relationships. Invalidated revisions remain immutable and auditable, while each affected Result resumes from its earliest stale checkpoint and unrelated Results or Domains remain complete.
_Avoid_: Deletion, blanket rerun, mutable stale flag

**Actor**:
The attributable human, agent run, or deterministic system component responsible for an authored or derived revision. Actor provenance states only identity and version information the host can actually establish.
_Avoid_: User, model

**Harness**:
A supported agent host, initially Codex or Claude Code, that invokes rob2-kit skills and MCP tools while presenting progress and required run-control choices in its own conversation. It is an orchestration client; authoritative assessment and resume state remains in rob2-kit.
_Avoid_: Companion workspace, web client, workflow engine

**Locked runtime**:
The default Harness installation mode, in which a project keeps its own `.rob2/runtime` copy of the released wheel and environment, content-verified against the installed release's pin at bootstrap and doctor time. Undeclared wiring that does not match this shape is a configuration failure, not an alternative mode.
_Avoid_: Bundled runtime, pinned install

**Unlocked runtime**:
An explicitly declared alternative Harness installation mode in which a project's configuration wires directly to the shared release runtime instead of keeping a project-local `.rob2/runtime` copy. It is created only through its own bootstrap mode, recorded once in the project's lock state, and verified against the shared release runtime's own self-consistency rather than a project-local copy. Wiring that resembles this shape without the recorded declaration remains a Run integrity failure rather than a tolerated third state.
_Avoid_: Bypassed runtime, dev mode, misconfigured wiring

**Evidence search policy**:
The versioned project convention governing minimum search completion, result traversal, context-view assembly, visual escalation, operational ceilings, and the consequences of incomplete evidence coverage. Completion requires guidance-seeded expected-evidence and contradiction or follow-up passes across available primary-report, protocol/SAP, registry, supplement, and later-report roles. Statements are aligned by Trial, event, population, Arm, Result, analysis, time point, and chronology; duplicate copies do not count as independent corroboration, and material conflicts remain separately attributable without a universal Source hierarchy. The policy changes how evidence is sought and presented without changing RoB 2 decision logic or the semantic retrieval aids carried by the Guidance pack.
_Avoid_: Guidance pack, hard-coded search limits

**Project rules**:
An optional, versioned set of attributable project conventions that may guide signaling-question answers when their stated conditions are met. Project rules cannot change Logic-pack behavior, replace required source evidence, or silently override a judgment, and the applicable rule is cited only when it materially influences an answer.
_Avoid_: Custom logic pack, hidden prompt instruction

**Project manifest revision**:
An immutable, portable statement of project intent that selects Outcome targets, supported RoB 2 scope, source adapters, pack releases, and applicable project policies. It is independent of host configuration and personal interface preferences, and each Preparation attempt binds its exact revision.
_Avoid_: Host settings, user preferences, mutable project config

**Confirmed run definition**:
The immutable, human-approved meaning of one run, including its supported RoB 2 method and canonical Result definitions, populations, estimands, measurements, analyses, effect measures, source locators, and time-point rules. It binds semantic Result identity but not extracted numerical estimates, intervals, event counts, or denominators, which belong to ResultSpec revisions. Later inputs must map safely to it; changing its meaning or silently substituting another Result requires a new run rather than rewriting the confirmed definition.
_Avoid_: Semantic contract, mutable run definition, input snapshot

**Current run**:
The sole unfinished run selected for automatic continuation within one project root. A direct request to continue resumes the sole Current run after a concise Resume summary; a clearly matching request recommends resume, while different or ambiguous scope requires one resume-or-start-new choice. Starting another run explicitly retires the previous Current run without deleting its Workflow ledger, artifacts, or inspectable history; completed and retired runs are never competing automatic resume candidates.
_Avoid_: Latest folder, concurrent active runs, deleted prior run

**Paused run**:
A Current run for which no new Preparation work is issued after the next safe atomic boundary, while every committed checkpoint and its automatic-continuation eligibility remain intact. User requests to stop for now, Harness disconnection, process interruption, or usage exhaustion pause rather than retire the Run.
_Avoid_: Cancelled run, failed run, retired run

**Retired run**:
An unfinished Run intentionally removed from automatic continuation without deleting its Workflow ledger, artifacts, or inspectable history. Retirement expresses abandonment or replacement, not failure or destructive cleanup.
_Avoid_: Paused run, deleted run, completed run

**Run reopening**:
The explicit resumption of a completed Run after compatible new or corrected input, preserving its Confirmed run definition while creating a new Input snapshot and superseding Preparation attempt. Dependency invalidation recomputes only affected Results from their earliest stale checkpoints, and prior reports or diagnostics remain immutable revisions. A change to Trial, Result, population, analysis, or time-policy meaning requires a new Run proposal instead.
_Avoid_: Automatic resume, mutable completed run, changed-scope continuation

**Run proposal**:
An immutable, content-digested candidate run definition and initial Trial, registry, and Source inventory presented for human confirmation. Proposal discovery uses bounded, structure-first inspection of provided Sources plus targeted identifier or registry checks needed for Trial identity, document structure, and coherent context around candidate outcome definitions, time points, and analyses; broad external acquisition waits until the Run meaning is confirmed. Filenames, acronyms, bibliography hits, metadata, or isolated keywords cannot alone establish Trial identity or Result availability. An agent may map requested clinical concepts to engine-discovered candidates and locators, while deterministic validation enforces supported-method and referential constraints. It autonomously constructs the most defensible complete proposal and asks an interim human question only when a Material proposal ambiguity cannot be resolved from the request and Sources; it does not seek approval after each Source, Trial, synonym, or candidate. Its normal human-readable view summarizes the method and shared Outcome-target rules, compares every Trial and Result, foregrounds differences, exclusions, ambiguities, missing source roles, planned acquisition, and limitations, and progressively reveals provenance while keeping opaque identities and raw schemas diagnostic. A natural-language correction is translated into a validated successor proposal with a human-readable semantic diff; it never mutates the prior proposal. The human may change research intent, grouping, valid candidate selection, time rules, or scope, but cannot make unsupported Source claims, merge distinct Trials, waive the Result-bearing full-text requirement, or select an unsupported RoB 2 method. Exhaustive RoB 2 evidence mining and broader source recovery begin only after confirmation. Its opaque proposal token becomes stale if any bound input or proposed meaning changes; confirmation promotes the exact latest proposal into a Confirmed run definition rather than editing the proposal in place.
_Avoid_: Draft manifest, mutable run definition, unbound confirmation prompt

**Run definition confirmation**:
The human operator's one-time contextual approval of a Confirmed run definition and its initial Trial, registry, and Source inventory before evidence mining begins. No magic phrase is required, but the approval must directly answer the latest human-readable confirmation prompt and bind an attributable human Actor to that exact Run-proposal token and digest; an agent's recommendation, the original request, silence, or an approval detached from the latest proposal is not confirmation. Confirmation is atomic over the requested scope: every requested Trial and Outcome-target pairing must identify exactly one trial-specific Result, be explicitly excluded with a human-readable reason, or be removed from scope by the human; an unresolved or competing mapping prevents confirmation. It authorizes execution but does not endorse any evidence, answer, or judgment produced by the run.
_Avoid_: Assessment sign-off, result review, report approval

**Material proposal ambiguity**:
An unresolved pre-confirmation uncertainty that could change the Run's meaning or requested coverage, including Trial or Randomization identity, Source–Trial association, selected Result, Outcome-target mapping, population, Comparison, estimand, measurement, analysis, time policy, or an inclusion/exclusion disposition. It prevents Run definition confirmation without relying on a numeric confidence threshold. Bibliographic gaps and unavailable optional Sources remain disclosed limitations rather than material ambiguities when identity and Result meaning are otherwise secure.
_Avoid_: Low confidence, any missing metadata, hidden assumption

**Input snapshot revision**:
An immutable inventory of active Trial folders and Source artifacts at one scan, including stable identities, relative paths, content hashes, registry provenance, and their compatibility with the Confirmed run definition. Discovery remains inside the explicitly selected project input root, does not follow links beyond it, excludes rob2-kit outputs and operational metadata, records unsupported or unreadable files, and deduplicates identical content while preserving every original path as provenance. Successive revisions preserve additions, changes, removals, and no-op scans without changing the run's meaning.
_Avoid_: Confirmed run definition, folder timestamp, mutable file list

**Input reconciliation**:
The content-hash comparison of current Trial folders and Source artifacts with the latest Input snapshot revision. Compatible changes create an attributable snapshot revision, trace their exact dependencies, and invalidate only affected ResultSpecs, Evidence Bundles, Domain answers, judgments, reports, and downstream preparation scopes; unaffected completed work remains reusable. A change that could alter the Confirmed run definition becomes a Material input ambiguity rather than a silent reconciliation.
_Avoid_: Reinitialize project, folder rescan, silent input mutation

**Material input ambiguity**:
An unresolved mismatch that could change whether a Trial, Source, or observed result belongs under the Confirmed run definition. It blocks completion rather than silently broadening that definition; the input must be corrected or removed, or assessed in a new run.
_Avoid_: Low-confidence match, automatic remapping, report correction

**Report audit**:
The human reader's inspection of a generated Assessment report and its evidence trail after the run completes. It occurs outside rob2-kit and creates no review state, correction request, override, or sign-off within the system.
_Avoid_: Guided review, Assessment sign-off, correction flow

**Report bundle**:
The fully local, manifest-rooted set of static human-readable reports and ancillary machine-readable outputs materialized incrementally from a Run. Each Result report or diagnostic report becomes independently available through an atomic checkpoint; the bundle is labeled complete only when every requested Result is terminal. It contains one regenerable Run index, one Result report or diagnostic report per terminal Result, and their required visual assets, while Assessment revisions and the Workflow ledger remain the source of truth.
_Avoid_: Web application, review workspace, verification archive

**Run index**:
The deterministic static entry page of a Report bundle, regenerated from durable state to organize every requested Trial and Result, its current preparation state or terminal outcome, available report, Domain and overall judgments where valid, and run-level limitations. It may expose completed Result reports while the Run is paused or assessing but labels the bundle complete only when every requested Result is terminal. It creates no live dashboard, workflow state, or report-comparison mode.
_Avoid_: Dashboard, project workspace, run controller

**Result report**:
The static human-audit projection of one complete Assessment revision, organized by RoB 2 domain and signaling question and exposing answers, rationales, supporting and contradicting Evidence claims, exact source phrases, Visual citations, Decision traces, coverage, and limitations through progressive disclosure. It is read-only and carries no correction, override, review, or sign-off state.
_Avoid_: Review case, editable assessment, paper-level report

**Diagnostic report**:
The static human-audit projection of a Result that could not produce a valid Assessment, listing every scoped blocker and any submitted signaling-question answers and rationales as diagnostic inputs. It contains no Domain or Overall judgments and never presents those inputs as a completed assessment.
_Avoid_: Partial Result report, provisional judgment, failed HTML report

**Visual-inspection gate**:
A condition indicating that a signaling question depends on a table, figure, spatial layout, or suspect text extraction and therefore requires inspection of a rendered page or crop. Visual inspection is selective because it consumes substantially more model context than verified text.
_Avoid_: Screenshot everything, visual fallback

**Visual candidate**:
A table, figure, or source region shortlisted for possible inspection because a Result locator, Guidance-pack mapping, retrieved reference, relevant caption, numerical conflict, or parse/render discrepancy connects it to an active signaling question. An agent may nominate additional candidates with a recorded question-specific reason, subject to the same visual budget.
_Avoid_: Every figure, arbitrary screenshot

**Visual candidate disposition**:
The attributable outcome for a Visual candidate: inspected, shown irrelevant to the Result or question, duplicate of another candidate, or unresolved. Visual coverage is complete only when every candidate has a disposition and every mandatory or still-plausibly-relevant candidate was inspected.
_Avoid_: Unlogged omission, screenshot count

**Visual transcription**:
An attributable reading of decision-relevant content from a rendered source region when canonical text is absent or unreliable. A legible transcription may support an answer when it is bound to the exact crop and transparently labeled as visual evidence, while an ambiguous region cannot support an answer; it is never reclassified as machine-verified canonical text.
_Avoid_: Verified quote, OCR correction

**Autonomous preparation**:
An uninterrupted post-confirmation run that produces the maximum defensible Assessment revision and static report without asking humans questions mid-run. An unresolved material evidence or coverage condition stops only the affected Result and produces a diagnostic report without an overall judgment rather than silently guessing or treating an operational limitation as a RoB 2 answer.
_Avoid_: Unconfirmed run, fail-open assessment

**Preparation attempt**:
An immutable execution episode of Autonomous preparation under one exact engine, schema, parser, pack, and policy contract. Usage exhaustion, Harness loss, or process interruption is an operational interruption rather than a scientific outcome: committed checkpoints remain reusable and the active uncommitted work item remains outstanding. An interrupted attempt may resume from committed checkpoints, while an execution-contract change creates a superseding attempt and recomputes only affected dependencies.
_Avoid_: Run, mutable preparation

**Execution contract**:
The exact release-locked set of rob2-kit engine, skill hashes, schemas, parser, Logic pack, Guidance pack, and policies under which a Preparation attempt executes. Mutation requires an exact installed match; an intentional contract change creates a superseding attempt and declared Dependency invalidation rather than runtime version negotiation.
_Avoid_: Compatible-enough version range, host capability matrix, implicit latest

**Preparation outcome**:
The terminal state of an Autonomous preparation after the versioned Recovery policy is exhausted: trial failed when a required Source or Result cannot be recovered, preparation incomplete when an evidence, coverage, or Result-scoped integrity condition prevents a valid assessment, or report ready when a complete Assessment revision and its deterministic report bundle have been materialized. Terminal failure or incompleteness produces a diagnostic-ready Result and does not absorb transient network, usage, process, or rendering interruptions; a later corrected dependency may supersede the diagnostic and reopen only the affected Result.
_Avoid_: Assessment judgment, run status

**Result withdrawal**:
The attributable human decision after Run confirmation to stop one Result at the next safe boundary while unaffected Results continue. It preserves committed work and confirmed scope, produces a diagnostic-ready record identifying withdrawal rather than scientific failure, and may later be explicitly reopened under the unchanged Confirmed run definition.
_Avoid_: Silent exclusion, Result failure, Run retirement

**Preparation checkpoint**:
The reproducible boundary of a validated, atomically committed, and independently reusable work unit from which interrupted or selectively invalidated Autonomous preparation can continue. Reusable boundaries include Source acquisition/parsing/indexing revisions, the frozen ResultSpec and Source inventory, each Domain's frozen question-specific Evidence, each Domain's completed answers and judgment, the overall Assessment revision, and deterministic report materialization. These durable boundaries do not require human acknowledgement; an uncommitted unit is retried and never converted into an assessment finding.
_Avoid_: Run status, resume flag

**Preparation work item**:
The next policy-permitted, bounded unit of agent reasoning issued from authoritative Workflow-ledger state, bound to exact dependencies, an expected submission kind, and a Preparation checkpoint. It is derived when requested rather than maintained as a separate mutable queue.
_Avoid_: Prompt, agent task, mutable preparation queue

**Domain assessment unit**:
The coherent assessor unit for one RoB 2 Domain of one Result, covering every signaling question active within that Domain while retaining separate Evidence Bundles, rationales, and answers for each question. It contains two ordered Preparation work-item kinds: a Domain-level freeze validates accumulated review and creates separate immutable question-specific Evidence Bundles, then an answer work item reasons against those bundles; a correctable evidence condition may issue a fresh attempt of these kinds without creating a new Domain assessment unit. Explicitly shared Evidence claims may link to several bundles without making their scopes interchangeable. This bounds repeated context without combining all five Domains or fragmenting orchestration into one task per signaling question.
_Avoid_: Domain assessment work item, signaling-question task, whole-Result assessment task, domain-level evidence citation

**Work token**:
An opaque, engine-issued reference that authorizes exactly one typed submission for one active Preparation work item. The engine binds its permitted submission kind, dependency fingerprint, contract version, and checkpoint internally; an identical retry after a lost or uncertain response returns the committed result, while changed content, stale dependencies, or a mismatched submission kind is rejected. Continuing without that response derives whether to skip the committed item or reissue the uncommitted item from the Workflow ledger; when a later Workflow condition requires corrected content, the engine issues a distinct Preparation work item and Work token while retaining reusable Domain-scoped progress. The Harness never invents an idempotency identity or infers success from output files; a successful nonterminal submission may return a successor token for the next work item in the same Domain assessment unit.
_Avoid_: User-authored idempotency key, client-assembled mutation context, reusable authorization

**Workflow ledger**:
The authoritative, append-only account of committed initialization, confirmation, preparation, invalidation, report-materialization, and failure transitions, their actors, dependencies, input and output revisions, and outcomes. Current progress and the next permitted work item are derived from it rather than maintained as competing mutable state.
_Avoid_: Audit log, status table, JSONL source of truth

**Run writer lease**:
The time-bounded authority for one Harness execution to append mutations to a Run while any number of readers inspect durable status and reports. A competing writer receives an expected already-active condition; after an abandoned lease expires, another Harness may take over only from the Workflow-ledger-derived checkpoint, never from chat history or assumed agent progress.
_Avoid_: Run lockout, Harness ownership, concurrent mutation

**Workflow event**:
An immutable, ordered record of one meaningful committed initialization, confirmation, preparation, invalidation, report-materialization, or failure transition in the Workflow ledger. Detailed evidence-search activity and tool diagnostics remain referenced receipts rather than separate top-level Workflow events.
_Avoid_: GUI interaction, telemetry event, mutable status change

**Workflow condition**:
An expected structured outcome that changes or constrains the next permitted workflow action, such as stale work, input invalidation, retryable interruption, scoped incompleteness, a correctable blocker, or a Run integrity failure. It is returned through the normal tool result contract with commit and resume information rather than represented as an MCP transport or internal error.
_Avoid_: Exception, tool crash, free-text warning

**Run directive**:
The single authoritative instruction derived from current Workflow-ledger state when a Harness continues a run: obtain confirmation, perform one bounded agent work item, surface a correctable run-wide blocker, acknowledge run completion, or stop for a Run integrity failure. Trial- and Result-scoped problems become diagnostic Preparation outcomes while unaffected work continues. A Run directive is distinct from read-only status and is never inferred by a Harness from folders, reports, or conversation history.
_Avoid_: Harness-inferred next step, mutable task queue, run status

**Resume summary**:
A concise, engine-derived projection of a Current run's confirmed scope, interruption reason, Result-state counts, reconciled changes, currently affected Trial, Result, and Domain, actionable blockers, and one recommended next action. It is reconstructed from durable state rather than Harness chat history or optional notifications, while completed details and ledger history remain available through progressive disclosure.
_Avoid_: Conversation recap, event dump, mutable progress note

**Progress snapshot**:
A concise, engine-derived view of overall Result-state counts, the active Trial, Result, and Domain, the latest committed checkpoint, scoped warnings or interruptions, and the next planned unit. Harness narration and optional MCP progress notifications project this same durable view; missing or lost notifications change only presentation and never correctness or resumability.
_Avoid_: Tool-call log, notification-owned state, verbose event stream

**Run work order**:
The stable ordering of pending Results under which shared deterministic preparation is reused and one Result is prepared end-to-end before the next begins. A human may reprioritize still-pending Results after the current safe boundary without changing assessment meaning or invalidating completed work; the attributable ordering change remains durable.
_Avoid_: Parallel assessment queue, hidden scheduler order, semantic scope change

**Run state**:
The coarse durable condition presented to a Harness: awaiting confirmation, assessing, blocked, complete, integrity failed, or retired. It summarizes run control and health without exposing internal engine phases or collapsing Result-scoped outcomes into run failure.
_Avoid_: Run directive, ledger event, Result status

**Result preparation state**:
The independently derived progress of one Result within a run: pending, assessing, assessment ready, report ready, or diagnostic ready. Assessment ready means the complete Assessment revision is committed but deterministic report materialization is still pending or failed; report failure never causes scientific work to be repeated. A failure or unresolved limitation affects only Results whose explicit dependencies are implicated, even when several belong to one Trial or share a Source. Report-ready and diagnostic-ready Results coexist in one completed run, while their detailed reason and provenance remain in the Assessment or diagnostic report.
_Avoid_: Run state, overall RoB 2 judgment, generic failed status

**Replay guarantee**:
The promise that committed agent outputs can be reused and all deterministic state can be reconstructed from their exact recorded inputs and revisions. It does not promise that rerunning a commercial model will reproduce the same output or hidden reasoning.
_Avoid_: Bit-for-bit model replay, conversation replay

**Durable run state**:
The complete typed, attributable, and integrity-bound facts needed to derive Run progress, resume safely, reproduce committed work, and render reports independently of Harness memory. It includes confirmed proposal and input revisions; Trial, Source, Parse, index, ResultSpec, dependency, evidence, answer, judgment, Assessment, attempt, interruption, diagnostic, invalidation, lease, Workflow, report, and archive records. Full conversations, hidden reasoning, transient progress messages, and optional notification history are excluded; necessary human and agent decisions survive as typed attributable submissions.
_Avoid_: Chat transcript, UI state, notification log

**Run integrity failure**:
A failure that makes shared authoritative state, dependency identity, or reproducibility untrustworthy and therefore stops all new Run mutations. Existing bytes, ledger history, and reports remain inspectable but cannot establish Run completeness or reproducibility and carry an integrity warning until an attributable bounded repair restores verification; repair appends history rather than silently rewriting it. Source, Trial, and assessment problems whose affected Results can be derived safely are not Run integrity failures.
_Avoid_: Trial failure, transient interruption

**Verification archive**:
A portable, manifest-rooted package for checking an Assessment revision outside its working project. A complete archive materializes all transitive source and decision dependencies; a reference archive may omit bytes but must declare that source integrity is not independently verifiable.
_Avoid_: Report bundle, backup, equally verifiable thin export

**Release acceptance gate**:
An executable criterion tied to a claimed v1 behavior. Evidence-pipeline gates require fixture-complete discovery and lineage, fail-closed freeze of projections, ambiguous fragments and unreviewed spans, deterministic stale/truncation recovery, exact dependency invalidation, and successful generalized-workflow replay of CHAARTED PFS; efficiency uses versioned fixture budgets rather than a universal scientific threshold.
_Avoid_: Aspirational requirement, documented known failure

**Private release evaluation**:
An owner-led, blinded run of a frozen candidate across every materializable Trial and Outcome target in the private real-RCT corpus, followed by direct review of the resulting Assessments, evidence trails, reports, usability, recovery, latency, cost signals, and Provisional reference-label discrepancies. It informs the owner's discretionary release decision without a fixed rubric, coded score, mandatory discrepancy taxonomy, or numerical threshold.
_Avoid_: Automated benchmark, correctness oracle, CI gate, fixed sign-off rubric

**Provisional reference label**:
A prior assessment judgment used for comparison or discrepancy review when its assessor provenance, evidence, rationale, or adjudication method is incomplete. It may guide preview evaluation but is not a correctness oracle.
_Avoid_: Gold standard, adjudicated reference
