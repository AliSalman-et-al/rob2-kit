# Domain 4: bias in measurement of the outcome

Source: RoB 2 full guidance, section 7 and Box 10, plus the Cochrane RoB 2 FAQ
for 4.3. The complete official text is returned by `get_domain_context`.

This domain is mainly about differential measurement error: error related to
the assigned intervention, which is less likely when assessors are blinded.

## Read first

Read the outcome definition and how and when it was measured for each group;
who assessed it (the participant, the clinician delivering care, an independent
assessor or adjudication committee, an automated test); and who was blinded to
assignment. For a composite, identify which components drive the events.

## Identify the outcome type and assessor

| Outcome type | Assessor | Can knowledge of assignment influence it? |
| --- | --- | --- |
| Participant-reported (pain, quality of life, symptom scores) | The participant, even if a blinded interviewer records the answers | Yes |
| Observer-reported, no judgement (all-cause mortality, automated laboratory value) | The observer | Usually not |
| Observer-reported, some judgement (clinical examination, imaging read, events other than death adjudicated from records) | The observer | Yes, if aware |
| Intervention-provider decision (hospitalization, discharge, stopping treatment, caesarean section) | The care provider making the decision | Usually yes, if aware |
| Composite | Each component's assessor | Judge by the most influential components |

## 4.1 Was the method of measuring the outcome inappropriate?

For pre-specified outcomes this is usually **No / Probably no**. Answer **Yes**
only if the method is unlikely to be sensitive to plausible effects, or the
instrument has demonstrated poor validity. This question does not judge whether
the outcome itself (for example a surrogate) was a sensible choice.

## 4.2 Could measurement or ascertainment of the outcome have differed between groups?

- **No / Probably no:** the same methods and thresholds at comparable times in
  both groups. This is usually the case for pre-specified outcomes.
- **Yes / Probably yes:** passive collection where one intervention prompts more
  testing or visits (diagnostic detection), or an intervention involving extra
  contacts that create more opportunities to detect events.

4.2 is about the measurement method, thresholds, timing and opportunities for
detection. Whether assessors knew the assignment is not a difference in method:
it is assessed in 4.3-4.5.

## 4.3 If N/PN/NI to 4.1 and 4.2: were outcome assessors aware of the intervention received?

Identify the assessor from the table above first. For participant-reported
outcomes the participant is the assessor, so answer as for 2.1. Answer **No**
if the assessor was blinded. In a double-blind trial with a matching placebo,
assessors are aware only if the sources report unblinding or there is a strong
reason, such as distinctive effects known to be specific to one intervention
that the assessor would observe; a theoretical possibility is not enough. "Double blind" alone does not say whether the
outcome assessor was blinded; read who was masked. A blinded adjudication
committee makes assessors unaware for the events it classifies, but not for an
earlier clinical decision by an aware care provider that the outcome records.

## 4.4 If Y/PY/NI to 4.3: could assessment of the outcome have been influenced by knowledge of intervention received?

- **No / Probably no:** observer-reported outcomes not involving judgement,
  such as all-cause mortality or an automated test, even when assessors knew
  the assignment.
- **Yes / Probably yes:** participant-reported outcomes, observer-reported
  outcomes involving judgement, and intervention-provider decisions.

## 4.5 If Y/PY/NI to 4.4: is it likely that assessment was influenced by knowledge of intervention received?

This separates "could" (Some concerns) from "likely" (High). Influence is more
likely when there are strong beliefs in either beneficial or harmful effects
of the intervention, for example participant-reported symptoms in trials of
homeopathy, or recovery of function assessed by the physiotherapist who
delivered the intervention. Awareness alone does not make influence likely; a severe or
unexpected harm recorded long after starting the intervention is unlikely to
be influenced.

## Algorithm

- **High:** 4.1 Yes/Probably yes; or 4.2 Yes/Probably yes; or 4.5 Yes/Probably
  yes/No information.
- **Some concerns:** 4.2 No information; or 4.5 No/Probably no.
- **Low:** otherwise (for example assessors blinded, or influence not possible).

Do not count one mechanism in both Domains 2 and 4: a change in care that
changes the true outcome belongs to Domain 2; a change in how the outcome is
measured, recorded or decided belongs here. Use
[Build a Domain answer](evidence.md#build-a-domain-answer) for the submission
shape.
