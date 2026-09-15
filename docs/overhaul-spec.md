# Adaptive evidence-grounded assessment overhaul

## Problem Statement

An assessment agent can locate a relevant page yet miss its qualification,
lose useful orientation after approval, or be prevented from correcting earlier
work when the fifth Domain save freezes a Trial. Coupled workflow revisions,
prescriptive search recovery and opaque answer options add mechanical work
without establishing scientific correctness. Evaluation must distinguish these
failures from interpretation errors and provisional-reference disagreements.

## Solution

Retain one host-controlled agent and a deterministic model-free server. Let the
agent alternate evidence discovery, interpretation, drafting and correction until
it explicitly reviews and closes one Trial. Preserve exact evidence, deterministic
judgments and independently verifiable history. Extend sound existing decisions
rather than rebuilding them. The supported scientific scope remains individually
randomized parallel-group trials and the effect of assignment.

## User Stories

1. As a researcher, I want to define and approve a specific Result so that the correct outcome is assessed.
2. As a researcher, I want unsupported or insufficient Results reported explicitly so that descriptive data are not mistaken for comparative assessments.
3. As an agent, I want the complete captured dossier inventory so that I can see missing and unreadable material.
4. As an agent, I want captured ClinicalTrials.gov information so that registry evidence is available alongside local documents.
5. As an agent, I want source-linked orientation notes so that delayed approval does not lose useful trial terminology.
6. As an agent, I want factual search diagnostics so that I can choose the next query without compulsory search rituals.
7. As an agent, I want direct document navigation so that I can inspect sections without first producing a failed query.
8. As an agent, I want independent query batches so that known searches require fewer round trips.
9. As an agent, I want exact reusable passage handles so that useful hits can support a draft without coordinate copying.
10. As an agent, I want lossless passage expansion so that qualifications and table footnotes remain available.
11. As an agent, I want explicitly linked evidence spans so that continued tables retain their separate provenance.
12. As an agent, I want verified image delivery so that visual methodological evidence can be cited honestly.
13. As an agent, I want readable official answers so that representation does not obscure polarity or certainty.
14. As an agent, I want complete question guidance so that I apply the scientific pack correctly.
15. As an agent, I want to inspect any Domain and return to evidence while drafting so that later questions can inform investigation.
16. As an agent, I want unrelated searches to preserve valid drafts so that progress does not create unnecessary repairs.
17. As an agent, I want to revise earlier Domains before closure so that newly discovered evidence can correct the assessment.
18. As an agent, I want native compaction and restart recovery so that long assessments remain resumable.
19. As a researcher, I want one Trial closed before the next begins so that evidence and working context stay scoped.
20. As an auditor, I want exact review and revision identities so that completed records can be independently checked.
21. As an evaluator, I want isolated uncoached runs so that results reflect ordinary kit performance.
22. As an evaluator, I want posthoc per-Domain agreement and failure analysis so that completion, reference agreement and scientific quality remain distinguishable.
23. As a maintainer, I want generalized model-agnostic fixes so that improvements extend beyond one corpus or model.

## Implementation Decisions

- Preserve existing canonical/derivative separation, exact evidence identity,
  immutable checkpoint history, idempotency, independent verification and native
  host recovery. Use concrete typed records and functions; add no generic agent
  framework or second scientific authority.
- A Result records endpoint definition, measurement, timing, groups, assignment
  effect, randomized/subgroup scope, reported analysis population, numerical
  result and supporting source context. Require a reported comparative estimate
  or sufficient quantities from both groups for assessment. Preserve one-arm
  observations as unassessed when information is insufficient.
- Researcher authority is Result definition and Proposal approval only. Preserve
  the postapproval minimal continuation policy, including exclusion of researcher
  evidence pointers. Autonomous corrections remain allowed. Align the skill and
  existing authority ADR; lineage cannot prove absence of conversational coaching.
- A discovered error in approved Result scope stops that assessment and requires
  a replacement Proposal and renewed approval with fresh Domain assessments.
  Preserve prior records. Later human review is separately attributable and does
  not revise autonomous answers through conversation.
- Capture local Sources and the specified NCT registry response during intake.
  Preserve hashes and retrieval/version metadata and reuse captured content.
  No other new documents, linked PDFs or external-site retrieval is permitted.
  Preserve visible typed registry failure conditions without a new approval gate.
- Retain explicit lexical modes and existing BM25-first ranking with deterministic
  source-order/page tie breaks. Add no-hit feedback for every query shape,
  conditional navigation options, independent bounded query batching, stable
  continuation and document navigation. No silent query changes or search quotas.
- Improve windows before ranking: exact deduplication, boundary expansion,
  explicit multi-span bundles and lossless long-line recovery. Evidence identity
  is independent of the discovery query. Keep span coordinates separate; the
  server neither invents continuous quotations nor decides scientific continuity.
- Permit host-observed visual transcription for methodological claims with source,
  page, region and render provenance. Require actual image delivery. Do not
  represent it as machine-verified text or silently introduce OCR authority.
- Preserve official Cochrane wording, version and attribution. Encode deterministic
  rules in the scientific pack/evaluator; expose interpretive guidance at the
  question. Keep project guidance separate. Avoid invented thresholds. Reuse
  existing question-specific comparisons and arithmetic without causal inference.
