# RoB 2 Assessment

This context describes the evidence-grounded assessment of bias in a specific randomized-trial Result and its transparent static report.

## Language

**Outcome target**:
A project-level description of the outcome and time point that researchers intend to assess across trials. It guides batching and discovery but is not itself an assessment identity.
_Avoid_: Outcome specification, assessment outcome

**Result**:
The stable, trial-specific intervention-effect analysis to which one RoB 2 assessment applies. Its identity includes the trial, randomization, comparison, effect of interest, outcome, measurement, time point, analysis choices, effect measure, and unique source locator, but not the extracted numerical value.
_Avoid_: Paper assessment, study-level risk of bias

**ResultSpec revision**:
An immutable resolved description of a Result at a point in time, including its numerical values, denominators, locators, and provenance. Correcting any of that content creates a new revision and invalidates dependent judgments and signatures without changing the Result’s identity.
_Avoid_: Result, outcome target

**Trial**:
The underlying randomized experiment, independent of any particular publication, folder, acronym, or registry record. External identifiers and multiple reports may refer to the same Trial, while uncertain record linkage remains unresolved.
_Avoid_: Paper, report, study folder

**Randomization**:
A distinct random allocation process within a Trial. It is the boundary within which randomization evidence may be considered for reuse.
_Avoid_: Trial arm, comparison

**Comparison**:
The ordered experimental and comparator Arms selected from one Randomization for a Result. It identifies the intervention contrast being assessed.
_Avoid_: Trial, intervention pair

**Evidence candidate**:
A potentially relevant retrieval result that has not yet been accepted as support for an assessment claim. It cannot be cited by a signaling-question answer.
_Avoid_: Evidence, verified quote

**Evidence candidate disposition**:
The attributable pre-answer decision to accept an Evidence candidate as supporting, contradicting, or contextual; reject it as duplicate, out of scope, immaterial, or superseded; or leave it unresolved. An Evidence Bundle cannot be frozen while a potentially material candidate remains unresolved.
_Avoid_: Silent exclusion, answer-driven selection

**Canonical evidence unit**:
The smallest preserved source unit that may ground an Evidence claim, such as a paragraph, heading, list item, caption, footnote, or table row, with stable page and spatial provenance. Larger search projections and neighboring context may help locate it but are not independently citable.
_Avoid_: Generated chunk, search aggregate

**Visual citation**:
A deterministic report view binding an Evidence claim's exact Canonical evidence unit span to the source page render and one or more highlight boxes. It exposes provenance for human audit without implying that an agent inspected the image or creating a separate evidence item.
_Avoid_: Visual candidate, Visual transcription, screenshot evidence

**Evidence claim**:
An immutable, typed assertion linked to an exact span selected from a Canonical evidence unit and its source provenance; deterministic code materializes the quoted text rather than accepting agent-authored quotation text. It records whether its basis is canonical text or a Visual transcription, and its status must never imply stronger validation than it received.
_Avoid_: Retrieval hit, evidence snippet

**Derived fact**:
An immutable value produced by a named, deterministic RoB 2-relevant derivation from typed Evidence claims, with explicit population, arm, analysis set, outcome, time point, units, formula, and rounding provenance. It inherits uncertainty and review requirements from its inputs and is never a model-authored calculation.
_Avoid_: Narrative calculation, general statistical analysis

**Evidence Bundle**:
The immutable, content-hashed set of accepted supporting and contradicting Evidence claims, derived facts, Visual transcriptions, Search coverage receipts, and declared limitations frozen before a signaling-question answer is made. Discovering or correcting evidence requires a new bundle revision rather than changing an existing bundle or silently extending it during answering.
_Avoid_: Context window, search results

**Evidence consideration manifest**:
The complete account of how every accepted item in an Evidence Bundle was considered for one signaling-question answer, including whether it was supporting, contradicting, contextual, duplicate, or unresolved. It permits a large bundle to be traversed through bounded working views without treating a context-window limit as an evidence limit.
_Avoid_: Context summary, model memory

