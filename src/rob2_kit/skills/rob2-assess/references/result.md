# Specify the Result

Use this reference before `save_proposal`.

## Result-choice invariant

Choose an exact assessable Result first. If no exact endpoint exists, choose
the closest complete non-exact assessable candidate or profile. Use unavailable
only when no complete assessable candidate exists. Missing comparator values do
not make a fully reported one-arm categorical profile unavailable: use
`single_group_category_profile`, keep all randomized arms in `target`, set
`reported.group_id` to the supported arm, and never invent comparator
categories.

## Keep the target and the report separate

Write the Result target from the researcher's request. Record what the Source reports as a separate Reported result.

The `results` array contains Result cards only. Every item starts with exactly
`kind:"assessable"` or `kind:"unavailable"`. Outputs from
`select_text_evidence` and `select_visual_evidence` are durable server state:
never place those objects in `results`, never place a figure handle under
`reported`, and never add an `evidence` field to an assessable card.

Do not repeat the user's named outcome in a Result. The server reconstructs
`requested_outcome`, `target.outcome_definition`, `target.measurement.metric`,
and `target.effect_of_interest` from the captured Intake declaration and fixed
workflow contract. Do not replace the captured request with a Source endpoint
or synonym. Keep a different Source endpoint in `reported.endpoint` and use an
explicit non-exact relation, or provide an evidence-bound unavailable result.

The Result target states:

- the measurement method;
- the time point;
- the intervention and comparator groups;
- the intended analysis population;
- the effect of interest; and
- the intended effect measure.

Use the closed target shapes exactly:

- `measurement` is `{method}`. The server supplies the captured metric; `method`
  names its definition or ascertainment, not a summary statistic such as a median.
- `time_point_or_window` is either `{kind:"described",description}` or
  `{kind:"quantified",description,value,unit}`.
- Each `comparison_groups` item is `{id,assignment}`. `assignment` describes the
  complete randomized arm, not one component of an arm.

This package implements the RoB 2 effect-of-assignment domain. The server sets
`effect_of_interest` to the exact closed value `assignment`. An intervention
name belongs in `comparison_groups`, not in an effect field.

The Reported result states:

- the Source-reported endpoint `name` and its exact `definition`;
- the population that the Source analyzed;
- the meaning of each group, row, column, or series;
- each quantity, unit, and denominator basis; and
- whether the Source reports or permits a comparative estimate.

Use one closed reported form. Every form includes `endpoint:{name,definition}`.
Set `definition` to the exact complete definition tied to that same endpoint
label in one selected passage; when no such passage exists, use `null` rather
than borrowing a component or related endpoint definition. The endpoint name
is the Source's endpoint name, not a summary statistic.
A comparative effect has `effect_measure`, `estimate`, optional `precision`,
and at least two `group_values`. A group-bound result has at least two `values`. Every group
value is `{group_id,statistic,value,unit}`; the reported group IDs must exactly
match the target group IDs. Do not send parallel quantities or group lists.

## State one Target relation

For an assessable Result, choose `exact`, `broader`, `narrower`, `component`,
or `related`. `ambiguous` and `unavailable` belong only
to an unavailable Result.

These relations are relative to the requested target. `exact` is a normalized
name match only. `broader` means the reported event, population, or time scope
is a superset of the target. `narrower` means it is a subset or has additional
restrictions; added criteria make a candidate narrower, not broader. `component`
means the reported endpoint is one constituent of a requested composite or
category. `related` means the constructs overlap but none of those ordered
relations applies.

Every non-exact assessable Result needs a `relation_rationale`. Use `exact` only
when the captured target outcome name matches the Source-reported endpoint name
after Unicode, whitespace, case, and hyphen normalization. Do not infer
synonyms. Omit `relation_rationale` for `exact`; the server derives its
deterministic rationale. A non-exact assessable relation requires a rationale
and researcher confirmation.
`ambiguous` and `unavailable` cannot enter Domain assessment.

When several endpoints may match, choose one complete candidate and submit it. If another candidate is better, revise and resubmit the complete proposal; do not send alternatives or a field patch.

When the Source has no exact endpoint label, do not stop at the first lexical
match and do not default to unavailable. Compare the Source-defined endpoint
definitions by event set, time origin or window, population, measurement, and
state criteria before extracting values. Make the closest fully reported
candidate the Result. Prefer direct event-construct wording and the fewest
added criteria over a named disease-state transition or surrogate; prefer
neither candidate merely because its name is more similar or its effect is
larger. Never infer equivalence from identical numbers. Apply the relation
definitions above and name the material differences in the rationale.

