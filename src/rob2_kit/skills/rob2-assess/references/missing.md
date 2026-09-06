# Assess missing outcome data

Use this reference for Domain 3.

Identify the denominator for the approved Result before you assess completeness. Keep randomized enrollment, outcome-measurement coverage, analyzed population, and the denominator for each reported quantity separate.

Assess whether outcome data are available for all or nearly all participants. If data are missing, look for evidence that the result is not biased. Then assess whether missingness could depend on the true outcome and whether that dependence is likely.

For question 3.1, compare the approved outcome and time point with the flow
and outcome-data passages. One passage may establish complete ascertainment;
otherwise cite separate passages for randomized, observed, and analyzed
populations. Do not treat an analyzed denominator as observed data. For
example, a flow passage reporting 110 randomized and 105 analyzed participants
does not by itself identify five missing outcomes; the host must determine what
those exclusions represent.

Use one basis when it contains the complete premise. Use several bases when,
for example, a flow passage gives arm-specific counts and a results passage
explains imputation or censoring. Keep conflicting counts visible and explain
the comparison briefly in `justification`; the server only calculates a
randomized-minus-observed difference after scope, arm, unit, and time point
match.

Question 3.1 may include compact `missing_data` rows for those comparisons.
The server uses Evidence handles already attached to the answer as each row's
provenance. Set a row's optional `basis` only when the row is supported by a
specific subset or additional Evidence handle; do not repeat quotes or
canonical Evidence identities.

The active question card is authoritative. Its official excerpt and locator
define the proposition; the seeds and pitfalls below guide retrieval.

## Optional search leads from official guidance

- **Official guidance, p. 45, Box 8, question 3.1:** Consider completeness terms
  such as `missing outcome data`, `nearly all`, `randomized participants`, `95%`,
  `imputed`, `continuous outcomes`, and `dichotomous outcomes`.
- **Official guidance, p. 45, Box 8, question 3.2:** Consider bias-check terms
  such as `bias-correcting`, `sensitivity analyses`, `plausible assumptions`, `true
  value`, `last-observation-carried-forward`, and `multiple imputation`.
- **Official guidance, p. 45, Box 8, question 3.3:** Consider missingness-cause
  terms such as `loss to follow-up`, `withdrawal`, `health status`, `documented reasons`,
  `censoring`, and `treatment switching`.
- **Official guidance, pp. 45-46, Box 8, question 3.4:** Consider dependence and
  likelihood terms such as `missingness proportions`, `censoring rates`, `reasons differ`,
  `trial circumstances`, `stopping`, `changing assigned intervention`, and
  `participant characteristics`.

When useful, group completeness, bias checks, missingness causes, and dependence
terms separately. Refine a truncated discovery search before concluding that a
reason or analysis is not reported.

## Pitfalls

Do not infer complete data from an estimate, a flow-diagram count, a time origin,
an analysis population, or a planned follow-up schedule. Treat imputed data as
missing data. A 95% threshold often applies to continuous outcomes, while event
risk matters for dichotomous outcomes. Keep randomized enrollment, measured
coverage, analyzed population, and each reported denominator separate.

Absence of a reported problem is not evidence that missingness was harmless.
Documented reasons can support a low-risk conclusion only when they address the
outcome relationship.

Completion: every active Domain 3 question has a permitted answer, and the
answer addresses the proposition in its active question card.
