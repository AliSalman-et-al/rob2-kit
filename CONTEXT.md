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

## MCP and host boundary

The public server shape is exactly twelve tools, in order: `ingest_batch`,
`list_sources`, `retrieve_evidence`, `render_page`, `save_proposal`,
`approve_batch`, `validate_domain_judgment`, `commit_domain_judgment`,
`finish_trial`, `finalize_batch`, `read_record`, and `discard_active_batch`.
Its resources are compact `rob2://current-batch`, immutable
`rob2://detail/{kind}/{identity}`, and captured
`rob2://registry/{trial_id}`. The portable skills are `rob2-workflow` and
`rob2-signalling`; they instruct both supported hosts without creating a second
model loop.

A **Canonical record** is the complete authoritative workflow or scientific
record retained by the server and protected by its identity and integrity rules.
A **Continuation receipt** is a compact, operation-specific projection of a
transition for the host: it carries only the status, identities, actionable
conditions, and next action needed to continue. A Continuation receipt is not a
second source of scientific or audit truth. When whole-record review is required,
the host deliberately reads the exact Canonical record instead of requesting a
verbose mutation response.

An immutable **Detail resource** is the deliberate whole-record review path for a
specific content identity. Reading one never changes workflow state and must
verify the record before returning it. The live `rob2://current-batch` progress
resource is intentionally mutable and is not a Detail resource. A **Review
record** is disposable, noncanonical data that preserves an exact uncommitted
candidate for deliberate review; its presence or absence cannot affect validation
or commit correctness.

A **Validation observation** is the immutable Review record, server observation
time, and receipt produced when one exact Domain draft is successfully validated
against one exact approved state. Retrying that unchanged validation reuses the
same observation rather than creating a new scientific identity.

A **Review acknowledgment** is the exact candidate checkpoint identity repeated
when the host commits a deliberately reviewed Validation observation. It records
which candidate was accepted, not whether its scientific conclusions are true.

A **Validation receipt** binds one Domain draft and its resolved Canonical record
to the exact approved state against which they were checked. It permits only the
reviewed candidate to advance that Domain's active revision.

A **Model-authored draft** contains the scientific choices and prose supplied by
the host, together with only the target selection needed to apply them. It does
not repeat identities or facts the server already owns and can reconstruct.

A **Proposal draft** is the Model-authored draft of the outcome target and one
scientifically specified, text-anchored Result for each ingested Trial. The server
reconstructs its complete Trial, Source, and anchor identities.

A **Domain draft** is the Model-authored draft of active signaling answers,
rationales, Evidence uses, limitations, and any explicit judgment override. The
server derives the inactive partition, deterministic judgment, and complete
canonical evidence and checkpoint identities.

A **Repair result** is a compact continuation outcome bound to one exact
Model-authored draft and verified workflow basis. It reports every independently
actionable deterministic defect but creates no Canonical record, Validation
observation, or commit authority.

A **Repair defect** identifies one independently actionable violation in a
Model-authored draft by its exact field path, stable scientific subject, expected
invariant, safe actual summary, and one mechanical next action. It is neither a
patch nor a server-authored scientific correction.

An **Evidence handle** is an immutable, transport-only locator for one
server-validated selection in an exact captured Source. It is scope-bound and
disposable, while canonical evidence remains self-contained after resolution;
it is neither a Canonical record nor an authorization or scientific claim.

An **Evidence selection** is the host's deliberate choice of an exact text span
or visual region from which the server may mint an Evidence handle. Ambiguous
text does not become a selection until one exact span is chosen; a visual
transcription remains host-authored and is bound to the verified render.

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
