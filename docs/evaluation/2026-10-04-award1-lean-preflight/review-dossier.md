# AWARD-1 D3 independent source dossier

This is a **development-exposed preparation**, not a held-out test. AWARD-1 had
a paid Luna native invocation on October 2, recovered October 3: 663,869 input,
575,488 cached input, 3,855 output tokens, approximately 105.5 seconds. Its source
review subsequently informed D3.4 guidance (`e6b893b`). The current preparation
launches no inference and endorses no signalling answer or domain label.

The attempted alternative check covered 802 retained `run.json` records across
the dated task workspaces, accompanying manifests/setup records, and textual
evaluation artifacts, excluding credential/session homes. Chua had no matched
targeted run metadata but appears in the cross-case premise inventory; Boeree
appears in earlier D2 source audits. Neither was certified as genuinely
unexposed. Original October 1 benchmark exposure also exists. We retain AWARD-1
for a disclosed test of existing lean-path provenance; no silent fresh-case
substitution or transfer claim is made. The earlier prospective-holdout wording
in the preceding audit is superseded by this verified exposure correction.

## Exact frozen Code Result

Original case: `benchmark-luna6-medium-2026-10-01/cases/award-1-2014`, requested
outcome **Change in HbA1c from baseline**. Target: assignment effect in all
randomized participants in the comparison groups, intended mean difference,
**26 weeks from randomization**, **dulaglutide 1.5 mg once weekly versus placebo
once weekly**, both with metformin and pioglitazone. Reported group-bound LS
mean changes are **−1.51% and −0.46%**, respectively, from **ANCOVA LOCF**.
The report also gives the between-group LS mean difference **−1.05 percentage
points**, nominal 95% CI **−1.22 to −0.88**. Figure 2A confirms signs and units;
text extraction renders some minus signs as `2` and `±` as `6`, so the raw text
must not be silently treated as numerically faithful. These are percentages of
HbA1c, and the difference is in percentage points, not relative percent change.

The original canonical Result declares `relation=exact`; its reported population
text says randomized-and-treated ITT, 976/978 overall, efficacy data after rescue
excluded, ANCOVA LOCF. We freeze those original target/report/relation fields
unchanged for comparison, rather than silently improving intake in one arm.
**This declaration is not a verified equivalence of estimands/populations.** The
registry supplies narrower result-specific denominators and pre-rescue rules.
The reviewer must resolve whether the assignment target and reported treatment
policy are sufficiently aligned before any accuracy claim. Assessments can
credibly discuss the reported contrast while preserving this limitation.

## Verified available sources and coordinates

The actual Code dossier contains two PDFs; both byte hashes match the October 1
canonical inventory and the newly copied source bundle:

| Source | Pages | SHA-256 |
| --- | ---: | --- |
| `2159.pdf` | 9 | `63cd5a3ff8875b21943f71cba0ec58fef741549f962132786cc1bf4a3b77270f` |
| `dc132760supplementarydata.pdf` | 2 | `da0de5a1322d6eecaacc7413b471916a87d231a107ab3b6221b3b15d7d9b2886` |

No separate complete protocol or SAP PDF is available in that directory. The
supplement's rescue-management passage is not a complete protocol or SAP. The
original registry's complete **9,433-line text projection** is preserved from the
Code derivative database; text SHA-256
`9680cc92144bf1e3888e0826fbbe25931c25c2b938897ba04959ec714b62db8f`, original
registry projection identity
`sha256:41d5c767dceed28cf46a137377106a310aac69246837768dc20b375121d28cd8`,
captured October 1. Original raw registry JSON bytes were not recovered here; this
is explicitly a retained projection, not a recreated raw capture. A new registry
capture inadvertently triggered by copying the original intake manifest is
preserved in a separate scratch workspace and **excluded** from future inputs.
The future source bundle uses roles only, avoiding another network capture.

