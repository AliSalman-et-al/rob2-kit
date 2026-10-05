# Exact SAP and scope source passages

Stored source projections; raw sources and sealed outputs unchanged. Physical PDF pages. Completed references denote delivered text, not comprehension. Original scope records and event-log hashes are in the JSON companion.

## nejmoa1507062_protocol.pdf, physical page 131, lines 1–21

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[{"stage": "proposal", "line": 41, "order": 18, "start_line": 1, "end_line": 44, "numbered_body_sha256": "8c82d32edfa5c9ced0b1e4306304c14bc5eef60ab54543c661e3505aae2a000a"}]`

```text
1|Statistical analysis plan for the 05TB study (ISRCTN61649292)
2|"Intensified treatment with high dose rifampicin and levofloxacin compared
3|to standard treatment for adult patients with tuberculous meningitis (TBM-
4|IT)"
5|
6|Authors: Marcel Wolbers and Dorothee Heemskerk
7|Reviewed by Guy Thwaites, Jeremy Day, Maxine Caws
8|Version: 2.0, April 5, 2015 - final version prior to unblinding
9|Purpose
10|This document details the planned analyses and endpoint derivations for the ISRCTN61649292 trial as
11|outlined in the published study protocol (Trials 2011, 12:25; doi:10.1186/1745-6215-12-25). It focuses
12|on the analysis for the main clinical trial publication and does not include analysis for any subsidiary
13|studies.
14|Statistical software
15|Data derivations will be performed with the statistical software SAS v9.2 (SAS Insitute, Cary, North
16|Carolina, US). All statistical analyses will be performed with the statistical software R using the current R
17|version at the time of the final analysis (R Foundation for Statistical Computing, Vienna, Austria).
18|Analysis populations
19|Intention-to treat population (ITT)
20|The main analysis population for all analyses is the full analysis set including all randomized patients and
21|analysis is according to the randomized treatment arm.
```

## nejmoa1507062_protocol.pdf, physical page 132, lines 9–12

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[{"stage": "proposal", "line": 41, "order": 18, "start_line": 1, "end_line": 57, "numbered_body_sha256": "e4e93adbfd7660ca42afee3b4be2d4daf8418ce80518d5191f3dc902bb52e4b5"}]`

```text
9|Baseline/date of randomization is defined as the date of the first dose of study treatment (first
10|TBDR.DateStart for TBDR.TBDrug=1 ("Rifampicin/Placebo ( Study Drug)") or 2 ("Levofloxacin/Placebo
11|(Study Drug)")). In case a subject did not receive any study treatment at all, baseline will be defined as
12|the date of the enrolment assessment (ASREC.StudyVisit=0 "Baseline").
```

## nejmoa1507062_protocol.pdf, physical page 134, lines 21–45

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[{"stage": "proposal", "line": 43, "order": 19, "start_line": 1, "end_line": 45, "numbered_body_sha256": "1de258cc380fea704f00a813592d98134f3e8ef4f00f77201613d1481046ae75"}]`

```text
21|Primary endpoint - overall survival during the 9 month follow-up period
22|Derivation
23|Definition time to death: [date of death or censoring]-[date of randomization]+1
24|Definition event indicator: =1 if patient died =0 otherwise
25|
26|[Date of randomization]: as defined at the beginning of the "Baseline characteristics" section.
27|[Date of death]:OUTC.DateDeath (if OUTC.Reason9FU=1 "(1) Patient died")
28|[Date of censoring] - last date patient is known to be alive:
29|-
30|If OUTC.Completed9FU=1 "yes, completed 9 months of follow-up": OUTC.DateAssess
31|-
32|If OUTC. Completed9FU=2 "did not complete 9 months of follow-up" and patient not dead:
33|OUTC.DateAlive ("last date patient was known to be alive")
34|-
35|If outcome form OUTC is missing, the last date alive will be defined as the latest of: last visit data,
36|last neurological or clinical adverse event start or stop date, last hematology, chemistry in blood or
37|csf date. [Note: This last part is required only while the study is ongoing. At the end of the study,
38|there must be an outcome form OUTC for every subject.]
39|
40|The date of the actual 9-month follow-up visit will be used in the calculation. However, for subjects for
41|whom the 9 month visit was delayed by >2 weeks or those who died >2 weeks after month 9 will be
42|treated as censored on month 9 plus 2 weeks (day 289) instead.
43|
44|Planned analyses
45|Primary analysis
```

## nejmoa1507062_protocol.pdf, physical page 135, lines 1–56

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[{"stage": "proposal", "line": 43, "order": 19, "start_line": 1, "end_line": 57, "numbered_body_sha256": "82e77ad183f183303a9fc5d7646f328ec9fdab0dab6bf5734fc03c1acd360811"}]`

