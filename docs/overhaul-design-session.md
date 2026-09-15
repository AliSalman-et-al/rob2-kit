# Overhaul design session

The 2026-09-14 grilling session examines `rob2-kit-final-overhaul-plan.md`.
The plan is proposed design, not implementation authorization. Repository HEAD
at the start is `862353658d54f2b115d6d081134f403326de6d8f`.

## Accepted decisions

- Engineering release requires demonstrated improvement on identified
  evidence-handling failures, no material scientific regression, and independently
  verifiable outputs. Cost reduction is a separate objective. Exact acceptance
  measures remain to be settled.
- Retain one host-controlled agent, a deterministic model-free server, and the
  individually randomized parallel-group assignment-effect scope.
- Separate engineering release from scientific qualification. Behavioral and
  integrity checks support engineering release; claims of improved scientific
  accuracy require result-specific expert evaluation.
- Use `eval/reference` for testing where its contents support the intended check.
  Inspection found real-source replay inputs and provisional domain labels,
  but no result-specific evidence-linked adjudication suitable for accuracy claims.
- Retain one-arm descriptive data as observations. Domain assessment requires a
  reported comparative estimate or sufficient quantities from both groups;
  otherwise retain an unassessed result identifying missing information.
- The host performs final trial review and explicitly closes the trial.
  Researcher approval remains at result selection; later human adjudication
  is separately attributable. This changes automatic fifth-domain finality.
- Discovering an incorrect approved result stops that assessment and requires a
  replacement proposal with renewed researcher approval. Preserve prior records
  and require fresh domain assessments for the replacement result.

- Retain the postapproval restriction on researcher scientific feedback,
  including evidence pointers. Handle researcher feedback after the run as
  separately attributed review. Align the assessment skill with ADR 0030's
  minimal `Continue.` policy. Autonomous evidence discovery and self-correction
  remain allowed. Server revision checks establish lineage, not absence of
  conversational coaching.
- Freeze the document dossier after intake. The agent may fetch information
  from ClinicalTrials.gov, but may not fetch other new documents. Registry
  capture timing, versioning, and invalidation remain to be settled.
- Allow visual transcriptions to support methodological claims with exact
  source, page, region, and render provenance. Mark them as host-observed,
  not machine-verified text; require actual image delivery to the host.
- An unresolved answer identifies the missing fact, what inspected evidence
  establishes, and why further available investigation is unlikely to resolve
  it. The server validates structure and references; evaluation assesses
  adequacy. Require neither fixed search counts nor a ritual search receipt.
- Use reference dossiers for engineering replay and disagreement discovery;
  repair stale catalog paths during implementation and add targeted challenge
  cases for coverage gaps. Provisional-label agreement remains descriptive
  pending result-specific adjudication.
- Compare updated assessments primarily against D1-D5 reference labels using
  exact Low / Some Concerns / High agreement and binary Low versus
  Some Concerns / High agreement. Overall-label agreement is secondary because
  aggregation criteria can differ. Detailed metrics and handling of unassessed
  or result-mismatched rows remain to be settled.
- Registry access should follow existing intake: capture ClinicalTrials.gov
  information before Proposal construction when `sources.toml` identifies an
  NCT record. Inspect current implementation before changing this behavior.
  Accepted Q12 recommends captured structured registry information reused for
  the assessment, with retrieval/version metadata and no linked-document fetches.
- Report per-domain and pooled three-category agreement/confusion matrices,
  binary agreement and directional disagreements, counts and percentages, and
  trial-clustered uncertainty. Reference-High performance is unmeasurable where
  the reference corpus contains no High labels.
- Retain all attempts. Report completion over all requested cases, agreement
  among completed scope-comparable cases, and matching domain outputs over all
  expected domain outputs. Show scope-uncertain comparisons separately.
- Calculate evaluation metrics posthoc from run logs and recorded outputs.
  Run normal uncoached assessments with minimal realistic prompts, for example
  `/rob2-assess Assess risk of bias for Progression Free Survival in CHAARTED.`
- For a Progression Free Survival benchmark, approve the definition or closest
  concept reported in each trial's abstract; skip trials without that outcome.
  Preserve screening and approval decisions for posthoc scope assessment.
- Use Codex CLI with Luna at medium reasoning effort, isolated environments,
  and JSONL logging. Codex alone is required for qualification.
- Run trials in batches to the saved-Proposal turn boundary, then review and
  approve proposals in batches, requesting scope corrections where needed.
  Resume assessments in parallel with no answer coaching. Analyze agreement
  and failure causes only after the runs finish.
- Benchmark eligibility requires the outcome or approved closest concept in the
  abstract. Record exclusions even if the full paper reports an absent abstract
  outcome. Screen without reference labels and report scope uncertainty.
- Reuse existing baselines under `C:/Users/Ali-Salman/Documents/`:
  `rob2-benchmark-2026-09-14`, `rob2-benchmark-ae-2026-09-14`, and
  `rob2-benchmark-os-2026-09-14`. Inspect their configuration and captured evidence
  for comparability instead of rerunning the current kit. Keep labels and prior
  outputs inaccessible to updated assessment agents.
- Start with one updated run per eligible trial. Preserve all failures; retry
  only identifiable infrastructure failures, retaining original attempts.
  Later reliability studies repeat the entire eligible set a fixed number of
  times rather than selectively rerunning disagreements.
