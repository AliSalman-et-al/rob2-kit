# Agentic search ticket breakdown

Approved and published on 17 September 2026. [Specification #386](https://github.com/AliSalman-et-al/rob2-kit/issues/386) and all 18 implementation tickets carry `ready-for-agent`. All 20 native blocking relationships were verified against the approved graph.

## Approved test boundaries

- Primary: existing public MCP/application workflows, from captured Sources through discovery, context, validation, recovery and verified export.
- Supporting oracle: native SQLite semantics and exact authoritative-projection reconstruction for search localization.
- Actual installed host: visible text, images, scientific guidance, tool schemas and continuation.
- Existing independent verifier: Source/Evidence integrity and historical artifact semantics.
- Existing scientific evaluator and evaluation harness: official mappings, retained host attempts, premise-based contrasts, attribution and metrics.

These preserve the previously agreed boundaries. No test-only production API,
new general evaluation framework or second assessor is proposed.

## Published slices

1. **[Accept source-grounded limitations without receipt-exhaustion gates](https://github.com/AliSalman-et-al/rob2-kit/issues/387)**. Blocked by: none. An agent can submit an honest unresolved scientific premise and stopping rationale without exhausting irrelevant search results or substituting a convenient zero-hit receipt.
2. **[Preserve explicit search purpose and unassigned Trial discoveries](https://github.com/AliSalman-et-al/rob2-kit/issues/388)**. Blocked by: none. The agent can investigate any question during an open Trial, omit purpose when it is unknown, and recover those discoveries without assigning them to the first unfinished Domain.
3. **[Recover exact FTS match spans from native SQLite results](https://github.com/AliSalman-et-al/rob2-kit/issues/389)**. Blocked by: none. Every native FTS match can produce an exact, recoverable passage with truthful query-unit membership, or an explicit technical failure.
4. **[Add precise normalized literal search through existing tools](https://github.com/AliSalman-et-al/rob2-kit/issues/390)**. Blocked by: none. An agent can search exact normalized wording in a chosen captured scope and receive citable Source spans in deterministic location order.
5. **[Upgrade all search paths to one versioned Porter profile](https://github.com/AliSalman-et-al/rob2-kit/issues/391)**. Blocked by: T03, T04. Ordinary searches recover English word forms consistently after a safe derivative upgrade, while literal search and existing scientific records retain their meaning.
6. **[Offer bounded source-scoped spelling alternatives](https://github.com/AliSalman-et-al/rob2-kit/issues/392)**. Blocked by: T05. An agent sees a few executable alternatives for an eligible unmatched word without changing the query that ran, its ranking, or its scientific meaning.
7. **[Navigate combined documents without collapsing distinct evidence](https://github.com/AliSalman-et-al/rob2-kit/issues/393)**. Blocked by: none. The agent can follow a combined protocol's own contents and chronology leads while seeing fewer overlapping windows and retaining distinct cohorts or versions.
8. **[Resume current working context without the remaining reread gate](https://github.com/AliSalman-et-al/rob2-kit/issues/394)**. Blocked by: none. The host continues after unchanged approval, compaction, or a usage interruption from the newest valid durable progress without rebuilding completed work.
9. **[Remove residual restrictions on delivered visual methods Evidence](https://github.com/AliSalman-et-al/rob2-kit/issues/395)**. Blocked by: none. The agent can use a literal image-only methods sentence throughout assessment and export with honest host-observed provenance.
10. **[Recover surrounding Cochrane guidance without weakening question cards](https://github.com/AliSalman-et-al/rob2-kit/issues/396)**. Blocked by: none. The model receives the full applicable question rubric automatically and can inspect surrounding official guidance when the case requires it.
11. **[Qualify and repair D3 premises with recovered rubric context](https://github.com/AliSalman-et-al/rob2-kit/issues/397)**. Blocked by: T10. The host distinguishes outcome observation, analysis membership, follow-up, and missingness mechanisms while using the recovered Cochrane context.
12. **[Qualify and repair D5 chronology and eligible-alternative reasoning](https://github.com/AliSalman-et-al/rob2-kit/issues/398)**. Blocked by: T10. The host answers each D5 proposition from the approved Result, applicable plan content, timing and actual eligible alternatives.
13. **[Qualify allocation consistency and assignment-effect safety reasoning](https://github.com/AliSalman-et-al/rob2-kit/issues/399)**. Blocked by: T10. The host reuses stable allocation facts across outcomes and judges AE analysis grouping/exclusions against the approved assignment-effect target.
14. **[Qualify D4 influence distinctions under recovered guidance](https://github.com/AliSalman-et-al/rob2-kit/issues/400)**. Blocked by: T10. The host distinguishes assessor awareness, measurement susceptibility, detection opportunity and supported likely influence for the approved Result.
15. **[Distinguish scientific revision from mechanical repair at Trial review](https://github.com/AliSalman-et-al/rob2-kit/issues/401)**. Blocked by: T01. The host revisits concrete tensions before closure and the retained record distinguishes new Evidence, corrected interpretation, and mechanical repair.
16. **[Measure and preserve warm reuse for the complete Porter profile](https://github.com/AliSalman-et-al/rob2-kit/issues/402)**. Blocked by: T06. Repeated searches and continuations reuse verified profile-specific work without unnecessary indexing or catalogue reconstruction.
17. **[Prepare controlled retrieval and context comparisons in the existing evaluator](https://github.com/AliSalman-et-al/rob2-kit/issues/403)**. Blocked by: none. Maintainers can compare free search, supplied decisive Evidence, Porter-only/spelling, and context variants without mixing scientific quality with completion or selecting favorable attempts.
18. **[Qualify the integrated adaptive-search candidate in installed hosts](https://github.com/AliSalman-et-al/rob2-kit/issues/404)**. Blocked by: T02, T07, T08, T09, T11, T12, T13, T14, T15, T16, T17. The complete candidate has reproducible evidence of public correctness, actual host delivery, scientific effects and operational cost.

## Dependency rationale

- T03 is an independently verifiable localization repair under existing search semantics. T04 supplies the literal escape. T05 requires both before enabling Porter.
- T06 adds source-scoped advice against the settled Porter profile. T16 measures and verifies reuse for the complete profile, including its catalogue.
- T11-T14 exercise the recovered rubric context supplied by T10. They reuse current scientific cards and controls and change guidance only for demonstrated gaps.
- T15 consumes the revised limitation contract from T01 so mechanical receipt repair can be distinguished from scientific revision.
- T17 prepares controlled comparisons independently. T18 executes the frozen integrated candidate after every feature path is complete.
- Navigation, recovery, visual support and search-purpose work have no artificial product blockers. Shared-file ownership is coordinated during implementation.

The graph contains 18 tickets and 20 direct blocking edges. T18 lists only
the necessary terminal dependencies; earlier prerequisites are transitive.
No separate broad prefactor or temporary compatibility layer is proposed.

Independent planning review found no material scope or dependency corrections.
The graph is acyclic and the final ticket transitively requires all 17 preceding
slices. Each draft body exists and has a unique title.

## Existing coverage and incremental scope

| Existing work | Treatment in this breakdown |
| --- | --- |
| #353 and #355, open | Reuse independent investigation, factual feedback, batch operations and Source navigation. T01/T02 add limitation/purpose semantics; T03-T07 add the search and navigation changes. |
| #357 and #374, latter closed | T09 repairs the observed remaining methodological-transcription restriction; it does not recreate image delivery. |
| #358 and #377, latter closed | T10 preserves complete question cards and pagination, adding surrounding official-section recovery. |
| #359 and #375, latter closed | T08 removes the observed remaining validation reread gate and proves abrupt-interruption recovery. |
| #360 and #376, latter closed | T16 reuses the existing cache and adds actual-work proof for the new full profile. |
| #378 and #380-382, closed | T11-T14 verify the same scientific distinctions through the new context; reuse cases and repair reproduced source-to-answer gaps only. |
| #383, closed | T15 adds the limitation-contract and revision-attribution delta to existing preclosure review. |
| #361 and #384, latter closed | T17/T18 prepare and qualify this new candidate using existing infrastructure. Prior qualification cannot establish new-profile behavior. |

Existing issue states, parent issues and prior artifacts will not be modified or
closed during publication. Related references are not blocking edges. A closed
ticket is neither proof of current behavior nor permission to recreate it.

## Publication record

The user approved the test boundaries, ticket granularity and dependency graph.
Published specification #386 and implementation tickets #387-404 through the
invoked to-spec and to-tickets skills. Existing issues and parent issues were not
modified or closed.

Fresh GitHub readback verified all 19 titles, complete bodies, open states,
ready-for-agent labels, and exact native blocker sets, totaling 20 edges. Local
drafts, exact publication bodies and the resumable publication manifest are
retained. This verifies publication only; production implementation and candidate
qualification remain ticketed work.
