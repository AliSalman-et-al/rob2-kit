# EXSCEL: independent target-matched D3 review packet

Read-only preparation, 3 October 2026. Please judge whether the frozen D3 **High** is scientifically supported, whether a qualified availability inference is justified, and whether uncertainty is over- or understated. No human Low judgment is presumed. Do not require a formal hazard-ratio bound as a prerequisite for reasoning about availability; do not convert person-time coverage into a participant fraction. The frozen assessment is unchanged. No model inference was run for this packet.

## Exact assessment scope

Frozen result identity: `sha256:4851824b2a81d36da8ab1d25d97b912ff0e1dd72b871c0b1144d9a9b379eb8e7`. Target outcome: “Composite of cardiovascular death, nonfatal MI, or nonfatal stroke (time to first event; noninferiority for safety and superiority for efficacy)”. Effect: assignment; intended population: “All randomized participants in the comparison groups”; contrast: assignment to extended-release exenatide 2 mg subcutaneously once weekly versus matching placebo once weekly. Measure: hazard ratio, exenatide versus placebo. Window: “During trial follow-up, from randomization until trial closeout/censoring.”. Reported result: ITT, all 14,752 randomized (7,356/7,396), HR 0.91 (95% CI 0.83–1.00); target relation `exact`. Primary report Table 1 uses a Cox model stratified by cardiovascular-disease history, regimen as sole explanatory variable. Noninferiority P<0.001; superiority P=0.06.

## Frozen final answers: complete warrants and limitations

D3 was saved at revision 7, before the later SAP read; all four counterevidence arrays are empty. The algorithm returns High via `missing.likely_dependent`; overall High is driven by D3. This records the algorithm’s output, not independent adjudication.

**3.1: `no_information`.** The flow identifies randomized denominators, participants without a primary endpoint, unknown vital status, and 94.5–95.1% observed/expected MACE patient-years. These are not direct counts of observed primary outcomes; participant-year coverage and vital status do not establish participant-level MACE ascertainment. The extent of unavailable time-to-event outcome data therefore remains unresolved, rather than showing complete follow-up or a materially incomplete rate.

Unknown: Participant-level endpoint observation/censoring distribution and reasons/timing are not clear from this figure; patient-year coverage does not resolve this.

Unresolved premise: The full trial flow and vital-status figure distinguishes patients with and without a primary endpoint and gives MACE person-year coverage, but does not establish an outcome-observed count for the approved time-to-first-event outcome. Stopping rationale: The figure and main-report follow-up summary were inspected; endpoint event counts and vital-status totals cannot substitute for participant-level outcome ascertainment, so neither near-complete nor materially incomplete availability is justified.

**3.2: `no`.** The report gives ITT and per-protocol estimates, but those compare analysis populations and do not demonstrate a sensitivity analysis across plausible missing primary outcomes. No evidence inspected establishes protection from missing-outcome bias; this answer does not assert that bias occurred.

Unknown: Whether a separate missing-outcome sensitivity analysis exists in the captured SAP/supplement remains to be investigated.

Unresolved premise: The main report's primary and per-protocol results do not address plausible unobserved MACE outcomes. Stopping rationale: The inspected Results passage reports estimates only; no missing-outcome mechanism-matched analysis is demonstrated here.

**3.3: `no_information`.** The figure reports loss to follow-up and consent withdrawal, but does not explain whether these reasons relate to true MACE risk or describe censoring timing. Dependence on the true event value cannot reasonably be determined.

Unknown: Relationship of censoring/withdrawal to health status and MACE risk is not reported in this passage.

Unresolved premise: Reasons and timing for missing MACE follow-up are not linked to true outcome status. Stopping rationale: The full flow figure was inspected; its categories identify losses/withdrawals but not their relation to clinical prognosis.

**3.4: `no_information`.** The available flow data do not establish differential outcome missingness mechanisms or prognosis-linked loss. Missingness could depend on true MACE status, but the evidence does not show that it likely did.

Unknown: Whether censoring followed treatment cessation or worsening status, by group, remains unknown.

Unresolved premise: Likelihood of outcome-dependent censoring remains unresolved. Stopping rationale: The figure reports group flows but not reasons/prognosis or timing sufficiently to distinguish possible from likely dependence.

## Archived comparable assessment

The October 1 Code benchmark archive `cases/exscel/.rob2-kit/finalized/a7dc7f3b779b7bdf14709feabfe2f0c964d2a8825fc7a7256463bc7716f5c68e.rob2.zip` assessed the same first-MACE assignment effect, all randomized, exenatide versus placebo, HR 0.91 (0.83–1.00), randomization through closeout (median 3.2 years). Its D3 was Low. Only 3.1 was active: `probably_yes`; 3.2–3.4 were skipped, not answered Yes/No.

