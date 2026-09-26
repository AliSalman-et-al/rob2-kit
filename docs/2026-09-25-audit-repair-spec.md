# Repair audited assessment and evaluation contracts

Published as [#442](https://github.com/AliSalman-et-al/rob2-kit/issues/442).

This specification supersedes the implementation plans in #413 and #427. It
uses the 24 September audit and the expanded 25 September design as source
material. Their selected traces and isolated probes establish specific defects
and examples, but they do not establish the cause of every benchmark
disagreement or a forecast accuracy gain.

## Problem Statement

Researchers need a RoB 2 assessment for the exact approved Result, with an
auditable route from Source observations to each Domain answer. In the fresh
24 September campaign, 87 of 140 Domain judgments matched provisional labels.
An all-Low answer would match 113 of 140, so raw agreement alone would reward
an unhelpful assessment. The reference catalog has no High labels and lacks
complete question-level rationales and exact Result scope.

The audit found contracts that can change a counterevidence citation's target,
accept D2 participant-flow data that a later verifier rejects, sort observed
operations by identity rather than event order, and calculate reliability after
removing failed draws. Other receipts overstate reading or support, and an
approved Result can remain ambiguous or conflict with the reported endpoint.
Selected scientific explanations use neighboring facts in place of the fact a
question requires. These are distinct failure modes and need separate evidence
before anyone attributes a benchmark disagreement to a particular defect.

## Solution

Repair the existing model-free server and host-owned investigation workflow.
Preserve exact Source, Evidence, Result, and revision identities while making
accepted records survive independent verification. Present delivery, selection,
host inference, structural validity, and scientific review as distinct states.
Keep the exact approved Result and unresolved scope visible through Domain
assessment and Trial review. Use the existing search, working checkpoint,
scientific pack, evaluator, observation importer, and comparison harness.

First, fix referential and cross-boundary contract defects. Then improve the
current investigation view, scope-conflict handling, question-specific
reasoning, decisive-warrant review, and source navigation. Run controlled
comparisons with every attempt retained. Report agreement with provisional
labels, minority-risk detection, supported decisive claims, completion,
uncertainty, and cost separately. The resulting decision can qualify an
engineering candidate but cannot claim independently adjudicated scientific
accuracy.

## User Stories

1. As a researcher, I want each Trial assessment tied to my approved Result, so that the answer applies to the comparison and endpoint I approved.
2. As a researcher, I want requested and source-reported Results distinguished, so that a nearby estimate cannot silently replace the target.
3. As a researcher, I want an unknown or conflicting safety window shown plainly, so that a populated description is not mistaken for a specified time point.
4. As a researcher, I want material endpoint, population, data-cut, and estimate conflicts surfaced before Trial closure, so that the final artifact has coherent scope.
5. As a researcher, I want a narrow scope correction to preserve prior history, so that an approved Result is never silently rewritten.
6. As a researcher, I want selected counterevidence to retain its intended basis through save and export, so that an apparent contradiction still points to the right Source fact.
7. As a researcher, I want accepted D2 and D3 participant-flow rows to survive final verification, so that a valid assessment can be finalized.
8. As a researcher, I want analyzed, treated, observed, imputed, excluded, censored, and event counts kept distinct, so that one denominator cannot answer a different question.
9. As a researcher, I want counts bound to arm, population, endpoint, unit, and window, so that incompatible quantities are not reconciled as if they matched.
10. As a researcher, I want a planned collection period distinguished from actual outcome availability, so that a D3 answer rests on the observed record.
11. As a researcher, I want treatment cessation distinguished from loss of follow-up, so that survival missingness reflects the endpoint's actual observation.
12. As a researcher, I want administrative censoring distinguished from outcome-dependent loss, so that a routine analysis cutoff is not called missing data without evidence.
13. As a researcher, I want justified probable answers and No information both available, so that the official D3 decision path follows the evidence.
14. As a researcher, I want trial-context deviations separated from permitted treatment changes, so that D2 measures the approved effect of assignment.
15. As a researcher, I want analysis exclusions assessed for the selected outcome and event frequency, so that small percentages are not dismissed automatically.
16. As a researcher, I want D4 explanations to identify the actual endpoint component and ascertainment mechanism, so that unrelated monitoring cannot determine a mortality judgment.
17. As a researcher, I want safety detection and observation windows compared under the selected estimand, so that treatment duration alone does not settle D4.
18. As a researcher, I want D5 plan versions, dates, and eligible analyses interpreted in their source context, so that a document date does not stand in for pre-access prespecification.
19. As an assessment host, I want the active question and exact Result before general guidance, so that I can investigate the right proposition.
20. As an assessment host, I want delivered ranges, selected passages, my stated interpretation, and independent semantic review identified separately, so that I can tell what is known.
21. As an assessment host, I want notebook coverage described as notebook coverage, so that an absent note does not erase actual source delivery.
22. As an assessment host, I want a structurally valid citation described without a claim of verified scientific support, so that validation does not end investigation prematurely.
23. As an assessment host, I want supporting facts, contrary facts, unknowns, and next discriminating actions together, so that I can resume an interrupted investigation.
24. As an assessment host, I want source observations retained across unrelated Domain revisions, so that I need not reread unchanged Sources.
25. As an assessment host, I want dependent interpretations marked stale when their Result or Source changes, so that a current-looking note cannot authorize an old inference.
26. As an assessment host, I want a note edit to leave a valid scientific cursor alone, so that writing a note does not force needless reorientation.
27. As an assessment host, I want omitted context reachable through exact expansion, so that concise context does not hide decisive qualifiers.
28. As an assessment host, I want useful direct-read Evidence carried forward without unrelated search candidates, so that the next Domain can reuse the relevant observation.
29. As an assessment host, I want section and registry navigation with genuine version boundaries, so that a long combined document remains navigable.
30. As an assessment host, I want repeated headers and incidental dates kept out of prominent navigation, so that useful sections are not buried.
31. As an assessment host, I want a source with degraded table extraction still capturable and renderable, so that a readable narrative is not discarded.
32. As an assessment host, I want every source in a large search scope represented without a feedback crash, so that retrieval remains usable beyond the first displayed sources.
33. As an assessment host, I want Trial review to challenge the decisive source-to-answer inference, so that an adjacent but irrelevant fact can be corrected before closure.
34. As an assessment host, I want justified High and uncertainty paths preserved, so that agreement pressure cannot force reassurance.
35. As an evaluator, I want current tool receipts imported with repairs, scopes, handles, answer literals, and batch query children, so that the observed record matches the live interface.
36. As an evaluator, I want call start and completion order preserved, so that I can tell whether a search followed a contradiction.
37. As an evaluator, I want missing or restarted transcript events shown as gaps, so that a finalization event does not imply a complete trajectory.
38. As an evaluator, I want failed and absent planned draws included in attempted reliability, so that an assessed-only score cannot hide operational failure.
39. As an evaluator, I want infrastructure retries separated from independent draws, so that each denominator means what it says.
40. As an evaluator, I want first-attempt completion, final completion, assisted scope correction, and unscorable results reported separately, so that campaign accounting is reproducible.
41. As an evaluator, I want exact scope-matched cases separated from proxies and mismatches, so that provisional-label agreement compares the same Result.
42. As an evaluator, I want an all-Low baseline and per-class confusion reported, so that majority-class accuracy does not hide missed non-Low cases.
43. As an evaluator, I want trial-family clustering respected, so that 140 correlated Domain cells do not appear to be 140 independent trials.
44. As an evaluator, I want the current trials kept as development material, so that a held-out campaign can test generalization.
45. As an evaluator, I want controlled changes to context, retrieval, guidance, and review, so that a measured difference has an identifiable mechanism.
46. As an evaluator, I want reviewer-complete and pending cohort states to require their stated provenance, so that a hash cannot masquerade as completed adjudication.
47. As an auditor, I want the aggregation policy named separately from Domain accuracy, so that policy disagreement is not counted as a Domain assessment failure.
48. As an auditor, I want the original provisional score preserved beside later analyses, so that historical results are not silently corrected.
49. As a maintainer, I want formatting, tests, and artifact verification to run as independent gates, so that one failed formatter does not erase test diagnostics.
50. As a maintainer, I want performance changes justified by cold and warm measurements while source integrity remains checked, so that faster search does not weaken Evidence provenance.
51. As a maintainer, I want replacement tickets to identify their old counterparts, so that only fully replaced child issues are closed and no distinct work is lost.

## Implementation Decisions

- Keep one model loop in the installed host and a model-free server. Proposal Review remains the only researcher approval gate. The host owns scientific sufficiency and signalling answers; the server owns state, structural contracts, Evidence identity, deterministic evaluation, and export.
- Preserve the mapping from an input basis to a normalized basis whenever a limitation expands into context. Define the meaning of a counterpoint on the original limitation. Round-trip the target through canonical persistence and independent verification. Do not add a generic evidence graph.
- Reconcile the existing D2.3, D2.6, and D3.1 typed participant-flow contract across input, save, projection, current-record verification, historical-record verification, and host guidance. Keep descriptive arithmetic separate from risk judgment.
- Import each supported live receipt shape into one ordered observation record. Retain source-event ordinals, call identity, start and completion, parent batch, scope, repairs, literal answers, continuation, and known lineage. Use digests as identities, never as chronological sort keys. Unknown delivery, cost, comprehension, and missing phases remain unknown.
- Calculate assessed-only correctness and all-planned-draw reliability as separate metrics. Preserve failed and missing planned draws, and keep infrastructure retries distinct from independent draws.
- Require complete reviewer provenance for a completed adjudication cell and complete cells for an adjudicated manifest. This repairs record integrity without initiating a new independent review program.
- Make source capture, transport delivery, Evidence selection, host-declared support, structurally valid provenance, and independent semantic review distinct in existing status and Domain context. A note is not a read receipt, and a delivered passage is not proof of comprehension.
- Preserve the user's outcome concept, precise Result target, and precise reported result as separate meanings in the existing Result model. Mark unknown and conflicting facets explicitly. Route material late conflicts through a narrow correction; do not silently reassign an estimate.
- Separate the canonical context dependency from advisory note revision. Reuse source observations while their Source and Result identities match, and stale only dependent interpretation and drafts. Present a compact active view with exact expansion for omitted material.
- Reconcile current question cards, official guidance, and skill instructions without multiplying rulebooks. Use neutral paired examples for D1–D5; preserve legal probable, No information, Some concerns, and High paths. Do not add trial-specific or model-specific answer policy.
- Use the existing Trial review to inspect the decisive proposition, source passage, inference, counterevidence, and scope. Reopen only affected Domains. A fresh-context critic is an experimental option, not routine architecture.
- Improve section, registry-field, and version navigation while preserving exact locators. Fix large-scope feedback and resource-release defects. Profile source verification, candidate writes, rank computation, and rendering before changing performance-sensitive code; preserve tamper detection.
- Reuse the current evaluation and comparison machinery. Freeze exact Results, Source and projection identities, prompts, tools, host and model settings, effort, budgets, attempts, retry selection, and scorer versions. Keep the assessment process unable to read reference labels.
- Keep the accepted deterministic overall aggregation rule under ADR 0035. Name and version it in reports, and evaluate its disagreement with the full conditional scientific policy separately. Changing it requires a later explicit decision.
- Supersede #413 and #427 with this program while leaving those parent issues unchanged. Close only child tickets fully replaced after their replacement tickets are published and linked; leave distinct work open.

## Testing Decisions

- Test observable behavior across the highest existing seams. A useful test fails for a changed source-to-answer relationship, lost artifact meaning, wrong denominator, or invalid lifecycle, rather than a private helper refactor.
- Exercise assessment, Evidence, status, review, closure, and export through the public application/MCP workflow. Extend existing lifecycle, Evidence, working-checkpoint, Result, and bundle-verifier tests.
- Exercise official answer activation and Domain/overall mapping through the pure evaluator. Preserve official decision-table outputs unless a separately verified transcription error is found.
- Exercise benchmark preparation, import, attempt accounting, scope matching, reliability, and scoring through commands and immutable artifacts. Extend existing observation-import, comparison, cohort, and evaluation-harness tests.
- Use installed-host transcripts to check structured and text receipt delivery, image visibility, continuation, compaction, restart, and actual review behavior. Server output alone does not prove that a host saw or retained it.
- Include cross-boundary round trips for normalized counterevidence and D2/D3 participant flow; wrong-Result conflicts; note edits versus Source/Result changes; ordered and incomplete transcript events; failed planned draws; pending versus completed cohort states; and a search scope larger than the displayed source prefix.
- Use paired fictional scientific cases that alter one premise, including analyzed versus observed, treatment stopping versus lost follow-up, mortality versus toxicity monitoring, common treatment-emergent versus fixed-horizon safety results, and dated pre-access versus ambiguous plans. Preserve positive controls and genuine High cases.
- Compare baseline and candidate on trial-separated held-out material and at least two model families or materially different supported hosts. Report domain and class confusion, non-Low and High support, decisive-claim validity, scope correctness, completion, all-attempt reliability, repairs, calls, latency, cost, and uncertainty. Treat the current ten trials as development material.
- Run formatting, type checks, the relevant suite, independent artifact verification, and installed-host checks before an integrated promote-or-hold decision. Record missing checks as missing, not passing.

## Out of Scope

- New independent scientific adjudication, a researcher Domain-answer override, or a second routine approval gate.
- A claim of independently validated scientific accuracy from provisional labels or autonomous review.
- Changing the current deterministic overall aggregation rule during this program.
- Mandatory multi-agent assessment, a second scientific model, a semantic entailment judge, or compulsory private reasoning traces.
- Vector retrieval, neural reranking, OCR-first capture, routine fresh-context critique, and atomic compound write tools without a later measured need.
- Fixed search quotas, trial-name rules, model-vendor rules, forced Low answers, or altering the official D3 decision table to match label frequencies.
- Rebuilding existing search, working checkpoint, Evidence, comparison, or adjudication machinery as parallel systems.
- Treating every audit hypothesis as a proven benchmark cause, or requiring a complete historical PDF and JSONL audit before confirmed repairs begin.

## Further Notes

The fresh campaign has 28 scored Trial–outcome cases from ten Trials and 87/140
exact Domain matches. D2–D4 account for 43 of 53 mismatches. These are
descriptive comparisons to provisional labels, not independently adjudicated
accuracy. The all-Low 113/140 baseline makes 80% a diagnostic rather than a
standalone release gate. A candidate must improve or preserve supported
reasoning and minority-risk detection while reporting regressions and
uncertainty. No particular gain is promised.

Some audit findings are reproduced transformations, others are static contract
findings, observed weak warrants, or hypotheses. Tests can establish repaired
contracts. Controlled host runs are needed to attribute changes in scientific
behavior. The accepted ADR on overall aggregation and existing domain glossary
remain authoritative for this program.
