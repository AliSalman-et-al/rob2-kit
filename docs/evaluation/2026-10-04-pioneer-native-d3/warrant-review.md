# Follow-up scientific and implementation review

This supersedes the initial review's categorical recommendation to revise the scientific assessment merely because SAP/S4 were unread. The original run, judgments, inputs, usage and failed preview remain frozen. No paid inference occurred in this follow-up.

## What the model actually concluded

The complete original 3.1 justification and typed input rows appear in `warrant-review.json`, along with literal selected source quotations and exact coordinates. The canonical saved form remains `saved-d3.json`. The model distinguished trial completion from observed endpoints and vital status from nonfatal MACE ascertainment. It used 11 noncompleters as a conservative *scenario*, not as a typed exact missing count: canonical observed, missing and missing fraction are null. Its near-all inference rests on reported 99.7% trial completion, 5/6 noncompleters, 2/5 losses, full-analysis-set primary analysis, and 61/76 events. The phrase “only about 0.3% potentially missing” overstates certainty if read as a verified bound, but the explicit caveat and Probably Yes make the interpretation qualified rather than an assertion of known complete ascertainment.

The selected support is:

- Main article physical p3 lines79–92: randomization1591/1592, median follow-up15.9months, trial completion3172/3183, treatment completion1347/1435, vital status obtained for11 noncompleters.
- Appendix physical p17 Figure S2, full-page delivered render and source-bound host transcription: completed trial1586/1586; withdrew3/1; lost2/5; noncompleters5/6; no unknown vital status. Visual evidence identity `sha256:274df28f6e4334c66f49386ed3260e414e56369484df306dadb37ce8257a3e6a`.
- Appendix physical p14 lines7–19: primary in-trial observation window, Cox model, censoring at final follow-up or withdrawal, FAS includes all randomized.
- Main article physical p7 lines65–123:61/76 primary events and HR0.79(CI0.57–1.11); all first events positively adjudicated, in-trial FAS.

This is a defensible contextual Probably Yes, not a demonstrated scientific error or a proof of complete ascertainment. Cochrane allows probable responses based on judgment and indirect information, and relates near-all reassurance to event frequency. It does not require an exact observed count or a formal numerical worst-case bound before a probable answer. The dichotomous-event example is a heuristic here, not a formal survival-analysis bound. Remaining follow-up time and selection of early censoring could matter; the model stated that limitation. A reviewer can disagree about the strength of reassurance without forcing NI or changing the algorithm.

## What the unread sources add

Captured exact numbered SAP203–208 and appendix19 passages are in `warrant-review.json`; these were inspected by the operator after freeze, never supplied as model corrective hints. SAP205 ends in-trial observation at last contact for withdrawn/lost participants. SAP206 explicitly assumes independent censoring; trial completers attend P18 *or die while active*, treatment completers include on-treatment deaths, and loss for P18 differs from loss for vital status. Thus completion is an informative follow-up measure but not a count of final nonfatal-event ascertainment. The model already left observed unknown, so this does not contradict its typed row or automatically overturn3.1.

An active-participant death is not automatically a missing MACE outcome: cardiovascular death belongs to the endpoint, and noncardiovascular death is a competing event. The completion definition prevents equating completion with attendance at the final visit; it does not prove missing outcomes among all such completers.

SAP207 calls the two on-treatment sensitivities different estimands. SAP208 makes tipping-point imputation and additional out-of-trial analyses conditional on superiority. Appendix19 Figure S4 shows the confirmatory estimate0.79[0.57–1.11], additional-covariate0.77[0.55–1.08], on-treatment38days0.82[0.58–1.17], on-treatment7days0.79[0.54–1.14]. No published superiority was established. The source pixel identity and operator transcription are recorded separately from model deliveries. Reading S4 cannot be made a mandatory prerequisite for3.1 merely because it contains sensitivities: the model did not invoke them to answer3.2, and3.2 was legitimately inactive.

`imputed=0` means no participant's missing primary MACE outcome/event time was replaced by an imputed primary-analysis value. Censoring allows partial follow-up into the risk set; it is not outcome imputation and does not establish complete observation. Reported primary Cox censoring therefore reasonably supports zero imputation as an inference, even without a literal count. The planned conditional tipping-point imputation concerns a separate analysis and was not evidence that primary outcomes were imputed. It would be better to make that inference explicit in the narrative; absence of the literal word “zero” is not itself unsupported reasoning. No implementation default created the zero.

## Guidance and stopping

The actual complete official profile delivered in item2 and the completion rule are in `warrant-review.json`. The profile includes official probable-response definitions, section6.3's instruction that no further questions need be answered when nearly all data are available, full Box8 elaborations, and the FAQ quotation that Probably Yes/No may be appropriate when extent is unknown. The native gate correctly closes3.2–3.4 after3.1PY. The generic context completion rule asks for relevant evidence or a bounded scientific limitation, not exhaustive reading of every source. The experimental prompt explicitly said stop after accepted D3; its budget exposure might also influence decisions. We cannot attribute early completion causally to one instruction or assume all unread sources could change the answer.

Future diagnostics must not use an arbitrary tool-count stop. Diagnostic time/output budgets should prompt spending review rather than masquerade as scientific completion criteria. No new runner was launched or completed-run monitor changed here.

## Concrete defect and correction

Inspection found no zero coercion: optional count defaults are None, normalization preserves unknown counts, the public roundtrip keeps None, and missing arithmetic uses only explicit observed counts. The model supplied zero. Canonical rows preserve their evidence identities, scope, outcome status and censoring metadata.

A real projection defect was reproducible: participant-flow cards resolved bases through a narrative-only reference index. Figure S2 supported the arm completion/loss counts but disappeared from flat flow provenance. Cards showed narrative coordinates without the visual basis, render identity, region, host provenance or uncertainty. This can make a correct fact difficult to inspect and overstate what narrative text directly establishes.

The correction adds compact typed `figures` references to D2/D3 participant-flow projections, preserving Source, render/PNG identity, region, delivery receipt, provenance and uncertainty. Full transcription stays in selected Evidence, avoiding repeated prose. Existing text `passages` and legacy output without visual bases are unchanged. Counts remain host-supplied, no label or activation rule changes, no trial-specific gate, no mandatory SAP reading, and no new scientific instruction. `visual-projection-review.json` reproduces the old omission against the actual frozen Code-corpus case and verifies the corrected offline projection; this is not a model behavior claim.

Tests include neutral D2/D3 visual-basis projection and a native render→selection→preview→save→read roundtrip with uncertainty, plus missing-data unknown-value coverage. The initial follow-up audit mistakenly looked for the card on context page0; it was on continuation item19. That offline audit indexing error was corrected without model spending or runtime changes.
