# Separate completion from endpoint observation in native participant flow

Implemented after the null STOP-IgAN D3 pair; **no paid model calls**.

## Trace-supported gap

The frozen pair supplied the article's study completion (76/80 and78/82), full-analysis denominators (80/82), available-case remission denominators (72/71), substitution rule and source caption as prose. Its production-helper comparison card had no drafted participant-flow rows. The prototype equated completion with endpoint observation despite contrary source information.

Native rob2-kit already represented Result-bound randomized, observed, analyzed, imputed, excluded and event counts, with exact source references and explicit unknowns. Its preview could reconcile those facts before a question answer. However, **study/follow-up completion had no typed count field**, and the flattened participant-flow view dropped the row's existing outcome-status/censoring semantics. Completion had to remain narrative or be misclassified into another quantity. This is a concrete representational gap, not proof that all source distinctions were absent or that adding a checklist would solve inference.

## Resulting behavior

`MissingDataRow.completed` now accepts a source-reported study/follow-up completion count. The existing preview, saved Domain answer, comparison card, canonical reconciliation and both bundle verifiers retain it. The card exposes a distinct `completed` stage with the same arm/population/unit/time/Result binding and source/page/line references. The existing row semantics also survive flattening into participant flow. There is no second ledger or copied evidence store: cited Evidence and its source recovery retain the original text.

Missing arithmetic still uses only explicit `randomized` and `observed`. Completion is never substituted for observation, analysis inclusion or imputation. Endpoint observations may outnumber study completers. When only completion/analysis/censoring is established, observed counts and exact missing counts stay unknown. Separate counts do not establish their overlap, an outcome-dependent mechanism, a signalling answer or a risk label. Continuous participant-measurement counts remain separate from study attendance; time-to-event censoring and event counts remain metadata, not a converted observation fraction.

Completion discrepancies are retained as source-report conflicts. Their absence/presence does not automatically change the availability proposition. Rows without the optional new field retain their existing serialized shape. The shared `ParticipantFlowKind` type now defines the public projection kinds, replacing its duplicated enum. Public schema hashes were regenerated; the scientific pack, official guidance, allowed answers, activation rules and algorithms are unchanged.

The D3 workflow reference now identifies how to use the existing source-fact preview before applying official questions when completion and availability coexist. This is procedural separation, with no new threshold or mandatory scientific certainty gate. Source interpretation remains the host's responsibility; successful source binding does not establish entailment.

## Existing activation gate

Native save already resolves the dependency-closed path and returns `answers_must_match_active_questions` with missing IDs before commitment. After3.1NI/3.2N/3.3NI,3.4 is active; it cannot be silently committed missing. Inactive extras are ignored. No runtime activation gate was added or changed to compensate for the earlier tool-free response.

## Offline evidence

- Neutral fixtures cover fully observed outcomes despite incomplete attendance; complete analysis with imputed/missing outcomes; complete follow-up as an insufficient endpoint-observation proxy; unknown overlap; continuous measurements; administrative versus loss-to-follow-up censoring; and retained completion conflicts.
- A native MCP preview/save/read round-trip verifies no preview revision change, preserved unknown observation, Result/arm binding, source coordinates and censoring semantics. It checks interface preservation, not scientific entailment of a synthetic citation.
- Both canonical verifiers accept legitimate completion conflicts and reject their removal. Existing historical bundle integrity tests pass.
- The original **Code benchmark** STOP-IgAN and PIONEER-6 bundles still pass independent verification with unchanged bytes; see `existing-case-preservation.json`.

Verification records include the initial test-argument error and corrected result. No new source facts were automatically extracted, no preferred answers/trial names/thresholds entered runtime, and no accuracy gain or production-model benefit is claimed. A future authorized native diagnostic must test whether the host actually records and uses the separated facts; another tool-free prose-only run would not establish that behavior.
