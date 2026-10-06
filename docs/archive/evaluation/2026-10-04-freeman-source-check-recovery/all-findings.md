# Freeman D3 recovery: all findings

Post-freeze appraisal by the implementation AI; independent parent review remains pending. This is not clinician adjudication or a reference gold standard. Findings are listed without changing the frozen response. Page numbers are physical captured PDF pages; line numbers belong to the saved text projection. All references below use main article `sh_08c08c63f9bf7b55`.

The reviewer flagged neither of the two predeclared underlying errors (cross-arm adherence, original age/sex citation gap). The cross-arm error occurs twice. No adverse scientific false-positive flag was emitted; that does not offset false assurance. All 27 quotation bindings fail the complete literal-window contract; 13 are verbatim excerpts after whitespace normalization, which is diagnostic only. Findings 2, 8 and 11 additionally join separate saved entries. No quotation repair or canonical change was made.

## Finding 1: supported_fact — justification

Correct selected-arm analysis and completion counts; preserves observed-versus-imputed uncertainty. Whole warrant mixes fact and inference.

Source windows (literal, preserving line breaks):

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

Main article p5, lines 31–51; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
46|10 completed treatment
47|11 included in intention-
48|to-treat analysis
49|23 included in final intention-
50|
51|to-treat analysis
```

Main article p5, lines 75–103; original saved citation: False.

```text
75|12 allocated to cannabidiol
76|
77|400 mg
78|1 did not receive
79| allocated intervention
80| (drop-out)
81| 1 use of psychotropic
82|
83|medication during
84|
85|treatment
86|12 allocated to cannabidiol
87|
88|400 mg
89|11 completed treatment and
90|
91|12 included in intention-
92|
93|to-treat interim analysis
94|All received allocated
95|intervention
96|12 completed treatment and
97|
98|were included in intention-
99|
100|to-treat analysis
101|24 included in final intention-
102|
103|to-treat analysis
```

Main article p5, lines 4–5; original saved citation: False.

```text
4|THC-COOH:creatinine ratio and days per week with
5|abstinence from cannabis during treatment weeks 1-4.
```

## Finding 2: supported_fact — unknowns

Preserves unknown urine availability; joins two separate saved unknown entries, violating clause binding.

Source windows (literal, preserving line breaks):

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

Main article p5, lines 31–51; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
46|10 completed treatment
47|11 included in intention-
48|to-treat analysis
49|23 included in final intention-
50|
51|to-treat analysis
```

## Finding 3: legitimate_inference — counterevidence

Defensible retention counterclaim; does not equate ITT membership with observed outcomes.

Source windows (literal, preserving line breaks):

Main article p5, lines 31–51; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
46|10 completed treatment
47|11 included in intention-
48|to-treat analysis
49|23 included in final intention-
50|
51|to-treat analysis
```

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

## Finding 4: legitimate_inference — justification

Defensible MAR limitation and globally true age/sex fact, but misses the original citation gap. Follow-up support is not original attribution.

Source windows (literal, preserving line breaks):

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

Main article p6, lines 7–15; original saved citation: False.

```text
7|generalised linear regression models assuming a gamma
8|distribution. We used logistic regression models for
9|binomial count outcomes (eg, the number of days with
10|abstinence from cannabis in a week). We did post-hoc
11|sensitivity analyses adding age and sex to primary
12|endpoint models. Secondary endpoints were analysed at
13|the final analysis only. We analysed cannabis use (urinary
14|THC-COOH:creatinine and days per week with abstin
15|ence) up to the final follow-up as secondary endpoints.
```

Main article p7, lines 11–20; original saved citation: False.

```text
11|cannabidiol 200 mg, 0·9354 for cannabidiol 400 mg,
12|and 0·8660 for cannabidiol 800 mg (appendix p 6).
13|Therefore, the cannabidiol 200 mg group was eliminated
14|from the trial after the first stage and no additional
15|participants were assigned to this group. Post-hoc
16|sensitivity analyses including age and sex did not
17|change the pattern of results.
18|In the second stage of the trial, an additional
19|34 participants were randomly assigned (1:1:1) to the
20|remaining groups of placebo (n=11), cannabidiol
```

## Finding 5: unresolved — unknowns

Honest scoped uncertainty about missingness assumptions; no mandatory MNAR analysis invented.

Source windows (literal, preserving line breaks):

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

Main article p6, lines 7–15; original saved citation: False.

```text
7|generalised linear regression models assuming a gamma
8|distribution. We used logistic regression models for
9|binomial count outcomes (eg, the number of days with
10|abstinence from cannabis in a week). We did post-hoc
11|sensitivity analyses adding age and sex to primary
12|endpoint models. Secondary endpoints were analysed at
13|the final analysis only. We analysed cannabis use (urinary
14|THC-COOH:creatinine and days per week with abstin
15|ence) up to the final follow-up as secondary endpoints.
```

## Finding 6: legitimate_inference — counterevidence

Defensible: principled MAR imputation is not proof against outcome-dependent missingness.

Source windows (literal, preserving line breaks):

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

## Finding 7: legitimate_inference — justification

Misses cross-arm contamination: poor adherence belongs to eliminated CBD200, not selected CBD400/placebo. Possible dependence remains a defensible inference.

Source windows (literal, preserving line breaks):

Main article p1, lines 74–82; original saved citation: True.

```text
74|cannabis use disorder criteria from DSM-5 were randomly assigned (1:1:1:1) in the first stage of the trial to
75|4-week treatment with three different doses of oral cannabidiol (200 mg, 400 mg, or 800 mg) or with matched placebo
76|during a cessation attempt by use of a double-blinded block randomisation sequence. All participants received a brief
77|psychological intervention of motivational interviewing. For the second stage of the trial, new participants were
78|randomly assigned to placebo or doses deemed efficacious in the interim analysis. The primary objective was
79|to identify the most efficacious dose of cannabidiol for reducing cannabis use. The primary endpoints were lower
80|urinary 11-nor-9-carboxy-δ-9-tetrahydrocannabinol (THC-COOH):creatinine ratio, increased days per week with
81|abstinence from cannabis during treatment, or both, evidenced by posterior probabilities that cannabidiol is better
82|than placebo exceeding 0·9. All analyses were done on an intention-to-treat basis. This trial is registered with
```

Main article p5, lines 31–45; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
```

