# Assess selection of the reported result

Use this reference for Domain 5. The approved Result is fixed; do not switch to
an easier endpoint. The returned question cards are authoritative.

## Establish the analysis plan

Identify the exact planned outcome measurement, definition, time point,
population, analysis, and effect estimate. Establish that the plan was finalized
before unblinded outcome data were available, or that later changes were
unrelated to the results. Then compare the plan with the approved reported
Result.

Use captured Source provenance to locate the applicable plan passages. Compare
their version, date, intervention groups, and cohort with the approved Result.
In `comparison_cards[].passage_groups`, inspect the Source label, role, logical
path, page count, and content and projection hashes. A protocol, SAP, or registry
group may have no selected passages yet. Use the Source to resolve missing
premises; an empty passage list does not establish absent plan content.
`source_origin`, `registry_url`, and `registry_retrieved_at` describe captured
provenance; they do not establish when a plan was finalized or which Trial
comparison it covered.

For a registry group with `registry_recovery`, call `read_pages` with that
object's `trial_id` and `windows`. Inspect the captured fields identified by
`registry_field_paths`. These are navigation paths into the immutable projection,
not a historical plan or an applicability judgment. `windows` contains at most
20 windows; `registry_window_count` reports the total. If more remain, navigate
the captured Source using its page count and `search_sources` with the field
paths. Refreshing context does not advance these registry windows. For omitted selected
passages, follow [Recover omitted Evidence](evidence.md#recover-omitted-evidence).

Keep record posting, record update, retrieval, plan finalization, recruitment,
and unblinded access dates distinct. A registry's first-posted date does not
date the endpoint content in its current record.

The selected plan passage establishes plan content. A registry identifier,
endpoint label, or report-level prespecification claim alone leaves plan timing
and correspondence unresolved. A probable answer still needs a stated basis for
the timing judgment; the report's "a priori" label alone does not supply it.
For a platform trial, establish that the plan applies to the approved intervention
comparison and cohort. A protocol or SAP
describes intent; check the report for what was actually done.

If the plan is unavailable after bounded source-specific discovery, record that
information limit. Missing plans do not prove selective reporting.
Keep unknown dates and historical applicability explicit. Use captured versions
and exact recovery windows. Obtain historical material only through a supported
source-capture action; a current record cannot stand in for an unseen past version.

## Separate the two selection mechanisms

For eligible outcome measurements, compare alternative scales, definitions,
thresholds, time points, or assessors. Ask whether only a subset was fully
reported and whether selection was likely based on the results.

For eligible analyses, compare alternative adjustment sets, transformations,
models, composite definitions, censoring rules, missing-data methods,
populations, or effect estimates. Apply the same selection question separately.

For 5.3, identify both the eligible alternatives and evidence that reporting
favoured a subset because of its results. Reporting ITT, per-protocol, imputed,
and survival analyses together establishes multiplicity, not that selection
occurred. An inability to rule out selection does not support Yes/Probably Yes.
When intentions are insufficiently detailed and multiple analyses were possible,
use No information unless other evidence resolves the selection question.

A detailed reported endpoint or estimate proves neither prespecification nor the
absence of alternatives. For a non-exact Result, compare the exact approved
definition and relation rationale with the plan; do not silently assess a more
convenient planned endpoint.