**Search coverage receipt**:
An immutable account of the versioned minimum search protocol performed for one signaling question, including the exact ResultSpec, source inventory, parses, index, guidance, rules, and search policy used; sources and visual regions covered; queries, filters, and results inspected; stopping reason; and any coverage limits. It establishes procedural search adequacy rather than proving that absent evidence does not exist, and deterministic dependency rules decide when it becomes stale.
_Avoid_: Search confidence, retrieval log

**Search query**:
A structured, attributable expression of lexical search intent using terms, phrases, prefixes, Boolean groups, and source metadata filters. Deterministic code compiles it for the search engine, so agents do not provide executable search syntax.
_Avoid_: Raw FTS expression, prompt

**Search result disposition**:
The attributable account of whether a unique evidence unit returned by an accepted Search query was inspected and found irrelevant, retained as an Evidence candidate, or already covered as a duplicate. Complete paginated traversal requires a disposition for every unique returned unit.
_Avoid_: Rank cutoff, implicit omission

**Trial orientation pack**:
A bounded summary that orients an assessor to one Trial preparation through its ResultSpec, Source inventory, coverage limitations, document outlines, registry projection, and applicable pack and policy identities. It points to complete searchable sources rather than attempting to reproduce the full dossier.
_Avoid_: Full-text context, trial dossier

**Domain context pack**:
The bounded, reproducible starting view for one Domain assessment work item, containing its Result and domain identity, applicable signaling questions and guidance, Project rules, Source inventory and limitations, accepted reusable Evidence claims, and required search and visual protocol. It organizes evidence by signaling question but points to bounded retrieval capabilities rather than reproducing a complete Evidence Bundle or source dossier.
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
The completed Search coverage receipts and adequate readable-source coverage that justify concluding that required information was not found. Missing, unreadable, unsearched, or search-limited material cannot itself establish this basis.
_Avoid_: No search hit, tool failure

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
A reproducible domain or overall RoB 2 judgment derived from an exact answer set and Logic-pack version. Its Decision trace explains the branch taken.
_Avoid_: Model judgment, final judgment

**Decision trace**:
The deterministic, structured explanation of a Logic-pack evaluation, identifying its exact inputs, active and inactive questions, evaluated and matched rules, and resulting judgments. It records reproducible rule execution rather than hidden model reasoning.
_Avoid_: Chain of thought, narrative rationale

**Overall judgment policy**:
The fixed maximum-domain roll-up in which all Low domain judgments produce Low overall, any High domain judgment produces High overall, and every remaining combination produces Some concerns. It does not escalate multiple Some-concerns domains through an additional assessor input.
_Avoid_: Combined-concerns judgment, model roll-up, human escalation

**Final judgment**:
The current deterministic domain or overall judgment derived from the applicable SQ Answer revisions and Logic-pack release. It is never independently editable or replaced by a human override.
_Avoid_: Proposed judgment, model judgment, manual label

**Source descriptor**:
The identity and expected roles of an obtained, missing, or discovered information source, including relevant dates and external identifiers. Roles are attributable classifications rather than forced labels, and the descriptor can exist even when no content was acquired.
_Avoid_: PDF, source file

**Source criticality**:
The consequence of a source’s unavailability for a particular Result preparation: required sources must be acquired and sufficiently readable, expected sources receive a bounded acquisition attempt, and optional sources are used when available. Criticality is contextual and distinct from source role or authority.
_Avoid_: Source role, global evidence ranking

**Source conflict**:
Two or more acquired source statements that materially disagree about the same event, population, analysis, outcome, or time point after accounting for chronology and amendments. Each statement remains separately attributable; resolution requires an explicit methodological or chronological basis rather than a universal source hierarchy.
_Avoid_: Any source difference, automatic precedence

**Acquisition receipt**:
An immutable record of one attempt to obtain a Source, including its method, origin, time, actor, declared metadata, outcome, and any failure category. Multiple receipts may point to the same content-hashed Source artifact without losing where each copy came from.
_Avoid_: Download log, Source artifact

