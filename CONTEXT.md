# RoB 2 Assessment

This context describes the evidence-grounded assessment of bias in a specific randomized-trial result and its accountable human review.

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

**Evidence claim**:
An immutable, typed assertion linked to an exact span selected from a Canonical evidence unit and its source provenance; deterministic code materializes the quoted text rather than accepting agent-authored quotation text. It may be machine-verified or require human review, and its status must never imply stronger validation than it received.
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

**SQ context pack**:
One bounded, reproducible working view of the guidance, applicable Project rules, accepted reusable Evidence claims, retrieved passages, contradictions, and gated visual material presented while answering one signaling question. Successive views may traverse a complete Evidence Bundle under a versioned policy; no individual view is itself the Evidence Bundle.
_Avoid_: Evidence Bundle, entire source document

**Context view manifest**:
The host-neutral, ordered account of the exact domain items, revisions, pagination state, selection reasons, and deterministic transformations used to render one Trial orientation pack or SQ context pack. Host-specific payloads bind back to this manifest without claiming access to hidden provider prompts or reasoning.
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
An immutable normative definition of one supported RoB 2 instrument edition, trial design, and effect of interest. It contains logic-element identities, allowed answers, applicability, branching, judgment rules, and required assessor inputs, but not official explanatory wording.
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
A reproducible domain or overall RoB 2 judgment derived from an exact answer set, assessor inputs, and logic-pack version. Its decision trace explains the branch taken.
_Avoid_: Model judgment, final judgment

**Decision trace**:
The deterministic, structured explanation of a Logic-pack evaluation, identifying its exact inputs, active and inactive questions, evaluated and matched rules, required assessor inputs, and resulting judgments. It records reproducible rule execution rather than hidden model reasoning.
_Avoid_: Chain of thought, narrative rationale

**Judgment override**:
A human decision to replace an Algorithmic judgment without changing its underlying signaling-question answers. It requires an attributable rationale and explicit policy authority.
_Avoid_: Corrected answer, edited judgment

**Final judgment**:
The current Algorithmic judgment after applying any active human Judgment override. It is a derived view rather than an independently editable value.
_Avoid_: Proposed judgment, manual label

**Domain review disposition**:
An attributable human decision to accept, correct, override, or defer one domain under a specific Review policy. A dependent change invalidates the affected disposition.
_Avoid_: Domain sign-off, checkbox approval

**Assessment sign-off**:
The final attributable human approval of an exact Result assessment after every domain satisfies the Review policy. It binds to the complete assessment snapshot and becomes invalid when any dependent artifact changes.
_Avoid_: Trial approval, agent sign-off

**Sign-off assurance**:
The explicit strength of the identity claim attached to an Assessment sign-off. V1 uses local human attribution bound to an integrity-verifiable Assessment revision and does not claim independently or cryptographically verified identity.
_Avoid_: Cryptographic signature, verified identity

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

**Coverage map**:
The page- and component-level account of what was read reliably, requires visual inspection or recovery, remains limited, or is intentionally blank. Aggregate source quality is derived from this map rather than represented by one opaque confidence score.
_Avoid_: Parser confidence, pass/fail document

**Source inventory revision**:
An immutable snapshot of Source availability, processing coverage, and assessment use for a Result preparation. It distinguishes information absent from adequately searched readable sources from sources not obtained, not processed, or not completely searched.
_Avoid_: Input folder, bibliography

**Source conflict**:
Two or more Evidence claims that cannot all describe the same relevant event, population, analysis, outcome, or time point after accounting for chronology and amendments. Each account remains preserved; resolution requires an explicit methodological or chronological basis, and unresolved material conflicts become Review findings.
_Avoid_: Any wording difference, automatic source precedence

**Assessment revision**:
The immutable, schema-versioned source of truth for one Result assessment, binding all exact input, evidence, answer, judgment, review, policy, and provenance revisions. Reports and exports are derived views, while a portable archive materializes every referenced artifact needed for independent verification.
_Avoid_: Current assessment, report

