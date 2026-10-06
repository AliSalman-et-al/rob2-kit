# Direct unavailable-outcome counts

Both preserved DAPA-HF assessments submitted the reported incomplete primary-endpoint follow-up counts as censoring metadata, with `observed: null`. Storage preserved those counts. Reconciliation then generated bounds from zero to the whole randomized population, because it recognizes only positive observed counts for exact missingness. This is a construction gap: the input has no direct negative availability quantity, so a reported unavailable count requires manufacturing its complementary observed count or relegating it to a different quantity role.

The optional `unavailable` participant-flow quantity represents a reported total with unavailable data for the selected outcome, population and window. With a compatible randomized count it produces exact missingness without synthesizing `observed`. It is visible with its Evidence coordinates in production comparison cards and checked independently in canonical verification. Existing rows without this field retain their arithmetic and shape; replay of 24 rows across 11 preserved states matched the pre-change implementation exactly. Original assessments and all source bytes remain untouched.

The field does not classify a source sentence. An assessor must establish that the report's definition concerns the selected endpoint. Generic censoring, treatment discontinuation and visit completion do not populate it. Conflicting observed/unavailable totals are retained without emitting a derived exact count. No signalling response, threshold or risk judgment follows from this quantity.

For the motivating case, original Code benchmark commit d04473df4a07a3117f3171df2d8471ec0defd522 contains the exact sources:

- Main report NEJMoa1911303.pdf, physical page 3 Figure 1: 14/2373 and 20/2371 incomplete primary-outcome follow-up. The two unknown vital statuses must not be added without resolving overlap.
- Protocol/SAP nejmoa1911303_protocol.pdf, physical page 211 lines 8–20 of the frozen projection: complete primary-endpoint follow-up includes a primary event, non-CV death or complete assessment at/after the primary analysis cutoff. Known vital status alone does not establish endpoint completeness.
- Official Cochrane pack, full guidance page 45, Box 8 question 3.3: loss during time-to-event follow-up represents missing outcome data even if earlier follow-up contributes to analysis. This is distinct from complete administrative censoring or follow-up ending after the first observed event.

Unknown event times and loss reasons remain separate uncertainties. The count does not claim that subsequent event times have been observed. The source-specific completeness definition is needed before using an incomplete-follow-up count as unavailable outcomes; the code does not equate the two automatically.

Generic offline controls cover an event preceding later loss, known competing death, loss before first event, complete administrative censoring and unknown overlap. Additional controls preserve incompatible reports, prevent invented observed counts, check conflicting reports and reject tampering in both verifiers. A real MCP client checks the new quantity and its source passages in the paged comparison-card preview.

This is a representation improvement, not demonstrated behavioral or accuracy improvement. No paid rerun, reference-label tuning, full benchmark or merge is part of this checkpoint. A later experiment must test whether the assessor actually uses the source-specific definition to preserve known availability extent, while retaining the contrasting censoring cases above.
