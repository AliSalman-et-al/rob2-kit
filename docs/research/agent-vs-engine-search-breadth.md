# Agent versus engine responsibility for search breadth in issue #167

## Question and conclusion

[Issue #167](https://github.com/AliSalman-et-al/rob2-kit/issues/167) asks whether cheap-source-first retrieval can stop after a short primary report appears to settle a RoB 2 signalling question, instead of forcing every question through three full-corpus passes.

The safe answer is a **hybrid contract**. A deterministic engine can prove that a declared procedure was executed over a fixed snapshot. It cannot prove that a source was understood exhaustively, that the query vocabulary found every semantically relevant passage, or that the observed evidence settles the scientific question. The assessment agent is better placed to judge those semantic matters, but its confidence must not be allowed to erase question-specific source obligations or undisclosed uncertainty.

In short: **the engine owns the auditable floor; the agent owns semantic sufficiency above that floor**.

## What “thorough enough” can mean

The design problem becomes tractable only if five claims are kept separate.

| Claim | Can the engine establish it? | Who should decide? |
| --- | --- | --- |
| **Exhaustive source traversal**: every page, canonical unit, or bounded continuation in a declared scope was made reachable and traversed | Yes, mechanically, if scope and traversal units are versioned and every continuation is recorded. This proves exposure, not comprehension. | Engine |
| **Query coverage**: every candidate matching a fixed query under a fixed index, policy, and source scope was returned and dispositioned | Yes. It does not prove that the query expressed every relevant synonym, concept, table, image, or contradiction. | Engine validates; agent authors/refines the information need |
| **Evidence sufficiency**: the available information supports `yes`, `probably_yes`, `probably_no`, `no`, or `no_information` | No. RoB 2 deliberately requires reviewer judgement, including when firm evidence is absent. | Agent/assessor, with cited evidence and limitations |
| **Contradiction seeking**: plausible disconfirming evidence and discrepant reports were actively considered | The engine can require a pass, relevant source roles, chronology/version checks, and dispositions. It cannot know that all meaningful contradictions were imagined or recognized. | Engine requires and records; agent performs and interprets |
| **Auditable stopping**: further searching is not required under the applicable policy | The engine can validate objective prerequisites and an allowed stopping reason. The semantic rationale remains attributable assessor judgement. | Joint decision |

This distinction prevents two unsafe substitutions: “all query pages traversed” must not mean “no relevant evidence exists”, and “the agent feels the answer is clear” must not mean “sources that could change the answer need not be checked”.

## Primary-source findings

### RoB 2 makes semantic sufficiency judgement-dependent

RoB 2 signalling questions seek reasonably factual information, but the response scheme explicitly distinguishes firm evidence (`yes`/`no`) from judgement (`probably yes`/`probably no`). `No information` is appropriate only after deciding that a probabilistic answer would also be unreasonable. The algorithm proposes a risk-of-bias judgement, but reviewers must verify it and may change it with reasons. These are semantic decisions, not properties that deterministic traversal can certify. [RoB 2 full guidance, §§1.1–1.2, pp. 3–4](https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf); [Cochrane Handbook, Chapter 8, §8.2.3](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08)

The guidance does not define a page count, unit count, query-recall threshold, or other mechanical test for when one document has been “read enough”. Instead, it tells reviewers to document the sources used and says that as many sources as possible should be used in practice. [RoB 2 full guidance, §3, pp. 8–9](https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf)

### A clear primary report does not make every other source role dispensable

Cochrane identifies published articles, trial registers, protocols, clinical study reports, and regulatory reviews as potential sources. It warns that published reporting is often incomplete, protocols may contain more methodological detail, and investigators may need to be contacted to clarify incomplete or discrepant information. [Cochrane Handbook, Chapter 7, §7.3.1](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-07)

This is especially important for Domain 5. Assessing selective reporting requires information about prespecified analysis intentions and their timing. The RoB 2 guidance strongly encourages access to advance plans, identifies registry entries, protocols/design papers, and statistical analysis plans as relevant sources, notes that the SAP often contains the most detail, and requires attention to document dates and amendments. An apparently decisive results paper cannot, by itself, establish that an analysis was prespecified before unblinded outcome data were available. [RoB 2 full guidance, §8.3.1, pp. 59–61](https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf); [Cochrane Handbook, Chapter 8, §8.7](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08)

The obligation should therefore be expressed as an **evidentiary role or proposition**, not necessarily a filename. One source may satisfy several roles; conversely, a file labelled “protocol” may not establish the relevant dated intention.

### Contradiction seeking is not optional confirmation work

The Handbook says sources can disagree and recommends clarification when information is discrepant. MECIR C42 also requires reviewers to collate multiple reports of the same study and warns that secondary reports may contain valuable design or conduct information. This supports an explicit contradiction/cross-report stage rather than permitting the first plausible supporting passage to terminate the search. [Cochrane Handbook, Chapter 7, §7.3.1](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-07); [MECIR C42](https://www.cochrane.org/authors/handbooks-and-manuals/mecir-manual/standards-conduct-new-cochrane-intervention-reviews-c1-c75/performing-review-c24-c75/selecting-studies-include-review-c39-c42)

The engine can ensure that a contradiction stage occurred and that surfaced candidates were dispositioned. Whether a passage truly conflicts, refers to the active Trial and Result, or changes the answer remains an assessor judgement.

### Search completeness is not objectively self-evident

The closest mature analogue is bibliographic searching. Cochrane states that deciding when search development is complete is often difficult to do scientifically or objectively, that proposed stopping methods have received little formal evaluation, and that checks such as known-item retrieval, citation searching, and relative recall are diagnostics rather than proof that nothing was missed. It also requires reasons for stopping to be documented where saturation is used. This guidance concerns study retrieval rather than reading one trial document, so it is analogous rather than directly controlling; nevertheless, it cautions against claiming that a deterministic heuristic proves semantic completeness. [Cochrane Handbook, Chapter 4, §4.4.11](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04)

What can be made reproducible is the process. MECIR C36 requires recording sources searched, when, by whom, and with which terms. [Cochrane Handbook, Chapter 4, §4.5](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04) PRISMA-S likewise focuses on transparent reporting of information sources, dates, complete strategies, and limits rather than certification that the information need was semantically exhausted. [PRISMA-S guideline](https://pmc.ncbi.nlm.nih.gov/articles/PMC7839230/)

## Fit with rob2-kit's existing design

The repository already draws most of the right boundary:

- [ADR-0016](../adr/0016-agent-reviewed-span-attribution-replaces-trial-discourse-scope.md) assigns Trial attribution and semantic disposition to attributable span-level review because parser labels are too brittle, while retaining deterministic provenance and freeze validation.
- [ADR-0017](../adr/0017-parser-output-carries-structure-not-scientific-scope.md) says parsers preserve structure rather than establish Trial, Result, Domain, or signalling-question meaning.
- [ADR-0018](../adr/0018-engine-owned-cost-bounded-evidence-navigation.md) gives the engine responsibility for bounded, reproducible navigation and continuation.
- [ADR-0019](../adr/0019-selected-query-supersession-preserves-surfaced-candidates.md) allows cost-saving query replacement while preventing already surfaced material from disappearing.
- [ADR-0001](../adr/0001-fail-closed-at-terminal-evidence-checkpoint.md) and [ADR-0007](../adr/0007-server-side-search-coverage-recorder-not-client-round-tripped-receipt.md) keep terminal adequacy and coverage state engine-verified rather than trusting a caller-authored receipt.
- [Brittle evidence guards and semantic review](brittle-evidence-guards.md) reaches the same general conclusion for discovery: broad, provenance-rich visibility should be paired with explicit agent review and a deterministic fail-closed freeze.

The current domain model also correctly says that a Search coverage receipt establishes **procedural search adequacy rather than proving absence**, and that a bounded read may stop only when displayed context is sufficient while potentially material omissions require further reading or an unresolved disposition. The issue #167 design should preserve those distinctions while replacing blanket full-corpus passes with additive, question-specific stages.

## Recommended responsibility split for #167

### Engine responsibilities

The engine should issue a versioned obligation for each active `(signalling question, pass)` and validate:

1. which evidence roles or propositions must be tested at the current stage;
2. the cheap-to-expensive stage order and which objective findings trigger escalation;
3. source/parse/version identities, readability, dates, amendments, and declared unavailable sources;
4. exhaustive traversal of each selected query within its declared scope;
5. disposition of every surfaced candidate, including material unresolved items;
6. completion of a distinct contradiction/follow-up stage where required;
7. a typed stopping outcome and its consequences; and
8. terminal freeze rules, including a stricter basis for `no_information` than zero hits or agent confidence.

The engine must describe this as **procedural breadth**, never semantic exhaustiveness.

### Agent responsibilities

The agent should:

1. translate the guidance's evidence need into appropriate terms, phrases, sections, and refinements;
2. read enough surrounding context to determine Trial, Result, chronology, meaning, and disposition;
3. identify supporting, contradicting, contextual, duplicate, and unresolved evidence;
4. decide whether the evidence is sufficient for a RoB 2 response, including whether a probabilistic answer is justified;
5. state what further source role or context could materially change the answer; and
6. submit an attributable stopping rationale, limitations, and uncertainty.

The agent may request escalation early and may explain why an otherwise optional stage is material. It may not waive an engine-declared role merely because the current source “looks clear”.

### Stopping outcomes

A stage should end through a finite, auditable outcome such as:

- `obligation_satisfied`: required roles and contradiction checks completed; agent judges current evidence sufficient;
- `escalation_required`: a stated gap, conflict, or source-role need could change the answer;
- `source_unavailable_after_attempt`: acquisition attempt recorded, with the RoB 2 answer/limitation consequence;
- `semantic_uncertainty_unresolved`: relevant material remains ambiguous and blocks an unsupported answer or forces an uncertainty-bearing outcome; or
- `policy_exception`: a narrow, versioned exception whose prerequisites and reviewer rationale are both recorded.

“No more hits”, “primary report was clear”, a traversal-cost ceiling, or “agent confidence high” should not be terminal outcomes by themselves.

## Precise recommendation

Adopt the additive stage model proposed in the grill, but revise Q5's wording:

> The engine issues and validates the minimum procedural obligation. The agent decides semantic sufficiency and whether evidence triggers escalation, within that obligation. The engine never claims that the source was understood exhaustively, and the agent cannot silently waive required evidentiary roles.

For cheap-source-first retrieval, begin with the lowest-cost source capable of answering the question. Escalate when either (a) the question/pass policy requires an evidentiary role that the completed stage cannot establish, or (b) the agent records a potentially material gap, conflict, ambiguity, or contradiction signal. Permit stopping only after the engine validates the objective floor and records the agent's semantic rationale.

This preserves most of #167's expected cost reduction without converting an intelligent assessor's judgement into an unaudited completeness guarantee.
