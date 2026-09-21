# Assess selection of the reported result

Use this reference for Domain 5. The approved Result is fixed; do not switch to
an easier endpoint. The returned question cards are authoritative.

## Establish the analysis plan

Identify the exact planned intervention comparison, cohort, outcome measurement,
definition, time point or window, population, analysis, and effect measure.
Establish that the plan was finalized
before unblinded outcome data were available, or that later changes were
unrelated to the results. Then compare the plan with the approved reported
Result.

Use captured Source provenance to locate the applicable plan passages. The
active comparison card lists every captured Source, including supplements and
combined protocol documents with no selected passages. Compare
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

Keep original and amended plans distinct, with source-located content and
chronology. Keep record posting, record update, retrieval, plan finalization,
recruitment, and unblinded access dates distinct. A registry's first-posted date
does not date the endpoint content in its current record; current registry content
does not establish unseen historical intent. A data cutoff is not
investigator unblinding.

The selected plan passage establishes plan content. A registry identifier,
endpoint label, or report-level prespecification claim alone leaves plan timing
and correspondence unresolved. A probable answer still needs a stated basis for
the timing judgment; the report's "a priori" label alone does not supply it.
For a platform trial, establish that the plan applies to the approved intervention
comparison and cohort. An embedded SAP can supply plan Evidence when its scope
and chronology match the Result; an absent or ambiguous plan preserves
legitimate uncertainty. A protocol or SAP
describes intent; check the report for what was actually done.

If the plan is unavailable after bounded source-specific discovery, record that
information limit. Missing plans do not prove selective reporting.
Keep unknown dates and historical applicability explicit. Use captured versions
and exact recovery windows. Use only captured Sources for this assessment. A
current record cannot stand in for an unseen past version.

For an unresolved plan premise, search with concrete wording from the report or
plan (for example, the endpoint label, analysis population, time point, or
section heading). Continue an existing cursor when deeper cached results may
contain the plan. Issue another bounded query or widen the Source scope only
when it could resolve the premise. Read the complete returned window, including
its date and cohort context, before treating it as a plan passage. Stop on a
complete applicable comparison or document the bounded information limit with
an explicit stopping rationale and, when useful, the current search receipt. A
Source role or an empty passage list cannot establish either plan presence or
plan absence.

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
absence of alternatives. For multiple eligible analyses, reporting adjusted,
unadjusted, complete-case, imputed, or survival analyses establishes
multiplicity, not result-driven selection. For a non-exact Result, compare the
exact approved definition and relation rationale with the plan; do not silently
assess a more convenient planned endpoint. Preserve Low, Some concerns, High,
or legitimate No information according to the evidence path rather than forcing
a severity category when applicability or chronology is unresolved.