Main article p5, lines 107–115; original saved citation: False.

```text
107|2 did not receive
108| allocated intervention
109| (drop-out)
110| 1 missed scheduled
111|
112|visits
113| 1 poor medication
114|
115|adherence
```

## Finding 8: unresolved — unknowns

Preserves unknown dependence and arm differences; joins two saved unknown entries, violating clause binding.

Source windows (literal, preserving line breaks):

Main article p5, lines 31–45; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
```

Main article p4, lines 108–113; original saved citation: False.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

## Finding 9: supported_fact — counterevidence

False assurance on repeated cross-arm adherence fact; psychotropic medication does belong to CBD400. Same underlying error as finding 7.

Source windows (literal, preserving line breaks):

Main article p5, lines 75–85; original saved citation: False.

```text
75|12 allocated to cannabidiol
76|
77|400 mg
78|1 did not receive
79| allocated intervention
80| (drop-out)
81| 1 use of psychotropic
82|
83|medication during
84|
85|treatment
```

Main article p5, lines 107–115; original saved citation: False.

```text
107|2 did not receive
108| allocated intervention
109| (drop-out)
110| 1 missed scheduled
111|
112|visits
113| 1 poor medication
114|
115|adherence
```

## Finding 10: legitimate_inference — justification

Correct noncompletion counts; explicitly treats completion as a proxy, not observed urine availability. Plausible versus likely distinction retained.

Source windows (literal, preserving line breaks):

Main article p5, lines 31–51; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
46|10 completed treatment
47|11 included in intention-
48|to-treat analysis
49|23 included in final intention-
50|
51|to-treat analysis
```

Main article p5, lines 75–103; original saved citation: False.

```text
75|12 allocated to cannabidiol
76|
77|400 mg
78|1 did not receive
79| allocated intervention
80| (drop-out)
81| 1 use of psychotropic
82|
83|medication during
84|
85|treatment
86|12 allocated to cannabidiol
87|
88|400 mg
89|11 completed treatment and
90|
91|12 included in intention-
92|
93|to-treat interim analysis
94|All received allocated
95|intervention
96|12 completed treatment and
97|
98|were included in intention-
99|
100|to-treat analysis
101|24 included in final intention-
102|
103|to-treat analysis
```

## Finding 11: unresolved — unknowns

Preserves unknown actual missingness and retention dependence; joins two saved unknown entries, violating clause binding.

Source windows (literal, preserving line breaks):

Main article p5, lines 31–51; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
46|10 completed treatment
47|11 included in intention-
48|to-treat analysis
49|23 included in final intention-
50|
51|to-treat analysis
```

Main article p4, lines 108–113; original saved citation: True.

```text
108|All analyses were done on an intention-to-treat basis.
109|Missing data were handled using Bayesian multiple
110|imputation under the assumption of missing at random.
111|The missing outcomes were automatically simulated
112|from the Bayesian procedure, in accordance with the
113|modelling and distributional assumptions. The same
```

## Finding 12: legitimate_inference — counterevidence

Defensible possibility counterclaim without asserting demonstrated likely dependence.

Source windows (literal, preserving line breaks):

Main article p1, lines 74–82; original saved citation: False.

```text
74|cannabis use disorder criteria from DSM-5 were randomly assigned (1:1:1:1) in the first stage of the trial to
75|4-week treatment with three different doses of oral cannabidiol (200 mg, 400 mg, or 800 mg) or with matched placebo
76|during a cessation attempt by use of a double-blinded block randomisation sequence. All participants received a brief
77|psychological intervention of motivational interviewing. For the second stage of the trial, new participants were
78|randomly assigned to placebo or doses deemed efficacious in the interim analysis. The primary objective was
79|to identify the most efficacious dose of cannabidiol for reducing cannabis use. The primary endpoints were lower
80|urinary 11-nor-9-carboxy-δ-9-tetrahydrocannabinol (THC-COOH):creatinine ratio, increased days per week with
81|abstinence from cannabis during treatment, or both, evidenced by posterior probabilities that cannabidiol is better
82|than placebo exceeding 0·9. All analyses were done on an intention-to-treat basis. This trial is registered with
```

Main article p5, lines 31–45; original saved citation: False.

```text
31|12 allocated to placebo
32|1 did not receive
33| allocated intervention
34| (drop-out)
35| 1 lost to follow-up
36|11 allocated to placebo
37|11 completed treatment
38|12 included in intention-
39|to-treat interim analysis
40|1 did not receive
41| allocated intervention
42| (drop-out)
43| 1 missed scheduled
44|
45|visits
```