Complete archived warrant: For the approved time-to-first-MACE outcome, the supplement’s flow diagram reports observed versus expected MACE follow-up of 95.1% in the exenatide group and 94.5% in placebo; 96.2% completed the trial, and vital status was known for 98.8%. The protocol required continued clinical-event follow-up after treatment discontinuation unless consent for further contact was explicitly withdrawn, with a trial-termination visit/contact expected for all participants. This supports data availability for nearly all randomized participants, although it was not complete.

Unknown: The diagram reports aggregate person-years rather than the exact number with an observed nonfatal component outcome at every point in follow-up; some participants withdrew consent or were lost to follow-up. Counterevidence: empty. Direct support was Figure S2 and protocol follow-up requirements; main page 4 was context.

## Primary facts, kept distinct

Physical PDF pages are one-based; printed page labels differ. M=main article, A=supplementary appendix, P=protocol/SAP bundle.

| Figure S2 (A31, printed 30) | Exenatide | Placebo |
|---|---:|---:|
| Randomized | 7,356 | 7,396 |
| Did not receive any dose | 18 | 18 |
| Completed study | 7,094 | 7,093 |
| Non-completers with primary endpoint | 7 | 17 |
| Of these: lost / consent withdrawal | 1 / 6 | 4 / 13 |
| Non-completers without primary endpoint | 255 | 286 |
| Of these: lost / consent withdrawal | 38 / 217 | 29 / 257 |
| Unknown vital status: lost / withdrawn | 39 / 44 | 33 / 55 |
| Withdrawn: not searched / not determined | 31 / 13 | 39 / 16 |
| Total unknown vital status | 83 (1.1%) | 88 (1.2%) |
| Observed/expected MACE follow-up person-years | 95.1% | 94.5% |

These are 565 non-completers and 171 unknown vital statuses, different quantities. Figure footnotes define completers as having vital status assessed at termination without consent withdrawal, and lost participants as having undeterminable vital status at termination. The person-time ratio’s numerator is randomization to first MACE or primary-scheme censoring; expected event-free time ends at termination vital-status date for living completers, death for deceased completers, or December 5, 2016 for lost/withdrawn participants. “Without primary endpoint” is not proof of event-free status throughout otherwise unobserved time.

M4 reports 96.2% trial completion, 98.8% vital-status ascertainment, median follow-up 3.2 years (IQR 2.2–4.4, maximum 6.8), similar between arms; closeout December 5, 2016–May 11, 2017. M6 reports 839/7,356 versus 905/7,396 first-MACE participants (11.4%/12.2%; 3.7/4.0 per 100 person-years). Neither all-randomized analysis nor event counts establishes complete outcome ascertainment.

Treatment exposure differs from follow-up: median 2.4/2.3 years; mean expected regimen time received 76%/75% (M4). A36 Table S2 reports permanent treatment cessation 3,164/3,343, primarily patient decision 2,231/2,369; adverse effects, investigator decisions, renal dysfunction and death also appear. These are treatment-cessation reasons, not demonstrated reasons for missing MACE follow-up. Figure S2 supplies loss/consent categories but not individual timing or prognosis-linked reasons.

Protocol P77–78 requires continued follow-up after treatment cessation unless further-contact consent is withdrawn; termination contact for all, documented location attempts, permissible vital-status searches, and last-known-alive documentation. These are planned procedures, not proof of implementation. M3 reports vital-status searches using records/registries during the washout period.

## Planned missing-data analyses versus reported results

P187 §4.1.2.1 specifies primary ITT censoring at earliest last contact assessing all endpoint elements or right-censoring date; no endpoint assessment means censoring at randomization. P188 lines 6–16 additionally specify on-treatment, +7/+30/+70-day, and cutoff-date schemes. Lines 17–18 define right censoring as last-known-alive at termination, except adjudicated death date for deceased participants.

P188 lines 20–25, adjacent qualification, verbatim:

> The time to event analysis (Cox regression) relies on the assumption of non-informative censoring. To examine this assumption, variables that may be related to censoring, for example, the most frequent major protocol deviation, certain SAEs, will be explored. Rates per 100 patient-years will be calculated per treatment group and compared between patients censored early without complete follow-up, and those with complete follow-up.

P188 lines 26–38, complete relevant sensitivity plan (line breaks normalized; superscript citation rendered inline):