- Replace opaque answer selection with one question-scoped official answer enum.
  Reject illegal values and stale scope. Repairs preserve submitted polarity.
  Rename the two reason validators to validate operations during clean cutover.
  Preserve validation then exact-receipt saving and existing supported scientific
  inputs; add no human override mechanism.
- Validation depends on the draft, approved Result, scientific pack, relevant
  evidence and same-Domain predecessor. Searches, reads, cursor changes and
  unrelated Domain saves do not invalidate it. Apply the same protections through
  MCP and CLI. Preserve atomic commitment and identical retry behavior.
- Deliver complete required Result/question context using bounded continuation.
  Keep unselected candidates optional and available on demand. Frozen views and
  short cursors remain usable at an unchanged scientific basis. Measure serialized
  response size, including metadata and multibyte content. Deliver one authoritative
  scientific view through supported host transport.
- Extend one replaceable working checkpoint per active Result to preapproval
  orientation notes, unread ranges, open questions and unfinished drafts. Bind to
  Sources and proposed/approved Result. Separate observations from interpretations.
  Notes are not canonical scientific authority or private reasoning transcripts.
  Recover status and notes after compaction; reread uncertain context, or repeat
  orientation when notes are absent. Cold caches alone do not require rereading.
- All five Domain commits make a Trial reviewable, not terminal. Review binds the
  exact Result and checkpoint set; correction requires refreshed review. Searches
  alone do not invalidate review. Close assessed or explicitly unassessed Trials
  through distinct typed outcomes. Finish one Trial before advancing within a
  Batch. Closure is immutable; Batch export packages terminal records.
- Reuse warm search rankings before rebuilding retrieval, cache misses, group
  writes and verification, and avoid repeated rank scans. Preserve scoped BM25
  semantics, authoritative source checks and independently verifiable exports.
- Update schemas, adapters, skill, examples and meaningful tests together. Reject
  unsupported active runtime formats without migrating scientific state silently;
  preserve historical verification. Amend superseded ADR decisions explicitly.

## Testing Decisions

- Prefer the existing public application/MCP contract as the primary behavioral
  seam, exercised through normal CLI/host operations where delivery or approval
  matters. Use independent artifact verification for persisted outputs and existing
  pure scientific evaluator tests for official decision rules. Avoid new test-only
  abstractions and tests that merely repeat implementation.
- Cover Result eligibility/replacement, authority, stale commitments, idempotency,
  lookahead, continued investigation, final review refresh, per-Trial closure,
  evidence provenance, source isolation, lossless delivery and restart/compaction.
- Test fictional and perturbed cases with absent keywords, deep evidence, misleading
  first hits, continued tables, visual contradictions, missing plans, changed
  negation/population and answers revised after further reading. Accept different
  defensible tool trajectories. Do not encode trial-specific or Luna-specific rules.
- Qualify Codex CLI with Luna Medium using isolated workspaces and JSONL logs.
  Permit normal native auto-compaction. Use minimal outcome/trial prompts. Run
  proposal waves, review Result scopes, then resume isolated trials in parallel
  with only minimal continuation. No answer coaching, labels or prior outputs
  enter the assessment environment. Preserve configuration/build/skill/source
  manifests and all attempts. Freeze the build for a scored wave.
- Reuse the existing PFS, AE and OS baseline runs, captured registry bytes and
  approved abstract-based scopes. Do not rerun the baseline. Screen eligibility
  without labels; record excluded, ineligible and scope-uncertain cases. Replay
  registry bytes explicitly for controlled comparison while preserving normal
  intake behavior outside evaluation. Audit traces for coaching posthoc.
- Start with one updated run per eligible Trial/outcome. Retain failed attempts;
  retry only identifiable infrastructure failures. A later reliability study uses
  a fixed repeat count across the complete eligible set.
- Calculate metrics posthoc from logs and recorded outputs: per-Domain and pooled
  D1-D5 three-category agreement/confusion matrices, binary Low versus Some
  Concerns/High agreement and both disagreement directions, counts, completion,
  matching outputs over all expected outputs, and trial-clustered uncertainty.
  Overall agreement is secondary. Show scope-uncertain comparisons separately.
  The provisional references lack High cases and adjudicated result-specific
  evidence; agreement is not clinical accuracy.
- Analyze why failures occurred, distinguishing evidence discovery, presentation,
  interpretation, scope, delivery and infrastructure. Report cost and reliability
  separately. Do not selectively rerun disagreements or tune answers to labels.
- Block engineering release on integrity/judgment defects, required Codex workflow
  failures, unresolved targeted challenges or demonstrated new scientific errors.
  Investigate agreement drops. Improved scientific accuracy claims require
  result-specific expert adjudication; Luna qualification is not cross-model proof.

## Out of Scope

Other trial designs/effects, new human answer authority, new judgment overrides,
external document fetching, vector databases, neural rerankers, semantic query
expansion, model-specific scientific policy, multi-agent assessment, fine-tuning,
self-evolving memory, generic orchestration and mandatory Claude qualification.
Implementation and paid benchmark execution are separate from this spec handoff.

## Further Notes

Baseline: commit 862353658d54f2b115d6d081134f403326de6d8f. Existing reports
contain 8 PFS, 10 AE and 9 OS completed assessments; 8 AE cases have reference
labels. Metadata inspection found Luna Medium and common captured source hashes.
Full trace review and fresh artifact verification remain evaluation work.
The local session record retains baseline locations and accepted decisions.