```text
1|Cox regression with treatment as the only covariate and stratification by HIV status (positive/negative)
2|and TBM disease severity (modified MRC grade I,II or III) at baseline.
3|Stratified Cox regression as implemented in the R function survival::coxph will be used with default
4|arguments (e.g. tie handling according to the Efron approximation). Of note, the protocol pre-specified a
5|log-rank test rather than Cox regression but the two approaches are essentially equivalent and Cox
6|regression has the benefit of providing a treatment effect estimate (HR) and associated 95% confidence
7|interval in addition to the p-value. In case the actual recorded TBM grade differs from the TBM grade
8|used in the stratified randomization, the actual TBM grade will be used.
9|
10|The proportional hazards assumption will be formally tested based on scaled Schoenfeld residuals and
11|visually assessed by a plot of the scaled Schoenfeld residuals versus transformed time (as implemented
12|in R function survival::cox.zph). In case of a significant test, a formal comparison of 9 month survival
13|probabilities between the two groups will also be performed (using Kaplan-Meier estimation and
14|Greenwood's formula to approximate variance).
15|
16|Kaplan-Meier estimates of the survival curve by treatment arm
17|-
18|Plots for all patients and subgroups defined by HIV status and TBM grade
19|-
20|Explicit numeric estimates (with 95% CI) at 3, 6, and 9 months for all patients and by subgroups
21|
22|Cox regression
23|
24|Include the following baseline covariates (in addition to the treatment group): TBM severity (grade I,
25|II, III), HIV status (positive/negative), participating (admission) hospital (PNT/HTD), previous TB
26|episode (yes/no), drug resistance category (MDR-TB / rifampicin (mono-)resistant / isoniazid
27|resistant / no or other resistance; subjects without a resistance result will be treated as a separate
28|category "unknown resistance" for the purpose of the Cox regression).
29|Note: The protocol specified "previous TB treatment" rather than "previous TB" episode but only
30|the latter was collected on the CRF.
31|
32|A separate analysis for HIV positive patients only including the above covariates and additionally
33|prior ARV therapy (yes/no) and CD4 cell count at baseline.
34|
35|Note: Derivation rules for the baseline covariates are as per the "Baseline characteristics" section above.
36|
37|Pre-defined subgroup analyses
38|
39|The following subgroups are pre-defined:
40|
41|Per protocol analysis
42|
43|TBM grade (I, II, or III)
44|
45|HIV status (positive/negative)
46|
47|Previous TB episode (yes/no)*
48|
49|On TB treatment at enrolment (yes/no)*
50|
51|TBM diagnostic category (definite / probable / possible) - Note: this is not mentioned in the
52|protocol but formally added as a pre-defined subgroup analysis in this analysis plan
53|
54|drug resistance (MDR-TB (including rifampicin (mono-)resistant, if any) / isoniazid resistant / no or
55|other resistance) - only culture-confirmed patients (in CSF) will be included in this analysis
56|* replacing the pre-defined subgroup "previous TB treatment" which was not collected on the CRF.
```

