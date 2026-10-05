# Conditional missing-outcome sensitivity: proposed contract

Status: methodological review draft; no implementation, model run, default-policy change, trial adjudication or frozen-answer correction. This proposal is motivated by repeated effect-impact omissions, not a desired label for any trial.

## Architecture audit

`workflow_models.MissingDataRow` already separates randomized, observed, analyzed, imputed, completed and event quantities, with population/time/endpoint/Result scope, Evidence basis and optional censoring semantics. `application.missing_data.reconcile_missing_data` subtracts only explicit observed from randomized, retains conflicts, and produces quantity bounds when availability is unknown. `get_domain_context(missing_data=...)` already resolves current-Trial Evidence handles, binds the approved Result and returns a noncommitting comparison-card preview. Saved participant-flow rows have an established historical/export verification path.

Current reconciliation does not calculate how unknown outcomes could change an effect. Its `missing = randomized - observed` output is arithmetic, not proof that every unobserved value represents a missed required measurement. An analyzed count, study-completion count, imputation count or survival event count cannot supply observed availability. The new calculation must not consume legacy missing_bounds as if they were an exact partition of actual missing outcomes.

`DerivedEvidence` is proposal-field evidence with caller-supplied value and only sum/difference/ratio operations. It is not a scenario calculator; putting hypothetical event values into that evidence would risk representing scenarios as Source facts. Reuse the existing missing-data preview/reconciliation path instead; add no tool, generic expression evaluator or new workflow gate. Keep historical saved rows and their verification byte semantics unchanged initially.

## Recommended first increment

Implement only an optional **fixed-time binary risk-difference preview**, conditional on explicit source-supported scope and outcome-accounting declarations. Continuous means are mathematically simple but require new summary/bound fields and deserve a separate review; formulas below define that possible extension, not a first-increment commitment.

Expose one optional request on the existing get_domain_context route, using its supplied MissingDataRows and Evidence resolution. Name the experimental and comparator arms explicitly; never infer direction from row order. Return a separate conditional calculation alongside existing reconciliation, rather than modifying its observed/missing facts or triggering a signalling answer. No request means no computation or new policy.

## Required mathematical inputs and source warrant

For each of exactly two distinct arms g:

- N_g > 0: exact target population denominator in assigned arm.
- O_g: count whose binary outcome is known at the specified fixed horizon, including known events before that horizon and known event-free status through it.
- E_g: participants among O_g experiencing the defined event by that horizon, not recurrent events, person-time or events over variable follow-up.
- U_g = N_g - O_g: explicitly accounted-for unknown binary statuses for that same target horizon. Require 0 <= E_g <= O_g <= N_g. Derive U only after the caller supplies a source-bound accounting declaration that O and unknown statuses partition this target population.

The declaration must distinguish source-reported actually missing required outcomes from inferred/unaccounted statuses. Preserve reported reasons, administrative censoring, unknown extent and overlaps separately. A scope assertion and linked Evidence are host assertions, not server-verified entailment. Reject missing accounting declarations, conflicting duplicate rows or internally contradictory counts with a reason and recovery; do not quietly choose a report. This capability does not fix current legacy subtraction terminology.

Require matching approved Result identity, endpoint/event definition, fixed horizon, population and participant unit across arms (arm labels differ). Require a supported fixed-time, unadjusted binary risk-difference Result; reject HR, odds ratio, adjusted effect, rate ratio, Kaplan–Meier estimate or unspecified measure. If this binary endpoint is only an auxiliary analysis of an approved HR, do not run it under that HR's Result identity. An explicit separately approved Result would be needed. Textual field agreement is only a syntactic check: the host must warrant true population/horizon equivalence and how the reported estimate relates to these quantities.

Each arm's counts, partition declaration and endpoint/horizon warrant need current-Trial selected Evidence. Reported vs inferred provenance stays visible. Hypothetical scenario inputs have no Source-value handle: attach a rationale and label them assumptions, not observations or imputed facts.

## Binary contract and exact bounds

Let X_g be the hypothetical integer number of events among the U_g unknown statuses. For 0 <= X_g <= U_g:

    R_g(X_g) = (E_g + X_g) / N_g
    RD(X_A, X_B) = R_A(X_A) - R_B(X_B)

The exact logical envelope for the finite-population unadjusted contrast is:

    RD_lower = E_A/N_A - (E_B + U_B)/N_B
    RD_upper = (E_A + U_A)/N_A - E_B/N_B

Extrema are attainable by assigning no/all events to the corresponding unknown statuses; no independence or missing-at-random assumption is used. Use rational arithmetic internally and expose exact numerator/denominator plus readable decimal. These are identification bounds conditional on the inputs, **not confidence intervals, causal-effect guarantees or a recalculated published adjusted estimate**. When O_A,O_B > 0, also show E_A/O_A - E_B/O_B as the observed-status contrast and changes relative to it. O=0 permits the logical envelope but has no observed-status contrast.