> To assess possible effects of informative censoring on the primary efficacy endpoint, sensitivity analyses will be done as follows. First, the tipping point analysis will be performed where in patients who prematurely discontinued the study without having a primary endpoint event prior to discontinuation, events will be imputed during their missing follow up time (i.e. time from censoring to trial termination visit) under various scenarios for the hazard rates for non-completers in each arm. For each scenario, 2000 imputations will be performed and the results will be combined across 2000 combined datasets (actual events in completers + imputed events in non-completers) using SAS PROC MIANALYZE. Specifically, log-hazard ratio estimate of treatment effect will be calculated as an average and its associated variance will be obtained using Rubin's8 (1987) formula, which combines within-imputation and between-imputation variances. Hazard ratios, Wald's 95% CIs and Wald's test p-values will also be calculated. The goal of this analysis is to find scenarios where the primary analysis results will be “tipped”, i.e. the conclusion will change.

This establishes a plan’s existence. It does not establish execution, assumptions’ plausibility, or reassuring results. The frozen 3.2 existence unknown is therefore stale after the later read; uncertainty about performed informative-censoring analyses can remain.

M8 explicitly directs readers to Figure S9 for prespecified sensitivity results. Operator image inspection of A45 confirms these actually reported HRs (95% CIs): ITT 0.91 (0.83–1.00); per-protocol 0.95 (0.85–1.07), 591/7,263 versus 605/7,302 events; on-treatment 1.03 (0.90–1.18); +7 days 0.98 (0.87–1.11); +30 days 0.98 (0.87–1.10); +70 days 0.96 (0.86–1.08); CRF-reported prior-CV stratification 0.91 (0.83–1.00); cutoff censoring 0.91 (0.82–1.00), 812 versus 885 events. Figure S9 does not display tipping-point hazard scenarios/imputation results. These variants cannot automatically be treated as robustness to plausible missing outcomes; nor does their presence justify saying no sensitivity analyses were reported. No claim of exhaustive absence elsewhere is made.

## Delivered support versus cited support

Final D3 3.1/3.3/3.4 cite Figure S2 context `eh_36d71260096952a7` (A31 lines 1–53); 3.2 cites main results context `eh_62c0318d013b0813` (M6 lines 1–148). The complete substantive source facts are reproduced above. Later native item 32 delivered P184–193, including untruncated P188 lines 1–43, `eh_f3ad502fa6c18431`; D3 was not resaved. D5 item 34 subsequently asserted SAP missing-follow-up imputation, but directly cited P187 lines 1–45 (`eh_776250d728c5dc52`) and P192 lines 1–43 (`eh_ba952ae2a3f96ebd`), with M6 context. Those citations do not contain the tipping-point plan: delivery and citation linkage are separate. A45 was operator-inspected after freezing, not delivered to the assessment model; its results are supplied here for independent review, not retroactive coverage credit.

## Source identity and separate scope ambiguity

All primary PDFs are from the required Code benchmark dossier `rob2-meta-set-full-2026-09-29/trials/exscel`, not older main-repository evaluations. Source identity is fixed by these raw SHA-256 hashes:

- `NEJMoa1612917.pdf`: `b9b1adb69702e20d68d4d98dac57e07cfeb3b73ff014d69a62f8859b200f1121`.
- `nejmoa1612917_appendix.pdf`: `df91cb4fa3fa0223497f3b828b3c2645f75a8a82d41b91b7e6f96b7e02f08a16`.
- `nejmoa1612917_protocol.pdf`: `d3498516286f49f1d609124999be3d44a7a8ddac46eb70d4542395ffabcc96a2`.

Main article: Holman et al., *Effects of Once-Weekly Exenatide on Cardiovascular Outcomes in Type 2 Diabetes*, NEJM 2017;377:1228–1239, DOI 10.1056/NEJMoa1612917. P188 is SAP Edition 4, February 23, 2017, study D5551C00003 (BCB109), printed SAP21/bundle187. Captured public source handles: M `sh_693e51915e5ffefc`, A `sh_08fbea6d1ed99fc0`, P `sh_bcf70e5423c2d8ef`; raw hashes above disambiguate the exact files. Page/line coordinates above refer to captured extracted receipts, not printed line numbers.

Intake metadata names NCT01455896; the article identifies EXSCEL as NCT01144338. Registry retrieval was unavailable. This conflict limits registry/reference applicability separately from within-article D3 reasoning. The archived Low is a comparator, not a verified matched human gold standard. Please adjudicate the stated result and evidence, and identify any additional evidence needed before assigning 3.1–3.4 and D3.
