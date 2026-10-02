# Trial-context cause versus intervention burden

Read-only source: the actual Code benchmark repository's October 1 campaign,
not the older main-repository evaluation corpus. `retained-records.json` pins
four canonical database hashes, log hashes/event coordinates, exact accepted
D2.3 answers and cited selected passages, approved targets and server-output
sensitivity calculations. No workbook/reference labels were used.

A bounded scan of accepted affirmative D2.3 rationales identified four cases
for close inspection. These are diagnostic examples, not a random sample or a
prevalence/accuracy estimate.

| Case | Retained claim | Assessment of the inference |
| --- | --- | --- |
| An 2021 | Stopping an intensive assigned exercise program establishes a trial-context cause | Faulty link: cited facts establish intervention burden, not a participation-specific cause |
| Bendix 1996 | Difficulty, smoking restrictions and increased pain are caused by the intervention context | Same faulty link; ordinary treatment burden is substituted for trial context |
| Guitton 2019 | Removing HFNC for obstructed laryngoscopic vision is probably context-caused | Unsupported promotion: the answer itself says ordinary clinical care versus trial cause is unknown |
| Boeree 2017 | Non-protocol interruptions may have resulted from unblinded allocation awareness | Credible affirmative judgment: authors explicitly identify the allocation-dependent decision; probable confidence retains uncertainty |

Cochrane full guidance (22 August 2019), printed p.28, Box 6 D2.3, distinguishes
recruitment/engagement or trial-specific personnel conduct from deviations
compatible with ordinary care. A protocol inconsistency and an intervention-
related cause alone do not establish a trial-context cause. Primary guidance:
https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf.

The mistake matters. All four retained D2 judgments were High, with appropriate
assignment analysis Yes/Probably yes. Holding the other answers fixed while
changing D2.3 to Probably no removes the dependent questions and produces Low;
No information produces Some concerns. These are counterfactual sensitivity
calculations, not adjudicated replacements. Boeree's affirmative rationale is
credible and should not be removed simply to lower a grade. In the other cases,
insufficient source coverage can warrant NI; this audit does not force Low.

## General context correction

The existing card's causal contrast varied ordinary clinician versus trial staff.
That can substitute personnel identity for a participation-specific cause;
trial staff can also provide ordinary care. The replacement holds the clinician,
conduct and protocol prohibition fixed and varies the documented reason:
ordinary symptom management versus allocation-dependent decision-making.
A second contrast holds program discontinuation fixed and varies ordinary
regimen burden versus additional research-only engagement. Protocol status is
compared separately with an explicitly documented allocation-driven cause.
The host's cause proposition now states the ordinary-delivery distinction.

No trial names, source quotations, workbook labels, suggested question answers
or required severity were added to production context. The host still leaves
causal status unknown until the assessor examines source evidence. No automatic
causal classifier, keyword heuristic, answer coercion or new transport field
was introduced. Current operational guidance already contained the correct
rule; the issue was an ambiguous causal comparison supplied to the model.

Three focused context controls passed, with lint/type checks. At most one
bounded production D2 diagnostic is authorized after this checkpoint; its
outcome will be reported separately, including durable usage and rationale
comparison. No full benchmark or automatic retry is authorized.

## Production diagnostic and refinement

The authorized single An D2 attempt is frozen in `production-an/`. Its rationale
now distinguishes intervention burden from trial context, but the model submission
failed a counterpoint field-name validation and no production checkpoint was
saved. An independent clerical-only offline control yields High via a different
D2 branch. No accuracy or risk-label improvement is claimed.

Failure review identified a contradictory D2.6 consideration in production
guidance. Cochrane printed p.29 permits modified ITT analyses excluding missing
outcomes. The clarification removes the blanket eligible-exclusion statement:
missing-only exclusions, observed-but-omitted outcomes, wrong grouping and unknown
exclusion mechanisms are separate. It preserves the original timing distinction
and the ineligible-participant exception. This refinement was not retested with
paid inference. The D3.2 scoped negative-evidence exception is also now explicit
in the shared Domain context instructions, matching its existing save/export
implementation rather than contradicting it with a generic certainty statement.

Matching source-byte hashes were checked against the Code corpus. Primary local
PDF pages supporting the causal audit: An p.11; Bendix p.4; Guitton main p.5 and
protocol sections; Boeree p.9. `source-page-checks.json` retains exact retrieved
page text and coordinates. An's complete main report was supplied through MCP
in the production attempt.

Validation after the refinement: three causal/card controls and seven targeted
D2 guidance/evaluator/pack/export controls passed (10 unique focused checks).
Type, lint and format checks passed. No full benchmark, merge or automatic retry.