Before submitting any non-exact, related, or component Result, search beyond
the abstract, summary, or first hit into the source body and tables and compare
all complete candidates. The first valid, most salient, or easiest-to-extract
candidate is not necessarily closest. Choose the direct complete construct or
profile with the fewest added criteria; use an isolated component only as a
last resort when no complete profile or closer candidate is reported.

For a broadly requested category outcome, identify the Source's reported scope
before choosing cells: population, severity window, time window, and category
set. Prefer the trial's explicitly reported summary or prespecified profile as
the candidate. If several scopes remain plausible, choose the best complete
candidate and revise the proposal if later review selects another scope; do not
silently splice rows, grades, or time windows.

The server derives canonical Result clarity for a fully assessable card. Do not
submit a `clarity` field.

Evidence selection is durable server state. Select every premise needed by the
Result before submission, but do not add an `evidence` field to the Result card.
The server derives bindings across selected material and retains only Evidence
that supports a Result field.

## Premise audit before submission

For each Source-derived Result field, compare the proposed value with the exact
selected premise that binds it. For each non-exact relation, keep the rationale
as researcher reasoning; the server checks provenance and identity, not semantic
equivalence. Each reported endpoint field must be supported by selected
Evidence; the fields may use different selected passages. If the premise does
not entail a proof-critical reported field, revise the field, select better
Evidence, choose and resubmit a different complete candidate, or record the
Result as unavailable with a concrete missing fact. Target timing and arm
assignments require selected source support. Target method, intended
population, and intended measure are reviewer-visible interpretation fields and
do not need duplicate source quotations.

Keep endpoint definitions, time points, populations, outcome coverage,
denominators, categories, and randomized groups distinct. Treat table axes as
categories unless the Source labels them as treatment groups. Preserve complete
category sets and do not infer comparator values from a one-arm report. A
composite or related endpoint is not interchangeable with the requested target
without a researcher-visible rationale and review.

For a single-group category table reported for only one randomized arm, use
`single_group_category_profile` with that supported `group_id`; this is
assessable even when comparator values were not collected. Keep both randomized
arms in the target and do not invent comparator categories. A related endpoint
with enough data is likewise an assessable non-exact Result, not automatically
unavailable.

Set `category_axis_names` to the ordered names of the non-treatment dimensions
shared by every category cell. One name is valid for a one-dimensional profile.
Each `reported.categories[*]` value must use exactly one source-owned label in
`category_axes` for each name, in table order, such as
`["category", "level"]`. Set the shared `denominator_basis` once on the
profile. Each cell contains only its complete opaque source value (for example,
`count (percentage)`); do not invent statistic or unit labels that the selected
material does not contain. Do not submit only one axis when both are needed to
locate the value. If a source prints both counts and percentages in one cell,
preserve the complete cell value.

For an unavailable Result, every `missing_facts` item is an object with a `fact`
and one nested `basis`. Use
`{kind:"missing_reporting",evidence:"<selected handle>"}` when a Source
explicitly reports the missing input. The server retains that selection's
complete quote or transcription as the exact source premise. For a Trial with
zero captured Sources, use
`{kind:"intake_condition",code:"no_supported_sources"}` only when the
Captured Batch contains that exact Trial condition. Both forms still require
Proposal Review. A related endpoint is not a missing-reporting premise. There
is no free rationale field. If a plausible related endpoint exists, revise and
submit it as one complete assessable non-exact Result instead of declaring the
requested endpoint unavailable solely because names differ.

Completion: every Trial has one internally consistent Result card or one unavailable disposition with concrete missing-input facts and one-to-one Evidence coverage.
# Selected material and Result completeness

Select a complete sentence or complete table/figure transcription before making a
Result claim. A truncated narrative fragment cannot support fields outside its exact
quote. Every proof-critical reported leaf and source-owned arm/category label
needs one indexed Evidence binding with its exact JSON-pointer path and value
digest. A narrative Evidence item is only its server-issued handle; the handle
already resolves to the immutable page-preserving quote. Do not copy clauses or
author source-to-value mappings. Target interpretation fields, caller-owned
labels, the closed effect discriminator, and comparison-group IDs are not
Source claims and are intentionally unbound.
Figure Evidence carries server-assigned `text_corroborated` or `host_visual`
provenance. Every figure-bound leaf must occur in its literal transcription;
host-visual support is limited to visible labels, endpoint text, values, axes,
arm labels, and stated timing. Use narrative or text-corroborated Evidence for
population, analysis/measurement method, prespecification, and conduct claims.
At least one selected immutable Evidence item must also anchor an endpoint
identifier (name or definition) together with one complete quantitative result
tuple: effect measure plus estimate, or one complete group-value tuple
(statistic/value/unit) for a comparative effect; statistic/value/unit for a
group-bound value; or category axes/value for a category profile. Precision is
checked independently and is not required in the anchor. Do not splice an
endpoint from one passage with values from another.
