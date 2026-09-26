# Make post-benchmark investigation and scoring scientifically faithful

Approved on 2026-09-22. This specification follows the 22 September accuracy
audit and the confirmed design session. It is a successor to the implemented
accuracy and agentic-search programs, not authorization to recreate their
capabilities.

## Problem Statement

Researchers need rob2-kit to produce scientifically defensible RoB 2
assessments for the exact comparative Result they approved. The current system
can preserve exact Evidence, pass structural validation, produce a verified
artifact, and still fall short in three ways: the host may stop before pursuing
a material uncertainty, the host may apply retrieved facts to the wrong
signaling proposition, or the benchmark may score a verified artifact that is
not demonstrably the intended Result.

The 22 September benchmark contains 24 scored Trial–outcome cases and 120 Domain
judgments. It agrees with the provisional catalog on 77 Domain judgments, but
the catalog is coarse, result-ambiguous, and contains no High labels. Some
disagreements are plausibly defensible; some matching labels have weak premises.
Raw agreement therefore cannot identify scientific error or serve as ground
truth.

Much of the required architecture already exists: one host-owned ReAct loop, a
model-free server, premise records, working checkpoints, exact Evidence,
recoverable lexical search, question cards, deterministic RoB 2 evaluation,
Trial review, immutable artifacts, observation import, and qualification
manifests. The residual problem is that workflow permission remains more
salient than scientific readiness, still-valid observations are hidden after
unrelated Domain progress, semantic review does not consistently foreground
the facts-to-warrant link, and the older benchmark scripts do not bind scoring
to a sufficiently exact Result and run identity.

## Solution

Make the current host-owned investigation loop premise-driven at each decision
point without adding another scientific authority. Present the active
proposition, inspected Evidence, counterevidence, unresolved material
information, and available recovery actions beside—but distinct from—the next
permitted write. Preserve source observations across unrelated Domain changes
while invalidating dependent inferences and drafts. Use the existing mandatory
Trial review to expose unsupported links, scope conflicts, and uninvestigated
routes before closure.

Strengthen benchmark preparation, execution, and scoring around one immutable
run record. Bind every scored artifact to the exact expected Result and declared
attempt-selection policy. Repair session recovery and make host/model settings
explicit. Keep every failed, resumed, and historical attempt visible.

Qualify the successor through public-contract tests, paired premise-changing
controls, Trial-held-out campaigns, and at least two model families or
materially different supported hosts. Because the program adds no independent
human adjudication, report source-grounded behavior and provisional agreement
without claiming independently validated scientific accuracy.

## User Stories