**Dependency invalidation**:
The derived loss of current usability when an exact dependency of a revision changes, propagated only through its explicit dependency relationships. Invalidated revisions remain immutable and auditable, while affected preparation and human review resume from the earliest stale checkpoint.
_Avoid_: Deletion, blanket rerun, mutable stale flag

**Actor**:
The attributable human, agent run, or deterministic system component responsible for an authored or derived revision. Actor provenance states only identity and version information the host can actually establish.
_Avoid_: User, model

**Reviewer profile revision**:
An immutable, project-scoped statement of the human identity used to attribute review actions, containing a required display name and optional affiliation or external identifiers. It supports local attribution and explicit session confirmation but is not an independently authenticated user account.
_Avoid_: Login, verified identity, mutable reviewer name

**Review policy**:
The versioned project convention that determines human sign-off granularity and when closer inspection is required. The v1 default is per-domain sign-off with signaling-question drill-down for triaged concerns, but projects may adopt a different policy.
_Avoid_: Hard-coded review workflow

**Evidence search policy**:
The versioned project convention governing minimum search completion, result traversal, context-view assembly, visual escalation, operational ceilings, and the consequences of incomplete evidence coverage. It changes how evidence is sought and presented without changing RoB 2 decision logic or the semantic retrieval aids carried by the Guidance pack.
_Avoid_: Guidance pack, hard-coded search limits

**Project rules**:
An optional, versioned set of attributable project conventions that may guide signaling-question answers when their stated conditions are met. Project rules cannot change Logic-pack behavior, replace required source evidence, or silently override a judgment, and the applicable rule is cited only when it materially influences an answer.
_Avoid_: Custom logic pack, hidden prompt instruction

**Project manifest revision**:
An immutable, portable statement of project intent that selects Outcome targets, supported RoB 2 scope, source adapters, pack releases, and applicable project policies. It is independent of host configuration and personal interface preferences, and each Preparation attempt binds its exact revision.
_Avoid_: Host settings, user preferences, mutable project config

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
An attributable reading of decision-relevant content from a rendered source region when canonical text is absent or unreliable. A legible transcription may support a draft answer but remains review-required, while an ambiguous region cannot support an answer; human acceptance never reclassifies it as machine-verified quoted text.
_Avoid_: Verified quote, OCR correction

**Autonomous preparation**:
An uninterrupted run that produces the maximum defensible draft assessment and a consolidated sign-off queue without asking humans questions mid-run. It preserves unresolved result identity, limited coverage, unverified evidence, and source conflicts as explicit review findings rather than silently guessing or treating operational limitations as RoB 2 answers.
_Avoid_: Autonomous final assessment, fail-open assessment

**Preparation attempt**:
An immutable execution episode of Autonomous preparation under one exact engine, schema, parser, pack, and policy contract. An interrupted attempt may resume from committed checkpoints, while an execution-contract change creates a superseding attempt and recomputes only affected dependencies.
_Avoid_: Run, mutable preparation

**Preparation outcome**:
The terminal state of an Autonomous preparation: trial failed when a required primary source or Result cannot be recovered, preparation incomplete when an operational gap prevents a valid signaling-question answer, or draft ready when a complete Assessment revision can be reviewed despite declared nonblocking findings.
_Avoid_: Assessment judgment, run status

**Preparation checkpoint**:
The reproducible boundary of a validated, atomically committed, and independently reusable work unit from which interrupted or selectively invalidated Autonomous preparation can continue. It is distinct from a Preparation outcome; an uncommitted unit is retried and never converted into an assessment finding.
_Avoid_: Run status, resume flag

**Preparation work item**:
The next policy-permitted, bounded unit of agent reasoning issued from authoritative Workflow-ledger state, bound to exact dependencies, an expected submission kind, and a Preparation checkpoint. It is derived when requested rather than maintained as a separate mutable queue.
_Avoid_: Prompt, agent task, mutable preparation queue

**Workflow ledger**:
The authoritative, append-only account of committed preparation and review transitions, their actors, dependencies, input and output revisions, and outcomes. Current progress and human-action queues are derived from it rather than maintained as competing mutable histories.
_Avoid_: Audit log, status table, JSONL source of truth

