# Assess missing outcome data

Use this reference for Domain 3. The approved Result fixes the outcome and time
point; the returned question cards fix answer direction and activation.

## Availability audit

For D3.1, support Yes or Probably Yes with actual outcome-availability
evidence. Accept one or more of:

- comparable observed-outcome counts for the randomized population;
- arm-specific loss-to-follow-up or censoring rates, reasons, and follow-up
  accounting; or
- an explicit statement that ascertainment was complete or nearly complete.

The following do not establish affirmative availability on their own:

- analysis denominators or ITT membership;
- planned or scheduled follow-up;
- treatment continuation or discontinuation; or
- a generic censoring rule without actual rates or follow-up accounting.

For mortality, recovery or discharge does not establish vital status at a later
time point. A total combining completed follow-up, recovery, and death does not
establish mortality availability. If availability remains unresolved, inspect
outcome-status or missing-value tables, including supplements. Match their
outcome and time window to the approved Result. Recovery may inform bias from
missingness, but does not make unknown vital status observed.

## Reconcile availability

Keep these quantities distinct for each arm and time point:

- randomized participants;
- participants with the outcome observed;
- participants included in the reported analysis;
- participants whose outcomes were imputed; and
- post-randomization exclusions.

An analyzed count is not necessarily an observed count. Imputed outcomes count
as missing outcome data for RoB 2. Treatment discontinuation is not missing
outcome data when follow-up and outcome ascertainment continued.

If some outcomes are missing, assess whether data remain available for nearly
all randomized participants. Consider whether the missing outcomes could make
an important difference to this Result. For dichotomous outcomes, compare the
missing count with observed events, not only the randomized denominator.
A count below the randomized total does not settle that question.

Distinguish administrative censoring at a common data cutoff from censoring
caused by missing follow-up before the outcome could be observed. For time-to-event Results,
censoring may still create missing outcome information; assess its timing,
reason, and relation to treatment or prognosis instead of treating every
censored participant as either fully observed or missing by default.

Question 3.1 may include compact `missing_data` rows. Give each row a comparable
arm, population, unit, and time point. Use a row-level `basis` only to narrow or
add to the answer's Evidence. The server calculates differences and fractions
only after scopes match and preserves conflicting reports without choosing the
scientific answer.

When a count comparison would help before answering, call `get_domain_context`
with `missing_data` rows. Every preview row needs a nonempty `basis` containing
current-Trial Evidence references: no answer exists to supply inherited Evidence.
Inspect `comparison_cards[].missing_data`
for differences, fractions, and conflicting reports. The preview changes no
checkpoint or State revision. To retain the chosen rows, submit them with the
3.1 answer in `save_domain_judgment`; there, omit row `basis` to reuse the
answer's Evidence when it supports those counts.

Check each input against its source passage before using the arithmetic. The
helper subtracts supplied observed counts from randomized counts; it does not
extract counts or sum grouped departures. Keep unknown observed counts unknown.
Skip the preview when an explicit ascertainment statement resolves availability
without arithmetic.

## Assess bias from missingness

If data were not available for all or nearly all participants, ask in sequence:

1. Does a bias-correcting method or informative sensitivity analysis show that
   the Result was not biased?
2. Could missingness depend on the true outcome, based on reasons, health
   status, withdrawal, loss to follow-up, or censoring?
3. If it could, is that dependence likely given arm differences, reasons,
   prognostic factors, or trial circumstances?

Simple imputation, including last observation carried forward or multiple
imputation based only on intervention group, does not by itself show freedom from
bias. Documented reasons support reassurance only when they address the outcome
relationship.

Keep possible dependence in 3.3 separate from likely dependence in 3.4. For
3.4, state which reasons or trial circumstances support the likelihood judgment.
Absent contrary evidence alone does not establish likely dependence. Preserve
`no_information` when the card's uncertainty rule applies, even when that answer
leads to High risk of bias.

D3.2 does not allow `no_information`. When no bias-correcting evidence is found,
use the question card to choose a permitted negative or probably-negative answer
with the appropriate limitation or Evidence basis. Do not fabricate direct
support for the absence of bias.