1. As a researcher, I want every assessment bound to my approved Result, so that the kit answers the question I authorized.
2. As a researcher, I want the Result’s comparison, endpoint, population, window, estimate, and precision preserved together, so that nearby results are not silently substituted.
3. As a researcher, I want a verified artifact for the wrong Result rejected, so that cryptographic validity is not mistaken for benchmark eligibility.
4. As a researcher, I want defensible uncertainty preserved, so that missing information does not become either automatic reassurance or automatic concern.
5. As a researcher, I want ordinary post-protocol care distinguished from a trial-context deviation, so that permitted treatment changes do not answer D2.3 by themselves.
6. As a researcher, I want randomized, eligible, treated, observed, analyzed, and excluded populations reconciled, so that unlike denominators do not support the same premise.
7. As a researcher, I want event counts distinguished from outcome availability, so that occurrence is not mistaken for ascertainment.
8. As a researcher, I want administrative censoring distinguished from loss of outcome follow-up, so that survival analyses are assessed on their documented terms.
9. As a researcher, I want missingness possibility distinguished from likely outcome dependence, so that one uncertainty does not answer several D3 questions.
10. As a researcher, I want assessor awareness distinguished from susceptibility and likely influence, so that D4 answers the proposition actually asked.
11. As a researcher, I want measurement suitability and differential ascertainment considered separately, so that an objective endpoint does not hide unequal detection opportunities.
12. As a researcher, I want plan existence distinguished from plan applicability and chronology, so that D5 does not treat retrieval metadata as prespecification.
13. As a researcher, I want eligible measurements distinguished from eligible analyses, so that multiplicity alone does not prove result-based selection.
14. As an agent, I want the active signaling proposition presented before general guidance, so that the decision target remains salient.
15. As an agent, I want the exact approved Result beside every material premise, so that retrieved facts remain scope-matched.
16. As an agent, I want supporting Evidence and counterevidence presented separately, so that contradictions remain visible.
17. As an agent, I want observed facts separated from my inference, so that a plausible interpretation cannot masquerade as a Source claim.
18. As an agent, I want the unresolved component stated explicitly, so that my next action can discriminate between real alternatives.
19. As an agent, I want source coverage and unread routes visible, so that a completed main-report pass does not imply dossier exhaustion.
20. As an agent, I want search misses described factually, so that no lexical hit does not become scientific absence.
21. As an agent, I want source roles treated as routing hints, so that a protocol label does not prove document contents or precedence.
22. As an agent, I want embedded versions, amendments, dates, and logical sections navigable, so that the applicable plan can be identified without guesswork.
23. As an agent, I want rendered pages available when layout carries meaning, so that tables, footnotes, and image-only methods remain assessable.
24. As an agent, I want scientific readiness distinguished from workflow permission, so that a valid draft does not look independently verified.
25. As an agent, I want save, search, read, revise, and accept-limitation choices visible after validation, so that validation does not prematurely end investigation.
26. As an agent, I want no fixed query quota, so that simple cases remain efficient and difficult cases can continue when another action is discriminating.
27. As an agent, I want a scientific limitation to name its unresolved premise and stopping rationale, so that bounded uncertainty remains auditable.
28. As an agent, I want still-valid source observations to survive unrelated Domain commits, so that progress does not force duplicate reading.
29. As an agent, I want stale inferences and drafts clearly marked after their dependencies change, so that old reasoning cannot outrank current Canonical state.
30. As an agent, I want a Source or Result change to invalidate affected notes, so that reuse cannot cross a scientific scope boundary.
31. As an agent, I want focused context ordered around the current decision, so that repeated general material does not displace decisive Evidence.
32. As an agent, I want every omitted passage exactly recoverable, so that concise context never becomes a lossy authority.
33. As an agent, I want short proposition-specific distinctions from one maintained source, so that guidance stays consistent across cards, schemas, and skills.
34. As an agent, I want paired neutral examples, so that I can distinguish neighboring propositions without learning Trial-specific label rules.
35. As an agent, I want quantitative helpers to expose verified bounds without choosing a risk label, so that arithmetic informs rather than replaces scientific judgment.
36. As an agent, I want Trial review to reconstruct each facts-to-warrant-to-answer chain, so that citation presence is not mistaken for entailment.
37. As an agent, I want Trial review to show scope, population, chronology, and contradiction conflicts, so that I can reopen the affected Domain before closure.
38. As an agent, I want review to remain in the same host, so that the workflow does not add another model authority or a duplicate full assessment.
39. As an auditor, I want the permitted mutation and scientific-sufficiency statement separate, so that workflow legality cannot be read as semantic approval.
40. As an auditor, I want host-asserted support identified as an assertion, so that provenance validation is not overstated.
41. As an auditor, I want every revision linked to changed Evidence or self-correction, so that scientific history remains attributable.
42. As an evaluator, I want one immutable run record, so that preparation, execution, verification, and scoring refer to the same campaign.
43. As an evaluator, I want model and effort settings owned by the manifest, so that a run can be reproduced without inspecting launcher defaults.
44. As an evaluator, I want command-line overrides recorded, so that convenience cannot silently change a condition.
45. As an evaluator, I want current and supported legacy session events recovered correctly, so that resumptions continue the intended host session.
46. As an evaluator, I want missing tool inventory diagnosed before another resume attempt, so that repeated blind continuation cannot masquerade as recovery.
47. As an evaluator, I want every attempt and resumption retained, so that operational failures remain in the denominator.
48. As an evaluator, I want the attempt-selection policy declared before execution, so that the best-scoring retry cannot be chosen afterward.
49. As an evaluator, I want infrastructure and scientific outcomes classified separately, so that transport failure is not a scientific judgment.
50. As an evaluator, I want historical mismatched artifacts retained but unscored, so that stronger future validation does not rewrite history.
51. As an evaluator, I want Trial-held-out conditions, so that outcomes from one RCT cannot leak across training and evaluation partitions.
52. As an evaluator, I want at least two model families or materially different supported hosts, so that a local interaction quirk is not reported as a general improvement.
53. As an evaluator, I want paired controls whose decisive premise changes, so that the system must respond to scientific meaning rather than surface vocabulary.
54. As an evaluator, I want agreements sampled as well as disagreements, so that a matching label cannot conceal a wrong premise.
55. As an evaluator, I want provisional-label agreement reported separately, so that it remains reproducible without becoming ground truth.
56. As an evaluator, I want unsupported concern and unsupported reassurance reported separately, so that aggregate agreement cannot hide asymmetric harm.
57. As an evaluator, I want Result-scope correctness, premise support, contradiction handling, completion, errors, context bytes, calls, latency, and cost reported separately, so that trade-offs remain visible.
58. As a maintainer, I want existing premise, Evidence, evaluation, and qualification machinery extended, so that the successor does not create parallel systems.
59. As a maintainer, I want each implementation slice independently demonstrable, so that failures can be attributed to a bounded change.
60. As a maintainer, I want existing issues left unchanged, so that the new successor plan does not rewrite prior tracking history.