## nejmoa1507062_protocol.pdf, physical page 35, lines 1–27

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[]`

```text
1|
2|05TB
3|Protocol 11.0 dated 24FEB11
4|33/63
5|11 Interim analysis and role of the Data and Safety Monitoring Committee (DSMC)
6|An independent DSMC will oversee the trial. Interim analyses are planned after 20 deaths, additionally
7|after 6 and 12 months of recruitment and yearly thereafter until the completion of the trial. The DSMC
8|will be provided with unblinded survival curves and summary tables of grade 3&4 and serious adverse
9|events. Tables will be prepared by the DSMC statistician and distributed to all DSMC members for
10|review; the study statistician will remain blinded throughout the study..
11|Based on these data, the committee has to make one of the following recommendations:
12|•
13|Continue the trial without modification
14|•
15|Continue the trial with modification
16|•
17|Stop the trial due to safety concerns
18|Unless the benefit of intensified treatment is shown "beyond reasonable doubt" at an interim analysis, no
19|formal stopping for efficacy is foreseen. The Haybittle-Peto boundary, requiring p<0.001 at interim
20|analysis to consider stopping for efficacy, should be used as a guidance. However, the DSMB
21|recommendation should not be based purely on statistical tables but also requires clinical judgment.
22|As the dissemination of preliminary summary data could influence the further conduct of the trial and
23|introduce bias, access to interim data and results will be confidential and strictly limited to the involved
24|independent statistician and the monitoring board and results (except for the recommendation) will not be
25|communicated to the outside and/or clinical investigators involved in the trial.
26|
27|
```

## nejmoa1507062_protocol.pdf, physical page 98, lines 19–42

Original SHA: `sha256:3b3d9a35dafd54331f425393b12b709c5da9a66d7fc4e15768f2c969c0de72d1`

Completed delivery refs: `[{"stage": "assessment", "line": 96, "order": 71, "start_line": 1, "end_line": 42, "numbered_body_sha256": "5a5334b500a1c964ba74c3b00a631abf0bd0f8193370b8e559863bea3a1d5543"}]`

```text
19|following patients: patients with a final diagnosis other than TBM major protocol violations and those
20|receiving less than 2 months of administration of the randomized study drug for reasons other than death.
21|
22|11 Interim analysis and role of the Data and Safety Monitoring Committee (DSMC)
23|An independent DSMC will oversee the trial. Interim analyses are planned after 20 deaths, additionally
24|after 6 and 12 months of recruitment and yearly thereafter until the completion of the trial. The DSMC
25|will be provided with unblinded survival curves and summary tables of grade 3&4 and serious adverse
26|events. Tables will be prepared by the DSMC statistician and distributed to all DSMC members for
27|review; the study statistician will remain blinded throughout the study..
28|Based on these data, the committee has to make one of the following recommendations:
29|•
30|Continue the trial without modification
31|•
32|Continue the trial with modification
33|•
34|Stop the trial due to safety concerns
35|Unless the benefit of intensified treatment is shown "beyond reasonable doubt" at an interim analysis, no
36|formal stopping for efficacy is foreseen. The Haybittle-Peto boundary, requiring p<0.001 at interim
37|analysis to consider stopping for efficacy, should be used as a guidance. However, the DSMB
38|recommendation should not be based purely on statistical tables but also requires clinical judgment.
39|As the dissemination of preliminary summary data could influence the further conduct of the trial and
40|introduce bias, access to interim data and results will be confidential and strictly limited to the involved
```

## NEJMoa1507062.pdf, physical page 4, lines 4–23

Original SHA: `sha256:b8673a2adc2d00a14919712c76c6c0c2ff6bbd6e684501a54c89683d8196a01a`

Completed delivery refs: `[{"stage": "proposal", "line": 22, "order": 9, "start_line": 1, "end_line": 105, "numbered_body_sha256": "f8283687eeefb97d68b3a9c40f17b43ae2fd055bdca5fd1774cf9629e096f4ac"}, {"stage": "assessment", "line": 12, "order": 30, "start_line": 1, "end_line": 105, "numbered_body_sha256": "f8283687eeefb97d68b3a9c40f17b43ae2fd055bdca5fd1774cf9629e096f4ac"}]`

```text
4|enrolling physicians, and investigators remained
5|unaware of the treatment assignments until the
6|last patient completed follow-up. The attending
7|physicians were responsible for enrolling the
8|participants and for ensuring that the study
9|drug was given from the correct treatment pack.
10|Daily monitoring of all inpatients by one of the
11|investigators ensured uniform management be-
12|tween the study sites and accurate recording of
13|clinical data in individual study notes.
14|Outcome Assessments
15|The condition of the patients was reviewed daily
16|until discharge from the hospital for assessment
17|of clinical progress and neurologic and drug-
18|related adverse events. After discharge, monthly
19|visits were scheduled for clinical evaluation and
20|laboratory monitoring until the completion of
21|treatment at 9 months.
22|The primary outcome was death by 9 months
23|after randomization. The secondary outcomes
```

## NEJMoa1507062.pdf, physical page 4, lines 62–103

Original SHA: `sha256:b8673a2adc2d00a14919712c76c6c0c2ff6bbd6e684501a54c89683d8196a01a`

Completed delivery refs: `[{"stage": "proposal", "line": 22, "order": 9, "start_line": 1, "end_line": 105, "numbered_body_sha256": "f8283687eeefb97d68b3a9c40f17b43ae2fd055bdca5fd1774cf9629e096f4ac"}, {"stage": "assessment", "line": 12, "order": 30, "start_line": 1, "end_line": 105, "numbered_body_sha256": "f8283687eeefb97d68b3a9c40f17b43ae2fd055bdca5fd1774cf9629e096f4ac"}]`

```text
62|The statistical analysis followed the protocol13
63|and the statistical analysis plan (see the Supple-
64|mentary Appendix). The primary outcome was
65|analyzed in all patients and in prespecified
66|subgroups, with the analysis based on the Cox
67|proportional-hazards model with stratification
68|according to HIV infection status and MRC grade.
69|The ordinal disability score was compared be-
70|tween the two study groups with a proportional-
71|odds logistic-regression model with adjustment
72|for HIV infection status and MRC grade. Second-
73|ary time-to-event outcomes were analyzed in the
74|same way as the primary outcome. Additional
75|prespecified multivariable Cox regression analy-
76|ses and analyses of the disability score were
77|based on multiple imputation of missing covari-
78|ates and disability outcomes, as detailed in the
79|statistical analysis plan.
80|The primary analysis population was the inten-
81|tion-to-treat population, which included all pa-
82|tients who underwent randomization. The analy-
83|sis of the primary outcome was repeated in the
84|per-protocol population, which did not include
85|patients with unlikely tuberculous meningitis or
86|an alternative diagnosis according to the diagnos-
87|tic criteria,14 patients with multidrug-resistant
88|infections, or patients who received less than
89|50 days of treatment with the study drug for
90|reasons other than death. All statistical analyses
91|were performed with the statistical software R,
92|version 3.1.2.20
93|Results
94|Study Population
95|From April 18, 2011, through June 18, 2014, a
96|total of 817 adult patients were randomly assigned
97|to receive standard antituberculosis treatment plus
98|either placebo (409 patients; standard-treatment
99|group) or additional rifampin and levofloxacin
100|(408 patients; intensified-treatment group). A total
101|of 53 patients (28 in the standard-treatment group
102|and 25 in the intensified-treatment group) did not
103|complete follow-up for reasons other than death.
```

## NEJMoa1507062.pdf, physical page 8, lines 173–182

Original SHA: `sha256:b8673a2adc2d00a14919712c76c6c0c2ff6bbd6e684501a54c89683d8196a01a`

Completed delivery refs: `[{"stage": "proposal", "line": 24, "order": 10, "start_line": 1, "end_line": 184, "numbered_body_sha256": "68accd26e9aac2d6ec8cbd24630a6b3db160a5bc1cf30ef27b0ef17cc1005227"}, {"stage": "assessment", "line": 14, "order": 31, "start_line": 1, "end_line": 184, "numbered_body_sha256": "68accd26e9aac2d6ec8cbd24630a6b3db160a5bc1cf30ef27b0ef17cc1005227"}]`

```text
173|Figure 2. Kaplan-Meier Curves for Overall Survival
174|According to Treatment Group and HIV Infection Status.
175|In accordance with the statistical analysis plan, all deaths
176|in the database were included in the final analysis; this
177|included two deaths on days 274 and 275. Because the
178|9-month follow-up visit was on days 270 through 272
179|for most patients, the numbers of patients at risk on
180|days 274 and 275 were low, which accounts for the
181|sharp decrease in the Kaplan-Meier curves at the end
182|of the study period.
```
