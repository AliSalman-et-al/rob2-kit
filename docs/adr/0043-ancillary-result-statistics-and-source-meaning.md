# Preserve ancillary statistics without fabricating an effect estimate

Status: accepted

## Context

Paired source group summaries can report a comparison p-value without a comparative point estimate. The v0.11 input has no structured place for that statistic: using precision rejects a group-only candidate, while entering an arm median as an effect can pass literal binding. Null printed units/statistic labels also force unclear table meaning even when inspected definitions establish scientific meaning. Literal support does not prove that periods are randomized arms or that related outcomes satisfy the shared request.

## Decision

The v0.12 public contract adds one optional `reported_statistics` collection of literal source expressions to comparative-effect and group-value Results. Effect intervals remain in precision; ancillary statistics do not require or supply a missing effect estimate. They must bind to selected same-Trial Evidence and the endpoint/quantitative anchor. Empty collections are omitted from canonical serialization, preserving existing record shapes and identities. The field is available in recovery, review and export; review displays all numerical roles together.

Scientific meaning and printed labels remain distinct. Null unit/statistic literals stay null and do not assert dimensionless or known scientific meaning. They no longer mechanically force an unclear scientific facet. The host must justify interpretation from inspected definitions, scales, headers or methods, preserve genuine uncertainty/conflicts, and never invent a printed label. Exactness still requires the existing explicit scope facets; binding is provenance, not an entailment judgment.

Preserve the shared request verbatim, distinguish its explicit constraints from each trial's selected reported endpoint, window, population and randomized comparison, and compare materially plausible source candidates. Resolve material ambiguity with concrete alternatives before final approval, without ceremonial questions about absent details that do not affect identity. Do not substitute composites/components, recurrence-free/overall survival, landmarks/time-to-event effects or exposure periods/randomized assignments based on name similarity. Reuse existing scope rationale, clarity, unknowns and source passages rather than adding a numerical ontology or a duplicate intent model.

## Compatibility and limits

Result semantics advances prospectively to v0.11; package/public contract to v0.12.0. Both verifiers retain exact historical descriptor pins and apply historical null-label restrictions under their original semantics. They reject the new statistics field under old semantics. No approved identity, historical record, Evidence or frozen evaluation is rewritten. Existing records without ancillary statistics retain their serialization; revised statistics change the Result identity and use the existing scoped proposal review/invalidation route. The immutable human approval boundary is unchanged.

This amends the printed-label clarity rule and reported observations in ADR0037. It does not introduce partial assessable Results, remove comparative completeness, or claim deterministic semantic equivalence. The supplied-source model and meaningful researcher review still establish scientific correspondence. Archived failures and targeted revised-build continuations remain distinct; no paid inference is authorized by this ADR.
