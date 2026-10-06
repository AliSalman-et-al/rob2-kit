# DAPA-HF D3 scientific warrant audit: no redundant inference

## Pinned question and classification

Does production reasoning distinguish actual outcome observation from analysis membership and justify plausible impact of missing outcomes using relevant event counts, reasons/timing and uncertainty? This question was recorded before considering any new inference. DAPA-HF was already used in development; this is a repeated diagnostic, not held-out/generalization evidence. No new model invocation was made, and no case-specific answers, computed counts or reference labels were passed to a model.

## Independently checked target and reference

The actual Code benchmark `OUTCOMES-batch.csv` specifies the primary composite of worsening HF (hospitalization or urgent IV-therapy visit) or cardiovascular death. Its anchor is386/2373 versus502/2371, HR0.74,95%CI0.65–0.85. The primary report Methods and Results support that endpoint/contrast. Both prior production targets describe assignment to dapagliflozin versus placebo, all randomized participants, time to first primary event through trial follow-up;18.2months is a follow-up summary, not a common fixed-time risk.

The Code label row declares “primary outcome of the trial,” located at “eTable2 supp1 p4, text.” Endpoint correspondence is supported by that declaration. Exact reference contrast, analysis population, estimand and follow-up are not supplied; full result-level matching remains **unknown**, consistent with but independently verified from the original CSV fields rather than promoted from the previous alignment audit. The raw cited meta-analysis table is not retained here. Low D3 labels therefore do not establish fully matched agreement.

## Existing scientific baseline

The Oct1 Code production result and Oct2 ad312a4 development diagnostic both already reached D3.1 Probably Yes and server Low. The Code baseline distinguishes incomplete follow-up from analyzed membership, reports14 and20 incomplete primary follow-ups, and preserves uncertain overlap with two placebo unknown vital statuses. The Oct2 baseline strengthens bookkeeping: randomized/analyzed counts remain distinct from event numerators; `observed` is null, and reasons/timing remain unknown. Neither subtraction nor complete observation is invented. Both outcomes and exact source premises are preserved in `baseline-results-and-d3.json`.

The Oct2 justification names386/502 events but concludes mainly from less-than1% randomized follow-up loss. It does not explicitly explain why plausible unknown primary outcomes would be unlikely to make an important difference to the selected time-to-event estimate. This is an underarticulated impact warrant, not proof that the PY/Low label is wrong. Source-supported nearly-complete follow-up may legitimately support PY without known reasons for every missing participant; unknown reasons alone do not mandate another label or activation of3.2–3.4.

## Source inspection and numerical limits

Read-only inspection of the five unchanged Code PDFs confirms the primary report's flow accounting (physical p3), primary composite event counts (p5) and result anchor (p1). Planned last-contact censoring appears in the protocol (e.g. physical p70); an adjudication provision about withdrawn consent appears in the appendix (p16). Those planned rules do not identify actual reasons or timing for the14/20 incomplete primary follow-ups. The bounded keyword ledger does not establish that unlocated reasons are absent.

Incomplete-follow-up flags are14/2373=0.590% and20/2371=0.844%; their counts are3.627% and3.984% of reported first-event counts. If the two placebo unknown vital statuses are disjoint,22 flags correspond to4.382% of502 events. These contextual scales are **not missing binary-outcome counts, a RoB threshold, or an HR sensitivity analysis**. Some incomplete-follow-up participants may already have experienced a known first event; unknown later vital status need not make that primary event unknown. Person-time, censoring timing, prognosis and overlap are unresolved. Crude counts or the between-arm event-count difference do not bound the HR/CI or establish freedom from missingness bias. `observed` stays unknown.

## Why no new paid diagnostic

The current D3.1 official/operational scientific guidance is exactly identical to ad312a4 after ignoring the operational version stamp. The missing-outcome reference changes only counterevidence handle grammar. Its guidance already distinguishes observed/analyzed/events and asks whether missing outcomes could make an important difference, without universal percentage thresholds. Changes to the negative material-incompleteness proposition, later D3 branches and context transport do not supply a new affirmative impact warrant for this already-PY path.

A new run now could identify stochastic reasoning variation or transport/presentation effects; it could not demonstrate an implemented scientific-warrant improvement. The unchanged guidance assertion, source/database hash preservation and exact baseline extraction passed offline. No paid call, save draft, domain revision, source mutation, full benchmark, merge or CI wait occurred. No accuracy or agreement gain is claimed.

## Recommended high-yield change and bounded test

Make the general D3.1 operational guidance explicitly ask for a short **impact warrant**, alongside the availability evidence: explain why plausible unknown outcomes could or could not materially change the selected estimate, using relevant event scale, actual follow-up accounting and known reasons/timing; preserve uncertainty. For time-to-event results, warn that simple binary worst-case counts do not bound a hazard ratio without person-time and censoring assumptions. This should refine host reasoning, not add a numerical cutoff, require formal sensitivity analysis for every PY, infer missing reasons, or impose a new automatic semantic gate.

First check this guidance with offline neutral contrasts across common/rare events and administrative/prognosis-related censoring, keeping analysis denominators and actual observation separate. Then one frozen D3 diagnostic can compare the new warrant with this baseline, using unchanged source corpus and approved target, without event-count solutions or desired labels in its prompt. Assess the warrant and its uncertainties separately from label agreement; reference matching remains qualified. This tests a concrete scientific improvement rather than another schema patch or an unchanged rerun.