Coordinates below use **physical PDF pages** and exact normalized rob2-kit text
projection line numbers. Main physical page 3 is journal page 2161; physical page
5 is journal page 2163. Figure-body values are visual transcriptions, not text
extraction quotations. All nine main pages, both supplement pages, both full
figure pages, and the complete original registry projection remain available;
these windows specify review necessities, not source-access limits.

Source URLs present in the material:

- Article: https://doi.org/10.2337/dc13-2760
- PDF download imprint: https://diabetesjournals.org/care/article-pdf/37/8/2159/621522/2159.pdf
- Supplement: http://care.diabetesjournals.org/lookup/suppl/doi:10.2337/dc13-2760/-/DC1
- Registry: https://clinicaltrials.gov/study/NCT01064687

## Allocation, completion and analysis populations

Main page 2, lines 100–119 describes four-arm 2:2:2:1 randomization and the
placebo switch after week 26. Main page 3, lines 55–60:

> A total of 978 patients were randomized
> to dulaglutide 1.5 mg, dulaglutide 0.75
> mg, exenatide, and placebo. Two pa-
> tients assigned to exenatide did not re-
> ceive thedrug;thus,theintention-to-treat
> population comprised 976 patients.

Figure 1B, main page 3, allocation branches and 26-week boxes, visually reads:

| Actual arm scope | Allocated/treated label | Discontinued study by week 26 | Completed week 26 |
| --- | ---: | ---: | ---: |
| **Selected: dulaglutide 1.5 mg** | 279 | 19 | 260 |
| **Selected: placebo** | 141 | 17 | 124 |
| Outside target: dulaglutide 0.75 mg | 280 | 17 | 263 |
| Outside target: exenatide | 276 | 26 in figure; 24 in prose | 252 |

The Figure 1B top box says “Randomized and Treated (N=976)” and “Discontinued
prior to treatment (n=2; Exenatide).” Main page 3, lines 67–76 reports 77 study
discontinuations and exenatide 24. The exenatide figure has 26 and its branch
does not arithmetically reconcile 276 treated with 252+26. Do not resolve that
inconsistency by inventing overlap or transfer those two never-treated people
into the selected comparison. Selected-arm completion counts reconcile, but
**study completion is not an observed HbA1c denominator**.

Original registry projection, page 1 lines 5802–5810, primary outcome denominator
entries, maps OG000/OG003 to dulaglutide 1.5 mg/placebo at lines 5813–5840:
**271 and 119 participants analyzed**. Outside-target values are 269 for
dulaglutide 0.75 mg and 266 for exenatide. Line 5842 states exactly:

> Participants who were randomized and received at least 1 dose of LY2189265, Exenatide, or Placebo with evaluable HbA1c data. Only pre-rescue measurements were used. Last observation carried forward (LOCF) was used to impute missing postbaseline values. If there were no data after the date of randomization, the endpoint was considered missing.

Thus selected-arm allocated/treated counts are 279/141; study completers are
260/124; primary-analysis denominators are 271/119. The latter include an
unknown number of LOCF-filled endpoint records. Neither 271/119 nor 260/124
establishes directly observed week-26 HbA1c counts. Differences of 8/22 between
allocation and primary analysis are derived counts, **not** verified counts of
missing observed week-26 values. The fact that placebo's difference is 22 and
its rescue count is also 22 does not establish individual correspondence.

## Missingness reasons and timing

Figure 1B, main page 3, 26-week discontinuation boxes, visually reads:

| Actual arm | Adverse event | Lack of efficacy | Lost to follow-up | Other |
| --- | ---: | ---: | ---: | ---: |
| **Selected: dulaglutide 1.5 mg** | 8 | 1 | 1 | 9 |
| **Selected: placebo** | 3 | 3 | 5 | 6 |
| Outside target: dulaglutide 0.75 mg | 4 | 0 | 7 | 6 |
| Outside target: exenatide | 9 | 1 | 3 | 13 |

These are reasons for **study discontinuation**, not a proven partition of
missing HbA1c values. Main page 2, lines 125–129 says patients stopping study
drug for an adverse event could remain for safety follow-up. It does not establish
continued endpoint measurement for every such person. Figure 1B later 52-week
boxes and post-switch placebo-to-dulaglutide arms are outside this week-26 target.

