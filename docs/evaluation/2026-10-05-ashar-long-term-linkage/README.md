# Ashar long-term pooled-control result: offline linkage check

**Decision:** supports an explicitly qualified result-linked diagnostic stratum, with unresolved
numerical and missing-data details. It is materially different from the locked Code primary
result and must remain in a separately versioned diagnostic dataset. This is a preparation
record, not an assessment, prediction or certified exact match. Ashar has development exposure;
it is not held out. No paid run or original corpus/label change.

## Independently verified source facts

The [review appendix](https://ars.els-cdn.com/content/image/1-s2.0-S2665991325000645-mmc1.pdf)
was freshly downloaded and hashed; web opening failed but direct retrieval succeeded.
Printed p42/PDF43 was rendered and visually inspected because the plot/grid is image-based.
The Ashar row shows **MD −13.900/100, 95% CI −19.776 to −8.024**, PRT n50 versus control n101.
Thus the supplied −13.8 is a reconstruction approximation, not the printed forest estimate.
Its domain grid is Some concerns / Low / Some concerns / Some concerns / Some concerns,
overall High. The row is explicitly long-term pain intensity, not a generic trial label.
[Row crop](reference-row.png) and [source facts/hashes](source-facts.json) preserve provenance.
Full retrieved PDF remains at the recorded private local path; original trial PDF remains
read-only in the required Code benchmark repository.

Printed p4/PDF5 defines long-term as 12 months to less than two years from baseline, choosing
the point closest to 12 months. Printed p11/PDF12 converts scales to 0–100 and combines
eligible same-class comparators by sample-size weighted means and pooled SDs. Its formula
was visually inspected. Printed pp5–7/PDF6–8 describes review-specific RoB2 conventions and
checks for different decisions by outcome, time and comparator. The conventions include
pragmatic D3/D4 assumptions and an overall rule of three or more Some concerns producing
High. These are human-reference conventions, not automatically authoritative Cochrane rules
or reasons to alter production algorithms. The grid alone does not supply each answer's warrant.

Trial Table2, printed p19/PDF7, gives 12-month means (SD): PRT 1.51 (1.59), placebo 2.79
(1.78), usual care 3.00 (1.77), all on 0–10. Figure1, printed p15/PDF3, gives randomized
50/51/50 and 12-month monitored 45/43/36. Published review n50/101 therefore matches randomized
allocation, **not observed follow-up n45/79**. Table2 notes available follow-up and corresponding
baseline data for effect-size calculation. Primary mixed-model ITT and missing-as-nonresponder
binary analyses on printed p16/PDF4 do not establish ITT imputation for continuous follow-up means.
Trial follow-up is described as months posttreatment, while the review's window starts at
baseline; nominal 12-month follow-up fits the broad window, not an asserted exact baseline clock.

## Numerical reconstruction and remaining uncertainty

Using the declared weighted mean and randomized control counts:

`control = (51 × 2.79 + 50 × 3.00) / 101 = 2.893960396`

`MD = 10 × (1.51 − control) = −13.839603960/100`

This rounds to −13.8 at one decimal, not the printed −13.900. Rounding the pooled control
to 2.90 would give −13.9, but the inspected source does not establish that operation.
Using displayed SDs and randomized counts, pooled control SD is 1.769309232; a conventional
normal 95% mean-difference interval is −19.436995 to −8.242213, not the printed interval.
Consequently neither the published precision nor exact extraction is independently reproduced.
The observed-count sensitivity (43/36 controls, PRT45) yields MD −13.756962 and normal interval
−19.820644 to −7.693280. It is a sensitivity calculation, not evidence the review used these n.
Calculations and exact inputs are recorded in JSON; no imputed arm data or preferred label.

The close point estimate, explicit outcome/window and pooled comparator support qualified
linkage rather than a genuine outcome mismatch. Unexplained extraction, continuous missing-data
handling and precise estimand remain important to D2/D3 and must travel with the diagnostic
result. They preclude calling it exact or assuming a randomized-count table proves complete
outcomes. No author confirmation or further retrieval is necessary to report these limits.

## Recommendation for discussion

Use this as the concrete non-Low candidate for a separate, development-exposed, qualified
comparison stratum. Pairing with a source-supported Low candidate offers All-Low headroom,
but no new run is authorized here. Freeze the actual published −13.900 result, pooled contrast,
window and these uncertainties; keep the original Code posttreatment primary target and labels
unchanged. Report reference agreement separately from evidence-based disagreement review,
particularly where the review's local D3/D4/overall conventions differ. Resolve extraction or
obtain expert linkage review if an exact-match analysis is required; do not force exactness or
reject the whole result solely because every metadata field is not known.