**Workflow event**:
An immutable, ordered record of one meaningful committed preparation, invalidation, review, sign-off, or failure transition in the Workflow ledger. Detailed evidence-search activity and tool diagnostics remain referenced receipts rather than separate top-level Workflow events.
_Avoid_: GUI interaction, telemetry event, mutable status change

**Replay guarantee**:
The promise that committed agent outputs can be reused and all deterministic state can be reconstructed from their exact recorded inputs and revisions. It does not promise that rerunning a commercial model will reproduce the same output or hidden reasoning.
_Avoid_: Bit-for-bit model replay, conversation replay

**Run integrity failure**:
A failure that makes shared assessment state or reproducibility untrustworthy and therefore stops the whole run. Source and assessment problems that remain safely isolated to one trial are not Run integrity failures.
_Avoid_: Trial failure, transient interruption

**Review finding**:
A typed condition that requires attention during sign-off, such as limited source coverage, unverified evidence, unresolved result identity, or conflicting sources. Its consequences come from the Review policy, while its reviewer-facing presentation uses plain biomedical language and a clear next action; it is distinct from a substantive `No information` signaling-question answer.
_Avoid_: Warning, No information

**Review queue**:
The policy-derived, ordered view of human actions available after every Trial in scope reaches a Preparation outcome. It may contain repair, verification, acknowledgment, domain-review, and Assessment sign-off actions, but the underlying findings, revisions, dispositions, and sign-offs remain the authoritative records.
_Avoid_: Final queue, mutable task list, warning list

**Guided review flow**:
The reviewer-facing traversal of a Review queue that prioritizes required human actions and higher-concern domains while keeping every domain, signaling-question answer, rationale, evidence claim, decision trace, and relevant Visual transcription available for optional inspection. It guides attention without hiding auditable work or replacing the Review policy.
_Avoid_: Mandatory wizard, exception-only review, opaque approval queue

**Companion workspace**:
The reopenable browser projection of durable project, preparation, evidence, Assessment, and review state that a supported agent host may display beside its conversation from project start through sign-off. Opening, refreshing, closing, or reconnecting it performs no model inference and does not affect authoritative progress.
_Avoid_: Agent transcript, live model session, standalone project editor

**Review handoff**:
The durable transfer from Autonomous preparation to direct human review, independent of whether an agent connection or browser session remains active. It preserves the exact next human action and returns control through a Review receipt.
_Avoid_: Live agent session, temporary review link

**Agent connection state**:
The transient indication that an agent host is waiting, performing targeted work, disconnected, or requires reinvocation during a Review handoff. It is informational only; Workflow-ledger state remains authoritative and review progress does not depend on the connection remaining active.
_Avoid_: Agent live status, preparation state, review status

**Review receipt**:
An immutable, typed outcome of a Review handoff, such as completed action, correction request, deferment, or Assessment sign-off, bound to the exact review and assessment revisions involved. It allows any later agent session to continue without relying on conversation history.
_Avoid_: Chat confirmation, mutable completion flag

**Verification archive**:
A portable, manifest-rooted package for checking an Assessment revision outside its working project. A complete archive materializes all transitive source and decision dependencies; a reference archive may omit bytes but must declare that source integrity is not independently verifiable.
_Avoid_: Report bundle, backup, equally verifiable thin export

**Release acceptance gate**:
An executable criterion tied to a claimed v1 behavior. Failure of a core gate blocks release, while an optional or experimental capability may degrade only when it is excluded from the completed assessment and its limitation is explicit.
_Avoid_: Aspirational requirement, documented known failure

**Hands-on preview**:
An explicitly pre-release, draft-only build made available once a safe end-to-end assessment and review path works, so its owner and invited lab users can refine the workflow before public-v1 assurance is complete. It must preserve work and prevent agent sign-off, but broader usability validation and hardening remain visible follow-up work.
_Avoid_: Public v1, validated assessment system

**Provisional reference label**:
A prior assessment judgment used for comparison or discrepancy review when its assessor provenance, evidence, rationale, or adjudication method is incomplete. It may guide preview evaluation but is not a correctness oracle.
_Avoid_: Gold standard, adjudicated reference
