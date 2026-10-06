# D5 authority and Bagg timing audit

## Exact addition in 247db8c

```text
## Bind the comparison to the cited passages

Keep earlier and later plan versions in the comparison. Matching the latest SAP
and report does not resolve changes in earlier intended measurements or analyses.
Read the relevant earlier definitions when they could change the conclusion;
qualify unresolved differences without assuming they were driven by results.

When a warrant says that alternative results were reported, cite the actual
results passages or tables, not only a methods paragraph describing analyses.
Likewise, cite the relevant plan passages for the intended alternatives. Reuse
adequate captured Evidence; no additional search is needed just to add a citation.
A method description can support what was analysed without establishing that all
estimates were fully reported. Keep inference and remaining uncertainty explicit.
```

## Claim-by-claim authority mapping

Authority is Cochrane RoB 2 parallel trials, effect of assignment, **22 August
2019**, Box 11 pp. 63–65. The independently read official PDF hash is
`a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670`, exactly the
production descriptor. The pack, official wording and evaluator are unchanged.

| Added claim | Official basis / attribution | Limit |
|---|---|---|
| Compare relevant earlier/later plans; matching latest versions does not settle earlier changes | 5.1 p.63 compares sufficiently detailed intentions with published analyses and considers plan changes; 5.2/5.3 pp.63–65 compare intended eligible alternatives with reported ones | Earlier-version investigation is an implementation inference from that comparison, not a new blanket requirement to obtain every version |
| Read earlier definitions when they could affect the conclusion | Same comparison and eligibility requirements, 5.1–5.3 | Relevance is conditional; no mandatory all-source reading, chronology-proof gate or preferred answer |
| Qualify unresolved differences without assuming result dependence | 5.1 p.63 allows changes unrelated to results; 5.2/5.3 pp.63–65 require likely selection on results in addition to eligible alternatives/subset reporting | Differences, multiplicity and missing dates alone cannot justify affirmative selection answers |
| Cite actual results when asserting alternatives were reported | 5.2/5.3 pp.63–65 distinguish full reported results from alternative measurements/analyses performed | Citation mechanics are local traceability guidance; Cochrane does not prescribe MCP handles, a note schema or citation count |
| Cite plan passages establishing intended alternatives | Same intention-versus-report comparison, 5.1–5.3 | Local evidence binding, not an independent scientific authority |
| Reuse adequate Evidence; no fresh search just to cite it | Local implementation ergonomics | No claim that Cochrane mandates this tool procedure; evidence sufficiency remains substantive |
| A methods description alone does not establish all estimates were fully reported | 5.2/5.3 distinguish analyses/measurements performed from results fully reported | It may still support actual conduct; no blanket exclusion of methods passages |
| Keep inference/uncertainty explicit | Official five answer options and conditional NI circumstances, 5.1–5.3 | Local audit presentation; does not force NI or require exact timestamps for probable judgments |

The added section contains **no chronology requirement, NI instruction, label
rule, count threshold or compulsory scope metadata**. It does not alter the
existing timing proposition. A statement about a late SAP is distinct from a
statement about access to unblinded data. A probable judgment may be supported
without exact chronology; NI may also be defensible when that inference remains
insufficiently supported. Under-explanation is not proof that an answer is wrong.

## Exact selected Bagg Result and warrant

The complete original Result is preserved in `bagg-premises.json` and
[original-result.json](../2026-10-04-bagg-native-d5/original-result.json).
It is an **exact** assignment-effect comparison of graded sensorimotor retraining
(RESOLVE) versus sham procedure and attention control. The target is all randomized
participants, past-week mean pain on an 11-point NRS (0=no pain, 10=worst pain)
**18 weeks after randomization**, mean difference. The reported estimate is
**−1.0 (95% CI −1.5 to −0.4)**. The full analysis set is randomized participants
providing data at each analysed time, in their assigned groups regardless of
adherence; 128 intervention and 133 control supplied the 18-week outcome
(261/276). Missing outcomes were assumed MAR and not multiply imputed.

