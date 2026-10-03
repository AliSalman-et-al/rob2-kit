# D2.7 mechanism-to-estimate impact guidance

**Methodological decision: keep the replacement, with behavioral benefit untested.** The rejected context reorder stays out of production. This change replaces the three existing operational2.7 considerations and synchronizes the corresponding skill paragraph. It adds no checklist, mandatory field, model call, automatic response, numerical threshold or rule. Exact Cochrane wording/elaboration, response options, activation, official attribution and server-computed domain/overall policies remain unchanged.

## Scientific change

Before: the considerations repeated conditional activation, small/balanced exclusions and before/after ascertainment timing. After: carry the inappropriate/uncertain mechanism from2.6 into its plausible effect on this selected estimate; distinguish stopping, unavailable measurements and measured values omitted by analysis; allow supported probable important/negligible judgments without requiring a numerical bound or sensitivity analysis. A small component does not establish another component's impact. Negligible impact does not make an inappropriate analysis appropriate.

The source-supported causal question is whether restricting data after stopping selects outcomes/prognosis or relies on assumptions that could materially alter the assignment estimate. Assignment encompasses post-randomization trajectories, including later treatment stopping and rescue. Randomized grouping and an all-randomized population label do not alone settle an analysis that removes parts of those trajectories. Conversely, stopping alone does not mean outcomes were lost, measured values were omitted, or bias occurred. If measurements are unavailable, missingness assumptions may be relevant underD3; it is different from recorded outcomes omitted by an adherence restriction. This operational clarification does not assign one universal response to either situation.

## Exact prior failure and evidence

Both frozen responses in [decision-context pair](../2026-10-03-decision-context-pair/) answered2.6PN and2.7PN. Baseline explained impact by one rescue and relatively few study noncompletions (10/5); candidate referred to modest discontinuations and the known rescue exclusion. Neither explained why the separate drug-stopping-based restriction could not materially change the continuous HbA1c effect. Their2.6 mechanism recognition improved relative to the older pair but cannot be causally attributed to reordering; both arms had a new synthetic control/task.

The [preserved complete source packet](../2026-10-03-evaluation-readiness/current-input.txt) distinguishes:

| Source fact | Location | Scientific implication and limit |
| --- | --- | --- |
| Drug stopping10/4, study noncompletion10/5; drug reasons includeAE4,withdrawal4,noncompliance1,unknown1 versuswithdrawal3,investigator1 | MainPDF physicalp4 Figure1, separate visual lines2–5 | Drug stopping and study loss are different events. AEs may be prognostically relevant, but these counts/reasons alone do not establish which HbA1c measurements existed or were omitted. |
| Efficacy data censored after rescue/premature drug stopping; primary continuous analysisMMRM | Mainp3lines89–100; p5lines1–7; visualp5line3 | A data-selection rule affecting the assignment-effect interpretation is explicit. Actual recorded post-stop values and consequences of model assumptions remain unknown. |
| One rescue, dulaglutide arm | Mainp7lines7–9 | Bounds only the rescue component, not drug stopping or all exclusions. |
| Primary eligibility133/142 requires baseline plus at least one post-baseline measurement | Capturedregistryp1lines1898–1920 | Analysis eligibility is not Week28 observation or proof of complete assignment-effect data. |
| Supplement139/147 andLOCF concern secondary composites | Supplementp2, counts lines8/11,methodline46 | Cannot substitute these for primary continuousMMRM. |

Outcome-dependent loss is an explanation to assess, not a fact established here. Different prognosis among those stopping can create selection even if observed groups remain randomized; a mixed model can address some unavailable observations only under its applicable assumptions. No actual bias magnitude, missing-value count, observed-value omission or formal bound is asserted. This change asks for that inferential bridge rather than proof of actual bias.

## Neutral controls and preparation

[Private neutral controls](private-neutral-controls.json) contain four fictional, fully specified mechanisms: measured unfavorable outcomes omitted; small administrative restrictions with independently reported near-identical all-randomized results; unknown measurement/reasons/model assumptions; and treatment stopping with all outcomes retained. These permit important, negligible, uncertain and inactive-impact paths. Expected responses are methodological possibilities, not model-generated accuracy observations or trial reference labels.

The frozen baseline/current inputs share all facts, task, official guidance,2.6 and2.7 decision/response/activation fields. Only2.7 operational considerations differ; version-only operational metadata is excluded from both diagnostic projections. Four declared source windows pass offline evidence preflight. Inputs are about10.8KB, approximately3.6k tokens at3characters/token; exact tokenizer measurement unavailable. The controls are complete synthetic sources, not compressed real-trial snippets, and test calibration rather than corpus accuracy. No model outputs exist and no paid launch is authorized by this package.

[Future protocol](future-experiment-protocol.json) freezes the scientific criteria and same existinggpt-6-luna/medium configuration. A future explicitly authorized pair must use `scripts/diagnostic_evidence_preflight.py:launch_checked` with frozen hashes; no third response, tools or accuracy retries. That future comparison is prepared, not launched. Broader performance evidence still needs diverse independently scope-matched cases and complete assessments againstAll-Low.

## Validation and limits

54 focused logic, guidance, neutral-control and current/historical/tampered-artifact tests passed. Neutral tests validate authored response paths and experiment preservation; they do **not** evaluate model comprehension or entailment. Official wording/options/activation and decision machinery were preserved. The new pack hash is pinned by the standalone verifier; the former exact descriptor remains recognized by both verifiers without relaxing tamper checks. Ruff/format/source typing and diff checks passed.

Two local test corrections are preserved as audit history: a first reference check caught omission of the existing observed-value-versus-missing-data distinction, which was restored; the initial new test referenced a nonexistent Evaluation.active_questions attribute, corrected to the existing activation/evaluation interface. Neither was an observed production regression.

Risk: expanded mechanism language could induce unjustified conservative judgments or demand unavailable data. Explicit supported-probability/no-bound wording and the negligible/retained-outcome controls address the intended contract, but behavioral calibration remains untested. Keep on methodological merits; revise/reject if a later authorized experiment shows those failures. No accuracy gain claim, benchmark, merge, paid call or CI wait occurred in this step.
