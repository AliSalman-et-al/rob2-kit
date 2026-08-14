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

The public server shape is eleven tools for proposal, ingestion, Source access,
approval, Domain judgment, Trial completion, finalization, and recovery; and three
resources for current-batch progress, pinned Domain guidance, and captured registry
records. The portable skills are `rob2-workflow` and `rob2-signalling`; they
instruct both supported hosts without creating a second model loop.

The current frozen candidate identity is the annotated release-candidate tag
recorded by the Git and release process. Its machine-readable contract and
verification steps are in [docs/release](docs/release/README.md). Claude Code has
accepted real-host evidence. Codex CLI 0.147.0 on Windows is an unaccepted known
MCP limitation, recorded in
[issue #193 acceptance evidence](docs/acceptance/issue-193.md).