The native 5.1 answer was **No information**, with this exact justification:

> The captured supplement dates the SAP draft to March 2, 2020, and describes the approved primary endpoint/analysis as pain intensity at 18 weeks using a mixed-effects model. The main report says follow-up was completed February 3, 2020, and reports the corresponding 18-week analysis. However, neither source establishes when unblinded outcome data became available to the investigators making analysis decisions. The chronology raises a concern that the SAP was drafted after outcome collection, but collection completion, data cutoff, or a draft date alone does not establish investigator access. Under the question's uncertainty rule, neither a definitive nor probable timing judgment is sufficiently grounded.

Its explicit unknown was:

> When investigators first had access to unblinded outcome data; whether the March 2, 2020 SAP draft was finalized before such access.

The model's statement that probable timing was not sufficiently grounded is its
case inference, not an official rule that missing timestamps require NI. Its bases
were supplement page1 lines1–9, SAP page12 lines17–21, and report page4 lines14–42.
The report follow-up date was read on main page1 but not included in these bases.
That is a citation gap, not a fabricated date or a demonstrated wrong answer.

## Earlier/later intentions, actual reading and conduct

Exact source-located quotations are preserved in `bagg-premises.json`; physical
page indices and line numbers use the captured immutable projection.

| Source passage | Native read? | What it establishes |
|---|---|---|
| Supplement1 p1 lines1–9 | Yes | Protocol submitted Nov29 2015 before first randomization; SAP **drafted** Mar2 2020; June2016 repeated-measures-power correction changed sample size and demoted disability, with ethics submission Nov27 2016 |
| Original protocol v5 Nov27 2015, p4 lines25–28 | No | Intended participant/statistician blinding; no proof it was carried out |
| Original protocol p4 lines30–53 | No | Pain/disability co-primary six weeks post-intervention; additional during/post-treatment measurements; applicability and actual collection of those alternatives remain unresolved |
| Original protocol p5 lines1–20 | Yes | Planned ITT, blinded statistician, mixed models/random intercepts, prior prognostic covariates and linear contrasts |
| SAP cover p7, abstract p9, design p10 | Yes | Later dated plan and comparison, not unblinded-access date |
| SAP p11–14 | Yes | Baseline/18/26/52-week schedule, funding-driven early later follow-ups, assignment principles, past-week NRS18week primary, mixed model/contrast, possible complier/ATET analyses |
| SAP p21 table shell | No | Intended primary18 and later26/52/overall estimates; a shell does not prove actual reporting |
| Main report p1,3–8 | Yes | Recruitment/follow-up, outcome definition, early power amendment, actual model/fullanalysisset/MAR/noimputation, reported tables/primary/complier estimates |

Native supplementary reading was p1,5,7,8,9,10,11,12,13,14; all10main-reportpages
were read. No operative p4 protocol definitions or p21 shell were read. The
complete four-PDF source set was available, which does not establish delivery.

NI is defensible because the later SAP draft postdates follow-up and the actual
unblinded-access/finalization sequence is not established. A qualified Probably
Yes could also be defensible using the earlier plan's core model consistency and
trial circumstances; future-tense blinded-analysis intent is supportive planning,
not proof of actual conduct. The early amendment's stated power rationale is
separate from the later SAP timing and affects disability rather than replacing
this pain endpoint. Do not infer result dependence from the amendment alone.

The prior review's completeness criticism is a warrant-coverage qualification,
not proof that 5.2/5.3 No was wrong. Earlier time points may be outside the user's
eligible18week Result; their actual measurement/withholding is unestablished.
Matching the later plan/report and reporting nonsignificant later results are
reassuring. No affirmative selective-reporting answer is imposed. The native
NI/No/No → Some concerns record remains unchanged.