## Implementation Decisions

- **Authority boundary.** Keep one installed-host model loop and a model-free server. The server owns workflow state, Source capture, Evidence identity, strict structural validation, deterministic RoB 2 logic, and verified export. The host owns scientific sufficiency and signaling answers. Proposal Review remains the only researcher gate.
- **Success claims.** Do not add human adjudication. Qualification may support an engineering promotion decision but cannot claim independently validated scientific accuracy. Use official-guidance review, source-grounded premises, paired controls, Trial-held-out evaluation, and cross-model/host consistency; retain provisional agreement as a separate diagnostic.
- **Successor boundary.** Publish new work items and leave all existing issues unchanged. Cite prior issues for context only. Implement only residual P0–P2 behavior; do not recreate completed navigation, search, Evidence, premise, context, or evaluation capabilities.
- **Investigation projection.** Reuse the existing premise record and working checkpoint to derive a compact typed investigation view. Include the proposition, observed coverage, support, counterevidence, unresolved component, recovery choices, and stopping rationale. Do not add another ledger or Canonical scientific object.
- **Permission versus readiness.** Preserve workflow continuation as the legal next mutation. Present it separately from host-asserted scientific sufficiency. Structural validation does not establish entailment or completeness and must keep further investigation actions visible.
- **Stopping policy.** Require neither a fixed search count nor exhaustive reading. A valid stopping rationale explains why the available answer is supported, why another accessible action is unlikely to discriminate the alternatives, or which access/budget limit prevents continuation.
- **Question distinctions.** Maintain concise, proposition-specific operational guidance for D1–D5 while keeping licensed official material visibly distinct. Generate repeated model-facing forms from one maintained source where practical. Use neutral paired examples, never Trial names, expected labels, or model-specific rules.
- **Population reconciliation.** Represent participant transitions and outcome constructs without substituting analyzed, treated, event, or denominator counts for observed outcomes. Keep reasons, timing, arm, population, endpoint, severity, and window attached to each quantitative premise.
- **Quantitative assistance.** Permit deterministic calculations only after inputs are scope-compatible and source-bound. Calculations expose consequences or bounds; they do not select an answer or impose a universal materiality threshold.
- **Trial review.** Extend the existing same-host review rather than add a second assessment or critic. Show current answers, decisive Evidence, host inference, counterevidence, limitations, population/chronology conflicts, and uninvestigated routes. Permit ordinary Domain revision before closure.
- **Dependency-aware working state.** Keep source observations reusable while their Source projections and Result remain unchanged. Track enough dependency information to mark affected interpretations, premises, drafts, and stopping decisions stale after Domain revision. Source or Result changes invalidate affected material.
- **Context ordering.** Present the exact Result, active proposition, material gap or contradiction, decisive Evidence, relevant compact guidance, then recoverable support. Preserve deterministic reconstruction and exact recovery; never make summaries or metadata Evidence authority.
- **Document navigation and vision.** Use stable human-readable labels, logical sections, embedded-document/version spans, dates with explicit meanings, and page/region recovery. Treat roles and dates as facts, not applicability judgments. Use verified renders when layout carries scientific meaning and retain honest host-observed provenance.
- **Benchmark record.** Extend the existing manifest, attempt, observation, comparison, and qualification types into one immutable campaign record. Bind case identity, selected-attempt policy, Source/build/pack/skill/contract identity, host/model/effort, prompt, tool inventory, phase/resumption lineage, terminal outcome, artifact hashes, verification, reference, and scorer identity.
- **Execution configuration.** Make model and effort explicit manifest fields. Record every override and keep portable invocation. Repair current and supported legacy session-event extraction and stop repeated resumptions when the negotiated tool inventory is absent or incompatible.
- **Exact-Result scoring.** Before scoring a new run, compare the approved artifact Result with the expected Trial, comparison, endpoint definition, population, time window or cutoff, estimate, and precision. Any mismatch is a hard failure. Historical mismatches remain visible and explicitly unscored.
- **Attempt integrity.** Retain all attempts, resumptions, failures, and artifacts. Declare selection policy before execution. A process exit, verified ZIP, or syntactically valid label vector does not alone establish a successful scientific case.
- **No speculative P3 work.** Do not add vector retrieval, neural reranking, a routine fresh-context critic, a second scientific model, or compound write tools in this program. A future controlled experiment may justify one independently.

## Testing Decisions