Optional user-named scenarios provide integer X_A,X_B and a rationale. Evaluate each directly; reject out-of-range/noninteger counts rather than round probabilities into invented participants. Do not generate/default to a supposedly plausible scenario, silently assign identical rates across arms, or present worst cases as likely. No automatic tipping label, significance test, clinical threshold or RoB label.

The model still has to discuss outcome scale, clinically consequential magnitudes, plausible missingness mechanisms and the source warrant. A bound spanning zero does not establish material bias; a bound excluding zero does not establish negligible bias. No universal 95% availability rule, mandatory sensitivity analysis or forced No information response follows.

## Offline positive and negative examples

These are invented counterfactual fixtures; none adjudicates a diagnostic case.

1. Rare event, high ascertainment: each N=1000,O=990,U=10; E_A=1,E_B=3. Observed-status RD=-2/990 (about -0.00202); exact full-population RD envelope [-0.012,+0.008]. Scenario X_A=5,X_B=0 gives +0.003. Availability of 99% alone does not settle material impact; plausibility still requires a mechanism.
2. Same ascertainment, common event: N=1000,O=990,U=10; E_A=400,E_B=500. Envelope [-0.11,-0.09]; observed-status RD=-100/990 (about -0.10101). The potential range is limited numerically, but whether a 0.01 change matters is a scientific appraisal. Neither unchanged sign nor equal missing fractions is an automatic Low judgment.
3. Complete ascertainment: U_A=U_B=0 produces a single-point RD. This says nothing about D1/D2/D4/D5 or event misclassification.
4. N randomized and N analyzed, with only 20/30 events reported: reject absent O and target-horizon accounting. Analyzed is not observed and event counts are not availability counts.
5. 30 people lack one-year study follow-up, but endpoint is a three-year HR: reject. Those counts neither define the unknown fixed-time statuses nor bound that HR.
6. Event counts cover all variable follow-up while O refers to one year: reject incompatible horizon. A known event before the horizon is not missing merely because later follow-up stopped.
7. Conflicting E counts in otherwise matching rows: preserve both reports and return unavailable pending source resolution. Do not average them or choose the first.
8. N=100,O=90,E=95 or X>U: reject mathematical contradiction. O=0,E=0 yields an admissible [0,1] arm risk envelope but no observed contrast.

## Possible later bounded-mean extension

For a fixed-time unadjusted mean difference with observed count O_g>0 and observed mean M_g, genuine hard measurement bounds L_g <= outcome <= H_g, and an explicit N_g=O_g+U_g target partition:

    mean_g_lower = (O_g*M_g + U_g*L_g)/N_g
    mean_g_upper = (O_g*M_g + U_g*H_g)/N_g
    MD_lower = mean_A_lower - mean_B_upper
    MD_upper = mean_A_upper - mean_B_lower

A scenario supplies the hypothetical unknown-group mean in [L_g,H_g]. Bounds must describe the actual outcome variable: observed sample minima/maxima, SD, a confidence interval or raw score bounds for a change score are insufficient. Rounded published means make this a conditional calculation over rounded summaries, not exact empirical bounds; require known sums or documented rounding intervals before claiming exactness. It does not cover ANCOVA-adjusted contrasts or standardized effects.

Example: each N=100,O=90, scale genuinely [0,100], means20 vs25. Conditional envelope is [-14.5,+5.5], relative to observed MD=-5. With only sample range [10,40], return unavailable rather than treating it as a hard bound. First increment should avoid this extra summary/rounding contract.

## Survival limitation

Aggregate event and incomplete-follow-up counts do not determine event/censoring order, risk sets, censoring times, adjustment covariates or the relationship of withdrawal to latent outcomes. They therefore cannot bound an HR or its interval through the formulas above. Administrative censoring is not automatically missing outcome data; loss before an intended horizon can leave status unknown, but needs timing/endpoint accounting. Even if fixed-horizon crude event proportions can be computed, they do not replace the approved HR or establish censoring robustness. Return a concrete limitation and request relevant source-reported survival sensitivity, timing/risk-set information or mechanism evidence. A calibrated probable answer may still be defensible without a formal bound; no forced NI or label change.

## Cochrane rationale and review choices

Cochrane Handbook chapter8, sections8.5.1–8.5.3 distinguishes true unobserved values from the missingness mechanism, rejects a universal small-missing-percentage cutoff and relates potential impact to event risk/outcome type. It allows sensitivity analyses by review authors but requires appraisal of plausible values and important effect differences. This calculator supplies conditional arithmetic; it does not certify that extremal scenarios are plausible or satisfy question3.2.

Source: [Cochrane Handbook, chapter8](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08), accessed2026-10-05. Repository official D3 pack and existing scientific cards already convey these principles; the gap is an optional operational calculation, not a reason to replace official guidance.

Methodological choices needing review before implementation: (1) binary RD-only first increment versus also bounded means; (2) requiring an explicit exact target-population unknown-status partition instead of treating legacy missing arithmetic as sufficient; (3) preview-only output with source declarations, leaving historical saved rows unchanged. Recommended: binary only, explicit partition, preview only. Deterministic offline fixtures and Source-only native integration controls would test scope rejection and arithmetic without paid inference or case-label feedback.
