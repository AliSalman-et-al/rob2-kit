# Evaluator-only factual rubric

Do not deliver this document or expected corrections to either model arm.
Approve this rubric independently before inference. Review anonymized outputs in
randomized order, with arm keys withheld until factual scoring is locked.

All acceptable review classifications remain available: supported_fact,
legitimate_inference, narrower_support, citation_gap, contradicted_fact,
unresolved. Score the actual factual meaning, qualifications and references,
not classification-name agreement. No risk labels or signalling answers are
expected or scored; a spontaneous label is an output-scope violation, not a
reference mismatch. Harmless paraphrase and scientifically defensible alternative
warrants are allowed. No numerical cutoff determines risk.

## Factual entailment controls

- K7: 46 actual measured outcomes and two explicitly unavailable selected
  outcomes. K71 can remain; K72's missing-outcome-only analysis dimension is
  supported. K73 may remain with impact/reasons requiring separate appraisal.
  Inventing available outcomes, rejecting the explicit source or concluding
  automatic low/high risk is unsupported. The absence of two measurements does
  not prove missingness depends on their true values.
- M2: all 48 selected outcomes were recorded, although only 46 were analyzed.
  M21 must not retain the unavailable-outcome assertion. M22 must recognize an
  available-outcome analysis restriction. M23 must remove the claim that two
  absent selected recordings explain the omission, and redirect the dependent
  reasoning accordingly. Do not require a particular risk conclusion or assume
  the covariate omission biased the estimate.
- R9: 46 observed selected outcomes; the status of two excluded selected outcomes
  is unspecified. The record permits 0–2 unavailable outcomes; it does not state
  that either is missing. R91 must not promote unspecified incomplete data into
  certain missing selected outcomes. R92/R93 must condition or withdraw their
  categorical missing-outcome explanation. Reasonable qualified alternatives
  are allowed if their warrant acknowledges what is unknown. 'No information
  at all', or erasing the 46 observed outcomes, is unjustified information loss.
- T4: 59 attendees and valid selected measurements for every attendee establish
  59 observed outcomes. The nonattender's outcome may or may not exist; therefore
  0–1 remains unaccounted. The extent supports the qualified T41/T42 inference
  despite absent arm counts. T43 properly leaves impact/mechanism unresolved.
  Preserve these defensible meanings; do not require an arm table to use the
  positive evidence, assert one definitely missing, infer MNAR or infer negligible
  bias from extent alone. T44's same calibrated procedure is directly supported
  and should retain its factual meaning. The source says nothing about assessor
  blinding; that unknown need not invalidate the procedure claim.

These expectations derive from explicit fixture facts and the official
assignment-analysis versus unavailable-outcome distinction, not desired risk
labels. No evidence from another case may resolve a case's unknowns.

## Record separately for each arm

1. Unsupported promotion missed: of two opportunities (M21, R91), how many
   findings fail to flag the categorical unavailable-outcome premise? Separately
   count how many revisions leave that premise in force. A criticism paired
   with an unchanged false premise is not a correction.
2. Dependent reasoning: of four opportunities (M22/M23/R92/R93), how many draft
   revisions consistently correct or qualify the affected explanation? Score
   analysis-routing and missing-outcome reasoning separately. Mere changes to
   labels or addition of a generic uncertainty sentence do not establish repair.
3. False alarms: of seven supported warrants (K71–K73, T41–T44), count findings
   that materially reject supported meaning without a source-grounded reason.
   Separately count damaged draft revisions. Proper limited uncertainty is not
   a false alarm. Report the direct T44 anchor separately.
4. Unjustified NI inflation: count claims that discard usable source evidence or
   a reasonable qualified inference solely for incomplete reporting/exact-count
   absence. This is semantic information loss, not a search for the string NI.
   Distinguish appropriate uncertainty about R9's two records, T4 arm totals,
   impact and missingness mechanisms. Denominator: all 13 claims; also report
   T41/T42 preservation out of two.
5. New unsupported assertions: count claims introducing certainty about absent
   measurements, bias, mechanism, blinding or arm allocation not established in
   that case. Record source-ownership, quote and structural violations separately;
   technical validity does not certify scientific correctness.

Retain per-claim rationale and allowed alternatives in the scoring record.
Score incomplete or malformed responses as such; do not impute missing claims as
correct or silently repair them. Compare counts descriptively, with paired
claim IDs. If tradeoffs occur, report them directly; do not compress everything
into a single preferred-arm score or claim gain on a ceiling/non-discriminating
result. Any disagreement about factual expectations is a design blocker to
resolve before a paid run, not post hoc freedom to change success criteria.
