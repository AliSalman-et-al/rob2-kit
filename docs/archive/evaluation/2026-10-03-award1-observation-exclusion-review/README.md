# AWARD-1: source-backed observation versus exclusion review

This review ran offline on 2026-10-03. The one AWARD-1 invocation occurred on 2026-10-02; no new invocation ran during today's recovery or review. [Recovery log](recovery-log.json) retains the durable usage timestamps. The original approved Result and accepted High checkpoint are unchanged.

## Exact source statements and bounded conclusions

[Source ledger](source-ledger.json) retains numbered physical-line windows, raw and projection hashes from the required Code benchmark, and the original target/reported/relation fields. The restored article and supplement were verified against retained identities before review; the unavailable historical registry was not substituted or treated as an absence source.

Main p2 lines120–129 permits add-on rescue for severe persistent hyperglycemia and permits patients discontinuing study drug because of an adverse event to remain for **safety** follow-up. This does not state that they actually remained, and it does not establish collection of the selected 26-week HbA1c endpoint.

Supplement p2 lines8–18 defines outcome-related rescue criteria, including glucose thresholds and HbA1c information used for investigator discretion. Lines24–27 state that rescued patients should continue their allocated dose. Continued study treatment is a treatment instruction, not proof of endpoint observation. The restored supplement does not give arm-specific post-rescue HbA1c observation counts. Supplement p1 tabulates other endpoints and analysis denominators; those denominators do not establish post-rescue ascertainment of the selected HbA1c result.

Main p3 lines13–35 defines a treated-randomized analysis population, restricts efficacy data to measurements before rescue, applies LOCF for missing data, and describes a secondary MMRM approach. The strongest supported statement is **analysis exclusion of post-rescue efficacy data**, not that collection ceased or that those data were actually collected. Neither direction can be inferred from the exclusion rule. Main p3 lines100–108 gives differential rescue quantities; these are rescue counts, not observed/missing HbA1c counts. Study-discontinuation quantities at lines55–79 likewise do not determine actual observed endpoint availability.

## Selected Result and estimand

The approved target is assignment to dulaglutide 1.5 mg versus placebo, change in HbA1c at 26 weeks, all randomized participants in those arms. The reported Result explicitly retains pre-rescue-only efficacy handling and LOCF, with estimates -1.51 and -0.46. Its historical relation field is exact, with a rationale focused on matching outcome, timing and comparison plus defined methods.

Outcome/time/group matching does not resolve whether this pre-rescue analysis estimates the approved all-randomized assignment effect. The two untreated participants were in the exenatide arm, so their exclusion alone does not establish a population mismatch in this selected comparison. The rescue-handling difference remains material. A hypothetical absence-of-rescue interpretation may be suggested by pre-rescue truncation/LOCF, but the restored sources do not explicitly declare that formal estimand. Preserve this as uncertainty about the analysis's target rather than asserting a formally different estimand or rewriting the approved record.

## Primary Cochrane guidance and production diagnosis

The retained primary RoB 2 full guidance, section6.1 p39, distinguishes genuinely missing outcome measurements and their imputation from deliberate exclusion of eligible participants with available outcomes, which belongs to D2. Box6 pp28–29 assesses assignment-analysis appropriateness. Preliminary considerations p8 require identifying the specific result and assignment/adherence effect. PDF path, hash and locators are in the source ledger.

The production model already has orthogonal observed/analyzed/imputed/excluded quantities and explicit outcome status. Reconciliation derives missing counts only from explicit observed counts; no count is inferred from analytic exclusion, rescue, imputation membership or scheduled collection. D2.6 already explicitly identifies omission of observed values as an assignment-analysis concern, and D3.1/3.3 separate observation from analysis membership. Thus the run's conflation is primarily a model reasoning error despite correct context, not a quantity-calculation bug.

A narrow local omission nevertheless exists: D3.4 lists censoring after stopping/changing intervention but does not repeat the D2/D3 attribution distinction at the point where the model made its decisive inference. The smallest reinforcement adds two operational considerations there, sourced to section6.1 p39: require a link to actual unobserved measurements/follow-up before using an outcome-driven pathway as a D3 mechanism; distinguish the same treatment change with observed-but-excluded, unobserved, or unknown endpoint data. Unknowns remain host-owned. It also reminds the host to compare reported handling with the approved assignment target, without claiming a new formal estimand.

Operational guidance advances to1.0.8; official text, activation, domain/overall algorithms, quantity types, reconciliation and saved judgments remain unchanged. No trial names, example thresholds, reference labels, wrapper layer or automatic risk coercion were added. [Exact updated question guidance](updated-guidance.json).

## Offline controls and interpretation

Three synthetic negative controls reuse existing randomized/observed/analyzed/excluded fields with the same analytic exclusion. Explicit complete observation produces zero missing; explicit incomplete observation produces a missing count; absent observation information keeps missingness unknown even when collection was scheduled. Counts are illustrative facts, not decision thresholds, and the tests assert no risk label. Existing imputation, bounds, conflict and guidance checks also pass: **37 focused tests**, Ruff, ty and diff checks.

The new guidance was also projected through existing get_domain_context offline, confirming that the D3.4 card carries the distinction. No model has tested it. No accuracy improvement or alternate AWARD-1 label is claimed. Its accepted High remains conditional on a missingness-mechanism link the inspected sources do not establish; outcome-driven exclusion may support a D2 concern independently. Further work should preserve those unknowns instead of changing the answer to obtain a preferred label.
