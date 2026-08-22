# RoB 2 Assessment

`rob2-kit` is a model-free FastMCP boundary for a structured RoB 2 assessment
workflow. The installed Codex or Claude Code host is the sole agent and model
loop. The server owns validation, deterministic RoB 2 logic, evidence records,
durable state, recovery, and report export.

## Workflow vocabulary

A **Batch** begins as one complete **Proposal** and becomes assessable only after
whole-batch approval. It contains **Trials**, each with approved immutable
**Sources**. Local ingestion captures those Sources and pairs each Trial with a
ClinicalTrials.gov registry attempt or a typed condition.

A **Captured Batch** is the canonical result of completed intake before a
Proposal exists. It binds the ordered Trial declarations, authoritative Source
inventories, registry outcomes or conditions, and their content identities so
later Model-authored drafts can refer to scientific targets without repeating
captured facts.

An **Authorized Source root** is a Trial-scoped file or directory inside the
configured workspace that a researcher or host explicitly grants to one Source
preflight. It bounds discovery and never authorizes an ambient workspace scan.

A **Candidate Source** is a file or file-level condition found under an
Authorized Source root before the intended dossier has been decided. Every
Candidate Source remains visible until it receives an explicit disposition.

A **Candidate Source identity** binds one Candidate Source to its Authorized
Source root, logical relative path, media facts, and exact bytes. It is distinct
from the identity of any Source later captured from that candidate.

A **Logical Source path** is a portable path relative to a server-issued
Authorized Source root alias. It preserves dossier provenance without exposing
or depending on an absolute filesystem path.

A **Source preflight** is the deterministic, read-only catalog of Candidate
Sources under exact Authorized Source roots. It precedes capture and does not
itself establish the intended dossier. Each exact catalog is a durable,
immutable Review record.

An **Intake plan** is the exact preflight-derived inclusion, omission, and role
decision for every Candidate Source in a Batch. A complete Intake plan has no
silently undecided Candidate Sources.

A **Dossier identity** binds one Trial's complete Candidate Source manifest,
final dispositions, accepted conditions, and Intake acknowledgment. The Batch
identity binds the ordered Trial dossier identities.

An **Intake acknowledgment** accepts one exact Intake plan for capture. The host
may acknowledge a plan that includes every Candidate Source without ambiguity or
warnings; omissions, ambiguity, and conditions require a user-mediated researcher
acknowledgment that the model cannot author for itself.

An **Intake blocker** is an unresolved intake defect that prevents acknowledgment
or capture and cannot be waived. An **Intake review condition** is a disclosed
omission, ambiguity, or limitation that a researcher may knowingly accept.

An **Omission decision** is the researcher's stable reason code and concise
rationale for excluding one Candidate Source. Mechanical file conditions remain
separate from that decision.

**Source criticality** is the researcher-authored consequence of omitting a
Candidate Source: required, expected, or optional. It is independent of Source
role and is never inferred by the server.

**Source origin** records how a Source was acquired, independently of what kind
of scientific document its role says it is.

A **Superseded Captured Batch** is an integrity-verifiable Captured Batch that a
researcher replaced through a new Source preflight before Proposal approval. It
remains historical and cannot become active again.

The host locates evidence using lexical search, exact page reading, and selective
PDF rendering. A **Domain judgment** is a versioned, evidence-grounded working
record for one Trial and result: before `finish_trial`, its active revision may be
replaced by an exact-hash correction while prior revisions remain append-only audit
entries. It binds active answers, inactive questions, attributable text or visual
evidence, rationale, reviewing actor, and UTC observation time. `finish_trial`
freezes the active revisions into an immutable AssessmentSnapshot. The server
validates judgments and derives Domain and overall judgments through the pinned
deterministic RoB 2 logic; hosts do not invent evidence or save hidden reasoning.

Each Trial is terminal exactly once: `assessed`, `needs_input`, or `failed`.
Assessment requires all five Domain checkpoints. Batch finalization records the
mixed terminal outcomes, exports verified trial and batch reports, and exposes
restart progress through `rob2://current-batch`. An unfinished active batch can be
recoverably discarded; committed report artifacts remain protected.