**Recovery policy**:
The versioned project policy that bounds safe acquisition and processing retries, permitted adapters, terminal failure categories, and the conditions under which a changed input may be attempted again.
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
The derived loss of current usability when an exact dependency of a revision changes, propagated only through its explicit dependency relationships. Invalidated revisions remain immutable and auditable, while affected preparation resumes from the earliest stale checkpoint.
_Avoid_: Deletion, blanket rerun, mutable stale flag

**Actor**:
The attributable human, agent run, or deterministic system component responsible for an authored or derived revision. Actor provenance states only identity and version information the host can actually establish.
_Avoid_: User, model

**Harness**:
A supported agent host, initially Codex or Claude Code, that invokes rob2-kit skills and MCP tools while presenting progress and required run-control choices in its own conversation. It is an orchestration client; authoritative assessment and resume state remains in rob2-kit.
_Avoid_: Companion workspace, web client, workflow engine

**Evidence search policy**:
The versioned project convention governing minimum search completion, result traversal, context-view assembly, visual escalation, operational ceilings, and the consequences of incomplete evidence coverage. It changes how evidence is sought and presented without changing RoB 2 decision logic or the semantic retrieval aids carried by the Guidance pack.
_Avoid_: Guidance pack, hard-coded search limits

**Project rules**:
An optional, versioned set of attributable project conventions that may guide signaling-question answers when their stated conditions are met. Project rules cannot change Logic-pack behavior, replace required source evidence, or silently override a judgment, and the applicable rule is cited only when it materially influences an answer.
_Avoid_: Custom logic pack, hidden prompt instruction

**Project manifest revision**:
An immutable, portable statement of project intent that selects Outcome targets, supported RoB 2 scope, source adapters, pack releases, and applicable project policies. It is independent of host configuration and personal interface preferences, and each Preparation attempt binds its exact revision.
_Avoid_: Host settings, user preferences, mutable project config

**Confirmed run definition**:
The immutable, human-approved meaning of one run, including its supported RoB 2 method and canonical Result definitions, populations, estimands, measurements, and time-point rules. Later inputs must map safely to it; changing its meaning requires a new run rather than rewriting the confirmed definition.
_Avoid_: Semantic contract, mutable run definition, input snapshot

**Current run**:
The sole unfinished run selected for automatic continuation within one project root. Starting another run explicitly retires the previous Current run without deleting its Workflow ledger, artifacts, or inspectable history; completed and retired runs are never competing resume candidates.
_Avoid_: Latest folder, concurrent active runs, deleted prior run

**Run proposal**:
An immutable, content-digested candidate run definition and initial Trial, registry, and Source inventory presented for human confirmation. An agent may map requested clinical concepts to engine-discovered candidates and locators, while deterministic validation enforces supported-method and referential constraints. Its opaque proposal token becomes stale if any bound input changes; confirmation promotes its exact meaning into a Confirmed run definition rather than editing the proposal in place.
_Avoid_: Draft manifest, mutable run definition, unbound confirmation prompt

**Run definition confirmation**:
The human operator's one-time approval of a Confirmed run definition and its initial Trial, registry, and Source inventory before evidence mining begins. It authorizes execution but does not endorse any evidence, answer, or judgment produced by the run.
_Avoid_: Assessment sign-off, result review, report approval

**Input snapshot revision**:
An immutable inventory of active Trial folders and Source artifacts at one scan, including stable identities, relative paths, content hashes, registry provenance, and their compatibility with the Confirmed run definition. Successive revisions preserve additions, changes, removals, and no-op scans without changing the run's meaning.
_Avoid_: Confirmed run definition, folder timestamp, mutable file list

**Input reconciliation**:
The content-hash comparison of current Trial folders and Source artifacts with the latest Input snapshot revision. Compatible changes create an attributable snapshot revision and invalidate only dependent preparation scopes without another confirmation or rewritten history.
_Avoid_: Reinitialize project, folder rescan, silent input mutation

