# Domain 3: bias due to missing outcome data

Source: RoB 2 full guidance, section 6 and Box 8, plus the Cochrane RoB 2 FAQ
for 3.1 and 3.2. The complete official text is returned by `get_domain_context`.

Missing outcome data bias the result only if whether an outcome is missing
depends on its true value. The questions move from "how much is missing" (3.1)
to "is there evidence the result is robust" (3.2) to "could" (3.3) and "is it
likely" (3.4) that missingness depended on the outcome.

## Read first

Read the CONSORT flow diagram, the participant flow text, the results table for
this Result (its denominators per arm), the statistical analysis section on
missing data and imputation, and any sensitivity analyses. Supplements and
registry results often carry the flow and per-arm counts.

## Count the right participants

For this Result's time point, keep these distinct per arm: randomized;
outcome observed; analysed; imputed; excluded after randomization; and outcome
events. Imputed outcomes count as missing. Participants who stopped treatment
but were still followed up and measured are not missing. In time-to-event
analyses, participants censored because they withdrew or were lost count as
missing even though some follow-up is included. For a time-to-first-event
outcome, a participant with a dated first event has an observed outcome even if
later follow-up was lost; loss before any first event is missing. Do not add
component-level and composite follow-up counts together. Participants excluded despite
having outcome data belong to Domain 2 (2.6), not here. Missing outcome data are participants
whose outcome is missing, not missing individual measurements: a few missed
repeated tests matter only if they could change that participant's outcome
(for example a per-participant worst grade over follow-up).

## 3.1 (`sq:missing:data-available`) Were data for this outcome available for all, or nearly all, participants randomized?

"Nearly all" means the number missing is so small that their outcomes, whatever
they were, could have made no important difference to the estimate.

- Continuous outcomes: data from 95% of participants will often be sufficient.
- Dichotomous outcomes: compare missing participants with events. If observed
  events greatly outnumber participants with missing data, the bias is
  necessarily small.
- **No information:** only if the reports give no information about the extent
  of missing data. If only an estimate is reported, look for a CONSORT diagram
  or other sources; a probable answer is often possible.

## 3.2 (`sq:missing:evidence-unbiased`) If N/PN/NI to 3.1: is there evidence that the result was not biased by missing outcome data?

- **Yes / Probably yes:** analysis methods that correct for bias, or sensitivity
  analyses showing the result changes little across the plausible range of
  outcomes the missing participants could have had. Look for the assumptions
  the trialists made about missing participants ("we assumed that ...").
- **No / Probably no:** no such evidence. Last observation carried forward and
  multiple imputation based only on intervention group should not be assumed
  to correct bias. This question has no No information option.

## 3.3 (`sq:missing:true-value-dependent`) If N/PN to 3.2: could missingness in the outcome depend on its true value?

- **Yes / Probably yes:** loss to follow-up or withdrawal could be related to
  participants' health status. This is usually the case.
- **No / Probably no:** all missing data occurred for documented reasons
  unrelated to the outcome, such as a failed measuring device or interrupted
  routine data collection.

## 3.4 (`sq:missing:likely-dependent`) If Y/PY/NI to 3.3: is it likely that missingness depended on its true value?

This separates "could" (Some concerns) from "likely" (High). Reasons for Yes:

1. the proportions missing differ between groups (for time-to-event outcomes,
   different censoring rates);
2. reported reasons for missingness suggest dependence on the outcome;
3. reported reasons differ between groups;
4. the trial's circumstances make dependence likely (for example, continuing
   symptoms driving dropout);
5. in time-to-event analyses, follow-up is censored when participants stop or
   change their assigned intervention.

Answer **No** if the analysis accounted for participant characteristics likely
to explain the relationship between missingness and the outcome.

A mechanism that is merely plausible (health status could affect follow-up)
is the "could" of 3.3. Reason 4 needs circumstances where dependence is
widely understood to be likely, as in the schizophrenia example. When none of
the five reasons applies, for example similar proportions missing in each arm
with no reasons suggesting dependence, answer No or Probably no. How the
trialists' primary analysis handled missing participants is not itself a reason
for missingness.

For reasons 2 and 3, section 6.1.4.2 asks whether the reasons relate to the
true value of the outcome: lack of efficacy, recovery, worsening illness or
adverse experiences of one intervention. The case most likely to bias is
participants who became unwell leaving one group while those who recovered
left the other. Reasons unrelated to the outcome (an operation cancelled for
scheduling, moving away, a protocol violation, a failed device) do not suggest
dependence even when they differ between groups. For reason 1, compare the
counts with the numbers randomized: a difference of one or two participants is
not by itself evidence that missingness depended on the outcome.

## Algorithm

- **Low:** 3.1 Yes/Probably yes; or 3.2 Yes/Probably yes; or 3.3 No/Probably no.
- **High:** 3.4 Yes/Probably yes/No information.
- **Some concerns:** otherwise (3.4 No/Probably no).

## Participant-count rows

Questions 2.3, 2.6 and 3.1 may carry compact `missing_data` rows in
`save_domain_judgment`. Each row names an arm, population, unit and time point,
with source-supported `randomized`, `completed`, `observed`, `unavailable`,
`analyzed`, `imputed`, `excluded` or `event_count` counts. Leave `observed` unset when only analysed or
event counts are reported. The server computes `randomized - observed` (or uses
a supplied `unavailable` total) only when scopes match, and reports
differences, fractions and conflicts; it never chooses the answer. A row-level
`basis` adds Evidence for that row; omit it to reuse the answer's Evidence.

To preview the arithmetic before saving, pass the rows to `get_domain_context`
(each row then needs a current-Trial Evidence `basis`) and read
`comparison_cards[].missing_data`. The preview changes no state and is optional.

Use [Build a Domain answer](evidence.md#build-a-domain-answer) for the
submission shape.