A **Trial disposition** is the scientific workflow state of one Trial: pending,
assessed, needs input, or failed. An assessment exists only for an assessed Trial
with an integrity-verified AssessmentSnapshot that binds all five committed Domain
checkpoints. A needs-input or failed terminal is an authoritative Canonical record
of what happened, but it is not a RoB 2 assessment.

Committed Domain checkpoints are assessment progress, not a partial assessment.
A needs-input or failed Trial remains unassessed even when it retains one or more
committed Domain checkpoints. A finalized Batch has no single scientific
disposition of its own; it retains the exact Trial dispositions and derives the
assessed, needs-input, and failed counts from them.

A **Needs-input terminal** records the specific missing scientific or researcher
input that could support a new assessment attempt. A **Failed terminal** records a
verified terminal failure that supplying missing scientific information alone
cannot resolve. Recoverable infrastructure errors, malformed calls, Repairs,
Workflow conditions, and Workflow conflicts are not failed Trial terminals. Every
problem terminal carries stable reason codes and concrete missing-input or failure
facts; host-authored prose alone cannot choose its category.

An **Assessment claim** presents a Domain judgment or overall RoB 2 judgment as a
completed scientific finding. Only a committed Canonical Domain checkpoint can
support a claim about a committed Domain judgment, and only an AssessmentSnapshot
can support a completed overall RoB 2 judgment. Before then, a host may report
Evidence-navigation facts and explicitly unresolved observations, but it cannot
claim that a Result was approved or that an assessment or review was completed.

## MCP and host boundary

The public server shape is exactly fifteen tools, in order: `preflight_sources`,
`inspect_candidate_sources`, `save_intake_plan`, `capture_batch`, `list_sources`,
`retrieve_evidence`, `render_page`, `save_proposal`, `approve_batch`,
`validate_domain_judgment`, `commit_domain_judgment`, `prepare_trial_finish`,
`finish_trial`, `finalize_batch`, and `read_record`. Its resources are compact
`rob2://current-batch`, immutable `rob2://detail/{kind}/{identity}`, captured
`rob2://registry/{trial_id}`, and binary `rob2://render/{identity}`. The portable
skills are `rob2-workflow` and `rob2-signalling`; they instruct both supported
hosts without creating a second model loop.

A **Canonical record** is the complete authoritative workflow or scientific
record retained by the server and protected by its identity and integrity rules.
A **Continuation receipt** is a compact, operation-specific projection of a
transition for the host: it carries only the status, identities, actionable
conditions, and next action needed to continue. A Continuation receipt is not a
second source of scientific or audit truth. When whole-record review is required,
the host deliberately reads the exact Canonical record instead of requesting a
verbose mutation response. It has no separate public reference; a consumed
Transition record retains the exact logical receipt needed for replay.

A **Next-call descriptor** is the typed continuation carried by every nonterminal
receipt. It names the permitted operation, supplies every server-owned argument,
identifies the remaining caller-owned inputs, and states whether host or researcher
authority is required. Next-call descriptors form an operation-discriminated union;
they never carry arbitrary argument objects. A tool continuation names one exact MCP
tool. A researcher-review continuation identifies the exact reviewed record, review
purpose, allowed elicitation or CLI method, and operation that acknowledgment will
unlock. Once acknowledged, verified current status replaces it with the exact tool
continuation carrying the Transition and Review acknowledgment references. A
terminal Trial has no Trial continuation, although its enclosing Batch may still
direct work to another pending Trial or to Batch finalization. A finalized Batch has
no Next-call descriptor. A needs-input or failed Trial cannot resume in place;
reassessment requires a new Batch after the missing input or failure has been
addressed.

A **Transition record** is a durable, immutable, noncanonical record that binds
one prepared or validated candidate to its exact operation and verified workflow
basis. A **Transition reference** is the opaque typed locator for one Transition
record. It is not an authorization capability, proof of review, scientific claim,
or audit entry. A committing operation resolves and verifies the Transition record
instead of requiring the host to reconstruct server-owned identities or resend the
candidate. An unavailable or corrupt Transition record cannot authorize a commit;
the host must prepare or validate the candidate again.

Only a pause before a delayed, reviewed, or destructive mutation creates a
Transition record. Read-only work, repairs, deterministic draft or plan revisions,
and mutations that need no later confirmation return ordinary operation-specific
receipts. A Transition reference has a typed operation and opaque deterministic
identity derived from the exact candidate, workflow basis, and review requirement.
An unchanged preparation returns the same reference. The public contract exposes
no separate continuation token, commit token, readable Transition resource, or
caller-generated idempotency key.

