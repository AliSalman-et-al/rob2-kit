# Working observation scope and warrant links

No paid calls were made for this change. Official D3 guidance remains an experimental opt-in profile.

## Trace diagnosis

The original Code benchmark source corpora and their preserved native diagnostics remain the evidence source. See the Freeman [prototype review](../2026-10-04-freeman-native-d3/scientific-review.json), [original control](../2026-10-04-freeman-original-control/paired-scientific-review.json), and PIONEER [follow-up review](../2026-10-04-pioneer-native-d3/warrant-review.md).

Freeman's selected main-report page 5 visual transcription retains all arm and stage labels. The prototype's saved 3.3 warrant nevertheless pools “poor adherence” from the eliminated CBD200 arm into the selected CBD400/placebo comparison. The numerical rows retain the correct selected arms. This is a loss of scope during warrant assembly, not an extraction error. Neither run saved working observations; existing WorkingNote had source coordinates but no typed group, stage, window, population, method, or Result scope, and evidence bases had no working-observation link. A whole-figure citation alone cannot identify which factual premise the prose uses.

PIONEER provides a contrasting case: trial completion and Cox censoring can provide indirect reassurance about assignment-effect MACE ascertainment, while product completion and on-treatment windows address different concepts. The qualified warrant explicitly distinguishes vital status from nonfatal-event ascertainment. Method-inferred zero imputation is not host zero-coercion. Unread SAP methods do not establish an error in the saved answer. Shared trial context therefore must remain usable, alongside partial overlap and unknown outcome-specific scope.

## Native change

WorkingNote optionally carries WorkingObservationScope: Result identity, host-asserted relation (matched, mismatch, partial_overlap, unknown, shared_trial_context), groups, stage, window, population, method, reported/inferred/uncertain meaning, and uncertainty. Unknown fields remain optional; no lexical matcher guesses relevance. Existing Result and source bindings remain authoritative for checkpoint freshness.

An evidence citation optionally carries working_observation: the existing checkpoint identity and an unchanged WorkingNote snapshot. Submission resolves membership against current source/Result-bound working observations and premise support/counterevidence. The canonical evidence basis keeps this snapshot when advisory notes are replaced. It retains the selected Evidence quote/transcription and its existing coordinates, render provenance and uncertainty; the observation is an interpretation, not newly certified Evidence. Domain/context projections expose the snapshot. The basis role, justification and counterevidence implication remain the places to explain indirect or out-of-target use; no scope category changes an answer or filters counterevidence.

Legacy notes and evidence bases omit the new optional fields. Product and standalone bundle verifiers accept the new snapshot representation without changing historical field sets. The checkpoint identity is an audit link, not an independently reconstructible archived checkpoint: offline verification checks snapshot structure and canonical integrity; native submission checks membership.

## Limits and validation

Optional scope and links cannot prevent an agent from ignoring them. No claim of behavioral improvement, benchmark accuracy gain, or source entailment is made. No paid follow-up is authorized here. Tests exercise native multiarm mismatch, overlapping time windows, method/population interpretation, shared trial context, unknown scope, unchanged answer values, unsaved-link rejection, persistence after working-note replacement, and finalized product/standalone verification. Participant-flow recovery and historical verification are checked separately.

Validation completed: 44 working/checkpoint/bundle tests, 35 comparison/missing-data tests, and two historical/revision bundle-integrity tests passed (81 total). The six new native scope tests passed again after adding public-context and exact Result-identity assertions. Ruff, formatting, ty, contract regeneration, and release verification passed. No broad benchmark or CI wait.
