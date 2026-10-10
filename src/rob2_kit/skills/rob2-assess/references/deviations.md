# Domain 2: bias due to deviations from intended interventions (effect of assignment)

Source: RoB 2 full guidance, section 5 and Box 6, assessed for the effect of
assignment to intervention (the intention-to-treat effect). The complete
official text is returned by `get_domain_context`.

For the effect of assignment, this domain has two parts. Questions 2.1-2.5 ask
whether the trial context caused deviations from the protocol that could bias
the result. Questions 2.6-2.7 ask whether participants were analysed in the
groups to which they were randomized.

## Read first

Read the blinding description (participants, carers, people delivering the
interventions), the intervention delivery and adherence sections, any reported
crossover, contamination or co-intervention, the CONSORT flow, and the
statistical analysis section that defines the analysis population for this
Result. Check the protocol or SAP for the planned analysis population.

## 2.1 Were participants aware of their assigned intervention during the trial?
## 2.2 Were carers and people delivering the interventions aware of participants' assigned intervention?

- **No / Probably no:** blinded, for example by a placebo or sham with matching
  appearance, and nothing suggests the blinding failed.
- **Yes / Probably yes:** open-label or unblinded delivery; interventions that
  cannot be hidden (surgery versus medical care, exercise versus none); side
  effects or toxicities known to be specific to one intervention. For 2.2, if
  allocation was not concealed, carers were probably aware.
- "Double blind" alone does not say who was blinded; read who was masked.

## 2.3 If Y/PY/NI to 2.1 or 2.2: were there deviations from the intended intervention that arose because of the trial context?

Trial context means effects of recruitment and engagement activities on
participants, or trial personnel undermining the protocol in ways that would not
happen outside the trial (for example comparator participants seeking the
experimental intervention, or clinicians giving non-protocol co-interventions in
one group because of their beliefs).

- **Yes / Probably yes:** only with evidence, or strong reason to believe, that
  the trial context led to failure to implement the protocol interventions or
  to interventions not allowed by the protocol.
- **No / Probably no:** deviations that could equally occur outside the trial,
  such as ordinary non-adherence; changes consistent with the protocol, such as
  stopping a drug for toxicity or treating consequences of an intervention; or
  no reported deviations of this kind in a trial whose report describes
  intervention delivery and adherence.
- **No information:** the report does not describe what happened to delivery
  and co-interventions well enough to judge. The guidance notes this may be
  appropriate because trialists rarely say why deviations occurred.

Deducing the assigned intervention does not by itself cause bias. Dropout is
assessed in Domain 3, not here.

## 2.4 If Y/PY to 2.3: were these deviations likely to have affected the outcome?

They affect the estimate only if they affect the outcome.

## 2.5 If Y/PY/NI to 2.4: were these deviations balanced between groups?

Unbalanced deviations are more likely to bias the estimate.

## 2.6 Was an appropriate analysis used to estimate the effect of assignment?

Classify each randomized participant missing from this Result's analysis by the
reason they are missing, and count each participant once:

- **Appropriate (Yes / Probably yes):** intention-to-treat analysis; modified
  ITT that excludes only participants with missing outcome data (lost to
  follow-up, withdrew, missed the measurement, died before it). Those
  participants are assessed in Domain 3, not here. Post-randomization exclusion
  of participants found ineligible, when eligibility could not have been
  influenced by assignment, can also be appropriate.
- **Inappropriate (No / Probably no):** naive per-protocol analysis (excluding
  participants who did not receive or complete their assigned intervention);
  as-treated analysis (grouping by intervention received); excluding eligible
  participants after randomization even though their outcome could be measured.
- **No information:** the report does not say who was analysed or how.

## 2.7 If N/PN/NI to 2.6: was there potential for a substantial impact of the failure to analyse participants in their randomized groups?

Consider the number analysed in the wrong group or excluded, relative to the
number of outcome events and the size of the effect. There is no fixed
threshold: fewer than 5% can matter if the outcome is rare or the exclusions are
strongly related to prognosis.

## Algorithm

- **High:** 2.3 Yes/Probably yes, 2.4 Yes/Probably yes/No information and 2.5
  No/Probably no/No information; or 2.6 No/Probably no/No information and 2.7
  Yes/Probably yes/No information.
- **Some concerns:** 2.3 No information; or 2.4 No/Probably no; or 2.5
  Yes/Probably yes; or 2.7 No/Probably no.
- **Low:** otherwise (for example participants and carers blinded, or no
  context deviations, with an appropriate analysis).

When counts help 2.3 or 2.6, `missing_data` rows can carry them; see
[Missing outcome data](missing.md#participant-count-rows). Use
[Build a Domain answer](evidence.md#build-a-domain-answer) for the submission
shape.