A live Transition record has no wall-clock expiry. It becomes invalid when its
verified workflow basis changes, its candidate is superseded, or its Batch is
discarded. Consumption retains a replay entry so an exact retry returns the same
logical receipt for the lifetime of the owning Batch records. Reuse with a
different normalized request returns a consumed-Transition mismatch and never
reveals the stored receipt.

Transition consumption authorizes the caller, resolves the record, verifies its
live workflow basis, Review acknowledgment, candidate, and dependencies, then
publishes the Canonical mutation, acknowledgment binding, and replay receipt in one
atomic operation. A stale basis permanently invalidates the Transition record. A
missing acknowledgment leaves it live. Missing or corrupt Transition content
invalidates it and requires fresh preparation.

**Caller authority** comes from the adapter's invocation context, not a
model-authored `actor` field or possession of a Transition reference. An MCP tool
invocation carries host authority. An accepted server-initiated elicitation or an
interactive local CLI review carries researcher authority. A public model-facing
call cannot claim researcher authority. A display label may support attribution but
does not establish identity.

An immutable **Detail resource** is the deliberate whole-record review path for a
specific content identity. Its copy-safe **Record reference** contains the closed
record kind, `sha256` content identity, and complete Detail URI. Callers pass the
Record reference unchanged and never parse the URI or extract its hash. Reading a
Detail resource never changes workflow state and must verify the record before
returning it. The live `rob2://current-batch` progress resource is intentionally
mutable and is not a Detail resource. A **Review record** is noncanonical data that
preserves an exact uncommitted candidate for deliberate review. When a Transition
depends on it, loss or corruption requires fresh preparation and can never
authorize a commit. The closed Detail kinds are `source_preflight`, `intake_plan`,
`captured_batch`, `proposal_review`, `approved_batch`, `domain_candidate`,
`domain_checkpoint`, `work_packet`, `trial_synthesis`, `trial_terminal`,
`assessment_snapshot`, `batch_summary`, `artifact_manifest`, `review_ack`, and
`diagnostic`. Trial, Result, Source, Evidence, Transition, and render records do not
create additional Detail kinds.

A **Validation observation** is the immutable Review record, server observation
time, and receipt produced when one exact Domain draft is successfully validated
against one exact approved state. Retrying that unchanged validation reuses the
same observation rather than creating a new scientific identity.

A **Review acknowledgment** binds an exact reviewed record to the required review
authority, review method, adapter-observed caller, and server observation time. It
records which candidate was accepted, not whether its scientific conclusions are
true. The host may acknowledge clean intake, a Domain candidate, or an assessed
Trial synthesis. Every Proposal Review requires researcher acknowledgment. Intake
omissions, ambiguity, warnings, and conditions; needs-input terminals;
researcher-authorized failed abandonment; and destructive instructions also require
researcher acknowledgment that the model cannot author for itself. A verified
server-detected failure requires no acknowledgment. Each acknowledgment is an
immutable audit record addressed by a copy-safe **Review acknowledgment reference**.
A resulting Canonical record retains the acknowledgment identity. The
acknowledgment binds the reviewed Record reference and review purpose rather than a
Transition identity, so an identical candidate prepared again for the same purpose
does not require duplicate review.

A **Review authority requirement** states whether no acknowledgment, a host
acknowledgment, or a researcher acknowledgment is required for one exact reviewed
record, and whether that requirement has been satisfied. A needs-input terminal
always requires researcher acknowledgment because it irreversibly ends the Trial.
A failed terminal requires either a verified server-detected terminal failure or
an explicit researcher-authorized abandonment; a host cannot infer failure from an
unsuccessful call. Caller identity comes from the adapter and observation time
comes from the server.

A **Validation receipt** binds one Domain draft and its resolved Canonical record
to the exact approved state against which they were checked. It permits only the
reviewed candidate to advance that Domain's active revision.

A **Model-authored draft** contains the scientific choices and prose supplied by
the host, together with only the target selection needed to apply them. It does
not repeat identities or facts the server already owns and can reconstruct.