- Final review binds the approved result and exact five active checkpoints.
  Domain corrections require refreshed review; searches alone do not.
  Trial closure makes the assessment immutable.
- Draft validation depends on answers, rationale, evidence basis, counterevidence,
  scientific pack, approved result, and same-domain predecessor. Changes to
  these require revalidation; searches, reads, pagination, and unrelated domain
  saves do not. Retain validation followed by exact-receipt commitment.
- Ship one optional replaceable agent-authored working checkpoint per active
  result for unfinished drafts, source-linked notes, open questions, and next
  action. It has no scientific authority; its loss cannot affect committed
  assessments. It is neither a transcript nor a second history system.
- Require complete delivery of approved result and applicable question semantics
  and guidance before domain commitment, with bounded continuation. Search
  candidates remain optional and reachable on demand. Delivery receipts establish
  delivery, never comprehension.
- For controlled updated comparisons, replay baseline captured registry responses
  through intake and record replay provenance. Review normally generated proposals
  against the same abstract-based scopes. Explicitly report baseline cases made
  ineligible by the stricter result contract.
- Make a clean public-contract cutover: readable official answer enums,
  `validate_*` names replacing the two `reason_*` validators, and explicit trial
  review/closure. Update schemas, CLI, skill, examples, and tests together.
  Preserve historical artifact verification; reject unsupported active workspace
  formats with a clear recovery route.
- Ship exact reusable passage handles, identical-window deduplication, lossless
  expansion, and explicitly linked multi-span evidence for continued tables.
  Preserve each span's coordinates; host interpretation establishes the premise.
  The server neither fabricates joined quotations nor infers table continuity.
- Engineering release is blocked by broken provenance or deterministic judgments,
  required Codex workflow failures, unresolved targeted challenge failures, or
  demonstrated new scientific errors attributable to the overhaul. Investigate
  lower provisional-label agreement rather than treating it as automatic proof
  of regression. Review completion, agreement, cost, and failure explanations.
- Product changes must generalize across datasets and host models. Luna Medium
  and `eval/reference` are evaluation configurations, not product assumptions.
  Do not add trial-specific heuristics, reference-label tuning, or Luna-specific
  scientific behavior.
- Generalization checks use fictional cases, meaning-preserving terminology,
  layout and evidence-location variations, and meaning-changing negation or
  population changes. Fix general mechanisms. Official Cochrane guidance may
  be encoded with versioning and attribution; model or reference-label tuning
  is excluded. Luna-only runs do not establish cross-model reliability.
- Preserve explicit lexical search modes; add factual diagnostics, independent
  query batching and direct navigation. Improve presentation and cached retrieval
  before changing ranking. User identifies current ranking as BM25 with
  source-role tie breaks. Inspection confirms BM25 first, then source order
  and page; source order uses role priority, logical path, and source ID.
  Passage clusters inherit page rank; no round-robin diversification occurs.
- Orient on the main article before proposal selection using bounded reads.
  Preserve unread ranges and recover missing context. Work with native harness
  auto-compaction and support continuation after delayed approval. Durable
  trial notes versus mandatory postapproval rereading remains to be settled.
- Operational interruption preserves resumable state and remains explicitly
  incomplete. Timeouts, exhausted usage, or failed image delivery do not become
  scientific conclusions or completed assessments; retain cause in benchmark logs.
- Reuse the agreed working checkpoint for preapproval source-linked observations,
  terminology, unresolved questions and unread ranges. Bind notes to captured
  sources and proposed result, retaining applicable notes after approval.
  Separate observations from provisional interpretations; exact passages remain
  evidence authority.
- Use native harness auto-compaction. On continuation recover server status and
  durable notes, then reread missing or uncertain passages. Repeat orientation
  when useful notes are absent. Elapsed time or a cold prompt cache alone does
  not require a full reread. Test delayed approval and compaction recovery without
  depending on Codex-specific memory internals.
- Put deterministic Cochrane activation/judgment rules in the scientific pack
  and evaluator; present interpretive guidance in question context and skill.
  Preserve official wording, version and attribution separately from project
  explanations. Test encoded rules against official logic; qualitative guidance
  does not justify invented numerical thresholds.
- Reuse and extend useful lessons and sound decisions already implemented.
  Change existing machinery only where the agreed requirements or demonstrated
  defects justify it; the overhaul is not a rewrite for its own sake.

- Close each Trial, including its five-Domain review when assessed, before
  advancing to the next Trial in a Batch. Confirmed unassessed terminals also
  complete that Trial. Benchmark parallelism uses separate isolated runs.
- Human scientific authority is limited to defining and approving the Result
  proposal. No human answer coaching or new human judgment override is added.
- Proceed with spec and ticket synthesis using the requested to-spec and
  to-tickets skills. Implementation follows verified slices and preserves useful
  existing behavior.

## Handoff

Design interview decisions, testing seams and ticket breakdown were approved.
The spec is GitHub issue #349; implementation tickets are #350 through #361.
Implementation and benchmark runs have not begun.

## Session constraint

Stay within the current five-hour usage allowance. Check usage between rounds
and stop with a reserve; preserve unresolved decisions for continuation.
