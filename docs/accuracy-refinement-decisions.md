# Accuracy refinement decisions

Session date: 2026-09-16. This records the owner's decisions during the
grill-with-docs session. The supplied accuracy refinement plan is discussion
material; its proposed actions are not implementation authorization.

## Settled scope

- Preserve the plan's existing architecture, authority, captured-source,
  scientific-rule, and evaluation boundaries initially. Surface any conflict
  that prevents a defensible assessment for an explicit decision.
- Maximize accuracy on the existing evaluation set through generalized
  improvements reasonably expected to help on unseen trials. Do not introduce
  trial-specific or Luna-specific rules. Existing-set improvement alone does
  not establish unseen-trial accuracy.
- Scientifically defensible kit answers may disagree with imperfect reference
  labels. Do not force agreement by changing otherwise defensible answers.
- Review scientific expectations autonomously against the exact Result, Source
  passages, signaling answers, and applicable official guidance. Make informed
  judgments and record uncertainty without waiting for human adjudication.
  This supersedes the first round's human-review dependency. Agent review is
  not independent human adjudication and creates no production approval gate.
- Accept scientific guidance changes against a demonstrated source-to-answer
  failure and paired fictional cases where changing the decisive premise should
  change the answer. Use general methodological language without trial names or
  model-specific instructions.
- Allow additional investigation when it resolves a material uncertainty. Avoid
  mandatory extra passes for every assessment. Measure cost and latency before
  imposing a numerical runtime ceiling.
- Include all reasonable correctness, scientific, workflow, and performance
  fixes and enhancements in the implementation scope. The owner rejected
  deferring independent cache improvements out of that scope. Proposed changes
  still require a concrete benefit and meaningful verification.
- Balance improvements and regressions rather than imposing a zero-regression
  promotion rule. Review their scientific significance as well as aggregate
  scores, including unsupported reassurance and genuine-High detection.
- Use the existing preclosure Trial review to inspect unresolved contradictions,
  unsupported inferences, and cross-domain inconsistencies. Reopen investigation
  when needed without requiring a second full assessment.

## Session boundary

Stay within the current five-hour usage allowance. The initial usage reading
showed 3% used. Recheck when usage tooling is available and leave a reserve.
The owner confirmed shared understanding and closed the interview. The next
authorized deliverable is a specification and implementation tickets through
the invoked to-spec and to-tickets skills, not immediate code implementation.

## Confirmed implementation direction

Diagnose available run artifacts and reproduce concrete defects before selecting
fixes. Prioritize D3, AE Result selection and D5, then D4 and D1/D2 while covering
the plan's commitment, evidence-delivery, recovery, cache, and evaluation fixes.
Treat the plan's causal explanations and interventions as hypotheses until
checked. Preserve original references, archived runs, and all evaluation attempts.
Use balanced fictional contrasts and source-grounded review to test general
improvements. Report existing-set agreement separately from defensibility,
completion, and efficiency; do not claim independent scientific validation.

D1-D5 accuracy is the objective. Overall judgments are auxiliary because
different aggregation policies can produce different overall judgments from the
same Domain inputs. Distinguish kit weaknesses from possible model limitations;
do not infer a model ceiling from the current evaluation. Scientifically
defensible differences from Suster labels are acceptable. Consider context,
tools, MCP contracts, metadata, skills, recovery, and ergonomics together when
selecting the highest-yield generalized improvements.

## Published handoff

The owner approved the test boundaries and 19-ticket breakdown. Published
specification [#365](https://github.com/AliSalman-et-al/rob2-kit/issues/365) and
implementation tickets #366-384 with ready-for-agent labels. Verified all issue
bodies and 23 native blocking relationships. Existing issues remain unchanged.