Main page 3, lines 104–108, Figure 1 footnote:

> Placebo patients continued until week 26 and were then randomized to dulaglutide 1.5 mg or
> dulaglutide 0.75 mg. aNumber of patients rescued at week 26: dulaglutide 1.5 mg, 4 (1.4%);
> dulaglutide 0.75 mg, 12 (4.3%); exenatide, 11 (4.0%); placebo, 22 (15.6%).

The selected-arm rescue counts are **4 and 22**, not the excluded-dose 12 or
exenatide 11. Their overlap with discontinuations, directly measured endpoint
availability, and LOCF use is not supplied. Rescue is an intercurrent event and
post-rescue efficacy measurements are excluded by the analysis rule; rescue
counts should not automatically be called dropout counts.

Supplement page 2, lines 8–18 gives outcome-related rescue criteria:

> An additional therapeutic intervention was considered in patients with a follow-up
> shorter than 6 months who developed persistent, severe hyperglycemia despite full compliance
> with the assigned therapeutic regimen.

Lines 11–15 specify average fasting blood glucose over at least two weeks:
above 270 mg/dL during the first six weeks, above 240 mg/dL after the first six
weeks, and above 200 mg/dL after week 26, without an acute glucose-raising
condition. The last threshold is outside the current target. Lines 16–18:

> develops persistent, severe hyperglycemia, but his most recent HbA1c measurements indicate
> a significant improvement in glycemic control (HbA1c change ≥0.3%) compared to the previous
> value, the investigator will decide if a new intervention is warranted.

Supplement page 2, lines 20–27 covers additional intervention in the **second**
26 weeks and continued allocated drug. Those later rules must not be used as
the first-26-week rule. These sources support examining outcome dependence;
they do not reveal each patient's unobserved week-26 HbA1c or the size/direction
of resulting bias.

## Primary and repeated-measures methods; sensitivity evidence

Main page 3, lines 13–27:

> The analyses of efficacy and safety
> were based on the intent-to-treat pop-
> ulation comprising all randomized pa-
> tients who received at least one dose
> of study treatment. For the assessment
> of efficacy and hypoglycemia events,
> only data collected before the initiation
> of rescue medication were used.
> The change from baseline in HbA1c
> and weight at 26 and 52 weeks were
> analyzed by ANCOVA, with factors for
> treatment, country, and baseline value
> as covariates. The last observation car-
> ried forward (LOCF) was used in the case
> of missing data. Secondary analysis

Main page 3, lines 28–37:

> methods for HbA1c and weight and
> methods for other continuous second-
> ary end points over time included a
> mixed-effects,
> repeated-measures
> (MMRM) analysis, with additional fac-
> tors for visit and treatment-by-visit in-
> teraction and the patient as a random
> effect. Least squares (LS) means and
> SEs are reported.

Figure 2, main page 5, caption lines 1–3 identifies panel A
as **ANCOVA LOCF** and panel B as **HbA1c over time, MMRM**. Full visual panels
are available. MMRM is an additional reported analysis, not the frozen primary
estimator. No explicit MNAR/pattern-mixture/tipping-point sensitivity result or
numerical sensitivity contrast for this exact primary result was found in the
two PDFs. The registry gives ANCOVA/LOCF for this result and does not establish
a directly observed endpoint denominator. The small supplement principally
reports other endpoints and rescue rules. This finding is bounded by the
available corpus; absence of such an analysis is not itself proof of bias, and
Cochrane does not impose a universal MNAR-analysis requirement.

## True unknowns and assessment credibility

Unknown: exact directly observed week-26 HbA1c counts; numbers and sources of
LOCF-filled records by selected arm; overlap of rescue, discontinuation,
analysis exclusion and measurement; individual timing/reasons within “other”;
unobserved outcomes; sensitivity of the frozen contrast to those outcomes;
complete protocol/SAP instructions; exact reconciliation of exenatide flow;
whether the original `exact` population/estimand relation is defensible.