**Material input ambiguity**:
An unresolved mismatch that could change whether a Trial, Source, or observed result belongs under the Confirmed run definition. It blocks completion rather than silently broadening that definition; the input must be corrected or removed, or assessed in a new run.
_Avoid_: Low-confidence match, automatic remapping, report correction

**Report audit**:
The human reader's inspection of a generated Assessment report and its evidence trail after the run completes. It occurs outside rob2-kit and creates no review state, correction request, override, or sign-off within the system.
_Avoid_: Guided review, Assessment sign-off, correction flow

**Report bundle**:
The fully local, manifest-rooted set of static human-readable reports and ancillary machine-readable outputs materialized from one completed run. It contains one Run index, one Result report or diagnostic report per requested Result, and their required visual assets, while the Assessment revisions and Workflow ledger remain the source of truth.
_Avoid_: Web application, review workspace, verification archive

**Run index**:
The static entry page of a Report bundle, organizing every requested Trial and Result, its terminal preparation outcome, available report, domain and overall judgments where valid, and run-level limitations. It links to Result reports but creates no live dashboard, workflow state, or report-comparison mode.
_Avoid_: Dashboard, project workspace, run controller

**Result report**:
The static human-audit projection of one complete Assessment revision, organized by RoB 2 domain and signaling question and exposing answers, rationales, supporting and contradicting Evidence claims, exact source phrases, Visual citations, Decision traces, coverage, and limitations through progressive disclosure. It is read-only and carries no correction, override, review, or sign-off state.
_Avoid_: Review case, editable assessment, paper-level report

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
An immutable execution episode of Autonomous preparation under one exact engine, schema, parser, pack, and policy contract. An interrupted attempt may resume from committed checkpoints, while an execution-contract change creates a superseding attempt and recomputes only affected dependencies.
_Avoid_: Run, mutable preparation

**Execution contract**:
The exact release-locked set of rob2-kit engine, skill hashes, schemas, parser, Logic pack, Guidance pack, and policies under which a Preparation attempt executes. Mutation requires an exact installed match; an intentional contract change creates a superseding attempt and declared Dependency invalidation rather than runtime version negotiation.
_Avoid_: Compatible-enough version range, host capability matrix, implicit latest

**Preparation outcome**:
The terminal state of an Autonomous preparation: trial failed when a required source or Result cannot be recovered, preparation incomplete when an operational or evidence gap prevents a valid assessment, or report ready when a complete Assessment revision and its deterministic report bundle have been materialized.
_Avoid_: Assessment judgment, run status

**Preparation checkpoint**:
The reproducible boundary of a validated, atomically committed, and independently reusable work unit from which interrupted or selectively invalidated Autonomous preparation can continue. It is distinct from a Preparation outcome; an uncommitted unit is retried and never converted into an assessment finding.
_Avoid_: Run status, resume flag

**Preparation work item**:
The next policy-permitted, bounded unit of agent reasoning issued from authoritative Workflow-ledger state, bound to exact dependencies, an expected submission kind, and a Preparation checkpoint. It is derived when requested rather than maintained as a separate mutable queue.
_Avoid_: Prompt, agent task, mutable preparation queue

**Domain assessment unit**:
The coherent assessor unit for one RoB 2 domain of one Result, covering every signaling question active within that domain while retaining separate Evidence Bundles, rationales, and answers for each question. It contains exactly two ordered Preparation work items: freeze the domain's question-specific evidence, then answer against that frozen evidence. This bounds repeated context without combining all five domains or fragmenting orchestration into one task per signaling question.
_Avoid_: Domain assessment work item, signaling-question task, whole-Result assessment task, domain-level evidence citation

**Work token**:
An opaque, engine-issued reference that authorizes exactly one typed submission for one active Preparation work item. The engine binds its permitted submission kind, dependency fingerprint, contract version, and checkpoint internally; an identical retry returns the committed result, while changed content, stale dependencies, or a mismatched submission kind is rejected. A successful nonterminal submission may return a successor token for the next work item in the same Domain assessment unit.
_Avoid_: User-authored idempotency key, client-assembled mutation context, reusable authorization

