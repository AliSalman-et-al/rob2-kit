# D3: indirect evidence can inform a probable judgment

This bounded refinement follows an independent AI methodological review of EXSCEL, not a new human gold label. The frozen EXSCEL state and packet are unchanged. No model calls or benchmark runs occurred. No accuracy gain is claimed.

## Demonstrated wording problem and minimal change

The current reference already allowed a calibrated probable judgment without exact censoring times or a formal sensitivity analysis. Its earlier availability rule nevertheless said “If the extent remains unknown after bounded retrieval, use No information,” and its retrieval paragraph said to stop when “comparable observed counts or complete follow-up accounting are inspected.” The leading question-card rule similarly directed No information when extent remained unknown. This could conflate imperfect quantification with no useful evidence and suppress the later qualification.

The replacements distinguish an exact extent that cannot be determined directly from evidence that cannot support a reasonable availability inference. Outcome-specific observed/expected follow-up time may inform a probable judgment without becoming a participant-observation fraction. Vital status does not ascertain nonfatal components. The retrieval stopping instruction now permits either a reasonable evidence-grounded judgment or honestly bounded uncertainty. The comparison review warning still rejects inference from randomized/analyzed/event quantities alone, but explicitly states that other outcome-specific follow-up evidence may support a probable answer without an exact observed count.

The existing possible-versus-likely distinction was sound. One consideration and its reference counterpart now explicitly require weighing contextual counterevidence (comparable endpoint follow-up and continued ascertainment after treatment stopping), without treating it as proof of non-informative censoring. Unknown timing or reasons alone cannot replace that appraisal. No thresholds, preferred EXSCEL answers, additional mandatory record, or decision-tree changes were introduced. D3.2 remains unchanged: an informative-censoring plan's existence does not establish performed or reassuring results.

`before-after.json` contains every scientific before/after passage. Operational question text, its reference and the existing comparison warning are the only scientific surfaces changed. The exact previous descriptor is retained by both verifiers; updated independent current pins follow the computed operational pack hash.

## Primary methodological basis

[Cochrane's RoB 2 FAQ](https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2), D3.1 question about unknown extent (page lines 258–260, accessed 3 October 2026), directs assessors to other information such as CONSORT and permits probable responses. [Handbook §8.5](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08) distinguishes missing data from available outcomes excluded from analysis, rejects universal thresholds, and bases dependence reasoning on trial circumstances. These support probabilistic appraisal; they do not endorse a particular EXSCEL label.

## Difference from the earlier DAPA impact-warrant refinement

The earlier refinement required explaining whether residual missing outcomes could materially affect the selected estimate, using event scale/variability and circumstances rather than a favorable percentage alone. That requirement remains. This correction is earlier in the inference: imperfect but informative accounting should still be evaluated, and exact participant-observation counts must not become a prerequisite for a probable answer. Availability inference, impact appraisal, and possible/likely dependence remain distinct.

## Neutral controls and next falsifiable check

`neutral-model-inputs.json` contains only outcome-scoped report passages and generic assessment instructions. `neutral-controls.json` keeps private interpretation questions alongside the same inputs. Across continuous, binary and time-to-event endpoints, the twelve controls distinguish partial-but-informative actual evidence, genuinely absent accounting, plausible reassurance and material concern. They contain no desired signaling paths or domain labels. They are constructed reasoning controls, not clinical gold cases and not model-tested outcomes.

The next bounded scientific check, only after authorization and diagnostic preflight, can use the two time-to-event controls `time-event-partial` and `time-event-absent`, with the same isolated Luna6 medium model and exact launcher ID verification. Falsifiable criterion: does the host evaluate endpoint-specific temporal accounting in the partial case without inventing observed participant counts, while recognizing that ITT/censoring rules/vital status alone do not establish composite availability in the absent case? It must distinguish possible from likely dependence and retain material missing-future-first-event uncertainty. A probable answer is permitted, not prescribed. No blanket PY, threshold, or High-to-Some-concerns conversion counts as success. Preflight must freeze actual model evidence, criteria, input and guidance hash before any future call. These files prepare that question but do not constitute authorization or a passed preflight.

## Verification

`contract-invariants.json` records exact equality of the complete pack before/after after removing only operational guidance and computed content hash: official question text/provenance, answer options, activation and decision trees are preserved. Existing guidance, missing-data semantics and comparison tests passed in the initial batch. That batch found three integration failures caused by the changed current descriptor and an unnecessarily removed affirmative-evidence marker; current pins were updated with prior history retained and that marker preserved. The focused verifier/release rerun is recorded below. These checks establish code/contract integrity, not model interpretation or clinical accuracy.

Focused rerun: **21 passed** (descriptor compatibility, installed/standalone bundle verification and release contracts). Ruff, ty and whitespace checks passed. The untouched frozen EXSCEL bundle passed both current verifiers and retained its original raw SHA-256; see `frozen-exscel-verification.json`. Initial batch: 66 passed, three corrected integration failures. Exact verification record: `verification.json`.