A **Proposal draft** is the Model-authored draft of the outcome target and one
scientifically specified, text-anchored Result for each ingested Trial. The server
reconstructs its complete Trial, Source, and anchor identities.

A **Result target** is the scientific result the assessment intends to evaluate.
It states the outcome, measurement, time point, effect of interest, comparison
groups, intended analysis population, and intended effect measure.

A **Reported result** states what a Source actually reports, independently of the
Result target. It identifies the observed population, the meaning of relevant
rows and columns, labeled quantities and their denominator basis, and whether a
comparative estimate is reported or estimable.

A **Derived result** is an effect calculated from exact labeled Reported
quantities through a closed deterministic derivation chosen by the host and
recomputed by the server. It remains visibly distinct from an effect reported by
a Source. An unsupported or incomplete derivation is not estimable.

A **Reported result form** is one of a comparative effect, group-bound values, a
single-group category profile, or an unavailable result. An unavailable result
distinguishes what was not reported, not measured, or not estimable.

A **Reported quantity** is a value whose statistic, unit, group or category, and
denominator basis are explicit. Randomized enrollment, outcome-measurement
coverage, the analyzed population, and a Reported quantity's denominator remain
distinct even when their participant counts happen to match.

**Outcome-measurement coverage** records whether the requested outcome was
measured, not measured, or remains unclear for each target comparison group.

A **Result Evidence set** is the role-labeled collection of exact Evidence used
to review one Result target and Reported result. Its roles distinguish the target
basis, reported values, reported context, and population basis. One exact
selection may fulfill several roles when it contains the required context.

**Result compatibility** is the deterministic relationship between one explicit
Result target and Reported result. It is compatible, review-required, or
incompatible. Only a compatible Result may advance to Proposal approval, and
every compatible Result requires researcher confirmation of its exact review
record. A researcher-approved manifest may provide that confirmation; the host
alone cannot.

A **Result clarity declaration** is the host's explicit account of whether the
outcome definition, measurement, time point, analysis population, comparison
groups, effect measure, source-table meaning, and choice among eligible Results
are specified, unclear, or unavailable. It discloses scientific uncertainty; it
does not override deterministic Result compatibility.

A **Proposal Review record** is the immutable whole-Batch review candidate. It
contains the researcher's requested outcome statement and one ordered Result
review card per Trial. Each card binds the Result target, Reported result,
population account, Result Evidence set, Result clarity declaration, and
compatibility findings. Any changed card creates a new Proposal Review record.

An **Exact Proposal manifest** is a researcher acknowledgment prepared for an
exact Proposal Review record so its unchanged review may resume or replay without
another live interaction. It cannot approve a different Source identity, Result,
Evidence selection, compatibility finding, or newly extracted value.

A **Result clarification** is a researcher decision among server-validated,
host-authored alternatives for one exact ambiguous Result field. Each alternative
contains complete replacement values rather than a patch. Selecting a fully
displayed alternative may acknowledge the exact resulting Proposal Review record;
free text requires the host to prepare a new candidate for review.

A **Preapproval needs-input terminal** records, with researcher acknowledgment,
that no compatible assessable Result can be established for one Trial from the
available target and Sources. It is not an approved Result or a completed RoB 2
assessment.

A **Preapproval disposition** is the whole-Batch decision for one Trial: either a
researcher-confirmed compatible Result or a researcher-acknowledged Preapproval
needs-input terminal. The Batch advances atomically only when every Trial has one
disposition; only Trials with compatible Results enter Domain assessment.

A **Domain draft** is the Model-authored draft of active signaling answers,
rationales, Evidence uses, limitations, and any explicit judgment override. The
server derives the inactive partition, deterministic judgment, and complete
canonical evidence and checkpoint identities.

A **Repair result** is a compact continuation outcome bound to one exact
Model-authored draft and verified workflow basis. It reports every independently
actionable deterministic defect but creates no Canonical record, Validation
observation, or commit authority.

A **Workflow condition** is an expected noncommitting application outcome that
preserves the current phase and carries a stable code, affected scope, concise safe
message, required Review authority, and one Next-call descriptor. Its consequence
is either `blocked` or `review_required`. One condition result aggregates every
independently actionable condition observed against the same verified state while
providing one continuation for the aggregate outcome. Verbose diagnostics, when
needed, live in an immutable Detail record. Nonblocking notices accompany a
successful receipt instead. A **Workflow conflict** is a separate closed outcome
caused by a verified concurrent or superseding state change. It identifies the
expected basis, verified current Record reference, meaningful changed paths, and
one continuation without embedding or silently adopting the current record.
Repairs, Workflow conditions, and Workflow conflicts are structured application
outcomes rather than protocol failures.