- Treat externally visible behavior as the testing target. Verify what the host can call, receive, recover, revise, review, and score rather than asserting private helper structure.
- Use the public application/MCP contract as the main deterministic seam for status, investigation projection, Domain context, Evidence recovery, validation, save, revision, Trial review, closure, and finalization.
- Use the pure evaluator seam for official question activation, Domain mapping, counterfactual branches, and the unchanged overall aggregation policy.
- Use benchmark command behavior and immutable artifacts as the seam for preparation, configuration, attempt lineage, session recovery, exact-Result matching, exclusion, and scoring.
- Use installed-host runs for actual tool visibility, structured-result delivery, context ordering, continuation, compaction, restart, premise recovery, selective revision, and preclosure review.
- Existing intake-contract, assessment-lifecycle, working-checkpoint, bounded-context, comparison-card, evaluation-harness, observation-import, qualification-manifest, score-trial, and bundle-verifier tests are the prior art to extend.
- Add behavioral cases where structural validation succeeds while investigation remains open; verify that permitted writes and investigation choices remain distinct.
- Add working-state cases where an unrelated Domain commit preserves source observations but stales dependent inference, and where changed Source or Result scope invalidates affected notes.
- Add review cases for unsupported links, contradictory Evidence, population mismatch, chronology mismatch, an honestly bounded limitation, and a correction that reopens one Domain without repeating the Trial.
- Add paired D2 cases for permitted versus protocol-inconsistent trial-context treatment changes.
- Add paired D3 cases for continued versus discontinued follow-up, event count versus ascertainment count, administrative versus informative censoring, and possible versus likely outcome dependence.
- Add paired D4 cases for awareness versus susceptibility, possibility versus likelihood, equal versus differential detection opportunity, and objective versus judgment-dependent assessment.
- Add paired D5 cases for plan retrieval versus applicability, pre-unblinding versus post-unblinding finalization, and multiple eligible analyses with versus without evidence of results-based selection.
- Add exact-Result scoring cases for mismatched comparison, definition, population, window, estimate, and precision; each must fail before label scoring.
- Add session fixtures for the current thread event, supported legacy session events, missing execution records, absent tool inventory, safe resumption, and repeated continuation prevention.
- Add run-record cases for child failure, timeout, approval pause, restart, duplicate attempt, stale artifact, hash mismatch, partial bundle, and successful completion.
- Run Trial-held-out campaigns across at least two model families or materially different supported hosts. Keep every draw and predeclare attempt selection.
- Report premise support, counterevidence handling, unsupported concern, unsupported reassurance, Result-scope correctness, Domain-level provisional agreement, completion, errors, context bytes, calls, latency, and cost. Do not collapse them into one score.
- Inspect a prespecified sample of matching labels and disagreements through autonomous source-grounded review. State uncertainty and do not describe that review as independent adjudication.
- Require formatting, type checking, the complete test suite, public-contract verification, independent bundle verification, and the installed-host campaign evidence appropriate to each slice.

## Out of Scope

- Human scientific adjudication or a new researcher answer-approval gate.
- Claims of independently validated scientific accuracy.
- A second model with answer authority, a routine fresh-context critic, or a multi-agent assessment architecture.
- Changes to the current deterministic overall aggregation policy.
- Changes to official RoB 2 question activation or Domain mapping unless a separately demonstrated implementation defect is found.
- Vector databases, embeddings, neural reranking, semantic query expansion, or another retrieval backend.
- Fixed search quotas, compulsory full-document reading, universal missingness thresholds, automatic Low defaults, or severity caps.
- Trial-specific, oncology-specific, catalog-specific, or model-specific answer rules.
- A new workflow orchestration service, generalized plugin framework, or parallel scientific state store.
- Automatic semantic entailment judgments by the server.
- Automatic import of facts or judgments across independent workspaces.
- Rewriting, closing, relabeling, or using existing issues as blockers for the new ticket set.
- Replacing exact Evidence, recoverable source text, immutable history, or deterministic verification with summaries.
- P3 experiments such as compound validation-and-commit tools unless later evidence supports a separate proposal.

## Further Notes

- The two supplied audit files differ only by the presence of a table of contents.
- The audited repository snapshot is the current main commit, so recommendations must be checked against capabilities already implemented at that exact baseline.
- The current fallback session parser contains a concrete mismatch between the current thread event field and the field it reads. This is a confirmed engineering defect, not proof that it caused any particular benchmark failure.
- Current benchmark scoring verifies artifact status and label shape but does not establish full exact-Result equivalence before scoring.
- Existing working checkpoints already contain premise records and Source/Result bindings; the successor changes projection and staleness granularity rather than introducing a new memory subsystem.
- Existing Trial review already binds the current Result and Domain checkpoints and projects Evidence bases. The successor makes semantic tensions more salient without creating another authority.
- The existing qualification record holds promotion because installed-host and scientific evidence remain incomplete. This successor deliberately removes human adjudication from its gate, so its final claims must remain narrower.
- Related prior issues include #347, #348, #407, #408, #410, #411, and #413–#425. They are context only and remain unchanged.