The available sources permit a credible **qualified** D3 review of the reported
comparison. They do not support a uniquely required answer vector or certainty
about missing-data bias. Source ambiguity does not invalidate the provenance
test, but it prevents a preferred-label test and limits any matched benchmark
accuracy claim until Result alignment is independently reviewed.

## Official authority and intended comparison

Both implementations must use the same full official D3 context:
**Cochrane RoB 2, parallel assignment effect, 22 August 2019**, full guidance
Box 8 pp. 45–46 and shared D3 material, PDF SHA-256
`a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670`.
The existing `official_d3_prototype` presentation also includes the same
preserved official FAQ clarification on 3.2, hash
`060c4f0aa70573bb5d07257eb3d7b1dfff07c4373de1907e0c1055addba4f8cd`.
The authority preserves the distinction between observed and imputed outcomes,
contextual “nearly all”, evidence that a result is unbiased, possible versus
likely outcome dependence, and reasonable model-based judgments. No rigid
percentage cutoff, mandatory MNAR analysis, or trial-specific answer is added.

Full official URLs:

- https://drive.google.com/uc?export=download&id=19R9savfPdCHC8XLz2iiMvL_71lPJERWK
- https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2

Proposed baseline is `247db8c805c34923e2cd086124b084d040121834`, immediately
before lean checkpoint `55ccc7a3cdd8352c025aa15b9fc039dac6f9f58d`. Current
production is `e6b13031ddfa72437f3e1f2f9ca3b38ea58a064c`, whose `src` tree is
unchanged from 55ccc7. This is a test of that existing path, not a new schema.
Same source bytes, original approved target/report/relation, official guidance,
generic task prompt, launcher, tool allowlist, guards and independent criteria
are required. The actual verified launcher model is **`gpt-6-luna`**, effort
**medium**, native `mcp-codex` direct namespace `mcp__rob2`, read-only isolated
home, shell/web/apps/delegation disabled. No implementation-model substitution.

Success means source-faithful attribution, honest denominator distinctions,
sound Cochrane warrants, preserved uncertainty/counterpoints, and canonical
evidence/result binding. It does not mean High, Low, a particular signal, or
agreement with the old assessment. Count whether the model actually uses lean
handles/ranges; non-use supplies no evidence of lean-path benefit. Inspect all
attempts and source receipts, plus cached/uncached usage and actions. A paired
benefit requires a demonstrated error/friction reduction without evidence or
warrant regression. Both scientifically sound means no measured accuracy gain.
AWARD-1 results must be reported as development-case evidence.

The future input bundle contains **only sources and role declarations**. The
initial assessment workspace contains the reconstructed Result and source-only
proposal evidence, zero domain judgments, zero working notes, and zero
post-approval page reads. This dossier, criteria, old assessments, gold and the
offline fixture are outside that workspace and must never be model input. Full
source access remains. Separate parent review and explicit inference approval,
then `launch_checked`, are required; no paid call is authorized or run now.

## Offline lean-path proof

On the existing current production implementation, normal native source reading,
visual delivery/selection, handle/range submission and canonical storage passed.
Assertions verify original target/report/relation and all seven original leaf
binding paths/digests unchanged; current Result identity binding; exact narrative
quotes, source versions and page/line coordinates; full counterpart-arm visual
transcription, render hash, delivery receipt and visual uncertainty; explicit
unknowns and excluded-arm counterpoint. Zero working checkpoints and no
`working_observation` fields were needed. Five canonical Evidence records support
four active D3 answers. The mechanical fixture's server label is High; it is
**not** a scientific reference or future-model answer.

The canonical gate rejected an initial invalid NI for 3.2 and attempted save
before full post-approval main reading; both were corrected in the offline
fixture, not by weakening gates. Earlier fixture-construction mistakes involving
private/public method arguments and quantitative anchoring are preserved as
diagnostic failures, not model behavior. The ordinary nine-case lean suite also
passed in the preceding checkpoint. No new production code, paid inference,
full benchmark, merge, CI wait, or scientific gain claim is introduced here.