An **Operation outcome** reports what one call did: success, Repair, Workflow
condition, or Workflow conflict. It is distinct from the **Workflow phase**, which
reports where the durable Batch is, and from each Trial disposition. These concepts
never share one overloaded status field. An unresolved stateful Workflow condition
remains durably projected or deterministically reconstructible until its verified
basis changes or the condition is resolved. Draft Repairs, read-only retrieval
conditions, and resolved conditions do not become global workflow state.

An **Authoritative status presentation** is the deterministic message code,
headline, and factual summary derived from verified durable state. MCP, CLI, report,
and host communication use the same presentation. A host may add explanation but
cannot rewrite its Workflow phase, Trial dispositions, assessment availability,
authority requirement, or permitted next action. The phrase "RoB 2 assessment
completed" applies only to an assessed Trial. Batch-level terminal wording says
"Batch finalized" and reports the exact Trial counts; it never turns Batch
finalization into a scientific disposition. A finalized Batch with no assessed
Trials says "Batch finalized. No RoB 2 assessments were completed." A finalized
Batch with assessed Trials states the exact assessed fraction. Repair, blocked,
review-required, and conflict wording states that the requested transition did not
occur.

**Verified current status** is the restart-safe projection derived only from
verified durable state. It reports the Workflow phase, exact Trial dispositions,
committed Domain progress, derived Trial counts, unresolved stateful Workflow
conditions, applicable Review authority requirements, one permitted Batch
continuation or none, and its Authoritative status presentation. It has no generic
status, assessment-complete, or authoritative-assessment flag from which callers
must infer those distinct facts. The closed Workflow phases are `empty`, `intake`,
`proposal`, `assessment`, `ready_to_finalize`, and `finalized`; review pauses and
blocked conditions do not create additional phases.

An **Operation outcome presentation** is the call-scoped Authoritative status
presentation for one success, Repair, Workflow condition, or Workflow conflict. It
reports the verified phase before and after the call. Verified current status does
not retain past call outcomes or reconstruct draft Repairs and read-only retrieval
conditions after restart. When a current-session operation does not advance, the
host presents both that Operation outcome presentation and Verified current status.

The server assigns preparation, review, commit, and destructive-instruction times.
The adapter supplies the authenticated or locally attributable caller. Public
model-facing inputs supply neither an actor identity nor an observation time.

A **Repair defect** identifies one independently actionable violation in a
Model-authored draft by its exact field path, stable scientific subject, expected
invariant, safe actual summary, and one mechanical next action. It is neither a
patch nor a server-authored scientific correction.

An **Evidence handle** is an immutable, transport-only locator for one
server-validated selection in an exact captured Source. It is scope-bound and
disposable, but remains resolvable across host and MCP restarts for the lifetime
of its owning Batch records. Its copy-safe **Evidence reference** contains only
the Evidence kind and identity and has no Detail URI. Canonical evidence remains
self-contained after resolution; an Evidence handle is neither a Canonical record
nor an authorization or scientific claim.

A **Verified render** is an immutable, content-addressed derivative containing
the exact PNG bytes and render metadata for one captured Source page or
normalized region. Its identity binds the Source identity, page, region,
renderer recipe, dimensions, media type, and PNG hash. It survives host and MCP
server restarts for the lifetime of its owning Batch records and is neither a
Canonical record, audit record, Evidence, nor scientific claim.

The Verified render identity is distinct from the hash of its PNG bytes. An
identical request under the same deterministic renderer recipe reuses the same
render, while a different recipe produces a different render. Every read
verifies both identities; missing or corrupt content is unavailable and is never
silently regenerated or replaced.

A **Verified render reference** is the copy-safe locator for one Verified
render. It contains the render identity and complete `rob2://render/` resource
URI. Callers pass it unchanged and never substitute the PNG hash for the render
identity. A host that cannot consume an inline image reads the exact PNG through
this resource; inability to consume either form cannot produce visual Evidence.