**Workflow ledger**:
The authoritative, append-only account of committed initialization, confirmation, preparation, invalidation, report-materialization, and failure transitions, their actors, dependencies, input and output revisions, and outcomes. Current progress and the next permitted work item are derived from it rather than maintained as competing mutable state.
_Avoid_: Audit log, status table, JSONL source of truth

**Workflow event**:
An immutable, ordered record of one meaningful committed initialization, confirmation, preparation, invalidation, report-materialization, or failure transition in the Workflow ledger. Detailed evidence-search activity and tool diagnostics remain referenced receipts rather than separate top-level Workflow events.
_Avoid_: GUI interaction, telemetry event, mutable status change

**Workflow condition**:
An expected structured outcome that changes or constrains the next permitted workflow action, such as stale work, input invalidation, retryable interruption, scoped incompleteness, a correctable blocker, or a Run integrity failure. It is returned through the normal tool result contract with commit and resume information rather than represented as an MCP transport or internal error.
_Avoid_: Exception, tool crash, free-text warning

**Run directive**:
The single authoritative instruction derived from current Workflow-ledger state when a Harness continues a run: obtain confirmation, perform one bounded agent work item, surface a correctable run-wide blocker, acknowledge run completion, or stop for a Run integrity failure. Trial- and Result-scoped problems become diagnostic Preparation outcomes while unaffected work continues. A Run directive is distinct from read-only status and is never inferred by a Harness from folders, reports, or conversation history.
_Avoid_: Harness-inferred next step, mutable task queue, run status

**Run state**:
The coarse durable condition presented to a Harness: awaiting confirmation, assessing, blocked, complete, integrity failed, or retired. It summarizes run control and health without exposing internal engine phases or collapsing Result-scoped outcomes into run failure.
_Avoid_: Run directive, ledger event, Result status

**Result preparation state**:
The independently derived progress of one Result within a run: pending, assessing, report ready, or diagnostic ready. Complete and diagnostic Results coexist in one completed run, while their detailed reason and provenance remain in the Assessment or diagnostic report.
_Avoid_: Run state, overall RoB 2 judgment, generic failed status

**Replay guarantee**:
The promise that committed agent outputs can be reused and all deterministic state can be reconstructed from their exact recorded inputs and revisions. It does not promise that rerunning a commercial model will reproduce the same output or hidden reasoning.
_Avoid_: Bit-for-bit model replay, conversation replay

**Run integrity failure**:
A failure that makes shared assessment state or reproducibility untrustworthy and therefore stops the whole run. Source and assessment problems that remain safely isolated to one trial are not Run integrity failures.
_Avoid_: Trial failure, transient interruption

**Verification archive**:
A portable, manifest-rooted package for checking an Assessment revision outside its working project. A complete archive materializes all transitive source and decision dependencies; a reference archive may omit bytes but must declare that source integrity is not independently verifiable.
_Avoid_: Report bundle, backup, equally verifiable thin export

**Release acceptance gate**:
An executable criterion tied to a claimed v1 behavior. Failure of a core gate blocks release, while an optional or experimental capability may degrade only when it is excluded from the completed assessment and its limitation is explicit.
_Avoid_: Aspirational requirement, documented known failure

**Private release evaluation**:
A blinded, manual review of frozen-candidate Assessments against the private real-RCT corpus and its Provisional reference labels. It records discrepancies and blocks release when a clinically material disagreement remains unexplained, but it is not product logic, an executable Release acceptance gate, or a coded accuracy threshold.
_Avoid_: Automated benchmark, correctness oracle, CI gate

**Provisional reference label**:
A prior assessment judgment used for comparison or discrepancy review when its assessor provenance, evidence, rationale, or adjudication method is incomplete. It may guide preview evaluation but is not a correctness oracle.
_Avoid_: Gold standard, adjudicated reference