An **Evidence selection** is the host's deliberate choice of an exact text span
or Verified render from which the server may mint an Evidence handle. Ambiguous
text does not become a selection until one exact span is chosen. A visual
selection supplies an exact Verified render reference and host-authored
transcription; the server derives its Source, page, region, and PNG hash from the
referenced render. Resolving the selection copies the required render provenance
and PNG hash into Canonical Evidence, so later scientific and report verification
does not depend on the derivative render store.

An **Evidence retrieval batch** is one logically read-only request containing
independent lexical searches, exact text reads, or Evidence selections for one
Trial. Every operation is attributable and is evaluated against the same
verified Source state; operations cannot depend on results from elsewhere in the
same batch. Materializing a disposable Evidence handle does not change canonical
or workflow state.

A **Lexical mode** states exactly how normalized query terms compose: all terms,
an exact phrase, any term, or term prefixes. Modes never broaden automatically,
invent synonyms, or establish that scientific Evidence is absent.

A **Retrieval cursor** is an opaque continuation bound to the exact search,
verified Source state, ordering, and text projection that produced it. It shapes
transport only and never records scientific completeness or sufficiency.

A **Text projection identity** is the authoritative extractor recipe, page count,
and hash of the ordered exact page texts frozen for one Source at ingestion. The
page texts remain rebuildable derivative data; a rebuild must reproduce this
identity rather than silently adopting a different projection.

A **Verified text projection** is a rebuildable exact page-text view that matches
one Source's Text projection identity and has been checked against that Source's
captured bytes for its current use. It is neither Canonical evidence nor a second
scientific record.

A **Derivative text store** is the assessment-scoped disposable storage for
Verified text projections and their deterministic lexical index. Its loss or
replacement cannot change Canonical records, scientific state, or audit history.

A **Retrieval snapshot** is the verified identity shared by every operation in
one Evidence retrieval batch. It binds the authoritative Source inventory, exact
extracted-text projection, tokenizer configuration, and deterministic ordering;
it is not a scientific or audit record.

A **Search hit** is one matching Source page used for navigation, not scientific
Evidence. It carries a compact preview, exact match spans, any omitted-match
count, and coordinates for deliberate reading or Evidence selection.

A **Retrieval condition** is an expected, operation-attributed outcome such as no
hits or an ambiguous quote. It does not invalidate independent operations in the
same Evidence retrieval batch and carries the exact safe next action.

An **Approved work packet** is an immutable, content-addressed derivative
projection of verified approved and committed state that is sufficient to start
or resume work on one Trial Domain without replaying Canonical records or Source
text. It is neither a Canonical record nor an audit record, and it contains no
uncommitted model scratch state.

A **Portable context boundary** is the post-approval transition at which a host
may discard preapproval conversation and rehydrate assessment work from an
Approved work packet. Correctness never depends on whether a host actually resets
or compacts its context.

A **Prior Domain digest** is the bounded projection of one committed Domain that
later Domain work uses for contradiction awareness. It retains the Domain's
answers, judgments, limitations, Evidence-use claims and relationships, and exact
Evidence locators while leaving complete quotes and rationales in the Canonical
checkpoint.

A **Source alias** is a compact per-Trial label assigned in authoritative Source
order and kept stable across Approved work packets and Trial synthesis packets.
It supplements rather than replaces the Source's canonical identity.

A **Trial synthesis packet** is an immutable, content-addressed derivative
projection of all five active Domain checkpoints used for final cross-Domain
review. A reviewed synthesis hash acknowledges the exact checkpoint set reviewed;
it is not a scientific attestation or a Canonical record.

A **Text coordinate** is a zero-based, page-local Unicode-code-point offset into
the exact extracted page text. Text spans use half-open `[start, end)` intervals
throughout search, reading, Evidence selection, and canonical Evidence.

A **Search diagnostic** reports deterministic facts about one exact lexical
search and Source scope, including normalized terms and matching-page counts. It
may explain why the requested expression produced no hits, but never proposes
scientific vocabulary or claims that Evidence is absent.

The v0.2.0 candidate is created only from the clean exact final commit after the
release-manifest commit, final review, and remote 3x3 CI. Its machine-readable
contract and verification steps are in [docs/release](docs/release/README.md).
